"""Capture maps: authoritative ownership, native UI and fair bot goals."""
from battle_participants import human, private
import math
import struct

RADIUS=60
SCORE_INTERVAL=3000
WIN_SCORE=1000


def install(arena):
    arena.pk['flags']=[dict(definition,capture_camp=0,capture_started_at=0,
                             score_due_at=0,wire=None)
                       for definition in arena.geometry.data['flags']]


def eligible(actor,now):
    return (actor.alive and actor.camp in (1,2) and not actor.info.get('npc_template')
            and not actor.is_untargetable() and not actor.in_stasis()
            and 26 not in actor.buff_types(now))


def wire(flag,now):
    seconds=min(flag['capture_ms']//1000,max(0,(now-flag['capture_started_at'])//1000)) if flag['capture_camp'] else 0
    progress=-seconds if flag['capture_camp']==1 else seconds
    # scoreTime is unused by the current native flag/UI views. Absolute match
    # times stay server-side, including across a frozen restart/checkpoint.
    return flag['index'],flag['camp'],flag['locked'],progress,0


def snapshot(arena,now=None):
    now=arena.clock() if now is None else now
    flags=arena.pk['flags']
    return 1565,struct.pack('<H',len(flags))+b''.join(struct.pack('<4iI',*wire(f,now)) for f in flags)


def tick(arena,now):
    if arena.tank_test:return []
    if arena.pk['finished'] or now<arena.pk.get('intro_until',0):return []
    tanks=[a for a in arena.actors.values() if eligible(a,now)]
    packets=[];changed=False
    for flag in arena.pk['flags']:
        counts={c:sum(a.camp==c and math.dist(a.position_at(now),flag['position'])<=RADIUS
                      for a in tanks) for c in (1,2)}
        leading=1 if counts[1]>counts[2] else 2 if counts[2]>counts[1] else 0
        if flag['locked'] or not leading or leading==flag['camp']:
            flag.update(capture_camp=0,capture_started_at=0)
        elif leading!=flag['capture_camp']:
            flag.update(capture_camp=leading,capture_started_at=now)
        elif now-flag['capture_started_at']>=flag['capture_ms']:
            flag.update(camp=leading,capture_camp=0,capture_started_at=0,score_due_at=now+SCORE_INTERVAL)
        state=wire(flag,now)
        if state!=flag['wire']:
            flag['wire']=state;changed=True
    # All ownership changes precede scoring; list order must not decide the
    # three-flag bonus when the last point changes hands on a score tick.
    owners={f['camp'] for f in arena.pk['flags']}
    double=len(arena.pk['flags'])==3 and len(owners)==1 and 0 not in owners
    for flag in arena.pk['flags']:
        if flag['camp'] and flag['score_due_at'] and now>=flag['score_due_at']:
            camp=flag['camp'];gain=min(flag['score']*(2 if double else 1),WIN_SCORE-arena.pk['scores'][camp])
            arena.pk['scores'][camp]+=gain
            flag['score_due_at']=now+SCORE_INTERVAL
            # S1732 increments native BattleModel itself: don't add an absolute
            # score packet before it (which would double-count on the client).
            packets.append((1732,struct.pack('<3i',flag['index'],camp,gain)))
    if changed:packets.insert(0,snapshot(arena,now))
    if max(arena.pk['scores'].values())>=WIN_SCORE:
        from pk_rules import finish
        packets+=finish(arena,now)
    return packets


def assignments(arena,actor,seen,now):
    """Allocate the team's bots from public flags and delayed team sightings.

    Brief orders avoid changing lanes every decision. An idle human receives
    no order; their presence counts only on the flag they actually occupy.
    """
    flags=arena.pk['flags'];camp=actor.camp
    friends=[a for a in arena.actors.values() if not human(a) and a.camp==camp
             and eligible(a,now) and not arena.bot_brains.get(a.id,{}).get('repair_goal')]
    signature=(tuple(f['camp'] for f in flags),tuple(a.id for a in friends))
    orders=arena.pk.setdefault('flag_orders',{})
    previous=orders.get(camp)
    if previous and previous['signature']==signature and now<previous['flag_order_until']:
        return previous['assignments']
    # Union only already-sampled reports. No fresh enemy position/HP read here.
    reports={s['id']:s for a in friends for s in arena.bot_brains.get(a.id,{}).get('observations',[])}
    reports.update((s['id'],s) for s in seen)
    enemies=[s for s in reports.values() if not s.get('objective') and now-s.get('observed_at',now)<=700]
    tasks=[]
    for f in flags:
        near=sum(math.dist(s['pos'],f['position'])<240 for s in enemies)
        present=sum(human(a) and a.camp==camp and eligible(a,now) and math.dist(a.position_at(now),f['position'])<=RADIUS for a in arena.actors.values())
        count=max(0,min(4,near+1)-present) if f['camp']!=camp or near else 0
        if count:tasks.append((f,count,near))
    available=list(friends);result={}
    while tasks and available:
        # Prefer attainable captures, reinforce observed fights, then rotate.
        f,count,near=min(tasks,key=lambda task:
            min(math.dist(a.position_at(now),task[0]['position']) for a in available)
            -task[0]['score']*12+(450 if task[2]>=len(available) else 0))
        tasks.remove((f,count,near))
        squad=sorted(available,key=lambda a:(math.dist(a.position_at(now),f['position']),a.id))[:count]
        for a in squad:result[a.id]=f['index'];available.remove(a)
    for a in available:
        f=min(flags,key=lambda f:math.dist(a.position_at(now),f['position'])
              +sum(i==f['index'] for i in result.values())*450
              +(450 if f['camp']==camp else 0)-f['score']*12)
        result[a.id]=f['index']
    orders[camp]=dict(signature=signature,flag_order_until=now+2400,assignments=result)
    return result


def goal(arena,actor,seen,now):
    """Use public ownership, friendly status and delayed visible observations.

    A few tanks occupy the small circle; others cover its approaches. No live
    enemy lookup or authoritative capture counts enter this policy.
    """
    orders=assignments(arena,actor,seen,now) if len(arena.pk['flags'])>1 else None
    flag=next((f for f in arena.pk['flags'] if orders and f['index']==orders.get(actor.id)),arena.pk['flags'][0])
    center=flag['position'];pos=actor.position_at(now)
    enemies=[s for s in seen if math.dist(s['pos'],center)<480]
    on_flag=sum(math.dist(s['pos'],center)<=RADIUS for s in enemies)
    friends=[a for a in arena.actors.values() if a.camp==actor.camp and eligible(a,now)
             and (not human(a) or math.dist(a.position_at(now),center)<=RADIUS)
             and (orders is None or human(a) or orders.get(a.id)==flag['index'])
             and not arena.bot_brains.get(a.id,{}).get('repair_goal')]
    # Count the human only once actually on the objective. Assigning a distant
    # human as the sole holder would make every bot wait for them to capture.
    # Keep healthy front-line tanks on the flag; somebody already holding it
    # gets priority so role changes don't repeatedly abandon capture progress.
    friends.sort(key=lambda a:(math.dist(a.position_at(now),center)>RADIUS,
                              float(a.hp/a.max_hp)<.4,
                              a.info['tank_id'] not in (10000056,10000031),
                              math.dist(a.position_at(now),center),a.id))
    needed=min(4,max(1,on_flag+1))
    if orders is not None and flag['camp']==actor.camp and not enemies:needed=0
    holders=friends[:needed]
    if actor in holders:
        slot=holders.index(actor)
        # Four 24-grid positions fit the circle with the bot's 64px spacing.
        # Human teammates
        # count as holders but are never steered by this function.
        offset=((-48,0),(48,0),(0,-48),(0,48))[slot] if needed>1 else (0,0)
        dest=(center[0]+offset[0],center[1]+offset[1])
        # A generic waypoint permits 20px arrival tolerance. If that leaves
        # this tank just outside the circle, take another real step inward.
        if math.dist(pos,center)>RADIUS and math.dist(pos,dest)<=24:dest=tuple(center)
        return 'flag_hold',dest
    if enemies:
        # Watch the known enemy approach; never chase beyond the objective.
        nearest=min(enemies,key=lambda s:math.dist(s['pos'],center))['pos']
        angle=math.atan2(nearest[1]-center[1],nearest[0]-center[0])
    else:
        start=arena.geometry.spawn(actor.camp)
        angle=math.atan2(start[1]-center[1],start[0]-center[0])
    covers=[a for a in friends if a not in holders]
    slot=covers.index(actor) if actor in covers else actor.id%4
    angle+=(slot-(len(covers)-1)/2)*.65
    distance=180 if actor.info['tank_id']==10000056 else 240
    return 'flag_cover',(center[0]+math.cos(angle)*distance,center[1]+math.sin(angle)*distance)
