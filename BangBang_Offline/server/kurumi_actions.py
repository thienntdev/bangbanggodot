"""Kurumi: cast-counted E, snapshot clones and launch-time bullet slowing."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import point_at, rect_contact
from combat_math import D, quantize
from combat_protocol import props, scene
from hulu_actions import HuluTurret
from melee_common import aimed, enemies, in_strip, prepare_displacement

SLOTS = {0:370100, 1:370201, 2:370301, 10:370401}


class KurumiActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.ready = None
        self.combo_count = self.combo_until = 0

    def _basic(self, now):
        if self.has_buff(370207, now): return 370220
        if self.has_buff(370203, now): return 370210
        if self.has_buff(370204, now): return 370211
        return 370100

    def _cooldown(self, slot, changed=False):
        skill = self._basic(self.clock()) if slot == 0 else SLOTS[slot]
        return (1579 if changed and self.id==1 else 1572), props(skill, slot, -1, self.cooldowns[slot])+struct.pack('<I', self.id)

    def on_spawn(self, now):
        self.ready = None
        self.combo_count = self.combo_until = 0
        return [self._cooldown(0, True)]

    def remove_buff(self, template, now, *, expired=False):
        active = self.has_buff(template, now) or (self.id, template) in self.active_buffs
        packets = super().remove_buff(template, now, expired=expired)
        if active and template in (370203,370207) and not self.info.get('npc_template'):
            packets.append(self._cooldown(0, True))
        return packets

    def _speed(self, now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self, action, now):
        return bool(self.ready) or super().blocked(action, now)

    def interrupt(self, now):
        packets = []
        if self.ready:
            self.ready = None
            packets.append((1583, struct.pack('<II', self.id, 370301)))
        return packets+self.sync_speed(now)

    def on_control(self, source, template, now):
        kind = int(table_row('BuffTemplate_table.xml', nBuffId=template)['nEffectType'])
        return self.interrupt(now) if self.ready and kind in (30,35,66) else []

    def _refund(self, now, generation):
        if not self.alive or self.generation != generation or self.cooldowns[1] <= now:
            return []
        self.cooldowns[1] = max(now, self.cooldowns[1]-500)
        return [self._cooldown(1)]

    def on_bullet_hit(self, flight, target, now):
        return self._refund(now, flight['source_generation']) if flight['template'] == 370100 else []

    def _beam(self, start, dest, now, template):
        end = aimed(start, dest, 600, fixed=True)
        wall = rect_contact(start, end, self.arena.water_rects(now))
        if wall is not None:
            end = tuple(round(v) for v in point_at(start, end, max(0, wall-.001)))
        packets = [scene(skills=(self._skill_event(template, start, end),))]
        power = self.combat_stat('iAttack', now)
        generation = self.generation
        hit = False
        for target in enemies(self,area=True):
            pos = target.position_at(now)
            if not in_strip(pos, start, end, math.dist(start, end), 48): continue
            packets.extend(self.damage(power*D('2.25')*(2 if template==370220 else 1), now,
                                       target=target, basic=True,critical_display=template==370220)[0])
            packets.extend(self._refund(now, generation))
            if template == 370220:
                packets.extend(self._buff(370221, now, target.id))
            hit = True
        # Every beam is one E success, even if several vehicles are hit.
        if hit and self.alive and self.generation == generation and template != 370211:
            if template == 370220:
                packets.extend(self.restore_hp(power*D('2.09'), now))
            else:
                self.combo_count = min(2, (self.combo_count if now < self.combo_until else 0)+1)
                self.combo_until = now+10000
                packets.extend(self.remove_buff(370205, now)+self.remove_buff(370206, now))
                packets.extend(self._buff(370204+self.combo_count, now))
        for buff in (370203,370204,370207,370209,370231):
            packets.extend(self.remove_buff(buff, now))
        return packets

    def _flight(self, flight, now):
        if flight['template'] != 370301:
            return super()._flight(flight, now)
        if now < flight['finish']:
            flight['previous'] = now
            self._queue(min(now+20, flight['finish']), 'flight', flight)
            return []
        pos = flight['end']
        ident, packet = self.add_object(370301, pos)
        visual, visual_packet = self.add_object(370307, pos)
        self._queue(now+3000, 'kurumi_visual_remove', visual)
        self._queue(now, 'kurumi_field', dict(id=ident, pos=pos, end=now+3000))
        packets = [scene(blown_bullets=(struct.pack('<I', flight['id']),)), packet, visual_packet]
        for target in enemies(self,area=True):
            if math.dist(pos, target.position_at(now)) <= 192:
                packets.extend(self._buff(370306, now, target.id))
        return packets

    def _event(self, now, kind, data):
        if kind == 'kurumi_visual_remove':
            # Visual prop370307 supplies the native field-disappearance movie;
            # gameplay field370301 expires through its existing callback.
            return self.remove_object(data[0],destroyed=True)
        if kind == 'kurumi_ready':
            cast, = data
            if self.ready is not cast or not self.alive: return []
            self.ready = None
            return self.shoot(370301, self.position_at(now), cast['dest'], now, 0,
                              school='physical', through_walls=True, fixed_destination=True)+self.sync_speed(now)
        if kind == 'kurumi_field':
            cast, = data
            if now >= cast['end']: return self.remove_object(cast['id'])
            packets = []
            for target in enemies(self,area=True):
                if math.dist(cast['pos'], target.position_at(now)) <= 192:
                    for buff in (370302,370303,370304,370308):
                        packets.extend(self._buff(buff, now, target.id))
            self._queue(min(now+150, cast['end']), kind, cast)
            return packets
        if kind == 'kurumi_spawn':
            cast, = data
            pos = self.arena.free_position(cast['pos'], now)
            if pos is None: return []
            info = dict(acct_id=self.info['acct_id'], tank_level=self.info['tank_level'], tank_id=10000095,
                        npc_template=370402, owner=self.id, source_generation=cast['generation'],
                        name=self.info['name'], in_room=True, summon_stats=cast['stats'], summon_hp=str(cast['hp']))
            clone = KurumiClone(self.arena, self._new_id(5), info, self.camp, pos)
            self.arena.actors[clone.id] = clone
            return [clone.snapshot(now)]+clone.on_spawn(now)
        return super()._event(now, kind, data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or not self.alive or self.blocked('attack', now) or self.skill_sealed(slot, now) or self.cooldowns[slot] > now:
            return []
        if not self._inside(dest) or slot in (0,1) and start == dest: return []
        if slot == 2 and math.dist(start, dest) > 600: return []
        if slot == 10 and (math.dist(start, dest) > 336 or self.arena.geometry.clamp_tank_position(dest) != dest
                          or self.arena.geometry.wall_contact(dest,dest,36-.001) is not None
                          or rect_contact(dest,dest,self.arena.water_rects(now),36-.001) is not None): return []
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:30000,10:8000}[slot], slot)
        if slot == 0:
            template = self._basic(now)
            packets = self._beam(start,dest,now,template) if template != 370100 else self.shoot(
                template,start,dest,now,self.combat_stat('iAttack',now)*D('1.5'),school='physical',basic=True,speed_multiplier=1.5)
            return packets+[self._cooldown(0)]
        if slot == 1:
            intended=aimed(start,dest,300)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            body=body if stopped else start
            packets = []
            for buff in (370203,370207,370209): packets.extend(self.remove_buff(buff,now))
            third = self.combo_count >= 2 and self.combo_until > now
            if third:
                self.combo_count = self.combo_until = 0
                packets.extend(self.remove_buff(370205,now)+self.remove_buff(370206,now)+self._buff(370209,now))
            packets.extend(self._buff(370207 if third else 370203,now)+self._buff(370202,now)+self._buff(370231,now))
            self._set_motion(body,intended,960,now,4)
            self.forced_until = self.motion[3]
            packets.extend(stopped)
            packets.append(scene(moves=(self._move_event(self.motion[1],960,4),)))
            for clone in self.arena.actors.values():
                if clone.alive and clone.info.get('npc_template')==370402 and clone.info['owner']==self.id and clone.info['source_generation']==self.generation:
                    packets.extend(self._buff(370204,now,clone.id))
            return packets+[self._cooldown(0,True),self._cooldown(1)]
        if slot == 10:
            stats = dict(self.stats)
            for key in ('iAttack','iEgAtk','iArmor','iEgArmor','iCentesis','iEgCtsis'):
                stats[key] = str(self.combat_stat(key,now)*(D('.5') if key in ('iAttack','iEgAtk') else 1))
            stats.update(iHp=str(self.max_hp),iSpeed='150',iFireInterv='1000',nFireRange='432')
            self._queue(now+500,'kurumi_spawn',dict(pos=dest,stats=stats,hp=self.hp,generation=self.generation))
            # This slot declares iChargeEffectId only; EffectLayer requires
            # m_isReady=1 to play it, despite R having no cast-time lock.
            packets = [scene(skills=(self._skill_event(370401,start,dest,ready=1),)),self._cooldown(10)]
            for template,duration in ((370401,1300),(370403,500)):
                ident,packet = self.add_object(template,dest);packets.append(packet)
                self._queue(now+duration,'object_expire',ident)
            return packets
        self.ready = dict(slot=2,skill=370301,dest=dest)
        _,stopped = prepare_displacement(self,now,interrupt=False)
        self.position,self.motion = self.position_at(now),None
        self._queue(now+50,'kurumi_ready',self.ready)
        ident,packet = self.add_object(370305,dest)
        self._queue(now+1000,'object_expire',ident)
        return [packet,scene(skills=(self._skill_event(370301,start,dest,ready=1),)),self._cooldown(2)]+self.sync_speed(now)+stopped


class KurumiClone(KurumiActions):
    taunt_mobile=True
    _respawn = HuluTurret._respawn

    def __init__(self, *args):
        super().__init__(*args)
        self.stats = dict(self.info['summon_stats'])
        self.max_hp = D(self.stats['iHp'])
        self.hp = min(self.max_hp,D(self.info['summon_hp']))
        self.info.update(hp=math.ceil(self.hp),max_hp=math.ceil(self.max_hp))
        self.cooldowns = {}
        self.passive_ready_at = 0

    def snapshot(self,now):
        body = struct.pack('<IIhhiBiIiH',self.id,370402,*self.position_at(now),math.ceil(self.hp),self.camp,
                           math.ceil(self.max_hp),self.info['owner'],math.ceil(sum(s.remaining for s in self.shields if s.expires_ms>now)),0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def sync_speed(self,now): return []

    def on_spawn(self,now):
        self._queue(now+8000,'kurumi_clone_end')
        self._queue(now+100,'kurumi_ai')
        return self._buff(370404,now)

    def _refund(self,now,generation):
        owner = self.arena.actors.get(self.info['owner'])
        return owner._refund(now,self.info['source_generation']) if owner else []

    def limit_hit(self,key,amount,now):
        return quantize(amount*2)  # Q68 incoming x2, including true damage, before shields.

    def commit_hp(self,hp,now,*,critical=False):
        before = self.alive
        packets = super().commit_hp(hp,now,critical=critical)
        if before and not self.alive:
            pos = self.position_at(now)
            # EffectLayer looks up the live caster. Present the explosion
            # BEFORE HP0/removal, or the original client drops its animation.
            packets.insert(0,scene(skills=(self._skill_event(370411,pos,pos),)))
            self._queue(now,'kurumi_clone_explode',pos,self.combat_stat('iAttack',now))
            packets.append(scene(removed=(struct.pack('<I',self.id),)))
        return packets

    def taunt_attack(self,target,now):
        pos=self.position_at(now);dest=target.position_at(now)
        if (not self.alive or not target.alive or target.is_untargetable() or self.blocked('attack',now)
                or self.skill_sealed(0,now) or now<self.passive_ready_at or math.dist(pos,dest)>432):return []
        self.passive_ready_at=now+self.fire_interval(now)
        if self._basic(now)==370211:return self._beam(pos,dest,now,370211)
        return self.shoot(370100,pos,dest,now,self.combat_stat('iAttack',now)*D('1.5'),school='physical',basic=True,speed_multiplier=1.5) if pos!=dest else []

    def _event(self,now,kind,data):
        if kind == 'kurumi_clone_end':
            return self.commit_hp(D(0),now) if self.alive else []
        if kind == 'kurumi_clone_explode':
            pos,power = data
            packets = []
            for target in enemies(self,area=True):
                if math.dist(pos,target.position_at(now)) <= 144:
                    packets.extend(self.damage(power*D('2.07'),now,target=target)[0])
            return packets
        if kind == 'kurumi_ai':
            if not self.alive: return []
            self._queue(now+100,kind)
            pos = self.position_at(now)
            from bot_ai import observable,team_visible
            candidates = [a for a in enemies(self) if math.dist(pos,a.position_at(now)) <= 960
                          and (observable(self.arena,self,a,now) or team_visible(self.arena,self,a,now))]
            packets = []
            target = min(candidates,key=lambda a:(math.dist(pos,a.position_at(now)),a.id)) if candidates else None
            if target and math.dist(pos,target.position_at(now)) > 432:
                if not self.blocked('move',now) and self._speed(now)>0:
                    self._set_motion(pos,aimed(pos,target.position_at(now),math.dist(pos,target.position_at(now))-432),self._speed(now),now,3)
                    packets.append(scene(moves=(self._move_event(self.motion[1],self._speed(now),3),)))
            elif self.motion and now >= self.forced_until:
                self.position,self.motion = pos,None
                packets.append(scene(moves=(self._move_event(pos,0,5),)))
            if target and math.dist(pos,target.position_at(now)) <= 432 and not self.blocked('attack',now) and not self.skill_sealed(0,now) and now >= self.passive_ready_at:
                packets.extend(self.taunt_attack(target,now))
            return packets
        return super()._event(now,kind,data)
