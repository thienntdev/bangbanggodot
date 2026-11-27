"""Kakashi's own kit. Borrowed E execution is isolated from donor passives."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene, stop_move
from melee_common import aimed, enemies, prepare_displacement
from strange_actions import StrangeShadow
from kakashi_borrowing import BorrowedKits

SLOTS = {0:330100, 1:330201, 2:330301, 10:330401}


class KakashiActions(BorrowedKits, TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.mp = 150
        self.ready = self.dash = self.vanish = self.kamui = None
        self.passive_ready_at = 0
        self.borrowed = None
        self.borrow_sessions = {}
        self.borrow_serial = 0
        self.borrow_buff_owners = {}
        self.borrow_memory = {}

    def _cooldown(self, slot, changed=False):
        borrowed=self.borrowed_slot(slot,self.clock())
        if borrowed is not None:
            return (1579,borrowed) if changed and self.id==1 else (1572,borrowed+struct.pack('<I',self.id))
        skill = 330141 if slot==0 and self.has_buff(330111,self.clock()) else SLOTS[slot]
        end = self.cooldowns[slot]
        if slot==2 and self.kamui:
            skill,end = 330311,self.kamui['begin']+1000
        body = props(skill,slot,-1,end)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self, amount):
        if not self.alive or self.in_stasis(): return []
        self.mp = min(150,max(0,self.mp+amount))
        return [scene(mp=(struct.pack('<Ii',self.id,math.ceil(self.mp)),))]

    def on_spawn(self, now):
        self.mp = 150
        self.ready = self.dash = self.vanish = self.kamui = None
        self.passive_ready_at = 0
        self.borrowed = None
        self._queue(now+1000,'kakashi_regen',self.generation)
        packets = self._resource(0)
        for template in (330101,330102,330103): packets.extend(self._buff(template,now))
        return packets+[self._cooldown(slot,True) for slot in SLOTS]

    def damage_bonus(self, target):
        if getattr(self,'_borrow_damage_multiplier',None) is not None:return self._borrow_damage_multiplier
        now = getattr(self.arena,'event_now',None) or self.clock()
        return 1+D('.1')*self.buff_stacks.get(330122,0) if self.has_buff(330122,now) else D(1)

    def damage(self, raw, now, **kwargs):
        trigger_passive=kwargs.pop('trigger_passive',True)
        previous=getattr(self,'_borrow_pen',None)
        flight=getattr(self.arena,'current_flight',None) or {}
        self._borrow_pen=kwargs.pop('pen_snapshot',flight.get('kakashi_pen',previous))
        try:packets,lost = super().damage(raw,now,**kwargs)
        finally:self._borrow_pen=previous
        # The killing hit can finish the match and clear its pending queue.
        # Do not recreate passive resource/buff work after that boundary.
        if self.arena.pk and self.arena.pk['finished']:
            return packets,lost
        target = kwargs.get('target') or self.enemy
        generation = kwargs.get('source_generation',self.generation)
        if (trigger_passive and lost and not kwargs.get('basic') and not kwargs.get('reflected')
                and not target.info.get('npc_template') and target.camp!=self.camp
                and self.alive and self.generation==generation):
            packets.extend(self._resource(10)+self._buff(330122,now))
        return packets,lost

    def _empower(self, now):
        return self._buff(330111,now)+[self._cooldown(0,True)]

    def _break_stealth(self, now):
        return self.remove_buff(330131,now) if self.has_buff(330131,now) else []

    def _queue(self,due,kind,*data):
        if kind=='flight' and data:
            data[0]['kakashi_pen']=getattr(self,'_cast_pen',D(0))
        return super()._queue(due,kind,*data)

    def is_untargetable(self):
        now = getattr(self.arena,'event_now',None) or self.clock()
        return bool(self.vanish) or (self.has_buff(330131,now) and 32 not in self.buff_types(now)) or super().is_untargetable()

    def is_area_targetable(self):
        return not self.vanish and super().is_area_targetable()

    def cc_immune(self, now, *, slow=False):
        return bool(self.vanish) or super().cc_immune(now,slow=slow)

    def damage_immune(self, school, now, periodic=False):
        return bool(self.vanish) or super().damage_immune(school,now,periodic)

    def blocked(self, action, now):
        return bool(self.ready or self.dash or self.vanish) or super().blocked(action,now)

    def _speed(self, now):
        return 0 if self.ready or self.dash or self.vanish else super()._speed(now)

    def _stop_packets(self, packets, position, movement=()):
        # Install ready/disappear/auto-move before S1554's held-key retry.
        # _buff may already have emitted speed=0: defer attrs until after stop.
        attrs = [p for p in packets if p[0]==1560]
        stop=stop_move(self.scene_id,self.id,position)
        return [p for p in packets if p[0]!=1560 and p!=stop and p not in movement]+[stop]+list(movement)+attrs

    def remove_buff(self, template, now, *, expired=False):
        packets = super().remove_buff(template,now,expired=expired)
        if template==330111: packets.append(self._cooldown(0,True))
        return packets

    def _substitute(self, now, *, lethal=False):
        if lethal:
            self.passive_ready_at = now+30000
            self.hp = D(1)
            self.info['hp'] = 1
        packets = self.cleanse(now) if lethal else []
        packets.append(self._hp_packet(self.id,self.hp))
        packets.append(scene(skills=(self._skill_event(330101,self.position_at(now),self.position_at(now)),)))
        for template in (330131,330132,330133,330135): packets.extend(self._buff(template,now))
        stats = dict(self.stats)
        for key in ('iAttack','iEgAtk','iArmor','iEgArmor','iCentesis','iEgCtsis'):
            stats[key] = str(self.combat_stat(key,now))
        stats['iHp'] = str(self.max_hp)
        info = dict(acct_id=self.info['acct_id'],tank_id=self.info['tank_id'],tank_level=self.info['tank_level'],
                    npc_template=20003,owner=self.id,source_generation=self.generation,name=self.info['name'],
                    in_room=True,summon_stats=stats,summon_hp=str(self.max_hp))
        wood = KakashiWood(self.arena,self._new_id(5),info,self.camp,self.position_at(now))
        self.arena.actors[wood.id] = wood
        wood._queue(now+2500,'kakashi_wood_end')
        return packets+[wood.snapshot(now)]

    def prevent_lethal_hit(self, hit, now):
        if self.alive and hit.hp_after==0 and now>=self.passive_ready_at:
            self.shields = hit.shields
            return self._substitute(now,lethal=True)+[self.shield_packet(now)]
        return None

    def commit_hp(self, hp, now,*,critical=False):
        if self.alive and hp==0 and now>=self.passive_ready_at:
            return self._substitute(now,lethal=True)
        return super().commit_hp(hp,now,critical=critical)

    def on_damage(self, source, hit, now, school, reflected, attacker_ap):
        packets=super().on_damage(source,hit,now,school,reflected,attacker_ap)
        return packets+(self._break_stealth(now) if self.alive and hit.hp_loss>0 else [])

    def on_skill_damage(self, source, hit, now):
        packets=super().on_skill_damage(source,hit,now)
        if self.alive and hit.hp_loss>0 and self.has_buff(330403,now):
            return packets+self.remove_buff(330403,now)+self._substitute(now)
        return packets

    def on_control(self, source, template, now):
        packets=super().on_control(source,template,now)
        row = table_row('BuffTemplate_table.xml',nBuffId=template)
        if row['nEffectType'] in ('30','35','66') and template!=330304:
            return packets+self.interrupt(now)
        return packets

    def interrupt(self, now):
        packets = []
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            self.ready = None
        if self.dash:
            # CC/death may have cleared motion before calling interrupt.
            origin = self.motion[0] if self.motion else self.dash.get('start',self.position)
            self.position,self.motion = self.move_destination(origin,self.position_at(now)),None
            self.dash = None
            packets.append(stop_move(self.scene_id,self.id,self.position))
            packets.extend(self.remove_buff(330402,now))
            packets.extend(self.remove_buff(50353,now))
        if not self.alive:
            self.vanish = None
            if self.kamui: packets.extend(self._end_kamui(now,explode=False))
        return packets+super().interrupt(now)+self.sync_speed(now)

    def _end_kamui(self, now, *, explode):
        cast,self.kamui = self.kamui,None
        if not cast: return []
        packets = []
        blast = explode and self.alive and self.generation==cast['generation']
        # Only the completed Kamui field (330302, first object) owns the
        # native si_fuzhirenzhe_k03 remove movie. Cancellation stays silent.
        for index,ident in enumerate(cast['objects']):
            packets.extend(self.remove_object(ident,destroyed=blast and index==0))
        for target in list(self.arena.actors.values()):
            for template in (330304,330305):
                if target.buff_sources.get(template)==self.id:
                    packets.extend(target.remove_buff(template,now))
        for template in (330307,330308,330310): packets.extend(self.remove_buff(template,now))
        packets.append(self._cooldown(2,True))
        if blast:
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))<=192:
                    packets.extend(self.damage(cast['power']*D('3.39'),now,target=target,school='energy',pen_snapshot=cast['pen'])[0])
        return packets

    def _event(self, now, kind, data):
        if kind=='kakashi_regen':
            if not self.alive or self.generation!=data[0]: return []
            self._queue(now+1000,kind,self.generation)
            return self._resource(5)
        if kind=='kakashi_ready':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']: return []
            self.ready = None
            start = self.position_at(now)
            packets = [scene(skills=(self._skill_event(cast['skill'],start,cast['dest']),))]
            if cast['skill']==330141:
                dest = self.blink_destination(start,aimed(start,cast['dest'],300))
                self.position,self.motion = dest,None
                self.vanish = cast
                cast['pos'] = dest
                packets.extend(self._buff(330143,now))
                packets = self._stop_packets(packets,dest)
                for template,pos,duration in ((330142,start,700),(330144,dest,500)):
                    ident,packet = self.add_object(template,pos);packets.append(packet)
                    self._queue(now+duration,'object_expire',ident)
                self._queue(now+500,'kakashi_thunder',cast)
            else:
                cast.update(pos=start,objects=[])
                ident,packet = self.add_object(330301,start)
                cast['objects'].append(ident);packets.append(packet)
                self._queue(now+250,'kakashi_open',cast)
            return packets+self.sync_speed(now)
        if kind=='kakashi_thunder':
            cast, = data
            if self.vanish is not cast or not self.alive or self.generation!=cast['generation']: return []
            self.vanish = None
            packets = self.remove_buff(330143,now)
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))<=120:
                    packets.extend(self._buff(330145,now,target.id))
                    packets.extend(self.damage(cast['power'],now,target=target,school='true',basic=True)[0])
            return packets+self.sync_speed(now)
        if kind=='kakashi_open':
            cast, = data
            packets = []
            for ident in cast['objects']: packets.extend(self.remove_object(ident))
            if not self.alive or self.generation!=cast['generation']: return packets
            cast.update(begin=now,end=now+3000,objects=[])
            self.kamui = cast
            for template in (330302,330303):
                ident,packet = self.add_object(template,cast['pos']);cast['objects'].append(ident);packets.append(packet)
            packets.extend(self._buff(330307,now)+self._buff(330308,now))
            packets.append(self._cooldown(2,True))
            for i in (1,2,3): self._queue(now+1000*i,'kakashi_heal',cast)
            packets.extend(self._event(now,'kakashi_field',(cast,)))
            return packets
        if kind=='kakashi_field':
            cast, = data
            if self.kamui is not cast: return []
            if not self.alive or self.generation!=cast['generation']: return self._end_kamui(now,explode=False)
            if now>=cast['end']: return self._end_kamui(now,explode=True)
            packets = []
            for target in list(self.arena.actors.values()):
                if not target.alive or not target.is_area_targetable() or math.dist(cast['pos'],target.position_at(now))>192: continue
                if not target.cc_immune(now): packets.extend(self._buff(330304,now,target.id,duration=min(300,cast['end']-now)))
                packets.extend(self._buff(330305,now,target.id,duration=min(300,cast['end']-now)))
            self._queue(min(now+250,cast['end']),kind,cast)
            return packets
        if kind=='kakashi_heal':
            cast, = data
            return self.restore_hp(cast['power']*D('.75'),now) if self.kamui is cast and self.alive and math.dist(self.position_at(now),cast['pos'])<=192 else []
        if kind=='kakashi_dash':
            cast, = data
            if self.dash is not cast or not self.alive: return []
            # Roots can stop motion without interrupting attack-capable casts.
            # A stopped dash cannot inspect its old trajectory or hit again.
            if self.motion is None:
                self.dash=None
                return ([stop_move(self.scene_id,self.id,self.position)]
                        +self.remove_buff(330402,now)+self.remove_buff(50353,now)+self.sync_speed(now))
            start,end = self.position_at(cast['previous']),self.position_at(now)
            contacts = [(h,t.id,t) for t in enemies(self)
                        if (h:=actor_contact(start,end,t,cast['previous'],now)) is not None]
            packets = []
            if contacts:
                h,_,target = min(contacts,key=lambda r:r[:2])
                pos = self.move_destination(self.motion[0],tuple(round(v) for v in point_at(start,end,h)))
                self.position,self.motion = pos,None
                packets.append(stop_move(self.scene_id,self.id,pos))
                packets.append(scene(skills=(self._skill_event(330411,pos,pos,target.id),)))
                for target in enemies(self,area=True):
                    if math.dist(pos,target.position_at(now))>144: continue
                    packets.extend(self.damage(cast['power']*D('1.75'),now,target=target,school='energy',pen_snapshot=cast['pen'])[0])
                    if self.arena.pk and self.arena.pk['finished']:
                        break  # Keep the existing dash teardown below.
                    packets.extend(self._buff(330412,now,target.id))
                    if target.alive and not target.cc_immune(now):
                        p = target.position_at(now)
                        dest = aimed(pos,p,math.dist(pos,p)+72,fixed=True) if p!=pos else (p[0]+72,p[1])
                        target._set_motion(p,dest,480,now,kind=1)
                        target.forced_until=target.motion[3]
                        packets.append(scene(moves=(target._move_event(target.motion[1],480,1),)))
            if contacts or not self.motion or now>=self.motion[3]:
                if not contacts:
                    self.position,self.motion = self.position_at(now),None
                    packets.append(stop_move(self.scene_id,self.id,self.position))
                self.dash = None
                packets.extend(self.remove_buff(330402,now))
                packets.extend(self.remove_buff(50353,now))
                return packets+self.sync_speed(now)
            cast['previous'] = now
            self._queue(min(now+20,self.motion[3]),kind,cast)
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot==1:return self.cast_borrowed(start,dest,target_id,now)
        if slot==2 and self.kamui:
            if not self.alive or self.in_stasis() or now<self.kamui['begin']+1000: return []
            return self._end_kamui(now,explode=False)
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or now<self.cooldowns[slot]: return []
        if slot==0:
            borrowed=self.borrowed_basic(now)
            if borrowed:
                stealth=self.stealth_versions(now)
                packets=borrowed.run('cast',0,start,dest,target_id,now)
                return packets+self.break_borrowed_stealth(now,stealth)+[self._cooldown(0,True)] if packets else []
        fee = {0:0,2:75,10:25}[slot]
        if self.mp<fee or slot in (0,10) and start==dest: return []
        power = self.combat_stat('iEgAtk',now)
        self._cast_pen=D('.25') if self.has_buff(305201,now) else D(0)
        packets = self.break_borrowed_stealth(now,self.stealth_versions(now))+self._resource(-fee)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),2:30000,10:8000}[slot], slot)
        if slot==0 and not self.has_buff(330111,now):
            return packets+self.shoot(330100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        if slot==0:
            packets.extend(self.remove_buff(330111,now))
            skill = 330141
            warning,packet=self.add_object(330151,self.blink_destination(start,aimed(start,dest,300)))
            packets.append(packet);self._queue(now+450,'object_expire',warning)
        else:
            packets.extend(self._empower(now))
            skill = SLOTS[slot]
        body,handoff = prepare_displacement(self,now,interrupt=False)
        if not handoff: body = start  # Preserve a legal C510 client origin.
        if slot==10:
            duration = self._set_motion(body,aimed(start,dest,480),720,now,kind=3)
            self.dash = dict(start=start,previous=now,generation=self.generation,power=power,pen=self._cast_pen)
            self._queue(now+min(20,duration),'kakashi_dash',self.dash)
            # Original generic BUT_AUTO_MOVE/MOVE_DASH marker. The visual hit
            # buff330402 is type46 and alone does not stop held movement keys.
            packets.extend(self._buff(50353,now)+self._buff(330402,now)+self._buff(330403,now))
            movement = [scene(moves=(self._move_event(self.motion[1],720,3),),skills=(self._skill_event(skill,start,dest),))]
        else:
            self.position,self.motion = body,None
            self.ready = dict(slot=slot,skill=skill,dest=dest,power=power,generation=self.generation,pen=self._cast_pen)
            self._queue(now+50,'kakashi_ready',self.ready)
            packets.append(scene(skills=(self._skill_event(skill,start,dest,ready=1),)))
            movement = []
        return self._stop_packets(packets+[self._cooldown(slot)]+self.sync_speed(now)+handoff,body,movement)


class KakashiWood(StrangeShadow):
    def snapshot(self, now):
        body = struct.pack('<IIhhiBiIiH',self.id,20003,*self.position_at(now),math.ceil(self.hp),self.camp,
                           math.ceil(self.max_hp),self.info['owner'],0,0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def _event(self, now, kind, data):
        if kind=='kakashi_wood_end': return self.commit_hp(D(0),now) if self.alive else []
        return super()._event(now,kind,data)
