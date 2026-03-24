"""Tx-Submission miniprotocol (v2) -- typed protocol FSM, codec, and client.

Implements the N2N tx-submission miniprotocol as a typed state machine
following the Ouroboros typed-protocols pattern. This is a pull-based
protocol where the SERVER drives the interaction by requesting tx IDs
and transactions from the CLIENT.

States:

    StInit   -- Client has agency (sends MsgInit)
    StIdle   -- Server has agency (sends MsgRequestTxIds or MsgRequestTxs)
    StTxIds  -- Client has agency (sends MsgReplyTxIds or MsgDone)
    StTxs    -- Client has agency (sends MsgReplyTxs)
    StDone   -- Nobody has agency (terminal)

The protocol uses the Hello transformer: MsgInit is sent first by the
client (StInit -> StIdle), then the server drives via StIdle.

Important: MsgDone can only be sent in StTxIds when the server's
MsgRequestTxIds was blocking (blocking=True). We model StTxIds as a
single state and track blocking vs non-blocking at the client level,
since the wire format uses the same state for both.

Size limits per state (from the Ouroboros spec):
    StIdle   -> 65535 bytes
    StTxIds  -> 65535 bytes (but can be larger for many txids)
    StTxs    -> 2500000 bytes (transactions can be large)

Time limits per state:
    StIdle   -> None (no timeout -- server drives at its own pace)
    StTxIds  -> 27 seconds (blocking), immediate for non-blocking
    StTxs    -> 60 seconds

Haskell reference:
    Ouroboros/Network/Protocol/TxSubmission2/Type.hs
    Ouroboros/Network/Protocol/TxSubmission2/Client.hs
    Ouroboros/Network/Protocol/TxSubmission2/Codec.hs

Spec reference:
    Ouroboros network spec, Section "Tx-Submission mini-protocol" (v2)
"""

from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import Awaitable, Callable

from vibe.cardano.network.txsubmission import (
    MsgDone,
    MsgInit,
    MsgReplyTxIds,
    MsgReplyTxs,
    MsgRequestTxIds,
    MsgRequestTxs,
    decode_client_message,
    decode_server_message,
    encode_done,
    encode_init,
    encode_reply_tx_ids,
    encode_reply_txs,
    encode_request_tx_ids,
    encode_request_txs,
)
from vibe.core.protocols.agency import (
    Agency,
    Message,
    PeerRole,
    Protocol,
    ProtocolError,
)
from vibe.core.protocols.codec import CodecError
from vibe.core.protocols.runner import ProtocolRunner

__all__ = [
    "TxSubmissionState",
    "TxSubmissionProtocol",
    "TxSubmissionCodec",
    "TxSubmissionClient",
    "run_tx_submission_client",
    "run_tx_submission_server",
    # Re-export message wrappers for convenience
    "TsMsgInit",
    "TsMsgRequestTxIds",
    "TsMsgReplyTxIds",
    "TsMsgRequestTxs",
    "TsMsgReplyTxs",
    "TsMsgDone",
    # Size and time limits
    "TX_SUBMISSION_SIZE_LIMITS",
    "TX_SUBMISSION_TIME_LIMITS",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol states
# ---------------------------------------------------------------------------


class TxSubmissionState(enum.Enum):
    """States of the tx-submission miniprotocol state machine.

    Haskell reference: TxSubmission2 type, with constructors
        StInit, StIdle, StTxIds (StBlocking | StNonBlocking), StTxs, StDone.

    We collapse StTxIds' two sub-states into a single value here, same
    as chain-sync collapses StNext sub-states. The blocking vs non-blocking
    distinction is tracked at the client level since it only affects which
    responses are valid (MsgDone is only valid when blocking).
    """

    StInit = "st_init"
    StIdle = "st_idle"
    StTxIds = "st_tx_ids"
    StTxs = "st_txs"
    StDone = "st_done"


# ---------------------------------------------------------------------------
# Size and time limits (from the Ouroboros spec)
# ---------------------------------------------------------------------------

#: Maximum message size in bytes per protocol state.
TX_SUBMISSION_SIZE_LIMITS: dict[TxSubmissionState, int] = {
    TxSubmissionState.StInit: 65535,
    TxSubmissionState.StIdle: 65535,
    TxSubmissionState.StTxIds: 65535,
    TxSubmissionState.StTxs: 2500000,
}

#: Timeout in seconds per protocol state. None means no timeout.
TX_SUBMISSION_TIME_LIMITS: dict[TxSubmissionState, float | None] = {
    TxSubmissionState.StInit: None,
    TxSubmissionState.StIdle: None,
    TxSubmissionState.StTxIds: 27.0,
    TxSubmissionState.StTxs: 60.0,
}


# ---------------------------------------------------------------------------
# Typed messages (Message wrappers with state transitions)
# ---------------------------------------------------------------------------


class TsMsgInit(Message[TxSubmissionState]):
    """Client -> Server: start the protocol.

    Transition: StInit -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=TxSubmissionState.StInit,
            to_state=TxSubmissionState.StIdle,
        )
        self.inner = MsgInit()


class TsMsgRequestTxIds(Message[TxSubmissionState]):
    """Server -> Client: request transaction IDs.

    Transition: StIdle -> StTxIds
    """

    __slots__ = ("inner",)

    def __init__(self, blocking: bool, ack_count: int, req_count: int) -> None:
        super().__init__(
            from_state=TxSubmissionState.StIdle,
            to_state=TxSubmissionState.StTxIds,
        )
        self.inner = MsgRequestTxIds(blocking=blocking, ack_count=ack_count, req_count=req_count)

    @property
    def blocking(self) -> bool:
        return self.inner.blocking

    @property
    def ack_count(self) -> int:
        return self.inner.ack_count

    @property
    def req_count(self) -> int:
        return self.inner.req_count


class TsMsgReplyTxIds(Message[TxSubmissionState]):
    """Client -> Server: reply with transaction IDs and sizes.

    Transition: StTxIds -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, txids: list[tuple[bytes, int]]) -> None:
        super().__init__(
            from_state=TxSubmissionState.StTxIds,
            to_state=TxSubmissionState.StIdle,
        )
        self.inner = MsgReplyTxIds(txids=txids)

    @property
    def txids(self) -> list[tuple[bytes, int]]:
        return self.inner.txids


