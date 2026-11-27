"""PvE-only authored patrol continuity; shared combat/PvP walking is unchanged.

NPC perception still runs on its original 200ms cadence. A route waypoint is
not a perception decision: advance it when the current native 24px walk ends,
and invalidate only the path to an obsolete patrol waypoint. Previously the
ordinary 1s A* cache left each short leg waiting after its path was exhausted.
"""
import math
import struct


def patrol_goal(arena, actor, now, *, air_arrival=12):
    brain = arena.bot_brains.setdefault(actor.id, dict(path=[], notice_at=0))
    brain['pve_patrolling'] = True
    if arena.geometry.id == 201:
        from pve_rules import _patrol as advance
    else:
        from pve_chapter1 import _patrol as advance
    if actor.info.get('pve_trap'):
        return advance(arena, actor, now)
    # Do not consume authored points or random graph edges during a movement,
    # CC or stationary state. Continue the selected route at the next boundary.
    if (actor.motion and actor.motion[3] > now or actor.blocked('move', now)
            or actor.info.get('pve_stationary') or actor._speed(now) <= 0):
        return brain.get('goal', actor.position_at(now))
    from bot_ai import Navigation
    flying = actor.info.get('pve_flying')
    if not flying and not hasattr(arena, 'navigation'):
        arena.navigation = Navigation(arena.geometry)
    pos = actor.position_at(now)
    visited = set()
    while True:
        if not actor.route_queue:
            if actor.info['npc_template'] == 266 and actor.route_point in (12, 14, 16):
                return pos  # Chapter one's approved extraction extension owns this end.
            edge = (actor.route_previous, actor.route_point)
            if edge in visited:
                return pos  # Includes an exhausted/dead-end/collapsed graph.
            visited.add(edge)
        goal = advance(arena, actor, now)
        if not actor.route_queue:
            continue  # Start the next authored leg without a 200ms idle tick.
        cell = goal if flying else arena.navigation.nearest(goal)
        if flying and air_arrival > 12:
            # Opt-in air controllers use whole native24px steps inside bounds.
            # An authored edge waypoint need not share that step lattice.
            cell = arena.geometry.clamp_tank_position(cell)
        if cell is None:
            return pos
        if math.dist(pos, cell) >= (air_arrival if flying else 20):
            return cell
        actor.route_queue.pop(0)


def flight_move(arena, actor, brain, goal, now):
    """One native air step for opt-in M44 controllers.

    Flying keeps its authored ability to cross terrain/water. Only the world
    boundary, movement/CC/lifecycle and friendly-body spacing are checked here;
    weapon line-of-fire remains a separate decision. A clamped goal does not
    make an overshooting24px endpoint legal. Never shorten MOVE_NORMAL or snap
    the aircraft to an arbitrary point.
    """
    if (arena.pk['finished'] or not actor.alive or actor.in_stasis()
            or goal is None or not actor.info.get('pve_flying')
            or actor.info.get('pve_stationary') or actor.blocked('move', now)
            or actor.motion and actor.motion[3] > now or actor._speed(now) <= 0):
        return []
    if len(goal) != 2 or not all(math.isfinite(v) for v in goal):
        return []
    from battle_runtime import DIRECTIONS
    from combat_protocol import scene
    pos = actor.position_at(now)
    goal = arena.geometry.clamp_tank_position(goal)
    distance = math.dist(pos, goal)
    if distance <= 12:
        return []
    friends = [a.position_at(now) for a in arena.actors.values()
               if a is not actor and a.alive and a.camp == actor.camp
               and not a.info.get('map_object') and math.dist(pos, a.position_at(now)) < 240]
    choices = []
    for direction, (dx, dy) in enumerate(DIRECTIONS[:8]):
        end = (pos[0]+24*dx, pos[1]+24*dy)
        if (arena.geometry.clamp_tank_position(end) != end
                or not arena.geometry.in_playable_region(end)
                or math.dist(end, goal) >= distance):
            continue
        if any(math.dist(end, p) < min(64, math.dist(pos, p)-1) for p in friends):
            continue
        choices.append((math.dist(end, goal), direction, end))
    if not choices:
        return []
    _, direction, end = min(choices)
    speed = actor._speed(now)
    duration = max(1, round(math.dist(pos, end)*1000/speed))
    actor.position, actor.motion = end, (pos, end, now, now+duration)
    actor.motion_kind = 0
    return [scene(moves=(struct.pack('<IhhhBB', actor.id, *pos, speed, direction, 0),))]


def move(arena, actor, brain, now):
    """Execute the selected PvE goal using native speed/CC/collision/spacing."""
    goal = brain.get('goal')
    if (arena.pk['finished'] or not actor.alive or goal is None
            or actor.info.get('pve_stationary')):
        return []
    from bot_ai import walk
    # Traps already have their separately verified boundary-advance policy in
    # bot_ai.walk. Do not modify it or turn combat movement into patrol.
    patrol = brain.get('pve_patrolling', False) and not actor.info.get('pve_trap')
    if not patrol:
        # Combat may replace brain.path while the cached authored goal stays
        # numerically identical. Re-entering that patrol must not reuse the
        # combat path until its unrelated one-second expiry.
        brain.pop('pve_path_goal', None)
    ready = not (actor.motion and actor.motion[3] > now)
    if patrol and ready and not actor.blocked('move', now) and actor._speed(now) > 0:
        goal = brain['goal'] = patrol_goal(arena, actor, now)
        if brain.get('pve_path_goal') != tuple(goal):
            brain['path'] = []
            brain['repath_at'] = 0
            brain['pve_path_goal'] = tuple(goal)
    if actor.info.get('pve_flying'):
        if not actor.blocked('move', now) and math.dist(actor.position_at(now), goal) > 12:
            return actor.fly(goal, now)
        return []
    pos = actor.position_at(now)
    correction = []
    if (ready and not actor.blocked('move', now) and actor._speed(now) > 0
            and tuple(pos) == tuple(actor.spawn) and math.dist(pos, goal) >= 20
            and not actor.info.get('pve_trap') and not arena.geometry.can_walk_to(pos)):
        # A strict swept walk cannot start inside an object. Preserve M41's
        # authored-spawn egress (31303/601 clips its cover by2px) through the
        # shared shallow-overlap repair, never by allowing a walk through it.
        # Only an exact initial pose can take this route. Deep/multi-wall or
        # occupied exits stay blocked; scripted traps keep their own placement.
        water = arena.water_rects(now)
        occupied = [a.position_at(now) for a in arena.actors.values()
                    if a is not actor and a.alive and a.camp == actor.camp
                    and not a.info.get('map_object')]
        repaired = arena.geometry.recover_walk_position(pos, water, occupied)
        if repaired is not None and tuple(repaired) != tuple(pos):
            actor.position, actor.motion = tuple(repaired), None
            brain['path'] = []
            brain['repath_at'] = 0
            correction = [(1554, struct.pack('<IIhh', actor.scene_id, actor.id, *repaired))]
    return correction + walk(arena, actor, brain, goal, now)
