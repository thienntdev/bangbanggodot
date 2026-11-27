"""AI16: safe returns, native attachment and deliberate allied rescue."""
import math

from bot_ai01 import ratio,aim_in_range
from bot_ai04 import mobility,mobility_goal_ok,near
from bot_ai05 import incoming
from bot_ai11 import safe_endpoint
from combat_geometry import circle_contact
from melee_common import aimed

TIME,STONE,STRANGE,DORA=10000050,10000109,10000083,10000080
TANKS=frozenset((TIME,STONE,STRANGE,DORA))
LAST_STAND={TIME:(2,10),STONE:(10,2),STRANGE:(1,10,2),DORA:(1,2,10)}
HELD=('flag_hold','bomb_escort','bomb_intercept','survive','base_defend')


def observation(actor,target,now):
    if actor.info['tank_id']==STRANGE:
        return dict(strange_mark=target.has_buff(357404,now) and target.buff_sources.get(357404)==actor.id)
    if actor.info['tank_id']==DORA:
        return {name:target.has_buff(ident,now) and target.buff_sources.get(ident)==actor.id
                for name,ident in (('dora_e',354208),('dora_space',354303))}
    return {}


def desired_range(actor,now):
    if actor.info['tank_id']==STRANGE:return 125 if actor.shadow else 320
    return {TIME:200,STONE:155,DORA:370}[actor.info['tank_id']]


def recast(actor,slot,now):
    tank=actor.info['tank_id']
    return (tank==TIME and slot==10 and actor.worm and not actor.worm['used'] and actor.has_buff(325502,now) or
            tank==STONE and (slot==1 and actor.burrow or slot==10 and actor.storm and actor.storm['count']==5) or
            tank==STRANGE and slot==1 and bool(actor.shadow))


def can_recover(actor,now):
    tank=actor.info['tank_id']
    return not (tank==STONE and (actor.burrow or actor.attach) or tank==DORA and actor.has_buff(354121,now))


def must_travel(actor,brain,now):
    return brain.get('objective') in HELD and math.dist(actor.position_at(now),brain.get('goal',actor.position_at(now)))>144


def retreat_point(actor,brain,seen,point,now):
    pos=actor.position_at(now);end=actor.blink_destination(pos,point)
    if math.dist(pos,end)<72 or not safe_endpoint(actor,brain,seen,end,now):return None
    goal=brain.get('goal',pos)
    closer=math.dist(end,goal)<=math.dist(pos,goal)-72
    safer=bool(seen) and min(math.dist(end,s['pos']) for s in seen)>=min(math.dist(pos,s['pos']) for s in seen)+96
    if not (closer or safer):return None
    if near(end,seen,300)>near(pos,seen,300):return None
    return end


def warp_point(actor,brain,seen,now,target=None,retreat=False):
    worm=actor.worm
    if not worm or worm['used'] or not worm['begin']+300<=now<worm['begin']+3500 or not actor.has_buff(325502,now):return None
    pos=actor.position_at(now)
    if math.dist(pos,worm['pos'])>600:return None
    if retreat:return retreat_point(actor,brain,seen,worm['pos'],now)
    end=actor.blink_destination(pos,worm['pos'])
    if target and ratio(actor)>=.5 and math.dist(end,target['pos'])<=200 and math.dist(end,target['pos'])<=math.dist(pos,target['pos'])-72 and safe_endpoint(actor,brain,seen,end,now):return end
    return None


def shadow_return(actor,brain,seen,now):
    shadow=actor.shadow
    if not shadow or now<shadow['begin']+1000:return None
    clone=actor.arena.actors.get(shadow['id'])  # Our own stationary shadow, not an enemy sensor.
    if not clone or not clone.alive:return None
    return retreat_point(actor,brain,seen,clone.position_at(now),now)


def attach_direction(actor,brain,allies,seen,point,ident,now):
    """Predict the first known tank on the fixed dash, including friendly bodies."""
    pos=actor.position_at(now);end=actor.move_destination(pos,aimed(pos,point,480,fixed=True))
    candidates=[(a.id,a.position_at(now)) for a in allies if a.id!=actor.id and a.alive and not a.is_untargetable() and not getattr(a,'attach',None)]
    candidates += [(s['id'],s['pos']) for s in seen if not s.get('objective',s.get('robo')) and not s.get('structure') and not s.get('barrier')]
    hits=[(t,i,p) for i,p in candidates if (t:=circle_contact(pos,end,p,p)) is not None]
    if not hits:return None
    _,first,host=min(hits)
    if first!=ident or not mobility_goal_ok(brain,pos,host) or not safe_endpoint(actor,brain,seen,host,now):return None
    return point


