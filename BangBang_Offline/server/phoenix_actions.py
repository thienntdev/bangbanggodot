"""Phoenix: finite trails, one burn clock and shield-gated rebirth."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene
from melee_common import prepare_displacement

SLOTS = {0:334010,1:334021,2:334031,10:334041}


class PhoenixActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.dash = self.egg = None
        self.e_second_until = 0
        self.burns,self.trail_hits = {},{}

    def _cooldown(self,slot,changed=False):
        second = slot==1 and self.e_second_until>self.clock()
        body = props(334023 if second else SLOTS[slot],slot,end=0 if second else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        return self._buff(334101,now)+[self._cooldown(1,True)]

    def _speed(self,now):
        return 0 if self.egg or self.dash else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.egg or self.dash) or super().blocked(action,now)

    def _burn(self,target,now):
        if not target.alive or target.reject_buff({'nEffectType':'201'},self,now):
            return []
        key = target.id,target.generation
        mark = self.burns.get(key)
        fresh = not mark or mark['end']<now or target.buff_versions.get(334111)!=mark['version']
        packets = self._buff(334111,now,target.id)+self._buff(334112,now,target.id)
        if not target.has_buff(334111,now):
            return packets
        if fresh:
            mark = dict(target=target.id,target_generation=target.generation,end=now+2000,
                        version=target.buff_versions[334111])
            self.burns[key] = mark
            self._queue(now+1000,'phoenix_burn',mark)
        else:
            mark.update(end=now+2000,version=target.buff_versions[334111])
        return packets

    def _hurt(self,target,raw,now,*,periodic=False):
        packets,_ = self.damage(raw,now,target=target,school='energy',periodic=periodic)
        if target.alive:
            packets.extend(self._burn(target,now))
        return packets

    def _end_dash(self,now):
        if not self.dash:
            return []
        self.dash = None
        self.position,self.motion,self.forced_until = self.position_at(now),None,now
        packets = [scene(moves=(self._move_event(self.position,0,5),))]
        for t in (334210,334211,334212,334252,334261):
            packets.extend(self.remove_buff(t,now))
        return packets+self.sync_speed(now)

    def _end_egg(self,now,*,success=False):
        cast,self.egg = self.egg,None
        if not cast:
            return []
        packets = self.remove_object(cast['id'])
        for t in (334301,334303,334304,334305,334307):
            packets.extend(self.remove_buff(t,now))
        packets.append(self.shield_packet(now))
        if success and self.alive:
            packets.extend(self.restore_hp(self.max_hp*5,now))
            packets.extend(self._buff(334333,now))
            self.cooldowns[1] = self.cooldowns[10] = now
            packets.extend((self._cooldown(1),self._cooldown(10)))
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(cast['pos'],target.position_at(now))<=288:
                    packets.extend(self._buff(334332,now,target.id))
        else:
            packets.extend(self._buff(334321,now))
        return packets+self.sync_speed(now)

    def on_shield_break(self,template,now):
        return self._end_egg(now) if template==334304 else []

    def interrupt(self,now):
        packets = self._end_dash(now)
        if not self.alive:
            packets.extend(self._end_egg(now))
            self.e_second_until = 0
        return packets

    def update(self,now):
        packets = []
        if self.e_second_until and now>=self.e_second_until:
            self.e_second_until = 0
            packets.extend(self.remove_buff(334232,now))
            packets.extend((self._cooldown(1,True),self._cooldown(1)))
        self.trail_hits = {k:v for k,v in self.trail_hits.items() if v['end']>now}
        return packets+super().update(now)

    def _event(self,now,kind,data):
        if kind=='phoenix_burn':
            mark, = data
            target = self.arena.actors.get(mark['target'])
            if not target or not target.alive or target.generation!=mark['target_generation'] or target.buff_versions.get(334111)!=mark['version']:
                return []
            packets = self.damage(target.max_hp*D('.03'),now,target=target,school='energy',periodic=True)[0]
            if now+1000<=mark['end']:
                self._queue(now+1000,kind,mark)
            return packets
        if kind=='phoenix_dash':
            cast, = data
            if self.dash is not cast or not self.alive:
                return []
            if not self.motion:
                return self._end_dash(now)
            start,end = self.position_at(cast['previous']),self.position_at(now)
            packets = []
            for target in list(self.arena.actors.values()):
                key = target.id,target.generation
                if target.alive and target.camp!=self.camp and key not in cast['hits'] and not target.is_untargetable():
                    if actor_contact(start,end,target,cast['previous'],now,60) is not None:
                        cast['hits'].add(key)
                        packets.extend(self._hurt(target,cast['power']*D('1.38'),now))
                        if not cast['second'] and not cast['recast_granted']:
                            cast['recast_granted'] = True
                            self.e_second_until = now+3000
                            packets.extend(self._buff(334232,now))
                            packets.extend((self._cooldown(1,True),self._cooldown(1)))
            if now>=cast['end']:
                return packets+self._end_dash(now)
            cast['previous'] = now
            self._queue(min(now+20,cast['end']),kind,cast)
            return packets
        if kind=='phoenix_trail_create':
            cast, = data
            if self.dash is not cast or not self.alive:
                return []
            pos = self.position_at(now)
            ident,packet = self.add_object(334241,pos)
            area = dict(id=ident,pos=pos,power=cast['power'],end=now+3000)
            self._queue(now+1000,'phoenix_trail',area)
            return [packet,scene(skills=(self._skill_event(334022,pos,pos,self.id),))]
        if kind=='phoenix_trail':
            cast, = data
            packets = []
            for target in list(self.arena.actors.values()):
                key = target.id,target.generation
                if target.alive and target.camp!=self.camp and math.dist(cast['pos'],target.position_at(now))<=72:
                    if self.trail_hits.get(key,{}).get('end',0)>now:
                        continue
                    self.trail_hits[key] = dict(end=now+1000)
                    packets.extend(self._buff(334251,now,target.id))
                    packets.extend(self._hurt(target,cast['power']*D('.91'),now,periodic=True))
            if now<cast['end']:
                self._queue(now+1000,kind,cast)
            else:
                packets.extend(self.remove_object(cast['id']))
            return packets
        if kind=='phoenix_egg':
            cast,index = data
            if self.egg is not cast or not self.alive:
                return []
            packets = []
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(cast['pos'],target.position_at(now))<=288:
                    packets.extend(self._hurt(target,cast['power']*D('.88'),now,periodic=True))
                    packets.extend(self._buff(334312,now,target.id)+self._buff(334313,now,target.id))
            if index==5:
                survived = any(s.shield_id=='334304' and s.remaining>0 for s in self.shields)
                return packets+self._end_egg(now,success=survived)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or not self.alive or self.skill_sealed(slot,now) or self.egg:
            return []
        if slot!=2 and self.blocked('attack',now):
            return []
        second = slot==1 and self.e_second_until>now
        if not second and self.cooldowns[slot]>now:
            return []
        if slot in (0,1) and (not self._inside(dest) or dest==start):
            return []
        power = self.combat_stat('iEgAtk',now)
        if not second:
            self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:25000,10:8000}[slot], slot)
        if slot==0:
            return self.shoot(334010,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        packets = []
        if slot==1:
            if second:
                self.e_second_until = 0
                packets.extend(self.remove_buff(334232,now))
                packets.append(self._cooldown(1,True))
            dest = point_at(start,dest,432/math.dist(start,dest))
            origin,stopped = prepare_displacement(self,now,interrupt=False)
            origin = origin if stopped else start
            duration = self._set_motion(origin,dest,600,now,kind=3)
            self.forced_until = now+duration
            self.dash = dict(previous=now,end=now+duration,power=power,hits=set(),second=second,recast_granted=False)
            # Queue trail before the final movement tick at the same timestamp.
            for offset in range(144,duration+1,144):
                self._queue(now+offset,'phoenix_trail_create',self.dash)
            self._queue(now+min(20,duration),'phoenix_dash',self.dash)
            for t in (334210,334261 if second else 334211,334212,334252):
                packets.extend(self._buff(t,now,duration=duration))
            packets.extend(stopped)
            packets.append(scene(skills=(self._skill_event(334023 if second else 334021,start,self.motion[1]),),
                                 moves=(self._move_event(self.motion[1],600,3),)))
        elif slot==10:
            packets.append(scene(skills=(self._skill_event(334041,start,start,self.id),)))
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(start,target.position_at(now))<=192:
                    packets.extend(self._hurt(target,power*D('2.14'),now))
                    packets.extend(self._buff(334411,now,target.id)+self._buff(334412,now,target.id))
        else:
            packets.extend(self._end_dash(now))
            packets.extend(self._buff(334301,now))
            packets.extend(self.commit_hp(max(D(1),self.hp-self.max_hp*D('.5')),now))
            ident,packet = self.add_object(334306,start)
            # Completion precedes shield timeout and never fires shield_break.
            self.egg = dict(id=ident,pos=start,power=power,end=now+2500)
            for index in range(1,6):
                self._queue(now+index*500,'phoenix_egg',self.egg,index)
            for t in (334303,334305,334307):
                packets.extend(self._buff(t,now))
            packets.extend(self.add_shield(334304,self.max_hp*D('.5'),now,duration=2500))
            packets.extend((packet,scene(skills=(self._skill_event(334031,start,start,self.id),))))
        return packets+[self._cooldown(slot)]+self.sync_speed(now)
