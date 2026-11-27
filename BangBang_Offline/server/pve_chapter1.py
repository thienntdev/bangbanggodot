"""Reviewed chapter-one stages. Native records remain data, not executable scripts."""
import math
import struct

from combat_math import D
from combat_protocol import scene
from pve_balance import hp_for

STAGES={204:(1,2,3,5,6,7,8),205:(1,3,4,5),203:(1,2,3),206:(1,2,3,4,5)}
HELPERS=(261,263,264)
HOSTAGES=(265,266)


def _finite(map_id, rec):
    return rec['wave'] in STAGES[map_id] and rec['camp']==0 and rec['repeat']>=0


def initialize(arena):
    total=D(0)
    for rec in arena.geometry.data['pve_spawns']:
        finite=_finite(arena.geometry.id,rec) or arena.geometry.id==205 and rec['wave']==0
        if not finite: continue
        for template in rec['templates']:
            if template==255 or template in HOSTAGES:continue
            total+=hp_for(arena,template)*(rec['repeat']+1)
    arena.pk['pve'].update(stage=0,damage_total=total,active_rules=[],zone_done=[],
                            bridge=False,rescued=[],started=False)


def _records(arena): return arena.geometry.data['pve_spawns']


def remove_objects(arena, instances):
    packets=[]
    for instance in instances:
        obj=arena.actors.get((3<<26)|instance)
        if obj and obj.alive:
            obj.hp=D(0);obj.info['hp']=0
            packets.extend((obj._hp_packet(obj.id,0),scene(removed=(struct.pack('<I',obj.id),))))
    if packets:
        from map_objects import rebuild_geometry
        rebuild_geometry(arena)
    return packets


def _schedule(arena,rec,now,*,loop=False,delay=None):
    pve=arena.pk['pve'];index=rec['index']
    if index in pve['active_rules']:return
    pve['active_rules'].append(index)
    for n,template in enumerate(rec['templates']):
        if template==255:continue  # Original server-only transition marker.
        first=max(0,rec['delay']) if delay is None else delay
        pve['spawns'].append(dict(rule=index,template=template,remaining=rec['repeat'],loop=loop,
            spawn_due_at=now+(first+n*max(1,rec['interval']))*1000))


def _scripts(arena,scripts,now):
    packets=[]
    for kind,arg,_,_ in scripts:
        if kind==4:packets+=remove_objects(arena,(arg,))
        elif kind==7:
            # A birth point may have several stage records. Only manual
            # records belong to this trigger; a numbered future wave does not.
            for rec in _records(arena):
                if rec['point']==arg and rec['wave']==0 and rec['delay']<0:
                    _schedule(arena,rec,now,loop=True,delay=0)
        elif kind==5:
            removed={r['index'] for r in _records(arena) if r['point']==arg}
            arena.pk['pve']['active_rules']=[i for i in arena.pk['pve']['active_rules'] if i not in removed]
            arena.pk['pve']['spawns']=[s for s in arena.pk['pve']['spawns'] if s['rule'] not in removed]
    return packets


def _stage(arena,wave,now):
    pve=arena.pk['pve'];pve['stage']=wave;packets=[]
    for rec in _records(arena):
        if rec['wave']!=wave:continue
        if arena.geometry.id==205 and wave==4:continue  # Wait for the bridge trigger.
        _schedule(arena,rec,now)
    for record in arena.geometry.data['pve_waves']:
        if record['fields']==wave:packets+=_scripts(arena,record['scripts'],now)
    if arena.geometry.id==203 and wave==3:
        for rec in _records(arena):
            if rec['point'] in (27,30):_schedule(arena,rec,now,loop=True,delay=0)
    return packets


