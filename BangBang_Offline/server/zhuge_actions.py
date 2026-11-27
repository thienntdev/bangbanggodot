"""Gia Cat Luong's independent weather kits and one-use fog counter."""
from battle_participants import friendly
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_math import D
from combat_protocol import props,scene,move_event
from melee_common import enemies,piercing_step,prepare_displacement

SLOTS=({0:358100,1:358501,2:358601,10:358401},
       {0:358100,1:358201,2:358301,10:358101},
       {0:358100,1:358801,2:358901,10:358701})


class ZhugeActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.weather=0;self.mp=100;self.assists={};self.hitting=None
        self.guard_version=0;self.blocked_attacks=[]

    def _cooldown(self,slot,changed=False):
        body=props(SLOTS[self.weather][slot],slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        before,self.mp=self.mp,max(0,min(100,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if before!=self.mp else []

    def on_spawn(self,now):
        self.weather=0;self.mp=100;self.assists={};self.hitting=None;self.guard_version=0;self.blocked_attacks=[]
        self._queue(now+1000,'zhuge_energy',self.generation)
        packets=[scene(mp=(struct.pack('<Ii',self.id,self.mp),))]+[self._cooldown(s,True) for s in SLOTS[0]]
        for template in (358911,358912,358931,358932):packets.extend(self._buff(template,now))
        return packets

    def _deal(self,target,raw,now,generation,*,basic=False,periodic=False):
        current=self.alive and self.generation==generation
        self.hitting=(target.id,target.generation) if current else None
        try:packets,lost=self.damage(raw,now,target=target,school='energy',basic=basic,periodic=periodic)
        finally:self.hitting=None
        if lost and current and target.alive and not target.info.get('npc_template'):
            self.assists[(target.id,target.generation)]=dict(end=now+5000,generation=generation)
        return packets,lost

    def on_target_death(self,target,now):
        key=target.id,target.generation;mark=self.assists.pop(key,None)
        if self.alive and target.camp!=self.camp and not target.info.get('npc_template') and (
                self.hitting==key or mark and mark['end']>=now and mark['generation']==self.generation):return self._resource(30)
        return []

    def effect_blocked(self):
        if super().effect_blocked():return True
        key=getattr(self.arena,'damage_context',None)
        if key in self.blocked_attacks:return True
        if not key:return False
        source=self.arena.actors.get(key[0])
        flight=getattr(self.arena,'current_flight',None)
        basic=flight.get('basic',False) if flight else getattr(self.arena,'current_slot',None)==0
        return self._guard(key,source,getattr(self.arena,'event_now',None) or self.clock(),basic=basic)

    def _guard(self,key,source,now,*,basic=False,periodic=False):
        if periodic:return False
        if key in self.blocked_attacks:return True
        if (basic or periodic or not source or source.camp==self.camp or not self.has_buff(358921,now)
                or self.guard_version!=self.buff_versions.get(358921)):return False
        self.guard_version=-1
        self.blocked_attacks.append(key);self.blocked_attacks=self.blocked_attacks[-128:]
        cast=dict(target=source.id,target_generation=source.generation,generation=self.generation,
                  power=self.combat_stat('iEgAtk',now),version=self.buff_versions[358921])
        self._queue(now,'zhuge_counter',cast)
        return True

    def reject_buff(self,row,source,now):
        if source.camp==self.camp:return False
        if getattr(self.arena,'damage_context',None) in self.blocked_attacks:return True
        # A refresh of an already-running debuff is not a new direct hit.
        # Its periodic damage goes through block_hit with periodic=True.
        if row.get('nBuffId') and self.has_buff(int(row['nBuffId']),now):return False
        flight=getattr(self.arena,'current_flight',None)
        basic=flight.get('basic',False) if flight else getattr(self.arena,'current_slot',None)==0
        key=getattr(self.arena,'damage_context',None)
        return bool(key and self._guard(key,source,now,basic=basic))

    def block_hit(self,key,amount,now,*,basic=False,periodic=False,source=None):
        return self._guard(key,source,now,basic=basic,periodic=periodic),[]

    def update(self,now):
        self.assists={k:v for k,v in self.assists.items() if v['end']>now}
        return super().update(now)

    def _bullet_hit(self,flight,target,now):
        if flight['template']==358100:return self._deal(target,flight['raw'],now,flight['source_generation'],basic=True)[0]
        # Wind's hit first lifts; damage is a distinct landing operation.
        packets=self._buff(358501,now,target.id)
        if target.effect_blocked():return packets
        cast=dict(target=target.id,target_generation=target.generation,power=flight['power'],generation=flight['source_generation'],
                  end=now+1000,lifted=target.has_buff(358501,now))
        self._queue(now+20,'zhuge_landing',cast)
        return packets

    def _flight(self,flight,now):
        return piercing_step(self,flight,now,self._bullet_hit,pierce=flight['template']==358501)

    def _area(self,template,pos,now,power,delay,event,generation):
        ident,packet=self.add_object(template,pos)
        cast=dict(id=ident,pos=pos,power=power,generation=generation)
        self._queue(now+delay,event,cast)
        return cast,[packet] if template!=358301 else friendly(self,packet)

    def _event(self,now,kind,data):
        if kind=='zhuge_energy':
            if not self.alive or data[0]!=self.generation:return []
            self._queue(now+1000,kind,*data);return self._resource(5)
        if kind=='zhuge_landing':
            cast,=data;target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation']:return []
            if target.has_buff(358501,now) or not cast['lifted'] and now<cast['end']:
                self._queue(now+20,kind,cast);return []
            packets=self._buff(358503,now,target.id)
            packets.extend(self._deal(target,cast['power']*D('1.73'),now,cast['generation'])[0])
            return packets+self._buff(358505,now,target.id)
        if kind=='zhuge_counter':
            cast,=data
            if not self.alive or self.generation!=cast['generation']:return []
            packets=self.remove_buff(358921,now) if self.buff_versions.get(358921)==cast['version'] else []
            target=self.arena.actors.get(cast['target'])
            if target and target.alive and target.generation==cast['target_generation']:
                pos=self.position_at(now);packets.append(scene(skills=(self._skill_event(358921,pos,target.position_at(now),target.id),)))
                for owner,template in list(self.active_buffs):
                    if owner==target.id and table_row('BuffTemplate_table.xml',nBuffId=template).get('nEffectType')=='54':packets.extend(target.remove_buff(template,now))
                packets.extend(self._deal(target,cast['power']*D('1.17'),now,cast['generation'])[0])
                if self.arena.pk and self.arena.pk['finished']:return packets
                packets.extend(self._buff(358922,now,target.id)+self._buff(358923,now,target.id,duration=1000))
            if not self.alive or self.generation!=cast['generation']:return packets
            previous_version=self.buff_versions.get(358925)
            packets.extend(self.add_shield(358924,self.max_hp*D('.3'),now)+self._buff(358925,now)+self._buff(358926,now)+self._resource(30))
            # Enqueue before natural expiry is irrelevant: versions survive expiry.
            # Stasis can reject the grant while this queued counter is running;
            # an older surviving version is not proof of a successful refresh.
            version=self.buff_versions.get(358925)
            if version!=previous_version and self.has_buff(358925,now) and self.buff_sources.get(358925)==self.id:
                self._queue(now+1000,'zhuge_regen',self.generation,version,1)
            return packets
        if kind=='zhuge_regen':
            generation,version,index=data
            if not self.alive or self.generation!=generation or self.buff_versions.get(358925)!=version:return []
            if index<2:self._queue(now+1000,kind,generation,version,index+1)
            return self.restore_hp(self.max_hp*D('.05'),now)+self._resource(5)
        if kind=='zhuge_thunder_e':
            cast,=data;packets=self.remove_object(cast['id'],destroyed=True)
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))>120:continue
                hit,lost=self._deal(target,cast['power']*D('1.81'),now,cast['generation']);packets.extend(hit)
                if not target.has_buff(358205,now):
                    packets.extend(self._buff(358204,now,target.id)+self._buff(358205,now,target.id))
                if lost and self.alive and self.generation==cast['generation']:packets.extend(self._buff(358203,now))
            return packets
        if kind=='zhuge_wind_start':
            cast,=data;packets=self.remove_object(cast['id'],destroyed=True)
            cast['ids']=[]
            for template in (358602,358603):
                ident,packet=self.add_object(template,cast['pos']);cast['ids'].append(ident);packets.append(packet)
            self._queue(now+1000,'zhuge_wind_tick',cast,1)
            return packets
        if kind=='zhuge_wind_tick':
            cast,index=data;packets=[]
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))>196:continue
                packets.extend(self._buff(358604,now,target.id)+self._buff(358607,now,target.id))
                packets.extend(self._deal(target,cast['power']*D('2.5'),now,cast['generation'],periodic=True)[0])
                if self.arena.pk and self.arena.pk['finished']:return packets
                if index==3 and target.alive and not target.cc_immune(now) and not target.effect_blocked():
                    origin,stopped=prepare_displacement(target,now,interrupt=False)
                    packets.extend(stopped)
                    pos=target.move_destination(origin,cast['pos']);target.position=pos;target.motion=None
                    packets.append(scene(moves=(move_event(pos,0,5,target.id),)))
            if index<3:self._queue(now+1000,kind,cast,index+1)
            else:
                for ident in cast['ids']:packets.extend(self.remove_object(ident,destroyed=True))
            return packets
        if kind=='zhuge_thunder_start':
            cast,=data;packets=self.remove_object(cast['id'],destroyed=True)+self.remove_object(cast['warning'],destroyed=True)
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))<=96:packets.extend(self._deal(target,cast['power']*D('4.62'),now,cast['generation'])[0])
            cast['id'],packet=self.add_object(358303,cast['pos']);packets.append(packet)
            self._queue(now+1000,'zhuge_thunder_tick',cast,1)
            return packets
        if kind=='zhuge_thunder_tick':
            cast,index=data;packets=[]
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))<=96:packets.extend(self._deal(target,cast['power']*D('.9'),now,cast['generation'],periodic=True)[0])
            if index<2:self._queue(now+1000,kind,cast,index+1)
            else:packets.extend(self.remove_object(cast['id'],destroyed=True))
            return packets
        if kind=='zhuge_fog':
            cast,=data;packets=self.remove_object(cast['id'],destroyed=True)
            for target in self.arena.actors.values():
                if target.alive and target.camp==self.camp and math.dist(cast['pos'],target.position_at(now))<=300:
                    packets.extend(self._buff(358902,now,target.id)+self._buff(358903,now,target.id))
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS[0] or not self.alive or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        skill=SLOTS[self.weather][slot];cost=20 if slot==1 else 50 if slot==2 else 0
        if self.mp<cost or slot==0 and start==dest or slot==1 and self.weather==0 and start==dest:return []
        if slot in (1,2) and self.weather!=2 and math.dist(start,dest)>(480 if skill==358601 else 600):return []
        power=self.combat_stat('iEgAtk',now)
        self.cooldowns[slot]=now+(self.skill_cooldown({0:self.fire_interval(now),10:1000}.get(slot) or int(table_row('SkillTemplate_table.xml',nId=skill)['iCoolTime']), slot))
        packets=self._resource(-cost)
        if slot==0:return packets+self.shoot(358100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        if slot==10:
            for template in (358911,358912,358913,358915,358102,358103,358104,358402,358403,358404,358702,358703,358704):packets.extend(self.remove_buff(template,now))
            self.weather=(self.weather+1)%3
            templates=((358911,358912,358702,358703,358704),(358913,358402,358403,358404),(358915,358102,358103,358104))[self.weather]
            for template in (skill,*templates):packets.extend(self._buff(template,now))
            self.cooldowns[1]=self.cooldowns[2]=0
            return packets+[self._cooldown(s,True) for s in (1,2,10)]+[self._cooldown(s) for s in (1,2,10)]
        if skill==358501:packets.extend(self.shoot(skill,start,dest,now,0,school='energy',through_walls=True,power=power))
        elif skill==358801:
            previous_version=self.buff_versions.get(358921)
            packets.extend(self._buff(358921,now))
            version=self.buff_versions.get(358921)
            if version!=previous_version and self.has_buff(358921,now) and self.buff_sources.get(358921)==self.id:self.guard_version=version
        elif skill in (358201,358601,358301,358901):
            delay,event={358201:(300,'zhuge_thunder_e'),358601:(500,'zhuge_wind_start'),358301:(1250,'zhuge_thunder_start'),358901:(1000,'zhuge_fog')}[skill]
            cast,created=self._area(skill,start if skill==358901 else dest,now,power,delay,event,self.generation);packets.extend(created)
            if skill==358301:
                cast['warning'],packet=self.add_object(358305,dest);packets.append(packet)
        return packets+[self._cooldown(slot)]
