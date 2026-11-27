"""User-reviewed chapter-three objectives. Not enabled until assets are published."""
import math
from combat_math import D
from pve_balance import hp_for
from pve_chapter1 import remove_objects,_inside
from pve_chapter2 import records,stop_points,respawn_position,_remove_actor

MAPS=(404,405,406,301,302,303)
STAGES={404:(1,2,3,4,5,6),405:(1,2,3,4,5),406:(1,2,3,4)}
DECOR=(1409,1414,1416,1440,353,342)
GOALS={405:{1437:2},406:{1430:1},301:{322:4},302:{346:4},303:{347:1,359:1}}
GUN_CLAIM_RADIUS=100  # Gun15's nearest legal mainland pose is 98.95px away.
SWITCH_RADIUS=96  # The closed door separates the nearer walkable pocket.


def objective(rec,tpl):
    return rec['camp']!=1 and rec['repeat']>=0 and tpl not in DECOR and (
        rec['camp']==0 or rec.get('map')==405 and tpl in (1408,1421,1437))


def initialize(arena):
    total=D(0)
    for rec in records(arena):
        for tpl in rec['templates']:
            if not objective(rec,tpl):continue
            total+=hp_for(arena,tpl)*(rec['repeat']+1)
    arena.pk['pve'].update(stage=0,damage_total=total,active_rules=[],zone_done=[],open_doors=[],
        rescued=[],goal_kills={},claimed_guns=[],started=False,hazards=[])


def schedule(arena,rec,now,*,triggered=False):
    pve=arena.pk['pve']
    if rec['index'] in pve['active_rules']:return
    pve['active_rules'].append(rec['index'])
    delay=abs(rec['delay']) if triggered and arena.geometry.id==406 and rec['delay']<-1 else max(0,rec['delay'])
    for n,tpl in enumerate(rec['templates']):
        if tpl in (1416,1440):continue
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,
            remaining=0 if tpl in DECOR else rec['repeat'],loop=tpl not in DECOR and rec['repeat']<0,
            spawn_due_at=now+(delay+n*max(1,rec['interval']))*1000))


def scripts(arena,script,now):
    packets=[]
    for kind,arg,_,_ in script:
        if kind==4:packets+=remove_objects(arena,(arg,))
        elif kind==5:stop_points(arena,(arg,))
        elif kind==7:
            for rec in records(arena):
                if rec['point']!=arg or rec['delay']>=0:continue
                # Allied guns are claimed by proximity, not a hidden stage command.
                if rec['camp']==1 and 1432 in rec['templates']:continue
                if rec['wave'] and rec['wave']!=arena.pk['pve']['stage'] and arena.geometry.id in STAGES:continue
                schedule(arena,rec,now,triggered=True)
    return packets


def object_destroyed(arena,obj,now):
    rec=next((r for r in arena.geometry.data['npcs'] if ((3<<26)|r['instance'])==obj.id),None)
    return scripts(arena,rec.get('pve_scripts',()),now) if rec else []


def stage(arena,wave,now):
    pve=arena.pk['pve'];old=pve['stage'];pve['stage']=wave
    # Cancel old phase repeat schedules, retaining already spawned enemies.
    for rec in records(arena):
        if rec['wave']==old and rec['wave'] and rec['repeat']<0:stop_points(arena,(rec['point'],))
    for rec in records(arena):
        if rec['wave']==wave and rec['delay']>=0:schedule(arena,rec,now)
    packets=[]
    for rec in arena.geometry.data['pve_waves']:
        if rec['fields']==wave:packets+=scripts(arena,rec['scripts'],now)
    return packets


def spawn(arena,event,now):
    from pve_npc import PveNpc
    rec=records(arena)[event['rule']];tpl=event['template']
    info=dict(point=rec['point'],npc_template=tpl,pve_rule=rec['index'],pve_loop=event['loop'],
        pve_remaining=event['remaining'],pve_logic=rec['logic'],pve_unscored=not objective(rec,tpl))
    actor=PveNpc(arena,arena.new_id(5),info,rec['camp'],tuple(rec['position']))
    if tpl==342:actor.turret_next_shot_at=now+5000
    arena.actors[actor.id]=actor
    return [actor.snapshot(now)]


def death(arena,actor,now):
    pve=arena.pk['pve'];tpl=actor.info['npc_template'];rec=records(arena)[actor.info['pve_rule']]
    if actor.camp!=1 and tpl not in DECOR:arena.pk['stats'][1][2]+=1
    if rec['index'] in pve['active_rules'] and (actor.info['pve_loop'] or actor.info['pve_remaining']>0):
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,loop=actor.info['pve_loop'],
            remaining=max(0,actor.info['pve_remaining']-1),spawn_due_at=now+max(1,rec['interval'])*1000))
    goals=GOALS.get(arena.geometry.id,{})
    if tpl in goals and not actor.info['pve_loop']:
        pve['goal_kills'][tpl]=pve['goal_kills'].get(tpl,0)+1
        if all(pve['goal_kills'].get(t,0)>=count for t,count in goals.items()):
            from pve_rules import finish
            pve['spawns']=[];pve['active_rules']=[]
            return finish(arena,now,True)
    return []