def _spawn(arena,event,now):
    from pve_npc import PveNpc
    rec=_records(arena)[event['rule']];tpl=event['template']
    info=dict(point=rec['point'],npc_template=tpl,pve_rule=rec['index'],pve_loop=event['loop'],
              pve_remaining=event['remaining'],pve_logic=rec['logic'],
              pve_unscored=event['loop'] or tpl in HOSTAGES or tpl in HELPERS)
    camp=1 if tpl in HOSTAGES or tpl in HELPERS else rec['camp']
    actor=PveNpc(arena,arena.new_id(5),info,camp,tuple(rec['position']))
    arena.actors[actor.id]=actor
    return [actor.snapshot(now)]


def death(arena,actor,now):
    pve=arena.pk['pve'];tpl=actor.info['npc_template']
    if actor.camp!=arena.player.camp:arena.pk['stats'][1][2]+=1
    rec=_records(arena)[actor.info['pve_rule']]
    if tpl in HELPERS or (rec['index'] in pve['active_rules'] and
                          (actor.info['pve_loop'] or actor.info['pve_remaining']>0)):
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,loop=actor.info['pve_loop'],
            remaining=max(0,actor.info['pve_remaining']-1),
            spawn_due_at=now+(3000 if tpl in HELPERS else max(1,rec['interval'])*1000)))
    if (arena.geometry.id==203 and tpl==233) or (arena.geometry.id==206 and tpl==226):
        loop_ids={r['index'] for r in _records(arena) if r['wave']==0 and r['camp']==0}
        pve['active_rules']=[i for i in pve['active_rules'] if i not in loop_ids]
        pve['spawns']=[s for s in pve['spawns'] if s['rule'] not in loop_ids]
        pve['boss_dead']=True
    return []


def _inside(pos,fields):
    _,x,y,w,h=fields
    return x<=pos[0]<=x+w and y<=pos[1]<=y+h


def _patrol(arena,actor,now):
    pos=actor.position_at(now)
    if not actor.route_queue:
        graph=next((g for g in arena.geometry.data['pve_logics'] if g['id']==actor.info['pve_logic']),None)
        node=next((p for p in graph['points'] if p['id']==actor.route_point),None) if graph else None
        if not node or not node['next']:return pos
        options=[i for i in node['next'] if i!=actor.route_previous] or node['next']
        end=arena.rng.choice(options)
        edge=next((p for p in arena.geometry.data['pve_paths'] if set(p['ends'])=={actor.route_point,end}),None)
        if edge is None:return pos
        points=edge['points'] if edge['ends'][0]==actor.route_point else list(reversed(edge['points']))
        actor.route_queue=[tuple(p) for p in points if actor.info.get('pve_flying') or arena.geometry.can_walk_to(tuple(p))]
        actor.route_previous,actor.route_point=actor.route_point,end
    while actor.route_queue and math.dist(pos,actor.route_queue[0])<24:actor.route_queue.pop(0)
    return actor.route_queue[0] if actor.route_queue else pos


def trap_patrol_goal(arena,actor,now):
    """Advance short patrol legs at movement boundaries, without idle AI ticks."""
    from bot_ai import Navigation
    if not hasattr(arena,'navigation'):arena.navigation=Navigation(arena.geometry)
    pos=actor.position_at(now);visited=set()
    while True:
        if not actor.route_queue:
            # Bound even a cyclic graph whose points all snap to our cell.
            edge=(actor.route_previous,actor.route_point)
            if edge in visited:return pos
            visited.add(edge)
        goal=_patrol(arena,actor,now)
        if not actor.route_queue:
            # End of a leg can immediately start the next leg.
            continue
        cell=arena.navigation.nearest(goal)
        if cell is None:return pos
        if math.dist(pos,cell)>=20:return cell
        actor.route_queue.pop(0)


