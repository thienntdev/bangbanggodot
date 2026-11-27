"""Frozen player / opted-in bot Guild skills. No database writes in combat."""
import math
import struct

from combat_data import table_row
from combat_math import D
from bot_loadouts import eligible
from combat_geometry import rect_contact
from combat_protocol import props, scene, stop_move
from melee_common import prepare_displacement

PASSIVE_ATTRIBUTES = {4:'iAttack',5:'iEgAtk',6:'iArmor',7:'iEgArmor',
                      8:'iCentesis',9:'iEgCtsis',10:'iFireInterv',11:'iSpeed',12:'iHp'}


def build(actor):
    if not eligible(actor.id, actor.info):
        return {}
    return actor.info.get('guild', {})


def passive_ids(info):
    return tuple(v['skill'] for k,v in info.get('guild',{}).items() if k != '1')


def passive_buff(template):
    return 500101 <= template <= 508109


def weaken_buff(template):
    return 510801 <= template <= 510839


def weaken_factor(actor, attributes, now):
    factor=D(1)
    for buff in actor.buff_started:
        if not weaken_buff(buff) or not actor.has_buff(buff,now):continue
        row=table_row('BuffTemplate_table.xml',nBuffId=buff)
        if int(row['nTypeParam']) in attributes:
            factor*=max(D(0),1+D(row['fEffectValA']))
    return factor


def apply_passives(stats, info):
    for skill in passive_ids(info):
        row = table_row('BuffTemplate_table.xml',nBuffId=skill)
        attr = int(row['nTypeParam'])
        field = PASSIVE_ATTRIBUTES[attr]
        value, amount = D(stats[field]), D(row['fEffectValA'])
        if attr == 10:
            stats[field] = str(max(1,round(value/(1+amount))))
        elif attr in (8,9):
            # Native tooltip: own penetration + percentage, plus flat points.
            stats[field] = str(value*(1+D(row['fFixParam']))+amount)
        elif int(row['iValType']) == 1:
            stats[field] = str(value+amount)
        else:
            stats[field] = str(value*(1+amount))


def spawn_passives(actor, now):
    if not build(actor): return []
    packets = []
    for template in passive_ids(actor.info):
        if not actor.has_buff(template,now):
            packets += actor._buff(template,now)
    return packets


def active(actor):
    return build(actor).get('1')


def command(build):
    item=build.get('1')
    return (item['group'] << 4) | item['level'] if item else 0


def slot(actor, now):
    item=active(actor)
    if not item:return None
    skill,end=item['skill'],getattr(actor,'guild_ready_at',0)
    if item['group']==2750 and actor.has_buff(511201,now):
        skill,end=511210,actor.buff_started[511201]+1000
    return props(skill,4,end=end)


def notify(actor, now, changed=False):
    body=slot(actor,now)
    return [] if body is None else [(1579,body) if changed and actor.id==1 else (1572,body+struct.pack('<I',actor.id))]


def line(actor, target, now):
    start,end=actor.position_at(now),target.position_at(now)
    exclude=(target.map_rect,) if hasattr(target,'map_rect') else ()
    return (actor.arena.geometry.wall_contact(start,end,exclude=exclude) is None
            and rect_contact(start,end,actor.arena.water_rects(now)) is None)


def target_for(actor, ident, radius, now):
    from bot_ai import team_visible
    target=actor.arena.actors.get(ident)
    if (not target or not target.alive or target.camp==actor.camp or target.is_untargetable()
            or math.dist(actor.position_at(now),target.position_at(now))>radius
            or not line(actor,target,now) or not team_visible(actor.arena,actor,target,now)):
        return None
    return target


def nearby(actor, radius, now, allies=False, tanks=False):
    return [a for a in list(actor.arena.actors.values()) if a.alive
            and (a.camp==actor.camp)==allies and (not tanks or not a.info.get('npc_template'))
            and (not a.in_stasis() if allies else a.is_area_targetable())
            and math.dist(actor.position_at(now),a.position_at(now))<=radius and line(actor,a,now)]


