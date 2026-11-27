"""Native destructible map objects. They never count as tank kills or respawn."""
import math
import struct
from copy import deepcopy

from battle_runtime import TankActions
from combat_data import table_row
from combat_math import D,quantize
from combat_geometry import rect_contact
from combat_protocol import scene


# Ordinary destructible scenery only. Script gates/decorations and special
# boxes keep their original rules, even where their legacy type is also 1.
ORDINARY_TEMPLATES = frozenset((*range(2000,2042),*range(3004,3010),5030,5031,9003))
PICKUPS = (105,106,412,413,414,417,418)


def missile_target_present(target,now):
    """An acquired target may hide, but cannot leave the battlefield."""
    if not target.alive or target.in_stasis():return False
    if getattr(target,'vanish',None) or getattr(target,'attach',None):return False
    form=getattr(target,'form',None)
    if isinstance(form,dict) and form.get('phase')=='gathering':return False
    # Vanish kits mark both flags; stealth kits only mark untargetable.
    if target.info.get('untargetable') and target.info.get('damage_immune'):return False
    if target.is_untargetable() and 26 not in target.buff_types(now):return False
    if hasattr(target,'borrowed_views'):
        return all(missile_target_present(v,now) for v in target.borrowed_views())
    return True


class MapObject(TankActions):
    def __init__(self,arena,definition):
        row=table_row('NpcTemplate_table.xml',nTemplateId=definition['template'])
        ident=(3<<26)|definition['instance']
        info=dict(map_object=True,npc_template=definition['template'],tank_id=10000019,
                  tank_level=1,acct_id=0,name=row['szName'],in_room=True)
        super().__init__(arena,ident,info,definition['camp'],(definition['x'],definition['y']))
        self.stats=dict(self.stats,iHp=str(definition['hp']),iArmor=row.get('iBdArmor') or '0',
                        iEgArmor='0',iAttack='0',iEgAtk='0',iCentesis='0',iEgCtsis='0',iSpeed='0',iMp='0')
        self.hp=self.max_hp=D(definition['hp'])
        self.info['hp']=self.info['max_hp']=int(self.hp)
        x,y=self.position;w,h=int(row.get('iWidth') or 0),int(row.get('iHeight') or 0)
        self.map_rect=(x-w/2,y-h/2,x+w/2,y+h/2)
        self.info['base']=bool(definition.get('base'))
        self.skill_damage_multiplier=definition.get('skill_damage_multiplier',1)
        self.repair_box=int(row['iType'])==6
        self.repair=None
        self.cooldowns={}
        self.explosion=definition.get('explosion')
        self.script_removes=definition.get('removes',[])
        self.spider_nest=definition.get('spider_nest')
        # Do not add false fields to old PvP checkpoint graphs.
        if definition.get('pve_gate'):self.pve_gate=True
        if definition.get('pve_ambush'):self.pve_ambush=True
        from pve_bomb_puzzles import protected
        if protected(arena,definition):self.pve_bomb_only=True
        self.ordinary_obstacle=(int(row['iType'])==1 and definition['template'] in ORDINARY_TEMPLATES
                                and not self.explosion and not self.spider_nest and not self.info['base'])
        if self.ordinary_obstacle:
            # Neutral combat targets let existing bullet/area selectors for
            # every tank hit scenery from either side, without friendly fire.
            self.camp=0
        self.unlocked_by=tuple((3<<26)|n['instance'] for n in arena.geometry.data['npcs']
                              if definition['instance'] in n.get('unlocks',()))
        if int(row['iType'])==4:
            self.info['map_turret']=True
            self.stats.update(iAttack=row['iAttack'],iEgAtk=row['iEgAtk'],iCentesis='0',iEgCtsis='0',
                              iFireInterv=row['nInterval'],nFireRange=row['iAlertRange'])
            self.turret_skill=int(row['nPropsId'])
            self.turret_next_shot_at=0
            self.turret_target=None
            self.turret_hits=0
            self.turret_shot_serial=0
        # Static map actors are reconstructed from the map on load. Save every
        # change, including fields added by skills, without repeating defaults
        # for a hundred idle obstacles on every durable checkpoint.
        from battle_persistence import STATIC
        self._checkpoint_defaults={k:deepcopy(v) for k,v in vars(self).items() if k not in STATIC}

    def snapshot(self,now):
        body=struct.pack('<IIhhiBiIiH',self.id,self.info['npc_template'],*self.position,
                         math.ceil(self.hp),self.camp,math.ceil(self.max_hp),0,0,0)
        return 1556,struct.pack('<I',self.scene_id)+body

    def sync_speed(self,now):return []
    def reject_buff(self,row,source,now):
        return not (self.repair_box and source is self and int(row['nBuffId'])==40001)
    def cc_immune(self,now,*,slow=False):return True
    def _set_motion(self,start,dest,speed,now,kind=0):
        self.motion=(self.spawn,self.spawn,now,now+1)
        return 1
    def move_destination(self,start,dest):return self.spawn
    def restore_hp(self,amount,now):return []
    def add_shield(self,template,amount,now,**kwargs):return []
    def update(self,now):return []

    def turret_locked(self):
        return any(self.arena.actors[i].alive for i in self.unlocked_by if i in self.arena.actors)

    def damage_immune(self,school,now,periodic=False):
        return (getattr(self,'pve_gate',False) or getattr(self,'pve_bomb_only',False)
                or self.turret_locked() or super().damage_immune(school,now,periodic))

    def commit_hp(self,hp,now,*,critical=False):
        if not self.alive or self.arena.pk['finished']:return []
        if hp<self.hp and (getattr(self,'pve_gate',False) or getattr(self,'pve_bomb_only',False)
                           or self.turret_locked()):return []
        if self.ordinary_obstacle and hp<self.hp:
            # Also cover direct HP-loss skills. Script dismantling deliberately
            # sets hp directly and must not roll extra loot or require hits.
            hp=max(D(0),self.hp-self.max_hp/4)
        before=self.hp;self.hp=max(D(0),quantize(hp));self.info['hp']=math.ceil(self.hp)
        from pk_rules import record_structure_hp
        record_structure_hp(self.arena,self,before)
        delta=math.ceil(self.hp)-math.ceil(before)
        credit=getattr(self,'damage_credit',None)
        fury=int(bool(critical) and delta<0)
        packets=[(1605,struct.pack('<HIiBI',1,self.id,delta,fury,credit[0] if credit else self.id)),self._hp_packet(self.id,self.hp)]
        if not self.alive:
            from battle_levels import reward_death
            packets+=reward_death(self,now)
            if self.info.get('base'):
                from pk_rules import finish
                return packets+finish(self.arena,now)
            packets.append(scene(removed=(struct.pack('<I',self.id),)))
            packets+=self.cancel_repair(now)
            # Authored Maya REMOVE_NPC is dismantling, not another destruction:
            # no extra damage, item roll or score from those linked blocks.
            for instance in self.script_removes:
                obj=self.arena.actors.get((3<<26)|instance)
                if obj and obj.alive:
                    obj.hp=D(0);obj.info['hp']=0
                    packets.append(scene(removed=(struct.pack('<I',obj.id),)))
            rebuild_geometry(self.arena)
            packets+=drop_item(self.arena,self.position)
            packets+=self.explode(now,credit)
            if self.spider_nest and not self.arena.pk['finished']:
                from maya_map import open_nest
                packets+=open_nest(self.arena,self.spider_nest,now)
            if getattr(self,'pve_ambush',False) and not self.arena.pk['finished']:
                from pve_rules import ambush
                packets+=ambush(self.arena,now)
            from pve_catalog import CHAPTER2, CHAPTER3, CHAPTER4, CHAPTER5, CHAPTER6, CHAPTER7, CHAPTER8, CHAPTER9
            if self.arena.geometry.id in CHAPTER2+CHAPTER3+CHAPTER4+CHAPTER5+CHAPTER6+CHAPTER7+CHAPTER8+CHAPTER9 and not self.arena.pk['finished']:
                from pve_rules import chapter
                packets+=chapter(self.arena).object_destroyed(self.arena,self,now)
        return packets

    def explode(self,now,credit):
        if not self.explosion:return []
        packets=[];targets=[]
        # Freeze contacts before this blast damages objects: a still-standing
        # obstacle shields the tank behind it, even if that obstacle is destroyed
        # by this blast. Any resulting second explosion gets its own contacts.
        for target in list(self.arena.actors.values()):
            if target is self or not target.alive or not target.is_area_targetable():continue
            dest=target.position_at(now)
            if math.dist(self.position,dest)>self.explosion['radius']:continue
            exclude=(target.map_rect,) if target.info.get('map_object') else ()
            if self.arena.geometry.wall_contact(self.position,dest,exclude=exclude) is not None:continue
            if rect_contact(self.position,dest,self.arena.water_rects(now)) is not None:continue
            targets.append(target)
        owner=self.arena.actors.get(credit[0]) if credit else None
        for target in sorted(targets,key=lambda a:a.id):
            # The map object is the damage source (no tank's penetration,
            # lifesteal or attack passive). Only attribution follows the breaker.
            award=credit if owner and (target.info.get('map_object') or owner.camp!=target.camp) else (self.id,self.generation)
            packets+=self.damage(D(self.explosion['damage']),now,target=target,school='physical',
                                 credit_override=award,allow_friendly=True)[0]
        return packets

    def cancel_repair(self,now):
        cast=self.repair;self.repair=None
        target=self.arena.actors.get(cast['target']) if cast else None
        packets=self.remove_buff(40001,now)
        if target and target.generation==cast['generation']:packets+=target.remove_buff(10,now)
        return packets

    def start_repair(self,target,now):
        cast=self.repair=dict(target=target.id,generation=target.generation,begin=now,end=now+5000,
                              amount=target.max_hp*D('.04'))
        target.repair_ready_at=now+15000
        packets=(self._buff(40001,now,duration=5000)+self._buff(10,now,target.id,duration=5000)
                 +self._buff(11,now,target.id,duration=15000))
        for count in range(1,6):self._queue(now+count*1000,'map_repair',cast,count)
        return packets

    def _event(self,now,kind,data):
        if kind=='turret_shot_result':
            shot,=data
            if self.alive and shot['serial']==self.turret_shot_serial and not shot['hit']:
                # A missile may still be chasing beyond its original 480ms.
                # Interception/water removes its flight; only then is it a miss.
                if any(cb.__self__ is self and args and args[0]=='flight'
                       and args[1][0].get('target') and args[1][0].get('template')==301
                       and args[1][0].get('context') is shot for _,_,cb,args in self.arena.pending):
                    self._queue(now+480,'turret_shot_result',shot)
                    return []
                self.turret_hits=0
            return []
        if kind!='map_repair':return super()._event(now,kind,data)
        cast,count=data
        if self.repair is not cast:return []
        target=self.arena.actors.get(cast['target'])
        if not self.alive or not target or not target.alive or target.generation!=cast['generation']:
            return self.cancel_repair(now)
        packets=target.restore_hp(cast['amount'],now)
        if count==5:packets+=self.cancel_repair(now)
        return packets

    def fire_turret(self,now):
        if not self.alive or now<self.turret_next_shot_at:return []
        candidates=[]
        for target in self.arena.actors.values():
            if (target.camp not in (1,2) or target.camp==self.camp or target.info.get('map_object')
                    or not target.alive or target.is_untargetable()):continue
            types=target.buff_types(now)
            if 26 in types and 32 not in types:continue
            if self.arena.geometry.id==1:
                from maya_map import visible_from
                scouts=[self]+[a for a in self.arena.actors.values() if a.alive and a.camp==self.camp and not a.info.get('npc_template')]
                if not any(visible_from(self.arena,a,target,now) for a in scouts):continue
            dest=target.position_at(now);distance=math.dist(self.position,dest)
            if not 0<distance<=int(self.stats['nFireRange']):continue
            if rect_contact(self.position,dest,self.arena.water_rects(now)) is not None:continue
            candidates.append((distance,target.id,target,dest))
        if not candidates:return []
        _,_,target,dest=min(candidates,key=lambda x:x[:2])
        key=(target.id,target.generation)
        if self.turret_target!=key:self.turret_target=key;self.turret_hits=0
        self.turret_next_shot_at=now+int(self.stats['iFireInterv'])
        self.turret_shot_serial+=1
        shot=dict(serial=self.turret_shot_serial,hit=False)
        raw=D(self.stats['iAttack'])*(D('1.2') if self.turret_hits>=5 else D(1))
        packets=self.shoot(self.turret_skill,self.position,dest,now,raw,school='physical',basic=True,context=shot,
                           through_walls=True,target=target if self.turret_skill==301 else None)
        lifetime=int(table_row('SkillTemplate_table.xml',nId=self.turret_skill)['iLifeTime'])
        self._queue(now+lifetime,'turret_shot_result',shot)
        return packets

    def projectile_targetable(self,flight,target,now):
        if not self.info.get('map_turret'):return super().projectile_targetable(flight,target,now)
        if target.info.get('map_object'):return False
        if flight.get('target') and flight.get('template')==301:
            return missile_target_present(target,now)
        return super().projectile_targetable(flight,target,now)

    def _flight(self,flight,now):
        if self.info.get('map_turret') and flight.get('target') and flight.get('template')==301:
            target=self.arena.actors.get(flight['target'])
            if (target is None or target.generation!=flight['target_generation']
                    or not missile_target_present(target,now)):
                return [scene(expired_bullets=(struct.pack('<I',flight['id']),))]
            # Keep the native speed/path updates; range only limits acquisition.
            flight['finish']=now+480
        return super()._flight(flight,now)

    def on_bullet_hit(self,flight,target,now):
        shot=flight.get('context')
        if not self.info.get('map_turret') or not shot:return []
        shot['hit']=True
        if self.alive and shot['serial']==self.turret_shot_serial:
            key=(target.id,target.generation)
            if self.turret_target!=key:self.turret_target=key;self.turret_hits=0
            self.turret_hits=min(5,self.turret_hits+1)
        return []


