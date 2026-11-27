"""Shared mode strategy and tank policies driven by delayed observations."""
from battle_participants import human, private
import heapq
import math
import struct
from collections import Counter,deque
from functools import lru_cache

from battle_runtime import DIRECTIONS
from combat_geometry import point_at,rect_contact
from combat_protocol import scene
import bot_ai01
import bot_ai02
import bot_ai03
import bot_ai04
import bot_ai05
import bot_ai06
import bot_ai07
import bot_ai08
import bot_ai09
import bot_ai10
import bot_ai11
import bot_ai12
import bot_ai13
import bot_ai14
import bot_ai15
import bot_ai16
import bot_ai17
import bot_ai18
import bot_ai20
import bot_ai19
import bot_obstacles


class Navigation:
    """Native 24-unit walk steps, cached obstacle edges, bounded A* per route."""
    def __init__(self,geometry):
        self.geometry=geometry
        self.clear=lru_cache(maxsize=60000)(self._clear)
        self._nearest_cached=lru_cache(maxsize=2048)(self._nearest)
        self.components={}
        self.walk_cells={}
        self.neighbor_edges={}
        self.removed_objects=Counter()

    def neighbors(self,p):
        if p not in self.neighbor_edges:self.neighbor_edges[p]=self._neighbors(p)
        return self.neighbor_edges[p]

    def remove_obstacles(self,rectangles):
        removed=Counter(rectangles)
        changed=(removed-self.removed_objects)+(self.removed_objects-removed)
        self.removed_objects=removed
        def near(p,padding):
            return any(l-padding<=p[0]<=r+padding and t-padding<=p[1]<=b+padding for l,t,r,b in changed)
        # Destroying or respawning an NPC changes occupancy within its rectangle + tank
        # radius. An edge can reach one more 24px step beyond that region.
        # Counts matter when multiple NPCs share the same rectangle.
        for p in list(self.walk_cells):
            if near(p,36):del self.walk_cells[p]
        for p in list(self.neighbor_edges):
            if near(p,60):del self.neighbor_edges[p]
        self.clear.cache_clear();self.components.clear();self._nearest_cached.cache_clear()

    def _neighbors(self,p):
        return tuple((q,math.hypot(dx,dy)*24) for dx,dy in DIRECTIONS[:8]
                     if self.clear(p,q:=(p[0]+dx*24,p[1]+dy*24)))

    def reachable(self,source):
        if source in self.components:return self.components[source]
        queue=deque([source]);seen={source}
        while queue:
            p=queue.popleft()
            if self.geometry.id in (14,19,70):
                # Same edge order as the original flood fill; unchanged edges
                # survive local obstacle invalidation and can be reused here.
                for q,_ in self.neighbors(p):
                    if q not in seen:seen.add(q);queue.append(q)
            else:
                for dx,dy in DIRECTIONS[:8]:
                    q=p[0]+dx*24,p[1]+dy*24
                    if q not in seen and self.clear(p,q):seen.add(q);queue.append(q)
        component=frozenset(seen)
        for p in component:self.components[p]=component
        return component

    def _clear(self,a,b):
        if (self.geometry.id in (14,19,70) and max(abs(y-x) for x,y in zip(a,b))<=24
                and all(v==round(v) for v in (*a,*b))):
            # Native walking checks the destination cell for a single step.
            # Reuse endpoint checks instead of repeating the same terrain/NPC
            # queries for every incoming edge on the Maya/Robo/escort routes.
            for p in (a,b):
                if p not in self.walk_cells:self.walk_cells[p]=self.geometry.can_walk_to(p)
                if not self.walk_cells[p]:return False
            return True
        return self.geometry.can_walk_to(a) and self.geometry.walk_end(a,b)==b

    def nearest(self,pos):
        return self._nearest_cached(tuple(pos))

    def _nearest(self,pos):
        center=tuple(round((v-12)/24)*24+12 for v in pos)
        choices=[(center[0]+24*x,center[1]+24*y) for x in range(-3,4) for y in range(-3,4)]
        # Stable sort preserves min()'s original tie order, but probes stop at
        # the first legal candidate instead of checking all 49 every time.
        choices.sort(key=lambda p:math.dist(pos,p))
        return next((p for p in choices if self.clear(p,p) and self.clear(pos,p)),None)

    def path(self,start,goal,threats=(),blockers=()):
        source=self.nearest(start);end=self.nearest(goal)
        if source is None:return []
        if end is None:
            # Aim points may be beside a wall; choose a reachable nearby cell.
            center=tuple(round((v-12)/24)*24+12 for v in goal)
            cells=[(center[0]+24*x,center[1]+24*y) for x in range(-6,7) for y in range(-6,7)]
            # A fallback across a sealed obstacle used to trigger an exhaustive
            # failed search every second. Pick only cells connected to the bot.
            reachable=self.reachable(source)
            cells=[p for p in cells if p in reachable]
            if not cells:
                if self.geometry.id not in (12,14,50,169):return []
                # A base can sit behind cover wider than the local probe.
                # Approach its reachable edge so observed blockers can be shot.
                cells=reachable
            end=min(cells,key=lambda p:math.dist(goal,p))
        if blockers and any(math.dist(end,b)<64 for b in blockers):
            # An ally can be holding the exact destination. Route to a nearby
            # free cell instead of exhaustively searching an occupied goal.
            cells=[(end[0]+24*x,end[1]+24*y) for x in range(-6,7) for y in range(-6,7)]
            reachable=self.reachable(source)
            cells=[p for p in cells if p in reachable and all(math.dist(p,b)>=64 for b in blockers)]
            if not cells:return []
            end=min(cells,key=lambda p:math.dist(goal,p))
        def estimate(p):
            dx,dy=abs(p[0]-end[0]),abs(p[1]-end[1])
            return max(dx,dy)+(math.sqrt(2)-1)*min(dx,dy)
        # Exact unobstructed distance on this eight-neighbour grid. Euclidean
        # distance expanded many unnecessary cells on long diagonal routes.
        queue=[(estimate(source),0,source)];cost={source:0};parent={}
        best=source
        # An ally's exclusion disc is local. Nodes far outside all those discs
        # cannot approach it below 64px; avoid repeated distance work there.
        bounds=((min(p[0] for p in blockers)-64,min(p[1] for p in blockers)-64,
                 max(p[0] for p in blockers)+64,max(p[1] for p in blockers)+64)
                if blockers and self.geometry.id in (14,19,70) else None)
        for _ in range(4500):
            if not queue:break
            _,g,p=heapq.heappop(queue)
            if g!=cost[p]:continue
            if math.dist(p,end)<math.dist(best,end):best=p
            if p==end:break
            edges=(self.neighbors(p) if self.geometry.id in (14,19,70) else self._neighbors(p))
            for q,step_cost in edges:
                # Allow already-close allies to separate, but never plan a
                # new step into their spacing. Dynamic bodies are not cached
                # as map terrain and never include hidden enemy positions.
                if (blockers and (bounds is None or bounds[0]<q[0]<bounds[2] and bounds[1]<q[1]<bounds[3])
                        and any(math.dist(q,b)<min(64,math.dist(p,b)) for b in blockers)):continue
                danger=sum(max(0,1-math.dist(q,p)/360) for p in threats) if threats else 0
                ng=g+step_cost+danger*48
                if ng<cost.get(q,float('inf')):
                    cost[q]=ng;parent[q]=p
                    heapq.heappush(queue,(ng+estimate(q),ng,q))
        route=[];p=best
        while p!=source:route.append(p);p=parent[p]
        if self.geometry.id==19:
            # The old Robo search produced fresh coordinate tuples per route.
            # Cached edges must not introduce cross-bot aliases into the graph
            # checkpoint. Keep the existing nearest/source identity below.
            route=[(p[0],p[1]) for p in route]
        route.append(source)
        return list(reversed(route))


