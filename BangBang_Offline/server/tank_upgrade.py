"""UI1 tank progression: C204 strengthens, C203 advances one tank level."""
from __future__ import annotations

import json
import struct
import time

import inventory
import storage
import military_rank
from combat_data import table_row
from storage_import import tank_instance_payload


def next_strength(record):
    try:
        return table_row('TankStrengthenTemplate_table.xml', nTankId=record['tank_id'],
                         nTankLevel=record['level'], nLevel=record['stth_level'] + 1)
    except ValueError:
        return None


def costs(row):
    result = {}
    for i in range(1, 6):
        item_id, count = int(row.get(f'nItemId{i}', 0)), int(row.get(f'iItemCount{i}', 0))
        if item_id and count:
            result[item_id] = result.get(item_id, 0) + count
    return result


def apply(state, message_id, payload, db):
    """Commit level, material consumption and selected tank together before replying."""
    uuid = ''
    try:
        size, = struct.unpack_from('<H', payload)
        if not 0 < size <= 200 or len(payload) < 2 + size:
            raise ValueError('Malformed tank UUID')
        uuid = payload[2:2 + size].decode('utf-8')
        end = 2 + size
        if message_id == 204:
            mode, = struct.unpack_from('<I', payload, end)
            end += 4
            if mode != 0:
                raise ValueError('Only native material strengthening is supported')
        elif message_id != 203:
            raise ValueError('Invalid upgrade operation')
        # CNetConnection.send pads message ID (2) + reserved (4) + body to
        # eight bytes, excluding the outer length (2). Offline UUIDs require
        # seven padding bytes for C204, but only three for C203.
        padding = (-(6 + end)) % 8
        if len(payload) - end not in (0, padding) or any(payload[end:]):
            raise ValueError('Malformed upgrade request')
        if state.get('battle'):
            raise ValueError('Cannot upgrade during a battle')
        db.execute('BEGIN IMMEDIATE')
        saved = db.execute('SELECT data FROM garage WHERE profile_id=? AND uuid=?',
                           (storage.profile_id(), uuid)).fetchone()
        if saved is None:
            raise ValueError('Tank is not owned')
        record = json.loads(saved[0])
        if record['tank_id'] in storage.DEFERRED_TANKS or record.get('cont_type', 0) != 0:
            raise ValueError('Tank is unavailable or rented')
        strength = next_strength(record)
        if message_id == 204:
            if strength is None:
                raise ValueError('Already fully strengthened at this level')
            row, op = strength, 4  # TIOT_STTEN_SUCCEED
        else:
            if strength is not None:
                raise ValueError('Strengthen this level first, as required by UI1')
            if record['level'] >= 6:
                raise ValueError('Tank is already level 6')
            table_row('TankUpTemplate_table.xml', nTankId=record['tank_id'], nLevel=record['level'] + 1)
            row = table_row('TankUpTemplate_table.xml', nTankId=record['tank_id'], nLevel=record['level'])
            op = 2  # TIOT_UP_SUCCEED
        if int(row.get('nWinRate1', 0)) != 100:
            raise ValueError('Unverified success rate')
        required = costs(row)
        if not required:
            raise ValueError('Missing upgrade recipe')
        containers = inventory.load(db)
        for item_id, count in required.items():
            available = sum(item['count'] for items in containers.values() for item in items
                            if item['template_id'] == item_id)
            if available < count:
                raise ValueError(f'Not enough material {item_id}')
        changed = []
        for item_id, count in required.items():
            for container, items in containers.items():
                for item in items:
                    if item['template_id'] != item_id or count == 0:
                        continue
                    taken = min(count, item['count'])
                    item['count'] -= taken
                    count -= taken
                    changed.append((int(container), item.copy()))
                items[:] = [item for item in items if item['count'] > 0]
        if message_id == 204:
            record['stth_level'] += 1
        else:
            record['level'] += 1
            record['stth_level'] = 0
            record['stth_count'] = 0
            record['n_exp'] = 0
        selected = (state.get('selected_tank_uuid') == uuid or
                    not state.get('selected_tank_uuid') and state['tank_id'] == record['tank_id'])
        new_state = dict(state)
        if selected:
            new_state.update(selected_tank_uuid=uuid, tank_level=record['level'],
                             tank_strength=record['stth_level'])
        db.execute('UPDATE garage SET data=? WHERE profile_id=? AND uuid=?',
                   (json.dumps(record, ensure_ascii=False, separators=(',', ':')),
                    storage.profile_id(), uuid))
        if message_id == 203:
            new_state['military_star'] = military_rank.stars(db)
            military_rank.record_stars(db, storage.profile_id(), new_state['military_star'])
        inventory.save(containers, db)
        db.execute('UPDATE worlds SET state=?,updated_ms=? WHERE profile_id=?',
                   (json.dumps(new_state, ensure_ascii=False, separators=(',', ':')),
                    time.time_ns() // 1_000_000, storage.profile_id()))
        db.commit()
        state.update(new_state)
        # Refresh affected containers: this also removes empty stacks correctly.
        packets = [(1100, inventory.list_payload(c, containers[str(c)], 3))
                   for c in sorted({c for c, _ in changed})]
        if message_id == 203:
            # Set stars before LEVEL_UPDATE refreshes the native garage panel.
            packets.append(military_rank.update_packet(state['military_star']))
        visible = dict(record, ext_flag=(record['ext_flag'] & ~2) | (2 if selected else 0))
        packets.append((1151, tank_instance_payload(visible) + bytes([op])))
        return record, packets, None
    except (ValueError, UnicodeError, struct.error) as exc:
        db.rollback()
        raw = uuid.encode('utf-8')
        failure = struct.pack('<H', len(raw)) + raw + struct.pack('<I', 5 if message_id == 204 else 3)
        return None, [(1153, failure)], str(exc)
    except BaseException:
        db.rollback()
        raise
