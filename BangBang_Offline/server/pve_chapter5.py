"""Chapter five: reviewed solo objectives and source-authored encounter triggers."""
import math
from combat_math import D
from pve_balance import hp_for
from pve_chapter1 import remove_objects,_inside
from pve_movement import patrol_goal as _patrol,move
from pve_chapter2 import records,respawn_position,_remove_actor
from pve_chapter4 import stop,finish as common_finish

STAGES={501:6,502:7,503:6}
DECOR=(517,518,519,520,522,524,525,526,527,567,578)
LASERS={524:(0,360),525:(-360,0),526:(360,0)}
BOSSES={503:515,506:566}
CROSSINGS={501:((588,1548),(540,1500)),502:((1116,900),(1092,828))}
CROSSING_RADIUS=24
# These source points are inside their own live factory. Its destroy script
# stops that same point, so waiting for the factory to disappear strands its
# emerging wave. Only use the first clear suffix of the existing authored leg.
FACTORY_EXITS={
    (501,9):(83,(2052,1764)),
    (502,9):(46,(804,1572)),
    (502,39):(120,(1668,300)),
    (502,30):(193,(1836,1188)),
    (503,9):(99,(1956,1092)),
    (503,67):(268,(516,324)),
}


def factory_exit(arena,actor,rec,now):
    if arena.geometry.id==505:
        from pve_factory505 import factory_exit as local_factory_exit
        return local_factory_exit(arena,actor,rec,now)
    source=FACTORY_EXITS.get((arena.geometry.id,rec['point']))
    if source is None:return
    instance,pos=source
    factory=arena.actors.get((3<<26)|instance)
    if (actor.camp!=0 or actor._speed(now)<=0
            or any(actor.info.get(key) for key in
                   ('pve_stationary','pve_flying','pve_trap','pve_hostage'))
            or tuple(rec['position'])!=pos or tuple(actor.position_at(now))!=pos
            or arena.geometry.can_walk_to(pos) or not factory or not factory.alive
            or not factory.info.get('map_object') or factory.info.get('npc_template')!=5019
            or tuple(factory.position_at(now))!=pos):return
    graph=next((g for g in arena.geometry.data['pve_logics'] if g['id']==rec['logic']),None)
    node=next((p for p in graph['points'] if p['id']==rec['point']),None) if graph else None
    if not node or not node['next']:return
    for end in node['next']:
        edge=next((p for p in arena.geometry.data['pve_paths']
                   if set(p['ends'])=={rec['point'],end}),None)
        if edge is None:return
        points=edge['points'] if edge['ends'][0]==rec['point'] else list(reversed(edge['points']))
        if not points or tuple(points[0])!=pos:return
        clear=[arena.geometry.can_walk_to(tuple(p)) for p in points]
        if not any(clear) or not all(clear[clear.index(True):]):return
    # Preserve the native route choice (including point502/30's three exits)
    # and keep its queue/previous/point for the next AI tick and checkpoints.
    from pve_chapter1 import _patrol as native_patrol
    dest=native_patrol(arena,actor,now)
    if actor.route_queue and arena.geometry.can_walk_to(dest):
        actor.position=actor.spawn=tuple(dest)


def objective(rec,tpl):
    if (rec['map'],rec['point']) in ((502,33),(503,15)):return False  # No surviving activation command.
    return rec['camp']==0 and rec['repeat']>=0 and tpl not in DECOR


def initialize(arena):
    total=D(0)
    for rec in records(arena):
        for tpl in rec['templates']:
            if not objective(rec,tpl):continue
            total+=hp_for(arena,tpl)*(rec['repeat']+1)
    arena.pk['pve'].update(stage=0,damage_total=total,active_rules=[],stopped_rules=[],zone_done=[],
        disabled_zones=[],rescued=[],started=False,hazards=[],rule_kills={},boss_kills=0,
        switches=[],allies_called=False,at_exit=False,crossing_latched=False)


