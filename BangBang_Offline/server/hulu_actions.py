"""Hồ Lô: finite healing areas, conversion of remaining shield, native NPC20017."""
from dataclasses import replace
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D, quantize
from combat_protocol import props, scene

SLOTS = {0:311100,1:311201,2:311301,10:311401}


class HuluActions(TankActions):
    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self._queue(now+3000,'hulu_passive',self.generation)
        return self._buff(311101,now)

    def _area(self,cast,now,*,healing):
        packets = []
        for target in self.arena.actors.values():
            if target.alive and target.camp==self.camp and math.dist(cast['pos'],target.position_at(now))<=264:
                if healing:
                    packets.extend(target.restore_hp(cast['power']*D('.5'),now))
                duration = min(550,cast['end']-now)
                if duration>0:
                    packets.extend(self._buff(311312,now,target.id,duration=duration))
                    packets.extend(self._buff(311313,now,target.id,duration=duration))
        return packets

    def _event(self,now,kind,data):
        if kind=='hulu_passive':
            if not self.alive or self.generation!=data[0]:
                return []
            self._queue(now+3000,kind,*data)
            pos,power = self.position_at(now),self.combat_stat('iEgAtk',now)
            packets = [scene(skills=(self._skill_event(311111,pos,pos,self.id),))]
            for target in self.arena.actors.values():
                if target.alive and target.camp==self.camp and math.dist(pos,target.position_at(now))<=360:
                    packets.extend(target.restore_hp(power*D('.5'),now))
            return packets
        if kind=='hulu_convert':
            target_id,generation,version,amount = data
            target = self.arena.actors.get(target_id)
            if not target or not target.alive or target.generation!=generation or target.buff_versions.get(311201)!=version:
                return []
            shield = next((s for s in target.shields if s.shield_id=='311201' and s.expires_ms>=now),None)
            if not shield:
                return []
            converted = min(shield.remaining,amount)
            target.shields = tuple(replace(s,remaining=quantize(s.remaining-converted)) if s is shield else s for s in target.shields)
            packets = target.restore_hp(converted,now)
            if converted==shield.remaining:
                packets.extend(target.remove_buff(311201,now))
            return packets+[target.shield_packet(now)]
        if kind=='hulu_area':
            cast, = data
            packets = self._area(cast,now,healing=True)
            if now<cast['end']:
                self._queue(now+500,kind,cast)
            else:
                packets.extend(self.remove_object(cast['id']))
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        target = self.arena.actors.get(target_id)
        if slot==1:
            if not target or not target.alive or target.camp!=self.camp or math.dist(start,target.position_at(now))>480:
                return []
        elif not self._inside(dest) or (slot==0 and start==dest):
            return []
        elif slot in (2,10) and math.dist(start,dest)>(480 if slot==2 else 336):
            return []
        if slot==10 and (self.arena.geometry.clamp_tank_position(dest)!=dest or self.arena.geometry.wall_contact(dest,dest,36) is not None):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:25000,10:8000}[slot], slot)
        if slot==0:
            return self.shoot(311100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        packets = [self._cooldown(slot),scene(skills=(self._skill_event(SLOTS[slot],start,
                   target.position_at(now) if slot==1 else dest,target.id if slot==1 else 0),))]
        if slot==1:
            version = target.buff_versions.get(311201,0)+1
            # Enqueue conversion before the natural expiry at the fifth tick.
            for i in range(1,6):
                self._queue(now+i*1200,'hulu_convert',target.id,target.generation,version,power*D('.45'))
            packets.extend(target.add_shield(311201,power*D('2.25'),now,caster=self))
            if target.has_buff(311201,now) and target.buff_versions[311201]==version:
                for buff in (311202,311203,311204):
                    packets.extend(self._buff(buff,now,target.id))
        elif slot==2:
            ident,packet = self.add_object(311301,dest)
            cast = dict(id=ident,pos=dest,power=power,end=now+4000,generation=self.generation)
            packets.extend([packet]+self._area(cast,now,healing=False))
            self._queue(now+500,'hulu_area',cast)
        else:
            info = dict(acct_id=self.info['acct_id'],tank_level=self.info['tank_level'],
                        npc_template=20017,owner=self.id,tank_id=10000037,
                        name='Hồ Lô',in_room=True,summon_stats=dict(self.stats))
            for key in ('iAttack','iEgAtk','iArmor','iEgArmor','iCentesis','iEgCtsis'):
                info['summon_stats'][key] = str(self.combat_stat(key,now))
            info['summon_stats'].update(iHp=str(self.max_hp*D('.5')),iSpeed='0',iFireInterv='1000',nFireRange='360')
            turret = HuluTurret(self.arena,self._new_id(5),info,self.camp,dest)
            self.arena.actors[turret.id] = turret
            packets.extend([turret.snapshot(now)]+turret.on_spawn(now))
        return packets


class HuluTurret(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.stats = dict(self.info['summon_stats'])
        self.hp = self.max_hp = D(self.stats['iHp'])
        self.info['hp'] = self.info['max_hp'] = math.ceil(self.hp)
        self.cooldowns = {}
        self.passive_ready_at = 0
        self.last_speed,self.last_interval = 0,1000

    def snapshot(self,now):
        body = struct.pack('<IIhhiBiIiH',self.id,20017,*self.position_at(now),math.ceil(self.hp),
                           self.camp,math.ceil(self.max_hp),self.info['owner'],
                           math.ceil(sum(s.remaining for s in self.shields if s.expires_ms>now)),0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def sync_speed(self,now):
        return []  # S1560 addresses a player's account, not an AI NPC object.

    def _set_motion(self,start,dest,speed,now,kind=0):
        self.position = self.spawn
        self.motion = (self.spawn,self.spawn,now,now+1)
        return 1

    @staticmethod
    def move_destination(start,dest):
        return start  # User: turrets cannot be pulled/pushed, but can be stunned.

    def on_spawn(self,now):
        self.passive_ready_at=now+1000
        self._queue(now+1000,'turret_tick',1)
        self._queue(now+250,'turret_reveal')
        return self._buff(311421,now)+self._buff(311431,now)

    def commit_hp(self,hp,now,*,critical=False):
        before = self.alive
        packets = super().commit_hp(hp,now,critical=critical)
        if before and not self.alive:
            packets.append(scene(removed=(struct.pack('<I',self.id),)))
        return packets

    def _respawn(self,now,generation):
        # Keep a tombstone while delayed projectiles/buffs still refer to it;
        # remove it afterwards instead of growing every checkpoint forever.
        def refers(value,seen):
            if isinstance(value,int):
                return value==self.id
            if isinstance(value,(dict,list,tuple,set)):
                if id(value) in seen:
                    return False
                seen.add(id(value))
                items = list(value.items()) if isinstance(value,dict) else value
                return any(refers(v,seen) for v in items)
            return False
        busy = any(getattr(cb.__self__,'id',None)==self.id or refers(args,set()) for _,_,cb,args in self.arena.pending)
        if busy:
            self._queue(now+1000,'respawn',generation)
        else:
            self.arena.actors.pop(self.id,None)
        return []

    def taunt_attack(self,target,now):
        start=self.position_at(now)
        if (not self.alive or not target.alive or target.is_untargetable() or self.blocked('attack',now)
                or self.skill_sealed(0,now) or now<self.passive_ready_at
                or math.dist(start,target.position_at(now))>360
                or self.arena.geometry.wall_contact(start,target.position_at(now)) is not None):return []
        self.passive_ready_at=now+1000
        packets=[]
        pos = target.position_at(now)
        dest = point_at(start,pos,360/max(1,math.dist(start,pos)))
        wall = self.arena.geometry.wall_contact(start,dest)
        if wall is not None:
            dest = point_at(start,dest,max(0,wall-.001))
        dest = tuple(round(v) for v in dest)
        ident = self._new_id(2)
        # Native exhibit37401 has no travelling sprite/lifetime. Fire
        # triggers its ray effect/audio; damage is evaluated once here.
        packets.append(scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*dest,32767,311411),)))
        for enemy in list(self.arena.actors.values()):
            if enemy.alive and enemy.camp!=self.camp and actor_contact(start,dest,enemy,now,now,48) is not None:
                packets.extend(self.damage(self.combat_stat('iEgAtk',now)*D('.5'),now,target=enemy,school='energy',basic=True)[0])
                packets.extend(self._buff(311412,now,enemy.id))
        # FlyBulletView divides distance by wire speed even with no
        # sprite. Reposition the invisible bullet before its blast.
        packets.append((1562,struct.pack('<Ihhhh',ident,*dest,*dest)))
        packets.append(scene(blown_bullets=(struct.pack('<I',ident),)))
        return packets

    def _event(self,now,kind,data):
        if kind=='turret_reveal':
            if not self.alive:
                return []
            packets = []
            for target in self.arena.actors.values():
                if target.alive and target.camp!=self.camp and math.dist(self.position_at(now),target.position_at(now))<=480:
                    packets.extend(self._buff(311422,now,target.id))
            self._queue(now+250,kind)
            return packets
        if kind=='turret_tick':
            if not self.alive:
                return []
            tick, = data
            if tick==10:
                return self.commit_hp(D(0),now)
            packets = self.commit_hp(max(D(0),self.hp-self.max_hp*D('.02')),now)
            if not self.alive:
                return packets
            start = self.position_at(now)
            targets = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                       and not a.is_untargetable() and math.dist(start,a.position_at(now))<=360
                       and self.arena.geometry.wall_contact(start,a.position_at(now)) is None]
            if targets and not self.blocked('attack',now) and not self.skill_sealed(0,now):
                target = min(targets,key=lambda a:(math.dist(start,a.position_at(now)),a.id))
                packets.extend(self.taunt_attack(target,now))
            self._queue(now+1000,kind,tick+1)
            return packets
        return super()._event(now,kind,data)
