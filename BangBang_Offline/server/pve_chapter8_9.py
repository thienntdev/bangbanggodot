"""Normal chapters eight-nine: authored ambush zones and explicit solo objectives."""
import math
from combat_math import D
from pve_chapter1 import remove_objects, _inside
from pve_movement import patrol_goal, move
from pve_chapter2 import records, respawn_position
from pve_chapter4 import stop, finish
from pve_balance import hp_for

BOSSES = {31401:3140111,31402:3140209,31403:3140314,31501:3150109,
          31502:3150208,31503:3150314,31601:3160111,31602:3160211}
LASERS = {3150209:(-360,0),3150210:(360,0)}
SAWS = (3160112,)
TELEPORT_TRAPS = (3160113,3160115,3160116)
DECOR = (*LASERS,*SAWS,*TELEPORT_TRAPS)
CROSSINGS = {}
CROSSING_RADIUS = 24
ESCORTS = (3140212,3160203)
ESCORT_ENDS = {(31402,901):(1898,1395),(31402,902):(1088,505),(31602,301):(1026,933)}


def objective(rec, tpl):
    return rec['camp']==0 and rec['repeat']>=0 and tpl not in DECOR


def initialize(arena):
    total=sum((hp_for(arena,t)*(r['repeat']+1) for r in records(arena)
               for t in r['templates'] if objective(r,t)), D(0))
    arena.pk['pve'].update(stage=0,damage_total=total,active_rules=[],stopped_rules=[],
        zone_done=[],started=False,hazards=[],rule_kills={},boss_kills=0,crossing_latched=False,escort_done=[],deferred_boss=[])
    from pve_local_late import initialize as local_initialize
    local_initialize(arena)


def schedule(arena, rec, now):
    pve=arena.pk['pve']
    needed=2 if arena.geometry.id==31402 else 0
    if BOSSES.get(arena.geometry.id) in rec['templates'] and len(pve['escort_done'])<needed:
        if rec['index'] not in pve['deferred_boss']:pve['deferred_boss'].append(rec['index'])
        return
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
    if tpl==3160211:packets+=actor._buff(15101,now)
    if tpl==3140314:
        from pve_balance import frozen_profile
        if frozen_profile(arena) is not None:
            # Arms7060501 explicitly declares the same plague passive used
            # by3130313. This is independent of the missing fortification AI.
            packets+=actor._buff(10001091,now)
            actor._queue(now+500,'pve_plague',actor.generation)
    if tpl in LASERS:actor.turret_next_shot_at=now+actor.fire_interval(now)
    return packets


def death(arena,actor,now):
    if actor.info.get('pve_fortification') or actor.info.get('pve_boss_add'):return []
    pve=arena.pk['pve'];tpl=actor.info['npc_template'];rec=records(arena)[actor.info['pve_rule']]
    if tpl==3160203:
        # Alice is support, not a failure condition or a prerequisite for the
        # boss. Keep her authored death (no extra respawn/life cost).
        return []
    if tpl==3140212:
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,loop=False,remaining=0,spawn_due_at=now+5000))
        return []
    if actor.camp!=1 and tpl not in DECOR:arena.pk['stats'][1][2]+=1
    pve['rule_kills'][rec['index']]=pve['rule_kills'].get(rec['index'],0)+1
    if rec['index'] in pve['active_rules'] and (actor.info['pve_loop'] or actor.info['pve_remaining']>0):
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,loop=actor.info['pve_loop'],
            remaining=max(0,actor.info['pve_remaining']-1),spawn_due_at=now+max(1,rec['interval'])*1000))
    if tpl==BOSSES.get(arena.geometry.id):
        pve['boss_kills']+=1
        from pve_boss_tactics import cleanup
        return cleanup(actor,now)+finish(arena,now)
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
    from pve_local_late import fortification_tick
    packets=fortification_tick(arena,now)
    if arena.pk['finished']:return packets
    for actor in list(arena.actors.values()):
        tpl=actor.info.get('npc_template')
        if tpl in TELEPORT_TRAPS:
            from pve_transport_traps import tick_emitter
            packets+=tick_emitter(actor,now)
            if arena.pk['finished']:return packets
        # The final boss is drawn entirely by its authored appearance buff;
        # external51 intentionally has no body. Repair old saved spawns too.
        if actor.alive and tpl==3160211 and not actor.has_buff(15101,now):
            packets+=actor._buff(15101,now)
        if not actor.alive or tpl not in LASERS or now<actor.turret_next_shot_at:continue
        pos=actor.position_at(now);dx,dy=LASERS[tpl];dest=(pos[0]+dx,pos[1]+dy)
        actor.turret_next_shot_at=now+(actor.pve_count-1)*actor.pve_break+actor.fire_interval(now)
        packets+=actor._shot(dest,now)
        if arena.pk['finished']:return packets
        for n in range(1,actor.pve_count):actor._queue(now+n*actor.pve_break,'pve_fixed_laser',actor.generation,dest)
    return packets


