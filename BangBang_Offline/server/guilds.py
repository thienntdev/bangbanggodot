"""Native Guild persistence. All mutations run under one SQLite transaction.

Account identity comes from authenticated GATE context, never from request UUIDs.
Boss/war, daily gifts, upkeep and automatic leader replacement are deferred.
"""
from datetime import datetime
from functools import lru_cache
import json
import sqlite3
import struct
import time
import uuid

import storage
import inventory
import cosmetic_shop as wallet
from characters import pstr, read_string

CARDS = (2600007, 2600006, 2600003)
CARD_PRICE = 10000
DONATION_ITEM = 8000002
# Counters on S1045 are contribution points, not the currency paid. The native
# exchange remains 100 silver / 1 cash -> 10 points. 500M cash would produce
# 5B points and 3.5B team funds, which cannot fit the existing signed-int32 ABI;
# keep that branch's old cap rather than truncating points or changing rates.
DONATION_SILVER_DAILY_COINS = 500_000_000
DONATION_SILVER_DAILY_POINTS = DONATION_SILVER_DAILY_COINS // 100 * 10
DONATION_CASH_DAILY_POINTS = 10_000
NATIVE_SIGNED_MAX = 0x7fffffff
SLOTS = (1, 5, 6, 7, 8)
DEFERRED = {70, 671, 673, 674, 675, 676}
REQUESTS = {68, 69, 71, 76, 77, 320, 321, 322, *range(651, 673), 778} | DEFERRED


def initialize():
    with storage.connection(write=True) as db:
        db.execute('CREATE TABLE IF NOT EXISTS guilds(id INTEGER PRIMARY KEY AUTOINCREMENT, '
                   'name TEXT UNIQUE COLLATE NOCASE NOT NULL, data TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS guild_teams(id INTEGER PRIMARY KEY AUTOINCREMENT, '
                   'guild INTEGER NOT NULL REFERENCES guilds(id) ON DELETE CASCADE, '
                   'name TEXT UNIQUE COLLATE NOCASE NOT NULL, data TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS guild_members(profile INTEGER PRIMARY KEY REFERENCES characters(profile_id), '
                   'guild INTEGER NOT NULL REFERENCES guilds(id) ON DELETE CASCADE, '
                   'team INTEGER NOT NULL REFERENCES guild_teams(id), data TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS guild_members_guild ON guild_members(guild)')
        db.execute('CREATE TABLE IF NOT EXISTS guild_applications(guild INTEGER REFERENCES guilds(id) ON DELETE CASCADE, '
                   'profile INTEGER REFERENCES characters(profile_id), inviter TEXT NOT NULL DEFAULT \'\', '
                   'PRIMARY KEY(guild,profile))')
        db.execute('CREATE TABLE IF NOT EXISTS guild_invites(profile INTEGER REFERENCES characters(profile_id), '
                   'guild INTEGER REFERENCES guilds(id) ON DELETE CASCADE, team INTEGER REFERENCES guild_teams(id) ON DELETE CASCADE, '
                   'starter INTEGER, expires INTEGER, PRIMARY KEY(profile,guild,team))')


def unpack_row(row):
    if row is None:
        return None
    result = dict(row)
    result.update(json.loads(result.pop('data')))
    return result


def member(db, profile=None):
    return unpack_row(db.execute('SELECT * FROM guild_members WHERE profile=?',
                                (storage.profile_id() if profile is None else profile,)).fetchone())


def guild(db, ident):
    return unpack_row(db.execute('SELECT * FROM guilds WHERE id=?', (ident,)).fetchone())


def team(db, ident):
    return unpack_row(db.execute('SELECT * FROM guild_teams WHERE id=?', (ident,)).fetchone())


def members(db, ident):
    return [unpack_row(r) for r in db.execute('SELECT * FROM guild_members WHERE guild=? ORDER BY profile', (ident,))]


def teams(db, ident):
    return [unpack_row(r) for r in db.execute('SELECT * FROM guild_teams WHERE guild=? ORDER BY id', (ident,))]


