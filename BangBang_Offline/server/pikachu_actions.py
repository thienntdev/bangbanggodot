"""Pikachu: marks, mobile contact aura and the approved five-second Space."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:321100, 1:321201, 2:321301, 10:321401}
MARKS = (321121,321122,321123,321124)


class PikachuActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.r_count, self.r_next_charge = 2, 0
        self.ready = self.contact = self.discharge = None

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,self.r_count if slot==10 else -1,
                          self.cooldowns[slot],self.r_next_charge if slot==10 else 0)+struct.pack('<I',self.id)

    def update(self, now):
        packets = super().update(now)
        if self.r_next_charge and now>=self.r_next_charge:
            while self.r_count<2 and now>=self.r_next_charge:
                self.r_count += 1
                self.r_next_charge += self.skill_cooldown(6000)
            if self.r_count==2:
                self.r_next_charge = 0
            packets.append(self._cooldown(10))
        return packets

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None

    def interrupt(self, now):
        packets = []
        if self.ready:
            slot = self.ready['slot']
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,SLOTS[slot])))
        if not self.alive:
            self.contact = self.discharge = None
        return packets

    def _mark(self, target, count, now, *, periodic=False):
        packets = []
        for _ in range(count):
            if not target.alive:
                break
            stage = max((i+1 for i,t in enumerate(MARKS) if target.has_buff(t,now)),default=0)
            for template in MARKS:
                if target.has_buff(template,now):
                    packets.extend(target.remove_buff(template,now))
            if stage<4:
                packets.extend(self._buff(MARKS[stage],now,target.id))
            else:
                packets.extend(self._buff(321111,now,target.id))
                packets.extend(self.damage(target.max_hp*D('.1'),now,target=target,
                                           school='energy',periodic=periodic)[0])
                for template in (321113,321114,321115):
                    packets.extend(self._buff(template,now,target.id))
            packets.extend(self._buff(321102,now,target.id))
        return packets

    def on_bullet_hit(self, flight, target, now):
        if flight['source_generation']!=self.generation or not self.alive:
            return []
        return self._mark(target,1,now) if flight['template']==321100 else []

    def _event(self, now, kind, data):
        if kind=='electric_ready':
            cast, = data
            if self.ready is not cast or not self.alive or cast['generation']!=self.generation:
                return []
            self.ready = None
            start = self.position_at(now)
            if cast['slot']==10:
                return self.shoot(321401,start,cast['dest'],now,cast['power']*D('1.55'),school='energy',power=cast['power'])
            distance = math.dist(start,cast['dest'])
            if distance==0:
                return []
            end = point_at(start,cast['dest'],360/distance)
            # DASH3 is a timed forced move for both self and remote clients.
            # Keep the stored kind identical so a resumed E is also a dash.
            duration = self._set_motion(start,end,720,now,kind=3)
            end = self.motion[1]
            self.forced_until = now+duration
            self.contact = dict(power=cast['power'],previous=now,end=now+4000,hits=set())
            self._queue(now+20,'electric_contact',self.contact)
            packets = [scene(moves=(self._move_event(end,720,3),),skills=(self._skill_event(321201,start,end),))]
            for template in (321202,321203,321204,321205,321221):
                packets.extend(self._buff(template,now))
            return packets
        if kind=='electric_contact':
            contact, = data
            if self.contact is not contact or not self.alive:
                return []
            if now>contact['end']:
                self.contact = None
                return []
            start,end = self.position_at(contact['previous']),self.position_at(now)
            packets = []
            for target in list(self.arena.actors.values()):
                key = target.id,target.generation
                if not target.alive or target.camp==self.camp or key in contact['hits']:
                    continue
                if actor_contact(start,end,target,contact['previous'],now,73) is None:
                    continue
                contact['hits'].add(key)
                packets.extend(self.damage(contact['power']*D('1.85'),now,target=target,school='energy')[0])
                packets.extend(self._mark(target,2,now))
                packets.extend(self._buff(321213,now,target.id))
            contact['previous'] = now
            if now<contact['end']:
                self._queue(min(now+20,contact['end']),kind,contact)
            else:
                self.contact = None
            return packets
        if kind=='electric_discharge':
            cast, = data
            if self.discharge is not cast or not self.alive:
                return []
            packets = []
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(self.position_at(now),target.position_at(now))<=240:
                    packets.extend(self.damage(cast['power']*D('.75'),now,target=target,school='energy',
                                               lifesteal=D('.3'),periodic=True)[0])
                    packets.extend(self._mark(target,1,now,periodic=True))
            if now<cast['end']:
                self._queue(now+500,kind,cast)
            else:
                self.discharge = None
            return packets
        return super()._event(now,kind,data)

    def _flight(self, flight, now):
        if flight.get('template')!=321401:
            return super()._flight(flight,now)
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        contacts = []
        for target in self.arena.actors.values():
            key = target.id,target.generation
            if target.alive and target.camp!=self.camp and key not in flight['hits']:
                hit = actor_contact(start,end,target,previous,now,36+48)
                if hit is not None:
                    contacts.append((hit,target.id))
        packets = []
        for _,ident in sorted(contacts):
            target = self.arena.actors[ident]
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['hits'].add((target.id,target.generation))
            packets.extend(self.damage(flight['raw'],now,target=target,school='energy')[0])
            packets.extend(self._buff(321402,now,target.id))
            if self.alive and self.generation==flight['source_generation']:
                if self.r_next_charge:
                    self.r_next_charge = max(now,self.r_next_charge-1000)
                    packets.extend(self.update(now))
                    packets.append(self._cooldown(10))
                packets.extend(self._mark(target,1,now))
        if now>=finish:
            return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return packets

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot!=2 and (not self._inside(dest) or start==dest) or slot==10 and not self.r_count:
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:1000}[slot], slot)
        if slot==0:
            packets = self.shoot(321100,start,dest,now,power,school='energy',basic=True)
        elif slot in (1,10):
            if slot==10:
                self.r_count -= 1
                if not self.r_next_charge:
                    self.r_next_charge = now+self.skill_cooldown(6000)
            self.ready = dict(slot=slot,dest=dest,power=power,generation=self.generation)
            self._queue(now+150,'electric_ready',self.ready)
            packets = [scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),))]
        else:
            self.discharge = dict(power=power,end=now+5000)
            self._queue(now+500,'electric_discharge',self.discharge)
            packets = [scene(skills=(self._skill_event(321301,start,start,self.id),))]
            for template in (321301,321302,321303,321304):
                packets.extend(self._buff(template,now,duration=5000))
        return packets+[self._cooldown(slot)]
