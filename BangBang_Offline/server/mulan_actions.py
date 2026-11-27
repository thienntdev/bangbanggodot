"""Hoa Moc Lan: carried sweeps, persistent sword field and charged rectangle."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,in_strip,piercing_step,prepare_displacement

SLOTS={0:374100,1:374201,2:374301,10:374401}
MARKS=(374111,374112,374113,374114)
E_BUFFS=(374204,374205,374206,374207,374211)
CHARGE_BUFFS=(374311,374312,374313,374314,374315)


class MulanActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.dash=None
        self.fields={}
        self.r_window=dict(end=0)

    def _cooldown(self,slot,changed=False):
        skill=SLOTS[slot]
        if slot==2 and self.ready:skill=374321
        if slot==10 and self.r_window['end']>self.clock():skill=374411
        body=props(skill,slot,end=0 if skill in (374321,374411) else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=self.dash=None;self.r_window=dict(end=0)
        return self._buff(374101,now)+self._buff(374102,now)+[self._cooldown(2,True),self._cooldown(10,True)]

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.dash) or super().blocked(action,now)

    def cc_immune(self,now,*,slow=False):
        return (bool(self.ready or self.dash) or self.has_buff(374125,now) or self.has_buff(374414,now)
                or super().cc_immune(now,slow=slow))

    def _mark(self,target,now):
        if not target.alive or target.reject_buff({'nEffectType':'49'},self,now):return []
        count=max((i+1 for i,t in enumerate(MARKS) if target.has_buff(t,now) and target.buff_sources.get(t)==self.id),default=0)
        packets=[]
        for template in MARKS:packets.extend(target.remove_buff(template,now))
        if count<4:return packets+self._buff(MARKS[count],now,target.id)
        packets.extend(self.damage(target.max_hp*D('.08'),now,target=target)[0])
        packets.extend(self._buff(374122,now,target.id))
        for template in (374123,374124):packets.extend(self._buff(template,now,target.id,duration=2000))
        return packets+self._buff(374125,now)+self._buff(374126,now)

    def _hit(self,target,raw,generation,now,*,basic=False,school='physical',periodic=False):
        packets,lost=self.damage(raw,now,target=target,basic=basic,school=school,periodic=periodic)
        if lost and self.alive and self.generation==generation:packets.extend(self._mark(target,now))
        return packets

    def _flight(self,flight,now):
        return piercing_step(self,flight,now,lambda f,t,n:self._hit(t,f['raw'],f['source_generation'],n,basic=True),pierce=False)

    def _end_dash(self,now):
        self.dash=None
        self.position,self.motion,self.forced_until=self.position_at(now),None,now
        packets=[]
        for template in (*E_BUFFS,374431):packets.extend(self.remove_buff(template,now))
        return packets

    def _clear_charge(self,now):
        packets=[]
        for template in CHARGE_BUFFS:packets.extend(self.remove_buff(template,now))
        return packets+[self._cooldown(2,True)]+self.sync_speed(now)

    def interrupt(self,now):
        if self.alive:return []
        self.ready=None;self.r_window=dict(end=0)
        return self._end_dash(now)+self._clear_charge(now)+[self._cooldown(10,True)]

    def update(self,now):
        packets=[]
        if self.r_window['end'] and now>=self.r_window['end']:
            self.r_window=dict(end=0);packets.append(self._cooldown(10,True))
        return packets+super().update(now)

    def _move_target(self,target,dest,speed,now):
        if not target.alive or target.cc_immune(now):return []
        start,packets=prepare_displacement(target,now)
        target.forced_until=now+target._set_motion(start,dest,speed,now,kind=1)
        return packets+[scene(moves=(self._move_event(target.motion[1],speed,1,target.id),))]

    def _swing(self,target,cast,index,now):
        key=target.id,target.generation
        if key in cast['swing_hits'][index]:return []
        cast['swing_hits'][index].add(key)
        packets=self._hit(target,cast['power']*(D('1.27'),D('1.59'),D('1.98'))[index],cast['generation'],now)
        if self.arena.pk and self.arena.pk['finished']:
            return packets
        packets.extend(self._buff(374213,now,target.id))
        if index==2:
            packets.extend(self.damage(target.max_hp*D('.03'),now,target=target,school='true')[0])
            packets.extend(self._buff(374233,now,target.id))
        return packets

    def _release(self,cast,now):
        if self.ready is not cast or not self.alive:return []
        self.ready=None
        fraction=min(1,max(0,(now-cast['begin'])/3000));length=120+360*fraction
        start=self.position_at(now);dest=cast['dest'];power=cast['power']*D('2.23')*(1+D(str(fraction)))
        packets=self._clear_charge(now)+[(1583,struct.pack('<II',self.id,374301)),scene(skills=(self._skill_event(374301,start,dest),))]
        for target in enemies(self,area=True):
            if in_strip(target.position_at(now),start,dest,length,300):
                packets.extend(self._hit(target,power,self.generation,now))
                if self.arena.pk and self.arena.pk['finished']:
                    return packets
                packets.extend(self._buff(374213,now,target.id))
                origin=target.position_at(now);dx,dy=dest[0]-start[0],dest[1]-start[1]
                packets.extend(self._move_target(target,aimed(origin,(origin[0]+dx,origin[1]+dy),120,fixed=True),360,now))
        return packets

    def _event(self,now,kind,data):
        if kind=='mulan_release':return self._release(data[0],now)
        if kind=='mulan_swing':
            cast,index=data
            if self.dash is not cast or not self.alive:return []
            packets=self._buff(374222 if index==1 else 374232,now)
            for target in enemies(self,area=True):
                if math.dist(self.position_at(now),target.position_at(now))<=144:
                    packets.extend(self._swing(target,cast,index,now))
                    if self.arena.pk and self.arena.pk['finished']:
                        return packets+self._end_dash(now)
                    packets.extend(self._move_target(target,self.motion[1] if self.motion else self.position_at(now),240,now))
            return packets
        if kind=='mulan_dash':
            cast,=data
            if self.dash is not cast or not self.alive:return []
            start,end=self.position_at(cast['previous']),self.position_at(now);packets=[]
            for target in enemies(self):
                key=target.id,target.generation
                if key in cast['hits'] or actor_contact(start,end,target,cast['previous'],now) is None:continue
                cast['hits'].add(key)
                if cast['slot']==1:
                    packets.extend(self._swing(target,cast,0,now))
                    if self.arena.pk and self.arena.pk['finished']:
                        return packets+self._end_dash(now)
                    packets.extend(self._move_target(target,self.motion[1] if self.motion else end,240,now))
                else:
                    packets.extend(self._hit(target,cast['power']*D('1.62'),cast['generation'],now))
                    if self.arena.pk and self.arena.pk['finished']:
                        return packets+self._end_dash(now)
                    origin=target.position_at(now);dx,dy=cast['direction']
                    dest=aimed(origin,(origin[0]+dx,origin[1]+dy),360 if target.id==cast['target'] else 180,fixed=True)
                    packets.extend(self._move_target(target,dest,600,now))
                    packets.extend(self._buff(374434,now,target.id)+self._buff(374435,now,target.id))
            # The three swings keep their schedule even when travel is clipped.
            done=now>=cast['end'] if cast['slot']==1 else not self.motion or now>=self.motion[3] or now>=cast['end']
            if done and cast['slot']==10 and not cast['second']:
                # Same hit set across the extra 168-unit thrust.
                cast['second']=True;dx,dy=cast['direction']
                duration=self._set_motion(end,aimed(end,(end[0]+dx,end[1]+dy),168,fixed=True),720,now,kind=3)
                cast['end']=now+duration;self.forced_until=cast['end'];done=False
                packets.append(scene(moves=(self._move_event(self.motion[1],720,3),)))
            if done:
                packets.extend(self._end_dash(now))
            else:
                cast['previous']=now;self._queue(min(now+20,cast['end']),kind,cast)
            return packets
        if kind=='mulan_sword_land':
            field,=data
            if self.fields.get(field['id']) is not field:return []
            self.fields.pop(field['id']);packets=self.remove_object(field['id'],destroyed=True)
            ident,packet=self.add_object(374402,field['pos']);field.update(id=ident,end=now+4000,next_stack_at=now+1000)
            self.fields[ident]=field;packets.append(packet)
            hit=False
            for target in enemies(self,area=True):
                if math.dist(field['pos'],target.position_at(now))<=144:
                    hit=True;packets.extend(self._hit(target,field['power']*D('1.34'),field['generation'],now))
                    packets.extend(self._buff(374404,now,target.id,duration=2000)+self._buff(374405,now,target.id))
            if hit and self.alive and self.generation==field['generation']:
                self.r_window=dict(end=now+2000)
                packets.extend(self._buff(374406,now));packets.append(self._cooldown(10,True))
            self._queue(now+250,'mulan_field',field)
            return packets
        if kind=='mulan_field':
            field,=data
            if self.fields.get(field['id']) is not field:return []
            damage_tick=now>=field['next_stack_at'];packets=[]
            if damage_tick:field['next_stack_at']+=1000
            for target in enemies(self,area=True):
                if math.dist(field['pos'],target.position_at(now))<=144:
                    if damage_tick:
                        packets.extend(self._hit(target,field['power']*D('.67'),field['generation'],now,periodic=True))
                    if now<field['end']:
                        # Refresh continuity at 250 ms; only damage ticks add a slow tier.
                        count=target.buff_stacks.get(374422,0) if target.has_buff(374422,now) and target.buff_sources.get(374422)==self.id else 0
                        packets.extend(self._buff(374422,now,target.id,stacks=min(5,max(1,count+int(damage_tick))),duration=min(550,field['end']-now)))
            if now>=field['end']:
                self.fields.pop(field['id']);packets.extend(self.remove_object(field['id'],destroyed=True))
            else:self._queue(min(now+250,field['end']),kind,field)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if self.ready and slot==2 and self.alive:return self._release(self.ready,now)
        second=slot==10 and self.r_window['end']>now
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or not second and self.cooldowns[slot]>now:return []
        if slot in (0,1,2) and start==dest:return []
        if slot==10 and not second and (not self._inside(dest) or math.dist(start,dest)>480):return []
        target=None
        if second:
            # AI05: user-approved team visibility filter for both human and bot.
            from bot_ai import observable
            scouts=[a for a in self.arena.actors.values() if a.alive and a.camp==self.camp and not a.info.get('npc_template')]
            targets=[t for t in enemies(self) if math.dist(start,t.position_at(now))<=600
                     and t.has_buff(374405,now) and t.buff_sources.get(374405)==self.id
                     and any(observable(self.arena,a,t,now) for a in scouts)]
            if not targets:return []
            target=min(targets,key=lambda t:(t.hp,t.id));dest=target.position_at(now)
        power=self.combat_stat('iAttack',now);packets=[]
        if not second:self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:20000,10:6000}[slot], slot)
        if slot==0:
            return self.shoot(374100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        if slot==2:
            body,handoff=prepare_displacement(self,now,interrupt=False)
            if not handoff: body=start
            self.position,self.motion=body,None
            self.ready=dict(slot=2,skill=374301,begin=now,dest=dest,power=power,generation=self.generation)
            for template in CHARGE_BUFFS:packets.extend(self._buff(template,now))
            self._queue(now+3000,'mulan_release',self.ready)
            return packets+[self._cooldown(2,True),scene(skills=(self._skill_event(374301,start,dest,ready=1),))]+self.sync_speed(now)+handoff
        if slot==10 and not second:
            ident,packet=self.add_object(374401,dest)
            field=dict(id=ident,pos=dest,power=power,generation=self.generation)
            self.fields[ident]=field;self._queue(now+500,'mulan_sword_land',field)
            return [packet,self._cooldown(10)]
        direction=(dest[0]-start[0],dest[1]-start[1]);speed=240 if slot==1 else 720
        end=aimed(start,dest,360,fixed=True) if slot==1 else dest
        duration=self._set_motion(start,end,speed,now,kind=3);self.forced_until=now+duration
        self.dash=dict(slot=slot,end=now+duration,previous=now,hits=set(),swing_hits=[set(),set(),set()],power=power,
                       generation=self.generation,direction=direction,target=target.id if target else 0,second=False)
        if slot==1:
            self.dash['end']=now+1500
            packets.extend(self._buff(374203,now))
            for template in E_BUFFS:packets.extend(self._buff(template,now,duration=1500))
            for index in (1,2):self._queue(now+650*index,'mulan_swing',self.dash,index)
        else:
            self.r_window=dict(end=0);packets.extend(self.remove_buff(374406,now));packets.append(self._cooldown(10,True))
            for template in (374412,374413,374414,374431):packets.extend(self._buff(template,now,duration=2000))
        self._queue(now+min(20,duration),'mulan_dash',self.dash)
        return packets+[scene(moves=(self._move_event(self.motion[1],speed,3),)),self._cooldown(slot)]
