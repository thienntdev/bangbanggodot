"""Ichigo: three-step reserves, Bankai slots and four generation-bound cuts."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import rect_contact
from combat_math import D
from combat_protocol import props,scene
from melee_common import enemies,in_strip,piercing_step

SLOTS={0:339100,1:339201,2:339301,10:339401}


class IchigoActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=150;self.e_count=3;self.e_next_charge=0
        self.ready=self.vanish=None;self.next_stack_at=0

    def _skill(self,slot,now):
        if slot==0:return 339121 if self.has_buff(339111,now) else 339106 if self.has_buff(339308,now) else 339100
        if slot==2 and self.has_buff(339303,now):return 339306
        if slot==10 and self.has_buff(339302,now):return 339305
        return SLOTS[slot]

    def _cooldown(self,slot,changed=False):
        skill=self._skill(slot,self.clock())
        body=props(skill,slot,self.e_count if slot==1 else -1,0 if skill==339306 else self.cooldowns[slot],self.e_next_charge if slot==1 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(150,self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def on_spawn(self,now):
        self.mp=150;self.ready=self.vanish=None;self.next_stack_at=0
        self._queue(now+3000,'ichigo_energy',self.generation)
        return self._buff(339101,now)+self._buff(339102,now)+[scene(mp=(struct.pack('<Ii',self.id,self.mp),))]+[self._cooldown(s,True) for s in (0,2,10)]

    def _empower(self,now):
        return self._buff(339111,now)+[self._cooldown(0,True)]

    def _hit(self,target,power,now,*,critical_display=False):
        packets,lost=self.damage(power,now,target=target,critical_display=critical_display)
        if lost and self.alive and now>=self.next_stack_at:
            self.next_stack_at=now+500
            for template in (339112,339113,339114):packets.extend(self._buff(template,now))
        return packets

    def remove_buff(self,template,now,*,expired=False):
        packets=super().remove_buff(template,now,expired=expired)
        if template in (339111,339308,339303,339302):
            slot={339111:0,339308:0,339303:2,339302:10}[template]
            packets.append(self._cooldown(slot,True));packets.append(self._cooldown(slot))
        return packets

    def cleanse(self,now):
        packets=super().cleanse(now)
        for owner,template in list(self.active_buffs):
            source=self.arena.actors.get(self.buff_sources.get(template))
            if owner==self.id and source and source.camp!=self.camp and int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']) in (30,35,36,39,62,66):
                packets.extend(self.remove_buff(template,now))
        return packets

    def _speed(self,now):
        return 0 if self.vanish else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.vanish) or super().blocked(action,now)

    def cc_immune(self,now,*,slow=False):
        return bool(self.vanish) or super().cc_immune(now,slow=slow)

    def reject_buff(self,row,source,now):
        return bool(self.vanish and source.camp!=self.camp)

    def _end_vanish(self,now):
        cast,self.vanish=self.vanish,None
        if not cast:return []
        self.info['untargetable']=cast['was_untargetable'];self.info['damage_immune']=cast['was_immune']
        packets=self.remove_buff(339336,now)+self.remove_buff(339346,now)
        packets.extend(self.remove_object(cast['object']))
        return packets+self.sync_speed(now)

    def interrupt(self,now):
        if self.alive and self.vanish:return []
        self.ready=None
        return self._end_vanish(now) if not self.alive else []

    def update(self,now):
        packets=[]
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count=min(3,self.e_count+1)
            self.e_next_charge=self.e_next_charge+self.skill_cooldown(6000) if self.e_count<3 else 0
            packets.append(self._cooldown(1))
        return packets+super().update(now)

    def _blade(self,flight,target,now):
        if flight['basic']:
            targets=[target] if flight['template']==339100 else [t for t in enemies(self,area=True) if math.dist(target.position_at(now),t.position_at(now))<=96]
            packets=[]
            for t in targets:packets.extend(self.damage(flight['raw'],now,target=t,basic=True)[0])
            return packets
        current=self.alive and self.generation==flight['source_generation']
        packets=self._hit(target,flight['raw'],now) if current else self.damage(flight['raw'],now,target=target)[0]
        return packets+self._buff(339315 if flight['template']==339305 else 339402,now,target.id)

    def _flight(self,flight,now):
        if flight['template']==339201:
            if now<flight['finish']:
                self._queue(flight['finish'],'flight',flight)
                return []
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        return piercing_step(self,flight,now,self._blade,pierce=not flight['basic'])

    def _enhanced(self,start,dest,now):
        power=self.combat_stat('iAttack',now);packets=[];landed=False
        for target in enemies(self,area=True):
            pos=target.position_at(now)
            if not in_strip(pos,start,dest,408,72) or rect_contact(start,pos,self.arena.water_rects(now)) is not None:continue
            tip=not in_strip(pos,start,dest,240,72)
            hit,lost=self.damage(power*(D('1.5') if tip else 1),now,target=target,basic=True)
            packets.extend(hit);landed|=lost
            if tip:packets.extend(self._buff(339122,now,target.id))
            if target.buff_sources.get(339210)==self.id:packets.extend(target.remove_buff(339210,now))
            packets.extend(self._buff(339127,now,target.id))
        if landed:packets.extend(self.restore_hp(power,now)+self._resource(15))
        packets.append(scene(skills=(self._skill_event(339121,start,dest),)))
        return packets+self.remove_buff(339111,now)

    @staticmethod
    def _airborne(target,now):
        return any(owner==target.id and end>now and table_row('BuffTemplate_table.xml',nBuffId=t).get('nBuffShowType')=='1'
                   for (owner,t),(_,end) in target.active_buffs.items())

    def _event(self,now,kind,data):
        if kind=='ichigo_step':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation']:return []
            start=self.position_at(now);aim=target.position_at(now);dest=self.blink_destination(start,aim)
            self.position,self.motion,self.forced_until=dest,None,now
            packets=self.shoot(339201,start,aim,now,0,school='physical',target=target,through_walls=True,fixed_destination=True)
            packets.append(scene(moves=(self._move_event(dest,0,5),)))
            if target.camp!=self.camp:
                packets.extend(self._hit(target,cast['power']*D('1.25'),now))
                packets.extend(self._buff(339210,now,target.id))
            for template in (339204,339205,339206):packets.extend(self._buff(template,now))
            return packets+self._empower(now)
        if kind=='ichigo_energy':
            if not self.alive or data[0]!=self.generation:return []
            self._queue(now+3000,kind,*data);return self._resource(5)
        if kind=='ichigo_form':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;packets=self.cleanse(now)+self._resource(75)
            self.cooldowns[10]=0
            for template in (339301,339302,339303,339308,339309):packets.extend(self._buff(template,now))
            packets.extend(self._empower(now))
            return packets+[self._cooldown(s,True) for s in (0,2,10)]+[self._cooldown(10)]
        if kind=='ichigo_cut':
            cast,index=data
            if self.vanish is not cast or not self.alive:return []
            packets=[]
            for ident,generation in cast['targets']:
                target=self.arena.actors.get(ident)
                if target and target.alive and target.generation==generation:
                    # User chose .75 AP and the native guaranteed critical (x2).
                    packets.extend(self._hit(target,cast['power']*D('1.5'),now,critical_display=True))
            if index<3:self._queue(now+375,kind,cast,index+1)
            else:packets.extend(self._end_vanish(now))
            return packets
        return super()._event(now,kind,data)

    def _start_step(self,start,dest,target,now,power):
        self.e_count-=1
        if not self.e_next_charge:self.e_next_charge=now+self.skill_cooldown(6000)
        self.cooldowns[1]=now+self.skill_cooldown(1500, 1)
        self.ready=dict(slot=1,target=target.id,target_generation=target.generation,power=power)
        self._queue(now+50,'ichigo_step',self.ready)
        return self._resource(-40)+self._buff(339207,now)+[self._cooldown(1)]

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or not self.alive or self.vanish:return []
        skill=self._skill(slot,now)
        if slot!=2 or skill==339306:
            if self.blocked('attack',now) or self.skill_sealed(slot,now):return []
        if skill!=339306 and self.cooldowns[slot]>now:return []
        if slot in (0,10) and start==dest or self.ready:return []
        target=self.arena.actors.get(target_id)
        if slot==1:
            if not self.e_count or self.mp<40 or not target or target is self or not target.alive or target.is_untargetable() or math.dist(start,target.position_at(now))>432:return []
            if target.has_buff(339210,now) and target.buff_sources.get(339210)==self.id:return []
            if target.camp!=self.camp:
                from bot_ai import team_visible
                if not team_visible(self.arena,self,target,now):return []
        if slot==10 and self.mp<30:return []
        if skill==339306:
            from bot_ai import team_visible
            candidates=[t for t in enemies(self) if self._airborne(t,now) and math.dist(start,t.position_at(now))<=600
                        and team_visible(self.arena,self,t,now)]
            if not candidates:return []
            target=min(candidates,key=lambda t:(math.dist(start,t.position_at(now)),t.id))
        power=self.combat_stat('iAttack',now);packets=[]
        if slot==0:
            self.cooldowns[0]=now+self.fire_interval(now)
            packets=self._enhanced(start,dest,now) if skill==339121 else self.shoot(skill,start,dest,now,power,school='physical',basic=True)
        elif slot==1:
            return self._start_step(start,dest,target,now,power)
        elif slot==10:
            self.cooldowns[10]=now+self.skill_cooldown(8000, 10);packets=self._resource(-30)
            packets.extend(self.shoot(skill,start,dest,now,power*D('1.65'),school='physical',through_walls=True))
            if skill==339305:packets.extend(self.remove_buff(339302,now))
            packets.extend(self._empower(now))
        elif skill==339301:
            self.cooldowns[2]=now+self.skill_cooldown(25000, 2);self.ready=dict(slot=2,dest=start)
            self._queue(now+50,'ichigo_form',self.ready)
            packets=[scene(skills=(self._skill_event(skill,start,start),))]
        else:
            center=target.position_at(now);targets=[t for t in enemies(self,area=True) if math.dist(center,t.position_at(now))<=96]
            self.position,self.motion=self.blink_destination(start,center),None
            packets=self.remove_buff(339303,now)
            ident,packet=self.add_object(339327,center);packets.append(packet)
            self.vanish=dict(power=power,targets=[(t.id,t.generation) for t in targets],object=ident,
                             was_untargetable=self.info.get('untargetable',False),was_immune=self.info.get('damage_immune',False))
            self.info['untargetable']=self.info['damage_immune']=True
            for t in targets:packets.extend(self._buff(339306,now,t.id))
            for template in (339336,339346):packets.extend(self._buff(template,now))
            packets.extend(self._empower(now)+self.sync_speed(now));packets.append(scene(moves=(self._move_event(self.position,0,5),)))
            self._queue(now+375,'ichigo_cut',self.vanish,0)
        return packets+[self._cooldown(slot)]