def install(arena):
    for definition in arena.geometry.data['npcs']:
        if definition['hp']>0 and not definition.get('script_only'):
            obj=MapObject(arena,definition)
            arena.actors[obj.id]=obj


def item_packet(arena,item):
    return 1556,struct.pack('<IIIhhiBiIiH',arena.scene_id,item['id'],item['template'],*item['pos'],1,0,1,0,0,0)


def air_drop_tick(arena,now):
    """Approved map1/map4: one public drop every minute, saved with the arena."""
    if arena.pk['finished'] or now<arena.pk['air_drop_due_at']:return []
    item=dict(id=arena.new_id(4),template=arena.rng.choice(PICKUPS+(30110,) if arena.geometry.id in (12,14,50,169) else PICKUPS),
              pos=tuple(arena.rng.choice(arena.geometry.data['air_drops'])))
    arena.pk.setdefault('drops',{})[item['id']]=item
    arena.pk['air_drop_due_at']+=60000
    return [item_packet(arena,item)]


def drop_item(arena,pos):
    draw=arena.rng.random()
    if draw>=.3:return []
    template=PICKUPS[min(len(PICKUPS)-1,int(draw/.3*len(PICKUPS)))]
    item=dict(id=arena.new_id(4),template=template,pos=pos)
    arena.pk.setdefault('drops',{})[item['id']]=item
    return [item_packet(arena,item)]


