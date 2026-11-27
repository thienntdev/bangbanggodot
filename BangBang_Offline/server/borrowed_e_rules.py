"""Explicit boundaries between a donor E and its independent passive kit."""
import math
from combat_math import D, quantize
from battle_runtime import TankActions


def nothing(self,*args,**kwargs):return []
def one(self,*args,**kwargs):return D(1)
def zero(self,*args,**kwargs):return 0


def energy_hit(self,target,raw,now,**kwargs):
    return self.damage(raw,now,target=target,school='energy',**kwargs)[0]


def magneto_hit(self,target,raw,now,generation,school='energy'):
    return self.damage(raw,now,target=target,school=school,source_generation=generation)[0]


def gil_hit(self,target,raw,generation,now,**kwargs):
    return self.damage(raw,now,target=target,school='energy',source_generation=generation,**kwargs)[0]


def sima_hit(self,raw,target,now,generation):
    return self.damage(raw,now,target=target,school='energy',source_generation=generation)[0]


def optimus_hit(self,target,power,now,*,basic=False,school='physical',current=True):
    return self.damage(power,now,target=target,basic=basic,school=school)[0]


def ichigo_hit(self,target,power,now):return self.damage(power,now,target=target)[0]


def dracula_hit(self,target,raw,now,generation,*,basic=False):
    return self.damage(raw,now,target=target,basic=basic,source_generation=generation)[0]


def wolf_hit(self,target,raw,now,*,own_ratio=0,space=False,basic=False,current=True,reflected=False):
    missing=self.max_hp-self.hp
    packets=self.damage(raw,now,target=target,basic=basic,reflected=reflected)[0]
    if own_ratio and target.alive:
        # This second component belongs to E itself, not Wolf's 5% passive.
        packets+=self.damage(missing*D(own_ratio),now,target=target,school='true',trigger_passive=False)[0]
    return packets


def erlang_hit(self,target,raw,power,generation,now,*,basic=False,heal=False):
    packets=self.damage(raw,now,target=target,basic=basic,source_generation=generation)[0]
    if heal and self.alive:
        packets+=self.restore_hp((self.max_hp-self.hp)*D('.075' if target.info.get('npc_template') else '.15'),now)
    return packets


def sontinh_hit(self,flight,target,now):
    key=target.id,target.generation
    if key in flight['hits'] or not target.alive:return []
    flight['hits'].add(key)
    return self.damage(flight['raw'],now,target=target,basic=True,
                       lifesteal=flight['lifesteal'] if self.alive else 0)[0]


def naruto_deal(self,target,raw,now,*,generation=None,**kwargs):
    # The fourth enhanced basic's HP component also cannot feed K's skill passive.
    kwargs['basic']=True
    return self.damage(raw,now,target=target,source_generation=generation,**kwargs)[0]


def naruto_hit(self,flight,target,now):
    distance=D(str(math.dist(self.position_at(now),target.position_at(now))))
    raw=flight['raw']*(D('.75')+min(D(1),distance/480))
    packets=self.damage(raw,now,target=target,basic=True)[0]
    if not target.alive:return packets
    key=flight['source_generation'],target.id,target.generation
    mark=self.e_hits.get(key)
    count=mark['count'] if mark and mark['end']>now else 0
    for t in (318212,318213,318214):
        if target.buff_sources.get(t)==self.id:packets+=target.remove_buff(t,now)
    if count==3:
        self.e_hits.pop(key,None)
        packets+=self.damage(target.max_hp*D('.1'),now,target=target,basic=True,school='true')[0]
        packets+=self._buff(318216,now,target.id)
    else:
        self.e_hits[key]=dict(count=count+1,end=now+1500)
        packets+=self._buff(318212+count,now,target.id)
    return packets


def shadow_deal(self,target,raw,now,generation,**kwargs):
    return self.damage(raw,now,target=target,source_generation=generation,**kwargs)


def dare_cost(self,now):
    return self.commit_hp(quantize(self.hp*D('.85')),now)


def borrowed_update(self,now):
    # These donors' update methods would install an independent passive even
    # without on_spawn. Their E timing is already in its scheduled events.
    if hasattr(self,'_visibility'):self._visibility(now)
    return self.sync_speed(now)


def assassin_visibility(self,now):
    self.info['untargetable']=self.has_buff(322202,now) and 32 not in self.buff_types(now)


def kurumi_damage(self,raw,now,**kwargs):
    if kwargs.get('basic') and self.has_buff(370207,now):raw/=2
    kwargs.setdefault('source_generation',self._session['generation'])
    return self._host.borrowed_damage(self,raw,now,**kwargs)


