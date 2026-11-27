"""Gilgamesh: ten field ticks and forty individually colliding weapons."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import props, scene
from melee_common import enemies, piercing_step

SLOTS = {0:362100,1:362201,2:362301,10:362401}
SPACE_BUFFS = (362302,362303,362304,362305)


class GilgameshActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.fields = {}
        self.marks = {}
        self.sweep = None

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.marks = {}
        return self._buff(362101,now)+self._buff(362102,now)

    def cc_immune(self,now,*,slow=False):
        return bool(self.sweep and now<self.sweep['begin']) or super().cc_immune(now,slow=slow)

    def _end_sweep(self,now):
        self.sweep = None
        packets = []
        for template in SPACE_BUFFS:
            if (self.id,template) in self.active_buffs:
                packets.extend(self.remove_buff(template,now))
        return packets

    def interrupt(self,now):
        return self._end_sweep(now) if not self.alive or self.sweep and now>=self.sweep['begin'] else []

    def update(self,now):
        packets = super().update(now)
        if self.sweep and now>=self.sweep['begin'] and self.skill_sealed(2,now):
            packets.extend(self._end_sweep(now))
        return packets

    def on_target_death(self,target,now):
        self.marks.pop(target.id,None)
        return []

    def _hit(self,target,raw,generation,now,*,periodic=False):
        packets,lost = self.damage(raw,now,target=target,school='energy',periodic=periodic)
        if not lost or not target.alive or not self.alive or self.generation!=generation:
            return packets
        mark = self.marks.get(target.id)
        valid = (mark and mark['target_generation']==target.generation
                 and target.has_buff(362103,now)
                 and target.buff_versions.get(362103)==mark['version'])
        hits = [h for h in mark['hits'] if h['begin']>=now-2000] if valid else []
        hits.append(dict(begin=now))
        if len(hits)>=7:
            self.marks.pop(target.id,None)
            packets.extend(target.remove_buff(362103,now))
            packets.extend(self._buff(362107,now,target.id,duration=2000))
            ident,packet = self.add_object(362403,target.position_at(now))
            self._queue(now+500,'object_expire',ident)
            return packets+[packet]
        packets.extend(self._buff(362103,now,target.id))
        if target.has_buff(362103,now):
            self.marks[target.id] = dict(hits=hits,target_generation=target.generation,
                                        version=target.buff_versions[362103])
        return packets

    def _flight(self,flight,now):
        if flight['template']!=362501:
            return super()._flight(flight,now)
        return piercing_step(self,flight,now,
            lambda f,t,n:self._hit(t,f['raw'],f['source_generation'],n),pierce=False)

    def _event(self,now,kind,data):
        if kind=='gil_field':
            field,index = data
            if self.fields.get(field['id']) is not field:
                return []
            packets = []
            for target in enemies(self,area=True):
                if math.dist(field['pos'],target.position_at(now))<=144:
                    packets.extend(self._hit(target,field['power']*D('.6'),field['generation'],now,periodic=True))
                    packets.extend(self._buff(362203,now,target.id,stacks=1))
            if index==10:
                self.fields.pop(field['id'])
                packets.extend(self.remove_object(field['id']))
            else:
                self._queue(now+300,kind,field,index+1)
            return packets
        if kind=='gil_weapon':
            cast,index = data
            if self.sweep is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            if self.skill_sealed(2,now):
                return self._end_sweep(now)
            x,y = self.position_at(now)
            dx,dy = cast['direction']
            offset = self.arena.rng.uniform(-48,48)
            start = round(x-dy*offset),round(y+dx*offset)
            dest = round(start[0]+dx*840),round(start[1]+dy*840)
            packets = self.shoot(362501,start,dest,now,self.combat_stat('iEgAtk',now)*D('.72'),
                                 school='energy',through_walls=True)
            if index<39:
                self._queue(now+100,kind,cast,index+1)
            else:
                packets.extend(self._end_sweep(now))
            return packets
        if kind=='gil_sweep_end':
            return self._end_sweep(now) if self.sweep is data[0] else []
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot in (0,2) and start==dest or slot==1 and (not self._inside(dest) or math.dist(start,dest)>600):
            return []
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:8000}[slot], slot)
        if slot==0:
            packets = self.shoot(362100,start,dest,now,self.combat_stat('iEgAtk',now),school='energy',basic=True)
        elif slot==1:
            ident,packet = self.add_object(362201,dest)
            field = dict(id=ident,pos=dest,power=self.combat_stat('iEgAtk',now),generation=self.generation,end=now+3000)
            self.fields[ident] = field
            self._queue(now+300,'gil_field',field,1)
            packets = [scene(skills=(self._skill_event(362201,start,dest),)),packet]
        elif slot==2:
            length = math.dist(start,dest)
            cast = dict(begin=now+300,end=now+4300,generation=self.generation,
                        direction=((dest[0]-start[0])/length,(dest[1]-start[1])/length))
            self.sweep = cast
            self._queue(now+400,'gil_weapon',cast,0)
            packets = [scene(skills=(self._skill_event(362301,start,dest,ready=1),))]
            for template in SPACE_BUFFS:
                packets.extend(self._buff(template,now))
        else:
            packets = [scene(skills=(self._skill_event(362401,start,start),))]
            packets.extend(self._buff(362401,now)+self._buff(362403,now))
            packets.extend(self.add_shield(362402,self.max_hp*D('.2'),now))
        return packets+[self._cooldown(slot)]
