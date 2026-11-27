"""Run a canonical E on Kakashi's actor with a separate, persistent cast state.

The donor is never spawned and never joins the arena. Its E executor supplies
timing/geometry; health, resources and ownership remain on the real actor.
Independent donor passives are excluded explicitly in borrowed_e_rules.
"""
import struct
from functools import lru_cache

from battle_runtime import TankActions, tank_action_classes
from combat_math import D
from combat_protocol import props


SHARED = frozenset(('arena','state','clock','id','camp','scene_id','stats',
    'position','spawn','motion','motion_kind','hp','max_hp','generation','forced_until',
    'last_speed','speed_lock','last_interval','last_attack','buff_started','buff_stacks',
    'buff_versions','buff_sources','shields','athena_shield','stat_loans','mp',
    'noel_box','dora_travel','damage_credit','caocao_hostage','crystal_crits','crystal_heal_at'))
CACHES = frozenset(('skills','buffs','effects','dash_effect'))
MEMORY = {10000044:('e_hits',),10000060:('turret_marks',),10000095:('combo_count','combo_until')}


@lru_cache(maxsize=None)
def executor_class(tank):
    from borrowed_e_rules import overrides
    donor = tank_action_classes()[tank]
    return type('Borrowed'+donor.__name__, (BorrowedE, donor),
                dict(_donor=donor, **overrides(tank)))


def executor(host, serial):
    cached = host.__dict__.setdefault('_borrow_views', {})
    if serial in cached: return cached[serial]
    session = host.borrow_sessions[serial]
    cls = executor_class(session['tank'])
    view = cls.__new__(cls)
    # Construction only reads donor tables. Never mutate the player's info or
    # run on_spawn, which would install donor passives and refill resources.
    cls._donor.__init__(view, host.arena, host.id, dict(host.info), host.camp, host.spawn)
    fields = vars(view).copy()
    if 'state' not in session:
        session['state'] = {k:v for k,v in fields.items() if k not in SHARED and k not in CACHES}
        session['state']['info'] = dict(host.info)
    vars(view).clear()
    vars(view).update({k:v for k,v in fields.items() if k in CACHES})
    object.__setattr__(view, '_host', host)
    object.__setattr__(view, '_session', session)
    memory=host.borrow_memory.setdefault((session['generation'],session['tank']),{})
    for key in MEMORY.get(session['tank'],()):memory.setdefault(key,session['state'][key])
    cached[serial] = view
    return view


