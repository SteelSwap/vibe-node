"""Local State-Query miniprotocol — typed protocol FSM, codec, and server.

Implements the N2C local state-query miniprotocol as a typed state machine
following the Ouroboros typed-protocols pattern. This is the most complex
N2C protocol — clients acquire a ledger state at a chain point and then
run multiple queries against it.

States:

    StIdle      — Client has agency (sends MsgAcquire, MsgDone)
    StAcquiring — Server has agency (sends MsgAcquired or MsgFailure)
    StAcquired  — Client has agency (sends MsgQuery, MsgReAcquire, MsgRelease)
    StQuerying  — Server has agency (sends MsgResult)
    StDone      — Nobody has agency (terminal)

Agency map (this is a standard N2C protocol where the client drives):
    StIdle      -> Client (Initiator sends MsgAcquire or MsgDone)
    StAcquiring -> Server (Responder sends MsgAcquired or MsgFailure)
    StAcquired  -> Client (Initiator sends MsgQuery, MsgReAcquire, MsgRelease)
    StQuerying  -> Server (Responder sends MsgResult)
    StDone      -> Nobody (terminal)

Haskell reference:
    Ouroboros/Network/Protocol/LocalStateQuery/Type.hs
    Ouroboros/Network/Protocol/LocalStateQuery/Server.hs
    Ouroboros/Network/Protocol/LocalStateQuery/Codec.hs

Spec reference:
    Ouroboros network spec, "Local State Query Mini-Protocol"
"""

from __future__ import annotations

import enum
import logging
from fractions import Fraction
from typing import Any

from vibe.core.protocols.agency import (
    Agency,
    Message,
    Protocol,
    ProtocolError,
    PeerRole,
)
from vibe.core.protocols.codec import Codec, CodecError
from vibe.core.protocols.runner import ProtocolRunner

from vibe.cardano.network.local_statequery import (
    AcquireFailureReason,
    MsgAcquire,
    MsgAcquired,
    MsgDone,
    MsgFailure,
    MsgQuery,
    MsgReAcquire,
    MsgRelease,
    MsgResult,
    Point,
    Query,
    QueryType,
    decode_message,
    encode_acquire,
    encode_acquired,
    encode_done,
    encode_failure,
    encode_query,
    encode_reacquire,
    encode_release,
    encode_result,
)

__all__ = [
    "LocalStateQueryState",
    "LocalStateQueryProtocol",
    "LocalStateQueryCodec",
    "LocalStateQueryServer",
    "LsqMsgAcquire",
    "LsqMsgFailure",
    "LsqMsgAcquired",
    "LsqMsgQuery",
    "LsqMsgResult",
    "LsqMsgRelease",
    "LsqMsgReAcquire",
    "LsqMsgDone",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol states
# ---------------------------------------------------------------------------


class LocalStateQueryState(enum.Enum):
    """States of the local state-query miniprotocol state machine.

    Haskell reference: LocalStateQuery type, with constructors
        StIdle, StAcquiring, StAcquired, StQuerying, StDone.
    """

    StIdle = "st_idle"
    """Client has agency — sends MsgAcquire or MsgDone."""

    StAcquiring = "st_acquiring"
    """Server has agency — sends MsgAcquired or MsgFailure."""

    StAcquired = "st_acquired"
    """Client has agency — sends MsgQuery, MsgReAcquire, or MsgRelease."""

    StQuerying = "st_querying"
    """Server has agency — sends MsgResult."""

    StDone = "st_done"
    """Terminal state. Nobody has agency. Protocol complete."""


# ---------------------------------------------------------------------------
# Typed messages (Message wrappers with state transitions)
# ---------------------------------------------------------------------------


class LsqMsgAcquire(Message[LocalStateQueryState]):
    """Client -> Server: acquire ledger state at a point.

    Transition: StIdle -> StAcquiring
    """

    __slots__ = ("inner",)

    def __init__(self, point: Point | None) -> None:
        super().__init__(
            from_state=LocalStateQueryState.StIdle,
            to_state=LocalStateQueryState.StAcquiring,
        )
        self.inner = MsgAcquire(point=point)

    @property
    def point(self) -> Point | None:
        return self.inner.point


class LsqMsgFailure(Message[LocalStateQueryState]):
    """Server -> Client: acquisition failed.

    Transition: StAcquiring -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, reason: AcquireFailureReason) -> None:
        super().__init__(
            from_state=LocalStateQueryState.StAcquiring,
            to_state=LocalStateQueryState.StIdle,
        )
        self.inner = MsgFailure(reason=reason)

    @property
    def reason(self) -> AcquireFailureReason:
        return self.inner.reason


class LsqMsgAcquired(Message[LocalStateQueryState]):
    """Server -> Client: acquisition succeeded.

    Transition: StAcquiring -> StAcquired
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalStateQueryState.StAcquiring,
            to_state=LocalStateQueryState.StAcquired,
        )
        self.inner = MsgAcquired()


