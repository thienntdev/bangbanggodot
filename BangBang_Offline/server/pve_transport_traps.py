"""Bounded local transport for the reviewed chapter-five/maze emitters.

The source provides directional AI, transparent projectiles and pull effect14,
but not the old server's destination script. This local rule pulls a tank to
the emitter's safe pocket. It may cross only its first adjacent static housing
span; live map objects, a second wall, water and occupied landings still block.
No damage, proc, objective, map geometry or global movement rule is changed.
"""
from collections import Counter
import math
import struct

from combat_data import table_row
from combat_geometry import actor_contact, point_at, rect_contact
from combat_protocol import scene, stop_move


RANGE = 600
GLOBAL_COOLDOWN = 3000
# Canonical map, authored point -> template, source. Hard aliases share these
# records only when their frozen local-mechanics profile also opts in.
SOURCES = {
    (501, 6): (519, (1740, 1572)),
    (501, 8): (519, (1740, 2052)),
    (501, 16): (520, (996, 1188)),
    (502, 54): (520, (804, 1476)),
    (502, 36): (519, (1572, 900)),
    (502, 38): (518, (2052, 516)),
    (502, 68): (520, (420, 2052)),
    (503, 8): (520, (900, 1764)),
    (503, 20): (517, (1668, 1356)),
    (503, 38): (519, (1500, 900)),
    (503, 40): (520, (1380, 324)),
    (31601, 711): (3160116, (843, 430)),
    (31601, 712): (3160113, (442, 650)),
    (31601, 713): (3160115, (1356, 765)),
}
DIRECTIONS = {
    517: (0, -1), 518: (0, 1), 519: (-1, 0), 520: (1, 0),
    3160113: (0, -1), 3160115: (-1, 0), 3160116: (1, 0),
}
# The north maze emitter has a 24px body; a 72px tank at its exact centre
# overlaps the lower wall by5.5px. This14px offset clears both the continuous
# footprint and the native24px grid (the tempting24px offset does not).
LANDINGS = {(31601, 712): (442, 636)}
# These exact decorative rail pieces sit beside three503 rays. An instant
# transport does not sweep the tank through their artwork; the projectile
# centre still collides with them, and landing/escape keep the full footprint.
# Real gates, protected/bomb walls and ordinary crates never get this exception.
TRANSIT_DECOR = {
    (503, 8): {140: (5002, (936., 1728., 960., 1752.))},
    (503, 38): {
        158: (5002, (1440., 912., 1464., 936.)),
        161: (5001, (1392., 864., 1416., 888.)),
        162: (5001, (1320., 864., 1344., 888.)),
        163: (5001, (1248., 864., 1272., 888.)),
        164: (5001, (1176., 864., 1200., 888.)),
        165: (5001, (1104., 864., 1128., 888.)),
    },
    (503, 40): {
        241: (5001, (1776., 336., 1800., 360.)),
        243: (5001, (1704., 336., 1728., 360.)),
        244: (5001, (1632., 336., 1656., 360.)),
        245: (5001, (1560., 336., 1584., 360.)),
        246: (5001, (1488., 336., 1512., 360.)),
    },
}


def _source(actor, now):
    from pve_local_mechanics import enabled
    arena = actor.arena
    key = (arena.geometry.id, actor.info.get('point'))
    spec = SOURCES.get(key)
    if (not spec or not enabled(arena) or arena.pk['finished']
            or not actor.alive or arena.actors.get(actor.id) is not actor
            or not actor.info.get('pve_npc') or not actor.info.get('pve_trap')
            or not actor.info.get('pve_stationary') or actor.info.get('pve_flying')
            or actor.camp != 0 or actor.info.get('npc_template') != spec[0]
            or tuple(actor.spawn) != spec[1] or actor.position_at(now) != spec[1]
            or actor.shot_skill != (1000134 if key[0] == 31601 else 1000055)):
        return None
    rec = next((r for r in arena.geometry.data.get('pve_spawns', ())
                if r['index'] == actor.info.get('pve_rule')), None)
    if (not rec or rec['map'] != key[0] or rec['point'] != key[1]
            or rec['camp'] != 0 or spec[0] not in rec['templates']
            or tuple(rec['position']) != spec[1]):
        return None
    return key, spec[1], DIRECTIONS[spec[0]]


