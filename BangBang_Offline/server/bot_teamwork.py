"""Elite V1 team orders, built only from friendly state and delayed reports.

This module chooses intentions, never actions or combat outcomes.  It does not
cast, move, read a hidden opponent's current state, consume combat RNG, or write
to SQLite.  The original bot/mode policies remain available independently.

The shared plan lives in ``pk['elite_teams']`` so a checkpoint freezes the same
orders and reports as the battle.  ``elite_plan_at`` and ``elite_order_until``
are absolute clocks; they are explicitly rebased by battle_persistence.
"""
from __future__ import annotations

from battle_participants import human, private
import math


VERSION = 4
PLAN_MS = 600
ORDER_MS = 1800
REACTION_MS = 180
MEMORY_MS = 1000
PK_MAPS = frozenset((1, 4, 17, 18, 19, 20, 21, 34, 35, 36))
FLAG_MAPS = frozenset((7, 9, 10, 37, 170))
BASE_MAPS = frozenset((12, 14, 50, 169))
DEATH_MAPS = frozenset((30, 40))
MAPS = PK_MAPS | FLAG_MAPS | BASE_MAPS | DEATH_MAPS | {70}

# Roles are decision hints, not stat modifiers.  A tank's native kit still
# chooses its real range, movement, recasts, resources and support abilities.
_SUPPORT = frozenset((10000002, 10000029, 10000031, 10000037, 10000054,
                     10000061, 10000065, 10000073, 10000080, 10000085,
                     10000107, 10000113))
_FRONTLINE = frozenset((10000003, 10000034, 10000036, 10000039, 10000040,
                       10000043, 10000046, 10000051, 10000056, 10000066,
                       10000067, 10000075, 10000082, 10000094, 10000097,
                       10000103, 10000109))
_ARTILLERY = frozenset((10000001, 10000033, 10000041, 10000050, 10000052,
                       10000058, 10000060, 10000063, 10000069, 10000084,
                       10000088, 10000089, 10000101, 10000106, 10000112))
_SKIRMISHER = frozenset((10000008, 10000030, 10000035, 10000044, 10000047,
                        10000048, 10000055, 10000070, 10000076, 10000077,
                        10000078, 10000081, 10000087, 10000093, 10000096,
                        10000099, 10000100, 10000104, 10000108, 10000114,
                        10000115))


def role_for(actor):
    tank = actor.info['tank_id']
    if tank in _SUPPORT:
        return 'support'
    if tank in _FRONTLINE:
        return 'frontline'
    if tank in _ARTILLERY:
        return 'artillery'
    if tank in _SKIRMISHER:
        return 'skirmisher'
    return 'fighter'


def _ratio(actor):
    return float(actor.hp / actor.max_hp) if actor.max_hp else 0.


def _eligible(actor, now):
    # The same native exclusions as flag/cart contribution, not a new rule.
    return (actor.alive and not actor.info.get('npc_template')
            and not actor.is_untargetable() and not actor.in_stasis()
            and 26 not in actor.buff_types(now))


def _members(arena, camp, now):
    from bot_policy import policy_for
    members = []
    for actor in arena.actors.values():
        if actor.camp != camp or not actor.alive or actor.info.get('npc_template'):
            continue
        members.append(dict(actor=actor, id=actor.id, generation=actor.generation,
                            pos=actor.position_at(now), hp=_ratio(actor),
                            role=role_for(actor), eligible=_eligible(actor, now),
                            recovering=bool(arena.bot_brains.get(actor.id, {}).get('repair_goal')),
                            controlled=not human(actor) and policy_for(arena, actor) == 'elite_v1'))
    return sorted(members, key=lambda m: m['id'])


def _mature(report, now):
    age = now - report.get('observed_at', now)
    return REACTION_MS <= age <= MEMORY_MS


def _reports(arena, members, previous, now):
    """Union mature teammate reports without leaking a fresh same-tick sample.

    A previous plan may contain the last mature sample while all current bot
    samples have just been refreshed.  Such memory expires after one second;
    it is never updated from an enemy actor, generation, HP or present pose.
    """
    reports = {}
    sources = [previous.get('contacts', ())]
    sources += [arena.bot_brains.get(m['id'], {}).get('observations', ()) for m in members]
    fields = ('id', 'generation', 'pos', 'velocity', 'hp', 'observed_at', 'robo',
              'objective', 'barrier', 'structure', 'bomb_cart', 'turret_rect',
              'elite_guarded', 'elite_shield', 'elite_control_ms', 'elite_range',
              'elite_tank_id')
    for observations in sources:
        for observation in observations:
            if not _mature(observation, now):
                continue
            if not all(k in observation for k in ('id', 'generation', 'pos', 'hp')):
                continue
            old = reports.get(observation['id'])
            if old is not None and old['observed_at'] >= observation['observed_at']:
                continue
            reports[observation['id']] = {k: observation[k] for k in fields if k in observation}
    return [reports[key] for key in sorted(reports)]


