"""Map70: approved two-team escort race, damageable carts and public routes."""
from battle_participants import human
import math
import struct

from battle_runtime import TankActions
from combat_math import D
from combat_geometry import point_at
from combat_protocol import scene,move_event,stop_move
from cow_objectives import eligible

SPEEDS=(0,50,60,70,75,80)


class BombCart(TankActions):
    def __init__(self,arena,ident,definition):
        info=dict(definition,npc_template=1601,bomb_cart=True,tank_id=10000019,
                  tank_level=1,acct_id=0,name='Xe Bom',in_room=True)
        super().__init__(arena,ident,info,definition['camp'],tuple(definition['position']))
        self.stats=dict(self.stats,iHp='7500',iArmor='113',iEgArmor='113',iSpeed='20',
                        iAttack='0',iEgAtk='0',iMp='0',iCentesis='0',iEgCtsis='0')
        self.hp=self.max_hp=D(7500)
        self.info['hp']=self.info['max_hp']=7500
        self.cooldowns={};self.cart_speed=0;self.respawn_at=0
        points=[tuple(p) for p in definition['route']]
        self.route=points[:1]
        # One tween per straight section, not a new FX/move every 24px tile.
        for i,p in enumerate(points[1:-1],1):
            a,b=points[i-1],points[i+1]
            if (p[0]-a[0])*(b[1]-p[1])!=(p[1]-a[1])*(b[0]-p[0]):self.route.append(p)
        self.route.append(points[-1]);self.route_index=1
        self.route_lengths=[math.dist(a,b) for a,b in zip(self.route,self.route[1:])]
        self.herders=[];self.cart_buffs=set();self.herder_buff=0

    def snapshot(self,now):
        return 1556,struct.pack('<IIIhhiBiIiH',self.scene_id,self.id,1601,
            *self.position_at(now),math.ceil(self.hp),self.camp,7500,0,0,0)

    def on_spawn(self,now):return [self.snapshot(now)]
    def update(self,now):return []
    def sync_speed(self,now):return []
    def cast(self,*args,**kwargs):return []
    def restore_hp(self,*args,**kwargs):return []
    def add_shield(self,*args,**kwargs):return []
    def cc_immune(self,now,*,slow=False):return True
    def _set_motion(self,start,dest,speed,now,kind=0):return 0
    def move_destination(self,start,dest):return self.position_at(self.clock())
    def blink_destination(self,start,dest):return self.position_at(self.clock())
    def reject_buff(self,row,source,now):return source is not self and source.camp==self.camp

    def nearby(self,now):
        pos=self.position_at(now)
        return [a for a in self.arena.actors.values() if eligible(a,now) and math.dist(pos,a.position_at(now))<=200]

    def escorted(self,now):
        # Authoritative damage eligibility is immediate, not the last AI sample
        # or a visual buff that may have been cleansed in the same tick.
        return any(a.camp==self.camp for a in self.nearby(now))

    def sync_effects(self,herders,contested,now):
        packets=[];count=min(5,len(herders));ids={a.id for a in herders}
        buff=7000000+count*10+1 if count else 0
        for ident in self.herders:
            actor=self.arena.actors[ident]
            if ident not in ids or buff!=self.herder_buff:
                if actor.buff_sources.get(self.herder_buff)==self.id:
                    packets+=actor.remove_buff(self.herder_buff,now)
        for actor in herders:
            if not actor.has_buff(buff,now):packets+=self._buff(buff,now,actor.id,duration=-1)
        self.herders=sorted(ids);self.herder_buff=buff
        desired=({7000000+count*10+3} if count else set())
        desired|=({7000000+count*10+2,7000000+count*10+4} if count and not contested
                  else {7000056 if contested else 7000055})
        for template in self.cart_buffs-desired:packets+=self.remove_buff(template,now)
        for template in desired:
            if not self.has_buff(template,now):packets+=self._buff(template,now,duration=-1)
        self.cart_buffs=desired
        return packets

    def stop(self,now):
        self.cart_speed=0
        if not self.motion:return []
        self.position=self.position_at(now);self.motion=None
        return [stop_move(self.scene_id,self.id,self.position)]

    def advance(self,now):
        if not self.alive:return []
        if self.motion and now>=self.motion[3]:
            self.position=self.motion[1];self.motion=None;self.route_index+=1
        if self.route_index>=len(self.route):return []
        nearby=self.nearby(now);friends=[a for a in nearby if a.camp==self.camp]
        opponents=sum(a.camp!=self.camp for a in nearby)
        contested=bool(opponents and opponents>=len(friends))
        speed=SPEEDS[min(5,len(friends))] if len(friends)>opponents else 0
        packets=[]
        if speed!=self.cart_speed:packets+=self.stop(now)
        packets+=self.sync_effects(friends,contested,now)
        if not speed or self.motion:return packets
        start=self.position_at(now);dest=self.route[self.route_index]
        self.cart_speed=speed;self.motion_kind=3
        self.motion=(start,dest,now,now+max(1,round(math.dist(start,dest)*1000/speed)))
        return packets+[scene(moves=(move_event(dest,speed,3,self.id),))]

    def commit_hp(self,hp,now,*,critical=False):
        if not self.alive or hp>=self.hp:return []
        packets=super().commit_hp(hp,now,critical=critical)
        if not self.alive:
            for ident in self.herders:
                actor=self.arena.actors[ident]
                if actor.buff_sources.get(self.herder_buff)==self.id:packets+=actor.remove_buff(self.herder_buff,now)
            self.herders=[];self.herder_buff=0;self.cart_buffs=set();self.cart_speed=0
            self.route_index=1;self.position=self.spawn;self.motion=None
            packets.append(scene(removed=(struct.pack('<I',self.id),)))
        return packets

    def _respawn(self,now,generation):
        if self.alive or generation!=self.generation:return []
        self.generation+=1;self.hp=self.max_hp;self.info['hp']=7500;self.respawn_at=0
        self.position=self.spawn;self.motion=None;self.forced_until=0;self.damage_credit=None
        return self.on_spawn(now)


