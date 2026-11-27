"""Approved one-life rounds; map-specific environmental rules stay separate."""
import copy
import math
import struct
from fractions import Fraction

from combat_math import D, apply_damage
from combat_protocol import scene, stop_move
from quicksand_map import notice

CENTER = (1092, 852)
RADIUS = 250
ZONE_TEMPLATE = 9000030


def center(arena):
    return (1092,840) if arena.geometry.id==40 else CENTER


def install(arena, now):
    pk = arena.pk
    pk.update(round_phase='playing', match_started_at=now, round_number=1,
              initial_bots=copy.deepcopy(arena.state.get('bots', [])),
              collapse_at=pk['intro_until']+60000, collapse_tick_at=pk['intro_until']+60500)
    pk['begin'] = pk['intro_until']
    pk['end'] = pk['begin']+150000
    pk['air_drop_due_at'] = pk['begin']+60000
    if arena.geometry.id==40:
        from death_city import install as install_city
        install_city(arena)


def tanks(arena):
    return [arena.actors[i] for i in arena.pk['stats']]


def alive_packet(arena):
    counts = [sum(a.alive and a.camp==c for a in tanks(arena)) for c in (1, 2)]
    return 1736, struct.pack('<II', *counts)


def round_packet(arena):
    return 1734, struct.pack('<III', arena.pk['begin']//1000,
                             arena.pk['round_number'], arena.scene_id)


def check_round(arena, now):
    pk = arena.pk
    if pk['finished'] or pk['round_phase']!='playing' or now<pk['intro_until']:
        return []
    groups = [[a for a in tanks(arena) if a.alive and a.camp==c] for c in (1, 2)]
    if all(groups) and now<pk['end']:
        return []
    values = [(len(group), sum((Fraction(a.hp)/Fraction(a.max_hp) for a in group), Fraction()))
              for group in groups]
    winner = 1 if values[0]>values[1] else 2 if values[1]>values[0] else 0
    pk.update(round_phase='result', round_winner=winner, round_reset_at=now+5000)
    if winner:pk['scores'][winner] += 1  # no trophy on a draw
    packets = []
    # Stop server simulation and client walking for the five-second result.
    for a in tanks(arena):
        a.position, a.motion = a.position_at(now), None
        packets.append(stop_move(arena.scene_id,a.id,a.position))
        for template in (50353,336302,4083):
            ident=arena.new_id(6)
            pk.setdefault('result_locks',[]).append((a.id,ident,template))
            packets.append((1558,struct.pack('<IIIBII',a.id,template,ident,1,a.id,5000)))
    if winner:
        # S1735 increments the native trophy counter itself. Do not precede
        # it with S1733 containing the already-incremented total.
        packets.append((1735,struct.pack('<i',winner)))
    else:
        packets.append(notice('Hòa vòng — không cộng cúp. Vòng này sẽ đấu lại sau 5 giây.'))
    return packets+[alive_packet(arena)]


def transition(arena, now):
    pk=arena.pk
    if now<pk['round_reset_at']:return []
    if max(pk['scores'].values())>=2:
        from pk_rules import finish
        return finish(arena,now)
    return reset_round(arena,now)


def reset_round(arena, now):
    from battle_entry import self_snapshot_packets,actor_info
    from pk_rules import static_packets,score_packets
    old=arena.pk
    packets=[(1559,struct.pack('<II',owner,ident))
             for (owner,_),(ident,_) in arena.active_buffs.items()]
    packets += [(1559,struct.pack('<II',owner,ident)) for owner,ident,template in old.get('result_locks',[])]
    ids=set(arena.actors)|set(arena.objects)|set(old.get('drops',{}))
    ids.update((3<<26)|n['instance'] for n in arena.geometry.data['npcs'])
    for _,_,_,args in arena.pending:
        if args and args[0]=='flight':ids.add(args[1][0]['id'])
    packets.append(scene(removed=tuple(struct.pack('<I',i) for i in sorted(ids))))
    state,clock,rng,ai,serial=arena.state,arena.clock,arena.rng,arena.bot_attacks,arena.serial
    navigation_seed=getattr(arena,'_multiplayer_navigation_seed',None)
    state['bots']=copy.deepcopy(old['initial_bots'])
    # Reconstruct every kit through its existing constructor. This also resets
    # borrowed E sessions, life-saving passives, map collision and summons.
    arena.__dict__.clear()
    arena.__init__(state,clock=clock,rng=rng,bot_attacks=ai,serial_start=serial)
    if navigation_seed is not None:
        from multiplayer_battle import install_navigation
        install_navigation(arena,navigation_seed)
    for key in ('scores','stats','initial_bots','match_started_at','first_blood'):
        if key in old:arena.pk[key]=old[key]
    arena.pk['round_number']=sum(arena.pk['scores'].values())+1
    if state.get('multiplayer_players'):
        from battle_participants import human, private
        for player in tanks(arena):
            if not human(player):continue
            others=[actor_info(a,now) for a in tanks(arena) if a is not player]
            packets += [private(player,p) for p in self_snapshot_packets(player.state,player)]
            packets.append(private(player,(1551,struct.pack('<H',len(others))+b''.join(others))))
    else:
        others=[actor_info(a,now) for a in tanks(arena) if a.id!=1]
        packets += self_snapshot_packets(state,arena.player)+[
                    (1551,struct.pack('<H',len(others))+b''.join(others))]
    packets += static_packets(arena)+score_packets(arena)
    if arena.geometry.id==40:
        from map_portals import snapshot
        packets.append(snapshot(arena))
    for actor,*ids in arena.pk['intro_buffs']:
        packets += [(1558,struct.pack('<IIIBII',actor,t,i,1,actor,3000))
                    for t,i in zip((50353,336302,4083),ids)]
    return packets+[round_packet(arena)]


