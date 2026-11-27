"""Superman has no R slot in the original base template."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:328100,1:328201,2:328301}


class SupermanActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.cooldowns.pop(10)
        self.dash = None
        self.nearby = 0

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.nearby = 0
        self._queue(now,'superman_aura',self.generation)
        return self._buff(328131,now)

    def interrupt(self,now):
        if not self.dash:
            return []
        self.dash = None
        self.position,self.motion,self.forced_until = self.position_at(now),None,now
        return self.remove_buff(328212,now)+self.sync_speed(now)

    def _event(self,now,kind,data):
        if kind=='superman_aura':
            if not self.alive or data[0]!=self.generation:
                return []
            count = min(5,sum(1 for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                            and not a.info.get('npc_template') and math.dist(self.position_at(now),a.position_at(now))<=408))
            packets = []
            if count!=self.nearby:
                for t in (328100+self.nearby,328110+self.nearby,328120+self.nearby) if self.nearby else ():
                    packets.extend(self.remove_buff(t,now))
                self.nearby = count
            if count:
                for t in (328100+count,328110+count,328120+count):
                    packets.extend(self._buff(t,now))
            self._queue(now+1000,kind,*data)
            return packets
        if kind=='superman_dash':
            cast, = data
            if self.dash is not cast or not self.alive:
                return []
            start,end = self.position_at(cast['previous']),self.position_at(now)
            packets = []
            for target in list(self.arena.actors.values()):
                key = target.id,target.generation
                if not target.alive or target.camp==self.camp or key in cast['hits'] or target.is_untargetable():
                    continue
                if actor_contact(start,end,target,cast['previous'],now) is None:
                    continue
                cast['hits'].add(key)
                packets.extend(self.damage(cast['power']*D('1.32'),now,target=target)[0])
                if self.arena.pk and self.arena.pk['finished']:
                    break
                immune = target.cc_immune(now)
                packets.extend(self._buff(328222,now,target.id))
                if target.alive and not immune:
                    origin = target.position_at(now)
                    dest = (origin[0]+cast['direction'][0]*72,origin[1]+cast['direction'][1]*72)
                    duration = target._set_motion(origin,dest,480,now,kind=1)
                    target.forced_until = now+duration
                    packets.append(scene(moves=(target._move_event(target.motion[1],480,1),)))
                if not target.info.get('npc_template'):
                    cast['count'] = min(4,cast['count']+1)
                    for t in range(328231,328236):
                        packets.extend(self.remove_buff(t,now))
                    packets.extend(self._buff(328230+cast['count'],now))
            if not self.motion or now>=self.motion[3]:
                self.dash = None
                packets.extend(self.remove_buff(328212,now))
            else:
                cast['previous'] = now
                self._queue(min(now+20,self.motion[3]),kind,cast)
            return packets
        if kind=='superman_landing':
            cast, = data
            packets = self.remove_object(cast['warning'])
            target = self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation']:
                return packets
            pos = target.position_at(now)
            packets.extend(self._buff(328304,now,target.id))
            packets.extend(self._buff(328307,now,target.id))
            for enemy in list(self.arena.actors.values()):
                if enemy.alive and enemy.camp!=self.camp and math.dist(pos,enemy.position_at(now))<=120:
                    packets.extend(self.damage(cast['power']*D('2.62'),now,target=enemy)[0])
                    packets.extend(self._buff(328306,now,enemy.id))
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or slot in (0,1) and start==dest:
            return []
        if slot==2:
            from bot_ai import team_visible
            candidates = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                          and not a.is_untargetable() and math.dist(start,a.position_at(now))<=240
                          and team_visible(self.arena,self,a,now)]
            if not candidates:
                return []
            target = min(candidates,key=lambda a:(math.dist(start,a.position_at(now)),a.id))
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:20000}[slot], slot)
        if slot==0:
            return self.shoot(328100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        packets = [self._cooldown(slot)]
        if slot==1:
            distance = math.dist(start,dest)
            direction = ((dest[0]-start[0])/distance,(dest[1]-start[1])/distance)
            endpoint = point_at(start,dest,min(1,480/distance))
            origin,stopped = prepare_displacement(self,now,interrupt=False)
            origin = origin if stopped else start
            duration = self._set_motion(origin,endpoint,600,now,kind=3)
            self.forced_until = now+duration
            self.dash = dict(previous=now,generation=self.generation,power=power,hits=set(),count=0,direction=direction)
            self._queue(min(now+20,self.motion[3]),'superman_dash',self.dash)
            return packets+self._buff(328212,now,duration=duration)+stopped+[
                scene(skills=(self._skill_event(328201,start,self.motion[1]),),moves=(self._move_event(self.motion[1],600,3),))]
        distance = math.dist(start,dest)
        desired = point_at(start,dest,min(1,528/max(1,distance)))
        origin = target.position_at(now)
        immune,stopped = target.cc_immune(now),[]
        if not immune:
            origin,stopped = prepare_displacement(target,now)
        landing = target.move_destination(origin,desired) if not immune else origin
        packets.append(scene(skills=(self._skill_event(328301,start,landing,target.id),)))
        if immune:
            duration = 0
        else:
            packets.extend(stopped)
            speed = max(1,math.dist(origin,landing)*1000/900)
            duration = target._set_motion(origin,landing,speed,now,kind=4)
            target.forced_until = now+duration
            packets.append((1578,struct.pack('<IhhhhIB',target.id,*origin,*target.motion[1],duration,0)))
        warning,packet = self.add_object(328311,landing)
        packets.extend([packet]+self.damage(power*D('1.05'),now,target=target)[0])
        cast = dict(target=target.id,target_generation=target.generation,power=power,generation=self.generation,
                    warning=warning,motion=target.motion if duration else None)
        packets.extend(self._buff(328303,now,target.id))
        self._queue(now+1000,'superman_landing',cast)
        return packets
