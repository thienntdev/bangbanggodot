"""Coarse PRO movement around an already published, visible warning.

This is a sensor/planner, not a combat or collision implementation. Its only
authored template is Chu Du's stationary S1556 warning388311. Other objects
can be hidden traps or invisible logic markers even when arena.objects holds
them. No caster, enemy intent, cooldown, queue or exact detonation is read.
"""
from __future__ import annotations

import math
import struct


MIN_AGE = 180
MAX_AGE = 1000
SENSOR_RADIUS = 600
OBJECT = struct.Struct('<IIhhiBiIiH')
# chudu_actions.chu_warning materializes388311; chu_space damages centers
# within120px. The additional24px below is a conservative tactical margin,
# not a change to native collision, hurt radius, speed or warning lifetime.
PUBLIC_WARNINGS = {388311: 120}
DIRECTIONS = ((-1,-1), (0,-1), (1,-1), (1,0),
              (1,1), (0,1), (-1,1), (-1,0))


def _enabled(arena, actor, brain):
    from bot_policy import ELITE, policy_for
    return (actor.alive and brain.get('generation') == actor.generation
            and not actor.info.get('npc_template')
            and policy_for(arena, actor) == ELITE)


def _parse(ident, body):
    """A body excludes the packet's sceneId; HP0 is normal for scene items."""
    try:
        raw = bytes.fromhex(body)
        if len(raw) < OBJECT.size:
            return None
        key, template, x, y, hp, camp, level, owner, maximum, count = OBJECT.unpack_from(raw)
        if (key != ident or key >> 26 != 4 or template not in PUBLIC_WARNINGS
                or camp not in (1, 2) or len(raw) != OBJECT.size + 13 * count):
            return None
        return dict(id=key, template=template, pos=(x, y), camp=camp, body=body)
    except (TypeError, ValueError, struct.error):
        return None


def observe(arena, actor, brain, now):
    """Called only at the ordinary end-of-notice observation point.

    A repeated stationary body reuses the ENTIRE first sample, not its old
    timestamp with a fresh position. First sight is not spawn time and MAX_AGE
    is only a bounded memory duration; neither predicts time left to explode.
    A removal does not immediately erase a previous sample. The planner never
    peeks at the current object map to obtain perfect removal timing.
    """
    objects = getattr(arena, 'objects', {})
    old = brain.get('elite_hazards', ())
    if not objects and not old:
        return
    if not _enabled(arena, actor, brain):
        return
    previous = {sample['id']: sample for sample in old
                if sample.get('generation') == actor.generation}
    rows = []
    found = set()
    pos = actor.position_at(now)
    for ident, body in objects.items():
        sample = _parse(ident, body)
        if (sample is None or sample['camp'] == actor.camp
                or math.dist(pos, sample['pos']) > SENSOR_RADIUS
                or arena.geometry.wall_contact(pos, sample['pos']) is not None):
            continue
        # Client SceneItemRenderer uses cover/camp and viewport, not caster
        # stealth or wall LOS. Local600px+LOS are deliberately stricter policy
        # limits, not a claim that they reproduce the native viewport.
        prior = previous.get(ident)
        if prior is not None and prior.get('body') == body:
            sample = prior
        else:
            sample.update(generation=actor.generation, observed_at=now)
        rows.append(sample)
        found.add(ident)
    for ident, sample in previous.items():
        if ident not in found and 0 <= now-sample.get('observed_at', now) <= MAX_AGE:
            rows.append(sample)
    if rows:
        brain['elite_hazards'] = rows
    else:
        brain.pop('elite_hazards', None)


def mature(brain, actor, now):
    return [sample for sample in brain.get('elite_hazards', ())
            if (sample.get('generation') == actor.generation
                and sample.get('template') in PUBLIC_WARNINGS
                and sample.get('camp') in (1, 2) and sample['camp'] != actor.camp
                and MIN_AGE <= now-sample.get('observed_at', now) <= MAX_AGE)]


def _segment_distance(start, end, point):
    dx, dy = end[0]-start[0], end[1]-start[1]
    length2 = dx*dx+dy*dy
    fraction = (max(0.0, min(1.0, ((point[0]-start[0])*dx+(point[1]-start[1])*dy)/length2))
                if length2 else 0.0)
    return math.dist((start[0]+dx*fraction, start[1]+dy*fraction), point)


def _risk(point, hazards):
    return sum(max(0.0, PUBLIC_WARNINGS[h['template']]+24-math.dist(point,h['pos']))
               for h in hazards)


