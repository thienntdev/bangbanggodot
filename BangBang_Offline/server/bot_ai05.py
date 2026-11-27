"""AI05 uses native recasts and delayed aim, never live enemy coordinates."""
import math

from bot_ai01 import aim_in_range,ratio
from bot_ai04 import mobility,mobility_goal_ok,near
from combat_geometry import point_at
from melee_common import aimed,in_strip

TANKS=frozenset((10000067,10000075,10000077,10000081,10000096,10000099))
LAST_STAND={10000067:(10,2),10000075:(1,2),10000077:(10,2),
            10000081:(10,2),10000096:(2,10),10000099:(1,10)}


def desired_range(actor,now):
    tank=actor.info['tank_id']
    if tank==10000075:return 130 if actor.has_buff(349204,now) else 200
    return {10000067:170,10000077:260,10000081:430,10000096:180,10000099:170}[tank]


def basic_range(actor,now):
    if actor.info['tank_id']==10000075 and actor.has_buff(349111,now):return 480
    if actor.info['tank_id']==10000096:return 408
    return int(actor.stats['nFireRange'])


def observation(actor,target,now):
    tank=actor.info['tank_id']
    mark={10000067:342208,10000077:351112,10000081:355202,10000099:374405}.get(tank)
    return dict(ai05_mark=bool(mark and target.has_buff(mark,now) and target.buff_sources.get(mark)==actor.id),
                hp_raw=float(target.hp))


def recast(actor,slot,now):
    tank=actor.info['tank_id']
    return (tank==10000075 and slot==1 and actor.has_buff(349204,now) or
            tank==10000099 and (slot==10 and actor.r_window['end']>now or slot==2 and bool(actor.ready)))


def support_choices(actor,allies,seen,now):
    # Native Sword God R cleanses hard control and also supplies energy.
    if actor.info['tank_id']==10000081 and actor.blocked('attack',now):
        return [(10,actor.position_at(now),actor.id)]
    return []


def steer(actor,brain,dest):
    brain['aim']=dest  # Also the mouse direction used by Zoro's reflected shots.
    if actor.info['tank_id']==10000096 and actor.vanish and actor.vanish['slot']==2:
        actor.vanish['dest']=dest  # Native C514 permits this; Mulan charge does not.


def incoming(actor,brain,now):
    pos=actor.position_at(now)
    for shot in brain.get('bullets',[]):
        vx,vy=shot['velocity'];speed2=vx*vx+vy*vy
        if not speed2:continue
        age=max(0,(now-shot['observed_at'])/1000)
        bx,by=shot['pos'][0]+vx*age,shot['pos'][1]+vy*age
        eta=((pos[0]-bx)*vx+(pos[1]-by)*vy)/speed2
        if 0<=eta<=.8 and math.dist(pos,(bx+vx*eta,by+vy*eta))<90:return True
    return False


