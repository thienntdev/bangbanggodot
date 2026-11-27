"""Night Wing: impact distance, counted dodge, bounded wounds and return darts."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene
from melee_common import enemies,piercing_step,prepare_displacement

SLOTS={0:390100,1:390201,2:390301,10:390401}


class NightWingActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=100;self.r_count,self.r_next_charge=2,0
        self.ready=self.channel=None;self.marks={};self.wounds={}
        self.dodge_rolls={};self.passive_ready_at=0

    def _cooldown(self,slot,changed=False):
        skill=390221 if slot==0 and self.has_buff(390204,self.clock()) else SLOTS[slot]
        body=props(skill,slot,self.r_count if slot==10 else -1,self.cooldowns[slot],self.r_next_charge if slot==10 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(100,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self,now):
        self.mp=100;self.ready=self.channel=None;self.marks={}
        self.dodge_rolls={};self.passive_ready_at=0
        self._queue(now+3000,'night_energy',self.generation)
        packets=[scene(mp=(struct.pack('<Ii',self.id,100),)),self._cooldown(0,True)]
        for t in (390101,390102,390103,390104):packets.extend(self._buff(t,now))
        return packets

    def blocked(self,action,now):return bool(self.ready) or super().blocked(action,now)

    def _speed(self,now):return 0 if self.ready else super()._speed(now)

    def is_untargetable(self):
        now=getattr(self.arena,'event_now',None) or self.clock()
        return super().is_untargetable() or (any(self.has_buff(t,now) for t in (390201,390304)) and 32 not in self.buff_types(now))

    def remove_buff(self,template,now,*,expired=False):
        packets=super().remove_buff(template,now,expired=expired)
        if template==390201:
            for t in (390202,390203):packets.extend(super().remove_buff(t,now))
        if template==390204:packets.append(self._cooldown(0,True))
        return packets

    def _break_stealth(self,now):
        packets=[]
        for t in (390201,390304):
            if self.has_buff(t,now):packets.extend(self.remove_buff(t,now))
        return packets

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        return self._break_stealth(now) if hit.hp_loss>0 else []

    def block_hit(self,key,amount,now,*,basic=False,periodic=False,source=None):
        if amount<=0 or periodic:return False,[]
        if key in self.dodge_rolls:return self.dodge_rolls[key],[]
        dodged=now>=self.passive_ready_at and self.arena.rng.random()<.25
        self.dodge_rolls[key]=dodged
        if len(self.dodge_rolls)>256:self.dodge_rolls.pop(next(iter(self.dodge_rolls)))
        if not dodged:return False,[]
        self.passive_ready_at=now+500
        return True,self._buff(390131,now)

    def update(self,now):
        packets=[]
        while self.r_next_charge and now>=self.r_next_charge:
            self.r_count=min(2,self.r_count+1)
            self.r_next_charge=self.r_next_charge+self.skill_cooldown(8000) if self.r_count<2 else 0
            packets.append(self._cooldown(10))
        return packets+super().update(now)

    def interrupt(self,now):
        packets=[]
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])));self.ready=None
        if not self.alive:self.channel=None
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        row=table_row('BuffTemplate_table.xml',nBuffId=template)
        return self.interrupt(now) if row['nEffectType'] in ('30','35','66') else []

    def _mark(self,target,now,power,generation):
        if not target.alive:return []
        key=target.id,target.generation;old=self.marks.get(key)
        valid=old and old['generation']==generation and old['end']>now and target.buff_versions.get(390110+old['count'])==old['version']
        count=old['count']+1 if valid else 1
        packets=[]
        for t in range(390111,390115):
            if target.buff_sources.get(t)==self.id:packets.extend(target.remove_buff(t,now))
        if count<5:
            packets.extend(self._buff(390110+count,now,target.id))
            if target.has_buff(390110+count,now):
                self.marks[key]=dict(count=count,end=now+3000,generation=generation,version=target.buff_versions[390110+count])
            return packets
        self.marks.pop(key,None)
        packets.extend(self._buff(390115,now,target.id)+self._buff(390117,now,target.id,duration=3000))
        if not target.has_buff(390115,now):return packets
        wound=self.wounds.get(key)
        valid=wound and wound['generation']==generation and now<wound['end'] and target.buff_versions.get(390115)==wound['version']+1
        if valid:
            wound.update(end=now+3000,power=power,version=target.buff_versions[390115],dot_version=target.buff_versions[390117])
        else:
            wound=dict(target=target.id,target_generation=target.generation,generation=generation,power=power,
                       end=now+3000,previous=now,next_tick_at=now+1000,distance=0.,
                       version=target.buff_versions[390115],dot_version=target.buff_versions[390117])
            self.wounds[key]=wound;self._queue(now+20,'night_wound',wound)
        return packets

    def _hit(self,flight,target,now):
        current=self.alive and self.generation==flight['source_generation']
        origin=self.position_at(now) if self.generation==flight['source_generation'] else flight['context']['origin']
        factor=1+max(D(0),1-D(str(math.dist(origin,target.position_at(now))))/408)
        raw=flight['raw']*factor;template=flight['template']
        if template==390311 and target.id!=flight['target']:raw*=D('.5')
        packets,lost=self.damage(raw,now,target=target,basic=flight['basic'])
        if flight['basic'] or lost:
            packets.extend(self._mark(target,now,flight['context']['power'],flight['source_generation']))
            if current:packets.extend(self._resource(5))
        if template==390221:
            packets.extend(self._buff(390222,now,target.id)+self._buff(390223,now,target.id))
            if current:packets.extend(self._resource(25))
        if template in (390401,390411):
            packets.extend(self._buff(390413,now,target.id))
            if lost and current:
                self.cooldowns[1]=now+round(max(0,self.cooldowns[1]-now)*D('.9'));packets.append(self._cooldown(1))
        if template==390311 and current:packets.extend(self.restore_hp(flight['context']['power']*D('.25'),now))
        return packets

    def _flight(self,flight,now):
        template=flight['template']
        if template in (390100,390221):return piercing_step(self,flight,now,self._hit,pierce=False)
        returning=template==390411;homing=returning or template==390311
        packets=[];target=self.arena.actors.get(flight.get('target'))
        if homing:
            if not target or not target.alive or target.generation!=flight['target_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start=flight['pos'];dest=target.position_at(now)
            end=point_at(start,dest,min(1,flight['speed']*(now-flight['previous'])/1000/max(1,math.dist(start,dest))))
            if dest!=flight['end']:packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))))
            flight['end']=dest;flight['pos']=end
            reached=returning and math.dist(end,dest)<=1
        else:
            start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
            end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
            reached=now>=flight['finish']
        contacts=[]
        for enemy in enemies(self):
            key=enemy.id,enemy.generation
            if key in flight['hits']:continue
            h=actor_contact(start,end,enemy,flight['previous'],now)
            if h is not None:contacts.append((h,enemy.id,enemy,key))
        for _,_,enemy,key in sorted(contacts):
            if self.projectile_blocked(enemy,now):return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['hits'].add(key);packets.extend(self._hit(flight,enemy,now))
            if template==390311:return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if reached or now>=flight['finish']:
            packets.append(scene(expired_bullets=(struct.pack('<I',flight['id']),)))
            if template==390401 and self.alive and self.generation==flight['source_generation']:
                packets.extend(self.shoot(390411,tuple(round(v) for v in end),self.position_at(now),now,
                    flight['context']['power']*D('.3'),school='physical',target=self,through_walls=True,
                    context=flight['context'],attack_key=flight['attack_key']))
            return packets
        flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _event(self,now,kind,data):
        if kind=='night_energy':
            if not self.alive or self.generation!=data[0]:return []
            self._queue(now+3000,kind,*data);return self._resource(10)
        if kind=='night_wound':
            wound,=data;target=self.arena.actors.get(wound['target']);key=wound['target'],wound['target_generation']
            if (self.wounds.get(key) is not wound or not target or not target.alive or target.generation!=wound['target_generation']
                    or target.buff_versions.get(390115)!=wound['version'] or target.buff_versions.get(390117)!=wound['dot_version']):
                if self.wounds.get(key) is wound:self.wounds.pop(key,None)
                return []
            packets=[]
            if target.motion:
                # Integrate the active movement segment, not a blink's jump.
                begin=max(wound['previous'],target.motion[2]);end=min(now,target.motion[3])
                if end>begin:wound['distance']+=math.dist(target.position_at(begin),target.position_at(end))
            wound['previous']=now
            count=int(wound['distance']//100);wound['distance']-=100*count
            for _ in range(count):packets.extend(self.damage(wound['power']*D('.5'),now,target=target,school='true',periodic=True)[0])
            if now>=wound['next_tick_at']:
                wound['next_tick_at']+=1000
                packets.extend(self.damage(wound['power']*D('.5'),now,target=target,periodic=True)[0])
            if now>=wound['end']:self.wounds.pop(key,None)
            else:self._queue(min(now+20,wound['end']),kind,wound)
            return packets
        if kind=='night_trace':
            generation,version,pos=data
            if not self.alive or self.generation!=generation or not self.has_buff(390203,now) or self.buff_versions.get(390203)!=version:return []
            current=self.position_at(now);packets=[]
            if current!=pos:
                ident,packet=self.add_object(390211,current);packets.append(packet)
                self._queue(now+500,'night_trace_show',ident,current)
            self._queue(now+750,kind,generation,version,current);return packets
        if kind=='night_trace_show':
            ident,pos=data;packets=self.remove_object(ident)
            ident,packet=self.add_object(390212,pos);self._queue(now+750,'object_expire',ident)
            return packets+[packet]
        if kind=='night_cast':
            cast,=data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:return []
            self.ready=None;packets=self.sync_speed(now);start=self.position_at(now)
            if cast['slot']==10:
                angle=math.atan2(cast['dest'][1]-start[1],cast['dest'][0]-start[0])
                for degree in (0,-30,30):
                    dest=(round(start[0]+408*math.cos(angle+math.radians(degree))),round(start[1]+408*math.sin(angle+math.radians(degree))))
                    packets.extend(self.shoot(390401,start,dest,now,cast['power']*D('.15'),school='physical',through_walls=True,context=cast))
            else:
                target=self.arena.actors.get(cast['target'])
                if not target or not target.alive or target.generation!=cast['target_generation']:return packets
                packets.extend(self._buff(390305,now,target.id))
                if not target.has_buff(390305,now):return packets
                cast.update(version=target.buff_versions[390305],end=now+3000)
                self.channel=cast
                for t in (390301,390302,390303,390304):packets.extend(self._buff(t,now))
                for delay in range(250,3001,250):self._queue(now+delay,'night_ghost',cast)
            return packets
        if kind=='night_ghost':
            cast,=data;target=self.arena.actors.get(cast['target'])
            if (self.channel is not cast or not self.alive or self.generation!=cast['generation'] or not target or not target.alive
                    or target.generation!=cast['target_generation'] or target.buff_versions.get(390305)!=cast['version']):return []
            packets=self.shoot(390311,self.position_at(now),target.position_at(now),now,cast['power']*D('.5'),school='physical',target=target,through_walls=True,context=cast)
            if now>=cast['end']:self.channel=None
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or now<self.cooldowns[slot]:return []
        if slot in (0,10) and start==dest:return []
        cost={0:0,1:15,2:60,10:25}[slot]
        if self.mp<cost or slot==10 and self.r_count==0:return []
        from bot_ai import team_visible
        target=self.arena.actors.get(target_id)
        if slot==2 and (not target or target not in enemies(self) or math.dist(start,target.position_at(now))>480
                       or not team_visible(self.arena,self,target,now)):return []
        power=self.combat_stat('iAttack',now)
        packets=self._resource(-cost)+self._break_stealth(now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:4000}[slot], slot)
        if slot==0:
            enhanced=self.has_buff(390204,now)
            if enhanced:packets.extend(self.remove_buff(390204,now))
            packets.extend(self.shoot(390221 if enhanced else 390100,start,dest,now,power*(D('.75') if enhanced else D('.5')),
                school='physical',basic=True,context=dict(power=power,origin=start)))
        elif slot==1:
            for t in (390201,390202,390203,390204):packets.extend(self._buff(t,now))
            self._queue(now+500,'night_trace',self.generation,self.buff_versions[390203],start)
            packets.extend([scene(skills=(self._skill_event(390201,start,start),)),self._cooldown(0,True)])
        else:
            body,stopped=prepare_displacement(self,now,interrupt=False)
            if slot==10:
                self.r_count-=1
                if not self.r_next_charge:self.r_next_charge=now+self.skill_cooldown(8000)
                packets.extend(self._buff(390421,now))
            self.position,self.motion=body if stopped else start,None
            self.ready=dict(slot=slot,skill=SLOTS[slot],dest=dest,power=power,origin=start,generation=self.generation,
                            target=target.id if slot==2 else 0,target_generation=target.generation if slot==2 else 0)
            self._queue(now+100,'night_cast',self.ready)
            packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,dest,target_id if slot==2 else 0,ready=1),)))
            packets.extend(self.sync_speed(now)+stopped)
        return packets+[self._cooldown(slot)]
