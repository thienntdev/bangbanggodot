"""Assassin: Space roll/recast stab, stealth and caster-owned marks."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene, stop_move
from melee_common import prepare_displacement

SLOTS = {0:322100, 1:322201, 2:322301, 10:322401}


class AssassinActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.space_count,self.space_next_charge = 3,0
        self.ready = self.dash = None
        self.marks = {}

    def _cooldown(self, slot, changed=False):
        recast = slot==2 and self.has_buff(322302,self.clock())
        body = (props(322311,slot) if recast else
                props(SLOTS[slot],slot,self.space_count if slot==2 else -1,self.cooldowns[slot],
                      self.space_next_charge if slot==2 else 0))
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _basic_slot(self):
        return [self._cooldown(0,True),self._cooldown(0)]

    def _space_slot(self):
        return [self._cooldown(2,True),self._cooldown(2)]

    def _stab_target(self, start, cursor, now):
        from bot_ai import team_visible
        candidates=[]
        for actor in self.arena.actors.values():
            if (actor.camp not in (1,2) or actor.camp==self.camp or not actor.alive
                    or actor.info.get('npc_template') or actor.is_untargetable()):continue
            types=actor.buff_types(now)
            if 26 in types and 32 not in types or not team_visible(self.arena,self,actor,now):continue
            distance=math.dist(start,actor.position_at(now))
            if 0<distance<=300:candidates.append((actor,distance,math.dist(cursor,actor.position_at(now))))
        near=[row for row in candidates if row[2]<=72]
        if near:return min(near,key=lambda row:(row[2],row[1],row[0].id))[0]
        return min(candidates,key=lambda row:(row[0].hp/row[0].max_hp,row[1],row[0].id))[0] if candidates else None

    def _isolated(self, now):
        return not any(a.id!=self.id and a.alive and a.camp==self.camp and not a.info.get('map_object')
                       and math.dist(self.position_at(now),a.position_at(now))<=300
                       for a in self.arena.actors.values())

    def attr_bonus(self, attributes, now):
        value = super().attr_bonus(attributes,now)
        # This conditional buff means damage, not AP/EN or healing strength.
        return value-D('.25') if 1 in attributes and self.has_buff(322101,now) else value

    def _visibility(self, now):
        types = self.buff_types(now)
        self.info['untargetable'] = 26 in types and 32 not in types

    def _speed(self, now):
        value = super()._speed(now)
        if self.has_buff(322113,now) and self.has_buff(322203,now):
            value -= round(int(self.stats['iSpeed'])*.25)
        return max(0,value)

    def on_spawn(self, now):
        packets = []
        for template in (322102,322103):
            packets.extend(self._buff(template,now))
        self._visibility(now)
        return packets+self._basic_slot()+self._space_slot()

    def update(self, now):
        packets = []
        if self.dash is not None and self.motion is None:
            # Root stops movement without interrupting attacks. Also recover
            # old checkpoints saved after the failed dash event was popped.
            packets.extend(self._end_dash(now))
        isolated = self.alive and self._isolated(now)
        if isolated and not self.has_buff(322101,now):
            packets.extend(self._buff(322101,now))
        elif not isolated and self.has_buff(322101,now):
            packets.extend(self.remove_buff(322101,now))
        self._visibility(now)
        if self.space_next_charge and now>=self.space_next_charge:
            while self.space_count<3 and now>=self.space_next_charge:
                self.space_count += 1
                self.space_next_charge += self.skill_cooldown(6000)
            if self.space_count==3:
                self.space_next_charge = 0
            packets.append(self._cooldown(2))
        return packets+super().update(now)

    def remove_buff(self, template, now, *, expired=False):
        existed = (self.id,template) in self.active_buffs
        packets = super().remove_buff(template,now,expired=expired)
        if template==322201 and existed:
            for other in (322202,322203,322204):
                packets.extend(super().remove_buff(other,now))
            if self.alive:
                for other in (322211,322212,322213,322214):
                    packets.extend(self._buff(other,now,duration=3000))
        if template==322302 and existed:
            packets.extend(self._space_slot())
        if template in (322201,322202,322303):
            self._visibility(now)
        return packets

    def _reveal(self, now):
        return self.remove_buff(322201,now)+self.remove_buff(322303,now)

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None or self.dash is not None

    def _end_dash(self, now):
        pos = self.position_at(now)
        if self.dash:
            pos = self.move_destination(self.dash.get('start',pos),pos)
        self.position,self.motion,self.forced_until = pos,None,now
        self.dash = None
        # Stop the client tween while auto-move still blocks held-key retries.
        packets = [stop_move(self.scene_id,self.id,self.position)]
        for template in (322311,322312,322341,50353):
            packets.extend(self.remove_buff(template,now))
        return packets+self.sync_speed(now)

    def interrupt(self, now):
        packets = self._end_dash(now) if self.dash else []
        if self.ready:
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,322401)))
        if not self.alive:
            self.info['untargetable'] = False
        return packets

    def on_target_death(self, target, now):
        self.marks.pop(target.id,None)
        return []

    def _deal(self, raw, target, now, generation, *, basic=False, school='physical', multiplier=None, critical_handled=False):
        multiplier = (D('1.25') if self._isolated(now) else D(1)) if multiplier is None else multiplier
        was_alive = target.alive
        packets,_ = self.damage(raw*multiplier,now,target=target,basic=basic,school=school,
                                critical_handled=critical_handled,critical_display=critical_handled)
        if self.arena.pk and self.arena.pk['finished']:
            return packets
        if was_alive and not target.alive and self.alive and generation==self.generation:
            self.cooldowns[1] = self.cooldowns[10] = 0
            packets.extend((self._cooldown(1),self._cooldown(10)))
            packets.extend(self._buff(322113,now))
        return packets

    def _mark(self, target, power, generation, now):
        if not target.alive or target.reject_buff({'nEffectType':'201'},self,now):
            return []
        packets = []
        for template in (322402,322403,322404,322405,322406,322407,322409):
            packets.extend(self._buff(template,now,target.id))
        if not target.has_buff(322404,now) or target.buff_sources.get(322404)!=self.id:return packets
        mark = dict(target_generation=target.generation,source_generation=generation,power=power,
                    version=target.buff_versions[322404],end=now+3000,first=True,
                    multiplier=D('1.25') if self._isolated(now) else D(1))
        self.marks[target.id] = mark
        self._queue(now+3000,'assassin_mark_end',target.id,mark)
        return packets

    def _own_mark(self, target, now):
        mark = self.marks.get(target.id)
        return mark if (mark and mark['end']>now and mark['target_generation']==target.generation
                        and target.has_buff(322404,now) and target.buff_versions[322404]==mark['version']) else None

    def _basic_hit(self, target, power, generation, now, *, stab=False, critical=False):
        mark = self._own_mark(target,now)
        ratio = D('1.8') if stab else D(1)
        amp = D('.25') if mark else D(0)
        if stab and target.has_buff(322322,now) and target.buff_sources.get(322322)==self.id:
            amp += D('.25')*target.buff_stacks[322322]
        raw = power*ratio*(1+amp)*(D('1.5') if critical else 1)
        packets = self._deal(raw,target,now,generation,basic=True,critical_handled=critical)
        if self.arena.pk and self.arena.pk['finished']:
            return packets
        if mark and mark['first'] and generation==mark['source_generation']==self.generation and self.alive:
            mark['first'] = False
            packets.extend(self.restore_hp(power*D('1.5'),now))
            packets.extend(self._buff(322422,now))
            packets.extend(self._buff(322431,now,target.id))
        if stab:
            packets.extend(self._buff(322322,now,target.id))
            packets.extend(self._buff(322323,now,target.id))
            packets.append(scene(skills=(self._skill_event(322321,self.position_at(now),target.position_at(now),target.id),)))
        return packets

    def _flight(self, flight, now):
        start = point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        contacts = []
        for target in self.arena.actors.values():
            if target.alive and target.camp!=self.camp and (target.id,target.generation) not in flight['hits']:
                hit = actor_contact(start,end,target,flight['previous'],now)
                if hit is not None:
                    contacts.append((hit,target.id))
        wall = self.arena.geometry.wall_contact(start,end) if flight['template']==322100 else None
        packets = []
        for contact,ident in sorted(contacts):
            if wall is not None and contact>=wall:
                break
            target = self.arena.actors[ident]
            flight['hits'].add((ident,target.generation))
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            if flight['template']==322100:
                packets.extend(self._basic_hit(target,flight['power'],flight['source_generation'],now,critical=flight['proc']))
                return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
            packets.extend(self._deal(flight['raw'],target,now,flight['source_generation']))
            packets.extend(self._mark(target,flight['power'],flight['source_generation'],now))
        if now>=flight['finish'] or wall is not None:
            return packets+[scene(**{('blown_bullets' if wall is not None else 'expired_bullets'):(struct.pack('<I',flight['id']),)})]
        flight['previous'] = now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _start_dash(self, start, dest, now, kind, **data):
        duration = self._set_motion(start,dest,720,now,4 if kind=='roll' else 3)
        self.forced_until = now+duration
        self.dash = dict(kind=kind,start=start,previous=now,generation=self.generation,hits=set(),**data)
        self._queue(now+min(20,duration),'assassin_dash',self.dash)
        # 322311 is a visual face buff, not BUT_AUTO_MOVE. Without the latter,
        # SelfTank continues its held-key walk after each roll/stab tween.
        return self._buff(50353,now)+[stop_move(self.scene_id,self.id,start),
            scene(moves=(self._move_event(self.motion[1],720,self.motion_kind),))]

    def _dash_step(self, dash, now):
        if self.arena.pk and self.arena.pk['finished']:
            self.dash = None
            return []
        if self.dash is not dash or not self.alive or dash['generation']!=self.generation:
            return []
        if self.motion is None:
            return self._end_dash(now)
        start,end = self.position_at(dash['previous']),self.position_at(now)
        packets = []
        touched = False
        if dash['kind']!='roll':
            for target in list(self.arena.actors.values()):
                key = target.id,target.generation
                if target.alive and target.camp!=self.camp and key not in dash['hits']:
                    hit = actor_contact(start,end,target,dash['previous'],now)
                    if hit is not None:
                        dash['hits'].add(key)
                        packets.extend(self._basic_hit(target,dash['power'],dash['generation'],now,stab=True,critical=dash['critical']))
                        if self.arena.pk and self.arena.pk['finished']:
                            # The winning hit freezes motion inside damage().
                            # Preserve its settlement; do not start the pierce.
                            self.dash = None
                            return packets
                        if self.dash is not dash:
                            return packets  # A reflected hit can kill/interrupt the attacker.
                        if self.motion is None:
                            return packets+self._end_dash(now)
                        touched |= target.id==dash['target']
        if dash['kind']=='track':
            target = self.arena.actors[dash['target']]
            if touched or now>=self.motion[3] or not target.alive or target.generation!=dash['target_generation']:
                # User-approved: continue 240 through the target; one hit per life/vehicle.
                direction = self.motion[1]
                if direction==start:
                    direction = dash['aim']
                dest = point_at(start,direction,(math.dist(start,end)+240)/max(1,math.dist(start,direction)))
                dash['kind'] = 'pierce'
                self._set_motion(end,dest,720,now,4)
                dest = self.motion[1]
                self.forced_until = self.motion[3]
                packets.extend(self.remove_buff(322312,now))
                for template in (322332,322341):
                    packets.extend(self._buff(template,now))
                packets.append(scene(moves=(self._move_event(dest,720,4),)))
            elif target.position_at(now)!=self.motion[1]:
                self._set_motion(end,target.position_at(now),720,now,3)
                self.forced_until = self.motion[3]
                packets.append(scene(moves=(self._move_event(self.motion[1],720,3),)))
        elif now>=self.motion[3]:
            return packets+self._end_dash(now)
        dash['previous'] = now
        self._queue(min(now+20,self.motion[3]),'assassin_dash',dash)
        return packets

    def _event(self, now, kind, data):
        if kind=='assassin_dash':
            return self._dash_step(data[0],now)
        if kind=='assassin_warn':
            generation,version = data
            if generation!=self.generation or not self.has_buff(322201,now) or self.buff_versions[322201]!=version:
                return []
            packets = []
            for target in self.arena.actors.values():
                if target.alive and target.camp!=self.camp and math.dist(self.position_at(now),target.position_at(now))<=600:
                    packets.extend(self._buff(305221,now,target.id))
            self._queue(now+1000,'assassin_warn',generation,version)
            return packets
        if kind=='assassin_ready':
            cast, = data
            if self.ready is not cast or not self.alive or cast['generation']!=self.generation:
                return []
            self.ready = None
            return self.shoot(322401,self.position_at(now),cast['dest'],now,cast['power']*D('1.25'),
                              school='physical',power=cast['power'],through_walls=True)
        if kind=='assassin_mark_end':
            ident,mark = data
            target = self.arena.actors[ident]
            if self.marks.get(ident) is not mark:
                return []
            del self.marks[ident]
            if not target.alive or target.generation!=mark['target_generation'] or target.buff_versions.get(322404)!=mark['version']:
                return []
            return self._deal((target.max_hp-target.hp)*D('.2'),target,now,mark['source_generation'],
                              school='true',multiplier=mark['multiplier'])+self._buff(322412,now,target.id)
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        recast = slot==2 and self.has_buff(322302,now)
        if (slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now)
                or not recast and self.cooldowns[slot]>now):
            return []
        if slot==1:
            if self.has_buff(322201,now):
                return []
            self.cooldowns[1] = now+self.skill_cooldown(10000, 1)
            packets = []
            for template in (322201,322202,322203,322204):
                packets.extend(self._buff(template,now))
            self._queue(now+1000,'assassin_warn',self.generation,self.buff_versions[322201])
            self._visibility(now)
            return packets+[self._cooldown(1),scene(skills=(self._skill_event(322201,start,start,self.id),))]
        if recast:
            target = self._stab_target(start,dest,now)
            if target is None:return []
            dest = target.position_at(now)
            packets = self._reveal(now)
            packets.extend(self.remove_buff(322302,now)+self.remove_buff(322307,now))
            packets.extend(self._buff(322312,now))
            packets.append(scene(skills=(self._skill_event(322311,start,dest,target.id),)))
            return packets+self._start_dash(start,dest,now,'track',target=target.id,target_generation=target.generation,
                aim=dest,power=self.combat_stat('iAttack',now),critical=self.has_buff(322212,now))
        if not self._inside(dest) or start==dest:
            return []
        if slot==2 and self.space_count<=0:
            return []
        packets = self._reveal(now) if slot in (0,10) else []
        power = self.combat_stat('iAttack',now)
        if slot==0:
            self.cooldowns[0] = now+self.fire_interval(now)
            return packets+self.shoot(322100,start,dest,now,power,school='physical',basic=True,power=power,
                                      proc=self.has_buff(322212,now))
        if slot==10:
            self.cooldowns[10] = now+self.skill_cooldown(8000, 10)
            self.ready = dict(slot=10,dest=dest,power=power,generation=self.generation)
            self._queue(now+100,'assassin_ready',self.ready)
            origin,stopped = prepare_displacement(self,now,interrupt=False,cancel_motion=True)
            self.position,self.motion = origin if stopped else start,None
            return packets+[self._cooldown(10),scene(skills=(self._skill_event(322401,start,dest,ready=1),))]+stopped
        self.space_count -= 1
        if not self.space_next_charge:
            self.space_next_charge = now+self.skill_cooldown(6000)
        self.cooldowns[2] = now+self.skill_cooldown(1000, 2)
        dest = self.move_destination(start,point_at(start,dest,240/math.dist(start,dest)))
        for template in (322302,322303,322304,322305,322306,322307,322311):
            packets.extend(self._buff(template,now,duration=500 if template==322303 else None))
        self._visibility(now)
        packets.extend(self._space_slot())
        # Original exhibit 104801 contains only a fire sound (no image). The
        # client explicitly accepts that; expire the visual event immediately.
        ident = self._new_id(2)
        packets.append(scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*dest,720,322301),),
                             expired_bullets=(struct.pack('<I',ident),)))
        return packets+self._start_dash(start,dest,now,'roll')