def route_goal(arena,actor,now):
    return patrol_goal(arena,actor,now)


def ai(arena,now):
    from bot_ai import observable,stop as stop_tank
    if arena.pk['finished']:return []
    packets=[]
    for actor in list(arena.actors.values()):
        tpl=actor.info.get('npc_template')
        if not actor.alive or not actor.info.get('pve_npc') or tpl in (*LASERS,*TELEPORT_TRAPS):continue
        if actor.info.get('pve_fortification'):
            from pve_local_late import fortification_ai
            packets+=fortification_ai(actor,now) or []
            if arena.pk['finished']:break
            continue
        brain=arena.bot_brains.setdefault(actor.id,dict(path=[],notice_at=0))
        from pve_boss_tactics import tick as boss_tactical_tick
        tactical=boss_tactical_tick(actor,brain,now)
        if tactical is not None:
            packets+=tactical
            if arena.pk['finished']:break
            continue
        if tpl in ESCORTS:
            p=arena.player;point=actor.info['point'];end=ESCORT_ENDS[(arena.geometry.id,point)]
            if tpl==3140212 and (not p.alive or p.in_stasis() or math.dist(p.position_at(now),actor.position_at(now))>200):
                packets+=stop_tank(actor,now);brain.pop('goal',None);continue
            snapped=arena.navigation.nearest(end) if hasattr(arena,'navigation') else None
            arrived=math.dist(actor.position_at(now),end)<=24 or (
                not actor.route_queue and snapped is not None and math.dist(actor.position_at(now),snapped)<20)
            if point not in arena.pk['pve']['escort_done'] and arrived:
                arena.pk['pve']['escort_done'].append(point)
                if tpl==3140212:
                    import struct
                    from combat_protocol import scene
                    actor.hp=D(0);actor.info['in_room']=False;actor.motion=None
                    packets.append(scene(removed=(struct.pack('<I',actor.id),)))
                    continue
        from pve_boss_tactics_v2 import tick as remaining_boss_tick
        tactical = remaining_boss_tick(actor, brain, now)
        if tactical is not None:
            packets += tactical
            if arena.pk['finished']: break
            continue
        from pve_tactics import tick as tactical_tick
        tactical=tactical_tick(actor,brain,now)
        if tactical is not None:
            packets+=tactical
            if arena.pk['finished']:break
            continue
        if now>=brain['notice_at']:
            brain['notice_at']=now+200;pos=actor.position_at(now)
            brain['pve_patrolling']=False
            from pve_bosses import enabled as offline_boss, RANGE as boss_range
            notice_range=boss_range if offline_boss(actor) else 600
            target=min((a for a in arena.actors.values() if not a.info.get('map_object')
                and not a.info.get('pve_hostage') and observable(arena,actor,a,now,notice_range)),
                key=lambda a:(math.dist(pos,a.position_at(now)),a.id),default=None)
            if tpl in SAWS:
                brain['goal']=route_goal(arena,actor,now)
                if target and math.dist(pos,target.position_at(now))<=72 and now>=actor.cooldowns[0]:
                    actor.cooldowns[0]=now+actor.fire_interval(now)
                    packets+=actor._shot(target.position_at(now),now,target)
            elif target and tpl!=3140212:
                dest=target.position_at(now);near=math.dist(pos,dest)<=actor.pve_fire_range
                brain['goal']=pos if near else dest
                if near:packets+=stop_tank(actor,now)+actor.cast(0,pos,dest,target.id,now)
            else:brain['goal']=route_goal(arena,actor,now)
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
    if arena.pk['finished']:return packets
    needed=2 if arena.geometry.id==31402 else 0
    if len(pve['escort_done'])>=needed:
        waiting=pve['deferred_boss'];pve['deferred_boss']=[]
        for index in waiting:schedule(arena,records(arena)[index],now)
    return packets