class LsqMsgQuery(Message[LocalStateQueryState]):
    """Client -> Server: submit a query.

    Transition: StAcquired -> StQuerying
    """

    __slots__ = ("inner",)

    def __init__(self, query: Query) -> None:
        super().__init__(
            from_state=LocalStateQueryState.StAcquired,
            to_state=LocalStateQueryState.StQuerying,
        )
        self.inner = MsgQuery(query=query)

    @property
    def query(self) -> Query:
        return self.inner.query


class LsqMsgResult(Message[LocalStateQueryState]):
    """Server -> Client: query result.

    Transition: StQuerying -> StAcquired
    """

    __slots__ = ("inner",)

    def __init__(self, result: Any) -> None:
        super().__init__(
            from_state=LocalStateQueryState.StQuerying,
            to_state=LocalStateQueryState.StAcquired,
        )
        self.inner = MsgResult(result=result)

    @property
    def result(self) -> Any:
        return self.inner.result


class LsqMsgRelease(Message[LocalStateQueryState]):
    """Client -> Server: release the acquired state.

    Transition: StAcquired -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalStateQueryState.StAcquired,
            to_state=LocalStateQueryState.StIdle,
        )
        self.inner = MsgRelease()


class LsqMsgReAcquire(Message[LocalStateQueryState]):
    """Client -> Server: re-acquire at a different point.

    Transition: StAcquired -> StAcquiring
    """

    __slots__ = ("inner",)

    def __init__(self, point: Point | None) -> None:
        super().__init__(
            from_state=LocalStateQueryState.StAcquired,
            to_state=LocalStateQueryState.StAcquiring,
        )
        self.inner = MsgReAcquire(point=point)

    @property
    def point(self) -> Point | None:
        return self.inner.point


class LsqMsgDone(Message[LocalStateQueryState]):
    """Client -> Server: terminate the protocol.

    Transition: StIdle -> StDone
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalStateQueryState.StIdle,
            to_state=LocalStateQueryState.StDone,
        )
        self.inner = MsgDone()


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------

# Pre-computed frozen sets for valid_messages.
_IDLE_MESSAGES: frozenset[type[Message[LocalStateQueryState]]] = frozenset(
    {LsqMsgAcquire, LsqMsgDone}
)
_ACQUIRING_MESSAGES: frozenset[type[Message[LocalStateQueryState]]] = frozenset(
    {LsqMsgAcquired, LsqMsgFailure}
)
_ACQUIRED_MESSAGES: frozenset[type[Message[LocalStateQueryState]]] = frozenset(
    {LsqMsgQuery, LsqMsgReAcquire, LsqMsgRelease}
)
_QUERYING_MESSAGES: frozenset[type[Message[LocalStateQueryState]]] = frozenset(
    {LsqMsgResult}
)
_DONE_MESSAGES: frozenset[type[Message[LocalStateQueryState]]] = frozenset()


