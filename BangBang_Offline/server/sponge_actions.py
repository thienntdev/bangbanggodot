"""Sponge: placed bubbles and one persistent soap pickup per damaging cast."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:319100, 1:319201, 2:319301}


class SpongeActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.cooldowns = {slot:0 for slot in SLOTS}
        self.soaps = {}

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self, now):
        return self._buff(319101,now)

    def _lob(self, template, start, dest, now, power):
        ident = self._new_id(2)
        dest = tuple(round(x) for x in dest)
        # Soap is a thrown pickup, not a normal/skill projectile.
        factor=1.15 if template!=319102 and self.has_buff(10400233,now) else 1
        speed = max(1,round(math.dist(start,dest)*factor))
        flight = dict(kind='bullet',id=ident,template=template,start=start,end=dest,
                      speed=speed,begin=now,previous=now,finish=now+round(1000/factor),
                      power=power,source_generation=self.generation)
        self._queue(now+20,'flight',flight)
        return [scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*dest,speed,template),))]

    def _passive(self, now, generation):
        if not self.alive or self.generation!=generation:
            return []
        start = self.position_at(now)
        # Approved temporary landing rule: an open point 72..168 from owner,
        # inside the enclosure; choose using the arena's persisted RNG.
        candidates = []
        for radius in (72,120,168):
            for index in range(16):
                angle = math.tau*index/16
                pos = (round(start[0]+radius*math.cos(angle)),round(start[1]+radius*math.sin(angle)))
                if pos==self.arena.geometry.clamp_tank_position(pos) and self.arena.geometry.wall_contact(pos,pos) is None:
                    candidates.append(pos)
        if not candidates:
            raise RuntimeError('No legal soap landing point on the supported map')
        return self.restore_hp(self.max_hp*D('.1'),now)+self._lob(319102,start,self.arena.rng.choice(candidates),now,D(0))

    def _area(self, center, radius, raw, buff, now, generation):
        packets,lost = [],False
        for target in list(self.arena.actors.values()):
            if target.alive and target.camp!=self.camp and math.dist(center,target.position_at(now))<=radius:
                hit,damage = self.damage(raw,now,target=target,school='energy')
                packets.extend(hit)
                packets.extend(self._buff(buff,now,target.id))
                lost |= damage
        if lost:
            packets.extend(self._passive(now,generation))
        return packets

    def _flight(self, flight, now):
        if flight['template']==319100:
            return super()._flight(flight,now)
        # E and passive soap are point-targeted lobs, not contact detonations.
        if flight['template']==319201:
            duration=flight['finish']-flight['begin']
            start = point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/duration)
            end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/duration))
            for target in self.arena.actors.values():
                if (target.alive and target.camp!=self.camp and self.projectile_blocked(target,now)
                        and actor_contact(start,end,target,flight['previous'],now) is not None):
                    return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        if now<flight['finish']:
            flight['previous'] = now
            self._queue(min(now+20,flight['finish']),'flight',flight)
            return []
        packets = [scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if flight['template']==319201:
            return packets+self._area(flight['end'],96,flight['power']*D('1.7'),319211,now,flight['source_generation'])
        ident,packet = self.add_object(319102,flight['end'])
        soap = dict(id=ident,pos=flight['end'],previous=now,end=now+8000)
        self.soaps[ident] = soap
        self._queue(now+50,'sponge_pickup',soap)
        return packets+[packet]

    def _event(self, now, kind, data):
        if kind=='sponge_pickup':
            soap, = data
            if self.soaps.get(soap['id']) is not soap:
                return []
            candidates = []
            for actor in self.arena.actors.values():
                if actor.alive and not actor.is_untargetable():
                    hit = circle_contact(actor.position_at(soap['previous']),actor.position_at(now),soap['pos'],soap['pos'],36)
                    if hit is not None:
                        candidates.append((hit,actor.id))
            if candidates or now>=soap['end']:
                del self.soaps[soap['id']]
                packets = self.remove_object(soap['id'],destroyed=bool(candidates))
                if candidates:
                    target = self.arena.actors[min(candidates)[1]]
                    packets.extend(target.restore_hp(target.max_hp*D('.1'),now) if target.camp==self.camp
                                   else self._buff(319104,now,target.id))
                return packets
            soap['previous'] = now
            self._queue(min(now+50,soap['end']),kind,soap)
            return []
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot!=2 and (not self._inside(dest) or start==dest):
            return []
        if slot==1 and math.dist(start,dest)>360:
            dest = tuple(round(x) for x in point_at(start,dest,360/math.dist(start,dest)))
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:20000}[slot], slot)
        power = self.combat_stat('iEgAtk',now)
        if slot==0:
            packets = self.shoot(319100,start,dest,now,power,school='energy',basic=True,power=power)
        elif slot==1:
            packets = self._lob(319201,start,dest,now,power)
        else:
            packets = [scene(skills=(self._skill_event(319301,start,start,self.id),))]
            packets.extend(self._area(start,288,power*D('3.8'),319311,now,self.generation))
        return packets+[self._cooldown(slot)]
