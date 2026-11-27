"""Hades: independent E banks, native melee slots and a fixed fear domain."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,in_cone,prepare_displacement

SLOTS={0:367100,1:367201,2:367301,10:367401}


class HadesActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.melee=False
        self.e_banks={False:dict(end=0),True:dict(end=0)}
        self.ready=self.vanish=None
        self.domains={}

    def _skill(self,slot,now):
        if not self.melee:return SLOTS[slot]
        if slot==0:
            enhanced=self.has_buff(367602,now)
            alternate=self.has_buff(367124 if enhanced else 367113,now)
            return (367140 if alternate else 367120) if enhanced else (367130 if alternate else 367110)
        return {1:367601,2:367301,10:367501}[slot]

    def _cooldown(self,slot,changed=False):
        body=props(self._skill(slot,self.clock()),slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def attr_bonus(self,attributes,now):
        value=super().attr_bonus(attributes,now)
        # E's description limits its attack-speed bonus to Reaper basics.
        if not self.melee and 10 in attributes and self.has_buff(367603,now):
            value-=D('1.5')
        return value

    def on_spawn(self,now):
        self.melee=False;self.ready=self.vanish=None
        self.info.pop('untargetable',None);self.info.pop('damage_immune',None)
        self.cooldowns[1]=self.e_banks[False]['end']
        return [self._cooldown(s,True) for s in SLOTS]

    def blocked(self,action,now):
        return bool(self.ready or self.vanish) or super().blocked(action,now)

    def cc_immune(self,now,*,slow=False):
        return bool(self.vanish) or super().cc_immune(now,slow=slow)

    def reject_buff(self,row,source,now):
        return bool(self.vanish and source.camp!=self.camp)

    def _speed(self,now):
        return 0 if self.ready or self.vanish else super()._speed(now)

    def remove_buff(self,template,now,*,expired=False):
        packets=super().remove_buff(template,now,expired=expired)
        if template in (367113,367124,367602) and self.alive:
            packets.append(self._cooldown(0,True))
        return packets

    def _switch(self,now):
        self.e_banks[self.melee]['end']=self.cooldowns[1]
        self.melee=not self.melee
        self.cooldowns[1]=self.e_banks[self.melee]['end']
        packets=[]
        for t in (367401,367402,367403,367404,367504,367113,367124):
            packets.extend(self.remove_buff(t,now))
        for t in ((367401,367402,367403,367404) if self.melee else (367501,367504)):
            packets.extend(self._buff(t,now))
        for t in (367405,367406,367407):packets.extend(self._buff(t,now))
        return packets+[self._cooldown(s,True) for s in (0,1,10)]

    def on_bullet_hit(self,flight,target,now):
        if flight['template']!=367100:return []
        packets=self._buff(367102,now,target.id)
        if self.alive and self.generation==flight['source_generation']:
            self.cooldowns[10]=now+round(max(0,self.cooldowns[10]-now)*.85)
            packets.append(self._cooldown(10))
        return packets

    def _return(self,now):
        self.ready=self.vanish=None
        self.info.pop('untargetable',None);self.info.pop('damage_immune',None)
        return self.remove_buff(367303,now)+self.sync_speed(now)

    def interrupt(self,now):
        return self._return(now) if not self.alive else []

    def _domain(self,cast,now):
        packets=[]
        remaining=cast['end']-now
        if remaining<=0:
            self.domains.pop(cast['id'],None)
            return self.remove_object(cast['id'])
        duration=min(300,remaining)
        for target in enemies(self,area=True):
            pos=target.position_at(now);distance=math.dist(pos,cast['pos'])
            locked=target.id==cast['target'] and target.generation==cast['target_generation']
            if locked:
                if distance>264:cast['escaped']=True
                if cast.get('escaped'):packets.extend(self._buff(367321,now,target.id,duration=duration))
            elif distance<=264 and not target.cc_immune(now):
                for t in (367308,367309,367313):packets.extend(self._buff(t,now,target.id,duration=duration))
                pos,stopped=prepare_displacement(target,now)
                packets.extend(stopped)
                distance=math.dist(pos,cast['pos'])
                speed=round(int(target.stats['iSpeed'])*1.5)
                direction=pos if distance else (pos[0]+1,pos[1])
                end=aimed(cast['pos'],direction,distance+speed*min(250,remaining)/1000,fixed=True)
                elapsed=target._set_motion(pos,end,speed,now,kind=1)
                target.forced_until=now+elapsed
                packets.append(scene(moves=(self._move_event(target.motion[1],speed,1,target.id),)))
        if self.alive and self.generation==cast['generation'] and math.dist(self.position_at(now),cast['pos'])<=264:
            packets.extend(self._buff(367310,now,duration=duration))
        self._queue(min(now+250,cast['end']),'hades_domain',cast)
        return packets

    def _event(self,now,kind,data):
        if kind=='hades_vanish':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;self.vanish=cast
            self.info['untargetable']=self.info['damage_immune']=True
            ident,packet=self.add_object(367302,cast['start'])
            self._queue(now+1000,'object_expire',ident)
            self._queue(now+1000,'hades_arrive',cast)
            return [packet]+self._buff(367303,now)+self.sync_speed(now)
        if kind=='hades_arrive':
            cast,=data
            if self.vanish is not cast or not self.alive:return []
            packets=self._return(now)
            target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation']:return packets
            pos=self.blink_destination(cast['start'],target.position_at(now))
            self.position,self.motion,self.forced_until=pos,None,now
            packets.append(scene(moves=(self._move_event(pos,0,5),)))
            packets.extend(self._buff(367311,now,target.id))
            for enemy in enemies(self,area=True):
                if math.dist(pos,enemy.position_at(now))<=264:
                    packets.extend(self.damage(cast['power']*D('2.23'),now,target=enemy,school='energy')[0])
                    if self.arena.pk and self.arena.pk['finished']:
                        return packets
            ident,packet=self.add_object(367312,pos);packets.append(packet)
            cast.update(id=ident,pos=pos,end=now+4000)
            self.domains[ident]=cast
            return packets+self._domain(cast,now)
        if kind=='hades_domain':return self._domain(data[0],now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot in (0,1) and start==dest:return []
        target=self.arena.actors.get(target_id)
        if slot==2 and (not target or target not in enemies(self) or math.dist(start,target.position_at(now))>480):return []
        if slot==2:
            from bot_ai import team_visible
            if not team_visible(self.arena,self,target,now):return []
        skill=self._skill(slot,now);power=self.combat_stat('iEgAtk',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:25000,10:6000}[slot], slot)
        if slot==0 and not self.melee:
            return self.shoot(skill,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        packets=[scene(skills=(self._skill_event(skill,start,dest),))]
        if slot==10:return packets+self._switch(now)+[self._cooldown(10)]
        if slot==2:
            self.position,self.motion=start,None
            self.ready=dict(slot=2,skill=skill,start=start,power=power,generation=self.generation,
                            target=target.id,target_generation=target.generation,end=now+10)
            for t in (367301,367306,367307):packets.extend(self._buff(t,now,target.id))
            self._queue(now+10,'hades_vanish',self.ready)
            return packets+self.sync_speed(now)+[self._cooldown(2)]
        enhanced=self.melee and self.has_buff(367602,now)
        lost_any=False
        for enemy in enemies(self,area=True):
            pos=enemy.position_at(now)
            if slot==0:
                if not in_cone(pos,start,dest,168,180):continue
                marked=any(enemy.has_buff(t,now) and enemy.buff_sources.get(t)==self.id for t in range(367203,367207))
                hit,_=self.damage(power*(D('1.5') if marked else 1),now,target=enemy,school='energy',basic=True,
                                  lifesteal=D('1.8') if enhanced else D('.3'))
                packets.extend(hit+self._buff(367120,now,enemy.id))
            else:
                if self.melee:
                    if math.dist(pos,start)>192:continue
                elif not in_cone(pos,start,dest,480,45):continue
                hit,lost=self.damage(power*(D('1.67') if self.melee else D('1.32')),now,target=enemy,school='energy')
                packets.extend(hit);lost_any=lost_any or lost
                if not self.melee:
                    packets.extend(self._buff(367202,now,enemy.id,duration=2000))
                    for t in range(367203,367207):packets.extend(self._buff(t,now,enemy.id))
        if slot==0:
            template=367124 if enhanced else 367113
            packets.extend(self.remove_buff(template,now) if self.has_buff(template,now) else self._buff(template,now))
            packets.append(self._cooldown(0,True))
        else:
            self.e_banks[self.melee]['end']=self.cooldowns[1]
            if self.melee and lost_any:
                packets.extend(self._buff(367602,now)+self._buff(367603,now))
                packets.append(self._cooldown(0,True))
        return packets+[self._cooldown(slot)]
