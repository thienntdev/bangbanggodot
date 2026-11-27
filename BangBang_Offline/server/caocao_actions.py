"""Cao Cao: one aura clock, explicit hostage ownership and one-way damage split."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import point_at
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,prepare_displacement

SLOTS={0:366100,1:366201,2:366301,10:366401}


class CaoCaoActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.dash=self.aura=self.hostage=None
        self.passive_damage=D(0);self.passive_ready_at=0

    def _cooldown(self,slot,changed=False):
        body=props(SLOTS[slot],slot,-1,self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=self.dash=self.aura=self.hostage=None
        self.passive_damage=D(0);self.passive_ready_at=0
        return self._buff(366101,now)+self._buff(366102,now)

    def blocked(self,action,now):return bool(self.ready or self.dash or self.hostage) or super().blocked(action,now)
    def _speed(self,now):return 0 if self.ready or self.dash or self.hostage else super()._speed(now)

    def _start_aura(self,now):
        if not self.alive:return []
        # Refreshing extends the existing clock, including a kill inside a tick.
        if self.aura and self.aura['end']>=now:self.aura['end']=now+5000
        else:
            self.aura=dict(end=now+5000,generation=self.generation)
            self._queue(now+500,'cao_aura',self.aura)
        packets=[]
        for template in (366401,366402,366403,366404):packets.extend(self._buff(template,now))
        return packets

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        if not self.alive or hit.hp_loss<=0:return []
        packets=[]
        if now>=self.passive_ready_at:
            self.passive_damage+=hit.hp_loss
            if self.passive_damage>=self.max_hp*D('.3'):
                self.passive_damage-=self.max_hp*D('.3');self.passive_ready_at=now+15000
                packets+=self._buff(366103,now)+self._buff(366104,now)
        return packets

    def on_skill_damage(self,source,hit,now):
        return self.restore_hp(self.max_hp*D('.03'),now) if self.alive and hit.hp_loss>0 and self.has_buff(366103,now) else []

    def on_target_death(self,target,now):
        packets=[]
        if self.hostage and self.hostage['target']==target.id:packets+=self._release(now)
        if self.dash and self.dash['target']==target.id:packets+=self.interrupt(now)
        if (self.alive and target.camp!=self.camp and not target.info.get('npc_template')
                and getattr(target,'damage_credit',None)==(self.id,self.generation)):
            packets+=self._start_aura(now)
        return packets

    def _release(self,now):
        cast=self.hostage
        if not cast:return []
        self.hostage=None;packets=[]
        for ident,templates in ((self.id,(366806,366807,366808,366809,366810,366811)),
                                (cast['target'],(366301,366601,366801,366802,366803,366804,366805))):
            actor=self.arena.actors.get(ident)
            if not actor:continue
            if getattr(actor,'caocao_hostage',None) is cast:actor.caocao_hostage=None
            for template in templates:packets+=actor.remove_buff(template,now)
            if actor.alive:packets+=self._buff(366901,now,actor.id)
            packets+=actor.sync_speed(now)
        return packets+self.sync_speed(now)

    def redirect_damage(self,amount,school,now):
        cast=self.hostage;target=self.arena.actors.get(cast['target']) if cast else None
        if (not target or not target.alive or cast['end']<=now
                or target.generation!=cast['target_generation']):return amount,self._release(now)
        half=amount/D(2)
        packets,_=self.damage(half,now,target=target,school=school,reflected=True,resolved_damage=half)
        return amount-half,packets

    def interrupt(self,now):
        packets=[]
        if self.ready:packets.append((1583,struct.pack('<II',self.id,366301)));self.ready=None
        if self.dash:
            self.position=self.stop_position(now);self.motion=None;self.forced_until=0;self.dash=None
            packets+=self.remove_buff(366302,now)
            packets.append(scene(moves=(self._move_event(self.position,0,5),)))
        if not self.alive:self.aura=None;packets+=self._release(now)
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        row=table_row('BuffTemplate_table.xml',nBuffId=template)
        if (self.ready or self.dash) and row['nEffectType'] in ('30','35','66') and (not int(row.get('fEffectValB',0)) or int(row.get('fEffectValB',0))&4):return self.interrupt(now)
        return []

    def _hold(self,cast,target,now):
        # Contact may occur before either moving body has cleared a wall.
        self.dash=None;self.position=self.stop_position(now);self.motion=None;self.forced_until=0
        packets=self.remove_buff(366302,now)
        if not target.alive or target.is_untargetable() or target.generation!=cast['target_generation']:return packets+self.sync_speed(now)
        # Only the original CC-immunity buff type is removed; forms stay intact.
        for owner,template in list(target.active_buffs):
            if owner==target.id and table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']=='54':packets+=target.remove_buff(template,now)
        target.position=target.stop_position(now);target.motion=None;target.forced_until=0
        packets+=target.interrupt(now)
        for template in (366801,366802,366803,366804,366805):packets+=self._buff(template,now,target.id)
        for template in (366806,366807,366808,366809,366810,366811):packets+=self._buff(template,now)
        cast.update(end=now+3000,owner=self.id)
        self.hostage=target.caocao_hostage=cast
        packets+=[scene(moves=(self._move_event(self.position,0,5),target._move_event(target.position,0,5)))]
        self._queue(now+250,'cao_hostage',cast,1)
        return packets+self.sync_speed(now)+target.sync_speed(now)

    def _flight(self,flight,now):
        if flight['template']!=366201:return super()._flight(flight,now)
        if now<flight['finish']:
            self._queue(min(now+20,flight['finish']),'flight',flight);flight['previous']=now;return []
        packets=[scene(blown_bullets=(struct.pack('<I',flight['id']),))];pos=flight['end']
        for target in enemies(self,area=True):
            old=target.position_at(now)
            if math.dist(pos,old)>144:continue
            packets+=self.damage(flight['raw'],now,target=target,source_generation=flight['source_generation'])[0]
            if self.arena.pk and self.arena.pk['finished']:
                return packets
            packets+=self._buff(366202,now,target.id)
            if target.alive and not target.cc_immune(now):
                old,stopped=prepare_displacement(target,now,interrupt=False)
                packets+=stopped
                dest=aimed(old,pos,72);target._set_motion(old,dest,300,now,kind=1);target.forced_until=target.motion[3]
                packets.append(scene(moves=(target._move_event(target.motion[1],300,1),)))
        return packets

    def _event(self,now,kind,data):
        if kind=='cao_aura':
            cast=data[0]
            if self.aura is not cast or not self.alive or cast['generation']!=self.generation:return []
            if now>cast['end']:self.aura=None;return []
            packets=[];power=self.combat_stat('iAttack',now)
            for target in enemies(self,area=True):
                if math.dist(self.position_at(now),target.position_at(now))<=240:
                    more,lost=self.damage(power*D('.5'),now,target=target);packets+=more
                    if lost and not target.info.get('npc_template'):packets+=self.restore_hp(self.max_hp*D('.02'),now)
            if now<cast['end']:self._queue(now+500,kind,cast)
            else:self.aura=None
            return packets
        if kind=='cao_ready':
            cast=data[0]
            if self.ready is not cast:return []
            self.ready=None;target=self.arena.actors.get(cast['target'])
            if not self.alive or not target or not target.alive or target.is_untargetable() or target.generation!=cast['target_generation']:return self.sync_speed(now)
            start=self.position_at(now);dest=target.position_at(now)
            self._set_motion(start,dest,960,now,kind=3);cast['end']=self.motion[3];self.dash=cast
            self._queue(min(now+20,cast['end']),'cao_dash',cast)
            return self._start_aura(now)+self._buff(366302,now)+[scene(moves=(self._move_event(self.motion[1],960,3),),skills=(self._skill_event(366301,start,dest,target.id),))]+self.sync_speed(now)
        if kind=='cao_dash':
            cast=data[0];target=self.arena.actors.get(cast['target'])
            if self.dash is not cast:return []
            if not self.alive or not target or not target.alive or target.generation!=cast['target_generation']:return self.interrupt(now)
            if math.dist(self.position_at(now),target.position_at(now))<=72:return self._hold(cast,target,now)
            if not self.motion or now>=min(cast['end'],self.motion[3]):return self.interrupt(now)
            self._queue(min(now+20,cast['end']),kind,cast);return []
        if kind=='cao_hostage':
            cast,tick=data
            if self.hostage is not cast:return []
            target=self.arena.actors.get(cast['target'])
            if not self.alive or not target or not target.alive or target.generation!=cast['target_generation']:return self._release(now)
            packets=self.damage(cast['power']*D('.2'),now,target=target,periodic=True)[0]
            if self.hostage is cast:
                if tick<12:self._queue(now+250,kind,cast,tick+1)
                else:packets+=self._release(now)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target,now):
        if self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        enemy=self.arena.actors.get(target)
        if slot==2 and (not enemy or not enemy.alive or enemy.camp==self.camp or enemy.info.get('npc_template')
                       or enemy.is_untargetable() or enemy.has_buff(366806,now) or getattr(enemy,'caocao_hostage',None)
                       or math.dist(start,enemy.position_at(now))>264):return []
        if slot==2:
            from bot_ai import team_visible
            if not team_visible(self.arena,self,enemy,now):return []
        if slot in (0,1) and (start==dest or not self._inside(dest)):return []
        if slot==0:
            self.cooldowns[0]=now+self.fire_interval(now)
            return self.shoot(366100,start,dest,now,self.combat_stat('iAttack',now),school='physical',basic=True)+[self._cooldown(0)]
        self.cooldowns[slot]=now+self.skill_cooldown({1:6000,2:30000,10:10000}[slot], slot)
        if slot==1:return self.shoot(366201,start,aimed(start,dest,480),now,self.combat_stat('iAttack',now)*D('1.83'),school='physical',through_walls=True,fixed_destination=True)+[self._cooldown(1)]
        if slot==10:return self._start_aura(now)+[scene(skills=(self._skill_event(366401,start,start),)),self._cooldown(10)]
        self.ready=dict(slot=2,target=target,target_generation=enemy.generation,generation=self.generation,power=self.combat_stat('iAttack',now),dest=enemy.position_at(now))
        self._queue(now+10,'cao_ready',self.ready)
        return self._buff(366301,now,target)+[scene(skills=(self._skill_event(366301,start,self.ready['dest'],target,ready=1),)),self._cooldown(2)]+self.sync_speed(now)
