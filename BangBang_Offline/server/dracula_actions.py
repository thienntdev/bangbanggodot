"""Dracula keeps damage, healing, stat loans and HP-ratio changes separate."""
import math
import struct

from battle_runtime import TankActions
from combat_data import table_row
from combat_math import D,quantize
from combat_protocol import props,scene
from melee_common import enemies,prepare_displacement

SLOTS={0:332100,1:332201,2:332301,10:332401}


class DraculaActions(TankActions):
    def __init__(self,*args):
        super().__init__(*args)
        self.ready=self.bat=self.link=self.regen=None
        self.dots={}

    def _cooldown(self,slot,changed=False):
        skill=332221 if slot==1 and self.bat else SLOTS[slot]
        end=self.bat['begin']+500 if slot==1 and self.bat else self.cooldowns[slot]
        body=props(skill,slot,-1,end)
        return (1579,body) if changed and self.id==1 else (1572,body+struct.pack('<I',self.id))

    def on_spawn(self,now):
        self.ready=self.bat=self.link=self.regen=None
        packets=[self._cooldown(1,True)]
        for template in (332101,332102,332103):packets.extend(self._buff(template,now))
        return packets

    def _speed(self,now):return 0 if self.ready else super()._speed(now)
    def blocked(self,action,now):return bool(self.ready) or super().blocked(action,now)

    def _dot(self,target,now):
        if self.arena.pk and self.arena.pk['finished']:return []
        packets=self._buff(332111,now,target.id)+self._buff(332112,now)
        if self.regen and self.regen['generation']==self.generation and self.regen['end']>now:self.regen['end']=now+3000
        else:
            self.regen=dict(end=now+3000,generation=self.generation)
            self._queue(now+1000,'dracula_regen',self.regen)
        if not target.alive or not target.has_buff(332111,now):return packets
        key=(target.id,target.generation,self.generation)
        mark=self.dots.get(key)
        if mark and mark['end']>now and mark['version']==target.buff_versions[332111]-1:
            mark.update(end=now+3000,version=target.buff_versions[332111])
        else:
            mark=dict(target=target.id,target_generation=target.generation,generation=self.generation,
                      end=now+3000,version=target.buff_versions[332111])
            self.dots[key]=mark;self._queue(now+1000,'dracula_dot',mark)
        return packets

    def _hit(self,target,raw,now,generation,*,basic=False):
        current=self.alive and self.generation==generation
        vampire=D('.25')+1-self.hp/self.max_hp if current and not basic else D(0)
        packets,lost=self.damage(raw,now,target=target,school='physical',basic=basic,lifesteal=vampire)
        if current and lost:packets.extend(self._dot(target,now))
        return packets

    def _end_bat(self,now,burst=True):
        cast=self.bat
        if not cast:return []
        self.bat=None;packets=[]
        for template in range(332202,332211):packets.extend(self.remove_buff(template,now))
        if self.alive and cast['generation']==self.generation:
            packets.extend(self._buff(332221,now))
            if burst:
                for target in enemies(self,area=True):
                    if math.dist(self.position_at(now),target.position_at(now))<=120:
                        packets.extend(self._hit(target,cast['power']*D('.95'),now,cast['generation']))
        return packets+[self._cooldown(1,True)]+self.sync_speed(now)

    def _loan(self,link,target,now):
        key=('dracula',self.id,link['token'])
        values=link.get('values')
        if values is None:
            values={k:max(D(0),target.combat_stat(k,now))*D('.1') for k in ('iAttack','iArmor')}
        grants=((332413,self),(332415,self),(332414,target),(332416,target))
        before={template:actor.buff_versions.get(template) for template,actor in grants}
        packets=[]
        for template,actor in grants:
            packets.extend(self._buff(template,now,actor.id))
        versions={template:actor.buff_versions.get(template) for template,actor in grants}
        # Borrowing is bilateral: a counter or stasis may reject either side.
        # Commit neither stat loan until all four native grants succeeded, and
        # remove partial grants through the link's normal cancellation path.
        if any(versions[t]==before[t] or not a.has_buff(t,now) or a.buff_sources.get(t)!=self.id for t,a in grants):
            return packets+self._end_link(now,True)
        link['values']=values;link['versions']=versions;end=now+1500
        self.stat_loans[key]=dict(values=values,end=end,armor_buff=332415,attack_buff=332413)
        target.stat_loans[key]=dict(values={k:-v for k,v in values.items()},end=end,armor_buff=332416,attack_buff=332414)
        return packets

    def _end_link(self,now,immediate=False):
        link=self.link
        if not link:return []
        self.link=None;self.cooldowns[10]=now+self.skill_cooldown(6000, 10)
        packets=(self.remove_buff(332401,now) if self.buff_sources.get(332401)==self.id else [])
        packets+=self.remove_buff(332402,now)+[self._cooldown(10)]
        target=self.arena.actors.get(link['target'])
        if target and target.buff_sources.get(332401)==self.id:
            packets.extend(target.remove_buff(332401,now))
        key=('dracula',self.id,link['token'])
        for actor,templates in ((self,(332413,332415)),(target,(332414,332416))):
            if not actor:continue
            if immediate:
                actor.stat_loans.pop(key,None)
                for template in templates:
                    if actor.buff_sources.get(template)==self.id:
                        packets.extend(actor.remove_buff(template,now))
            elif key in actor.stat_loans:
                actor.stat_loans[key]['end']=now+1500
                for template in templates:
                    if actor.buff_sources.get(template)==self.id:
                        packets.extend(self._buff(template,now,actor.id,duration=1500))
        return packets

    def clear_loans(self,target,now):
        keys={k for k in target.stat_loans if k[:2]==('dracula',self.id)}
        packets=[]
        for actor in self.arena.actors.values():
            for key in keys:
                loan=actor.stat_loans.pop(key,None)
                if loan:
                    for template in (loan['armor_buff'],loan['attack_buff']):packets.extend(actor.remove_buff(template,now))
        return packets

    def _unlock(self,cast,now):
        packets=[]
        for ident in (self.id,cast['target']):
            actor=self.arena.actors.get(ident)
            if actor and getattr(actor,'dracula_ritual',None) is cast:
                actor.dracula_ritual=None
                for template in (332311,332312,332313):packets.extend(actor.remove_buff(template,now))
                packets.extend(actor.sync_speed(now))
        return packets

    def interrupt(self,now):
        packets=[]
        if self.ready:
            cast=self.ready;self.ready=None;self.cooldowns[2]=now+self.skill_cooldown(6000, 2)
            packets.extend(self._unlock(cast,now)+[(1583,struct.pack('<II',self.id,332301)),self._cooldown(2)])
        if not self.alive:packets.extend(self._end_link(now,True)+self._end_bat(now,False))
        return packets+self.sync_speed(now)

    def on_control(self,source,template,now):
        row=table_row('BuffTemplate_table.xml',nBuffId=template);mask=int(row.get('fEffectValB',0))
        return self.interrupt(now) if self.ready and row['nEffectType'] in ('35','66') and (not mask or mask&4) else []

    def on_target_death(self,target,now):
        packets=self.clear_loans(target,now)
        if self.link and self.link['target']==target.id:packets.extend(self._end_link(now,True))
        if self.ready and self.ready['target']==target.id:packets.extend(self.interrupt(now))
        return packets

    def update(self,now):
        # The ritual's own input lock is not an external silence.
        return super().update(now)

    def _flight(self,flight,now):
        # The base homing executor owns collision/defenses, while this hook
        # supplies the pre-hit HP-based spell-vamp and native DOT trigger.
        if flight['template']==332211:
            flight['lifesteal']=D('.25')+1-self.hp/self.max_hp if self.alive and self.generation==flight['source_generation'] else 0
        return super()._flight(flight,now)

    def on_bullet_hit(self,flight,target,now):
        # Base executor reports contact; compare the HP snapshot from damage.
        if self.alive and self.generation==flight['source_generation'] and getattr(self,'last_hp_loss',False):return self._dot(target,now)
        return []

    def damage(self,*args,**kwargs):
        packets,lost=super().damage(*args,**kwargs)
        self.last_hp_loss=lost
        return packets,lost

    def _event(self,now,kind,data):
        if kind=='dracula_dot':
            mark,=data;target=self.arena.actors.get(mark['target'])
            if not target or not target.alive or target.generation!=mark['target_generation'] or target.buff_versions.get(332111)!=mark['version'] or now>mark['end']:return []
            packets=self.damage(target.max_hp*D('.01'),now,target=target,school='true',periodic=True,crystal_vamp=False)[0]
            if now+1000<=mark['end']:self._queue(now+1000,kind,mark)
            return packets
        if kind=='dracula_regen':
            cast,=data
            if self.regen is not cast or not self.alive or self.generation!=cast['generation'] or now>cast['end']:return []
            packets=self.restore_hp(self.max_hp*D('.01'),now)
            if now+1000<=cast['end']:self._queue(now+1000,kind,cast)
            return packets
        if kind=='dracula_bat':
            cast,index=data
            if self.bat is not cast or not self.alive or self.generation!=cast['generation']:return []
            start=self.position_at(now)
            from bot_ai import team_visible
            targets=[t for t in enemies(self) if math.dist(start,t.position_at(now))<=360 and team_visible(self.arena,self,t,now)]
            packets=[]
            if targets:
                target=min(targets,key=lambda t:(math.dist(start,t.position_at(now)),t.id))
                packets.extend(self.shoot(332211,start,target.position_at(now),now,cast['power']*D('.66'),school='physical',target=target,through_walls=True))
            if index==6:packets.extend(self._end_bat(now))
            else:self._queue(now+500,kind,cast,index+1)
            return packets
        if kind=='dracula_link':
            link,=data
            if self.link is not link:return []
            target=self.arena.actors.get(link['target'])
            if not self.alive or self.generation!=link['generation'] or self.in_stasis() or not target or not target.alive or target.generation!=link['target_generation']:return self._end_link(now,True)
            if 'versions' in link and any(a.buff_versions.get(t)!=link['versions'][t] for a,ts in ((self,(332413,332415)),(target,(332414,332416))) for t in ts):return self._end_link(now,True)
            if target.is_untargetable() or math.dist(self.position_at(now),target.position_at(now))>360:return self._end_link(now)
            packets=[]
            if now>=link['next_tick_at']:
                raw=self.combat_stat('iAttack',now)
                packets.extend(self._loan(link,target,now))
                if self.link is not link:return packets
                packets.extend(self._hit(target,raw,now,link['generation']))
                link['next_tick_at']+=1000
            if self.link is not link:return packets
            if now>=link['end']:return packets+self._end_link(now)
            self._queue(min(now+50,link['end']),kind,link);return packets
        if kind=='dracula_swap':
            cast,=data
            if self.ready is not cast:return []
            target=self.arena.actors.get(cast['target'])
            if not self.alive or not target or not target.alive or target.generation!=cast['target_generation'] or target.is_untargetable():return self.interrupt(now)
            ch,th=self.hp,target.hp;cm,tm=self.max_hp,target.max_hp
            vampire=D('.25')+1-ch/cm
            self.ready=None;packets=self._unlock(cast,now)
            packets.append(scene(skills=(self._skill_event(332301,self.position_at(now),target.position_at(now),target.id),)))
            candidate=max(min(D(1),tm),min(tm,quantize(ch/cm*tm)))
            after=max(min(D(1),cm),min(cm,quantize(th/tm*cm)))
            if target.camp==self.camp:
                packets.extend(target.commit_hp(candidate,now)+self.commit_hp(after,now))
            else:
                floor=min(th,max(D(target.info.get('death_floor',0)),D(1) if target.has_buff(359301,now) else D(0)))
                loss=min(max(D(0),th-candidate),max(D(0),th-floor))
                packets.extend(target.commit_hp(th-loss,now)+self.commit_hp(max(ch,after),now))
                hit,lost=self.damage(cast['power']*D('3.58'),now,target=target,school='physical',lifesteal=vampire,hp_swap_loss=loss)
                packets.extend(hit)
                if lost:packets.extend(self._dot(target,now))
            return packets+self.sync_speed(now)
        return super()._event(now,kind,data)

    def cast(self,slot,start,dest,target_id,now):
        if slot==1 and self.bat:
            return self._end_bat(now) if now>=self.bat['begin']+500 and not self.blocked('attack',now) and not self.skill_sealed(1,now) else []
        if slot not in SLOTS or self.blocked('attack',now) or self.skill_sealed(slot,now) or self.cooldowns[slot]>now:return []
        target=self.arena.actors.get(target_id)
        if slot in (2,10) and (not target or target is self or not target.alive or target.is_untargetable() or target.info.get('npc_template')
                or math.dist(start,target.position_at(now))>{2:264,10:360}[slot] or slot==10 and target.camp==self.camp):return []
        if slot in (2,10) and target.camp!=self.camp:
            from bot_ai import team_visible
            if not team_visible(self.arena,self,target,now):return []
        if slot==2 and self.link:return []
        if slot==0 and start==dest:return []
        power=self.combat_stat('iAttack',now)
        self.cooldowns[slot]=now+self.skill_cooldown({0:self.fire_interval(now),1:8000,2:30000,10:5000}[slot], slot)
        if slot==0:return self.shoot(332100,start,dest,now,power,school='physical',basic=True)+[self._cooldown(slot)]
        cast=dict(slot=slot,skill=SLOTS[slot],dest=dest,power=power,generation=self.generation,begin=now,token=self._new_id(2))
        packets=[scene(skills=(self._skill_event(SLOTS[slot],start,dest,target_id,ready=1 if slot==2 else 0),))]
        if slot==1:
            self.bat=cast
            for enemy in enemies(self,area=True):
                if math.dist(start,enemy.position_at(now))<=120:packets.extend(self._hit(enemy,power*D('.68'),now,self.generation))
            for template in range(332202,332211):packets.extend(self._buff(template,now))
            self._queue(now+500,'dracula_bat',cast,1)
        elif slot==10:
            cast.update(target=target.id,target_generation=target.generation,end=now+5000,next_tick_at=now+1000)
            self.link=cast
            packets.extend(self._buff(332401,now,target.id)+self._buff(332402,now))
            self._queue(now+50,'dracula_link',cast)
        else:
            cast.update(target=target.id,target_generation=target.generation,dest=target.position_at(now))
            self.ready=cast
            for actor,template in ((self,332311),(target,332313)):
                if actor.camp!=self.camp and actor.cc_immune(now):continue
                origin,stopped=prepare_displacement(actor,now,interrupt=False)
                packets.extend(stopped)
                actor.position,actor.motion=origin,None
                packets.extend(self._buff(template,now,actor.id))
                actor.dracula_ritual=cast
                packets.extend(actor.sync_speed(now))
            self._queue(now+1500,'dracula_swap',cast)
        return packets+[self._cooldown(slot,slot==1)]+self.sync_speed(now)
