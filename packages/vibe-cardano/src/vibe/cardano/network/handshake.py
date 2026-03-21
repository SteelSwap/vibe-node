"""Handshake miniprotocol CBOR message types (miniprotocol ID 0).

Implements the three handshake messages defined in the Ouroboros network
specification and the Haskell reference implementation
(``Ouroboros.Network.Protocol.Handshake.Codec``):

* **MsgProposeVersions** — client proposes a version table to the server
* **MsgAcceptVersion** — server accepts a mutually supported version
* **MsgRefuse** — server refuses the handshake with a typed reason

Wire format references:
    - ``codecHandshake`` in ``Ouroboros.Network.Protocol.Handshake.Codec``
    - ``nodeToNodeCodecCBORTerm`` in ``Ouroboros.Network.NodeToNode.Version``
    - ``nodeToNodeVersionCodec`` in ``Ouroboros.Network.NodeToNode.Version``
    - ``encodeRefuseReason`` / ``decodeRefuseReason`` in the same Codec module

Version data encoding (N2N V14+):
    ``[networkMagic :: uint32, initiatorOnly :: bool, peerSharing :: uint8, query :: bool]``
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Union

import cbor2

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HANDSHAKE_PROTOCOL_ID: int = 0
"""Handshake is always miniprotocol number 0."""

HANDSHAKE_TIMEOUT_S: float = 10.0
"""SDU timeout for the handshake miniprotocol (spec-mandated 10 s)."""

# Well-known network magic values.
MAINNET_NETWORK_MAGIC: int = 764824073
PREPROD_NETWORK_MAGIC: int = 1
PREVIEW_NETWORK_MAGIC: int = 2

# Current node-to-node protocol versions supported by the Haskell node.
# Reference: ``NodeToNodeVersion`` data type in
# ``ouroboros-network-api/src/Ouroboros/Network/NodeToNode/Version.hs``
# As of ouroboros-network-0.22, only V14 and V15 are active.
N2N_V14: int = 14
N2N_V15: int = 15

# CBOR message tags (first element of the outer list).
_MSG_PROPOSE_VERSIONS: int = 0
_MSG_ACCEPT_VERSION: int = 1
_MSG_REFUSE: int = 2

# Refuse-reason sub-tags (first element of the reason list).
_REFUSE_VERSION_MISMATCH: int = 0
_REFUSE_DECODE_ERROR: int = 1
_REFUSE_REFUSED: int = 2


# ---------------------------------------------------------------------------
# Peer-sharing enum
# ---------------------------------------------------------------------------


class PeerSharing(enum.IntEnum):
    """Peer sharing mode negotiated during handshake.

    Reference: ``PeerSharing`` in ``Ouroboros.Network.PeerSelection.PeerSharing``
    V14+ codec uses 0 = disabled, 1 = enabled.
    """

    DISABLED = 0
    ENABLED = 1


# ---------------------------------------------------------------------------
# Version data
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NodeToNodeVersionData:
    """Parameters carried alongside each proposed version number.

    Encoding (V14+): ``[networkMagic, initiatorOnly, peerSharing, query]``
    Reference: ``nodeToNodeCodecCBORTerm`` in
    ``Ouroboros.Network.NodeToNode.Version``
    """

    network_magic: int
    """Network discriminator (e.g. 764824073 for mainnet)."""

    initiator_only_diffusion_mode: bool = False
    """True  -> InitiatorOnlyDiffusionMode (no responder).
    False -> InitiatorAndResponderDiffusionMode."""

    peer_sharing: PeerSharing = PeerSharing.DISABLED
    """Whether this node participates in peer sharing."""

    query: bool = False
    """Query flag — when True the initiator only wants to query, not sync."""


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MsgProposeVersions:
    """Client -> Server: propose a set of versions with their parameters.

    Wire format: ``[0, {versionNumber: versionData, ...}]``
    The version table is a CBOR map keyed by integer version numbers.
    """

    version_table: dict[int, NodeToNodeVersionData]


@dataclass(frozen=True, slots=True)
class MsgAcceptVersion:
    """Server -> Client: accept a mutually supported version.

    Wire format: ``[1, versionNumber, versionData]``
    """

    version_number: int
    version_data: NodeToNodeVersionData


@dataclass(frozen=True, slots=True)
class RefuseReasonVersionMismatch:
    """No common version.  Wire: ``[0, [versionNumbers...]]``."""

    versions: list[int]


@dataclass(frozen=True, slots=True)
class RefuseReasonHandshakeDecodeError:
    """Decode error for a specific version.  Wire: ``[1, versionNumber, msg]``."""

    version_number: int
    message: str


@dataclass(frozen=True, slots=True)
class RefuseReasonRefused:
    """Explicit refusal for a version.  Wire: ``[2, versionNumber, msg]``."""

    version_number: int
    message: str


RefuseReason = Union[
    RefuseReasonVersionMismatch,
    RefuseReasonHandshakeDecodeError,
    RefuseReasonRefused,
]


@dataclass(frozen=True, slots=True)
class MsgRefuse:
    """Server -> Client: refuse the handshake.

    Wire format: ``[2, reason]``
    """

    reason: RefuseReason


HandshakeResponse = Union[MsgAcceptVersion, MsgRefuse]


# ---------------------------------------------------------------------------
# Version-data encoding helpers
# ---------------------------------------------------------------------------


def _encode_version_data(vd: NodeToNodeVersionData) -> list:
    """Encode ``NodeToNodeVersionData`` to a CBOR-serialisable list.

    Reference: ``encodeTerm`` inside ``nodeToNodeCodecCBORTerm`` (V14+ branch).
    """
    return [
        vd.network_magic,
        vd.initiator_only_diffusion_mode,
        int(vd.peer_sharing),
        vd.query,
    ]


def _decode_version_data(term: list) -> NodeToNodeVersionData:
    """Decode a CBOR list back to ``NodeToNodeVersionData``.

    Reference: ``decodeTerm`` inside ``nodeToNodeCodecCBORTerm`` (V14+ branch).

    Raises:
        ValueError: If the term structure is invalid.
    """
    if not isinstance(term, list) or len(term) != 4:
        raise ValueError(f"Expected list of 4 elements, got: {term!r}")

    network_magic = term[0]
    if not isinstance(network_magic, int) or network_magic < 0 or network_magic > 0xFFFFFFFF:
        raise ValueError(f"networkMagic out of bound: {network_magic}")

    initiator_only = term[1]
    if not isinstance(initiator_only, bool):
        raise ValueError(f"Expected bool for initiatorOnly, got: {initiator_only!r}")

    peer_sharing_raw = term[2]
    if not isinstance(peer_sharing_raw, int) or peer_sharing_raw not in (0, 1):
        raise ValueError(f"peerSharing out of bound: {peer_sharing_raw}")

    query = term[3]
    if not isinstance(query, bool):
        raise ValueError(f"Expected bool for query, got: {query!r}")

    return NodeToNodeVersionData(
        network_magic=network_magic,
        initiator_only_diffusion_mode=initiator_only,
        peer_sharing=PeerSharing(peer_sharing_raw),
        query=query,
    )


# ---------------------------------------------------------------------------
# Public API — building version tables
# ---------------------------------------------------------------------------


def build_version_table(
    network_magic: int,
    *,
    initiator_only: bool = False,
    peer_sharing: PeerSharing = PeerSharing.DISABLED,
    query: bool = False,
) -> dict[int, NodeToNodeVersionData]:
    """Build a version table with current N2N versions (V14, V15).

    This is the table a client sends inside ``MsgProposeVersions``.

    Args:
        network_magic: The network discriminator (e.g. ``MAINNET_NETWORK_MAGIC``).
        initiator_only: Whether to run in initiator-only diffusion mode.
        peer_sharing: Peer sharing preference.
        query: Whether this is a query-only connection.

    Returns:
        A dict mapping version numbers to ``NodeToNodeVersionData``.
    """
    vd = NodeToNodeVersionData(
        network_magic=network_magic,
        initiator_only_diffusion_mode=initiator_only,
        peer_sharing=peer_sharing,
        query=query,
    )
    return {N2N_V14: vd, N2N_V15: vd}


# ---------------------------------------------------------------------------
# Public API — CBOR encoding
# ---------------------------------------------------------------------------


def encode_propose_versions(versions: dict[int, NodeToNodeVersionData]) -> bytes:
    """Encode a ``MsgProposeVersions`` message to CBOR bytes.

    Wire format (from ``codecHandshake``):
        ``[0, {versionNumber: versionData, ...}]``

    The version table is a CBOR **map** whose keys are integer version
    numbers and whose values are the encoded version-data lists.

    Args:
        versions: Mapping from version number to version data.

    Returns:
        CBOR-encoded bytes ready for multiplexer framing.
    """
    # Build the CBOR map: {int -> list}
    # Keys must be sorted (CBOR canonical / deterministic) to match Haskell's
    # Map.toAscList serialisation order.
    version_map = {k: _encode_version_data(v) for k, v in sorted(versions.items())}
    msg = [_MSG_PROPOSE_VERSIONS, version_map]
    return cbor2.dumps(msg)


def encode_accept_version(accept: MsgAcceptVersion) -> bytes:
    """Encode a ``MsgAcceptVersion`` message to CBOR bytes.

    Wire format: ``[1, versionNumber, versionData]``
    """
    ver_data = _encode_version_data(accept.version_data)
    msg = [_MSG_ACCEPT_VERSION, accept.version_number, ver_data]
    return cbor2.dumps(msg)


def encode_refuse(refuse: MsgRefuse) -> bytes:
    """Encode a ``MsgRefuse`` message to CBOR bytes.

    Wire format: ``[2, [reason_tag, ...]]``
    """
    reason = refuse.reason
    if isinstance(reason, RefuseReasonVersionMismatch):
        reason_term = [_REFUSE_VERSION_MISMATCH, reason.versions]
    elif isinstance(reason, RefuseReasonDecodeError):
        reason_term = [_REFUSE_DECODE_ERROR, reason.version, reason.message]
    elif isinstance(reason, RefuseReasonRefused):
        reason_term = [_REFUSE_REFUSED, reason.version, reason.message]
    else:
        raise ValueError(f"Unknown refuse reason: {reason!r}")
    msg = [_MSG_REFUSE, reason_term]
    return cbor2.dumps(msg)


# ---------------------------------------------------------------------------
# Public API — CBOR decoding
# ---------------------------------------------------------------------------


def _decode_refuse_reason(reason_term: list) -> RefuseReason:
    """Decode a refuse-reason CBOR term.

    Reference: ``decodeRefuseReason`` in
    ``Ouroboros.Network.Protocol.Handshake.Codec``
    """
    if not isinstance(reason_term, list) or len(reason_term) < 2:
        raise ValueError(f"Invalid refuse reason: {reason_term!r}")

    tag = reason_term[0]

    if tag == _REFUSE_VERSION_MISMATCH:
        # [0, [versionNumbers...]]
        if len(reason_term) != 2:
            raise ValueError(f"VersionMismatch expects 2 elements, got {len(reason_term)}")
        version_list = reason_term[1]
        if not isinstance(version_list, list):
            raise ValueError(f"Expected list of versions, got: {version_list!r}")
        return RefuseReasonVersionMismatch(versions=version_list)

    elif tag == _REFUSE_DECODE_ERROR:
        # [1, versionNumber, errorMessage]
        if len(reason_term) != 3:
            raise ValueError(
                f"HandshakeDecodeError expects 3 elements, got {len(reason_term)}"
            )
        return RefuseReasonHandshakeDecodeError(
            version_number=reason_term[1],
            message=reason_term[2],
        )

    elif tag == _REFUSE_REFUSED:
        # [2, versionNumber, errorMessage]
        if len(reason_term) != 3:
            raise ValueError(f"Refused expects 3 elements, got {len(reason_term)}")
        return RefuseReasonRefused(
            version_number=reason_term[1],
            message=reason_term[2],
        )

    else:
        raise ValueError(f"Unknown refuse reason tag: {tag}")


def decode_handshake_response(cbor_bytes: bytes) -> HandshakeResponse:
    """Decode a server handshake response (``MsgAcceptVersion`` or ``MsgRefuse``).

    Wire formats:
        - AcceptVersion: ``[1, versionNumber, versionData]``
        - Refuse:        ``[2, reason]``

    Args:
        cbor_bytes: Raw CBOR bytes of the response message.

    Returns:
        Either ``MsgAcceptVersion`` or ``MsgRefuse``.

    Raises:
        ValueError: If the message tag is unrecognised or structure is invalid.
    """
    decoded = cbor2.loads(cbor_bytes)
    if not isinstance(decoded, list) or len(decoded) < 2:
        raise ValueError(f"Expected CBOR list with >= 2 elements, got: {decoded!r}")

    tag = decoded[0]

    if tag == _MSG_ACCEPT_VERSION:
        # [1, versionNumber, versionData]
        if len(decoded) != 3:
            raise ValueError(
                f"MsgAcceptVersion expects list of 3, got {len(decoded)}"
            )
        version_number = decoded[1]
        version_data = _decode_version_data(decoded[2])
        return MsgAcceptVersion(
            version_number=version_number,
            version_data=version_data,
        )

    elif tag == _MSG_REFUSE:
        # [2, reason]
        if len(decoded) != 2:
            raise ValueError(f"MsgRefuse expects list of 2, got {len(decoded)}")
        reason = _decode_refuse_reason(decoded[1])
        return MsgRefuse(reason=reason)

    else:
        raise ValueError(
            f"Expected MsgAcceptVersion (tag=1) or MsgRefuse (tag=2), got tag={tag}"
        )