class BorrowedE:
    def __getattribute__(self, name):
        fields = object.__getattribute__(self, '__dict__')
        if '_host' in fields and name in SHARED:
            value = getattr(fields['_host'], name)
            # Sword God's own E consumes and scales at most 100 Chakra.
            if name=='mp' and fields['_session']['tank']==10000081: return min(100,value)
            return value
        if '_host' in fields and name in MEMORY.get(fields['_session']['tank'],()):
            s=fields['_session']
            return fields['_host'].borrow_memory[(s['generation'],s['tank'])][name]
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        session = object.__getattribute__(self, '__dict__').get('_session')
        if session is not None and name in session['state']: return session['state'][name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        fields = object.__getattribute__(self, '__dict__')
        if '_host' not in fields or name in CACHES or name.startswith('_borrow_'):
            object.__setattr__(self,name,value)
        elif name in SHARED:
            setattr(fields['_host'],name,value)
        elif name in MEMORY.get(fields['_session']['tank'],()):
            s=fields['_session']
            fields['_host'].borrow_memory[(s['generation'],s['tank'])][name]=value
        else:
            fields['_session']['state'][name] = value

    @property
    def alive(self):
        fields = vars(self)
        if '_host' not in fields: return TankActions.alive.fget(self)
        return self._host.alive and self.generation==self._session['generation']

    def native_slot(self, slot):
        packet = self._donor._cooldown(self,slot)
        return struct.unpack_from('<IBbQQ',packet[1])

    def _cooldown(self, slot, changed=False):
        # Donors may report their native charge pool. Only one chain is lent.
        return (-slot-1, bool(changed))

    def _queue(self,due,kind,*data):
        if data and isinstance(data[0],dict):
            data[0].setdefault('kakashi_pen',getattr(self,'_borrow_pen',self._session.get('pen',D(0))))
            data[0].setdefault('kakashi_multiplier',self._host.damage_bonus(self._host.enemy))
        return super()._queue(due,kind,*data)

    def _resource(self, amount, *args):
        if not self.alive:return []
        if self._session['tank']==10000033 and amount>0:return []
        if self._session['tank']==10000081 and amount==-100: amount=-min(100,self._host.mp)
        return self._host._resource(amount)

    def damage(self, raw, now, **kwargs):
        kwargs.setdefault('source_generation',self._session['generation'])
        if not self.alive or self._session['tank'] in (10000033,10000074):kwargs['lifesteal']=0
        target=kwargs.get('target') or self.enemy
        key=target.id,target.generation
        credited=vars(self).get('_borrow_hits',set())
        if key in credited:kwargs['trigger_passive']=False
        result=self._host.borrowed_damage(self,raw,now,**kwargs)
        if result[1] and not kwargs.get('basic') and not kwargs.get('reflected'):credited.add(key)
        return result

    def add_shield(self, template, amount, now, **kwargs):
        if self._session['tank']==10000109 and template==384111:return []
        return super().add_shield(template,amount,now,**kwargs)

    def restore_hp(self, amount, now):
        return self._host.restore_hp(amount,now) if self.alive else []

    def commit_hp(self, hp, now, *, critical=False):
        return self._host.commit_hp(hp,now,critical=critical) if self.alive else []

    def combat_stat(self, key, now):return self._host.combat_stat(key,now)
    def attr_bonus(self, attributes, now):return self._host.attr_bonus(attributes,now)
    def fire_interval(self, now):return self._host.fire_interval(now)
    def damage_bonus(self, target):return self._host.damage_bonus(target)
    def reject_buff(self, row, source, now):
        if self._session['tank']==10000083:return False  # Strange's silence immunity is passive.
        return self._donor.reject_buff(self,row,source,now)

    def remove_buff(self, template, now, *, expired=False):
        owner=self._host.borrow_buff_owners.get(template)
        if owner is not None and owner>self._session['serial']:return []
        self._host.borrow_buff_owners.pop(template,None)
        return self._donor.remove_buff(self,template,now,expired=expired)

    def _buff(self, template, now, owner=None, **kwargs):
        if self._session['tank']==10000072 and template in (346131,346132):return []
        packets=TankActions._buff(self,template,now,owner,**kwargs)
        if packets and (owner is None or owner==self.id):
            self._host.borrow_buff_owners[template]=self._session['serial']
        return packets
    def sync_speed(self, now):
        return self._host.sync_speed(now) if '_host' in vars(self) else []

    def _event(self, now, kind, data):
        if vars(self).get('_borrow_running'):return self._donor._event(self,now,kind,data)
        return self.run('_event',now,kind,data)

    def run(self, method, *args, **kwargs):
        """Invoke a donor operation, forwarding refunds without replacing K's CD."""
        index={'cast':-1,'on_skill_damage':-1,'on_control':-1,'on_target_death':-1,
               'on_damage':2,'remove_buff':1,'_reflect_reply':1}.get(method,0)
        now=args[index] if args else self.clock()
        state = self._session['state']
        cds = state['cooldowns']
        first = method=='cast' and args[0]==1 and not self._session['used']
        before = dict(self._host.cooldowns)
        gate=cds[1]
        refunding=method not in ('cast','update','interrupt','remove_buff')
        for slot in (0,2,10):cds[slot]=before[slot]
        if not first:
            if refunding:cds[1]=before[1]
        else:
            cds[1]=0
        charge = 'e_next_charge' in state
        old_charge=state.get('e_next_charge',0)
        if charge and (refunding or first):state['e_next_charge']=before[1] if not first else 0
        actors = set(self.arena.actors)
        if method=='cast':
            self._session['pen']=D('.25') if self.has_buff(305201,now) else D(0)
            self._session['multiplier']=self._host.damage_bonus(self._host.enemy)
        context=args[2][0] if method=='_event' and args[2] and isinstance(args[2][0],dict) else {}
        self._borrow_pen=context.get('kakashi_pen',self._session.get('pen',D(0)))
        self._borrow_multiplier=context.get('kakashi_multiplier',self._session.get('multiplier',D(1)))
        self._borrow_hits=set()
        self._borrow_running=True
        try:
            packets = getattr(type(self),method)(self,*args,**kwargs) if method!='_event' else self._donor._event(self,*args)
        finally:self._borrow_running=False
        if method=='cast' and packets:
            if args[0]==0:self._host.cooldowns[0]=cds[0]
            elif args[0]==1:
                self._session['used']=True
                self._session['used_at']=now
        for slot in (1,2,10):
            if not self.alive:continue
            if slot==1 and (not refunding or self._session['tank']-10000000 not in (8,31,36,44,58,63,76,82,86,105,112)):continue
            end = state['e_next_charge'] if slot==1 and charge else cds[slot]
            if 0<=end<before[slot]:
                scale={31:1.25,58:1.25,86:10/6,44:2}.get(self._session['tank']-10000000,1) if slot==1 else 1
                self._host.cooldowns[slot]=max(now,before[slot]-round((before[slot]-end)*scale))
        if refunding:
            cds[1]=gate
            if charge:state['e_next_charge']=old_charge
        for ident in set(self.arena.actors)-actors:
            actor=self.arena.actors[ident]
            if actor.info.get('owner')==self.id:actor.info['borrow_session']=self._session['serial']
        packets=self._host._borrow_finished(self,now,packets)
        return [self._host._cooldown(-code-1,body) if code<0 else (code,body) for code,body in packets]

    def update_borrowed(self, now):
        return self.run('update',now)


def owner_executor(arena, info):
    owner=arena.actors.get(info['owner'])
    serial=info.get('borrow_session')
    return executor(owner,serial) if owner and serial is not None else owner
