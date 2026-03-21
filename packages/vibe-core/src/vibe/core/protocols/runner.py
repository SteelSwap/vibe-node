"""ProtocolRunner — drives a typed protocol state machine over a mux channel.

The ProtocolRunner is the bridge between the typed-protocols framework
(agency, state machines, messages) and the multiplexer layer (bytes over
channels). It takes a MiniProtocolChannel and a Protocol definition, plus
a Codec for the specific miniprotocol, and provides async send/recv that:

1. Validate agency before every operation.
2. Encode/decode messages via the codec.
3. Transport bytes through the mux channel.
4. Advance the protocol state machine.

This is the core abstraction that each miniprotocol client/server uses
to drive its protocol. A chain-sync client, for example, creates a
ProtocolRunner with the chain-sync protocol definition and codec, then
calls send_message / recv_message to execute the protocol.

Haskell reference:
    Network.TypedProtocol.Driver (runPeerWithDriver)
    Network.TypedProtocol.Driver.Simple (runPeer)
    The Haskell driver runs a Peer (free monad) over a channel+codec.
    Our version is imperative: the caller explicitly calls send/recv
    rather than constructing a Peer computation.

Spec reference:
    Ouroboros network spec, Chapter 2 "Mini-Protocol Framework" —
    each mini-protocol is a typed state machine where the driver
    enforces agency and serializes messages through a codec.
"""

from __future__ import annotations

import io
import logging
from typing import Generic

from vibe.core.multiplexer.mux import MiniProtocolChannel, MuxClosedError
from vibe.core.protocols.agency import (
    Agency,
    Message,
    PeerRole,
    Protocol,
    ProtocolError,
    St,
)
from vibe.core.protocols.codec import Codec, CodecError

__all__ = ["ProtocolRunner"]

logger = logging.getLogger(__name__)


class ProtocolRunner(Generic[St]):
    """Drives a typed protocol state machine over a multiplexer channel.

    The runner maintains the current protocol state and enforces agency
    rules on every send/recv. Messages are serialized/deserialized through
    the provided codec, and bytes are transported via the mux channel.

    Parameters
    ----------
    role : PeerRole
        Whether this side is the Initiator or Responder.
    protocol : Protocol[St]
        The protocol definition (states, agency map, valid messages).
    codec : Codec
        Encodes/decodes messages for this specific miniprotocol.
    channel : MiniProtocolChannel
        The mux channel for this miniprotocol.

    Haskell reference:
        Network.TypedProtocol.Driver.runPeerWithDriver — the main loop
        that matches Yield/Await/Effect/Done constructors and drives
        the protocol over a channel. Our version exposes send/recv
        directly instead of interpreting a free monad.
    """

    __slots__ = ("_role", "_protocol", "_codec", "_channel", "_state", "_recv_buf")

    def __init__(
        self,
        role: PeerRole,
        protocol: Protocol[St],
        codec: Codec,
        channel: MiniProtocolChannel,
    ) -> None:
        self._role = role
        self._protocol = protocol
        self._codec = codec
        self._channel = channel
        self._state: St = protocol.initial_state()
        self._recv_buf: bytes = b""  # Buffer for multi-message segments

    @property
    def state(self) -> St:
        """The current protocol state."""
        return self._state

    @property
    def role(self) -> PeerRole:
        """This runner's peer role."""
        return self._role

    @property
    def is_done(self) -> bool:
        """True if the protocol has reached a terminal state (Nobody has agency)."""
        return self._protocol.agency(self._state) is Agency.Nobody

    def _has_agency(self) -> bool:
        """Return True if this peer currently has agency."""
        ag = self._protocol.agency(self._state)
        if ag is Agency.Nobody:
            return False
        if ag is Agency.Client:
            return self._role is PeerRole.Initiator
        # ag is Agency.Server
        return self._role is PeerRole.Responder

    async def send_message(self, message: Message[St]) -> None:
        """Send a protocol message over the mux channel.

        Validates agency and message validity, encodes the message to bytes
        via the codec, sends through the channel, and advances state.

        Args:
            message: The typed message to send.

        Raises:
            ProtocolError: If this peer does not have agency, if the
                message's from_state doesn't match the current state,
                or if the message type is not valid at the current state.
            CodecError: If encoding the message fails.
            MuxClosedError: If the mux channel is closed.
        """
        ag = self._protocol.agency(self._state)

        # Terminal state check.
        if ag is Agency.Nobody:
            raise ProtocolError(
                f"Cannot send in terminal state {self._state!r}"
            )

        # Agency check — we must have agency to send.
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

        # Encode and send.
        try:
            data = self._codec.encode(message)
        except CodecError:
            raise
        except Exception as exc:
            raise CodecError(
                f"Failed to encode {type(message).__name__}: {exc}"
            ) from exc

        logger.debug(
            "send %s (%d bytes) [%s -> %s]",
            type(message).__name__,
            len(data),
            message.from_state,
            message.to_state,
        )

        await self._channel.send(data)

        # Advance state only after successful send.
        self._state = message.to_state

    async def recv_message(self) -> Message[St]:
        """Receive a protocol message from the mux channel.

        Validates that the peer has agency (we should be waiting), reads
        bytes from the channel, decodes via the codec, validates the
        decoded message, and advances state.

        Returns:
            The decoded and validated Message.

        Raises:
            ProtocolError: If this peer has agency (should send, not recv),
                if the decoded message's from_state doesn't match the
                current state, or if the message type is invalid.
            CodecError: If decoding the bytes fails.
            MuxClosedError: If the mux channel is closed.
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

        # Read bytes from the channel, prepending any buffered data.
        if self._recv_buf:
            data = self._recv_buf
            self._recv_buf = b""
        else:
            data = await self._channel.recv()

        # Decode the first CBOR message from the data. If the segment
        # contains multiple CBOR items (common in block-fetch where
        # StartBatch + Block arrive in one TCP segment), we decode the
        # first and buffer the rest for the next recv_message call.
        import cbor2 as _cbor2

        try:
            # Find the boundary of the first CBOR item.
            # cbor2's CBORDecoder.fp.tell() is unreliable (consumes entire
            # buffer), so we find the boundary by trial: decode with
            # increasing slice sizes until cbor2.loads succeeds.
            consumed = 0
            for n in range(1, len(data) + 1):
                try:
                    _cbor2.loads(data[:n])
                    consumed = n
                    break
                except Exception:
                    continue
            if consumed == 0:
                consumed = len(data)

            remainder = data[consumed:]
            if remainder:
                self._recv_buf = remainder
            single_cbor = data[:consumed]
            message = self._codec.decode(single_cbor)
        except CodecError:
            raise
        except Exception as exc:
            raise CodecError(
                f"Failed to decode message at state {self._state!r}: {exc}"
            ) from exc

        # Validate the decoded message against current state.
        if message.from_state != self._state:
            raise ProtocolError(
                f"Decoded {message!r} but current state is "
                f"{self._state!r}"
            )

        valid = self._protocol.valid_messages(self._state)
        if type(message) not in valid:
            raise ProtocolError(
                f"Decoded invalid message type "
                f"{type(message).__name__} at state {self._state!r}"
            )

        logger.debug(
            "recv %s (%d bytes) [%s -> %s]",
            type(message).__name__,
            len(data),
            message.from_state,
            message.to_state,
        )

        # Advance state only after successful validation.
        self._state = message.to_state
        return message
