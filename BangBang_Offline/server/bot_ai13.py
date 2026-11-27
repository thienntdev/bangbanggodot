"""AI13: observed marks, native ammunition and fixed-direction charged casts."""
import math

from bot_ai01 import ratio,aim_in_range
from bot_ai04 import mobility,near
from bot_ai11 import safe_endpoint
from melee_common import in_cone

TANKS=frozenset((10000049,10000053,10000090,10000104,10000102))
LAST_STAND={10000049:(1,2,10),10000053:(1,2),10000090:(2,10),10000104:(1,10),10000102:(2,10)}


def observation(actor,target,now):
    result={}
    if actor.info['tank_id']==10000049:
        for name,template in (('transformer_e',324203),('transformer_r',324402),('transformer_combo',324413)):
            result[name]=target.has_buff(template,now) and target.buff_sources.get(template)==actor.id
    if actor.info['tank_id']==10000104:
        result['falcon_mark']=target.has_buff(379302,now) and target.buff_sources.get(379302)==actor.id
    return result


def desired_range(actor,now):
    tank=actor.info['tank_id']
    if tank==10000090:return 160 if actor.aura else 300
    return min({10000049:410,10000053:170,10000104:370,10000102:240}[tank],int(actor.stats['nFireRange'])-36)


def recast(actor,slot,now):
    return actor.info['tank_id']==10000102 and slot==2 and actor.ready and actor.ready['slot']==2


def falcon_reload_dash(actor,brain,seen,dest,now):
    # Reload/empower without diving into the target or leaving a held objective.
    pos=actor.position_at(now);dx=dest[0]-pos[0];dy=dest[1]-pos[1];length=max(1,math.hypot(dx,dy))
    side=1 if actor.id%2 else -1
    for sign in (side,-side):
        point=actor.arena.geometry.clamp_tank_position((pos[0]-sign*dy/length*96,pos[1]+sign*dx/length*96))
        end=actor.move_destination(pos,point)
        if math.dist(pos,end)>=72 and safe_endpoint(actor,brain,seen,end,now):return point
    return None


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain or {};tank=actor.info['tank_id'];pos=actor.position_at(now)
    if recast(actor,2,now):
        cast=actor.ready;elapsed=now-cast['begin']
        # The original charge stores its direction. Do not rotate it towards a
        # newly sampled enemy, including after loading a checkpoint.
        reach=240+360*min(1,elapsed/3000)
        contact=any(in_cone(s['pos'],pos,cast['dest'],reach,60) for s in seen)
        if elapsed>=750 and (contact or recovering or not seen):return [(2,cast['dest'],actor.id)]
        return []
    if getattr(actor,'ready',None) or getattr(actor,'dash',None):return []
    if tank==10000090 and not actor.aura and ratio(actor)<.5:return [(2,pos,actor.id)]
    if recovering and seen and tank in (10000053,10000090,10000104,10000102):
        target=min(seen,key=lambda s:math.dist(pos,s['pos']))
        slot,length,fixed={10000053:(1,480,False),10000090:(10,336,False),10000104:(1,336,False),10000102:(1,480,True)}[tank]
        point=mobility(actor,brain,target,seen,target['pos'],True,now,length,fixed=fixed)
        if point is not None:return [(slot,point,target['id'])]
    return []


def structure_choices(actor,brain,target,seen,dest,now):
    if actor.info['tank_id']==10000104 and not actor.enhanced:
        point=falcon_reload_dash(actor,brain,seen,dest,now)
        if point is not None:return [(1,point,target['id'])]
    return []


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    if getattr(actor,'ready',None) or getattr(actor,'dash',None):return []
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);result=[]
    if tank==10000049:
        if target.get('transformer_combo') and distance<=960:result.append((2,aim_in_range(actor,dest,960,now),ident))
        if target.get('transformer_e') and distance<=720:result.append((10,dest,ident))
        if target.get('transformer_r') and distance<=720:result.append((1,dest,ident))
        if distance<=720:result.extend(((1,dest,ident),(10,dest,ident)))
        if distance<=960 and (near(target['pos'],seen,192)>=2 or target['hp']<.5):
            result.append((2,aim_in_range(actor,dest,960,now),ident))
    elif tank==10000053:
        if distance<=240:
            # Space chooses the nearest visible enemy itself. Toss towards the
            # visible cluster, or back to our position for the team to follow up.
            closest=min(seen,key=lambda s:(math.dist(pos,s['pos']),s['id']))
            point=closest['pos'] if near(closest['pos'],seen,120)>=2 else pos
            result.append((2,point,closest['id']))
        if retreat or 200<distance<=560:
            point=mobility(actor,brain,target,seen,dest,retreat,now,480)
            if point is not None:result.append((1,point,ident))
    elif tank==10000090:
        if not actor.aura and distance<=300:result.append((2,pos,actor.id))
        if distance<=(528 if actor.has_buff(365405,now) else 480):result.append((1,dest,ident))
        if retreat or 170<distance<=480:
            point=mobility(actor,brain,target,seen,dest,retreat,now,336)
            if point is not None:result.append((10,point,ident))
    elif tank==10000104:
        if retreat:
            point=mobility(actor,brain,target,seen,dest,True,now,336)
            if point is not None:result.append((1,point,ident))
        if distance<=int(actor.stats['nFireRange']):
            if not actor.enhanced and (actor.mp<=30 or not retreat):
                point=falcon_reload_dash(actor,brain,seen,dest,now)
                if point is not None:result.append((1,point,ident))
            if distance<=600:result.append((10,aim_in_range(actor,dest,600,now),ident))
            if not target.get('falcon_mark') and actor.mp>=30:result.append((2,dest,ident))
            if not blocked:result.append((0,dest,ident))
    elif tank==10000102:
        if distance<=360:result.append((10,dest,ident))
        if not retreat and distance<=540 and actor.mp>=60:
            result.append((2,dest,ident))
        if retreat or 280<distance<=540:
            point=mobility(actor,brain,target,seen,dest,retreat,now,480,fixed=True)
            if point is not None:result.append((1,point,ident))
    return result
