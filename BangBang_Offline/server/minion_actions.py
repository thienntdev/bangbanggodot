"""Minion: owner-only component drops, two reserves and persistent native NPCs."""
from dataclasses import replace
import math
import struct

from battle_runtime import TankActions
from hulu_actions import HuluTurret
from combat_geometry import rect_contact
from combat_math import D,quantize
from combat_protocol import props,scene
from melee_common import enemies,in_strip,prepare_displacement

SLOTS={0:335100,1:335201,2:335301,10:335401}


class MinionActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=100;self.e_count=2;self.e_next_charge=0;self.ready=None
        self.components={};self.turret_marks={}

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,self.e_count if slot==1 else -1,
            self.cooldowns[slot],self.e_next_charge if slot==1 else 0)+struct.pack('<I',self.id)

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(100,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self,now):
        self.mp=100;self.ready=None
        self._queue(now+1000,'minion_energy',self.generation)
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),)),self._cooldown(1)]

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def interrupt(self,now):
        if not self.ready:return []
        self.ready=None;self.cooldowns[10]=now+self.skill_cooldown(3000, 10)
        return [(1583,struct.pack('<II',self.id,335401)),self._cooldown(10)]+self.sync_speed(now)

    def update(self,now):
        packets=[]
        self.turret_marks={k:v for k,v in self.turret_marks.items() if v['end']>now}
        if self.ready and (super().blocked('attack',now) or self.skill_sealed(10,now)):
            packets.extend(self.interrupt(now))
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count=min(2,self.e_count+1)
            self.e_next_charge=self.e_next_charge+self.skill_cooldown(6000) if self.e_count<2 else 0
            packets.append(self._cooldown(1))
        return packets+super().update(now)

    def damage(self,raw,now,**kwargs):
        target=kwargs.get('target') or self.enemy
        if kwargs.get('basic') and target.has_buff(335311,now) and target.buff_sources.get(335311)==self.id:
            raw*=D('1.25')
        return super().damage(raw,now,**kwargs)

    def drop_component(self,entity,pos,generation,now):
        # Entity IDs never repeat within this arena. The owning event removes
        # its entity before calling this method, so expiry/death cannot double.
        ident,packet=self.add_object(335101,pos)
        item=dict(id=ident,entity=entity,pos=pos,generation=generation,end=now+5000)
        self.components[ident]=item;self._queue(now+100,'minion_pickup',item)
        return [packet]

    def _pickup(self,item,now):
        self.components.pop(item['id'],None)
        packets=self.remove_object(item['id'])+self._resource(10)
        for slot in (2,10):
            self.cooldowns[slot]=max(now,self.cooldowns[slot]-4000);packets.append(self._cooldown(slot))
        if self.e_next_charge:self.e_next_charge=max(now,self.e_next_charge-4000)
        packets.extend(self.update(now));packets.append(self._cooldown(1))
        power=self.combat_stat('iAttack',now)
        packets.extend(self.add_shield(335103,power,now))
        if self.has_buff(335103,now):
            version=self.buff_versions[335103]
            for i in range(1,5):self._queue(now+i*1000,'minion_shield',self.generation,version,power*D('.1'))
        return packets

    def _device_area(self,cast,now):
        packets=[]
        for target in enemies(self,area=True):
            distance=math.dist(cast['pos'],target.position_at(now))
            if distance<=240:
                for template in (335311,335312):packets.extend(self._buff(template,now,target.id))
            if 240<=distance<=264:
                for template in (335313,335314):packets.extend(self._buff(template,now,target.id))
        if self.alive and self.generation==cast['generation'] and math.dist(cast['pos'],self.position_at(now))<=264:
            packets.extend(self._buff(335315,now))
        return packets

    def _event(self,now,kind,data):
        if kind=='minion_energy':
            if not self.alive or self.generation!=data[0]:return []
            self._queue(now+1000,kind,*data);return self._resource(5)
        if kind=='minion_laser':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            if super().blocked('attack',now) or self.skill_sealed(10,now):return self.interrupt(now)
            self.ready=None;start=self.position_at(now)
            packets=[scene(skills=(self._skill_event(335401,start,cast['dest']),))]+self.sync_speed(now)
            for target in enemies(self,area=True):
                if in_strip(target.position_at(now),start,cast['dest'],600,96):
                    packets.extend(self.damage(cast['power']*D('1.99'),now,target=target)[0])
                    packets.extend(self._buff(335402,now,target.id))
            return packets
        if kind=='minion_pickup':
            item,=data
            if self.components.get(item['id']) is not item:return []
            if now>=item['end']:
                self.components.pop(item['id']);return self.remove_object(item['id'])
            if self.alive and self.generation==item['generation'] and math.dist(self.position_at(now),item['pos'])<=72:
                return self._pickup(item,now)
            self._queue(min(now+100,item['end']),kind,item);return []
        if kind=='minion_shield':
            generation,version,amount=data
            if not self.alive or self.generation!=generation or self.buff_versions.get(335103)!=version:return []
            shield=next((s for s in self.shields if s.shield_id=='335103'),None)
            if not shield:return []
            self.shields=tuple(replace(s,remaining=quantize(max(D(0),s.remaining-amount))) if s is shield else s for s in self.shields)
            return [self.shield_packet(now)]
        if kind=='minion_device_start':
            cast,=data
            packets=self.remove_object(cast['prepare'])
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))<=240:
                    packets.extend(self.damage(cast['power']*D('3.98'),now,target=target)[0])
            ident=self._new_id(5);buff=self._new_id(6)
            body=struct.pack('<IIhhiBiIiH',ident,20007,*cast['pos'],1,self.camp,1,self.id,0,1)+struct.pack('<IIBI',335321,buff,1,3000)
            self.arena.objects[ident]=body.hex();cast['id']=ident;cast['end']=now+3000
            packets.append((1556,struct.pack('<I',self.scene_id)+body))
            packets.extend(self._device_area(cast,now));self._queue(now+100,'minion_device_tick',cast)
            return packets
        if kind=='minion_device_tick':
            cast,=data
            if now>=cast['end']:
                packets=self.remove_object(cast['id'],destroyed=True)+self.remove_object(cast['visual'])
                return packets+self.drop_component(cast['id'],cast['pos'],cast['generation'],now)
            self._queue(now+100,kind,cast);return self._device_area(cast,now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot in (0,10) and start==dest:return []
        if slot in (1,2) and (not self._inside(dest) or math.dist(start,dest)>(480 if slot==1 else 600)):return []
        if slot==1 and (self.e_count<1 or self.mp<30 or self.arena.geometry.clamp_tank_position(dest)!=dest
                       or self.arena.geometry.wall_contact(dest,dest,36) is not None or rect_contact(dest,dest,self.arena.water_rects(now),36) is not None):return []
        power=self.combat_stat('iAttack',now);packets=[]
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:1000,2:25000,10:8000}[slot], slot)
        if slot==0:return self.shoot(335100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        if slot==10:
            body,stopped=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body if stopped else start,None
            self.ready=dict(slot=10,dest=dest,power=power)
            self._queue(now+600,'minion_laser',self.ready)
            return [scene(skills=(self._skill_event(335401,start,dest,ready=1),)),self._cooldown(10)]+self.sync_speed(now)+stopped
        packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,dest),)))
        if slot==1:
            self.e_count-=1
            if not self.e_next_charge:self.e_next_charge=now+self.skill_cooldown(6000)
            packets.extend(self._resource(-30))
            stats=dict(self.stats)
            for key in ('iAttack','iEgAtk','iArmor','iEgArmor','iCentesis','iEgCtsis'):stats[key]=str(self.combat_stat(key,now))
            stats.update(iHp=str(self.max_hp*D('.6')),iSpeed='0',iFireInterv='1000',nFireRange='480')
            info=dict(acct_id=self.info['acct_id'],tank_level=self.info['tank_level'],npc_template=20006,
                owner=self.id,owner_generation=self.generation,tank_id=10000060,name='Minion',in_room=True,summon_stats=stats)
            turret=MinionTurret(self.arena,self._new_id(5),info,self.camp,dest)
            self.arena.actors[turret.id]=turret;packets.extend([turret.snapshot(now)]+turret.on_spawn(now))
        else:
            prepare,p=self.add_object(335301,dest);visual,v=self.add_object(335304,dest)
            packets.extend([p,v]);cast=dict(prepare=prepare,visual=visual,pos=dest,power=power,generation=self.generation)
            self._queue(now+1000,'minion_device_start',cast)
        return packets+[self._cooldown(slot)]


