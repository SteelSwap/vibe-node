"""Tests for the typed protocol state machine framework.

Defines a simple Ping/Pong protocol with three states to exercise
agency validation, state transitions, and terminal state handling.

Protocol:
    StIdle  (Client agency) --MsgPing--> StBusy
    StBusy  (Server agency) --MsgPong--> StIdle
    StIdle  (Client agency) --MsgDone--> StDone (Nobody)
"""

from __future__ import annotations

import asyncio
import enum

import pytest

from vibe.core.protocols import (
    Agency,
    Message,
    Peer,
    PeerRole,
    Protocol,
    ProtocolError,
)

# ---------------------------------------------------------------------------
# Test protocol definition: Ping/Pong
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

    def valid_messages(self, state: PingPongState) -> frozenset[type[Message[PingPongState]]]:
        match state:
            case PingPongState.StIdle:
                return frozenset({MsgPing, MsgDone})
            case PingPongState.StBusy:
                return frozenset({MsgPong})
            case PingPongState.StDone:
                return frozenset()
        raise ValueError(f"Unknown state: {state}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_peers() -> tuple[Peer[PingPongState], Peer[PingPongState]]:
    """Create a connected Initiator/Responder peer pair."""
    proto = PingPongProtocol()
    # Initiator sends on q_c2s, receives on q_s2c.
    # Responder sends on q_s2c, receives on q_c2s.
    q_c2s: asyncio.Queue[Message[PingPongState]] = asyncio.Queue()
    q_s2c: asyncio.Queue[Message[PingPongState]] = asyncio.Queue()
    client = Peer(PeerRole.Initiator, proto, send_queue=q_c2s, recv_queue=q_s2c)
    server = Peer(PeerRole.Responder, proto, send_queue=q_s2c, recv_queue=q_c2s)
    return client, server


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_transitions() -> None:
    """A full Ping/Pong exchange should work without errors."""
    client, server = make_peers()

    # Client sends Ping (StIdle -> StBusy).
    await client.send(MsgPing())
    assert client.state is PingPongState.StBusy

    # Server receives Ping.
    msg = await server.receive()
    assert isinstance(msg, MsgPing)
    assert server.state is PingPongState.StBusy

    # Server sends Pong (StBusy -> StIdle).
    await server.send(MsgPong())
    assert server.state is PingPongState.StIdle

    # Client receives Pong.
    msg = await client.receive()
    assert isinstance(msg, MsgPong)
    assert client.state is PingPongState.StIdle


@pytest.mark.asyncio
async def test_invalid_agency() -> None:
    """Server trying to send when Client has agency raises ProtocolError."""
    _client, server = make_peers()

    # Both start at StIdle where Client (Initiator) has agency.
    # Server (Responder) trying to send should fail.
    with pytest.raises(ProtocolError, match="does not have agency"):
        await server.send(MsgPing())


@pytest.mark.asyncio
async def test_terminal_state() -> None:
    """No messages allowed after reaching StDone."""
    client, server = make_peers()

    # Client sends Done (StIdle -> StDone).
    await client.send(MsgDone())
    assert client.state is PingPongState.StDone

    # Server receives Done.
    msg = await server.receive()
    assert isinstance(msg, MsgDone)
    assert server.state is PingPongState.StDone

    # Neither side can send or receive in terminal state.
    with pytest.raises(ProtocolError, match="terminal state"):
        await client.send(MsgPing())

    with pytest.raises(ProtocolError, match="terminal state"):
        await server.send(MsgPong())

    with pytest.raises(ProtocolError, match="terminal state"):
        await client.receive()


@pytest.mark.asyncio
async def test_wrong_message_for_state() -> None:
    """Sending MsgPong in StIdle (where only MsgPing/MsgDone are valid)."""
    client, _server = make_peers()

    # MsgPong's from_state is StBusy, but we're in StIdle.
    # This should fail the state consistency check.
    with pytest.raises(ProtocolError, match="expects from_state"):
        await client.send(MsgPong())


@pytest.mark.asyncio
async def test_multiple_ping_pong_rounds() -> None:
    """Multiple Ping/Pong rounds followed by Done."""
    client, server = make_peers()

    for _ in range(3):
        await client.send(MsgPing())
        await server.receive()
        await server.send(MsgPong())
        await client.receive()

    # Finish the protocol.
    await client.send(MsgDone())
    await server.receive()
    assert client.state is PingPongState.StDone
    assert server.state is PingPongState.StDone


@pytest.mark.asyncio
async def test_initiator_cannot_receive_with_agency() -> None:
    """Initiator trying to receive when it has agency raises ProtocolError."""
    client, _server = make_peers()

    # At StIdle, Client (Initiator) has agency — should send, not receive.
    with pytest.raises(ProtocolError, match="has agency"):
        await client.receive()


@pytest.mark.asyncio
async def test_peer_repr_and_properties() -> None:
    """Peer properties and Message repr work correctly."""
    client, _server = make_peers()

    assert client.role is PeerRole.Initiator
    assert client.state is PingPongState.StIdle

    msg = MsgPing()
    assert "MsgPing" in repr(msg)
    assert "idle" in repr(msg)
    assert "busy" in repr(msg)
