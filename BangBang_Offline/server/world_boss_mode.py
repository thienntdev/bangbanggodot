"""Reviewed first World Boss: private arena, authoritative shared HP ledger."""
import math
import struct

from combat_geometry import point_at, rect_contact
from combat_math import D
from combat_protocol import scene, props, stop_move
from melee_common import in_strip
from pve_npc import PveNpc
from pve_shots import targets
from world_boss_store import MAP, MAX_HP

ENERGY_FLAT = (0, 400, 600, 800, 1000, 1500, 2000, 2500)
# HTML5 user balance 2026-11-15: exactly 100 physical and energy armor.
# Keep source tables intact; bears and other PvE NPCs retain their own stats.
MAIN_ARMOR = D(100)


def install(arena, now):
    meta = arena.state['battle']['world_boss']
    ready = now + 3000
    arena.pk = dict(begin=ready, end=now+meta['remaining_ms'], intro_until=ready,
        intro_buffs=[(1, arena.new_id(6), arena.new_id(6), arena.new_id(6))],
        finished=False, winner=0, scores={1: 0, 2: 0}, stats={1: [0]*21},
        world_boss=dict(damage=D(0), boss=None, energy=0, energy_end_at=0, beam=None,
            spawns=[dict(point=1, spawn_due_at=ready+1000),
                    dict(point=33, spawn_due_at=ready+10000), dict(point=37, spawn_due_at=ready+10000)]))
    arena.queue(ready, arena.player.on_spawn)
    arena.queue(ready, arena._map_tick)


def record_hp(arena, target, before):
    if arena.pk['finished'] or not target.info.get('world_boss_main'):
        return
    loss = max(D(0), before-target.hp)
    credit = getattr(target, 'damage_credit', None)
    source = arena.actors.get(credit[0]) if credit else None
    if not loss or not source or source.generation != credit[1] or source.camp == target.camp:
        return
    owner = source if source is arena.player else arena.actors.get(source.info.get('owner'))
    if owner is arena.player and source.camp == owner.camp:
        arena.pk['world_boss']['damage'] += loss


def spawn(arena, point, now, *, summoned=False):
    definition = next(r for r in arena.geometry.data['world_boss_spawns'] if r['point'] == point)
    old = next((a for a in arena.actors.values() if a.info.get('world_boss_npc') and not a.alive
                and a.info.get('point')==point and a.info.get('summoned',False)==summoned), None)
    ident = old.id if old else arena.new_id(5)
    info = dict(point=point, npc_template=10001 if point==1 else 20004, world_boss_npc=True, summoned=summoned)
    generation = old.generation+1 if old else 0
    if old:
        # Stable small pool for an unlimited-respawn event. Old callbacks keep
        # their generation/buff IDs and cannot hit the newly spawned life.
        for key in list(arena.active_buffs):
            if key[0]==old.id:del arena.active_buffs[key]
        old.__init__(arena,ident,info,2,tuple(definition['position']))
        npc=old
        arena.bot_brains.pop(ident,None)
    else:
        npc=WorldBossNpc(arena,ident,info,2,tuple(definition['position']))
    npc.generation=generation
    npc.wb_cycle_at = now + 8000
    npc.wb_life_end_at = now+30000 if summoned else 0
    if point == 1:
        arena.pk['world_boss']['boss'] = ident
        npc.hp = D(arena.state['battle']['world_boss']['hp']) / 1000
        npc.info['hp'] = math.ceil(npc.hp)
    arena.actors[ident] = npc
    return [npc.snapshot(now)]


def synchronize(arena, row, wall_now):
    """Other arenas' damage is an authoritative correction, never a local hit."""
    if arena.pk['finished']:
        return []
    meta = arena.state['battle']['world_boss']
    if row['id'] != meta['round_id'] or row['closed_ms'] is not None:
        return finish(arena, arena.clock())
    arena.pk['end'] = arena.clock() + max(0, row['end_ms']-wall_now)
    meta.update(hp=row['hp'], remaining_ms=max(0, row['end_ms']-wall_now))
    boss = arena.actors.get(arena.pk['world_boss']['boss'])
    # Local damage has already been submitted by the preceding checkpoint.
    if boss and boss.alive and boss.hp != D(row['hp'])/1000:
        boss.hp = D(row['hp'])/1000
        boss.info['hp'] = math.ceil(boss.hp)
        return [boss._hp_packet(boss.id, boss.hp)]
    return []


