"""Medusa: bounded bouncing snakes and a paid, interruptible channel."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:333100,1:333201,2:333301,10:333401}


class MedusaActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready = self.channel = None
        self.e_count,self.e_next_charge = 2,0
        self.mp = int(self.stats['iMp'])

    def _resource(self,delta):
        if getattr(self,'noel_box',None):return []  # Stasis suppresses resource effects too.
        old,self.mp = self.mp,max(0,min(int(self.stats['iMp']),self.mp+delta))
        return [scene(mp=(struct.pack('<Ii',self.id,self.mp),))] if old!=self.mp else []

    def _cooldown(self,slot):
        return 1572,props(SLOTS[slot],slot,self.e_count if slot==1 else -1,
                          self.cooldowns[slot],self.e_next_charge if slot==1 else 0)+struct.pack('<I',self.id)

    def on_spawn(self,now):
        self.mp = int(self.stats['iMp'])
        self._queue(now+3000,'medusa_regen',self.generation)
        return self._buff(333101,now)+self._buff(333102,now)+[scene(mp=(struct.pack('<Ii',self.id,self.mp),))]

    def _speed(self,now):
        return 0 if self.ready else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def _end_channel(self,now):
        if not self.channel:
            return []
        self.channel = None
        self.cooldowns[2] = now+self.skill_cooldown(15000, 2)
        packets = []
        for template in range(333302,333306):
            packets.extend(self.remove_buff(template,now))
        if self.has_buff(333301,now):
            remaining = min(500,self.active_buffs[(self.id,333301)][1]-now)
            packets.extend(self._buff(333301,now,duration=remaining))
        return packets+[self._cooldown(2)]+self.sync_speed(now)

    def interrupt(self,now):
        packets = self._end_channel(now)
        if self.ready:
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,333401)))
        return packets+self.sync_speed(now)

    def update(self,now):
        packets = []
        if self.ready and self.skill_sealed(10,now):
            packets.extend(self.interrupt(now))
        if self.channel:
            # Ignore the channel's own attack/Space ban, not external silence.
            sealed = any(self.has_buff(t,now) and t!=333304 and
                         (self._silence_row(t)) for t in self.buff_started)
            if sealed:
                packets.extend(self._end_channel(now))
        while self.e_next_charge and self.e_next_charge<=now:
            self.e_count = min(2,self.e_count+1)
            self.e_next_charge = self.e_next_charge+self.skill_cooldown(8000) if self.e_count<2 else 0
            packets.append(self._cooldown(1))
        return packets+super().update(now)

    @staticmethod
    def _silence_row(template):
        from combat_data import table_row
        row = table_row('BuffTemplate_table.xml',nBuffId=template)
        return int(row['nEffectType']) in (35,66) and (not int(row.get('fEffectValB',0)) or int(row.get('fEffectValB',0))&4)

    def _curse(self,target,now):
        if target.reject_buff({'nEffectType':'49'},self,now):
            return []
        # The petrification sequence and stacking penetration penalty are
        # separate native buffs. Reaching five curses must not erase -50% pen.
        count = max((t-333120 for t in range(333121,333125)
                     if target.has_buff(t,now) and target.buff_sources.get(t)==self.id),default=0)
        penalty = target.buff_stacks.get(333112,0) if target.has_buff(333112,now) and target.buff_sources.get(333112)==self.id else 0
        packets = []
        for t in range(333121,333125):
            if target.buff_sources.get(t)==self.id:
                packets.extend(target.remove_buff(t,now))
        count += 1
        packets.extend(self._buff(333112,now,target.id,duration=2000,stacks=min(5,penalty+1)))
        if count>=5:
            packets.extend(self._buff(333125,now,target.id))
        else:
            packets.extend(self._buff(333120+count,now,target.id,duration=2000))
        packets.extend(self._drain_mp(target,5,now))
        return packets+self._resource(5)

    @staticmethod
    def _drain_mp(target,amount,now):
        if not hasattr(target,'_resource'):
            return []
        # Pea's Gatling may end at this exact event time when MP reaches zero.
        return target._resource(-amount,now) if target.info['tank_id']==10000033 else target._resource(-amount)

    def on_bullet_hit(self,flight,target,now):
        packets = []
        current = self.alive and flight['source_generation']==self.generation
        if current:
            packets.extend(self._curse(target,now))
        if flight['template'] not in (333201,333211):
            return packets
        packets.extend(self._drain_mp(target,10,now))
        if current and self.e_next_charge:
            self.e_next_charge = max(now,self.e_next_charge-800)
            packets.append(self._cooldown(1))
        cast = flight['context']
        cast['hits'].add((target.id,target.generation))
        if len(cast['hits'])>=5:
            return packets
        from bot_ai import team_visible
        pos = target.position_at(now)
        choices = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                   and not a.is_untargetable() and (a.id,a.generation) not in cast['hits']
                   and math.dist(pos,a.position_at(now))<=336 and team_visible(self.arena,self,a,now)]
        if choices:
            next_target = min(choices,key=lambda a:(math.dist(pos,a.position_at(now)),a.id))
            packets.extend(self.shoot(333211,pos,next_target.position_at(now),now,
                            cast['power']*D('1.51')*(1+D('.1')*len(cast['hits'])),school='energy',
                            target=next_target,through_walls=True,context=cast,attack_key=flight['attack_key']))
        return packets

    def _flight(self,flight,now):
        if flight['template']!=333311:
            if 'context' in flight and 'generation' in flight['context']:
                flight['source_generation'] = flight['context']['generation']
            return super()._flight(flight,now)
        start = point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
        end = point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
        packets = []
        contacts = []
        for target in list(self.arena.actors.values()):
            key = target.id,target.generation
            if not target.alive or target.camp==self.camp or key in flight['hits'] or target.is_untargetable():
                continue
            hit = actor_contact(start,end,target,flight['previous'],now)
            if hit is not None:
                contacts.append((hit,target.id,target,key))
        for _,_,target,key in sorted(contacts):
            if self.projectile_blocked(target,now):
                return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            flight['hits'].add(key)
            counts = flight['context']['counts']
            raw = flight['raw']*D('.75')**counts.get(key,0)
            counts[key] = counts.get(key,0)+1
            packets.extend(self.damage(raw,now,target=target,school='energy')[0])
            if self.alive and flight['source_generation']==self.generation:
                packets.extend(self._curse(target,now))
        if now>=flight['finish']:
            return packets+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        flight['previous'] = now
        self._queue(min(now+20,flight['finish']),'flight',flight)
        return packets

    def _event(self,now,kind,data):
        if kind=='medusa_regen':
            if not self.alive or self.generation!=data[0]:
                return []
            self._queue(now+3000,kind,*data)
            return self._resource(10)
        if kind=='medusa_channel':
            cast, = data
            if self.channel is not cast or not self.alive:
                return []
            if self.mp<25:
                return self._end_channel(now)
            packets = self._resource(-25)+self._buff(333301,now,duration=500)
            start,dest = self.position_at(now),cast['dest']
            theta = math.atan2(dest[1]-start[1],dest[0]-start[0])
            volley = dict(counts={},generation=self.generation)
            power = self.combat_stat('iEgAtk',now)
            for angle in (-15,0,15):
                rad = theta+math.radians(angle)
                end = start[0]+round(600*math.cos(rad)),start[1]+round(600*math.sin(rad))
                packets.extend(self.shoot(333311,start,end,now,power,school='energy',through_walls=True,context=volley))
            self._queue(now+500,kind,cast)
            return packets
        if kind=='medusa_gaze':
            cast, = data
            if self.ready is not cast or not self.alive:
                return []
            self.ready = None
            start = self.position_at(now)
            theta = math.atan2(cast['dest'][1]-start[1],cast['dest'][0]-start[0])
            packets = [scene(skills=(self._skill_event(333401,start,cast['dest']),))]
            for target in list(self.arena.actors.values()):
                if not target.alive or target.camp==self.camp or math.dist(start,target.position_at(now))>480:
                    continue
                pos = target.position_at(now)
                angle = math.atan2(pos[1]-start[1],pos[0]-start[0])-theta
                if abs(math.atan2(math.sin(angle),math.cos(angle)))>math.radians(30):
                    continue
                packets.extend(self.damage(cast['power']*D('1.87'),now,target=target,school='energy')[0])
                packets.extend(self._buff(333402,now,target.id)+self._curse(target,now))
            return packets+self.sync_speed(now)
        return super()._event(now,kind,data)

    def handle(self,message,payload):
        if message==514:
            packets = self.arena.tick(self.clock())
            if not self.arena.input_open(self.clock(),self):return packets
            if self.channel and len(payload)==8:
                scene_id,x,y = struct.unpack_from('<Ihh',payload)
                if scene_id==self.scene_id and (x,y)!=self.position_at(self.clock()):
                    self.channel['dest'] = x,y
            return packets
        return super().handle(message,payload)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot in (0,10) and (not self._inside(dest) or start==dest):
            return []
        from bot_ai import team_visible
        target = self.arena.actors.get(target_id)
        if slot==1 and (not self.e_count or not target or not target.alive or target.camp==self.camp
                       or target.is_untargetable() or math.dist(start,target.position_at(now))>600
                       or not team_visible(self.arena,self,target,now)):
            return []
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:3000,2:0,10:10000}[slot], slot)
        if slot==0:
            return self.shoot(333100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        if slot==1:
            self.e_count -= 1
            if not self.e_next_charge:
                self.e_next_charge = now+self.skill_cooldown(8000)
            cast = dict(hits=set(),power=power,generation=self.generation)
            return self.shoot(333201,start,target.position_at(now),now,power*D('1.51'),school='energy',
                              target=target,through_walls=True,context=cast)+[self._cooldown(1)]
        if slot==2:
            self.channel = dict(dest=dest if dest!=start else (start[0]+600,start[1]),generation=self.generation)
            self._queue(now+500,'medusa_channel',self.channel)
            packets = [scene(skills=(self._skill_event(333301,start,start,self.id),))]
            for t in range(333301,333306):
                packets.extend(self._buff(t,now))
            return packets+[self._cooldown(2)]+self.sync_speed(now)
        origin,stopped = prepare_displacement(self,now,interrupt=False)
        self.position,self.motion = origin if stopped else start,None
        self.ready = dict(slot=10,dest=dest,power=power,generation=self.generation)
        self._queue(now+500,'medusa_gaze',self.ready)
        return [self._cooldown(10),scene(skills=(self._skill_event(333401,start,dest,ready=1),))]+self.sync_speed(now)+stopped
