"""Elsa: marked hits, capped incoming attacks and five cancellable waves."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D, quantize
from combat_protocol import props, scene
from melee_common import aimed, enemies, in_cone, prepare_displacement

SLOTS = {0:381100,1:381201,2:381301,10:381401}


class ElsaActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready = self.channel = None
        self.r_count,self.r_next_charge = 2,0
        self.hit_caps = {}

    def _cooldown(self,slot,changed=False):
        skill = 381501 if slot==2 and self.channel else SLOTS[slot]
        end = self.channel['begin']+1000 if slot==2 and self.channel else self.cooldowns[slot]
        body = props(skill,slot,self.r_count if slot==10 else -1,end,self.r_next_charge if slot==10 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready = self.channel = None
        self.hit_caps = {}
        packets = [self._cooldown(2,True)]
        for template in range(381101,381106): packets.extend(self._buff(template,now))
        return packets

    def limit_hit(self,key,amount,now):
        remaining = self.hit_caps.get(key,quantize(self.max_hp*D('.15')))
        allowed = min(amount,remaining)
        self.hit_caps[key] = remaining-allowed
        return allowed

    def _mark(self,target,now):
        packets = []
        for template in range(381111,381117): packets.extend(self._buff(template,now,target.id,duration=2000))
        return packets

    def on_skill_damage(self,source,hit,now):
        if not self.alive or hit.hp_loss<=0: return []
        return self._mark(source,now)+self._buff(381121,now)+self._buff(381122,now)

    def _hit(self,target,raw,now):
        marked = target.has_buff(381114,now) and target.buff_sources.get(381114)==self.id
        packets,lost = self.damage(raw*(D('1.5') if marked else 1),now,target=target,school='energy')
        if lost:
            packets.extend(self._mark(target,now))
            if marked and self.arena.rng.random()<.25:
                packets.extend(self._buff(381131,now,target.id))
                if target.has_buff(381131,now): packets.extend(self._buff(381132,now,target.id,duration=500))
        return packets

    def _speed(self,now):
        return 0 if self.ready or self.channel else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.channel) or super().blocked(action,now)

    def interrupt(self,now):
        packets = []
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,381201)))
            self.ready = None
        if self.channel:
            packets.extend(self.remove_object(self.channel['id']))
            self.channel = None
            packets.append((1583,struct.pack('<II',self.id,381301)))
            for template in (381303,381305,381306,381307,381308): packets.extend(self.remove_buff(template,now))
            packets.append(self._cooldown(2,True))
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        from combat_data import table_row
        row = table_row('BuffTemplate_table.xml',nBuffId=template)
        mask = int(row.get('fEffectValB',0))
        blocked = (self.ready and (not mask or mask&2)) or (self.channel and (not mask or mask&4))
        return self.interrupt(now) if row['nEffectType'] in ('35','66') and blocked else []

    def update(self,now):
        packets = []
        while self.r_next_charge and self.r_next_charge<=now:
            self.r_count = min(2,self.r_count+1)
            self.r_next_charge = self.r_next_charge+self.skill_cooldown(8000) if self.r_count<2 else 0
            packets.append(self._cooldown(10))
        if self.ready and self.skill_sealed(1,now): packets.extend(self.interrupt(now))
        # The first-second self lock must not cancel the channel itself.
        if self.channel and any(owner==self.id and end>now and template not in (381305,381308)
                and self._silences_space(template) for (owner,template),(_,end) in self.active_buffs.items()):
            packets.extend(self.interrupt(now))
        live = {args[1][0].get('attack_key') for _,_,callback,args in self.arena.pending
                if callback.__name__=='_event' and args[0]=='flight'}
        self.hit_caps = {k:v for k,v in self.hit_caps.items() if k in live}
        return packets+super().update(now)

    @staticmethod
    def _silences_space(template):
        from combat_data import table_row
        row = table_row('BuffTemplate_table.xml',nBuffId=template)
        return row['nEffectType'] in ('35','66') and (not int(row.get('fEffectValB',0)) or int(row['fEffectValB'])&4)

    def _event(self,now,kind,data):
        if kind=='elsa_e':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']: return []
            self.ready = None
            start = self.position_at(now)
            packets = self.sync_speed(now)+[scene(skills=(self._skill_event(381201,start,cast['dest']),))]
            for target in enemies(self,area=True):
                if not in_cone(target.position_at(now),start,cast['dest'],360,60): continue
                packets.extend(self._hit(target,cast['power']*D('1.88'),now))
                if self.arena.pk and self.arena.pk['finished']:
                    return packets
                if target.alive:
                    pos = target.position_at(now)
                    dest = aimed(start,pos,math.dist(start,pos)+216,fixed=True)
                    if not target.cc_immune(now):
                        target._set_motion(pos,dest,480,now,kind=1)
                        target.forced_until = target.motion[3]
                        packets.append(scene(moves=(target._move_event(target.motion[1],480,1),)))
                    packets.extend(self._buff(381203,now,target.id)+self._buff(381204,now,target.id))
            return packets
        if kind=='elsa_ring':
            cast, = data
            packets = self.remove_object(cast['id'])
            ident,packet = self.add_object(381403,cast['pos'])
            packets.append(packet);self._queue(now+1000,'object_expire',ident)
            for target in enemies(self,area=True):
                distance = math.dist(cast['pos'],target.position_at(now))
                if distance>168: continue
                if distance>72: packets.extend(self._buff(381412,now,target.id))
                packets.extend(self._hit(target,cast['power']*D('2.37'),now))
                if distance>72 and target.has_buff(381412,now): packets.extend(self._buff(381415,now,target.id))
            return packets
        if kind=='elsa_wave':
            cast,index = data
            if self.channel is not cast or not self.alive or self.generation!=cast['generation']: return []
            packets = []
            if index==1:
                packets.extend(self.remove_object(cast['id']))
                cast['id'],packet = self.add_object(381302,cast['pos']);packets.append(packet)
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))>216: continue
                building = target.info.get('npc_template') in (20017,20006)
                packets.extend(self._hit(target,cast['power']*D('1.77')*(D('.25') if building else 1),now))
            if index==5: packets.extend(self.interrupt(now))
            else: self._queue(now+750,kind,cast,index+1)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot==2 and self.channel:
            return self.interrupt(now) if now>=self.channel['begin']+1000 else []
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or now<self.cooldowns[slot]: return []
        if slot==10 and not self.r_count or slot in (0,1) and start==dest: return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:25000,10:4000}[slot], slot)
        if slot==0: return self.shoot(381100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        cast = dict(slot=slot,skill=SLOTS[slot],pos=aimed(start,dest,600),dest=dest,power=power,begin=now,generation=self.generation)
        if slot==10:
            self.r_count-=1
            if not self.r_next_charge: self.r_next_charge=now+self.skill_cooldown(8000)
            cast['id'],packet = self.add_object(381401,cast['pos'])
            self._queue(now+650,'elsa_ring',cast)
            return [packet,self._cooldown(10)]
        body,handoff = prepare_displacement(self,now,interrupt=False)
        if not handoff: body = start
        self.position,self.motion = body,None
        packets = [scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),))]
        if slot==1:
            self.ready=cast;self._queue(now+200,'elsa_e',cast)
        else:
            self.channel=cast
            cast['id'],packet=self.add_object(381301,cast['pos']);packets.append(packet)
            for template in (381303,381305,381306,381307,381308): packets.extend(self._buff(template,now))
            self._queue(now+750,'elsa_wave',cast,1)
        return packets+[self._cooldown(slot,slot==2)]+self.sync_speed(now)+handoff
