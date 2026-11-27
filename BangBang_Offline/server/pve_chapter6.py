"""Chapter-six solo progression; missing boss scripts remain explicit exceptions.

Assets and rendering exceptions are recorded in the chapter-six install receipt.
"""
import math

from combat_math import D
from pve_balance import hp_for
from pve_chapter1 import remove_objects, _inside
from pve_movement import patrol_goal as _patrol, move
from pve_chapter2 import records, respawn_position, _remove_actor
from pve_chapter4 import stop, finish as common_finish

STAGES = {601: 5, 602: 2, 603: 5}
DECOR = (717, 718, 719, 720, 721, 3110112, 3110113)
LASERS = {719: (-360, 0), 720: (360, 0), 721: (0, -300), 3110112: (0, 300)}
BOSSES = {602: 710, 603: 715, 30101: 3110108, 30102: 3110211, 30103: 3110312}
CROSSINGS = {603: ((1188,2916),(996,2892))}
CROSSING_RADIUS = 24


def zone_fields(arena, zone):
    fields = list(zone['fields'])
    if arena.geometry.id == 30101 and fields[0] == 1:
        # The native switch starts at x539, precisely the last legal tank
        # centre before the closed gate. Reachable 24-unit steps stop at x516;
        # include that one approach step without moving the gate or terrain.
        fields[1] -= 24
        fields[3] += 24
    elif arena.geometry.id == 30101 and fields[0] == 6:
        # This source controller is wholly behind its own closed gate.
        # Extend only toward the accessible eastern approach (129 units),
        # retaining the same y-range and exact authored open commands.
        fields[3] += 144
    return fields


def objective(rec, tpl):
    # Reinforcements ended by the troopship/phase are not mandatory kills.
    if rec['map'] == 601 and rec['point'] == 53:
        return False
    if rec['map'] == 602 and rec['point'] == 171 and tpl != 710:
        return False
    return rec['camp'] == 0 and rec['repeat'] >= 0 and tpl not in DECOR


def initialize(arena):
    total = sum((hp_for(arena,t) * (r['repeat'] + 1) for r in records(arena)
                 for t in r['templates'] if objective(r, t)), D(0))
    arena.pk['pve'].update(stage=0, damage_total=total, active_rules=[], stopped_rules=[],
                          zone_done=[], rescued=[], started=False, hazards=[], rule_kills={},
                          boss_kills=0, crossing_latched=False)


def schedule(arena, rec, now):
    pve = arena.pk['pve']
    if rec['index'] in pve['active_rules'] or rec['index'] in pve['stopped_rules']:
        return
    pve['active_rules'].append(rec['index'])
    for n, tpl in enumerate(rec['templates']):
        # Immortal racers use one finite authored group, not unbounded spawns
        # waiting for deaths which can never happen.
        pve['spawns'].append(dict(rule=rec['index'], template=tpl,
            remaining=0 if tpl in DECOR else rec['repeat'],
            loop=tpl not in DECOR and rec['repeat'] < 0,
            spawn_due_at=now + (abs(rec['delay']) + n * max(1, rec['interval'])) * 1000))


def scripts(arena, script, now):
    packets = []
    for kind, arg, _, _ in script:
        if kind == 4:
            packets += remove_objects(arena, (arg,))
        elif kind == 5:
            stop(arena, (arg,))
            # A laser's stop command must also retire the existing immortal actor.
            for a in list(arena.actors.values()):
                if a.alive and a.info.get('pve_npc') and a.info['point'] == arg and a.info['npc_template'] in LASERS:
                    packets += _remove_actor(a)
        elif kind == 7:
            for rec in records(arena):
                if rec['point'] != arg or rec['delay'] >= 0:
                    continue
                if rec['wave'] and rec['wave'] != arena.pk['pve']['stage']:
                    continue
                schedule(arena, rec, now)
    return packets


def object_destroyed(arena, obj, now):
    rec = next((r for r in arena.geometry.data['npcs'] if ((3 << 26) | r['instance']) == obj.id), None)
    return scripts(arena, rec.get('pve_scripts', ()), now) if rec else []


def stage(arena, wave, now):
    pve = arena.pk['pve']
    old = pve['stage']
    pve['stage'] = wave
    for rec in records(arena):
        if old and rec['wave'] == old and rec['repeat'] < 0:
            stop(arena, (rec['point'],))
        if rec['wave'] == wave and rec['delay'] >= 0:
            schedule(arena, rec, now)
    packets = []
    for rec in arena.geometry.data['pve_waves']:
        if rec['fields'] == wave:
            packets += scripts(arena, rec['scripts'], now)
    for index in pve['zone_done']:
        packets += scripts(arena, arena.geometry.data['pve_zones'][index]['scripts'], now)
    return packets


