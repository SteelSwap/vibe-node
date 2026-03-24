"""Local Tx-Monitor miniprotocol -- typed protocol FSM, codec, and server.

Implements the N2C local tx-monitor miniprotocol as a typed state machine
following the Ouroboros typed-protocols pattern. This protocol allows local
clients to query the mempool: acquire a consistent snapshot, iterate
transactions, check membership, and get size statistics.

States:

    StIdle       -- Client has agency (sends MsgAcquire, MsgAwaitAcquire, or MsgDone)
    StAcquiring  -- Server has agency (sends MsgAcquired)
    StAcquired   -- Client has agency (sends MsgRelease, MsgNextTx, MsgHasTx, MsgGetSizes, MsgAwaitAcquire)
    StBusy (sub) -- Server has agency for query responses:
        StBusyNextTx    -- Server sends MsgReplyNextTx
        StBusyHasTx     -- Server sends MsgReplyHasTx
        StBusyGetSizes  -- Server sends MsgReplyGetSizes
    StDone       -- Nobody has agency (terminal)

We collapse the StBusy sub-states into separate enum values so the FSM
can track which reply is expected. This matches the Haskell approach
where StBusy has type-level tags.

Haskell reference:
    Ouroboros/Network/Protocol/LocalTxMonitor/Type.hs
    Ouroboros/Network/Protocol/LocalTxMonitor/Server.hs
    Ouroboros/Network/Protocol/LocalTxMonitor/Codec.hs

Spec reference:
    Ouroboros network spec, "Local Tx-Monitor Mini-Protocol"
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Awaitable, Callable

from vibe.cardano.network.local_txmonitor import (
    MsgAcquire,
    MsgAcquired,
    MsgAwaitAcquire,
    MsgDone,
    MsgGetSizes,
    MsgHasTx,
    MsgNextTx,
    MsgRelease,
    MsgReplyGetSizes,
    MsgReplyHasTx,
    MsgReplyNextTx,
    decode_message,
    encode_acquire,
    encode_acquired,
    encode_await_acquire,
    encode_done,
    encode_get_sizes,
    encode_has_tx,
    encode_next_tx,
    encode_release,
    encode_reply_get_sizes,
    encode_reply_has_tx,
    encode_reply_next_tx,
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
    "LocalTxMonitorState",
    "LocalTxMonitorProtocol",
    "LocalTxMonitorCodec",
    "LocalTxMonitorServer",
    "run_local_tx_monitor_server",
    # Typed message wrappers
    "LtmMsgAcquire",
    "LtmMsgAcquired",
    "LtmMsgAwaitAcquire",
    "LtmMsgRelease",
    "LtmMsgNextTx",
    "LtmMsgReplyNextTx",
    "LtmMsgHasTx",
    "LtmMsgReplyHasTx",
    "LtmMsgGetSizes",
    "LtmMsgReplyGetSizes",
    "LtmMsgDone",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol states
# ---------------------------------------------------------------------------


class LocalTxMonitorState(enum.Enum):
    """States of the local tx-monitor miniprotocol state machine.

    Haskell reference: LocalTxMonitor type, with constructors
        StIdle, StAcquiring, StAcquired, StBusy (NextTx | HasTx | GetSizes),
        StDone.

    We split StBusy into three concrete states so the FSM knows which
    reply message is valid.
    """

    StIdle = "st_idle"
    """Client has agency -- sends MsgAcquire, MsgAwaitAcquire, or MsgDone."""

    StAcquiring = "st_acquiring"
    """Server has agency -- sends MsgAcquired."""

    StAcquired = "st_acquired"
    """Client has agency -- sends query messages or MsgRelease/MsgAwaitAcquire."""

    StBusyNextTx = "st_busy_next_tx"
    """Server has agency -- sends MsgReplyNextTx."""

    StBusyHasTx = "st_busy_has_tx"
    """Server has agency -- sends MsgReplyHasTx."""

    StBusyGetSizes = "st_busy_get_sizes"
    """Server has agency -- sends MsgReplyGetSizes."""

    StDone = "st_done"
    """Terminal state. Nobody has agency. Protocol complete."""


# ---------------------------------------------------------------------------
# Typed messages (Message wrappers with state transitions)
# ---------------------------------------------------------------------------


class LtmMsgAcquire(Message[LocalTxMonitorState]):
    """Client -> Server: request mempool snapshot.

    Transition: StIdle -> StAcquiring
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StIdle,
            to_state=LocalTxMonitorState.StAcquiring,
        )
        self.inner = MsgAcquire()


