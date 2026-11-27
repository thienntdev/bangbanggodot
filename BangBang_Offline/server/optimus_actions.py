"""Optimus base 819xxx: live rage, independent sword area and timed melee form."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact
from combat_math import D
from combat_protocol import props,scene
from melee_common import enemies,in_cone,in_strip

SLOTS={0:819010,1:819021,2:819031,10:819041}


class OptimusActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=0;self.form=None;self.swing=819012;self.swords=[];self.proc_locks={};self.dash=None

    def _cooldown(self,slot,changed=False):
        skill=self.swing if slot==0 and self.form else SLOTS[slot]
        body=props(skill,slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self,delta,now=None):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        now=self.clock() if now is None else now
        old,self.mp=self.mp,max(0,min(200,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))]+self.sync_speed(now) if old!=self.mp else []

    def attr_bonus(self,attributes,now):
        value=super().attr_bonus(attributes,now)
        if 10 in attributes and self.has_buff(8190101,now):value+=D('.5')*self.mp/200
        return value

    def _speed(self,now):
        base=super()._speed(now)
        if 36 not in self.buff_types(now) and self.has_buff(8190102,now):
            base+=round(D(self.stats['iSpeed'])*D('.5')*self.mp/200)
        return base

    def on_spawn(self,now):
        self.mp=0;self.form=self.dash=None;self.swing=819012;self.proc_locks={}
        self._queue(now+600,'optimus_rage',self.generation)
        packets=[scene(mp=(struct.pack('<Ii',self.id,0),)),self._cooldown(0,True)]
        for template in range(8190101,8190108):packets.extend(self._buff(template,now))
        return packets

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        return self._resource(5,now) if self.alive and hit.hp_loss>0 else []

    def _hit(self,target,power,now,*,basic=False,school='physical',current=True):
        before=target.hp;key=(target.id,target.generation)
        proc=basic and self.proc_locks.get(key,{}).get('end',0)<=now
        packets,lost=self.damage(power,now,target=target,basic=basic,school=school)
        if lost and current and self.alive:
            packets.extend(self._resource(5 if basic else 25,now))
        if proc and lost:
            self.proc_locks[key]=dict(end=now+6000)
            packets.extend(self.damage(before*D('.1'),now,target=target,school='true',basic=True)[0])
            packets.extend(self._buff(8190113,now,target.id))
        return packets

    def on_bullet_hit(self,flight,target,now):
        return []

    def _flight(self,flight,now):
        from melee_common import piercing_step
        return piercing_step(self,flight,now,lambda f,t,n:self._hit(t,f['raw'],n,basic=True,
            current=self.alive and self.generation==f['source_generation']),pierce=False)

    def _end_form(self,now):
        if not self.form:return []
        self.form=None;self.cooldowns[2]=now+self.skill_cooldown(25000, 2)
        packets=[]
        for template in (8190311,8190312,8190315,8190316,8190114,8190115):
            packets.extend(self.remove_buff(template,now))
        packets.extend(self._buff(8190321,now))
        return packets+[self._cooldown(0,True),self._cooldown(2)]

    def interrupt(self,now):
        self.dash=None
        return self._end_form(now) if not self.alive else []

    def _sword_area(self,cast,now):
        packets=[]
        for target in list(self.arena.actors.values()):
            if not target.alive or math.dist(cast['pos'],target.position_at(now))>192:continue
            template=8190421 if target.id==self.id and self.generation==cast['generation'] else 8190422 if target.camp==self.camp else 8190423
            packets.extend(self._buff(template,now,target.id,duration=min(550,cast['end']-now)))
        return packets

    def _event(self,now,kind,data):
        if kind=='optimus_rage':
            if not self.alive or data[0]!=self.generation:return []
            self._queue(now+600,kind,*data)
            return self._resource(-5,now)
        if kind=='optimus_sword_land':
            cast,=data
            packets=self.remove_object(cast['id'])
            cast['id'],packet=self.add_object(8190412,cast['pos']);cast['end']=now+2000
            packets.append(packet)
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))<=192:
                    packets.extend(self._hit(target,cast['power']*D('1.88'),now,
                        current=self.alive and self.generation==cast['generation']))
            packets.extend(self._sword_area(cast,now));self._queue(now+500,'optimus_area',cast)
            return packets
        if kind=='optimus_area':
            cast,=data
            if now>=cast['end']:
                self.swords=[s for s in self.swords if s is not cast]
                return self.remove_object(cast['id'])
            self._queue(now+500,kind,cast)
            return self._sword_area(cast,now)
        if kind=='optimus_form_end':
            return self._end_form(now) if self.form is data[0] else []
        if kind=='optimus_dash':
            cast,=data
            if self.dash is not cast or not self.alive:return []
            start,end=self.position_at(cast['previous']),self.position_at(now);packets=[]
            for target in enemies(self):
                key=target.id,target.generation
                if key in cast['hits'] or actor_contact(start,end,target,cast['previous'],now) is None:continue
                cast['hits'].add(key)
                packets.extend(self._buff(8190222,now,target.id))
                packets.extend(self._hit(target,cast['power']*D('1.96'),now))
            if not self.motion or now>=self.motion[3]:self.dash=None
            else:cast['previous']=now;self._queue(min(now+20,self.motion[3]),kind,cast)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot in (0,1) and start==dest or slot==2 and (self.form or self.mp<100):return []
        if slot==10 and (not self._inside(dest) or math.dist(start,dest)>480):return []
        power=self.combat_stat('iAttack',now);packets=[]
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:0,10:8000}[slot], slot)
        if slot==0:
            if not self.form:return self.shoot(819010,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
            skill=self.swing;packets.append(scene(skills=(self._skill_event(skill,start,dest),)))
            for target in enemies(self,area=True):
                if in_cone(target.position_at(now),start,dest,216,180):
                    packets.extend(self._hit(target,power,now,basic=True,school='true'))
                    packets.extend(self._buff(8190116,now,target.id))
            self.swing=819013 if skill==819012 else 819012
            packets.append(self._cooldown(0,True))
        elif slot==1:
            packets.append(scene(skills=(self._skill_event(819021,start,dest),)))
            for target in enemies(self,area=True):
                if in_strip(target.position_at(now),start,dest,480,72):
                    packets.extend(self._hit(target,power*D('1.46'),now))
                    packets.extend(self._buff(8190214,now,target.id))
            packets.extend(self._buff(8190215,now))
            swords=[s for s in self.swords if s['end']>now and s['generation']==self.generation and in_strip(s['pos'],start,dest,480,72)]
            if swords and not (self.arena.pk and self.arena.pk['finished']):
                chosen=min(swords,key=lambda s:math.dist(start,s['pos']))
                duration=self._set_motion(start,chosen['pos'],960,now,3);self.forced_until=now+duration
                self.dash=dict(previous=now,hits=set(),power=power)
                packets.extend(self._buff(8190221,now,duration=duration))
                packets.append(scene(moves=(self._move_event(self.motion[1],960,3),)))
                self._queue(now+min(20,duration),'optimus_dash',self.dash)
        elif slot==10:
            ident,packet=self.add_object(8190411,dest)
            cast=dict(id=ident,pos=dest,power=power,generation=self.generation,end=now+2500)
            self.swords.append(cast);packets.append(packet);self._queue(now+500,'optimus_sword_land',cast)
        else:
            packets.extend(self._resource(-100,now));self.form=dict(end=now+8000);self.swing=819012
            packets.append(scene(skills=(self._skill_event(819031,start,start,self.id),)))
            for target in enemies(self,area=True):
                distance=math.dist(start,target.position_at(now))
                if distance<=216:
                    packets.extend(self._hit(target,power*(D('3.37')-D('1.685')*D(str(distance))/216),now))
                    for t in (8190313,8190317):packets.extend(self._buff(t,now,target.id))
            for t in (8190311,8190312,8190315,8190316):packets.extend(self._buff(t,now))
            packets.append(self._cooldown(0,True));self._queue(now+8000,'optimus_form_end',self.form)
        return packets+[self._cooldown(slot)]
