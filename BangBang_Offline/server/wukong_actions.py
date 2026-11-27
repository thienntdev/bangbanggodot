"""Wukong: one empowered sweep per cast and one reactive shield per E."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import props,scene,stop_move
from melee_common import aimed,enemies,in_cone,prepare_displacement

SLOTS={0:310100,1:310201,2:310301,10:310401}


class WukongActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.vanish=None

    def _cooldown(self,slot,changed=False):
        skill=310121 if slot==0 and self.has_buff(310111,self.clock()) else SLOTS[slot]
        body=props(skill,slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        return self._buff(310101,now)+[self._cooldown(0,True)]

    def _empower(self,now):
        return self._buff(310111,now)+self._buff(310112,now)+[self._cooldown(0,True)]

    def _stop_packets(self,packets,position):
        # S1564 MOVE_SERVER queues behind a running tween. S1554 stops it now.
        # Install ready/disappear first (its handler retries held movement),
        # then stop, then set selfSpeed=0 so the old tween cannot chain at zero.
        attrs=[p for p in packets if p[0]==1560]
        stop=stop_move(self.scene_id,self.id,position)
        return [p for p in packets if p[0]!=1560 and p!=stop]+[stop]+attrs

    def remove_buff(self,template,now,*,expired=False):
        packets=super().remove_buff(template,now,expired=expired)
        if template==310111:
            packets.extend(self.remove_buff(310112,now))
            packets.append(self._cooldown(0,True))
        return packets

    def _speed(self,now):
        return 0 if self.ready or self.vanish else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.vanish) or super().blocked(action,now)

    def reject_buff(self,row,source,now):
        return bool(self.vanish and source.camp!=self.camp)

    def cc_immune(self,now,*,slow=False):
        return bool(self.vanish) or super().cc_immune(now,slow=slow)

    def on_skill_damage(self,source,hit,now):
        if not self.alive or hit.potential_damage<=0 or not self.has_buff(310204,now):
            return []
        packets=self.remove_buff(310204,now)
        for slot in (1,10):
            self.cooldowns[slot]=now+round(max(0,self.cooldowns[slot]-now)*.75)
            packets.append(self._cooldown(slot))
        return packets+self.add_shield(310223,self.max_hp*D('.25'),now)

    def interrupt(self,now):
        packets=[]
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,self.ready['skill'])))
            self.ready=None
        if not self.alive and self.vanish:
            for ident in self.vanish['objects']:
                packets.extend(self.remove_object(ident))
            self.vanish=None
            self.info.pop('untargetable',None);self.info.pop('damage_immune',None)
        return packets+self.sync_speed(now)

    def update(self,now):
        packets=self.interrupt(now) if self.ready and self.skill_sealed(self.ready['slot'],now) else []
        return packets+super().update(now)

    def _event(self,now,kind,data):
        if kind=='wukong_hit':
            cast,=data
            if self.ready is not cast or not self.alive:
                return []
            self.ready=None
            start=self.position_at(now)
            packets=[scene(skills=(self._skill_event(cast['skill'],start,cast['dest']),))]
            for target in enemies(self,area=True):
                inside=(in_cone(target.position_at(now),start,cast['dest'],192,180) if cast['slot']==0
                        else math.dist(start,target.position_at(now))<=216)
                if inside:
                    packets.extend(self.damage(cast['power']*(D(2) if cast['slot']==0 else D('1.77')),now,target=target,
                                              basic=cast['slot']==0,lifesteal=D('.25') if cast['slot']==0 else 0)[0])
                    packets.extend(self._buff(310122 if cast['slot']==0 else 310402,now,target.id))
                    if cast['slot']==0:
                        packets.extend(self._buff(310123,now,target.id))
            if cast['slot']==10:
                packets.extend(self._empower(now))
            return packets+self.sync_speed(now)
        if kind=='wukong_land':
            cast,=data
            if self.vanish is not cast or not self.alive:
                return []
            self.vanish=None
            self.info.pop('untargetable',None);self.info.pop('damage_immune',None)
            packets=self.remove_buff(310302,now)
            for target in enemies(self,area=True):
                if math.dist(cast['dest'],target.position_at(now))<=192:
                    packets.extend(self.damage(cast['power']*D('4.87'),now,target=target)[0])
                    packets.extend(self._buff(310312,now,target.id))
            return packets+self._empower(now)+self.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot in (0,1,2) and (start==dest or not self._inside(dest)):
            return []
        cancelled_e=self.has_buff(310211,now) and self.motion is not None
        packets=[]
        if cancelled_e:
            # A new accepted action cuts E short; never land the 72px body
            # inside an inner wall just because the dash can cross that wall.
            start=self.move_destination(self.motion[0],self.position_at(now))
            self.position,self.motion,self.forced_until=start,None,0
            packets.extend(self.remove_buff(310211,now))
        power=self.combat_stat('iAttack',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:20000,10:8000}[slot], slot)
        packets.append(self._cooldown(slot))
        if slot==0 and not self.has_buff(310111,now):
            if cancelled_e:packets=self._stop_packets(packets,start)
            return packets+self.shoot(310100,start,dest,now,power,school='physical',basic=True)
        if slot in (0,10):
            skill=310121 if slot==0 else 310401
            if slot==0:
                packets.extend(self.remove_buff(310111,now))
            body,stopped=prepare_displacement(self,now,interrupt=False)
            body=body if stopped else start
            self.position,self.motion=body,None
            self.ready=dict(slot=slot,skill=skill,dest=dest,power=power,generation=self.generation)
            self._queue(now+(10 if slot==0 else 100),'wukong_hit',self.ready)
            return self._stop_packets(packets+[scene(skills=(self._skill_event(skill,start,dest,ready=1),))]+self.sync_speed(now),body)
        if slot==1:
            intended=aimed(start,dest,384,fixed=True)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            body=body if stopped else start
            duration=self._set_motion(body,intended,960,now,kind=3)
            self.forced_until=now+duration
            movement=scene(skills=(self._skill_event(310201,start,self.motion[1]),),moves=(self._move_event(self.motion[1],960,3),))
            if not stopped:packets.append(movement)
            for template in (310202,310203,310204,310211):
                packets.extend(self._buff(template,now,duration=duration if template==310211 else None))
            packets.extend(self._empower(now))
            return packets+stopped+[movement] if stopped else packets
        dest=self.blink_destination(start,aimed(start,dest,264))
        self.position,self.motion=dest,None
        self.vanish=dict(slot=2,dest=dest,power=power,generation=self.generation,objects=[])
        self.info.update(untargetable=True,damage_immune=True)
        for template,pos,life in ((310302,start,360),(310304,dest,700),(310305,dest,1350)):
            ident,packet=self.add_object(template,pos);packets.append(packet);self.vanish['objects'].append(ident)
            self._queue(now+life,'object_expire',ident)
        self._queue(now+700,'wukong_land',self.vanish)
        return self._stop_packets(packets+self._buff(310302,now)+self.sync_speed(now),dest)
