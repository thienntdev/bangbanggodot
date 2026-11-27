"""Durable offline gift mail and the explicit HTML5 mail-v1 GATE extension.

Native Flash C271/272 definitions were incomplete in the recovered sources.
Do not guess their ABI: C60000/S60001 are a documented HTML5 extension, carrying
u16-length UTF-8 JSON. Native S1230 unread, S1039 wallet, S1100 inventory and
S1150 garage retain their recovered wire layouts. The claim executes only in
the authenticated GATE owner thread, never in an admin HTTP handler.
"""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import re
import struct
import sqlite3
import threading
import time
import unicodedata
import uuid

import storage
import mail_rewards
import account_lifecycle
from mail_rewards import RewardError

REQUEST = 60000
REPLY = 60001
VERSION = 1
SENDER = 'Quản trị offline'
MAX_REQUEST_BYTES = 2048
MAX_REPLY_BYTES = 60000
MAIL_CAPACITY = 30
CLAIM_RETENTION_SECONDS = 12 * 60 * 60
MAIL_PAGE_SIZE = 5
CLEANUP_INTERVAL_SECONDS = 60
_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_MAIL_ID = re.compile(r'^mail-[0-9a-f]{32}$')
_guard = threading.Lock()
_subscribers = {}
_maintenance = None
_maintenance_guard = threading.Lock()
_log = logging.getLogger(__name__)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True,
                      allow_nan=False)


def initialize(*, start_worker=True):
    """Add only runtime-owned tables, when the operator starts the server.

    Code/assets installers must not import/call this function or open SQLite.
    Existing worlds, currencies, inventory, garages and schema version remain.
    """
    with storage.connection(write=True) as db:
        db.execute('CREATE TABLE IF NOT EXISTS offline_mail_v1 ('
                   'id TEXT PRIMARY KEY,profile_id INTEGER NOT NULL REFERENCES characters(profile_id),'
                   'recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,'
                   'rewards TEXT NOT NULL,created_at INTEGER NOT NULL,read_at INTEGER,'
                   'claimed_at INTEGER,claim_receipt TEXT)')
        db.execute('CREATE INDEX IF NOT EXISTS offline_mail_v1_profile '
                   'ON offline_mail_v1(profile_id,created_at DESC,id DESC)')
        _initialize_receipts(db)
        db.execute('CREATE INDEX IF NOT EXISTS offline_mail_v1_claimed '
                   'ON offline_mail_v1(claimed_at) WHERE claimed_at IS NOT NULL')
        changed = cleanup(db)
        # M35 had no cap. Never discard a pre-existing unclaimed reward just
        # to meet the new cap: remove safe claimed excess, then drain any
        # legacy protected excess through normal claims. New sends stay blocked.
        for row in db.execute('SELECT profile_id FROM offline_mail_v1 GROUP BY profile_id '
                              'HAVING COUNT(*)>?', (MAIL_CAPACITY,)).fetchall():
            if _make_room(db, row['profile_id'], MAIL_CAPACITY):
                changed.add(row['profile_id'])
    for ident in changed:
        notify(ident)
    if start_worker:
        _start_maintenance()


