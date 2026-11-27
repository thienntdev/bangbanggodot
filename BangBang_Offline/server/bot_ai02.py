"""AI02 support choices. Enemy inputs are delayed, shared observations only."""
import math

from bot_ai01 import aim_in_range, ratio
from combat_geometry import point_at

TANKS=frozenset((10000002,10000037,10000073,10000085))
LAST_STAND={10000002:(2,10),10000037:(1,2),10000073:(2,10),10000085:(1,2)}


def friends(actor,now,radius):
    pos=actor.position_at(now)
    return [a for a in actor.arena.actors.values() if a.alive and a.camp==actor.camp
            and not a.info.get('npc_template') and not a.is_untargetable()
            and math.dist(pos,a.position_at(now))<=radius]


def threats(pos,seen,radius=360):
    return sum(math.dist(pos,s['pos'])<=radius for s in seen if not s.get('barrier'))


def controlled(actor,now):
    return bool(actor.buff_types(now)&{30,35,36,62,66})


def desired_range(actor):
    tank=actor.info['tank_id']
    if tank==10000002:return 155 if actor.drain else 300
    if tank==10000073:return 100 if actor.form else 350
    return min(420,int(actor.stats['nFireRange'])-36)


def field_point(actor,allies,seen,now,reach):
    """A few ally-centered candidates; never inspect a hidden enemy's pose."""
    pos=actor.position_at(now)
    points=[pos]+[aim_in_range(actor,a.position_at(now),reach,now) for a in allies]
    scored=[]
    for point in points:
        if not actor._inside(point):continue
        covered=[a for a in allies if math.dist(point,a.position_at(now))<=240]
        wounded=[a for a in covered if ratio(a)<.8]
        pressure=threats(point,seen,264)
        if not (len(wounded)>=2 or any(ratio(a)<.55 for a in wounded)
                or pressure>=2 and len(covered)>=2):continue
        score=sum((1-ratio(a))*4+int(controlled(a,now)) for a in covered)+pressure*.35
        scored.append((score,-math.dist(pos,point),point))
    return max(scored)[2] if scored else None


def support_choices(actor,allies,seen,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now)
    if tank not in TANKS or not actor.alive:return []
    # Cancelling a live tether is legal even during CC; no new cast is needed.
    if tank==10000073 and actor.link:
        target=actor.arena.actors.get(actor.link['target'])
        if target and (ratio(actor)>.97 and ratio(target)>.97 or actor.mp<10):
            return [(10,pos,target.id)]
    if getattr(actor,'ready',None) or getattr(actor,'dash',None):return []
    result=[]
    allies=friends(actor,now,1200 if tank==10000073 else 600)
    if tank==10000002:
        point=field_point(actor,allies,seen,now,360)
        if point is not None and not actor.fields:result.append((2,point,0))
    elif tank==10000037:
        point=field_point(actor,allies,seen,now,480)
        if point is not None:result.append((2,point,0))
        eligible=[a for a in allies if math.dist(pos,a.position_at(now))<=480
                  and not a.has_buff(311201,now)
                  and (ratio(a)<.85 or threats(a.position_at(now),seen,360))]
        if eligible:
            target=min(eligible,key=lambda a:(ratio(a)-.12*threats(a.position_at(now),seen,240),a.id))
            result.append((1,target.position_at(now),target.id))
    elif tank==10000073:
        others=[a for a in allies if a is not actor]
        rescue=[a for a in others if threats(a.position_at(now),seen,360)
                and ratio(a)<.65 and (ratio(actor)>=.35 or
                    threats(a.position_at(now),seen,240)<threats(pos,seen,240))]
        escape=[a for a in others if ratio(actor)<.4 and threats(pos,seen,300)
                and math.dist(pos,a.position_at(now))>=180
                and not threats(a.position_at(now),seen,420)]
        if not actor.form and (rescue or escape):
            target=min(rescue or escape,key=lambda a:(ratio(a),math.dist(pos,a.position_at(now)),a.id))
            result.append((2,target.position_at(now),target.id))
        if not actor.link and actor.mp>=30:
            eligible=[a for a in others if math.dist(pos,a.position_at(now))<=336
                      and (ratio(a)<.8 or ratio(actor)<.8)]
            if eligible:
                target=min(eligible,key=lambda a:(ratio(a),math.dist(pos,a.position_at(now)),a.id))
                result.append((10,target.position_at(now),target.id))
    elif tank==10000085:
        eligible=[a for a in allies if math.dist(pos,a.position_at(now))<=480]
        urgent=[a for a in eligible if ratio(a)<.32 and not a.has_buff(359301,now)
                and threats(a.position_at(now),seen,480)]
        if urgent:
            target=min(urgent,key=lambda a:(ratio(a),a.id))
            result.append((2,target.position_at(now),target.id))
        shield=[a for a in eligible if not a.has_buff(359201,now) and
                (controlled(a,now) or ratio(a)<.72 or
                 ratio(a)<.9 and threats(a.position_at(now),seen,360))]
        if shield:
            target=min(shield,key=lambda a:(ratio(a)-.25*controlled(a,now),a.id))
            result.append((1,target.position_at(now),target.id))
    return result


