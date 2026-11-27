"""M29 offline PvE grading, using native five-byte result fields.

The Flash client displays server grades; the recovered client is not evidence
of a server grading formula.  This is an explicit offline rule, frozen for a
new run.  Old runs without the marker keep pve_rules' original evaluation.
Only fresh HP loss on finite, spawned hostile NPCs contributes scoring damage.
Raw STAT_HARM remains the actual credited damage, as in previous releases.
"""
from copy import deepcopy

from combat_data import table_row
from combat_math import D


POLICY = 'm29_helper_weighted_v1'
RESULT_KEY = 'grading_result_v1'
LEDGER_KEY = 'grading_hp_v1'
DAMAGE_KEY = 'grading_damage_v1'

# These rules are copied into the world state at start, not read from a newer
# deployment when a checkpoint resumes. Values are integer ratios/points.
RULES = {
    'helper': ((125, 7, 20), (100, 6, 18), (80, 5, 14),
               (50, 4, 10), (0, 3, 5)),
    'no_helper': (3, 0),
    'harm': ((85, 5, 35), (65, 4, 25), (0, 3, 10)),
    'dead': ((0, 5, 25), (1, 4, 12), (2, 3, 0)),
    'time': ((100, 5, 20), (150, 4, 16), (200, 3, 8)),
    'slow_time': (3, 0),
    'total': ((90, 7), (80, 6), (65, 5), (50, 4), (0, 3)),
    'sss': {'damage_percent': 85, 'maximum_deaths': 0, 'time_percent': 150},
}


def _integer(value, name, *, minimum=0, maximum=2**32-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'Invalid PvE grading {name}')
    return value


