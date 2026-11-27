"""Kakashi: choose a visible donor, reuse its E policy, execute only on the host."""
import importlib
import math
from functools import lru_cache

from borrowed_e import executor
from bot_ai01 import ratio,aim_in_range
from bot_ai04 import mobility,mobility_goal_ok,near
from bot_ai05 import incoming
from bot_ai11 import safe_endpoint
from bot_ai16 import must_travel

KAKASHI=10000055
TANKS=frozenset((KAKASHI,))
LAST_STAND={KAKASHI:(2,10)}
HEALERS=frozenset((10000029,10000032,10000037,10000085,10000052,10000054,10000061))


@lru_cache(maxsize=None)
def policy(tank):
    for number in (*range(1,19),20):
        module=importlib.import_module(f'bot_ai{number:02}')
        if tank in module.TANKS:return number,module
    return 0,None  # The five original kits live in bot_ai.py.


class PolicyView:
    """Expose donor identity to decisions without changing the native executor."""
    def __init__(self,view):
        self.view=view
        self.info=dict(view.info,tank_id=view._session['tank'])

    def __getattr__(self,name):return getattr(self.view,name)


def current(actor):
    return PolicyView(executor(actor,actor.borrowed)) if actor.borrowed is not None else None


def observation(actor,target,now):
    result={'copy_tank':None if target.info.get('npc_template') else target.info['tank_id']}
    view=current(actor)
    if view:
        _,module=policy(view.info['tank_id'])
        if module and hasattr(module,'observation'):result.update(module.observation(view,target,now))
        if view.info['tank_id']==10000041:result['legolas_marks']=view._stage(target,now)
    return result


def recast(actor,slot,now):
    # Copy CD is not the borrowed E's recast/phase timer. Native cast_borrowed
    # checks the latter, Chakra and control without changing the copy deadline.
    return slot==1 and actor.borrowed is not None or slot==2 and bool(actor.kamui)


def basic_range(actor,now):
    view=actor.borrowed_basic(now)
    if view:
        donor=PolicyView(view);_,module=policy(donor.info['tank_id'])
        if module and hasattr(module,'basic_range'):return module.basic_range(donor,now)
        return 600
    return 420 if actor.has_buff(330111,now) else int(actor.stats['nFireRange'])


def desired_range(actor,now):
    view=current(actor)
    if view:
        number,module=policy(view.info['tank_id'])
        if module:
            reach=module.desired_range(view) if number<=3 else module.desired_range(view,now)
            return min(420,reach)
        if view.info['tank_id']==10000056:return 220
    return 260 if actor.has_buff(330111,now) and not actor.borrowed_basic(now) else 380


def can_recover(actor,now):
    if actor.ready or actor.dash or actor.vanish or actor.kamui:return False
    return not any(getattr(v,'burrow',None) or getattr(v,'egg',None) or getattr(v,'vanish',None)
                   or getattr(v,'ready',None) or getattr(v,'dash',None) for v in actor.borrowed_views())


def hold_stealth(actor,retreat,now):
    return (retreat or ratio(actor)<.28) and any(actor.has_buff(t,now) for t in (330131,322201,305202,390201))


def copy_choice(actor,allies,seen,now):
    if actor.borrowed is not None or actor.cooldowns[1]>now or actor.mp<10:return None
    pos=actor.position_at(now)
    from bot_setup import AI_TANKS
    # Friendly positions/identity are known; enemy identity comes only from the
    # delivered observation. Never inspect a hidden enemy to choose its E.
    candidates=[(a.id,a.info['tank_id'],a.position_at(now)) for a in allies if a.id!=actor.id and a.alive and not a.is_untargetable()]
    candidates += [(s['id'],s.get('copy_tank'),s['pos']) for s in seen]
    candidates=[c for c in candidates if c[1] in AI_TANKS and c[1]!=KAKASHI and math.dist(pos,c[2])<=960]
    if not candidates:return None
    wounded=any(ratio(a)<.65 for a in allies)
    def score(c):
        heal=c[1] in HEALERS
        return (int(heal and wounded)*4+int(not heal and bool(seen))*2-math.dist(pos,c[2])/960,-c[0])
    ident,_,point=max(candidates,key=score)
    return 1,point,ident


def borrowed_support(actor,allies,seen,brain,now,recovering):
    view=current(actor)
    if not view:return []
    number,module=policy(view.info['tank_id'])
    if not module or not hasattr(module,'support_choices'):return []
    # Decisions may update a local goal/aim, but cannot replace the host's mode
    # objective or import a donor's R/Space. Only E commands leave this adapter.
    options=(module.support_choices(view,allies,seen,now) if number<=5 else
             module.support_choices(view,allies,seen,now,dict(brain),recovering))
    return [choice for choice in options if choice[0]==1]