class MinionTurret(HuluTurret):
    def snapshot(self,now):
        body=struct.pack('<IIhhiBiIiH',self.id,20006,*self.position_at(now),math.ceil(self.hp),self.camp,
            math.ceil(self.max_hp),self.info['owner'],math.ceil(sum(s.remaining for s in self.shields if s.expires_ms>now)),0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def on_spawn(self,now):
        self.passive_ready_at=now+1000
        self.component_dropped=False;self._queue(now+1000,'minion_turret_tick',1)
        return self._buff(335221,now)

    def commit_hp(self,hp,now,*,critical=False):
        before=self.alive;packets=super().commit_hp(hp,now,critical=critical)
        if before and not self.alive and not self.component_dropped:
            from borrowed_e import owner_executor
            self.component_dropped=True;owner=owner_executor(self.arena,self.info)
            if owner:packets.extend(owner.drop_component(self.id,self.position_at(now),self.info['owner_generation'],now))
        return packets

    def _flight(self,flight,now):
        # Homing motion and native fire/blow packets remain in the shared engine.
        return TankActions._flight(self,flight,now)

    def damage(self,raw,now,**kwargs):
        from borrowed_e import owner_executor
        target=kwargs.get('target') or self.enemy;owner=owner_executor(self.arena,self.info)
        if kwargs.get('basic') and owner:
            key=(self.info['owner_generation'],target.id,target.generation)
            mark=owner.turret_marks.get(key,{})
            stacks=mark.get('stacks',0) if mark.get('end',0)>now else 0
            raw*=1+D('.025')*stacks
            if target.has_buff(335312,now) and target.buff_sources.get(335312)==owner.id:raw*=D('1.25')
            packets,lost=TankActions.damage(self,raw,now,**kwargs)
            if target.alive:
                owner.turret_marks[key]=dict(stacks=min(40,stacks+1),end=now+1500)
                packets.extend(self._buff(335212,now,target.id,stacks=min(40,stacks+1)))
            return packets,lost
        return TankActions.damage(self,raw,now,**kwargs)

    def taunt_attack(self,target,now):
        start=self.position_at(now);dest=target.position_at(now)
        if (not self.alive or not target.alive or target.is_untargetable() or self.blocked('attack',now)
                or self.skill_sealed(0,now) or now<self.passive_ready_at or math.dist(start,dest)>480
                or self.arena.geometry.wall_contact(start,dest) is not None
                or rect_contact(start,dest,self.arena.water_rects(now)) is not None):return []
        self.passive_ready_at=now+1000
        return self.shoot(335211,start,dest,now,self.combat_stat('iAttack',now)*D('.5'),school='physical',basic=True,target=target)

    def _event(self,now,kind,data):
        if kind=='minion_turret_tick':
            if not self.alive:return []
            tick,=data
            packets=self.commit_hp(D(0) if tick>=20 else max(D(0),self.hp-self.max_hp*D('.05')),now)
            if not self.alive:return packets
            start=self.position_at(now)
            from bot_ai import observable,team_visible
            candidates=[t for t in enemies(self) if math.dist(start,t.position_at(now))<=480
                and (observable(self.arena,self,t,now) or team_visible(self.arena,self,t,now))
                and self.arena.geometry.wall_contact(start,t.position_at(now)) is None and rect_contact(start,t.position_at(now),self.arena.water_rects(now)) is None]
            if candidates and not self.blocked('attack',now) and not self.skill_sealed(0,now):
                target=min(candidates,key=lambda t:(math.dist(start,t.position_at(now)),t.id))
                packets.extend(self.taunt_attack(target,now))
            self._queue(now+1000,kind,tick+1);return packets
        return TankActions._event(self,now,kind,data)
