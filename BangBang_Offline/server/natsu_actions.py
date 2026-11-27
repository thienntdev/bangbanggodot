"""Natsu: three stored casts, native enhanced slots and a moving 500 ms aura."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:365100, 1:365201, 2:365401, 10:365301}
STAGES = ((365102,365103),(365104,365105),(365106,365107))
AURA_BUFFS = (365402,365403,365404,365405,365406,365407)


class NatsuActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.power_stacks = 0
        self.ready = self.dash = self.aura = None

    def _slot(self, slot):
        if slot in (1,10) and self.has_buff(365405 if slot==1 else 365406,self.clock()):
            return 365501 if slot==1 else 365601
        return SLOTS[slot]

    def _cooldown(self, slot, changed=False):
        body = props(self._slot(slot),slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _slots(self):
        return [packet for slot in (1,10) for packet in (self._cooldown(slot,True),self._cooldown(slot))]

    def on_spawn(self, now):
        return self._buff(365101,now)+self._slots()

    def on_death(self):
        self.power_stacks = 0
        self.aura = None

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None or self.dash is not None

    def _speed(self, now):
        return 0 if self.ready or self.dash else super()._speed(now)

    def remove_buff(self, template, now, *, expired=False):
        existed = (self.id,template) in self.active_buffs
        packets = super().remove_buff(template,now,expired=expired)
        if existed and template in (365405,365406):
            slot = 1 if template==365405 else 10
            packets.extend((self._cooldown(slot,True),self._cooldown(slot)))
        return packets

    def _passive(self, slot, now):
        packets = []
        for templates in STAGES:
            for template in templates:
                if (self.id,template) in self.active_buffs:
                    packets.extend(self.remove_buff(template,now))
        if self.power_stacks==3:
            self.power_stacks = 0
            packets.extend(self.remove_buff(365108,now))
            self.cooldowns[slot] = max(now,self.cooldowns[slot]-6000)
            for template in (365109,365110):
                packets.extend(self._buff(template,now))
        else:
            self.power_stacks += 1
            for template in STAGES[self.power_stacks-1]:
                packets.extend(self._buff(template,now))
            if self.power_stacks==3:
                packets.extend(self._buff(365108,now))
        return packets

    def interrupt(self, now):
        packets = []
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            self.ready = None
        if self.dash:
            template = self.dash['buff']
            self.dash = None
            self.position,self.motion,self.forced_until = self.position_at(now),None,now
            packets.extend(self.remove_buff(template,now))
        return packets+self.sync_speed(now)

    def _enemies(self, center, radius, now):
        return [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                and a.is_area_targetable() and math.dist(center,a.position_at(now))<=radius]

    def _event(self, now, kind, data):
        if kind=='natsu_flame':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            self.ready = None
            center = self.position_at(now)
            packets = self.sync_speed(now)+[scene(skills=(self._skill_event(cast['skill'],center,cast['dest']),))]
            enhanced = cast['enhanced']
            radius = 528 if enhanced else 480
            length = math.dist(center,cast['dest'])
            if not length:
                return packets
            direction = tuple((b-a)/length for a,b in zip(center,cast['dest']))
            for target in self._enemies(center,radius+36,now):
                pos = target.position_at(now)
                delta = tuple(b-a for a,b in zip(center,pos))
                along = sum(a*b for a,b in zip(delta,direction))
                across = abs(delta[0]*direction[1]-delta[1]*direction[0])
                contact = (math.dist(center,pos)<=528 and along>=math.dist(center,pos)*math.cos(math.radians(22.5))
                           if enhanced else 0<=along<=480 and across<=48+36)
                if not contact:
                    continue
                packets.extend(self.damage(cast['power']*D('1.66' if enhanced else '1.28'),now,
                                          target=target,school='energy',lifesteal=D('.3') if enhanced else 0)[0])
                packets.extend(self._buff(365202,now,target.id))
                if enhanced:
                    packets.extend(self._buff(365503,now,target.id))
            return packets
        if kind=='natsu_arrive':
            cast, = data
            if self.dash is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            self.dash = None
            center = self.position_at(now)
            self.position,self.motion,self.forced_until = center,None,now
            packets = self.remove_buff(cast['buff'],now)+self.sync_speed(now)
            enhanced = cast['enhanced']
            targets = [(target,target.max_hp-target.hp) for target in self._enemies(center,240 if enhanced else 192,now)]
            for target,missing in targets:
                # One logical impact: snapshot missing HP before both packets.
                packets.extend(self.damage(cast['power']*D('2.29' if enhanced else '1.76'),now,
                                          target=target,school='energy',lifesteal=D('.3') if enhanced else 0)[0])
                if enhanced and target.alive:
                    packets.extend(self.damage(missing*D('.06'),now,target=target,school='true')[0])
            for template in ((365604,365303) if enhanced else (365303,365304,365305)):
                packets.extend(self._buff(template,now))
            return packets
        if kind=='natsu_aura':
            cast,index = data
            if self.aura is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            center = self.position_at(now)
            packets = [scene(skills=(self._skill_event(365801,center,center,self.id),))]
            for target in self._enemies(center,240,now):
                multiplier = D('.75') if math.dist(center,target.position_at(now))<=120 else D('.5')
                packets.extend(self.damage(cast['power']*multiplier,now,target=target,school='energy',periodic=True)[0])
            packets.extend(self.restore_hp((self.max_hp-self.hp)*D('.03'),now))
            if index==16:
                self.aura = None
            else:
                self._queue(now+500,kind,cast,index+1)
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot!=2 and (not self._inside(dest) or start==dest):
            return []
        power = self.combat_stat('iEgAtk',now)
        skill = self._slot(slot)
        enhanced = skill in (365501,365601)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:25000,10:8000}[slot], slot)
        packets = self._passive(slot,now) if slot else []
        if slot==0:
            packets.extend(self.shoot(skill,start,dest,now,power,school='energy',basic=True,power=power))
        elif slot==1:
            self.ready = dict(slot=1,skill=skill,dest=dest,power=power,generation=self.generation,enhanced=enhanced)
            body,stopped = prepare_displacement(self,now,interrupt=False)
            self.position,self.motion = body if stopped else start,None
            self._queue(now+100,'natsu_flame',self.ready)
            packets.append(scene(skills=(self._skill_event(skill,start,dest,ready=1),)))
            packets.extend(self.sync_speed(now)+stopped)
        elif slot==10:
            if math.dist(start,dest)>336:
                dest = point_at(start,dest,336/math.dist(start,dest))
            body,stopped=prepare_displacement(self,now,interrupt=False)
            body=body if stopped else start
            duration = self._set_motion(body,dest,600,now,kind=3)
            self.forced_until = now+duration
            self.dash = dict(power=power,generation=self.generation,enhanced=enhanced,
                             buff=365601 if enhanced else 365301)
            self._queue(now+duration,'natsu_arrive',self.dash)
            packets.extend(self._buff(self.dash['buff'],now,duration=duration))
            packets.extend(stopped)
            packets.append(scene(moves=(self._move_event(self.motion[1],600,3),)))
            packets.extend(self.sync_speed(now))
        else:
            self.aura = dict(power=power,generation=self.generation,end=now+8000)
            for template in AURA_BUFFS:
                packets.extend(self._buff(template,now))
            packets.extend(self._slots())
            self._queue(now+500,'natsu_aura',self.aura,1)
        return packets+[self._cooldown(slot)]
