"""Next-match settings, separate from the active room's durable snapshot."""
import json
import random
import bot_cosmetics
import bot_loadouts

from storage import connection, setting_key

SETTING = 'pk_bot_setup'
AI_TANKS = {10000019:'Gundam',10000001:'Iron Man',10000056:'Quan Vũ',
            10000031:'Captain',10000065:'Tiên Cá',10000003:'Panda',
            10000029:'Chopper',10000032:'Teddy Bear',10000041:'Legolas',10000063:'Thạch Sanh',
            10000002:'Groot',10000037:'Hồ Lô',10000073:'Baymax',10000085:'Athena',
            10000039:'Thor',10000047:'Pikachu',10000043:'Thánh Gióng',
            10000069:'Bò Cạp Độc',10000089:'Star Lord',
            10000034:'Hulk',10000036:'Ngộ Không',10000046:'Luffy',
            10000066:'Edwina Knight',10000103:'Ngưu Ma Vương',
            10000067:'Triệu Vân',10000075:'Lữ Bố',10000077:'Zoro',
            10000081:'Kiếm Thần',10000096:'Kirito',10000099:'Hoa Mộc Lan',
            10000045:'Bọt Biển',10000074:'Điêu Thuyền',10000107:'Hikari',
            10000086:'Cửu Vĩ Hồ',10000106:'Elsa',10000079:'Thủy Tinh',
            10000105:'Hỏa Thần',10000112:'Chu Du',10000058:'Medusa',
            10000088:'Gilgamesh',10000098:'Tư Mã Ý',
            10000008:'Spider Man',10000100:'Black Panther',10000078:'Mikasa',
            10000110:'Aquaman',10000111:'Tsubasa',
            10000048:'Sát thủ',10000030:'Dark Knight',10000071:'Joker',
            10000114:'Night Wing',10000108:'Shadowblade',
            10000038:'Ghost Rider',10000059:'Phượng Hoàng Lửa',10000070:'Deadpool',10000076:'Kaneki - Ghoul',
            10000051:'Sơn Tinh',10000042:'Songoku',10000064:'Ichigo',10000062:'Optimus Prime',10000082:'Na Tra',
            10000061:'Thiên Thần',10000092:'Hades',10000044:'Naruto',10000093:'Sasuke',
            10000049:'Transformer',10000053:'Superman',10000090:'Natsu',10000104:'Falcon',10000102:'Saitama',
            10000033:'Pea Shooter',10000101:'Sniper',10000052:'Bí Ngô Vương',10000060:'Minion',10000095:'Kurumi',
            10000035:'Pegasus',10000040:'Người Sói',10000072:'Apocalypse',10000087:'Dương Tiễn',
            10000050:'Thợ Săn Thời Gian',10000109:'Thạch Thần',10000083:'Doctor Strange',10000080:'Doraemon',
            10000054:'Ông già Noel',10000057:'Dracula',10000091:'Tào Tháo',10000115:'Daredevil',10000084:'Gia Cát Lượng',10000055:'Kakashi',10000094:'Lạc Long Quân',10000097:'Magneto',10000113:'Nữ Thần Thời Gian'}
# Same verified fallback approved for the playable base tank on 28/09.
# It changes presentation only; the default 452 still has missing body/cannon.
AI_EXTERNALS = {10000063:453,10000002:833,10000103:825,10000096:782,10000107:866,10000105:872,10000098:869,10000111:887,10000082:642,10000090:723,10000060:10507,10000109:882,10000084:662}
PK_MAPS=(1,4,17,18,19,20,21,34,35,36)
BOT_MAPS=(70,30,40,7,9,10,12,14,37,50,169,170,*PK_MAPS)
MODE_MAPS={'escort_bomb':70,'death_city':40,'death_mine':30,'base_polar':169,'base_ruins':14,'base_mineral':12,'base_town':50,'pk_mine':36,'pk_fortress':35,'pk_polar':34,'pk_lightning':21,'pk_fastfood':17,'pk_snow':4,'pk_maya':1,'occupy_quicksand':170,'occupy_military':37,'occupy_freight':10,'occupy_tomb':9,'occupy_desert':7,'pk_robo':19,'pk_cow':20,'pk_totem':18,'test':101}
MODE_MAPS['test_desert']=7
# Clear ground on the east side of map 7, 180px minimum spacing. These are
# room-specific positions; the original map spawns/terrain stay unchanged.
TEST_DESERT_TANKS=(10000019,10000003,10000034,10000042,10000044)
TEST_DESERT_POSITIONS=((1380,636),(1560,636),(1380,816),(1560,816),(1470,996))


