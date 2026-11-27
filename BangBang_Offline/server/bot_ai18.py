"""Gia Cat Luong: deliberate native weather cycling with a real mana budget."""
import math

from bot_ai01 import ratio,aim_in_range
from bot_ai04 import near
from bot_ai05 import incoming

ZHUGE=10000084
TANKS=frozenset((ZHUGE,))
LAST_STAND={ZHUGE:(1,2)}


def observation(actor,target,now):
    return dict(zhuge_lift=target.has_buff(358501,now),
                zhuge_wind=target.has_buff(358604,now),
                ai18_tank=not bool(target.info.get('npc_template')))


def desired_range(actor,now):
    return 340 if actor.weather==0 else 430 if actor.weather==2 else 400


def fog_pending(actor):
    # Our own placed field is known even after a checkpoint; never inspect an
    # enemy callback to predict its next cast.
    return any(getattr(callback,'__self__',None) is actor and callback.__name__=='_event'
               and args[0]=='zhuge_fog' and args[1][0]['generation']==actor.generation
               for _,_,callback,args in actor.arena.pending)


def hold_fog(actor,retreat,now):
    return (retreat or ratio(actor)<.4) and (actor.has_buff(358902,now) or fog_pending(actor))


def fog_safe(actor,allies,brain,now):
    """Don't hide tanks contributing to capture/escort, including a human."""
    pos=actor.position_at(now);arena=actor.arena
    for ally in allies:
        if not ally.alive or ally.is_untargetable() or math.dist(pos,ally.position_at(now))>300:continue
        p=ally.position_at(now);order=brain if ally.id==actor.id else arena.bot_brains.get(ally.id,{})
        if order.get('objective') in ('flag_hold','bomb_escort','bomb_intercept','escort'):
            if math.dist(p,order.get('goal',p))<=240:return False
        if any(math.dist(p,f['position'])<=132 for f in arena.pk.get('flags',())):return False
        for obj in arena.actors.values():
            if not obj.alive:continue
            if obj.info.get('bomb_cart') and math.dist(p,obj.position_at(now))<=272:return False
            if obj.info.get('cow_object') and obj.camp!=actor.camp and math.dist(p,obj.position_at(now))<=312:return False
    return True


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain if brain is not None else {};pos=actor.position_at(now)
    if hold_fog(actor,recovering,now):return []
    threats=[s for s in seen if s.get('ai18_tank') and math.dist(pos,s['pos'])<=600]
    danger=incoming(actor,brain,now)
    wounded=[a for a in allies if a.alive and not a.effect_blocked() and ratio(a)<.35
             and math.dist(pos,a.position_at(now))<=240 and near(a.position_at(now),threats,480)]
    defensive=bool((recovering or ratio(actor)<.45 or wounded) and (threats or danger))
    close=[s for s in seen if not s.get('barrier') and math.dist(pos,s['pos'])<=600]
    grouped=any(near(s['pos'],close,196)>=2 for s in close)
    wanted=2 if defensive or danger else 0 if not close or grouped else 1
    if brain.get('weather_seen')!=actor.weather:
        brain['weather_seen']=actor.weather
        if actor.weather==wanted:brain['weather_hold_until']=now+2200
    if actor.weather==2:
        if (actor.mp>=20 and actor.cooldowns[1]<=now and not actor.skill_sealed(1,now)
                and (danger or near(pos,threats,480)) and not actor.has_buff(358921,now)):
            return [(1,pos,actor.id)]
        if (defensive and actor.mp>=50 and actor.cooldowns[2]<=now and not actor.skill_sealed(2,now)
                and not fog_pending(actor) and not actor.has_buff(358902,now)
                and fog_safe(actor,allies,brain,now)):
            return [(2,pos,actor.id)]
    if actor.weather==wanted:return []
    if not (defensive or danger) and now<brain.get('weather_hold_until',0):return []
    # First use the ready wind lift in a fight, then chain into thunder using
    # native R. Do not burn MP purely to reach another weather.
    if (actor.weather==0 and wanted==1 and actor.mp>=20 and actor.cooldowns[1]<=now
            and not actor.skill_sealed(1,now) and threats):return []
    if close and actor.mp<20 and not (defensive or danger):return []
    return [(10,pos,actor.id)]


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    pos=actor.position_at(now);distance=math.dist(pos,target['pos']);ident=target['id']
    if hold_fog(actor,retreat,now):return []
    result=[]
    if actor.weather==2:return result  # Defensive spells are considered before attack lock.
    reach=480 if actor.weather==0 else 600
    cluster=near(target['pos'],seen,196 if actor.weather==0 else 96)
    slow=math.hypot(*target.get('velocity',(0,0)))<90
    caught=target.get('zhuge_lift') or target.get('zhuge_wind')
    # Expensive delayed zones need a cluster, control, or a nearly stationary
    # target. Keep 20MP for control/guard while retreating.
    if distance<=reach and actor.mp>=(70 if retreat else 50):
        worthwhile=(cluster>=2 or caught or slow and (target['hp']<.6 or target.get('objective')))
        if worthwhile:result.append((2,aim_in_range(actor,dest,reach,now),ident))
    if distance<=600 and actor.mp>=20:
        if actor.weather==1 or not target.get('zhuge_lift'):
            result.append((1,aim_in_range(actor,dest,600,now),ident))
    return result
