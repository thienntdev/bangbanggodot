"""Geometry for the local map-101 combat checkpoint.

Tank contact radius 36 is a USER-APPROVED PLACEHOLDER (2026-09-26), not an
original server hitbox. Replace it when original collision evidence is found.
Map rectangles follow MapHeader/BlockInfoChunk.unSerialize in TankLib.dat.
"""
import math
from functools import lru_cache
from storage import setting, database_path

TANK_CONTACT_RADIUS = 36
# SelfTank.TANK_EDGE / SelfMoveRule.legalMove use a 72x72 movement footprint.
TANK_MOVE_HALF = 36


def actor_contact(start,end,actor,previous,now,radius=TANK_CONTACT_RADIUS):
    if hasattr(actor,'map_rect'):
        # Static map NPCs use the native rectangle, not the tank's circle.
        # A tiny tie bias lets damage happen before this same obstacle stops
        # the bullet; a different, earlier wall still wins.
        hit=rect_contact(start,end,(actor.map_rect,),max(0,radius-TANK_CONTACT_RADIUS))
        return max(0,hit-1e-7) if hit is not None else None
    return circle_contact(start,end,actor.position_at(previous),actor.position_at(now),radius)


def point_at(start, end, fraction):
    return tuple(a + (b - a) * fraction for a, b in zip(start, end))


def circle_contact(start, end, center_start, center_end, radius=TANK_CONTACT_RADIUS):
    """First contact fraction of two linearly moving centers, or None."""
    x, y = (a - b for a, b in zip(start, center_start))
    dx, dy = ((b - a) - (d - c) for a, b, c, d in
              zip(start, end, center_start, center_end))
    c = x*x + y*y - radius*radius
    if c <= 0:
        return 0.0
    a, b = dx*dx + dy*dy, 2*(x*dx + y*dy)
    discriminant = b*b - 4*a*c
    if a == 0 or discriminant < 0:
        return None
    t = (-b - math.sqrt(discriminant)) / (2*a)
    return t if 0 <= t <= 1 else None


def map101_walls():
    return _walls(str(database_path()))


@lru_cache(maxsize=1)
def _walls(database):
    return tuple(tuple(rect) for rect in setting('map101_walls'))


def map101_tank_bounds():
    return _tank_bounds(str(database_path()))


@lru_cache(maxsize=1)
def _tank_bounds(database):
    # Outer four rectangles from the original .map, already imported to SQLite.
    # The image is 1440x936; its playable enclosure is only 216..1224,72..864.
    walls = _walls(database)
    left = max(r for l,t,r,b in walls if l==0 and t==0 and b==936)
    right = min(l for l,t,r,b in walls if r==1440 and t==0 and b==936)
    top = max(b for l,t,r,b in walls if t==0 and l<=left and r>=right)
    bottom = min(t for l,t,r,b in walls if b==936 and l<=left and r>=right)
    return left+TANK_MOVE_HALF,top+TANK_MOVE_HALF,right-TANK_MOVE_HALF,bottom-TANK_MOVE_HALF


def clamp_tank_position(pos):
    left,top,right,bottom = map101_tank_bounds()
    return round(min(right,max(left,pos[0]))),round(min(bottom,max(top,pos[1])))


def clip_tank_motion(start, dest):
    """Stop at the enclosing wall along the original ray; ignore inner walls."""
    start = clamp_tank_position(start)
    left,top,right,bottom = map101_tank_bounds()
    fraction = 1.0
    for a,b,lo,hi in zip(start,dest,(left,top),(right,bottom)):
        if b>hi:
            fraction = min(fraction,(hi-a)/(b-a))
        elif b<lo:
            fraction = min(fraction,(lo-a)/(b-a))
    return clamp_tank_position(point_at(start,dest,fraction))


def clear_tank_landing(start, dest):
    """Cross inner walls only if the whole 72px body can land beyond them.

    Backtrack along the requested segment, never extend skill range or choose
    the opposite wall edge. Earlier walls already crossed remain passable.
    """
    dest = tuple(round(v) for v in dest)
    for _ in range(len(map101_walls())):
        blocked = [r for r in map101_walls()
                   if rect_contact(dest,dest,(r,),TANK_MOVE_HALF-.001) is not None]
        if not blocked:
            return dest
        fraction = min(rect_contact(start,dest,(r,),TANK_MOVE_HALF) for r in blocked)
        if fraction<=0:
            return tuple(round(v) for v in start)
        edge = point_at(start,dest,fraction)
        # Round toward the origin: ordinary rounding can put a diagonal landing
        # half a pixel back into the wall when encoded as integer coordinates.
        dest = tuple(math.floor(v) if b>a else math.ceil(v) if b<a else round(v)
                     for v,a,b in zip(edge,start,dest))
    return tuple(round(v) for v in start)


def wall_contact(start, end, padding=0):
    """Segment vs map's non-through rectangles; return earliest fraction."""
    return rect_contact(start,end,map101_walls(),padding)


def rect_contact(start,end,rectangles,padding=0):
    """Swept contact with axis-aligned rectangles (also used by native NPC walls)."""
    x,y=start;dx,dy=end[0]-x,end[1]-y
    first = None
    for left, top, right, bottom in rectangles:
        low, high = 0.0, 1.0
        # Slab clipping, with the same inclusive edges and divisions as before.
        # Reject a missed axis immediately; sight probes run this millions of
        # times and need neither temporary tuples nor a sort for two numbers.
        if dx==0:
            if not left-padding<=x<=right+padding:continue
        else:
            t1,t2=(left-padding-x)/dx,(right+padding-x)/dx
            if t1>t2:t1,t2=t2,t1
            if t1>low:low=t1
            if t2<high:high=t2
            if low>high:continue
        if dy==0:
            if not top-padding<=y<=bottom+padding:continue
        else:
            t1,t2=(top-padding-y)/dy,(bottom+padding-y)/dy
            if t1>t2:t1,t2=t2,t1
            if t1>low:low=t1
            if t2<high:high=t2
            if low>high:continue
        if first is None or low<first:first=low
        if first==0:return first
    return first