def default_setup():
    return dict(mode='pk_robo',allies=[5]*4,enemies=[5]*5,quanvu_execute_hint=False,bot_guild=False,bot_crystals=False,bot_military=False,bot_ai='legacy',bot_ai_allies='legacy',bot_ai_enemies='legacy')


def validate_setup(value):
    if not isinstance(value,dict) or value.get('mode') not in MODE_MAPS:
        raise ValueError('Chọn Chiếm cờ Việt Dã/Cổ Mộ/Trung Tâm Vận Chuyển/Quân Khu Tử Thần/Vùng Cát Lún, PK Băng Thiên Tuyết Địa, PK Maya, PK Robo, PK Dắt bò, PK Vật Tổ hoặc phòng thử tank.')
    out = {'mode':value['mode']}
    for key,minimum,maximum in (('allies',0,4),('enemies',0,5)):
        levels = value.get(key)
        if (not isinstance(levels,list) or not minimum<=len(levels)<=maximum
                or any(type(level) is not int or not 1<=level<=6 for level in levels)):
            raise ValueError('Mỗi bot cần cấp tank từ 1 đến 6; tối đa 5 xe mỗi phe.')
        out[key] = list(levels)
    hint=value.get('quanvu_execute_hint',False)
    if type(hint) is not bool:
        raise ValueError('Gợi ý trảm Quan Vũ cần chọn bật hoặc tắt.')
    out['quanvu_execute_hint']=hint
    from bot_policy import validate as validate_policy
    out['bot_ai']=validate_policy(value.get('bot_ai','legacy'))
    for side in ('allies','enemies'):
        out['bot_ai_'+side]=validate_policy(value.get('bot_ai_'+side,out['bot_ai']))
    for flag in ('bot_guild','bot_crystals','bot_military'):
        value_flag=value.get(flag,False)
        if type(value_flag) is not bool:raise ValueError('Trang bị bot cần chọn bật hoặc tắt.')
        out[flag]=value_flag
    if out['mode']=='test_desert':
        out.update(allies=[],enemies=[6]*5)
    return out


def load_setup(db=None):
    if db is None:
        with connection() as opened:
            return load_setup(opened)
    row = db.execute('SELECT value FROM settings WHERE name=?',(setting_key(SETTING),)).fetchone()
    return validate_setup(json.loads(row[0])) if row else default_setup()


def save_setup(value):
    value = validate_setup(value)
    with connection(write=True) as db:
        db.execute('INSERT INTO settings(name,value) VALUES (?,?) '
                   'ON CONFLICT(name) DO UPDATE SET value=excluded.value',
                   (setting_key(SETTING),json.dumps(value)))
    return value


def make_roster(setup, rng=None, player_tank=None):
    """Roll once per room. Levels don't enter tank choice or AI policy."""
    rng = rng or random.SystemRandom()
    roster = []
    for side in ('enemies','allies'):
        pool=[t for t in AI_TANKS if side!='allies' or t!=player_tank]
        fixed=setup.get('mode')=='test_desert'
        levels=([6]*5 if side=='enemies' else []) if fixed else setup[side]
        tanks=TEST_DESERT_TANKS if fixed else rng.sample(pool,len(levels))
        for tank,level in zip(tanks,levels):
            ident = len(roster)+2
            roster.append(dict(object_id=ident,acct_id=88888886+ident,
                char_uuid=f'robot-pk-{ident}',name=f'{AI_TANKS[tank]} {ident-1}',
                tank_id=tank,tank_level=level,tank_ext=AI_EXTERNALS.get(tank,0),tank_strength=0,
                side=side,ready=1,in_room=True))
            if fixed:
                roster[-1]['test_spawn']=TEST_DESERT_POSITIONS[ident-2]
            else:
                bot_cosmetics.roll(roster[-1],rng)
            bot_loadouts.apply(roster[-1],setup)
    return roster


def unique_room_roster(state,rng=None):
    """Changing the human's tank only rerolls conflicting lobby bots."""
    if state.get('battle') or (state.get('room') or {}).get('map_id') not in BOT_MAPS:return []
    if (state.get('room') or {}).get('ranked') and state.get('rank_bot_roster'):
        from ranked_matches import stable_room_roster
        return stable_room_roster(state)
    rng=rng or random.SystemRandom();changed=[]
    for side in ('enemies','allies'):
        bots=[b for b in state.get('bots',[]) if b['side']==side and b.get('in_room',True)]
        used={state['tank_id']} if side=='allies' else set()
        conflicts=[]
        for bot in bots:
            if bot['tank_id'] in used:conflicts.append(bot)
            else:used.add(bot['tank_id'])
        pool=[t for t in AI_TANKS if t not in used]
        for bot,tank in zip(conflicts,rng.sample(pool,len(conflicts))):
            bot.update(tank_id=tank,tank_ext=AI_EXTERNALS.get(tank,0),name=f'{AI_TANKS[tank]} {bot["object_id"]-1}')
            if not (state.get('room') or {}).get('tank_test'):
                bot_cosmetics.roll(bot,rng,skin_only=True)
            bot_loadouts.apply(bot,state.get('room') or {})
            changed.append(bot)
    return changed


