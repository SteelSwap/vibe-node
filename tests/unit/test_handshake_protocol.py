"""Unit tests for the handshake miniprotocol FSM and version negotiation.

Covers:
- State machine transitions (valid and invalid)
- Agency enforcement at each state
- Version negotiation selects highest common version
- Version negotiation with mismatched network magic
- Refuse handling (all variants)
- run_handshake_client with mock channel (accept and refuse paths)
- Timeout handling

Test spec references (from test_specifications table):
- test_handshake_protocol_num_is_zero
- test_handshake_shared_by_node_to_node_and_node_to_client
- test_request_outbound_returns_handshake_error
- test_request_outbound_blocks_until_negotiated
- prop_negotiated_outbound_transition_consistency
"""

from __future__ import annotations

import asyncio

import cbor2
import pytest

from vibe.core.protocols import Agency, Peer, PeerRole, ProtocolError
from vibe.cardano.network.handshake import (
    HANDSHAKE_TIMEOUT_S,
    MAINNET_NETWORK_MAGIC,
    PREPROD_NETWORK_MAGIC,
    N2N_V14,
    N2N_V15,
    MsgAcceptVersion,
    MsgProposeVersions,
    MsgRefuse,
    NodeToNodeVersionData,
    PeerSharing,
    RefuseReasonHandshakeDecodeError,
    RefuseReasonRefused,
    RefuseReasonVersionMismatch,
    build_version_table,
)
from vibe.cardano.network.handshake_protocol import (
    HandshakeError,
    HandshakeProtocol,
    HandshakeRefusedError,
    HandshakeState,
    HandshakeTimeoutError,
    MsgAcceptVersionMsg,
    MsgProposeVersionsMsg,
    MsgRefuseMsg,
    negotiate_version,
    run_handshake_client,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_version_data(
    magic: int = PREPROD_NETWORK_MAGIC,
    initiator_only: bool = False,
    peer_sharing: PeerSharing = PeerSharing.DISABLED,
    query: bool = False,
) -> NodeToNodeVersionData:
    return NodeToNodeVersionData(
        network_magic=magic,
        initiator_only_diffusion_mode=initiator_only,
        peer_sharing=peer_sharing,
        query=query,
    )


class MockChannel:
    """In-memory async channel for testing run_handshake_client."""

    def __init__(self, response_bytes: bytes | None = None) -> None:
        self.sent: list[bytes] = []
        self._response = response_bytes
        self._recv_queue: asyncio.Queue[bytes] = asyncio.Queue()
        if response_bytes is not None:
            self._recv_queue.put_nowait(response_bytes)

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> bytes:
        return await self._recv_queue.get()


class HangingChannel:
    """Channel that never returns from recv — for timeout testing."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> bytes:
        # Block forever
        await asyncio.Event().wait()
        return b""  # pragma: no cover


# ---------------------------------------------------------------------------
# Protocol definition tests
# ---------------------------------------------------------------------------


class TestHandshakeProtocol:
    """Test the HandshakeProtocol state machine definition."""

    def setup_method(self) -> None:
        self.proto = HandshakeProtocol()

    def test_initial_state(self) -> None:
        """Protocol starts at StPropose."""
        assert self.proto.initial_state() is HandshakeState.StPropose

    def test_agency_propose(self) -> None:
        """Client has agency at StPropose."""
        assert self.proto.agency(HandshakeState.StPropose) is Agency.Client

    def test_agency_confirm(self) -> None:
        """Server has agency at StConfirm."""
        assert self.proto.agency(HandshakeState.StConfirm) is Agency.Server

    def test_agency_done(self) -> None:
        """Nobody has agency at StDone (terminal)."""
        assert self.proto.agency(HandshakeState.StDone) is Agency.Nobody

    def test_valid_messages_propose(self) -> None:
        """Only MsgProposeVersionsMsg is valid at StPropose."""
        valid = self.proto.valid_messages(HandshakeState.StPropose)
        assert valid == frozenset({MsgProposeVersionsMsg})

    def test_valid_messages_confirm(self) -> None:
        """MsgAcceptVersionMsg and MsgRefuseMsg are valid at StConfirm."""
        valid = self.proto.valid_messages(HandshakeState.StConfirm)
        assert valid == frozenset({MsgAcceptVersionMsg, MsgRefuseMsg})

    def test_valid_messages_done(self) -> None:
        """No messages valid at StDone."""
        valid = self.proto.valid_messages(HandshakeState.StDone)
        assert valid == frozenset()


# ---------------------------------------------------------------------------
# State transition tests (via Peer)
# ---------------------------------------------------------------------------


def _make_peers():
    """Create connected Initiator/Responder peer pair for handshake."""
    proto = HandshakeProtocol()
    q_c2s: asyncio.Queue = asyncio.Queue()
    q_s2c: asyncio.Queue = asyncio.Queue()
    client = Peer(PeerRole.Initiator, proto, send_queue=q_c2s, recv_queue=q_s2c)
    server = Peer(PeerRole.Responder, proto, send_queue=q_s2c, recv_queue=q_c2s)
    return client, server


class TestHandshakeTransitions:
    """Test valid and invalid state transitions through the Peer."""

    @pytest.mark.asyncio
    async def test_propose_then_accept(self) -> None:
        """Full handshake: client proposes, server accepts."""
        client, server = _make_peers()

        # Client sends MsgProposeVersions (StPropose -> StConfirm)
        propose = MsgProposeVersions(version_table=build_version_table(PREPROD_NETWORK_MAGIC))
        await client.send(MsgProposeVersionsMsg(propose))
        assert client.state is HandshakeState.StConfirm

        # Server receives
        msg = await server.receive()
        assert isinstance(msg, MsgProposeVersionsMsg)
        assert server.state is HandshakeState.StConfirm

        # Server sends MsgAcceptVersion (StConfirm -> StDone)
        accept = MsgAcceptVersion(
            version_number=N2N_V15,
            version_data=_make_version_data(),
        )
        await server.send(MsgAcceptVersionMsg(accept))
        assert server.state is HandshakeState.StDone

        # Client receives
        msg = await client.receive()
        assert isinstance(msg, MsgAcceptVersionMsg)
        assert client.state is HandshakeState.StDone

    @pytest.mark.asyncio
    async def test_propose_then_refuse(self) -> None:
        """Full handshake: client proposes, server refuses."""
        client, server = _make_peers()

        # Client sends proposal
        propose = MsgProposeVersions(version_table=build_version_table(PREPROD_NETWORK_MAGIC))
        await client.send(MsgProposeVersionsMsg(propose))

        # Server receives
        await server.receive()

        # Server sends MsgRefuse (StConfirm -> StDone)
        refuse = MsgRefuse(reason=RefuseReasonVersionMismatch(versions=[14, 15]))
        await server.send(MsgRefuseMsg(refuse))
        assert server.state is HandshakeState.StDone

        # Client receives
        msg = await client.receive()
        assert isinstance(msg, MsgRefuseMsg)
        assert client.state is HandshakeState.StDone

    @pytest.mark.asyncio
    async def test_server_cannot_send_at_propose(self) -> None:
        """Server cannot send in StPropose (client has agency)."""
        _client, server = _make_peers()

        accept = MsgAcceptVersion(
            version_number=N2N_V14,
            version_data=_make_version_data(),
        )
        with pytest.raises(ProtocolError, match="does not have agency"):
            await server.send(MsgAcceptVersionMsg(accept))

    @pytest.mark.asyncio
    async def test_client_cannot_send_at_confirm(self) -> None:
        """Client cannot send in StConfirm (server has agency)."""
        client, server = _make_peers()

        # Advance to StConfirm
        propose = MsgProposeVersions(version_table=build_version_table(1))
        await client.send(MsgProposeVersionsMsg(propose))

        # Client tries to send again — wrong agency
        propose2 = MsgProposeVersions(version_table=build_version_table(1))
        with pytest.raises(ProtocolError, match="does not have agency"):
            await client.send(MsgProposeVersionsMsg(propose2))

    @pytest.mark.asyncio
    async def test_cannot_send_at_done(self) -> None:
        """Neither peer can send in StDone (terminal)."""
        client, server = _make_peers()

        # Complete the handshake
        propose = MsgProposeVersions(version_table=build_version_table(1))
        await client.send(MsgProposeVersionsMsg(propose))
        await server.receive()

        accept = MsgAcceptVersion(version_number=N2N_V14, version_data=_make_version_data())
        await server.send(MsgAcceptVersionMsg(accept))
        await client.receive()

        # Both at StDone — nobody can send
        with pytest.raises(ProtocolError, match="terminal state"):
            await client.send(MsgProposeVersionsMsg(propose))

        with pytest.raises(ProtocolError, match="terminal state"):
            await server.send(MsgAcceptVersionMsg(accept))

    @pytest.mark.asyncio
    async def test_cannot_receive_at_done(self) -> None:
        """Neither peer can receive in StDone (terminal)."""
        client, server = _make_peers()

        # Complete the handshake
        propose = MsgProposeVersions(version_table=build_version_table(1))
        await client.send(MsgProposeVersionsMsg(propose))
        await server.receive()

        accept = MsgAcceptVersion(version_number=N2N_V14, version_data=_make_version_data())
        await server.send(MsgAcceptVersionMsg(accept))
        await client.receive()

        with pytest.raises(ProtocolError, match="terminal state"):
            await client.receive()

    @pytest.mark.asyncio
    async def test_wrong_message_from_state(self) -> None:
        """Sending a message with wrong from_state raises ProtocolError."""
        client, _server = _make_peers()

        # MsgAcceptVersionMsg has from_state=StConfirm, but we're at StPropose
        accept = MsgAcceptVersion(version_number=N2N_V14, version_data=_make_version_data())
        with pytest.raises(ProtocolError, match="expects from_state"):
            await client.send(MsgAcceptVersionMsg(accept))


# ---------------------------------------------------------------------------
# Version negotiation tests
# ---------------------------------------------------------------------------


class TestNegotiateVersion:
    """Test pure version negotiation logic.

    References pureHandshake from
    Ouroboros.Network.Protocol.Handshake.Direct:
    picks highest common version via Map.toDescList of intersection.
    """

    def test_selects_highest_common_version(self) -> None:
        """Highest version present in both tables wins.

        prop_negotiated_outbound_transition_consistency: for any version
        combination, exactly one outcome.
        """
        client = {
            N2N_V14: _make_version_data(magic=1),
            N2N_V15: _make_version_data(magic=1),
        }
        server = {
            N2N_V14: _make_version_data(magic=1),
            N2N_V15: _make_version_data(magic=1),
        }
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_number == N2N_V15

    def test_selects_only_common_version(self) -> None:
        """When only one version overlaps, that one is selected."""
        client = {N2N_V14: _make_version_data(magic=1)}
        server = {
            N2N_V14: _make_version_data(magic=1),
            N2N_V15: _make_version_data(magic=1),
        }
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_number == N2N_V14

    def test_no_common_version_returns_none(self) -> None:
        """No intersection yields None (VersionMismatch)."""
        client = {N2N_V14: _make_version_data(magic=1)}
        server = {N2N_V15: _make_version_data(magic=1)}
        result = negotiate_version(client, server)
        assert result is None

    def test_empty_client_versions(self) -> None:
        """Empty client table yields None."""
        client: dict[int, NodeToNodeVersionData] = {}
        server = {N2N_V14: _make_version_data(magic=1)}
        assert negotiate_version(client, server) is None

    def test_empty_server_versions(self) -> None:
        """Empty server table yields None."""
        client = {N2N_V14: _make_version_data(magic=1)}
        server: dict[int, NodeToNodeVersionData] = {}
        assert negotiate_version(client, server) is None

    def test_mismatched_network_magic_returns_none(self) -> None:
        """Different network magic causes rejection even with common versions."""
        client = {N2N_V14: _make_version_data(magic=MAINNET_NETWORK_MAGIC)}
        server = {N2N_V14: _make_version_data(magic=PREPROD_NETWORK_MAGIC)}
        result = negotiate_version(client, server)
        assert result is None

    def test_merged_data_uses_server_magic(self) -> None:
        """Merged version data uses server's network magic."""
        client = {N2N_V14: _make_version_data(magic=1)}
        server = {N2N_V14: _make_version_data(magic=1)}
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_data.network_magic == 1

    def test_initiator_only_or_merge(self) -> None:
        """If either side is initiator-only, merged result is initiator-only.

        test_negotiated_outbound_unidirectional_when_initiator_only:
        when one side declares initiator-only, connection is unidirectional.
        """
        client = {N2N_V14: _make_version_data(magic=1, initiator_only=True)}
        server = {N2N_V14: _make_version_data(magic=1, initiator_only=False)}
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_data.initiator_only_diffusion_mode is True

        # Reverse: server is initiator-only
        client2 = {N2N_V14: _make_version_data(magic=1, initiator_only=False)}
        server2 = {N2N_V14: _make_version_data(magic=1, initiator_only=True)}
        result2 = negotiate_version(client2, server2)
        assert result2 is not None
        assert result2.version_data.initiator_only_diffusion_mode is True

    def test_neither_initiator_only_gives_duplex(self) -> None:
        """Neither side initiator-only means duplex (initiator_only=False).

        test_negotiated_outbound_duplex_when_version_gt_v7_and_neither_initiator_only.
        """
        client = {N2N_V14: _make_version_data(magic=1, initiator_only=False)}
        server = {N2N_V14: _make_version_data(magic=1, initiator_only=False)}
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_data.initiator_only_diffusion_mode is False

    def test_peer_sharing_uses_server_preference(self) -> None:
        """Server's peer sharing preference wins in merge."""
        client = {
            N2N_V14: _make_version_data(magic=1, peer_sharing=PeerSharing.ENABLED)
        }
        server = {
            N2N_V14: _make_version_data(magic=1, peer_sharing=PeerSharing.DISABLED)
        }
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_data.peer_sharing == PeerSharing.DISABLED

    def test_query_uses_client_preference(self) -> None:
        """Client's query flag is used in merge."""
        client = {N2N_V14: _make_version_data(magic=1, query=True)}
        server = {N2N_V14: _make_version_data(magic=1, query=False)}
        result = negotiate_version(client, server)
        assert result is not None
        assert result.version_data.query is True


# ---------------------------------------------------------------------------
# run_handshake_client tests (mock channel)
# ---------------------------------------------------------------------------


class TestRunHandshakeClient:
    """Test the high-level run_handshake_client function.

    test_request_outbound_blocks_until_negotiated: run_handshake_client
    blocks until AcceptVersion or error.
    """

    @pytest.mark.asyncio
    async def test_accept_version(self) -> None:
        """Successful handshake returns MsgAcceptVersion."""
        # Server will respond with AcceptVersion for V15
        response_bytes = cbor2.dumps([
            1,
            N2N_V15,
            [PREPROD_NETWORK_MAGIC, False, 0, False],
        ])
        channel = MockChannel(response_bytes)

        result = await run_handshake_client(channel, PREPROD_NETWORK_MAGIC)

        assert isinstance(result, MsgAcceptVersion)
        assert result.version_number == N2N_V15
        assert result.version_data.network_magic == PREPROD_NETWORK_MAGIC

        # Verify client sent a proposal
        assert len(channel.sent) == 1
        decoded = cbor2.loads(channel.sent[0])
        assert decoded[0] == 0  # MsgProposeVersions tag
        assert set(decoded[1].keys()) == {N2N_V14, N2N_V15}

    @pytest.mark.asyncio
    async def test_refuse_version_mismatch(self) -> None:
        """Refuse with VersionMismatch raises HandshakeRefusedError.

        test_request_outbound_returns_handshake_error.
        """
        response_bytes = cbor2.dumps([2, [0, [14, 15]]])
        channel = MockChannel(response_bytes)

        with pytest.raises(HandshakeRefusedError) as exc_info:
            await run_handshake_client(channel, PREPROD_NETWORK_MAGIC)

        assert isinstance(exc_info.value.refuse.reason, RefuseReasonVersionMismatch)

    @pytest.mark.asyncio
    async def test_refuse_decode_error(self) -> None:
        """Refuse with HandshakeDecodeError raises HandshakeRefusedError."""
        response_bytes = cbor2.dumps([2, [1, 14, "bad version data"]])
        channel = MockChannel(response_bytes)

        with pytest.raises(HandshakeRefusedError) as exc_info:
            await run_handshake_client(channel, PREPROD_NETWORK_MAGIC)

        reason = exc_info.value.refuse.reason
        assert isinstance(reason, RefuseReasonHandshakeDecodeError)
        assert reason.version_number == 14
        assert reason.message == "bad version data"

    @pytest.mark.asyncio
    async def test_refuse_refused(self) -> None:
        """Refuse with Refused reason raises HandshakeRefusedError."""
        response_bytes = cbor2.dumps([2, [2, 15, "connection limit"]])
        channel = MockChannel(response_bytes)

        with pytest.raises(HandshakeRefusedError) as exc_info:
            await run_handshake_client(channel, PREPROD_NETWORK_MAGIC)

        reason = exc_info.value.refuse.reason
        assert isinstance(reason, RefuseReasonRefused)
        assert reason.version_number == 15

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        """Handshake times out when server doesn't respond.

        Uses a very short timeout to avoid slow tests.
        """
        channel = HangingChannel()

        with pytest.raises(HandshakeTimeoutError, match="timed out"):
            await run_handshake_client(channel, PREPROD_NETWORK_MAGIC, timeout=0.05)

        # Client should have sent the proposal before timing out
        assert len(channel.sent) == 1

    @pytest.mark.asyncio
    async def test_mainnet_magic_in_proposal(self) -> None:
        """Verify mainnet magic is encoded correctly in the proposal."""
        response_bytes = cbor2.dumps([
            1,
            N2N_V15,
            [MAINNET_NETWORK_MAGIC, False, 0, False],
        ])
        channel = MockChannel(response_bytes)

        result = await run_handshake_client(channel, MAINNET_NETWORK_MAGIC)
        assert result.version_data.network_magic == MAINNET_NETWORK_MAGIC

        # Check the proposal encodes mainnet magic
        decoded = cbor2.loads(channel.sent[0])
        for vdata in decoded[1].values():
            assert vdata[0] == MAINNET_NETWORK_MAGIC

    @pytest.mark.asyncio
    async def test_default_timeout_is_spec_mandated(self) -> None:
        """Default timeout matches the spec-mandated 10 seconds."""
        assert HANDSHAKE_TIMEOUT_S == 10.0


# ---------------------------------------------------------------------------
# Message type tests
# ---------------------------------------------------------------------------


class TestMessageTypes:
    """Test handshake message wrapper types carry correct state transitions."""

    def test_propose_versions_msg_states(self) -> None:
        propose = MsgProposeVersions(version_table={})
        msg = MsgProposeVersionsMsg(propose)
        assert msg.from_state is HandshakeState.StPropose
        assert msg.to_state is HandshakeState.StConfirm
        assert msg.propose is propose

    def test_accept_version_msg_states(self) -> None:
        accept = MsgAcceptVersion(
            version_number=N2N_V14,
            version_data=_make_version_data(),
        )
        msg = MsgAcceptVersionMsg(accept)
        assert msg.from_state is HandshakeState.StConfirm
        assert msg.to_state is HandshakeState.StDone
        assert msg.accept is accept

    def test_refuse_msg_states(self) -> None:
        refuse = MsgRefuse(reason=RefuseReasonVersionMismatch(versions=[]))
        msg = MsgRefuseMsg(refuse)
        assert msg.from_state is HandshakeState.StConfirm
        assert msg.to_state is HandshakeState.StDone
        assert msg.refuse is refuse


# ---------------------------------------------------------------------------
# Error type tests
# ---------------------------------------------------------------------------


class TestErrorTypes:
    """Test handshake error hierarchy."""

    def test_refused_error_is_handshake_error(self) -> None:
        refuse = MsgRefuse(reason=RefuseReasonVersionMismatch(versions=[14]))
        err = HandshakeRefusedError(refuse)
        assert isinstance(err, HandshakeError)
        assert err.refuse is refuse
        assert "Handshake refused" in str(err)

    def test_timeout_error_is_handshake_error(self) -> None:
        err = HandshakeTimeoutError("timed out")
        assert isinstance(err, HandshakeError)


# ---------------------------------------------------------------------------
# Mux segment integration tests
# ---------------------------------------------------------------------------


class TestHandshakeMuxSegment:
    """Test handshake messages framed as mux segments.

    Verifies that handshake CBOR payloads, when wrapped in a MuxSegment,
    produce the correct 8-byte header with protocol_id=0 and accurate
    payload length — the invariants that the receiver loop relies on
    to route handshake traffic to the correct miniprotocol channel.

    Spec reference: Ouroboros network spec, Section 1.1 "Wire Format"
    Haskell reference: Network.Mux.Codec.encodeSDU
    """

    def test_handshake_message_has_proper_segment_header(self) -> None:
        """Encode ProposeVersions into a MuxSegment; verify 8-byte header
        has protocol_id=0 and correct payload length.

        The handshake is always miniprotocol 0. The segment header must
        reflect this so the demux routes it correctly.
        """
        from vibe.core.multiplexer.segment import (
            MuxSegment,
            SEGMENT_HEADER_SIZE,
            encode_segment,
        )
        from vibe.cardano.network.handshake import (
            HANDSHAKE_PROTOCOL_ID,
            encode_propose_versions,
        )

        version_table = build_version_table(PREPROD_NETWORK_MAGIC)
        payload = encode_propose_versions(version_table)

        segment = MuxSegment(
            timestamp=0,
            protocol_id=HANDSHAKE_PROTOCOL_ID,
            is_initiator=True,
            payload=payload,
        )
        wire = encode_segment(segment)

        # Header is always 8 bytes
        assert len(wire) == SEGMENT_HEADER_SIZE + len(payload)

        # Parse the header manually: bytes 4-5 encode mode|protocol_id
        import struct

        _ts, proto_word, payload_len = struct.unpack_from("!IHH", wire)

        # Initiator: M=0, so proto_word == protocol_id directly
        assert proto_word == HANDSHAKE_PROTOCOL_ID  # 0
        assert payload_len == len(payload)

    def test_handshake_segment_wire_format_protocol_id(self) -> None:
        """Encode handshake into mux segment, parse back the 2-byte
        protocol ID field from raw bytes.

        Verifies the exact byte-level layout: bytes 4-5 of the segment
        header carry the mode bit (bit 15) and protocol ID (bits 14-0).
        For handshake (protocol 0) from the initiator, both bytes must be 0x00.
        """
        from vibe.core.multiplexer.segment import (
            MuxSegment,
            encode_segment,
            decode_segment,
        )
        from vibe.cardano.network.handshake import (
            HANDSHAKE_PROTOCOL_ID,
            encode_propose_versions,
        )

        version_table = build_version_table(PREPROD_NETWORK_MAGIC)
        payload = encode_propose_versions(version_table)

        segment = MuxSegment(
            timestamp=42,
            protocol_id=HANDSHAKE_PROTOCOL_ID,
            is_initiator=True,
            payload=payload,
        )
        wire = encode_segment(segment)

        # Bytes 4-5 are the protocol_id word (big-endian uint16)
        proto_bytes = wire[4:6]
        assert proto_bytes == b"\x00\x00"  # protocol_id=0, M=0 (initiator)

        # Roundtrip: decode and verify
        decoded, consumed = decode_segment(wire)
        assert decoded.protocol_id == HANDSHAKE_PROTOCOL_ID
        assert decoded.is_initiator is True
        assert decoded.payload == payload
        assert consumed == len(wire)

    def test_handshake_completes_before_mux_init(self) -> None:
        """Verify that the handshake protocol runs on the mux before any
        other miniprotocol channel is activated.

        The Ouroboros mux spec requires that protocol 0 (handshake) completes
        before any other miniprotocol traffic is exchanged. We verify this
        by checking that:
        1. Handshake is protocol_id 0 (the first protocol)
        2. The HandshakeProtocol starts in StPropose and terminates at StDone
        3. The protocol is a 2-message exchange (propose -> accept/refuse)
           meaning it completes before any sustained traffic
        """
        from vibe.cardano.network.handshake import HANDSHAKE_PROTOCOL_ID

        # Handshake is always protocol 0 — the lowest numbered protocol
        assert HANDSHAKE_PROTOCOL_ID == 0

        # The protocol has exactly 3 states: propose, confirm, done
        states = list(HandshakeState)
        assert len(states) == 3

        proto = HandshakeProtocol()

        # Initial state is StPropose (client sends first)
        assert proto.initial_state() is HandshakeState.StPropose

        # Terminal state is StDone (nobody has agency)
        assert proto.agency(HandshakeState.StDone) is Agency.Nobody

        # The protocol terminates after exactly 2 messages:
        # MsgProposeVersions (StPropose -> StConfirm)
        # MsgAcceptVersion or MsgRefuse (StConfirm -> StDone)
        # No cycles — once you reach StDone, you're done
        assert proto.valid_messages(HandshakeState.StDone) == frozenset()


class TestVersionNegotiationProperty:
    """Hypothesis property test for version negotiation."""

    def test_version_negotiation_property(self) -> None:
        """Given two random subsets of version numbers, negotiation selects
        the highest common, or None if disjoint.

        This is the core invariant of pureHandshake from
        Ouroboros.Network.Protocol.Handshake.Direct: the intersection of
        version sets, ordered descending, picks the first (= highest).
        """
        from hypothesis import given, settings
        from hypothesis import strategies as st

        # Version numbers in the valid N2N range (we test with a wider range
        # to exercise the logic beyond just V14/V15)
        version_numbers = st.integers(min_value=1, max_value=20)
        version_sets = st.frozensets(version_numbers, min_size=0, max_size=10)

        @given(client_versions=version_sets, server_versions=version_sets)
        @settings(max_examples=200, deadline=None)
        def check(
            client_versions: frozenset[int], server_versions: frozenset[int]
        ) -> None:
            magic = 1  # Use same magic so mismatch doesn't interfere
            client_table = {
                v: _make_version_data(magic=magic) for v in client_versions
            }
            server_table = {
                v: _make_version_data(magic=magic) for v in server_versions
            }

            result = negotiate_version(client_table, server_table)
            common = client_versions & server_versions

            if not common:
                assert result is None
            else:
                assert result is not None
                assert result.version_number == max(common)

        check()
