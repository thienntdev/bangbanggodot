"""Battle packet layouts verified against the original AS3 client."""
import struct


def props(skill, slot, count=-1, end=0, next_charge=0):
    return struct.pack('<IBbQQ', skill, slot, count, end, next_charge)


def scene(*, moves=(), fires=(), skills=(), hp=(), mp=(), blown_bullets=(), expired_bullets=(), shields=(), removed=()):
    vectors = (moves, fires, skills, hp, (), mp, blown_bullets, removed, expired_bullets, shields)
    return 1564, b''.join(struct.pack('<H', len(v)) + b''.join(v) for v in vectors)


def skill_event(skill, start, dest, target=0, *, owner=1, ready=0):
    return struct.pack('<IIIhhhhBB', owner, target, skill,
                       *(round(x) for x in (*start, *dest)), ready, 1)


def move_event(position, speed, kind, owner=1):
    return struct.pack('<IhhhBB', owner, *(round(x) for x in position), speed, 8, kind)


def stop_move(scene_id, owner, position):
    """NotifyStopMove: cancel the current client tween and set its position."""
    return 1554, struct.pack('<IIhh', scene_id, owner, *(round(x) for x in position))


def team_space_cooldowns(packets, arena, viewer=None):
    """Feed native teammate portraits only Space, never another slot's timer.

    BattleSkillModel.updateSelfCampSkill filters non-Space for self only.
    Other owners share one PropsInfo per portrait, so E/R/basic would overwrite
    Space. Keep self's full skill packets untouched for its own hotbar.
    """
    player = viewer or arena.player

    def teammate(actor):
        return (actor is not None and actor is not player
                and not actor.info.get('npc_template')
                and actor.info.get('in_room', True) and actor.camp == player.camp)

    def portrait(body):
        # The portrait reads only nEndTime. Match SkillTool.getEndTimeStmp:
        # no charges means wait for the later of the gap and next recharge.
        count, end, charge = struct.unpack_from('<bQQ', body, 5)
        if count == 0 and charge > end:
            return body[:6] + struct.pack('<Q', charge) + body[14:]
        return body

    result = []
    for mid, body in packets:
        if mid == 1572:
            owner, = struct.unpack_from('<I', body, 22)
            if owner != player.id:
                if body[4] != 2 or not teammate(arena.actors.get(owner)):
                    continue
                body = portrait(body)
        result.append((mid, body))
        if mid == 1550:
            # Self's portrait also needs a fresh value after initSkill().
            result.append(player._cooldown(2))
        elif mid == 1551:
            # Initial entry/new round: views now exist. Explicit zeros clear
            # the client's per-owner cache left over from the previous match.
            for actor in arena.actors.values():
                if teammate(actor):
                    _, cooldown = actor._cooldown(2)
                    result.append((1572, portrait(cooldown)))
        elif mid == 1552:
            actor = arena.actors.get(struct.unpack_from('<I', body)[0])
            if teammate(actor):
                _, cooldown = actor._cooldown(2)
                result.append((1572, portrait(cooldown)))
    return result


def immediate_positions(packets, scene_id):
    """Send authoritative snaps immediately, not into CTank's walking queue.

    MOVE_SERVER (5, direction NONE) is currently used for teleports/stops.
    Native NotifyStopMove expresses exactly that intent and clears old tweens.
    Leave timed pushes, dashes and every non-movement vector unchanged.
    """
    result=[]
    for mid,body in packets:
        if mid!=1564:
            result.append((mid,body));continue
        count,=struct.unpack_from('<H',body)
        if not count:
            result.append((mid,body));continue
        moves=[]
        for offset in range(2,2+12*count,12):
            owner,x,y,speed,direction,kind=struct.unpack_from('<IhhhBB',body,offset)
            if kind==5 and direction==8 and speed==0:
                if moves:
                    result.append(scene(moves=tuple(moves)));moves=[]
                packet=stop_move(scene_id,owner,(x,y))
                if not result or result[-1]!=packet:result.append(packet)
            else:moves.append(body[offset:offset+12])
        tail=body[2+12*count:]
        if moves or any(tail):
            result.append((mid,struct.pack('<H',len(moves))+b''.join(moves)+tail))
    return result
