"""Kakashi's copied button and the still-live effects of earlier E casts."""
import math
import struct

from battle_runtime import TankActions, tank_action_classes
from borrowed_e import executor
from combat_protocol import props, scene
from combat_math import D


class BorrowedKits:
    def attr_bonus(self,attributes,now):
        value=super().attr_bonus(attributes,now)
        if 34 in attributes:
            pen=getattr(self,'_borrow_pen',None)
            value+=pen if pen is not None else D('.25') if self.has_buff(305201,now) else D(0)
        return value

    def borrowed_damage(self,view,raw,now,**kwargs):
        # Borrowed E strips donor guaranteed criticals; do not inherit their visual tag.
        kwargs['critical_display']=False
        pen=getattr(self,'_borrow_pen',None);multiplier=getattr(self,'_borrow_damage_multiplier',None)
        self._borrow_pen=getattr(view,'_borrow_pen',view._session.get('pen',D(0)))
        if kwargs.get('source_generation')!=self.generation:
            self._borrow_damage_multiplier=getattr(view,'_borrow_multiplier',view._session.get('multiplier',D(1)))
        try:return self.damage(raw,now,**kwargs)
        finally:self._borrow_pen=pen;self._borrow_damage_multiplier=multiplier

    def break_borrowed_stealth(self,now,existing):
        packets=[]
        for template,version in existing.items():
            if self.has_buff(template,now) and self.buff_versions.get(template)==version:
                packets+=self.remove_buff(template,now)
        return packets

    def stealth_versions(self,now):
        return {t:self.buff_versions[t] for t in (330131,322201,305202,390201)
                if self.has_buff(t,now)}

    def borrowed_views(self, *, current=True):
        return [executor(self,key) for key,s in self.borrow_sessions.items()
                if s['used'] and (not current or s['generation']==self.generation)]

    def borrowed_basic(self, now):
        for view in sorted(self.borrowed_views(),key=lambda v:(v._session.get('used_at',0),v._session['serial']),reverse=True):
            tank=view._session['tank']-10000000
            # A repeated copy of the same E replaces its buff instance.
            owned=lambda t:self.has_buff(t,now) and self.borrow_buff_owners.get(t)==view._session['serial']
            active={44:lambda:bool(view.shots and owned(318201)),
                    51:lambda:view.rage_until>now and owned(326201),69:lambda:owned(343201),
                    77:lambda:bool(view.scatter_count and owned(351204)),
                    95:lambda:owned(370203) or owned(370207),
                    104:lambda:bool(view.enhanced and owned(379203)),108:lambda:owned(383203),
                    114:lambda:owned(390204)}.get(tank)
            if active and active():return view
        return None

    def borrowed_slot(self, slot, now):
        view=executor(self,self.borrowed) if slot==1 and self.borrowed is not None else self.borrowed_basic(now) if slot==0 else None
        if view is None:return None
        skill,_,_,end,_=view.native_slot(slot)
        if slot==0 and view._session['tank'] in (10000051,10000077):skill=330100
        if slot==0:end=self.cooldowns[0]
        elif not view._session['used']:end=0
        return props(skill,slot,-1,end)

    def _borrow_finished(self, view, now, packets):
        session=view._session
        if self.borrowed!=session['serial'] or not session['used']:return packets
        skill=view.native_slot(1)[0]
        pending=bool(getattr(view,'ready',None) or getattr(view,'dash',None))
        if session['tank']==10000070:
            pending=pending or any(cb.__self__ is view and args[0]=='flight' for _,_,cb,args in self.arena.pending)
        if skill==session['base_skill'] and not pending:
            self.borrowed=None
            packets=list(packets)+[(-2,True)]
        return packets

    def cast_borrowed(self, start, dest, target_id, now):
        if self.ready or self.dash or self.vanish or TankActions.blocked(self,'attack',now) or self.skill_sealed(1,now):return []
        view=executor(self,self.borrowed) if self.borrowed is not None else None
        if any(v is not view and v.blocked('attack',now) for v in self.borrowed_views()):return []
        stealth=self.stealth_versions(now)
        if view is None:
            target=self.arena.actors.get(target_id)
            if (now<self.cooldowns[1] or self.mp<10 or not target or not target.alive
                    or target.is_untargetable() or target.info.get('npc_template')
                    or target.info['tank_id']==10000055 or target.info['tank_id'] not in tank_action_classes()
                    or math.dist(start,target.position_at(now))>960):return []
            if target.camp!=self.camp:
                from bot_ai import team_visible
                if not team_visible(self.arena,self,target,now):return []
            self.borrow_serial+=1;serial=self.borrow_serial
            self.borrow_sessions[serial]=dict(serial=serial,tank=target.info['tank_id'],generation=self.generation,
                                               used=False,copied_at=now)
            self.borrowed=serial
            view=executor(self,serial)
            view._session['base_skill']=view.native_slot(1)[0]
            self.cooldowns[1]=now+self.skill_cooldown(10000, 1)
            packets=self.break_borrowed_stealth(now,stealth)+self._resource(-10)+self._empower(now)
            packets+=self._buff(330203,now,duration=-1)
            packets.append(scene(skills=(self._skill_event(330201,start,target.position_at(now),target.id),)))
            return packets+[self._cooldown(1,True),self._cooldown(1)]
        packets=view.run('cast',1,start,dest,target_id,now)
        if packets:packets+=self.break_borrowed_stealth(now,stealth)+self._empower(now)
        return packets

    def blocked(self, action, now):
        return super().blocked(action,now) or any(v.blocked(action,now) for v in self.borrowed_views())

    def _speed(self, now):
        values=[super()._speed(now)]+[v._speed(now) for v in self.borrowed_views()]
        return min(values)

    def is_untargetable(self):
        return super().is_untargetable() or any(v.is_untargetable() for v in self.borrowed_views())

    def is_area_targetable(self):
        return not self.in_stasis() and all(v.is_area_targetable() for v in self.borrowed_views())

    def cc_immune(self, now, *, slow=False):
        return super().cc_immune(now,slow=slow) or any(v.cc_immune(now,slow=slow) for v in self.borrowed_views())

    def damage_immune(self, school, now, periodic=False):
        return super().damage_immune(school,now,periodic) or any(v.damage_immune(school,now,periodic) for v in self.borrowed_views())

    def reject_buff(self, row, source, now):
        return super().reject_buff(row,source,now) or any(v.reject_buff(row,source,now) for v in self.borrowed_views())

    def remove_buff(self, template, now, *, expired=False):
        serial=self.borrow_buff_owners.pop(template,None)
        if serial is not None and serial in self.borrow_sessions:
            return executor(self,serial).run('remove_buff',template,now,expired=expired)
        return super().remove_buff(template,now,expired=expired)

    def update(self, now):
        packets=[]
        for view in self.borrowed_views():packets+=view.update_borrowed(now)
        pending={cb.__self__._session['serial'] for _,_,cb,_ in self.arena.pending
                 if '_session' in vars(cb.__self__) and cb.__self__.id==self.id}
        pending.update(cb.__self__.info.get('borrow_session') for _,_,cb,_ in self.arena.pending
                       if getattr(cb.__self__,'info',{}).get('owner')==self.id)
        summoned={a.info.get('borrow_session') for a in self.arena.actors.values()
                  if a.alive and a.info.get('owner')==self.id}
        buffs={serial for template,serial in self.borrow_buff_owners.items() if self.has_buff(template,now)}
        for serial,session in list(self.borrow_sessions.items()):
            if serial==self.borrowed or serial in pending|summoned|buffs:continue
            state=session['state']
            if state.get('combo_until',0)>now:continue
            del self.borrow_sessions[serial]
            self.__dict__.get('_borrow_views',{}).pop(serial,None)
        self.borrow_buff_owners={t:s for t,s in self.borrow_buff_owners.items() if s in self.borrow_sessions}
        retained={(s['generation'],s['tank']) for s in self.borrow_sessions.values()}
        self.borrow_memory={k:v for k,v in self.borrow_memory.items() if k[0]==self.generation or k in retained}
        return packets+super().update(now)

    def interrupt(self, now):
        packets=[]
        motion=self.motion
        for view in self.borrowed_views():packets+=view.run('interrupt',now)
        if motion and self.motion is None and self.alive:
            pos=self.move_destination(motion[0],self.position)
            if pos!=self.position:
                self.position=pos
                packets.append(scene(moves=(self._move_event(pos,0,5),)))
        return packets+super().interrupt(now)

    def on_death(self):
        for view in self.borrowed_views():view.on_death()
        self.borrowed=None
        self.borrow_buff_owners.clear()
        return super().on_death()

    def on_control(self, source, template, now):
        packets=[]
        for view in self.borrowed_views():
            # Na Tra's reaction to CC is an independent passive.
            if view._session['tank']!=10000082:packets+=view.run('on_control',source,template,now)
        return packets

    def on_skill_damage(self, source, hit, now):
        packets=[]
        for view in self.borrowed_views():
            if view._session['tank']==10000036:packets+=view.run('on_skill_damage',source,hit,now)
        return packets

    def on_damage(self, source, hit, now, school, reflected, attacker_ap):
        packets=[]
        for view in self.borrowed_views():
            if view._session['tank'] in (10000030,10000114):
                packets+=view.run('on_damage',source,hit,now,school,reflected,attacker_ap)
        return packets

    def on_target_death(self, target, now):
        packets=[]
        for view in self.borrowed_views():
            if view._session['tank'] in (10000083,10000051):packets+=view.run('on_target_death',target,now)
        return packets

    def reflect_projectile(self, flight, now):
        for view in reversed(self.borrowed_views()):
            if view._session['tank']==10000111 and view.reflect_projectile(flight,now):return True
        return False

    def handle(self, message, payload):
        views=self.borrowed_views()
        if message==510 and len(payload)>=12:
            view=next((v for v in views if v._session['tank']==10000111 and v.reflections),None)
            if view:
                packets=self.arena.tick(self.clock())
                if not self.arena.input_open(self.clock(),self):return packets
                ident,_,_,x,y=struct.unpack_from('<Ihhhh',payload)
                if ident==self.scene_id:packets+=view.run('_reflect_reply',(x,y),self.clock())
                return packets
        if message==514 and len(payload)>=8:
            packets=self.arena.tick(self.clock());ident,x,y=struct.unpack_from('<Ihh',payload)
            if not self.arena.input_open(self.clock(),self):return packets
            if ident==self.scene_id:
                for view in views:
                    if view._session['tank']==10000111 and view.dash:view.dash['dest']=(x,y)
            return packets
        return super().handle(message,payload)
