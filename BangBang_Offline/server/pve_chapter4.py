"""Reviewed chapter-four progression. Geometry/assets must be published separately."""
import math
from combat_math import D
from pve_balance import hp_for
from pve_chapter1 import remove_objects,_inside
from pve_movement import patrol_goal as _patrol,move
from pve_chapter2 import records,stop_points,respawn_position,_remove_actor
from pve_support import MAPS,SUPPORT,allies,cast_support,explode

STAGES={701:(1,2,3,4,5),702:(1,2,3,4),703:(1,2)}
DECOR=(1350,1351,1353,2612,2613,2673,2676)
BOSSES={304:1331,306:1332,702:2641,703:2610}
TANKS305=(1321,1322,1323,1324)
FACTORIES305=(33,34,35,36)
SWITCH_RADIUS=96  # Approved reachable approach to the authored controller.


def objective(rec,tpl):
    if rec['map']==703 and rec['point']==105:return False  # Approved: no activation command survives.
    if rec['map']==305:return rec['repeat']==0 and tpl in TANKS305
    return rec['camp']==0 and rec['repeat']>=0 and tpl not in DECOR


def initialize(arena):
    total=D(0)
    for rec in records(arena):
        for tpl in rec['templates']:
            if not objective(rec,tpl):continue
            total+=hp_for(arena,tpl)*(rec['repeat']+1)
    arena.pk['pve'].update(stage=0,damage_total=total,active_rules=[],stopped_rules=[],zone_done=[],
        rescued=[],started=False,hazards=[],rule_kills={},boss_kills=0,laser_disabled=False)


def schedule(arena,rec,now):
    if rec['map']==703 and rec['point']==105:return
    pve=arena.pk['pve']
    if rec['index'] in pve['active_rules'] or rec['index'] in pve['stopped_rules']:return
    pve['active_rules'].append(rec['index'])
    for n,tpl in enumerate(rec['templates']):
        if tpl==2613:continue  # Controller position is handled by the solo mechanism.
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,
            remaining=0 if tpl in DECOR else rec['repeat'],loop=tpl not in DECOR and rec['repeat']<0,
            spawn_due_at=now+(max(0,rec['delay'])+n*max(1,rec['interval']))*1000))


def stop(arena,points):
    ids={r['index'] for r in records(arena) if r['point'] in points}
    arena.pk['pve']['stopped_rules']=sorted(set(arena.pk['pve']['stopped_rules'])|ids)
    stop_points(arena,points)


def scripts(arena,script,now):
    packets=[]
    for kind,arg,_,_ in script:
        if kind==4:packets+=remove_objects(arena,(arg,))
        elif kind==5:stop(arena,(arg,))
        elif kind==7:
            for rec in records(arena):
                if rec['point']!=arg or rec['delay']>=0:continue
                if arena.geometry.id in STAGES and rec['wave'] and rec['wave']!=arena.pk['pve']['stage']:continue
                schedule(arena,rec,now)
    return packets


def object_destroyed(arena,obj,now):
    rec=next((r for r in arena.geometry.data['npcs'] if ((3<<26)|r['instance'])==obj.id),None)
    return scripts(arena,rec.get('pve_scripts',()),now) if rec else []


def stage(arena,wave,now):
    pve=arena.pk['pve'];old=pve['stage'];pve['stage']=wave
    for rec in records(arena):
        if rec['wave']==old and old and rec['repeat']<0:stop(arena,(rec['point'],))
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
    if tpl in (1350,1351,2612,2673):actor.turret_next_shot_at=now+(500 if tpl==2612 else 5000)
    arena.actors[actor.id]=actor;packets=[actor.snapshot(now)]
    if tpl==2619:packets+=actor._buff(50316,now)
    return packets


def death(arena,actor,now):
    pve=arena.pk['pve'];tpl=actor.info['npc_template'];rec=records(arena)[actor.info['pve_rule']]
    if actor.camp!=1 and tpl not in DECOR:arena.pk['stats'][1][2]+=1
    pve['rule_kills'][rec['index']]=pve['rule_kills'].get(rec['index'],0)+1
    if rec['index'] in pve['active_rules'] and (actor.info['pve_loop'] or actor.info['pve_remaining']>0):
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,loop=actor.info['pve_loop'],
            remaining=max(0,actor.info['pve_remaining']-1),spawn_due_at=now+max(1,rec['interval'])*1000))
    if tpl==BOSSES.get(arena.geometry.id):
        pve['boss_kills']+=1
        if arena.geometry.id in (304,306):return finish(arena,now)
        if arena.geometry.id==702:
            pve['spawns']=[];pve['active_rules']=[]
    return []


