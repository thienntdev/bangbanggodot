"""Versioned data-only checkpoints; no pickle, sockets or executable callbacks.

Shared cast dictionaries retain identity: prepared/channel/aura events deliberately
use `is` to reject cancelled casts. Offline time is removed by rebasing timestamps.
"""
import heapq
import json
import math
import struct
from dataclasses import asdict, replace
from decimal import Decimal

from combat_math import Shield, quantize
from pve_catalog import MAPS as PVE_MAPS
from combat_protocol import scene, move_event
from battle_participants import human, private
from cpp_backend import encode_checkpoint_graph

VERSION = 1
STATIC = {'arena','state','clock','stats','skills','buffs','effects','dash_effect','_borrow_views','_checkpoint_defaults'}
TIMES = {'forced_until','e_second_until','r_next_charge','e_next_charge','combo_until',
         'begin','finish','previous','began','end','passive_ready_at','counter_ready_at','next_tick_at','rage_until','space_next_charge','next_stack_at','phase_end','phase_gap',
         'portal_safe_until','dora_next_tick','used_at','copied_at'}
TIMES.update(('pk_safe_until','notice_at','observed_at','repath_at'))
TIMES.update(('respawn_at','hit_at','kill_at','repair_ready_at'))
TIMES.update(('match_started_at','round_reset_at','collapse_at','collapse_tick_at'))
TIMES.update(('vent_due_at','vent_burst_at','vent_end_at','vent_tick_at'))
TIMES.add('beam_aim_at')
TIMES.add('weather_hold_until')
TIMES.add('repair_check_at')
TIMES.add('crystal_heal_at')
TIMES.add('guild_ready_at')
TIMES.add('turret_next_shot_at')
TIMES.update(('capture_started_at','score_due_at','intro_until','flag_order_until'))
TIMES.update(('avoid_allies_until','avoid_repath_at'))
TIMES.update(('spawn_due_at','wave_due_at'))
TIMES.update(('air_drop_due_at','quest_due_at'))
TIMES.update(('energy_ready_at','electric_ready_at','portal_ready_at'))
TIMES.update(('time_combat_until','e_gap_until'))
TIMES.update(('energy_end_at','wb_cycle_at','wb_cast_until','wb_weak_until','wb_life_end_at'))
TIMES.update(('elite_plan_at','elite_order_until','elite_target_until','elite_retreat_until'))

# Most callback deadlines live in named cast dictionaries and are handled by
# TIMES. These legacy positional arguments also contain an absolute clock;
# keep their schema explicit so IDs, generations and durations are not shifted.
# This accepts existing VERSION 1 checkpoints, including borrowed-E callbacks.
EVENT_DATA_TIMES = {'stone_fall': (2,)}


def encode(value):
    native_graph = encode_checkpoint_graph(value, Decimal, Shield, asdict)
    if native_graph is not NotImplemented:
        return json.dumps(native_graph,separators=(',',':'),ensure_ascii=False)
    nodes,seen = [],{}
    scalars = (type(None),str,int,float,bool)
    scalar_types = frozenset(scalars)
    container_kinds = {dict:'dict',list:'list',tuple:'tuple',set:'set'}
    def item(obj):
        # Recursive calls overwhelmingly visit containers; primitive leaves
        # are handled below. Dispatch those exact built-in types once instead
        # of testing every node against scalars, Decimal, Shield and containers.
        # Retain the original isinstance fallback for supported subclasses.
        kind = container_kinds.get(type(obj))
        if kind is None:
            if isinstance(obj,scalars):
                return obj
            if isinstance(obj,Decimal):
                return {'decimal':str(obj)}
            if isinstance(obj,Shield):
                return {'shield':{k:item(v) for k,v in asdict(obj).items()}}
            if isinstance(obj,(dict,list,tuple,set)):
                kind = type(obj).__name__
            else:
                raise TypeError(f'Unsupported checkpoint value {type(obj).__name__}')
        marker = id(obj)
        ref = seen.get(marker)
        if ref is not None:
            return ref
        index = len(nodes)
        ref = seen[marker] = {'ref':index}
        nodes.append(None)
        # Most leaves are numbers/strings. Preserve graph IDs and order,
        # but avoid a recursive call and repeated isinstance tuple scans
        # for every primitive leaf. Subclasses still take item's fallback.
        # Tuples in this temporary JSON scaffolding emit the same arrays
        # as lists, with smaller allocations; they are not graph objects.
        data = ([(k if type(k) in scalar_types else item(k),
                  v if type(v) in scalar_types else item(v)) for k,v in obj.items()]
                if kind=='dict' else
                [v if type(v) in scalar_types else item(v) for v in obj])
        nodes[index] = (kind,data)
        return ref
    try:
        top = item(value)
        return json.dumps(dict(root=top,nodes=nodes),separators=(',',':'),ensure_ascii=False)
    finally:
        # Break the recursive closure's self-reference. Otherwise each call
        # retains its temporary graph until a later cyclic-GC pause.
        item = None


