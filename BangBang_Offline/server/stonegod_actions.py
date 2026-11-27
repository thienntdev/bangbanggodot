"""Stone God: buried recovery, an annular storm and native host attachment."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,piercing_step,prepare_displacement

SLOTS={0:384100,1:384201,2:384301,10:384401}
BURROW=(384201,384202,384203,384204,384205,384206,384207,384208,384209,384210,384217,384218)
STORM=(384401,384402,384414,384415,384416,384417,384418,384431)


class StoneGodActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.burrow=self.storm=self.dash=self.attach=None

    def _cooldown(self,slot,changed=False):
        skill=SLOTS[slot]
        if slot==1 and self.burrow and self.clock()<self.burrow['phase_end']:skill=384211
        if slot==10 and self.storm and self.storm['count']==5:skill=384421
        body=props(skill,slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=self.burrow=self.storm=self.dash=self.attach=None
        self._queue(now+3000,'stone_shield',self.generation)
        return self._buff(384101,now)+self._buff(384103,now)+[self._cooldown(s,True) for s in SLOTS]

    def blocked(self,action,now):
        return bool(self.ready or self.burrow or self.attach or self.dash) or super().blocked(action,now)

    def _speed(self,now):
        return 0 if self.ready or self.burrow or self.attach else super()._speed(now)

    def is_untargetable(self):
        now=getattr(self.arena,'event_now',None) or self.clock()
        return bool(self.attach) or super().is_untargetable() or (self.has_buff(384208,now) and 32 not in self.buff_types(now))

    def cc_immune(self,now,*,slow=False):return bool(self.attach) or super().cc_immune(now,slow=slow)

    def is_area_targetable(self):
        return not self.attach and (bool(self.burrow) or super().is_area_targetable())

    def reject_buff(self,row,source,now):return bool(self.attach) and source.camp!=self.camp

    def position_at(self,now):
        cast=self.attach
        if cast:
            target=self.arena.actors.get(cast['target'])
            if target and target.generation==cast['target_generation']:
                # Cyclic Stone-God attachment is prevented at target selection.
                return target.position_at(now)
        return super().position_at(now)

    def _end_storm(self,now):
        if not self.storm:return []
        self.storm=None;self.cooldowns[10]=now+self.skill_cooldown(6000, 10);packets=[]
        for t in STORM:packets.extend(self.remove_buff(t,now))
        return packets+[self._cooldown(10,True),self._cooldown(10)]

    def _end_burrow(self,now):
        if not self.burrow:return []
        self.burrow=None;self.cooldowns[1]=now+self.skill_cooldown(8000, 1);packets=[]
        for t in BURROW:packets.extend(self.remove_buff(t,now))
        return packets+[self._cooldown(1,True),self._cooldown(1)]

    def _end_attach(self,now,*,burst=True):
        cast=self.attach
        if not cast:return []
        pos=self.position_at(now);self.attach=None
        self.info['damage_immune']=cast['was_immune']
        self.position=self.blink_destination(cast['origin'],pos);self.motion=None
        packets=[];target=self.arena.actors.get(cast['target'])
        if target and target.generation==cast['target_generation']:
            for t in (384321,384322,384331,384335,384336,384337,384338,384340):
                if target.buff_sources.get(t)==self.id:packets.extend(target.remove_buff(t,now))
        for t in (384311,384312,384333):packets.extend(self.remove_buff(t,now))
        packets.append(scene(moves=(self._move_event(self.position,0,5),)))
        if burst and self.alive:
            packets.append(scene(skills=(self._skill_event(384341,self.position,self.position),)))
            for enemy in enemies(self,area=True):
                if math.dist(self.position,enemy.position_at(now))<=168:
                    packets.extend(self.damage(cast['power']*D('2.24'),now,target=enemy)[0])
                    packets.extend(self._buff(384342,now,enemy.id))
            for ally in self.arena.actors.values():
                if ally.alive and ally.camp==self.camp and math.dist(self.position,ally.position_at(now))<=168:
                    packets.extend(ally.add_shield(384343,cast['max_hp']*D('.2'),now,caster=self))
        return packets+self.sync_speed(now)

    def on_target_death(self,target,now):
        return self._end_attach(now) if self.attach and self.attach['target']==target.id else []

    def interrupt(self,now):
        if self.ready and self.ready['slot']==1 and self.alive:return []
        packets=[]
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            if 'object' in self.ready:packets.extend(self.remove_object(self.ready['object']))
            self.ready=None
        if self.dash:
            self.position,self.motion=self.stop_position(now),None;self.dash=None;self.forced_until=now
            packets.extend(self.remove_buff(384302,now))
            packets.append(scene(moves=(self._move_event(self.position,0,5),)))
        if not self.alive:
            packets.extend(self._end_burrow(now)+self._end_storm(now)+self._end_attach(now,burst=False))
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        row=table_row('BuffTemplate_table.xml',nBuffId=template)
        return self.interrupt(now) if row['nEffectType'] in ('30','35','66') else []

    def _flight(self,flight,now):
        def hit(f,target,due):
            packets=self.damage(f['raw'],due,target=target,basic=f['basic'])[0]
            if not f['basic']:packets.extend(self._buff(384422,due,target.id)+self._buff(384423,due,target.id))
            return packets
        return piercing_step(self,flight,now,hit,pierce=flight['template']==384421)

    def _emerge(self,cast,now):
        if self.ready is not cast or not self.alive:return []
        self.ready=None
        pos=self.blink_destination(self.position_at(now),cast['dest'])
        packets=self._end_burrow(now)+self.remove_object(cast['object'],destroyed=True)
        self.position,self.motion=pos,None
        packets.extend([scene(moves=(self._move_event(pos,0,5),),skills=(self._skill_event(384211,pos,pos),))])
        for target in enemies(self,area=True):
            if math.dist(pos,target.position_at(now))>168:continue
            packets.extend(self.damage(cast['power']*D('1.62'),now,target=target)[0])
            packets.extend(self._buff(384222,now,target.id))
            self._queue(now+100,'stone_fall',target.id,target.generation,now+1000)
        return packets+self.sync_speed(now)

    def _event(self,now,kind,data):
        if kind=='stone_shield':
            if not self.alive or self.generation!=data[0]:return []
            self._queue(now+3000,kind,*data)
            return self.add_shield(384111,self.max_hp*D('.05'),now)
        if kind=='stone_burrow':
            cast,=data
            if self.burrow is not cast or not self.alive:return []
            packets=self.restore_hp((self.max_hp-self.hp)*D('.05'),now)
            if now==cast['begin']+1000:
                for t in (384208,384217,384218):packets.extend(self._buff(t,now))
            if now==cast['phase_end']:packets.append(self._cooldown(1,True))
            if now==cast['begin']+3500 and not self.ready:
                ident,packet=self.add_object(384213,self.position_at(now));packets.append(packet)
                self.ready=dict(slot=1,skill=384211,dest=self.position_at(now),power=cast['power'],generation=self.generation,object=ident)
                self._queue(now+500,'stone_emerge',self.ready)
            return packets
        if kind=='stone_emerge':return self._emerge(data[0],now)
        if kind=='stone_fall':
            ident,generation,finish=data;target=self.arena.actors.get(ident)
            if not target or not target.alive or target.generation!=generation:return []
            if target.has_buff(384222,now) and now<finish:
                self._queue(min(now+100,finish),kind,*data);return []
            return self._buff(384223,now,target.id,duration=2000)
        if kind=='stone_storm':
            cast,=data
            if self.storm is not cast or not self.alive:return []
            packets=[]
            if cast['count']<5 and cast['phase_end']<=now:
                cast['count']=0
                for t in range(384414,384418):packets.extend(self.remove_buff(t,now))
            for target in enemies(self,area=True):
                distance=math.dist(self.position_at(now),target.position_at(now))
                if distance>192:continue
                packets.extend(self._buff(384411,now,target.id))
                if distance<=120:packets.extend(self._buff(384412,now,target.id))
                result,lost=self.damage(cast['power']*D('.25')*(5 if distance>120 else 1),now,target=target)
                packets.extend(result)
                if lost and cast['count']<5:
                    for t in range(384414,384418):packets.extend(self.remove_buff(t,now))
                    cast['count']+=1;cast['phase_end']=now+3000
                    packets.extend(self._buff(384413+cast['count'],now))
                    if cast['count']==5:
                        cast['phase_end']=now+5000
                        packets.extend(self.remove_buff(384402,now)+self._buff(384431,now))
                        self.cooldowns[10]=now;packets.append(self._cooldown(10,True))
                        self._queue(cast['phase_end'],'stone_storm_end',cast)
            if now<cast['end']:self._queue(min(now+500,cast['end']),kind,cast)
            elif cast['count']<5:packets.extend(self._end_storm(now))
            return packets
        if kind=='stone_storm_end':return self._end_storm(now) if self.storm is data[0] else []
        if kind=='stone_cast':
            cast,=data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:return []
            self.ready=None;packets=self.sync_speed(now);start=self.position_at(now)
            if cast['slot']==10:
                angle=math.atan2(cast['dest'][1]-start[1],cast['dest'][0]-start[0])
                for deg in (0,72,-72,144,-144):
                    dest=(round(start[0]+480*math.cos(angle+math.radians(deg))),round(start[1]+480*math.sin(angle+math.radians(deg))))
                    packets.extend(self.shoot(384421,start,dest,now,cast['power']*D('2.08'),school='physical',through_walls=True))
                return packets
            duration=self._set_motion(start,aimed(start,cast['dest'],480,fixed=True),960,now,3)
            self.forced_until=now+duration
            cast.update(previous=now,end=now+duration,origin=start);self.dash=cast
            packets.extend(self._buff(384302,now,duration=duration))
            packets.append(scene(moves=(self._move_event(self.motion[1],960,3),)))
            self._queue(now+min(20,duration),'stone_dash',cast)
            return packets
        if kind=='stone_dash':
            cast,=data
            if self.dash is not cast or not self.alive:return []
            start,end=self.position_at(cast['previous']),self.position_at(now)
            contacts=[]
            for target in self.arena.actors.values():
                if target is self or not target.alive or target.info.get('npc_template') or target.is_untargetable() or getattr(target,'attach',None):continue
                hit=actor_contact(start,end,target,cast['previous'],now)
                if hit is not None:contacts.append((hit,target.id,target))
            if contacts:
                _,_,target=min(contacts,key=lambda v:v[:2]);self.dash=None;self.motion=None;self.forced_until=now
                cast.update(target=target.id,target_generation=target.generation,end=now+5000,
                            was_immune=self.info.get('damage_immune',False),max_hp=self.max_hp)
                self.attach=cast;self.info['damage_immune']=True
                packets=self.remove_buff(384302,now)
                for t in (384311,384312):packets.extend(self._buff(t,now,duration=5000))
                for t in (384321,384322):packets.extend(self._buff(t,now,target.id))
                self._queue(now+500,'stone_attach',cast)
                return packets+self.sync_speed(now)
            if now>=cast['end'] or not self.motion or now>=self.motion[3]:
                self.dash=None;self.forced_until=now
                return self.remove_buff(384302,now)
            cast['previous']=now;self._queue(min(now+20,cast['end']),kind,cast);return []
        if kind=='stone_attach':
            cast,=data
            if self.attach is not cast or not self.alive:return []
            target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation']:return self._end_attach(now)
            packets=[scene(skills=(self._skill_event(384331,self.position_at(now),target.position_at(now),target.id),))]
            packets.extend(self._buff(384333,now,duration=min(600,max(1,cast['end']-now))))
            if target.camp==self.camp:
                packets.extend(target.add_shield(384334,cast['max_hp']*D('.1'),now,caster=self))
                for t in (384335,384336):packets.extend(self._buff(t,now,target.id))
            else:
                for t in (384337,384338):packets.extend(self._buff(t,now,target.id))
                packets.extend(self.damage(cast['power']*D('.35'),now,target=target,periodic=True)[0])
            if self.attach is not cast:return packets
            packets.extend(self._buff(384340,now,target.id))
            if now>=cast['end']:packets.extend(self._end_attach(now))
            else:self._queue(now+500,kind,cast)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        e2=slot==1 and self.burrow and self.burrow['begin']+1000<=now<self.burrow['phase_end'] and not self.ready
        r2=slot==10 and self.storm and self.storm['count']==5
        if slot not in SLOTS or not self.alive or self.skill_sealed(slot,now) or self.blocked('attack',now) and not e2 or now<self.cooldowns[slot]:return []
        if slot in (0,2) or r2:
            if start==dest:return []
        power=self.combat_stat('iAttack',now);packets=[];stopped=[]
        if slot==0:
            self.cooldowns[0]=now+self.fire_interval(now)
            return self.shoot(384100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        if e2:
            if not self._inside(dest) or math.dist(start,dest)>480:return []
            dest=self.blink_destination(start,dest)
            ident,packet=self.add_object(384213,dest);packets.append(packet)
            self.ready=dict(slot=1,skill=384211,dest=dest,power=power,generation=self.generation,object=ident)
            packets.extend(self.remove_buff(384207,now))
            self.burrow['phase_end']=now
            self._queue(now+500,'stone_emerge',self.ready)
            packets.append(scene(skills=(self._skill_event(384211,start,dest,ready=1),)))
        elif slot==1:
            body,stopped=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body if stopped else start,None
            self.burrow=dict(begin=now,end=now+4000,phase_end=now+3000,power=power,generation=self.generation)
            self.cooldowns[1]=now+1000
            for t in (*range(384201,384208),384209,384210):packets.extend(self._buff(t,now))
            packets.extend(self.add_shield(384111,self.max_hp*D('.05'),now))
            for delay in range(500,4001,500):self._queue(now+delay,'stone_burrow',self.burrow)
            packets.extend([self._cooldown(1,True),scene(skills=(self._skill_event(384201,start,start),))])
        elif slot==10 and not r2:
            self.storm=dict(begin=now,end=now+5000,count=0,phase_end=now+3000,power=power)
            self.cooldowns[10]=now+5000
            packets.extend(self._buff(384401,now)+self._buff(384402,now))
            self._queue(now+500,'stone_storm',self.storm)
        else:
            packets.extend(self._end_storm(now))
            if slot==2:self.cooldowns[2]=now+self.skill_cooldown(30000, 2)
            skill=384421 if slot==10 else 384301
            body,stopped=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body if stopped else start,None
            self.ready=dict(slot=slot,skill=skill,dest=dest,power=power,generation=self.generation)
            self._queue(now+(150 if slot==10 else 300),'stone_cast',self.ready)
            packets.append(scene(skills=(self._skill_event(skill,start,dest,ready=1),)))
        return packets+[self._cooldown(slot)]+self.sync_speed(now)+stopped
