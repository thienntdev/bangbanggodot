"""Opt-in decisions for the remaining native chapter-two to eight bosses.

These are local tactics, not recovered Flash scripts. Each exact encounter
keeps its source stats, weapon, burst, cooldown, passives and chapter events.
Hunters intercept a visible walk, ranged bosses change angle/distance, native
air bosses orbit without becoming ground tanks, and fixed forts choose useful
firing lanes. HP phases only change these decisions; they grant no extra shot,
damage, movement speed, summons or unannounced special attack. Chapter one's
bosses and the existing Dooku/Long Cot/Eye controllers are deliberately absent.

Perception is bounded to 200ms and planning to native step boundaries/600ms.
Memory stores a last seen point for 1600ms, never an invisible actor's position.
All state is checkpoint data; absolute clocks use existing persistence names.
"""
import math

from combat_math import D
from pve_balance import frozen_profile

PERCEPTION_MS, PLAN_MS, MEMORY_MS, ORBIT_MS = 200, 600, 1600, 4000
NOTICE_RANGE = 600

# Map + template, not template alone: e.g. helicopter1331 is an ordinary
# reinforcement on306. Likewise the two later Hunter aliases are ordinary mobs.
BINDINGS = {
    (211, 614): 'heavy', (212, 625): 'skirmisher', (213, 633): 'air',
    (401, 413): 'air', (403, 422): 'skirmisher',
    (405, 1437): 'skirmisher', (406, 1430): 'heavy',
    (302, 346): 'siege', (303, 347): 'siege', (303, 359): 'siege',
    (304, 1331): 'air', (306, 1332): 'heavy',
    (702, 2641): 'heavy', (703, 2610): 'air',
    (503, 515): 'hunter', (506, 566): 'skirmisher',
    (602, 710): 'heavy', (603, 715): 'skirmisher',
    (30101, 3110108): 'skirmisher', (30102, 3110211): 'skirmisher',
    (31201, 3120106): 'hunter', (31202, 3120209): 'skirmisher',
    (31203, 3120309): 'skirmisher', (31302, 3130209): 'skirmisher',
    (31303, 3130313): 'skirmisher', (31401, 3140111): 'hunter',
    (31402, 3140209): 'skirmisher', (31403, 3140314): 'skirmisher',
    (31501, 3150109): 'skirmisher', (31502, 3150208): 'skirmisher',
    (31503, 3150314): 'skirmisher',
}
SOURCE_SHA256 = {
    211: '29cd00d2e500300c858b3814206a34f514a835d6dc536f9df284c6cc782ce772',
    212: '3a931857336ecae7e0486df5133f8ef1cca7382f5366b377eba3b9ebe4d2ac15',
    213: '126998ff568dd9bc8af57e276f562d2be002bd36e0adedd1ba2970752200ebbd',
    302: 'af152ddc6f77e8837012cb4a0f90acdc968c2c6508b65e0cebd7ce65f40ffada',
    303: 'bc329b9cdc7bb155f389146b9cb38e05f1f605b7553395b0e46dba41acb16093',
    304: '1256fb0a52ae33575ce669891090e257de620f7037cc6ce2799363e8e1b3370c',
    306: '20dbdaf01048ed8b13c3f38fa11e766ec52674038d67492a59f2320a447f57e4',
    401: 'de6730b5f2ddc3fa8b6e56fd1cb0f102dbcaed0d6a90db9f3b7b658ade31a119',
    403: 'e47d3e8acffd5f6059c26d4f799dbfd851e56466b845eaa856bb37a86b2c6a68',
    405: 'c9d355360a909880eaba7c9a561b1eed33ba3db7a7fb76b596c21091ee8ed1d9',
    406: 'c15e8b02de72afe300a2f1e92bfc8571f48ae2b22a4869291b1836782e14a4f0',
    503: '77594140837da09ca9e6e9967a86f26485c25ca6f7ef963e70c1850045d1c5fe',
    506: 'cd5762b325096ad5735f4a3a263b231d1fca7ecc94b5e3fb341916fbee93d0ad',
    602: '43f0025fe3774507108bc3649780d86a199b22a6210bcc476dcf6d62072e03f2',
    603: '184f690f3dc68e7f595adf6a82ae948154d8f1391b74986a196473c3ace67d3f',
    702: '2a8a01303af3586674c8f41fdb0844569ebc59f5be01eab8259ce7704464ffc0',
    703: '56cd5383937d4006ce2babcaf5ee64266932d43465a433ccf8a0b0f421744366',
    30101: 'c9ccdf09c27259729bbf68e40a977f6e3d4130c93123666cbfa7167100b8385e',
    30102: 'df5f5fe3bc4d9961d61e0ad0e82777574e1119ecc846b859a3bf9ae29c6d9466',
    31201: '70a2bda77b57aff038429a66b0a7aebc1e0192d6160c1e53613dfa500e4ecfc2',
    31202: '7484fd5b48227166ede79f372c5957c9c19382892cb6bc07c3271bec98b711d5',
    31203: '972a549eba075400e70ccb8d9b40dd3fce395a2afd0fc07c52fd1fa284e69fee',
    31302: '963e098e46c2f911dc52311fd41d70b6634c170ef66e2506837cd9b981425dba',
    31303: '122fd2a058a2734d4f901bf797e7e887492606a3ae4af572d9c92e24415e4412',
    31401: '53b8df05d5741ac37de6dbba9cf2085032dfb264f3d6ab2d0e04d2244e2536cc',
    31402: '1712595558f68d367ea3576c7e2a61e2f9ef2ec8ef6bf3f1265f933a84dcc13f',
    31403: 'a68071b4d629b15155aea717bbc7eb0120bf015b08808f9c0f743cd23c9cd441',
    31501: '7d462a521ed9fa3ff79c452982b6e9f1f4462fe9b255c4f0a9c262e038227d0f',
    31502: 'a7fcae916b6d85d38c0353e9dacba8a4ad8ef795ad82a5552ee85c427a88140b',
    31503: '2debebed38e2ce5cc748edb7ba5a3d7d3ec19e3756d188d8272b09c135b043e6',
}

