"""Songoku: target teleport and a twelve-second, cast-time enemy-count form."""
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_protocol import props,scene
from melee_common import aimed,enemies,prepare_displacement

SLOTS={0:316100,1:316201,2:316301}


class SongokuActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.cooldowns.pop(10)
        self.nearby=0
        self.teleport=None

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def _count(self,now):
        return min(3,sum(a.alive and a.camp!=self.camp and not a.info.get('npc_template')
                         and math.dist(self.position_at(now),a.position_at(now))<=432
                         for a in self.arena.actors.values()))

    def _form(self,now):
        return next((t-316311 for t in range(316311,316315) if self.has_buff(t,now)),None)

    def attr_bonus(self,attributes,now):
        value=super().attr_bonus(attributes,now)
        # Native rows use attribute5 for the form display; V1 explicitly treats
        # these as outgoing damage bonuses, not EN plus a second damage bonus.
        form=self._form(now)
        if 5 in attributes and form is not None:value-=(D(1),D('1.1'),D('1.3'),D('1.5'))[form]
        return value

    def _power(self,now):
        form=self._form(now)
        return self.combat_stat('iEgAtk',now)*(1+(D(1),D('1.1'),D('1.3'),D('1.5'))[form] if form is not None else 1)

    def on_spawn(self,now):
        self.nearby=0;self.teleport=None
        self._queue(now,'goku_aura',self.generation)
        return self._buff(316141,now)

    def _aura(self,now):
        count=0 if self._form(now) is not None else self._count(now)
        packets=[]
        if count!=self.nearby:
            if self.nearby:packets.extend(self.remove_buff(316130+self.nearby,now))
            self.nearby=count
        if count:packets.extend(self._buff(316130+count,now))
        return packets

    def strip_defenses(self,now):
        packets=super().strip_defenses(now)
        # TankBase explicitly says Groot suppression also removes Saiyan gains.
        for start in (316311,316321,316331):
            for t in range(start,start+4):packets.extend(self.remove_buff(t,now))
        return packets+self._aura(now)

    def interrupt(self,now):
        if not self.alive:self.teleport=None
        return []  # Approved: hostile control does not cancel an already placed E.

    def _event(self,now,kind,data):
        if kind=='goku_aura':
            if not self.alive or data[0]!=self.generation:return []
            self._queue(now+1000,kind,*data)
            return self._aura(now)
        if kind=='goku_teleport':
            cast,=data
            if self.teleport is not cast or not self.alive:return []
            self.teleport=None;target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation']:return []
            start=self.position_at(now);dest=self.blink_destination(start,target.position_at(now))
            self.position,self.motion,self.forced_until=dest,None,now
            packets=[scene(moves=(self._move_event(dest,0,5),))]
            if target.camp!=self.camp:
                packets.extend(self.damage(cast['power']*2,now,target=target,school='energy')[0])
                packets.extend(self._buff(316213,now,target.id))
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot==0 and start==dest:return []
        target=self.arena.actors.get(target_id)
        if slot==1 and (not target or not target.alive or target.is_untargetable()
                       or math.dist(start,target.position_at(now))>432):return []
        if slot==1 and target.camp!=self.camp:
            from bot_ai import team_visible
            if not team_visible(self.arena,self,target,now):return []
        power=self._power(now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:20000}[slot], slot)
        if slot==0:return self.shoot(316100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        packets=[self._cooldown(slot),scene(skills=(self._skill_event(SLOTS[slot],start,dest,target_id),))]
        if slot==1:
            self.teleport=dict(target=target.id,target_generation=target.generation,power=power)
            packets.extend(self._buff(316201,now,target.id))
            self._queue(now+1000,'goku_teleport',self.teleport)
            return packets
        count=self._count(now)  # Before the initial push, not after it.
        for target in enemies(self,area=True):
            origin=target.position_at(now)
            if math.dist(start,origin)>144:continue
            packets.extend(self.damage(power*2,now,target=target,school='energy')[0])
            if self.arena.pk and self.arena.pk['finished']:
                break
            packets.extend(self._buff(316302,now,target.id))
            if target.alive and not target.cc_immune(now):
                origin,stopped=prepare_displacement(target,now)
                packets.extend(stopped)
                dest=aimed(start,origin if origin!=start else (start[0]+1,start[1]),math.dist(start,origin)+144,fixed=True)
                duration=target._set_motion(origin,dest,720,now,kind=1)
                target.forced_until=now+duration
                packets.append(scene(moves=(target._move_event(target.motion[1],720,1),)))
        for template in (316311+count,316321+count,316331+count):packets.extend(self._buff(template,now))
        return packets+self._aura(now)
