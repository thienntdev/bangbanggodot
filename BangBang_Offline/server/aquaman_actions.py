"""Aquaman: third-shot current, landing whirlpool and charged shield burst."""
import math
import struct
from dataclasses import replace

from battle_runtime import TankActions
from combat_data import table_row
from combat_math import D, quantize
from combat_protocol import props, scene
from melee_common import aimed, enemies, in_cone, piercing_step, prepare_displacement

SLOTS = {0:385100, 1:385201, 2:385301, 10:385401}
CHARGE = (385311,385312,385313,385314,385316)


class AquamanActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=100;self.shots=0
        self.ready=self.dash=self.r_window=None

    def _skill(self,slot):
        if slot==0 and self.shots==2:return 385111
        if slot==2 and self.ready:return 385321
        if slot==10 and self.r_window:return 385401+10*self.r_window['phase']
        return SLOTS[slot]

    def _cooldown(self,slot,changed=False):
        body=props(self._skill(slot),slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(100,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self,now):
        self.mp=100;self.shots=0;self.ready=self.dash=self.r_window=None
        self._queue(now+3000,'aqua_energy',self.generation)
        return [scene(mp=(struct.pack('<Ii',self.id,100),))]+[self._cooldown(s,True) for s in SLOTS]

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def _basic_hit(self,flight,target,now):
        packets=self.damage(flight['raw'],now,target=target,basic=True)[0]
        current=self.alive and self.generation==flight['source_generation']
        if flight['template']==385111:
            packets.extend(self._buff(385112,now,target.id))
            if current:packets.extend(self.restore_hp(self.max_hp*D('.03'),now))
        if current:packets.extend(self._resource(5))
        return packets

    def _flight(self,flight,now):
        return piercing_step(self,flight,now,self._basic_hit,pierce=flight['template']==385111)

    def _end_r(self,now):
        self.r_window=None;self.cooldowns[10]=now+self.skill_cooldown(8000, 10)
        return self.remove_buff(385402,now)+self.remove_buff(385412,now)+[self._cooldown(10,True),self._cooldown(10)]

    def _release(self,now):
        cast,self.ready=self.ready,None
        if not cast:return []
        packets=[]
        for t in CHARGE:packets.extend(self.remove_buff(t,now))
        ratio=min(D(1),D(now-cast['begin'])/3000)
        radius=120+240*ratio
        pos=self.position_at(now)
        packets.append(scene(skills=(self._skill_event(385301,pos,pos),)))
        for target in enemies(self,area=True):
            if target.info.get('npc_template') in (20006,20017,353201):continue
            if D(str(math.dist(pos,target.position_at(now))))>radius:continue
            packets.extend(self.damage(cast['power']*D('1.145')*(1+ratio),now,target=target)[0])
            packets.extend(self._buff(385302,now,target.id)+self._buff(385303,now,target.id))
        return packets+[self._cooldown(2,True),self._cooldown(2)]+self.sync_speed(now)

    def interrupt(self,now):
        packets=[]
        if self.ready and not self.alive:
            self.ready=None
            for t in CHARGE:packets.extend(self.remove_buff(t,now))
            packets.append(self._cooldown(2,True))
        if self.dash:
            self.dash=None;self.forced_until=now
            # A seal may stop a wall-crossing leap before its safe endpoint.
            self.position,self.motion=self.stop_position(now),None
            packets.extend(self.remove_buff(385202,now))
            packets.append(scene(moves=(self._move_event(self.position,0,5),)))
        if not self.alive and self.r_window:packets.extend(self._end_r(now))
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        row=table_row('BuffTemplate_table.xml',nBuffId=template)
        return self.interrupt(now) if row['nEffectType'] in ('30','35','66') else []

    def _event(self,now,kind,data):
        if kind=='aqua_energy':
            if not self.alive or self.generation!=data[0]:return []
            self._queue(now+3000,kind,*data)
            return self._resource(5)
        if kind=='aqua_land':
            cast,=data
            if self.dash is not cast or not self.alive or self.generation!=cast['generation']:return []
            # A new water wall can shorten the dash after it has started.
            pos=self.position_at(now)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body,None
            self.dash=None;self.forced_until=now
            packets=self.remove_buff(385202,now)+stopped
            packets.append(scene(skills=(self._skill_event(385211,pos,pos),)))
            for target in enemies(self,area=True):
                if math.dist(pos,target.position_at(now))<=168:
                    packets.extend(self.damage(cast['power']*D('1.35'),now,target=target)[0])
            ident,packet=self.add_object(385212,pos);packets.append(packet)
            packets.extend(self._buff(385213,now))
            self._queue(now+1000,'aqua_whirl',dict(pos=pos,id=ident,power=cast['power'],generation=cast['generation']))
            return packets
        if kind=='aqua_whirl':
            cast,=data;packets=self.remove_object(cast['id'],destroyed=True)
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))>168:continue
                packets.extend(self.damage(cast['power']*D('1.87'),now,target=target)[0])
                if self.arena.pk and self.arena.pk['finished']:return packets
                if target.alive and not target.cc_immune(now) and not target.effect_blocked():
                    origin=target.position_at(now)
                    body,stopped=prepare_displacement(target,now,interrupt=False)
                    packets.extend(stopped)
                    target.position=target.move_destination(body if stopped else origin,cast['pos']);target.motion=None
                    packets.append(scene(moves=(target._move_event(target.position,0,5),)))
                packets.extend(self._buff(385223,now,target.id))
            return packets
        if kind=='aqua_r_end':
            return self._end_r(now) if self.r_window is data[0] else []
        if kind=='aqua_release':
            return self._release(now) if self.ready is data[0] and self.alive else []
        if kind=='aqua_decay':
            generation,version,amount=data
            if self.generation!=generation or not self.alive or self.buff_versions.get(385315)!=version:return []
            shield=next((s for s in self.shields if s.shield_id=='385315'),None)
            if shield is None:return []
            value=quantize(max(D(0),shield.remaining-amount))
            if not value:return self.remove_buff(385315,now)+[self.shield_packet(now)]
            self.shields=tuple(replace(s,remaining=value) if s is shield else s for s in self.shields)
            return [self.shield_packet(now)]
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if self.ready and slot==2 and self.alive and now-self.ready['begin']>=750:
            return self._release(now)
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or now<self.cooldowns[slot]:return []
        if slot in (0,1,10) and start==dest:return []
        follow=slot==10 and self.r_window
        cost={0:0,1:20,2:60,10:0 if follow else 30}[slot]
        if self.mp<cost:return []
        packets=self._resource(-cost);power=self.combat_stat('iAttack',now);correction=[]
        if slot==0:
            template=self._skill(0);self.shots=(self.shots+1)%3
            self.cooldowns[0]=now+self.fire_interval(now)
            if template==385111:packets.extend(self.remove_buff(385121,now)+self.remove_buff(385122,now))
            packets.extend(self.shoot(template,start,dest,now,power*(D('1.5') if template==385111 else 1),school='physical',basic=True,through_walls=template==385111))
            if self.shots==2:packets.extend(self._buff(385121,now,duration=-1))
            return packets+[self._cooldown(0,True),self._cooldown(0)]
        if slot==1:
            self.cooldowns[1]=now+self.skill_cooldown(8000, 1)
            intended=aimed(start,dest,480,fixed=True)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            body=body if stopped else start
            duration=self._set_motion(body,intended,960,now,3)
            self.forced_until=now+duration
            self.dash=dict(generation=self.generation,power=power,end=now+duration,begin=now)
            packets.extend(self._buff(385202,now,duration=duration))
            packets.extend(stopped)
            packets.append(scene(moves=(self._move_event(self.motion[1],960,3),),skills=(self._skill_event(385201,start,self.motion[1]),)))
            self._queue(now+duration,'aqua_land',self.dash)
        elif slot==10:
            phase=follow['phase'] if follow else 0
            if follow:
                for t in (385402,385412):packets.extend(self.remove_buff(t,now))
            packets.append(scene(skills=(self._skill_event(385401+phase*10,start,dest),)))
            hit=False
            for target in enemies(self,area=True):
                pos=target.position_at(now)
                if not in_cone(pos,start,dest,192 if phase==2 else 168,180):continue
                result,lost=self.damage(power*D('1.01')*D('1.25')**phase,now,target=target);packets.extend(result)
                if self.arena.pk and self.arena.pk['finished']:return packets
                if lost:
                    hit=True
                    packets.extend(self.restore_hp((self.max_hp-self.hp)*(D('.1') if phase==2 else D('.05')),now))
                    packets.extend(self._resource(20 if phase==2 else 10))
                    for s in (1,2):
                        self.cooldowns[s]=now+round(max(0,self.cooldowns[s]-now)*D('.9'));packets.append(self._cooldown(s))
                if phase==2:packets.extend(self._buff(385423,now,target.id))
                elif target.alive and not target.cc_immune(now):
                    pos,stopped=prepare_displacement(target,now,interrupt=False)
                    packets.extend(stopped)
                    end=(pos[0]+dest[0]-start[0],pos[1]+dest[1]-start[1])
                    duration=target._set_motion(pos,aimed(pos,end,36,fixed=True),240,now,1)
                    target.forced_until=now+duration;packets.append(scene(moves=(target._move_event(target.motion[1],240,1),)))
            intended=aimed(start,dest,36,fixed=True)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            body=body if stopped else start
            duration=self._set_motion(body,intended,240,now,3)
            packets.extend(stopped)
            self.forced_until=now+duration;packets.append(scene(moves=(self._move_event(self.motion[1],240,3),)))
            if hit and phase<2:
                self.r_window=dict(phase=phase+1,end=now+3000);self.cooldowns[10]=now+500
                packets.extend(self._buff(385402 if phase==0 else 385412,now)+self._buff(385408,now))
                self._queue(now+3000,'aqua_r_end',self.r_window)
                packets.append(self._cooldown(10,True))
            else:packets.extend(self._end_r(now))
        else:
            self.cooldowns[2]=now+self.skill_cooldown(15000, 2)
            body,correction=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body if correction else start,None
            self.ready=dict(slot=2,skill=385301,begin=now,power=power,dest=start,generation=self.generation)
            for t in CHARGE:packets.extend(self._buff(t,now))
            previous_version=self.buff_versions.get(385315)
            packets.extend(self.add_shield(385315,self.max_hp,now))
            if self.has_buff(385315,now) and self.buff_versions.get(385315)!=previous_version:
                for delay in range(250,5001,250):self._queue(now+delay,'aqua_decay',self.generation,self.buff_versions[385315],self.max_hp*D('.05'))
            self._queue(now+3000,'aqua_release',self.ready)
            packets.append(scene(skills=(self._skill_event(385301,start,start,ready=1),)))
            packets.append(self._cooldown(2,True));packets.extend(self.sync_speed(now))
        return packets+[self._cooldown(slot)]+correction
