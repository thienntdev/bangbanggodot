"""Initial battle snapshot for the existing local map-101 test room.

Wire layouts come from the client's NotifyBattleEnter, NotifySelfData,
NotifyOtherList, TankInfo and PropsInfo classes. This is scene initialization,
not a combat simulator: equipment bonuses, damage and AI are not calculated here.
"""
from __future__ import annotations
from pve_catalog import MAPS as PVE_MAPS

import struct
import time
import math
from combat_data import table_row as _table_row, tank_stats

BOT_OBJECT_ID = 2  # Tank object IDs must have their top six bits clear (type 0).


def ensure_test_ally(state):
    """User-approved stationary teammate; old saves gain it without a reset."""
    return state.setdefault('ally_bot',dict(acct_id=88888889,char_uuid='robot-88888889',
        name='Gundam đồng đội',tank_id=10000019,tank_level=5,tank_ext=0,ready=1,in_room=True))


def _tank_info(obj_id: int, acct_id: int, name: str, level: int, camp: int,
               position: tuple[int, int], hp: int, mp: int = 0, *, max_hp=None, shield=0, max_mp=None, battle_level=1, battle_exp=0, lives=-1) -> bytes:
    raw_name = name.encode("utf-8")
    # All level-6 TankUp rows use enter skill150 -> visual-only buff15001.
    # CTank.initBuff reads this vector; tankLevel alone does not draw the ring.
    # Reserve the top of the buff-ID range for permanent snapshot visuals;
    # runtime temporary buffs allocate upward from the bottom of that range.
    buffs = [struct.pack('<IIBI',15001,(7 << 26)-1-obj_id,1,obj_id)] if level==6 else []
    return (
        struct.pack("<IIhhiiBBH", obj_id, acct_id, *position, hp, hp if max_hp is None else max_hp,
                    0, camp, len(raw_name))
        + raw_name
        + struct.pack('<H',len(buffs)) + b''.join(buffs)
        + struct.pack("<hIBBiii", lives, battle_exp, battle_level, level, mp, mp if max_mp is None else max_mp, shield)
    )


def actor_info(actor, now):
    return _tank_info(actor.id,actor.info['acct_id'],actor.info['name'],
                      actor.info['tank_level'],actor.camp,actor.position_at(now),
                      math.ceil(actor.hp),getattr(actor,'mp',int(actor.stats.get('iMp',0))),
                      max_mp=int(actor.stats.get('iMp',0)),
                      max_hp=math.ceil(actor.max_hp),battle_level=actor.info.get('battle_level',1),battle_exp=actor.info.get('battle_exp',0),
                      shield=math.ceil(sum(s.remaining for s in actor.shields if s.expires_ms>now)),
                      lives=actor.arena.pk['pve']['lives'] if actor.arena.geometry.id in PVE_MAPS else -1)


