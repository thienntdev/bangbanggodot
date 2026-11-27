"""AI14: native stationary bonuses, resource modes and placed summons."""
import math

from bot_ai01 import ratio,aim_in_range
from bot_ai04 import mobility,near
from bot_ai13 import falcon_reload_dash
from combat_geometry import rect_contact

PEA,SNIPER,PUMPKIN,MINION,KURUMI=10000033,10000101,10000052,10000060,10000095
TANKS=frozenset((PEA,SNIPER,PUMPKIN,MINION,KURUMI))
LAST_STAND={PEA:(10,1),SNIPER:(1,0),PUMPKIN:(1,2,10),MINION:(10,2),KURUMI:(2,10,1)}
HELD=('flag_hold','survive','base_defend','bomb_escort','bomb_intercept')


def basic_range(actor,now):
    tank=actor.info['tank_id']
    if tank==PEA and actor.gatling:return 720
    if tank==SNIPER and (actor.special or actor.has_buff(376142,now)):return 960
    if tank==KURUMI and actor._basic(now)!=370100:return 600
    return int(actor.stats['nFireRange'])


def desired_range(actor,now):
    return min({PEA:440,SNIPER:600,PUMPKIN:400,MINION:390,KURUMI:390}[actor.info['tank_id']],basic_range(actor,now)-36)


def recast(actor,slot,now):
    return actor.info['tank_id']==PEA and slot==2 and actor.gatling


def must_travel(actor,brain,now):
    # Do not sit aiming/healing while a mode requires us somewhere else.
    return brain.get('objective') in HELD and math.dist(actor.position_at(now),brain.get('goal',actor.position_at(now)))>36


def adjust_goal(actor,brain,seen,now,recovering=False):
    tank=actor.info['tank_id'];pos=actor.position_at(now)
    if tank==PEA:
        if not seen and ratio(actor)<.85 and not must_travel(actor,brain,now):brain['goal']=pos
    elif tank==SNIPER and not recovering and ratio(actor)>=.4 and not must_travel(actor,brain,now):
        if seen and all(math.dist(pos,s['pos'])>=300 for s in seen):
            target=next((s for s in seen if s['id']==brain.get('target')),None)
            if target and math.dist(pos,target['pos'])<=960:
                exclude=(tuple(target['turret_rect']),) if target.get('turret_rect') else ()
                if actor.arena.geometry.wall_contact(pos,target['pos'],exclude=exclude) is None:brain['goal']=pos
    elif tank==MINION and not recovering and brain.get('objective') not in HELD:
        items=[x for x in actor.components.values() if x['generation']==actor.generation and x['end']>now
               and math.dist(pos,x['pos'])<=240 and near(x['pos'],seen,300)<=near(pos,seen,300)
               and actor.arena.geometry.wall_contact(pos,x['pos'],36) is None
               and rect_contact(pos,x['pos'],actor.arena.water_rects(now),36) is None]
        if items:brain['goal']=min(items,key=lambda x:math.dist(pos,x['pos']))['pos']


def placement(actor,dest,reach,seen,now):
    """Small set of legal placements, using terrain, allies and sightings only."""
    pos=actor.position_at(now);center=aim_in_range(actor,dest, min(reach,180),now)
    allies=[a.position_at(now) for a in actor.arena.actors.values() if a.alive and a.camp==actor.camp]
    for dx,dy in ((0,96),(0,-96),(96,0),(-96,0),(96,96),(-96,-96)):
        p=(round(center[0]+dx),round(center[1]+dy))
        if math.dist(pos,p)>reach or actor.arena.geometry.clamp_tank_position(p)!=p:continue
        if any(math.dist(p,q)<72 for q in allies) or near(p,seen,96):continue
        if actor.arena.geometry.wall_contact(p,p,36) is not None:continue
        if rect_contact(p,p,actor.arena.water_rects(now),36) is None:return p
    return None


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain if brain is not None else {};tank=actor.info['tank_id'];pos=actor.position_at(now)
    if tank==PEA and actor.gatling:
        if recovering or ratio(actor)<.3 or must_travel(actor,brain,now) or not near(pos,seen,720) or actor.mp<10:
            return [(2,pos,actor.id)]
    if getattr(actor,'ready',None) or now<actor.forced_until:return []
    if tank==PEA and seen and not near(pos,seen,480):
        carriers=[a for a in allies if a.alive and math.dist(pos,a.position_at(now))<=480
                  and near(a.position_at(now),seen,144)]
        if carriers:
            ally=max(carriers,key=lambda a:near(a.position_at(now),seen,144))
            return [(10,ally.position_at(now),ally.id)]
    if tank==PUMPKIN:
        injured=[a for a in (actor,*allies) if a.alive and ratio(a)<.6 and math.dist(pos,a.position_at(now))<=480]
        if injured:
            ally=min(injured,key=ratio)
            return [(1,ally.position_at(now),ally.id)]
    if tank==KURUMI and recovering and seen:
        target=min(seen,key=lambda s:math.dist(pos,s['pos']))
        point=mobility(actor,brain,target,seen,target['pos'],True,now,300)
        if point is not None:return [(1,point,target['id'])]
    return []


