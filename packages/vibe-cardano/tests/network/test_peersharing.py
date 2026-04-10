"""Tests for peer-sharing miniprotocol CBOR message types and codec.

Tests cover:
- Message construction and field access
- PeerAddress IPv4 and IPv6 encode/decode
- CBOR encoding produces expected wire format
- CBOR decoding recovers the original message
- Round-trip property: decode(encode(msg)) == msg for all message types
- Edge cases: amount boundaries (0, 255), empty peer lists, mixed address types
- Invalid decode: wrong tags, malformed data, out-of-range values
- Protocol round-trip: client/server state machine over MockChannel
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import cbor2
import pytest

from vibe.cardano.network.peersharing import (
    AMOUNT_MAX,
    AMOUNT_MIN,
    PEER_SHARING_PROTOCOL_ID,
    MsgDone,
    MsgSharePeers,
    MsgShareRequest,
    PeerAddress,
    decode_message,
    decode_peer_address,
    encode_done,
    encode_peer_address,
    encode_share_peers,
    encode_share_request,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify protocol constants match the spec."""

    def test_protocol_id(self) -> None:
        assert PEER_SHARING_PROTOCOL_ID == 10

    def test_amount_range(self) -> None:
        assert AMOUNT_MIN == 0
        assert AMOUNT_MAX == 255


# ---------------------------------------------------------------------------
# PeerAddress construction
# ---------------------------------------------------------------------------


class TestPeerAddress:
    """PeerAddress dataclass construction and fields."""

    def test_ipv4_construction(self) -> None:
        addr = PeerAddress(ip="192.168.1.1", port=3001)
        assert addr.ip == "192.168.1.1"
        assert addr.port == 3001
        assert addr.is_ipv6 is False

    def test_ipv6_construction(self) -> None:
        addr = PeerAddress(ip="::1", port=3001, is_ipv6=True)
        assert addr.ip == "::1"
        assert addr.port == 3001
        assert addr.is_ipv6 is True

    def test_frozen(self) -> None:
        addr = PeerAddress(ip="1.2.3.4", port=80)
        with pytest.raises(AttributeError):
            addr.ip = "5.6.7.8"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = PeerAddress(ip="10.0.0.1", port=3001)
        b = PeerAddress(ip="10.0.0.1", port=3001)
        c = PeerAddress(ip="10.0.0.2", port=3001)
        assert a == b
        assert a != c


# ---------------------------------------------------------------------------
# PeerAddress encode / decode
# ---------------------------------------------------------------------------


