"""Decisions for AI01. Enemy information is restricted to delayed observations."""
import math

from combat_geometry import point_at

TANKS = frozenset((10000003,10000029,10000032,10000041,10000063))
LAST_STAND = {10000003:(1,2),10000029:(1,2,10),10000032:(1,2),
              10000041:(2,10),10000063:(2,10)}


def ratio(actor):
    return float(actor.hp/actor.max_hp)


def desired_range(actor):
    tank=actor.info['tank_id']
    distance=140 if tank==10000003 else 340 if tank==10000029 else 420
    return min(distance,int(actor.stats['nFireRange'])-36)


def aim_in_range(actor,dest,radius,now):
    pos=actor.position_at(now);distance=math.dist(pos,dest)
    return tuple(round(v) for v in point_at(pos,dest,min(1,(radius-8)/max(1,distance))))


def dash_point(actor,direction,length,now):
    """Check the native landing geometry, not other enemies' hidden positions."""
    pos=actor.position_at(now);distance=math.dist(pos,direction)
    if distance<1:return None
    end=actor.move_destination(pos,point_at(pos,direction,length/distance))
    return end if math.dist(pos,end)>=96 else None


def support_choices(actor,allies,seen,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now)
    if tank not in TANKS or not actor.alive:return []
    if getattr(actor,'ready',None) or getattr(actor,'roll',None):return []
    control=actor.blocked('move',now) or actor.blocked('attack',now)
    if tank==10000003:
        threatened=any(math.dist(pos,s['pos'])<=192 for s in seen)
        if control or threatened and ratio(actor)<.8:
            return [(1,pos,actor.id)]
    elif tank==10000029:
        in_range=[a for a in allies if math.dist(pos,a.position_at(now))<=480
                  and not a.is_untargetable()]
        wounded=[a for a in in_range if ratio(a)<.78]
        group=[a for a in wounded if math.dist(pos,a.position_at(now))<=300]
        choices=[]
        if not actor.aura and (len(group)>=2 or any(ratio(a)<.4 for a in group)):
            choices.append((2,pos,actor.id))
        if wounded:
            target=min(wounded,key=lambda a:(ratio(a),-float(a.max_hp-a.hp),a.id))
            choices.append((1,target.position_at(now),target.id))
        return choices
    elif tank==10000032:
        # The native E heals self and the nearest two allies without a range cap.
        recipients=sorted((a for a in actor.arena.actors.values() if a.id!=actor.id
                           and a.camp==actor.camp and a.alive and not a.info.get('map_object')),
                          key=lambda a:(math.dist(pos,a.position_at(now)),a.id))[:2]
        if control or any(ratio(a)<=.78 for a in [actor]+recipients):
            return [(1,pos,actor.id)]
    elif tank==10000063 and ratio(actor)<.55 and not actor.has_buff(338302,now):
        return [(2,pos,actor.id)]
    return []


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now)
    distance=math.dist(pos,target['pos']);ident=target['id'];result=[]
    cluster=sum(math.dist(target['pos'],s['pos'])<=180 for s in seen)
    if tank==10000003:
        if distance<=192:result.append((1,pos,actor.id))
        if not retreat and not blocked and distance<=336:
            result.append((2,dest,ident))
        if retreat and distance<300:
            direction=point_at(pos,target['pos'],-1)
        elif not retreat and 210<distance<450 and not actor.aura:
            direction=dest
        else:direction=None
        end=dash_point(actor,direction,336,now) if direction else None
        if end is not None:result.append((10,end,ident))
    elif tank==10000029:
        # Save the push for peeling a nearby threat or disrupting a group.
        if not blocked and distance<=550 and (distance<300 or retreat or cluster>=2):
            result.append((10,dest,ident))
    elif tank==10000032:
        if distance<=528 and (cluster>=2 or target['hp']<.65 or retreat or distance<360):
            result.append((2,aim_in_range(actor,dest,528,now),ident))
    elif tank==10000041:
        marks=target.get('legolas_marks',0)
        # Fields and the marks in this snapshot are public effects, not live
        # target state. Native execution still checks hits at their actual time.
        rooted=any(f['kind'] in ('root_start','root_tick') and
                   math.dist(f['pos'],target['pos'])<=144 for f in actor.fields.values())
        if distance<=600 and (retreat or distance<280 or marks>=2 or cluster>=2):
            result.append((2,dest,ident))
        if distance<=600 and (rooted or marks>=2 or cluster>=2):
            result.append((10,aim_in_range(actor,dest,600,now),ident))
        if distance<=600 and (marks or actor.e_count==3 or target['hp']<.4 or retreat):
            result.append((1,dest,ident))
    elif tank==10000063:
        if (retreat or distance<250 or actor.blocked('move',now)) and not actor.roll:
            direction=point_at(pos,target['pos'],-1)
            end=dash_point(actor,direction,264,now)
            if end is not None and math.dist(end,target['pos'])>distance+48:
                result.append((10,end,ident))
        if not blocked and distance<=int(actor.stats['nFireRange']) and not actor.has_buff(338302,now):
            if not retreat or ratio(actor)<.75:result.append((2,pos,actor.id))
        if not blocked and distance<=600:result.append((1,dest,ident))
    return result
