"""Approved one-shot PvE hazards; checkpointed state."""
import math
from combat_math import D
from combat_geometry import rect_contact
from death_city import put_scene,remove_scene
from death_mode import environment_hit
from pve_bomb_puzzles import activation_radius


def initialize(arena,*,airstrikes=False):
    packets=[]
    for ident,tpl,camp,x,y in arena.geometry.data['pve_props']:
        if tpl not in ((600,700,800) if airstrikes else (700,800)):continue
        rec=dict(source=ident,template=tpl,camp=camp,position=(x,y),active=False,done=False,visual=None)
        if tpl==800:rec['visual'],packet=put_scene(arena,tpl,(x,y));packets.append(packet)
        arena.pk['pve']['hazards'].append(rec)
    return packets


def contacts(arena,rec,radius,now):
    pos=rec['position'];result=[]
    for a in list(arena.actors.values()):
        if not a.alive or a.info.get('pve_hostage'):continue
        if rec['template'] in (600,700) and (a.camp==rec['camp'] or a.info.get('map_object')):continue
        dest=a.position_at(now)
        if math.dist(pos,dest)>radius:continue
        # Check per-kit stasis/stealth only for nearby eligible targets.
        if not a.is_area_targetable():continue
        ignore=(a.map_rect,) if hasattr(a,'map_rect') else ()
        if arena.geometry.wall_contact(pos,dest,exclude=ignore) is not None:continue
        if rect_contact(pos,dest,arena.water_rects(now)) is None:result.append(a)
    return result


def tick(arena,now):
    packets=[]
    for rec in arena.pk['pve']['hazards']:
        if rec['done']:continue
        mine=rec['template']==700;airstrike=rec['template']==600
        if not rec['active']:
            trigger=bool(contacts(arena,rec,60,now)) if mine or airstrike else (
                arena.player.alive and not arena.player.in_stasis() and
                math.dist(arena.player.position_at(now),rec['position'])<=activation_radius(arena,rec))
            if not trigger:continue
            if rec['visual']:packets.append(remove_scene(arena,rec['visual']))
            rec.update(active=True,end=now+(1200 if mine else 2000 if airstrike else 5000))
            rec['visual'],packet=put_scene(arena,702 if mine else 602 if airstrike else 802,rec['position']);packets.append(packet)
        if now<rec['end']:continue
        rec['done']=True
        packets.append(remove_scene(arena,rec['visual']));rec['visual']=None
        # Freeze ordinary blast contacts before opening the puzzle wall.
        # Linked bricks are a script objective, not four ordinary damage hits;
        # rear bricks cannot be shielded by their own front row.
        victims=contacts(arena,rec,120 if mine else 192 if airstrike else 216,now)
        if rec['template']==800:
            from pve_bomb_puzzles import detonate
            packets+=detonate(arena,rec,now)
        for actor in victims:
            raw=actor.max_hp*D('.25') if mine else actor.max_hp*D('.4') if airstrike else D(1000)+actor.max_hp*D('.55')
            packets+=environment_hit(actor,now,raw)
            if arena.pk['finished']:return packets
    return packets
