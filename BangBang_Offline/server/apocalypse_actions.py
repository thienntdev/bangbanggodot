"""Apocalypse: bounded pellet budget, timed bursts and non-lethal recovery."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import aimed, enemies, in_cone, in_strip, piercing_step, prepare_displacement

SLOTS = {0:346100, 1:346201, 2:346301, 10:346401}


class ApocalypseActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.ready = None
        self.burst_count = 0
        self.passive_ready_at = 0

    def _cooldown(self, slot, changed=False):
        body = props(SLOTS[slot], slot, -1, self.cooldowns[slot])
        return (1579, body) if changed and self.id==1 else (1572, body+struct.pack('<I', self.id))

    def on_spawn(self, now):
        self.ready = None
        self.burst_count = self.passive_ready_at = 0
        self._queue(now+3000, 'apoc_reload', self.generation)
        packets = []
        for template in (346101,346102,346103): packets.extend(self._buff(template, now))
        return packets

    def blocked(self, action, now):
        return bool(self.ready) or super().blocked(action, now)

    def _speed(self, now):
        return 0 if self.ready else super()._speed(now)

    def interrupt(self, now):
        packets = []
        if self.ready:
            packets.append((1583, struct.pack('<II', self.id, self.ready['skill'])))
            self.ready = None
        return packets+self.sync_speed(now)

    def on_control(self, source, template, now):
        return self.interrupt(now) if table_row('BuffTemplate_table.xml', nBuffId=template)['nEffectType'] in ('30','35','66') else []

    def on_damage(self, source, hit, now, school, reflected, attacker_ap):
        if not self.alive or hit.hp_loss <= 0 or self.hp >= self.max_hp/2 or now < self.passive_ready_at:
            return []
        # Set the cooldown before healing/cleansing can invoke other hooks.
        self.passive_ready_at = now+30000
        packets = self.cleanse(now)+self._buff(346112, now)+self._buff(346113, now, duration=30000)
        packets.extend(self.restore_hp(self.max_hp*D('.1'), now))
        for tick in range(1,6): self._queue(now+1000*tick, 'apoc_heal', self.generation)
        return packets

    def _pellet(self, flight, target, now):
        cast = flight['context']
        key = target.id, target.generation
        used = cast['budget'].get(key, D(0))
        raw = min(flight['raw'], max(D(0), cast['power']*D('2.5')-used))
        cast['budget'][key] = used+raw
        return self.damage(raw, now, target=target, basic=True)[0]+self._buff(346201, now, target.id)

    def _flight(self, flight, now):
        if flight['template'] == 346401:
            return piercing_step(self, flight, now, self._pellet, pierce=False)
        if flight['template'] != 346301:
            return super()._flight(flight, now)
        start = point_at(flight['start'], flight['end'], (flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end = point_at(flight['start'], flight['end'], min(1, (now-flight['begin'])/(flight['finish']-flight['begin'])))
        contacts = [(h,t.id,t) for t in enemies(self)
                    if (h := actor_contact(start,end,t,flight['previous'],now)) is not None]
        if contacts:
            h, _, target = min(contacts, key=lambda row:row[:2])
            if self.projectile_blocked(target, now):
                return [scene(expired_bullets=(struct.pack('<I', flight['id']),))]
            pos = tuple(round(v) for v in point_at(start,end,h))
            ratio = min(D(1), D(str(math.dist(flight['start'], pos)))/840)
            raw = flight['raw']*(D('2.03')+D('3.15')*ratio)
            ident, packet = self.add_object(346302, pos)
            self._queue(now+2000, 'object_expire', ident)
            packets = [packet, scene(blown_bullets=(struct.pack('<I', flight['id']),))]
            for enemy in enemies(self, area=True):
                if math.dist(pos,enemy.position_at(now)) <= 120:
                    packets.extend(self.damage(raw, now, target=enemy)[0])
                    packets.extend(self._buff(346303, now, enemy.id))
            return packets
        if now >= flight['finish']:
            return [scene(expired_bullets=(struct.pack('<I', flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,flight['finish']), 'flight', flight)
        return []

    def _event(self, now, kind, data):
        if kind == 'apoc_reload':
            if not self.alive or self.generation != data[0]: return []
            self._queue(now+3000, kind, self.generation)
            return self._buff(346121, now)
        if kind == 'apoc_heal':
            return self.restore_hp(self.max_hp*D('.04'), now) if self.alive and self.generation == data[0] else []
        if kind == 'apoc_burst':
            cast, = data
            if not self.alive or self.generation != cast['generation'] or self.blocked('attack',now) or self.skill_sealed(0,now): return []
            start = self.position_at(now)
            dest = start[0]+cast['direction'][0], start[1]+cast['direction'][1]
            return self.shoot(346100, start, dest, now, cast['power']*D('1.5'), school='physical',
                              basic=True, speed_multiplier=1.5, proc=True)
        if kind == 'apoc_cast':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation != cast['generation']: return []
            self.ready = None
            start, dest = self.position_at(now), cast['dest']
            packets = self.sync_speed(now)
            self.burst_count = 2
            packets.extend(self._buff(346131,now)+self._buff(346132,now))
            if cast['slot'] == 1:
                packets.append(scene(skills=(self._skill_event(346201,start,dest),)))
                for target in enemies(self,area=True):
                    if in_strip(target.position_at(now),start,dest,480,72):
                        packets.extend(self.damage(cast['power']*D('1.5'),now,target=target)[0])
                        packets.extend(self._buff(346203,now,target.id))
                packets.extend(self._buff(346204,now))
            elif cast['slot'] == 10:
                for target in enemies(self,area=True):
                    if in_cone(target.position_at(now),start,dest,168,30) and not target.cc_immune(now):
                        pos,stopped = prepare_displacement(target,now,interrupt=False)
                        packets.extend(stopped)
                        pushed = aimed(start,pos,math.dist(start,pos)+240,fixed=True)
                        # BEAT_BACK1 keeps the victim's facing and is forced
                        # on self/remote clients, including checkpoint resume.
                        target._set_motion(pos,target.arena.clip_motion(pos,pushed,now),720,now,kind=1)
                        target.forced_until = target.motion[3]
                        packets.append(scene(moves=(target._move_event(target.motion[1],720,1),)))
                angle = math.atan2(dest[1]-start[1],dest[0]-start[0])
                for degree in (-15,-7.5,0,7.5,15):
                    endpoint = (round(start[0]+600*math.cos(angle+math.radians(degree))),round(start[1]+600*math.sin(angle+math.radians(degree))))
                    packets.extend(self.shoot(346401,start,endpoint,now,cast['power']*D('1.6'),school='physical',basic=True,
                                              through_walls=True,context=cast))
            else:
                packets.extend(self.shoot(346301,start,dest,now,cast['power'],school='physical',through_walls=True))
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or start == dest or self.blocked('attack',now) or self.skill_sealed(slot,now) or now < self.cooldowns[slot]: return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:25000,10:8000}[slot], slot)
        if slot == 0:
            packets = self.shoot(346100,start,dest,now,power*D('1.5'),school='physical',basic=True,speed_multiplier=1.5)
            burst = False
            if self.has_buff(346131,now) and self.burst_count:
                self.burst_count -= 1
                burst = True
                if not self.burst_count: packets.extend(self.remove_buff(346131,now)+self.remove_buff(346132,now))
            elif self.has_buff(346121,now):
                burst = True
                packets.extend(self.remove_buff(346121,now))
            if burst:
                cast = dict(power=power,direction=(dest[0]-start[0],dest[1]-start[1]),generation=self.generation)
                for delay in (100,200): self._queue(now+delay,'apoc_burst',cast)
            return packets+[self._cooldown(0)]
        body,stopped = prepare_displacement(self,now,interrupt=False,cancel_motion=True)
        self.position,self.motion = body if stopped else start,None
        self.ready = dict(slot=slot,skill=SLOTS[slot],dest=dest,power=power,generation=self.generation,budget={})
        self._queue(now+100,'apoc_cast',self.ready)
        return [scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),)),self._cooldown(slot)]+self.sync_speed(now)+stopped