def turret_point(actor,target,now):
    pos=actor.position_at(now);dest=target['pos'];distance=math.dist(pos,dest)
    center=point_at(pos,dest,min(240,max(0,distance-220))/max(1,distance))
    allies=[a.position_at(now) for a in friends(actor,now,600)]
    existing=[a.position_at(now) for a in actor.arena.actors.values()
              if a.alive and a.info.get('owner')==actor.id and a.info.get('npc_template')==20017]
    candidates=[]
    for dx,dy in ((0,0),(96,0),(-96,0),(0,96),(0,-96),(72,72),(-72,72),(72,-72),(-72,-72)):
        point=tuple(round(v) for v in (center[0]+dx,center[1]+dy))
        geometry=actor.arena.geometry
        if (math.dist(pos,point)>336 or math.dist(point,dest)>350
                or any(math.dist(point,p)<72 for p in allies+existing)
                or geometry.clamp_tank_position(point)!=point
                or geometry.wall_contact(point,point,36) is not None
                or geometry.wall_contact(point,dest) is not None):continue
        candidates.append((abs(math.dist(point,dest)-220),math.dist(pos,point),point))
    return min(candidates)[2] if candidates else None


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now)
    distance=math.dist(pos,target['pos']);result=[]
    if tank==10000002:
        if distance<=192 and not actor.drain:result.append((10,pos,actor.id))
        if distance<=480:result.append((1,aim_in_range(actor,dest,480,now),target['id']))
        if distance<=550 and (target['hp']<.55 or threats(target['pos'],seen,240)>=2):
            result.append((2,aim_in_range(actor,dest,360,now),0))
    elif tank==10000037 and not blocked and not retreat and distance<=650:
        point=turret_point(actor,target,now)
        if point is not None:result.append((10,point,0))
    elif tank==10000073:
        if distance<=600:result.append((1,aim_in_range(actor,dest,600,now),target['id']))
        # Use the form offensively only around an ally already in combat.
        if not retreat and not actor.form and ratio(actor)>.55:
            front=[a for a in friends(actor,now,1200) if a is not actor
                   and math.dist(a.position_at(now),target['pos'])<=216]
            if front:
                ally=min(front,key=lambda a:(math.dist(a.position_at(now),target['pos']),a.id))
                result.append((2,ally.position_at(now),ally.id))
    elif tank==10000085 and distance<=600 and actor.mp>=50 and actor.r_count:
        if actor.mp>=100 or target['hp']<.65 or retreat:
            result.append((10,pos,target['id']))
    return result


def adjust_goal(actor,brain,seen,now,recovering=False):
    """Stay close enough to help, without abandoning a contested mode goal."""
    tank=actor.info['tank_id']
    if tank not in TANKS or recovering or brain.get('objective') in (
            'flag_hold','survive','base_defend','bomb_escort','bomb_intercept'):return
    pos=actor.position_at(now)
    if tank==10000073 and actor.link:
        target=actor.arena.actors.get(actor.link['target'])
        if target and target.alive and (ratio(target)<.95 or ratio(actor)<.95):
            point=target.position_at(now)
            if math.dist(pos,point)>240 and threats(point,seen,240)<=threats(pos,seen,240):
                brain['goal']=point_at(point,pos,192/max(1,math.dist(pos,point)))
                return
    if seen:return
    wounded=[a for a in friends(actor,now,600) if a is not actor and ratio(a)<.6]
    if wounded:
        target=min(wounded,key=lambda a:(ratio(a),a.id));point=target.position_at(now)
        if math.dist(pos,point)>300:
            brain['goal']=point_at(point,pos,240/math.dist(pos,point))
