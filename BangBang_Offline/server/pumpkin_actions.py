"""Pumpkin: consumable traps, finite soul volleys and native NPC20001 ghosts."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene,move_event
from hulu_actions import HuluTurret
from melee_common import aimed,enemies,prepare_displacement,accept_water_reclip

SLOTS={0:327100,1:327201,2:327301,10:327401}


class PumpkinActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.e_count=2;self.e_next_charge=0
        self.ready=self.volley=None

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,self.e_count if slot==1 else -1,self.cooldowns[slot],self.e_next_charge if slot==1 else 0)+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.ready=self.volley=None
        return self._buff(327102,now)

    def _speed(self,now):return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):return bool(self.ready) or super().blocked(action,now)

    def interrupt(self,now):
        packets=[]
        if self.ready:
            self.ready=None;packets.append((1583,struct.pack('<II',self.id,327301)))
        if not self.alive and self.volley:
            self.volley=None;self.cooldowns[10]=now+self.skill_cooldown(10000, 10);packets.append(self._cooldown(10))
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        return self.interrupt(now) if self.ready and int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']) in (30,35,66) else []

    def update(self,now):
        packets=[]
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count=min(2,self.e_count+1);self.e_next_charge=self.e_next_charge+self.skill_cooldown(8000) if self.e_count<2 else 0
            packets.append(self._cooldown(1))
        return packets+super().update(now)

    def _summon_stats(self,now):
        stats=dict(self.stats)
        for k in ('iAttack','iEgAtk','iArmor','iEgArmor','iCentesis','iEgCtsis'):stats[k]=str(self.combat_stat(k,now))
        stats.update(iHp=str(self.max_hp*D('.5')),iSpeed='150',iFireInterv='1500',nFireRange='96')
        return stats

    def on_target_death(self,target,now):
        if not self.alive or target.camp==self.camp or target.info.get('npc_template'):return []
        owners=[a.id for a in self.arena.actors.values() if a.alive and a.camp==self.camp and a.info['tank_id']==10000052 and not a.info.get('npc_template')]
        if self.id==min(owners):self._queue(now,'pumpkin_spawn',target.position_at(now),self._summon_stats(now),self.generation)
        return []

    def _spawn_ghost(self,pos,stats,generation,now):
        pos=self.blink_destination(self.position_at(now),pos)
        info=dict(acct_id=self.info['acct_id'],tank_level=self.info['tank_level'],npc_template=20001,
                  owner=self.id,source_generation=generation,tank_id=10000052,name='Hồn Bí Ngô',in_room=True,summon_stats=dict(stats))
        ghost=PumpkinGhost(self.arena,self._new_id(5),info,self.camp,pos)
        self.arena.actors[ghost.id]=ghost
        return [ghost.snapshot(now)]+ghost.on_spawn(now)

    def _explosion(self,flight,pos,now):
        distance=min(960,math.dist(flight['start'],pos));raw=flight['power']*(D('1.11')+D('6.66')*D(str(distance))/960)
        packets=[]
        for target in enemies(self,area=True):
            if math.dist(pos,target.position_at(now))<=192:
                packets.extend(self.damage(raw,now,target=target,school='energy')[0]+self._buff(327302,now,target.id))
        ident,packet=self.add_object(327303,pos);packets.append(packet)
        self._queue(now+1000,'pumpkin_portal',dict(id=ident,pos=pos,stats=flight['context']['stats'],generation=flight['source_generation']),1)
        return packets

    def _flight(self,flight,now):
        template=flight['template']
        if template==327100:return super()._flight(flight,now)
        ident=struct.pack('<I',flight['id'])
        if template==327201:
            if now<flight['finish']:
                flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight);return []
            obj,packet=self.add_object(327201,flight['end'])
            self._queue(now,'pumpkin_trap',dict(id=obj,pos=flight['end'],power=flight['power'],end=now+45000,generation=flight['source_generation']))
            return [scene(blown_bullets=(ident,)),packet]
        if template==327411:
            target=self.arena.actors.get(flight['target'])
            if not target or not target.alive or target.generation!=flight['target_generation']:return [scene(expired_bullets=(ident,))]
            start=flight['pos'];dest=target.position_at(now)
            end=point_at(start,dest,min(1,flight['speed']*(now-flight['previous'])/1000/max(1,math.dist(start,dest))))
            packets=[]
            if dest!=flight['end']:
                packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))));flight['end']=dest
            contact=circle_contact(start,end,target.position_at(flight['previous']),dest)
            if contact is not None:
                if self.projectile_blocked(target,now):return packets+[scene(expired_bullets=(ident,))]
                packets.extend(self.damage(flight['raw'],now,target=target,school='energy')[0])
                if self.alive and self.generation==flight['source_generation']:packets.extend(self.restore_hp((self.max_hp-self.hp)*D('.05'),now))
                return packets+[scene(blown_bullets=(ident,))]
            if now>=flight['finish']:return packets+[scene(expired_bullets=(ident,))]
            flight['pos']=end;flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
            return packets
        start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        contacts=[(h,t.id,t) for t in enemies(self) if (h:=actor_contact(start,end,t,flight['previous'],now)) is not None]
        hit=min(contacts,key=lambda v:v[:2]) if contacts else None
        if hit and self.projectile_blocked(hit[2],now):return [scene(expired_bullets=(ident,))]
        if hit or now>=flight['finish']:
            pos=tuple(round(v) for v in point_at(start,end,hit[0] if hit else 1))
            return [scene(blown_bullets=(ident,))]+self._explosion(flight,pos,now)
        flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
        return []

    def _event(self,now,kind,data):
        if kind=='pumpkin_spawn':return self._spawn_ghost(*data,now)
        if kind=='pumpkin_portal':
            cast,index=data;packets=self._spawn_ghost(cast['pos'],cast['stats'],cast['generation'],now)
            if index<6:self._queue(now+1000,kind,cast,index+1)
            else:packets.extend(self.remove_object(cast['id']))
            return packets
        if kind=='pumpkin_trap':
            cast,=data
            if now>=cast['end']:return self.remove_object(cast['id'])
            candidates=[a for a in self.arena.actors.values() if a.alive and not a.is_untargetable() and math.dist(cast['pos'],a.position_at(now))<=96]
            if not candidates:self._queue(min(now+50,cast['end']),kind,cast);return []
            target=min(candidates,key=lambda a:(math.dist(cast['pos'],a.position_at(now)),a.id))
            packets=self.remove_object(cast['id'],destroyed=True)
            if target.camp==self.camp:
                return packets+target.restore_hp(cast['power']*D('1.27'),now)+self._buff(327222,now,target.id)
            packets.extend(self.damage(cast['power']*D('2.15'),now,target=target,school='energy')[0])
            if self.arena.pk and self.arena.pk['finished']:return packets
            if not target.alive or target.cc_immune(now):return packets
            pos=target.position_at(now);direction=pos if pos!=cast['pos'] else (pos[0]+1,pos[1])
            dest=aimed(cast['pos'],direction,math.dist(cast['pos'],pos)+240,fixed=True)
            body,stopped=prepare_displacement(target,now,interrupt=False)
            if stopped:pos=body
            packets.extend(stopped)
            dest=target.move_destination(pos,dest);wall=self.arena.geometry.wall_contact(pos,dest,36)
            if wall is not None:dest=tuple(round(v) for v in point_at(pos,dest,max(0,wall-.001)))
            target._set_motion(pos,dest,480,now,1);target.forced_until=target.motion[3]
            cast.update(target=target.id,target_generation=target.generation,previous=now,motion=target.motion,wall=math.dist(pos,dest)<239.5)
            self._queue(now+20,'pumpkin_push',cast)
            return packets+self._buff(327214,now,target.id)+[scene(moves=(move_event(target.motion[1],480,1,target.id),))]
        if kind=='pumpkin_push':
            cast,=data;target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation']:return []
            if target.motion!=cast['motion']:
                if not accept_water_reclip(target,cast):return []
                cast['motion']=target.motion;cast['previous']=max(cast['previous'],target.motion[2]);cast['wall']=True
            start,end=target.position_at(cast['previous']),target.position_at(now)
            contacts=[(h,a.id,a) for a in self.arena.actors.values() if a is not target and a.alive and not a.is_untargetable()
                      if (h:=actor_contact(start,end,a,cast['previous'],now)) is not None]
            if contacts:
                h,_,other=min(contacts,key=lambda v:v[:2]);target.position=target.move_destination(start,point_at(start,end,h));target.motion=None;target.forced_until=now
                return [scene(moves=(move_event(target.position,0,5,target.id),))]+self._buff(327231,now,target.id)+self._buff(327232,now,other.id)
            if not target.motion or now>=target.motion[3]:
                return self._buff(327231,now,target.id) if cast['wall'] or target.motion and target.motion!=cast['motion'] else []
            cast['previous']=now;self._queue(min(now+20,target.motion[3]),kind,cast);return []
        if kind=='pumpkin_volley':
            cast,index=data
            if self.volley is not cast or not self.alive:return []
            from bot_ai import team_visible
            packets=[];pos=self.position_at(now);targets=[t for t in enemies(self) if math.dist(pos,t.position_at(now))<=600
                and team_visible(self.arena,self,t,now)]
            if targets:
                target=min(targets,key=lambda t:(math.dist(pos,t.position_at(now)),t.id))
                packets.extend(self.shoot(327411,pos,target.position_at(now),now,cast['power']*D('.65'),school='energy',target=target,through_walls=True))
            if index<10:self._queue(now+500,kind,cast,index+1)
            else:
                self.volley=None;self.cooldowns[10]=now+self.skill_cooldown(10000, 10)
                packets.extend(self.remove_buff(327401,now)+self.remove_buff(327402,now)+[self._cooldown(10)])
            return packets
        if kind=='pumpkin_ready':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None
            return self.shoot(327301,self.position_at(now),cast['dest'],now,0,school='energy',power=cast['power'],through_walls=True,context=cast)+self.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or not self.alive or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot in (0,2) and start==dest or slot==1 and (not self.e_count or math.dist(start,dest)>480) or slot==10 and self.volley:return []
        power=self.combat_stat('iEgAtk',now)
        self.cooldowns[slot]=now+{0:self.fire_interval(now),1:4000,2:self.skill_cooldown(30000,2),10:5000+self.skill_cooldown(10000,10)}[slot]
        if slot==0:return self.shoot(327100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        if slot==1:
            self.e_count-=1
            if not self.e_next_charge:self.e_next_charge=now+self.skill_cooldown(8000)
            return self.shoot(327201,start,dest,now,0,school='energy',power=power,through_walls=True,fixed_destination=True)+[self._cooldown(1)]
        if slot==2:
            self.ready=dict(slot=2,skill=327301,dest=dest,power=power,stats=self._summon_stats(now))
            _,stopped=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=self.position_at(now),None
            self._queue(now+500,'pumpkin_ready',self.ready)
            return [scene(skills=(self._skill_event(327301,start,dest,ready=1),)),self._cooldown(2)]+self.sync_speed(now)+stopped
        self.volley=dict(power=power,generation=self.generation)
        self._queue(now+500,'pumpkin_volley',self.volley,1)
        return self._buff(327401,now)+self._buff(327402,now)+[self._cooldown(10)]


class PumpkinGhost(TankActions):
    taunt_mobile=True
    _respawn=HuluTurret._respawn

    def __init__(self,*args):
        super().__init__(*args);self.stats=dict(self.info['summon_stats'])
        self.hp=self.max_hp=D(self.stats['iHp']);self.info['hp']=self.info['max_hp']=math.ceil(self.hp)
        self.cooldowns={};self.passive_ready_at=0

    def snapshot(self,now):
        body=struct.pack('<IIhhiBiIiH',self.id,20001,*self.position_at(now),math.ceil(self.hp),self.camp,math.ceil(self.max_hp),self.info['owner'],
                         math.ceil(sum(s.remaining for s in self.shields if s.expires_ms>now)),0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def sync_speed(self,now):return []

    def on_spawn(self,now):
        self._queue(now+1000,'pumpkin_decay',1);self._queue(now+100,'pumpkin_ai')
        return self._buff(327122,now)

    def commit_hp(self,hp,now,*,critical=False):
        before=self.alive;packets=super().commit_hp(hp,now,critical=critical)
        if before and not self.alive:
            packets.append(scene(removed=(struct.pack('<I',self.id),)))
            self._queue(now,'pumpkin_death',self.position_at(now),self.combat_stat('iEgAtk',now))
        return packets

    def _flight(self,flight,now):
        target=self.arena.actors.get(flight['target'])
        if now<flight['finish']:flight['previous']=now;self._queue(flight['finish'],'flight',flight);return []
        packets=[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if target and target.alive and target.generation==flight['target_generation'] and not self.projectile_blocked(target,now):
            packets.extend(self.damage(flight['raw'],now,target=target,school='energy')[0]+self._buff(327113,now,target.id))
        return packets

    def taunt_attack(self,target,now):
        pos=self.position_at(now);dest=target.position_at(now)
        if (not self.alive or not target.alive or target.is_untargetable() or self.blocked('attack',now)
                or self.skill_sealed(0,now) or now<self.passive_ready_at or math.dist(pos,dest)>96):return []
        self.passive_ready_at=now+self.fire_interval(now)
        return self.shoot(327112,pos,dest,now,self.combat_stat('iEgAtk',now)*D('.5'),school='energy',target=target,through_walls=True)

    def _event(self,now,kind,data):
        if kind=='pumpkin_death':
            pos,power=data;packets=[scene(skills=(self._skill_event(327121,pos,pos),))]
            for target in enemies(self,area=True):
                if math.dist(pos,target.position_at(now))<=168:packets.extend(self.damage(power*D('1.5'),now,target=target,school='energy')[0])
            return packets
        if kind=='pumpkin_decay':
            if not self.alive:return []
            index,=data;packets=self.commit_hp(max(D(0),self.hp-self.max_hp*D('.125')) if index<120 else D(0),now)
            if self.alive:self._queue(now+1000,kind,index+1)
            return packets
        if kind=='pumpkin_ai':
            if not self.alive:return []
            self._queue(now+100,kind);packets=[]
            if self.blocked('attack',now):return []
            from bot_ai import observable,team_visible
            candidates=[t for t in enemies(self) if observable(self.arena,self,t,now) or team_visible(self.arena,self,t,now)];pos=self.position_at(now)
            if not candidates:return []
            target=min(candidates,key=lambda t:(math.dist(pos,t.position_at(now)),t.id));dest=target.position_at(now)
            if math.dist(pos,dest)>96:
                if not self.blocked('move',now) and self._speed(now)>0:
                    self._set_motion(pos,aimed(pos,dest,max(0,math.dist(pos,dest)-90)),self._speed(now),now,3)
                    packets.append(scene(moves=(move_event(self.motion[1],self._speed(now),3,self.id),)))
            else:
                if self.motion and now>=self.forced_until:
                    self.position,self.motion=pos,None;packets.append(scene(moves=(move_event(pos,0,5,self.id),)))
                packets.extend(self.taunt_attack(target,now))
            return packets
        return super()._event(now,kind,data)