class LocalStateQueryProtocol(Protocol[LocalStateQueryState]):
    """Local state-query miniprotocol state machine definition.

    Agency map:
        StIdle      -> Client (Initiator sends MsgAcquire or MsgDone)
        StAcquiring -> Server (Responder sends MsgAcquired or MsgFailure)
        StAcquired  -> Client (Initiator sends MsgQuery, MsgReAcquire, MsgRelease)
        StQuerying  -> Server (Responder sends MsgResult)
        StDone      -> Nobody (terminal)

    Haskell reference:
        instance Protocol (LocalStateQuery block point query) where
            type ClientHasAgency st = st in {StIdle, StAcquired}
            type ServerHasAgency st = st in {StAcquiring, StQuerying}
            type NobodyHasAgency st = st ~ StDone
    """

    _AGENCY_MAP = {
        LocalStateQueryState.StIdle: Agency.Client,
        LocalStateQueryState.StAcquiring: Agency.Server,
        LocalStateQueryState.StAcquired: Agency.Client,
        LocalStateQueryState.StQuerying: Agency.Server,
        LocalStateQueryState.StDone: Agency.Nobody,
    }

    _VALID_MESSAGES = {
        LocalStateQueryState.StIdle: _IDLE_MESSAGES,
        LocalStateQueryState.StAcquiring: _ACQUIRING_MESSAGES,
        LocalStateQueryState.StAcquired: _ACQUIRED_MESSAGES,
        LocalStateQueryState.StQuerying: _QUERYING_MESSAGES,
        LocalStateQueryState.StDone: _DONE_MESSAGES,
    }

    def initial_state(self) -> LocalStateQueryState:
        return LocalStateQueryState.StIdle

    def agency(self, state: LocalStateQueryState) -> Agency:
        try:
            return self._AGENCY_MAP[state]
        except KeyError:
            raise ProtocolError(f"Unknown local state-query state: {state!r}")

    def valid_messages(
        self, state: LocalStateQueryState
    ) -> frozenset[type[Message[LocalStateQueryState]]]:
        try:
            return self._VALID_MESSAGES[state]
        except KeyError:
            raise ProtocolError(f"Unknown local state-query state: {state!r}")


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class LocalStateQueryCodec:
    """CBOR codec for local state-query miniprotocol messages.

    Wraps the encode/decode functions from local_statequery.py, translating
    between typed Message wrappers (LsqMsg*) and raw CBOR bytes.

    Implements the Codec protocol (structural typing).
    """

    def encode(self, message: Message[LocalStateQueryState]) -> bytes:
        """Encode a typed local state-query message to CBOR bytes."""
        if isinstance(message, LsqMsgAcquire):
            return encode_acquire(message.point)
        elif isinstance(message, LsqMsgFailure):
            return encode_failure(message.reason)
        elif isinstance(message, LsqMsgAcquired):
            return encode_acquired()
        elif isinstance(message, LsqMsgQuery):
            return encode_query(message.query)
        elif isinstance(message, LsqMsgResult):
            return encode_result(message.result)
        elif isinstance(message, LsqMsgRelease):
            return encode_release()
        elif isinstance(message, LsqMsgReAcquire):
            return encode_reacquire(message.point)
        elif isinstance(message, LsqMsgDone):
            return encode_done()
        else:
            raise CodecError(
                f"Unknown local state-query message type: "
                f"{type(message).__name__}"
            )

    def decode(self, data: bytes) -> Message[LocalStateQueryState]:
        """Decode CBOR bytes into a typed local state-query message.

        Tries all message types via the generic decode_message function.
        """
        try:
            msg = decode_message(data)
        except ValueError as exc:
            raise CodecError(str(exc)) from exc

        if isinstance(msg, MsgAcquire):
            return LsqMsgAcquire(point=msg.point)
        elif isinstance(msg, MsgFailure):
            return LsqMsgFailure(reason=msg.reason)
        elif isinstance(msg, MsgAcquired):
            return LsqMsgAcquired()
        elif isinstance(msg, MsgQuery):
            return LsqMsgQuery(query=msg.query)
        elif isinstance(msg, MsgResult):
            return LsqMsgResult(result=msg.result)
        elif isinstance(msg, MsgRelease):
            return LsqMsgRelease()
        elif isinstance(msg, MsgReAcquire):
            return LsqMsgReAcquire(point=msg.point)
        elif isinstance(msg, MsgDone):
            return LsqMsgDone()
        else:
            raise CodecError(
                f"Failed to decode local state-query message "
                f"({len(data)} bytes)"
            )


# ---------------------------------------------------------------------------
# High-level server (Responder side)
# ---------------------------------------------------------------------------


