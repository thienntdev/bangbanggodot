"""Sasuke: bounded Amaterasu chains, substitution and counted direct-hit wards."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D,quantize
from combat_protocol import props,scene
from hulu_actions import HuluTurret
from melee_common import aimed,enemies,prepare_displacement

SLOTS={0:368100,1:368201,2:368301,10:368401}


class SasukeActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=100
        self.ready=self.dash=self.counter=None
        self.dots={}
        self.ward_count=0
        self.blocked_attacks=set()

    def _skill(self,slot,now):
        if slot==0 and self.has_buff(368301,now):return 368310
        if slot==2 and self.has_buff(368304,now):return 368320
        if slot==10 and self.has_buff(368404,now):return 368410
        return SLOTS[slot]

    def _cooldown(self,slot,changed=False):
        skill=self._skill(slot,self.clock())
        body=props(skill,slot,end=0 if skill in (368320,368410) else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(100,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self,now):
        self.mp=100;self.ready=self.dash=self.counter=None
        self.ward_count=0;self.blocked_attacks.clear()
        self.info.pop('untargetable',None)
        self._queue(now+1000,'sasuke_energy',self.generation)
        return self._buff(368101,now)+[scene(mp=(struct.pack('<Ii',self.id,self.mp),))]+[self._cooldown(s,True) for s in SLOTS]

    def _visibility(self,now):
        self.info['untargetable']=self.has_buff(368403,now) and 32 not in self.buff_types(now)

    def _ward(self,now):
        self.ward_count=3
        return self._buff(368414,now)

    def remove_buff(self,template,now,*,expired=False):
        existed=(self.id,template) in self.active_buffs
        packets=super().remove_buff(template,now,expired=expired)
        if template==368403:
            self._visibility(now)
            if existed and self.alive:packets.extend(self._ward(now))
        if template==368414:self.ward_count=0
        if template==368401 and existed and self.alive:packets.extend(self._buff(368408,now))
        if template in (368301,368304,368404):
            packets.append(self._cooldown(0 if template==368301 else 2 if template==368304 else 10,True))
        return packets

    def block_hit(self,key,amount,now,*,basic=False,periodic=False,source=None):
        if amount<=0:return False,[]
        if key in self.blocked_attacks:return True,[]
        if basic and self.has_buff(368401,now) and source:
            self.blocked_attacks.add(key)
            packets=self.remove_buff(368401,now)+self.remove_buff(368406,now)
            pos=self.position_at(now)
            flight=getattr(self.arena,'current_flight',None)
            origin=flight['start'] if flight else source.position_at(now)
            endpoint=flight['end'] if flight else pos
            vector=endpoint[0]-origin[0],endpoint[1]-origin[1]
            if vector==(0,0):vector=(1,0)
            self.counter=dict(target=source.id,target_generation=source.generation,vector=vector,end=now+3000)
            for t in (368403,368404):packets.extend(self._buff(t,now))
            packets.extend(self._buff(368405,now,source.id))
            self.cooldowns[1]=now+round(max(0,self.cooldowns[1]-now)*.25)
            info=dict(acct_id=self.info['acct_id'],tank_level=self.info['tank_level'],tank_id=self.info['tank_id'],
                      npc_template=368402,owner=self.id,source_generation=self.generation,name=self.info['name'],
                      in_room=True,summon_stats=dict(self.stats))
            info['summon_stats']['iHp']=str(max(D('.001'),quantize(self.max_hp*D('.00001'))))
            for k in ('iAttack','iEgAtk','iArmor','iEgArmor','iCentesis','iEgCtsis'):
                info['summon_stats'][k]=str(self.combat_stat(k,now))
            shadow=SasukeShadow(self.arena,self._new_id(5),info,self.camp,pos)
            self.arena.actors[shadow.id]=shadow
            self._visibility(now)
            return True,packets+[shadow.snapshot(now)]+shadow.on_spawn(now)+[self._cooldown(1),self._cooldown(10,True)]
        if not periodic and self.ward_count and self.has_buff(368414,now):
            self.ward_count-=1;self.blocked_attacks.add(key)
            return True,self.remove_buff(368414,now) if not self.ward_count else []
        return False,[]

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.dash) or super().blocked(action,now)

    def interrupt(self,now):
        packets=[]
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            self.ready=None
        if self.dash:
            self.position,self.motion,self.forced_until=self.stop_position(now),None,now
            self.dash=None
            packets.append(scene(moves=(self._move_event(self.position,0,5),)))
            packets.extend(self.remove_buff(368201,now))
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        if (self.ready or self.dash) and int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']) in (30,35,66):
            return self.interrupt(now)
        return []

    def update(self,now):
        self._visibility(now)
        self.dots={k:v for k,v in self.dots.items() if v['end']>now}
        live={args[1][0].get('attack_key') for _,_,callback,args in self.arena.pending
              if callback.__name__=='_event' and args[0]=='flight'}
        self.blocked_attacks.intersection_update(live)
        packets=self.interrupt(now) if self.ready and self.skill_sealed(self.ready['slot'],now) else []
        return packets+super().update(now)

    def _ignite(self,target,power,now,*,generation,chain=None,form=False):
        if not target.alive:return []
        key=(target.id,target.generation)
        chain=chain if chain is not None else dict(end=now+12000,visited=set())
        if now>=chain['end'] or key in chain['visited']:return []
        chain['visited'].add(key)
        template,spread=(368311,368312) if form else (368102,368103)
        packets=[]
        for t in (368102,368103,368311,368312):packets.extend(target.remove_buff(t,now))
        duration=min(4000,chain['end']-now)
        packets.extend(self._buff(template,now,target.id,duration=duration)+self._buff(spread,now,target.id,duration=duration))
        if not target.has_buff(template,now):return packets
        dot=dict(target=target.id,target_generation=target.generation,power=power,generation=generation,
                 template=template,version=target.buff_versions[template],chain=chain,end=now+duration,form=form)
        self.dots[key]=dot
        packets.extend(self._dot_hit(dot,now))
        self._queue(now+1000,'sasuke_dot',dot,1)
        self._queue(now+250,'sasuke_spread',dot)
        return packets

    def _dot_target(self,dot,now):
        target=self.arena.actors.get(dot['target'])
        if (not target or not target.alive or target.generation!=dot['target_generation'] or now>=dot['end']
                or self.dots.get((target.id,target.generation)) is not dot
                or target.buff_versions.get(dot['template'])!=dot['version']):return None
        return target

    def _dot_hit(self,dot,now):
        target=self._dot_target(dot,now)
        if not target:return []
        previous=getattr(self.arena,'damage_context',None)
        self.arena.damage_context=(self.id,self._new_id(2))
        try:return self.damage(dot['power']*D('.75'),now,target=target,school='energy',periodic=True)[0]
        finally:self.arena.damage_context=previous

    def _hit(self,target,raw,power,now,*,generation):
        packets=self.damage(raw,now,target=target,school='energy')[0]
        return packets+self._ignite(target,power,now,generation=generation)

    def on_bullet_hit(self,flight,target,now):
        if flight['template']!=368310:return []
        return self._ignite(target,flight['power'],now,generation=flight['source_generation'],form=True)

    def _event(self,now,kind,data):
        if kind=='sasuke_energy':
            if not self.alive or self.generation!=data[0]:return []
            self._queue(now+1000,kind,data[0]);return self._resource(2)
        if kind=='sasuke_dot':
            dot,index=data
            packets=self._dot_hit(dot,now)
            if index<3 and self._dot_target(dot,now):self._queue(now+1000,kind,dot,index+1)
            return packets
        if kind=='sasuke_spread':
            dot,=data;target=self._dot_target(dot,now)
            if not target:return []
            packets=[];pos=target.position_at(now)
            for enemy in enemies(self,area=True):
                if (enemy.info.get('npc_template') and not dot['form']) or math.dist(pos,enemy.position_at(now))>144:continue
                packets.extend(self._ignite(enemy,dot['power'],now,generation=dot['generation'],chain=dot['chain'],form=dot['form']))
            if now+900<dot['end']:self._queue(now+900,kind,dot)
            return packets
        if kind=='sasuke_ready':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;start=self.position_at(now)
            packets=self.sync_speed(now)+[scene(skills=(self._skill_event(cast['skill'],start,cast['dest'],cast.get('target',0)),))]
            if cast['skill']==368201:
                end=aimed(start,cast['dest'],432,fixed=True)
                duration=self._set_motion(start,end,960,now,kind=3);self.forced_until=now+duration
                self.dash=dict(generation=self.generation,power=cast['power'],hits=set(),previous=now,end=now+duration)
                packets.extend(self._buff(368201,now))
                packets.append(scene(moves=(self._move_event(self.motion[1],960,3),)))
                self._queue(now+min(20,duration),'sasuke_dash',self.dash)
            elif cast['skill']==368320:
                for template in (368320,368323):
                    ident,packet=self.add_object(template,cast['dest']);packets.append(packet)
                    self._queue(now+(500 if template==368320 else 800),'object_expire',ident)
                self._queue(now+500,'sasuke_arrow_art',cast)
                self._queue(now+800,'sasuke_arrow_hit',cast)
            else:
                target=self.arena.actors.get(cast['target'])
                if not target or not target.alive or target.generation!=cast['target_generation']:return packets
                pos=target.position_at(now);dx,dy=cast['vector'];length=math.hypot(dx,dy)
                dest=self.blink_destination(start,(round(pos[0]-72*dx/length),round(pos[1]-72*dy/length)))
                self.position,self.motion,self.forced_until=dest,None,now
                packets.append(scene(moves=(self._move_event(dest,0,5),)))
                packets.extend(self._hit(target,cast['power']*2,cast['power'],now,generation=cast['generation']))
                packets.extend(self._buff(368412,now,target.id)+self._buff(368415,now,target.id)+self._buff(368413,now))
                packets.extend(self._resource(30))
            return packets
        if kind=='sasuke_dash':
            cast,=data
            if self.dash is not cast or not self.alive:return []
            start,end=self.position_at(cast['previous']),self.position_at(now);packets=[]
            for target in enemies(self):
                key=target.id,target.generation
                if key in cast['hits'] or actor_contact(start,end,target,cast['previous'],now) is None:continue
                cast['hits'].add(key)
                packets.extend(self._hit(target,cast['power']*D('2.06'),cast['power'],now,generation=cast['generation']))
                packets.extend(self._buff(368203,now,target.id))
                if target.has_buff(368305,now):packets.extend(self._buff(368204,now,target.id))
                packets.extend(self.restore_hp(cast['power'],now)+self._resource(20))
            if not self.motion or now>=min(cast['end'],self.motion[3]):
                self.dash=None;packets.extend(self.remove_buff(368201,now))
            else:
                cast['previous']=now;self._queue(min(now+20,cast['end'],self.motion[3]),kind,cast)
            return packets
        if kind=='sasuke_arrow_art':
            cast,=data;packets=[]
            for template,lifetime in ((368321,1000),(368322,300)):
                ident,packet=self.add_object(template,cast['dest']);packets.append(packet)
                self._queue(now+lifetime,'object_expire',ident)
            return packets
        if kind=='sasuke_arrow_hit':
            cast,=data;packets=[]
            for target in enemies(self,area=True):
                if math.dist(cast['dest'],target.position_at(now))<=192:
                    packets.extend(self._hit(target,cast['power']*D('3.87'),cast['power'],now,generation=cast['generation']))
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now):return []
        skill=self._skill(slot,now)
        if skill not in (368320,368410) and self.cooldowns[slot]>now:return []
        if slot in (0,1) and start==dest or skill==368301 and self.mp<100:return []
        if skill==368320 and (not self._inside(dest) or math.dist(start,dest)>600):return []
        if skill==368410:
            mark=self.counter;target=self.arena.actors.get(mark['target']) if mark else None
            if (not target or target not in enemies(self) or target.generation!=mark['target_generation']
                    or not target.has_buff(368405,now) or target.buff_sources.get(368405)!=self.id
                    or mark['end']<=now or math.dist(start,target.position_at(now))>720):return []
            if target_id not in (0,target.id):return []
            from bot_ai import team_visible
            if not team_visible(self.arena,self,target,now):return []
        packets=self.remove_buff(368403,now)
        power=self.combat_stat('iEgAtk',now)
        if skill not in (368320,368410):
            self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:20000,10:8000}[slot], slot)
        if slot==0:
            return packets+self.shoot(skill,start,dest,now,power,school='energy',basic=True,power=power)+[self._cooldown(0)]
        if skill in (368201,368320,368410):
            duration=100 if skill==368201 else 50
            body,stopped=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body if stopped else start,None
            self.ready=dict(slot=slot,skill=skill,dest=dest,power=power,generation=self.generation,end=now+duration)
            if skill==368410:
                self.ready.update(self.counter);self.ready['end']=now+duration
                packets.extend(self.remove_buff(368404,now));self.counter=None
            elif skill==368320:packets.extend(self.remove_buff(368304,now))
            packets.append(scene(skills=(self._skill_event(skill,start,dest,ready=duration),)))
            self._queue(now+duration,'sasuke_ready',self.ready)
            return packets+self.sync_speed(now)+[self._cooldown(slot,True)]+stopped
        packets.append(scene(skills=(self._skill_event(skill,start,dest),)))
        if skill==368401:
            packets.extend(self._buff(368401,now)+self._buff(368406,now))
        else:
            packets.extend(self._resource(-100))
            for t in (368301,368302,368304):packets.extend(self._buff(t,now))
            for target in enemies(self,area=True):
                if math.dist(start,target.position_at(now))>192:continue
                packets.extend(self._hit(target,power*D('2.46'),power,now,generation=self.generation))
                packets.extend(self._buff(368305,now,target.id)+self._buff(368306,now,target.id))
            packets.append(self._cooldown(0,True))
        return packets+[self._cooldown(slot,True)]


class SasukeShadow(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.stats=dict(self.info['summon_stats']);self.hp=self.max_hp=D(self.stats['iHp'])
        self.info['hp']=self.info['max_hp']=math.ceil(self.hp)
        self.cooldowns={}

    def snapshot(self,now):
        body=struct.pack('<IIhhiBiIiH',self.id,368402,*self.position_at(now),math.ceil(self.hp),self.camp,
                         math.ceil(self.max_hp),self.info['owner'],0,0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def sync_speed(self,now):return []

    def on_spawn(self,now):
        self._queue(now+3000,'sasuke_shadow_end');return []

    def commit_hp(self,hp,now,*,critical=False):
        before=self.alive;packets=super().commit_hp(hp,now,critical=critical)
        if before and not self.alive:
            pos=self.position_at(now)
            packets.extend((scene(skills=(self._skill_event(368421,pos,pos),)),scene(removed=(struct.pack('<I',self.id),))))
        return packets

    def _event(self,now,kind,data):
        if kind=='sasuke_shadow_end':return self.commit_hp(D(0),now) if self.alive else []
        return super()._event(now,kind,data)

    _respawn=HuluTurret._respawn
