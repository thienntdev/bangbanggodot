"""Versioned local completion of the late PvE interaction scripts.

Dialog6023 describes capturing the forklift and clearing the exit. Dialogs
860/861 describe one allied-support choice per opposed bridgehead row. The
original interaction scripts are absent: the explicit positions, hold times,
support mapping and escort policy below are a local design, not Flash parity.
Native combat stats, attacks, movement, scoring and rewards remain in their
existing executors. Only new runs with the frozen local-mechanics profile opt in.
"""
import copy
import math
import struct

from combat_geometry import rect_contact
from combat_math import D
from combat_protocol import scene

FORKLIFT_MAP = 31202
FORKLIFT_TEMPLATE = 3120209
FORKLIFT_GATE_IDS = tuple(range(29950, 29955))
FORKLIFT_GATE_POSITIONS = tuple((2818, y) for y in (795, 867, 939, 1011, 1083))
FORKLIFT_GOAL = (2700, 939)
FORKLIFT_EXIT = (2870, 800, 70, 310)
CAPTURE_RADIUS = 144
CAPTURE_MS = 1000
CLEAR_RADIUS = 180
CLEAR_MS = 1500

# Road-side fronts of the six bridgeheads; banks/buildings remain solid.
# The artwork/dialogs establish paired choices, not their original effects.
# Mapping these native support units to the six choices is deliberately local.
FORT_ROWS = (
    (1665, (3140311, 3140312)),
    (1230, (3140313, 3140308)),
    (735, (3140312, 3140311)),
)
FORT_NAMES = {3140311: 'Pháo đài laser', 3140312: 'Tank quân phản kháng',
              3140313: 'Bác sĩ chiến trường', 3140308: 'Mira'}
FORT_HOLD_MS = 1000


def _enabled(arena, map_id):
    from pve_local_mechanics import enabled
    return arena.geometry.id == map_id and enabled(arena)


def _notice(text):
    # Existing native battle notice, also decoded by the HTML5 client.
    from quicksand_map import notice
    return notice(text)


def _players(arena):
    return sorted((a for a in arena.actors.values()
                   if a.camp == 1 and not a.info.get('npc_template')
                   and a.info.get('in_room', True) and a.alive and not a.in_stasis()),
                  key=lambda a: a.id)


def _line(arena, start, end, now):
    return (arena.geometry.wall_contact(start, end) is None
            and rect_contact(start, end, arena.water_rects(now)) is None)


def _can_hold(actor, center, radius, now):
    return (actor.alive and actor.info.get('in_room', True) and not actor.in_stasis()
            and not actor.blocked('move', now) and not actor.blocked('attack', now)
            and math.dist(actor.position_at(now), center) <= radius
            and _line(actor.arena, actor.position_at(now), center, now))


def _free_position(arena, center, now, *, ignore=()):
    """Bounded, deterministic full-body landing with an ordinary walk exit."""
    occupied = [a.position_at(now) for a in arena.actors.values()
                if a.id not in ignore and a.alive and a.info.get('in_room', True)
                and not a.info.get('map_object') and not a.in_stasis()]
    candidates = sorted(((dx*dx+dy*dy, dx, dy)
                         for dx in range(-144, 145, 24)
                         for dy in range(-144, 145, 24)
                         if dx*dx+dy*dy <= 144*144))
    water = arena.water_rects(now)
    for _, dx, dy in candidates:
        pos = (round(center[0]+dx), round(center[1]+dy))
        if (arena.geometry.clamp_tank_position(pos) != pos
                or not arena.geometry.can_walk_to(pos)
                or arena.geometry.wall_contact(pos, pos, 35.999) is not None
                or rect_contact(pos, pos, water, 35.999) is not None
                or any(math.dist(pos, other) < 72 for other in occupied)):
            continue
        if any(arena.geometry.walk_end(pos, (pos[0]+x, pos[1]+y), water)
               == (pos[0]+x, pos[1]+y) for x, y in ((24, 0), (-24, 0), (0, 24), (0, -24))):
            return pos
    return None


