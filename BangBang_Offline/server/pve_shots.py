"""Approved chapter-one projectile variants, using the shared damage pipeline."""
import math
import struct
from combat_data import table_row
from combat_geometry import point_at,rect_contact
from combat_math import D
from combat_protocol import scene
from melee_common import in_strip


def targets(actor,pos,radius,now,exclude=()):
    for target in list(actor.arena.actors.values()):
        if (target.id in exclude or target.camp==actor.camp or not target.alive
                or not target.is_area_targetable() or target.info.get('pve_hostage')):continue
        dest=target.position_at(now)
        if math.dist(pos,dest)>radius:continue
        ignore=(target.map_rect,) if hasattr(target,'map_rect') else ()
        if actor.arena.geometry.wall_contact(pos,dest,exclude=ignore) is not None:continue
        if rect_contact(pos,dest,actor.arena.water_rects(now)) is not None:continue
        yield target


def _fixed_laser_origin(actor,start,end,now):
    """Narrow offline repair for703's authored wall-mounted emitter2612.

    Its source point145 is inside the120x72 housing. Starting collision at
    the NPC centre clips every ray to zero. Keep the actor and its original
    300px endpoint unchanged; the visible/damaging ray begins just outside
    that one housing. No other emitter, pose, direction or wall is exempt.
    """
    geometry=actor.arena.geometry
    if (geometry.id!=703 or actor.shot_skill!=1000056
            or not actor.info.get('pve_npc') or actor.info.get('npc_template')!=2612
            or actor.info.get('point')!=145 or not actor.info.get('pve_trap')
            or not actor.info.get('pve_stationary') or start!=(612,2820)
            or tuple(actor.spawn)!=(612,2820) or end[0]<=start[0] or end[1]!=start[1]):
        return start
    housing=(552.,2784.,672.,2856.);muzzle=(673,2820)
    if (geometry.walls.count(housing)!=1 or not geometry.inside(muzzle)
            or geometry.wall_contact(start,muzzle,exclude=(housing,)) is not None
            or rect_contact(start,muzzle,actor.arena.water_rects(now)) is not None):
        return start
    return muzzle


