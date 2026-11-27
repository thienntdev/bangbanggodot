"""Fixed-route escorts: map20 cows and map36 mine carts share approved rules."""
from battle_participants import human
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_geometry import point_at
from combat_protocol import scene,move_event,stop_move


class CowObject(TankActions):
    def __init__(self,arena,ident,definition):
        info=dict(definition,npc_template=definition['template'],cow_object=True,
                  tank_id=10000019,tank_level=1,acct_id=0,name=definition.get('name','Bò Sữa'),in_room=True,
                  untargetable=True,damage_immune=True)
        super().__init__(arena,ident,info,definition['camp'],tuple(definition['position']))
        self.stats=dict(self.stats,iHp='1',iSpeed='0',iMp='0')
        self.hp=self.max_hp=D(1)
        self.cooldowns={}
        self.herders=[]
        self.route_index=1
        self.cow_speed=0
        self.respawn_at=0
        # Keep only corners. One linear tween per straight section avoids a
        # packet/tween reset for every 24-unit source point.
        points=[tuple(p) for p in definition.get('route',[])]
        self.route=points[:1]
        for i,p in enumerate(points[1:-1],1):
            before=points[i-1];after=points[i+1]
            if (p[0]-before[0],p[1]-before[1])!=(after[0]-p[0],after[1]-p[1]):
                self.route.append(p)
        if points:self.route.append(points[-1])

    def snapshot(self,now):
        # Native no-HP AI object sentinel, matching fHpCoef=-1 for cow/barn.
        return 1556,struct.pack('<IIIhhiBiIiH',self.scene_id,self.id,self.info['npc_template'],
            *self.position_at(now),-1,self.camp,-1,0,0,0)

    def on_spawn(self,now):return [self.snapshot(now)]
    def update(self,now):return []
    def sync_speed(self,now):return []
    def commit_hp(self,hp,now,*,critical=False):return []
    def restore_hp(self,amount,now):return []
    def add_shield(self,*args,**kwargs):return []
    def cc_immune(self,now,*,slow=False):return True
    def reject_buff(self,row,source,now):return not (source is self and int(row['nBuffId'])==50315)
    def _set_motion(self,start,dest,speed,now,kind=0):return 0
    def move_destination(self,start,dest):return self.position_at(self.clock())

    def sync_herders(self,herders,now):
        packets=[];ids={a.id for a in herders}
        for ident in set(self.herders)-ids:
            actor=self.arena.actors[ident]
            if actor.buff_sources.get(50313)==self.id:packets+=actor.remove_buff(50313,now)
        for actor in herders:
            if not actor.has_buff(50313,now):packets+=self._buff(50313,now,actor.id,duration=-1)
        self.herders=sorted(ids)
        return packets

    def stop(self,now):
        packets=[]
        if self.motion:
            self.position=self.position_at(now);self.motion=None
            packets.append(stop_move(self.scene_id,self.id,self.position))
        self.cow_speed=0
        return packets+self.remove_buff(50315,now)

    def advance(self,now):
        if not self.route:return []  # Barns are stationary, immortal scenery.
        if not self.alive:
            if now<self.respawn_at:return []
            self.hp=D(1);self.generation+=1;self.respawn_at=0
            self.position=self.spawn;self.route_index=1
            return [self.snapshot(now)]
        packets=[]
        if self.motion and now>=self.motion[3]:
            self.position=self.motion[1];self.motion=None;self.route_index+=1
            if self.route_index==len(self.route):
                packets+=self.sync_herders([],now)+self.remove_buff(50315,now)
                self.hp=D(0);self.cow_speed=0;self.respawn_at=now+3000
                packets.append(scene(removed=(struct.pack('<I',self.id),)))
                from pk_rules import score_packets,finish
                camp=self.info['barn_camp']
                self.arena.pk['scores'][camp]+=1
                packets+=score_packets(self.arena)
                if self.arena.pk['scores'][camp]>=25:packets+=finish(self.arena,now)
                return packets
        pos=self.position_at(now)
        herders=[a for a in self.arena.actors.values() if eligible(a,now)
                 and a.camp!=self.camp and math.dist(pos,a.position_at(now))<=240]
        packets+=self.sync_herders(herders,now)
        speed=100+12*(len(herders)-1) if herders else 0
        if not speed:return packets+self.stop(now)
        if self.motion and speed==self.cow_speed:return packets
        if self.motion:
            # Stop the old tween before applying the new speed, including
            # partial segments saved/reloaded while an escort leaves range.
            packets+=self.stop(now)
        start=self.position_at(now);dest=self.route[self.route_index]
        self.cow_speed=speed
        self.motion=(start,dest,now,now+max(1,round(math.dist(start,dest)*1000/speed)))
        self.motion_kind=3
        if not self.has_buff(50315,now):packets+=self._buff(50315,now,duration=-1)
        packets.append(scene(moves=(move_event(dest,speed,3,self.id),)))
        return packets


def eligible(actor,now):
    return (actor.alive and not actor.info.get('npc_template') and not actor.is_untargetable()
            and 26 not in actor.buff_types(now))


def install(arena):
    for definition in (*arena.geometry.data['barns'],*arena.geometry.data['cows']):
        obj=CowObject(arena,arena.new_id(5),definition)
        arena.actors[obj.id]=obj


def tick(arena,now):
    packets=[]
    for cow in arena.actors.values():
        if cow.info.get('cow_object'):
            packets+=cow.advance(now)
            if arena.pk['finished']:break
    return packets


def goal(arena,actor,seen,now):
    """Public objectives + allied positions; never unseen enemy coordinates."""
    cows=[a for a in arena.actors.values() if a.info.get('cow_object') and a.route]
    offensive=next(c for c in cows if c.camp!=actor.camp)
    defensive=next(c for c in cows if c.camp==actor.camp)
    friends=[a for a in arena.actors.values() if a.camp==actor.camp and eligible(a,now)
             and float(a.hp/a.max_hp)>=.4]
    target=offensive.position_at(now) if offensive.alive else offensive.spawn
    # A human already escorting occupies a slot; don't count an idle human at
    # the other end of the map and leave the cow without a bot.
    volunteers=[a for a in friends if not human(a) or math.dist(a.position_at(now),target)<=240]
    escorts=sorted(volunteers,key=lambda a:(math.dist(a.position_at(now),target)-(180 if a.has_buff(50313,now) else 0),a.id))[:2]
    if actor in escorts:
        if offensive.alive:
            dest=offensive.route[min(offensive.route_index,len(offensive.route)-1)]
            distance=max(1,math.dist(target,dest))
            ahead=point_at(target,dest,min(96/distance,1))
            dx,dy=dest[0]-target[0],dest[1]-target[1]
            side=-1 if escorts.index(actor)==0 else 1
            target=(ahead[0]-dy/distance*72*side,ahead[1]+dx/distance*72*side)
        return 'escort',arena.geometry.clamp_tank_position(target)
    defend=defensive.position_at(now)
    if defensive.alive and (defensive.motion or any(math.dist(s['pos'],defend)<480 for s in seen)):
        return 'defend',arena.geometry.clamp_tank_position(defend)
    return None
