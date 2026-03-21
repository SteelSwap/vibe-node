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
import logging
from dataclasses import dataclass, field
from typing import Any

from vibe.cardano.consensus.nonce import (
    EpochNonce,
    accumulate_vrf_output,
    evolve_nonce,
    is_in_stability_window,
)
from vibe.cardano.network.chainsync import Point, Tip, ORIGIN, PointOrOrigin
from vibe.cardano.network.chainsync_protocol import ChainProvider
from vibe.cardano.network.blockfetch_protocol import BlockProvider

logger = logging.getLogger(__name__)


@dataclass
class BlockEntry:
    """A block stored in the kernel's chain."""

    slot: int
    block_hash: bytes
    block_number: int
    header_cbor: bytes  # Wrapped header for chain-sync
    block_cbor: bytes  # Full block for block-fetch


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
        # Epoch nonce tracking
        self._epoch_nonce: EpochNonce = EpochNonce(value=b"\x00" * 32)
        self._eta_v: bytes = b"\x00" * 32
        self._current_epoch: int = 0
        self._epoch_length: int = 432000

    @property
    def tip(self) -> Tip | None:
        return self._tip

    @property
    def chain_length(self) -> int:
        return len(self._chain)

    @property
    def epoch_nonce(self) -> EpochNonce:
        return self._epoch_nonce

    def init_nonce(self, genesis_hash: bytes, epoch_length: int) -> None:
        """Seed the epoch nonce from the genesis hash."""
        self._epoch_nonce = EpochNonce(value=genesis_hash)
        self._eta_v = genesis_hash
        self._epoch_length = epoch_length
        logger.info(
            "Epoch nonce initialised: %s (epoch_length=%d)",
            genesis_hash.hex()[:16], epoch_length,
        )

    def on_block_vrf_output(self, slot: int, epoch_start_slot: int, vrf_output: bytes) -> None:
        """Accumulate VRF output from a block within the stability window."""
        if is_in_stability_window(slot, epoch_start_slot, self._epoch_length):
            self._eta_v = accumulate_vrf_output(self._eta_v, vrf_output)

    def on_epoch_boundary(self, new_epoch: int, extra_entropy: bytes | None = None) -> None:
        """Evolve the epoch nonce at an epoch transition."""
        if new_epoch <= self._current_epoch:
            return
        old_nonce = self._epoch_nonce
        self._epoch_nonce = evolve_nonce(old_nonce, self._eta_v, extra_entropy)
        self._eta_v = b"\x00" * 32
        self._current_epoch = new_epoch
        logger.info("Epoch nonce evolved: %d -> %d", new_epoch - 1, new_epoch)

    def add_block(
        self,
        slot: int,
        block_hash: bytes,
        block_number: int,
        header_cbor: bytes,
        block_cbor: bytes,
    ) -> None:
        """Add a block to the chain and notify waiting servers."""
        entry = BlockEntry(
            slot=slot,
            block_hash=block_hash,
            block_number=block_number,
            header_cbor=header_cbor,
            block_cbor=block_cbor,
        )
        idx = len(self._chain)
        self._chain.append(entry)
        self._hash_index[block_hash] = idx

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
                # Client's point not in our chain — roll back to Origin
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