def _housing(geometry, origin, direction):
    """Only the first contiguous STATIC wall on the exact authored bearing."""
    terrain = Counter(tuple(r) for r in geometry.data['movement_walls']) - geometry._walk_objects
    axis = 0 if direction[0] else 1
    other = 1 - axis
    sign = direction[axis]
    intervals = []
    for rect, count in terrain.items():
        if not rect[other] <= origin[other] <= rect[other + 2]:
            continue
        a = (rect[axis] - origin[axis]) * sign
        b = (rect[axis + 2] - origin[axis]) * sign
        low, high = min(a, b), max(a, b)
        if high > 0 and low <= RANGE:
            intervals.append((max(0, low), high, rect, count))
    intervals.sort()
    if not intervals or not 0 < intervals[0][0] <= 96:
        return Counter()
    begin, end = intervals[0][:2]
    allowed = Counter()
    for low, high, rect, count in intervals:
        if low > end:
            break
        end = max(end, high)
        allowed[rect] += count
    if end - begin > 480:
        return Counter()
    return allowed


def _blockers(actor, spec):
    geometry = actor.arena.geometry
    cache = getattr(geometry, '_pve_transport_cache', None)
    if cache is None or cache['walls'] is not geometry.movement_walls:
        terrain = Counter(tuple(r) for r in geometry.data['movement_walls']) - geometry._walk_objects
        cache = dict(walls=geometry.movement_walls, sources={},
                     objects=Counter(geometry.movement_walls) - terrain)
        geometry._pve_transport_cache = cache
    key, origin, direction = spec
    if key not in cache['sources']:
        # Counter subtraction retains a living object that happens to share
        # a terrain rectangle. A set/exclude shortcut would erase that gate.
        remaining = Counter(geometry.movement_walls) - _housing(geometry, origin, direction)
        cache['sources'][key] = tuple(remaining)
    return cache['sources'][key]