def decode(text):
    data = json.loads(text)
    built = {}
    def item(obj):
        if not isinstance(obj,dict):
            return obj
        if 'decimal' in obj:
            return Decimal(obj['decimal'])
        if 'shield' in obj:
            return Shield(**{k:item(v) for k,v in obj['shield'].items()})
        index = obj['ref']
        if index in built:
            return built[index]
        kind,values = data['nodes'][index]
        if kind=='dict':
            out = built[index] = {}
            out.update((item(k),item(v)) for k,v in values)
        else:
            factory = {'list':list,'tuple':tuple,'set':set}[kind]
            out = built[index] = factory(item(v) for v in values)
        return out
    return item(data['root'])


def dump_arena(arena, now=None):
    events = []
    for due,order,callback,args in arena.pending:
        owner = 0 if callback.__self__ is arena else callback.__self__.id
        if '_session' in vars(callback.__self__):
            owner = (owner,callback.__self__._session['serial'])
        name = callback.__name__
        if (owner==0 and name not in ('_bot_attack','_pk_tick','_map_tick')) or (owner!=0 and name not in ('_event','on_spawn')):
            raise ValueError(f'Unregistered persistent battle event: {name}')
        events.append((due,order,owner,name,args))
    actors = {}
    for ident,actor in arena.actors.items():
        defaults = getattr(actor,'_checkpoint_defaults',{})
        actors[ident] = {k:v for k,v in vars(actor).items() if k not in STATIC
                        and (k=='info' or k not in defaults or v!=defaults[k])}
    return encode(dict(version=VERSION,at=arena.clock() if now is None else now,
                       serial=arena.serial,event_serial=arena.event_serial,
                       actors=actors,
                       buffs=arena.active_buffs,objects=arena.objects,events=events,
                       pk=arena.pk,bot_brains=arena.bot_brains,bot_attacks=arena.bot_attacks,rng=arena.rng.getstate()))


