"""vibe.core.multiplexer — Ouroboros network multiplexer.

Implements the multiplexer wire format (segment framing), async TCP
bearer, and multiplexer/demultiplexer as defined in the Ouroboros
network specification, Chapter 1 "Multiplexing mini-protocols".

Spec source: IntersectMBO/ouroboros-network, docs/network-spec/mux.tex
Haskell ref: Network.Mux.Codec (encodeSDU / decodeSDUHeader)
             Network.Mux.Bearer.Socket (socketAsBearer)
             Network.Mux (runMux, muxChannel)
"""

from vibe.core.multiplexer.bearer import (
    Bearer,
    BearerClosedError,
    BearerError,
    connect,
)
from vibe.core.multiplexer.mux import (
    IngressOverflowError,
    MiniProtocolChannel,
    Multiplexer,
    MuxClosedError,
    MuxError,
)
from vibe.core.multiplexer.segment import (
    MAX_PAYLOAD_SIZE,
    SEGMENT_HEADER_SIZE,
    MuxSegment,
    decode_segment,
    encode_segment,
)

__all__ = [
    "Bearer",
    "BearerClosedError",
    "BearerError",
    "MAX_PAYLOAD_SIZE",
    "MiniProtocolChannel",
    "Multiplexer",
    "IngressOverflowError",
    "MuxClosedError",
    "MuxError",
    "MuxSegment",
    "SEGMENT_HEADER_SIZE",
    "connect",
    "decode_segment",
    "encode_segment",
]
