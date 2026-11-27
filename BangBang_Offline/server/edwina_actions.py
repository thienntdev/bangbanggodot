"""Edwina: paid mobile E, projectile ward R and a persistent sword field."""
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,in_strip,prepare_displacement

SLOTS={0:341100,1:341201,2:341301,10:341401}


class EdwinaActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.channel=self.ready=self.combat=None
        self.mp=int(self.stats['iMp'])

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def _cooldown(self,slot,changed=False):
        body=props(341221 if slot==1 and self.channel else SLOTS[slot],slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.mp=int(self.stats['iMp']);self.combat=None
        self._queue(now+1000,'edwina_idle',self.generation)
        packets=[]
        for t in (341101,341102,341103,341104):
            packets.extend(self._buff(t,now))
        return packets+[self._cooldown(1,True)]

    def on_combat(self,now):
        if self.alive:
            self.combat=dict(end=now+5000)

    def block_hit(self,key,amount,now,*,basic=False,periodic=False,source=None):
        if amount>0:
            self.on_combat(now)
        return False,[]

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def reject_buff(self,row,source,now):
        return bool(self.ready and source.camp!=self.camp)

    def cc_immune(self,now,*,slow=False):
        return bool(self.ready) or super().cc_immune(now,slow=slow)

    def _end_channel(self,now):
        if not self.channel:
            return []
        self.channel=None
        self.cooldowns[1]=now+self.skill_cooldown(1000, 1)
        packets=[]
        for t in (341201,341202,341203,341204):
            packets.extend(self.remove_buff(t,now))
        return packets+[self._cooldown(1,True),self._cooldown(1)]+self.sync_speed(now)

    def interrupt(self,now):
        if self.alive:
            return []  # Mobile E persists through crowd control; Space is protected.
        self.ready=None
        self.info.pop('damage_immune',None)
        return self._end_channel(now)+self.sync_speed(now)

    def on_bullet_hit(self,flight,target,now):
        return self._resource(5) if self.alive and flight['source_generation']==self.generation else []

    def _event(self,now,kind,data):
        if kind=='edwina_idle':
            if not self.alive or data[0]!=self.generation:
                return []
            self._queue(now+1000,kind,*data)
            idle=not self.channel and not self.ready and not self.has_buff(341401,now) and (not self.combat or now>=self.combat['end'])
            packets=[]
            for t in (341111,341112):
                if idle and not self.has_buff(t,now):
                    packets.extend(self._buff(t,now))
                if not idle:
                    packets.extend(self.remove_buff(t,now))
            return packets+self.restore_hp(self.max_hp*D('.03'),now)+self._resource(5) if idle else packets
        if kind=='edwina_aura':
            cast,index=data
            if self.channel is not cast or not self.alive:
                return []
            if self.mp<10:
                return self._end_channel(now)
            packets=self._resource(-10)
            if index%2==0:
                import math
                start=self.position_at(now)
                for target in enemies(self,area=True):
                    if math.dist(start,target.position_at(now))<=144:
                        packets.extend(self.damage(self.combat_stat('iEgAtk',now)*D('1.52'),now,target=target,school='energy',lifesteal=D('.3'))[0])
                        key=target.id,target.generation
                        last=cast['slows'].get(key)
                        count=last['count'] if last and last['end']>=now else 0
                        packets.extend(self._buff(341212,now,target.id,duration=1000,stacks=min(2,count+1)))
                        if target.has_buff(341212,now):
                            cast['slows'][key]=dict(count=min(2,count+1),end=now+1000)
            self._queue(now+500,kind,cast,index+1)
            return packets
        if kind=='edwina_guard_heal':
            generation,version=data
            if not self.alive or self.generation!=generation or self.buff_versions.get(341401)!=version:
                return []
            return self.restore_hp(self.max_hp*D('.03'),now)+self._resource(10)
        if kind=='edwina_sword':
            cast,=data
            if self.ready is not cast or not self.alive:
                return []
            self.ready=None;self.info.pop('damage_immune',None)
            packets=self.remove_buff(341321,now)+[scene(skills=(self._skill_event(341301,cast['start'],cast['dest']),))]
            for target in enemies(self,area=True):
                if in_strip(target.position_at(now),cast['start'],cast['dest'],600,150):
                    packets.extend(self.damage(cast['power']*D('2.23'),now,target=target,school='energy')[0])
            ident,packet=self.add_object(341302,cast['start']);packets.append(packet)
            cast.update(id=ident,end=now+6000)
            for index in range(1,13):
                self._queue(now+index*500,'edwina_field',cast,index)
            return packets+self.sync_speed(now)
        if kind=='edwina_field':
            cast,index=data
            packets=[]
            for target in enemies(self,area=True):
                if in_strip(target.position_at(now),cast['start'],cast['dest'],600,150):
                    packets.extend(self.damage(cast['power']*D('.82'),now,target=target,school='energy',periodic=True)[0])
                    packets.extend(self._buff(341311,now,target.id,duration=550))
                    packets.extend(self._buff(341312,now,target.id,duration=550))
            if self.alive and self.generation==cast['generation'] and in_strip(self.position_at(now),cast['start'],cast['dest'],600,150):
                packets.extend(self._buff(341313,now,duration=min(550,max(1,cast['end']-now))))
                if index%2==0:
                    packets.extend(self.restore_hp(self.max_hp*D('.03'),now)+self._resource(15))
            if index==12:
                packets.extend(self.remove_object(cast['id']))
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or not self.alive or self.ready or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot!=10 and self.blocked('attack',now):
            return []
        if slot==1 and self.channel:
            return self._end_channel(now)
        if slot in (0,2,10) and (start==dest or not self._inside(dest)):
            return []
        power=self.combat_stat('iEgAtk',now)
        self.cooldowns[slot]=now+{0:self.fire_interval(now),1:1000,2:self.skill_cooldown(25000, 2),10:self.skill_cooldown(10000, 10)}[slot]
        packets=[self._cooldown(slot)]
        if slot==0:
            return packets+self.shoot(341100,start,dest,now,power,school='energy',basic=True)
        if slot==1:
            if self.mp<10:
                self.cooldowns[1]=now
                return []
            self.channel=dict(generation=self.generation,slows={})
            for t in (341201,341202,341203,341204):
                packets.extend(self._buff(t,now))
            self._queue(now+500,'edwina_aura',self.channel,1)
            return packets+[self._cooldown(1,True)]
        if slot==10:
            endpoint=aimed(start,dest,336,fixed=True)
            origin,stopped=prepare_displacement(self,now,interrupt=False)
            origin=origin if stopped else start
            duration=self._set_motion(origin,endpoint,600,now,kind=3)
            self.forced_until=now+duration
            version=self.buff_versions.get(341401,0)+1
            for offset in range(500,2501,500):
                self._queue(now+offset,'edwina_guard_heal',self.generation,version)
            for t in (341401,341402,341403,341404):
                packets.extend(self._buff(t,now))
            packets.extend(stopped)
            return packets+[scene(moves=(self._move_event(self.motion[1],600,3),))]
        origin,stopped=prepare_displacement(self,now,interrupt=False)
        self.position,self.motion=origin if stopped else start,None
        self.ready=dict(slot=2,start=start,dest=aimed(start,dest,600,fixed=True),power=power,generation=self.generation)
        self.info['damage_immune']=True
        self._queue(now+500,'edwina_sword',self.ready)
        return packets+self._buff(341321,now,duration=500)+[scene(skills=(self._skill_event(341301,start,self.ready['dest'],ready=1),))]+self.sync_speed(now)+stopped
