"""Frozen player / opted-in bot crystals; native combat rules stay authoritative."""
from combat_math import D
from bot_loadouts import eligible

FLAT = {2: ('iArmor', 'iEgArmor'), 4: ('iAttack',), 5: ('iEgAtk',),
        6: ('iArmor',), 7: ('iEgArmor',), 8: ('iCentesis',), 9: ('iEgCtsis',), 12: ('iHp',)}


def bonus(actor, attributes, value_type=2):
    if not eligible(actor.id, actor.info):
        return D(0)
    return sum((D(value) for attr, kind, value in actor.info.get('crystals', [])
                if kind == value_type and attr in attributes), D(0))


def apply_flat(stats, info):
    for attr, kind, value in info.get('crystals', []):
        if kind == 1:
            for field in FLAT.get(attr, ()):
                stats[field] = str(D(stats[field]) + D(value))
    return stats


def cooldown(actor, duration, slot):
    from military_rank import cooldown_rate
    rate = bonus(actor, (16,)) + cooldown_rate(actor)
    if not rate:
        from battle_levels import cooldown as native_cooldown
        return native_cooldown(actor, duration, slot)
    if slot == 0 or (slot in (1, 2, 10) and hasattr(actor, {1: 'e_next_charge', 2: 'space_next_charge', 10: 'r_next_charge'}[slot])):
        return duration
    from battle_levels import enabled, row
    owner = vars(actor).get('_host', actor)
    level_rate = D(row(owner.info.get('battle_level', 1))['fSkillCoolTimeReduceRate']) if enabled(actor) else D(0)
    return max(0, round(D(duration) * max(D(0), 1 - level_rate + rate)))


def critical(actor, key, *, basic, school, handled, reflected, resolved):
    rate = bonus(actor, (27,))
    if not basic or school == 'true' or handled or reflected or resolved or rate <= 0:
        return False
    cache = actor.crystal_crits
    if key not in cache:
        cache[key] = actor.arena.rng.random() < float(min(D(1), rate))
    return cache[key]


def vamp(actor, target, *, basic, reflected, resolved, allowed):
    if not allowed or reflected or resolved or target.camp == actor.camp:
        return D(0)
    return bonus(actor, (28 if basic else 29,))


def regenerate(actor, now):
    amount = bonus(actor, (26,), 1)
    if not amount:
        return []
    if not actor.alive or actor.in_stasis():
        actor.crystal_heal_at = now + 5000
        return []
    packets = []
    while actor.crystal_heal_at <= now:
        packets += actor.restore_hp(amount, actor.crystal_heal_at)
        actor.crystal_heal_at += 5000
    return packets
