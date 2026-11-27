"""Kirito: lethal-hit rejection, carried dash and a divided fifteen-cut burst."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene,stop_move
from melee_common import aimed,enemies,in_strip,piercing_step,prepare_displacement,accept_water_reclip

SLOTS={0:371100,1:371201,2:371301,10:371401}


class KiritoActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.dash=self.vanish=None
        self.passive_ready_at=0

    def _cooldown(self,slot,changed=False):
        skill=371131 if slot==0 and self.has_buff(371121,self.clock()) else SLOTS[slot]
        body=props(skill,slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        return self._buff(371101,now)+self._buff(371102,now)+[self._cooldown(0,True)]

    def _rescue(self,now):
        self.passive_ready_at=now+30000
        self.cooldowns[1]=self.cooldowns[10]=0
        return self._buff(371111,now)+self._buff(371113,now)+[self._cooldown(1),self._cooldown(10),self._hp_packet(self.id,self.hp)]

    def prevent_lethal_hit(self,hit,now):
        if self.alive and hit.hp_after==0 and now>=self.passive_ready_at:
            return self._rescue(now)
        return None

    def commit_hp(self,hp,now,*,critical=False):
        if self.alive and hp==0 and now>=self.passive_ready_at:
            return self._rescue(now)
        return super().commit_hp(hp,now,critical=critical)

    def _empower(self,now):
        packets=[]
        for template in (371121,371122,371123,371124):packets.extend(self._buff(template,now))
        return packets+[self._cooldown(0,True)]

    def remove_buff(self,template,now,*,expired=False):
        packets=super().remove_buff(template,now,expired=expired)
        if template==371121:
            packets.extend(super().remove_buff(371122,now))
            packets.append(self._cooldown(0,True))
        if template==371111 and expired and self.alive:packets.extend(self._buff(371114,now))
        return packets

    def _hit(self,target,raw,now,*,school='physical'):
        packets,lost=self.damage(raw,now,target=target,school=school)
        if lost and self.alive:packets.extend(self._empower(now))
        return packets

    def _speed(self,now):
        return 0 if self.ready or self.vanish else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.vanish or self.dash) or super().blocked(action,now)

    def reject_buff(self,row,source,now):
        return bool(self.vanish and source.camp!=self.camp)

    def cc_immune(self,now,*,slow=False):
        return bool(self.vanish) or super().cc_immune(now,slow=slow)

    def _end_vanish(self,now):
        cast,self.vanish=self.vanish,None
        if not cast:return []
        self.info['untargetable']=cast['was_untargetable'];self.info['damage_immune']=cast['was_immune']
        packets=[]
        for template in (371306,371401,371302):packets.extend(self.remove_buff(template,now))
        for ident in cast['objects']:packets.extend(self.remove_object(ident,destroyed=True))
        return packets+self.sync_speed(now)

    def interrupt(self,now):
        packets=[]
        if self.vanish and self.alive:return []
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            self.ready=None
        if self.dash:
            self.dash=None;self.position,self.motion,self.forced_until=self.position_at(now),None,now
            packets.extend(self.remove_buff(371201,now))
        if not self.alive:packets.extend(self._end_vanish(now))
        return packets+self.sync_speed(now)

    def update(self,now):
        packets=self.interrupt(now) if self.ready and self.skill_sealed(self.ready['slot'],now) else []
        return packets+super().update(now)

    def handle(self,message,payload):
        if message==514 and len(payload)>=8 and self.vanish and self.vanish['slot']==2:
            now=self.clock();pk=self.arena.pk
            if (not self.arena.input_open(now,self)
                    or pk and not self.arena.tank_test and now>=pk['end']):
                return self.arena.tick(now)
            scene_id,x,y=struct.unpack_from('<Ihh',payload)
            if scene_id==self.scene_id:self.vanish['dest']=(x,y)
            return self.arena.tick(self.clock())
        return super().handle(message,payload)

    def _blade(self,flight,target,now):
        current=self.alive and flight['source_generation']==self.generation
        packets,lost=self.damage(flight['raw'],now,target=target,basic=True,lifesteal=D('.25') if flight['template']==371131 and current else 0)
        if lost and current and flight['template']==371131:packets.extend(self._buff(371132,now))
        return packets

    def _flight(self,flight,now):
        return piercing_step(self,flight,now,self._blade,pierce=False)

    def _carry(self,target,cast,now):
        if not target.alive or target.cc_immune(now):return []
        current=target.position_at(now);start=target.stop_position(now)
        dest=cast['dest'];wall=self.arena.geometry.wall_contact(start,dest,36)
        if wall is not None:dest=point_at(start,dest,max(0,wall-.0001))
        if start!=current:target.position,target.motion=start,None
        packets=target.interrupt(now)
        if start!=current:packets.append(stop_move(self.scene_id,target.id,start))
        duration=target._set_motion(start,dest,1200,now,kind=1)
        target.forced_until=now+duration
        carried=dict(target=target.id,target_generation=target.generation,source_generation=self.generation,power=cast['power'],
                     end=now+duration,motion=target.motion,wall=cast['wall'] or wall is not None)
        self._queue(now+min(20,duration),'kirito_wall',carried)
        return packets+self._buff(371221,now,target.id)+[scene(moves=(self._move_event(target.motion[1],1200,1,target.id),))]

    def _event(self,now,kind,data):
        if kind=='kirito_arrival_visual':
            cast,=data
            # 371411's body is intentionally blank: the arrival windup is
            # its native remove movie. Cancelled/dead casts only expire it.
            return self.remove_object(cast['visual_object'],
                destroyed=self.vanish is cast and self.alive)
        if kind=='kirito_wall':
            cast,=data;target=self.arena.actors[cast['target']]
            if not target.alive or target.generation!=cast['target_generation']:return []
            if target.motion!=cast['motion']:
                if (target.motion and target.motion_kind==1 and target.motion[3]<=cast['end']
                        and target.has_buff(371221,now) and accept_water_reclip(target,cast)):
                    cast.update(motion=target.motion,end=target.motion[3],wall=True)
                else:return target.remove_buff(371221,now)
            if now<cast['end']:
                self._queue(min(now+20,cast['end']),kind,cast);return []
            packets=target.remove_buff(371221,now)
            if cast['wall']:
                packets.extend(self.damage(cast['power']*D('1.45'),now,target=target)[0])
                packets.extend(self._buff(371232,now,target.id))
                if self.alive and self.generation==cast['source_generation']:
                    packets.extend(self.restore_hp(cast['power'],now)+self._empower(now))
            return packets
        if kind=='kirito_dash':
            cast,=data
            if self.dash is not cast or not self.alive:return []
            start,end=self.position_at(cast['previous']),self.position_at(now);packets=[]
            if self.motion and self.motion[1]!=cast['dest']:
                cast['dest']=self.motion[1];cast['wall']=True
            for target in enemies(self):
                key=target.id,target.generation
                if key in cast['hits'] or actor_contact(start,end,target,cast['previous'],now) is None:continue
                cast['hits'].add(key);packets.extend(self._hit(target,cast['power'],now))
                if self.arena.pk and self.arena.pk['finished']:break
                packets.extend(self._carry(target,cast,now))
            if not self.motion or now>=self.motion[3] or now>=cast['end']:
                self.dash=None;packets.extend(self.remove_buff(371201,now))
            else:
                cast['previous']=now;self._queue(min(now+20,cast['end']),kind,cast)
            return packets
        if kind=='kirito_blink':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;start=self.position_at(now);dest=self.blink_destination(start,cast['dest'])
            self.position,self.motion,self.forced_until=dest,None,now
            cast.update(dest=dest,was_untargetable=self.info.get('untargetable',False),was_immune=self.info.get('damage_immune',False),objects=[])
            self.vanish=cast;self.info['untargetable']=self.info['damage_immune']=True
            packets=self._buff(371401,now)+[scene(moves=(self._move_event(dest,0,5),))]
            ident,packet=self.add_object(371402,start);packets.append(packet);self._queue(now+700,'object_expire',ident)
            ident,packet=self.add_object(371404,dest);packets.append(packet);cast['objects'].append(ident)
            self._queue(now+500,'kirito_land',cast)
            return packets+self.sync_speed(now)
        if kind=='kirito_land':
            cast,=data
            if self.vanish is not cast or not self.alive:return []
            packets=self._end_vanish(now)
            for target in enemies(self,area=True):
                if math.dist(cast['dest'],target.position_at(now))<=144:
                    packets.extend(self._buff(371405,now,target.id));packets.extend(self._hit(target,cast['power']*D('1.27'),now))
            return packets
        if kind=='kirito_cut':
            cast,index=data
            if self.vanish is not cast or not self.alive:return []
            targets=[t for t in enemies(self,area=True) if math.dist(cast['start'],t.position_at(now))<=216]
            packets=[]
            for target in targets:
                packets.extend(self._hit(target,cast['power']*D('.4')/len(targets),now))
                for template in (371312,371313,371314):packets.extend(self._buff(template,now,target.id))
            if index<14:self._queue(now+100,kind,cast,index+1)
            if index==14:
                packets.append(scene(skills=(self._skill_event(371321,cast['start'],cast['dest'],ready=1),)))
            return packets
        if kind=='kirito_final':
            cast,=data
            if self.vanish is not cast or not self.alive:return []
            packets=self._end_vanish(now);start=cast['start'];dest=cast['dest']
            targets=[t for t in enemies(self,area=True) if in_strip(t.position_at(now),start,dest,224,300)]
            packets.append(scene(skills=(self._skill_event(371321,start,dest),)))
            for target in targets:
                missing=target.max_hp-target.hp
                packets.extend(self._hit(target,cast['power']*D('1.75')/len(targets),now))
                packets.extend(self._hit(target,missing*D('.2')/len(targets),now,school='true'))
                packets.extend(self._buff(371305,now,target.id)+self._buff(371307,now,target.id))
            ident,packet=self.add_object(371308,start);self._queue(now+100,'object_expire',ident)
            return packets+[packet]
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot in (0,1) and start==dest or slot==10 and (not self._inside(dest) or math.dist(start,dest)>360):return []
        power=self.combat_stat('iAttack',now);packets=[];correction=[]
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:25000,10:8000}[slot], slot)
        if slot==0:
            enhanced=self.has_buff(371121,now);key=(self.id,self.generation,371100,self._new_id(2))
            packets.extend(self.shoot(371100,start,dest,now,power,school='physical',basic=True,attack_key=key))
            if enhanced:
                angle=math.atan2(dest[1]-start[1],dest[0]-start[0])
                for degrees in (-144,-72,72,144):
                    a=angle+math.radians(degrees);end=(round(start[0]+480*math.cos(a)),round(start[1]+480*math.sin(a)))
                    packets.extend(self.shoot(371131,start,end,now,power*D('.75'),school='physical',basic=True,attack_key=key))
                packets.extend(self.remove_buff(371121,now))
        elif slot==1:
            dest=aimed(start,dest,336,fixed=True)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            body=body if stopped else start
            wall=self.arena.geometry.wall_contact(body,dest,36)
            if wall is not None:dest=point_at(body,dest,max(0,wall-.0001))
            requested=dest;duration=self._set_motion(body,dest,1200,now,kind=3)
            self.forced_until=now+duration
            self.dash=dict(previous=now,end=now+duration,dest=self.motion[1],hits=set(),power=power,
                           wall=wall is not None or math.dist(requested,self.motion[1])>.1)
            self._queue(now+min(20,duration),'kirito_dash',self.dash)
            packets.extend(self._buff(371201,now,duration=duration)+stopped);packets.append(scene(moves=(self._move_event(self.motion[1],1200,3),)))
        elif slot==2:
            body,correction=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body if correction else start,None
            cast=dict(slot=2,start=start,dest=dest if dest!=start and dest!=(0,0) else (start[0]+224,start[1]),power=power,objects=[],
                      was_untargetable=self.info.get('untargetable',False),was_immune=self.info.get('damage_immune',False))
            self.vanish=cast;self.info['untargetable']=self.info['damage_immune']=True
            packets.extend(self._buff(371306,now)+self._buff(371302,now,duration=1500))
            ident,packet=self.add_object(371301,start);cast['objects'].append(ident);packets.append(packet)
            self._queue(now,'kirito_cut',cast,0);self._queue(now+1500,'kirito_final',cast)
            packets.extend(self.sync_speed(now))
        else:
            body,correction=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body if correction else start,None
            self.ready=dict(slot=10,skill=371401,dest=dest,power=power)
            ident,packet=self.add_object(371411,dest);packets.append(packet)
            self.ready['visual_object']=ident
            self._queue(now+450,'kirito_arrival_visual',self.ready)
            self._queue(now+50,'kirito_blink',self.ready)
            packets.append(scene(skills=(self._skill_event(371401,start,dest,ready=1),)));packets.extend(self.sync_speed(now))
        return packets+[self._cooldown(slot)]+correction