def borrowed_choices(actor,brain,target,seen,dest,retreat,blocked,now):
    view=current(actor)
    if not view:return []
    tank=view.info['tank_id'];_,module=policy(tank)
    if module:
        choices=module.choices(view,dict(brain),target,seen,dest,retreat,blocked,now)
        # Legolas's original policy can wait for marks from a passive that is
        # deliberately not lent. His E is still a useful projectile by itself.
        if tank==10000041 and math.dist(actor.position_at(now),target['pos'])<=600:
            choices.append((1,dest,target['id']))
        return [choice for choice in choices if choice[0]==1]
    distance=math.dist(actor.position_at(now),target['pos'])
    if tank==10000056:
        second=view.e_second_until>now
        if second and distance<480:return [(1,dest,target['id'])]
        if retreat or distance>200:
            point=mobility(view,brain,target,seen,dest,retreat,now,480)
            if point is not None:return [(1,point,target['id'])]
    elif distance<=(560 if tank in (10000019,10000031) else 600):return [(1,dest,target['id'])]
    return []


def basic_choice(actor,brain,target,seen,dest,retreat,blocked,now):
    pos=actor.position_at(now)
    if blocked or math.dist(pos,target['pos'])>basic_range(actor,now):return None
    if not actor.borrowed_basic(now) and actor.has_buff(330111,now):
        end=actor.blink_destination(pos,aim_in_range(actor,dest,300,now))
        if not mobility_goal_ok(brain,pos,end) or not safe_endpoint(actor,brain,seen,end,now):return None
        if retreat and math.dist(end,target['pos'])<math.dist(pos,target['pos']):return None
    return 0,dest,target['id']


def kamui_safe(actor,allies,brain,now):
    pos=actor.position_at(now)
    if must_travel(actor,brain,now) or brain.get('objective') in ('bomb_escort','bomb_intercept','escort'):return False
    for ally in allies:
        if ally.id==actor.id or math.dist(pos,ally.position_at(now))>192:continue
        order=actor.arena.bot_brains.get(ally.id,{})
        if order.get('objective') in ('flag_hold','bomb_escort','bomb_intercept','escort'):return False
        if any(math.dist(ally.position_at(now),f['position'])<=60 for f in actor.arena.pk.get('flags',())):return False
        if any(obj.alive and (obj.info.get('bomb_cart') or obj.info.get('cow_object'))
               and math.dist(ally.position_at(now),obj.position_at(now))<=240
               for obj in actor.arena.actors.values()):return False
    return True


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain or {};pos=actor.position_at(now)
    if actor.kamui:
        # Let healing/explosion finish unless the fight has left or movement is
        # needed by the mode. Cancel through the same native one-second gate.
        if now>=actor.kamui['begin']+1000 and (must_travel(actor,brain,now) or
                ratio(actor)>.85 and not near(actor.kamui['pos'],seen,240)):
            return [(2,pos,actor.id)]
        return []
    if hold_stealth(actor,recovering,now) or actor.ready or actor.dash or actor.vanish:return []
    options=borrowed_support(actor,allies,seen,brain,now,recovering)
    if options:return options
    if (actor.mp>=75 and ratio(actor)<.55 and (near(pos,seen,240) or incoming(actor,brain,now))
            and kamui_safe(actor,allies,brain,now)):
        return [(2,pos,actor.id)]
    choice=copy_choice(actor,allies,seen,now)
    return [choice] if choice else []


def decide(actor,brain,allies,target,seen,dest,retreat,blocked,now):
    from bot_ai import perform
    pos=actor.position_at(now);brain['aim']=dest
    view=current(actor)
    if view and view.info['tank_id']==10000111:
        from bot_ai08 import steer
        steer(view,brain,dest,seen,retreat,now)
    for choice in support_choices(actor,allies,seen,now,brain,retreat):
        packets=perform(actor.arena,actor,*choice,now)
        if packets:return packets
    if actor.kamui or hold_stealth(actor,retreat,now):return []
    # Native E2/toggle may remain legal while that E blocks ordinary attacks.
    for choice in borrowed_choices(actor,brain,target,seen,dest,retreat,blocked,now):
        packets=perform(actor.arena,actor,*choice,now)
        if packets:return packets
    if actor.blocked('attack',now):return []
    # Wukong's lent E permits attacks but is useful movement until it reaches
    # melee distance. Do not overwrite that motion with our own R/basic blink.
    if actor.has_buff(310211,now) and math.dist(pos,target['pos'])>192:return []
    basic=basic_choice(actor,brain,target,seen,dest,retreat,blocked,now)
    if basic and (actor.borrowed_basic(now) or actor.has_buff(330111,now)):
        packets=perform(actor.arena,actor,*basic,now)
        if packets:return packets
    if actor.mp>=25 and (retreat or ratio(actor)>.5 and math.dist(pos,target['pos'])>250):
        point=mobility(actor,brain,target,seen,dest,retreat,now,480)
        if point is not None:
            packets=perform(actor.arena,actor,10,point,target['id'],now)
            if packets:return packets
    if (actor.mp>=75 and near(pos,seen,192)>=2 and kamui_safe(actor,allies,brain,now)):
        packets=perform(actor.arena,actor,2,pos,actor.id,now)
        if packets:return packets
    return perform(actor.arena,actor,*basic,now) if basic else []
