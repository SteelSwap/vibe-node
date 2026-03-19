"""Peer — runs one side of a typed protocol state machine.

A Peer wraps a Protocol definition and a PeerRole, enforcing that only
the peer with agency can send messages. It tracks the current protocol
state and validates every send/receive against the protocol rules.

Spec reference: In the Haskell typed-protocols library, the ``Peer``
type is a free monad that sequences protocol actions (``Effect``,
``Yield``, ``Await``, ``Done``). Our version is simpler — an imperative
object that validates transitions at runtime rather than encoding them
in the type system.
"""

from __future__ import annotations

import asyncio
from typing import Generic

from .agency import Agency, Message, PeerRole, Protocol, ProtocolError, St

__all__ = ["Peer"]


class Peer(Generic[St]):
    """Runs one side of a miniprotocol, enforcing agency rules.

    The Peer maintains the current protocol state and uses an asyncio
    Queue pair for communication. In production, these queues will be
    replaced by actual network I/O (multiplexed TCP or Unix sockets),
    but the agency validation logic remains the same.

    Parameters
    ----------
    role : PeerRole
        Whether this peer is the Initiator or Responder.
    protocol : Protocol[St]
        The protocol definition (states, agency map, valid messages).
    send_queue : asyncio.Queue[Message[St]]
        Queue to place outgoing messages on.
    recv_queue : asyncio.Queue[Message[St]]
        Queue to read incoming messages from.
    """

    __slots__ = ("_role", "_protocol", "_state", "_send_q", "_recv_q")

    def __init__(
        self,
        role: PeerRole,
        protocol: Protocol[St],
        send_queue: asyncio.Queue[Message[St]],
        recv_queue: asyncio.Queue[Message[St]],
    ) -> None:
        self._role = role
        self._protocol = protocol
        self._state: St = protocol.initial_state()
        self._send_q = send_queue
        self._recv_q = recv_queue

    @property
    def state(self) -> St:
        """The current protocol state."""
        return self._state

    @property
    def role(self) -> PeerRole:
        """This peer's role."""
        return self._role

    def _has_agency(self) -> bool:
        """Return True if this peer currently has agency."""
        ag = self._protocol.agency(self._state)
        if ag is Agency.Nobody:
            return False
        if ag is Agency.Client:
            return self._role is PeerRole.Initiator
        # ag is Agency.Server
        return self._role is PeerRole.Responder

    async def send(self, message: Message[St]) -> None:
        """Send a message, advancing the protocol state.

        Raises
        ------
        ProtocolError
            If this peer does not have agency, if the message's
            from_state does not match the current state, or if the
            message type is not valid at the current state.
        """
        ag = self._protocol.agency(self._state)

        # Terminal state check.
        if ag is Agency.Nobody:
            raise ProtocolError(
                f"Cannot send in terminal state {self._state!r}"
            )

        # Agency check.
        if not self._has_agency():
            raise ProtocolError(
                f"Peer {self._role.value} does not have agency at "
                f"state {self._state!r} (agency is {ag.value})"
            )

        # State consistency check.
        if message.from_state != self._state:
            raise ProtocolError(
                f"Message {message!r} expects from_state "
                f"{message.from_state!r} but current state is "
                f"{self._state!r}"
            )

        # Valid message type check.
        valid = self._protocol.valid_messages(self._state)
        if type(message) not in valid:
            raise ProtocolError(
                f"Message type {type(message).__name__} is not valid "
                f"at state {self._state!r}; valid types: "
                f"{[m.__name__ for m in valid]}"
            )

        # All checks passed — send and advance state.
        await self._send_q.put(message)
        self._state = message.to_state

    async def receive(self) -> Message[St]:
        """Receive a message, advancing the protocol state.

        Blocks until a message is available on the receive queue.

        Raises
        ------
        ProtocolError
            If this peer currently has agency (meaning it should be
            sending, not receiving), or if the received message is
            invalid for the current state.
        """
        ag = self._protocol.agency(self._state)

        # Terminal state check.
        if ag is Agency.Nobody:
            raise ProtocolError(
                f"Cannot receive in terminal state {self._state!r}"
            )

        # Agency check — we should NOT have agency when receiving.
        if self._has_agency():
            raise ProtocolError(
                f"Peer {self._role.value} has agency at state "
                f"{self._state!r} — should send, not receive"
            )

        message = await self._recv_q.get()

        # Validate the received message.
        if message.from_state != self._state:
            raise ProtocolError(
                f"Received {message!r} but current state is "
                f"{self._state!r}"
            )

        valid = self._protocol.valid_messages(self._state)
        if type(message) not in valid:
            raise ProtocolError(
                f"Received invalid message type "
                f"{type(message).__name__} at state {self._state!r}"
            )

        self._state = message.to_state
        return message
