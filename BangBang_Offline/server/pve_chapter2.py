"""User-reviewed chapter two. Missing server scripts are explicit local rules."""
import math
import struct

from combat_math import D
from combat_protocol import scene
from pve_balance import hp_for
from pve_chapter1 import remove_objects, _inside
from pve_movement import patrol_goal as _patrol, move

STAGES={401:(1,2,3,4,5),402:(1,2,3,4,5),403:(1,2,3,4)}
DECOR=(409,414,415,416,440,612,613)
BOSSES={211:614,212:625,213:633,401:413,403:422}
SWITCHES={402:{67:3},403:{63:2,62:3,61:4,68:65}}


def switch_radius(mid,point):
    # The two horizontal-door switches are 86.6 away from the closest legal
    # approach. User approved96 here; the three vertical switches retain72.
    return 96 if (mid,point) in ((402,67),(403,68)) else 72


def records(arena):return arena.geometry.data['pve_spawns']


def objective(rec,tpl):
    return rec['camp']==0 and rec['repeat']>=0 and tpl not in DECOR


def initialize(arena):
    total=D(0)
    for rec in records(arena):
        for tpl in rec['templates']:
            if not objective(rec,tpl):continue
            total+=hp_for(arena,tpl)*(rec['repeat']+1)
    arena.pk['pve'].update(stage=0,damage_total=total,active_rules=[],zone_done=[],
        open_doors=[],rescued=[],boss_kills=0,started=False,hazards=[])


def schedule(arena,rec,now):
    pve=arena.pk['pve']
    if rec['index'] in pve['active_rules']:return
    pve['active_rules'].append(rec['index'])
    for n,tpl in enumerate(rec['templates']):
        if tpl in (416,440):continue
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,
            remaining=0 if tpl in DECOR else rec['repeat'],loop=tpl not in DECOR and rec['repeat']<0,
            spawn_due_at=now+(max(0,rec['delay'])+n*max(1,rec['interval']))*1000))


def stop_points(arena,points):
    pve=arena.pk['pve'];ids={r['index'] for r in records(arena) if r['point'] in points}
    pve['active_rules']=[i for i in pve['active_rules'] if i not in ids]
    pve['spawns']=[s for s in pve['spawns'] if s['rule'] not in ids]


def scripts(arena,script,now):
    packets=[];pve=arena.pk['pve']
    for kind,arg,_,_ in script:
        if kind==4:packets+=remove_objects(arena,(arg,))
        elif kind==5:stop_points(arena,(arg,))
        elif kind==7:
            for rec in records(arena):
                if rec['point']!=arg or rec['delay']>=0:continue
                if rec['wave'] and rec['wave']!=pve['stage']:continue
                schedule(arena,rec,now)
    return packets


def object_destroyed(arena,obj,now):
    definition=next((r for r in arena.geometry.data['npcs'] if (3<<26)|r['instance']==obj.id),None)
    return scripts(arena,definition.get('pve_scripts',()),now) if definition else []


def stage(arena,wave,now):
    pve=arena.pk['pve'];pve['stage']=wave;packets=[]
    # Infinite reinforcements belong to their activation phase, not all future phases.
    looping={s['rule'] for s in pve['spawns'] if s['loop']}
    looping.update(a.info['pve_rule'] for a in arena.actors.values() if a.info.get('pve_loop'))
    pve['active_rules']=[i for i in pve['active_rules'] if i not in looping]
    pve['spawns']=[s for s in pve['spawns'] if s['rule'] not in looping]
    for rec in records(arena):
        if rec['wave']==wave and rec['delay']>=0:schedule(arena,rec,now)
    for record in arena.geometry.data['pve_waves']:
        if record['fields']==wave:packets+=scripts(arena,record['scripts'],now)
    return packets


def spawn(arena,event,now):
    from pve_npc import PveNpc
    rec=records(arena)[event['rule']];tpl=event['template']
    info=dict(point=rec['point'],npc_template=tpl,pve_rule=rec['index'],pve_loop=event['loop'],
        pve_remaining=event['remaining'],pve_logic=rec['logic'],pve_unscored=not objective(rec,tpl))
    position=tuple(rec['position'])
    # Offline correction for this one authored guard spawn: its centre is
    # clear, but the native tank footprint is trapped between two wall rows
    # and none of the eight 24px steps is legal. The closest legal grid cell
    # is 48px left in the same chamber. Correct only a new spawn, never an
    # arbitrary blocked actor or a saved in-progress position.
    if (arena.geometry.id==213 and tpl==631 and rec['point']==4
            and position==(1188,2436) and not arena.geometry.can_walk_to(position)
            and arena.geometry.can_walk_to((1140,2436))
            and arena.geometry.wall_contact(position,(1140,2436)) is None):
        position=(1140,2436)
    actor=PveNpc(arena,arena.new_id(5),info,rec['camp'],position)
    if tpl in (612,613):actor.turret_next_shot_at=now+5000
    arena.actors[actor.id]=actor
    return [actor.snapshot(now)]