class LtmMsgAcquired(Message[LocalTxMonitorState]):
    """Server -> Client: snapshot acquired at slot.

    Transition: StAcquiring -> StAcquired
    """

    __slots__ = ("inner",)

    def __init__(self, slot: int) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StAcquiring,
            to_state=LocalTxMonitorState.StAcquired,
        )
        self.inner = MsgAcquired(slot=slot)

    @property
    def slot(self) -> int:
        return self.inner.slot


class LtmMsgAwaitAcquire(Message[LocalTxMonitorState]):
    """Client -> Server: wait for mempool change, then acquire.

    Transition: StAcquired -> StAcquiring

    Note: MsgAwaitAcquire can be sent from StIdle (initial acquire) or
    StAcquired (re-acquire after queries). We model two separate message
    types for the two source states.
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StAcquired,
            to_state=LocalTxMonitorState.StAcquiring,
        )
        self.inner = MsgAwaitAcquire()


class LtmMsgAwaitAcquireIdle(Message[LocalTxMonitorState]):
    """Client -> Server: wait for mempool change (from StIdle).

    Transition: StIdle -> StAcquiring
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StIdle,
            to_state=LocalTxMonitorState.StAcquiring,
        )
        self.inner = MsgAwaitAcquire()


class LtmMsgRelease(Message[LocalTxMonitorState]):
    """Client -> Server: release the mempool snapshot.

    Transition: StAcquired -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StAcquired,
            to_state=LocalTxMonitorState.StIdle,
        )
        self.inner = MsgRelease()


class LtmMsgNextTx(Message[LocalTxMonitorState]):
    """Client -> Server: request next transaction.

    Transition: StAcquired -> StBusyNextTx
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StAcquired,
            to_state=LocalTxMonitorState.StBusyNextTx,
        )
        self.inner = MsgNextTx()


class LtmMsgReplyNextTx(Message[LocalTxMonitorState]):
    """Server -> Client: reply with next transaction or Nothing.

    Transition: StBusyNextTx -> StAcquired
    """

    __slots__ = ("inner",)

    def __init__(self, tx: tuple[int, bytes] | None) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StBusyNextTx,
            to_state=LocalTxMonitorState.StAcquired,
        )
        self.inner = MsgReplyNextTx(tx=tx)

    @property
    def tx(self) -> tuple[int, bytes] | None:
        return self.inner.tx


class LtmMsgHasTx(Message[LocalTxMonitorState]):
    """Client -> Server: check if tx is in mempool.

    Transition: StAcquired -> StBusyHasTx
    """

    __slots__ = ("inner",)

    def __init__(self, tx_id: bytes) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StAcquired,
            to_state=LocalTxMonitorState.StBusyHasTx,
        )
        self.inner = MsgHasTx(tx_id=tx_id)

    @property
    def tx_id(self) -> bytes:
        return self.inner.tx_id


class LtmMsgReplyHasTx(Message[LocalTxMonitorState]):
    """Server -> Client: whether tx is in mempool.

    Transition: StBusyHasTx -> StAcquired
    """

    __slots__ = ("inner",)

    def __init__(self, has_tx: bool) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StBusyHasTx,
            to_state=LocalTxMonitorState.StAcquired,
        )
        self.inner = MsgReplyHasTx(has_tx=has_tx)

    @property
    def has_tx(self) -> bool:
        return self.inner.has_tx


class LtmMsgGetSizes(Message[LocalTxMonitorState]):
    """Client -> Server: request mempool size statistics.

    Transition: StAcquired -> StBusyGetSizes
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StAcquired,
            to_state=LocalTxMonitorState.StBusyGetSizes,
        )
        self.inner = MsgGetSizes()


class LtmMsgReplyGetSizes(Message[LocalTxMonitorState]):
    """Server -> Client: mempool size statistics.

    Transition: StBusyGetSizes -> StAcquired
    """

    __slots__ = ("inner",)

    def __init__(self, num_txs: int, total_size: int, num_bytes: int) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StBusyGetSizes,
            to_state=LocalTxMonitorState.StAcquired,
        )
        self.inner = MsgReplyGetSizes(num_txs=num_txs, total_size=total_size, num_bytes=num_bytes)

    @property
    def num_txs(self) -> int:
        return self.inner.num_txs

    @property
    def total_size(self) -> int:
        return self.inner.total_size

    @property
    def num_bytes(self) -> int:
        return self.inner.num_bytes


class LtmMsgDone(Message[LocalTxMonitorState]):
    """Client -> Server: terminate the protocol.

    Transition: StIdle -> StDone
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalTxMonitorState.StIdle,
            to_state=LocalTxMonitorState.StDone,
        )
        self.inner = MsgDone()


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------

