"""Peer connection management with automatic reconnect.

Manages outbound N2N peer connections: TCP connect, multiplexer setup,
handshake, miniprotocol launch, and reconnect with exponential backoff.

Haskell references:
    - Ouroboros.Network.Diffusion.P2P -- P2P governor for outbound connections
    - Ouroboros.Network.PeerSelection.Governor.ActivePeers -- backoff logic
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from vibe.cardano.network.blockfetch import BLOCK_FETCH_N2N_ID
from vibe.cardano.network.chainsync import CHAIN_SYNC_N2N_ID
from vibe.cardano.network.handshake import HANDSHAKE_PROTOCOL_ID
from vibe.cardano.network.keepalive import KEEP_ALIVE_PROTOCOL_ID
from vibe.cardano.network.txsubmission import TX_SUBMISSION_N2N_ID
from vibe.core.multiplexer import (
    Bearer,
    BearerClosedError,
    MiniProtocolChannel,
    Multiplexer,
    MuxClosedError,
)

from .config import NodeConfig, PeerAddress
from .inbound_server import N2N_PROTOCOL_IDS

__all__ = ["PeerManager"]

logger = logging.getLogger(__name__)


def _get_new_chain_blocks(
    chain_db: Any,
    intersection_hash: bytes,
    tip_hash: bytes,
) -> list[tuple[int, bytes, bytes, bytes | None]]:
    """Walk backward from tip to intersection through VolatileDB.

    Returns list of (slot, block_hash, prev_hash, vrf_output) oldest-first,
    for blocks AFTER the intersection (not including intersection itself).
    Used to re-apply nonce state after a fork switch.
    """
    from vibe.cardano.serialization.block import decode_block_header

    blocks: list[tuple[int, bytes, bytes, bytes | None]] = []
    h = tip_hash
    while h and h != intersection_hash and h in chain_db.volatile_db._block_info:
        info = chain_db.volatile_db._block_info[h]
        # Try to get VRF output from the block
        vrf_out: bytes | None = None
        block_cbor = chain_db.volatile_db._blocks.get(h)
        if block_cbor:
            try:
                hdr = decode_block_header(block_cbor)
                vrf_out = hdr.vrf_output
            except Exception:
                pass
        blocks.append((info.slot, info.block_hash, info.predecessor_hash, vrf_out))
        h = info.predecessor_hash
    blocks.reverse()  # oldest first
    return blocks


@dataclass
class _PeerConnection:
    """Internal tracking for a single peer connection."""

    address: PeerAddress
    bearer: Bearer | None = None
    mux: Multiplexer | None = None
    mux_task: asyncio.Task[None] | None = None
    task: asyncio.Task[None] | None = None
    stop_event: asyncio.Event | None = None
    reconnect_delay: float = 1.0
    reconnect_attempt: int = 0
    connected: bool = False


class PeerManager:
    """Manages outbound N2N peer connections with automatic reconnect.

    For each configured peer, the PeerManager:
    1. Opens a TCP connection
    2. Wraps it in a Bearer + Multiplexer
    3. Registers the N2N miniprotocol bundle
    4. Runs the multiplexer
    5. On disconnect, waits with exponential backoff and reconnects

    Haskell ref:
        ``Ouroboros.Network.Diffusion.P2P`` -- the P2P governor manages
        outbound connections with warm/hot/cold state transitions and
        backoff on failure.  Our implementation is simpler: connect,
        run mux, reconnect on failure.

    Args:
        config: Node configuration (for network_magic and peer list).
        chain_db: ChainDB instance for storing received blocks.
    """

    __slots__ = (
        "_config",
        "_chain_db",
        "_node_kernel",
        "_peers",
        "_stopped",
        "_tasks",
        "_known_points",
        "_block_received_event",
    )

    def __init__(
        self,
        config: NodeConfig,
        chain_db: Any = None,
        node_kernel: Any = None,
        block_received_event: Any = None,
    ) -> None:
        self._config = config
        self._chain_db = chain_db
        self._node_kernel = node_kernel
        self._peers: dict[str, _PeerConnection] = {}
        self._stopped = False
        self._tasks: list[asyncio.Task[None]] = []
        self._known_points: list[Any] = []
        # threading.Event — set when a new block is processed,
        # wakes the forge thread to check leadership immediately.
        self._block_received_event = block_received_event

    @property
    def known_points(self) -> list[Any]:
        """Known chain points for chain-sync intersection (from snapshot or chain tip)."""
        return self._known_points

    def set_known_points(self, points: list[Any]) -> None:
        """Set known points for chain-sync to start from (instead of Origin)."""
        self._known_points = points

    @property
    def connected_count(self) -> int:
        """Number of currently connected peers."""
        return sum(1 for p in self._peers.values() if p.connected)

    @property
    def peer_ids(self) -> list[str]:
        """List of all tracked peer IDs (host:port strings)."""
        return list(self._peers.keys())

    def add_peer(self, address: PeerAddress) -> None:
        """Register a peer for connection management.

        Args:
            address: The peer's network address.
        """
        peer_id = str(address)
        if peer_id not in self._peers:
            self._peers[peer_id] = _PeerConnection(address=address)

    async def start(self) -> None:
        """Start connection tasks for all registered peers."""
        for peer_id, peer in self._peers.items():
            task = asyncio.create_task(self._peer_loop(peer), name=f"peer-{peer_id}")
            self._tasks.append(task)
            peer.task = task

    async def stop(self) -> None:
        """Disconnect all peers and cancel reconnect loops."""
        self._stopped = True
        for peer in self._peers.values():
            await self._disconnect_peer(peer)
            if peer.task is not None and not peer.task.done():
                peer.task.cancel()
                try:
                    await peer.task
                except asyncio.CancelledError, Exception:
                    pass

    async def _peer_loop(self, peer: _PeerConnection) -> None:
        """Connection loop for a single peer -- connect, run, reconnect.

        Implements exponential backoff on connection failures:
        1s -> 2s -> 4s -> ... -> 60s (capped).

        On successful reconnection the backoff delay and attempt counter
        reset to their initial values so transient errors don't
        permanently degrade reconnect speed.

        Haskell ref:
            Ouroboros.Network.PeerSelection.Governor.ActivePeers -- the
            governor uses exponential backoff with a cap for peer
            reconnection delays after connection failures.
        """
        while not self._stopped:
            try:
                await self._connect_peer(peer)
                # Reset backoff on successful connection.
                peer.reconnect_delay = 1.0
                peer.reconnect_attempt = 0

                # Mux is already running (started in _connect_peer after
                # handshake). Await the mux task until disconnect.
                if peer.mux_task is not None:
                    await peer.mux_task

            except (MuxClosedError, BearerClosedError) as exc:
                # Multiplexer or bearer closed -- normal disconnect path.
                # Log at INFO rather than WARNING since this is expected
                # during peer disconnects and node shutdowns.
                logger.info(
                    "Peer %s: connection closed: %s",
                    peer.address,
                    exc,
                )
            except (ConnectionError, OSError) as exc:
                logger.warning(
                    "Peer %s: connection failed: %s",
                    peer.address,
                    exc,
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error(
                    "Peer %s: unexpected error: %s",
                    peer.address,
                    exc,
                    exc_info=True,
                )
            finally:
                peer.connected = False
                await self._disconnect_peer(peer)

            if self._stopped:
                return

            # Backoff before reconnect.
            peer.reconnect_attempt += 1
            logger.info(
                "Reconnecting to peer %s in %.1fs (attempt %d)",
                peer.address,
                peer.reconnect_delay,
                peer.reconnect_attempt,
            )
            await asyncio.sleep(peer.reconnect_delay)
            peer.reconnect_delay = min(peer.reconnect_delay * 2, 60.0)

    async def _connect_peer(self, peer: _PeerConnection) -> None:
        """Open TCP connection, set up multiplexer, and run N2N handshake.

        The handshake must complete before any other miniprotocol can run.
        We start the mux sender/receiver in the background (they handle
        wire framing), run the handshake on channel 0, then return — the
        caller continues with mux.run() which blocks until disconnect.

        Haskell ref:
            Ouroboros.Network.Protocol.Handshake.Client — client peer
            The Haskell node runs the handshake as the first action on a
            new connection before activating other miniprotocols.
        """
        from vibe.cardano.network.handshake_protocol import (
            HandshakeError,
            run_handshake_client,
        )

        logger.info(
            "Peer %s connecting",
            peer.address,
            extra={"event": "peer.connect", "peer": str(peer.address)},
        )
        reader, writer = await asyncio.open_connection(peer.address.host, peer.address.port)
        bearer = Bearer(reader, writer)
        mux = Multiplexer(bearer, is_initiator=True)

        # Register N2N miniprotocol channels.
        channels: dict[int, MiniProtocolChannel] = {}
        for proto_id in N2N_PROTOCOL_IDS:
            channels[proto_id] = mux.add_protocol(proto_id)

        peer.bearer = bearer
        peer.mux = mux

        # The mux must be running for channels to work (sender/receiver
        # loops handle the wire framing). Start it, run the handshake,
        # then let the caller's mux.run() take over.
        #
        # We use a task for the mux and run the handshake concurrently.
        # After handshake completes, we stop the mux task — the caller
        # will call mux.run() again which restarts the loops.
        #
        # Actually, mux.run() can only be called once. So instead, we
        # need to run the handshake as part of the mux lifetime. The
        # approach: start the mux in a background task, do the handshake,
        # then return. The peer_loop will NOT call mux.run() again —
        # instead, we await the background mux task.

        # Start mux sender/receiver loops in background.
        mux_task = asyncio.create_task(mux.run(), name=f"mux-{peer.address}")

        try:
            # Run N2N handshake on channel 0.
            hs_channel = channels[HANDSHAKE_PROTOCOL_ID]
            result = await run_handshake_client(hs_channel, self._config.network_magic)
            peer.connected = True
            logger.info(
                "Peer %s connected (v%d, magic %d)",
                peer.address,
                result.version_number,
                result.version_data.network_magic,
                extra={
                    "event": "peer.connected",
                    "peer": str(peer.address),
                    "version": result.version_number,
                    "magic": result.version_data.network_magic,
                },
            )
        except (HandshakeError, Exception) as exc:
            # Handshake failed — tear down the mux and propagate.
            await mux.close()
            try:
                await mux_task
            except Exception:
                pass
            raise ConnectionError(f"Handshake with {peer.address} failed: {exc}") from exc

        # --- Launch miniprotocol runners on their channels ---
        # Each runs as a background task for the lifetime of the connection.
        # The mux routes bytes between the bearer and these channel tasks.

        from vibe.cardano.network.chainsync_protocol import run_chain_sync
        from vibe.cardano.network.keepalive_protocol import run_keep_alive_client
        from vibe.cardano.network.txsubmission_protocol import run_tx_submission_client

        stop_event = asyncio.Event()
        peer.stop_event = stop_event

        async def _safe_run(coro, name: str) -> None:
            """Run a miniprotocol coroutine, suppressing MuxClosedError on shutdown."""
            try:
                await coro
            except MuxClosedError:
                logger.debug("Peer %s: %s channel closed", peer.address, name)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Peer %s: %s error: %s", peer.address, name, exc)

        # --- Sync pipeline: chain-sync -> block-fetch -> store ---
        # Chain-sync receives headers, extracts Point(slot, hash),
        # queues them for block-fetch. Block-fetch downloads full
        # block bodies and stores them in ChainDB.

        import hashlib

        import cbor2pure as cbor2

        from vibe.cardano.network.chainsync import Point

        # Queue of points discovered by chain-sync, consumed by block-fetch.
        fetch_queue: asyncio.Queue[Point] = asyncio.Queue(maxsize=1000)
        chain_db = self._chain_db
        node_kernel = self._node_kernel
        _headers_received = 0

        async def _on_roll_forward(header: object, tip: object) -> None:
            nonlocal _headers_received
            _headers_received += 1

            # header = [era_tag, CBORTag(24, header_cbor)]
            # Use the serialization layer to decode header fields.
            from vibe.cardano.serialization.block import (
                Era,
                decode_block_header_raw,
            )
            from vibe.cardano.serialization.block import (
                block_hash as compute_block_hash,
            )

            try:
                if isinstance(header, (list, tuple)) and len(header) >= 2:
                    era_tag = header[0]
                    wrapped = header[1]  # CBORTag(24, inner_bytes)
                    header_bytes = wrapped.value if hasattr(wrapped, "value") else wrapped

                    try:
                        era = Era(era_tag)
                        hdr = decode_block_header_raw(header_bytes, era)
                        slot = hdr.slot
                        blk_hash = hdr.hash
                    except (NotImplementedError, ValueError):
                        # Byron or unrecognised era -- fall back to inline
                        inner = cbor2.loads(header_bytes)
                        hdr_body = inner[0]
                        slot = hdr_body[1]
                        blk_hash = compute_block_hash(header_bytes)

                    point = Point(slot=slot, hash=blk_hash)

                    # NOTE: We do NOT update the nonce here from the header.
                    # Haskell's reupdateChainDepState is tentative — committed
                    # only after chain selection adopts the block. If we update
                    # nonce from a header whose block is later rejected (stale,
                    # fork switch), the nonce state is corrupted. The nonce is
                    # updated in _on_block AFTER ChainDB confirms adoption.
                    # STM ensures the forge loop sees consistent nonce+tip.

                    # Queue for block-fetch (still need body for storage)
                    try:
                        fetch_queue.put_nowait(point)
                    except asyncio.QueueFull:
                        pass

                    if _headers_received % 1000 == 1 or _headers_received <= 5:
                        # Compute sync percentage from server tip
                        tip_block = getattr(tip, "block_number", 0) or 0
                        sync_pct = (
                            (_headers_received / tip_block * 100)
                            if tip_block > 0
                            else 0.0
                        )
                        logger.info(
                            "Chain-sync header #%d at slot %d (%.2f%% synced) from %s",
                            _headers_received,
                            slot,
                            sync_pct,
                            peer.address,
                            extra={
                                "event": "chainsync.header",
                                "peer": str(peer.address),
                                "header_num": _headers_received,
                                "slot": slot,
                                "hash": blk_hash.hex()[:16],
                                "sync_pct": round(sync_pct, 2),
                                "tip_block": tip_block,
                            },
                        )
                else:
                    if _headers_received % 100 == 1:
                        logger.debug(
                            "Peer %s: header #%d (unparsed, tip=%s)",
                            peer.address,
                            _headers_received,
                            tip,
                        )
            except Exception as exc:
                logger.warning("Peer %s: header parse error: %s", peer.address, exc)

        async def _on_roll_backward(point: object, tip: object) -> None:
            logger.info(
                "Chain rollback to %s (tip=%s) from %s",
                point,
                tip,
                peer.address,
                extra={
                    "event": "chainsync.rollback",
                    "peer": str(peer.address),
                    "point": str(point),
                    "tip": str(tip),
                },
            )
            # TODO: ChainDB rollback to point

        asyncio.create_task(
            _safe_run(
                run_chain_sync(
                    channels[CHAIN_SYNC_N2N_ID],
                    known_points=self._known_points,  # Resume from ChainDB tip
                    on_roll_forward=_on_roll_forward,
                    on_roll_backward=_on_roll_backward,
                    stop_event=stop_event,
                ),
                "chain-sync",
            ),
            name=f"chainsync-{peer.address}",
        )

        # Block-fetch worker: batches points from the queue into ranges,
        # fetches full block bodies, and stores them in ChainDB.
        async def _block_fetch_worker() -> None:
            from vibe.cardano.network.blockfetch_protocol import run_block_fetch_continuous

            bf_channel = channels[BLOCK_FETCH_N2N_ID]
            _blocks_stored = 0

            # Use a queue for block-fetch ranges. The chain-sync
            # _on_roll_forward fills fetch_queue with Points; we
            # convert to (from, to) range tuples for block-fetch.
            range_queue: asyncio.Queue[tuple] = asyncio.Queue()

            # Background task: drain fetch_queue Points into ranges
            async def _range_builder() -> None:
                while not stop_event.is_set():
                    batch: list[Point] = []
                    try:
                        point = await asyncio.wait_for(fetch_queue.get(), timeout=1.0)
                        batch.append(point)
                        while len(batch) < 100:
                            try:
                                batch.append(fetch_queue.get_nowait())
                            except asyncio.QueueEmpty:
                                break
                    except TimeoutError:
                        continue
                    if batch:
                        await range_queue.put((batch[0], batch[-1]))

            builder_task = asyncio.create_task(_range_builder())

            async def _on_block(block_cbor: bytes) -> None:
                nonlocal _blocks_stored
                from vibe.cardano.consensus.hfc import validate_block
                from vibe.cardano.serialization.block import (
                    Era,
                    decode_block_header_from_array,
                )
                from vibe.cardano.serialization.transaction import (
                    decode_block_body_from_array,
                )

                try:
                    # --- Parse block from block-fetch wire format ---
                    # Block-fetch delivers CBORTag(24, raw_bytes) or re-encoded
                    # CBOR. We preserve original bytes to avoid re-encoding
                    # issues with IndefiniteFrozenList types from cbor2.
                    #
                    # Haskell ref: MemoBytes / Annotator pattern — always
                    # preserve original wire bytes, never re-serialize.
                    raw_wire = block_cbor
                    decoded = cbor2.loads(block_cbor)

                    # Unwrap tag-24 if present
                    if hasattr(decoded, "tag") and decoded.tag == 24:
                        inner = decoded.value
                        if isinstance(inner, bytes):
                            raw_wire = inner
                            decoded = cbor2.loads(inner)
                        else:
                            decoded = inner

                    # Block-fetch format: [era_int, block_body]
                    if (
                        isinstance(decoded, list)
                        and len(decoded) >= 2
                        and isinstance(decoded[0], int)
                    ):
                        era_tag = decoded[0]
                        block_body = decoded[1]
                    elif hasattr(decoded, "tag"):
                        era_tag = decoded.tag
                        block_body = decoded.value
                    else:
                        raise ValueError(f"Unexpected block format: {type(decoded)}")

                    # Store the original wire bytes — do NOT re-encode.
                    # Re-encoding fails on IndefiniteFrozenList types and
                    # changes CBOR encoding, breaking hash computation.
                    # Haskell ref: MemoBytes/Annotator — never re-serialize.
                    raw_block = raw_wire

                    # decode_block_header now handles both CBORTag and [era, body]
                    # list formats, so raw_wire works directly.

                    # --- Decode once: extract header + body from pre-decoded block_body ---
                    # Avoids re-parsing the same CBOR 3 times (was: decode in _on_block,
                    # then decode_block_header re-parses, then decode_block_body re-parses).
                    era = Era(era_tag)
                    try:
                        hdr = decode_block_header_from_array(block_body, era)
                        slot = hdr.slot
                        block_number = hdr.block_number
                        prev_hash = hdr.prev_hash or b"\x00" * 32
                        block_hash = hdr.hash
                        hdr_cbor = hdr.header_cbor
                    except NotImplementedError:
                        # Byron blocks -- fall back to inline extraction
                        hdr_arr = block_body[0]
                        hdr_body_arr = hdr_arr[0]
                        block_number = hdr_body_arr[0]
                        slot = hdr_body_arr[1]
                        prev_hash = hdr_body_arr[2] or b"\x00" * 32
                        from vibe.cardano.serialization.transaction import (
                            _normalize_cbor_types,
                        )

                        hdr_cbor = cbor2.dumps(_normalize_cbor_types(hdr_arr))
                        block_hash = hashlib.blake2b(hdr_cbor, digest_size=32).digest()

                    # --- Decode body from pre-decoded array (no re-parse) ---
                    body = decode_block_body_from_array(block_body, era)
                    if body.transactions:
                        errors = validate_block(
                            era=era,
                            block=body.transactions,
                            ledger_state=(chain_db.ledger_db if chain_db else None),
                            protocol_params=self._config.protocol_params,
                            current_slot=slot,
                        )
                        if errors:
                            if self._config.permissive_validation:
                                logger.warning(
                                    "Peer %s: block #%d slot=%d has %d "
                                    "validation errors (permissive): %s",
                                    peer.address,
                                    block_number,
                                    slot,
                                    len(errors),
                                    errors[:3],
                                )
                            else:
                                logger.warning(
                                    "Peer %s: REJECTING block #%d slot=%d: %d errors: %s",
                                    peer.address,
                                    block_number,
                                    slot,
                                    len(errors),
                                    errors[:3],
                                )
                                return  # Don't store invalid blocks

                    # --- Apply ledger state (UTxO mutations) ---
                    if chain_db is not None and chain_db.ledger_db is not None:
                        consumed: list[bytes] = []
                        created: list[tuple[bytes, dict]] = []
                        for tx in body.transactions:
                            if not tx.valid:
                                continue
                            tb = tx.body
                            # Extract consumed inputs
                            inputs = getattr(tb, "inputs", None)
                            if inputs:
                                for inp in inputs:
                                    tx_id = getattr(inp, "transaction_id", None)
                                    tx_idx = getattr(inp, "index", None)
                                    if tx_id is not None and tx_idx is not None:
                                        payload = getattr(tx_id, "payload", tx_id)
                                        if isinstance(payload, bytes) and len(payload) == 32:
                                            key = payload + tx_idx.to_bytes(2, "big")
                                            consumed.append(key)
                            # Extract created outputs
                            outputs = getattr(tb, "outputs", None)
                            if outputs:
                                for idx, out in enumerate(outputs):
                                    key = tx.tx_hash + idx.to_bytes(2, "big")
                                    addr = str(getattr(out, "address", ""))
                                    amount = getattr(out, "amount", 0)
                                    if isinstance(amount, int):
                                        value = amount
                                    else:
                                        value = getattr(amount, "coin", 0) or 0
                                    datum_hash = getattr(out, "datum_hash", b"") or b""
                                    if hasattr(datum_hash, "payload"):
                                        datum_hash = datum_hash.payload
                                    created.append(
                                        (
                                            key,
                                            {
                                                "tx_hash": tx.tx_hash,
                                                "tx_index": idx,
                                                "address": addr,
                                                "value": int(value),
                                                "datum_hash": (
                                                    datum_hash
                                                    if isinstance(datum_hash, bytes)
                                                    else b""
                                                ),
                                            },
                                        )
                                    )
                        if consumed or created:
                            try:
                                chain_db.ledger_db.apply_block(
                                    consumed,
                                    created,
                                    block_slot=slot,
                                )
                            except Exception as exc:
                                logger.warning(
                                    "Peer %s: ledger apply error at slot %d: %s",
                                    peer.address,
                                    slot,
                                    exc,
                                )

                    # --- Store in ChainDB (includes chain selection + follower notification) ---
                    if chain_db is not None:
                        header_cbor_wrapped = [
                            max(0, era_tag - 1) if era_tag >= 2 else 0,
                            cbor2.CBORTag(24, hdr_cbor),
                        ]
                        hdr_vrf_out = getattr(hdr, "vrf_output", None)
                        result = await chain_db.add_block(
                            slot=slot,
                            block_hash=block_hash,
                            predecessor_hash=prev_hash,
                            block_number=block_number,
                            cbor_bytes=raw_block,
                            header_cbor=header_cbor_wrapped,
                            vrf_output=hdr_vrf_out,
                        )

                        if result.adopted and self._block_received_event is not None:
                            self._block_received_event.set()

                        # Praos chain-dependent state update
                        if result.adopted and node_kernel is not None:
                            vrf_out = hdr_vrf_out
                            if result.rollback_depth > 0 and result.intersection_hash is not None:
                                # Fork switch — rollback nonce and re-apply
                                # Walk new chain from intersection to tip via VolatileDB
                                new_blocks = _get_new_chain_blocks(
                                    chain_db,
                                    result.intersection_hash,
                                    block_hash,
                                )
                                node_kernel.on_fork_switch(
                                    result.intersection_hash,
                                    new_blocks,
                                )
                            else:
                                # Simple extension
                                node_kernel.on_block_adopted(
                                    slot,
                                    block_hash,
                                    prev_hash,
                                    vrf_out,
                                )

                    _blocks_stored += 1
                    tx_count = (
                        len(block_body[1])
                        if len(block_body) > 1 and isinstance(block_body[1], list)
                        else 0
                    )
                    if _blocks_stored % 100 == 1 or _blocks_stored <= 5:
                        logger.info(
                            "Block #%d stored at slot %d (%s, %d txs, %d bytes) from %s [%d total]",
                            block_number,
                            slot,
                            era.name,
                            tx_count,
                            len(raw_block),
                            peer.address,
                            _blocks_stored,
                            extra={
                                "event": "block.stored",
                                "block_number": block_number,
                                "slot": slot,
                                "era": era.name,
                                "tx_count": tx_count,
                                "size_bytes": len(raw_block),
                                "hash": block_hash.hex()[:16],
                                "peer": str(peer.address),
                                "total_stored": _blocks_stored,
                            },
                        )
                except Exception as exc:
                    logger.error(
                        "Peer %s: block process error: %s",
                        peer.address,
                        exc,
                        exc_info=True,
                    )
                    # In strict mode, halt on first error so we can debug.
                    # The node restarts and resumes from the last good block
                    # via initial_chain_selection.
                    import os

                    if os.environ.get("VIBE_STRICT_SYNC", "").lower() in (
                        "1",
                        "true",
                        "yes",
                    ):
                        raise

            try:
                await run_block_fetch_continuous(
                    bf_channel,
                    range_queue=range_queue,
                    on_block_received=_on_block,
                    stop_event=stop_event,
                )
            except Exception as exc:
                logger.warning("Peer %s: block-fetch error: %s", peer.address, exc)
            finally:
                builder_task.cancel()

        asyncio.create_task(
            _safe_run(_block_fetch_worker(), "block-fetch"),
            name=f"blockfetch-{peer.address}",
        )

        # Keep-Alive (protocol 8): periodic pings to keep connection alive.
        asyncio.create_task(
            _safe_run(
                run_keep_alive_client(
                    channels[KEEP_ALIVE_PROTOCOL_ID],
                    stop_event=stop_event,
                ),
                "keep-alive",
            ),
            name=f"keepalive-{peer.address}",
        )

        # Tx-Submission (protocol 4): respond to server's tx requests.
        # Server drives this protocol (pull-based). We provide empty
        # responses until the mempool is wired in.
        async def _on_request_tx_ids(
            blocking: bool, ack_count: int, req_count: int
        ) -> list[tuple[bytes, int]] | None:
            if blocking:
                # Block until we have txs -- for now, wait for stop.
                await stop_event.wait()
                return None
            return []

        async def _on_request_txs(
            txids: list[bytes],
        ) -> list[bytes]:
            return []

        asyncio.create_task(
            _safe_run(
                run_tx_submission_client(
                    channels[TX_SUBMISSION_N2N_ID],
                    on_request_tx_ids=_on_request_tx_ids,
                    on_request_txs=_on_request_txs,
                    stop_event=stop_event,
                ),
                "tx-submission",
            ),
            name=f"txsub-{peer.address}",
        )

        # Store the mux task -- peer_loop will await it instead of mux.run().
        peer.mux_task = mux_task

    async def _disconnect_peer(self, peer: _PeerConnection) -> None:
        """Tear down a peer's multiplexer and bearer."""
        logger.info(
            "Peer %s disconnected",
            peer.address,
            extra={"event": "peer.disconnect", "peer": str(peer.address)},
        )
        # Signal miniprotocol runners to stop.
        if peer.stop_event is not None:
            peer.stop_event.set()
            peer.stop_event = None
        if peer.mux is not None:
            try:
                await peer.mux.close()
            except Exception:
                pass
            peer.mux = None
        if peer.mux_task is not None and not peer.mux_task.done():
            peer.mux_task.cancel()
            try:
                await peer.mux_task
            except asyncio.CancelledError, Exception:
                pass
            peer.mux_task = None
        if peer.bearer is not None:
            try:
                await peer.bearer.close()
            except Exception:
                pass
            peer.bearer = None
        peer.connected = False
