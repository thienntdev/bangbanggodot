"""Predictable local Dooku phases using the recovered native weapons/buffs.

The m803_boss AI script is unavailable. Its fan50333, laser50334 and four
debuff skills/buffs survive in the source tables. The local schedule is an
explicit design: laser warning1200ms, two locked shots800ms apart,1000ms
recovery; debuff warnings1500ms with poison/slow/stun/silence rotation every
15000ms. The source says random every15s; deterministic order is intentional.
Base HP/attack/armor and the ordinary fan are untouched. Poison uses the
source numeric cooldown2000ms, not the conflicting prose 'each second'.

Only versioned local runs opt in. Tick state contains ordinary checkpoint
data and existing timestamp keys; reconnect never restarts an attack.
"""
import math
import struct

from combat_data import table_row
from combat_geometry import point_at, rect_contact
from combat_math import D
from combat_protocol import scene, skill_event
from pve_local_mechanics import enabled as local_enabled

MAP = 30103
TEMPLATE = 3110312
LASER = 50334
DEBUFFS = ((50335, 50346), (50338, 50347), (50339, 50348), (50340, 50349))
CYCLE = 15000
LASER_WARNING = 1200
DEBUFF_WARNING = 1500
RECOVERY = 1000
RANGE = 600


def enabled(actor):
    return (actor.info.get('pve_npc') and actor.info.get('npc_template') == TEMPLATE
            and actor.arena.geometry.id == MAP and local_enabled(actor.arena))


def configure(actor, now):
    if enabled(actor) and not hasattr(actor, 'pve_dooku'):
        actor.pve_dooku = dict(version=1, generation=actor.generation, phase='idle',
                               cast=None, cursor=0, poisons=[], phase_end=now,
                               next_tick_at=now, phase_gap=now)


def _eligible(actor, target, now, radius=RANGE):
    # The source special targets enemy tanks. Yoda/objects/hostages do not
    # consume a targeted debuff which is meant to threaten the player.
    if (target is None or not target.alive or target.camp == actor.camp
            or target.info.get('npc_template') or target.info.get('pve_hostage')
            or target.in_stasis() or not target.is_area_targetable()):
        return False
    from bot_ai import observable
    return (observable(actor.arena, actor, target, now, radius)
            and rect_contact(actor.position_at(now), target.position_at(now),
                             actor.arena.water_rects(now)) is None)


def _nearest(actor, now, radius=RANGE):
    start = actor.position_at(now)
    return min((target for target in actor.arena.actors.values()
                if _eligible(actor, target, now, radius)),
               key=lambda target: (math.dist(start, target.position_at(now)), target.id),
               default=None)


def _beam_end(actor, start, dest, now):
    fraction = min((value for value in (
        actor.arena.geometry.wall_contact(start, dest),
        rect_contact(start, dest, actor.arena.water_rects(now))) if value is not None), default=1.)
    return tuple(round(v) for v in point_at(start, dest, fraction))


def _warning(actor, cast, now):
    dest = _beam_end(actor, cast['start'], cast['dest'], now) if cast['skill'] == LASER else cast['dest']
    return [scene(skills=(skill_event(cast['skill'], cast['start'], dest,
                                     cast['target'], owner=actor.id, ready=1),))]


def _valid_cast(actor, cast, now):
    target = actor.arena.actors.get(cast['target'])
    return (actor.alive and actor.generation == cast['generation']
            and not actor.arena.pk['finished'] and not actor.blocked('attack', now)
            and not actor.skill_sealed(0, now)
            and math.dist(actor.position_at(now), cast['start']) <= 1
            and target is not None and target.generation == cast['target_generation']
            and _eligible(actor, target, now, RANGE))