def structure_choices(actor,brain,target,seen,dest,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id'];result=[]
    if tank==PEA and not actor.gatling and actor.mp>=60 and ratio(actor)>=.4 and not must_travel(actor,brain,now):
        result.append((2,pos,actor.id))
    if tank==MINION and actor.e_count and actor.mp>=30 and math.dist(pos,target['pos'])<=600:
        point=placement(actor,dest,480,seen,now)
        if point is not None:result.append((1,point,ident))
    if tank==KURUMI:
        if actor._basic(now)==370100:
            point=falcon_reload_dash(actor,brain,seen,dest,now)
            if point is not None:result.append((1,point,ident))
        point=placement(actor,dest,336,seen,now) if math.dist(pos,target['pos'])<=700 else None
        if point is not None:result.append((10,point,ident))
    return result


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    if getattr(actor,'ready',None) or now<actor.forced_until:return []
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);result=[]
    if tank==PEA:
        if actor.gatling:
            if retreat:return [(2,pos,actor.id)]
            if distance<=720:result.append((0,dest,ident))
        if distance<=480:result.append((10,dest,ident))
        if distance<=420:result.append((1,aim_in_range(actor,dest,360,now),ident))
        if not retreat and not blocked and distance<=720 and ratio(actor)>=.4 and actor.mp>=60 and not actor.gatling and not must_travel(actor,brain,now):
            result.append((2,pos,actor.id))
    elif tank==SNIPER:
        if actor.special:
            return [(0,dest,ident)] if distance<=960 and not blocked else []
        if distance<=720 and (retreat or distance<360):result.append((1,dest,ident))
        if not retreat and not blocked and distance<=960:result.append((2,dest,ident))
        if distance<300 and not any(math.dist(pos,x['pos'])<96 for x in actor.traps.values()):result.append((10,pos,ident))
    elif tank==PUMPKIN:
        if distance<=600 and not actor.volley:result.append((10,dest,ident))
        if distance<=960 and not blocked and (near(target['pos'],seen,192)>=2 or distance>=360 or retreat):
            result.append((2,aim_in_range(actor,dest,960,now),ident))
        if distance<=480:result.append((1,aim_in_range(actor,dest,480,now),ident))
    elif tank==MINION:
        if not retreat:result+=structure_choices(actor,brain,target,seen,dest,now)
        if distance<=600:
            if near(target['pos'],seen,240)>=2 or retreat:result.append((2,aim_in_range(actor,dest,600,now),ident))
            if not blocked:result.append((10,dest,ident))
    elif tank==KURUMI:
        if actor._basic(now)!=370100 and distance<=600 and not blocked:result.append((0,dest,ident))
        if retreat:
            point=mobility(actor,brain,target,seen,dest,True,now,300)
            if point is not None:result.append((1,point,ident))
        else:result+=structure_choices(actor,brain,target,seen,dest,now)
        if distance<=600 and (near(target['pos'],seen,192)>=2 or retreat or target['hp']<.65):
            result.append((2,aim_in_range(actor,dest,600,now),ident))
    return result
