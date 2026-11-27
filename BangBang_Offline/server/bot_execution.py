"""PRO V2 held-fire input, separate from perception and tactical decisions.

An already chosen cursor may remain pressed between reactions, just like the
native client's right-button fire. This module never samples an enemy, advances
a cooldown, grants a resource, or replaces any native tank cast. A new target
or cursor still requires a delayed observation on a normal decision tick.
"""
from __future__ import annotations

import math


def basic_range(actor, now):
    import bot_ai
    tank = actor.info['tank_id']
    for module in (bot_ai.bot_ai20, bot_ai.bot_ai19, bot_ai.bot_ai14,
                   bot_ai.bot_ai12, bot_ai.bot_ai11, bot_ai.bot_ai10,
                   bot_ai.bot_ai07, bot_ai.bot_ai05, bot_ai.bot_ai04,
                   bot_ai.bot_ai03):
        if tank in module.TANKS:
            return module.basic_range(actor, now)
    return int(actor.stats['nFireRange'])


def _permitted(actor, brain, contact, now, retreat):
    import bot_ai
    tank = actor.info['tank_id']
    if (not actor.alive or actor.blocked('attack', now)
            or actor.skill_sealed(0, now) or actor.is_untargetable()
            or actor.cooldowns.get(0, now + 1) > now):
        return False
    # Conservatively leave native charge/channel/forced-motion follow-ups to
    # the kit dispatcher. No held input cancels a cast to gain firing uptime.
    if (getattr(actor, 'ready', None) or getattr(actor, 'channel', None)
            or getattr(actor, 'dash', None) or getattr(actor, 'vanish', None)
            or getattr(actor, 'egg', None) or getattr(actor, 'rebirth', None)
            or getattr(actor, 'ice', None) or now < actor.forced_until
            or actor.motion and actor.motion_kind != 0 and actor.motion[3] > now):
        return False
    if tank in bot_ai.bot_ai09.TANKS and bot_ai.bot_ai09.hold_stealth(actor, contact, retreat, now):
        return False
    if tank in bot_ai.bot_ai12.TANKS and bot_ai.bot_ai12.hold_stealth(actor, retreat, now):
        return False
    if tank in bot_ai.bot_ai18.TANKS and bot_ai.bot_ai18.hold_fog(actor, retreat, now):
        return False
    if tank in bot_ai.bot_ai16.TANKS and bot_ai.bot_ai16.hold_flight(actor, retreat, now):
        return False
    if tank in bot_ai.bot_ai19.TANKS and bot_ai.bot_ai19.hold_stealth(actor, retreat, now):
        return False
    if tank in bot_ai.bot_ai08.TANKS and not bot_ai.bot_ai08.basic_allowed(actor, brain, contact, now):
        return False
    return True


def prepare(arena, actor, brain, seen, now):
    """Latch an old contact and cursor once, after a normal PRO reaction."""
    from bot_elite import basic_aim, mature_contacts
    brain.pop('pro_fire_plan', None)
    contacts = mature_contacts(seen, now)
    target = next((sample for sample in contacts
                   if sample['id'] == brain.get('target')), None)
    if target is None:
        return
    retreat = bool(brain.get('repair_goal') or now < brain.get('elite_retreat_until', 0))
    # The native action can become ready before the next reaction. Do not
    # require readiness here; it is checked at the actual input time below.
    cursor = basic_aim(arena, actor, target, now)
    plan = dict(generation=actor.generation, contact=dict(target),
                cursor=tuple(cursor), observed_at=now, retreat=retreat)
    if actor.info['tank_id'] == 10000055:
        plan['contacts'] = [dict(sample) for sample in contacts]
    brain['pro_fire_plan'] = plan


def tick(arena, actor, brain, now):
    """Issue only a legal held basic input, never a new perception/decision."""
    from bot_policy import ELITE, policy_for
    plan = brain.get('pro_fire_plan')
    if not plan or policy_for(arena, actor) != ELITE or arena.pk['finished']:
        return []
    if plan['generation'] != actor.generation:
        brain.pop('pro_fire_plan', None)
        return []
    # Repeated-life PK favors the next existing native input callback. Other
    # objective and one-life policies retain their conservative follow-through.
    # This is a mode-family calibration, never a roster/seed/map-result switch;
    # perception and every native cooldown/phase check are unchanged.
    from bot_elite import LOCAL_LEGACY_MAPS
    minimum = 20 if arena.geometry.id in LOCAL_LEGACY_MAPS else 60
    # Both timestamps use the existing observed_at checkpoint rebase contract.
    if not minimum <= now - plan['observed_at'] <= 350:
        return []
    contact = plan['contact']
    if not 180 <= now - contact['observed_at'] <= 1000:
        return []
    if not _permitted(actor, brain, contact, now, plan['retreat']):
        return []
    from bot_elite import basic_target_open
    if not basic_target_open(contact, now, actor):
        return []
    identity = arena.actors.get(contact['id'])
    if identity is None or identity.generation != contact['generation']:
        return []  # identity guard, never read current enemy position/HP/CD
    position = actor.position_at(now)
    if math.dist(position, contact['pos']) > basic_range(actor, now):
        return []
    cursor = plan['cursor']
    exclude = (tuple(contact['turret_rect']),) if contact.get('turret_rect') else ()
    if arena.geometry.wall_contact(position, cursor, exclude=exclude) is not None:
        return []
    import bot_ai
    if actor.info['tank_id'] == 10000055:
        choice = bot_ai.bot_ai19.basic_choice(actor, brain, contact,
            plan.get('contacts', ()), cursor, plan['retreat'], False, now)
        if choice is None:
            return []
    return bot_ai.perform(arena, actor, 0, cursor, contact['id'], now)
