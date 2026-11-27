"""Persistent native item containers; captured inventory is only the initial seed."""
from __future__ import annotations

import json
import struct
import time

import storage

SETTING = 'inventory'
FIELDS = ('template_id', 'life_time', 'ext_flag', 'count', 'level', 'up_level',
          'exp', 'rank', 'up_cost', 'rank_cost', 'create_time', 'slot_no')
ITEM = struct.Struct('<IIIiBBiBiiIh')


def grocery_capacity(db):
    row = db.execute('SELECT value FROM settings WHERE name=?',
                     (f'inventory_slots:{storage.profile_id()}',)).fetchone()
    return int(row[0]) if row else 45


def parse_list(payload):
    container, count = struct.unpack_from('<IH', payload)
    items, pos = [], 6
    for _ in range(count):
        size, = struct.unpack_from('<H', payload, pos)
        pos += 2
        uuid = payload[pos:pos + size].decode('utf-8')
        pos += size
        item = dict(zip(FIELDS, ITEM.unpack_from(payload, pos)))
        pos += ITEM.size
        items.append(dict(uuid=uuid, **item))
    return container, items, payload[pos]


def item_payload(item):
    uuid = item['uuid'].encode('utf-8')
    return struct.pack('<H', len(uuid)) + uuid + ITEM.pack(*(item[k] for k in FIELDS))


def list_payload(container, items, notify_type=1):
    return (struct.pack('<IH', int(container), len(items))
            + b''.join(item_payload(item) for item in items) + bytes([notify_type]))


def initialize():
    with storage.connection(write=True) as db:
        if db.execute('SELECT 1 FROM settings WHERE name=?', (storage.setting_key(SETTING),)).fetchone():
            return
        containers = {}
        for row in db.execute('SELECT frame FROM lobby_frames ORDER BY ordinal'):
            frame = bytes(row[0])
            if struct.unpack_from('<H', frame, 2)[0] == 1100:
                container, items, _ = parse_list(frame[8:])
                containers[str(container)] = items
        save(containers, db)


def load(db=None):
    if db is None:
        with storage.connection() as opened:
            return load(opened)
    row = db.execute('SELECT value FROM settings WHERE name=?', (storage.setting_key(SETTING),)).fetchone()
    if row is None:
        raise RuntimeError('Inventory has not been initialized')
    return json.loads(row[0])


def save(containers, db):
    db.execute('INSERT INTO settings(name,value) VALUES(?,?) '
               'ON CONFLICT(name) DO UPDATE SET value=excluded.value',
               (storage.setting_key(SETTING), json.dumps(containers, ensure_ascii=False, separators=(',', ':'))))


def upgrade_material_ids():
    owned = {r['tank_id'] for r in storage.garage()}
    ids = set()
    for filename in ('TankUpTemplate_table.xml', 'TankStrengthenTemplate_table.xml'):
        for row in storage.template_rows(filename):
            if int(row['nTankId']) in owned:
                ids.update(int(row[f'nItemId{i}']) for i in range(1, 6)
                           if int(row.get(f'nItemId{i}', 0)) > 0
                           and int(row.get(f'iItemCount{i}', 0)) > 0)
    return ids


def grant_upgrade_materials(count=500_000):
    """Explicit one-time test grant, never called by login or normal startup."""
    if not 0 < count < 2**31:
        raise ValueError('Invalid item count')
    wanted = upgrade_material_ids()
    templates = {int(r['nItemId']): r for r in storage.template_rows('ItemTemplate_table.xml')}
    for item_id in wanted:
        row = templates[item_id]
        if int(row.get('nAutoUse', 0)) or int(row['nContType']) not in (2, 3):
            raise ValueError(f'Unexpected upgrade material {item_id}')
    initialize()
    with storage.connection(write=True) as db:
        containers = load(db)
        for item_id in sorted(wanted):
            container = str(templates[item_id]['nContType'])
            items = containers.setdefault(container, [])
            existing = [item for item in items if item['template_id'] == item_id]
            # Keep UUID/slot of an existing stack; preserve all unrelated items.
            if existing:
                existing[0]['count'] = count
                for extra in existing[1:]:
                    items.remove(extra)
            else:
                slot = 0
                occupied = {item['slot_no'] for item in items}
                while slot in occupied:
                    slot += 1
                item = {key: 0 for key in FIELDS}
                item.update(uuid=f'offline-material-{item_id}', template_id=item_id,
                            count=count, create_time=int(time.time()), slot_no=slot)
                items.append(item)
        save(containers, db)
    return sorted(wanted)
