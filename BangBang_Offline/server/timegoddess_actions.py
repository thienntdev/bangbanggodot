"""Time Goddess: energy ammunition, sleep, life-bound rewind and guardians."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import rect_contact, actor_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from hulu_actions import HuluTurret
from melee_common import enemies, piercing_step

SLOTS = {0:389100, 1:389201, 2:389301, 10:389401}


def clear_line(actor,start,end,now):
    return (actor.arena.geometry.wall_contact(start,end) is None
            and rect_contact(start,end,actor.arena.water_rects(now),0) is None)


class TimeGoddessActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp = 100
        self.time_combat_until = 0

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,-1,self.cooldowns[slot])+struct.pack('<I',self.id)

    def _resource(self,delta):
        if not self.alive or self.in_stasis():return []
        old,self.mp = self.mp,max(0,min(100,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if self.mp!=old else []

    def on_spawn(self,now):
        self.mp = 100
        self.time_combat_until = now
        self._queue(now+500,'time_energy',self.generation)
        return [scene(mp=(struct.pack('<Ii',self.id,100),))]

    def on_combat(self,now):
        self.time_combat_until = now+4000

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        if self.arena.pk and self.arena.pk['finished']:return []
        if hit.potential_damage>0:self.on_combat(now)
        return []

    def _flight(self,flight,now):
        if flight['template']==389100:
            start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
            end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
            targets=list(enemies(self))+[a for a in self.arena.actors.values()
                if a.id!=self.id and a.alive and a.camp==self.camp
                and not a.info.get('npc_template') and not a.in_stasis()]
            contacts=[(h,a.id,a) for a in targets
                      if (h:=actor_contact(start,end,a,flight['previous'],now,24)) is not None]
            ident=struct.pack('<I',flight['id'])
            if contacts:
                target=min(contacts,key=lambda x:x[:2])[2]
                if target.camp!=self.camp and self.projectile_blocked(target,now):
                    return [scene(expired_bullets=(ident,))]
                return self._impact(flight,target,now)+[scene(blown_bullets=(ident,))]
            if now>=flight['finish']:return [scene(expired_bullets=(ident,))]
            flight['previous']=now
            self._queue(min(now+20,flight['finish']),'flight',flight)
            return []
        if flight['template']==389201:
            return piercing_step(self,flight,now,self._impact,pierce=False,
                                 contact_radius=36)
        return super()._flight(flight,now)

    def _impact(self,flight,target,now):
        if flight['template']==389201:
            packets = self.damage(flight['raw'],now,target=target,school='energy',source_generation=flight['source_generation'])[0]
            if self.arena.pk and self.arena.pk['finished']:return packets
            return packets+self._buff(389202,now,target.id)+self._buff(389203,now,target.id)
        pos = target.position_at(now)
        packets = []
        for enemy in enemies(self,area=True):
            if math.dist(pos,enemy.position_at(now))>144:continue
            if rect_contact(pos,enemy.position_at(now),self.arena.water_rects(now),0) is not None:continue
            distance = min(720,math.dist(flight['start'],enemy.position_at(now)))
            factor = D('.5')+D(str(distance/1440))
            packets += self.damage(flight['power']*factor,now,target=enemy,school='energy',basic=True,
                                   ignore_reductions=distance>=720,source_generation=flight['source_generation'])[0]
            if self.arena.pk and self.arena.pk['finished']:return packets
        for ally in self.arena.actors.values():
            if (ally.alive and ally.camp==self.camp and not ally.info.get('npc_template')
                    and math.dist(pos,ally.position_at(now))<=144 and clear_line(self,pos,ally.position_at(now),now)):
                if ally.id!=self.id or self.generation==flight['source_generation']:
                    packets += ally.restore_hp(flight['power'],now)
        return packets

    def _event(self,now,kind,data):
        if kind=='time_energy':
            generation, = data
            if not self.alive or self.generation!=generation:return []
            self._queue(now+500,kind,generation)
            return self._resource(10) if now>=self.time_combat_until else []
        if kind=='time_reload':
            generation,version = data
            if self.alive and self.generation==generation and self.buff_versions.get(389121)==version:
                return self.remove_buff(389121,now)+self._resource(100)
            return []
        if kind=='time_rewind':
            cast, = data
            target = self.arena.actors.get(cast['target'])
            if (not target or not target.alive or target.in_stasis() or target.generation!=cast['target_generation']
                    or target.buff_versions.get(389301)!=cast['version']):return []
            packets = target.remove_buff(389301,now)+target.remove_buff(389305,now)
            return packets+target.commit_hp(min(target.max_hp,cast['hp']),now)+self._buff(389302,now,target.id)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if self.arena.pk and self.arena.pk['finished']:return []
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if not self._inside(dest) or slot in (0,1) and start==dest:return []
        if slot in (2,10) and math.dist(start,dest)>480:return []
        if slot==0 and self.mp<20:return []
        if slot==10 and (self.arena.geometry.clamp_tank_position(dest)!=dest
                         or self.arena.geometry.wall_contact(dest,dest,36) is not None
                         or rect_contact(dest,dest,self.arena.water_rects(now),36) is not None):return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+(self.fire_interval(now) if slot==0 else self.skill_cooldown({1:8000,2:30000,10:8000}[slot],slot))
        self.on_combat(now)
        packets = [self._cooldown(slot)]
        if slot in (0,1):
            packets += self.shoot(SLOTS[slot],start,dest,now,power*(D(1) if slot==0 else D('1.75')),
                                  school='energy',basic=slot==0,through_walls=True,power=power)
            if slot==0:
                packets += self._resource(-20)
                if self.mp==0:
                    # Queue before natural expiry so a version check remains
                    # valid even when a checkpoint lands on the exact deadline.
                    version = self.buff_versions.get(389121,0)+1
                    self._queue(now+1000,'time_reload',self.generation,version)
                    packets += self._buff(389121,now)
            return packets
        packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,dest),)))
        if slot==2:
            for ally in list(self.arena.actors.values()):
                if (not ally.alive or ally.camp!=self.camp or ally.info.get('npc_template') or ally.in_stasis()
                        or math.dist(dest,ally.position_at(now))>300 or not clear_line(self,dest,ally.position_at(now),now)
                        or not clear_line(self,start,ally.position_at(now),now)):continue
                cast = dict(target=ally.id,target_generation=ally.generation,hp=ally.hp,
                            version=ally.buff_versions.get(389301,0)+1)
                self._queue(now+2000,'time_rewind',cast)
                packets += self._buff(389301,now,ally.id)+self._buff(389305,now,ally.id)
                # Falcon ammunition and Minion components are not energy.
                if hasattr(ally,'_resource') and ally.info['tank_id'] not in (10000104,10000060):
                    packets += ally._resource(100,now) if ally.info['tank_id']==10000033 else ally._resource(100)
            return packets+self._buff(389304,now)
        info = dict(acct_id=self.info['acct_id'],tank_id=self.info['tank_id'],tank_level=self.info['tank_level'],
                    npc_template=389401,owner=self.id,source_generation=self.generation,
                    name='Thủ Hộ Thời Gian',in_room=True,summon_stats=dict(self.stats))
        for key in ('iAttack','iEgAtk','iArmor','iEgArmor','iCentesis','iEgCtsis'):
            info['summon_stats'][key] = str(self.combat_stat(key,now))
        info['summon_stats'].update(iHp=str(self.max_hp*D('.5')),iSpeed='0',iFireInterv='1000',nFireRange='0')
        guardian = TimeGuardian(self.arena,self._new_id(5),info,self.camp,dest)
        self.arena.actors[guardian.id] = guardian
        return packets+[guardian.snapshot(now)]+guardian.on_spawn(now)


class TimeGuardian(HuluTurret):
    def snapshot(self,now):
        body = struct.pack('<IIhhiBiIiH',self.id,389401,*self.position_at(now),math.ceil(self.hp),self.camp,
                           math.ceil(self.max_hp),self.info['owner'],0,0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def taunt_attack(self,target,now):
        return []  # A healer must not acquire an attack from taunt.

    def on_spawn(self,now):
        self._queue(now+1000,'time_guardian')
        return self._buff(389402,now)+self._buff(389403,now)

    def _event(self,now,kind,data):
        if kind=='time_guardian':
            if not self.alive:return []
            packets = self.commit_hp(max(D(0),self.hp-self.max_hp*D('.08')),now)
            if not self.alive or self.arena.pk and self.arena.pk['finished']:return packets
            if not self.blocked('attack',now) and not self.skill_sealed(0,now):
                pos = self.position_at(now)
                owner = self.arena.actors.get(self.info['owner'])
                for ally in self.arena.actors.values():
                    if (not ally.alive or ally.camp!=self.camp or ally.info.get('npc_template')
                            or math.dist(pos,ally.position_at(now))>300 or not clear_line(self,pos,ally.position_at(now),now)):continue
                    if owner is ally and owner.generation!=self.info['source_generation']:continue
                    packets += ally.restore_hp(D(self.stats['iEgAtk'])*D('.75'),now)
            self._queue(now+1000,kind)
            return packets
        return super()._event(now,kind,data)
