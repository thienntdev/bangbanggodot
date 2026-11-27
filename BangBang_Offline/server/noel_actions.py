"""Noel's gifts, mixed-team projectiles and native rescue box."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from hulu_actions import HuluTurret
from melee_common import aimed, piercing_step, prepare_displacement

SLOTS = {0:329100,1:329201,2:329301,10:329401}


class NoelActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready = None
        self.e_count = self.r_count = 3
        self.e_next_charge = self.r_next_charge = 0

    def _cooldown(self,slot,changed=False):
        prefix = 'e' if slot==1 else 'r'
        count = getattr(self,prefix+'_count') if slot in (1,10) else -1
        next_charge = getattr(self,prefix+'_next_charge') if slot in (1,10) else 0
        body = props(SLOTS[slot],slot,count,self.cooldowns[slot],next_charge)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready = None
        return self._buff(329101,now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def interrupt(self,now):
        packets = []
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            self.ready = None
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        if not self.ready:return []
        row=table_row('BuffTemplate_table.xml',nBuffId=template)
        mask=int(row.get('fEffectValB',0))
        return self.interrupt(now) if row['nEffectType'] in ('35','66') and (not mask or mask&{1:2,10:8}[self.ready['slot']]) else []

    def update(self,now):
        packets=[]
        for slot,prefix in ((1,'e'),(10,'r')):
            due=getattr(self,prefix+'_next_charge')
            while due and due<=now:
                count=min(3,getattr(self,prefix+'_count')+1)
                setattr(self,prefix+'_count',count)
                due=due+self.skill_cooldown(6000) if count<3 else 0
                setattr(self,prefix+'_next_charge',due)
                packets.append(self._cooldown(slot))
        if self.ready and self.skill_sealed(self.ready['slot'],now):packets.extend(self.interrupt(now))
        return packets+super().update(now)

    def _gift(self,now):
        start=self.position_at(now)
        candidates=[]
        for radius in (72,120,168):
            for i in range(16):
                angle=math.tau*i/16
                pos=round(start[0]+radius*math.cos(angle)),round(start[1]+radius*math.sin(angle))
                if self.arena.free_position(pos,now)==pos:candidates.append(pos)
        if not candidates:return []
        template=self.arena.rng.choice((329103,329104,329105))
        return self.shoot(template,start,self.arena.rng.choice(candidates),now,D(0),school='energy',
                          fixed_destination=True,through_walls=True)

    def _gift_reward(self,target,template,generation,now):
        packets=[]
        if template==329103:packets.extend(self._buff(329113,now,target.id))
        elif template==329104:packets.extend(target.add_shield(329114,target.max_hp*D('.2'),now,caster=self))
        if self.alive and self.generation==generation and not self.effect_blocked():
            for slot,field in ((1,'e_next_charge'),(10,'r_next_charge'),(2,None)):
                old=getattr(self,field) if field else self.cooldowns[slot]
                if old:
                    remaining=max(0,old-now-500)
                    if template==329105:remaining=round(remaining*.8)
                    if field:setattr(self,field,now+remaining)
                    else:self.cooldowns[slot]=now+remaining
                    packets.append(self._cooldown(slot))
        return packets

    def _box_hit(self,flight,target,now):
        if target.info.get('npc_template') or target.cc_immune(now):return []
        packets=self._buff(329301,now,target.id)+self._buff(329302,now,target.id)
        if target.has_buff(329302,now):
            self._queue(now+830,'noel_box',dict(target=target.id,target_generation=target.generation,
                version=target.buff_versions[329302],source_generation=flight['source_generation']))
        return packets

    def _flight(self,flight,now):
        template=flight['template']
        if template==329100:return super()._flight(flight,now)
        if template==329301:return piercing_step(self,flight,now,self._box_hit,pierce=False,contact_radius=72)
        if template==329201:
            a=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
            b=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
            contacts=[]
            for target in self.arena.actors.values():
                key=target.id,target.generation
                if not target.alive or target.is_untargetable() or key in flight['hits'] or target.info.get('npc_template') in (20017,20006,329303):continue
                hit=actor_contact(a,b,target,flight['previous'],now,84)
                if hit is not None:contacts.append((hit,target.id,target,key))
            packets=[]
            for _,_,target,key in sorted(contacts):
                if target.camp!=self.camp and self.projectile_blocked(target,now):return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
                flight['hits'].add(key)
                packets.extend(target.restore_hp(flight['raw'],now) if target.camp==self.camp else self.damage(flight['raw'],now,target=target,school='energy')[0])
            if now>=flight['finish']:return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        else:
            packets=[]
            if template==329401:
                a=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
                b=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
                for target in self.arena.actors.values():
                    if target.alive and target.camp!=self.camp and not target.is_untargetable() and actor_contact(a,b,target,flight['previous'],now) is not None and self.projectile_blocked(target,now):
                        return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            if now>=flight['finish']:
                packets.append(scene(blown_bullets=(struct.pack('<I',flight['id']),)))
                if template==329401:
                    for target in list(self.arena.actors.values()):
                        if not target.alive or not target.is_area_targetable() or math.dist(flight['end'],target.position_at(now))>120:continue
                        if target.camp==self.camp:
                            if target is not self or flight['source_generation']==self.generation:packets.extend(target.restore_hp(flight['raw'],now))
                        else:
                            packets.extend(self.damage(flight['raw'],now,target=target,school='energy')[0])
                            packets.extend(self._buff(329402,now,target.id))
                else:
                    ident,packet=self.add_object(template,flight['end']);packets.append(packet)
                    self._queue(now+50,'noel_pickup',dict(id=ident,pos=flight['end'],template=template,
                        previous=now,end=now+5000,generation=flight['source_generation']))
                return packets
        flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _event(self,now,kind,data):
        if kind=='noel_cast':
            cast,=data
            if self.ready is not cast or not self.alive or cast['generation']!=self.generation:return []
            self.ready=None
            start=self.position_at(now)
            packets=self.sync_speed(now)
            if cast['slot']==1:packets.extend(self.restore_hp(cast['power']*D('2.25'),now))
            packets.extend(self.shoot(cast['skill'],start,cast['dest'],now,cast['power']*D('2.25' if cast['slot']==1 else '1.65'),
                school='energy',power=cast['power'],through_walls=True,fixed_destination=cast['slot']==10,
                hit_ids=((self.id,self.generation),) if cast['slot']==1 else ()))
            return packets
        if kind=='noel_pickup':
            gift,=data
            if gift['id'] not in self.arena.objects:return []
            targets=[]
            for target in self.arena.actors.values():
                if not target.alive or target.camp!=self.camp or target.info.get('npc_template') or target.is_untargetable():continue
                hit=circle_contact(target.position_at(gift['previous']),target.position_at(now),gift['pos'],gift['pos'],72)
                if hit is not None:targets.append((hit,target.id,target))
            if targets or now>=gift['end']:
                packets=self.remove_object(gift['id'],destroyed=bool(targets))
                if targets:packets.extend(self._gift_reward(min(targets)[2],gift['template'],gift['generation'],now))
                return packets
            gift['previous']=now;self._queue(min(now+50,gift['end']),kind,gift);return []
        if kind=='noel_box':
            cast,=data;target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation'] or target.is_untargetable() or target.cc_immune(now) or target.buff_versions.get(329302)!=cast['version']:return []
            _,packets=prepare_displacement(target,now,interrupt=False)
            packets+=target.update(now)+target.interrupt(now)
            target.position,target.motion=target.position_at(now),None
            # Durations live in tuples so checkpoint timestamp rebasing cannot
            # mistake them for absolute cooldown/charge deadlines.
            saved=dict(remaining_slots=[(k,max(0,v-now)) for k,v in target.cooldowns.items()],remaining_fields=[])
            for key,value in vars(target).items():
                if key in ('e_count','r_count','space_count') or key.endswith('_next_charge'):
                    saved['remaining_fields'].append((key,max(0,value-now) if key.endswith('_next_charge') and value else value))
            info=dict(acct_id=self.info['acct_id'],tank_id=self.info['tank_id'],tank_level=self.info['tank_level'],
                npc_template=329303,owner=self.id,in_room=True,name='Hộp Quà Noel',summon_stats=dict(self.stats),
                target=target.id,target_generation=target.generation)
            info['summon_stats'].update(iHp='6000',iArmor='0',iEgArmor='0',iSpeed='0')
            box=NoelBox(self.arena,self._new_id(5),info,self.camp,target.position)
            box.saved=saved;self.arena.actors[box.id]=box
            box.end=now+8000;box._queue(box.end,'noel_release')
            packets.extend([box.snapshot(now)]+box._buff(329303,now))
            for template in (329305,329306,329304):packets.extend(self._buff(template,now,target.id,duration=8000))
            target.noel_box=box.id
            return packets+[scene(moves=(target._move_event(target.position,0,5),))]+target.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now or start==dest:return []
        prefix='e' if slot==1 else 'r'
        if slot in (1,10) and not getattr(self,prefix+'_count'):return []
        power=self.combat_stat('iEgAtk',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:1500,10:1500,2:25000}[slot], slot)
        if slot==0:return self.shoot(329100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        packets=self._gift(now)
        if slot==2:return packets+[self._cooldown(slot)]+self.shoot(329301,start,dest,now,D(0),school='energy',through_walls=True)
        setattr(self,prefix+'_count',getattr(self,prefix+'_count')-1)
        if not getattr(self,prefix+'_next_charge'):setattr(self,prefix+'_next_charge',now+self.skill_cooldown(6000))
        self.ready=dict(slot=slot,skill=SLOTS[slot],dest=aimed(start,dest,720) if slot==10 else dest,power=power,generation=self.generation)
        body,stopped=prepare_displacement(self,now,interrupt=False)
        self.position,self.motion=body if stopped else start,None;self._queue(now+50,'noel_cast',self.ready)
        return packets+[scene(skills=(self._skill_event(SLOTS[slot],start,self.ready['dest'],ready=1),)),self._cooldown(slot)]+self.sync_speed(now)+stopped


class NoelBox(HuluTurret):
    def hold(self,target,now):
        target.cooldowns={slot:now+remaining for slot,remaining in self.saved['remaining_slots']}
        for key,value in self.saved['remaining_fields']:
            setattr(target,key,now+value if key.endswith('_next_charge') and value else value)

    def snapshot(self,now):
        body=struct.pack('<IIhhiBiIiH',self.id,329303,*self.position_at(now),math.ceil(self.hp),self.camp,
                         6000,self.info['owner'],0,0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def reject_buff(self,row,source,now):return source.camp!=self.camp
    def cc_immune(self,now,*,slow=False):return True
    def on_spawn(self,now):return []
    def cast(self,*args):return []
    def restore_hp(self,*args,**kwargs):return []
    def add_shield(self,*args,**kwargs):return []

    def release(self,now):
        target=self.arena.actors.get(self.info['target'])
        if not target or target.generation!=self.info['target_generation'] or getattr(target,'noel_box',None)!=self.id:return []
        target.noel_box=None
        self.hold(target,now)
        packets=[]
        for template in (329304,329305,329306):packets.extend(target.remove_buff(template,now))
        for slot in target.cooldowns:packets.append(target._cooldown(slot))
        return packets+target.sync_speed(now)

    def commit_hp(self,hp,now,*,critical=False):
        packets=self.release(now) if hp<=0 else []
        return packets+super().commit_hp(hp,now,critical=critical)

    def _event(self,now,kind,data):
        if kind=='noel_release':return self.commit_hp(D(0),now) if self.alive else []
        return super()._event(now,kind,data)
