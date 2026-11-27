"""Versioned local chapter-nine encounters, using native movement and actors.

The two original server scripts are unavailable. Long Cot keeps its native
speed, scatter weapon, three-shot burst, lifesteal and stats; its new policy
changes distance/angle and leads a visibly moving target. The immobile Eye
keeps death-ray1000150/R300/damage and gets deliberate HP phases, sequential
telegraphs and bounded waves of the map's own NPCs. These are local rules,
not recovered Flash script behavior. Old frozen profiles keep the M42 AI.

All state is ordinary checkpoint data; absolute times use the existing
checkpoint names. A saved ready cast never restarts its two-second warning.
"""
import math
import struct

from combat_geometry import rect_contact
from combat_math import D
from combat_protocol import scene, skill_event
from pve_balance import frozen_profile

MAZE, EYE = 3160111, 3160211
MAPS = {31601: MAZE, 31602: EYE}
SOURCE_SHA256 = {
    31601: '2828c13b9b2b445b3f886fbec6909b8e32ed72ec4653207ef32c44fe8a70d0d7',
    31602: '3361dcb7a29619360007a85d3c6ca71ddb5fc281bf7f439ca43c39fc6f7880ec',
}
SKILL, RADIUS, RANGE, WARNING_MS = 1000150, 300, 800, 2000
GAP_MS = 450
RECOVERY_MS = {1: 2500, 2: 2300, 3: 1800}
GUARD_WAVES = {1: (3160201, 3160210), 2: (3160210, 3160202), 3: (3160201, 3160202)}
GUARD_CAP, GUARD_GRACE_MS = 3, 1200


def enabled(actor):
    arena = actor.arena
    profile = frozen_profile(arena) or {}
    version = profile.get('pve_tactics_version')
    return (type(version) is int and version == 1
            and actor.info.get('pve_npc') and actor.camp != arena.player.camp
            and MAPS.get(arena.geometry.id) == actor.info.get('npc_template')
            and profile.get('map_id') == arena.geometry.id
            and arena.geometry.data.get('source', {}).get('sha256') == SOURCE_SHA256.get(arena.geometry.id))


def _state(actor, now):
    state = getattr(actor, 'pve_boss_tactics', None)
    if state is None or state.get('generation') != actor.generation:
        state = actor.pve_boss_tactics = dict(version=1, generation=actor.generation,
            phase=1, remaining=0, wave_cursors={1: 0, 2: 0, 3: 0},
            next_tick_at=now+1200, phase_end=now, phase_gap=now,
            wave_due_at=now, observed_at=now, last_target_pos=None)
    # Healing/lifesteal never repeatedly earns a phase or another summon wave.
    phase = 3 if actor.hp <= actor.max_hp*D('.35') else 2 if actor.hp <= actor.max_hp*D('.70') else 1
    state['phase'] = max(state['phase'], phase)
    return state


def _eligible(actor, target, now, radius):
    if (target is None or not target.alive or target.camp == actor.camp
            or target.info.get('map_object') or target.info.get('pve_hostage')
            or target.in_stasis() or not target.is_area_targetable()):
        return False
    from bot_ai import observable
    return (observable(actor.arena, actor, target, now, radius)
            and rect_contact(actor.position_at(now), target.position_at(now), actor.arena.water_rects(now)) is None)


def _target(actor, now, radius):
    pos = actor.position_at(now)
    return min((a for a in actor.arena.actors.values() if _eligible(actor, a, now, radius)),
        key=lambda a: (bool(a.info.get('npc_template')), math.dist(pos, a.position_at(now)), a.id),
        default=None)


def _aim(actor, target, now, predictive):
    """Bounded lead from an observed current walk, never an unseen future path."""
    pos = target.position_at(now)
    motion = target.motion
    if not predictive or not motion or motion[3] <= now or motion[3] <= motion[2]:
        return pos
    start, end, began, finish = motion
    dx, dy = (end[0]-start[0])*550/(finish-began), (end[1]-start[1])*550/(finish-began)
    distance = math.hypot(dx, dy)
    if distance > 96:
        dx, dy = dx*96/distance, dy*96/distance
    wish = actor.arena.geometry.clamp_tank_position((round(pos[0]+dx), round(pos[1]+dy)))
    # Predict only the immediately visible walk corridor. No lead through a
    # wall/water corner and no snap to a different chamber on the A* grid.
    return actor.arena.geometry.walk_end(pos, wish, actor.arena.water_rects(now))


