"""Reviewed chapter-one NPCs; all damage/control use TankActions."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import point_at, rect_contact
from combat_math import D
from combat_protocol import scene
from melee_common import in_strip


class PveNpc(TankActions):
    def __init__(self, arena, ident, info, camp, spawn):
        row = table_row('AINpcTemplate_table.xml', nTemplateId=info['npc_template'])
        arms = table_row('AINpcArmsTemplate_table.xml', nTemplateId=int(row['nArmsId']))
        info.update(pve_npc=True, tank_id=10000019, tank_level=1, acct_id=0,
                    name=row['szName'], in_room=True)
        super().__init__(arena, ident, info, camp, spawn)
        # Keep player/PvP formulas untouched. New runs use the frozen map
        # quality; an old in-progress save keeps its legacy role-only rows.
        from pve_balance import armor_constant, enemy_multiplier, npc_stats
        self.stats.update(npc_stats(arena, info['npc_template'], camp=camp))
        self.pve_armor_constant = armor_constant(arena, info['npc_template'])
        self.pve_damage_multiplier = enemy_multiplier(
            arena, info['npc_template'], 'enemy_damage_multiplier', camp=camp)
        self.stats.update(iSpeed=arms.get('iSpeed') or '0', iFireInterv=arms.get('iFireInterv') or '1000',
                          nFireRange='360' if arms.get('nSkillId')=='1000009' else arms.get('iFireRange') or '0', iMp='0')
        if info['npc_template'] in (265,266,409,414,415,612,613):
            self.info.update(pve_hostage=True,damage_immune=True)
            self.stats['iHp']='1'
        self.info['pve_flying']=info['npc_template'] in (260,626,633,413)
        self.info['pve_stationary']=info['npc_template'] in (224,265,409,414,415,605,610,612,613,632,410,411,419,420)
        from pve_catalog import CHAPTER3
        if arena.geometry.id in CHAPTER3:
            if info['npc_template'] in (1409,1414,353,342):
                self.info.update(pve_hostage=True,damage_immune=True)
                self.stats['iHp']='1'
            self.info['pve_flying']=info['npc_template'] in (311,312,313,1436)
            self.info['pve_stationary']=int(arms.get('iSpeed') or 0)<=0 or bool(self.info.get('pve_hostage'))
        from pve_support import MAPS as SUPPORT_MAPS
        if arena.geometry.id in SUPPORT_MAPS:
            if info['npc_template'] in (1350,1351,1353,2612,2613,2673,2676):
                self.info.update(pve_hostage=True,damage_immune=True)
                self.stats['iHp']='1'
            self.info['pve_trap']=info['npc_template'] in (1350,1351,2612,2613,2673,2676)
            self.info['pve_flying']=info['npc_template'] in (1331,2635,2609,2610)
            self.info['pve_stationary']=int(arms.get('iSpeed') or 0)<=0 or info['npc_template'] in (1353,2612,2613)
        from pve_catalog import CHAPTER5, CHAPTER6, CHAPTER7, CHAPTER8, CHAPTER9
        if arena.geometry.id in CHAPTER5 + CHAPTER6 + CHAPTER7 + CHAPTER8 + CHAPTER9:
            if D(arms['fHpCoef'])<0:
                self.info.update(pve_hostage=True,damage_immune=True)
                self.stats['iHp']='1'
            self.info['pve_trap']=info['npc_template'] in (517,518,519,520,524,525,526,567)
            self.info['pve_stationary']=int(arms.get('iSpeed') or 0)<=0 or info['npc_template']==522
        if arena.geometry.id in CHAPTER6:
            tpl = info['npc_template']
            self.info['pve_trap'] = tpl in (718,719,720,721,3110112)
            self.info['pve_stationary'] = int(arms.get('iSpeed') or 0)<=0 or tpl in (717,3110113)
            self.info['pve_flying'] = tpl == 716
        if arena.geometry.id in CHAPTER7:
            self.info['pve_trap']=info['npc_template'] in (3130108,3130210,3130211)
        if arena.geometry.id in CHAPTER8 + CHAPTER9:
            from pve_chapter8_9 import DECOR
            self.info['pve_trap']=info['npc_template'] in DECOR
        self.hp = self.max_hp = D(self.stats['iHp'])
        self.info.update(hp=int(self.hp), max_hp=int(self.hp))
        self.last_speed = int(self.stats['iSpeed'])
        self.cooldowns = {0: 0}
        self.shot_skill = {261:304100,263:363100,264:301100}.get(info['npc_template'],int(arms.get('nSkillId') or 0))
        shot=table_row('SkillTemplate_table.xml',nId=self.shot_skill) if self.shot_skill else {}
        self.pve_fire_range=min(int(self.stats['nFireRange']),int(shot.get('iRange') or 0))
        # Suicide weapon1000034 has an arms trigger range but no skill iRange.
        # Its explosion executor owns the damage radius; zeroing the trigger
        # here makes the NPC chase indefinitely without ever using that weapon.
        if self.shot_skill in (1000034,1000088,1000103,1000105,1000117,1000118,1000119,1000123,1000128,1000133,1000151,1000122):
            self.pve_fire_range=int(arms.get('iFireRange') or 0)
        if arena.geometry.id in CHAPTER5 and self.shot_skill==1000040:self.pve_fire_range=96
        if arena.geometry.id in CHAPTER5 and info['npc_template'] in (502,552):self.pve_fire_range=100
        if self.shot_skill in (1000054,1000057,1000060,1000061):
            self.pve_fire_range={1000054:480,1000057:216,1000060:600,1000061:600}[self.shot_skill]
        self.pve_count=int(arms.get('iFireCount') or '1')
        self.pve_break=int(arms.get('iFireBreak') or '0')
        self.pve_scatter=arms.get('iBuffId1')=='30107'
        self.route_point = info['point']
        self.route_previous = None
        self.route_queue = []
        from pve_bosses import configure
        configure(self)

    def interrupt(self, now):
        from pve_bosses import interrupt
        from pve_dooku import interrupt as dooku_interrupt
        return super().interrupt(now) + interrupt(self, now) + dooku_interrupt(self, now)

    def snapshot(self, now):
        body = struct.pack('<IIhhiBiIiH', self.id, self.info['npc_template'], *self.position_at(now),
                           math.ceil(self.hp), self.camp, math.ceil(self.max_hp), 0, 0, 0)
        return 1556, struct.pack('<I', self.scene_id) + body

    def sync_speed(self, now): return []

    @property
    def taunt_mobile(self):
        return (not self.info.get('pve_hostage') and not self.info.get('pve_stationary')
                and int(self.stats['iSpeed']) > 0)

    def taunt_attack(self, target, now):
        # Keep the NPC's own weapon/cadence; support-only NPCs gain no attack.
        if (not self.shot_skill or self.shot_skill in (1000057,1000060,1000061,50332)
                or self.info.get('pve_hostage') or not target.alive or target.is_untargetable()
                or self.skill_sealed(0,now)
                or math.dist(self.position_at(now),target.position_at(now))>self.pve_fire_range):
            return []
        return self.cast(0,self.position_at(now),target.position_at(now),target.id,now)

    def commit_hp(self, hp, now, *, critical=False):
        if self.info.get('pve_hostage'):return []
        alive = self.alive
        if (alive and hp<=0 and self.shot_skill==1000062 and self.info['npc_template'] not in (502,552)
                and not getattr(self,'pve_exploded',False)):
            from pve_support import explode
            return explode(self,now)
        packets = super().commit_hp(hp, now, critical=critical)
        if alive and not self.alive:
            packets.append(scene(removed=(struct.pack('<I', self.id),)))
        return packets

    def attr_bonus(self,attributes,now):
        value=super().attr_bonus(attributes,now)
        # This NPC buff stores a flat value; generic tank buffs are percentages.
        if 4 in attributes and self.has_buff(252,now):value-=100
        return value

    def combat_stat(self,key,now):
        value=super().combat_stat(key,now)
        if key=='iAttack' and self.has_buff(252,now):
            from guild_combat import weaken_factor
            value+=D(100)*weaken_factor(self,(1,4),now)
        return value

    def damage_immune(self,school,now,periodic=False):
        return self.has_buff(251,now) or self.has_buff(50350,now) or super().damage_immune(school,now,periodic)

    def damage_bonus(self, target):
        # One shared source multiplier covers flat/percent/DoT/boss attacks.
        # TankActions preserves already-resolved amounts after this formula,
        # so transferred/deferred damage is never amplified twice.
        return super().damage_bonus(target) * self.pve_damage_multiplier

    def cc_immune(self,now,*,slow=False):
        return self.info.get('pve_hostage',False) or super().cc_immune(now,slow=slow)

    def reject_buff(self,row,source,now):
        return self.info.get('pve_hostage',False) or super().reject_buff(row,source,now)

    def fly(self,dest,now):
        if self.motion and self.motion[3]>now or self._speed(now)<=0:return []
        from battle_runtime import DIRECTIONS
        start=self.position_at(now);dest=self.arena.geometry.clamp_tank_position(dest)
        _,direction,end=min((math.dist((start[0]+24*dx,start[1]+24*dy),dest),i,
                             (start[0]+24*dx,start[1]+24*dy)) for i,(dx,dy) in enumerate(DIRECTIONS[:8]))
        duration=max(1,round(math.dist(start,end)*1000/self._speed(now)))
        self.position,self.motion=end,(start,end,now,now+duration);self.motion_kind=0
        return [scene(moves=(struct.pack('<IhhhBB',self.id,*start,self._speed(now),direction,0),))]

    def _shot(self, dest, now, target=None):
        if self.arena.geometry.id!=201:
            from pve_shots import shot
            return shot(self,dest,now,target)
        start = self.position_at(now)
        if start == dest: return []
        if self.info['npc_template'] != 1115:
            return self.shoot(self.shot_skill, start, dest, now, self.combat_stat('iAttack', now),
                              school='physical', basic=True)
        end = tuple(round(v) for v in point_at(start, dest, 360 / math.dist(start, dest)))
        wall = self.arena.geometry.wall_contact(start, end)
        water = rect_contact(start, end, self.arena.water_rects(now))
        fraction = min((v for v in (wall, water) if v is not None), default=1.)
        end = tuple(round(v) for v in point_at(start, end, fraction))
        ident = self._new_id(2)
        # See pve_shots.shot: an instantaneous native laser is the source
        # BLOW movie, not an invisible projectile removed on the next tick.
        packets = [scene(fires=(struct.pack('<IIhhhhhI', ident, self.id, *start, *end, 32767, self.shot_skill),),
                         blown_bullets=(struct.pack('<I', ident),))]
        for target in list(self.arena.actors.values()):
            if (target.alive and target.camp != self.camp and target.is_area_targetable()
                    and in_strip(target.position_at(now), start, end, math.dist(start, end), 24)
                    and self.arena.geometry.wall_contact(start, target.position_at(now),
                          exclude=(target.map_rect,) if hasattr(target, 'map_rect') else ()) is None
                    and not self.projectile_blocked(target, now)):
                packets += self.damage(self.combat_stat('iEgAtk', now), now, target=target,
                                       school='energy', basic=True)[0]
        return packets

    def cast(self, slot, start, dest, target, now):
        if self.info.get('pve_hostage') or not self.shot_skill:return []
        if (slot or not self.alive or self.blocked('attack', now) or self.skill_sealed(0,now)
                or self.cooldowns[0] > now or start == dest and self.shot_skill != 1000034):
            return []
        if self.shot_skill in (1000057,1000060,1000061):
            from pve_support import cast_support
            return cast_support(self,now)
        self.cooldowns[0] = now + (4000 if self.info['npc_template'] == 1120 else self.fire_interval(now))
        if self.info['npc_template'] == 1120:
            for offset in (1000, 2000):
                self._queue(now+offset, 'pve_burst', self.generation, target)
        elif self.arena.geometry.id!=201:
            # Full pause after the final shot, matching the approved201 burst.
            self.cooldowns[0]=now+(self.pve_count-1)*self.pve_break+self.fire_interval(now)
            for i in range(1,self.pve_count):
                self._queue(now+i*self.pve_break,'pve_burst',self.generation,target)
        return self._shot(dest, now, self.arena.actors.get(target))

    def _flight(self,flight,now):
        if flight.get('pve_transport'):
            from pve_transport_traps import flight_step
            return flight_step(self,flight,now)
        if flight.get('pve_lob'):
            from pve_shots import lob
            return lob(self,flight,now)
        if flight.get('target') and flight['template'] in (1000015,1000025,1000026):
            from map_objects import missile_target_present
            target=self.arena.actors.get(flight['target'])
            if target is None or target.generation!=flight['target_generation'] or not missile_target_present(target,now):
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['finish']=now+480
        return super()._flight(flight,now)

    def projectile_targetable(self,flight,target,now):
        if flight.get('target') and flight['template'] in (1000015,1000025,1000026):
            from map_objects import missile_target_present
            return missile_target_present(target,now)
        return super().projectile_targetable(flight,target,now)

    def on_bullet_hit(self,flight,target,now):
        from pve_shots import on_hit
        return on_hit(self,flight,target,now)

    def _event(self, now, kind, data):
        if kind == 'pve_boss_ray':
            from pve_bosses import event
            return event(self, now, kind, data)
        if kind in ('pve_bio_poison','pve_plague'):
            from pve_bio import event
            return event(self,now,kind,data)
        if kind=='pve_fixed_laser':
            generation,dest=data
            return self._shot(dest,now) if self.alive and self.generation==generation and not self.arena.pk['finished'] else []
        if kind=='pve_poison_tick':
            from pve_shots import poison_tick
            return poison_tick(self,now,data)
        if kind.startswith(('pve_support_','pve_signal_','pve_flame_')):
            from pve_support import event
            result=event(self,now,kind,data)
            if result is not None:return result
        if kind=='pve_radiation':
            from pve_shots import radiation
            return radiation(self,data[0],now)
        if kind == 'pve_laser_end':
            return [scene(expired_bullets=(struct.pack('<I', data[0]),))]
        if kind == 'pve_burst':
            generation, target_id = data
            from bot_ai import observable
            target = self.arena.actors.get(target_id)
            prior = getattr(self.arena,'forced_basic_actor',None)
            if self.has_buff(314303,now) and self.buff_sources.get(314303)==target_id:
                self.arena.forced_basic_actor=self.id
            try:
                if (generation != self.generation or not self.alive or self.blocked('attack', now)
                        or self.skill_sealed(0,now) or not target
                        or not observable(self.arena,self,target,now,int(self.stats['nFireRange']))):
                    return []
                return self._shot(target.position_at(now),now,target)
            finally:
                self.arena.forced_basic_actor=prior
        return super()._event(now, kind, data)
