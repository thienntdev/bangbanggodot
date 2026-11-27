"""Shared local arena: actor state, event order, projectiles and two-way damage.

Map 101 and radius36 remain the documented local test setup. Tank mechanics
live in their action classes; this module does not interpret raw Effect bytecode.
"""
from __future__ import annotations
from pve_catalog import MAPS as PVE_MAPS

import heapq
import math
import random
import struct
import time

from battle_entry import _tank_info, self_snapshot_packets
from battle_map import BattleMap
from combat_data import table_row, tank_stats, active_buff_effect_types
from combat_geometry import actor_contact, circle_contact, point_at, rect_contact
from combat_math import D, Shield, apply_damage, damage_amount, heal, quantize
from combat_protocol import move_event, skill_event, scene, stop_move
from battle_participants import human, private, other_viewers

SUPPORTED_TANKS = {10000094, 10000097, 10000113, 10000056, 10000019, 10000001, 10000003, 10000029, 10000032, 10000033,
                   10000031, 10000002, 10000008, 10000038, 10000039, 10000047, 10000041, 10000043,
                   10000048, 10000051, 10000063, 10000100, 10000045, 10000069, 10000089, 10000090,
                   10000065, 10000103, 10000107, 10000105, 10000112,10000037,10000073,10000085,
                   10000034,10000035,10000050,10000059,10000074,10000079,
                   10000049,10000053,10000058,10000071,10000086,10000104,
                   10000036,10000046,10000066,10000067,10000075,10000077,
                   10000078,10000088,10000096,10000099,10000101,10000102,
                   10000042,10000064,10000081,10000060,10000062,10000082,
                   10000044,10000061,10000070,10000076,10000092,10000093,
                   10000052,10000084,10000087,10000095,10000030,10000040,10000108,
                   10000109,10000110,10000114,10000072,10000083,10000098,10000106,10000111,
                   10000054,10000057,10000080,10000091,10000115,10000055}
DIRECTIONS = ((-1,-1), (0,-1), (1,-1), (1,0), (1,1), (0,1), (-1,1), (-1,0), (0,0))


from functools import lru_cache

@lru_cache(maxsize=1)
def tank_action_classes():
    from laclongquan_actions import LacLongQuanActions
    from magneto_actions import MagnetoActions
    from timegoddess_actions import TimeGoddessActions
    from quanvu_actions import QuanVuActions
    from gundam_actions import GundamActions
    from ironman_actions import IronManActions
    from panda_actions import PandaActions
    from chopper_actions import ChopperActions
    from teddy_actions import TeddyActions
    from pea_actions import PeaActions
    from captain_actions import CaptainActions
    from groot_actions import GrootActions
    from spider_actions import SpiderActions
    from ghost_actions import GhostActions
    from thor_actions import ThorActions
    from pikachu_actions import PikachuActions
    from legolas_actions import LegolasActions
    from giong_actions import GiongActions
    from assassin_actions import AssassinActions
    from sontinh_actions import SonTinhActions
    from thachsanh_actions import ThachSanhActions
    from panther_actions import PantherActions
    from sponge_actions import SpongeActions
    from scorpion_actions import ScorpionActions
    from starlord_actions import StarLordActions
    from natsu_actions import NatsuActions
    from mermaid_actions import MermaidActions
    from ox_actions import OxActions
    from hikari_actions import HikariActions
    from firegod_actions import FireGodActions
    from chudu_actions import ChuDuActions
    from hulu_actions import HuluActions
    from baymax_actions import BaymaxActions
    from athena_actions import AthenaActions
    from hulk_actions import HulkActions
    from timehunter_actions import TimeHunterActions
    from pegasus_actions import PegasusActions
    from phoenix_actions import PhoenixActions
    from diaochan_actions import DiaoChanActions
    from thuytinh_actions import ThuyTinhActions
    from transformer_actions import TransformerActions
    from superman_actions import SupermanActions
    from medusa_actions import MedusaActions
    from joker_actions import JokerActions
    from fox_actions import FoxActions
    from falcon_actions import FalconActions
    from wukong_actions import WukongActions
    from luffy_actions import LuffyActions
    from edwina_actions import EdwinaActions
    from zhaoyun_actions import ZhaoYunActions
    from lubu_actions import LuBuActions
    from zoro_actions import ZoroActions
    from mikasa_actions import MikasaActions
    from gilgamesh_actions import GilgameshActions
    from kirito_actions import KiritoActions
    from mulan_actions import MulanActions
    from sniper_actions import SniperActions
    from saitama_actions import SaitamaActions
    from songoku_actions import SongokuActions
    from ichigo_actions import IchigoActions
    from swordgod_actions import SwordGodActions
    from minion_actions import MinionActions
    from optimus_actions import OptimusActions
    from nezha_actions import NezhaActions
    from naruto_actions import NarutoActions
    from angel_actions import AngelActions
    from deadpool_actions import DeadpoolActions
    from kaneki_actions import KanekiActions
    from hades_actions import HadesActions
    from sasuke_actions import SasukeActions
    from pumpkin_actions import PumpkinActions
    from kurumi_actions import KurumiActions
    from darkknight_actions import DarkKnightActions
    from wolf_actions import WolfActions
    from shadowblade_actions import ShadowbladeActions
    from stonegod_actions import StoneGodActions
    from aquaman_actions import AquamanActions
    from nightwing_actions import NightWingActions
    from apocalypse_actions import ApocalypseActions
    from strange_actions import StrangeActions
    from simayi_actions import SimayiActions
    from elsa_actions import ElsaActions
    from tsubasa_actions import TsubasaActions
    from kakashi_actions import KakashiActions
    from caocao_actions import CaoCaoActions
    from daredevil_actions import DaredevilActions
    from noel_actions import NoelActions
    from dracula_actions import DraculaActions
    from doraemon_actions import DoraemonActions
    from zhuge_actions import ZhugeActions
    from erlang_actions import ErlangActions
    return {10000094:LacLongQuanActions,10000097:MagnetoActions,10000113:TimeGoddessActions,
               10000056: QuanVuActions, 10000019: GundamActions,
               10000001: IronManActions, 10000003: PandaActions,
               10000029: ChopperActions, 10000032: TeddyActions, 10000033: PeaActions,
               10000031: CaptainActions, 10000002: GrootActions, 10000008: SpiderActions,
               10000038: GhostActions, 10000039: ThorActions, 10000047: PikachuActions,
               10000041: LegolasActions, 10000043: GiongActions,
               10000048: AssassinActions, 10000051: SonTinhActions,
               10000063: ThachSanhActions, 10000100: PantherActions,
               10000045: SpongeActions, 10000069: ScorpionActions,
               10000089: StarLordActions, 10000090: NatsuActions,
               10000065: MermaidActions, 10000103: OxActions, 10000107: HikariActions,
               10000105: FireGodActions, 10000112: ChuDuActions,
               10000037:HuluActions,10000073:BaymaxActions,10000085:AthenaActions,
               10000034:HulkActions,10000050:TimeHunterActions,10000035:PegasusActions,
               10000059:PhoenixActions,10000074:DiaoChanActions,10000079:ThuyTinhActions,
               10000049:TransformerActions,10000053:SupermanActions,10000058:MedusaActions,
               10000071:JokerActions,10000086:FoxActions,10000104:FalconActions,
               10000036:WukongActions,10000046:LuffyActions,10000066:EdwinaActions,
               10000067:ZhaoYunActions,10000075:LuBuActions,10000077:ZoroActions,
               10000078:MikasaActions,10000088:GilgameshActions,10000096:KiritoActions,
               10000099:MulanActions,10000101:SniperActions,10000102:SaitamaActions,
               10000042:SongokuActions,10000064:IchigoActions,10000081:SwordGodActions,
               10000060:MinionActions,10000062:OptimusActions,10000082:NezhaActions,
               10000044:NarutoActions,10000061:AngelActions,10000070:DeadpoolActions,
               10000076:KanekiActions,10000092:HadesActions,10000093:SasukeActions,
               10000052:PumpkinActions,10000084:ZhugeActions,10000087:ErlangActions,10000095:KurumiActions,
               10000030:DarkKnightActions,10000040:WolfActions,10000108:ShadowbladeActions,
               10000109:StoneGodActions,10000110:AquamanActions,10000114:NightWingActions,
               10000072:ApocalypseActions,10000083:StrangeActions,
               10000098:SimayiActions,10000106:ElsaActions,10000111:TsubasaActions,
               10000054:NoelActions,10000057:DraculaActions,10000080:DoraemonActions,10000091:CaoCaoActions,10000115:DaredevilActions,10000055:KakashiActions}


