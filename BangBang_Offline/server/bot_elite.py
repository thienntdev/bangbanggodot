"""PRO tactics over the existing native tank executors.

This is a decision policy, not a second combat engine. Enemy information is
delivered through the same delayed, team-visible samples as the legacy AI.
The director supplies a team assignment; this module chooses a local target,
firing/retreat position and imperfect aim, then uses the unchanged kit logic.
It never edits HP, stats, cooldowns, motion or enemy state.
"""
from __future__ import annotations

import math

import bot_ai as legacy
from combat_geometry import point_at, rect_contact


MIN_REACTION_MS = 180
MAX_CONTACT_AGE_MS = 1000
BASE_MAPS = frozenset((12, 14, 50, 169))
SURVIVAL_MAPS = frozenset((30, 40))
HOLD_TASKS = frozenset(('flag_hold', 'bomb_escort', 'bomb_intercept', 'escort'))
LOCAL_LEGACY_MAPS = frozenset((1, 4, 17, 18, 19, 20, 21, 34, 35, 36))

# These slot-0 launches were checked against each native cast method.  They
# are weapon knowledge belonging to the shooter, never an enemy sensor. Keep
# explicit multipliers (Gundam/Thach Sanh/Legolas/Tsubasa) instead of pretending
# that every tank's basic uses the same speed or even launches a projectile.
_BASIC_SHOTS = {
    'gundam_actions': (302600, 2.0),
    'ironman_actions': (363100, 1.0),
    'captain_actions': (323100, 1.0),
    'mermaid_actions': (340100, 1.0),
    'panda_actions': (301100, 1.0),
    'chopper_actions': (304100, 1.0),
    'teddy_actions': (306100, 1.0),
    'legolas_actions': (315100, 1.5),
    'thor_actions': (313100, 1.0),
    'hulu_actions': (311100, 1.0),
    'athena_actions': (359100, 1.0),
    'gilgamesh_actions': (362100, 1.0),
    'hikari_actions': (382100, 1.0),
    'elsa_actions': (381100, 1.0),
    'thuytinh_actions': (353100, 1.0),
    'swordgod_actions': (355100, 1.0),
    'noel_actions': (329100, 1.0),
    'caocao_actions': (366100, 1.0),
    'tsubasa_actions': (386100, 1.5),
    'zoro_actions': (351100, 1.0),
    'darkknight_actions': (305100, 1.5),
    'stonegod_actions': (384100, 1.0),
    'mulan_actions': (374100, 1.0),
}

# This verified own slot-0 missile uses the existing ballistic cursor only.
# Keep projectile-defense classification in _BASIC_SHOTS unchanged: knowing
# a launch speed does not add a guard-based target or firing preference.
_AIM_ONLY_SHOTS = {
    'medusa_actions': (333100, 1.0),
}

# Visible projectile-block/reflect buffs used by TankActions.projectile_blocked.
# Remaining duration is captured only after ordinary visibility succeeds.
_PROJECTILE_GUARDS = frozenset((332206, 386111, 351401, 323401, 382121,
                               334212, 341401, 318402))


def _ratio(actor):
    return float(actor.hp / actor.max_hp)


def _is_tank(sample):
    return not sample.get('objective', sample.get('robo', False))


def mature_contacts(seen, now):
    """Reject fresh/future and expired reports, without consulting live enemies.

    Kit-specific fields are intentionally kept on the original sample. The
    native executor still validates life, generation, LOS and cast legality.
    A stale sample is not extended using an enemy's current pose or velocity.
    """
    return [sample for sample in seen
            if MIN_REACTION_MS <= now - sample.get('observed_at', now)
            <= MAX_CONTACT_AGE_MS]


def observe(arena, actor, brain, now):
    """Add public target state only after the native observer sees that target.

    Remaining control is a duration at the sample instant, not a new absolute
    timer; decisions subtract sample age. No pending enemy casts, cooldowns,
    future route, input or invisible actor is used as a sensor.
    """
    from combat_data import active_buff_effect_types

    seen = legacy.observe(arena, actor, brain, now)
    previous = {sample['id']: sample for sample in brain.get('observations', ())}
    for sample in seen:
        target = arena.actors[sample['id']]
        sample['elite_tank_id'] = (None if target.info.get('npc_template')
                                   else target.info['tank_id'])
        sample['elite_range'] = int(target.stats.get('nFireRange', 420))
        sample['elite_shield'] = min(2.0, float(sum(
            shield.remaining for shield in target.shields
            if shield.expires_ms > now) / target.max_hp))
        # These are displayed protective states, sampled now and delivered on
        # the next reaction. A penalty is not a promise that all damage fails.
        sample['elite_guarded'] = (target.damage_immune('physical', now)
                                    and target.damage_immune('energy', now))
        control_ms = 0
        projectile_guard_ms = 0
        for (owner, template), (_, end) in target.active_buffs.items():
            if owner != target.id or end <= now:
                continue
            if active_buff_effect_types((template,)) & {30, 36, 62}:
                control_ms = max(control_ms, min(3000, end - now))
            if (template in _PROJECTILE_GUARDS
                    and (template != 386111 or target.info['tank_id'] in (10000111, 10000055))):
                projectile_guard_ms = max(projectile_guard_ms, min(10000, end - now))
        sample['elite_control_ms'] = control_ms
        sample['elite_projectile_guard_ms'] = projectile_guard_ms
        old = previous.get(sample['id'])
        stability = .85
        if old is not None and old['generation'] == sample['generation']:
            vx, vy = sample['velocity']
            ox, oy = old.get('velocity', (0, 0))
            speed, prior_speed = math.hypot(vx, vy), math.hypot(ox, oy)
            if speed > 20 and prior_speed > 20:
                alignment = max(-1.0, min(1.0, (vx*ox + vy*oy) / (speed*prior_speed)))
                stability = .65 + .35 * max(0, alignment)
            elif speed <= 20 and prior_speed <= 20:
                stability = 1.0
        sample['elite_track_stability'] = stability
    # Only materialized public warning bodies; these observations become
    # eligible on the following ordinary reaction, never the current tick.
    import bot_pro_hazards
    bot_pro_hazards.observe(arena, actor, brain, now)
    return seen


