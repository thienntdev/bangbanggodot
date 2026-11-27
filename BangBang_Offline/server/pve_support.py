"""Reviewed NPC support abilities and one-shot explosions for chapter four."""
import math
from combat_geometry import rect_contact
from combat_math import D
from pve_shots import targets

MAPS=(701,702,703,304,305,306)
SUPPORT=(1000057,1000060,1000061)


def allies(actor,radius,now,*,healing=False):
    pos=actor.position_at(now)
    for target in list(actor.arena.actors.values()):
        if (not target.info.get('pve_npc') or target.camp!=actor.camp or not target.alive
                or target.in_stasis() or target.info.get('pve_hostage')
                or target.info.get('pve_trap')):continue
        if healing and target.info.get('pve_stationary'):continue
        if healing and (target is actor or target.hp>=target.max_hp):continue
        dest=target.position_at(now)
        if math.dist(pos,dest)>radius:continue
        if actor.arena.geometry.wall_contact(pos,dest) is not None:continue
        if rect_contact(pos,dest,actor.arena.water_rects(now)) is not None:continue
        yield target


def pulse(actor,now):
    packets=[];skill=actor.shot_skill
    for target in allies(actor,216 if skill==1000057 else 200,now,healing=skill==1000057):
        if skill==1000057:packets+=target.restore_hp(D(300)+target.max_hp*D('.05'),now)
        elif skill==1000061:packets+=actor._buff(252,now,target.id)
        else:
            packets+=actor._buff(251,now,target.id)
            packets+=actor._buff(247,now,target.id)
    return packets


def cast_support(actor,now):
    # Chapter-four AI also invokes this directly; retain the native slot-zero
    # lock checked by PveNpc.cast, including disarm/taunt without a stun.
    if actor.blocked('attack',now) or actor.skill_sealed(0,now) or now<actor.cooldowns[0]:return []
    if actor.shot_skill==1000057 and not any(allies(actor,216,now,healing=True)):return []
    actor.cooldowns[0]=now+(actor.pve_count-1)*actor.pve_break+actor.fire_interval(now)
    if actor.shot_skill==1000060:
        for index in range(1,5):actor._queue(now+index*1000,'pve_support_pulse',actor.generation)
    return pulse(actor,now)


def explode(actor,now):
    if getattr(actor,'pve_exploded',False):return []
    actor.pve_exploded=True;packets=[]
    oil=actor.shot_skill==1000062
    raw=D(100)+actor.combat_stat('iAttack',now) if oil else actor.combat_stat('iAttack',now)*10
    for target in targets(actor,actor.position_at(now),144 if oil else 216,now):
        packets+=actor.damage(raw,now,target=target,school='true' if oil else 'physical',basic=True)[0]
    if actor.alive:packets+=actor.commit_hp(D(0),now)
    return packets


def signal(actor,pos,now):
    ident,packet=actor.add_object(253,pos)
    actor._queue(now+2000,'pve_signal_blast',ident,pos,actor.generation)
    return [packet]


def event(actor,now,kind,data):
    if kind=='pve_support_pulse':
        return pulse(actor,now) if (actor.generation==data[0] and not actor.blocked('attack',now)
            and not actor.skill_sealed(0,now)) else []
    if kind=='pve_signal_blast':
        ident,pos,generation=data;packets=actor.remove_object(ident)
        if actor.arena.pk['finished']:return packets
        for target in targets(actor,pos,216,now):
            packets+=actor.damage(D(220),now,target=target,school='physical',basic=True,
                                  source_generation=generation)[0]
        return packets
    if kind=='pve_flame_tick':
        target_id,version,generation,remaining=data;target=actor.arena.actors.get(target_id)
        if (not target or not target.alive or target.buff_versions.get(224)!=version
                or target.buff_sources.get(224)!=actor.id):return []
        # The fifth tick coincides with buff expiry; the version distinguishes a cleanse/refresh.
        if not target.has_buff(224,now) and remaining!=1:return []
        packets=actor.damage(D(10),now,target=target,school='true',periodic=True,
                             source_generation=generation)[0]
        if remaining>1 and not actor.arena.pk['finished']:
            actor._queue(now+1000,kind,target_id,version,generation,remaining-1)
        return packets
    return None
