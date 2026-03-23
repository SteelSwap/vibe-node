"""Tests for ChainFollower — per-client chain-sync state machine.

Tests cover:
  - Basic follower lifecycle (new_follower / close_follower)
  - instruction() returning roll_forward / await
  - Fork switch triggering rollback for affected followers
"""

from __future__ import annotations

import asyncio

import pytest

from vibe.cardano.network.chainsync import ORIGIN, Point, Tip
from vibe.cardano.node.kernel import BlockEntry, ChainFollower, NodeKernel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _make_block_entry(
    slot: int,
    block_number: int,
    block_hash: bytes,
    predecessor_hash: bytes = b"\x00" * 32,
    header_cbor: bytes = b"hdr",
    block_cbor: bytes = b"blk",
    is_forged: bool = False,
) -> dict:
    return dict(
        slot=slot,
        block_hash=block_hash,
        block_number=block_number,
        predecessor_hash=predecessor_hash,
        header_cbor=header_cbor,
        block_cbor=block_cbor,
        is_forged=is_forged,
    )


def add_block(kernel: NodeKernel, **kwargs) -> None:
    """Thin wrapper that unpacks a block-entry dict into add_block()."""
    d = kwargs
    kernel.add_block(
        slot=d["slot"],
        block_hash=d["block_hash"],
        block_number=d["block_number"],
        header_cbor=d["header_cbor"],
        block_cbor=d["block_cbor"],
        predecessor_hash=d["predecessor_hash"],
        is_forged=d.get("is_forged", False),
    )


# ---------------------------------------------------------------------------
# TestChainFollowerBasic
# ---------------------------------------------------------------------------