def aim(arena, actor, sample, now):
    """Bounded prediction from two old sightings, with persistent human error.

    The kit dispatcher shares one cursor between instant and projectile
    choices. Keep the prediction short rather than treating every skill as a
    projectile of a known speed; do not read a current enemy position.
    """
    pos = actor.position_at(now)
    distance = math.dist(pos, sample['pos'])
    age = max(0.0, min(.5, (now - sample['observed_at']) / 1000))
    travel = min(.40, distance / 1100)
    horizon = min(.55, age + travel) * arena.rng.uniform(.75, .95)
    vx, vy = sample.get('velocity', (0, 0))
    speed = math.hypot(vx, vy)
    if speed > 400:
        vx, vy = vx * 400 / speed, vy * 400 / speed
    # A control observation may expire before we react. Do not keep aiming at
    # a frozen point after that duration, nor query the live buff to correct it.
    if sample.get('elite_control_ms', 0) > now - sample['observed_at'] + 120:
        horizon *= .15
    error = arena.rng.gauss(0, 5 + distance * .014)
    angle = math.atan2(sample['pos'][1] - pos[1], sample['pos'][0] - pos[0])
    dest = (sample['pos'][0] + vx * horizon - math.sin(angle) * error,
            sample['pos'][1] + vy * horizon + math.cos(angle) * error)
    return arena.geometry.clamp_tank_position(dest)


def basic_target_open(sample, now, actor=None):
    """Do not knowingly feed a still-observed projectile reflect/guard.

    This is only a basic-fire preference. Native cast/hit rules retain final
    authority and the regular kit may still choose a useful non-projectile
    action. Expired observations do not extend the remembered protection.
    """
    age = now - sample.get('observed_at', now)
    if not MIN_REACTION_MS <= age <= MAX_CONTACT_AGE_MS:
        return False
    if actor is not None:
        profile = _basic_profile(actor, now)
        if profile is None or not profile[0]:
            # Unknown, melee and beam basics may bypass projectile defenses.
            # Do not silently suppress those native attacks using this hint.
            return True
    return sample.get('elite_projectile_guard_ms', 0) <= age


def _basic_profile(actor, now):
    module = type(actor).__module__.rsplit('.', 1)[-1]
    profile = _BASIC_SHOTS.get(module)
    if profile is not None:
        return (*profile, 0.0)
    if module == 'thachsanh_actions':
        return (338311 if actor.has_buff(338302, now) else 338100, 1.5, 0.0)
    if module == 'spider_actions':
        return (303131, 1.0, .1) if actor.has_buff(303113, now) else (303100, 1.0, 0.0)
    if module == 'kurumi_actions':
        # The alternative ammo is an instantaneous beam, not a slow bullet.
        return (370100, 1.5, 0.0) if actor._basic(now) == 370100 else (0, 1.0, 0.0)
    if module == 'sniper_actions' and not actor.special:
        return (376151 if actor.has_buff(376142, now) else 376100, 1.0, 0.0)
    return None


def _intercept_time(delta, velocity, speed):
    """Earliest constant-velocity intercept, bounded to an uncertain forecast."""
    dx, dy = delta
    vx, vy = velocity
    a = vx*vx + vy*vy - speed*speed
    b = 2*(dx*vx + dy*vy)
    c = dx*dx + dy*dy
    if abs(a) < 1e-6:
        return min(.75, max(0.0, -c/b)) if b < -1e-6 else min(.75, math.sqrt(c)/max(1, speed))
    discriminant = b*b - 4*a*c
    if discriminant < 0:
        return min(.75, math.sqrt(c)/max(1, speed))
    root = math.sqrt(discriminant)
    positive = [value for value in ((-b-root)/(2*a), (-b+root)/(2*a)) if value >= 0]
    return min(.75, min(positive)) if positive else min(.75, math.sqrt(c)/max(1, speed))


def basic_aim(arena, actor, sample, now):
    """Slot-specific lead from old sightings and our verified own weapon.

    General skills still use aim(): instant areas, dashes and homing casts do
    not share one bullet travel time. Unverified transformed/charged/melee
    basics deliberately retain that fallback too. The computed displacement
    is discounted for changes of direction during native walk/cast/evasion;
    this does not halve the sample age or the minimum reaction-time gate.
    This never inspects the live target, its route, cooldowns or next input.
    """
    profile = _basic_profile(actor, now)
    if profile is None:
        own_module = type(actor).__module__.rsplit('.', 1)[-1]
        aim_profile = _AIM_ONLY_SHOTS.get(own_module)
        if aim_profile is not None:
            profile = (*aim_profile, 0.0)
    if profile is None:
        return aim(arena, actor, sample, now)
    from combat_data import table_row
    template, multiplier, windup = profile
    start = actor.position_at(now)
    age = max(0.0, min(.8, (now-sample['observed_at'])/1000))
    vx, vy = sample.get('velocity', (0, 0))
    speed = math.hypot(vx, vy)
    if speed > 400:
        vx, vy = vx*400/speed, vy*400/speed
    stability = max(.65, min(1.0, sample.get('elite_track_stability', .85)))
    vx, vy = vx*stability, vy*stability
    observed = sample['pos']
    current = observed[0]+vx*age, observed[1]+vy*age
    if template:
        row = table_row('SkillTemplate_table.xml', nId=template)
        life = int(row['iLifeTime'])
        distance = int(row['iFlyRange'])
        if life <= 0 or distance <= 0:
            return aim(arena, actor, sample, now)
        own_speed = max(1, round(distance*1000/life * multiplier
                                 * max(.01, float(1+actor.attr_bonus((23,), now)))))
        travel = _intercept_time((current[0]-start[0], current[1]-start[1]),
                                 (vx, vy), own_speed)
    else:
        travel = 0.0
    horizon = min(1.0, age + windup + travel)
    controlled = sample.get('elite_control_ms', 0)/1000
    if controlled:
        # A just-stopped target's measured velocity includes its pre-CC walk.
        # We know only the sampled remaining duration, not future control.
        horizon = max(0.0, horizon-controlled)*.5
    # Old velocity frequently changes during a native walk/cast/evade period.
    # Discount the forecast displacement, not observation age or readiness.
    # The uncertainty weight uses no live input or future enemy trajectory.
    horizon *= .5 * arena.rng.uniform(.92, 1.02)
    point = observed[0]+vx*horizon, observed[1]+vy*horizon
    distance = math.dist(start, observed)
    error = arena.rng.gauss(0, 4+distance*.008)
    angle = math.atan2(point[1]-start[1], point[0]-start[0])
    point = point[0]-math.sin(angle)*error, point[1]+math.cos(angle)*error
    return arena.geometry.clamp_tank_position(point)


def _can_recover(actor, now):
    tank = actor.info['tank_id']
    if tank in legacy.bot_ai19.TANKS:
        return legacy.bot_ai19.can_recover(actor, now)
    if tank in legacy.bot_ai16.TANKS:
        return legacy.bot_ai16.can_recover(actor, now)
    if tank in legacy.bot_ai17.TANKS:
        return legacy.bot_ai17.can_recover(actor, now)
    if tank in legacy.bot_ai11.TANKS:
        return legacy.bot_ai11.can_recover(actor)
    return tank not in legacy.bot_ai10.TANKS or legacy.bot_ai10.can_recover(actor)