def mobile_npc(target):
    return (target.info.get('npc_template') and not any(target.info.get(k)
            for k in ('map_object','map_turret','totem','cow','bomb_cart','base_main'))
            and int(target.stats.get('iSpeed',0))>0)


def cast(actor, dest, ident, now):
    item=active(actor)
    if not item or not actor.alive or actor.in_stasis():return []
    if getattr(actor,'dracula_ritual',None) or getattr(actor,'caocao_hostage',None):return []
    group,skill=item['group'],item['skill']
    if group==2750 and actor.has_buff(511201,now):
        if now<actor.buff_started[511201]+1000:return []
        packets=[]
        for buff in (511201,511202,511203,511204):packets+=actor.remove_buff(buff,now)
        return packets+notify(actor,now,True)
    if now<getattr(actor,'guild_ready_at',0):return []
    # Purify is explicitly usable while controlled, but never during suppression.
    if group!=2300 and (actor.blocked('attack',now) or actor.skill_sealed(4,now)):return []
    row=table_row('SkillTemplate_table.xml',nId=skill)
    target=None
    if group in (2000,2400,3200):
        target=target_for(actor,ident,int(row['iRange']),now)
        if target is None:return []
        if group==3200 and target.info.get('npc_template') and not mobile_npc(target):return []
    if group==3000 and actor.blocked('move',now):return []
    from military_rank import cooldown_rate
    actor.guild_ready_at=now+max(0,round(D(row['iCoolTime'])*max(D(0),1+cooldown_rate(actor))))
    start=actor.position_at(now)
    packets=[scene(skills=(actor._skill_event(skill,start,target.position_at(now) if target else dest if group==3000 else start,
                                             target.id if target else actor.id,ready=int(row.get('iReadyTime',0))>0),))]
    effect=int(row['fEffect'])
    if group==1100:
        for ally in nearby(actor,192,now,allies=True,tanks=True):
            packets+=ally.restore_hp(ally.max_hp*D('.15'),now)+actor._buff(510110,now,ally.id)
    elif group==1500:
        shield=table_row('BuffTemplate_table.xml',nBuffId=effect)
        packets+=actor.add_shield(effect,D(shield['fEffectValA'])+D(shield['fFixParam'])*actor.max_hp,now)
    elif group in (1800,1900):
        packets+=actor._buff(effect,now)
    elif group==2000:
        packets+=actor._buff(effect,now,target.id)+actor._buff(510610,now,target.id)
        if target.has_buff(effect,now):
            for tick in range(1,6):
                actor._queue(now+1000*tick,'guild_bleed',target.id,target.generation,effect,
                             target.buff_versions[effect],actor.generation,target.max_hp*D('.03'))
    elif group==2300:
        packets+=actor.cleanse(now)+actor._buff(510711,now)+actor._buff(510720,now)
    elif group==2400:
        for buff in (effect,effect+10,effect+20,effect+30,510841):
            packets+=actor._buff(buff,now,target.id)
    elif group==2600:
        packets+=actor._buff(510901,now)+actor._buff(510911,now)
    elif group==2700:
        packets+=actor._buff(511101,now)+actor._buff(511111,now)
        for enemy in nearby(actor,240,now):
            if not enemy.cc_immune(now) and not enemy.effect_blocked():
                origin,stopped=prepare_displacement(enemy,now)
                packets+=stopped
                length=math.dist(start,origin)
                end=tuple(round(a+(b-a)*(1+240/length)) for a,b in zip(start,origin)) if length else (origin[0]+240,origin[1])
                enemy.forced_until=now+enemy._set_motion(origin,end,720,now,kind=1)
                packets.append(scene(moves=(enemy._move_event(enemy.motion[1],720,1),)))
            packets+=actor._buff(511113,now,enemy.id)
    elif group==2750:
        for buff in (511201,511202,511203,511204):packets+=actor._buff(buff,now)
        actor._queue(now+3000,'guild_stasis_end',actor.generation)
    elif group==2900:
        packets+=actor._buff(510501,now)+actor._buff(510510,now)
    elif group==3000:
        from melee_common import aimed
        dest=actor.blink_destination(start,aimed(start,dest,288))
        actor._queue(now+50,'guild_blink',actor.generation,dest)
    elif group==3100:
        for enemy in nearby(actor,192,now,tanks=True):
            packets+=actor.damage(max(D(0),enemy.max_hp-enemy.hp)*D('.2'),now,target=enemy,school='true')[0]
    elif group==3200:
        packets+=actor._buff(511501,now,target.id)
        if not target.info.get('npc_template'):packets+=actor._buff(511511,now,target.id)
        packets+=actor.damage(D(2000) if target.info.get('npc_template') else target.max_hp*D('.05'),
                              now,target=target,school='true')[0]
    elif group==3300:
        # Clamp at now: leftover reduction never pays a second charge or E2 gap.
        if hasattr(actor,'e_next_charge'):
            if actor.e_next_charge:actor.e_next_charge=max(now,actor.e_next_charge-10000)
            packets+=actor.update(now)
        else:
            actor.cooldowns[1]=max(now,actor.cooldowns[1]-10000)
        packets.append(actor._cooldown(1))
    else:
        raise ValueError(f'Unknown Guild skill group {group}')
    return packets+notify(actor,now,group==2750)