class TestPeerAddressCodec:
    """Encode and decode PeerAddress to/from CBOR-compatible lists."""

    def test_ipv4_encode(self) -> None:
        addr = PeerAddress(ip="192.168.1.1", port=3001)
        encoded = encode_peer_address(addr)
        assert encoded[0] == 0  # IPv4 tag
        assert len(encoded) == 3
        # word32 for 192.168.1.1 = 0xC0A80101
        assert encoded[1] == 0xC0A80101
        assert encoded[2] == 3001

    def test_ipv4_decode(self) -> None:
        term = [0, 0xC0A80101, 3001]
        addr = decode_peer_address(term)
        assert addr.ip == "192.168.1.1"
        assert addr.port == 3001
        assert addr.is_ipv6 is False

    def test_ipv4_round_trip(self) -> None:
        original = PeerAddress(ip="192.168.1.1", port=3001)
        encoded = encode_peer_address(original)
        decoded = decode_peer_address(encoded)
        assert decoded == original

    def test_ipv4_zero_address(self) -> None:
        addr = PeerAddress(ip="0.0.0.0", port=0)
        encoded = encode_peer_address(addr)
        assert encoded == [0, 0, 0]
        decoded = decode_peer_address(encoded)
        assert decoded == addr

    def test_ipv4_max_address(self) -> None:
        addr = PeerAddress(ip="255.255.255.255", port=65535)
        encoded = encode_peer_address(addr)
        assert encoded == [0, 0xFFFFFFFF, 65535]
        decoded = decode_peer_address(encoded)
        assert decoded == addr

    def test_ipv6_loopback_encode(self) -> None:
        addr = PeerAddress(ip="::1", port=3001, is_ipv6=True)
        encoded = encode_peer_address(addr)
        assert encoded[0] == 1  # IPv6 tag
        assert len(encoded) == 6
        # ::1 = 0, 0, 0, 1
        assert encoded[1] == 0
        assert encoded[2] == 0
        assert encoded[3] == 0
        assert encoded[4] == 1
        assert encoded[5] == 3001

    def test_ipv6_loopback_decode(self) -> None:
        term = [1, 0, 0, 0, 1, 3001]
        addr = decode_peer_address(term)
        assert addr.ip == "::1"
        assert addr.port == 3001
        assert addr.is_ipv6 is True

    def test_ipv6_loopback_round_trip(self) -> None:
        original = PeerAddress(ip="::1", port=3001, is_ipv6=True)
        encoded = encode_peer_address(original)
        decoded = decode_peer_address(encoded)
        assert decoded == original

    def test_ipv6_full_address_round_trip(self) -> None:
        original = PeerAddress(ip="2001:db8::1", port=3001, is_ipv6=True)
        encoded = encode_peer_address(original)
        decoded = decode_peer_address(encoded)
        # inet_ntop may normalize the address, so compare normalized forms
        assert decoded.port == original.port
        assert decoded.is_ipv6 is True
        # Re-encode both to confirm they produce the same wire representation
        assert encode_peer_address(decoded) == encode_peer_address(original)

    def test_ipv6_full_address_encode(self) -> None:
        addr = PeerAddress(ip="2001:db8::1", port=3001, is_ipv6=True)
        encoded = encode_peer_address(addr)
        assert encoded[0] == 1  # IPv6 tag
        assert len(encoded) == 6
        # 2001:0db8:0000:0000:0000:0000:0000:0001
        assert encoded[1] == 0x20010DB8
        assert encoded[2] == 0x00000000
        assert encoded[3] == 0x00000000
        assert encoded[4] == 0x00000001
        assert encoded[5] == 3001

    def test_decode_invalid_not_list(self) -> None:
        with pytest.raises(ValueError, match="Expected peer address list"):
            decode_peer_address(42)  # type: ignore[arg-type]

    def test_decode_invalid_empty_list(self) -> None:
        with pytest.raises(ValueError, match="Expected peer address list"):
            decode_peer_address([])

    def test_decode_invalid_ipv4_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 3 elements"):
            decode_peer_address([0, 123])

    def test_decode_invalid_ipv6_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 6 elements"):
            decode_peer_address([1, 0, 0, 0])

    def test_decode_unknown_tag(self) -> None:
        with pytest.raises(ValueError, match="Unknown peer address tag"):
            decode_peer_address([2, 0, 0])


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


class TestMsgShareRequest:
    """MsgShareRequest message construction and fields."""

    def test_construction(self) -> None:
        msg = MsgShareRequest(amount=10)
        assert msg.amount == 10
        assert msg.msg_id == 0

    def test_frozen(self) -> None:
        msg = MsgShareRequest(amount=5)
        with pytest.raises(AttributeError):
            msg.amount = 20  # type: ignore[misc]

    def test_equality(self) -> None:
        assert MsgShareRequest(amount=10) == MsgShareRequest(amount=10)
        assert MsgShareRequest(amount=10) != MsgShareRequest(amount=20)


class TestMsgSharePeers:
    """MsgSharePeers message construction and fields."""

    def test_construction_empty(self) -> None:
        msg = MsgSharePeers(peers=())
        assert msg.peers == ()
        assert msg.msg_id == 1

    def test_construction_with_peers(self) -> None:
        peers = (PeerAddress(ip="1.2.3.4", port=3001),)
        msg = MsgSharePeers(peers=peers)
        assert len(msg.peers) == 1
        assert msg.peers[0].ip == "1.2.3.4"

    def test_frozen(self) -> None:
        msg = MsgSharePeers(peers=())
        with pytest.raises(AttributeError):
            msg.peers = ()  # type: ignore[misc]

    def test_equality(self) -> None:
        p = (PeerAddress(ip="1.2.3.4", port=80),)
        assert MsgSharePeers(peers=p) == MsgSharePeers(peers=p)
        assert MsgSharePeers(peers=p) != MsgSharePeers(peers=())


class TestMsgDone:
    """MsgDone message construction."""

    def test_construction(self) -> None:
        msg = MsgDone()
        assert msg.msg_id == 2

    def test_equality(self) -> None:
        assert MsgDone() == MsgDone()


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


