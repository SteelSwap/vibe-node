"""ChainFollower — per-client chain-sync state machine.

Tracks a client's read position on the chain and detects when fork
switches invalidate that position, producing rollback instructions.

Haskell ref: Ouroboros.Consensus.Storage.ChainDB.Impl.Follower
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from vibe.cardano.network.chainsync import ORIGIN, Point, PointOrOrigin, Tip

if TYPE_CHECKING:
    from vibe.cardano.storage.chaindb import ChainDB

logger = logging.getLogger(__name__)


class ChainFollower:
    """Per-client chain-sync follower state machine.

    Tracks the client's read position on the chain fragment maintained
    by ChainDB. When a fork switch orphans the client's position, the
    follower produces a rollback instruction before continuing.

    Haskell ref:
        instructionSTM in Follower.hs
        switchFork in Follower.hs
    """

    def __init__(self, follower_id: int, chain_db: ChainDB) -> None:
        self.id = follower_id
        self._chain_db = chain_db
        self.client_point: PointOrOrigin = ORIGIN
        self._pending_rollback: Point | None = None
        self._last_seen_generation: int = 0

    def notify_fork_switch(
        self,
        removed_hashes: set[bytes],
        intersection_point: Point,
    ) -> None:
        """Called by ChainDB when a fork switch removes blocks.

        If this follower's client_point is in the removed set,
        transition to rollback state.

        Haskell ref: fhSwitchFork in Follower.hs
        """
        if isinstance(self.client_point, Point):
            if self.client_point.hash in removed_hashes:
                self._pending_rollback = intersection_point

    async def find_intersect(
        self,
        points: list[PointOrOrigin],
    ) -> tuple[PointOrOrigin | None, Tip]:
        """Find intersection and update follower position.

        Haskell ref: followerForward
        """
        tip = self._chain_db.get_tip_as_tip()
        # Read fragment index from STM TVar for thread-safe snapshot
        _fragment, fragment_index = self._chain_db.fragment_tvar.value
        for point in points:
            if point is ORIGIN or point == ORIGIN:
                self.client_point = ORIGIN
                self._pending_rollback = None
                return ORIGIN, tip
            if isinstance(point, Point) and point.hash in fragment_index:
                self.client_point = point
                self._pending_rollback = None
                return point, tip
        # No intersection in fragment — try Origin
        self.client_point = ORIGIN
        self._pending_rollback = None
        return ORIGIN, tip

    async def instruction(
        self,
    ) -> tuple[str, Any | None, PointOrOrigin | None, Tip]:
        """Get the next chain-sync instruction for this follower.

        Returns (action, header, point, tip):
        - ("roll_backward", None, rollback_point, tip) if fork switch pending
        - ("roll_forward", header_cbor, block_point, tip) if next block available
        - ("await", None, None, tip) if client is at tip

        Haskell ref: instructionSTM in Follower.hs
            Uses AF.successorBlock(pt, curChain) to find next block.
        """
        tip = self._chain_db.get_tip_as_tip()

        # 1. Check for pending rollback (fork switch happened)
        if self._pending_rollback is not None:
            rollback_point = self._pending_rollback
            self._pending_rollback = None
            self.client_point = rollback_point
            return ("roll_backward", None, rollback_point, tip)

        # Read fragment from STM TVar — consistent snapshot across threads.
        # Haskell ref: instructionSTM reads cdbChain TVar
        fragment, fragment_index = self._chain_db.fragment_tvar.value

        if not fragment:
            return ("await", None, None, tip)

        # 2. Find next block after client_point in the chain fragment
        if self.client_point is ORIGIN or self.client_point == ORIGIN:
            next_idx = 0
        elif isinstance(self.client_point, Point):
            idx = fragment_index.get(self.client_point.hash)
            if idx is not None:
                next_idx = idx + 1
            else:
                # Point not in fragment — rollback to fragment anchor
                anchor = Point(
                    slot=fragment[0].slot,
                    hash=fragment[0].block_hash,
                )
                self.client_point = anchor
                return ("roll_backward", None, anchor, tip)
        else:
            next_idx = 0

        if next_idx < len(fragment):
            entry = fragment[next_idx]
            point = Point(slot=entry.slot, hash=entry.block_hash)
            self.client_point = point
            return ("roll_forward", entry.header_cbor, point, tip)

        # 3. At tip — wait for new blocks.
        # Wait on threading.Event via run_in_executor to avoid blocking
        # the asyncio event loop. Wakes instantly when any thread sets
        # tip_changed (e.g., forge thread or receive thread).
        try:
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,  # default thread pool
                    self._chain_db.tip_changed.wait,
                    0.5,  # timeout
                ),
                timeout=0.6,
            )
            self._chain_db.tip_changed.clear()
        except TimeoutError:
            pass
        self._last_seen_generation = self._chain_db._tip_generation

        # Re-check after wake
        tip = self._chain_db.get_tip_as_tip()

        # Check rollback again (fork switch during wait)
        if self._pending_rollback is not None:
            rollback_point = self._pending_rollback
            self._pending_rollback = None
            self.client_point = rollback_point
            return ("roll_backward", None, rollback_point, tip)

        # Re-read fragment from TVar (may have changed during wait)
        fragment, fragment_index = self._chain_db.fragment_tvar.value
        if next_idx < len(fragment):
            entry = fragment[next_idx]
            point = Point(slot=entry.slot, hash=entry.block_hash)
            self.client_point = point
            return ("roll_forward", entry.header_cbor, point, tip)

        return ("await", None, None, tip)
