"""Doraemon: non-stacking traps, paired reactions and one-use portals."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props, scene
from melee_common import aimed, enemies, prepare_displacement

SLOTS={0:354100,1:354201,2:354301,10:354401}


class DoraemonActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=None
        self.portals={}
        self.marks={}
        self.reactions=set()
        self.passive_ready_at=0

    def _cooldown(self,slot,changed=False):
        body=props(SLOTS[slot],slot,-1,self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=None
        return self._buff(354101,now)

    def is_untargetable(self):
        now=getattr(self.arena,'event_now',None) or self.clock()
        return self.has_buff(354121,now) or super().is_untargetable()

    def is_area_targetable(self):
        return not super().is_untargetable()

    def on_damage(self,source,hit,now,school,reflected,attacker_ap):
        if not self.alive or hit.hp_loss<=0:return []
        packets=self._buff(354111,now)
        if self.hp<self.max_hp*D('.3') and now>=self.passive_ready_at:
            self.passive_ready_at=now+30000
            for template in range(354121,354127):packets.extend(self._buff(template,now))
        return packets

    def _end_flight(self,now):
        packets=[]
        if self.has_buff(354121,now):
            for template in (354121,354122,354124,354125,354126):packets.extend(self.remove_buff(template,now))
            packets.extend(self._buff(354131,now))
        return packets

    def _speed(self,now):return 0 if self.ready else super()._speed(now)
    def blocked(self,action,now):return bool(self.ready) or super().blocked(action,now)

    def interrupt(self,now):
        packets=[]
        if self.ready:
            packets.append((1583,struct.pack('<II',self.id,354301)));self.ready=None
        if not self.alive:
            for ident in list(self.portals):packets.extend(self.remove_object(ident))
            self.portals.clear()
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        if not self.ready:return []
        row=table_row('BuffTemplate_table.xml',nBuffId=template);mask=int(row.get('fEffectValB',0))
        return self.interrupt(now) if row['nEffectType'] in ('35','66') and (not mask or mask&4) else []

    def update(self,now):
        self.marks={key:value for key,value in self.marks.items() if value['end']>now}
        active={value['cast'] for value in self.marks.values()}
        self.reactions={key for key in self.reactions if key[0] in active or key[1] in active}
        return (self.interrupt(now) if self.ready and self.skill_sealed(2,now) else [])+super().update(now)

    def _mark(self,target,cast,kind,now):
        template=354208 if kind=='e' else 354303
        packets=self._buff(template,now,target.id)
        if not target.alive or not target.has_buff(template,now):return packets
        key=(target.id,target.generation,kind)
        self.marks[key]=dict(cast=cast['token'],end=now+3000,version=target.buff_versions[template])
        other=self.marks.get((target.id,target.generation,'space' if kind=='e' else 'e'))
        other_template=354303 if kind=='e' else 354208
        if other and other['end']>now and target.has_buff(other_template,now) and target.buff_versions.get(other_template)==other['version']:
            pair=(cast['token'],other['cast']) if kind=='e' else (other['cast'],cast['token'])
            identity=(*pair,target.id,target.generation)
            if identity not in self.reactions:
                self.reactions.add(identity)
                packets.extend(self.damage(target.max_hp*D('.1'),now,target=target,school='true')[0])
                packets.extend(self._buff(354304,now,target.id))
        return packets

    def _trap_tick(self,cast,now,index):
        packets=[]
        for target in list(self.arena.actors.values()):
            if not target.alive or not target.is_area_targetable() or math.dist(target.position_at(now),cast['pos'])>84:continue
            if target.camp==self.camp:
                if target is self and cast['generation']!=self.generation:continue
                if target.has_buff(354209,now) or target.effect_blocked():continue
                packets.extend(target.cleanse(now)+target.restore_hp(cast['power']*D('2.09'),now))
                if hasattr(target,'_resource'):
                    packets.extend(target._resource(30,now) if target.info['tank_id']==10000033 else target._resource(30))
                packets.extend(self._buff(354209,now,target.id,duration=3500)+self._buff(354210,now,target.id,duration=3500))
            else:
                packets.extend(self._buff(354203,now,target.id)+self._buff(354204,now,target.id))
                if index>0 and index%2==0 and getattr(target,'dora_next_tick',0)<=now:
                    target.dora_next_tick=now+500
                    hit,lost=self.damage(cast['power']*D('.5'),now,target=target,school='energy',periodic=True)
                    packets.extend(hit)
                    if lost:packets.extend(self._mark(target,cast,'e',now))
        if index==12:
            for ident in cast['objects']:packets.extend(self.remove_object(ident))
        else:self._queue(now+250,'dora_trap_tick',cast,index+1)
        return packets

    def _portal_enter(self,portal,target,now):
        packets=self.remove_object(portal['id'],destroyed=True)
        self.portals.pop(portal['id'],None)
        _,stopped=prepare_displacement(target,now,interrupt=False)
        packets.extend(target.interrupt(now))
        target.position,target.motion=target.position_at(now),None
        travel=dict(owner=self.id,generation=self.generation,target=target.id,target_generation=target.generation,
                    pos=target.position,power=portal['power'],end=now+1000)
        packets.extend(self._buff(354404,now,target.id))
        target.dora_travel=travel
        self._queue(now+1000,'dora_exit',travel)
        return packets+stopped+[scene(moves=(target._move_event(target.position,0,5),))]+target.sync_speed(now)

    def _flight(self,flight,now):
        if flight['template']==354100:return super()._flight(flight,now)
        if flight['template']==354301:
            a=point_at(flight['start'],flight['end'],(flight['previous']-flight['begin'])/(flight['finish']-flight['begin']))
            b=point_at(flight['start'],flight['end'],min(1,(now-flight['begin'])/(flight['finish']-flight['begin'])))
            for target in self.arena.actors.values():
                if target.alive and target.camp!=self.camp and not target.is_untargetable() and actor_contact(a,b,target,flight['previous'],now) is not None and self.projectile_blocked(target,now):
                    return self.remove_object(flight['context']['warning'])+[scene(expired_bullets=(struct.pack('<I',flight['id']),))]
        if now<flight['finish']:
            flight['previous']=now;self._queue(min(now+20,flight['finish']),'flight',flight);return []
        packets=[scene(blown_bullets=(struct.pack('<I',flight['id']),))]
        if flight['template']==354401:
            if not self.alive or self.generation!=flight['source_generation']:return packets
            ident,packet=self.add_object(354401,flight['end']);packets.append(packet)
            portal=dict(id=ident,pos=flight['end'],power=flight['power'],end=now+4000,previous=now,generation=self.generation)
            self.portals[ident]=portal;self._queue(now+50,'dora_portal',portal)
            return packets
        cast=flight['context']
        packets.extend(self.remove_object(cast['warning']))
        for target in enemies(self,area=True):
            if math.dist(flight['end'],target.position_at(now))>168:continue
            packets.extend(self.damage(cast['power']*D('3.35'),now,target=target,school='energy')[0])
            if self.arena.pk and self.arena.pk['finished']:return packets
            if target.alive and not target.cc_immune(now):
                origin,stopped=prepare_displacement(target,now,interrupt=False)
                packets.extend(stopped)
                dest=target.move_destination(origin,flight['end'])
                target.position,target.motion=dest,None
                packets.append(scene(moves=(target._move_event(dest,0,5),)))
            packets.extend(self._mark(target,cast,'space',now))
        return packets

    def _event(self,now,kind,data):
        if kind=='dora_trap_open':
            cast,=data
            packets=self.remove_object(cast['warning'])
            ident,packet=self.add_object(354203,cast['pos']);packets.append(packet);cast['objects'].append(ident)
            return packets+self._trap_tick(cast,now,0)
        if kind=='dora_trap_tick':return self._trap_tick(data[0],now,data[1])
        if kind=='dora_space':
            cast,=data
            if self.ready is not cast or not self.alive or self.generation!=cast['generation']:return []
            self.ready=None
            return self.sync_speed(now)+self.shoot(354301,self.position_at(now),cast['dest'],now,D(0),school='energy',
                power=cast['power'],fixed_destination=True,through_walls=True,context=cast)
        if kind=='dora_portal':
            portal,=data
            if self.portals.get(portal['id']) is not portal:return []
            targets=[]
            for target in self.arena.actors.values():
                if not target.alive or target.camp!=self.camp or target.info.get('npc_template') or target.is_untargetable():continue
                hit=circle_contact(target.position_at(portal['previous']),target.position_at(now),portal['pos'],portal['pos'],72)
                if hit is not None:targets.append((hit,target.id,target))
            if targets:return self._portal_enter(portal,min(targets)[2],now)
            if now>=portal['end']:
                del self.portals[portal['id']];return self.remove_object(portal['id'])
            portal['previous']=now;self._queue(min(now+50,portal['end']),kind,portal);return []
        if kind=='dora_exit':
            travel,=data;target=self.arena.actors.get(travel['target'])
            if not target or not target.alive or target.generation!=travel['target_generation'] or getattr(target,'dora_travel',None) is not travel:return []
            target.dora_travel=None
            dest=self.position_at(now) if self.alive and self.generation==travel['generation'] else travel['pos']
            dest=target.blink_destination(target.position_at(now),dest)
            target.position,target.motion=dest,None;target.portal_safe_until=now+500
            return target.remove_buff(354404,now)+[scene(moves=(target._move_event(dest,0,5),))]+target.restore_hp(travel['power']*D('2.13'),now)+target.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        if slot==0 and start==dest:return []
        power=self.combat_stat('iEgAtk',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:25000,10:8000}[slot], slot)
        packets=[] if slot==0 else self._end_flight(now)
        if slot==0:return self.shoot(354100,start,dest,now,power,school='energy',basic=True)+[self._cooldown(slot)]
        dest=aimed(start,dest,600 if slot==10 else 480)
        if slot==10:
            dest=self.arena.free_position(dest,now) or start
            return packets+self.shoot(354401,start,dest,now,D(0),school='energy',power=power,fixed_destination=True,through_walls=True)+[self._cooldown(slot)]
        cast=dict(slot=slot,skill=SLOTS[slot],pos=dest,dest=dest,power=power,generation=self.generation,token=self._new_id(2),objects=[])
        stopped=[]
        if slot==1:
            ident,packet=self.add_object(354201,dest);packets.append(packet);cast['objects'].append(ident)
            cast['warning'],packet=self.add_object(354202,dest);packets.append(packet)
            self._queue(now+500,'dora_trap_open',cast)
        else:
            body,stopped=prepare_displacement(self,now,interrupt=False)
            self.ready=cast;self.position,self.motion=body if stopped else start,None
            cast['warning'],packet=self.add_object(354305,dest);packets.append(packet)
            self._queue(now+700,'object_expire',cast['warning'])
            packets.append(scene(skills=(self._skill_event(354301,start,dest,ready=1),)))
            self._queue(now+50,'dora_space',cast)
        return packets+[self._cooldown(slot)]+self.sync_speed(now)+stopped
