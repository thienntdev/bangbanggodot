"""One explicit local birth outlet for505/901; no authored route is invented."""
from combat_geometry import rect_contact


SOURCE = (2052, 1956)
OUTLET = (1980, 1956)
FACTORY_RECT = (2028., 1932., 2076., 1980.)


def factory_exit(arena, actor, rec, now):
    from pve_local_mechanics import enabled
    geometry = arena.geometry
    factory = arena.actors.get((3 << 26) | 20187)
    if (geometry.id != 505 or not enabled(arena) or arena.pk['finished']
            or rec.get('map') != 505 or rec.get('point') != 901
            or tuple(rec.get('position', ())) != SOURCE or rec.get('camp') != 0
            or actor.info.get('point') != 901 or actor.info.get('pve_rule') != rec.get('index')
            or actor.info.get('npc_template') not in (555, 556)
            or actor.info['npc_template'] not in rec.get('templates', ())
            or not actor.alive or actor.camp != 0 or actor._speed(now) <= 0
            or not actor.info.get('pve_npc')
            or any(actor.info.get(key) for key in
                   ('pve_stationary', 'pve_flying', 'pve_trap', 'pve_hostage'))
            or tuple(actor.position_at(now)) != SOURCE or tuple(actor.spawn) != SOURCE
            or geometry.can_walk_to(SOURCE) or not factory or not factory.alive
            or not factory.info.get('map_object') or factory.info.get('npc_template') != 5019
            or tuple(factory.position_at(now)) != SOURCE or factory.map_rect != FACTORY_RECT
            or geometry.movement_walls.count(FACTORY_RECT) != 1
            or geometry.walls.count(FACTORY_RECT) != 1):
        return
    native = next((r for r in geometry.data.get('pve_spawns', ())
                   if r['index'] == rec['index']), None)
    definition = next((r for r in geometry.data.get('npcs', ()) if r['instance'] == 20187), None)
    if (native != rec or not definition or [5, 901, 0, ''] not in definition.get('pve_scripts', ())
            or not geometry.can_walk_to(OUTLET) or geometry.clamp_tank_position(OUTLET) != OUTLET
            or geometry.wall_contact(OUTLET, OUTLET, 35.999) is not None
            or geometry.wall_contact(SOURCE, OUTLET, 35.999, exclude=(FACTORY_RECT,)) is not None
            or rect_contact(SOURCE, OUTLET, arena.water_rects(now), 35.999) is not None):
        return
    # Spawn geometry is resolved beforeS1556. The ordinary NPC AI retains its
    # own cadence, targeting, route fields and ability to wait for allied body
    # spacing. A factory death still invokes the original STOP901 exactly once.
    actor.position = actor.spawn = OUTLET