def schedule(arena,rec,now):
    pve=arena.pk['pve']
    if rec['index'] in pve['active_rules'] or rec['index'] in pve['stopped_rules']:return
    pve['active_rules'].append(rec['index'])
    for n,tpl in enumerate(rec['templates']):
        if tpl==578:continue  # Invisible story marker, not a combat unit.
        delay=abs(rec['delay']) if arena.geometry.id>=504 else max(0,rec['delay'])
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,
            remaining=0 if tpl in DECOR else rec['repeat'],loop=tpl not in DECOR and rec['repeat']<0,
            spawn_due_at=now+(delay+n*max(1,rec['interval']))*1000))


def scripts(arena,script,now):
    packets=[];pve=arena.pk['pve']
    for kind,arg,_,_ in script:
        if kind==3:
            if arg not in pve['disabled_zones']:pve['disabled_zones'].append(arg)
        elif kind==4:packets+=remove_objects(arena,(arg,))
        elif kind==5:stop(arena,(arg,))
        elif kind==7:
            for rec in records(arena):
                if rec['point']!=arg or rec['delay']>=0:continue
                if rec['wave'] and rec['wave']!=pve['stage']:continue
                schedule(arena,rec,now)
    return packets


def object_destroyed(arena,obj,now):
    rec=next((r for r in arena.geometry.data['npcs'] if ((3<<26)|r['instance'])==obj.id),None)
    return scripts(arena,rec.get('pve_scripts',()),now) if rec else []


def stage(arena,wave,now):
    pve=arena.pk['pve'];old=pve['stage'];pve['stage']=wave
    for rec in records(arena):
        if old and rec['wave']==old and rec['repeat']<0:stop(arena,(rec['point'],))
        if rec['wave']==wave and rec['delay']>=0:schedule(arena,rec,now)
    packets=[]
    for rec in arena.geometry.data['pve_waves']:
        if rec['fields']==wave:packets+=scripts(arena,rec['scripts'],now)
    # A region entered earlier still activates its future-stage spawn records.
    for index in pve['zone_done']:
        zone=arena.geometry.data['pve_zones'][index]
        if zone['fields'][0] not in pve['disabled_zones']:packets+=scripts(arena,zone['scripts'],now)
    return packets


def spawn(arena,event,now):
    from pve_npc import PveNpc
    rec=records(arena)[event['rule']];tpl=event['template']
    info=dict(point=rec['point'],npc_template=tpl,pve_rule=rec['index'],pve_loop=event['loop'],
        pve_remaining=event['remaining'],pve_logic=rec['logic'],pve_unscored=not objective(rec,tpl))
    actor=PveNpc(arena,arena.new_id(5),info,rec['camp'],tuple(rec['position']))
    factory_exit(arena,actor,rec,now)
    arena.actors[actor.id]=actor;packets=[actor.snapshot(now)]
    if tpl in LASERS:actor.turret_next_shot_at=now+3500
    if tpl in (514,565):
        packets+=actor._buff(30101,now);actor.map_shield_hits=3
    if tpl==577:arena.pk['pve']['allies_called']=True
    return packets


def death(arena,actor,now):
    pve=arena.pk['pve'];tpl=actor.info['npc_template'];rec=records(arena)[actor.info['pve_rule']]
    if actor.camp!=1 and tpl not in DECOR:arena.pk['stats'][1][2]+=1
    pve['rule_kills'][rec['index']]=pve['rule_kills'].get(rec['index'],0)+1
    if rec['index'] in pve['active_rules'] and (actor.info['pve_loop'] or actor.info['pve_remaining']>0):
        pve['spawns'].append(dict(rule=rec['index'],template=tpl,loop=actor.info['pve_loop'],
            remaining=max(0,actor.info['pve_remaining']-1),spawn_due_at=now+max(1,rec['interval'])*1000))
    if tpl==BOSSES.get(arena.geometry.id):return finish(arena,now)
    return []