def save(db, table, record):
    columns = {'guilds': ('id', 'name'), 'guild_teams': ('id', 'guild', 'name'),
               'guild_members': ('profile', 'guild', 'team')}[table]
    data = {k: v for k, v in record.items() if k not in columns}
    assignments = ','.join(f'{k}=?' for k in columns[1:]) + ',data=?'
    db.execute(f'UPDATE {table} SET {assignments} WHERE {columns[0]}=?',
               (*(record[k] for k in columns[1:]), json.dumps(data, ensure_ascii=False), record[columns[0]]))


def state_for(db, profile):
    row = db.execute('SELECT state FROM worlds WHERE profile_id=?', (profile,)).fetchone()
    if not row:
        raise ValueError('Không tìm thấy nhân vật.')
    return json.loads(row[0])


def find_character(db, text):
    for row in db.execute('SELECT profile_id,state FROM worlds'):
        state = json.loads(row['state'])
        if text in (state['char_uuid'], state['name']):
            return row['profile_id']
    raise ValueError('Không tìm thấy nhân vật.')


def account(db, profile=None):
    profile = storage.profile_id() if profile is None else profile
    key = f'guild_account:{profile}'
    row = db.execute('SELECT value FROM settings WHERE name=?', (key,)).fetchone()
    result = json.loads(row[0]) if row else dict(learned={}, slots={}, flags=0, joined_day='', last_seen=0)
    day = datetime.now().date().isoformat()
    if result.get('day') != day:
        result.update(day=day, silver_donation=0, cash_donation=0)
    return result


def save_account(db, data, profile=None):
    profile = storage.profile_id() if profile is None else profile
    db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
               (f'guild_account:{profile}', json.dumps(data, ensure_ascii=False)))


def name_checked(name):
    if not name.strip() or len(name.encode('utf8')) > 12 or any(ord(c) < 32 for c in name):
        raise ValueError('Tên không được trống, tối đa 12 byte UTF-8 và không chứa ký tự điều khiển.')
    return name.strip()


@lru_cache(maxsize=4)
def tables(path):
    skills = {(int(r['nGuildSkillId']), int(r['nLevel'])): r
              for r in storage.template_rows('GuildSkillTemplate_table.xml')}
    levels = {int(r['nLevel']): r for r in storage.template_rows('GuildTemplate_table.xml')}
    types = {int(r['nId']): int(r.get('nType', 0)) for r in storage.template_rows('SkillTemplate_table.xml')}
    return skills, levels, types


def config():
    return tables(str(storage.database_path()))


def battle_build(db, profile=None):
    """Freeze the equipped, learned, researched build at match entry."""
    a, mine = account(db, profile), member(db, profile)
    if mine is None:
        return {}
    researched = guild(db, mine['guild'])['research']
    equipped = {}
    for slot, (group, selected) in a['slots'].items():
        level = min(selected, a['learned'].get(str(group), 0), researched.get(str(group), 0))
        row = config()[0].get((group, level))
        if row and int(slot) in SLOTS and a['flags'] & (1 << int(slot)):
            equipped[slot] = dict(group=group, level=level, skill=int(row['nSkillTpltPvpId']))
    return equipped


def require_member(db):
    mine = member(db)
    if mine is None:
        raise ValueError('Bạn chưa tham gia Guild.')
    return mine, guild(db, mine['guild'])


def require_officer(g, leader=False):
    allowed = (g['leader'],) if leader else (g['leader'], g['vice'])
    if storage.profile_id() not in allowed:
        raise ValueError('Bạn không có quyền thực hiện thao tác này.')


def spend_card(db, ident):
    bags = inventory.load(db)
    for container, items in bags.items():
        for item in items:
            if item['template_id'] == ident and item['count'] > 0:
                item['count'] -= 1
                inventory.save(bags, db)
                return [(1100, inventory.list_payload(container, [item], notify_type=2))]
    raise ValueError('Bạn chưa có thẻ cần thiết. Hãy mua thẻ trước.')


