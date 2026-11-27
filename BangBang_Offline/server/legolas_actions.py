"""Legolas: consumable marks, piercing E and original scene-item fields."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at, TANK_CONTACT_RADIUS
from combat_math import D
from combat_protocol import props, scene, stop_move
from melee_common import prepare_displacement

SLOTS = {0:315100, 1:315201, 2:315301, 10:315401}
MARKS = (315101,315102,315103)


class LegolasActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.e_count,self.e_next_charge = 3,0
        self.ready = None
        self.fields = {}

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,self.e_count if slot==1 else -1,
                          self.cooldowns[slot],self.e_next_charge if slot==1 else 0)+struct.pack('<I',self.id)

    def update(self, now):
        packets = super().update(now)
        if self.e_next_charge and now>=self.e_next_charge:
            while self.e_count<3 and now>=self.e_next_charge:
                self.e_count += 1
                self.e_next_charge += self.skill_cooldown(6000)
            if self.e_count==3:
                self.e_next_charge = 0
            packets.append(self._cooldown(1))
        return packets

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None

    def interrupt(self, now):
        if self.ready is None:
            return []
        self.ready = None
        return [(1583,struct.pack('<II',self.id,315401))]

    def _stage(self, target, now):
        return max((i+1 for i,t in enumerate(MARKS)
                    if target.has_buff(t,now) and target.buff_sources.get(t)==self.id),default=0)

    def on_bullet_hit(self, flight, target, now):
        if flight['template']!=315100 or flight['source_generation']!=self.generation or not self.alive or not target.alive:
            return []
        stage = min(3,self._stage(target,now)+1)
        packets = []
        for template in MARKS:
            if target.has_buff(template,now):
                packets.extend(target.remove_buff(template,now))
        return packets+self._buff(MARKS[stage-1],now,target.id)+self._buff(315121,now)

    def _field(self, template, pos, power, now, duration, kind, generation):
        ident,packet = self.add_object(template,pos)
        self.fields[ident] = dict(id=ident,pos=pos,power=power,end=now+duration,kind=kind,generation=generation)
        self._queue(now+duration,kind,ident)
        return [packet]

    def _detonate(self, target, power, generation, now):
        stage = self._stage(target,now)
        if not stage or not target.alive:
            return []
        packets = []
        for template in MARKS:
            if target.has_buff(template,now):
                packets.extend(target.remove_buff(template,now))
        packets.extend(self._buff(315112,now,target.id))
        if stage==3:
            return packets+self._field(315104,target.position_at(now),power,now,400,'mark_blast',generation)
        vamp = D('.5') if self.alive and self.generation==generation else 0
        return packets+self.damage(power*(D('.5') if stage==1 else 1),now,target=target,
                                   lifesteal=vamp,school='physical')[0]

    def _push(self, target, start, now):
        if target.cc_immune(now):
            return []
        current = target.position_at(now)
        distance = math.dist(start,current)
        if not distance:
            return []
        origin = target.stop_position(now)
        safe_distance = math.dist(start,origin)
        dest = (point_at(start,origin,1+72/safe_distance) if safe_distance
                else point_at(start,current,72/distance))
        dest = self.arena.geometry.clamp_tank_position(dest)
        wall = self.arena.geometry.wall_contact(origin,dest,TANK_CONTACT_RADIUS)
        if wall is not None:
            dest = point_at(origin,dest,max(0,wall-.001))
        dest = tuple(round(v) for v in dest)
        if origin!=current:
            target.position,target.motion = origin,None
        packets = target.interrupt(now)
        if origin!=current:
            packets.append(stop_move(target.scene_id,target.id,origin))
        target.forced_until = now+target._set_motion(origin,dest,720,now,kind=3)
        dest = target.motion[1]
        return packets+[scene(moves=(self._move_event(dest,720,3,target.id),))]

    def _event(self, now, kind, data):
        if kind=='rain_cast':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            self.ready = None
            packets = []
            # Effect315401 triggers existing marks before the delayed rain.
            # Mark damage can synchronously spawn rescue actors; they are not
            # targets of this already-started mark detonation.
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(cast['dest'],target.position_at(now))<=144:
                    packets.extend(self._detonate(target,cast['power'],cast['generation'],now))
            return packets+self._field(315402,cast['dest'],cast['power'],now,500,'rain_start',cast['generation'])
        if kind in ('mark_blast','root_start','rain_start','root_tick','rain_tick'):
            field = self.fields.get(data[0])
            if field is None:
                return []
            packets = []
            if kind in ('root_start','rain_start'):
                self.fields.pop(field['id'])
                packets.extend(self.remove_object(field['id'],destroyed=True))
                root = kind=='root_start'
                ident,packet = self.add_object(315304 if root else 315403,field['pos'])
                field.update(id=ident,end=now+(2000 if root else 3000),kind='root_tick' if root else 'rain_tick')
                self.fields[ident] = field
                self._queue(now if root else now+750,field['kind'],ident)
                return packets+[packet]
            for target in list(self.arena.actors.values()):
                if not target.alive or target.camp==self.camp or math.dist(field['pos'],target.position_at(now))>144:
                    continue
                if kind=='root_tick':
                    if now<field['end']:
                        packets.extend(self._buff(315305,now,target.id,duration=min(750,field['end']-now)))
                else:
                    vamp = D('.5') if kind=='mark_blast' and self.alive and self.generation==field['generation'] else 0
                    packets.extend(self.damage(field['power']*(2 if kind=='mark_blast' else D('.75')),now,
                                               target=target,school='physical',lifesteal=vamp,periodic=kind=='rain_tick')[0])
                    if kind=='rain_tick':
                        packets.extend(self._buff(315405,now,target.id))
                        packets.extend(self._detonate(target,field['power'],field['generation'],now))
            if kind=='mark_blast' or now>=field['end']:
                self.fields.pop(field['id'])
                packets.extend(self.remove_object(field['id'],destroyed=True))
            else:
                self._queue(min(now+750,field['end']),kind,field['id'])
            return packets
        return super()._event(now,kind,data)

    def _flight(self, flight, now):
        if flight['template'] not in (315100,315201,315301):
            return super()._flight(flight,now)
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        contacts = []
        for target in self.arena.actors.values():
            key = target.id,target.generation
            if target.alive and target.camp!=self.camp and key not in flight['hits']:
                hit = actor_contact(start,end,target,previous,now,36 if flight['basic'] else 36+48)
                if hit is not None:
                    contacts.append((hit,target.id))
        packets = []
        for _,ident in sorted(contacts):
            target = self.arena.actors[ident]
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['hits'].add((target.id,target.generation))
            pos = target.position_at(now)
            packets.extend(self.damage(flight['raw'],now,target=target,school='physical',basic=flight['basic'])[0])
            if flight['basic']:
                packets.extend(self.on_bullet_hit(flight,target,now))
                return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
            # Damage may finish the match and freeze all surviving actors.
            # Do not continue this in-flight callback into another push.
            if self.arena.pk and self.arena.pk['finished']:
                break
            packets.extend(self._detonate(target,flight['power'],flight['source_generation'],now))
            if self.arena.pk and self.arena.pk['finished']:
                break
            if flight['template']==315301:
                packets.extend(self._field(315303,pos,flight['power'],now,200,'root_start',flight['source_generation']))
                return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
            if target.alive:
                if target.has_buff(315203,now) and target.buff_sources.get(315203)==self.id:
                    packets.extend(target.remove_buff(315203,now))
                    packets.extend(self._push(target,flight['start'],now))
                else:
                    packets.extend(self._buff(315203,now,target.id))
        if now>=finish:
            return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return packets

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or (slot!=10 and dest==start) or (slot==1 and not self.e_count):
            return []
        if slot==10 and math.dist(start,dest)>600:
            return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:1000,2:25000,10:10000}[slot], slot)
        if slot==10:
            self.ready = dict(slot=slot,dest=dest,power=power,generation=self.generation)
            body,stopped = prepare_displacement(self,now,interrupt=False,cancel_motion=True)
            self.position,self.motion = body if stopped else start,None
            self._queue(now+200,'rain_cast',self.ready)
            packets = [scene(skills=(self._skill_event(315401,start,dest,ready=1),))]+self._buff(315411,now)+stopped
        else:
            if slot==1:
                self.e_count -= 1
                if not self.e_next_charge:
                    self.e_next_charge = now+self.skill_cooldown(6000)
            ratio = {0:D('1.5'),1:D('2.01'),2:D('4.37')}[slot]
            packets = self.shoot(SLOTS[slot],start,dest,now,power*ratio,school='physical',basic=slot==0,
                                 speed_multiplier=1.5 if slot==0 else 1,power=power,through_walls=True)
        return packets+[self._cooldown(slot)]
