"""Native Guild packets, HTTP views and delivery to authenticated online peers."""
import json
import queue
import sqlite3
import struct
import threading
import time
import xml.etree.ElementTree as ET

import storage
import guilds as g
from characters import pstr
from cosmetic_shop import tip

_peers = {}
_guard = threading.Lock()
HTTP_ROUTES = frozenset(('cguildjoinlist.php', 'cguildinfo.php', 'cteaminfo.php',
                         'cteamplace.php', 'goodsshopquickquery.php',
                         'cguildlist.php', 'cteamserverlist.php', 'cteammember.php'))


def online():
    with _guard:
        return set(_peers)


def register(profile):
    inbox = queue.SimpleQueue()
    with _guard:
        _peers[profile] = inbox
    with storage.connection(write=True) as db:
        a = g.account(db, profile); a['last_seen'] = int(time.time()); g.save_account(db, a, profile)
    return inbox


def unregister(profile, inbox):
    with _guard:
        if _peers.get(profile) is inbox:
            del _peers[profile]
    with storage.connection(write=True) as db:
        a = g.account(db, profile); a['last_seen'] = int(time.time()); g.save_account(db, a, profile)


def deliver(profile, packets):
    with _guard:
        inbox = _peers.get(profile)
        if inbox is not None:
            inbox.put(packets)


def char_uuid(db, profile):
    return g.state_for(db, profile)['char_uuid'] if profile else ''


def buddy(db, profile, connected):
    s = g.state_for(db, profile)
    last = g.account(db, profile)['last_seen']
    return (struct.pack('<I', profile) + pstr(s['char_uuid']) + pstr(s['name']) + pstr('')
            + struct.pack('<8Bh6I', s['level'], s['sex'], int(profile in connected), 0, 0,
                          s['vip_level'], 0, 0, 0, 0, last, s.get('avatar', 0), s.get('decorate_id', 0), 0, 0))


def guild_info(db, guild):
    return (struct.pack('<I', guild['id']) + pstr(guild['name']) + struct.pack('<I', guild['level'])
            + pstr(char_uuid(db, guild['leader'])) + pstr(char_uuid(db, guild['vice'])) + pstr(guild['notice'])
            + struct.pack('<IiIiII', 0, guild['coin'], guild['created'], guild['settings'], guild['min_level'], guild['min_ladder'])
            + pstr(guild['recruit']) + struct.pack('<II', 0, 0))


def team_info(db, team):
    return (struct.pack('<II', team['id'], team['guild']) + pstr(team['name']) + pstr(char_uuid(db, team['leader']))
            + struct.pack('<4I3iIi', 0, 0, team['created'], team['level'], team['coin'], team['glory'], team['merit'], 0, 0))


def member_info(db, m):
    return (struct.pack('<I', m['team']) + pstr(char_uuid(db, m['profile']))
            + struct.pack('<IIIiiII', m['profile'], m['joined'], m['transferred'], m['merit'], m['all_merit'], 0, 0))


def skill_list(values, reset=True):
    return (struct.pack('<H', len(values)) + b''.join(struct.pack('<II', int(k), v) for k, v in sorted(values.items()))
            + struct.pack('<I', int(reset)))


def slots(a):
    return (struct.pack('<H', len(a['slots']))
            + b''.join(struct.pack('<III', int(k), *v) for k, v in sorted(a['slots'].items()))
            + struct.pack('<I', a['flags']))


def apply_list(db, gid, connected):
    rows = list(db.execute('SELECT profile,inviter FROM guild_applications WHERE guild=? ORDER BY profile', (gid,)))
    # Native InviteInfo maps an applicant UUID to the inviter's display name.
    refs = [r for r in rows if r['inviter']]
    payload = struct.pack('<H', len(rows)) + b''.join(buddy(db, r['profile'], connected) for r in rows)
    payload += struct.pack('<H', len(refs))
    payload += b''.join(struct.pack('<I', r['profile']) + pstr(r['inviter']) for r in refs)
    return 1816, payload


def snapshot(db, profile, connected=None):
    connected = online() if connected is None else connected
    a, mine = g.account(db, profile), g.member(db, profile)
    packets = []
    if mine:
        guild = g.guild(db, mine['guild'])
        teams, members = g.teams(db, guild['id']), g.members(db, guild['id'])
        packets.append((1508, struct.pack('<H', len(members)) + b''.join(buddy(db, m['profile'], connected) for m in members)))
        packets.append((1800, guild_info(db, guild) + struct.pack('<H', len(teams))
                        + b''.join(team_info(db, t) for t in teams) + struct.pack('<I', mine['team'])))
        for t in teams:
            rows = [m for m in members if m['team'] == t['id']]
            packets.append((1831, struct.pack('<IIIH', 0, guild['id'], t['id'], len(rows))
                            + b''.join(member_info(db, m) for m in rows)))
        packets.append((1832, skill_list(guild['research'])))
        if profile in (guild['leader'], guild['vice']):
            packets.append(apply_list(db, guild['id'], connected))
    packets.extend([(1351, skill_list(a['learned'])), (1350, slots(a)),
                    (1045, struct.pack('<HIiIiIi', 3, 2, int(a['joined_day'] == a['day']),
                                       12, a['silver_donation'], 220, a['cash_donation']))])
    return packets


