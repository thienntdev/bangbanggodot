"""Opt-in local tactics for mobile hostile PvE combatants.

This changes decisions, never native stats, weapons, cooldowns or navigation.
Perception is local line-of-sight every200ms. A lost target leaves only its
last observed point for1800ms, not a live position behind cover. Planning is
bounded to sixteen local candidates every800ms; the existing native24px walk
owns terrain/water/body spacing. Scripted actors retain their chapter logic.

M44 adds opt-in air/ordinary stationary combat and aligns firing decisions
with the native water-blocked projectile executor. Old frozen runs retain
the M43 policy, including its original candidate ordering and target choices.
"""
import math

from combat_geometry import rect_contact
from pve_balance import frozen_profile

PERCEPTION_MS = 200
PLAN_MS = 800
MEMORY_MS = 1800
NOTICE_RANGE = 600

# Chapter-owned traps, transport/escort/support and bespoke boss controllers.
# Speed alone is not sufficient to distinguish an enemy from a moving saw.
SCRIPTED = frozenset((
    255, 261, 263, 264, 265, 266,
    409, 414, 415, 416, 440, 612, 613,
    1409, 1414, 1416, 1440, 353, 342,
    1350, 1351, 1353, 1354, 2612, 2613, 2673, 2676,
    517, 518, 519, 520, 522, 524, 525, 526, 527, 567, 578,
    717, 718, 719, 720, 721, 3110112, 3110113, 3110310, 3110312,
    3130108, 3130210, 3130211, 3140212, 3160203,
    3150209, 3150210, 3160111, 3160112, 3160113, 3160115, 3160116,
    3160211,
))
SPECIAL_WEAPONS = frozenset((
    0, 1000034, 1000062, 1000122,  # Suicide explosions retain their trigger.
    1000054, 1000055, 1000057, 1000060, 1000061, 1000134, 50332,
))
LOB_WEAPONS = frozenset((1000010, 1000017, 1000037, 1000065, 1000069))


def enabled(arena):
    profile = frozen_profile(arena)
    return bool(profile and type(profile.get('pve_tactics_version')) is int
                and profile['pve_tactics_version'] == 1)


def eligible(actor):
    info = actor.info
    return bool(info.get('pve_npc') and actor.camp != actor.arena.player.camp
                and info.get('npc_template') not in SCRIPTED
                and not any(info.get(key) for key in (
                    'pve_hostage', 'pve_trap', 'pve_stationary', 'pve_flying',
                    'pve_fortification', 'pve_local_forklift', 'map_object'))
                and actor.shot_skill not in SPECIAL_WEAPONS
                and actor.pve_fire_range > 0 and int(actor.stats['iSpeed']) > 0)


def upgraded(arena):
    """The additional policy never upgrades chapter one or an old snapshot."""
    from pve_catalog import MAPS
    profile = frozen_profile(arena) or {}
    version = profile.get('pve_mob_tactics_version')
    return (type(version) is int and version == 1
            and arena.geometry.id in MAPS[5:]
            and profile.get('map_id') == arena.geometry.id)


def extended_eligible(actor):
    """Ordinary air and fixed guns; authored utility/hazard roles stay out."""
    info = actor.info
    if not (info.get('pve_npc') and actor.camp != actor.arena.player.camp
            and info.get('npc_template') not in SCRIPTED
            and not any(info.get(key) for key in (
                'pve_hostage', 'pve_trap', 'pve_fortification',
                'pve_local_forklift', 'map_object'))
            and actor.shot_skill not in SPECIAL_WEAPONS and actor.pve_fire_range > 0):
        return False
    profile = frozen_profile(actor.arena) or {}
    version = profile.get('pve_boss_tactics_version')
    if type(version) is int and version == 1:
        from pve_boss_tactics_v2 import handles
        if handles(actor):
            return False  # Its chapter hook owns all decisions for this boss.
    return bool(info.get('pve_stationary') or int(actor.stats['iSpeed']) > 0)


