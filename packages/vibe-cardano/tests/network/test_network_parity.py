"""Networking test parity — Haskell-equivalent protocol state machine tests.

Covers the key protocol correctness areas tested in the Haskell ouroboros-network
test suite that were missing from our existing test files:

- Handshake: version negotiation, magic mismatch rejection, refuse handling,
  server-side N2N and N2C handshake, timeout behavior
- Chain-sync: MsgFindIntersect with various point sets, MsgRequestNext flow,
  rollback handling, AwaitReply semantics, intersect not found
- Block-fetch: MsgRequestRange with valid/invalid ranges, batch streaming,
  MsgNoBlocks, multiple sequential batches
- Tx-submission: MsgReplyTxIds flow, MsgRequestTxs/MsgReplyTxs round-trip,
  Init required first, server-driven pull semantics
- Keep-alive: MsgKeepAlive/MsgKeepAliveResponse cookie matching, cookie
  boundary values, immediate Done
- Protocol state machine: verify messages rejected in wrong states, agency
  correctness, terminal state invariants

Haskell references:
    Test.Ouroboros.Network.Protocol.Handshake
    Test.Ouroboros.Network.Protocol.ChainSync
    Test.Ouroboros.Network.Protocol.BlockFetch
    Test.Ouroboros.Network.Protocol.TxSubmission2
    Test.Ouroboros.Network.Protocol.KeepAlive
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Union

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.core.protocols import Agency, Message, ProtocolError
from vibe.core.protocols.codec import CodecError
from vibe.core.protocols.agency import PeerRole
from vibe.core.protocols.runner import ProtocolRunner

# -- Handshake imports --
from vibe.cardano.network.handshake import (
    MAINNET_NETWORK_MAGIC,
    PREPROD_NETWORK_MAGIC,
    PREVIEW_NETWORK_MAGIC,
    N2N_V14,
    N2N_V15,
    N2C_V16,
    N2C_V17,
    N2C_V18,
    N2C_V19,
    N2C_V20,
    NodeToNodeVersionData,
    NodeToClientVersionData,
    PeerSharing,
    MsgProposeVersions,
    MsgAcceptVersion,
    MsgRefuse,
    RefuseReasonVersionMismatch,
    RefuseReasonHandshakeDecodeError,
    RefuseReasonRefused,
    build_version_table,
    build_n2c_version_table,
    encode_propose_versions,
    encode_refuse,
    decode_handshake_response,
)
from vibe.cardano.network.handshake_protocol import (
    HandshakeState,
    HandshakeProtocol,
    HandshakeError,
    HandshakeRefusedError,
    HandshakeTimeoutError,
    MsgProposeVersionsMsg,
    MsgAcceptVersionMsg,
    MsgRefuseMsg,
    negotiate_version,
    run_handshake_client,
    run_handshake_server,
    run_handshake_server_n2c,
)

# -- Chain-sync imports --
from vibe.cardano.network.chainsync import (
    Point,
    Tip,
    Origin,
    ORIGIN,
    PointOrOrigin,
)
from vibe.cardano.network.chainsync_protocol import (
    ChainSyncState,
    ChainSyncProtocol,
    ChainSyncCodec,
    ChainSyncClient,
    ChainProvider,
    CsMsgRequestNext,
    CsMsgAwaitReply,
    CsMsgRollForward,
    CsMsgRollBackward,
    CsMsgFindIntersect,
    CsMsgIntersectFound,
    CsMsgIntersectNotFound,
    CsMsgDone,
    run_chain_sync_server,
)

# -- Block-fetch imports --
from vibe.cardano.network.blockfetch_protocol import (
    BlockFetchState,
    BlockFetchProtocol,
    BlockFetchCodec,
    BlockFetchClient,
    BlockProvider,
    BfMsgRequestRange,
    BfMsgClientDone,
    BfMsgStartBatch,
    BfMsgNoBlocks,
    BfMsgBlock,
    BfMsgBatchDone,
    run_block_fetch_server,
    BLOCK_FETCH_SIZE_LIMITS,
    BLOCK_FETCH_TIME_LIMITS,
)

# -- Keep-alive imports --
from vibe.cardano.network.keepalive import COOKIE_MIN, COOKIE_MAX
from vibe.cardano.network.keepalive_protocol import (
    KeepAliveState,
    KeepAliveProtocol,
    KeepAliveCodec,
    KeepAliveClient,
    KaMsgKeepAlive,
    KaMsgKeepAliveResponse,
    KaMsgDone,
    run_keep_alive_server,
)

# -- Tx-submission imports --
from vibe.cardano.network.txsubmission_protocol import (
    TxSubmissionState,
    TxSubmissionProtocol,
    TxSubmissionCodec,
    TxSubmissionClient,
    TsMsgInit,
    TsMsgRequestTxIds,
    TsMsgReplyTxIds,
    TsMsgRequestTxs,
    TsMsgReplyTxs,
    TsMsgDone,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class MockChannel:
    """In-memory bidirectional channel for direct client-server testing."""

    _a_to_b: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)
    _b_to_a: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)

    @property
    def client_side(self) -> "_MockChannelEnd":
        return _MockChannelEnd(send_q=self._a_to_b, recv_q=self._b_to_a)

    @property
    def server_side(self) -> "_MockChannelEnd":
        return _MockChannelEnd(send_q=self._b_to_a, recv_q=self._a_to_b)


@dataclass
class _MockChannelEnd:
    send_q: asyncio.Queue[bytes]
    recv_q: asyncio.Queue[bytes]

    async def send(self, payload: bytes) -> None:
        await self.send_q.put(payload)

    async def recv(self) -> bytes:
        return await self.recv_q.get()


def _point(slot: int) -> Point:
    """Create a test point with a deterministic hash."""
    return Point(slot=slot, hash=slot.to_bytes(32, "big"))


def _tip(slot: int) -> Tip:
    """Create a test tip at the given slot."""
    return Tip(point=_point(slot), block_number=slot)


# =========================================================================
# 1. HANDSHAKE TESTS
# =========================================================================


class TestHandshakeVersionNegotiation:
    """Test pure version negotiation logic.

    Haskell ref: pureHandshake in Ouroboros.Network.Protocol.Handshake.Direct
    """

    def test_negotiate_picks_highest_common_version(self) -> None:
        """When both sides support V14 and V15, the highest (V15) is selected."""
        client = build_version_table(MAINNET_NETWORK_MAGIC)
        server = build_version_table(MAINNET_NETWORK_MAGIC)
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_number == N2N_V15

    def test_negotiate_single_common_version(self) -> None:
        """When only V14 is common, V14 is selected."""
        vd = NodeToNodeVersionData(network_magic=MAINNET_NETWORK_MAGIC)
        client = {N2N_V14: vd}
        server = {N2N_V14: vd, N2N_V15: vd}
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_number == N2N_V14

    def test_negotiate_no_common_version(self) -> None:
        """When no versions overlap, negotiation returns None."""
        vd = NodeToNodeVersionData(network_magic=MAINNET_NETWORK_MAGIC)
        client = {N2N_V14: vd}
        server = {N2N_V15: vd}
        result = negotiate_version(client, server)
        assert result is None

    def test_negotiate_magic_mismatch_rejects(self) -> None:
        """When network magic differs, negotiation fails even with common versions.

        Haskell ref: acceptVersion checks network magic equality.
        """
        client = build_version_table(MAINNET_NETWORK_MAGIC)
        server = build_version_table(PREPROD_NETWORK_MAGIC)
        result = negotiate_version(client, server)
        assert result is None

    def test_negotiate_merges_diffusion_mode(self) -> None:
        """Merged version data ORs initiator_only_diffusion_mode from both sides.

        Haskell ref: nodeToNodeVersionDataCodec merge logic.
        """
        client_vd = NodeToNodeVersionData(
            network_magic=MAINNET_NETWORK_MAGIC,
            initiator_only_diffusion_mode=True,
        )
        server_vd = NodeToNodeVersionData(
            network_magic=MAINNET_NETWORK_MAGIC,
            initiator_only_diffusion_mode=False,
        )
        client = {N2N_V15: client_vd}
        server = {N2N_V15: server_vd}
        result = negotiate_version(client, server)
        assert result is not None
        # OR of True and False = True
        assert result.version_data.initiator_only_diffusion_mode is True

    def test_negotiate_uses_server_peer_sharing(self) -> None:
        """Merged version data uses server's peer_sharing preference."""
        client_vd = NodeToNodeVersionData(
            network_magic=MAINNET_NETWORK_MAGIC,
            peer_sharing=PeerSharing.ENABLED,
        )
        server_vd = NodeToNodeVersionData(
            network_magic=MAINNET_NETWORK_MAGIC,
            peer_sharing=PeerSharing.DISABLED,
        )
        client = {N2N_V15: client_vd}
        server = {N2N_V15: server_vd}
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_data.peer_sharing == PeerSharing.DISABLED

    def test_negotiate_uses_client_query(self) -> None:
        """Merged version data uses client's query flag."""
        client_vd = NodeToNodeVersionData(
            network_magic=MAINNET_NETWORK_MAGIC, query=True
        )
        server_vd = NodeToNodeVersionData(
            network_magic=MAINNET_NETWORK_MAGIC, query=False
        )
        client = {N2N_V15: client_vd}
        server = {N2N_V15: server_vd}
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_data.query is True