class TsMsgRequestTxs(Message[TxSubmissionState]):
    """Server -> Client: request full transactions by ID.

    Transition: StIdle -> StTxs
    """

    __slots__ = ("inner",)

    def __init__(self, txids: list[bytes]) -> None:
        super().__init__(
            from_state=TxSubmissionState.StIdle,
            to_state=TxSubmissionState.StTxs,
        )
        self.inner = MsgRequestTxs(txids=txids)

    @property
    def txids(self) -> list[bytes]:
        return self.inner.txids


class TsMsgReplyTxs(Message[TxSubmissionState]):
    """Client -> Server: reply with full transactions.

    Transition: StTxs -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, txs: list[bytes]) -> None:
        super().__init__(
            from_state=TxSubmissionState.StTxs,
            to_state=TxSubmissionState.StIdle,
        )
        self.inner = MsgReplyTxs(txs=txs)

    @property
    def txs(self) -> list[bytes]:
        return self.inner.txs


class TsMsgDone(Message[TxSubmissionState]):
    """Client -> Server: terminate the protocol.

    Transition: StTxIds -> StDone

    Can only be sent when the server's MsgRequestTxIds was blocking.
    We don't enforce that at the FSM level (StTxIds is a single state),
    but the client tracks it.
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=TxSubmissionState.StTxIds,
            to_state=TxSubmissionState.StDone,
        )
        self.inner = MsgDone()


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------

# Pre-computed frozen sets for valid_messages.
_INIT_MESSAGES: frozenset[type[Message[TxSubmissionState]]] = frozenset({TsMsgInit})
_IDLE_MESSAGES: frozenset[type[Message[TxSubmissionState]]] = frozenset(
    {TsMsgRequestTxIds, TsMsgRequestTxs}
)
_TXIDS_MESSAGES: frozenset[type[Message[TxSubmissionState]]] = frozenset(
    {TsMsgReplyTxIds, TsMsgDone}
)
_TXS_MESSAGES: frozenset[type[Message[TxSubmissionState]]] = frozenset({TsMsgReplyTxs})
_DONE_MESSAGES: frozenset[type[Message[TxSubmissionState]]] = frozenset()


