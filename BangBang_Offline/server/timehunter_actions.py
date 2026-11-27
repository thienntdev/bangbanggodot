"""Time Hunter: absolute rewind, one wormhole explosion and interruptible pulses."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:325100,1:325201,2:325601,10:325501}


class TimeHunterActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.rewind = self.worm = self.ready = self.channel = None
        self.passive_ready_at = 0

    def _cooldown(self,slot,changed=False):
        warp = slot==10 and self.worm and not self.worm['used'] and self.has_buff(325502,self.clock())
        body = props(325701 if warp else SLOTS[slot],slot,end=self.worm['begin']+300 if warp else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        return self._buff(325401,now)+[self._cooldown(10,True)]

    def _speed(self,now):
        return 0 if self.ready or self.channel else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready or self.channel) or super().blocked(action,now)

    def reject_buff(self,row,source,now):
        # The first two seconds expressly resist silence, not stuns.
        return bool(self.rewind and now<self.rewind['begin']+2000 and source.camp!=self.camp
                    and (row['nEffectType']=='35' or row['nEffectType']=='66'
                         and int(row.get('fEffectValB',31)) & 30))

    def _silenced(self,now):
        return any(owner==self.id and end>now and self.buff_sources.get(t)!=self.id
                   and table_row('BuffTemplate_table.xml',nBuffId=t)['nEffectType'] in ('35','66')
                   and (not int(table_row('BuffTemplate_table.xml',nBuffId=t).get('fEffectValB',0))
                        or int(table_row('BuffTemplate_table.xml',nBuffId=t).get('fEffectValB',0)) & 30)
                   for (owner,t),(_,end) in self.active_buffs.items())

    def _end_rewind(self,now):
        cast,self.rewind = self.rewind,None
        if not cast:
            return []
        packets = self.remove_object(cast['id'])
        for t in (325201,325202,325211,325212,325213):
            packets.extend(self.remove_buff(t,now))
        return packets

    def interrupt(self,now):
        cast = self.channel or self.ready
        self.channel = self.ready = None
        packets = []
        if cast:
            skill = cast.get('skill',325601)
            packets.append((1583,struct.pack('<II',self.id,skill)))
            if skill==325601:
                packets.extend(self.remove_object(cast['id']))
                for t in (325611,325612,325613,325605):
                    packets.extend(self.remove_buff(t,now))
                packets.extend(self._buff(325621,now))
                for target in self.arena.actors.values():
                    if target.buff_sources.get(325607)!=self.id:
                        continue
                    pull = cast.get('pulls',{}).get(target.id)
                    if (target.has_buff(325607,now) and target.motion_kind==1 and pull
                            and target.generation==pull['generation'] and target.motion==pull['motion']):
                        target.position,target.motion,target.forced_until = target.position_at(now),None,now
                        packets.append(scene(moves=(target._move_event(target.position,0,5),)))
                    for t in (325601,325603,325604,325607):
                        if target.buff_sources.get(t)==self.id:
                            packets.extend(target.remove_buff(t,now))
        if not self.alive:
            packets.extend(self._end_rewind(now))
        return packets+self.sync_speed(now)

    def update(self,now):
        packets = []
        if self.rewind and now>=self.rewind['begin']+2000 and self._silenced(now):
            packets.extend(self._end_rewind(now))
        if (self.ready or self.channel) and self._silenced(now):
            packets.extend(self.interrupt(now))
        return packets+super().update(now)

    def on_basic_damage(self,source,hit,now):
        if not self.alive or now<self.passive_ready_at:
            return []
        self.passive_ready_at = now+1000
        packets = self._buff(325412,now)
        pos,power = self.position_at(now),self.combat_stat('iEgAtk',now)
        for target in list(self.arena.actors.values()):
            if target.alive and target.camp!=self.camp and math.dist(pos,target.position_at(now))<=192:
                packets.extend(self.damage(power*D('1.5'),now,target=target,school='energy')[0])
                packets.extend(self._buff(325413,now,target.id))
        return packets

    def _pulse(self,cast,index,now):
        pos = self.position_at(now)
        packets = self._buff(325605,now)+self._buff(325613,now)
        for target in list(self.arena.actors.values()):
            distance = math.dist(pos,target.position_at(now))
            if not target.alive or target.camp==self.camp or distance>264:
                continue
            if index:
                raw = cast['power']*(D('1.26')-D('.63')*D(str(distance))/264)
                packets.extend(self.damage(raw,now,target=target,school='energy',periodic=True)[0])
                if self.arena.pk and self.arena.pk['finished']:
                    return packets
            if not target.alive or target.cc_immune(now) or index==10:
                continue
            for t in (325601,325603,325604,325607):
                packets.extend(self._buff(t,now,target.id,duration=300))
            if distance>72:
                # A later push may be crossing static terrain when a pulse
                # takes over. Resolve its original segment before interrupt
                # can discard it; damage/range above keep the contact sample.
                start,stopped = prepare_displacement(target,now)
                packets.extend(stopped)
                remaining = math.dist(start,pos)
                dest = point_at(start,pos,min(27,max(0,remaining-72))/max(1,remaining))
                duration = target._set_motion(start,dest,90,now,kind=1)
                target.forced_until = now+duration
                # A later source can replace this pull before its buff expires.
                # Keep the exact segment, including restore-rebased timestamps,
                # so ending this channel only stops motion that it still owns.
                cast.setdefault('pulls',{})[target.id] = dict(motion=target.motion,generation=target.generation)
                packets.append(scene(moves=(target._move_event(target.motion[1],90,1),)))
        return packets

    def _event(self,now,kind,data):
        if kind in ('time_rewind_phase','time_rewind'):
            cast, = data
            if self.rewind is not cast or not self.alive:
                return []
            if self._silenced(now):
                return self._end_rewind(now)
            if kind=='time_rewind_phase':
                return self._buff(325213,now)
            self.position,self.motion,self.forced_until = self.blink_destination(self.position_at(now),cast['pos']),None,now
            packets = super().commit_hp(min(self.max_hp,cast['hp']),now)
            return packets+[scene(moves=(self._move_event(self.position,0,5),))]+self._end_rewind(now)
        if kind=='time_worm_form':
            cast, = data
            ident = self._new_id(5)
            buffs = b''.join(struct.pack('<IIBI',t,self._new_id(6),1,self.id) for t in (325511,325512))
            body = struct.pack('<IIhhiBiIiH',ident,325511,*cast['pos'],1,self.camp,1,self.id,0,2)+buffs
            self.arena.objects[ident] = body.hex()
            cast['npc'] = ident
            return self.remove_object(cast['warning'])+[(1556,struct.pack('<I',self.scene_id)+body)]
        if kind=='time_worm_slot':
            cast, = data
            if self.worm is not cast:
                return []
            cast['used'] = True
            return self.remove_buff(325502,now)+[self._cooldown(10,True),self._cooldown(10)]
        if kind=='time_worm_end':
            cast, = data
            packets = self.remove_object(cast['id'])+self.remove_object(cast['npc'],destroyed=True)
            if self.worm is cast:
                self.worm = None
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(cast['pos'],target.position_at(now))<=192:
                    packets.extend(self.damage(cast['power']*D('3.24'),now,target=target,school='energy')[0])
                    packets.extend(self._buff(325522,now,target.id))
            return packets
        if kind=='time_warp':
            cast, = data
            if self.ready is not cast or not self.alive or self._silenced(now):
                return self.interrupt(now) if self.ready is cast else []
            self.ready = None
            start = self.position_at(now)
            self.position,self.motion,self.forced_until = self.blink_destination(start,cast['dest']),None,now
            return [scene(skills=(self._skill_event(325701,start,self.position),),
                          moves=(self._move_event(self.position,0,5),))]+self.sync_speed(now)
        if kind=='time_channel':
            cast,index = data
            if (self.ready or self.channel) is not cast or not self.alive:
                return []
            if self._silenced(now) or 30 in self.buff_types(now):
                return self.interrupt(now)
            self.ready,self.channel = None,cast
            packets = [scene(skills=(self._skill_event(325601,self.position_at(now),self.position_at(now),self.id),))] if index==0 else []
            packets.extend(self._pulse(cast,index,now))
            if index==10:
                return packets+self.interrupt(now)
            self._queue(now+300,kind,cast,index+1)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now):
            return []
        warp = slot==10 and self.worm and not self.worm['used'] and self.has_buff(325502,now)
        if not warp and self.cooldowns[slot]>now:
            return []
        if slot==0 and (not self._inside(dest) or dest==start):
            return []
        if slot==10 and (math.dist(start,self.worm['pos'])>600 if warp else not self._inside(dest) or math.dist(start,dest)>480):
            return []
        power = self.combat_stat('iEgAtk',now)
        if warp:
            cast = self.ready = dict(slot=10,skill=325701,dest=self.worm['pos'])
            self.worm['used'] = True
            self._queue(now+50,'time_warp',cast)
            return self.remove_buff(325502,now)+[self._cooldown(10,True),self._cooldown(10),
                scene(skills=(self._skill_event(325701,start,cast['dest'],ready=1),))]+self.sync_speed(now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:30000,10:8000}[slot], slot)
        if slot==0:
            return self.shoot(325100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        packets = [scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=int(slot==2)),))]
        if slot==1:
            ident,packet = self.add_object(325221,start)
            self.rewind = dict(id=ident,pos=start,hp=self.hp,begin=now)
            self._queue(now+2000,'time_rewind_phase',self.rewind)
            self._queue(now+3500,'time_rewind',self.rewind)
            for t in (325201,325202,325211,325212):
                packets.extend(self._buff(t,now))
            packets.append(packet)
        elif slot==10:
            warning,packet = self.add_object(325501,dest)
            ident,timer = self.add_object(325504,dest)
            self.worm = dict(id=ident,warning=warning,npc=None,pos=dest,power=power,begin=now,used=False)
            self._queue(now+300,'time_worm_form',self.worm)
            self._queue(now+3500,'time_worm_slot',self.worm)
            self._queue(now+3800,'time_worm_end',self.worm)
            packets.extend((packet,timer))
            packets.extend(self._buff(325502,now)+self._buff(325503,now))
            packets.append(self._cooldown(10,True))
        else:
            ident,packet = self.add_object(325614,start)
            self.ready = dict(id=ident,slot=2,skill=325601,dest=start,power=power)
            self._queue(now+200,'time_channel',self.ready,0)
            self.position,self.motion = start,None
            for t in (325611,325612,325613):
                packets.extend(self._buff(t,now,duration=3200))
            packets.append(packet)
        return packets+[self._cooldown(slot)]+self.sync_speed(now)
