"""Transactional, one-time import of the existing local server data."""
import hashlib
import io
import json
import sqlite3
import struct
from xml.etree import ElementTree as ET

from storage import ROOT, SCHEMA_VERSION, database_path, quote

GARAGE_FIELDS = (
    ('uuid','s'),('tank_id','I'),('level','B'),('n_exp','I'),('ext_flag','I'),
    ('stth_level','B'),('external_id','I'),('war_count','I'),('week_war_count','I'),
    ('cont_type','B'),('cash_hire','B'),('coin_hire','B'),('exist_time','I'),
    ('halo_id','I'),('skin_frame_type','B'),('own_time','I'),('stth_count','B'),
    ('com_skill_id','I'),('crystal_scheme_id','B'),('tal_page_uuid','s'),
    ('prof_val','I'),('battle_gains','i'))


def parse_garage(payload):
    stream = io.BytesIO(payload)
    def read(fmt):
        return struct.unpack('<'+fmt, stream.read(struct.calcsize('<'+fmt)))[0]
    records = []
    for _ in range(read('H')):
        records.append({name: stream.read(read('H')).decode('utf-8') if fmt=='s' else read(fmt)
                        for name,fmt in GARAGE_FIELDS})
    trailer = stream.read()
    # Two NotifyTankList flags, followed by the capture's transport padding.
    # Preserve the entire suffix byte-for-byte rather than invent its meaning.
    if len(trailer)<2:
        raise ValueError(f'Invalid NotifyTankList trailer: {len(trailer)} bytes')
    return records,trailer


def tank_instance_payload(record):
    out = bytearray()
    for name,fmt in GARAGE_FIELDS:
        value = record[name]
        if fmt=='s':
            raw = value.encode('utf-8')
            out.extend(struct.pack('<H',len(raw))+raw)
        else:
            out.extend(struct.pack('<'+fmt,value))
    return bytes(out)


def garage_payload(records, trailer):
    out = bytearray(struct.pack('<H',len(records)))
    for record in records:
        out.extend(tank_instance_payload(record))
    return bytes(out)+trailer


