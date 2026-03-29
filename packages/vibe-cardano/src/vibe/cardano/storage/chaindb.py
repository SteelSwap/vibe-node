"""ChainDB — coordinator for ImmutableDB, VolatileDB, and LedgerDB.

The ChainDB is the top-level storage component that receives blocks from
block-fetch or chain-sync and routes them to the appropriate sub-stores:

- **VolatileDB** — receives all new blocks (recent, may be on a fork)
- **ImmutableDB** — receives finalized blocks once the chain grows past k
- **LedgerDB** — updated after each block (UTxO set mutations)

ChainDB maintains an in-memory **chain fragment** (the last k headers of the
selected chain) used by chain-sync followers to serve headers to peers.
When chain selection switches to a fork, all followers are notified
atomically (before returning from add_block), ensuring no peer sees
orphaned blocks without a rollback first.

Haskell reference:
    Ouroboros.Consensus.Storage.ChainDB.API
    Ouroboros.Consensus.Storage.ChainDB.Impl
    Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel

Key invariants maintained:
    1. The immutable tip never rolls back.
    2. All blocks in the volatile DB have blockNo > immutable tip blockNo.
    3. The selected chain tip is always the block with the highest blockNo
       among chains reachable from the immutable tip.
    4. After advancing the immutable tip, blocks at or below the new
       immutable slot are garbage-collected from the volatile DB.
    5. Fork switches notify all followers before the chain fragment is
       visible to other coroutines (no await between notification and update).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .immutable import ImmutableDB
from .ledger import LedgerDB
from .ledger_seq import LedgerSeq
from .volatile import BlockInfo, VolatileDB

__all__ = [
    "BlockToAdd",
    "ChainDB",
    "ChainSelectionError",
    "ChainSelectionResult",
    "FragmentEntry",
]

logger = logging.getLogger(__name__)


class ChainSelectionError(Exception):
    """Raised when chain selection encounters an unrecoverable error."""


@dataclass(frozen=True, slots=True)
class _ChainTip:
    """Internal representation of the current chain tip."""

    slot: int
    block_hash: bytes
    block_number: int
    vrf_output: bytes = b""  # Raw 64-byte VRF output for tiebreaking


@dataclass(frozen=True, slots=True)
class FragmentEntry:
    """A block in the in-memory chain fragment.

    Stored in the chain fragment for chain-sync serving. Contains the
    header CBOR so followers can serve headers without re-parsing blocks.

    Haskell ref: entries in the AnchoredFragment stored in cdbChain.
    """

    slot: int
    block_hash: bytes
    block_number: int
    predecessor_hash: bytes
    header_cbor: Any  # Wrapped header: [era_tag, CBORTag(24, bytes)]


@dataclass(frozen=True)
class ChainSelectionResult:
    """Result of adding a block to ChainDB.

    Haskell ref: AddBlockResult + ChainDiff information.
    """

    adopted: bool
    """True if the block became part of the new selected chain tip."""

    new_tip: tuple[int, bytes, int] | None = None
    """(slot, hash, block_number) of the new tip, or None if empty."""

    rollback_depth: int = 0
    """Number of blocks rolled back (0 = simple extension)."""

    removed_hashes: set[bytes] = field(default_factory=set)
    """Block hashes that were orphaned by this fork switch."""

    intersection_hash: bytes | None = None
    """Hash of the fork point (common ancestor), or None if no rollback."""


@dataclass
class BlockToAdd:
    """Queue entry for the chain selection runner.

    Holds all parameters for add_block plus signaling fields for the
    caller to wait on the result.

    Haskell ref: BlockToAdd in ChainDB.Impl.Types
    """

    slot: int
    block_hash: bytes
    predecessor_hash: bytes
    block_number: int
    cbor_bytes: bytes
    header_cbor: Any = None
    vrf_output: bytes | None = None
    result: ChainSelectionResult | None = field(default=None, init=False)
    error: Exception | None = field(default=None, init=False)
    done: threading.Event = field(default_factory=threading.Event, init=False)


class ChainDB:
    """Coordinator for ImmutableDB, VolatileDB, and LedgerDB.

    Maintains an in-memory chain fragment (last k blocks of the selected
    chain), a follower registry for chain-sync serving, and coordinates
    chain selection with fork switch notification.

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.Impl.openDBInternal
    """

    def __init__(
        self,
        immutable_db: ImmutableDB,
        volatile_db: VolatileDB,
        ledger_db: LedgerDB,
        k: int = 2160,
        lock: Any = None,
    ) -> None:
        self.immutable_db = immutable_db
        self.volatile_db = volatile_db
        self.ledger_db = ledger_db
        self._k = k

        # Thread-safety: RWLock for concurrent read/exclusive write.
        # If not provided, creates a default instance (transparent in
        # single-threaded mode).
        if lock is None:
            from vibe.core.rwlock import RWLock

            lock = RWLock()
        self._lock = lock

        # Current selected chain tip (None if DB is empty).
        self._tip: _ChainTip | None = None

        # The block number of the immutable tip (None if empty).
        self._immutable_tip_block_number: int | None = None

        # In-memory chain fragment: last k blocks of selected chain, oldest-first.
        # Haskell ref: cdbChain TVar (AnchoredFragment)
        self._chain_fragment: list[FragmentEntry] = []
        self._fragment_index: dict[bytes, int] = {}

        # Tip change notification — generation counter + per-follower events.
        # The generation counter increments on every tip change; followers
        # compare against their last-seen generation to detect changes
        # without the lost-wakeup race of a shared threading.Event.
        # Haskell ref: STM retry on TVar read handles this naturally.
        self._tip_generation: int = 0
        self._follower_events: dict[int, threading.Event] = {}
        self._async_follower_events: dict[int, tuple[Any, Any]] = {}  # fid → (asyncio.Event, loop)

        # STM TVars for cross-thread shared state.
        # Haskell ref: cdbChain :: TVar (AnchoredFragment)
        from vibe.core.stm import TVar

        self.tip_tvar: TVar = TVar(None)  # _ChainTip | None
        self.fragment_tvar: TVar = TVar(([], {}))  # (fragment_list, index_dict)

        # Follower registry: id → ChainFollower
        # Haskell ref: cdbFollowers TVar
        self._followers: dict[int, Any] = {}
        self._next_follower_id: int = 0
        self._followers_lock = threading.Lock()

        # LedgerSeq for atomic nonce tracking (None until init_praos_state called).
        # Haskell ref: cdbLedgerDB :: LedgerDB
        self._ledger_seq: LedgerSeq | None = None
        self.praos_nonce_tvar: TVar = TVar(None)  # epoch nonce bytes | None

        # Lock serializing all _process_block calls. Acquired by both
        # the chain-sel runner (for received blocks) and the forge loop
        # (for inline-processed forged blocks).
        self._chain_sel_lock = threading.Lock()

        # Chain selection queue — serializes all add_block processing
        # through a single thread. Haskell ref: cdbChainSelQueue (TBQueue)
        import queue
        self._chain_sel_queue: queue.Queue[BlockToAdd | None] = queue.Queue()
        self._chain_sel_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Praos nonce state (LedgerSeq)
    # ------------------------------------------------------------------

    def init_praos_state(
        self,
        genesis_hash: bytes,
        epoch_length: int,
        security_param: int,
        active_slot_coeff: float,
    ) -> None:
        """Create the initial LedgerSeq and set the praos nonce TVar.

        Called during node startup after genesis parameters are known.
        Creates a genesis PraosState and wraps it in a LedgerSeq anchored
        at the genesis hash.

        Haskell ref: initialisation of cdbLedgerDB with genesis ledger state.
        """
        from vibe.cardano.consensus.praos_state import genesis_praos_state

        initial_state = genesis_praos_state(
            genesis_hash=genesis_hash,
            epoch_length=epoch_length,
            security_param=security_param,
            active_slot_coeff=active_slot_coeff,
        )
        self._ledger_seq = LedgerSeq(
            anchor_state=initial_state,
            anchor_hash=genesis_hash,
            max_rollback=self._k,
        )
        self.praos_nonce_tvar._write(initial_state.epoch_nonce)
        logger.info(
            "ChainDB: praos state initialised (epoch_nonce=%s, epoch_length=%d, k=%d)",
            initial_state.epoch_nonce.hex(),
            epoch_length,
            security_param,
        )

    def _walk_chain(
        self, intersection_hash: bytes, tip_hash: bytes,
    ) -> list[tuple[int, bytes, bytes, bytes | None]]:
        """Walk backward from tip to intersection, return blocks oldest-first.

        Each element is (slot, block_hash, prev_hash, vrf_output).
        Used during fork switches to collect blocks on the new chain
        for LedgerSeq replay.

        Haskell ref: Paths.computeReversePath — walks backward through
        VolatileDB predecessor links.
        """
        blocks: list[tuple[int, bytes, bytes, bytes | None]] = []
        h = tip_hash
        while h and h != intersection_hash:
            info = self.volatile_db._block_info.get(h)
            if info is None:
                break
            vrf_out = info.vrf_output if info.vrf_output else None
            blocks.append((info.slot, info.block_hash, info.predecessor_hash, vrf_out))
            h = info.predecessor_hash
        blocks.reverse()
        return blocks

    # ------------------------------------------------------------------
    # Initial chain selection (startup)
    # ------------------------------------------------------------------

    async def initial_chain_selection(self) -> int:
        """Reconstruct the selected chain from on-disk storage.

        Called during startup to recover state from a previous run.
        Walks the VolatileDB successor map from the ImmutableDB tip
        anchor to find the best chain, then builds the chain fragment.

        Haskell ref:
            ChainSel.initialChainSelection — reads ImmutableDB tip,
            constructs maximal candidates from VolatileDB, runs chain
            selection, stores result in cdbChain TVar.

        Returns:
            Number of blocks in the reconstructed chain fragment.
        """
        # Step 1: Load volatile blocks from disk
        from vibe.cardano.serialization.block import decode_block_header

        def _parse_header(cbor_bytes: bytes) -> BlockInfo:
            """Extract BlockInfo from raw block CBOR."""
            try:
                hdr = decode_block_header(cbor_bytes)
                return BlockInfo(
                    block_hash=hdr.hash,
                    slot=hdr.slot,
                    predecessor_hash=hdr.prev_hash or b"\x00" * 32,
                    block_number=hdr.block_number,
                )
            except NotImplementedError:
                # Byron blocks — fall back to inline extraction
                import hashlib

                import cbor2pure as cbor2

                decoded = cbor2.loads(cbor_bytes)
                if hasattr(decoded, "tag"):
                    block_body = decoded.value
                elif isinstance(decoded, list) and len(decoded) >= 2:
                    block_body = decoded[1] if isinstance(decoded[0], int) else decoded
                else:
                    block_body = decoded
                hdr_arr = block_body[0]
                hdr_body = hdr_arr[0] if isinstance(hdr_arr, list) else hdr_arr
                block_number = hdr_body[0] if isinstance(hdr_body, list) else 0
                slot = hdr_body[1] if isinstance(hdr_body, list) else 0
                prev_hash = hdr_body[2] if isinstance(hdr_body, list) else b"\x00" * 32
                if not isinstance(prev_hash, bytes):
                    prev_hash = b"\x00" * 32
                hdr_cbor = cbor2.dumps(hdr_arr)
                block_hash = hashlib.blake2b(hdr_cbor, digest_size=32).digest()
                return BlockInfo(
                    block_hash=block_hash,
                    slot=slot,
                    predecessor_hash=prev_hash,
                    block_number=block_number,
                )

        loaded = 0
        if self.volatile_db._db_dir is not None:
            loaded = await self.volatile_db.load_from_disk(_parse_header)

        if loaded == 0:
            logger.info("ChainDB: no volatile blocks to restore")
            return 0

        # Step 2: Find the anchor (ImmutableDB tip or chain root)
        # Haskell ref: ImmutableDB.getTipAnchor — anchor of the chain fragment
        immutable_tip_hash = self.immutable_db.get_tip_hash()
        immutable_tip_slot = self.immutable_db.get_tip_slot()
        if immutable_tip_hash is not None:
            anchor_hash = immutable_tip_hash
            # We don't have block_number from ImmutableDB directly
            anchor_block_number = -1
        else:
            # No immutable blocks — find the root of the volatile chain.
            # The root's predecessor hash is NOT in the volatile DB.
            # This is the "anchor" that the chain hangs from.
            roots: list[bytes] = []
            non_bytes_preds = 0
            for bh, info in self.volatile_db._block_info.items():
                pred = info.predecessor_hash
                if not isinstance(pred, bytes):
                    non_bytes_preds += 1
                    continue  # Skip non-bytes predecessor (corrupt/Byron)
                if pred not in self.volatile_db._block_info:
                    roots.append(pred)
            logger.info(
                "ChainDB: root scan — %d roots found, %d non-bytes predecessors skipped, "
                "%d total blocks",
                len(roots),
                non_bytes_preds,
                len(self.volatile_db._block_info),
            )
            # Deduplicate — all chain roots should share the same predecessor
            root_set = set(roots)
            if len(root_set) == 1:
                anchor_hash = root_set.pop()
            elif root_set:
                # Multiple roots — pick the one with the most successors
                anchor_hash = max(
                    root_set,
                    key=lambda h: len(self.volatile_db._successors.get(h, [])),
                )
            else:
                anchor_hash = b"\x00" * 32
            anchor_block_number = -1

        # Step 3: Walk successor chains from anchor to find all maximal candidates
        # Haskell ref: Paths.maximalCandidates — DFS through successor map
        def _walk_longest_chain(start_hash: bytes) -> list[BlockInfo]:
            """Iterative walk from start_hash to find the longest chain.

            Uses iterative traversal instead of recursive DFS to avoid
            stack overflow on long chains (k can be 2160+ on mainnet).
            At each fork, picks the successor with the highest block number.

            Haskell ref: Paths.maximalCandidates — but simplified to
            pick the best successor at each step (greedy) rather than
            enumerating all candidates.
            """
            chain: list[BlockInfo] = []
            current = start_hash
            while True:
                successors = self.volatile_db._successors.get(current, [])
                if not successors:
                    break
                # Pick the best successor (highest block number, then slot)
                best_succ = None
                best_info = None
                for succ_hash in successors:
                    info = self.volatile_db._block_info.get(succ_hash)
                    if info is None:
                        continue
                    if best_info is None or (
                        info.block_number > best_info.block_number
                        or (
                            info.block_number == best_info.block_number
                            and info.slot > best_info.slot
                        )
                    ):
                        best_succ = succ_hash
                        best_info = info
                if best_info is None:
                    break
                chain.append(best_info)
                current = best_succ
            return chain

        chain = _walk_longest_chain(anchor_hash)
        anchor_repr = anchor_hash.hex()[:16] if isinstance(anchor_hash, bytes) else repr(anchor_hash)
        logger.info(
            "ChainDB: chain walk from anchor %s found %d blocks "
            "(successors at anchor: %d)",
            anchor_repr,
            len(chain),
            len(self.volatile_db._successors.get(anchor_hash, [])),
        )
        candidates = [chain] if chain else []

        if not candidates:
            logger.info(
                "ChainDB: volatile blocks loaded but no chain extends from anchor"
            )
            return 0

        # Step 4: Select the best candidate
        # Haskell ref: preferAnchoredCandidate — highest block number, VRF tiebreak
        best = max(
            candidates,
            key=lambda chain: (
                chain[-1].block_number,
                chain[-1].slot,
            ),
        )

        # Step 5: Build chain fragment (last k blocks, oldest-first)
        if len(best) > self._k:
            best = best[-self._k :]

        fragment: list[FragmentEntry] = []
        for info in best:
            block_cbor = self.volatile_db._blocks.get(info.block_hash)
            header_cbor_data = (
                self._extract_header_from_block(block_cbor)
                if block_cbor else None
            )
            fragment.append(
                FragmentEntry(
                    slot=info.slot,
                    block_hash=info.block_hash,
                    block_number=info.block_number,
                    predecessor_hash=info.predecessor_hash,
                    header_cbor=header_cbor_data,
                )
            )

        # Step 6: Store the chain fragment and update tip
        self._chain_fragment = fragment
        self._fragment_index = {e.block_hash: i for i, e in enumerate(fragment)}

        tip_entry = fragment[-1]
        self._tip = _ChainTip(
            slot=tip_entry.slot,
            block_hash=tip_entry.block_hash,
            block_number=tip_entry.block_number,
        )
        self._immutable_tip_block_number = anchor_block_number

        # Update STM TVars
        self.tip_tvar._write(self._tip)
        self.fragment_tvar._write(
            (list(self._chain_fragment), dict(self._fragment_index))
        )
        self._notify_tip_changed()

        logger.info(
            "ChainDB: initial chain selection — %d blocks, tip at slot %d block #%d "
            "(from %d volatile blocks, anchor block #%d)",
            len(fragment),
            tip_entry.slot,
            tip_entry.block_number,
            loaded,
            anchor_block_number if anchor_block_number >= 0 else 0,
            extra={
                "event": "chaindb.initial_selection",
                "fragment_length": len(fragment),
                "tip_slot": tip_entry.slot,
                "tip_block": tip_entry.block_number,
                "volatile_loaded": loaded,
            },
        )
        return len(fragment)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def k(self) -> int:
        """Security parameter."""
        return self._k

    # ------------------------------------------------------------------
    # Chain fragment queries
    # ------------------------------------------------------------------

    def get_current_chain(self) -> list[FragmentEntry]:
        """Return the current chain fragment (last k blocks, oldest-first).

        Haskell ref: Query.getCurrentChain — reads cdbChain, trims to k.
        """
        return list(self._chain_fragment)

    def get_tip_as_tip(self) -> Any:
        """Return the current tip as a chainsync Tip object."""
        from vibe.cardano.network.chainsync import Point, Tip

        if self._tip:
            return Tip(
                point=Point(slot=self._tip.slot, hash=self._tip.block_hash),
                block_number=self._tip.block_number,
            )
        return Tip(point=Point(slot=0, hash=b"\x00" * 32), block_number=0)

    # ------------------------------------------------------------------
    # Follower management
    # ------------------------------------------------------------------

    def new_follower(self) -> Any:
        """Create a new chain-sync follower starting at Origin.

        Haskell ref: ChainDB.newFollower
        """
        from vibe.cardano.storage.chain_follower import ChainFollower

        with self._followers_lock:
            fid = self._next_follower_id
            self._next_follower_id += 1
            self._follower_events[fid] = threading.Event()
            follower = ChainFollower(fid, self)
            self._followers[fid] = follower
        return follower

    def close_follower(self, follower_id: int) -> None:
        """Remove a follower when the peer disconnects."""
        with self._followers_lock:
            self._followers.pop(follower_id, None)
            self._follower_events.pop(follower_id, None)
            self._async_follower_events.pop(follower_id, None)

    def _register_async_follower(
        self, follower_id: int, async_event: Any, loop: Any,
    ) -> None:
        """Register an asyncio.Event + event loop for instant cross-thread wake.

        Called by ChainFollower.instruction() on first await. The event loop
        is needed for call_soon_threadsafe from _notify_tip_changed.
        """
        with self._followers_lock:
            self._async_follower_events[follower_id] = (async_event, loop)

    def _notify_tip_changed(self) -> None:
        """Wake all follower events so each sees the new tip.

        Uses loop.call_soon_threadsafe to set asyncio.Events from any thread,
        matching Haskell's STM retry instant-wake pattern. Falls back to
        threading.Event for followers that haven't registered async events.
        """
        with self._followers_lock:
            async_items = list(self._async_follower_events.items())
            event_items = list(self._follower_events.values())

        # Async followers — instant wake via call_soon_threadsafe
        for fid, (async_evt, loop) in async_items:
            try:
                loop.call_soon_threadsafe(async_evt.set)
            except RuntimeError:
                # Loop closed — remove stale registration
                with self._followers_lock:
                    self._async_follower_events.pop(fid, None)

        # Legacy threading.Event followers (backward compat)
        for evt in event_items:
            evt.set()

    def _notify_fork_switch(
        self,
        removed_hashes: set[bytes],
        intersection_point: Any,
    ) -> None:
        """Notify all followers of a fork switch.

        Called inside add_block atomically (no await) with the chain
        fragment update.

        Haskell ref: switchTo in ChainSel.hs — notifies followers in
        same STM transaction as cdbChain update.
        """
        with self._followers_lock:
            followers = list(self._followers.values())
        for follower in followers:
            follower.notify_fork_switch(removed_hashes, intersection_point)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def _process_block(
        self,
        slot: int,
        block_hash: bytes,
        predecessor_hash: bytes,
        block_number: int,
        cbor_bytes: bytes,
        header_cbor: Any = None,
        vrf_output: bytes | None = None,
    ) -> ChainSelectionResult:
        """Process a single block through the storage pipeline (private).

        Only called by the chain selection runner thread. External callers
        must use add_block() or add_block_async().

        1. Ignore blocks at or below the immutable tip.
        2. Store in VolatileDB.
        3. Run chain selection — if this block produces a better chain,
           update the tip and chain fragment.
        4. If fork switch: notify followers before returning.
        5. Check whether the immutable tip should advance.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.addBlockAsync
            Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel.chainSelSync
        """
        t_start = time.monotonic()

        # --- Ignore blocks at or below immutable tip ---
        if (
            self._immutable_tip_block_number is not None
            and block_number <= self._immutable_tip_block_number
        ):
            logger.debug(
                "ChainDB: ignoring block %s at blockNo %d (immutable tip at blockNo %d)",
                block_hash.hex()[:16],
                block_number,
                self._immutable_tip_block_number,
            )
            tip_tuple = (
                (self._tip.slot, self._tip.block_hash, self._tip.block_number)
                if self._tip
                else None
            )
            return ChainSelectionResult(adopted=False, new_tip=tip_tuple)

        # --- Store in VolatileDB ---
        self.volatile_db.add_block(
            block_hash=block_hash,
            slot=slot,
            predecessor_hash=predecessor_hash,
            block_number=block_number,
            cbor_bytes=cbor_bytes,
            vrf_output=vrf_output or b"",
        )

        t_volatile = time.monotonic()

        # --- Chain selection (out-of-order safe) ---
        # Haskell ref: chainSelectionForBlock in ChainSel.hs
        #   1. Store block (done above)
        #   2. Check if block is reachable from current chain
        #   3. Walk successor map forward from predecessor's ALL successors
        #      to find the best candidate tip
        #   4. Switch if candidate is preferred over current tip
        old_tip = self._tip

        # Check reachability first — if block is unreachable, store but don't change.
        # Skip for first block (old_tip is None) — any block can start the chain.
        if old_tip is not None and not self._is_reachable_from_chain(block_hash):
            await self._maybe_advance_immutable()
            tip_tuple = (
                (old_tip.slot, old_tip.block_hash, old_tip.block_number)
                if old_tip else None
            )
            return ChainSelectionResult(adopted=False, new_tip=tip_tuple)

        # Walk successors forward from this block's predecessor's ALL successors
        candidate_bn, candidate_hash = self._best_candidate_from(block_hash)

        # Determine if the candidate chain is better than current tip
        should_switch = False
        new_vrf = vrf_output or b""
        if old_tip is None:
            should_switch = True
        elif candidate_bn > old_tip.block_number:
            should_switch = True
        elif candidate_bn == old_tip.block_number:
            # VRF tiebreaker: lower VRF output wins (Haskell comparePraos).
            # Use candidate's VRF from BlockInfo (set by _best_candidate_from).
            cand_info = self.volatile_db._block_info.get(candidate_hash)
            cand_vrf = (cand_info.vrf_output if cand_info else b"") or new_vrf
            if cand_vrf and old_tip.vrf_output:
                if cand_vrf < old_tip.vrf_output:
                    should_switch = True
                    logger.info(
                        "ChainDB: VRF tiebreak — switching to block %s at slot %d "
                        "(cand_vrf=%s < tip_vrf=%s)",
                        candidate_hash.hex()[:16], slot,
                        cand_vrf.hex()[:16], old_tip.vrf_output.hex()[:16],
                    )

        if not should_switch:
            await self._maybe_advance_immutable()
            tip_tuple = (
                (old_tip.slot, old_tip.block_hash, old_tip.block_number)
                if old_tip else None
            )
            return ChainSelectionResult(adopted=False, new_tip=tip_tuple)

        # Switch to the candidate chain
        ct_info = self.volatile_db._block_info[candidate_hash]
        # Always use the VRF output from BlockInfo so tiebreak works
        # even when the tip was set via DFS (not the current block).
        candidate_vrf = ct_info.vrf_output or (new_vrf if candidate_hash == block_hash else b"")
        new_tip = _ChainTip(
            slot=ct_info.slot,
            block_hash=candidate_hash,
            block_number=candidate_bn,
            vrf_output=candidate_vrf,
        )

        rollback_depth = 0
        removed_hashes: set[bytes] = set()
        intersection_hash: bytes | None = None

        if old_tip is not None:
            # Compute diff — handles both fork switches and gap-fill extensions
            rollback_depth, removed_hashes, intersection_hash = self._compute_chain_diff(
                candidate_hash
            )
        # Notify followers of fork switch BEFORE fragment update.
        # The follower's _lock ensures it checks _pending_rollback AFTER
        # it was set, preventing the race where it reads a stale fragment.
        if rollback_depth > 0 and intersection_hash is not None:
            from vibe.cardano.network.chainsync import Point as _Point
            intersection_info = self.volatile_db._block_info.get(intersection_hash)
            if intersection_info:
                ipoint = _Point(slot=intersection_info.slot, hash=intersection_hash)
                self._notify_fork_switch(removed_hashes, ipoint)

        # --- LedgerSeq nonce update BEFORE tip TVar ---
        # Must happen before tip_tvar._write() so the forge loop's
        # STM transaction never sees a new tip with a stale nonce.
        # Haskell does this atomically in a single STM transaction
        # (switchTo in ChainSel.hs); we approximate by ordering the
        # writes: nonce first, tip second.
        if self._ledger_seq is not None:
            if rollback_depth > 0 and intersection_hash is not None:
                rolled = self._ledger_seq.rollback_to_hash(intersection_hash)
                if rolled is not None:
                    new_blocks = self._walk_chain(intersection_hash, candidate_hash)
                    missing_vrf = sum(1 for _, _, _, v in new_blocks if not v)
                    if missing_vrf:
                        logger.warning(
                            "LedgerSeq fork switch: %d/%d blocks missing VRF output",
                            missing_vrf, len(new_blocks),
                        )
                    for blk_slot, blk_hash, blk_prev, blk_vrf in new_blocks:
                        rolled = rolled.extend(
                            slot=blk_slot, block_hash=blk_hash,
                            prev_hash=blk_prev,
                            vrf_output=blk_vrf or b"\x00" * 64,
                        )
                    self._ledger_seq = rolled
                else:
                    logger.warning(
                        "LedgerSeq: no checkpoint at intersection %s (seq len=%d)",
                        intersection_hash.hex()[:16],
                        self._ledger_seq.length(),
                    )
            else:
                if vrf_output:
                    self._ledger_seq = self._ledger_seq.extend(
                        slot=slot, block_hash=candidate_hash,
                        prev_hash=predecessor_hash, vrf_output=vrf_output,
                    )
                else:
                    logger.warning(
                        "LedgerSeq: block at slot %d has no VRF output — skipping nonce update",
                        slot,
                    )
            # Write nonce BEFORE tip so forge loop never reads new tip + old nonce
            self.praos_nonce_tvar._write(self._ledger_seq.tip_state().epoch_nonce)

        t_ledger = time.monotonic()

        self._tip = new_tip
        self.tip_tvar._write(new_tip)

        # Fast path: simple extension (no rollback, direct child of old tip,
        # fragment already at capacity, slot ordering maintained).
        use_fast_path = (
            old_tip is not None
            and rollback_depth == 0
            and candidate_hash == block_hash
            and ct_info.predecessor_hash == old_tip.block_hash
            and self._chain_fragment
            and ct_info.slot >= self._chain_fragment[-1].slot
        )

        if use_fast_path:
            entry = FragmentEntry(
                slot=ct_info.slot,
                block_hash=candidate_hash,
                block_number=candidate_bn,
                predecessor_hash=ct_info.predecessor_hash,
                header_cbor=header_cbor,
            )
            if self._chain_fragment:
                prev_bn = self._chain_fragment[-1].block_number
                if candidate_bn != prev_bn + 1:
                    logger.warning(
                        "ChainDB.FastPathGap: prev_bn=%d candidate_bn=%d slot=%d",
                        prev_bn, candidate_bn, ct_info.slot,
                    )
            self._chain_fragment.append(entry)
            self._fragment_index[candidate_hash] = len(self._chain_fragment) - 1

            if len(self._chain_fragment) > self._k:
                excess = len(self._chain_fragment) - self._k
                for e in self._chain_fragment[:excess]:
                    self._fragment_index.pop(e.block_hash, None)
                self._chain_fragment = self._chain_fragment[excess:]
                self._fragment_index = {
                    e.block_hash: i
                    for i, e in enumerate(self._chain_fragment)
                }

            self.fragment_tvar._write(
                (list(self._chain_fragment), dict(self._fragment_index))
            )
        else:
            header_map = {e.block_hash: e.header_cbor for e in self._chain_fragment}
            header_map[block_hash] = header_cbor
            self._rebuild_fragment_from_tip(candidate_hash, header_map)

        t_chainsel = time.monotonic()

        logger.debug(
            "ChainDB: new tip block %s at slot %d, blockNo %d "
            "(rollback=%d, fragment=%d)",
            candidate_hash.hex()[:16], ct_info.slot, candidate_bn,
            rollback_depth, len(self._chain_fragment),
        )

        # Haskell-matching ChainDB events for log correlation
        hash_hex = candidate_hash.hex()[:16]
        if rollback_depth > 0:
            logger.info(
                "ChainDB.AddBlockEvent.SwitchedToAFork: tip=%s slot=%d block_no=%d rollback=%d",
                hash_hex, ct_info.slot, candidate_bn, rollback_depth,
            )
        else:
            logger.info(
                "ChainDB.AddBlockEvent.AddedToCurrentChain: tip=%s slot=%d block_no=%d",
                hash_hex, ct_info.slot, candidate_bn,
            )

        self._tip_generation += 1
        self._notify_tip_changed()
        t_notify = time.monotonic()

        logger.info(
            "ChainDB.Timing: volatile=%.1fms ledger=%.1fms chainsel=%.1fms notify=%.1fms total=%.1fms",
            (t_volatile - t_start) * 1000,
            (t_ledger - t_volatile) * 1000,
            (t_chainsel - t_ledger) * 1000,
            (t_notify - t_chainsel) * 1000,
            (t_notify - t_start) * 1000,
        )

        await self._maybe_advance_immutable()

        return ChainSelectionResult(
            adopted=True,
            new_tip=(ct_info.slot, candidate_hash, candidate_bn),
            rollback_depth=rollback_depth,
            removed_hashes=removed_hashes,
            intersection_hash=intersection_hash,
        )

    # ------------------------------------------------------------------
    # Chain selection runner (serialized on dedicated thread)
    # ------------------------------------------------------------------

    def start_chain_sel_runner(self) -> None:
        """Launch the chain selection background thread.

        Must be called before any add_block() calls. The thread runs
        a while-loop pulling BlockToAdd entries from the queue and
        processing them one at a time.

        Haskell ref: addBlockRunner in Background.hs
        """
        import asyncio as _asyncio

        def _runner() -> None:
            loop = _asyncio.new_event_loop()
            try:
                while True:
                    entry = self._chain_sel_queue.get()
                    if entry is None:
                        break  # Shutdown sentinel
                    try:
                        with self._chain_sel_lock:
                            result = loop.run_until_complete(
                                self._process_block(
                                    slot=entry.slot,
                                    block_hash=entry.block_hash,
                                    predecessor_hash=entry.predecessor_hash,
                                    block_number=entry.block_number,
                                    cbor_bytes=entry.cbor_bytes,
                                    header_cbor=entry.header_cbor,
                                    vrf_output=entry.vrf_output,
                                )
                            )
                        entry.result = result
                    except Exception as exc:
                        entry.error = exc
                    finally:
                        entry.done.set()
            finally:
                loop.close()

        self._chain_sel_thread = threading.Thread(
            target=_runner, daemon=True, name="vibe-chainsel",
        )
        self._chain_sel_thread.start()
        logger.info("Chain selection runner started (thread=%s)", self._chain_sel_thread.name)

    def stop_chain_sel_runner(self) -> None:
        """Stop the chain selection background thread."""
        if self._chain_sel_thread is not None:
            self._chain_sel_queue.put(None)
            self._chain_sel_thread.join(timeout=5)
            self._chain_sel_thread = None
            logger.info("Chain selection runner stopped")

    def add_block(
        self,
        slot: int,
        block_hash: bytes,
        predecessor_hash: bytes,
        block_number: int,
        cbor_bytes: bytes,
        header_cbor: Any = None,
        vrf_output: bytes | None = None,
    ) -> ChainSelectionResult:
        """Enqueue a block for chain selection and wait for the result.

        This is the public API. It is synchronous -- callers on async
        event loops should use add_block_async() instead.

        Haskell ref: addBlockAsync + atomically (blockProcessed promise)
        """
        entry = BlockToAdd(
            slot=slot,
            block_hash=block_hash,
            predecessor_hash=predecessor_hash,
            block_number=block_number,
            cbor_bytes=cbor_bytes,
            header_cbor=header_cbor,
            vrf_output=vrf_output,
        )
        self._chain_sel_queue.put(entry)
        entry.done.wait()
        if entry.error is not None:
            raise entry.error
        assert entry.result is not None
        return entry.result

    def add_block_inline(
        self,
        slot: int,
        block_hash: bytes,
        predecessor_hash: bytes,
        block_number: int,
        cbor_bytes: bytes,
        header_cbor: Any = None,
        vrf_output: bytes | None = None,
    ) -> ChainSelectionResult:
        """Process a block inline on the caller's thread (no queue hop).

        Used by the forge loop for self-forged blocks. Acquires
        _chain_sel_lock to serialize with the queue-based runner.
        Avoids the queue latency that causes missed slot checks.

        The caller MUST be on a thread that can block (not an asyncio
        event loop). The forge loop runs on the main OS thread, so
        this is safe.
        """
        import asyncio as _asyncio

        with self._chain_sel_lock:
            # Use a temporary event loop for the async _process_block.
            # This is cheap (~10us) and avoids sharing the runner's loop.
            loop = _asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._process_block(
                        slot=slot,
                        block_hash=block_hash,
                        predecessor_hash=predecessor_hash,
                        block_number=block_number,
                        cbor_bytes=cbor_bytes,
                        header_cbor=header_cbor,
                        vrf_output=vrf_output,
                    )
                )
            finally:
                loop.close()

    async def add_block_async(
        self,
        **kwargs: Any,
    ) -> ChainSelectionResult:
        """Async wrapper for add_block, for callers on event loops.

        Uses asyncio.to_thread to avoid blocking the caller's event loop.
        """
        import asyncio as _asyncio
        return await _asyncio.to_thread(self.add_block, **kwargs)

    async def get_tip(self) -> tuple[int, bytes, int] | None:
        """Return the current chain tip as (slot, hash, block_number).

        Haskell reference: Ouroboros.Consensus.Storage.ChainDB.API.getTip
        """
        if self._tip is None:
            return None
        return (self._tip.slot, self._tip.block_hash, self._tip.block_number)

    async def get_block(self, block_hash: bytes) -> bytes | None:
        """Look up a block by hash, searching volatile then immutable.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.API.getBlockComponent
        """
        result = self.volatile_db.get_block(block_hash)
        if result is not None:
            return result
        return await self.immutable_db.get_block(block_hash)

    async def get_blocks(
        self,
        point_from: Any,
        point_to: Any,
    ) -> list[bytes] | None:
        """Get blocks in a range [point_from, point_to] for block-fetch.

        Walks backward from point_to through VolatileDB predecessor
        links to build the path, then serves block CBOR bytes from
        VolatileDB/ImmutableDB. The chain fragment is NOT used.

        Haskell ref:
            ChainDB.stream in Iterator.hs — creates an iterator that
            walks backward from end through VolatileDB (computePath
            in Paths.hs), then serves from both ImmutableDB and
            VolatileDB. getAnyBlockComponent in Query.hs — searches
            VolatileDB first, then ImmutableDB.
        """
        from vibe.cardano.network.chainsync import ORIGIN, Point

        # Extract hashes from points
        if point_to is ORIGIN or point_to == ORIGIN:
            return None
        if not isinstance(point_to, Point):
            return None
        end_hash = point_to.hash

        if point_from is ORIGIN or point_from == ORIGIN:
            start_hash = None  # Walk all the way back
        elif isinstance(point_from, Point):
            start_hash = point_from.hash
        else:
            start_hash = None

        # Walk backward from end_hash through VolatileDB predecessor links
        # to collect the path of block hashes from start to end.
        # Haskell ref: computePath / computeReversePath in Paths.hs
        path: list[bytes] = []
        h = end_hash
        while h is not None:
            if h not in self.volatile_db._block_info:
                # Block not in VolatileDB — might be in ImmutableDB.
                # For now, stop the backward walk here. A full
                # implementation would switch to ImmutableDB iteration.
                break
            path.append(h)
            if start_hash is not None and h == start_hash:
                break  # Reached the start point
            info = self.volatile_db._block_info[h]
            h = info.predecessor_hash
            # Safety: limit to 2*k to avoid infinite loops on corrupt data
            if len(path) > self._k * 2:
                break

        if not path:
            return None

        # Reverse to get oldest-first order
        path.reverse()

        # Fetch CBOR bytes for each block in the path
        blocks: list[bytes] = []
        for block_hash in path:
            cbor = await self.get_block(block_hash)
            if cbor is not None:
                blocks.append(cbor)
        return blocks if blocks else None

    # ------------------------------------------------------------------
    # Chain selection helpers (out-of-order safe)
    # ------------------------------------------------------------------

    def _best_candidate_from(self, start_hash: bytes) -> tuple[int, bytes]:
        """Walk successor map forward to find the best reachable chain tip.

        Starts from start_hash's predecessor and evaluates ALL successor
        paths (not just paths through start_hash). This ensures sibling
        chains are considered when a gap-filling block arrives.

        Returns (block_number, tip_hash) of the best candidate.

        Haskell ref: Paths.maximalCandidates — evaluates all forward
        paths from the new block's predecessor's successors.
        """
        info = self.volatile_db._block_info.get(start_hash)
        if info is None:
            return (0, start_hash)

        # Start from the predecessor's successors (all of them)
        pred_hash = info.predecessor_hash
        roots = self.volatile_db._successors.get(pred_hash, [start_hash])

        best_bn = 0
        best_hash = start_hash
        best_vrf = info.vrf_output

        # DFS from each root to find the longest path
        for root in roots:
            stack = [root]
            visited: set[bytes] = set()
            while stack:
                h = stack.pop()
                if h in visited:
                    continue
                visited.add(h)
                bi = self.volatile_db._block_info.get(h)
                if bi is None:
                    continue
                if bi.block_number > best_bn:
                    best_bn = bi.block_number
                    best_hash = bi.block_hash
                    best_vrf = bi.vrf_output
                elif bi.block_number == best_bn and bi.vrf_output and best_vrf:
                    # VRF tiebreak: lower VRF output wins (Haskell comparePraos)
                    if bi.vrf_output < best_vrf:
                        best_hash = bi.block_hash
                        best_vrf = bi.vrf_output
                for succ in self.volatile_db._successors.get(h, []):
                    stack.append(succ)

        return best_bn, best_hash

    def _is_reachable_from_chain(self, block_hash: bytes) -> bool:
        """Walk backward from block_hash through predecessor links.

        Returns True if we reach a block on the current chain fragment,
        the fragment's anchor (predecessor of oldest entry), or the
        immutable tip.

        Haskell ref: Paths.isReachable / computeReversePath
        """
        # Compute the anchor hash — predecessor of the oldest fragment entry
        anchor_hash: bytes | None = None
        if self._chain_fragment:
            anchor_hash = self._chain_fragment[0].predecessor_hash

        imm_tip_hash = self.immutable_db.get_tip_hash()

        h = block_hash
        visited: set[bytes] = set()
        while h:
            if h in visited:
                return False  # cycle
            visited.add(h)
            # On current chain fragment?
            if h in self._fragment_index:
                return True
            # Is it the fragment anchor?
            if anchor_hash is not None and h == anchor_hash:
                return True
            # Is it the immutable tip?
            if imm_tip_hash is not None and h == imm_tip_hash:
                return True
            # Walk backward
            info = self.volatile_db._block_info.get(h)
            if info is None:
                return False
            h = info.predecessor_hash
        return False

    # ------------------------------------------------------------------
    # Chain fragment management
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_header_from_block(block_cbor: bytes) -> list | None:
        """Extract wrapped header CBOR from a full block's CBOR bytes.

        Returns [era_tag, CBORTag(24, header_bytes)] suitable for chain-sync
        serving, or None if extraction fails.

        Haskell ref: getBlockHeader extracts the header from a SerializedBlock.
        """
        try:
            import cbor2pure as cbor2

            decoded = cbor2.loads(block_cbor)
            if hasattr(decoded, "tag"):
                era_tag = decoded.tag
                block_body = decoded.value
            elif isinstance(decoded, list) and isinstance(decoded[0], int):
                era_tag = decoded[0]
                block_body = decoded[1]
            else:
                era_tag = 0
                block_body = decoded
            hdr_arr = block_body[0] if isinstance(block_body, list) else block_body
            hdr_cbor = cbor2.dumps(hdr_arr)
            return [
                max(0, era_tag - 1) if era_tag >= 2 else 0,
                cbor2.CBORTag(24, hdr_cbor),
            ]
        except Exception:
            return None

    def _rebuild_fragment_from_tip(
        self,
        tip_hash: bytes,
        header_cbor_map: dict[bytes, Any],
    ) -> None:
        """Rebuild chain fragment by walking backward from tip.

        Haskell ref: cdbChain is an AnchoredFragment maintained
        incrementally, but we rebuild from VolatileDB predecessors.
        """
        fragment: list[FragmentEntry] = []
        h = tip_hash
        while h and h in self.volatile_db._block_info and len(fragment) < self._k:
            info = self.volatile_db._block_info[h]
            hdr = header_cbor_map.get(h)
            # If header not in map (block from new fork), extract from
            # VolatileDB block bytes.  Missing headers cause chain-sync
            # followers to skip blocks (the follower advances client_point
            # past the None-header entry, but the server treats it as
            # "await", creating a block_number gap).
            if hdr is None:
                block_cbor = self.volatile_db._blocks.get(h)
                if block_cbor:
                    hdr = self._extract_header_from_block(block_cbor)
                    if hdr is not None:
                        logger.debug(
                            "ChainDB.RebuildExtract: extracted header for bn=%d hash=%s",
                            info.block_number, h.hex()[:16],
                        )
                if hdr is None:
                    logger.warning(
                        "ChainDB.RebuildMissingHeader: bn=%d hash=%s in_volatile=%s",
                        info.block_number, h.hex()[:16], block_cbor is not None,
                    )
            fragment.append(
                FragmentEntry(
                    slot=info.slot,
                    block_hash=info.block_hash,
                    block_number=info.block_number,
                    predecessor_hash=info.predecessor_hash,
                    header_cbor=hdr,
                )
            )
            h = info.predecessor_hash
        fragment.reverse()  # oldest first (predecessor chain order)
        # Diagnostic: check for block_no gaps in rebuilt fragment
        for i in range(1, len(fragment)):
            if fragment[i].block_number != fragment[i-1].block_number + 1:
                logger.warning(
                    "ChainDB.FragmentGap: pos=%d prev_blk=%d next_blk=%d prev_slot=%d next_slot=%d prev_hash=%s next_hash=%s",
                    i, fragment[i-1].block_number, fragment[i].block_number,
                    fragment[i-1].slot, fragment[i].slot,
                    fragment[i-1].block_hash.hex()[:16], fragment[i].block_hash.hex()[:16],
                )
        self._chain_fragment = fragment
        self._fragment_index = {e.block_hash: i for i, e in enumerate(fragment)}
        # Update STM TVar
        self.fragment_tvar._write((list(fragment), dict(self._fragment_index)))

    def _compute_chain_diff(
        self,
        new_block_hash: bytes,
    ) -> tuple[int, set[bytes], bytes | None]:
        """Compute rollback depth and removed hashes for a fork switch.

        Walks backward from the new block to find the intersection with
        the current chain fragment, then counts how many current-chain
        blocks are after the intersection (= rollback depth).

        Haskell ref: Paths.isReachable + computeReversePath
        """
        current_hashes = {e.block_hash for e in self._chain_fragment}

        # Walk new block backward to find intersection
        h = new_block_hash
        intersection: bytes | None = None
        while h and h in self.volatile_db._block_info:
            if h in current_hashes:
                intersection = h
                break
            h = self.volatile_db._block_info[h].predecessor_hash

        if intersection is None:
            return (0, set(), None)

        # Count rollback: blocks on current chain after intersection
        removed: set[bytes] = set()
        idx = self._fragment_index.get(intersection)
        if idx is not None:
            for e in self._chain_fragment[idx + 1 :]:
                removed.add(e.block_hash)

        return (len(removed), removed, intersection)

    # ------------------------------------------------------------------
    # Immutable tip advancement
    # ------------------------------------------------------------------

    async def advance_immutable(self, new_immutable_slot: int) -> int:
        """Explicitly advance the immutable tip to the given slot.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.copyToImmutableDB
        """
        all_info = self.volatile_db.get_all_block_info()
        to_promote: list[BlockInfo] = [
            info for info in all_info.values() if info.slot <= new_immutable_slot
        ]
        to_promote.sort(key=lambda bi: bi.slot)

        copied = 0
        for info in to_promote:
            cbor_bytes = self.volatile_db.get_block(info.block_hash)
            if cbor_bytes is None:
                continue
            try:
                await self.immutable_db.append_block(
                    slot=info.slot,
                    block_hash=info.block_hash,
                    cbor_bytes=cbor_bytes,
                )
                copied += 1
                self._immutable_tip_block_number = info.block_number
            except Exception:
                logger.debug(
                    "ChainDB: skipped promoting block %s (slot %d)",
                    info.block_hash.hex()[:16],
                    info.slot,
                    exc_info=True,
                )

        gc_count = self.volatile_db.gc(new_immutable_slot)
        logger.debug(
            "ChainDB: GC removed %d volatile blocks at or below slot %d",
            gc_count,
            new_immutable_slot,
        )
        return copied

    async def _maybe_advance_immutable(self) -> None:
        """Check if the chain has grown enough to advance the immutable tip.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.copyToImmutableDB
        """
        if self._tip is None:
            return

        imm_bn = self._immutable_tip_block_number or 0
        tip_bn = self._tip.block_number

        if tip_bn - imm_bn <= self._k:
            return

        new_imm_block_number = tip_bn - self._k

        all_info = self.volatile_db.get_all_block_info()
        target_block: BlockInfo | None = None
        for info in all_info.values():
            if info.block_number == new_imm_block_number:
                if target_block is None or info.slot > target_block.slot:
                    target_block = info

        if target_block is None:
            return

        await self.advance_immutable(target_block.slot)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    async def get_max_slot(self) -> int | None:
        """Return the maximum slot."""
        if self._tip is None:
            return None
        return self._tip.slot

    def close(self) -> None:
        """Close the ChainDB and its sub-stores."""
        self._closed = True
        if hasattr(self.volatile_db, "close"):
            self.volatile_db.close()
        if hasattr(self.immutable_db, "close"):
            self.immutable_db.close()

    @property
    def is_closed(self) -> bool:
        return getattr(self, "_closed", False)

    async def wipe_volatile(self) -> None:
        """Wipe the volatile DB, reverting the chain to the immutable tip."""
        all_info = self.volatile_db.get_all_block_info()
        for bh in list(all_info.keys()):
            self.volatile_db.remove_block(bh)

        imm_tip_slot = self.immutable_db.get_tip_slot()
        imm_tip_hash = self.immutable_db.get_tip_hash()
        if imm_tip_slot is not None and imm_tip_hash is not None:
            self._tip = _ChainTip(
                slot=imm_tip_slot,
                block_hash=imm_tip_hash,
                block_number=self._immutable_tip_block_number or 0,
            )
        else:
            self._tip = None
        self._chain_fragment = []
        self._fragment_index = {}

    def __repr__(self) -> str:
        tip_str = (
            f"slot={self._tip.slot}, blockNo={self._tip.block_number}" if self._tip else "empty"
        )
        return (
            f"ChainDB(tip=({tip_str}), "
            f"immutable_tip_blockNo={self._immutable_tip_block_number}, "
            f"k={self._k}, fragment={len(self._chain_fragment)})"
        )