class BattleArena:
    def __init__(self, state, clock=None, rng=None, *, bot_attacks=False, serial_start=0):
        self.bot_attacks = bot_attacks
        classes = tank_action_classes()
        self.state = state
        self.human_states = {p['object_id']:p['state'] for p in state.get('multiplayer_players', [])}
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.rng = rng or random.Random()
        self.scene_id = state['battle']['scene_id']
        self.geometry = BattleMap(state['room'].get('map_id', 101))
        self.tank_test = self.geometry.id==7 and state['room'].get('tank_test',False)
        self.bot_attacks = bot_attacks and not self.tank_test
        self.serial, self.event_serial = serial_start, 0
        self.pending = []
        self.active_buffs = {}
        self.objects = {}  # Live ObjInfo payloads for reconnect snapshots.
        self.pk = None
        self.bot_brains = {}
        camp = state['room'].get('camp', 1)
        spawns = {1: (444,612), 2: (780,804)}
        info = dict(acct_id=state['char_id'], name=state['name'],
                    tank_id=state['tank_id'], tank_level=state['tank_level'],
                    tank_strength=state.get('tank_strength',0), human=True,
                    human_profile_id=state['char_id'], tank_ext=state.get('tank_ext',0),
                    in_room=not state.get('multiplayer_left',False))
        if state.get('crystal_build'):
            info['crystals'] = state['crystal_build']
        if state.get('military_build'):
            info['military'] = state['military_build']
        if state.get('guild_build'):
            info['guild'] = state['guild_build']
        if state.get('booster_build'):
            info['booster'] = state['booster_build']
        if self.geometry.id in (1,4,7,9,10,12,14,17,18,19,20,21,30,40,34,35,36,37,50,70,169,170):
            spawns={c:self.geometry.spawn(c) for c in (1,2)}
        if self.geometry.id in PVE_MAPS or self.geometry.id == 40002:
            if state['room'].get('room_type') != (7 if self.geometry.id == 40002 else 4) or camp != 1:
                raise ValueError('Map PvE chỉ nhận phòng PvE đơn, phe 1.')
            spawns={1:self.geometry.spawn(1)}
        self.player = classes[info['tank_id']](self, 1, info, camp, spawns[camp])
        if self.geometry.id == 40002:
            from world_boss_mode import install
            self.actors={1:self.player}
            self.bot=None
            self.bot_attacks=False
            install(self,self.clock())
            return
        if self.geometry.id in PVE_MAPS:
            from pve_rules import install as install_pve
            self.actors={1:self.player}
            self.bot=None
            self.bot_attacks=False  # NPC scripts use the map tick, never the PvP roster.
            install_pve(self,self.clock())
            return
        if self.geometry.id in (1,4,7,9,10,12,14,17,18,19,20,21,30,40,34,35,36,37,50,70,169,170):
            from bot_setup import room_bots
            from pk_rules import initialize
            from robo_actions import RoboActions,MayaChieftain
            self.actors={1:self.player}
            indices={camp:1,3-camp:0}
            for member in state.get('multiplayer_players', []):
                ident, side, member_state = member['object_id'], member['camp'], member['state']
                if ident == 1:continue
                member_info = dict(acct_id=member_state['char_id'], name=member_state['name'],
                    tank_id=member_state['tank_id'], tank_level=member_state['tank_level'],
                    tank_strength=member_state.get('tank_strength',0), tank_ext=member_state.get('tank_ext',0),
                    human=True, human_profile_id=member_state['char_id'], in_room=not member_state.get('multiplayer_left',False), object_id=ident,
                    spawn_index=indices[side])
                for source,target in (('crystal_build','crystals'),('military_build','military'),
                                      ('guild_build','guild'),('booster_build','booster')):
                    if member_state.get(source):member_info[target]=member_state[source]
                actor=classes[member_info['tank_id']](self,ident,member_info,side,self.geometry.spawn(side,indices[side]))
                indices[side]+=1
                self.actors[ident]=actor
            for bot in room_bots(state):
                side=bot.get('camp',camp if bot['side']=='allies' else 3-camp)
                spawn=tuple(bot['test_spawn']) if self.tank_test else self.geometry.spawn(side,indices[side])
                actor=classes[bot['tank_id']](self,bot['object_id'],bot,side,spawn)
                actor.info['spawn_index']=indices[side]
                indices[side]+=1
                self.actors[actor.id]=actor
            self.bot=next(a for a in self.actors.values() if a.camp!=camp)
            for definition in self.geometry.data['robos']:
                ident=self.new_id(5)
                npc_class=MayaChieftain if self.geometry.id==1 else RoboActions
                robo=npc_class(self,ident,dict(definition),definition['camp'],tuple(definition['position']))
                self.actors[ident]=robo
            if self.geometry.id==17:
                from fastfood_map import install as install_mascots
                install_mascots(self)
            initialize(self,self.clock())
            if self.geometry.id in (12,14,50,169):
                from base_mode import install as install_base
                install_base(self)
            if self.geometry.id in (1,4,9,10,12,14,17,21,30,40,34,35,36,37,50,70,169,170):
                self.pk['intro_until']=self.clock()+3000
                # Presentation-only native locks; the arena gate below is the
                # authority, unaffected by tank CC immunity or cleanse skills.
                self.pk['intro_buffs']=[(a.id,self.new_id(6),self.new_id(6),self.new_id(6))
                    for a in self.actors.values() if not a.info.get('npc_template')]
            if self.geometry.id in (7,9,10,37,170):
                from occupy_rules import install as install_flags
                install_flags(self)
            if self.geometry.id==18:
                from totem_objectives import install as install_totems
                install_totems(self)
            if self.geometry.id==70:
                from escort_mode import install as install_escort
                install_escort(self)
            if self.geometry.id in (20,36):
                from cow_objectives import install as install_cows
                install_cows(self)
            from map_objects import install
            install(self)
            if self.geometry.id in (35,40):
                from map_portals import install as install_portals
                install_portals(self)
            if self.geometry.id==21:
                from lightning_map import install as install_lightning
                install_lightning(self)
            if self.geometry.id in (4,12,14,17,21,30,40,34,35,36,50,70,169):
                self.pk['air_drop_due_at']=self.pk['begin']+60000
            if self.geometry.id==1:
                from maya_map import install as install_maya
                install_maya(self)
            if self.geometry.id==170:
                from quicksand_map import install as install_quicksand
                install_quicksand(self)
            if self.geometry.id in (30,40):
                from death_mode import install as install_death
                install_death(self,self.clock())
            ready=self.pk.get('intro_until',self.clock())
            self.queue(ready if self.geometry.id in (1,4,9,10,12,14,17,21,30,40,34,35,36,37,50,70,169,170) else ready+50,self._map_tick)
            for actor in self.actors.values():self.queue(ready,actor.on_spawn)
            if self.bot_attacks:self.queue(ready+200,self._pk_tick)
            return
        bot = state['bot']
        self.bot = classes[bot['tank_id']](self, 2, bot, 3-camp, spawns[3-camp])
        self.actors = {1: self.player, 2: self.bot}
        if state.get('ally_bot'):
            self.actors[3] = classes[10000019](self,3,state['ally_bot'],camp,
                                          (660,804) if camp==1 else (540,612))
        for actor in self.actors.values():
            self.queue(self.clock(),actor.on_spawn)
        if bot_attacks:
            self.queue(self.clock()+1000, self._bot_attack)

    def new_id(self, object_type):
        self.serial += 1
        return (object_type << 26) | self.serial

    def queue(self, due, callback, *args):
        self.event_serial += 1
        heapq.heappush(self.pending, (due, self.event_serial, callback, args))

    def water_rects(self,now):
        actors=list(self.actors.values())
        for actor in list(actors):
            if hasattr(actor,'borrowed_views'):actors.extend(actor.borrowed_views(current=False))
        return tuple((x-36,y-36,x+36,y+36) for actor in actors
                     if (wall:=getattr(actor,'water_wall',None)) and wall['end']>now
                     for _,(x,y) in wall['blocks'])

    def clip_motion(self,start,dest,now):
        dest = self.geometry.clip_tank_motion(start,dest)
        water = self.water_rects(now)
        hit = rect_contact(start,dest,water,36-.001)
        if hit is not None:
            dest = tuple(round(v) for v in point_at(start,dest,max(0,hit-.0001)))
        return self.geometry.clear_tank_landing(self.geometry.clamp_tank_position(start),dest,water)

    def free_position(self,pos,now,extra=(),occupied=()):
        """Nearest legal wall edge for a blink endpoint or a newly erected block."""
        pos = self.geometry.clamp_tank_position(pos)
        rects = self.water_rects(now)+tuple(extra)
        candidates = {pos}
        for l,t,r,b in rects:
            candidates.update(((round(l-36),pos[1]),(round(r+36),pos[1]),
                               (pos[0],round(t-36)),(pos[0],round(b+36))))
        legal = [p for p in candidates if self.geometry.clamp_tank_position(p)==p
                 and self.geometry.in_playable_region(p)
                 and rect_contact(p,p,rects,36-.001) is None
                 and self.geometry.wall_contact(p,p,36-.001) is None
                 and all(math.dist(p,q)>=72 for q in occupied)]
        return min(legal,key=lambda p:(math.dist(pos,p),p)) if legal else None

    def _water_blocked_flight(self,flight,due):
        if flight.get('kind')!='bullet':
            return None
        if flight.get('template')==352501:
            return None  # Mikasa's executor latches to water/static walls itself.
        rects = self.water_rects(due)
        if not rects:
            return None
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        target = self.actors.get(flight.get('target'))
        if target:
            start,dest = flight['pos'],target.position_at(due)
            end = point_at(start,dest,min(1,flight['speed']*(due-previous)/1000/max(1,math.dist(start,dest))))
        else:
            start = point_at(flight['start'],flight['end'],(previous-begin)/max(1,finish-begin))
            end = point_at(flight['start'],flight['end'],min(1,(due-begin)/max(1,finish-begin)))
        hit = rect_contact(start,end,rects,96 if flight.get('template')==386301 else 0)
        # Stop before an endpoint callback can create a returning projectile
        # or detonate a projectile whose destination lies inside the wall.
        return max(previous,min(finish-1,previous+math.floor((due-previous)*hit))) if hit is not None else None

    def _aquaman_absorbs(self,owner,flight,now):
        if not flight or flight.get('kind')!='bullet':return False
        previous=flight['previous'];source=self.actors[owner]
        absorbers=[a for a in self.actors.values() if a.info['tank_id']==10000110 and a.alive and a.camp!=source.camp and a.dash]
        absorbers.extend(v for a in self.actors.values() if a.alive and a.camp!=source.camp and hasattr(a,'borrowed_views')
                         for v in a.borrowed_views() if v._session['tank']==10000110 and v.dash)
        if not absorbers:return False
        target=self.actors.get(flight.get('target'))
        if target:
            start=flight['pos'];dest=target.position_at(now)
            end=point_at(start,dest,min(1,flight['speed']*(now-previous)/1000/max(1,math.dist(start,dest))))
        else:
            start=point_at(flight['start'],flight['end'],(previous-flight['begin'])/max(1,flight['finish']-flight['begin']))
            end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/max(1,flight['finish']-flight['begin'])))
        for actor in absorbers:
            hit=actor_contact(start,end,actor,previous,now,96)
            if hit is None:continue
            wall=self.geometry.wall_contact(start,end) if not flight.get('through_walls') else None
            water=rect_contact(start,end,self.water_rects(now))
            if any(h is not None and h<hit for h in (wall,water)):continue
            earlier=any(t.alive and t.camp!=source.camp and source.projectile_targetable(flight,t,now)
                        and (not source.info.get('map_turret') or not target or t is target)
                        and (h:=actor_contact(start,end,t,previous,now)) is not None and h<hit
                        for t in self.actors.values())
            if not earlier:return True
        return False

    def tick(self, now=None):
        # Shared service already advanced this room once before its ordered
        # input frame. Legacy solo callers retain their original eager tick.
        if getattr(self,'_shared_input_dispatch',False):return []
        now = self.clock() if now is None else now
        from quanvu_hint import sync as sync_hint
        if self.pk and now<self.pk.get('intro_until',0):return []
        if self.pk and self.pk['finished']:return sync_hint(self,now)
        if self.geometry.id in (30,40) and self.pk.get('round_phase')=='result':
            from death_mode import transition
            return transition(self,now)
        deadline=self.pk['end'] if self.pk and not self.tank_test else None
        if deadline is not None:now=min(now,deadline)
        packets = []
        while self.pending and self.pending[0][0] <= now and not (self.pk and self.pk['finished']):
            due, order, callback, args = heapq.heappop(self.pending)
            owner = getattr(callback.__self__,'id',0)
            flight = args[1][0] if args and args[0]=='flight' else None
            self.damage_context = flight.get('attack_key',(owner,order)) if flight else (owner,order)
            self.current_flight = flight
            self.event_now = due
            try:
                if self._aquaman_absorbs(owner,flight,due):
                    packets.append(scene(expired_bullets=(struct.pack('<I',flight['id']),)))
                    continue
                wall_due = self._water_blocked_flight(flight,due) if flight else None
                # Process contacts before the wall using the existing executor,
                # then cancel only this projectile's remaining flight. Other
                # damage/timers and independent pellets retain their schedules.
                packets.extend(callback(wall_due if wall_due is not None else due, *args))
                if wall_due is not None:
                    remaining = [e for e in self.pending if not (e[2].__name__=='_event'
                                 and e[3][0]=='flight' and e[3][1][0] is flight)]
                    if len(remaining)!=len(self.pending):
                        self.pending = remaining
                        heapq.heapify(self.pending)
                        packets.append(scene(expired_bullets=(struct.pack('<I',flight['id']),)))
            finally:
                self.damage_context = None
                self.current_flight = None
                self.event_now = None
            if self.geometry.id in (30,40) and (not self.pending or self.pending[0][0]>due):
                from death_mode import check_round
                result=check_round(self,due)
                if result:return packets+result
        if self.pk and self.pk['finished']:return packets+sync_hint(self,now)
        for actor in list(self.actors.values()):
            box=self.actors.get(getattr(actor,'noel_box',None))
            if box:box.hold(actor,now)
            packets.extend(actor.update(now))
        if self.geometry.id in (30,40):
            from death_mode import check_round
            return packets+check_round(self,now)+sync_hint(self,now)
        if deadline is not None and now>=deadline:
            from pk_rules import finish
            packets.extend(finish(self,deadline))
        return packets+sync_hint(self,now)

    def input_open(self, now, actor=None):
        """Input may outlive a tick that settled the match or replaced actors.

        Call this again after advancing events, not only before dispatch.
        Result locks sent to the client are presentation, not server CC buffs.
        """
        if actor is not None and self.actors.get(actor.id) is not actor:
            return False
        if self.pk and (self.pk['finished'] or now<self.pk.get('intro_until',0)):
            return False
        return self.geometry.id not in (30,40) or self.pk.get('round_phase')=='playing'

    def handle(self, message, payload):
        if not self.input_open(self.clock()):return []
        from quanvu_hint import sync
        packets=self.player.handle(message, payload)
        if self.geometry.id in (30,40):
            from death_mode import check_round
            packets+=check_round(self,self.clock())
        return packets+sync(self,self.clock())

    def handle_for(self, object_id, message, payload):
        """Authenticated shared-room input; object ownership is resolved upstream."""
        actor=self.actors.get(object_id)
        if actor is None or not human(actor) or not self.input_open(self.clock(),actor):return []
        packets=actor.handle(message,payload)
        if self.geometry.id in (30,40):
            from death_mode import check_round
            packets+=check_round(self,self.clock())
        from quanvu_hint import sync
        return packets+sync(self,self.clock())

    def _pk_tick(self,now):
        if self.tank_test:return []
        from bot_ai import tick
        packets=tick(self,now)
        if not self.pk['finished']:self.queue(now+50,self._pk_tick)
        return packets

    def _map_tick(self,now):
        from map_objects import tick
        packets=[(1559,struct.pack('<II',actor,ident))
                 for actor,*ids in self.pk.pop('intro_buffs',[]) for ident in ids]
        packets+=tick(self,now)
        if self.geometry.id == 40002 and not self.pk['finished']:
            from world_boss_mode import tick as world_boss_tick
            packets+=world_boss_tick(self,now)
        if self.geometry.id in PVE_MAPS and not self.pk['finished']:
            from pve_rules import tick as pve_tick
            packets+=pve_tick(self,now)
        if self.geometry.id in (4,12,14,17,21,30,40,34,35,36,50,70,169) and not self.pk['finished']:
            from quicksand_map import apply_bonuses
            from map_objects import air_drop_tick
            for actor in self.actors.values():packets+=apply_bonuses(actor,now)
            packets+=air_drop_tick(self,now)
        if self.geometry.id in (12,14,50,169) and not self.pk['finished']:
            from base_mode import tick as base_tick
            packets+=base_tick(self,now)
        if self.geometry.id in (30,40) and not self.pk['finished']:
            from death_mode import hazard_tick
            packets+=hazard_tick(self,now)
        if self.geometry.id in (35,40) and not self.pk['finished']:
            from map_portals import tick as portal_tick
            packets+=portal_tick(self,now)
        if self.geometry.id==21 and not self.pk['finished']:
            from lightning_map import tick as lightning_tick
            packets+=lightning_tick(self,now)
        if self.geometry.id==1 and not self.pk['finished']:
            from maya_map import tick as maya_tick
            packets+=maya_tick(self,now)
        if self.geometry.id==170 and not self.pk['finished']:
            from quicksand_map import tick as quicksand_tick
            packets+=quicksand_tick(self,now)
        if self.geometry.id in (7,9,10,37,170) and not self.pk['finished']:
            from occupy_rules import tick as flag_tick
            packets+=flag_tick(self,now)
        if self.geometry.id==70 and not self.pk['finished']:
            from escort_mode import tick as escort_tick
            packets+=escort_tick(self,now)
        if self.geometry.id in (20,36) and not self.pk['finished']:
            from cow_objectives import tick as cow_tick
            packets+=cow_tick(self,now)
        if not self.pk['finished']:self.queue(now+50,self._map_tick)
        return packets

    def _bot_attack(self, now):
        # Stationary test opponent. Uses the same normal attack as a player.
        bot, target = self.bot, self.player
        packets = []
        if bot.alive and target.alive and not target.is_untargetable() and not bot.blocked('attack', now):
            start, dest = bot.position_at(now), target.position_at(now)
            if (math.dist(start,dest) <= int(bot.stats['nFireRange'])
                    and self.geometry.wall_contact(start,dest) is None):
                packets = bot.cast(0, start, dest, target.id, now)
        self.queue(now+50, self._bot_attack)
        return packets


