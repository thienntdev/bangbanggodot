"""Magneto's original kit, with the explicitly approved global storm policy."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_geometry import rect_contact
from combat_protocol import props, scene
from melee_common import enemies, prepare_displacement

SLOTS = {0:372100, 1:372201, 2:372301, 10:372401}


class MagnetoActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready = None

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,-1,self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.ready = None
        return self._buff(372101,now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def interrupt(self,now):
        if not self.ready:return []
        self.ready = None
        return [(1583,struct.pack('<II',self.id,372401))]+self.sync_speed(now)

    def update(self,now):
        packets = self.interrupt(now) if self.ready and self.skill_sealed(10,now) else []
        return packets+super().update(now)

    def _skill_hit(self,target,raw,now,generation,school='energy'):
        packets,hit = self.damage(raw,now,target=target,school=school,source_generation=generation)
        if self.arena.pk and self.arena.pk['finished']:return packets
        if hit and self.alive and self.generation==generation:
            packets += self._buff(372102,now)+self._buff(372103,now)
        return packets

    def _area_targets(self,pos,radius,now):
        return [a for a in enemies(self,area=True) if math.dist(pos,a.position_at(now))<=radius
                and rect_contact(pos,a.position_at(now),self.arena.water_rects(now),0) is None]

    def _object(self,template,pos,now,duration):
        ident,packet = self.add_object(template,pos)
        self._queue(now+duration,'object_expire',ident)
        return [packet]

    def _event(self,now,kind,data):
        if kind=='magneto_visual_remove':
            # Presentation-only native prop372403 has its SWF on ITEM_REMOVE.
            # It does not own either R damage pulse or the extra paired hit.
            return self.remove_object(data[0],destroyed=True)
        if kind=='magneto_e_lift':
            cast, = data
            targets = self._area_targets(cast['pos'],108,now)
            cast['targets'] = [(a.id,a.generation) for a in targets]
            cast['lifted'] = set()
            packets = []
            for target in targets:
                packets += self._buff(372202,now,target.id)
                if self.arena.pk and self.arena.pk['finished']:return packets
                if target.has_buff(372202,now):
                    cast['lifted'].add((target.id,target.generation))
                    packets += self._buff(372204,now,target.id,duration=1500)
            self._queue(now+1500,'magneto_e_land',cast)
            return packets
        if kind=='magneto_e_land':
            cast, = data
            lifted = [self.arena.actors.get(i) for i,g in cast['targets']
                      if self.arena.actors.get(i) and self.arena.actors[i].alive and self.arena.actors[i].generation==g]
            direct = {(a.id,a.generation) for a in lifted}
            victims = {a.id:a for a in lifted}
            packets = []
            for target in lifted:
                if (target.id,target.generation) not in cast['lifted']:continue
                pos = target.position_at(now)
                packets += self._buff(372206,now,target.id)+self._object(372209,pos,now,400)
                for other in self._area_targets(pos,108,now):
                    if not other.info.get('npc_template'):victims[other.id] = other
            for target in victims.values():
                packets += self._skill_hit(target,cast['power']*D('1.9'),now,cast['generation'])
                if self.arena.pk and self.arena.pk['finished']:return packets
                if (target.id,target.generation) not in direct:packets += self._buff(372207,now,target.id)
            return packets
        if kind=='magneto_r_ready':
            cast, = data
            if self.ready is not cast:return []
            if not self.alive or self.skill_sealed(10,now):return self.interrupt(now)
            self.ready = None
            packets = self.sync_speed(now)+[scene(skills=(self._skill_event(372401,self.position_at(now),cast['pos']),))]
            # Effect372401 -> 372402 -> 372403 also creates the visual prop.
            # PropsTemplate372403 defines its 100ms delay before the native
            # movie begins; blank gameplay props372401/372402 cannot render it.
            visual,packet = self.add_object(372403,cast['pos'])
            packets.append(packet)
            self._queue(now+100,'magneto_visual_remove',visual)
            for template,delay in ((372401,700),(372402,1300)):
                packets += self._object(template,cast['pos'],now,delay)
                self._queue(now+delay,'magneto_r_hit',cast,template)
            return packets
        if kind=='magneto_r_hit':
            cast,template = data
            packets = []
            for target in self._area_targets(cast['pos'],144,now):
                key = target.id,target.generation
                packets += self._skill_hit(target,cast['power']*D('1.24' if template==372401 else '1.83'),now,cast['generation'])
                if self.arena.pk and self.arena.pk['finished']:return packets
                if template==372401:cast['hits'].add(key)
                elif key in cast['hits']:
                    packets += self._skill_hit(target,target.max_hp*D('.1'),now,cast['generation'],'true')
                    if self.arena.pk and self.arena.pk['finished']:return packets
            return packets
        if kind=='magneto_storm':
            cast,tick = data
            if not self.alive or self.generation!=cast['generation']:return []
            # User explicitly retains map-wide hits on invisible tanks. Stasis
            # and actual absence remain protection, not a hidden radar for AI.
            targets = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                       and not a.info.get('npc_template') and not a.in_stasis()
                       and (not a.info.get('untargetable',False) or 26 in a.buff_types(now))]
            close = [a for a in targets if math.dist(self.position_at(now),a.position_at(now))<=360]
            enhanced = self.arena.rng.choice(close) if close else None
            packets = []
            for target in targets:
                packets += self._skill_hit(target,cast['power']*D('1.5' if target is enhanced else '.25'),now,cast['generation'])
                if self.arena.pk and self.arena.pk['finished']:return packets
                packets += self._buff((372316 if target is enhanced else 372306)+(tick-1)%3,now,target.id)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if self.arena.pk and self.arena.pk['finished']:return []
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot in (0,1,10) and (not self._inside(dest) or slot==0 and start==dest):return []
        if slot in (1,10) and math.dist(start,dest)>600:return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+(self.fire_interval(now) if slot==0 else self.skill_cooldown({1:8000,2:30000,10:6000}[slot],slot))
        packets = [self._cooldown(slot)]
        if slot==0:return packets+self.shoot(372100,start,dest,now,power,school='energy',basic=True)
        cast = dict(pos=dest,dest=dest,slot=slot,power=power,generation=self.generation,hits=set())
        if slot==10:
            start,pre = prepare_displacement(self,now,interrupt=False)
            packets += pre
            self.position,self.motion = start,None
            self.ready = cast
            self._queue(now+300,'magneto_r_ready',cast)
            return packets+[scene(skills=(self._skill_event(372401,start,dest,ready=1),))]+self.sync_speed(now)
        packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,dest),)))
        if slot==1:
            packets += self._object(372201,dest,now,700)
            self._queue(now+700,'magneto_e_lift',cast)
        else:
            packets += self._buff(372301,now)+self._buff(372302,now)
            for tick in range(1,9):self._queue(now+750*tick,'magneto_storm',cast,tick)
        return packets