def rescue_portal(actor,allies,seen,brain,now):
    if actor.portals:return None
    pos=actor.position_at(now);threats=[s for s in seen if not s.get('objective',s.get('robo'))]
    if not threats or near(pos,threats,300):return None
    choices=[]
    for ally in allies:
        if ally.id==actor.id or not ally.alive or ally.is_untargetable() or ratio(ally)>=.4:continue
        p=ally.position_at(now)
        if not 144<=math.dist(pos,p)<=600 or not near(p,threats,300):continue
        if min(math.dist(pos,s['pos']) for s in threats)<min(math.dist(p,s['pos']) for s in threats)+144:continue
        ally_brain=actor.arena.bot_brains.get(ally.id,{})
        if not mobility_goal_ok(ally_brain,p,pos):continue
        # An actively held flag/cart also matters for a human without a bot brain.
        if brain.get('objective') in HELD:
            goal=brain.get('goal',pos)
            if math.dist(p,goal)<=144<math.dist(pos,goal):continue
        free=actor.arena.free_position(p,now)
        if free is None or math.dist(free,p)>60:continue
        choices.append((ratio(ally),ally.id,free))
    if not choices:return None
    _,ident,point=min(choices);return (10,point,ident)


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain if brain is not None else {};tank=actor.info['tank_id'];pos=actor.position_at(now)
    if getattr(actor,'ready',None) or now<actor.forced_until:return []
    if tank==TIME:
        if actor.channel:return []
        if recovering or ratio(actor)<.4:
            point=warp_point(actor,brain,seen,now,retreat=True)
            if point is not None:return [(10,point,actor.id)]
        if not actor.rewind and ratio(actor)>=.55 and not must_travel(actor,brain,now) and (near(pos,seen,264) or incoming(actor,brain,now)):
            return [(1,pos,actor.id)]
    elif tank==STONE:
        if actor.attach or actor.dash:return []
        if actor.burrow:
            if not actor.burrow['begin']+1000<=now<actor.burrow['phase_end']:return []
            if recovering or ratio(actor)<.4 or must_travel(actor,brain,now):
                point=aim_in_range(actor,brain.get('goal',pos),480,now)
                end=retreat_point(actor,brain,seen,point,now)
                if end is not None:return [(1,end,actor.id)]
            elif seen and ratio(actor)>=.5:
                target=min(seen,key=lambda s:math.dist(pos,s['pos']))
                point=mobility(actor,brain,target,seen,target['pos'],False,now,480,blink=True)
                if point is not None and math.dist(actor.blink_destination(pos,point),target['pos'])<=168:return [(1,point,target['id'])]
            return []
        if ratio(actor)<.4 or ratio(actor)<.7 and not seen and not must_travel(actor,brain,now):return [(1,pos,actor.id)]
        if not actor.storm:
            for ally in sorted(allies,key=ratio):
                if ally.id==actor.id or ratio(ally)>=.65 or not near(ally.position_at(now),seen,300):continue
                point=attach_direction(actor,brain,allies,seen,ally.position_at(now),ally.id,now)
                if point is not None:return [(2,point,ally.id)]
    elif tank==STRANGE:
        if actor.shadow and (recovering or ratio(actor)<.4 or must_travel(actor,brain,now)):
            point=shadow_return(actor,brain,seen,now)
            if point is not None:return [(1,point,actor.id)]
    elif tank==DORA:
        if actor.has_buff(354121,now):return []
        portal=rescue_portal(actor,allies,seen,brain,now)
        if portal:return [portal]
        injured=[a for a in (actor,*allies) if a.alive and not a.effect_blocked() and not a.has_buff(354209,now)
                 and ratio(a)<.65 and math.dist(pos,a.position_at(now))<=480]
        if injured:
            ally=min(injured,key=ratio);return [(1,ally.position_at(now),ally.id)]
    return []


def hold_flight(actor,retreat,now):
    return actor.info['tank_id']==DORA and actor.has_buff(354121,now) and retreat


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    if getattr(actor,'ready',None) or now<actor.forced_until:return []
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id'];distance=math.dist(pos,target['pos']);result=[]
    if tank==TIME:
        if actor.channel:return []
        point=warp_point(actor,brain,seen,now,target,retreat)
        if point is not None:result.append((10,point,ident))
        if not actor.worm and distance<=480:
            point=aim_in_range(actor,brain.get('goal',dest) if retreat else dest,480,now)
            result.append((10,point,ident))
        if distance<=264 and not retreat and not must_travel(actor,brain,now):result.append((2,pos,actor.id))
    elif tank==STONE:
        if actor.burrow or actor.attach or actor.dash:return []
        if actor.storm and actor.storm['count']==5:
            if distance<=480:result.append((10,dest,ident))
        elif not actor.storm and distance<=192:result.append((10,pos,actor.id))
        if not actor.storm and not retreat and not target.get('objective',target.get('robo')):
            allies=[a for a in actor.arena.actors.values() if a.alive and a.camp==actor.camp and not a.info.get('npc_template')]
            point=attach_direction(actor,brain,allies,seen,dest,ident,now)
            if point is not None:result.append((2,point,ident))
    elif tank==STRANGE:
        if target.get('strange_mark') and actor.has_buff(357406,now) and distance<=600 and not blocked:result.append((0,dest,ident))
        if not actor.shadow:
            point=mobility(actor,brain,target,seen,dest,retreat,now,600,blink=True)
            if point is not None:result.append((1,point,ident))
        elif retreat:
            point=shadow_return(actor,brain,seen,now)
            if point is not None:result.append((1,point,ident))
        if distance<=600:
            if not retreat:result.append((2,aim_in_range(actor,dest,600,now),ident))
            result.append((10,dest,ident))
    elif tank==DORA:
        if hold_flight(actor,retreat,now):return []
        if distance<=480:
            if target.get('dora_e'):result.append((2,aim_in_range(actor,dest,480,now),ident))
            result.append((1,aim_in_range(actor,dest,480,now),ident))
            result.append((2,aim_in_range(actor,dest,480,now),ident))
    return result