def progress(cart,now):
    if not cart.alive:return 0.
    if cart.route_index>=len(cart.route):return 1.
    travelled=sum(cart.route_lengths[:cart.route_index-1])+math.dist(cart.route[cart.route_index-1],cart.position_at(now))
    return round(min(1,travelled/sum(cart.route_lengths)),8)


def install(arena):
    for definition in arena.geometry.data['bomb_carts']:
        cart=BombCart(arena,arena.new_id(5),definition);arena.actors[cart.id]=cart


def tick(arena,now):
    packets=[];carts=[a for a in arena.actors.values() if a.info.get('bomb_cart')]
    for cart in carts:packets+=cart.advance(now)
    if any(progress(c,now)>=1 for c in carts):
        from pk_rules import finish
        packets+=finish(arena,now)
    return packets


def goal(arena,actor,seen,now):
    """Cart routes are public; opponent tanks come only from delayed sight."""
    carts={a.camp:a for a in arena.actors.values() if a.info.get('bomb_cart')}
    own,enemy=carts[actor.camp],carts[3-actor.camp]
    pos=own.position_at(now) if own.alive else own.spawn
    friends=[a for a in arena.actors.values() if a.camp==actor.camp and eligible(a,now)
             and (a.hp/a.max_hp>=D('.4') or a is actor)]
    volunteers=[a for a in friends if not human(a) or math.dist(a.position_at(now),pos)<=200]
    opposition=sum(not s.get('objective') and math.dist(s['pos'],pos)<=300 for s in seen)
    count=min(len(volunteers),max(1,2 if not opposition else min(3,opposition+1)))
    escorts=sorted(volunteers,key=lambda a:(math.dist(a.position_at(now),pos)-(180 if a.id in own.herders else 0),a.id))[:count]
    pushing=actor in escorts or not enemy.alive
    cart=own if pushing else enemy
    center=cart.position_at(now) if cart.alive else cart.spawn
    dest=cart.route[min(cart.route_index,len(cart.route)-1)]
    length=max(1,math.dist(center,dest));dx,dy=(dest[0]-center[0])/length,(dest[1]-center[1])/length
    team=escorts if pushing else [a for a in volunteers if a not in escorts]
    slot=team.index(actor) if actor in team else 0
    side=(-1 if slot%2==0 else 1)*(64 if slot<2 else 120)
    ahead=48 if pushing else 96
    wanted=(center[0]+dx*ahead-dy*side,center[1]+dy*ahead+dx*side)
    # A desired flank can be on a rail/wall. Pick a connected walk cell within
    # escort range so a ranged tank doesn't stop 400px away from the cart.
    from bot_ai import Navigation
    if not hasattr(arena,'navigation'):arena.navigation=Navigation(arena.geometry)
    nav=arena.navigation;source=nav.nearest(actor.position_at(now))
    if source is not None:
        connected=nav.reachable(source)
        base=tuple(round((v-12)/24)*24+12 for v in center)
        cells=[(base[0]+x*24,base[1]+y*24) for x in range(-8,9) for y in range(-8,9)]
        cells=[p for p in cells if p in connected and math.dist(p,center)<=180]
        if cells:wanted=min(cells,key=lambda p:(math.dist(p,wanted),p))
    return ('bomb_escort' if pushing else 'bomb_intercept',arena.geometry.clamp_tank_position(wanted))


def targets(actor,seen,tanks,objective):
    pos=actor.position_at(actor.clock())
    relevant=[s for s in tanks if math.dist(s['pos'],pos)<=360 or objective and math.dist(s['pos'],objective[1])<=300]
    if relevant:return relevant
    return [s for s in seen if s.get('barrier') or s.get('bomb_cart') or
            s.get('structure') and (math.dist(pos,s['pos'])<=360 or objective and math.dist(s['pos'],objective[1])<=360)]
