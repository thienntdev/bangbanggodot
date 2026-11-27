"""SQLite persistence. Legacy files are import sources, never runtime fallbacks."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / 'data' / 'bangbang.sqlite3'
PROFILE_ID = 30000791  # Existing single-character TCP sandbox, not web account auth.
_profile = ContextVar('bangbang_profile', default=PROFILE_ID)
# Old keys remain valid for Vua36; other characters get independent records.
PERSONAL_SETTINGS = frozenset(('inventory', 'cosmetic_shop_profile', 'crystal_profile',
                               'pk_bot_setup', 'guild_skills', 'booster_profile', 'pve_progress',
                               'pve_stamina'))


def profile_id():
    return _profile.get()


@contextmanager
def for_profile(ident):
    token = _profile.set(int(ident))
    try:
        yield
    finally:
        _profile.reset(token)


def setting_key(name, ident=None):
    ident = profile_id() if ident is None else int(ident)
    if name in PERSONAL_SETTINGS and ident != PROFILE_ID:
        return f'profile:{ident}:{name}'
    return name
SCHEMA_VERSION = 1
# All 91 native tanks now have checked resources, combat handlers and AI.
# Keep the shared gate for future incomplete entries; saved ownership is unchanged.
DEFERRED_TANKS = frozenset()


@lru_cache(maxsize=16)
def _resolved_database(path, base):
    return (Path(base) / path).resolve()


def database_path():
    path = os.environ.get('BB_DATABASE', str(DEFAULT_DATABASE))
    # Buff/stat cache hits must not perform Windows filesystem IO. Keep env/CWD
    # in the key so private test databases and relative paths remain isolated.
    return _resolved_database(path, '' if os.path.isabs(path) else os.getcwd())


@contextmanager
def connection(path=None, *, write=False):
    target = Path(path).resolve() if path is not None else database_path()
    db = sqlite3.connect(target.as_uri() + '?mode=rw', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            raise RuntimeError('Unsupported SQLite schema; run tools/migrate_sqlite.py first')
        if write:
            db.execute('BEGIN IMMEDIATE')
        yield db
        if write:
            db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def template_rows(filename):
    with connection() as db:
        rec = db.execute('SELECT sql_table FROM template_sources WHERE filename=?', (filename,)).fetchone()
        if rec is None:
            raise ValueError(f'Missing template source {filename}')
        return tuple({k: row[k] for k in row.keys() if k != '_ordinal' and row[k] is not None}
                     for row in db.execute(f'SELECT * FROM {quote(rec[0])} ORDER BY _ordinal'))


def setting(name):
    with connection() as db:
        rec = db.execute('SELECT value FROM settings WHERE name=?', (setting_key(name),)).fetchone()
        if rec is None:
            raise ValueError(f'Missing setting {name}')
        return json.loads(rec[0])


def capture_payload(name):
    with connection() as db:
        rec = db.execute('SELECT payload FROM http_bootstrap WHERE name=?', (name,)).fetchone()
        return bytes(rec[0]) if rec else None


def lobby_frames():
    with connection() as db:
        return [bytes(r[0]) for r in db.execute('SELECT frame FROM lobby_frames ORDER BY ordinal')]


def garage():
    with connection() as db:
        return [json.loads(data) for tank_id,data in db.execute(
            'SELECT tank_id,data FROM garage WHERE profile_id=? ORDER BY ordinal', (profile_id(),))
                if tank_id not in DEFERRED_TANKS]


def load_world():
    with connection() as db:
        row = db.execute('SELECT state,arena FROM worlds WHERE profile_id=?', (profile_id(),)).fetchone()
        if row is None:
            raise RuntimeError('Missing local character state')
        return json.loads(row[0]), row[1]


def save_world(state, arena_snapshot, *, db=None, before_write=None):
    if db is None:
        with connection() as opened:
            return save_world(state, arena_snapshot, db=opened, before_write=before_write)
    clean = {k: v for k, v in state.items() if k != 'battle'}
    battle = state.get('battle')
    clean['battle'] = {k: v for k, v in battle.items() if k != 'actions'} if battle else None
    # The GATE thread reuses one connection, but each snapshot is still its own
    # durable transaction. No async queue, reduced synchronous mode or save gap.
    try:
        db.execute('BEGIN IMMEDIATE')
        result = before_write(db) if before_write else None
        db.execute('UPDATE worlds SET state=?,arena=?,updated_ms=? WHERE profile_id=?',
                   (json.dumps(clean, ensure_ascii=False, separators=(',', ':')),
                    arena_snapshot, time.time_ns() // 1_000_000, profile_id()))
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def backup(destination):
    """SQLite backup API includes committed WAL pages; copying only .sqlite3 does not."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    with connection() as source:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