def initialize(arena):
    if _enabled(arena, FORKLIFT_MAP):
        arena.pk['pve']['local_forklift'] = dict(phase='boss', vehicle=None,
            capture=None, clear=None, next_tick_at=0)
        _install_exit(arena)
    elif _enabled(arena, 31403):
        arena.pk['pve']['local_fortifications'] = dict(choices={}, pending=None, notices=[])


def _install_exit(arena):
    """Per-arena native sandbag barriers; never mutate the cached imported map.

    Fixed IDs are recreated during normal arena construction before checkpoint
    fields are restored, so MapObject's existing persistence remains sufficient.
    """
    from map_objects import MapObject, rebuild_geometry
    arena.geometry.data = copy.deepcopy(arena.geometry.data)
    for instance, (x, y) in zip(FORKLIFT_GATE_IDS, FORKLIFT_GATE_POSITIONS):
        definition = dict(instance=instance, template=2008, x=x, y=y, camp=2,
                          hp=300, pve_gate=True, pve_scripts=[])
        ident = (3 << 26) | instance
        if ident in arena.actors:
            raise ValueError('Local forklift exit object ID conflicts with the map')
        actor = MapObject(arena, definition)
        actor.info['pve_local_exit_gate'] = True
        arena.actors[ident] = actor
        arena.geometry.data['npcs'].append(definition)
        arena.geometry.data['walls'].append(list(actor.map_rect))
        arena.geometry.data['movement_walls'].append(list(actor.map_rect))
        arena.geometry._walk_objects[actor.map_rect] += 1
    rebuild_geometry(arena)


def forklift_defeated(arena, actor, now):
    """Return None for legacy runs; a new run now requires capture/clear/exit."""
    if not _enabled(arena, FORKLIFT_MAP):
        return None
    state = arena.pk['pve']['local_forklift']
    if state['phase'] != 'boss':
        return []
    state.update(phase='capture', spawn=tuple(actor.position_at(now)), next_tick_at=now)
    packets = [_notice('Đã hạ Xe Cẩu Điên. Đến gần xe nâng và giữ vị trí 1 giây để chiếm xe; sau đó đi cùng xe tới lối ra phía đông.')]
    return packets + _spawn_forklift(arena, now)


def _spawn_forklift(arena, now):
    from pve_npc import PveNpc
    state = arena.pk['pve']['local_forklift']
    if state['vehicle'] is not None or now < state['next_tick_at']:
        return []
    state['next_tick_at'] = now+250
    pos = _free_position(arena, state['spawn'], now)
    if pos is None:
        return []  # Try again after bodies/water clear; never place inside cover.
    info = dict(point=602, npc_template=FORKLIFT_TEMPLATE, pve_rule=-1,
        pve_loop=False, pve_remaining=0, pve_logic=0, pve_unscored=True,
        pve_local_forklift=True, pve_hostage=True, damage_immune=True,
        untargetable=True)
    vehicle = PveNpc(arena, arena.new_id(5), info, 1, pos)
    arena.actors[vehicle.id] = vehicle
    state['vehicle'] = vehicle.id
    return [vehicle.snapshot(now)]


def _channel(state, key, actor, now, duration):
    pending = state.get(key)
    if not pending or pending['owner'] != actor.id or pending['generation'] != actor.generation:
        state[key] = dict(owner=actor.id, generation=actor.generation,
                          begin=now, end=now+duration)
        return False
    return now >= pending['end']


def _stop(actor, now):
    from bot_ai import stop
    # Native terrain is sampled on a24px grid. Interpolated points between
    # two legal steps can fail the next path query; finish this one short
    # step before parking the utility vehicle, never snap it onto a wall.
    if actor.info.get('pve_local_forklift') and actor.motion and now < actor.motion[3]:
        return []
    brain = actor.arena.bot_brains.get(actor.id)
    if brain is not None:
        brain.update(path=[], repath_at=0, goal=actor.position_at(now))
    return stop(actor, now)


def _open_exit(arena, now):
    from map_objects import rebuild_geometry
    packets = []
    for instance in FORKLIFT_GATE_IDS:
        obj = arena.actors[(3 << 26) | instance]
        if not obj.alive:
            continue
        obj.hp = D(0)
        obj.info['hp'] = 0
        packets.extend((obj._hp_packet(obj.id, 0), scene(removed=(struct.pack('<I', obj.id),))))
    rebuild_geometry(arena)
    return packets


