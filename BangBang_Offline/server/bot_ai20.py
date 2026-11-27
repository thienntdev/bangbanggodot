"""Last three native kits; decisions use delayed observations and allied state."""
import math

from bot_ai01 import ratio, aim_in_range
from bot_ai04 import mobility, near
from bot_ai05 import incoming

LAC, MAGNETO, TIME = 10000094, 10000097, 10000113
TANKS = frozenset((LAC, MAGNETO, TIME))
LAST_STAND = {LAC:(2,10,1), MAGNETO:(2,1,10), TIME:(2,10,1)}


def observation(actor,target,now):
    return dict(ai20_tank=not bool(target.info.get('npc_template')),
                time_sleep=target.has_buff(389202,now), magneto_lift=target.has_buff(372202,now))


def recast(actor,slot,now):
    return actor.info['tank_id']==LAC and (slot==1 and now<actor.e_second_until
                                         or slot==2 and actor.form and not actor.form['used'])


def basic_range(actor,now):
    tank=actor.info['tank_id']
    return (480 if actor.form else 336) if tank==LAC else 720 if tank==TIME else 480


def desired_range(actor,now):
    return (340 if actor.form else 180) if actor.info['tank_id']==LAC else 500 if actor.info['tank_id']==TIME else 400


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain if brain is not None else {};pos=actor.position_at(now)
    if actor.info['tank_id']!=TIME:return []
    from timegoddess_actions import clear_line
    friends=[a for a in allies if a.alive and not a.in_stasis() and not a.info.get('npc_template')
             and math.dist(pos,a.position_at(now))<=480 and clear_line(actor,pos,a.position_at(now),now)]
    threatened=[a for a in friends if (near(a.position_at(now),seen,480) or a is actor and incoming(actor,brain,now))
                and not a.has_buff(389301,now)]
    result=[]
    if threatened and (recovering or any(ratio(a)<.65 for a in threatened) or len(seen)>=2):
        target=min(threatened,key=ratio)
        result.append((2,target.position_at(now),target.id))
    wounded=[a for a in friends if ratio(a)<.8]
    if wounded:
        target=min(wounded,key=ratio);point=target.position_at(now)
        # Avoid spending a second guardian on a nearly full isolated ally.
        covered=any(a.alive and a.info.get('npc_template')==389401 and a.camp==actor.camp
                    and math.dist(a.position_at(now),point)<=240 for a in actor.arena.actors.values())
        if not covered or ratio(target)<.4 or len(wounded)>=3:
            result.append((10,point,target.id))
    if actor.mp>=20:
        healable=[a for a in allies if a.id!=actor.id and a.alive and not a.in_stasis()
                  and not a.info.get('npc_template') and ratio(a)<.8
                  and 24<math.dist(pos,a.position_at(now))<=720]
        if healable:
            target=min(healable,key=ratio)
            result.append((0,target.position_at(now),target.id))
    return result


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);distance=math.dist(pos,target['pos']);ident=target['id']
    result=[]
    if tank==LAC:
        if actor.form:
            stacks=actor.buff_stacks.get(387313,0) if actor.has_buff(387313,now) else 0
            if not actor.form['used'] and distance<=600 and (stacks>=4 or actor.form['end']-now<1800 or target['hp']<.2):
                result.append((2,aim_in_range(actor,dest,600,now),ident))
        elif distance<=480 and (not retreat or distance<=240):result.append((2,pos,actor.id))
        if distance<=192:result.append((10,target['pos'],ident))
        second=now<actor.e_second_until
        if distance>180 or retreat or second:
            point=mobility(actor,brain,target,seen,dest,retreat,now,240 if second else 192)
            if point is not None:result.append((1,point,ident))
    elif tank==MAGNETO:
        tanks=[s for s in seen if s.get('ai20_tank')]
        if tanks and not actor.has_buff(372301,now) and (len(tanks)>=2 or target['hp']<.5 or distance<=360):
            result.append((2,pos,actor.id))
        if distance<=600:
            point=aim_in_range(actor,dest,600,now)
            if not target.get('magneto_lift'):result.append((1,point,ident))
            result.append((10,point,ident))
    else:
        if distance<=720 and not target.get('time_sleep'):result.append((1,aim_in_range(actor,dest,720,now),ident))
        if blocked and distance<=720 and actor.mp>=20:
            result.append((0,dest,ident))  # Native projectile can cross map walls.
    return result
