"""Star Lord: replaceable two-tick burns, mobile sweep and a bounded jump."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene, stop_move

SLOTS = {0:364100, 1:364201, 2:364301, 10:364401}
BURNS = (364102,364105,364106,364107)  # User retained Q42: four stages.
SPACE_BUFFS = (364301,364302,364303,364304,364305)


class StarLordActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.marks = {}
        self.ready = self.jump = self.sweep = None

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self, now):
        return self._buff(364101,now)

    def blocked(self, action, now):
        return (super().blocked(action,now) or self.ready is not None or self.jump is not None
                or action=='attack' and self.sweep is not None)

    def _speed(self, now):
        return 0 if self.ready or self.jump else super()._speed(now)

    def cc_immune(self, now, *, slow=False):
        return self.jump is not None or super().cc_immune(now,slow=slow)

    def on_target_death(self, target, now):
        self.marks.pop(target.id,None)
        return []

    def _end_jump(self, now):
        cast,self.jump = self.jump,None
        if cast is None:
            return []
        self.info['untargetable'] = cast['was_untargetable']
        self.info['damage_immune'] = cast['was_immune']
        self.position,self.motion,self.forced_until = self.position_at(now),None,now
        return self.remove_buff(364409,now)+self.sync_speed(now)

    def _end_sweep(self, now):
        self.sweep = None
        packets = []
        for template in SPACE_BUFFS:
            if (self.id,template) in self.active_buffs:
                packets.extend(self.remove_buff(template,now))
        return packets

    def interrupt(self, now):
        packets = []
        if self.ready:
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,364401)))
        packets.extend(self._end_jump(now))
        # User: CC does not stop the sweep. Death does, while old burns persist.
        if not self.alive:
            packets.extend(self._end_sweep(now))
        return packets+self.sync_speed(now)

    def _damage(self, target, raw, now, generation, *, basic=False, periodic=False):
        was_alive = target.alive
        packets,lost = self.damage(raw,now,target=target,school='energy',basic=basic,periodic=periodic)
        if (was_alive and not target.alive and self.alive and generation==self.generation
                and self.sweep and now<=self.sweep['end']):
            packets.extend(self.restore_hp(self.max_hp*D('.1'),now))
            packets.extend(self._buff(364307,now))
        return packets,lost

    def _valid_mark(self, target, mark, now):
        return (target.alive and target.generation==mark['target_generation']
                and self.marks.get(target.id) is mark and now<mark['end']
                and target.has_buff(mark['template'],now)
                and target.buff_versions.get(mark['template'])==mark['version'])

    def _burn(self, target, power, generation, now):
        if not target.alive or target.reject_buff({'nEffectType':'201'},self,now):
            return []
        old = self.marks.get(target.id)
        valid = old and old['source_generation']==generation and self._valid_mark(target,old,now)
        stacks = old['stacks'] if valid else 0
        next_stack = old['next_stack_at'] if valid else 0
        if now>=next_stack:
            stacks = min(4,stacks+1)
            next_stack = now+500
        packets = []
        for template in BURNS:
            if target.has_buff(template,now) and target.buff_sources.get(template)==self.id:
                packets.extend(target.remove_buff(template,now))
        template = BURNS[stacks-1]
        packets.extend(self._buff(template,now,target.id))
        packets.extend(self._buff(364103,now,target.id,stacks=stacks))
        mark = dict(template=template,stacks=stacks,power=power,end=now+2000,
                    next_stack_at=next_stack,version=target.buff_versions[template],
                    source_generation=generation,target_generation=target.generation)
        self.marks[target.id] = mark
        # A refresh replaces the delayed tick's identity; it never keeps two
        # delayed clocks. The immediate tick bypasses _hit to avoid recursion.
        packets.extend(self._damage(target,power*D('.1')*stacks,now,generation,periodic=True)[0])
        if target.alive:
            self._queue(now+1000,'star_burn',target.id,mark)
            self._queue(now+2000,'star_burn_end',target.id,mark)
        return packets

    def _hit(self, target, raw, power, generation, now, *, basic=False):
        packets,lost = self._damage(target,raw,now,generation,basic=basic)
        if lost:
            packets.extend(self._burn(target,power,generation,now))
        return packets

    def _enemies(self, pos, radius, now):
        return [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                and a.is_area_targetable() and math.dist(pos,a.position_at(now))<=radius]

    def _push(self, target, center, now):
        current = target.position_at(now)
        distance = math.dist(current,center)
        if not distance or target.cc_immune(now):
            return []
        start = target.stop_position(now)
        safe_distance = math.dist(start,center)
        dest = (point_at(center,start,1+144/safe_distance) if safe_distance
                else point_at(center,current,144/distance))
        wall = self.arena.geometry.wall_contact(start,dest,36)
        if wall is not None:
            dest = point_at(start,dest,max(0,wall-.001))
        if start!=current:
            target.position,target.motion = start,None
        packets = target.interrupt(now)
        if start!=current:
            packets.append(stop_move(target.scene_id,target.id,start))
        target.forced_until = now+target._set_motion(start,dest,720,now,kind=1)
        return packets+[scene(moves=(self._move_event(target.motion[1],720,1,target.id),))]

    def _object(self, template, pos, duration, now):
        ident,packet = self.add_object(template,pos)
        # These two native takeoff/landing props have their movies on removal.
        # Other helper objects and interruption cleanup retain overtime.
        kind = 'star_visual_remove' if template in (364404,364402) else 'object_expire'
        self._queue(now+duration,kind,ident)
        return [packet]

    def _flight(self, flight, now):
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        contacts = []
        basic = flight['template']==364100
        for target in self.arena.actors.values():
            if target.alive and target.camp!=self.camp and not target.is_untargetable():
                hit = actor_contact(start,end,target,previous,now,36 if basic else 66)
                if hit is not None:
                    contacts.append((hit,target.id))
        hit = min(contacts) if contacts else None
        wall = self.arena.geometry.wall_contact(start,end)
        if hit and (wall is None or hit[0]<wall):
            target = self.arena.actors[hit[1]]
            if self.projectile_blocked(target,now):
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            packets = [scene(blown_bullets=(struct.pack('<I',flight['id']),))]
            if basic:
                packets.extend(self._hit(target,flight['raw'],flight['power'],flight['source_generation'],now,basic=True))
                if self.alive and self.generation==flight['source_generation']:
                    packets.extend(self._buff(364109,now))
            else:
                center = tuple(round(v) for v in point_at(start,end,hit[0]))
                targets = self._enemies(center,144,now)
                for victim in targets:
                    packets.extend(self._hit(victim,flight['raw'],flight['power'],flight['source_generation'],now))
                if self.alive and self.generation==flight['source_generation']:
                    for slot in (1,2,10):
                        self.cooldowns[slot] = max(now,self.cooldowns[slot]-1000*len(targets))
                        packets.append(self._cooldown(slot))
            return packets
        if wall is not None or now>=finish:
            return [scene(**{('blown_bullets' if wall is not None else 'expired_bullets'):(struct.pack('<I',flight['id']),)})]
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return []

    def _event(self, now, kind, data):
        if kind=='star_visual_remove':
            return self.remove_object(data[0],destroyed=True)
        if kind in ('star_burn','star_burn_end'):
            ident,mark = data
            target = self.arena.actors[ident]
            if kind=='star_burn' and self._valid_mark(target,mark,now):
                return self._damage(target,mark['power']*D('.1')*mark['stacks'],now,
                                    mark['source_generation'],periodic=True)[0]
            if self.marks.get(ident) is mark:
                self.marks.pop(ident,None)
            return []
        if kind=='star_sweep':
            cast,index = data
            if self.sweep is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            center = self.position_at(now)
            packets = [scene(skills=(self._skill_event(364501,center,center,self.id),))]
            for target in self._enemies(center,288,now):
                packets.extend(self._hit(target,cast['power'],cast['power'],cast['generation'],now))
            if index==12:
                return packets+self._end_sweep(now)
            self._queue(now+250,kind,cast,index+1)
            return packets
        if kind=='star_takeoff':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            self.ready,self.jump = None,cast
            self.info['untargetable'] = self.info['damage_immune'] = True
            start = self.position_at(now)
            dest = self.move_destination(start,cast['dest'])
            speed = max(1,math.dist(start,dest)*2)
            duration = self._set_motion(start,dest,speed,now,kind=4)
            self.forced_until = now+duration
            self._queue(now+duration,'star_land',cast)
            packets = self._buff(364409,now,duration=duration)
            packets += self._object(364404,start,100,now)+self._object(364402,dest,400,now)
            packets.append(scene(moves=(self._move_event(dest,round(speed),4),)))
            for target in self._enemies(start,144,now):
                packets.extend(self._hit(target,cast['power']*D('1.39'),cast['power'],cast['generation'],now))
                if self.arena.pk and self.arena.pk['finished']:
                    break
                if target.alive:
                    packets.extend(self._push(target,start,now))
            return packets
        if kind=='star_land':
            cast, = data
            if self.jump is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            center = self.position_at(now)
            packets = self._end_jump(now)+self._object(364408,center,500,now)
            for target in self._enemies(center,144,now):
                packets.extend(self._hit(target,cast['power']*D('1.68'),cast['power'],cast['generation'],now))
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot!=2 and (not self._inside(dest) or start==dest):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:30000,10:8000}[slot], slot)
        if slot in (0,1):
            packets = self.shoot(SLOTS[slot],start,dest,now,power*D('1.5' if slot==0 else '1.93'),
                                 school='energy',basic=slot==0,power=power,speed_multiplier=1.5 if slot==0 else 1)
        elif slot==2:
            self.sweep = dict(power=power,generation=self.generation,end=now+3000)
            packets = []
            for template in SPACE_BUFFS+(364308,):
                packets.extend(self._buff(template,now))
            self._queue(now+250,'star_sweep',self.sweep,1)
        else:
            if math.dist(start,dest)>408:
                dest = point_at(start,dest,408/math.dist(start,dest))
            self.ready = dict(slot=10,dest=tuple(round(x) for x in dest),power=power,generation=self.generation,
                              was_immune=self.info.get('damage_immune',False),was_untargetable=self.info.get('untargetable',False))
            self.position,self.motion = start,None
            self._queue(now+50,'star_takeoff',self.ready)
            packets = self._buff(364403,now)+[scene(skills=(self._skill_event(364401,start,dest,ready=1),))]
            packets.extend(self.sync_speed(now))
        return packets+[self._cooldown(slot)]
