"""Zoro: Oni marks, three-shot scatter and native S1590/C510 reflection aim."""
from battle_participants import human, private
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,in_strip,piercing_step,prepare_displacement

SLOTS={0:351100,1:351201,2:351301,10:351401}


class ZoroActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=None
        self.space_count=3
        self.space_next_charge=0
        self.scatter_count=0
        self.marks={}
        self.reflections=[]

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,self.space_count if slot==2 else -1,
                         self.cooldowns[slot],self.space_next_charge if slot==2 else 0)+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.reflections=[]
        return self._buff(351101,now)

    def _mark(self,target,now,generation):
        packets=[]
        for template in (351111,351112,351113):
            packets.extend(self._buff(template,now,target.id))
        if target.has_buff(351112,now) and target.buff_sources.get(351112)==self.id:
            self.marks[target.id]=dict(generation=generation,target_generation=target.generation,
                                       end=now+3000,version=target.buff_versions[351112])
        return packets

    def on_target_death(self,target,now):
        mark=self.marks.pop(target.id,None)
        if not (mark and mark['end']>now and mark['generation']==self.generation and self.alive
                and mark['target_generation']==target.generation and target.buff_versions.get(351112)==mark['version']
                and target.buff_sources.get(351112)==self.id):
            return []
        self.cooldowns[1]=now
        return [self._cooldown(1),scene(skills=(self._skill_event(351121,self.position_at(now),self.position_at(now)),))]

    def _basic_hit(self,flight,target,now):
        mark=self.marks.get(target.id)
        marked=bool(mark and mark['end']>now and mark['target_generation']==target.generation
                    and target.has_buff(351112,now) and target.buff_sources.get(351112)==self.id)
        packets=self.damage(flight['raw'],now,target=target,basic=True)[0]
        if marked and self.alive and self.generation==flight['source_generation']==mark['generation']:
            packets.extend(self._mark(target,now,mark['generation']))
            packets.extend(self.restore_hp(flight['attacker_ap']*D('.25'),now))
            for slot in (1,10):
                self.cooldowns[slot]=max(now,self.cooldowns[slot]-500)
                packets.append(self._cooldown(slot))
            if self.space_next_charge:
                self.space_next_charge=max(now,self.space_next_charge-500)
                packets.append(self._cooldown(2))
        return packets

    def _skill_hit(self,flight,target,now):
        missing=target.max_hp-target.hp
        # Attach before damage so a lethal skill hit can award this same life.
        packets=self._mark(target,now,flight['source_generation'])
        packets.extend(self.damage(flight['raw'],now,target=target,reflected=flight.get('reflected',False))[0])
        if flight['template']==351301:
            packets.extend(self.damage(missing*D('.05'),now,target=target,school='true')[0])
            packets.extend(self._buff(351303,now,target.id))
        return packets

    def _flight(self,flight,now):
        if flight['template']==351100:
            return piercing_step(self,flight,now,self._basic_hit,pierce=False)
        return piercing_step(self,flight,now,self._skill_hit)

    def reflect_projectile(self,flight,now):
        if flight.get('reflected'):
            return
        self._queue(now,'zoro_reflect',dict(generation=self.generation,power=self.combat_stat('iAttack',now),end=now+2000))

    def _event(self,now,kind,data):
        if kind=='zoro_reflect':
            request,=data
            if not self.alive or self.generation!=request['generation']:
                return []
            self.reflections.append(request)
            if human(self):return [private(self,(1590,b''))]
            # Bot mouse direction was chosen from delayed observations, not self.enemy.
            dest=self.arena.bot_brains.get(self.id,{}).get('aim',self.position_at(now))
            return self._reflect_reply(dest,now)
        if kind=='zoro_blink':
            cast,=data
            if self.ready is not cast or not self.alive:
                return []
            self.ready=None
            self.position,self.motion=self.blink_destination(cast['start'],cast['dest']),None
            packets=[scene(moves=(self._move_event(self.position,0,5),),
                           skills=(self._skill_event(351201,cast['start'],self.position),))]
            for target in enemies(self,area=True):
                if in_strip(target.position_at(now),cast['start'],self.position,min(432,math.dist(cast['start'],self.position)),96):
                    packets.extend(self._buff(351202,now,target.id)+self._mark(target,now,cast['generation']))
                    packets.extend(self.damage(cast['power']*D('2.07'),now,target=target)[0])
            self.scatter_count=3
            for template in (351204,351205,351206):
                packets.extend(self._buff(template,now))
            return packets+self.sync_speed(now)
        return super()._event(now,kind,data)

    def _reflect_reply(self,dest,now):
        if not self.reflections:
            return []
        request=self.reflections.pop(0)
        start=self.position_at(now)
        if not self.alive or self.generation!=request['generation'] or request['end']<now or start==dest:
            return []
        return self.shoot(351411,start,dest,now,request['power']*D('1.5'),school='physical',reflected=True,through_walls=True)

    def handle(self,message,payload):
        if message==510:
            packets=self.arena.tick(self.clock())
            if not self.arena.input_open(self.clock(),self):return packets
            if len(payload)>=12 and struct.unpack_from('<I',payload)[0]==self.scene_id:
                _,_,_,x,y=struct.unpack_from('<Ihhhh',payload)
                packets.extend(self._reflect_reply((x,y),self.clock()))
            return packets  # C510 replies to S1590, never an unsolicited basic.
        return super().handle(message,payload)

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def interrupt(self,now):
        packets=[]
        if self.ready:
            self.ready=None
            packets.append((1583,struct.pack('<II',self.id,351201)))
        for template in (351401,351402):
            packets.extend(self.remove_buff(template,now))
        return packets+self.sync_speed(now)

    def update(self,now):
        packets=[]
        while self.space_next_charge and self.space_next_charge<=now:
            self.space_count=min(3,self.space_count+1)
            self.space_next_charge=self.space_next_charge+self.skill_cooldown(10000) if self.space_count<3 else 0
            packets.append(self._cooldown(2))
        if (self.ready and self.skill_sealed(1,now)) or (self.has_buff(351401,now) and self.skill_sealed(10,now)):
            packets.extend(self.interrupt(now))
        self.marks={key:value for key,value in self.marks.items() if value['end']>now}
        return packets+super().update(now)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot!=10 and (start==dest or not self._inside(dest)) or slot==2 and not self.space_count:
            return []
        power=self.combat_stat('iAttack',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:10000,2:1500,10:10000}[slot], slot)
        if slot==2:
            self.space_count-=1
            if not self.space_next_charge:
                self.space_next_charge=now+self.skill_cooldown(10000)
        packets=[self._cooldown(slot)]
        if slot==0:
            scatter=self.has_buff(351204,now) and self.scatter_count>0
            if scatter:
                self.scatter_count-=1
                if not self.scatter_count:
                    packets.extend(self.remove_buff(351204,now))
            angle=math.atan2(dest[1]-start[1],dest[0]-start[0]);hits=set()
            for offset in ((-15,0,15) if scatter else (0,)):
                direction=angle+math.radians(offset)
                aim=round(start[0]+336*math.cos(direction)),round(start[1]+336*math.sin(direction))
                packets.extend(self.shoot(351100,start,aim,now,power,school='physical',basic=True,shared_hits=hits if scatter else None))
            return packets
        if slot==10:
            return packets+self._buff(351401,now)+self._buff(351402,now)
        if slot==2:
            return packets+self.shoot(351301,start,dest,now,power*D('3.22'),school='physical',through_walls=True)
        body,stopped=prepare_displacement(self,now,interrupt=False)
        self.position,self.motion=body if stopped else start,None
        self.ready=dict(slot=1,start=start,dest=aimed(start,dest,456,fixed=True),power=power,generation=self.generation)
        self._queue(now+50,'zoro_blink',self.ready)
        return packets+[scene(skills=(self._skill_event(351201,start,self.ready['dest'],ready=1),))]+self.sync_speed(now)+stopped
