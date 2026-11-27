"""Mikasa: wall-only hook, bounded travel and separate E/Space reserves."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at, rect_contact
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,prepare_displacement

SLOTS = {0:352100,1:352201,2:352301,10:352401}


class MikasaActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp = int(self.stats['iMp'])
        self.e_count = self.space_count = 3
        self.e_next_charge = self.space_next_charge = 0
        self.ready = self.hook = self.dash = self.reload = None

    def _cooldown(self,slot):
        count = self.e_count if slot==1 else self.space_count if slot==2 else -1
        next_charge = self.e_next_charge if slot==1 else self.space_next_charge if slot==2 else 0
        return 1572,props(SLOTS[slot],slot,count,self.cooldowns[slot],next_charge)+struct.pack('<I',self.id)

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp = self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self,now):
        self.mp = int(self.stats['iMp'])
        self.hook = self.dash = self.ready = self.reload = None
        self._queue(now+1000,'mikasa_energy',self.generation)
        return self._buff(352101,now)+[scene(mp=(struct.pack('<Ii',self.id,self.mp),))]

    def damage(self,raw,now,**kwargs):
        if kwargs.get('school','physical')=='physical':
            kwargs['inverse_armor'] = True
        return super().damage(raw,now,**kwargs)

    def _speed(self,now):
        return 0 if self.ready or self.hook else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.hook) or super().blocked(action,now)

    def cc_immune(self,now,*,slow=False):
        return bool(self.dash) or self.has_buff(352404,now) or super().cc_immune(now,slow=slow)

    def _end_reload(self,now):
        if not self.reload:
            return []
        self.reload = None
        self.cooldowns[10] = now+self.skill_cooldown(7000, 10)
        packets = []
        for template in (352404,352405,352407):
            packets.extend(self.remove_buff(template,now))
        return packets+[self._cooldown(10)]

    def cleanse(self,now):
        packets=super().cleanse(now)
        # Some native stun rows are labelled positive (iAspect=1). R explicitly
        # clears hostile controls too; never remove the caster's own locks.
        for (owner,template) in list(self.active_buffs):
            source=self.arena.actors.get(self.buff_sources.get(template))
            if owner!=self.id or not source or source.camp==self.camp:continue
            row=table_row('BuffTemplate_table.xml',nBuffId=template)
            if int(row['nEffectType']) in (30,35,36,39,62,66):
                packets.extend(self.remove_buff(template,now))
        return packets

    def remove_buff(self,template,now,*,expired=False):
        packets = super().remove_buff(template,now,expired=expired)
        if template==352406:
            packets.extend(self._end_reload(now))
        return packets

    def interrupt(self,now):
        if self.alive and self.dash:
            return []  # Successful hook travel is immune to control.
        packets = []
        if self.ready:
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,352401)))
        packets.extend(self._remove_hook_line())
        self.hook = self.dash = None
        self.position,self.motion,self.forced_until = self.position_at(now),None,now
        packets.extend(self.remove_buff(352201,now)+self.remove_buff(352601,now))
        if not self.alive:
            packets.extend(self._end_reload(now))
        return packets+self.sync_speed(now)

    def update(self,now):
        packets = []
        for slot,count_name,next_name in ((1,'e_count','e_next_charge'),(2,'space_count','space_next_charge')):
            changed = False
            while getattr(self,next_name) and getattr(self,next_name)<=now:
                count = min(3,getattr(self,count_name)+1)
                setattr(self,count_name,count)
                setattr(self,next_name,getattr(self,next_name)+self.skill_cooldown(4000) if count<3 else 0)
                changed = True
            if changed:
                packets.append(self._cooldown(slot))
        return packets+super().update(now)

    def on_bullet_hit(self,flight,target,now):
        return self._resource(5) if flight['basic'] and self.alive and flight['source_generation']==self.generation else []

    def _end_hook(self,now):
        self.hook = None
        return self.remove_buff(352201,now)+self.sync_speed(now)

    def _remove_hook_line(self):
        # LinkBulletView.blow() only stops the hook head; the rope stays linked
        # to its owner until NOTIFY_BULLET_REMOVE. Keep it during the pull,
        # then remove the same object ID (also for skins and copied E).
        ident = self.dash.pop('bullet',None) if self.dash else None
        return [scene(expired_bullets=(struct.pack('<I',ident),))] if ident is not None else []

    def _flight(self,flight,now):
        if flight['template']!=352501:
            return super()._flight(flight,now)
        cast = flight['context']
        if self.hook is not cast or not self.alive or flight['source_generation']!=self.generation:
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        start = point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        contacts = [x for x in (self.arena.geometry.wall_contact(start,end),rect_contact(start,end,self.arena.water_rects(now))) if x is not None]
        if contacts:
            latch = point_at(start,end,min(contacts))
            packets = self._end_hook(now)
            origin = self.position_at(now)
            # Stop the body before the surface reached by the thin hook.
            hit = self.arena.geometry.wall_contact(origin,latch,36)
            dest = point_at(origin,latch,max(0,hit-.0001)) if hit is not None else latch
            duration = self._set_motion(origin,dest,720,now,kind=3)
            self.forced_until = now+duration
            self.dash = dict(end=now+duration,previous=now,generation=self.generation,hits=set(),power=cast['power'],bullet=flight['id'])
            self._queue(now+min(20,duration),'mikasa_dash',self.dash)
            packets.extend(self._buff(352502,now)+self._buff(352504,now)+self._buff(352601,now,duration=duration))
            return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),),moves=(self._move_event(self.motion[1],720,3),))]
        if now>=flight['finish']:
            return self._end_hook(now)+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return []

    def _event(self,now,kind,data):
        if kind=='mikasa_energy':
            if data[0]!=self.generation or not self.alive:
                return []
            self._queue(now+1000,kind,self.generation)
            return self._resource(5)
        if kind=='mikasa_dash':
            cast, = data
            if self.dash is not cast or not self.alive:
                return []
            start,end = self.position_at(cast['previous']),self.position_at(now)
            packets = []
            for target in enemies(self):
                key = target.id,target.generation
                if key not in cast['hits'] and actor_contact(start,end,target,cast['previous'],now) is not None:
                    cast['hits'].add(key)
                    packets.extend(self.damage(cast['power'],now,target=target)[0])
                    packets.extend(self._buff(352602,now,target.id))
            if not self.motion or now>=self.motion[3] or now>=cast['end']:
                packets.extend(self._remove_hook_line())
                self.dash = None
                packets.extend(self.remove_buff(352601,now))
            else:
                cast['previous'] = now
                self._queue(min(now+20,cast['end']),kind,cast)
            return packets
        if kind=='mikasa_reload':
            cast, = data
            if self.ready is not cast or not self.alive:
                return []
            self.ready = None
            start = self.position_at(now)
            dest = aimed(start,cast['dest'],336,fixed=True)
            self.forced_until = now+self._set_motion(start,dest,960,now,kind=3)
            self.reload = dict(end=now+4000)
            packets = self.cleanse(now)+self._resource(75)
            for template in (352404,352405,352407):
                packets.extend(self._buff(template,now))
            packets.extend(self.add_shield(352406,self.max_hp*D('.25'),now))
            return packets+[scene(moves=(self._move_event(self.motion[1],960,3),))]+self.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or not self.alive or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if (slot!=10 and self.blocked('attack',now)) or (slot==10 and (self.reload or self.ready)):
            return []
        if slot in (0,1,10) and start==dest or slot==1 and (not self.e_count or self.mp<50) or slot==2 and not self.space_count:
            return []
        packets = []
        if slot==0:
            self.cooldowns[0] = now+self.fire_interval(now)
            packets.extend(self.shoot(352100,start,dest,now,self.combat_stat('iAttack',now),school='physical',basic=True))
        elif slot==1:
            self.e_count -= 1
            self.e_next_charge = self.e_next_charge or now+self.skill_cooldown(4000)
            self.cooldowns[1] = now+self.skill_cooldown(1500, 1)
            packets.extend(self._resource(-50))
            self.hook = dict(generation=self.generation,power=self.combat_stat('iAttack',now))
            packets.extend(self._buff(352201,now,duration=401))
            packets.extend(self.shoot(352501,start,dest,now,0,school='physical',context=self.hook))
        elif slot==2:
            self.space_count -= 1
            self.space_next_charge = self.space_next_charge or now+self.skill_cooldown(4000)
            self.cooldowns[2] = now+self.skill_cooldown(1500, 2)
            packets.append(scene(skills=(self._skill_event(352301,start,start),)))
            critical = self.has_buff(352502,now)
            power = self.combat_stat('iAttack',now)*(2 if critical else 1)
            for target in enemies(self,area=True):
                if math.dist(start,target.position_at(now))>144:
                    continue
                stacks = target.buff_stacks.get(352302,0) if target.has_buff(352302,now) and target.buff_sources.get(352302)==self.id else 0
                packets.extend(self.damage(power*(1+D('.25')*stacks),now,target=target,lifesteal=D('.5'),
                                           critical_display=critical)[0])
                packets.extend(self._buff(352302,now,target.id,stacks=min(3,stacks+1)))
        else:
            origin,stopped = prepare_displacement(self,now,interrupt=False)
            packets.extend(self._remove_hook_line())
            self.hook = self.dash = None
            packets.extend(self.remove_buff(352201,now)+self.remove_buff(352601,now)+self.cleanse(now))
            self.position,self.motion,self.forced_until = origin if stopped else start,None,now
            self.ready = dict(slot=10,dest=dest,generation=self.generation)
            self._queue(now+150,'mikasa_reload',self.ready)
            packets.append(scene(skills=(self._skill_event(352401,start,dest,ready=1),)))
            packets.extend(self.sync_speed(now))
            packets.extend(stopped)
        return packets+[self._cooldown(slot)]
