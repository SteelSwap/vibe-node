"""Local Tx-Submission miniprotocol -- typed protocol FSM, codec, and server.

Implements the N2C local tx-submission miniprotocol as a typed state machine
following the Ouroboros typed-protocols pattern. This is a simple
request-response protocol: the CLIENT submits transactions, the SERVER
validates them and returns accept/reject.

States:

    StIdle   -- Client has agency (sends MsgSubmitTx or MsgDone)
    StBusy   -- Server has agency (sends MsgAcceptTx or MsgRejectTx)
    StDone   -- Nobody has agency (terminal)

Unlike the N2N tx-submission protocol (which is pull-based and server-driven),
local tx-submission is push-based and client-driven. The client submits
transactions and the server responds synchronously.

Haskell reference:
    Ouroboros/Network/Protocol/LocalTxSubmission/Type.hs
    Ouroboros/Network/Protocol/LocalTxSubmission/Server.hs
    Ouroboros/Network/Protocol/LocalTxSubmission/Codec.hs

Spec reference:
    Ouroboros network spec, "Local Tx-Submission Mini-Protocol"
"""

from __future__ import annotations

import enum
import logging
from typing import Awaitable, Callable, Protocol as TypingProtocol

from vibe.core.protocols.agency import (
    Agency,
    Message,
    Protocol,
    ProtocolError,
    PeerRole,
)
from vibe.core.protocols.codec import Codec, CodecError
from vibe.core.protocols.runner import ProtocolRunner

from vibe.cardano.network.local_txsubmission import (
    MsgSubmitTx,
    MsgAcceptTx,
    MsgRejectTx,
    MsgDone,
    encode_submit_tx,
    encode_accept_tx,
    encode_reject_tx,
    encode_done,
    decode_message,
)

__all__ = [
    "LocalTxSubmissionState",
    "LocalTxSubmissionProtocol",
    "LocalTxSubmissionCodec",
    "LocalTxSubmissionServer",
    "run_local_tx_submission_server",
    # Typed message wrappers
    "LtsMsgSubmitTx",
    "LtsMsgAcceptTx",
    "LtsMsgRejectTx",
    "LtsMsgDone",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol states
# ---------------------------------------------------------------------------


class LocalTxSubmissionState(enum.Enum):
    """States of the local tx-submission miniprotocol state machine.

    Haskell reference: LocalTxSubmission type, with constructors
        StIdle, StBusy, StDone.
    """

    StIdle = "st_idle"
    """Client has agency -- sends MsgSubmitTx or MsgDone."""

    StBusy = "st_busy"
    """Server has agency -- sends MsgAcceptTx or MsgRejectTx."""

    StDone = "st_done"
    """Terminal state. Nobody has agency. Protocol complete."""


# ---------------------------------------------------------------------------
# Typed messages (Message wrappers with state transitions)
# ---------------------------------------------------------------------------


class LtsMsgSubmitTx(Message[LocalTxSubmissionState]):
    """Client -> Server: submit a transaction.

    Transition: StIdle -> StBusy
    """

    __slots__ = ("inner",)

    def __init__(self, era_id: int, tx_bytes: bytes) -> None:
        super().__init__(
            from_state=LocalTxSubmissionState.StIdle,
            to_state=LocalTxSubmissionState.StBusy,
        )
        self.inner = MsgSubmitTx(era_id=era_id, tx_bytes=tx_bytes)

    @property
    def era_id(self) -> int:
        return self.inner.era_id

    @property
    def tx_bytes(self) -> bytes:
        return self.inner.tx_bytes


class LtsMsgAcceptTx(Message[LocalTxSubmissionState]):
    """Server -> Client: transaction accepted.

    Transition: StBusy -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalTxSubmissionState.StBusy,
            to_state=LocalTxSubmissionState.StIdle,
        )
        self.inner = MsgAcceptTx()


class LtsMsgRejectTx(Message[LocalTxSubmissionState]):
    """Server -> Client: transaction rejected.

    Transition: StBusy -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, reason: bytes) -> None:
        super().__init__(
            from_state=LocalTxSubmissionState.StBusy,
            to_state=LocalTxSubmissionState.StIdle,
        )
        self.inner = MsgRejectTx(reason=reason)

    @property
    def reason(self) -> bytes:
        return self.inner.reason