def mechanisms(arena,now):
    pve=arena.pk['pve'];p=arena.player;packets=[];present=p.alive and not p.in_stasis()
    for a in list(arena.actors.values()):
        if not a.alive or not a.info.get('pve_npc'):continue
        tpl=a.info['npc_template'];pos=a.position_at(now)
        if tpl==522 and present and math.dist(p.position_at(now),pos)<=72:
            pve['rescued'].append(a.info['pve_rule']);packets+=_remove_actor(a)
        elif tpl in (517,518,519,520):
            from pve_transport_traps import tick_emitter
            packets+=tick_emitter(a,now)
        elif tpl in LASERS and now>=a.turret_next_shot_at:
            a.turret_next_shot_at=now+4400  # Three shots450ms apart, then3500ms pause.
            dx,dy=LASERS[tpl];dest=(pos[0]+dx,pos[1]+dy)
            packets+=a._shot(dest,now)
            if arena.pk['finished']:return packets
            for delay in (450,900):a._queue(now+delay,'pve_fixed_laser',a.generation,dest)
    return packets


def crossing(arena,now,*,ends=None):
    """Approved temporary passage; authored terrain and trap shots stay intact."""
    from combat_geometry import rect_contact
    from combat_protocol import stop_move
    from map_portals import eligible
    if ends is None:ends=CROSSINGS.get(arena.geometry.id)
    if not ends:return []
    p=arena.player;pve=arena.pk['pve'];pos=p.position_at(now)
    if all(math.dist(pos,e)>CROSSING_RADIUS for e in ends):pve['crossing_latched']=False
    if pve['crossing_latched'] or not eligible(p,now):return []
    for i,start in enumerate(ends):
        dest=ends[1-i]
        if math.dist(pos,start)>CROSSING_RADIUS or arena.geometry.wall_contact(pos,start) is not None:continue
        water=arena.water_rects(now)
        if (arena.geometry.wall_contact(dest,dest,35.999) is not None
                or not arena.geometry.can_walk_to(dest) or rect_contact(pos,dest,water,35.999) is not None
                or any(a is not p and a.alive and not a.info.get('map_object') and
                    not a.is_untargetable() and math.dist(a.position_at(now),dest)<72 for a in arena.actors.values())):continue
        p.position=dest;p.motion=None;p.motion_kind=0;pve['crossing_latched']=True
        return [stop_move(arena.scene_id,p.id,dest)]
    return []


def ai(arena,now):
    from bot_ai import observable,stop as stop_tank
    from pve_support import explode
    if arena.pk['finished']:return []
    packets=[]
    for actor in list(arena.actors.values()):
        tpl=actor.info.get('npc_template')
        if not actor.alive or not actor.info.get('pve_npc') or tpl in DECOR and tpl not in (527,567):continue
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
            if tpl in (527,567):
                brain['goal']=_patrol(arena,actor,now)
                if tpl==567 and target and math.dist(pos,target.position_at(now))<=72 and now>=actor.cooldowns[0]:
                    actor.cooldowns[0]=now+1000;packets+=actor._shot(target.position_at(now),now,target)
            elif target:
                dest=target.position_at(now);near=math.dist(pos,dest)<=actor.pve_fire_range
                brain['goal']=pos if near else dest
                if near:
                    packets+=stop_tank(actor,now)
                    if tpl in (502,552) and not actor.blocked('attack',now):packets+=explode(actor,now)
                    else:packets+=actor.cast(0,pos,dest,target.id,now)
            else:brain['goal']=_patrol(arena,actor,now)
        if arena.pk['finished']:break
        packets+=move(arena,actor,brain,now)
        if arena.pk['finished']:break
    return packets


