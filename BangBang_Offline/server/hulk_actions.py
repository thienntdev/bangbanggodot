"""Hulk: finite rage ticks, missing-health healing and a bounded leap."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:308100,1:308501,2:308601,10:308401}


class HulkActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready = self.jump = None

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self._queue(now+3000,'hulk_regen',self.generation)
        return self._buff(308101,now)+self._buff(308102,now)

    def attr_bonus(self,attributes,now):
        value = super().attr_bonus(attributes,now)
        if 21 in attributes and self.has_buff(308102,now):
            value += D('.5')*(1-self.hp/self.max_hp)
        return value

    def _speed(self,now):
        return 0 if self.ready or self.jump else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.jump) or super().blocked(action,now)

    def interrupt(self,now):
        if not (self.ready or self.jump):
            return []
        cast = self.ready or self.jump
        self.ready = self.jump = None
        self.position,self.motion,self.forced_until = self.position_at(now),None,now
        packets = [(1583,struct.pack('<II',self.id,308501))]
        packets.extend(self.remove_object(cast['warning']))
        packets.extend(self.remove_buff(308502,now))
        return packets+[scene(moves=(self._move_event(self.position,0,5),))]+self.sync_speed(now)

    def update(self,now):
        packets = self.interrupt(now) if self.ready and self.skill_sealed(1,now) else []
        return packets+super().update(now)

    def on_basic_damage(self,source,hit,now):
        if not self.alive or not self.has_buff(308601,now):
            return []
        packets = self.restore_hp((self.max_hp-self.hp)*D('.03'),now)
        for slot in (1,10):
            self.cooldowns[slot] = now+round(max(0,self.cooldowns[slot]-now)*.9)
            packets.append(self._cooldown(slot))
        return packets+self._buff(308631,now)+self._buff(308641,now)

    def _event(self,now,kind,data):
        if kind=='hulk_regen':
            if not self.alive or self.generation!=data[0]:
                return []
            self._queue(now+3000,kind,*data)
            return self.restore_hp(self.max_hp*D('.06'),now)
        if kind=='hulk_rage_heal':
            generation,version = data
            if not self.alive or self.generation!=generation or self.buff_versions.get(308601)!=version:
                return []
            return self.restore_hp(self.max_hp*D('.03'),now)
        if kind=='hulk_jump':
            cast, = data
            if self.ready is not cast or not self.alive:
                return []
            self.ready,self.jump = None,cast
            start = self.position_at(now)
            dest = self.move_destination(start,cast['dest'])
            speed = max(1,round(math.dist(start,dest)*2))
            duration = self._set_motion(start,dest,speed,now,kind=4)
            self.forced_until = now+duration
            self._queue(now+duration,'hulk_land',cast)
            return [scene(skills=(self._skill_event(308501,start,self.motion[1]),),
                          moves=(self._move_event(self.motion[1],speed,4),))]+self._buff(308502,now,duration=duration)
        if kind=='hulk_land':
            cast, = data
            if self.jump is not cast or not self.alive:
                return []
            pos = self.position_at(now)
            self.jump = None
            self.position,self.motion,self.forced_until = pos,None,now
            packets = self.remove_object(cast['warning'])
            ident,packet = self.add_object(308522,pos)
            packets.append(packet)
            self._queue(now+416,'object_expire',ident)
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(pos,target.position_at(now))<=168:
                    packets.extend(self.damage(cast['power']*D('1.55'),now,target=target)[0])
                    packets.extend(self._buff(308512,now,target.id))
            return packets+self.remove_buff(308502,now)+self.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot in (0,1) and (not self._inside(dest) or start==dest):
            return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:10000,2:25000,10:6000}[slot], slot)
        if slot==0:
            return self.shoot(308100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        packets = [self._cooldown(slot)]
        if slot==1:
            distance = math.dist(start,dest)
            dest = self.move_destination(start,point_at(start,dest,min(1,408/distance)))
            ident,packet = self.add_object(308521,dest)
            body,handoff = prepare_displacement(self,now,interrupt=False)
            if not handoff: body = start
            self.position,self.motion = body,None
            self.ready = dict(slot=1,dest=dest,power=power,generation=self.generation,warning=ident)
            self._queue(now+100,'hulk_jump',self.ready)
            return packets+[packet,scene(skills=(self._skill_event(308501,start,dest,ready=1),))]+self.sync_speed(now)+handoff
        packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,start,self.id),)))
        if slot==2:
            version = self.buff_versions.get(308601,0)+1
            # Natural expiry must not swallow the eighth approved heal.
            for offset in range(1000,8001,1000):
                self._queue(now+offset,'hulk_rage_heal',self.generation,version)
            for template in (308601,308602,308603,308604):
                packets.extend(self._buff(template,now))
        else:
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(start,target.position_at(now))<=192:
                    packets.extend(self.damage(power*D('1.63'),now,target=target)[0])
                    packets.extend(self._buff(308402,now,target.id)+self._buff(308403,now,target.id))
        return packets
