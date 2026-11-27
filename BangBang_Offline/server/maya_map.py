"""Map1 objectives and approved provisional native-script replacements."""
import math
import struct

from robo_actions import RoboActions
from combat_math import D
from combat_geometry import rect_contact
from combat_protocol import scene,stop_move
from quicksand_map import apply_bonuses,notice


class MineSpider(RoboActions):
    def __init__(self,arena,ident,info,camp,spawn):
        super().__init__(arena,ident,info,camp,spawn)
        self.info.update(robo=False,map_spider=True,name='Nhện mìn',hp=0,max_hp=139)
        self.stats.update(iHp='138.4',iAttack='306',iEgAtk='306',iArmor='226',
                          iEgArmor='113',iSpeed='140',nFireRange='100',iFireInterv='1000')
        self.hp=D(0);self.max_hp=D('138.4');self.last_speed=140;self.activated=False

    def _respawn(self,now,generation):return []

    def cast(self,slot,start,dest,target,now):
        if slot or not self.alive or self.blocked('attack',now):return []
        tank=self.arena.actors.get(target)
        if (not tank or tank.info.get('npc_template') or not tank.alive or tank.is_untargetable()
                or math.dist(start,tank.position_at(now))>100):return []
        types=tank.buff_types(now)
        if 26 in types and 32 not in types:return []
        if self.arena.geometry.wall_contact(start,tank.position_at(now)) is not None:return []
        if rect_contact(start,tank.position_at(now),self.arena.water_rects(now)) is not None:return []
        targets=[a for a in self.arena.actors.values() if not a.info.get('npc_template')
                 and a.alive and a.is_area_targetable() and math.dist(start,a.position_at(now))<=144
                 and self.arena.geometry.wall_contact(start,a.position_at(now)) is None
                 and rect_contact(start,a.position_at(now),self.arena.water_rects(now)) is None]
        self.position=start;self.motion=None
        packets=[stop_move(self.scene_id,self.id,start)]
        for actor in targets:
            packets+=self.damage(D(500),now,target=actor,school='physical')[0]
            if self.arena.pk['finished']:return packets
        packets+=self.commit_hp(D(0),now)
        return packets


def install(arena):
    # Keep the four dormant actors from construction onward: stable IDs across
    # checkpoints, and a box breaking during AoE never changes actors mid-loop.
    for nest in arena.geometry.data['spider_nests']:
        for index in range(2):
            obj=MineSpider(arena,arena.new_id(5),dict(nest,nest_index=index),0,tuple(nest['position']))
            arena.actors[obj.id]=obj
    arena.pk['air_drop_due_at']=arena.pk['begin']+60000
    arena.pk['opened_nests']=set()
    arena.pk['maya_quest']=dict(hunter=arena.rng.choice((1,2)),kills=0,finished=False,
                                announced=False,quest_due_at=arena.pk['intro_until']+90000)


def reward_quest(arena,camp):
    quest=arena.pk['maya_quest']
    if quest['finished']:return []
    quest['finished']=True;quest['winner']=camp
    arena.pk['scores'][camp]+=3
    return [notice(f'Phe {"xanh" if camp==1 else "đỏ"} hoàn thành thử thách Tù Trưởng: +3 điểm!')]


def chieftain_death(arena,victim,now):
    quest=arena.pk['maya_quest']
    if quest['finished']:return []
    if now>quest['quest_due_at']:return reward_quest(arena,3-quest['hunter'])
    if victim.camp==quest['hunter']:return []
    quest['kills']+=1
    return reward_quest(arena,quest['hunter']) if quest['kills']>=2 else []


def open_nest(arena,point,now):
    arena.pk['opened_nests'].add(point)
    packets=[];occupied=[a.position_at(now) for a in arena.actors.values() if a.alive and not a.info.get('map_object')]
    for actor in arena.actors.values():
        if not actor.info.get('map_spider') or actor.info['point']!=point or actor.activated:continue
        # The authored center was inside the destroyed crate; spawn in a nearby
        # clear cell, without overlapping the other spider or a tank.
        x,y=actor.info['position']
        choices=[(x+24*dx,y+24*dy) for dx in range(-6,7) for dy in range(-6,7)]
        legal=[p for p in choices if arena.geometry.can_walk_to(p)
               and arena.geometry.wall_contact(p,p,35.999) is None
               and rect_contact(p,p,arena.water_rects(now),36) is None
               and all(math.dist(p,q)>=72 for q in occupied)]
        if not legal:continue
        pos=min(legal,key=lambda p:(math.dist((x,y),p),p))
        actor.activated=True;actor.hp=actor.max_hp;actor.info['hp']=math.ceil(actor.hp)
        actor.position=actor.spawn=pos;occupied.append(pos)
        packets.append(actor.snapshot(now))
    return packets


def tick(arena,now):
    if arena.pk['finished'] or now<arena.pk['intro_until']:return []
    packets=[]
    for actor in arena.actors.values():packets+=apply_bonuses(actor,now)
    for point in arena.pk['opened_nests']:
        if any(a.info.get('map_spider') and a.info['point']==point and not a.activated for a in arena.actors.values()):
            packets+=open_nest(arena,point,now)
    quest=arena.pk['maya_quest']
    if not quest['announced']:
        quest['announced']=True
        packets.append(notice(f'Thử thách 90s: phe {"xanh" if quest["hunter"]==1 else "đỏ"} hạ 2 Tù Trưởng địch; phe kia bảo vệ. Bên hoàn thành +3 điểm.'))
    if not quest['finished'] and now>=quest['quest_due_at']:
        from pk_rules import score_packets,finish
        packets+=reward_quest(arena,3-quest['hunter'])+score_packets(arena)
        if max(arena.pk['scores'].values())>=25:
            return packets+finish(arena,now)
    from map_objects import air_drop_tick
    packets+=air_drop_tick(arena,now)
    return packets


def in_bush(arena,position):
    x,y=position
    return arena.geometry.data.get('bushes',{}).get(str(int(y)//24*(arena.geometry.width//24)+int(x)//24),0)


def visible_from(arena,observer,target,now):
    """Approved conservative sight rule; never invent an unverified reveal."""
    bush=in_bush(arena,target.position_at(now))
    return not bush or in_bush(arena,observer.position_at(now))==bush


def goal(arena,actor,observations,now):
    quest=arena.pk['maya_quest']
    if quest['finished'] or actor.id%3!=0:return None
    hunting=actor.camp==quest['hunter']
    chief=next(a for a in arena.actors.values() if a.info.get('chieftain')
               and a.camp==(3-actor.camp if hunting else actor.camp))
    # Friendly positions and authored objective routes are known; never read
    # an enemy objective's unseen current pose/HP to guide its hunters.
    seen=next((s for s in observations if s['id']==chief.id),None)
    if hunting:
        pos=seen['pos'] if seen else chief.spawn
    else:
        pos=chief.position_at(now) if chief.alive else chief.spawn
    return 'maya_quest',pos
