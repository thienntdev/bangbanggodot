"""Observed breakable cover at a blocked native walk step, across game modes."""
from collections import Counter, OrderedDict
import math

from combat_geometry import rect_contact


def _without(arena, rectangles):
    """Hypothetical geometry for a probe only; never used to move an actor."""
    from battle_map import BattleMap
    nav = arena.navigation
    cached = getattr(nav, 'obstacle_probes', None)
    if cached is None or cached[0] is not arena.geometry.movement_walls:
        cached = nav.obstacle_probes = (arena.geometry.movement_walls, OrderedDict())
    cache = cached[1]
    key = tuple(sorted(rectangles))
    if key not in cache:
        geometry = BattleMap(arena.geometry.id)
        removed = Counter(tuple(r) for r in geometry.data['movement_walls']) - Counter(arena.geometry.movement_walls)
        geometry.remove_objects(list(removed.elements()) + list(key))
        cache[key] = geometry
        if len(cache) > 16:
            cache.popitem(last=False)
    return cache[key]


def note_blockage(arena, actor, brain, waypoint, goal, now):
    """Queue a hint; only the next delayed decision may acquire/fire at it."""
    if actor.info.get('npc_template'):
        return
    from battle_runtime import DIRECTIONS
    pos = actor.position_at(now)
    observed = []
    for row in brain.get('observations', ()):
        target = arena.actors.get(row['id'])
        if (row.get('barrier') and target is not None and target.alive and
                target.generation == row['generation'] and getattr(target, 'ordinary_obstacle', False) and
                target.camp != actor.camp and math.dist(pos, row['pos']) < 480):
            observed.append((row, target))
    if not observed:
        return
    water = arena.water_rects(now)
    steps = sorted((math.dist((pos[0]+24*dx, pos[1]+24*dy), waypoint), i,
                    (pos[0]+24*dx, pos[1]+24*dy)) for i, (dx, dy) in enumerate(DIRECTIONS[:8]))
    for distance, _, dest in steps:
        if distance >= math.dist(pos, waypoint):
            continue
        blocked = [(row, obj) for row, obj in observed
                   if rect_contact(dest, dest, (obj.map_rect,), 35.999) is not None]
        if not blocked:
            continue
        # Prove that these specific observed objects, rather than immutable
        # terrain, water, a pickup or a friendly building, block the real step.
        probe = _without(arena, [obj.map_rect for _, obj in blocked])
        if probe.walk_end(pos, dest, water) != dest:
            continue
        visible = [(row, obj) for row, obj in blocked if
                   arena.geometry.wall_contact(pos, row['pos'], 12, exclude=(obj.map_rect,), bullets=True) is None]
        if not visible:
            continue
        row, _ = min(visible, key=lambda pair: (math.dist(pos, pair[0]['pos']), pair[0]['id']))
        brain['route_blocker'] = dict(id=row['id'], generation=row['generation'], goal=tuple(goal), origin=pos)
        return


def selected(brain, seen, objective, position=None):
    hint = brain.get('route_blocker')
    if hint is None:
        return None
    if ((objective and math.dist(hint['goal'], objective[1]) > 96) or
            (position is not None and hint.get('origin') is not None and math.dist(position, hint['origin']) > 96)):
        brain.pop('route_blocker', None)
        return None
    row = next((s for s in seen if s['id'] == hint['id'] and
                s['generation'] == hint['generation'] and s.get('barrier')), None)
    if row is None:
        brain.pop('route_blocker', None)
    return row
