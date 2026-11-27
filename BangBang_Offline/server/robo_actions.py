"""Map19 Robo: native stats/route, user-approved provisional AI and fixed shot."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import scene


class RoboActions(TankActions):
    shot_skill=1000006
    shot_interval=2250
    shot_school='energy'
    def __init__(self,arena,ident,info,camp,spawn):
        info.setdefault('npc_template',info.get('template'))
        info.update(robo=True,tank_id=10000019,tank_level=1,acct_id=0,name='Robo',in_room=True)
        super().__init__(arena,ident,info,camp,spawn)
        self.stats=dict(self.stats,iHp='1800',iAttack='187.2',iEgAtk='187.2',iArmor='100',
                        iEgArmor='200',iCentesis='0',iEgCtsis='0',iSpeed='60',iFireInterv='2250',
                        nFireRange='480',iMp='0')
        self.hp=self.max_hp=D(1800)
        self.cooldowns={0:0}
        self.info['hp']=self.info['max_hp']=1800
        self.last_speed=60
        self.route_point=info['point']
        self.route_previous=None
        self.route_queue=[]

    def snapshot(self,now):
        body=struct.pack('<IIhhiBiIiH',self.id,self.info['npc_template'],*self.position_at(now),
                         math.ceil(self.hp),self.camp,math.ceil(self.max_hp),0,0,0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def sync_speed(self,now):return []

    def commit_hp(self,hp,now,*,critical=False):
        alive=self.alive
        packets=super().commit_hp(hp,now,critical=critical)
        if alive and not self.alive:packets.append(scene(removed=(struct.pack('<I',self.id),)))
        return packets

    def _respawn(self,now,generation):
        if self.alive or self.generation!=generation:return []
        self.generation+=1
        self.hp=self.max_hp
        self.info['hp']=int(self.hp)
        self.position,self.motion,self.forced_until=self.spawn,None,0
        self.route_point=self.info['point'];self.route_previous=None;self.route_queue=[]
        self.cooldowns={0:now}
        return [self.snapshot(now)]

    def cast(self,slot,start,dest,target,now):
        if slot or not self.alive or self.blocked('attack',now) or self.cooldowns[0]>now or dest==start:return []
        self.cooldowns[0]=now+self.shot_interval
        packets=self.shoot(self.shot_skill,start,dest,now,D(100),school=self.shot_school,basic=True)
        for offset in (300,600):self._queue(now+offset,'robo_shot',self.generation,dest)
        return packets

    def _event(self,now,kind,data):
        if kind=='robo_shot':
            generation,dest=data
            if self.generation!=generation or not self.alive or self.blocked('attack',now):return []
            start=self.position_at(now)
            return self.shoot(self.shot_skill,start,dest,now,D(100),school=self.shot_school,basic=True) if start!=dest else []
        return super()._event(now,kind,data)


class MayaChieftain(RoboActions):
    """Approved map1 objective: reuse visible-target patrol AI and 30s respawn."""
    shot_skill=1000041
    shot_interval=4000
    shot_school='physical'

    def __init__(self,arena,ident,info,camp,spawn):
        super().__init__(arena,ident,info,camp,spawn)
        self.info.update(chieftain=True,name='Tù Trưởng (1 điểm)',hp=1494,max_hp=1494)
        self.stats.update(iHp='1494',iAttack='301.6',iEgAtk='301.6',iArmor='225',
                          iEgArmor='225',iSpeed='90',iFireInterv='4000')
        self.hp=self.max_hp=D(1494)
        self.last_speed=90