def restore_arena(state, text, clock=None):
    from battle_runtime import BattleArena
    data = decode(text)
    if data['version']!=VERSION:
        raise ValueError('Unsupported battle checkpoint version; checkpoint kept unchanged')
    arena = BattleArena(state,clock=clock)
    now = arena.clock()
    delta = now-data['at']
    def shift(value):
        return value+delta if value and value!=2**63-1 else value
    seen = set()
    def rebase(obj):
        if isinstance(obj,Shield):
            return replace(obj,expires_ms=shift(obj.expires_ms))
        if isinstance(obj,dict):
            if id(obj) in seen:
                return obj
            seen.add(id(obj))
            for key,value in list(obj.items()):
                if key in TIMES and isinstance(value,int):
                    obj[key] = shift(value)
                elif key in ('cooldowns','buff_started'):
                    obj[key] = {k:shift(v) for k,v in value.items()}
                elif key=='motion' and value:
                    obj[key] = (*value[:2],shift(value[2]),shift(value[3]))
                else:
                    obj[key] = rebase(value)
        elif isinstance(obj,tuple):
            return tuple(rebase(v) for v in obj)
        elif isinstance(obj,list):
            return [rebase(v) for v in obj]
        return obj
    rebase(data['actors'])
    arena.pk=rebase(data.get('pk'))
    arena.bot_brains=rebase(data.get('bot_brains',{}))
    arena.bot_attacks=data.get('bot_attacks',bool(arena.bot_brains))
    for ident,fields in data['actors'].items():
        if ident not in arena.actors and fields['info'].get('world_boss_npc'):
            from world_boss_mode import WorldBossNpc
            arena.actors[ident]=WorldBossNpc(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('pve_npc'):
            from pve_npc import PveNpc
            arena.actors[ident]=PveNpc(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('base_robot'):
            from base_mode import BaseRobot
            arena.actors[ident]=BaseRobot(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==20003:
            from kakashi_actions import KakashiWood
            arena.actors[ident]=KakashiWood(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==329303:
            from noel_actions import NoelBox
            arena.actors[ident]=NoelBox(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==389401:
            from timegoddess_actions import TimeGuardian
            arena.actors[ident] = TimeGuardian(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==20017:
            from hulu_actions import HuluTurret
            # Construction initializes HP metadata; never mutate saved fields.
            arena.actors[ident] = HuluTurret(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==451401:
            from joker_actions import JokerClone
            arena.actors[ident] = JokerClone(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==20006:
            from minion_actions import MinionTurret
            arena.actors[ident] = MinionTurret(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==368402:
            from sasuke_actions import SasukeShadow
            arena.actors[ident] = SasukeShadow(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==20001:
            from pumpkin_actions import PumpkinGhost
            arena.actors[ident] = PumpkinGhost(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==370402:
            from kurumi_actions import KurumiClone
            arena.actors[ident] = KurumiClone(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==357201:
            from strange_actions import StrangeShadow
            arena.actors[ident] = StrangeShadow(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        if ident not in arena.actors and fields['info'].get('npc_template')==373201:
            from simayi_actions import SimaOrb
            arena.actors[ident] = SimaOrb(arena,ident,dict(fields['info']),fields['camp'],fields['spawn'])
        vars(arena.actors[ident]).update(fields)
        # Older checkpoints stored guns as inert MapObjects; preserve their
        # HP/death state while enabling the newly approved shooting behavior.
        actor=arena.actors[ident]
        if getattr(actor,'ordinary_obstacle',False):actor.camp=0
        from battle_levels import refresh_stats
        refresh_stats(actor)
        # Repair only the sub-quantum overflow produced by older full heals.
        # Do not heal injured actors or silently normalize unrelated HP errors.
        if actor.hp>actor.max_hp and quantize(actor.hp)==quantize(actor.max_hp):
            actor.hp=actor.max_hp
            actor.info['hp']=math.ceil(actor.hp)
        if actor.info.get('map_object') and hasattr(actor,'turret_skill'):
            actor.info['map_turret']=True
    if arena.pk:
        state['bots']=[a.info for a in arena.actors.values() if not human(a) and not a.info.get('npc_template')]
    else:
        state['bot'] = arena.bot.info
        if 3 in arena.actors:
            state['ally_bot'] = arena.actors[3].info
    arena.active_buffs = {k:(ident,shift(end)) for k,(ident,end) in data['buffs'].items()}
    arena.objects = data['objects']
    arena.serial,arena.event_serial = data['serial'],data['event_serial']
    arena.rng.setstate(data['rng'])
    arena.pending = []
    for due,order,owner,name,args in data['events']:
        if (owner==0 and name not in ('_bot_attack','_pk_tick','_map_tick')) or (owner!=0 and name not in ('_event','on_spawn')):
            raise ValueError('Unknown checkpoint callback')
        if isinstance(owner,tuple):
            from borrowed_e import executor
            target=executor(arena.actors[owner[0]],owner[1])
        else:
            target = arena if owner==0 else arena.actors[owner]
        args = rebase(args)
        if name=='_event' and args[0] in EVENT_DATA_TIMES:
            kind,values = args
            positions = EVENT_DATA_TIMES[kind]
            args = (kind,tuple(shift(value) if index in positions and isinstance(value,int) else value
                               for index,value in enumerate(values)))
        arena.pending.append((due+delta,order,getattr(target,name),args))
    heapq.heapify(arena.pending)
    # VERSION 1 could save expired/consumed Sima orbs without a cleanup event.
    # Schedule the same reference-aware reclamation, never an immediate delete
    # or another combat death; repeated restores must not duplicate the event.
    if not (arena.pk and (arena.pk['finished'] or arena.pk.get('round_phase')=='result')):
        cleanup_owners={cb.__self__.id for _,_,cb,args in arena.pending
                        if cb.__name__=='_event' and args and args[0]=='respawn'}
        for actor in arena.actors.values():
            if actor.info.get('npc_template')==373201 and not actor.alive and actor.id not in cleanup_owners:
                actor._queue(now+2000,'respawn',actor.generation)
    if arena.pk:
        from map_objects import rebuild_geometry
        rebuild_geometry(arena)
        if not arena.pk['finished'] and arena.pk.get('round_phase')!='result' and not any(cb.__name__=='_map_tick' for _,_,cb,_ in arena.pending):
            arena.queue(now+50,arena._map_tick)
        # An exception inside AI pops its current callback before finally saves
        # the match. Resume the loop once, not the already-applied failed cast.
        if arena.bot_attacks and not arena.pk['finished'] and arena.pk.get('round_phase')!='result' and not any(cb.__name__=='_pk_tick' for _,_,cb,_ in arena.pending):
            arena.queue(max(now,arena.pk.get('intro_until',0))+50,arena._pk_tick)
    return arena


def resume_packets(arena, viewer=None):
    """Recreate ongoing scene objects without executing casts/damage again."""
    now = arena.clock()
    player=viewer or arena.player
    packets = []
    if arena.pk and arena.pk['finished']:
        if arena.geometry.id==40002:
            return [(1707,struct.pack('<IIIII',0,arena.scene_id,arena.player.info['acct_id'],1,0))]
        from pk_rules import settlement
        if arena.geometry.id in PVE_MAPS:
            from pve_progress import reward_packet
            return [reward_packet(arena.pk['winner']==1,arena.state),settlement(arena)]
        return [settlement(arena)]
    if arena.pk:
        from map_objects import item_packet
        packets.extend(item_packet(arena,item) for item in arena.pk.get('drops',{}).values())
    if arena.geometry.id in (30,40) and arena.pk.get('round_phase')=='result':
        remaining=max(0,arena.pk['round_reset_at']-now)
        for owner,ident,template in arena.pk.get('result_locks',[]):
            packets.append((1558,struct.pack('<IIIBII',owner,template,ident,1,owner,remaining)))
    thrown = {}
    for _,_,callback,args in arena.pending:
        if callback.__name__=='_event' and args[0]=='superman_landing':
            cast = args[1][0]
            target = arena.actors.get(cast['target'])
            if (target and target.alive and target.generation==cast['target_generation']
                    and cast.get('motion') and target.motion==cast['motion'] and target.motion[3]>now):
                thrown[target.id] = cast
    # NPCs must exist before buffs, HP, motion or projectiles reference them.
    for actor in arena.actors.values():
        if actor.info.get('npc_template') and not actor.info.get('map_object') and actor.alive:
            packets.append(actor.snapshot(now))
    for actor in arena.actors.values():
        if actor.info.get('npc_template') and not actor.alive:
            continue
        if actor.info.get('pve_npc'):
            # Re-send a balanced offline boss's locked warning after its NPC
            # snapshot. This is presentation only: never restart its damage,
            # cooldown, queue or remaining charge on reconnect.
            from pve_bosses import resume
            packets.extend(resume(actor, now))
            from pve_dooku import resume as dooku_resume
            packets.extend(dooku_resume(actor, now))
        if not actor.alive and not actor.info.get('npc_template') and (arena.geometry.id not in (30,40) or actor.id==player.id):
            due=getattr(actor,'respawn_at',0) or next((d for d,_,cb,args in arena.pending
                if cb.__self__ is actor and args and args[0]=='respawn'),now)
            packets.append(private(actor,(1588,b'')) if arena.geometry.id in (30,40) else (1553,struct.pack('<Ii',actor.info['acct_id'],max(0,due-now))))
        for slot in (() if actor.info.get('robo') or actor.info.get('base_robot') or actor.info.get('map_spider') or actor.info.get('pve_npc') else actor.cooldowns):
            if actor.id==player.id and slot in (1,2) and actor.info['tank_id'] in (10000056,10000001):
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot in (0,2) and actor.info['tank_id']==10000033:
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot in (0,1,2) and actor.info['tank_id']==10000094:
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot==0 and actor.info['tank_id']==10000008:
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot in (0,2) and actor.info['tank_id'] in (10000048,10000051):
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot==0 and actor.info['tank_id'] in (10000063,10000069,10000105):
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot==10 and actor.info['tank_id'] in (10000112,10000073,10000050):
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot in (1,10) and actor.info['tank_id']==10000090:
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot==1 and actor.info['tank_id'] in (10000035,10000059,10000079):
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot==0 and actor.info['tank_id']==10000104:
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and slot==0 and actor.info['tank_id'] in (10000095,10000108):
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and ((slot==0 and actor.info['tank_id'] in (10000036,10000075))
                               or (slot==1 and actor.info['tank_id'] in (10000066,10000075))):
                packets.append(actor._cooldown(slot,True))
            packets.append(actor._cooldown(slot))
            if actor.id==player.id and ((slot==0 and actor.info['tank_id'] in (10000096,10000101))
                               or (slot in (2,10) and actor.info['tank_id']==10000099)
                               or (slot in (0,2,10) and actor.info['tank_id']==10000064)
                               or (slot==2 and actor.info['tank_id']==10000102)):
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and ((slot==0 and actor.info['tank_id']==10000062)
                               or (slot in (0,1,2,10) and actor.info['tank_id']==10000082)):
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and ((slot==0 and actor.info['tank_id']==10000044)
                               or actor.info['tank_id']==10000061
                               or (slot==1 and actor.info['tank_id']==10000070)):
                packets.append(actor._cooldown(slot,True))
            if actor.id==player.id and actor.info['tank_id'] in (10000092,10000093,10000087,10000084,10000109,10000110,10000114,10000083,10000098,10000106,10000054,10000057,10000080,10000091,10000115,10000055):
                packets.append(actor._cooldown(slot,True))
        beam = getattr(actor,'channel',None) if not human(actor) and actor.info['tank_id']==10000001 else None
        if beam:
            # Set the saved bearing before buff 363301 enables slow rotation;
            # then resume turning toward the observed goal after restoring it.
            start=actor.position_at(now)
            angle=beam.get('beam_angle',math.atan2(beam['dest'][1]-start[1],beam['dest'][0]-start[0]))
            packets.append((1603,struct.pack('<Ihh',actor.id,
                round(start[0]+2000*math.cos(angle)),round(start[1]+2000*math.sin(angle)))))
        for (owner,template),(ident,end) in arena.active_buffs.items():
            if owner==actor.id and end>now:
                duration = 0xffffffff if end==2**63-1 else end-now
                packets.append((1558,struct.pack('<IIIBII',owner,template,ident,
                    actor.buff_stacks.get(template,1),actor.buff_sources[template],duration)))
        if beam:
            goal=beam.get('beam_goal',angle)
            packets.append((1603,struct.pack('<Ihh',actor.id,
                round(start[0]+2000*math.cos(goal)),round(start[1]+2000*math.sin(goal)))))
        if not actor.info.get('npc_template'):
            packets.append((1560,struct.pack('<IBi',actor.info['acct_id'],1,actor._speed(now))))
            packets.append((1560,struct.pack('<IBi',actor.info['acct_id'],4,actor.fire_interval(now))))
        if not actor.info.get('npc_template') and actor.info['tank_id'] in (10000033,10000008,10000112,10000073,10000085,10000058,10000104,10000066,10000075,10000078,10000102,10000064,10000081,10000060,10000062,10000044,10000093,10000084,10000108,10000110,10000114,10000111,10000055,10000113):
            packets.append(scene(mp=(struct.pack('<Ii',actor.id,math.ceil(actor.mp)),)))
        if actor.motion and actor.motion[3]>now:
            start = actor.position_at(now)
            dest,end = actor.motion[1],actor.motion[3]
            speed = max(1,round(math.dist(start,dest)*1000/(end-now)))
            if actor.id in thrown:
                packets.append((1578,struct.pack('<IhhhhIB',actor.id,*start,*dest,end-now,0)))
            elif arena.pk and actor.id!=player.id and actor.motion_kind==0:
                # Resume a partial walk with its remaining endpoint. Normal
                # wire movement always travels a full 24-unit cell from start.
                packets.append(scene(moves=(move_event(dest,speed,3,actor.id),)))
            else:
                packets.append(scene(moves=(move_event(dest,speed,actor.motion_kind,actor.id),)))
    for body in arena.objects.values():
        body = bytes.fromhex(body)
        _,template,_,_,_,camp = struct.unpack_from('<IIhhiB',body)
        if template not in (307211,376401,358301) or camp==player.camp:
            packets.append((1556,struct.pack('<I',arena.scene_id)+body))
    for _,_,callback,args in arena.pending:
        if callback.__name__!='_event':
            continue
        if args[0]=='laser':
            actor = callback.__self__
            cast_id,generation,start,dest,_ = args[1]
            if actor.ready==cast_id and actor.alive and actor.generation==generation:
                packets.append(scene(skills=(actor._skill_event(302801,start,dest,ready=1),)))
        if args[0]!='flight':
            continue
        flight = args[1][0]
        if flight['kind']!='bullet' or flight['finish']<=now:
            continue
        owner = callback.__self__.id
        if flight.get('target'):
            position = flight['pos']
        else:
            f = min(1,max(0,(now-flight['begin'])/(flight['finish']-flight['begin'])))
            position = tuple(a+(b-a)*f for a,b in zip(flight['start'],flight['end']))
        packets.append(scene(fires=(struct.pack('<IIhhhhhI',flight['id'],owner,
            *(round(x) for x in (*position,*flight['end'])),flight['speed'],flight['template']),)))
    # Readying effects are presentation only; scheduled server events keep the
    # remaining duration and original cast identity.
    presentations=list(arena.actors.values())
    for actor in list(presentations):
        if hasattr(actor,'borrowed_views'):presentations.extend(actor.borrowed_views())
    for actor in presentations:
        donor=getattr(actor,'_session',{}).get('tank',actor.info['tank_id'])
        channel = getattr(actor,'channel',None)
        if donor==10000040 and actor.dash and actor.motion and actor.motion[3]>now:
            packets.append(scene(fires=(struct.pack('<IIhhhhhI',actor.dash['bullet'],actor.id,
                *(round(x) for x in (*actor.position_at(now),*actor.motion[1])),720,314201),)))
        if actor.id==player.id and donor in (10000077,10000111):
            packets.extend(private(actor,(1590,b'')) for request in actor.reflections)
        if actor.info['tank_id']==10000106 and channel:
            packets.append(scene(skills=(actor._skill_event(381301,actor.position_at(now),channel['pos'],ready=1),)))
        if channel and actor.info['tank_id']==10000067 and actor.id==player.id and channel['aim_pending']:
            packets.append(private(actor,(1590,b'')))
        if channel and actor.info['tank_id']==10000038:
            target = arena.actors[channel['target']]
            packets.append(scene(skills=(actor._skill_event(312301,actor.position_at(now),
                target.position_at(now),target.id),)))
        ready = getattr(actor,'ready',None)
        if isinstance(ready,dict):
            import sys
            slots = sys.modules[getattr(actor,'_donor',type(actor)).__module__].SLOTS
            start = actor.position_at(now)
            dest = ready.get('dest',actor.enemy.position_at(now))
            packets.append(scene(skills=(actor._skill_event((ready.get('skill') or (actor.native_slot(ready['slot'])[0] if hasattr(actor,'native_slot') else slots[ready['slot']])),start,dest,
                ready.get('target') or (actor.enemy.id if ready['slot']==2 and actor.info['tank_id']==10000003 else 0),ready=1),)))
    from quanvu_hint import sync
    if arena.geometry.id==40002:
        from world_boss_mode import resume
        packets+=resume(arena,now)
    if arena.geometry.id in (31202,31403):
        from pve_local_late import resume as local_pve_resume
        packets+=local_pve_resume(arena,now)
    return packets+sync(arena,now,reset=True,viewer=player)