def forklift_tick(arena, now):
    if arena.pk['finished'] or not _enabled(arena, FORKLIFT_MAP):
        return []
    state = arena.pk['pve']['local_forklift']
    if state['phase'] == 'boss':
        return []
    packets = _spawn_forklift(arena, now)
    vehicle = arena.actors.get(state['vehicle'])
    if vehicle is None:
        return packets
    players = _players(arena)
    if state['phase'] == 'capture':
        owner = next((a for a in players if _can_hold(a, vehicle.position_at(now), CAPTURE_RADIUS, now)), None)
        if owner is None:
            state['capture'] = None
            return packets
        if _channel(state, 'capture', owner, now, CAPTURE_MS):
            state.update(phase='driving', capture=None)
            packets.append(_notice('Đã chiếm xe nâng. Theo xe đến lối ra phía đông; ở gần xe khi xe dọn chướng ngại.'))
        return packets
    if state['phase'] == 'exit':
        from pve_chapter1 import _inside
        if any(_inside(a.position_at(now), (0, *FORKLIFT_EXIT)) for a in players):
            from pve_chapter4 import finish
            return packets + finish(arena, now)
        return packets
    # A captured utility vehicle cannot be destroyed or award another boss kill.
    # The player may return after a normal respawn; no hidden escort death loss.
    guide = min(players, key=lambda a: (math.dist(a.position_at(now), vehicle.position_at(now)), a.id), default=None)
    if (guide is None or math.dist(guide.position_at(now), vehicle.position_at(now)) > 600
            or vehicle.blocked('move', now)):
        state.update(clear=None, phase='driving')
        return packets + _stop(vehicle, now)
    if math.dist(vehicle.position_at(now), FORKLIFT_GOAL) > 36:
        from pve_movement import move
        state.update(clear=None, phase='driving')
        brain = arena.bot_brains.setdefault(vehicle.id, dict(path=[], notice_at=0))
        brain.update(goal=FORKLIFT_GOAL, pve_patrolling=False)
        return packets + move(arena, vehicle, brain, now)
    packets += _stop(vehicle, now)
    owner = next((a for a in players if _can_hold(a, vehicle.position_at(now), CLEAR_RADIUS, now)), None)
    if owner is None:
        state.update(clear=None, phase='driving')
        return packets
    if state['phase'] != 'clearing':
        packets.append(_notice('Xe nâng đang dọn chướng ngại: giữ gần xe trong 1,5 giây.'))
        state['phase'] = 'clearing'
    if _channel(state, 'clear', owner, now, CLEAR_MS):
        state.update(phase='exit', clear=None)
        packets += _open_exit(arena, now)
        packets.append(_notice('Lối ra đã thông! Đi qua cửa phía đông để hoàn thành phụ bản.'))
    return packets


def _front(pos, y, side):
    left, right = (480, 550) if side == 0 else (950, 1020)
    return left <= pos[0] <= right and abs(pos[1]-y) <= 64


def fortification_tick(arena, now):
    if arena.pk['finished'] or not _enabled(arena, 31403):
        return []
    state = arena.pk['pve']['local_fortifications']
    players = _players(arena)
    packets = []
    candidates = []
    for index, (y, templates) in enumerate(FORT_ROWS):
        if index in state['choices']:
            continue
        if index not in state['notices'] and any(abs(a.position_at(now)[1]-y) < 180 for a in players):
            state['notices'].append(index)
            packets.append(_notice('Công sự %d/3: sát mép trái chọn %s; sát mép phải chọn %s. Giữ vị trí 1 giây; mỗi hàng chỉ chọn một bên.' %
                                   (index+1, FORT_NAMES[templates[0]], FORT_NAMES[templates[1]])))
        for actor in players:
            for side in (0, 1):
                if (_front(actor.position_at(now), y, side)
                        and _can_hold(actor, actor.position_at(now), 0, now)):
                    candidates.append((index, actor.id, side, actor))
    if not candidates:
        state['pending'] = None
        return packets
    index, _, side, owner = min(candidates, key=lambda x: x[:3])
    pending = state['pending']
    if (not pending or (pending['row'], pending['side'], pending['owner'], pending['generation'])
            != (index, side, owner.id, owner.generation)):
        state['pending'] = dict(row=index, side=side, owner=owner.id,
                               generation=owner.generation, begin=now, end=now+FORT_HOLD_MS)
        return packets
    if now < pending['end']:
        return packets
    y, templates = FORT_ROWS[index]
    pos = _free_position(arena, (600 if side == 0 else 900, y), now)
    if pos is None:
        return packets  # Do not consume a choice before a legal unit can exist.
    from pve_npc import PveNpc
    template = templates[side]
    info = dict(point=910+index, npc_template=template, pve_rule=-1,
        pve_loop=False, pve_remaining=0, pve_logic=0, pve_unscored=True,
        pve_fortification=True)
    actor = PveNpc(arena, arena.new_id(5), info, 1, pos)
    arena.actors[actor.id] = actor
    state['choices'][index] = dict(side=side, template=template, actor=actor.id)
    state['pending'] = None
    packets.extend((actor.snapshot(now), _notice('Công sự %d/3 đã chọn %s. Lựa chọn được giữ đến hết trận.' %
                                                (index+1, FORT_NAMES[template]))))
    return packets