def room_bots(state):
    if (state.get('room') or {}).get('room_type') in (4,7):return []
    if (state.get('room') or {}).get('map_id') in BOT_MAPS:
        bots=[b for b in state.get('bots',[]) if b.get('in_room',True)]
    else:
        bots=[state[k] for k in ('bot','ally_bot') if state.get(k) and state[k].get('in_room',True)]
    for bot in bots:
        bot['avatar']=bot_cosmetics.valid_avatar(bot.get('avatar'))
    return bots


def configure_room(state, db, *, setup=None, rng=None):
    """Apply web choices only when creating a room, never to an active match."""
    setup=load_setup(db) if setup is None else validate_setup(setup)
    room=state['room']
    room['quanvu_execute_hint']=setup['quanvu_execute_hint']
    room.update({key:setup[key] for key in ('bot_guild','bot_crystals','bot_military')})
    room['tank_test']=setup['mode']=='test_desert'
    camp=int(room.get('camp',1))
    if not room['tank_test']:
        room['bot_ai_camps']={str(camp):setup['bot_ai_allies'],str(3-camp):setup['bot_ai_enemies']}
    else:
        room.pop('bot_ai_camps',None)
    if setup['bot_ai']=='elite_v1' and not room['tank_test']:
        room['bot_ai']=setup['bot_ai']
    else:
        room.pop('bot_ai',None)
    if MODE_MAPS[setup['mode']] in BOT_MAPS:
        if room['tank_test']:
            room.update(map_id=7,mode=2,room_type=2,name='Phòng test tank - Việt Dã')
        elif MODE_MAPS[setup['mode']] in (7,9,10,37,170):
            title={'occupy_desert':'Việt Dã','occupy_tomb':'Cổ Mộ','occupy_freight':'Trung Tâm Vận Chuyển','occupy_military':'Quân Khu Tử Thần','occupy_quicksand':'Vùng Cát Lún'}[setup['mode']]
            room.update(map_id=MODE_MAPS[setup['mode']],mode=2,room_type=2,name=f'Chiếm cờ {title} - 1.000 điểm / 10 phút')
        elif setup['mode']=='escort_bomb':
            room.update(map_id=70,mode=1,room_type=2,name='Hộ tống xe bom - về đích / 15 phút')
        elif setup['mode']=='death_city':
            room.update(map_id=40,mode=4,room_type=2,name='Sinh Tử Thành Tận Thế - thắng 2 vòng')
        elif setup['mode']=='death_mine':
            room.update(map_id=30,mode=4,room_type=2,name='Sinh Tử Mỏ Khoáng Sụp Đổ - thắng 2 vòng')
        elif setup['mode'] in ('base_town','base_mineral','base_ruins','base_polar'):
            title={'base_town':'Thị Trấn Ánh Dương','base_mineral':'Tranh Đoạt Tinh Khoáng','base_ruins':'Di Tích Maya','base_polar':'Địa Cực Dota'}[setup['mode']]
            room.update(map_id=MODE_MAPS[setup['mode']],mode=1,room_type=2,name=f'Phá nhà {title} - 15 phút')
        else:
            title={'pk_mine':'Khu Mỏ Phóng Xạ','pk_fortress':'Pháo Đài Không Gian','pk_polar':'Tiền Đồn Cực Địa','pk_lightning':'Điện Chớp Sấm Rền','pk_fastfood':'Quán Ăn Vui Vẻ','pk_snow':'Băng Thiên Tuyết Địa','pk_maya':'Lời Tiên Tri Maya','pk_robo':'Robo','pk_cow':'Dắt bò','pk_totem':'Vật Tổ'}[setup['mode']]
            duration='3 phút 30 giây' if setup['mode'] in ('pk_totem','pk_polar') else '4 phút'
            room.update(map_id=MODE_MAPS[setup['mode']],mode=3,room_type=2,name=f'PK {title} - 25 điểm / {duration}')
        state['bots']=make_roster(setup,rng=rng,player_tank=state['tank_id'])
        state['bot_cosmetics_prepared']=True
    else:
        from battle_entry import ensure_test_ally
        room.update(map_id=101,mode=1,room_type=1)
        state.pop('bots',None)
        state['bot']['in_room']=True
        ensure_test_ally(state)['in_room']=True