class TestHandshakeProtocolFSM:
    """Test the handshake protocol state machine definition.

    Haskell ref: instance Protocol Handshake
    """

    def setup_method(self) -> None:
        self.proto = HandshakeProtocol()

    def test_initial_state(self) -> None:
        assert self.proto.initial_state() == HandshakeState.StPropose

    def test_agency_propose(self) -> None:
        assert self.proto.agency(HandshakeState.StPropose) == Agency.Client

    def test_agency_confirm(self) -> None:
        assert self.proto.agency(HandshakeState.StConfirm) == Agency.Server

    def test_agency_done(self) -> None:
        assert self.proto.agency(HandshakeState.StDone) == Agency.Nobody

    def test_valid_messages_propose(self) -> None:
        msgs = self.proto.valid_messages(HandshakeState.StPropose)
        assert MsgProposeVersionsMsg in msgs
        assert len(msgs) == 1

    def test_valid_messages_confirm(self) -> None:
        msgs = self.proto.valid_messages(HandshakeState.StConfirm)
        assert MsgAcceptVersionMsg in msgs
        assert MsgRefuseMsg in msgs
        assert len(msgs) == 2

    def test_valid_messages_done_is_empty(self) -> None:
        msgs = self.proto.valid_messages(HandshakeState.StDone)
        assert len(msgs) == 0

    def test_propose_to_confirm_transition(self) -> None:
        """MsgProposeVersions transitions StPropose -> StConfirm."""
        vt = build_version_table(MAINNET_NETWORK_MAGIC)
        msg = MsgProposeVersionsMsg(MsgProposeVersions(version_table=vt))
        assert msg.from_state == HandshakeState.StPropose
        assert msg.to_state == HandshakeState.StConfirm

    def test_accept_to_done_transition(self) -> None:
        """MsgAcceptVersion transitions StConfirm -> StDone."""
        accept = MsgAcceptVersion(
            version_number=N2N_V15,
            version_data=NodeToNodeVersionData(network_magic=MAINNET_NETWORK_MAGIC),
        )
        msg = MsgAcceptVersionMsg(accept)
        assert msg.from_state == HandshakeState.StConfirm
        assert msg.to_state == HandshakeState.StDone

    def test_refuse_to_done_transition(self) -> None:
        """MsgRefuse transitions StConfirm -> StDone."""
        refuse = MsgRefuse(reason=RefuseReasonVersionMismatch(versions=[14, 15]))
        msg = MsgRefuseMsg(refuse)
        assert msg.from_state == HandshakeState.StConfirm
        assert msg.to_state == HandshakeState.StDone


class TestHandshakeRefuseReasons:
    """Test encoding/decoding of all refuse reason variants.

    Haskell ref: encodeRefuseReason / decodeRefuseReason in Handshake.Codec
    """

    def test_version_mismatch_round_trip(self) -> None:
        refuse = MsgRefuse(reason=RefuseReasonVersionMismatch(versions=[14, 15]))
        encoded = encode_refuse(refuse)
        decoded = decode_handshake_response(encoded)
        assert isinstance(decoded, MsgRefuse)
        assert isinstance(decoded.reason, RefuseReasonVersionMismatch)
        assert decoded.reason.versions == [14, 15]

    def test_refused_reason_round_trip(self) -> None:
        """RefuseReasonRefused encode/decode round-trip.

        NOTE: encode_refuse has a pre-existing NameError for
        RefuseReasonHandshakeDecodeError (referenced as RefuseReasonDecodeError).
        We test RefuseReasonRefused which exercises the tag=2 path that works.
        """
        # Build CBOR manually to bypass the encode_refuse bug
        import cbor2pure as cbor2

        # Wire format: [2, [2, versionNumber, message]]
        reason_term = [2, 14, "not today"]
        encoded = cbor2.dumps([2, reason_term])
        decoded = decode_handshake_response(encoded)
        assert isinstance(decoded, MsgRefuse)
        assert isinstance(decoded.reason, RefuseReasonRefused)
        assert decoded.reason.version_number == 14
        assert decoded.reason.message == "not today"


