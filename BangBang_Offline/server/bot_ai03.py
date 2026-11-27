"""AI03 combos use observed marks; movement and damage remain native casts."""
import math

from bot_ai01 import aim_in_range,ratio
from combat_geometry import point_at

TANKS=frozenset((10000039,10000047,10000043,10000069,10000089))
LAST_STAND={10000039:(1,10),10000047:(2,10),10000043:(1,2),
            10000069:(2,10),10000089:(2,10)}


def observation(actor,target,now):
    """Called only after the shared vision filter, never from a decision."""
    tank=actor.info['tank_id'];marks=0
    if tank==10000039:
        marks=2 if target.has_buff(313132,now) else int(target.has_buff(313131,now))
    elif tank==10000047:
        marks=max((i for i,b in enumerate(range(321121,321125),1) if target.has_buff(b,now)),default=0)
    elif tank in (10000069,10000089):
        mark=actor.marks.get(target.id)
        valid=actor._mark_valid if tank==10000069 else actor._valid_mark
        if mark and mark['source_generation']==actor.generation and valid(target,mark,now):marks=mark['stacks']
    return dict(ai03_marks=marks,ai03_controlled=bool(target.buff_types(now)&{30,35,36,62}))


def basic_range(actor,now):
    reach=int(actor.stats['nFireRange'])
    return reach*1.25 if actor.info['tank_id']==10000043 and actor.enhanced_count and actor.has_buff(317402,now) else reach


def desired_range(actor):
    tank=actor.info['tank_id']
    if tank==10000047 and (actor.discharge or actor.contact):return 175
    if tank==10000089 and actor.sweep:return 210
    return min(410,int(actor.stats['nFireRange'])-36)


def jump_point(actor,dest,target,seen,retreat,now):
    """Check the real full dash endpoint; danger uses delayed sightings only."""
    pos=actor.position_at(now);distance=math.dist(pos,target['pos'])
    pika=actor.info['tank_id']==10000047
    direction=point_at(pos,target['pos'],-1) if retreat else dest
    direction=actor.arena.geometry.clamp_tank_position(direction)
    length=360 if pika else min(408,math.dist(pos,direction))
    if math.dist(pos,direction)<1:return None
    end=actor.move_destination(pos,point_at(pos,direction,length/math.dist(pos,direction)))
    if math.dist(pos,end)<96 or not actor._inside(end):return None
    after=math.dist(end,target['pos'])
    point=direction if pika else end
    if retreat:return point if after>distance+72 else None
    if after>=distance-72 or after>220:return None
    friends=sum(a.alive and a.camp==actor.camp and not a.info.get('npc_template')
                and math.dist(end,a.position_at(now))<480 for a in actor.arena.actors.values())
    threats=sum(math.dist(end,s['pos'])<360 for s in seen if not s.get('barrier'))
    return point if ratio(actor)>.55 and threats<=friends+1 else None


def structure_choices(actor,dest,now):
    """Empower ordinary shots while keeping the shared building target."""
    tank=actor.info['tank_id']
    if tank==10000043 and not actor.has_buff(317402,now):return [(10,dest,0)]
    if tank==10000069 and not actor.has_buff(343201,now):return [(1,actor.position_at(now),actor.id)]
    return []


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);marks=target.get('ai03_marks',0)
    cluster=sum(math.dist(target['pos'],s['pos'])<=180 for s in seen if not s.get('barrier'))
    controlled=target.get('ai03_controlled',False);result=[]
    if tank==10000039:
        if distance<=600 and (marks==2 or retreat or cluster>=2 or distance<320):
            result.append((10,aim_in_range(actor,dest,600,now),ident))
        if distance<=700 and not actor.fields and (cluster>=2 or controlled or target['hp']<.55):
            result.append((2,aim_in_range(actor,dest,720,now),ident))
        if distance<=600:result.append((1,dest,ident))
    elif tank==10000047:
        if distance<=230 and not actor.discharge:result.append((2,pos,actor.id))
        if retreat and distance<300 or not retreat and 270<distance<540 and not actor.contact:
            end=jump_point(actor,dest,target,seen,retreat,now)
            if end is not None:result.append((1,end,ident))
        if distance<=600 and (marks>=3 or actor.r_count==2 or retreat or cluster>=2):
            result.append((10,aim_in_range(actor,dest,600,now),ident))
    elif tank==10000043:
        # No hard-CC exception: the native cast guard decides if R can cleanse.
        if distance<=basic_range(actor,now) and not blocked and not actor.has_buff(317402,now):
            result.append((10,aim_in_range(actor,dest,552,now),ident))
        if distance<=480:result.append((1,aim_in_range(actor,dest,480,now),ident))
        if distance<=940 and not retreat and (target['hp']<.55 or cluster>=2 or controlled):
            result.append((2,dest,ident))
    elif tank==10000069:
        marked=sum(s.get('ai03_marks',0)>=4 and math.dist(pos,s['pos'])<=600 for s in seen)
        if distance<=600 and (marks>=7 or marked>=2 or marks>=4 and target['hp']<.55
                             or distance<360 and (retreat or ratio(actor)<.55)):
            result.append((2,pos,ident))
        if distance<=480 and not actor.spray:result.append((10,aim_in_range(actor,dest,480,now),ident))
        if distance<=basic_range(actor,now) and not actor.has_buff(343201,now):
            result.append((1,pos,actor.id))
    elif tank==10000089:
        if distance<=270 and (not retreat or ratio(actor)<.5):result.append((2,pos,actor.id))
        if retreat and distance<300 or not retreat and 300<distance<600:
            end=jump_point(actor,dest,target,seen,retreat,now)
            if end is not None:result.append((10,end,ident))
        if distance<=600 and not blocked:result.append((1,aim_in_range(actor,dest,600,now),ident))
    return result