class TxSubmissionProtocol(Protocol[TxSubmissionState]):
    """Tx-submission miniprotocol state machine definition.

    Agency map (note: this protocol has inverted agency compared to most):
        StInit   -> Client (Initiator sends MsgInit)
        StIdle   -> Server (Responder sends MsgRequestTxIds or MsgRequestTxs)
        StTxIds  -> Client (Initiator sends MsgReplyTxIds or MsgDone)
        StTxs    -> Client (Initiator sends MsgReplyTxs)
        StDone   -> Nobody (terminal)

    Haskell reference:
        instance Protocol (TxSubmission2 txid tx) where
            type ClientHasAgency st = st in {StInit, StTxIds, StTxs}
            type ServerHasAgency st = st ~ StIdle
            type NobodyHasAgency st = st ~ StDone
    """

    _AGENCY_MAP = {
        TxSubmissionState.StInit: Agency.Client,
        TxSubmissionState.StIdle: Agency.Server,
        TxSubmissionState.StTxIds: Agency.Client,
        TxSubmissionState.StTxs: Agency.Client,
        TxSubmissionState.StDone: Agency.Nobody,
    }

    _VALID_MESSAGES = {
        TxSubmissionState.StInit: _INIT_MESSAGES,
        TxSubmissionState.StIdle: _IDLE_MESSAGES,
        TxSubmissionState.StTxIds: _TXIDS_MESSAGES,
        TxSubmissionState.StTxs: _TXS_MESSAGES,
        TxSubmissionState.StDone: _DONE_MESSAGES,
    }

    def initial_state(self) -> TxSubmissionState:
        return TxSubmissionState.StInit

    def agency(self, state: TxSubmissionState) -> Agency:
        try:
            return self._AGENCY_MAP[state]
        except KeyError:
            raise ProtocolError(f"Unknown tx-submission state: {state!r}")

    def valid_messages(
        self, state: TxSubmissionState
    ) -> frozenset[type[Message[TxSubmissionState]]]:
        try:
            return self._VALID_MESSAGES[state]
        except KeyError:
            raise ProtocolError(f"Unknown tx-submission state: {state!r}")


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class TxSubmissionCodec:
    """CBOR codec for tx-submission miniprotocol messages.

    Wraps the encode/decode functions from txsubmission.py, translating
    between typed Message wrappers (TsMsg*) and raw CBOR bytes.

    Implements the Codec protocol (structural typing).
    """

    def encode(self, message: Message[TxSubmissionState]) -> bytes:
        """Encode a typed tx-submission message to CBOR bytes."""
        if isinstance(message, TsMsgInit):
            return encode_init()
        elif isinstance(message, TsMsgRequestTxIds):
            return encode_request_tx_ids(message.blocking, message.ack_count, message.req_count)
        elif isinstance(message, TsMsgReplyTxIds):
            return encode_reply_tx_ids(message.txids)
        elif isinstance(message, TsMsgRequestTxs):
            return encode_request_txs(message.txids)
        elif isinstance(message, TsMsgReplyTxs):
            return encode_reply_txs(message.txs)
        elif isinstance(message, TsMsgDone):
            return encode_done()
        else:
            raise CodecError(f"Unknown tx-submission message type: {type(message).__name__}")

    def decode(self, data: bytes) -> Message[TxSubmissionState]:
        """Decode CBOR bytes into a typed tx-submission message.

        Tries server-side decode first, then client-side.
        """
        try:
            return self._decode_server(data)
        except ValueError:
            pass
        try:
            return self._decode_client(data)
        except ValueError:
            pass
        raise CodecError(f"Failed to decode tx-submission message ({len(data)} bytes)")

    def _decode_server(self, data: bytes) -> Message[TxSubmissionState]:
        """Decode a server-to-client message."""
        msg = decode_server_message(data)

        if isinstance(msg, MsgRequestTxIds):
            return TsMsgRequestTxIds(
                blocking=msg.blocking,
                ack_count=msg.ack_count,
                req_count=msg.req_count,
            )
        elif isinstance(msg, MsgRequestTxs):
            return TsMsgRequestTxs(txids=msg.txids)
        else:
            raise ValueError(f"Unexpected server message: {type(msg).__name__}")

    def _decode_client(self, data: bytes) -> Message[TxSubmissionState]:
        """Decode a client-to-server message."""
        msg = decode_client_message(data)

        if isinstance(msg, MsgInit):
            return TsMsgInit()
        elif isinstance(msg, MsgReplyTxIds):
            return TsMsgReplyTxIds(txids=msg.txids)
        elif isinstance(msg, MsgReplyTxs):
            return TsMsgReplyTxs(txs=msg.txs)
        elif isinstance(msg, MsgDone):
            return TsMsgDone()
        else:
            raise ValueError(f"Unexpected client message: {type(msg).__name__}")


# ---------------------------------------------------------------------------
# High-level client (Initiator side)
# ---------------------------------------------------------------------------

