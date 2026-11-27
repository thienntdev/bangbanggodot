"""Ghost Rider: lethal-damage form is distinct from an actual tank death."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:312100, 1:312201, 2:312301, 10:312401}
FORM_BUFFS = (312111,312114,312115,312116,312117,312118,312121)
EMBERS = tuple(range(312151,312160))


class GhostActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.soul = self.channel = None
        self.passive_ready_at = 0

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,-1,self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self, now):
        return self._buff(312101,now)

    def blocked(self, action, now):
        return super().blocked(action,now) or action=='attack' and self.soul is not None or self.channel is not None

    def _speed(self, now):
        return 0 if self.channel else super()._speed(now)

    def cc_immune(self, now, *, slow=False):
        # User: Space cannot be controlled; form description also grants immunity.
        return self.channel is not None or self.soul is not None or super().cc_immune(now,slow=slow)

    def interrupt(self, now):
        cast,self.channel = self.channel,None
        if cast is None:
            return []
        packets = [(1583,struct.pack('<II',self.id,312301))]
        target = self.arena.actors[cast['target']]
        for actor,templates in ((self,(312331,312341)),(target,(312311,312321))):
            for template in templates:
                if actor.buff_sources.get(template)==self.id:
                    packets.extend(actor.remove_buff(template,now))
        return packets+self.sync_speed(now)

    def _max_hp_packet(self):
        self.info['max_hp'] = math.ceil(self.max_hp)
        return 1560,struct.pack('<IBi',self.info['acct_id'],3,math.ceil(self.max_hp))

    def _clear_form(self, now):
        self.soul = None
        packets = []
        for template in FORM_BUFFS+EMBERS:
            if self.has_buff(template,now):
                packets.extend(self.remove_buff(template,now))
        self.max_hp = D(self.stats['iHp'])
        return packets+[self._max_hp_packet()]

    def commit_hp(self, hp, now,*,critical=False):
        if self.hp>0 and hp==0:
            if self.soul is None and now>=self.passive_ready_at:
                _,stopped = prepare_displacement(self,now,interrupt=False)
                packets = self.interrupt(now)
                self.position,self.motion = self.position_at(now),None
                self.forced_until = 0
                self.passive_ready_at = now+10000  # Original passive buff cooldown.
                self.soul = dict(begin=now,generation=self.generation,power=self.combat_stat('iEgAtk',now))
                # User chose 150% HP for the form, with a matching client HP bar.
                self.max_hp = D(self.stats['iHp'])*D('1.5')
                self.hp = self.max_hp
                self.info['hp'] = math.ceil(self.hp)
                for (owner,template) in list(self.active_buffs):
                    if owner==self.id:
                        row = table_row('BuffTemplate_table.xml',nBuffId=template)
                        cc = int(row['nEffectType']) in (30,35,36,66) or (row['nEffectType']=='201'
                             and row.get('nTypeParam')=='11' and D(row.get('fEffectValA','0'))<0)
                        if row.get('iAspect')=='-1' and cc:
                            packets.extend(self.remove_buff(template,now))
                packets.extend((self._max_hp_packet(),self._hp_packet(self.id,self.hp)))
                for template in FORM_BUFFS:
                    packets.extend(self._buff(template,now))
                self._queue(now+300,'hellfire',self.soul)
                return packets+stopped
            if self.soul:
                pos,power = self.position_at(now),self.combat_stat('iEgAtk',now)
                packets = self._clear_form(now)
                packets.extend(super().commit_hp(0,now,critical=critical))
                ident,packet = self.add_object(312411,pos)
                self._queue(now+410,'death_flame',dict(id=ident,pos=pos,power=power,generation=self.generation))
                return packets+[packet]
        return super().commit_hp(hp,now,critical=critical)

    def _ember(self, now):
        stage = max((i+1 for i,t in enumerate(EMBERS) if self.has_buff(t,now)),default=0)
        packets = []
        for template in EMBERS:
            if self.has_buff(template,now):
                packets.extend(self.remove_buff(template,now))
        if stage<9:
            return packets+self._buff(EMBERS[stage],now,duration=4000)
        hp = self.hp+D(self.stats['iHp'])*D('.5')
        packets.extend(self._clear_form(now))
        # This is the explicit form revival, not ordinary healing (which is banned).
        packets.extend(super().commit_hp(min(self.max_hp,hp),now))
        packets.extend(self._buff(312161,now))
        return packets

    def _flame(self, pos, power, now, *, death=False):
        packets,lost_any = [],False
        for target in list(self.arena.actors.values()):
            if not target.alive or target.camp==self.camp or math.dist(pos,target.position_at(now))>192:
                continue
            missing = target.max_hp-target.hp  # Both components share the impact snapshot.
            factor = 1+D('.1')*target.buff_stacks.get(312124,0) if death and target.has_buff(312124,now) else D(1)
            first,lost = self.damage(power*D('2.21')*factor,now,target=target,school='energy')
            packets.extend(first)
            second,lost2 = self.damage(missing*D('.15')*factor,now,target=target,school='true')
            packets.extend(second)
            lost_any |= lost or lost2
            packets.extend(self._buff(312403,now,target.id))
        if lost_any and not death:
            self.cooldowns[10] = max(now,self.cooldowns[10]-2000)
            packets.append(self._cooldown(10))
        return packets

    def _event(self, now, kind, data):
        if kind=='hellfire':
            soul, = data
            if self.soul is not soul or not self.alive:
                return []
            packets = []
            for target in list(self.arena.actors.values()):
                if not target.alive or target.camp==self.camp or math.dist(self.position_at(now),target.position_at(now))>168:
                    continue
                hit,lost = self.damage(soul['power']*D('.75'),now,target=target,school='energy',periodic=True)
                packets.extend(hit)
                packets.extend(self._buff(312122,now,target.id))
                if lost:
                    packets.extend(self._buff(312124,now,target.id))
                    packets.extend(self._ember(now))
                    if self.soul is not soul:
                        break
            if self.soul is soul:
                self._queue(now+300,kind,soul)
            return packets
        if kind=='death_flame':
            cast, = data
            packets = self.remove_object(cast['id'],destroyed=True)
            if cast['generation']==self.generation:
                packets.extend(self._flame(cast['pos'],cast['power'],now,death=True))
            return packets
        if kind=='judgment':
            cast, = data
            if self.channel is not cast or not self.alive:
                return []
            target = self.arena.actors[cast['target']]
            if not target.alive or target.generation!=cast['target_generation'] or math.dist(self.position_at(now),target.position_at(now))>264:
                return self.interrupt(now)
            packets = self.damage(cast['power']*D('1.5'),now,target=target,school='energy',periodic=True)[0]
            if now>=cast['end'] or not target.alive:
                return packets+self.interrupt(now)
            self._queue(now+500,kind,cast)
            return packets
        return super()._event(now,kind,data)

    def on_target_death(self, target, now):
        return self.interrupt(now) if self.channel and self.channel['target']==target.id else []

    def _flight(self, flight, now):
        if flight.get('template')!=312201:
            return super()._flight(flight,now)
        previous,begin,finish = flight['previous'],flight['begin'],flight['finish']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        hits = []
        for target in self.arena.actors.values():
            if target.alive and target.camp!=self.camp:
                hit = actor_contact(start,end,target,previous,now,54)
                if hit is not None:
                    hits.append((hit,target.id))
        if hits:
            target = self.arena.actors[min(hits)[1]]
            if self.projectile_blocked(target,now):
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            packets = []
            center,origin = self.position_at(now),target.position_at(now)
            distance = math.dist(center,origin)
            if self.alive and self.generation==flight['source_generation'] and distance>72 and not target.cc_immune(now):
                body,stopped = prepare_displacement(target,now,interrupt=False)
                if not stopped: body = origin
                target.position,target.motion = target.move_destination(body,point_at(center,origin,72/distance)),None
                packets.extend(target.interrupt(now))
                packets.extend(stopped)
                packets.append(scene(moves=(self._move_event(target.position,0,5,target.id),)))
            packets.extend(self.damage(flight['raw'],now,target=target,school='energy')[0])
            packets.extend(self._buff(312212,now,target.id))
            return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if now>=finish:
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return []

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot in (0,1) and (not self._inside(dest) or start==dest):
            return []
        target = self.arena.actors.get(target_id)
        if slot==2 and (target is None or not target.alive or target.camp==self.camp
                        or target.is_untargetable() or math.dist(start,target.position_at(now))>264):
            return []
        if slot==2:
            from bot_ai import team_visible
            if not team_visible(self.arena,self,target,now):return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:6000}[slot], slot)
        if slot in (0,1):
            packets = self.shoot(SLOTS[slot],start,dest,now,power*(D('2.35') if slot else 1),school='energy',basic=slot==0)
        elif slot==10:
            packets = [scene(skills=(self._skill_event(312401,start,start,self.id),))]
            packets.extend(self._flame(start,power,now))
        else:
            self.channel = dict(target=target.id,target_generation=target.generation,power=power,end=now+2500)
            self.position,self.motion = start,None
            packets = [scene(skills=(self._skill_event(312301,start,target.position_at(now),target.id),),
                             moves=(self._move_event(start,0,5),))]
            for actor,templates in ((target,(312311,312321)),(self,(312331,312341))):
                for template in templates:
                    packets.extend(self._buff(template,now,actor.id,duration=2500))
            packets.extend(self.sync_speed(now))
            self._queue(now+500,'judgment',self.channel)
        return packets+[self._cooldown(slot)]
