"""AI08: native hooks, charged release, carry and delayed reflection aim."""
import math

from bot_ai01 import ratio
from bot_ai04 import mobility,mobility_goal_ok,near
from bot_ai05 import incoming
from combat_geometry import point_at,rect_contact,circle_contact
from melee_common import aimed

TANKS=frozenset((10000008,10000100,10000078,10000110,10000111))
LAST_STAND={10000008:(2,1),10000100:(2,10),10000078:(2,10),10000110:(2,10),10000111:(2,10)}


def desired_range(actor,now):
    return {10000008:210,10000100:190,10000078:120,10000110:140,10000111:340}[actor.info['tank_id']]


def recast(actor,slot,now):
    return actor.info['tank_id']==10000110 and slot==2 and bool(actor.ready)


def basic_allowed(actor,brain,target,now):
    if (actor.info['tank_id']!=10000008 or not actor.has_buff(303113,now)
            or target.get('structure') or target.get('barrier')):return True
    pos=actor.position_at(now);distance=math.dist(pos,target['pos'])
    end=actor._clipped(pos,point_at(pos,target['pos'],max(0,distance-72)/max(1,2*distance)))
    return mobility_goal_ok(brain,pos,end)


def safe_endpoint(actor,brain,seen,end,now,retreat=False):
    pos=actor.position_at(now)
    if not mobility_goal_ok(brain,pos,end):return False
    if retreat:return near(end,seen,300)<=near(pos,seen,300)
    allies=sum(a.alive and a.camp==actor.camp and not a.info.get('npc_template')
               and math.dist(end,a.position_at(now))<=480 for a in actor.arena.actors.values())
    return ratio(actor)>=.45 and near(end,seen,360)<=allies+1


def hook_aim(actor,brain,target,seen,now,retreat):
    """A thin hook must find a surface; rank its body-sized landing, not the ray."""
    pos=actor.position_at(now);goal=brain.get('goal',pos) if retreat else target['pos']
    angle=math.atan2(goal[1]-pos[1],goal[0]-pos[0]);options=[]
    water=actor.arena.water_rects(now)
    for offset in (0,-25,25,-50,50,-80,80):
        rad=angle+math.radians(offset)
        ray=(round(pos[0]+720*math.cos(rad)),round(pos[1]+720*math.sin(rad)))
        hits=[h for h in (actor.arena.geometry.wall_contact(pos,ray),rect_contact(pos,ray,water)) if h is not None]
        if not hits:continue
        latch=point_at(pos,ray,min(hits));hit=actor.arena.geometry.wall_contact(pos,latch,36)
        request=point_at(pos,latch,max(0,hit-.0001)) if hit is not None else latch
        end=actor.move_destination(pos,request)
        if math.dist(pos,end)<72 or not safe_endpoint(actor,brain,seen,end,now,retreat):continue
        if retreat:
            if math.dist(end,goal)>math.dist(pos,goal)-60:continue
        elif math.dist(end,target['pos'])>180 or math.dist(end,target['pos'])>math.dist(pos,target['pos'])-60:continue
        options.append((math.dist(end,goal),ray))
    return min(options)[1] if options else None


def steer(actor,brain,dest,seen,retreat,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now)
    brain['aim']=dest
    if tank==10000100 and actor.combo and actor.combo['kind']=='r':
        actor.combo['aim']=dest  # Native C514 can steer only the later bombs.
    if tank==10000111 and actor.dash and not actor.dash['bounced']:
        point=brain.get('goal',dest) if retreat else dest
        end=actor.move_destination(pos,aimed(pos,point,300,fixed=True))
        actor.dash['dest']=point if safe_endpoint(actor,brain,seen,end,now,retreat) else pos
    if tank==10000008 and actor.fields and not retreat and not brain.get('objective'):
        fields=[f for f in actor.fields.values() if f['end']>now and math.dist(pos,f['pos'])<280]
        if fields:
            field=min(fields,key=lambda f:math.dist(pos,f['pos']));goal=brain.get('goal',pos)
            if math.dist(goal,field['pos'])>240 and near(field['pos'],seen,300):
                brain['goal']=point_at(field['pos'],goal,240/math.dist(goal,field['pos']))


def support_choices(actor,allies,seen,now,brain=None,recovering=False):
    brain=brain or {};pos=actor.position_at(now);tank=actor.info['tank_id']
    if tank==10000110 and actor.ready:
        elapsed=now-actor.ready['begin'];radius=120+240*min(1,elapsed/3000)
        combat=[s for s in seen if not s.get('barrier') and not s.get('structure')]
        # Release only after the native minimum, when foes may leave the burst
        # or the charge prevents retreat. Otherwise native auto-release owns it.
        if elapsed>=750 and (recovering or not combat or near(pos,combat,float(radius)) and
                             (elapsed>=1500 or ratio(actor)<.35)):
            return [(2,pos,actor.id)]
    if tank==10000078 and not actor.ready and not actor.reload and not actor.dash and not actor.hook:
        if actor.mp<=50 or ratio(actor)<.5 and near(pos,seen,480) or actor.blocked('attack',now):
            point=brain.get('goal',pos)
            if point==pos:point=(pos[0]+1,pos[1])
            end=actor.move_destination(pos,aimed(pos,point,336,fixed=True))
            if safe_endpoint(actor,brain,seen,end,now,True):return [(10,point,actor.id)]
    return []