#: Type alias for the callback that provides tx IDs when the server requests them.
OnRequestTxIds = Callable[[bool, int, int], Awaitable[list[tuple[bytes, int]] | None]]
"""Called with (blocking, ack_count, req_count).
Return list of (txid, size) pairs, or None to signal done (blocking only)."""

#: Type alias for the callback that provides full transactions.
OnRequestTxs = Callable[[list[bytes]], Awaitable[list[bytes]]]
"""Called with list of requested txids. Return list of CBOR-encoded txs."""


class TxSubmissionClient:
    """High-level tx-submission client (Initiator).

    In the tx-submission protocol, the CLIENT (Initiator) is the one that
    has transactions to offer. The SERVER (Responder) pulls tx IDs and
    transactions from the client.

    This client handles the Initiator side: sending MsgInit, then
    responding to server requests with tx IDs and transactions via
    user-provided callbacks.

    Parameters
    ----------
    runner : ProtocolRunner[TxSubmissionState]
        A protocol runner already set up with TxSubmissionProtocol, codec,
        and a connected mux channel.
    """

    __slots__ = ("_runner",)

    def __init__(self, runner: ProtocolRunner[TxSubmissionState]) -> None:
        self._runner = runner

    @property
    def state(self) -> TxSubmissionState:
        """Current protocol state."""
        return self._runner.state

    @property
    def is_done(self) -> bool:
        """Whether the protocol has terminated."""
        return self._runner.is_done

    async def send_init(self) -> None:
        """Send MsgInit to start the protocol.

        Must be called first, transitions StInit -> StIdle.
        """
        await self._runner.send_message(TsMsgInit())

    async def recv_server_request(
        self,
    ) -> TsMsgRequestTxIds | TsMsgRequestTxs:
        """Wait for the server to send a request.

        The server has agency in StIdle and will send either
        MsgRequestTxIds or MsgRequestTxs.

        Returns:
        -------
        TsMsgRequestTxIds | TsMsgRequestTxs
            The server's request.
        """
        response = await self._runner.recv_message()

        if isinstance(response, (TsMsgRequestTxIds, TsMsgRequestTxs)):
            return response
        else:
            raise ProtocolError(f"Unexpected server message in StIdle: {type(response).__name__}")

    async def reply_tx_ids(self, txids: list[tuple[bytes, int]]) -> None:
        """Reply to MsgRequestTxIds with tx ID and size pairs.

        Parameters
        ----------
        txids : list[tuple[bytes, int]]
            List of (txid, size_in_bytes) pairs.
        """
        await self._runner.send_message(TsMsgReplyTxIds(txids=txids))

    async def reply_txs(self, txs: list[bytes]) -> None:
        """Reply to MsgRequestTxs with full transaction bodies.

        Parameters
        ----------
        txs : list[bytes]
            List of CBOR-encoded transactions.
        """
        await self._runner.send_message(TsMsgReplyTxs(txs=txs))

    async def done(self) -> None:
        """Send MsgDone to terminate the protocol.

        Can only be sent in StTxIds when the server's MsgRequestTxIds
        was blocking.
        """
        await self._runner.send_message(TsMsgDone())


# ---------------------------------------------------------------------------
# High-level client loop
# ---------------------------------------------------------------------------


