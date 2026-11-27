"""PRO navigation with native-step recovery for off-grid waypoint clipping.

The fixed4500-node search preserves the native path algorithm, ordering and
collision authority. Blocker thresholds are reused per expanded node and a
conservative rectangle rejects distant edges without repeated distance work.
An ordinary route is unchanged when its first real step is geometrically
legal, or when its reachable approach has already been reached. Only a
remaining waypoint with no legal improving step invokes a bounded search
on the actor's actual24px lattice instead of an assumed snapped grid cell.
No cache survives a path call; legacy Navigation.path remains unchanged.
"""
import heapq
import math


# The earlier invalid-start recovery remains separate from waypoint clipping.
# _grid_path retains the canonical search; the native executor owns all motion.
def _native_escape(nav, start, goal, threats, blockers):
    """Leave an invalid off-grid start with one legal native24px walk.

    A knockback or an object appearing around a tank may leave its current
    point unsuitable as an A* source. Navigation.nearest requires the start
    itself to be clear, whereas native walk_end validates the destination
    of an ordinary step. Probe those same eight real steps; do not snap to a
    grid cell, relax body geometry, teleport, or inspect any enemy actor.
    The native walk executor still validates water, allies, motion and CC.
    """
    from battle_runtime import DIRECTIONS
    options = []
    for index, (dx, dy) in enumerate(DIRECTIONS[:8]):
        point = (start[0] + dx*24, start[1] + dy*24)
        if nav.geometry.walk_end(start, point) != point or nav.nearest(point) is None:
            continue
        if any(math.dist(point, b) < min(64, math.dist(start, b)) for b in blockers):
            continue
        danger = sum(max(0, 1-math.dist(point, p)/360) for p in threats)
        options.append((math.dist(point, goal)+danger*48, index, point))
    if not options:
        return []
    point = min(options)[2]
    # Preserve the actual off-grid endpoint as the first waypoint. Merely
    # returning the subsequent grid route could make walk() choose a different
    # first direction that is not one of the proven legal escape steps.
    onward = path(nav, point, goal, threats, blockers)
    return [tuple(start), point] + onward


def _walk_step(nav, start, route):
    """Predict only the geometry choice made by the unchanged native walker.

    Choosing the closest *grid* edge is not sufficient after a dash/knockback:
    walk() always adds a full24px direction to the actor's actual position.
    Its arrival and corner predicates are mirrored here, not relaxed.
    """
    from battle_runtime import DIRECTIONS
    remaining = [tuple(p) for p in route]
    while remaining and math.dist(start, remaining[0]) < 18:
        remaining.pop(0)
    if not remaining:
        return None
    for index, waypoint in enumerate(remaining[:2]):
        if index and math.dist(start, remaining[0]) >= 24:
            break
        distance = math.dist(start, waypoint)
        choices = sorted((math.dist((start[0]+24*dx, start[1]+24*dy), waypoint), i,
                          (start[0]+24*dx, start[1]+24*dy))
                         for i, (dx, dy) in enumerate(DIRECTIONS[:8]))
        for score, _, point in choices:
            if score < distance and nav.geometry.walk_end(start, point) == point:
                return point
    return None


def _ally_blocked(start, point, blockers):
    """Native friendly-spacing predicate, using communicated allies only."""
    return any(math.dist(point, b) < 64 and math.dist(point, b) < math.dist(start, b)-1
               for b in blockers)


def _native_route(nav, start, goal, threats, blockers):
    """Search real steps when canonical-cell guidance cannot be executed.

    The starting offset is preserved throughout: every edge is exactly one
    ordinary24px step checked by native geometry. Initial progress may be
    away from the objective to round an obstructed corner. Ally spacing remains
    a constraint, not a recovery trigger. No position is assigned or snapped.
    """
    from battle_runtime import DIRECTIONS
    start = tuple(start)
    end = tuple(p+24*round((g-p)/24) for p, g in zip(start, goal))

    def estimate(p):
        dx, dy = abs(p[0]-end[0]), abs(p[1]-end[1])
        return max(dx, dy)+(math.sqrt(2)-1)*min(dx, dy)

    queue = [(estimate(start), 0, start)]
    cost = {start: 0}
    parent = {}
    best = start
    for _ in range(4500):
        if not queue:
            break
        _, g, p = heapq.heappop(queue)
        if g != cost[p]:
            continue
        if math.dist(p, goal) < math.dist(best, goal):
            best = p
        if math.dist(p, goal) < 18:
            best = p
            break
        for dx, dy in DIRECTIONS[:8]:
            q = p[0]+24*dx, p[1]+24*dy
            if nav.geometry.walk_end(p, q) != q or _ally_blocked(p, q, blockers):
                continue
            danger = sum(max(0, 1-math.dist(q, threat)/360) for threat in threats)
            ng = g+math.hypot(dx, dy)*24+danger*48
            if ng < cost.get(q, float('inf')):
                cost[q] = ng
                parent[q] = p
                heapq.heappush(queue, (ng+estimate(q), ng, q))
    if best == start:
        return []
    result = [best]
    while result[-1] != start:
        result.append(parent[result[-1]])
    return list(reversed(result))