def finish(arena,now):
    from pve_rules import finish as win
    arena.pk['pve']['spawns']=[];arena.pk['pve']['active_rules']=[]
    return win(arena,now,True)


def mechanisms(arena,now):
    pve=arena.pk['pve'];p=arena.player;packets=[];present=p.alive and not p.in_stasis()
    if arena.geometry.id==703 and present and not pve['laser_disabled'] and math.dist(p.position_at(now),(540,2820))<=SWITCH_RADIUS:
        pve['laser_disabled']=True;stop(arena,(145,146))
        for a in list(arena.actors.values()):
            if a.alive and a.info.get('npc_template') in (2612,2613):packets+=_remove_actor(a)
    for a in list(arena.actors.values()):
        if not a.alive or not a.info.get('pve_npc'):continue
        tpl=a.info['npc_template'];pos=a.position_at(now)
        if tpl==1353 and present and math.dist(p.position_at(now),pos)<=72:
            pve['rescued'].append(a.info['pve_rule']);packets+=_remove_actor(a)
        elif tpl in (1350,1351,2612,2673) and now>=a.turret_next_shot_at:
            a.turret_next_shot_at=now+(500 if tpl==2612 else 5000)
            dx,dy={1350:(-360,0),1351:(360,0),2612:(300,0),2673:(0,-360)}[tpl]
            packets+=a._shot((pos[0]+dx,pos[1]+dy),now)
            if arena.pk['finished']:return packets
    return packets


def ai(arena,now):
    from bot_ai import observable,stop as stop_tank
    if arena.pk['finished']:return []
    packets=[]
    for actor in list(arena.actors.values()):
        tpl=actor.info.get('npc_template')
        if not actor.alive or not actor.info.get('pve_npc') or tpl in DECOR and tpl!=2676:continue
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
            if actor.shot_skill==1000057:
                healed=cast_support(actor,now);packets+=healed
                brain['goal']=pos if healed else _patrol(arena,actor,now)
            elif actor.shot_skill in (1000060,1000061):
                if target:packets+=cast_support(actor,now)
                brain['goal']=_patrol(arena,actor,now)
            elif tpl in (1354,2676):
                brain['goal']=_patrol(arena,actor,now)
                if target and math.dist(pos,target.position_at(now))<=(144 if tpl==1354 else 72):
                    if tpl==1354:packets+=explode(actor,now)
                    elif not actor.blocked('attack',now) and now>=actor.cooldowns[0]:
                        actor.cooldowns[0]=now+1000;packets+=actor._shot(target.position_at(now),now,target)
            elif target:
                dest=target.position_at(now);near=math.dist(pos,dest)<=actor.pve_fire_range
                brain['goal']=pos if near else dest
                if near:packets+=stop_tank(actor,now)+actor.cast(0,pos,dest,target.id,now)
            else:brain['goal']=_patrol(arena,actor,now)
        if arena.pk['finished']:break
        packets+=move(arena,actor,brain,now)
        if arena.pk['finished']:break
    return packets


def completed(arena,rec):
    if rec['index'] in arena.pk['pve']['stopped_rules']:return True
    expected=sum(objective(rec,t) for t in rec['templates'])*(rec['repeat']+1)
    return arena.pk['pve']['rule_kills'].get(rec['index'],0)>=expected


def tick(arena,now):
    from pve_hazards import initialize as init_hazards,tick as hazard_tick
    pve=arena.pk['pve'];mid=arena.geometry.id;packets=[]
    if not pve['started']:
        pve['started']=True
        packets+=stage(arena,1,now)
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
    if mid in STAGES and pve['stage']<STAGES[mid][-1]:
        if all(completed(arena,r) for r in records(arena) if r['wave']==pve['stage']):
            packets+=stage(arena,pve['stage']+1,now)
    if mid in (701,703) and pve['stage']==STAGES[mid][-1]:
        if all(completed(arena,r) for r in records(arena)):
            packets+=finish(arena,now)
    elif mid==702 and pve['boss_kills']:
        if not any(a.alive and a.info.get('pve_npc') and a.camp==0 and a.info['npc_template'] not in DECOR for a in arena.actors.values()):
            packets+=finish(arena,now)
    elif mid==305:
        if (all(not arena.actors[(3<<26)|i].alive for i in FACTORIES305) and
                not any(a.alive and a.info.get('npc_template') in TANKS305 for a in arena.actors.values())):
            packets+=finish(arena,now)
    return packets
