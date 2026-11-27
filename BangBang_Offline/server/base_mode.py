"""Approved map50 base rules, authored Robot waves and visible-information goals."""
import math
import struct

from robo_actions import RoboActions
from combat_math import D
from combat_geometry import actor_contact,point_at,rect_contact
from combat_protocol import scene


class BaseRobot(RoboActions):
    shot_skill=1000165
    shot_interval=2400

    def __init__(self,arena,ident,info,camp,spawn):
        info=dict(info)
        info.setdefault('wave_index',next(i for i,d in enumerate(arena.geometry.data['base_waves']) if d['point']==info['point']))
        info.pop('paths',None);info.pop('logic',None)
        super().__init__(arena,ident,info,camp,spawn)
        self.info.pop('robo',None)
        self.info.update(base_robot=True,name='Robot Siêu Cấp',hp=2598,max_hp=2598)
        self.stats.update(iHp='2598',iAttack='730.8',iEgAtk='730.8',iArmor='191',
                          iEgArmor='191',iSpeed='90',nFireRange='650',iFireInterv='2400')
        self.hp=self.max_hp=D(2598);self.last_speed=90

    def _respawn(self,now,generation):return []

    def cast(self,slot,start,dest,target,now):
        if slot or not self.alive or self.blocked('attack',now) or self.cooldowns[0]>now or start==dest:return []
        self.cooldowns[0]=now+self.shot_interval
        # Fixed aim, constant speed; neither chase the target nor extend beyond it.
        speed=217;duration=max(1,round(math.dist(start,dest)*1000/speed));ident=self._new_id(2)
        dest=tuple(round(v) for v in dest)
        flight=dict(kind='bullet',id=ident,template=self.shot_skill,start=start,end=dest,pos=start,
                    begin=now,finish=now+duration,previous=now,raw=D('730.8'),school='physical',basic=True,
                    speed=speed,source_generation=self.generation,through_walls=False,
                    attack_key=(self.id,self.generation,self.shot_skill,ident))
        self._queue(now+min(20,duration),'flight',flight)
        return [scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*dest,speed,self.shot_skill),))]

    def _flight(self,flight,now):
        span=flight['finish']-flight['begin']
        start=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/span)
        end=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/span))
        targets=[a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp and not a.is_untargetable()]
        contacts=[(h,a.id,a) for a in targets if (h:=actor_contact(start,end,a,flight['previous'],now)) is not None]
        hit,_,target=min(contacts,key=lambda r:r[:2]) if contacts else (None,0,None)
        wall=self.arena.geometry.wall_contact(start,end)
        contact=hit is not None and (wall is None or hit<=wall)
        if contact and self.projectile_blocked(target,now):
            return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        if contact or wall is not None or now>=flight['finish']:
            fraction=hit if contact else wall if wall is not None else 1
            pos=point_at(start,end,fraction);packets=[]
            for target in targets:
                if not target.is_area_targetable() or math.dist(pos,target.position_at(now))>90:continue
                exclude=(target.map_rect,) if target.info.get('map_object') else ()
                if self.arena.geometry.wall_contact(pos,target.position_at(now),exclude=exclude) is not None:continue
                if rect_contact(pos,target.position_at(now),self.arena.water_rects(now)) is not None:continue
                raw=flight['raw']*(D('1.5') if target.info.get('base') or target.info.get('map_turret') else 1)
                packets+=self.damage(raw,now,target=target,school='physical',basic=True,
                                     source_generation=flight['source_generation'],attacker_ap=flight['raw'])[0]
            packets.append(scene(blown_bullets=(struct.pack('<I',flight['id']),)))
            return packets
        flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight)
        return []


def install(arena):
    for actor in arena.actors.values():
        if not actor.info.get('npc_template'):actor.info.update(battle_level=1,battle_exp=0)
    arena.pk['base_waves']=[dict(wave_index=i,wave_due_at=arena.pk['begin']+d['begin_seconds']*1000)
                            for i,d in enumerate(arena.geometry.data['base_waves'])]


def tick(arena,now):
    packets=[]
    for wave in arena.pk['base_waves']:
        if now<wave['wave_due_at']:continue
        d=arena.geometry.data['base_waves'][wave['wave_index']];ident=arena.new_id(5)
        robot=BaseRobot(arena,ident,dict(d),d['camp'],tuple(d['position']))
        arena.actors[ident]=robot
        packets.append(robot.snapshot(now))
        wave['wave_due_at']+=d['interval_seconds']*1000
    return packets


