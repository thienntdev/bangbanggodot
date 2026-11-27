"""AI15: native wards, sustain, earned bursts and dog/three-phase recasts."""
import math

from bot_ai01 import ratio
from bot_ai04 import mobility,near
from bot_ai05 import incoming
from bot_ai11 import safe_endpoint
from combat_geometry import point_at

PEGASUS,WOLF,APOC,ERLANG=10000035,10000040,10000072,10000087
TANKS=frozenset((PEGASUS,WOLF,APOC,ERLANG))
LAST_STAND={PEGASUS:(1,2),WOLF:(2,10),APOC:(10,2),ERLANG:(10,2)}


def observation(actor,target,now):
    if actor.info['tank_id']==ERLANG:
        return dict(erlang_mark=target.has_buff(361403,now) and target.buff_sources.get(361403)==actor.id)
    return {}


def desired_range(actor,now):
    tank=actor.info['tank_id']
    if tank==PEGASUS:return 110 if actor.vanish else 180
    return {WOLF:135,APOC:400,ERLANG:145}[tank]


def recast(actor,slot,now):
    tank=actor.info['tank_id']
    return (tank==PEGASUS and slot==1 and bool(actor.vanish) or
            tank==ERLANG and (slot==1 and bool(actor.dog) and actor.has_buff(361201,now) or
                             slot==2 and actor.phase>1 and now<actor.phase_end))


def dog_landing(actor,brain,seen,now,target=None,retreat=False):
    dog=actor.dog
    if not dog or not actor.has_buff(361201,now) or now+50>=dog['finish']:return None
    # E2 lands on our own moving dog after its native 50 ms preparation.
    point=point_at(dog['start'],dog['end'],(now+50-dog['begin'])/(dog['finish']-dog['begin']))
    pos=actor.position_at(now);end=actor.blink_destination(pos,point)
    if math.dist(pos,end)<72 or not safe_endpoint(actor,brain,seen,end,now):return None
    if retreat:
        goal=brain.get('goal',pos)
        if math.dist(end,goal)>math.dist(pos,goal)-72:return None
        if seen and min(math.dist(end,s['pos']) for s in seen)<min(math.dist(pos,s['pos']) for s in seen)+72:return None
    elif not target or ratio(actor)<.4 or math.dist(end,target['pos'])>192 or math.dist(end,target['pos'])>math.dist(pos,target['pos'])-60:
        return None
    return end


def burst_active(actor,now):
    return bool(actor.burst_count and actor.has_buff(346131,now) or actor.has_buff(346121,now))


def burst_pending(actor):
    return any(getattr(callback,'__self__',None) is actor and callback.__name__=='_event'
               and args[0]=='apoc_burst' and args[1][0]['generation']==actor.generation
               for _,_,callback,args in actor.arena.pending)


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain if brain is not None else {};tank=actor.info['tank_id'];pos=actor.position_at(now)
    if getattr(actor,'ready',None) or now<actor.forced_until:return []
    if tank==PEGASUS:
        if actor.vanish:
            if now<actor.vanish['begin']+1000:return []
            safe=not near(pos,seen,360) and not incoming(actor,brain,now)
            if safe or not recovering and ratio(actor)>=.4 and near(pos,seen,144):return [(1,pos,actor.id)]
        elif (recovering or ratio(actor)<.4 or actor.ward_count==0) and (near(pos,seen,300) or incoming(actor,brain,now)):
            return [(1,pos,actor.id)]
    if tank==ERLANG and recovering:
        end=dog_landing(actor,brain,seen,now,retreat=True)
        if end is not None:return [(1,end,actor.id)]
        goal=brain.get('goal',pos)
        if not actor.dog and seen and math.dist(pos,goal)>=144:return [(1,goal,actor.id)]
    return []


def structure_choices(actor,brain,target,seen,dest,now):
    if actor.info['tank_id']!=APOC or actor.ready or burst_pending(actor):return []
    if burst_active(actor,now):return [(0,dest,target['id'])]
    # Native R pellets are basic damage; other skills mainly refill burst shots.
    distance=math.dist(actor.position_at(now),target['pos']);result=[]
    if distance<=600:result.append((10,dest,target['id']))
    if distance<=480:result.append((1,dest,target['id']))
    return result


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    if getattr(actor,'ready',None) or now<actor.forced_until:return []
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);result=[]
    if tank==PEGASUS:
        if actor.vanish:return []
        if distance<=480:result.append((2,dest,ident))
        if distance<=600:result.append((10,dest,ident))
        if distance<=144 and actor.ward_count==0:result.append((1,pos,actor.id))
    elif tank==WOLF:
        if distance<=192:result.append((2,dest,ident))
        if distance<=168:result.append((10,dest,ident))
        if retreat or distance>200:
            point=mobility(actor,brain,target,seen,dest,retreat,now,360,fixed=True)
            if point is not None:result.append((1,point,ident))
    elif tank==APOC:
        if burst_pending(actor):return []
        if distance<=168 and retreat:result.append((10,dest,ident))
        if distance<=int(actor.stats['nFireRange']) and not blocked and burst_active(actor,now):
            return result+[(0,dest,ident)]
        if distance<=840 and (distance>=360 or near(target['pos'],seen,120)>=2):result.append((2,dest,ident))
        if distance<=600:result.append((10,dest,ident))
        if distance<=480:result.append((1,dest,ident))
    elif tank==ERLANG:
        end=dog_landing(actor,brain,seen,now,target,retreat)
        if end is not None:result.append((1,end,ident))
        if distance<=192 and not target.get('erlang_mark'):result.append((10,dest,ident))
        if distance<=(600 if actor.phase==3 and now<actor.phase_end else 192):result.append((2,dest,ident))
        if distance<=192:result.append((10,dest,ident))
        if not actor.dog and distance<=720:
            point=brain.get('goal',pos) if retreat else dest
            if point!=pos:result.append((1,point,ident))
    return result
