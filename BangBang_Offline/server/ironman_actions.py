"""Iron Man base kit; original packets/data and provisional V1 arithmetic."""
from battle_participants import human, private
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import TANK_CONTACT_RADIUS
from combat_math import D
from combat_protocol import props, scene
from melee_common import prepare_displacement

SLOTS = {0:363100, 1:363201, 2:363301, 10:363401}
# Original effect chain applies silence/root before control immunity. Reversing
# this order makes _buff reject the caster's own root. Client movement also
# needs the speed update supplied by _speed below.
CHANNEL_BUFFS = (363301,363303,363304,363302,363308,363309)


class IronManActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.skills = {i:table_row('SkillTemplate_table.xml',nId=i) for i in SLOTS.values()}
        self.ready = self.channel = None
        self.shield_epoch = 0
        self.cancel_available = False

    def _cooldown(self, slot, changed=False):
        skill = 363601 if slot==2 and self.cancel_available else SLOTS[slot]
        end = 0 if slot==2 and self.cancel_available else self.cooldowns[slot]
        body = props(skill,slot,end=end)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self, now):
        self.shield_epoch += 1
        return self.add_shield(363102,self.max_hp*D('.3'),now)

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None or self.channel is not None

    def _speed(self, now):
        # Original SelfTank checks TankModel.selfSpeed (<12), not BUT_STILL,
        # before local movement. sync_speed sends S1560 on channel start/end;
        # resume_packets also uses this value for an ongoing saved channel.
        return 0 if self.channel is not None else super()._speed(now)

    def on_shield_break(self, template, now):
        if template!=363102:
            return []
        self.shield_epoch += 1
        packets = self._buff(363104,now)
        if self.alive:
            packets.extend(self._buff(363103,now))
            self._queue(now+15000,'shield_return',self.generation,self.shield_epoch)
        for target in list(self.arena.actors.values()):
            if target.alive and target.camp!=self.camp and target.is_area_targetable() and math.dist(self.position_at(now),target.position_at(now))<=300:
                packets.extend(self.damage(self.combat_stat('iAttack',now)*D('2.36'),now,target=target)[0])
        return packets

    def interrupt(self, now):
        packets = []
        if self.ready:
            slot = self.ready['slot']
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,SLOTS[slot])))
        if self.channel:
            self.channel = None
            self.cancel_available = False
            for template in CHANNEL_BUFFS+(363601,):
                packets.extend(self.remove_buff(template,now))
            packets.extend((self._cooldown(2,True),self._cooldown(2)))
        return packets

    def on_death(self):
        self.ready = self.channel = None
        self.cancel_available = False
        self.shield_epoch += 1

    def on_bullet_hit(self, flight, target, now):
        if flight['template']!=363401:
            return []
        packets = []
        if target.has_buff(363206,now):
            packets.extend(self._buff(363203,now,target.id))
        packets.extend(self._buff(363402,now,target.id))
        packets.extend(self._buff(363403,now,target.id))
        return packets

    def handle(self, message, payload):
        if message==514:
            now = self.clock()
            packets = self.arena.tick(now)
            if not self.arena.input_open(now,self):return packets
            if len(payload)==8 and self.channel and self.alive:
                scene_id,x,y = struct.unpack('<Ihh',payload)
                # Original SelfTimmingSkillCaster projects 2000 units, often
                # outside the map. These are aiming coordinates, not movement.
                if scene_id==self.scene_id and (x,y)!=self.position_at(now):
                    self.channel['dest'] = (x,y)
            return packets
        return super().handle(message,payload)

    def bot_beam_dest(self,now):
        cast=self.channel;start=self.position_at(now)
        angle=cast.get('beam_angle',math.atan2(cast['dest'][1]-start[1],cast['dest'][0]-start[0]))
        goal=cast.get('beam_goal',angle)
        delta=(goal-angle+math.pi)%(2*math.pi)-math.pi
        # CTank.addTimmingSkillBuff -> UniformRotater: fEffectValB degrees/sec.
        speed=math.radians(int(table_row('BuffTemplate_table.xml',nBuffId=363301)['fEffectValB']))
        step=speed*max(0,now-cast.get('beam_aim_at',cast['began']))/1000
        angle+=max(-step,min(step,delta))
        cast.update(beam_angle=angle,beam_goal=goal,beam_aim_at=now)
        return tuple(round(v) for v in (start[0]+2000*math.cos(angle),start[1]+2000*math.sin(angle)))

    def aim_bot_channel(self,dest,now):
        if not self.channel:return []
        self.bot_beam_dest(now)
        start=self.position_at(now)
        self.channel['beam_goal']=math.atan2(dest[1]-start[1],dest[0]-start[0])
        # Native packet rotates the remote cannon/beam with the same limiter.
        return [(1603,struct.pack('<Ihh',self.id,*dest))]

    def _area_object(self, template, position):
        ident = self._new_id(4)
        # Keep ObjInfo in the checkpoint; NotifyAddObject prefixes the scene ID.
        body = struct.pack('<IIhhiBiIiH',ident,template,*position,0,self.camp,0,self.id,0,0)
        self.arena.objects[ident] = body.hex()
        return ident,(1556,struct.pack('<I',self.scene_id)+body)

    def _event(self, now, kind, data):
        if kind=='shield_return':
            generation,epoch = data
            return self.on_spawn(now) if self.alive and self.generation==generation and self.shield_epoch==epoch else []
        if kind=='prepared':
            cast, = data
            if self.ready is not cast or not self.alive or cast['generation']!=self.generation:
                return []
            self.ready = None
            slot,start,dest,power = (cast[k] for k in ('slot','start','dest','power'))
            packets = [scene(skills=(self._skill_event(SLOTS[slot],start,dest),))]
            if slot==1:
                ident,packet = self._area_object(363201,dest)
                packets.append(packet)
                self._queue(now+50,'area_start',ident,dest,power)
            elif slot==10:
                packets.extend(self.shoot(363401,start,dest,now,power*D('2.67'),school='physical'))
            else:
                self.channel = cast
                cast['began'] = now
                if not human(self):
                    self.bot_beam_dest(now)
                    packets.append((1603,struct.pack('<Ihh',self.id,*dest)))
                self.shield_epoch += 1  # Space refreshes the single passive shield.
                packets.extend(self.remove_buff(363103,now))
                packets.extend(self.add_shield(363102,self.max_hp*D('.3'),now))
                for buff in CHANNEL_BUFFS:
                    packets.extend(self._buff(buff,now))
                for offset in range(200,4001,200):
                    self._queue(now+offset,'beam_tick',cast)
                self._queue(now+1000,'enable_cancel',cast)
                self._queue(now+4000,'channel_end',cast)
            return packets
        if kind=='area_start':
            old,dest,power = data
            self.arena.objects.pop(old,None)
            ident,packet = self._area_object(363204,dest)
            for offset in range(500,3001,500):
                self._queue(now+offset,'area_tick',dest,power)
            self._queue(now+3000,'area_end',ident)
            return [scene(removed=(struct.pack('<I',old),)),packet]
        if kind=='area_end':
            self.arena.objects.pop(data[0],None)
            return [scene(removed=(struct.pack('<I',data[0]),))]
        if kind=='area_tick':
            dest,power = data
            packets = []
            for target in list(self.arena.actors.values()):
                if not target.alive or target.camp==self.camp or not target.is_area_targetable() or math.dist(dest,target.position_at(now))>144:
                    continue
                packets.extend(self.damage(power*D('.75'),now,target=target)[0])
                if target.has_buff(363402,now):
                    packets.extend(self._buff(363203,now,target.id))
                packets.extend(self._buff(363206,now,target.id))
            return packets
        if kind in ('beam_tick','enable_cancel','channel_end'):
            cast, = data
            if self.channel is not cast or not self.alive:
                return []
            if kind=='channel_end':
                return self.interrupt(now)
            if kind=='enable_cancel':
                self.cancel_available = True
                return [self._cooldown(2,True),self._cooldown(2)]
            start,dest = self.position_at(now),(self.bot_beam_dest(now) if not human(self) else cast['dest'])
            dx,dy = dest[0]-start[0],dest[1]-start[1]
            length = math.hypot(dx,dy)
            if not length:
                return []
            packets = [scene(skills=(self._skill_event(363501,start,dest),))]
            for target in list(self.arena.actors.values()):
                if not target.alive or target.camp==self.camp or not target.is_area_targetable():continue
                tx,ty = target.position_at(now)
                ax,ay = tx-start[0],ty-start[1]
                along,side = (ax*dx+ay*dy)/length,(-ax*dy+ay*dx)/length
                if math.hypot(max(0,-along,along-600),max(0,abs(side)-24))<=TANK_CONTACT_RADIUS:
                    packets.extend(self.damage(cast['power']*D('1.25'),now,target=target,lifesteal=D('.25'))[0])
            return packets
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target, now):
        if slot==2 and self.channel and self.cancel_available and self.alive:
            return self.interrupt(now)
        if slot not in SLOTS or self.blocked('attack',now) or self.cooldowns[slot]>now:
            return []
        if not self._inside(dest) or (start==dest and slot!=1):
            return []
        row = self.skills[SLOTS[slot]]
        if slot==1 and math.dist(start,dest)>int(row['iRange']):
            return []
        self.cooldowns[slot] = now+(self.skill_cooldown(self.fire_interval(now) if slot==0 else int(row['iCoolTime']), slot))
        power = self.combat_stat('iAttack',now)
        if slot==0:
            return self.shoot(363100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(0)]
        body,stopped = prepare_displacement(self,now,interrupt=False)
        self.position,self.motion = body if stopped else start,None
        self.ready = dict(slot=slot,start=start,dest=dest,power=power,generation=self.generation)
        self._queue(now+int(row['iReadyTime']),'prepared',self.ready)
        return [scene(moves=(self._move_event(start,0,5),),skills=(self._skill_event(SLOTS[slot],start,dest,ready=1),)),self._cooldown(slot)]+stopped