class TestChainFollowerBasic:
    """Lifecycle tests: creation, registration, and independence."""

    def test_new_follower_starts_at_origin(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()
        assert follower.client_point is ORIGIN or follower.client_point == ORIGIN

    def test_new_follower_registered(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()
        assert follower.id in kernel._followers
        assert kernel._followers[follower.id] is follower

    def test_close_follower_removes_from_registry(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()
        fid = follower.id
        kernel.close_follower(fid)
        assert fid not in kernel._followers

    def test_close_nonexistent_follower_is_noop(self):
        kernel = NodeKernel()
        # Should not raise
        kernel.close_follower(9999)

    def test_multiple_followers_are_independent(self):
        kernel = NodeKernel()
        f1 = kernel.new_follower()
        f2 = kernel.new_follower()
        assert f1.id != f2.id
        assert f1 is not f2
        # Closing one does not affect the other
        kernel.close_follower(f1.id)
        assert f2.id in kernel._followers

    def test_follower_ids_increment(self):
        kernel = NodeKernel()
        ids = [kernel.new_follower().id for _ in range(5)]
        assert ids == list(range(5))


# ---------------------------------------------------------------------------
# TestFollowerInstruction
# ---------------------------------------------------------------------------


class TestFollowerInstruction:
    """instruction() behaviour for normal (no-fork) operation."""

    @pytest.mark.asyncio
    async def test_await_on_empty_chain(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()
        action, header, point, tip = await asyncio.wait_for(
            follower.instruction(), timeout=2.0
        )
        assert action == "await"
        assert header is None
        assert point is None

    @pytest.mark.asyncio
    async def test_roll_forward_after_block_added(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()

        b = _make_block_entry(slot=1, block_number=1, block_hash=_hash(1))
        add_block(kernel, **b)

        action, header, point, tip = await asyncio.wait_for(
            follower.instruction(), timeout=1.0
        )
        assert action == "roll_forward"
        assert header == b"hdr"
        assert isinstance(point, Point)
        assert point.hash == _hash(1)
        assert point.slot == 1

    @pytest.mark.asyncio
    async def test_client_point_advances_through_blocks(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()

        hashes = [_hash(i) for i in range(1, 5)]
        for i, h in enumerate(hashes):
            pred = hashes[i - 1] if i > 0 else b"\x00" * 32
            add_block(
                kernel,
                **_make_block_entry(
                    slot=i + 1,
                    block_number=i + 1,
                    block_hash=h,
                    predecessor_hash=pred,
                )
            )

        for i, expected_hash in enumerate(hashes):
            action, header, point, tip = await asyncio.wait_for(
                follower.instruction(), timeout=1.0
            )
            assert action == "roll_forward", f"Expected roll_forward at step {i}"
            assert point.hash == expected_hash

    @pytest.mark.asyncio
    async def test_await_after_reaching_tip(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()

        b = _make_block_entry(slot=1, block_number=1, block_hash=_hash(1))
        add_block(kernel, **b)

        # Consume the block
        await asyncio.wait_for(follower.instruction(), timeout=1.0)

        # Now at tip — should await
        action, header, point, tip = await asyncio.wait_for(
            follower.instruction(), timeout=2.0
        )
        assert action == "await"

    @pytest.mark.asyncio
    async def test_two_followers_advance_independently(self):
        kernel = NodeKernel()
        f1 = kernel.new_follower()
        f2 = kernel.new_follower()

        hashes = [_hash(i) for i in range(1, 4)]
        for i, h in enumerate(hashes):
            pred = hashes[i - 1] if i > 0 else b"\x00" * 32
            add_block(
                kernel,
                **_make_block_entry(
                    slot=i + 1,
                    block_number=i + 1,
                    block_hash=h,
                    predecessor_hash=pred,
                )
            )

        # f1 reads all three blocks
        for _ in hashes:
            action, _, point, _ = await asyncio.wait_for(f1.instruction(), timeout=1.0)
            assert action == "roll_forward"

        # f2 has not advanced — it should still get block 1
        action, _, point, _ = await asyncio.wait_for(f2.instruction(), timeout=1.0)
        assert action == "roll_forward"
        assert point.hash == _hash(1)


# ---------------------------------------------------------------------------
# TestFollowerForkSwitch
# ---------------------------------------------------------------------------


class TestFollowerForkSwitch:
    """Fork switch causes rollback for affected followers only."""

    @pytest.mark.asyncio
    async def test_fork_switch_triggers_rollback_for_affected_follower(self):
        """A follower at block B2 is rolled back when a deeper fork replaces it.

        Chain before fork:
            genesis -> block1 -> block2 -> block3 (tip)

        Then a competing block3' arrives that extends block1 (not block2),
        triggering a fork switch that removes block2 and block3.
        The follower is at block2, so it should receive a rollback to block1.
        """
        kernel = NodeKernel()

        # Build initial chain: block1 -> block2 -> block3
        add_block(kernel, **_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1), predecessor_hash=b"\x00" * 32
        ))
        add_block(kernel, **_make_block_entry(
            slot=2, block_number=2, block_hash=_hash(2), predecessor_hash=_hash(1)
        ))
        add_block(kernel, **_make_block_entry(
            slot=3, block_number=3, block_hash=_hash(3), predecessor_hash=_hash(2)
        ))

        follower = kernel.new_follower()

        # Advance follower to block 2 (read block1 and block2)
        for i in range(2):
            action, _, _, _ = await asyncio.wait_for(follower.instruction(), timeout=1.0)
            assert action == "roll_forward", f"Expected roll_forward at step {i}"

        assert isinstance(follower.client_point, Point)
        assert follower.client_point.hash == _hash(2)

        # Fork: block4 arrives extending block1 directly (bypassing block2, block3)
        # block_number=4 > current tip of 3, predecessor=block1
        # This removes block2 and block3, intersection at block1
        add_block(kernel, **_make_block_entry(
            slot=4, block_number=4, block_hash=_hash(40),
            predecessor_hash=_hash(1),
        ))

        # follower's client_point (_hash(2)) is in the removed set
        # Next instruction should be roll_backward
        action, header, rollback_point, tip = await asyncio.wait_for(
            follower.instruction(), timeout=1.0
        )
        assert action == "roll_backward"
        assert header is None
        # Rolled back to block 1 (the intersection)
        assert isinstance(rollback_point, Point)
        assert rollback_point.hash == _hash(1)

    @pytest.mark.asyncio
    async def test_fork_switch_does_not_affect_unrelated_follower(self):
        """A follower still at Origin is not affected by a fork switch.

        Chain before fork:
            genesis -> block1 -> block2 -> block3

        Fork: block4 extends block1, removing block2 and block3.
        follower_at_tip was at block2, so it gets rolled back.
        follower_at_origin was never advanced, so it is unaffected.
        """
        kernel = NodeKernel()

        # Build initial chain: block1 -> block2 -> block3
        add_block(kernel, **_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1), predecessor_hash=b"\x00" * 32
        ))
        add_block(kernel, **_make_block_entry(
            slot=2, block_number=2, block_hash=_hash(2), predecessor_hash=_hash(1)
        ))
        add_block(kernel, **_make_block_entry(
            slot=3, block_number=3, block_hash=_hash(3), predecessor_hash=_hash(2)
        ))

        # follower_at_tip advances to block 2
        follower_at_tip = kernel.new_follower()
        for _ in range(2):
            await asyncio.wait_for(follower_at_tip.instruction(), timeout=1.0)

        # follower_at_origin has not advanced
        follower_at_origin = kernel.new_follower()

        # Fork: block4 extends block1, removing block2 and block3
        add_block(kernel, **_make_block_entry(
            slot=4, block_number=4, block_hash=_hash(40),
            predecessor_hash=_hash(1),
        ))

        # follower_at_origin should NOT get a rollback — it starts at Origin
        # and Origin is still valid; it should roll forward to block1 instead
        action, _, point, _ = await asyncio.wait_for(
            follower_at_origin.instruction(), timeout=1.0
        )
        assert action == "roll_forward"
        assert point.hash == _hash(1)

    @pytest.mark.asyncio
    async def test_after_rollback_follower_rolls_forward_with_new_chain(self):
        """After a rollback, the follower advances on the new fork.

        Chain before fork:
            genesis -> block1 -> block2 -> block3

        Fork: block4 arrives extending block1 (removes block2, block3).
        Follower was at block2, so gets rolled back to block1, then
        should roll forward to block4.
        """
        kernel = NodeKernel()

        # Initial chain: block1 -> block2 -> block3
        add_block(kernel, **_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1), predecessor_hash=b"\x00" * 32
        ))
        add_block(kernel, **_make_block_entry(
            slot=2, block_number=2, block_hash=_hash(2), predecessor_hash=_hash(1)
        ))
        add_block(kernel, **_make_block_entry(
            slot=3, block_number=3, block_hash=_hash(3), predecessor_hash=_hash(2)
        ))

        follower = kernel.new_follower()
        # Advance to block 2 (read block1 and block2)
        for _ in range(2):
            await asyncio.wait_for(follower.instruction(), timeout=1.0)

        assert follower.client_point.hash == _hash(2)

        # Fork: block4 extends block1, removing block2 and block3
        add_block(kernel, **_make_block_entry(
            slot=4, block_number=4, block_hash=_hash(40),
            predecessor_hash=_hash(1),
        ))

        # Rollback instruction
        action, _, rollback_point, _ = await asyncio.wait_for(
            follower.instruction(), timeout=1.0
        )
        assert action == "roll_backward"
        assert rollback_point.hash == _hash(1)

        # After rollback, follower is at block 1; next instruction should
        # roll forward to block4 (the new fork tip)
        action, header, point, _ = await asyncio.wait_for(
            follower.instruction(), timeout=1.0
        )
        assert action == "roll_forward"
        assert point.hash == _hash(40)
