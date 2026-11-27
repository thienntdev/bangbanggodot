"""AI11: native forms, changing buttons and resources; delayed enemy samples."""
import math

from bot_ai01 import ratio,aim_in_range
from bot_ai04 import mobility,mobility_goal_ok,near
from melee_common import in_strip

TANKS=frozenset((10000051,10000042,10000064,10000062,10000082))
LAST_STAND={10000051:(2,10),10000042:(1,2),10000064:(2,10),10000062:(1,10),10000082:(2,10)}


def observation(actor,target,now):
    result={'ai11_tank':not bool(target.info.get('npc_template'))}
    if actor.info['tank_id']==10000064:
        result.update(ichigo_mark=target.has_buff(339210,now) and target.buff_sources.get(339210)==actor.id,
                      airborne=actor._airborne(target,now))
    return result


def basic_range(actor,now):
    if actor.info['tank_id']==10000064 and actor.has_buff(339111,now):return 408
    if actor.info['tank_id']==10000062 and actor.form:return 216
    return int(actor.stats['nFireRange'])


def desired_range(actor,now):
    tank=actor.info['tank_id']
    if tank==10000062:return 150 if actor.form else 330
    return min({10000051:340,10000042:280,10000064:300,10000082:330}[tank],basic_range(actor,now)-36)


def recast(actor,slot,now):
    return (actor.info['tank_id']==10000064 and slot==2 and actor.has_buff(339303,now) or
            actor.info['tank_id']==10000082 and slot==1 and actor.e_follow and actor.e_follow['end']>now)


def cleanse(actor,slot,now):
    # Initial Bankai explicitly bypasses native attack/seal guards; its second
    # activation does not. Cooldown and preparation guards still apply.
    return actor.info['tank_id']==10000064 and slot==2 and actor._skill(2,now)==339301


def can_recover(actor):
    return not (actor.info['tank_id']==10000051 and actor.form or
                actor.info['tank_id']==10000064 and actor.vanish or
                actor.info['tank_id']==10000082 and actor._vanished())


def safe_endpoint(actor,brain,seen,end,now):
    pos=actor.position_at(now)
    friends=sum(a.alive and a.camp==actor.camp and not a.info.get('npc_template')
                and math.dist(end,a.position_at(now))<=480 for a in actor.arena.actors.values())
    return mobility_goal_ok(brain,pos,end) and near(end,seen,360)<=friends+1


def ally_escape(actor,allies,seen,brain,now):
    pos=actor.position_at(now);goal=brain.get('goal',pos)
    candidates=[]
    for ally in allies:
        point=ally.position_at(now)
        if ally.id==actor.id or not ally.alive or ally.is_untargetable() or math.dist(pos,point)>432:continue
        end=actor.blink_destination(pos,point)
        if math.dist(end,goal)>math.dist(pos,goal)-72:continue
        if seen and min(math.dist(end,s['pos']) for s in seen)<min(math.dist(pos,s['pos']) for s in seen)+72:continue
        if safe_endpoint(actor,brain,seen,end,now):candidates.append((math.dist(end,goal),ally.id,point))
    if not candidates:return None
    _,ident,point=min(candidates)
    return (1,point,ident)


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain or {};tank=actor.info['tank_id'];pos=actor.position_at(now);hp=ratio(actor)
    if getattr(actor,'ready',None) or getattr(actor,'vanish',None):return []
    if tank==10000064 and not actor.has_buff(339308,now):
        if actor.blocked('attack',now) or actor.mp<70 and near(pos,seen,600):return [(2,pos,actor.id)]
    if tank in (10000042,10000064) and (recovering or hp<.3) and near(pos,seen,600):
        choice=ally_escape(actor,allies,seen,brain,now)
        if choice:return [choice]
    if tank==10000042 and actor._form(now) is None:
        close=[s for s in seen if s.get('ai11_tank') and math.dist(pos,s['pos'])<=432]
        if len(close)>=2 or close and (hp<.55 or near(pos,close,170)):
            return [(2,pos,actor.id)]
    return []