def weapon_line(actor, start, end, now):
    """Visible direct aim must also survive native projectile water checks.

    Even the native lob executor expires on a crossed water segment. Flight
    movement can cross water; this does not imply its weapon can do the same.
    """
    return (actor.arena.geometry.wall_contact(start, end) is None
            and rect_contact(start, end, actor.arena.water_rects(now)) is None)


def _line(actor, start, end, now):
    if upgraded(actor.arena):
        return weapon_line(actor, start, end, now)
    return (actor.arena.geometry.wall_contact(start, end) is None
            and (actor.shot_skill in LOB_WEAPONS
                 or rect_contact(start, end, actor.arena.water_rects(now)) is None))


def choose_goal(actor, target_pos, now, *, fire_range=None,
                preferred_range=None, strafe=False, strafe_side=None):
    """Return a bounded legal goal; never move, teleport, or mutate the map.

    This helper may also be called by a chapter-owned mobile boss. All actual
    motion still goes through pve_movement.move and its native step checks.
    """
    from battle_runtime import DIRECTIONS

    arena = actor.arena
    pos = actor.position_at(now)
    radius = float(actor.pve_fire_range if fire_range is None else fire_range)
    melee = radius <= 180
    ideal = (max(48, radius * .65) if melee else min(360, max(144, radius * .66)))
    if preferred_range is not None:
        ideal = max(24, min(radius, float(preferred_range)))
    distance = math.dist(pos, target_pos)
    water = arena.water_rects(now)
    # Physical avoidance only consults nearby friendly bodies, not hidden foes.
    friends = sorted((a.position_at(now) for a in arena.actors.values()
                      if a is not actor and a.alive and a.camp == actor.camp
                      and not a.info.get('map_object')
                      and math.dist(pos, a.position_at(now)) < 240),
                     key=lambda p: math.dist(pos, p))[:8]
    dx, dy = target_pos[0] - pos[0], target_pos[1] - pos[1]
    length = max(1, math.hypot(dx, dy))
    side = (1 if actor.id % 2 else -1) if strafe_side is None else (1 if strafe_side >= 0 else -1)
    choices = [pos]
    for step in (48, 96):
        for ux, uy in DIRECTIONS[:8]:
            point = (round(pos[0] + ux * step), round(pos[1] + uy * step))
            if arena.geometry.walk_end(pos, point, water) == point:
                choices.append(point)

    def score(point):
        gap = math.dist(point, target_pos)
        # Ranged bodies back out of melee and settle inside their real range;
        # melee bodies close in instead of orbiting outside attack distance.
        spacing = abs(gap - ideal)
        if melee and gap <= radius:
            spacing *= .35
        clear = _line(actor, point, target_pos, now)
        obstruction = 300 if not clear else 0
        crowd = sum(max(0, 84 - math.dist(point, p)) * 2 for p in friends)
        travel = math.dist(pos, point) * .07
        lateral = ((point[1] - pos[1]) * dx - (point[0] - pos[0]) * dy) / length
        # A small bounded strafe is worthwhile inside the useful firing band,
        # but cannot outweigh range, cover, or allied-body spacing.
        orbit = (-min(24, max(0, side * lateral) * .35)
                 if strafe and not melee and distance <= radius else 0)
        return spacing + obstruction + crowd + travel + orbit

    current = score(pos)
    goal = min(choices, key=lambda p: (score(p), math.dist(pos, p), p))
    if not _line(actor, pos, target_pos, now):
        clear = [p for p in choices if _line(actor, p, target_pos, now)]
        if clear:
            return min(clear, key=lambda p: (score(p), math.dist(pos, p), p))
        # A visible tank across water can be inside range with no legal shot.
        # Commit to a short side probe instead of firing forever into water or
        # stopping at the ideal range. Probes remain within perception range.
        limit = min(NOTICE_RANGE - 24, max(radius * 1.15, distance + 24))
        probes = [p for p in choices if p != pos and math.dist(p, target_pos) <= limit]
        def probe_score(point):
            lateral = ((point[1]-pos[1])*dx - (point[0]-pos[0])*dy) / length
            crowd = sum(max(0, 84-math.dist(point, p))*2 for p in friends)
            return (abs(math.dist(point, target_pos)-ideal)*.2 + crowd
                    - abs(lateral) - (16 if side*lateral > 0 else 0))
        if probes:
            return min(probes, key=lambda p: (probe_score(p), math.dist(pos, p), p))
    if score(goal) < current - 2:
        return goal
    # If a distant observed goal needs a real route around cover, keep A*'s
    # ordinary bounded search instead of deciding to stand still forever.
    if distance > radius * .9:
        return tuple(target_pos)
    return pos