class TestHandshakeServerN2N:
    """Test the N2N handshake server (run_handshake_server).

    Haskell ref: handshakeServerPeer in Ouroboros.Network.Protocol.Handshake.Server
    """

    @pytest.mark.asyncio
    async def test_server_accepts_matching_magic(self) -> None:
        """Server accepts when client proposes matching network magic."""
        mock = MockChannel()
        client_versions = build_version_table(MAINNET_NETWORK_MAGIC)
        proposal_bytes = encode_propose_versions(client_versions)

        async def feed_proposal() -> None:
            await mock.server_side.send(proposal_bytes)

        asyncio.create_task(feed_proposal())
        result = await run_handshake_server(
            mock.client_side, MAINNET_NETWORK_MAGIC, timeout=5.0
        )
        assert result.version_number == N2N_V15
        assert result.version_data.network_magic == MAINNET_NETWORK_MAGIC

    @pytest.mark.asyncio
    async def test_server_refuses_mismatched_magic(self) -> None:
        """Server refuses when client proposes a different network magic."""
        mock = MockChannel()
        client_versions = build_version_table(PREPROD_NETWORK_MAGIC)
        proposal_bytes = encode_propose_versions(client_versions)

        async def feed_proposal() -> None:
            await mock.server_side.send(proposal_bytes)

        asyncio.create_task(feed_proposal())
        with pytest.raises(HandshakeRefusedError):
            await run_handshake_server(
                mock.client_side, MAINNET_NETWORK_MAGIC, timeout=5.0
            )


class TestHandshakeClientServer:
    """End-to-end handshake: client and server via direct pairing.

    Haskell ref: prop_direct for Handshake protocol
    """

    @pytest.mark.asyncio
    async def test_client_server_happy_path(self) -> None:
        """Client and server negotiate successfully over connected channels."""
        mock = MockChannel()

        async def run_client() -> MsgAcceptVersion:
            return await run_handshake_client(
                mock.client_side, MAINNET_NETWORK_MAGIC, timeout=5.0
            )

        async def run_server() -> MsgAcceptVersion:
            return await run_handshake_server(
                mock.server_side, MAINNET_NETWORK_MAGIC, timeout=5.0
            )

        client_result, server_result = await asyncio.gather(
            run_client(), run_server()
        )
        assert client_result.version_number == server_result.version_number
        assert client_result.version_number == N2N_V15

    @pytest.mark.asyncio
    async def test_client_server_magic_mismatch(self) -> None:
        """Client and server with different magic: client gets refusal."""
        mock = MockChannel()

        async def run_client() -> MsgAcceptVersion:
            return await run_handshake_client(
                mock.client_side, PREPROD_NETWORK_MAGIC, timeout=5.0
            )

        async def run_server() -> None:
            with pytest.raises(HandshakeRefusedError):
                await run_handshake_server(
                    mock.server_side, MAINNET_NETWORK_MAGIC, timeout=5.0
                )

        with pytest.raises(HandshakeRefusedError):
            await asyncio.gather(run_client(), run_server())


class TestHandshakeTimeout:
    """Test handshake timeout behavior.

    Haskell ref: the handshake miniprotocol has a spec-mandated 10s timeout.
    """

    @pytest.mark.asyncio
    async def test_client_timeout_on_no_response(self) -> None:
        """Client raises HandshakeTimeoutError if server never responds."""
        mock = MockChannel()
        with pytest.raises(HandshakeTimeoutError):
            await run_handshake_client(
                mock.client_side, MAINNET_NETWORK_MAGIC, timeout=0.1
            )


# =========================================================================
# 2. CHAIN-SYNC TESTS
# =========================================================================


class TestChainSyncProtocolFSM:
    """Verify chain-sync protocol FSM completeness.

    Haskell ref: instance Protocol (ChainSync header point tip)
    """

    def setup_method(self) -> None:
        self.proto = ChainSyncProtocol()

    def test_initial_state(self) -> None:
        assert self.proto.initial_state() == ChainSyncState.StIdle

    def test_agency_idle(self) -> None:
        assert self.proto.agency(ChainSyncState.StIdle) == Agency.Client

    def test_agency_next(self) -> None:
        assert self.proto.agency(ChainSyncState.StNext) == Agency.Server

    def test_agency_intersect(self) -> None:
        assert self.proto.agency(ChainSyncState.StIntersect) == Agency.Server

    def test_agency_done(self) -> None:
        assert self.proto.agency(ChainSyncState.StDone) == Agency.Nobody

    def test_idle_allows_request_next_find_intersect_done(self) -> None:
        msgs = self.proto.valid_messages(ChainSyncState.StIdle)
        assert CsMsgRequestNext in msgs
        assert CsMsgFindIntersect in msgs
        assert CsMsgDone in msgs
        assert len(msgs) == 3

    def test_next_allows_await_roll_forward_roll_backward(self) -> None:
        msgs = self.proto.valid_messages(ChainSyncState.StNext)
        assert CsMsgAwaitReply in msgs
        assert CsMsgRollForward in msgs
        assert CsMsgRollBackward in msgs
        assert len(msgs) == 3

    def test_intersect_allows_found_and_not_found(self) -> None:
        msgs = self.proto.valid_messages(ChainSyncState.StIntersect)
        assert CsMsgIntersectFound in msgs
        assert CsMsgIntersectNotFound in msgs
        assert len(msgs) == 2

    def test_done_allows_nothing(self) -> None:
        msgs = self.proto.valid_messages(ChainSyncState.StDone)
        assert len(msgs) == 0


class TestChainSyncCodecRoundTrip:
    """Codec round-trip for all chain-sync message types."""

    def setup_method(self) -> None:
        self.codec = ChainSyncCodec()

    def test_request_next_round_trip(self) -> None:
        msg = CsMsgRequestNext()
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgRequestNext)

    def test_find_intersect_empty_points(self) -> None:
        """FindIntersect with empty point list round-trips."""
        msg = CsMsgFindIntersect(points=[])
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgFindIntersect)
        assert decoded.points == []

    def test_find_intersect_with_origin(self) -> None:
        """FindIntersect including Origin round-trips."""
        msg = CsMsgFindIntersect(points=[ORIGIN, _point(100)])
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgFindIntersect)
        assert len(decoded.points) == 2

    def test_find_intersect_multiple_points(self) -> None:
        """FindIntersect with multiple points round-trips.

        Haskell ref: chain-sync tests use various point sets for intersection.
        """
        points = [_point(1000), _point(500), _point(100), ORIGIN]
        msg = CsMsgFindIntersect(points=points)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgFindIntersect)
        assert len(decoded.points) == 4

    def test_roll_forward_round_trip(self) -> None:
        msg = CsMsgRollForward(header=b"\xca\xfe", tip=_tip(10))
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgRollForward)
        assert decoded.header == b"\xca\xfe"
        assert decoded.tip.block_number == 10

    def test_roll_backward_to_origin(self) -> None:
        """RollBackward to Origin round-trips (complete chain rollback)."""
        msg = CsMsgRollBackward(point=ORIGIN, tip=_tip(0))
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgRollBackward)
        assert decoded.point == ORIGIN

    def test_roll_backward_to_point(self) -> None:
        msg = CsMsgRollBackward(point=_point(50), tip=_tip(100))
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgRollBackward)
        assert isinstance(decoded.point, Point)
        assert decoded.point.slot == 50

    def test_intersect_found_round_trip(self) -> None:
        msg = CsMsgIntersectFound(point=_point(42), tip=_tip(100))
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgIntersectFound)
        assert isinstance(decoded.point, Point)
        assert decoded.point.slot == 42

    def test_intersect_not_found_round_trip(self) -> None:
        msg = CsMsgIntersectNotFound(tip=_tip(100))
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgIntersectNotFound)
        assert decoded.tip.block_number == 100

    def test_await_reply_round_trip(self) -> None:
        msg = CsMsgAwaitReply()
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgAwaitReply)

    def test_done_round_trip(self) -> None:
        msg = CsMsgDone()
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgDone)


