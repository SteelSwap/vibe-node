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

from vibe.core.multiplexer.mux import MiniProtocolChannel
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
            raise ProtocolError(f"Cannot send in terminal state {self._state!r}")

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
            raise CodecError(f"Failed to encode {type(message).__name__}: {exc}") from exc

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
            raise ProtocolError(f"Cannot receive in terminal state {self._state!r}")

        # Agency check — we should NOT have agency when receiving.
        if self._has_agency():
            raise ProtocolError(
                f"Peer {self._role.value} has agency at state "
                f"{self._state!r} — should send, not receive"
            )

        # Read bytes from the channel, prepending any buffered data.
        # Large messages (e.g., blocks with transactions) may span multiple
        # SDU segments (max 12,288 bytes each). We accumulate segments
        # using a bytearray buffer (O(1) append) instead of bytes
        # concatenation (O(n) copy per segment).
        #
        # Haskell ref: Network.Mux.Ingress accumulates bytes per-channel
        # as a lazy Builder (O(1) append), codec reads from the stream.
        if self._recv_buf:
            buf = bytearray(self._recv_buf)
            self._recv_buf = b""
        else:
            buf = bytearray(await self._channel.recv())

        import cbor2pure as _cbor2

        # Try to decode. If the CBOR is incomplete (message spans multiple
        # SDU segments), read more segments into the buffer and retry.
        max_reassembly_attempts = 50  # ~600KB at 12KB/segment
        for _attempt in range(max_reassembly_attempts):
            try:
                data = bytes(buf)  # CBORDecoder needs immutable bytes
                decoder = _cbor2.CBORDecoder(io.BytesIO(data))
                decoder.decode()  # consume first CBOR item
                consumed = decoder.fp.tell()
                remainder = data[consumed:]
                if remainder:
                    self._recv_buf = remainder
                single_cbor = data[:consumed]
                message = self._codec.decode(single_cbor)
                break
            except CodecError:
                raise
            except Exception as exc:
                # Check if this looks like incomplete data (premature end)
                err_str = str(exc).lower()
                if "end of" in err_str or "truncated" in err_str or "premature" in err_str or "incomplete" in err_str:
                    # Read another segment and append to buffer (O(1))
                    try:
                        more = await self._channel.recv()
                        buf.extend(more)
                    except Exception:
                        raise CodecError(
                            f"Failed to decode message at state {self._state!r}: "
                            f"{exc} (after {len(buf)} bytes across {_attempt + 1} segments)"
                        ) from exc
                else:
                    raise CodecError(
                        f"Failed to decode message at state {self._state!r}: {exc}"
                    ) from exc
        else:
            raise CodecError(
                f"Failed to reassemble message at state {self._state!r} "
                f"after {max_reassembly_attempts} segments ({len(data)} bytes)"
            )

        # Validate the decoded message against current state.
        if message.from_state != self._state:
            raise ProtocolError(f"Decoded {message!r} but current state is {self._state!r}")

        valid = self._protocol.valid_messages(self._state)
        if type(message) not in valid:
            raise ProtocolError(
                f"Decoded invalid message type {type(message).__name__} at state {self._state!r}"
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
