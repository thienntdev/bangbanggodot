"""Geometry and piercing contact shared by the approved batch10 melee kits."""
import math
import struct

from combat_geometry import actor_contact, circle_contact, point_at
from combat_protocol import scene, stop_move


def prepare_displacement(target,now,*,interrupt=True,cancel_motion=False):
    """Resolve a forced-motion handoff before interrupt can discard its origin.

    A dash may legally cross a wall, but a replacement push or suppression
    cannot inherit the wall-interior sample as its body origin. Ordinary
    grid-based walking is deliberately unchanged. Callers keep their original
    contact/range sample separately and use the returned pose only for motion.

    A cast that abandons motion (rather than replaces it with another move)
    opts into cancel_motion: publish the authoritative stop even in open space,
    and release only a forced deadline matching that abandoned segment. Other
    control buffs and independently longer movement locks are not removed.
    """
    packets=[]
    motion=target.motion
    forced_until=target.forced_until
    if cancel_motion and motion:
        position=target.position_at(now)
        if (target.motion_kind or forced_until>now) and motion[3]>now:
            position=target.stop_position(now)
        target.position,target.motion=position,None
        packets.append(stop_move(target.scene_id,target.id,position))
        if forced_until>now and forced_until==motion[3]:
            target.forced_until=now
    elif motion and (target.motion_kind or forced_until>now) and motion[3]>now:
        current=target.position_at(now)
        stopped=target.stop_position(now)
        if stopped!=current:
            target.position,target.motion=stopped,None
            packets.append(stop_move(target.scene_id,target.id,stopped))
    if interrupt:
        packets.extend(target.interrupt(now))
    return target.position_at(now),packets


def accept_water_reclip(target,cast):
    """Accept only a recorded continuation of this cast's water-clipped motion.

    ThuyTinh records a constant-size lineage when an actual water wall clips
    an existing kind1 segment. A different source's shorter push is not proof
    of a wall impact. Nested ``motion`` fields use native checkpoint rebasing.
    A rejected match does not mutate either target or cast.
    """
    record=getattr(target,'water_motion_reclip',None)
    if (not record or record.get('generation')!=target.generation
            or not target.motion or target.motion!=record.get('motion')):
        return False
    origin=record.get('origin')
    expected=cast.get('water_motion_origin',{}).get('motion',cast.get('motion'))
    if not origin or expected!=origin.get('motion'):
        return False
    cast['water_motion_origin']=origin
    return True


def aimed(start,dest,distance,*,fixed=False):
    length=math.dist(start,dest)
    if not length:
        return start
    return tuple(round(v) for v in point_at(start,dest,distance/length if fixed else min(1,distance/length)))


def enemies(actor,*,area=False):
    return [a for a in actor.arena.actors.values() if a.alive and a.camp!=actor.camp
            and (a.is_area_targetable() if area else not a.is_untargetable())]


def in_cone(pos,start,dest,radius,degrees):
    if math.dist(start,pos)>radius:
        return False
    angle=math.atan2(pos[1]-start[1],pos[0]-start[0])-math.atan2(dest[1]-start[1],dest[0]-start[0])
    return abs(math.atan2(math.sin(angle),math.cos(angle)))<=math.radians(degrees/2)


def in_strip(pos,start,dest,length,width):
    dx,dy=dest[0]-start[0],dest[1]-start[1]
    distance=math.hypot(dx,dy)
    if not distance:
        return False
    x,y=pos[0]-start[0],pos[1]-start[1]
    return 0<=(x*dx+y*dy)/distance<=length and abs(x*dy-y*dx)/distance<=width/2


def piercing_step(actor,flight,now,on_hit,*,pierce=True,contact_radius=36):
    start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
    end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
    wall=actor.arena.geometry.wall_contact(start,end) if not flight.get('through_walls') else None
    contacts=[]
    for target in enemies(actor):
        key=target.id,target.generation
        if key in flight['hits']:
            continue
        hit=actor_contact(start,end,target,flight['previous'],now,contact_radius)
        if hit is not None and (wall is None or hit<wall):
            contacts.append((hit,target.id,target,key))
    packets=[]
    ident=struct.pack('<I',flight['id'])
    for _,_,target,key in sorted(contacts):
        if actor.projectile_blocked(target,now):
            return packets+[scene(expired_bullets=(ident,))]
        flight['hits'].add(key)
        packets.extend(on_hit(flight,target,now))
        if not pierce:
            return packets+[scene(blown_bullets=(ident,))]
    if wall is not None or now>=flight['finish']:
        return packets+[scene(**{'blown_bullets' if wall is not None else 'expired_bullets':(ident,)})]
    flight['previous']=now
    actor._queue(min(now+20,flight['finish']),'flight',flight)
    return packets