def mechanisms(arena,now):
    pve=arena.pk['pve'];player=arena.player;packets=[];pos=player.position_at(now)
    present=player.alive and not player.in_stasis()
    for actor in list(arena.actors.values()):
        if not actor.alive or not actor.info.get('pve_npc'):continue
        tpl=actor.info['npc_template']
        if tpl in (1409,353) and present and math.dist(pos,actor.position_at(now))<=72:
            pve['rescued'].append(actor.info['pve_rule']);packets+=_remove_actor(actor)
        elif tpl==342 and now>=actor.turret_next_shot_at:
            actor.turret_next_shot_at=now+5000
            x,y=actor.position_at(now);packets+=actor._shot((x,y-360),now)
            if arena.pk['finished']:return packets
    if not present:return packets
    if arena.geometry.id==405 and pve['stage']==2:
        for point in (14,15):
            rec=next(r for r in records(arena) if r['point']==point and 1432 in r['templates'])
            if point in pve['claimed_guns'] or math.dist(pos,rec['position'])>GUN_CLAIM_RADIUS:continue
            enemy_rules={r['index'] for r in records(arena) if r['point']==point and 1427 in r['templates']}
            if any(s['rule'] in enemy_rules for s in pve['spawns']) or any(a.alive and a.info.get('pve_rule') in enemy_rules for a in arena.actors.values()):continue
            pve['claimed_guns'].append(point);schedule(arena,rec,now,triggered=True)
    if arena.geometry.id==406 and 48 not in pve['open_doors']:
        switch=next(r for r in records(arena) if 1416 in r['templates'])
        if math.dist(pos,switch['position'])<=SWITCH_RADIUS:
            pve['open_doors'].append(48)
            for actor in list(arena.actors.values()):
                if actor.alive and actor.info.get('npc_template')==1414:packets+=_remove_actor(actor)
            pve['spawns']=[s for s in pve['spawns'] if s['template']!=1414]
            from map_objects import rebuild_geometry
            rebuild_geometry(arena)
    return packets


def ai(arena,now):
    from bot_ai import observable,stop
    from pve_movement import patrol_goal as _patrol,move
    if arena.pk['finished']:return []
    packets=[]
    for actor in list(arena.actors.values()):
        if not actor.alive or not actor.info.get('pve_npc') or actor.info['npc_template'] in DECOR:continue
        brain=arena.bot_brains.setdefault(actor.id,dict(path=[],notice_at=0))
        from pve_boss_tactics_v2 import tick as remaining_boss_tick
        tactical = remaining_boss_tick(actor, brain, now)
        if tactical is not None:
            packets += tactical
            if arena.pk['finished']: break
            continue
        from pve_tactics import tick as tactical_tick
        tactical = tactical_tick(actor, brain, now)
        if tactical is not None:
            packets += tactical
            if arena.pk['finished']: break
            continue
        if now>=brain['notice_at']:
            brain['notice_at']=now+200;pos=actor.position_at(now)
            brain['pve_patrolling']=False
            target=min((a for a in arena.actors.values() if not a.info.get('map_object') and
                not a.info.get('pve_hostage') and observable(arena,actor,a,now,600)),
                key=lambda a:(math.dist(pos,a.position_at(now)),a.id),default=None)
            if target:
                dest=target.position_at(now);in_range=math.dist(pos,dest)<=actor.pve_fire_range
                brain['goal']=pos if in_range else dest
                if in_range:packets+=stop(actor,now)+actor.cast(0,pos,dest,target.id,now)
            else:brain['goal']=_patrol(arena,actor,now)
        if arena.pk['finished']:break
        packets+=move(arena,actor,brain,now)
        if arena.pk['finished']:break
    return packets


def tick(arena,now):
    from pve_hazards import initialize as init_hazards,tick as hazard_tick
    from pve_rules import finish
    pve=arena.pk['pve'];mid=arena.geometry.id;packets=[]
    if not pve['started']:
        pve['started']=True
        if mid in STAGES:packets+=stage(arena,1,now)
        for rec in records(arena):
            if rec['wave']==0 and rec['delay']>=0:schedule(arena,rec,now)
        packets+=init_hazards(arena,airstrikes=True)
    if arena.player.alive and not arena.player.in_stasis():
        for index,zone in enumerate(arena.geometry.data['pve_zones']):
            if index in pve['zone_done'] or not _inside(arena.player.position_at(now),zone['fields']):continue
            pve['zone_done'].append(index);packets+=scripts(arena,zone['scripts'],now)
    waiting=pve['spawns'];pve['spawns']=[]
    for event in waiting:
        if now>=event['spawn_due_at']:packets+=spawn(arena,event,now)
        else:pve['spawns'].append(event)
    packets+=mechanisms(arena,now)
    if arena.pk['finished']:return packets
    packets+=hazard_tick(arena,now)
    if arena.pk['finished']:return packets
    packets+=ai(arena,now)
    if arena.pk['finished']:return packets
    if mid in STAGES:
        enemies=any(a.alive and a.info.get('pve_npc') and not a.info['pve_unscored'] for a in arena.actors.values())
        waiting=any(objective(records(arena)[s['rule']],s['template']) for s in pve['spawns'])
        if not enemies and not waiting:
            wave=pve['stage'];stages=STAGES[mid]
            if mid==405 and wave==2 and len(pve['claimed_guns'])<2:return packets
            if wave<stages[-1]:packets+=stage(arena,stages[stages.index(wave)+1],now)
            elif mid==404:packets+=finish(arena,now,True)
    return packets