# Pre-computed frozen sets for valid_messages.
_IDLE_MESSAGES: frozenset[type[Message[LocalTxMonitorState]]] = frozenset(
    {LtmMsgAcquire, LtmMsgAwaitAcquireIdle, LtmMsgDone}
)
_ACQUIRING_MESSAGES: frozenset[type[Message[LocalTxMonitorState]]] = frozenset({LtmMsgAcquired})
_ACQUIRED_MESSAGES: frozenset[type[Message[LocalTxMonitorState]]] = frozenset(
    {LtmMsgRelease, LtmMsgNextTx, LtmMsgHasTx, LtmMsgGetSizes, LtmMsgAwaitAcquire}
)
_BUSY_NEXT_TX_MESSAGES: frozenset[type[Message[LocalTxMonitorState]]] = frozenset(
    {LtmMsgReplyNextTx}
)
_BUSY_HAS_TX_MESSAGES: frozenset[type[Message[LocalTxMonitorState]]] = frozenset(
    {LtmMsgReplyHasTx}
)
_BUSY_GET_SIZES_MESSAGES: frozenset[type[Message[LocalTxMonitorState]]] = frozenset(
    {LtmMsgReplyGetSizes}
)
_DONE_MESSAGES: frozenset[type[Message[LocalTxMonitorState]]] = frozenset()


