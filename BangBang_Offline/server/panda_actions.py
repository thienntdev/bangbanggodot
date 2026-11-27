"""Panda base kit. Q09/Q84 math; provisional contact rules documented in DOCS."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, TANK_CONTACT_RADIUS, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:301100, 1:301201, 2:301301, 10:301401}


class PandaActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.skills = {i:table_row('SkillTemplate_table.xml',nId=i) for i in SLOTS.values()}
        self.ready = self.aura = self.roll = None

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None

    def interrupt(self, now):
        packets = []
        if self.ready and (self.ready['slot']!=1 or not self.alive):
            slot = self.ready['slot']
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,SLOTS[slot])))
            if slot==2:
                self.cooldowns[2] = now+self.skill_cooldown(20000, 2)
                packets.append(self._cooldown(2))
        if self.roll:
            self.roll = None
            self.forced_until = now
            packets.extend(self.remove_buff(301403,now))
        # Space is a mobile aura, not an interruptible channel.
        if not self.alive and self.aura:
            self.aura = None
            self.cooldowns[2] = now+self.skill_cooldown(20000, 2)
            packets.append(self._cooldown(2))
        return packets

    def on_death(self):
        self.ready = self.aura = self.roll = None

    def on_bullet_hit(self, flight, target, now):
        if flight['template']==301100 and self.alive and flight['source_generation']==self.generation:
            return self.restore_hp(self.max_hp*D('.01'),now)  # Q09, includes bot tanks.
        return []

    def on_damage(self, source, hit, now, school, reflected, attacker_ap):
        if (not self.alive or not self.aura or now>=self.aura['end'] or school!='energy'
                or reflected or hit.potential_damage<=0 or not source.alive):
            return []
        # Q84: original attacker's AP snapshot, never incoming damage or EN.
        return self.shoot(301331,self.position_at(now),source.position_at(now),now,
                          attacker_ap*D('.5'),school='physical',target=source,
                          reflected=True,lifesteal=D(1))

    def _cleanse(self, now):
        packets = []
        for (owner,template) in list(self.active_buffs):
            if owner!=self.id:
                continue
            row = table_row('BuffTemplate_table.xml',nBuffId=template)
            if row.get('iAspect')=='-1' or int(row['nEffectType']) in (30,36):
                packets.extend(self.remove_buff(template,now))
        return packets

    def _targets(self, now, radius=None):
        start=self.position_at(now)
        return [a for a in self.arena.actors.values() if a.camp!=self.camp
                and a.alive and a.is_area_targetable()
                and (radius is None or math.dist(start,a.position_at(now))<=radius)]

    def _space_target(self, ident, now):
        target=self.arena.actors.get(ident)
        if target is None or target.camp==self.camp or not target.alive or target.is_untargetable():
            return None
        types=target.buff_types(now)
        if 26 in types and 32 not in types:return None
        if math.dist(self.position_at(now),target.position_at(now))>int(self.skills[301301]['iRange']):return None
        return target

    def _pull(self, target, now):
        start = self.position_at(now)
        current = target.position_at(now)
        if not target.alive or target.cc_immune(now) or math.dist(start,current)<=72:
            return []
        # Resolve an interrupted dash from its full path before replacing it.
        origin = target.stop_position(now)
        distance = math.dist(start,origin)
        dest = point_at(start,origin,72/distance) if distance>72 else origin
        wall = self.arena.geometry.wall_contact(origin,dest,TANK_CONTACT_RADIUS)
        if wall is not None:
            dest = point_at(origin,dest,max(0,wall-.001))
        target.position,target.motion = target.move_destination(origin,dest),None
        packets = target.interrupt(now)
        return packets+[scene(moves=(self._move_event(target.position,0,5,target.id),))]

    def _event(self, now, kind, data):
        if kind=='prepared':
            cast, = data
            if self.ready is not cast or not self.alive or cast['generation']!=self.generation:
                return []
            self.ready = None
            start = self.position_at(now)
            if cast['slot']==1:
                packets = [scene(skills=(self._skill_event(301201,start,start,self.id),))]
                packets.extend(self._cleanse(now))
                packets.extend(self.add_shield(301201,self.max_hp*D('.15'),now))
                for target in self._targets(now,192):
                    # Original effects 301203 -> 301204 -> 301205: pull, stun,
                    # then damage. Killing first would skip the pull entirely.
                    packets.extend(self._pull(target,now))
                    packets.extend(self._buff(301204,now,target.id))
                    packets.extend(self.damage(cast['power']*D('1.57'),now,target=target)[0])
                    # Damage may finish the match and freeze all survivors.
                    # Do not pull another recipient from this active callback.
                    if self.arena.pk and self.arena.pk['finished']:
                        break
                return packets
            target=self._space_target(cast.get('target'),now)
            if target is None or target.generation!=cast['target_generation']:
                self.cooldowns[2] = now+self.skill_cooldown(20000, 2)
                return [(1583,struct.pack('<II',self.id,301301)),self._cooldown(2)]
            dest = self.move_destination(start,target.position_at(now))
            self.position,self.motion = dest,None
            cast['end'] = now+5000
            self.aura = cast
            # Instant relocation must reach self too; presentation converts
            # SERVER5/speed0 to S1554 before the Space effect is dispatched.
            packets = [scene(moves=(self._move_event(dest,0,5),),
                             skills=(self._skill_event(301301,start,dest,target.id),))]
            for template in (301303,301305,301306):
                packets.extend(self._buff(template,now))
            packets.extend(self.damage(cast['power']*D('2.33'),now,target=target,lifesteal=D(1))[0])
            packets.extend(self._buff(301302,now,target.id))
            for offset in range(250,5001,250):
                self._queue(now+offset,'aura_tick',cast)
            self._queue(now+5000,'aura_end',cast)
            return packets
        if kind in ('aura_tick','aura_end'):
            cast, = data
            if self.aura is not cast or not self.alive:
                return []
            if kind=='aura_end':
                self.aura = None
                self.cooldowns[2] = now+self.skill_cooldown(20000, 2)
                return [self._cooldown(2)]
            packets=[]
            for target in self._targets(now,192):
                packets.extend(self.damage(cast['power']*D('.25'),now,target=target,lifesteal=D(1))[0])
                packets.extend(self._buff(301312,now,target.id))
            return packets
        if kind=='roll_tick':
            roll, = data
            if self.roll is not roll or not self.alive:
                return []
            start = point_at(roll['start'],roll['dest'],(roll['previous']-roll['began'])/roll['duration'])
            end = self.position_at(now)
            packets = []
            for target in self._targets(now):
                if target.id in roll['hit']:continue
                contact = actor_contact(start,end,target,roll['previous'],now)
                if contact is not None:
                    roll['hit'].add(target.id)
                    # Original effects 301411 -> 301412 -> 301413.
                    packets.extend(self._buff(301411,now,target.id))
                    packets.extend(self._buff(301412,now,target.id))
                    packets.extend(self.damage(roll['power']*D('1.71'),now,target=target)[0])
            if now>=roll['began']+roll['duration']:
                self.roll = None
                packets.extend(self.remove_buff(301403,now))
            else:
                roll['previous'] = now
                self._queue(min(now+20,roll['began']+roll['duration']),'roll_tick',roll)
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or not self.alive or self.ready or self.cooldowns[slot]>now:
            return []
        # Original iUseInStun=1 permits E to cleanse even during hard CC.
        if slot!=1 and super().blocked('attack',now):
            return []
        row,power = self.skills[SLOTS[slot]],self.combat_stat('iAttack',now)
        if slot==2:
            target = self._space_target(target_id,now)
            if self.aura or target is None:
                return []
            dest = target.position_at(now)
        elif slot in (0,10) and (not self._inside(dest) or start==dest):
            return []
        self.cooldowns[slot] = now+(self.skill_cooldown(self.fire_interval(now) if slot==0 else int(row['iCoolTime']), slot))
        if slot==0:
            return self.shoot(301100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        if slot==10:
            dest = point_at(start,dest,336/math.dist(start,dest))
            dest = self.arena.geometry.clamp_tank_position(dest)
            body,stopped = prepare_displacement(self,now,interrupt=False)
            body = body if stopped else start
            wall = self.arena.geometry.wall_contact(body,dest,TANK_CONTACT_RADIUS)
            if wall is not None:
                dest = point_at(body,dest,max(0,wall-.001))
            dest = tuple(round(x) for x in dest)
            duration = self._set_motion(body,dest,720,now,kind=4)
            dest = self.motion[1]
            self.forced_until = now+duration
            self.roll = dict(start=body,dest=dest,began=now,previous=now,duration=duration,hit=set(),power=power)
            self._queue(now+min(20,duration),'roll_tick',self.roll)
            movement = scene(moves=(self._move_event(dest,720,4),),skills=(self._skill_event(301401,start,dest),))
            packets = [self._cooldown(10)]+self._buff(301403,now)
            return packets+stopped+[movement] if stopped else [movement]+packets
        body,stopped = prepare_displacement(self,now,interrupt=False)
        self.position,self.motion = body if stopped else start,None
        stopped_roll = self.interrupt(now) if self.roll else []
        self.ready = dict(slot=slot,power=power,generation=self.generation,dest=dest)
        if slot==2:
            self.ready.update(target=target.id,target_generation=target.generation)
            self.cooldowns[2] = now+int(row['iReadyTime'])+5000+self.skill_cooldown(int(row['iCoolTime']), 2)
        self._queue(now+int(row['iReadyTime']),'prepared',self.ready)
        return stopped_roll+[scene(moves=(self._move_event(start,0,5),),skills=(self._skill_event(SLOTS[slot],start,dest,target_id,ready=1),)),self._cooldown(slot)]+stopped
