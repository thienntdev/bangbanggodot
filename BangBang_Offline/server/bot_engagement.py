"""PRO contact commitment, using old sightings and communicated allied state.

This is a pre-cast intention only. It cannot cancel a native action, issue a
move, alter resources, or bypass the shared kit executor. A healthy melee bot
does not mistake distant/repairing teammates for support at its dive endpoint.
"""
from __future__ import annotations

import math


def spacing_range(arena, actor, target, order, desired, now):
    """Use our basic-attack reach while every usable active skill is cooling.

    The native preferred distance often assumes a melee combo is available.
    Remaining in that distance for its entire cooldown needlessly trades away
    health. This changes only a walk intention; the existing native kit may
    still override it. Own recasts, pending actions and objective holders retain
    their existing spacing. No enemy cooldown or future pose is consulted.
    """
    from bot_policy import ELITE, policy_for
    if not getattr(arena, 'state', None) or policy_for(arena, actor) != ELITE:
        return desired
    if (order.get('task') not in ('skirmish', 'clear_path', 'survive')
            or target.get('objective', target.get('robo', False))
            or any(getattr(actor, key, None) for key in (
                'channel', 'ready', 'dash', 'vanish', 'hook', 'leap', 'e_follow',
                'dracula_ritual', 'caocao_hostage', 'hostage', 'ice', 'egg', 'rebirth'))
            or now < actor.forced_until
            or actor.motion and actor.motion_kind != 0 and actor.motion[3] > now):
        return desired
    import bot_ai
    from bot_execution import basic_range
    tank = actor.info['tank_id']
    policies = [getattr(bot_ai, 'bot_ai%02d' % number) for number in range(1, 21)]
    recasts = [policy.recast for policy in policies
               if tank in policy.TANKS and hasattr(policy, 'recast')]
    for slot in (1, 2, 10):
        if actor.skill_sealed(slot, now):
            continue
        # Prepare to re-engage shortly before an OWN skill becomes available;
        # this is not a faster sensor or a cast before the native cooldown.
        if actor.cooldowns.get(slot, now + 1000) <= now + 350:
            return desired
        if any(recast(actor, slot, now) for recast in recasts):
            return desired
    reach = basic_range(actor, now)
    if reach < desired + 120:
        return desired
    return min(reach - 45, desired + 180)


def prepare(arena, actor, brain, seen, target, retreat, recovering, now):
    from bot_policy import ELITE, policy_for
    if policy_for(arena, actor) != ELITE:
        return retreat
    from bot_elite import LOCAL_LEGACY_MAPS, mature_contacts, _retreat_goal
    if arena.geometry.id not in LOCAL_LEGACY_MAPS:
        return retreat
    brain['pro_isolated_contact'] = False
    if (retreat or recovering
            or not actor.alive or actor.blocked('move', now)
            or any(getattr(actor, key, None) for key in (
                'channel', 'ready', 'dash', 'vanish', 'hook', 'leap',
                'e_follow', 'dracula_ritual', 'caocao_hostage', 'hostage'))
            or now < getattr(actor, 'forced_until', 0)
            or actor.motion and actor.motion_kind != 0 and actor.motion[3] > now):
        return retreat
    import bot_ai
    if bot_ai.bot_ai10.soul(actor):
        return retreat
    contacts = [s for s in mature_contacts(seen, now)
                if not s.get('objective', s.get('robo', False))]
    position = actor.position_at(now)
    threats = [s for s in contacts if math.dist(position, s['pos']) <= 600]
    if len(threats) < 2:
        return retreat
    allies = [friend for friend in arena.actors.values()
              if friend.camp == actor.camp and friend is not actor
              and friend.alive and not friend.info.get('npc_template')]
    if (float(actor.hp / actor.max_hp) < .4
            and bot_ai.useful_last_stand(actor, [actor] + allies, contacts, now)):
        return retreat
    # A teammate below 35%HP, disabled, or deliberately going to repair is
    # not counted as an immediate reinforcement merely because it is alive.
    ready = [friend for friend in allies
             if float(friend.hp / friend.max_hp) >= .35
             and not friend.blocked('attack', now)
             and not arena.bot_brains.get(friend.id, {}).get('repair_goal')]
    if any(math.dist(position, friend.position_at(now)) <= 420 for friend in ready):
        return retreat
    if any(math.dist(target['pos'], friend.position_at(now)) <= 480 for friend in ready):
        return retreat
    # Do not turn a currently available low-risk finish into an endless
    # regroup. This is an old displayed HP fraction, not exact hidden damage.
    if target['hp'] <= .18 and math.dist(position, target['pos']) <= 220:
        return retreat
    order = dict(task='regroup', goal=brain.get('goal', position))
    goal = _retreat_goal(arena, actor, ready, contacts, order, now)
    if goal is None:
        return retreat
    old_goal = brain.get('goal')
    brain['goal'] = tuple(round(value) for value in goal)
    if old_goal is None or math.dist(old_goal, brain['goal']) > 96:
        brain['repath_at'] = 0
    brain['pro_isolated_contact'] = True
    # Passing retreat into the unchanged kit prevents an optional forward
    # dive/recast; defensive skills and native pending follow-ups stay native.
    return True
