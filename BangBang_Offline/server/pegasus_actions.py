"""Pegasus: counted wards, timed disappearance and per-victim meteor decay."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene
from melee_common import prepare_displacement

SLOTS = {0:309100,1:309201,2:309301,10:309401}
VANISH = tuple(range(309201,309211))


class PegasusActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.vanish = self.ready = self.combat = None
        self.ward_count = 0
        self.shield_blocked = set()
        self.r_count,self.r_next_charge = 2,0
        self.assists,self.rewarded = {},set()

    def _cooldown(self,slot,changed=False):
        body = props(309211 if slot==1 and self.vanish else SLOTS[slot],slot,
                     self.r_count if slot==10 else -1,
                     self.vanish['begin']+1000 if slot==1 and self.vanish else self.cooldowns[slot],
                     self.r_next_charge if slot==10 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _ward(self,now,*,skill=False):
        self.ward_count = 3
        packets = self.remove_buff(309111,now)+self.remove_buff(309131,now)
        return packets+self._buff(309131 if skill else 309111,now)

    def remove_buff(self,template,now,*,expired=False):
        packets = super().remove_buff(template,now,expired=expired)
        if template==309131 and expired and self.alive and self.combat is None:
            packets.extend(self._ward(now))
        return packets

    def on_spawn(self,now):
        self.assists.clear()
        self.rewarded.clear()
        self.shield_blocked.clear()
        self.combat = None
        packets = []
        for t in range(309101,309106):
            packets.extend(self._buff(t,now))
        return packets+self._ward(now)+[self._cooldown(1,True)]

    def _engage(self,now):
        self.combat = dict(end=now+5000,generation=self.generation)
        self._queue(now+5000,'pegasus_idle',self.combat)

    def on_combat(self,now):
        context = getattr(self.arena,'damage_context',None)
        if self.alive and (not context or len(context)!=4 or context[0]!=self.id or context[1]==self.generation):
            self._engage(now)

    def block_hit(self,key,amount,now,*,basic=False,periodic=False,source=None):
        if amount<=0:
            return False,[]
        self._engage(now)
        if key in self.shield_blocked:
            return True,[]
        if self.ward_count and (self.has_buff(309111,now) or self.has_buff(309131,now)):
            self.ward_count -= 1
            self.shield_blocked.add(key)
            packets = []
            if not self.ward_count:
                packets = self.remove_buff(309111,now)+self.remove_buff(309131,now)
            return True,packets
        return False,[]

    def damage(self,raw,now,**kwargs):
        target = kwargs.get('target') or self.enemy
        before = target.alive
        result,lost = super().damage(raw,now,**kwargs)
        context = getattr(self.arena,'damage_context',None)
        current = not context or len(context)!=4 or context[0]!=self.id or context[1]==self.generation
        if current and self.alive:
            if before and not target.alive:
                result.extend(self._ward(now))
        return result,lost

    def reject_buff(self,row,source,now):
        return bool(self.vanish and source.camp!=self.camp)

    def cc_immune(self,now,*,slow=False):
        return bool(self.vanish) or super().cc_immune(now,slow=slow)

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def _appear(self,now,*,dead=False):
        cast,self.vanish = self.vanish,None
        if not cast:
            return []
        self.info.pop('untargetable',None)
        self.info.pop('damage_immune',None)
        self.cooldowns[1] = now+self.skill_cooldown(8000, 1)
        packets = []
        for t in VANISH:
            packets.extend(self.remove_buff(t,now))
        if not dead:
            cast['pos'] = self.position_at(now)
            self._queue(now+200,'pegasus_impact',cast)
            for t in (309211,309214,309215):
                packets.extend(self._buff(t,now))
            packets.extend(self._ward(now,skill=True))
            packets.append(scene(skills=(self._skill_event(309211,cast['pos'],cast['pos'],self.id),)))
        return packets+[self._cooldown(1,True),self._cooldown(1)]+self.sync_speed(now)

    def interrupt(self,now):
        packets = []
        if self.ready:
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,309301)))
        if not self.alive:
            packets.extend(self._appear(now,dead=True))
        return packets+self.sync_speed(now)

    def update(self,now):
        packets = self.interrupt(now) if self.ready and self.skill_sealed(2,now) else []
        while self.r_next_charge and self.r_next_charge<=now:
            self.r_count = min(2,self.r_count+1)
            self.r_next_charge = self.r_next_charge+self.skill_cooldown(6000) if self.r_count<2 else 0
            packets.append(self._cooldown(10))
        # Only ongoing pellets need a retained blocked-attack identity.
        live = {args[1][0].get('attack_key') for _,_,callback,args in self.arena.pending
                if callback.__name__=='_event' and args[0]=='flight'}
        self.shield_blocked.intersection_update(live)
        return packets+super().update(now)

    def on_target_death(self,target,now):
        key = target.id,target.generation
        mark = self.assists.pop(key,None)
        if not self.alive or not mark or mark['generation']!=self.generation or mark['end']<now or key in self.rewarded:
            return []
        self.rewarded.add(key)
        self.cooldowns[1] = now
        return [self._cooldown(1)]

    def _event(self,now,kind,data):
        if kind=='pegasus_idle':
            cast, = data
            if self.combat is cast and self.alive and self.generation==cast['generation']:
                self.combat = None
                return self._ward(now)
            return []
        if kind=='pegasus_appear':
            return self._appear(now) if self.vanish is data[0] and self.alive else []
        if kind=='pegasus_impact':
            cast, = data
            if not self.alive or self.generation!=cast['generation']:
                return []
            packets = []
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(cast['pos'],target.position_at(now))<=144:
                    packets.extend(self.damage(cast['power']*D('2.17'),now,target=target,school='energy')[0])
                    packets.extend(self._buff(309222,now,target.id))
            return packets
        if kind=='pegasus_meteors':
            cast, = data
            if self.ready is not cast or not self.alive or self.skill_sealed(2,now):
                return self.interrupt(now) if self.ready is cast else []
            self.ready = None
            start = self.position_at(now)
            theta = math.atan2(cast['dest'][1]-start[1],cast['dest'][0]-start[0])
            packets = [scene(skills=(self._skill_event(309301,start,cast['dest']),))]
            for index in range(12):
                angle = theta+math.radians(index*30)
                dest = start[0]+round(480*math.cos(angle)),start[1]+round(480*math.sin(angle))
                packets.extend(self.shoot(309301,start,dest,now,cast['power']*D('2.1'),school='energy',
                                          through_walls=True,context=cast,
                                          attack_key=(self.id,self.generation,309301,(cast['attack_id'],index))))
            return packets+self.sync_speed(now)
        return super()._event(now,kind,data)

    def _flight(self,flight,now):
        if flight['template']==309100:
            return super()._flight(flight,now)
        start = point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        packets = []
        for target in list(self.arena.actors.values()):
            key = target.id,target.generation
            if not target.alive or target.camp==self.camp or key in flight['hits'] or target.is_untargetable():
                continue
            hit = actor_contact(start,end,target,flight['previous'],now,84 if flight['template']==309401 else 36)
            if hit is None:
                continue
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['hits'].add(key)
            raw = flight['raw']
            if flight['template']==309301:
                counts = flight['context']['counts']
                raw *= D('.95')**counts.get(key,0)
                counts[key] = counts.get(key,0)+1
                if flight['source_generation']==self.generation and self.alive:
                    self.assists[key] = dict(end=now+5000,generation=self.generation)
            packets.extend(self.damage(raw,now,target=target,school='energy')[0])
            if flight['template']==309401:
                packets.extend(self._buff(309402,now,target.id))
        if now>=flight['finish']:
            return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now):
            return []
        if slot==1 and self.vanish:
            return self._appear(now) if now>=self.vanish['begin']+1000 else []
        if self.vanish or self.cooldowns[slot]>now or slot==10 and not self.r_count:
            return []
        if slot in (0,2,10) and (start==dest or not self._inside(dest)):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:0,2:20000,10:3000}[slot], slot)
        if slot==0:
            return self.shoot(309100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        packets = self._ward(now,skill=True)
        stopped = []
        if slot==1:
            self.vanish = dict(begin=now,power=power,generation=self.generation)
            self.info['untargetable'] = self.info['damage_immune'] = True
            self._queue(now+3000,'pegasus_appear',self.vanish)
            for t in VANISH:
                packets.extend(self._buff(t,now))
            packets.extend((scene(skills=(self._skill_event(309201,start,start,self.id),)),self._cooldown(1,True)))
        elif slot==10:
            self.r_count -= 1
            if not self.r_next_charge:
                self.r_next_charge = now+self.skill_cooldown(6000)
            packets.extend(self.shoot(309401,start,dest,now,power*D('2.26'),school='energy',through_walls=True))
        else:
            _,stopped = prepare_displacement(self,now,interrupt=False)
            self.ready = dict(slot=2,dest=dest,power=power,generation=self.generation,counts={},attack_id=self._new_id(2))
            self._queue(now+150,'pegasus_meteors',self.ready)
            packets.append(scene(skills=(self._skill_event(309301,start,dest,ready=1),)))
        return packets+[self._cooldown(slot)]+self.sync_speed(now)+stopped
