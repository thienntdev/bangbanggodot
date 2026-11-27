"""Approved map170 hazards. Authored routes; no hidden enemy information for AI."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import scene,move_event

BONUSES=(10400231,10400232,10400233)
NOTICE_ID=3996


def notice(text):
    # GateManager -> SystemErrorMessage -> SystemTipTool (battle text).
    raw=text.encode('utf8')
    return 1501,struct.pack('<IiH',0,NOTICE_ID,1)+struct.pack('<H',len(raw))+raw


class Tornado(TankActions):
    def __init__(self,arena,ident,definition):
        info=dict(definition,npc_template=3260216,tornado=True,tank_id=10000019,
                  tank_level=1,acct_id=0,name='Lốc Xoáy',untargetable=True,damage_immune=True)
        super().__init__(arena,ident,info,0,tuple(definition['position']))
        self.stats=dict(self.stats,iHp='1',iSpeed='100',iMp='0')
        self.hp=D(0);self.max_hp=D(1);self.cooldowns={}
        self.spawn_due_at=max(arena.pk['begin']+definition['spawn_ms'],arena.pk['intro_until'])
        self.warned=False;self.next_tick_at=0;self.route_index=1
        points=[tuple(p) for p in definition['route']]
        self.route=points[:1]
        for i,p in enumerate(points[1:-1],1):
            before,after=points[i-1],points[i+1]
            if (p[0]-before[0],p[1]-before[1])!=(after[0]-p[0],after[1]-p[1]):self.route.append(p)
        self.route.append(points[-1])

    def snapshot(self,now):
        return 1556,struct.pack('<IIIhhiBiIiH',self.scene_id,self.id,3260216,
                               *self.position_at(now),-1,0,-1,0,0,0)

    def on_spawn(self,now):return []
    def update(self,now):return []
    def sync_speed(self,now):return []
    def commit_hp(self,hp,now,*,critical=False):return []
    def restore_hp(self,amount,now):return []
    def add_shield(self,*args,**kwargs):return []
    def cc_immune(self,now,*,slow=False):return True
    def reject_buff(self,row,source,now):return not (source is self and int(row['nBuffId'])==10400192)
    def _set_motion(self,start,dest,speed,now,kind=0):return 0
    def move_destination(self,start,dest):return self.position_at(self.clock())

    def advance(self,now):
        packets=[]
        if not self.alive:
            if now<self.spawn_due_at:
                if not self.warned and now>=self.spawn_due_at-3000:
                    self.warned=True
                    packets.append(notice('Lốc xoáy mới xuất hiện sau 3 giây!'))
                return packets
            self.hp=D(1);self.warned=True
            # Native GameInfoTipsFrame replaces its current text; combine the
            # first spawn and rule into one notice so neither overwrites the other.
            text=('Lốc đầu đã xuất hiện: né lốc để tránh hất 1,5s và chậm dần; không gây sát thương.'
                  if self.info['spawn_ms']==0 else 'Lốc xoáy đã xuất hiện — chú ý né tránh!')
            packets+=[self.snapshot(now),notice(text)]
            packets+=self._buff(10400192,now,duration=-1)
        if self.motion and now>=self.motion[3]:
            self.position=self.motion[1];self.motion=None;self.route_index+=1
            if self.route_index>=len(self.route):self.route_index=1
        if not self.motion:
            start=self.position;dest=self.route[self.route_index]
            self.motion=(start,dest,now,now+max(1,round(math.dist(start,dest)*10)))
            self.motion_kind=3
            packets.append(scene(moves=(move_event(dest,100,3,self.id),)))
        if now>=self.next_tick_at:
            self.next_tick_at=now+200
            pos=self.position_at(now)
            for actor in list(self.arena.actors.values()):
                if (actor.info.get('npc_template') or not actor.alive or not actor.is_area_targetable()
                    or actor.has_buff(10400196,now) or math.dist(pos,actor.position_at(now))>120):continue
                if actor.cc_immune(now):continue
                packets+=self._buff(10400191,now,actor.id)
                packets+=self._buff(10400193,now,actor.id)
                packets+=self._buff(10400196,now,actor.id)
        return packets


def install(arena):
    for definition in arena.geometry.data['tornadoes']:
        obj=Tornado(arena,arena.new_id(5),definition)
        arena.actors[obj.id]=obj


def apply_bonuses(actor,now):
    if actor.arena.geometry.id not in (1,4,12,14,17,21,34,35,36,50,70,169,170) or actor.info.get('npc_template') or not actor.alive:return []
    packets=[]
    for buff in BONUSES:
        if not actor.has_buff(buff,now):packets+=actor._buff(buff,now,duration=-1,stacks=1)
    return packets


def tick(arena,now):
    if arena.geometry.id!=170 or arena.pk['finished'] or now<arena.pk['intro_until']:return []
    packets=[]
    arena.pk['quicksand_notice']=True
    for actor in list(arena.actors.values()):
        if actor.info.get('tornado'):packets+=actor.advance(now)
        elif actor.alive and not actor.info.get('npc_template'):
            packets+=apply_bonuses(actor,now)
    return packets


def observe(arena,actor,now):
    """Visible current positions/velocity only, sampled at normal reaction time."""
    pos=actor.position_at(now);seen=[]
    for wind in arena.actors.values():
        if not wind.info.get('tornado') or not wind.alive:continue
        point=wind.position_at(now)
        if math.dist(pos,point)>600 or arena.geometry.wall_contact(pos,point) is not None:continue
        velocity=(0,0)
        if wind.motion:
            start,end,begin,finish=wind.motion
            velocity=tuple((v-u)*1000/max(1,finish-begin) for u,v in zip(start,end))
        seen.append(dict(pos=point,velocity=velocity,observed_at=now))
    return seen


def evade(arena,actor,brain,now):
    pos=actor.position_at(now)
    for wind in brain.get('winds',[]):
        age=(now-wind['observed_at'])/1000
        if not 0<age<1:continue
        center=tuple(p+v*(age+.4) for p,v in zip(wind['pos'],wind['velocity']))
        if math.dist(pos,center)>210:continue
        angle=math.atan2(pos[1]-center[1],pos[0]-center[0])
        for offset in (0,.8,-.8):
            dest=tuple(round(v) for v in (pos[0]+math.cos(angle+offset)*144,pos[1]+math.sin(angle+offset)*144))
            if arena.geometry.walk_end(pos,dest,arena.water_rects(now))==dest:
                brain['goal']=dest;brain['repath_at']=0
                return