def fortification_ai(actor, now):
    """Allied support uses native attack/collision, with a local following rule."""
    arena = actor.arena
    if not actor.info.get('pve_fortification') or not _enabled(arena, 31403):
        return None
    if arena.pk['finished'] or not actor.alive:
        return []
    from bot_ai import observable, stop
    from pve_movement import move
    brain = arena.bot_brains.setdefault(actor.id, dict(path=[], notice_at=0))
    packets = []
    if now >= brain['notice_at']:
        brain['notice_at'] = now+200
        pos = actor.position_at(now)
        players = _players(arena)
        guide = min(players, key=lambda a: (math.dist(pos, a.position_at(now)), a.id), default=None)
        brain['goal'] = guide.position_at(now) if guide and math.dist(pos, guide.position_at(now)) > 168 else pos
        brain['pve_patrolling'] = False
        if actor.info['npc_template'] == 3140313:
            if not actor.blocked('attack', now) and not actor.skill_sealed(0, now) and now >= actor.cooldowns[0]:
                patients = [a for a in arena.actors.values() if a is not actor and a.camp == actor.camp
                    and a.alive and a.hp < a.max_hp and a.info.get('in_room', True)
                    and not a.in_stasis() and not a.info.get('map_object')
                    and not a.info.get('pve_hostage') and not a.info.get('pve_trap')
                    and math.dist(pos, a.position_at(now)) <= 216
                    and _line(arena, pos, a.position_at(now), now)]
                if patients:
                    actor.cooldowns[0] = now+actor.fire_interval(now)
                    packets += stop(actor, now)
                    for patient in patients:
                        packets += patient.restore_hp(D(300)+patient.max_hp*D('.05'), now)
        else:
            target = min((a for a in arena.actors.values() if not a.info.get('map_object')
                and not a.info.get('pve_hostage') and observable(arena, actor, a, now, 600)),
                key=lambda a: (math.dist(pos, a.position_at(now)), a.id), default=None)
            if target:
                dest = target.position_at(now)
                near = math.dist(pos, dest) <= actor.pve_fire_range
                brain['goal'] = pos if near else dest
                if near:
                    packets += stop(actor, now)+actor.cast(0, pos, dest, target.id, now)
    if arena.pk['finished']:
        return packets
    return packets+move(arena, actor, brain, now)


def resume(arena, now):
    """Presentation only: restore instructions without advancing a job/choice."""
    if arena.pk['finished']:
        return []
    if _enabled(arena, FORKLIFT_MAP):
        state = arena.pk['pve'].get('local_forklift', {})
        text = {'capture': 'Đến gần xe nâng và giữ vị trí 1 giây để chiếm xe.',
                'driving': 'Theo xe nâng tới lối ra phía đông; xe sẽ chờ nếu bạn ở quá xa.',
                'clearing': 'Giữ gần xe nâng để hoàn tất dọn chướng ngại.',
                'exit': 'Lối ra đã thông: đi qua cửa phía đông để hoàn thành phụ bản.'}.get(state.get('phase'))
        return [_notice(text)] if text else []
    return []