def _initialize_receipts(db):
    """Detach compact send receipts from live letters, in the same transaction.

    The old foreign key would either prevent deletion or lose retry identity.
    Keep only the canonical hash, recipient identity and lifecycle timestamps;
    never duplicate letter bodies/reward lists into permanent tombstones.

    The four-column INSERT used by M35 must still work after a code rollback.
    Defaults allow that statement; an AFTER INSERT trigger copies authoritative
    identity from the just-created letter in the same atomic statement. Code
    rollback does not restore deleted letters: an old M35 retry for a removed
    letter hits the retained UNIQUE receipt and rolls back without a new gift.
    """
    existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='offline_mail_send_v1'").fetchone()
    modern = False
    if existing:
        columns = {r['name']: r for r in db.execute('PRAGMA table_info(offline_mail_send_v1)')}
        modern = 'deleted_at' in columns
        if (modern and columns['profile_id']['dflt_value'] == '0' and
                columns['recipient']['dflt_value'] == "'{}'"):
            _receipt_metadata_trigger(db)
            return
        db.execute('ALTER TABLE offline_mail_send_v1 RENAME TO offline_mail_send_m35')
    db.execute('CREATE TABLE offline_mail_send_v1 ('
               'request_id TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,'
               'mail_id TEXT NOT NULL UNIQUE,created_at INTEGER NOT NULL,'
               "profile_id INTEGER NOT NULL DEFAULT 0,recipient TEXT NOT NULL DEFAULT '{}',"
               'claimed_at INTEGER,deleted_at INTEGER)')
    if existing:
        if modern:
            db.execute('INSERT INTO offline_mail_send_v1 '
                       '(request_id,payload_hash,mail_id,created_at,profile_id,recipient,claimed_at,deleted_at) '
                       'SELECT request_id,payload_hash,mail_id,created_at,profile_id,recipient,claimed_at,deleted_at '
                       'FROM offline_mail_send_m35')
        else:
            db.execute('INSERT INTO offline_mail_send_v1 '
                       '(request_id,payload_hash,mail_id,created_at,profile_id,recipient,claimed_at) '
                       'SELECT r.request_id,r.payload_hash,r.mail_id,r.created_at,m.profile_id,m.recipient,m.claimed_at '
                       'FROM offline_mail_send_m35 r JOIN offline_mail_v1 m ON m.id=r.mail_id')
        old_count = db.execute('SELECT COUNT(*) FROM offline_mail_send_m35').fetchone()[0]
        if db.execute('SELECT COUNT(*) FROM offline_mail_send_v1').fetchone()[0] != old_count:
            raise RuntimeError('Mail receipt migration found an orphan; no mail was changed')
        db.execute('DROP TABLE offline_mail_send_m35')
    _receipt_metadata_trigger(db)


def _receipt_metadata_trigger(db):
    # A missing live letter yields NULL and fails the NOT NULL constraint;
    # defaults are never left behind as an ambiguous/orphan receipt. M36 also
    # uses the trigger, so both old and new writers get identical identity.
    db.execute('CREATE TRIGGER IF NOT EXISTS offline_mail_send_v1_metadata '
               'AFTER INSERT ON offline_mail_send_v1 BEGIN '
               'UPDATE offline_mail_send_v1 SET '
               'profile_id=(SELECT profile_id FROM offline_mail_v1 WHERE id=NEW.mail_id),'
               'recipient=(SELECT recipient FROM offline_mail_v1 WHERE id=NEW.mail_id),'
               'claimed_at=(SELECT claimed_at FROM offline_mail_v1 WHERE id=NEW.mail_id) '
               'WHERE request_id=NEW.request_id; END')


def _delete_rows(db, values, now=None):
    now = int(time.time()) if now is None else int(now)
    deleted = []
    for row in values:
        if row['claimed_at'] is None:
            raise RewardError('mail_unclaimed', 'Thư còn quà. Hãy nhận hết quà trước khi xóa.')
        db.execute('UPDATE offline_mail_send_v1 SET claimed_at=?,deleted_at=? '
                   'WHERE mail_id=? AND profile_id=?',
                   (row['claimed_at'], now, row['id'], row['profile_id']))
        db.execute('DELETE FROM offline_mail_v1 WHERE id=? AND profile_id=?',
                   (row['id'], row['profile_id']))
        deleted.append(row['id'])
    return deleted


def cleanup(db, *, profile_id=None, now=None):
    """Remove fully claimed letters at the persisted 12-hour boundary.

    The caller owns the write transaction. This touches only mail rows and
    compact receipts, not wallets, inventories, worlds, or profile locks.
    """
    if not db.in_transaction:
        raise RuntimeError('Mailbox cleanup requires a write transaction')
    now = int(time.time()) if now is None else int(now)
    sql = 'SELECT id,profile_id,claimed_at FROM offline_mail_v1 WHERE claimed_at<=?'
    args = [now - CLAIM_RETENTION_SECONDS]
    if profile_id is not None:
        sql += ' AND profile_id=?'
        args.append(profile_id)
    values = db.execute(sql, args).fetchall()
    _delete_rows(db, values, now)
    return {row['profile_id'] for row in values}


def _make_room(db, profile_id, target=MAIL_CAPACITY - 1):
    total = db.execute('SELECT COUNT(*) FROM offline_mail_v1 WHERE profile_id=?', (profile_id,)).fetchone()[0]
    excess = max(0, total - target)
    values = db.execute('SELECT id,profile_id,claimed_at FROM offline_mail_v1 '
                        'WHERE profile_id=? AND claimed_at IS NOT NULL '
                        'ORDER BY claimed_at,created_at,id LIMIT ?', (profile_id, excess)).fetchall()
    return _delete_rows(db, values)


