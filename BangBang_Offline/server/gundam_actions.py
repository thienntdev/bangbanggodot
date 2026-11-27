"""Gundam base skills. User decisions/provisional rules: HienTaiBangbang.md."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import TANK_CONTACT_RADIUS, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

GUNDAM = 10000019
EXTRA_MISSILE_CHANCE = .25  # User chose description/V1 over raw Effect40%.
SLOTS = {0:302600, 1:302701, 2:302801, 10:302901}


class GundamActions(TankActions):
    def __init__(self, arena, ident, info, camp, spawn):
        super().__init__(arena,ident,info,camp,spawn)
        self.skills = {i:table_row('SkillTemplate_table.xml',nId=i) for i in SLOTS.values()}
        self.effects = {i:table_row('EffectTemplate_table.xml',nId=i)
                        for i in (302600,302611,302701,302801,302902,302911)}
        self.ready = None
        self.cast_serial = 0
        self.combo_target = None
        self.combo_count = self.combo_until = 0

    def _cooldown(self, slot):
        return 1572, props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None

    def on_death(self):
        self.ready = None
        self.combo_target = None
        self.combo_count = self.combo_until = 0

    def update(self, now):
        if now >= self.combo_until:
            self.combo_target = None
            self.combo_count = 0
        return super().update(now)

    def interrupt(self, now):
        if self.ready is None:
            return []
        self.ready = None
        self.cooldowns[2] = now+self.skill_cooldown(int(self.skills[302801]['iSkillBreakCoolTime']), 2)
        return [(1583,struct.pack('<II',self.id,302801)),self._cooldown(2)]

    def _clear_marks(self, target):
        packets = []
        for template in (302601,302602):
            item = self.active_buffs.pop((target.id,template),None)
            if item:
                packets.append((1559,struct.pack('<II',target.id,item[0])))
        return packets

    def on_bullet_hit(self, flight, target, now):
        packets = []
        if flight['template']==302911:
            packets.extend(self._buff(302912,now,target.id))
        # User: primary basic, E and R all count/proc; extra missile never recurses.
        if (flight.get('proc') or not flight['basic'] or not self.alive
                or flight['source_generation']!=self.generation or not target.alive):
            return packets
        key = target.id,target.generation
        if self.combo_target!=key or now>=self.combo_until:
            self.combo_count = 0
        self.combo_target = key
        self.combo_count += 1
        self.combo_until = now+int(table_row('BuffTemplate_table.xml',nBuffId=302601)['iPersistTime'])
        packets.extend(self._clear_marks(target))
        if self.combo_count == 3:
            self.combo_count = 0
            packets.extend(self._buff(302612,now,target.id))
            packets.extend(self.damage(flight['power']*D(self.effects[302611]['fAddVal']),
                                       now,target=target,school='energy',basic=True)[0])
        else:
            packets.extend(self._buff(302600+self.combo_count,now,target.id))
        if target.alive and self.arena.rng.random() < EXTRA_MISSILE_CHANCE:
            packets.extend(self.shoot(302602,self.position_at(now),target.position_at(now),now,
                            flight['power']*D(self.effects[302701]['fAddVal']),school='energy',
                            basic=True,target=target,proc=True,power=flight['power']))
        return packets

    def _event(self, now, kind, data):
        if kind=='missile':
            generation,target_id,target_generation,power = data
            target = self.arena.actors[target_id]
            if self.alive and self.generation==generation and target.alive and target.generation==target_generation:
                return self.shoot(302701,self.position_at(now),target.position_at(now),now,
                                  power*D(self.effects[302701]['fAddVal']),school='energy',
                                  basic=True,target=target,power=power)
            return []
        if kind=='laser':
            token,generation,start,dest,power = data
            if not self.alive or self.generation!=generation or self.ready!=token:
                return []
            self.ready = None
            packets = [scene(skills=(self._skill_event(302801,start,dest),))]
            distance = math.dist(start,dest)
            ux,uy = ((dest[0]-start[0])/distance,(dest[1]-start[1])/distance)
            length = int(self.effects[302801]['iRange1'])
            half_width = int(self.effects[302801]['iRange2'])/2
            # Original client draws a length528/width72 rectangle. Tank radius36
            # is the same approved contact placeholder used by other attacks.
            # Damage may spawn a substitute. Finish this hit's existing targets;
            # the newly created object participates in later hits only.
            for target in list(self.arena.actors.values()):
                if not target.alive or target.camp==self.camp:
                    continue
                tx,ty = target.position_at(now)
                dx,dy = tx-start[0],ty-start[1]
                along,side = dx*ux+dy*uy,-dx*uy+dy*ux
                outside_x = max(0,-along,along-length)
                outside_y = max(0,abs(side)-half_width)
                if math.hypot(outside_x,outside_y) <= TANK_CONTACT_RADIUS:
                    packets.extend(self.damage(power*D(self.effects[302801]['fAddVal']),now,
                                               target=target,school='energy')[0])
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.cooldowns[slot]>now:
            return []
        skill = SLOTS[slot]
        row = self.skills[skill]
        power = self.combat_stat('iEgAtk',now)
        if slot==1:
            target = self.arena.actors.get(target_id)
            if (target is None or not target.alive or target.camp==self.camp
                    or target.is_untargetable()
                    or math.dist(start,target.position_at(now))>int(row['iRange'])):
                return []
            dest = target.position_at(now)
        elif not self._inside(dest) or start==dest:
            return []
        self.cooldowns[slot] = now+(self.skill_cooldown(self.fire_interval(now) if slot==0 else int(row['iCoolTime']), slot))
        if slot==0:
            return self.shoot(skill,start,dest,now,power*D(self.effects[302600]['fAddVal']),
                              school='energy',basic=True,speed_multiplier=2,power=power)+[self._cooldown(slot)]
        if slot==1:
            for count in range(1,int(row['iCount'])+1):
                self._queue(now+count*int(row['iInterval']),'missile',
                            self.generation,target.id,target.generation,power)
            return [scene(skills=(self._skill_event(skill,start,dest,target.id),)),self._cooldown(slot)]
        if slot==10:
            packets = self.shoot(302911,start,dest,now,power*D(self.effects[302911]['fAddVal']),
                                 school='energy',basic=True,power=power)
            # Effect302902: recoil speed960/distance300, opposite the shot.
            effect = self.effects[302902]
            end = point_at(start,dest,-int(effect['nEffectValB'])/math.dist(start,dest))
            end = self.arena.geometry.clamp_tank_position(end)
            body,stopped = prepare_displacement(self,now,interrupt=False)
            body = body if stopped else start
            wall = self.arena.geometry.wall_contact(body,end,TANK_CONTACT_RADIUS)
            if wall is not None:
                end = point_at(body,end,max(0,wall-.001))
            end = tuple(round(x) for x in end)
            speed = int(effect['fEffectVal'])
            self.forced_until = now+self._set_motion(body,end,speed,now,kind=3)
            end = self.motion[1]
            packets.extend(stopped)
            packets.extend((scene(moves=(self._move_event(end,speed,3),)),self._cooldown(slot)))
            return packets
        self.cast_serial += 1
        self.ready = self.cast_serial
        body,stopped = prepare_displacement(self,now,interrupt=False)
        self.position, self.motion = body if stopped else start,None
        self._queue(now+int(row['iReadyTime']),'laser',self.ready,self.generation,start,dest,power)
        return [scene(moves=(self._move_event(start,0,5),),
                      skills=(self._skill_event(skill,start,dest,ready=1),)),self._cooldown(slot)]+stopped
