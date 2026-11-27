"""Naruto: chakra, four piercing attacks, Rasengan and a persistent vortex."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene,stop_move
from melee_common import aimed,enemies,piercing_step,prepare_displacement

SLOTS={0:318100,1:318201,2:318301,10:318401}


class NarutoActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=int(self.stats['iMp']);self.shots=0
        self.ready=self.dash=self.hitting=None
        self.assists={};self.fields={};self.e_hits={}

    def _cooldown(self,slot,changed=False):
        skill=318211 if slot==0 and self.shots and self.has_buff(318201,self.clock()) else SLOTS[slot]
        body=props(skill,slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self,now):
        self.mp=int(self.stats['iMp']);self.shots=0;self.ready=self.dash=self.hitting=None;self.assists={};self.e_hits={}
        self._queue(now+3000,'naruto_energy',self.generation)
        packets=[scene(mp=(struct.pack('<Ii',self.id,self.mp),)),self._cooldown(0,True)]
        for t in (318101,318102,318103):packets.extend(self._buff(t,now))
        return packets

    def remove_buff(self,template,now,*,expired=False):
        packets=super().remove_buff(template,now,expired=expired)
        if template==318201:
            self.shots=0;packets.append(self._cooldown(0,True))
        return packets

    def _deal(self,target,raw,now,*,generation=None,**kwargs):
        generation=self.generation if generation is None else generation
        current=self.alive and self.generation==generation
        self.hitting=(target.id,target.generation) if current else None
        try:packets,lost=self.damage(raw,now,target=target,**kwargs)
        finally:self.hitting=None
        if lost and current and target.alive and not target.info.get('npc_template'):
            self.assists[(target.id,target.generation)]=dict(end=now+5000,generation=generation)
        return packets

    def on_target_death(self,target,now):
        key=target.id,target.generation;mark=self.assists.pop(key,None)
        if (not self.alive or target.camp==self.camp or target.info.get('npc_template')
                or not (self.hitting==key or mark and mark['end']>=now and mark['generation']==self.generation)):
            return []
        packets=self._resource(50)
        for template in (318111,318112,318113,318115,318116,318117):packets.extend(self._buff(template,now))
        return packets

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.dash) or super().blocked(action,now)

    def interrupt(self,now):
        packets=[]
        if self.ready:
            self.ready=None;self.cooldowns[2]=now+self.skill_cooldown(5000, 2)
            packets.extend(((1583,struct.pack('<II',self.id,318301)),self._cooldown(2)))
        if self.dash:
            self.dash=None
            packets.extend(self.remove_buff(318416,now))
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        if self.ready and int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']) in (30,35,66):
            return self.interrupt(now)
        return []

    def update(self,now):
        self.assists={k:v for k,v in self.assists.items() if v['end']>now}
        self.e_hits={k:v for k,v in self.e_hits.items() if v['end']>now}
        packets=self.interrupt(now) if self.ready and self.skill_sealed(2,now) else []
        return packets+super().update(now)

    def _basic_hit(self,flight,target,now):
        current=self.alive and self.generation==flight['source_generation']
        enhanced=flight['template']==318211;raw=flight['raw']
        if enhanced:
            distance=math.dist(self.position_at(now),target.position_at(now))
            raw*=D('.75')+min(D(1),D(str(distance))/480)
        if target.has_buff(318313,now) and target.buff_sources.get(318313)==self.id:raw*=D('1.5')
        packets=self._deal(target,raw,now,generation=flight['source_generation'],basic=True,
                           lifesteal=flight['lifesteal'] if current else 0)
        if current:
            from medusa_actions import MedusaActions
            packets.extend(MedusaActions._drain_mp(target,5,now)+self._resource(5))
            for slot,base in ((1,5000),(2,25000),(10,8000)):
                self.cooldowns[slot]=max(now,self.cooldowns[slot]-base//20)
                packets.append(self._cooldown(slot))
        if enhanced and target.alive:
            key=flight['source_generation'],target.id,target.generation
            mark=self.e_hits.get(key)
            count=mark['count'] if mark and mark['end']>now else 0
            for t in (318212,318213,318214):
                if target.buff_sources.get(t)==self.id:packets.extend(target.remove_buff(t,now))
            if count==3:
                self.e_hits.pop(key,None)
                packets.extend(self._deal(target,target.max_hp*D('.1'),now,generation=flight['source_generation'],school='true'))
                packets.extend(self._buff(318216,now,target.id))
            else:
                self.e_hits[key]=dict(count=count+1,end=now+1500)
                packets.extend(self._buff(318212+count,now,target.id))
        return packets

    def _vortex(self,flight,pos,now):
        packets=[]
        for target in enemies(self,area=True):
            if math.dist(pos,target.position_at(now))<=144:
                packets.extend(self._deal(target,flight['power']*D('3.5'),now,generation=flight['source_generation']))
                packets.extend(self._buff(318302,now,target.id)+self._buff(318303,now,target.id))
        ident,packet=self.add_object(318304,pos);packets.append(packet)
        self.fields[ident]=dict(pos=pos,power=flight['power'],generation=flight['source_generation'])
        self._queue(now+500,'naruto_vortex',ident,1)
        return packets

    def _flight(self,flight,now):
        if flight['template']!=318301:
            return piercing_step(self,flight,now,self._basic_hit,pierce=flight['template']==318211)
        start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        contacts=[(hit,t.id,t) for t in enemies(self)
                  if (hit:=actor_contact(start,end,t,flight['previous'],now)) is not None]
        contact=min(contacts,key=lambda v:v[:2]) if contacts else None
        ident=struct.pack('<I',flight['id'])
        if contact and self.projectile_blocked(contact[2],now):return [scene(expired_bullets=(ident,))]
        if contact or now>=flight['finish']:
            pos=tuple(round(v) for v in point_at(start,end,contact[0] if contact else 1))
            return [scene(blown_bullets=(ident,))]+self._vortex(flight,pos,now)
        flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
        return []

    def _event(self,now,kind,data):
        if kind=='naruto_energy':
            if data[0]!=self.generation or not self.alive:return []
            self._queue(now+3000,kind,self.generation)
            return self._resource(10)
        if kind=='naruto_space':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None
            return self.shoot(318301,cast['start'],cast['dest'],now,0,school='physical',power=cast['power'],through_walls=True)+self.sync_speed(now)
        if kind=='naruto_vortex':
            ident,index=data;cast=self.fields.get(ident)
            if cast is None:return []
            packets=[]
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))<=144:
                    packets.extend(self._buff(318311,now,target.id)+self._buff(318313,now,target.id))
                    packets.extend(self._deal(target,cast['power']*D('.5'),now,generation=cast['generation'],periodic=True))
            if index<8:self._queue(now+500,kind,ident,index+1)
            else:
                self.fields.pop(ident,None);packets.extend(self.remove_object(ident,destroyed=True))
            return packets
        if kind=='naruto_dash':
            cast,=data
            if self.dash is not cast or not self.alive:return []
            start,end=self.position_at(cast['previous']),self.position_at(now)
            contacts=[(hit,t.id,t) for t in enemies(self)
                      if (hit:=actor_contact(start,end,t,cast['previous'],now)) is not None]
            if contacts:
                hit,_,_=min(contacts,key=lambda v:v[:2])
                impact=tuple(round(v) for v in point_at(start,end,hit))
                # Contact can occur while crossing a wall. The last 20ms ray
                # may already start inside it; resolve the body from the full
                # dash origin before starting the retreat, as for hard CC.
                pos=self.stop_position(now,impact)
                self.dash=None;self.position,self.motion=pos,None
                packets=self.remove_buff(318416,now)+[stop_move(self.scene_id,self.id,pos),
                    scene(skills=(self._skill_event(318411,impact,cast['dest']),))]
                for target in enemies(self,area=True):
                    # The collision point still owns the blast/pull geometry;
                    # moving the body out of a wall must not move its damage.
                    tpos=target.position_at(now);distance=math.dist(impact,tpos)
                    if distance>144:continue
                    packets.extend(self._deal(target,cast['power']*D('1.96'),now))
                    if self.arena.pk and self.arena.pk['finished']:
                        return packets
                    if target.alive and not target.cc_immune(now) and distance>72:
                        body,stopped=prepare_displacement(target,now,interrupt=False)
                        # Damage can return a living form and already resolve its
                        # body. Keep that result; tpos still owns hit/range/aim.
                        dest=target.move_destination(body,point_at(impact,tpos,72/distance));packets.extend(target.interrupt(now))
                        packets.extend(stopped)
                        target.position,target.motion,target.forced_until=dest,None,now
                        packets.append(scene(moves=(self._move_event(dest,0,5,target.id),)))
                    packets.extend(self._buff(318413,now,target.id))
                dest=(pos[0]-cast['direction'][0]*240,pos[1]-cast['direction'][1]*240)
                duration=self._set_motion(pos,dest,960,now,kind=4);self.forced_until=now+duration
                return packets+self._resource(25)+self._buff(318414,now)+self._buff(318415,now)+[scene(moves=(self._move_event(self.motion[1],960,4),))]
            if not self.motion or now>=self.motion[3]:
                self.dash=None
                return self.remove_buff(318416,now)
            cast['previous']=now;self._queue(min(now+20,self.motion[3]),kind,cast)
            return []
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot in (0,2,10) and start==dest:return []
        cost={0:0,1:25,2:50,10:25}[slot]
        if self.mp<cost:return []
        power=self.combat_stat('iAttack',now);packets=self._resource(-cost);handoff=[]
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:5000,2:25000,10:8000}[slot], slot)
        if slot==0:
            enhanced=self.shots>0 and self.has_buff(318201,now);nine=self.has_buff(318111,now)
            packets.extend(self.shoot(318211 if enhanced else 318100,start,dest,now,power*(D('1.5') if nine else 1),
                school='physical',basic=True,lifesteal=D('.5') if nine else 0,through_walls=enhanced))
            if enhanced:
                self.shots-=1
                if not self.shots:packets.extend(self.remove_buff(318201,now))
        elif slot==1:
            self.shots=4
            packets.extend(self._buff(318201,now)+self._buff(318202,now))
            packets.append(self._cooldown(0,True))
        elif slot==2:
            body,handoff=prepare_displacement(self,now,interrupt=False)
            if not handoff: body=start
            self.position,self.motion=body,None
            self.ready=dict(slot=2,start=start,dest=dest,power=power,end=now+500)
            self._queue(now+500,'naruto_space',self.ready)
            packets.append(scene(skills=(self._skill_event(318301,start,dest,ready=1),)))
        else:
            distance=math.dist(start,dest);direction=((dest[0]-start[0])/distance,(dest[1]-start[1])/distance)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            if not stopped: body=start
            duration=self._set_motion(body,aimed(start,dest,480),960,now,kind=3);self.forced_until=now+duration
            self.dash=dict(start=start,dest=self.motion[1],power=power,previous=now,direction=direction)
            self._queue(now+min(20,duration),'naruto_dash',self.dash)
            packets.extend(self._buff(318402,now)+self._buff(318416,now))
            packets.extend(stopped)
            packets.extend((scene(skills=(self._skill_event(318401,start,self.motion[1]),)),scene(moves=(self._move_event(self.motion[1],960,3),))))
        return packets+[self._cooldown(slot)]+self.sync_speed(now)+handoff
