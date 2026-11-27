"""Source-pinned PvE timed-bomb barriers (M28 offline rule).

Native Props800 -> Effect801 -> Props802 waits 5000 ms, then Effect803 has
radius216/damageLevel3. Npc2002 is the authored grade3 hollow-brick barrier.
The native prop chunk has no explicit group links. To honor the requested
whole-barrier blast, the groups below are the connected camp2 brick walls
touching each authored bomb's radius, reviewed against the raw map records.
This grouping is an explicit offline inference, not recovered Flash code.
It never applies to all bricks in a map, other templates, gates or PvP.
"""

# map: (raw .map SHA256, ((prop instance, position, brick instances), ...))
PUZZLES = {
    211: ('29cd00d2e500300c858b3814206a34f514a835d6dc536f9df284c6cc782ce772', (
        (4, (708, 1356), (349, 350, 352, 353)),
    )),
    212: ('3a931857336ecae7e0486df5133f8ef1cca7382f5366b377eba3b9ebe4d2ac15', (
        (3, (1020, 1044), (308, 309, 310, 311)),
        (4, (852, 2268), (324, 325, 326, 327)),
    )),
    301: ('fe9e1edd4c48b17716aae710ea3d7bfa93fa239cdb2c25f6155f27c663af822c', (
        (1, (564, 660), (158, 159, 160, 161, 162, 163)),
        (2, (372, 2076), (110, 111, 112, 113, 166, 167)),
    )),
    302: ('af152ddc6f77e8837012cb4a0f90acdc968c2c6508b65e0cebd7ce65f40ffada', (
        (1, (972, 3516), (20, 21)),
        (18, (804, 1980), (117, 118, 119, 120, 121, 122, 131, 132)),
        (19, (804, 1692), (144, 145, 146, 147, 148, 149, 150, 151, 152,
                          153, 154, 155, 156, 157, 158, 159, 160, 161, 162)),
        (20, (804, 1332), (177, 178, 179, 180, 181, 182, 183, 184, 185,
                          186, 187, 188, 189, 198, 199, 209)),
        (64, (852, 684), (351, 352, 353, 354)),
    )),
    303: ('bc329b9cdc7bb155f389146b9cb38e05f1f605b7553395b0e46dba41acb16093', (
        (5, (420, 1764), (87, 88, 89, 90)),
    )),
    304: ('1256fb0a52ae33575ce669891090e257de620f7037cc6ce2799363e8e1b3370c', (
        (23, (468, 2076), (139, 140, 141, 142, 143)),
        (24, (828, 1260), (150, 151)),
    )),
    305: ('8a0556a7ecb109fa0ffce2ad2739c0532aba30a9616778659907e4efbac16041', (
        (15, (852, 1740), (14, 15, 16, 17)),
    )),
    306: ('20dbdaf01048ed8b13c3f38fa11e766ec52674038d67492a59f2320a447f57e4', (
        (21, (852, 3132), (109, 110, 113, 114)),
        (22, (516, 2196), (46, 47)),
    )),
    703: ('56cd5383937d4006ce2babcaf5ee64266932d43465a433ccf8a0b0f421744366', (
        (1, (1788, 1932), (100, 101, 102, 103, 104, 105)),
        (2, (1788, 2364), (93, 94, 95, 96, 97, 98)),
    )),
}


def groups(arena):
    """Only exact authored bomb identities in a matching native layout."""
    # Old checkpoints may contain a spent bomb and partially damaged bricks.
    # Do not make those remaining old-rule bricks suddenly indestructible.
    profile = arena.state.get('battle', {}).get('pve_balance') or {}
    if profile.get('bomb_puzzles_version') != 1:
        return ()
    rule = PUZZLES.get(arena.geometry.id)
    if rule is None or arena.geometry.data.get('source', {}).get('sha256') != rule[0]:
        return ()
    props = {tuple(p) for p in arena.geometry.data.get('pve_props', ())}
    return tuple(g for g in rule[1] if (g[0], 800, 0, *g[1]) in props)


def protected(arena, definition):
    if (definition['template'] != 2002 or definition['camp'] != 2
            or definition.get('pve_gate') or definition['hp'] <= 0):
        return False
    return any(definition['instance'] in instances for _, _, instances in groups(arena))


def activation_radius(arena, hazard):
    """Reach the reviewed bomb behind its own protected wall in map302.

    Its nearest accessible native walking point is 144px south of the bomb.
    Keep the original prop position, five-second fuse and blast unchanged;
    this offline correction belongs only to the pinned M28 puzzle layout.
    Other bombs and checkpoints with the legacy barrier rule retain 72px.
    """
    if (arena.geometry.id == 302 and hazard.get('template') == 800
            and hazard.get('source') == 20
            and tuple(hazard.get('position', ())) == (804, 1332)
            and any(source == 20 and pos == (804, 1332)
                    for source, pos, _ in groups(arena))):
        return 144
    return 72


def detonate(arena, hazard, now):
    """Dismantle this barrier once, then execute existing authored callbacks.

    Ordinary combat cannot cross the guard. This dedicated script path must
    not run through the four-hit scenery rule, damage credit, random drops,
    or NPC kill rewards. Clearing geometry before callbacks also invalidates
    Python/native walking and projectile caches for the newly opened route.
    """
    if arena.pk['finished'] or hazard['template'] != 800:
        return []
    instances = next((ids for source, pos, ids in groups(arena)
                      if source == hazard['source'] and pos == tuple(hazard['position'])), ())
    objects = [arena.actors.get((3 << 26) | ident) for ident in instances]
    objects = [obj for obj in objects if obj and obj.alive and getattr(obj, 'pve_bomb_only', False)]
    if not objects:
        return []
    from pve_chapter1 import remove_objects
    from pve_rules import chapter
    packets = remove_objects(arena, (obj.id & ((1 << 26) - 1) for obj in objects))
    controller = chapter(arena)
    for obj in objects:
        if arena.pk['finished']:
            break
        packets += controller.object_destroyed(arena, obj, now)
    return packets
