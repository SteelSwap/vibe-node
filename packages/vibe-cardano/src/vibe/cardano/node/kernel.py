"""NodeKernel — shared node state for miniprotocol servers.

Holds the chain state (blocks, tip) and implements the ChainProvider and
BlockProvider interfaces so that chain-sync and block-fetch servers can
serve data to connected peers.

The forge loop and sync pipeline write blocks into the kernel; the
protocol servers read from it. An asyncio.Event is set whenever the
tip changes, waking up any chain-sync servers that are waiting.

Haskell reference:
    Ouroboros.Consensus.NodeKernel (initNodeKernel, NodeKernel)
    The Haskell NodeKernel holds ChainDB, Mempool, BlockFetchInterface, etc.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from vibe.cardano.consensus.nonce import (
    EpochNonce,
    stability_window,
)
from vibe.cardano.ledger.delegation import (
    DelegationState,
    apply_block_certs,
    compute_pool_stake_distribution,
)
from vibe.cardano.network.chainsync import Point, Tip, ORIGIN, PointOrOrigin
from vibe.cardano.network.chainsync_protocol import ChainProvider
from vibe.cardano.network.blockfetch_protocol import BlockProvider

logger = logging.getLogger(__name__)


@dataclass
class StakeDistribution:
    """Snapshot of stake distribution for VRF leader election."""

    pool_stakes: dict[bytes, int]
    total_stake: int

    def relative_stake(self, pool_id: bytes) -> float:
        if self.total_stake == 0:
            return 0.0
        return self.pool_stakes.get(pool_id, 0) / self.total_stake


@dataclass(slots=True)
class BlockEntry:
    """A block stored in the kernel's chain."""

    slot: int
    block_hash: bytes
    block_number: int
    predecessor_hash: bytes  # 32-byte hash of predecessor block
    header_cbor: Any  # Wrapped header for chain-sync: [era_tag, CBORTag(24, bytes)]
    block_cbor: bytes  # Full block for block-fetch


class ChainFollower:
    """Per-client chain-sync state machine.

    Tracks a client's read position on the chain and handles fork
    switches that invalidate that position.

    Each connected chain-sync client gets its own ChainFollower instance
    from NodeKernel.new_follower(). The follower is driven by the
    chain-sync server calling instruction() in a loop.

    Haskell reference:
        Ouroboros.Consensus.MiniProtocol.ChainSync.Server
        (the follower / cursor abstraction used per client connection)
    """

    def __init__(self, follower_id: int, kernel: "NodeKernel") -> None:
        self.id = follower_id
        self._kernel = kernel
        self.client_point: PointOrOrigin = ORIGIN
        self._pending_rollback: Point | None = None

    def notify_fork_switch(
        self, removed_hashes: set[bytes], intersection_point: Point
    ) -> None:
        """Notify this follower that a fork switch has occurred.

        If the client's current read position was on the removed fork,
        schedule a rollback to the intersection point.

        Args:
            removed_hashes: Set of block hashes that were removed.
            intersection_point: The deepest point shared by both forks.
        """
        if (
            isinstance(self.client_point, Point)
            and self.client_point.hash in removed_hashes
        ):
            self._pending_rollback = intersection_point

    async def find_intersect(
        self, points: list[PointOrOrigin]
    ) -> tuple[PointOrOrigin | None, Tip]:
        """Find the best intersection point and update client_point.

        Args:
            points: List of points to search for, in order of preference.

        Returns:
            (intersect_point, tip) where intersect_point is the best
            match found, or None if no intersection was found.
        """
        kernel = self._kernel
        tip = kernel._tip or kernel._genesis_tip()

        for point in points:
            if point is ORIGIN or point == ORIGIN:
                self.client_point = ORIGIN
                return ORIGIN, tip
            if isinstance(point, Point) and point.hash in kernel._hash_index:
                self.client_point = point
                return point, tip

        # No intersection — reset to Origin
        self.client_point = ORIGIN
        return None, tip

    async def instruction(
        self,
    ) -> tuple[str, bytes | None, PointOrOrigin | None, Tip]:
        """Get the next instruction for the chain-sync client.

        Returns one of:
            ("roll_backward", None, rollback_point, tip)
            ("roll_forward", header_cbor, point, tip)
            ("await", None, None, tip)
        """
        kernel = self._kernel
        tip = kernel._tip or kernel._genesis_tip()

        # Pending rollback takes priority
        if self._pending_rollback is not None:
            rollback_point = self._pending_rollback
            self._pending_rollback = None
            self.client_point = rollback_point
            return ("roll_backward", None, rollback_point, tip)

        # Find the next block after client_point
        if self.client_point is ORIGIN or self.client_point == ORIGIN:
            next_idx = 0
        elif isinstance(self.client_point, Point):
            idx = kernel._hash_index.get(self.client_point.hash)
            if idx is not None:
                next_idx = idx + 1
            else:
                # Client's point was pruned — roll back to start
                if kernel._chain:
                    rollback_point = Point(
                        slot=kernel._chain[0].slot,
                        hash=kernel._chain[0].block_hash,
                    )
                    self.client_point = rollback_point
                    return ("roll_backward", None, rollback_point, tip)
                self.client_point = ORIGIN
                return ("roll_backward", None, ORIGIN, tip)
        else:
            next_idx = 0

        if next_idx < len(kernel._chain):
            entry = kernel._chain[next_idx]
            point = Point(slot=entry.slot, hash=entry.block_hash)
            self.client_point = point
            return ("roll_forward", entry.header_cbor, point, tip)

        # At tip — wait for new blocks
        try:
            await asyncio.wait_for(kernel.tip_changed.wait(), timeout=0.5)
        except TimeoutError:
            pass

        # Re-check after wake or timeout
        tip = kernel._tip or kernel._genesis_tip()
        if next_idx < len(kernel._chain):
            entry = kernel._chain[next_idx]
            point = Point(slot=entry.slot, hash=entry.block_hash)
            self.client_point = point
            return ("roll_forward", entry.header_cbor, point, tip)

        return ("await", None, None, tip)