def pressure(pos, allies, tanks, now):
    """Local numbers/health, not unobserved attack stats or hidden cooldowns."""
    friendly = sum((.35 + .85 * _ratio(ally))
                   * max(0.0, 1 - math.dist(pos, ally.position_at(now)) / 720)
                   for ally in allies)
    hostile = sum((.35 + .85 * sample['hp'])
                  * max(0.0, 1 - math.dist(pos, sample['pos']) / 720)
                  * (.65 if sample.get('elite_control_ms', 0)
                     > now - sample['observed_at'] + 180 else 1.0)
                  for sample in tanks)
    return friendly, hostile


def _guard_preference_context(arena, actor, candidates, now):
    """Prefer an available open firing lane over a long sampled guard.

    This is a soft target preference, not another cast gate. It uses only
    our verified weapon/phase and mature enemy observations. Native skills
    may still prefer a guarded target, and pending native phases keep their
    existing cursor/target priorities. The order and observations are not
    modified and no current enemy actor is consulted.
    """
    profile = _basic_profile(actor, now)
    if arena is None or profile is None or not profile[0]:
        return frozenset()
    if (any(getattr(actor, key, None) for key in (
            'channel', 'ready', 'dash', 'vanish', 'hook', 'leap',
            'e_follow', 'dracula_ritual', 'caocao_hostage', 'hostage',
            'ice', 'egg', 'rebirth'))
            or now < getattr(actor, 'forced_until', 0)
            or (getattr(actor, 'motion', None)
                and getattr(actor, 'motion_kind', 0) != 0 and actor.motion[3] > now)):
        return frozenset()
    contacts = mature_contacts(candidates, now)
    guarded = frozenset((sample['id'], sample['generation']) for sample in contacts
                        if not sample.get('elite_guarded')
                        and sample.get('elite_projectile_guard_ms', 0)
                        - (now - sample['observed_at']) > 180)
    if not guarded:
        return guarded
    from bot_execution import basic_range
    reach = basic_range(actor, now)
    pos = actor.position_at(now)
    for sample in contacts:
        if ((sample['id'], sample['generation']) in guarded
                or sample.get('elite_guarded')
                or sample.get('elite_projectile_guard_ms', 0) > now - sample['observed_at']
                or math.dist(pos, sample['pos']) > reach):
            continue
        exclude = (tuple(sample['turret_rect']),) if sample.get('turret_rect') else ()
        if arena.geometry.wall_contact(pos, sample['pos'], exclude=exclude) is None:
            return guarded
    return frozenset()


def _target_score(actor, brain, sample, allies, order, now, guarded=()):
    pos = actor.position_at(now)
    distance = math.dist(pos, sample['pos'])
    score = distance * .72 + sample['hp'] * 240
    score += sample.get('elite_shield', 0) * 150
    if sample.get('elite_guarded'):
        score += 560
    if (sample['id'], sample['generation']) in guarded:
        # Less than full immunity; enough to offset focus+lock when another
        # mature, unguarded target is already in our own native firing lane.
        score += 360
    if (sample['id'] == order.get('focus')
            and sample['generation'] == order.get('focus_generation')):
        score -= 240
    if (brain.get('target') == sample['id']
            and brain.get('elite_target_generation') == sample['generation']
            and now < brain.get('elite_target_until', 0)):
        score -= 85
    if sample['hp'] <= .23:
        score -= 140
    if sample.get('elite_control_ms', 0) > now - sample['observed_at'] + 120:
        score -= 90  # Follow a teammate's visible initiation before it ends.
    if _is_tank(sample):
        # Peel by an old threat position and current allied distress. Allies
        # may communicate their health/position; enemy intent is not read.
        endangered = [ally for ally in allies if ally is not actor
                      and _ratio(ally) < .55
                      and math.dist(ally.position_at(now), sample['pos']) < 264]
        if endangered:
            score -= max((1 - _ratio(ally)) * 250 for ally in endangered)
        nearby_friends = sum(math.dist(ally.position_at(now), sample['pos']) <= 420
                             for ally in allies)
        score -= min(3, nearby_friends) * 30
        if order.get('role') == 'skirmisher' and sample.get('elite_range', 420) >= 450:
            score -= 45
    if order.get('goal') is not None and order.get('task') not in ('skirmish', 'regroup'):
        score += max(0, math.dist(order['goal'], sample['pos']) - 200) * .28
    return score, sample['id']


def select_target(actor, brain, candidates, allies, order, now):
    if not candidates:
        brain['target'] = None
        brain.pop('elite_target_generation', None)
        brain.pop('elite_target_until', None)
        return None
    guarded = _guard_preference_context(getattr(actor, 'arena', None), actor, candidates, now)
    target = min(candidates, key=lambda s: _target_score(actor, brain, s, allies, order, now, guarded))
    if (brain.get('target'), brain.get('elite_target_generation')) != (target['id'], target['generation']):
        brain['elite_target_until'] = now + 650
    brain['target'] = target['id']
    brain['elite_target_generation'] = target['generation']
    return target


def _set_goal(brain, goal):
    brain['goal'] = tuple(round(value) for value in goal)


def _refresh_route(brain, previous):
    # A director anchor and a firing point are intermediate decisions, not
    # separate walk commands. Invalidate once against the previous final goal
    # so a stable firing lane does not force A* on every reaction.
    if previous is None or math.dist(previous, brain['goal']) > 96:
        brain['repath_at'] = 0


def _retreat_goal(arena, actor, allies, tanks, order, now):
    pos = actor.position_at(now)
    if arena.geometry.id in SURVIVAL_MAPS:
        from death_mode import survival_goal
        return survival_goal(arena, actor, {}, now)[1]
    # Retreat toward a healthy teammate, not indefinitely toward a spawn that
    # cannot heal. This keeps a wounded bot useful as a second-line fighter.
    friends = [ally for ally in allies if ally is not actor and _ratio(ally) > .38]
    if friends:
        def score(ally):
            point = ally.position_at(now)
            danger = sum(max(0, 360 - math.dist(point, s['pos'])) for s in tanks)
            return math.dist(pos, point) + danger * 1.3 - _ratio(ally) * 180, ally.id
        friend = min(friends, key=score)
        goal = friend.position_at(now)
        if tanks:
            nearest = min(tanks, key=lambda s: math.dist(goal, s['pos']))
            distance = max(1, math.dist(goal, nearest['pos']))
            goal = point_at(goal, nearest['pos'], -144 / distance)
        goal = arena.geometry.clamp_tank_position(goal)
        if arena.geometry.can_walk_to(goal):
            return goal
        return friend.position_at(now)
    if tanks:
        threat = min(tanks, key=lambda s: math.dist(pos, s['pos']))
        distance = max(1, math.dist(pos, threat['pos']))
        point = arena.geometry.clamp_tank_position(point_at(pos, threat['pos'], -216 / distance))
        if arena.geometry.can_walk_to(point):
            return point
    return order.get('goal') or arena.geometry.spawn(actor.camp, 0, respawn=True)