def interrupt(actor, now):
    state = getattr(actor, 'pve_dooku', None)
    if not state or state.get('cast') is None:
        return []
    cast, state['cast'] = state['cast'], None
    state['phase'] = 'stopped' if actor.arena.pk['finished'] or not actor.alive else 'recovery'
    state['phase_end'] = now + RECOVERY
    actor.cooldowns[0] = max(actor.cooldowns.get(0, 0), state['phase_end'])
    return [(1583, struct.pack('<II', actor.id, cast['skill']))]


def resume(actor, now):
    """Repaint the saved warning only; no mutation, cast or new deadline."""
    state = getattr(actor, 'pve_dooku', None)
    if not enabled(actor) or not state:
        return []
    cast = state.get('cast')
    if (cast is None or state['phase'] not in ('laser_warning', 'laser_gap', 'debuff_warning')
            or cast['finish'] <= now or not _valid_cast(actor, cast, now)):
        return []
    return _warning(actor, cast, now)


def _start(actor, state, target, now, laser):
    from bot_ai import stop
    # A native 24px step can be legal at both ends while an interpolated
    # corner pose is not a legal new walk origin. Own the AI tick but let
    # this one step finish before parking; no warning/deadline starts early.
    # tick() returns busy while this is pending, so ordinary AI cannot
    # replace the finishing motion with another step or a premature stop.
    if actor.motion is not None and actor.motion[3] > now:
        return []
    packets = stop(actor, now)
    start, dest = actor.position_at(now), target.position_at(now)
    if laser:
        if start == dest:
            return packets
        row = table_row('SkillTemplate_table.xml', nId=LASER)
        effect = table_row('EffectTemplate_table.xml', nId=269)
        length = min(int(row['iRange']), int(effect['iRange1']))
        dest = tuple(round(v) for v in point_at(start, dest, length / math.dist(start, dest)))
        # Lock the warned endpoint too: destroying cover during the charge
        # must not extend this shot into an area which was never warned.
        dest = _beam_end(actor, start, dest, now)
        cast = dict(skill=LASER, start=start, dest=dest, target=target.id,
                    target_generation=target.generation, generation=actor.generation,
                    finish=now + LASER_WARNING, count=int(row['iCount']),
                    interval=int(row['iInterval']), width=int(effect['iRange2']),
                    raw=D(effect['fEffectVal']) + actor.combat_stat('iEgAtk', now) * D(effect['fAddVal']))
        state['phase'] = 'laser_warning'
        state['next_tick_at'] = now + CYCLE
        lock = cast['finish'] + (cast['count'] - 1) * cast['interval'] + RECOVERY
    else:
        skill, buff = DEBUFFS[state['cursor'] % len(DEBUFFS)]
        state['cursor'] += 1
        cast = dict(skill=skill, buff=buff, start=start, dest=dest, target=target.id,
                    target_generation=target.generation, generation=actor.generation,
                    finish=now + DEBUFF_WARNING)
        state['phase'] = 'debuff_warning'
        state['phase_gap'] = now + CYCLE
        lock = cast['finish'] + RECOVERY
    state['cast'] = cast
    actor.cooldowns[0] = max(actor.cooldowns.get(0, 0), lock)
    return packets + _warning(actor, cast, now)


def _laser(actor, cast, now):
    from melee_common import in_strip
    from pve_shots import targets
    start, dest = cast['start'], cast['dest']
    end = _beam_end(actor, start, dest, now)
    packets = [scene(skills=(skill_event(LASER, start, end, cast['target'],
                                        owner=actor.id, ready=0),))]
    for target in targets(actor, start, math.dist(start, end) + 36, now):
        if (in_strip(target.position_at(now), start, end, math.dist(start, end), cast['width'])
                and not actor.projectile_blocked(target, now)):
            packets += actor.damage(cast['raw'], now, target=target, school='energy',
                                    source_generation=cast['generation'])[0]
            if actor.arena.pk['finished'] or not actor.alive:
                return packets
    return packets


