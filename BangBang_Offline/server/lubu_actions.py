"""Lu Bu: per-cast shields, bounded E recast and one reward per basic volley."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene,stop_move
from melee_common import aimed,enemies,in_cone,piercing_step,prepare_displacement

SLOTS={0:349100,1:349201,2:349301,10:349401}


class LuBuActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.mp=int(self.stats['iMp'])
        self.ready=None

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp=self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def _cooldown(self,slot,changed=False):
        now=self.clock()
        second=slot==1 and self.has_buff(349204,now)
        enhanced=slot==0 and self.has_buff(349111,now)
        body=props(349211 if second else 349121 if enhanced else SLOTS[slot],slot,end=0 if second else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.mp=int(self.stats['iMp'])
        self._queue(now+5000,'lubu_regen',self.generation)
        return self._buff(349101,now)+[self._cooldown(0,True),self._cooldown(1,True)]

    def _empower(self,now):
        packets=self.add_shield(349112,self.max_hp*D('.15'),now)
        for t in (349111,349113,349114):
            packets.extend(self._buff(t,now))
        return packets+[self._cooldown(0,True)]

    def remove_buff(self,template,now,*,expired=False):
        packets=super().remove_buff(template,now,expired=expired)
        if template==349111:
            packets.extend(self.remove_buff(349113,now)+self.remove_buff(349114,now))
            packets.append(self._cooldown(0,True))
        if template==349204:
            packets.append(self._cooldown(1,True))
        return packets

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def _stop_packets(self,packets,position):
        # Ready/disappear must reach SelfTank before stopMoveAt retries held
        # input; stop the old tween before publishing zero movement speed.
        attrs=[p for p in packets if p[0]==1560]
        stop=stop_move(self.scene_id,self.id,position)
        return [p for p in packets if p[0]!=1560 and p!=stop]+[stop]+attrs

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def cc_immune(self,now,*,slow=False):
        return bool(self.ready and self.ready['slot']==2) or super().cc_immune(now,slow=slow)

    def reject_buff(self,row,source,now):
        return bool(self.ready and self.ready['slot']==2 and source.camp!=self.camp)

    def interrupt(self,now):
        if not self.ready:
            return []
        cast=self.ready;self.ready=None
        self.info.pop('untargetable',None);self.info.pop('damage_immune',None)
        packets=self.remove_object(cast['object']) if 'object' in cast else []
        return packets+[(1583,struct.pack('<II',self.id,cast['skill']))]+self.sync_speed(now)

    def update(self,now):
        packets=self.interrupt(now) if self.ready and self.ready['slot']!=2 and self.skill_sealed(1,now) else []
        return packets+super().update(now)

    def _r_hit(self,flight,target,now):
        packets=self.damage(flight['raw'],now,target=target)[0]+self._buff(349402,now,target.id)
        return packets+self._resource(20) if self.alive and self.generation==flight['source_generation'] else packets

    def _flight(self,flight,now):
        if flight['template']==349401:
            return piercing_step(self,flight,now,self._r_hit)
        if flight['template'] not in (349100,349121):
            return super()._flight(flight,now)
        start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        contacts=[(hit,a.id,a) for a in enemies(self)
                  if (hit:=actor_contact(start,end,a,flight['previous'],now)) is not None]
        hit,_,target=min(contacts,key=lambda r:r[:2]) if contacts else (None,0,None)
        wall=self.arena.geometry.wall_contact(start,end)
        packets=[];ident=struct.pack('<I',flight['id'])
        if hit is not None and (wall is None or hit<wall):
            if self.projectile_blocked(target,now):
                return [scene(expired_bullets=(ident,))]
            center=point_at(start,end,hit);landed=False
            for victim in enemies(self,area=True):
                if victim is target or math.dist(center,victim.position_at(now))<=(120 if flight['template']==349121 else 96):
                    result,lost=self.damage(flight['raw'],now,target=victim,basic=True)
                    packets.extend(result);landed=landed or lost
            if self.alive and self.generation==flight['source_generation']:
                packets.extend(self._resource(15 if flight['template']==349121 else 5))
                if landed and flight['template']==349121:
                    for slot in (1,2,10):
                        self.cooldowns[slot]=max(now,self.cooldowns[slot]-1000)
                        packets.append(self._cooldown(slot))
            return packets+[scene(blown_bullets=(ident,))]
        if wall is not None or now>=flight['finish']:
            return [scene(**{'blown_bullets' if wall is not None else 'expired_bullets':(ident,)})]
        flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
        return []

    def _event(self,now,kind,data):
        if kind=='lubu_regen':
            if not self.alive or self.generation!=data[0]:
                return []
            self._queue(now+5000,kind,*data)
            return self._resource(10)
        if kind=='lubu_arrive':
            cast,=data
            if self.ready is not cast or not self.alive:
                return []
            self.ready=None
            self.info.pop('untargetable',None);self.info.pop('damage_immune',None)
            self.position,self.motion=self.blink_destination(cast['start'],cast['dest']),None
            packets=[stop_move(self.scene_id,self.id,self.position)]
            if cast['slot']==1:
                packets.append(scene(skills=(self._skill_event(349201,cast['start'],self.position),)))
            else:
                # Landing is ITEM_REMOVE: Flash plays SceneItem.szRemoveSwf/Mp3.
                # Interrupt/cleanup remains expiry and must not fake an impact.
                packets.extend(self.remove_object(cast['object'],destroyed=True)+self.remove_buff(349302,now))
            landed=False
            for target in enemies(self,area=True):
                if math.dist(self.position,target.position_at(now))<=(168 if cast['slot']==1 else 192):
                    result,lost=self.damage(cast['power']*(D('1.55') if cast['slot']==1 else D('3.88')),now,target=target)
                    packets.extend(result);landed=landed or lost
                    for template in ((349205,349203) if cast['slot']==1 else (349322,349323)):
                        packets.extend(self._buff(template,now,target.id))
            if cast['slot']==1 and landed:
                packets.extend(self._buff(349204,now))
                packets.append(self._cooldown(1,True))
            return packets+self.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        second=slot==1 and self.has_buff(349204,now)
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or not second and self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or start==dest:
            return []
        cost=0 if second else {0:0,1:30,2:50,10:20}[slot]
        if self.mp<cost:
            return []
        power=self.combat_stat('iAttack',now)
        if not second:
            self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:6000}[slot], slot)
        packets=self._resource(-cost)+[self._cooldown(slot)]
        if slot==0:
            enhanced=self.has_buff(349111,now)
            if enhanced:
                packets.extend(self.remove_buff(349111,now))
            return packets+self.shoot(349121 if enhanced else 349100,start,dest,now,power*(2 if enhanced else 1),school='physical',basic=True)
        packets.extend(self._empower(now))
        if second:
            packets.extend(self.remove_buff(349204,now))
            packets.append(scene(skills=(self._skill_event(349211,start,dest),)))
            for target in enemies(self,area=True):
                if in_cone(target.position_at(now),start,dest,168,180):
                    packets.extend(self.damage(power*D('1.58'),now,target=target)[0])
                    packets.extend(self.restore_hp((self.max_hp-self.hp)*D('.15'),now))
            return packets
        if slot==10:
            return packets+self.shoot(349401,start,dest,now,power*D('1.84'),school='physical',through_walls=True)
        origin,stopped=prepare_displacement(self,now,interrupt=False) if slot==1 else (start,[])
        body=origin if stopped else start
        self.position,self.motion=body,None
        dest=self.blink_destination(start,aimed(start,dest,240 if slot==1 else 720))
        self.ready=dict(slot=slot,skill=SLOTS[slot],start=start,dest=dest,power=power,generation=self.generation)
        if slot==2:
            self.info.update(untargetable=True,damage_immune=True)
            ident,packet=self.add_object(349311,dest);self.ready['object']=ident;packets.append(packet)
            packets.extend(self._buff(349302,now))
        self._queue(now+(50 if slot==1 else 1000),'lubu_arrive',self.ready)
        return self._stop_packets(packets+[scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),))]+self.sync_speed(now),body)
