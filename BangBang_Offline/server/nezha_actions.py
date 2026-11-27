"""Na Tra: returning rings, finite root propagation and the base three-head form."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,piercing_step

SLOTS={0:356100,1:356201,2:356301,10:356401}
FORM_BUFFS=(356303,356305,356306,356307,356308,356309,356310,356311,356324,356325)


class NezhaActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.form=self.e_follow=None;self.passive_ready_at=0

    def _skill(self,slot):
        if slot==1 and self.e_follow:return 356211
        if self.form and self.form['landed']:return {0:356601,1:356221,2:356301,10:356411}[slot]
        return SLOTS[slot]

    def _cooldown(self,slot,changed=False):
        body=props(self._skill(slot),slot,end=0 if slot==1 and self.e_follow or slot==2 and self.form else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=self.form=self.e_follow=None;self.passive_ready_at=0
        packets=[]
        for t in (356101,356102,356103):packets.extend(self._buff(t,now))
        return packets+[self._cooldown(s,True) for s in (0,1,10)]

    def attr_bonus(self,attributes,now):
        value=super().attr_bonus(attributes,now)
        # Native old form buffs display its gains. The approved version grants
        # AP only, as a cast-time amount; do not also increase EN by attribute1.
        if 1 in attributes and self.has_buff(356325,now):value-=D('.1')*self.buff_stacks[356325]
        return value

    def combat_stat(self,key,now):
        value=super().combat_stat(key,now)
        if key=='iAttack' and self.form and self.form['landed'] and self.has_buff(356325,now):
            value+=self.form['power']*D('.15')*self.form['count']
        return value

    def damage(self,raw,now,**kwargs):
        if self.has_buff(356121,now):raw*=1+D('.1')*self.buff_stacks.get(356121,0)
        return super().damage(raw,now,**kwargs)

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        return self._buff(356121,now) if self.alive and hit.hp_loss>0 else []

    def on_control(self,source,template,now):
        if not self.alive or now<self.passive_ready_at:return []
        self.passive_ready_at=now+3000
        packets=self.restore_hp((self.max_hp-self.hp)*D('.1'),now)
        for slot,amount in ((1,800),(10,800),(2,3000)):
            self.cooldowns[slot]=max(now,self.cooldowns[slot]-amount);packets.append(self._cooldown(slot))
        return packets

    def _protection(self,now):
        return self._buff(356111,now)+self._buff(356112,now)

    def _vanished(self):
        return bool(self.form and not self.form['landed'])

    def blocked(self,action,now):
        return self._vanished() or bool(self.ready) or super().blocked(action,now)

    def _speed(self,now):
        return 0 if self._vanished() else super()._speed(now)

    def cc_immune(self,now,*,slow=False):
        return self._vanished() or super().cc_immune(now,slow=slow)

    def reject_buff(self,row,source,now):
        return self._vanished() and source.camp!=self.camp

    def _max_hp_packet(self):
        self.info['max_hp']=math.ceil(self.max_hp)
        return 1560,struct.pack('<IBi',self.info['acct_id'],3,math.ceil(self.max_hp))

    def _end_form(self,now):
        form,self.form=self.form,None
        if not form:return []
        self.info['untargetable']=form['was_untargetable'];self.info['damage_immune']=form['was_immune']
        self.max_hp=form['max_hp'];self.cooldowns[2]=now+self.skill_cooldown(30000, 2)
        packets=self.remove_object(form['object'])+[self._max_hp_packet()]
        if self.hp>self.max_hp:packets.extend(self.commit_hp(self.max_hp,now))
        for template in (*FORM_BUFFS,356302):packets.extend(self.remove_buff(template,now))
        return packets+[self._cooldown(s,True) for s in (0,1,2,10)]+self.sync_speed(now)

    def _end_follow(self,now):
        self.e_follow=None
        return self.remove_buff(356205,now)+[self._cooldown(1,True),self._cooldown(1)]

    def interrupt(self,now):
        if self._vanished() and self.alive:return []
        packets=self.remove_object(self.ready['object']) if self.ready and 'object' in self.ready else []
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
        self.ready=None
        return packets+self._end_form(now)+self._end_follow(now) if not self.alive else packets

    @staticmethod
    def _directions(start,dest,angles):
        angle=math.atan2(dest[1]-start[1],dest[0]-start[0])
        return [(round(start[0]+480*math.cos(angle+math.radians(a))),
                 round(start[1]+480*math.sin(angle+math.radians(a)))) for a in angles]

    def _root(self,target,now,chain):
        key=target.id,target.generation
        if key in chain['visited'] or target.has_buff(356403,now):return []
        packets=self._buff(356402,now,target.id)
        if not target.has_buff(356402,now) or target.buff_sources.get(356402)!=self.id:return packets
        chain['visited'].add(key)
        packets.extend(self._buff(356403,now,target.id))
        self._queue(now+1000,'nezha_spread',chain,target.id,target.generation,target.buff_versions[356402])
        return packets

    def _bullet_hit(self,flight,target,now):
        if flight['basic']:return self.damage(flight['raw'],now,target=target,basic=True,
                                             critical_handled=flight['template']==356601,
                                             critical_display=flight['template']==356601)[0]
        if flight['template'] in (356401,356411):
            return self.damage(flight['raw'],now,target=target)[0]+self._root(target,now,flight['context'])
        cast=flight['context'];key=target.id,target.generation
        raw=flight['raw']*(D('.2') if key in cast['hits'] else 1);cast['hits'].add(key)
        return self.damage(raw,now,target=target)[0]+self._buff(356202,now,target.id)

    def _return_ring(self,flight,pos,now):
        if not self.alive or self.generation!=flight['source_generation']:return []
        return self.shoot(356501,pos,self.position_at(now),now,0,school='physical',through_walls=True,
            target=self,context=flight['context'])

    def _flight(self,flight,now):
        if flight['template']==356501:
            if not self.alive or self.generation!=flight['source_generation']:
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            start=flight['pos'];dest=self.position_at(now)
            end=point_at(start,dest,min(1,flight['speed']*(now-flight['previous'])/1000/max(1,math.dist(start,dest))))
            packets=[]
            if dest!=flight['end']:
                packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))))
            flight['pos']=end;flight['end']=dest
            caught=circle_contact(start,end,self.position_at(flight['previous']),dest,48) is not None
            if caught or now>=flight['finish']:
                packets.append(scene(expired_bullets=(struct.pack('<I',flight['id']),)))
                cast=flight['context']
                if caught and not cast['caught']:
                    cast['caught']=True;self.cooldowns[1]=now+self.skill_cooldown(1500, 1)
                    packets.extend(self._buff(356501,now));packets.append(self._cooldown(1))
                return packets
            flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
            return packets
        if flight['template'] not in (356201,356221):
            return piercing_step(self,flight,now,self._bullet_hit,pierce=False)
        start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        contacts=[(h,t.id,t) for t in enemies(self)
            if (h:=actor_contact(start,end,t,flight['previous'],now)) is not None]
        packets=[]
        if contacts:
            hit,_,target=min(contacts,key=lambda c:c[:2])
            if self.projectile_blocked(target,now):return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            packets.extend(self._bullet_hit(flight,target,now));end=point_at(start,end,hit)
        if contacts or now>=flight['finish']:
            packets.append(scene(blown_bullets=(struct.pack('<I',flight['id']),)))
            return packets+self._return_ring(flight,tuple(round(v) for v in end),now)
        flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _event(self,now,kind,data):
        if kind=='nezha_follow_end':
            return self._end_follow(now) if self.e_follow is data[0] else []
        if kind=='nezha_e':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;start=self.position_at(now)
            skill=cast['skill']
            packets=[scene(skills=(self._skill_event(skill,start,cast['dest']),))]
            for dest in self._directions(start,cast['dest'],(0,120,-120) if skill==356221 else (0,)):
                packets.extend(self.shoot(skill,start,dest,now,cast['power']*D('2.12'),school='physical',through_walls=True,context=cast))
            return packets
        if kind=='nezha_spread':
            chain,ident,generation,version=data;target=self.arena.actors.get(ident)
            if not target or not target.alive or target.generation!=generation or target.buff_versions.get(356402)!=version:return []
            packets=[]
            for other in enemies(self,area=True):
                if math.dist(target.position_at(now),other.position_at(now))<=144:packets.extend(self._root(other,now,chain))
            return packets
        if kind=='nezha_form_start':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;self.form=cast;cast.update(landed=False,count=0,max_hp=self.max_hp,
                was_immune=self.info.get('damage_immune',False),was_untargetable=self.info.get('untargetable',False),end=now+13000)
            packets=self.cleanse(now)+self.restore_hp((self.max_hp-self.hp)*D('.4'),now)
            self.info['untargetable']=self.info['damage_immune']=True
            self.position,self.motion=cast['dest'],None
            packets.extend(self._buff(356302,now))
            self._queue(now+1000,'nezha_land',cast);self._queue(cast['end'],'nezha_form_end',cast)
            return packets+[scene(moves=(self._move_event(self.position,0,5),))]+self.sync_speed(now)
        if kind=='nezha_land':
            cast,=data
            if self.form is not cast or not self.alive:return []
            self.info['untargetable']=cast['was_untargetable'];self.info['damage_immune']=cast['was_immune']
            # Landing consumes the warning with its original impact movie.
            # interrupt/_end_form still expire cancelled warnings silently.
            packets=self.remove_object(cast['object'],destroyed=True)+self.remove_buff(356302,now)
            targets=[t for t in enemies(self,area=True) if math.dist(cast['dest'],t.position_at(now))<=216]
            cast['count']=min(3,sum(not t.info.get('npc_template') for t in targets))
            for target in targets:
                packets.extend(self.damage(cast['power']*D('2.1'),now,target=target)[0])
                packets.extend(self._buff(356322,now,target.id))
            cast['landed']=True;bonus=cast['max_hp']*D('.15')*cast['count'];self.max_hp=cast['max_hp']+bonus
            packets.append(self._max_hp_packet());packets.extend(self.commit_hp(min(self.max_hp,self.hp+bonus),now))
            for template in FORM_BUFFS:
                if template in (356324,356325) and not cast['count']:continue
                packets.extend(self._buff(template,now,duration=12000,stacks=cast['count'] if template in (356324,356325) else None))
            return packets+[self._cooldown(s,True) for s in (0,1,10)]+self.sync_speed(now)
        if kind=='nezha_form_end':
            return self._end_form(now) if self.form is data[0] else []
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now):return []
        follow=slot==1 and self.e_follow
        if not follow and self.cooldowns[slot]>now:return []
        if start==dest or slot==2 and (self.form or not self._inside(dest) or math.dist(start,dest)>720):return []
        skill=self._skill(slot);power=self.combat_stat('iAttack',now);packets=[]
        if slot==0:
            self.cooldowns[0]=now+self.fire_interval(now)
            angles=range(-160,161,40) if skill==356601 else (0,)
            for aim in self._directions(start,dest,angles):
                # Native form is .5 AP with guaranteed x2 critical, per pellet.
                packets.extend(self.shoot(skill,start,aim,now,power,school='physical',basic=True))
        elif follow:
            packets.extend(self._end_follow(now)+self._protection(now))
            duration=self._set_motion(start,aimed(start,dest,240,fixed=True),720,now,3)
            self.forced_until=now+duration
            packets.append(scene(skills=(self._skill_event(356211,start,self.motion[1]),),moves=(self._move_event(self.motion[1],720,3),)))
        elif slot==1:
            self.cooldowns[1]=now+self.skill_cooldown(8000, 1);self.e_follow=dict(end=now+3000)
            packets.extend(self._protection(now)+self._buff(356205,now))
            cast=dict(slot=1,skill=skill,power=power,dest=dest,hits=set(),caught=False)
            self.ready=cast;self._queue(now+50,'nezha_e',cast)
            # Match the existing 50ms native windup on both self and remote
            # clients, before E is exposed as its follow-up dash.
            packets.append(scene(skills=(self._skill_event(skill,start,dest,ready=1),)))
            self._queue(now+3000,'nezha_follow_end',self.e_follow);packets.append(self._cooldown(1,True))
        elif slot==10:
            self.cooldowns[10]=now+self.skill_cooldown(8000, 10);packets.extend(self._protection(now));chain=dict(visited=set())
            for aim in self._directions(start,dest,(0,120,-120) if skill==356411 else (0,)):
                packets.extend(self.shoot(skill,start,aim,now,power*D('1.69'),school='physical',through_walls=True,context=chain))
        else:
            pos=self.blink_destination(start,dest);ident,packet=self.add_object(356314,pos)
            self.ready=dict(slot=2,skill=356301,dest=pos,object=ident,power=power)
            self.cooldowns[2]=now+self.skill_cooldown(30000, 2)
            packets.extend([packet,scene(skills=(self._skill_event(356301,start,pos,ready=1),))]+self._protection(now))
            self._queue(now+100,'nezha_form_start',self.ready)
        return packets+[self._cooldown(slot)]
