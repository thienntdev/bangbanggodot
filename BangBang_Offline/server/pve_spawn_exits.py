"""Two explicit local chapter-six spawn exits; never a movement exception.

The source records put these unrouted NPCs inside live destructible cover.
Only a new versioned local run may use the reviewed adjacent birth points.
Actors are constructed at the legal point before their first snapshot. The
source records, live covers, STOP scripts and all subsequent walking stay
unchanged. No actor already present in a checkpoint is relocated.
"""
import math

from combat_geometry import rect_contact
from pve_local_mechanics import enabled


EXITS = {
    (603, 301): dict(
        origin=(250, 1000), wave=3, repeat=0,
        births={702: (324, 996), 703: (324, 1068)},
        covers=((20005, 2004, (191., 952., 263., 1024.)),
                (20006, 2003, (167., 1024., 239., 1096.)))),
    (30102, 211): dict(
        origin=(359, 1418), wave=1, repeat=1,
        births={3110201: (348, 1380), 3110202: (420, 1380)},
        covers=((21001, 4318, (267., 1426., 411., 1570.)),)),
}


def position(arena, record, template, now):
    source = tuple(record['position'])
    rule = EXITS.get((arena.geometry.id, record['point']))
    if (not enabled(arena) or rule is None
            or record.get('map') != arena.geometry.id or record.get('camp') != 0
            or record.get('wave') != rule['wave'] or record.get('repeat') != rule['repeat']
            or source != rule['origin'] or template not in rule['births']
            or arena.geometry.can_walk_to(source)):
        return source
    live = []
    for instance, kind, rectangle in rule['covers']:
        actor = arena.actors.get((3 << 26) | instance)
        if actor is None or not actor.alive:
            continue
        if (actor.info.get('npc_template') != kind or tuple(actor.map_rect) != rectangle
                or arena.geometry.movement_walls.count(rectangle) != 1):
            return source
        live.append(rectangle)
    # The exception cannot conceal overlapping terrain or any other cover.
    if (not live or rect_contact(source, source, live, 35.999) is None
            or arena.geometry.wall_contact(source, source, 35.999, exclude=live) is not None):
        return source
    birth = rule['births'][template]
    if (math.dist(source, birth) > 128 or not arena.geometry.can_walk_to(birth)
            or rect_contact(birth, birth, arena.geometry.movement_walls, 35.999) is not None
            or arena.geometry.wall_contact(source, birth, 35.999, exclude=live) is not None
            or rect_contact(source, birth, arena.water_rects(now), 35.999) is not None):
        return source
    return birth
