"""Dark Knight: ending-based stealth cooldown, five darts and versioned poison."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_math import D
from combat_protocol import props, scene
from melee_common import aimed, enemies, in_cone, piercing_step, prepare_displacement

SLOTS = {0:305100, 1:305201, 2:305301, 10:305401}


class DarkKnightActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.channel = None
        self.poisons = {}
        self.impact_pen = None

    def attr_bonus(self, attributes, now):
        value = super().attr_bonus(attributes,now)
        if 34 in attributes:
            value += self.impact_pen if self.impact_pen is not None else D('.25') if self.has_buff(305201,now) else D(0)
        return value

    def _deal(self, raw, target, now, pen, **kwargs):
        self.impact_pen = pen
        try:return self.damage(raw,now,target=target,**kwargs)[0]
        finally:self.impact_pen = None

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def is_untargetable(self):
        now = getattr(self.arena,'event_now',None) or self.clock()
        return super().is_untargetable() or (self.has_buff(305202,now) and 32 not in self.buff_types(now))

    def remove_buff(self, template, now, *, expired=False):
        existed = (self.id,template) in self.active_buffs
        packets = super().remove_buff(template,now,expired=expired)
        if template == 305202 and existed:
            for other in (305201,305203,305204,305205):
                packets.extend(super().remove_buff(other,now))
            self.cooldowns[1] = now+self.skill_cooldown(8000, 1)
            packets.append(self._cooldown(1))
        return packets

    def on_damage(self, source, hit, now, school, reflected, attacker_ap):
        return self.remove_buff(305202,now) if hit.hp_loss else []

    def interrupt(self, now):
        packets = []
        if self.channel:
            self.channel = None
            packets.append((1583,struct.pack('<II',self.id,305401)))
            for template in (305401,305402,305403,305404):
                packets.extend(self.remove_buff(template,now))
        if not self.alive:
            packets.extend(self.remove_buff(305202,now))
        return packets

    def on_control(self, source, template, now):
        kind = int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType'])
        return self.interrupt(now) if kind in (30,35,66) else []

    def _poison(self, target, now, generation, pen=0):
        if not target.alive or target.reject_buff({'nEffectType':'60'},self,now):return []
        key = target.id,target.generation
        dot = self.poisons.get(key)
        valid = dot and dot['end']>now and target.buff_versions.get(dot['buff'])==dot['version']
        count = min(3,dot['count']+1) if valid else 1
        packets = []
        for template in (305100,305101,305102):
            if target.buff_sources.get(template)==self.id:
                packets.extend(target.remove_buff(template,now))
        template = 305099+count
        packets.extend(self._buff(template,now,target.id))
        if not target.has_buff(template,now):return packets
        if not valid:
            dot = dict(target=target.id,target_generation=target.generation,generation=generation)
            self.poisons[key] = dot
            self._queue(now+1000,'dark_poison',dot)
        dot.update(end=now+3000,count=count,buff=template,version=target.buff_versions[template],pen=pen)
        # One 30% healing reduction pool; no generic attribute21/shield penalty.
        packets.extend(self._buff(305112,now,target.id))
        return packets

    def _dart_hit(self, flight, target, now):
        raw = flight['raw']*D('.5')**(len(flight['hits'])-1)
        pen = flight['context']['pen']
        packets = self._deal(raw,target,now,pen,basic=True)
        return packets+self._poison(target,now,flight['source_generation'],pen)

    def _flight(self, flight, now):
        if flight['template']==305411:
            return piercing_step(self,flight,now,self._dart_hit)
        if flight['template']==305100:
            return piercing_step(self,flight,now,self._dart_hit,pierce=False)
        return super()._flight(flight,now)

    def _event(self, now, kind, data):
        if kind=='dark_poison':
            dot, = data
            key = dot['target'],dot['target_generation']
            target = self.arena.actors.get(dot['target'])
            if (self.poisons.get(key) is not dot or not target or not target.alive
                    or target.generation!=dot['target_generation']
                    or target.buff_versions.get(dot['buff'])!=dot['version'] or now>dot['end']):
                if self.poisons.get(key) is dot:self.poisons.pop(key,None)
                return []
            packets = self._deal(target.max_hp*D('.01')*dot['count'],target,now,dot['pen'],periodic=True)
            if now<dot['end']:self._queue(now+1000,kind,dot)
            else:self.poisons.pop(key,None)
            return packets
        if kind=='dark_space_tick':
            cast,index = data
            target = self.arena.actors.get(cast['target'])
            if (not target or not target.alive or target.generation!=cast['target_generation']
                    or target.buff_versions.get(305301)!=cast['version']):return []
            packets = self._deal(cast['power']*D('.9'),target,now,cast['pen'],periodic=True)
            if index<5:self._queue(now+1000,kind,cast,index+1)
            return packets
        if kind=='dark_dart':
            cast,index = data
            if self.channel is not cast or not self.alive:return []
            pos = self.position_at(now)
            dest = pos[0]+cast['vector'][0],pos[1]+cast['vector'][1]
            packets = self.shoot(305411,pos,dest,now,cast['power'],school='physical',basic=True,through_walls=True,context=dict(pen=cast['pen']))
            if index<5:self._queue(now+200,kind,cast,index+1)
            return packets
        if kind=='dark_channel_end':
            if self.channel is data[0]:return self.interrupt(now)
            return []
        if kind=='dark_warning':
            generation,index = data
            if self.generation!=generation or not self.has_buff(305202,now):return []
            packets = [scene(skills=(self._skill_event(305221,self.position_at(now),self.position_at(now)),))]
            for target in enemies(self):
                if math.dist(self.position_at(now),target.position_at(now))<=480:
                    packets.extend(self._buff(305221,now,target.id))
            if index<4:self._queue(now+1000,kind,generation,index+1)
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if self.channel and slot in (0,2,10) or slot in (0,2,10) and start==dest:return []
        pen = D('.25') if self.has_buff(305201,now) else D(0)
        packets = self.remove_buff(305202,now) if slot!=1 else []
        power = self.combat_stat('iAttack',now)
        if slot==1:
            self.cooldowns[1] = 2**63-1
            for template in (305201,305202,305203,305204,305205):packets.extend(self._buff(template,now))
            self._queue(now+1000,'dark_warning',self.generation,1)
        else:
            self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),2:25000,10:6000}[slot], slot)
        if slot==0:
            packets.extend(self.shoot(305100,start,dest,now,power*D('1.5'),school='physical',basic=True,speed_multiplier=1.5,context=dict(pen=pen)))
        elif slot==10:
            self.channel = dict(vector=(dest[0]-start[0],dest[1]-start[1]),power=power,pen=pen,end=now+1000)
            for template in (305401,305402,305403,305404):packets.extend(self._buff(template,now))
            self._queue(now+50,'dark_dart',self.channel,1)
            self._queue(now+1000,'dark_channel_end',self.channel)
        elif slot==2:
            for target in enemies(self,area=True):
                # Approved building exception: summon towers only. Water-wall
                # blocks are scene objects; ghosts/clones remain valid targets.
                if target.info.get('npc_template') in (20006,20017) or not in_cone(target.position_at(now),start,dest,240,90):continue
                packets.extend(self._buff(305301,now,target.id))
                if not target.has_buff(305301,now):continue
                for template in (305313,305314):packets.extend(self._buff(template,now,target.id))
                cast = dict(target=target.id,target_generation=target.generation,generation=self.generation,
                            power=power,pen=pen,version=target.buff_versions[305301])
                self._queue(now+1000,'dark_space_tick',cast,1)
                packets.extend(self._poison(target,now,self.generation,pen))
            end = aimed(start,(2*start[0]-dest[0],2*start[1]-dest[1]),192,fixed=True)
            origin,stopped = prepare_displacement(self,now,interrupt=False)
            origin = origin if stopped else start
            duration = self._set_motion(origin,end,960,now,4)
            self.forced_until = now+duration
            packets.extend(stopped)
            packets.append(scene(moves=(self._move_event(self.motion[1],960,4),)))
        if slot!=0:packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,dest),)))
        return packets+[self._cooldown(slot)]
