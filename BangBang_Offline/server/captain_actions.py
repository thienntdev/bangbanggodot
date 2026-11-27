"""Captain base kit; charge refund and R duration are user-approved overrides."""
import math
import struct
from dataclasses import replace

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D, quantize
from combat_protocol import props, scene

SLOTS = {0:323100, 1:323201, 2:323301, 10:323401}


class CaptainActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.e_count, self.e_next_charge = 2, 0
        self.ready = None

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,self.e_count if slot==1 else -1,
                          self.cooldowns[slot],self.e_next_charge if slot==1 else 0)+struct.pack('<I',self.id)

    def on_spawn(self, now):
        self._queue(now,'command_aura',self.generation)
        return self._buff(323101,now)

    def _allies(self, now, radius):
        return [a for a in self.arena.actors.values() if a.alive and a.camp==self.camp
                and not a.info.get('map_object') and not a.info.get('cow_object') and not a.info.get('totem')
                and math.dist(self.position_at(now),a.position_at(now))<=radius]

    def _inspire(self, now):
        packets = []
        for target in self._allies(now,480):
            for template in (323121,323122):
                packets.extend(self._buff(template,now,target.id,refresh=True))
        return packets

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None

    def interrupt(self, now):
        if self.ready is None:
            return []
        self.ready = None
        self.cooldowns[2] = now+self.skill_cooldown(10000, 2)
        return [(1583,struct.pack('<II',self.id,323301)),self._cooldown(2)]

    def update(self, now):
        packets = super().update(now)
        if self.e_next_charge and now>=self.e_next_charge:
            while self.e_count<2 and now>=self.e_next_charge:
                self.e_count += 1
                self.e_next_charge += self.skill_cooldown(8000)
            if self.e_count==2:
                self.e_next_charge = 0
            packets.append(self._cooldown(1))
        return packets

    def _event(self, now, kind, data):
        if kind=='command_aura':
            if not self.alive or self.generation!=data[0]:
                return []
            self._queue(now+1000,kind,*data)
            packets = []
            for target in self._allies(now,480):
                for template in (323102,323103,323104):
                    packets.extend(self._buff(template,now,target.id,refresh=True))
            return packets
        if kind=='courage':
            cast, = data
            if self.ready is not cast or not self.alive or cast['generation']!=self.generation:
                return []
            self.ready = None
            start = self.position_at(now)
            packets = [scene(skills=(self._skill_event(323301,start,start,self.id),))]
            for target in self._allies(now,360):
                previous_version = target.buff_versions.get(323301)
                packets.extend(target.add_shield(323301,cast['power']*D('7.2'),now))
                version = target.buff_versions.get(323301)
                if version == previous_version:
                    continue  # Rejected shields have no bonus or new decay timer.
                for template in (323302,323303):
                    packets.extend(self._buff(template,now,target.id))
                for offset in range(500,5001,500):
                    self._queue(now+offset,'shield_decay',target.id,target.generation,version,cast['power']*D('.72'))
            return packets
        if kind=='shield_decay':
            target_id,generation,version,amount = data
            target = self.arena.actors[target_id]
            if not target.alive or target.generation!=generation or target.buff_versions.get(323301)!=version:
                return []
            shield = next((s for s in target.shields if s.shield_id=='323301'),None)
            if shield is None:
                return []
            remaining = quantize(max(D(0),D(shield.remaining)-amount))
            if remaining==0:
                return target.remove_buff(323301,now)+[target.shield_packet(now)]
            target.shields = tuple(replace(s,remaining=remaining) if s is shield else s for s in target.shields)
            return [target.shield_packet(now)]+target.sync_speed(now)
        return super()._event(now,kind,data)

    def _flight(self, flight, now):
        if flight.get('template') not in (323201,323211):
            return super()._flight(flight,now)
        previous = flight['previous']
        returning = flight['template']==323211
        packets = []
        if returning:
            if not self.alive or self.generation!=flight['source_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start,dest = flight['pos'],self.position_at(now)
            distance = math.dist(start,dest)
            end = point_at(start,dest,min(1,flight['speed']*(now-previous)/1000/max(1,distance)))
            if dest!=flight['end']:
                packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(x) for x in (*start,*dest)))))
                flight['end'] = dest
            reached = math.dist(end,dest)<1
            wall = None  # User: both outbound and return pass through walls.
        else:
            start = point_at(flight['start'],flight['end'],(previous-flight['begin'])/(flight['finish']-flight['begin']))
            end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
            wall = None
            reached = wall is not None or now>=flight['finish']
        hits = flight.setdefault('hits',set())
        for target in list(self.arena.actors.values()):
            if not target.alive or target.camp==self.camp or (target.id,target.generation) in hits:
                continue
            hit = actor_contact(start,end,target,previous,now,72)
            if hit is None or wall is not None and hit>=wall:
                continue
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            hits.add((target.id,target.generation))
            packets.extend(self.damage(flight['raw'],now,target=target)[0])
            packets.extend(self._buff(323212 if returning else 323202,now,target.id))
            if returning and self.e_next_charge:
                self.e_next_charge = max(now,self.e_next_charge-1200)
                packets.extend(self.update(now))
                packets.append(self._cooldown(1))
        flight['pos'] = end
        if reached:
            packets.append(scene(expired_bullets=(struct.pack('<I',flight['id']),)))
            if not returning and self.alive and self.generation==flight['source_generation']:
                position = point_at(start,end,max(0,wall-.001)) if wall is not None else end
                position = tuple(round(x) for x in position)
                speed = round(800*float(1+self.attr_bonus((37,),now)))
                dest = self.position_at(now)
                duration = max(1,math.ceil(math.dist(position,dest)*1000/speed))
                ret = dict(flight, id=self._new_id(2),template=323211,start=position,end=dest,pos=position,
                           begin=now,previous=now,finish=now+duration,speed=speed,
                           target=self.id,target_generation=self.generation,raw=flight['power']*D('1.59'),hits=set())
                packets.append(scene(fires=(struct.pack('<IIhhhhhI',ret['id'],self.id,*position,*dest,speed,323211),)))
                self._queue(now+min(20,duration),'flight',ret)
            return packets
        flight['previous'] = now
        # Return follows a moving caster; keep a valid remaining flight snapshot.
        if returning:
            flight['finish'] = now+max(1,math.ceil(math.dist(end,self.position_at(now))*1000/flight['speed']))
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot in (0,1) and (start==dest or not self._inside(dest)) or slot==1 and not self.e_count:
            return []
        target = self.arena.actors.get(target_id)
        if slot==10 and (target is None or not target.alive or target.camp!=self.camp
                         or math.dist(start,target.position_at(now))>600):
            return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:4000,2:30000,10:6000}[slot], slot)
        packets = self._inspire(now) if slot else []
        if slot in (0,1):
            if slot==1:
                self.e_count -= 1
                if not self.e_next_charge:
                    self.e_next_charge = now+self.skill_cooldown(8000)
            packets.extend(self.shoot(SLOTS[slot],start,dest,now,power*(D('.76') if slot else 1),
                                      school='physical',basic=slot==0,power=power))
        elif slot==10:
            packets.append(scene(skills=(self._skill_event(323401,start,target.position_at(now),target.id),)))
            for ally_id in {self.id,target.id}:
                for template in (323401,323402):
                    packets.extend(self._buff(template,now,ally_id,duration=1250))
        else:
            self.ready = dict(slot=2,dest=start,power=power,generation=self.generation)
            self._queue(now+500,'courage',self.ready)
            packets.append(scene(skills=(self._skill_event(323301,start,start,self.id,ready=1),)))
        return packets+[self._cooldown(slot)]
