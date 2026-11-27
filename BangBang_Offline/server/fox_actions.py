"""Nine-tailed Fox: independent per-wave/per-target decay and finite foxfire."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:360100,1:360401,2:360701,10:360201}


class FoxActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.e_count,self.space_count = 3,3
        self.e_next_charge = self.space_next_charge = 0
        self.ready = self.foxfire = None
        self.fire_count = 0

    def _cooldown(self,slot):
        count = self.e_count if slot==1 else self.space_count if slot==2 else -1
        charge = self.e_next_charge if slot==1 else self.space_next_charge if slot==2 else 0
        return 1572,props(SLOTS[slot],slot,count,self.cooldowns[slot],charge)+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.foxfire,self.fire_count = None,0
        return self._buff(360101,now)

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def interrupt(self,now):
        packets = []
        if self.ready:
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,360701)))
        if not self.alive:
            self.foxfire,self.fire_count = None,0
        return packets+self.sync_speed(now)

    def update(self,now):
        packets = self.interrupt(now) if self.ready and self.skill_sealed(2,now) else []
        for slot,field,clock in ((1,'e_count','e_next_charge'),(2,'space_count','space_next_charge')):
            while getattr(self,clock) and getattr(self,clock)<=now:
                count = min(3,getattr(self,field)+1)
                setattr(self,field,count)
                setattr(self,clock,getattr(self,clock)+self.skill_cooldown(6000) if count<3 else 0)
                packets.append(self._cooldown(slot))
        return packets+super().update(now)

    def _fire_visual(self,now,template=0):
        packets = []
        for t in range(360102,360113):
            packets.extend(self.remove_buff(t,now))
        if template:
            packets.extend(self._buff(template,now))
        return packets

    def _stack_fire(self,now,generation):
        if not self.alive or generation!=self.generation or self.foxfire:
            return []
        if self.fire_count and not self.has_buff(360101+self.fire_count,now):
            self.fire_count = 0
        self.fire_count += 1
        packets = self._fire_visual(now,360101+self.fire_count)
        if self.fire_count==5:
            self.foxfire = dict(left=5,counts={},end=now+10000,generation=self.generation)
            self.fire_count = 0
            self._queue(now+400,'fox_fire',self.foxfire)
        return packets

    def on_bullet_hit(self,flight,target,now):
        if flight['template']==360201:
            return self._buff(360202,now,target.id)+self._buff(360203,now,target.id)+self._stack_fire(now,flight['source_generation'])
        if flight['template']==360601:
            cast = flight['context']
            key = target.id,target.generation
            count = cast['counts'].get(key,0)
            cast['counts'][key] = count+1
            packets = self.damage(flight['power']*D('.8')**count,now,target=target,school='energy')[0]
            if self.alive and flight['source_generation']==self.generation and not target.info.get('npc_template'):
                packets.extend(self.restore_hp(flight['power']*D('.5'),now))
            return packets
        return []

    def _flight(self,flight,now):
        if flight['template']!=360401:
            return super()._flight(flight,now)
        start = point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        contacts,packets = [],[]
        for target in list(self.arena.actors.values()):
            key = target.id,target.generation
            if not target.alive or target.camp==self.camp or key in flight['hits'] or target.is_untargetable():
                continue
            hit = actor_contact(start,end,target,flight['previous'],now,84)
            if hit is not None:
                contacts.append((hit,target.id,target,key))
        for _,_,target,key in sorted(contacts):
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            count = flight['context']['counts'].get(key,0)
            raw = flight['raw']*D('.75')**(len(flight['hits'])+count)
            flight['hits'].add(key)
            flight['context']['counts'][key] = count+1
            packets.extend(self.damage(raw,now,target=target,school='energy')[0])
            if self.alive and flight['source_generation']==self.generation:
                if self.e_next_charge:
                    self.e_next_charge = max(now,self.e_next_charge-300)
                    packets.append(self._cooldown(1))
                packets.extend(self._stack_fire(now,flight['source_generation']))
        if now>=flight['finish']:
            return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _blink_hit(self,pos,cast,now):
        packets = []
        for target in list(self.arena.actors.values()):
            if not target.alive or target.camp==self.camp or math.dist(pos,target.position_at(now))>168:
                continue
            repeat = target.has_buff(360302,now) and target.buff_sources.get(360302)==self.id
            packets.extend(self.damage(cast['power'],now,target=target,school='energy')[0])
            packets.extend(self._buff(360302,now,target.id))
            if repeat:
                packets.extend(self._buff(360311,now,target.id))
            packets.extend(self._stack_fire(now,cast['generation']))
        return packets

    def _event(self,now,kind,data):
        if kind=='fox_fire':
            from bot_ai import team_visible
            cast, = data
            if self.foxfire is not cast or not self.alive or cast['generation']!=self.generation:
                return []
            if now>=cast['end']:
                self.foxfire = None
                return self._fire_visual(now)
            start = self.position_at(now)
            targets = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                       and not a.is_untargetable() and not a.info.get('npc_template')
                       and math.dist(start,a.position_at(now))<=480 and team_visible(self.arena,self,a,now)]
            packets = []
            if targets:
                target = min(targets,key=lambda a:(math.dist(start,a.position_at(now)),a.id))
                power = self.combat_stat('iEgAtk',now)
                packets.extend(self.shoot(360601,start,target.position_at(now),now,D(0),
                                          school='energy',target=target,proc=True,through_walls=True,power=power,context=cast))
                cast['left'] -= 1
                packets.extend(self._fire_visual(now,360113-cast['left'] if cast['left'] else 0))
            if cast['left']:
                self._queue(min(now+400,cast['end']),kind,cast)
            else:
                self.foxfire = None
            return packets
        if kind=='fox_blink':
            cast, = data
            if self.ready is not cast or not self.alive:
                return []
            self.ready = None
            start = self.position_at(now)
            dest = self.blink_destination(start,cast['dest'])
            self.position,self.motion = dest,None
            packets = [scene(moves=(self._move_event(dest,0,5),),skills=(self._skill_event(360701,start,dest),))]
            return packets+self._blink_hit(dest,cast,now)+self.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        from bot_ai import team_visible
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot in (0,1,2) and (start==dest or not self._inside(dest)):
            return []
        if slot==1 and not self.e_count or slot==2 and not self.space_count:
            return []
        target = self.arena.actors.get(target_id)
        if slot==10 and (not target or not target.alive or target.camp==self.camp
                        or target.is_untargetable() or math.dist(start,target.position_at(now))>480
                        or not team_visible(self.arena,self,target,now)):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:1500,2:1500,10:8000}[slot], slot)
        if slot==0:
            return self.shoot(360100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        if slot==10:
            return self.shoot(360201,start,target.position_at(now),now,power*D('1.56'),school='energy',
                              target=target,through_walls=True)+[self._cooldown(10)]
        if slot==1:
            self.e_count -= 1
            if not self.e_next_charge:
                self.e_next_charge = now+self.skill_cooldown(6000)
            cast = dict(counts={},generation=self.generation)
            theta = math.atan2(dest[1]-start[1],dest[0]-start[0])
            packets = [self._cooldown(1)]
            for angle in (-15,0,15):
                rad = theta+math.radians(angle)
                endpoint = start[0]+round(600*math.cos(rad)),start[1]+round(600*math.sin(rad))
                packets.extend(self.shoot(360401,start,endpoint,now,power*D('1.65'),school='energy',through_walls=True,context=cast))
            return packets
        self.space_count -= 1
        if not self.space_next_charge:
            self.space_next_charge = now+self.skill_cooldown(6000)
        dest = point_at(start,dest,min(1,336/math.dist(start,dest)))
        self.position,self.motion = start,None
        cast = self.ready = dict(slot=2,dest=dest,power=power,generation=self.generation)
        ident,packet = self.add_object(360303,start)
        self._queue(now+800,'object_expire',ident)
        self._queue(now+50,'fox_blink',cast)
        return [self._cooldown(2),packet,scene(skills=(self._skill_event(360701,start,dest,ready=1),))]+self._blink_hit(start,cast,now)+self.sync_speed(now)
