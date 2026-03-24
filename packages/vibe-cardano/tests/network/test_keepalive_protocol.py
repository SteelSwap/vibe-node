"""Tests for keep-alive miniprotocol typed protocol FSM and codec.

Tests cover:
- Protocol state machine: initial state, agency at each state, valid messages
- Typed message wrappers: construction, state transitions
- Codec: encode/decode round-trip through the KeepAliveCodec
- KeepAliveClient: ping/pong exchange, done termination, cookie mismatch
- Edge cases: invalid states, wrong message types
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.keepalive import (
    MsgDone,
    MsgKeepAlive,
    MsgKeepAliveResponse,
)
from vibe.cardano.network.keepalive_protocol import (
    KaMsgDone,
    KaMsgKeepAlive,
    KaMsgKeepAliveResponse,
    KeepAliveClient,
    KeepAliveCodec,
    KeepAliveProtocol,
    KeepAliveState,
)
from vibe.core.protocols import Agency, ProtocolError

# ---------------------------------------------------------------------------
# Protocol state machine tests
# ---------------------------------------------------------------------------


class TestKeepAliveProtocol:
    """Verify the protocol state machine definition."""

    def setup_method(self) -> None:
        self.protocol = KeepAliveProtocol()

    def test_initial_state(self) -> None:
        assert self.protocol.initial_state() == KeepAliveState.StClient

    def test_agency_client(self) -> None:
        assert self.protocol.agency(KeepAliveState.StClient) == Agency.Client

    def test_agency_server(self) -> None:
        assert self.protocol.agency(KeepAliveState.StServer) == Agency.Server

    def test_agency_done(self) -> None:
        assert self.protocol.agency(KeepAliveState.StDone) == Agency.Nobody

    def test_valid_messages_client(self) -> None:
        msgs = self.protocol.valid_messages(KeepAliveState.StClient)
        assert KaMsgKeepAlive in msgs
        assert KaMsgDone in msgs
        assert len(msgs) == 2

    def test_valid_messages_server(self) -> None:
        msgs = self.protocol.valid_messages(KeepAliveState.StServer)
        assert KaMsgKeepAliveResponse in msgs
        assert len(msgs) == 1

    def test_valid_messages_done(self) -> None:
        msgs = self.protocol.valid_messages(KeepAliveState.StDone)
        assert len(msgs) == 0


# ---------------------------------------------------------------------------
# Typed message wrapper tests
# ---------------------------------------------------------------------------


class TestTypedMessages:
    """Verify typed message wrappers carry correct state transitions."""

    def test_ka_msg_keep_alive(self) -> None:
        msg = KaMsgKeepAlive(cookie=42)
        assert msg.from_state == KeepAliveState.StClient
        assert msg.to_state == KeepAliveState.StServer
        assert msg.cookie == 42
        assert msg.inner == MsgKeepAlive(cookie=42)

    def test_ka_msg_keep_alive_response(self) -> None:
        msg = KaMsgKeepAliveResponse(cookie=42)
        assert msg.from_state == KeepAliveState.StServer
        assert msg.to_state == KeepAliveState.StClient
        assert msg.cookie == 42
        assert msg.inner == MsgKeepAliveResponse(cookie=42)

    def test_ka_msg_done(self) -> None:
        msg = KaMsgDone()
        assert msg.from_state == KeepAliveState.StClient
        assert msg.to_state == KeepAliveState.StDone
        assert msg.inner == MsgDone()

    def test_ka_msg_keep_alive_boundary_cookies(self) -> None:
        msg_min = KaMsgKeepAlive(cookie=0)
        assert msg_min.cookie == 0
        msg_max = KaMsgKeepAlive(cookie=65535)
        assert msg_max.cookie == 65535


# ---------------------------------------------------------------------------
# Codec tests
# ---------------------------------------------------------------------------


class TestKeepAliveCodec:
    """Verify the codec encodes and decodes correctly."""

    def setup_method(self) -> None:
        self.codec = KeepAliveCodec()

    def test_encode_keep_alive(self) -> None:
        msg = KaMsgKeepAlive(cookie=42)
        encoded = self.codec.encode(msg)
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0

    def test_encode_response(self) -> None:
        msg = KaMsgKeepAliveResponse(cookie=42)
        encoded = self.codec.encode(msg)
        assert isinstance(encoded, bytes)

    def test_encode_done(self) -> None:
        msg = KaMsgDone()
        encoded = self.codec.encode(msg)
        assert isinstance(encoded, bytes)

    def test_round_trip_keep_alive(self) -> None:
        original = KaMsgKeepAlive(cookie=12345)
        encoded = self.codec.encode(original)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, KaMsgKeepAlive)
        assert decoded.cookie == original.cookie

    def test_round_trip_response(self) -> None:
        original = KaMsgKeepAliveResponse(cookie=54321)
        encoded = self.codec.encode(original)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, KaMsgKeepAliveResponse)
        assert decoded.cookie == original.cookie

    def test_round_trip_done(self) -> None:
        original = KaMsgDone()
        encoded = self.codec.encode(original)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, KaMsgDone)

    def test_decode_preserves_state_transitions(self) -> None:
        """Decoded messages have correct from_state/to_state."""
        msg = KaMsgKeepAlive(cookie=100)
        decoded = self.codec.decode(self.codec.encode(msg))
        assert decoded.from_state == KeepAliveState.StClient
        assert decoded.to_state == KeepAliveState.StServer

        resp = KaMsgKeepAliveResponse(cookie=100)
        decoded_resp = self.codec.decode(self.codec.encode(resp))
        assert decoded_resp.from_state == KeepAliveState.StServer
        assert decoded_resp.to_state == KeepAliveState.StClient

        done = KaMsgDone()
        decoded_done = self.codec.decode(self.codec.encode(done))
        assert decoded_done.from_state == KeepAliveState.StClient
        assert decoded_done.to_state == KeepAliveState.StDone

    @given(cookie=st.integers(min_value=0, max_value=65535))
    @settings(max_examples=200)
    def test_hypothesis_round_trip_keep_alive(self, cookie: int) -> None:
        """Property: encode->decode is identity for keep-alive messages."""
        original = KaMsgKeepAlive(cookie=cookie)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, KaMsgKeepAlive)
        assert decoded.cookie == cookie

    @given(cookie=st.integers(min_value=0, max_value=65535))
    @settings(max_examples=200)
    def test_hypothesis_round_trip_response(self, cookie: int) -> None:
        """Property: encode->decode is identity for response messages."""
        original = KaMsgKeepAliveResponse(cookie=cookie)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, KaMsgKeepAliveResponse)
        assert decoded.cookie == cookie


# ---------------------------------------------------------------------------
# FSM transition tests
# ---------------------------------------------------------------------------


class TestFSMTransitions:
    """Verify the full state machine transition graph."""

    def setup_method(self) -> None:
        self.protocol = KeepAliveProtocol()

    def test_client_to_server_via_keep_alive(self) -> None:
        """StClient -> StServer via MsgKeepAlive."""
        msg = KaMsgKeepAlive(cookie=1)
        assert msg.from_state == KeepAliveState.StClient
        assert msg.to_state == KeepAliveState.StServer
        # Verify agency: client has agency in StClient
        assert self.protocol.agency(msg.from_state) == Agency.Client

    def test_server_to_client_via_response(self) -> None:
        """StServer -> StClient via MsgKeepAliveResponse."""
        msg = KaMsgKeepAliveResponse(cookie=1)
        assert msg.from_state == KeepAliveState.StServer
        assert msg.to_state == KeepAliveState.StClient
        # Verify agency: server has agency in StServer
        assert self.protocol.agency(msg.from_state) == Agency.Server

    def test_client_to_done_via_msg_done(self) -> None:
        """StClient -> StDone via MsgDone."""
        msg = KaMsgDone()
        assert msg.from_state == KeepAliveState.StClient
        assert msg.to_state == KeepAliveState.StDone
        # Verify agency: client has agency in StClient
        assert self.protocol.agency(msg.from_state) == Agency.Client

    def test_done_is_terminal(self) -> None:
        """StDone has no valid messages (terminal state)."""
        assert self.protocol.agency(KeepAliveState.StDone) == Agency.Nobody
        assert len(self.protocol.valid_messages(KeepAliveState.StDone)) == 0

    def test_full_ping_pong_cycle(self) -> None:
        """Walk through a complete ping -> pong -> done cycle."""
        state = self.protocol.initial_state()
        assert state == KeepAliveState.StClient

        # Client sends ping
        ping = KaMsgKeepAlive(cookie=42)
        assert ping.from_state == state
        state = ping.to_state
        assert state == KeepAliveState.StServer

        # Server sends pong
        pong = KaMsgKeepAliveResponse(cookie=42)
        assert pong.from_state == state
        state = pong.to_state
        assert state == KeepAliveState.StClient

        # Client terminates
        done = KaMsgDone()
        assert done.from_state == state
        state = done.to_state
        assert state == KeepAliveState.StDone
        assert self.protocol.agency(state) == Agency.Nobody

    def test_multiple_ping_pong_cycles(self) -> None:
        """Multiple pings before done is valid."""
        state = self.protocol.initial_state()

        for cookie in [0, 100, 65535]:
            ping = KaMsgKeepAlive(cookie=cookie)
            assert ping.from_state == state
            state = ping.to_state
            assert state == KeepAliveState.StServer

            pong = KaMsgKeepAliveResponse(cookie=cookie)
            assert pong.from_state == state
            state = pong.to_state
            assert state == KeepAliveState.StClient

        done = KaMsgDone()
        assert done.from_state == state
        state = done.to_state
        assert state == KeepAliveState.StDone


# ---------------------------------------------------------------------------
# KeepAliveClient tests
# ---------------------------------------------------------------------------


class TestKeepAliveClient:
    """Test the high-level KeepAliveClient."""

    def _make_client(self) -> tuple[KeepAliveClient, MagicMock]:
        """Create a KeepAliveClient with a mocked runner."""
        runner = MagicMock()
        runner.state = KeepAliveState.StClient
        runner.is_done = False
        runner.send_message = AsyncMock()
        runner.recv_message = AsyncMock()
        client = KeepAliveClient(runner)
        return client, runner

    @pytest.mark.asyncio
    async def test_ping_sends_and_receives(self) -> None:
        client, runner = self._make_client()
        runner.recv_message.return_value = KaMsgKeepAliveResponse(cookie=42)

        result = await client.ping(cookie=42)

        assert result == 42
        runner.send_message.assert_called_once()
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, KaMsgKeepAlive)
        assert sent.cookie == 42

    @pytest.mark.asyncio
    async def test_ping_auto_cookie(self) -> None:
        """When no cookie is provided, a random one is generated."""
        client, runner = self._make_client()
        # We need to capture what cookie was sent and echo it back
        captured_cookie = None

        async def capture_send(msg: KaMsgKeepAlive) -> None:
            nonlocal captured_cookie
            captured_cookie = msg.cookie

        runner.send_message.side_effect = capture_send

        async def echo_response() -> KaMsgKeepAliveResponse:
            return KaMsgKeepAliveResponse(cookie=captured_cookie)

        runner.recv_message.side_effect = echo_response

        result = await client.ping()
        assert 0 <= result <= 65535

    @pytest.mark.asyncio
    async def test_ping_cookie_mismatch_raises(self) -> None:
        client, runner = self._make_client()
        runner.recv_message.return_value = KaMsgKeepAliveResponse(cookie=99)

        with pytest.raises(ProtocolError, match="Cookie mismatch"):
            await client.ping(cookie=42)

    @pytest.mark.asyncio
    async def test_ping_unexpected_message_raises(self) -> None:
        client, runner = self._make_client()
        runner.recv_message.return_value = KaMsgDone()

        with pytest.raises(ProtocolError, match="Expected MsgKeepAliveResponse"):
            await client.ping(cookie=42)

    @pytest.mark.asyncio
    async def test_done_sends_msg_done(self) -> None:
        client, runner = self._make_client()

        await client.done()

        runner.send_message.assert_called_once()
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, KaMsgDone)

    def test_state_property(self) -> None:
        client, runner = self._make_client()
        runner.state = KeepAliveState.StServer
        assert client.state == KeepAliveState.StServer

    def test_is_done_property(self) -> None:
        client, runner = self._make_client()
        runner.is_done = True
        assert client.is_done is True


# ---------------------------------------------------------------------------
# Direct client-server pairing test (Haskell prop_direct pattern)
# ---------------------------------------------------------------------------


class TestDirectClientServer:
    """Direct client-server pairing via message passing.

    Follows the Haskell ``prop_direct`` test pattern: a KeepAliveClient
    and a mock server exchange messages through connected in-memory
    channels without any real networking.

    Haskell reference:
        Ouroboros.Network.Protocol.KeepAlive.Test (prop_direct)
    """

    @staticmethod
    def _make_connected_channels() -> tuple[MagicMock, MagicMock]:
        """Create a pair of connected mock channels.

        Returns two channels where sending on one delivers to the other's
        recv, simulating a bidirectional pipe.
        """
        client_to_server: asyncio.Queue[bytes] = asyncio.Queue()
        server_to_client: asyncio.Queue[bytes] = asyncio.Queue()

        client_channel = MagicMock()
        server_channel = MagicMock()

        async def client_send(data: bytes) -> None:
            await client_to_server.put(data)

        async def client_recv() -> bytes:
            return await server_to_client.get()

        async def server_send(data: bytes) -> None:
            await server_to_client.put(data)

        async def server_recv() -> bytes:
            return await client_to_server.get()

        client_channel.send = AsyncMock(side_effect=client_send)
        client_channel.recv = AsyncMock(side_effect=client_recv)
        server_channel.send = AsyncMock(side_effect=server_send)
        server_channel.recv = AsyncMock(side_effect=server_recv)

        return client_channel, server_channel

    @staticmethod
    async def _mock_server(
        server_channel: MagicMock,
        num_pings: int,
    ) -> list[int]:
        """Mock keep-alive server that echoes cookies.

        Reads MsgKeepAlive messages, responds with MsgKeepAliveResponse
        echoing the same cookie, then expects MsgDone.

        Returns the list of cookies received.
        """
        from vibe.cardano.network.keepalive import MsgKeepAlive as RawKeepAlive
        from vibe.cardano.network.keepalive import (
            decode_client_message,
            encode_keep_alive_response,
        )

        cookies: list[int] = []
        for _ in range(num_pings):
            data = await server_channel.recv()
            msg = decode_client_message(data)
            assert isinstance(msg, RawKeepAlive)
            cookies.append(msg.cookie)
            response_bytes = encode_keep_alive_response(msg.cookie)
            await server_channel.send(response_bytes)

        # Expect MsgDone
        data = await server_channel.recv()
        msg = decode_client_message(data)
        assert isinstance(msg, MsgDone)

        return cookies

    @pytest.mark.asyncio
    async def test_single_ping_pong(self) -> None:
        """Client sends one ping, server echoes cookie, client sends done."""
        from vibe.cardano.network.keepalive_protocol import (
            KeepAliveClient,
            KeepAliveCodec,
            KeepAliveProtocol,
        )
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        client_ch, server_ch = self._make_connected_channels()
        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=KeepAliveProtocol(),
            codec=KeepAliveCodec(),
            channel=client_ch,
        )
        client = KeepAliveClient(runner)

        cookie = 12345
        server_task = asyncio.create_task(self._mock_server(server_ch, num_pings=1))

        echoed = await client.ping(cookie=cookie)
        assert echoed == cookie

        await client.done()
        server_cookies = await server_task
        assert server_cookies == [cookie]
        assert client.is_done

    @pytest.mark.asyncio
    async def test_multiple_ping_pong_rounds(self) -> None:
        """Multiple ping/pong rounds with different cookies."""
        from vibe.cardano.network.keepalive_protocol import (
            KeepAliveClient,
            KeepAliveCodec,
            KeepAliveProtocol,
        )
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        client_ch, server_ch = self._make_connected_channels()
        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=KeepAliveProtocol(),
            codec=KeepAliveCodec(),
            channel=client_ch,
        )
        client = KeepAliveClient(runner)

        cookies = [0, 42, 1000, 65535]
        server_task = asyncio.create_task(self._mock_server(server_ch, num_pings=len(cookies)))

        for cookie in cookies:
            echoed = await client.ping(cookie=cookie)
            assert echoed == cookie

        await client.done()
        server_cookies = await server_task
        assert server_cookies == cookies
        assert client.is_done

    @pytest.mark.asyncio
    async def test_clean_termination(self) -> None:
        """Protocol terminates cleanly with MsgDone (no pings)."""
        from vibe.cardano.network.keepalive_protocol import (
            KeepAliveClient,
            KeepAliveCodec,
            KeepAliveProtocol,
        )
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        client_ch, server_ch = self._make_connected_channels()
        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=KeepAliveProtocol(),
            codec=KeepAliveCodec(),
            channel=client_ch,
        )
        client = KeepAliveClient(runner)

        server_task = asyncio.create_task(self._mock_server(server_ch, num_pings=0))

        await client.done()
        server_cookies = await server_task
        assert server_cookies == []
        assert client.is_done

    @given(cookies=st.lists(st.integers(min_value=0, max_value=65535), min_size=1, max_size=10))
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_hypothesis_direct_pairing(self, cookies: list[int]) -> None:
        """Property: any sequence of uint16 cookies roundtrips correctly."""
        from vibe.cardano.network.keepalive_protocol import (
            KeepAliveClient,
            KeepAliveCodec,
            KeepAliveProtocol,
        )
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        client_ch, server_ch = self._make_connected_channels()
        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=KeepAliveProtocol(),
            codec=KeepAliveCodec(),
            channel=client_ch,
        )
        client = KeepAliveClient(runner)

        server_task = asyncio.create_task(self._mock_server(server_ch, num_pings=len(cookies)))

        for cookie in cookies:
            echoed = await client.ping(cookie=cookie)
            assert echoed == cookie

        await client.done()
        server_cookies = await server_task
        assert server_cookies == cookies
