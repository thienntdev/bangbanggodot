"""Tsubasa: bounded bounces, one-shot reflection and catch-only rewards."""
from battle_participants import human, private
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene, stop_move
from melee_common import aimed, enemies, piercing_step, prepare_displacement

SLOTS={0:386100,1:386201,2:386301,10:386401}


class TsubasaActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=150
        self.e_count,self.e_next_charge=2,0
        self.ready=self.dash=None
        self.reflections=[]
        self.reflect_used=0

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(150,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def _cooldown(self,slot,changed=False):
        body=props(SLOTS[slot],slot,self.e_count if slot==1 else -1,self.cooldowns[slot],self.e_next_charge if slot==1 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=self.dash=None;self.reflections=[];self.reflect_used=0;self.mp=150
        return [scene(mp=(struct.pack('<Ii',self.id,150),))]+self._buff(386101,now)

    def blocked(self,action,now):
        return bool(self.ready or self.dash) or super().blocked(action,now)

    def _speed(self,now): return 0 if self.ready or self.dash else super()._speed(now)

    def interrupt(self,now):
        packets=[]
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,386301)));self.ready=None
            packets.extend(self.remove_buff(386311,now)+self.remove_buff(386312,now))
        if self.dash:
            self.position,self.motion=self.stop_position(now),None;self.forced_until=now;self.dash=None
            packets.append(scene(moves=(self._move_event(self.position,0,5),)))
            for t in (386202,386221,386231):packets.extend(self.remove_buff(t,now))
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        row=table_row('BuffTemplate_table.xml',nBuffId=template)
        mask=int(row.get('fEffectValB',0))
        sealed=(self.ready and (not mask or mask&4)) or (self.dash and (not mask or mask&2))
        return self.interrupt(now) if row['nEffectType']=='30' or row['nEffectType'] in ('35','66') and sealed else []

    def update(self,now):
        packets=[]
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count=min(2,self.e_count+1)
            self.e_next_charge=self.e_next_charge+self.skill_cooldown(6000) if self.e_count<2 else 0
            packets.append(self._cooldown(1))
        self.reflections=[r for r in self.reflections if r['end']>now and r['generation']==self.generation]
        return packets+super().update(now)

    def reflect_projectile(self,flight,now):
        version=self.buff_versions.get(386111,0)
        if not self.has_buff(386111,now) or self.reflect_used==version:return False
        self.reflect_used=version
        self._queue(now,'tsubasa_reflect',dict(generation=self.generation,power=flight['attacker_ap'],end=now+2000,
                                             reflected=flight.get('reflected',False),version=version))
        return True

    def _reflect_reply(self,dest,now):
        if not self.reflections:return []
        request=self.reflections.pop(0);start=self.position_at(now)
        if not self.alive or request['generation']!=self.generation or request['end']<now or start==dest:return []
        return self.shoot(386121,start,dest,now,request['power'],school='physical',reflected=True,through_walls=True)

    def handle(self,message,payload):
        if message==510:
            packets=self.arena.tick(self.clock())
            if not self.arena.input_open(self.clock(),self):return packets
            if len(payload)>=12 and struct.unpack_from('<I',payload)[0]==self.scene_id:
                _,_,_,x,y=struct.unpack_from('<Ihhhh',payload);packets.extend(self._reflect_reply((x,y),self.clock()))
            return packets
        if message==514 and len(payload)>=8 and self.dash:
            packets=self.arena.tick(self.clock())
            if not self.arena.input_open(self.clock(),self):return packets
            scene_id,x,y=struct.unpack_from('<Ihh',payload)
            if scene_id==self.scene_id and self.dash:self.dash['dest']=(x,y)
            return packets
        return super().handle(message,payload)

    def _push(self,target,origin,distance,speed,now):
        if self.arena.pk and self.arena.pk['finished']:return []
        if not target.alive or target.cc_immune(now):return []
        current=target.position_at(now)
        pos=target.stop_position(now)
        end=aimed(origin,pos,math.dist(origin,pos)+distance,fixed=True)
        packets=[]
        if pos!=current:
            target.position,target.motion=pos,None
            packets.extend(target.interrupt(now))
            packets.append(stop_move(self.scene_id,target.id,pos))
        target._set_motion(pos,end,speed,now,kind=1);target.forced_until=target.motion[3]
        return packets+[scene(moves=(target._move_event(target.motion[1],speed,1),))]

    def _hit(self,flight,target,now):
        current=self.alive and self.generation==flight.get('context',{}).get('generation',flight['source_generation'])
        packets,lost=self.damage(flight['raw'],now,target=target,basic=flight['basic'],reflected=flight['reflected'])
        template=flight['template']
        if flight['basic']:
            if current:packets.extend(self._resource(5))
            cast=flight['context'];cast['visited'].add((target.id,target.generation))
            if cast['count']<3:
                from bot_ai import team_visible
                pos=target.position_at(now)
                choices=[t for t in enemies(self) if (t.id,t.generation) not in cast['visited'] and math.dist(pos,t.position_at(now))<=300 and team_visible(self.arena,self,t,now)]
                if choices:
                    other=min(choices,key=lambda t:(math.dist(pos,t.position_at(now)),t.id))
                    cast['count']+=1
                    packets.extend(self.shoot(386110,pos,other.position_at(now),now,flight['raw']*D('.5'),school='physical',basic=True,
                                              speed_multiplier=1.5,target=other,context=cast,attack_key=flight['attack_key']))
            return packets
        if template==386121:return packets+self._push(target,flight['start'],72,240,now)
        if template==386301:
            if current:packets.extend(self._resource(25))
            return packets+self._push(target,flight['start'],240,720,now)
        if template==386401:
            packets.extend(self._buff(386402,now,target.id)+self._push(target,flight['start'],120,480,now))
            if current:
                if lost:packets.extend(self._buff(386403,now))
                pos=target.position_at(now)
                packets.extend(self.shoot(386411,pos,self.position_at(now),now,0,school='physical',target=self,
                                          power=flight['attacker_ap'],through_walls=True,context=dict(caught=False)))
        return packets

    def _flight(self,flight,now):
        if flight['template']==386411:
            if not self.alive or self.generation!=flight['source_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start=flight['pos'];dest=self.position_at(now)
            end=point_at(start,dest,min(1,flight['speed']*(now-flight['previous'])/1000/max(1,math.dist(start,dest))))
            packets=[]
            if dest!=flight['end']:packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))))
            flight['pos']=end;flight['end']=dest
            caught=circle_contact(start,end,self.position_at(flight['previous']),dest,48) is not None
            if caught or now>=flight['finish']:
                packets.append(scene(expired_bullets=(struct.pack('<I',flight['id']),)))
                if caught and not flight['context']['caught']:
                    flight['context']['caught']=True
                    self.cooldowns[10]=now+round(max(0,self.cooldowns[10]-now)*D('.75'))
                    packets.extend(self.add_shield(386413,flight['power']*D('1.5'),now)+self._resource(50)+self._buff(386111,now))
                    packets.append(self._cooldown(10))
                return packets
            flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight);return packets
        if flight['template']==386110:
            # Native bounce follows a selected target; still allow interception.
            target=self.arena.actors.get(flight['target'])
            if not target or not target.alive or target.generation!=flight['target_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start=flight['pos'];dest=target.position_at(now)
            end=point_at(start,dest,min(1,flight['speed']*(now-flight['previous'])/1000/max(1,math.dist(start,dest))))
            packets=[]
            if dest!=flight['end']:packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))))
            flight['pos']=end;flight['end']=dest
            wall=self.arena.geometry.wall_contact(start,end)
            contacts=[(h,t.id,t) for t in enemies(self) if (t.id,t.generation) not in flight['context']['visited']
                      and (h:=actor_contact(start,end,t,flight['previous'],now)) is not None and (wall is None or h<wall)]
            if contacts:
                _,_,other=min(contacts,key=lambda x:x[:2])
                blocked=self.projectile_blocked(other,now)
                if not blocked:packets.extend(self._hit(flight,other,now))
                return packets+[scene(**{'expired_bullets' if blocked else 'blown_bullets':(struct.pack('<I',flight['id']),)})]
            if wall is not None or now>=flight['finish']:return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight);return packets
        return piercing_step(self,flight,now,self._hit,pierce=flight['template']==386301,
                             contact_radius=132 if flight['template']==386301 else 36)

    def _event(self,now,kind,data):
        if kind=='tsubasa_reflect':
            request,=data;packets=[]
            if self.buff_versions.get(386111)==request['version']:packets.extend(self.remove_buff(386111,now))
            if request['reflected'] or not self.alive or self.generation!=request['generation']:return packets
            self.reflections.append(request)
            if human(self):return packets+[private(self,(1590,b''))]
            dest=self.arena.bot_brains.get(self.id,{}).get('aim',self.position_at(now))
            return packets+self._reflect_reply(dest,now)
        if kind=='tsubasa_space':
            cast,=data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:return []
            self.ready=None
            packets=self.remove_buff(386311,now)+self.remove_buff(386312,now)+self.sync_speed(now)
            return packets+self.shoot(386301,self.position_at(now),cast['dest'],now,cast['power']*D('2.94'),school='physical',through_walls=True)
        if kind=='tsubasa_dash':
            cast,=data
            if self.dash is not cast or not self.alive or self.generation!=cast['generation']:return []
            start,end=self.position_at(cast['previous']),self.position_at(now);packets=[]
            if not cast['bounced']:
                contacts=[(h,t.id,t) for t in self.arena.actors.values() if t.id!=self.id and t.alive and not t.info.get('npc_template')
                          and not t.is_untargetable() and (h:=actor_contact(start,end,t,cast['previous'],now)) is not None]
                if contacts:
                    _,_,target=min(contacts,key=lambda v:v[:2]);cast['bounced']=True
                    if target.camp!=self.camp:packets.extend(self._buff(386211,now,target.id))
                    packets.extend(self.remove_buff(386202,now)+self._buff(386231,now))
                    # A redirected bounce can begin before the body has cleared a wall.
                    bounce=self.stop_position(now,end)
                    if bounce!=end:packets.append(stop_move(self.scene_id,self.id,bounce))
                    duration=self._set_motion(bounce,aimed(bounce,cast['dest'],300,fixed=True),720,now,kind=3)
                    cast['finish']=now+duration
                    packets.append(scene(moves=(self._move_event(self.motion[1],720,3),)))
            if now>=cast['finish']:
                body,stopped=prepare_displacement(self,now,interrupt=False)
                self.position,self.motion=body if stopped else end,None;self.dash=None;self.forced_until=now
                return packets+stopped+self.remove_buff(386202,now)+self.remove_buff(386221,now)+self.remove_buff(386231,now)+self.sync_speed(now)
            cast['previous']=now;self._queue(min(now+20,cast['finish']),kind,cast);return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or now<self.cooldowns[slot] or start==dest:return []
        cost={0:0,1:50,2:50,10:25}[slot]
        if self.mp<cost or slot==1 and not self.e_count:return []
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:3000,2:30000,10:8000}[slot], slot)
        power=self.combat_stat('iAttack',now);packets=self._resource(-cost)+[self._cooldown(slot)]
        if slot==0:
            return packets+self.shoot(386100,start,dest,now,power*D('1.5'),school='physical',basic=True,speed_multiplier=1.5,context=dict(count=0,visited=set(),generation=self.generation))
        if slot==10:return packets+self.shoot(386401,start,dest,now,power*D('1.58'),school='physical',through_walls=True)
        cast=dict(slot=slot,skill=SLOTS[slot],begin=now,generation=self.generation,dest=dest,power=power)
        stopped=[]
        if slot==2:
            body,stopped=prepare_displacement(self,now,interrupt=False)
            self.position,self.motion=body if stopped else start,None;self.ready=cast
            packets.extend(self._buff(386311,now,duration=500)+self._buff(386312,now,duration=500))
            packets.append(scene(skills=(self._skill_event(386301,start,dest,ready=1),)))
            self._queue(now+500,'tsubasa_space',cast)
        else:
            self.e_count-=1
            if not self.e_next_charge:self.e_next_charge=now+self.skill_cooldown(6000)
            intended=aimed(start,dest,300,fixed=True)
            body,correction=prepare_displacement(self,now,interrupt=False)
            body=body if correction else start
            duration=self._set_motion(body,intended,720,now,kind=3)
            cast.update(finish=now+duration,previous=now,bounced=False);self.dash=cast;self.forced_until=cast['finish']
            packets.extend(self._buff(386111,now)+self._buff(386232,now)+self._buff(386202,now)+self._buff(386221,now,duration=duration+500))
            packets.extend(correction)
            packets.append(scene(moves=(self._move_event(self.motion[1],720,3),),skills=(self._skill_event(386201,start,dest),)))
            packets.append(self._cooldown(1));self._queue(now+min(20,duration),'tsubasa_dash',cast)
        return packets+self.sync_speed(now)+stopped
