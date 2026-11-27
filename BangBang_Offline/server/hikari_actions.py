"""Hikari: projectile wards, finite wind marks and three mobile Space pulses."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene, stop_move
from melee_common import prepare_displacement

SLOTS = {0:382100, 1:382201, 2:382301, 10:382401}


class HikariActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.e_count,self.e_next_charge = 2,0
        self.ready = self.temple = None

    def _cooldown(self, slot):
        body = props(SLOTS[slot],slot,self.e_count if slot==1 else -1,
                     0 if slot==2 and self.temple else self.cooldowns[slot],
                     self.e_next_charge if slot==1 else 0)
        return 1572,body+struct.pack('<I',self.id)

    def on_spawn(self, now):
        return self._buff(382101,now)+self._buff(382102,now)

    def _speed(self, now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self, action, now):
        return self.ready is not None or super().blocked(action,now)

    def _near(self, center, radius, now, *, allied=False):
        return [a for a in self.arena.actors.values() if a.alive and (a.camp==self.camp)==allied
                and (allied or a.is_area_targetable()) and math.dist(center,a.position_at(now))<=radius]

    def _inspire(self, now):
        packets = self._buff(382122,now)+self._buff(382123,now)
        for target in self._near(self.position_at(now),432,now,allied=True):
            packets.extend(self._buff(382121,now,target.id))
        return packets

    def _mark(self, target, now):
        packets = []
        for template in (382111,382112,382113):
            packets.extend(self._buff(template,now,target.id))
        return packets

    def _impact(self, target, power, ratio, now):
        missing = target.max_hp-target.hp
        packets,lost = self.damage(power,now,target=target,school='energy')
        if target.alive and ratio:
            more,extra = self.damage(missing*ratio,now,target=target,school='true')
            packets.extend(more)
            lost = lost or extra
        if lost:
            packets.extend(self._mark(target,now))
        return packets

    def _object(self, template, pos, lifetime, now):
        ident,packet = self.add_object(template,pos)
        self._queue(now+lifetime,'object_expire',ident)
        return [packet]

    def interrupt(self, now):
        packets = []
        if self.ready:
            self.ready = None
            self.cooldowns[2] = now+self.skill_cooldown(8000, 2)
            packets.extend(((1583,struct.pack('<II',self.id,382301)),self._cooldown(2)))
            packets.extend(self.remove_buff(382322,now))
        if not self.alive and self.temple:
            packets.extend(self._end_temple(now))
        return packets+self.sync_speed(now)

    def update(self, now):
        packets = []
        if self.ready and self.skill_sealed(2,now):
            packets.extend(self.interrupt(now))
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count = min(2,self.e_count+1)
            self.e_next_charge = self.e_next_charge+self.skill_cooldown(6000) if self.e_count<2 else 0
            packets.append(self._cooldown(1))
        return packets+super().update(now)

    def _end_temple(self, now):
        cast,self.temple = self.temple,None
        if not cast:
            return []
        self.cooldowns[2] = now+self.skill_cooldown(30000, 2)
        packets = []
        for template in (382301,382302,382303,382304):
            packets.extend(self.remove_buff(template,now))
        packets.extend(self._buff(382331,now))
        return packets+[self._cooldown(2)]

    def _pull(self, target, center, now):
        current = target.position_at(now)
        if current==center or target.cc_immune(now):
            return []
        # A pulse can catch a wall-crossing dash before its legal endpoint.
        # Resolve the old motion before interrupt() discards its safe origin.
        start = target.stop_position(now)
        distance = math.dist(start,center)
        dest = point_at(start,center,min(1,120/distance)) if distance else start
        if start!=current:
            target.position,target.motion = start,None
        packets = target.interrupt(now)
        if start!=current:
            packets.append(stop_move(target.scene_id,target.id,start))
        duration = target._set_motion(start,dest,360,now,kind=1)
        target.forced_until = now+duration
        return packets+[scene(moves=(self._move_event(target.motion[1],360,1,target.id),))]

    def _pulse(self, cast, index, now):
        center = self.position_at(now)
        packets = []
        for target in self._near(center,432,now,allied=True):
            packets.extend(target.cleanse(now))
            packets.extend(self._buff(382121,now,target.id))
            packets.extend(target.restore_hp(cast['max_hp']*D('.1' if index==1 else '.05'),now))
        for target in self._near(center,432,now):
            more,lost = self.damage((target.max_hp-target.hp)*D('.1' if index==1 else '.05'),now,
                                   target=target,school='true')
            packets.extend(more)
            if self.arena.pk and self.arena.pk['finished']:
                return packets
            if lost:
                packets.extend(self._mark(target,now))
            for template in (382605,382606,382607,382608):
                packets.extend(self._buff(template,now,target.id))
            if target.alive:
                packets.extend(self._pull(target,center,now))
        return packets

    def _flight(self, flight, now):
        if flight['template']==382100:
            return super()._flight(flight,now)
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        contacts = []
        for target in self.arena.actors.values():
            if target.alive and target.camp!=self.camp and not target.is_untargetable():
                hit = actor_contact(start,end,target,previous,now,72)
                if hit is not None:
                    contacts.append((hit,target.id))
        if contacts:
            hit,ident = min(contacts)
            if self.projectile_blocked(self.arena.actors[ident],now):
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            center = tuple(round(x) for x in point_at(start,end,hit))
            packets = self._object(382201,center,380,now)
            for target in self._near(center,168,now):
                packets.extend(self._impact(target,flight['power'],D('.05'),now))
                packets.extend(self._buff(382213,now,target.id)+self._buff(382214,now,target.id))
            return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if now>=finish:
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return []

    def _event(self, now, kind, data):
        if kind=='hikari_eye':
            cast, = data
            packets = self._object(382402,cast['pos'],550,now)
            for target in self._near(cast['pos'],168,now):
                packets.extend(self._impact(target,cast['power'],D(0),now))
                packets.extend(self._buff(382412,now,target.id))
                if target.alive and target.has_buff(382412,now):
                    mark = dict(target=target.id,target_generation=target.generation,
                                version=target.buff_versions[382412])
                    for index in (1,2,3):
                        self._queue(now+1500*index,'hikari_eye_tick',mark)
            return packets
        if kind=='hikari_eye_tick':
            mark, = data
            target = self.arena.actors[mark['target']]
            if (not target.alive or target.generation!=mark['target_generation']
                    or not target.has_buff(382412,now) or target.buff_versions.get(382412)!=mark['version']):
                return []
            packets,lost = self.damage((target.max_hp-target.hp)*D('.05'),now,target=target,school='true',periodic=True)
            if lost:
                packets.extend(self._mark(target,now))
            return packets+self._buff(382422,now,target.id)
        if kind=='hikari_ready':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            if self.skill_sealed(2,now):
                return self.interrupt(now)
            self.ready,self.temple = None,cast
            packets = self.sync_speed(now)
            packets.append(scene(skills=(self._skill_event(382301,self.position_at(now),self.position_at(now),self.id),)))
            for template in (382301,382302,382303,382304):
                packets.extend(self._buff(template,now))
            packets.extend(self._pulse(cast,1,now))
            if self.arena.pk and self.arena.pk['finished']:
                return packets
            self._queue(now+1500,'hikari_pulse',cast,2)
            return packets
        if kind=='hikari_pulse':
            cast,index = data
            if self.temple is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            packets = self._pulse(cast,index,now)
            if self.arena.pk and self.arena.pk['finished']:
                return packets
            if index==3:
                return packets+self._end_temple(now)
            self._queue(now+1500,'hikari_pulse',cast,index+1)
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if (slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now)
                or self.cooldowns[slot]>now or slot==1 and not self.e_count or slot==2 and self.temple):
            return []
        if slot!=2 and (not self._inside(dest) or start==dest):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:3000,2:30000,10:8000}[slot], slot)
        packets = self._inspire(now) if slot else []
        handoff = []
        if slot in (0,1):
            if slot==1:
                self.e_count -= 1
                if not self.e_next_charge:
                    self.e_next_charge = now+self.skill_cooldown(6000)
            packets.extend(self.shoot(SLOTS[slot],start,dest,now,power,school='energy',basic=slot==0,
                                      power=power,through_walls=slot==1))
        elif slot==10:
            if math.dist(start,dest)>600:
                dest = tuple(round(x) for x in point_at(start,dest,600/math.dist(start,dest)))
            packets.extend(self._object(382401,dest,750,now))
            self._queue(now+750,'hikari_eye',dict(pos=dest,power=power))
        else:
            body,handoff = prepare_displacement(self,now,interrupt=False)
            if not handoff: body = start
            self.ready = dict(slot=2,dest=start,generation=self.generation,max_hp=self.max_hp)
            self.position,self.motion = body,None
            for target in self._near(start,432,now):
                packets.extend(self._buff(382321,now,target.id))
            packets.extend(self._buff(382322,now))
            packets.append(scene(skills=(self._skill_event(382301,start,start,self.id,ready=1),)))
            packets.extend(self.sync_speed(now))
            self._queue(now+1000,'hikari_ready',self.ready)
        return packets+[self._cooldown(slot)]+handoff