def _debuff(actor, state, cast, now):
    target = actor.arena.actors[cast['target']]
    packets = [scene(skills=(skill_event(cast['skill'], cast['start'], target.position_at(now),
                                        target.id, owner=actor.id, ready=0),))]
    buff = cast['buff']
    before = target.buff_versions.get(buff)
    packets += actor._buff(buff, now, target.id)
    if (buff == 50346 and target.buff_versions.get(buff) != before
            and target.has_buff(buff, now) and target.buff_sources.get(buff) == actor.id):
        row = table_row('BuffTemplate_table.xml', nBuffId=buff)
        interval, duration = int(row['iCoolTime']), int(row['iPersistTime'])
        state['poisons'] = [dot for dot in state['poisons'] if dot['target'] != target.id]
        state['poisons'].append(dict(target=target.id, target_generation=target.generation,
            generation=actor.generation, version=target.buff_versions[buff],
            next_tick_at=now + interval, end=now + duration, interval=interval,
            raw=abs(D(row['fEffectValA'])), remaining=duration // interval))
    return packets


def _poisons(actor, state, now):
    packets, keep = [], []
    for dot in state['poisons']:
        target = actor.arena.actors.get(dot['target'])
        if (actor.arena.pk['finished'] or not actor.alive or actor.generation != dot['generation']
                or target is None or not target.alive or target.generation != dot['target_generation']
                or target.buff_versions.get(50346) != dot['version']
                or target.buff_sources.get(50346) != actor.id
                or not target.has_buff(50346, now) and not (
                    dot['remaining'] == 1 and dot['next_tick_at'] == dot['end'] and now >= dot['end'])):
            continue
        if now >= dot['next_tick_at']:
            packets += actor.damage(dot['raw'], now, target=target, school='true', periodic=True,
                                    source_generation=dot['generation'])[0]
            dot['remaining'] -= 1
            dot['next_tick_at'] += dot['interval']
            if actor.arena.pk['finished'] or not actor.alive:
                state['poisons'] = []
                return packets
        if dot['remaining'] > 0:
            keep.append(dot)
    state['poisons'] = keep
    return packets


def tick(actor, now):
    """Return (owns movement/attack this tick, packets) to chapter-six AI."""
    if not enabled(actor):
        return False, []
    configure(actor, now)
    state = actor.pve_dooku
    if (actor.arena.pk['finished'] or not actor.alive
            or actor.generation != state['generation']):
        return True, interrupt(actor, now)
    packets = _poisons(actor, state, now)
    if actor.arena.pk['finished'] or not actor.alive:
        return True, packets
    cast = state.get('cast')
    if cast is not None:
        if not _valid_cast(actor, cast, now):
            return True, packets + interrupt(actor, now)
        if now < cast['finish']:
            return True, packets
        if cast['skill'] == LASER:
            packets += _laser(actor, cast, now)
            if actor.arena.pk['finished'] or not actor.alive:
                return True, packets
            cast['count'] -= 1
            if cast['count'] > 0:
                cast['finish'] = now + cast['interval']
                state['phase'] = 'laser_gap'
                return True, packets + _warning(actor, cast, now)
        else:
            packets += _debuff(actor, state, cast, now)
        state['cast'] = None
        state['phase'], state['phase_end'] = 'recovery', now + RECOVERY
        return True, packets
    if state['phase'] == 'recovery':
        if now < state['phase_end']:
            return True, packets
        state['phase'] = 'barrage'
    target = _nearest(actor, now)
    if state['phase'] == 'idle':
        if target is not None:
            state.update(phase='barrage', next_tick_at=now + 6000,
                         phase_gap=now + CYCLE - DEBUFF_WARNING)
        return False, packets
    if target is None or actor.blocked('attack', now) or actor.skill_sealed(0, now):
        return False, packets
    if now >= state['phase_gap']:
        return True, packets + _start(actor, state, target, now, False)
    if now >= state['next_tick_at']:
        target = _nearest(actor, now, 500)
        if target is not None and actor.position_at(now) != target.position_at(now):
            return True, packets + _start(actor, state, target, now, True)
    return False, packets
