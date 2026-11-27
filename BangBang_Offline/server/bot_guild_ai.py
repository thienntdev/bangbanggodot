"""Guild decisions after the existing kit AI, on its delayed observations.

Does not replace movement, target selection, objective logic or consume RNG.
The native Guild executor remains responsible for all cast/cooldown guards.
"""
import math
from combat_math import D
import guild_combat


def busy(actor, now):
    if now < actor.forced_until:
        return True
    if any(getattr(actor, key, None) for key in ('channel', 'ready', 'dash', 'hook',
            'e_follow', 'dracula_ritual', 'caocao_hostage', 'hostage', 'leap')):
        return True
    # A borrowed kit or a pending native follow-up retains its own policy.
    import bot_ai
    for n in range(5, 20):
        module = getattr(bot_ai, 'bot_ai%02d' % n, None)
        if (module and actor.info['tank_id'] in module.TANKS and hasattr(module, 'recast')
                and any(module.recast(actor, slot, now) for slot in (1, 2, 10))):
            return True
    return False


def decide(arena, actor, brain, seen, now):
    if not actor.info.get('bot_loadout_version') or not actor.info.get('guild'):
        return []
    item = guild_combat.active(actor)
    if (not item or not actor.alive or actor.in_stasis() or arena.pk.get('finished')
            or now < arena.pk.get('intro_until', 0) or arena.pk.get('round_phase') == 'result'
            or now < getattr(actor, 'guild_ready_at', 0) or busy(actor, now)):
        return []
    # Avoid exposing a stealth approach by firing an unrelated active skill.
    if actor.is_untargetable() or actor.has_buff(510501, now):
        return []
    pos = actor.position_at(now)
    visible = [s for s in seen if now-s.get('observed_at', now) <= 750
               and not s.get('structure') and not s.get('barrier')
               and math.dist(pos, s['pos']) <= 600
               and arena.geometry.wall_contact(pos, s['pos']) is None]
    group, use = item['group'], False
    if group == 1100:
        # Heal only real missing HP; share the heal when teammates are in reach.
        allies = guild_combat.nearby(actor, 192, now, allies=True, tanks=True)
        use = any(a.hp <= a.max_hp*D('.80') for a in allies)
    elif group == 1500:
        threatened = any(math.dist(pos, s['pos']) <= 480 for s in visible) or bool(brain.get('bullets'))
        use = threatened and actor.hp <= actor.max_hp*D('.72') and not actor.shields
    elif group in (1800, 2600):
        reach = min(600, max(192, int(actor.stats.get('nFireRange', 0))))
        use = any(math.dist(pos, s['pos']) <= reach for s in visible)
        if group == 1800:
            use = use and actor.cooldowns.get(0, 0) <= now+500
    elif group == 3100:
        # Don't spend the execute on a full-health enemy or change chase goals.
        use = any(not s.get('objective', s.get('robo', False)) and s['hp'] <= .35
                  and math.dist(pos, s['pos']) <= 180 for s in visible)
    elif group == 3300:
        # Native action gaps / E2 / borrowed chains are excluded by busy().
        refill = getattr(actor, 'e_next_charge', 0) if hasattr(actor, 'e_next_charge') else actor.cooldowns.get(1, 0)
        use = bool(visible) and refill >= now+3500
    if not use:
        return []
    from bot_ai import perform
    return perform(arena, actor, 4, pos, 0, now)