def _guards(actor):
    return [a for a in actor.arena.actors.values() if a.alive
            and a.info.get('pve_boss_add') == actor.id
            and a.info.get('pve_boss_generation') == actor.generation]


def _guard_position(actor, now, cursor):
    arena, center = actor.arena, actor.position_at(now)
    water = arena.water_rects(now)
    others = [a.position_at(now) for a in arena.actors.values()
              if a.alive and not a.info.get('map_object')]
    # Native24px centres, enough body clearance and a real first step out.
    from battle_runtime import DIRECTIONS
    from bot_ai import Navigation
    if not hasattr(arena, 'navigation'):
        arena.navigation = Navigation(arena.geometry)
    offsets = ((-144, 120), (144, 120), (0, 216), (-216, 0), (216, 0),
               (-144, -120), (144, -120), (0, -216), (-240, 144), (240, 144))
    for index in range(len(offsets)):
        dx, dy = offsets[(cursor+index) % len(offsets)]
        point = arena.navigation.nearest((center[0]+dx, center[1]+dy))
        if point is None or math.dist(center, point) > 300:
            continue
        if (not arena.geometry.can_walk_to(point)
                or arena.geometry.wall_contact(point, point, 35.999) is not None
                or rect_contact(point, point, water, 35.999) is not None
                or arena.geometry.wall_contact(center, point) is not None
                or rect_contact(center, point, water) is not None
                or any(math.dist(point, other) < 96 for other in others)
                or any(math.dist(point, a.position_at(now)) < 180 for a in arena.actors.values()
                       if a.alive and a.camp != actor.camp and not a.info.get('map_object'))):
            continue
        if any(arena.geometry.walk_end(point, (point[0]+24*x, point[1]+24*y), water)
               == (point[0]+24*x, point[1]+24*y) for x, y in DIRECTIONS[:8]):
            return point
    return None


def _summon(actor, state, now):
    if now < state['wave_due_at'] or len(_guards(actor)) >= GUARD_CAP:
        return []
    state['wave_due_at'] = now+1500
    phase = next((p for p in range(1, state['phase']+1) if state['wave_cursors'][p] < 2), None)
    if phase is None:
        return []
    cursor = state['wave_cursors'][phase]
    point = _guard_position(actor, now, phase*2+cursor)
    if point is None:
        return []
    from pve_npc import PveNpc
    info = dict(point=actor.info['point'], npc_template=GUARD_WAVES[phase][cursor],
        pve_rule=actor.info['pve_rule'], pve_loop=False, pve_remaining=0,
        pve_logic=actor.info.get('pve_logic', 1), pve_unscored=True,
        pve_boss_add=actor.id, pve_boss_generation=actor.generation)
    guard = PveNpc(actor.arena, actor.arena.new_id(5), info, actor.camp, point)
    guard.cooldowns[0] = now+GUARD_GRACE_MS
    actor.arena.actors[guard.id] = guard
    state['wave_cursors'][phase] += 1
    return [guard.snapshot(now)]


def cleanup(actor, now):
    """Despawn owned guards on the real boss death, without rewards/deaths."""
    removed = []
    for guard in _guards(actor):
        guard.hp = D(0)
        guard.info.update(in_room=False, hp=0)
        guard.position, guard.motion = guard.position_at(now), None
        removed.append(struct.pack('<I', guard.id))
    return [scene(removed=tuple(removed))] if removed else []


def eye_shot(actor, dest, now, target=None):
    """Start exactly one warned ray; native shot dispatcher calls this too."""
    if not enabled(actor) or actor.info.get('npc_template') != EYE:
        return None
    state = _state(actor, now)
    if (actor.arena.pk['finished'] or not actor.alive or actor.blocked('attack', now)
            or actor.skill_sealed(0, now) or now < state['next_tick_at']
            or getattr(actor, 'pve_boss_cast', None) is not None
            or not _eligible(actor, target, now, RANGE)):
        return []
    if state['remaining'] <= 0:
        state['remaining'] = state['phase']
        state['cycle_phase'] = state['phase']
    start = actor.position_at(now)
    dest = _aim(actor, target, now, state['phase'] >= 2)
    cast = dict(start=start, dest=dest, target=target.id, target_generation=target.generation,
        generation=actor.generation, finish=now+WARNING_MS,
        raw=D(1000)+actor.combat_stat('iEgAtk', now), tactics_version=1)
    actor.pve_boss_cast = cast
    actor.cooldowns[0] = cast['finish']+GAP_MS
    actor._queue(cast['finish'], 'pve_boss_ray', cast)
    return [scene(skills=(skill_event(SKILL, start, dest, target.id, owner=actor.id, ready=1),))]