def spawn(arena, event, now):
    from pve_npc import PveNpc
    from pve_spawn_exits import position as birth_position
    rec = records(arena)[event['rule']]
    tpl = event['template']
    info = dict(point=rec['point'], npc_template=tpl, pve_rule=rec['index'],
                pve_loop=event['loop'], pve_remaining=event['remaining'],
                pve_logic=rec['logic'], pve_unscored=not objective(rec, tpl))
    birth = birth_position(arena, rec, tpl, now)
    if birth != tuple(rec['position']):
        info['pve_spawn_origin'] = tuple(rec['position'])
    actor = PveNpc(arena, arena.new_id(5), info, rec['camp'], birth)
    arena.actors[actor.id] = actor
    if tpl == 3110312:
        from pve_dooku import configure
        configure(actor, now)
    if tpl in LASERS:
        actor.turret_next_shot_at = now + actor.fire_interval(now)
    packets=[actor.snapshot(now)]
    if tpl == 3110310:packets += actor._buff(50350,now)
    return packets


def cleanse_allies(actor,now):
    from combat_geometry import rect_contact
    from combat_protocol import scene,skill_event
    pos=actor.position_at(now)
    packets=[scene(skills=(skill_event(50332,pos,pos,owner=actor.id),))]
    for target in list(actor.arena.actors.values()):
        if (target.camp!=actor.camp or not target.alive or target.in_stasis()
                or target.info.get('map_object') or target.info.get('pve_hostage')):continue
        dest=target.position_at(now)
        if math.dist(pos,dest)>300 or actor.arena.geometry.wall_contact(pos,dest) is not None:continue
        if rect_contact(pos,dest,actor.arena.water_rects(now)) is None:packets+=target.cleanse(now)
    return packets


def crossing(arena,now):
    from pve_chapter5 import crossing as native_crossing
    return native_crossing(arena,now,ends=CROSSINGS.get(arena.geometry.id,()))


def death(arena, actor, now):
    pve = arena.pk['pve']
    tpl = actor.info['npc_template']
    rec = records(arena)[actor.info['pve_rule']]
    if actor.camp != 1 and tpl not in DECOR:
        arena.pk['stats'][1][2] += 1
    pve['rule_kills'][rec['index']] = pve['rule_kills'].get(rec['index'], 0) + 1
    if rec['index'] in pve['active_rules'] and (actor.info['pve_loop'] or actor.info['pve_remaining'] > 0):
        pve['spawns'].append(dict(rule=rec['index'], template=tpl, loop=actor.info['pve_loop'],
            remaining=max(0, actor.info['pve_remaining'] - 1),
            spawn_due_at=now + max(1, rec['interval']) * 1000))
    if arena.geometry.id == 601 and tpl == 716:
        stop(arena, ({69: 56, 65: 53}[rec['point']],))
    if tpl == BOSSES.get(arena.geometry.id):
        pve['boss_kills'] += 1
        if arena.geometry.id == 602:
            # Source phase3 explicitly announces the recovered engine.
            packets = stage(arena, 3, now)
            return packets + finish(arena, now)
        if tpl == 3110312:
            from pve_dooku import interrupt
            return interrupt(actor, now) + finish(arena, now)
        return finish(arena, now)
    return []


def mechanisms(arena, now):
    packets = []
    for actor in list(arena.actors.values()):
        tpl = actor.info.get('npc_template')
        if not actor.alive or not actor.info.get('pve_npc'):
            continue
        pos = actor.position_at(now)
        if tpl == 717 and arena.player.alive and not arena.player.in_stasis():
            if math.dist(arena.player.position_at(now), pos) <= 72:
                arena.pk['pve']['rescued'].append(actor.id)
                packets += _remove_actor(actor)
        elif tpl in LASERS and now >= actor.turret_next_shot_at:
            dx, dy = LASERS[tpl]
            dest = (pos[0] + dx, pos[1] + dy)
            actor.turret_next_shot_at = now + (actor.pve_count - 1) * actor.pve_break + actor.fire_interval(now)
            packets += actor._shot(dest, now)
            if arena.pk['finished']:
                return packets
            for n in range(1, actor.pve_count):
                actor._queue(now + n * actor.pve_break, 'pve_fixed_laser', actor.generation, dest)
    return packets


