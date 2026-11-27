"""Son Tinh: shared scatter hits, separate form HP and persistent curses."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene, stop_move
from melee_common import prepare_displacement

SLOTS = {0:326100, 1:326201, 2:326301, 10:326401}
RAGE = (326201,326202,326203,326204,326205)
FORM = (326301,326304,326305,326306,326307,326308,326309,326310,326316,326321,326322)


class SonTinhActions(TankActions):
    def __init__(self, *args):
        super().__init__(*args)
        self.ready = self.form = None
        self.rage_until = 0
        self.curses = {}

    def _cooldown(self, slot, changed=False):
        active = self.form and self.form['phase']=='active'
        skill = 326331 if slot==0 and active else 326371 if slot==2 and self.form else SLOTS[slot]
        body = props(skill,slot,-1,self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def _slots(self):
        return [p for slot in (0,2) for p in (self._cooldown(slot,True),self._cooldown(slot))]

    def on_spawn(self, now):
        return self._buff(326101,now)

    def blocked(self, action, now):
        return super().blocked(action,now) or self.ready is not None or bool(self.form and self.form['phase']=='gathering')

    def _speed(self, now):
        return 0 if self.ready or self.form and self.form['phase']=='gathering' else super()._speed(now)

    def interrupt(self, now):
        packets = self._end_rage(now) if not self.alive else []
        if not self.ready:
            return packets
        ready,self.ready = self.ready,None
        if ready['slot']==2:
            self.cooldowns[2] = now+self.skill_cooldown(30000, 2)
        return packets+[(1583,struct.pack('<II',self.id,326301 if ready['slot']==2 else 326331)),self._cooldown(ready['slot'])]

    def _end_form(self, now):
        form,self.form = self.form,None
        if form is None:
            return []
        position,_ = prepare_displacement(self,now,interrupt=False)
        self.info.pop('death_floor',None)
        self.info['untargetable'] = False
        self.position,self.motion,self.forced_until = position,None,now
        self.cooldowns[2] = now+self.skill_cooldown(30000, 2)
        packets = [stop_move(self.scene_id,self.id,self.position)]
        for template in FORM:
            packets.extend(self.remove_buff(template,now))
        # User: this returns the original HP, including after lethal form damage.
        packets.extend(super().commit_hp(form['saved_hp'],now))
        packets.extend(self._slots())
        for template in (326341,326343,326344):
            packets.extend(self._buff(template,now))
        return packets+self.sync_speed(now)

    def commit_hp(self, hp, now,*,critical=False):
        if self.form and self.form['phase']=='active' and hp<=0:
            return self._end_form(now)  # No death/respawn/kill reward for destroying the form.
        return super().commit_hp(hp,now,critical=critical)

    def _end_rage(self, now):
        if not self.rage_until:
            return []
        self.rage_until = 0
        self.cooldowns[1] = now+self.skill_cooldown(8000, 1)
        packets = []
        for template in RAGE:
            packets.extend(self.remove_buff(template,now))
        return packets+self._buff(326211,now)+[self._cooldown(1)]

    def on_death(self):
        self.ready = None

    def on_target_death(self, target, now):
        for token,curse in list(self.curses.items()):
            if curse['target']==target.id:
                del self.curses[token]
        return []

    def _fire(self, start, dest, now, power):
        stone = bool(self.form and self.form['phase']=='active')
        template = 326331 if stone else 326100
        rage = self.rage_until>now
        shared,packets = set(),[]
        angle = math.atan2(dest[1]-start[1],dest[0]-start[0])
        # User-approved temporary fan; one victim can be damaged once per volley.
        for offset in ((0,-15,15) if rage else (0,)):
            direction = angle+math.radians(offset)
            aim = (round(start[0]+600*math.cos(direction)),round(start[1]+600*math.sin(direction)))
            packets.extend(self.shoot(template,start,aim,now,power if stone else power*D('1.5'),
                school='physical',basic=True,power=power,speed_multiplier=1.5,
                lifesteal=D('.5') if rage else D('.25'),shared_hits=shared if rage else None))
        return packets

    def _hit(self, flight, target, now):
        key = target.id,target.generation
        if key in flight['hits'] or not target.alive:
            return []
        flight['hits'].add(key)
        steal = flight['lifesteal'] if flight['source_generation']==self.generation else 0
        packets,_ = self.damage(flight['raw'],now,target=target,basic=True,
            ignore_armor=flight['template']==326331,lifesteal=steal)
        if target.alive:
            # Passive follows the primary hit. V1 keeps physical defenses other
            # than armor and does not apply the unresolved raw .08 limit.
            bonus = (target.max_hp-target.hp)*D('.03')
            packets.extend(self.damage(bonus,now,target=target,basic=True,ignore_armor=True,lifesteal=steal)[0])
            packets.extend(self._buff(326112,now,target.id))
            if flight['template']==326331:
                packets.extend(self._buff(326332,now,target.id))
        return packets

    def _flight(self, flight, now):
        if flight['template'] not in (326100,326331):
            return super()._flight(flight,now)
        begin,finish,previous = flight['begin'],flight['finish'],flight['previous']
        start = point_at(flight['start'],flight['end'],(previous-begin)/(finish-begin))
        end = point_at(flight['start'],flight['end'],min(1,(now-begin)/(finish-begin)))
        contacts = []
        for target in self.arena.actors.values():
            if target.alive and target.camp!=self.camp:
                hit = actor_contact(start,end,target,previous,now)
                if hit is not None:
                    contacts.append((hit,target.id))
        wall = self.arena.geometry.wall_contact(start,end)  # User: both spear and stone stop at walls.
        if contacts and (wall is None or min(contacts)[0]<wall):
            target = self.arena.actors[min(contacts)[1]]
            if self.projectile_blocked(target,now):
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            targets = [target]
            if flight['template']==326331:
                targets = [a for a in self.arena.actors.values() if a.alive and a.camp!=self.camp
                           and math.dist(a.position_at(now),target.position_at(now))<=120]
            packets = []
            for victim in targets:
                packets.extend(self._hit(flight,victim,now))
            return packets+[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if wall is not None or now>=finish:
            return [scene(**{('blown_bullets' if wall is not None else 'expired_bullets'):
                            (struct.pack('<I',flight['id']),)})]
        flight['previous'] = now
        self._queue(min(now+20,finish),'flight',flight)
        return []

    def _event(self, now, kind, data):
        if kind=='son_rage_end':
            generation, = data
            return self._end_rage(now) if generation==self.generation and self.rage_until==now else []
        if kind=='son_ready':
            cast, = data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:
                return []
            self.ready = None
            if cast['slot']==0:
                return self._fire(self.position_at(now),cast['dest'],now,cast['power'])
            self.form = dict(phase='gathering',saved_hp=self.hp,generation=self.generation,end=now+14600)
            packets = super().commit_hp(self.max_hp,now)
            self.info['death_floor'] = 1  # Original HP_KEEP while vanished.
            self.info['untargetable'] = True
            cast['dest'] = self.blink_destination(self.position_at(now),cast['dest'])
            self.position,self.motion = cast['dest'],None
            packets.append(scene(moves=(self._move_event(cast['dest'],0,5),)))
            for template in (326301,326304,326305,326306,326307,326308,326316):
                packets.extend(self._buff(template,now))
            ident,packet = self.add_object(326309,cast['dest'])
            self._queue(now+1000,'son_land',dict(form=self.form,id=ident,pos=cast['dest'],power=cast['power']))
            return packets+[packet]+self._slots()+self.sync_speed(now)
        if kind=='son_land':
            cast, = data
            packets = self.remove_object(cast['id'])
            if self.form is not cast['form']:
                return packets
            for target in list(self.arena.actors.values()):
                if target.alive and target.camp!=self.camp and math.dist(cast['pos'],target.position_at(now))<=168:
                    packets.extend(self.damage(cast['power']*D('3.51'),now,target=target)[0])
                    packets.extend(self._buff(326312,now,target.id))
            ident,packet = self.add_object(326313,cast['pos'])
            self._queue(now+1600,'son_form',cast['form'],ident)
            return packets+[packet]
        if kind=='son_form':
            form,ident = data
            packets = self.remove_object(ident)
            if self.form is not form:
                return packets
            form['phase'] = 'active'
            self.info.pop('death_floor',None)
            self.info['untargetable'] = False
            for template in (326304,326305):
                packets.extend(self.remove_buff(template,now))
            for template in (326309,326310,326316,326321,326322):
                packets.extend(self._buff(template,now,duration=12000))
            self._queue(now+12000,'son_form_end',form)
            return packets+self._slots()+self.sync_speed(now)
        if kind=='son_form_end':
            return self._end_form(now) if self.form is data[0] else []
        if kind=='son_curse_area':
            cast, = data
            packets = self.remove_object(cast['id'],destroyed=True)
            for target in self.arena.actors.values():
                if not target.alive or target.camp==self.camp or math.dist(cast['pos'],target.position_at(now))>168:
                    continue
                for template in (326402,326403,326404):
                    packets.extend(self._buff(template,now,target.id))
                if not target.has_buff(326403,now):
                    continue
                token = self.active_buffs[(target.id,326403)][0]
                curse = dict(target=target.id,target_generation=target.generation,power=cast['power'],
                             source_generation=cast['generation'],token=token,version=target.buff_versions[326403])
                self.curses[token] = curse
                self._queue(now+2500,'son_petrify',curse)
                self._queue(now+3000,'son_curse_end',curse)
            return packets
        if kind in ('son_petrify','son_curse_end'):
            curse, = data
            target = self.arena.actors[curse['target']]
            if (self.curses.get(curse['token']) is not curse or not target.alive
                    or target.generation!=curse['target_generation'] or target.buff_versions.get(326403)!=curse['version']):
                self.curses.pop(curse['token'],None)
                return []
            if kind=='son_petrify':
                return self._buff(326411,now,target.id)
            del self.curses[curse['token']]
            return self.damage(curse['power']*D('2.23'),now,target=target)[0]+self._buff(326422,now,target.id)
        return super()._event(now,kind,data)

    def cast(self, slot, start, dest, target_id, now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:
            return []
        if slot==1:
            if self.rage_until:
                return []
            self.rage_until = now+4000
            self._queue(self.rage_until,'son_rage_end',self.generation)
            packets = []
            for template in RAGE:
                packets.extend(self._buff(template,now))
            return packets
        if not self._inside(dest) or start==dest:
            return []
        power = self.combat_stat('iAttack',now)
        if slot==0:
            self.cooldowns[0] = now+self.fire_interval(now)
            if not self.form:
                return self._fire(start,dest,now,power)
            self.ready = dict(slot=0,skill=326331,dest=dest,power=power,generation=self.generation)
            self._queue(now+100,'son_ready',self.ready)
            ident,packet = self.add_object(326351,dest)
            self._queue(now+500,'object_expire',ident)
            return [packet,scene(skills=(self._skill_event(326331,start,dest,ready=1),))]+self.sync_speed(now)
        if slot==2 and self.form:
            return []
        distance = math.dist(start,dest)
        dest = tuple(round(v) for v in point_at(start,dest,min(1,480/distance)))
        if slot==2:
            dest = self.blink_destination(start,dest)
            body,stopped=prepare_displacement(self,now,interrupt=False)
            self.ready = dict(slot=2,dest=dest,power=power,generation=self.generation)
            self.position,self.motion = body if stopped else start,None
            self._queue(now+100,'son_ready',self.ready)
            return [scene(skills=(self._skill_event(326301,start,dest,ready=1),))]+self.sync_speed(now)+stopped
        self.cooldowns[10] = now+self.skill_cooldown(10000, 10)
        ident,packet = self.add_object(326401,dest)
        self._queue(now+1000,'son_curse_area',dict(id=ident,pos=dest,power=power,generation=self.generation))
        return [packet,self._cooldown(10)]
