"""Transformer: scoped E/R reactions and charged piercing shots."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:324100,1:324201,2:324301,10:324401}


class TransformerActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready = None
        self.r_count,self.r_next_charge = 2,0

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,self.r_count if slot==10 else -1,
                          self.cooldowns[slot],self.r_next_charge if slot==10 else 0)+struct.pack('<I',self.id)

    def on_spawn(self,now):
        return self._buff(324101,now)

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def interrupt(self,now):
        if not self.ready:
            return []
        slot = self.ready['slot']
        self.ready = None
        return [(1583,struct.pack('<II',self.id,SLOTS[slot]))]+self.sync_speed(now)

    def update(self,now):
        packets = self.interrupt(now) if self.ready and self.skill_sealed(self.ready['slot'],now) else []
        while self.r_next_charge and self.r_next_charge<=now:
            self.r_count = min(2,self.r_count+1)
            self.r_next_charge = self.r_next_charge+self.skill_cooldown(6000) if self.r_count<2 else 0
            packets.append(self._cooldown(10))
        return packets+super().update(now)

    def _passive(self,now,generation):
        if not self.alive or generation!=self.generation:
            return []
        return self._buff(324111,now)+self._buff(324112,now)

    def _reaction(self,target,now,slot,generation):
        other = 324402 if slot==1 else 324203
        if not target.has_buff(other,now) or target.buff_sources.get(other)!=self.id:
            return []
        packets = target.remove_buff(other,now)
        packets.extend(self._buff(324411,now,target.id))
        packets.extend(self.damage(target.max_hp*D('.15'),now,target=target,school='energy')[0])
        # Both directions share Effect324411 -> 324412 -> 324413.
        packets.extend(self._buff(324413,now,target.id))
        return packets

    def _hit(self,target,slot,power,generation,now):
        packets = self.damage(power*D('2.12' if slot==1 else '1.92'),now,target=target,school='energy')[0]
        packets.extend(self._reaction(target,now,slot,generation))
        for buff in ((324202,324203) if slot==1 else (324402,324403,324404)):
            packets.extend(self._buff(buff,now,target.id))
        if slot==10 and self.alive and generation==self.generation:
            self.cooldowns[1] = max(now,self.cooldowns[1]-1200)
            if self.r_next_charge:
                self.r_next_charge = max(now,self.r_next_charge-900)
            packets.extend((self._cooldown(1),self._cooldown(10)))
        return packets+self._passive(now,generation)

    def on_bullet_hit(self,flight,target,now):
        if flight['template']!=324201:
            return []
        packets = []
        pos = target.position_at(now)
        for enemy in list(self.arena.actors.values()):
            if enemy.alive and enemy.camp!=self.camp and math.dist(pos,enemy.position_at(now))<=144:
                packets.extend(self._hit(enemy,1,flight['power'],flight['source_generation'],now))
        return packets

    def _flight(self,flight,now):
        if flight['template']!=324401:
            return super()._flight(flight,now)
        start = point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        contacts = []
        for target in list(self.arena.actors.values()):
            key = target.id,target.generation
            if not target.alive or target.camp==self.camp or key in flight['hits'] or target.is_untargetable():
                continue
            hit = actor_contact(start,end,target,flight['previous'],now,84)
            if hit is not None:
                contacts.append((hit,target.id,target,key))
        packets = []
        for _,_,target,key in sorted(contacts):
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['hits'].add(key)
            packets.extend(self._hit(target,10,flight['power'],flight['source_generation'],now))
        if now>=flight['finish']:
            return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _event(self,now,kind,data):
        if kind=='transformer_ready':
            cast, = data
            if self.ready is not cast or not self.alive:
                return []
            self.ready = None
            start,slot = self.position_at(now),cast['slot']
            packets = [scene(skills=(self._skill_event(SLOTS[slot],start,cast['dest']),))]
            if slot==2:
                ident,packet = self.add_object(324301,cast['dest'])
                cast['id'] = ident
                packets.append(packet)
                self._queue(now+1000,'transformer_beam',cast)
            else:
                packets.extend(self.shoot(SLOTS[slot],start,cast['dest'],now,D(0),
                                          school='energy',through_walls=True,power=cast['power']))
            return packets+self.sync_speed(now)
        if kind=='transformer_beam':
            cast, = data
            # Completed beam: SceneItem324301 declares its impact/finish movie
            # on removal. A cancelled ready phase never creates this object.
            packets = self.remove_object(cast['id'],destroyed=True)
            for target in list(self.arena.actors.values()):
                if not target.alive or target.camp==self.camp or math.dist(cast['dest'],target.position_at(now))>192:
                    continue
                raw = cast['power']*D('2.5')+target.max_hp*D('.15')
                if target.has_buff(324413,now) and target.buff_sources.get(324413)==self.id:
                    raw *= D('1.5')
                packets.extend(self.damage(raw,now,target=target,school='energy')[0])
                packets.extend(self._buff(324313,now,target.id))
                packets.extend(self._passive(now,cast['generation']))
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or slot!=2 and start==dest or slot==10 and not self.r_count:
            return []
        if slot==2 and math.dist(start,dest)>960:
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:20000,10:3000}[slot], slot)
        if slot==0:
            return self.shoot(324100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        if slot==10:
            self.r_count -= 1
            if not self.r_next_charge:
                self.r_next_charge = now+self.skill_cooldown(6000)
        body,stopped = prepare_displacement(self,now,interrupt=False)
        self.position,self.motion = body if stopped else start,None
        self.ready = dict(slot=slot,dest=dest,power=power,generation=self.generation)
        self._queue(now+100,'transformer_ready',self.ready)
        # Shared sync_speed installs the native lock and stops the old tween.
        return [self._cooldown(slot),scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),))]+self.sync_speed(now)+stopped
