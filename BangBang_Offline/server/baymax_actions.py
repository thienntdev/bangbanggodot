"""Baymax: teammate tether and intercept flight, with original client buffs."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene, stop_move

SLOTS = {0:347100,1:347201,2:347301,10:347401}


class BaymaxActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp = int(self.stats['iMp'])
        self.e_count,self.e_next_charge = 3,0
        self.passive_ready_at = 0
        self.ready = self.dash = self.link = self.form = None

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp = self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def _cooldown(self,slot,changed=False):
        body = props(347421 if slot==10 and self.link else SLOTS[slot],slot,
                     self.e_count if slot==1 else -1,self.cooldowns[slot],
                     self.e_next_charge if slot==1 else 0)
        return (1579,body) if changed else (1572,body+struct.pack('<I',self.id))

    def _link_slot(self):
        # S1579 has no owner and changes the local player's button.
        return ([self._cooldown(10,True)] if self.id==1 else [])+[self._cooldown(10)]

    def on_spawn(self,now):
        self.mp = int(self.stats['iMp'])
        self.ready = self.dash = self.link = self.form = None
        self._queue(now+1000,'bay_mp',self.generation)
        packets = self._buff(347101,now)+[scene(mp=(struct.pack('<Ii',self.id,self.mp),))]
        if self.passive_ready_at>now:
            packets.extend(self._buff(347103,now,duration=self.passive_ready_at-now))
        return packets+self._link_slot()

    def _emergency(self,now):
        if not self.alive or self.passive_ready_at>now:
            return []
        allies = [a for a in self.arena.actors.values() if a.alive and a.camp==self.camp and not a.info.get('map_object')
                  and a.hp<=a.max_hp*D('.3') and math.dist(self.position_at(now),a.position_at(now))<=360]
        if not allies:
            return []
        target = min(allies,key=lambda a:(a.hp/a.max_hp,a.id))
        self.passive_ready_at = now+30000
        return (self._buff(347103,now)+self._buff(347102,now,target.id)+self._buff(347104,now,target.id)
                +target.restore_hp(self.combat_stat('iAttack',now)*D('4.5'),now))

    def _valid_link(self,now):
        cast = self.link
        target = self.arena.actors.get(cast['target']) if cast else None
        return (cast and self.alive and self.mp>0 and target and target.alive
                and target.generation==cast['target_generation'] and target.has_buff(347401,now)
                and target.buff_versions.get(347401)==cast['version']
                and math.dist(self.position_at(now),target.position_at(now))<=360)

    def _end_link(self,now):
        cast,self.link = self.link,None
        if not cast:
            return []
        packets = self.remove_buff(347402,now)
        target = self.arena.actors.get(cast['target'])
        if target and target.buff_versions.get(347401)==cast['version']:
            packets.extend(target.remove_buff(347401,now))
        return packets+self._link_slot()

    def _clear_guard(self,cast,now):
        target = self.arena.actors.get(cast['target'])
        return target.remove_buff(347303,now) if target and target.buff_versions.get(347303)==cast['guard_version'] else []

    def interrupt(self,now):
        packets = []
        cast = self.ready or self.dash
        if cast:
            was_dash = self.dash is not None
            self.ready = self.dash = None
            if was_dash:
                # Target death or a skill seal can end the flight inside a wall.
                self.position,self.motion = self.stop_position(now),None
                self.forced_until = 0
                packets.append(scene(moves=(self._move_event(self.position,0,5),)))
            packets.extend(self._clear_guard(cast,now)+self.remove_buff(347302,now))
            packets.append((1583,struct.pack('<II',self.id,347301)))
        if not self.alive:
            packets.extend(self._end_link(now))
            self.form = None
        return packets+self.sync_speed(now)

    def on_target_death(self,target,now):
        packets = self._end_link(now) if self.link and self.link['target']==target.id else []
        cast = self.ready or self.dash
        return packets+(self.interrupt(now) if cast and cast['target']==target.id else [])

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.dash) or super().blocked(action,now)

    def update(self,now):
        packets = []
        if (self.ready or self.dash) and (self.skill_sealed(2,now) or self.dash and not self.motion):
            packets.extend(self.interrupt(now))
        if self.link and not self._valid_link(now):
            packets.extend(self._end_link(now))
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count = min(3,self.e_count+1)
            self.e_next_charge = self.e_next_charge+self.skill_cooldown(6000) if self.e_count<3 else 0
            packets.append(self._cooldown(1))
        return packets+self._emergency(now)+super().update(now)

    def _push(self,target,origin,distance,speed,now):
        if not target.alive or target.cc_immune(now):
            return []
        current = target.position_at(now)
        start = target.stop_position(now)
        length = math.dist(origin,start)
        dest = point_at(origin,start,1+distance/length) if length else (start[0]+distance,start[1])
        if start != current:
            target.position,target.motion = start,None
        packets = target.interrupt(now)
        if start != current:
            packets.append(stop_move(self.scene_id,target.id,start))
        target.forced_until = now+target._set_motion(start,dest,speed,now,kind=1)
        return packets+[scene(moves=(self._move_event(target.motion[1],speed,1,target.id),))]

    def _arrive(self,cast,target,now):
        self.dash = None
        self.position,self.motion = self.position_at(now),None
        self.forced_until = 0
        packets = self._clear_guard(cast,now)+self.remove_buff(347302,now)
        packets.extend(self.add_shield(347321,cast['max_hp']*D('.5'),now))
        packets.extend(target.add_shield(347331,cast['max_hp']*D('.5'),now,caster=self))
        packets.extend(self._buff(347322,now,target.id))
        for enemy in list(self.arena.actors.values()):
            if enemy.alive and enemy.camp!=self.camp and math.dist(self.position,enemy.position_at(now))<=216:
                packets.extend(self._push(enemy,self.position,240,480,now))
        self.form = dict(generation=self.generation,power=cast['power'],end=now+10000)
        for buff in (347324,347325,347326,347327):
            packets.extend(self._buff(buff,now))
        self._queue(now+500,'bay_form',self.form)
        return packets+self.sync_speed(now)

    def _flight(self,flight,now):
        if flight['template']!=347201:
            return super()._flight(flight,now)
        if now<flight['finish']:
            self._queue(flight['finish'],'flight',flight)
            return []
        pos = flight['end']
        ident,packet = self.add_object(347201,pos)
        self._queue(now+100,'object_expire',ident)
        packets = [scene(blown_bullets=(struct.pack('<I',flight['id']),)),packet]
        hit = False
        for target in list(self.arena.actors.values()):
            if target.alive and target.camp!=self.camp and math.dist(pos,target.position_at(now))<=120:
                hit = True
                packets.extend(self.damage(flight['raw'],now,target=target)[0])
                if self.arena.pk and self.arena.pk['finished']:
                    return packets
                packets.extend(self._push(target,pos,120,360,now)+self._buff(347213,now,target.id))
        if hit and self.alive and self.generation==flight['source_generation']:
            previous_version=self.buff_versions.get(347214)
            packets.extend(self._buff(347214,now))
            version=self.buff_versions.get(347214)
            if version!=previous_version and self.has_buff(347214,now) and self.buff_sources.get(347214)==self.id:
                for i in range(1,6):
                    self._queue(now+200*i,'bay_refund',self.generation,version)
        return packets

    def _event(self,now,kind,data):
        if kind=='bay_mp':
            if not self.alive or data[0]!=self.generation:
                return []
            self._queue(now+1000,kind,*data)
            return self._resource(5)
        if kind=='bay_refund':
            return self._resource(5) if self.alive and self.generation==data[0] and self.buff_versions.get(347214)==data[1] else []
        if kind=='bay_link':
            cast, = data
            if self.link is not cast:
                return []
            if not self._valid_link(now) or self.mp<10:
                return self._end_link(now)
            target = self.arena.actors[cast['target']]
            packets = self._resource(-10)
            packets.extend(self.restore_hp(cast['power'],now)+target.restore_hp(cast['power'],now))
            if self.mp==0:
                return packets+self._end_link(now)
            self._queue(now+1000,kind,cast)
            return packets
        if kind=='bay_ready':
            cast, = data
            if self.ready is not cast:
                return []
            target = self.arena.actors.get(cast['target'])
            if not self.alive or not target or not target.alive or target.generation!=cast['target_generation'] or self.skill_sealed(2,now) or super().blocked('attack',now):
                return self.interrupt(now)
            self.ready,self.dash = None,cast
            start,dest = self.position_at(now),target.position_at(now)
            self.forced_until = now+self._set_motion(start,dest,720,now,kind=3)
            cast['previous'] = now
            self._queue(min(now+20,self.forced_until),'bay_dash',cast)
            return (self._buff(347302,now)+[scene(skills=(self._skill_event(347301,start,dest,target.id),),
                    moves=(self._move_event(self.motion[1],720,3),))]+self.sync_speed(now))
        if kind=='bay_dash':
            cast, = data
            if self.dash is not cast:
                return []
            if not self.motion:
                return self.interrupt(now)
            target = self.arena.actors.get(cast['target'])
            if not self.alive or not target or not target.alive or target.generation!=cast['target_generation'] or self.skill_sealed(2,now) or super().blocked('attack',now):
                return self.interrupt(now)
            start,end = self.position_at(cast['previous']),self.position_at(now)
            packets = []
            for enemy in list(self.arena.actors.values()):
                if enemy.alive and enemy.camp!=self.camp and (enemy.id,enemy.generation) not in cast['hits'] and actor_contact(start,end,enemy,cast['previous'],now) is not None:
                    cast['hits'].add((enemy.id,enemy.generation))
                    packets.extend(self.damage(cast['power']*D('2.66'),now,target=enemy)[0])
                    packets.extend(self._buff(347312,now,enemy.id))
                    if self.dash is not cast or not self.alive:return packets
                    if not self.motion:return packets+self.interrupt(now)
            dest = target.position_at(now)
            if math.dist(end,dest)<=1:
                return packets+self._arrive(cast,target,now)
            if self.motion[1]!=dest:
                self.forced_until = now+self._set_motion(end,dest,720,now,kind=3)
                packets.append(scene(moves=(self._move_event(self.motion[1],720,3),)))
            cast['previous'] = now
            self._queue(min(now+20,max(now+1,self.forced_until)),'bay_dash',cast)
            return packets
        if kind=='bay_form':
            cast, = data
            if self.form is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            pos = self.position_at(now)
            packets = [scene(skills=(self._skill_event(347321,pos,pos,self.id),))]
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(pos,target.position_at(now))<=144:
                    packets.extend(self.damage(cast['power']*D('.5'),now,target=target)[0])
                    if self.arena.pk and self.arena.pk['finished']:
                        break
                    packets.extend(self._push(target,pos,72,480,now))
            if now<cast['end']:
                self._queue(now+500,kind,cast)
            else:
                self.form = None
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot==10 and self.link and self.alive and self.cooldowns[10]<=now:
            return self._end_link(now)
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        target = self.arena.actors.get(target_id)
        if slot in (2,10):
            if not target or not target.alive or target.camp!=self.camp or target is self or (slot==2 and target.id>>26!=0) or math.dist(start,target.position_at(now))>(1200 if slot==2 else 336):
                return []
        elif not self._inside(dest) or (slot==0 and start==dest):
            return []
        if slot==1 and (not self.e_count or math.dist(start,dest)>600) or slot==10 and self.mp<20:
            return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+{0:self.fire_interval(now),1:self.skill_cooldown(1250, 1),2:self.skill_cooldown(25000, 2),10:1000}[slot]
        if slot==0:
            return self.shoot(347100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        if slot==1:
            self.e_count -= 1
            if not self.e_next_charge:
                self.e_next_charge = now+self.skill_cooldown(6000)
            ident = self._new_id(2)
            factor=1.15 if self.has_buff(10400233,now) else 1
            flight = dict(kind='bullet',id=ident,template=347201,start=start,end=dest,begin=now,
                          finish=now+round(500/factor),speed=max(1,round(math.dist(start,dest)*2*factor)),previous=now,
                          raw=power*2,source_generation=self.generation)
            self._queue(flight['finish'],'flight',flight)
            return [scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*dest,flight['speed'],347201),)),self._cooldown(1)]
        cast = dict(slot=slot,target=target.id,target_generation=target.generation,generation=self.generation,
                    power=power,max_hp=self.max_hp,dest=target.position_at(now),hits=set())
        packets = [self._cooldown(slot)]
        if slot==2:
            self.position,self.motion = start,None
            self.ready = cast
            packets.extend(self._buff(347303,now,target.id))
            cast['guard_version'] = target.buff_versions.get(347303)
            self._queue(now+500,'bay_ready',cast)
            packets.append(scene(skills=(self._skill_event(347301,start,cast['dest'],target.id,ready=1),)))
            return packets+self.sync_speed(now)
        packets.extend(self._resource(-20)+self._buff(347401,now,target.id)+self._buff(347402,now))
        cast['version'] = target.buff_versions[347401]
        self.link = cast
        self._queue(now+1000,'bay_link',cast)
        return packets+self._link_slot()
