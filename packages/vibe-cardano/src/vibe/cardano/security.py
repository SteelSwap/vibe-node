"""Security hardening utilities for CBOR decoding and protocol messages.

Defense-in-depth against malformed or adversarial network payloads:
- Size limits on CBOR payloads before any decoding occurs
- Depth limits to prevent stack exhaustion from deeply nested structures
- Protocol message type validation to reject unexpected message types early

Haskell ref:
    Ouroboros.Network.Protocol.* -- each miniprotocol codec rejects
    unexpected message types; the Haskell CBOR decoder (cborg) limits
    nesting depth internally.

Spec ref:
    No single spec section -- this is cross-cutting defensive coding
    that applies to all network-facing CBOR decoding paths.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import cbor2pure

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CBOR_SIZE: int = 64 * 1024 * 1024  # 64 MB
"""Maximum CBOR payload size we will attempt to decode.

Blocks on Cardano mainnet are at most ~90 KB; 64 MB provides generous
headroom while still rejecting obviously malicious multi-gigabyte payloads
before any parsing work is done.
"""

MAX_CBOR_DEPTH: int = 256
"""Maximum nesting depth for CBOR structures.

Deeply nested arrays/maps can cause stack exhaustion during recursive
decoding.  256 levels is far beyond any legitimate Cardano structure
while still catching adversarial payloads.
"""

MAX_ARRAY_LENGTH: int = 65536
"""Maximum number of elements in a single CBOR array/map we consider sane.

Used as a reference constant for downstream validators; not enforced
directly by safe_cbor_loads (cbor2pure doesn't expose per-collection
limits), but callers can check after decoding.
"""


# ---------------------------------------------------------------------------
# Safe CBOR decoding
# ---------------------------------------------------------------------------


def _check_depth(obj: Any, max_depth: int, _current: int = 0) -> None:
    """Recursively verify that *obj* does not exceed *max_depth* nesting.

    Raises ``cbor2pure.CBORDecodeError`` if the depth limit is exceeded,
    matching the exception type callers would expect from CBOR decoding
    failures.
    """
    if _current > max_depth:
        raise cbor2pure.CBORDecodeError(
            f"CBOR nesting depth exceeds limit of {max_depth}"
        )
    if isinstance(obj, (list, tuple)):
        for item in obj:
            _check_depth(item, max_depth, _current + 1)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _check_depth(k, max_depth, _current + 1)
            _check_depth(v, max_depth, _current + 1)
    elif isinstance(obj, cbor2pure.CBORTag):
        _check_depth(obj.value, max_depth, _current + 1)


def safe_cbor_loads(
    data: bytes | bytearray | memoryview,
    *,
    max_size: int = MAX_CBOR_SIZE,
    max_depth: int = MAX_CBOR_DEPTH,
) -> Any:
    """Decode CBOR with size and depth limits.

    This is the **only** CBOR decoding entry point that should be used for
    data received from the network.  It applies two checks:

    1. **Pre-decode size check** -- rejects payloads larger than *max_size*
       bytes before any parsing occurs.  This is O(1) and prevents
       allocation of large internal buffers.

    2. **Post-decode depth check** -- walks the decoded object tree and
       raises ``cbor2pure.CBORDecodeError`` if nesting exceeds *max_depth*.
       cbor2pure does not expose a native depth parameter, so we enforce
       it ourselves after decoding.

    Parameters
    ----------
    data:
        Raw CBOR bytes to decode.
    max_size:
        Maximum allowed byte length.  Defaults to :data:`MAX_CBOR_SIZE`.
    max_depth:
        Maximum allowed nesting depth.  Defaults to :data:`MAX_CBOR_DEPTH`.

    Returns
    -------
    Any
        The decoded Python object.

    Raises
    ------
    ValueError
        If ``len(data)`` exceeds *max_size*.
    cbor2pure.CBORDecodeError
        If the CBOR is malformed or nesting exceeds *max_depth*.
    """
    payload_len = len(data)
    if payload_len > max_size:
        raise ValueError(
            f"CBOR payload size {payload_len} bytes exceeds limit of {max_size} bytes"
        )

    decoded = cbor2pure.loads(data)

    _check_depth(decoded, max_depth)

    return decoded


# ---------------------------------------------------------------------------
# Protocol message validation
# ---------------------------------------------------------------------------


def validate_protocol_message(
    msg: Any,
    expected_types: Sequence[type],
) -> Any | None:
    """Return *msg* if it is an instance of one of *expected_types*, else ``None``.

    This is a thin guard placed at miniprotocol codec boundaries.  If a peer
    sends a message of an unexpected type -- whether through a bug or a
    deliberate attack -- we log a warning and return ``None`` so the caller
    can handle the mismatch gracefully (typically by closing the connection).

    Parameters
    ----------
    msg:
        The decoded protocol message object.
    expected_types:
        Sequence of types that are acceptable at this point in the protocol.

    Returns
    -------
    The original *msg* if its type matches, or ``None`` with a logged warning.
    """
    if isinstance(msg, tuple(expected_types)):
        return msg

    logger.warning(
        "Unexpected protocol message type %s; expected one of %s",
        type(msg).__name__,
        [t.__name__ for t in expected_types],
    )
    return None
