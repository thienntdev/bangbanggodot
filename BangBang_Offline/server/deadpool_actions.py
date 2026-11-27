"""Deadpool: one rescue per R window and deduplicated continuous knockback."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_geometry import actor_contact, circle_contact, point_at
from combat_math import D
from combat_protocol import props,scene,stop_move
from melee_common import aimed,enemies,accept_water_reclip,prepare_displacement

SLOTS={0:344100,1:344201,2:344301,10:344101}


class DeadpoolActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.rebirth=self.mark=None

    def _cooldown(self,slot,changed=False):
        follow=slot==1 and self.mark is not None and self.has_buff(344212,self.clock())
        body=props(344202 if follow else SLOTS[slot],slot,end=0 if follow else self.cooldowns[slot])
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=self.rebirth=self.mark=None
        self.info['untargetable']=self.info['damage_immune']=False
        return [self._cooldown(1,True)]

    def attr_bonus(self,attributes,now):
        value=super().attr_bonus(attributes,now)
        if 4 in attributes and self.has_buff(344112,now):value+=D('.05')*self.buff_stacks[344112]
        return value

    def _speed(self,now):
        return 0 if self.rebirth else super()._speed(now)

    def blocked(self,action,now):
        return bool(self.rebirth or self.ready and action=='attack') or super().blocked(action,now)

    def reject_buff(self,row,source,now):
        return bool(self.rebirth and source.camp!=self.camp)

    def cc_immune(self,now,*,slow=False):
        return bool(self.rebirth) or super().cc_immune(now,slow=slow)

    def restore_hp(self,amount,now):
        return [] if self.rebirth else super().restore_hp(amount,now)

    def commit_hp(self,hp,now,*,critical=False):
        if self.alive and hp==0 and self.has_buff(344101,now) and not self.rebirth:
            _,stopped=prepare_displacement(self,now,interrupt=False)
            packets=self.interrupt(now)+self.remove_buff(344101,now)+self.cleanse(now)
            self.position,self.motion,self.forced_until=self.position_at(now),None,now
            self.rebirth=dict(end=now+1000,was_immune=self.info.get('damage_immune',False),
                              was_untargetable=self.info.get('untargetable',False))
            self.info['untargetable']=self.info['damage_immune']=True
            # Keep the actor alive server-side: no kill, execute reward or
            # ordinary 2-second respawn is scheduled during this rescue.
            packets.extend(super().commit_hp(D(1),now,critical=critical))
            packets.extend(self._buff(344103,now)+self._buff(344104,now))
            self._queue(now+1000,'deadpool_return',self.rebirth)
            return packets+stopped+[scene(moves=(self._move_event(self.position,0,5),))]+self.sync_speed(now)
        if self.rebirth and hp<self.hp:return []
        return super().commit_hp(hp,now,critical=critical)

    def interrupt(self,now):
        if not self.ready:return []
        self.ready=None
        return [(1583,struct.pack('<II',self.id,344202))]

    def on_control(self,source,template,now):
        if self.ready and int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']) in (30,35,66):
            return self.interrupt(now)
        return []

    def remove_buff(self,template,now,*,expired=False):
        packets=super().remove_buff(template,now,expired=expired)
        if template==344212:
            self.mark=None;packets.append(self._cooldown(1,True))
        return packets

    def _marked_target(self,now):
        mark=self.mark
        if not mark:return None
        target=self.arena.actors.get(mark['target'])
        if (target and target.alive and target.generation==mark['target_generation']
                and target.has_buff(344211,now) and target.buff_versions.get(344211)==mark['version']):return target
        return None

    def update(self,now):
        packets=[]
        if self.mark and not self._marked_target(now):packets.extend(self.remove_buff(344212,now))
        if self.ready and self.skill_sealed(1,now):packets.extend(self.interrupt(now))
        return packets+super().update(now)

    def on_bullet_hit(self,flight,target,now):
        if flight['template']!=344201 or not self.alive or flight['source_generation']!=self.generation:return []
        packets=self._buff(344211,now,target.id)
        if target.has_buff(344211,now) and target.buff_sources.get(344211)==self.id:
            self.mark=dict(target=target.id,target_generation=target.generation,version=target.buff_versions[344211])
            packets.extend(self._buff(344212,now));packets.append(self._cooldown(1,True))
        return packets

    def _push(self,target,start,power,now):
        if not target.alive or target.cc_immune(now):return []
        current=target.position_at(now);pos=target.stop_position(now)
        direction=(pos[0]-start[0],pos[1]-start[1])
        if direction==(0,0):direction=(1,0)
        dest=aimed(pos,(pos[0]+direction[0],pos[1]+direction[1]),480,fixed=True)
        wall=self.arena.geometry.wall_contact(pos,dest,36)
        if wall is not None:dest=point_at(pos,dest,max(0,wall-.00001))
        requested=dest
        if pos!=current:target.position,target.motion=pos,None
        packets=target.interrupt(now)
        if pos!=current:packets.append(stop_move(target.scene_id,target.id,pos))
        duration=target._set_motion(pos,dest,720,now,kind=1);target.forced_until=now+duration
        cast=dict(target=target.id,target_generation=target.generation,power=power,previous=now,end=now+duration,
                  motion=target.motion,wall=wall is not None or math.dist(requested,target.motion[1])>.1,hits=set())
        self._queue(now+min(20,duration),'deadpool_push',cast)
        return packets+self._buff(344303,now,target.id,duration=duration)+[scene(moves=(self._move_event(target.motion[1],720,1,target.id),))]

    def _event(self,now,kind,data):
        if kind=='deadpool_return':
            cast,=data
            if self.rebirth is not cast or not self.alive:return []
            self.rebirth=None
            self.info['damage_immune']=cast['was_immune'];self.info['untargetable']=cast['was_untargetable']
            packets=self.remove_buff(344103,now)+self.remove_buff(344104,now)+super().commit_hp(self.max_hp*D('.5'),now)
            for template in (344106,344108,344109,344110,344111,344112,344113):packets.extend(self._buff(template,now))
            ident,packet=self.add_object(344107,self.position_at(now));packets.append(packet)
            self._queue(now+1000,'object_expire',ident)
            return packets+self.sync_speed(now)
        if kind=='deadpool_recast':
            cast,=data
            if self.ready is not cast or not self.alive:return []
            self.ready=None;target=self.arena.actors.get(cast['target'])
            if (not target or not target.alive or target.generation!=cast['target_generation']
                    or target.is_untargetable() or not target.has_buff(344211,now)
                    or target.buff_versions.get(344211)!=cast['version']):return []
            start=self.position_at(now);dest=self.blink_destination(start,target.position_at(now))
            self.position,self.motion,self.forced_until=dest,None,now
            packets=[scene(moves=(self._move_event(dest,0,5),)),scene(skills=(self._skill_event(344202,start,dest,target.id),))]
            packets.extend(self.damage((target.max_hp-target.hp)*D('.25'),now,target=target,school='true')[0])
            packets.extend(self._buff(344204,now)+self._buff(344205,now,target.id)+self._buff(344207,now,target.id)+self._buff(344206,now))
            return packets
        if kind=='deadpool_push':
            cast,=data;target=self.arena.actors.get(cast['target'])
            if not target or not target.alive or target.generation!=cast['target_generation']:return []
            if target.motion!=cast['motion']:
                if (target.motion and target.motion_kind==1 and target.motion[3]<=cast['end']
                        and target.has_buff(344303,now) and accept_water_reclip(target,cast)):
                    cast['motion']=target.motion;cast['previous']=max(cast['previous'],target.motion[2])
                    cast['end']=target.motion[3];cast['wall']=True
                else:return target.remove_buff(344303,now)
            start,end=target.position_at(cast['previous']),target.position_at(now);packets=[]
            contacts=[]
            for other in enemies(self):
                key=other.id,other.generation
                if other is target or key in cast['hits']:continue
                hit=actor_contact(start,end,other,cast['previous'],now,radius=72)
                if hit is not None:contacts.append((hit,other.id,other,key))
            for _,_,other,key in sorted(contacts,key=lambda v:v[:2]):
                cast['hits'].add(key)
                for victim in (target,other):
                    packets.extend(self.damage(cast['power']*D('2.5'),now,target=victim)[0])
                    if self.arena.pk and self.arena.pk['finished']:return packets
                    if victim.alive:packets.extend(self._buff(344305,now,victim.id))
                if not target.alive or target.is_untargetable():return packets
                # Its knockup must not cancel the approved continuing push.
                target.motion=cast['motion'];target.position=cast['motion'][1];target.motion_kind=1
                target.forced_until=cast['end']
                packets.append(scene(moves=(self._move_event(target.motion[1],720,1,target.id),)))
            if now>=cast['end']:
                target.position,target.motion,target.forced_until=end,None,now
                packets.extend(target.remove_buff(344303,now))
                packets.append(scene(moves=(self._move_event(end,0,5,target.id),)))
                if cast['wall']:
                    packets.extend(self.damage(cast['power']*D('2.5'),now,target=target)[0])
                    packets.extend(self._buff(344307,now,target.id))
                return packets
            cast['previous']=now;self._queue(min(now+20,cast['end']),kind,cast)
            return packets
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now):return []
        follow=slot==1 and self.mark and self.has_buff(344212,now)
        if not follow and self.cooldowns[slot]>now:return []
        if follow:
            target=self._marked_target(now)
            # Native STARGET_OBJ_NEAREST may submit target=0; the marked
            # actor is selected by the server, never by mouse coordinates.
            if not target or target_id not in (0,target.id) or target.is_untargetable() or math.dist(start,target.position_at(now))>600:return []
            from bot_ai import team_visible
            if not team_visible(self.arena,self,target,now):return []
            self.ready=dict(self.mark,slot=1,skill=344202,dest=target.position_at(now),end=now+50)
            self._queue(now+50,'deadpool_recast',self.ready)
            return self.remove_buff(344212,now)+[scene(skills=(self._skill_event(344202,start,target.position_at(now),target.id,ready=1),))]
        if slot in (0,1) and start==dest:return []
        if slot==2:
            target=self.arena.actors.get(target_id)
            if not target or target not in enemies(self) or math.dist(start,target.position_at(now))>168:return []
            from bot_ai import team_visible
            if not team_visible(self.arena,self,target,now):return []
        power=self.combat_stat('iAttack',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:6000,2:15000,10:8000}[slot], slot)
        packets=[self._cooldown(slot)]
        if slot in (0,1):
            return packets+self.shoot(SLOTS[slot],start,dest,now,power*(D('1.85') if slot==1 else 1),school='physical',basic=slot==0,through_walls=slot==1)
        packets.append(scene(skills=(self._skill_event(SLOTS[slot],start,dest,target_id),)))
        if slot==10:return packets+self._buff(344101,now)
        packets.extend(self.damage(power*D('3.58'),now,target=target)[0])
        if self.arena.pk and self.arena.pk['finished']:return packets
        return packets+self._push(target,start,power,now)