class LocalTxMonitorProtocol(Protocol[LocalTxMonitorState]):
    """Local tx-monitor miniprotocol state machine definition.

    Agency map:
        StIdle          -> Client
        StAcquiring     -> Server
        StAcquired      -> Client
        StBusyNextTx    -> Server
        StBusyHasTx     -> Server
        StBusyGetSizes  -> Server
        StDone          -> Nobody

    Haskell reference:
        instance Protocol (LocalTxMonitor txid tx slot) where
            type ClientHasAgency st = st in {StIdle, StAcquired}
            type ServerHasAgency st = st in {StAcquiring, StBusy kind}
            type NobodyHasAgency st = st ~ StDone
    """

    _AGENCY_MAP = {
        LocalTxMonitorState.StIdle: Agency.Client,
        LocalTxMonitorState.StAcquiring: Agency.Server,
        LocalTxMonitorState.StAcquired: Agency.Client,
        LocalTxMonitorState.StBusyNextTx: Agency.Server,
        LocalTxMonitorState.StBusyHasTx: Agency.Server,
        LocalTxMonitorState.StBusyGetSizes: Agency.Server,
        LocalTxMonitorState.StDone: Agency.Nobody,
    }

    _VALID_MESSAGES = {
        LocalTxMonitorState.StIdle: _IDLE_MESSAGES,
        LocalTxMonitorState.StAcquiring: _ACQUIRING_MESSAGES,
        LocalTxMonitorState.StAcquired: _ACQUIRED_MESSAGES,
        LocalTxMonitorState.StBusyNextTx: _BUSY_NEXT_TX_MESSAGES,
        LocalTxMonitorState.StBusyHasTx: _BUSY_HAS_TX_MESSAGES,
        LocalTxMonitorState.StBusyGetSizes: _BUSY_GET_SIZES_MESSAGES,
        LocalTxMonitorState.StDone: _DONE_MESSAGES,
    }

    def initial_state(self) -> LocalTxMonitorState:
        return LocalTxMonitorState.StIdle

    def agency(self, state: LocalTxMonitorState) -> Agency:
        try:
            return self._AGENCY_MAP[state]
        except KeyError:
            raise ProtocolError(f"Unknown local tx-monitor state: {state!r}")

    def valid_messages(
        self, state: LocalTxMonitorState
    ) -> frozenset[type[Message[LocalTxMonitorState]]]:
        try:
            return self._VALID_MESSAGES[state]
        except KeyError:
            raise ProtocolError(f"Unknown local tx-monitor state: {state!r}")


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class LocalTxMonitorCodec:
    """CBOR codec for local tx-monitor miniprotocol messages.

    Wraps the encode/decode functions from local_txmonitor.py,
    translating between typed Message wrappers (LtmMsg*) and raw CBOR bytes.

    Implements the Codec protocol (structural typing).
    """

    def encode(self, message: Message[LocalTxMonitorState]) -> bytes:
        """Encode a typed local tx-monitor message to CBOR bytes."""
        if isinstance(message, LtmMsgAcquire):
            return encode_acquire()
        elif isinstance(message, (LtmMsgAwaitAcquire, LtmMsgAwaitAcquireIdle)):
            return encode_await_acquire()
        elif isinstance(message, LtmMsgAcquired):
            return encode_acquired(message.slot)
        elif isinstance(message, LtmMsgRelease):
            return encode_release()
        elif isinstance(message, LtmMsgNextTx):
            return encode_next_tx()
        elif isinstance(message, LtmMsgReplyNextTx):
            return encode_reply_next_tx(message.tx)
        elif isinstance(message, LtmMsgHasTx):
            return encode_has_tx(message.tx_id)
        elif isinstance(message, LtmMsgReplyHasTx):
            return encode_reply_has_tx(message.has_tx)
        elif isinstance(message, LtmMsgGetSizes):
            return encode_get_sizes()
        elif isinstance(message, LtmMsgReplyGetSizes):
            return encode_reply_get_sizes(message.num_txs, message.total_size, message.num_bytes)
        elif isinstance(message, LtmMsgDone):
            return encode_done()
        else:
            raise CodecError(f"Unknown local tx-monitor message type: {type(message).__name__}")

    def decode(self, data: bytes) -> Message[LocalTxMonitorState]:
        """Decode CBOR bytes into a typed local tx-monitor message.

        Note: MsgAwaitAcquire on the wire is ambiguous -- it can come from
        StIdle or StAcquired. We decode it as LtmMsgAwaitAcquire (from
        StAcquired) by default. The caller (ProtocolRunner) will validate
        the from_state against the current protocol state. For StIdle,
        we also check and return LtmMsgAwaitAcquireIdle.

        In practice, the ProtocolRunner tracks state, so we try both
        variants and let the runner's validation pick the right one.
        """
        try:
            msg = decode_message(data)
        except ValueError as exc:
            raise CodecError(str(exc)) from exc

        if isinstance(msg, MsgAcquire):
            return LtmMsgAcquire()
        elif isinstance(msg, MsgAcquired):
            return LtmMsgAcquired(slot=msg.slot)
        elif isinstance(msg, MsgAwaitAcquire):
            # Ambiguous: could be from StIdle or StAcquired.
            # Return the StAcquired variant; the codec also provides
            # a fallback mechanism below.
            return LtmMsgAwaitAcquire()
        elif isinstance(msg, MsgRelease):
            return LtmMsgRelease()
        elif isinstance(msg, MsgNextTx):
            return LtmMsgNextTx()
        elif isinstance(msg, MsgReplyNextTx):
            return LtmMsgReplyNextTx(tx=msg.tx)
        elif isinstance(msg, MsgHasTx):
            return LtmMsgHasTx(tx_id=msg.tx_id)
        elif isinstance(msg, MsgReplyHasTx):
            return LtmMsgReplyHasTx(has_tx=msg.has_tx)
        elif isinstance(msg, MsgGetSizes):
            return LtmMsgGetSizes()
        elif isinstance(msg, MsgReplyGetSizes):
            return LtmMsgReplyGetSizes(
                num_txs=msg.num_txs,
                total_size=msg.total_size,
                num_bytes=msg.num_bytes,
            )
        elif isinstance(msg, MsgDone):
            return LtmMsgDone()
        else:
            raise CodecError(f"Failed to decode local tx-monitor message ({len(data)} bytes)")

    def decode_for_state(
        self, data: bytes, state: LocalTxMonitorState
    ) -> Message[LocalTxMonitorState]:
        """Decode with state hint to disambiguate MsgAwaitAcquire.

        Parameters
        ----------
        data : bytes
            CBOR-encoded message.
        state : LocalTxMonitorState
            Current protocol state, used to disambiguate messages that
            share the same wire encoding but have different from_states.
        """
        try:
            msg = decode_message(data)
        except ValueError as exc:
            raise CodecError(str(exc)) from exc

        if isinstance(msg, MsgAwaitAcquire):
            if state == LocalTxMonitorState.StIdle:
                return LtmMsgAwaitAcquireIdle()
            return LtmMsgAwaitAcquire()

        # For all other messages, delegate to the standard decode.
        return self.decode(data)


# ---------------------------------------------------------------------------
# Mempool snapshot interface (structural typing)
# ---------------------------------------------------------------------------

#: Type for acquiring a mempool snapshot. Returns the slot number.
AcquireSnapshot = Callable[[], Awaitable[int]]

#: Type for getting the next tx from the snapshot. Returns (era_id, tx_bytes) or None.
GetNextTx = Callable[[], Awaitable[tuple[int, bytes] | None]]

