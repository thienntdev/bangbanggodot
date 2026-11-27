"""Native C207 appearance changes. Combat continues to use the base tank kit."""
from __future__ import annotations

import json
import struct
import time

import inventory
import skin_catalog_overrides
import storage
from storage_import import tank_instance_payload

CATALOG_SETTING = 'skin_support_phase1'

# M40 level appearances are earned by tank level, not inventory items. Keep
# the existing C207 transaction/acknowledgement and reserve only these exact
# tokens; arbitrary external IDs and another tank's appearances remain invalid.
LEVEL_LOOK_PREFIX = 'level-look:'
LEVEL_LOOKS = {
    10000094: ((761, 1), (762, 4), (763, 5)),
    10000097: ((791, 1), (792, 4), (793, 5)),
    10000113: ((892, 1), (893, 4), (894, 5)),
}


def level_look_external(record, token):
    for external, required_level in LEVEL_LOOKS.get(record['tank_id'], ()):
        if token == f'{LEVEL_LOOK_PREFIX}{external}':
            if int(record['level']) < required_level:
                raise ValueError(f'Ngoại hình này cần tank cấp {required_level}.')
            return external
    raise ValueError('Ngoại hình theo cấp không thuộc tank này.')


def _request(payload):
    strings, pos = [], 0
    for _ in range(2):
        size, = struct.unpack_from('<H', payload, pos)
        pos += 2
        if size > 200 or pos + size > len(payload):
            raise ValueError('Yêu cầu đổi skin không hợp lệ.')
        strings.append(payload[pos:pos + size].decode('utf-8'))
        pos += size
    container, = struct.unpack_from('<B', payload, pos)
    pos += 1
    if (not strings[0] or len(payload) - pos not in (0, (-(6 + pos)) % 8)
            or any(payload[pos:])):
        raise ValueError('Yêu cầu đổi skin không hợp lệ.')
    return *strings, container


def base_external(record, db):
    """Restore approved fallback artwork, never an unavailable original model."""
    for row in db.execute("SELECT value FROM settings WHERE name LIKE 'temporary_%_visuals'"):
        setting = json.loads(row[0])
        candidates = [setting, *setting.get('original_rows', []),
                      *setting.get('original_garage', [])]
        for entry in candidates:
            if entry.get('tank_id') == record['tank_id'] and entry.get('temporary_external'):
                return int(entry['temporary_external'])
    # Zero is the native sentinel for the current level's default appearance.
    return 0


def apply(state, payload, db):
    """Persist the garage and selected room appearance before acknowledging C207."""
    try:
        uuid, skin_uuid, container = _request(payload)
        if state.get('battle'):
            raise ValueError('Hãy về sảnh hoặc phòng chờ để đổi skin.')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT data FROM garage WHERE profile_id=? AND uuid=?',
                         (storage.profile_id(), uuid)).fetchone()
        if row is None:
            raise ValueError('Bạn chưa sở hữu tank này.')
        record = json.loads(row[0])
        if (record['tank_id'] in storage.DEFERRED_TANKS or container != 0
                or record.get('cont_type', 0) != container):
            raise ValueError('Tank này hiện chưa dùng được skin.')
        if skin_uuid.startswith(LEVEL_LOOK_PREFIX):
            external = level_look_external(record, skin_uuid)
        elif skin_uuid:
            item = next((item for item in inventory.load(db).get('6', [])
                         if item['uuid'] == skin_uuid and item['count'] > 0), None)
            if item is None:
                raise ValueError('Bạn chưa sở hữu skin này.')
            if item.get('life_time', 0):
                raise ValueError('Skin có thời hạn chưa được hỗ trợ trong lượt này.')
            item_row = skin_catalog_overrides.item_template(db, item['template_id'])
            if (not item_row or int(item_row['nType']) != 29
                    or int(item_row['iReuseA'] or 0) != record['tank_id']):
                raise ValueError('Skin không thuộc tank này.')
            external = int(item_row['iReuseB'])
            catalog, _effects = skin_catalog_overrides.load(db)
            if not skin_catalog_overrides.item_matches(item['template_id'], record['tank_id'], external):
                raise ValueError('Vật phẩm skin này chưa được kiểm tra tài nguyên.')
            supported = catalog.get(str(record['tank_id']), {})
            reason = supported.get(str(external), 'Skin này chưa được kiểm tra tài nguyên.')
            if reason != 'ready':
                raise ValueError(reason)
        else:
            external = base_external(record, db)
        record['external_id'] = external
        selected = (state.get('selected_tank_uuid') == uuid or
                    not state.get('selected_tank_uuid') and state['tank_id'] == record['tank_id'])
        new_state = dict(state)
        if selected:
            new_state.update(selected_tank_uuid=uuid, tank_ext=external)
        db.execute('UPDATE garage SET data=? WHERE profile_id=? AND uuid=?',
                   (json.dumps(record, ensure_ascii=False, separators=(',', ':')),
                    storage.profile_id(), uuid))
        db.execute('UPDATE worlds SET state=?,updated_ms=? WHERE profile_id=?',
                   (json.dumps(new_state, ensure_ascii=False, separators=(',', ':')),
                    time.time_ns() // 1_000_000, storage.profile_id()))
        db.commit()
        state.update(new_state)
        visible = dict(record, ext_flag=(record['ext_flag'] & ~2) | (2 if selected else 0))
        return record, [(1151, tank_instance_payload(visible) + b'\x0a')], None
    except (ValueError, UnicodeError, struct.error) as exc:
        db.rollback()
        # Native SystemTip 3997 is SHOW_ON_UI with content "%s". S1153 only
        # recognizes upgrade/strengthen failures and cannot explain skin errors.
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else 'Yêu cầu đổi skin không hợp lệ.'
        raw = message.encode('utf-8')
        return None, [(1501, struct.pack('<IiHH', 207, 3997, 1, len(raw)) + raw)], message
    except BaseException:
        db.rollback()
        raise