def _contagion_friends(actor, allies, order, now):
    """Separate ordinary fighters from an allied visible spreading burn.

    Native Amaterasu transfers from its displayed spread buffs within 144px.
    Own and allied buffs/positions are communicated state, not an enemy
    sensor. Keep holds, recovery and every native pending phase in charge;
    this helper adds no timers or checkpoint state.
    """
    if (order.get('task') not in ('skirmish', 'clear_path')
            or actor.blocked('move', now)
            or any(getattr(actor, key, None) for key in (
                'channel', 'ready', 'dash', 'vanish', 'hook', 'leap',
                'e_follow', 'dracula_ritual', 'caocao_hostage', 'hostage',
                'ice', 'egg', 'rebirth'))
            or now < getattr(actor, 'forced_until', 0)
            or (actor.motion and actor.motion_kind != 0 and actor.motion[3] > now)):
        return ()
    spread_buffs = (368103, 368312)
    spreading = any(actor.has_buff(template, now) for template in spread_buffs)
    return tuple(ally.position_at(now) for ally in allies
                 if ally is not actor and ally.alive and ally.camp == actor.camp
                 and (spreading or any(ally.has_buff(template, now)
                                       for template in spread_buffs)))


def _combat_goal(arena, actor, allies, tanks, target, order, desired, blocked, now):
    """Small bounded geometric choice; all actual movement uses native walk."""
    from bot_engagement import spacing_range
    desired = spacing_range(arena, actor, target, order, desired, now)
    pos = actor.position_at(now)
    distance = math.dist(pos, target['pos'])
    task = order.get('task')
    objective = order.get('goal', pos)
    if task in HOLD_TASKS:
        return objective
    if task == 'regroup' and distance > 240:
        return objective
    leash = order.get('target_radius', 720)
    if (task not in ('skirmish', 'base_push', 'clear_path')
            and (math.dist(target['pos'], objective) > leash
                 or math.dist(pos, objective) > 300 and distance > 300)):
        return objective

    # No constant orbit when a stable firing position already works. Stationary
    # kits still get their own adjust_goal afterwards, through native combat.
    friends = [ally.position_at(now) for ally in allies if ally is not actor]
    contagious = _contagion_friends(actor, allies, order, now)
    # The existing native body half-width (36px) gives one body margin beyond
    # the authored 144px spread radius. Ordinary spacing stays unchanged.
    crowded = (any(math.dist(pos, p) < 88 for p in friends)
               or any(math.dist(pos, p) < 180 for p in contagious))
    threats_close = any(math.dist(pos, s['pos']) < min(260, desired - 70) for s in tanks)
    if not blocked and abs(distance - desired) < 65 and not crowded and not threats_close:
        return pos

    # Candidate points around the observed target spread the team across firing
    # lanes without running past its front line or consulting hidden opponents.
    angle = math.atan2(pos[1] - target['pos'][1], pos[0] - target['pos'][0])
    turn = 1 if actor.id % 2 else -1
    radius = max(84, desired)
    points = []
    for offset in (0, turn * .28, -turn * .28, turn * .56, -turn * .56):
        p = arena.geometry.clamp_tank_position((target['pos'][0] + math.cos(angle + offset) * radius,
                                                 target['pos'][1] + math.sin(angle + offset) * radius))
        if not arena.geometry.can_walk_to(p):
            continue
        if (task not in ('skirmish', 'base_push', 'clear_path', 'regroup')
                and math.dist(p, objective) > leash):
            continue
        points.append(p)
    if not points:
        return target['pos'] if blocked and task in ('skirmish', 'base_push', 'clear_path') else objective

    if blocked:
        # A teammate can keep reporting an enemy behind our wall. If every
        # sampled firing point is occluded, the closest point may be exactly
        # where we stand: endlessly scoring it as cheap would never open LOS.
        # Approach through the unchanged native path planner instead; bounded
        # objective roles keep their own anchor rather than chase past a leash.
        # Native walk stops within 20px and removes grid waypoints within
        # 18px. A new LOS point in that dead zone would never be reached.
        clear = [point for point in points
                 if math.dist(pos, point) >= 48
                 and arena.geometry.wall_contact(point, target['pos']) is None]
        if not clear:
            return target['pos'] if task in ('skirmish', 'base_push', 'clear_path') else objective
        points = clear

    if any(math.dist(pos, friend) < 180 for friend in contagious):
        # A small spacing improvement inside native walk's 20px stop radius
        # cannot separate these bodies. A firing-ring point on the other side
        # can instead move us closer to the burn. Require less exposure and
        # the same 48px movement margin used above. The bounded96px probes
        # reuse native evade's scale and native body/water collision checks.
        def exposure(point):
            return sum(max(0, 180 - math.dist(point, friend)) for friend in contagious)
        current_exposure = exposure(pos)
        moving = [point for point in points if math.dist(pos, point) >= 48
                  and exposure(point) < current_exposure]
        closest = min(contagious, key=lambda friend: math.dist(pos, friend))
        away = math.atan2(pos[1] - closest[1], pos[0] - closest[0])
        water = arena.water_rects(now)
        for offset in (0, turn * .28, -turn * .28, turn * .56, -turn * .56):
            proposed = arena.geometry.clamp_tank_position(
                (pos[0] + math.cos(away + offset) * 96,
                 pos[1] + math.sin(away + offset) * 96))
            point = arena.geometry.walk_end(pos, proposed, water)
            if (math.dist(pos, point) >= 48 and exposure(point) < current_exposure
                    and arena.geometry.can_walk_to(point)):
                moving.append(point)
        if moving:
            points = moving

    def score(point):
        spacing = sum(max(0, 100 - math.dist(point, p)) * 4 for p in friends)
        spacing += sum((max(0, 180 - math.dist(point, p))
                        - max(0, 100 - math.dist(point, p))) * 4 for p in contagious)
        # Supports/backline avoid charging between several known enemies.
        danger = sum(max(0, 240 - math.dist(point, sample['pos'])) for sample in tanks
                     if sample['id'] != target['id'])
        danger *= 1.5 if order.get('role') in ('support', 'artillery') else .7
        line = 160 if arena.geometry.wall_contact(point, target['pos']) is not None else 0
        leash_cost = (math.dist(point, objective) * .18
                      if task not in ('skirmish', 'base_push', 'clear_path') else 0)
        return math.dist(pos, point) + spacing + danger + line + leash_cost
    return min(points, key=score)


