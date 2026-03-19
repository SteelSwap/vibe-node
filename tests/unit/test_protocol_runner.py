"""Tests for the ProtocolRunner — driving a typed FSM over a mux channel.

Uses the same Ping/Pong test protocol from test_protocol_framework.py,
but exercises the full stack: codec encode/decode, mux channel transport,
agency validation, and state advancement.

Test coverage maps to test_specifications DB entries:
    - test_msg_await_reply_codec_roundtrip: codec roundtrip integrity
    - test_miniprotocol_error_triggers_mux_terminated: error propagation
    - Agency validation on send/recv (agency enforcement tests)
"""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass
from typing import Any

import pytest

from vibe.core.multiplexer.mux import MiniProtocolChannel, MuxClosedError
from vibe.core.protocols import (
    Agency,
    Message,
    PeerRole,
    Protocol,
    ProtocolError,
)
from vibe.core.protocols.codec import Codec, CodecError
from vibe.core.protocols.runner import ProtocolRunner


# ---------------------------------------------------------------------------
# Ping/Pong test protocol (same as test_protocol_framework.py)
# ---------------------------------------------------------------------------


class PingPongState(enum.Enum):
    StIdle = "idle"
    StBusy = "busy"
    StDone = "done"


class MsgPing(Message[PingPongState]):
    def __init__(self) -> None:
        super().__init__(PingPongState.StIdle, PingPongState.StBusy)


class MsgPong(Message[PingPongState]):
    def __init__(self) -> None:
        super().__init__(PingPongState.StBusy, PingPongState.StIdle)


class MsgDone(Message[PingPongState]):
    def __init__(self) -> None:
        super().__init__(PingPongState.StIdle, PingPongState.StDone)