def _ai(arena,now):
    from bot_ai import observable,stop
    from pve_movement import patrol_goal,move
    if arena.pk['finished']:return []
    packets=[]
    for actor in list(arena.actors.values()):
        if not actor.alive or not actor.info.get('pve_npc'):continue
        tpl=actor.info['npc_template']
        if tpl==265:continue
        brain=arena.bot_brains.setdefault(actor.id,dict(path=[],notice_at=0))
        from pve_tactics import tick as tactical_tick
        tactical = tactical_tick(actor, brain, now)
        if tactical is not None:
            packets += tactical
            if arena.pk['finished']: break
            continue
        if now>=brain['notice_at']:
            brain['notice_at']=now+200;pos=actor.position_at(now)
            brain['pve_patrolling']=False
            target=None if tpl in HOSTAGES else min((a for a in arena.actors.values()
                if not a.info.get('map_object') and not a.info.get('pve_hostage')
                and observable(arena,actor,a,now,600)),key=lambda a:(math.dist(pos,a.position_at(now)),a.id),default=None)
            if target:
                dest=target.position_at(now);in_range=math.dist(pos,dest)<=actor.pve_fire_range
                brain['goal']=pos if in_range else dest
                if in_range:
                    packets+=stop(actor,now);packets+=actor.cast(0,pos,dest,target.id,now)
            else:
                goal=patrol_goal(arena,actor,now)
                # Native hostage route ends in the courtyard; approved extension
                # uses normal collision/pathfinding all the way to extraction.
                if tpl==266 and not actor.route_queue and actor.route_point in (12,14,16):
                    goal=arena.geometry.spawn(1)
                    brain['pve_patrolling']=False
                brain['goal']=goal
        # A synchronous attack can settle the final life or boss in this stack.
        if arena.pk['finished']:break
        packets+=move(arena,actor,brain,now)
        if tpl==266 and math.dist(actor.position_at(now),arena.geometry.spawn(1))<=120:
            if actor.id not in arena.pk['pve']['rescued']:
                arena.pk['pve']['rescued'].append(actor.id)
                actor.info['in_room']=False;actor.motion=None
                packets.append(scene(removed=(struct.pack('<I',actor.id),)))
        if arena.pk['finished']:break
    return packets


def tick(arena,now):
    from pve_rules import finish
    pve=arena.pk['pve'];mid=arena.geometry.id;packets=[]
    if not pve['started']:
        pve['started']=True
        packets+=_stage(arena,1,now)
        for rec in _records(arena):
            if rec['wave']==0 and rec['delay']>=0:
                _schedule(arena,rec,now)
    if arena.player.alive and not arena.player.in_stasis():
        for zone in arena.geometry.data['pve_zones']:
            zid=zone['fields'][0]
            if zid not in pve['zone_done'] and _inside(arena.player.position_at(now),zone['fields']):
                pve['zone_done'].append(zid)
                packets+=_scripts(arena,zone['scripts'],now)
        if mid==205 and pve['stage']==4 and 1 in pve['zone_done'] and not pve['bridge']:
            pve['bridge']=True
            for n,rec in enumerate(r for r in _records(arena) if r['wave']==4):
                _schedule(arena,rec,now,delay=2+n*2)
    events=pve['spawns'];pve['spawns']=[]
    for event in events:
        if now>=event['spawn_due_at']:packets+=_spawn(arena,event,now)
        else:pve['spawns'].append(event)
    packets+=_ai(arena,now)
    if arena.pk['finished']:return packets
    enemies=[a for a in arena.actors.values() if a.alive and a.info.get('pve_npc')
             and a.camp!=arena.player.camp and not a.info.get('pve_hostage')]
    waiting=any(s for s in pve['spawns'] if s['template'] not in HELPERS+HOSTAGES)
    stage=pve['stage'];stages=STAGES[mid]
    if mid==206 and stage==5:
        if len(pve['rescued'])==3:packets+=finish(arena,now,True)
    elif not enemies and not waiting:
        if mid==204 and stage==8:
            zone=next(z for z in arena.geometry.data['pve_zones'] if z['fields'][0]==1)
            if arena.player.alive and _inside(arena.player.position_at(now),zone['fields']):
                packets+=finish(arena,now,True)
        elif mid==205 and stage==4 and not pve['bridge']:pass
        elif mid==204 and stage==2 and 9 not in pve['zone_done']:pass
        elif stage==stages[-1]:packets+=finish(arena,now,True)
        else:packets+=_stage(arena,stages[stages.index(stage)+1],now)
    return packets
