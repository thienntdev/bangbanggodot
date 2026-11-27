"""Read-only native character inspection and the implemented rank lists.

Only public character fields are serialized. Battle statistics and unsupported
leaderboards stay empty until their progression rules are implemented.
"""
import json
import struct

import guilds
import military_rank
import ranked_matches
import storage

HTTP_ROUTES = frozenset(('observechar.php', 'crankquery.php', 'ccharrankquery.php',
                         'ctoppowertanklist.php', 'cchallengerankquery.php', 'crankstatus.php'))


def _native_vip(db):
    # Match the native login entitlement; a room's vip_level is not a paid
    # subscription or an expiry date. Never invent an active subscription.
    # Reuse this public snapshot's read transaction. Opening a second reader
    # here can deadlock with a rank writer waiting to commit behind the first.
    for row in db.execute('SELECT frame FROM lobby_frames ORDER BY ordinal'):
        frame = bytes(row[0])
        if struct.unpack_from('<H', frame, 2)[0] == 1016:
            body = frame[8:]
            return dict(char_vip_time=struct.unpack_from('<I', body, 6)[0],
                        char_vippoint=struct.unpack_from('<I', body, 46)[0],
                        char_super_vip_time=struct.unpack_from('<I', body, 68)[0])
    return dict(char_vip_time=0, char_vippoint=0, char_super_vip_time=0)


def _characters(db):
    return [(int(r[0]), json.loads(r[1])) for r in db.execute(
        'SELECT w.profile_id,w.state FROM characters c JOIN worlds w '
        'ON c.profile_id=w.profile_id ORDER BY w.profile_id')]


def _find(records, identity):
    if not identity or len(identity) > 200:
        return None
    return next(((ident, state) for ident, state in records
                 if identity in (str(ident), state['char_uuid'])), None)


def _garage(db, ident, state):
    records = [json.loads(r[0]) for r in db.execute(
        'SELECT data FROM garage WHERE profile_id=? ORDER BY ordinal', (ident,))]
    records = [r for r in records if int(r['tank_id']) not in storage.DEFERRED_TANKS]
    selected = state.get('selected_tank_uuid')
    if not selected:
        selected = next((r['uuid'] for r in records if r['tank_id'] == state['tank_id']), '')
    records.sort(key=lambda r: r['uuid'] != selected)
    return records


def _public(db, ident, state):
    result = dict(char_oid=ident, account_oid=ident, char_uuid=state['char_uuid'],
                  char_name=state['name'], char_level=state['level'],
                  char_avatar=state.get('avatar', 0), char_decorate=state.get('decorate_id', 0),
                  char_elo=0, elo_section_id=0, char_charm=0, char_romantic=0,
                  char_honors=[], char_honor=0, char_yl=0, char_iyy=0, char_ihy=0,
                  char_bl=0, char_iyb=0, char_ihb=0,
                  guild_id=0, guild_level=0, guild_name='',
                  team_id=0, team_level=0, team_name='')
    vip = _native_vip(db)
    result.update({key: int(state.get(key, value)) for key, value in vip.items()})
    # The shop owns these values; its atomic commit can precede a world checkpoint.
    saved = db.execute('SELECT value FROM settings WHERE name=?',
                       (storage.setting_key('cosmetic_shop_profile', ident),)).fetchone()
    if saved:
        appearance = json.loads(saved[0])
        result.update(char_avatar=appearance['avatar'], char_decorate=appearance['decorate'])
    member = guilds.member(db, ident)
    if member:
        guild = guilds.guild(db, member['guild'])
        team = guilds.team(db, member['team'])
        result.update(guild_id=guild['id'], guild_name=guild['name'], guild_level=guild['level'],
                      team_id=team['id'], team_name=team['name'], team_level=team['level'])
    return result


def _public_companion(db, ident):
    """WatchHelperInfo's six public fields, from this same read transaction.

    Do not load another profile context, open another reader, initialize a pet,
    or serialize an inventory item. The equipped UUID is only an internal join.
    """
    rows = {}
    for name in ('booster_profile', 'inventory'):
        saved = db.execute('SELECT value FROM settings WHERE name=?',
                           (storage.setting_key(name, ident),)).fetchone()
        if not saved:
            return None
        try:
            rows[name] = json.loads(saved[0])
        except (ValueError, TypeError):
            return None
        if not isinstance(rows[name], dict):
            return None
    active = rows['booster_profile'].get('active')
    bag = rows['inventory'].get('5', [])
    if not isinstance(active, str) or not active or not isinstance(bag, list):
        return None
    matches = [item for item in bag if isinstance(item, dict) and item.get('uuid') == active]
    if len(matches) != 1 or type(matches[0].get('count')) is not int or matches[0]['count'] != 1:
        return None
    item = matches[0]
    fields = {'booster_tid': 'template_id', 'booster_r': 'rank',
              'booster_rcost': 'rank_cost', 'booster_l': 'level',
              'booster_ul': 'up_level', 'booster_ulcost': 'up_cost'}
    # Malformed legacy metadata hides this badge, not the whole public profile.
    if any(type(item.get(key)) is not int or not 0 <= item[key] <= 0x7fffffff
           for key in fields.values()) or not item['template_id']:
        return None
    return {public: item[internal] for public, internal in fields.items()}


