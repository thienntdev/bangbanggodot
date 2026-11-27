"""Versioned PvE-only map-quality stats; no tank, PvP or player-save migration.

The role/quality join is reconstructed from the complete 5 x 101 source table
and the exact final-boss HP reference, not claimed as recovered server code.
Each new run freezes its five rows and multipliers before BattleArena starts.
Old runs lacking that contract keep the old role-only lookup on resume.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from combat_data import table_row
from combat_math import D
from pve_catalog import MAPS, NORMAL_TO_HARD, resolve_request

LEVEL_FIELDS = ('iHp', 'iBdAtk', 'iEgAtk', 'iBdArmor', 'iEgArmor', 'iBdCtsis', 'iEgCtsis', 'iK')
STAT_FIELDS = (
    ('iHp', 'iHp', 'fHpCoef', 'hp_multiplier'),
    ('iAttack', 'iBdAtk', 'fBdAtkCoef', 'attack_multiplier'),
    ('iEgAtk', 'iEgAtk', 'fEgAtkCoef', 'attack_multiplier'),
    ('iArmor', 'iBdArmor', 'fBdArmorCoef', 'armor_multiplier'),
    ('iEgArmor', 'iEgArmor', 'fEgArmorCoef', 'armor_multiplier'),
    ('iCentesis', 'iBdCtsis', 'fBdCtsisCoef', 'penetration_multiplier'),
    ('iEgCtsis', 'iEgCtsis', 'fEgCtsisCoef', 'penetration_multiplier'),
)
MULTIPLIERS = ('hp_multiplier', 'attack_multiplier', 'armor_multiplier', 'penetration_multiplier')
ENEMY_MULTIPLIERS = ('enemy_hp_multiplier', 'enemy_damage_multiplier')


def _positive(value, label):
    number = D(value)
    if not number.is_finite() or number <= 0 or number > 16:
        raise ValueError('PvE multiplier invalid: ' + label)
    return str(number)


@lru_cache(maxsize=1)
def _config():
    path = Path(__file__).with_name('pve_balance_config.json')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('Duplicate PvE balance key: ' + key)
            out[key] = value
        return out
    config = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
    if (type(config.get('schema')) is not int or config['schema'] != 1
            or type(config.get('version')) is not int or config['version'] not in (1, 2)):
        raise ValueError('Unsupported PvE balance configuration')
    if config.get('npc_armor_curve') != 'source_iK_target_only_v1':
        raise ValueError('Unsupported PvE armor curve')
    result = dict(npc_armor_curve=config['npc_armor_curve'],
                  **{key: _positive(config[key], key) for key in MULTIPLIERS})
    if config['version'] == 2:
        if type(config.get('bomb_puzzles_version')) is not int or config['bomb_puzzles_version'] != 1:
            raise ValueError('Unsupported PvE bomb puzzle rule')
        result.update({key: _positive(config[key], key) for key in ENEMY_MULTIPLIERS})
        result['bomb_puzzles_version'] = config['bomb_puzzles_version']
    return result


def requested_map(room):
    """Validate the saved room contract without interpreting a room display name."""
    if room.get('room_type') != 4 or room.get('map_id') not in MAPS:
        raise ValueError('PvE balance requires a supported solo room')
    difficulty = room.get('pve_difficulty', 0)
    if type(difficulty) is not int or difficulty not in (0, 1):
        raise ValueError('Invalid PvE difficulty')
    default = NORMAL_TO_HARD.get(room['map_id']) if difficulty else room['map_id']
    requested = room.get('pve_requested_map_id', default)
    canonical, requested_difficulty = resolve_request(requested)
    if canonical != room['map_id'] or requested_difficulty != difficulty:
        raise ValueError('PvE map and difficulty disagree')
    return requested


def profile_for_room(room):
    requested = requested_map(room)
    map_row = table_row('MapTemplate_table.xml', nMapId=requested)
    quality = int(map_row.get('nQuality') or 0)
    if not 0 <= quality <= 100:
        raise ValueError('PvE map quality is outside the source table')
    levels = {}
    for role in range(1, 6):
        key = role * 100000 + quality
        source = table_row('AINpcLevelTemplate_table.xml', nLevelId=key)
        row = {}
        for field in LEVEL_FIELDS:
            value = D(source[field])
            if not value.is_finite() or value < 0 or (field == 'iK' and value == 0):
                raise ValueError('Invalid PvE source stat: ' + field)
            row[field] = str(value)
        row['nLevelId'] = str(key)
        levels[str(role)] = row
    return dict(version=1, map_id=room['map_id'], requested_map_id=requested,
                local_mechanics_version=1,
                pve_tactics_version=1,
                pve_boss_tactics_version=1,
                pve_mob_tactics_version=1,
                difficulty=room.get('pve_difficulty', 0), quality=quality,
                recommended_power=int(map_row.get('nBoosterAttack') or 489),
                minimum_power=int(map_row.get('nBoosterAttackMin') or 489),
                levels=levels, **deepcopy(_config()))


def frozen_profile(arena):
    profile = arena.state.get('battle', {}).get('pve_balance')
    if profile is None:
        return None
    room = arena.state.get('room') or {}
    if (profile.get('version') != 1 or profile.get('map_id') != arena.geometry.id
            or profile.get('requested_map_id') != requested_map(room)
            or profile.get('difficulty') != room.get('pve_difficulty', 0)
            or profile.get('npc_armor_curve') != 'source_iK_target_only_v1'):
        raise ValueError('Invalid frozen PvE balance contract')
    return profile


def npc_level(arena, template):
    """A fresh level row for the source NPC role; never mutate the table cache."""
    row = table_row('AINpcTemplate_table.xml', nTemplateId=template)
    role = int(row['nLevelId'])
    profile = frozen_profile(arena)
    if profile is None:
        return table_row('AINpcLevelTemplate_table.xml', nLevelId=role)
    if role not in range(1, 6) or str(role) not in profile['levels']:
        raise ValueError('Unsupported PvE NPC stat role: ' + str(role))
    return dict(profile['levels'][str(role)])


def enemy_multiplier(arena, template, key, *, camp=0):
    """M28 only: hostile finite-health NPCs, never escorts or inert traps.

    The optional keys live in the run's frozen profile. A pre-M28 profile or
    legacy save defaults to 1, even if the installed configuration is newer.
    Static map objects do not call this path. Negative source HP identifies
    indestructible hazards/hostages whose existing one-HP representation is
    not an enemy health pool.
    """
    if key not in ENEMY_MULTIPLIERS:
        raise ValueError('Unsupported PvE enemy multiplier: ' + key)
    profile = frozen_profile(arena)
    if profile is None or camp == 1 or key not in profile:
        return D(1)
    row = table_row('AINpcTemplate_table.xml', nTemplateId=template)
    arms = table_row('AINpcArmsTemplate_table.xml', nTemplateId=int(row['nArmsId']))
    if D(arms.get('fHpCoef') or '1') <= 0:
        return D(1)
    return D(_positive(profile[key], key))


def npc_stats(arena, template, *, camp=0):
    """Map-quality values before the existing NPC hostage/trap/speed rules."""
    row = table_row('AINpcTemplate_table.xml', nTemplateId=template)
    arms = table_row('AINpcArmsTemplate_table.xml', nTemplateId=int(row['nArmsId']))
    level = npc_level(arena, template)
    profile = frozen_profile(arena)
    result = {}
    for stat, field, coefficient, multiplier in STAT_FIELDS:
        value = D(level[field]) * D(arms.get(coefficient) or '1')
        # Negative HP is a source sentinel for invulnerable/support objects,
        # not a finite health pool. Existing PveNpc classification owns it.
        if profile is not None and (stat != 'iHp' or value > 0):
            value *= D(profile[multiplier])
        if stat == 'iHp' and value > 0:
            value *= enemy_multiplier(arena, template, 'enemy_hp_multiplier', camp=camp)
        if not value.is_finite() or (stat != 'iHp' and value < 0):
            raise ValueError('Invalid PvE NPC stat: ' + stat)
        result[stat] = str(value)
    return result


def hp_for(arena, template, *, camp=0):
    hp = D(npc_stats(arena, template, camp=camp)['iHp'])
    return max(D(0), hp) if frozen_profile(arena) is not None else hp


def armor_constant(arena, template):
    """Offline calibration for the NPC *receiving* damage, never for PvP.

    Source quality rows carry iK but the Flash server formula is unavailable.
    M23 explicitly uses it in the existing armor curve to avoid a fixed-300
    high-armor plateau. Player targets and pre-M23 runs retain V1's 300.
    """
    if frozen_profile(arena) is None:
        return D(300)
    value = D(npc_level(arena, template)['iK'])
    if not value.is_finite() or value <= 0:
        raise ValueError('Invalid PvE NPC armor constant')
    return value