def environment_hit(actor, now, amount=None):
    if not actor.alive or actor.in_stasis() or actor.damage_immune('true',now,True):return []
    hit=apply_damage(actor.max_hp*D('.02') if amount is None else amount,actor.hp,actor.shields,school='true',now_ms=now,
                     hp_floor=min(actor.hp,max(D(actor.info.get('death_floor',0)),
                                              D(1) if actor.has_buff(359301,now) else D(0))))
    protected=actor.prevent_lethal_hit(hit,now)
    if protected is not None:return protected
    old=actor.shields;actor.shields=hit.shields
    # Environment is not a tank skill and cannot credit an earlier attacker.
    actor.damage_credit=None
    packets=actor.commit_hp(hit.hp_after,now)
    if old!=actor.shields:packets.append(actor.shield_packet(now))
    for ident in hit.broken_shield_ids:
        packets+=actor.remove_buff(int(ident),now)+actor.on_shield_break(int(ident),now)
    return packets


def hazard_tick(arena, now):
    if arena.geometry.id==40:
        from death_city import tick
        return tick(arena,now)
    pk=arena.pk;packets=[]
    if now>=pk['collapse_at']-5000 and not pk.get('collapse_warned'):
        pk['collapse_warned']=True
        ident=arena.new_id(4)
        body=struct.pack('<IIhhiBiIiH',ident,ZONE_TEMPLATE,*CENTER,0,0,0,0,0,0)
        arena.objects[ident]=body.hex()
        packets.append((1556,struct.pack('<I',arena.scene_id)+body))
        packets.append(notice('Sụp mỏ sau 5 giây! Về vùng bảo vệ giữa bản đồ (bán kính 250).'))
    if now<pk['collapse_at']:return packets
    if not pk.get('collapse_started'):
        pk['collapse_started']=True
        packets.append(notice('Mỏ đang sụp: ngoài vùng giữa mất 4% HP tối đa mỗi giây. Trong vùng không thể tàng hình.'))
    due=now>=pk['collapse_tick_at']
    if due:pk['collapse_tick_at']+=500
    for a in tanks(arena):
        if not a.alive or a.in_stasis():continue
        safe=math.dist(a.position_at(now),CENTER)<=RADIUS
        templates=(10300061,10300063) if safe else (10300062,)
        for template in (10300061,10300062,10300063):
            if template not in templates and a.has_buff(template,now):packets+=a.remove_buff(template,now)
        for template in templates:
            if a.active_buffs.get((a.id,template),(0,0))[1]-now<500:
                packets+=a._buff(template,now,duration=1500,refresh=True)
        if due and not safe:packets+=environment_hit(a,now)
    return packets


def survival_goal(arena, actor, brain, now):
    # Public hazard position; neither hidden opponents nor future observations.
    angle=(actor.id%5)*math.tau/5
    radius=130
    c=center(arena)
    point=(round(c[0]+radius*math.cos(angle)),round(c[1]+radius*math.sin(angle)))
    return ('survive',point if arena.geometry.can_walk_to(point) else c)


def constrain_goal(arena,actor,brain,seen,now):
    """Retreat toward support, then stay inside the announced safe area."""
    pos=actor.position_at(now)
    if not seen:return
    allies=[a for a in tanks(arena) if a is not actor and a.alive and a.camp==actor.camp]
    if actor.hp/actor.max_hp<D('.28') and allies:
        friend=min(allies,key=lambda a:math.dist(pos,a.position_at(now)))
        brain['goal']=friend.position_at(now)
    if now>=arena.pk['collapse_at']-5000:
        goal=brain.get('goal',pos)
        if math.dist(goal,center(arena))>RADIUS-45:
            brain['goal']=survival_goal(arena,actor,brain,now)[1]
