"""Saitama: finite serious mode and a manually released charged punch."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene,stop_move
from melee_common import aimed,enemies,in_cone,prepare_displacement,accept_water_reclip

SLOTS={0:377100,1:377201,2:377301,10:377401}
CHARGE_BUFFS=(377321,377322,377323,377324,377325)


class SaitamaActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=int(self.stats['iMp'])
        self.stacks=0
        self.received=D(0)
        self.proc_clocks={False:dict(end=0),True:dict(end=0)}
        self.ready=self.dash=self.serious=None

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def _cooldown(self,slot,changed=False):
        skill=377311 if slot==2 and self.ready and self.ready['slot']==2 else SLOTS[slot]
        body=props(skill,slot,end=0 if skill==377311 else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.mp=int(self.stats['iMp']);self.stacks=0;self.received=D(0)
        self.serious=self.dash=self.ready=None
        self.proc_clocks={False:dict(end=0),True:dict(end=0)}
        self._queue(now+3000,'saitama_energy',self.generation)
        packets=[]
        for template in (377101,377102,377103):
            packets.extend(self._buff(template,now))
        return packets+[self._cooldown(2,True),scene(mp=(struct.pack('<Ii',self.id,self.mp),))]

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.dash) or super().blocked(action,now)

    def cc_immune(self,now,*,slow=False):
        return bool(self.serious or self.ready and self.ready['slot']==2) or super().cc_immune(now,slow=slow)

    def _stack(self,count,now):
        if not self.alive or self.serious or count<=0:
            return []
        if self.stacks and not self.has_buff(377110+self.stacks,now):
            self.stacks=0
        packets=[]
        for template in range(377111,377121):
            packets.extend(self.remove_buff(template,now))
        self.stacks=min(10,self.stacks+count)
        packets.extend(self._buff(377110+self.stacks,now))
        if self.stacks==10:
            self.serious=dict(end=now+3000,generation=self.generation)
            for template in (377121,377122,377123,377124,377126,377127,377128):
                packets.extend(self._buff(template,now))
            self._queue(now+500,'saitama_heal',self.serious,1)
        return packets

    def damage(self,raw,now,**kwargs):
        packets,lost=super().damage(raw,now,**kwargs)
        flight=getattr(self.arena,'current_flight',None)
        current=not flight or flight.get('source_generation')==self.generation
        basic=kwargs.get('basic',False)
        if lost and current and self.alive:
            if basic:
                packets.extend(self._resource(5))
            timer=self.proc_clocks[basic]
            if now>=timer['end']:
                timer['end']=now+(150 if basic else 500)
                packets.extend(self._resource(10) if self.serious else self._stack(1,now))
        return packets,lost

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        if not self.alive or hit.hp_loss<=0:
            return []
        self.received+=hit.hp_loss
        step=self.max_hp*D('.05')
        count=int(self.received//step);self.received-=count*step
        return self._stack(count,now)

    def _clear_charge(self,now):
        packets=[]
        for template in CHARGE_BUFFS:
            packets.extend(self.remove_buff(template,now))
        return packets+[self._cooldown(2,True)]+self.sync_speed(now)

    def interrupt(self,now):
        if self.alive and self.ready and self.ready['slot']==2:
            return []
        packets=[]
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            self.ready=None
            packets.extend(self._clear_charge(now))
        if self.dash:
            self.dash=None
            self.position,self.motion,self.forced_until=self.position_at(now),None,now
            packets.extend(self.remove_buff(377202,now))
        if not self.alive:
            self.serious=None;self.stacks=0;self.received=D(0)
        return packets+self.sync_speed(now)

    def update(self,now):
        packets=[]
        if self.ready and self.ready['slot']!=2 and self.skill_sealed(self.ready['slot'],now):
            packets.extend(self.interrupt(now))
        return packets+super().update(now)

    def _push(self,target,direction,now):
        if not target.alive or target.cc_immune(now):
            return []
        current=target.position_at(now)
        start=target.stop_position(now)
        dest=aimed(start,(start[0]+direction[0],start[1]+direction[1]),360,fixed=True)
        wall=self.arena.geometry.wall_contact(start,dest,36)
        if wall is not None:
            dest=point_at(start,dest,max(0,wall-.0001))
        requested=dest
        if start!=current:target.position,target.motion=start,None
        packets=target.interrupt(now)
        if start!=current:packets.append(stop_move(self.scene_id,target.id,start))
        duration=target._set_motion(start,dest,960,now,kind=1)
        target.forced_until=now+duration
        cast=dict(target=target.id,target_generation=target.generation,source_generation=self.generation,motion=target.motion,
                  end=now+duration,wall=wall is not None or math.dist(requested,target.motion[1])>.1)
        self._queue(now+min(20,duration),'saitama_wall',cast)
        return packets+self._buff(377303,now,target.id)+[scene(moves=(self._move_event(target.motion[1],960,1,target.id),))]

    def _release(self,cast,now):
        if self.ready is not cast or not self.alive:
            return []
        self.ready=None
        fraction=min(1,max(0,(now-cast['begin'])/3000))
        radius=240+360*fraction
        power=cast['power']*D('1.58')*(1+D(str(fraction)))
        start=self.position_at(now);dest=cast['dest']
        packets=self._clear_charge(now)+[(1583,struct.pack('<II',self.id,377301)),scene(skills=(self._skill_event(377301,start,dest),))]
        for target in enemies(self,area=True):
            if in_cone(target.position_at(now),start,dest,radius,60):
                packets.extend(self.damage(power,now,target=target)[0])
                if self.arena.pk and self.arena.pk['finished']:
                    return packets
                packets.extend(self._push(target,(dest[0]-start[0],dest[1]-start[1]),now))
        return packets

    def _event(self,now,kind,data):
        if kind=='saitama_energy':
            if not self.alive or data[0]!=self.generation:
                return []
            self._queue(now+3000,kind,self.generation)
            return self._resource(10)
        if kind=='saitama_heal':
            cast,index=data
            if self.serious is not cast or not self.alive:
                return []
            packets=self.restore_hp((self.max_hp-self.hp)*D('.05'),now)
            if index<6:
                self._queue(now+500,kind,cast,index+1)
            else:
                self.serious=None;self.stacks=0
                for template in range(377111,377130):
                    packets.extend(self.remove_buff(template,now))
                packets.extend(self._buff(377141,now))
            return packets
        if kind=='saitama_wall':
            cast,=data;target=self.arena.actors[cast['target']]
            if not target.alive or target.generation!=cast['target_generation']:
                return []
            if target.motion!=cast['motion']:
                if (target.motion and target.motion_kind==1 and target.motion[3]<=cast['end']
                        and target.has_buff(377303,now) and accept_water_reclip(target,cast)):
                    cast.update(motion=target.motion,end=target.motion[3],wall=True)
                else:
                    return target.remove_buff(377303,now)
            if now<cast['end']:
                self._queue(min(now+20,cast['end']),kind,cast)
                return []
            packets=target.remove_buff(377303,now)
            if cast['wall']:
                hit=self.damage if self.generation==cast['source_generation'] else super().damage
                packets.extend(hit((target.max_hp-target.hp)*D('.5'),now,target=target)[0])
                packets.extend(self._buff(377332,now,target.id))
            return packets
        if kind=='saitama_release':
            return self._release(data[0],now)
        if kind=='saitama_ready':
            cast,=data
            if self.ready is not cast or not self.alive:
                return []
            self.ready=None
            start=self.position_at(now);dest=cast['dest'];packets=self.sync_speed(now)
            if cast['slot']==1:
                duration=self._set_motion(start,aimed(start,dest,480,fixed=True),960,now,kind=3)
                self.forced_until=now+duration
                self.dash=dict(end=now+duration,previous=now,power=cast['power'])
                self._queue(now+min(20,duration),'saitama_dash',self.dash)
                return packets+self._buff(377202,now,duration=duration)+[scene(moves=(self._move_event(self.motion[1],960,3),))]
            packets.append(scene(skills=(self._skill_event(377401,start,dest),)))
            count=0
            for target in enemies(self,area=True):
                if not in_cone(target.position_at(now),start,dest,360,60):
                    continue
                more,lost=self.damage(cast['power']*D('1.75'),now,target=target);packets.extend(more);count+=bool(lost)
                if self.arena.pk and self.arena.pk['finished']:
                    return packets
                packets.extend(self._buff(377403,now,target.id))
                if target.alive and not target.cc_immune(now):
                    origin,stopped=prepare_displacement(target,now)
                    packets.extend(stopped)
                    end=aimed(origin,aimed(start,dest,360),120)
                    target.forced_until=now+target._set_motion(origin,end,720,now,kind=1)
                    packets.append(scene(moves=(self._move_event(target.motion[1],720,1,target.id),)))
            return packets+self._stack(max(0,count-1),now)
        if kind=='saitama_dash':
            cast,=data
            if self.dash is not cast or not self.alive:
                return []
            start,end=self.position_at(cast['previous']),self.position_at(now)
            hits=[(h,t.id,t) for t in enemies(self) if (h:=actor_contact(start,end,t,cast['previous'],now)) is not None]
            done=not self.motion or now>=self.motion[3] or now>=cast['end']
            packets=[]
            if hits:
                h,_,_=min(hits,key=lambda v:v[:2])
                impact=tuple(round(v) for v in point_at(start,end,h))
                # Keep impact damage separate from the safe 72px body landing.
                self.position=self.stop_position(now,impact)
                self.motion=None;self.forced_until=now;done=True
                packets.append(stop_move(self.scene_id,self.id,self.position))
                packets.append(scene(moves=(self._move_event(self.position,0,5),),skills=(self._skill_event(377211,impact,impact),)))
                for target in enemies(self,area=True):
                    if math.dist(impact,target.position_at(now))<=144:
                        packets.extend(self.damage(cast['power']*D('2.25'),now,target=target)[0])
                        packets.extend(self._buff(377212,now,target.id))
            if done:
                self.dash=None;packets.extend(self.remove_buff(377202,now))
            else:
                cast['previous']=now;self._queue(min(now+20,cast['end']),kind,cast)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if self.ready and self.ready['slot']==2 and slot==2 and self.alive:
            return self._release(self.ready,now)
        cost={0:0,1:15,2:60,10:25}.get(slot,0)
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now or self.mp<cost or start==dest:
            return []
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:15000,10:8000}[slot], slot)
        packets=self._resource(-cost)+[self._cooldown(slot)]
        if slot==0:
            return packets+self.shoot(377100,start,dest,now,self.combat_stat('iAttack',now),school='physical',basic=True)
        power=self.combat_stat('iAttack',now)
        body,handoff=prepare_displacement(self,now,interrupt=False)
        if not handoff: body=start
        self.position,self.motion=body,None
        self.ready=dict(slot=slot,skill=SLOTS[slot],begin=now,dest=dest,power=power,generation=self.generation)
        if slot==2:
            for template in CHARGE_BUFFS:
                packets.extend(self._buff(template,now))
            packets.append(self._cooldown(2,True))
        self._queue(now+{1:100,2:3000,10:300}[slot],'saitama_release' if slot==2 else 'saitama_ready',self.ready)
        return packets+[scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),))]+self.sync_speed(now)+handoff
