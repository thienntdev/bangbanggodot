"""Black Panther: two-stage carry, mouse-aimed bombs and one Space finale."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene, stop_move
from melee_common import prepare_displacement

SLOTS = {0:375100, 1:375201, 2:375301, 10:375401}
OWN_BUFFS = (375202,375211,375220,375404,375405,375406,375407,
             375302,375305,375306,375313,375321,375330)


class PantherActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.combo = None

    def _cooldown(self, slot, changed=False):
        body = props(SLOTS[slot],slot,-1,self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self, now):
        return self._buff(375101,now)+self._buff(375102,now)

    def blocked(self, action, now):
        return super().blocked(action,now) or self.combo is not None

    def _speed(self, now):
        return 0 if self.combo else super()._speed(now)

    def cc_immune(self, now, *, slow=False):
        return bool(self.combo and self.combo['kind']=='space') or super().cc_immune(now,slow=slow)

    def _valid(self, cast):
        return self.combo is cast and self.alive and self.generation==cast['generation']

    def _enemies(self, position, radius, now):
        from bot_ai import team_visible
        return [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                and not a.is_untargetable() and math.dist(position,a.position_at(now))<=radius and team_visible(self.arena,self,a,now)]

    def _object(self, template, position, duration, now):
        ident,packet = self.add_object(template,position)
        kind = 'panther_visual_remove' if template==375326 else 'object_expire'
        self._queue(now+duration,kind,ident)
        return [packet]

    def _finish(self, now):
        cast,self.combo = self.combo,None
        if cast is None:
            return []
        self.position,self.motion,self.forced_until = self.position_at(now),None,now
        if cast['kind']=='space':
            self.info['untargetable'] = cast['was_untargetable']
            self.info['damage_immune'] = cast['was_immune']
        packets = [scene(moves=(self._move_event(self.position,0,5),))]
        finished = self.arena.pk and self.arena.pk['finished']
        for ident,held in cast.get('held',{}).items():
            target = self.arena.actors[ident]
            if target.generation==held['generation'] and (target.motion==held['motion']
                    or finished and target.motion is None):
                target.position,target.motion,target.forced_until = target.position_at(now),None,now
                packets.append(scene(moves=(target._move_event(target.position,0,5),)))
        for template in OWN_BUFFS:
            if (self.id,template) in self.active_buffs:
                packets.extend(self.remove_buff(template,now))
        return packets if finished else packets+self.sync_speed(now)

    def interrupt(self, now):
        return self._finish(now)

    def _motion(self, cast, start, dest, speed, now, kind):
        self._set_motion(start,dest,speed,now,kind)
        self.forced_until = self.motion[3]
        cast['previous'] = now
        self._queue(min(now+20,self.motion[3]),'panther_dash',cast)
        return [scene(moves=(self._move_event(self.motion[1],speed,kind),))]

    def _dash(self, cast, now):
        if not self._valid(cast):
            return []
        if not self.motion:
            return self._finish(now)
        start,end = self.position_at(cast['previous']),self.position_at(now)
        packets = []
        if cast['phase'] in ('e_first','e_second'):
            contacts = []
            for target in self.arena.actors.values():
                if (target.alive and target.camp!=self.camp and not target.is_untargetable()
                        and (target.id,target.generation) not in cast['hits']):
                    hit = actor_contact(start,end,target,cast['previous'],now)
                    if hit is not None:
                        contacts.append((hit,target.id))
            for hit,ident in sorted(contacts):
                target = self.arena.actors[ident]
                cast['hits'].add((ident,target.generation))
                if cast['phase']=='e_first':
                    impact = tuple(round(v) for v in point_at(start,end,hit))
                    # E can be interrupted during its wait; that stop must already be clear.
                    self.position,self.motion,self.forced_until = self.stop_position(now,impact),None,now
                    cast.update(phase='e_wait',target=ident,target_generation=target.generation)
                    packets.extend(self.remove_buff(375202,now))
                    packets.append(stop_move(self.scene_id,self.id,self.position))
                    packets.append(scene(moves=(self._move_event(self.position,0,5),),
                        skills=(self._skill_event(375210,impact,target.position_at(now),ident),)))
                    packets.extend(self.damage(cast['power']*D('1.25'),now,target=target)[0])
                    if self.arena.pk and self.arena.pk['finished']:
                        return packets+self._finish(now)
                    if not self._valid(cast):
                        return packets
                    packets.extend(self._buff(375211,now))
                    self._queue(now+200,'panther_e_second',cast)
                    return packets
                # Carry along the remaining dash; one impact per victim/life.
                if not target.cc_immune(now):
                    packets.extend(target.interrupt(now))
                    target_start = target.position_at(now)
                    target._set_motion(target_start,self.motion[1],792,now,1)
                    target.forced_until = target.motion[3]
                    cast['held'][ident] = dict(generation=target.generation,motion=target.motion)
                    packets.append(scene(moves=(target._move_event(target.motion[1],792,1),)))
                packets.extend(self.damage(cast['power']*D('1.65'),now,target=target)[0])
                if self.arena.pk and self.arena.pk['finished']:
                    return packets+self._finish(now)
                if not self._valid(cast):
                    return packets
        if now>=self.motion[3]:
            if cast['phase']=='r_jump':
                self.position,self.motion,self.forced_until = self.position_at(now),None,now
                cast['phase'] = 'r_wait_bombs'
                return packets+[scene(moves=(self._move_event(self.position,0,5),))]
            return packets+self._finish(now)
        cast['previous'] = now
        self._queue(min(now+20,self.motion[3]),'panther_dash',cast)
        return packets

    def _e_second(self, cast, now):
        if not self._valid(cast):
            return []
        target = self.arena.actors[cast['target']]
        start = self.position_at(now)
        if not target.alive or target.generation!=cast['target_generation'] or target.is_untargetable():
            candidates = self._enemies(start,336,now)
            if not candidates:
                return self._finish(now)
            target = min(candidates,key=lambda a:(math.dist(start,a.position_at(now)),a.id))
        direction = target.position_at(now)
        if direction==start:
            direction = cast['aim']
        dest = point_at(start,direction,240/max(1,math.dist(start,direction)))
        cast.update(phase='e_second',hits=set(),held={})
        packets = self.remove_buff(375211,now)+self._buff(375220,now)
        return packets+self._motion(cast,start,dest,792,now,3)

    def _r_hit(self, cast, target, now):
        if not self._valid(cast):
            return []
        start = self.position_at(now)
        self.position,self.motion = self.move_destination(start,target.position_at(now)),None
        packets = [scene(moves=(self._move_event(self.position,0,5),))]
        packets.extend(self.damage(cast['power']*D('1.45'),now,target=target)[0])
        if self.arena.pk and self.arena.pk['finished']:
            return packets+self._finish(now)
        if not self._valid(cast):
            return packets
        packets.extend(self._buff(375430,now,target.id))
        for template in (375404,375405,375407):
            # Native auto-move removal resumes held walking immediately. Keep
            # its invisible marker until _finish: bombs follow the jump by
            # 100 ms, and server walking remains locked in that interval.
            packets.extend(self._buff(template,now,**({'duration':-1} if template==375407 else {})))
        cast['phase'] = 'r_jump'
        dx,dy = cast['start'][0]-self.position[0],cast['start'][1]-self.position[1]
        distance = max(1,math.hypot(dx,dy))
        dest = self.move_destination(self.position,(self.position[0]+336*dx/distance,self.position[1]+336*dy/distance))
        # User-approved interpretation: the raw 700 is the jump duration.
        speed = max(1,round(math.dist(self.position,dest)*1000/700))
        packets.extend(self._motion(cast,self.position,dest,speed,now,4))
        self._queue(now+300,'panther_r_aim',cast)
        self._queue(now+800,'panther_bombs',cast)
        return packets

    def _bombs(self, cast, now):
        if not self._valid(cast):
            return []
        start = self.position_at(now)
        dest = cast['aim']
        if start==dest:
            dest = (start[0]+1,start[1])
        angle = math.atan2(dest[1]-start[1],dest[0]-start[0])
        packets = []
        for offset in (-45,-22.5,0,22.5,45):
            rad = angle+math.radians(offset)
            aim = (round(start[0]+336*math.cos(rad)),round(start[1]+336*math.sin(rad)))
            packets.extend(self.shoot(375420,start,aim,now,cast['power']*D('1.94'),school='physical',power=cast['power']))
        return packets+self._finish(now)

    def _flight(self, flight, now):
        if flight['template']==375100:
            return super()._flight(flight,now)
        if flight['template']==375310:
            if now>=flight['finish']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            self._queue(flight['finish'],'flight',flight)
            return []  # Presentation only; the Space schedule owns the hit.
        if flight['template']==375401:
            cast = flight['context']
            target = self.arena.actors[flight['target']]
            if (not self._valid(cast) or not target.alive or target.is_untargetable()
                    or target.generation!=flight['target_generation']):
                packets = self._finish(now) if self.combo is cast else []
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start,dest = flight['pos'],target.position_at(now)
            end = point_at(start,dest,min(1,flight['speed']*(now-flight['previous'])/1000/max(1,math.dist(start,dest))))
            packets = []
            if dest!=flight['end']:
                packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(x) for x in (*start,*dest)))))
                flight['end'] = dest
            flight['pos'] = end
            if circle_contact(start,end,target.position_at(flight['previous']),dest) is not None:
                packets.extend(self._finish(now) if self.projectile_blocked(target,now) else self._r_hit(cast,target,now))
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            if now>=flight['finish']:
                return packets+self._finish(now)+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        else:
            begin,finish,previous = flight['begin'],flight['finish'],flight['previous']
            start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
            end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
            contacts = []
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp:
                    hit = actor_contact(start,end,target,previous,now)
                    if hit is not None:
                        contacts.append((hit,target.id))
            wall = self.arena.geometry.wall_contact(start,end)
            contact = min(contacts) if contacts else None
            at_target = contact and (wall is None or contact[0]<wall)
            if at_target and self.projectile_blocked(self.arena.actors[contact[1]],now):
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            if at_target or wall is not None or now>=finish:
                pos = point_at(start,end,contact[0] if at_target else wall if wall is not None else 1)
                pos = tuple(round(x) for x in pos)
                packets = self._object(375420,pos,100,now)
                for target in list(self.arena.actors.values()):
                    if target.alive and target.camp!=self.camp and math.dist(pos,target.position_at(now))<=96:
                        packets.extend(self.damage(flight['raw'],now,target=target)[0])
                        packets.extend(self._buff(375421,now,target.id))
                return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
            packets = []
        flight['previous'] = now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _space_final(self, cast, now):
        if not self._valid(cast) or cast.get('final'):
            return []
        cast['final'] = True
        center = self.position_at(now)
        packets = self._finish(now)
        packets.extend(self._object(375323,center,300,now)+self._object(375326,center,100,now))
        for target in list(self.arena.actors.values()):
            if not target.alive or target.camp==self.camp or math.dist(center,target.position_at(now))>144:
                continue
            raw = cast['power']*D('3.5')+(target.max_hp-target.hp)*D('.15')
            packets.extend(self.damage(raw,now,target=target)[0])
            if self.arena.pk and self.arena.pk['finished']:
                return packets
            if target.alive and not target.cc_immune(now):
                packets.extend(target.interrupt(now))
                pos = target.position_at(now)
                aim = pos if pos!=center else cast['aim']
                if aim==center:
                    aim = (center[0]+1,center[1])
                dx,dy = aim[0]-center[0],aim[1]-center[1]
                length = math.hypot(dx,dy)
                target._set_motion(pos,(pos[0]+144*dx/length,pos[1]+144*dy/length),720,now,1)
                target.forced_until = target.motion[3]
                packets.append(scene(moves=(target._move_event(target.motion[1],720,1),)))
            packets.extend(self._buff(375309,now,target.id))
        return packets

    def _space_hit(self, cast, index, now):
        if not self._valid(cast):
            return []
        center = self.position_at(now)
        target = self.arena.actors[cast['target']]
        if index or not target.alive or target.generation!=cast['target_generation']:
            candidates = self._enemies(center,408,now)
            if not candidates:
                return self._space_final(cast,now)
            target = self.arena.rng.choice(candidates)
        if target.is_untargetable():
            return self._space_final(cast,now)
        pos = target.position_at(now)
        self.position,self.motion = self.blink_destination(center,pos),None
        cast.update(target=target.id,target_generation=target.generation,resolving=True)
        packets = [scene(moves=(self._move_event(self.position,0,5),))]
        if index==0:
            packets.extend(self.remove_buff(375302,now))
            packets.extend(self._buff(375305,now))
            packets.extend(self._buff(375306,now,duration=3800))
        else:
            # Original follow-up slash has a projectile exhibit. It is a visual
            # event only; this scheduled strike owns the damage exactly once.
            packets.extend(self.shoot(375310,center,pos,now,0,school='physical',target=target))
        packets.extend(self._buff(375304 if index==0 else 375312,now,target.id))
        for victim in list(self.arena.actors.values()):
            if victim.alive and victim.camp!=self.camp and math.dist(pos,victim.position_at(now))<=72:
                packets.extend(self.damage(cast['power']*D('2.22'),now,target=victim)[0])
                packets.extend(self._buff(375309,now,victim.id))
        cast['resolving'] = False
        if self._valid(cast) and not self._enemies(pos,408,now):
            packets.extend(self._space_final(cast,now))
        return packets

    def on_target_death(self, target, now):
        cast = self.combo
        if (cast and cast['kind']=='space' and not cast.get('resolving')
                and target.id==cast['target'] and not self._enemies(self.position_at(now),408,now)):
            return self._space_final(cast,now)
        return []

    def _event(self, now, kind, data):
        if kind=='panther_visual_remove':
            # Native presentation prop375326 begins its impact SWF on remove;
            # the actual burst has already run and is never repeated here.
            return self.remove_object(data[0],destroyed=True)
        if kind.startswith('panther_'):
            cast = data[0]
            if not self._valid(cast):
                return []
            if kind=='panther_dash':
                return self._dash(cast,now)
            if kind=='panther_e_second':
                return self._e_second(cast,now)
            if kind=='panther_r_aim':
                return self._buff(375406,now)
            if kind=='panther_bombs':
                return self._bombs(cast,now)
            if kind=='panther_space_hit':
                return self._space_hit(cast,data[1],now)
            if kind=='panther_space_final_ready':
                return self._buff(375313,now)
            if kind=='panther_space_final':
                return self._space_final(cast,now)
        return super()._event(now,kind,data)

    def handle(self, message, payload):
        if message==514:
            now = self.clock()
            packets = self.arena.tick(now)
            if not self.arena.input_open(now,self):return packets
            if len(payload)==8 and self.combo and self.combo['kind']=='r' and self.alive:
                scene_id,x,y = struct.unpack('<Ihh',payload)
                if scene_id==self.scene_id and (x,y)!=self.position_at(now):
                    self.combo['aim'] = (x,y)  # Original client projects 2000 units.
            return packets
        return super().handle(message,payload)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        target = self.arena.actors.get(target_id)
        if slot in (2,10):
            from bot_ai import team_visible
            if (not target or not target.alive or target.camp==self.camp or target.is_untargetable()
                    or math.dist(start,target.position_at(now))>(240 if slot==2 else 408)
                    or not team_visible(self.arena,self,target,now)):
                return []
        elif not self._inside(dest) or start==dest:
            return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+(self.skill_cooldown({1:8000,2:25000,10:6000}.get(slot,self.fire_interval(now)), slot))
        packets = [self._cooldown(slot)]
        if slot==0:
            return packets+self.shoot(375100,start,dest,now,power,school='physical',basic=True,power=power)
        body,handoff = start,[]
        if slot==1:
            body,handoff = prepare_displacement(self,now,interrupt=False)
            if not handoff: body = start
        cast = self.combo = dict(kind={1:'e',2:'space',10:'r'}[slot],generation=self.generation,
                                 start=start,aim=dest,power=power,begin=now)
        self.position,self.motion = body,None
        if slot==1:
            cast.update(phase='e_first',hits=set())
            dest = point_at(start,dest,408/math.dist(start,dest))
            packets.extend(self._buff(375202,now))
            packets.extend(handoff)
            packets.extend(self._motion(cast,body,dest,840,now,3))
        elif slot==10:
            cast['phase'] = 'r_flight'
            packets.extend(self.shoot(375401,start,target.position_at(now),now,0,
                school='physical',target=target,power=power,through_walls=True,context=cast))
        else:
            cast.update(target=target.id,target_generation=target.generation,
                        was_immune=self.info.get('damage_immune',False),
                        was_untargetable=self.info.get('untargetable',False))
            self.position,self.motion = start,None
            self.info['damage_immune'] = self.info['untargetable'] = True
            packets.extend(self._buff(375302,now)+self._buff(375308,now,target.id))
            packets.extend(self._object(375307,start,700,now))
            for index in range(6):
                self._queue(now+600+index*500,'panther_space_hit',cast,index)
            self._queue(now+3800,'panther_space_final_ready',cast)
            self._queue(now+4400,'panther_space_final',cast)
        return packets+self.sync_speed(now)
