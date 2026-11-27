"""Chu Du: bounded contagion, untargeted fire orbs and a server-clock channel."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:388100,1:388201,2:388301,10:388401}
CHANNEL_BUFFS = (388401,388402,388403,388404,388405,388406,388421)


class ChuDuActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.mp = int(self.stats['iMp'])
        self.e_count,self.e_next_charge = 3,0
        self.ready = self.channel = None
        self.marks,self.orbs = {},{}
        self.rewarded = set()

    def _cooldown(self, slot, changed=False):
        body = props(388431 if slot==10 and self.channel else SLOTS[slot],slot,
                     self.e_count if slot==1 else -1,0 if slot==10 and self.channel else self.cooldowns[slot],
                     self.e_next_charge if slot==1 else 0)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _resource(self, delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        before,self.mp = self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if before!=self.mp else []

    def on_spawn(self, now):
        self.mp = int(self.stats['iMp'])
        self.rewarded.clear()
        self._queue(now+3000,'chu_regen',self.generation)
        packets = [scene(mp=(struct.pack('<Ii',self.id,self.mp),))]
        for template in (388101,388102,388103,388104,388141):
            packets.extend(self._buff(template,now))
        return packets+[self._cooldown(10,True),self._cooldown(10)]

    def _speed(self, now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self, action, now):
        return bool(self.ready) or super().blocked(action,now)

    def cc_immune(self, now, *, slow=False):
        return bool(self.channel) or super().cc_immune(now,slow=slow)

    def update(self, now):
        packets = []
        if self.ready and self.skill_sealed(self.ready['slot'],now):
            packets.extend(self.interrupt(now))
        if self.channel and self._silenced(now):
            packets.extend(self._end_channel(now))
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count = min(3,self.e_count+1)
            self.e_next_charge = self.e_next_charge+self.skill_cooldown(8000) if self.e_count<3 else 0
            packets.append(self._cooldown(1))
        return packets+super().update(now)

    def _silenced(self, now):
        # Own initial R lock (388406) is not an external silence.
        from combat_data import table_row
        for (owner,t),(_,end) in self.active_buffs.items():
            if owner!=self.id or end<=now or self.buff_sources.get(t)==self.id:
                continue
            row = table_row('BuffTemplate_table.xml',nBuffId=t)
            if row.get('nEffectType') in ('35','66') and (not int(row.get('fEffectValB',0)) or int(row.get('fEffectValB',0)) & 8):
                return True
        return False

    def _end_channel(self, now):
        if not self.channel:
            return []
        self.channel = None
        self.cooldowns[10] = now+self.skill_cooldown(6000, 10)
        packets = []
        for template in CHANNEL_BUFFS:
            packets.extend(self.remove_buff(template,now))
        packets.extend(self._buff(388435,now))
        return packets+[self._cooldown(10,True),self._cooldown(10)]+self.sync_speed(now)

    def interrupt(self, now):
        packets = []
        if self.ready:
            slot = self.ready['slot']
            self.ready = None
            if slot==10:
                self.cooldowns[10] = now+self.skill_cooldown(6000, 10)
            packets.extend(((1583,struct.pack('<II',self.id,SLOTS[slot])),self._cooldown(slot)))
        return packets+self._end_channel(now)+self.sync_speed(now)

    def handle(self, message, payload):
        if message==514:
            now = self.clock()
            packets = self.arena.tick(now)
            if not self.arena.input_open(now,self):return packets
            if len(payload)==8 and self.channel and self.alive:
                scene_id,x,y = struct.unpack('<Ihh',payload)
                if scene_id==self.scene_id and (x,y)!=self.position_at(now):
                    self.channel['dest'] = x,y
            return packets
        return super().handle(message,payload)

    def _enemies(self, pos, radius, now):
        return [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                and a.is_area_targetable() and math.dist(pos,a.position_at(now))<=radius]

    def _valid(self, target, mark, now, final=False):
        return (self.marks.get(target.id) is mark and target.alive
                and target.generation==mark['target_generation']
                and target.buff_versions.get(388113)==mark['version']
                and (now<=mark['end'] if final else now<mark['end'])
                and (final or target.has_buff(388113,now)))

    def _burn(self, target, power, generation, now, *, chain=None):
        if not target.alive or target.reject_buff({'nEffectType':'201'},self,now):
            return []
        direct = chain is None
        key = target.id,target.generation
        if chain is not None and key in chain:
            return []
        chain = {key} if direct else chain
        chain.add(key)
        old = self.marks.get(target.id)
        valid = old and old['source_generation']==generation and self._valid(target,old,now)
        mark = old if valid else {}
        packets = self._buff(388113,now,target.id,duration=2000)
        mark.update(version=target.buff_versions[388113],end=now+2000,power=power,
                    source_generation=generation,target_generation=target.generation)
        self.marks[target.id] = mark
        if direct:
            packets.extend(self._buff(388111,now,target.id,duration=2000))
            packets.extend(self._buff(388112,now,target.id,duration=2000))
            stacks = target.buff_stacks.get(388111,1)
            for template in range(388115,388120):
                if target.has_buff(template,now):
                    packets.extend(target.remove_buff(template,now))
            packets.extend(self._buff(388114+stacks,now,target.id,duration=2000))
        if not valid:
            self._queue(now+1000,'chu_dot',target.id,mark)
        self._queue(now+1000,'chu_spread',target.id,mark,chain)
        return packets

    def _reward(self, target, generation, now):
        key = target.id,target.generation
        if not self.alive or self.generation!=generation or key in self.rewarded:
            return []
        self.rewarded.add(key)
        packets = self._resource(15)+self._buff(388121,now)
        if self.e_next_charge:
            self.e_next_charge = max(now,self.e_next_charge-400)
        for slot,amount in ((2,1500),(10,300)):
            if not (slot==10 and self.channel):
                self.cooldowns[slot] = max(now,self.cooldowns[slot]-amount)
        return packets+[self._cooldown(slot) for slot in (1,2,10)]

    def on_target_death(self, target, now):
        mark = self.marks.pop(target.id,None)
        if (mark and target.generation==mark['target_generation'] and now<=mark['end']
                and target.buff_versions.get(388113)==mark['version']):
            return self._reward(target,mark['source_generation'],now)
        return []

    def _hurt(self, target, raw, power, generation, now, *, burn=True, periodic=False, steal=0, basic=False):
        before_alive = target.alive
        packets,lost = self.damage(raw,now,target=target,school='energy',periodic=periodic,basic=basic,
                                   lifesteal=steal if generation==self.generation else 0)
        if before_alive and not target.alive:
            packets.extend(self._reward(target,generation,now))
        if lost and burn:
            packets.extend(self._burn(target,power,generation,now))
        return packets,lost

    def on_bullet_hit(self, flight, target, now):
        # The generic flight has already applied normal damage.
        packets = self.remove_buff(388141,now) if flight['source_generation']==self.generation else []
        if not target.alive:
            packets.extend(self._reward(target,flight['source_generation'],now))
        return packets

    def _new_orb(self, pos, power, generation, now):
        ident = self._new_id(5)
        buffs = b''.join(struct.pack('<IIBI',t,self._new_id(6),1,self.id) for t in (388205,388206))
        body = struct.pack('<IIhhiBiIiH',ident,388201,*pos,10,self.camp,10,self.id,0,2)+buffs
        self.arena.objects[ident] = body.hex()
        prop,packet = self.add_object(388206,pos)
        orb = dict(id=ident,prop=prop,pos=pos,power=power,generation=generation,end=now+8000,ignited=False)
        self.orbs[ident] = orb
        self._queue(now+8000,'chu_orb',orb)
        return [(1556,struct.pack('<I',self.scene_id)+body),packet]

    def _ignite(self, orb, now, *, immediate=False):
        if self.orbs.get(orb['id']) is not orb:
            return []
        if immediate:
            return self._explode_orb(orb,now)
        if not orb['ignited']:
            orb['ignited'] = True
            self._queue(now+1000,'chu_orb',orb)
        return []

    def _explode_orb(self, orb, now):
        if self.orbs.pop(orb['id'],None) is not orb:
            return []
        packets = self.remove_object(orb['id'],destroyed=True)+self.remove_object(orb['prop'])
        pos = orb['pos']
        packets.append(scene(skills=(self._skill_event(388211,pos,pos,self.id),)))
        hit = False
        for target in self._enemies(pos,168,now):
            more,lost = self._hurt(target,orb['power']*D('1.26'),orb['power'],orb['generation'],now)
            packets.extend(more+self._buff(388212,now,target.id))
            hit = hit or lost
        if hit and self.alive and orb['generation']==self.generation and self.e_next_charge:
            self.e_next_charge = now+round(max(0,self.e_next_charge-now)*.75)
            packets.append(self._cooldown(1))
        ident,packet = self.add_object(388213,pos)
        packets.append(packet)
        area = dict(orb,id=ident)
        self._queue(now+1000,'chu_ground',area,1)
        return packets

    @staticmethod
    def _in_cone(start, dest, pos):
        distance = math.dist(start,pos)
        if not distance:
            return True
        length = math.dist(start,dest)
        return distance<=456 and length>0 and sum((b-a)*(c-a) for a,b,c in zip(start,dest,pos))/(length*distance)>=math.cos(math.radians(7.5))

    def _flight(self, flight, now):
        if flight['template']==388100:
            return super()._flight(flight,now)
        if now<flight['finish']:
            self._queue(flight['finish'],'flight',flight)
            return []
        pos = flight['end']
        packets = [scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        hit = False
        for target in self._enemies(pos,168,now):
            more,lost = self._hurt(target,flight['power']*D('1.47'),flight['power'],flight['source_generation'],now)
            packets.extend(more)
            if self.arena.pk and self.arena.pk['finished']:return packets
            packets.extend(self._buff(388203,now,target.id))
            hit = hit or lost
        if self.alive and flight['source_generation']==self.generation:
            if hit:
                packets.extend(self._buff(388202,now))
                for index in range(1,6):
                    self._queue(now+index*400,'chu_e_mp',self.generation)
            start = self.position_at(now)
            distance = math.dist(start,pos)
            if 0<distance<=168 and not self.cc_immune(now):
                dest = point_at(pos,start,1+240/distance)
                duration = self._set_motion(start,dest,720,now,kind=1)
                self.forced_until = now+duration
                packets.append(scene(moves=(self._move_event(self.motion[1],720,1),)))
        return packets+self._new_orb(pos,flight['power'],flight['source_generation'],now)

    def _event(self, now, kind, data):
        if kind in ('chu_regen','chu_e_mp'):
            generation, = data
            if not self.alive or self.generation!=generation:
                return []
            if kind=='chu_regen':
                self._queue(now+3000,kind,generation)
            return self._resource(10 if kind=='chu_regen' else 5)
        if kind=='chu_dot':
            ident,mark = data
            target = self.arena.actors[ident]
            if not self._valid(target,mark,now,True):
                if self.marks.get(ident) is mark:
                    self.marks.pop(ident,None)
                return []
            packets = self._hurt(target,(target.max_hp-target.hp)*D('.025'),mark['power'],mark['source_generation'],now,burn=False,periodic=True)[0]
            if self.marks.get(ident) is mark:
                if now<mark['end']:
                    self._queue(now+1000,kind,ident,mark)
                else:
                    self.marks.pop(ident,None)
            return packets
        if kind=='chu_spread':
            ident,mark,chain = data
            target = self.arena.actors[ident]
            if not self._valid(target,mark,now):
                return []
            packets = []
            for victim in self._enemies(target.position_at(now),120,now):
                packets.extend(self._burn(victim,mark['power'],mark['source_generation'],now,chain=chain))
            return packets
        if kind=='chu_orb':
            return self._explode_orb(data[0],now)
        if kind=='chu_ground':
            area,index = data
            packets = []
            for target in self._enemies(area['pos'],168,now):
                packets.extend(self._hurt(target,area['power']*D('.3'),area['power'],area['generation'],now)[0])
            if index<3:
                self._queue(now+1000,kind,area,index+1)
            else:
                packets.extend(self.remove_object(area['id']))
            return packets
        if kind=='chu_ready':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            if self.skill_sealed(cast['slot'],now):
                return self.interrupt(now)
            self.ready = None
            pos = self.position_at(now)
            packets = self.sync_speed(now)
            packets.append(scene(skills=(self._skill_event(SLOTS[cast['slot']],pos,cast['dest']),)))
            if cast['slot']==10:
                self.channel = cast
                for template in CHANNEL_BUFFS[:-1]:
                    packets.extend(self._buff(template,now))
                self._queue(now+300,'chu_beam',cast)
                self._queue(now+400,'chu_cost',cast)
                return packets+[self._cooldown(10,True),self._cooldown(10)]
            packets.extend(self._buff(388302,now))
            from bot_ai import team_visible
            for target in self._enemies(pos,10000,now):
                if not team_visible(self.arena,self,target,now):continue
                packets.extend(self._buff(388301,now,target.id))
                self._queue(now+100,'chu_warning',dict(cast,pos=target.position_at(now)))
            return packets
        if kind=='chu_warning':
            cast, = data
            ident,packet = self.add_object(388311,cast['pos'])
            self._queue(now+1000,'chu_space',dict(cast,id=ident))
            return [packet]
        if kind=='chu_space':
            cast, = data
            # Successful delayed field impact: SceneItem388311 carries its
            # native flame movie on removal. A cancelled ready phase never
            # creates the warning/impact; committed damage remains unchanged.
            packets = self.remove_object(cast['id'],destroyed=True)
            for target in self._enemies(cast['pos'],120,now):
                packets.extend(self._hurt(target,cast['power']*D('3.23'),cast['power'],cast['generation'],now)[0])
                packets.extend(self._buff(388322,now,target.id))
            for orb in list(self.orbs.values()):
                if math.dist(cast['pos'],orb['pos'])<=120:
                    packets.extend(self._ignite(orb,now,immediate=True))
            return packets
        if kind in ('chu_beam','chu_cost'):
            cast, = data
            if self.channel is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            if self._silenced(now):
                return self._end_channel(now)
            if kind=='chu_cost':
                if self.mp<10:
                    return self._end_channel(now)
                packets = self._resource(-10)+self._buff(388421,now)
                if self.mp==0:
                    return packets+self._end_channel(now)
                self._queue(now+400,kind,cast)
                return packets
            start,dest = self.position_at(now),cast['dest']
            packets = [scene(skills=(self._skill_event(388411,start,dest),))]
            for target in self._enemies(start,456,now):
                if self._in_cone(start,dest,target.position_at(now)):
                    scale = D('1.5') if math.dist(start,target.position_at(now))>408 else D(1)
                    packets.extend(self._buff(388411,now,target.id))
                    packets.extend(self._hurt(target,cast['power']*D('.375')*scale,cast['power'],cast['generation'],now,steal=D('.25'))[0])
            for orb in list(self.orbs.values()):
                if self._in_cone(start,dest,orb['pos']):
                    packets.extend(self._ignite(orb,now))
            self._queue(now+300,kind,cast)
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot==10 and self.channel and self.alive and not self.skill_sealed(slot,now):
            return self._end_channel(now)
        if (slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now)
                or self.cooldowns[slot]>now or slot==1 and not self.e_count or slot==10 and self.mp<10):
            return []
        if slot!=2 and (not self._inside(dest) or start==dest):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:2000,2:30000,10:6000}[slot], slot)
        if slot==0:
            packets = self.shoot(388100,start,dest,now,power,school='energy',basic=True)
        elif slot==1:
            self.e_count -= 1
            if not self.e_next_charge:
                self.e_next_charge = now+self.skill_cooldown(8000)
            distance = min(480,math.dist(start,dest))
            packets = self.shoot(388201,start,dest,now,power*D('1.47'),school='energy',
                                  power=power,range_multiplier=D(str(distance))/480,through_walls=True)
        else:
            # R does not forbid E/Space in the native masks. Their prep is a
            # separate state; the R timer remains the sole damage/MP owner.
            self.ready = dict(slot=slot,dest=dest,power=power,generation=self.generation)
            body,stopped = prepare_displacement(self,now,interrupt=False)
            self.position,self.motion = body if stopped else start,None
            self._queue(now+(100 if slot==2 else 300),'chu_ready',self.ready)
            packets = [scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),))]+self.sync_speed(now)+stopped
        return packets+[self._cooldown(slot)]
