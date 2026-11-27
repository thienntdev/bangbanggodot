"""Shared event ledger. All writes use the existing GATE save transaction.

HP uses integer thousandths, matching combat quantization. A run submits a
cumulative total: reconnecting/retrying a checkpoint cannot count a hit twice.
"""
from collections import Counter
from copy import deepcopy
import struct
import time
import json

import storage
import cosmetic_shop as shop
import inventory
import boosters
from crystals import bag_updates, pstr
from pve_progress import REWARD_V3

MAP = 40002
ACTIVITY = 8
MAX_HP = 10_000_000
DURATION = 1_800_000
INTERMISSION = 60_000
META_REQUEST = 60002
META_REPLY = 60003
META_VERSION = 1


def now_ms():
    return time.time_ns() // 1_000_000


def schema(db):
    # Runtime startup only. Installers never import this or open the user DB.
    for sql in (
        '''CREATE TABLE IF NOT EXISTS world_boss_rounds (
            id INTEGER PRIMARY KEY, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
            hp INTEGER NOT NULL, closed_ms INTEGER, next_ms INTEGER, revision INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS world_boss_runs (
            run TEXT PRIMARY KEY, round_id INTEGER NOT NULL, profile_id INTEGER NOT NULL,
            submitted INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS world_boss_scores (
            round_id INTEGER NOT NULL, profile_id INTEGER NOT NULL, uuid TEXT NOT NULL,
            name TEXT NOT NULL, damage INTEGER NOT NULL, attained INTEGER NOT NULL,
            PRIMARY KEY(round_id,profile_id))''',
        '''CREATE TABLE IF NOT EXISTS world_boss_rewards (
            round_id INTEGER NOT NULL, profile_id INTEGER NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(round_id,profile_id))''',
    ):
        db.execute(sql)


def initialize():
    from world_boss_data import preload
    preload()
    with storage.connection(write=True) as db:
        schema(db)


def current(db):
    row = db.execute('SELECT * FROM world_boss_rounds ORDER BY id DESC LIMIT 1').fetchone()
    return dict(row) if row else None


def close(db, row, now):
    if row['closed_ms'] is not None:
        return row
    # Timeouts keep the actual remaining HP in storage; protocol marks closed.
    closed = min(now, row['end_ms'])
    db.execute('UPDATE world_boss_rounds SET closed_ms=?,next_ms=? WHERE id=? AND closed_ms IS NULL',
               (closed, closed + INTERMISSION, row['id']))
    db.execute('INSERT OR IGNORE INTO world_boss_rewards(round_id,profile_id) '
               'SELECT round_id,profile_id FROM world_boss_scores WHERE round_id=? AND damage>0', (row['id'],))
    return dict(row, closed_ms=closed, next_ms=closed + INTERMISSION)


def advance(db, now=None):
    """Caller owns a transaction. Starts one current round, not missed offline rounds."""
    now = now_ms() if now is None else now
    row = current(db)
    if row and row['closed_ms'] is None and (row['hp'] <= 0 or now >= row['end_ms']):
        row = close(db, row, now)
    if row is None or row['closed_ms'] is not None and now >= row['next_ms']:
        db.execute('INSERT INTO world_boss_rounds(start_ms,end_ms,hp) VALUES(?,?,?)',
                   (now, now + DURATION, MAX_HP * 1000))
        row = current(db)
    return row


def poll(db, now=None):
    now = now_ms() if now is None else now
    row = current(db)
    if (row is None or row['closed_ms'] is None and (row['hp'] <= 0 or now >= row['end_ms'])
            or row['closed_ms'] is not None and now >= row['next_ms']):
        try:
            db.execute('BEGIN IMMEDIATE')
            row = advance(db, now)
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return row


def ranking(db, round_id):
    return [dict(r) for r in db.execute('SELECT * FROM world_boss_scores WHERE round_id=? '
        'ORDER BY damage DESC,attained,profile_id', (round_id,))]