#: Type for checking if a tx_id is in the snapshot. Returns bool.
HasTxInSnapshot = Callable[[bytes], Awaitable[bool]]

#: Type for getting mempool sizes. Returns (num_txs, total_size, num_bytes).
GetMempoolSizes = Callable[[], Awaitable[tuple[int, int, int]]]


# ---------------------------------------------------------------------------
# High-level server (Responder side)
# ---------------------------------------------------------------------------


class LocalTxMonitorServer:
    """High-level local tx-monitor server (Responder).

    The server provides mempool snapshot queries to local clients.

    Parameters
    ----------
    runner : ProtocolRunner[LocalTxMonitorState]
        A protocol runner set up as Responder with the local tx-monitor
        protocol, codec, and a connected mux channel.
    """

    __slots__ = ("_runner",)

    def __init__(self, runner: ProtocolRunner[LocalTxMonitorState]) -> None:
        self._runner = runner

    @property
    def state(self) -> LocalTxMonitorState:
        return self._runner.state

    @property
    def is_done(self) -> bool:
        return self._runner.is_done

    async def recv_client_message(self) -> Message[LocalTxMonitorState]:
        """Wait for the client to send a message."""
        return await self._runner.recv_message()

    async def send_acquired(self, slot: int) -> None:
        """Send MsgAcquired with the snapshot slot."""
        await self._runner.send_message(LtmMsgAcquired(slot=slot))

    async def send_reply_next_tx(self, tx: tuple[int, bytes] | None) -> None:
        """Send MsgReplyNextTx with a transaction or Nothing."""
        await self._runner.send_message(LtmMsgReplyNextTx(tx=tx))

    async def send_reply_has_tx(self, has_tx: bool) -> None:
        """Send MsgReplyHasTx."""
        await self._runner.send_message(LtmMsgReplyHasTx(has_tx=has_tx))

    async def send_reply_get_sizes(self, num_txs: int, total_size: int, num_bytes: int) -> None:
        """Send MsgReplyGetSizes."""
        await self._runner.send_message(
            LtmMsgReplyGetSizes(
                num_txs=num_txs,
                total_size=total_size,
                num_bytes=num_bytes,
            )
        )


# ---------------------------------------------------------------------------
# High-level server loop
# ---------------------------------------------------------------------------


async def run_local_tx_monitor_server(
    channel: object,
    acquire_snapshot: AcquireSnapshot,
    get_next_tx: GetNextTx,
    has_tx_in_snapshot: HasTxInSnapshot,
    get_mempool_sizes: GetMempoolSizes,
) -> None:
    """Run the local tx-monitor server protocol loop.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for local tx-monitor.
    acquire_snapshot : AcquireSnapshot
        Async callback to acquire a mempool snapshot. Returns slot number.
    get_next_tx : GetNextTx
        Async callback to get the next tx from the snapshot.
    has_tx_in_snapshot : HasTxInSnapshot
        Async callback to check if a tx_id is in the snapshot.
    get_mempool_sizes : GetMempoolSizes
        Async callback to get mempool size stats.
    """
    protocol = LocalTxMonitorProtocol()
    codec = LocalTxMonitorCodec()
    runner = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    server = LocalTxMonitorServer(runner)

    while not server.is_done:
        client_msg = await server.recv_client_message()

        if isinstance(client_msg, LtmMsgDone):
            logger.debug("Local tx-monitor: client sent MsgDone, terminating")
            return

        elif isinstance(client_msg, (LtmMsgAcquire, LtmMsgAwaitAcquireIdle, LtmMsgAwaitAcquire)):
            slot = await acquire_snapshot()
            await server.send_acquired(slot)
            logger.debug("Local tx-monitor: acquired snapshot at slot %d", slot)

        elif isinstance(client_msg, LtmMsgRelease):
            logger.debug("Local tx-monitor: snapshot released")
            # State transitions back to StIdle automatically via the message.

        elif isinstance(client_msg, LtmMsgNextTx):
            tx = await get_next_tx()
            await server.send_reply_next_tx(tx)

        elif isinstance(client_msg, LtmMsgHasTx):
            result = await has_tx_in_snapshot(client_msg.tx_id)
            await server.send_reply_has_tx(result)

        elif isinstance(client_msg, LtmMsgGetSizes):
            num_txs, total_size, num_bytes = await get_mempool_sizes()
            await server.send_reply_get_sizes(num_txs, total_size, num_bytes)

        else:
            raise ProtocolError(
                f"Unexpected message in tx-monitor server: {type(client_msg).__name__}"
            )