def sweep_once(path=None):
    with storage.connection(path, write=True) as db:
        changed = cleanup(db)
    for ident in changed:
        notify(ident)
    return changed


def _start_maintenance():
    global _maintenance
    with _maintenance_guard:
        if _maintenance is not None and _maintenance.is_alive():
            return
        path = storage.database_path()
        def run():
            tick = threading.Event()
            while not tick.wait(CLEANUP_INTERVAL_SECONDS):
                try:
                    sweep_once(path)
                except (sqlite3.Error, RuntimeError):
                    _log.warning('Mailbox cleanup deferred; retrying on the next sweep')
        _maintenance = threading.Thread(target=run, name='mailbox-cleanup', daemon=True)
        _maintenance.start()


def subscribe(profile_id):
    inbox = queue.Queue(maxsize=1)
    with _guard:
        _subscribers.setdefault(profile_id, set()).add(inbox)
    return inbox


def unsubscribe(profile_id, inbox):
    with _guard:
        listeners = _subscribers.get(profile_id)
        if listeners is not None:
            listeners.discard(inbox)
            if not listeners:
                _subscribers.pop(profile_id, None)


def notify(profile_id):
    # Coalesced dirty flag, not an unbounded queue or a cached mailbox snapshot.
    with _guard:
        targets = tuple(_subscribers.get(profile_id, ()))
    for inbox in targets:
        try:
            inbox.put_nowait(True)
        except queue.Full:
            pass


def recipient(db, ident, expected_name=None):
    row = db.execute('SELECT c.profile_id,c.username,w.state FROM characters c '
                     'JOIN worlds w ON w.profile_id=c.profile_id WHERE c.profile_id=?', (ident,)).fetchone()
    if row is None:
        raise RewardError('recipient_missing', 'Nhân vật không tồn tại; không tự tạo tài khoản nhận quà.')
    if account_lifecycle.blocked(db, row['username']):
        raise RewardError('recipient_deleted', 'Tài khoản đã xóa mềm; khôi phục tài khoản trước khi gửi thư mới.')
    state = json.loads(row['state'])
    name = state.get('name')
    if not isinstance(name, str) or not name:
        raise RewardError('recipient_invalid', 'Dữ liệu tên nhân vật chưa hợp lệ.')
    if expected_name is not None and name != expected_name:
        raise RewardError('recipient_changed', 'Tên nhân vật đã đổi; chọn lại đúng ID và xem trước lần nữa.')
    return dict(id=int(row['profile_id']), username=row['username'], name=name)


def recipients(db, query='', offset=0, limit=25):
    found = []
    folded = query.casefold()
    for row in db.execute('SELECT c.profile_id,c.username,w.state FROM characters c '
                          'JOIN worlds w ON w.profile_id=c.profile_id ORDER BY c.profile_id'):
        if account_lifecycle.blocked(db, row['username']):
            continue
        name = json.loads(row['state']).get('name', '')
        if folded and not any(folded in str(value).casefold() for value in (row['profile_id'], row['username'], name)):
            continue
        found.append(dict(id=int(row['profile_id']), username=row['username'], name=name))
    return dict(rows=found[offset:offset + limit], total=len(found), offset=offset, limit=limit)