class LtsMsgDone(Message[LocalTxSubmissionState]):
    """Client -> Server: terminate the protocol.

    Transition: StIdle -> StDone
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalTxSubmissionState.StIdle,
            to_state=LocalTxSubmissionState.StDone,
        )
        self.inner = MsgDone()


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------

# Pre-computed frozen sets for valid_messages.
_IDLE_MESSAGES: frozenset[type[Message[LocalTxSubmissionState]]] = frozenset(
    {LtsMsgSubmitTx, LtsMsgDone}
)
_BUSY_MESSAGES: frozenset[type[Message[LocalTxSubmissionState]]] = frozenset(
    {LtsMsgAcceptTx, LtsMsgRejectTx}
)
_DONE_MESSAGES: frozenset[type[Message[LocalTxSubmissionState]]] = frozenset()


class LocalTxSubmissionProtocol(Protocol[LocalTxSubmissionState]):
    """Local tx-submission miniprotocol state machine definition.

    Agency map:
        StIdle -> Client (sends MsgSubmitTx or MsgDone)
        StBusy -> Server (sends MsgAcceptTx or MsgRejectTx)
        StDone -> Nobody (terminal)

    Haskell reference:
        instance Protocol LocalTxSubmission where
            type ClientHasAgency st = st ~ 'StIdle
            type ServerHasAgency st = st ~ 'StBusy
            type NobodyHasAgency st = st ~ 'StDone
    """

    _AGENCY_MAP = {
        LocalTxSubmissionState.StIdle: Agency.Client,
        LocalTxSubmissionState.StBusy: Agency.Server,
        LocalTxSubmissionState.StDone: Agency.Nobody,
    }

    _VALID_MESSAGES = {
        LocalTxSubmissionState.StIdle: _IDLE_MESSAGES,
        LocalTxSubmissionState.StBusy: _BUSY_MESSAGES,
        LocalTxSubmissionState.StDone: _DONE_MESSAGES,
    }

    def initial_state(self) -> LocalTxSubmissionState:
        return LocalTxSubmissionState.StIdle

    def agency(self, state: LocalTxSubmissionState) -> Agency:
        try:
            return self._AGENCY_MAP[state]
        except KeyError:
            raise ProtocolError(
                f"Unknown local tx-submission state: {state!r}"
            )

    def valid_messages(
        self, state: LocalTxSubmissionState
    ) -> frozenset[type[Message[LocalTxSubmissionState]]]:
        try:
            return self._VALID_MESSAGES[state]
        except KeyError:
            raise ProtocolError(
                f"Unknown local tx-submission state: {state!r}"
            )


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class LocalTxSubmissionCodec:
    """CBOR codec for local tx-submission miniprotocol messages.

    Wraps the encode/decode functions from local_txsubmission.py,
    translating between typed Message wrappers (LtsMsg*) and raw CBOR bytes.

    Implements the Codec protocol (structural typing).
    """

    def encode(self, message: Message[LocalTxSubmissionState]) -> bytes:
        """Encode a typed local tx-submission message to CBOR bytes."""
        if isinstance(message, LtsMsgSubmitTx):
            return encode_submit_tx(message.era_id, message.tx_bytes)
        elif isinstance(message, LtsMsgAcceptTx):
            return encode_accept_tx()
        elif isinstance(message, LtsMsgRejectTx):
            return encode_reject_tx(message.reason)
        elif isinstance(message, LtsMsgDone):
            return encode_done()
        else:
            raise CodecError(
                f"Unknown local tx-submission message type: "
                f"{type(message).__name__}"
            )

    def decode(self, data: bytes) -> Message[LocalTxSubmissionState]:
        """Decode CBOR bytes into a typed local tx-submission message."""
        try:
            msg = decode_message(data)
        except ValueError as exc:
            raise CodecError(str(exc)) from exc

        if isinstance(msg, MsgSubmitTx):
            return LtsMsgSubmitTx(era_id=msg.era_id, tx_bytes=msg.tx_bytes)
        elif isinstance(msg, MsgAcceptTx):
            return LtsMsgAcceptTx()
        elif isinstance(msg, MsgRejectTx):
            return LtsMsgRejectTx(reason=msg.reason)
        elif isinstance(msg, MsgDone):
            return LtsMsgDone()
        else:
            raise CodecError(
                f"Failed to decode local tx-submission message "
                f"({len(data)} bytes)"
            )


# ---------------------------------------------------------------------------
# Mempool interface (structural typing)
# ---------------------------------------------------------------------------

#: Type alias for the tx validation callback.
#: Called with (era_id, tx_bytes). Returns None on accept, or
#: rejection-reason bytes on reject.
ValidateTx = Callable[[int, bytes], Awaitable[bytes | None]]


# ---------------------------------------------------------------------------
# High-level server (Responder side)
# ---------------------------------------------------------------------------


class LocalTxSubmissionServer:
    """High-level local tx-submission server (Responder).

    The server receives transactions from a local client, validates them
    via a user-provided callback, and returns accept/reject.

    Parameters
    ----------
    runner : ProtocolRunner[LocalTxSubmissionState]
        A protocol runner set up as Responder with the local tx-submission
        protocol, codec, and a connected mux channel.
    """

    __slots__ = ("_runner",)

    def __init__(
        self, runner: ProtocolRunner[LocalTxSubmissionState]
    ) -> None:
        self._runner = runner

    @property
    def state(self) -> LocalTxSubmissionState:
        """Current protocol state."""
        return self._runner.state

    @property
    def is_done(self) -> bool:
        """Whether the protocol has terminated."""
        return self._runner.is_done

    async def recv_client_message(
        self,
    ) -> LtsMsgSubmitTx | LtsMsgDone:
        """Wait for the client to send a message.

        The client has agency in StIdle and will send either
        MsgSubmitTx or MsgDone.

        Returns
        -------
        LtsMsgSubmitTx | LtsMsgDone
            The client's message.
        """
        response = await self._runner.recv_message()
        if isinstance(response, (LtsMsgSubmitTx, LtsMsgDone)):
            return response
        raise ProtocolError(
            f"Unexpected client message in StIdle: "
            f"{type(response).__name__}"
        )

    async def accept_tx(self) -> None:
        """Send MsgAcceptTx to accept the submitted transaction."""
        await self._runner.send_message(LtsMsgAcceptTx())

    async def reject_tx(self, reason: bytes) -> None:
        """Send MsgRejectTx to reject the submitted transaction.

        Parameters
        ----------
        reason : bytes
            CBOR-encoded rejection reason.
        """
        await self._runner.send_message(LtsMsgRejectTx(reason=reason))


# ---------------------------------------------------------------------------
# High-level server loop
# ---------------------------------------------------------------------------


async def run_local_tx_submission_server(
    channel: object,
    validate_tx: ValidateTx,
) -> None:
    """Run the local tx-submission server protocol loop.

    This is the main entry point for serving local tx-submission. It:
    1. Creates a ProtocolRunner with the protocol and codec.
    2. Loops: receives MsgSubmitTx from the client, validates via callback,
       sends MsgAcceptTx or MsgRejectTx.
    3. Exits when the client sends MsgDone.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for local tx-submission.
    validate_tx : ValidateTx
        Async callback invoked to validate each transaction.
        Called with (era_id, tx_bytes).
        Return None to accept, or CBOR-encoded reason bytes to reject.
    """
    protocol = LocalTxSubmissionProtocol()
    codec = LocalTxSubmissionCodec()
    runner = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    server = LocalTxSubmissionServer(runner)

    while not server.is_done:
        client_msg = await server.recv_client_message()

        if isinstance(client_msg, LtsMsgDone):
            logger.debug("Local tx-submission: client sent MsgDone, terminating")
            return

        if isinstance(client_msg, LtsMsgSubmitTx):
            logger.debug(
                "Local tx-submission: received tx (era=%d, %d bytes)",
                client_msg.era_id,
                len(client_msg.tx_bytes),
            )
            rejection = await validate_tx(
                client_msg.era_id, client_msg.tx_bytes
            )
            if rejection is None:
                await server.accept_tx()
                logger.debug("Local tx-submission: accepted tx")
            else:
                await server.reject_tx(rejection)
                logger.debug("Local tx-submission: rejected tx")
