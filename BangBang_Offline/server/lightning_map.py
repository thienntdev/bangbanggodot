"""Map21: approved provisional energy objectives and home lightning defenses."""
import math
import struct

from totem_objectives import TotemObject
from combat_math import D
from combat_geometry import rect_contact
from combat_protocol import scene


def tank_present(actor):
    return not actor.info.get('npc_template') and actor.alive and actor.is_area_targetable()


def clear(arena,start,end,now):
    return (arena.geometry.wall_contact(start,end) is None
            and rect_contact(start,end,arena.water_rects(now)) is None)


class EnergyTower(TotemObject):
    def __init__(self,*args):
        super().__init__(*args)
        self.info['energy_tower']=True
        self.energy_ready_at=0
        self.next_tick_at=0

    def reject_buff(self,row,source,now):
        if source is self and int(row['nBuffId'])==10001323:return False
        return super().reject_buff(row,source,now)

    def on_spawn(self,now):
        self.energy_ready_at=now;self.next_tick_at=now
        return super().on_spawn(now)

    def advance(self,now):
        if not self.alive or now<self.next_tick_at or now<self.energy_ready_at:return []
        self.next_tick_at=now+200
        targets=[a for a in self.arena.actors.values() if tank_present(a) and a.camp==self.camp
                 and math.dist(self.spawn,a.position_at(now))<=300
                 and clear(self.arena,self.spawn,a.position_at(now),now)]
        if not targets:return []
        self.energy_ready_at=now+30000
        packets=self._buff(10001323,now)
        packets.append(scene(skills=(self._skill_event(1000132,self.spawn,self.spawn,self.id),)))
        for actor in targets:
            packets+=self._buff(10001321,now,actor.id)
            packets+=self._buff(10001322,now,actor.id)
        return packets


class ElectricTower(TotemObject):
    def __init__(self,*args):
        super().__init__(*args)
        self.info.update(totem=False,electric_tower=True,untargetable=True,damage_immune=True,hp=-1,max_hp=-1)
        self.hp=self.max_hp=D(1)
        self.next_tick_at=0;self.electric_ready_at=0

    def snapshot(self,now):
        return 1556,struct.pack('<IIIhhiBiIiH',self.scene_id,self.id,self.info['npc_template'],
                               *self.spawn,-1,self.camp,-1,0,0,0)

    def commit_hp(self,hp,now,*,critical=False):return []
    def reject_buff(self,row,source,now):
        return not (source is self and int(row['nBuffId'])==self.color_buff)

    def candidates(self,start,radius,visited,now):
        return sorted((math.dist(start,a.position_at(now)),a.id,a) for a in self.arena.actors.values()
                      if tank_present(a) and a.camp!=self.camp and a.id not in visited
                      and (26 not in a.buff_types(now) or 32 in a.buff_types(now))
                      and math.dist(start,a.position_at(now))<=radius
                      and clear(self.arena,start,a.position_at(now),now))

    def advance(self,now):
        if now<self.next_tick_at or now<self.electric_ready_at:return []
        self.next_tick_at=now+200
        targets=self.candidates(self.spawn,450,set(),now)
        if not targets:return []
        self.electric_ready_at=now+5000
        target=targets[0][2]
        return self.shoot(1000114,self.spawn,target.position_at(now),now,D(0),school='true',target=target)

    def damage(self,raw,now,**kwargs):
        # Contact installs the delayed native mark. It is not a zero-damage
        # attack that should trigger tank defenses a second time.
        return ([],False) if raw==0 else super().damage(raw,now,**kwargs)

    def _flight(self,flight,now):
        if flight.get('template') not in (1000114,1001114):return super()._flight(flight,now)
        target=self.arena.actors.get(flight.get('target'))
        if (target is None or not tank_present(target) or target.generation!=flight['target_generation']
                or (26 in target.buff_types(now) and 32 not in target.buff_types(now))):
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        # Native traced projectile uses the same trajectory/update packets as
        # other homing skills. Newly created water walls also stop this chain.
        if rect_contact(flight['pos'],target.position_at(now),self.arena.water_rects(now)) is not None:
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        return super()._flight(flight,now)

    def on_bullet_hit(self,flight,target,now):
        packets=self._buff(10001141,now,target.id)
        if packets:
            self._queue(now+1000,'electric_damage',target.id,target.generation,target.buff_versions[10001141])
        visited=flight['hits'];visited.add(target.id)
        if len(visited)<5:
            pos=target.position_at(now);targets=self.candidates(pos,360,visited,now)
            if targets:
                nxt=targets[0][2]
                packets+=self.shoot(1001114,pos,nxt.position_at(now),now,D(0),school='true',target=nxt,hit_ids=visited)
        return packets

    def _event(self,now,kind,data):
        if kind!='electric_damage':return super()._event(now,kind,data)
        ident,generation,version=data;target=self.arena.actors.get(ident)
        if (not target or not target.alive or target.generation!=generation
                or target.buff_versions.get(10001141)!=version):return []
        return self.damage(D(150),now,target=target,school='true',periodic=True)[0]


def install(arena):
    for actor in arena.actors.values():
        if (actor.info.get('map_object') and actor.camp==0 and actor.info['npc_template'] in (2008,2009,2010)
                and any(math.dist(actor.spawn,d['position'])<180 for d in arena.geometry.data['energy_towers'])):
            actor.info['energy_barrier']=True
    for key,cls in (('energy_towers',EnergyTower),('electric_towers',ElectricTower)):
        for definition in arena.geometry.data[key]:
            actor=cls(arena,arena.new_id(5),definition)
            arena.actors[actor.id]=actor


def tick(arena,now):
    packets=[]
    for actor in arena.actors.values():
        if actor.info.get('energy_tower') or actor.info.get('electric_tower'):packets+=actor.advance(now)
    return packets


def goal(arena,actor,now):
    # Static objective positions are public; never select a concealed tank.
    # Combat/recovery take priority in bot_ai before considering this goal.
    own=next(a for a in arena.actors.values() if a.info.get('energy_tower') and a.camp==actor.camp)
    if own.alive and now>=own.energy_ready_at and not actor.has_buff(10001321,now):
        return 'totem',own.spawn
    enemy=next(a for a in arena.actors.values() if a.info.get('energy_tower') and a.camp!=actor.camp)
    return ('totem',enemy.spawn) if enemy.alive else None
