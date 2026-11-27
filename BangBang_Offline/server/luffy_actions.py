"""Luffy has no native R: one collision per push and five Space punches."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene,stop_move
from melee_common import aimed,enemies,in_cone,in_strip,prepare_displacement,accept_water_reclip

SLOTS={0:320100,1:320301,2:320201}


class LuffyActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.cooldowns.pop(10)
        self.channel=None
        self.passive_ready_at=0

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_spawn(self,now):
        return self._buff(320102,now)

    def commit_hp(self,hp,now,*,critical=False):
        trigger=self.hp>0 and hp<self.hp and hp<self.max_hp*D('.4') and now>=self.passive_ready_at
        if trigger:
            self.passive_ready_at=now+30000
            return super().commit_hp(max(D(1),hp),now,critical=critical)+self._buff(320101,now)
        return super().commit_hp(hp,now,critical=critical)

    def _speed(self,now):
        return 0 if self.channel else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.channel) or super().blocked(action,now)

    def interrupt(self,now):
        if not self.channel:
            return []
        self.channel=None
        return [(1583,struct.pack('<II',self.id,320201))]+self.sync_speed(now)

    def update(self,now):
        packets=self.interrupt(now) if self.channel and self.skill_sealed(2,now) else []
        return packets+super().update(now)

    def _push(self,target,dest,now,pairs):
        if not target.alive or target.cc_immune(now):
            return []
        current=target.position_at(now)
        # Keep the old dash origin until its interrupted body has a legal stop.
        start=target.stop_position(now)
        finish=aimed(start,(start[0]+dest[0],start[1]+dest[1]),240,fixed=True)
        wall=self.arena.geometry.wall_contact(start,finish,36)
        if wall is not None:
            finish=point_at(start,finish,max(0,wall-.00001))
        requested=finish
        if start!=current:
            target.position,target.motion=start,None
        packets=target.interrupt(now)
        if start!=current:
            packets.append(stop_move(target.scene_id,target.id,start))
        duration=target._set_motion(start,finish,480,now,kind=1)
        finish=target.motion[1]
        target.forced_until=now+duration
        cast=dict(target=target.id,target_generation=target.generation,generation=self.generation,
                  start=start,end=now+duration,previous=now,motion=target.motion,pairs=pairs,
                  wall=wall is not None or math.dist(finish,requested)>.1)
        self._queue(now+min(20,duration),'luffy_push',cast)
        return packets+self._buff(320311,now,target.id,duration=duration)+self._buff(320321,now,target.id,duration=duration)+[scene(moves=(self._move_event(finish,480,1,target.id),))]

    def _event(self,now,kind,data):
        if kind=='luffy_punch':
            cast,index=data
            if self.channel is not cast or not self.alive:
                return []
            packets=[scene(skills=(self._skill_event(320201,cast['start'],cast['dest']),))]
            for target in enemies(self,area=True):
                if in_cone(target.position_at(now),cast['start'],cast['dest'],360,60):
                    packets.extend(self.damage(cast['power']*D('.91'),now,target=target)[0])
                    if index<5:
                        packets.extend(self._buff(320211,now,target.id,duration=200))
            if index==5:
                self.channel=None
                packets.extend(self.sync_speed(now))
            return packets
        if kind=='luffy_push':
            cast,=data
            target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation']:
                return []
            if target.motion!=cast['motion']:
                # A water wall may truncate an in-progress push. Use its new
                # endpoint and stop time, never continue the old collision path.
                if (target.motion and target.motion_kind==1 and target.motion[3]<=cast['end']
                        and target.has_buff(320311,now) and accept_water_reclip(target,cast)):
                    cast['motion']=target.motion
                    cast['previous']=max(cast['previous'],target.motion[2])
                    cast['end']=target.motion[3];cast['wall']=True
                else:
                    return target.remove_buff(320311,now)+target.remove_buff(320321,now)
            start,end=target.position_at(cast['previous']),target.position_at(now)
            contacts=[]
            for other in self.arena.actors.values():
                pair=tuple(sorted(((target.id,target.generation),(other.id,other.generation))))
                if other is target or not other.alive or other.is_untargetable() or pair in cast['pairs']:
                    continue
                hit=actor_contact(start,end,other,cast['previous'],now,radius=72)
                if hit is not None:
                    contacts.append((hit,other.id,other,pair))
            if contacts or now>=cast['end']:
                packets=[]
                other=None
                if contacts:
                    hit,_,other,pair=min(contacts,key=lambda v:v[:2]);cast['pairs'].add(pair)
                    target.position=target.move_destination(start,point_at(start,end,hit))
                else:
                    target.position=end
                target.motion=None;target.forced_until=now
                packets.extend(target.remove_buff(320311,now)+target.remove_buff(320321,now))
                packets.append(scene(moves=(self._move_event(target.position,0,5,target.id),)))
                if contacts or cast['wall']:
                    amount=target.max_hp*D('.05')
                    victims=[target]+([other] if other and other.camp!=self.camp else [])
                    for victim in victims:
                        packets.extend(self._buff(320411,now,victim.id))
                        packets.extend(self.damage(amount,now,target=victim)[0])
                return packets
            cast['previous']=now
            self._queue(min(now+20,cast['end']),kind,cast)
            return []
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if start==dest or not self._inside(dest):
            return []
        power=self.combat_stat('iAttack',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000}[slot], slot)
        packets=[self._cooldown(slot)]
        if slot==0:
            return packets+self.shoot(320100,start,dest,now,power,school='physical',basic=True)
        if slot==1:
            packets.append(scene(skills=(self._skill_event(320301,start,dest),)))
            pairs=set()
            for target in enemies(self,area=True):
                if in_strip(target.position_at(now),start,dest,360,72):
                    packets.extend(self.damage(power*D('1.24'),now,target=target)[0])
                    if self.arena.pk and self.arena.pk['finished']:
                        return packets
                    packets.extend(self._push(target,(dest[0]-start[0],dest[1]-start[1]),now,pairs))
            return packets
        body,handoff=prepare_displacement(self,now,interrupt=False)
        if not handoff: body=start
        self.position,self.motion=body,None
        self.channel=dict(start=start,dest=dest,power=power,generation=self.generation,end=now+1000)
        for target in enemies(self,area=True):
            if in_cone(target.position_at(now),start,dest,360,60):
                packets.extend(self._buff(320211,now,target.id,duration=1000))
        for index in range(1,6):
            self._queue(now+index*200,'luffy_punch',self.channel,index)
        return packets+self.sync_speed(now)+handoff
