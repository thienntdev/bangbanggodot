"""Diao Chan: nonrecursive marks, charm and returning native fan projectiles."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene
from melee_common import prepare_displacement

SLOTS = {0:348100,1:348201,2:348301,10:348401}
MARKS = tuple(range(348111,348115))


class DiaoChanActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready = self.dash = None
        self.space_count,self.space_next_charge = 3,0

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,self.space_count if slot==2 else -1,
                          self.cooldowns[slot],self.space_next_charge if slot==2 else 0)+struct.pack('<I',self.id)

    def on_spawn(self,now):
        return self._buff(348101,now)+self._buff(348102,now)

    def _speed(self,now):
        return 0 if self.ready or self.dash else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.dash) or super().blocked(action,now)

    def interrupt(self,now):
        packets = []
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,SLOTS[self.ready['slot']])))
        self.ready = self.dash = None
        if self.motion:
            self.position,self.motion,self.forced_until = self.position_at(now),None,now
            packets.append(scene(moves=(self._move_event(self.position,0,5),)))
        return packets+self.sync_speed(now)

    def update(self,now):
        packets = self.interrupt(now) if self.ready and self.skill_sealed(self.ready['slot'],now) else []
        while self.space_next_charge and self.space_next_charge<=now:
            self.space_count = min(3,self.space_count+1)
            self.space_next_charge = self.space_next_charge+self.skill_cooldown(8000) if self.space_count<3 else 0
            packets.append(self._cooldown(2))
        return packets+super().update(now)

    def _mark(self,target,power,generation,now):
        if not target.alive or target.reject_buff({'nEffectType':'49'},self,now):
            return []
        count = max((i+1 for i,t in enumerate(MARKS) if target.has_buff(t,now)),default=0)
        packets = []
        for t in MARKS:
            if target.has_buff(t,now):
                packets.extend(target.remove_buff(t,now))
        if count<4:
            return packets+self._buff(MARKS[count],now,target.id)
        pos = target.position_at(now)
        packets.extend(self._buff(348122,now,target.id))
        for victim in list(self.arena.actors.values()):
            if victim.alive and victim.camp!=self.camp and math.dist(pos,victim.position_at(now))<=192:
                packets.extend(self.damage(power,now,target=victim,school='true',
                    lifesteal='.25' if self.alive and generation==self.generation else 0)[0])
                packets.extend(self._buff(348123,now,victim.id))
        return packets

    def _impact(self,flight,target,now):
        packets = self.damage(flight['raw'],now,target=target,school='energy',
                    lifesteal='.25' if self.alive and flight['source_generation']==self.generation else 0)[0]
        packets.extend(self._mark(target,flight['power'],flight['source_generation'],now))
        if flight['template'] in (348211,348301,348311):
            packets.extend(self._buff(348313,now,target.id))
        if flight['template'] in (348301,348311) and self.alive and flight['source_generation']==self.generation:
            for slot in (1,10):
                self.cooldowns[slot] = now+round(max(0,self.cooldowns[slot]-now)*.7)
                packets.append(self._cooldown(slot))
        if flight['template']==348401 and target.alive:
            if self.arena.pk and self.arena.pk['finished']:
                return packets
            for t in (348402,348403,348404):
                packets.extend(self._buff(t,now,target.id))
            if target.has_buff(348402,now) and target.buff_sources.get(348402)==self.id:
                charm = dict(target=target.id,target_generation=target.generation,
                             version=target.buff_versions[348402],end=now+1000)
                _,stopped = prepare_displacement(target,now)
                packets.extend(stopped)
                packets.extend(self._charm(charm,now))
        return packets

    def _charm(self,cast,now):
        target = self.arena.actors.get(cast['target'])
        if not target or not target.alive or target.generation!=cast['target_generation'] or not target.has_buff(348402,now) or target.buff_versions.get(348402)!=cast['version']:
            return []
        start,center = target.position_at(now),self.position_at(now)
        distance = math.dist(start,center)
        speed = max(1,round(int(target.stats['iSpeed'])*.5))
        step = min(100,cast['end']-now)
        packets = []
        if distance>72:
            # A later external push can still be crossing a wall when this
            # periodic charm reclaims movement. Preserve that motion's origin
            # until its safe body pose is resolved; do not interrupt each tick.
            origin,stopped = prepare_displacement(target,now,interrupt=False)
            packets.extend(stopped)
            remaining = math.dist(origin,center)
            dest = point_at(origin,center,min(speed*step/1000,max(0,remaining-72))/max(1,remaining))
            duration = target._set_motion(origin,dest,speed,now,kind=1)
            target.forced_until = now+duration
            packets.append(scene(moves=(target._move_event(target.motion[1],speed,1),)))
        if now+step<cast['end']:
            self._queue(now+step,'diao_charm',cast)
        return packets

    def _flight(self,flight,now):
        if flight['template']==348100:
            return super()._flight(flight,now)
        returning = flight['template']==348311
        fan = flight['template'] in (348301,348311)
        if fan and (not self.alive or self.generation!=flight['source_generation']):
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        previous = flight['previous']
        homing = self if returning else self.arena.actors.get(flight.get('target'))
        packets = []
        if homing:
            if not homing.alive or homing.generation!=flight['target_generation'] or not returning and homing.is_untargetable():
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start,dest = flight['pos'],homing.position_at(now)
            end = point_at(start,dest,min(1,flight['speed']*(now-previous)/1000/max(1,math.dist(start,dest))))
            if dest!=flight['end']:
                packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(x) for x in (*start,*dest)))))
                flight['end'] = dest
            reached = math.dist(end,dest)<1
        else:
            start = point_at(flight['start'],flight['end'],(previous-flight['begin'])/(flight['finish']-flight['begin']))
            end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
            reached = now>=flight['finish']
        candidates = [homing] if homing and not returning else list(self.arena.actors.values())
        contacts = []
        for target in candidates:
            if target.alive and target.camp!=self.camp and not target.is_untargetable() and (target.id,target.generation) not in flight['hits']:
                hit = actor_contact(start,end,target,previous,now,84 if fan else 72 if flight['template']==348401 else 36)
                if hit is not None:
                    contacts.append((hit,target.id))
        for _,ident in sorted(contacts):
            target = self.arena.actors[ident]
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['hits'].add((target.id,target.generation))
            packets.extend(self._impact(flight,target,now))
            if not fan:
                return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        flight['pos'] = end
        if reached or now>=flight['begin']+5000:
            packets.append(scene(expired_bullets=(struct.pack('<I',flight['id']),)))
            if fan and not returning:
                pos = tuple(round(v) for v in end)
                dest = self.position_at(now)
                speed = max(1,round(240*float(1+self.attr_bonus((37,),now))))
                duration = max(1,math.ceil(math.dist(pos,dest)*1000/speed))
                ret = dict(flight,id=self._new_id(2),template=348311,start=pos,end=dest,pos=pos,begin=now,previous=now,
                           finish=now+duration,speed=speed,target=self.id,target_generation=self.generation,
                           raw=flight['power']*D('1.8'),hits=set())
                packets.append(scene(fires=(struct.pack('<IIhhhhhI',ret['id'],self.id,*pos,*dest,speed,348311),)))
                self._queue(now+min(20,duration),'flight',ret)
            return packets
        flight['previous'] = now
        if homing:
            # A moving target can outlive the launch ETA. Never requeue at an
            # already processed timestamp; retain the existing five-second limit.
            flight['finish'] = min(flight['begin']+5000,now+max(1,math.ceil(math.dist(end,homing.position_at(now))*1000/flight['speed'])))
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _event(self,now,kind,data):
        if kind=='diao_flowers':
            from bot_ai import team_visible
            cast,index = data
            if not self.alive or cast['generation']!=self.generation:
                return []
            start = self.position_at(now)
            candidates = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                          and not a.is_untargetable() and math.dist(start,a.position_at(now))<=(336 if index==0 else 480)
                          and team_visible(self.arena,self,a,now)]
            if index==0 and not candidates:
                return []
            packets = []
            if candidates:
                target = min(candidates,key=lambda a:(bool(a.info.get('npc_template')),math.dist(start,a.position_at(now)),a.id))
                packets.extend(self.shoot(348211,start,target.position_at(now),now,cast['power']*D('.5'),
                    school='energy',target=target,power=cast['power'],through_walls=True))
            if index<3:
                self._queue(now+150,kind,cast,index+1)
            return packets
        if kind=='diao_charm':
            return self._charm(data[0],now)
        if kind=='diao_dash_end':
            cast, = data
            if self.dash is not cast:
                return []
            origin,stopped = prepare_displacement(self,now,interrupt=False)
            self.dash = None
            self.position,self.motion,self.forced_until = origin,None,now
            return stopped+self.sync_speed(now)
        if kind=='diao_cast':
            cast, = data
            if self.ready is not cast or not self.alive or self.skill_sealed(cast['slot'],now):
                return self.interrupt(now) if self.ready is cast else []
            self.ready = None
            start,slot = self.position_at(now),cast['slot']
            packets = [scene(skills=(self._skill_event(SLOTS[slot],start,cast['dest']),))]
            if slot==1:
                duration = self._set_motion(start,cast['dest'],960,now,kind=3)
                self.forced_until = now+duration
                self.dash = cast
                self._queue(now+duration,'diao_dash_end',cast)
                self._queue(now+200,'diao_flowers',cast,0)
                for t in (348202,348203,348204,348205,348211):
                    packets.extend(self._buff(t,now,duration=1000 if t==348202 else None))
                packets.append(scene(moves=(self._move_event(self.motion[1],960,3),)))
            elif slot==10:
                packets.extend(self.shoot(348401,start,cast['dest'],now,cast['power']*D('1.52'),
                                          school='energy',power=cast['power'],through_walls=True))
            else:
                theta = math.atan2(cast['dest'][1]-start[1],cast['dest'][0]-start[0])
                for offset in (-15,0,15):
                    angle = theta+math.radians(offset)
                    dest = start[0]+round(480*math.cos(angle)),start[1]+round(480*math.sin(angle))
                    packets.extend(self.shoot(348301,start,dest,now,cast['power']*D('.6'),
                                              school='energy',power=cast['power'],through_walls=True))
            return packets+self.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or start==dest or slot==2 and not self.space_count:
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:3000,10:8000}[slot], slot)
        if slot==0:
            return self.shoot(348100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        if slot==1:
            dest = self.move_destination(start,point_at(start,dest,360/math.dist(start,dest)))
        self.ready = dict(slot=slot,dest=dest,power=power,generation=self.generation)
        origin,stopped = prepare_displacement(self,now,interrupt=False)
        self.position,self.motion = origin if stopped else start,None
        self._queue(now+100,'diao_cast',self.ready)
        packets = []
        if slot==2:
            self.space_count -= 1
            if not self.space_next_charge:
                self.space_next_charge = now+self.skill_cooldown(8000)
            packets.extend(self._buff(348321,now))
        return packets+[self._cooldown(slot),scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),))]+self.sync_speed(now)+stopped
