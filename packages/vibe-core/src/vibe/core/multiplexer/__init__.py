"""vibe.core.multiplexer — Ouroboros network multiplexer.

Implements the multiplexer wire format (segment framing) and async TCP
bearer as defined in the Ouroboros network specification, Section 1.1
"Wire Format".

Spec source: IntersectMBO/ouroboros-network, docs/network-spec/mux.tex
Haskell ref: Network.Mux.Codec (encodeSDU / decodeSDUHeader)
             Network.Mux.Bearer.Socket (socketAsBearer)
"""

from vibe.core.multiplexer.bearer import (
    Bearer,
    BearerClosedError,
    BearerError,
    connect,
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
    "MuxSegment",
    "SEGMENT_HEADER_SIZE",
    "connect",
    "decode_segment",
    "encode_segment",
]