class TestEncoding:
    """CBOR encoding produces the correct wire format."""

    def test_encode_share_request(self) -> None:
        encoded = encode_share_request(10)
        decoded = cbor2.loads(encoded)
        assert decoded == [0, 10]

    def test_encode_share_request_zero(self) -> None:
        encoded = encode_share_request(0)
        decoded = cbor2.loads(encoded)
        assert decoded == [0, 0]

    def test_encode_share_request_max(self) -> None:
        encoded = encode_share_request(255)
        decoded = cbor2.loads(encoded)
        assert decoded == [0, 255]

    def test_encode_share_request_invalid_negative(self) -> None:
        with pytest.raises(ValueError, match="word8"):
            encode_share_request(-1)

    def test_encode_share_request_invalid_too_large(self) -> None:
        with pytest.raises(ValueError, match="word8"):
            encode_share_request(256)

    def test_encode_share_peers_empty(self) -> None:
        encoded = encode_share_peers([])
        decoded = cbor2.loads(encoded)
        assert decoded == [1, []]

    def test_encode_share_peers_single_ipv4(self) -> None:
        peers = [PeerAddress(ip="192.168.1.1", port=3001)]
        encoded = encode_share_peers(peers)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 1
        assert len(decoded[1]) == 1
        assert decoded[1][0][0] == 0  # IPv4 tag
        assert decoded[1][0][1] == 0xC0A80101
        assert decoded[1][0][2] == 3001

    def test_encode_share_peers_mixed(self) -> None:
        peers = [
            PeerAddress(ip="10.0.0.1", port=3001),
            PeerAddress(ip="::1", port=3002, is_ipv6=True),
        ]
        encoded = encode_share_peers(peers)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 1
        assert len(decoded[1]) == 2
        assert decoded[1][0][0] == 0  # IPv4 tag
        assert decoded[1][1][0] == 1  # IPv6 tag

    def test_encode_done(self) -> None:
        encoded = encode_done()
        decoded = cbor2.loads(encoded)
        assert decoded == [2]

    def test_encode_share_request_boundary_amounts(self) -> None:
        """All boundary amounts encode correctly."""
        for amount in [0, 1, 10, 127, 128, 255]:
            encoded = encode_share_request(amount)
            decoded = cbor2.loads(encoded)
            assert decoded == [0, amount]


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


