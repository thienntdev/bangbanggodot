"""Authoritative small-server room membership and HTML5 rooms-v1 protocol.

This module owns only process-local coordination. It never opens a database,
sends a socket, ticks an arena, or accepts player combat statistics from JSON.
Authenticated GATE owner threads supply trusted peer/bot snapshots and drain
their own control queues. A separate shared-match owner runs each battle once.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from copy import deepcopy
import hashlib
import json
import re
import secrets
import struct
import threading
import time

REQUEST = 60006
REPLY = 60007
VERSION = 1
MAX_REQUEST_BYTES = 4096
MAX_REPLY_BYTES = 60000
MAX_PEER_EVENTS = 128
INVITE_SECONDS = 60
RANK_SOLO_SECONDS = 5
RECONNECT_SECONDS = 120
POLICIES = ('legacy', 'elite_v1')
_IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_CODE = re.compile(r'^[0-9]{6}$')
_FIELDS = {
    'status': set(), 'subscribe': set(), 'online': set(), 'create': set(),
    'join': {'code', 'camp'}, 'leave': set(), 'ready': {'ready'},
    'team': {'camp', 'account_id', 'revision'},
    'kick': {'slot', 'expected_account_id', 'revision'},
    'remove_bot': {'slot', 'expected_account_id', 'revision'},
    'add_bot': {'camp', 'level', 'revision'},
    'bot_policy': {'camp', 'bot_ai', 'revision'},
    'invite': {'account_id', 'camp', 'revision'},
    'accept': {'invite_id'}, 'decline': {'invite_id'},
    'rank_queue': set(), 'rank_cancel': set(),
}


class RoomError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _need(ok, code, message):
    if not ok:
        raise RoomError(code, message)


def _integer(value, low=0, high=0xffffffff):
    return type(value) is int and low <= value <= high


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate rooms-v1 JSON key')
        result[key] = value
    return result


def validate_request(value):
    """Validate the exact public request shape, not membership or authority."""
    if not isinstance(value, dict):
        raise ValueError('Rooms-v1 request must be an object')
    action = value.get('action')
    if (type(value.get('v')) is not int or value['v'] != VERSION
            or not isinstance(action, str) or action not in _FIELDS
            or not isinstance(value.get('request_id'), str)
            or not _IDENTIFIER.fullmatch(value['request_id'])
            or set(value) - ({'v', 'request_id', 'action'} | _FIELDS[action])):
        raise ValueError('Invalid rooms-v1 envelope or fields')
    if 'camp' in value and not _integer(value['camp'], 1, 2):
        raise ValueError('Camp must be 1 or 2')
    if 'account_id' in value and not _integer(value['account_id'], 1):
        raise ValueError('Invalid account ID')
    if 'revision' in value and not _integer(value['revision'], 1):
        raise ValueError('Invalid room revision')
    if action == 'join' and (not isinstance(value.get('code'), str) or not _CODE.fullmatch(value['code'])):
        raise ValueError('Room code must contain six digits')
    if action == 'ready' and type(value.get('ready')) is not bool:
        raise ValueError('Readiness must be boolean')
    if action in ('team', 'add_bot', 'bot_policy') and 'camp' not in value:
        raise ValueError('Camp is required')
    if action in ('team', 'kick', 'remove_bot', 'add_bot', 'bot_policy') and 'revision' not in value:
        raise ValueError('Room revision is required')
    if action in ('kick', 'remove_bot') and (not _integer(value.get('slot'), 0, 9)
                                           or not _integer(value.get('expected_account_id'), 1)):
        raise ValueError('Slot and expected occupant are required')
    if action == 'add_bot' and not _integer(value.get('level'), 1, 6):
        raise ValueError('Bot tank level must be 1..6')
    if action == 'bot_policy' and value.get('bot_ai') not in POLICIES:
        raise ValueError('Bot AI must be legacy or elite_v1')
    if action == 'invite' and 'account_id' not in value:
        raise ValueError('Invitation recipient is required')
    if action in ('accept', 'decline') and (not isinstance(value.get('invite_id'), str)
                                           or not _IDENTIFIER.fullmatch(value['invite_id'])):
        raise ValueError('Invitation ID is required')
    return deepcopy(value)


def decode_request(payload):
    if not isinstance(payload, (bytes, bytearray)) or len(payload) < 2:
        raise ValueError('Truncated rooms-v1 request')
    size, = struct.unpack_from('<H', payload)
    if not 0 < size <= MAX_REQUEST_BYTES or len(payload) != size + 2:
        raise ValueError('Rooms-v1 request length mismatch')
    def invalid_constant(_):
        raise ValueError('Non-finite rooms-v1 JSON number')
    value = json.loads(bytes(payload[2:]).decode('utf-8'), object_pairs_hook=_unique_pairs,
                       parse_constant=invalid_constant)
    return validate_request(value)


def encode_reply(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(raw) > MAX_REPLY_BYTES:
        raise ValueError('Rooms-v1 reply is too large')
    return struct.pack('<H', len(raw)) + raw


def reply_packet(value):
    return REPLY, encode_reply(value)


def _public(profile, value):
    value = value or {}
    return dict(account_id=profile, name=str(value.get('name', 'Người chơi'))[:80],
                level=int(value.get('level', 1)), avatar_id=int(value.get('avatar_id', value.get('avatar', 0))),
                tank_id=int(value.get('tank_id', 0)), tank_level=int(value.get('tank_level', 1)),
                external_id=int(value.get('external_id', value.get('tank_ext', 0))))


def _merge_public(profile, old, update):
    update = dict(update)
    if 'avatar' in update and 'avatar_id' not in update:
        update['avatar_id'] = update['avatar']
    if 'tank_ext' in update and 'external_id' not in update:
        update['external_id'] = update['tank_ext']
    return _public(profile, {**old, **update})


class RoomHub:
    """One process-local authority for seats, invitations, and queue reservation."""
    def __init__(self, *, clock=None, wall_clock=None, code_factory=None,
                 rank_wait=RANK_SOLO_SECONDS, reconnect_grace=RECONNECT_SECONDS):
        self._guard = threading.RLock()
        self._clock = clock or time.monotonic
        self._wall = wall_clock or time.time
        self._code_factory = code_factory or (lambda: secrets.randbelow(900000) + 100000)
        self.rank_wait = float(rank_wait)
        self.reconnect_grace = float(reconnect_grace)
        self._peers = {}
        self._rooms = {}
        self._membership = {}
        self._invites = {}
        self._queue = OrderedDict()
        self._reservations = {}
        self._reserved = {}
        self._sequence = 0
        self._bot_id = 1900000000

    def _peer(self, profile, generation=None, *, connected=True):
        peer = self._peers.get(profile)
        _need(peer is not None and (not connected or peer['connected'])
              and (generation is None or peer['generation'] == generation),
              'session_changed', 'Phiên game đã thay đổi. Hãy tải lại trang.')
        return peer

    def _status(self, peer):
        profile = peer['profile_id']
        if profile in self._reserved:
            return 'rank_reserved'
        if profile in self._queue:
            return 'rank_queue'
        room = self._rooms.get(self._membership.get(profile))
        return room['phase'] if room else peer['status']

    def _available(self, peer):
        profile = peer['profile_id']
        return (peer['connected'] and profile not in self._membership
                and profile not in self._queue and profile not in self._reserved
                and peer['status'] == 'lobby')

    def _emit(self, profile, kind, **data):
        peer = self._peers.get(profile)
        if peer is None or not peer['connected']:
            return
        event = dict(kind=kind, **deepcopy(data))
        queue = peer['events']
        # Notifications are control-plane state, not battle packets. Replacing
        # stale snapshots keeps a slow browser from building an unbounded queue.
        if kind in ('presence_changed', 'room_changed', 'invitation_changed', 'queue_changed'):
            queue = deque(e for e in queue if not (e['kind'] == kind and
                           (kind != 'room_changed' or e.get('room_id') == data.get('room_id'))))
            peer['events'] = queue
        if len(queue) >= MAX_PEER_EVENTS:
            queue.popleft()
            peer['needs_resync'] = True
        queue.append(event)

    def _presence(self):
        for profile, peer in self._peers.items():
            if peer['connected']:
                self._emit(profile, 'presence_changed')

    def _human_seats(self, room):
        return [seat for seat in room['seats'] if seat and seat['kind'] == 'human']

    def _broadcast(self, room, kind, **data):
        for seat in self._human_seats(room):
            if self._membership.get(seat['account_id']) == room['room_id']:
                self._emit(seat['account_id'], kind, room_id=room['room_id'], **data)

    def _changed(self, room, reason, actor_id=0, *, reset_ready=False):
        if reset_ready and room['phase'] == 'waiting':
            for seat in self._human_seats(room):
                seat['ready'] = seat['account_id'] == room['owner_id']
        room['revision'] += 1
        self._broadcast(room, 'room_changed', revision=room['revision'], reason=reason, actor_id=actor_id)
        self._presence()

    def _room_for(self, profile):
        room = self._rooms.get(self._membership.get(profile))
        _need(room is not None, 'not_in_room', 'Bạn chưa ở trong phòng.')
        return room

    def _waiting(self, room, *, casual=False):
        _need(room['phase'] == 'waiting', 'room_started', 'Phòng đang chọn xe hoặc đang trong trận.')
        if casual:
            _need(not room['ranked'], 'ranked_locked', 'Đội hình đấu rank do server ghép.')

    def _owner(self, profile, room):
        _need(profile == room['owner_id'], 'owner_required', 'Chỉ chủ phòng được thực hiện thao tác này.')

    def _revision(self, room, revision):
        _need(type(revision) is int and revision == room['revision'], 'room_changed',
              'Phòng vừa thay đổi. Hãy kiểm tra lại đội hình.')

    def _empty_slot(self, room, camp, *, replace_bot=False):
        choices = list(range(0 if camp == 1 else 5, 5 if camp == 1 else 10))
        for slot in choices:
            if room['seats'][slot] is None:
                return slot
        if replace_bot:
            for slot in reversed(choices):
                if room['seats'][slot]['kind'] == 'bot':
                    return slot
        return None

    def _join_slot(self, room, camp=None):
        if camp is None:
            def weight(side):
                seats = room['seats'][:5] if side == 1 else room['seats'][5:]
                return (sum(bool(s and s['kind'] == 'human') for s in seats),
                        sum(s is not None for s in seats), side)
            camps = sorted((1, 2), key=weight)
        else:
            _need(_integer(camp, 1, 2), 'invalid_camp', 'Phe không hợp lệ.')
            camps = [camp]
        for side in camps:
            slot = self._empty_slot(room, side, replace_bot=True)
            if slot is not None:
                return slot
        raise RoomError('room_full', 'Phe này đã đủ 5 người hoặc phòng đã đầy.')

    def _human(self, peer, slot, ready=False):
        return dict(kind='human', slot=slot, camp=1 if slot < 5 else 2,
                    account_id=peer['profile_id'], public=deepcopy(peer['public']),
                    private=deepcopy(peer['private']), ready=bool(ready), connected=peer['connected'],
                    joined=self._clock(), disconnected_at=None, grace_reported=False)

    def _bot(self, room, record, slot):
        _need(isinstance(record, dict) and _integer(record.get('tank_id'), 1)
              and _integer(record.get('tank_level'), 1, 6), 'invalid_bot', 'Bot chưa có cấu hình hợp lệ.')
        record = deepcopy(record)
        used = {s['account_id'] for s in room['seats'] if s}
        account = record.get('acct_id')
        if not _integer(account, 1) or account in used or account in self._peers:
            while self._bot_id in used or self._bot_id in self._peers:
                self._bot_id += 1
            account = self._bot_id
            self._bot_id += 1
        record.update(acct_id=account, camp=1 if slot < 5 else 2, in_room=True, ready=1)
        record.setdefault('char_uuid', 'room-bot-' + str(account))
        public = _public(account, dict(record, level=record.get('level', 36)))
        return dict(kind='bot', slot=slot, camp=record['camp'], account_id=account,
                    public=public, private=record, ready=True, connected=True)

    def _new_room(self, config, ranked=False):
        _need(isinstance(config, dict) and _integer(config.get('map_id'), 1)
              and _integer(config.get('mode'), 1, 255), 'invalid_room', 'Cấu hình phòng chưa hợp lệ.')
        code = None
        for _ in range(100):
            candidate = self._code_factory()
            if isinstance(candidate, str) and _CODE.fullmatch(candidate):
                candidate = int(candidate)
            if _integer(candidate, 100000, 999999) and candidate not in self._rooms:
                code = candidate
                break
        _need(code is not None, 'room_codes_busy', 'Chưa tạo được mã phòng. Hãy thử lại.')
        policies = config.get('bot_ai_camps', {'1': config.get('bot_ai', 'legacy'), '2': config.get('bot_ai', 'legacy')})
        _need(isinstance(policies, dict) and set(map(str, policies)) == {'1', '2'},
              'invalid_policy', 'Cần chọn AI bot cho cả hai phe.')
        policies = {str(k): v for k, v in policies.items()}
        _need(all(value in POLICIES for value in policies.values()), 'invalid_policy', 'AI bot không hợp lệ.')
        copied = deepcopy(config)
        copied.update(room_id=code, code=str(code), name=str(config.get('name', 'Phòng chơi cùng'))[:80],
                      room_type=9 if ranked else int(config.get('room_type', 2)), ranked=bool(ranked),
                      bot_ai_camps=policies, max_num=10, min_num=2, ob_num=0)
        return dict(room_id=code, code=str(code), owner_id=0, revision=1, phase='waiting',
                    ranked=bool(ranked), config=copied, seats=[None] * 10, locked=set(),
                    selection_deadline=None, selection_id=None, start_claim=None, runtime_ids=None)

    def _fill_bots(self, room, bots):
        for record in bots:
            camp = record.get('camp')
            if camp is None:
                camp = 1 if record.get('side') == 'allies' else 2
            _need(_integer(camp, 1, 2), 'invalid_camp', 'Phe bot không hợp lệ.')
            slot = self._empty_slot(room, camp)
            _need(slot is not None, 'room_full', 'Mỗi phe chỉ có tối đa 5 vị trí.')
            room['seats'][slot] = self._bot(room, record, slot)

    def register(self, profile_id, public, private=None, status='lobby'):
        _need(_integer(profile_id, 1), 'invalid_profile', 'Nhân vật không hợp lệ.')
        with self._guard:
            old = self._peers.get(profile_id)
            _need(old is None or not old['connected'], 'already_online', 'Nhân vật đang mở trong phiên khác.')
            generation = secrets.token_hex(12)
            self._sequence += 1
            peer = dict(profile_id=profile_id, generation=generation, public=_public(profile_id, public),
                        private=deepcopy(private or {}), status=str(status), connected=True,
                        events=deque(), requests=OrderedDict(), sequence=self._sequence, needs_resync=False)
            self._peers[profile_id] = peer
            room = self._rooms.get(self._membership.get(profile_id))
            if room:
                seat = next(s for s in self._human_seats(room) if s['account_id'] == profile_id)
                seat.update(connected=True, disconnected_at=None, grace_reported=False)
                if room['phase'] == 'waiting':
                    seat.update(public=deepcopy(peer['public']), private=deepcopy(peer['private']))
                self._broadcast(room, 'peer_reconnected', account_id=profile_id)
                self._changed(room, 'reconnected', profile_id)
            self._presence()
            return generation

    def update_peer(self, profile_id, generation, *, public=None, private=None, status=None):
        with self._guard:
            peer = self._peer(profile_id, generation)
            old = (peer['public'], peer['status'])
            if public is not None:
                peer['public'] = _merge_public(profile_id, peer['public'], public)
            if private is not None:
                peer['private'] = deepcopy(private)
            if status is not None:
                peer['status'] = str(status)
            room = self._rooms.get(self._membership.get(profile_id))
            if room and room['phase'] == 'waiting':
                seat = next(s for s in self._human_seats(room) if s['account_id'] == profile_id)
                changed = seat['public'] != peer['public']
                seat.update(public=deepcopy(peer['public']), private=deepcopy(peer['private']))
                if changed:
                    self._changed(room, 'member_changed', profile_id)
            if old != (peer['public'], peer['status']):
                self._presence()

    def update_waiting_player(self, profile_id, generation, *, public, private):
        """Commit an owned garage/loadout change against the waiting barrier.

        Unlike presence refresh, this operation must fail if selection won the
        race. The GATE stages its local state and only commits it after success.
        """
        with self._guard:
            peer = self._peer(profile_id, generation)
            room = self._room_for(profile_id)
            self._waiting(room, casual=True)
            _need(isinstance(public, dict) and isinstance(private, dict),
                  'invalid_profile', 'Cấu hình người chơi chưa hợp lệ.')
            updated_public = _merge_public(profile_id, peer['public'], public)
            updated_private = deepcopy(private)
            seat = next(s for s in self._human_seats(room) if s['account_id'] == profile_id)
            changed = seat['public'] != updated_public or seat['private'] != updated_private
            peer.update(public=updated_public, private=updated_private)
            seat.update(public=deepcopy(updated_public), private=deepcopy(updated_private))
            if changed:
                self._changed(room, 'member_changed', profile_id, reset_ready=True)
            return self._public_room(room)

    def unregister(self, profile_id, generation):
        with self._guard:
            peer = self._peers.get(profile_id)
            if peer is None or peer['generation'] != generation or not peer['connected']:
                return False
            peer['connected'] = False
            self._cancel_rank(profile_id)
            room = self._rooms.get(self._membership.get(profile_id))
            if room and room['phase'] == 'waiting':
                self._leave_waiting(profile_id, room, 'disconnected')
            elif room:
                seat = next(s for s in self._human_seats(room) if s['account_id'] == profile_id)
                seat.update(connected=False, disconnected_at=self._clock(), grace_reported=False)
                if room.get('start_claim') and room['start_claim']['coordinator_id'] == profile_id:
                    room['start_claim'] = None
                self._broadcast(room, 'peer_disconnected', account_id=profile_id,
                                grace_seconds=self.reconnect_grace)
                self._changed(room, 'disconnected', profile_id)
            for key, invitation in list(self._invites.items()):
                if profile_id in (invitation['from_id'], invitation['to_id']):
                    del self._invites[key]
                    self._emit(invitation['to_id'], 'invitation_changed', invite_id=key)
            self._presence()
            return True

    def create(self, profile_id, generation, config, bots=()):
        with self._guard:
            peer = self._peer(profile_id, generation)
            _need(self._available(peer), 'player_busy', 'Hãy rời phòng hoặc hàng chờ hiện tại trước.')
            room = self._new_room(config)
            camp = config.get('camp', 1)
            _need(_integer(camp, 1, 2), 'invalid_camp', 'Phe chủ phòng không hợp lệ.')
            slot = 0 if camp == 1 else 5
            room['owner_id'] = profile_id
            room['seats'][slot] = self._human(peer, slot, True)
            self._fill_bots(room, bots)
            self._rooms[room['room_id']] = room
            self._membership[profile_id] = room['room_id']
            self._changed(room, 'created', profile_id)
            return self._public_room(room)

    def join(self, profile_id, generation, code, camp=None):
        with self._guard:
            peer = self._peer(profile_id, generation)
            _need(self._available(peer), 'player_busy', 'Bạn đang ở trong phòng, trận hoặc hàng chờ.')
            _need(isinstance(code, str) and _CODE.fullmatch(code), 'invalid_code', 'Mã phòng phải gồm 6 chữ số.')
            room = self._rooms.get(int(code))
            _need(room is not None and not room['ranked'], 'room_missing', 'Không tìm thấy phòng chơi thường này.')
            self._waiting(room, casual=True)
            slot = self._join_slot(room, camp)
            room['seats'][slot] = self._human(peer, slot)
            self._membership[profile_id] = room['room_id']
            self._changed(room, 'joined', profile_id, reset_ready=True)
            return self._public_room(room)

    def _delete_room(self, room):
        self._rooms.pop(room['room_id'], None)
        for seat in self._human_seats(room):
            if self._membership.get(seat['account_id']) == room['room_id']:
                self._membership.pop(seat['account_id'], None)
        for key, invite in list(self._invites.items()):
            if invite['room_id'] == room['room_id']:
                del self._invites[key]
                self._emit(invite['to_id'], 'invitation_changed', invite_id=key)

    def _leave(self, profile_id, room, reason='left', actor_id=None):
        slot = next((s['slot'] for s in self._human_seats(room) if s['account_id'] == profile_id), None)
        _need(slot is not None, 'not_in_room', 'Bạn không thuộc phòng này.')
        room['seats'][slot] = None
        room['locked'].discard(profile_id)
        self._membership.pop(profile_id, None)
        self._emit(profile_id, 'room_left', room_id=room['room_id'], reason=reason,
                   actor_id=profile_id if actor_id is None else actor_id)
        remaining = self._human_seats(room)
        if not remaining:
            self._delete_room(room)
            self._presence()
            return
        if room['owner_id'] == profile_id:
            room['owner_id'] = min(remaining, key=lambda s: (s['joined'], s['slot']))['account_id']
        self._changed(room, reason, profile_id, reset_ready=True)

    def leave(self, profile_id, generation):
        with self._guard:
            self._peer(profile_id, generation)
            room = self._room_for(profile_id)
            self._waiting(room)
            self._leave_waiting(profile_id, room)

    def _leave_waiting(self, profile_id, room, reason='left'):
        if room['ranked']:
            self.close_room(room['room_id'], reason='rank_waiting_cancelled')
        else:
            self._leave(profile_id, room, reason)

    def detach(self, profile_id, generation=None, reason='left'):
        """Trusted adapter exit after the shared runtime's leave barrier.

        Ordinary JSON leave remains waiting-only. A deliberate exit during
        selection cancels that selection; ranked groups are dissolved before
        battle without pretending that a match was played. During battle the
        surviving actors keep their frozen runtime IDs until end_battle.
        """
        with self._guard:
            self._peer(profile_id, generation, connected=False)
            room = self._rooms.get(self._membership.get(profile_id))
            if room is None:
                return None
            room_id = room['room_id']
            if room['ranked'] and room['phase'] in ('waiting', 'selecting'):
                self.close_room(room_id, reason='rank_' + room['phase'] + '_cancelled')
                return None
            if room['phase'] == 'selecting':
                room.update(phase='waiting', selection_deadline=None, selection_id=None, start_claim=None,
                            locked=set(), runtime_ids=None)
                self._broadcast(room, 'selection_cancelled', account_id=profile_id,
                                reason=str(reason))
            self._leave(profile_id, room, str(reason))
            return self._public_room(self._rooms.get(room_id))

    def close_room(self, room_id, reason='closed'):
        """Trusted teardown; callers stop/settle any runtime before using it."""
        with self._guard:
            room = self._rooms.get(room_id)
            if room is None:
                return False
            if room['phase'] == 'selecting':
                self._broadcast(room, 'selection_cancelled', reason=str(reason))
            self._broadcast(room, 'room_left', reason=str(reason), actor_id=0)
            self._delete_room(room)
            self._presence()
            return True

    def _room_action(self, profile, request, *, bot=None):
        room = self._room_for(profile)
        self._waiting(room, casual=request['action'] not in ('leave',))
        action = request['action']
        if action == 'leave':
            self._leave_waiting(profile, room)
            return
        if 'revision' in request:
            self._revision(room, request['revision'])
        if action == 'ready':
            seat = next(s for s in self._human_seats(room) if s['account_id'] == profile)
            seat['ready'] = request['ready']
            self._changed(room, 'ready', profile)
            return
        if action == 'team':
            target = request.get('account_id', profile)
            if target != profile:
                self._owner(profile, room)
            seat = next((s for s in self._human_seats(room) if s['account_id'] == target), None)
            _need(seat is not None, 'member_missing', 'Người chơi không còn trong phòng.')
            if seat['camp'] == request['camp']:
                return
            slot = self._join_slot(room, request['camp'])
            room['seats'][seat['slot']] = None
            seat.update(slot=slot, camp=request['camp'])
            room['seats'][slot] = seat
            self._changed(room, 'team', target, reset_ready=True)
            return
        self._owner(profile, room)
        if action in ('kick', 'remove_bot'):
            slot = request['slot']
            seat = room['seats'][slot]
            _need(seat is not None and seat['account_id'] == request['expected_account_id'],
                  'occupant_changed', 'Vị trí này đã đổi người. Hãy kiểm tra lại.')
            if action == 'remove_bot':
                _need(seat['kind'] == 'bot', 'not_a_bot', 'Vị trí này đang có người chơi.')
                room['seats'][slot] = None
                self._changed(room, 'bot_removed', profile, reset_ready=True)
            else:
                _need(seat['kind'] == 'human' and seat['account_id'] != profile,
                      'invalid_kick', 'Chỉ có thể mời người chơi khác ra khỏi phòng.')
                self._leave(seat['account_id'], room, 'kicked', profile)
        elif action == 'add_bot':
            slot = self._empty_slot(room, request['camp'])
            _need(slot is not None, 'room_full', 'Phe này đã đủ 5 vị trí.')
            _need(isinstance(bot, dict) and bot.get('tank_level') == request['level'],
                  'bot_not_prepared', 'Server chưa chuẩn bị cấu hình bot.')
            room['seats'][slot] = self._bot(room, bot, slot)
            self._changed(room, 'bot_added', profile, reset_ready=True)
        elif action == 'bot_policy':
            room['config']['bot_ai_camps'][str(request['camp'])] = request['bot_ai']
            self._changed(room, 'bot_policy', profile, reset_ready=True)

    def _invite(self, profile, request):
        room = self._room_for(profile)
        self._waiting(room, casual=True)
        self._owner(profile, room)
        if 'revision' in request:
            self._revision(room, request['revision'])
        target = self._peer(request['account_id'])
        _need(target['profile_id'] != profile and self._available(target), 'player_busy',
              'Người chơi đang bận hoặc không thể nhận lời mời.')
        camp = request.get('camp')
        self._join_slot(room, camp)
        existing = next((v for v in self._invites.values() if v['room_id'] == room['room_id']
                         and v['to_id'] == target['profile_id']), None)
        if existing:
            return
        _need(sum(v['to_id'] == target['profile_id'] for v in self._invites.values()) < 10,
              'invite_limit', 'Người chơi đang có nhiều lời mời. Hãy thử lại sau.')
        ident = 'inv-' + secrets.token_hex(12)
        self._invites[ident] = dict(invite_id=ident, room_id=room['room_id'], code=room['code'],
                                    from_id=profile, from_name=self._peers[profile]['public']['name'],
                                    to_id=target['profile_id'], to_generation=target['generation'],
                                    camp=camp, expires=self._clock() + INVITE_SECONDS,
                                    expires_at_ms=int((self._wall() + INVITE_SECONDS) * 1000))
        self._emit(target['profile_id'], 'invitation_changed', invite_id=ident)

    def _invitation_action(self, profile, generation, request):
        invite = self._invites.get(request['invite_id'])
        _need(invite is not None and invite['to_id'] == profile and invite['to_generation'] == generation
              and invite['expires'] > self._clock(), 'invite_expired', 'Lời mời đã hết hạn hoặc không thuộc phiên này.')
        if request['action'] == 'accept':
            self.join(profile, generation, invite['code'], invite['camp'])
        del self._invites[invite['invite_id']]
        self._emit(profile, 'invitation_changed', invite_id=invite['invite_id'])

    def enqueue_rank(self, profile_id, generation):
        with self._guard:
            peer = self._peer(profile_id, generation)
            if profile_id in self._queue or profile_id in self._reserved:
                return
            _need(self._available(peer), 'player_busy', 'Hãy rời phòng hoặc trận hiện tại trước khi tìm rank.')
            self._queue[profile_id] = dict(profile_id=profile_id, generation=generation, queued=self._clock())
            self._emit(profile_id, 'queue_changed')
            self._presence()

    def _cancel_rank(self, profile_id):
        changed = self._queue.pop(profile_id, None) is not None
        reservation_id = self._reserved.pop(profile_id, None)
        if reservation_id is not None:
            reservation = self._reservations.pop(reservation_id, None)
            if reservation:
                for item in reservation['entries']:
                    other = item['profile_id']
                    self._reserved.pop(other, None)
                    if other != profile_id:
                        peer = self._peers.get(other)
                        if peer and peer['connected'] and peer['generation'] == item['generation']:
                            self._queue[other] = item
                            self._emit(other, 'queue_changed')
                changed = True
        if changed:
            self._emit(profile_id, 'queue_changed')
            self._presence()
        return changed

    def cancel_rank(self, profile_id, generation):
        with self._guard:
            self._peer(profile_id, generation)
            return self._cancel_rank(profile_id)

    def claim_rank_groups(self, profile_id=None, generation=None):
        """Atomically reserve opposing pairs; only a caller's groups if supplied.

        No rank_reserved event triggers a second builder. The returned group is
        the sole claim, and create_ranked consumes its reservation exactly once.
        """
        with self._guard:
            self._sweep()
            if profile_id is not None:
                self._peer(profile_id, generation)
            pending = sorted(self._queue.values(), key=lambda e: (e['queued'], e['profile_id']))
            proposed = [pending[i:i+2] for i in range(0, len(pending)-1, 2)]
            if len(pending) % 2 and self._clock() - pending[-1]['queued'] >= self.rank_wait:
                proposed.append([pending[-1]])
            result = []
            for entries in proposed:
                coordinator = entries[0]['profile_id']
                if profile_id is not None and coordinator != profile_id:
                    continue
                ident = 'rank-' + secrets.token_hex(12)
                reservation = dict(reservation_id=ident, account_ids=[e['profile_id'] for e in entries],
                                   coordinator_id=coordinator, solo=len(entries) == 1,
                                   entries=deepcopy(entries), created=self._clock())
                self._reservations[ident] = reservation
                for entry in entries:
                    account = entry['profile_id']
                    self._queue.pop(account, None)
                    self._reserved[account] = ident
                    self._emit(account, 'queue_changed')
                result.append({k: deepcopy(v) for k, v in reservation.items() if k != 'entries'})
            if result:
                self._presence()
            return result

    def create_ranked(self, reservation_id, config, bots=()):
        with self._guard:
            reservation = self._reservations.get(reservation_id)
            _need(reservation is not None, 'reservation_expired', 'Lượt ghép rank đã thay đổi.')
            peers = [self._peer(e['profile_id'], e['generation']) for e in reservation['entries']]
            _need(all(self._reserved.get(p['profile_id']) == reservation_id
                      and p['profile_id'] not in self._membership for p in peers),
                  'reservation_expired', 'Người chơi đã đổi trạng thái ghép rank.')
            room = self._new_room(config, ranked=True)
            room['owner_id'] = peers[0]['profile_id']
            for index, peer in enumerate(peers):
                slot = 0 if index == 0 else 5
                room['seats'][slot] = self._human(peer, slot, True)
            self._fill_bots(room, bots)
            self._rooms[room['room_id']] = room
            for peer in peers:
                profile = peer['profile_id']
                self._membership[profile] = room['room_id']
                self._reserved.pop(profile, None)
                self._emit(profile, 'queue_changed')
            del self._reservations[reservation_id]
            self._changed(room, 'rank_matched', room['owner_id'])
            return self._public_room(room)

    def release_rank_group(self, reservation_id):
        with self._guard:
            reservation = self._reservations.pop(reservation_id, None)
            if reservation is None:
                return False
            for entry in reservation['entries']:
                profile = entry['profile_id']
                self._reserved.pop(profile, None)
                peer = self._peers.get(profile)
                if peer and peer['connected'] and peer['generation'] == entry['generation']:
                    self._queue[profile] = entry
                    self._emit(profile, 'queue_changed')
            self._presence()
            return True

    def set_rank_policies(self, room_id, policies):
        """Trusted coordinator publishes both human camps' ranked AI policy.

        Read ratings from the room's trusted member snapshots before calling.
        Public room requests cannot select or override ranked difficulty.
        """
        with self._guard:
            room = self._rooms.get(room_id)
            _need(room is not None, 'room_missing', 'Không tìm thấy phòng rank.')
            _need(room['ranked'], 'ranked_required', 'Thao tác này chỉ áp dụng cho phòng rank.')
            self._waiting(room)
            _need(isinstance(policies, dict) and set(policies) == {'1', '2'}
                  and all(value in POLICIES for value in policies.values()),
                  'invalid_policy', 'Cần AI hợp lệ cho cả hai phe rank.')
            if room['config']['bot_ai_camps'] != policies:
                room['config']['bot_ai_camps'] = deepcopy(policies)
                self._changed(room, 'bot_policy')
            return self._public_room(room)

    def begin_selection(self, profile_id, generation, seconds=60):
        with self._guard:
            self._peer(profile_id, generation)
            room = self._room_for(profile_id)
            self._owner(profile_id, room)
            self._waiting(room)
            humans = self._human_seats(room)
            _need(any(room['seats'][:5]) and any(room['seats'][5:]), 'empty_team',
                  'Mỗi phe cần ít nhất một người hoặc bot để bắt đầu.')
            _need(all(s['connected'] and s['ready'] for s in humans), 'players_not_ready',
                  'Hãy chờ tất cả người chơi sẵn sàng.')
            _need(type(seconds) in (int, float) and 1 <= seconds <= 60, 'invalid_deadline', 'Thời gian chọn xe không hợp lệ.')
            room.update(phase='selecting', selection_deadline=self._clock() + seconds,
                        selection_id=secrets.token_hex(12), start_claim=None,
                        locked=set(), runtime_ids=self._runtime_ids(room))
            for seat in humans:
                seat['ready'] = False
            self._changed(room, 'selection_started', profile_id)
            self._broadcast(room, 'selection_started')
            return self._public_room(room)

    def select(self, profile_id, generation, *, public=None, private=None):
        with self._guard:
            peer = self._peer(profile_id, generation)
            room = self._room_for(profile_id)
            _need(room['phase'] == 'selecting' and not room['start_claim']
                  and profile_id not in room['locked'] and self._clock() < room['selection_deadline'],
                  'selection_locked', 'Lượt chọn xe đã được khóa.')
            if public is not None:
                peer['public'] = _merge_public(profile_id, peer['public'], public)
            if private is not None:
                peer['private'] = deepcopy(private)
            seat = next(s for s in self._human_seats(room) if s['account_id'] == profile_id)
            seat.update(public=deepcopy(peer['public']), private=deepcopy(peer['private']))
            self._changed(room, 'selection_changed', profile_id)
            self._broadcast(room, 'selection_changed', account_id=profile_id, locked=False)
            return self._public_room(room)

    def lock(self, profile_id, generation):
        with self._guard:
            self._peer(profile_id, generation)
            room = self._room_for(profile_id)
            _need(room['phase'] == 'selecting' and not room['start_claim'], 'selection_locked', 'Phòng đã khóa chọn xe.')
            if profile_id not in room['locked']:
                room['locked'].add(profile_id)
                next(s for s in self._human_seats(room) if s['account_id'] == profile_id)['ready'] = True
                self._changed(room, 'selection_locked', profile_id)
                self._broadcast(room, 'selection_changed', account_id=profile_id, locked=True)
            return self._public_room(room)

    def _selection_done(self, room):
        return (room['phase'] == 'selecting' and (self._clock() >= room['selection_deadline']
                or all(s['account_id'] in room['locked'] for s in self._human_seats(room))))

    def selection_done(self, room_id):
        with self._guard:
            room = self._rooms.get(room_id)
            return bool(room and self._selection_done(room))

    def claim_selection_starts(self, profile_id=None, generation=None):
        with self._guard:
            self._sweep()
            if profile_id is not None:
                self._peer(profile_id, generation)
            result = []
            for room in self._rooms.values():
                connected = sorted((s for s in self._human_seats(room) if s['connected']),
                                   key=lambda s: (s['account_id'] != room['owner_id'], s['joined'], s['slot']))
                if not connected or room['start_claim'] or not self._selection_done(room):
                    continue
                coordinator = connected[0]['account_id']
                if profile_id is not None and profile_id != coordinator:
                    continue
                claim = dict(room_id=room['room_id'], coordinator_id=coordinator,
                             claim_id='start-' + secrets.token_hex(12))
                room['start_claim'] = claim
                result.append(deepcopy(claim))
            return result

    def release_selection_claim(self, room_id, claim_id):
        with self._guard:
            room = self._rooms.get(room_id)
            if room and room['start_claim'] and room['start_claim']['claim_id'] == claim_id:
                room['start_claim'] = None
                return True
            return False

    def start_battle(self, room_id, claim_id=None):
        with self._guard:
            room = self._rooms.get(room_id)
            _need(room is not None and self._selection_done(room), 'selection_pending', 'Phòng chưa hoàn tất chọn xe.')
            if claim_id is not None:
                _need(room['start_claim'] and room['start_claim']['claim_id'] == claim_id,
                      'start_claim_changed', 'Lượt bắt đầu trận đã thay đổi.')
            room.update(phase='battle', start_claim=None)
            self._changed(room, 'battle_started')
            self._broadcast(room, 'battle_started')
            return self._room_data(room)

    def end_battle(self, room_id):
        with self._guard:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            room.update(phase='waiting', selection_deadline=None, selection_id=None, start_claim=None,
                        locked=set(), runtime_ids=None)
            for seat in list(self._human_seats(room)):
                if not seat['connected']:
                    self._leave(seat['account_id'], room, 'disconnected')
                    if room_id not in self._rooms:
                        return None
            self._changed(room, 'battle_ended', reset_ready=True)
            self._broadcast(room, 'battle_ended')
            return self._public_room(room)

    def _runtime_ids(self, room):
        seats = [s for s in room['seats'] if s]
        seats.sort(key=lambda s: (s['account_id'] != room['owner_id'], s['slot']))
        return {s['account_id']: index + 1 for index, s in enumerate(seats)}

    def _public_room(self, room):
        if room is None:
            return None
        seats = []
        for slot, seat in enumerate(room['seats']):
            common = dict(slot=slot, camp=1 if slot < 5 else 2, kind='empty', account_id=0,
                          name='', level=0, avatar_id=0, tank_id=0, tank_level=0, external_id=0,
                          ready=False, connected=False)
            if seat:
                common.update(seat['public'], kind=seat['kind'], ready=seat['ready'], connected=seat['connected'])
            seats.append(common)
        config = room['config']
        return dict(room_id=room['room_id'], code=room['code'], owner_id=room['owner_id'],
                    revision=room['revision'], phase=room['phase'], ranked=room['ranked'],
                    map_id=config['map_id'], mode=config['mode'], name=config['name'],
                    room_type=config['room_type'], bot_ai_camps=deepcopy(config['bot_ai_camps']),
                    seats=seats, human_count=sum(s['kind'] == 'human' for s in seats),
                    bot_count=sum(s['kind'] == 'bot' for s in seats))

    def _room_data(self, room):
        result = self._public_room(room)
        ids = room['runtime_ids'] or self._runtime_ids(room)
        owner_camp = next(s['camp'] for s in self._human_seats(room) if s['account_id'] == room['owner_id'])
        members, bots = [], []
        for seat in room['seats']:
            if not seat:
                continue
            common = dict(account_id=seat['account_id'], object_id=ids[seat['account_id']],
                          camp=seat['camp'], slot=seat['slot'], connected=seat['connected'])
            if seat['kind'] == 'human':
                members.append(dict(common, profile_id=seat['account_id'], public=deepcopy(seat['public']),
                                    private=deepcopy(seat['private'])))
            else:
                bot = deepcopy(seat['private'])
                bot.update(common, side='allies' if seat['camp'] == owner_camp else 'enemies')
                bots.append(bot)
        config = deepcopy(room['config'])
        config.update(owner_id=room['owner_id'], camp=owner_camp, state=int(room['phase'] != 'waiting'))
        result.update(host_id=room['owner_id'], config=config, members=members, bots=bots,
                      locked_ids=sorted(room['locked']), selection_deadline=room['selection_deadline'],
                      selection_id=room['selection_id'],
                      selection_remaining_ms=max(0, int((room['selection_deadline'] - self._clock()) * 1000))
                      if room['selection_deadline'] is not None else 0,
                      start_claimed=deepcopy(room['start_claim']))
        return result

    def room_data(self, room_id):
        with self._guard:
            room = self._rooms.get(room_id)
            return self._room_data(room) if room else None

    def room_for(self, profile_id, generation=None):
        with self._guard:
            if generation is not None:
                self._peer(profile_id, generation)
            room = self._rooms.get(self._membership.get(profile_id))
            return self._room_data(room) if room else None

    def list_rooms(self):
        with self._guard:
            return [self._public_room(room) for _, room in sorted(self._rooms.items())
                    if room['phase'] == 'waiting' and not room['ranked']]

    def _sweep(self):
        now = self._clock()
        for key, invitation in list(self._invites.items()):
            if invitation['expires'] <= now or invitation['room_id'] not in self._rooms:
                del self._invites[key]
                self._emit(invitation['to_id'], 'invitation_changed', invite_id=key)
        for profile, entry in list(self._queue.items()):
            peer = self._peers.get(profile)
            if not peer or not peer['connected'] or peer['generation'] != entry['generation']:
                self._queue.pop(profile, None)
        for ident, reservation in list(self._reservations.items()):
            if now - reservation['created'] > 30:
                self.release_rank_group(ident)
        for room in self._rooms.values():
            if room['phase'] not in ('selecting', 'battle'):
                continue
            for seat in self._human_seats(room):
                if (not seat['connected'] and seat['disconnected_at'] is not None
                        and not seat['grace_reported'] and now - seat['disconnected_at'] >= self.reconnect_grace):
                    seat['grace_reported'] = True
                    self._broadcast(room, 'peer_grace_expired', account_id=seat['account_id'])

    def _snapshot(self, peer, request_id='', action='status', ok=True, error=None):
        profile = peer['profile_id']
        room = self._rooms.get(self._membership.get(profile))
        online = []
        for account, other in sorted(self._peers.items()):
            if other['connected']:
                item = {k: v for k, v in other['public'].items() if k in ('account_id', 'name', 'level', 'avatar_id')}
                item.update(status=self._status(other), room_id=self._membership.get(account),
                            can_invite=self._available(other) and account != profile)
                online.append(item)
        invites = [{k: deepcopy(v) for k, v in inv.items() if k in
                    ('invite_id', 'room_id', 'code', 'from_id', 'from_name', 'camp', 'expires_at_ms')}
                   for inv in self._invites.values() if inv['to_id'] == profile and inv['to_generation'] == peer['generation']]
        queued = self._queue.get(profile)
        reserved = profile in self._reserved
        queue = dict(active=bool(queued or reserved), status='reserved' if reserved else 'waiting' if queued else 'idle',
                     wait_remaining_ms=max(0, int((self.rank_wait - (self._clock() - queued['queued'])) * 1000)) if queued else 0)
        result = dict(v=VERSION, request_id=request_id, action=action, ok=bool(ok), room=self._public_room(room),
                      online=online, invites=invites, queue=queue, server_time_ms=int(self._wall() * 1000))
        if error is not None:
            result['error'] = dict(code=error.code, message=str(error))
        return result

    def snapshot(self, profile_id, generation, request_id='', action='status'):
        with self._guard:
            self._sweep()
            return self._snapshot(self._peer(profile_id, generation), request_id, action)

    def drain(self, profile_id, generation, limit=MAX_PEER_EVENTS):
        with self._guard:
            self._sweep()
            peer = self._peer(profile_id, generation)
            result = []
            if peer['needs_resync']:
                result.append(dict(kind='resync_required'))
                peer['needs_resync'] = False
            for _ in range(min(max(int(limit), 0), MAX_PEER_EVENTS)):
                if not peer['events']:
                    break
                result.append(peer['events'].popleft())
            return result

    def command(self, profile_id, generation, request, *, config=None, bots=None, bot=None):
        request = validate_request(request)
        with self._guard:
            self._sweep()
            peer = self._peer(profile_id, generation)
            action, ident = request['action'], request['request_id']
            digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            previous = peer['requests'].get(ident)
            if previous:
                if previous['digest'] != digest:
                    return self._snapshot(peer, ident, action, False,
                                          RoomError('request_id_reused', 'Mã yêu cầu đã dùng cho thao tác khác.'))
                error = RoomError(previous['error']['code'], previous['error']['message']) if previous.get('error') else None
                return self._snapshot(peer, ident, action, previous['ok'], error)
            error = None
            try:
                if action in ('status', 'subscribe', 'online'):
                    pass
                elif action == 'create':
                    self.create(profile_id, generation, config, bots or ())
                elif action == 'join':
                    self.join(profile_id, generation, request['code'], request.get('camp'))
                elif action in ('leave', 'ready', 'team', 'kick', 'remove_bot', 'add_bot', 'bot_policy'):
                    self._room_action(profile_id, request, bot=bot)
                elif action == 'invite':
                    self._invite(profile_id, request)
                elif action in ('accept', 'decline'):
                    self._invitation_action(profile_id, generation, request)
                elif action == 'rank_queue':
                    self.enqueue_rank(profile_id, generation)
                elif action == 'rank_cancel':
                    self.cancel_rank(profile_id, generation)
            except RoomError as exc:
                error = exc
            result = self._snapshot(peer, ident, action, error is None, error)
            cached = dict(digest=digest, ok=result['ok'])
            if error:
                cached['error'] = result['error']
            peer['requests'][ident] = cached
            while len(peer['requests']) > 64:
                peer['requests'].popitem(last=False)
            return result


HUB = RoomHub()
