"""Sniper: stationary aiming, persistent mines and three finite special shots."""
from battle_participants import friendly
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at, rect_contact
from combat_math import D
from combat_protocol import props,scene,stop_move
from melee_common import aimed,enemies,in_strip,piercing_step,accept_water_reclip

SLOTS={0:376100,1:376201,2:376301,10:376401}
SHOTS=(376310,376320,376330)


class SniperActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.special=None
        self.traps={}
        self.aim_state=dict(begin=self.clock(),next_stack_at=self.clock()+2000,pos=self.position,count=0)
        self.combat_timer=dict(end=0)

    def _cooldown(self,slot,changed=False):
        skill=SLOTS[slot]
        if slot==0:
            skill=SHOTS[self.special['index']] if self.special else 376151 if self.has_buff(376142,self.clock()) else 376100
        body=props(skill,slot,end=0 if slot==2 and self.special else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=self.special=None
        self.aim_state=dict(begin=now,next_stack_at=now+2000,pos=self.position,count=0)
        self.combat_timer=dict(end=0)
        packets=[]
        for template in range(376101,376108):
            packets.extend(self._buff(template,now))
        return packets+self._conceal(now)+[self._cooldown(0,True)]

    def _visibility(self,now):
        self.info['untargetable']=self.has_buff(376111,now) and 32 not in self.buff_types(now)

    def _conceal(self,now):
        packets=[]
        if not self.has_buff(376111,now):
            packets=self._buff(376111,now)+self._buff(376112,now)
        self._visibility(now)
        return packets

    def _activity(self,now):
        self.combat_timer['end']=now+2000
        packets=self.remove_buff(376111,now)+self.remove_buff(376112,now)+self._buff(376121,now)
        self._visibility(now)
        return packets

    def on_combat(self,now):
        pass  # Cast/received damage own this timer; old traps must not reveal a new life.

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        return self._activity(now) if self.alive and hit.hp_loss>0 else []

    def _reset_aim(self,now):
        changed=self.has_buff(376142,now)
        self.aim_state=dict(begin=now,next_stack_at=now+2000,pos=self.position_at(now),count=0)
        packets=self.remove_buff(376142,now)+self.remove_buff(376141,now)
        return packets+([self._cooldown(0,True)] if changed else [])

    def update(self,now):
        packets=[]
        if not self.alive:
            return super().update(now)
        state=self.aim_state;pos=self.position_at(now)
        if pos!=state['pos'] or self.motion and now<self.motion[3]:
            packets.extend(self._reset_aim(now));state=self.aim_state
        else:
            if now>=state['begin']+1500 and not self.special and not self.has_buff(376142,now):
                packets.extend(self._buff(376142,now));packets.append(self._cooldown(0,True))
            if now>=state['next_stack_at']:
                count=1+(now-state['next_stack_at'])//500
                state['next_stack_at']+=500*count
                state['count']=min(10,state['count']+count)
                packets.extend(self._buff(376141,now,stacks=state['count']))
        if self.special or now<self.combat_timer['end']:
            if self.has_buff(376111,now):
                packets.extend(self.remove_buff(376111,now)+self.remove_buff(376112,now))
        else:
            packets.extend(self._conceal(now))
        self._visibility(now)
        if self.ready:
            slot=self.ready['slot'];mask={0:1,10:8}[slot]
            for (owner,template),(_,end) in self.active_buffs.items():
                if owner!=self.id or end<=now or template in (376305,376313):continue
                row=table_row('BuffTemplate_table.xml',nBuffId=template)
                effect=int(row['nEffectType']);bits=int(row.get('fEffectValB',0))
                if (effect==66 or effect==35 and slot!=0) and (bits==0 or bits & mask):
                    packets.extend(self.interrupt(now));break
        return packets+super().update(now)

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def _end_special(self,now):
        if not self.special:
            return []
        self.special=None;self.cooldowns[2]=now+self.skill_cooldown(15000, 2)
        packets=[]
        for template in (376301,376302,376303,376304,376305,376306):
            packets.extend(self.remove_buff(template,now))
        return packets+[self._cooldown(0,True),self._cooldown(2)]

    def interrupt(self,now):
        packets=[]
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            self.ready=None
        if not self.alive:
            packets.extend(self._end_special(now));self.info['untargetable']=False
        return packets+self.sync_speed(now)

    def _mark_hit(self,target,raw,power,now):
        marked=target.has_buff(376410,now) and target.buff_sources.get(376410)==self.id
        packets,lost=self.damage(raw,now,target=target)
        if marked:
            packets.extend(target.remove_buff(376410,now))
            extra,hit=self.damage(power,now,target=target,school='true');packets.extend(extra);lost=lost or hit
            packets.extend(self._buff(376412,now,target.id))
        packets.extend(self._buff(376410,now,target.id))
        return packets,lost

    def _push(self,target,flight,now):
        if not target.alive or target.cc_immune(now):
            return []
        current=target.position_at(now);start=target.stop_position(now)
        dx,dy=flight['end'][0]-flight['start'][0],flight['end'][1]-flight['start'][1]
        dest=aimed(start,(start[0]+dx,start[1]+dy),240,fixed=True)
        wall=self.arena.geometry.wall_contact(start,dest,36)
        if wall is not None:dest=point_at(start,dest,max(0,wall-.0001))
        requested=dest
        if start!=current:target.position,target.motion=start,None
        packets=target.interrupt(now)
        if start!=current:packets.append(stop_move(target.scene_id,target.id,start))
        duration=target._set_motion(start,dest,720,now,kind=1);target.forced_until=now+duration
        cast=dict(target=target.id,target_generation=target.generation,end=now+duration,motion=target.motion,
                  wall=wall is not None or math.dist(requested,target.motion[1])>.1)
        self._queue(now+min(20,duration),'sniper_wall',cast)
        return packets+self._buff(376202,now,target.id)+[scene(moves=(self._move_event(target.motion[1],720,1,target.id),))]

    def _bullet_hit(self,flight,target,now):
        template=flight['template'];current=self.alive and self.generation==flight['source_generation']
        if flight['basic']:
            packets,lost=self.damage(flight['raw'],now,target=target,basic=True)
            if template==376151:
                packets.extend(self._buff(376321,now,target.id))
                if lost and current:
                    self.cooldowns[2]=now+round(max(0,self.cooldowns[2]-now)*.85)
                    packets.append(self._cooldown(2))
            return packets
        if template==376201:
            packets=self._push(target,flight,now)
            more,lost=self._mark_hit(target,flight['raw'],flight['power'],now);packets.extend(more)
            if lost and current and not flight['context']['aimed']:
                packets.extend(self._buff(376203,now))
            return packets
        targets=[target] if template==376310 else [t for t in enemies(self,area=True) if math.dist(t.position_at(now),target.position_at(now))<=120]
        packets=[]
        for victim in targets:
            packets.extend(self._mark_hit(victim,flight['raw'],flight['power'],now)[0])
            for buff in ((376311,376312,376421) if template==376310 else (376321,376421)):
                packets.extend(self._buff(buff,now,victim.id))
        return packets

    def _flight(self,flight,now):
        return piercing_step(self,flight,now,self._bullet_hit,pierce=False)

    def clear_hidden_traps(self,center,radius):
        packets=[]
        for ident,trap in list(self.traps.items()):
            if not trap.get('triggered') and math.dist(center,trap['pos'])<=radius:
                self.traps.pop(ident);packets.extend(self.remove_object(ident))
        return packets

    def _event(self,now,kind,data):
        if kind=='sniper_wall':
            cast,=data;target=self.arena.actors[cast['target']]
            if not target.alive or target.generation!=cast['target_generation']:return []
            if target.motion!=cast['motion']:
                # Only a water-wall reclip of this push may count as a wall hit.
                # A shorter push from another skill must not grant Sniper's stun.
                if (target.motion and target.motion_kind==1 and target.motion[3]<=cast['end']
                        and target.has_buff(376202,now) and accept_water_reclip(target,cast)):
                    cast.update(motion=target.motion,end=target.motion[3],wall=True)
                else:return target.remove_buff(376202,now)
            if now<cast['end']:
                self._queue(min(now+20,cast['end']),kind,cast);return []
            return target.remove_buff(376202,now)+(self._buff(376210,now,target.id) if cast['wall'] else [])
        if kind=='sniper_special_end':
            return self._end_special(now) if self.special is data[0] else []
        if kind=='sniper_ready':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;packets=self.sync_speed(now)
            if cast['slot']==10:
                ident,packet=self.add_object(376401,cast['start'])
                trap=dict(id=ident,pos=cast['start'],power=cast['power'],generation=self.generation,previous=now,end=now+15000)
                self.traps[ident]=trap;self._queue(now+20,'sniper_trap',trap)
                return packets+friendly(self,packet)
            skill=cast['skill'];start=self.position_at(now);dest=cast['dest']
            if skill==376330:
                end=aimed(start,dest,960,fixed=True)
                wall=rect_contact(start,end,self.arena.water_rects(now))
                if wall is not None:end=point_at(start,end,max(0,wall-.0001))
                packets.append(scene(skills=(self._skill_event(skill,start,end),)))
                for target in enemies(self,area=True):
                    if in_strip(target.position_at(now),start,end,math.dist(start,end),48):
                        packets.extend(self._mark_hit(target,cast['power']*D('3.5'),cast['power'],now)[0])
                        packets.extend(self._buff(376312,now,target.id)+self._buff(376421,now,target.id))
            else:
                packets.extend(self.shoot(skill,start,dest,now,cast['power']*(D('2.5') if skill==376310 else 3),school='physical',power=cast['power'],through_walls=True))
            return packets
        if kind=='sniper_trap':
            trap,=data
            if self.traps.get(trap['id']) is not trap:return []
            if now>=trap['end']:
                self.traps.pop(trap['id']);return self.remove_object(trap['id'])
            hit=any(actor_contact(trap['pos'],trap['pos'],t,trap['previous'],now,96) is not None for t in enemies(self))
            if hit:
                self.traps.pop(trap['id']);packets=self.remove_object(trap['id'])
                ident,packet=self.add_object(376402,trap['pos']);trap.update(id=ident,end=now+1000,triggered=True)
                self.traps[ident]=trap;self._queue(now+1000,'sniper_blast',trap)
                for target in enemies(self,area=True):
                    if math.dist(target.position_at(now),trap['pos'])<=120:packets.extend(self._buff(376404,now,target.id))
                return packets+[packet]
            trap['previous']=now;self._queue(min(now+20,trap['end']),kind,trap);return []
        if kind=='sniper_blast':
            trap,=data
            if self.traps.pop(trap['id'],None) is not trap:return []
            packets=self.remove_object(trap['id'],destroyed=True)
            for target in enemies(self,area=True):
                if math.dist(trap['pos'],target.position_at(now))<=120:
                    packets.extend(self._mark_hit(target,trap['power']*D('2.05'),trap['power'],now)[0])
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot in (0,1) and start==dest:return []
        packets=self._activity(now);power=self.combat_stat('iAttack',now)
        if slot==0 and self.special:
            index=self.special['index'];skill=SHOTS[index]
            self.cooldowns[0]=now+1250
            self.ready=dict(slot=0,skill=skill,start=start,dest=dest,power=power)
            self._queue(now+(100 if index==2 else 50),'sniper_ready',self.ready)
            packets.append(scene(skills=(self._skill_event(skill,start,dest,ready=1),)))
            packets.extend(self._buff(376313,now))
            packets.extend(self.remove_buff(376301+index,now))
            if index==2:
                packets.extend(self._end_special(now))
            else:
                self.special['index']+=1
                packets.extend(self._buff(376302+index,now))
                if index==1:self._queue(now+3000,'sniper_special_end',self.special)
                packets.append(self._cooldown(0,True))
        elif slot==0:
            is_aimed=self.has_buff(376142,now)
            self.cooldowns[0]=now+self.fire_interval(now)
            packets.extend(self.shoot(376151 if is_aimed else 376100,start,dest,now,power*(2 if is_aimed else 1),school='physical',basic=True))
            if is_aimed:
                packets.extend(self.remove_buff(376142,now)+self._buff(376143,now))
                self.aim_state['begin']=now
                packets.append(self._cooldown(0,True))
        elif slot==1:
            self.cooldowns[1]=now+self.skill_cooldown(6000, 1)
            packets.extend(self.shoot(376201,start,dest,now,power*D('1.75'),school='physical',power=power,through_walls=True,
                                      context=dict(aimed=self.has_buff(376142,now) or bool(self.special))))
        elif slot==2:
            if self.special:return []
            self.special=dict(index=0)
            packets.extend(self.remove_buff(376142,now))
            for template in (376301,376304,376305,376306):packets.extend(self._buff(template,now))
            packets.append(self._cooldown(0,True))
        else:
            self.cooldowns[10]=now+self.skill_cooldown(8000, 10)
            self.position,self.motion=start,None
            self.ready=dict(slot=10,skill=376401,start=start,dest=start,power=power)
            self._queue(now+100,'sniper_ready',self.ready)
            packets.append(scene(skills=(self._skill_event(376401,start,start,ready=1),)))
        return packets+[self._cooldown(slot)]+self.sync_speed(now)
