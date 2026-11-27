"""Thuy Tinh: five marks, one reward per freeze and native NPC water walls."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import point_at, rect_contact
from combat_math import D
from combat_protocol import props,scene
from melee_common import prepare_displacement

SLOTS = {0:353100,1:353201,2:353301,10:353101}
MARKS = (353200,353201,353202,353204)
ICE = (353121,353122,353123,353125)


class ThuyTinhActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ice = self.ready = self.water_wall = None
        self.passive_ready_at = 0

    def _cooldown(self,slot,changed=False):
        cancel = slot==1 and self.water_wall is not None and self.has_buff(353501,self.clock())
        body = props(353501 if cancel else SLOTS[slot],slot,end=0 if cancel else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        return self._buff(353111,now)+[self._cooldown(1,True)]

    def _speed(self,now):
        return 0 if self.ready or self.ice else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.ready) or super().blocked(action,now)

    def cc_immune(self,now,*,slow=False):
        return bool(self.ice) or super().cc_immune(now,slow=slow)

    def reject_buff(self,row,source,now):
        return bool(self.ice and source.camp!=self.camp)

    def _end_ice(self,now):
        if not self.ice:
            return []
        self.ice = None
        packets = []
        for t in ICE:
            packets.extend(self.remove_buff(t,now))
        return packets+self._buff(353131,now)+self.sync_speed(now)

    def commit_hp(self,hp,now,*,critical=False):
        if self.hp>0 and hp==0 and not self.ice and now>=self.passive_ready_at:
            packets = self.interrupt(now)+self.cleanse(now)
            self.passive_ready_at = now+15000
            packets.extend(super().commit_hp(1,now,critical=critical))
            self.ice = dict(end=now+2000,generation=self.generation)
            for index in range(1,5):
                self._queue(now+index*500,'thuy_ice',self.ice,index)
            for t in ICE:
                packets.extend(self._buff(t,now,duration=2000))
            packets.extend(self._buff(353124,now,duration=15000))
            return packets+self.sync_speed(now)
        return super().commit_hp(hp,now,critical=critical)

    def interrupt(self,now):
        packets = []
        if self.ready:
            self.ready = None
            packets.append((1583,struct.pack('<II',self.id,353301)))
        if not self.alive:
            packets.extend(self._end_ice(now))
        return packets+self.sync_speed(now)

    def update(self,now):
        packets = self.interrupt(now) if self.ready and self.skill_sealed(2,now) else []
        return packets+super().update(now)

    def _mark(self,target,now,count=1):
        if not target.alive or target.has_buff(353403,now) or target.reject_buff({'nEffectType':'201'},self,now):
            return []
        stage = max((i+1 for i,t in enumerate(MARKS) if target.has_buff(t,now)),default=0)
        packets = []
        for t in MARKS:
            if target.has_buff(t,now):
                packets.extend(target.remove_buff(t,now))
        if stage+count<5:
            return packets+self._buff(MARKS[stage+count-1],now,target.id)
        for t in (353401,353403,353205):
            packets.extend(self._buff(t,now,target.id))
        return packets

    def on_bullet_hit(self,flight,target,now):
        return self._mark(target,now) if flight['template']==353100 else []

    def _remove_wall(self,now):
        wall,self.water_wall = self.water_wall,None
        if not wall:
            return []
        packets = []
        for ident,_ in wall['blocks']:
            packets.extend(self.remove_object(ident,destroyed=True))
        packets.extend(self.remove_object(wall['prop']))
        packets.extend(self.remove_buff(353501,now))
        return packets+[self._cooldown(1,True),self._cooldown(1)]

    def _create_wall(self,start,center,power,now):
        length = math.dist(start,center)
        normal = ((center[0]-start[0])/length,(center[1]-start[1])/length)
        axis = -normal[1],normal[0]
        packets = []
        # Effect's damage rectangle is separate from the approved 648 wall.
        for target in list(self.arena.actors.values()):
            pos = target.position_at(now)
            offset = pos[0]-center[0],pos[1]-center[1]
            if target.alive and target.camp!=self.camp and abs(sum(a*b for a,b in zip(offset,axis)))<=108 and abs(sum(a*b for a,b in zip(offset,normal)))<=36:
                packets.extend(self.damage(power*D('2.21'),now,target=target,school='energy')[0])
                if self.arena.pk and self.arena.pk['finished']:
                    return packets
                packets.extend(self._mark(target,now,2))
        centers = [tuple(round(a+b*index*72) for a,b in zip(center,axis)) for index in range(-4,5)]
        centers = [p for p in centers if self.arena.geometry.clamp_tank_position(p)==p]
        planned = [(p,(p[0]-36,p[1]-36,p[0]+36,p[1]+36)) for p in centers]
        ident,packet = self.add_object(353205,center)
        wall = self.water_wall = dict(blocks=[],prop=ident,end=now+4000)
        packets.append(packet)
        for pos,rect in planned:
            pushes = {}
            for target in self.arena.actors.values():
                current = target.position_at(now)
                if not target.alive or rect_contact(current,current,(rect,),36-.001) is None:
                    continue
                if target.info.get('npc_template'):
                    pushes = None  # Fixed turret: skip this block, never move it.
                    break
                occupied = [pushes.get(a.id,a.position_at(now)) for a in self.arena.actors.values() if a.alive and a.id!=target.id]
                dest = self.arena.free_position(current,now,extra=[r for _,r in planned],occupied=occupied)
                if dest is None:
                    pushes = None
                    break
                pushes[target.id] = dest
            if pushes is None:
                continue
            for owner,dest in pushes.items():
                target = self.arena.actors[owner]
                packets.extend(target.interrupt(now))
                target.position,target.motion,target.forced_until = dest,None,now
                packets.append(scene(moves=(target._move_event(dest,0,5),)))
            block = self._new_id(3)
            body = struct.pack('<IIhhiBiIiH',block,353201,*pos,-1,self.camp,-1,self.id,0,0)
            self.arena.objects[block] = body.hex()
            wall['blocks'].append((block,pos))
            packets.append((1556,struct.pack('<I',self.scene_id)+body))
        # Clip movements already under way when the obstacle appeared.
        for target in self.arena.actors.values():
            if not target.alive or not target.motion or target.motion[3]<=now:
                continue
            origin,dest = target.position_at(now),target.motion[1]
            if (not target.motion_kind and target.forced_until<=now
                    and rect_contact(origin,dest,self.arena.water_rects(now),36-.001) is None):
                # A distant new wall must not apply dash-footprint clearance
                # to an ordinary step already accepted by the nine-grid rule.
                continue
            clipped = self.arena.clip_motion(origin,dest,now)
            if clipped!=dest:
                old_motion = target.motion
                old_reclip = getattr(target,'water_motion_reclip',None)
                motion_origin = (old_reclip['origin'] if old_reclip
                    and old_reclip.get('generation')==target.generation
                    and old_reclip.get('motion')==old_motion else dict(motion=old_motion))
                speed = max(1,round(math.dist(origin,dest)*1000/(target.motion[3]-now)))
                kind = target.motion_kind
                origin,stopped = prepare_displacement(target,now,interrupt=False)
                packets.extend(stopped)
                clipped = self.arena.clip_motion(origin,dest,now)
                duration = target._set_motion(origin,clipped,speed,now,kind)
                target.forced_until = min(target.forced_until,now+duration)
                if kind==1:
                    # Preserve only the first/current segment, not an unbounded
                    # history. Other sources break the exact lineage above.
                    target.water_motion_reclip = dict(generation=target.generation,
                        origin=motion_origin,motion=target.motion)
                packets.append(scene(moves=(target._move_event(clipped,speed,kind),)))
        self._queue(now+4000,'thuy_wall_end',wall)
        return packets+self._buff(353501,now)+[self._cooldown(1,True)]

    def _event(self,now,kind,data):
        if kind=='thuy_ice':
            cast,index = data
            if self.ice is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            packets = self.restore_hp(self.max_hp*D('.0375'),now)
            return packets+self._end_ice(now) if index==4 else packets
        if kind=='thuy_wall_end':
            return self._remove_wall(now) if self.water_wall is data[0] else []
        if kind=='thuy_space_cast':
            cast, = data
            if self.ready is not cast or not self.alive or self.skill_sealed(2,now):
                return self.interrupt(now) if self.ready is cast else []
            self.ready = None
            start = self.position_at(now)
            return self.shoot(353301,start,cast['dest'],now,0,school='energy',power=cast['power'],
                              through_walls=True,context=cast,fixed_destination=True)+self.sync_speed(now)
        if kind=='thuy_area':
            cast,index = data
            packets = []
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(cast['pos'],target.position_at(now))<=288:
                    packets.extend(self.damage(cast['power']*D('.81'),now,target=target,school='energy',periodic=True)[0])
                    packets.extend(self._mark(target,now)+self._buff(353304,now,target.id))
            if self.alive and self.generation==cast['generation'] and math.dist(cast['pos'],self.position_at(now))<=288:
                packets.extend(self.restore_hp(cast['power']*D('.5'),now))
            if index==8:
                packets.extend(self.remove_object(cast['id']))
            else:
                self._queue(now+500,kind,cast,index+1)
            return packets
        return super()._event(now,kind,data)

    def _flight(self,flight,now):
        if flight['template']==353100:
            return super()._flight(flight,now)
        if now<flight['finish']:
            flight['previous'] = now
            self._queue(min(now+20,flight['finish']),'flight',flight)
            return []
        ident,packet = self.add_object(353301,flight['end'])
        cast = dict(id=ident,pos=flight['end'],power=flight['power'],generation=flight['source_generation'])
        self._queue(now+500,'thuy_area',cast,1)
        return [scene(blown_bullets=(struct.pack('<I',flight['id']),)),packet]

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now):
            return []
        cancel = slot==1 and self.water_wall and self.has_buff(353501,now)
        if not cancel and self.cooldowns[slot]>now:
            return []
        if not cancel and (not self._inside(dest) or slot in (0,1) and start==dest or slot!=0 and math.dist(start,dest)>600):
            return []
        if cancel:
            return self._end_ice(now)+[scene(skills=(self._skill_event(353501,start,start,self.id),))]+self._remove_wall(now)
        power = self.combat_stat('iEgAtk',now)
        self.cooldowns[slot] = now+self.skill_cooldown({0:self.fire_interval(now),1:10000,2:25000,10:6000}[slot], slot)
        if slot==0:
            return self.shoot(353100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(0)]
        packets = self._end_ice(now)
        packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,dest,ready=int(slot==2)),)))
        if slot==10:
            for target in list(self.arena.actors.values()):
                if not target.alive or target.camp==self.camp or math.dist(dest,target.position_at(now))>192:
                    continue
                missing = target.max_hp-target.hp
                packets.extend(self._buff(353300,now,target.id)+self._mark(target,now))
                version = target.buff_versions.get(353205,0)
                extra = target.has_buff(353205,now) and getattr(target,'freeze_consumed_version',None)!=version
                if extra:
                    target.freeze_consumed_version = version
                packets.extend(self.damage(power*D('1.75'),now,target=target,school='energy')[0])
                if extra:
                    packets.extend(self.damage(power*D('2.25')+missing*D('.15'),now,target=target,school='energy')[0])
                    packets.extend(self._buff(353601,now,target.id))
                    self.cooldowns[10] = now
        elif slot==1:
            packets.extend(self._create_wall(start,dest,power,now))
        else:
            _,stopped = prepare_displacement(self,now,interrupt=False)
            ident,packet = self.add_object(353801,dest)
            self._queue(now+50,'object_expire',ident)
            self.ready = dict(slot=2,dest=dest,power=power,generation=self.generation)
            self._queue(now+50,'thuy_space_cast',self.ready)
            packets.append(packet)
            return packets+[self._cooldown(slot)]+self.sync_speed(now)+stopped
        return packets+[self._cooldown(slot)]+self.sync_speed(now)
