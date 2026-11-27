"""Map35's approved one-way portals; native S1589 visuals and instant snaps."""
import math
import struct
from functools import lru_cache

from combat_geometry import rect_contact
from combat_protocol import stop_move


def install(arena):
    arena.pk['portals']={p['index']:dict(p,portal_ready_at=0) for p in arena.geometry.data['portals']}


def snapshot(arena):
    points=arena.pk.get('portals',{})
    return 1589,struct.pack('<H',len(points))+b''.join(
        struct.pack('<ii',i,p['state']) for i,p in sorted(points.items()))


def eligible(actor,now):
    return (actor.alive and not actor.info.get('npc_template') and not actor.is_untargetable()
            and not getattr(actor,'portal_exit_id',None)
            and not actor.blocked('move',now) and not getattr(actor,'ready',None)
            and not getattr(actor,'channel',None)
            and not (actor.motion and actor.motion[3]>now and actor.motion_kind!=0))


def landing(arena,actor,point,now):
    center=tuple(point)
    # Keep displacement local to the authored exit, never search the whole map.
    candidates=[(center[0]+24*x,center[1]+24*y) for x in range(-3,4) for y in range(-3,4)
                if math.hypot(x,y)<=3]
    water=arena.water_rects(now)
    occupied=[a.position_at(now) for a in arena.actors.values()
              if a is not actor and a.alive and not a.info.get('map_object') and not a.is_untargetable()]
    for pos in sorted(candidates,key=lambda p:(math.dist(center,p),p)):
        if (arena.geometry.clamp_tank_position(pos)==pos
                and arena.geometry.wall_contact(pos,pos,35.999) is None
                and arena.geometry.wall_contact(center,pos) is None
                and rect_contact(pos,pos,water,35.999) is None
                and all(math.dist(pos,p)>=72 for p in occupied)):
            return pos
    return None


def tick(arena,now):
    if arena.pk['finished'] or now<arena.pk.get('intro_until',0):return []
    packets=[];changed=False;moved=set()
    points=arena.pk['portals']
    if arena.geometry.id==40:
        for actor in arena.actors.values():
            exit_point=points.get(getattr(actor,'portal_exit_id',None))
            if exit_point and math.dist(actor.position_at(now),exit_point['position'])>exit_point['radius']:
                actor.portal_exit_id=None
    for portal in points.values():
        if not portal['destinations']:continue
        if portal['state']==2 and now>=portal['portal_ready_at']:
            portal['state']=1;changed=True
        if portal['state']!=1:continue
        center=portal['position']
        # Stable arbitration only when several tanks reach the same tick.
        for actor in sorted(arena.actors.values(),key=lambda a:a.id):
            if actor.id in moved or not eligible(actor,now):continue
            pos=actor.position_at(now)
            if (math.dist(pos,center)>portal['radius']
                    or arena.geometry.wall_contact(pos,center) is not None
                    or rect_contact(pos,center,arena.water_rects(now)) is not None):continue
            dest=landing(arena,actor,points[portal['destinations'][0]]['position'],now)
            if dest is None:continue
            actor.position=dest;actor.motion=None;actor.motion_kind=0
            if arena.geometry.id==40:actor.portal_exit_id=portal['destinations'][0]
            brain=arena.bot_brains.get(actor.id)
            if brain is not None:
                brain['path']=[];brain['repath_at']=0
            packets.append(stop_move(actor.scene_id,actor.id,dest))
            moved.add(actor.id)
            portal['state']=2;portal['portal_ready_at']=now+portal['cooldown_ms'];changed=True
            break
    if changed:packets.append(snapshot(arena))
    return packets


def route(arena,actor,brain,goal,direct,now):
    """Compare public walking routes; exit danger uses prior observations only."""
    if not eligible(actor,now):return direct
    pos=actor.position_at(now);goal=tuple(goal);nav=arena.navigation
    if not hasattr(nav,'portal_route'):
        # Static geometry only; rebuild_geometry clears this when cover breaks.
        nav.portal_route=lru_cache(maxsize=256)(lambda a,b:tuple(nav.path(a,b)))
    def cost(start,path,end):
        if not path or math.dist(path[-1],end)>72:return math.inf
        return sum(math.dist(p,q) for p,q in zip((start,)+tuple(path),path))
    best=cost(pos,direct,goal);chosen=direct
    for p in arena.pk.get('portals',{}).values():
        if p['state']!=1 or not p['destinations']:continue
        enter=tuple(p['position']);leave=tuple(arena.pk['portals'][p['destinations'][0]]['position'])
        # Skip expensive searches when even an unobstructed shortcut cannot win.
        if math.dist(pos,enter)+math.dist(leave,goal)+96>=best:continue
        danger=sum(max(0,480-math.dist(leave,s['pos'])) for s in brain.get('observations',())
                   if not s.get('barrier') and now-s['observed_at']<=2000)
        if math.dist(pos,enter)+math.dist(leave,goal)+danger+96>=best:continue
        first=nav.portal_route(pos,enter);second=nav.portal_route(leave,goal)
        total=cost(pos,first,enter)+cost(leave,second,goal)+danger+96
        if total<best:chosen=list(first);best=total
    return chosen


def approach(arena,actor,goal,seen,now):
    """Public shortcut destination, even while its visible cover needs clearing."""
    pos=actor.position_at(now);best=math.dist(pos,goal);chosen=goal
    for p in arena.pk['portals'].values():
        if p['state']!=1 or not p['destinations']:continue
        leave=arena.pk['portals'][p['destinations'][0]]['position']
        danger=sum(max(0,480-math.dist(leave,s['pos'])) for s in seen
                   if not s.get('barrier') and now-s['observed_at']<=2000)
        cost=math.dist(pos,p['position'])+math.dist(leave,goal)+96+danger
        if cost<best:best=cost;chosen=tuple(p['position'])
    return chosen