async def run_tx_submission_client(
    channel: object,
    on_request_tx_ids: OnRequestTxIds,
    on_request_txs: OnRequestTxs,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the tx-submission client protocol loop.

    This is the main entry point for offering transactions. It:
    1. Creates a ProtocolRunner with TxSubmissionProtocol and codec.
    2. Sends MsgInit to start the protocol.
    3. Loops: receives server requests, dispatches to callbacks.
    4. Sends MsgDone when on_request_tx_ids returns None or stop_event is set.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for tx-submission.
    on_request_tx_ids : OnRequestTxIds
        Async callback invoked when the server requests tx IDs.
        Called with (blocking, ack_count, req_count).
        Return list of (txid, size) pairs, or None to signal done
        (only valid when blocking=True).
    on_request_txs : OnRequestTxs
        Async callback invoked when the server requests full transactions.
        Called with list of requested txids.
        Return list of CBOR-encoded transactions.
    stop_event : asyncio.Event | None
        If provided, the loop exits when this event is set.
    """
    protocol = TxSubmissionProtocol()
    codec = TxSubmissionCodec()
    runner = ProtocolRunner(
        role=PeerRole.Initiator,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    client = TxSubmissionClient(runner)

    # Step 1: Send MsgInit
    await client.send_init()
    logger.debug("Tx-submission: sent MsgInit, entering main loop")

    # Step 2: Main loop -- respond to server requests
    while not client.is_done:
        if stop_event is not None and stop_event.is_set():
            logger.debug("Tx-submission stop requested")
            # We can only send MsgDone from StTxIds after a blocking request.
            # If we're in StIdle, we need to wait for a blocking request first.
            # For now, just break and let the connection close.
            break

        request = await client.recv_server_request()

        if isinstance(request, TsMsgRequestTxIds):
            result = await on_request_tx_ids(
                request.blocking, request.ack_count, request.req_count
            )
            if result is None:
                # Client wants to terminate -- only valid for blocking requests
                if request.blocking:
                    await client.done()
                    logger.debug("Tx-submission: sent MsgDone, protocol complete")
                    return
                else:
                    # Non-blocking: reply with empty list instead
                    await client.reply_tx_ids([])
            else:
                await client.reply_tx_ids(result)

        elif isinstance(request, TsMsgRequestTxs):
            txs = await on_request_txs(request.txids)
            await client.reply_txs(txs)


# ---------------------------------------------------------------------------
# Server-side tx-submission runner
# ---------------------------------------------------------------------------

# Callback types for the server
OnTxIdsReceived = Callable[[list[tuple[bytes, int]]], Awaitable[None]]
OnTxsReceived = Callable[[list[bytes]], Awaitable[None]]


async def run_tx_submission_server(
    channel: object,
    on_tx_ids_received: OnTxIdsReceived,
    on_txs_received: OnTxsReceived,
    *,
    max_tx_ids_to_request: int = 10,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the server side of the N2N tx-submission miniprotocol.

    As the server, we drive the protocol by requesting tx IDs and then
    requesting the full transactions. This is how we pull transactions
    from peers into our mempool.

    The protocol is "inverted agency" — the server sends requests in
    StIdle, and the client replies.

    Haskell ref:
        ``Ouroboros.Network.Protocol.TxSubmission2.Server``

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for tx-submission (responder direction).
    on_tx_ids_received : OnTxIdsReceived
        Async callback invoked with a list of (txid, size) pairs.
    on_txs_received : OnTxsReceived
        Async callback invoked with a list of CBOR-encoded transactions.
    max_tx_ids_to_request : int
        How many tx IDs to request at a time.
    stop_event : asyncio.Event | None
        If provided, the server exits when this event is set.
    """
    protocol = TxSubmissionProtocol()
    codec = TxSubmissionCodec()
    runner = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )

    logger.debug("Tx-submission server started")

    # Wait for MsgInit from client
    msg = await runner.recv_message()
    if not isinstance(msg, TsMsgInit):
        logger.warning("Tx-submission server: expected MsgInit, got %s", type(msg).__name__)
        return

    # Track acknowledged tx IDs
    outstanding_tx_ids: list[tuple[bytes, int]] = []

    while True:
        if stop_event is not None and stop_event.is_set():
            return

        # Request tx IDs from the peer (blocking if we have none outstanding)
        blocking = len(outstanding_tx_ids) == 0
        ack_count = 0  # We ack all previously received IDs
        await runner.send_message(
            TsMsgRequestTxIds(
                blocking=blocking,
                ack_count=ack_count,
                req_count=max_tx_ids_to_request,
            )
        )

        # Receive reply
        reply = await runner.recv_message()

        if isinstance(reply, TsMsgDone):
            logger.debug("Tx-submission server: client sent Done")
            return

        if isinstance(reply, TsMsgReplyTxIds):
            if reply.txids:
                await on_tx_ids_received(reply.txids)
                outstanding_tx_ids.extend(reply.txids)

                # Request the actual transactions
                txids_to_fetch = [tid for tid, _ in outstanding_tx_ids]
                if txids_to_fetch:
                    await runner.send_message(TsMsgRequestTxs(txids=txids_to_fetch))
                    tx_reply = await runner.recv_message()
                    if isinstance(tx_reply, TsMsgReplyTxs):
                        if tx_reply.txs:
                            await on_txs_received(tx_reply.txs)
                    outstanding_tx_ids.clear()
            else:
                # Empty reply to non-blocking request — peer has nothing.
                # Brief sleep to avoid busy-wait.
                await asyncio.sleep(1.0)

        else:
            logger.warning(
                "Tx-submission server: unexpected reply %s",
                type(reply).__name__,
            )
            return