def apply(state, mid, payload, db):
    try:
        if state.get('battle'):
            raise ValueError('Hãy về sảnh/phòng chờ để thao tác Guild.')
        connected = online()
        db.execute('BEGIN IMMEDIATE')
        if mid in (666, 667) and g.member(db) is None:
            g.Reader(payload).end()
            gid, immediate, events = None, [], {}
        else:
            gid, immediate, events = g.mutate(db, state, mid, payload, connected)
        recipients = {storage.profile_id()}
        if gid is not None:
            recipients.update(m['profile'] for m in g.members(db, gid) if m['profile'] in connected)
        recipients.update(events)
        results = {ident: events.get(ident, []) + snapshot(db, ident, connected) for ident in recipients}
        results[storage.profile_id()] = immediate + results[storage.profile_id()]
        db.commit()
        for ident, packets in results.items():
            if ident != storage.profile_id(): deliver(ident, packets)
        return results[storage.profile_id()], None
    except (ValueError, UnicodeError, struct.error, sqlite3.IntegrityError) as exc:
        db.rollback()
        message = ('Tên Guild/đội đã có người sử dụng.' if isinstance(exc, sqlite3.IntegrityError)
                   else str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError)
                   else 'Yêu cầu Guild không hợp lệ.')
        return [tip(mid, message)], message
    except BaseException:
        db.rollback()
        raise


def quickshop(qs):
    ident = int(qs.get('tid', ['0'])[0])
    root = ET.Element('query', amount='1' if ident in (*g.CARDS, g.DONATION_ITEM) else '0', cur_time=str(int(time.time())))
    if ident in (*g.CARDS, g.DONATION_ITEM):
        donate = ident == g.DONATION_ITEM
        row = dict(goods_id=400000000+ident, first_label=100, second_label=0, goods_type=4,
                   template_oid=ident, limit_level=0, vip_level=0, count_1=0, count_2=0, count_3=0,
                   coin_type=1 if donate else 2, price1=1 if donate else g.CARD_PRICE,
                   price2=0, price3=0, coin_type2=2 if donate else 0, price2_1=100 if donate else 0,
                   price2_2=0, price2_3=0, is_new=0, is_hot=0, is_agio=0, is_limit_time=0,
                   is_limit_count=0, can_use_gift=0, slot_no=0, goods_uuid=f'guild-goods-{ident}')
        ET.SubElement(root, 'row', {k: str(v) for k, v in row.items()})
    return ET.tostring(root, encoding='utf8', xml_declaration=True), 'application/xml; charset=utf-8'


def list_row(db, guild):
    leader = g.state_for(db, guild['leader'])
    return dict(guild_id=guild['id'], guild_name=guild['name'], guild_leader=leader['name'],
                guild_leader_level=leader['level'], guild_leader_mil_level=0,
                guild_leader_vippoint=0, guild_leader_vip=0, guild_leader_super_vip=0,
                guild_number=len(g.members(db, guild['id'])), guild_maxnum=10*int(g.config()[1][guild['level']]['nTeamCount']),
                guild_level=guild['level'], guild_coin=guild['coin'], guild_active=0,
                guild_level_limit=guild['min_level'], guild_ladder_limit=guild['min_ladder'],
                guild_notice=guild['recruit'], auto_join=bool(guild['settings'] & 1))


def detail(db, guild):
    all_teams = []
    for t in g.teams(db, guild['id']):
        leader = g.state_for(db, t['leader']) if t['leader'] else {}
        all_teams.append(dict(nTeamId=t['id'], szTeamName=t['name'], szTeamLeader=leader.get('name',''),
                              nTeamLeaderLevel=leader.get('level',0), nTeamPlace=0,
                              nTeamNumMember=db.execute('SELECT COUNT(*) FROM guild_members WHERE team=?',(t['id'],)).fetchone()[0],
                              nTeamLeaderViptime=0, nTeamLeaderSuperViptime=0, nTeamLeaderVippoint=0))
    return dict(nGuildId=guild['id'], szGuildName=guild['name'], szGuildLeader=g.state_for(db,guild['leader'])['name'],
                nGuildNumMember=len(g.members(db,guild['id'])), nGuildLv=guild['level'], allTeams=all_teams)