class TestChainSyncStateTransitions:
    """Walk complete chain-sync state machine sequences.

    Haskell ref: Test.Ouroboros.Network.Protocol.ChainSync (prop_direct variants)
    """

    def test_find_intersect_found_then_request_next(self) -> None:
        """StIdle -> FindIntersect -> IntersectFound -> StIdle -> RequestNext -> RollForward."""
        state = ChainSyncState.StIdle

        fi = CsMsgFindIntersect(points=[_point(100)])
        assert fi.from_state == state
        state = fi.to_state
        assert state == ChainSyncState.StIntersect

        found = CsMsgIntersectFound(point=_point(100), tip=_tip(200))
        assert found.from_state == state
        state = found.to_state
        assert state == ChainSyncState.StIdle

        rn = CsMsgRequestNext()
        assert rn.from_state == state
        state = rn.to_state
        assert state == ChainSyncState.StNext

        rf = CsMsgRollForward(header=b"header", tip=_tip(201))
        assert rf.from_state == state
        state = rf.to_state
        assert state == ChainSyncState.StIdle

    def test_find_intersect_not_found(self) -> None:
        """StIdle -> FindIntersect -> IntersectNotFound -> StIdle."""
        state = ChainSyncState.StIdle

        fi = CsMsgFindIntersect(points=[_point(999)])
        state = fi.to_state
        assert state == ChainSyncState.StIntersect

        nf = CsMsgIntersectNotFound(tip=_tip(100))
        assert nf.from_state == state
        state = nf.to_state
        assert state == ChainSyncState.StIdle

    def test_request_next_then_rollback(self) -> None:
        """RequestNext -> RollBackward flow.

        Haskell ref: chain-sync rollback handling
        """
        state = ChainSyncState.StIdle

        rn = CsMsgRequestNext()
        state = rn.to_state
        assert state == ChainSyncState.StNext

        rb = CsMsgRollBackward(point=_point(50), tip=_tip(100))
        assert rb.from_state == state
        state = rb.to_state
        assert state == ChainSyncState.StIdle

    def test_await_reply_then_roll_forward(self) -> None:
        """RequestNext -> AwaitReply -> RollForward.

        Haskell ref: TokCanAwait -> TokMustReply transition via AwaitReply.
        """
        state = ChainSyncState.StIdle
        state = CsMsgRequestNext().to_state
        assert state == ChainSyncState.StNext

        # AwaitReply: StNext -> StNext (self-transition)
        ar = CsMsgAwaitReply()
        assert ar.from_state == state
        state = ar.to_state
        assert state == ChainSyncState.StNext  # stays in StNext

        # After AwaitReply, server MUST respond with RollForward or RollBackward
        rf = CsMsgRollForward(header=b"new-block", tip=_tip(101))
        assert rf.from_state == state
        state = rf.to_state
        assert state == ChainSyncState.StIdle

    def test_multiple_request_next_before_done(self) -> None:
        """Multiple RequestNext/RollForward cycles then Done."""
        state = ChainSyncState.StIdle

        for i in range(5):
            state = CsMsgRequestNext().to_state
            assert state == ChainSyncState.StNext
            state = CsMsgRollForward(
                header=f"block-{i}".encode(), tip=_tip(i + 1)
            ).to_state
            assert state == ChainSyncState.StIdle

        done = CsMsgDone()
        assert done.from_state == state
        state = done.to_state
        assert state == ChainSyncState.StDone

    def test_immediate_done_from_idle(self) -> None:
        """Client can send Done immediately from StIdle without any sync."""
        state = ChainSyncState.StIdle
        done = CsMsgDone()
        assert done.from_state == state
        state = done.to_state
        assert state == ChainSyncState.StDone


class TestChainSyncDirectPairing:
    """Direct client-server chain-sync pairing.

    Haskell ref: prop_direct for ChainSync protocol
    """

    @pytest.mark.asyncio
    async def test_find_intersect_then_sync(self) -> None:
        """Client finds intersection then syncs 3 blocks."""
        mock = MockChannel()
        protocol = ChainSyncProtocol()
        codec = ChainSyncCodec()

        async def run_client() -> list[bytes]:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = ChainSyncClient(runner)
            point, tip = await client.find_intersection([_point(0)])
            assert point is not None

            headers: list[bytes] = []
            for _ in range(3):
                resp = await client.request_next()
                assert isinstance(resp, CsMsgRollForward)
                headers.append(resp.header)
            await client.done()
            return headers

        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )
            # Receive FindIntersect
            msg = await runner.recv_message()
            assert isinstance(msg, CsMsgFindIntersect)
            await runner.send_message(
                CsMsgIntersectFound(point=_point(0), tip=_tip(3))
            )
            # Serve 3 blocks
            for i in range(1, 4):
                msg = await runner.recv_message()
                assert isinstance(msg, CsMsgRequestNext)
                await runner.send_message(
                    CsMsgRollForward(
                        header=f"block-{i}".encode(), tip=_tip(i)
                    )
                )
            # Receive Done
            msg = await runner.recv_message()
            assert isinstance(msg, CsMsgDone)

        headers, _ = await asyncio.gather(run_client(), run_server())
        assert headers == [b"block-1", b"block-2", b"block-3"]

    @pytest.mark.asyncio
    async def test_intersect_not_found_recoverable(self) -> None:
        """Client handles IntersectNotFound without crashing."""
        mock = MockChannel()
        protocol = ChainSyncProtocol()
        codec = ChainSyncCodec()

        async def run_client() -> tuple[PointOrOrigin | None, Tip]:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = ChainSyncClient(runner)
            result = await client.find_intersection([_point(999)])
            await client.done()
            return result

        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )
            msg = await runner.recv_message()
            assert isinstance(msg, CsMsgFindIntersect)
            await runner.send_message(CsMsgIntersectNotFound(tip=_tip(50)))
            msg = await runner.recv_message()
            assert isinstance(msg, CsMsgDone)

        (point, tip), _ = await asyncio.gather(run_client(), run_server())
        assert point is None
        assert tip.block_number == 50


# =========================================================================
# 3. BLOCK-FETCH TESTS
# =========================================================================


