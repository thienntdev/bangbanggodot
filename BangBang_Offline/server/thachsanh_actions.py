"""Thach Sanh: per-target arrow budget, critical basics and extended Space."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:338100, 1:338201, 2:338301, 10:338101}
SPACE = (338302,338303,338304,338305,338306)


class ThachSanhActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.roll = None

    def _cooldown(self, slot, changed=False):
        skill = 338311 if slot==0 and self.has_buff(338302,self.clock()) else SLOTS[slot]
        body = props(skill,slot,-1,self.cooldowns[slot])
        return (1579,body) if changed else (1572,body+struct.pack('<I',self.id))

    def _basic_slot(self):
        # S1579 has no owner ID: it changes the local player's button only.
        # Bots retain S1572 with their own actor ID and normal buff/fire visuals.
        return ([self._cooldown(0,True)] if self.id==1 else [])+[self._cooldown(0)]

    def on_spawn(self, now):
        packets = []
        for template in (338411,338412,338413):
            packets.extend(self._buff(template,now))
        return packets+self._basic_slot()

    def remove_buff(self, template, now, *, expired=False):
        existed = (self.id,template) in self.active_buffs
        packets = super().remove_buff(template,now,expired=expired)
        if template==338302 and existed:
            packets.extend(self._basic_slot())
        return packets

    def blocked(self, action, now):
        return super().blocked(action,now) or self.roll is not None

    def interrupt(self, now):
        if self.roll is None:
            return []
        self.roll = None
        self.position,self.motion,self.forced_until = self.position_at(now),None,now
        return [scene(moves=(self._move_event(self.position,0,5),))]+self.remove_buff(338106,now)

    def _reward(self, now, generation):
        if not self.alive or self.generation!=generation:
            return []
        packets = self._buff(338421,now)
        if self.has_buff(338305,now):
            # User: +5 s to the existing remaining duration, not a second form.
            for template in SPACE:
                end = self.active_buffs.get((self.id,template),(0,0))[1]
                if end>now:
                    packets.extend(self._buff(template,now,duration=end-now+5000))
            packets.extend(self._buff(338405,now)+self._buff(338406,now))
            self.cooldowns[10] = 0
            packets.append(self._cooldown(10))
        return packets

    def _hit(self, flight, target, now):
        key = target.id,target.generation
        raw = flight['raw']
        if flight['template']==338201:
            budget = flight['context']
            used = budget.get(key,D(0))
            raw = min(raw,max(D(0),flight['power']*D('2.25')-used))
            budget[key] = used+raw  # Consume raw budget before armor/shields.
        packets = []
        if raw:
            was_alive = target.alive
            steal = flight['lifesteal'] if flight['source_generation']==self.generation else 0
            # This kit already snapshots crit and basic-vamp via attr_bonus.
            packets.extend(self.damage(raw,now,target=target,basic=flight['basic'],lifesteal=steal,
                                       critical_handled=flight['basic'],crystal_vamp=not flight['basic'],
                                       critical_display=flight.get('critical_display',False))[0])
            if was_alive and not target.alive:
                packets.extend(self._reward(now,flight['source_generation']))
        if flight['template']==338201:
            packets.extend(self._buff(338202,now,target.id))
        return packets

    def _flight(self, flight, now):
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        contacts = []
        for target in self.arena.actors.values():
            if target.alive and target.camp!=self.camp and (target.id,target.generation) not in flight['hits']:
                hit = actor_contact(start,end,target,previous,now)
                if hit is not None:
                    contacts.append((hit,target.id))
        wall = self.arena.geometry.wall_contact(start,end)  # User: even Space arrows stop at inner walls.
        packets = []
        for hit,ident in sorted(contacts):
            if wall is not None and hit>=wall:
                break
            target = self.arena.actors[ident]
            flight['hits'].add((ident,target.generation))
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            packets.extend(self._hit(flight,target,now))
            if flight['template']!=338311:
                return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if now>=finish or wall is not None:
            return packets+[scene(**{('blown_bullets' if wall is not None else 'expired_bullets'):
                                     (struct.pack('<I',flight['id']),)})]
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return packets

    def _event(self, now, kind, data):
        if kind=='thach_roll_end':
            roll, = data
            if self.roll is not roll:
                return []
            _,stopped = prepare_displacement(self,now,interrupt=False)
            return stopped+self.interrupt(now)
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if (slot not in SLOTS or not self.alive or self.roll or self.skill_sealed(slot,now)
                or self.cooldowns[slot]>now or slot!=10 and self.blocked('attack',now)):
            return []
        if slot!=2 and (not self._inside(dest) or start==dest):
            return []
        self.cooldowns[slot] = now+(self.skill_cooldown(self.fire_interval(now) if slot==0 else 30000 if slot==2 else 8000, slot))
        packets = [self._cooldown(slot)]
        power = self.combat_stat('iAttack',now)
        if slot==0:
            critical = self.arena.rng.random()<float(min(D(1),self.attr_bonus((27,),now)))
            ratio = max(D(1),D(2)+self.attr_bonus((31,),now)) if critical else D(1)
            template = 338311 if self.has_buff(338302,now) else 338100
            return packets+self.shoot(template,start,dest,now,power*D('1.5')*ratio,
                school='physical',basic=True,power=power,speed_multiplier=1.5,
                lifesteal=self.attr_bonus((28,),now),critical_display=critical)
        if slot==1:
            # Client draws a total 30-degree sector. Five evenly spaced arrows
            # share a raw budget; their separate contact sets remain independent.
            budget = {}
            angle = math.atan2(dest[1]-start[1],dest[0]-start[0])
            for offset in (-15,-7.5,0,7.5,15):
                rad = angle+math.radians(offset)
                aim = (round(start[0]+600*math.cos(rad)),round(start[1]+600*math.sin(rad)))
                packets.extend(self.shoot(338201,start,aim,now,power*D('1.5'),
                                          school='physical',power=power,context=budget))
            return packets
        if slot==2:
            packets.extend(self.restore_hp(self.max_hp*D('.25'),now))
            for template in SPACE:
                packets.extend(self._buff(template,now))
            return packets+self._basic_slot()
        body,stopped=prepare_displacement(self,now,interrupt=False)
        body=body if stopped else start
        # V1 permits rolling under hard CC. Clear crowd control, not unrelated
        # marks/healing debuffs; collision rules are independent of cleansing.
        for (owner,template) in list(self.active_buffs):
            if owner!=self.id:
                continue
            row = table_row('BuffTemplate_table.xml',nBuffId=template)
            effect = int(row['nEffectType'])
            if row.get('iAspect')=='-1' and (effect in (30,35,36,66) or
                    effect==201 and row.get('nTypeParam')=='11' and D(row.get('fEffectValA','0'))<0):
                packets.extend(self.remove_buff(template,now))
        self.cooldowns[1] = 0
        packets.append(self._cooldown(1))
        for template in (338103,338104,338105,338106):
            packets.extend(self._buff(template,now))
        dest = point_at(start,dest,264/math.dist(start,dest))
        duration = self._set_motion(body,dest,720,now,4)
        self.forced_until = self.motion[3]
        self.roll = dict(generation=self.generation)
        self._queue(now+duration,'thach_roll_end',self.roll)
        return packets+stopped+[scene(moves=(self._move_event(self.motion[1],720,4),),
                              skills=(self._skill_event(338101,start,self.motion[1]),))]
