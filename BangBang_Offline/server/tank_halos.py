"""Native C210/S1160: cosmetic-only halo selection, scoped to the owner.

The five custom choices have both original garage and battle assets. The two
incomplete native choices stay closed; 7003002 is the native default, sent as0.
Inventory is neither granted nor consumed by an equip operation.
"""
import json
import struct
import time

import inventory
import storage
from cosmetic_shop import tip

SUPPORTED = frozenset((5500002, 5500004, 5500005, 5500006, 5500007))


def request(payload):
    size, = struct.unpack_from('<H', payload)
    if not 0 < size <= 200:
        raise ValueError('Yêu cầu vòng sáng không hợp lệ.')
    uuid = payload[2:2 + size].decode('utf-8')
    halo, = struct.unpack_from('<I', payload, 2 + size)
    end = 6 + size
    if len(payload) - end not in (0, (-(6 + end)) % 8) or any(payload[end:]):
        raise ValueError('Yêu cầu vòng sáng không hợp lệ.')
    return uuid, halo


def apply(state, payload, db):
    uuid, halo = '', 0
    try:
        uuid, halo = request(payload)
        if state.get('battle'):
            raise ValueError('Hãy về sảnh hoặc phòng chờ để đổi vòng sáng.')
        if halo and halo not in SUPPORTED:
            raise ValueError('Vòng sáng này chưa đủ tài nguyên gốc để sử dụng.')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT data FROM garage WHERE profile_id=? AND uuid=?',
                         (storage.profile_id(), uuid)).fetchone()
        if row is None:
            raise ValueError('Bạn chưa sở hữu tank này.')
        record = json.loads(row[0])
        if record.get('cont_type', 0) != 0 or record['tank_id'] in storage.DEFERRED_TANKS:
            raise ValueError('Chỉ trang bị vòng sáng cho tank đang sở hữu vĩnh viễn.')
        if halo:
            # Native HaloItemFrame reads container9, not the grocery/skin bag.
            items = [item for item in inventory.load(db).get('9', [])
                     if item['template_id'] == halo and item['count'] > 0]
            if not items:
                raise ValueError('Bạn chưa sở hữu vòng sáng này.')
            if not any(item.get('life_time', 0) == 0 for item in items):
                raise ValueError('Hiện chỉ hỗ trợ trang bị vòng sáng vĩnh viễn.')
            item = db.execute('SELECT nType,nContType,iReuseA FROM client_ItemTemplate_table '
                              'WHERE nItemId=? ORDER BY _ordinal DESC LIMIT 1', (str(halo),)).fetchone()
            if not item or tuple(map(int, item[:2])) != (55, 9):
                raise ValueError('Dữ liệu vòng sáng không hợp lệ.')
        record['halo_id'] = halo
        selected = (state.get('selected_tank_uuid') == uuid or
                    not state.get('selected_tank_uuid') and state['tank_id'] == record['tank_id'])
        new_state = dict(state)
        if selected:
            new_state.update(selected_tank_uuid=uuid, halo_id=halo)
        db.execute('UPDATE garage SET data=? WHERE profile_id=? AND uuid=?',
                   (json.dumps(record, ensure_ascii=False, separators=(',', ':')), storage.profile_id(), uuid))
        db.execute('UPDATE worlds SET state=?,updated_ms=? WHERE profile_id=?',
                   (json.dumps(new_state, ensure_ascii=False, separators=(',', ':')),
                    time.time_ns() // 1_000_000, storage.profile_id()))
        db.commit()
        state.update(new_state)
        raw = uuid.encode('utf-8')
        return record, [(1160, struct.pack('<BH', 1, len(raw)) + raw + struct.pack('<I', halo))], None
    except (ValueError, UnicodeError, struct.error) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else 'Yêu cầu vòng sáng không hợp lệ.'
        raw = uuid.encode('utf-8')
        return None, [tip(210, message), (1160, struct.pack('<BH', 0, len(raw)) + raw + struct.pack('<I', halo))], message
    except BaseException:
        db.rollback()
        raise
