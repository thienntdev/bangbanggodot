"""Native helper progression and frozen PvE-only bonuses (PVE01/PVE03)."""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import struct
import time
import uuid
import secrets

import storage
import inventory
import cosmetic_shop as shop
from crystals import bag_updates, pstr
from combat_math import D
from pve_catalog import MAPS as PVE_MAPS

SETTING = 'booster_profile'
STARTER = 4440004
CHIP = 3700002
REQUESTS = (156, 157, 158, 159, 166)
FLAT = {'hp': ('iHp',), 'attack': ('iAttack', 'iEgAtk'),
        'armor': ('iArmor', 'iEgArmor'), 'penetration': ('iCentesis', 'iEgCtsis')}


@lru_cache(maxsize=8)
def _catalog(database):
    items = {int(r['nItemId']): r for r in storage.template_rows('ItemTemplate_table.xml')}
    pets = {int(r['nId']): r for r in storage.template_rows('BoosterTemplate_table.xml')}
    levels = {int(r.get('nLevel', 0)): int(r['iExp'])
              for r in storage.template_rows('BoosterLevelTemplate_table.xml')}
    costs = {(int(r['nType']), int(r['nLevel'])): int(r['iCostMax'])
             for r in storage.template_rows('ConsumeLevelTemplate_table.xml')}
    return items, pets, levels, costs


def catalog():
    return _catalog(str(storage.database_path()))


@lru_cache(maxsize=8)
def _upgrade_rows(database):
    return {(int(r['nType']), int(r['nLevel'])): r
            for r in storage.template_rows('ConsumeLevelTemplate_table.xml')}


def _consume(containers, costs):
    """Validate the complete cost before touching any stack."""
    bag = containers.get('3', [])
    for ident, count in costs.items():
        if count <= 0 or sum(i['count'] for i in bag if i['template_id'] == ident) < count:
            raise ValueError('Không đủ nguyên liệu trợ thủ.')
    for ident, count in costs.items():
        for item in sorted(bag, key=lambda i: i['slot_no']):
            if item['template_id'] != ident:
                continue
            take = min(item['count'], count)
            item['count'] -= take
            count -= take
            if not count:
                break
    containers['3'] = [i for i in bag if i['count'] > 0]