def choices(actor,brain,target,seen,dest,retreat,blocked,now):
    tank=actor.info['tank_id'];pos=actor.position_at(now);ident=target['id']
    distance=math.dist(pos,target['pos']);cluster=near(target['pos'],seen,180);result=[]
    if tank==10000008:
        if actor.dash:return []
        if actor.has_buff(303113,now) and not blocked and distance<=int(actor.stats['nFireRange']) and basic_allowed(actor,brain,target,now):
            result.append((0,dest,ident))
        if distance<=270 and (not retreat or distance<180):result.append((2,pos,actor.id))
        if retreat and distance<300 or not retreat and 230<distance<520:
            point=mobility(actor,brain,target,seen,dest,retreat,now,360,fixed=True)
            if point is not None:
                end=actor._clipped(pos,aimed(pos,point,360,fixed=True))
                if math.dist(pos,end)>=72 and (retreat or math.dist(end,target['pos'])<=180):
                    result.append((1,point,ident))
        if distance<=600 and not actor.has_buff(303113,now):result.append((10,dest,ident))
    elif tank==10000100:
        if actor.combo:return []
        if distance<=240 and safe_endpoint(actor,brain,seen,target['pos'],now) and (cluster>=2 or target['hp']<.6):
            result.append((2,dest,ident))
        if distance<=408 and safe_endpoint(actor,brain,seen,target['pos'],now,retreat):
            back=actor.move_destination(target['pos'],aimed(target['pos'],pos,336,fixed=True))
            if safe_endpoint(actor,brain,seen,back,now,retreat):result.append((10,dest,ident))
        if retreat and distance<320 or not retreat and 240<distance<550:
            point=mobility(actor,brain,target,seen,dest,retreat,now,408,fixed=True)
            if point is not None:
                end=actor.move_destination(pos,aimed(pos,point,408,fixed=True))
                # A first hit adds a second 240-unit carry past the victim.
                carry=actor.move_destination(pos,aimed(pos,point,distance+168,fixed=True))
                if safe_endpoint(actor,brain,seen,end,now,retreat) and safe_endpoint(actor,brain,seen,carry,now,retreat):
                    result.append((1,point,ident))
    elif tank==10000078:
        if actor.ready or actor.hook:return []
        if distance<=144:result.append((2,pos,actor.id))
        if not actor.dash and actor.e_count and actor.mp>=50 and actor.cooldowns[1]<=now and (retreat or distance>190):
            point=hook_aim(actor,brain,target,seen,now,retreat)
            if point is not None:result.append((1,point,ident))
    elif tank==10000110:
        if actor.ready or actor.dash:return []
        if distance<=(192 if actor.r_window and actor.r_window['phase']==2 else 168):
            result.append((10,dest,ident))
        if actor.r_window:return result  # Do not spend its short follow-up window charging Space.
        if distance<=300 and (cluster>=2 or distance<210 or incoming(actor,brain,now)):
            result.append((2,pos,actor.id))
        if retreat and distance<350 or not retreat and 300<distance<630:
            point=mobility(actor,brain,target,seen,dest,retreat,now,480,fixed=True)
            if point is not None:result.append((1,point,ident))
    elif tank==10000111:
        if actor.ready or actor.dash:return []
        if distance<=570:result.append((10,dest,ident))
        if distance<=660 and (cluster>=2 or target['hp']<.6 or distance<420):result.append((2,dest,ident))
        if retreat and distance<380 or not retreat and 280<distance<500 and incoming(actor,brain,now):
            point=mobility(actor,brain,target,seen,dest,retreat,now,300,fixed=True)
            if point is not None:
                end=actor.move_destination(pos,aimed(pos,point,300,fixed=True))
                bodies=[a.position_at(now) for a in actor.arena.actors.values() if a.id!=actor.id
                        and a.alive and a.camp==actor.camp and not a.info.get('npc_template')]
                bodies += [s['pos'] for s in seen if not s.get('objective')]
                hits=[h for p in bodies if (h:=circle_contact(pos,end,p,p)) is not None]
                if hits:
                    bounce=point_at(pos,end,min(hits))
                    second=actor.move_destination(bounce,aimed(bounce,point,300,fixed=True))
                    if not safe_endpoint(actor,brain,seen,second,now,retreat):return result
                result.append((1,point,ident))
    return result
