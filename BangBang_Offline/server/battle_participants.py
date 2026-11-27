"""Human ownership and recipient metadata at the native combat boundary.

Recipients are actor IDs assigned by the room authority, never client input.
Packets remain ordinary two-item tuples for the legacy single-player path.
The shared service removes metadata before presentation/framing.
"""
import struct


def human(actor):
    return bool(not actor.info.get('npc_template')
                and actor.info.get('human', actor.id == 1))


class TargetedPacket(tuple):
    def __new__(cls, mid, body, *, viewers=None, exclude=()):
        packet = tuple.__new__(cls, (mid, body))
        packet.viewers = None if viewers is None else frozenset(viewers)
        packet.exclude = frozenset(exclude)
        return packet


def private(actor, packet):
    return TargetedPacket(*packet, viewers=(actor.id,))


def other_viewers(actor, packet):
    return TargetedPacket(*packet, exclude=(actor.id,))


def friendly(actor, packet):
    """Hidden traps are visible only to the placing actor's own camp."""
    if actor.arena.state.get('multiplayer_players'):
        return [TargetedPacket(*packet, viewers=(a.id for a in actor.arena.actors.values()
                                                  if human(a) and a.camp == actor.camp))]
    return [packet] if actor.camp == actor.arena.player.camp else []


def for_viewer(packets, actor):
    result = []
    for packet in packets:
        viewers = getattr(packet, 'viewers', None)
        if (viewers is not None and actor.id not in viewers) or actor.id in getattr(packet, 'exclude', ()):
            continue
        mid, body = packet
        # Existing kits use the native local-slot form for actor 1. Every
        # other human already receives the equivalent explicit-owner form.
        if mid == 1579:
            owner = struct.unpack_from('<I', body, 22)[0] if len(body) >= 26 else 1
            mid, body = 1572, body[:22] + struct.pack('<I', owner)
        # Untagged local-only legacy packets belong to the canonical host.
        if mid in (1581, 1585, 1588, 1590) and viewers is None and actor.id != 1:
            continue
        if mid == 1550 and struct.unpack_from('<I', body)[0] != actor.id:
            continue
        result.append((mid, body))
    return result
