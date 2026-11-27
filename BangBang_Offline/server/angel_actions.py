"""Angel: native form slots, shared cooldowns and one bounded holy bounce."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,in_cone,prepare_displacement

SLOTS={0:336100,1:336201,2:336301,10:336101}
FALLEN={0:336500,1:336601,2:336701,10:336501}


class AngelActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.fallen=False
        self.ready=self.sanctuary=None

    def _skill(self,slot):
        return (FALLEN if self.fallen else SLOTS)[slot]

    def _cooldown(self,slot,changed=False):
        body=props(self._skill(slot),slot,end=self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.fallen=False;self.ready=self.sanctuary=None
        return self._buff(336401,now)+[self._cooldown(s,True) for s in SLOTS]

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or action=='attack' and self.sanctuary) or super().blocked(action,now)

    def interrupt(self,now):
        packets=[]
        if self.ready:
            self.ready=None
            packets.append((1583,struct.pack('<II',self.id,336601)))
        if not self.alive:self.sanctuary=None
        return packets+self.sync_speed(now)

    def update(self,now):
        packets=self.interrupt(now) if self.ready and self.skill_sealed(1,now) else []
        return packets+super().update(now)

    def on_control(self,source,template,now):
        if self.ready and int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']) in (30,35,66):
            return self.interrupt(now)
        return []

    def _switch(self,start,dest,now):
        origin,stopped=prepare_displacement(self,now,interrupt=False)
        origin=origin if stopped else start
        old=self.fallen;self.fallen=not old
        packets=[]
        for template in (range(336101,336107) if old else (336401,336501,336503)):
            packets.extend(self.remove_buff(template,now))
        for template in ((336501,336502,336503,336507) if old else range(336101,336109)):
            packets.extend(self._buff(template,now))
        packets.extend(self._buff(336109,now))
        packets.extend(stopped)
        end=aimed(start,dest,360,fixed=True)
        duration=self._set_motion(origin,end,720,now,kind=4);self.forced_until=now+duration
        self.cooldowns[1]=0
        return packets+[scene(moves=(self._move_event(self.motion[1],720,4),))]+[self._cooldown(s,True) for s in SLOTS]

    def _next_bounce(self,cast,pos,now):
        if cast['index']>=4:return []
        from bot_ai import team_visible
        choices=[a for a in self.arena.actors.values() if a.alive and not a.is_untargetable()
                 and (a.camp==self.camp or team_visible(self.arena,self,a,now))
                 and a.id not in cast['visited'] and math.dist(pos,a.position_at(now))<=336]
        if not choices:return []
        target=self.arena.rng.choice(choices)
        cast['visited'].add(target.id)
        raw=cast['power']*D('1.78')*D('.8')**cast['index'];cast['index']+=1
        packets=self.shoot(336211,pos,target.position_at(now),now,raw,school='energy',target=target,
                           through_walls=True,context=cast)
        return packets

    def _flight(self,flight,now):
        if flight['template']!=336211:return super()._flight(flight,now)
        target=self.arena.actors.get(flight['target']);ident=struct.pack('<I',flight['id'])
        if not target or not target.alive or target.generation!=flight['target_generation'] or target.is_untargetable():
            return [scene(expired_bullets=(ident,))]
        start=flight['pos'];dest=target.position_at(now)
        end=point_at(start,dest,min(1,flight['speed']*(now-flight['previous'])/1000/max(1,math.dist(start,dest))))
        packets=[]
        if dest!=flight['end']:
            packets.append((1562,struct.pack('<Ihhhh',flight['id'],*(round(v) for v in (*start,*dest)))))
            flight['end']=dest
        hit=circle_contact(start,end,target.position_at(flight['previous']),dest)
        if hit is not None:
            if target.camp!=self.camp and self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(ident,))]
            packets.append(scene(blown_bullets=(ident,)))
            packets.extend(target.restore_hp(flight['raw'],now) if target.camp==self.camp
                           else self.damage(flight['raw'],now,target=target,school='energy')[0])
            return packets+self._next_bounce(flight['context'],dest,now)
        if now>=flight['finish']:return packets+[scene(expired_bullets=(ident,))]
        flight['pos'],flight['previous']=end,now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _event(self,now,kind,data):
        if kind=='angel_pull':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;start=self.position_at(now)
            packets=[scene(skills=(self._skill_event(336601,start,cast['dest']),))]+self.sync_speed(now)
            for target in enemies(self,area=True):
                if not in_cone(target.position_at(now),start,cast['dest'],408,20):continue
                packets.extend(self.damage(cast['power']*D('1.95'),now,target=target)[0])
                if self.arena.pk and self.arena.pk['finished']:
                    break
                if not target.alive or target.cc_immune(now):continue
                pos=target.position_at(now);distance=math.dist(start,pos)
                if distance<=72:continue
                desired=point_at(start,pos,72/distance)
                pos,stopped=prepare_displacement(target,now)
                packets.extend(stopped)
                dest=target.move_destination(pos,desired)
                target.position,target.motion,target.forced_until=dest,None,now
                packets.append(scene(moves=(self._move_event(dest,0,5,target.id),)))
            return packets
        if kind=='angel_sanctuary':
            cast,=data
            if self.sanctuary is not cast or not self.alive:return []
            self.sanctuary=None;pos=self.position_at(now);packets=[]
            for target in self.arena.actors.values():
                if not target.alive or math.dist(pos,target.position_at(now))>240:continue
                if target.camp==self.camp:
                    packets.extend(self._buff(336311,now,target.id))
                    packets.extend(target.restore_hp(cast['power']*D('2.96'),now))
                    packets.extend(target.cleanse(now))
                elif not target.is_untargetable() and not target.cc_immune(now):
                    start,stopped=prepare_displacement(target,now)
                    packets.extend(stopped)
                    dest=aimed(pos,start,math.dist(pos,start)+240,fixed=True)
                    duration=target._set_motion(start,dest,480,now,kind=1);target.forced_until=now+duration
                    packets.append(scene(moves=(self._move_event(target.motion[1],480,1,target.id),)))
            return packets+self._buff(336314,now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot in (0,10) and start==dest or slot==1 and self.fallen and start==dest:return []
        skill=self._skill(slot);fallen=self.fallen
        power=self.combat_stat('iAttack' if fallen else 'iEgAtk',now)*(D('1.25') if fallen else 1)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:25000,10:8000}[slot], slot)
        packets=[]
        if slot==0:
            packets.extend(self.shoot(skill,start,dest,now,power,school='physical' if fallen else 'energy',basic=True))
        elif slot==10:
            packets.append(scene(skills=(self._skill_event(skill,start,dest),)))
            packets.extend(self._switch(start,dest,now))
        elif slot==1 and not fallen:
            packets.extend(self.restore_hp(power*D('2.23'),now))
            ident=self._new_id(2)
            packets.extend((scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*start,408,336201),)),
                            scene(blown_bullets=(struct.pack('<I',ident),))))
            packets.extend(self._next_bounce(dict(power=power,generation=self.generation,index=0,visited={self.id}),start,now))
        elif slot==1:
            self.position,self.motion=start,None
            self.ready=dict(slot=1,skill=skill,dest=dest,power=power,end=now+500)
            self._queue(now+500,'angel_pull',self.ready)
            packets.append(scene(skills=(self._skill_event(skill,start,dest,ready=1),)))
        elif not fallen:
            self.sanctuary=dict(power=power,end=now+1000)
            self._queue(now+1000,'angel_sanctuary',self.sanctuary)
            packets.extend(self._buff(336301,now)+self._buff(336302,now))
            packets.append(scene(skills=(self._skill_event(skill,start,dest),)))
        else:
            packets.append(scene(skills=(self._skill_event(skill,start,dest),)))
            for target in enemies(self,area=True):
                if math.dist(start,target.position_at(now))<=216:
                    packets.extend(self.damage(power*D('4.55'),now,target=target)[0])
                    packets.extend(self._buff(336702,now,target.id))
        return packets+[self._cooldown(slot)]+self.sync_speed(now)