def initialize(path=None, root=ROOT):
    path = path or database_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    db = sqlite3.connect(path)
    try:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version == SCHEMA_VERSION:
            return False
        if version or db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
            raise RuntimeError('Existing database is not a supported import target')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        statements = (
            'CREATE TABLE users (username TEXT PRIMARY KEY,salt TEXT NOT NULL,pw TEXT NOT NULL,created INTEGER NOT NULL)',
            'CREATE TABLE sessions (token TEXT PRIMARY KEY,username TEXT NOT NULL REFERENCES users(username),cookie TEXT NOT NULL,exp REAL NOT NULL)',
            'CREATE INDEX sessions_cookie ON sessions(cookie)',
            'CREATE TABLE settings (name TEXT PRIMARY KEY,value TEXT NOT NULL)',
            'CREATE TABLE template_sources (filename TEXT PRIMARY KEY,sql_table TEXT UNIQUE NOT NULL,row_count INTEGER NOT NULL,sha256 TEXT NOT NULL)',
            'CREATE TABLE lobby_frames (ordinal INTEGER PRIMARY KEY,message_id INTEGER NOT NULL,frame BLOB NOT NULL)',
            'CREATE TABLE http_bootstrap (name TEXT PRIMARY KEY,payload BLOB NOT NULL)',
            'CREATE TABLE worlds (profile_id INTEGER PRIMARY KEY,state TEXT NOT NULL,arena TEXT,updated_ms INTEGER NOT NULL DEFAULT 0)',
            'CREATE TABLE garage (profile_id INTEGER NOT NULL REFERENCES worlds(profile_id),ordinal INTEGER NOT NULL,uuid TEXT NOT NULL,tank_id INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(profile_id,uuid))',
        )
        for sql in statements:
            db.execute(sql)
        for name,rec in json.loads((root/'data/users.json').read_text(encoding='utf-8')).items():
            db.execute('INSERT INTO users VALUES (?,?,?,?)',(name,rec['salt'],rec['pw'],rec['created']))
        for token,rec in json.loads((root/'data/sessions.json').read_text(encoding='utf-8')).items():
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(token,rec['username'],rec['cookie'],rec['exp']))
        for source in sorted((root/'data/xmlpack').glob('*.xml')):
            raw = source.read_bytes()
            rows = [{f.tag:f.text or '' for f in row} for row in ET.fromstring(raw).iter('entry')]
            fields = sorted({k for row in rows for k in row})
            table = 'client_'+source.stem
            columns = ','.join(quote(k)+' TEXT' for k in fields)
            db.execute(f'CREATE TABLE {quote(table)} (_ordinal INTEGER PRIMARY KEY'+(','+columns if columns else '')+')')
            if rows:
                marks = ','.join('?' for _ in range(len(fields)+1))
                db.executemany(f'INSERT INTO {quote(table)} VALUES ({marks})',
                               ((i,*(row.get(k) for k in fields)) for i,row in enumerate(rows)))
            db.execute('INSERT INTO template_sources VALUES (?,?,?,?)',
                       (source.name,table,len(rows),hashlib.sha256(raw).hexdigest()))
        bot_hp = int(db.execute('SELECT iHp FROM client_TankUpTemplate_table WHERE nTankId=? AND nLevel=?',('10000019','5')).fetchone()[0])
        world = dict(char_id=30000791,char_uuid='multiplayer-char-30000791',name='Vua36',
                     level=36,sex=1,vip_level=6,tank_id=10000056,tank_level=5,tank_ext=395,
                     halo_id=0,skin_frame_type=0,room=None,battle=None,
                     bot=dict(acct_id=88888888,char_uuid='robot-88888888',name='Bot Gundam',
                              tank_id=10000019,tank_level=5,tank_ext=0,camp=2,ready=1,in_room=True,
                              hp=bot_hp,max_hp=bot_hp))
        db.execute('INSERT INTO worlds(profile_id,state) VALUES (?,?)',(world['char_id'],json.dumps(world)))
        capture = root/'data/netzone_capture'
        raw = (capture/'frames/38658_s2c.bin').read_bytes()
        offset = 2 if raw.startswith(b'\0\0') else 0
        ordinal = 0
        garage_found = False
        while offset < len(raw):
            size,mid = struct.unpack_from('<HH',raw,offset)
            if size<8 or offset+size>len(raw):
                raise ValueError('Invalid lobby capture')
            frame = raw[offset:offset+size]
            db.execute('INSERT INTO lobby_frames VALUES (?,?,?)',(ordinal,mid,frame))
            if mid==1150:
                records,trailer = parse_garage(frame[8:])
                db.execute('INSERT INTO settings VALUES (?,?)',('garage_trailer',json.dumps(trailer.hex())))
                for i,record in enumerate(records):
                    db.execute('INSERT INTO garage VALUES (?,?,?,?,?)',
                               (world['char_id'],i,record['uuid'],record['tank_id'],json.dumps(record)))
                garage_found = True
            ordinal += 1
            offset += size
        if not garage_found:
            raise ValueError('Missing garage capture')
        for source in capture.glob('live_*_capi_*'):
            db.execute('INSERT INTO http_bootstrap VALUES (?,?)',(source.name,source.read_bytes()))
        data = (root/'www/rez/zh_CN/map/d03c0100380b46ebc410489a4b7388a6.map').read_bytes()
        version,_,width,height,*_ = struct.unpack_from('<9i',data)
        tag,_,count = struct.unpack_from('<3i',data,36)
        if (version,width,height,tag,count)!=(1006,1440,936,1,7):
            raise ValueError('Map 101 layout changed')
        walls = []
        for i in range(count):
            x,y,w,h,kind = struct.unpack_from('<5i',data,48+i*20)
            if kind in (-1,0):
                walls.append((x-w/2,y-h/2,x+w/2,y+h/2))
        host_source = root/'data/advertise_host.txt'
        host = host_source.read_text(encoding='utf-8').strip() if host_source.exists() else ''
        for name,value in {'advertise_host':host or 'bangbang.private','map101_walls':walls}.items():
            db.execute('INSERT INTO settings VALUES (?,?)',(name,json.dumps(value)))
        db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        db.commit()
        return True
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
