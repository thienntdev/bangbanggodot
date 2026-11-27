"""Groot: mobile drain/borrow and a fixed field; provisional rules in HienTai."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:416100, 1:416201, 2:416301, 10:416401}
BORROW_KEYS = ('iAttack','iEgAtk','iArmor','iEgArmor')


class GrootActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.passive_ready_at = 0
        self.drain = None
        self.fields = {}

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self, now):
        return self._buff(416101,now)

    def on_damage(self, source, hit, now, school, reflected, attacker_ap):
        if not self.alive or not hit.hp_loss or self.hp>=self.max_hp*D('.8') or self.passive_ready_at>now:
            return []
        self.passive_ready_at = now+10000
        start = self.position_at(now)
        packets = [scene(skills=(self._skill_event(416111,start,start,self.id),))]
        packets.extend(self.restore_hp(self.max_hp*D('.05'),now))
        packets.extend(self._buff(416102,now,duration=3000))
        packets.extend(self.cleanse(now))
        packets.extend(self._buff(416104,now))
        packets.extend(self._buff(416105,now,duration=3000))
        for offset in (1000,2000,3000):
            self._queue(now+offset,'regrowth',self.generation,self.buff_versions[416102])
        return packets

    def interrupt(self, now):
        if self.alive:
            return []  # Mobile R is an aura, not a held beam.
        packets = []
        if self.drain:
            self.drain = None
            self.cooldowns[10] = now+self.skill_cooldown(8000, 10)
            packets.append(self._cooldown(10))
        for field in self.fields.values():
            packets.extend(self.remove_object(field['id']))
        self.fields.clear()
        return packets

    def _borrow(self, target, now):
        key = self.id,self.generation,target.id,target.generation
        old = self.stat_loans.get(key)
        continuing = old and old['end']>now and self.has_buff(416413,now)
        base = old['base'] if continuing else {k:target.combat_stat(k,now) for k in BORROW_KEYS}
        stacks = min(10,old['stacks']+1) if continuing else 1
        values = {k:v*D('.05')*stacks for k,v in base.items()}
        packets = []
        for owner,templates in ((self,(416412,416413)),(target,(416415,416416))):
            for template in templates:
                packets.extend(self._buff(template,now,owner.id))
        self.stat_loans[key] = dict(base=base,values=values,stacks=stacks,end=now+2000,armor_buff=416412,attack_buff=416413)
        target.stat_loans[key] = dict(values={k:-v for k,v in values.items()},end=now+2000,armor_buff=416415,attack_buff=416416)
        return packets

    def _field_tick(self, field, now):
        packets = []
        for target in self.arena.actors.values():
            if not target.alive or math.dist(field['pos'],target.position_at(now))>264:
                continue
            if target.camp==self.camp:
                for template in (416321,416322,416325):
                    packets.extend(self._buff(template,now,target.id))
            else:
                packets.extend(target.strip_defenses(now))
                packets.extend(self._buff(416323,now,target.id))
                packets.extend(self._buff(416324,now,target.id))
                key = target.id,target.generation
                mark = field['marks'].get(key)
                if mark is None or mark['end']<=now:
                    mark = field['marks'][key] = dict(pos=target.position_at(now),end=now+2000,
                                                     previous=now,steps=[],stage=0,done=False)
                    self._queue(now+20,'movement_mark',field,key,mark)
                mark['end'] = now+2000
        return packets

    def _event(self, now, kind, data):
        if kind=='regrowth':
            generation,version = data
            if self.alive and generation==self.generation and self.buff_versions.get(416102)==version:
                return self.restore_hp(self.max_hp*D('.02'),now)
            return []
        if kind=='drain_tick':
            cast, = data
            if self.drain is not cast or not self.alive or cast['generation']!=self.generation:
                return []
            pos = self.position_at(now)
            packets = [scene(skills=(self._skill_event(416411,pos,pos,self.id),))]
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(pos,target.position_at(now))<=192:
                    hit,lost = self.damage(cast['power']*D('.42'),now,target=target,school='energy')
                    packets.extend(hit)
                    if lost:
                        packets.extend(self._borrow(target,now))
                        packets.extend(self.restore_hp(cast['power']*D('.26'),now))
            if now==cast['end']:
                self.drain = None
                packets.extend(self.remove_buff(416403,now))
                packets.extend(self._buff(416421,now))
                self.cooldowns[10] = now+self.skill_cooldown(8000, 10)
                packets.append(self._cooldown(10))
            return packets
        if kind=='field_open':
            token, = data
            field = self.fields.get(token)
            if field is None:
                return []
            packets = self.remove_object(field['id'],destroyed=True)
            field['id'],packet = self.add_object(416311,field['pos'])
            packets.append(packet)
            for target in list(self.arena.actors.values()):
                if not target.alive or math.dist(field['pos'],target.position_at(now))>264:
                    continue
                if target.camp==self.camp:
                    packets.extend(target.restore_hp(field['power']*D('1.95'),now))
                    packets.extend(self._buff(416313,now,target.id))
                else:
                    packets.extend(self.damage(field['power']*D('2.47'),now,target=target,school='energy')[0])
                    packets.extend(target.strip_defenses(now))
                    packets.extend(self._buff(416315,now,target.id))
            self._queue(now,'field_tick',token)
            return packets
        if kind=='field_tick':
            token, = data
            field = self.fields.get(token)
            if field is None:
                return []
            if now>=field['end']:
                del self.fields[token]
                return self.remove_object(field['id'],destroyed=True)
            self._queue(min(now+500,field['end']),kind,token)
            return self._field_tick(field,now)  # User: refresh 550 ms buffs continuously.
        if kind=='movement_mark':
            field,key,mark = data
            target = self.arena.actors[key[0]]
            if (not target.alive or target.generation!=key[1] or now>=mark['end']
                    or not target.has_buff(416324,now) or mark['done']):
                return []
            pos = target.position_at(now)
            mark['steps'].append(dict(end=now,distance=math.dist(mark['pos'],pos)))
            mark['steps'] = [s for s in mark['steps'] if s['end']>now-2000]
            mark['pos'],mark['previous'] = pos,now
            distance = sum(s['distance'] for s in mark['steps'])
            stage = min(3,int(distance//90))
            packets = []
            if stage!=mark['stage']:
                for template in (416341,416342,416343):
                    packets.extend(target.remove_buff(template,now))
                if stage:
                    packets.extend(self._buff(416340+stage,now,target.id))
                mark['stage'] = stage
            if distance>=360:
                mark['done'] = True
                for template in (416351,416352):
                    packets.extend(self._buff(template,now,target.id))
                packets.extend(self.damage(target.hp*D('.25'),now,target=target,school='true')[0])
            else:
                self._queue(min(now+20,mark['end']),kind,field,key,mark)
            return packets
        return super()._event(now,kind,data)

    def _flight(self, flight, now):
        if flight.get('template')!=416201:
            return super()._flight(flight,now)
        start = point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        wall = self.arena.geometry.wall_contact(start,end)
        for target in list(self.arena.actors.values()):
            if target.alive and target.camp!=self.camp and self.projectile_blocked(target,now):
                hit = actor_contact(start,end,target,flight['previous'],now)
                if hit is not None and (wall is None or hit<wall):
                    return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        if wall is None and now<flight['finish']:
            flight['previous'] = now
            self._queue(min(now+20,flight['finish']),'flight',flight)
            return []
        pos = point_at(start,end,wall) if wall is not None else end
        packets = [scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        for target in list(self.arena.actors.values()):
            if target.alive and target.camp!=self.camp and math.dist(pos,target.position_at(now))<=168:
                packets.extend(self.damage(flight['raw'],now,target=target,school='energy')[0])
                for template in (416202,416203):
                    packets.extend(self._buff(template,now,target.id))
        ident,packet = self.add_object(416204,pos)
        self._queue(now+800,'object_expire',ident)
        return packets+[packet]

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot==10 and self.drain:
            return []
        if slot in (0,1,2) and (not self._inside(dest) or slot!=2 and start==dest):
            return []
        if slot in (1,2) and math.dist(start,dest)>{1:480,2:360}[slot]:
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+{0:self.fire_interval(now),1:self.skill_cooldown(6000,1),2:self.skill_cooldown(30000,2),10:5000}[slot]
        if slot==0:
            packets = self.shoot(416100,start,dest,now,power,school='energy',basic=True)
        elif slot==1:
            ident = self._new_id(2)
            speed = round(600*float(1+self.attr_bonus((37,),now)))
            duration = max(1,round(math.dist(start,dest)*1000/speed))
            flight = dict(kind='bullet',id=ident,template=416201,start=start,end=dest,begin=now,
                          finish=now+duration,previous=now,speed=speed,raw=power*D('1.89'),source_generation=self.generation)
            self._queue(now+min(20,duration),'flight',flight)
            packets = [scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*dest,speed,416201),))]
        elif slot==2:
            ident,packet = self.add_object(416301,dest)
            self.fields[ident] = dict(id=ident,pos=dest,power=power,end=now+5000,marks={})
            self._queue(now+1000,'field_open',ident)
            packets = [scene(skills=(self._skill_event(416301,start,dest),)),packet]
        else:
            self.drain = dict(power=power,end=now+5000,generation=self.generation)
            packets = [scene(skills=(self._skill_event(416401,start,start,self.id),))]
            for template in (416401,416402,416403):
                packets.extend(self._buff(template,now))
            for offset in range(500,5001,500):
                self._queue(now+offset,'drain_tick',self.drain)
        return packets+[self._cooldown(slot)]