def join(db, g, target, tid, now, merit=0):
    if member(db, target):
        raise ValueError('Nhân vật đã ở trong một Guild.')
    target_state = state_for(db, target)
    if target_state['level'] < g['min_level']:
        raise ValueError('Nhân vật chưa đủ cấp vào Guild.')
    # Ranked play is not implemented; characters have no earned ranked score.
    if g['min_ladder'] > 0:
        raise ValueError('Nhân vật chưa đạt điều kiện xếp hạng của Guild.')
    t = team(db, tid)
    if not t or t['guild'] != g['id']:
        raise ValueError('Đội không thuộc Guild này.')
    if db.execute('SELECT COUNT(*) FROM guild_members WHERE team=?', (tid,)).fetchone()[0] >= 10:
        raise ValueError('Đội đã đủ 10 thành viên.')
    a = account(db, target)
    if a['joined_day'] == a['day']:
        raise ValueError('Mỗi ngày chỉ được vào Guild một lần.')
    m = dict(joined=now, transferred=0, merit=merit, all_merit=merit)
    db.execute('INSERT INTO guild_members VALUES (?,?,?,?)', (target, g['id'], tid, json.dumps(m)))
    db.execute('DELETE FROM guild_applications WHERE profile=?', (target,))
    db.execute('DELETE FROM guild_invites WHERE profile=?', (target,))
    a['joined_day'] = a['day']
    save_account(db, a, target)


def create(db, guild_name, team_name, now):
    if member(db):
        raise ValueError('Bạn đã ở trong một Guild.')
    names = name_checked(guild_name), name_checked(team_name)
    packets = spend_card(db, CARDS[0])
    profile = storage.profile_id()
    data = dict(level=1, coin=1000, leader=profile, vice=0, created=now, settings=0,
                min_level=1, min_ladder=0, notice='', recruit='', channel='', research={})
    ident = db.execute('INSERT INTO guilds(name,data) VALUES (?,?)', (names[0], json.dumps(data))).lastrowid
    tid = create_team(db, ident, names[1], now, leader=profile)
    join(db, guild(db, ident), profile, tid, now, 2000)
    return ident, packets


def create_team(db, gid, name, now, leader=0):
    data = dict(leader=leader, created=now, level=1, coin=1000, glory=0, merit=0)
    return db.execute('INSERT INTO guild_teams(guild,name,data) VALUES (?,?,?)',
                      (gid, name_checked(name), json.dumps(data))).lastrowid


def research(db, g, group):
    require_officer(g)
    level = g['research'].get(str(group), 0) + 1
    row = config()[0].get((group, level))
    if row is None or g['level'] < int(row['nNeedGuildLevel']):
        raise ValueError('Guild chưa đủ cấp hoặc kỹ năng đã đạt cấp tối đa.')
    cost = int(row.get('nResearchFee', 0))
    if g['coin'] < cost:
        raise ValueError('Quỹ Guild không đủ để nghiên cứu.')
    g['coin'] -= cost
    g['research'][str(group)] = level
    save(db, 'guilds', g)


