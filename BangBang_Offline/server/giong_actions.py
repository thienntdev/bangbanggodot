"""Thanh Giong: shot-count replacement, radial bamboo and interceptable homing."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:317100, 1:317201, 2:317301, 10:317401}


class GiongActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.shot_count = self.enhanced_count = 0
        self.ready = None

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,-1,self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self, now):
        self.shot_count = self.enhanced_count = 0
        return self._buff(317101,now)

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None

    def interrupt(self, now):
        cast,self.ready = self.ready,None
        if cast is None:
            return []
        packets = [(1583,struct.pack('<II',self.id,SLOTS[cast['slot']]))]
        if cast['slot']==2:
            self.cooldowns[2] = now+self.skill_cooldown(6000, 2)
            packets.append(self._cooldown(2))
        return packets

    def _bamboo(self, pos, power, now, primary):
        packets = []
        for target in list(self.arena.actors.values()):
            if not target.alive or target.camp==self.camp:
                continue
            distance = math.dist(pos,target.position_at(now))
            if distance<=144:
                ratio = D('2.5')-D('1.25')*D(str(distance))/144
                packets.extend(self.damage(power*ratio,now,target=target,school='physical',basic=True)[0])
        if primary is not None:
            packets.extend(self._buff(317103,now,primary.id))
        return packets

    def _space_blast(self, flight, pos, now):
        packets = []
        # Each victim's missing HP is captured before either damage component.
        targets = [(a,a.max_hp-a.hp) for a in self.arena.actors.values()
                   if a.alive and a.camp!=self.camp and math.dist(pos,a.position_at(now))<=168]
        for target,missing in targets:
            locked = target.id==flight['target'] and target.generation==flight['target_generation']
            packets.extend(self.damage(flight['power']*(3 if locked else 2),now,target=target,school='physical')[0])
            # User kept V1; unresolved Effect317302 cap is intentionally not guessed.
            packets.extend(self.damage(missing*D('.2'),now,target=target,school='true')[0])
            packets.extend(self._buff(317304,now,target.id))
        return packets

    def _event(self, now, kind, data):
        if kind=='bamboo_ready':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            target = self.arena.actors.get(cast.get('target'))
            if cast['slot']==2 and (target is None or not target.alive or target.generation!=cast['target_generation']):
                return self.interrupt(now)
            self.ready = None
            return self.shoot(SLOTS[cast['slot']],self.position_at(now),
                              target.position_at(now) if target else cast['dest'],now,cast['power'],
                              school='physical',basic=cast['slot']==10,target=target,
                              speed_multiplier=1.5 if cast['slot']==10 else 1,power=cast['power'],through_walls=True)
        return super()._event(now,kind,data)

    def on_target_death(self, target, now):
        return self.interrupt(now) if self.ready and self.ready.get('target')==target.id else []

    def _flight(self, flight, now):
        template = flight['template']
        if template not in (317100,317102,317201,317301,317401):
            return super()._flight(flight,now)
        previous = flight['previous']
        packets = []
        homing = template==317301
        if homing:
            target = self.arena.actors.get(flight['target'])
            if target is None or not target.alive or target.generation!=flight['target_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start,dest = flight['pos'],target.position_at(now)
            end = point_at(start,dest,min(1,flight['speed']*(now-previous)/1000/max(1,math.dist(start,dest))))
            if dest!=flight['end']:
                packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))))
                flight['end'] = dest
        else:
            begin,finish = flight['begin'],flight['finish']
            start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
            end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        contacts = []
        for target in self.arena.actors.values():
            key = target.id,target.generation
            if target.alive and target.camp!=self.camp and key not in flight['hits']:
                hit = actor_contact(start,end,target,previous,now,72 if template==317201 else 36)
                if hit is not None:
                    contacts.append((hit,target.id))
        wall = self.arena.geometry.wall_contact(start,end) if not flight['through_walls'] else None
        for contact,ident in sorted(contacts):
            if wall is not None and contact>=wall:
                break
            target = self.arena.actors[ident]
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['hits'].add((target.id,target.generation))
            if template==317100:
                packets.extend(self.damage(flight['raw'],now,target=target,school='physical',basic=True)[0])
                return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
            if template==317201:
                packets.extend(self.damage(flight['power']*D('2.15'),now,target=target,school='physical')[0])
                packets.extend(self._buff(317211,now,target.id))
            else:
                pos = target.position_at(now)
                packets.extend(self._space_blast(flight,pos,now) if homing else self._bamboo(pos,flight['power'],now,target))
                return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if wall is not None:
            # Base third-shot bamboo stops at walls like other normal attacks;
            # no enemy contact means no on-hit explosion.
            return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if now>=flight['finish']:
            return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['pos'],flight['previous'] = end,now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or start==dest:
            return []
        target = self.arena.actors.get(target_id) if slot==2 else None
        if slot==2 and (target is None or not target.alive or target.camp==self.camp
                        or target.is_untargetable() or math.dist(start,target.position_at(now))>960):
            return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:6000}[slot], slot)
        if slot==0:
            self.shot_count = (self.shot_count+1)%3  # User: casts count, even misses; R does not.
            template = 317102 if self.shot_count==0 else 317100
            enhanced = self.enhanced_count>0 and self.has_buff(317402,now)
            packets = self.shoot(template,start,dest,now,power*D('1.5'),school='physical',basic=True,
                                 speed_multiplier=1.5,power=power,range_multiplier=D('1.25') if enhanced else 1)
            if enhanced:
                self.enhanced_count -= 1
                if self.enhanced_count==0:
                    for buff in (317402,317403):
                        packets.extend(self.remove_buff(buff,now))
        elif slot==1:
            packets = self.shoot(317201,start,dest,now,power*D('2.15'),school='physical',power=power,through_walls=True)
        else:
            packets = []
            origin,stopped = prepare_displacement(self,now,interrupt=False,cancel_motion=True)
            if slot==10:
                packets.extend(self.cleanse(now))
                for template in (317401,317402,317403):
                    packets.extend(self._buff(template,now))
                self.enhanced_count = 3
            else:
                packets.extend(self._buff(317311,now,target.id))
            self.ready = dict(slot=slot,dest=dest,power=power,generation=self.generation,
                              target=target.id if target else None,target_generation=target.generation if target else None)
            self.position,self.motion = origin if stopped else start,None
            self._queue(now+(1000 if slot==2 else 50),'bamboo_ready',self.ready)
            packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,target.position_at(now) if target else dest,
                                                           target_id if target else 0,ready=1),)))
            packets.extend(stopped)
        return packets+[self._cooldown(slot)]