class PingPongProtocol(Protocol[PingPongState]):
    def initial_state(self) -> PingPongState:
        return PingPongState.StIdle

    def agency(self, state: PingPongState) -> Agency:
        match state:
            case PingPongState.StIdle:
                return Agency.Client
            case PingPongState.StBusy:
                return Agency.Server
            case PingPongState.StDone:
                return Agency.Nobody
        raise ValueError(f"Unknown state: {state}")  # pragma: no cover

    def valid_messages(
        self, state: PingPongState
    ) -> frozenset[type[Message[PingPongState]]]:
        match state:
            case PingPongState.StIdle:
                return frozenset({MsgPing, MsgDone})
            case PingPongState.StBusy:
                return frozenset({MsgPong})
            case PingPongState.StDone:
                return frozenset()
        raise ValueError(f"Unknown state: {state}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Mock codec — simple tag-based encoding for testing
# ---------------------------------------------------------------------------

# Wire format: single byte tag.
_TAG_PING = b"\x01"
_TAG_PONG = b"\x02"
_TAG_DONE = b"\x03"


class PingPongCodec:
    """Trivial codec for the Ping/Pong test protocol.

    Encodes each message as a single-byte tag. This is NOT real CBOR —
    it's the simplest possible codec for testing the runner logic.
    """

    def encode(self, message: Message) -> bytes:
        if isinstance(message, MsgPing):
            return _TAG_PING
        elif isinstance(message, MsgPong):
            return _TAG_PONG
        elif isinstance(message, MsgDone):
            return _TAG_DONE
        raise CodecError(f"Unknown message type: {type(message).__name__}")

    def decode(self, data: bytes) -> Message:
        if data == _TAG_PING:
            return MsgPing()
        elif data == _TAG_PONG:
            return MsgPong()
        elif data == _TAG_DONE:
            return MsgDone()
        raise CodecError(f"Unknown tag: {data!r}")


# ---------------------------------------------------------------------------
# Mock channel — in-memory queue pair (no real mux needed)
# ---------------------------------------------------------------------------


class MockChannel:
    """In-memory mock of MiniProtocolChannel for unit tests.

    Provides the same send/recv interface as MiniProtocolChannel but
    backed by simple asyncio queues. A pair of MockChannels can be
    cross-wired to simulate two ends of a mux channel.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False
        self.protocol_id = 0
        self.is_initiator = True

    async def send(self, payload: bytes) -> None:
        if self._closed:
            raise MuxClosedError("mock channel closed")
        await self._queue.put(payload)

    async def recv(self) -> bytes:
        if self._closed:
            raise MuxClosedError("mock channel closed")
        return await self._queue.get()

    def close(self) -> None:
        self._closed = True


def make_channel_pair() -> tuple[MockChannel, MockChannel]:
    """Create a cross-wired channel pair.

    Returns (client_channel, server_channel) where:
    - client sends -> server receives
    - server sends -> client receives
    """
    # We cross-wire by sharing queues: client's send goes to server's recv
    # and vice versa.
    c2s: asyncio.Queue[bytes] = asyncio.Queue()
    s2c: asyncio.Queue[bytes] = asyncio.Queue()

    client = MockChannel()
    server = MockChannel()

    # Override send/recv to cross-wire.
    client.send = lambda payload: c2s.put(payload)  # type: ignore[assignment]
    client.recv = lambda: s2c.get()  # type: ignore[assignment]
    server.send = lambda payload: s2c.put(payload)  # type: ignore[assignment]
    server.recv = lambda: c2s.get()  # type: ignore[assignment]

    return client, server


def make_runners() -> tuple[
    ProtocolRunner[PingPongState], ProtocolRunner[PingPongState]
]:
    """Create a connected client/server ProtocolRunner pair."""
    proto = PingPongProtocol()
    codec = PingPongCodec()
    client_ch, server_ch = make_channel_pair()

    client = ProtocolRunner(
        role=PeerRole.Initiator,
        protocol=proto,
        codec=codec,
        channel=client_ch,  # type: ignore[arg-type]
    )
    server = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=proto,
        codec=codec,
        channel=server_ch,  # type: ignore[arg-type]
    )
    return client, server


# ---------------------------------------------------------------------------
# Tests: Codec roundtrip
# ---------------------------------------------------------------------------


class TestCodecRoundtrip:
    """Codec encode/decode roundtrip tests.

    Maps to test_specifications: test_msg_await_reply_codec_roundtrip
    """

    def test_ping_roundtrip(self) -> None:
        codec = PingPongCodec()
        msg = MsgPing()
        decoded = codec.decode(codec.encode(msg))
        assert isinstance(decoded, MsgPing)
        assert decoded.from_state == PingPongState.StIdle
        assert decoded.to_state == PingPongState.StBusy

    def test_pong_roundtrip(self) -> None:
        codec = PingPongCodec()
        msg = MsgPong()
        decoded = codec.decode(codec.encode(msg))
        assert isinstance(decoded, MsgPong)
        assert decoded.from_state == PingPongState.StBusy
        assert decoded.to_state == PingPongState.StIdle

    def test_done_roundtrip(self) -> None:
        codec = PingPongCodec()
        msg = MsgDone()
        decoded = codec.decode(codec.encode(msg))
        assert isinstance(decoded, MsgDone)
        assert decoded.from_state == PingPongState.StIdle
        assert decoded.to_state == PingPongState.StDone

    def test_decode_unknown_tag_raises_codec_error(self) -> None:
        codec = PingPongCodec()
        with pytest.raises(CodecError, match="Unknown tag"):
            codec.decode(b"\xff")

    def test_encode_unknown_message_raises_codec_error(self) -> None:
        codec = PingPongCodec()

        class UnknownMsg(Message[PingPongState]):
            def __init__(self) -> None:
                super().__init__(PingPongState.StIdle, PingPongState.StIdle)

        with pytest.raises(CodecError, match="Unknown message type"):
            codec.encode(UnknownMsg())


# ---------------------------------------------------------------------------
# Tests: ProtocolRunner — valid transitions
# ---------------------------------------------------------------------------


class TestProtocolRunnerValidTransitions:
    """Full Ping/Pong exchanges through the runner."""

    @pytest.mark.asyncio
    async def test_single_ping_pong(self) -> None:
        """Client sends Ping, server receives and responds with Pong."""
        client, server = make_runners()

        # Client sends Ping.
        await client.send_message(MsgPing())
        assert client.state is PingPongState.StBusy

        # Server receives Ping.
        msg = await server.recv_message()
        assert isinstance(msg, MsgPing)
        assert server.state is PingPongState.StBusy

        # Server sends Pong.
        await server.send_message(MsgPong())
        assert server.state is PingPongState.StIdle

        # Client receives Pong.
        msg = await client.recv_message()
        assert isinstance(msg, MsgPong)
        assert client.state is PingPongState.StIdle

    @pytest.mark.asyncio
    async def test_multiple_rounds_then_done(self) -> None:
        """Multiple Ping/Pong rounds followed by Done."""
        client, server = make_runners()

        for _ in range(5):
            await client.send_message(MsgPing())
            await server.recv_message()
            await server.send_message(MsgPong())
            await client.recv_message()

        # Terminate.
        await client.send_message(MsgDone())
        msg = await server.recv_message()
        assert isinstance(msg, MsgDone)

        assert client.state is PingPongState.StDone
        assert server.state is PingPongState.StDone
        assert client.is_done
        assert server.is_done

    @pytest.mark.asyncio
    async def test_immediate_done(self) -> None:
        """Client sends Done immediately without any Ping/Pong."""
        client, server = make_runners()

        await client.send_message(MsgDone())
        msg = await server.recv_message()
        assert isinstance(msg, MsgDone)
        assert client.is_done
        assert server.is_done


# ---------------------------------------------------------------------------
# Tests: ProtocolRunner — agency violations
# ---------------------------------------------------------------------------


class TestProtocolRunnerAgencyViolations:
    """Agency enforcement tests — wrong peer trying to send/recv."""

    @pytest.mark.asyncio
    async def test_server_cannot_send_when_client_has_agency(self) -> None:
        """Server sending at StIdle (Client has agency) raises ProtocolError."""
        _client, server = make_runners()

        with pytest.raises(ProtocolError, match="does not have agency"):
            await server.send_message(MsgPing())

    @pytest.mark.asyncio
    async def test_client_cannot_recv_when_client_has_agency(self) -> None:
        """Client receiving at StIdle (it has agency) raises ProtocolError."""
        client, _server = make_runners()

        with pytest.raises(ProtocolError, match="has agency"):
            await client.recv_message()

    @pytest.mark.asyncio
    async def test_client_cannot_send_when_server_has_agency(self) -> None:
        """Client sending at StBusy (Server has agency) raises ProtocolError."""
        client, server = make_runners()

        # Move to StBusy.
        await client.send_message(MsgPing())
        await server.recv_message()

        # Now server has agency — client cannot send.
        with pytest.raises(ProtocolError, match="does not have agency"):
            await client.send_message(MsgPong())

    @pytest.mark.asyncio
    async def test_server_cannot_recv_when_server_has_agency(self) -> None:
        """Server receiving at StBusy (it has agency) raises ProtocolError."""
        client, server = make_runners()

        await client.send_message(MsgPing())
        await server.recv_message()

        # Server has agency — should send, not receive.
        with pytest.raises(ProtocolError, match="has agency"):
            await server.recv_message()


# ---------------------------------------------------------------------------
# Tests: ProtocolRunner — terminal state
# ---------------------------------------------------------------------------


class TestProtocolRunnerTerminalState:
    """No operations allowed after reaching the terminal state."""

    @pytest.mark.asyncio
    async def test_send_in_terminal_state(self) -> None:
        """Sending after Done raises ProtocolError."""
        client, server = make_runners()

        await client.send_message(MsgDone())
        await server.recv_message()

        with pytest.raises(ProtocolError, match="terminal state"):
            await client.send_message(MsgPing())

    @pytest.mark.asyncio
    async def test_recv_in_terminal_state(self) -> None:
        """Receiving after Done raises ProtocolError."""
        client, server = make_runners()

        await client.send_message(MsgDone())
        await server.recv_message()

        with pytest.raises(ProtocolError, match="terminal state"):
            await server.recv_message()


# ---------------------------------------------------------------------------
# Tests: ProtocolRunner — invalid messages
# ---------------------------------------------------------------------------


class TestProtocolRunnerInvalidMessages:
    """Message validity checks — wrong message type for current state."""

    @pytest.mark.asyncio
    async def test_send_wrong_message_type(self) -> None:
        """Sending MsgPong in StIdle (where only Ping/Done valid) raises."""
        client, _server = make_runners()

        # MsgPong's from_state is StBusy, current is StIdle.
        with pytest.raises(ProtocolError, match="expects from_state"):
            await client.send_message(MsgPong())

    @pytest.mark.asyncio
    async def test_recv_wrong_message_from_peer(self) -> None:
        """Receiving a message with wrong from_state raises ProtocolError."""
        client, server = make_runners()

        # Manually put a MsgPong on the wire (wrong message for StIdle).
        # The server is expecting to receive at StIdle after client sends,
        # but we'll inject bytes for MsgPong.
        proto = PingPongProtocol()
        codec = PingPongCodec()

        # Create a runner with a channel that returns Pong bytes.
        ch = MockChannel()
        ch._queue.put_nowait(codec.encode(MsgPong()))

        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=proto,
            codec=codec,
            channel=ch,  # type: ignore[arg-type]
        )

        # StIdle, Responder doesn't have agency — recv is valid.
        # But the decoded message (MsgPong) has from_state=StBusy != StIdle.
        with pytest.raises(ProtocolError, match="current state is"):
            await runner.recv_message()


# ---------------------------------------------------------------------------
# Tests: ProtocolRunner — codec errors
# ---------------------------------------------------------------------------


class TestProtocolRunnerCodecErrors:
    """Codec failures propagate as CodecError."""

    @pytest.mark.asyncio
    async def test_decode_failure_raises_codec_error(self) -> None:
        """Garbage bytes on the channel raise CodecError on recv."""
        proto = PingPongProtocol()
        codec = PingPongCodec()

        ch = MockChannel()
        ch._queue.put_nowait(b"\xff\xfe")  # Garbage.

        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=proto,
            codec=codec,
            channel=ch,  # type: ignore[arg-type]
        )

        with pytest.raises(CodecError, match="Unknown tag"):
            await runner.recv_message()

    @pytest.mark.asyncio
    async def test_encode_failure_raises_codec_error(self) -> None:
        """A codec that fails to encode raises CodecError on send."""

        class FailCodec:
            def encode(self, message: Message) -> bytes:
                raise CodecError("encode boom")

            def decode(self, data: bytes) -> Message:
                return MsgPing()  # pragma: no cover

        proto = PingPongProtocol()
        ch = MockChannel()

        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=proto,
            codec=FailCodec(),  # type: ignore[arg-type]
            channel=ch,  # type: ignore[arg-type]
        )

        with pytest.raises(CodecError, match="encode boom"):
            await runner.send_message(MsgPing())

    @pytest.mark.asyncio
    async def test_encode_unexpected_exception_wrapped_as_codec_error(self) -> None:
        """Non-CodecError exceptions from encode are wrapped."""

        class BadCodec:
            def encode(self, message: Message) -> bytes:
                raise RuntimeError("unexpected")

            def decode(self, data: bytes) -> Message:
                return MsgPing()  # pragma: no cover

        proto = PingPongProtocol()
        ch = MockChannel()

        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=proto,
            codec=BadCodec(),  # type: ignore[arg-type]
            channel=ch,  # type: ignore[arg-type]
        )

        with pytest.raises(CodecError, match="Failed to encode"):
            await runner.send_message(MsgPing())


# ---------------------------------------------------------------------------
# Tests: ProtocolRunner — channel closed
# ---------------------------------------------------------------------------


class TestProtocolRunnerChannelClosed:
    """MuxClosedError propagates when channel is closed."""

    @pytest.mark.asyncio
    async def test_send_on_closed_channel(self) -> None:
        """Sending on a closed channel raises MuxClosedError."""
        proto = PingPongProtocol()
        codec = PingPongCodec()
        ch = MockChannel()
        ch.close()

        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=proto,
            codec=codec,
            channel=ch,  # type: ignore[arg-type]
        )

        with pytest.raises(MuxClosedError):
            await runner.send_message(MsgPing())

    @pytest.mark.asyncio
    async def test_recv_on_closed_channel(self) -> None:
        """Receiving on a closed channel raises MuxClosedError."""
        proto = PingPongProtocol()
        codec = PingPongCodec()
        ch = MockChannel()
        ch.close()

        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=proto,
            codec=codec,
            channel=ch,  # type: ignore[arg-type]
        )

        with pytest.raises(MuxClosedError):
            await runner.recv_message()


# ---------------------------------------------------------------------------
# Tests: ProtocolRunner — state does not advance on failure
# ---------------------------------------------------------------------------


class TestProtocolRunnerStateRollback:
    """State should not advance if send/recv fails."""

    @pytest.mark.asyncio
    async def test_state_unchanged_after_agency_violation(self) -> None:
        """State remains unchanged when send is rejected for agency."""
        _client, server = make_runners()

        original_state = server.state
        with pytest.raises(ProtocolError):
            await server.send_message(MsgPing())

        assert server.state is original_state

    @pytest.mark.asyncio
    async def test_state_unchanged_after_codec_error(self) -> None:
        """State remains unchanged when codec.encode fails."""

        class FailCodec:
            def encode(self, message: Message) -> bytes:
                raise CodecError("nope")

            def decode(self, data: bytes) -> Message:
                return MsgPing()  # pragma: no cover

        proto = PingPongProtocol()
        ch = MockChannel()
        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=proto,
            codec=FailCodec(),  # type: ignore[arg-type]
            channel=ch,  # type: ignore[arg-type]
        )

        original_state = runner.state
        with pytest.raises(CodecError):
            await runner.send_message(MsgPing())

        assert runner.state is original_state

    @pytest.mark.asyncio
    async def test_state_unchanged_after_recv_decode_error(self) -> None:
        """State remains unchanged when codec.decode fails."""
        proto = PingPongProtocol()
        codec = PingPongCodec()
        ch = MockChannel()
        ch._queue.put_nowait(b"\xff")  # Garbage.

        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=proto,
            codec=codec,
            channel=ch,  # type: ignore[arg-type]
        )

        original_state = runner.state
        with pytest.raises(CodecError):
            await runner.recv_message()

        assert runner.state is original_state


# ---------------------------------------------------------------------------
# Tests: Codec structural typing
# ---------------------------------------------------------------------------


class TestCodecStructuralTyping:
    """Verify the Codec Protocol works with structural typing."""

    def test_ping_pong_codec_is_codec(self) -> None:
        """PingPongCodec satisfies the Codec protocol."""
        assert isinstance(PingPongCodec(), Codec)

    def test_arbitrary_class_with_encode_decode_is_codec(self) -> None:
        """Any class with encode/decode methods satisfies Codec."""

        class MyCodec:
            def encode(self, message: Message) -> bytes:
                return b""

            def decode(self, data: bytes) -> Message:
                return MsgPing()

        assert isinstance(MyCodec(), Codec)


# ---------------------------------------------------------------------------
# Tests: ProtocolRunner properties
# ---------------------------------------------------------------------------


class TestProtocolRunnerProperties:
    """Runner property accessors."""

    def test_initial_state(self) -> None:
        client, server = make_runners()
        assert client.state is PingPongState.StIdle
        assert server.state is PingPongState.StIdle

    def test_role(self) -> None:
        client, server = make_runners()
        assert client.role is PeerRole.Initiator
        assert server.role is PeerRole.Responder

    def test_is_done_initially_false(self) -> None:
        client, _server = make_runners()
        assert not client.is_done

    @pytest.mark.asyncio
    async def test_is_done_after_terminal(self) -> None:
        client, server = make_runners()
        await client.send_message(MsgDone())
        await server.recv_message()
        assert client.is_done
        assert server.is_done