# These weapons already track a target or resolve instantly. Predictive aim
# would not improve their actual executor and must not change their semantics.
NO_LEAD = frozenset((1000009, 1000015, 1000025, 1000026, 1000031,
                     1000032, 1000033, 1000039, 1000056, 1000088,
                     1000120, 1000123))
# Only source weapons with these real splash radii receive cluster scoring.
SPLASH = {1000004: 144, 1000010: 108, 1000017: 108, 1000030: 216}


def handles(actor):
    """Side-effect-free ownership check, also used by generic mob dispatch."""
    arena = actor.arena
    profile = frozen_profile(arena) or {}
    version = profile.get('pve_boss_tactics_version')
    return bool(type(version) is int and version == 1
                and actor.info.get('pve_npc') and actor.camp != arena.player.camp
                and (arena.geometry.id, actor.info.get('npc_template')) in BINDINGS
                and profile.get('map_id') == arena.geometry.id
                and arena.geometry.data.get('source', {}).get('sha256')
                    == SOURCE_SHA256.get(arena.geometry.id)
                and not any(actor.info.get(key) for key in (
                    'pve_hostage', 'pve_trap', 'pve_fortification',
                    'pve_local_forklift', 'map_object')))


def _state(actor, brain, now):
    state = brain.get('pve_boss_tactics_v2')
    if not isinstance(state, dict) or state.get('generation') != actor.generation:
        state = dict(version=1, generation=actor.generation, phase=1,
                     notice_at=0, next_tick_at=0, end=0, observed_at=0,
                     phase_end=now+ORBIT_MS, side=1 if actor.id % 2 else -1,
                     target=None)
        brain['pve_boss_tactics_v2'] = state
        brain['path'], brain['repath_at'] = [], 0
        brain['goal'] = actor.position_at(now)
        brain['pve_patrolling'] = False
    phase = 3 if actor.hp <= actor.max_hp*D('.35') else 2 if actor.hp <= actor.max_hp*D('.70') else 1
    if phase > state['phase']:
        state['phase'] = phase
        state['next_tick_at'] = now
    # Healing/lifesteal never awards the same phase again. Direction changes
    # are movement choices, not a timer that grants another attack.
    if now >= state['phase_end']:
        turns = 1 + (now-state['phase_end']) // ORBIT_MS
        if turns % 2:
            state['side'] = -state['side']
        state['phase_end'] += turns*ORBIT_MS
    return state


def _target(actor, state, now):
    from bot_ai import observable
    from pve_tactics import weapon_line

    arena, pos = actor.arena, actor.position_at(now)
    # Only observable actors contribute position/HP/cluster information. Do not
    # consult a hidden actor's motion while deciding to change targets.
    visible = [a for a in arena.actors.values()
               if not a.info.get('map_object') and not a.info.get('pve_hostage')
               and not a.in_stasis() and a.is_area_targetable()
               and observable(arena, actor, a, now, NOTICE_RANGE)]
    visible.sort(key=lambda a: (math.dist(pos, a.position_at(now)), a.id))
    visible = visible[:16]
    if not visible:
        return None
    points = {a.id: tuple(a.position_at(now)) for a in visible}
    radius = SPLASH.get(actor.shot_skill, 0)

    def score(target):
        point = points[target.id]
        distance = math.dist(pos, point)
        # A clear native weapon lane takes priority over firing repeatedly
        # into water. Proximity still makes an adjacent threat important.
        blocked = 900 if not weapon_line(actor, pos, point, now) else 0
        out_of_range = 180 if distance > actor.pve_fire_range else 0
        group = (sum(1 for other in visible if other is not target
                     and math.dist(point, points[other.id]) <= radius
                     and weapon_line(actor, point, points[other.id], now))
                 if radius else 0)
        return blocked + out_of_range + distance + (48 if target.info.get('npc_template') else 0) - min(3, group)*56

    selected = min(visible, key=lambda a: (score(a), a.id))
    current = next((a for a in visible if a.id == state.get('target')
                    and a.generation == state.get('target_generation')), None)
    if current is not None and score(current) <= score(selected)+72:
        return current
    return selected