def tick(arena,now):
    packets=[]
    tanks=[a for a in arena.actors.values() if a.alive and not a.info.get('npc_template') and not a.in_stasis()]
    for box in arena.actors.values():
        if box.info.get('map_turret'):packets+=box.fire_turret(now)
        if not box.info.get('map_object') or not box.repair_box or not box.alive:continue
        if box.repair:
            target=arena.actors.get(box.repair['target'])
            if not target or not target.alive or target.generation!=box.repair['generation']:
                packets+=box.cancel_repair(now)
            else:continue
        for tank in sorted(tanks,key=lambda a:a.id):
            pos=tank.position_at(now)
            if (box.camp in (0,tank.camp) and tank.hp<tank.max_hp and now>=getattr(tank,'repair_ready_at',0)
                    and repair_contact(arena,box,pos,now)):
                packets+=box.start_repair(tank,now);break
    for ident,item in list(arena.pk.setdefault('drops',{}).items()):
        for tank in sorted(tanks,key=lambda a:a.id):
            if math.dist(tank.position_at(now),item['pos'])>48:continue
            if item['template']==30110:
                if tank.info.get('battle_level',1)>=20:continue
                from battle_levels import grant
                packets+=grant(tank,150,now,item['pos'])
            elif item['template']==412:
                if tank.hp>=tank.max_hp:continue
                packets+=tank.restore_hp(tank.max_hp*D('.1'),now)
            elif item['template']==413:
                packets+=tank._buff(30101,now,duration=-1)
                if tank.has_buff(30101,now):tank.map_shield_hits=3
            elif item['template']==414:
                for buff in (30102,30108,30109):packets+=tank._buff(buff,now,duration=-1)
            elif item['template']==417:
                packets+=tank._buff(30105,now,duration=10000)
            elif item['template']==418:
                packets+=tank._buff(30106,now,duration=30000)
            elif item['template'] in (105,106):
                for buff in (203,204):packets+=tank.remove_buff(buff,now)
                tank.map_ammo=dict(template=item['template'],remaining=15)
                packets+=tank._buff(203 if item['template']==105 else 204,now,duration=-1)
            else:
                continue
            del arena.pk['drops'][ident]
            packets.append(scene(removed=(struct.pack('<I',ident),)))
            break
    return packets


