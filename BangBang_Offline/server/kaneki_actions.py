"""Kaneki: explicit HP costs, healing stacks and one cap per logical hit."""
import struct

from battle_runtime import TankActions
from combat_math import D, quantize
from combat_protocol import props, scene
from melee_common import in_cone, enemies, piercing_step

SLOTS = {0:350100, 1:350201, 2:350301, 10:350401}


class KanekiActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.r_count,self.r_next_charge = 2,0
        self.passive_ready_at = 0
        self.hit_caps = {}

    def _cooldown(self,slot,changed=False):
        body = props(SLOTS[slot],slot,self.r_count if slot==10 else -1,
                     self.cooldowns[slot],self.r_next_charge if slot==10 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.hit_caps.clear();self.passive_ready_at=0
        return self._buff(350101,now)

    def limit_hit(self,key,amount,now):
        if not self.has_buff(350302,now):
            return amount
        remaining = self.hit_caps.get(key,quantize(self.max_hp*D('.05')))
        allowed = min(amount,remaining)
        self.hit_caps[key] = remaining-allowed
        return allowed

    def _proc(self,now,generation):
        if not self.alive or generation!=self.generation or now<self.passive_ready_at:
            return []
        self.passive_ready_at=now+100
        return self._buff(350111,now)+self._buff(350112,now)

    def update(self,now):
        packets=[]
        while self.r_next_charge and self.r_next_charge<=now:
            self.r_count=min(2,self.r_count+1)
            self.r_next_charge=self.r_next_charge+self.skill_cooldown(10000) if self.r_count<2 else 0
            packets.append(self._cooldown(10))
        live={args[1][0].get('attack_key') for _,_,callback,args in self.arena.pending
              if callback.__name__=='_event' and args[0]=='flight'}
        self.hit_caps={k:v for k,v in self.hit_caps.items() if k in live}
        return packets+super().update(now)

    def _e_hit(self,flight,target,now):
        current=self.alive and self.generation==flight['source_generation']
        # Q35: own missing HP after the cost, before this hit's heal.
        raw=flight['power']*D('1.47')+(self.max_hp-self.hp)*D('.1')
        packets,lost=self.damage(raw,now,target=target)
        if lost:packets.extend(self._proc(now,flight['source_generation']))
        if current:
            packets.extend(self.restore_hp(self.max_hp*D('.1'),now))
            self.cooldowns[1]=now+self.skill_cooldown(1500, 1)
            packets.append(self._cooldown(1))
        return packets+self._buff(350215,now,target.id)

    def _flight(self,flight,now):
        if flight['template']==350211:
            if not self.alive or self.generation!=flight['source_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            return piercing_step(self,flight,now,self._e_hit,pierce=False)
        return super()._flight(flight,now)

    def _event(self,now,kind,data):
        if kind=='kaneki_regen':
            generation,version,index=data
            if not self.alive or self.generation!=generation or self.buff_versions.get(350301)!=version:
                return []
            packets=self.restore_hp((self.max_hp-self.hp)*D('.05'),now)
            if index<10:self._queue(now+500,'kaneki_regen',generation,version,index+1)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or not self.alive or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        # Space's original iUseInStun permits activation during stun.
        if slot!=2 and self.blocked('attack',now) or slot==10 and not self.r_count:
            return []
        if slot in (0,1,10) and start==dest:return []
        power=self.combat_stat('iAttack',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:20000,10:5000}[slot], slot)
        if slot==0:
            return self.shoot(350100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        packets=[scene(skills=(self._skill_event(SLOTS[slot],start,dest),))]
        if slot in (1,10):
            packets.extend(self.commit_hp(min(self.hp,max(D(1),self.hp*(D('.85') if slot==1 else D('.8')))),now))
        if slot==1:
            packets.extend(self.shoot(350211,start,dest,now,D(0),school='physical',through_walls=True,power=power))
        elif slot==10:
            self.r_count-=1
            if not self.r_next_charge:self.r_next_charge=now+self.skill_cooldown(10000)
            raw=power*D('1.64')+(self.max_hp-self.hp)*D('.1')
            for target in enemies(self,area=True):
                if not in_cone(target.position_at(now),start,dest,408,60):continue
                hit,lost=self.damage(raw,now,target=target);packets.extend(hit)
                if lost:packets.extend(self._proc(now,self.generation))
                packets.extend(self.restore_hp(self.max_hp*D('.1'),now))
                packets.extend(self._buff(350405,now,target.id))
        else:
            self.hit_caps.clear()
            for template in (350301,350302,350303):packets.extend(self._buff(template,now))
            self._queue(now+500,'kaneki_regen',self.generation,self.buff_versions[350301],1)
        return packets+[self._cooldown(slot)]