def packets(db, row, *, transition=False):
    board = ranking(db, row['id'])
    own = next(((i, r) for i, r in enumerate(board, 1) if r['profile_id'] == storage.profile_id()), (0, {}))
    entries = b''.join(pstr(r['uuid']) + pstr(r['name']) + struct.pack('<i', r['damage']//1000)
                       for r in board[:10])
    active = row['closed_ms'] is None
    body = struct.pack('<iiiiIIH', ACTIVITY, (row['hp']+999)//1000 if active else 0,
                       MAX_HP, own[1].get('damage', 0)//1000, own[0], 0, min(10, len(board))) + entries
    state = (1951, struct.pack('<iiI', ACTIVITY, 2 if active else 3, 0))
    # RUNNING resets the native model. CLOSED opens its result using latest ranks.
    return ([state] if transition and active else []) + [(1952, body)] + ([state] if transition and not active else [])


def validate_meta_request(body):
    if body != bytes((META_VERSION,)):
        raise ValueError('World Boss metadata requires version 1 and no extra fields')


def metadata(db, row, now=None):
    """HTML5-only opt-in clock/reward snapshot; native 1951/1952 stay unchanged."""
    now = now_ms() if now is None else now
    receipt = db.execute('SELECT delivered FROM world_boss_rewards WHERE round_id=? AND profile_id=?',
                         (row['id'], storage.profile_id())).fetchone()
    pending = db.execute('SELECT COUNT(*) FROM world_boss_rewards WHERE profile_id=? AND delivered=0',
                        (storage.profile_id(),)).fetchone()[0]
    active = row['closed_ms'] is None
    result = dict(version=META_VERSION, activity=ACTIVITY, round_id=row['id'], state=2 if active else 3,
                  server_now_ms=now, starts_at_ms=row['start_ms'], ends_at_ms=row['end_ms'],
                  reopens_at_ms=row['next_ms'], hp=(row['hp']+999)//1000 if active else 0,
                  max_hp=MAX_HP, revision=row['revision'],
                  rewards=dict(round_id=row['id'], status=('none' if receipt is None else
                      'delivered' if receipt['delivered'] else 'pending'), item_count=len(REWARD_V3),
                      pending_rounds=pending))
    raw = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return META_REPLY, struct.pack('<H', len(raw)) + raw


def deliver(db):
    rows = db.execute('SELECT round_id FROM world_boss_rewards WHERE profile_id=? AND delivered=0 '
                      'ORDER BY round_id', (storage.profile_id(),)).fetchall()
    if not rows:
        return []
    bag = inventory.load(db)
    before = deepcopy(bag)
    delivered = 0
    for row in rows:
        trial = deepcopy(bag)
        try:
            for item, count in Counter(REWARD_V3).items():
                boosters._grant(trial, item, count)
        except ValueError:
            break
        bag = trial
        db.execute('UPDATE world_boss_rewards SET delivered=1 WHERE round_id=? AND profile_id=?',
                   (row[0], storage.profile_id()))
        delivered += 1
    result = []
    if delivered:
        inventory.save(bag, db)
        result += bag_updates(before, bag, (3,))
        result.append(shop.tip(0, f'Đã nhận {delivered} bộ nguyên liệu Boss Thế Giới vào túi.'))
    if delivered < len(rows):
        result.append(shop.tip(0, 'Túi nguyên liệu đầy. Thưởng Boss Thế Giới đã lưu; dọn túi rồi đăng nhập lại để nhận.'))
    return result


def checkpoint(db, state, arena):
    """Atomically acknowledge only new boss HP loss, cap concurrent overkill."""
    # Close deadlines under the same writer lock *before* accepting damage.
    # A delayed socket/checkpoint cannot credit a finished round or its successor.
    now = now_ms()
    row = advance(db, now)
    battle = state.get('battle') or {}
    meta = battle.get('world_boss')
    if row and meta and arena and arena.geometry.id == MAP and row['id'] == meta['round_id']:
        run = meta['run']
        wb = arena.pk['world_boss']
        total = round(wb['damage'] * 1000)
        old = db.execute('SELECT * FROM world_boss_runs WHERE run=?', (run,)).fetchone()
        if old is None:
            db.execute('INSERT INTO world_boss_runs(run,round_id,profile_id) VALUES(?,?,?)',
                       (run, row['id'], storage.profile_id()))
            submitted = 0
        else:
            if old['profile_id'] != storage.profile_id() or old['round_id'] != row['id']:
                raise ValueError('World Boss run owner/round mismatch')
            submitted = old['submitted']
        delta = max(0, total-submitted)
        if row['closed_ms'] is None and delta:
            credit = min(delta, row['hp'])
            db.execute('UPDATE world_boss_runs SET submitted=? WHERE run=?', (max(total, submitted), run))
            if credit:
                row['hp'] -= credit
                row['revision'] += 1
                db.execute('UPDATE world_boss_rounds SET hp=?,revision=? WHERE id=?',
                           (row['hp'], row['revision'], row['id']))
                db.execute('INSERT INTO world_boss_scores(round_id,profile_id,uuid,name,damage,attained) '
                    'VALUES(?,?,?,?,?,?) ON CONFLICT(round_id,profile_id) DO UPDATE SET '
                    'damage=damage+excluded.damage,attained=excluded.attained,name=excluded.name,uuid=excluded.uuid',
                    (row['id'], storage.profile_id(), state['char_uuid'], state['name'], credit, row['revision']))
    advance(db, now)
    # Login / round-transition notifications deliver rewards once. Trying on
    # every combat checkpoint would spam the full-bag tip at tick frequency.
    return []