def repair_contact(arena,box,pos,now):
    # Native walking rejects a whole 24-unit step. A tank can stop just short
    # of the exact edge after a dash or a diagonal approach.
    if rect_contact(pos,pos,(box.map_rect,),60-.001) is None:return False
    contact=rect_contact(pos,box.position,(box.map_rect,),36)
    end=tuple(a+(b-a)*max(0,(contact or 0)-.0001) for a,b in zip(pos,box.position))
    # Check the gap, stopping before this box itself. No healing through
    # another obstacle or water wall, even within the one-step allowance.
    return arena.geometry.wall_contact(pos,end,35.999) is None and rect_contact(pos,end,arena.water_rects(now),35.999) is None


def enhance_shot(actor,flight,now):
    ammo=getattr(actor,'map_ammo',None)
    if not ammo or not actor.alive or actor.info.get('npc_template'):return []
    if (not flight['basic'] or flight['proc'] or flight['reflected']
            or flight['target'] is not None or flight['hits']):return []
    base=table_row('TankBaseTemplate_table.xml',nTankId=actor.info['tank_id'])
    if flight['template']!=int(base['nBullet']):return []
    if flight['template']==386100:return [] # Tsubasa's native bouncing attack.
    # Native replacement, scatter and burst attacks keep their own rules.
    for template in actor.buff_started:
        if template in (203,204) or not actor.has_buff(template,now):continue
        if int(table_row('BuffTemplate_table.xml',nBuffId=template)['nEffectType']) in (24,25,52):return []
    if getattr(actor,'map_ammo_shot',None)==flight['attack_key']:return []
    actor.map_ammo_shot=flight['attack_key']
    ammo['remaining']-=1
    packets=[]
    for i in (1,2):
        extra=dict(flight,id=actor._new_id(2),hits=set(),source_generation=actor.generation)
        if ammo['template']==105:
            angle=math.atan2(flight['end'][1]-flight['start'][1],flight['end'][0]-flight['start'][0])+math.radians(-15 if i==1 else 15)
            length=math.dist(flight['start'],flight['end'])
            extra['end']=tuple(round(v) for v in (flight['start'][0]+length*math.cos(angle),flight['start'][1]+length*math.sin(angle)))
            packets+=launch_extra(actor,extra,now)
        else:
            actor._queue(now+i*100,'map_ammo_shot',extra)
    if ammo['remaining']==0:
        actor.map_ammo=None
        packets+=actor.remove_buff(203 if ammo['template']==105 else 204,now)
    return packets


