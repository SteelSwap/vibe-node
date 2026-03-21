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
Codec, CodecError
    Message serialization abstraction from :mod:`~vibe.core.protocols.codec`.
ProtocolRunner
    Drives a protocol state machine over a mux channel,
    from :mod:`~vibe.core.protocols.runner`.
PipelinedRunner
    Sends multiple requests without waiting for responses,
    from :mod:`~vibe.core.protocols.pipelining`.
"""

from .agency import Agency, Message, PeerRole, Protocol, ProtocolError
from .codec import Codec, CodecError
from .peer import Peer
from .pipelining import PipelinedRunner
from .runner import ProtocolRunner

__all__ = [
    "Agency",
    "Codec",
    "CodecError",
    "Message",
    "Peer",
    "PeerRole",
    "PipelinedRunner",
    "Protocol",
    "ProtocolError",
    "ProtocolRunner",
]