def _self_snapshot_parts(state: dict, actor=None) -> tuple[bytes, int]:
    # Sample one authoritative instant for both the legacy snapshot and any
    # int32 correction. In particular, buff expiry must not split the pair.
    now = actor.clock() if actor is not None else None
    room = state["room"]
    # Existing default data101.map: start-point (444, 612), rebirth (780, 804).
    # It has one native camp. The local test bot uses the second clear spawn
    # location; do not claim these are the official spawns for a 5v5 PvP map.
    positions = {1: (444, 612), 2: (780, 804)}
    camp = room.get("camp", 1)
    tank_id, level = state["tank_id"], state["tank_level"]
    base = _table_row("TankBaseTemplate_table.xml", nTankId=tank_id)
    stats = tank_stats(tank_id,level,state.get('tank_strength',0))
    hp = int(stats["iHp"])
    mp = int(stats.get("iMp", "0"))
    player = _tank_info(1, state["char_id"], state["name"], level,
                        camp, positions[camp], hp, mp)
    if actor is not None:
        player = actor_info(actor,now)

    # Base skill slots as defined by SKILL_SLOT: common, E, Space, passive, R.
    # PropsInfo count is signed; -1 means unlimited, R starts with 3 charges.
    skills = []
    for field, slot in (("nBullet", 0), ("nSkill1", 1), ("nSkill2", 2),
                        ("nSkill3", 3), ("nSkill4", 10)):
        skill_id = int(stats.get(field) or base.get(field) or "0")
        # Kurumi's passive370101 has no Skill entry (V1 virtual binding).
        # Its actual passive is in R370401; don't send a nonexistent UI slot.
        # PreloadClassifier.analyzeSkill also ignores missing templates.
        if tank_id==10000095 and slot==3 and skill_id==370101:
            continue
        if skill_id:
            skill = _table_row("SkillTemplate_table.xml", nId=skill_id)
            count = int(skill["iStackCount"])
            body = struct.pack("<IBbIIII", skill_id, slot, count, 0, 0, 0, 0)
            if actor is not None and slot in actor.cooldowns:
                body = actor._cooldown(slot)[1][:22]
            skills.append(body)
    if actor is not None:
        from guild_combat import slot as guild_slot
        guild=guild_slot(actor,now)
        if guild is not None:skills.append(guild)
    # NotifySelfData is also sent on respawn. TankModel assigns these fields
    # directly; the separate scoreboard (S1561) does not update the HUD KDA.
    pk = actor.arena.pk if actor is not None else None
    totals = pk['stats'].get(actor.id) if pk else None
    kda = tuple(min(255, totals[i]) for i in (2, 0, 3)) if totals else (0, 0, 0)
    fire_interval = actor.fire_interval(now) if actor is not None else int(stats["iFireInterv"])
    self_data = (
        player
        + struct.pack("<hhH", min(32767, max(-32768, fire_interval)),
                      actor._speed(now) if actor is not None else int(stats["iSpeed"]), len(skills))
        + b"".join(skills)
        + struct.pack("<HBBB", 0, *kda)  # items, kills (including Robo), deaths, assists
    )
    return self_data, fire_interval


def self_snapshot(state: dict, actor=None) -> bytes:
    """Return the unchanged legacy S1550 layout with a bounded int16 interval.

    This bytes-only API cannot carry an out-of-range interval by itself. Wire
    producers must use self_snapshot_packets so native S1560 supplies the exact
    authoritative int32 value immediately after S1550. Gameplay is not capped.
    """
    return _self_snapshot_parts(state, actor)[0]


def self_snapshot_packets(state: dict, actor=None) -> list[tuple[int, bytes]]:
    """Lossless native self snapshot without widening the legacy S1550 field."""
    body, interval = _self_snapshot_parts(state, actor)
    packets = [(1550, body)]
    if not -32768 <= interval <= 32767:
        account = actor.info['acct_id'] if actor is not None else state['char_id']
        packets.append((1560, struct.pack('<IBi', account, 4, interval)))
    return packets