def path(nav, start, goal, threats=(), blockers=()):
    route = _grid_path(nav, start, goal, threats, blockers)
    if math.dist(start, goal) < 20:
        return route
    point = _walk_step(nav, start, route)
    # Geometry-only recovery: a legal first step obstructed by an ally stays
    # with the existing cooperative-spacing controller. A permanent detour
    # around a transient friendly body can otherwise split a fighting group.
    if point is not None or not any(math.dist(start, p) >= 18 for p in route):
        return route
    # An empty route or arrival at the closest reachable approach is not a
    # clipped walking step. Preserve those cases for the existing obstacle/
    # siege policy rather than exploring toward an unreachable building centre.
    # A grid-projected goal may be solid (a siege target) or unreachable. Use
    # the existing planner's reachable approach, not the building centre.
    destination = route[-1] if route and math.dist(start, route[-1]) >= 18 else goal
    return _native_route(nav, start, destination, threats, blockers) or route


def _grid_path(nav, start, goal, threats=(), blockers=()):
    source = nav.nearest(start)
    end = nav.nearest(goal)
    if source is None:
        return _native_escape(nav, start, goal, threats, blockers)
    if end is None:
        center = tuple(round((v-12)/24)*24+12 for v in goal)
        cells = [(center[0]+24*x, center[1]+24*y)
                 for x in range(-6, 7) for y in range(-6, 7)]
        reachable = nav.reachable(source)
        cells = [p for p in cells if p in reachable]
        if not cells:
            if nav.geometry.id not in (12, 14, 50, 169):
                return []
            cells = reachable
        end = min(cells, key=lambda p: math.dist(goal, p))
    if blockers and any(math.dist(end, b) < 64 for b in blockers):
        cells = [(end[0]+24*x, end[1]+24*y)
                 for x in range(-6, 7) for y in range(-6, 7)]
        reachable = nav.reachable(source)
        cells = [p for p in cells if p in reachable
                 and all(math.dist(p, b) >= 64 for b in blockers)]
        if not cells:
            return []
        end = min(cells, key=lambda p: math.dist(goal, p))

    def estimate(p):
        dx, dy = abs(p[0]-end[0]), abs(p[1]-end[1])
        return max(dx, dy)+(math.sqrt(2)-1)*min(dx, dy)

    queue = [(estimate(source), 0, source)]
    cost = {source: 0}
    parent = {}
    best = source
    # Preserve the original strict rectangle on its three existing fast maps.
    # A new general rectangle must be inclusive: floating subtraction at an
    # exact64px boundary can make math.dist slightly below64. The native
    # distance predicate remains the final authority on boundary candidates.
    original_bounds = nav.geometry.id in (14, 19, 70)
    bounds = ((min(p[0] for p in blockers)-64, min(p[1] for p in blockers)-64,
               max(p[0] for p in blockers)+64, max(p[1] for p in blockers)+64)
              if blockers else None)
    if bounds is not None and not original_bounds:
        # Conservative outward rounding can only add exact distance checks,
        # never incorrectly remove an edge close to a floating boundary.
        bounds = (math.nextafter(bounds[0], -math.inf), math.nextafter(bounds[1], -math.inf),
                  math.nextafter(bounds[2], math.inf), math.nextafter(bounds[3], math.inf))
    for _ in range(4500):
        if not queue:
            break
        _, g, p = heapq.heappop(queue)
        if g != cost[p]:
            continue
        if math.dist(p, end) < math.dist(best, end):
            best = p
        if p == end:
            break
        edges = (nav.neighbors(p) if nav.geometry.id in (14, 19, 70)
                 else nav._neighbors(p))
        # These values depend on p and each ally, never the candidate edge q.
        # Computing once retains the same strict float comparisons and order.
        blocker_limits = tuple((b, min(64, math.dist(p, b))) for b in blockers)
        for q, step_cost in edges:
            if (bounds is not None
                    and ((bounds[0] < q[0] < bounds[2] and bounds[1] < q[1] < bounds[3])
                         if original_bounds else
                         (bounds[0] <= q[0] <= bounds[2] and bounds[1] <= q[1] <= bounds[3]))
                    and any(math.dist(q, b) < limit for b, limit in blocker_limits)):
                continue
            danger = sum(max(0, 1-math.dist(q, p)/360) for p in threats) if threats else 0
            ng = g+step_cost+danger*48
            if ng < cost.get(q, float('inf')):
                cost[q] = ng
                parent[q] = p
                heapq.heappush(queue, (ng+estimate(q), ng, q))
    route = []
    p = best
    while p != source:
        route.append(p)
        p = parent[p]
    if nav.geometry.id == 19:
        route = [(p[0], p[1]) for p in route]
    route.append(source)
    return list(reversed(route))