def shot(actor,dest,now,target=None):
    from pve_bosses import shot as boss_shot
    boss_packets=boss_shot(actor,dest,now,target)
    if boss_packets is not None:return boss_packets
    start=actor.position_at(now);skill=actor.shot_skill
    # The suicide blast is centered on its caster and needs no aim vector.
    if start==dest and skill!=1000034:return []
    if skill in (1000088,1000103,1000105,1000117,1000118,1000119,1000123,1000128,1000133,1000151):
        from pve_bio import melee
        return melee(actor,target,now)
    if skill in (1000055,1000134):
        from pve_transport_traps import shot as transport_shot
        return transport_shot(actor,dest,now)
    if skill==1000120:
        from pve_final_attacks import chain
        return chain(actor,start,target,now)
    if skill==1000122:
        from pve_final_attacks import spider_explode
        return spider_explode(actor,now)
    if skill==50332:
        from pve_chapter6 import cleanse_allies
        return cleanse_allies(actor,now)
    if skill==1000040:
        from combat_protocol import skill_event
        packets=[scene(skills=(skill_event(skill,start,start,owner=actor.id),))]
        for victim in targets(actor,start,96,now):
            packets+=actor.damage(actor.combat_stat('iAttack',now)*D('.5'),now,target=victim,
                                  school='physical',basic=True)[0]
            if actor.arena.pk['finished']:return packets
            if victim.alive:packets+=actor._buff(222,now,victim.id)
        return packets
    if skill==1000054:
        from pve_support import signal
        return signal(actor,dest,now)
    if skill in (1000034,1000062):
        from pve_support import explode
        return explode(actor,now)
    if skill in (1000009,1000031,1000032,1000033,1000039,1000056):
        length={1000031:500,1000032:500,1000039:200,1000056:300}.get(skill,360)
        end=tuple(round(v) for v in point_at(start,dest,length/math.dist(start,dest)))
        start=_fixed_laser_origin(actor,start,end,now)
        fraction=min((v for v in (actor.arena.geometry.wall_contact(start,end),
            rect_contact(start,end,actor.arena.water_rects(now))) if v is not None),default=1.)
        end=tuple(round(v) for v in point_at(start,end,fraction));ident=actor._new_id(2)
        # Native laser exhibits have no flying bitmap. Their forward beam is
        # the BLOW movie, anchored at the firing origin. Dispatch FIRE + BLOW
        # together: a delayed expiry neither plays that movie nor preserves
        # its origin (the invisible projectile has already travelled).
        packets=[scene(fires=(struct.pack('<IIhhhhhI',ident,actor.id,*start,*end,32767,skill),),
                       blown_bullets=(struct.pack('<I',ident),))]
        for target in targets(actor,start,length+36,now):
            if in_strip(target.position_at(now),start,end,math.dist(start,end),24) and not actor.projectile_blocked(target,now):
                physical=skill in (1000031,1000056)
                packets+=actor.damage(actor.combat_stat('iAttack' if physical else 'iEgAtk',now),now,
                                      target=target,school='physical' if physical else 'energy',basic=True)[0]
                if actor.arena.pk['finished']:return packets
                if skill==1000039 and target.alive:
                    version=target.buff_versions.get(224)
                    packets+=actor._buff(224,now,target.id)
                    if target.buff_versions.get(224)!=version:
                        actor._queue(now+1000,'pve_flame_tick',target.id,target.buff_versions[224],actor.generation,5)
        return packets
    if skill in (1000010,1000017,1000037,1000065,1000069):
        row=table_row('SkillTemplate_table.xml',nId=skill)
        radius=int(row['iFlyRange']);dist=math.dist(start,dest)
        dest=tuple(round(v) for v in point_at(start,dest,min(1,radius/dist)))
        duration=int(row['iLifeTime']);ident=actor._new_id(2)
        speed=max(1,round(math.dist(start,dest)*1000/duration))
        flight=dict(pve_lob=True,kind='bullet',id=ident,start=start,end=dest,begin=now,finish=now+duration,
                    previous=now,template=skill,generation=actor.generation,raw=actor.combat_stat('iAttack',now),
                    source_generation=actor.generation,speed=speed,basic=True,school='energy' if skill in (1000065,1000069) else 'physical',
                    through_walls=True,target=None,reflected=False,attacker_ap=actor.combat_stat('iAttack',now))
        if skill==1000065:flight['energy_ap']=actor.combat_stat('iEgAtk',now)
        actor._queue(now+20,'flight',flight)
        return [scene(fires=(struct.pack('<IIhhhhhI',ident,actor.id,*start,*dest,
                     speed,skill),))]
    packets=[]
    angles = (-15,0,15) if actor.pve_scatter or skill==1000071 else (0,)
    if skill in (50333,50337):
        # Source fan parameter is treated as the full spread, centered on aim.
        count, spread = (5,75) if skill==50333 else (7,90)
        angles = tuple(-spread/2 + i*spread/(count-1) for i in range(count))
    for angle in angles:
        dx,dy=dest[0]-start[0],dest[1]-start[1];a=math.radians(angle)
        aim=(round(start[0]+dx*math.cos(a)-dy*math.sin(a)),round(start[1]+dx*math.sin(a)+dy*math.cos(a)))
        energy=skill in (1000006,1000008,1000015,1000018,1000025,1000027,1000043,1000064,1000072,1000073)
        raw=D(0) if skill==1000016 else actor.combat_stat('iEgAtk' if energy else 'iAttack',now)
        if skill==1000030:raw*=3
        if skill==1000038:raw*=D('.5')
        if skill==1000071:raw=D(300)+raw*D('.5')
        if skill==50337:raw*=2
        packets+=actor.shoot(skill,start,aim,now,raw,school='energy' if energy else 'physical',basic=True,
                            lifesteal=D('.1') if skill==1000087 else D('.02') if skill in (1020040,1020050) else 0,
                            target=target if skill in (1000015,1000025,1000026) else None)
    return packets


