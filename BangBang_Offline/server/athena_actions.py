"""Athena base kit; Q83 and the user-approved three-second death floor."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:359100,1:359201,2:359301,10:359401}


class AthenaActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp = int(self.stats['iMp'])
        self.r_count,self.r_next_charge = 3,0
        self.ready = None

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp = self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,self.r_count if slot==10 else -1,
                          self.cooldowns[slot],self.r_next_charge if slot==10 else 0)+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.mp = int(self.stats['iMp'])
        self._queue(now+3000,'athena_mp',self.generation)
        return self._buff(359101,now)+[scene(mp=(struct.pack('<Ii',self.id,self.mp),))]

    def update(self,now):
        packets = []
        if self.ready and self.skill_sealed(1,now):
            packets.extend(self.interrupt(now))
        while self.r_next_charge and self.r_next_charge<=now:
            self.r_count = min(3,self.r_count+1)
            self.r_next_charge = self.r_next_charge+self.skill_cooldown(6000) if self.r_count<3 else 0
            packets.append(self._cooldown(10))
        return packets+super().update(now)

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def interrupt(self,now):
        if not self.ready:
            return []
        self.ready = None
        return [(1583,struct.pack('<II',self.id,359201))]+self.sync_speed(now)

    def _passive(self,power,now):
        # SelectLimit5 = teammate + tank, no NOT_SELF bit: owner is eligible.
        allies = [a for a in self.arena.actors.values() if a.alive and a.camp==self.camp
                  and a.id>>26==0 and math.dist(self.position_at(now),a.position_at(now))<=300]
        packets = []
        if allies:
            target = min(allies,key=lambda a:(a.hp/a.max_hp,a.id))
            packets.append(scene(skills=(self._skill_event(359111,self.position_at(now),target.position_at(now),target.id),)))
            packets.extend(self._buff(359112,now,target.id)+target.restore_hp(power*D('1.5'),now))
        packets.extend(self._buff(359113,now))
        for i in range(1,6):
            self._queue(now+400*i,'athena_hot',self.generation,self.buff_versions[359113],power*D('.3'))
        return packets

    def _event(self,now,kind,data):
        if kind=='athena_mp':
            if not self.alive or data[0]!=self.generation:
                return []
            self._queue(now+3000,kind,*data)
            return self._resource(10)
        if kind=='athena_hot':
            generation,version,amount = data
            return self.restore_hp(amount,now) if self.alive and generation==self.generation and self.buff_versions.get(359113)==version else []
        if kind=='athena_e':
            cast, = data
            if self.ready is not cast:
                return []
            if not self.alive or self.skill_sealed(1,now) or super().blocked('attack',now):
                return self.interrupt(now)
            self.ready = None
            target = self.arena.actors.get(cast['target'])
            packets = self.sync_speed(now)
            if not target or not target.alive or target.generation!=cast['target_generation']:
                return packets
            packets.append(scene(skills=(self._skill_event(359201,self.position_at(now),target.position_at(now),target.id),)))
            packets.extend(target.cleanse(now))
            previous_version = target.buff_versions.get(359201,0)
            packets.extend(target.add_shield(359201,cast['max_hp']*D('.3'),now,caster=self))
            if target.has_buff(359201,now) and target.buff_versions.get(359201,0)>previous_version:
                target.athena_shield = dict(owner=self.id,generation=self.generation,
                                           step=cast['max_hp']*D('.03'),absorbed=D(0))
            return packets+self._passive(cast['power'],now)
        if kind=='athena_blessing':
            target_id,generation,version,amount = data
            target = self.arena.actors.get(target_id)
            if target and target.alive and target.generation==generation and target.buff_versions.get(359302)==version:
                return target.restore_hp(amount,now)
            return []
        if kind=='athena_mark':
            cast, = data
            target = self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation'] or target.buff_versions.get(359401)!=cast['version']:
                return []
            pos = target.position_at(now)
            ident,packet = self.add_object(359701,pos)
            self._queue(now+500,'object_expire',ident)
            packets = [packet]
            for enemy in list(self.arena.actors.values()):
                if enemy.alive and enemy.camp!=self.camp and math.dist(pos,enemy.position_at(now))<=96:
                    missing = enemy.max_hp-enemy.hp
                    packets.extend(self.damage(cast['power']*D('1.76'),now,target=enemy,school='energy')[0])
                    packets.extend(self.damage(missing*D('.15'),now,target=enemy,school='true')[0])
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot==0:
            if start==dest or not self._inside(dest):
                return []
            self.cooldowns[0] = now+self.fire_interval(now)
            return self.shoot(359100,start,dest,now,self.combat_stat('iEgAtk',now),school='energy',basic=True)+[self._cooldown(0)]
        target = self.arena.actors.get(target_id)
        if slot in (1,2):
            if not target or not target.alive or target.camp!=self.camp or math.dist(start,target.position_at(now))>480:
                return []
        else:
            if not self.r_count or self.mp<50:
                return []
            # User-approved AI02 rule: acquire only a currently team-visible
            # enemy. Allied vision may still permit casting through a wall.
            from bot_ai import observable
            scouts=[a for a in self.arena.actors.values() if a.alive
                    and a.camp==self.camp and not a.info.get('npc_template')]
            targets = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                       and not a.is_untargetable() and math.dist(start,a.position_at(now))<=600
                       and any(observable(self.arena,scout,a,now) for scout in scouts)]
            if not targets:
                return []
            target = min(targets,key=lambda a:(a.id>>26!=0,math.dist(start,a.position_at(now)),a.id))
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({1:8000,2:25000,10:2000}[slot], slot)
        cast = dict(slot=slot,target=target.id,target_generation=target.generation,
                    power=power,max_hp=self.max_hp,generation=self.generation,dest=target.position_at(now))
        packets = [self._cooldown(slot)]
        if slot==1:
            self.position,self.motion = start,None
            self.ready = cast
            self._queue(now+50,'athena_e',cast)
            return packets+[scene(skills=(self._skill_event(359201,start,cast['dest'],target.id,ready=1),))]+self.sync_speed(now)
        packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,cast['dest'],target.id),)))
        if slot==2:
            version = target.buff_versions.get(359302,0)+1
            self._queue(now+3000,'athena_blessing',target.id,target.generation,version,self.max_hp*D('.3'))
            packets.extend(self._buff(359301,now,target.id,duration=3000)+self._buff(359302,now,target.id))
        else:
            self.r_count -= 1
            if not self.r_next_charge:
                self.r_next_charge = now+self.skill_cooldown(6000)
            packets.extend(self._resource(-50)+self._buff(359401,now,target.id))
            if target.has_buff(359401,now):
                cast['version'] = target.buff_versions[359401]
                self._queue(now+1000,'athena_mark',cast)
            packets[0] = self._cooldown(10)
        return packets+self._passive(power,now)