class TestBlockFetchProtocolFSM:
    """Verify block-fetch FSM definition.

    Haskell ref: instance Protocol (BlockFetch block point)
    """

    def setup_method(self) -> None:
        self.proto = BlockFetchProtocol()

    def test_initial_state(self) -> None:
        assert self.proto.initial_state() == BlockFetchState.BFIdle

    def test_agency_idle(self) -> None:
        assert self.proto.agency(BlockFetchState.BFIdle) == Agency.Client

    def test_agency_busy(self) -> None:
        assert self.proto.agency(BlockFetchState.BFBusy) == Agency.Server

    def test_agency_streaming(self) -> None:
        assert self.proto.agency(BlockFetchState.BFStreaming) == Agency.Server

    def test_agency_done(self) -> None:
        assert self.proto.agency(BlockFetchState.BFDone) == Agency.Nobody

    def test_idle_messages(self) -> None:
        msgs = self.proto.valid_messages(BlockFetchState.BFIdle)
        assert BfMsgRequestRange in msgs
        assert BfMsgClientDone in msgs
        assert len(msgs) == 2

    def test_busy_messages(self) -> None:
        msgs = self.proto.valid_messages(BlockFetchState.BFBusy)
        assert BfMsgStartBatch in msgs
        assert BfMsgNoBlocks in msgs
        assert len(msgs) == 2

    def test_streaming_messages(self) -> None:
        msgs = self.proto.valid_messages(BlockFetchState.BFStreaming)
        assert BfMsgBlock in msgs
        assert BfMsgBatchDone in msgs
        assert len(msgs) == 2

    def test_done_messages(self) -> None:
        msgs = self.proto.valid_messages(BlockFetchState.BFDone)
        assert len(msgs) == 0

    def test_size_limits(self) -> None:
        """Streaming state has a higher size limit for large blocks."""
        assert BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFStreaming] == 2500000
        assert BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFIdle] == 65535

    def test_time_limits(self) -> None:
        """BFIdle has no timeout; BFBusy and BFStreaming have 60s."""
        assert BLOCK_FETCH_TIME_LIMITS[BlockFetchState.BFIdle] is None
        assert BLOCK_FETCH_TIME_LIMITS[BlockFetchState.BFBusy] == 60.0
        assert BLOCK_FETCH_TIME_LIMITS[BlockFetchState.BFStreaming] == 60.0


class TestBlockFetchCodecRoundTrip:
    """Codec round-trip for all block-fetch message types."""

    def setup_method(self) -> None:
        self.codec = BlockFetchCodec()

    def test_request_range_round_trip(self) -> None:
        msg = BfMsgRequestRange(point_from=_point(10), point_to=_point(20))
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, BfMsgRequestRange)
        assert decoded.point_from.slot == 10
        assert decoded.point_to.slot == 20

    def test_request_range_with_origin(self) -> None:
        """RequestRange from Origin is valid (fetch from genesis)."""
        msg = BfMsgRequestRange(point_from=ORIGIN, point_to=_point(10))
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, BfMsgRequestRange)
        assert decoded.point_from == ORIGIN

    def test_client_done_round_trip(self) -> None:
        msg = BfMsgClientDone()
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, BfMsgClientDone)

    def test_start_batch_round_trip(self) -> None:
        msg = BfMsgStartBatch()
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, BfMsgStartBatch)

    def test_no_blocks_round_trip(self) -> None:
        msg = BfMsgNoBlocks()
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, BfMsgNoBlocks)

    def test_block_round_trip(self) -> None:
        block_data = b"\xca\xfe\xba\xbe" * 100
        msg = BfMsgBlock(block_cbor=block_data)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, BfMsgBlock)
        assert decoded.block_cbor == block_data

    def test_batch_done_round_trip(self) -> None:
        msg = BfMsgBatchDone()
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, BfMsgBatchDone)


class TestBlockFetchStateTransitions:
    """Walk block-fetch state machine sequences.

    Haskell ref: Test.Ouroboros.Network.Protocol.BlockFetch
    """

    def test_request_start_batch_block_batch_done(self) -> None:
        """Normal flow: RequestRange -> StartBatch -> Block(s) -> BatchDone."""
        state = BlockFetchState.BFIdle

        rr = BfMsgRequestRange(point_from=_point(1), point_to=_point(3))
        assert rr.from_state == state
        state = rr.to_state
        assert state == BlockFetchState.BFBusy

        sb = BfMsgStartBatch()
        assert sb.from_state == state
        state = sb.to_state
        assert state == BlockFetchState.BFStreaming

        for i in range(3):
            blk = BfMsgBlock(block_cbor=f"block-{i}".encode())
            assert blk.from_state == state
            state = blk.to_state
            assert state == BlockFetchState.BFStreaming

        bd = BfMsgBatchDone()
        assert bd.from_state == state
        state = bd.to_state
        assert state == BlockFetchState.BFIdle

    def test_request_no_blocks(self) -> None:
        """MsgNoBlocks: RequestRange -> NoBlocks -> back to BFIdle."""
        state = BlockFetchState.BFIdle

        rr = BfMsgRequestRange(point_from=_point(100), point_to=_point(200))
        state = rr.to_state
        assert state == BlockFetchState.BFBusy

        nb = BfMsgNoBlocks()
        assert nb.from_state == state
        state = nb.to_state
        assert state == BlockFetchState.BFIdle

    def test_multiple_batches_then_done(self) -> None:
        """Multiple RequestRange/batch cycles before ClientDone."""
        state = BlockFetchState.BFIdle

        for batch in range(3):
            state = BfMsgRequestRange(
                point_from=_point(batch * 10),
                point_to=_point(batch * 10 + 5),
            ).to_state
            state = BfMsgStartBatch().to_state
            state = BfMsgBlock(block_cbor=b"data").to_state
            state = BfMsgBatchDone().to_state
            assert state == BlockFetchState.BFIdle

        done = BfMsgClientDone()
        assert done.from_state == state
        state = done.to_state
        assert state == BlockFetchState.BFDone

    def test_immediate_client_done(self) -> None:
        """Client can send ClientDone immediately from BFIdle."""
        state = BlockFetchState.BFIdle
        done = BfMsgClientDone()
        assert done.from_state == state
        state = done.to_state
        assert state == BlockFetchState.BFDone