def _valid_cast(actor, cast, now):
    target = actor.arena.actors.get(cast['target'])
    return (enabled(actor) and actor.alive and not actor.arena.pk['finished']
            and actor.generation == cast['generation'] and not actor.blocked('attack', now)
            and not actor.skill_sealed(0, now) and math.dist(actor.position_at(now), cast['start']) <= 1
            and target is not None and target.generation == cast['target_generation']
            and _eligible(actor, target, now, RANGE))


def interrupted(actor, now):
    state = getattr(actor, 'pve_boss_tactics', None)
    if state is not None:
        state['remaining'] = 0
        state['next_tick_at'] = now+RECOVERY_MS[state['phase']]
        actor.cooldowns[0] = max(actor.cooldowns.get(0, 0), state['next_tick_at'])


def eye_release(actor, cast, now):
    if not _valid_cast(actor, cast, now):
        from pve_bosses import interrupt
        return interrupt(actor, now)
    actor.pve_boss_cast = None
    state = _state(actor, now)
    state['remaining'] = max(0, state['remaining']-1)
    state['next_tick_at'] = now+(GAP_MS if state['remaining'] else RECOVERY_MS[state['cycle_phase']])
    actor.cooldowns[0] = state['next_tick_at']
    packets = [scene(skills=(skill_event(SKILL, cast['start'], cast['dest'], cast['target'],
        owner=actor.id, ready=0),))]
    from pve_shots import targets
    for victim in targets(actor, cast['dest'], RADIUS, now):
        packets += actor.damage(cast['raw'], now, target=victim, school='energy',
                                source_generation=cast['generation'])[0]
        if actor.arena.pk['finished'] or not actor.alive:
            break
    return packets


def _eye_tick(actor, brain, state, now):
    cast = getattr(actor, 'pve_boss_cast', None)
    target = _target(actor, now, RANGE)
    if actor.blocked('attack', now) or actor.skill_sealed(0, now) or target is None:
        if cast is not None:
            from pve_bosses import interrupt
            return interrupt(actor, now)
        if state['remaining']:
            interrupted(actor, now)
        return []
    if cast is not None and not _valid_cast(actor, cast, now):
        from pve_bosses import interrupt
        return interrupt(actor, now)
    packets = _summon(actor, state, now)
    if cast is None and now >= state['next_tick_at']:
        packets += eye_shot(actor, target.position_at(now), now, target)
    return packets


def _maze_tick(actor, brain, state, now):
    from pve_movement import move, patrol_goal
    if now >= brain['notice_at']:
        brain['notice_at'] = now+200
        brain['pve_patrolling'] = False
        target = _target(actor, now, 600)
        pos = actor.position_at(now)
        if target is not None:
            dest = target.position_at(now)
            state['last_target_pos'], state['observed_at'] = dest, now
            ready = not actor.motion or actor.motion[3] <= now
            if ready and now >= state['phase_gap']:
                from pve_tactics import choose_goal
                goal = choose_goal(actor, dest, now, fire_range=600,
                    preferred_range=(384, 312, 240)[state['phase']-1], strafe=True)
                if brain.get('goal') != goal:
                    brain['path'], brain['repath_at'] = [], 0
                brain['goal'], state['phase_gap'] = goal, now+900
            if math.dist(pos, dest) <= actor.pve_fire_range:
                aim = _aim(actor, target, now, state['phase'] >= 2)
                packets = actor.cast(0, pos, aim, target.id, now)
            else:
                packets = []
        else:
            packets = []
            if state['last_target_pos'] is not None and now-state['observed_at'] <= 1600:
                brain['goal'] = state['last_target_pos']
            else:
                brain['goal'] = patrol_goal(actor.arena, actor, now)
        if actor.arena.pk['finished']:
            return packets
    else:
        packets = []
    return packets+move(actor.arena, actor, brain, now)


def tick(actor, brain, now):
    """None means legacy/not owned; a list owns this actor's AI for the tick."""
    if not enabled(actor):
        return None
    if actor.arena.pk['finished'] or not actor.alive:
        return []
    state = _state(actor, now)
    return (_eye_tick(actor, brain, state, now) if actor.info['npc_template'] == EYE
            else _maze_tick(actor, brain, state, now))