def team_row(db, t):
    guild = g.guild(db,t['guild']); leader = g.state_for(db,t['leader']) if t['leader'] else {}
    return dict(rank=0,team_id=t['id'],team_name=t['name'],team_level=t['level'],
                team_leader=leader.get('name',''),team_leader_level=leader.get('level',0),
                team_leader_mil_level=0,team_leader_vip=0,team_leader_super_vip=0,team_leader_vippoint=0,
                team_glory=t['glory'],team_coin=t['coin'],team_merit=t['merit'],guild_name=guild['name'],
                team_score=0,team_wins=0,team_loses=0,team_leader_yl=0,team_leader_iyy=0,
                team_leader_ihy=0,team_leader_bl=0,team_leader_iyb=0,team_leader_ihb=0)


def team_members(db, ident):
    t = g.team(db, ident)
    if t is None: return []
    rows = []
    for raw in db.execute('SELECT * FROM guild_members WHERE team=? ORDER BY profile', (ident,)):
        m = g.unpack_row(raw); s = g.state_for(db,m['profile'])
        rows.append(dict(char_uuid=s['char_uuid'],char_name=s['name'],char_level=s['level'],
                         char_oid=m['profile'],team_post=5 if t['leader']==m['profile'] else 0,
                         team_name=t['name'],char_elo=0,team_merit=m['merit'],
                         char_viptime=0,char_superviptime=0,char_vippoints=0,elo_section_id=0))
    return rows


def ranked_list(db, name, qs):
    # These two native rank windows start at page 1; GuildJoinList starts at 0.
    page = max(1,int(qs.get('p',['1'])[0])); size = max(1,min(100,int(qs.get('li',['10'])[0])))
    if name == 'cguildlist.php':
        records = [g.unpack_row(r) for r in db.execute('SELECT * FROM guilds ORDER BY id')]
        records.sort(key=lambda r:(-r['level'],r['id']))
        rows = []
        for rank,record in enumerate(records,1):
            row = list_row(db,record)
            row.update(rank=rank,guild_teamlevel=sum(t['level'] for t in g.teams(db,record['id'])),
                       guild_month_liveness=0,guild_leader_yl=0,guild_leader_iyy=0,guild_leader_ihy=0,
                       guild_leader_bl=0,guild_leader_iyb=0,guild_leader_ihb=0)
            rows.append(row)
    else:
        records = [g.unpack_row(r) for r in db.execute('SELECT * FROM guild_teams ORDER BY id')]
        by_level = qs.get('s',['level'])[0] == 'level'
        if by_level: records.sort(key=lambda r:(-r['level'],r['id']))
        rows = [team_row(db,t) for t in records]
        for rank,row in enumerate(rows,1):
            # Competitive team matches are deferred. Do not invent a place,
            # score or wins for the native s=place request.
            row['rank'] = rank if by_level else 0
    return dict(amount=len(rows),datas=rows[(page-1)*size:page*size])


def http(name, qs):
    if name not in HTTP_ROUTES:
        return None
    try:
        if name == 'goodsshopquickquery.php': return quickshop(qs)
        with storage.connection() as db:
            if name in ('cguildlist.php','cteamserverlist.php'):
                result = ranked_list(db,name,qs)
            elif name == 'cteammember.php':
                result = team_members(db,int(qs.get('tid',['0'])[0]))
            elif name == 'cguildjoinlist.php':
                page = max(0, int(qs.get('p',['0'])[0])); size = max(1,min(100,int(qs.get('li',['10'])[0])))
                guilds = [g.unpack_row(r) for r in db.execute('SELECT * FROM guilds ORDER BY id')]
                if 'char' in qs:
                    profile = g.find_character(db, qs['char'][0]); s = g.state_for(db,profile)
                    guilds = [x for x in guilds if not x['settings']&2 and s['level'] >= x['min_level'] and not x['min_ladder']]
                result = dict(amount=len(guilds),datas=[list_row(db,x) for x in guilds[page*size:(page+1)*size]])
            elif name == 'cguildinfo.php':
                guild = (g.guild(db,int(qs['gid'][0])) if 'gid' in qs else
                         g.unpack_row(db.execute('SELECT * FROM guilds WHERE name=?', (qs.get('gn',[''])[0],)).fetchone()))
                if guild is None: return b'', 'application/json; charset=utf-8'
                result = detail(db,guild)
            elif name == 'cteamplace.php':
                result = dict(rank=0,score=0,wins=0,loses=0)
            else:
                t = g.team(db,int(qs.get('tid',['0'])[0]))
                if t is None: return b'', 'application/json; charset=utf-8'
                result = team_row(db,t)
        return json.dumps(result,ensure_ascii=False).encode('utf8'),'application/json; charset=utf-8'
    except (ValueError, TypeError, KeyError, IndexError):
        if name == 'cteammember.php': return b'[]', 'application/json; charset=utf-8'
        if name in ('cguildlist.php','cteamserverlist.php'):
            return b'{"amount":0,"datas":[]}', 'application/json; charset=utf-8'
        return b'', 'application/json; charset=utf-8'