def death(arena, victim, now):
    wb = arena.pk['world_boss']
    if victim is arena.player:
        arena.pk['stats'][1][0] += 1
        return clear_energy(arena, now)
    if victim.info.get('world_boss_main'):
        return []  # Global ledger closes the round after committing this hit.
    if not victim.info.get('world_boss_npc'):
        return []
    from map_objects import item_packet
    item = dict(id=arena.new_id(4), template=483, pos=victim.position_at(now), end=now+12000)
    arena.pk.setdefault('drops', {})[item['id']] = item
    if not victim.info.get('summoned'):
        wb['spawns'].append(dict(point=victim.info['point'], spawn_due_at=now+10000))
    return [item_packet(arena, item)]


def finish(arena, now):
    if arena.pk['finished']:
        return []
    packets = clear_energy(arena, now)
    arena.pk.update(finished=True, elapsed=max(0, (now-arena.pk['begin'])//1000))
    for actor in arena.actors.values():
        actor.position, actor.motion = actor.position_at(now), None
    arena.pending.clear()
    arena.state['room']['state'] = 0
    # Native MAPT_BOSS exits to its activity window/main; no PvP/PvE settlement.
    return packets + [(1707, struct.pack('<IIIII', 0, arena.scene_id,
                                         arena.player.info['acct_id'], 1, 0))]


def energy_level(actor, now):
    if actor.arena.geometry.id != MAP or actor is not actor.arena.player or not actor.arena.pk:
        return 0
    wb = actor.arena.pk['world_boss']
    return min(7, wb['energy']) if actor.alive and wb['energy_end_at'] > now else 0


def beam_active(actor, now):
    if actor.arena.geometry.id != MAP or actor is not actor.arena.player or not actor.arena.pk:
        return False
    beam = actor.arena.pk['world_boss']['beam']
    return bool(beam and beam['end'] > now and actor.alive and beam['generation']==actor.generation)


def replacement(actor):
    """Native NotifyChangeSlotSkill accepts PropsInfo; keep tank's timers server-side."""
    wb = actor.arena.pk['world_boss']
    if wb['energy'] >= 8:
        return (1579, props(1020099, 1, 1, 0, 0))
    return (1579, actor._cooldown(1)[1][:22])


def clear_energy(arena, now):
    wb = arena.pk['world_boss']; player = arena.player
    replaced = wb['energy'] >= 8
    beam = wb['beam']
    wb.update(energy=0, energy_end_at=0, beam=None)
    packets = []
    if beam:
        packets.append(scene(expired_bullets=(struct.pack('<I', beam['visual']),)))
    for template in (*range(483,491),10200994):
        packets += player.remove_buff(template, now)
    if replaced:
        packets += [replacement(player), player._cooldown(1)]
    return packets


def collect_energy(arena, now):
    wb = arena.pk['world_boss']; player = arena.player
    if wb['energy'] >= 8:
        return []
    packets = []
    for template in range(483,490):
        packets += player.remove_buff(template, now)
    wb['energy'] += 1
    wb['energy_end_at'] = now+120000
    packets += player._buff(482+wb['energy'], now, duration=120000)
    if wb['energy'] == 8:
        packets.append(replacement(player))
    return packets


def cast_energy(actor, dest, now):
    arena = actor.arena; wb = arena.pk['world_boss']
    if (wb['energy'] != 8 or wb['energy_end_at'] <= now or not actor.alive
            or actor.blocked('attack', now) or actor.skill_sealed(1, now) or wb['beam']
            or actor.forced_until > now or actor.motion and actor.motion_kind and actor.motion[3] > now):
        return []
    start = actor.position_at(now)
    if start == dest or not arena.geometry.inside(dest):
        return []
    # Interrupt old tank channels cleanly; do not consume its E/cooldown/charges.
    packets = actor.interrupt(now)
    actor.position, actor.motion = start, None
    end = tuple(round(v) for v in point_at(start, dest, 1000/math.dist(start,dest)))
    beam = wb['beam'] = dict(start=start, dest=end, end=now+3530, generation=actor.generation,
                            visual=actor._new_id(2))
    packets += [stop_move(arena.scene_id, actor.id, start),
                scene(skills=(actor._skill_event(1020099,start,end,ready=1),))]
    packets += actor._buff(10200994, now, duration=3530)
    actor._queue(now+200,'world_boss_beam',beam,0)
    actor._queue(now+3530,'world_boss_beam_end',beam)
    return packets


def player_event(actor, now, kind, data):
    beam = data[0]; arena = actor.arena
    if (arena.pk['world_boss']['beam'] is not beam or arena.pk['finished']
            or not actor.alive or actor.generation != beam['generation']):
        return []
    if kind == 'world_boss_beam_end':
        return clear_energy(arena,now)
    index = data[1]
    # Native CONTINUE (iMultiType=1) executes one finite movie per pulse.
    # The ready notification only plays exhibit566; fire1020099 has no
    # bullet exhibit, so it cannot replace these execute558 notifications.
    # Emit independently of hits, as for other source CONTINUE skills.
    packets = [scene(skills=(actor._skill_event(1020099,beam['start'],beam['dest']),))]
    if not index:
        packets.append(scene(fires=(struct.pack('<IIhhhhhI',beam['visual'],actor.id,
            *beam['start'],*beam['dest'],32767,1020099),)))
    for target in targets(actor,beam['start'],1036,now):
        if in_strip(target.position_at(now),beam['start'],beam['dest'],1000,144):
            packets += actor.damage(D(10000),now,target=target,school='true')[0]
    if index < 29:
        actor._queue(now+111,'world_boss_beam',beam,index+1)
    return packets


def _patrol(actor, now):
    data = actor.arena.geometry.data
    definition = next(r for r in data['world_boss_spawns'] if r['point']==actor.info['point'])
    nodes = next(g['points'] for g in data['world_boss_logic'] if g['id']==definition['logic'])
    pos = actor.position_at(now)
    if not actor.route_queue:
        node = next((r for r in nodes if r['id']==actor.route_point), None)
        if not node or not node['next']:
            return pos
        choices = [i for i in node['next'] if i!=actor.route_previous] or node['next']
        end = actor.arena.rng.choice(choices)
        edge = next((p for p in data['pve_paths'] if set(p['ends'])=={actor.route_point,end}), None)
        if edge:
            points = edge['points'] if edge['ends'][0]==actor.route_point else list(reversed(edge['points']))
            actor.route_queue = [tuple(p) for p in points if actor.arena.geometry.can_walk_to(tuple(p))]
        actor.route_previous, actor.route_point = actor.route_point, end
    while actor.route_queue and math.dist(pos,actor.route_queue[0]) < 24:
        actor.route_queue.pop(0)
    return actor.route_queue[0] if actor.route_queue else pos


def tick(arena, now):
    wb = arena.pk['world_boss']; packets = []
    if wb['energy'] and wb['energy_end_at'] <= now and not wb['beam']:
        packets += clear_energy(arena, now)
    for ident,item in list(arena.pk.setdefault('drops',{}).items()):
        if item['template'] != 483: continue
        collect = (wb['energy'] < 8 and arena.player.alive and not arena.player.in_stasis()
                   and math.dist(arena.player.position_at(now),item['pos']) <= 60)
        if now >= item['end'] or collect:
            if collect and now < item['end']: packets += collect_energy(arena, now)
            del arena.pk['drops'][ident]
            packets.append(scene(removed=(struct.pack('<I',ident),)))
    waiting = []
    for record in wb['spawns']:
        if record['spawn_due_at'] <= now:
            packets += spawn(arena,record['point'],now)
        else: waiting.append(record)
    wb['spawns'] = waiting
    from bot_ai import observable, walk, stop
    for actor in list(arena.actors.values()):
        if not actor.info.get('world_boss_npc') or not actor.alive: continue
        if actor.wb_life_end_at and actor.wb_life_end_at <= now:
            actor.hp=D(0); actor.info['hp']=0; actor.motion=None
            packets.append(scene(removed=(struct.pack('<I',actor.id),)))
            continue  # Expiry is not a kill: no energy and no respawn.
        boss = actor.info['world_boss_main']
        if boss and now >= actor.wb_cycle_at:
            packets += actor.special(now)
        if now < actor.wb_cast_until or now < actor.wb_weak_until:
            packets += stop(actor,now)
            continue
        brain = arena.bot_brains.setdefault(actor.id,dict(path=[],notice_at=0))
        if now >= brain['notice_at']:
            brain['notice_at']=now+200
            seen=[a for a in arena.actors.values() if observable(arena,actor,a,now,2000 if boss else 600)]
            target=min(seen,key=lambda a:(math.dist(actor.position_at(now),a.position_at(now)),a.id),default=None)
            pos=actor.position_at(now)
            if target:
                dest=target.position_at(now)
                in_range=math.dist(pos,dest) <= (2000 if boss else 100)
                brain['goal']=_patrol(actor,now) if boss else pos if in_range else dest
                if in_range:packets+=actor.cast(0,pos,dest,target.id,now)
            else:brain['goal']=_patrol(actor,now)
        if brain.get('goal') is not None:
            packets += walk(arena,actor,brain,brain['goal'],now)
    return packets


def resume(arena, now):
    wb=arena.pk['world_boss']; actor=arena.player; packets=[]
    if wb['energy']>=8:packets.append(replacement(actor))
    beam=wb['beam']
    if beam and beam['end']>now and actor.alive and actor.generation==beam['generation']:
        packets.append(scene(fires=(struct.pack('<IIhhhhhI',beam['visual'],actor.id,
            *beam['start'],*beam['dest'],32767,1020099),)))
    for _,_,callback,args in arena.pending:
        if callback.__name__=='_event' and args[0]=='world_boss_laser':
            source=callback.__self__;start,dest,generation=args[1]
            if source.alive and generation==source.generation:
                packets.append(scene(skills=(source._skill_event(1020095,start,dest,ready=1),)))
    return packets


class WorldBossNpc(PveNpc):
    def __init__(self,arena,ident,info,camp,spawn):
        super().__init__(arena,ident,info,camp,spawn)
        self.info.update(world_boss_npc=True, world_boss_main=info['npc_template']==10001)
        if self.info['world_boss_main']:
            self.hp=self.max_hp=D(MAX_HP)
            self.stats['iHp']=str(MAX_HP)
            for key in ('iArmor', 'iEgArmor'):
                self.stats[key]=str(MAIN_ARMOR)
            self.info.update(hp=MAX_HP,max_hp=MAX_HP)
        self.wb_cycle_at=0; self.wb_phase=0
        self.wb_cast_until=0; self.wb_weak_until=0; self.wb_life_end_at=0
        self.pve_fire_range=2000 if self.info['world_boss_main'] else 100

    def cc_immune(self,now,*,slow=False):
        return self.info['world_boss_main'] or super().cc_immune(now,slow=slow)

    def restore_hp(self,amount,now):
        return [] if self.info['world_boss_main'] else super().restore_hp(amount,now)

    def commit_hp(self,hp,now,*,critical=False):
        if self.info['world_boss_main'] and hp>self.hp:return []
        return super().commit_hp(hp,now,critical=critical)

    def combat_stat(self,key,now):
        if key in ('iArmor','iEgArmor') and now<getattr(self,'wb_weak_until',0):return D(0)
        return super().combat_stat(key,now)

    def cast(self,slot,start,dest,target,now):
        if (slot or not self.alive or self.blocked('attack',now) or self.skill_sealed(0,now)
                or self.cooldowns[0]>now or now<self.wb_cast_until or now<self.wb_weak_until):return []
        target=self.arena.actors.get(target)
        if not target or not target.alive:return []
        self.cooldowns[0]=now+(2000 if self.info['world_boss_main'] else 1500)
        if self.info['world_boss_main']:
            packets=self.shoot(1020092,start,dest,now,target.max_hp*D('.05'),school='true',basic=True)
            # Tag the just-created flight, preserving native collision/defenses.
            for _,_,cb,args in reversed(self.arena.pending):
                if cb.__self__ is self and args and args[0]=='flight' and args[1][0]['begin']==now:
                    args[1][0]['hp_fraction']=D('.05')
            return packets
        if math.dist(start,target.position_at(now))>100 or target not in list(targets(self,start,100,now)):return []
        return [scene(skills=(self._skill_event(1020098,start,dest,target.id),))]+self.damage(
            target.max_hp*D('.1'),now,target=target,school='true',basic=True)[0]

    def on_bullet_hit(self,flight,target,now):
        if flight['template']!=1020092 or not target.alive:return []
        packets=self._buff(10200921,now,target.id,duration=5000)
        if target.has_buff(10200921,now):
            self._queue(now+1000,'world_boss_burn',target.id,target.generation,
                        target.buff_versions[10200921],5,self.generation)
        return packets

    def special(self,now):
        from bot_ai import observable,stop
        phase=self.wb_phase;self.wb_phase=(phase+1)%5;self.wb_cycle_at+=8000
        if phase==4:
            self.wb_weak_until=now+5000
            return stop(self,now)+self._buff(10200961,now,duration=5000)+self._buff(10200962,now,duration=5000)+self._buff(10200963,now,duration=5000)
        seen=[t for t in self.arena.actors.values() if observable(self.arena,self,t,now,2000)]
        target=min(seen,key=lambda t:(math.dist(self.position_at(now),t.position_at(now)),t.id),default=None)
        if target is None:return []
        start=self.position_at(now);dest=target.position_at(now)
        delay=(500,1000,1000,1000)[phase]
        self.wb_cast_until=now+delay
        packets=stop(self,now)
        if phase==0:
            positions=[dest]
            for _ in range(4):
                candidates=[(x,y) for x in range(108,self.arena.geometry.width-108,72)
                                  for y in range(108,self.arena.geometry.height-108,72)
                                  if self.arena.geometry.can_walk_to((x,y)) and (x,y) not in positions]
                if candidates:positions.append(self.arena.rng.choice(candidates))
            for pos in positions:
                ident,packet=self.add_object(10200931,pos);packets.append(packet)
                self._queue(now+500,'world_boss_quake',pos,ident,self.generation)
        elif phase==1:
            packets.append(scene(skills=(self._skill_event(1020095,start,dest,ready=1),)))
            self._queue(now+1000,'world_boss_laser',start,dest,self.generation)
        elif phase==2:
            packets.append(scene(skills=(self._skill_event(1020094,start,start,ready=1),)))
            self._queue(now+1000,'world_boss_summon',self.generation)
        else:
            ident,packet=self.add_object(10200931,dest);packets.append(packet)
            self._queue(now+1000,'world_boss_hole_start',dest,ident,self.generation)
        return packets

    def _event(self,now,kind,data):
        if not kind.startswith('world_boss_'):return super()._event(now,kind,data)
        if self.arena.pk['finished']:return []
        if kind=='world_boss_burn':
            ident,gen,version,left,source_gen=data;target=self.arena.actors.get(ident)
            if not target or not target.alive or target.generation!=gen or target.buff_versions.get(10200921)!=version:return []
            packets=self.damage(target.max_hp*D('.03'),now,target=target,school='true',periodic=True,source_generation=source_gen)[0]
            if left>1:self._queue(now+1000,kind,ident,gen,version,left-1,source_gen)
            return packets
        if kind=='world_boss_hole':
            cast,=data
            if not self.alive or self.generation!=cast['generation'] or now>cast['end']:
                return self.remove_object(cast['visual'],destroyed=True)
            packets=[]
            for target in targets(self,cast['pos'],600,now):
                packets+=self.damage(target.max_hp*D('.175'),now,target=target,school='true',periodic=True)[0]
                key=(target.id,target.generation)
                if target.alive and key not in cast['hit']:
                    cast['hit'].add(key);packets+=self._buff(10200973,now,target.id,duration=2000)
            if now<cast['end']:self._queue(now+500,kind,cast)
            else:packets+=self.remove_object(cast['visual'],destroyed=True)
            return packets
        if not self.alive or self.generation!=data[-1]:return []
        if kind=='world_boss_summon':
            return spawn(self.arena,33,now,summoned=True)+spawn(self.arena,37,now,summoned=True)
        if kind=='world_boss_quake':
            pos,visual,_=data;packets=self.remove_object(visual,destroyed=True)
            ident,packet=self.add_object(10200932,pos);packets.append(packet);self._queue(now+500,'object_expire',ident)
            for target in targets(self,pos,144,now):
                packets+=self.damage(target.max_hp*D('.1'),now,target=target,school='true')[0]
                if target.alive:packets+=self._buff(10200936,now,target.id,duration=5000)
            return packets
        if kind=='world_boss_laser':
            start,dest,_=data
            if start==dest:return []
            end=tuple(round(v) for v in point_at(start,dest,524/math.dist(start,dest)))
            ident=self._new_id(2)
            packets=[scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*end,32767,1020095),))]
            self._queue(now+200,'pve_laser_end',ident)
            for target in targets(self,start,560,now):
                if in_strip(target.position_at(now),start,end,524,96):
                    packets+=self.damage(target.max_hp*D('.4'),now,target=target,school='true')[0]
            return packets
        if kind=='world_boss_hole_start':
            pos,visual,_=data;packets=self.remove_object(visual,destroyed=True)
            ident,packet=self.add_object(10200971,pos);packets.append(packet)
            cast=dict(pos=pos,visual=ident,generation=self.generation,end=now+5000,hit=set())
            self._queue(now+500,'world_boss_hole',cast)
            return packets
        return []