def completed(arena,rec):
    pve=arena.pk['pve']
    if rec['index'] in pve['stopped_rules']:return True
    if rec['index'] not in pve['active_rules'] and rec['delay']<0:
        references=[z for z in arena.geometry.data['pve_zones'] if any(s[0]==7 and s[1]==rec['point'] for s in z['scripts'])]
        if references and all(z['fields'][0] in pve['disabled_zones'] for z in references):return True
    expected=sum(objective(rec,t) for t in rec['templates'])*(rec['repeat']+1)
    return pve['rule_kills'].get(rec['index'],0)>=expected


def finish(arena,now):
    # Disabled alternate ambushes and factory waves which never spawned cannot
    # contribute obtainable HP. Already spawned finite enemies retain their HP.
    pve=arena.pk['pve'];total=D(0)
    for rec in records(arena):
        canceled=rec['index'] in pve['stopped_rules'] or (
            rec['index'] not in pve['active_rules'] and rec['delay']<0 and completed(arena,rec))
        if canceled:
            total+=sum((a.max_hp for a in arena.actors.values() if a.info.get('pve_npc') and
                a.info.get('pve_rule')==rec['index'] and objective(rec,a.info['npc_template'])),D(0))
            continue
        for tpl in rec['templates']:
            if not objective(rec,tpl):continue
            total+=hp_for(arena,tpl)*(rec['repeat']+1)
    pve['damage_total']=max(D(1),total)
    return common_finish(arena,now)


def tick(arena,now):
    pve=arena.pk['pve'];mid=arena.geometry.id;packets=[]
    if not pve['started']:
        pve['started']=True;packets+=stage(arena,1,now)
        # Invisible story blocker occupies the approved temporary entrance.
        if mid==502:packets+=remove_objects(arena,(177,))
        for rec in records(arena):
            if rec['wave']==0 and rec['delay']>=0:schedule(arena,rec,now)
    packets+=crossing(arena,now)
    if arena.player.alive and not arena.player.in_stasis():
        for index,zone in enumerate(arena.geometry.data['pve_zones']):
            if index in pve['zone_done'] or zone['fields'][0] in pve['disabled_zones']:continue
            if not _inside(arena.player.position_at(now),zone['fields']):continue
            pve['zone_done'].append(index);packets+=scripts(arena,zone['scripts'],now)
            if mid==506:pve['switches'].append(zone['fields'][0])
        if mid==504:pve['at_exit']=_inside(arena.player.position_at(now),[0,2030,380,80,60])
    waiting=pve['spawns'];pve['spawns']=[]
    for event in waiting:
        if now>=event['spawn_due_at']:packets+=spawn(arena,event,now)
        else:pve['spawns'].append(event)
    packets+=mechanisms(arena,now)
    if arena.pk['finished']:return packets
    packets+=ai(arena,now)
    if arena.pk['finished']:return packets
    if mid in STAGES and pve['stage']<STAGES[mid]:
        if all(completed(arena,r) for r in records(arena) if r['wave']==pve['stage']):
            packets+=stage(arena,pve['stage']+1,now)
    all_clear=all(completed(arena,r) for r in records(arena))
    all_clear=all_clear and not any(a.alive and a.info.get('pve_npc') and
        not a.info.get('pve_unscored') for a in arena.actors.values())
    if mid in (501,502) and pve['stage']==STAGES[mid] and all_clear and (mid==501 or len(pve['rescued'])==6):
        packets+=finish(arena,now)
    elif mid==504 and all_clear and pve['allies_called'] and pve['at_exit']:packets+=finish(arena,now)
    elif mid==505 and all_clear:
        factory=arena.actors.get((3<<26)|20187)
        if factory and not factory.alive and not any(a.alive and a.camp==0 and a.info.get('pve_npc') and a.info['npc_template'] not in DECOR for a in arena.actors.values()):packets+=finish(arena,now)
    elif mid==506 and pve['stage']==1 and len(set(pve['switches']))==3:packets+=stage(arena,2,now)
    return packets