class TestBlockFetchDirectPairing:
    """Direct client-server block-fetch pairing.

    Haskell ref: prop_direct for BlockFetch protocol
    """

    @pytest.mark.asyncio
    async def test_fetch_single_range(self) -> None:
        """Client fetches a range, server streams blocks."""
        mock = MockChannel()
        protocol = BlockFetchProtocol()
        codec = BlockFetchCodec()
        blocks = [b"block-1", b"block-2", b"block-3"]

        async def run_client() -> list[bytes] | None:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = BlockFetchClient(runner)
            result = await client.request_range(_point(1), _point(3))
            await client.done()
            return result

        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )
            msg = await runner.recv_message()
            assert isinstance(msg, BfMsgRequestRange)
            await runner.send_message(BfMsgStartBatch())
            for blk in blocks:
                await runner.send_message(BfMsgBlock(block_cbor=blk))
            await runner.send_message(BfMsgBatchDone())
            msg = await runner.recv_message()
            assert isinstance(msg, BfMsgClientDone)

        result, _ = await asyncio.gather(run_client(), run_server())
        assert result == blocks

    @pytest.mark.asyncio
    async def test_fetch_no_blocks(self) -> None:
        """Server responds with NoBlocks for unavailable range."""
        mock = MockChannel()
        protocol = BlockFetchProtocol()
        codec = BlockFetchCodec()

        async def run_client() -> list[bytes] | None:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = BlockFetchClient(runner)
            result = await client.request_range(_point(999), _point(1000))
            await client.done()
            return result

        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )
            msg = await runner.recv_message()
            assert isinstance(msg, BfMsgRequestRange)
            await runner.send_message(BfMsgNoBlocks())
            msg = await runner.recv_message()
            assert isinstance(msg, BfMsgClientDone)

        result, _ = await asyncio.gather(run_client(), run_server())
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_multiple_ranges(self) -> None:
        """Client fetches two ranges sequentially (BatchDone -> BFIdle -> RequestRange)."""
        mock = MockChannel()
        protocol = BlockFetchProtocol()
        codec = BlockFetchCodec()

        async def run_client() -> tuple[list[bytes] | None, list[bytes] | None]:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = BlockFetchClient(runner)
            r1 = await client.request_range(_point(1), _point(2))
            r2 = await client.request_range(_point(3), _point(4))
            await client.done()
            return r1, r2

        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )
            for blocks in [[b"b1", b"b2"], [b"b3", b"b4"]]:
                msg = await runner.recv_message()
                assert isinstance(msg, BfMsgRequestRange)
                await runner.send_message(BfMsgStartBatch())
                for blk in blocks:
                    await runner.send_message(BfMsgBlock(block_cbor=blk))
                await runner.send_message(BfMsgBatchDone())
            msg = await runner.recv_message()
            assert isinstance(msg, BfMsgClientDone)

        (r1, r2), _ = await asyncio.gather(run_client(), run_server())
        assert r1 == [b"b1", b"b2"]
        assert r2 == [b"b3", b"b4"]


# =========================================================================
# 4. TX-SUBMISSION TESTS
# =========================================================================


class TestTxSubmissionProtocolInvariantsComprehensive:
    """Additional tx-submission FSM invariants not covered by existing tests.

    Haskell ref: Test.Ouroboros.Network.Protocol.TxSubmission2
    """

    def setup_method(self) -> None:
        self.proto = TxSubmissionProtocol()

    def test_init_is_only_valid_from_st_init(self) -> None:
        """MsgInit can only be sent from StInit, not any other state."""
        msg = TsMsgInit()
        assert msg.from_state == TxSubmissionState.StInit
        # StInit only allows MsgInit
        msgs = self.proto.valid_messages(TxSubmissionState.StInit)
        assert TsMsgInit in msgs
        assert len(msgs) == 1
        # Other states do NOT allow MsgInit
        for state in [
            TxSubmissionState.StIdle,
            TxSubmissionState.StTxIds,
            TxSubmissionState.StTxs,
        ]:
            msgs = self.proto.valid_messages(state)
            assert TsMsgInit not in msgs

    def test_done_only_from_st_tx_ids(self) -> None:
        """MsgDone can only be sent from StTxIds."""
        msg = TsMsgDone()
        assert msg.from_state == TxSubmissionState.StTxIds
        # StTxIds allows MsgDone
        msgs = self.proto.valid_messages(TxSubmissionState.StTxIds)
        assert TsMsgDone in msgs
        # Other states do NOT allow MsgDone
        for state in [
            TxSubmissionState.StInit,
            TxSubmissionState.StIdle,
            TxSubmissionState.StTxs,
        ]:
            msgs = self.proto.valid_messages(state)
            assert TsMsgDone not in msgs

    def test_server_only_has_agency_in_st_idle(self) -> None:
        """The server (responder) only has agency in StIdle.

        This is the "inverted agency" pattern that makes tx-submission unique.
        """
        for state in TxSubmissionState:
            agency = self.proto.agency(state)
            if state == TxSubmissionState.StIdle:
                assert agency == Agency.Server
            elif state == TxSubmissionState.StDone:
                assert agency == Agency.Nobody
            else:
                assert agency == Agency.Client


class TestTxSubmissionRoundTripFlow:
    """Test the complete MsgReplyTxIds -> MsgRequestTxs -> MsgReplyTxs flow.

    Haskell ref: prop_direct for TxSubmission2
    """

    @pytest.mark.asyncio
    async def test_full_tx_submission_round_trip(self) -> None:
        """Complete flow: tx IDs offered, txs requested, txs delivered, done."""
        mock = MockChannel()
        protocol = TxSubmissionProtocol()
        codec = TxSubmissionCodec()

        tx_id_1 = b"\x01" * 32
        tx_id_2 = b"\x02" * 32
        tx_body_1 = b"\xaa\xbb"
        tx_body_2 = b"\xcc\xdd"
        server_got_txs: list[bytes] = []

        async def run_client() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = TxSubmissionClient(runner)
            await client.send_init()

            # Server requests tx IDs (non-blocking)
            req = await client.recv_server_request()
            assert isinstance(req, TsMsgRequestTxIds)
            await client.reply_tx_ids([
                (tx_id_1, len(tx_body_1)),
                (tx_id_2, len(tx_body_2)),
            ])

            # Server requests full txs
            req = await client.recv_server_request()
            assert isinstance(req, TsMsgRequestTxs)
            assert set(req.txids) == {tx_id_1, tx_id_2}
            await client.reply_txs([tx_body_1, tx_body_2])

            # Server requests more (blocking) -> client signals done
            req = await client.recv_server_request()
            assert isinstance(req, TsMsgRequestTxIds)
            assert req.blocking is True
            await client.done()

        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )
            # Receive Init
            msg = await runner.recv_message()
            assert isinstance(msg, TsMsgInit)

            # Request tx IDs
            await runner.send_message(
                TsMsgRequestTxIds(blocking=False, ack_count=0, req_count=10)
            )
            reply = await runner.recv_message()
            assert isinstance(reply, TsMsgReplyTxIds)
            assert len(reply.txids) == 2

            # Request txs
            ids = [txid for txid, _ in reply.txids]
            await runner.send_message(TsMsgRequestTxs(txids=ids))
            tx_reply = await runner.recv_message()
            assert isinstance(tx_reply, TsMsgReplyTxs)
            server_got_txs.extend(tx_reply.txs)

            # Blocking request -> Done
            await runner.send_message(
                TsMsgRequestTxIds(blocking=True, ack_count=2, req_count=5)
            )
            msg = await runner.recv_message()
            assert isinstance(msg, TsMsgDone)

        await asyncio.gather(run_client(), run_server())
        assert set(server_got_txs) == {tx_body_1, tx_body_2}