def skills(db, state, mid, values):
    mine, g = require_member(db)
    a = account(db)
    if mid == 320:
        group = values[0]
        level = a['learned'].get(str(group), 0) + 1
        row = config()[0].get((group, level))
        if not row or level > g['research'].get(str(group), 0):
            raise ValueError('Guild chưa nghiên cứu cấp kỹ năng này.')
        if state['level'] < int(row.get('nCharLevelMin', 0)):
            raise ValueError('Nhân vật chưa đủ cấp học kỹ năng.')
        cost = int(row['nNeedMerit'])
        if mine['merit'] < cost:
            raise ValueError('Không đủ cống hiến học kỹ năng.')
        mine['merit'] -= cost
        a['learned'][str(group)] = level
    elif mid == 321:
        slot = values[0]
        if slot not in SLOTS or a['flags'] & (1 << slot):
            raise ValueError('Ô kỹ năng không hợp lệ hoặc đã mở.')
        cost = 750 * SLOTS.index(slot)**2
        if mine['merit'] < cost:
            raise ValueError('Không đủ cống hiến mở ô kỹ năng.')
        mine['merit'] -= cost
        a['flags'] |= 1 << slot
    else:
        slot, group, level = values
        if slot not in SLOTS or not a['flags'] & (1 << slot):
            raise ValueError('Ô kỹ năng chưa mở.')
        if group == level == 0:
            a['slots'].pop(str(slot), None)
        else:
            maximum = min(a['learned'].get(str(group), 0), g['research'].get(str(group), 0))
            if not 1 <= level <= a['learned'].get(str(group),0) or maximum==0:
                raise ValueError('Kỹ năng chưa học hoặc Guild chưa nghiên cứu.')
            level=min(level,maximum)
            row = config()[0].get((group, level))
            if not row or not 1 <= level <= maximum:
                raise ValueError('Kỹ năng chưa học hoặc vượt cấp Guild đã nghiên cứu.')
            skill_type = config()[2].get(int(row['nSkillTpltPvpId']))
            if (slot == 1) != (skill_type in (1, 2)):
                raise ValueError('Kỹ năng không đúng loại ô chủ động/bị động.')
            if any(int(k) != slot and v[0] == group for k, v in a['slots'].items()):
                raise ValueError('Kỹ năng này đã được xếp ở ô khác.')
            a['slots'][str(slot)] = [group, level]
    save(db, 'guild_members', mine)
    save_account(db, a)


def purchase(db, state, payload):
    kind, goods, coin, price, count, n = struct.unpack_from('<iIIiiH', payload)
    silver_donation = kind == 8 and goods == 400000000 + DONATION_ITEM and coin == 2
    count_limit = DONATION_SILVER_DAILY_COINS // 100 if silver_donation else 100000
    if n > 6 or not 1 <= count <= count_limit:
        raise ValueError('Số lượng mua không hợp lệ.')
    entries = [struct.unpack_from('<Ii', payload, 22 + i*8) for i in range(n)]
    wallet._end(payload, 22 + n*8)
    paid = dict(entries)
    if len(paid) != n or any(k not in range(1, 7) or v < 0 for k, v in entries):
        raise ValueError('Yêu cầu thanh toán không hợp lệ.')
    item_id = goods - 400000000
    profile = wallet.snapshot(db)
    packets = []
    gid = None
    if kind == 1 and item_id in CARDS:
        expected = CARD_PRICE
        if coin != 2 or count > 9999:
            raise ValueError('Thẻ Guild chỉ bán bằng bạc.')
        bags = inventory.load(db)
        items = bags.setdefault('2', [])
        item = next((r for r in items if r['template_id'] == item_id), None)
        if item is None:
            occupied = {r['slot_no'] for r in items}
            slot = next((s for s in range(inventory.grocery_capacity(db)) if s not in occupied), None)
            if slot is None:
                raise ValueError('Túi vật phẩm đã đầy.')
            item = dict.fromkeys(inventory.FIELDS, 0)
            item.update(uuid='guild-card-'+uuid.uuid4().hex, template_id=item_id,
                        create_time=int(time.time()), slot_no=slot)
            items.append(item)
        item['count'] += count
        if item['count'] > 9999:
            raise ValueError('Tối đa 9.999 thẻ mỗi loại.')
        inventory.save(bags, db)
        packets.append((1100, inventory.list_payload(2, [item], notify_type=2)))
    elif kind == 8 and item_id == DONATION_ITEM and coin in (2, 1):
        mine, g = require_member(db)
        t = team(db, mine['team'])
        a = account(db)
        expected = 100 if coin == 2 else 1
        key = 'silver_donation' if coin == 2 else 'cash_donation'
        cap = DONATION_SILVER_DAILY_POINTS if coin == 2 else DONATION_CASH_DAILY_POINTS
        amount = count*10
        if type(a.get(key)) is not int or not 0 <= a[key] <= NATIVE_SIGNED_MAX:
            raise ValueError('Bộ đếm đóng góp chưa hợp lệ. Chưa trừ tiền.')
        if a[key]+amount > cap:
            raise ValueError('Vượt giới hạn đóng góp hôm nay.')
        # Validate every cumulative signed field before modifying records. A
        # daily cap alone cannot protect a guild with many members or old
        # balances already near the wire limit. Never clamp, wrap or partially
        # donate; guild_protocol.apply owns the transaction and ACK preflight.
        for record, field, addition, label in (
                (mine, 'merit', amount, 'Cống hiến hiện tại'),
                (mine, 'all_merit', amount, 'Tổng cống hiến'),
                (g, 'coin', count*3, 'Quỹ Guild'),
                (t, 'coin', count*7, 'Quỹ Team'),
                (t, 'merit', amount, 'Cống hiến Team')):
            current = record.get(field)
            if type(current) is not int or not 0 <= current <= NATIVE_SIGNED_MAX - addition:
                raise ValueError(label + ' sẽ vượt giới hạn 2.147.483.647 của giao thức. Chưa trừ tiền.')
        a[key] += amount
        mine['merit'] += amount
        mine['all_merit'] += amount
        g['coin'] += count*3
        t['coin'] += count*7
        t['merit'] += amount
        for table, record in (('guild_members', mine), ('guilds', g), ('guild_teams', t)):
            save(db, table, record)
        save_account(db, a)
        gid = g['id']
    else:
        raise ValueError('Mặt hàng Guild chưa được mở.')
    cost = expected*count
    if price != expected or paid.get(coin) != cost or any(v for k, v in paid.items() if k != coin):
        raise ValueError('Giá hoặc loại tiền không đúng.')
    if profile['currency'][coin-1] < cost:
        raise ValueError('Không đủ tiền.')
    profile['currency'][coin-1] -= cost
    wallet._set(db, wallet.PROFILE, profile)
    packets.insert(0, (1039, struct.pack('<HH6i', 2, 0, *profile['currency'])))
    return gid, packets


