"""Zhao Yun: separate charge clocks, real-HP rage and a damage-free Space."""
from battle_participants import human, private
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene,stop_move
from melee_common import aimed,enemies,in_cone,in_strip,prepare_displacement

SLOTS={0:342100,1:342201,2:342301,10:342401}


class ZhaoYunActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.e_count=self.r_count=2
        self.e_next_charge=self.r_next_charge=0
        self.rage_damage=D(0)
        self.ready=self.channel=self.dash=None
        self.r_visual=None

    def _cooldown(self,slot):
        count=self.e_count if slot==1 else self.r_count if slot==10 else -1
        next_charge=self.e_next_charge if slot==1 else self.r_next_charge if slot==10 else 0
        return 1572,props(SLOTS[slot],slot,count,self.cooldowns[slot],next_charge)+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.rage_damage=D(0)
        return self._buff(342101,now)

    def attr_bonus(self,attributes,now):
        value=super().attr_bonus(attributes,now)
        if 2 in attributes and self.has_buff(342102,now):
            value+=D('.05')*self.buff_stacks[342102]  # Source 10%, user chose 15%.
        return value

    def damage(self,raw,now,**kwargs):
        current=self.alive
        flight=getattr(self.arena,'current_flight',None)
        if flight:
            current=current and flight['source_generation']==self.generation
        if current:
            count=self.buff_stacks.get(342103,0) if self.has_buff(342103,now) else 0
            kwargs['lifesteal']=(D('.25') if kwargs.get('basic') else D('.5'))+D('.15')*count
        return super().damage(raw,now,**kwargs)

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        if not self.alive or hit.hp_loss<=0:
            return []
        count=min(10,(self.buff_stacks.get(342102,0) if self.has_buff(342102,now) else 0)+1)
        packets=self._buff(342102,now,stacks=count)+self._buff(342103,now,stacks=count)
        self.rage_damage+=hit.hp_loss
        count=int(self.rage_damage//(self.max_hp*D('.05')))
        self.rage_damage-=count*self.max_hp*D('.05')
        for slot,field in ((1,'e_next_charge'),(10,'r_next_charge')):
            if count and getattr(self,field):
                setattr(self,field,max(now,getattr(self,field)-500*count))
                packets.append(self._cooldown(slot))
        return packets

    def _speed(self,now):
        return 0 if self.ready or self.channel else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.channel or self.dash) or super().blocked(action,now)

    def _stop_packets(self,packets,position,movement=()):
        # Install ready/auto-move before stopMoveAt retries held movement;
        # never let the old walking tween finish after selfSpeed becomes zero.
        attrs=[p for p in packets if p[0]==1560]
        stop=stop_move(self.scene_id,self.id,position)
        return [p for p in packets if p[0]!=1560 and p!=stop and p not in movement]+[stop]+list(movement)+attrs

    def interrupt(self,now):
        packets=[]
        if self.ready or self.channel or self.dash:
            pos=self.position_at(now)
            if self.dash:
                origin=self.motion[0] if self.motion else self.dash.get('start',pos)
                pos=self.move_destination(origin,pos)
            self.position,self.motion=pos,None
            packets.append(stop_move(self.scene_id,self.id,pos))
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,342301)))
        if self.channel or self.r_visual:
            packets.append((1583,struct.pack('<II',self.id,342401)))
        controlled=bool(self.channel or self.dash)
        self.r_visual=None
        self.ready=self.channel=self.dash=None
        self.forced_until=now
        if controlled:
            for template in (342211,342402,342403,50353):
                packets.extend(self.remove_buff(template,now))
        return packets+self.sync_speed(now)

    def update(self,now):
        packets=[]
        for slot,prefix in ((1,'e'),(10,'r')):
            count,next_charge=getattr(self,prefix+'_count'),getattr(self,prefix+'_next_charge')
            while next_charge and next_charge<=now:
                count=min(2,count+1);next_charge=next_charge+self.skill_cooldown(8000) if count<2 else 0
                setattr(self,prefix+'_count',count);setattr(self,prefix+'_next_charge',next_charge)
                packets.append(self._cooldown(slot))
        if self.ready and self.skill_sealed(2,now):
            packets.extend(self.interrupt(now))
        return packets+super().update(now)

    def _event(self,now,kind,data):
        if kind=='zhao_visual_end':
            cast,=data
            if self.r_visual is not cast:return []
            self.r_visual=None
            return [(1583,struct.pack('<II',self.id,342401))]
        if kind=='zhao_dash':
            cast,=data
            if self.dash is not cast or not self.alive:
                return []
            start,end=self.position_at(cast['previous']),self.position_at(now)
            packets=[]
            for target in enemies(self):
                key=target.id,target.generation
                if key in cast['hits'] or actor_contact(start,end,target,cast['previous'],now) is None:
                    continue
                cast['hits'].add(key)
                packets.extend(self.damage(cast['power']*D('2.06'),now,target=target)[0])
                for t in (342205,342206,342208):
                    packets.extend(self._buff(t,now,target.id))
                packets.extend(self._buff(342207,now,duration=3000))
                if target.alive and not target.cc_immune(now) and self.motion:
                    packets.extend(target.interrupt(now))
                    duration=target._set_motion(target.position_at(now),self.motion[1],600,now,kind=1)
                    target.forced_until=now+duration
                    packets.append(scene(moves=(self._move_event(target.motion[1],600,1,target.id),)))
            if not self.motion or now>=min(cast['end'],self.motion[3]):
                self.position,self.motion=end,None
                packets.append(stop_move(self.scene_id,self.id,end))
                self.dash=None;self.forced_until=now
                packets.extend(self.remove_buff(342211,now)+self.remove_buff(50353,now))
                return packets
            cast['previous']=now;self._queue(min(now+20,self.motion[3]),kind,cast)
            return packets
        if kind=='zhao_stab':
            cast,index=data
            if self.channel is not cast or not self.alive:
                return []
            start=self.position_at(now)
            # iMultiType=5 loops until S1583. Reusing its key without stopping
            # first strands the previous MovieClip in EffectLayer forever.
            packets=[(1583,struct.pack('<II',self.id,342401))] if self.r_visual else []
            self.r_visual=cast
            packets.append(scene(skills=(self._skill_event(342401,start,cast['dest']),)))
            for target in enemies(self,area=True):
                if in_cone(target.position_at(now),start,cast['dest'],240,90):
                    raw=cast['power']*D('.5')
                    if target.has_buff(342208,now) and target.buff_sources.get(342208)==self.id:
                        raw*=D('1.25')
                    packets.extend(self.damage(raw,now,target=target)[0])
            if index==5:
                self.channel=None
                self._queue(now+200,'zhao_visual_end',cast)
                packets.append(stop_move(self.scene_id,self.id,start))
                packets.extend(self.remove_buff(342402,now)+self.remove_buff(342403,now)
                               +self.remove_buff(50353,now)+self.sync_speed(now))
            elif human(self) and not cast['aim_pending']:
                cast['aim_pending']=True
                packets.append(private(self,(1590,b'')))
            return packets
        if kind=='zhao_field':
            cast,=data
            if self.ready is not cast or not self.alive:
                return []
            self.ready=None
            packets=[];cast['targets']=[]
            for target in enemies(self,area=True):
                if in_strip(target.position_at(now),cast['start'],cast['dest'],480,192):
                    version=target.buff_versions.get(342304,0)
                    packets.extend(self._buff(342304,now,target.id))
                    # Capture only a successfully rooted life. A rejected first
                    # root must not become a delayed pull after immunity ends.
                    if target.buff_versions.get(342304,0)!=version:
                        cast['targets'].append((target.id,target.generation))
            self._queue(now+1000,'zhao_pull',cast)
            return packets+self.sync_speed(now)
        if kind=='zhao_pull':
            cast,=data
            center=point_at(cast['start'],cast['dest'],.5)
            packets=[]
            for ident,generation in cast['targets']:
                target=self.arena.actors.get(ident)
                if (not target or not target.alive or target.generation!=generation
                        or not target.is_area_targetable() or target.cc_immune(now)):
                    continue
                version=target.buff_versions.get(342304,0)
                # Revalidate the native protection/rejection rules at impact.
                # _buff stops the whole old motion at a valid tank position;
                # do not sample an in-wall dash point before interrupting it.
                packets.extend(self._buff(342304,now,target.id))
                if (target.buff_versions.get(342304,0)==version or not target.alive
                        or not target.is_area_targetable() or target.cc_immune(now)):
                    continue
                packets.extend(target.interrupt(now))
                pos=target.stop_position(now)
                target.position,target.motion=target.move_destination(pos,center),None
                packets.append(stop_move(self.scene_id,target.id,target.position))
            return packets
        return super()._event(now,kind,data)

    def handle(self,message,payload):
        if message==510:
            packets=self.arena.tick(self.clock())
            if not self.arena.input_open(self.clock(),self):return packets
            if self.channel and self.channel['aim_pending'] and len(payload)>=12:
                scene_id,_,_,x,y=struct.unpack_from('<Ihhhh',payload)
                if scene_id==self.scene_id:
                    self.channel['dest']=x,y
                    self.channel['aim_pending']=False
            return packets
        if message==514:
            packets=self.arena.tick(self.clock())
            if not self.arena.input_open(self.clock(),self):return packets
            if self.channel and len(payload)==8:
                scene_id,x,y=struct.unpack_from('<Ihh',payload)
                if scene_id==self.scene_id:
                    self.channel['dest']=x,y
            return packets
        return super().handle(message,payload)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if start==dest or not self._inside(dest) or slot==1 and not self.e_count or slot==10 and not self.r_count:
            return []
        power=self.combat_stat('iAttack',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:1500,2:25000,10:1500}[slot], slot)
        if slot in (1,10):
            prefix='e' if slot==1 else 'r'
            setattr(self,prefix+'_count',getattr(self,prefix+'_count')-1)
            if not getattr(self,prefix+'_next_charge'):
                setattr(self,prefix+'_next_charge',now+self.skill_cooldown(8000))
        packets=[self._cooldown(slot)]
        if slot==0:
            return packets+self.shoot(342100,start,dest,now,power,school='physical',basic=True)
        if slot==1:
            intended=aimed(start,dest,360,fixed=True)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            body=body if stopped else start
            duration=self._set_motion(body,intended,600,now,kind=3)
            self.forced_until=now+duration
            self.dash=dict(start=start,previous=now,end=now+duration,power=power,hits=set(),generation=self.generation)
            self._queue(now+min(20,duration),'zhao_dash',self.dash)
            packets+=self._buff(50353,now)+self._buff(342211,now,duration=duration)
            return self._stop_packets(packets,body,[scene(moves=(self._move_event(self.motion[1],600,3),))])
        body,stopped=prepare_displacement(self,now,interrupt=False)
        body=body if stopped else start
        self.position,self.motion=body,None
        if slot==10:
            self.channel=dict(dest=dest,power=power,generation=self.generation,end=now+1000,aim_pending=human(self))
            for index in range(1,6):
                self._queue(now+index*200,'zhao_stab',self.channel,index)
            packets+=self._buff(50353,now)+self._buff(342402,now,duration=1000)+self._buff(342403,now,duration=1000)
            return self._stop_packets(packets+([private(self,(1590,b''))] if human(self) else [])+self.sync_speed(now),body)
        self.ready=dict(slot=2,start=start,dest=aimed(start,dest,480,fixed=True),generation=self.generation)
        self._queue(now+100,'zhao_field',self.ready)
        return self._stop_packets(packets+[scene(skills=(self._skill_event(342301,start,self.ready['dest'],ready=1),))]+self.sync_speed(now),body)
