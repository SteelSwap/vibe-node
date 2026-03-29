"""ChainFollower — per-client chain-sync state machine.

Tracks a client's read position on the chain and detects when fork
switches invalidate that position, producing rollback instructions.

Haskell ref: Ouroboros.Consensus.Storage.ChainDB.Impl.Follower
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
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

    Two-phase instruction model (matches Haskell):
        instruction()          — non-blocking, returns immediately
        instruction_blocking() — blocks until data available

    The chain-sync server calls instruction() first. If it returns
    "await", the server sends MsgAwaitReply (transitioning the client
    from StCanAwait to StMustReply with a much longer timeout), then
    calls instruction_blocking() to wait for the next block.

    Haskell ref:
        followerInstruction        (non-blocking) in ChainDB.Impl.hs
        followerInstructionBlocking (blocking)     in ChainDB.Impl.hs
        switchFork in Follower.hs
    """

    def __init__(self, follower_id: int, chain_db: ChainDB) -> None:
        self.id = follower_id
        self._chain_db = chain_db
        self.client_point: PointOrOrigin = ORIGIN
        self._pending_rollback: Point | None = None
        self._last_seen_generation: int = 0
        # Lock protecting _pending_rollback writes (from notify_fork_switch
        # on Thread 2) and reads (from instruction() on Thread 3).
        self._lock = threading.Lock()
        # Asyncio event for instant cross-thread wake.
        self._async_event: asyncio.Event | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None

    def notify_fork_switch(
        self,
        removed_hashes: set[bytes],
        intersection_point: Point,
    ) -> None:
        """Called by ChainDB when a fork switch removes blocks.

        Always roll back to the intersection point. Even if the follower's
        client_point wasn't removed, the fragment indices changed during
        the rebuild, so next_idx would point to the wrong entry.

        Haskell ref: fhSwitchFork in Follower.hs — rolls back ALL
        followers whose read pointer is in the removed suffix.
        """
        with self._lock:
            self._pending_rollback = intersection_point
            logger.info(
                "ChainFollower.NotifyForkSwitch: follower=%d intersection_slot=%s",
                self.id, getattr(intersection_point, 'slot', '?'),
            )

    async def find_intersect(
        self,
        points: list[PointOrOrigin],
    ) -> tuple[PointOrOrigin | None, Tip]:
        """Find intersection and update follower position.

        Haskell ref: followerForward
        """
        tip = self._chain_db.get_tip_as_tip()
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
        self.client_point = ORIGIN
        self._pending_rollback = None
        return ORIGIN, tip

    def _try_advance(
        self,
    ) -> tuple[str, Any | None, PointOrOrigin | None, Tip]:
        """Non-blocking fragment check. Returns immediately.

        Shared logic for both instruction() and instruction_blocking().
        Must be called with self._lock held or from a single thread.
        """
        tip = self._chain_db.get_tip_as_tip()

        with self._lock:
            # 1. Check for pending rollback (fork switch happened)
            if self._pending_rollback is not None:
                rollback_point = self._pending_rollback
                self._pending_rollback = None
                self.client_point = rollback_point
                return ("roll_backward", None, rollback_point, tip)

            # Read fragment from STM TVar
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
                logger.debug(
                    "ChainFollower.Serve: f=%d bn=%d slot=%d",
                    self.id, entry.block_number, entry.slot,
                )
                self.client_point = point
                return ("roll_forward", entry.header_cbor, point, tip)

        # At tip — nothing to serve
        return ("await", None, None, tip)

    async def instruction(
        self,
    ) -> tuple[str, Any | None, PointOrOrigin | None, Tip]:
        """Non-blocking: get the next instruction or "await" if at tip.

        Haskell ref: followerInstruction in ChainDB.Impl.hs
            Returns Nothing when at tip (server should send MsgAwaitReply).

        The chain-sync server calls this first. If it returns "await",
        the server sends MsgAwaitReply to transition Haskell's client
        from StCanAwait (10s timeout) to StMustReply (601-911s timeout),
        then calls instruction_blocking() to wait for data.
        """
        return self._try_advance()

    async def instruction_blocking(
        self,
    ) -> tuple[str, Any | None, PointOrOrigin | None, Tip]:
        """Blocking: wait for new data then return the next instruction.

        Called AFTER the server has sent MsgAwaitReply. Blocks until
        a new block arrives or a fork switch happens.

        Haskell ref: followerInstructionBlocking in ChainDB.Impl.hs
            Uses STM retry to block until the chain tip changes.
        """
        # Ensure async event is registered for cross-thread wake
        if self._async_event is None:
            self._async_event = asyncio.Event()
            self._event_loop = asyncio.get_event_loop()
            self._chain_db._register_async_follower(
                self.id, self._async_event, self._event_loop,
            )

        # Loop until we have data to return
        while True:
            # Non-blocking check first (data may have arrived between
            # the server's instruction() call and this call)
            result = self._try_advance()
            if result[0] != "await":
                return result

            # Wait for tip change. Don't clear BEFORE waiting — that
            # causes a lost-wakeup race if _notify_tip_changed fires
            # between the check and here. Wait (returns instantly if
            # already set), then clear AFTER we've been woken.
            t_wait_start = time.monotonic()
            try:
                await asyncio.wait_for(
                    self._async_event.wait(), timeout=30.0,
                )
            except TimeoutError:
                pass
            t_wait_done = time.monotonic()
            self._async_event.clear()
            self._last_seen_generation = self._chain_db._tip_generation

            wait_ms = (t_wait_done - t_wait_start) * 1000
            if wait_ms > 1000.0:
                logger.info(
                    "ChainFollower.Timing: follower=%d wait=%.1fms",
                    self.id, wait_ms,
                )
