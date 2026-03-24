"""ChainDB tests — chain selection, tip tracking, and volatile/immutable fallback.

Covers:
- Chain selection: higher block_number wins
- Chain selection tie: equal height keeps existing tip
- Ignoring blocks below immutable tip
- Fallback search: volatile then immutable
- Tip updates on better chain

Haskell references:
    Ouroboros.Consensus.Storage.ChainDB.API
    Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
    Test.Ouroboros.Storage.ChainDB

Antithesis compatibility:
    All tests use deterministic data and can be replayed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import VolatileDB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _block_hash(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _cbor(n: int) -> bytes:
    return (n.to_bytes(4, "big") * 16)[:64]


def _genesis_hash() -> bytes:
    return b"\x00" * 32


def _make_chaindb(tmp_path: Path, k: int = 5) -> ChainDB:
    """Create a ChainDB with in-memory volatile, disk-backed immutable."""
    immutable = ImmutableDB(base_dir=tmp_path / "immutable", epoch_size=100)
    volatile = VolatileDB(db_dir=None)
    ledger = LedgerDB(k=k)
    return ChainDB(
        immutable_db=immutable,
        volatile_db=volatile,
        ledger_db=ledger,
        k=k,
    )


# ---------------------------------------------------------------------------
# Chain selection tests
# ---------------------------------------------------------------------------


class TestChainSelectionHigherBlockWins:
    """The block with the highest block_number becomes the tip.

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
        preferCandidate — candidate chain is better if it has a
        higher block number (simplified from full Ouroboros Praos
        chain selection).
    """

    @pytest.mark.asyncio
    async def test_chain_selection_higher_block_wins(self, tmp_path: Path) -> None:
        """Adding a block with higher block_number updates the tip."""
        db = _make_chaindb(tmp_path, k=100)
        genesis = _genesis_hash()

        # Block 1 becomes tip
        await db.add_block(
            slot=1,
            block_hash=_block_hash(1),
            predecessor_hash=genesis,
            block_number=1,
            cbor_bytes=_cbor(1),
        )
        tip = await db.get_tip()
        assert tip is not None
        assert tip[2] == 1  # block_number

        # Block 2 (higher) takes over
        await db.add_block(
            slot=2,
            block_hash=_block_hash(2),
            predecessor_hash=_block_hash(1),
            block_number=2,
            cbor_bytes=_cbor(2),
        )
        tip = await db.get_tip()
        assert tip is not None
        assert tip[2] == 2
        assert tip[1] == _block_hash(2)


class TestChainSelectionTieKeepsCurrent:
    """On equal block_number, the existing tip is kept (no switch on tie).

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
        "prefer the current chain if the candidate is not strictly better"
    """

    @pytest.mark.asyncio
    async def test_chain_selection_tie_keeps_current(self, tmp_path: Path) -> None:
        """Two blocks at the same block_number: first one stays as tip."""
        db = _make_chaindb(tmp_path, k=100)
        genesis = _genesis_hash()

        bh_a = _block_hash(1)
        bh_b = _block_hash(2)

        # Add block A at block_number 1
        await db.add_block(
            slot=1,
            block_hash=bh_a,
            predecessor_hash=genesis,
            block_number=1,
            cbor_bytes=_cbor(1),
        )

        # Add block B also at block_number 1 (fork)
        await db.add_block(
            slot=2,
            block_hash=bh_b,
            predecessor_hash=genesis,
            block_number=1,
            cbor_bytes=_cbor(2),
        )

        # Tip should still be block A (first seen, tie does not switch)
        tip = await db.get_tip()
        assert tip is not None
        assert tip[1] == bh_a


class TestAddBlockBelowImmutableIgnored:
    """Blocks at or below the immutable tip block_number are ignored.

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.Impl.addBlockSync'
        olderThanK check — blocks with blockNo <= immutableTipBlockNo
        are silently dropped.
    """

    @pytest.mark.asyncio
    async def test_add_block_below_immutable_ignored(self, tmp_path: Path) -> None:
        """Once immutable tip advances, old blocks are rejected."""
        db = _make_chaindb(tmp_path, k=2)
        genesis = _genesis_hash()

        # Build a chain of 10 blocks — k=2 means immutable tip will advance
        prev = genesis
        for i in range(1, 11):
            bh = _block_hash(i)
            await db.add_block(
                slot=i,
                block_hash=bh,
                predecessor_hash=prev,
                block_number=i,
                cbor_bytes=_cbor(i),
            )
            prev = bh

        # Immutable tip should have advanced
        assert db._immutable_tip_block_number is not None
        imm_bn = db._immutable_tip_block_number
        assert imm_bn > 0

        # Try to add a block at block_number 1 — should be silently ignored
        old_tip = await db.get_tip()
        await db.add_block(
            slot=100,
            block_hash=_block_hash(999),
            predecessor_hash=genesis,
            block_number=1,
            cbor_bytes=_cbor(999),
        )

        # Tip should not have changed
        new_tip = await db.get_tip()
        assert new_tip == old_tip

        # The ignored block should NOT be in volatile
        assert await db.volatile_db.get_block(_block_hash(999)) is None


class TestGetBlockVolatileThenImmutable:
    """get_block searches volatile first, then falls back to immutable.

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.API.getBlockComponent
        "First consult the VolatileDB, then the ImmutableDB"
    """

    @pytest.mark.asyncio
    async def test_get_block_volatile_then_immutable(self, tmp_path: Path) -> None:
        """Blocks in volatile and immutable are both findable via ChainDB."""
        db = _make_chaindb(tmp_path, k=2)
        genesis = _genesis_hash()

        # Build chain so some blocks move to immutable
        prev = genesis
        for i in range(1, 8):
            bh = _block_hash(i)
            await db.add_block(
                slot=i,
                block_hash=bh,
                predecessor_hash=prev,
                block_number=i,
                cbor_bytes=_cbor(i),
            )
            prev = bh

        # Some blocks should be in immutable (promoted), others in volatile
        # The exact split depends on k=2 and the chain length
        # But ALL blocks should be retrievable through ChainDB
        for i in range(1, 8):
            result = await db.get_block(_block_hash(i))
            assert result is not None, f"Block {i} not found via ChainDB"
            assert result == _cbor(i)

    @pytest.mark.asyncio
    async def test_get_block_not_found(self, tmp_path: Path) -> None:
        """get_block returns None for a hash not in either store."""
        db = _make_chaindb(tmp_path)
        result = await db.get_block(_block_hash(999))
        assert result is None


class TestTipUpdatesOnBetterChain:
    """Tip tracking updates when a better chain is found.

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
        ChangingSelection trace event when the tip updates.
    """

    @pytest.mark.asyncio
    async def test_tip_updates_on_better_chain(self, tmp_path: Path) -> None:
        """Building a longer chain incrementally updates the tip each time."""
        db = _make_chaindb(tmp_path, k=100)
        genesis = _genesis_hash()

        # Empty DB has no tip
        assert await db.get_tip() is None

        prev = genesis
        for i in range(1, 6):
            bh = _block_hash(i)
            await db.add_block(
                slot=i,
                block_hash=bh,
                predecessor_hash=prev,
                block_number=i,
                cbor_bytes=_cbor(i),
            )

            tip = await db.get_tip()
            assert tip is not None
            assert tip[0] == i  # slot
            assert tip[1] == bh  # hash
            assert tip[2] == i  # block_number

            prev = bh

    @pytest.mark.asyncio
    async def test_shorter_fork_does_not_update_tip(self, tmp_path: Path) -> None:
        """A fork with lower block_number does not change the tip."""
        db = _make_chaindb(tmp_path, k=100)
        genesis = _genesis_hash()

        # Main chain: 3 blocks
        prev = genesis
        for i in range(1, 4):
            await db.add_block(
                slot=i,
                block_hash=_block_hash(i),
                predecessor_hash=prev,
                block_number=i,
                cbor_bytes=_cbor(i),
            )
            prev = _block_hash(i)

        tip_before = await db.get_tip()
        assert tip_before is not None
        assert tip_before[2] == 3

        # Fork: 2 blocks (shorter)
        fork_prev = genesis
        for i in range(1, 3):
            await db.add_block(
                slot=10 + i,
                block_hash=_block_hash(100 + i),
                predecessor_hash=fork_prev,
                block_number=i,
                cbor_bytes=_cbor(100 + i),
            )
            fork_prev = _block_hash(100 + i)

        # Tip should still be the main chain
        tip_after = await db.get_tip()
        assert tip_after == tip_before