class TestDecoding:
    """CBOR decoding recovers the original message."""

    def test_decode_share_request(self) -> None:
        cbor_bytes = cbor2.dumps([0, 10])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgShareRequest)
        assert msg.amount == 10

    def test_decode_share_peers_empty(self) -> None:
        cbor_bytes = cbor2.dumps([1, []])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgSharePeers)
        assert msg.peers == ()

    def test_decode_share_peers_with_ipv4(self) -> None:
        cbor_bytes = cbor2.dumps([1, [[0, 0xC0A80101, 3001]]])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgSharePeers)
        assert len(msg.peers) == 1
        assert msg.peers[0].ip == "192.168.1.1"
        assert msg.peers[0].port == 3001
        assert msg.peers[0].is_ipv6 is False

    def test_decode_share_peers_with_ipv6(self) -> None:
        cbor_bytes = cbor2.dumps([1, [[1, 0, 0, 0, 1, 3001]]])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgSharePeers)
        assert len(msg.peers) == 1
        assert msg.peers[0].ip == "::1"
        assert msg.peers[0].port == 3001
        assert msg.peers[0].is_ipv6 is True

    def test_decode_share_peers_mixed(self) -> None:
        cbor_bytes = cbor2.dumps([
            1,
            [
                [0, 0x0A000001, 3001],
                [1, 0x20010DB8, 0, 0, 1, 3002],
            ],
        ])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgSharePeers)
        assert len(msg.peers) == 2
        assert msg.peers[0].is_ipv6 is False
        assert msg.peers[0].ip == "10.0.0.1"
        assert msg.peers[1].is_ipv6 is True

    def test_decode_done(self) -> None:
        cbor_bytes = cbor2.dumps([2])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgDone)

    def test_decode_unknown_message_id(self) -> None:
        cbor_bytes = cbor2.dumps([99])
        with pytest.raises(ValueError, match="Unknown peer-sharing message ID"):
            decode_message(cbor_bytes)

    def test_decode_not_a_list(self) -> None:
        cbor_bytes = cbor2.dumps(42)
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor_bytes)

    def test_decode_empty_list(self) -> None:
        cbor_bytes = cbor2.dumps([])
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor_bytes)

    def test_decode_share_request_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([0])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_message(cbor_bytes)

    def test_decode_share_request_extra_element(self) -> None:
        cbor_bytes = cbor2.dumps([0, 10, 99])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_message(cbor_bytes)

    def test_decode_share_peers_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([1])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_message(cbor_bytes)

    def test_decode_share_peers_not_list(self) -> None:
        cbor_bytes = cbor2.dumps([1, 42])
        with pytest.raises(ValueError, match="expected iterable of peers"):
            decode_message(cbor_bytes)

    def test_decode_done_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([2, 0])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_message(cbor_bytes)

    def test_decode_amount_not_integer(self) -> None:
        cbor_bytes = cbor2.dumps([0, "hello"])
        with pytest.raises(ValueError, match="must be an integer"):
            decode_message(cbor_bytes)

    def test_decode_amount_is_bool(self) -> None:
        cbor_bytes = cbor2.dumps([0, True])
        with pytest.raises(ValueError, match="must be an integer"):
            decode_message(cbor_bytes)

    def test_decode_amount_out_of_range(self) -> None:
        cbor_bytes = cbor2.dumps([0, 300])
        with pytest.raises(ValueError, match="word8"):
            decode_message(cbor_bytes)

    def test_decode_amount_negative(self) -> None:
        cbor_bytes = cbor2.dumps([0, -1])
        with pytest.raises(ValueError, match="word8"):
            decode_message(cbor_bytes)


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Encode then decode recovers the original message."""

    def test_share_request_round_trip(self) -> None:
        for amount in [0, 1, 10, 255]:
            encoded = encode_share_request(amount)
            decoded = decode_message(encoded)
            assert isinstance(decoded, MsgShareRequest)
            assert decoded.amount == amount

    def test_share_peers_empty_round_trip(self) -> None:
        encoded = encode_share_peers([])
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgSharePeers)
        assert decoded.peers == ()

    def test_share_peers_ipv4_round_trip(self) -> None:
        peers = [PeerAddress(ip="192.168.1.1", port=3001)]
        encoded = encode_share_peers(peers)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgSharePeers)
        assert len(decoded.peers) == 1
        assert decoded.peers[0] == peers[0]

    def test_share_peers_ipv6_round_trip(self) -> None:
        peers = [PeerAddress(ip="::1", port=3001, is_ipv6=True)]
        encoded = encode_share_peers(peers)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgSharePeers)
        assert len(decoded.peers) == 1
        assert decoded.peers[0] == peers[0]

    def test_share_peers_mixed_round_trip(self) -> None:
        peers = [
            PeerAddress(ip="10.0.0.1", port=3001),
            PeerAddress(ip="::1", port=3002, is_ipv6=True),
            PeerAddress(ip="2001:db8::1", port=3003, is_ipv6=True),
        ]
        encoded = encode_share_peers(peers)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgSharePeers)
        assert len(decoded.peers) == 3
        # IPv4 round-trips exactly
        assert decoded.peers[0] == peers[0]
        # IPv6 round-trips (inet_ntop may normalize)
        for i in range(len(peers)):
            assert decoded.peers[i].port == peers[i].port
            assert decoded.peers[i].is_ipv6 == peers[i].is_ipv6
            assert (
                encode_peer_address(decoded.peers[i])
                == encode_peer_address(peers[i])
            )

    def test_done_round_trip(self) -> None:
        encoded = encode_done()
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgDone)
        assert decoded == MsgDone()


# ---------------------------------------------------------------------------
# Wire format verification
# ---------------------------------------------------------------------------


class TestWireFormat:
    """Verify exact CBOR wire format matches the CDDL spec."""

    def test_share_request_wire_format(self) -> None:
        """MsgShareRequest [0, 10] should encode as CBOR array."""
        encoded = encode_share_request(10)
        wire = cbor2.loads(encoded)
        assert wire == [0, 10]

    def test_share_peers_wire_format_ipv4(self) -> None:
        """Peer address uses [0, word32, word16] for IPv4."""
        peers = [PeerAddress(ip="1.2.3.4", port=80)]
        encoded = encode_share_peers(peers)
        wire = cbor2.loads(encoded)
        assert wire[0] == 1
        assert wire[1][0] == [0, 0x01020304, 80]

    def test_share_peers_wire_format_ipv6(self) -> None:
        """Peer address uses [1, w0, w1, w2, w3, port] for IPv6."""
        peers = [PeerAddress(ip="::1", port=80, is_ipv6=True)]
        encoded = encode_share_peers(peers)
        wire = cbor2.loads(encoded)
        assert wire[0] == 1
        assert wire[1][0] == [1, 0, 0, 0, 1, 80]

    def test_done_wire_format(self) -> None:
        """MsgDone wire format is always [2]."""
        wire = cbor2.loads(encode_done())
        assert wire == [2]


# ---------------------------------------------------------------------------
# Mock channel for protocol round-trip tests
# ---------------------------------------------------------------------------


@dataclass
class _MockChannelEnd:
    send_q: asyncio.Queue[bytes]
    recv_q: asyncio.Queue[bytes]

    async def send(self, payload: bytes) -> None:
        await self.send_q.put(payload)

    async def recv(self) -> bytes:
        return await self.recv_q.get()


@dataclass
class MockChannel:
    """In-memory bidirectional channel for direct client-server testing."""

    _a_to_b: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)
    _b_to_a: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)

    @property
    def client_side(self) -> _MockChannelEnd:
        return _MockChannelEnd(send_q=self._a_to_b, recv_q=self._b_to_a)

    @property
    def server_side(self) -> _MockChannelEnd:
        return _MockChannelEnd(send_q=self._b_to_a, recv_q=self._a_to_b)


# ---------------------------------------------------------------------------
# Protocol round-trip tests
# ---------------------------------------------------------------------------

from vibe.cardano.network.peersharing_protocol import (
    PeerSharingCodec,
    PeerSharingProtocol,
    PeerSharingState,
    PsMsgDone,
    PsMsgSharePeers,
    PsMsgShareRequest,
    run_peer_sharing_client,
    run_peer_sharing_server,
)
from vibe.core.protocols.agency import PeerRole
from vibe.core.protocols.runner import ProtocolRunner


class TestProtocolRoundTrip:
    """End-to-end protocol round-trip tests using MockChannel."""

    @pytest.mark.asyncio
    async def test_single_request_response(self) -> None:
        """Client requests peers, server responds, both return to StIdle."""
        ch = MockChannel()
        protocol_c = PeerSharingProtocol()
        protocol_s = PeerSharingProtocol()
        codec = PeerSharingCodec()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=protocol_c,
            codec=codec,
            channel=ch.client_side,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol_s,
            codec=codec,
            channel=ch.server_side,
        )

        # Client sends request
        await client_runner.send_message(PsMsgShareRequest(amount=5))
        assert client_runner.state == PeerSharingState.StBusy

        # Server receives request
        msg = await server_runner.recv_message()
        assert isinstance(msg, PsMsgShareRequest)
        assert msg.amount == 5
        assert server_runner.state == PeerSharingState.StBusy

        # Server sends response
        peers = (
            PeerAddress(ip="10.0.0.1", port=3001),
            PeerAddress(ip="10.0.0.2", port=3002),
        )
        await server_runner.send_message(PsMsgSharePeers(peers=peers))
        assert server_runner.state == PeerSharingState.StIdle

        # Client receives response
        resp = await client_runner.recv_message()
        assert isinstance(resp, PsMsgSharePeers)
        assert len(resp.peers) == 2
        assert resp.peers[0].ip == "10.0.0.1"
        assert resp.peers[1].ip == "10.0.0.2"
        assert client_runner.state == PeerSharingState.StIdle

    @pytest.mark.asyncio
    async def test_multiple_request_response_cycles(self) -> None:
        """Three consecutive request/response cycles work correctly."""
        ch = MockChannel()
        codec = PeerSharingCodec()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=PeerSharingProtocol(),
            codec=codec,
            channel=ch.client_side,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=PeerSharingProtocol(),
            codec=codec,
            channel=ch.server_side,
        )

        for cycle in range(3):
            amount = (cycle + 1) * 3  # 3, 6, 9

            # Client request
            await client_runner.send_message(PsMsgShareRequest(amount=amount))

            # Server receives and responds
            req = await server_runner.recv_message()
            assert isinstance(req, PsMsgShareRequest)
            assert req.amount == amount

            peers = tuple(
                PeerAddress(ip=f"10.0.{cycle}.{i}", port=3000 + i)
                for i in range(amount)
            )
            await server_runner.send_message(PsMsgSharePeers(peers=peers))

            # Client receives
            resp = await client_runner.recv_message()
            assert isinstance(resp, PsMsgSharePeers)
            assert len(resp.peers) == amount

            # Both back to StIdle
            assert client_runner.state == PeerSharingState.StIdle
            assert server_runner.state == PeerSharingState.StIdle

    @pytest.mark.asyncio
    async def test_client_done_terminates(self) -> None:
        """Client sends MsgDone, both reach StDone."""
        ch = MockChannel()
        codec = PeerSharingCodec()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=PeerSharingProtocol(),
            codec=codec,
            channel=ch.client_side,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=PeerSharingProtocol(),
            codec=codec,
            channel=ch.server_side,
        )

        # Client sends Done from StIdle
        await client_runner.send_message(PsMsgDone())
        assert client_runner.state == PeerSharingState.StDone
        assert client_runner.is_done is True

        # Server receives Done
        msg = await server_runner.recv_message()
        assert isinstance(msg, PsMsgDone)
        assert server_runner.state == PeerSharingState.StDone
        assert server_runner.is_done is True

    @pytest.mark.asyncio
    async def test_server_respects_amount(self) -> None:
        """Server returns fewer or equal peers than the requested amount."""
        ch = MockChannel()
        codec = PeerSharingCodec()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=PeerSharingProtocol(),
            codec=codec,
            channel=ch.client_side,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=PeerSharingProtocol(),
            codec=codec,
            channel=ch.server_side,
        )

        # Client requests 10 peers
        await client_runner.send_message(PsMsgShareRequest(amount=10))

        req = await server_runner.recv_message()
        assert isinstance(req, PsMsgShareRequest)
        assert req.amount == 10

        # Server responds with only 3 (fewer than requested — valid)
        peers = tuple(
            PeerAddress(ip=f"172.16.0.{i}", port=3001)
            for i in range(3)
        )
        await server_runner.send_message(PsMsgSharePeers(peers=peers))

        resp = await client_runner.recv_message()
        assert isinstance(resp, PsMsgSharePeers)
        assert len(resp.peers) == 3
        assert len(resp.peers) <= 10

    @pytest.mark.asyncio
    async def test_runner_functions_client_server(self) -> None:
        """run_peer_sharing_client and run_peer_sharing_server work together."""
        ch = MockChannel()
        stop_event = asyncio.Event()
        received_peers: list[list[PeerAddress]] = []

        test_peers = [
            PeerAddress(ip="10.0.0.1", port=3001),
            PeerAddress(ip="10.0.0.2", port=3002),
        ]

        async def on_peers(peers: list[PeerAddress]) -> None:
            received_peers.append(peers)
            # After receiving one batch, signal stop
            stop_event.set()

        async def provide_peers(amount: int) -> list[PeerAddress]:
            return test_peers[:amount]

        # Run both sides concurrently with a short interval
        async with asyncio.timeout(5.0):
            await asyncio.gather(
                run_peer_sharing_client(
                    ch.client_side,
                    on_peers_received=on_peers,
                    request_interval=0.01,  # Very short for testing
                    max_peers_per_request=10,
                    stop_event=stop_event,
                    peer_info="test",
                ),
                run_peer_sharing_server(
                    ch.server_side,
                    peer_provider=provide_peers,
                    stop_event=None,  # Server exits on MsgDone from client
                ),
            )

        assert len(received_peers) == 1
        assert len(received_peers[0]) == 2
        assert received_peers[0][0].ip == "10.0.0.1"
        assert received_peers[0][1].ip == "10.0.0.2"

    @pytest.mark.asyncio
    async def test_empty_peer_response(self) -> None:
        """Server can respond with zero peers."""
        ch = MockChannel()
        codec = PeerSharingCodec()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=PeerSharingProtocol(),
            codec=codec,
            channel=ch.client_side,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=PeerSharingProtocol(),
            codec=codec,
            channel=ch.server_side,
        )

        await client_runner.send_message(PsMsgShareRequest(amount=5))
        await server_runner.recv_message()

        # Server responds with empty list
        await server_runner.send_message(PsMsgSharePeers(peers=()))

        resp = await client_runner.recv_message()
        assert isinstance(resp, PsMsgSharePeers)
        assert len(resp.peers) == 0
        assert client_runner.state == PeerSharingState.StIdle