def _crosses(start, end, hazards):
    return any(_segment_distance(start, end, h['pos']) < PUBLIC_WARNINGS[h['template']]+24
               for h in hazards)


def evade(arena, actor, brain, now):
    """Override only an ordinary walk goal using previous mature samples.

    The discrete destinations are requested through the existing native
    navigator/walker. They are neither teleports nor a guarantee of dodging.
    No RNG is consumed; no current enemy or warning-removal state is read.
    """
    if not brain.get('elite_hazards'):
        return False
    if not _enabled(arena, actor, brain):
        return False
    motion = getattr(actor, 'motion', None)
    if (actor.blocked('move', now) or getattr(actor, 'channel', None)
            or getattr(actor, 'ready', None) or brain.get('elite_native_goal')
            or brain.get('repair_goal') or brain.get('repair_box')
            or (motion and motion[3] > now and getattr(actor, 'motion_kind', 0) != 0)
            or arena.pk.get('finished') or arena.pk.get('round_phase', 'playing') != 'playing'
            or now < arena.pk.get('intro_until', 0)):
        return False
    hazards = mature(brain, actor, now)
    if not hazards:
        brain.pop('elite_hazard_goal', None)
        return False
    pos = actor.position_at(now)
    if actor._speed(now) <= 0:
        return False
    goal = brain.get('goal') or pos
    distance = math.dist(pos, goal)
    lookahead = (tuple(pos[i]+(goal[i]-pos[i])*min(1.0,240/distance) for i in range(2))
                 if distance else pos)
    stay_risk = _risk(pos, hazards)
    if not stay_risk and not _crosses(pos, lookahead, hazards):
        brain.pop('elite_hazard_goal', None)
        return False
    water = arena.water_rects(now)
    friends = [ally.position_at(now) for ally in arena.actors.values()
               if ally is not actor and ally.camp == actor.camp and ally.alive
               and not any(ally.info.get(k) for k in
                           ('map_object','cow_object','bomb_cart','totem'))]
    safe_center = None
    if arena.geometry.id in (30, 40) and arena.pk.get('collapse_warned'):
        from death_mode import RADIUS, center
        safe_center, safe_radius = center(arena), RADIUS
    hold_center = brain.get('elite_hold_center')
    hold_radius = brain.get('elite_hold_radius', 0)

    def legal(point):
        if arena.geometry.walk_end(pos, point, water) != point:
            return False
        # Match ordinary walking's64px ally clearance, including friendly
        # summons. If already crowded, allow only non-worsening separation.
        if any(_segment_distance(pos, point, p)+.01 < min(64,math.dist(pos,p))
               for p in friends):
            return False
        if safe_center is not None:
            old, new = math.dist(pos, safe_center), math.dist(point, safe_center)
            if new > safe_radius and (old <= safe_radius or new >= old):
                return False
        if brain.get('elite_final_push') and hold_center is not None and hold_radius:
            old, new = math.dist(pos, hold_center), math.dist(point, hold_center)
            if new > hold_radius and (old <= hold_radius or new >= old):
                return False
        # Once outside all observed warning circles, do not cross one to get
        # to another safe endpoint. If initially inside, an exit is necessary.
        if not stay_risk and _crosses(pos, point, hazards):
            return False
        return True

    previous = brain.get('elite_hazard_goal')
    candidates = []
    # Keep a still-valid escape rather than reversing sides each reaction.
    if (previous is not None and legal(tuple(previous))
            and _risk(previous, hazards) <= max(0,stay_risk-24)):
        chosen = tuple(previous)
    else:
        points = [pos] if not stay_risk else []
        for radius in (96, 168, 240):
            for dx, dy in DIRECTIONS:
                length = math.hypot(dx, dy)
                points.append((round(pos[0]+dx*radius/length),
                               round(pos[1]+dy*radius/length)))
        for point in points:
            risk = _risk(point, hazards)
            if not legal(point) or (stay_risk and risk > max(0,stay_risk-24)):
                continue
            penalty = math.dist(point, goal)*.025
            if hold_center is not None and hold_radius:
                penalty += max(0,math.dist(point,hold_center)-hold_radius)*.35
            # Leaving every sampled circle is the first priority. Within that
            # group, prefer short walks and the current objective direction.
            candidates.append((risk, math.dist(pos,point)*.05+penalty, point))
        if not candidates:
            return False
        chosen = min(candidates)[2]
    if tuple(brain.get('goal') or pos) != chosen:
        brain['repath_at'] = 0
    brain['goal'] = chosen
    brain['elite_hazard_goal'] = chosen
    return True
