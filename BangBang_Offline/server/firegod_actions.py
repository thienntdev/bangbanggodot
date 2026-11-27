"""Fire God: one burn clock, finite lava trails and three native melee slots."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:380100, 1:380201, 2:380301, 10:380401}
BURNS = tuple(range(380121,380126))


class FireGodActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.marks = {}
        self.ready = self.jump = self.trail = None

    def _melee(self, now):
        return next((i for i in range(3) if self.has_buff(380402+i,now)),None)

    def _cooldown(self, slot, changed=False):
        stage = self._melee(self.clock()) if slot==0 else None
        body = props(380141+stage if stage is not None else SLOTS[slot],slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _basic_slot(self):
        return [self._cooldown(0,True),self._cooldown(0)]

    def on_spawn(self, now):
        return self._buff(380101,now)+self._buff(380102,now)+self._basic_slot()

    def remove_buff(self, template, now, *, expired=False):
        existed = (self.id,template) in self.active_buffs
        packets = super().remove_buff(template,now,expired=expired)
        if existed and template in (380402,380403,380404):
            packets.extend(self._basic_slot())
        return packets

    def _valid(self, target, mark, now, final=False):
        return (self.marks.get(target.id) is mark and target.alive
                and target.generation==mark['target_generation']
                and target.buff_versions.get(mark['template'])==mark['version']
                and (now<=mark['end'] if final else now<mark['end'])
                and (final or target.has_buff(mark['template'],now)))

    def burning_count(self, now):
        return sum(self._valid(self.arena.actors[i],m,now) and m['source_generation']==self.generation
                   for i,m in self.marks.items()) if self.alive else 0

    def attr_bonus(self, attributes, now):
        value = super().attr_bonus(attributes,now)
        # V1 defines total damage, not a second +EN bonus from the display buff.
        if 5 in attributes and self.has_buff(380146,now):
            value -= D('.1')
        return value

    def _enemies(self, pos, radius, now):
        return [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                and a.is_area_targetable() and math.dist(pos,a.position_at(now))<=radius]

    def _burn(self, target, power, generation, now):
        # Stone God's burrow remains area-targetable, but that override must
        # not turn a simultaneous Doraemon/Noel stasis into a buff grant.
        if (not target.alive or target.in_stasis() or self.arena.pk and self.arena.pk['finished']
                or target.reject_buff({'nEffectType':'201'},self,now)):
            return []
        old = self.marks.get(target.id)
        valid = old and old['source_generation']==generation and self._valid(target,old,now)
        stacks = old['stacks'] if valid else 0
        next_stack = old['next_stack_at'] if valid else 0
        if now>=next_stack:
            stacks = min(5,stacks+1)
            next_stack = now+100
        packets = []
        for template in BURNS:
            if target.has_buff(template,now):
                packets.extend(target.remove_buff(template,now))
        template = BURNS[stacks-1]
        previous_version=target.buff_versions.get(template)
        packets.extend(self._buff(template,now,target.id))
        version=target.buff_versions.get(template)
        if version==previous_version or not target.has_buff(template,now) or target.buff_sources.get(template)!=self.id:return packets
        mark = old if valid else {}
        mark.update(template=template,stacks=stacks,version=version,
                    end=now+3000,next_stack_at=next_stack,power=power,
                    source_generation=generation,target_generation=target.generation)
        self.marks[target.id] = mark
        if not valid:
            self._queue(now+1000,'fire_dot',target.id,mark)
        if stacks==5 and not target.has_buff(380126,now) and not target.has_buff(380127,now):
            packets.extend(self._buff(380126,now,target.id))
            if target.has_buff(380126,now):
                self._queue(self.active_buffs[(target.id,380126)][1],'fire_confuse_end',
                            target.id,target.generation,target.buff_versions[380126])
        if self.alive and generation==self.generation:
            packets.extend(self._buff(380146,now)+self._buff(380147,now))
        return packets

    def _hit(self, target, raw, power, generation, now):
        packets,lost = self.damage(raw,now,target=target,school='energy')
        if lost:
            packets.extend(self._burn(target,power,generation,now))
        return packets

    def on_target_death(self, target, now):
        mark = self.marks.pop(target.id,None)
        if (not mark or target.generation!=mark['target_generation'] or now>mark['end']
                or target.buff_versions.get(mark['template'])!=mark['version']):
            return []
        pos = target.position_at(now)
        ident,packet = self.add_object(380160+mark['stacks'],pos)
        self._queue(now+300,'fire_death_blast',pos,mark,ident)
        return [packet]

    def _speed(self, now):
        return 0 if self.ready or self.jump else super()._speed(now)

    def blocked(self, action, now):
        return bool(self.ready or self.jump) or super().blocked(action,now)

    def update(self, now):
        packets = self.interrupt(now) if self.ready and self.skill_sealed(1,now) else []
        return packets+super().update(now)

    def interrupt(self, now):
        packets = []
        if self.ready:
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,380201)))
        if self.jump:
            self.jump = None
            self.position,self.motion,self.forced_until = self.position_at(now),None,now
            packets.append(scene(moves=(self._move_event(self.position,0,5),)))
        if not self.alive:
            self.trail = None
        return packets+self.sync_speed(now)

    def _object(self, template, pos, lifetime, now):
        ident,packet = self.add_object(template,pos)
        self._queue(now+lifetime,'object_expire',ident)
        return [packet]

    def _begin_trail(self, now, power):
        self.trail = dict(end=now+2000,previous=self.position_at(now),power=power,generation=self.generation)
        self._queue(now+300,'fire_trail',self.trail)
        return self._buff(380111,now)

    def _radial(self, pos, maximum, cast, now, *, space=False):
        packets = []
        for target in self._enemies(pos,192,now):
            d = D(str(math.dist(pos,target.position_at(now))))
            packets.extend(self._hit(target,cast['power']*maximum*(1-d/384),cast['power'],cast['generation'],now))
            if self.arena.pk and self.arena.pk['finished']:return packets
            if space:
                if d<=96:
                    packets.extend(self._buff(380312,now,target.id))
            else:
                packets.extend(self._buff(380212,now,target.id))
                if target.has_buff(380212,now):
                    self._queue(self.active_buffs[(target.id,380212)][1],'fire_slow',target.id,
                                target.generation,target.buff_versions[380212])
        return packets

    def _event(self, now, kind, data):
        if kind=='fire_dot':
            ident,mark = data
            target = self.arena.actors[ident]
            if not self._valid(target,mark,now,True):
                if self.marks.get(ident) is mark:
                    self.marks.pop(ident,None)
                return []
            packets = self.damage(mark['power']*D('.25')*mark['stacks'],now,target=target,school='true',periodic=True)[0]
            if self.arena.pk and self.arena.pk['finished']:return packets
            if self.alive and mark['source_generation']==self.generation and now<mark['end']:
                packets.extend(self._buff(380146,now)+self._buff(380147,now))
            if self.marks.get(ident) is mark:
                if now<mark['end']:
                    self._queue(now+1000,kind,ident,mark)
                else:
                    self.marks.pop(ident,None)
            return packets
        if kind=='fire_confuse_end':
            ident,generation,version = data
            target = self.arena.actors[ident]
            return self._buff(380127,now,ident) if target.alive and target.generation==generation and target.buff_versions.get(380126)==version else []
        if kind=='fire_death_blast':
            pos,mark,ident = data
            packets = self.remove_object(ident)
            for target in self._enemies(pos,168,now):
                packets.extend(self.damage(mark['power']*(1+D('.25')*(mark['stacks']-1)),now,
                                           target=target,school='true')[0])
            return packets
        if kind=='fire_trail':
            cast, = data
            if self.trail is not cast or not self.alive or self.generation!=cast['generation'] or now>cast['end']:
                return []
            pos = self.position_at(now)
            packets = []
            if math.dist(pos,cast['previous'])>0:
                ident,packet = self.add_object(380144,pos)
                packets.append(packet)
                area = dict(pos=pos,power=cast['power'],generation=cast['generation'],id=ident,end=now+6000)
                self._queue(now+1000,'fire_lava',area)
                cast['previous'] = pos
            self._queue(now+300,kind,cast)
            return packets
        if kind=='fire_lava':
            cast, = data
            packets = []
            for target in self._enemies(cast['pos'],72,now):
                packets.extend(self._burn(target,cast['power'],cast['generation'],now))
            if now<cast['end']:
                self._queue(now+1000,kind,cast)
            else:
                packets.extend(self.remove_object(cast['id']))
            return packets
        if kind=='fire_takeoff':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            if self.skill_sealed(1,now):
                return self.interrupt(now)
            self.ready,self.jump = None,cast
            start = self.position_at(now)
            dest = self.move_destination(start,cast['dest'])
            speed = max(1,math.dist(start,dest)*2)
            duration = self._set_motion(start,dest,speed,now,kind=4)
            self.forced_until = now+duration
            self._queue(now+550,'fire_land',cast)
            return self._object(380202,dest,200,now)+self._buff(380203,now)+[scene(moves=(self._move_event(self.motion[1],round(speed),4),))]
        if kind=='fire_land':
            cast, = data
            if self.jump is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            pos = self.position_at(now)
            self.jump = None
            self.position,self.motion,self.forced_until = pos,None,now
            packets = [scene(skills=(self._skill_event(380211,pos,pos,self.id),))]
            packets.extend(self._radial(pos,D('2.29'),cast,now))
            if self.arena.pk and self.arena.pk['finished']:return packets
            packets.extend(self._buff(380214,now,duration=2000)+self._buff(380215,now,duration=2000))
            return packets+self.sync_speed(now)
        if kind=='fire_slow':
            ident,generation,version = data
            target = self.arena.actors[ident]
            return self._buff(380213,now,ident,duration=1500) if target.alive and target.generation==generation and target.buff_versions.get(380212)==version else []
        if kind=='fire_space':
            cast, = data
            if not self.alive or self.generation!=cast['generation']:
                return []
            pos = self.position_at(now)
            return [scene(skills=(self._skill_event(380311,pos,pos,self.id),))]+self._radial(pos,D('7.25'),cast,now,space=True)
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot in (0,1) and (not self._inside(dest) or start==dest):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:20000,10:8000}[slot], slot)
        packets = self._begin_trail(now,power) if slot else []
        handoff = []
        if slot==0:
            stage = self._melee(now)
            if stage is None:
                return self.shoot(380100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
            packets.append(scene(skills=(self._skill_event(380141+stage,start,dest),)))
            direction = tuple(b-a for a,b in zip(start,dest))
            hit = False
            for target in self._enemies(start,216 if stage==2 else 192,now):
                delta = tuple(b-a for a,b in zip(start,target.position_at(now)))
                if stage<2 and sum(a*b for a,b in zip(delta,direction))<0:
                    continue
                more,lost = self.damage(power*D('1.5'),now,target=target,school='energy',basic=True,lifesteal=D('.75'))
                packets.extend(more)
                hit = hit or lost
            packets.extend(self.remove_buff(380402+stage,now))
            if stage<2:
                packets.extend(self._buff(380403+stage,now))
            else:
                packets.extend(self.remove_buff(380411,now))
            if hit:
                self.cooldowns[1] = now+round(max(0,self.cooldowns[1]-now)*.9)
                packets.append(self._cooldown(1))
            packets.extend(self._basic_slot())
        elif slot==1:
            dest = point_at(start,dest,min(1,480/math.dist(start,dest)))
            body,handoff = prepare_displacement(self,now,interrupt=False)
            if not handoff: body = start
            self.ready = dict(slot=1,dest=dest,power=power,generation=self.generation)
            self.position,self.motion = body,None
            packets.extend(self._object(380221,start,300,now))
            packets.append(scene(skills=(self._skill_event(380201,start,dest,ready=1),)))
            self._queue(now+300,'fire_takeoff',self.ready)
            packets.extend(self.sync_speed(now))
        elif slot==2:
            packets.extend(self._buff(380301,now)+self._buff(380302,now))
            self._queue(now+2000,'fire_space',dict(power=power,generation=self.generation))
        else:
            for template in (380402,380403,380404):
                packets.extend(self.remove_buff(template,now))
            packets.extend(self._buff(380401,now)+self._buff(380402,now)+self._buff(380411,now))
            packets.extend(self.add_shield(380413,power*D('1.5'),now)+self._basic_slot())
        return packets+[self._cooldown(slot)]+handoff
