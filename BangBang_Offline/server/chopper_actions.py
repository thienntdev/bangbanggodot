"""Chopper: original skill chain, Q01 shield and agreed wave collision rules."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, TANK_CONTACT_RADIUS, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:304100, 1:304201, 2:304301, 10:304401}


class ChopperActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.skills = {i:table_row('SkillTemplate_table.xml',nId=i) for i in SLOTS.values()}
        self.r_count, self.r_next_charge = 2, 0
        self.shield_epoch = 0
        self.aura = None

    def _cooldown(self, slot):
        return 1572, props(SLOTS[slot],slot,self.r_count if slot==10 else -1,
                           self.cooldowns[slot],self.r_next_charge if slot==10 else 0)+struct.pack('<I',self.id)

    def on_spawn(self, now):
        self.shield_epoch += 1
        return self.add_shield(304111,self.max_hp*D('.25'),now)

    def on_shield_break(self, template, now):
        if template!=304111 or not self.alive:
            return []
        self.shield_epoch += 1
        self._queue(now+15000,'shield_return',self.generation,self.shield_epoch)
        return self._buff(304121,now)

    def interrupt(self, now):
        if not self.alive and self.aura:
            self.aura = None
            self.cooldowns[2] = now+self.skill_cooldown(25000, 2)
            return [self._cooldown(2)]
        return []  # A mobile aura, not an interruptible beam.

    def on_death(self):
        self.aura = None
        self.shield_epoch += 1

    def update(self, now):
        packets = super().update(now)
        if self.r_next_charge and now>=self.r_next_charge:
            while self.r_count<2 and now>=self.r_next_charge:
                self.r_count += 1
                self.r_next_charge += self.skill_cooldown(8000)
            if self.r_count==2:
                self.r_next_charge = 0
            packets.append(self._cooldown(10))
        return packets

    def _event(self, now, kind, data):
        if kind=='shield_return':
            generation,epoch = data
            return self.on_spawn(now) if self.alive and self.generation==generation and self.shield_epoch==epoch else []
        if kind=='heal_aura':
            cast, = data
            if self.aura is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            packets = []
            for target in self.arena.actors.values():
                if target.alive and target.camp==self.camp and math.dist(self.position_at(now),target.position_at(now))<=300:
                    packets.extend(target.restore_hp(cast['power']*D('.7'),now))
                    packets.extend(self._buff(304312,now,target.id))
            if now==cast['end']:
                self.aura = None
                self.cooldowns[2] = now+self.skill_cooldown(25000, 2)
                packets.append(self._cooldown(2))
            return packets
        return super()._event(now,kind,data)

    def _flight(self, flight, now):
        if flight.get('template')!=304401:
            return super()._flight(flight,now)
        # A wave crosses tanks once each. User approved wall stops and push 240/480.
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        wall = self.arena.geometry.wall_contact(start,end)
        packets = []
        hits = flight.setdefault('hits',set())
        for target in list(self.arena.actors.values()):
            if not target.alive or target.camp==self.camp or target.id in hits:
                continue
            hit = actor_contact(start,end,target,previous,now,98+TANK_CONTACT_RADIUS)
            if hit is None or (wall is not None and hit>=wall):
                continue
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            hits.add(target.id)
            packets.extend(self._buff(304401,now,target.id))
            if not target.cc_immune(now):
                # The wave may hit during another source's wall-crossing push.
                # Interrupt the old kit before installing the new push: dash
                # cleanup must never cancel a segment just advertised below.
                # Contact and damage keep the original projectile samples.
                generation = target.generation
                origin,stopped = prepare_displacement(target,now)
                packets.extend(stopped)
                if self.arena.pk and self.arena.pk['finished']:
                    break
                if not target.alive or target.generation!=generation:
                    continue
                dx,dy = (b-a for a,b in zip(flight['start'],flight['end']))
                distance = math.hypot(dx,dy)
                dest = self.arena.geometry.clamp_tank_position((origin[0]+dx/distance*240,origin[1]+dy/distance*240))
                contact = self.arena.geometry.wall_contact(origin,dest,TANK_CONTACT_RADIUS)
                if contact is not None:
                    dest = point_at(origin,dest,max(0,contact-.001))
                dest = tuple(round(v) for v in dest)
                target.forced_until = now+target._set_motion(origin,dest,480,now,kind=3)
                dest = target.motion[1]
                packets.append(scene(moves=(self._move_event(dest,480,3,target.id),)))
            packets.extend(self.damage(flight['raw'],now,target=target,school='energy')[0])
            if self.arena.pk and self.arena.pk['finished']:
                break
        ident = struct.pack('<I',flight['id'])
        if wall is not None or now>=finish:
            packets.append(scene(expired_bullets=(ident,)))
        else:
            flight['previous'] = now
            self._queue(min(now+20,finish),'flight',flight)
        return packets

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot==2 and self.aura or slot==10 and not self.r_count:
            return []
        if slot in (0,10) and (not self._inside(dest) or start==dest):
            return []
        target = self.arena.actors.get(target_id)
        if slot==1 and (target is None or not target.alive or target.camp!=self.camp
                        or math.dist(start,target.position_at(now))>480):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+{0:self.fire_interval(now),1:self.skill_cooldown(6000, 1),2:6000,10:self.skill_cooldown(4000, 10)}[slot]
        if slot in (0,10):
            if slot==10:
                self.r_count -= 1
                if not self.r_next_charge:
                    self.r_next_charge = now+self.skill_cooldown(8000)
            return self.shoot(SLOTS[slot],start,dest,now,power*(D('2.26') if slot==10 else 1),
                              school='energy',basic=slot==0)+[self._cooldown(slot)]
        if slot==1:
            packets = [scene(skills=(self._skill_event(304201,start,target.position_at(now),target.id),))]
            packets.extend(target.restore_hp(power*D('2.6'),now))
            packets.extend(self._buff(304202,now,target.id))
        else:
            self.aura = dict(generation=self.generation,end=now+6000,power=power)
            packets = [scene(skills=(self._skill_event(304301,start,start,self.id),))]
            for template in (304301,304302,304303,304304):
                packets.extend(self._buff(template,now))
            for offset in range(500,6001,500):
                self._queue(now+offset,'heal_aura',self.aura)
        return packets+[self._cooldown(slot)]