def death(arena,actor,now):
    pve=arena.pk['pve'];tpl=actor.info['npc_template'];rec=records(arena)[actor.info['pve_rule']]
    if actor.camp!=arena.player.camp and tpl not in DECOR:arena.pk['stats'][1][2]+=1
    if rec['index'] in pve['active_rules'] and (actor.info['pve_loop'] or actor.info['pve_remaining']>0):
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,loop=actor.info['pve_loop'],
            remaining=max(0,actor.info['pve_remaining']-1),spawn_due_at=now+max(1,rec['interval'])*1000))
    if tpl==BOSSES.get(arena.geometry.id):
        pve['boss_kills']+=1
        if arena.geometry.id!=212 and pve['boss_kills']>=(2 if arena.geometry.id==213 else 1):
            from pve_rules import finish
            pve['spawns']=[];pve['active_rules']=[]
            return finish(arena,now,True)
    return []


def respawn_position(arena):
    phase=arena.pk['pve']['stage']
    choices=[r for r in arena.geometry.data['pve_respawns'] if r[0]==1 and r[3]<=phase]
    return tuple(max(choices,key=lambda r:r[3])[1:3]) if choices else arena.geometry.spawn(1)


def _remove_actor(actor):
    actor.hp=D(0);actor.info.update(hp=0,in_room=False);actor.motion=None
    return [scene(removed=(struct.pack('<I',actor.id),))]


def mechanisms(arena,now):
    pve=arena.pk['pve'];player=arena.player;packets=[]
    pos=player.position_at(now)
    for actor in list(arena.actors.values()):
        if not actor.alive or not actor.info.get('pve_npc'):continue
        tpl=actor.info['npc_template']
        if tpl==409 and player.alive and not player.in_stasis() and math.dist(pos,actor.position_at(now))<=72:
            pve['rescued'].append(actor.info['pve_rule']);packets+=_remove_actor(actor)
        elif tpl in (612,613) and now>=getattr(actor,'turret_next_shot_at',0):
            actor.turret_next_shot_at=now+5000
            x,y=actor.position_at(now);packets+=actor._shot((x+(-360 if tpl==612 else 360),y),now)
            if arena.pk['finished']:return packets
    if not player.alive or player.in_stasis():return packets
    for point,door in SWITCHES.get(arena.geometry.id,{}).items():
        rec=next(r for r in records(arena) if r['point']==point and 416 in r['templates'])
        if door in pve['open_doors'] or math.dist(pos,rec['position'])>switch_radius(arena.geometry.id,point):continue
        pve['open_doors'].append(door)
        for actor in list(arena.actors.values()):
            if actor.alive and actor.info.get('npc_template') in (414,415) and actor.info['point']==door:
                packets+=_remove_actor(actor)
        # If the player reaches a switch before the delayed door appearance, cancel it.
        pve['spawns']=[s for s in pve['spawns'] if not
            (s['template'] in (414,415) and records(arena)[s['rule']]['point']==door)]
        from map_objects import rebuild_geometry
        rebuild_geometry(arena)
    return packets


def ai(arena,now):
    from bot_ai import observable,stop
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
            target=min((a for a in arena.actors.values() if not a.info.get('map_object')
                and not a.info.get('pve_hostage') and observable(arena,actor,a,now,600)),
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
        packets+=stage(arena,1 if mid in STAGES else 0,now)
        for rec in records(arena):
            if rec['wave']==0 and rec['delay']>=0:schedule(arena,rec,now)
        packets+=init_hazards(arena)
    if arena.player.alive and not arena.player.in_stasis():
        for index,zone in enumerate(arena.geometry.data['pve_zones']):
            if index in pve['zone_done'] or not _inside(arena.player.position_at(now),zone['fields']):continue
            pve['zone_done'].append(index)
            final_zone={211:6,212:1,213:3}.get(mid)
            if final_zone==zone['fields'][0] and pve['stage']==0:
                packets+=stage(arena,1,now)
            packets+=scripts(arena,zone['scripts'],now)
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
    if mid==212 and pve['boss_kills'] and arena.player.alive and math.dist(arena.player.position_at(now),(852,324))<=120:
        return packets+finish(arena,now,True)
    if mid in STAGES:
        enemies=any(a.alive and a.info.get('pve_npc') and a.camp==0
                    and a.info['npc_template'] not in DECOR for a in arena.actors.values())
        waiting=any(records(arena)[s['rule']]['camp']==0 and s['template'] not in DECOR for s in pve['spawns'])
        if not enemies and not waiting:
            stages=STAGES[mid];wave=pve['stage']
            if wave<stages[-1]:packets+=stage(arena,stages[stages.index(wave)+1],now)
            elif mid==402:packets+=finish(arena,now,True)
    return packets
