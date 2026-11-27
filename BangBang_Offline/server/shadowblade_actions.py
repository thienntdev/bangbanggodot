"""Shadowblade: energy snapshots, bounded bounces, breakable links and a field."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import aimed, enemies, piercing_step, prepare_displacement

SLOTS = {0:383100, 1:383201, 2:383301, 10:383401}


class ShadowbladeActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.mp = 100
        self.e_count,self.e_next_charge = 2,0
        self.ready = self.dash = self.hitting = None
        self.links = {}; self.assists = {}

    def _cooldown(self, slot, changed=False):
        skill = 383211 if slot==0 and self.has_buff(383203,self.clock()) else SLOTS[slot]
        body = props(skill,slot,self.e_count if slot==1 else -1,self.cooldowns[slot],self.e_next_charge if slot==1 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self, delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp = self.mp,max(0,min(100,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def _factor(self):return 1+D('.05')*(self.mp//10)

    def _speed(self, now):
        if self.ready or self.dash or 36 in self.buff_types(now):return 0
        return max(0,super()._speed(now)+round(int(self.stats['iSpeed'])*D('.05')*(self.mp//10)))

    def blocked(self, action, now):
        return bool(self.ready or self.dash) or super().blocked(action,now)

    def cc_immune(self, now, *, slow=False):
        return bool(self.dash or self.ready and self.ready['slot']==2) or super().cc_immune(now,slow=slow)

    def reject_buff(self, row, source, now):
        return source.camp!=self.camp and bool(self.dash or self.ready and self.ready['slot']==2)

    def block_hit(self, key, amount, now, *, basic=False, periodic=False, source=None):
        if basic and (self.has_buff(383402,now) or self.has_buff(383345,now)):
            return True,self.restore_hp(amount,now)
        return False,[]

    def on_spawn(self, now):
        self.mp=100;self.ready=self.dash=self.hitting=None;self.links={};self.assists={}
        self._queue(now+1000,'shadow_energy',self.generation)
        packets = [scene(mp=(struct.pack('<Ii',self.id,self.mp),)),self._cooldown(0,True)]
        for t in range(383101,383108):packets.extend(self._buff(t,now))
        return packets

    def remove_buff(self, template, now, *, expired=False):
        packets = super().remove_buff(template,now,expired=expired)
        if template==383203 and self.alive:packets.append(self._cooldown(0,True))
        return packets

    def update(self, now):
        packets = []
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count=min(2,self.e_count+1)
            self.e_next_charge=self.e_next_charge+self.skill_cooldown(8000) if self.e_count<2 else 0
            packets.append(self._cooldown(1))
        self.assists={k:v for k,v in self.assists.items() if v['end']>now}
        return packets+super().update(now)

    def _deal(self, target, raw, now, generation, **kwargs):
        current = self.alive and self.generation==generation
        self.hitting=(target.id,target.generation) if current else None
        try:packets,lost=self.damage(raw,now,target=target,**kwargs)
        finally:self.hitting=None
        if current and lost and target.alive and not target.info.get('npc_template'):
            self.assists[(target.id,target.generation)]=dict(end=now+5000,generation=generation)
        return packets,lost

    def on_target_death(self, target, now):
        key=target.id,target.generation;mark=self.assists.pop(key,None)
        if (not self.alive or target.camp==self.camp or target.info.get('npc_template')
                or not (self.hitting==key or mark and mark['end']>=now and mark['generation']==self.generation)):
            return []
        ratio=D('.15') if self.hitting==key else D('.05')
        packets=self.restore_hp(self.max_hp*ratio,now)+self._resource(int(100*ratio))
        for slot in (2,10):
            self.cooldowns[slot]=now+round(max(0,self.cooldowns[slot]-now)*(1-ratio))
            packets.append(self._cooldown(slot))
        if self.e_next_charge:
            self.e_next_charge=now+round(max(0,self.e_next_charge-now)*(1-ratio))
            packets.append(self._cooldown(1))
        return packets

    def _basic_hit(self, flight, target, now):
        packets,_=self._deal(target,flight['raw'],now,flight['source_generation'],school='energy',basic=True)
        if self.alive and self.generation==flight['source_generation']:packets.extend(self._resource(5))
        return packets

    def _bounce_hit(self, flight, target, now):
        cast=flight['context'];pos=target.position_at(now)
        cast['hits'].add((target.id,target.generation))
        current=self.alive and self.generation==cast['generation']
        packets=[]
        for enemy in enemies(self,area=True):
            if math.dist(pos,enemy.position_at(now))>96:continue
            hit,_=self._deal(enemy,cast['power']*D('1.97')*D('.75')**cast['index'],now,cast['generation'],
                             school='energy',basic=True,lifesteal=D('.25') if current else 0)
            packets.extend(hit)
            for t in (383212,383213):packets.extend(self._buff(t,now,enemy.id))
        if current:packets.extend(self._resource(10))
        cast['index']+=1
        if cast['index']<4:
            from bot_ai import team_visible
            choices=[a for a in enemies(self) if (a.id,a.generation) not in cast['hits']
                     and math.dist(pos,a.position_at(now))<=300 and team_visible(self.arena,self,a,now)]
            if choices:
                following=min(choices,key=lambda a:(math.dist(pos,a.position_at(now)),a.id))
                packets.extend(self.shoot(383221,pos,following.position_at(now),now,0,school='energy',
                                          basic=True,target=following,through_walls=True,context=cast,
                                          attack_key=flight['attack_key']))
        return packets

    def _flight(self, flight, now):
        if flight['template']==383100:return piercing_step(self,flight,now,self._basic_hit,pierce=False)
        if flight['template'] not in (383211,383221):return super()._flight(flight,now)
        cast=flight['context'];flight['source_generation']=cast['generation']
        target=self.arena.actors.get(flight.get('target'));packets=[]
        if target:
            if not target.alive or target.generation!=flight['target_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start,dest=flight['pos'],target.position_at(now)
            end=point_at(start,dest,min(1,flight['speed']*(now-flight['previous'])/1000/max(1,math.dist(start,dest))))
            if dest!=flight['end']:
                packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))))
                flight['end']=dest
            flight['pos']=end
            choices=[target]
        else:
            start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
            end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
            choices=enemies(self)
        contacts=[(h,a.id,a) for a in choices if a.alive and not a.is_untargetable()
                  if (h:=actor_contact(start,end,a,flight['previous'],now)) is not None]
        if contacts:
            _,_,target=min(contacts,key=lambda x:x[:2])
            blocked=self.projectile_blocked(target,now)
            if not blocked:packets.extend(self._bounce_hit(flight,target,now))
            return packets+[scene(**{'expired_bullets' if blocked else 'blown_bullets':(struct.pack('<I',flight['id']),)})]
        if now>=flight['finish']:return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _end_link(self, target, cast, now, *, pull=False):
        self.links.pop(target.id,None)
        if target.generation!=cast['target_generation'] or target.buff_sources.get(383403)!=self.id:return []
        if target.has_buff(383403,now) and target.buff_versions.get(383403)!=cast['version']:return []
        packets=[]
        for t in (383403,383404,383405,383421,383431):packets.extend(target.remove_buff(t,now))
        if pull and target.alive and not target.cc_immune(now):
            pos,stopped=prepare_displacement(target,now)
            packets.extend(stopped)
            dest=self.position_at(now)
            end=aimed(pos,dest,min(72,max(0,math.dist(pos,dest)-72)))
            elapsed=target._set_motion(pos,end,720,now,1);target.forced_until=now+elapsed
            packets.append(scene(moves=(self._move_event(target.motion[1],720,1,target.id),)))
            self._queue(now+elapsed,'shadow_link_slow',target.id,target.generation)
        return packets

    def _link_step(self, cast, now):
        target=self.arena.actors.get(cast['target'])
        if not target or self.links.get(target.id) is not cast:return []
        if (not self.alive or self.generation!=cast['generation'] or not target.alive
                or target.generation!=cast['target_generation'] or now>cast['end']
                or target.buff_versions.get(383403)!=cast['version']
                or target.buff_versions.get(383404)!=cast['debuff_version']):
            return self._end_link(target,cast,now)
        if math.dist(self.position_at(now),target.position_at(now))>300:
            return self._end_link(target,cast,now,pull=True)
        packets=[]
        if now>=cast['next_tick_at']:
            packets.extend(self._deal(target,cast['power']*D('.5'),now,cast['generation'],school='energy',periodic=True)[0])
            cast['next_tick_at']+=1000
        if now>=cast['end']:return packets+self._end_link(target,cast,now)
        self._queue(min(now+100,cast['end']),'shadow_link',cast)
        return packets

    def _clear_form(self, now):
        self.ready=self.dash=None
        self.info.pop('untargetable',None);self.info.pop('damage_immune',None)
        packets=[]
        for t in (383302,383303,383304,383305,383312,383313,383314):packets.extend(self.remove_buff(t,now))
        return packets+self.sync_speed(now)

    def interrupt(self, now):
        if self.alive and (self.dash or self.ready and self.ready['slot']==2):return []
        packets=[]
        if self.ready:packets.append((1583,struct.pack('<II',self.id,SLOTS[self.ready['slot']])))
        packets.extend(self._clear_form(now))
        if not self.alive:
            for ident,cast in list(self.links.items()):
                target=self.arena.actors.get(ident)
                if target:packets.extend(self._end_link(target,cast,now))
        return packets

    def on_control(self, source, template, now):
        kind=int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType'])
        return self.interrupt(now) if self.ready and self.ready['slot']==1 and kind in (30,35,66) else []

    def _field_hit(self, target, cast, now, raw):
        packets,lost=self._deal(target,raw,now,cast['generation'],school='energy',periodic=cast.get('index',0)>0)
        key=target.id,target.generation
        if lost and key not in cast['hits']:
            cast['hits'].add(key)
            if self.alive and self.generation==cast['generation']:packets.extend(self._buff(383323,now))
        return packets

    def _field(self, cast, now):
        cast['index']+=1
        packets=[]
        for target in enemies(self,area=True):
            if math.dist(cast['pos'],target.position_at(now))<=216:
                packets.extend(self._field_hit(target,cast,now,cast['power']*D('.18')))
                if now<cast['end']:
                    for t in (383342,383343):packets.extend(self._buff(t,now,target.id,duration=min(300,cast['end']-now)))
        if self.alive and self.generation==cast['generation'] and math.dist(cast['pos'],self.position_at(now))<=216:
            packets.extend(self._resource(5))
            if now<cast['end']:packets.extend(self._buff(383345,now,duration=min(300,cast['end']-now)))
        if now<cast['end']:self._queue(now+250,'shadow_field',cast)
        # The completed field has a native closing movie (si_yingren_k04).
        else:packets.extend(self.remove_object(cast['id'],destroyed=True))
        return packets

    def _arrive(self, cast, now):
        pos=self.position_at(now);self.position,self.motion,self.forced_until=pos,None,now
        packets=[scene(moves=(self._move_event(pos,0,5),))]+self._clear_form(now)
        packets.append(scene(skills=(self._skill_event(383311,pos,pos),)))
        packets.extend(self._buff(383315,now))
        ident,packet=self.add_object(383321,pos);packets.append(packet)
        self._queue(now+250,'object_expire',ident)
        ident,packet=self.add_object(383331,pos);packets.append(packet)
        cast.update(id=ident,pos=pos,end=now+3000,hits=set(),index=0)
        for target in enemies(self,area=True):
            if math.dist(pos,target.position_at(now))<=216:
                packets.extend(self._field_hit(target,cast,now,cast['power']*D('3.19')))
                for t in (383342,383343):packets.extend(self._buff(t,now,target.id))
        if self.alive:packets.extend(self._buff(383345,now))
        self._queue(now+250,'shadow_field',cast)
        return packets

    def _event(self, now, kind, data):
        if kind=='shadow_energy':
            if not self.alive or self.generation!=data[0]:return []
            self._queue(now+1000,kind,*data)
            return self._resource(-5)
        if kind=='shadow_link':return self._link_step(data[0],now)
        if kind=='shadow_link_slow':
            target=self.arena.actors.get(data[0])
            return self._buff(383461,now,target.id) if target and target.alive and target.generation==data[1] else []
        if kind=='shadow_field':return self._field(data[0],now)
        if kind=='shadow_ready':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None
            pos=self.position_at(now)
            if cast['slot']==1:
                self.position,self.motion,self.forced_until=self.blink_destination(pos,cast['dest']),None,now
                packets=[scene(moves=(self._move_event(self.position,0,5),)),
                               scene(skills=(self._skill_event(383201,pos,self.position),))]
                for t in (383201,383203,383204,383205):packets.extend(self._buff(t,now))
                return packets+[self._cooldown(0,True)]+self.sync_speed(now)
            packets=[]
            for t in (383312,383313,383314):packets.extend(self.remove_buff(t,now))
            for t in (383302,383303,383304,383305):packets.extend(self._buff(t,now))
            elapsed=self._set_motion(pos,cast['dest'],960,now,3);self.forced_until=now+elapsed
            self.dash=cast
            packets.append(scene(moves=(self._move_event(self.motion[1],960,3),)))
            self._queue(now+min(20,elapsed),'shadow_dash',cast)
            return packets
        if kind=='shadow_dash':
            cast,=data
            if self.dash is not cast or not self.alive:return []
            if not self.motion or now>=self.motion[3]:return self._arrive(cast,now)
            self._queue(min(now+20,self.motion[3]),kind,cast)
            return []
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot==1 and not self.e_count or slot==0 and start==dest:return []
        power=self.combat_stat('iEgAtk',now)*self._factor()
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:3000,2:25000,10:10000}[slot], slot)
        if slot==0:
            if not self.has_buff(383203,now):
                return self.shoot(383100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
            cast=dict(power=power,generation=self.generation,hits=set(),index=0)
            packets=self.shoot(383211,start,dest,now,0,school='energy',basic=True,through_walls=True,context=cast)
            for t in (383203,383204):packets.extend(self.remove_buff(t,now))
            return packets+[self._cooldown(0)]
        if slot in (1,2):
            pos=aimed(start,dest,240 if slot==1 else 720)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body if stopped else start,None
            cast=dict(slot=slot,dest=pos,power=power,generation=self.generation)
            self.ready=cast
            packets=[scene(skills=(self._skill_event(SLOTS[slot],start,pos,ready=1),))]
            if slot==1:
                self.e_count-=1
                if not self.e_next_charge:self.e_next_charge=now+self.skill_cooldown(8000)
            else:
                self.info['untargetable']=self.info['damage_immune']=True
                ident,packet=self.add_object(383311,pos);packets.append(packet)
                self._queue(now+1000,'object_expire',ident)
                for t in (383312,383313,383314):packets.extend(self._buff(t,now))
            self._queue(now+(100 if slot==1 else 500),'shadow_ready',cast)
            return packets+[self._cooldown(slot)]+self.sync_speed(now)+stopped
        packets=[scene(skills=(self._skill_event(383401,start,start),))]
        lost_any=False
        for target in enemies(self,area=True):
            if math.dist(start,target.position_at(now))>216:continue
            hit,lost=self._deal(target,power*D('1.5'),now,self.generation,school='energy')
            packets.extend(hit);lost_any=lost_any or lost
            if not target.alive:continue
            for t in (383403,383404,383405):packets.extend(self._buff(t,now,target.id))
            if not target.has_buff(383403,now):continue
            cast=dict(target=target.id,target_generation=target.generation,generation=self.generation,
                      power=power,end=now+3000,next_tick_at=now+1000,version=target.buff_versions[383403],
                      debuff_version=target.buff_versions[383404])
            self.links[target.id]=cast;self._queue(now+100,'shadow_link',cast)
        if self.links:packets.extend(self._buff(383406,now))
        if lost_any:packets.extend(self._buff(383402,now))
        return packets+[self._cooldown(10)]
