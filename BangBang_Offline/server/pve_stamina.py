"""Persistent native C78 stamina purchase: 1 Xu (COIN_CASH) buys 100 thew.

The Flash RequestBuyThew coin vector and NotifyThew wire format are retained.
Only this offline price is new. No stamina spending, regeneration, VIP quota,
account reset, or schema migration is introduced. Both balances commit before
the acknowledgement; the client must never automatically retry an unknown
outcome because native C78 does not carry an idempotency key.
"""
from __future__ import annotations

import json
import struct

import cosmetic_shop
import storage

REQUEST = 78
NOTIFY = 1027
PROFILE = 'pve_stamina'
CASH = 1  # CurrencyTool: cash is Xu; misleading COIN_GOLDEN(2) is Bạc.
PRICE = 1
GAIN = 100
THEW_OFFSET = 76  # CHAR_BASIC fixed prefix: thew:i16, thewBuy:i16.
MAX_THEW = 32767


def _validate(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Dữ liệu thể lực chưa hợp lệ; chưa trừ xu.')
    for name in ('thew', 'thew_buy', 'thew_vip'):
        number = value.get(name)
        if type(number) is not int or not 0 <= number <= MAX_THEW:
            raise ValueError('Dữ liệu thể lực ngoài giới hạn native; chưa trừ xu.')
    return value


def _load(db):
    row = db.execute('SELECT value FROM settings WHERE name=?',
                     (storage.setting_key(PROFILE),)).fetchone()
    if row is not None:
        return _validate(json.loads(row[0]))
    # Bootstrap only the new personal key from the same native login record
    # that supplied the character's previous displayed stamina. No new grant.
    for frame_row in db.execute('SELECT frame FROM lobby_frames ORDER BY ordinal'):
        frame = bytes(frame_row[0])
        if len(frame) >= 8 and struct.unpack_from('<H', frame, 2)[0] == 1016:
            thew, thew_buy = struct.unpack_from('<hh', frame, 8 + THEW_OFFSET)
            return _validate(dict(version=1, thew=thew, thew_buy=thew_buy, thew_vip=0))
    raise ValueError('Không có dữ liệu thể lực native để khởi tạo; chưa trừ xu.')


def _save(db, value):
    db.execute('INSERT INTO settings(name,value) VALUES(?,?) '
               'ON CONFLICT(name) DO UPDATE SET value=excluded.value',
               (storage.setting_key(PROFILE), json.dumps(value, separators=(',', ':'))))


def initialize():
    with storage.connection(write=True) as db:
        value = _load(db)
        _save(db, value)


def snapshot(db=None):
    if db is None:
        with storage.connection() as opened:
            return snapshot(opened)
    return _load(db)


def login_payload(body, profile):
    value = _validate(profile)
    data = bytearray(body)
    struct.pack_into('<hh', data, THEW_OFFSET, value['thew'], value['thew_buy'])
    return bytes(data)


def notify(value):
    return NOTIFY, struct.pack('<iii', value['thew'], value['thew_buy'], value['thew_vip'])


def apply(state, payload, db):
    """Authenticated GATE owner only; atomic wallet + personal stamina update."""
    try:
        if (state.get('battle') or state.get('tank_selection')
                or (state.get('room') and state['room'].get('state', 0) != 0)):
            raise ValueError('Chỉ mua thể lực ở sảnh hoặc phòng chờ.')
        if len(payload) != 10 or struct.unpack('<HIi', payload) != (1, CASH, PRICE):
            raise ValueError('Mỗi lần mua 100 thể lực giá 1 xu vàng.')
        db.execute('BEGIN IMMEDIATE')
        wallet, value = cosmetic_shop.snapshot(db), _load(db)
        currency = wallet.get('currency')
        if (not isinstance(currency, list) or len(currency) != 6
                or any(type(v) is not int or not -0x80000000 <= v <= 0x7fffffff
                       for v in currency)):
            raise ValueError('Dữ liệu xu chưa hợp lệ; chưa trừ xu.')
        if currency[CASH - 1] < PRICE:
            raise ValueError('Bạn không đủ 1 xu vàng để mua 100 thể lực.')
        if value['thew'] > MAX_THEW - GAIN or value['thew_buy'] == MAX_THEW:
            raise ValueError('Thể lực đã gần giới hạn native (32767); chưa trừ xu.')
        value = {**value, 'thew': value['thew'] + GAIN, 'thew_buy': value['thew_buy'] + 1}
        wallet['currency'] = [currency[0] - PRICE, *currency[1:]]
        _save(db, value)
        cosmetic_shop._set(db, cosmetic_shop.PROFILE, wallet)
        # Serialize before commit too: a corrupt record cannot consume payment
        # and then fail while constructing the acknowledgement.
        packets = [(1039, struct.pack('<HH6i', 2, 0, *wallet['currency'])), notify(value)]
        db.commit()
        return packets, None
    except (ValueError, UnicodeError, struct.error) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else 'Yêu cầu mua thể lực không hợp lệ.'
        return [cosmetic_shop.tip(REQUEST, message)], message
    except BaseException:
        db.rollback()
        raise