def respawn_delay(arena,now):
    """Lock the duration at death; the shared match clock pauses on reload."""
    return min(30000,5000*(1+max(0,now-arena.pk['begin'])//120000))


def firing_position(arena,actor,target,now,*,reach=None):
    """Reachable firing cells, never a solid building's centre or hidden bodies."""
    from bot_ai import Navigation
    if not hasattr(arena,'navigation'):arena.navigation=Navigation(arena.geometry)
    nav=arena.navigation;pos=actor.position_at(now);source=nav.nearest(pos)
    if source is None:return None
    # Reuse static probes until a destructible object changes the map geometry.
    cached=getattr(nav,'siege_cells',None)
    if cached is None or cached[0] is not arena.geometry.walls:
        nav.siege_cells=(arena.geometry.walls,{})
    cache=nav.siege_cells[1];reach=int(actor.stats['nFireRange']) if reach is None else reach
    key=(target.id,reach)
    if key not in cache:
        cells=set()
        for radius in (max(72,reach-36),max(72,reach*.65)):
            for step in range(32):
                angle=step*math.tau/32
                p=tuple(round((v-12)/24)*24+12 for v in
                        (target.position[0]+math.cos(angle)*radius,target.position[1]+math.sin(angle)*radius))
                if (nav.clear(p,p) and math.dist(p,target.position)<=reach-12 and
                        arena.geometry.wall_contact(p,target.position,12,exclude=(target.map_rect,),bullets=True) is None):
                    cells.add(p)
        cache[key]=sorted(cells)
    reachable=nav.reachable(source)
    cells=[p for p in cache[key] if p in reachable]
    if not cells:
        # Narrow approaches can be entirely inside both sampled rings (map14).
        # Cache a full local grid fallback; range is a maximum, not a minimum.
        near_key=(target.id,reach,'near')
        if near_key not in cache:
            centre=tuple(round((v-12)/24)*24+12 for v in target.position)
            steps=math.ceil(reach/24);near=[]
            for dx in range(-steps,steps+1):
                for dy in range(-steps,steps+1):
                    p=(centre[0]+dx*24,centre[1]+dy*24)
                    if (math.dist(p,target.position)<=reach-12 and nav.clear(p,p) and
                            arena.geometry.wall_contact(p,target.position,12,exclude=(target.map_rect,),bullets=True) is None):
                        near.append(p)
            cache[near_key]=near
        cells=[p for p in cache[near_key] if p in reachable]
    if not cells:return None
    friends=[a.position_at(now) for a in arena.actors.values() if a is not actor and a.alive
             and a.camp==actor.camp and not a.info.get('map_object')]
    # Stay and fire once in range; moving every decision used to spoil sieges.
    if (math.dist(pos,target.position)<=reach-12 and
            arena.geometry.wall_contact(pos,target.position,12,exclude=(target.map_rect,),bullets=True) is None and
            all(math.dist(pos,p)>=64 for p in friends)):
        return pos
    return min(cells,key=lambda p:math.dist(pos,p)+sum(max(0,96-math.dist(p,q))*4 for q in friends))


def goal(arena,actor,seen,now,brain=None):
    """Buildings/routes are public; mobile threats come only from delayed samples."""
    pos=actor.position_at(now)
    homes={a.camp:a for a in arena.actors.values() if a.info.get('base')}
    home=homes[actor.camp]
    if brain is not None:brain.pop('siege_target',None)
    threats=[s for s in seen if not s.get('barrier') and not s.get('structure') and math.dist(s['pos'],home.position)<660]
    if threats:
        team=sorted((a for a in arena.actors.values() if a.alive and a.camp==actor.camp and not a.info.get('npc_template')),
                    key=lambda a:(math.dist(a.position_at(now),home.position),a.id))
        if actor in team[:min(3,len(threats)+1)]:
            return 'base_defend',min(threats,key=lambda s:math.dist(pos,s['pos']))['pos']
    structures=[a for a in arena.actors.values() if a.alive and a.camp!=actor.camp
                and (a.info.get('base') or a.info.get('map_turret')) and not a.turret_locked()]
    enemy_home=homes[3-actor.camp]
    # User-approved order: exposed base, its large tower, then blocking towers.
    # A reachable firing cell proves the small towers can actually be bypassed.
    structures.sort(key=lambda a:(0 if a.info.get('base') else 1 if a.id in enemy_home.unlocked_by else 2,
                                  math.dist(pos,a.position),a.id))
    for target in structures:
        dest=firing_position(arena,actor,target,now)
        if dest is not None:
            if brain is not None:brain['siege_target']=target.id
            return 'base_push',dest
    # No clear firing cell yet: the shared observed-barrier policy opens a path.
    target=structures[0] if structures else enemy_home
    return 'clear_path',target.position


def targets(actor,brain,seen,tanks,allies,objective,now):
    """Only delayed observations can cause a combat target switch."""
    pos=actor.position_at(now)
    if objective and objective[0]=='base_defend':
        return [s for s in seen if not s.get('barrier') and not s.get('structure')
                and math.dist(s['pos'],objective[1])<=360]
    close=[s for s in tanks if math.dist(pos,s['pos'])<=360 or
           (math.dist(pos,s['pos'])<=600 and any(float(a.hp/a.max_hp)<.6 and
            math.dist(a.position_at(now),s['pos'])<=240 for a in allies))]
    if close:return close
    siege=[s for s in seen if s['id']==brain.get('siege_target')]
    if siege:return siege
    # Clear observed blockers/Robot defenders on the way; don't chase remote tanks.
    return [s for s in seen if s.get('barrier') or
            (s.get('objective') and not s.get('structure') and math.dist(pos,s['pos'])<=360)]
