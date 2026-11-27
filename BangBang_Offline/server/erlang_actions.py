"""Duong Tien: one travelling dog, three manual Space phases and Q40 marks."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import point_at
from combat_math import D
from combat_protocol import props,scene,move_event
from melee_common import enemies,in_cone,piercing_step

SLOTS={0:361100,1:361201,2:361301,10:361401}


class ErlangActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.dog=self.ready=None
        self.phase=1;self.phase_end=0;self.phase_gap=0

    def _cooldown(self,slot,changed=False):
        skill=SLOTS[slot];end=self.cooldowns[slot]
        if slot==1 and self.dog and self.has_buff(361201,self.clock()):skill,end=361801,0
        if slot==2 and self.phase>1:skill,end={2:361601,3:361701}[self.phase],self.phase_gap
        body=props(skill,slot,end=end)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.dog=self.ready=None;self.phase=1;self.phase_end=self.phase_gap=0
        return self._buff(361101,now)+self._buff(361102,now)+[self._cooldown(1,True),self._cooldown(2,True)]

    def interrupt(self,now):
        cast=self.ready;self.ready=None
        if cast and cast['slot']==2:
            self.phase=1;self.phase_end=0;self.cooldowns[2]=now+500
            return self.remove_buff(361303,now)+self.remove_buff(361603,now)+[(1583,struct.pack('<II',self.id,cast['skill'])),self._cooldown(2,True),self._cooldown(2)]
        return [(1583,struct.pack('<II',self.id,361801))] if cast else []

    def on_control(self,source,template,now):
        if self.ready and int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']) in (30,35,66):return self.interrupt(now)
        return []

    def _drop_dog(self,now):
        self.dog=None
        return self.remove_buff(361201,now)+[self._cooldown(1,True),self._cooldown(1)]

    def update(self,now):
        packets=[]
        if self.dog and (not self.alive or now>=self.dog['finish'] or not any(
                callback.__self__ is self and callback.__name__=='_event' and args[0]=='flight' and args[1][0] is self.dog
                for _,_,callback,args in self.arena.pending)):
            packets.extend(self._drop_dog(now))
        if self.phase>1 and (not self.alive or now>=self.phase_end):
            self.phase=1;self.phase_end=0
            packets.extend(self.remove_buff(361303,now)+self.remove_buff(361603,now)+[self._cooldown(2,True),self._cooldown(2)])
        return packets+super().update(now)

    def _hit(self,target,raw,power,generation,now,*,basic=False,heal=False):
        marked=target.has_buff(361403,now) and target.buff_sources.get(361403)==self.id
        packets=self.damage(raw,now,target=target,basic=basic)[0]
        current=self.alive and self.generation==generation
        if marked:
            packets.extend(self.damage(power*D('.45'),now,target=target)[0])
            packets.extend(self._buff(361901,now,target.id))
            if current:
                packets.extend(self.restore_hp(self.max_hp*D('.015'),now))
                self.cooldowns[1]=now+max(0,round((self.cooldowns[1]-now)*.9))
                packets.append(self._cooldown(1))
        for template in (361111,361112):packets.extend(self._buff(template,now,target.id))
        if current:
            packets.extend(self._buff(361113,now)+self._buff(361114,now))
            if heal:packets.extend(self.restore_hp((self.max_hp-self.hp)*D('.075' if target.info.get('npc_template') else '.15'),now))
        return packets

    def _bullet_hit(self,flight,target,now):
        template=flight['template'];raw=flight['raw'];heal=False
        if template==361701:
            counts=flight['context']['counts'];key=target.id,target.generation
            index=counts.get(key,0);counts[key]=index+1;raw*=D('.75')**index;heal=index==0
        return self._hit(target,raw,flight['power'],flight['source_generation'],now,basic=template==361100,heal=heal)

    def _flight(self,flight,now):
        if flight['template']==361501 and (not self.alive or flight['source_generation']!=self.generation):
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        packets=piercing_step(self,flight,now,self._bullet_hit,pierce=flight['template']!=361100)
        if flight['template']==361501 and (now>=flight['finish'] or not any(
                callback.__self__ is self and callback.__name__=='_event' and args[0]=='flight' and args[1][0] is flight
                for _,_,callback,args in self.arena.pending)):
            packets.extend(self._drop_dog(now))
        return packets

    def _event(self,now,kind,data):
        if kind=='erlang_landing':
            target_id,generation,version=data;target=self.arena.actors.get(target_id)
            if not target or not target.alive or target.generation!=generation:return []
            if target.has_buff(361402,now):
                self._queue(now+20,kind,*data);return []
            return self._buff(361406,now,target.id) if target.buff_versions.get(361402)==version else []
        if kind=='erlang_ready':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;start=self.position_at(now);dest=cast['dest'];power=cast['power']
            if cast['slot']==1:
                dog=cast['dog']
                if self.dog is not dog or now>=dog['finish']:return []
                pos=point_at(dog['start'],dog['end'],(now-dog['begin'])/(dog['finish']-dog['begin']))
                self.position=self.blink_destination(start,pos);self.motion=None;start=self.position
                packets=[scene(moves=(move_event(start,0,5,self.id),),skills=(self._skill_event(361801,start,start),))]
                for target in enemies(self,area=True):
                    if math.dist(start,target.position_at(now))<=192:packets.extend(self._hit(target,power*D('2.29'),power,cast['generation'],now))
                return packets+self._buff(361803,now)
            packets=[scene(skills=(self._skill_event(cast['skill'],start,dest),))]
            for target in enemies(self,area=True):
                if in_cone(target.position_at(now),start,dest,192,180):
                    packets.extend(self._hit(target,power*2,power,cast['generation'],now,heal=True))
                    packets.extend(self._buff(361305,now,target.id,duration=1500))
            self.phase=cast['phase']+1;self.phase_end=now+5000;self.phase_gap=now+500
            packets.extend(self._buff(361303 if self.phase==2 else 361603,now)+self._buff(361304,now))
            return packets+[self._cooldown(2,True),self._cooldown(2)]
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or not self.alive or self.ready or self.blocked('attack',now) or self.skill_sealed(slot,now):return []
        second=slot==1 and self.dog and self.has_buff(361201,now)
        phase=self.phase if slot==2 and now<self.phase_end else 1
        if not second and (self.phase_gap if slot==2 and phase>1 else self.cooldowns[slot])>now:return []
        if slot in (0,1,2) and not second and start==dest:return []
        power=self.combat_stat('iAttack',now)
        if slot==0:
            self.cooldowns[0]=now+self.fire_interval(now)
            return self.shoot(361100,start,dest,now,power,school='physical',basic=True,power=power)+[self._cooldown(0)]
        if slot==1:
            if second:
                self.ready=dict(slot=1,skill=361801,dest=dest,power=power,dog=self.dog,generation=self.generation)
                self._queue(now+50,'erlang_ready',self.ready)
                return self.remove_buff(361201,now)+[scene(skills=(self._skill_event(361801,start,start,ready=1),)),self._cooldown(1,True),self._cooldown(1)]
            self.cooldowns[1]=now+self.skill_cooldown(8000, 1)
            packets=self.shoot(361501,start,dest,now,power*D('1.12'),school='physical',power=power,through_walls=True)
            self.dog=next(args[1][0] for _,_,cb,args in reversed(sorted(self.arena.pending)) if cb.__self__ is self and cb.__name__=='_event' and args[0]=='flight')
            return packets+self._buff(361201,now)+[self._cooldown(1,True),self._cooldown(1)]
        if slot==10:
            self.cooldowns[10]=now+self.skill_cooldown(6000, 10);packets=[scene(skills=(self._skill_event(361401,start,start),)),self._cooldown(10)]
            for target in enemies(self,area=True):
                if math.dist(start,target.position_at(now))>192:continue
                packets.extend(self._hit(target,power*D('1.36'),power,self.generation,now))
                packets.extend(self._buff(361402,now,target.id)+self._buff(361403,now,target.id,duration=5000))
                if target.has_buff(361402,now):self._queue(now+20,'erlang_landing',target.id,target.generation,target.buff_versions[361402])
            return packets+self._buff(361404,now,duration=5000)+self._buff(361405,now,duration=5000)
        if phase==1:self.cooldowns[2]=now+self.skill_cooldown(15000, 2)
        packets=self.remove_buff(361303,now)+self.remove_buff(361603,now)
        if phase<3:
            skill=361301 if phase==1 else 361601
            self.ready=dict(slot=2,skill=skill,dest=dest,power=power,phase=phase,generation=self.generation)
            self._queue(now+100,'erlang_ready',self.ready)
            return packets+[scene(skills=(self._skill_event(skill,start,dest,ready=1),)),self._cooldown(2)]
        self.phase=1;self.phase_end=0;context=dict(counts={})
        angle=math.atan2(dest[1]-start[1],dest[0]-start[0])
        for offset in (-15,0,15):
            a=angle+math.radians(offset);end=(start[0]+round(600*math.cos(a)),start[1]+round(600*math.sin(a)))
            packets.extend(self.shoot(361701,start,end,now,power*2,school='physical',power=power,through_walls=True,context=context))
        return packets+[self._cooldown(2,True),self._cooldown(2)]
