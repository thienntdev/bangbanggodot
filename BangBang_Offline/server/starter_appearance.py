"""Native Ash starter outfit; explicit offline migration, never a login regrant."""
import json
import time

import inventory
import storage
from cosmetic_shop import CAPACITY

ASH = 2801001
VERSION = 1


def marker_key(profile_id):
    return f'starter_ash_v1:{int(profile_id)}'


def new_item(profile_id, *, slot=0, equipped=True, now=None):
    item = dict.fromkeys(inventory.FIELDS, 0)
    item.update(uuid=f'starter-ash-{int(profile_id)}', template_id=ASH, count=1,
                ext_flag=32 if equipped else 0, slot_no=slot,
                create_time=int(time.time() if now is None else now))
    return item


def receipt(profile_id, *, equipped, added, now=None):
    return dict(version=VERSION, profile_id=int(profile_id), item_id=ASH,
                equipped=bool(equipped), added=bool(added),
                applied_at=int(time.time() if now is None else now))


def _read(db, name):
    row = db.execute('SELECT value FROM settings WHERE name=?', (name,)).fetchone()
    if row is None:
        raise ValueError(f'Missing required starter setting: {name}')
    return json.loads(row[0])


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def plan(db, *, now=None):
    """Read only, using the caller's single SQLite snapshot and exact native data."""
    if db.execute('PRAGMA user_version').fetchone()[0] != storage.SCHEMA_VERSION:
        raise ValueError('Unsupported SQLite schema')
    shop = _read(db, 'cosmetic_shop_catalog')
    row = shop.get(str(ASH))
    if not row or int(row.get('container', 0)) != 4:
        raise ValueError('Ash is missing from the installed fashion shop')
    source = db.execute('SELECT sql_table FROM template_sources WHERE filename=?',
                        ('ItemTemplate_table.xml',)).fetchone()
    if source is None:
        raise ValueError('Missing native item templates')
    item = db.execute(f'SELECT nType,nContType FROM {storage.quote(source[0])} WHERE nItemId=?',
                      (str(ASH),)).fetchone()
    if item is None or tuple(map(int, item)) != (28, 4):
        raise ValueError('Ash is not a native fashion item')
    changes = []
    for ident, raw, arena in db.execute('SELECT c.profile_id,w.state,w.arena FROM characters c '
                                       'JOIN worlds w ON w.profile_id=c.profile_id ORDER BY c.profile_id'):
        prior = db.execute('SELECT value FROM settings WHERE name=?', (marker_key(ident),)).fetchone()
        if prior is not None:
            done = json.loads(prior[0])
            if (done.get('version'), done.get('profile_id'), done.get('item_id')) != (VERSION, ident, ASH):
                raise ValueError(f'Invalid starter receipt for profile {ident}')
            continue
        state = json.loads(raw)
        if state.get('char_id') != ident:
            raise ValueError(f'Character identity mismatch: {ident}')
        # Inventory and appearance are also held in a live GATE session. Require
        # the stopped-server installer and a lobby checkpoint for every change.
        if state.get('battle') or state.get('tank_selection') or arena:
            raise ValueError(f'Profile {ident}: return to lobby and stop server before installing Ash')
        inv_key = storage.setting_key('inventory', ident)
        profile_key = storage.setting_key('cosmetic_shop_profile', ident)
        containers = _read(db, inv_key)
        profile = _read(db, profile_key)
        outfits = containers.setdefault('4', [])
        ash = next((x for x in outfits if x['template_id'] == ASH and
                    x.get('count', 0) > 0 and not x.get('life_time', 0)), None)
        equip = int(profile.get('avatar', 0)) == 0
        added = ash is None
        if added:
            used = {int(x['slot_no']) for x in outfits}
            slot = next((n for n in range(CAPACITY[4]) if n not in used), None)
            if slot is None:
                raise ValueError(f'Profile {ident}: fashion inventory is full; free one slot for Ash')
            ash = new_item(ident, slot=slot, equipped=equip, now=now)
            if any(x['uuid'] == ash['uuid'] for items in containers.values() for x in items):
                raise ValueError(f'Profile {ident}: starter item UUID already exists')
            outfits.append(ash)
        if equip:
            for outfit in outfits:
                outfit['ext_flag'] = (int(outfit['ext_flag']) & ~32) | (32 if outfit is ash else 0)
            profile['avatar'] = state['avatar'] = ASH
        changes.append(dict(profile_id=ident, inventory_key=inv_key, inventory=containers,
                            profile_key=profile_key, profile=profile, world=state if equip else None,
                            receipt=receipt(ident, equipped=equip, added=added, now=now)))
    return changes


def apply(db, *, now=None):
    """Caller owns BEGIN IMMEDIATE, pre-write backup, commit and rollback."""
    if not db.in_transaction:
        raise ValueError('Starter migration requires an explicit transaction')
    changes = plan(db, now=now)
    for change in changes:
        for key, value in ((change['inventory_key'], change['inventory']),
                           (change['profile_key'], change['profile']),
                           (marker_key(change['profile_id']), change['receipt'])):
            db.execute('INSERT INTO settings(name,value) VALUES(?,?) '
                       'ON CONFLICT(name) DO UPDATE SET value=excluded.value', (key, _json(value)))
        if change['world'] is not None:
            db.execute('UPDATE worlds SET state=? WHERE profile_id=?',
                       (_json(change['world']), change['profile_id']))
    return [c['receipt'] for c in changes]
