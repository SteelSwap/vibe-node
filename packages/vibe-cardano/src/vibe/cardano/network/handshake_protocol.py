"""Handshake miniprotocol FSM and version negotiation logic.

Implements the handshake as a typed protocol using the vibe.core.protocols
framework, following the Haskell reference implementation:

* ``Ouroboros.Network.Protocol.Handshake.Type`` — states and messages
* ``Ouroboros.Network.Protocol.Handshake.Client`` — client peer
* ``Ouroboros.Network.Protocol.Handshake.Direct`` — pureHandshake

**State machine:**

    StPropose (Client agency)
        |
        | MsgProposeVersions
        v
    StConfirm (Server agency)
        |
        +-- MsgAcceptVersion --> StDone (Nobody)
        |
        +-- MsgRefuse --------> StDone (Nobody)

**Version negotiation** (from ``pureHandshake``):
    The server intersects its known versions with the client's proposed
    versions, picks the **highest common version** (Map.toDescList), then
    calls ``acceptVersion`` to merge the version data from both sides.
    If no common version exists, it sends ``MsgRefuse(VersionMismatch)``.
"""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass
from typing import Protocol as TypingProtocol

from vibe.core.protocols import Agency, Message, Protocol

from .handshake import (
    HANDSHAKE_TIMEOUT_S,
    HandshakeResponse,
    MsgAcceptVersion,
    MsgProposeVersions,
    MsgRefuse,
    NodeToClientVersionData,
    NodeToNodeVersionData,
    RefuseReasonVersionMismatch,
    _decode_n2c_version_data,
    build_n2c_version_table,
    build_version_table,
    decode_handshake_response,
    encode_n2c_accept_version,
    encode_propose_versions,
    encode_refuse,
)

__all__ = [
    "HandshakeState",
    "HandshakeProtocol",
    "HandshakeError",
    "HandshakeRefusedError",
    "MsgProposeVersionsMsg",
    "MsgAcceptVersionMsg",
    "MsgRefuseMsg",
    "run_handshake_client",
    "run_handshake_server",
    "run_handshake_server_n2c",
]


# ---------------------------------------------------------------------------
# Protocol states
# ---------------------------------------------------------------------------


class HandshakeState(enum.Enum):
    """States of the handshake miniprotocol.

    Reference: ``Handshake`` data type in
    ``Ouroboros.Network.Protocol.Handshake.Type``
    """

    StPropose = "propose"
    """Initial state. Client has agency — sends MsgProposeVersions."""

    StConfirm = "confirm"
    """Server has agency — responds with MsgAcceptVersion or MsgRefuse."""

    StDone = "done"
    """Terminal state. Nobody has agency. Protocol complete."""


# ---------------------------------------------------------------------------
# Protocol messages (typed transitions)
# ---------------------------------------------------------------------------


class MsgProposeVersionsMsg(Message[HandshakeState]):
    """Transition: StPropose -> StConfirm.

    Client sends its version table to the server.
    """

    __slots__ = ("propose",)

    def __init__(self, propose: MsgProposeVersions) -> None:
        super().__init__(HandshakeState.StPropose, HandshakeState.StConfirm)
        self.propose = propose


class MsgAcceptVersionMsg(Message[HandshakeState]):
    """Transition: StConfirm -> StDone.

    Server accepts a mutually supported version.
    """

    __slots__ = ("accept",)

    def __init__(self, accept: MsgAcceptVersion) -> None:
        super().__init__(HandshakeState.StConfirm, HandshakeState.StDone)
        self.accept = accept


class MsgRefuseMsg(Message[HandshakeState]):
    """Transition: StConfirm -> StDone.

    Server refuses the handshake.
    """

    __slots__ = ("refuse",)

    def __init__(self, refuse: MsgRefuse) -> None:
        super().__init__(HandshakeState.StConfirm, HandshakeState.StDone)
        self.refuse = refuse


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------


