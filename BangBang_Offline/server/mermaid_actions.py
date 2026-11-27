"""Mermaid: delayed geyser, one mark proc per skill hit, and a piercing wave."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:340100, 1:340201, 2:340301, 10:340401}


class MermaidActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.ready = None

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self, now):
        return self._buff(340101,now)

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None

    def _speed(self, now):
        return 0 if self.ready else super()._speed(now)

    def update(self, now):
        packets = self.interrupt(now) if self.ready and self.skill_sealed(2,now) else []
        return packets+super().update(now)

    def interrupt(self, now):
        packets = []
        if self.ready:
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,340301)))
        return packets+self.sync_speed(now)

    def _enemies(self, center, radius, now):
        return [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                and a.is_area_targetable() and math.dist(center,a.position_at(now))<=radius]

    def _hit(self, target, raw, now):
        marked = target.has_buff(340103,now) and target.buff_sources.get(340103)==self.id
        packets,lost = self.damage(raw,now,target=target,school='energy')
        if not lost:
            return packets
        if marked and target.alive:
            # User keeps V1; raw upper-rate .2 has no verified server semantics.
            packets.extend(self.damage(target.max_hp*D('.1'),now,target=target,school='true')[0])
        for buff in (340102,340103,340104):
            packets.extend(self._buff(buff,now,target.id))
        return packets

    def _burst(self, flight, center, now):
        targets = self._enemies(center,120,now)
        packets = []
        for target in targets:
            packets.extend(self._hit(target,flight['raw'],now))
        # User: one refund/shield per cast, independent of number of victims.
        if targets and self.alive and flight['source_generation']==self.generation:
            self.cooldowns[10] = max(now,self.cooldowns[10]-3000)
            packets.extend(self.add_shield(340403,flight['power']*D('1.5'),now))
            packets.append(self._cooldown(10))
        return packets

    def _flight(self, flight, now):
        if flight['template']==340100:
            return super()._flight(flight,now)
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        wave = flight['template']==340301
        contacts = []
        for target in self.arena.actors.values():
            if (not target.alive or target.camp==self.camp or target.is_untargetable()
                    or (target.id,target.generation) in flight['hits']):
                continue
            hit = actor_contact(start,end,target,previous,now,156 if wave else 84)
            if hit is not None:
                contacts.append((hit,target.id))
        packets = []
        for hit,ident in sorted(contacts):
            target = self.arena.actors[ident]
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            if not wave:
                center = tuple(round(x) for x in point_at(start,end,hit))
                return self._burst(flight,center,now)+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
            flight['hits'].add((target.id,target.generation))
            packets.extend(self._hit(target,flight['raw'],now))
            packets.extend(self._buff(340302,now,target.id))
        if now>=finish:
            if not wave:
                packets.extend(self._burst(flight,flight['end'],now))
            return packets+[scene(**{('expired_bullets' if wave else 'blown_bullets'):(struct.pack('<I',flight['id']),)})]
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return packets

    def _event(self, now, kind, data):
        if kind=='mermaid_geyser':
            cast, = data
            packets = self.remove_object(cast['object'])
            ident,packet = self.add_object(340202,cast['pos'])
            packets.append(packet)
            # Native 340202 has only a REMOVE exhibit/sound, no live cover.
            packets.extend(self.remove_object(ident,destroyed=True))
            # User: already placed E survives the caster's death.
            for target in self._enemies(cast['pos'],120,now):
                packets.extend(self._hit(target,cast['power']*D('2.16'),now))
                packets.extend(self._buff(340212,now,target.id))
            return packets
        if kind=='mermaid_wave':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            if self.skill_sealed(2,now):
                return self.interrupt(now)
            self.ready = None
            return self.sync_speed(now)+self.shoot(340301,self.position_at(now),cast['dest'],now,
                cast['power']*D('4.44'),school='energy',power=cast['power'],through_walls=True)
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if (slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now)
                or self.cooldowns[slot]>now or not self._inside(dest) or start==dest):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:6000}[slot], slot)
        if slot in (0,10):
            packets = self.shoot(SLOTS[slot],start,dest,now,power*(D('2.05') if slot else 1),
                                  school='energy',basic=slot==0,power=power,through_walls=slot==10)
        elif slot==1:
            if math.dist(start,dest)>600:
                dest = tuple(round(x) for x in point_at(start,dest,600/math.dist(start,dest)))
            ident,packet = self.add_object(340201,dest)
            self._queue(now+800,'mermaid_geyser',dict(pos=dest,power=power,object=ident))
            packets = [packet,scene(skills=(self._skill_event(340201,start,dest),))]
        else:
            self.ready = dict(slot=2,dest=dest,power=power,generation=self.generation)
            body,stopped = prepare_displacement(self,now,interrupt=False)
            self.position,self.motion = body if stopped else start,None
            self._queue(now+500,'mermaid_wave',self.ready)
            packets = [scene(skills=(self._skill_event(340301,start,dest,ready=1),))]+self.sync_speed(now)+stopped
        return packets+[self._cooldown(slot)]