def _transit_objects(actor, spec):
    arena = actor.arena
    remaining = arena.geometry._pve_transport_cache['objects'].copy()
    for instance, (template, rect) in TRANSIT_DECOR.get(spec[0], {}).items():
        obj = arena.actors.get((3 << 26) | instance)
        row = next((r for r in arena.geometry.data['npcs'] if r['instance'] == instance), None)
        center = ((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)
        if (obj and obj.alive and obj.info.get('map_object')
                and obj.info.get('npc_template') == template and obj.map_rect == rect
                and obj.position == center and not getattr(obj, 'pve_gate', False)
                and not getattr(obj, 'pve_bomb_only', False)
                and row and row['template'] == template and (row['x'], row['y']) == center
                and not row.get('pve_gate') and not row.get('pve_scripts')):
            remaining.subtract((rect,))
    return tuple(rect for rect, count in remaining.items() if count > 0)


def _outside_corridor(position, origin, direction):
    dx, dy = position[0] - origin[0], position[1] - origin[1]
    along = dx * direction[0] + dy * direction[1]
    across = abs(dx * direction[1] - dy * direction[0])
    return along < 0 or along > RANGE + 36 or across > 36


def _latches(target):
    state = getattr(target, 'pve_transport_state', None)
    if state is None or state['generation'] != target.generation:
        state = dict(generation=target.generation, portal_safe_until=0, emitters={})
        target.pve_transport_state = state
    return state


def _release_latch(actor, target, spec, now):
    state = getattr(target, 'pve_transport_state', None)
    if not state or state['generation'] != target.generation:
        return
    entry = state['emitters'].get(actor.id)
    if not entry:
        return
    if entry['generation'] != actor.generation:
        state['emitters'].pop(actor.id, None)
        return
    motion = target.motion
    # A second trap's snap must never re-arm the first trap. Only an actual
    # ordinary walk begun after the hit can release this emitter's latch.
    if (motion and target.motion_kind == 0 and motion[2] > entry['hit_at']
            and motion[0] != motion[1]
            and _outside_corridor(target.position_at(now), spec[1], spec[2])):
        state['emitters'].pop(actor.id, None)


def tick_emitter(actor, now):
    spec = _source(actor, now)
    if spec is None:
        return []
    for target in actor.arena.actors.values():
        if target.alive and not target.info.get('npc_template'):
            _release_latch(actor, target, spec, now)
    interval = max(1, int(actor.stats['iFireInterv']))
    if not hasattr(actor, 'turret_next_shot_at'):
        actor.turret_next_shot_at = now + interval
        return []
    if now < actor.turret_next_shot_at:
        return []
    actor.turret_next_shot_at = now + interval
    if actor.blocked('attack', now) or actor.skill_sealed(0, now):
        return []
    origin, direction = spec[1:]
    dest = tuple(a + b * RANGE for a, b in zip(origin, direction))
    return actor._shot(dest, now)


def shot(actor, dest, now):
    spec = _source(actor, now)
    if spec is None or actor.blocked('attack', now) or actor.skill_sealed(0, now):
        return []
    origin, direction = spec[1:]
    end = tuple(a + b * RANGE for a, b in zip(origin, direction))
    if tuple(dest) != end:
        return []
    row = table_row('SkillTemplate_table.xml', nId=actor.shot_skill)
    speed = max(1, round(int(row['iFlyRange']) * 1000 / int(row['iLifeTime'])))
    duration = max(1, round(RANGE * 1000 / speed))
    ident = actor._new_id(2)
    flight = dict(pve_transport=True, kind='bullet', id=ident, start=origin, end=end,
                  begin=now, previous=now, finish=now + duration, speed=speed,
                  template=actor.shot_skill, source_generation=actor.generation,
                  target=None, generations={a.id: a.generation for a in actor.arena.actors.values()
                      if a.alive and not a.info.get('npc_template') and a.camp != actor.camp})
    actor._queue(now + min(20, duration), 'flight', flight)
    return [scene(fires=(struct.pack('<IIhhhhhI', ident, actor.id, *origin, *end,
                                    speed, actor.shot_skill),))]


def _landing(actor, target, spec, now):
    arena = actor.arena
    geometry = arena.geometry
    dest = LANDINGS.get(spec[0], spec[1])
    water = arena.water_rects(now)
    if (geometry.clamp_tank_position(dest) != dest or not geometry.in_playable_region(dest)
            or not geometry.can_walk_to(dest) or geometry.wall_contact(dest, dest, 35.999) is not None
            or rect_contact(dest, dest, water, 35.999) is not None):
        return None
    if any(a is not target and a is not actor and a.alive and not a.info.get('map_object')
           and not a.is_untargetable() and math.dist(a.position_at(now), dest) < 72
           for a in arena.actors.values()):
        return None
    # Landing must have a real 24px exit; a clear but sealed single cell is
    # insufficient. This also keeps the maze's small offset reviewable.
    for dx, dy in ((24, 0), (-24, 0), (0, 24), (0, -24)):
        step = (dest[0] + dx, dest[1] + dy)
        if (geometry.can_walk_to(step) and geometry.wall_contact(dest, step, 35.999) is None
                and rect_contact(dest, step, water, 35.999) is None):
            return dest
    return None


def _pull(actor, target, spec, now):
    from map_portals import eligible
    if not eligible(target, now) or target.cc_immune(now):
        return []
    state = _latches(target)
    if now < state['portal_safe_until'] or actor.id in state['emitters']:
        return []
    dest = _landing(actor, target, spec, now)
    origin = target.position_at(now)
    if (dest is None or dest == origin or _outside_corridor(origin, spec[1], spec[2])
            or rect_contact(origin, dest, _blockers(actor, spec)) is not None
            or rect_contact(origin, dest, _transit_objects(actor, spec), 35.999) is not None
            or rect_contact(origin, dest, actor.arena.water_rects(now), 35.999) is not None):
        return []
    target.position, target.motion, target.motion_kind = dest, None, 0
    state['portal_safe_until'] = now + GLOBAL_COOLDOWN
    state['emitters'][actor.id] = dict(generation=actor.generation, hit_at=now)
    brain = actor.arena.bot_brains.get(target.id)
    if brain is not None:
        brain.update(path=[], repath_at=0)
    return [stop_move(actor.scene_id, target.id, dest)]


def flight_step(actor, flight, now):
    ident = struct.pack('<I', flight['id'])
    spec = _source(actor, now)
    if (spec is None or actor.generation != flight['source_generation']
            or flight['template'] != actor.shot_skill or tuple(flight['start']) != spec[1]):
        return [scene(expired_bullets=(ident,))]
    duration = max(1, flight['finish'] - flight['begin'])
    start = point_at(flight['start'], flight['end'], (flight['previous'] - flight['begin']) / duration)
    end = point_at(flight['start'], flight['end'], min(1, (now - flight['begin']) / duration))
    wall = min((h for h in (rect_contact(start, end, _blockers(actor, spec)),
                rect_contact(start, end, actor.arena.water_rects(now))) if h is not None), default=None)
    contacts = []
    for target in actor.arena.actors.values():
        if (not target.alive or target.info.get('npc_template') or target.camp == actor.camp
                or flight['generations'].get(target.id) != target.generation or target.is_untargetable()
                or _outside_corridor(target.position_at(now), spec[1], spec[2])):
            continue
        hit = actor_contact(start, end, target, flight['previous'], now)
        if hit is not None and (wall is None or hit < wall):
            contacts.append((hit, target.id, target))
    if contacts:
        target = min(contacts, key=lambda row: row[:2])[2]
        if actor.projectile_blocked(target, now):
            return [scene(expired_bullets=(ident,))]
        packets = _pull(actor, target, spec, now)
        return packets + [scene(blown_bullets=(ident,))]
    if wall is not None or now >= flight['finish']:
        return [scene(expired_bullets=(ident,))]
    flight['previous'] = now
    actor._queue(min(now + 20, flight['finish']), 'flight', flight)
    return []