def _survival_constraint(arena, actor, brain, tanks, now):
    if arena.geometry.id not in SURVIVAL_MAPS:
        return
    from death_mode import RADIUS, center, constrain_goal, survival_goal
    constrain_goal(arena, actor, brain, tanks, now)
    # The original constrain_goal returns early without enemy sightings. A
    # regroup/retreat plan must still obey the publicly announced safe area.
    if now >= arena.pk['collapse_at'] - 5000:
        if math.dist(brain['goal'], center(arena)) > RADIUS - 45:
            _set_goal(brain, survival_goal(arena, actor, brain, now)[1])


def _flag_hold_arrival(arena, actor, brain, order, now):
    """Finish a real inward walk if generic arrival stops outside capture.

    A displaced bot can stand 62px from the flag but only 14px from its 48px
    holding offset. Native walk treats that as arrived. Merely moving the
    cursor one 24px step inward is insufficient: the nearest-grid/path 18px
    tolerance can discard that waypoint too. Check the native planner's next
    actual step, without moving, snapping, or changing its collision rules.
    """
    if (order.get('task') != 'flag_hold' or order.get('objective_center') is None
            or getattr(actor, 'channel', None) or getattr(actor, 'ready', None)
            or (actor.motion and actor.motion[3] > now and actor.motion_kind != 0)):
        return None
    from occupy_rules import RADIUS
    pos, center, goal = actor.position_at(now), order['objective_center'], order['goal']
    if (math.dist(pos, center) <= RADIUS or math.dist(pos, goal) > 24
            or actor.blocked('move', now) or actor._speed(now) <= 0):
        return None
    friends = [a.position_at(now) for a in arena.actors.values()
               if a.id != actor.id and a.camp == actor.camp and a.alive
               and not a.info.get('map_object') and not a.info.get('cow_object')
               and not a.info.get('bomb_cart') and not a.info.get('totem')]
    water = arena.water_rects(now)

    def inward(point):
        return (math.dist(point, center) <= RADIUS
                and all(math.dist(point, friend) >= 64 for friend in friends)
                and arena.geometry.walk_end(pos, point, water) == point)

    legal_steps = {(pos[0]+dx*24, pos[1]+dy*24) for dx, dy in legacy.DIRECTIONS[:8]
                   if inward((pos[0]+dx*24, pos[1]+dy*24))}
    if not legal_steps:
        # A centred human or a packed neighbouring holder can make another
        # contribution physically impossible. Do not push through the ally.
        return None
    if not hasattr(arena, 'navigation'):
        arena.navigation = legacy.Navigation(arena.geometry)
    nav = arena.navigation
    grid = tuple(round((v-12)/24)*24+12 for v in center)
    candidates = [(grid[0]+dx*24, grid[1]+dy*24)
                  for dx in range(-3, 4) for dy in range(-3, 4)]
    candidates = [p for p in candidates if math.dist(p, center) <= RADIUS
                  and math.dist(p, pos) >= 20 and nav.clear(p, p)
                  and all(math.dist(p, friend) >= 64 for friend in friends)]
    blockers = ([p for p in friends if math.dist(p, pos) < 240]
                if now < brain.get('avoid_allies_until', 0) else ())

    def next_step(waypoint):
        choices = sorted((math.dist((pos[0]+24*dx, pos[1]+24*dy), waypoint), i,
                          (pos[0]+24*dx, pos[1]+24*dy))
                         for i, (dx, dy) in enumerate(legacy.DIRECTIONS[:8]))
        return next((p for distance, _, p in choices if distance < math.dist(pos, waypoint)
                     and arena.geometry.walk_end(pos, p, water) == p), None)

    for point in sorted(candidates, key=lambda p: (math.dist(p, goal), math.dist(p, center), p)):
        path = list(nav.path(pos, point, blockers=blockers))
        while path and math.dist(pos, path[0]) < 18:
            path.pop(0)
        if not path:
            continue
        step = next_step(path[0])
        if step is None and len(path) > 1 and math.dist(pos, path[0]) < 24:
            step = next_step(path[1])
        if step in legal_steps:
            return point
    return None


def _base_target_objective(actor, order, nearby, objective, now):
    """Native defence filtering expects a threat point, not a holding offset.

    The director's goal is where the bot should stand. In base_mode.targets,
    objective[1] instead denotes the selected observed home threat, around
    which the native 360px target filter is applied. Keep those semantics
    separate; all attack candidates still come from this bot's mature sample.
    """
    center = order.get('objective_center')
    if order.get('task') != 'base_defend' or center is None:
        return objective
    threats = [s for s in mature_contacts(nearby, now)
               if not s.get('barrier') and not s.get('structure')
               and math.dist(s['pos'], center) < 660]
    if not threats:
        return objective
    pos = actor.position_at(now)
    threat = min(threats, key=lambda s: (math.dist(pos, s['pos']), s['id']))
    return objective[0], tuple(threat['pos'])


def _finishing_cart(arena, actor, brain, order, now):
    """Revalidate a cached final-push order against our own public cart."""
    if (order.get('task') != 'bomb_escort' or not order.get('final_push')
            or _ratio(actor) < .40 or brain.get('repair_goal')
            or brain.get('generation') != actor.generation):
        return False
    from escort_mode import eligible, progress
    if not eligible(actor, now):
        return False
    # This is allied/public objective state, not a scan of enemy contributors.
    return any(cart.camp == actor.camp and cart.info.get('bomb_cart')
               and cart.alive and progress(cart, now) > .87
               and math.dist(actor.position_at(now), cart.position_at(now)) <= 200
               for cart in arena.actors.values())


def _distant_contact_focus(arena, actor, candidates, order, now):
    """Return a distant shared focus when a local basic opportunity exists.

    This is a preference adjustment, not an attack or pursuit prohibition.
    Shared focus is useful only when this actor can contribute to it; a tank
    currently in our own native basic range should not be ignored just because
    a teammate can reach another target. Kit-owned pending actions keep their
    existing steering. All enemy facts below are already mature observations.
    """
    if (arena.geometry.id not in LOCAL_LEGACY_MAPS
            or any(getattr(actor, key, None) for key in (
                'channel', 'ready', 'dash', 'vanish', 'hook', 'leap',
                'e_follow', 'dracula_ritual', 'caocao_hostage', 'hostage',
                'ice', 'egg', 'rebirth'))
            or now < getattr(actor, 'forced_until', 0)
            or actor.motion and actor.motion_kind != 0 and actor.motion[3] > now):
        return None
    contacts = [sample for sample in mature_contacts(candidates, now)
                if _is_tank(sample)]
    focus = next((sample for sample in contacts
                  if (sample['id'], sample['generation'])
                  == (order.get('focus'), order.get('focus_generation'))), None)
    if focus is None:
        return None
    from bot_execution import basic_range
    reach = basic_range(actor, now)
    pos = actor.position_at(now)
    if math.dist(pos, focus['pos']) <= reach + 24:
        return None
    if any(sample is not focus and not sample.get('elite_guarded')
           and math.dist(pos, sample['pos']) <= reach
           and arena.geometry.wall_contact(pos, sample['pos']) is None
           for sample in contacts):
        return focus['id'], focus['generation']
    return None


