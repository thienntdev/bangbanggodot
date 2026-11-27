"""AI09: stealth approach/escape and native follow-ups from delayed sightings."""
import math

from bot_ai01 import ratio,aim_in_range
from bot_ai04 import mobility,mobility_goal_ok,near
from bot_ai05 import incoming
from combat_geometry import point_at
from melee_common import aimed

TANKS=frozenset((10000048,10000030,10000071,10000114,10000108))
LAST_STAND={tank:(2,10) for tank in TANKS}


def observation(actor,target,now):
    result={'ai09_tank':not bool(target.info.get('npc_template'))}
    if actor.info['tank_id']==10000048:
        mark=actor.marks.get(target.id)
        result['assassin_mark']=bool(mark and mark['target_generation']==target.generation
                                     and target.has_buff(322404,now))
    return result


def desired_range(actor,now):
    return {10000048:220,10000030:240,10000071:330,10000114:220,10000108:200}[actor.info['tank_id']]


def recast(actor,slot,now):
    return actor.info['tank_id']==10000048 and slot==2 and actor.has_buff(322302,now)


def hidden(actor,now):
    return any(actor.has_buff(buff,now) for buff in {
        10000048:(322201,),10000030:(305202,),10000071:(451403,),
        10000114:(390201,390304),10000108:()}[actor.info['tank_id']])


def hold_stealth(actor,target,retreat,now):
    if not hidden(actor,now):return False
    if retreat:return True
    reach=desired_range(actor,now)+60
    if target.get('structure') or target.get('barrier'):reach=int(actor.stats['nFireRange'])
    return math.dist(actor.position_at(now),target['pos'])>reach


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain or {};tank=actor.info['tank_id'];pos=actor.position_at(now)
    if tank not in (10000048,10000030,10000114) or hidden(actor,now):return []
    # Own channel state is known; do not waste E while Night Wing is already
    # under Space stealth or its ghosts are still doing the work.
    if tank==10000114 and actor.channel and actor.channel['end']>now:return []
    combat=[s for s in seen if s.get('ai09_tank')]
    distance=min((math.dist(pos,s['pos']) for s in combat),default=10000)
    if distance<600 and (recovering or incoming(actor,brain,now) or 300<distance<600):
        return [(1,pos,actor.id)]
    return []


def stab_choice(actor,brain,seen,cursor,now):
    """Predict native cursor/HP priority using only the last delivered sample."""
    pos=actor.position_at(now)
    tanks=[s for s in seen if s.get('ai09_tank') and 0<math.dist(pos,s['pos'])<=300]
    close=[s for s in tanks if math.dist(cursor,s['pos'])<=72]
    target=(min(close,key=lambda s:(math.dist(cursor,s['pos']),math.dist(pos,s['pos']),s['id'])) if close else
            min(tanks,key=lambda s:(s['hp'],math.dist(pos,s['pos']),s['id'])) if tanks else None)
    if target is None:return None
    # The second leg continues 240 beyond the contact. Check that endpoint too.
    end=actor.move_destination(target['pos'],aimed(pos,target['pos'],math.dist(pos,target['pos'])+240,fixed=True))
    friends=sum(a.alive and a.camp==actor.camp and not a.info.get('npc_template')
                and math.dist(end,a.position_at(now))<=480 for a in actor.arena.actors.values())
    if not mobility_goal_ok(brain,pos,end) or near(end,seen,360)>friends+1:return None
    return (2,cursor,target['id'])


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);result=[]
    if tank==10000048:
        if actor.ready or actor.dash:return []
        if not retreat and recast(actor,2,now):
            stab=stab_choice(actor,brain,seen,dest,now)
            if stab:
                if not target.get('assassin_mark') and distance<=600:result.append((10,dest,ident))
                result.append(stab)
        elif retreat and distance<420 or not retreat and 320<distance<550:
            point=mobility(actor,brain,target,seen,dest,retreat,now,240,fixed=True)
            if point is not None and not recast(actor,2,now):result.append((2,point,ident))
        if distance<=600:result.append((10,dest,ident))
        if not hidden(actor,now) and not retreat and 180<distance<=300:result.append((1,pos,actor.id))
    elif tank==10000030:
        if actor.channel:return []  # Its five darts keep the vector captured by native R.
        if distance<=240:
            end=actor.move_destination(pos,aimed(pos,point_at(pos,dest,-1),192,fixed=True))
            if math.dist(pos,end)>=72 and mobility_goal_ok(brain,pos,end) and near(end,seen,300)<=near(pos,seen,300):
                result.append((2,dest,ident))
        if distance<=600:result.append((10,dest,ident))
    elif tank==10000071:
        if retreat and distance<450 or distance<230 and (incoming(actor,brain,now) or ratio(actor)<.65):
            point=mobility(actor,brain,target,seen,dest,True,now,336,blink=True)
            if point is not None:result.append((10,point,ident))
        if distance<=600:result.append((1,aim_in_range(actor,dest,600,now),ident))
        if distance<=650 and (target['hp']<.65 or near(target['pos'],seen,180)>=2 or math.hypot(*target['velocity'])>50):
            result.append((2,dest,ident))
    elif tank==10000114:
        if actor.ready:return []
        if actor.has_buff(390204,now) and distance<=280 and not blocked:result.append((0,dest,ident))
        if distance<=480 and (target['hp']<.65 or ratio(actor)<.65 or distance<320):result.append((2,dest,ident))
        if distance<=408:result.append((10,dest,ident))
        if not hidden(actor,now) and distance<=280:result.append((1,pos,actor.id))
    elif tank==10000108:
        if actor.ready or actor.dash:return []
        if actor.has_buff(383203,now) and distance<=int(actor.stats['nFireRange']):result.append((0,dest,ident))
        if distance<=216:result.append((10,pos,actor.id))
        if retreat and distance<450 or not retreat and 260<distance<650:
            point=mobility(actor,brain,target,seen,dest,retreat,now,720)
            if point is not None:result.append((2,point,ident))
        if retreat and distance<400 or not retreat and distance>240 or not retreat and not actor.has_buff(383203,now):
            point=mobility(actor,brain,target,seen,dest,retreat,now,240,blink=True)
            if point is not None:result.append((1,point,ident))
    return result