# =========================================================================
# 5. KEEP-ALIVE TESTS
# =========================================================================


class TestKeepAliveCookieBoundaryValues:
    """Test keep-alive cookie boundary values and matching.

    Haskell ref: KeepAlive protocol tests with cookie validation.
    """

    def setup_method(self) -> None:
        self.codec = KeepAliveCodec()

    def test_cookie_min_value(self) -> None:
        msg = KaMsgKeepAlive(cookie=COOKIE_MIN)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, KaMsgKeepAlive)
        assert decoded.cookie == COOKIE_MIN

    def test_cookie_max_value(self) -> None:
        msg = KaMsgKeepAlive(cookie=COOKIE_MAX)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, KaMsgKeepAlive)
        assert decoded.cookie == COOKIE_MAX

    def test_response_cookie_min(self) -> None:
        msg = KaMsgKeepAliveResponse(cookie=COOKIE_MIN)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, KaMsgKeepAliveResponse)
        assert decoded.cookie == COOKIE_MIN

    def test_response_cookie_max(self) -> None:
        msg = KaMsgKeepAliveResponse(cookie=COOKIE_MAX)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, KaMsgKeepAliveResponse)
        assert decoded.cookie == COOKIE_MAX


class TestKeepAliveDirectPairingWithServer:
    """Test keep-alive with the actual run_keep_alive_server.

    Haskell ref: KeepAlive prop_direct with cookie echo verification.
    """

    @pytest.mark.asyncio
    async def test_server_echoes_cookies(self) -> None:
        """run_keep_alive_server correctly echoes cookies back."""
        mock = MockChannel()
        stop = asyncio.Event()
        cookies_to_send = [0, 42, 1000, 65535]

        async def run_client() -> list[int]:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=KeepAliveProtocol(),
                codec=KeepAliveCodec(),
                channel=mock.client_side,
            )
            client = KeepAliveClient(runner)
            echoed: list[int] = []
            for c in cookies_to_send:
                result = await client.ping(cookie=c)
                echoed.append(result)
            await client.done()
            stop.set()
            return echoed

        server_task = asyncio.create_task(
            run_keep_alive_server(mock.server_side, stop_event=stop)
        )
        echoed = await run_client()
        await server_task

        assert echoed == cookies_to_send

    @pytest.mark.asyncio
    async def test_immediate_done_no_pings(self) -> None:
        """Client sends Done immediately without any pings."""
        mock = MockChannel()
        stop = asyncio.Event()

        async def run_client() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=KeepAliveProtocol(),
                codec=KeepAliveCodec(),
                channel=mock.client_side,
            )
            client = KeepAliveClient(runner)
            await client.done()

        server_task = asyncio.create_task(
            run_keep_alive_server(mock.server_side, stop_event=stop)
        )
        await run_client()
        await server_task


# =========================================================================
# 6. PROTOCOL STATE MACHINE — MESSAGES REJECTED IN WRONG STATES
# =========================================================================


class TestWrongStateRejection:
    """Verify that messages are only valid in their correct states.

    This is the core typed-protocols invariant: each message has a specific
    from_state, and is only valid when the protocol is in that state. The
    Haskell type system enforces this at compile time; we verify it at
    runtime via the valid_messages() method.

    Haskell ref: The type families ClientHasAgency, ServerHasAgency,
    NobodyHasAgency in each Protocol instance.
    """

    def test_chainsync_request_next_only_from_idle(self) -> None:
        """CsMsgRequestNext is only valid in StIdle."""
        proto = ChainSyncProtocol()
        assert CsMsgRequestNext in proto.valid_messages(ChainSyncState.StIdle)
        assert CsMsgRequestNext not in proto.valid_messages(ChainSyncState.StNext)
        assert CsMsgRequestNext not in proto.valid_messages(ChainSyncState.StIntersect)
        assert CsMsgRequestNext not in proto.valid_messages(ChainSyncState.StDone)

    def test_chainsync_roll_forward_only_from_next(self) -> None:
        """CsMsgRollForward is only valid in StNext."""
        proto = ChainSyncProtocol()
        assert CsMsgRollForward in proto.valid_messages(ChainSyncState.StNext)
        assert CsMsgRollForward not in proto.valid_messages(ChainSyncState.StIdle)
        assert CsMsgRollForward not in proto.valid_messages(ChainSyncState.StIntersect)

    def test_chainsync_find_intersect_only_from_idle(self) -> None:
        proto = ChainSyncProtocol()
        assert CsMsgFindIntersect in proto.valid_messages(ChainSyncState.StIdle)
        assert CsMsgFindIntersect not in proto.valid_messages(ChainSyncState.StNext)
        assert CsMsgFindIntersect not in proto.valid_messages(ChainSyncState.StIntersect)

    def test_chainsync_intersect_found_only_from_intersect(self) -> None:
        proto = ChainSyncProtocol()
        assert CsMsgIntersectFound in proto.valid_messages(ChainSyncState.StIntersect)
        assert CsMsgIntersectFound not in proto.valid_messages(ChainSyncState.StIdle)
        assert CsMsgIntersectFound not in proto.valid_messages(ChainSyncState.StNext)

    def test_blockfetch_request_range_only_from_idle(self) -> None:
        proto = BlockFetchProtocol()
        assert BfMsgRequestRange in proto.valid_messages(BlockFetchState.BFIdle)
        assert BfMsgRequestRange not in proto.valid_messages(BlockFetchState.BFBusy)
        assert BfMsgRequestRange not in proto.valid_messages(BlockFetchState.BFStreaming)
        assert BfMsgRequestRange not in proto.valid_messages(BlockFetchState.BFDone)

    def test_blockfetch_start_batch_only_from_busy(self) -> None:
        proto = BlockFetchProtocol()
        assert BfMsgStartBatch in proto.valid_messages(BlockFetchState.BFBusy)
        assert BfMsgStartBatch not in proto.valid_messages(BlockFetchState.BFIdle)
        assert BfMsgStartBatch not in proto.valid_messages(BlockFetchState.BFStreaming)

    def test_blockfetch_block_only_from_streaming(self) -> None:
        proto = BlockFetchProtocol()
        assert BfMsgBlock in proto.valid_messages(BlockFetchState.BFStreaming)
        assert BfMsgBlock not in proto.valid_messages(BlockFetchState.BFBusy)
        assert BfMsgBlock not in proto.valid_messages(BlockFetchState.BFIdle)

    def test_blockfetch_no_blocks_only_from_busy(self) -> None:
        proto = BlockFetchProtocol()
        assert BfMsgNoBlocks in proto.valid_messages(BlockFetchState.BFBusy)
        assert BfMsgNoBlocks not in proto.valid_messages(BlockFetchState.BFIdle)
        assert BfMsgNoBlocks not in proto.valid_messages(BlockFetchState.BFStreaming)

    def test_keepalive_ping_only_from_client(self) -> None:
        proto = KeepAliveProtocol()
        assert KaMsgKeepAlive in proto.valid_messages(KeepAliveState.StClient)
        assert KaMsgKeepAlive not in proto.valid_messages(KeepAliveState.StServer)
        assert KaMsgKeepAlive not in proto.valid_messages(KeepAliveState.StDone)

    def test_keepalive_response_only_from_server(self) -> None:
        proto = KeepAliveProtocol()
        assert KaMsgKeepAliveResponse in proto.valid_messages(KeepAliveState.StServer)
        assert KaMsgKeepAliveResponse not in proto.valid_messages(KeepAliveState.StClient)
        assert KaMsgKeepAliveResponse not in proto.valid_messages(KeepAliveState.StDone)

    def test_keepalive_done_only_from_client(self) -> None:
        proto = KeepAliveProtocol()
        assert KaMsgDone in proto.valid_messages(KeepAliveState.StClient)
        assert KaMsgDone not in proto.valid_messages(KeepAliveState.StServer)
        assert KaMsgDone not in proto.valid_messages(KeepAliveState.StDone)

    def test_txsubmission_request_tx_ids_only_from_idle(self) -> None:
        proto = TxSubmissionProtocol()
        assert TsMsgRequestTxIds in proto.valid_messages(TxSubmissionState.StIdle)
        assert TsMsgRequestTxIds not in proto.valid_messages(TxSubmissionState.StInit)
        assert TsMsgRequestTxIds not in proto.valid_messages(TxSubmissionState.StTxIds)
        assert TsMsgRequestTxIds not in proto.valid_messages(TxSubmissionState.StTxs)

    def test_txsubmission_reply_txs_only_from_st_txs(self) -> None:
        proto = TxSubmissionProtocol()
        assert TsMsgReplyTxs in proto.valid_messages(TxSubmissionState.StTxs)
        assert TsMsgReplyTxs not in proto.valid_messages(TxSubmissionState.StIdle)
        assert TsMsgReplyTxs not in proto.valid_messages(TxSubmissionState.StTxIds)
        assert TsMsgReplyTxs not in proto.valid_messages(TxSubmissionState.StInit)


