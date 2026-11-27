"""Persist native C79/C88 character preferences, independent of battle resets."""
import json
import struct

import storage


def key(mid):
    return f'player_settings:{storage.profile_id()}:{mid}'


def save(mid,payload):
    if mid==79:
        if len(payload)<4:raise ValueError('Missing setting flags')
        value=struct.unpack_from('<I',payload)[0]
        reply=1036,struct.pack('<I',value)
    elif mid==88:
        if len(payload)<2:raise ValueError('Missing character options')
        length=struct.unpack_from('<H',payload)[0]
        if length>16384 or len(payload)<length+2:raise ValueError('Invalid character options length')
        value=payload[2:length+2].decode('utf8')
        options=json.loads(value)
        if not isinstance(options,dict):raise ValueError('Character options must be an object')
        for field in ('skillSlot','keyBoardSet'):
            if field in options and not isinstance(options[field],list):
                raise ValueError('Invalid character option array')
        reply=1047,payload[:length+2]
    else:raise ValueError('Unknown setting request')
    with storage.connection(write=True) as db:
        db.execute('INSERT INTO settings(name,value) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
                   (key(mid),json.dumps(value,ensure_ascii=False)))
    return reply


def snapshot():
    """Use fast casting on first login; preserve every explicitly saved choice.

    The historical login capture contains an empty skillSlot array, which is
    indistinguishable on the wire from a player deliberately disabling all
    quick casts. Choose the requested default here, before those two cases are
    flattened into S1047. Reading a default must not create a saved preference.
    """
    with storage.connection() as db:
        saved={r[0]:json.loads(r[1]) for r in db.execute(
            'SELECT name,value FROM settings WHERE name IN (?,?)',(key(79),key(88)))}
    result={}
    if key(79) in saved:result[1036]=struct.pack('<I',saved[key(79)])
    if key(88) in saved:
        raw=saved[key(88)].encode('utf8');result[1047]=struct.pack('<H',len(raw))+raw
    else:
        # SystemSetModel slots: R=10, E=1, Space=2, Guild=4. Passive slot3 has
        # no user input. Existing C88 data, including skillSlot=[], wins above.
        raw=json.dumps({'skillSlot':[10,1,2,4],'keyBoardSet':[]},separators=(',',':')).encode('utf8')
        result[1047]=struct.pack('<H',len(raw))+raw
    return result