def on_hit(actor,flight,target,now):
    if actor.arena.pk['finished']:return []
    if actor.arena.geometry.id==201:return []
    if flight['template'] in (1000120,1001120):
        from pve_final_attacks import bounce
        return bounce(actor,flight,target,now)
    if flight['template'] in (1000106,1000125,1000131,1020022,1020025):
        from pve_bio import on_hit as bio_hit
        return bio_hit(actor,flight,target,now)
    if flight['template'] in (1000043,1000064,1000073):
        if not target.alive:return []
        buff={1000043:244,1000064:50307,1000073:101503}[flight['template']]
        packets=actor._buff(buff,now,target.id,refresh=True)
        if buff==244 and target.has_buff(244,now) and target.buff_sources.get(244)==actor.id:
            actor._queue(now+2000,'pve_poison_tick',target.id,target.buff_versions[244],actor.generation,20,target.generation)
        return packets
    if flight['template'] in (1000016,50337):
        return actor._buff(3,now,target.id)
    if flight['template'] not in (1000018,1000004,1000030,1000038):return []
    packets=actor._buff(222,now,target.id) if flight['template']==1000038 else []
    radius={1000004:144,1000018:72,1000030:216,1000038:24}[flight['template']]
    for other in targets(actor,target.position_at(now),radius,now,(target.id,)):
        if flight['template'] in (1000004,1000030) and actor.projectile_blocked(other,now):continue
        packets+=actor.damage(flight['raw'],now,target=other,school=flight['school'],basic=True,
                              source_generation=flight['source_generation'])[0]
        if actor.arena.pk['finished']:return packets
        if flight['template']==1000038:packets+=actor._buff(222,now,other.id)
    return packets


def poison_tick(actor,now,data):
    ident,version,generation,remaining,target_generation=data;target=actor.arena.actors.get(ident)
    if (actor.arena.pk['finished'] or not target or not target.alive or
            target.generation!=target_generation or target.buff_versions.get(244)!=version or
            target.buff_sources.get(244)!=actor.id):return []
    if not target.has_buff(244,now) and remaining!=1:return []
    packets=actor.damage(D(30),now,target=target,school='true',periodic=True,source_generation=generation)[0]
    if remaining>1 and not actor.arena.pk['finished']:
        actor._queue(now+2000,'pve_poison_tick',ident,version,generation,remaining-1,target_generation)
    return packets


def lob(actor,flight,now):
    start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
    end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
    if rect_contact(start,end,actor.arena.water_rects(now)) is not None:
        return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
    if now<flight['finish']:
        flight['previous']=now;actor._queue(min(now+20,flight['finish']),'flight',flight);return []
    packets=[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
    nuclear=flight['template'] in (1000065,1000069)
    for target in targets(actor,flight['end'],144 if nuclear else 108,now):
        if flight['template']==1000010 and actor.projectile_blocked(target,now):continue
        raw=D(1000)+target.max_hp*D('.1') if nuclear else flight['raw']
        if flight['template']==1000065:raw=D(200)+flight['energy_ap']
        packets+=actor.damage(raw,now,target=target,school='energy' if nuclear else 'physical',basic=True,
                              source_generation=flight['generation'])[0]
        if actor.arena.pk['finished']:return packets
        if flight['template']==1000010 and target.alive:
            packets+=actor._buff(20001,now,target.id,duration=3000)
    if nuclear and not actor.arena.pk['finished']:
        ident,packet=actor.add_object(50303,flight['end']);packets.append(packet)
        zone=dict(id=ident,position=flight['end'],end=now+(3000 if flight['template']==1000065 else 5000),
                  generation=flight['generation'],next_tick_at=now+1000)
        if flight['template']==1000065:zone['energy_raw']=D(80)+flight['energy_ap']*D('.75')
        packets+=radiation(actor,zone,now)
    return packets


def radiation(actor,zone,now):
    if actor.arena.pk['finished']:return actor.remove_object(zone['id'])
    packets=[]
    tick=now>=zone.get('next_tick_at',now)
    for target in targets(actor,zone['position'],144,now):
        if now<zone['end']:
            packets+=actor._buff(50311,now,target.id,duration=min(100,zone['end']-now),refresh=True)
        if not tick:continue
        # Overlapping fields from one NPC cannot tick twice at the same time.
        key=(actor.id,target.id);last=getattr(actor,'pve_radiation_hits',{})
        if last.get(key,{}).get('hit_at',-1000)+1000>now:continue
        last[key]={'hit_at':now};actor.pve_radiation_hits=last
        packets+=actor.damage(zone.get('energy_raw',target.max_hp*D('.06')),now,target=target,
                              school='energy' if 'energy_raw' in zone else 'physical',periodic=True,
                              source_generation=zone['generation'])[0]
        if actor.arena.pk['finished']:return packets
    if tick:zone['next_tick_at']=now+1000
    if now>=zone['end']:packets+=actor.remove_object(zone['id'])
    else:actor._queue(min(now+100,zone['end']),'pve_radiation',zone)
    return packets