def mulan_recast_point(actor,brain,seen,now):
    pos=actor.position_at(now)
    marked=[s for s in seen if s.get('ai05_mark') and math.dist(pos,s['pos'])<=600]
    if not marked:return None
    target=min(marked,key=lambda s:(s['hp_raw'],s['id']))
    first=actor.move_destination(pos,target['pos'])
    dx,dy=target['pos'][0]-pos[0],target['pos'][1]-pos[1]
    end=actor.move_destination(first,aimed(first,(first[0]+dx,first[1]+dy),168,fixed=True))
    friends=sum(a.alive and a.camp==actor.camp and not a.info.get('npc_template')
                and math.dist(end,a.position_at(now))<=480 for a in actor.arena.actors.values())
    if ratio(actor)<.45 or near(end,seen,360)>friends+1 or not mobility_goal_ok(brain,pos,end):return None
    return target


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);cluster=near(target['pos'],seen,180);result=[]
    if tank==10000067:
        if distance<=225:result.append((10,dest,ident))
        if distance<=470 and (cluster>=2 or retreat or target['hp']<.55):result.append((2,dest,ident))
        if retreat and distance<320 or not retreat and 240<distance<500:
            point=mobility(actor,brain,target,seen,dest,retreat,now,360,fixed=True)
            if point is not None:result.append((1,point,ident))
    elif tank==10000075:
        second=actor.has_buff(349204,now)
        if second and distance<=160:result.append((1,dest,ident))
        if not blocked and distance<=basic_range(actor,now) and actor.has_buff(349111,now):
            result.append((0,dest,ident))
        if distance<=160 and not retreat:result.append((1,dest,ident))
        if not second and (retreat and distance<320 or not retreat and 180<distance<390):
            point=mobility(actor,brain,target,seen,dest,retreat,now,240,blink=True)
            if point is not None:result.append((1,point,ident))
        if distance<=700 and (retreat or cluster>=2 or target['hp']<.55):
            point=mobility(actor,brain,target,seen,dest,retreat,now,720,blink=True)
            if point is not None:result.append((2,point,ident))
            elif not retreat and distance<180:
                point=aim_in_range(actor,dest,120,now)
                if mobility_goal_ok(brain,pos,actor.blink_destination(pos,point)):result.append((2,point,ident))
        if distance<=480:result.append((10,dest,ident))
    elif tank==10000077:
        if not actor.has_buff(351401,now) and incoming(actor,brain,now):result.append((10,dest,ident))
        if not blocked and distance<=330 and (target.get('ai05_mark') or actor.scatter_count):result.append((0,dest,ident))
        if retreat and distance<360 or not retreat and 280<distance<600:
            point=mobility(actor,brain,target,seen,dest,retreat,now,456,fixed=True,blink=True)
            if point is not None:result.append((1,point,ident))
        if distance<=480:result.append((2,dest,ident))
    elif tank==10000081:
        if retreat and distance<450 or distance<196 or actor.mp<25 and distance<840:
            result.append((10,pos,actor.id))
        tanks=[s for s in seen if not s.get('objective',False)]
        if any(math.dist(pos,s['pos'])<=1200 and (s.get('ai05_mark') or s['hp']<.5) for s in tanks):
            result.append((2,dest,ident))
        if distance<=820:result.append((1,dest,ident))
    elif tank==10000096:
        if distance<=210 and (not retreat or ratio(actor)<.5):result.append((2,dest,ident))
        if not blocked and distance<=basic_range(actor,now) and actor.has_buff(371121,now):result.append((0,dest,ident))
        if retreat and distance<350 or not retreat and 230<distance<490:
            # E stops at ordinary walls too, unlike most other dashes.
            direction=point_at(pos,target['pos'],-1) if retreat else dest
            requested=aimed(pos,direction,336,fixed=True)
            wall=actor.arena.geometry.wall_contact(pos,requested,36)
            if wall is None or wall*336>=max(72,distance-50):
                point=mobility(actor,brain,target,seen,dest,retreat,now,336,fixed=True)
                if point is not None:result.append((1,point,ident))
        if retreat and distance<350 or not retreat and 210<distance<450:
            point=mobility(actor,brain,target,seen,dest,retreat,now,360,blink=True)
            if point is not None:result.append((10,point,ident))
    elif tank==10000099:
        if actor.ready:
            elapsed=now-actor.ready['begin'];length=120+360*min(1,elapsed/3000)
            if elapsed>=700 and any(in_strip(s['pos'],pos,actor.ready['dest'],length,300) for s in seen):
                result.append((2,actor.ready['dest'],ident))
            return result
        if actor.r_window['end']>now:
            selected=mulan_recast_point(actor,brain,seen,now) if not retreat else None
            if selected:result.append((10,selected['pos'],selected['id']))
        elif distance<=470:result.append((10,aim_in_range(actor,dest,480,now),ident))
        if retreat and distance<320 or not retreat and 210<distance<500:
            point=mobility(actor,brain,target,seen,dest,retreat,now,360,fixed=True)
            if point is not None:result.append((1,point,ident))
        if not retreat and distance<430 and (cluster>=2 or distance<230):result.append((2,dest,ident))
    return result
