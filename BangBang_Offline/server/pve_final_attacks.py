"""Reviewed chapter-eight/nine attacks; unknown boss-script skills stay deferred."""
import math
from combat_math import D
from combat_protocol import scene,skill_event
from pve_shots import targets


def visible(actor,target,now):
    from bot_ai import observable
    return any(observable(actor.arena,scout,target,now,600)
               for scout in actor.arena.actors.values() if scout.alive and scout.camp==actor.camp)


def chain(actor,start,target,now,context=None):
    if not target or not target.alive or not visible(actor,target,now):return []
    initial=context is None
    context=context or dict(hits=[],generation=actor.generation)
    if target not in targets(actor,start,450 if initial else 312,now):return []
    packets=actor.shoot(1000120 if initial else 1001120,start,target.position_at(now),now,
        target.max_hp*D('.25'),school='energy',basic=True,target=target,context=context)
    return packets


def bounce(actor,flight,target,now):
    context=flight.get('context')
    if not context or flight.get('reflected') or context['generation']!=actor.generation:return []
    key=(target.id,target.generation)
    context['hits'].append(key)
    if len(context['hits'])>=5 or actor.arena.pk['finished']:return []
    pos=target.position_at(now)
    choices=[t for t in targets(actor,pos,312,now) if (t.id,t.generation) not in context['hits']
             and visible(actor,t,now)]
    if not choices:return []
    next_target=min(choices,key=lambda t:(math.dist(pos,t.position_at(now)),t.id))
    return chain(actor,pos,next_target,now,context)


def spider_explode(actor,now):
    if getattr(actor,'pve_exploded',False):return []
    actor.pve_exploded=True;pos=actor.position_at(now)
    packets=[scene(skills=(skill_event(1000122,pos,pos,owner=actor.id),))]
    for target in targets(actor,pos,144,now):
        packets+=actor.damage(D(100)+actor.combat_stat('iAttack',now),now,target=target,school='true',basic=True)[0]
    if actor.alive:packets+=actor.commit_hp(D(0),now)
    return packets
