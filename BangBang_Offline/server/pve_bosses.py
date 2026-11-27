"""Explicit offline final-boss attack, not a recovered Flash AI script.

The source m31602_boss script is absent and its NPC has no basic weapon.
Skill1000150 supplies the death-ray identity and radius300 source effect. Its
legacy type4/AddB2 semantics are not established; energy1000+1xEgAtk is our
offline rule. Charge is deliberately 2000ms rather than the source text's
1000ms, with a 5000ms start-to-start interval, so a moving player can dodge.
Only new version1 balanced runs opt in. Old checkpoints retain old behavior.
"""
import math
import struct

from combat_math import D
from combat_protocol import scene, skill_event
from pve_balance import frozen_profile

TEMPLATE = 3160211
SKILL = 1000150
RADIUS = 300
RANGE = 800
CHARGE_MS = 2000
INTERVAL_MS = 5000


def enabled(actor):
    return (actor.info.get('pve_npc') and actor.info.get('npc_template') == TEMPLATE
            and actor.arena.geometry.id == 31602 and frozen_profile(actor.arena) is not None)


def configure(actor):
    if not enabled(actor):
        return
    actor.shot_skill = SKILL
    actor.pve_fire_range = RANGE
    actor.stats['nFireRange'] = str(RANGE)
    actor.pve_boss_cast = None


def interrupt(actor, now):
    cast = getattr(actor, 'pve_boss_cast', None)
    if cast is None:
        return []
    actor.pve_boss_cast = None
    if cast.get('tactics_version') == 1:
        from pve_boss_tactics import interrupted
        interrupted(actor, now)
    return [(1583, struct.pack('<II', actor.id, SKILL))]


def resume(actor, now):
    """Presentation only: do not restart or extend the saved server timer."""
    cast = getattr(actor, 'pve_boss_cast', None)
    if (cast is None or not enabled(actor) or actor.arena.pk['finished'] or not actor.alive
            or actor.generation != cast['generation'] or cast['finish'] <= now):
        return []
    target = actor.arena.actors.get(cast['target'])
    if (target is None or not target.alive or target.generation != cast['target_generation']
            or target.camp == actor.camp or not target.is_area_targetable()):
        return []
    if cast.get('tactics_version') == 1:
        from pve_boss_tactics import _valid_cast
        if not _valid_cast(actor, cast, now):
            return []
    return [scene(skills=(skill_event(SKILL, cast['start'], cast['dest'], cast['target'],
                                    owner=actor.id, ready=1),))]


def shot(actor, dest, now, target=None):
    if not enabled(actor):
        return None
    from pve_boss_tactics import eye_shot
    tactical = eye_shot(actor, dest, now, target)
    if tactical is not None:
        return tactical
    if (actor.arena.pk['finished'] or not actor.alive or actor.blocked('attack', now)
            or actor.skill_sealed(0, now) or getattr(actor, 'pve_boss_cast', None) is not None
            or target is None or not target.alive or target.camp == actor.camp
            or not target.is_area_targetable() or target.info.get('pve_hostage')):
        return []
    start, dest = actor.position_at(now), target.position_at(now)
    if math.dist(start, dest) > RANGE:
        return []
    # Persist only ordinary data. `finish` and queued due time already belong
    # to the VERSION1 checkpoint time schema; cast identity survives restore.
    cast = dict(start=start, dest=dest, target=target.id, target_generation=target.generation,
                generation=actor.generation, finish=now+CHARGE_MS,
                raw=D(1000)+actor.combat_stat('iEgAtk', now))
    actor.pve_boss_cast = cast
    actor.cooldowns[0] = now+INTERVAL_MS
    actor._queue(cast['finish'], 'pve_boss_ray', cast)
    return [scene(skills=(skill_event(SKILL, start, dest, target.id, owner=actor.id, ready=1),))]


def event(actor, now, kind, data):
    if kind != 'pve_boss_ray':
        return None
    cast, = data
    if getattr(actor, 'pve_boss_cast', None) is not cast:
        return []
    if cast.get('tactics_version') == 1:
        from pve_boss_tactics import eye_release
        return eye_release(actor, cast, now)
    if actor.arena.pk['finished']:
        return []
    target = actor.arena.actors.get(cast['target'])
    if (not enabled(actor) or not actor.alive or actor.generation != cast['generation']
            or actor.blocked('attack', now) or actor.skill_sealed(0, now)
            or target is None or not target.alive or target.generation != cast['target_generation']
            or target.camp == actor.camp or not target.is_area_targetable()):
        return interrupt(actor, now)
    actor.pve_boss_cast = None
    packets = [scene(skills=(skill_event(SKILL, cast['start'], cast['dest'], cast['target'],
                                        owner=actor.id, ready=0),))]
    from pve_shots import targets
    for victim in targets(actor, cast['dest'], RADIUS, now):
        packets += actor.damage(cast['raw'], now, target=victim, school='energy',
                                source_generation=cast['generation'])[0]
        if actor.arena.pk['finished']:
            return packets
    return packets
