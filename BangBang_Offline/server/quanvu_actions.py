"""Quan Vu mechanics; shared movement/damage/events are in battle_runtime."""
import math
import struct
from battle_runtime import TankActions
from combat_data import table_row as _table_row
from combat_math import D, heal
from combat_geometry import TANK_CONTACT_RADIUS, point_at
from combat_protocol import props, scene, stop_move

QUAN_VU = 10000056
R_USE_INTERVAL_MS = 1500  # User choice over raw2000ms.


class QuanVuActions(TankActions):
    def __init__(self, arena, ident, info, camp, spawn):
        super().__init__(arena, ident, info, camp, spawn)
        self.skills = {i: _table_row("SkillTemplate_table.xml", nId=i)
                       for i in (331100, 331201, 331211, 331221, 331301)}
        self.buffs = {i: _table_row("BuffTemplate_table.xml", nBuffId=i)
                      for i in (331102, 331202, 331204, 331205, 331206,
                                331211, 331212, 331222, 331224, 331304)}
        self.effects = {i: _table_row("EffectTemplate_table.xml", nId=i)
                        for i in (331203, 331221, 331301, 331302, 331303)}
        self.dash_effect = _table_row("EffectTemplate_table.xml", nId=331201)
        self.e_second_until = 0
        self.r_count = int(self.skills[331221]['iStackCount'])
        self.r_next_charge = 0
        self.dash_id = 0

    def damage_bonus(self, target):
        return 1 + (D(self.buffs[331102]['fEffectValA']) if target.hp*2 < target.max_hp else D(0))

    def on_death(self):
        self.e_second_until = 0
        self.dash_id += 1

    def on_dash_hit(self, position, target, now):
        # Damage contact can be inside a narrow map NPC. Resolve the full
        # 72px body from the original dash start, not the last 20ms segment.
        position = self.stop_position(now,position)
        self.position, self.motion, self.forced_until = position, None, now
        packets = [stop_move(self.scene_id,self.id,position),
                   scene(skills=(self._skill_event(331203,position,target.position_at(now),target.id),))]
        if target.alive:
            packets.extend(self._buff(331204,now,target.id))
        return packets

    def _cooldown(self, slot: int, changed=False):
        skill = {0: 331100, 1: 331201, 2: 331301, 10: 331221}[slot]
        end = self.cooldowns[slot]
        if slot == 1 and self.e_second_until:
            skill, end = 331211, 0
        body = props(skill, slot, self.r_count if slot == 10 else -1, end,
                     self.r_next_charge if slot == 10 else 0)
        return (1579, body) if changed and self.id==1 else (1572, body + struct.pack("<I", self.id))


    def _space_hit(self, start, now, victim=None):
        victim = victim or self.enemy
        bot = victim.info
        threshold = D(self.effects[331301]['fEffectVal'])
        execute = victim.hp <= victim.max_hp * threshold
        packets = []
        if execute:
            # General damage immunity is NOT execute immunity (V1 D07).
            if not bot.get('execute_immune') and D(bot.get('death_floor', 0)) == 0:
                victim.damage_credit=(self.id,self.generation)
                try: packets.extend(victim.commit_hp(0, now))
                finally: victim.damage_credit=None
                if victim.alive:
                    # Ghost's first lethal hit changes form, not a successful kill.
                    return packets
                # Original passive presentation: skill331101 -> exhibit568 ->
                # qinglongzhihun.swf + longyin.mp3. Resetting HP/CD alone never
                # tells EffectLayer to play this successful-execute feedback.
                packets.append(scene(skills=(self._skill_event(331101, start, start, self.id),)))
                packets.extend(self.restore_hp((self.max_hp-self.hp)*D('0.25'),now))
                self.e_second_until = 0
                self.cooldowns[1] = 0
                self.r_count = int(self.skills[331221]['iStackCount'])
                self.r_next_charge = self.cooldowns[10] = 0
                self.cooldowns[2] = now + self.skill_cooldown(1500, 2)  # User choice, description.
                packets.extend((self._cooldown(1, changed=True), self._cooldown(1),
                                self._cooldown(10), self._cooldown(2)))
        else:
            packets.extend(self.damage(self.combat_stat('iAttack',now) * D(self.effects[331302]['fAddVal']), now,target=victim)[0])
        if self.arena.pk and self.arena.pk['finished']:
            return packets
        if victim.alive and not victim.cc_immune(now):
            current = victim.position_at(now)
            origin = victim.stop_position(now)
            distance = math.dist(start, origin)
            if distance:
                # Finish the victim's previous dash before replacing its motion.
                if origin!=current:
                    victim.position,victim.motion = origin,None
                packets.extend(victim.interrupt(now))
                if origin!=current:
                    packets.append(stop_move(victim.scene_id,victim.id,origin))
                effect = self.effects[331303]
                dest = point_at(start, origin, 1 + int(effect['nEffectValB']) / distance)
                wall = self.arena.geometry.wall_contact(origin, dest, TANK_CONTACT_RADIUS)
                if wall is not None:
                    dest = point_at(origin, dest, max(0, wall - 0.001))
                dest = tuple(round(x) for x in dest)
                speed = int(effect['fEffectVal'])
                duration = victim._set_motion(origin,dest,speed,now,kind=3)
                dest = victim.motion[1]
                victim.forced_until = now+duration
                packets.append(scene(moves=(self._move_event(dest, speed, 3, victim.id),)))
        return packets


    def update(self, now):
        packets = super().update(now)
        if self.e_second_until and now >= self.e_second_until:
            self.e_second_until = 0
            packets.extend((self._cooldown(1, changed=True), self._cooldown(1)))
        if self.r_next_charge and now >= self.r_next_charge:
            maximum = int(self.skills[331221]["iStackCount"])
            recharge = int(self.skills[331221]["iCoolTime"])
            while self.r_count < maximum and now >= self.r_next_charge:
                self.r_count += 1
                self.r_next_charge += self.skill_cooldown(recharge)
            if self.r_count == maximum:
                self.r_next_charge = 0
            packets.append(self._cooldown(10))
        return packets

    def cast(self, slot, start, dest, target, now):
        packets = []
        second_e = slot == 1 and self.e_second_until > now
        if self.blocked("attack", now) or (self.cooldowns[slot] > now and not second_e):
            return packets
        if (second_e or slot == 2):
            victim = self.arena.actors.get(target)
            if not victim or victim.camp==self.camp or not victim.alive or victim.is_untargetable():
                return packets
            template = self.skills[331211 if second_e else 331301]
            dest = victim.position_at(now)
            if math.dist(start, dest) > int(template["iRange"]):
                return packets
        elif slot in (0, 1) and (not self._inside(dest) or dest == start):
            return packets

        if slot == 0:
            self.cooldowns[0] = now + self.fire_interval(now)
            packets.extend(self.shoot(331100,start,dest,now,self.combat_stat('iAttack',now),school='physical',basic=True))
            packets.append(self._cooldown(0))
        elif second_e:
            dest = self.blink_destination(start,dest)
            self.dash_id += 1  # Cancel an unfinished E1 flight if E2 interrupts it.
            self.e_second_until = 0
            self.position, self.motion, self.forced_until = dest, None, 0
            packets.extend((scene(moves=(self._move_event(dest, 0, 5),),
                                  skills=(self._skill_event(331211, start, dest, target),)),
                            self._cooldown(1, changed=True)))
            packets.append(self._cooldown(1))
            packets.extend(self._buff(331211, now, victim.id))
            packets.extend(self._buff(331212, now, victim.id))
            dot = self.buffs[331212]
            raw = self.combat_stat('iAttack',now) * D(dot['fFixParam'])  # E2 AP snapshot.
            packets.extend(self.damage(raw, now,target=victim)[0])
            if victim.has_buff(331212,now):
                for offset in range(int(dot['iCoolTime']), int(dot['iPersistTime'])+1, int(dot['iCoolTime'])):
                    self._queue(now+offset, 'damage', victim.generation, raw, 331212, victim.buff_versions[331212],victim.id,self.generation)
        elif slot == 1:
            distance = math.dist(start, dest)
            length = min(distance, int(self.skills[331201]["iRange"]))
            dest = tuple(round(a + (b - a) * length / distance) for a, b in zip(start, dest))
            # Description explicitly allows E's dash through map obstructions.
            speed = int(float(self.dash_effect["fEffectVal"]))
            duration = self._set_motion(start, dest, speed, now, kind=3)
            dest = self.motion[1]
            self.forced_until = now + duration
            self.cooldowns[1] = now + self.skill_cooldown(int(self.skills[331201]["iCoolTime"]), 1)
            self.e_second_until = now + int(self.buffs[331205]["iPersistTime"])
            packets.append(scene(moves=(self._move_event(dest, speed, 3),),
                                 skills=(self._skill_event(331201, start, dest),)))
            packets.extend(self._buff(331202, now))
            packets.extend(self._buff(331206, now))
            packets.append(self._cooldown(1, changed=True))
            self.dash_id += 1
            self._launch('dash', self.dash_id, start, dest, duration,
                         self.combat_stat('iAttack',now)*D(self.effects[331203]['fAddVal']), now)
        elif slot == 10:
            if self.r_count == 0:
                return packets
            self.r_count -= 1
            self.cooldowns[10] = now + self.skill_cooldown(R_USE_INTERVAL_MS, 10)
            if not self.r_next_charge:
                self.r_next_charge = now + self.skill_cooldown(int(self.skills[331221]["iCoolTime"]))
            packets.extend((scene(skills=(self._skill_event(331221, start, start, self.id),)),
                            self._cooldown(10)))
            any_damage=False
            for victim in list(self.arena.actors.values()):
                if not (victim.alive and victim.camp!=self.camp and victim.is_area_targetable()
                        and math.dist(start,victim.position_at(now))<=int(self.effects[331221]['iRange1'])):
                    continue
                hit_packets, damaged = self.damage(self.combat_stat('iAttack',now)*D(self.effects[331221]['fAddVal']), now,target=victim)
                packets.extend(hit_packets)
                any_damage |= damaged
                if victim.alive:
                    packets.extend(self._buff(331222, now, victim.id))
            if any_damage:
                self.cooldowns[1] = max(now,self.cooldowns[1]-1000) if self.cooldowns[1]>now else self.cooldowns[1]
                packets.append(self._cooldown(1))
                packets.extend(self._buff(331224,now))
        elif slot == 2:
            self.cooldowns[2] = now + self.skill_cooldown(int(self.skills[331301]["iCoolTime"]), 2)
            packets.extend((scene(skills=(self._skill_event(331301, start, dest, target),)), self._cooldown(2)))
            packets.extend(self._buff(331304, now))
            packets.extend(self._space_hit(start, now,victim))
        return packets
