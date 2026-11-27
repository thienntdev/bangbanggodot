"""AI10: native rescue forms and HP costs, using delayed enemy observations."""
import math

from bot_ai01 import ratio
from bot_ai04 import mobility,mobility_goal_ok,near
from bot_ai05 import incoming
from melee_common import in_cone

TANKS=frozenset((10000038,10000059,10000070,10000076))
LAST_STAND={10000038:(2,10),10000059:(2,10),10000070:(2,10),10000076:(2,10)}


def observation(actor,target,now):
    if actor.info['tank_id']!=10000070:return {}
    mark=actor.mark
    return {'deadpool_mark':bool(mark and mark['target']==target.id
            and mark['target_generation']==target.generation and target.has_buff(344211,now)
            and target.buff_versions.get(344211)==mark['version'])}


def soul(actor):
    return actor.info['tank_id']==10000038 and bool(actor.soul)


def can_recover(actor):
    # Hellfire, not a repair box, restores Ghost Rider's normal life.
    return not (soul(actor) or getattr(actor,'egg',None) or getattr(actor,'rebirth',None))


def basic_range(actor,now):
    return 168 if soul(actor) else int(actor.stats['nFireRange'])


def desired_range(actor,now):
    return {10000038:140 if soul(actor) else 180,10000059:170,
            10000070:145,10000076:300}[actor.info['tank_id']]


def recast(actor,slot,now):
    if slot!=1:return False
    return (actor.info['tank_id']==10000059 and actor.e_second_until>now or
            actor.info['tank_id']==10000070 and actor.mark and actor.has_buff(344212,now))


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    tank=actor.info['tank_id'];pos=actor.position_at(now);hp=ratio(actor)
    if soul(actor) or getattr(actor,'egg',None) or getattr(actor,'rebirth',None):return []
    threats=[s for s in seen if not s.get('barrier')]
    close=near(pos,threats,400);shot=incoming(actor,brain or {},now)
    if tank==10000059:
        friends=sum(math.dist(pos,a.position_at(now))<=400 for a in allies)
        # Egg spends half max HP: prefer a damaged, supported position or a
        # safe recovery; critical danger can still justify its shield.
        if hp<.55 and (not close or close<=friends or hp<.22):return [(2,pos,actor.id)]
    elif tank==10000070:
        if not actor.has_buff(344101,now) and hp<.45 and (shot or close):return [(10,pos,actor.id)]
    elif tank==10000076:
        if not actor.has_buff(350301,now) and (hp<.65 or actor.blocked('attack',now) and (close or shot)):
            return [(2,pos,actor.id)]
    return []


def marked_choice(actor,brain,seen,now):
    pos=actor.position_at(now)
    target=next((s for s in seen if s.get('deadpool_mark') and math.dist(pos,s['pos'])<=600),None)
    if target is None:return None
    end=actor.blink_destination(pos,target['pos'])
    friends=sum(a.alive and a.camp==actor.camp and not a.info.get('npc_template')
                and math.dist(end,a.position_at(now))<=480 for a in actor.arena.actors.values())
    if not mobility_goal_ok(brain,pos,end) or near(end,seen,360)>friends+1:return None
    if ratio(actor)<.35 and not actor.has_buff(344101,now):return None
    return (1,target['pos'],target['id'])


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);result=[]
    if tank==10000038:
        if actor.soul or actor.channel:return []
        if distance<=192:result.append((10,pos,actor.id))
        if not retreat and distance<=264:result.append((2,dest,ident))
        if 192<distance<=600:result.append((1,dest,ident))
    elif tank==10000059:
        if actor.egg or actor.dash:return []
        if distance<=192:result.append((10,pos,actor.id))
        if retreat and distance<500 or not retreat and 260<distance<600:
            point=mobility(actor,brain,target,seen,dest,retreat,now,432,fixed=True)
            if point is not None:result.append((1,point,ident))
    elif tank==10000070:
        if actor.rebirth or actor.ready:return []
        if not retreat and recast(actor,1,now):
            follow=marked_choice(actor,brain,seen,now)
            if follow:result.append(follow)
        if distance<=168:result.append((2,dest,ident))
        if not recast(actor,1,now) and distance<=600:result.append((1,dest,ident))
    elif tank==10000076:
        # HP is paid even on a miss. Do not spend it on an empty direction,
        # or while retreating at critical HP without the native defensive cap.
        if ratio(actor)<.2 and not actor.has_buff(350301,now):return []
        if in_cone(target['pos'],pos,dest,408,60):result.append((10,dest,ident))
        if 0<distance<=480 and in_cone(target['pos'],pos,dest,480,12):result.append((1,dest,ident))
    return result
