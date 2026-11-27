"""Thor: original packets; 04B wall/Space choices are recorded in HienTaiBangbang."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:313100, 1:313201, 2:313301, 10:313401}


class ThorActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.e_count, self.e_next_charge = 2, 0
        self.ready = None
        self.fields = {}

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,self.e_count if slot==1 else -1,
                          self.cooldowns[slot],self.e_next_charge if slot==1 else 0)+struct.pack('<I',self.id)

    def on_spawn(self, now):
        return self._buff(313101,now)

    def update(self, now):
        packets = super().update(now)
        if self.e_next_charge and now>=self.e_next_charge:
            while self.e_count<2 and now>=self.e_next_charge:
                self.e_count += 1
                self.e_next_charge += self.skill_cooldown(6000)
            if self.e_count==2:
                self.e_next_charge = 0
            packets.append(self._cooldown(1))
        return packets

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None

    def interrupt(self, now):
        if self.ready is None:
            return []
        self.ready = None
        self.cooldowns[2] = now+self.skill_cooldown(10000, 2)
        return [(1583,struct.pack('<II',self.id,313301)),self._cooldown(2)]

    def _hit(self, target, raw, now, *, periodic=False):
        generation = target.generation
        packets,lost = self.damage(raw,now,target=target,school='energy',periodic=periodic)
        if not lost or not target.alive or target.generation!=generation:
            return packets
        # Separate true packet cannot recursively trigger this method.
        packets.extend(self.damage(target.max_hp*D('.03'),now,target=target,
                                   school='true',periodic=periodic)[0])
        if not target.alive or target.has_buff(313121,now):
            return packets
        stage = 2 if target.has_buff(313132,now) else 1 if target.has_buff(313131,now) else 0
        for template in (313131,313132):
            if target.has_buff(template,now):
                packets.extend(target.remove_buff(template,now))
        if stage==2:
            packets.extend(self._buff(313121,now,target.id))
            packets.extend(self._buff(313133,now,target.id))
        else:
            packets.extend(self._buff(313131+stage,now,target.id))
        return packets

    def _field(self, pos, power, now):
        ident,packet = self.add_object(313302,pos)
        self.fields[ident] = dict(id=ident,pos=pos,power=power,end=now+4000)
        for offset in (900,1800,2700,3600):
            self._queue(now+offset,'thunder_field',ident)
        self._queue(now+4000,'thunder_end',ident)
        return [packet]

    def _event(self, now, kind, data):
        if kind=='thor_visual_remove':
            # Prop313401 is the native 500ms presentation-only lightning cue.
            # Its movie is on ITEM_REMOVE; the 600ms strike remains separate.
            return self.remove_object(data[0],destroyed=True)
        if kind=='hammer_cast':
            cast, = data
            if self.ready is not cast or not self.alive or cast['generation']!=self.generation:
                return []
            self.ready = None
            return self.shoot(313301,self.position_at(now),cast['dest'],now,cast['power']*D('1.7'),
                              school='energy',power=cast['power'])
        if kind=='thunder_strike':
            cast, = data
            packets = self.remove_object(cast['id'],destroyed=True)
            if not self.alive or cast['generation']!=self.generation:
                return packets
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(cast['pos'],target.position_at(now))<=120:
                    packets.extend(self._hit(target,cast['power']*D('2.29'),now))
                    packets.extend(self._buff(313412,now,target.id))
            return packets
        if kind=='thunder_field':
            field = self.fields.get(data[0])
            if field is None:
                return []
            packets = []
            # User: an already-created field survives its owner's death.
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(field['pos'],target.position_at(now))<=192:
                    packets.extend(self._hit(target,field['power']*D('.85'),now,periodic=True))
                    packets.extend(self._buff(313312,now,target.id))
            return packets
        if kind=='thunder_end':
            field = self.fields.pop(data[0],None)
            return self.remove_object(field['id'],destroyed=True) if field else []
        return super()._event(now,kind,data)

    def _flight(self, flight, now):
        if flight.get('template') not in (313201,313211,313301):
            return super()._flight(flight,now)
        previous = flight['previous']
        chain = flight['template']!=313301
        target = self.arena.actors.get(flight.get('target')) if chain else None
        packets = []
        if chain:
            if target is None or not target.alive or target.generation!=flight['target_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start,dest = flight['pos'],target.position_at(now)
            end = point_at(start,dest,min(1,flight['speed']*(now-previous)/1000/max(1,math.dist(start,dest))))
            if dest!=flight['end']:
                packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))))
                flight['end'] = dest
            candidates = [target]
        else:
            start = point_at(flight['start'],flight['end'],(previous-flight['begin'])/(flight['finish']-flight['begin']))
            end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
            candidates = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp]
        hits = []
        for actor in candidates:
            contact = actor_contact(start,end,actor,previous,now)
            if contact is not None:
                hits.append((contact,actor.id))
        contact = min(hits) if hits else None
        if contact and self.projectile_blocked(self.arena.actors[contact[1]],now):
            return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        if contact or now>=flight['finish']:
            pos = tuple(round(v) for v in point_at(start,end,contact[0] if contact else 1))
            packets.append(scene(blown_bullets=(struct.pack('<I',flight['id']),)))
            if not chain:
                for actor in list(self.arena.actors.values()):
                    if actor.alive and actor.camp!=self.camp and math.dist(pos,actor.position_at(now))<=192:
                        packets.extend(self._hit(actor,flight['raw'],now))
                if self.alive and self.generation==flight['source_generation']:
                    packets.extend(self._field(pos,flight['power'],now))
            elif contact:
                target = self.arena.actors[contact[1]]
                packets.extend(self._hit(target,flight['raw'],now))
                visited = flight.setdefault('hits',set())
                visited.add(target.id)
                next_targets = sorted((math.dist(pos,a.position_at(now)),a.id) for a in self.arena.actors.values()
                                      if a.alive and a.camp!=self.camp and a.id not in visited
                                      and not a.is_untargetable() and math.dist(pos,a.position_at(now))<=336)
                if len(visited)<5 and next_targets and self.alive and self.generation==flight['source_generation']:
                    nxt = self.arena.actors[next_targets[0][1]]
                    packets.extend(self.shoot(313211,pos,nxt.position_at(now),now,flight['raw']*D('.75'),
                                              school='energy',target=nxt,power=flight['power'],hit_ids=visited))
            return packets
        flight['pos'],flight['previous'] = end,now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or slot in (0,2) and start==dest:
            return []
        target = self.arena.actors.get(target_id)
        if slot==1 and (not self.e_count or target is None or not target.alive or target.camp==self.camp
                        or target.is_untargetable() or math.dist(start,target.position_at(now))>600):
            return []
        if slot==10 and math.dist(start,dest)>600:
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:3000,2:25000,10:8000}[slot], slot)
        if slot==0:
            packets = self.shoot(313100,start,dest,now,power,school='energy',basic=True)
        elif slot==1:
            self.e_count -= 1
            if not self.e_next_charge:
                self.e_next_charge = now+self.skill_cooldown(6000)
            packets = self.shoot(313201,start,target.position_at(now),now,power*D('1.93'),school='energy',target=target,power=power)
        elif slot==2:
            self.ready = dict(slot=2,dest=dest,power=power,generation=self.generation)
            self._queue(now+150,'hammer_cast',self.ready)
            packets = [scene(skills=(self._skill_event(313301,start,dest,ready=1),))]
        else:
            ident,packet = self.add_object(313401,dest)
            other,other_packet = self.add_object(313402,dest)
            self._queue(now+500,'thor_visual_remove',ident)
            self._queue(now+600,'thunder_strike',dict(id=other,pos=dest,power=power,generation=self.generation))
            packets = [packet,other_packet]
        return packets+[self._cooldown(slot)]
