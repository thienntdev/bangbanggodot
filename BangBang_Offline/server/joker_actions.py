"""Joker family451; native shadow NPC and distance-based soul tear."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import point_at
from combat_math import D
from combat_protocol import props, scene
from hulu_actions import HuluTurret

SLOTS = {0:451100,1:451201,2:451301,10:451401}


class JokerActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.e_count,self.e_next_charge = 3,0
        self.passive_ready_at = 0
        self.marks = {}

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,self.e_count if slot==1 else -1,
                          self.cooldowns[slot],self.e_next_charge if slot==1 else 0)+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.info['untargetable'] = False
        return self._buff(451101,now)+self._buff(451102,now)

    def _visibility(self,now):
        self.info['untargetable'] = self.has_buff(451403,now) and 32 not in self.buff_types(now)

    def remove_buff(self,template,now,*,expired=False):
        packets = super().remove_buff(template,now,expired=expired)
        if template==451403:
            self._visibility(now)
        return packets

    def update(self,now):
        self._visibility(now)
        packets = []
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count = min(3,self.e_count+1)
            self.e_next_charge = self.e_next_charge+self.skill_cooldown(8000) if self.e_count<3 else 0
            packets.append(self._cooldown(1))
        return packets+super().update(now)

    def _proc(self,now,generation):
        if not self.alive or generation!=self.generation or now<self.passive_ready_at:
            return []
        self.passive_ready_at = now+250
        packets = self.restore_hp(self.max_hp*D('.08'),now)
        if self.e_next_charge:
            self.e_next_charge = now+round(max(0,self.e_next_charge-now)*.92)
        for slot in (2,10):
            self.cooldowns[slot] = now+round(max(0,self.cooldowns[slot]-now)*.92)
        return packets+[self._cooldown(slot) for slot in (1,2,10)]

    def _area(self,pos,power,ratio,generation,now,*,slow=False):
        packets = []
        for target in list(self.arena.actors.values()):
            if target.alive and target.camp!=self.camp and math.dist(pos,target.position_at(now))<=144:
                packets.extend(self.damage(power*ratio,now,target=target)[0])
                if slow:
                    packets.extend(self._buff(451204,now,target.id))
                packets.extend(self._proc(now,generation))
        return packets

    def on_bullet_hit(self,flight,target,now):
        if flight['template']!=451301:
            return []
        packets = self._proc(now,flight['source_generation'])
        packets.extend(self._buff(451302,now,target.id))
        if not target.has_buff(451302,now) or target.buff_sources.get(451302)!=self.id:
            return packets
        mark = dict(target=target.id,target_generation=target.generation,
                    generation=flight['source_generation'],power=flight['power'],
                    version=target.buff_versions[451302],distance=0.,pos=target.position_at(now))
        self.marks[target.id] = mark
        self._queue(now+500,'joker_tear_start',mark)
        return packets

    def on_target_death(self,target,now):
        self.marks.pop(target.id,None)
        return []

    def _event(self,now,kind,data):
        if kind=='joker_box':
            cast, = data
            # The box detonates here; only normal impact emits its native
            # removal movie. The damage callback and timing are unchanged.
            return self.remove_object(cast['id'],destroyed=True)+self._area(cast['pos'],cast['power'],D('3.54'),cast['generation'],now,slow=True)
        if kind in ('joker_tear_start','joker_tear'):
            mark, = data
            target = self.arena.actors.get(mark['target'])
            if not target or not target.alive or target.generation!=mark['target_generation'] or self.marks.get(target.id) is not mark:
                return []
            if kind=='joker_tear_start':
                if target.buff_versions.get(451302)!=mark['version']:
                    return []
                # The original 451302 removal chain points to Buff345303.
                packets = self._buff(345303,now,target.id)
                if not target.has_buff(345303,now):
                    return packets
                mark.update(version=target.buff_versions[345303],pos=target.position_at(now),end=now+3000)
            else:
                if target.buff_versions.get(345303)!=mark['version'] or now>mark['end']:
                    return []
                packets = []
                pos = target.position_at(now)
                mark['distance'] += math.dist(mark['pos'],pos)
                mark['pos'] = pos
                count = int(mark['distance']//24)
                mark['distance'] -= count*24
                for _ in range(count):
                    if not target.alive:
                        break
                    packets.extend(self.damage(mark['power']*D('.36'),now,target=target,school='true',periodic=True)[0])
                    packets.extend(self._proc(now,mark['generation']))
            if now<mark['end']:
                self._queue(min(now+20,mark['end']),'joker_tear',mark)
            else:
                self.marks.pop(target.id,None)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or slot in (0,2,10) and start==dest or slot==1 and (not self.e_count or math.dist(start,dest)>600):
            return []
        power = self.combat_stat('iAttack',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:1000,2:25000,10:8000}[slot], slot)
        packets = self.remove_buff(451403,now)
        if slot in (0,2):
            return packets+self.shoot(SLOTS[slot],start,dest,now,power*(D('4.12') if slot else 1),
                                      school='physical',basic=slot==0,through_walls=slot==2,power=power)+[self._cooldown(slot)]
        packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,dest),)))
        if slot==1:
            self.e_count -= 1
            if not self.e_next_charge:
                self.e_next_charge = now+self.skill_cooldown(8000)
            ident,packet = self.add_object(451201,dest)
            packets.append(packet)
            self._queue(now+1000,'joker_box',dict(id=ident,pos=dest,power=power,generation=self.generation))
        else:
            info = dict(acct_id=self.info['acct_id'],tank_level=self.info['tank_level'],
                        tank_id=self.info['tank_id'],npc_template=451401,owner=self.id,
                        source_generation=self.generation,name=self.info['name'],in_room=True,summon_stats=dict(self.stats))
            for key in ('iAttack','iEgAtk','iArmor','iEgArmor','iCentesis','iEgCtsis'):
                info['summon_stats'][key] = str(self.combat_stat(key,now))
            info['summon_stats']['iHp'] = str(self.max_hp)
            clone = JokerClone(self.arena,self._new_id(5),info,self.camp,start)
            self.arena.actors[clone.id] = clone
            packets.extend([clone.snapshot(now)]+clone.on_spawn(now))
            dest = self.blink_destination(start,point_at(start,dest,min(1,336/math.dist(start,dest))))
            self.position,self.motion = dest,None
            packets.append(scene(moves=(self._move_event(dest,0,5),)))
            packets.extend(self._buff(451403,now))
            self._visibility(now)
        return packets+[self._cooldown(slot)]


class JokerClone(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.stats = dict(self.info['summon_stats'])
        self.hp = self.max_hp = D(self.stats['iHp'])
        self.info['hp'] = self.info['max_hp'] = math.ceil(self.hp)
        self.cooldowns = {}
        self.received = D(0)
        self.exploded = False

    def snapshot(self,now):
        body = struct.pack('<IIhhiBiIiH',self.id,451401,*self.position_at(now),math.ceil(self.hp),
                           self.camp,math.ceil(self.max_hp),self.info['owner'],
                           math.ceil(sum(s.remaining for s in self.shields if s.expires_ms>now)),0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def sync_speed(self,now):
        return []

    def on_spawn(self,now):
        self._queue(now+2000,'joker_clone_end')
        return []

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        self.received += hit.hp_loss
        owner = self.arena.actors.get(self.info['owner'])
        step = self.max_hp*D('.08')
        if owner and owner.alive and owner.generation==self.info['source_generation'] and now>=owner.passive_ready_at and self.received>=step:
            self.received -= step
            return owner._proc(now,self.info['source_generation'])
        return []

    def commit_hp(self,hp,now,*,critical=False):
        before = self.alive
        packets = super().commit_hp(hp,now,critical=critical)
        if before and not self.alive and not self.exploded:
            self.exploded = True
            owner = self.arena.actors[self.info['owner']]
            pos = self.position_at(now)
            packets.append(scene(skills=(self._skill_event(451411,pos,pos),)))
            packets.extend(owner._area(pos,D(self.stats['iAttack']),D('2.7'),self.info['source_generation'],now))
            packets.append(scene(removed=(struct.pack('<I',self.id),)))
        return packets

    def _event(self,now,kind,data):
        if kind=='joker_clone_end':
            return self.commit_hp(D(0),now) if self.alive else []
        return super()._event(now,kind,data)

    _respawn = HuluTurret._respawn
