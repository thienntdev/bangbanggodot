"""Normal chapter seven: authored ambush zones and explicit solo objectives."""
import math
from combat_math import D
from pve_chapter1 import remove_objects, _inside
from pve_movement import patrol_goal as _patrol, move
from pve_chapter2 import records, respawn_position
from pve_chapter4 import stop, finish
from pve_balance import hp_for

BOSSES = {31201:3120106, 31202:3120209, 31203:3120309,
          31302:3130209, 31303:3130313}
LASERS = {3130210:(-360,0), 3130211:(360,0)}
SAWS = (3130108,)
DECOR = (*LASERS, *SAWS)
CROSSINGS = {31302:((348,324),(468,324))}
CROSSING_RADIUS = 24


def objective(rec, tpl):
    return rec['camp']==0 and rec['repeat']>=0 and tpl not in DECOR


def initialize(arena):
    total=sum((hp_for(arena,t)*(r['repeat']+1) for r in records(arena)
               for t in r['templates'] if objective(r,t)), D(0))
    arena.pk['pve'].update(stage=0,damage_total=total,active_rules=[],stopped_rules=[],
        zone_done=[],started=False,hazards=[],rule_kills={},boss_kills=0,crossing_latched=False)
    from pve_local_late import initialize as local_initialize
    local_initialize(arena)


def schedule(arena, rec, now):
    pve=arena.pk['pve']
    if rec['index'] in pve['active_rules'] or rec['index'] in pve['stopped_rules']:return
    pve['active_rules'].append(rec['index'])
    for n,tpl in enumerate(rec['templates']):
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,remaining=rec['repeat'],
            loop=rec['repeat']<0,spawn_due_at=now+(abs(rec['delay'])+n*max(1,rec['interval']))*1000))


def scripts(arena, script, now):
    packets=[]
    for kind,arg,_,_ in script:
        if kind==4:packets+=remove_objects(arena,(arg,))
        elif kind==5:stop(arena,(arg,))
        elif kind==7:
            for rec in records(arena):
                if rec['point']==arg and rec['delay']<0:schedule(arena,rec,now)
    return packets


def object_destroyed(arena,obj,now):
    rec=next((r for r in arena.geometry.data['npcs'] if ((3<<26)|r['instance'])==obj.id),None)
    return scripts(arena,rec.get('pve_scripts',()),now) if rec else []


def spawn(arena,event,now):
    from pve_npc import PveNpc
    rec=records(arena)[event['rule']];tpl=event['template']
    info=dict(point=rec['point'],npc_template=tpl,pve_rule=rec['index'],pve_loop=event['loop'],
              pve_remaining=event['remaining'],pve_logic=rec['logic'],pve_unscored=not objective(rec,tpl))
    actor=PveNpc(arena,arena.new_id(5),info,rec['camp'],tuple(rec['position']))
    arena.actors[actor.id]=actor;packets=[actor.snapshot(now)]
    if tpl in LASERS:actor.turret_next_shot_at=now+actor.fire_interval(now)
    if tpl==3130313:
        packets+=actor._buff(10001091,now)
        actor._queue(now+500,'pve_plague',actor.generation)
    return packets


def death(arena,actor,now):
    if actor.info.get('pve_local_forklift'):return []
    pve=arena.pk['pve'];tpl=actor.info['npc_template'];rec=records(arena)[actor.info['pve_rule']]
    if actor.camp!=1 and tpl not in DECOR:arena.pk['stats'][1][2]+=1
    pve['rule_kills'][rec['index']]=pve['rule_kills'].get(rec['index'],0)+1
    if rec['index'] in pve['active_rules'] and (actor.info['pve_loop'] or actor.info['pve_remaining']>0):
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,loop=actor.info['pve_loop'],
            remaining=max(0,actor.info['pve_remaining']-1),spawn_due_at=now+max(1,rec['interval'])*1000))
    if tpl==BOSSES.get(arena.geometry.id):
        pve['boss_kills']+=1
        if tpl==3120209:
            from pve_local_late import forklift_defeated
            packets=forklift_defeated(arena,actor,now)
            if packets is not None:return packets
        return finish(arena,now)
    return []


