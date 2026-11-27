"""Sima Yi: finite orb objects, bounded push contacts and per-target volleys."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from hulu_actions import HuluTurret
from melee_common import aimed, enemies, in_cone, piercing_step, prepare_displacement

SLOTS={0:373100,1:373201,2:373301,10:373401}


class SimayiActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.e_count,self.e_next_charge=3,0
        self.r_count,self.r_next_charge=2,0
        self.orb_count=0

    def _cooldown(self,slot,changed=False):
        skill=373310+self.orb_count*10 if slot==2 and self.orb_count else SLOTS[slot]
        body=props(skill,slot,self.e_count if slot==1 else self.r_count if slot==10 else -1,self.cooldowns[slot],
                   self.e_next_charge if slot==1 else self.r_next_charge if slot==10 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _orbs(self,count,now):
        self.orb_count=min(3,count);packets=[]
        for t in (373102,373103,373104):packets.extend(self.remove_buff(t,now))
        if self.orb_count:packets.extend(self._buff(373101+self.orb_count,now))
        return packets+[self._cooldown(2,True)]

    def on_spawn(self,now):
        self.orb_count=0;self._queue(now+5000,'sima_passive',self.generation)
        return self._buff(373101,now)+self._buff(373111,now)+[self._cooldown(2,True)]

    def update(self,now):
        packets=[]
        for field,maximum,period,slot in (('e',3,6000,1),('r',2,8000,10)):
            end=getattr(self,field+'_next_charge')
            while end and end<=now:
                count=min(maximum,getattr(self,field+'_count')+1);setattr(self,field+'_count',count)
                end=end+self.skill_cooldown(period) if count<maximum else 0
                setattr(self,field+'_next_charge',end);packets.append(self._cooldown(slot))
        return packets+super().update(now)

    def _hit(self,raw,target,now,generation):
        was_alive=target.alive
        packets=self.damage(raw,now,target=target,school='energy')[0]
        if was_alive and not target.alive and not target.info.get('npc_template') and self.alive and self.generation==generation:
            packets.extend(self._orbs(3,now));self.cooldowns[2]=now;packets.append(self._cooldown(2))
        return packets

    def on_bullet_hit(self,flight,target,now):
        if flight['template']==373100:
            was_alive=target.alive
            packets=self.damage(flight['raw'],now,target=target,school='energy',basic=True)[0]
            if was_alive and not target.alive and not target.info.get('npc_template') and self.alive and self.generation==flight['source_generation']:
                packets.extend(self._orbs(3,now));self.cooldowns[2]=now;packets.append(self._cooldown(2))
            return packets
        return super().on_bullet_hit(flight,target,now)

    def _new_orb(self,pos,power,generation,now):
        pos=self.arena.free_position(pos,now)
        if pos is None:return []
        info=dict(acct_id=self.info['acct_id'],tank_id=self.info['tank_id'],tank_level=self.info['tank_level'],
                  npc_template=373201,owner=self.id,source_generation=generation,name='Orb',in_room=True,
                  untargetable=True,damage_immune=True)
        orb=SimaOrb(self.arena,self._new_id(5),info,self.camp,pos)
        orb.power=power;orb.end=now+8000
        self.arena.actors[orb.id]=orb
        orb._queue(orb.end,'sima_orb_expire')
        packets=[orb.snapshot(now)]
        for t in (373202,373203,373204,373440):packets.extend(orb._buff(t,now,duration=8000))
        return packets

    def _reduce(self,now,generation):
        if not self.alive or self.generation!=generation:return []
        for attr in ('e_next_charge','r_next_charge'):
            value=getattr(self,attr)
            if value>now:setattr(self,attr,now+round((value-now)*D('.9')))
        self.cooldowns[2]=now+round(max(0,self.cooldowns[2]-now)*D('.9'))
        return [self._cooldown(s) for s in (1,2,10)]

    def _flight(self,flight,now):
        if flight['template']==373100:return piercing_step(self,flight,now,self.on_bullet_hit,pierce=False)
        target=self.arena.actors.get(flight['target'])
        if not target or not target.alive or target.generation!=flight['target_generation']:
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        start=flight['pos'];dest=target.position_at(now)
        end=point_at(start,dest,min(1,flight['speed']*(now-flight['previous'])/1000/max(1,math.dist(start,dest))))
        packets=[]
        if dest!=flight['end']:packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))))
        flight['pos']=end;flight['end']=dest
        contacts=[(h,t.id,t) for t in enemies(self)
                  if (h:=actor_contact(start,end,t,flight['previous'],now)) is not None]
        if contacts:
            _,_,other=min(contacts,key=lambda v:v[:2]);blocked=self.projectile_blocked(other,now)
            if not blocked:
                cast=flight['context'];key=other.id,other.generation
                mark=cast['hits'].get(key)
                count=mark['count'] if mark and mark['end']>now and other.buff_versions.get(373311)==mark['version'] else 0
                packets.extend(self._hit(cast['power']*(1+D('.5')*count),other,now,cast['generation']))
                for t in range(373311,373315):packets.extend(self._buff(t,now,other.id,stacks=min(10,count+1)))
                if other.has_buff(373311,now):cast['hits'][key]=dict(count=min(10,count+1),end=now+1000,version=other.buff_versions[373311])
                if self.alive and self.generation==cast['generation']:packets.extend(self.restore_hp(cast['power']*D('.5'),now))
            return packets+[scene(**{'expired_bullets' if blocked else 'blown_bullets':(struct.pack('<I',flight['id']),)})]
        if now>=flight['finish']:return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight);return packets

    def _event(self,now,kind,data):
        if kind=='sima_remaining':
            return self._buff(373106,now) if self.alive and self.generation==data[0] else []
        if kind=='sima_passive':
            generation,=data
            if not self.alive or self.generation!=generation:return []
            self._queue(now+5000,kind,generation)
            return self._orbs(self.orb_count+1,now) if self.orb_count<3 else []
        if kind=='sima_create':
            cast,=data;packets=self.remove_object(cast['id'])
            for target in enemies(self,area=True):
                if math.dist(cast['pos'],target.position_at(now))<=108:packets.extend(self._hit(cast['power']*D('1.83'),target,now,cast['generation']))
            return packets+self._new_orb(cast['pos'],cast['power'],cast['generation'],now)
        if kind=='sima_volley':
            cast,origin,template=data
            target=self.arena.actors.get(cast['target'])
            if not self.alive or self.generation!=cast['generation'] or not target or not target.alive or target.generation!=cast['target_generation']:return []
            pos=origin or self.position_at(now)
            return self.shoot(template,pos,target.position_at(now),now,0,school='energy',target=target,through_walls=True,context=cast)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or now<self.cooldowns[slot]:return []
        if slot in (0,10) and start==dest or slot==1 and not self.e_count or slot==10 and not self.r_count:return []
        from bot_ai import team_visible
        target=self.arena.actors.get(target_id)
        if slot==2 and (not target or target not in enemies(self) or math.dist(start,target.position_at(now))>720
                       or not team_visible(self.arena,self,target,now)):return []
        power=self.combat_stat('iEgAtk',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:2000,2:20000,10:2000}[slot], slot)
        if slot==0:return self.shoot(373100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        if slot==1:
            self.e_count-=1
            if not self.e_next_charge:self.e_next_charge=now+self.skill_cooldown(6000)
            pos=aimed(start,dest,600);ident,p=self.add_object(373201,pos)
            self._queue(now+950,'object_expire',ident)
            second,q=self.add_object(373202,pos)
            self._queue(now+300,'sima_create',dict(pos=pos,power=power,generation=self.generation,id=second))
            return [p,q,self._cooldown(1)]
        if slot==10:
            self.r_count-=1
            if not self.r_next_charge:self.r_next_charge=now+self.skill_cooldown(8000)
            packets=[scene(skills=(self._skill_event(373401,start,dest),)),self._cooldown(10)]
            # Snapshot objects first: contact-created orbs cannot join this push.
            orbs=[a for a in self.arena.actors.values() if isinstance(a,SimaOrb) and a.alive and a.info['owner']==self.id
                  and in_cone(a.position_at(now),start,dest,384,45)]
            for other in enemies(self,area=True):
                pos=other.position_at(now)
                if not in_cone(pos,start,dest,384,45):continue
                packets.extend(self._hit(power*D('1.83'),other,now,self.generation))
                if self.arena.pk and self.arena.pk['finished']:
                    return packets
                if other.alive and not other.cc_immune(now):
                    pos,stopped=prepare_displacement(other,now,interrupt=False)
                    packets.extend(stopped)
                    other._set_motion(pos,aimed(start,pos,math.dist(start,pos)+168,fixed=True),504,now,kind=1)
                    other.forced_until=other.motion[3];packets.append(scene(moves=(other._move_event(other.motion[1],504,1),)))
                packets.extend(self._buff(373404,now,other.id))
            for orb in orbs:
                pos=orb.position_at(now);endpoint=aimed(start,pos,math.dist(start,pos)+480,fixed=True)
                duration=orb._set_motion(pos,endpoint,960,now,kind=1)
                cast=dict(previous=now,finish=now+duration,motion=orb.motion,hits=set(),power=power,generation=self.generation)
                orb.push=cast;orb._queue(now+min(20,duration),'sima_orb_push',cast)
                packets.extend(orb._buff(373403,now)+[scene(moves=(orb._move_event(orb.motion[1],960,1),))])
            return packets
        orbs=[a for a in self.arena.actors.values() if isinstance(a,SimaOrb) and a.alive and a.info['owner']==self.id]
        cast=dict(target=target.id,target_generation=target.generation,power=power,generation=self.generation,hits={})
        count=self.orb_count;template=373310+count*10 if count else 373301
        packets=[scene(skills=(self._skill_event(template,start,target.position_at(now),target.id),))]
        packets.extend(self._buff(373301,now,target.id)+self._buff(373350,now,target.id)+self._buff(373330,now))
        for index in range(count):self._queue(now+index*500,'sima_volley',cast,None,template)
        if count>=2:packets.extend(self._buff(373105 if count==3 else 373106,now))
        if count==3:self._queue(now+500,'sima_remaining',self.generation)
        packets.extend(self._orbs(0,now))
        for orb in orbs:
            pos=orb.position_at(now)
            self._queue(now,'sima_volley',cast,pos,373310)
            packets.extend(orb.despawn(now))
        return packets+[self._cooldown(2)]


class SimaOrb(TankActions):
    _respawn=HuluTurret._respawn

    def __init__(self,*args):
        super().__init__(*args)
        self.cooldowns={};self.power=D(0);self.end=0;self.push=None

    def snapshot(self,now):
        body=struct.pack('<IIhhiBiIiH',self.id,373201,*self.position_at(now),math.ceil(self.hp),self.camp,
                         math.ceil(self.max_hp),self.info['owner'],0,0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def sync_speed(self,now):return []

    def despawn(self,now):
        if not self.alive:return []
        self.position,self.motion=self.position_at(now),None;self.hp=D(0);self.info['hp']=0;self.push=None
        # Orbs expire/are consumed without a combat death or kill rewards.
        # Still reclaim the tombstone once its delayed references are done.
        self._queue(now+2000,'respawn',self.generation)
        packets=[]
        for owner,template in list(self.active_buffs):
            if owner==self.id:packets.extend(self.remove_buff(template,now))
        return packets+[scene(removed=(struct.pack('<I',self.id),))]

    def _event(self,now,kind,data):
        # Legacy expired borrowed orbs may outlive their pruned copy session.
        # Tombstone cleanup needs no combat source, only pending references.
        if kind=='respawn':return super()._event(now,kind,data)
        from borrowed_e import owner_executor
        owner=owner_executor(self.arena,self.info)
        if kind=='sima_orb_expire':
            if not self.alive:return []
            pos=self.position_at(now);packets=[scene(skills=(self._skill_event(373430,pos,pos),))]
            for target in enemies(owner,area=True):
                if math.dist(pos,target.position_at(now))<=96:packets.extend(owner._hit(self.power*D('1.83'),target,now,self.info['source_generation']))
            return packets+self.despawn(now)
        if kind=='sima_orb_push':
            cast,=data
            if not self.alive or self.push is not cast:return []
            start,end=self.position_at(cast['previous']),self.position_at(now);packets=[]
            for target in enemies(owner):
                key=target.id,target.generation
                if key in cast['hits'] or actor_contact(start,end,target,cast['previous'],now) is None:continue
                cast['hits'].add(key);pos=target.position_at(now)
                packets.extend(owner._hit(cast['power']*D('2.04'),target,now,cast['generation']))
                packets.extend(owner._reduce(now,cast['generation'])+owner._buff(373421,now,target.id))
                packets.extend(owner._new_orb(pos,cast['power'],cast['generation'],now))
            if not self.motion or now>=self.motion[3] or now>=cast['finish']:
                self.position,self.motion=end,None;self.push=None
                return packets+self.remove_buff(373403,now)
            cast['previous']=now;self._queue(min(now+20,self.motion[3],cast['finish']),kind,cast);return packets
        return super()._event(now,kind,data)
