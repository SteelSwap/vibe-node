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
from dataclasses import dataclass, field
from typing import Any

from .immutable import ImmutableDB
from .ledger import LedgerDB
from .volatile import BlockInfo, VolatileDB

__all__ = [
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

        # Thread-safe tip change notification.
        self.tip_changed: threading.Event = threading.Event()
        self._tip_generation: int = 0

        # STM TVars for cross-thread shared state.
        # Haskell ref: cdbChain :: TVar (AnchoredFragment)
        from vibe.core.stm import TVar

        self.tip_tvar: TVar = TVar(None)  # _ChainTip | None
        self.fragment_tvar: TVar = TVar(([], {}))  # (fragment_list, index_dict)

        # Follower registry: id → ChainFollower
        # Haskell ref: cdbFollowers TVar
        self._followers: dict[int, Any] = {}
        self._next_follower_id: int = 0

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
            # Get header CBOR for serving via chain-sync
            block_cbor = self.volatile_db._blocks.get(info.block_hash)
            header_cbor_data: list | None = None
            if block_cbor:
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
                    header_cbor_data = [
                        max(0, era_tag - 1) if era_tag >= 2 else 0,
                        cbor2.CBORTag(24, hdr_cbor),
                    ]
                except Exception:
                    pass

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
        self.tip_changed.set()

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

        fid = self._next_follower_id
        self._next_follower_id += 1
        follower = ChainFollower(fid, self)
        self._followers[fid] = follower
        return follower

    def close_follower(self, follower_id: int) -> None:
        """Remove a follower when the peer disconnects."""
        self._followers.pop(follower_id, None)

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
        for follower in self._followers.values():
            follower.notify_fork_switch(removed_hashes, intersection_point)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_block(
        self,
        slot: int,
        block_hash: bytes,
        predecessor_hash: bytes,
        block_number: int,
        cbor_bytes: bytes,
        header_cbor: Any = None,
        vrf_output: bytes | None = None,
    ) -> ChainSelectionResult:
        """Receive a block and route it through the storage pipeline.

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
        await self.volatile_db.add_block(
            block_hash=block_hash,
            slot=slot,
            predecessor_hash=predecessor_hash,
            block_number=block_number,
            cbor_bytes=cbor_bytes,
        )

        # --- Chain selection ---
        # Haskell ref: chainSelectionForBlock + comparePraos in ChainSel.hs
        #   1. Higher block_number wins (longer chain)
        #   2. Equal block_number: lower VRF leader value wins (tiebreaker)
        #   3. Equal VRF or no VRF: keep current tip
        old_tip = self._tip

        # Determine if new block should become tip
        # Haskell ref: comparePraos in Praos/Common.hs
        #   1. Higher block_number wins (longer chain)
        #   2. Equal block_number: lower raw VRF output wins (tiebreaker)
        #   3. Equal or no VRF: keep current tip (ShouldNotSwitch)
        should_adopt = False
        new_vrf = vrf_output or b""
        if self._tip is None:
            should_adopt = True
        elif block_number > self._tip.block_number:
            should_adopt = True
        elif block_number == self._tip.block_number:
            # VRF tiebreaker: lower raw VRF output wins
            # Haskell ref: compare (Down ptvTieBreakVRF) — Down reverses,
            # so lower OutputVRF is preferred (ShouldSwitch)
            if new_vrf and self._tip.vrf_output and new_vrf < self._tip.vrf_output:
                should_adopt = True
                logger.info(
                    "ChainDB: VRF tiebreak — switching to block %s at slot %d "
                    "(new_vrf=%s < tip_vrf=%s)",
                    block_hash.hex()[:16],
                    slot,
                    new_vrf.hex()[:16],
                    self._tip.vrf_output.hex()[:16],
                )

        if should_adopt:
            new_tip = _ChainTip(
                slot=slot,
                block_hash=block_hash,
                block_number=block_number,
                vrf_output=new_vrf,
            )

            rollback_depth = 0
            removed_hashes: set[bytes] = set()
            intersection_hash: bytes | None = None

            if old_tip is not None and predecessor_hash != old_tip.block_hash:
                # Fork switch — compute diff
                rollback_depth, removed_hashes, intersection_hash = self._compute_chain_diff(
                    block_hash
                )
                # Notify followers BEFORE updating fragment (atomic)
                if rollback_depth > 0 and intersection_hash is not None:
                    from vibe.cardano.network.chainsync import Point

                    intersection_info = self.volatile_db._block_info.get(
                        intersection_hash,
                    )
                    if intersection_info:
                        ipoint = Point(
                            slot=intersection_info.slot,
                            hash=intersection_hash,
                        )
                        self._notify_fork_switch(removed_hashes, ipoint)

            self._tip = new_tip
            self.tip_tvar._write(new_tip)  # STM TVar update

            # Rebuild or extend fragment
            if rollback_depth > 0 or old_tip is None:
                # Full rebuild (fork switch or first block)
                header_map = {e.block_hash: e.header_cbor for e in self._chain_fragment}
                header_map[block_hash] = header_cbor
                self._rebuild_fragment_from_tip(block_hash, header_map)
            else:
                # Simple extend — append to fragment
                entry = FragmentEntry(
                    slot=slot,
                    block_hash=block_hash,
                    block_number=block_number,
                    predecessor_hash=predecessor_hash,
                    header_cbor=header_cbor,
                )
                idx = len(self._chain_fragment)
                self._chain_fragment.append(entry)
                self._fragment_index[block_hash] = idx
                # Trim to k
                while len(self._chain_fragment) > self._k:
                    removed_entry = self._chain_fragment.pop(0)
                    self._fragment_index.pop(removed_entry.block_hash, None)
                # Reindex after trim
                if len(self._chain_fragment) < idx + 1:
                    self._fragment_index = {
                        e.block_hash: i for i, e in enumerate(self._chain_fragment)
                    }
                # Update STM TVar
                self.fragment_tvar._write((list(self._chain_fragment), dict(self._fragment_index)))

            logger.debug(
                "ChainDB: new tip block %s at slot %d, blockNo %d (rollback=%d, fragment=%d)",
                block_hash.hex()[:16],
                slot,
                block_number,
                rollback_depth,
                len(self._chain_fragment),
            )

            # Set tip_changed — stays set until consumers clear it.
            # This ensures no waiter misses the notification.
            self._tip_generation += 1
            self.tip_changed.set()

            await self._maybe_advance_immutable()

            return ChainSelectionResult(
                adopted=True,
                new_tip=(slot, block_hash, block_number),
                rollback_depth=rollback_depth,
                removed_hashes=removed_hashes,
                intersection_hash=intersection_hash,
            )

        # Not adopted — stored but didn't change tip
        await self._maybe_advance_immutable()
        tip_tuple = (
            (self._tip.slot, self._tip.block_hash, self._tip.block_number) if self._tip else None
        )
        return ChainSelectionResult(adopted=False, new_tip=tip_tuple)

    def add_block_sync(self, **kwargs: Any) -> ChainSelectionResult:
        """Synchronous wrapper for add_block, used by the forge thread.

        Uses a thread-local event loop to avoid conflicts with other
        threads' event loops.
        """
        import asyncio as _asyncio

        # Get or create a thread-local event loop
        try:
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                # Can't use running loop — create a new one
                loop = _asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(self.add_block(**kwargs))
                finally:
                    loop.close()
            else:
                return loop.run_until_complete(self.add_block(**kwargs))
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.add_block(**kwargs))
            finally:
                loop.close()

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
        result = await self.volatile_db.get_block(block_hash)
        if result is not None:
            return result
        return await self.immutable_db.get_block(block_hash)

    async def get_blocks(
        self,
        point_from: Any,
        point_to: Any,
    ) -> list[bytes] | None:
        """Get blocks in a range, for block-fetch serving.

        Walks the chain fragment from point_from to point_to and
        returns the CBOR bytes for each block.

        Haskell ref: ChainDB iterator API
        """
        from vibe.cardano.network.chainsync import ORIGIN, Point

        if not self._chain_fragment:
            return None

        # Find start index
        if point_from is ORIGIN or point_from == ORIGIN:
            start_idx = 0
        elif isinstance(point_from, Point):
            idx = self._fragment_index.get(point_from.hash)
            if idx is None:
                return None
            start_idx = idx
        else:
            start_idx = 0

        # Find end index
        if point_to is ORIGIN or point_to == ORIGIN:
            end_idx = 0
        elif isinstance(point_to, Point):
            idx = self._fragment_index.get(point_to.hash)
            if idx is None:
                return None
            end_idx = idx
        else:
            end_idx = len(self._chain_fragment) - 1

        if start_idx > end_idx:
            return None

        # Fetch block CBOR for each entry in range
        blocks: list[bytes] = []
        for i in range(start_idx, end_idx + 1):
            entry = self._chain_fragment[i]
            cbor = await self.get_block(entry.block_hash)
            if cbor is not None:
                blocks.append(cbor)
        return blocks if blocks else None

    # ------------------------------------------------------------------
    # Chain fragment management
    # ------------------------------------------------------------------

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
        fragment.reverse()  # oldest first
        # Ensure monotonic slot ordering (required by Haskell chain-sync)
        fragment.sort(key=lambda e: e.slot)
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
        all_info = await self.volatile_db.get_all_block_info()
        to_promote: list[BlockInfo] = [
            info for info in all_info.values() if info.slot <= new_immutable_slot
        ]
        to_promote.sort(key=lambda bi: bi.slot)

        copied = 0
        for info in to_promote:
            cbor_bytes = await self.volatile_db.get_block(info.block_hash)
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

        gc_count = await self.volatile_db.gc(new_immutable_slot)
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

        all_info = await self.volatile_db.get_all_block_info()
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
        all_info = await self.volatile_db.get_all_block_info()
        for bh in list(all_info.keys()):
            await self.volatile_db.remove_block(bh)

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