def _recover_blocker(arena, actor, brain, seen, now):
    """Clear observed cover that has physically stopped our repair route.

    A previous native blocked step supplies the hint. Bind it to the same
    repair destination and location, then use only a mature cover sample.
    This is a basic-shot target preference: keep the repair goal, resource
    policy and every native support/cast/stealth/phase guard unchanged.
    """
    repair = brain.get('repair_goal')
    hint = brain.get('route_blocker')
    goal = brain.get('goal')
    if (repair is None or hint is None or goal is None or brain.get('path')
            or math.dist(goal, repair) > 20 or math.dist(hint['goal'], repair) > 96
            or not actor.alive or actor.info.get('npc_template')
            or actor.blocked('move', now) or actor.blocked('attack', now)
            or actor.motion and actor.motion[3] > now
            or any(getattr(actor, key, None) for key in (
                'channel', 'ready', 'dash', 'vanish', 'hook', 'leap', 'e_follow',
                'dracula_ritual', 'caocao_hostage', 'hostage', 'ice', 'egg', 'rebirth'))):
        return None
    pos = actor.position_at(now)
    if (hint.get('origin') is None or math.dist(pos, hint['origin']) > 96
            or math.dist(pos, repair) < 20):
        return None
    contacts = mature_contacts(seen, now)
    blocker = next((sample for sample in contacts
                    if sample.get('barrier') and sample.get('turret_rect')
                    and sample['id'] == hint['id']
                    and sample['generation'] == hint['generation']), None)
    if blocker is None:
        return None
    from bot_execution import basic_range
    reach = basic_range(actor, now)
    rectangle = (tuple(blocker['turret_rect']),)
    if (math.dist(pos, blocker['pos']) > reach
            or rect_contact(pos, repair, rectangle, 35.999) is None
            or arena.geometry.wall_contact(pos, blocker['pos'], exclude=rectangle) is not None):
        return None
    if any(_is_tank(sample) and math.dist(pos, sample['pos']) <= max(360, reach)
           and arena.geometry.wall_contact(pos, sample['pos']) is None
           for sample in contacts):
        return None
    return blocker


def contact_combat(arena, actor, brain, seen, nearby, allies, target, dest,
                   retreat, blocked, recovering, now):
    """Refine a native PK decision, then let its existing kit execute it.

    Local mode selection, healing, special objectives and every kit's own
    support/steer/recast sequence remain in the native decision path.  A team
    focus is a preference only among our mature local contacts, never a new
    target ID read from a live enemy or another bot's instantaneous action.
    This runs *before* the shared executor; there is no post-cast goal write.
    """
    from bot_teamwork import orders, role_for

    pos = actor.position_at(now)
    tanks = [sample for sample in mature_contacts(nearby, now) if _is_tank(sample)]
    order = dict(orders(arena, actor.camp, now).get(actor.id) or {})
    order.update(role=role_for(actor), task=brain.get('objective') or 'skirmish',
                 goal=tuple(brain.get('goal', pos)))
    repair_blocker = _recover_blocker(arena, actor, brain, seen, now) if recovering else None
    candidates = [repair_blocker] if repair_blocker is not None else tanks or [target]
    previous_goal = brain.get('elite_contact_previous_goal', brain.get('goal'))
    # legacy.decide has just assigned brain['target']; that is not necessarily
    # the target this controller was fighting last reaction. Keep a separate
    # identity and use the existing rebased deadline for bounded hysteresis.
    scoring_brain = dict(brain, target=brain.get('elite_contact_target'),
                         elite_target_generation=brain.get('elite_contact_generation'))
    distant_focus = _distant_contact_focus(arena, actor, candidates, order, now)
    guarded = _guard_preference_context(arena, actor, candidates, now)

    def score(sample):
        value = _target_score(actor, scoring_brain, sample, allies, order, now, guarded)[0]
        if (sample['id'], sample['generation']) == distant_focus:
            # Keep 60 of the ordinary 240 shared-focus preference. Existing
            # own-target hysteresis, finish/control/peel priorities remain.
            value += 180
        if arena.geometry.wall_contact(pos, sample['pos']) is not None:
            value += 200
        # Do not run through an immediate threat just to chase a remote focus
        # or tiny HP bar.  LOS and reach are preferences, not a target ban.
        value += max(0, math.dist(pos, sample['pos']) - 540) * .5
        return value, sample['id']

    chosen = min(candidates, key=score)
    if chosen['id'] != target['id']:
        target = chosen
        dest = aim(arena, actor, target, now)
        exclude = (tuple(target['turret_rect']),) if repair_blocker is not None else ()
        blocked = arena.geometry.wall_contact(pos, target['pos'], exclude=exclude) is not None
        brain['target'] = target['id']
    brain['elite_target_generation'] = target['generation']
    brain['elite_contact_target'] = target['id']
    brain['elite_contact_generation'] = target['generation']
    brain['elite_target_until'] = now + 700
    if retreat and not recovering:
        _set_goal(brain, _retreat_goal(arena, actor, allies, tanks, order, now))
    elif not recovering and _is_tank(target) and order['task'] in ('skirmish', 'clear_path'):
        _set_goal(brain, _combat_goal(arena, actor, allies, tanks, target, order,
                                     legacy.desired_range(actor, now), blocked, now))
    _refresh_route(brain, previous_goal)
    return target, dest, retreat, blocked


