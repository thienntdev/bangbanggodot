"""Daredevil records post-shield damage and adjusted healing in one fixed ledger."""
from dataclasses import replace
import heapq
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import point_at
from combat_math import D,quantize
from combat_protocol import props,scene
from melee_common import aimed,enemies,in_strip,piercing_step

SLOTS={0:391100,1:391201,2:391301,10:391401}
CHARGES={1:('e',2,8000,4000),2:('space',3,8000,5000),10:('r',2,6000,3000)}


class DaredevilActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.dash=self.ledger=None;self.passive_ready_at=0
        for name,count,_,_ in CHARGES.values():setattr(self,name+'_count',count);setattr(self,name+'_next_charge',0)

    def _cooldown(self,slot,changed=False):
        skill=SLOTS[slot];count=-1;charge=0
        if slot==0:
            if self.has_buff(391111,self.clock()):skill=391111
            elif self.has_buff(391307,self.clock()):skill=391311
        else:
            name=CHARGES[slot][0];count=getattr(self,name+'_count');charge=getattr(self,name+'_next_charge')
        body=props(skill,slot,count,self.cooldowns[slot],charge)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=self.dash=self.ledger=None;self.passive_ready_at=0
        packets=[self._cooldown(0,True)]
        for template in range(391101,391106):packets+=self._buff(template,now)
        return packets+self.sync_speed(now)

    def missing_bonus(self):return max(D(0),1-self.hp/self.max_hp)

    def attr_bonus(self,attributes,now):
        return super().attr_bonus(attributes,now)+(self.missing_bonus() if 10 in attributes else D(0))

    def _speed(self,now):
        if self.ready or self.dash or self.blocked('move',now):return 0
        return max(0,super()._speed(now)+round(D(self.stats['iSpeed'])*self.missing_bonus()))

    def blocked(self,action,now):return bool(self.ready or self.dash) or super().blocked(action,now)

    def restore_hp(self,amount,now):
        return super().restore_hp(D(amount)*(D('1.25') if self.ledger else 1),now)

    def defer_heal(self,amount,now):
        self.ledger['healing']+=amount
        return []

    def defer_hit(self,hit,now,source,school,source_generation=None,*,transferred=False,credit_override=None):
        amount=max(D(0),hit.potential_damage-hit.shield_absorbed)
        if amount:
            self.ledger['damage']+=quantize(amount*(1 if transferred else D('.75')))
            hold=getattr(self,'caocao_hostage',None)
            self.ledger['source']=(hold['owner'],hold['generation']) if hold and hold['end']>now else (credit_override or (source.id,source.generation if source_generation is None else source_generation))
        return replace(hit,hp_loss=D(0),hp_after=self.hp,overkill=D(0),killed=False)

    def _cast_cost(self,now):
        # HP costs are outside the ledger even when another cast is pending.
        packets=self.commit_hp(quantize(self.hp*D('.85')),now)+self._buff(391111,now)
        if not self.ledger:
            self.ledger=dict(end=now+1000,damage=D(0),healing=D(0),source=None,generation=self.generation)
            self._queue(now+1000,'dare_settle',self.ledger)
            packets+=self._buff(391113,now)
        return packets+[self._cooldown(0,True)]+self.sync_speed(now)

    def _settle(self,cast,now):
        if self.ledger is not cast:return []
        self.ledger=None
        if not self.alive or cast['generation']!=self.generation:return []
        packets=self.remove_buff(391113,now)
        if self.in_stasis():return packets
        net=cast['healing']-cast['damage']
        floor=min(self.hp,max(D(self.info.get('death_floor',0)),D(1) if self.has_buff(359301,now) else D(0)))
        hp=min(self.max_hp,max(floor,self.hp+net))
        self.damage_credit=cast['source'] if hp<self.hp else None
        try:packets+=self.commit_hp(hp,now)
        finally:self.damage_credit=None
        return packets+self.sync_speed(now)

    def dodge_projectile(self,now):
        flight=getattr(self.arena,'current_flight',None)
        if not self.alive or not flight or self.in_stasis() or now<self.passive_ready_at:return False
        if self.arena.rng.random()>=.25:return False
        self.passive_ready_at=now+250
        self._queue(now,'dare_dodge',self.generation)
        return True

    def _refund(self,now):
        packets=[]
        for slot,(name,_,duration,_) in CHARGES.items():
            field=name+'_next_charge';end=getattr(self,field)
            if end:setattr(self,field,max(now,end-round(duration*.05)));packets.append(self._cooldown(slot))
        return packets

    def update(self,now):
        packets=[]
        for slot,(name,maximum,duration,_) in CHARGES.items():
            count=getattr(self,name+'_count');end=getattr(self,name+'_next_charge')
            while end and end<=now:
                count=min(maximum,count+1);end=end+self.skill_cooldown(duration) if count<maximum else 0
            if count!=getattr(self,name+'_count'):
                setattr(self,name+'_count',count);setattr(self,name+'_next_charge',end);packets.append(self._cooldown(slot))
        return packets+super().update(now)

    def _spend(self,slot,now):
        name,_,duration,gap=CHARGES[slot]
        setattr(self,name+'_count',getattr(self,name+'_count')-1)
        if not getattr(self,name+'_next_charge'):setattr(self,name+'_next_charge',now+self.skill_cooldown(duration))
        self.cooldowns[slot]=now+gap
        return self._cast_cost(now)+[self._cooldown(slot)]

    def interrupt(self,now,*,stun=False):
        packets=[]
        # Slot iUseInStun preserves the Space preparation through stun.
        if self.ready and (not stun or not self.alive or self.in_stasis() or self.skill_sealed(2,now)):
            self.ready=None;packets.append((1583,struct.pack('<II',self.id,391301)))
        if self.dash:
            packets+=self._remove_hook_line()
            # Keep the original pull segment until the interrupted landing is safe.
            self.position=self.stop_position(now);self.motion=None;self.forced_until=0;self.dash=None
            packets.append(scene(moves=(self._move_event(self.position,0,5),)))
        if not self.alive:self.ledger=None
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        row=table_row('BuffTemplate_table.xml',nBuffId=template);mask=int(row.get('fEffectValB',0))
        if self.dash and row['nEffectType'] in ('30','35','66') and (not mask or mask&2):return self.interrupt(now)
        if self.ready and row['nEffectType'] in ('35','66') and (not mask or mask&4):return self.interrupt(now)
        return []

    def remove_buff(self,template,now,*,expired=False):
        packets=super().remove_buff(template,now,expired=expired)
        if template in (391111,391307):packets.append(self._cooldown(0,True))
        return packets

    def _erase(self,now,predicate):
        keep=[];ids=set()
        for event in self.arena.pending:
            due,_,callback,args=event;actor=callback.__self__
            flight=args[1][0] if callback.__name__=='_event' and args and args[0]=='flight' else None
            if flight and flight.get('kind')=='bullet' and actor.camp!=self.camp:
                pos=flight.get('pos',flight['start']) if flight.get('target') else point_at(flight['start'],flight['end'],max(0,min(1,(now-flight['begin'])/max(1,flight['finish']-flight['begin']))))
                if predicate(pos):ids.add(flight['id']);continue
            keep.append(event)
        self.arena.pending=keep;heapq.heapify(keep)
        return [scene(expired_bullets=tuple(struct.pack('<I',i) for i in sorted(ids)))] if ids else []

    def _hit(self,flight,target,now):
        current=self.alive and flight['source_generation']==self.generation;basic=flight['basic']
        vamp=self.missing_bonus()+(D('.25') if self.has_buff(391306,now) else 0) if basic and current else D(0)
        raw=flight['raw'];cast=flight.get('context',{})
        if basic and target.has_buff(391413,now) and target.buff_sources.get(391413)==self.id:raw*=D('1.25')
        packets,lost=self.damage(raw,now,target=target,basic=basic,lifesteal=vamp,source_generation=flight['source_generation'])
        if self.arena.pk and self.arena.pk['finished']:
            return packets
        if basic:
            if cast.get('empowered'):
                packets+=self._buff(391122,now,target.id)
                if lost and current and not cast.get('rewarded'):
                    cast['rewarded']=True;packets+=self.restore_hp((self.max_hp-self.hp)*D('.1'),now)
        elif flight['template']==391211:
            packets+=self._buff(391212,now,target.id)
            if current and not self.blocked('attack',now) and not self.skill_sealed(1,now):
                start=self.position_at(now);dest=target.position_at(now)
                self._set_motion(start,dest,720,now,kind=3)
                self.dash=dict(end=self.motion[3],generation=self.generation,bullet=flight['id'])
                self._queue(self.motion[3],'dare_arrive',self.dash)
                packets+=self._buff(391214,now)+[scene(moves=(self._move_event(self.motion[1],720,3),))]+self.sync_speed(now)
        else:
            for template in (391412,391413,391414):packets+=self._buff(template,now,target.id)
        return packets

    def _flight(self,flight,now):
        packets=piercing_step(self,flight,now,self._hit,pierce=flight['template']==391411,
                              contact_radius=96 if flight['template']==391411 else 48 if flight['template']==391211 else 36)
        if flight['template']==391211 and not (self.dash and self.dash.get('bullet')==flight['id']):
            ident=struct.pack('<I',flight['id'])
            # A hit can finish without a pull (dead/controlled caster). Blow
            # only stops LinkBulletView; explicitly remove that stopped rope.
            if scene(blown_bullets=(ident,)) in packets:
                packets.append(scene(expired_bullets=(ident,)))
        return packets

    def _remove_hook_line(self):
        # Keep the rope during travel, then release the same client object ID.
        # The dash dictionary is also persisted for Kakashi's borrowed E.
        ident=self.dash.pop('bullet',None) if self.dash else None
        return [scene(expired_bullets=(struct.pack('<I',ident),))] if ident is not None else []

    def _event(self,now,kind,data):
        if kind=='dare_settle':return self._settle(data[0],now)
        if kind=='dare_dodge':
            if not self.alive or self.generation!=data[0]:return []
            return self._buff(391131,now)+self._buff(391143,now)+self._refund(now)+self.restore_hp((self.max_hp-self.hp)*D('.05'),now)+[scene(skills=(self._skill_event(391141,self.position_at(now),self.position_at(now)),))]
        if kind=='dare_arrive':
            if self.dash is not data[0]:return []
            packets=self._remove_hook_line()
            self.position=self.position_at(now);self.motion=None;self.forced_until=0;self.dash=None
            return packets+self.sync_speed(now)
        if kind=='dare_space':
            cast=data[0]
            if self.ready is not cast:return []
            self.ready=None
            if not self.alive:return []
            pos=self.position_at(now);packets=[scene(skills=(self._skill_event(391301,pos,pos),))]
            for target in enemies(self,area=True):
                if math.dist(pos,target.position_at(now))<=192:
                    packets+=self.damage(cast['power']*D('2.06'),now,target=target)[0]+self._buff(391302,now,target.id)
            packets+=self._erase(now,lambda p:math.dist(pos,p)<=240)
            for template in (391303,391305,391306,391307,391308):packets+=self._buff(template,now)
            return packets+[self._cooldown(0,True)]+self.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target,now):
        if self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot==2:
            if not self.alive or self.in_stasis() or self.ready or self.dash or getattr(self,'caocao_hostage',None) or getattr(self,'dracula_ritual',None):return []
        elif self.blocked('attack',now):return []
        if slot and not getattr(self,CHARGES[slot][0]+'_count'):return []
        if slot!=2 and (start==dest or not self._inside(dest)):return []
        power=self.combat_stat('iAttack',now)
        if slot==0:
            empowered=self.has_buff(391111,now);spread=self.has_buff(391307,now)
            template=391111 if empowered else 391311 if spread else 391100
            self.cooldowns[0]=now+self.fire_interval(now);packets=[]
            cast=dict(empowered=empowered,rewarded=False);hits=set()
            angle=math.atan2(dest[1]-start[1],dest[0]-start[0])
            for delta in ((0,15,-15) if spread else (0,)):
                a=angle+math.radians(delta);end=(round(start[0]+480*math.cos(a)),round(start[1]+480*math.sin(a)))
                packets+=self.shoot(template,start,end,now,power*(D('1.5') if empowered else 1),school='physical',basic=True,shared_hits=hits if spread else None,context=cast)
            if empowered:packets+=self.remove_buff(391111,now)
            return packets+[self._cooldown(0)]
        packets=self._spend(slot,now)
        if slot==1:return packets+self._buff(391201,now)+[scene(skills=(self._skill_event(391201,start,dest),))]+self.shoot(391211,start,dest,now,power*D('1.58'),school='physical',through_walls=True)
        if slot==10:
            packets+=self._erase(now,lambda p:in_strip(p,start,dest,480,120))
            return packets+[scene(skills=(self._skill_event(391401,start,dest),))]+self.shoot(391411,start,dest,now,power*D('1.87'),school='physical',through_walls=True)
        self.ready=dict(slot=2,skill=391301,dest=start,power=power,generation=self.generation)
        self._queue(now+100,'dare_space',self.ready)
        return packets+[scene(skills=(self._skill_event(391301,start,start,ready=1),))]+self.sync_speed(now)
