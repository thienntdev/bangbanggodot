"""Map40 rules approved 08/10; temporary schedules, original visual templates."""
import math
import struct

from combat_math import D
from combat_protocol import scene
from death_mode import center,RADIUS,ZONE_TEMPLATE,tanks,environment_hit
from quicksand_map import notice

BASE_BUFFS=(108001,108002,108003)
AREA_BUFFS=(10301006,10301007)


def install(arena):
    arena.pk.update(vent_due_at=arena.pk['begin']+30000,vents=[],radiation_steps={})
    arena.pk['collapse_tick_at']=arena.pk['collapse_at']+1000


def put_scene(arena,template,pos):
    ident=arena.new_id(4)
    body=struct.pack('<IIhhiBiIiH',ident,template,*pos,0,0,0,0,0,0)
    arena.objects[ident]=body.hex()
    return ident,(1556,struct.pack('<I',arena.scene_id)+body)


def remove_scene(arena,ident):
    arena.objects.pop(ident,None)
    return scene(removed=(struct.pack('<I',ident),))


def refresh(actor,template,now,duration=1500):
    threshold=100 if template in AREA_BUFFS else 500
    if actor.active_buffs.get((actor.id,template),(0,0))[1]-now>threshold:return []
    return actor._buff(template,now,duration=duration,refresh=True,stacks=1)


def tick(arena,now):
    pk=arena.pk;packets=[];members=tanks(arena)
    for actor in members:
        if not actor.alive:continue
        for buff in BASE_BUFFS:
            if not actor.has_buff(buff,now):packets+=actor._buff(buff,now,duration=-1,stacks=1)
    if now>=pk['vent_due_at']:
        # Sample public terrain, never a player's inputs or hidden position.
        cells=[(x,y) for x in range(108,arena.geometry.width-108,48)
               for y in range(108,arena.geometry.height-108,48) if arena.geometry.can_walk_to((x,y))]
        chosen=[]
        for _ in range(2):
            choices=[p for p in cells if all(math.dist(p,q)>=240 for q in chosen)]
            if not choices:break
            pos=arena.rng.choice(choices);chosen.append(pos)
            ident,packet=put_scene(arena,10301001,pos);packets.append(packet)
            pk['vents'].append(dict(id=ident,pos=pos,vent_burst_at=now+2000,
                                    vent_end_at=now+7000,vent_tick_at=now+2500,active=False))
        pk['vent_due_at']+=20000
    for vent in list(pk['vents']):
        if now>vent['vent_end_at']:
            packets.append(remove_scene(arena,vent['id']));pk['vents'].remove(vent);continue
        if now<vent['vent_burst_at']:continue
        contacts=[a for a in members if a.alive and a.is_area_targetable() and math.dist(a.position_at(now),vent['pos'])<=120]
        if not vent['active']:
            packets.append(remove_scene(arena,vent['id']))
            vent['id'],packet=put_scene(arena,10301002,vent['pos']);packets.append(packet)
            vent['active']=True
            for actor in contacts:
                packets+=environment_hit(actor,now,D(50))
                if actor.alive and not actor.cc_immune(now):packets+=actor._buff(10301004,now,duration=1000)
        if now>=vent['vent_tick_at']:
            vent['vent_tick_at']+=500
            for actor in contacts:packets+=environment_hit(actor,now,D(25))
        if now==vent['vent_end_at']:
            packets.append(remove_scene(arena,vent['id']));pk['vents'].remove(vent)
    for actor in members:
        if not actor.alive or actor.in_stasis():continue
        hot=any(v['active'] and math.dist(actor.position_at(now),v['pos'])<=120 for v in pk['vents'])
        for buff in AREA_BUFFS:
            if hot:packets+=refresh(actor,buff,now,550)
            elif actor.has_buff(buff,now):packets+=actor.remove_buff(buff,now)
    if now>=pk['collapse_at']-5000 and not pk.get('collapse_warned'):
        pk['collapse_warned']=True
        _,packet=put_scene(arena,ZONE_TEMPLATE,center(arena));packets.append(packet)
        packets.append(notice('Phóng xạ lan rộng sau 5 giây! Về vùng bảo vệ giữa bản đồ; vẫn phải né địa hỏa.'))
    if now<pk['collapse_at']:return packets
    if not pk.get('collapse_started'):
        pk['collapse_started']=True
        packets.append(notice('Ngoài vùng bảo vệ: mất 5–10% HP tối đa mỗi giây. Vào vùng xóa mức tăng và làm lộ tàng hình.'))
    due=now>=pk['collapse_tick_at']
    if due:pk['collapse_tick_at']+=1000
    for actor in members:
        if not actor.alive:continue
        safe=math.dist(actor.position_at(now),center(arena))<=RADIUS
        if safe:pk['radiation_steps'][actor.id]=0
        if actor.in_stasis():continue
        required=(10301021,10301023) if safe else (10301022,)
        for buff in (10301021,10301022,10301023):
            if buff in required:packets+=refresh(actor,buff,now)
            elif actor.has_buff(buff,now):packets+=actor.remove_buff(buff,now)
        if due and not safe:
            step=pk['radiation_steps'].get(actor.id,0)
            packets+=environment_hit(actor,now,actor.max_hp*D(min(10,5+step))/100)
            pk['radiation_steps'][actor.id]=min(5,step+1)
    return packets


def observe(arena,actor,now):
    pos=actor.position_at(now)
    return [dict(pos=v['pos'],observed_at=now,vent_end_at=v['vent_end_at'])
            for v in arena.pk['vents'] if math.dist(pos,v['pos'])<=600
            and arena.geometry.wall_contact(pos,v['pos']) is None]


def evade(arena,actor,brain,now):
    pos=actor.position_at(now)
    hazards=[v for v in brain.get('vents',[]) if now<v['vent_end_at'] and now-v['observed_at']<2000]
    if not any(math.dist(pos,v['pos'])<180 or math.dist(brain.get('goal',pos),v['pos'])<150 for v in hazards):return
    choices=[]
    for i in range(8):
        p=tuple(round(v) for v in (pos[0]+192*math.cos(i*math.tau/8),pos[1]+192*math.sin(i*math.tau/8)))
        if not arena.geometry.can_walk_to(p) or arena.geometry.walk_end(pos,p)!=p:continue
        if now>=arena.pk['collapse_at']-5000 and math.dist(p,center(arena))>RADIUS-36:continue
        if all(math.dist(p,v['pos'])>=160 for v in hazards):choices.append(p)
    if choices:
        brain['goal']=min(choices,key=lambda p:math.dist(p,brain.get('goal',pos)))
        brain['repath_at']=0
