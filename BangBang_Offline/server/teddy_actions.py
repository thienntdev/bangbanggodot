"""Teddy has E/Space only; basic slow and split Space radii are user decisions."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene

SLOTS = {0:306100, 1:306201, 2:306301}


class TeddyActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.cooldowns = {slot:0 for slot in SLOTS}

    def _cooldown(self, slot):
        return 1572,props(SLOTS[slot],slot,end=self.cooldowns[slot])+struct.pack('<I',self.id)

    def on_bullet_hit(self, flight, target, now):
        if flight['template']!=306100:
            return []
        packets = []
        for template in (306101,306102,306103):
            packets.extend(self._buff(template,now,target.id))
        return packets

    def _flight(self, flight, now):
        if flight['template']!=306301:
            return super()._flight(flight,now)
        begin,finish,previous = flight['begin'],flight['finish'],flight['previous']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        for target in list(self.arena.actors.values()):
            if (target.alive and target.camp!=self.camp and self.projectile_blocked(target,now)
                    and actor_contact(start,end,target,previous,now) is not None):
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        if now<finish:
            flight['previous'] = now
            self._queue(min(now+20,finish),'flight',flight)
            return []
        packets = [scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        for target in list(self.arena.actors.values()):
            distance = math.dist(flight['end'],target.position_at(now))
            if not target.alive or target.camp==self.camp or distance>216:
                continue
            # Original chain damages first; user kept each Effect's radius.
            packets.extend(self.damage(flight['raw'],now,target=target,school='energy')[0])
            if distance<=144:
                for template in (306311,306321,306331,306341):
                    packets.extend(self._buff(template,now,target.id))
        return packets

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or not self.alive or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        # iUseInStun=1. Client still enforces its own silence/slot restrictions.
        if slot!=1 and self.blocked('attack',now):
            return []
        if slot!=1 and (not self._inside(dest) or start==dest):
            return []
        if slot==2 and math.dist(start,dest)>528:
            return []
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000}[slot], slot)
        if slot==0:
            packets = self.shoot(306100,start,dest,now,self.combat_stat('iEgAtk',now),school='energy',basic=True)
        elif slot==1:
            packets = [scene(skills=(self._skill_event(306201,start,start,self.id),))]
            allies = sorted((a for a in self.arena.actors.values() if a.id!=self.id and a.camp==self.camp and a.alive and not a.info.get('map_object')),
                            key=lambda a:(math.dist(start,a.position_at(now)),a.id))[:2]
            for target in [self]+allies:
                packets.extend(target.restore_hp(target.max_hp*D('.2'),now))
            for (owner,template) in list(self.active_buffs):
                if owner==self.id and table_row('BuffTemplate_table.xml',nBuffId=template).get('iAspect')=='-1':
                    packets.extend(self.remove_buff(template,now))
        else:
            # Exhibit902 is a six-frame projectile, interpolated by travel distance.
            # Keep the original flight presentation; detonate at the selected point
            # after its travel time, regardless of intermediate tanks/walls.
            ident = self._new_id(2)
            factor=1.15 if self.has_buff(10400233,now) else 1
            speed = max(1,round(math.dist(start,dest)*factor))
            flight = dict(kind='bullet',template=306301,id=ident,start=start,end=dest,
                          begin=now,finish=now+round(1000/factor),previous=now,speed=speed,
                          raw=self.combat_stat('iEgAtk',now)*D('3.79'),source_generation=self.generation)
            self._queue(now+20,'flight',flight)
            packets = [scene(fires=(struct.pack('<IIhhhhhI',ident,self.id,*start,*dest,speed,306301),))]
        return packets+[self._cooldown(slot)]
