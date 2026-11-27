"""Explicit, frozen PvP controller selection for ranked and unranked rooms.

An absent marker always means the historical AI, including restored matches.
New matches copy the room policy: unranked rooms use the saved manual choice;
ranked rooms select it once from the owner's authoritative current-season rank
in ranked_matches.prepare_room. Runtime/restore never infer policy from stats
or a displayed medal. Casual rooms choose the policy separately for each camp;
ranked rooms freeze each camp's automatic policy from its human participant.
"""

LEGACY = 'legacy'
ELITE = 'elite_v1'
POLICIES = (LEGACY, ELITE)


def validate(value):
    if not isinstance(value, str) or value not in POLICIES:
        raise ValueError('AI bot phải là Bot gốc hoặc Bot V3.')
    return value


def prepare_match(state):
    """Called once by the native new-battle path, never by restore/respawn."""
    from bot_setup import BOT_MAPS
    room = state.get('room') or {}
    battle = state.get('battle')
    if battle is None:
        raise ValueError('Chưa có trận để chốt bộ AI.')
    if (room.get('map_id') not in BOT_MAPS or room.get('room_type') == 4
            or room.get('tank_test')):
        return
    policy = validate(room.get('bot_ai', LEGACY))
    if policy == ELITE:
        battle['bot_ai'] = policy
    overrides = room.get('bot_ai_camps')
    if overrides is not None:
        if not isinstance(overrides, dict) or set(map(str, overrides)) - {'1', '2'}:
            raise ValueError('Invalid camp-policy map')
        battle['bot_ai_camps'] = {str(camp): validate(overrides.get(str(camp), overrides.get(camp, policy)))
                                  for camp in (1, 2)}
    # Policy freezing never consumes combat RNG.


def policy_for(arena, actor):
    if (actor.info.get('human', actor.id == 1) or actor.info.get('npc_template') or not arena.pk
            or getattr(arena, 'tank_test', False)
            or (arena.state.get('room') or {}).get('room_type') == 4):
        return LEGACY
    battle = arena.state.get('battle') or {}
    overrides = battle.get('bot_ai_camps')
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError('Invalid camp-policy map')
        # JSON world persistence stringifies numeric dictionary keys.
        choice = overrides.get(actor.camp, overrides.get(str(actor.camp)))
        if choice is not None:
            return validate(choice)
    return validate(battle.get('bot_ai', LEGACY))
