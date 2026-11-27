"""Optional local-player presentation. Never stored in combat buffs or stats."""
import math
import struct

from combat_math import D

TEMPLATE=990056
INSTANCE_BASE=0x7e000000


def survives_execute(target,now):
    """Read-only counterparts of the existing commit_hp(0) rescue branches."""
    tank=target.info['tank_id']
    if target.info.get('execute_immune') or D(target.info.get('death_floor',0))!=0:
        return True
    if tank in (10000096,10000055,10000046):  # Kirito, Kakashi, Luffy
        return now>=target.passive_ready_at
    if tank==10000038:  # Ghost Rider changes to soul instead of dying.
        return target.soul is None and now>=target.passive_ready_at
    if tank==10000051:
        return bool(target.form and target.form['phase']=='active')
    if tank==10000079:
        return not target.ice and now>=target.passive_ready_at
    if tank==10000070:
        return bool(target.rebirth or target.has_buff(344101,now))
    return False


def ready(source,now):
    return (source.info['tank_id']==10000056 and source.alive
            and not source.blocked('attack',now) and not source.skill_sealed(2,now)
            and source.cooldowns[2]<=now)


def eligible_target(source,target,now):
    if (target.camp==source.camp or not target.alive or target.info.get('npc_template')
            or target.info.get('map_object') or target.is_untargetable()):
        return False
    return (target.hp<=target.max_hp*D(source.effects[331301]['fEffectVal'])
            and math.dist(source.position_at(now),target.position_at(now))<=int(source.skills[331301]['iRange'])
            and not survives_execute(target,now))


def eligible(source,target,now):
    return ready(source,now) and eligible_target(source,target,now)


def sync(arena,now,*,reset=False,viewer=None):
    from battle_participants import human, private
    if viewer is None and arena.state.get('multiplayer_players'):
        return [packet for actor in arena.actors.values() if human(actor)
                for packet in sync(arena,now,reset=reset,viewer=actor)]
    player=viewer or arena.player
    all_previous=getattr(arena,'_quanvu_hints_by_actor',{})
    previous={} if reset else all_previous.get(player.id,{})
    current={}
    if ((player.state.get('room') or {}).get('quanvu_execute_hint',False)
            and not (arena.pk and arena.pk['finished']) and ready(player,now)):
        current={a.id:a.generation for a in arena.actors.values() if eligible_target(player,a,now)}
    packets=[]
    for ident,generation in previous.items():
        if current.get(ident)!=generation:
            packets.append(private(player,(1559,struct.pack('<II',ident,INSTANCE_BASE+ident))))
    for ident,generation in current.items():
        if previous.get(ident)!=generation:
            packets.append(private(player,(1558,struct.pack('<IIIBII',ident,TEMPLATE,INSTANCE_BASE+ident,1,player.id,0xffffffff))))
    all_previous[player.id]=current
    arena._quanvu_hints_by_actor=all_previous
    return packets