def choose_air_goal(actor, target_pos, now, *, preferred_range=None,
                    strafe=False, strafe_side=None):
    """At most16 local air candidates; terrain crossing stays native."""
    from battle_runtime import DIRECTIONS
    arena = actor.arena
    pos = actor.position_at(now)
    radius = float(actor.pve_fire_range)
    ideal = min(360, max(144, radius*.66)) if preferred_range is None else max(24, min(radius, float(preferred_range)))
    distance = math.dist(pos, target_pos)
    friends = sorted((a.position_at(now) for a in arena.actors.values()
                      if a is not actor and a.alive and a.camp == actor.camp
                      and not a.info.get('map_object')
                      and math.dist(pos, a.position_at(now)) < 240),
                     key=lambda p: math.dist(pos, p))[:8]
    dx, dy = target_pos[0]-pos[0], target_pos[1]-pos[1]
    length = max(1, math.hypot(dx, dy))
    side = (1 if actor.id % 2 else -1) if strafe_side is None else (1 if strafe_side >= 0 else -1)
    choices = [pos]
    for step in (48, 96):
        for ux, uy in DIRECTIONS[:8]:
            point = (round(pos[0]+ux*step), round(pos[1]+uy*step))
            if arena.geometry.clamp_tank_position(point) == point and arena.geometry.in_playable_region(point):
                choices.append(point)

    def score(point):
        spacing = abs(math.dist(point, target_pos)-ideal)
        crowd = sum(max(0, 84-math.dist(point, p))*2 for p in friends)
        lateral = ((point[1]-pos[1])*dx-(point[0]-pos[0])*dy)/length
        orbit = (-min(24, max(0, side*lateral)*.35)
                 if strafe and distance <= radius else 0)
        return spacing+crowd+math.dist(pos, point)*.07+orbit

    clear = [point for point in choices if weapon_line(actor, point, target_pos, now)]
    if clear:
        best = min(clear, key=lambda point: (score(point), math.dist(pos, point), point))
        if not weapon_line(actor, pos, target_pos, now) or score(best) < score(pos)-2:
            return best
    elif len(choices) > 1:
        # A plane above water/cover can see a tank without a viable shot. Move
        # out along a bounded side probe; never grant its bullets wall bypass.
        probes = [point for point in choices if point != pos
                  and math.dist(point, target_pos) <= max(NOTICE_RANGE-24, distance+24)]
        if probes:
            def probe(point):
                lateral = ((point[1]-pos[1])*dx-(point[0]-pos[0])*dy)/length
                return score(point)*.2-abs(lateral)-(16 if side*lateral > 0 else 0)
            return min(probes, key=lambda point: (probe(point), point))
    if distance > radius*.9:
        return arena.geometry.clamp_tank_position(target_pos)
    return pos


def _target(actor, state, now):
    from bot_ai import observable

    arena = actor.arena
    pos = actor.position_at(now)
    choices = [target for target in arena.actors.values()
               if not target.info.get('map_object') and not target.info.get('pve_hostage')
               and observable(arena, actor, target, now, NOTICE_RANGE)]
    if not choices:
        return None
    modern = upgraded(arena)
    def shootable(target):
        point = target.position_at(now)
        return math.dist(pos, point) <= actor.pve_fire_range and weapon_line(actor, pos, point, now)
    nearest = min(choices, key=lambda t: ((not shootable(t)) if modern else False,
                                        math.dist(pos, t.position_at(now)), t.id))
    current = next((t for t in choices if t.id == state.get('target')
                    and t.generation == state.get('target_generation')), None)
    # Avoid rapid target flipping when two allies cross each other. A much
    # closer opponent still wins, so the NPC does not ignore a new melee threat.
    if (current and (not modern or shootable(current) or not shootable(nearest))
            and math.dist(pos, current.position_at(now)) <= math.dist(pos, nearest.position_at(now)) + 96):
        return current
    return nearest


