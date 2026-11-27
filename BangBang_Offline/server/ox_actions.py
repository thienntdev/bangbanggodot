"""Ox King: damage thresholds, shield conversion and a bounded carrying dash."""
from dataclasses import replace
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:378100, 1:378201, 2:378301, 10:378401}


class OxActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.ready = self.dash = None
        self.r_count,self.r_next_charge = 2,0
        self.received = D(0)

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,self.r_count if slot==10 else -1,
                          self.cooldowns[slot],self.r_next_charge if slot==10 else 0)+struct.pack('<I',self.id)

    def on_spawn(self, now):
        self.received = D(0)
        self._queue(now+3000,'ox_periodic',self.generation)
        return self._buff(378111,now)+self._buff(378112,now)+self._buff(378113,now)

    def attr_bonus(self, attributes, now):
        value = super().attr_bonus(attributes,now)
        if self.has_buff(378131,now):
            stacks = self.buff_stacks[378131]
            # User selected V1: +10% energy armor, not native +5% physical.
            if 6 in attributes:
                value -= D('.05')*stacks
            if 7 in attributes:
                value += D('.1')*stacks
        return value

    def _enemies(self, center, radius, now):
        return [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                and a.is_area_targetable() and math.dist(center,a.position_at(now))<=radius]

    def _cry(self, now):
        if not self.alive or self.arena.pk and self.arena.pk['finished']:
            return []
        center = self.position_at(now)
        power = self.combat_stat('iAttack',now)
        packets = [scene(skills=(self._skill_event(378501,center,center,self.id),))]
        packets.extend(self._buff(378131,now)+self._buff(378502,now))
        for target in self._enemies(center,240,now):
            stacks = target.buff_stacks.get(378503,0) if target.has_buff(378503,now) and target.buff_sources.get(378503)==self.id else 0
            packets.extend(self.damage(power*D('.5')*(1+D('.15')*stacks),now,target=target)[0])
            if self.arena.pk and self.arena.pk['finished']:
                return packets
            packets.extend(self._buff(378503,now,target.id)+self._buff(378505,now,target.id))
        return packets

    def on_damage(self, source, hit, now, school, reflected, attacker_ap):
        if not self.alive:
            return []
        self.received += hit.hp_loss  # User excludes damage absorbed by shields.
        packets = []
        threshold = self.max_hp*D('.1')
        while self.received>=threshold and self.alive:
            self.received -= threshold
            packets.extend(self._cry(now))
        return packets

    def _speed(self, now):
        return 0 if self.ready or self.dash else super()._speed(now)

    def blocked(self, action, now):
        return bool(self.ready or self.dash) or super().blocked(action,now)

    def _finish_dash(self, now):
        cast,self.dash = self.dash,None
        if not cast:
            return []
        self.position,self.motion,self.forced_until = self.position_at(now),None,now
        packets = [scene(moves=(self._move_event(self.position,0,5),))]
        finished = self.arena.pk and self.arena.pk['finished']
        for ident,held in cast['held'].items():
            target = self.arena.actors[ident]
            if target.generation==held['generation'] and (target.motion==held['motion']
                    or finished and target.motion is None):
                target.position,target.motion,target.forced_until = target.position_at(now),None,now
                packets.append(scene(moves=(self._move_event(target.position,0,5,target.id),)))
        return packets if finished else packets+self.sync_speed(now)

    def interrupt(self, now):
        packets = []
        if self.ready:
            slot = self.ready['slot']
            self.ready = None
            if slot==2:
                self.cooldowns[slot] = now+self.skill_cooldown(5000, slot)
                packets.append(self._cooldown(slot))
            packets.append((1583,struct.pack('<II',self.id,SLOTS[slot])))
        return packets+self._finish_dash(now)+self.sync_speed(now)

    def update(self, now):
        packets = []
        if self.ready and self.skill_sealed(self.ready['slot'],now):
            packets.extend(self.interrupt(now))
        while self.r_next_charge and self.r_next_charge<=now:
            self.r_count = min(2,self.r_count+1)
            self.r_next_charge = self.r_next_charge+self.skill_cooldown(6000) if self.r_count<2 else 0
            packets.append(self._cooldown(10))
        return packets+super().update(now)

    def _shield(self, now):
        cast = dict(generation=self.generation,version=0,amount=self.max_hp*D('.05'))
        # Queue the fifth conversion before the native shield expiry at 4000.
        for index in range(1,6):
            self._queue(now+800*index,'ox_convert',cast)
        packets = self.add_shield(378202,self.max_hp*D('.25'),now)+self._buff(378203,now)
        cast['version'] = self.buff_versions.get(378202,0)
        return packets

    def _dash_tick(self, cast, now):
        if self.dash is not cast or not self.alive:
            return []
        if not self.motion:
            return self._finish_dash(now)
        start,end = self.position_at(cast['previous']),self.position_at(now)
        packets = []
        # A hit can create a rescue summon. Only actors present at the start
        # of this dash slice participate; a later slice may contact newborns.
        for target in list(self.arena.actors.values()):
            key = target.id,target.generation
            if not target.alive or target.camp==self.camp or target.is_untargetable() or key in cast['hits']:
                continue
            if actor_contact(start,end,target,cast['previous'],now) is None:
                continue
            cast['hits'].add(key)
            if not target.cc_immune(now):
                packets.extend(target.interrupt(now))
                if self.dash is not cast:
                    return packets
                if not self.motion:
                    return packets+self._finish_dash(now)
                target._set_motion(target.position_at(now),self.motion[1],360,now,kind=1)
                target.forced_until = target.motion[3]
                cast['held'][target.id] = dict(generation=target.generation,motion=target.motion)
                packets.append(scene(moves=(self._move_event(target.motion[1],360,1,target.id),)))
            packets.extend(self.damage(cast['power']*D('1.62'),now,target=target)[0])
            # A winning hit freezes all motion synchronously inside damage().
            # Release this cast/its carried actors, without scheduling another
            # dash slice or applying follow-up effects to a finished match.
            if self.arena.pk and self.arena.pk['finished']:
                return packets+self._finish_dash(now)
            packets.extend(self._buff(378213,now,target.id))
            if self.dash is not cast:
                return packets
            if not self.motion:
                return packets+self._finish_dash(now)
        if now>=self.motion[3]:
            return packets+self._finish_dash(now)
        cast['previous'] = now
        self._queue(min(now+20,self.motion[3]),'ox_dash',cast)
        return packets

    def _event(self, now, kind, data):
        if kind=='ox_periodic':
            generation, = data
            if not self.alive or generation!=self.generation:
                return []
            self._queue(now+3000,kind,generation)
            return self._cry(now)
        if kind=='ox_convert':
            cast, = data
            if not self.alive or cast['generation']!=self.generation or self.buff_versions.get(378202)!=cast['version']:
                return []
            shield = next((s for s in self.shields if s.shield_id=='378202' and s.expires_ms>=now),None)
            if not shield:
                return []
            amount = min(shield.remaining,cast['amount'])
            remaining = shield.remaining-amount
            self.shields = tuple(replace(s,remaining=remaining) if s is shield else s for s in self.shields)
            packets = [self.shield_packet(now)]+self.restore_hp(amount,now)
            if not remaining:
                packets.extend(self.remove_buff(378202,now)+self.remove_buff(378203,now))
            return packets
        if kind=='ox_dash':
            return self._dash_tick(data[0],now)
        if kind=='ox_after_cc':
            ident,generation,buff,version,slot = data
            target = self.arena.actors[ident]
            if not target.alive or target.generation!=generation or target.buff_versions.get(buff)!=version:
                return []
            packets = []
            for template in ((378302,378303) if slot==2 else (378411,378412,378413)):
                packets.extend(self._buff(template,now,ident,duration=2500 if slot==2 else 2000))
            return packets
        if kind=='ox_ready':
            cast, = data
            if self.ready is not cast or not self.alive or cast['generation']!=self.generation:
                return []
            if self.skill_sealed(cast['slot'],now):
                return self.interrupt(now)
            self.ready = None
            slot = cast['slot']
            start = self.position_at(now)
            packets = self.sync_speed(now)
            if slot==1:
                dest = point_at(start,cast['dest'],min(1,408/max(1,math.dist(start,cast['dest']))))
                duration = self._set_motion(start,dest,360,now,kind=3)
                self.forced_until = now+duration
                self.dash = dict(cast,previous=now,hits=set(),held={})
                packets.extend(self._shield(now))
                packets.append(scene(moves=(self._move_event(self.motion[1],360,3),)))
                packets.extend(self.sync_speed(now))
                self._queue(min(now+20,self.motion[3]),'ox_dash',self.dash)
                return packets
            packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,cast['dest']),)))
            direction = tuple((b-a)/max(1,math.dist(start,cast['dest'])) for a,b in zip(start,cast['dest']))
            targets = self._enemies(start,math.hypot(720,132) if slot==2 else 240,now)
            for target in targets:
                pos = target.position_at(now)
                delta = tuple(b-a for a,b in zip(start,pos))
                if slot==2 and not (0<=sum(a*b for a,b in zip(delta,direction))<=720
                                   and abs(delta[0]*direction[1]-delta[1]*direction[0])<=96+36):
                    continue
                packets.extend(self.damage(cast['power']*D('3.57' if slot==2 else '1'),now,target=target)[0])
                if self.arena.pk and self.arena.pk['finished']:
                    return packets
                buff = 378304 if slot==2 else 378402
                packets.extend(self._buff(buff,now,target.id))
                if target.has_buff(buff,now):
                    duration = self.active_buffs[(target.id,buff)][1]-now
                    self._queue(now+duration,'ox_after_cc',target.id,target.generation,buff,target.buff_versions[buff],slot)
                    if slot==10 and math.dist(start,pos):
                        dest = point_at(start,pos,1+72/math.dist(start,pos))
                        body,stopped = prepare_displacement(target,now,interrupt=False)
                        packets.extend(stopped)
                        travel = target._set_motion(body,dest,360,now,kind=1)
                        target.forced_until = now+travel
                        packets.append(scene(moves=(self._move_event(target.motion[1],360,1,target.id),)))
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if (slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now)
                or self.cooldowns[slot]>now or slot==10 and not self.r_count):
            return []
        if slot!=10 and (not self._inside(dest) or start==dest):
            return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:3000}[slot], slot)
        if slot==0:
            return self.shoot(378100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(slot)]
        if slot==10:
            self.r_count -= 1
            if not self.r_next_charge:
                self.r_next_charge = now+self.skill_cooldown(6000)
        packets = self._cry(now)
        if not self.alive or self.arena.pk and self.arena.pk['finished']:
            return packets+[self._cooldown(slot)]
        body,handoff = prepare_displacement(self,now,interrupt=False)
        if not handoff: body = start
        self.ready = dict(slot=slot,dest=dest,power=power,generation=self.generation)
        self.position,self.motion = body,None
        self._queue(now+(1000 if slot==2 else 300),'ox_ready',self.ready)
        packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),)))
        return packets+self.sync_speed(now)+[self._cooldown(slot)]+handoff
