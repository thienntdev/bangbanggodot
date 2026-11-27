"""AI06 casters: delayed sightings, native charges and cancellable fields."""
import math

from bot_ai01 import aim_in_range,ratio
from bot_ai02 import controlled,friends
from bot_ai04 import mobility,mobility_goal_ok,near
from bot_ai05 import incoming
from combat_geometry import point_at,rect_contact

TANKS=frozenset((10000045,10000074,10000107,10000086,10000106,10000079))
LAST_STAND={10000045:(2,1),10000074:(10,2),10000107:(2,10),
            10000086:(10,2),10000106:(10,1),10000079:(10,2)}


def desired_range(actor,now):
    return {10000045:250,10000074:300,10000107:350,
            10000086:350,10000106:420,10000079:420}[actor.info['tank_id']]


def observation(actor,target,now):
    return dict(ai06_cc=controlled(target,now),ai06_frozen=target.has_buff(353401,now))


def recast(actor,slot,now):
    return (actor.info['tank_id']==10000106 and slot==2 and bool(actor.channel) or
            actor.info['tank_id']==10000079 and slot==1 and bool(actor.water_wall)
            and actor.has_buff(353501,now))


def wall_rects(actor,center,now):
    pos=actor.position_at(now);distance=math.dist(pos,center)
    if distance<1:return []
    axis=(-(center[1]-pos[1])/distance,(center[0]-pos[0])/distance)
    points=[tuple(round(a+b*i*72) for a,b in zip(center,axis)) for i in range(-4,5)]
    return [(p[0]-36,p[1]-36,p[0]+36,p[1]+36) for p in points
            if actor.arena.geometry.clamp_tank_position(p)==p]


def blocks_friends(actor,rects,brain,now):
    for ally in friends(actor,now,1000):
        pos=ally.position_at(now)
        other=brain if ally is actor else actor.arena.bot_brains.get(ally.id,{})
        destinations=[other.get('repair_goal'),other.get('goal')]
        if ally.motion and ally.motion[3]>now:destinations.append(ally.motion[1])
        if rect_contact(pos,pos,rects,36) is not None:return True
        if any(dest is not None and rect_contact(pos,dest,rects,36) is not None
               for dest in destinations):return True
    return False


def wall_point(actor,brain,target,seen,dest,retreat,now):
    pos=actor.position_at(now);distance=math.dist(pos,dest)
    # First try the aimed line; then a line behind it to preserve allied routes.
    for offset in ((-108,0) if retreat else (0,108)):
        center=aim_in_range(actor,point_at(pos,dest,(distance+offset)/max(1,distance)),600,now)
        if math.dist(pos,center)<144 or not near(center,seen,216):continue
        rects=wall_rects(actor,center,now)
        if rects and not blocks_friends(actor,rects,brain,now):return center
    return None


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain if brain is not None else {};tank=actor.info['tank_id'];pos=actor.position_at(now)
    if tank==10000106 and actor.channel:
        field=actor.channel
        if now>=field['begin']+1000 and (not near(field['pos'],seen,264) or recovering or
                ratio(actor)<.35 and incoming(actor,brain,now) or
                brain.get('objective')=='survive' and math.dist(pos,brain.get('goal',pos))>250):
            return [(2,pos,actor.id)]
    if tank==10000079:
        if actor.ice:return []  # Casting breaks the native rescue before its heal ticks.
        if actor.water_wall:
            rects=[(p[0]-36,p[1]-36,p[0]+36,p[1]+36) for _,p in actor.water_wall['blocks']]
            if blocks_friends(actor,rects,brain,now):return [(1,pos,actor.id)]
    if tank==10000107 and not actor.temple:
        covered=friends(actor,now,432)
        if (any(controlled(a,now) for a in covered) or any(ratio(a)<.55 for a in covered)
                or sum(ratio(a)<.8 for a in covered)>=2):return [(2,pos,actor.id)]
    return []


def adjust_goal(actor,brain,seen,now,recovering=False):
    if recovering or brain.get('objective') in ('flag_hold','survive','base_defend','bomb_escort','bomb_intercept'):return
    pos=actor.position_at(now);tank=actor.info['tank_id']
    if tank==10000045 and ratio(actor)<.8:
        soaps=[s['pos'] for s in actor.soaps.values() if s['end']>now
               and math.dist(pos,s['pos'])<=240 and near(s['pos'],seen,216)<=near(pos,seen,216)
               and actor.arena.geometry.wall_contact(pos,s['pos'],36) is None]
        if soaps:brain['goal']=min(soaps,key=lambda p:math.dist(pos,p))
    if tank==10000107 and not seen:
        wounded=[a for a in friends(actor,now,600) if a is not actor and ratio(a)<.6]
        if wounded:
            point=min(wounded,key=lambda a:(ratio(a),a.id)).position_at(now)
            if math.dist(pos,point)>350:brain['goal']=point_at(point,pos,300/math.dist(pos,point))


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);cluster=near(target['pos'],seen,180);result=[]
    if tank==10000045:
        if distance<=288:result.append((2,pos,ident))
        if distance<=420:result.append((1,aim_in_range(actor,dest,360,now),ident))
    elif tank==10000074:
        if retreat and distance<360 or not retreat and 240<distance<600:
            point=mobility(actor,brain,target,seen,dest,retreat,now,360,fixed=True)
            if point is not None:result.append((1,point,ident))
        if distance<=480:result.append((10,dest,ident))
        if distance<=480:result.append((2,dest,ident))
    elif tank==10000107:
        if not actor.temple and distance<=400 and (cluster>=2 or target['hp']<.5):result.append((2,pos,ident))
        if distance<=600:result.append((10,aim_in_range(actor,dest,600,now),ident))
        if distance<=600:result.append((1,dest,ident))
    elif tank==10000086:
        if retreat and distance<360 or not retreat and 240<distance<550:
            point=mobility(actor,brain,target,seen,dest,retreat,now,336,blink=True)
            if point is not None:result.append((2,point,ident))
        if distance<=480:result.append((10,dest,ident))
        if distance<=600:result.append((1,dest,ident))
    elif tank==10000106:
        if actor.channel:return []
        if distance<300 and (retreat or distance<200):result.append((1,dest,ident))
        if distance<=600:
            # Put the delayed aim in the outer freezing ring, not its hollow center.
            ring=point_at(pos,dest,(math.dist(pos,dest)+100)/max(1,math.dist(pos,dest)))
            result.append((10,aim_in_range(actor,ring,600,now),ident))
        if not retreat and distance<=600 and (cluster>=2 or target.get('ai06_cc')):
            result.append((2,aim_in_range(actor,dest,600,now),ident))
        if distance<=350:result.append((1,dest,ident))
    elif tank==10000079:
        if actor.ice:return []
        if distance<=600 and target.get('ai06_frozen'):result.append((10,aim_in_range(actor,dest,600,now),ident))
        if not actor.water_wall and distance<=580:
            point=wall_point(actor,brain,target,seen,dest,retreat,now)
            if point is not None:result.append((1,point,ident))
        if distance<=600:result.append((10,aim_in_range(actor,dest,600,now),ident))
        if distance<=600 and (cluster>=2 or target.get('ai06_cc') or ratio(actor)<.65):
            result.append((2,aim_in_range(actor,dest,600,now),ident))
    return result
