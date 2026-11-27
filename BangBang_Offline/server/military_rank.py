"""Native military stars derived from permanent garage tanks; frozen per battle."""
from battle_participants import human, private
import json
import struct
import time
from collections import defaultdict
from functools import lru_cache

import storage
from combat_math import D

FLAT = {1: ('iAttack', 'iEgAtk'), 3: ('iCentesis', 'iEgCtsis'),
        6: ('iArmor',), 7: ('iEgArmor',), 12: ('iHp',)}


@lru_cache(maxsize=8)
def _catalog(database):
    groups = defaultdict(list)
    for row in storage.template_rows('CrystalAttrTemplate_table.xml'):
        groups[int(row['nAttrGroupId'])].append(
            (int(row['nAttrType']), int(row['nValueType']), row['fAttrValue']))
    rows = []
    for row in storage.template_rows('MilitaryRankTemplate_table.xml'):
        attrs = []
        for key in ('nAttrGroupId', 'nSpecAttrGroupId'):
            group = int(row.get(key, 0))
            if group:
                if group not in groups:
                    raise ValueError(f'Missing military rank attribute group {group}')
                attrs.extend(groups[group])
        if any(not ((kind == 1 and attr in FLAT) or (kind == 2 and attr == 14))
               or not D(value).is_finite() for attr, kind, value in attrs):
            raise ValueError('Unsupported military rank attribute')
        rows.append((int(row.get('nTankStar', 0)), int(row['nRankId']),
                     row['szRankName'], tuple(attrs)))
    rows.sort()
    if not rows or rows[0][0] != 0 or len({r[0] for r in rows}) != len(rows):
        raise ValueError('Invalid military rank thresholds')
    return tuple(rows)


def build(stars):
    """Mirror MilitaryRankTool: cumulative groups at stars 1..current, not index."""
    totals = defaultdict(lambda: D(0))
    rank, name = 1, ''
    for threshold, ident, label, attrs in _catalog(str(storage.database_path())):
        if threshold > stars:
            break
        rank, name = ident, label
        # Native UI deliberately starts summing at 1, despite a template at 0.
        if threshold:
            for attr, kind, value in attrs:
                totals[attr, kind] += D(value)
    return dict(stars=stars, rank=rank, name=name,
                attributes=[[a, k, str(v)] for (a, k), v in sorted(totals.items())])


def maximum_build():
    """Virtual bot rank: the last real template threshold, not player ownership."""
    return build(_catalog(str(storage.database_path()))[-1][0])


def count_stars(records):
    levels = {}
    for record in records:
        tank = int(record['tank_id'])
        if tank in storage.DEFERRED_TANKS or record.get('cont_type', 0) != 0:
            continue
        level = int(record['level'])
        if not 1 <= level <= 6:
            raise ValueError('Invalid garage star level')
        levels[tank] = max(levels.get(tank, 1), level)
    return sum(level - 1 for level in levels.values())


def stars(db):
    return count_stars(json.loads(r[0]) for r in db.execute(
        'SELECT data FROM garage WHERE profile_id=?', (storage.profile_id(),)))


def rank_stamp(db, ident):
    row = db.execute('SELECT value FROM settings WHERE name=?',
                     (f'military_rank_achieved:{ident}',)).fetchone()
    return json.loads(row[0]) if row else None


def record_stars(db, ident, value, now_ns=None):
    """Use the caller's transaction; skins/strengthening/restarts cannot reset age."""
    old = rank_stamp(db, ident)
    if old and old['stars'] == value:
        return
    record = dict(stars=value, at_ns=time.time_ns() if now_ns is None else now_ns)
    db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
               (f'military_rank_achieved:{ident}', json.dumps(record)))


def initialize_ranking(db):
    # All pre-existing characters receive the same installation baseline. Their
    # actual historical upgrade times are unknown, not reconstructed from saves.
    now = time.time_ns()
    for row in db.execute('SELECT profile_id FROM worlds').fetchall():
        ident = row[0]
        records = [json.loads(r[0]) for r in db.execute(
            'SELECT data FROM garage WHERE profile_id=?', (ident,))]
        record_stars(db, ident, count_stars(records), now)


def login_payload(body, value):
    # CHAR_BASIC.nMilitaryStar at byte 122. milLevel is an unrelated legacy rank.
    data = bytearray(body)
    struct.pack_into('<I', data, 122, value)
    return bytes(data)


def update_packet(value):
    return 85, struct.pack('<BIH', 27, value, 0)


def apply_flat(stats, info):
    for attr, kind, value in info.get('military', {}).get('attributes', []):
        if kind == 1:
            for field in FLAT.get(attr, ()):
                stats[field] = str(D(stats[field]) + D(value))


def equipped(ident, info):
    from bot_loadouts import eligible
    if not eligible(ident, info):
        return False
    if info.get('human', ident == 1):
        return True
    stars = info.get('military_star', 0)
    return (type(stars) is int and stars > 0
            and info.get('military', {}).get('stars') == stars)


def cooldown_rate(actor):
    if not equipped(actor.id, actor.info):
        return D(0)
    return sum((D(value) for attr, kind, value in
                actor.info.get('military', {}).get('attributes', [])
                if attr == 14 and kind == 2), D(0))
