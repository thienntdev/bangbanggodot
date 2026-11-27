"""Explicit offline M8.13 grant, called only by the reviewed installer.

The caller owns the transaction and must back up the stopped database first.
Never run this at login/startup; do not reset a name, password or an owned item.
"""
import json
import time
import uuid

import inventory
import storage
from tank_halos import SUPPORTED

USERNAME = '1'
CARD = 2600002
CARD_COUNT = 9999


def grant(db, *, username=USERNAME):
    if not db.in_transaction:
        raise RuntimeError('The grant requires an explicit caller-owned transaction.')
    if username != USERNAME:
        raise ValueError('M8.13 chỉ cấp cho tài khoản 1 đã được chỉ định.')
    row = db.execute('SELECT profile_id FROM characters WHERE username=?', (username,)).fetchone()
    if not row:
        raise ValueError('Chưa có nhân vật của tài khoản 1. Đăng nhập tạo nhân vật rồi chạy lại bước cấp đồ.')
    ident = int(row[0])
    key = f'm813_entitlements_once:{ident}'
    done = db.execute('SELECT value FROM settings WHERE name=?', (key,)).fetchone()
    if done:
        return dict(already_applied=True, **json.loads(done[0]))
    saved = json.loads(db.execute('SELECT state FROM worlds WHERE profile_id=?', (ident,)).fetchone()[0])
    if saved.get('battle') or saved.get('tank_selection'):
        raise ValueError('Nhân vật 1 cần về sảnh trước khi cấp đồ.')
    with storage.for_profile(ident):
        bags = inventory.load(db)
        templates = {}
        for item_id in (*sorted(SUPPORTED), CARD):
            template = db.execute('SELECT nContType,iStackMax FROM client_ItemTemplate_table '
                                  'WHERE nItemId=? ORDER BY _ordinal DESC LIMIT 1', (str(item_id),)).fetchone()
            expected = (2, 9999) if item_id == CARD else (9, 1)
            if template is None or tuple(map(int, template)) != expected:
                raise ValueError(f'Sai dữ liệu gốc vật phẩm {item_id}; chưa cấp đồ.')
            templates[item_id] = expected
        def add(item_id, count):
            container, limit = templates[item_id]
            bag = bags.setdefault(str(container), [])
            for item in sorted(bag, key=lambda v: v['slot_no']):
                if item['template_id'] == item_id and item.get('life_time', 0) == 0 and 0 < item['count'] < limit:
                    take = min(count, limit - item['count'])
                    item['count'] += take
                    count -= take
                    if not count:
                        return
            occupied = {v['slot_no'] for v in bag}
            while count:
                slot = next(i for i in range(32768) if i not in occupied)
                item = {field: 0 for field in inventory.FIELDS}
                item.update(uuid='m813-' + uuid.uuid4().hex, template_id=item_id,
                            count=min(count, limit), create_time=int(time.time()), slot_no=slot)
                bag.append(item)
                occupied.add(slot)
                count -= item['count']
        halo_added = []
        for halo in sorted(SUPPORTED):
            if not any(i['template_id'] == halo and i['count'] > 0 and not i.get('life_time', 0)
                       for i in bags.get('9', [])):
                add(halo, 1)
                halo_added.append(halo)
        add(CARD, CARD_COUNT)
        old_capacity = inventory.grocery_capacity(db)
        capacity = max(old_capacity, 1 + max((i['slot_no'] for i in bags['2']), default=-1))
        if capacity > old_capacity:
            db.execute('INSERT INTO settings(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
                       (f'inventory_slots:{ident}', str(capacity)))
        inventory.save(bags, db)
        receipt = dict(profile_id=ident, username=username, rename_cards_added=CARD_COUNT,
                       halos_added=halo_added, halos_available=sorted(SUPPORTED),
                       grocery_capacity_before=old_capacity, grocery_capacity_after=capacity,
                       granted_at=int(time.time()))
        db.execute('INSERT INTO settings(name,value) VALUES(?,?)',
                   (key, json.dumps(receipt, ensure_ascii=False, separators=(',', ':'))))
    return dict(already_applied=False, **receipt)