def _unit(start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max(1., math.hypot(dx, dy))
    return dx / length, dy / length


def _offset(center, facing, forward=0., lateral=0.):
    dx, dy = facing
    return center[0] + dx * forward - dy * lateral, center[1] + dy * forward + dx * lateral


def _centroid(members):
    return (sum(m['pos'][0] for m in members) / len(members),
            sum(m['pos'][1] for m in members) / len(members))


def _formation_core(members):
    """The largest ready cluster leads; a healing straggler is not a rally point.

    This uses communicated friendly state only. There is no assumption that
    every living teammate is available for a five-body fight at the centroid.
    """
    ready = [m for m in members if not m.get('recovering')] or list(members)
    anchor = min(ready, key=lambda m: (
        -sum(.4+.6*n['hp'] for n in ready if math.dist(m['pos'],n['pos']) <= 480),
        m['role'] != 'frontline', -m['hp'], m['id']))
    return [m for m in ready if math.dist(m['pos'], anchor['pos']) <= 480]


def _navigation(arena):
    if not hasattr(arena, 'navigation'):
        from bot_ai import Navigation
        arena.navigation = Navigation(arena.geometry)
    return arena.navigation


def _goal(arena, member, wanted, reserved, *, center=None, radius=None,
          strict_spacing=False):
    """Prefer reachable legal offsets, but retain a blocked objective's intent.

    If a destructible wall separates the objective, returning the nearest
    *reachable* edge would make walk() stop forever without noting blockage.
    Therefore a legal cell on the objective side remains a clear-path goal
    when no connected cell contributes; native walk still must open the wall.
    """
    wanted = arena.geometry.clamp_tank_position(wanted)
    nav = _navigation(arena)
    source = nav.nearest(member['pos'])
    reachable = nav.reachable(source) if source is not None else ()
    base = tuple(round((v - 12) / 24) * 24 + 12 for v in wanted)
    steps = 3
    if center is not None and radius is not None:
        base = tuple(round((v - 12) / 24) * 24 + 12 for v in center)
        steps = min(12, math.ceil(radius / 24) + 1)
    cells = [(base[0] + dx * 24, base[1] + dy * 24)
             for dx in range(-steps, steps + 1) for dy in range(-steps, steps + 1)]
    if center is not None and radius is not None:
        cells = [p for p in cells if math.dist(p, center) <= radius]
    def cost(point):
        return (math.dist(point, wanted)
                + sum(max(0., 64 - math.dist(point, q)) * 8 for q in reserved), point)

    def choose(candidates):
        first_legal = None
        for point in sorted(candidates, key=cost):
            if strict_spacing and any(math.dist(point, q) < 64 for q in reserved):
                continue
            if not nav.clear(point, point):
                continue
            if first_legal is None:
                first_legal = point
            if point in reachable:
                return point
        return first_legal

    goal = choose(cells)
    if goal is not None or strict_spacing:
        return goal
    if center is None or radius is None:
        # Broad solid blocks (notably map 4 ice) can cover all 49 local cells.
        # Never send the original illegal point back as a formation goal.
        wide = ((base[0] + dx*24, base[1] + dy*24)
                for dx in range(-12, 13) for dy in range(-12, 13))
        goal = choose(wide)
        if goal is not None:
            return goal
    # An obstructed contribution circle may require an approach outside it.
    # Strict flag holders instead return None above and become covering bots.
    goal = choose(reachable)
    if goal is not None:
        return goal
    return member['pos'] if nav.clear(member['pos'], member['pos']) else None


def _order(arena, result, member, task, wanted, group, *, stance='engage',
           radius=600., center=None, hold_radius=None, rationale='',
           avoid=(), strict_spacing=False, **extra):
    reserved = list(avoid) + [o['goal'] for o in result.values() if o['group'] == group]
    goal = _goal(arena, member, wanted, reserved, center=center,
                 radius=(hold_radius - 8 if hold_radius is not None else None),
                 strict_spacing=strict_spacing)
    if goal is None:
        return False
    result[member['id']] = dict(task=task, goal=goal, role=member['role'],
                                focus=None, focus_generation=None, observed_at=0,
                                stance=stance, group=group, target_radius=radius,
                                rationale=rationale, **extra)
    if center is not None:
        result[member['id']]['objective_center'] = tuple(center)
    if hold_radius is not None:
        result[member['id']]['hold_radius'] = hold_radius
    return True


def _pick(available, count, point, group, previous, now, *, holders=False):
    old_orders = previous.get('orders', {})
    sticky = now < previous.get('elite_order_until', 0)
    def cost(member):
        old = old_orders.get(member['id'], {})
        role = {'frontline': -100, 'fighter': 0, 'skirmisher': 20,
                'support': 110, 'artillery': 140}[member['role']] if holders else 0
        health = max(0., .6 - member['hp']) * 550
        return (math.dist(member['pos'], point) + role + health
                + (1800 if holders and not member['eligible'] else 0)
                + (1800 if holders and member.get('recovering') else 0)
                - (170 if sticky and old.get('group') == group else 0), member['id'])
    selected = sorted(available, key=cost)[:max(0, count)]
    chosen = {m['id'] for m in selected}
    available[:] = [m for m in available if m['id'] not in chosen]
    return selected


def _uncontrolled_on(members, point, radius):
    # The human/legacy ally is credited for actual contribution, never ordered
    # to move and never assumed to hold a point merely because they are alive.
    return [m for m in members if not m['controlled'] and m['eligible']
            and math.dist(m['pos'], point) <= radius]


def _tanks(reports):
    return [s for s in reports if not s.get('objective', s.get('robo', False))]


def _capture_body(sample):
    """Known visible summons fight, but cannot contribute to native circles.

    The PRO observer already records a visible NPC's elite_tank_id as None.
    Preserve that aged public classification rather than querying its live
    actor. Older checkpoint samples without the field stay conservative.
    Do not remove summons from combat threats/focus: they still deal damage.
    """
    return sample.get('elite_tank_id', 0) is not None


def _published_flag_capture(flag):
    """Use the last S1565 publication, never its private sub-second timer.

    Native occupy_rules.tick stores this exact wire tuple when broadcasting
    its public signed progress. The client has no indication during the first
    999 ms; raw capture_camp/capture_started_at are deliberately not read.
    A visible ring reveals an objective under capture, not enemy IDs/counts.
    """
    state = flag.get('wire')
    if (not state or len(state) != 5 or state[0] != flag['index']
            or state[1] != flag['camp'] or state[2] or not state[3]):
        return 0
    return 1 if state[3] < 0 else 2


def _flag_finish_holder(arena, camp, bots, flags, previous):
    """Keep one real, healthy holder when its public point can close the game.

    Six ordinary score pulses bound this commitment. If the other camp's
    currently owned points would finish sooner, ordinary contest priorities
    remain in charge. This reads public scores/ownership and friendly state,
    never private capture clocks or unseen enemy state. A native displacement
    may briefly move an established holder outside the circle; allow its
    short return, while healing, death and low HP release it immediately.
    """
    from occupy_rules import WIN_SCORE
    remaining = WIN_SCORE - arena.pk['scores'][camp]
    if remaining <= 0:
        return None
    opposing = [flag for flag in flags if flag['camp'] == 3-camp]
    enemy_rate = sum(flag.get('score', 10) for flag in opposing)
    if len(flags) == 3 and len(opposing) == 3:
        enemy_rate *= 2  # The native three-point bonus is public ownership.
    enemy_ticks = (math.ceil((WIN_SCORE-arena.pk['scores'][3-camp])/enemy_rate)
                   if enemy_rate else float('inf'))
    options = []
    old_orders = previous.get('orders', {})
    for flag in flags:
        score = flag.get('score', 10)
        if flag['camp'] != camp or score <= 0:
            continue
        ticks = math.ceil(remaining/score)
        if ticks > 6 or ticks > enemy_ticks:
            continue
        for member in bots:
            if not member['eligible'] or member.get('recovering') or member['hp'] < .4:
                continue
            distance = math.dist(member['pos'], flag['position'])
            old = old_orders.get(member['id'], {})
            returning = (old.get('flag_finish_guard') and old.get('flag_index') == flag['index']
                         and old.get('member_generation') == member['generation'] and distance <= 180)
            if distance > 60 and not returning:
                continue
            options.append(((ticks, distance > 60, not returning, -member['hp'],
                             distance, flag['index'], member['id']), flag, member))
    if not options:
        return None
    _, flag, member = min(options, key=lambda option: option[0])
    return flag, member


def _flag_plan(arena, camp, members, bots, reports, previous, now):
    result = {}
    flags = [f for f in arena.pk.get('flags', ()) if not f.get('locked')]
    if not flags:
        return result
    enemies = _tanks(reports)
    available = list(bots)
    groups = {}
    old_orders = previous.get('orders', {})
    by_index = {f['index']: f for f in flags}
    alerts = {f['index'] for f in flags if f['camp'] == camp
              and _published_flag_capture(f) == 3-camp}
    responding = set()
    finish = _flag_finish_holder(arena, camp, bots, flags, previous)
    if finish is not None:
        flag, member = finish
        groups[flag['index']] = [member]
        available.remove(member)
    # A new observation is a reason to update a fight, not to send an already
    # travelling capturer across the entire map every 600ms.  Each assignment
    # has its own bounded travel/capture lease.  The reused clock field is in
    # battle_persistence.TIMES even when nested in an order.  Death/recovery,
    # completion and an observed unviable fight release it immediately.
    # This does not make a holder invulnerable or override its native kit.
    def continuation(member):
        old = old_orders.get(member['id'], {})
        index = old.get('flag_index')
        flag = by_index.get(index)
        if (flag is None or old.get('member_generation') != member['generation']
                or member.get('recovering') or not member['eligible']):
            return None
        close = [s for s in enemies if math.dist(s['pos'], flag['position']) <= 360]
        returning = (old.get('flag_backcap') and now < old.get('elite_order_until', 0)
                     and math.dist(member['pos'], flag['position']) > 60)
        if flag['camp'] == camp and not close and index not in alerts and not returning:
            return None  # Captured empty flags keep scoring without a body.
        if (len(flags) > 1 and len(close) >= len(bots)
                and any(f['camp'] != camp and not any(math.dist(s['pos'], f['position']) <= 360
                        for s in enemies) for f in flags if f is not flag)):
            return None
        if now < old.get('elite_order_until', 0):
            return flag
        return None

    for member in list(available):
        flag = continuation(member)
        if flag is not None:
            groups.setdefault(flag['index'], []).append(member)
            available.remove(member)
            if old_orders.get(member['id'], {}).get('flag_backcap'):
                responding.add(member['id'])
    tasks = []
    for flag in flags:
        center = flag['position']
        close = [s for s in enemies if math.dist(s['pos'], center) <= 300]
        on = sum(_capture_body(s) and math.dist(s['pos'], center) <= 60 for s in close)
        actual = len(_uncontrolled_on(members, center, 60))
        needed = max(0, on + 1 - actual) if flag['camp'] != camp or close else 0
        if not needed and not close and flag['camp'] == camp:
            continue
        size = max(needed, min(3, len(close) + 1))
        nearest = min(math.dist(m['pos'], center) for m in available) if available else 0
        priority = (flag.get('score', 10) * 16 - nearest * .35
                    + (180 if flag['camp'] == camp and close else 120 if flag['camp'] not in (0, camp) else 0)
                    - (650 if len(close) >= len(bots) and len(flags) > 1 else 0))
        # Deny an imminent winning score instead of idly defending a quiet flag.
        if flag['camp'] not in (0, camp) and arena.pk['scores'][3-camp] >= 900:
            priority += 450
        tasks.append((priority, flag['index'], flag, size))
    for _, _, flag, size in sorted(tasks, key=lambda item: (-item[0], item[1])):
        if not available:
            break
        # Avoid trickling one tank into a known larger squad when an undefended
        # capture exists.  The leftover squad will cover rather than suicide.
        center = flag['position']
        hostile = sum(math.dist(s['pos'], center) <= 300 for s in enemies)
        other_open = any(f['index'] != flag['index'] and f['camp'] != camp
                         and not any(math.dist(s['pos'], f['position']) <= 300 for s in enemies)
                         for f in flags)
        if len(available) <= hostile and other_open:
            continue
        group = 'flag:' + str(flag['index'])
        count = max(0, min(size-len(groups.get(flag['index'], ())), len(available)))
        groups.setdefault(flag['index'], []).extend(_pick(available, count, center,
                                      group, previous, now, holders=True))
    for member in list(available):
        # Reinforce the nearest actionable group; retain a two-point spread
        # when the team already owns multiple safe objectives.
        flag = min(flags, key=lambda f: (
            math.dist(member['pos'], f['position'])
            + len(groups.get(f['index'], ())) * 230
            + (300 if f['camp'] == camp and not any(math.dist(s['pos'], f['position']) <= 360 for s in enemies) else 0)
            - f.get('score', 10) * 9, f['index']))
        groups.setdefault(flag['index'], []).append(member)

    def capture_need(flag):
        center = flag['position']
        close = [s for s in enemies if math.dist(s['pos'], center) <= 480]
        if flag['camp'] == camp and not close and flag['index'] not in alerts:
            if finish is not None and flag['index'] == finish[0]['index']:
                return max(0, 1-len(_uncontrolled_on(members, center, 60)))
            # An already dispatched responder finishes its bounded trip even
            # if a public progress pulse disappears between team replans.
            if any(m['id'] in responding for m in groups.get(flag['index'], ())):
                return 1
            return 0
        on = sum(_capture_body(s) and math.dist(s['pos'], center) <= 60 for s in close)
        return max(0, min(4, on + 1) - len(_uncontrolled_on(members, center, 60)))

    def holder_key(member, flag):
        guarding = (finish is not None and flag['index'] == finish[0]['index']
                    and member['id'] == finish[1]['id'])
        return (not guarding, math.dist(member['pos'], flag['position']) > 60,
                member['id'] not in responding, member['hp'] < .4,
                member['role'] not in ('frontline', 'fighter'),
                math.dist(member['pos'], flag['position']), member['id'])

    # Repair travel is owned by the native individual controller. A healing
    # member cannot fill a promised capture slot, even when its old assignment
    # is sticky. Borrow spare ready cover from another allocated group, while
    # preserving that group's observed majority. Never reopen a deliberately
    # skipped enemy stack or leave another flag without its own needed holder.
    for flag in flags:
        squad = groups.get(flag['index'], [])
        if not squad or not any(m.get('recovering') for m in squad):
            continue
        ready = [m for m in squad if m['eligible'] and not m.get('recovering')]
        deficit = capture_need(flag) - len(ready)
        while deficit > 0:
            spares = []
            for donor in flags:
                if donor['index'] == flag['index']:
                    continue
                donor_ready = sorted((m for m in groups.get(donor['index'], [])
                                      if m['eligible'] and not m.get('recovering')),
                                     key=lambda m: holder_key(m, donor))
                spares.extend((m, donor['index']) for m in donor_ready[capture_need(donor):])
            if not spares:
                break
            member, donor_index = min(spares, key=lambda item: (
                math.dist(item[0]['pos'], flag['position']), -item[0]['hp'], item[0]['id']))
            groups[donor_index].remove(member)
            squad.append(member)
            deficit -= 1

    # A public backcap invalidates a spare's ordinary travel lease. Send at
    # most one ready responder, preserving each donor's required holders and
    # urgent defense. Never infer a hidden attacker location beyond the flag.
    for index in sorted(alerts):
        flag = by_index[index]
        squad = groups.setdefault(index, [])
        if any(m['id'] in responding for m in squad):
            continue
        options = [(m, index) for m in squad if m['eligible']
                   and not m.get('recovering') and m['hp'] >= .4]
        for donor in flags:
            donor_index = donor['index']
            if (donor_index == index or donor_index in alerts
                    or (donor['camp'] != camp and arena.pk['scores'][3-camp] >= 900)):
                continue
            ready = sorted((m for m in groups.get(donor_index, ()) if m['eligible']
                            and not m.get('recovering')), key=lambda m: holder_key(m, donor))
            close = sum(math.dist(s['pos'], donor['position']) <= 480 for s in enemies)
            preserve = max(capture_need(donor), min(3, close+1) if close else 0)
            options.extend((m, donor_index) for m in ready[preserve:]
                           if m['hp'] >= .4 and m['id'] not in responding)
        if not options:
            continue
        member, donor_index = min(options, key=lambda item: (
            math.dist(item[0]['pos'], flag['position']), -item[0]['hp'], item[0]['id']))
        if donor_index != index:
            groups[donor_index].remove(member)
            squad.append(member)
        responding.add(member['id'])
    for flag in flags:
        squad = groups.get(flag['index'], [])
        if not squad:
            continue
        center = flag['position']
        group = 'flag:' + str(flag['index'])
        close = [s for s in enemies if math.dist(s['pos'], center) <= 480]
        actual = _uncontrolled_on(members, center, 60)
        need = capture_need(flag)
        candidates = sorted((m for m in squad if m['eligible'] and not m.get('recovering')),
                            key=lambda m: holder_key(m, flag))[:need]
        holders = []
        slots = [(-48, 0), (48, 0), (0, -48), (0, 48)] if need + len(actual) > 1 else [(0, 0)]
        for member in candidates:
            offset = min(slots, key=lambda d: (sum(max(0., 64-math.dist((center[0]+d[0], center[1]+d[1]), a['pos'])) for a in actual),
                                               math.dist(member['pos'], (center[0]+d[0], center[1]+d[1])), d))
            slots.remove(offset)
            wanted = center[0] + offset[0], center[1] + offset[1]
            if _order(arena, result, member, 'flag_hold', wanted, group, stance='hold',
                      radius=300, center=center, hold_radius=60,
                      avoid=[m['pos'] for m in actual], strict_spacing=True,
                      rationale='Maintain capture majority; human contribution counts only on point.'):
                holders.append(member)
        # Lease continuation inserts members before new allocations. Reserve
        # covering lanes by stable identity, not by that incidental insertion
        # order, or otherwise stationary/recovering bots swap left/right.
        cover = sorted((m for m in squad if m not in holders), key=lambda m:m['id'])
        approach = (min(close, key=lambda s: (math.dist(s['pos'], center), s['id']))['pos']
                    if close else arena.geometry.spawn(3-camp))
        facing = _unit(center, approach)
        for i, member in enumerate(cover):
            forward = {'frontline': 150, 'fighter': 75, 'skirmisher': 100,
                       'support': -100, 'artillery': -150}[member['role']]
            wanted = _offset(center, facing, forward, (i-(len(cover)-1)/2)*96)
            _order(arena, result, member, 'flag_cover', wanted, group,
                   stance='defend' if flag['camp'] == camp else 'engage', radius=480,
                   center=center, avoid=[m['pos'] for m in actual],
                   rationale='Screen the holder, focus nearby threats, rotate between flags.')
        for member in squad:
            if member['id'] not in result:
                continue
            old = old_orders.get(member['id'], {})
            same = (old.get('flag_index') == flag['index']
                    and old.get('member_generation') == member['generation'])
            deadline = old.get('elite_order_until', 0) if same else 0
            if deadline <= now:
                speed = max(90., float(member['actor'].stats.get('iSpeed', 140)))
                travel = math.dist(member['pos'], center) / speed * 1000
                deadline = now + round(min(15000, max(4500, travel + flag.get('capture_ms', 2000) + 1800)))
            result[member['id']].update(flag_index=flag['index'], member_generation=member['generation'],
                                        elite_order_until=deadline,
                                        flag_backcap=member['id'] in responding,
                                        flag_finish_guard=(finish is not None
                                            and member['id'] == finish[1]['id']
                                            and flag['index'] == finish[0]['index']))
    return result


def _base_damage_alarm(home, enemy_home, previous, now, *, uncovered):
    """Remember a public home-HP drop, without inventing an enemy contact.

    A squad beyond sight of its own home can otherwise keep pushing while
    that publicly visible objective is being destroyed.  The alarm only
    requests a return to the known home position; ordinary aged sightings
    still decide whom to attack. Once threats are observed, normal defense
    takes over. Preserve an advantageous public home-health race instead of
    pulling an attacking squad back on every harmless damage pulse. Reuse
    a checkpoint-rebased deadline name inside this public-objective memory.
    """
    old = previous.get('base_watch') or {}
    same = (old.get('id') == home.id
            and old.get('generation') == home.generation)
    hp = float(home.hp)
    deadline = old.get('elite_order_until', 0) if same else 0
    emergency = uncovered and _ratio(home) < _ratio(enemy_home)
    if not emergency:
        deadline = 0
    elif same and hp < old.get('hp', hp) - 1:
        deadline = now + 8000
    previous['base_watch'] = dict(id=home.id, generation=home.generation,
                                  hp=hp, elite_order_until=deadline)
    return home.alive and now < deadline


def _base_plan(arena, camp, members, bots, reports, previous, now):
    from base_mode import firing_position
    homes = {a.camp: a for a in arena.actors.values() if a.info.get('base')}
    if camp not in homes or 3-camp not in homes:
        return {}
    home, enemy_home = homes[camp], homes[3-camp]
    threats = [s for s in reports if not s.get('structure') and not s.get('barrier')
               and math.dist(s['pos'], home.position) < 660]
    available = list(bots)
    result = {}
    damaged = _base_damage_alarm(home, enemy_home, previous, now, uncovered=not threats)
    if threats or damaged:
        critical = _ratio(home) < .4 or any(math.dist(s['pos'], home.position) < 360 for s in threats)
        count = len(threats) + 1 if critical else min(3, len(threats)+1)
        if damaged:
            # A bounded responding squad leaves attackers on the other side;
            # do not infer an unseen enemy headcount from objective damage.
            count = max(count, 3 if critical else 2)
        count = min(len(available), count)
        defenders = _pick(available, count, home.position, 'base:defend', previous, now, holders=True)
        approach = (min(threats, key=lambda s: (math.dist(s['pos'], home.position), s['hp'], s['id']))['pos']
                    if threats else enemy_home.position)
        facing = _unit(home.position, approach)
        for i, member in enumerate(defenders):
            forward = 250 if member['role'] == 'frontline' else 150
            wanted = _offset(home.position, facing, forward, (i-(len(defenders)-1)/2)*96)
            _order(arena, result, member, 'base_defend', wanted, 'base:defend', stance='defend',
                   radius=720, center=home.position,
                   rationale='Respond to observed home threats or public home damage; acquire targets through normal sightings.')
    structures = [a for a in arena.actors.values() if a.camp == 3-camp and a.alive
                  and (a.info.get('base') or a.info.get('map_turret')) and not a.turret_locked()]
    structures.sort(key=lambda a: (0 if a.info.get('base') else 1 if a.id in enemy_home.unlocked_by else 2,
                                   math.dist(_centroid(available or bots), a.position), a.id))
    if not structures:
        structures = [enemy_home]
    target = structures[0]
    # Public tower availability is not permission to shoot a hidden mobile tank.
    if available:
        leader = max(available, key=lambda m: (m['role'] == 'frontline', m['hp'], -m['id']))
        for structure in structures:
            if firing_position(arena, leader['actor'], structure, now) is not None:
                target = structure
                break
    for member in available:
        point = firing_position(arena, member['actor'], target, now)
        task = 'base_push' if point is not None else 'clear_path'
        _order(arena, result, member, task, point or target.position, 'base:push',
               radius=600, center=target.position, siege_target=target.id,
               rationale='Push exposed home, then unlocking tower; preserve native siege/firing rules.')
    return result


def _cart_intercept_center(cart, member, now):
    """Aim ahead on the public route, never at a future opponent tank pose.

    A distant interceptor cannot catch a moving cart by repeatedly walking to
    its old segment.  Estimate a bounded rendezvous using only our current
    native walking speed and the cart's public route/current speed.  Replans
    update this estimate when the cart slows, stops or turns.  Native movement
    still owns walls, barrier clearing, CC, combat and the final circle.
    """
    center = cart.position_at(now)
    speed = float(getattr(cart, 'cart_speed', 0))
    if (not cart.alive or speed <= 0 or member.get('recovering')
            or math.dist(member['pos'], center) <= 400):
        return center, None
    own_speed = max(1., member['actor']._speed(now))

    def future(seconds):
        remaining = speed * seconds
        point = center
        for endpoint in cart.route[cart.route_index:]:
            length = math.dist(point, endpoint)
            if length >= remaining and length > 0:
                ratio = remaining / length
                return (point[0] + (endpoint[0]-point[0])*ratio,
                        point[1] + (endpoint[1]-point[1])*ratio), endpoint
            remaining -= length
            point = endpoint
        return point, point

    seconds = min(10., math.dist(member['pos'], center) / own_speed)
    for _ in range(3):
        point, endpoint = future(seconds)
        seconds = min(10., math.dist(member['pos'], point) / own_speed)
    return future(seconds)


def _route_point(cart, member, slot, count, pushing, arena, result, group, task, now):
    center = cart.position_at(now) if cart.alive else cart.spawn
    end = cart.route[min(cart.route_index, len(cart.route)-1)] if cart.route else center
    cart_center = center
    if not pushing and cart.info.get('bomb_cart') and cart.alive:
        center, next_point = _cart_intercept_center(cart, member, now)
        if next_point is not None:
            end = next_point
    facing = _unit(center, end)
    side = (slot-(count-1)/2)*72
    wanted = _offset(center, facing, 48 if pushing else 96, side)
    radius = 200 if cart.info.get('bomb_cart') else 240
    _order(arena, result, member, task, wanted, group,
           stance='hold' if pushing else 'defend', radius=400 if radius == 240 else 360,
           center=center, hold_radius=radius,
           rationale='Keep contributing bodies in the native circle; fight escorts before chasing.',
           route_intercept=center != cart_center, cart_center=cart_center)


def _escort_continuity(cart, bots, previous, now, urgent):
    """Keep nearby holders through one brief native loss of contribution.

    A friendly stealth/phase transition must not send a healthy escort across
    the map and recall a distant fighter for a five-second absence. Retained
    members are defenders, never credited as eligible cart contributors; the
    ordinary selection still supplies eligible backups. This finite order
    uses the already checkpoint-rebased elite_order_until clock.
    """
    if not cart.alive or urgent:
        return {}
    center = cart.position_at(now)
    old_orders = previous.get('orders', {})
    held = {}
    for member in bots:
        old = old_orders.get(member['id'], {})
        if (member['eligible'] or member['hp'] < .6 or member.get('recovering')
                or math.dist(member['pos'], center) > 200
                or old.get('group') != 'bomb:escort'
                or old.get('cart_generation') != cart.generation
                or old.get('member_generation') != member['generation']):
            continue
        if old.get('escort_continuity'):
            deadline = old.get('elite_order_until', 0)
            if now >= deadline:
                continue
        elif old.get('escort_eligible') is True:
            deadline = now+6000
        else:
            continue
        held[member['id']] = deadline
    return held


def _escort_plan(arena, camp, members, bots, reports, previous, now):
    from escort_mode import progress
    carts = {a.camp: a for a in arena.actors.values() if a.info.get('bomb_cart')}
    if camp not in carts or 3-camp not in carts:
        return {}
    own, enemy = carts[camp], carts[3-camp]
    own_pos = own.position_at(now) if own.alive else own.spawn
    enemy_pos = enemy.position_at(now) if enemy.alive else enemy.spawn
    enemies = _tanks(reports)
    # The native cart contests only real visible tank bodies. Summons still
    # remain combat targets/threats, but cannot demand phantom escort slots.
    pressure = sum(_capture_body(s) and math.dist(s['pos'], own_pos) <= 300 for s in enemies)
    guards = sum(_capture_body(s) and math.dist(s['pos'], enemy_pos) <= 280 for s in enemies)
    own_progress, enemy_progress = progress(own, now), progress(enemy, now)
    actual = len(_uncontrolled_on(members, own_pos, 200))
    count = max(1, 3-actual, pressure+1-actual)
    urgent = enemy_progress > own_progress+.15 or enemy_progress > .8
    if urgent:
        count = max(1, min(count, len(bots)-max(2, guards)))
    if own_progress > .87:
        # A nearly finished cart needs an actual finisher even if the other
        # cart is a little ahead. Swapping four escorts into interception at
        # 98% abandons an attainable win and repeatedly changes their route.
        count = max(count, len(bots)-1)
    if pressure >= 3:
        majority = max(count, min(len(bots), pressure+1-actual))
        count = len(bots)
    if not enemy.alive:
        count = len(bots)
    if not own.alive:
        count = 0
    continuity = _escort_continuity(own, bots, previous, now, urgent)
    retained = [member for member in bots if member['id'] in continuity]
    available = [member for member in bots if member['id'] not in continuity]
    interceptor = None
    if pressure >= 3 and own.alive and enemy.alive:
        # Preserve an existing contributor at the opposing cart only when
        # enough eligible, nonrecovering backups can supply our requested majority.
        # A distant respawn or a recovering/ineligible body is not that spare.
        local = [member for member in available
                 if member['eligible'] and not member.get('recovering')
                 and math.dist(member['pos'], enemy_pos) <= 200
                 and previous.get('orders', {}).get(member['id'], {}).get('group') == 'bomb:intercept']
        if local and sum(member['eligible'] and not member.get('recovering') for member in available) > majority:
            interceptor = min(local, key=lambda member: (math.dist(member['pos'], enemy_pos), member['id']))
            available.remove(interceptor)
            count = majority
    # Ineligible retained defenders never satisfy the requested contributing
    # squad size. Bring eligible backups while preserving their short lease.
    escorts = retained + _pick(available, min(len(available), count), own_pos,
                               'bomb:escort', previous, now, holders=True)
    if interceptor is not None:
        available.append(interceptor)
    # _pick ranks by current distance to select a squad, not a formation lane.
    # Reusing that changing rank as left/centre/right makes the same escorts
    # cross through one another each plan. Keep lanes stable until membership
    # actually changes; routes still rotate the whole formation at corners.
    escorts.sort(key=lambda member: member['id'])
    available.sort(key=lambda member: member['id'])
    result = {}
    for i, member in enumerate(escorts):
        _route_point(own, member, i, len(escorts), True, arena, result, 'bomb:escort', 'bomb_escort', now)
        if member['id'] in result:
            result[member['id']].update(cart_generation=own.generation,
                member_generation=member['generation'], escort_eligible=member['eligible'])
            if member['id'] in continuity:
                result[member['id']].update(escort_continuity=True,
                    elite_order_until=continuity[member['id']])
    for i, member in enumerate(available):
        _route_point(enemy, member, i, len(available), False, arena, result, 'bomb:intercept', 'bomb_intercept', now)
    if own.alive and own_progress > .87:
        # Commit only already-present, healthy contributors, not a distant
        # healing bot nominated as a phantom carrier. Opposition is estimated
        # solely from aged team sightings; never call cart.nearby() here.
        on = sum(_capture_body(s) and math.dist(s['pos'], own_pos) <= 200 for s in enemies)
        need = max(0, on + 1 - actual)
        contributors = [m for m in escorts if m['eligible'] and m['hp'] >= .40
                        and not m.get('recovering')
                        and math.dist(m['pos'], own_pos) <= 200]
        contributors.sort(key=lambda m: (m['id'] not in getattr(own, 'herders', ()),
                                         math.dist(m['pos'], own_pos), -m['hp'], m['id']))
        for member in contributors[:need]:
            if member['id'] in result:
                result[member['id']]['final_push'] = True
    return result


def _cow_plan(arena, camp, members, bots, reports, previous, now):
    cows = {a.camp: a for a in arena.actors.values() if a.info.get('cow_object') and a.route}
    if camp not in cows or 3-camp not in cows:
        return {}
    own, enemy = cows[camp], cows[3-camp]
    offense = enemy.position_at(now) if enemy.alive else enemy.spawn
    defense = own.position_at(now) if own.alive else own.spawn
    threats = sum(math.dist(s['pos'], defense) <= 400 for s in _tanks(reports))
    # Movement of the scored objective is public, not an enemy-position query.
    stealing = bool(own.alive and (own.motion or threats))
    available = list(bots)
    actual = len(_uncontrolled_on(members, offense, 240))
    count = max(1, 2-actual)
    if not stealing:
        count = max(count, len(bots)-1)
    if not enemy.alive:
        count = 0
    escorts = _pick(available, min(len(bots), count), offense, 'cow:escort', previous, now, holders=True)
    result = {}
    for i, member in enumerate(escorts):
        _route_point(enemy, member, i, len(escorts), True, arena, result, 'cow:escort', 'escort', now)
    if stealing or not enemy.alive:
        for i, member in enumerate(available):
            _route_point(own, member, i, len(available), False, arena, result, 'cow:defend', 'defend', now)
    elif available:
        # Extra firepower screens the escort rather than idling at the own cow.
        for i, member in enumerate(available, len(escorts)):
            _route_point(enemy, member, i, len(bots), True, arena, result, 'cow:escort', 'escort', now)
    return result


def _survival_plan(arena, camp, members, bots, reports, previous, now):
    center = (1092, 840) if arena.geometry.id == 40 else (1092, 852)
    enemies = _tanks(reports)
    towards = (min(enemies, key=lambda s: (math.dist(s['pos'], center), s['id']))['pos']
               if enemies else arena.geometry.spawn(3-camp))
    facing = _unit(center, towards)
    # Enemy alive counts are public S1736 scoreboard state.  No enemy pose, HP,
    # cooldown or future event is read to decide whether to conserve the team.
    alive = {c: sum(arena.actors[i].alive and arena.actors[i].camp == c
                    for i in arena.pk.get('stats', ()) if i in arena.actors) for c in (1, 2)}
    conservative = alive[camp] < alive[3-camp]
    warned = bool(arena.pk.get('collapse_warned') or arena.pk.get('collapse_started'))
    result = {}
    ordered = sorted(bots, key=lambda m: (m['role'] != 'frontline', m['role'] == 'support', m['id']))
    for i, member in enumerate(ordered):
        forward = {'frontline': 105, 'fighter': 35, 'skirmisher': 60,
                   'support': -100, 'artillery': -120}[member['role']]
        if conservative:
            forward -= 45
        lateral = (i-(len(ordered)-1)/2)*70
        point = _offset(center, facing, forward, lateral)
        # Before the public collapse warning, retain the native kit's combat
        # range instead of leashing a ranged tank back into the central fight.
        # The warned/active collapse still uses the original survival orders.
        _order(arena, result, member, 'survive' if warned else 'skirmish', point, 'survive:team',
               stance='regroup' if conservative else 'hold', radius=450 if warned else 720,
               center=center, hold_radius=250 if warned else 310,
               rationale='One life: meet inside the safe area, protect teammates, do not trickle after deaths.')
    return result


def _pk_plan(arena, camp, members, bots, reports, previous, now):
    result = {}
    available = list(bots)
    enemies = _tanks(reports)
    team_center = _centroid(_formation_core(bots))
    # Feed a small objective squad only when no nearby tank fight needs it.
    nearby_fight = any(math.dist(s['pos'], team_center) < 700 for s in enemies)
    if not nearby_fight and arena.geometry.id in (1, 18, 21):
        objective = None
        if arena.geometry.id == 18:
            target = next((a for a in arena.actors.values() if a.info.get('totem') and a.camp == 3-camp and a.alive), None)
            if target is not None:
                objective = ('totem', target.spawn)
        elif arena.geometry.id == 21:
            from lightning_map import goal
            objective = goal(arena, bots[0]['actor'], now)
        else:
            quest = arena.pk.get('maya_quest', {})
            if quest.get('announced') and not quest.get('finished'):
                hunting = quest.get('hunter') == camp
                chief = next((a for a in arena.actors.values() if a.info.get('chieftain')
                              and a.camp == (3-camp if hunting else camp)), None)
                if chief is not None:
                    seen = next((s for s in reports if s['id'] == chief.id), None)
                    point = (seen['pos'] if seen else chief.spawn) if hunting else chief.position_at(now)
                    objective = ('maya_quest', point)
        if objective is not None:
            count = 1 if len(bots) < 4 else 2
            squad = _pick(available, count, objective[1], 'pk:objective', previous, now)
            for i, member in enumerate(squad):
                facing = _unit(objective[1], arena.geometry.spawn(3-camp))
                point = _offset(objective[1], facing, -120, (i-(len(squad)-1)/2)*96)
                _order(arena, result, member, objective[0], point, 'pk:objective',
                       radius=600, center=objective[1], rationale='Secure a public scoring/buff objective with a small squad.')
    if not available:
        return result
    core = _formation_core(available)
    team_center = _centroid(core)
    near = [s for s in enemies if math.dist(s['pos'], team_center) < 1100]
    if near:
        target = min(near, key=lambda s: (math.dist(s['pos'], team_center)+s['hp']*300, s['id']))
        facing = _unit(team_center, target['pos'])
        # Meet at combat range together, not on the enemy's exact body.
        center = _offset(target['pos'], facing, -280)
    else:
        start, end = arena.geometry.spawn(camp), arena.geometry.spawn(3-camp)
        stage = previous.get('advance', 0)
        fraction = (.50, .70, .86)[min(2, stage)]
        center = (start[0]+(end[0]-start[0])*fraction, start[1]+(end[1]-start[1])*fraction)
        if math.dist(team_center, center) < 180:
            previous['advance'] = min(2, stage+1)
        facing = _unit(start, end)
    spread = max(math.dist(m['pos'], team_center) for m in available)
    separated = len(available) > 1 and spread > 540 and not any(s['hp'] < .25 for s in near)
    if separated and not near:
        # A returning bot rejoins a nearby living squad; an idle human is not
        # its leader and cannot indefinitely pin all bots at the spawn.
        anchor = min(available, key=lambda m: (sum(math.dist(m['pos'], n['pos']) for n in available),
                                               m['role'] != 'frontline', m['id']))
        center = _offset(anchor['pos'], facing, 72)
    ordered = sorted(available, key=lambda m: (m['role'] != 'frontline', m['role'] == 'support', m['id']))
    for i, member in enumerate(ordered):
        forward = {'frontline': 100, 'fighter': 20, 'skirmisher': 55,
                   'support': -100, 'artillery': -120}[member['role']]
        point = _offset(center, facing, forward, (i-(len(ordered)-1)/2)*90)
        # The ready core keeps fighting while a respawn/recovery straggler
        # rejoins it. Do not order the whole frontline to turn back toward
        # one far-away teammate, or order a bot already engaged to disengage
        # solely because someone else has just respawned.
        regroup = (separated and math.dist(member['pos'], team_center) > 420
                   and not any(math.dist(member['pos'], s['pos']) < 360 for s in near))
        task = 'regroup' if regroup else 'clear_path' if not near and arena.geometry.id in (34, 35) else 'skirmish'
        _order(arena, result, member, task, point, 'pk:team',
               stance='regroup' if regroup else 'engage' if near else 'rotate', radius=720,
               rationale='Fight as a squad, reserve room for frontline/support, rejoin rather than feed alone.')
    return result


def _focus(result, reports, members, previous, now):
    old_orders = previous.get('orders', {})
    groups = sorted({order['group'] for order in result.values()})
    friends = {m['id']: m for m in members}
    for group in groups:
        ids = [i for i, order in result.items() if order['group'] == group]
        squad = [friends[i] for i in ids]
        ready = [m for m in squad if not m.get('recovering')] or squad
        center = _centroid(ready)
        orders_here = [result[i] for i in ids]
        contacts = [s for s in _tanks(reports)
                    if any(math.dist(s['pos'], o['goal']) <= o['target_radius'] for o in orders_here)]
        if not contacts:
            # Native objective NPCs remain valid only once actually reported.
            siege_ids = {o.get('siege_target') for o in orders_here}
            contacts = [s for s in reports if s['id'] in siege_ids
                        or (s.get('bomb_cart') and group == 'bomb:intercept')
                        or (s.get('robo') and math.dist(s['pos'], center) < 500)]
        if not contacts:
            continue
        def value(contact):
            support = sum(math.dist(m['pos'], contact['pos']) <= 650 for m in ready)
            opposition = sum(math.dist(s['pos'], contact['pos']) <= 350 for s in _tanks(reports))
            peel = any(m['hp'] < .5 and math.dist(m['pos'], contact['pos']) < 260 for m in members)
            sticking = sum(old_orders.get(i, {}).get('focus') == contact['id']
                           and old_orders.get(i, {}).get('focus_generation') == contact['generation'] for i in ids)
            control = contact.get('elite_control_ms', 0) > now-contact['observed_at']+180
            return (math.dist(center, contact['pos']) + contact['hp']*270
                    + contact.get('elite_shield', 0)*220
                    + (650 if contact.get('elite_guarded') else 0)
                    - (100 if control else 0)
                    + max(0, opposition-support)*130 - support*40
                    - (180 if peel else 0) - min(100, sticking*25), contact['id'])
        focus = min(contacts, key=value)
        for ident in ids:
            order = result[ident]
            if math.dist(focus['pos'], order['goal']) > order['target_radius']:
                continue
            order.update(focus=focus['id'], focus_generation=focus['generation'],
                         observed_at=focus['observed_at'])


def _signature(arena, members):
    # No hidden enemy lookup belongs in a signature/cache invalidation either.
    team = tuple((m['id'], m['generation'], m['controlled'], m['eligible'],
                  bool(m.get('recovering'))) for m in members)
    mode = arena.geometry.id
    public = ()
    if mode in FLAG_MAPS:
        camp = members[0]['actor'].camp if members else 0
        public = tuple((f['index'], f['camp'], f.get('locked', 0),
                        f['camp'] == camp and _published_flag_capture(f) == 3-camp)
                       for f in arena.pk.get('flags', ()))
    elif mode in BASE_MAPS:
        public = tuple((a.id, a.alive) for a in arena.actors.values()
                       if a.info.get('base') or a.info.get('map_turret'))
    elif mode == 70:
        public = tuple((a.id, a.alive) for a in arena.actors.values() if a.info.get('bomb_cart'))
    elif mode in DEATH_MAPS:
        public = (arena.pk.get('round_number'), bool(arena.pk.get('collapse_warned')),
                  bool(arena.pk.get('collapse_started')))
    return team, public


def _fresh_orders(orders_, now):
    # Return shallow copies: a tactical controller must not mutate another
    # teammate's durable assignment, and a stale focus never survives the TTL.
    result = {}
    for ident, order in orders_.items():
        value = dict(order)
        if value.get('focus') is not None and not _mature(value, now):
            value.update(focus=None, focus_generation=None, observed_at=0)
        result[ident] = value
    return result


def resolve_order(arena, actor, order, own_delivered, now):
    """Execute shared base assignments with actor-local native feasibility.

    PRO1 reran ``base_mode.goal`` here, silently discarding every coordinated
    defend/push assignment.  Preserve the director's actual choice instead.
    Only public buildings are queried, and firing_position remains the native
    authority for range/LOS/reachability.  The micro controller separately
    converts a defending formation to its own mature observed threat for the
    native target filter.  A teammate's focus is never a new live target.
    """
    result = dict(order)
    if arena.geometry.id not in BASE_MAPS or human(actor) or actor.info.get('npc_template'):
        return result
    if result.get('task') == 'base_defend':
        result.pop('siege_target', None)
        result.pop('hold_radius', None)
        return result
    if result.get('task') not in ('base_push', 'clear_path'):
        return result
    from base_mode import firing_position
    pos = actor.position_at(now)
    structures = [a for a in arena.actors.values() if a.camp == 3-actor.camp
                  and (a.info.get('base') or a.info.get('map_turret'))
                  and a.alive and not a.turret_locked()]
    home = next((a for a in arena.actors.values()
                 if a.camp == 3-actor.camp and a.info.get('base')), None)
    chosen = result.get('siege_target')
    structures.sort(key=lambda a: (a.id != chosen,
                                   0 if a.info.get('base') else 1 if home is not None and a.id in home.unlocked_by else 2,
                                   math.dist(pos, a.position), a.id))
    result.pop('hold_radius', None)
    result.pop('siege_target', None)
    # Do not formation-snap the actor's exact native firing coordinate: that
    # can push it behind a wall or a few pixels outside its real weapon range.
    for target in structures:
        point = firing_position(arena, actor, target, now)
        if point is not None:
            result.update(task='base_push', goal=point, stance='engage',
                          siege_target=target.id, objective_center=tuple(target.position))
            return result
    target = structures[0] if structures else home
    if target is not None:
        result.update(task='clear_path', goal=tuple(target.position), stance='engage',
                      objective_center=tuple(target.position))
    return result


def orders(arena, camp, now):
    """Return elite-only team intentions; human/NPC/legacy actors get no order.

    Order fields: task, goal, role, focus/focus_generation, focus observed_at,
    stance, group and target_radius (chase leash). Contribution tasks also
    expose objective_center/hold_radius; base pushes expose siege_target.
    """
    if (camp not in (1, 2) or not arena.pk or arena.pk.get('finished')
            or arena.pk.get('round_phase') == 'result' or arena.geometry.id not in MAPS
            or getattr(arena, 'tank_test', False)
            or (arena.state.get('room') or {}).get('room_type') == 4):
        return {}
    members = _members(arena, camp, now)
    bots = [m for m in members if m['controlled']]
    if not bots:
        return {}
    teams = arena.pk.setdefault('elite_teams', {})
    previous = teams.get(camp, {})
    signature = _signature(arena, members)
    if (previous.get('version') == VERSION and previous.get('signature') == signature
            and now < previous.get('elite_plan_at', 0)):
        return _fresh_orders(previous['orders'], now)
    reports = _reports(arena, members, previous, now)
    mode = arena.geometry.id
    if mode in FLAG_MAPS:
        result = _flag_plan(arena, camp, members, bots, reports, previous, now)
    elif mode in BASE_MAPS:
        result = _base_plan(arena, camp, members, bots, reports, previous, now)
    elif mode == 70:
        result = _escort_plan(arena, camp, members, bots, reports, previous, now)
    elif mode in (20, 36):
        result = _cow_plan(arena, camp, members, bots, reports, previous, now)
    elif mode in DEATH_MAPS:
        result = _survival_plan(arena, camp, members, bots, reports, previous, now)
    else:
        result = _pk_plan(arena, camp, members, bots, reports, previous, now)
    _focus(result, reports, members, previous, now)
    lease = previous.get('elite_order_until', 0)
    teams[camp] = dict(version=VERSION, signature=signature, contacts=reports,
                       orders=result, advance=previous.get('advance', 0),
                       elite_plan_at=now+PLAN_MS,
                       elite_order_until=lease if now < lease else now+ORDER_MS)
    if mode in BASE_MAPS and previous.get('base_watch') is not None:
        teams[camp]['base_watch'] = previous['base_watch']
    return _fresh_orders(result, now)
