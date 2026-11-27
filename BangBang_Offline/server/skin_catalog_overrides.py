"""M33's three source-verified cosmetic unlocks, without a static DB migration.

The supplied Nov 2 snapshot approves Spider 10142's body/basic shot only and
Hikari II 865's base kit. M14 held both because its dependency walk included
obsolete skills/unrelated preload buffs. Their HTML5 closures are corrected by
the matching M33 presentation sidecar. No combat row, inventory or bonus is
changed here; the native C207 ownership checks remain authoritative.

Ham Chuc Long 10689 additionally has its complete source-paired presentation
graph and converted HTML5 closure verified. Its explicit 609xxx wire aliases
never replace Lac Long Quan's native 387xxx combat rows or mechanics.

Source: BangBang_BoSung_PvE_TroThu_Data_20261102.zip, reference_docs/
HienTaiBangbang.md (Nov 1 20:20) and config/static_settings.json. The static
reference SQLite SHA256 is 2781e332adfa9f697c7314b8eeafcf8be2cb0f08ef589b25716ca06bb8baaef2.
"""
from __future__ import annotations

from copy import deepcopy
import json
import skin_catalog_m34
import skin_catalog_m35

SUPPORT_SETTING = 'skin_support_phase1'
EFFECT_SETTING = 'skin_effect_maps'
LEGACY_UNAVAILABLE = 'Skin đang thiếu hoặc chưa xác minh đủ tài nguyên, chưa thể mặc.'

# Exact source item aliases. An unrelated item pointing at the same exterior
# must not become usable/grantable merely because its numeric exterior matches.
APPROVED_ITEMS = {
    (10000008, 10142): frozenset((2900802, 2910002)),
    (10000107, 865): frozenset((2970211,)),
    (10000094, 10689): frozenset((2909413,)),
}
SPIDER_EFFECTS = {
    'tank': 10000008, 'skill': {'303100': 403100}, 'buff': {}, 'scene': {},
}
LAC_EFFECTS = {
    'tank': 10000094,
    'skill': {
        '387100': 609100, '387101': 609101, '387201': 609201,
        '387211': 609211, '387221': 609221, '387231': 609231,
        '387241': 609241, '387251': 609251, '387301': 609301,
        '387311': 609311, '387321': 609321, '387331': 609331,
        '387401': 609401,
    },
    'buff': {
        '387101': 609101, '387102': 609102, '387103': 609103,
        '387104': 609104, '387105': 609105,
        '387201': 609201, '387202': 609202, '387203': 609203,
        '387206': 609206, '387207': 609207, '387210': 609210,
        '387301': 609301, '387302': 609302, '387303': 609303,
        '387304': 609304, '387330': 609330, '387340': 609340,
        '387313': 609313, '387314': 609314, '387316': 609316,
        '387318': 609318, '387312': 609312, '387327': 609327,
        '387337': 609337, '387339': 609339,
        '387402': 609402, '387404': 609404, '387405': 609405,
        '387351': 609351, '387352': 609352, '387353': 609353,
        '387354': 609354,
    },
    'scene': {
        '387321': 609321, '387322': 609322, '387323': 609323,
        '387324': 609324, '387325': 609325,
        '387331': 609331, '387332': 609332, '387333': 609333,
        '387334': 609334, '387335': 609335, '387401': 609401,
    },
    'npc': {},
}
_EXPECTED_MAPS = {
    10142: SPIDER_EFFECTS,
    865: {'tank': 10000107},  # Source base kit; no separate visual IDs.
    10689: LAC_EFFECTS,
}
_MISSING = object()


def _guard_map(value, expected):
    if not isinstance(value, dict) or set(value) - {'tank', 'skill', 'buff', 'scene', 'npc'}:
        return False
    return (value.get('tank') == expected['tank']
            and all(value.get(kind, {}) == expected.get(kind, {})
                    for kind in ('skill', 'buff', 'scene', 'npc')))


def effective_settings(support, effects):
    """Return private effective copies; reject unknown/custom target preimages.

    Only absent, known M32 held, or already-approved values can be opened.
    10689 was absent, not a historical blocked leaf: do not override a block.
    Other tanks/skins and every unrelated mapping are preserved byte-for-value.
    In particular, an old 403xxx teleport/immunity map is never merged or
    silently replaced by the normal-shot-only contract.
    """
    if not isinstance(support, dict) or not isinstance(effects, dict):
        raise ValueError('M33: danh mục skin tĩnh không đúng cấu trúc.')
    result, maps = deepcopy(support), deepcopy(effects)
    for (tank, exterior), _items in APPROVED_ITEMS.items():
        tank_key, ext_key = str(tank), str(exterior)
        group = result.setdefault(tank_key, {})
        if not isinstance(group, dict):
            raise ValueError(f'M33: danh mục skin tank {tank} khác nguồn đã kiểm.')
        before = group.get(ext_key, _MISSING)
        allowed_statuses = ('ready',) if exterior == 10689 else ('ready', LEGACY_UNAVAILABLE)
        if before is not _MISSING and before not in allowed_statuses:
            raise ValueError(f'M33: trạng thái skin {tank}/{exterior} khác nguồn đã kiểm.')
        old_map = maps.get(ext_key, _MISSING)
        if old_map is not _MISSING and not _guard_map(old_map, _EXPECTED_MAPS[exterior]):
            raise ValueError(f'M33: ánh xạ skin {tank}/{exterior} khác nguồn đã kiểm.')
        group[ext_key] = 'ready'
    for exterior in (10142, 10689):
        if str(exterior) not in maps:
            maps[str(exterior)] = deepcopy(_EXPECTED_MAPS[exterior])
    # 865 has no separate skill/buff/scene/NPC mapping in the source.
    return skin_catalog_m35.effective_settings(*skin_catalog_m34.effective_settings(result, maps))


def item_matches(template_id, tank, exterior):
    """Keep the release's unlock limited to the four reviewed item aliases."""
    if not skin_catalog_m34.item_matches(template_id, tank, exterior):
        return False
    if not skin_catalog_m35.item_matches(template_id, tank, exterior):
        return False
    allowed = APPROVED_ITEMS.get((int(tank), int(exterior)))
    return allowed is None or int(template_id) in allowed


def load(db):
    """Read on the caller's existing connection; never write static settings."""
    values = []
    for key in (SUPPORT_SETTING, EFFECT_SETTING):
        row = db.execute('SELECT value FROM settings WHERE name=?', (key,)).fetchone()
        values.append(json.loads(row[0]) if row else {})
    # Checking exact rows prevents a custom item-to-tank mapping from being
    # accidentally opened by a code-only update. Last ordinal is native policy.
    for (tank, exterior), items in APPROVED_ITEMS.items():
        for item in sorted(items):
            row = db.execute(
                'SELECT nType,nContType,iReuseA,iReuseB FROM client_ItemTemplate_table '
                'WHERE nItemId=? ORDER BY _ordinal DESC LIMIT 1', (str(item),)).fetchone()
            if row is None or tuple(str(v) for v in row) != ('29', '6', str(tank), str(exterior)):
                raise ValueError(f'M33: vật phẩm skin {item} khác nguồn đã kiểm.')
    skin_catalog_m34.validate_source_rows(db)
    skin_catalog_m35.validate_source_rows(db)
    return effective_settings(*values)


def item_template(db, template_id):
    """Read-only effective item identity; C207 keeps ownership/phase checks."""
    return skin_catalog_m35.item_template(db, template_id)


def effective_items(db, items):
    """Private read-only mail catalog overlay; no SQL migrations or grants."""
    return skin_catalog_m35.effective_items(db, items)