def canonical(payload):
    if not isinstance(payload, dict) or set(payload) != {'recipient', 'subject', 'body', 'rewards'}:
        raise RewardError('payload_invalid', 'Nội dung gửi thư không hợp lệ.')
    target = payload['recipient']
    if (not isinstance(target, dict) or set(target) != {'id', 'name'} or
            type(target['id']) is not int or not 1 <= target['id'] <= 0xffffffff or
            not isinstance(target['name'], str) or not 1 <= len(target['name']) <= 128):
        raise RewardError('recipient_invalid', 'Chọn chính xác ID và tên nhân vật nhận thư.')
    values = {}
    for field, chars, byte_limit, required in (('subject', 80, 240, True), ('body', 2000, 6000, False)):
        value = payload[field]
        if not isinstance(value, str):
            raise RewardError('text_invalid', 'Tiêu đề và nội dung phải là văn bản.')
        value = unicodedata.normalize('NFC', value).strip()
        if ((required and not value) or len(value) > chars or len(value.encode('utf-8')) > byte_limit or
                any(ord(c) < 32 and c not in ('\n', '\t') for c in value)):
            raise RewardError('text_invalid', 'Tiêu đề tối đa 80 ký tự/240 byte; nội dung tối đa 2000 ký tự/6000 byte.')
        values[field] = value
    rewards = payload['rewards']
    if not isinstance(rewards, list) or not 1 <= len(rewards) <= mail_rewards.MAX_ROWS:
        raise RewardError('rewards_invalid', 'Mỗi thư cần từ 1 đến 16 dòng quà.')
    normalized, seen = [], set()
    for row in rewards:
        if not isinstance(row, dict) or set(row) != {'kind', 'id', 'quantity'}:
            raise RewardError('rewards_invalid', 'Dòng quà cần đúng kind, id, quantity.')
        kind, ident, amount = row['kind'], row['id'], row['quantity']
        if (kind not in ('currency', 'tank', 'item') or type(amount) is not int or not 1 <= amount <= mail_rewards.MAX_INT or
                kind == 'currency' and (not isinstance(ident, str) or ident not in mail_rewards.CURRENCIES) or
                kind != 'currency' and (type(ident) is not int or not 1 <= ident <= 0xffffffff)):
            raise RewardError('rewards_invalid', 'Mã, loại hoặc số lượng quà không hợp lệ.')
        key = kind + ':' + str(ident)
        if key in seen:
            raise RewardError('reward_duplicate', 'Mỗi món quà chỉ xuất hiện một dòng.')
        seen.add(key)
        normalized.append(dict(kind=kind, id=ident, quantity=amount))
    normalized.sort(key=lambda row: row['kind'] + ':' + str(row['id']))
    return dict(recipient=dict(target), rewards=normalized, **values)


def digest(payload):
    return hashlib.sha256(json_text(payload).encode('utf-8')).hexdigest()


def preview(db, payload):
    payload = canonical(payload)
    target = recipient(db, payload['recipient']['id'], payload['recipient']['name'])
    available = mail_rewards.catalog(db)
    rewards = mail_rewards.normalize(payload['rewards'], available)
    warnings = []
    protected = db.execute('SELECT COUNT(*) FROM offline_mail_v1 WHERE profile_id=? AND claimed_at IS NULL',
                           (target['id'],)).fetchone()[0]
    if protected >= MAIL_CAPACITY:
        warnings.append(RewardError('mailbox_full',
            'Hòm thư đã đầy thư chưa nhận quà (tối đa 30 thư). Nhận quà và dọn thư trước khi gửi thêm; quà cũ được giữ nguyên.',
            dict(capacity=MAIL_CAPACITY, unclaimed=protected)).envelope())
    try:
        mail_rewards.plan(db, target['id'], rewards, available)
    except RewardError as exc:
        warnings.append(exc.envelope())
    return dict(recipient=target, subject=payload['subject'], body=payload['body'],
                rewards=rewards, warnings=warnings, can_send=not warnings,
                claim_policy='all_or_nothing')


def send_receipt(db, request_id, payload_hash):
    row = db.execute('SELECT r.*,COALESCE(m.claimed_at,r.claimed_at) AS received_at '
                     'FROM offline_mail_send_v1 r LEFT JOIN offline_mail_v1 m ON m.id=r.mail_id '
                     'WHERE r.request_id=?', (request_id,)).fetchone()
    if row is None:
        return None
    if row['payload_hash'] != payload_hash:
        raise RewardError('idempotency_conflict', 'Mã yêu cầu này đã dùng cho nội dung khác; không gửi thêm thư.')
    return dict(mail_id=row['mail_id'], request_id=request_id, recipient=json.loads(row['recipient']),
                status='claimed' if row['received_at'] is not None else 'pending',
                removed=row['deleted_at'] is not None, duplicate=True, created_at=row['created_at'])


