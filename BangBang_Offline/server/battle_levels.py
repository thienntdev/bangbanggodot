"""Battle-only progression for approved base mode; garage levels stay separate."""
from battle_participants import human, private
import math
import struct
from functools import lru_cache

from combat_data import table_row, tank_stats
from combat_math import D
from storage import database_path


@lru_cache(maxsize=80)
def _row(database, level):
    return table_row('BattleExpTemplate_table.xml',nMode=1,nLevel=level)


def row(level):
    return _row(str(database_path()),level)


def enabled(actor):
    return actor.arena.geometry.id in (12,14,50,169) and not actor.info.get('npc_template')


def refresh_stats(actor):
    """Rebuild excluded static stats after checkpoint load, without healing."""
    if not enabled(actor):return
    level=actor.info.get('battle_level',1)
    if level==1:return
    bonus=row(level)
    base=tank_stats(actor.info['tank_id'],actor.info['tank_level'],actor.info.get('tank_strength',0))
    from bot_loadouts import eligible
    if eligible(actor.id,actor.info):
        from crystal_combat import apply_flat
        apply_flat(base,actor.info)
        from military_rank import apply_flat as apply_military, equipped as military_equipped
        if military_equipped(actor.id, actor.info):
            apply_military(base,actor.info)
        from guild_combat import apply_passives
        apply_passives(base,actor.info)
    for key,field in (('iHp','fMaxHpAddRate'),('iAttack','fAtkAddRate'),('iEgAtk','fAtkAddRate')):
        actor.stats[key]=str(D(base[key])*(1+D(bonus[field])))


def cooldown(actor,duration,slot=None):
    if not enabled(actor) or slot==0:return duration
    # A charged slot's action lock is its use interval, not its refill timer.
    # Refills call with no slot; ordinary active skills pass their actual slot.
    charge={1:'e_next_charge',2:'space_next_charge',10:'r_next_charge'}.get(slot)
    if charge and hasattr(actor,charge):return duration
    owner=vars(actor).get('_host',actor)
    rate=D(row(owner.info.get('battle_level',1))['fSkillCoolTimeReduceRate'])
    return max(0,round(D(duration)*(1-rate)))


def grant(actor,amount,now,position=None,*,kill=False):
    if not enabled(actor) or amount<=0:return []
    level=actor.info.get('battle_level',1)
    if level>=20:return []
    exp=actor.info.get('battle_exp',0)+int(amount)
    packets=[];old_level=level
    while level<20 and exp>=int(row(level)['nExp']):
        exp-=int(row(level)['nExp']);level+=1
        packets.append((1595,struct.pack('<IB',actor.id,level)))
        if human(actor):
            pos=position or actor.position_at(now)
            packets.append(private(actor,(1585,struct.pack('<HhhB',0,*(round(v) for v in pos),int(kill)))))
    actor.info.update(battle_exp=exp if level<20 else 0,battle_level=level)
    if level!=old_level:
        factor=(1+D(row(level)['fMaxHpAddRate']))/(1+D(row(old_level)['fMaxHpAddRate']))
        actor.max_hp*=factor;actor.hp*=factor
        # Nezha restores a captured untransformed maximum at Space end.
        # Advance that baseline too, so ending the form cannot erase levels.
        if actor.info['tank_id']==10000082 and getattr(actor,'form',None):
            actor.form['max_hp']*=factor
        refresh_stats(actor)
        actor.info.update(hp=math.ceil(actor.hp),max_hp=math.ceil(actor.max_hp))
        packets+=[(1560,struct.pack('<IBi',actor.info['acct_id'],3,math.ceil(actor.max_hp))),
                  actor._hp_packet(actor.id,actor.hp)]
    if human(actor):
        # Native TankModel consumes level first, then current EXP. This packet
        # is self-only; other players' progress is carried by level snapshots.
        pos=position or actor.position_at(now)
        packets.append(private(actor,(1585,struct.pack('<HhhB',actor.info['battle_exp'],*(round(v) for v in pos),int(kill)))))
    return packets


def reward_death(victim,now):
    arena=victim.arena
    if arena.geometry.id not in (12,14,50,169) or arena.pk['finished']:return []
    credit=getattr(victim,'damage_credit',None)
    source=arena.actors.get(credit[0]) if credit else None
    if not source or source.generation!=credit[1] or source.camp not in (1,2) or source.camp==victim.camp:return []
    if not victim.info.get('npc_template'):
        return grant(source,50,now,victim.position_at(now),kill=True)
    if victim.info.get('map_object'):
        reward=table_row('NpcTemplate_table.xml',nTemplateId=victim.info['npc_template'])
    elif victim.info.get('base_robot'):
        reward=table_row('AINpcTemplate_table.xml',nTemplateId=victim.info['npc_template'])
    else:return []
    common=int(reward.get('nCampBattleExp') or 0)
    single=int(reward.get('nSingleBattleExp') or 0)
    radius=int(reward.get('nCampBattleRadius') or 0)
    targets=sorted((a for a in arena.actors.values() if enabled(a) and a.alive and a.camp==source.camp
                    and math.dist(a.position_at(now),victim.position_at(now))<=radius),key=lambda a:a.id)
    packets=[]
    if common and targets:
        share,remainder=divmod(common,len(targets))
        for i,a in enumerate(targets):packets+=grant(a,share+int(i<remainder),now,victim.position_at(now))
    packets+=grant(source,single,now,victim.position_at(now),kill=True)
    return packets
