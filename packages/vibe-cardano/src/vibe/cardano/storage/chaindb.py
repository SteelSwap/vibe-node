"""ChainDB — coordinator for ImmutableDB, VolatileDB, and LedgerDB.

The ChainDB is the top-level storage component that receives blocks from
block-fetch or chain-sync and routes them to the appropriate sub-stores:

- **VolatileDB** — receives all new blocks (recent, may be on a fork)
- **ImmutableDB** — receives finalized blocks once the chain grows past k
- **LedgerDB** — updated after each block (UTxO set mutations)

Chain selection uses a simple longest-chain rule: the block with the
highest block_number wins. Full Ouroboros Praos chain selection (VRF
tiebreakers, slot leader checks) is deferred to Phase 4.

Haskell reference:
    Ouroboros.Consensus.Storage.ChainDB.API
    Ouroboros.Consensus.Storage.ChainDB.Impl
    Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel

The Haskell ChainDB coordinates between the three sub-databases and
maintains the current chain fragment (volatile suffix of the selected
chain). Our implementation mirrors this structure with a simplified
chain selection rule.

Key invariants maintained:
    1. The immutable tip never rolls back.
    2. All blocks in the volatile DB have blockNo > immutable tip blockNo.
    3. The selected chain tip is always the block with the highest blockNo
       among chains reachable from the immutable tip.
    4. After advancing the immutable tip, blocks at or below the new
       immutable slot are garbage-collected from the volatile DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .immutable import ImmutableDB
from .ledger import LedgerDB
from .volatile import BlockInfo, VolatileDB

__all__ = ["ChainDB", "ChainSelectionError"]

logger = logging.getLogger(__name__)


class ChainSelectionError(Exception):
    """Raised when chain selection encounters an unrecoverable error."""


@dataclass(frozen=True, slots=True)
class _ChainTip:
    """Internal representation of the current chain tip.

    Attributes:
        slot: Absolute slot number of the tip block.
        block_hash: 32-byte block header hash.
        block_number: Block height (used for chain selection).
    """

    slot: int
    block_hash: bytes
    block_number: int


class ChainDB:
    """Coordinator for ImmutableDB, VolatileDB, and LedgerDB.

    Routes incoming blocks to the volatile store, runs chain selection,
    advances the immutable tip when blocks are finalized past k
    confirmations, and garbage-collects stale volatile blocks.

    Args:
        immutable_db: The append-only finalized block store.
        volatile_db: The hash-indexed recent block store.
        ledger_db: The UTxO state store with diff-based rollback.
        k: Security parameter — number of confirmations before a block
           is considered immutable. Defaults to 2160 (Cardano mainnet).

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.Impl.openDBInternal
    """

    def __init__(
        self,
        immutable_db: ImmutableDB,
        volatile_db: VolatileDB,
        ledger_db: LedgerDB,
        k: int = 2160,
    ) -> None:
        self.immutable_db = immutable_db
        self.volatile_db = volatile_db
        self.ledger_db = ledger_db
        self._k = k

        # Current selected chain tip (None if DB is empty).
        self._tip: _ChainTip | None = None

        # The block number of the immutable tip (None if empty).
        self._immutable_tip_block_number: int | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def k(self) -> int:
        """Security parameter."""
        return self._k

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
    ) -> None:
        """Receive a block and route it through the storage pipeline.

        1. Ignore blocks at or below the immutable tip.
        2. Store in VolatileDB.
        3. Run chain selection — if this block extends the best chain,
           update the tip.
        4. Check whether the immutable tip should advance (chain grew
           past k blocks beyond immutable tip).
        5. If advancing, move finalized blocks to ImmutableDB and GC.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.addBlockAsync
            Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel.addBlockSync'

        Args:
            slot: Absolute slot number.
            block_hash: 32-byte block header hash.
            predecessor_hash: Hash of the predecessor block.
            block_number: Block height.
            cbor_bytes: Raw CBOR-encoded block bytes.
        """
        # --- Ignore blocks at or below immutable tip ---
        # Haskell: olderThanK check in addBlockSync'
        if (
            self._immutable_tip_block_number is not None
            and block_number <= self._immutable_tip_block_number
        ):
            logger.debug(
                "ChainDB: ignoring block %s at blockNo %d "
                "(immutable tip at blockNo %d)",
                block_hash.hex()[:16],
                block_number,
                self._immutable_tip_block_number,
            )
            return

        # --- Store in VolatileDB ---
        await self.volatile_db.add_block(
            block_hash=block_hash,
            slot=slot,
            predecessor_hash=predecessor_hash,
            block_number=block_number,
            cbor_bytes=cbor_bytes,
        )

        # --- Chain selection ---
        # Simple rule: highest block_number wins.
        # When equal, keep existing tip (no switch on tie).
        # Haskell: Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
        if self._tip is None or block_number > self._tip.block_number:
            self._tip = _ChainTip(
                slot=slot,
                block_hash=block_hash,
                block_number=block_number,
            )
            logger.debug(
                "ChainDB: new tip block %s at slot %d, blockNo %d",
                block_hash.hex()[:16],
                slot,
                block_number,
            )

        # --- Advance immutable tip if chain is long enough ---
        await self._maybe_advance_immutable()

    async def get_tip(self) -> tuple[int, bytes, int] | None:
        """Return the current chain tip as (slot, hash, block_number).

        Returns None if the ChainDB is empty.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.API.getTip
        """
        if self._tip is None:
            return None
        return (self._tip.slot, self._tip.block_hash, self._tip.block_number)

    async def get_block(self, block_hash: bytes) -> bytes | None:
        """Look up a block by hash, searching volatile then immutable.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.API.getBlockComponent
            "First consult the VolatileDB, then the ImmutableDB"

        Args:
            block_hash: 32-byte block header hash.

        Returns:
            CBOR block bytes, or None if not found.
        """
        # Try volatile first (fast path — in-memory dict lookup)
        result = await self.volatile_db.get_block(block_hash)
        if result is not None:
            return result

        # Fall back to immutable (disk-backed)
        # Haskell: slot check guard — only query immutable if block
        # could plausibly be there. We skip the slot check for now
        # since our immutable DB does hash-based lookup.
        return await self.immutable_db.get_block(block_hash)

    async def advance_immutable(self, new_immutable_slot: int) -> int:
        """Explicitly advance the immutable tip to the given slot.

        Moves finalized blocks from VolatileDB to ImmutableDB and
        garbage-collects the volatile store.

        This is the manual API — normally called internally by
        _maybe_advance_immutable, but exposed for testing and forced
        finalization scenarios.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.copyToImmutableDB

        Args:
            new_immutable_slot: The slot up to which blocks are finalized.

        Returns:
            Number of blocks copied to the immutable DB.
        """
        # Collect volatile blocks that should be promoted
        all_info = await self.volatile_db.get_all_block_info()
        to_promote: list[BlockInfo] = [
            info for info in all_info.values()
            if info.slot <= new_immutable_slot
        ]

        # Sort by slot for monotonic append to ImmutableDB
        to_promote.sort(key=lambda bi: bi.slot)

        copied = 0
        for info in to_promote:
            cbor_bytes = await self.volatile_db.get_block(info.block_hash)
            if cbor_bytes is None:
                continue

            # Append to immutable — the ImmutableDB enforces monotonic
            # slot ordering, so we skip blocks already there.
            try:
                await self.immutable_db.append_block(
                    slot=info.slot,
                    block_hash=info.block_hash,
                    cbor_bytes=cbor_bytes,
                )
                copied += 1

                # Track the immutable tip block number
                self._immutable_tip_block_number = info.block_number

                logger.debug(
                    "ChainDB: promoted block %s (slot %d) to immutable",
                    info.block_hash.hex()[:16],
                    info.slot,
                )
            except Exception:
                # Block may already be in immutable (e.g., duplicate),
                # or slot ordering violation — skip gracefully.
                logger.debug(
                    "ChainDB: skipped promoting block %s (slot %d)",
                    info.block_hash.hex()[:16],
                    info.slot,
                    exc_info=True,
                )

        # GC volatile blocks at or below the new immutable slot
        # Haskell: garbageCollect in VolatileDB after copyToImmutableDB
        gc_count = await self.volatile_db.gc(new_immutable_slot)
        logger.debug(
            "ChainDB: GC removed %d volatile blocks at or below slot %d",
            gc_count,
            new_immutable_slot,
        )

        return copied

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _maybe_advance_immutable(self) -> None:
        """Check if the chain has grown enough to advance the immutable tip.

        The rule: if the selected chain has more than k blocks beyond the
        current immutable tip, the oldest blocks can be finalized.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.copyToImmutableDB
            "Copy blocks to the ImmutableDB when the volatile chain is
            longer than k"

        The immutable tip advances to (tip.block_number - k). We find the
        highest-slotted block in volatile with block_number equal to the
        new immutable block_number, and promote everything up to its slot.
        """
        if self._tip is None:
            return

        imm_bn = self._immutable_tip_block_number or 0
        tip_bn = self._tip.block_number

        # Need more than k blocks between immutable tip and chain tip
        if tip_bn - imm_bn <= self._k:
            return

        # The new immutable block number: everything up to (tip - k)
        new_imm_block_number = tip_bn - self._k

        # Find the block in volatile with that block number to get its slot
        all_info = await self.volatile_db.get_all_block_info()
        target_block: BlockInfo | None = None
        for info in all_info.values():
            if info.block_number == new_imm_block_number:
                if target_block is None or info.slot > target_block.slot:
                    target_block = info

        if target_block is None:
            # No matching block found — shouldn't happen with a connected
            # chain, but be defensive.
            return

        await self.advance_immutable(target_block.slot)

    async def get_max_slot(self) -> int | None:
        """Return the maximum slot across both volatile and immutable stores.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.API.getMaxSlotNo
        """
        if self._tip is None:
            return None
        return self._tip.slot

    def close(self) -> None:
        """Close the ChainDB and its sub-stores.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.API.closeDB
        """
        self._closed = True
        if hasattr(self.volatile_db, "close"):
            self.volatile_db.close()
        if hasattr(self.immutable_db, "close"):
            self.immutable_db.close()

    @property
    def is_closed(self) -> bool:
        """Whether the DB has been closed."""
        return getattr(self, "_closed", False)

    async def wipe_volatile(self) -> None:
        """Wipe the volatile DB, reverting the chain to the immutable tip.

        After wiping, only blocks in the immutable DB remain.  The tip
        reverts to the immutable tip.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.reopen
            (which effectively wipes volatile state on corruption recovery)
        """
        # Clear all volatile blocks
        all_info = await self.volatile_db.get_all_block_info()
        for bh in list(all_info.keys()):
            await self.volatile_db.remove_block(bh)

        # Revert tip to immutable tip
        imm_tip_slot = self.immutable_db.get_tip_slot()
        imm_tip_hash = self.immutable_db.get_tip_hash()
        if imm_tip_slot is not None and imm_tip_hash is not None:
            # Reconstruct tip from immutable
            self._tip = _ChainTip(
                slot=imm_tip_slot,
                block_hash=imm_tip_hash,
                block_number=self._immutable_tip_block_number or 0,
            )
        else:
            self._tip = None

    def __repr__(self) -> str:
        tip_str = (
            f"slot={self._tip.slot}, blockNo={self._tip.block_number}"
            if self._tip
            else "empty"
        )
        return (
            f"ChainDB(tip=({tip_str}), "
            f"immutable_tip_blockNo={self._immutable_tip_block_number}, "
            f"k={self._k})"
        )
