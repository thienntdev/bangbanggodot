"""Native C75 character rename. Identity/login and all ownership stay unchanged."""
import json
import struct
import time
import unicodedata

import inventory
import storage
from cosmetic_shop import tip

CARD = 2600002


def normalized(value):
    return unicodedata.normalize('NFC', value).strip()


def request(payload):
    size, = struct.unpack_from('<H', payload)
    if not 1 <= size <= 96:
        raise ValueError('Tên nhân vật không hợp lệ.')
    name = normalized(payload[2:2 + size].decode('utf-8'))
    sex, = struct.unpack_from('<i', payload, 2 + size)
    end = 6 + size
    if (len(payload) - end not in (0, (-(6 + end)) % 8) or any(payload[end:])
            or sex != 0):
        raise ValueError('Yêu cầu đổi tên không hợp lệ.')
    # Original RenameFrame uses CHAR_NAME_LENGTH_LIMIT=12. Reject hidden
    # controls, bidi overrides and markup, while retaining Vietnamese/Unicode.
    if (not 1 <= len(name) <= 12 or any(unicodedata.category(c)[0] == 'C'
            or c in '<>&' for c in name)):
        raise ValueError('Tên cần từ 1–12 ký tự, không chứa ký tự điều khiển hoặc < > &.')
    return name


def apply(state, payload, db):
    try:
        name = request(payload)
        if state.get('battle') or state.get('tank_selection'):
            raise ValueError('Hãy về sảnh để đổi tên nhân vật.')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT state FROM worlds WHERE profile_id=?',
                         (storage.profile_id(),)).fetchone()
        if not row:
            raise ValueError('Không tìm thấy nhân vật.')
        saved = json.loads(row[0])
        # A retry after a lost acknowledgement must not consume a second card.
        if saved['name'] == name:
            db.commit()
            state['name'] = name
            return True, [], None
        for ident, data in db.execute('SELECT profile_id,state FROM worlds'):
            if ident != storage.profile_id() and normalized(json.loads(data)['name']).casefold() == name.casefold():
                raise ValueError('Tên này đã có nhân vật khác sử dụng.')
        bags = inventory.load(db)
        cards = sorted((v for v in bags.get('2', []) if v['template_id'] == CARD
                        and v['count'] > 0 and v.get('life_time', 0) == 0), key=lambda v: v['slot_no'])
        if not cards:
            raise ValueError('Cần 1 Thẻ Đổi Tên để đổi tên nhân vật.')
        cards[0]['count'] -= 1
        if cards[0]['count'] == 0:
            bags['2'].remove(cards[0])
        inventory.save(bags, db)
        new_state = dict(state, name=name)
        db.execute('UPDATE worlds SET state=?,updated_ms=? WHERE profile_id=?',
                   (json.dumps(new_state, ensure_ascii=False, separators=(',', ':')),
                    time.time_ns() // 1_000_000, storage.profile_id()))
        db.commit()
        state['name'] = name
        return True, [(1100, inventory.list_payload(2, bags.get('2', [])))], None
    except (ValueError, UnicodeError, struct.error) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else 'Yêu cầu đổi tên không hợp lệ.'
        return False, [tip(75, message)], message
    except BaseException:
        db.rollback()
        raise
