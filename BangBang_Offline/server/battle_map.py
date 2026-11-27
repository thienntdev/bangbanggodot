"""Immutable, cached geometry per arena; source maps are imported into SQLite."""
import math
from collections import Counter
from functools import lru_cache

from combat_geometry import point_at, rect_contact, map101_walls, map101_tank_bounds
from storage import database_path, setting
from combat_data import table_row
from cpp_backend import create_index


@lru_cache(maxsize=8)
def _definition(database, map_id):
    if map_id == 40002:
        from world_boss_data import geometry
        return geometry()
    if map_id == 101:
        return dict(width=1440,height=936,bounds=map101_tank_bounds(),
                    walls=map101_walls(),movement_walls=map101_walls(),
                    spawns={'1':[(444,612)],'2':[(780,804)]},
                    respawns={'1':[(444,612)],'2':[(780,804)]},npcs=[],robos=[])
    from pve_catalog import MAPS as PVE_MAPS
    if map_id not in (1,4,7,9,10,12,14,17,18,19,20,21,30,40,34,35,36,37,50,70,169,170)+PVE_MAPS:
        raise ValueError(f'Map {map_id} chưa có luật server; hãy chọn một map đã mở trong thiết lập trận bot.')
    return setting(f'battle_map_{map_id}')


class BattleMap:
    def __init__(self,map_id):
        self.id = map_id
        self.data = _definition(str(database_path()),map_id)
        self.width,self.height = self.data['width'],self.data['height']
        self.bounds = tuple(self.data['bounds'])
        self.walls = tuple(tuple(r) for r in self.data['walls'])
        self.movement_walls = tuple(tuple(r) for r in self.data['movement_walls'])
        # Map7's authored north/west fence encloses an empty exterior strip
        # inside the image's rectangular bounds. A 72px tank can fit there,
        # but cannot return without another wall-crossing skill. Fill only
        # that exterior for vehicle movement, keeping the inner fence edges
        # (y=216 and x=216 until y=504). Do not add these to bullet/sight walls,
        # aim bounds, or the immutable source definition. Other maps include
        # intentional isolated Robo/portal/air-drop rooms, not exterior voids.
        self._playable_exterior = ((0,0,self.width,216),(0,0,216,504)) if map_id==7 else ()
        self._bullet_bins=self._index(self.walls)
        self._move_bins=self._index(self.movement_walls)
        # MapDataModel samples terrain on a 24px grid. SelfMoveRule checks
        # NPC rectangles separately, using the actual (possibly off-grid) pose.
        objects=[]
        for npc in self.data['npcs']:
            if map_id==70 and npc.get('script_only'):continue
            row=table_row('NpcTemplate_table.xml',nTemplateId=npc['template'])
            if int(row['iType']) in (51,52,53):continue  # Visual markers need no hitbox.
            w,h=int(row.get('iWidth') or 0),int(row.get('iHeight') or 0)
            if int(row['iType']) not in (51,52,53) and w and h:
                x,y=npc['x'],npc['y']
                objects.append((x-w/2,y-h/2,x+w/2,y+h/2))
        objects.extend(tuple(r['rect']) for r in self.data.get('pve_barriers',()))
        self._walk_objects=Counter(objects)
        terrain=Counter(self.movement_walls)-self._walk_objects
        self._walk_terrain_bins=self._index(terrain)
        self._walk_object_bins=self._index(self._walk_objects)
        # Native handles are derived only from this arena's current map. They
        # are excluded from checkpoints and recreated by normal construction.
        self._cpp_bullet_index=create_index(self.walls)
        self._cpp_move_index=create_index(self.movement_walls)
        self._cpp_terrain_index=create_index(tuple(terrain))
        self._cpp_object_index=create_index(tuple(self._walk_objects))
        self.can_walk_to=lru_cache(maxsize=8192)(self.can_walk_to)
        self._wall_contact_cached=lru_cache(maxsize=8192)(self._wall_contact)

    def remove_objects(self,rectangles):
        # Subtract individual NPC copies, preserving overlapping terrain and
        # other living objects. Never alter the shared cached map definition.
        removed=Counter(tuple(r) for r in rectangles)
        self.walls=tuple((Counter(tuple(r) for r in self.data['walls'])-removed).elements())
        self.movement_walls=tuple((Counter(tuple(r) for r in self.data['movement_walls'])-removed).elements())
        self._bullet_bins=self._index(self.walls)
        self._move_bins=self._index(self.movement_walls)
        self._walk_object_bins=self._index(self._walk_objects-removed)
        self._cpp_bullet_index=create_index(self.walls)
        self._cpp_move_index=create_index(self.movement_walls)
        self._cpp_object_index=create_index(tuple(self._walk_objects-removed))
        self.can_walk_to.cache_clear()
        self._wall_contact_cached.cache_clear()

    @staticmethod
    def _index(rects):
        bins={}
        for rect in rects:
            l,t,r,b=rect
            for x in range(math.floor(l/192),math.floor(r/192)+1):
                for y in range(math.floor(t/192),math.floor(b/192)+1):
                    bins.setdefault((x,y),set()).add(rect)
        return bins

    def spawn(self,camp,index=0,*,respawn=False):
        points = self.data['respawns' if respawn else 'spawns'][str(camp)]
        return tuple(points[index%len(points)])

    def inside(self,pos):
        return 0<=pos[0]<=self.width and 0<=pos[1]<=self.height

    def clamp_tank_position(self,pos):
        l,t,r,b = self.bounds
        return round(min(r,max(l,pos[0]))),round(min(b,max(t,pos[1])))

    def in_playable_region(self,pos):
        """Explicit exterior guard only; bounds/terrain keep their own rules."""
        return not self._playable_exterior or rect_contact(pos,pos,self._playable_exterior,35.999) is None

    def _clip_playable_motion(self,start,dest):
        # Check the whole ray, not just its endpoint: a diagonal can enter
        # and leave the L-shaped exterior, then be interrupted in the void.
        # The tiny inset permits tangency and moving away from a safe edge.
        if not self._playable_exterior:return dest
        hit=rect_contact(start,dest,self._playable_exterior,35.999)
        if hit is None:return dest
        edge=point_at(start,dest,hit)
        return tuple(math.floor(v) if z>a else math.ceil(v) if z<a else round(v)
                     for v,a,z in zip(edge,start,dest))

    def clip_tank_motion(self,start,dest):
        start = self.clamp_tank_position(start)
        l,t,r,b = self.bounds
        fraction = 1.
        for a,z,lo,hi in zip(start,dest,(l,t),(r,b)):
            if z>hi:fraction=min(fraction,(hi-a)/(z-a))
            elif z<lo:fraction=min(fraction,(lo-a)/(z-a))
        dest=self.clamp_tank_position(point_at(start,dest,fraction))
        return self._clip_playable_motion(start,dest)

    def clear_tank_landing(self,start,dest,water=()):
        dest = self._clip_playable_motion(start,tuple(round(v) for v in dest))
        landing_walls=self.movement_walls+self._playable_exterior
        for _ in landing_walls:
            blocked = [r for r in landing_walls if rect_contact(dest,dest,(r,),35.999) is not None]
            if not blocked:return self._mobile_tank_landing(start,dest,water)
            fraction=min(rect_contact(start,dest,(r,),36) for r in blocked)
            if fraction<=0:return tuple(round(v) for v in start)
            edge=point_at(start,dest,fraction)
            dest=tuple(math.floor(v) if z>a else math.ceil(v) if z<a else round(v)
                       for v,a,z in zip(edge,start,dest))
        return tuple(round(v) for v in start)

    def _mobile_tank_landing(self,start,dest,water=()):
        """A clear landing must leave at least one ordinary 24px exit.

        A 72px pocket between walls can fit the body exactly, yet leave no
        legal movement until another dash. Only that dead-end case searches
        backward along the original clamped ray, at <=1px axis intervals.
        It never extends skill range or searches sideways/across a new gate.
        Normal landings, cooldowns and wall-crossing skill rules are unchanged.
        The rare fallback tests at most ceil(max(abs(dest-start))) positions,
        bounded by this map's tank bounds; ordinary landings need one exit.
        """
        directions=((-1,-1),(0,-1),(1,-1),(1,0),(1,1),(0,1),(-1,1),(-1,0))
        def mobile(pos):
            return any(self.can_walk_step(pos,(pos[0]+24*x,pos[1]+24*y),water)
                       for x,y in directions)
        if mobile(dest):return dest
        start=self.clamp_tank_position(start)
        steps=max(1,math.ceil(max(abs(b-a) for a,b in zip(start,dest))))
        previous=dest
        for i in range(steps-1,-1,-1):
            point=tuple(round(v) for v in point_at(start,dest,i/steps))
            if point==previous:continue
            previous=point
            if not self.can_walk_to(point) or self.wall_contact(point,point,35.999) is not None:continue
            if rect_contact(start,point,water,35.999) is not None:continue
            if mobile(point):return point
        # Do not replace a clear endpoint by an invalid/corrupt saved origin.
        # A trapped origin with no safe point on this ray needs a different aim.
        return dest

    def wall_contact(self,start,dest,padding=0,*,exclude=(),bullets=False):
        # Map geometry only. Moving actors, vision eligibility and temporary
        # water walls remain checked by their existing callers every time.
        return self._wall_contact_cached(tuple(start),tuple(dest),padding,tuple(exclude),bullets)

    def _wall_contact(self,start,dest,padding,exclude,bullets):
        # Native -2 blocks stop vehicles but permit bullets. NPC obstacles stop both.
        # Aim clearance may pad a bullet line without turning it into a dash.
        native=self._cpp_bullet_index if bullets or not padding else self._cpp_move_index
        # Exclusions retain the original Python set semantics. Temporary water
        # walls and actors are never put into these immutable map indexes.
        if native is not None and not exclude:
            contact=native.contact(start,dest,padding)
            if contact is not NotImplemented:return contact
        bins=self._bullet_bins if bullets or not padding else self._move_bins
        rects=set()
        for x in range(math.floor((min(start[0],dest[0])-padding)/192),math.floor((max(start[0],dest[0])+padding)/192)+1):
            for y in range(math.floor((min(start[1],dest[1])-padding)/192),math.floor((max(start[1],dest[1])+padding)/192)+1):
                rects.update(bins.get((x,y),()))
        return rect_contact(start,dest,rects.difference(exclude) if exclude else rects,padding)

    def _walk_contact(self,start,end,*,objects=False):
        """72px body contact against one current walk layer, without bullets."""
        bins,native = ((self._walk_object_bins,self._cpp_object_index) if objects
                       else (self._walk_terrain_bins,self._cpp_terrain_index))
        if native is not None:
            contact=native.contact(start,end,35.999)
            if contact is not NotImplemented:return contact
        rects=set()
        for x in range(math.floor((min(start[0],end[0])-36)/192),math.floor((max(start[0],end[0])+36)/192)+1):
            for y in range(math.floor((min(start[1],end[1])-36)/192),math.floor((max(start[1],end[1])+36)/192)+1):
                rects.update(bins.get((x,y),()))
        return rect_contact(start,end,rects,35.999)

    def _walk_bounds(self,pos):
        l,t,r,b=self.bounds
        return l<=pos[0]<=r and t<=pos[1]<=b and self.in_playable_region(pos)

    @staticmethod
    def _walk_grid(pos):
        return tuple(math.floor((v-36)/24)*24+36 for v in pos)

    def _walk_grid_clear(self,pos):
        grid=self._walk_grid(pos)
        return self._walk_bounds(grid) and self._walk_contact(grid,grid) is None

    def can_walk_to(self,pos):
        """Keep native nine-cell poses and admit a fully clear 72px body.

        Authored terrain may be off the24px grid. Requiring only the floored
        grid footprint can close a real82px corridor or reject a safe skill
        landing beside a half-pixel wall. The extra route uses the full72px
        body against the same terrain, never a smaller skin-dependent box.
        NPCs always retain their exact rectangles; actual bounds/exterior
        apply to both routes. Native-legal off-grid corner poses still work.
        """
        return (self._walk_bounds(pos) and self._walk_contact(pos,pos,objects=True) is None
                and (self._walk_grid_clear(pos) or self._walk_contact(pos,pos) is None))

    def can_walk_step(self,start,dest,water=()):
        """Validate every occupancy interval of a normal movement segment.

        Native grid occupancy only changes at36+24k on either axis. Between
        these boundaries, a clear grid footprint or a clear continuous body
        is sufficient. Checking intervals prevents a diagonal with two legal
        endpoints from crossing an illegal corner in between, without a
        pixel loop. Normal24px steps have at most two interior boundaries.
        """
        if not self.can_walk_to(start) or not self.can_walk_to(dest):return False
        if (self._walk_contact(start,dest,objects=True) is not None
                or rect_contact(start,dest,water,35.999) is not None
                or rect_contact(start,dest,self._playable_exterior,35.999) is not None):return False
        if self._walk_contact(start,dest) is None:return True
        cuts={0.,1.}
        for a,b in zip(start,dest):
            if a==b:continue
            lo,hi=sorted((a,b))
            for cell in range(math.floor((lo-36)/24)+1,math.ceil((hi-36)/24)):
                fraction=(36+24*cell-a)/(b-a)
                if 0<fraction<1:cuts.add(fraction)
        cuts=sorted(cuts)
        if any(not self.can_walk_to(point_at(start,dest,t)) for t in cuts[1:-1]):return False
        for left,right in zip(cuts,cuts[1:]):
            if self._walk_grid_clear(point_at(start,dest,(left+right)/2)):continue
            if self._walk_contact(point_at(start,dest,left),point_at(start,dest,right)) is not None:return False
        return True

    def recover_walk_position(self,pos,water=(),occupied=()):
        """Exit only a shallow overlap through its nearest boundary.

        This is a server-owned repair for an already-invalid saved/interrupted
        pose, not a nearest-free teleport. Travel is bounded by one diagonal
        native step; each overlapping rectangle must be exited on a nearest
        side and no other rectangle may be entered. A deep overlap, closed
        gate crossing, occupied endpoint or water path therefore stays put.
        """
        if self.can_walk_to(pos) and rect_contact(pos,pos,water,35.999) is None:return pos
        if not self._walk_bounds(pos):return None
        rectangles=tuple(dict.fromkeys(self.movement_walls+self._playable_exterior+tuple(water)))
        overlaps=[r for r in rectangles if rect_contact(pos,pos,(r,),35.999) is not None]
        if not overlaps:return None
        xs,ys={pos[0]},{pos[1]}
        exits=[]
        for l,t,r,b in overlaps:
            distances=(pos[0]-(l-36),r+36-pos[0],pos[1]-(t-36),b+36-pos[1])
            nearest=min(distances)
            sides={i for i,d in enumerate(distances) if d<=nearest+.001}
            exits.append((l,t,r,b,sides))
            if 0 in sides:xs.add(math.floor(l-36))
            if 1 in sides:xs.add(math.ceil(r+36))
            if 2 in sides:ys.add(math.floor(t-36))
            if 3 in sides:ys.add(math.ceil(b+36))
        others=tuple(r for r in rectangles if r not in overlaps)
        legal=[]
        for x in xs:
            for y in ys:
                dest=(x,y)
                if dest==pos or max(abs(x-pos[0]),abs(y-pos[1]))>24:continue
                if not self.can_walk_to(dest) or rect_contact(dest,dest,rectangles,35.999) is not None:continue
                if any(math.dist(dest,other)<72 for other in occupied):continue
                if rect_contact(pos,dest,others,35.999) is not None:continue
                if not all((0 in sides and x<=l-36) or (1 in sides and x>=r+36)
                           or (2 in sides and y<=t-36) or (3 in sides and y>=b+36)
                           for l,t,r,b,sides in exits):continue
                legal.append(dest)
        return min(legal,key=lambda p:(math.dist(pos,p),p)) if legal else None

    def walk_end(self,start,dest,water=()):
        # MOVE_NORMAL still describes one whole24px step. Longer navigation
        # probes check each segment and stop at the last whole safe endpoint.
        steps=max(1,math.ceil(max(abs(b-a) for a,b in zip(start,dest))/24))
        end=tuple(start)
        for i in range(1,steps+1):
            point=tuple(round(v) for v in point_at(start,dest,i/steps))
            if not self.can_walk_step(end,point,water):break
            end=point
        return end