def event(actor, now, kind, data):
    if kind=='guild_bleed':
        ident,generation,buff,version,source_generation,raw=data
        target=actor.arena.actors.get(ident)
        if (target and target.alive and target.generation==generation
                and target.buff_versions.get(buff)==version):
            return actor.damage(raw,now,target=target,school='true',periodic=True,source_generation=source_generation)[0]
    elif kind=='guild_blink':
        generation,dest=data
        if actor.alive and actor.generation==generation and not actor.blocked('move',now) and not actor.skill_sealed(4,now):
            actor.position,actor.motion=actor.blink_destination(actor.position_at(now),dest),None
            return [stop_move(actor.scene_id,actor.id,actor.position)]
    elif kind=='guild_stasis_end' and actor.generation==data[0]:
        return notify(actor,now,True)
    elif kind=='guild_extra':
        from map_objects import launch_extra
        return launch_extra(actor,data[0],now)
    return []


def break_stealth(actor, now):
    packets=[]
    for buff in (510501,510510):
        if actor.has_buff(buff,now):packets+=actor.remove_buff(buff,now)
    return packets


def extra_shots(actor, flight, now):
    mode=105 if actor.has_buff(510401,now) else 106 if actor.has_buff(510301,now) else None
    if mode is None or not actor.alive or actor.info.get('npc_template'):return []
    if (not flight['basic'] or flight['proc'] or flight['reflected'] or flight['target'] is not None
            or flight['hits'] or flight['template']==386100):return []
    base=table_row('TankBaseTemplate_table.xml',nTankId=actor.info['tank_id'])
    if flight['template']!=int(base['nBullet']):return []
    for buff in actor.buff_started:
        if buff in (203,204,510301,510401) or not actor.has_buff(buff,now):continue
        if int(table_row('BuffTemplate_table.xml',nBuffId=buff)['nEffectType']) in (24,25,52):return []
    if getattr(actor,'guild_shot',None)==flight['attack_key']:return []
    actor.guild_shot=flight['attack_key']
    from map_objects import launch_extra
    packets=[]
    for i in (1,2):
        extra=dict(flight,id=actor._new_id(2),hits=set(),source_generation=actor.generation)
        if mode==105:
            angle=math.atan2(flight['end'][1]-flight['start'][1],flight['end'][0]-flight['start'][0])+math.radians(-15 if i==1 else 15)
            length=math.dist(flight['start'],flight['end'])
            extra['end']=tuple(round(v) for v in (flight['start'][0]+length*math.cos(angle),flight['start'][1]+length*math.sin(angle)))
            packets+=launch_extra(actor,extra,now)
        else:actor._queue(now+i*100,'guild_extra',extra)
    return packets