def _visible_kind(arena,observer,target,now,*,navigation=False):
    """Target eligibility, shared by the same-camp scouts of one observation."""
    if arena.geometry.id==35 and observer.info.get('robo') and target.info.get('map_object'):
        return None  # Robo keeps map19's combat-target patrol policy.
    turret=(arena.geometry.id in (1,9,10,12,14,17,21,35,36,37,50,70,169,170) and target.info.get('map_turret') or arena.geometry.id in (12,14,50,169) and target.info.get('base'))
    barrier=(arena.geometry.id in (12,14,50,70,169) and target.info.get('map_object') and not turret or arena.geometry.id==21 and target.info.get('energy_barrier') or
                 arena.geometry.id==34 and target.info.get('map_object') and target.info.get('npc_template') in (2034,2035) or
                 arena.geometry.id==35 and target.info.get('npc_template')==2039 and
                 any(math.dist(target.position,p['position'])<300 for p in arena.geometry.data['portals']))
    # Ordinary breakable scenery is usable for navigation on every mode.
    # NPCs keep their authored combat policy; pickups/script gates are excluded.
    barrier=barrier or (navigation and not observer.info.get('npc_template') and getattr(target,'ordinary_obstacle',False))
    if observer.info.get('base_robot') and target.info.get('npc_template') and not (target.info.get('base_robot') or turret):return None
    if target.info.get('map_object') and not (turret or barrier):return None
    if turret and target.turret_locked():return None
    if not target.alive or target.camp==observer.camp or target.is_untargetable():return None
    types=target.buff_types(now)
    if 26 in types and 32 not in types:return None
    return turret,barrier


def _visible_line(arena,observer,target,now,radius,pos,exclude,start=None):
    if start is None:start=observer.position_at(now)
    if arena.geometry.id==40:radius=min(radius,600)
    if math.dist(start,pos)>radius:return False
    if arena.geometry.id in (1,40):
        from maya_map import visible_from
        if not visible_from(arena,observer,target,now):return False
    return arena.geometry.wall_contact(start,pos,exclude=exclude) is None


def observable(arena,observer,target,now,radius=960):
    kind=_visible_kind(arena,observer,target,now)
    if kind is None:return False
    return _visible_line(arena,observer,target,now,radius,target.position_at(now),
                         (target.map_rect,) if any(kind) else ())


def team_visible(arena,actor,target,now):
    """Native target-lock check, also used by human casts; no homing retarget."""
    return any(observable(arena,scout,target,now) for scout in arena.actors.values()
               if scout.alive and scout.camp==actor.camp and not scout.info.get('npc_template'))


