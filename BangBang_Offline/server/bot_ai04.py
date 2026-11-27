"""AI04 frontliners: native mobility, paid auras and delayed enemy sightings."""
import math

from bot_ai01 import aim_in_range,ratio
from combat_geometry import point_at
from melee_common import aimed

TANKS=frozenset((10000034,10000036,10000046,10000066,10000103))
LAST_STAND={10000034:(2,10),10000036:(2,10),10000046:(1,2),
            10000066:(2,10),10000103:(2,10)}


def basic_range(actor,now):
    if actor.info['tank_id']==10000036 and actor.has_buff(310111,now):return 192
    return int(actor.stats['nFireRange'])


def desired_range(actor,now):
    tank=actor.info['tank_id']
    if tank==10000034:return 140
    if tank==10000036:return 135
    if tank==10000046:return 250
    if tank==10000103:return 180
    return 90 if actor.channel or actor.mp>=30 and ratio(actor)>.4 and actor.cooldowns[1]<=now else 340


def near(pos,seen,radius):
    return sum(math.dist(pos,s['pos'])<=radius for s in seen if not s.get('barrier'))


def mobility(actor,brain,target,seen,dest,retreat,now,length,*,fixed=False,blink=False):
    """Evaluate the actual endpoint; do not read hidden enemies to rank it."""
    pos=actor.position_at(now);distance=math.dist(pos,target['pos'])
    direction=point_at(pos,target['pos'],-1) if retreat else dest
    direction=actor.arena.geometry.clamp_tank_position(direction)
    if math.dist(pos,direction)<1:return None
    requested=aimed(pos,direction,length,fixed=fixed)
    endpoint=(actor.blink_destination if blink else actor.move_destination)(pos,requested)
    if math.dist(pos,endpoint)<72:return None
    if not mobility_goal_ok(brain,pos,endpoint):return None
    after=math.dist(endpoint,target['pos'])
    if retreat:
        if after<distance+72:return None
    else:
        if after>200 or after>distance-60:return None
        friends=sum(a.alive and a.camp==actor.camp and not a.info.get('npc_template')
                    and math.dist(endpoint,a.position_at(now))<=480 for a in actor.arena.actors.values())
        if ratio(actor)<.45 or near(endpoint,seen,360)>friends+1:return None
    # Fixed dashes must retain the input direction; a clipped endpoint would
    # otherwise be extended to full length a second time in native cast.
    return direction if fixed else tuple(round(v) for v in requested)


def support_choices(actor,allies,seen,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now)
    if tank==10000034 and not actor.has_buff(308601,now):
        if ratio(actor)<.45 or ratio(actor)<.8 and near(pos,seen,300):return [(2,pos,actor.id)]
    if tank==10000066:
        combat=[s for s in seen if not s.get('barrier') and not s.get('structure')]
        if actor.channel:
            if actor.mp<20 or not near(pos,combat,200):return [(1,pos,actor.id)]
        elif actor.mp>=30 and near(pos,combat,140):return [(1,pos,actor.id)]
    return []


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);cluster=near(target['pos'],seen,180);result=[]
    if tank==10000034:
        if distance<=190:result.append((10,pos,actor.id))
        if retreat and distance<320 or not retreat and 220<distance<550:
            point=mobility(actor,brain,target,seen,dest,retreat,now,408)
            if point is not None:result.append((1,point,ident))
    elif tank==10000036:
        # Let E carry the bot into reach before a new cast cuts it short.
        if actor.has_buff(310211,now) and distance>192:return []
        if not retreat and not blocked and distance<=185 and actor.has_buff(310111,now):
            result.append((0,dest,ident))
        if distance<=210:result.append((10,pos,actor.id))
        if retreat and distance<320 or not retreat and 220<distance<560:
            point=mobility(actor,brain,target,seen,dest,retreat,now,384,fixed=True)
            if point is not None:result.append((1,point,ident))
        if retreat and distance<260:
            point=mobility(actor,brain,target,seen,dest,True,now,264,blink=True)
            if point is not None:result.append((2,point,ident))
        elif not retreat and distance<=430 and (cluster>=2 or target['hp']<.55 or distance<200):
            point=aim_in_range(actor,dest,264,now)
            endpoint=actor.blink_destination(pos,point)
            if math.dist(endpoint,target['pos'])<=185 and mobility_goal_ok(brain,pos,endpoint):
                result.append((2,point,ident))
    elif tank==10000046:
        if distance<=335 and (not retreat or actor.has_buff(320101,now)):
            result.append((2,aim_in_range(actor,dest,360,now),ident))
        if distance<=350:result.append((1,aim_in_range(actor,dest,360,now),ident))
    elif tank==10000066:
        if actor.forced_until>now:return []
        escape=retreat or distance<300 and (ratio(actor)<.45 or actor.blocked('attack',now))
        if escape and distance<360 or not escape and 200<distance<520:
            point=mobility(actor,brain,target,seen,dest,escape,now,336,fixed=True)
            if point is not None:result.append((10,point,ident))
        elif distance<240 and (ratio(actor)<.65 or actor.mp<40):
            point=mobility(actor,brain,target,seen,dest,True,now,336,fixed=True)
            if point is not None:result.append((10,point,ident))
        if distance<=590 and (cluster>=2 or target['hp']<.65 or ratio(actor)<.65 or actor.mp<40):
            result.append((2,aim_in_range(actor,dest,600,now),ident))
    elif tank==10000103:
        if distance<=235:result.append((10,pos,actor.id))
        if retreat and distance<320 or not retreat and 210<distance<520:
            point=mobility(actor,brain,target,seen,dest,retreat,now,408)
            if point is not None:result.append((1,point,ident))
        if distance<=680 and (cluster>=2 or target['hp']<.6 or retreat or distance<300):
            result.append((2,aim_in_range(actor,dest,720,now),ident))
    return result


def mobility_goal_ok(brain,pos,endpoint):
    if brain.get('objective') not in ('flag_hold','bomb_escort','bomb_intercept','survive','base_defend'):return True
    goal=brain.get('goal',pos)
    return math.dist(endpoint,goal)<=max(144,math.dist(pos,goal))