def entry_packets(state: dict, arena=None, viewer=None) -> list[tuple[int, bytes]]:
    """Build the complete snapshot before sending the transition notification."""
    room = state["room"]
    player=viewer or (arena.player if arena is not None else None)
    if room['map_id'] in PVE_MAPS or room['map_id']==40002:
        if arena is None:raise ValueError('PvE entry requires its authoritative arena')
        from pk_rules import static_packets,score_packets
        now=arena.clock();locks=[]
        remaining=arena.pk.get('intro_until',0)-now
        if remaining>0:
            for actor,*ids in arena.pk.get('intro_buffs',[]):
                for template,ident in zip((50353,336302,4083),ids):
                    locks.append((1558,struct.pack('<IIIBII',actor,template,ident,1,actor,remaining)))
        elapsed=(now-arena.pk['begin'])//1000
        if room['map_id']==40002:
            elapsed=1800-max(0,(arena.pk['end']-now)//1000)
        # The HTML5 reducer waits for the ordered S1561 snapshot marker before
        # enabling input. Send the existing native actor-stat layout after all
        # static objects, including on reconnect; PvP camp-score S1710 is not
        # part of a solo PvE entry and must not leak from score_packets.
        ready=[packet for packet in score_packets(arena) if packet[0]==1561]
        return [(1586,struct.pack('<IB',int(time.time())-elapsed,0))]+self_snapshot_packets(state,player)+[(1551,struct.pack('<H',0))]+static_packets(arena)+ready+locks
    if room['map_id'] in (1,4,7,9,10,12,14,17,18,19,20,21,30,40,34,35,36,37,50,70,169,170):
        if arena is None:raise ValueError('PK entry requires its authoritative arena')
        from pk_rules import static_packets,score_packets
        others=[actor_info(a,arena.clock()) for a in arena.actors.values()
                if a is not player and not a.info.get('npc_template')]
        elapsed=max(0,(arena.clock()-arena.pk['begin'])//1000)
        flags=[]
        if room['map_id'] in (7,9,10,37,170):
            from occupy_rules import snapshot
            flags=[snapshot(arena)]
        if room['map_id'] in (35,40):
            from map_portals import snapshot as portal_snapshot
            flags.append(portal_snapshot(arena))
        if room['map_id'] in (30,40) and arena.pk.get('round_phase')=='playing' and arena.clock()<arena.pk['intro_until']:
            from death_mode import round_packet
            flags.append(round_packet(arena))
        locks=[]
        remaining=arena.pk.get('intro_until',0)-arena.clock()
        if remaining>0:
            for actor,*ids in arena.pk.get('intro_buffs',[]):
                for template,ident in zip((50353,336302,4083),ids):
                    locks.append((1558,struct.pack('<IIIBII',actor,template,ident,1,actor,remaining)))
        return [(1586,struct.pack('<IB',int(time.time())-elapsed,0))]+self_snapshot_packets(state,player)+[(1551,struct.pack('<H',len(others))+b''.join(others))]+static_packets(arena)+(score_packets(arena)+flags if room['map_id'] in (30,40) else flags+score_packets(arena))+locks
    if room["map_id"] != 101:
        raise ValueError(f"Battle snapshot only verified for local map 101, got {room['map_id']}")

    self_packets = self_snapshot_packets(state,player)
    camp = room.get("camp", 1)
    positions = {1: (444, 612), 2: (780, 804)}
    others = []
    bot = state["bot"]
    if bot.get("in_room", True):
        bot_camp = 2 if camp == 1 else 1
        bot_stats = _table_row("TankUpTemplate_table.xml", nTankId=bot["tank_id"],
                               nLevel=bot["tank_level"])
        if arena is not None:
            others.append(actor_info(arena.bot,arena.clock()))
        else:
            bot["hp"] = bot["max_hp"] = int(bot_stats["iHp"])
            others.append(_tank_info(BOT_OBJECT_ID, bot["acct_id"], bot["name"],
                                bot["tank_level"], bot_camp, positions[bot_camp],
                                bot["max_hp"], int(bot_stats.get("iMp", "0"))))
    ally = state.get('ally_bot')
    if ally and ally.get('in_room',True):
        if arena is not None:
            others.append(actor_info(arena.actors[3],arena.clock()))
        else:
            stats = _table_row('TankUpTemplate_table.xml',nTankId=ally['tank_id'],nLevel=ally['tank_level'])
            others.append(_tank_info(3,ally['acct_id'],ally['name'],ally['tank_level'],camp,
                                    (660,804) if camp==1 else (540,612),int(stats['iHp'])))
    return [
        # GateManager handles 1586 synchronously, creating the battle view and
        # registering its snapshot listeners before the next packet is decoded.
        (1586, struct.pack("<IB", int(time.time()), 0)),
        *self_packets,
        (1551, struct.pack("<H", len(others)) + b"".join(others)),
    ]
