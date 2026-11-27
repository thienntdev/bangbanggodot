"""Werewolf: separate passive clocks and server-owned taunt attacks."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene, stop_move
from melee_common import aimed, enemies, prepare_displacement

SLOTS = {0:314100, 1:314201, 2:314301, 10:314401}


class WolfActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.r_count,self.r_next_charge = 2,0
        self.passive_ready_at = self.counter_ready_at = 0
        self.dash = None
        self.taunts = {}

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,self.r_count if slot==10 else -1,
                          self.cooldowns[slot],self.r_next_charge if slot==10 else 0)+struct.pack('<I',self.id)

    def on_spawn(self, now):
        self.passive_ready_at = self.counter_ready_at = 0
        packets = []
        for t in (314101,314102,314103,314104):packets.extend(self._buff(t,now))
        return packets

    def update(self, now):
        packets = []
        while self.r_next_charge and self.r_next_charge<=now:
            self.r_count = min(2,self.r_count+1)
            self.r_next_charge = self.r_next_charge+self.skill_cooldown(8000) if self.r_count<2 else 0
            packets.append(self._cooldown(10))
        return packets+super().update(now)

    def blocked(self, action, now):
        return bool(self.dash) or super().blocked(action,now)

    def _end_dash(self, now, *, hit=False):
        if not self.dash:return []
        cast,self.dash = self.dash,None
        self.position,self.motion,self.forced_until = self.position_at(now),None,now
        return [scene(moves=(self._move_event(self.position,0,5),),
                      **{'blown_bullets' if hit else 'expired_bullets':(struct.pack('<I',cast['bullet']),)})]+self.remove_buff(314202,now)

    def _end_taunt(self, target, cast, now):
        self.taunts.pop(target.id,None)
        if target.generation!=cast['target_generation'] or target.buff_sources.get(314303)!=self.id:return []
        if target.has_buff(314303,now) and target.buff_versions.get(314303)!=cast['version']:return []
        packets = []
        for template in (314303,314304,314305):packets.extend(target.remove_buff(template,now))
        if target.motion and target.motion==cast.get('motion'):
            target.position,target.motion,target.forced_until = target.position_at(now),None,now
            packets.append(scene(moves=(self._move_event(target.position,0,5,target.id),)))
        return packets

    def interrupt(self, now):
        packets = self._end_dash(now)
        if not self.alive:
            for ident,cast in list(self.taunts.items()):
                target = self.arena.actors.get(ident)
                if target:packets.extend(self._end_taunt(target,cast,now))
        return packets

    def _hit(self, target, raw, now, *, own_ratio=0, space=False, basic=False, current=True, reflected=False):
        missing,target_hp = self.max_hp-self.hp,target.hp
        vamp = D('.25')+(D('.25')*missing/self.max_hp if not basic else 0)
        packets,lost = self.damage(raw,now,target=target,basic=basic,reflected=reflected,
                                   lifesteal=vamp if current else 0)
        if own_ratio and target.alive:
            hit,extra_lost = self.damage(missing*D(own_ratio),now,target=target,school='true',
                                         lifesteal=vamp if current else 0,reflected=reflected)
            packets.extend(hit);lost = lost or extra_lost
        bonus = space or not basic and lost and current and now>=self.passive_ready_at
        if bonus:
            if current:self.passive_ready_at=now+250
            if target.alive:
                packets.extend(self.damage(target_hp*D('.05'),now,target=target,school='true',
                                           lifesteal=vamp if current else 0,reflected=reflected)[0])
            if current:packets.extend(self._buff(314112,now))
        return packets

    def _r(self, now, *, reflected=False):
        packets = [scene(skills=(self._skill_event(314401,self.position_at(now),self.position_at(now)),))]
        power = self.combat_stat('iAttack',now)
        for target in enemies(self,area=True):
            if math.dist(self.position_at(now),target.position_at(now))<=168:
                packets.extend(self._hit(target,power,now,own_ratio='.05',reflected=reflected))
        return packets

    def on_basic_damage(self, source, hit, now):
        if not self.alive or now<self.counter_ready_at:return []
        self.counter_ready_at = now+250
        if self.arena.rng.random()>=.25:return []
        self._queue(now+50,'wolf_counter',self.generation)
        return self._buff(314121,now)+self._buff(314122,now)

    def _taunt(self, target, now):
        if target.cc_immune(now):return []
        packets = self._buff(314303,now,target.id,duration=3000)
        if not target.has_buff(314303,now):return packets
        end = target.active_buffs[(target.id,314303)][1]
        for t in (314304,314305):packets.extend(self._buff(t,now,target.id,duration=3000))
        _,stopped = prepare_displacement(target,now)
        packets.extend(stopped)
        cast = dict(target=target.id,target_generation=target.generation,generation=self.generation,
                    end=end,version=target.buff_versions[314303])
        self.taunts[target.id] = cast
        return packets+self._taunt_step(cast,now)

    def _taunt_step(self, cast, now):
        target = self.arena.actors.get(cast['target'])
        if not target or self.taunts.get(target.id) is not cast:return []
        if (not self.alive or self.generation!=cast['generation'] or not target.alive
                or target.generation!=cast['target_generation'] or now>=cast['end']
                or not target.has_buff(314303,now) or target.buff_versions.get(314303)!=cast['version']):
            return self._end_taunt(target,cast,now)
        packets = []
        pos,dest = target.position_at(now),self.position_at(now)
        npc=bool(target.info.get('npc_template'))
        if (not npc or getattr(target,'taunt_mobile',False)) and not 30 in target.buff_types(now) and not 36 in target.buff_types(now):
            distance = math.dist(pos,dest)
            if distance>72:
                speed = max(1,round(int(target.stats['iSpeed'])*.15))
                # Another source may replace this taunt's previous step with
                # a wall-crossing push. Keep the contact sample above, but
                # resolve that motion before its origin is replaced here.
                origin,stopped = prepare_displacement(target,now,interrupt=False)
                packets.extend(stopped)
                remaining = max(0,math.dist(origin,dest)-72)
                end = aimed(origin,dest,min(remaining,speed*min(100,cast['end']-now)/1000))
                elapsed = target._set_motion(origin,end,speed,now,1)
                target.forced_until = now+elapsed
                cast['motion'] = target.motion
                packets.append(scene(moves=(self._move_event(target.motion[1],speed,1,target.id),)))
        # Native type88 does not send a client attack command. A single server
        # cast owns the attack; ordinary player/bot commands remain blocked.
        if (not self.is_untargetable() and math.dist(pos,dest)<=int(target.stats['nFireRange'])
                and self.arena.geometry.wall_contact(pos,dest) is None):
            self.arena.forced_basic_actor = target.id
            try:
                if npc:
                    attack=getattr(target,'taunt_attack',None)
                    if attack:packets.extend(attack(self,now))
                else:packets.extend(target.cast(0,pos,dest,self.id,now))
            finally:self.arena.forced_basic_actor = None
        self._queue(min(now+100,cast['end']),'wolf_taunt',cast)
        return packets

    def _flight(self, flight, now):
        # Keep the original projectile's contact/wall behavior, but heal from
        # actual HP lost at impact rather than an unconditional fixed amount.
        if flight['template']==314100:
            flight['lifesteal']=D('.25') if self.alive and self.generation==flight['source_generation'] else 0
        return super()._flight(flight,now)

    def _event(self, now, kind, data):
        if kind=='wolf_counter':
            return self._r(now,reflected=True) if self.alive and self.generation==data[0] else []
        if kind=='wolf_taunt':return self._taunt_step(data[0],now)
        if kind=='wolf_dash':
            cast, = data
            if self.dash is not cast or not self.alive:return []
            start,end = self.position_at(cast['previous']),self.position_at(now)
            contacts = [(h,t.id,t) for t in enemies(self)
                        if (h:=actor_contact(start,end,t,cast['previous'],now)) is not None]
            if contacts:
                contact,_,target = min(contacts,key=lambda x:x[:2])
                impact = tuple(round(x) for x in point_at(start,end,contact))
                # Resolve an early hit from the whole dash before dropping its origin.
                self.position = self.stop_position(now,impact)
                self.motion = None
                packets = [stop_move(self.scene_id,self.id,self.position)]
                packets.extend(self._end_dash(now,hit=True))
                packets.extend(self._hit(target,cast['power']*D('1.67'),now,own_ratio='.05'))
                for t in (314212,314213):packets.extend(self._buff(t,now,target.id))
                packets.append(scene(skills=(self._skill_event(314211,impact,target.position_at(now),target.id),)))
                return packets
            if not self.motion or now>=self.motion[3]:return self._end_dash(now)
            cast['previous']=now
            self._queue(min(now+20,self.motion[3]),kind,cast)
            return []
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot==10 and not self.r_count or slot in (0,1) and start==dest:return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:30000,10:4000}[slot], slot)
        if slot==0:return self.shoot(314100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        if slot==10:
            self.r_count-=1
            if not self.r_next_charge:self.r_next_charge=now+self.skill_cooldown(8000)
            return self._r(now)+[self._cooldown(10)]
        packets = [scene(skills=(self._skill_event(SLOTS[slot],start,dest),))]
        if slot==1:
            end = aimed(start,dest,360,fixed=True)
            origin,stopped = prepare_displacement(self,now,interrupt=False)
            origin = origin if stopped else start
            elapsed = self._set_motion(origin,end,720,now,3)
            self.forced_until=now+elapsed
            self.dash=dict(previous=now,power=power,bullet=self._new_id(2))
            packets.extend(self._buff(314202,now))
            packets.extend(stopped)
            # The native dash declares bullet exhibit472 (including its use
            # sound). This is presentation only; the dash owns all damage.
            packets.append(scene(fires=(struct.pack('<IIhhhhhI',self.dash['bullet'],self.id,
                                                    *start,*self.motion[1],720,314201),)))
            packets.append(scene(moves=(self._move_event(self.motion[1],720,3),)))
            self._queue(now+min(20,elapsed),'wolf_dash',self.dash)
        else:
            for target in enemies(self,area=True):
                if math.dist(start,target.position_at(now))<=192:
                    packets.extend(self._hit(target,power*D('2.68'),now,own_ratio='.1',space=True))
                    if self.arena.pk and self.arena.pk['finished']:
                        break
                    if target.alive:packets.extend(self._taunt(target,now))
        return packets+[self._cooldown(slot)]