def _amount(value, name):
    if isinstance(value, bool):
        raise ValueError(f'Invalid PvE grading {name}')
    amount = D(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError(f'Invalid PvE grading {name}')
    return amount


def profile_for_run(state):
    """Called after balance and helper builds were frozen by native start."""
    room, battle = state['room'], state['battle']
    balance = battle['pve_balance']
    if balance['map_id'] != room['map_id'] or balance['difficulty'] != room.get('pve_difficulty', 0):
        raise ValueError('PvE grading room does not match frozen balance')
    build = state.get('booster_build') or {}
    if build and (type(build.get('version')) is not int or build.get('version') != 1
                  or build.get('map_id') != room['map_id']):
        raise ValueError('PvE grading helper does not match this run')
    helper = _integer(build.get('score', 0), 'helper power')
    recommendation = _integer(balance['recommended_power'], 'recommended power', minimum=1)
    requested = _integer(balance['requested_map_id'], 'requested map', minimum=1)
    source = table_row('MapTemplate_table.xml', nMapId=requested)
    native_target = int(source.get('nPassTime') or 900)
    if native_target <= 0:
        raise ValueError('Invalid source PvE pass-time recommendation')
    return dict(version=1, policy=POLICY, map_id=room['map_id'],
                requested_map_id=requested, difficulty=balance['difficulty'],
                helper_power=helper, recommended_power=recommendation,
                native_target_seconds=native_target,
                target_seconds=max(180, min(360, native_target)),
                rules=deepcopy(RULES))


def frozen_profile(arena):
    """Absent marker is deliberately legacy, not a request to regrade a save."""
    battle = arena.state.get('battle') or {}
    if 'pve_scoring' not in battle:
        return None
    profile = battle['pve_scoring']
    room = arena.state.get('room') or {}
    balance = battle.get('pve_balance') or {}
    if (not isinstance(profile, dict) or type(profile.get('version')) is not int
            or profile.get('version') != 1
            or profile.get('policy') != POLICY
            or profile.get('map_id') != arena.geometry.id
            or profile.get('map_id') != room.get('map_id')
            or profile.get('difficulty') != room.get('pve_difficulty', 0)
            or profile.get('requested_map_id') != balance.get('requested_map_id')):
        raise ValueError('Invalid frozen PvE grading profile')
    _integer(profile.get('helper_power'), 'helper power')
    _integer(profile.get('recommended_power'), 'recommended power', minimum=1)
    _integer(profile.get('target_seconds'), 'target seconds', minimum=1, maximum=900)
    return profile


def eligible(arena, actor):
    """Only finite combat NPCs; not endless waves, allies, bricks or hazards."""
    info = actor.info
    if (not info.get('pve_npc') or actor.camp == arena.player.camp
            or any(info.get(key) for key in (
                'pve_unscored', 'pve_loop', 'pve_hostage', 'pve_trap'))):
        return False
    maximum = D(actor.max_hp)
    return maximum.is_finite() and maximum > 0


def _entry(arena, actor, before):
    ledger = arena.pk['pve'].setdefault(LEDGER_KEY, {})
    # Native PvE spawn IDs are never reused during the run. A finite authored
    # repeat gets a new ID/budget; an endless-loop actor is never eligible.
    key = str(actor.id)
    if key not in ledger:
        maximum = _amount(actor.max_hp, 'NPC maximum HP')
        ledger[key] = dict(maximum=maximum, lowest=min(maximum, max(D(0), D(before))))
    return ledger[key]


def record_hp(arena, actor, before, credited):
    """Fresh personal/summon damage only; healing never resets a HP budget."""
    if frozen_profile(arena) is None or not eligible(arena, actor):
        return
    row = _entry(arena, actor, before)
    remaining = min(row['maximum'], max(D(0), D(actor.hp)))
    fresh = max(D(0), row['lowest'] - remaining)
    # Advance even on environmental/uncredited damage. Shooting healed HP that
    # somebody else removed must not earn personal scoring credit later.
    row['lowest'] = min(row['lowest'], remaining)
    if credited and fresh:
        pve = arena.pk['pve']
        pve[DAMAGE_KEY] = pve.get(DAMAGE_KEY, D(0)) + fresh


def damage_totals(arena):
    """Include untouched spawned enemies, not impossible/untriggered branches.

    PvE controllers retain their NPC actors through settlement. The persisted
    ledger also keeps dead/previous-wave budgets if a future controller removes
    an actor after a recorded HP event. No damage credit is invented by a scan.
    """
    pve = arena.pk['pve']
    for actor in arena.actors.values():
        if eligible(arena, actor):
            _entry(arena, actor, actor.hp)
    total = sum((row['maximum'] for row in pve.get(LEDGER_KEY, {}).values()), D(0))
    damage = min(total, _amount(pve.get(DAMAGE_KEY, 0), 'effective damage'))
    return damage, total


def metrics(profile, *, won, damage, damage_total, deaths, elapsed):
    """Pure evaluation for a frozen contract; no DB, RNG, clock or player writes."""
    helper = _integer(profile['helper_power'], 'helper power')
    recommendation = _integer(profile['recommended_power'], 'recommended power', minimum=1)
    target = _integer(profile['target_seconds'], 'target seconds', minimum=1, maximum=900)
    deaths = _integer(deaths, 'deaths', maximum=2**31-1)
    elapsed = _integer(elapsed, 'elapsed seconds', maximum=2**31-1)
    total_hp = _amount(damage_total, 'eligible HP')
    damage = min(total_hp, _amount(damage, 'effective damage'))
    rules = profile['rules']
    helper_grade, helper_points = (next((grade, points) for percent, grade, points in rules['helper']
                                          if helper*100 >= recommendation*percent)
                                   if helper else rules['no_helper'])
    harm_grade, harm_points = next((grade, points) for percent, grade, points in rules['harm']
                                  if (total_hp > 0 and damage*100 >= total_hp*percent) or percent == 0)
    dead_grade, dead_points = next((grade, points) for count, grade, points in rules['dead']
                                  if deaths <= count or count == rules['dead'][-1][0])
    time_grade, time_points = next(((grade, points) for percent, grade, points in rules['time']
                                   if elapsed*100 <= target*percent), rules['slow_time'])
    points = helper_points + harm_points + dead_points + time_points
    sss = rules['sss']
    eligible_sss = bool(won and total_hp > 0
                        and damage*100 >= total_hp*sss['damage_percent']
                        and deaths <= sss['maximum_deaths']
                        and elapsed*100 <= target*sss['time_percent'])
    total_grade = next(grade for threshold, grade in rules['total'] if points >= threshold)
    if not eligible_sss:
        total_grade = min(total_grade, 6)
    grades = [total_grade, harm_grade, dead_grade, time_grade, helper_grade] if won else [0]*5
    return dict(version=1, policy=profile['policy'], map_id=profile['map_id'],
                requested_map_id=profile['requested_map_id'], difficulty=profile['difficulty'],
                helper_power=helper, recommended_power=recommendation, target_seconds=target,
                effective_damage=str(damage), eligible_hp=str(total_hp), deaths=deaths,
                elapsed_seconds=elapsed, points=points if won else 0,
                component_points=dict(helper=helper_points, harm=harm_points,
                                      dead=dead_points, time=time_points),
                eligible_sss=eligible_sss, grades=grades)


def _result(arena, profile):
    damage, total = damage_totals(arena)
    return metrics(profile, won=arena.pk['winner'] == 1, damage=damage,
                   damage_total=total, deaths=arena.pk['stats'][1][0],
                   elapsed=arena.pk['elapsed'])


def freeze_result(arena):
    """Finish records the decision once, before persistence/reward settlement."""
    profile = frozen_profile(arena)
    if profile is not None and RESULT_KEY not in arena.pk['pve']:
        arena.pk['pve'][RESULT_KEY] = _result(arena, profile)


def evaluation(arena):
    profile = frozen_profile(arena)
    if profile is None:
        return None
    result = arena.pk['pve'].get(RESULT_KEY)
    if result is None:
        result = _result(arena, profile)
    grades = result['grades']
    if len(grades) != 5 or any(type(value) is not int or not 0 <= value <= 7 for value in grades):
        raise ValueError('Invalid frozen PvE evaluation')
    return tuple(grades)
