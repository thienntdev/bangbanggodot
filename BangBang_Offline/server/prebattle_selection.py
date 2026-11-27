"""Native select/lock packets; the Garage primary UUID never changes here."""
import math
import struct

SELECT_SECONDS = 60


def use_tank(state, record):
    state.update(tank_id=record['tank_id'], tank_level=record['level'],
                 tank_strength=record.get('stth_level', 0),
                 tank_ext=record.get('external_id', 0), halo_id=record.get('halo_id', 0),
                 skin_frame_type=record.get('skin_frame_type', 0))


def begin(state, records):
    primary = next((r for r in records if r['uuid'] == state.get('selected_tank_uuid')), None)
    if primary is None:
        primary = next(r for r in records if r['tank_id'] == state['tank_id'])
        state['selected_tank_uuid'] = primary['uuid']
    use_tank(state, primary)
    state['match_tank_uuid'] = primary['uuid']
    state['tank_selection'] = {'remaining': SELECT_SECONDS}


def restore_primary(state, records):
    if state.pop('match_tank_uuid', None) is not None:
        primary = next(r for r in records if r['uuid'] == state['selected_tank_uuid'])
        use_tank(state, primary)
    state.pop('tank_selection', None)


def select(state, payload, records, supported):
    if not state.get('tank_selection') or state.get('battle'):
        return None
    if len(payload) < 13 or any(payload[13:]):
        raise ValueError('Invalid C215 select-tank packet')
    scene, tank, container, room_type = struct.unpack_from('<IIIB', payload)
    room = state['room']
    if scene != room['room_id'] or room_type != room['room_type']:
        raise ValueError('Select-tank scene/type mismatch')
    record = next((r for r in records if r['tank_id'] == tank
                   and r.get('cont_type', 0) == container), None)
    if container != 0 or tank not in supported or record is None:
        raise ValueError('Select-tank requires an owned, supported tank')
    use_tank(state, record)
    state['match_tank_uuid'] = record['uuid']
    return record


def pair_payload(state, char_data, locked_ids):
    room = state['room']
    seconds = max(0, math.ceil(state['tank_selection']['remaining']))
    return (struct.pack('<IIBH', room['room_id'], room['map_id'], room['room_type'], len(char_data))
            + b''.join(char_data) + struct.pack('<H', len(locked_ids))
            + b''.join(struct.pack('<I', ident) for ident in locked_ids)
            + struct.pack('<I', seconds))


def selected_payload(ident, tank, external, skin_frame=0, command=0):
    return struct.pack('<6I', ident, tank, 0, external, skin_frame, command)
