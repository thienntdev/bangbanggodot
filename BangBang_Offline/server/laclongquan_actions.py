"""Lac Long Quan: two safe dashes, two independent shields and water form."""
import math
import struct

from battle_runtime import TankActions
from combat_geometry import actor_contact, rect_contact
from combat_math import D
from combat_protocol import props, scene, stop_move
from melee_common import aimed, enemies, piercing_step, prepare_displacement, accept_water_reclip

SLOTS = {0:387100, 1:387201, 2:387301, 10:387401}


class LacLongQuanActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.dash = self.form = None
        self.e_second_until = self.e_gap_until = 0
        self.passive_ready_at = 0

    def _cooldown(self,slot,changed=False):
        now = getattr(self.arena,'event_now',None) or self.clock()
        skill,end = SLOTS[slot],self.cooldowns[slot]
        if slot==0 and self.form:skill = 387311
        if slot==1 and now<self.e_second_until:skill,end = 387231,self.e_gap_until
        if slot==2 and self.form:
            skill = 387331 if self.has_buff(387313,now) and self.buff_stacks.get(387313,0)>=4 else 387321
            end = self.cooldowns[2] if self.form['used'] else 0
        body = props(skill,slot,-1,end)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.dash = self.form = None
        self.e_second_until = self.e_gap_until = 0
        self.passive_ready_at = 0
        return self.add_shield(387101,self.max_hp*D('.15'),now)+[self._cooldown(s,True) for s in (0,1,2)]

    def attr_bonus(self,attributes,now):
        result = super().attr_bonus(attributes,now)
        if 5 in attributes and self.has_buff(387313,now):
            result -= D('.05')*self.buff_stacks.get(387313,1)  # AP only, not energy attack.
        return result

    def blocked(self,action,now):
        return bool(self.dash) or super().blocked(action,now)

    def interrupt(self,now):
        packets = []
        if self.dash:
            pos = self.stop_position(now)
            self.dash = None
            self.position,self.motion,self.forced_until = pos,None,now
            packets.append(stop_move(self.scene_id,self.id,pos))
            for t in (387201,387206):packets += self.remove_buff(t,now)
        if not self.alive and self.form:
            self.cooldowns[2] = now+self.skill_cooldown(30000,2)
            self.form = None
        return packets+self.sync_speed(now)

    def remove_buff(self,template,now,*,expired=False):
        packets = super().remove_buff(template,now,expired=expired)
        if template==387313:
            for visual in range(387351,387355):
                if self.has_buff(visual,now):packets += self.remove_buff(visual,now)
        if template==387202 and self.e_second_until and now>=self.e_second_until:
            self.e_second_until = 0
            packets.append(self._cooldown(1,True))
        return packets

    def on_shield_break(self,template,now):
        if template!=387101 or not self.alive:return []
        self.passive_ready_at = now+15000
        self._queue(self.passive_ready_at,'lac_shield',self.generation)
        packets = self._buff(387102,now)+self._buff(387104,now)
        for target in self._targets(self.position_at(now),192,now):
            packets += self.damage(self.combat_stat('iAttack',now)*D('2.31'),now,target=target)[0]
            if self.arena.pk and self.arena.pk['finished']:return packets
            packets += self._buff(387105,now,target.id)
        return packets

    def _targets(self,pos,radius,now):
        return [a for a in enemies(self,area=True) if math.dist(pos,a.position_at(now))<=radius
                and rect_contact(pos,a.position_at(now),self.arena.water_rects(now),0) is None]

    def _flight(self,flight,now):
        if flight['template']==387311:
            return piercing_step(self,flight,now,self._water_hit,pierce=False,contact_radius=48)
        return super()._flight(flight,now)

    def _water_hit(self,flight,target,now):
        packets = []
        for enemy in self._targets(target.position_at(now),144,now):
            raw = flight['raw']*(D('.5') if enemy.info.get('map_turret') or enemy.info.get('base') else 1)
            packets += self.damage(raw,now,target=enemy,basic=True,source_generation=flight['source_generation'])[0]
            if self.arena.pk and self.arena.pk['finished']:return packets
            packets += self._buff(387312,now,enemy.id)+self._buff(387316,now,enemy.id)
        if self.alive and self.generation==flight['source_generation'] and self.form:
            packets += self.restore_hp(max(D(0),self.max_hp-self.hp)*D('.05'),now)
            count = min(5,self.buff_stacks.get(387313,0)+1) if self.has_buff(387313,now) else 1
            packets += self._buff(387313,now,stacks=count)+self._buff(387314,now,stacks=count)
            visual = 387350+min(count,4)
            for other in range(387351,387355):
                if other!=visual and self.has_buff(other,now):packets += self.remove_buff(other,now)
            packets += self._buff(visual,now)
            if count>=4 and not self.form['used']:packets += self._buff(387318,now,duration=max(1,self.form['end']-now))
            packets.append(self._cooldown(2,True))
        return packets

    def _push(self,target,cast,now):
        if not target.alive or target.cc_immune(now):return []
        start,packets = prepare_displacement(target,now)
        dx,dy = cast['direction']
        dest = target.move_destination(start,aimed(start,(start[0]+dx,start[1]+dy),cast['distance'],fixed=True))
        if dest==start:return packets
        duration = target._set_motion(start,dest,cast['speed'],now,kind=1)
        target.forced_until = now+duration
        return packets+[scene(moves=(target._move_event(target.motion[1],cast['speed'],1),))]

    def _event(self,now,kind,data):
        if kind=='lac_visual_remove':
            # Native SceneItemTemplet plays these movies on ITEM_REMOVE,
            # never on ITEM_OVERTIME. Only the visual object is retired here;
            # the existing lac_wave/R damage callbacks remain authoritative.
            return self.remove_object(data[0],destroyed=True)
        if kind=='lac_shield':
            return self.add_shield(387101,self.max_hp*D('.15'),now) if self.alive and self.generation==data[0] else []
        if kind=='lac_dash':
            cast, = data
            if self.dash is not cast or not self.alive:return []
            if self.motion!=cast['motion'] and not accept_water_reclip(self,cast):return self.interrupt(now)
            start,end = self.position_at(cast['previous']),self.position_at(now)
            packets = []
            for target in enemies(self,area=True):
                key = target.id,target.generation
                if key not in cast['hits'] and actor_contact(start,end,target,cast['previous'],now,36) is not None:
                    cast['hits'].add(key)
                    packets += self._push(target,cast,now)
                    if self.arena.pk and self.arena.pk['finished']:return packets
            if now<self.motion[3]:
                cast['previous'] = now
                self._queue(min(now+20,self.motion[3]),kind,cast)
                return packets
            self.position,self.motion,self.forced_until = self.stop_position(now),None,now
            self.dash = None
            for t in (387201,387206):packets += self.remove_buff(t,now)
            packets.append(stop_move(self.scene_id,self.id,self.position))
            packets += self._buff(387207 if cast['second'] else 387203,now)
            for target in self._targets(self.position,168,now):
                raw = cast['power']*D('1.57' if cast['second'] else '1.23')
                if target.info.get('map_turret') or target.info.get('base'):raw *= D('.5')
                packets += self.damage(raw,now,target=target,source_generation=cast['generation'])[0]
                if self.arena.pk and self.arena.pk['finished']:return packets
                if cast['second']:packets += self._buff(387210,now,target.id)
            return packets+self.sync_speed(now)
        if kind=='lac_form_end':
            cast, = data
            if self.form is not cast:return []
            self.form = None
            self.cooldowns[2] = now+self.skill_cooldown(30000,2)
            packets = []
            for template in (387301,387302,387303,387304,387318):packets += self.remove_buff(template,now)
            return packets+[self._cooldown(0,True),self._cooldown(2,True)]+self.sync_speed(now)
        if kind=='lac_wave':
            cast,index = data
            raw = cast['power']*D('3.68' if cast['enhanced'] and index==1 else '2.16')
            debuff = 387339 if index==2 else 387337 if cast['enhanced'] else 387327
            packets = []
            for target in self._targets(cast['pos'],192,now):
                packets += self.damage(raw,now,target=target,source_generation=cast['generation'])[0]
                if self.arena.pk and self.arena.pk['finished']:return packets
                packets += self._buff(debuff,now,target.id)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if self.arena.pk and self.arena.pk['finished']:return []
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now):return []
        second = slot==1 and now<self.e_second_until
        wave = slot==2 and self.form is not None
        if (self.e_gap_until if second else 0 if wave and not self.form['used'] else self.cooldowns[slot])>now:return []
        if wave and self.form['used']:return []
        if slot in (0,1) and (start==dest or not self._inside(dest)):return []
        if wave and (not self._inside(dest) or math.dist(start,dest)>600):return []
        if slot==10:
            from bot_ai import team_visible
            targets = [a for a in enemies(self) if math.dist(start,a.position_at(now))<=192
                       and team_visible(self.arena,self,a,now)]
            if not targets:return []
            target = min(targets,key=lambda a:(bool(a.info.get('npc_template')),math.dist(start,a.position_at(now)),a.id))
            dest = target.position_at(now)
        power = self.combat_stat('iAttack',now)
        if slot==0:
            self.cooldowns[0] = now+self.fire_interval(now)
            return [self._cooldown(0)]+self.shoot(387311 if self.form else 387100,start,dest,now,
                    power*(D('1.5') if self.form else 1),school='physical',basic=True,power=power)
        if not second and not wave:
            self.cooldowns[slot] = now+self.skill_cooldown({1:8000,2:30000,10:6000}[slot],slot)
        skill = 387231 if second else 387331 if wave and self.buff_stacks.get(387313,0)>=4 and self.has_buff(387313,now) else 387321 if wave else SLOTS[slot]
        packets = [scene(skills=(self._skill_event(skill,start,dest,target.id if slot==10 else 0),))]
        if slot==1:
            start,pre = prepare_displacement(self,now,interrupt=False)
            packets += pre
            distance,speed = (240,600) if second else (192,480)
            end = self.move_destination(start,aimed(start,dest,distance))
            duration = self._set_motion(start,end,speed,now,kind=1)
            self.forced_until = now+duration
            self.dash = dict(previous=now,motion=self.motion,generation=self.generation,power=power,
                             direction=(dest[0]-start[0],dest[1]-start[1]),distance=distance,speed=speed,second=second,hits=set())
            if second:
                self.e_second_until = 0
                packets += self.remove_buff(387202,now)
            else:
                self.e_second_until,self.e_gap_until = now+2000,now+500
                packets += self._buff(387202,now)
            packets += self._buff(387206 if second else 387201,now,duration=duration)
            packets.append(scene(moves=(self._move_event(end,speed,1),)))
            self._queue(now+min(20,duration),'lac_dash',self.dash)
        elif slot==2 and not wave:
            self.form = dict(end=now+8000,used=False,generation=self.generation)
            self.cooldowns[2] = self.form['end']+self.skill_cooldown(30000,2)
            for template in (387301,387302,387303,387304):packets += self._buff(template,now)
            self._queue(self.form['end'],'lac_form_end',self.form)
            packets.append(self._cooldown(0,True))
        elif wave:
            self.form['used'] = True
            cast = dict(pos=dest,power=power,generation=self.generation,enhanced=skill==387331)
            obj,packet = self.add_object(387331 if cast['enhanced'] else 387321,dest)
            packets.append(packet)
            self._queue(now+1000,'object_expire',obj)
            # Effect387321/387331 creates the presentation props at cast time.
            # Props387322/387332 last 300ms, and Props387333 lasts 1300ms:
            # their removal starts the original dragon movie ahead of each
            # unchanged 1000/2000ms damage impact, as in the Flash template.
            visuals = ((387332,300),(387333,1300)) if cast['enhanced'] else ((387322,300),)
            for template,delay in visuals:
                visual,packet = self.add_object(template,dest)
                packets.append(packet)
                self._queue(now+delay,'lac_visual_remove',visual)
            self._queue(now+1000,'lac_wave',cast,1)
            if cast['enhanced']:self._queue(now+2000,'lac_wave',cast,2)
            for template in (387304,387318):packets += self.remove_buff(template,now)
        else:
            obj,packet = self.add_object(387401,dest)
            packets.append(packet)
            self._queue(now+50,'lac_visual_remove',obj)
            for enemy in self._targets(dest,168,now):
                raw = power*D('2.04')*(D('.5') if enemy.info.get('map_turret') or enemy.info.get('base') else 1)
                packets += self.damage(raw,now,target=enemy)[0]
                if self.arena.pk and self.arena.pk['finished']:return packets
                packets += self._buff(387402,now,enemy.id)+self._buff(387404,now,enemy.id)
            packets += self.add_shield(387405,self.max_hp*D('.15'),now)
        return packets+[self._cooldown(slot,True)]+self.sync_speed(now)
