"""Pinned, read-only World Boss additions; never migrate user template tables.

Source: BangBang_BossTheGioi_HTML5_20261115/config. Only the two reviewed
World Boss buff corrections and one new scene item enter combat table copies.
Geometry is a packaged sidecar, not a new mutable SQLite setting. SHA pins
cover the delivered UTF-8 files (the JSON source is newline-normalized).
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

PINS = {
    'world_boss_map_40002.json': '030a19ca33a817ec503061c457787807c7be6f8de4d360e34be4509eec7f795b',
    'world_boss_template_changes.json': 'eb4cc4034c85bc7b743f976d1630a01f4051a89ef82746694af062497617d518',
}
TABLES = {'BuffTemplate_table.xml': 'client_BuffTemplate_table',
          'SceneItem_Templet.xml': 'client_SceneItem_Templet'}
FIELDS = frozenset(('iAspect', 'iPersistTime', 'nEffectType'))


@lru_cache(maxsize=2)
def _load(name):
    raw = Path(__file__).with_name(name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PINS[name]:
        raise ValueError('World Boss sidecar hash mismatch: ' + name)
    return json.loads(raw)


def geometry():
    return deepcopy(_load('world_boss_map_40002.json'))


def preload():
    for name in PINS:
        _load(name)


def merge_rows(filename, rows):
    """Merge by explicit business key, never source row ordinal or tank prefix."""
    table = TABLES.get(filename)
    if table is None:
        return rows
    result = [dict(row) for row in rows]
    for change in _load('world_boss_template_changes.json'):
        if change['table'] != table:
            continue
        key = change['key']
        found = [row for row in result if all(row.get(k) == v for k, v in key.items())]
        if len(found) > 1:
            raise ValueError('Ambiguous World Boss template: ' + repr(key))
        if change['operation'] == 'insert':
            after = {k: v['after'] for k, v in change['fields'].items() if v['after'] is not None}
            if found and any(found[0].get(k) != value for k, value in after.items()):
                raise ValueError('Conflicting World Boss scene item: ' + repr(key))
            if not found:
                result.append(after)
            continue
        if not found:
            raise ValueError('Missing World Boss base template: ' + repr(key))
        row = found[0]
        for field, values in change['fields'].items():
            if field in FIELDS and row.get(field) not in (values['before'], values['after']):
                raise ValueError('World Boss template preimage mismatch: ' + field)
            if values['after'] is None:
                row.pop(field, None)
            else:
                row[field] = values['after']
    return tuple(result)