def _lead(actor, target, now, *, limit, horizon):
    """Predict only a visible current walk; clamp against the target's terrain."""
    point, motion = tuple(target.position_at(now)), target.motion
    if not limit or not motion or motion[3] <= now or motion[3] <= motion[2]:
        return point
    start, end, began, finish = motion
    dx, dy = (end[0]-start[0])*horizon/(finish-began), (end[1]-start[1])*horizon/(finish-began)
    distance = math.hypot(dx, dy)
    if distance > limit:
        dx, dy = dx*limit/distance, dy*limit/distance
    wish = actor.arena.geometry.clamp_tank_position((round(point[0]+dx), round(point[1]+dy)))
    return actor.arena.geometry.walk_end(point, wish, actor.arena.water_rects(now))


def _set_goal(brain, goal):
    goal = tuple(goal)
    if brain.get('goal') is None or math.dist(goal, brain['goal']) >= 24:
        brain['path'], brain['repath_at'] = [], 0
    brain['goal'], brain['pve_patrolling'] = goal, False


def _goal(actor, state, target, now, archetype):
    from pve_tactics import choose_air_goal, choose_goal

    phase, radius = state['phase'], actor.pve_fire_range
    point = tuple(target.position_at(now))
    if archetype == 'siege':
        return actor.position_at(now)
    if archetype == 'hunter':
        intercept = _lead(actor, target, now, limit=(0, 48, 72)[phase-1], horizon=240)
        return choose_goal(actor, intercept, now,
                           preferred_range=max(48, radius*(.68, .60, .52)[phase-1]))
    if archetype == 'air':
        return choose_air_goal(actor, point, now,
                               preferred_range=radius*(.80, .68, .56)[phase-1],
                               strafe=True, strafe_side=state['side'])
    factors = (.78, .70, .60) if archetype == 'heavy' else (.76, .64, .52)
    # Heavy vehicles make short firing-lane corrections during the native
    # cooldown; agile ranged bosses orbit even while their volley is active.
    strafe = archetype != 'heavy' or actor.cooldowns[0] > now+PERCEPTION_MS
    return choose_goal(actor, point, now, preferred_range=max(120, radius*factors[phase-1]),
                       strafe=strafe, strafe_side=state['side'])


def tick(actor, brain, now):
    """None preserves existing chapter behavior; a list owns this NPC tick."""
    if not handles(actor):
        return None
    arena = actor.arena
    if arena.pk['finished'] or not actor.alive or actor.in_stasis():
        return []
    from pve_movement import flight_move, move, patrol_goal
    from pve_tactics import weapon_line

    archetype = BINDINGS[arena.geometry.id, actor.info['npc_template']]
    state = _state(actor, brain, now)
    packets = []
    if now >= state['notice_at']:
        state['notice_at'] = now+PERCEPTION_MS
        brain['notice_at'] = state['notice_at']
        target = _target(actor, state, now)
        boundary = not (actor.motion and actor.motion[3] > now)
        if target is not None:
            changed = (state.get('target'), state.get('target_generation')) != (target.id, target.generation)
            point = tuple(target.position_at(now))
            state.update(target=target.id, target_generation=target.generation,
                         position=point, observed_at=now, end=now+MEMORY_MS)
            if boundary and (changed or now >= state['next_tick_at']):
                _set_goal(brain, _goal(actor, state, target, now, archetype))
                state['next_tick_at'] = now+PLAN_MS
            pos = actor.position_at(now)
            if math.dist(pos, point) <= actor.pve_fire_range and weapon_line(actor, pos, point, now):
                aim = point
                if archetype != 'hunter' and actor.shot_skill not in NO_LEAD:
                    proposal = _lead(actor, target, now, limit=(0, 48, 96)[state['phase']-1], horizon=450)
                    if math.dist(pos, proposal) <= actor.pve_fire_range and weapon_line(actor, pos, proposal, now):
                        aim = proposal
                # Native cast owns attack/slot locks, burst timing, cooldown,
                # effects and damage. Subsequent native burst rounds retain
                # their existing visible-target check and aim, not new lead.
                packets += actor.cast(0, pos, aim, target.id, now)
        else:
            prior = arena.actors.get(state.get('target'))
            remembered = (prior is not None and prior.alive
                          and prior.generation == state.get('target_generation')
                          and now < state['end'] and 'position' in state)
            if remembered and archetype != 'siege':
                if boundary and now >= state['next_tick_at']:
                    _set_goal(brain, state['position'])
                    state['next_tick_at'] = now+PLAN_MS
            else:
                state['target'], state['end'] = None, 0
                state['next_tick_at'] = now
                brain['goal'] = (patrol_goal(arena, actor, now, air_arrival=24)
                                 if archetype == 'air' else patrol_goal(arena, actor, now))
    if arena.pk['finished']:
        return packets
    if archetype == 'air':
        goal = brain.get('goal')
        if goal is not None:
            packets += flight_move(arena, actor, brain, goal, now)
    else:
        packets += move(arena, actor, brain, now)
    return packets