def is_purchase(payload):
    if len(payload) < 8:
        return False
    kind, goods = struct.unpack_from('<iI', payload)
    return kind in (8, 10) or goods-400000000 in (*CARDS, DONATION_ITEM)


class Reader:
    def __init__(self, payload):
        self.payload, self.pos = payload, 0

    def number(self, fmt='I'):
        value, = struct.unpack_from('<'+fmt, self.payload, self.pos)
        self.pos += struct.calcsize('<'+fmt)
        return value

    def text(self):
        result, self.pos = read_string(self.payload, self.pos)
        return result

    def end(self):
        wallet._end(self.payload, self.pos)


def same_member(db, g, text, tid=None):
    target = find_character(db, text)
    m = member(db, target)
    if not m or m['guild'] != g['id'] or tid is not None and m['team'] != tid:
        raise ValueError('Thành viên không thuộc Guild/đội này.')
    return m


def move(db, g, first, dest, other, now):
    if dest['guild'] != g['id'] or dest['id'] == first['team']:
        raise ValueError('Đội đích không hợp lệ.')
    moving = [first] + ([other] if other else [])
    if not other and db.execute('SELECT COUNT(*) FROM guild_members WHERE team=?', (dest['id'],)).fetchone()[0] >= 10:
        raise ValueError('Đội đích đã đầy.')
    for m in moving:
        if m['transferred'] and now-m['transferred'] < 86400:
            raise ValueError('Chưa đủ 1 ngày từ lần chuyển đội trước.')
        t = team(db, m['team'])
        if t['leader'] == m['profile']:
            raise ValueError('Hãy chuyển chức đội trưởng trước khi chuyển đội.')
    original = first['team']
    first['team'] = dest['id']
    if other:
        other['team'] = original
    for m in moving:
        m['merit'] -= m['merit']//2
        m['transferred'] = now
        save(db, 'guild_members', m)


