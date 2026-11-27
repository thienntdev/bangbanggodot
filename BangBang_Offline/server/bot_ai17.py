"""AI17: healing, deliberate HP exchange and native damage/charge windows."""
import math

from bot_ai01 import ratio,aim_in_range
from bot_ai04 import near
from bot_ai05 import incoming
from bot_ai11 import safe_endpoint
from bot_ai16 import must_travel
from combat_geometry import circle_contact
from melee_common import aimed

NOEL,DRACULA,CAO,DARE=10000054,10000057,10000091,10000115
TANKS=frozenset((NOEL,DRACULA,CAO,DARE))
LAST_STAND={NOEL:(1,10,2),DRACULA:(2,1),CAO:(2,10),DARE:(2,10)}


def observation(actor,target,now):
    result={'ai17_tank':not bool(target.info.get('npc_template'))}
    if actor.info['tank_id']==NOEL:
        result.update(noel_mark=target.has_buff(329302,now),cc_immune=target.cc_immune(now))
    elif actor.info['tank_id']==CAO:
        result['cao_held']=bool(getattr(target,'caocao_hostage',None) or target.has_buff(366806,now))
    elif actor.info['tank_id']==DARE:
        result['dare_mark']=target.has_buff(391413,now) and target.buff_sources.get(391413)==actor.id
    return result


def desired_range(actor,now):
    tank=actor.info['tank_id']
    if tank==DRACULA:return 100 if actor.bat and ratio(actor)>.45 else 230
    return {NOEL:400,CAO:180,DARE:170 if actor.has_buff(391307,now) else 320}[tank]


def recast(actor,slot,now):
    return actor.info['tank_id']==DRACULA and slot==1 and bool(actor.bat)


def can_recover(actor,now):
    return not (getattr(actor,'ready',None) or getattr(actor,'hostage',None) or getattr(actor,'dash',None))


def projected_hp(actor):
    # Only our own already recorded damage/healing; never predict enemy input.
    hp=float(actor.hp)
    if actor.ledger:hp+=float(actor.ledger['healing']-actor.ledger['damage'])
    return max(0,min(1,hp/float(actor.max_hp)))


def direction(actor,point,now):
    pos=actor.position_at(now)
    return point if point!=pos else actor.arena.geometry.clamp_tank_position((pos[0]+72,pos[1]))


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain or {};tank=actor.info['tank_id'];pos=actor.position_at(now);hp=ratio(actor)
    if getattr(actor,'ready',None) or getattr(actor,'dash',None) or getattr(actor,'hostage',None):return []
    threats=[s for s in seen if s.get('ai17_tank')]
    if tank==NOEL:
        injured=[a for a in allies if a.alive and not a.effect_blocked() and ratio(a)<.65
                 and math.dist(pos,a.position_at(now))<=600]
        if injured:
            ally=min(injured,key=ratio);point=direction(actor,ally.position_at(now),now)
            return [(1,point,ally.id),(10,point,ally.id)]
    elif tank==DRACULA:
        if not actor.bat and (incoming(actor,brain,now) or hp<.4 and near(pos,threats,360)):
            return [(1,pos,actor.id)]
        # Donate HP only when we can survive the simultaneous ratio exchange.
        if hp>=.75 and not actor.link and not recovering and not must_travel(actor,brain,now) and not near(pos,threats,300):
            candidates=[a for a in allies if a.id!=actor.id and a.alive and not a.is_untargetable()
                        and ratio(a)<.25 and math.dist(pos,a.position_at(now))<=264
                        and near(a.position_at(now),threats,360)
                        and not must_travel(a,actor.arena.bot_brains.get(a.id,{}),now)]
            if candidates:
                ally=min(candidates,key=ratio);return [(2,ally.position_at(now),ally.id)]
    elif tank==CAO:
        if not actor.aura and recovering and near(pos,threats,240):return [(10,pos,actor.id)]
    elif tank==DARE:
        # Space is explicitly usable in stun. Native silence/stasis guards stay.
        if (actor.blocked('attack',now) or recovering) and (near(pos,threats,192) or incoming(actor,brain,now)):
            if projected_hp(actor)>.18 and not actor.has_buff(391307,now):return [(2,pos,actor.id)]
    return []


def hook_point(actor,brain,seen,target,dest,now):
    pos=actor.position_at(now);end=aimed(pos,dest,480,fixed=True)
    hits=[(hit,s['id'],s['pos']) for s in seen
          if (hit:=circle_contact(pos,end,s['pos'],s['pos'],48)) is not None]
    if not hits:return None
    _,ident,point=min(hits)
    if ident!=target['id']:return None
    landing=actor.move_destination(pos,point)
    if math.dist(pos,landing)<72 or not safe_endpoint(actor,brain,seen,landing,now):return None
    return dest


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    if getattr(actor,'ready',None) or getattr(actor,'dash',None) or getattr(actor,'hostage',None):return []
    tank=actor.info['tank_id'];pos=actor.position_at(now);hp=ratio(actor)
    ident=target['id'];distance=math.dist(pos,target['pos']);result=[]
    if tank==NOEL:
        # Box removes an enemy from combat; don't waste it on a dying focus target.
        if (target.get('ai17_tank') and distance<=600 and target['hp']>.25
                and not target.get('noel_mark') and not target.get('cc_immune')
                and (retreat or hp<.55 or near(pos,seen,600)>=2)):
            result.append((2,dest,ident))
        if distance<=720:
            result.append((10,aim_in_range(actor,dest,720,now),ident))
            # Leave one healing charge while healthy unless a kill is plausible.
            if actor.e_count>1 or hp<.65 or target['hp']<.25:result.append((1,dest,ident))
    elif tank==DRACULA:
        if (target.get('ai17_tank') and distance<=264 and not actor.link
                and hp+.2<target['hp'] and not must_travel(actor,brain,now)):
            result.append((2,target['pos'],ident))
        if not actor.bat and distance<=360:result.append((1,pos,actor.id))
        elif (actor.bat and now>=actor.bat['begin']+500 and not retreat
              and distance<=120 and target['hp']<.2):result.append((1,pos,actor.id))
        if target.get('ai17_tank') and distance<=360 and not actor.link and not retreat:
            result.append((10,target['pos'],ident))
    elif tank==CAO:
        landing=actor.move_destination(pos,target['pos'])
        if (target.get('ai17_tank') and not target.get('cao_held') and distance<=264
                and not retreat and not must_travel(actor,brain,now)
                and math.dist(landing,target['pos'])<=72 and safe_endpoint(actor,brain,seen,landing,now)):
            result.append((2,target['pos'],ident))
        if not actor.aura and distance<=240:result.append((10,pos,actor.id))
        if distance<=480:result.append((1,aim_in_range(actor,dest,480,now),ident))
    elif tank==DARE:
        if actor.has_buff(391111,now) and distance<=480 and not blocked:
            result.append((0,dest,ident))
            # Let the paid empowered shot land before paying for another skill.
            return result
        if actor.ledger:return result
        predicted=projected_hp(actor)
        if predicted<=.18:return result
        if distance<=192 and not actor.has_buff(391307,now):result.append((2,pos,actor.id))
        if distance<=480:
            if not target.get('dare_mark') or incoming(actor,brain,now):result.append((10,dest,ident))
            if not retreat and predicted>=.45 and distance>192:
                point=hook_point(actor,brain,seen,target,dest,now)
                if point is not None:result.append((1,point,ident))
    return result
