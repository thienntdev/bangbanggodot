"""AI12: native forms, shared/banked cooldowns and delayed enemy sightings."""
import math

from bot_ai01 import ratio,aim_in_range
from bot_ai04 import mobility,mobility_goal_ok,near
from bot_ai11 import safe_endpoint

TANKS=frozenset((10000061,10000092,10000044,10000093))
LAST_STAND={10000061:(1,2),10000092:(1,2),10000044:(1,10),10000093:(1,2,10)}


def observation(actor,target,now):
    result={'ai12_tank':not bool(target.info.get('npc_template'))}
    if actor.info['tank_id']==10000092:
        result['hades_mark']=any(target.has_buff(t,now) and target.buff_sources.get(t)==actor.id for t in range(367203,367207))
    if actor.info['tank_id']==10000093:
        result['sasuke_counter']=target.has_buff(368405,now) and target.buff_sources.get(368405)==actor.id
    return result


def basic_range(actor,now):
    if actor.info['tank_id']==10000092 and actor.melee:return 168
    return int(actor.stats['nFireRange'])


def desired_range(actor,now):
    tank=actor.info['tank_id']
    if tank==10000092:return 120 if actor.melee else 330
    if tank==10000061:return 190 if actor.fallen else 300
    return min(380 if tank==10000044 else 280,basic_range(actor,now)-36)


def recast(actor,slot,now):
    return actor.info['tank_id']==10000093 and (slot==2 and actor.has_buff(368304,now) or slot==10 and actor.has_buff(368404,now))


def hold_stealth(actor,retreat,now):
    return actor.info['tank_id']==10000093 and retreat and actor.has_buff(368403,now)


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain or {};tank=actor.info['tank_id'];pos=actor.position_at(now);hp=ratio(actor)
    if getattr(actor,'ready',None) or getattr(actor,'vanish',None) or getattr(actor,'dash',None):return []
    if tank==10000061:
        if actor.sanctuary:return []  # It can walk; native cast guard owns the one-second attack lock.
        if not actor.fallen:
            result=[]
            wounded=[a for a in allies if math.dist(pos,a.position_at(now))<=240 and ratio(a)<.6]
            if wounded and near(pos,seen,480) or hp<.45 and near(pos,seen,360):result.append((2,pos,actor.id))
            if hp<.85 or any(ratio(a)<.8 and math.dist(pos,a.position_at(now))<=336 for a in allies):result.append((1,pos,actor.id))
            return result
        elif (recovering or hp<.45) and seen:
            target=min(seen,key=lambda s:math.dist(pos,s['pos']))
            point=mobility(actor,brain,target,seen,target['pos'],True,now,360,fixed=True)
            if point is not None:return [(10,point,target['id'])]
    if tank==10000092 and actor.melee and (recovering or hp<.28):return [(10,pos,actor.id)]
    if tank==10000093 and not actor.has_buff(368403,now) and not recast(actor,10,now):
        if not actor.has_buff(368401,now) and near(pos,seen,480) and (hp<.75 or near(pos,seen,280)):
            return [(10,pos,actor.id)]
    return []


def counter_choice(actor,brain,seen,now,retreat):
    if retreat or not recast(actor,10,now) or not actor.counter:return None
    mark=actor.counter;pos=actor.position_at(now)
    target=next((s for s in seen if s['id']==mark['target'] and s['generation']==mark['target_generation']
                 and s.get('sasuke_counter') and math.dist(pos,s['pos'])<=720),None)
    if target is None:return None
    dx,dy=mark['vector'];length=max(1,math.hypot(dx,dy))
    end=actor.blink_destination(pos,(round(target['pos'][0]-72*dx/length),round(target['pos'][1]-72*dy/length)))
    return (10,target['pos'],target['id']) if safe_endpoint(actor,brain,seen,end,now) else None


def structure_choices(actor,brain,target,seen,dest,now):
    # Do not waste burst spells on buildings with 90% skill mitigation.
    if actor.info['tank_id']==10000044 and not actor.shots and actor.mp>=25:return [(1,dest,target['id'])]
    return []


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);result=[]
    if getattr(actor,'ready',None) or getattr(actor,'vanish',None) or getattr(actor,'dash',None):return []
    if tank==10000061:
        if actor.sanctuary or actor.motion and actor.motion_kind!=0 and actor.motion[3]>now:return []
        if actor.fallen:
            if distance<=216:result.append((2,pos,actor.id))
            if distance<=408:result.append((1,dest,ident))
        else:
            if distance<=336:result.append((1,pos,actor.id))
            if not retreat and ratio(actor)>.65 and 240<distance<550:
                point=mobility(actor,brain,target,seen,dest,False,now,360,fixed=True)
                if point is not None:result.append((10,point,ident))
    elif tank==10000092:
        if actor.melee:
            if not retreat and distance<=192:result.append((1,dest,ident))
            if retreat or distance>360:result.append((10,pos,actor.id))
        else:
            if distance<=480:result.append((1,dest,ident))
            if not retreat and distance<=180 and ratio(actor)>.35:result.append((10,pos,actor.id))
        if not retreat and 180<distance<=480 and (target.get('hades_mark') or near(target['pos'],seen,264)>=2 or target['hp']<.5):
            end=actor.blink_destination(pos,target['pos'])
            if safe_endpoint(actor,brain,seen,end,now):result.append((2,dest,ident))
    elif tank==10000044:
        # Finish the four native piercing shots before refreshing E or spending
        # another preparation window; hits own chakra and cooldown refunds.
        if actor.shots and actor.has_buff(318201,now) and distance<=basic_range(actor,now):result.append((0,dest,ident))
        if distance<=basic_range(actor,now) and not actor.shots:result.append((1,dest,ident))
        if distance<=600 and (near(target['pos'],seen,144)>=2 or target['hp']<.65 or distance<420):
            result.append((2,aim_in_range(actor,dest,600,now),ident))
        if retreat or 190<distance<=480:
            point=mobility(actor,brain,target,seen,dest,retreat,now,480)
            if point is not None:
                # R retreats 240 after contact. Protect the mode goal for that
                # second leg too, using the observed target, not live positions.
                length=max(1,math.dist(pos,point));dx=(point[0]-pos[0])/length;dy=(point[1]-pos[1])/length
                back=actor.move_destination(target['pos'],(target['pos'][0]-240*dx,target['pos'][1]-240*dy))
                if retreat or mobility_goal_ok(brain,pos,back):result.append((10,point,ident))
    elif tank==10000093:
        if hold_stealth(actor,retreat,now):return []
        counter=counter_choice(actor,brain,seen,now,retreat)
        if counter:result.append(counter)
        if recast(actor,2,now) and distance<=600:result.append((2,aim_in_range(actor,dest,600,now),ident))
        elif not actor.has_buff(368301,now) and actor.mp>=100 and (distance<=192 or near(pos,seen,360)>=2 and ratio(actor)<.6):
            result.append((2,pos,actor.id))
        if retreat or 200<distance<=560:
            point=mobility(actor,brain,target,seen,dest,retreat,now,432,fixed=True)
            if point is not None:result.append((1,point,ident))
    return result