def launch_extra(actor,flight,now):
    if not actor.alive or actor.generation!=flight['source_generation']:return []
    duration=flight['finish']-flight['begin']
    direction=tuple(z-a for a,z in zip(flight['start'],flight['end']))
    start=actor.position_at(now)
    flight.update(start=start,pos=start,end=tuple(a+d for a,d in zip(start,direction)),begin=now,previous=now,finish=now+duration)
    actor._queue(now+min(20,duration),'flight',flight)
    return [scene(fires=(struct.pack('<IIhhhhhI',flight['id'],actor.id,*start,*flight['end'],flight['speed'],flight['template']),))]


def rebuild_geometry(arena):
    removed=[a.map_rect for a in arena.actors.values() if a.info.get('map_object') and not a.alive]
    opened=(arena.pk or {}).get('pve',{}).get('open_doors',())
    removed.extend(tuple(r['rect']) for r in arena.geometry.data.get('pve_barriers',()) if r['point'] in opened)
    arena.geometry.remove_objects(removed)
    if hasattr(arena,'navigation'):
        if arena.geometry.id in (14,19,70):
            arena.navigation.remove_obstacles(removed)
        else:
            arena.navigation.clear.cache_clear()
            arena.navigation.components.clear()
            arena.navigation._nearest_cached.cache_clear()
        if hasattr(arena.navigation,'portal_route'):arena.navigation.portal_route.cache_clear()
    for brain in arena.bot_brains.values():brain['repath_at']=0;brain['path']=[]