def observe(arena,actor,brain,now):
    previous={o['id']:o for o in brain.get('observations',[])}
    scouts=[actor] if (actor.info.get('robo') or actor.info.get('base_robot') or actor.info.get('mascot') or actor.info.get('map_spider')) else [a for a in arena.actors.values() if a.alive and a.camp==actor.camp and not a.info.get('npc_template')]
    # Only this observation: no cast/tick intervenes, and no position cache is
    # shared with the next bot or retained across damage, movement or stealth.
    scouts=[(a,a.position_at(now)) for a in scouts]
    radius=650 if actor.info.get('base_robot') else 600 if actor.info.get('robo') or actor.info.get('mascot') or actor.info.get('map_spider') else 960
    seen=[]
    for target in arena.actors.values():
        # Scouts are either this NPC alone, or only allied tanks. Eligibility
        # is identical across that group; no cache survives this observation
        # (damage, stealth, death and broken walls remain visible immediately).
        kind=_visible_kind(arena,actor,target,now,navigation=True)
        if kind is None:continue
        turret,barrier=kind;pos=target.position_at(now)
        exclude=(target.map_rect,) if turret or barrier else ()
        if not any(_visible_line(arena,a,target,now,radius,pos,exclude,start) for a,start in scouts):continue
        old=previous.get(target.id);velocity=(0,0)
        if old and old['generation']==target.generation:
            dt=max(1,now-old['observed_at'])/1000
            velocity=tuple(max(-400,min(400,(v-u)/dt)) for v,u in zip(pos,old['pos']))
        seen.append(dict(id=target.id,generation=target.generation,pos=pos,velocity=velocity,
                         hp=float(target.hp/target.max_hp),observed_at=now,robo=bool(target.info.get('robo')),
                         objective=bool(target.info.get('robo') or target.info.get('base_robot') or target.info.get('mascot') or target.info.get('totem') or target.info.get('bomb_cart') or turret or barrier)))
        if turret or barrier:seen[-1]['turret_rect']=target.map_rect
        if target.info.get('bomb_cart'):seen[-1]['bomb_cart']=True
        if barrier:seen[-1]['barrier']=True
        if turret:seen[-1]['structure']=True
        if actor.info['tank_id']==10000041:
            seen[-1]['legolas_marks']=actor._stage(target,now)
        if actor.info['tank_id'] in bot_ai03.TANKS:
            seen[-1].update(bot_ai03.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai05.TANKS:
            seen[-1].update(bot_ai05.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai06.TANKS:
            seen[-1].update(bot_ai06.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai09.TANKS:
            seen[-1].update(bot_ai09.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai10.TANKS:
            seen[-1].update(bot_ai10.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai11.TANKS:
            seen[-1].update(bot_ai11.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai12.TANKS:
            seen[-1].update(bot_ai12.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai20.TANKS:
            seen[-1].update(bot_ai20.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai19.TANKS:
            seen[-1].update(bot_ai19.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai18.TANKS:
            seen[-1].update(bot_ai18.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai17.TANKS:
            seen[-1].update(bot_ai17.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai16.TANKS:
            seen[-1].update(bot_ai16.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai15.TANKS:
            seen[-1].update(bot_ai15.observation(actor,target,now))
        if actor.info['tank_id'] in bot_ai13.TANKS:
            seen[-1].update(bot_ai13.observation(actor,target,now))
    return seen


def observe_bullets(arena,actor,now):
    """Sample only visible in-flight projectiles, never an opponent's next cast."""
    if (actor.info.get('robo') or actor.info.get('base_robot') or actor.info.get('mascot') or actor.info.get('map_spider')):return []
    pos=actor.position_at(now);seen=[];ids=set()
    for _,_,callback,args in arena.pending:
        if callback.__name__!='_event' or not args or args[0]!='flight':continue
        shot=args[1][0];source=getattr(callback,'__self__',None)
        if shot.get('kind')!='bullet' or source.camp==actor.camp or shot['id'] in ids:continue
        ids.add(shot['id'])
        if shot.get('target'):
            point=shot['pos']
        else:
            point=point_at(shot['start'],shot['end'],min(1,max(0,(now-shot['begin'])/max(1,shot['finish']-shot['begin']))))
        if math.dist(pos,point)>600 or arena.geometry.wall_contact(pos,point) is not None:continue
        dx,dy=shot['end'][0]-point[0],shot['end'][1]-point[1];length=math.hypot(dx,dy)
        if length:
            speed=shot.get('speed',0)
            seen.append(dict(pos=point,velocity=(dx/length*speed,dy/length*speed),observed_at=now))
    return seen


def evade(arena,actor,brain,now):
    pos=actor.position_at(now)
    for shot in brain.get('bullets',[]):
        vx,vy=shot['velocity'];speed2=vx*vx+vy*vy
        if not speed2:continue
        age=(now-shot['observed_at'])/1000
        bx,by=shot['pos'][0]+vx*age,shot['pos'][1]+vy*age
        arrival=((pos[0]-bx)*vx+(pos[1]-by)*vy)/speed2
        if not 0<arrival<.7 or math.dist(pos,(bx+vx*arrival,by+vy*arrival))>68:continue
        # React with a coarse sidestep; no instantaneous aim or guaranteed dodge.
        speed=math.sqrt(speed2);side=1 if actor.id%2 else -1
        for sign in (side,-side):
            dest=tuple(round(v) for v in (pos[0]-sign*vy/speed*96,pos[1]+sign*vx/speed*96))
            if arena.geometry.walk_end(pos,dest,arena.water_rects(now))==dest:
                brain['goal']=dest;brain['repath_at']=0
                return


def stop(actor,now):
    if actor.motion is None or actor.motion_kind!=0:return []
    actor.position=actor.position_at(now);actor.motion=None
    return [(1554,struct.pack('<IIhh',actor.scene_id,actor.id,*actor.position))]


def walk(arena,actor,brain,goal,now):
    if actor.blocked('move',now) or actor._speed(now)<=0:return []
    if actor.motion and actor.motion[3]>now:return []
    pos=actor.position_at(now)
    if actor.info.get('pve_trap'):
        from pve_chapter1 import trap_patrol_goal
        goal=brain['goal']=trap_patrol_goal(arena,actor,now)
    if math.dist(pos,goal)<20:return stop(actor,now)
    if not hasattr(arena,'navigation'):arena.navigation=Navigation(arena.geometry)
    friends=[a.position_at(now) for a in arena.actors.values()
             if a.id!=actor.id and a.camp==actor.camp and a.alive
             and not a.info.get('map_object') and not a.info.get('cow_object') and not a.info.get('bomb_cart') and not a.info.get('totem')]
    nearby=[p for p in friends if math.dist(pos,p)<240]
    if (arena.geometry.id==70 and brain.get('path') and 0<brain.get('repath_at',0)<=now
            and now>=brain.get('avoid_allies_until',0) and not brain.get('repair_box')
            and math.dist(pos,brain['path'][0])<=48
            and math.dist(goal,brain['path'][-1])<=72):
        # A slowly moving cart usually leaves the existing path inside its
        # escort radius. Keep that valid suffix instead of searching the whole
        # winding map every second. Destruction/ally blockage still invalidates
        # paths below; a different combat/repair destination replans normally.
        brain['repath_at']=now+500
    # Authored trap waypoints may change before the ordinary path-cache expiry.
    trap_goal_changed=actor.info.get('pve_trap') and brain.get('path_goal')!=tuple(goal)
    if now>=brain.get('repath_at',0) or trap_goal_changed:
        from bot_policy import ELITE,policy_for
        if policy_for(arena,actor)==ELITE:
            from bot_pro_navigation import path as pro_path
            brain['path']=pro_path(arena.navigation,pos,goal,brain.get('repair_threats',()),
                nearby if now<brain.get('avoid_allies_until',0) else ())
        else:
            brain['path']=arena.navigation.path(pos,goal,brain.get('repair_threats',()),
                nearby if now<brain.get('avoid_allies_until',0) else ())
        if actor.info.get('pve_trap'):brain['path_goal']=tuple(goal)
        if arena.geometry.id in (35,40) and not actor.info.get('npc_template'):
            from map_portals import route as portal_route
            brain['path']=portal_route(arena,actor,brain,goal,brain['path'],now)
        brain['repath_at']=now+1000
    path=brain['path']
    while path and math.dist(pos,path[0])<18:path.pop(0)
    if not path:
        bot_obstacles.note_blockage(arena,actor,brain,goal,goal,now)
        return []
    water=arena.water_rects(now)
    def forward_step(waypoint):
        steps=sorted((math.dist((pos[0]+24*dx,pos[1]+24*dy),waypoint),i,(pos[0]+24*dx,pos[1]+24*dy))
                     for i,(dx,dy) in enumerate(DIRECTIONS[:8]))
        # A dash/CC can leave a bot off the A* grid. Its closest diagonal may
        # clip a corner; all candidates still use native walking collision.
        return next((s for s in steps if s[0]<math.dist(pos,waypoint)
                     and arena.geometry.walk_end(pos,s[2],water)==s[2]),None)
    step=forward_step(path[0])
    if step is None and len(path)>1 and math.dist(pos,path[0])<24:
        # An off-grid bot can be just outside the arrival radius with no
        # improving 24px step. Round the corner toward the next waypoint only
        # if that actual step is legal; never snap the bot onto the grid.
        step=forward_step(path[1])
        if step is not None:path.pop(0)
    if step is None:
        bot_obstacles.note_blockage(arena,actor,brain,path[0],goal,now)
        brain['path']=[];brain['repath_at']=now+500
        return stop(actor,now)
    _,direction,dest=step
    # Physical spacing uses allies the bot can see; never scan hidden enemies here.
    if any(math.dist(dest,p)<64 and math.dist(dest,p)<math.dist(pos,p)-1 for p in friends):
        # A single sidestep followed by the old waypoint causes A-B-A loops
        # at a crowded spawn. Keep an actual detour for the following steps.
        brain['avoid_allies_until']=now+2000
        if now>=brain.get('avoid_repath_at',0):
            brain['path']=arena.navigation.path(pos,goal,brain.get('repair_threats',()),nearby)
            brain['repath_at']=brain['avoid_repath_at']=now+1000
        return stop(actor,now)
    speed=actor._speed(now)
    actor.position=pos;actor.motion=(pos,dest,now,now+max(1,round(math.dist(pos,dest)*1000/speed)))
    actor.motion_kind=0
    packets=actor._activity(now) if actor.info['tank_id']==bot_ai14.PEA else []
    # MOVE_NORMAL is a start coordinate + direction, not an arbitrary endpoint.
    return packets+[scene(moves=(struct.pack('<IhhhBB',actor.id,*pos,speed,direction,0),))]


def aim(arena,actor,observation,now):
    # Only the opt-in PvP contact controller changes its prediction. An old
    # brain marker cannot switch a legacy/human/NPC/practice battle policy.
    if _elite_contact(arena,actor):
        import bot_elite
        return bot_elite.aim(arena,actor,observation,now)
    return _legacy_aim(arena,actor,observation,now)


def _elite_contact(arena,actor):
    if getattr(arena,'bot_brains',{}).get(actor.id,{}).get('elite_micro_policy')!='legacy_contact':
        return False
    from bot_policy import policy_for,ELITE
    if policy_for(arena,actor)!=ELITE:return False
    from bot_elite import LOCAL_LEGACY_MAPS
    return arena.geometry.id in LOCAL_LEGACY_MAPS


def _legacy_aim(arena,actor,observation,now):
    start=actor.position_at(now);pos=observation['pos'];distance=math.dist(start,pos)
    travel=min(.65,distance/850)
    velocity=observation['velocity']
    lead=arena.rng.uniform(.5,.95)
    error=arena.rng.gauss(0,8+distance*.025)
    angle=math.atan2(pos[1]-start[1],pos[0]-start[0])
    return arena.geometry.clamp_tank_position((pos[0]+velocity[0]*travel*lead-math.sin(angle)*error,
                                               pos[1]+velocity[1]*travel*lead+math.cos(angle)*error))


def perform(arena,actor,slot,dest,target,now):
    # PRO may guard only the ordinary cursor belonging to this synchronous
    # combat decision. Kit-authored blink/melee/recast destinations differ
    # from that cursor and are left untouched. Legacy has no such context.
    if slot==0:
        from bot_policy import policy_for,ELITE
        if policy_for(arena,actor)==ELITE:
            context=getattr(arena,'bot_brains',{}).get(actor.id,{}).get('_pro_cast_context')
            if (context and context['observed_at']==now
                    and context['sample']['id']==target and tuple(dest)==context['cursor']
                    and actor.cooldowns.get(0,now+1)<=now):
                import bot_elite
                # Keep the reaction's already sampled cursor and RNG for the
                # normal native cast. Held input prepares its own forecast.
                # The sampled projectile guard is only valid for known kits.
                if bot_elite._basic_profile(actor,now) is not None:
                    if not bot_elite.basic_target_open(context['sample'],now,actor):return []
    return _native_perform(arena,actor,slot,dest,target,now)


def _native_perform(arena,actor,slot,dest,target,now):
    if slot==4:
        import guild_combat
        arena.damage_context=(actor.id,actor.generation,0,arena.new_id(2));arena.current_slot=slot
        try:
            stealth=actor.buff_versions.get(510501)
            packets=guild_combat.cast(actor,dest,target,now)
            if packets:
                actor.pk_safe_until=0
                if stealth is not None and actor.buff_versions.get(510501)==stealth:
                    packets+=guild_combat.break_stealth(actor,now)
                for buff in (358902,30105):
                    if actor.has_buff(buff,now):packets+=actor.remove_buff(buff,now)
            return packets
        finally:arena.damage_context=None;arena.current_slot=None
    ai05=actor.info['tank_id'] in bot_ai05.TANKS
    ai06=actor.info['tank_id'] in bot_ai06.TANKS
    ai07=actor.info['tank_id'] in bot_ai07.TANKS
    ai08=actor.info['tank_id'] in bot_ai08.TANKS
    ai09=actor.info['tank_id'] in bot_ai09.TANKS
    ai10=actor.info['tank_id'] in bot_ai10.TANKS
    ai11=actor.info['tank_id'] in bot_ai11.TANKS
    ai12=actor.info['tank_id'] in bot_ai12.TANKS
    ai13=actor.info['tank_id'] in bot_ai13.TANKS
    ai14=actor.info['tank_id'] in bot_ai14.TANKS
    ai15=actor.info['tank_id'] in bot_ai15.TANKS
    ai16=actor.info['tank_id'] in bot_ai16.TANKS
    ai17=actor.info['tank_id'] in bot_ai17.TANKS
    if actor.info['tank_id']==10000079 and actor.ice:return []
    repeat=(actor.info['tank_id'] in bot_ai20.TANKS and bot_ai20.recast(actor,slot,now) or actor.info['tank_id'] in bot_ai19.TANKS and bot_ai19.recast(actor,slot,now) or ai05 and bot_ai05.recast(actor,slot,now) or ai06 and bot_ai06.recast(actor,slot,now) or
            ai07 and bot_ai07.recast(actor,slot,now) or ai08 and bot_ai08.recast(actor,slot,now) or
            ai09 and bot_ai09.recast(actor,slot,now) or ai10 and bot_ai10.recast(actor,slot,now) or
            ai11 and bot_ai11.recast(actor,slot,now) or ai12 and bot_ai12.recast(actor,slot,now) or
            ai13 and bot_ai13.recast(actor,slot,now) or ai14 and bot_ai14.recast(actor,slot,now) or
            ai15 and bot_ai15.recast(actor,slot,now) or ai16 and bot_ai16.recast(actor,slot,now) or ai17 and bot_ai17.recast(actor,slot,now))
    cleanse=actor.info['tank_id']==10000081 and slot==10 or ai11 and bot_ai11.cleanse(actor,slot,now)
    if not (repeat or cleanse) and actor.skill_sealed(slot,now):return []
    if not repeat and actor.cooldowns.get(slot,now+1)>now:return []
    arena.damage_context=(actor.id,actor.generation,0,arena.new_id(2));arena.current_slot=slot
    try:
        packets=actor.cast(slot,actor.position_at(now),dest,target,now)
        if packets:
            actor.pk_safe_until=0
            if actor.has_buff(358902,now):packets+=actor.remove_buff(358902,now)
            if actor.has_buff(30105,now):packets+=actor.remove_buff(30105,now)
        return packets
    finally:arena.damage_context=None;arena.current_slot=None


def support(arena,actor,allies,seen,now,brain=None,recovering=False):
    if brain is not None:bot_ai02.adjust_goal(actor,brain,seen,now,recovering)
    if actor.info['tank_id'] in bot_ai20.TANKS:
        for slot,point,ident in bot_ai20.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai19.TANKS:
        for slot,point,ident in bot_ai19.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai18.TANKS:
        for slot,point,ident in bot_ai18.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai17.TANKS:
        for slot,point,ident in bot_ai17.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai16.TANKS:
        for slot,point,ident in bot_ai16.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai15.TANKS:
        for slot,point,ident in bot_ai15.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai14.TANKS:
        if brain is not None:bot_ai14.adjust_goal(actor,brain,seen,now,recovering)
        for slot,point,ident in bot_ai14.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai13.TANKS:
        for slot,point,ident in bot_ai13.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai12.TANKS:
        for slot,point,ident in bot_ai12.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai11.TANKS:
        for slot,point,ident in bot_ai11.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai10.TANKS:
        for slot,point,ident in bot_ai10.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai09.TANKS:
        for slot,point,ident in bot_ai09.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai08.TANKS:
        for slot,point,ident in bot_ai08.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai07.TANKS:
        for slot,point,ident in bot_ai07.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    if actor.info['tank_id'] in bot_ai06.TANKS:
        if brain is not None:bot_ai06.adjust_goal(actor,brain,seen,now,recovering)
        for slot,point,ident in bot_ai06.support_choices(actor,allies,seen,now,brain,recovering):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
        return []
    policy=(bot_ai05 if actor.info['tank_id'] in bot_ai05.TANKS else
            bot_ai04 if actor.info['tank_id'] in bot_ai04.TANKS else
            bot_ai02 if actor.info['tank_id'] in bot_ai02.TANKS else bot_ai01)
    for slot,point,ident in policy.support_choices(actor,allies,seen,now):
        packets=perform(arena,actor,slot,point,ident,now)
        if packets:return packets
    return []


def useful_last_stand(actor,allies,tanks,now):
    """Low HP is a retreat signal, not a command to abandon a winnable fight."""
    pos=actor.position_at(now)
    close=[s for s in tanks if math.dist(pos,s['pos'])<=360]
    support=[a for a in allies if a.id!=actor.id and math.dist(pos,a.position_at(now))<=450]
    if not close or not support or len(close)>len(support)+1:return False
    if any(s['hp']<.25 for s in close):return True
    tank=actor.info['tank_id']
    slots=(10,1) if tank==10000056 else (10,2) if tank==10000031 else (10,2) if tank==10000065 else bot_ai01.LAST_STAND.get(tank,bot_ai02.LAST_STAND.get(tank,bot_ai03.LAST_STAND.get(tank,bot_ai04.LAST_STAND.get(tank,bot_ai05.LAST_STAND.get(tank,bot_ai06.LAST_STAND.get(tank,bot_ai07.LAST_STAND.get(tank,bot_ai08.LAST_STAND.get(tank,bot_ai09.LAST_STAND.get(tank,())))))))))
    if tank in bot_ai10.TANKS:slots=bot_ai10.LAST_STAND[tank]
    if tank in bot_ai11.TANKS:slots=bot_ai11.LAST_STAND[tank]
    if tank in bot_ai12.TANKS:slots=bot_ai12.LAST_STAND[tank]
    if tank in bot_ai20.TANKS:slots=bot_ai20.LAST_STAND[tank]
    if tank in bot_ai19.TANKS:slots=bot_ai19.LAST_STAND[tank]
    if tank in bot_ai18.TANKS:slots=bot_ai18.LAST_STAND[tank]
    if tank in bot_ai17.TANKS:slots=bot_ai17.LAST_STAND[tank]
    if tank in bot_ai16.TANKS:slots=bot_ai16.LAST_STAND[tank]
    if tank in bot_ai15.TANKS:slots=bot_ai15.LAST_STAND[tank]
    if tank in bot_ai14.TANKS:slots=bot_ai14.LAST_STAND[tank]
    elif tank in bot_ai13.TANKS:slots=bot_ai13.LAST_STAND[tank]
    return any(actor.cooldowns.get(s,now+1)<=now and not actor.skill_sealed(s,now) for s in slots)


def seek_repair(arena,actor,brain,seen,now):
    from map_objects import repair_contact
    if now<getattr(actor,'repair_ready_at',0) or actor.has_buff(10,now):return False
    if not hasattr(arena,'navigation'):arena.navigation=Navigation(arena.geometry)
    pos=actor.position_at(now);nav=arena.navigation
    if now>=brain.get('repair_check_at',0):
        brain['repair_check_at']=now+1000
        threats=[s['pos'] for s in seen if not s.get('objective',s['robo'])]
        friends=[a.position_at(now) for a in arena.actors.values()
                 if a.id!=actor.id and a.camp==actor.camp and a.alive and not a.info.get('npc_template')]
        options=[]
        for box in arena.actors.values():
            if not box.alive or not getattr(box,'repair_box',False) or box.camp not in (0,actor.camp):continue
            waiting=bool(box.repair) or any(i<actor.id and b.get('repair_box')==box.id
                and arena.actors[i].alive and arena.actors[i].camp==actor.camp
                and b.get('repair_check_at',0)>now for i,b in arena.bot_brains.items())
            left,top,right,bottom=box.map_rect;cx,cy=box.position
            gap=144 if waiting else 36
            candidates=((left-gap,cy),(right+gap,cy),(cx,top-gap),(cx,bottom+gap))
            for candidate in candidates:
                point=nav.nearest(candidate)
                if point is None or (not waiting and not repair_contact(arena,box,point,now)):continue
                # The nearest side may be occupied by an idle ally. Select
                # another contact point, not a detour ending outside healing range.
                if any(math.dist(point,p)<64 for p in friends):continue
                danger=sum(max(0,400-math.dist(point,p))*3 for p in threats)
                options.append((math.dist(pos,point)+danger+(120 if waiting else 0),box.id,point))
        options.sort()
        brain.pop('repair_goal',None);brain.pop('repair_box',None)
        if options:
            source=nav.nearest(pos)
            reachable=nav.reachable(source) if source is not None else ()
            for _,ident,point in options:
                if point in reachable:
                    brain.update(repair_box=ident,repair_goal=point,repair_threats=threats,repath_at=0)
                    break
    if 'repair_goal' not in brain:return False
    brain['goal']=brain['repair_goal']
    return True


def advance_goal(arena,actor,brain,now):
    # Public spawn/lane geometry, never an unseen opponent's current position.
    start=arena.geometry.spawn(actor.camp,0)
    end=arena.geometry.spawn(3-actor.camp,0)
    stage=brain.get('advance_stage',0)
    fraction=(.5,.7)[stage]
    x,y=point_at(start,end,fraction)
    dx,dy=end[0]-start[0],end[1]-start[1];length=max(1,math.hypot(dx,dy))
    lane=(actor.id%3-1)*96
    goal=arena.geometry.clamp_tank_position((x-dy/length*lane,y+dx/length*lane))
    if math.dist(actor.position_at(now),goal)<120:
        brain['advance_stage']=1-stage
    return goal


def desired_range(actor,now):
    """Native kit-aware spacing, also available to the separate elite policy."""
    tank=actor.info['tank_id']
    for policy in (bot_ai01,bot_ai02,bot_ai03):
        if tank in policy.TANKS:return policy.desired_range(actor)
    for policy in (bot_ai05,bot_ai04,bot_ai06,bot_ai07,bot_ai09,bot_ai08,
                   bot_ai10,bot_ai20,bot_ai19,bot_ai18,bot_ai17,bot_ai16,
                   bot_ai15,bot_ai14,bot_ai13,bot_ai12,bot_ai11):
        if tank in policy.TANKS:return policy.desired_range(actor,now)
    return 125 if tank==10000056 else 340 if tank==10000031 else 420


def structure_range(actor,now):
    """Keep stance-dependent basic ranges used by native siege positioning."""
    tank=actor.info['tank_id']
    for policy in (bot_ai20,bot_ai19,bot_ai14,bot_ai12,bot_ai11,bot_ai10,
                   bot_ai07,bot_ai05,bot_ai04):
        if tank in policy.TANKS:return policy.basic_range(actor,now)
    return None


def decide(arena,actor,brain,seen,now):
    pos=actor.position_at(now)
    nearby=[s for s in seen if math.dist(pos,s['pos'])<960]
    if (actor.info.get('robo') or actor.info.get('base_robot') or actor.info.get('mascot') or actor.info.get('map_spider')):
        return decide_robo(arena,actor,brain,nearby,now)
    allies=[a for a in arena.actors.values() if a.alive and a.camp==actor.camp and not a.info.get('npc_template') and math.dist(pos,a.position_at(now))<600]
    tanks=[s for s in nearby if not s.get('objective',s['robo'])]
    ratio=float(actor.hp/actor.max_hp)
    commit=ratio<.4 and useful_last_stand(actor,allies,tanks,now)
    can_recover=actor.info['tank_id'] not in bot_ai10.TANKS or bot_ai10.can_recover(actor)
    if actor.info['tank_id'] in bot_ai11.TANKS:can_recover=bot_ai11.can_recover(actor)
    if actor.info['tank_id'] in bot_ai17.TANKS:can_recover=bot_ai17.can_recover(actor,now)
    if actor.info['tank_id'] in bot_ai16.TANKS:can_recover=bot_ai16.can_recover(actor,now)
    if actor.info['tank_id'] in bot_ai19.TANKS:can_recover=bot_ai19.can_recover(actor,now)
    recovering=can_recover and ratio<.4 and not commit and seek_repair(arena,actor,brain,nearby,now)
    objective=None
    if arena.geometry.id in (30,40):
        from death_mode import survival_goal
        objective=survival_goal(arena,actor,brain,now)
    elif arena.geometry.id in (12,14,50,169) and not recovering:
        from base_mode import goal
        objective=goal(arena,actor,nearby,now,brain)
    elif arena.geometry.id in (7,9,10,37,170) and not recovering:
        from occupy_rules import goal
        objective=goal(arena,actor,tanks,now)
    elif arena.geometry.id==70 and not recovering:
        from escort_mode import goal
        objective=goal(arena,actor,nearby,now)
    elif arena.geometry.id in (20,36) and not recovering:
        from cow_objectives import goal
        objective=goal(arena,actor,tanks,now)
    elif arena.geometry.id==21 and not recovering and not tanks:
        from lightning_map import goal
        objective=goal(arena,actor,now)
    elif arena.geometry.id==18 and not recovering and not tanks:
        from totem_objectives import goal
        objective=goal(arena,actor)
    elif arena.geometry.id==1 and not recovering and not tanks:
        from maya_map import goal
        objective=goal(arena,actor,nearby,now)
    if arena.geometry.id==34 and not recovering and not tanks:
        objective=('clear_path',advance_goal(arena,actor,brain,now))
    if arena.geometry.id==35 and not recovering and not tanks:
        from map_portals import approach
        objective=('clear_path',approach(arena,actor,advance_goal(arena,actor,brain,now),nearby,now))
    blocker=bot_obstacles.selected(brain,nearby,objective,pos)
    # Keep mode/combat priorities. The additional blocker must have prevented
    # a real native walk step and survived the normal observation delay.
    nearby=[s for s in nearby if not s.get('barrier') or
            ((not tanks or arena.geometry.id in (12,14,50,169)) and not recovering and
             (s is blocker or (arena.geometry.id in (12,14,21,34,35,50,70,169) and objective and
              rect_contact(pos,objective[1],(tuple(s['turret_rect']),)) is not None)))]
    brain['objective']=objective[0] if objective else None
    if not recovering:
        brain.pop('repair_box',None);brain.pop('repair_goal',None);brain.pop('repair_threats',None)
    if not nearby:
        brain['target']=None
        if not recovering:brain['goal']=objective[1] if objective else advance_goal(arena,actor,brain,now)
        return support(arena,actor,allies,seen if actor.info['tank_id']==10000112 else nearby,now,brain,recovering)
    focus=[b.get('target') for i,b in arena.bot_brains.items() if i!=actor.id and arena.actors[i].camp==actor.camp]
    candidates=tanks or nearby
    if arena.geometry.id==70 and not recovering:
        from escort_mode import targets
        candidates=targets(actor,nearby,tanks,objective)
        if not candidates:
            brain['target']=None;brain['goal']=objective[1] if objective else pos
            return support(arena,actor,allies,seen if actor.info['tank_id']==10000112 else nearby,now,brain,recovering)
    if arena.geometry.id in (12,14,50,169) and not recovering:
        from base_mode import targets
        candidates=targets(actor,brain,nearby,tanks,allies,objective,now)
        if not candidates:
            brain['target']=None
            brain['goal']=objective[1] if objective else pos
            return support(arena,actor,allies,seen if actor.info['tank_id']==10000112 else nearby,now,brain,recovering)
    target=min(candidates,key=lambda s:math.dist(pos,s['pos'])+s['hp']*180-40*focus.count(s['id'])
               +(math.dist(objective[1],s['pos'])*.4 if objective else 0))
    brain['target']=target['id'];distance=math.dist(pos,target['pos']);dest=aim(arena,actor,target,now)
    exclude=(tuple(target['turret_rect']),) if target.get('turret_rect') else ()
    blocked=arena.geometry.wall_contact(pos,target['pos'],exclude=exclude) is not None
    outnumbered=sum(arena.geometry.id not in (12,14,50,169) or math.dist(pos,s['pos'])<480 for s in tanks)>len(allies)+1
    retreat=recovering or not commit and (ratio<.28 and not bot_ai10.soul(actor) or outnumbered and ratio<.55)
    tank=actor.info['tank_id'];desired=(bot_ai01.desired_range(actor) if tank in bot_ai01.TANKS
                                      else bot_ai02.desired_range(actor) if tank in bot_ai02.TANKS
                                      else bot_ai03.desired_range(actor) if tank in bot_ai03.TANKS
                                      else bot_ai05.desired_range(actor,now) if tank in bot_ai05.TANKS
                                      else bot_ai04.desired_range(actor,now) if tank in bot_ai04.TANKS
                                      else bot_ai06.desired_range(actor,now) if tank in bot_ai06.TANKS
                                      else bot_ai07.desired_range(actor,now) if tank in bot_ai07.TANKS
                                      else bot_ai09.desired_range(actor,now) if tank in bot_ai09.TANKS
                                      else bot_ai08.desired_range(actor,now) if tank in bot_ai08.TANKS
                                      else bot_ai10.desired_range(actor,now) if tank in bot_ai10.TANKS
                                      else bot_ai20.desired_range(actor,now) if tank in bot_ai20.TANKS
                                      else bot_ai19.desired_range(actor,now) if tank in bot_ai19.TANKS
                                      else bot_ai18.desired_range(actor,now) if tank in bot_ai18.TANKS
                                      else bot_ai17.desired_range(actor,now) if tank in bot_ai17.TANKS
                                      else bot_ai16.desired_range(actor,now) if tank in bot_ai16.TANKS
                                      else bot_ai15.desired_range(actor,now) if tank in bot_ai15.TANKS
                                      else bot_ai14.desired_range(actor,now) if tank in bot_ai14.TANKS
                                      else bot_ai13.desired_range(actor,now) if tank in bot_ai13.TANKS
                                      else bot_ai12.desired_range(actor,now) if tank in bot_ai12.TANKS
                                      else bot_ai11.desired_range(actor,now) if tank in bot_ai11.TANKS
                                      else 125 if tank==10000056 else 340 if tank==10000031 else 420)
    if recovering:
        pass  # Keep the box/queue destination; shooting can still cover retreat.
    elif retreat:
        brain['goal']=(objective[1] if arena.geometry.id in (30,40) else
                       arena.geometry.spawn(actor.camp,actor.info.get('spawn_index',0),respawn=True))
    elif target.get('barrier') or arena.geometry.id in (12,14,50,169) and target.get('structure'):
        from base_mode import firing_position
        reach=(bot_ai20.basic_range(actor,now) if tank in bot_ai20.TANKS else
               bot_ai19.basic_range(actor,now) if tank in bot_ai19.TANKS else
               bot_ai14.basic_range(actor,now) if tank in bot_ai14.TANKS else
               bot_ai12.basic_range(actor,now) if tank in bot_ai12.TANKS else
               bot_ai11.basic_range(actor,now) if tank in bot_ai11.TANKS else
               bot_ai10.basic_range(actor,now) if tank in bot_ai10.TANKS else
               bot_ai07.basic_range(actor,now) if tank in bot_ai07.TANKS else
               bot_ai05.basic_range(actor,now) if tank in bot_ai05.TANKS else
               bot_ai04.basic_range(actor,now) if tank in bot_ai04.TANKS else None)
        brain['goal']=firing_position(arena,actor,arena.actors[target['id']],now,reach=reach) or (objective[1] if objective else target['pos'])
    elif objective and objective[0] in ('bomb_escort','bomb_intercept'):
        brain['goal']=objective[1]
    elif objective and objective[0]=='flag_hold':
        # Standing on the objective matters more than ordinary ranged kiting.
        # Retreat and visible-projectile evasion still take priority.
        brain['goal']=objective[1]
    elif objective and objective[0] not in ('totem','clear_path','base_push') and (distance>300 or math.dist(target['pos'],objective[1])>360):
        # Keep a nearby firing opportunity without abandoning the escort for
        # an unrelated enemy across the map. Close threats use combat spacing.
        brain['goal']=objective[1]
    elif distance>desired+50 or blocked:
        brain['goal']=(target['pos'] if blocked
                       else point_at(target['pos'],pos,desired/max(1,distance)))
    elif distance<desired-70 and tank not in (10000056,10000003) and not (tank in bot_ai20.TANKS and desired<=200) and not (tank in bot_ai02.TANKS and desired<200) and not (tank in bot_ai03.TANKS and desired<240) and not (tank in bot_ai04.TANKS and desired<200) and not (tank in bot_ai05.TANKS and desired<=200) and not (tank in bot_ai07.TANKS and desired<=200) and not (tank in bot_ai08.TANKS and desired<=210) and not (tank in bot_ai10.TANKS and desired<=200) and not (tank in bot_ai11.TANKS and desired<=200) and not (tank in bot_ai12.TANKS and desired<=200) and not (tank in bot_ai13.TANKS and desired<=200) and not (tank in bot_ai15.TANKS and desired<=200) and not (tank in bot_ai16.TANKS and desired<=200) and not (tank in bot_ai17.TANKS and desired<=200):
        brain['goal']=point_at(pos,target['pos'],-120/max(1,distance))
    else:
        # Small lateral movement keeps firing lanes open without pixel-perfect dodges.
        side=1 if actor.id%2 else -1;dx,dy=target['pos'][0]-pos[0],target['pos'][1]-pos[1]
        brain['goal']=(pos[0]-side*dy/max(1,distance)*72,pos[1]+side*dx/max(1,distance)*72)
    if arena.geometry.id in (30,40):
        from death_mode import constrain_goal
        constrain_goal(arena,actor,brain,tanks,now)
    return combat(arena,actor,brain,seen,nearby,allies,target,dest,retreat,blocked,recovering,now)


def combat(arena,actor,brain,seen,nearby,allies,target,dest,retreat,blocked,recovering,now):
    # Elite can reuse the unchanged local decision policy in contact. Observe
    # only the kit executor's goal adjustment, not the tactical goal chosen by
    # decide(), so later evasion does not overwrite a native steer/recast goal.
    # Legacy battles take the direct path with no added brain state or RNG.
    from bot_policy import policy_for,ELITE
    if policy_for(arena,actor)!=ELITE:
        return _native_combat(arena,actor,brain,seen,nearby,allies,target,dest,retreat,blocked,recovering,now)
    if _elite_contact(arena,actor):
        import bot_elite
        target,dest,retreat,blocked=bot_elite.contact_combat(
            arena,actor,brain,seen,nearby,allies,target,dest,retreat,blocked,recovering,now)
    import bot_engagement
    retreat=bot_engagement.prepare(arena,actor,brain,nearby,target,retreat,recovering,now)
    before=tuple(brain['goal']) if brain.get('goal') is not None else None
    brain['_pro_cast_context']=dict(sample=target,cursor=tuple(dest),observed_at=now)
    try:
        return _native_combat(arena,actor,brain,seen,nearby,allies,target,dest,retreat,blocked,recovering,now)
    finally:
        brain.pop('_pro_cast_context',None)
        after=tuple(brain['goal']) if brain.get('goal') is not None else None
        brain['elite_native_goal']=after!=before


def _native_combat(arena,actor,brain,seen,nearby,allies,target,dest,retreat,blocked,recovering,now):
    """Shared native kit executor; strategy changes never bypass cast rules.

    The legacy execution chain below is unchanged. Elite supplies a decision
    made from delayed observations, not a second implementation of 91 kits.
    """
    pos=actor.position_at(now)
    ratio=float(actor.hp/actor.max_hp)
    distance=math.dist(pos,target['pos'])
    tank=actor.info['tank_id']
    exclude=(tuple(target['turret_rect']),) if target.get('turret_rect') else ()
    if tank in bot_ai19.TANKS:
        return bot_ai19.decide(actor,brain,allies,target,nearby,dest,retreat,blocked,now)
    if tank in bot_ai05.TANKS:bot_ai05.steer(actor,brain,dest)
    if tank in bot_ai07.TANKS:bot_ai07.steer(actor,brain,dest,retreat,now)
    if tank in bot_ai08.TANKS:bot_ai08.steer(actor,brain,dest,nearby,retreat,now)
    if getattr(actor,'channel',None):
        if tank==bot_ai16.TIME:return []
        if tank==10000001:return actor.aim_bot_channel(dest,now)
        if tank not in bot_ai04.TANKS and tank not in bot_ai06.TANKS and tank not in bot_ai07.TANKS and tank not in bot_ai09.TANKS and tank not in bot_ai10.TANKS:
            actor.channel['dest']=dest
            return []
    packets=support(arena,actor,allies,seen if actor.info['tank_id']==10000112 else nearby,now,brain,recovering)
    if packets:return packets
    # Thach Sanh's R may cleanse hard CC through its native cast guard.
    if tank==10000063 and actor.blocked('attack',now):
        for slot,point,ident in bot_ai01.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            if slot!=10:continue
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    # Edwina's native R remains usable during attack CC, including with E on.
    if tank==10000066 and actor.blocked('attack',now):
        for slot,point,ident in bot_ai04.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            if slot!=10:continue
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank==10000099 and actor.ready:
        for slot,point,ident in bot_ai05.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if actor.blocked('attack',now):return []
    if tank in bot_ai09.TANKS and bot_ai09.hold_stealth(actor,target,retreat,now):return []
    if tank in bot_ai12.TANKS and bot_ai12.hold_stealth(actor,retreat,now):return []
    if tank in bot_ai18.TANKS and bot_ai18.hold_fog(actor,retreat,now):return []
    if tank in bot_ai16.TANKS and bot_ai16.hold_flight(actor,retreat,now):return []
    basic_range=(bot_ai20.basic_range(actor,now) if tank in bot_ai20.TANKS else
                 bot_ai14.basic_range(actor,now) if tank in bot_ai14.TANKS else
                 bot_ai12.basic_range(actor,now) if tank in bot_ai12.TANKS else
                 bot_ai11.basic_range(actor,now) if tank in bot_ai11.TANKS else
                 bot_ai07.basic_range(actor,now) if tank in bot_ai07.TANKS else
                 bot_ai05.basic_range(actor,now) if tank in bot_ai05.TANKS else
                 bot_ai04.basic_range(actor,now) if tank in bot_ai04.TANKS else
                 bot_ai03.basic_range(actor,now) if tank in bot_ai03.TANKS else int(actor.stats['nFireRange']))
    if target.get('barrier') or arena.geometry.id in (12,14,50,169) and target.get('structure'):
        if distance<=basic_range and arena.geometry.wall_contact(pos,dest,exclude=exclude) is None:
            if tank==10000063 and not actor.has_buff(338302,now) and not retreat:
                packets=perform(arena,actor,2,pos,actor.id,now)
                if packets:return packets
            if tank in bot_ai03.TANKS and not retreat:
                for slot,point,ident in bot_ai03.structure_choices(actor,dest,now):
                    packets=perform(arena,actor,slot,point,ident,now)
                    if packets:return packets
            if tank in bot_ai15.TANKS and not retreat:
                for slot,point,ident in bot_ai15.structure_choices(actor,brain,target,nearby,dest,now):
                    packets=perform(arena,actor,slot,point,ident,now)
                    if packets:return packets
            if tank in bot_ai14.TANKS and not retreat:
                for slot,point,ident in bot_ai14.structure_choices(actor,brain,target,nearby,dest,now):
                    packets=perform(arena,actor,slot,point,ident,now)
                    if packets:return packets
            if tank in bot_ai13.TANKS and not retreat:
                for slot,point,ident in bot_ai13.structure_choices(actor,brain,target,nearby,dest,now):
                    packets=perform(arena,actor,slot,point,ident,now)
                    if packets:return packets
            if tank in bot_ai12.TANKS and not retreat:
                for slot,point,ident in bot_ai12.structure_choices(actor,brain,target,nearby,dest,now):
                    packets=perform(arena,actor,slot,point,ident,now)
                    if packets:return packets
            if tank in bot_ai11.TANKS and not retreat:
                for slot,point,ident in bot_ai11.structure_choices(actor,brain,target,nearby,dest,now):
                    packets=perform(arena,actor,slot,point,ident,now)
                    if packets:return packets
            return perform(arena,actor,0,dest,target['id'],now)
        return []
    if tank in bot_ai20.TANKS:
        for slot,point,ident in bot_ai20.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai01.TANKS:
        for slot,point,ident in bot_ai01.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai02.TANKS:
        for slot,point,ident in bot_ai02.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai03.TANKS:
        for slot,point,ident in bot_ai03.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai04.TANKS:
        for slot,point,ident in bot_ai04.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai05.TANKS:
        for slot,point,ident in bot_ai05.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai06.TANKS:
        for slot,point,ident in bot_ai06.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai07.TANKS:
        for slot,point,ident in bot_ai07.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai09.TANKS:
        for slot,point,ident in bot_ai09.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai08.TANKS:
        for slot,point,ident in bot_ai08.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai10.TANKS:
        for slot,point,ident in bot_ai10.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai18.TANKS:
        for slot,point,ident in bot_ai18.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai17.TANKS:
        for slot,point,ident in bot_ai17.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai16.TANKS:
        for slot,point,ident in bot_ai16.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai15.TANKS:
        for slot,point,ident in bot_ai15.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai14.TANKS:
        for slot,point,ident in bot_ai14.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai13.TANKS:
        for slot,point,ident in bot_ai13.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai12.TANKS:
        for slot,point,ident in bot_ai12.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    if tank in bot_ai11.TANKS:
        for slot,point,ident in bot_ai11.choices(actor,brain,target,nearby,dest,retreat,blocked,now):
            packets=perform(arena,actor,slot,point,ident,now)
            if packets:return packets
    choices=[]
    if tank==10000019:
        if distance<270 or retreat:choices.append((10,target['id']))
        if distance<560:choices.append((1,target['id']))
        if distance<650 and (len(nearby)>1 or target['hp']<.65):choices.append((2,target['id']))
    elif tank==10000001:
        if distance<600:choices.append((1,target['id']))
        if distance<650:choices.append((10,target['id']))
        if distance<550 and not retreat and len(allies)>=2:choices.append((2,target['id']))
    elif tank==10000056:
        if distance<=288 and target['hp']<.30:choices.append((2,target['id']))
        if distance<=216:choices.append((10,target['id']))
        if (getattr(actor,'e_second_until',0)>now and distance<480) or (distance>200 and not retreat):choices.append((1,target['id']))
    elif tank==10000031:
        weak=min(allies,key=lambda a:float(a.hp/a.max_hp))
        if float(weak.hp/weak.max_hp)<.6:choices.append((10,weak.id))
        if len(allies)>1 and (ratio<.65 or len(nearby)>=2):choices.append((2,actor.id))
        if distance<560:choices.append((1,target['id']))
    elif tank==10000065:
        if distance<600:choices.append((1,target['id']))
        if distance<620:choices.append((10,target['id']))
        if distance<750 and (len(nearby)>=2 or retreat):choices.append((2,target['id']))
    for slot,ident in choices:
        packets=perform(arena,actor,slot,dest,ident,now)
        if packets:return packets
    if (distance<=basic_range and arena.geometry.wall_contact(pos,dest,exclude=exclude) is None
            and (tank not in bot_ai08.TANKS or bot_ai08.basic_allowed(actor,brain,target,now))):
        return perform(arena,actor,0,dest,target['id'],now)
    return []


def decide_robo(arena,actor,brain,seen,now):
    pos=actor.position_at(now)
    targets=[s for s in seen if not actor.info.get('mascot') and math.dist(pos,s['pos'])<=(650 if actor.info.get('base_robot') else 600) and
             (not actor.info.get('map_spider') or not arena.actors[s['id']].info.get('npc_template'))]
    if targets:
        target=min(targets,key=lambda s:math.dist(pos,s['pos']))
        reach=int(actor.stats['nFireRange'])
        brain['goal']=pos if actor.info.get('base_robot') else target['pos'] if math.dist(pos,target['pos'])>reach-60 else pos
        if math.dist(pos,target['pos'])<=reach:
            return perform(arena,actor,0,aim(arena,actor,target,now),target['id'],now)
        return []
    route=(arena.geometry.data['base_waves'][actor.info['wave_index']] if actor.info.get('base_robot') else actor.info)
    if not actor.route_queue:
        node=next((p for p in route['logic'] if p['id']==actor.route_point),None)
        if not node or not node['next']:
            brain['goal']=pos
            return []
        options=[i for i in node['next'] if i!=actor.route_previous] or node['next']
        end=arena.rng.choice(options)
        edge=next(p for p in route['paths'] if set(p['ends'])=={actor.route_point,end})
        points=edge['points'] if edge['ends'][0]==actor.route_point else list(reversed(edge['points']))
        actor.route_queue=[tuple(p) for p in points]
        actor.route_previous,actor.route_point=actor.route_point,end
    while actor.route_queue and math.dist(pos,actor.route_queue[0])<24:actor.route_queue.pop(0)
    if actor.route_queue:brain['goal']=actor.route_queue[0]
    return []


def tick(arena,now):
    from bot_policy import policy_for,ELITE
    packets=[]
    for actor in list(arena.actors.values()):
        if human(actor) or not actor.alive or (actor.info.get('npc_template') and not (actor.info.get('robo') or actor.info.get('base_robot') or actor.info.get('mascot') or actor.info.get('map_spider'))):continue
        brain=arena.bot_brains.setdefault(actor.id,dict(generation=actor.generation,notice_at=now+arena.rng.randint(180,350),observations=[],path=[]))
        if brain['generation']!=actor.generation:
            brain.clear();brain.update(generation=actor.generation,notice_at=now+250,observations=[],path=[])
        if now>=brain['notice_at']:
            # Act on the preceding observation, then sample for the next reaction.
            seen=brain['observations']
            elite=policy_for(arena,actor)==ELITE
            if elite:
                import bot_elite
                packets+=bot_elite.decide(arena,actor,brain,seen,now)
                if arena.pk['finished']:break
                import bot_execution
                bot_execution.prepare(arena,actor,brain,seen,now)
            else:
                packets+=decide(arena,actor,brain,seen,now)
            if actor.info.get('guild') and actor.info.get('bot_loadout_version'):
                from bot_guild_ai import decide as guild_decide
                packets+=guild_decide(arena,actor,brain,seen,now)
            if elite:
                if arena.pk['finished']:break
                bot_elite.evade(arena,actor,brain,now)
            elif not (actor.info.get('robo') or actor.info.get('base_robot') or actor.info.get('mascot') or actor.info.get('map_spider')):evade(arena,actor,brain,now)
            if arena.geometry.id==170:
                from quicksand_map import evade as evade_wind,observe as observe_wind
                evade_wind(arena,actor,brain,now)
                brain['winds']=observe_wind(arena,actor,now)
            if arena.geometry.id==40:
                from death_city import evade as evade_vent,observe as observe_vent
                evade_vent(arena,actor,brain,now)
                brain['vents']=observe_vent(arena,actor,now)
            brain['observations']=(bot_elite.observe(arena,actor,brain,now) if elite else observe(arena,actor,brain,now))
            brain['bullets']=observe_bullets(arena,actor,now)
            # A stronger, deliberately bounded PRO control cadence. The bot
            # still acts on an observation at least180ms old; no fresh-sensor
            # reaction or extra combat cooldown/resource is granted. Legacy
            # keeps exactly its original random interval and RNG draw.
            brain['notice_at']=now+arena.rng.randint(180,220 if elite else 350)
        if arena.pk['finished']:break
        if brain.get('pro_fire_plan'):
            import bot_execution
            packets+=bot_execution.tick(arena,actor,brain,now)
            if arena.pk['finished']:break
        if brain.get('goal') is not None:
            packets+=walk(arena,actor,brain,brain['goal'],now)
    return packets
