"""M32 opt-in HTML5 economy-v1 extension; native Flash C156 is unchanged.

Only the authenticated GATE owner may call apply(). Quotes are read-only. A
confirmation binds exact UUID/counts and the complete current economy snapshot
to this GATE generation. A persistent per-profile operation receipt is committed
with the inventory and wallet, so lost acknowledgements never require a second
sale/dismantle/feed. The installer must never call this module or open a save.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import re
import secrets
import struct
import time

import inventory
import storage
import cosmetic_shop as shop
import boosters
from crystals import bag_updates, pstr
from display_locale import item_name
from mail_rewards import RewardError, rows
from combat_math import D

REQUEST, REPLY, VERSION = 60004, 60005, 1
MAX_INT, MAX_ROWS, MAX_REQUEST_BYTES, MAX_REPLY_BYTES = 0x7fffffff, 135, 32768, 60000
PREVIEW_SECONDS = 120
_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')
_REF_KEYS = {'container', 'uuid', 'template_id', 'count', 'slot_no'}


def text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(text(value).encode('utf-8')).hexdigest()


def session():
    # Deliberately separate from session_state, which is checkpointed to disk.
    return dict(generation=secrets.token_hex(16), secret=secrets.token_bytes(32))


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _ident(value):
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _ref(value, *, quantity=False):
    keys = _REF_KEYS | ({'quantity'} if quantity else set())
    if (not isinstance(value, dict) or set(value) != keys
            or not _integer(value.get('container'), 1, 10)
            or not isinstance(value.get('uuid'), str) or not 1 <= len(value['uuid'].encode('utf-8')) <= 128
            or any(ord(c) < 32 for c in value['uuid'])
            or not _integer(value.get('template_id'), 1, 0xffffffff)
            or not _integer(value.get('count'), 1, MAX_INT)
            or not _integer(value.get('slot_no'), 0, 32767)
            or quantity and not _integer(value.get('quantity'), 1, value['count'])):
        raise RewardError('target_invalid', 'UUID, ô, loại hoặc số lượng vật phẩm không hợp lệ.')
    return dict(value)


def canonical(value):
    if not isinstance(value, dict):
        raise RewardError('intent_invalid', 'Thao tác kho không hợp lệ.')
    kind = value.get('kind')
    if kind in ('sell', 'dismantle'):
        if set(value) != {'kind', 'items'} or not isinstance(value['items'], list) or not 1 <= len(value['items']) <= MAX_ROWS:
            raise RewardError('selection_empty', 'Chọn ít nhất một vật phẩm hoặc trợ thủ trước khi xem trước.')
        items = [_ref(row, quantity=True) for row in value['items']]
        allowed = (2, 3) if kind == 'sell' else (5,)
        if any(row['container'] not in allowed or kind == 'dismantle' and row['quantity'] != 1 for row in items):
            raise RewardError('container_blocked', 'Chỉ bán Vật phẩm/Nguyên liệu; chỉ tách Trợ thủ ở ngăn trợ thủ.')
        if len({row['uuid'] for row in items}) != len(items):
            raise RewardError('target_duplicate', 'Một UUID chỉ được xuất hiện một lần trong thao tác.')
        return dict(kind=kind, items=sorted(items, key=lambda row: (row['container'], row['slot_no'], row['uuid'])))
    if kind == 'feed':
        if set(value) not in ({'kind', 'helper', 'chips', 'level', 'exp'}, {'kind', 'helper', 'chips', 'level', 'exp', 'discard_exp'}) or not isinstance(value['chips'], list) or len(value['chips']) > MAX_ROWS:
            raise RewardError('intent_invalid', 'Yêu cầu tăng một cấp trợ thủ không hợp lệ.')
        if 'discard_exp' in value and not _integer(value['discard_exp'], 1, MAX_INT):
            raise RewardError('intent_invalid', 'Số EXP đồng ý bỏ không hợp lệ.')
        helper = _ref(value['helper'])
        chips = [_ref(row) for row in value['chips']]
        if (helper['container'] != 5 or any(row['container'] != 3 for row in chips)
                or len({row['uuid'] for row in chips}) != len(chips)
                or len({row['template_id'] for row in chips}) > 1
                or not _integer(value['level'], 0, 255) or not _integer(value['exp'], 0, MAX_INT)):
            raise RewardError('intent_invalid', 'Chọn một loại chip và đúng trợ thủ hiện tại.')
        return dict(kind=kind, helper=helper, chips=sorted(chips, key=lambda row: (row['slot_no'], row['uuid'])),
                    level=value['level'], exp=value['exp'], **({'discard_exp': value['discard_exp']} if 'discard_exp' in value else {}))
    raise RewardError('intent_invalid', 'Thao tác kho chưa được hỗ trợ.')


def decode_request(body):
    if len(body) < 2 or len(body) > MAX_REQUEST_BYTES + 2 or struct.unpack_from('<H', body)[0] != len(body) - 2:
        raise RewardError('request_invalid', 'Chiều dài gói kho không hợp lệ.')
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    try:
        value = json.loads(body[2:].decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise RewardError('request_invalid', 'JSON kho không hợp lệ.') from exc
    base = {'v', 'request_id', 'action', 'operation_id'}
    if (not isinstance(value, dict) or type(value.get('v')) is not int or value['v'] != VERSION
            or not _ident(value.get('request_id')) or not _ident(value.get('operation_id'))):
        raise RewardError('request_invalid', 'Phiên bản hoặc mã yêu cầu kho không hợp lệ.')
    action = value.get('action')
    if action == 'status':
        if set(value) != base:
            raise RewardError('request_invalid', 'Gói kiểm tra kết quả chứa trường ngoài hợp đồng.')
    elif action in ('preview', 'apply'):
        if set(value) != base | {'intent'} | ({'proof'} if action == 'apply' else set()):
            raise RewardError('request_invalid', 'Gói thao tác kho chứa trường ngoài hợp đồng.')
        value['intent'] = canonical(value['intent'])
        if action == 'apply':
            proof = value['proof']
            if (not isinstance(proof, dict) or set(proof) != {'generation', 'revision', 'expires', 'token'}
                    or not isinstance(proof['generation'], str) or not re.fullmatch(r'[0-9a-f]{32}', proof['generation'])
                    or not _integer(proof['expires'], 1, 0x7fffffffffffffff)
                    or any(not isinstance(proof[key], str) or not _HASH.fullmatch(proof[key]) for key in ('revision', 'token'))):
                raise RewardError('request_invalid', 'Xác nhận kho không hợp lệ.')
    else:
        raise RewardError('request_invalid', 'Thao tác kho chưa được hỗ trợ.')
    return value


def packet(value):
    raw = text(dict(v=VERSION, **value)).encode('utf-8')
    if len(raw) > MAX_REPLY_BYTES:
        raise RewardError('packet_limit', 'Danh sách vượt giới hạn gói tin; chưa thay đổi vật phẩm.')
    return REPLY, struct.pack('<H', len(raw)) + raw


def _receipt_key(operation_id):
    return f'economy_v1:{storage.profile_id()}:{operation_id}'


def _receipt(db, operation_id):
    row = db.execute('SELECT value FROM settings WHERE name=?', (_receipt_key(operation_id),)).fetchone()
    return json.loads(row[0]) if row else None


def _lookup(containers, ref):
    matches = [item for values in containers.values() for item in values if item.get('uuid') == ref['uuid']]
    item = next((item for item in containers.get(str(ref['container']), []) if item.get('uuid') == ref['uuid']), None)
    if (len(matches) != 1 or item is None or any(item.get(key) != ref[key] for key in ('template_id', 'count', 'slot_no'))
            or sum(row.get('slot_no') == ref['slot_no'] for row in containers.get(str(ref['container']), [])) != 1):
        raise RewardError('target_changed', 'Vật phẩm đã đổi ô/số lượng hoặc không thuộc túi của bạn. Hãy chọn và xem trước lại.')
    return item


def _protection(item, active='', *, helper=False):
    # ITEM_EXT_FLAG_BIT.as: SYS_BIND=1, USER_LOCK=2, TIME_START=4,
    # CUR_AVATAR=8, NO_NEW=16, CUR_USE=32. Binding / already seen are not locks.
    flags = item.get('ext_flag')
    if not _integer(flags, 0, 0xffffffff):
        raise RewardError('item_flags', 'Cờ bảo vệ vật phẩm không hợp lệ; chưa tiêu vật phẩm.')
    if flags & 2:
        raise RewardError('item_locked', 'Vật phẩm/trợ thủ đang khóa bảo vệ; không bán/tách/tiêu.')
    if flags & ~17:
        raise RewardError('item_protected', 'Vật phẩm đang có cờ bảo vệ/trạng thái chưa hỗ trợ; chưa tiêu vật phẩm.')
    if item.get('life_time') != 0:
        raise RewardError('item_timed', 'Chưa hỗ trợ bán/tách/tiêu vật phẩm có thời hạn.')
    if helper and item['uuid'] == active:
        raise RewardError('helper_equipped', 'Trợ thủ đang làm chủ chiến. Tháo trang bị trước khi tách.')


def _catalog(db):
    return ({int(row['nItemId']): row for row in rows(db, 'ItemTemplate_table.xml')},
            {int(row['nId']): row for row in rows(db, 'BoosterTemplate_table.xml')},
            {int(row.get('nLevel') or 0): int(row['iExp']) for row in rows(db, 'BoosterLevelTemplate_table.xml')})


def _helper(item, items, helpers):
    row = items.get(item['template_id'], {})
    helper = helpers.get(int(row.get('iReuseA') or 0))
    if item['count'] != 1 or int(row.get('nType') or 0) != 36 or int(row.get('nContType') or 0) != 5 or helper is None:
        raise RewardError('helper_invalid', 'Trợ thủ thiếu cấu hình gốc hợp lệ; chưa thay đổi túi.')
    return helper


def _label(item, templates):
    row = templates.get(item['template_id'], {})
    source = str(row.get('szName') or row.get('szName1') or item['template_id'])
    return item_name(item['template_id'], source)[:300]


def _row(ref, item, templates, quantity):
    return dict(container=ref['container'], uuid=item['uuid'], template_id=item['template_id'],
                slot_no=item['slot_no'], count=item['count'], quantity=quantity, name=_label(item, templates),
                level=item['level'], exp=item['exp'], upgrade_level=item['up_level'], rank=item['rank'])


def plan(db, intent):
    """Private-copy plan using one SQLite snapshot, never a write or grant."""
    containers, wallet, profile = inventory.load(db), shop.snapshot(db), boosters.snapshot(db)
    revision = digest(dict(containers=containers, wallet=wallet, helper=profile))
    before = deepcopy(containers)
    items, helpers, levels = _catalog(db)
    currencies = wallet.get('currency')
    if not isinstance(currencies, list) or len(currencies) != 6 or any(not _integer(v, 0, MAX_INT) for v in currencies):
        raise RewardError('wallet_invalid', 'Ví vượt miền native an toàn; chưa thay đổi vật phẩm hoặc tiền.')
    quote = dict(kind=intent['kind'], items=[], gold_xu=0, currency='cash', unit_price=0,
                 policy='all_or_nothing', profile_id=storage.profile_id())
    if intent['kind'] in ('sell', 'dismantle'):
        quote['unit_price'] = 1 if intent['kind'] == 'sell' else 10
        for ref in intent['items']:
            item = _lookup(containers, ref)
            template = items.get(item['template_id'], {})
            if int(template.get('nContType') or 0) != ref['container']:
                raise RewardError('container_mismatch', 'Cấu hình vật phẩm không khớp ngăn đang chứa.')
            _protection(item, profile.get('active', ''), helper=intent['kind'] == 'dismantle')
            if intent['kind'] == 'dismantle':
                _helper(item, items, helpers)
            quote['items'].append(_row(ref, item, items, ref['quantity']))
            quote['gold_xu'] += ref['quantity'] * quote['unit_price']
            item['count'] -= ref['quantity']
            if item['count'] == 0:
                containers[str(ref['container'])].remove(item)
        if quote['gold_xu'] > MAX_INT - currencies[0]:
            raise RewardError('wallet_overflow', 'Xu vàng sẽ vượt giới hạn 2.147.483.647; chưa bán/tách hoặc cộng tiền.')
        currencies[0] += quote['gold_xu']
    else:
        pet = _lookup(containers, intent['helper'])
        helper = _helper(pet, items, helpers)
        # Feeding an equipped helper is native and remains allowed. Protection
        # of the consumed material still applies; no implicit unequip occurs.
        if not _integer(pet.get('ext_flag'), 0, 0xffffffff) or pet['ext_flag'] & 2:
            raise RewardError('item_locked', 'Trợ thủ đang khóa bảo vệ; chưa tiêu chip hoặc EXP.')
        if pet['ext_flag'] & ~49 or pet.get('life_time') != 0:
            raise RewardError('helper_protected', 'Trợ thủ có thời hạn/trạng thái chưa hỗ trợ; chưa tiêu chip hoặc EXP.')
        if pet['level'] != intent['level'] or pet['exp'] != intent['exp']:
            raise RewardError('helper_changed', 'Tiến trình trợ thủ đã đổi. Kiểm tra lại mức EXP/cấp trước khi nâng.')
        cap, old, experience = int(helper['iLevelLimit']), pet['level'], pet['exp']
        if not _integer(cap, 1, 255) or old >= cap:
            raise RewardError('helper_capped', 'Trợ thủ đã đạt cấp tối đa; không tiêu chip.')
        need = levels.get(old, 0)
        if not _integer(need, 1, MAX_INT):
            raise RewardError('exp_config', 'Thiếu cấu hình EXP gốc; không tiêu chip.')
        remaining = max(0, need - experience)
        chips, gain, available = [], 0, 0
        for ref in intent['chips']:
            chip = _lookup(containers, ref)
            row = items.get(chip['template_id'], {})
            this_gain = int(row.get('iReuseA') or 0)
            if int(row.get('nType') or 0) != 37 or int(row.get('nContType') or 0) != 3 or not _integer(this_gain, 1, MAX_INT):
                raise RewardError('chip_invalid', 'Chọn chip EXP hợp lệ trong Nguyên liệu.')
            _protection(chip)
            gain = this_gain
            available += chip['count']
            chips.append((ref, chip))
        if remaining and not chips:
            raise RewardError('chip_missing', 'Chọn loại chip EXP để lên đúng một cấp.')
        required = (remaining + gain - 1) // gain if remaining else 0
        if required > available:
            raise RewardError('chips_insufficient', f'Cần {required:,} chip để lên một cấp, hiện có {available:,}; chưa tiêu chip hoặc EXP.',
                              dict(required_count=required, available_count=available, exp_needed=remaining))
        remainder = experience + required * gain - need
        if remainder > MAX_INT:
            raise RewardError('exp_overflow', 'EXP dư vượt miền native; chưa tiêu chip.')
        discarded = remainder if old + 1 == cap else 0
        if intent.get('discard_exp', 0) != discarded:
            raise RewardError('cap_remainder', f'Cần xác nhận bỏ {discarded:,} EXP dư ở cấp tối đa; chưa tiêu chip.',
                              dict(required_count=required, available_count=available, excess_exp=discarded, exp_needed=remaining))
        remainder -= discarded
        left = required
        for ref, chip in chips:
            take = min(left, chip['count'])
            if take:
                quote['items'].append(_row(ref, chip, items, take))
                chip['count'] -= take
                left -= take
                if chip['count'] == 0:
                    containers['3'].remove(chip)
        pet['level'], pet['exp'] = old + 1, remainder
        quote.update(helper_uuid=pet['uuid'], helper_name=_label(pet, items), previous_level=old, current_level=old + 1,
                     previous_exp=experience, current_exp=remainder, discarded_exp=discarded, exp_threshold=need, chip_exp=gain,
                     required_count=required, available_count=available, next_exp_threshold=levels.get(old + 1, 0), cap=cap)
    return dict(before=before, containers=containers, wallet=wallet, profile=profile, quote=quote, revision=revision)


def _proof(context, operation_id, intent, value, expires):
    signed = dict(profile=storage.profile_id(), generation=context['generation'], operation_id=operation_id,
                  intent=digest(intent), revision=value['revision'], quote=value['quote'], expires=expires)
    return dict(generation=context['generation'], revision=value['revision'], expires=expires,
                token=hmac.new(context['secret'], text(signed).encode('utf-8'), hashlib.sha256).hexdigest())


def _snapshot_packets(db):
    containers, wallet = inventory.load(db), shop.snapshot(db)
    return ([(1100, inventory.list_payload(c, containers.get(str(c), []))) for c in (2, 3, 5)]
            + [(1039, struct.pack('<HH6i', 1, 0, *wallet['currency'])),
               (1056, pstr(boosters.snapshot(db).get('active', '')))])


def _validate_packets(packets):
    # Native frame has uint16 total bytes. Serialize size/id before COMMIT.
    for mid, body in packets:
        struct.pack('<HHI', len(body) + 8, mid, 0)


def _score(db, containers, profile):
    active = profile.get('active', '')
    if not active:
        return 0
    pet = next((item for item in containers.get('5', []) if item['uuid'] == active), None)
    if pet is None:
        raise RewardError('helper_active_missing', 'Trợ thủ chủ chiến không còn trong túi; chưa thay đổi dữ liệu.')
    items, helpers, _ = _catalog(db)
    helper = _helper(pet, items, helpers)
    costs = {(int(row['nType']), int(row['nLevel'])): int(row['iCostMax']) for row in rows(db, 'ConsumeLevelTemplate_table.xml')}
    def progress(kind, level, consumed):
        maximum = costs.get((kind, level + 1), 0)
        return D(level) + D(int(D(consumed) / maximum * 100)) / 100 if maximum else D(level)
    rank = progress(2, pet['rank'], pet['rank_cost'])
    up = progress(1, pet['up_level'], pet['up_cost'])
    return int(1000 * (1 + D(pet['level']) * D('.05')) * (1 + D(helper['nAptitude']) * 4 / 50)
               * (D('1.025') + rank * rank / 120 + rank / 12 + D('.0125') * up))


def apply(state, body, db, context):
    request_id = action = operation_id = ''
    known_absent = False
    try:
        request = decode_request(body)
        request_id, action, operation_id = (request[key] for key in ('request_id', 'action', 'operation_id'))
        if state.get('char_id') != storage.profile_id():
            raise RewardError('profile_mismatch', 'Phiên kho không khớp nhân vật đã đăng nhập.')
        db.execute('BEGIN IMMEDIATE' if action == 'apply' else 'BEGIN')
        receipt = _receipt(db, operation_id)
        response = dict(request_id=request_id, operation_id=operation_id, action=action, ok=True,
                        profile_id=storage.profile_id())
        native, score = [], None
        if action == 'status':
            response.update(status='committed' if receipt else 'not_committed', receipt=receipt)
            native = _snapshot_packets(db)
        elif receipt is not None:
            if receipt['intent_hash'] != digest(request['intent']):
                raise RewardError('operation_conflict', 'Mã thao tác đã dùng cho nội dung khác; không thực hiện thêm.')
            response.update(status='committed', duplicate=True, receipt=receipt)
            native = _snapshot_packets(db)
        else:
            known_absent = True
            if state.get('battle') or state.get('tank_selection') or (state.get('room') or {}).get('state', 0) != 0:
                raise RewardError('economy_phase', 'Về sảnh hoặc phòng chờ để bán/tách/nâng trợ thủ.')
            value = plan(db, request['intent'])
            if action == 'preview':
                response.update(status='preview', quote=value['quote'],
                                proof=_proof(context, operation_id, request['intent'], value, int(time.time()) + PREVIEW_SECONDS))
            else:
                proof = request['proof']
                expected = _proof(context, operation_id, request['intent'], value, proof['expires'])
                if (proof['generation'] != context['generation'] or proof['revision'] != value['revision']
                        or not int(time.time()) <= proof['expires'] <= int(time.time()) + PREVIEW_SECONDS
                        or not hmac.compare_digest(proof['token'], expected['token'])):
                    raise RewardError('preview_stale', 'Xác nhận đã hết hạn hoặc túi/tiền/trợ thủ đã đổi; chưa tiêu gì. Hãy xem trước lại.')
                native = bag_updates(value['before'], value['containers'], (2, 3, 5))
                if value['quote']['kind'] == 'feed':
                    q = value['quote']
                    native.append((1106, struct.pack('<IBI', 31, 1, 0) + pstr(q['helper_uuid'])
                                   + struct.pack('<ii', q['previous_level'], q['current_level'])))
                    score = _score(db, value['containers'], value['profile'])
                else:
                    native.append((1039, struct.pack('<HH6i', 1, 0, *value['wallet']['currency'])))
                receipt = dict(operation_id=operation_id, profile_id=storage.profile_id(), intent_hash=digest(request['intent']),
                               quote=value['quote'], committed_at=int(time.time()))
                inventory.save(value['containers'], db)
                shop._set(db, shop.PROFILE, value['wallet'])
                db.execute('INSERT INTO settings(name,value) VALUES(?,?)', (_receipt_key(operation_id), text(receipt)))
                response.update(status='committed', duplicate=False, receipt=receipt)
        final = native + [packet(response)]
        _validate_packets(final)
        db.commit()
        if score is not None:
            state['booster_attack'] = score
        return final, None
    except (RewardError, ValueError, UnicodeError, struct.error) as exc:
        db.rollback()
        error = exc if isinstance(exc, RewardError) else RewardError('economy_invalid', 'Dữ liệu kho chưa hợp lệ; chưa thay đổi vật phẩm.')
        envelope = error.envelope()
        envelope['not_committed'] = known_absent
        return [packet(dict(request_id=request_id, operation_id=operation_id, action=action, ok=False,
                            profile_id=storage.profile_id(), error=envelope))], str(error)
    except BaseException:
        db.rollback()
        raise
