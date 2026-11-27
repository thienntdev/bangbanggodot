"""Map18 stationary objectives: native stats, approved 30s respawn, no drops."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_math import D
from combat_protocol import scene


class TotemObject(TankActions):
    def __init__(self,arena,ident,definition):
        row=table_row('AINpcTemplate_table.xml',nTemplateId=definition['template'])
        arms=table_row('AINpcArmsTemplate_table.xml',nTemplateId=int(row['nArmsId']))
        level=table_row('AINpcLevelTemplate_table.xml',nLevelId=int(row['nLevelId']))
        info=dict(definition,npc_template=definition['template'],totem=True,
                  tank_id=10000019,tank_level=1,acct_id=0,name=row['szName'],in_room=True)
        super().__init__(arena,ident,info,definition['camp'],tuple(definition['position']))
        self.stats=dict(self.stats,iHp=level['iHp'],iArmor=level['iBdArmor'],iEgArmor=level['iEgArmor'],
                        iAttack='0',iEgAtk='0',iCentesis='0',iEgCtsis='0',iSpeed='0',iMp='0')
        self.hp=self.max_hp=D(level['iHp'])*D(arms['fHpCoef'])
        self.info['hp']=self.info['max_hp']=int(self.hp)
        self.cooldowns={}
        self.color_buff=int(arms['iBuffId1'])

    def snapshot(self,now):
        return 1556,struct.pack('<IIIhhiBiIiH',self.scene_id,self.id,self.info['npc_template'],
            *self.spawn,math.ceil(self.hp),self.camp,math.ceil(self.max_hp),0,0,0)

    def on_spawn(self,now):
        return [self.snapshot(now)]+self._buff(self.color_buff,now,duration=-1)

    def position_at(self,now):return self.spawn
    def sync_speed(self,now):return []
    def cc_immune(self,now,*,slow=False):return True
    def _set_motion(self,start,dest,speed,now,kind=0):return 1
    def move_destination(self,start,dest):return self.spawn
    def blink_destination(self,start,dest):return self.spawn
    def restore_hp(self,amount,now):return []
    def add_shield(self,*args,**kwargs):return []
    def cast(self,*args,**kwargs):return []

    def reject_buff(self,row,source,now):
        # Keep normal hostile damage/debuffs; CC is rejected by cc_immune.
        # Allies cannot add support effects, including immunity or invisibility.
        return source.camp==self.camp and not (source is self and int(row['nBuffId'])==self.color_buff)

    def commit_hp(self,hp,now,*,critical=False):
        if not self.alive or hp>=self.hp:return []
        packets=super().commit_hp(hp,now,critical=critical)
        if not self.alive:packets.append(scene(removed=(struct.pack('<I',self.id),)))
        return packets

    def _respawn(self,now,generation):
        if self.alive or self.generation!=generation:return []
        self.generation+=1;self.respawn_at=0
        self.hp=self.max_hp;self.info['hp']=int(self.hp)
        self.position,self.motion,self.forced_until=self.spawn,None,0
        self.damage_credit=None
        return self.on_spawn(now)


def install(arena):
    for definition in arena.geometry.data['totems']:
        obj=TotemObject(arena,arena.new_id(5),definition)
        arena.actors[obj.id]=obj


def goal(arena,actor):
    # Both objective locations and their destruction/respawn are public.
    # Enemy tanks still take priority whenever seen by the team.
    target=next(a for a in arena.actors.values() if a.info.get('totem') and a.camp!=actor.camp)
    return ('totem',target.spawn) if target.alive else None
