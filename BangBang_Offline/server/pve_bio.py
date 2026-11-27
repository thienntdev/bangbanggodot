"""Reviewed biological NPC attacks; temporary formulas recorded with PVE05."""
from combat_math import D
from combat_protocol import scene,skill_event
from pve_shots import targets


def poison(actor,target,now,buff):
    if actor.arena.pk['finished'] or not target.alive:return []
    packets=actor._buff(buff,now,target.id,duration=10000,refresh=True)
    if target.has_buff(buff,now) and target.buff_sources.get(buff)==actor.id:
        actor._queue(now+1000,'pve_bio_poison',target.id,target.generation,buff,
                     target.buff_versions[buff],actor.generation,10)
    return packets


def melee(actor,target,now):
    skill=actor.shot_skill;pos=actor.position_at(now)
    packets=[scene(skills=(skill_event(skill,pos,pos,owner=actor.id),))]
    area=skill in (1000103,1000117,1000133)
    victims=list(targets(actor,pos,144 if area else actor.pve_fire_range,now))
    if not area:victims=[t for t in victims if t is target]
    for victim in victims:
        packets+=actor.damage(actor.combat_stat('iAttack',now),now,target=victim,school='physical',basic=True)[0]
        if actor.arena.pk['finished']:return packets
        if skill in (1000088,1000128):packets+=poison(actor,victim,now,10000882)
        if skill==1000123:packets+=poison(actor,victim,now,10001062)
    return packets


def on_hit(actor,flight,target,now):
    if actor.arena.pk['finished']:return []
    if flight['template'] in (1000106,1000125,1000131):return poison(actor,target,now,10001062)
    pos=target.position_at(now);packets=[]
    for other in targets(actor,pos,200,now,(target.id,)):
        if not actor.projectile_blocked(other,now):
            packets+=actor.damage(flight['raw'],now,target=other,school='physical',basic=True,
                                  source_generation=flight['source_generation'])[0]
            if actor.arena.pk['finished']:return packets
    if flight['template']==1020022:
        for other in targets(actor,pos,300,now):packets+=actor._buff(10200211,now,other.id)
    return packets


def event(actor,now,kind,data):
    if actor.arena.pk['finished']:return []
    if kind=='pve_plague':
        generation,=data
        if not actor.alive or actor.generation!=generation or not actor.has_buff(10001091,now):return []
        packets=[]
        for target in targets(actor,actor.position_at(now),168,now):
            packets+=actor.damage(actor.combat_stat('iAttack',now)*D('.5'),now,target=target,
                                  school='physical',periodic=True)[0]
            # Last-life damage can finish PvE inside this callback. Do not
            # repopulate the queue that native finish has just cleared.
            if actor.arena.pk['finished']:return packets
        actor._queue(now+500,kind,generation)
        return packets
    ident,target_generation,buff,version,generation,remaining=data
    target=actor.arena.actors.get(ident)
    if (not target or not target.alive or target.generation!=target_generation
            or target.buff_versions.get(buff)!=version or target.buff_sources.get(buff)!=actor.id):return []
    if not target.has_buff(buff,now) and remaining!=1:return []
    packets=actor.damage(target.max_hp*D('.05'),now,target=target,school='true',periodic=True,
                          source_generation=generation)[0]
    if remaining>1 and not actor.arena.pk['finished']:
        actor._queue(now+1000,kind,ident,target_generation,buff,version,generation,remaining-1)
    return packets