def completed(arena,rec):
    expected=sum(objective(rec,t) for t in rec['templates'])*(rec['repeat']+1)
    return arena.pk['pve']['rule_kills'].get(rec['index'],0)>=expected


def zone_fields(arena,zone):
    return zone['fields']


def crossing(arena,now):
    from pve_chapter5 import crossing as native_crossing
    return native_crossing(arena,now,ends=CROSSINGS.get(arena.geometry.id,()))


def mechanisms(arena,now):
    from pve_local_late import forklift_tick
    packets=forklift_tick(arena,now)
    if arena.pk['finished']:return packets
    for actor in list(arena.actors.values()):
        tpl=actor.info.get('npc_template')
        if not actor.alive or tpl not in LASERS or now<actor.turret_next_shot_at:continue
        pos=actor.position_at(now);dx,dy=LASERS[tpl];dest=(pos[0]+dx,pos[1]+dy)
        actor.turret_next_shot_at=now+(actor.pve_count-1)*actor.pve_break+actor.fire_interval(now)
        packets+=actor._shot(dest,now)
        if arena.pk['finished']:return packets
        for n in range(1,actor.pve_count):actor._queue(now+n*actor.pve_break,'pve_fixed_laser',actor.generation,dest)
    return packets


def ai(arena,now):
    from bot_ai import observable,stop as stop_tank
    if arena.pk['finished']:return []
    packets=[]
    for actor in list(arena.actors.values()):
        tpl=actor.info.get('npc_template')
        if (not actor.alive or not actor.info.get('pve_npc') or tpl in LASERS
                or actor.info.get('pve_local_forklift')):continue
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
            target=min((a for a in arena.actors.values() if not a.info.get('map_object')
                and not a.info.get('pve_hostage') and observable(arena,actor,a,now,600)),
                key=lambda a:(math.dist(pos,a.position_at(now)),a.id),default=None)
            if tpl in SAWS:
                brain['goal']=_patrol(arena,actor,now)
                if target and math.dist(pos,target.position_at(now))<=72 and now>=actor.cooldowns[0]:
                    actor.cooldowns[0]=now+actor.fire_interval(now)
                    packets+=actor._shot(target.position_at(now),now,target)
            elif target:
                dest=target.position_at(now);near=math.dist(pos,dest)<=actor.pve_fire_range
                brain['goal']=pos if near else dest
                if near:packets+=stop_tank(actor,now)+actor.cast(0,pos,dest,target.id,now)
            else:brain['goal']=_patrol(arena,actor,now)
        if arena.pk['finished']:break
        packets+=move(arena,actor,brain,now)
        if arena.pk['finished']:break
    return packets


def tick(arena,now):
    pve=arena.pk['pve'];packets=[]
    if not pve['started']:
        pve['started']=True;pve['stage']=1
        for rec in records(arena):
            if rec['delay']>=0:schedule(arena,rec,now)
    packets+=crossing(arena,now)
    if arena.player.alive and not arena.player.in_stasis():
        for index,zone in enumerate(arena.geometry.data['pve_zones']):
            if index not in pve['zone_done'] and _inside(arena.player.position_at(now),zone_fields(arena,zone)):
                pve['zone_done'].append(index);packets+=scripts(arena,zone['scripts'],now)
    waiting=pve['spawns'];pve['spawns']=[]
    for event in waiting:
        if now>=event['spawn_due_at']:packets+=spawn(arena,event,now)
        else:pve['spawns'].append(event)
    packets+=mechanisms(arena,now)
    if arena.pk['finished']:return packets
    packets+=ai(arena,now)
    if not arena.pk['finished'] and arena.geometry.id==31301 and all(completed(arena,r) for r in records(arena)):
        packets+=finish(arena,now)
    return packets
