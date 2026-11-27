"""Kiem Than: movement energy, cast snapshots and delayed E-mark consumption."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,piercing_step,prepare_displacement

SLOTS={0:355100,1:355201,2:355301,10:355401}


class SwordGodActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=0;self.e_count=3;self.e_next_charge=0
        self.ready=None;self.nearby=False
        self.walk=dict(pos=self.position,previous=self.clock(),end=self.clock()+2000,next_stack_at=0,distance=0.)

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,self.e_count if slot==1 else -1,self.cooldowns[slot],
                          self.e_next_charge if slot==1 else 0)+struct.pack('<I',self.id)

    def _resource(self,delta,now=None):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        now=self.clock() if now is None else now
        old,self.mp=self.mp,max(0,min(100,self.mp+delta))
        if delta>0:self.walk['end']=now+2000
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self,now):
        self.mp=0;self.ready=None;self.nearby=False
        self.walk=dict(pos=self.position,previous=now,end=now+2000,next_stack_at=0,distance=0.)
        self._queue(now,'sword_aura',self.generation)
        return [scene(mp=(struct.pack('<Ii',self.id,0),))]

    def _speed(self,now):
        # Q37: enemy present, speed only; do not install obsolete +25% AP.
        return super()._speed(now)+(round(int(self.stats['iSpeed'])*.25) if self.nearby and 36 not in self.buff_types(now) else 0)

    def cleanse(self,now):
        packets=super().cleanse(now)
        for owner,template in list(self.active_buffs):
            source=self.arena.actors.get(self.buff_sources.get(template))
            if owner==self.id and source and source.camp!=self.camp and int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']) in (30,35,36,39,62,66):
                packets.extend(self.remove_buff(template,now))
        return packets

    def interrupt(self,now):
        self.ready=None
        return []

    def update(self,now):
        packets=[]
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count=min(3,self.e_count+1)
            self.e_next_charge=self.e_next_charge+self.skill_cooldown(6000) if self.e_count<3 else 0
            packets.append(self._cooldown(1))
        pos=self.position_at(now);walk=self.walk
        # Only the actual kind0 walking path contributes, never forced motion,
        # coordinate reconciliation, blink or a jump in a client C501 origin.
        distance=0.
        if self.alive and self.motion and self.motion_kind==0:
            a,b,began,end=self.motion
            start=max(began,walk['previous']);finish=min(now,end)
            if finish>start:distance=math.dist(a,b)*(finish-start)/(end-began)
        if distance:
            walk['distance']+=distance;walk['end']=now+2000
            if walk['distance']>=120 and now>=walk['next_stack_at']:
                walk['distance']-=120;walk['next_stack_at']=now+1000
                packets.extend(self._resource(5,now))
        elif self.alive and now>=walk['end']:
            walk['distance']=0.;packets.extend(self._resource(-100,now))
        walk['pos']=pos;walk['previous']=now
        return packets+super().update(now)

    def _blade(self,flight,target,now):
        cast=flight['context']
        distance=min(840,math.dist(flight['start'],target.position_at(now)))
        packets,lost=self.damage(cast['power']*(1+D(str(distance))/840),now,target=target,ignore_armor=True)
        if self.arena.pk and self.arena.pk['finished']:
            return packets
        if not target.info.get('npc_template'):packets.extend(self._buff(355202,now,target.id))
        if lost and self.alive and self.generation==flight['source_generation']:
            previous_version=self.buff_versions.get(355204)
            packets.extend(self._buff(355204,now))
            version=self.buff_versions.get(355204)
            # Stasis may reject this grant while an older version still exists.
            if version!=previous_version and self.has_buff(355204,now) and self.buff_sources.get(355204)==self.id:
                self._queue(now+300,'sword_refund',self.generation,version,0)
        return packets

    def _flight(self,flight,now):
        if flight['template']==355201:return piercing_step(self,flight,now,self._blade,pierce=False)
        return super()._flight(flight,now)

    def _event(self,now,kind,data):
        if kind=='sword_aura':
            if not self.alive or data[0]!=self.generation:return []
            self.nearby=any(math.dist(self.position_at(now),a.position_at(now))<=360 for a in enemies(self))
            self._queue(now+1000,kind,*data)
            return self.sync_speed(now)
        if kind=='sword_refund':
            generation,version,index=data
            if not self.alive or self.generation!=generation or self.buff_versions.get(355204)!=version:return []
            if index<4:self._queue(now+300,kind,generation,version,index+1)
            return self._resource(5,now)
        if kind=='sword_fire':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None
            return self.shoot(355201,self.position_at(now),cast['dest'],now,0,school='physical',
                              through_walls=True,speed_multiplier=cast['speed'],context=cast)
        if kind=='sword_space':
            cast,=data;target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation'] or target.buff_versions.get(355301)!=cast['version']:return []
            marked=target.has_buff(355202,now) and target.buff_sources.get(355202)==self.id
            missing=target.max_hp-target.hp
            packets=target.remove_buff(355301,now)
            if marked:packets.extend(target.remove_buff(355202,now))
            packets.extend(self.damage(cast['power']*(3 if marked else 1),now,target=target)[0])
            packets.extend(self.damage(missing*D('.15'),now,target=target,school='true')[0])
            packets.extend(self._buff(355305,now,target.id))
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or not self.alive or (slot!=10 and (self.blocked('attack',now) or self.skill_sealed(slot,now))) or self.cooldowns[slot]>now:return []
        if slot in (0,1) and start==dest or slot==1 and (not self.e_count or self.ready):return []
        energy=self.mp;power=self.combat_stat('iAttack',now)*(1+D('.25')*energy/100)
        if slot==0:
            self.cooldowns[0]=now+self.fire_interval(now)
            return self.shoot(355100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        if slot==1:
            self.e_count-=1
            if not self.e_next_charge:self.e_next_charge=now+self.skill_cooldown(6000)
            self.cooldowns[1]=now+self.skill_cooldown(2000, 1)
            self.ready=dict(slot=1,dest=dest,power=self.combat_stat('iAttack',now)*(1+D('.5')*energy/100),speed=1+.5*energy/100)
            self._queue(now+50,'sword_fire',self.ready)
            return self._resource(-100,now)+self._buff(355211,now)+[self._cooldown(1)]
        self.cooldowns[slot]=now+(self.skill_cooldown(25000 if slot==2 else 10000, slot))
        packets=[self._cooldown(slot)]
        if slot==2:
            for target in enemies(self,area=True):
                if target.info.get('npc_template') or math.dist(start,target.position_at(now))>1200 or target.has_buff(355301,now):continue
                packets.extend(self._buff(355301,now,target.id))
                if not target.has_buff(355301,now) or target.buff_sources.get(355301)!=self.id:continue
                cast=dict(target=target.id,target_generation=target.generation,power=power,version=target.buff_versions[355301])
                self._queue(now+1500,'sword_space',cast)
            return packets
        packets.extend(self.cleanse(now)+self._resource(50,now)+self._buff(355403,now))
        packets.append(scene(skills=(self._skill_event(355401,start,start),)))
        for target in enemies(self,area=True):
            origin=target.position_at(now)
            if math.dist(start,origin)>196:continue
            packets.extend(self.damage(power,now,target=target)[0])
            if self.arena.pk and self.arena.pk['finished']:
                return packets
            packets.extend(self._buff(355406,now,target.id))
            if target.alive and not target.cc_immune(now):
                origin,stopped=prepare_displacement(target,now)
                packets.extend(stopped)
                dest=aimed(start,origin if origin!=start else (start[0]+1,start[1]),math.dist(start,origin)+240,fixed=True)
                duration=target._set_motion(origin,dest,720,now,kind=1)
                target.forced_until=now+duration;packets.append(scene(moves=(target._move_event(target.motion[1],720,1),)))
        return packets
