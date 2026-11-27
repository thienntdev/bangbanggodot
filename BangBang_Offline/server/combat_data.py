"""Read the existing client tables without substituting provisional V1 values.

SkillData and BulletExhibitTableData call HashMap.put in XML order, so the final
SkillTemplate/BulletExhibit entry for an ID wins. Other ambiguous tables need a verified parser policy;
in particular, this module does not guess how duplicate Effect IDs execute.
Missing fields remain absent. Consumers must not silently invent a stat/skill.
"""
from __future__ import annotations

from functools import lru_cache
from storage import template_rows, database_path


class _TableRows(tuple):
    """Indexes belong to this loaded table, so clearing _rows drops them too."""
    def __init__(self, rows):
        self.indexes = {}

    def candidates(self, keys):
        if not keys:
            return self
        field, value = keys[0]
        if field not in self.indexes:
            index = {}
            for row in self:
                index.setdefault(row.get(field), []).append(row)
            self.indexes[field] = index
        return self.indexes[field].get(str(value), ())


@lru_cache(maxsize=16)
def _rows(filename: str, database: str) -> tuple[dict[str, str], ...]:
    from world_boss_data import merge_rows
    return _TableRows(merge_rows(filename, template_rows(filename)))


def preload():
    """Read static combat tables before accepting players, not on first hit."""
    database = str(database_path())
    # World Boss NPCs spawn after the native introduction. Warm their three
    # static tables here, before accepting sockets, rather than opening SQLite
    # for the first spawn/fireball inside a live combat tick.
    for table in ('TankBase', 'TankUp', 'TankStrengthen', 'Skill', 'Effect', 'Buff',
                  'AINpc', 'AINpcArms', 'AINpcLevel'):
        _rows(table + 'Template_table.xml', database)


@lru_cache(maxsize=4096)
def _matching_row(filename: str, database: str, keys: tuple) -> dict:
    matches = [row for row in _rows(filename,database).candidates(keys)
               if all(row.get(key) == str(value) for key, value in keys)]
    if not matches:
        raise ValueError(f"Missing battle template {filename}: {keys}")
    if len(matches) > 1 and filename not in ("SkillTemplate_table.xml", "BulletExhibit_table.xml"):
        raise ValueError(f"Ambiguous battle template {filename}: {keys}; "
                         "duplicate handling has not been verified")
    # BulletExhibitTableData.parseData likewise uses HashMap.put in XML order.
    # Return a copy so a live buff or caller cannot mutate cached source data.
    # A private dict supports a C-level copy instead of reconstructing every
    # field from a tuple on every buff/stat lookup. It is never returned by
    # table_row or exposed to mutable game state. Same cache keys/lifetime.
    return dict(matches[-1])


def table_row(filename: str, **keys: int) -> dict[str, str]:
    return _matching_row(filename,str(database_path()),tuple(sorted(keys.items()))).copy()


def active_buff_effect_types(templates):
    """Static template lookup only; callers still filter live owner/expiry.

    Resolve the database once per scan, not once per active buff. Do not cache
    active sets or permanently pin a training database into a gameplay server.
    Clearing _matching_row invalidates these reads exactly like table_row.
    """
    if not templates:
        return set()
    database = str(database_path())
    return {int(_matching_row('BuffTemplate_table.xml',database,(('nBuffId',template),))['nEffectType'])
            for template in templates}


def tank_stats(tank_id, level, strength=0):
    stats = table_row('TankUpTemplate_table.xml', nTankId=tank_id, nLevel=level)
    if strength:
        row = table_row('TankStrengthenTemplate_table.xml', nTankId=tank_id,
                        nTankLevel=level, nLevel=strength)
        # TankInstanceTool adds the current strengthening row, not all prior rows.
        for stat, bonus in (('iHp','nHpValue'),('iAttack','nAttackValue'),('iEgAtk','nAttackValue')):
            stats[stat] = str(int(stats.get(stat,0)) + int(row.get(bonus,0)))
    return stats