class HandshakeProtocol(Protocol[HandshakeState]):
    """Handshake miniprotocol state machine.

    Three states, two transitions from StConfirm (accept or refuse).
    The handshake is always miniprotocol number 0 and must complete
    within the spec-mandated 10 second timeout.

    Reference: ``Handshake`` type class instances in
    ``Ouroboros.Network.Protocol.Handshake.Type``
    """

    def initial_state(self) -> HandshakeState:
        return HandshakeState.StPropose

    def agency(self, state: HandshakeState) -> Agency:
        match state:
            case HandshakeState.StPropose:
                return Agency.Client
            case HandshakeState.StConfirm:
                return Agency.Server
            case HandshakeState.StDone:
                return Agency.Nobody
        raise ValueError(f"Unknown handshake state: {state}")  # pragma: no cover

    def valid_messages(
        self, state: HandshakeState
    ) -> frozenset[type[Message[HandshakeState]]]:
        match state:
            case HandshakeState.StPropose:
                return frozenset({MsgProposeVersionsMsg})
            case HandshakeState.StConfirm:
                return frozenset({MsgAcceptVersionMsg, MsgRefuseMsg})
            case HandshakeState.StDone:
                return frozenset()
        raise ValueError(f"Unknown handshake state: {state}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class HandshakeError(Exception):
    """Base exception for handshake failures."""


class HandshakeRefusedError(HandshakeError):
    """Raised when the server refuses the handshake."""

    def __init__(self, refuse: MsgRefuse) -> None:
        self.refuse = refuse
        super().__init__(f"Handshake refused: {refuse.reason}")


class HandshakeTimeoutError(HandshakeError):
    """Raised when the handshake exceeds the spec-mandated timeout."""


# ---------------------------------------------------------------------------
# Channel protocol — abstract byte-level I/O
# ---------------------------------------------------------------------------


class Channel(TypingProtocol):
    """Minimal async channel for sending/receiving raw bytes.

    In production this wraps the multiplexer's sub-channel for
    miniprotocol 0. For testing, a simple asyncio.Queue pair suffices.
    """

    async def send(self, data: bytes) -> None: ...
    async def recv(self) -> bytes: ...


# ---------------------------------------------------------------------------
# Version negotiation (pure logic)
# ---------------------------------------------------------------------------


def negotiate_version(
    client_versions: dict[int, NodeToNodeVersionData],
    server_versions: dict[int, NodeToNodeVersionData],
) -> MsgAcceptVersion | None:
    """Pure version negotiation — select highest common version.

    Mirrors ``pureHandshake`` from
    ``Ouroboros.Network.Protocol.Handshake.Direct``:

        Map.toDescList $ serverVersions `Map.intersection` clientVersions

    The highest version number present in both maps wins. Version data
    is taken from the server's perspective (the server's version data
    for the negotiated version number).

    For N2N, the ``acceptVersion`` function in the Haskell implementation
    checks that network magic matches and merges diffusion mode / peer
    sharing settings. We enforce network magic equality here.

    Args:
        client_versions: Client's proposed version table.
        server_versions: Server's known version table.

    Returns:
        ``MsgAcceptVersion`` if a common version is found, ``None`` otherwise.
    """
    # Intersection: versions present in both tables
    common = set(client_versions.keys()) & set(server_versions.keys())
    if not common:
        return None

    # Highest common version (Map.toDescList picks the first = highest)
    best = max(common)

    client_data = client_versions[best]
    server_data = server_versions[best]

    # Network magic must match (Haskell's acceptVersion checks this)
    if client_data.network_magic != server_data.network_magic:
        return None

    # Merge version data following Haskell's nodeToNodeVersionDataCodec:
    # - network_magic: must be equal (checked above), use server's
    # - initiator_only: OR of both (if either is initiator-only, connection
    #   is unidirectional)
    # - peer_sharing: use server's preference (server decides)
    # - query: use client's (client is the one requesting query mode)
    from .handshake import PeerSharing

    merged_data = NodeToNodeVersionData(
        network_magic=server_data.network_magic,
        initiator_only_diffusion_mode=(
            client_data.initiator_only_diffusion_mode
            or server_data.initiator_only_diffusion_mode
        ),
        peer_sharing=server_data.peer_sharing,
        query=client_data.query,
    )

    return MsgAcceptVersion(version_number=best, version_data=merged_data)


# ---------------------------------------------------------------------------
# Client-side handshake runner
# ---------------------------------------------------------------------------


async def run_handshake_client(
    channel: Channel,
    network_magic: int,
    *,
    timeout: float = HANDSHAKE_TIMEOUT_S,
) -> MsgAcceptVersion:
    """Run the client side of the handshake miniprotocol.

    High-level function that:
    1. Builds a version table for the given network magic
    2. Encodes and sends MsgProposeVersions
    3. Receives and decodes the server response
    4. Returns MsgAcceptVersion on success, raises on Refuse

    The entire exchange must complete within ``timeout`` seconds
    (spec-mandated 10 s for the handshake miniprotocol).

    Args:
        channel: Async byte-level channel (wraps multiplexer sub-channel).
        network_magic: Network discriminator (e.g. 764824073 for mainnet).
        timeout: Maximum time for the handshake (default: 10 s per spec).

    Returns:
        ``MsgAcceptVersion`` with the negotiated version and parameters.

    Raises:
        HandshakeRefusedError: If the server sends MsgRefuse.
        HandshakeTimeoutError: If the handshake exceeds the timeout.
        HandshakeError: For unexpected protocol errors.
    """
    # Build version table with current N2N versions
    version_table = build_version_table(network_magic)

    # Encode MsgProposeVersions
    propose_bytes = encode_propose_versions(version_table)

    try:
        async with asyncio.timeout(timeout):
            # Send proposal
            await channel.send(propose_bytes)

            # Receive response
            response_bytes = await channel.recv()
    except TimeoutError:
        raise HandshakeTimeoutError(
            f"Handshake timed out after {timeout}s"
        ) from None

    # Decode response
    response: HandshakeResponse = decode_handshake_response(response_bytes)

    if isinstance(response, MsgAcceptVersion):
        return response
    elif isinstance(response, MsgRefuse):
        raise HandshakeRefusedError(response)
    else:
        raise HandshakeError(f"Unexpected handshake response: {response!r}")


# ---------------------------------------------------------------------------
# Server-side handshake runner
# ---------------------------------------------------------------------------


async def run_handshake_server(
    channel: Channel,
    network_magic: int,
    *,
    timeout: float = HANDSHAKE_TIMEOUT_S,
) -> MsgAcceptVersion:
    """Run the server side of the handshake miniprotocol.

    Receives MsgProposeVersions from the client, negotiates a common
    version, and responds with MsgAcceptVersion or MsgRefuse.

    Haskell ref:
        ``Ouroboros.Network.Protocol.Handshake.Server``
        ``pureHandshake`` in ``Ouroboros.Network.Protocol.Handshake.Direct``

    Args:
        channel: Async byte-level channel (wraps multiplexer sub-channel).
        network_magic: Our network magic for version negotiation.
        timeout: Maximum time for the handshake (default: 10 s per spec).

    Returns:
        ``MsgAcceptVersion`` with the negotiated version and parameters.

    Raises:
        HandshakeRefusedError: If no common version exists.
        HandshakeTimeoutError: If the handshake exceeds the timeout.
        HandshakeError: For unexpected protocol errors.
    """
    # Build our version table
    server_versions = build_version_table(network_magic)

    try:
        async with asyncio.timeout(timeout):
            # Receive client's proposal
            propose_bytes = await channel.recv()
    except TimeoutError:
        raise HandshakeTimeoutError(
            f"Handshake server timed out after {timeout}s"
        ) from None

    # Decode the proposal
    import cbor2pure as cbor2
    proposal = cbor2.loads(propose_bytes)
    # proposal = [0, {version: version_data, ...}]
    if not isinstance(proposal, list) or len(proposal) < 2 or proposal[0] != 0:
        raise HandshakeError(f"Invalid MsgProposeVersions: {proposal!r}")

    version_map = proposal[1]
    from .handshake import PeerSharing

    client_versions: dict[int, NodeToNodeVersionData] = {}
    for ver_num, ver_data in version_map.items():
        if isinstance(ver_data, list) and len(ver_data) >= 4:
            client_versions[ver_num] = NodeToNodeVersionData(
                network_magic=ver_data[0],
                initiator_only_diffusion_mode=bool(ver_data[1]),
                peer_sharing=PeerSharing(ver_data[2]),
                query=bool(ver_data[3]),
            )

    # Negotiate
    result = negotiate_version(client_versions, server_versions)

    if result is not None:
        # Accept — encode and send
        from .handshake import encode_accept_version
        accept_bytes = encode_accept_version(result)
        try:
            async with asyncio.timeout(timeout):
                await channel.send(accept_bytes)
        except TimeoutError:
            raise HandshakeTimeoutError(
                f"Handshake server send timed out after {timeout}s"
            ) from None
        return result
    else:
        # Refuse — version mismatch
        refuse = MsgRefuse(reason=RefuseReasonVersionMismatch(
            versions=list(server_versions.keys())
        ))
        refuse_bytes = encode_refuse(refuse)
        try:
            async with asyncio.timeout(timeout):
                await channel.send(refuse_bytes)
        except TimeoutError:
            pass
        raise HandshakeRefusedError(refuse)


# ---------------------------------------------------------------------------
# Server-side N2C handshake runner
# ---------------------------------------------------------------------------


@dataclass
class N2CHandshakeResult:
    """Result of a successful N2C handshake."""

    version_number: int
    version_data: NodeToClientVersionData


async def run_handshake_server_n2c(
    channel: Channel,
    network_magic: int,
    *,
    timeout: float = HANDSHAKE_TIMEOUT_S,
) -> N2CHandshakeResult:
    """Run the server side of the N2C handshake miniprotocol.

    N2C handshake uses versions 16--20 with 2-element version data
    ``[networkMagic, query]`` instead of N2N's 4-element format.

    Haskell ref:
        ``Ouroboros.Network.NodeToClient.Version``
        ``nodeToClientCodecCBORTerm``

    Args:
        channel: Async byte-level channel (wraps multiplexer sub-channel).
        network_magic: Our network magic for version negotiation.
        timeout: Maximum time for the handshake (default: 10 s per spec).

    Returns:
        ``N2CHandshakeResult`` with the negotiated version and parameters.

    Raises:
        HandshakeRefusedError: If no common version exists.
        HandshakeTimeoutError: If the handshake exceeds the timeout.
        HandshakeError: For unexpected protocol errors.
    """
    import cbor2pure as cbor2

    # Build our N2C version table
    server_versions = build_n2c_version_table(network_magic)

    try:
        async with asyncio.timeout(timeout):
            # Receive client's proposal
            propose_bytes = await channel.recv()
    except TimeoutError:
        raise HandshakeTimeoutError(
            f"N2C handshake server timed out after {timeout}s"
        ) from None

    # Decode the proposal
    proposal = cbor2.loads(propose_bytes)
    # proposal = [0, {version: version_data, ...}]
    if not isinstance(proposal, list) or len(proposal) < 2 or proposal[0] != 0:
        raise HandshakeError(f"Invalid MsgProposeVersions (N2C): {proposal!r}")

    version_map = proposal[1]

    client_versions: dict[int, NodeToClientVersionData] = {}
    for ver_num, ver_data in version_map.items():
        if isinstance(ver_data, list) and len(ver_data) >= 2:
            try:
                client_versions[ver_num] = _decode_n2c_version_data(ver_data)
            except ValueError:
                continue  # skip undecodable versions

    # Negotiate: find highest common version with matching network magic
    common = set(client_versions.keys()) & set(server_versions.keys())
    best: int | None = None
    for ver in sorted(common, reverse=True):
        if client_versions[ver].network_magic == server_versions[ver].network_magic:
            best = ver
            break

    if best is not None:
        # Accept — encode and send
        merged = NodeToClientVersionData(
            network_magic=server_versions[best].network_magic,
            query=client_versions[best].query,
        )
        accept_bytes = encode_n2c_accept_version(best, merged)
        try:
            async with asyncio.timeout(timeout):
                await channel.send(accept_bytes)
        except TimeoutError:
            raise HandshakeTimeoutError(
                f"N2C handshake server send timed out after {timeout}s"
            ) from None
        return N2CHandshakeResult(version_number=best, version_data=merged)
    else:
        # Refuse — version mismatch
        refuse = MsgRefuse(reason=RefuseReasonVersionMismatch(
            versions=list(server_versions.keys())
        ))
        refuse_bytes = encode_refuse(refuse)
        try:
            async with asyncio.timeout(timeout):
                await channel.send(refuse_bytes)
        except TimeoutError:
            pass
        raise HandshakeRefusedError(refuse)