def ai(arena, now):
    from bot_ai import observable, stop as stop_tank
    if arena.pk['finished']:
        return []
    packets = []
    for actor in list(arena.actors.values()):
        tpl = actor.info.get('npc_template')
        if not actor.alive or not actor.info.get('pve_npc') or tpl in DECOR and tpl!=718:
            continue
        if tpl == 3110312:
            from pve_dooku import tick as dooku_tick
            busy, emitted = dooku_tick(actor, now)
            packets += emitted
            if arena.pk['finished']:
                break
            if busy:
                continue
        brain = arena.bot_brains.setdefault(actor.id, dict(path=[], notice_at=0))
        from pve_boss_tactics_v2 import tick as remaining_boss_tick
        tactical = remaining_boss_tick(actor, brain, now)
        if tactical is not None:
            packets += tactical
            if arena.pk['finished']: break
            continue
        from pve_tactics import tick as tactical_tick
        tactical = tactical_tick(actor, brain, now)
        if tactical is not None:
            packets += tactical
            if arena.pk['finished']: break
            continue
        if now >= brain['notice_at']:
            brain['notice_at'] = now + 200
            brain['pve_patrolling'] = False
            pos = actor.position_at(now)
            target = min((a for a in arena.actors.values() if not a.info.get('map_object')
                and not a.info.get('pve_hostage') and observable(arena, actor, a, now, 600)),
                key=lambda a: (math.dist(pos, a.position_at(now)), a.id), default=None)
            if tpl == 718:
                brain['goal'] = _patrol(arena,actor,now)
                if target and math.dist(pos,target.position_at(now))<=100 and now>=actor.cooldowns[0]:
                    from pve_shots import targets
                    actor.cooldowns[0]=now+1000
                    for victim in targets(actor,pos,144,now):
                        packets+=actor.damage(D(100)+actor.combat_stat('iAttack',now),now,
                            target=victim,school='true',basic=True)[0]
                        if arena.pk['finished']:
                            break
            elif tpl == 3110310:
                brain['goal'] = _patrol(arena,actor,now)
                if (now>=actor.cooldowns[0] and not actor.blocked('attack',now)
                        and not actor.skill_sealed(0,now)):
                    actor.cooldowns[0]=now+2000
                    packets+=cleanse_allies(actor,now)
            elif target and actor.shot_skill:
                dest = target.position_at(now)
                near = math.dist(pos, dest) <= actor.pve_fire_range
                brain['goal'] = pos if near else dest
                if near:
                    packets += stop_tank(actor, now) + actor.cast(0, pos, dest, target.id, now)
            else:
                brain['goal'] = _patrol(arena, actor, now)
        if arena.pk['finished']:
            break
        packets += move(arena, actor, brain, now)
        if arena.pk['finished']:
            break
    return packets


def completed(arena, rec):
    if rec['index'] in arena.pk['pve']['stopped_rules']:
        return True
    expected = sum(objective(rec, t) for t in rec['templates']) * (rec['repeat'] + 1)
    return arena.pk['pve']['rule_kills'].get(rec['index'], 0) >= expected


def finish(arena, now):
    pve = arena.pk['pve']
    total = D(0)
    for rec in records(arena):
        if rec['index'] in pve['stopped_rules']:
            total += sum((a.max_hp for a in arena.actors.values() if a.info.get('pve_npc')
                and a.info.get('pve_rule') == rec['index'] and objective(rec, a.info['npc_template'])), D(0))
        else:
            total += sum((hp_for(arena,t) * (rec['repeat'] + 1) for t in rec['templates'] if objective(rec, t)), D(0))
    pve['damage_total'] = max(D(1), total)
    return common_finish(arena, now)


def tick(arena, now):
    pve = arena.pk['pve']
    mid = arena.geometry.id
    packets = []
    if not pve['started']:
        pve['started'] = True
        packets += stage(arena, 1, now)
        for rec in records(arena):
            if rec['wave'] == 0 and rec['delay'] >= 0:
                schedule(arena, rec, now)
    packets += crossing(arena,now)
    if arena.player.alive and not arena.player.in_stasis():
        for index, zone in enumerate(arena.geometry.data['pve_zones']):
            if index not in pve['zone_done'] and _inside(arena.player.position_at(now), zone_fields(arena, zone)):
                pve['zone_done'].append(index)
                packets += scripts(arena, zone['scripts'], now)
    waiting = pve['spawns']
    pve['spawns'] = []
    for event in waiting:
        if now >= event['spawn_due_at']:
            packets += spawn(arena, event, now)
        else:
            pve['spawns'].append(event)
    packets += mechanisms(arena, now)
    if arena.pk['finished']:
        return packets
    packets += ai(arena, now)
    if arena.pk['finished']:
        return packets
    if mid in STAGES and pve['stage'] < STAGES[mid]:
        if all(completed(arena, r) for r in records(arena) if r['wave'] == pve['stage']):
            packets += stage(arena, pve['stage'] + 1, now)
    if mid == 601 and pve['stage'] == 5 and pve['rescued']:
        packets += finish(arena, now)
    return packets