def mutate(db, state, mid, payload, online=()):
    """Return affected Guild, immediate packets and explicit cross-account events."""
    now, profile = int(time.time()), storage.profile_id()
    r, packets, events = Reader(payload), [], {}
    if mid in DEFERRED or mid == 71:
        raise ValueError('Nhánh này chưa được mở trong bản Guild hiện tại.')
    if mid == 69:
        name, team_name = r.text(), r.text()
        r.end()
        gid, packets = create(db, name, team_name, now)
        return gid, packets, events
    if mid == 250:
        gid, packets = purchase(db, state, payload)
        return gid, packets, events
    if mid in (651, 656):
        gid = r.number()
        g = guild(db, gid)
        if g is None or member(db):
            raise ValueError('Guild không tồn tại hoặc bạn đã có Guild.')
        if mid == 651:
            tid = r.number()
            r.end()
            invite = db.execute('SELECT 1 FROM guild_invites WHERE profile=? AND guild=? AND team=?',
                                (profile, gid, tid)).fetchone()
            if not invite and not g['settings'] & 1:
                raise ValueError('Guild cần duyệt đơn hoặc lời mời hợp lệ.')
            if g['settings'] & 2 and not invite:
                raise ValueError('Guild đang đóng tuyển thành viên.')
            join(db, g, profile, tid, now)
        else:
            inviter, fast = r.text(), r.number('B')
            r.end()
            if g['settings'] & 2:
                raise ValueError('Guild đang đóng tuyển thành viên.')
            if state['level'] < g['min_level'] or g['min_ladder'] > 0:
                raise ValueError('Bạn chưa đạt điều kiện tuyển thành viên.')
            if g['settings'] & 1:
                choices = teams(db, gid)
                choices.sort(key=lambda t: (db.execute('SELECT COUNT(*) FROM guild_members WHERE team=?',
                                                       (t['id'],)).fetchone()[0], t['id']))
                if not choices:
                    raise ValueError('Guild chưa có đội nhận thành viên.')
                join(db, g, profile, choices[0]['id'], now)
            else:
                if account(db)['joined_day'] == account(db)['day']:
                    raise ValueError('Mỗi ngày chỉ được vào Guild một lần.')
                db.execute('INSERT INTO guild_applications VALUES (?,?,?) ON CONFLICT DO NOTHING',
                           (gid, profile, inviter[:100]))
                packets.append(wallet.tip(mid, 'Đã gửi đơn xin vào Guild.'))
        return gid, packets, events
    mine, g = require_member(db)
    gid = g['id']
    if mid in (320, 321, 322):
        values = [r.number() for _ in range(3 if mid == 322 else 1)]
        r.end()
        skills(db, state, mid, values)
    elif mid == 672:
        group = r.number(); r.end()
        research(db, g, group)
    elif mid == 68:
        name = r.text(); r.end()
        require_officer(g)
        if len(teams(db, gid)) >= int(config()[1][g['level']]['nTeamCount']):
            raise ValueError('Guild đã đủ số đội theo cấp hiện tại.')
        if g['coin'] < 10000:
            raise ValueError('Quỹ Guild cần ít nhất 10.000 để tạo đội.')
        create_team(db, gid, name, now)
        g['coin'] -= 1000
        save(db, 'guilds', g)
    elif mid in (76, 77):
        name = name_checked(r.text())
        if mid == 77:
            require_officer(g, leader=True)
            record, table, card = g, 'guilds', 2600006
        else:
            record = team(db, r.number())
            if not record or record['guild'] != gid or record['leader'] != profile:
                raise ValueError('Chỉ đội trưởng được đổi tên đội của mình.')
            table, card = 'guild_teams', 2600003
        r.end()
        packets += spend_card(db, card)
        record['name'] = name
        save(db, table, record)
    elif mid == 660:
        r.end(); require_officer(g)
        row = config()[1][g['level']]
        cost = int(row.get('iNextCoin', 0))
        if not cost or g['level']+1 not in config()[1]:
            raise ValueError('Guild đã đạt cấp tối đa.')
        if g['coin'] < cost:
            raise ValueError('Quỹ Guild chưa đủ để nâng cấp.')
        g['coin'] -= cost
        g['level'] += 1
        save(db, 'guilds', g)
    elif mid in (661, 662, 663):
        require_officer(g)
        text = r.text(); r.end()
        if len(text.encode('utf8')) > 1000 or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            raise ValueError('Nội dung quá dài hoặc chứa ký tự không hợp lệ.')
        g[{661:'channel', 662:'notice', 663:'recruit'}[mid]] = text
        save(db, 'guilds', g)
    elif mid == 655:
        require_officer(g)
        kind, val = r.number('i'), r.number('i'); r.end()
        if kind == 1 and 0 <= val <= 7:
            g['settings'] = val
        elif kind == 2 and 1 <= val <= 100:
            g['min_level'] = val
        elif kind == 3 and 0 <= val <= 100000:
            g['min_ladder'] = val
        else:
            raise ValueError('Thiết lập tuyển thành viên không hợp lệ.')
        save(db, 'guilds', g)
    elif mid in (652, 653):
        target = mine if mid == 652 else same_member(db, g, r.text(), r.number())
        r.end()
        if target['profile'] == g['leader'] and len(members(db, gid)) > 1:
            raise ValueError('Hãy chuyển chức chủ hội trước khi rời Guild.')
        if mid == 653:
            t = team(db, target['team'])
            own_team = team(db, mine['team'])
            allowed = profile == g['leader'] or (profile == g['vice'] and target['profile'] != g['leader'])
            allowed |= (own_team['leader'] == profile and mine['team'] == target['team']
                        and target['profile'] not in (g['leader'], g['vice']))
            if not allowed or target['profile'] == profile:
                raise ValueError('Bạn không có quyền đuổi thành viên này.')
            last = account(db, target['profile'])['last_seen'] or now
            days = 0 if target['profile'] in online else max(0, (now-last)//86400)
            rate = (30,70) if days < 2 else (20,40) if days < 3 else (10,20) if days < 5 else (5,10) if days < 7 else (0,0)
            cost_g, cost_t = (target['all_merit']*v//100 for v in rate)
            if g['coin'] < cost_g or t['coin'] < cost_t:
                raise ValueError('Quỹ Guild hoặc đội không đủ phí đuổi thành viên.')
            g['coin'] -= cost_g
            t['coin'] -= cost_t
            save(db, 'guild_teams', t)
        char = state_for(db, target['profile'])['char_uuid']
        for m in members(db, gid):
            events[m['profile']] = [(1802 if mid == 653 else 1801, pstr(char))]
        db.execute('DELETE FROM guild_members WHERE profile=?', (target['profile'],))
        if g['vice'] == target['profile']:
            g['vice'] = 0
        for t in teams(db, gid):
            if t['leader'] == target['profile']:
                t['leader'] = 0
                save(db, 'guild_teams', t)
        if not members(db, gid):
            db.execute('DELETE FROM guilds WHERE id=?', (gid,))
        else:
            save(db, 'guilds', g)
    elif mid == 654:
        target_name, post, tid = r.text(), r.number('i'), r.number(); r.end()
        target = same_member(db, g, target_name, tid)
        t = team(db, tid)
        if post in (9, 10) or target['profile'] in (g['leader'], g['vice']):
            require_officer(g, leader=True)
        elif profile not in (g['leader'], g['vice'], t['leader']):
            raise ValueError('Bạn không có quyền thay chức vụ này.')
        if post == 10:
            if target['profile'] == profile:
                raise ValueError('Nhân vật đã là chủ hội.')
            g['leader'] = target['profile']
            if g['vice'] == target['profile']:
                g['vice'] = 0
        elif post == 9:
            if target['profile'] == g['leader']:
                raise ValueError('Không thể đặt chủ hội làm phó hội.')
            g['vice'] = target['profile']
        elif post == 5:
            t['leader'] = target['profile']
        elif post == 0 and target['profile'] != g['leader']:
            if g['vice'] == target['profile']: g['vice'] = 0
            if t['leader'] == target['profile']: t['leader'] = 0
        else:
            raise ValueError('Chức vụ không hợp lệ.')
        save(db, 'guilds', g); save(db, 'guild_teams', t)
    elif mid in (658, 659):
        require_officer(g)
        name = r.text()
        tid = r.number() if mid == 658 else None
        r.end()
        target = find_character(db, name) if name else None
        if mid == 659 and target is None:
            db.execute('DELETE FROM guild_applications WHERE guild=?', (gid,))
        else:
            if not db.execute('SELECT 1 FROM guild_applications WHERE guild=? AND profile=?', (gid, target)).fetchone():
                raise ValueError('Đơn xin vào Guild không còn tồn tại.')
            if mid == 658:
                join(db, g, target, tid, now)
            else:
                db.execute('DELETE FROM guild_applications WHERE guild=? AND profile=?', (gid, target))
    elif mid == 665:
        require_officer(g)
        tid = r.number(); r.end()
        t = team(db, tid)
        if not t or t['guild'] != gid:
            raise ValueError('Đội không thuộc Guild.')
        if db.execute('SELECT 1 FROM guild_members WHERE team=?', (tid,)).fetchone():
            raise ValueError('Hãy chuyển hết thành viên trước khi giải tán đội.')
        if len(teams(db, gid)) <= 1:
            raise ValueError('Guild phải giữ ít nhất một đội.')
        db.execute('DELETE FROM guild_teams WHERE id=?', (tid,))
    elif mid == 668:
        origin, first_name, dest_id, second_name = r.number(), r.text(), r.number(), r.text(); r.end()
        first = same_member(db, g, first_name, origin)
        other = same_member(db, g, second_name, dest_id) if second_name else None
        if profile != first['profile'] or other is not None:
            require_officer(g)
        dest = team(db, dest_id)
        if dest is None:
            raise ValueError('Đội đích không tồn tại.')
        move(db, g, first, dest, other, now)
    elif mid in (669, 778):
        if mid == 669:
            tid, name = r.number(), r.text()
        else:
            name, tid = r.text(), r.number()
        r.end()
        t = team(db, tid)
        if not t or t['guild'] != gid:
            raise ValueError('Đội không thuộc Guild.')
        if profile not in (g['leader'], g['vice'], t['leader']) and not g['settings'] & 4:
            raise ValueError('Guild chưa cho thành viên thường mời người.')
        target = find_character(db, name)
        target_member = member(db, target)
        if (target == profile or target_member and (mid == 778 or target_member['guild'] != gid)
                or mid == 669 and target_member is None):
            raise ValueError('Không thể mời nhân vật này.')
        db.execute('INSERT INTO guild_invites VALUES (?,?,?,?,?) ON CONFLICT DO UPDATE SET starter=excluded.starter',
                   (target, gid, tid, profile, 0))
        if mid == 778:
            body = pstr(state['name']) + struct.pack('<I', gid) + pstr(g['name']) + struct.pack('<I', tid) + pstr(t['name']) + b'\x01'
            events[target] = [(1804, body)]
        else:
            body = pstr(state['char_uuid']) + pstr(state_for(db, target)['char_uuid']) + struct.pack('<I', tid) + pstr(t['name'])
            events[target] = [(1830, body)]
    elif mid == 670:
        tid, text = r.number(), r.text(); r.end()
        if text != state['char_uuid']:
            raise ValueError('Chỉ người nhận được chấp nhận lời mời chuyển đội.')
        if not db.execute('SELECT 1 FROM guild_invites WHERE profile=? AND guild=? AND team=?', (profile, gid, tid)).fetchone():
            raise ValueError('Không có lời mời chuyển đội này.')
        move(db, g, mine, team(db, tid), None, now)
        db.execute('DELETE FROM guild_invites WHERE profile=?', (profile,))
    elif mid in (657, 664, 666, 667):
        if mid == 664:
            tid = r.number()
            if not team(db, tid) or team(db, tid)['guild'] != gid:
                raise ValueError('Đội không thuộc Guild.')
        if mid == 657: require_officer(g)
        r.end()
    else:
        raise ValueError('Thao tác Guild chưa hỗ trợ.')
    return gid, packets, events
