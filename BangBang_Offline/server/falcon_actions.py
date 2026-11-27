"""Falcon: ammunition, precision armor reversal and four marked explosions."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:379100,1:379201,2:379301,10:379401}


class FalconActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp = int(self.stats['iMp'])
        self.enhanced = self.precision_count = 0
        self.reload = self.dash = None
        self.marks = {}

    def _cooldown(self,slot,changed=False):
        skill = 379211 if slot==0 and self.enhanced else SLOTS[slot]
        body = props(skill,slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp = self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self,now):
        self.mp = int(self.stats['iMp'])
        self.reload = self.dash = None
        self.enhanced = self.precision_count = 0
        packets = []
        for t in range(379101,379107):
            packets.extend(self._buff(t,now))
        return packets+[self._cooldown(0,True),scene(mp=(struct.pack('<Ii',self.id,self.mp),))]

    def attr_bonus(self,attributes,now):
        value = super().attr_bonus(attributes,now)
        if any(t in attributes for t in (5,28)):
            value += D('.5')*(1-self.hp/self.max_hp)
        return value

    def _reload(self,now):
        if self.reload or not self.alive or self.mp>=10:
            return []
        self.reload = dict(generation=self.generation)
        self._queue(now+1000,'falcon_reload',self.reload)
        return self._buff(379114,now)

    def interrupt(self,now):
        if not self.dash:
            return []
        self.dash = None
        # The 450ms E reward may outlive a short dash. Interruption can then
        # cancel a newer walk; publish its actual stopped pose as well.
        _,stopped = prepare_displacement(self,now,interrupt=False,cancel_motion=True)
        return stopped+self.remove_buff(379202,now)+self.remove_buff(379207,now)

    def update(self,now):
        return self._reload(now)+super().update(now)

    def damage(self,raw,now,**kwargs):
        if kwargs.get('basic') and self.has_buff(379113,now):
            kwargs['inverse_armor'] = True
        return super().damage(raw,now,**kwargs)

    def _precision(self,now):
        buff = (379111,379121,379122)[self.precision_count-1] if self.precision_count else 0
        if buff and not self.has_buff(buff,now):
            self.precision_count = 0
        packets = []
        for t in (379111,379121,379122):
            packets.extend(self.remove_buff(t,now))
        self.precision_count += 1
        if self.precision_count==4:
            self.precision_count = 0
            packets.extend(self._buff(379113,now))
        else:
            packets.extend(self._buff((379111,379121,379122)[self.precision_count-1],now))
        return packets

    def on_bullet_hit(self,flight,target,now):
        current = self.alive and flight['source_generation']==self.generation
        if flight['template']==379301:
            packets = self._buff(379302,now,target.id)+self._buff(379303,now,target.id)
            if (target.has_buff(379302,now) and target.buff_sources.get(379302)==self.id
                    and target.has_buff(379303,now) and target.buff_sources.get(379303)==self.id):
                self.marks[target.id] = dict(target_generation=target.generation,generation=flight['source_generation'],
                    power=flight['power'],version=target.buff_versions[379302],index=0,end=now+4000)
            return packets
        if not flight['basic']:
            return []
        packets = self._precision(now) if current else []
        if flight['template']==379211 and self.arena.rng.random()<.25:
            packets.extend(self._buff(379212,now,target.id))
        mark = self.marks.get(target.id)
        if (mark and target.alive and mark['target_generation']==target.generation and mark['end']>now
                and target.has_buff(379302,now) and target.buff_versions.get(379302)==mark['version'] and mark['index']<4
                and flight['source_generation']==mark['generation']):
            index = mark['index']
            mark['index'] += 1
            pos = target.position_at(now)
            ident,packet = self.add_object(379321+index,pos)
            packets.append(packet)
            self._queue(now+400,'falcon_explosion',dict(id=ident,pos=pos,power=mark['power'],index=index,
                        generation=mark['generation']))
            packets.extend(target.remove_buff(379303 if index==0 else 379310+index,now))
            if index<3:
                packets.extend(self._buff(379311+index,now,target.id,duration=mark['end']-now))
        return packets

    def on_target_death(self,target,now):
        self.marks.pop(target.id,None)
        return []

    def _radar(self,cast,now):
        packets = []
        for target in list(self.arena.actors.values()):
            if target.camp!=self.camp and hasattr(target,'clear_hidden_traps'):
                packets.extend(target.clear_hidden_traps(cast['pos'],192))
            if target.alive and target.camp!=self.camp and math.dist(cast['pos'],target.position_at(now))<=192:
                packets.extend(self._buff(379411,now,target.id)+self._buff(379412,now,target.id))
        return packets

    def _event(self,now,kind,data):
        if kind=='falcon_reload':
            if self.reload is not data[0] or not self.alive:
                return []
            self.reload = None
            return self._resource(100)+self.remove_buff(379114,now)
        if kind=='falcon_dash':
            cast, = data
            if self.dash is not cast or not self.alive:
                return []
            self.dash = self.reload = None
            self.enhanced = 5
            packets = self._resource(100)+self.remove_buff(379114,now)
            for t in (379203,379204,379206):
                packets.extend(self._buff(t,now))
            return packets+[self._cooldown(0,True),self._cooldown(0)]+self.sync_speed(now)
        if kind=='falcon_radar':
            cast, = data
            packets = self._radar(cast,now)
            if now<cast['end']:
                self._queue(min(now+250,cast['end']),kind,cast)
            else:
                packets.extend(self.remove_object(cast['id']))
            return packets
        if kind=='falcon_explosion':
            cast, = data
            packets = self.remove_object(cast['id'])
            for target in list(self.arena.actors.values()):
                distance = math.dist(cast['pos'],target.position_at(now))
                if target.alive and target.camp!=self.camp and distance<=192:
                    raw = cast['power']*(D('.75')+D('.25')*cast['index'])*(1-D('.5')*D(str(distance))/192)
                    packets.extend(self.damage(raw,now,target=target,school='energy')[0])
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or slot!=10 and start==dest or slot==10 and math.dist(start,dest)>600:
            return []
        if slot==0 and self.mp<10:
            return self._reload(now)
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:25000,10:8000}[slot], slot)
        packets = []
        if slot==0:
            enhanced = self.enhanced>0
            lifesteal = self.attr_bonus((28,),now)+(D('.5') if enhanced else D(0))
            packets.extend(self.shoot(379211 if enhanced else 379100,start,dest,now,power,school='energy',basic=True,
                                      speed_multiplier=1.5,lifesteal=lifesteal,power=power))
            packets.extend(self._resource(-10))
            if enhanced:
                self.enhanced -= 1
                if not self.enhanced:
                    packets.extend(self.remove_buff(379203,now)+self.remove_buff(379204,now))
                    packets.append(self._cooldown(0,True))
            packets.extend(self._reload(now))
        elif slot==1:
            dest = point_at(start,dest,min(1,336/math.dist(start,dest)))
            body,handoff = prepare_displacement(self,now,interrupt=False)
            if not handoff: body = start
            duration = self._set_motion(body,dest,720,now,kind=4)
            self.forced_until = now+duration
            self.dash = dict(generation=self.generation)
            self._queue(now+450,'falcon_dash',self.dash)
            packets.extend(self._buff(379202,now)+self._buff(379207,now))
            packets.extend(handoff)
            packets.append(scene(skills=(self._skill_event(379201,start,self.motion[1]),),moves=(self._move_event(self.motion[1],720,4),)))
        elif slot==2:
            packets.extend(self.shoot(379301,start,dest,now,power*D('1.57'),school='energy',through_walls=True,power=power))
        else:
            ident,packet = self.add_object(379402,dest)
            cast = dict(id=ident,pos=dest,end=now+5000,generation=self.generation)
            packets.extend([packet,scene(skills=(self._skill_event(379401,start,dest),))]+self._radar(cast,now))
            self._queue(now+250,'falcon_radar',cast)
        return packets+[self._cooldown(slot)]
