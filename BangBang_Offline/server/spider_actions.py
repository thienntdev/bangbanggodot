"""Spider Man base kit; web timing/anchor and pull geometry are user decisions."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:303100, 1:303201, 2:303301, 10:303401}


class SpiderActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.mp = int(self.stats['iMp'])
        self.r_count, self.r_next_charge = 3, 0
        self.webs, self.fields, self.web_dots = {}, {}, {}
        self.dash = None

    def _cooldown(self, slot, changed=False):
        skill = 303131 if slot==0 and self.has_buff(303113,self.clock()) else SLOTS[slot]
        body = props(skill,slot,self.r_count if slot==10 else -1,self.cooldowns[slot],self.r_next_charge if slot==10 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self, amount):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp = self.mp,max(0,min(int(self.stats['iMp']),self.mp+amount))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self, now):
        self.mp = int(self.stats['iMp'])
        self._queue(now+1000,'spider_regen',self.generation)
        packets = [scene(mp=(struct.pack('<Ii',self.id,self.mp),))]
        for template in (303101,303102):
            packets.extend(self._buff(template,now))
        return packets

    def remove_buff(self, template, now, *, expired=False):
        packets = super().remove_buff(template,now,expired=expired)
        if template==303113:
            packets.extend((self._cooldown(0,True),self._cooldown(0)))
        return packets

    def damage(self, raw, now, *, target=None, basic=False, **kwargs):
        packets,lost = super().damage(raw,now,target=target,basic=basic,**kwargs)
        if lost and not basic and self.alive:
            for template in (303121,303122):
                packets.extend(self._buff(template,now))
        return packets,lost

    def update(self, now):
        packets = super().update(now)
        if self.r_next_charge and now>=self.r_next_charge:
            while self.r_count<3 and now>=self.r_next_charge:
                self.r_count += 1
                self.r_next_charge += self.skill_cooldown(6000)
            if self.r_count==3:
                self.r_next_charge = 0
            packets.append(self._cooldown(10))
        return packets

    def interrupt(self, now):
        packets = []
        if self.dash:
            self.dash = None
            for template in (303202,303203):
                packets.extend(self.remove_buff(template,now))
        if not self.alive:
            for obj in list(self.webs.values())+list(self.fields.values()):
                packets.extend(self.remove_object(obj['id']))
            self.webs.clear()
            self.fields.clear()
            self.web_dots.clear()
        return packets

    def _web(self, pos, power, now):
        ident,packet = self.add_object(303402,pos)
        self.webs[ident] = dict(id=ident,pos=pos,power=power,end=now+8000)
        self._queue(now,'web_tick',ident)
        return [packet]

    def _web_contact(self, target, web, now):
        if target.reject_buff({'nEffectType':'201'},self,now):
            return []
        key = target.id,target.generation
        dot = self.web_dots.get(key)
        valid = dot and dot['end']>=now and target.buff_versions.get(303403)==dot['version']
        packets = []
        for template in (303403,303404,303405):
            packets.extend(self._buff(template,now,target.id))
        packets.extend(self._buff(303406,now))
        if not target.has_buff(303403,now) or target.buff_sources.get(303403)!=self.id:return packets
        if not valid:
            dot = self.web_dots[key] = dict(end=now+2000,power=web['power'],version=target.buff_versions[303403])
            self._queue(now+1000,'web_dot',key,dot)
        dot.update(end=now+2000,power=web['power'],version=target.buff_versions[303403])
        return packets

    def _clipped(self, start, dest):
        dest = self.arena.geometry.clamp_tank_position(dest)
        wall = self.arena.geometry.wall_contact(start,dest,36)
        if wall is not None:
            dest = point_at(start,dest,max(0,wall-.001))
        return tuple(round(v) for v in dest)

    def on_bullet_hit(self, flight, target, now):
        if (flight['template']!=303131 or not self.alive or not target.alive
                or self.generation!=flight['source_generation']):
            return []
        if self.arena.pk and self.arena.pk['finished']:
            return []
        # User: this separate SAFE buff protects the caster from ALL damage.
        packets = self._buff(303136,now)
        a,b = self.position_at(now),target.position_at(now)
        distance = math.dist(a,b)
        if distance<=72 or target.cc_immune(now):
            return packets
        half = (distance-72)/2
        ends = ((self,self._clipped(a,point_at(a,b,half/distance))),
                (target,self._clipped(b,point_at(b,a,half/distance))))
        for actor,dest in ends:
            origin = actor.position_at(now)
            duration = actor._set_motion(origin,dest,720,now,kind=3)
            dest = actor.motion[1]
            actor.forced_until = now+duration
            packets.extend(actor.interrupt(now))
            packets.append(scene(moves=(self._move_event(dest,720,3,actor.id),)))
            if actor is target:
                for template in (303132,303133,303134,303135):
                    packets.extend(self._buff(template,now,target.id,duration=duration))
                pull = dict(target=target.id,generation=target.generation,previous=now,end=now+duration,rooted=False)
                self._queue(now+min(20,duration),'pull_web',pull)
        return packets

    def _event(self, now, kind, data):
        if kind=='pull_web':
            pull, = data
            target = self.arena.actors[pull['target']]
            if not target.alive or target.generation!=pull['generation'] or pull['rooted']:
                return []
            start,end = target.position_at(pull['previous']),target.position_at(now)
            for web in self.webs.values():
                if circle_contact(start,end,web['pos'],web['pos'],72) is not None:
                    pull['rooted'] = True
                    return self._buff(303141,now,target.id)
            pull['previous'] = now
            if now<pull['end']:
                self._queue(min(now+20,pull['end']),kind,pull)
            return []
        if kind=='spider_regen':
            if not self.alive or self.generation!=data[0]:
                return []
            self._queue(now+1000,kind,*data)
            return self._resource(int(self.stats['iMpRecover']))
        if kind=='spider_shot':
            generation,template,start,dest,power = data
            if not self.alive or generation!=self.generation or self.blocked('attack',now):
                return []
            return self.shoot(template,start,dest,now,power*(D('1.05') if template==303401 else D('1.5')),
                              school='energy',basic=template==303131,power=power)
        if kind=='spider_dash':
            dash, = data
            if self.dash is not dash or not self.alive:
                return []
            start,end = self.position_at(dash['previous']),self.position_at(now)
            packets = []
            for target in list(self.arena.actors.values()):
                key = target.id,target.generation
                if not target.alive or target.camp==self.camp or key in dash['hits']:
                    continue
                if actor_contact(start,end,target,dash['previous'],now,72) is None:
                    continue
                dash['hits'].add(key)
                packets.extend(self.damage(dash['power']*D('2.46'),now,target=target,school='energy')[0])
                for template in (303213,303214,303215):
                    packets.extend(self._buff(template,now,target.id))
                packets.extend(self._resource(25))
                packets.extend(self.restore_hp(dash['power']*D('.75'),now))
            for token,web in list(self.webs.items()):
                if circle_contact(start,end,web['pos'],web['pos'],144) is not None:
                    del self.webs[token]
                    packets.extend(self.remove_object(web['id'],destroyed=True))
                    self.cooldowns[1] = now
                    packets.append(self._cooldown(1))
            if now>=dash['end']:
                self.dash = None
                for template in (303202,303203):
                    packets.extend(self.remove_buff(template,now))
            else:
                dash['previous'] = now
                self._queue(min(now+20,dash['end']),kind,dash)
            return packets
        if kind=='web_tick':
            token, = data
            web = self.webs.get(token)
            if web is None:
                return []
            if now>=web['end']:
                del self.webs[token]
                return self.remove_object(web['id'])
            packets = []
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(web['pos'],target.position_at(now))<=72:
                    packets.extend(self._web_contact(target,web,now))
            self._queue(min(now+100,web['end']),kind,token)
            return packets
        if kind=='web_dot':
            key,dot = data
            target = self.arena.actors[key[0]]
            if (self.web_dots.get(key) is not dot or not target.alive or target.generation!=key[1]
                    or now>dot['end'] or target.buff_versions.get(303403)!=dot['version']):
                return []
            self._queue(now+1000,kind,key,dot)
            return self.damage(dot['power']*D('.5'),now,target=target,school='energy',periodic=True)[0]
        if kind=='spider_field_open':
            token, = data
            field = self.fields.get(token)
            if field is None:
                return []
            packets = self.remove_object(field['id'],destroyed=True)
            field['id'],packet = self.add_object(303301,field['pos'])
            field['previous'] = now
            packets.append(packet)
            for offset in range(1000,6001,1000):
                self._queue(now+offset,'spider_field_damage',token)
            self._queue(now+20,'spider_field_clock',token)
            self._queue(now,'spider_field_presence',token)
            self._queue(now+6000,'spider_field_end',token)
            return packets
        if kind=='spider_field_presence':
            field = self.fields.get(data[0])
            if field is None or now>=field['end']:
                return []
            packets = []
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(field['pos'],target.position_at(now))<=300:
                    for template in (303303,303305):
                        packets.extend(self._buff(template,now,target.id))
            self._queue(now+500,kind,*data)
            return packets
        if kind=='spider_field_damage':
            field = self.fields.get(data[0])
            if field is None:
                return []
            packets = []
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(field['pos'],target.position_at(now))<=300:
                    packets.extend(self.damage(field['power']*D('.6'),now,target=target,school='energy',periodic=True)[0])
            if math.dist(field['pos'],self.position_at(now))<=300:
                packets.extend(self._resource(20))
            return packets
        if kind=='spider_field_clock':
            field = self.fields.get(data[0])
            if field is None:
                return []
            packets = []
            # Two extra ms per elapsed ms while the caster is inside its field.
            if math.dist(field['pos'],self.position_at(now))<=300:
                extra = (now-field['previous'])*2
                for slot in (1,10):
                    if self.cooldowns[slot]>now:
                        self.cooldowns[slot] = max(now,self.cooldowns[slot]-extra)
                if self.r_next_charge:
                    self.r_next_charge -= extra
                packets.extend(self.update(now))
                if (now-field['begin'])%500==0:
                    packets.extend(self._cooldown(s) for s in (1,10))
            field['previous'] = now
            if now<field['end']:
                self._queue(min(now+20,field['end']),kind,*data)
            return packets
        if kind=='spider_field_end':
            packets = self._event(now,'spider_field_clock',data)
            field = self.fields.pop(data[0],None)
            return packets+self.remove_object(field['id'],destroyed=True) if field else packets
        return super()._event(now,kind,data)

    def _flight(self, flight, now):
        if flight.get('template')!=303401:
            return super()._flight(flight,now)
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        wall = self.arena.geometry.wall_contact(start,end)
        candidates = []
        for target in self.arena.actors.values():
            if target.alive and target.camp!=self.camp:
                hit = actor_contact(start,end,target,previous,now)
                if hit is not None and (wall is None or hit<wall):
                    candidates.append((hit,target.id))
        contact = min(candidates) if candidates else None
        packets = []
        if contact:
            target = self.arena.actors[contact[1]]
            if self.projectile_blocked(target,now):
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            packets.extend(self.damage(flight['raw'],now,target=target,school='energy')[0])
        if contact or wall is not None or now>=finish:
            pos = point_at(start,end,contact[0] if contact else wall if wall is not None else 1)
            packets.append(scene(blown_bullets=(struct.pack('<I',flight['id']),)))
            if self.alive and self.generation==flight['source_generation']:
                packets.extend(self._web(tuple(round(v) for v in pos),flight['power'],now))
            return packets
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return packets

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot!=2 and (not self._inside(dest) or start==dest):
            return []
        if slot==1 and (self.mp<25 or self.dash) or slot==10 and not self.r_count:
            return []
        if slot==0 and self.has_buff(303112,now):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:1500}[slot], slot)
        packets = self._buff(303111,now) if slot else []
        if slot==0:
            if self.has_buff(303113,now):
                packets.extend(self.remove_buff(303113,now))
                self._queue(now+100,'spider_shot',self.generation,303131,start,dest,power)
            else:
                packets.extend(self.shoot(303100,start,dest,now,power,school='energy',basic=True))
        elif slot==10:
            self.r_count -= 1
            if not self.r_next_charge:
                self.r_next_charge = now+self.skill_cooldown(6000)
            for template in (303112,303113):
                packets.extend(self._buff(template,now))
            packets.extend((self._cooldown(0,True),self._cooldown(0)))
            self._queue(now+100,'spider_shot',self.generation,303401,start,dest,power)
        elif slot==1:
            packets.extend(self._resource(-25))
            dest = self._clipped(start,point_at(start,dest,360/math.dist(start,dest)))
            # MOVE_DASH (3), not MOVE_TRANSFER (2): the native/HTML5 self
            # consumer ignores transfer as a walking update. Keep the stored
            # kind identical to the wire kind so reconnect also resumes a dash.
            duration = self._set_motion(start,dest,720,now,kind=3)
            dest = self.motion[1]
            self.forced_until = now+duration
            self.dash = dict(power=power,previous=now,end=now+duration,hits=set())
            for template in (303202,303203):
                packets.extend(self._buff(template,now,duration=duration))
            packets.append(scene(moves=(self._move_event(dest,720,3),),skills=(self._skill_event(303201,start,dest),)))
            self._queue(now+min(20,duration),'spider_dash',self.dash)
        else:
            ident,packet = self.add_object(303311,start)
            self.fields[ident] = dict(id=ident,pos=start,power=power,begin=now+500,end=now+6500,previous=now+500)
            self._queue(now+500,'spider_field_open',ident)
            packets.extend((scene(skills=(self._skill_event(303301,start,start,self.id),)),packet))
        return packets+[self._cooldown(slot)]
