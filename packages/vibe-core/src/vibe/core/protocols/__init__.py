"""vibe.core.protocols — Typed protocol state machine framework.

This package implements the Ouroboros typed-protocols pattern: every
miniprotocol is a state machine where exactly one peer has agency at
each state.  Messages are typed transitions between states, and the
framework enforces agency rules at runtime.

Public API
----------
Agency, PeerRole, Message, Protocol, ProtocolError
    Core abstractions from :mod:`~vibe.core.protocols.agency`.
Peer
    Runtime protocol executor from :mod:`~vibe.core.protocols.peer`.
"""

from .agency import Agency, Message, PeerRole, Protocol, ProtocolError
from .peer import Peer

__all__ = [
    "Agency",
    "Message",
    "Peer",
    "PeerRole",
    "Protocol",
    "ProtocolError",
]