def decide(arena, actor, brain, seen, now):
    from bot_teamwork import orders, resolve_order, role_for

    # This is last-reaction metadata, not a timer or an asynchronous command.
    # Tick pairs decide/evade synchronously; each decision replaces the marker,
    # and generation changes already clear the native brain before deciding.
    brain['elite_micro_policy'] = 'elite'
    brain['elite_native_goal'] = False
    if actor.info.get('npc_template'):
        return legacy.decide(arena, actor, brain, seen, now)
    pos = actor.position_at(now)
    previous_goal = brain.get('goal')
    delivered = mature_contacts(seen, now)
    if (arena.geometry.id in LOCAL_LEGACY_MAPS
            and any(not sample.get('barrier') and math.dist(pos, sample['pos']) < 960
                    for sample in delivered)):
        # Keep the proven native local fight/objective/support sequencing. The
        # elite director handles assembly when there is no mature local fight.
        # 960px matches legacy.decide's own contact filter, so a non-barrier
        # contact on these PK maps reaches its shared native combat executor.
        brain['elite_micro_policy'] = 'legacy_contact'
        for key in ('elite_task', 'elite_role', 'elite_stance', 'elite_anchor',
                    'elite_hold_center', 'elite_hold_radius', 'elite_pressure',
                    'elite_retreat_until', 'elite_final_push'):
            brain.pop(key, None)
        if brain.get('elite_contact_target') is None:
            # A tactical/non-contact lock is not a PK contact lock. Old saves
            # lacking the new identity keep the original clean-entry behavior.
            brain.pop('elite_target_generation', None)
            brain.pop('elite_target_until', None)
        # Native decide may temporarily choose a spawn/linear firing point.
        # Route invalidation must compare our final goal with the preceding
        # reaction's final goal, not that intermediate point. This synchronous
        # scratch entry is never retained in a checkpoint, even on an error.
        brain['elite_contact_previous_goal'] = previous_goal
        try:
            packets = legacy.decide(arena, actor, brain, delivered, now)
        finally:
            brain.pop('elite_contact_previous_goal', None)
        brain['elite_task'] = brain.get('objective') or 'combat'
        brain['elite_role'] = role_for(actor)
        brain['elite_stance'] = 'native_contact'
        brain['elite_anchor'] = tuple(brain.get('goal', pos))
        # The shared combat wrapper records elite_native_goal around only the
        # native executor, so a kit-owned goal can suppress ordinary evasion.
        return packets
    nearby = [sample for sample in delivered if math.dist(pos, sample['pos']) < 960]
    tanks = [sample for sample in nearby if _is_tank(sample)]
    # Own-side information is communicated, not guessed from an enemy actor.
    friends = [a for a in arena.actors.values() if a.camp == actor.camp and a.alive
               and not a.info.get('npc_template')]
    allies = [a for a in friends if math.dist(pos, a.position_at(now)) < 720]
    order = dict(orders(arena, actor.camp, now).get(actor.id) or {})
    if 'goal' not in order:
        order.update(task='skirmish', goal=legacy.advance_goal(arena, actor, brain, now),
                     role='fighter', stance='engage', target_radius=720)
    order = resolve_order(arena, actor, order, delivered, now)
    arrival = _flag_hold_arrival(arena, actor, brain, order, now)
    if arrival is not None:
        # This is our private order copy; the shared director plan is immutable.
        order['goal'] = arrival
        brain['repath_at'] = 0
    brain['objective'] = order['task']
    brain['elite_task'] = order['task']
    brain['elite_role'] = order.get('role', 'fighter')
    brain['elite_stance'] = order.get('stance', 'engage')
    brain['elite_anchor'] = tuple(order['goal'])
    brain['elite_hold_center'] = order.get('objective_center')
    brain['elite_hold_radius'] = order.get('hold_radius', 0)
    # A healthy contributor already moving the nearly-finished cart should
    # close the round instead of abandoning it on a generic pressure score.
    # The director has verified actual native contribution and public route
    # progress; this is a tactical commitment, never immunity or extra HP.
    final_push = _finishing_cart(arena, actor, brain, order, now)
    brain['elite_final_push'] = bool(final_push)
    if order.get('siege_target') is not None:
        brain['siege_target'] = order['siege_target']
    else:
        brain.pop('siege_target', None)
    _set_goal(brain, order['goal'])

    friendly, hostile = pressure(pos, allies, tanks, now)
    brain['elite_pressure'] = (round(friendly, 3), round(hostile, 3))
    ratio = _ratio(actor)
    commit = ratio < .4 and legacy.useful_last_stand(actor, allies, tanks, now)
    soul = legacy.bot_ai10.soul(actor)
    overwhelmed = hostile > max(1.1, friendly * 1.4) and len(tanks) >= 2
    danger = bool(tanks) and (ratio < .26 or overwhelmed and ratio < .68)
    retreat_now = not commit and not soul and danger and not final_push
    if retreat_now:
        brain['elite_retreat_until'] = now + 700
    retreat = retreat_now or (not commit and not soul and not final_push and bool(tanks)
                              and now < brain.get('elite_retreat_until', 0))
    recover_limit = .48 if order.get('role') in ('support', 'artillery') else .40
    recovering = (_can_recover(actor, now) and ratio < recover_limit and not commit and not final_push
                  and legacy.seek_repair(arena, actor, brain, nearby, now))
    if not recovering:
        brain.pop('repair_box', None)
        brain.pop('repair_goal', None)
        brain.pop('repair_threats', None)
    retreat = retreat or recovering
    if retreat and not recovering:
        _set_goal(brain, _retreat_goal(arena, actor, friends, tanks, order, now))

    objective = order['task'], tuple(order['goal'])
    repair_blocker = _recover_blocker(arena, actor, brain, delivered, now) if recovering else None
    blocker = repair_blocker or legacy.bot_obstacles.selected(brain, nearby, objective, pos)
    # Only fire at a barrier after a real blocked step or when it intersects
    # the public objective approach, and never let it outrank a close fight.
    nearby = [s for s in nearby if s is repair_blocker or not s.get('barrier') or
              (not recovering and (not tanks or arena.geometry.id in BASE_MAPS)
               and (s is blocker or (arena.geometry.id in (12, 14, 21, 34, 35, 50, 70, 169)
                    and rect_contact(pos, objective[1], (tuple(s['turret_rect']),)) is not None)))]
    candidates = [repair_blocker] if repair_blocker is not None else tanks or nearby
    if arena.geometry.id == 70 and not recovering:
        from escort_mode import targets
        candidates = targets(actor, nearby, tanks, objective)
    elif arena.geometry.id in BASE_MAPS and not recovering:
        from base_mode import targets
        target_objective = _base_target_objective(actor, order, nearby, objective, now)
        candidates = targets(actor, brain, nearby, tanks, allies, target_objective, now)
    elif order['task'] not in ('skirmish', 'regroup', 'clear_path') and not retreat:
        leash = order.get('target_radius', 720)
        candidates = [s for s in candidates if math.dist(s['pos'], order['goal']) <= leash
                      or math.dist(pos, s['pos']) <= 280]
    target = select_target(actor, brain, candidates, allies, order, now)
    if target is None:
        _survival_constraint(arena, actor, brain, tanks, now)
        _refresh_route(brain, previous_goal)
        tactical_goal = brain['goal']
        packets = legacy.support(arena, actor, allies,
                                 delivered if actor.info['tank_id'] == 10000112 else nearby,
                                 now, brain, recovering)
        brain['elite_native_goal'] = brain['goal'] != tactical_goal
        return packets

    dest = aim(arena, actor, target, now)
    exclude = (tuple(target['turret_rect']),) if target.get('turret_rect') else ()
    blocked = arena.geometry.wall_contact(pos, target['pos'], exclude=exclude) is not None
    if not retreat:
        if target.get('barrier') or target.get('structure') and arena.geometry.id in BASE_MAPS:
            from base_mode import firing_position
            structure = arena.actors.get(target['id'])
            if structure is not None and structure.generation == target['generation']:
                point = firing_position(arena, actor, structure, now,
                                        reach=legacy.structure_range(actor, now))
                _set_goal(brain, point or order['goal'])
        else:
            _set_goal(brain, _combat_goal(arena, actor, allies, tanks, target, order,
                                         legacy.desired_range(actor, now), blocked, now))
    _survival_constraint(arena, actor, brain, tanks, now)
    _refresh_route(brain, previous_goal)
    # No post-combat goal assignment: support/steer/hold/recast logic owns any
    # kit-specific adjustment it legitimately makes, including invisibility.
    tactical_goal = brain['goal']
    packets = legacy.combat(arena, actor, brain, delivered, nearby, allies, target,
                            dest, retreat, blocked, recovering, now)
    brain['elite_native_goal'] = brain['goal'] != tactical_goal
    return packets


