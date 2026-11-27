"""M34's source-closed Hai Linh skin; no static migration or item grants.

The supplied November 17 data closes10651's HTML5 presentation. Five other
candidate skins remain unavailable because exact inventory icons/portrait
are missing. Their proposed source graphs are evidence, not runtime unlocks.
Native combat remains353xxx; only final presentation IDs are mapped.
"""
from __future__ import annotations

from copy import deepcopy

LEGACY_UNAVAILABLE = 'Skin đang thiếu hoặc chưa xác minh đủ tài nguyên, chưa thể mặc.'
APPROVED_ITEMS = {(10000079, 10651): frozenset((2907913,))}

# Explicit reviewed pairs, never a numeric prefix/offset transformation.
HAI_LINH_EFFECTS = {
    'tank': 10000079,
    'skill': {'353100': 477100, '353101': 477101, '353111': 477111,
              '353201': 477201, '353301': 477301, '353501': 477501,
              '353701': 477701},
    'buff': {'353300': 477300, '353304': 477304, '353401': 477401,
             '353403': 477403, '353501': 477501, '353601': 477601},
    'scene': {'353205': 477205, '353301': 477301, '353801': 477801},
    # Native passive water-wall ObjInfo(type3), not the unused AINpc graph.
    'npc': {'353201': 477201},
}
_MISSING = object()


def item_matches(template_id, tank, exterior):
    """Only the exact source item may equip/grant the newly approved exterior."""
    allowed = APPROVED_ITEMS.get((int(tank), int(exterior)))
    return allowed is None or int(template_id) in allowed


def _matches_map(value):
    return (isinstance(value, dict)
            and not set(value) - {'tank', 'skill', 'buff', 'scene', 'npc'}
            and value.get('tank') == HAI_LINH_EFFECTS['tank']
            and all(value.get(kind, {}) == HAI_LINH_EFFECTS[kind]
                    for kind in ('skill', 'buff', 'scene', 'npc')))


def effective_settings(support, effects):
    """Copy effective catalogs; unknown/custom target preimages fail closed."""
    if not isinstance(support, dict) or not isinstance(effects, dict):
        raise ValueError('M34: danh mục skin tĩnh không đúng cấu trúc.')
    result, maps = deepcopy(support), deepcopy(effects)
    group = result.setdefault('10000079', {})
    if not isinstance(group, dict):
        raise ValueError('M34: danh mục skin tank10000079 khác nguồn đã kiểm.')
    before = group.get('10651', _MISSING)
    if before is not _MISSING and before not in ('ready', LEGACY_UNAVAILABLE):
        raise ValueError('M34: trạng thái skin10000079/10651 khác nguồn đã kiểm.')
    old_map = maps.get('10651', _MISSING)
    if old_map is not _MISSING and not _matches_map(old_map):
        raise ValueError('M34: ánh xạ skin10000079/10651 khác nguồn đã kiểm.')
    group['10651'] = 'ready'
    maps.setdefault('10651', deepcopy(HAI_LINH_EFFECTS))
    return result, maps


def validate_source_rows(db):
    """Read on the caller connection, honor last ordinal, never write SQL."""
    row = db.execute(
        'SELECT nType,nContType,iReuseA,iReuseB FROM client_ItemTemplate_table '
        'WHERE nItemId=? ORDER BY _ordinal DESC LIMIT 1', ('2907913',)).fetchone()
    if row is None or tuple(str(v) for v in row) != ('29', '6', '10000079', '10651'):
        raise ValueError('M34: vật phẩm Phù Thủy Hải Linh2907913 khác nguồn đã kiểm.')