def _rate_materials(containers, slots, rank):
    """HelperGradeUpProxy: up to three selected doses, including one stack twice."""
    bag = {i['slot_no']: i for i in containers.get('3', [])}
    qualified, extra = 0, 0
    for slot, count in Counter(slots).items():
        item = bag.get(slot)
        row = catalog()[0].get(item['template_id'], {}) if item else {}
        if item is None or item['count'] < count or int(row.get('nType') or 0) != 39:
            raise ValueError('Vật liệu tăng tỷ lệ không hợp lệ hoặc không đủ số lượng.')
        tier = int(row.get('iReuseB') or 0)
        qualified += count if tier >= rank // 2 else 0
        # Native assignment to uint truncates each dose before summation.
        extra += count * (int(row['iReuseA']) // (2 ** max(0, rank // 2 - tier)))
    extra += {2: 2_000_000, 3: 6_000_000}.get(qualified, 0)
    return extra, bag


def _upgrade(containers, wallet, pet, template, kind, slots):
    field, progress, limit = (('up_level', 'up_cost', 'iUpLevelLimit') if kind == 1
                              else ('rank', 'rank_cost', 'iRankLimit'))
    old = pet[field]
    if old >= int(template[limit]):
        raise ValueError('Trợ thủ đã đạt giới hạn nâng; không tiêu nguyên liệu.')
    row = _upgrade_rows(str(storage.database_path())).get((kind, old + 1))
    if row is None:
        raise ValueError('Thiếu cấu hình nâng trợ thủ; chưa tiêu nguyên liệu.')
    coin, amount = int(row['iCoin']), int(row['iItemCount'])
    rate, gain, maximum = int(row['iRate']), int(row['iCost']), int(row['iCostMax'])
    if coin < 0 or amount <= 0 or gain <= 0 or maximum <= 0 or not 0 <= rate <= 10_000_000:
        raise ValueError('Cấu hình nâng trợ thủ không hợp lệ.')
    if wallet['currency'][1] < coin:
        raise ValueError('Không đủ bạc để nâng trợ thủ.')
    extra, bag = _rate_materials(containers, slots, pet['rank'])
    # Only selected slots contribute/are spent; the base material is located
    # by its configured ID because C157/C158 do not send its slot.
    _consume(containers, {int(row['nItemId']): amount})
    for slot in slots:
        bag[slot]['count'] -= 1
    containers['3'] = [i for i in containers['3'] if i['count'] > 0]
    wallet['currency'][1] -= coin
    success = secrets.randbelow(10_000_000) < min(10_000_000, rate + extra)
    if success or pet[progress] + gain >= maximum:
        pet[field] += 1
        pet[progress] = 0
    else:
        pet[progress] += gain
    return 31 + kind, pet[field] != old, old, pet[field]


def _transfer(containers, left, left_template, right, right_template):
    if left['uuid'] == right['uuid']:
        raise ValueError('Hãy chọn hai trợ thủ khác nhau.')
    for source, target in ((left, right_template), (right, left_template)):
        for field, partial, cap in (('level', 'exp', 'iLevelLimit'),
                                    ('up_level', 'up_cost', 'iUpLevelLimit'),
                                    ('rank', 'rank_cost', 'iRankLimit')):
            if source[field] > int(target[cap]) or (source[field] == int(target[cap]) and source[partial]):
                raise ValueError('Tiến trình chuyển vượt giới hạn trợ thủ nhận; không tiêu nguyên liệu.')
    aptitude = max(int(left_template['nAptitude']), int(right_template['nAptitude']))
    count = 1 if aptitude <= 10 else 10 if aptitude <= 20 else aptitude // 5 - 1 if aptitude <= 50 else 10
    _consume(containers, {4000001: count})
    for field in ('level', 'exp', 'up_level', 'up_cost', 'rank', 'rank_cost'):
        left[field], right[field] = right[field], left[field]
    return 34, True, 0, 0


def snapshot(db):
    return shop._get(db, SETTING, {'starter_received': False, 'active': ''})


def _grant(containers, ident, count, *, level=0):
    row = catalog()[0][ident]
    bag = containers.setdefault(str(row['nContType']), [])
    maximum = int(row['iStackMax'])
    for item in bag:
        if item['template_id'] == ident and item['level'] == level:
            take = min(count, maximum - item['count'])
            item['count'] += take
            count -= take
    while count:
        occupied = {i['slot_no'] for i in bag}
        slot = next((s for s in range(135) if s not in occupied), None)
        if slot is None:
            raise ValueError('Túi trợ thủ/nguyên liệu đã đầy; hãy để trống ô rồi đăng nhập lại để nhận quà.')
        take = min(count, maximum)
        item = dict.fromkeys(inventory.FIELDS, 0)
        item.update(uuid='booster-' + uuid.uuid4().hex, template_id=ident, count=take,
                    level=level, ext_flag=1, create_time=int(time.time()), slot_no=slot)
        bag.append(item)
        count -= take


def initialize():
    """Authenticated profile only. Grant and receipt marker commit together."""
    with storage.connection(write=True) as db:
        profile = snapshot(db)
        if profile['starter_received']:
            return
        containers = inventory.load(db)
        _grant(containers, STARTER, 1, level=1)
        _grant(containers, CHIP, 10)
        profile['starter_received'] = True
        inventory.save(containers, db)
        shop._set(db, SETTING, profile)


def _pet(containers, *, slot=None, ident=None):
    item = next((i for i in containers.get('5', []) if
                 (i['slot_no'] == slot if slot is not None else i['uuid'] == ident)), None)
    if item is None or item['count'] != 1:
        raise ValueError('Trợ thủ không thuộc túi của bạn.')
    template = catalog()[0].get(item['template_id'], {})
    if int(template.get('nType', 0)) != 36 or int(template.get('iReuseA', 0)) not in catalog()[1]:
        raise ValueError('Trợ thủ không có cấu hình hợp lệ.')
    return item, catalog()[1][int(template['iReuseA'])]


def attributes(item):
    """HelperTool's displayed integers, including partial rank/strength progress."""
    _, row = _pet({'5': [item]}, ident=item['uuid'])
    costs = catalog()[3]
    def progress(kind, level, consumed):
        maximum = costs.get((kind, level + 1), 0)
        return D(level) + D(int(D(consumed) / maximum * 100)) / 100 if maximum else D(level)
    rank = progress(2, item['rank'], item['rank_cost'])
    up = progress(1, item['up_level'], item['up_cost'])
    level_factor = 1 + D(item['level']) * D('.05')
    result = {}
    for name, attr, field in (('hp', 4, 'iHp'), ('attack', 1, 'iAttack'),
                              ('armor', 3, 'iArmor'), ('penetration', 2, 'iCtsis')):
        base = D(row[field]) * level_factor
        extra = D(0)
        for suffix in ('A', 'B'):
            if attr == int(row.get('nType' + suffix, 0)):
                extra = base * (up * D(row['iAdd' + suffix]) + D(row['iValue' + suffix])) / 10_000_000
                break
        result[name] = int(base + extra + base * (rank * rank / 120 + rank / 12))
    result['score'] = int(1000 * level_factor * (1 + D(row['nAptitude']) * 4 / 50)
                          * (D('1.025') + rank * rank / 120 + rank / 12 + D('.0125') * up))
    return result


def active_item(db):
    active = snapshot(db)['active']
    return _pet(inventory.load(db), ident=active)[0] if active else None


def score(db):
    item = active_item(db)
    return attributes(item)['score'] if item else 0


def login_packets(db):
    return [(1100, inventory.list_payload(5, inventory.load(db).get('5', []))),
            (1056, pstr(snapshot(db)['active']))]


def apply(state, mid, payload, db):
    try:
        if state.get('battle') or state.get('tank_selection'):
            raise ValueError('Hãy về sảnh để đổi hoặc nuôi trợ thủ.')
        db.execute('BEGIN IMMEDIATE')
        profile, containers = snapshot(db), inventory.load(db)
        before = deepcopy(containers)
        packets = []
        if mid == 166:
            size, = struct.unpack_from('<H', payload)
            ident = payload[2:2 + size].decode('utf-8')
            shop._end(payload, 2 + size)
            _pet(containers, ident=ident)
            profile['active'] = '' if profile['active'] == ident else ident
            packets.append((1056, pstr(profile['active'])))
        elif mid == 156:
            slot, exp_slot = struct.unpack_from('<hi', payload)
            shop._end(payload, 6)
            pet, row = _pet(containers, slot=slot)
            cap, old = int(row['iLevelLimit']), pet['level']
            if old >= cap:
                raise ValueError('Trợ thủ đã đạt cấp tối đa; không tiêu chip.')
            chip = next((i for i in containers.get('3', []) if i['slot_no'] == exp_slot), None)
            template = catalog()[0].get(chip['template_id'], {}) if chip else {}
            if (chip is None or chip['count'] <= 0 or int(template.get('nType', 0)) != 37
                    or int(template.get('iReuseA', 0)) <= 0):
                raise ValueError('Hãy chọn chip EXP hợp lệ trong túi nguyên liệu.')
            pet['exp'] += int(template['iReuseA'])
            levels = catalog()[2]
            while pet['level'] < cap:
                need = levels.get(pet['level'], 0)
                if need <= 0:
                    raise ValueError('Thiếu cấu hình EXP; chưa tiêu chip.')
                if pet['exp'] < need:
                    break
                pet['exp'] -= need
                pet['level'] += 1
            if pet['level'] == cap:
                pet['exp'] = 0
            chip['count'] -= 1
            if not chip['count']:
                containers['3'].remove(chip)
            # Refresh inventory before result: the native handler looks up the new instance.
            packets = bag_updates(before, containers, (3, 5))
            packets.append((1106, struct.pack('<IBI', 31, 1, 0) + pstr(pet['uuid'])
                            + struct.pack('<ii', old, pet['level'])))
        elif mid in (157, 158, 159):
            slot, = struct.unpack_from('<h', payload)
            pet, template = _pet(containers, slot=slot)
            wallet = shop.snapshot(db)
            if mid == 159:
                other, = struct.unpack_from('<h', payload, 2)
                shop._end(payload, 4)
                right, right_template = _pet(containers, slot=other)
                result = _transfer(containers, pet, template, right, right_template)
            else:
                slots = ()
                if mid == 158:
                    count, = struct.unpack_from('<H', payload, 2)
                    if count > 3:
                        raise ValueError('Chỉ được dùng tối đa ba vật liệu tăng tỷ lệ.')
                    slots = struct.unpack_from('<' + 'h' * count, payload, 4)
                    shop._end(payload, 4 + 2 * count)
                else:
                    shop._end(payload, 2)
                result = _upgrade(containers, wallet, pet, template, mid - 156, slots)
                shop._set(db, shop.PROFILE, wallet)
                packets.append((1039, struct.pack('<HH6i', 2, 0, *wallet['currency'])))
            packets += bag_updates(before, containers, (3, 5))
            action, success, old, new = result
            packets.append((1106, struct.pack('<IBI', action, int(success), 0) + pstr(pet['uuid'])
                            + struct.pack('<ii', old, new)))
        else:
            raise ValueError('Yêu cầu trợ thủ không được hỗ trợ.')
        inventory.save(containers, db)
        shop._set(db, SETTING, profile)
        new_score = score(db)
        db.commit()
        state['booster_attack'] = new_score
        return packets, None
    except (ValueError, UnicodeError, struct.error) as exc:
        db.rollback()
        return [shop.tip(mid, str(exc))], str(exc)
    except BaseException:
        db.rollback()
        raise


def is_pve(room):
    # Never infer PvE from a pet alone.
    return (room.get('room_type') == 4 and room.get('map_id') in PVE_MAPS
            or room.get('room_type') == 7 and room.get('map_id') == 40002)


def battle_build(db, room):
    if not is_pve(room):
        return {}
    item = active_item(db)
    if item is None:
        return {}
    return dict(version=1, map_id=room['map_id'], uuid=item['uuid'], template_id=item['template_id'],
                level=item['level'], rank=item['rank'], up_level=item['up_level'],
                up_cost=item['up_cost'], rank_cost=item['rank_cost'], **attributes(item))


def other_brief(state, db=None):
    """Native CHAR_OTHER drives preload and CTank's decorative apparatus view."""
    room = state.get('room') or {}
    if not is_pve(room):
        return {}
    if state.get('battle'):
        build = state.get('booster_build', {})
    elif db is None:
        with storage.connection() as opened:
            return other_brief(state, opened)
    else:
        build = battle_build(db, room)
    if build.get('version') != 1 or build.get('map_id') != room['map_id']:
        return {}
    return dict(bt_item_id=build['template_id'], bt_level=build['level'],
                bt_rank=build.get('rank', 0), bt_up_level=build.get('up_level', 0),
                bt_up_cost=build.get('up_cost', 0), bt_rank_cost=build.get('rank_cost', 0),
                bt_atk=build.get('score', 0))


def apply_flat(stats, info, room):
    build = info.get('booster', {})
    if not is_pve(room) or build.get('version') != 1 or build.get('map_id') != room.get('map_id'):
        return
    for name, fields in FLAT.items():
        for field in fields:
            stats[field] = str(D(stats[field]) + D(build.get(name, 0)))