def send(db, payload, request_id, *, proof_checked=False):
    """HTTP admin only. Atomically insert mail and idempotency receipt.

    Retry lookup precedes the short-lived preview proof, permitting exact retry
    after a refresh/re-auth/restart without needing the original admin session.
    """
    if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
        raise RewardError('request_id_invalid', 'Mã yêu cầu cần 1–64 ký tự chữ/số/gạch nối.')
    payload = canonical(payload)
    payload_hash = digest(payload)
    if not db.in_transaction:
        raise RuntimeError('Sending mail requires BEGIN IMMEDIATE')
    previous = send_receipt(db, request_id, payload_hash)
    if previous is not None:
        return previous
    try:
        if not proof_checked:
            raise RewardError('preview_required', 'Xác nhận đã hết hạn, đổi phiên hoặc không khớp nội dung. Xem trước lại đúng nội dung, giữ nguyên mã yêu cầu rồi xác nhận gửi.')
        checked = preview(db, payload)
        if not checked['can_send']:
            warning = checked['warnings'][0]
            raise RewardError(warning['code'], warning['message'], warning.get('details'))
        cleanup(db, profile_id=checked['recipient']['id'])
        _make_room(db, checked['recipient']['id'])
        total = db.execute('SELECT COUNT(*) FROM offline_mail_v1 WHERE profile_id=?',
                           (checked['recipient']['id'],)).fetchone()[0]
        if total >= MAIL_CAPACITY:
            raise RewardError('mailbox_full', 'Hòm thư đã đủ 30 thư. Nhận quà và dọn thư trước khi gửi thêm.')
    except RewardError as exc:
        # We own BEGIN IMMEDIATE, found no receipt for this canonical intent,
        # and have not attempted either INSERT. The HTTP layer may expose this
        # proof only AFTER its connection context has successfully rolled back.
        # Auth, malformed requests, conflicting receipts and commit/IO failures
        # never get this marker: they may still represent an uncertain retry.
        exc.send_not_created_request_id = request_id
        raise
    ident, now = 'mail-' + uuid.uuid4().hex, int(time.time())
    db.execute('INSERT INTO offline_mail_v1(id,profile_id,recipient,subject,body,rewards,created_at) '
               'VALUES(?,?,?,?,?,?,?)', (ident, checked['recipient']['id'], json_text(checked['recipient']),
                checked['subject'], checked['body'], json_text(checked['rewards']), now))
    db.execute('INSERT INTO offline_mail_send_v1(request_id,payload_hash,mail_id,created_at,profile_id,recipient) '
               'VALUES(?,?,?,?,?,?)',
               (request_id, payload_hash, ident, now, checked['recipient']['id'], json_text(checked['recipient'])))
    return dict(mail_id=ident, request_id=request_id, recipient=checked['recipient'],
                status='pending', duplicate=False, created_at=now)


def counts(db):
    row = db.execute('SELECT SUM(read_at IS NULL),SUM(claimed_at IS NULL) '
                     'FROM offline_mail_v1 WHERE profile_id=?', (storage.profile_id(),)).fetchone()
    return dict(unread=int(row[0] or 0), pending=int(row[1] or 0))


def packet(value):
    raw = json_text(dict(v=VERSION, **value)).encode('utf-8')
    if len(raw) > MAX_REPLY_BYTES:
        raise RewardError('packet_limit', 'Thư vượt giới hạn gói tin; chưa thay đổi dữ liệu.')
    return REPLY, struct.pack('<H', len(raw)) + raw


def changed_packets(db, *, include_extension=True):
    current = counts(db)
    packets = [(1230, struct.pack('<i', current['unread']))]
    if include_extension:
        packets.append(packet(dict(request_id='', action='changed', ok=True, **current)))
    return packets