def inspect(db, records, identity):
    found = _find(records, identity)
    if found is None:
        # CharTool checks char_tank before constructing PlayerInfoView.
        return dict(state=0, char_tank=[], msg='Không tìm thấy nhân vật.')
    ident, state = found
    result = _public(db, ident, state)
    tanks = _garage(db, ident, state)
    result.update(state=1, char_tank=[dict(
        tank_tplt_id=r['tank_id'], level=r['level'], external_id=r.get('external_id', 0),
        halo_id=r.get('halo_id', 0), skin_frame_type=r.get('skin_frame_type', 0),
        proficiency_val=r.get('prof_val', 0), winmatchs=0, totalkill=0, totalassist=0,
        fightScore=0) for r in tanks], booster=_public_companion(db, ident))
    result['military_star'] = military_rank.count_stars(tanks)
    result['char_tech'] = {kind: dict(totalmatchs=0, winmatchs=0, winpercent=0,
        escapeprecent=0, killerkingmatchs=0, assistkingmatchs=0, kda_count=0,
        destroyer_count=0) for kind in ('total', 'pvp', 'league', 'ladderpvp')}
    return result


def _ranked(db, records):
    result = []
    for ident, state in records:
        tanks = _garage(db, ident, state)
        if not tanks:
            continue
        stars = military_rank.count_stars(tanks)
        stamp = military_rank.rank_stamp(db, ident)
        # Initialization and upgrades save the timestamp atomically. Missing or
        # externally stale metadata must not give a character an earlier rank.
        when = stamp['at_ns'] if stamp and stamp['stars'] == stars else 2**63 - 1
        result.append((stars, when, ident, state, tanks[0]))
    result.sort(key=lambda row: (-row[0], row[1], row[2]))
    return result


def http(name, qs):
    if name not in HTTP_ROUTES:
        return None
    if name == 'crankstatus.php' or name == 'cchallengerankquery.php' or (
            name in ('crankquery.php', 'ccharrankquery.php') and qs.get('rt', [''])[0] == '4'):
        return _rank_http(name, qs)
    empty = (dict(state=0, char_tank=[], msg='Không tìm thấy nhân vật.') if name == 'observechar.php'
             else [] if name == 'ctoppowertanklist.php'
             else dict(today_rank=0, yestoday_rank=0, total_rank=0) if name == 'ccharrankquery.php'
             else dict(amount=0, datas=[]) if name == 'cchallengerankquery.php'
             else dict(amount=0, rank=[]))
    result = empty
    try:
        # This native template cache opens its own readers on a cold process.
        # Populate it before holding the public character snapshot transaction.
        if name == 'crankquery.php' and qs.get('rt', ['0'])[0] == '11':
            military_rank.build(0)
        with storage.connection() as db:
            db.execute('BEGIN')  # One consistent read of identity, appearance and garage.
            records = _characters(db)
            if name == 'observechar.php':
                result = inspect(db, records, qs.get('charoid', [''])[0])
            elif name in ('crankquery.php', 'ccharrankquery.php') and int(qs.get('rt', ['0'])[0]) == 11:
                ranked = _ranked(db, records)
                if name == 'ccharrankquery.php':
                    found = _find(records, qs.get('char', [''])[0])
                    rank = next((i for i, row in enumerate(ranked, 1)
                                 if found and row[2] == found[0]), 0)
                    result = dict(today_rank=rank, yestoday_rank=0, total_rank=rank)
                elif qs.get('rd', ['0'])[0] == '0':
                    page = max(0, int(qs.get('p', ['0'])[0]))
                    size = max(1, min(100, int(qs.get('limit', ['10'])[0])))
                    rows = []
                    for i, (stars, _, ident, state, tank) in enumerate(ranked, 1):
                        if not page * size <= i - 1 < (page + 1) * size:
                            continue
                        row = _public(db, ident, state)
                        row.update(char_rank=i, char_point=stars, all_point=stars,
                            military_name=military_rank.build(stars)['name'],
                            char_teamname=row['team_name'], char_maintank=tank['tank_id'],
                            char_maintank_l=tank['level'], char_maintank_e=tank.get('external_id', 0),
                            halo_id=tank.get('halo_id', 0))
                        rows.append(row)
                    result = dict(amount=len(ranked), rank=rows)
    except (ValueError, TypeError, IndexError):
        result = empty
    return json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf8'), 'application/json; charset=utf-8'


def _rank_http(name, qs):
    """Public results only. Maintenance owns a short transaction, never combat."""
    result = dict(amount=0, rank=[])
    try:
        with storage.connection(write=True) as db:
            current = ranked_matches.maintain(db)
            records = _characters(db)
            found = _find(records, qs.get('char', [''])[0])
            owner = found[0] if found else None
            requested = qs.get('season', ['current'])[0]
            season = current - 1 if requested == 'previous' else current
            rows = ranked_matches.rank_list(db, season, owner=owner)
            if name == 'crankstatus.php':
                result = ranked_matches.status(db, owner) if owner else dict(error='Không tìm thấy nhân vật.')
            elif name == 'ccharrankquery.php':
                own = next((r for r in rows if not r['is_bot'] and r['char_oid'] == owner), None)
                result = dict(total_rank=own['char_rank'] if own else 0, today_rank=0, yestoday_rank=0)
            elif name == 'cchallengerankquery.php':
                winners = [r for r in rows if r['challenger']]
                result = dict(amount=len(winners), datas=winners)
            else:
                page = max(0, int(qs.get('p', ['0'])[0]))
                size = max(1, min(100, int(qs.get('limit', ['10'])[0])))
                result = dict(amount=len(rows), rank=rows[page*size:(page+1)*size],
                              season_id=season, current_season=current)
    except (ValueError, TypeError, IndexError):
        result = dict(amount=0, rank=[])
    return json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf8'), 'application/json; charset=utf-8'