def _projectile_risk(pos, point, shots, now, move_speed):
    """Risk estimate along a proposed walk, using visible old flight samples."""
    walk_time = max(.05, math.dist(pos, point) / max(1, move_speed))
    risk = 0.0
    for shot in shots:
        age = (now - shot['observed_at']) / 1000
        if not MIN_REACTION_MS / 1000 <= age <= .8:
            continue
        vx, vy = shot['velocity']
        speed2 = vx * vx + vy * vy
        if not speed2:
            continue
        bx, by = shot['pos'][0] + vx * age, shot['pos'][1] + vy * age
        arrival = ((pos[0] - bx) * vx + (pos[1] - by) * vy) / speed2
        if not -.1 <= arrival <= .65:
            continue
        for future in (.12, .28, .45, .60):
            tank = point_at(pos, point, min(1.0, future / walk_time))
            gap = math.dist(tank, (bx + vx * future, by + vy * future))
            risk += max(0, 88 - gap) * (1 - future * .5)
    return risk


def evade(arena, actor, brain, now):
    """Choose a coarse safer sidestep, never a perfect/future projectile dodge."""
    import bot_pro_hazards
    if bot_pro_hazards.evade(arena, actor, brain, now):
        return
    if brain.get('elite_micro_policy') == 'legacy_contact':
        # This guarded production branch differs deliberately from the QA
        # diagnostic's unconditional legacy evade call. Preserve native active
        # channels, ready/recast phases, dashes and explicit kit-owned goals.
        motion = getattr(actor, 'motion', None)
        if (arena.geometry.id not in LOCAL_LEGACY_MAPS or not actor.alive
                or brain.get('generation') != actor.generation
                or actor.info.get('npc_template') or actor.blocked('move', now)
                or getattr(actor, 'channel', None) or getattr(actor, 'ready', None)
                or (motion and motion[3] > now and getattr(actor, 'motion_kind', 0) != 0)
                or brain.get('elite_native_goal')):
            return
        return legacy.evade(arena, actor, brain, now)
    if (actor.info.get('npc_template') or actor.blocked('move', now)
            or getattr(actor, 'channel', None) or getattr(actor, 'ready', None)
            or brain.get('elite_native_goal')):
        return
    shots = brain.get('bullets', ())
    if not shots:
        return
    pos = actor.position_at(now)
    speed = actor._speed(now)
    if speed <= 0:
        return
    stay_risk = _projectile_risk(pos, pos, shots, now, speed)
    if stay_risk < 18:
        return
    goal = brain.get('goal', pos)
    friends = [a.position_at(now) for a in arena.actors.values()
               if a is not actor and a.camp == actor.camp and a.alive
               and not a.info.get('npc_template')]
    candidates = []
    water = arena.water_rects(now)
    hold_center = brain.get('elite_hold_center')
    hold_radius = brain.get('elite_hold_radius', 0)
    # A healthy assigned capturer that has arrived should prefer a short
    # sidestep inside the public circle over repeatedly resetting capture.
    # Recovery, retreat and native kit movement still own their goals. Large
    # public-warning avoidance above deliberately keeps its survival priority.
    hold_flag = (arena.geometry.id in (7, 9, 10, 37, 170)
                 and brain.get('generation') == actor.generation
                 and brain.get('elite_task') == 'flag_hold'
                 and hold_center is not None and 0 < hold_radius <= 60
                 and math.dist(pos, hold_center) <= hold_radius
                 and _ratio(actor) >= .4
                 and not brain.get('repair_goal') and not brain.get('repair_box')
                 and now >= brain.get('elite_retreat_until', 0))
    safe_center = None
    if (arena.geometry.id in SURVIVAL_MAPS
            and now >= arena.pk['collapse_at'] - 5000):
        from death_mode import RADIUS, center
        safe_center = center(arena)
        safe_distance = math.dist(pos, safe_center)
    choices = [(dx, dy, 96) for dx, dy in legacy.DIRECTIONS[:8]]
    if hold_flag:
        choices = [(dx, dy, 48) for dx, dy in legacy.DIRECTIONS[:8]] + choices
    for dx, dy, radius in choices:
        norm = max(1.0, math.hypot(dx, dy))
        point = tuple(round(v) for v in (pos[0] + dx * radius / norm, pos[1] + dy * radius / norm))
        if arena.geometry.walk_end(pos, point, water) != point:
            continue
        # Evasion runs after the ordinary goal constraint. Do not dodge out
        # of the announced survival zone; if already outside, only consider
        # sidesteps that also make progress toward safety.
        if safe_center is not None:
            end_distance = math.dist(point, safe_center)
            if (end_distance > RADIUS
                    and (safe_distance <= RADIUS or end_distance >= safe_distance)):
                continue
        if any(math.dist(point, p) < min(68, math.dist(pos, p)) for p in friends):
            continue
        if (brain.get('elite_final_push') or hold_flag) and hold_center is not None and hold_radius:
            # Keep a final-push contributor or healthy capturer in its area.
            # If a native displacement took us out, only move back toward it.
            current_distance = math.dist(pos, hold_center)
            next_distance = math.dist(point, hold_center)
            if (next_distance > hold_radius
                    and (current_distance <= hold_radius or next_distance >= current_distance)):
                continue
        risk = _projectile_risk(pos, point, shots, now, speed)
        if risk >= stay_risk - 12:
            continue
        penalty = math.dist(point, goal) * .025
        if hold_center is not None and hold_radius:
            penalty += max(0, math.dist(point, hold_center) - hold_radius) * .35
        candidates.append((risk + penalty, math.dist(point, goal), point))
    if candidates:
        _set_goal(brain, min(candidates)[2])
        brain['repath_at'] = 0