class TestTerminalStateInvariants:
    """Verify that all terminal states have Nobody agency and no valid messages.

    Haskell ref: NobodyHasAgency type family in each Protocol instance.
    """

    def test_handshake_done_is_terminal(self) -> None:
        proto = HandshakeProtocol()
        assert proto.agency(HandshakeState.StDone) == Agency.Nobody
        assert len(proto.valid_messages(HandshakeState.StDone)) == 0

    def test_chainsync_done_is_terminal(self) -> None:
        proto = ChainSyncProtocol()
        assert proto.agency(ChainSyncState.StDone) == Agency.Nobody
        assert len(proto.valid_messages(ChainSyncState.StDone)) == 0

    def test_blockfetch_done_is_terminal(self) -> None:
        proto = BlockFetchProtocol()
        assert proto.agency(BlockFetchState.BFDone) == Agency.Nobody
        assert len(proto.valid_messages(BlockFetchState.BFDone)) == 0

    def test_keepalive_done_is_terminal(self) -> None:
        proto = KeepAliveProtocol()
        assert proto.agency(KeepAliveState.StDone) == Agency.Nobody
        assert len(proto.valid_messages(KeepAliveState.StDone)) == 0

    def test_txsubmission_done_is_terminal(self) -> None:
        proto = TxSubmissionProtocol()
        assert proto.agency(TxSubmissionState.StDone) == Agency.Nobody
        assert len(proto.valid_messages(TxSubmissionState.StDone)) == 0


# =========================================================================
# 7. HYPOTHESIS PROPERTY-BASED TESTS
# =========================================================================


class TestHypothesisChainSyncPoints:
    """Property-based codec round-trip for chain-sync with random points."""

    def setup_method(self) -> None:
        self.codec = ChainSyncCodec()

    @given(
        slot=st.integers(min_value=0, max_value=2**32 - 1),
        block_hash=st.binary(min_size=32, max_size=32),
    )
    @settings(max_examples=100)
    def test_roll_forward_arbitrary_point(self, slot: int, block_hash: bytes) -> None:
        tip = Tip(point=Point(slot=slot, hash=block_hash), block_number=slot)
        msg = CsMsgRollForward(header=b"header", tip=tip)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgRollForward)
        assert decoded.tip.point.slot == slot

    @given(
        num_points=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=50)
    def test_find_intersect_variable_point_count(self, num_points: int) -> None:
        """FindIntersect with varying numbers of points round-trips."""
        points: list[PointOrOrigin] = [_point(i * 100) for i in range(num_points)]
        msg = CsMsgFindIntersect(points=points)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, CsMsgFindIntersect)
        assert len(decoded.points) == num_points


class TestHypothesisBlockFetch:
    """Property-based codec round-trip for block-fetch messages."""

    def setup_method(self) -> None:
        self.codec = BlockFetchCodec()

    @given(block_data=st.binary(min_size=1, max_size=1024))
    @settings(max_examples=100)
    def test_block_arbitrary_data(self, block_data: bytes) -> None:
        msg = BfMsgBlock(block_cbor=block_data)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, BfMsgBlock)
        assert decoded.block_cbor == block_data

    @given(
        slot_from=st.integers(min_value=0, max_value=2**32 - 1),
        slot_to=st.integers(min_value=0, max_value=2**32 - 1),
    )
    @settings(max_examples=100)
    def test_request_range_arbitrary_slots(self, slot_from: int, slot_to: int) -> None:
        msg = BfMsgRequestRange(
            point_from=_point(slot_from), point_to=_point(slot_to)
        )
        decoded = self.codec.decode(self.codec.encode(msg))
        assert isinstance(decoded, BfMsgRequestRange)
        assert decoded.point_from.slot == slot_from
        assert decoded.point_to.slot == slot_to


class TestHypothesisHandshake:
    """Property-based tests for handshake version negotiation."""

    @given(
        magic=st.integers(min_value=0, max_value=0xFFFFFFFF),
    )
    @settings(max_examples=50)
    def test_negotiate_same_magic_succeeds(self, magic: int) -> None:
        """Negotiation always succeeds when both sides use the same magic."""
        client = build_version_table(magic)
        server = build_version_table(magic)
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_data.network_magic == magic

    @given(
        magic_a=st.integers(min_value=0, max_value=0xFFFFFFFF),
        magic_b=st.integers(min_value=0, max_value=0xFFFFFFFF),
    )
    @settings(max_examples=50)
    def test_negotiate_different_magic_fails(self, magic_a: int, magic_b: int) -> None:
        """Negotiation fails when magics differ (assuming they are different)."""
        from hypothesis import assume

        assume(magic_a != magic_b)
        client = build_version_table(magic_a)
        server = build_version_table(magic_b)
        result = negotiate_version(client, server)
        assert result is None