class LocalStateQueryServer:
    """High-level local state-query server (Responder).

    The server acquires a ledger state at a requested chain point, then
    handles queries against that immutable snapshot. Multiple queries can
    be run against the same acquired state.

    Parameters
    ----------
    runner : ProtocolRunner[LocalStateQueryState]
        A protocol runner already set up with LocalStateQueryProtocol,
        codec, and a connected mux channel.
    ledgerdb : LedgerDB
        The ledger database for UTxO queries.
    chain_tip : Point | None
        Current chain tip for epoch info.
    epoch_no : int
        Current epoch number.
    slot_in_epoch : int
        Current slot within the epoch.
    epoch_length : int
        Number of slots per epoch.
    protocol_params : dict[str, Any]
        Current protocol parameters.
    stake_distribution : dict[bytes, Fraction] | None
        Per-pool relative stake, or None if not available.
    stake_rewards : dict[bytes, int] | None
        Stake credential -> accumulated rewards (lovelace).
    stake_delegations : dict[bytes, bytes] | None
        Stake credential -> pool key hash.
    genesis_config : dict[str, Any] | None
        Genesis configuration data.
    governance_state : dict[str, Any] | None
        Conway governance state, or None if not available.

    Haskell reference:
        Ouroboros.Network.Protocol.LocalStateQuery.Server
        LocalStateQueryServer definition with handlers for acquire + queries.
    """

    __slots__ = (
        "_runner",
        "_ledgerdb",
        "_chain_tip",
        "_epoch_no",
        "_slot_in_epoch",
        "_epoch_length",
        "_protocol_params",
        "_stake_distribution",
        "_stake_rewards",
        "_stake_delegations",
        "_genesis_config",
        "_governance_state",
        "_acquired_ledger",
    )

    def __init__(
        self,
        runner: ProtocolRunner[LocalStateQueryState],
        ledgerdb: Any,
        chain_tip: Point | None = None,
        epoch_no: int = 0,
        slot_in_epoch: int = 0,
        epoch_length: int = 432000,
        protocol_params: dict[str, Any] | None = None,
        stake_distribution: dict[bytes, Fraction] | None = None,
        stake_rewards: dict[bytes, int] | None = None,
        stake_delegations: dict[bytes, bytes] | None = None,
        genesis_config: dict[str, Any] | None = None,
        governance_state: dict[str, Any] | None = None,
    ) -> None:
        self._runner = runner
        self._ledgerdb = ledgerdb
        self._chain_tip = chain_tip
        self._epoch_no = epoch_no
        self._slot_in_epoch = slot_in_epoch
        self._epoch_length = epoch_length
        self._protocol_params = protocol_params or {}
        self._stake_distribution = stake_distribution or {}
        self._stake_rewards = stake_rewards or {}
        self._stake_delegations = stake_delegations or {}
        self._genesis_config = genesis_config or {}
        self._governance_state = governance_state or {}
        self._acquired_ledger: Any = None

    @property
    def state(self) -> LocalStateQueryState:
        """Current protocol state."""
        return self._runner.state

    @property
    def is_done(self) -> bool:
        """Whether the protocol has terminated."""
        return self._runner.is_done

    async def run(self) -> None:
        """Run the server protocol loop.

        Handles the full lifecycle: wait for MsgAcquire, respond with
        MsgAcquired/MsgFailure, handle queries, and terminate on MsgDone.
        """
        while not self.is_done:
            state = self._runner.state

            if state == LocalStateQueryState.StIdle:
                # Wait for client to send MsgAcquire or MsgDone
                msg = await self._runner.recv_message()

                if isinstance(msg, LsqMsgAcquire):
                    await self._handle_acquire(msg.point)
                elif isinstance(msg, LsqMsgDone):
                    logger.debug("Local state-query: client sent MsgDone")
                    return
                else:
                    raise ProtocolError(
                        f"Unexpected message in StIdle: "
                        f"{type(msg).__name__}"
                    )

            elif state == LocalStateQueryState.StAcquired:
                # Wait for client query, re-acquire, or release
                msg = await self._runner.recv_message()

                if isinstance(msg, LsqMsgQuery):
                    await self._handle_query(msg.query)
                elif isinstance(msg, LsqMsgReAcquire):
                    await self._handle_acquire(msg.point)
                elif isinstance(msg, LsqMsgRelease):
                    self._acquired_ledger = None
                    logger.debug("Local state-query: released acquired state")
                else:
                    raise ProtocolError(
                        f"Unexpected message in StAcquired: "
                        f"{type(msg).__name__}"
                    )

            else:
                # StAcquiring and StQuerying are server-agency states
                # — we should never be waiting to recv in these states.
                # StDone is terminal.
                raise ProtocolError(
                    f"Server should not recv in state: {state!r}"
                )

    async def _handle_acquire(self, point: Point | None) -> None:
        """Handle MsgAcquire or MsgReAcquire.

        Tries to find the ledger state at the requested point. If the
        point is on the chain and within rollback range, sends MsgAcquired.
        Otherwise sends MsgFailure.

        For now, we only support acquiring the current tip (point=None
        or matching current tip). Historical point lookup will require
        the LedgerDB's get_past_ledger method once ChainDB is integrated.
        """
        if point is None:
            # Origin or current — acquire current ledger state
            self._acquired_ledger = self._ledgerdb
            await self._runner.send_message(LsqMsgAcquired())
            logger.debug("Local state-query: acquired at origin/current")
            return

        # Check if the point matches our chain tip
        if (self._chain_tip is not None
                and point.slot == self._chain_tip.slot
                and point.block_hash == self._chain_tip.block_hash):
            self._acquired_ledger = self._ledgerdb
            await self._runner.send_message(LsqMsgAcquired())
            logger.debug(
                "Local state-query: acquired at tip slot=%d", point.slot
            )
            return

        # Point not found — send failure
        await self._runner.send_message(
            LsqMsgFailure(AcquireFailureReason.AcquireFailurePointNotOnChain)
        )
        logger.debug(
            "Local state-query: acquisition failed for slot=%d", point.slot
        )

    async def _handle_query(self, query: Query) -> None:
        """Dispatch a query to the appropriate handler and send the result."""
        qt = query.query_type
        result: Any

        if qt == QueryType.LedgerTip:
            result = self._query_ledger_tip()
        elif qt == QueryType.UTxOByAddress:
            result = self._query_utxo_by_address(query.params)
        elif qt == QueryType.UTxOByTxIn:
            result = self._query_utxo_by_txin(query.params)
        elif qt == QueryType.UTxOWhole:
            result = self._query_utxo_whole()
        elif qt == QueryType.StakeDistribution:
            result = self._query_stake_distribution()
        elif qt == QueryType.ProtocolParameters:
            result = self._query_protocol_params()
        elif qt == QueryType.EpochInfo:
            result = self._query_epoch_info()
        elif qt == QueryType.GenesisConfig:
            result = self._query_genesis_config()
        elif qt == QueryType.StakeAddresses:
            result = self._query_stake_addresses(query.params)
        elif qt == QueryType.GovernanceState:
            result = self._query_governance_state()
        else:
            logger.warning(
                "Local state-query: unsupported query type %s", qt
            )
            result = None

        await self._runner.send_message(LsqMsgResult(result))
        logger.debug("Local state-query: sent result for %s", qt.value)

    # -- Query handlers -------------------------------------------------------

    def _query_ledger_tip(self) -> Any:
        """Return the current ledger tip as [slot, hash].

        Returns the chain tip point as a CBOR-serializable list.
        """
        if self._chain_tip is None:
            return []  # Origin
        return self._chain_tip.to_cbor_list()

    def _query_utxo_by_address(self, addresses: Any) -> dict:
        """Query UTxOs filtered by address.

        Args:
            addresses: List of address bytes/strings to filter by.

        Returns:
            Dict mapping TxIn keys to UTxO values for matching addresses.
        """
        if not addresses or self._acquired_ledger is None:
            return {}

        if not isinstance(addresses, list):
            addresses = [addresses]

        # Convert addresses to a set for O(1) lookup
        addr_set = set()
        for addr in addresses:
            if isinstance(addr, memoryview):
                addr = bytes(addr)
            if isinstance(addr, bytes):
                addr_set.add(addr.hex())
                addr_set.add(addr)  # Also keep raw bytes
            else:
                addr_set.add(str(addr))

        result = {}
        ledger = self._acquired_ledger
        for key in list(ledger._index.keys()):
            utxo = ledger.get_utxo(key)
            if utxo is not None:
                addr = utxo.get("address", "")
                if addr in addr_set:
                    result[key] = utxo
        return result

    def _query_utxo_by_txin(self, tx_ins: Any) -> dict:
        """Query UTxOs filtered by specific TxIn keys.

        Args:
            tx_ins: List of TxIn key bytes to look up.

        Returns:
            Dict mapping TxIn keys to UTxO values for matching inputs.
        """
        if not tx_ins or self._acquired_ledger is None:
            return {}

        if not isinstance(tx_ins, list):
            tx_ins = [tx_ins]

        result = {}
        ledger = self._acquired_ledger
        for txin in tx_ins:
            if isinstance(txin, memoryview):
                txin = bytes(txin)
            utxo = ledger.get_utxo(txin)
            if utxo is not None:
                result[txin] = utxo
        return result

    def _query_utxo_whole(self) -> dict:
        """Return the entire UTxO set.

        WARNING: This can be very large on mainnet. Use with caution.
        """
        if self._acquired_ledger is None:
            return {}

        result = {}
        ledger = self._acquired_ledger
        for key in list(ledger._index.keys()):
            utxo = ledger.get_utxo(key)
            if utxo is not None:
                result[key] = utxo
        return result

    def _query_stake_distribution(self) -> dict:
        """Return per-pool relative stake distribution.

        Returns a dict mapping pool key hash hex strings to their
        relative stake as [numerator, denominator] pairs.
        """
        result = {}
        for pool_id, fraction in self._stake_distribution.items():
            if isinstance(fraction, Fraction):
                result[pool_id.hex() if isinstance(pool_id, bytes) else pool_id] = [
                    fraction.numerator, fraction.denominator
                ]
            else:
                result[pool_id.hex() if isinstance(pool_id, bytes) else pool_id] = fraction
        return result

    def _query_protocol_params(self) -> dict[str, Any]:
        """Return current protocol parameters."""
        return dict(self._protocol_params)

    def _query_epoch_info(self) -> list:
        """Return (epoch_no, slot_in_epoch, slots_remaining).

        Returns as a CBOR-serializable list of 3 integers.
        """
        slots_remaining = max(0, self._epoch_length - self._slot_in_epoch)
        return [self._epoch_no, self._slot_in_epoch, slots_remaining]

    def _query_genesis_config(self) -> dict[str, Any]:
        """Return genesis configuration."""
        return dict(self._genesis_config)

    def _query_stake_addresses(self, credentials: Any) -> list:
        """Query rewards and delegations for stake addresses.

        Args:
            credentials: List of stake credential bytes.

        Returns:
            [rewards_map, delegations_map] where:
            - rewards_map: {credential -> lovelace}
            - delegations_map: {credential -> pool_key_hash}
        """
        if not credentials:
            return [{}, {}]

        if not isinstance(credentials, list):
            credentials = [credentials]

        rewards_map: dict = {}
        delegations_map: dict = {}

        for cred in credentials:
            if isinstance(cred, memoryview):
                cred = bytes(cred)

            reward = self._stake_rewards.get(cred, 0)
            if reward > 0:
                rewards_map[cred] = reward

            delegation = self._stake_delegations.get(cred)
            if delegation is not None:
                delegations_map[cred] = delegation

        return [rewards_map, delegations_map]

    def _query_governance_state(self) -> dict[str, Any]:
        """Return Conway governance state."""
        return dict(self._governance_state)


# ---------------------------------------------------------------------------
# High-level server loop entry point
# ---------------------------------------------------------------------------


async def run_local_state_query_server(
    channel: object,
    ledgerdb: Any,
    **kwargs: Any,
) -> None:
    """Run a local state-query server on the given channel.

    Creates a ProtocolRunner, wraps it in a LocalStateQueryServer, and
    runs the server loop.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for the local state-query miniprotocol.
    ledgerdb : LedgerDB
        The ledger database for UTxO queries.
    **kwargs
        Additional keyword arguments passed to LocalStateQueryServer
        (chain_tip, epoch_no, protocol_params, etc.).
    """
    protocol = LocalStateQueryProtocol()
    codec = LocalStateQueryCodec()
    runner = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    server = LocalStateQueryServer(runner, ledgerdb, **kwargs)
    await server.run()
