"""Scorpion: one poison clock per target, consumed once by Space."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:343100, 1:343201, 2:343301, 10:343401}
POISON = tuple(range(343111,343121))
DOT = tuple(D(v) for v in ('.10','.13','.16','.20','.24','.31','.38','.48','.60','.75'))


class ScorpionActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.marks = {}
        self.spray = None
        self.space_count,self.space_next_charge = 2,0

    def _cooldown(self, slot, changed=False):
        skill = 343211 if slot==0 and self.has_buff(343201,self.clock()) else SLOTS[slot]
        body = props(skill,slot,self.space_count if slot==2 else -1,
                     self.cooldowns[slot],self.space_next_charge if slot==2 else 0)
        return (1579,body) if changed else (1572,body+struct.pack('<I',self.id))

    def _basic_slot(self):
        return ([self._cooldown(0,True)] if self.id==1 else [])+[self._cooldown(0)]

    def on_spawn(self, now):
        return self._buff(343101,now)+self._buff(343102,now)+self._basic_slot()

    def remove_buff(self, template, now, *, expired=False):
        existed = (self.id,template) in self.active_buffs
        packets = super().remove_buff(template,now,expired=expired)
        if template==343201 and existed:
            packets.extend(self._basic_slot())
        return packets

    def update(self, now):
        packets = super().update(now)
        if self.space_next_charge and now>=self.space_next_charge:
            while self.space_count<2 and now>=self.space_next_charge:
                self.space_count += 1
                self.space_next_charge += self.skill_cooldown(15000)
            if self.space_count==2:
                self.space_next_charge = 0
            packets.append(self._cooldown(2))
        return packets

    def interrupt(self, now):
        self.spray = None
        return []

    def on_target_death(self, target, now):
        self.marks.pop(target.id,None)
        return []

    def _mark_valid(self, target, mark, now, *, final_tick=False):
        return (self.marks.get(target.id) is mark and target.alive
                and target.generation==mark['target_generation']
                and target.buff_versions.get(mark['template'])==mark['version']
                and (now<=mark['end'] if final_tick else now<mark['end'])
                and (final_tick or target.has_buff(mark['template'],now)))

    def _poison(self, target, power, generation, now):
        if not target.alive or target.reject_buff({'nEffectType':'201'},self,now):
            return []
        old = self.marks.get(target.id)
        valid = old and old['source_generation']==generation and self._mark_valid(target,old,now)
        count = min(10,old['stacks']+1) if valid else 1
        packets = []
        for template in POISON:
            if target.has_buff(template,now):
                packets.extend(target.remove_buff(template,now))
        template = POISON[count-1]
        packets.extend(self._buff(template,now,target.id))
        mark = old if valid else {}
        mark.update(stacks=count,template=template,version=target.buff_versions[template],
                    end=now+5000,power=power,source_generation=generation,target_generation=target.generation)
        self.marks[target.id] = mark
        if not valid:
            self._queue(now+1000,'scorpion_dot',target.id,mark)
        # Refresh duration/power but retain the existing 1 s clock; never add
        # another DOT loop when a volley changes the displayed stack template.
        return packets

    def _consume(self, target, now):
        mark = self.marks.pop(target.id,None)
        packets = []
        if mark and target.has_buff(mark['template'],now) and target.buff_sources.get(mark['template'])==self.id:
            packets.extend(target.remove_buff(mark['template'],now))
        return packets

    def _flight(self, flight, now):
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        enhanced = flight['template']==343211
        contacts = []
        for target in self.arena.actors.values():
            if (target.alive and target.camp!=self.camp and not target.is_untargetable()
                    and (target.id,target.generation) not in flight['hits']):
                hit = actor_contact(start,end,target,previous,now,36+24 if enhanced else 36)
                if hit is not None:
                    contacts.append((hit,target.id))
        wall = None if enhanced else self.arena.geometry.wall_contact(start,end)
        packets = []
        for contact,ident in sorted(contacts):
            if wall is not None and contact>=wall:
                break
            target = self.arena.actors[ident]
            flight['hits'].add((ident,target.generation))
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            packets.extend(self.damage(flight['raw'],now,target=target,school='energy',basic=True)[0])
            packets.extend(self._poison(target,flight['power'],flight['source_generation'],now))
            if not enhanced:
                return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if now>=finish or wall is not None:
            return packets+[scene(**{('blown_bullets' if wall is not None else 'expired_bullets'):(struct.pack('<I',flight['id']),)})]
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return packets

    def _explode(self, target, center, stacks, power, now):
        packets = []
        raw = power*(1+D('.5')*((stacks-1)//3))  # User retained V1, not the geometric raw table.
        for victim in list(self.arena.actors.values()):
            if victim.alive and victim.camp!=self.camp and math.dist(center,victim.position_at(now))<=120:
                packets.extend(self.damage(raw,now,target=victim,school='energy',lifesteal=D('.25'))[0])
        if stacks==10:
            packets.extend(self._buff(343321,now,target.id)+self._buff(343322,now,target.id))
        return packets

    def _event(self, now, kind, data):
        if kind=='scorpion_dot':
            ident,mark = data
            target = self.arena.actors[ident]
            if not self._mark_valid(target,mark,now,final_tick=True):
                if self.marks.get(ident) is mark:
                    self.marks.pop(ident)
                return []
            steal = D('.5') if self.generation==mark['source_generation'] and self.alive else 0
            packets = self.damage(mark['power']*DOT[mark['stacks']-1],now,target=target,
                                  school='energy',lifesteal=steal,periodic=True)[0]
            if self.marks.get(ident) is mark:
                if now<mark['end']:
                    self._queue(now+1000,kind,ident,mark)
                else:
                    self.marks.pop(ident,None)  # No natural-expiry explosion.
            return packets
        if kind=='scorpion_spray':
            cast,index = data
            if self.spray is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            center = self.position_at(now)
            dest = tuple(round(a+b*480) for a,b in zip(center,cast['direction']))
            packets = [scene(skills=(self._skill_event(343401,center,dest),))]
            for target in list(self.arena.actors.values()):
                if not target.alive or target.camp==self.camp or target.is_untargetable():
                    continue
                pos = target.position_at(now)
                distance = math.dist(center,pos)
                dot = sum((b-a)*v for a,b,v in zip(center,pos,cast['direction']))
                if distance<=480 and (distance==0 or dot>=distance*math.cos(math.radians(15))):
                    packets.extend(self.damage(cast['power']*D('.58'),now,target=target,school='energy')[0])
                    packets.extend(self._poison(target,cast['power'],cast['generation'],now))
            if index<4 and self.spray is cast:
                self._queue(now+300,kind,cast,index+1)
            elif self.spray is cast:
                self.spray = None
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot==2 and not self.space_count:
            return []
        if slot in (0,10) and (not self._inside(dest) or start==dest):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:5000,10:8000}[slot], slot)
        packets = []
        if slot==0:
            template = 343211 if self.has_buff(343201,now) else 343100
            packets.extend(self.shoot(template,start,dest,now,power,school='energy',basic=True,power=power))
        elif slot==1:
            for template in (343201,343202,343203):
                packets.extend(self._buff(template,now))
            packets.extend(self._basic_slot())
        elif slot==10:
            length = math.dist(start,dest)
            cast = self.spray = dict(generation=self.generation,power=power,
                                    direction=tuple((b-a)/length for a,b in zip(start,dest)))
            packets.extend(self._event(now,'scorpion_spray',(cast,0)))
        else:
            if self.space_count==2:
                self.space_next_charge = now+self.skill_cooldown(15000)
            self.space_count -= 1
            targets = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                       and not a.is_untargetable() and math.dist(start,a.position_at(now))<=600]
            explosions = []
            # Snapshot/consume every pre-cast mark before any damage or proc.
            for target in targets:
                mark = self.marks.get(target.id)
                if mark and self._mark_valid(target,mark,now):
                    explosions.append((target,target.position_at(now),mark['stacks']))
                    packets.extend(self._consume(target,now))
            packets.append(scene(skills=(self._skill_event(343301,start,start,self.id),)))
            ident,packet = self.add_object(343303,start)
            packets.append(packet)
            self._queue(now+300,'object_expire',ident)
            for target in targets:
                packets.extend(self.damage(power*D('2.37'),now,target=target,school='energy',lifesteal=D('.5'))[0])
                for template in (343302,343304,343305):
                    packets.extend(self._buff(template,now,target.id))
            for target,center,stacks in explosions:
                packets.extend(self._explode(target,center,stacks,power,now))
        return packets+[self._cooldown(slot)]
