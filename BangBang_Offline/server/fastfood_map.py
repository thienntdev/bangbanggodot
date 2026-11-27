"""Map17 KFC mascots: authored patrols and approved provisional healing."""
import math

from battle_runtime import TankActions
from robo_actions import RoboActions
from combat_math import D
from combat_geometry import rect_contact
from combat_protocol import scene


class Mascot(RoboActions):
    def __init__(self,arena,ident,info,camp,spawn):
        super().__init__(arena,ident,info,camp,spawn)
        self.info.update(robo=False,mascot=True,name=f'Ông Già KFC {"A" if camp==1 else "B"} (1 điểm)',
                         hp=5000,max_hp=5000)
        self.stats.update(iHp='5000',iArmor='25',iEgArmor='25',iSpeed='60',
                          iAttack='135',iEgAtk='135',iFireInterv='10000',nFireRange='216')
        self.hp=self.max_hp=D(5000)
        self.cooldowns={}

    def cast(self,*args,**kwargs):return []  # No offensive shot or enemy chase.

    def sync_speed(self,now):return TankActions.sync_speed(self,now)

    def on_spawn(self,now):
        self._queue(now+10000,'mascot_heal',self.generation)
        return self._buff(249 if self.camp==1 else 250,now,duration=-1)

    def _respawn(self,now,generation):
        packets=super()._respawn(now,generation)
        if not packets:return []
        self.respawn_at=0;self.damage_credit=None;self.cooldowns={}
        self.last_speed=60
        return packets+self.on_spawn(now)

    def _event(self,now,kind,data):
        if kind!='mascot_heal':return super()._event(now,kind,data)
        if data[0]!=self.generation or not self.alive or self.arena.pk['finished']:return []
        self._queue(now+10000,'mascot_heal',self.generation)
        if self.blocked('skill',now) or self.skill_sealed(1,now):return []
        pos=self.position_at(now);packets=[]
        for target in self.arena.actors.values():
            if (target.info.get('npc_template') or target.camp!=self.camp or not target.alive
                    or not target.is_area_targetable() or target.hp>=target.max_hp):continue
            dest=target.position_at(now)
            if (math.dist(pos,dest)>216 or self.arena.geometry.wall_contact(pos,dest) is not None
                    or rect_contact(pos,dest,self.arena.water_rects(now)) is not None):continue
            packets+=target.restore_hp(D(300)+target.max_hp*D('.05'),now)
            packets.append(scene(skills=(self._skill_event(1000058,pos,dest,target.id),)))
        return packets


def install(arena):
    for definition in arena.geometry.data['mascots']:
        actor=Mascot(arena,arena.new_id(5),dict(definition),definition['camp'],tuple(definition['position']))
        arena.actors[actor.id]=actor