class TankActions:
    def __init__(self, arena, ident, info, camp, spawn):
        self.arena, self.state, self.clock = arena, getattr(arena,'human_states',{}).get(ident,arena.state), arena.clock
        self.id, self.info, self.camp = ident, info, camp
        self.scene_id = arena.scene_id
        self.stats = tank_stats(info['tank_id'],info['tank_level'],info.get('tank_strength',0))
        from crystal_combat import apply_flat
        from bot_loadouts import eligible
        if eligible(ident, info):
            apply_flat(self.stats, info)
            from military_rank import apply_flat as apply_military, equipped as military_equipped
            if military_equipped(ident, info):
                apply_military(self.stats, info)
            from guild_combat import apply_passives
            apply_passives(self.stats, info)
            if info.get('human',ident == 1) and not info.get('npc_template'):
                from boosters import apply_flat as apply_booster
                apply_booster(self.stats, info, self.state.get('room', {}))
        self.crystal_crits = {}
        self.crystal_heal_at = self.clock() + 5000
        self.position = self.spawn = spawn
        self.motion = None
        self.motion_kind = 0
        self.hp = self.max_hp = D(self.stats['iHp'])
        self.info['hp'] = self.info['max_hp'] = int(self.hp)
        self.generation = 0
        self.forced_until = 0
        self.cooldowns = {0:0, 1:0, 2:0, 10:0}
        self.last_speed = int(self.stats['iSpeed'])
        self.speed_lock = None
        self.buffs = {}
        self.buff_started = {}
        self.buff_stacks = {}
        self.buff_versions = {}
        self.buff_sources = {}
        self.shields = ()
        self.athena_shield = None
        self.stat_loans = {}  # Groot links: signed flat modifiers, never base-stat edits.
        self.last_interval = int(self.stats['iFireInterv'])
        self.last_attack = None

    @property
    def enemy(self):
        if self.arena.pk:
            now=getattr(self.arena,'event_now',None) or self.clock()
            candidates=[a for a in self.arena.actors.values() if a.camp!=self.camp]
            return min(candidates,key=lambda a:(not a.alive,a.is_untargetable(),math.dist(self.position_at(now),a.position_at(now)),a.id))
        # Preserve the original two-tank target; summons/teammates use enemies.
        if self.id in (1,2):
            return self.arena.actors[3-self.id]
        return next(a for a in self.arena.actors.values() if a.camp!=self.camp)

    @property
    def alive(self):
        return self.hp > 0 and self.info.get('in_room',True)

    @property
    def active_buffs(self):
        return self.arena.active_buffs

    def _new_id(self, kind):
        return self.arena.new_id(kind)

    def _skill_event(self, skill, start, dest, target=0, *, ready=0):
        return skill_event(skill,start,dest,target,owner=self.id,ready=ready)

    def _move_event(self, position, speed, kind, owner=None):
        return move_event(position,speed,kind,self.id if owner is None else owner)

    def _queue(self, due, kind, *data):
        if kind=='flight' and data and isinstance(data[0],dict):
            flight=data[0]
            if flight.get('kind')=='bullet' and 'attacker_ap' not in flight:
                # Custom projectile constructors need the same launch snapshot as shoot().
                flight['attacker_ap']=self.combat_stat('iAttack',flight.get('begin',due))
        self.arena.queue(due, self._event, kind, data)

    def tick(self, now=None):
        return self.arena.tick(now)

    def position_at(self, now):
        if self.motion is None:
            return self.position
        start, dest, begin, end = self.motion
        f = min(1, max(0, (now-begin)/max(1,end-begin)))
        return tuple(round(x) for x in point_at(start,dest,f))

    def _inside(self,pos):
        return self.arena.geometry.inside(pos)

    def _set_motion(self, start, dest, speed, now, kind=0):
        if self.effect_blocked():
            dest = start
        start = self.arena.geometry.clamp_tank_position(start)
        dest = self.arena.clip_motion(start,dest,now)
        duration = max(1, round(math.dist(start,dest)*1000/speed))
        self.position, self.motion = dest, (start,dest,now,now+duration)
        self.motion_kind = kind
        return duration

    def stop_position(self, now, position=None):
        """A hit/CC can end a wall-crossing dash before its safe endpoint."""
        position = self.position_at(now) if position is None else position
        origin = self.motion[0] if self.motion else position
        return self.arena.clip_motion(origin, position, now)

    def move_destination(self,start,dest):
        if self.effect_blocked():return start
        return self.arena.clip_motion(start,dest,self.clock())

    def blink_destination(self,start,dest):
        if self.effect_blocked():return start
        dest = self.arena.geometry.clear_tank_landing(self.arena.geometry.clamp_tank_position(start),self.arena.geometry.clip_tank_motion(start,dest))
        if rect_contact(dest,dest,self.arena.water_rects(self.clock()),36-.001) is None:
            return dest
        return self.arena.free_position(dest,self.clock()) or start

    def has_buff(self, template, now):
        return self.active_buffs.get((self.id,template),(0,0))[1] > now

    def effect_blocked(self):
        return self.in_stasis()

    def in_stasis(self):
        # A passive state check must not consume active counters such as fog.
        return bool(getattr(self,'noel_box',None) or getattr(self,'dora_travel',None)) or self.has_buff(357402, getattr(self.arena,'event_now',None) or self.clock())

    def is_untargetable(self):
        # Allied fog is independent of an actor's own form/stealth state.
        # Do not save/restore it over info['untargetable'] and erase a vanish.
        now = getattr(self.arena,'event_now',None) or self.clock()
        return self.in_stasis() or self.info.get('untargetable',False) or (self.has_buff(358902,now) and 32 not in self.buff_types(now))

    def cc_immune(self, now, *, slow=False):
        return bool(getattr(self,'dora_travel',None)) or self.has_buff(311313,now) or self.has_buff(510711,now) or not slow and 54 in self.buff_types(now)

    def is_area_targetable(self):
        # Keep each existing kit's protection policy unless it explicitly opts
        # into area hits while hidden (Stone God's approved burrow rule).
        return not self.is_untargetable()

    def attr_bonus(self, attributes, now):
        from crystal_combat import bonus
        value = bonus(self, attributes)
        for (owner,template),(_,end) in self.active_buffs.items():
            if self.arena.geometry.id == 40002 and 483 <= template <= 489:
                continue  # World Boss energy is a flat attack bonus plus 5%.
            if 500101 <= template <= 508109 or 510801 <= template <= 510839:
                continue  # Frozen Guild passives are already in base stats.
            if owner!=self.id or end<=now or template in (416412,416413,416415,416416,388112,336106,344207,358923,305110,305111,305112,305314,381203,381204,391103,391104,391105,330122):
                continue  # Borrowed values are in stat_loans, these buffs show stacks.
            row = table_row('BuffTemplate_table.xml',nBuffId=template)
            attribute = 10 if template==358607 else int(row.get('nTypeParam',0))
            if row.get('nEffectType')=='201' and attribute in attributes:
                amount = D(row.get('fEffectValA','0'))+D(row.get('iStackAdd','0'))*(self.buff_stacks.get(template,1)-1)
                if row.get('fTimeEffectValA') and int(row.get('iCoolTime',0))>0:
                    changed = amount+D(row['fTimeEffectValA'])*((now-self.buff_started[template])//int(row['iCoolTime']))
                    amount = max(D(0),changed) if amount>0 else min(D(0),changed)
                value += amount
        return value

    def combat_stat(self, key, now):
        attrs = {'iAttack':(1,4), 'iEgAtk':(1,5), 'iArmor':(2,6),
                 'iEgArmor':(2,7), 'iCentesis':(3,8), 'iEgCtsis':(3,9)}
        value = D(self.stats[key])*(1+self.attr_bonus(attrs[key],now))
        if self.arena.geometry.id == 40002 and key in ('iAttack','iEgAtk'):
            from world_boss_mode import energy_level, ENERGY_FLAT
            energy = energy_level(self,now)
            if energy:
                value += D(ENERGY_FLAT[energy]) + D(self.stats[key])*D('.05')
        value += sum((link['values'].get(key,D(0)) for link in self.stat_loans.values()
                      if link['end']>now and self.has_buff(link['armor_buff' if key in ('iArmor','iEgArmor') else 'attack_buff'],now)),D(0))
        from guild_combat import weaken_factor
        value*=weaken_factor(self,attrs[key],now)
        return max(D(0),value) if key not in ('iArmor','iEgArmor') else value

    def fire_interval(self, now):
        from guild_combat import weaken_factor
        return max(1,round(int(self.stats['iFireInterv'])/max(D('.01'),(1+self.attr_bonus((10,),now))*weaken_factor(self,(10,),now))))

    def projectile_blocked(self, target, now):
        if target.info['tank_id']==10000115 and target.dodge_projectile(now):return True
        if target.has_buff(332206,now):
            flight=getattr(self.arena,'current_flight',None)
            if flight and flight.get('basic'):return True
        if target.info['tank_id'] in (10000111,10000055) and target.has_buff(386111,now):
            flight=getattr(self.arena,'current_flight',None)
            if flight and target.reflect_projectile(flight,now):return True
        if target.has_buff(351401,now):
            flight=getattr(self.arena,'current_flight',None)
            if flight:
                target.reflect_projectile(flight,now)
            return True
        return any(target.has_buff(t,now) for t in (323401,382121,334212,341401,318402))

    def projectile_targetable(self,flight,target,now):
        return not target.is_untargetable()

    def cleanse(self, now):
        packets = []
        for (owner,template) in list(self.active_buffs):
            if owner==self.id and (table_row('BuffTemplate_table.xml',nBuffId=template).get('iAspect')=='-1'
                    or template in (344207,344211,368305,368405) and self.buff_sources.get(template)!=self.id):
                packets.extend(self.remove_buff(template,now))
        # Naruto's approved hit counter survives CC immunity, independently
        # of the slow's presentation, but is still a cleansable enemy mark.
        for actor in self.arena.actors.values():
            # Summons retain their owner's tank ID for visuals/stats, but do
            # not own that tank's kit (including expired Kakashi wood).
            if actor.info.get('npc_template'):
                continue
            if actor.info['tank_id']==10000044:
                actor.e_hits={k:v for k,v in actor.e_hits.items() if k[1:]!=(self.id,self.generation)}
            if actor.info['tank_id']==10000055:
                for view in actor.borrowed_views(current=False):
                    if view._session['tank']==10000044:
                        view.e_hits={k:v for k,v in view.e_hits.items() if k[1:]!=(self.id,self.generation)}
            if actor.info['tank_id']==10000057:
                if actor.link and self.id in (actor.id,actor.link['target']):packets.extend(actor._end_link(now,True))
                packets.extend(actor.clear_loans(self,now))
        return packets

    def add_object(self, template, position):
        ident = self._new_id(4)
        body = struct.pack('<IIhhiBiIiH',ident,template,*(round(v) for v in position),0,self.camp,0,self.id,0,0)
        self.arena.objects[ident] = body.hex()
        return ident,(1556,struct.pack('<I',self.scene_id)+body)

    def remove_object(self, ident, *, destroyed=False):
        if self.arena.objects.pop(ident,None) is None:
            return []
        vector = {'removed' if destroyed else 'expired_bullets':(struct.pack('<I',ident),)}
        return [scene(**vector)]

    @staticmethod
    def defense_buff(template):
        row = table_row('BuffTemplate_table.xml',nBuffId=template)
        if template in (350302,367406,368302,314101,383323,381307):
            return True
        return (row.get('nEffectType')=='201' and int(row.get('nTypeParam',0)) in (2,6,7)
                and D(row.get('fEffectValA','0'))>0) or template in (331224,363309,304302,304312,307303,323122,321302,322214,322305,338105,338306,364303,365403,380147,380401,311312,347104,347303,339204,339113,318202,336401,336503,344110,344113,335315,8190103,8190421,8190422,356112,*range(328231,328236),*range(316311,316315),*range(316321,316325),*range(316331,316335))

    def strip_defenses(self, now):
        packets = []
        for (owner,template) in list(self.active_buffs):
            if owner==self.id and self.defense_buff(template):
                packets.extend(self.remove_buff(template,now))
        return packets

    def buff_types(self, now):
        active = [t for (owner,t),(_,end) in self.active_buffs.items()
                  if owner==self.id and end>now]
        return active_buff_effect_types(active)

    def _speed(self, now):
        if self.in_stasis() or (getattr(self,'dracula_ritual',None) or getattr(self,'caocao_hostage',None)) or 36 in self.buff_types(now):
            # SelfTank movement uses S1560/selfSpeed, not the root buff alone.
            return 0
        from crystal_combat import bonus
        bonuses, slows = [float(bonus(self, (11,)))], []
        flat = 0
        for (owner, template), (_, end) in self.active_buffs.items():
            if owner != self.id or end <= now:
                continue
            if 500101 <= template <= 508109 or 510801 <= template <= 510839:
                continue
            row = table_row('BuffTemplate_table.xml',nBuffId=template)
            if template==30106:
                flat+=72  # Pickup is a flat speed bonus, not +7200%.
                continue
            source=self.arena.actors.get(self.buff_sources.get(template))
            if (template==50347 and source and row.get('nEffectType')=='201'
                    and row.get('nTypeParam')=='11' and row.get('iValType')=='1'):
                from pve_dooku import enabled as local_dooku_enabled
                if local_dooku_enabled(source):
                    # Dooku's native slow is flat -110, not -11000%. Scope
                    # this to the new-run source; legacy and other buffs keep
                    # their established speed aggregation and expiry rules.
                    flat+=float(row.get('fEffectValA',0))
                    continue
            if (template==247 and self.info.get('pve_npc') or template==50311 and source
                    and source.info.get('pve_npc') and getattr(source,'shot_skill',0)==1000065):
                flat-=min(100,int(self.stats['iSpeed']))
                continue  # Source-approved flat slow of shield/nuclear PvE NPCs.
            if template in (391103,391104,391105,330122):continue  # V1 uses the explicit linear missing-HP bonus.
            if row.get('nEffectType')=='201' and (row.get('nTypeParam')=='11' or template==381203) and template!=358607:
                value = float(row.get('fEffectValA',0))
                value += float(row.get('iStackAdd',0))*(self.buff_stacks.get(template,1)-1)
                if template==310122:
                    value=-.4
                if template==341212:
                    value=-.3*min(2,self.buff_stacks.get(template,1))
                if template==384223:
                    value=-.5
                if template==362107:
                    value=-.5  # Q41: seven skill hits, constant slow for two seconds.
                if template==350112:
                    value=.05*self.buff_stacks.get(template,1)  # Q35, not the old 10% speed.
                if template not in (362107,384223) and row.get('fTimeEffectValA') and int(row.get('iCoolTime',0))>0:
                    changed = value+float(row['fTimeEffectValA'])*\
                              ((now-self.buff_started[template])//int(row['iCoolTime']))
                    value = max(0,changed) if value>0 else min(0,changed)
                (slows if value < 0 else bonuses).append(value)
        from guild_combat import weaken_factor
        return round(max(0,int(self.stats['iSpeed'])*max(0,1+sum(bonuses)+min(slows,default=0))+flat)*float(weaken_factor(self,(11,),now)))

    def blocked(self, action, now):
        if self.arena.geometry.id == 40002:
            from world_boss_mode import beam_active
            if beam_active(self,now):return True
        if not self.alive or self.in_stasis() or (getattr(self,'dracula_ritual',None) or getattr(self,'caocao_hostage',None)):
            return True
        types = self.buff_types(now)
        forced_basic = action=='attack' and getattr(self.arena,'forced_basic_actor',None)==self.id
        charm = any(self.has_buff(t,now) and table_row('BuffTemplate_table.xml',nBuffId=t)['nEffectType']=='62'
                    and not (forced_basic and t==314304) for t in self.buff_started) if forced_basic else 62 in types
        if 30 in types or charm:  # stun/knockup or server-controlled charm
            return True
        if action=='attack' and self.has_buff(320311,now):
            return True
        return action=='move' and (now < self.forced_until or 36 in types)

    def skill_sealed(self, slot, now):
        if self.arena.geometry.id == 40002:
            from world_boss_mode import beam_active
            if beam_active(self,now):return True
        if self.in_stasis() or (getattr(self,'dracula_ritual',None) or getattr(self,'caocao_hostage',None)):return True
        if self.has_buff(314303,now) and not (slot==0 and getattr(self.arena,'forced_basic_actor',None)==self.id):
            return True
        # SkillTool.getBanSlots: silence excludes common attack; masks E/Space/R.
        mask = {0:1, 1:2, 2:4, 10:8, 4:16}.get(slot,0)
        for (owner,template),(_,end) in self.active_buffs.items():
            if owner!=self.id or end<=now or not mask:
                continue
            row = table_row('BuffTemplate_table.xml',nBuffId=template)
            effect = int(row['nEffectType'])
            if effect==66 or effect==35 and slot!=0:
                bits = int(row.get('fEffectValB',0))
                if bits==0 or bits & mask:
                    return True
        return False

    def _buff(self, template, now, owner=None, *, duration=None, stacks=None, refresh=False):
        target = self if owner is None else self.arena.actors[owner]
        if not target.alive or target.in_stasis():
            return []
        row = table_row('BuffTemplate_table.xml',nBuffId=template)
        if target.reject_buff(row,self,now):
            return []
        effect = int(row['nEffectType'])
        harmful = self.camp!=target.camp
        is_cc = effect in (30,35,36,39,62,66,88) or template in (357402,381203) or (effect==201 and row.get('nTypeParam')=='11' and D(row.get('fEffectValA','0'))<0)
        silence_chu_channel = (effect in (35,66) and (not int(row.get('fEffectValB',0)) or int(row.get('fEffectValB',0)) & 8)
                               and target.info['tank_id']==10000112 and target.channel)
        if harmful and is_cc and not silence_chu_channel and target.cc_immune(now,slow=effect==201):
            return []
        if self.defense_buff(template) and (target.has_buff(416315,now) or target.has_buff(416323,now)):
            return []
        duration = int(row['iPersistTime']) if duration is None else duration
        if harmful and is_cc and duration>0 and target.has_buff(357103,now):
            duration = round(duration*1.25)
        if harmful and is_cc and duration>0 and target.has_buff(323402,now):
            duration = round(duration*.5)
        if harmful and is_cc and duration>0 and target.has_buff(321304,now):
            duration = round(duration*.5)
        if harmful and is_cc and duration>0 and target.has_buff(326316,now):
            duration = round(duration*.25)
        if harmful and is_cc and duration>0 and target.has_buff(365404,now):
            duration = round(duration*.7)
        if harmful and is_cc and duration>0 and target.has_buff(308603,now):
            duration = round(duration*.5)
        if harmful and is_cc and duration>0 and target.has_buff(356111,now):
            duration = round(duration*.5)
        if harmful and is_cc and duration>0 and target.has_buff(318117,now):
            duration = round(duration*.75)
        if harmful and is_cc and duration>0 and target.has_buff(391308,now):
            duration=round(duration*.75)
        if harmful and is_cc and duration>0 and target.has_buff(367407,now):
            duration = round(duration*.5)
        end = now+duration if duration>=0 else 2**63-1
        ident = self._new_id(6)
        key = target.id, template
        packets = []
        if stacks is None:
            stacks = min(6 if template==327113 else int(row.get('iStackCount',1)),target.buff_stacks.get(template,0)+1) if target.has_buff(template,now) else 1
        else:
            stacks = max(1,min(int(row.get('iStackCount',1)),stacks))
        reuse=(refresh and target.has_buff(template,now) and target.buff_sources.get(template)==self.id
               and target.buff_stacks.get(template)==stacks)
        if reuse:
            ident=self.active_buffs[key][0]
        elif key in self.active_buffs:
            packets.append((1559,struct.pack('<II',target.id,self.active_buffs[key][0])))
        target.buff_stacks[template] = stacks
        target.buff_versions[template] = target.buff_versions.get(template,0)+1
        target.buff_started[template] = now
        target.buff_sources[template] = self.id
        self.active_buffs[key] = ident, end
        if duration>=0:
            self._queue(end,'unbuff',key,ident)
        if not reuse:
            packets.append((1558,struct.pack('<IIIBII',target.id,template,ident,stacks,self.id,duration & 0xffffffff)))
        elif human(target):
            # Native S1581 only updates the local buff timer/stack. Remote
            # buffs have no client timer; leave their existing visual intact.
            packets.append(private(target,(1581,struct.pack('<IIB',ident,duration & 0xffffffff,stacks))))
        if effect in (30,36) or template==357402:
            target.position, target.motion = target.stop_position(now), None
            packets.append(scene(moves=(move_event(target.position,0,5,target.id),)))
            if effect == 30 or template==357402:
                packets.extend(target.interrupt(now,stun=True) if effect==30 and target.info['tank_id']==10000115 else target.interrupt(now))
        packets.extend(target.sync_speed(now))
        received_control = effect in (30,36) or (effect in (35,66)
            and (not int(row.get('fEffectValB',0)) or int(row.get('fEffectValB',0)) & 8))
        if harmful and (received_control or (target.info['tank_id'] in (10000106,10000111,10000054,10000057,10000080,10000091,10000115,10000055) and effect in (35,66))):
            packets.extend(target.on_control(self,template,now))
        return packets

    def sync_speed(self, now):
        speed = 0 if self.in_stasis() or (getattr(self,'dracula_ritual',None) or getattr(self,'caocao_hostage',None)) else self._speed(now)
        packets = []
        if speed != self.last_speed:
            self.last_speed = speed
            if speed==0 and self.alive:
                # SelfTank.moveEndHandle chains held walking without canMove().
                # A zero-speed attribute alone can run 24-unit steps to a wall.
                # S1554 itself retries the held key, so lock that retry first.
                if 45 not in self.buff_types(now):
                    packets.extend(self._buff(50353,now))
                    self.speed_lock=self.active_buffs.get((self.id,50353),(None,))[0]
                pos=self.position_at(now)
                if (self.motion and not self.motion_kind and self.forced_until>now
                        and self.motion[3]>now):
                    # A forced kind0 push is not ordinary grid walking. Keep
                    # the existing stop policy, but retain its safe origin.
                    pos=self.stop_position(now)
                packets.append(stop_move(self.scene_id,self.id,pos))
                if self.motion and self.motion_kind and self.motion[3]>now:
                    # Some kits report walking speed zero after starting a dash.
                    # Stop the old tween, then resume just its remaining path.
                    start,dest,begin,end=self.motion
                    velocity=max(1,round(math.dist(start,dest)*1000/max(1,end-begin)))
                    packets.append(scene(moves=(self._move_event(dest,velocity,self.motion_kind),)))
                elif self.motion:
                    self.position,self.motion=pos,None
            packets.append((1560,struct.pack('<IBi',self.info['acct_id'],1,speed)))
        if speed>0 and self.speed_lock and (not self.motion or self.motion[3]<=now):
            ident,self.speed_lock=self.speed_lock,None
            if self.active_buffs.get((self.id,50353),(None,))[0]==ident:
                # Removing BUT_AUTO_MOVE immediately calls onMoveEnd on Flash.
                # Its walking speed must already be positive before unlocking.
                packets.extend(self.remove_buff(50353,now))
        interval = self.fire_interval(now)
        if interval!=self.last_interval:
            self.last_interval = interval
            packets.append((1560,struct.pack('<IBi',self.info['acct_id'],4,interval)))
        return packets

    def _hp_packet(self, owner, hp):
        return scene(hp=(struct.pack('<Ii',owner,math.ceil(hp)),))

    def remove_buff(self, template, now, *, expired=False):
        old = self.active_buffs.pop((self.id,template),None)
        if not expired:
            self.buff_versions[template] = self.buff_versions.get(template,0)+1
        self.buff_started.pop(template,None)
        self.buff_stacks.pop(template,None)
        self.shields = tuple(s for s in self.shields if s.shield_id!=str(template))
        packets = ([(1559,struct.pack('<II',self.id,old[0]))] if old else [])+self.sync_speed(now)
        if template==323301:
            for dependent in (323302,323303):
                packets.extend(self.remove_buff(dependent,now))
        if template==311201:
            for dependent in (311202,311203,311204):
                packets.extend(self.remove_buff(dependent,now))
        if template==359201:
            self.athena_shield = None
        if template==30101:self.map_shield_hits=0
        if template==30102:
            for dependent in (30108,30109):packets.extend(self.remove_buff(dependent,now))
        return packets

    def shield_packet(self, now):
        amount = sum(D(s.remaining) for s in self.shields if s.expires_ms>now)
        return scene(shields=(struct.pack('<Ii',self.id,math.ceil(amount)),))

    def add_shield(self, template, amount, now, *, caster=None, duration=None):
        if not self.alive or self.in_stasis():
            return []
        if self.has_buff(382213,now):
            return []  # Hikari E explicitly blocks received shields and healing.
        if self.has_buff(321114,now):
            amount *= D('.5')  # Pikachu explicitly reduces received shields too.
        if self.has_buff(375309,now):
            amount *= D('.5')  # Panther's original debuff explicitly covers shields.
        if self.has_buff(376421,now):
            amount *= D('.5')  # User: Sniper Space reduces both healing and shields.
        if self.has_buff(356322,now):
            amount *= D('.5')
        if self.has_buff(361112,now):
            amount *= D('.7')
        previous_version = self.buff_versions.get(template)
        packets = (caster or self)._buff(template,now,self.id,duration=duration)
        if self.buff_versions.get(template) == previous_version:
            return packets  # A rejected buff must not create/refresh shield HP.
        end = self.active_buffs[(self.id,template)][1]
        self.shields = tuple(s for s in self.shields if s.shield_id!=str(template))+(Shield(str(template),quantize(amount),expires_ms=end),)
        return packets+[self.shield_packet(now)]

    def restore_hp(self, amount, now):
        if not self.alive or self.in_stasis():
            return []  # Heal/late lifesteal cannot resurrect a dead tank.
        if self.has_buff(510610,now):return []  # Approved Guild wound: 100%, not stale table 50%.
        if self.has_buff(510901,now):amount*=D('1.3')
        # Burn and poison share one 30% wound pool, never one copy per stack.
        poison_wound = D('.3') if any(self.has_buff(t,now) for t in (*range(343111,343121),364102,364105,364106,364107,334111,368102,368311,305100,305101,305102,305301,*range(380121,380126))) else D(0)
        result = heal(amount*max(D(0),1+self.attr_bonus((21,),now)),self.hp,self.max_hp,
                      wound_reductions=(poison_wound,))
        if getattr(self,'ledger',None):return self.defer_heal(result.potential_heal,now)
        return self.commit_hp(result.hp_after,now) if result.effective_heal else []

    def skill_cooldown(self, duration, slot=None):
        from crystal_combat import cooldown as build_cooldown
        return build_cooldown(self,duration,slot)

    def commit_hp(self, hp, now, *, critical=False):
        if self.arena.pk and self.arena.pk['finished']:return []
        # Level/form max HP can have more precision than the 0.001 HP ledger.
        # Rounding a full heal upwards must never exceed that actual ceiling:
        # missing-HP skills (e.g. Quan Vu execute) would then request a negative heal.
        before, self.hp = self.hp, min(self.max_hp, quantize(hp))
        self.info['hp'] = math.ceil(self.hp)
        delta=math.ceil(self.hp)-math.ceil(before)
        credit=getattr(self,'damage_credit',None)
        # S1605 is presentation metadata; it must not calculate damage again.
        fury = int(bool(critical) and delta < 0)
        packets = ([(1605,struct.pack('<HIiBI',1,self.id,delta,fury,credit[0] if credit else self.id))] if delta else [])
        packets.append(self._hp_packet(self.id,self.hp))
        if self.arena.pk:
            from pk_rules import record_hp
            record_hp(self.arena,self,before,now)
        if before > 0 and self.hp == 0:
            from battle_levels import reward_death
            packets+=reward_death(self,now)
            self.map_ammo=None
            self.map_shield_hits=0
            self.position, self.motion = self.position_at(now), None
            packets.extend(self.interrupt(now))
            for key,(ident,_) in list(self.active_buffs.items()):
                if key[0] == self.id:
                    packets.append((1559,struct.pack('<II',self.id,ident)))
                    del self.active_buffs[key]
            self.on_death()
            # A death listener can deal secondary damage and create a rescue
            # actor. Notify only the recipients present when this dispatch
            # began; newborns must not receive an earlier death notification.
            for actor in list(self.arena.actors.values()):
                packets.extend(actor.on_target_death(self,now))
            self.shields = ()
            self.athena_shield = None
            self.buff_started.clear()
            self.buff_stacks.clear()
            packets.append(self.shield_packet(now))
            if self.arena.pk:
                from pk_rules import death
                packets.extend(death(self.arena,self,now))
            if self.info.get('pve_npc'):
                self.respawn_at=0
                return packets
            if self.arena.geometry.id in (30,40) and not self.info.get('npc_template'):
                self.respawn_at=0
                if human(self):
                    packets.append(private(self,(1588,b'')))
                return packets
            delay=10000 if self.info.get('bomb_cart') else 30000 if self.info.get('robo') or self.info.get('mascot') or self.info.get('totem') else 5000 if self.arena.pk and not self.info.get('npc_template') else 2000
            if self.arena.geometry.id in (12,14,50,70,169) and not self.info.get('npc_template'):
                from base_mode import respawn_delay
                delay=respawn_delay(self.arena,now)
            if (not self.arena.pk or not self.arena.pk['finished']) and not self.info.get('base_robot'):
                self.respawn_at=now+delay
                self._queue(now+delay,'respawn',self.generation)
                if not self.info.get('npc_template'):
                    packets.append((1553,struct.pack('<Ii',self.info['acct_id'],delay)))
        return packets

    def damage_immune(self, school, now, periodic=False):
        if self.arena.geometry.id == 40002:
            from world_boss_mode import beam_active
            if beam_active(self,now):return True
        return (self.info.get('damage_immune',False)
                               or self.has_buff(511202,now)
                               or now<getattr(self,'pk_safe_until',0)
                               or now<getattr(self,'portal_safe_until',0)
                               or (school=='physical' and self.has_buff(332205,now))
                               or self.has_buff(330132,now)
                               or (school=='true' and self.has_buff(330305,now))
                               or self.has_buff(303136,now)
                               or self.has_buff(386312,now)
                               or self.has_buff(312111,now)
                               or self.has_buff(320101,now)
                               or self.has_buff(326341,now)
                               or self.has_buff(338103,now)
                               or self.has_buff(348202,now)
                               or self.has_buff(353121,now)
                               or self.has_buff(371111,now)
                               or self.has_buff(336108,now) or self.has_buff(336507,now)
                               or self.has_buff(336301,now) or self.has_buff(336311,now)
                               or self.has_buff(344103,now)
                               or self.has_buff(327222,now)
                               or self.has_buff(379202,now) or self.has_buff(379207,now)
                               or (school=='energy' and self.has_buff(333301,now))
                               or (not periodic and self.has_buff(303111,now)))

    def damage(self, raw, now, *, target=None, school='physical', basic=False,
               lifesteal=0, reflected=False, attacker_ap=None, periodic=False,
               ignore_armor=False, inverse_armor=False, hp_swap_loss=0, resolved_damage=None, source_generation=None,
               credit_override=None, allow_friendly=False, critical_handled=False, crystal_vamp=True,
               critical_display=False, ignore_reductions=False):
        if self.arena.pk and self.arena.pk['finished']:return [], False
        target = target or self.enemy
        if not allow_friendly and (target.info.get('map_object') or target.info.get('totem') or target.info.get('bomb_cart')) and target.camp==self.camp:return [],False
        if not target.alive or target.in_stasis():
            return [], False
        armor, pen = ('iArmor','iCentesis') if school=='physical' else ('iEgArmor','iEgCtsis')
        reductions = [D('.5')] if not basic and target.has_buff(331224,now) else []
        if not basic and target.has_buff(510720,now):reductions.append(D('.5'))
        if target.info.get('bomb_cart') and target.escorted(now):reductions.append(D('.9'))
        if not basic and getattr(target,'skill_damage_multiplier',1)!=1:
            reductions.append(1-D(str(target.skill_damage_multiplier)))
        if target.has_buff(330305,now):reductions.append(D('.99'))
        if self.has_buff(381204,now):reductions.append(D('.25'))
        if target.has_buff(381307,now):reductions.append(D('.25'))
        if not basic and target.has_buff(384101,now):
            reductions.append(D('.6')*(1-target.hp/target.max_hp))
        if target.has_buff(384205,now):reductions.append(D('.25'))
        if basic and target.has_buff(314101,now):
            reductions.append(D('.6')*(1-target.hp/target.max_hp))
        if target.has_buff(383323,now):
            reductions.append(D('.1')*target.buff_stacks.get(383323,1))
        if self.has_buff(383404,now) and self.buff_sources.get(383404)==target.id:
            reductions.append(D('.25'))
        if basic and target.has_buff(358915,now):reductions.append(D('.15'))
        if self.has_buff(358923,now):reductions.append(D('.3'))
        if school=='energy' and target.has_buff(363309,now):
            reductions.append(D('.5'))
        if target.has_buff(304302,now):
            reductions.append(D('.5'))
        if not basic and target.has_buff(304312,now):
            reductions.append(D('.25'))
        if target.has_buff(307303,now):
            reductions.append(D('.25'))  # User chose description/V1 over raw .5.
        if basic and target.has_buff(323122,now):
            reductions.append(D('.25'))
        if target.has_buff(321302,now):
            reductions.append(D('.5'))
        if target.has_buff(322214,now):
            reductions.append(D('.25'))
        if target.has_buff(322305,now):
            reductions.append(D('.5'))  # User: all damage, not only skills.
        if not basic and target.has_buff(325202,now):
            reductions.append(D('.5'))
        if target.has_buff(325605,now):
            reductions.append(D('.5'))
        if target.has_buff(334252,now):
            reductions.append(D('.5'))
        if target.has_buff(310203,now):
            reductions.append(D('.5'))
        if target.has_buff(341313,now):
            reductions.append(D('.3'))
        if not basic and target.has_buff(342403,now):
            reductions.append(D('.5'))
        if not basic and target.has_buff(352504,now):
            reductions.append(D('.5'))
        if any(target.has_buff(t,now) for t in (374126,374207,374315,374412)):
            reductions.append(D('.75'))
        if target.has_buff(377122,now) or target.has_buff(377325,now):
            reductions.append(D('.5'))
        if target.has_buff(339204,now):
            reductions.append(D('.25'))
        if not basic and target.has_buff(339113,now):
            reductions.append(D('.15')*target.buff_stacks.get(339113,1))
        if target.has_buff(335315,now):
            reductions.append(D('.25'))
        if target.has_buff(8190103,now):
            reductions.append(D('.5')*getattr(target,'mp',0)/200)
        if target.has_buff(8190421,now):
            reductions.append(D('.5'))
        elif target.has_buff(8190422,now):
            reductions.append(D('.25'))
        if not basic and target.has_buff(356112,now):
            reductions.append(D('.5'))
        if target.has_buff(318202,now):
            reductions.append(D('.5'))
        if target.has_buff(336401,now) or target.has_buff(336503,now):
            reductions.append(D('.25'))
        if target.has_buff(344110,now):
            reductions.append(D('.5'))
        if target.has_buff(344113,now):
            reductions.append(D('.15')*target.buff_stacks.get(344113,1))
        if self.has_buff(344207,now):
            reductions.append(D('.5'))
        if target.has_buff(367406,now):
            reductions.append(D('.5'))
        if target.has_buff(368302,now):
            reductions.append(D('.25'))
        if self.has_buff(367102,now) and self.buff_sources.get(367102)==target.id:
            reductions.append(D('.3'))
        for t,amount in zip(range(316321,316325),('.1','.2','.4','.6')):
            if target.has_buff(t,now):reductions.append(D(amount))
        if self.has_buff(355406,now) and self.buff_sources.get(355406)==target.id:
            reductions.append(D('.25'))
        if self.has_buff(351113,now) and self.buff_sources.get(351113)==target.id:
            reductions.append(D('.25'))
        for t in range(328231,328236):
            if target.has_buff(t,now):
                reductions.append(D('.15')*min(4,t-328230))
        if self.has_buff(360203,now) and self.buff_sources.get(360203)==target.id:
            reductions.append(D('.3'))
        if self.has_buff(334313,now) and self.buff_sources.get(334313)==target.id:
            reductions.append(D('.5'))
        if not basic and target.has_buff(338105,now):
            reductions.append(D('.5'))
        if target.has_buff(338306,now):
            reductions.append(D('.25'))
        if self.has_buff(321213,now) and self.buff_sources.get(321213)==target.id:
            reductions.append(D('.5'))
        if any(self.has_buff(t,now) and self.buff_sources.get(t)==target.id for t in range(343111,343121)):
            reductions.append(D('.2'))  # Poison weakens damage only toward its owner.
        if self.has_buff(343304,now) and self.buff_sources.get(343304)==target.id:
            reductions.append(D('.25'))
        if target.has_buff(364303,now):
            reductions.append(D('.25'))
        if target.has_buff(365403,now):
            reductions.append(D('.3'))
        if target.has_buff(311312,now):
            reductions.append(D('.25'))
        if target.has_buff(347104,now) or target.has_buff(347303,now):
            reductions.append(D('.5'))
        if self.has_buff(340104,now) and self.buff_sources.get(340104)==target.id:
            reductions.append(D('.25'))
        if not basic and self.has_buff(378302,now):
            reductions.append(D('.5'))
        if self.has_buff(388411,now) and self.buff_sources.get(388411)==target.id:
            reductions.append(D('.25'))
        if school=='physical' and self.has_buff(388112,now):
            reductions.append(D('.05')*self.buff_stacks[388112])
        if basic and target.has_buff(380401,now):
            reductions.append(D('.5'))
        if target.info['tank_id']==10000105 and target.has_buff(380147,now):
            reductions.append(min(D(1),D('.1')*target.burning_count(now)))
        if target.has_buff(387302,now):reductions.append(D('.25'))
        if target.has_buff(387314,now):reductions.append(D('.05')*target.buff_stacks.get(387314,1))
        if not basic and target.has_buff(389305,now):reductions.append(D('.25'))
        if target.has_buff(306341,now) or ignore_reductions:
            reductions = []  # Teddy suppresses reductions, never shields/immunity.
        armor_reduction = sum((D('.2') if t in (306101,306102) else D('.4'))
                              for t in ((306101,306311) if school=='physical' else (306102,306321))
                              if target.has_buff(t,now))
        key = getattr(self.arena,'damage_context',None)
        if reflected or not key or key[0]!=self.id:
            key = (self.id,self._new_id(2))
        from crystal_combat import critical, vamp
        crit = critical(self,key,basic=basic,school=school,handled=critical_handled,
                        reflected=reflected,resolved=resolved_damage is not None)
        amount = damage_amount(raw,school=school,armor=0 if ignore_armor else target.combat_stat(armor,now),
                               armor_constant=getattr(target,'pve_armor_constant',300),
                               critical=crit,can_critical=basic and school!='true',
                               reduction_pct=armor_reduction,
                               penetration_flat=self.combat_stat(pen,now),
                               penetration_pct=max(D(0),self.attr_bonus((34,),now)
                                                   -(D('.15') if school=='physical' and self.has_buff(358913,now) else D(0))
                                                   +(D('.5') if school=='physical' and self.has_buff(377121,now) else D(0))),
                               inverse_armor=inverse_armor,
                               source_condition_multiplier=self.damage_bonus(target)*(1+D('.1')*self.burning_count(now) if self.info['tank_id']==10000105 else 1),
                               incoming_bonus=(D('.3') if target.has_buff(303305,now) else D(0))
                                              +(D('.15') if target.has_buff(510841,now) else D(0))
                                              +(D('.1') if ((target.has_buff(381131,now) and target.has_buff(381132,now))
                                                           or (target.has_buff(381412,now) and target.has_buff(381415,now))) else D(0))
                                              +(D('.25') if target.has_buff(321113,now) else D(0))
                                              +(D('.25') if basic and target.has_buff(379412,now) else D(0))
                                              +(D('.15') if target.has_buff(358505,now) else D(0))
                                              +(D('.5') if basic and target.has_buff(384337,now) else D(0)),
                               reductions=reductions,immune=target.damage_immune(school,now,periodic))
        # Q58: the physical minimum is evaluated once, then only its deficit
        # beyond the direct HP swap enters shields/HP and spell-vamp.
        amount=max(D(0),amount-D(hp_swap_loss))
        if resolved_damage is not None:
            amount=D(0) if target.damage_immune(school,now,periodic) else D(resolved_damage)
        if resolved_damage is None and not basic and target.has_buff(416313,now):
            return target.restore_hp(amount,now),False
        if resolved_damage is None:amount = target.limit_hit(key,amount,now)
        if amount>0 and getattr(target,'ordinary_obstacle',False):amount=target.max_hp/4
        if amount>0:
            self.on_combat(now)
        blocked,ward_packets = target.block_hit(key,amount,now,basic=basic,periodic=periodic,source=self) if resolved_damage is None else (False,[])
        if blocked:
            return ward_packets,False
        if (amount>0 and basic and target.has_buff(30101,now)
                and getattr(target,'map_shield_hits',0)>0 and not self.has_buff(30102,now)):
            target.map_shield_hits-=1
            return (target.remove_buff(30101,now) if not target.map_shield_hits else []),False
        transfer_packets=[]
        if resolved_damage is None and getattr(target,'hostage',None):
            amount,transfer_packets=target.redirect_damage(amount,school,now)
        old_shields = target.shields
        hit = apply_damage(amount,target.hp,target.shields,school=school,now_ms=now,
                           hp_floor=min(target.hp,max(D(target.info.get('death_floor',0)),
                                                      D(1) if target.has_buff(359301,now) else D(0))))
        if getattr(target,'ledger',None):
            hit=target.defer_hit(hit,now,self,school,source_generation,transferred=resolved_damage is not None,
                                 credit_override=credit_override)
        protected = target.prevent_lethal_hit(hit,now)
        if protected is not None:
            return transfer_packets+protected,False
        target.shields = hit.shields
        # Athena refunds only absorption by her shield, before a break removes
        # its owner/threshold record. Other shields cannot fill this counter.
        shield_packets = []
        grant = target.athena_shield
        if grant and target.has_buff(359201,now):
            used = (sum((s.remaining for s in old_shields if s.shield_id=='359201' and s.expires_ms>now),D(0))
                    -sum((s.remaining for s in hit.shields if s.shield_id=='359201'),D(0)))
            caster = self.arena.actors.get(grant['owner'])
            if used>0 and caster and caster.alive and caster.generation==grant['generation']:
                grant['absorbed'] += used
                count = int(grant['absorbed']//grant['step'])
                grant['absorbed'] -= count*grant['step']
                if count:
                    shield_packets.extend(caster._resource(15*count))
        credit=credit_override or (self.id,self.generation if source_generation is None else source_generation)
        hold=getattr(target,'caocao_hostage',None)
        if hold and hold['end']>now:credit=(hold['owner'],hold['generation'])
        target.damage_credit=credit if hit.hp_loss>0 else None
        # Reuse the existing roll or a kit's already-applied critical.
        # critical_handled only suppresses a second roll; it is NOT a hit result.
        display_critical = bool(crit or critical_display) and school!='true' and not reflected and resolved_damage is None
        try:packets=transfer_packets+target.commit_hp(hit.hp_after,now,critical=display_critical)
        finally:target.damage_credit=None
        if hit.hp_loss>0 and target.has_buff(358902,now):
            packets.extend(target.remove_buff(358902,now))
        if (hit.potential_damage>0 and target.has_buff(389202,now)
                and now-target.buff_started.get(389202,now)>=1000):
            packets.extend(target.remove_buff(389202,now)+target.remove_buff(389203,now))
        packets.extend(shield_packets)
        if old_shields!=target.shields:
            packets.append(target.shield_packet(now))
        for ident in hit.broken_shield_ids:
            packets.extend(target.remove_buff(int(ident),now))
            packets.extend(target.on_shield_break(int(ident),now))
        lifesteal = D(lifesteal) + vamp(self,target,basic=basic,reflected=reflected,
                                      resolved=resolved_damage is not None,allowed=crystal_vamp)
        if lifesteal:
            packets.extend(self.restore_hp(hit.hp_loss*D(lifesteal),now))
        if resolved_damage is not None:return packets,hit.hp_loss>0
        packets.extend(target.on_damage(self,hit,now,school,reflected,
                                       self.combat_stat('iAttack',now) if attacker_ap is None else attacker_ap))
        if basic and hit.hp_loss>0 and not (reflected and target.info['tank_id']==10000040):
            packets.extend(target.on_basic_damage(self,hit,now))
        if not basic and hit.potential_damage>0:
            packets.extend(target.on_skill_damage(self,hit,now))
        for actor in self.arena.actors.values():
            if actor.info['tank_id']==10000073:
                packets.extend(actor._emergency(now))
        return packets, hit.hp_loss > 0

    def on_shield_break(self, template, now):
        return []

    def prevent_lethal_hit(self, hit, now):
        return None

    def on_damage(self, source, hit, now, school, reflected, attacker_ap):
        return []

    def on_basic_damage(self, source, hit, now):
        return []

    def on_skill_damage(self, source, hit, now):
        return []

    def on_control(self, source, template, now):
        return []

    def reject_buff(self, row, source, now):
        return False

    def block_hit(self, key, amount, now, *, basic=False, periodic=False, source=None):
        return False,[]

    def limit_hit(self, key, amount, now):
        return amount

    def on_combat(self, now):
        pass

    def on_target_death(self, target, now):
        return []

    def damage_bonus(self, target):
        return D(1)

    def _respawn(self, now, generation):
        if generation != self.generation or self.alive or not self.info.get('in_room',True):
            return []
        self.generation += 1
        self.respawn_at=0
        if self.arena.pk:
            self.pk_safe_until=now+2000
            self.mp=int(self.stats.get('iMp',0))
            if self.arena.tank_test and self.info.get('test_spawn'):
                self.spawn=tuple(self.info['test_spawn'])
            else:
                self.spawn=self.arena.geometry.spawn(self.camp,self.info.get('spawn_index',0),respawn=True)
                from pve_catalog import CHAPTER2, CHAPTER3, CHAPTER4
                if self.id==1 and self.arena.geometry.id in CHAPTER2+CHAPTER3+CHAPTER4:
                    from pve_chapter2 import respawn_position
                    self.spawn=respawn_position(self.arena)
        self.hp = self.max_hp
        self.info['hp'] = int(self.hp)
        self.position, self.motion, self.forced_until = self.spawn, None, 0
        self.last_speed = int(self.stats['iSpeed'])
        map_bonuses=[]
        if self.arena.geometry.id in (1,4,12,14,17,21,30,40,34,35,36,50,70,169,170):
            from quicksand_map import apply_bonuses
            map_bonuses=apply_bonuses(self,now)
        if human(self):
            packets = [private(self,p) for p in self_snapshot_packets(self.state,self)]
            packets.extend(self._cooldown(slot) for slot in self.cooldowns)
            if self.arena.state.get('multiplayer_players'):
                from battle_entry import actor_info
                packets.append(other_viewers(self,(1552,actor_info(self,now))))
            return packets+map_bonuses+self.on_spawn(now)
        return [(1552,_tank_info(self.id,self.info['acct_id'],self.info['name'],
                                self.info['tank_level'],self.camp,self.spawn,
                                int(self.hp),int(self.stats.get('iMp',0)),
                                battle_level=self.info.get('battle_level',1),battle_exp=self.info.get('battle_exp',0)))]+map_bonuses+self.on_spawn(now)

    def on_spawn(self, now):
        return []

    def shoot(self, template, start, dest, now, raw, *, school, basic=False,
              target=None, speed_multiplier=1, proc=False, power=None, lifesteal=0, reflected=False,
              hit_ids=(), range_multiplier=1, through_walls=False, shared_hits=None, context=None, attack_key=None,
              fixed_destination=False, critical_display=False):
        row = table_row('SkillTemplate_table.xml',nId=template)
        duration = int(row['iLifeTime'])
        launch_speed_factor = max(.01,float(1+self.attr_bonus((23 if basic else 37,),now)))
        speed_multiplier *= launch_speed_factor
        speed = max(1,round(int(row['iFlyRange'])*1000/duration*speed_multiplier))
        if fixed_destination:
            speed = max(1,round(math.dist(start,dest)*1000/duration*launch_speed_factor))
            duration = max(1,round(duration/launch_speed_factor))
        elif target is not None:
            duration = max(1,round(duration/launch_speed_factor))
        elif target is None:
            distance = float(D(row['iFlyRange'])*D(range_multiplier))
            aim_length = math.dist(start,dest)
            if not aim_length:
                # Displacement during windup can put the caster exactly on
                # the locked aim point. There is no direction to normalize;
                # do not launch an arbitrary shot or refund the accepted cast.
                return []
            dest = point_at(start,dest,distance/aim_length)
            duration = max(1,round(distance*1000/speed))
        dest = tuple(round(x) for x in dest)
        ident = self._new_id(2)
        packet = scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*dest,speed,template),))
        flight = dict(kind='bullet',id=ident,start=start,end=dest,begin=now,
                      finish=now+duration,previous=now,raw=raw,school=school,basic=basic,
                      template=template,proc=proc,source_generation=self.generation,
                      target=target.id if target else None,
                      target_generation=target.generation if target else None,
                      pos=start,speed=speed,
                      attacker_ap=self.combat_stat('iAttack',now),lifesteal=lifesteal,reflected=reflected,
                      power=self.combat_stat('iEgAtk',now) if power is None else power,
                      hits=set(hit_ids) if shared_hits is None else shared_hits,
                      through_walls=through_walls)
        if critical_display:
            flight['critical_display'] = True  # Persist the cosmetic tag with this projectile.
        # Simultaneous pellets share a firing action; procs/reflections are
        # independent attacks. Keep this identity through save/return flights.
        if attack_key is None:
            if not proc and not reflected:
                if not self.last_attack or self.last_attack['begin']!=now or self.last_attack['template']!=template:
                    self.last_attack = dict(begin=now,template=template,id=ident)
                attack_id = self.last_attack['id']
            else:
                attack_id = ident
            # IDs remain stable when the battle clock is rebased after restart.
            attack_key = (self.id,self.generation,template,attack_id)
        flight['attack_key'] = attack_key
        if context is not None:
            flight['context'] = context  # Shared cast state survives checkpoints.
        self._queue(now+min(20,duration),'flight',flight)
        packets=[packet]
        if range_multiplier==1 and shared_hits is None and not fixed_destination:
            from guild_combat import extra_shots
            packets+=extra_shots(self,flight,now)
        if self.arena.pk and range_multiplier==1 and shared_hits is None and not fixed_destination:
            from map_objects import enhance_shot
            packets+=enhance_shot(self,flight,now)
        return packets

    def _launch(self, kind, ident, start, dest, duration, raw, now):
        self._queue(now+min(20,duration),'flight',dict(kind=kind,id=ident,start=start,
                    end=dest,begin=now,finish=now+duration,previous=now,raw=raw,
                    school='physical',basic=False,source_generation=self.generation))

    def _flight(self, flight, now):
        if flight['kind']=='dash' and (flight['id']!=self.dash_id or not self.alive):
            return []
        previous, begin, finish = flight['previous'],flight['begin'],flight['finish']
        packets = []
        homing = self.arena.actors.get(flight.get('target'))
        if flight['kind']=='dash':
            # A newly created water wall can shorten an ongoing dash. Damage
            # must follow the actor's corrected motion, not its old endpoint.
            start,end = self.position_at(previous),self.position_at(now)
        elif homing:
            if not homing.alive or homing.generation != flight['target_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start, dest = flight['pos'], homing.position_at(now)
            distance = math.dist(start,dest)
            end = point_at(start,dest,min(1,flight['speed']*(now-previous)/1000/max(1,distance)))
            if dest != flight['end']:
                packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(x) for x in (*start,*dest)))))
                flight['end'] = dest
            flight['pos'] = end
        else:
            start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
            end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        candidates = [homing] if homing else [a for a in self.arena.actors.values() if a.camp!=self.camp]
        contacts = [(h,a.id,a) for a in candidates if a.alive
                    if (h:=actor_contact(start,end,a,previous,now)) is not None
                    and self.projectile_targetable(flight,a,now)]
        # A miss has no target callback; don't search/rank every enemy for it.
        hit,_,target = min(contacts,key=lambda item:item[:2]) if contacts else (None,0,None)
        # User-approved temporary rule: Gundam R also stops at walls. Its client
        # path/first-object flags do not prove original server wall behavior.
        # A stationary map gun fires from its own footprint. Exclude only
        # that rectangle for legacy shots; current map guns use through_walls.
        own_rect = (self.map_rect,) if self.info.get('map_turret') else ()
        wall = self.arena.geometry.wall_contact(start,end,exclude=own_rect) if flight['kind']=='bullet' and not flight.get('through_walls') else None
        contact = hit is not None and (wall is None or hit < wall)
        if contact and flight['kind']=='bullet' and self.projectile_blocked(target,now):
            return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        if contact:
            raw = target.max_hp*flight['hp_fraction'] if 'hp_fraction' in flight else flight['raw']
            packets.extend(self.damage(raw,now,target=target,school=flight['school'],basic=flight['basic'],
                                       lifesteal=flight.get('lifesteal',0) if flight['source_generation']==self.generation else 0,
                                       reflected=flight.get('reflected',False),
                                       attacker_ap=flight.get('attacker_ap'),source_generation=flight['source_generation'])[0])
            if flight['kind']=='dash':
                pos = tuple(round(x) for x in point_at(start,end,hit))
                packets = self.on_dash_hit(pos,target,now)+packets
            else:
                packets.extend(self.on_bullet_hit(flight,target,now))
        stopped = contact or wall is not None or now>=finish or (flight['kind']=='dash' and
                  (self.motion is None or now>=self.motion[3]))
        if stopped and flight['kind']=='bullet':
            ident = struct.pack('<I',flight['id'])
            packets.append(scene(blown_bullets=(ident,)) if contact or wall is not None
                           else scene(expired_bullets=(ident,)))
        if not stopped:
            flight['previous'] = now
            self._queue(min(now+20,finish),'flight',flight)
        return packets

    def _event(self, now, kind, data):
        if kind in ('world_boss_beam','world_boss_beam_end'):
            from world_boss_mode import player_event
            return player_event(self,now,kind,data)
        if kind.startswith('guild_'):
            from guild_combat import event
            return event(self,now,kind,data)
        if kind=='map_ammo_shot':
            from map_objects import launch_extra
            return launch_extra(self,data[0],now)
        if kind=='object_expire':
            return self.remove_object(data[0])
        if kind=='flight':
            return self._flight(data[0],now)
        if kind=='damage':
            generation, raw, buff_id, version = data[:4]
            target = self.arena.actors.get(data[4]) if len(data)>4 else self.enemy
            # Include a scheduled final tick at expiry, but never after cleanse,
            # replacement or target respawn.
            valid = target and target.generation==generation and target.buff_versions.get(buff_id)==version
            return self.damage(raw,now,target=target,periodic=True,source_generation=data[5] if len(data)>5 else None)[0] if valid else []
        if kind=='respawn':
            return self._respawn(now,data[0])
        if kind=='unbuff':
            key,ident = data
            if self.active_buffs.get(key,(None,0))[0]==ident and self.active_buffs[key][1]<=now:
                target = self.arena.actors[key[0]]
                shield = any(s.shield_id==str(key[1]) for s in target.shields)
                packets = target.remove_buff(key[1],now,expired=True)
                return packets+([target.shield_packet(now)] if shield else [])
        return []

    def update(self, now):
        self.stat_loans = {key:link for key,link in self.stat_loans.items() if link['end']>now}
        from crystal_combat import regenerate
        from guild_combat import spawn_passives
        return self.sync_speed(now) + regenerate(self,now) + spawn_passives(self,now)

    def interrupt(self, now):
        return []

    def on_death(self):
        pass

    def on_bullet_hit(self, flight, target, now):
        return []

    def handle(self, message, payload):
        now = self.clock()
        packets = self.arena.tick(now)
        if not self.arena.input_open(now,self):
            return packets
        if message==501 and len(payload)>=9:
            x,y,direction,scene_id = struct.unpack_from('<HHBI',payload)
            if scene_id!=self.scene_id or direction>8 or not self._inside((x,y)) or self.blocked('move',now):
                return packets
            dx,dy = DIRECTIONS[direction]
            dest = x+24*dx,y+24*dy
            if self._speed(now)>0:
                start=(x,y)
                water=self.arena.water_rects(now)
                if (not self.arena.geometry.can_walk_to(start)
                        or rect_contact(start,start,water,35.999) is not None):
                    # C501 can predate a water-wall displacement or a skill
                    # interrupted while crossing static terrain. Never restore
                    # its now-invalid origin after the authoritative safe stop.
                    # Native walking uses grid samples, not continuous dash
                    # clearance, so legal off-grid corner poses remain valid.
                    # Keep the authoritative displacement and ask the client to
                    # retry from there, without changing wall/skill collision.
                    current=self.position_at(now)
                    if rect_contact(current,current,water,35.999) is not None:
                        occupied=[a.position_at(now) for a in self.arena.actors.values()
                                  if a is not self and a.alive]
                        current=self.arena.free_position(current,now,occupied=occupied) or current
                    if not self.arena.geometry.can_walk_to(current):
                        occupied=[a.position_at(now) for a in self.arena.actors.values()
                                  if a is not self and a.alive and not a.info.get('map_object')]
                        current=self.arena.geometry.recover_walk_position(current,water,occupied) or current
                    self.position,self.motion=current,None
                    packets.append(stop_move(self.scene_id,self.id,current))
                    return packets
                end=self.arena.geometry.walk_end(start,dest,water)
                if end==dest:
                    duration=max(1,round(math.dist(start,end)*1000/self._speed(now)))
                    self.position,self.motion=end,(start,end,now,now+duration)
                    self.motion_kind=0
                    if self.arena.state.get('multiplayer_players') and human(self):
                        packet=stop_move(self.scene_id,self.id,end) if direction==8 else scene(moves=(
                            struct.pack('<IhhhBB',self.id,*start,self._speed(now),direction,0),))
                        packets.append(other_viewers(self,packet))
                else:
                    # Correct genuinely blocked steps only. Walking uses the
                    # same grid rule as SelfTank, not the stricter dash landing.
                    if not self.arena.geometry.can_walk_to(end):
                        end=self.arena.clip_motion(start,end,now)
                    self.position,self.motion = end,None
                    packets.append(scene(moves=(self._move_event(self.position,0,5),)))
            return packets
        if message==503 and len(payload)>=13:
            scene_id,target,slot,x,y = struct.unpack_from('<IIBhh',payload)
            start = self.position_at(now)
        elif message==510 and len(payload)>=12:
            scene_id,sx,sy,x,y = struct.unpack_from('<Ihhhh',payload)
            if not self._inside((sx,sy)):
                return packets
            start,target,slot = self.arena.geometry.clamp_tank_position((sx,sy)),0,0
            if scene_id==self.scene_id and not self.blocked('attack',now):
                water=self.arena.water_rects(now)
                crossing=self.motion and self.motion_kind and self.motion[3]>now
                if crossing and not self.arena.geometry.in_playable_region(start):
                    # An airborne basic may name a point inside an ordinary
                    # wall, but never the explicit exterior strip. Reject the
                    # stale origin without cancelling the current valid dash
                    # or consuming the enhanced attack/cooldown/resources.
                    return packets
                if (not crossing and (not self.arena.geometry.can_walk_to(start)
                        or rect_contact(start,start,water,35.999) is not None)):
                    current=self.position_at(now)
                    if (self.arena.geometry.can_walk_to(current)
                            and rect_contact(current,current,water,35.999) is None):
                        # A delayed basic can still name a pose predating a
                        # safe stop. Enhanced basics may move the actor, so do
                        # not let that obsolete origin restore a wall overlap.
                        # Retry without spending the attack; native airborne
                        # attacks during an unfinished skill motion are intact.
                        self.position,self.motion=current,None
                        packets.append(stop_move(self.scene_id,self.id,current))
                        return packets
        else:
            return packets
        if scene_id==self.scene_id and (slot==4 or slot in self.cooldowns and not self.skill_sealed(slot,now)):
            self.arena.damage_context = (self.id,self.generation,0,self._new_id(2))
            self.arena.current_slot = slot
            try:
                from guild_combat import cast as guild_cast, break_stealth
                stealth_version=self.buff_versions.get(510501)
                if self.arena.geometry.id == 40002 and slot==1 and self.arena.pk['world_boss']['energy']>=8:
                    from world_boss_mode import cast_energy
                    cast_packets = cast_energy(self,(x,y),now)
                else:
                    cast_packets = guild_cast(self,(x,y),target,now) if slot==4 else self.cast(slot,start,(x,y),target,now)
                if cast_packets:self.pk_safe_until=0
                if cast_packets and self.has_buff(510501,now) and self.buff_versions.get(510501)==stealth_version:
                    packets.extend(break_stealth(self,now))
                if cast_packets and self.has_buff(358902,now):
                    packets.extend(self.remove_buff(358902,now))
                if cast_packets and self.has_buff(30105,now):
                    packets.extend(self.remove_buff(30105,now))
                packets.extend(cast_packets)
            finally:
                self.arena.damage_context = None
                self.arena.current_slot = None
        return packets