def airborne_choice(actor,brain,seen,now):
    pos=actor.position_at(now)
    candidates=[s for s in seen if s.get('airborne') and math.dist(pos,s['pos'])<=600]
    if not candidates:return None
    # Native Space2 chooses nearest, independent of the ID sent by the client.
    target=min(candidates,key=lambda s:(math.dist(pos,s['pos']),s['id']))
    end=actor.blink_destination(pos,target['pos'])
    return (2,target['pos'],target['id']) if safe_endpoint(actor,brain,seen,end,now) else None


def sword_endpoint(actor,dest,now):
    pos=actor.position_at(now)
    swords=[s for s in actor.swords if s['end']>now and s['generation']==actor.generation
            and in_strip(s['pos'],pos,dest,480,72)]
    if not swords:return None
    chosen=min(swords,key=lambda s:math.dist(pos,s['pos']))
    return actor.move_destination(pos,chosen['pos'])


def structure_choices(actor,brain,target,seen,dest,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now)
    if tank==10000051 and not actor.rage_until:return [(1,dest,target['id'])]
    # Normal attacks remain the primary siege tool; these existing forms buff
    # them. The melee form must first be within its real 216-unit reach.
    if tank==10000042 and actor._form(now) is None:return [(2,pos,actor.id)]
    if tank==10000062 and not actor.form and actor.mp>=100 and math.dist(pos,target['pos'])<=216:
        return [(2,pos,actor.id)]
    return []


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);result=[]
    if getattr(actor,'ready',None) or getattr(actor,'vanish',None):return []
    if tank==10000051:
        if actor.form and actor.form['phase']!='active':return []
        if not actor.form and (ratio(actor)<.6 or near(target['pos'],seen,168)>=2 or distance<220):
            point=mobility(actor,brain,target,seen,dest,retreat,now,480,blink=True)
            if point is not None:result.append((2,point,ident))
        if not actor.rage_until and distance<=basic_range(actor,now) and not blocked:result.append((1,dest,ident))
        if distance<=540:result.append((10,aim_in_range(actor,dest,480,now),ident))
    elif tank==10000042:
        if not retreat and not actor.teleport and 144<distance<=432:
            end=actor.blink_destination(pos,target['pos'])
            if safe_endpoint(actor,brain,seen,end,now):result.append((1,dest,ident))
        if actor._form(now) is None and distance<=432:result.append((2,pos,actor.id))
    elif tank==10000064:
        if not retreat and recast(actor,2,now):
            choice=airborne_choice(actor,brain,seen,now)
            if choice:result.append(choice)
        if actor.has_buff(339111,now) and in_strip(target['pos'],pos,dest,408,72):
            result.append((0,dest,ident))
        if not retreat and 180<distance<=432 and not target.get('ichigo_mark'):
            end=actor.blink_destination(pos,target['pos'])
            if safe_endpoint(actor,brain,seen,end,now):result.append((1,dest,ident))
        if distance<=600:result.append((10,dest,ident))
        if not actor.has_buff(339308,now) and distance<=600:result.append((2,pos,actor.id))
    elif tank==10000062:
        if actor.dash:return []
        if actor.mp>=100 and not actor.form and distance<=216:result.append((2,pos,actor.id))
        if distance<=480:
            # Place R first, then use native E's nearest intersected own sword.
            if not actor.swords:result.append((10,aim_in_range(actor,dest,480,now),ident))
            end=sword_endpoint(actor,dest,now)
            if end is None or safe_endpoint(actor,brain,seen,end,now) and (not retreat or math.dist(end,target['pos'])>distance):
                result.append((1,dest,ident))
        if distance<=540:result.append((10,aim_in_range(actor,dest,480,now),ident))
    elif tank==10000082:
        if actor._vanished() or actor.motion and actor.motion_kind==3 and actor.motion[3]>now:return []
        if not actor.form and (ratio(actor)<.65 or distance<380 or near(target['pos'],seen,216)>=2):
            point=mobility(actor,brain,target,seen,dest,retreat,now,720,blink=True)
            if point is not None:result.append((2,point,ident))
        if recast(actor,1,now):
            if retreat or distance>260:
                point=mobility(actor,brain,target,seen,dest,retreat,now,240,fixed=True)
                if point is not None:result.append((1,point,ident))
        elif distance<=480:result.append((1,dest,ident))
        if distance<=480:result.append((10,dest,ident))
    return result