class NodeKernel(ChainProvider, BlockProvider):
    """Shared node state — implements ChainProvider and BlockProvider.

    Maintains an ordered chain of blocks. The forge loop and sync
    pipeline call add_block() to extend the chain. Chain-sync and
    block-fetch servers query the chain to serve peers.

    Thread safety: all access is via asyncio (single event loop), so
    no locks are needed beyond the tip_changed event for notification.
    """

    def __init__(self) -> None:
        # Ordered chain: list of BlockEntry, index 0 = oldest
        self._chain: list[BlockEntry] = []
        # Hash → index for O(1) lookup
        self._hash_index: dict[bytes, int] = {}
        # Current tip
        self._tip: Tip | None = None
        # Event set whenever tip changes (wakes chain-sync servers)
        self.tip_changed: asyncio.Event = asyncio.Event()
        # Per-client chain followers
        self._followers: dict[int, ChainFollower] = {}
        self._next_follower_id: int = 0
        # Praos chain-dependent state — full 5-nonce model
        # Haskell ref: PraosState in Ouroboros.Consensus.Protocol.Praos
        self._epoch_nonce: EpochNonce = EpochNonce(value=b"\x00" * 32)
        self._evolving_nonce: bytes = b"\x00" * 32      # Running VRF accumulation
        self._candidate_nonce: bytes = b"\x00" * 32      # Frozen after stability window
        self._lab_nonce: bytes = b"\x00" * 32             # prevHashToNonce of last applied block
        self._last_epoch_block_nonce: bytes = b"\x00" * 32  # labNonce carried across epoch boundary
        self._current_epoch: int = 0
        self._epoch_length: int = 432000
        self._security_param: int = 2160
        self._active_slot_coeff: float = 0.05
        # Delegation state tracking
        self._delegation_state: DelegationState = DelegationState()
        # Protocol parameters
        self._protocol_params: dict[str, Any] = {}
        self._pending_param_updates: list[dict[str, Any]] = []
        # Per-pool stake distribution (pool_key_hash -> total lovelace)
        self._stake_distribution: dict[bytes, int] = {}

    @property
    def tip(self) -> Tip | None:
        return self._tip

    @property
    def chain_length(self) -> int:
        return len(self._chain)

    @property
    def epoch_nonce(self) -> EpochNonce:
        return self._epoch_nonce

    @property
    def delegation_state(self) -> DelegationState:
        return self._delegation_state

    @property
    def stake_distribution(self) -> dict[bytes, int]:
        return self._stake_distribution

    @property
    def current_epoch(self) -> int:
        return self._current_epoch

    @property
    def epoch_length(self) -> int:
        return self._epoch_length

    def apply_delegation_certs(
        self, transactions: list[Any], current_epoch: int
    ) -> None:
        """Apply delegation certificates from a block's transactions.

        Called by the sync pipeline after each block is processed.
        Updates the internal delegation state with any certificate
        changes (registrations, delegations, pool updates, retirements).

        Args:
            transactions: List of transaction objects from the block.
            current_epoch: Current epoch number.
        """
        self._delegation_state = apply_block_certs(
            self._delegation_state, transactions, current_epoch,
        )

    def update_stake_distribution(
        self, utxo_stakes: dict[bytes, int]
    ) -> dict[bytes, int]:
        """Recompute the per-pool stake distribution.

        Called at epoch boundaries. Combines the current delegation state
        with UTxO stake balances to produce the stake snapshot for leader
        election (used with a 2-epoch lag per the Shelley spec).

        Args:
            utxo_stakes: Mapping from stake_credential_hash -> total
                lovelace in the UTxO set for that credential.

        Returns:
            The new per-pool stake distribution.
        """
        self._stake_distribution = compute_pool_stake_distribution(
            self._delegation_state, utxo_stakes,
        )
        total = sum(self._stake_distribution.values())
        logger.info("Stake distribution updated: %d pools, total stake=%d", len(self._stake_distribution), total, extra={"event": "stake.updated", "pool_count": len(self._stake_distribution), "total_stake": total})
        return self._stake_distribution

    @property
    def protocol_params(self) -> dict[str, Any]:
        return self._protocol_params

    def init_protocol_params(self, params: dict[str, Any]) -> None:
        self._protocol_params = dict(params)

    def queue_param_update(self, update: dict[str, Any]) -> None:
        self._pending_param_updates.append(update)

    def apply_pending_updates(self) -> None:
        for update in self._pending_param_updates:
            self._protocol_params.update(update)
        count = len(self._pending_param_updates)
        self._pending_param_updates.clear()
        if count:
            logger.info("Applied %d protocol parameter updates", count, extra={"event": "params.updated", "update_count": count})

    def init_nonce(
        self,
        genesis_hash: bytes,
        epoch_length: int,
        security_param: int = 2160,
        active_slot_coeff: float = 0.05,
    ) -> None:
        """Seed the Praos chain-dependent state from the genesis hash.

        Haskell ref: translateChainDepStateByronToShelley sets the initial
        epoch nonce from tpraosInitialNonce (= shelley genesis hash).
        All other nonce values start as NeutralNonce.
        """
        self._epoch_nonce = EpochNonce(value=genesis_hash)
        self._evolving_nonce = genesis_hash
        self._candidate_nonce = genesis_hash
        self._lab_nonce = b"\x00" * 32             # NeutralNonce
        self._last_epoch_block_nonce = b"\x00" * 32  # NeutralNonce
        self._epoch_length = epoch_length
        self._security_param = security_param
        self._active_slot_coeff = active_slot_coeff
        logger.info("Epoch nonce initialised (epoch_length=%d, k=%d, f=%.4f)", epoch_length, security_param, active_slot_coeff, extra={"event": "nonce.init", "nonce": genesis_hash.hex()[:16], "epoch_length": epoch_length})

    def _combine_nonces(self, a: bytes, b: bytes) -> bytes:
        """Combine two nonces with the ⭒ operator.

        Haskell ref: (⭒) in Cardano.Ledger.BaseTypes
            NeutralNonce ⭒ x = x
            x ⭒ NeutralNonce = x
            Nonce a ⭒ Nonce b = Nonce (hash(a || b))
        """
        neutral = b"\x00" * 32
        if a == neutral:
            return b
        if b == neutral:
            return a
        return hashlib.blake2b(a + b, digest_size=32).digest()

    def on_block(self, slot: int, prev_hash: bytes, vrf_output: bytes) -> None:
        """Update Praos chain-dependent state for a received/forged block.

        Implements reupdateChainDepState from Praos.hs:
        1. evolvingNonce = evolvingNonce ⭒ vrfNonce
        2. candidateNonce = evolvingNonce if in stability window, else frozen
        3. labNonce = prevHashToNonce(prevHash)

        Args:
            slot: Block's slot number.
            prev_hash: Block's predecessor hash (32 bytes).
            vrf_output: Block's VRF output (64 bytes from header).
        """
        epoch_len = self._epoch_length
        if epoch_len <= 0:
            return

        # vrfNonce = vrfNonceValue = blake2b_256(blake2b_256("N" || vrf_output))
        # Haskell ref: vrfNonceValue in Praos/VRF.hs — double hash with "N" prefix
        from vibe.cardano.crypto.vrf import vrf_nonce_value
        vrf_nonce = vrf_nonce_value(vrf_output)

        # evolvingNonce = evolvingNonce ⭒ vrfNonce
        self._evolving_nonce = self._combine_nonces(
            self._evolving_nonce, vrf_nonce,
        )

        # candidateNonce: freeze after stability window
        # Haskell: if slot + stabilityWindow < firstSlotNextEpoch
        #          then evolvingNonce else candidateNonce
        block_epoch = slot // epoch_len
        first_slot_next_epoch = (block_epoch + 1) * epoch_len
        stab_window = stability_window(
            epoch_len, self._security_param, self._active_slot_coeff,
        )
        if slot + stab_window < first_slot_next_epoch:
            self._candidate_nonce = self._evolving_nonce

        # labNonce = prevHashToNonce(prevHash)
        # Haskell: prevHashToNonce just wraps the hash as a Nonce
        self._lab_nonce = prev_hash

    def on_epoch_boundary(self, new_epoch: int, extra_entropy: bytes | None = None) -> None:
        """Evolve the epoch nonce at an epoch transition.

        Implements tickChainDepState from Praos.hs:
            epochNonce = candidateNonce ⭒ lastEpochBlockNonce
            lastEpochBlockNonce = labNonce

        Haskell ref: tickChainDepState in Ouroboros.Consensus.Protocol.Praos
        """
        if new_epoch <= self._current_epoch:
            return

        # epochNonce = candidateNonce ⭒ lastEpochBlockNonce
        new_nonce_bytes = self._combine_nonces(
            self._candidate_nonce, self._last_epoch_block_nonce,
        )
        if extra_entropy is not None:
            new_nonce_bytes = self._combine_nonces(
                new_nonce_bytes, extra_entropy,
            )

        old_epoch = self._current_epoch
        self._epoch_nonce = EpochNonce(value=new_nonce_bytes)

        # lastEpochBlockNonce = labNonce (carry forward)
        self._last_epoch_block_nonce = self._lab_nonce

        self._current_epoch = new_epoch
        logger.info("Epoch transition %d -> %d (nonce=%s)", old_epoch, new_epoch, new_nonce_bytes.hex()[:16], extra={"event": "epoch.transition", "from_epoch": old_epoch, "to_epoch": new_epoch})

    def add_block(
        self,
        slot: int,
        block_hash: bytes,
        block_number: int,
        header_cbor: bytes,
        block_cbor: bytes,
        predecessor_hash: bytes = b"\x00" * 32,
        is_forged: bool = False,
    ) -> None:
        """Add a block to the chain.

        For received blocks (from chain-sync): always accept if
        block_number > tip. These come from a valid Haskell chain.

        For forged blocks: only accept if they extend the current tip
        (predecessor matches tip hash). If a received block arrives at
        the same height, it takes precedence (our forged block is
        replaced via fork switching).

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
        """
        entry = BlockEntry(
            slot=slot,
            block_hash=block_hash,
            block_number=block_number,
            predecessor_hash=predecessor_hash,
            header_cbor=header_cbor,
            block_cbor=block_cbor,
        )

        if is_forged:
            # Forged blocks: must extend current tip.
            if self._chain and predecessor_hash != self._chain[-1].block_hash:
                logger.warning(
                    "NodeKernel: skipping forged block #%d slot=%d "
                    "(doesn't extend tip: pred=%s, tip=%s)",
                    block_number, slot,
                    predecessor_hash.hex()[:16],
                    self._chain[-1].block_hash.hex()[:16],
                )
                return

        if not self._chain:
            # First block.
            self._chain.append(entry)
            self._hash_index[block_hash] = 0
        elif block_number > self._chain[-1].block_number:
            # Better than current tip.
            if predecessor_hash == self._chain[-1].block_hash:
                # Extends current tip — normal append.
                idx = len(self._chain)
                self._chain.append(entry)
                self._hash_index[block_hash] = idx
            else:
                # Fork — find fork point and switch.
                fork_idx = self._hash_index.get(predecessor_hash)
                if fork_idx is not None:
                    removed = self._chain[fork_idx + 1:]
                    intersection_point = Point(
                        slot=self._chain[fork_idx].slot,
                        hash=self._chain[fork_idx].block_hash,
                    )
                    self._notify_fork_switch(removed, intersection_point)
                    for r in removed:
                        self._hash_index.pop(r.block_hash, None)
                    self._chain = self._chain[:fork_idx + 1]
                    idx = len(self._chain)
                    self._chain.append(entry)
                    self._hash_index[block_hash] = idx
                    logger.info("Chain fork switch: removed %d blocks, new tip block #%d at slot %d", len(removed), block_number, slot, extra={"event": "chain.fork", "removed_blocks": len(removed), "block_number": block_number, "slot": slot})
                else:
                    # Predecessor not in chain — just append (received
                    # blocks from a valid chain may arrive after pruning).
                    idx = len(self._chain)
                    self._chain.append(entry)
                    self._hash_index[block_hash] = idx
        elif block_number == self._chain[-1].block_number:
            if not is_forged and predecessor_hash != self._chain[-1].predecessor_hash:
                # Received block at same height on different fork — switch
                # (prefer received over our forged blocks).
                fork_idx = self._hash_index.get(predecessor_hash)
                if fork_idx is not None:
                    removed = self._chain[fork_idx + 1:]
                    intersection_point = Point(
                        slot=self._chain[fork_idx].slot,
                        hash=self._chain[fork_idx].block_hash,
                    )
                    self._notify_fork_switch(removed, intersection_point)
                    for r in removed:
                        self._hash_index.pop(r.block_hash, None)
                    self._chain = self._chain[:fork_idx + 1]
                    idx = len(self._chain)
                    self._chain.append(entry)
                    self._hash_index[block_hash] = idx
                    logger.info("Chain fork switch at height %d, replaced %d blocks", block_number, len(removed), extra={"event": "chain.fork", "block_number": block_number, "removed_blocks": len(removed)})
                else:
                    return
            else:
                return
        else:
            # Block number <= tip — ignore.
            return

        self._tip = Tip(
            point=Point(slot=slot, hash=block_hash),
            block_number=block_number,
        )

        # Wake up any chain-sync servers waiting for new data.
        self.tip_changed.set()
        self.tip_changed.clear()

        logger.debug(
            "NodeKernel: added block #%d slot=%d hash=%s (chain len=%d)",
            block_number, slot, block_hash.hex()[:16], len(self._chain),
        )

    def _genesis_tip(self) -> Tip:
        """Return a genesis tip when the chain is empty."""
        return Tip(point=Point(slot=0, hash=b"\x00" * 32), block_number=0)

    # --- Follower registry ---

    def new_follower(self) -> ChainFollower:
        """Create and register a new chain-sync follower.

        Returns:
            A new ChainFollower starting at Origin.
        """
        follower_id = self._next_follower_id
        self._next_follower_id += 1
        follower = ChainFollower(follower_id=follower_id, kernel=self)
        self._followers[follower_id] = follower
        logger.debug("ChainFollower %d created", follower_id)
        return follower

    def close_follower(self, follower_id: int) -> None:
        """Remove a follower from the registry.

        Args:
            follower_id: The ID of the follower to remove.
        """
        self._followers.pop(follower_id, None)
        logger.debug("ChainFollower %d closed", follower_id)

    def _notify_fork_switch(
        self, removed: list[BlockEntry], intersection_point: Point
    ) -> None:
        """Notify all followers of a fork switch.

        Called internally when add_block() performs a chain fork switch.
        Any follower whose client_point is on the removed chain will
        be given a pending rollback to the intersection_point.

        Args:
            removed: List of BlockEntry items that were removed from the chain.
            intersection_point: The deepest point shared by both the old and
                new forks (the fork point itself, not a removed block).
        """
        removed_hashes = {entry.block_hash for entry in removed}
        for follower in self._followers.values():
            follower.notify_fork_switch(removed_hashes, intersection_point)

    # --- ChainProvider interface ---

    async def get_tip(self) -> Tip:
        return self._tip or self._genesis_tip()

    async def find_intersect(
        self, points: list[PointOrOrigin]
    ) -> tuple[PointOrOrigin | None, Tip]:
        tip = self._tip or self._genesis_tip()

        for point in points:
            if point is ORIGIN or point == ORIGIN:
                return ORIGIN, tip
            if isinstance(point, Point) and point.hash in self._hash_index:
                return point, tip

        # No intersection — but Origin always works
        return ORIGIN, tip

    async def next_block(
        self, client_point: PointOrOrigin
    ) -> tuple[str, bytes | None, PointOrOrigin | None, Tip]:
        tip = self._tip or self._genesis_tip()

        if not self._chain:
            # Empty chain — wait for a block
            return ("await", None, None, tip)

        # Find client's position in our chain
        if client_point is ORIGIN or client_point == ORIGIN:
            next_idx = 0
        elif isinstance(client_point, Point):
            idx = self._hash_index.get(client_point.hash)
            if idx is not None:
                next_idx = idx + 1
            else:
                # Client's point not in our chain (fork switch removed it).
                # Find the deepest block in our chain whose predecessor
                # matches something the client might have, or roll back to
                # the start of our chain. This avoids full re-sync to Origin.
                if self._chain:
                    rollback_point = Point(
                        slot=self._chain[0].slot,
                        hash=self._chain[0].block_hash,
                    )
                    return ("roll_backward", None, rollback_point, tip)
                return ("roll_backward", None, ORIGIN, tip)
        else:
            next_idx = 0

        if next_idx < len(self._chain):
            # Have a block to serve
            entry = self._chain[next_idx]
            point = Point(slot=entry.slot, hash=entry.block_hash)
            return ("roll_forward", entry.header_cbor, point, tip)
        else:
            # Client is at our tip — wait for new blocks
            # Wait with a timeout so the server loop can check stop_event
            try:
                await asyncio.wait_for(self.tip_changed.wait(), timeout=0.5)
            except TimeoutError:
                pass
            # Re-check after wake
            if next_idx < len(self._chain):
                entry = self._chain[next_idx]
                point = Point(slot=entry.slot, hash=entry.block_hash)
                return ("roll_forward", entry.header_cbor, point, tip)
            return ("await", None, None, tip)

    # --- BlockProvider interface ---

    async def get_blocks(
        self, point_from: PointOrOrigin, point_to: PointOrOrigin
    ) -> list[bytes] | None:
        if not self._chain:
            return None

        # Find start index
        if point_from is ORIGIN or point_from == ORIGIN:
            start_idx = 0
        elif isinstance(point_from, Point):
            idx = self._hash_index.get(point_from.hash)
            if idx is None:
                return None
            start_idx = idx
        else:
            start_idx = 0

        # Find end index
        if point_to is ORIGIN or point_to == ORIGIN:
            end_idx = 0
        elif isinstance(point_to, Point):
            idx = self._hash_index.get(point_to.hash)
            if idx is None:
                return None
            end_idx = idx
        else:
            end_idx = len(self._chain) - 1

        if start_idx > end_idx:
            return None

        return [
            self._chain[i].block_cbor
            for i in range(start_idx, end_idx + 1)
        ]
