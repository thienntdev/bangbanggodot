"""AI07: delayed aim, native channels, fixed volleys and owned orb combos."""
import math

from bot_ai01 import aim_in_range
from bot_ai04 import mobility,mobility_goal_ok,near
from bot_ai05 import incoming
from combat_geometry import circle_contact,point_at

TANKS=frozenset((10000105,10000112,10000058,10000088,10000098))
LAST_STAND={10000105:(2,10),10000112:(2,1),10000058:(10,2),
            10000088:(10,1),10000098:(10,2)}


def basic_range(actor,now):
    if actor.info['tank_id']==10000105:
        stage=actor._melee(now)
        if stage is not None:return 216 if stage==2 else 192
    return int(actor.stats['nFireRange'])


def desired_range(actor,now):
    tank=actor.info['tank_id']
    if tank==10000105:return 160 if actor._melee(now) is not None or actor.has_buff(380301,now) else 330
    return {10000112:420,10000058:380,10000088:500,10000098:340}[tank]


def recast(actor,slot,now):
    return actor.info['tank_id']==10000112 and slot==10 and bool(actor.channel)


def steer(actor,brain,dest,retreat,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now)
    if tank in (10000112,10000058) and actor.channel:
        actor.channel['dest']=dest  # Same aim operation as native C514.
    if tank!=10000088 or not actor.sweep or retreat:return
    dx,dy=actor.sweep['direction']
    # Move perpendicular to the FIXED volley; never rotate its cast direction.
    lateral=(dest[0]-pos[0])*(-dy)+(dest[1]-pos[1])*dx
    step=max(-96,min(96,lateral))
    point=(round(pos[0]-dy*step),round(pos[1]+dx*step))
    if mobility_goal_ok(brain,pos,point) and actor.arena.geometry.walk_end(pos,point,actor.arena.water_rects(now))==point:
        brain['goal']=point


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain or {};pos=actor.position_at(now);tank=actor.info['tank_id']
    if tank==10000112:
        if actor.channel and not actor.skill_sealed(10,now):
            if recovering or not near(pos,seen,480) or actor.mp<20:
                return [(10,pos,actor.id)]
        # Shared sightings can justify the native global spell; no live enemy scan.
        combat=[s for s in seen if not s.get('structure') and not s.get('barrier')]
        if len(combat)>=2 or any(s['hp']<.4 for s in combat):return [(2,pos,actor.id)]
    if tank==10000088 and not actor.has_buff(362401,now):
        if (near(pos,seen,650) and not recovering or incoming(actor,brain,now)):
            return [(10,pos,actor.id)]
    if tank==10000105 and not actor.has_buff(380401,now) and incoming(actor,brain,now):
        return [(10,pos,actor.id)]
    return []


def safe_chu_e(actor,brain,seen,point,now):
    pos=actor.position_at(now);distance=math.dist(pos,point)
    if not 0<distance<=168 or actor.cc_immune(now):return True
    endpoint=actor.move_destination(pos,point_at(point,pos,1+240/distance))
    return (mobility_goal_ok(brain,pos,endpoint) and
            near(endpoint,seen,216)<=near(pos,seen,216))


def ground_orbs(actor):
    from simayi_actions import SimaOrb
    return [a for a in actor.arena.actors.values() if isinstance(a,SimaOrb)
            and a.alive and a.info['owner']==actor.id]


def push_aim(actor,orbs,dest,now):
    pos=actor.position_at(now)
    for orb in orbs:
        start=orb.position_at(now);distance=math.dist(pos,start)
        if not 0<distance<=384 or orb.push:continue
        end=point_at(pos,start,1+480/distance)
        if circle_contact(start,end,dest,dest,60) is not None:return start
    return None


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);cluster=near(target['pos'],seen,180);result=[]
    if tank==10000105:
        if actor._melee(now) is not None and distance<=basic_range(actor,now):
            result.append((0,dest,ident))
        if retreat and distance<360 or not retreat and 220<distance<600:
            point=mobility(actor,brain,target,seen,dest,retreat,now,480)
            if point is not None:result.append((1,point,ident))
        if distance<=250 and not actor.has_buff(380401,now):result.append((10,dest,ident))
        if distance<=240 and (not retreat or distance<160):result.append((2,dest,ident))
    elif tank==10000112:
        if distance<=600:
            point=aim_in_range(actor,dest,480,now)
            if safe_chu_e(actor,brain,seen,point,now):result.append((1,point,ident))
        if not actor.channel and not retreat and distance<=450 and actor.mp>=30:
            result.append((10,dest,ident))
    elif tank==10000058:
        if distance<=600:result.append((1,dest,ident))
        if distance<=460:result.append((10,dest,ident))
        if not actor.channel and distance<=570 and actor.mp>=50 and (cluster>=2 or distance<=420):
            result.append((2,dest,ident))
    elif tank==10000088:
        if distance<=600:result.append((1,aim_in_range(actor,dest,600,now),ident))
        if not retreat and not actor.sweep and distance<=800 and (cluster>=2 or distance<=600):
            result.append((2,dest,ident))
    elif tank==10000098:
        orbs=ground_orbs(actor);push=push_aim(actor,orbs,dest,now)
        if push is not None:result.append((10,push,ident))
        elif distance<=360:result.append((10,dest,ident))
        if distance<=720 and actor.orb_count+len(orbs)>= (1 if target['hp']<.3 else 2):
            result.append((2,dest,ident))
        if distance<=600:
            result.append((1,aim_in_range(actor,dest,600,now),ident))
    return result
