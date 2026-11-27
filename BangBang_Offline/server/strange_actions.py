"""Doctor Strange: native exile, cast reveal and a non-recursive shield burst."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import props, scene
from hulu_actions import HuluTurret
from melee_common import aimed, enemies, piercing_step, prepare_displacement

SLOTS = {0:357100, 1:357201, 2:357301, 10:357401}


class StrangeActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.ready = None
        self.shadow = None
        self.reveal = None
        self.shield_power = D(0)
        self.r_marks = {}

    def _cooldown(self, slot, changed=False):
        now = self.clock()
        skill = 357411 if slot==0 and self.has_buff(357406,now) else SLOTS[slot]
        end = self.cooldowns[slot]
        if slot==1 and self.shadow:
            skill,end = 357211,self.shadow['begin']+1000
        body = props(skill,slot,-1,end)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self, now):
        self.ready = self.shadow = self.reveal = None
        self.shield_power = D(0)
        self.r_marks = {}
        packets = [self._cooldown(0,True),self._cooldown(1,True)]
        for template in (357101,357102,357103): packets.extend(self._buff(template,now))
        return packets

    def reject_buff(self, row, source, now):
        # The E animation's own short slot lock is not an enemy silence.
        return source.camp!=self.camp and row['nEffectType'] in ('35','66')

    def blocked(self, action, now):
        return bool(self.ready) or super().blocked(action,now)

    def _speed(self, now):
        return 0 if self.ready else super()._speed(now)

    def interrupt(self, now):
        packets = []
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            self.ready = None
        if not self.alive and self.shadow:
            clone = self.arena.actors.get(self.shadow['id'])
            if clone and clone.alive: packets.extend(clone.commit_hp(D(0),now))
            self.shadow = None
        return packets+self.sync_speed(now)

    def on_target_death(self, target, now):
        self.r_marks.pop((target.id,target.generation),None)
        if self.shadow and target.id==self.shadow['id']:
            self.shadow = None
            return self.remove_buff(357205,now)+[self._cooldown(1,True)]
        return []

    def _area(self, pos, radius, raw, now, generation, power):
        packets = []
        for target in enemies(self,area=True):
            if math.dist(pos,target.position_at(now))<=radius:
                packets.extend(self._skill_hit(raw,target,now,generation,power))
                if self.arena.pk and self.arena.pk['finished']:break
        return packets

    def _reveal(self, now):
        if not self.alive or self.arena.pk and self.arena.pk['finished']:return []
        packets = self._buff(357121,now)
        if self.reveal and self.reveal['end']>now:
            self.reveal['end'] = now+2000
        else:
            self.reveal = dict(end=now+2000,generation=self.generation)
            self._queue(now,'strange_reveal',self.reveal)
        return packets

    def _grant_shield(self, now, generation, power):
        if not self.alive or self.generation!=generation or self.arena.pk and self.arena.pk['finished']: return []
        # Expiry, break and replacement all use the same single removal path.
        packets = self.remove_buff(357111,now)
        self.shield_power = power
        return packets+self.add_shield(357111,self.max_hp*D('.1'),now)

    def remove_buff(self, template, now, *, expired=False):
        active = (self.id,template) in self.active_buffs
        power = self.shield_power
        packets = super().remove_buff(template,now,expired=expired)
        if active and template==357111 and self.alive and not (self.arena.pk and self.arena.pk['finished']):
            self.shield_power = D(0)
            pos = self.position_at(now)
            for target in enemies(self,area=True):
                if math.dist(pos,target.position_at(now))>144: continue
                packets.extend(self.damage(power*D('.25'),now,target=target,school='true')[0])
                if self.arena.pk and self.arena.pk['finished']:return packets
                count = min(3,target.buff_stacks.get(357132,0)+1) if target.has_buff(357132,now) else 1
                packets.extend(self._buff(357132,now,target.id,stacks=count))
            packets.extend(self._buff(357133,now))
        if active and template==357406: packets.append(self._cooldown(0,True))
        return packets

    def _skill_hit(self, raw, target, now, generation, power):
        if not target.alive or target.has_buff(357402,now): return []
        packets = self.damage(raw,now,target=target,school='energy')[0]
        return packets+self._grant_shield(now,generation,power)

    def _r_hit(self, flight, target, now):
        generation,power = flight['source_generation'],flight['power']
        packets = self._skill_hit(flight['raw'],target,now,generation,power)
        if not target.alive: return packets
        packets.extend(self._buff(357402,now,target.id))
        if target.has_buff(357402,now):
            end = self.active_buffs[(target.id,357402)][1]
            ident, packet = self.add_object(357405,target.position_at(now))
            packets.append(packet)
            self._queue(end,'object_expire',ident)
        else:
            end = now
        if self.alive and self.generation==generation:
            packets.extend(self._buff(357406,now))
            packets.append(self._cooldown(0,True))
        mark = dict(target=target.id,target_generation=target.generation,generation=generation,end=now+3000)
        self.r_marks[target.id,target.generation] = mark
        self._queue(end,'strange_exile_end',mark)
        return packets

    def _flight(self, flight, now):
        if flight['template']==357401:
            return piercing_step(self,flight,now,self._r_hit,pierce=False)
        if flight['template']==357411:
            return piercing_step(self,flight,now,self._empowered_hit,pierce=False)
        return super()._flight(flight,now)

    def _empowered_hit(self, flight, target, now):
        mark = self.r_marks.get((target.id,target.generation))
        enhanced = mark and mark['end']>now and mark['generation']==flight['source_generation'] and target.has_buff(357404,now)
        packets = self.damage(flight['raw']*(2 if enhanced else 1),now,target=target,school='energy',basic=True)[0]
        if enhanced:
            self.r_marks.pop((target.id,target.generation),None)
            packets.extend(target.remove_buff(357404,now))
            if self.alive and self.generation==flight['source_generation']:
                packets.extend(self.restore_hp(flight['power']*D('1.5'),now))
        return packets

    def _event(self, now, kind, data):
        if kind=='strange_cast':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']: return []
            self.ready = None
            packets = self.sync_speed(now)
            start = self.position_at(now)
            if cast['skill']==357211:
                clone = self.arena.actors.get(cast['target'])
                if not clone or not clone.alive or not self.shadow or clone.id!=self.shadow['id']: return packets
                dest = self.blink_destination(start,clone.position_at(now))
                packets.append(scene(skills=(self._skill_event(357211,start,dest,clone.id),)))
                self.position,self.motion = dest,None
                packets.append(scene(moves=(self._move_event(dest,0,5),)))
                packets.extend(clone.commit_hp(D(0),now))
                packets.extend(self.remove_buff(357205,now))
                return packets+self._reveal(now)
            dest = self.blink_destination(start,aimed(start,cast['dest'],600))
            info = dict(acct_id=self.info['acct_id'],tank_id=self.info['tank_id'],tank_level=self.info['tank_level'],
                        npc_template=357201,owner=self.id,source_generation=self.generation,
                        name=self.info['name'],in_room=True,summon_stats=dict(self.stats),summon_hp=str(self.hp))
            for key in ('iAttack','iEgAtk','iArmor','iEgArmor','iCentesis','iEgCtsis'):
                info['summon_stats'][key] = str(self.combat_stat(key,now))
            info['summon_stats']['iHp'] = str(self.max_hp)
            clone = StrangeShadow(self.arena,self._new_id(5),info,self.camp,start)
            self.arena.actors[clone.id] = clone
            shadow = self.shadow = dict(id=clone.id,begin=cast['begin'],end=cast['begin']+5000)
            clone._queue(self.shadow['end'],'strange_shadow_end')
            packets.extend([clone.snapshot(now)]+clone._buff(357221,now,duration=self.shadow['end']-now))
            self.position,self.motion = dest,None
            packets.extend((scene(moves=(self._move_event(dest,0,5),)),scene(skills=(self._skill_event(357201,start,dest),))))
            packets.extend(self._area(dest,144,cast['power']*D('1.63'),now,cast['generation'],cast['power']))
            # Damage can synchronously kill the owner/clone or finish the
            # match. The death hook then clears self.shadow before E resumes.
            if not self.alive or self.generation!=cast['generation'] or self.arena.pk and self.arena.pk['finished']:return packets
            for target in enemies(self,area=True):
                if math.dist(dest,target.position_at(now))<=96: packets.extend(self._buff(357204,now,target.id))
            for template in (357205,357206,357207,357208):
                if template==357205 and self.shadow is not shadow:continue
                packets.extend(self._buff(template,now,duration=shadow['end']-now if template==357205 else None))
            for tick in range(1,5): self._queue(now+750*tick,'strange_pulse',cast)
            packets.extend(self._reveal(now))
            packets.append(self._cooldown(1,True))
            return packets
        if kind=='strange_pulse':
            cast, = data
            if not self.alive or self.generation!=cast['generation']: return []
            pos = self.position_at(now)
            packets = [scene(skills=(self._skill_event(357221,pos,pos),))]
            for target in enemies(self,area=True):
                if math.dist(pos,target.position_at(now))>144: continue
                amplified = target.has_buff(357312,now) and target.buff_sources.get(357312)==self.id
                raw = cast['power']*D('.5')*(2 if amplified else 1)
                packets.extend(self._skill_hit(raw,target,now,cast['generation'],cast['power']))
            return packets
        if kind=='strange_field_open':
            cast, = data
            packets = self.remove_object(cast['id'])
            pos = cast['pos']
            packets.extend(self._area(pos,144,cast['power']*D('2.03'),now,cast['generation'],cast['power']))
            for target in enemies(self,area=True):
                if math.dist(pos,target.position_at(now))<=144:
                    packets.extend(self._buff(357303,now,target.id)+self._buff(357304,now,target.id))
            ident,packet = self.add_object(357305,pos)
            cast.update(id=ident,end=now+4000,inside=False)
            packets.append(packet)
            if self.alive and self.generation==cast['generation']: packets.extend(self._buff(357306,now))
            self._queue(now,'strange_field',cast)
            return packets
        if kind=='strange_field':
            cast, = data
            if now>=cast['end']: return self.remove_object(cast['id'])
            packets = []
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))<=144:
                    # This original debuff modifies only E's orbit pulses.
                    packets.extend(self._buff(357312,now,target.id))
            current = self.alive and self.generation==cast['generation']
            inside = current and not self.has_buff(357402,now) and math.dist(cast['pos'],self.position_at(now))<=144
            if inside and not cast['inside']:
                pos = self.position_at(now)
                packets.extend(self._buff(357311,now))
                for target in enemies(self,area=True):
                    if math.dist(pos,target.position_at(now))<=144:
                        packets.extend(self._skill_hit(cast['power']*D('1.67'),target,now,cast['generation'],cast['power']))
                        packets.extend(self._buff(357322,now,target.id))
                packets.extend(self._buff(357323,now))
            cast['inside'] = inside
            self._queue(min(now+100,cast['end']),kind,cast)
            return packets
        if kind=='strange_reveal':
            cast, = data
            if self.reveal is not cast or not self.alive or self.generation!=cast['generation']: return []
            if now>=cast['end']:
                self.reveal = None
                return []
            packets = []
            for target in self.arena.actors.values():
                if target.alive and target.camp!=self.camp and math.dist(self.position_at(now),target.position_at(now))<=360:
                    packets.extend(self._buff(357141,now,target.id,duration=min(300,cast['end']-now)))
            self._queue(min(now+250,cast['end']),kind,cast)
            return packets
        if kind=='strange_exile_end':
            mark, = data
            target = self.arena.actors.get(mark['target'])
            if not target or not target.alive or target.generation!=mark['target_generation']: return []
            return self._buff(357403,now,target.id,duration=2000)+self._buff(357404,now,target.id,duration=max(1,mark['end']-now))
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        second = slot==1 and self.shadow is not None
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now): return []
        if now<(self.shadow['begin']+1000 if second else self.cooldowns[slot]): return []
        if slot in (0,10) and start==dest: return []
        power = self.combat_stat('iEgAtk',now)
        if not second: self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:20000,10:6000}[slot], slot)
        if slot==0:
            enhanced = self.has_buff(357406,now)
            packets = self.remove_buff(357406,now) if enhanced else []
            return packets+self.shoot(357411 if enhanced else 357100,start,dest,now,power,school='energy',basic=True,power=power)+[self._cooldown(0)]
        if slot==10:
            return self._reveal(now)+self.shoot(357401,start,dest,now,power*D('1.44'),school='energy',power=power,through_walls=True)+[self._cooldown(10)]
        if slot==2:
            pos = aimed(start,dest,600)
            ident,packet = self.add_object(357301,pos)
            self._queue(now+1000,'strange_field_open',dict(id=ident,pos=pos,power=power,generation=self.generation))
            return [packet,self._cooldown(2)]+self._reveal(now)
        body,stopped=prepare_displacement(self,now,interrupt=False)
        self.position,self.motion = body if stopped else start,None
        self.ready = dict(slot=1,skill=357211 if second else 357201,begin=now,dest=dest,power=power,
                          generation=self.generation,target=self.shadow['id'] if second else 0)
        self._queue(now+50,'strange_cast',self.ready)
        return [scene(skills=(self._skill_event(self.ready['skill'],start,dest,self.ready['target'],ready=1),)),self._cooldown(1)]+self.sync_speed(now)+stopped


class StrangeShadow(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.stats = dict(self.info['summon_stats'])
        self.max_hp = D(self.stats['iHp'])
        self.hp = min(self.max_hp,D(self.info['summon_hp']))
        self.info.update(hp=math.ceil(self.hp),max_hp=math.ceil(self.max_hp))
        self.cooldowns = {}

    def snapshot(self, now):
        body = struct.pack('<IIhhiBiIiH',self.id,357201,*self.position_at(now),math.ceil(self.hp),self.camp,
                           math.ceil(self.max_hp),self.info['owner'],0,0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def sync_speed(self, now): return []

    def commit_hp(self, hp, now,*,critical=False):
        before = self.alive
        packets = super().commit_hp(hp,now,critical=critical)
        if before and not self.alive: packets.append(scene(removed=(struct.pack('<I',self.id),)))
        return packets

    def _event(self, now, kind, data):
        if kind=='strange_shadow_end': return self.commit_hp(D(0),now) if self.alive else []
        return super()._event(now,kind,data)

    _respawn = HuluTurret._respawn