def decode_request(body):
    if len(body) < 2 or len(body) > MAX_REQUEST_BYTES + 2:
        raise RewardError('request_invalid', 'Gói thư không hợp lệ.')
    size, = struct.unpack_from('<H', body)
    if size != len(body) - 2:
        raise RewardError('request_invalid', 'Chiều dài gói thư không hợp lệ.')
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise RewardError('request_invalid', 'Khóa JSON thư bị lặp.')
            result[key] = value
        return result
    try:
        value = json.loads(body[2:].decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (ValueError, UnicodeError) as exc:
        raise RewardError('request_invalid', 'JSON thư không hợp lệ.') from exc
    if (not isinstance(value, dict) or type(value.get('v')) is not int or value['v'] != VERSION or
            not isinstance(value.get('request_id'), str) or not _ID.fullmatch(value['request_id'])):
        raise RewardError('request_invalid', 'Phiên bản hoặc mã yêu cầu thư không hợp lệ.')
    action = value.get('action')
    if action == 'list':
        if set(value) - {'v', 'request_id', 'action', 'offset', 'limit', 'filter'}:
            raise RewardError('request_invalid', 'Gói danh sách thư chứa trường ngoài hợp đồng.')
        offset, limit = value.get('offset', 0), value.get('limit', MAIL_PAGE_SIZE)
        if type(offset) is not int or not 0 <= offset <= MAX_INT or type(limit) is not int or not 1 <= limit <= 50:
            raise RewardError('request_invalid', 'Phân trang thư không hợp lệ.')
        selected_filter = value.get('filter', 'all')
        if selected_filter not in ('all', 'unread'):
            raise RewardError('request_invalid', 'Bộ lọc hòm thư không hợp lệ.')
        value.update(offset=offset, limit=limit, filter=selected_filter)
    elif action in ('read', 'claim', 'delete'):
        if set(value) != {'v', 'request_id', 'action', 'mail_id'} or not isinstance(value['mail_id'], str) or not _MAIL_ID.fullmatch(value['mail_id']):
            raise RewardError('request_invalid', 'Mã thư không hợp lệ.')
    elif action == 'delete_read':
        if set(value) != {'v', 'request_id', 'action'}:
            raise RewardError('request_invalid', 'Gói xóa thư chứa trường ngoài hợp đồng.')
    else:
        raise RewardError('request_invalid', 'Thao tác thư không được hỗ trợ.')
    return value


MAX_INT = 0x7fffffff


def _mail(db, ident):
    row = db.execute('SELECT * FROM offline_mail_v1 WHERE id=? AND profile_id=?',
                     (ident, storage.profile_id())).fetchone()
    if row is None:
        raise RewardError('mail_missing', 'Không tìm thấy thư của nhân vật này.')
    return row


def detail(row):
    return dict(id=row['id'], recipient=json.loads(row['recipient']), subject=row['subject'],
                body=row['body'], sender=SENDER, rewards=json.loads(row['rewards']),
                created_at=row['created_at'], read=row['read_at'] is not None,
                claimed=row['claimed_at'] is not None, claimed_at=row['claimed_at'],
                expires_at=row['claimed_at'] + CLAIM_RETENTION_SECONDS if row['claimed_at'] is not None else None,
                claim_policy='all_or_nothing')


def apply(state, body, db):
    """Only sixcube's authenticated per-profile GATE owner calls this.

    The connection owns all state mutations and re-reads bags/wallet/garage;
    world checkpoints do not contain these settings. No stale HTTP world copy
    or side connection may commit a claim over an active GATE session.
    """
    request_id, action = '', ''
    try:
        request = decode_request(body)
        request_id, action = request['request_id'], request['action']
        if state.get('char_id') != storage.profile_id():
            raise RewardError('profile_mismatch', 'Phiên game không khớp nhân vật.')
        db.execute('BEGIN IMMEDIATE')
        now = int(time.time())
        cleanup(db, profile_id=storage.profile_id(), now=now)
        response = dict(request_id=request_id, action=action, ok=True,
                        capacity=MAIL_CAPACITY, server_time=now)
        native = []
        if action == 'list':
            suffix = ' AND read_at IS NULL' if request['filter'] == 'unread' else ''
            total = db.execute('SELECT COUNT(*) FROM offline_mail_v1 WHERE profile_id=?' + suffix,
                               (storage.profile_id(),)).fetchone()[0]
            offset = min(request['offset'], max(0, (total - 1) // request['limit'] * request['limit']))
            values = list(db.execute('SELECT * FROM offline_mail_v1 WHERE profile_id=?' + suffix +
                                     ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                                     (storage.profile_id(), request['limit'], offset)))
            response.update(rows=[dict(id=row['id'], subject=row['subject'], sender=SENDER,
                                       created_at=row['created_at'], read=row['read_at'] is not None,
                                       claimed=row['claimed_at'] is not None,
                                       claimed_at=row['claimed_at'],
                                       expires_at=row['claimed_at'] + CLAIM_RETENTION_SECONDS if row['claimed_at'] is not None else None,
                                       reward_count=len(json.loads(row['rewards']))) for row in values],
                            total=total, offset=offset, limit=request['limit'], filter=request['filter'])
        elif action == 'delete_read':
            _require_lobby(state)
            values = db.execute('SELECT id,profile_id,claimed_at FROM offline_mail_v1 '
                                'WHERE profile_id=? AND read_at IS NOT NULL AND claimed_at IS NOT NULL',
                                (storage.profile_id(),)).fetchall()
            response['deleted'] = _delete_rows(db, values, now)
            response['kept_unclaimed'] = db.execute('SELECT COUNT(*) FROM offline_mail_v1 '
                'WHERE profile_id=? AND read_at IS NOT NULL AND claimed_at IS NULL', (storage.profile_id(),)).fetchone()[0]
        else:
            row = db.execute('SELECT * FROM offline_mail_v1 WHERE id=? AND profile_id=?',
                             (request['mail_id'], storage.profile_id())).fetchone()
            retired = None if row else db.execute('SELECT mail_id,claimed_at FROM offline_mail_send_v1 '
                'WHERE mail_id=? AND profile_id=? AND deleted_at IS NOT NULL',
                (request['mail_id'], storage.profile_id())).fetchone()
            if row is None:
                if action not in ('claim', 'delete') or retired is None:
                    raise RewardError('mail_missing', 'Không tìm thấy thư của nhân vật này.')
                response.update(mail_id=retired['mail_id'], removed=True)
                if action == 'claim':
                    response['already_claimed'] = retired['claimed_at'] is not None
                else:
                    response['deleted'] = []
            elif action == 'delete':
                _require_lobby(state)
                response.update(mail_id=row['id'], deleted=_delete_rows(db, [row], now), removed=True)
            else:
                if action == 'claim':
                    if row['claimed_at'] is not None:
                        response['already_claimed'] = True
                    else:
                        _require_lobby(state)
                        value = mail_rewards.plan(db, storage.profile_id(), json.loads(row['rewards']))
                        native = mail_rewards.commit_plan(db, state, value)
                        receipt = dict(version=1, profile_id=storage.profile_id(),
                                       rewards=mail_rewards.bare(value['rewards']),
                                       tank_uuids=[t['uuid'] for _, t in value['new_tanks']])
                        db.execute('UPDATE offline_mail_v1 SET claimed_at=?,claim_receipt=? '
                                   'WHERE id=? AND profile_id=? AND claimed_at IS NULL',
                                   (now, json_text(receipt), row['id'], storage.profile_id()))
                        db.execute('UPDATE offline_mail_send_v1 SET claimed_at=? WHERE mail_id=? AND profile_id=?',
                                   (now, row['id'], storage.profile_id()))
                        response['already_claimed'] = False
                db.execute('UPDATE offline_mail_v1 SET read_at=COALESCE(read_at,?) WHERE id=? AND profile_id=?',
                           (now, row['id'], storage.profile_id()))
                current = _mail(db, row['id'])
                response['mail'] = detail(current)
                if action == 'claim':
                    removed = _make_room(db, storage.profile_id(), MAIL_CAPACITY)
                    if row['id'] in removed:
                        response.pop('mail')
                        response.update(mail_id=row['id'], removed=True)
        response.update(counts(db))
        response['total_inbox'] = db.execute('SELECT COUNT(*) FROM offline_mail_v1 WHERE profile_id=?',
                                             (storage.profile_id(),)).fetchone()[0]
        # Validate all response serialization before commit. A lost TCP ACK after
        # commit is retried by mail ID and cannot grant again.
        final = native + [(1230, struct.pack('<i', response['unread'])), packet(response)]
        db.commit()
        return final, None
    except (RewardError, ValueError, UnicodeError, struct.error) as exc:
        db.rollback()
        error = exc if isinstance(exc, RewardError) else RewardError('mail_invalid', 'Dữ liệu thư chưa hợp lệ; chưa nhận quà.')
        return [packet(dict(request_id=request_id, action=action, ok=False, error=error.envelope()))], str(error)
    except BaseException:
        db.rollback()
        raise


def _require_lobby(state):
    if (state.get('battle') or state.get('tank_selection') or
            state.get('room') and state['room'].get('state', 0) != 0):
        raise RewardError('claim_phase', 'Về sảnh hoặc phòng chờ để nhận quà hoặc xóa thư.')
