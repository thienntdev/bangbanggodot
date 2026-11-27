"""Pea Shooter: resource, traps, carried bombs and player-driven Gatling mode."""
from battle_participants import friendly
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:307100, 1:307201, 2:307301, 10:307401}
GATLING_BUFFS = (307301,307302,307303,307304,307305,307306)
PHOTO_BUFFS = (307131,307132,307133)


class PeaActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.mp = int(self.stats['iMp'])
        self.e_count, self.e_next_charge = 2, 0
        self.gatling = False
        self.photo_epoch = 0
        self.photosynthesis = False
        self.traps, self.bombs = {}, {}

    def _cooldown(self, slot, changed=False):
        skill = (307321 if slot==0 else 307311) if self.gatling and slot in (0,2) else SLOTS[slot]
        end = 0 if self.gatling and slot==2 else self.cooldowns[slot]
        body = props(skill,slot,self.e_count if slot==1 else -1,end,self.e_next_charge if slot==1 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def fire_rate_packet(self):
        interval = self.fire_interval(self.clock())
        return 1560,struct.pack('<IBi',self.info['acct_id'],4,interval)

    def _resource(self, delta, now):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        before,self.mp = self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        packets = [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if before!=self.mp else []
        if self.gatling and self.mp==0:
            packets.extend(self._end_gatling(now))
        return packets

    def _activity(self, now):
        self.photo_epoch += 1
        self.photosynthesis = False
        self.info['untargetable'] = False
        packets = []
        for template in PHOTO_BUFFS:
            packets.extend(self.remove_buff(template,now))
        # Begin only after 2.5 seconds actually stationary, not from step start.
        stationary = max(now,self.motion[3]) if self.motion else now
        self._queue(stationary+2500,'photo_begin',self.generation,self.photo_epoch)
        return packets

    def on_spawn(self, now):
        self.mp = int(self.stats['iMp'])
        self.gatling = False
        packets = self._activity(now)
        self._queue(now+int(self.stats['iMpRecInterv']),'mp_regen',self.generation)
        return packets+[self.fire_rate_packet(),scene(mp=(struct.pack('<Ii',self.id,self.mp),))]

    def _end_gatling(self, now):
        self.gatling = False
        packets = []
        for template in GATLING_BUFFS:
            packets.extend(self.remove_buff(template,now))
        for slot in (0,2):
            packets.extend((self._cooldown(slot,True),self._cooldown(slot)))
        return packets+[self.fire_rate_packet()]

    def interrupt(self, now):
        packets = self._activity(now) if self.photosynthesis else []
        if not self.alive:
            if self.gatling:
                packets.extend(self._end_gatling(now))
            # User: caster death removes both planted traps and carried bombs.
            for trap in self.traps.values():
                self.arena.objects.pop(trap['id'],None)
                packets.append(scene(expired_bullets=(struct.pack('<I',trap['id']),)))
            self.traps.clear()
            for bomb in self.bombs.values():
                target = self.arena.actors[bomb['target']]
                if self.active_buffs.get((target.id,307401),(None,))[0]==bomb['buff_id']:
                    packets.extend(target.remove_buff(307401,now))
            self.bombs.clear()
        return packets

    def on_death(self):
        self.gatling = self.photosynthesis = False
        self.photo_epoch += 1
        self.info['untargetable'] = False

    def on_target_death(self, target, now):
        # User: a carried bomb is cancelled when its carrier dies.
        for token,bomb in list(self.bombs.items()):
            if bomb['target']==target.id:
                del self.bombs[token]
        return []

    def _detonate_bomb(self, bomb, carrier, now):
        if not self.alive or not carrier.alive or carrier.generation!=bomb['generation']:
            return []
        center = carrier.position_at(now)
        packets = self._buff(307403,now,carrier.id)
        # Damage may synchronously create a rescue summon (e.g. Kakashi wood).
        # This explosion owns the targets present when it began, not newborns.
        for target in list(self.arena.actors.values()):
            if target.alive and target.camp!=self.camp and math.dist(center,target.position_at(now))<=144:
                hit,lost = self.damage(bomb['power']*D('2.78'),now,target=target,school='energy',lifesteal=D('.5'))
                packets.extend(hit)
                if lost:
                    packets.extend(self._resource(25,now))
        return packets

    def update(self, now):
        packets = super().update(now)
        self.info['untargetable'] = self.photosynthesis and 32 not in self.buff_types(now)
        if self.e_next_charge and now>=self.e_next_charge:
            while self.e_count<2 and now>=self.e_next_charge:
                self.e_count += 1
                self.e_next_charge += self.skill_cooldown(8000)
            if self.e_count==2:
                self.e_next_charge = 0
            packets.append(self._cooldown(1))
        return packets

    def damage(self, raw, now, *, target=None, basic=False, **kwargs):
        target = target or self.enemy
        if basic and target.has_buff(307121,now) and target.buff_sources.get(307121)==self.id:
            raw *= 1+D('.05')*target.buff_stacks[307121]
        return super().damage(raw,now,target=target,basic=basic,**kwargs)

    def on_bullet_hit(self, flight, target, now):
        if not self.alive or self.generation!=flight['source_generation']:
            return []
        packets = self._resource(5,now)
        for template in (307121,307122):
            packets.extend(self._buff(template,now,target.id))
        return packets

    def _flight(self, flight, now):
        if flight['template']==307321:
            flight['through_walls'] = True  # User: stops at the first enemy tank.
        return super()._flight(flight,now)

    def _trap_object(self, template, pos):
        ident = self._new_id(4)
        body = struct.pack('<IIhhiBiIiH',ident,template,*pos,0,self.camp,0,self.id,0,0)
        self.arena.objects[ident] = body.hex()
        # Armed traps are hidden from enemies; sprouting and allied traps show.
        packet=(1556,struct.pack('<I',self.scene_id)+body)
        packets = [packet] if template==307201 else friendly(self,packet)
        return ident,packets

    def clear_hidden_traps(self,center,radius):
        """Falcon radar destroys armed enemy traps, without triggering damage."""
        packets = []
        for token,trap in list(self.traps.items()):
            if 'end' in trap and math.dist(center,trap['pos'])<=radius:
                del self.traps[token]
                self.arena.objects.pop(trap['id'],None)
                packets.append(scene(expired_bullets=(struct.pack('<I',trap['id']),)))
        return packets

    def _event(self, now, kind, data):
        if kind=='mp_regen':
            if not self.alive or self.generation!=data[0]:
                return []
            self._queue(now+int(self.stats['iMpRecInterv']),kind,*data)
            return self._resource(int(self.stats['iMpRecover']),now)
        if kind in ('photo_begin','photo_tick'):
            generation,epoch = data
            if not self.alive or self.generation!=generation or self.photo_epoch!=epoch:
                return []
            if self.motion and self.motion[3]>now:
                return self._activity(now)
            packets = []
            if kind=='photo_begin':
                self.photosynthesis = True
                self.info['untargetable'] = True
                for template in PHOTO_BUFFS:
                    packets.extend(self._buff(template,now))
            else:
                packets.extend(self.restore_hp(self.max_hp*D('.025'),now))
                packets.extend(self._resource(5,now))
            self._queue(now+500,'photo_tick',generation,epoch)
            return packets
        if kind=='trap_arm':
            token, = data
            trap = self.traps.get(token)
            if trap is None:
                return []
            old = trap['id']
            self.arena.objects.pop(old,None)
            trap['id'],packets = self._trap_object(307211,trap['pos'])
            trap['previous'],trap['end'] = now,now+45000
            self._queue(now,'trap_check',token)
            return [scene(expired_bullets=(struct.pack('<I',old),))]+packets
        if kind=='trap_check':
            token, = data
            trap = self.traps.get(token)
            if trap is None:
                return []
            if now>=trap['end']:
                self.traps.pop(token)
                self.arena.objects.pop(trap['id'],None)
                return [scene(expired_bullets=(struct.pack('<I',trap['id']),))]
            for target in self.arena.actors.values():
                if not target.alive or target.camp==self.camp:
                    continue
                # PropsTemplate iSelectRange=72 is the trap trigger radius.
                if actor_contact(trap['pos'],trap['pos'],target,trap['previous'],now,72) is None:
                    continue
                self.traps.pop(token)
                self.arena.objects.pop(trap['id'],None)
                packets = [scene(removed=(struct.pack('<I',trap['id']),))]
                hit,lost = self.damage(trap['power']*D('1.57'),now,target=target,school='energy',lifesteal=D('.5'))
                packets.extend(hit)
                if lost:
                    packets.extend(self._resource(25,now))
                packets.extend(self._buff(307231,now,target.id,duration=1500))
                packets.extend(self._buff(307232,now,target.id))
                return packets
            trap['previous'] = now
            self._queue(min(now+20,trap['end']),kind,token)
            return []
        if kind=='bomb':
            token, = data
            bomb = self.bombs.pop(token,None)
            if bomb is None:
                return []
            carrier = self.arena.actors[bomb['target']]
            return self._detonate_bomb(bomb,carrier,now)
        return super()._event(now,kind,data)

    def handle(self, message, payload):
        packets = super().handle(message,payload)
        now = self.clock()
        if message==501 and self.motion and self.motion[2]==now and self.motion[0]!=self.motion[1]:
            packets.extend(self._activity(now))
        return packets

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now):
            return []
        if slot==2 and self.gatling:
            return self._end_gatling(now)
        if self.cooldowns[slot]>now or slot==1 and not self.e_count:
            return []
        if slot in (0,1) and not self._inside(dest):
            return []
        if slot==0 and (start==dest or self.gatling and self.mp<10):
            return []
        if slot==1 and math.dist(start,dest)>360:
            return []
        from bot_ai import team_visible
        target = self.arena.actors.get(target_id)
        if slot==10 and (target is None or not target.alive or
                         target.camp!=self.camp and (target.is_untargetable() or not team_visible(self.arena,self,target,now))
                         or math.dist(start,target.position_at(now))>480):
            return []
        if slot==2 and self.mp<10:
            return []
        packets = self._activity(now)
        power = self.combat_stat('iEgAtk',now)
        if slot==0:
            gatling = self.gatling
            self.cooldowns[0] = now+self.fire_interval(now)
            packets.extend(self.shoot(307321 if gatling else 307100,start,dest,now,power*D('1.5'),
                                     school='energy',basic=True,speed_multiplier=1 if gatling else 1.5))
            if gatling:
                packets.extend(self._resource(-10,now))
        elif slot==1:
            self.cooldowns[1] = now+self.skill_cooldown(1000, 1)
            self.e_count -= 1
            if not self.e_next_charge:
                self.e_next_charge = now+self.skill_cooldown(8000)
            ident,objects = self._trap_object(307201,dest)
            self.traps[ident] = dict(id=ident,pos=dest,power=power)
            self._queue(now+1000,'trap_arm',ident)
            packets.extend([scene(skills=(self._skill_event(307201,start,dest),))]+objects)
        elif slot==2:
            self.cooldowns[2] = now+self.skill_cooldown(20000, 2)
            self.gatling = True
            for template in GATLING_BUFFS:
                packets.extend(self._buff(template,now))
            for changed in (0,2):
                packets.extend((self._cooldown(changed,True),self._cooldown(changed)))
            packets.append(self.fire_rate_packet())
        else:
            self.cooldowns[10] = now+self.skill_cooldown(10000, 10)
            packets.extend(self._buff(307401,now,target.id))
            if target.has_buff(307401,now):
                ident = self.active_buffs[(target.id,307401)][0]
                self.bombs[ident] = dict(target=target.id,generation=target.generation,power=power,buff_id=ident)
                self._queue(now+2000,'bomb',ident)
        return packets+[self._cooldown(slot)]