def _set_goal(brain, goal):
    goal = tuple(goal)
    if brain.get('goal') is None or math.dist(goal, brain['goal']) >= 24:
        brain['path'] = []
        brain['repath_at'] = 0
    brain['goal'] = goal
    brain['pve_patrolling'] = False


def tick(actor, brain, now):
    """None leaves the chapter controller untouched; a list owns this tick."""
    arena = actor.arena
    modern = upgraded(arena)
    if not enabled(arena) or not (extended_eligible(actor) if modern else eligible(actor)):
        return None
    if arena.pk['finished'] or not actor.alive or actor.in_stasis():
        return []
    from pve_movement import move, patrol_goal, flight_move

    state = brain.get('pve_tactics')
    if (not isinstance(state, dict) or state.get('generation') != actor.generation
            or state.get('version', 1) != (2 if modern else 1)):
        state = dict(generation=actor.generation, notice_at=0, next_tick_at=0,
                     end=0, maneuver=0, target=None)
        brain['pve_tactics'] = state
        brain['path'] = []
        brain['repath_at'] = 0
        if modern:
            state['version'] = 2
    packets = []
    if now >= state['notice_at']:
        state['notice_at'] = now + PERCEPTION_MS
        brain['notice_at'] = state['notice_at']
        target = _target(actor, state, now)
        if target is not None:
            changed = (state.get('target'), state.get('target_generation')) != (target.id, target.generation)
            point = tuple(target.position_at(now))
            state.update(target=target.id, target_generation=target.generation,
                         position=point, observed_at=now, end=now + MEMORY_MS)
            # Planning waits for the end of the active native step. Interrupting
            # a slow NPC every200ms used to strand it on diagonal wall corners.
            boundary = not (actor.motion and actor.motion[3] > now)
            if boundary and (changed or now >= state['next_tick_at']):
                state['maneuver'] += 1
                strafe = (actor.cooldowns[0] > now + PERCEPTION_MS
                          and state['maneuver'] % 3 != 0)
                goal = (actor.position_at(now) if actor.info.get('pve_stationary') else
                        choose_air_goal(actor, point, now, strafe=strafe) if actor.info.get('pve_flying') else
                        choose_goal(actor, point, now, strafe=strafe))
                _set_goal(brain, goal)
                state['next_tick_at'] = now + PLAN_MS
            pos = actor.position_at(now)
            if math.dist(pos, point) <= actor.pve_fire_range and _line(actor, pos, point, now):
                # Cast respects all native attack/slot locks and its own cooldown;
                # moving between shots does not grant another shot or a stat buff.
                packets += actor.cast(0, pos, point, target.id, now)
        else:
            prior = arena.actors.get(state.get('target'))
            valid_memory = (prior is not None and prior.alive
                            and prior.generation == state.get('target_generation')
                            and now < state['end'] and 'position' in state)
            if valid_memory:
                if not (actor.motion and actor.motion[3] > now) and now >= state['next_tick_at']:
                    # Crucially this uses only the saved observation, never the
                    # hidden actor's current position. No attack without new LOS.
                    _set_goal(brain, actor.position_at(now) if actor.info.get('pve_stationary') else state['position'])
                    state['next_tick_at'] = now + PLAN_MS
            else:
                state['target'] = None
                state['end'] = 0
                state['next_tick_at'] = now
                brain['goal'] = patrol_goal(arena, actor, now, air_arrival=24 if modern else 12)
    if arena.pk['finished']:
        return packets
    # Recheck visibility at the next perception before another cast; movement
    # alone never acquires targets or fires through a newly closed wall.
    if modern and actor.info.get('pve_flying'):
        if brain.get('pve_patrolling'):
            brain['goal'] = patrol_goal(arena, actor, now, air_arrival=24)
        packets += flight_move(arena, actor, brain, brain.get('goal'), now)
    else:
        packets += move(arena, actor, brain, now)
    return packets