def night_hit(self,flight,target,now):
    packets=self.damage(flight['raw'],now,target=target,basic=True)[0]
    if flight['template']==390221:
        packets+=self._buff(390222,now,target.id)+self._buff(390223,now,target.id)
        if self.alive:packets+=self._resource(25)
    return packets


def scatter_cast(self,slot,start,dest,target_id,now):
    if slot!=0:return self._donor.cast(self,slot,start,dest,target_id,now)
    if start==dest or self.blocked('attack',now) or self.skill_sealed(0,now) or now<self.cooldowns[0]:return []
    self.cooldowns[0]=now+self.fire_interval(now)
    zoro=self._session['tank']==10000077
    packets=[]
    if zoro:
        self.scatter_count-=1
        if not self.scatter_count:packets+=self.remove_buff(351204,now)
    angle=math.atan2(dest[1]-start[1],dest[0]-start[0]);hits=set()
    for offset in (0,-15,15):
        heading=angle+math.radians(offset)
        aim=(round(start[0]+600*math.cos(heading)),round(start[1]+600*math.sin(heading)))
        packets+=self.shoot(330100,start,aim,now,self.combat_stat('iEgAtk',now),school='energy',
                           basic=True,shared_hits=hits,lifesteal=0 if zoro else D('.25'))
    return packets+[self._cooldown(0)]


def zoro_flight(self,flight,now):
    if flight['template']==330100:return TankActions._flight(self,flight,now)
    return self._donor._flight(self,flight,now)


def falcon_cast(self,slot,start,dest,target_id,now):
    if slot!=0:return self._donor.cast(self,slot,start,dest,target_id,now)
    if start==dest or self.blocked('attack',now) or self.skill_sealed(0,now) or now<self.cooldowns[0]:return []
    power=self.combat_stat('iEgAtk',now)
    self.cooldowns[0]=now+self.fire_interval(now)
    packets=self.shoot(379211,start,dest,now,power,school='energy',basic=True,
                       lifesteal=D('.5'),power=power)
    self.enhanced-=1
    if not self.enhanced:packets+=self.remove_buff(379203,now)+self.remove_buff(379204,now)
    return packets+[self._cooldown(0,True)]


def overrides(tank):
    # Only methods that add an independent donor passive are suppressed.
    # Methods implementing E's hit reward, expiry, return or recast stay native.
    disabled={
        19:('on_bullet_hit',),33:('_activity',),31:('_inspire',),35:('_ward',),
        47:('_mark',),41:('on_bullet_hit',),63:('_reward',),
        45:('_passive',),69:('_poison',),89:('_burn',),90:('_passive',),
        105:('_burn',),112:('_burn','_reward'),107:('_mark','_inspire'),
        85:('_passive',),59:('_burn',),74:('_mark',),79:('_mark',),
        49:('_passive',),58:('_curse',),71:('_proc',),86:('_stack_fire',),
        36:('_empower',),75:('_empower',),77:('_mark',),
        96:('_empower',),99:('_mark',),64:('_empower',),82:('_protection',),
        76:('_proc',),93:('_ignite',),54:('_gift',),57:('_dot',),
        83:('_grant_shield','_reveal'),30:('_poison',),60:('drop_component',),
        73:('_emergency',),104:('_precision','_reload'),
    }
    result={name:nothing for name in disabled.get(tank-10000000,())}
    custom={
        39:dict(_hit=energy_hit),65:dict(_hit=energy_hit),
        88:dict(_hit=gil_hit),98:dict(_hit=sima_hit),62:dict(_hit=optimus_hit),
        64:dict(_hit=ichigo_hit),57:dict(_hit=dracula_hit),40:dict(_hit=wolf_hit),
        87:dict(_hit=erlang_hit),51:dict(_hit=sontinh_hit,cast=scatter_cast),77:dict(cast=scatter_cast,_flight=zoro_flight),
        44:dict(_deal=naruto_deal,_basic_hit=naruto_hit,on_target_death=nothing),
        108:dict(_deal=shadow_deal,_factor=one,on_target_death=nothing),
        115:dict(_cast_cost=dare_cost),106:dict(_hit=energy_hit),
        48:dict(update=borrowed_update,_visibility=assassin_visibility),101:dict(update=borrowed_update,_activity=nothing),
        81:dict(update=borrowed_update),95:dict(damage=kurumi_damage,_refund=nothing),
        114:dict(_hit=night_hit),
        104:dict(cast=falcon_cast),97:dict(_skill_hit=magneto_hit),
    }
    result.update(custom.get(tank-10000000,{}))
    return result
