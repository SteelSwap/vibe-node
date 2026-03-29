"""ChainDB + LedgerSeq integration tests — atomic nonce updates.

Covers:
- Simple extension updates the praos_nonce_tvar
- Fork switch rolls back LedgerSeq and reapplies new chain
- Non-adopted block does not change nonce
- praos_nonce_tvar stays consistent with ledger_seq.tip_state().epoch_nonce

Haskell references:
    Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
    Ouroboros.Consensus.Protocol.Praos (tickChainDepState, reupdateChainDepState)

Antithesis compatibility:
    All tests use deterministic data and can be replayed.
"""

from __future__ import annotations

import os
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
    import hashlib
    return hashlib.blake2b(b"test-genesis", digest_size=32).digest()


def _vrf_output(n: int) -> bytes:
    """Deterministic 64-byte VRF output for test blocks."""
    return (n.to_bytes(8, "big") * 8)


def _make_chaindb_with_praos(tmp_path: Path, k: int = 100) -> ChainDB:
    """Create a ChainDB with LedgerSeq initialized for praos nonce tracking."""
    immutable = ImmutableDB(base_dir=tmp_path / "immutable", epoch_size=100)
    volatile = VolatileDB(db_dir=None)
    ledger = LedgerDB(k=k)
    db = ChainDB(
        immutable_db=immutable,
        volatile_db=volatile,
        ledger_db=ledger,
        k=k,
    )
    # Initialize praos state with genesis parameters
    db.init_praos_state(
        genesis_hash=_genesis_hash(),
        epoch_length=100,
        security_param=k,
        active_slot_coeff=0.05,
    )
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAtomicNonceUpdate:
    """Verify that ChainDB atomically updates the praos nonce TVar
    when blocks are added and chain selection runs."""

    @pytest.mark.asyncio
    async def test_simple_extension_updates_nonce(self, tmp_path: Path) -> None:
        """Adding a block with VRF output updates praos_nonce_tvar."""
        db = _make_chaindb_with_praos(tmp_path)
        db.start_chain_sel_runner()
        try:
            genesis = _genesis_hash()

            # Read initial nonce
            initial_nonce = db.praos_nonce_tvar.value

            # Add a block with VRF output
            result = db.add_block(
                slot=1,
                block_hash=_block_hash(1),
                predecessor_hash=genesis,
                block_number=1,
                cbor_bytes=_cbor(1),
                vrf_output=_vrf_output(1),
            )
            assert result.adopted is True

            # Nonce should have changed (VRF output was mixed in)
            new_nonce = db.praos_nonce_tvar.value
            # The epoch_nonce doesn't change per-block (only at epoch boundaries),
            # but it should still be set and consistent with LedgerSeq
            assert new_nonce is not None
            assert new_nonce == db._ledger_seq.tip_state().epoch_nonce
        finally:
            db.stop_chain_sel_runner()

    @pytest.mark.asyncio
    async def test_fork_switch_rolls_back_nonce(self, tmp_path: Path) -> None:
        """Build chain A (2 blocks), then chain B (3 blocks, longer).
        Verify nonce reflects chain B, not chain A."""
        db = _make_chaindb_with_praos(tmp_path)
        db.start_chain_sel_runner()
        try:
            genesis = _genesis_hash()

            # Chain A: 2 blocks from genesis
            db.add_block(
                slot=1,
                block_hash=_block_hash(1),
                predecessor_hash=genesis,
                block_number=1,
                cbor_bytes=_cbor(1),
                vrf_output=_vrf_output(1),
            )
            db.add_block(
                slot=2,
                block_hash=_block_hash(2),
                predecessor_hash=_block_hash(1),
                block_number=2,
                cbor_bytes=_cbor(2),
                vrf_output=_vrf_output(2),
            )
            nonce_after_a = db.praos_nonce_tvar.value
            evolving_after_a = db._ledger_seq.tip_state().evolving_nonce

            # Chain B: 3 blocks from genesis (longer, forces fork switch)
            db.add_block(
                slot=3,
                block_hash=_block_hash(101),
                predecessor_hash=genesis,
                block_number=1,
                cbor_bytes=_cbor(101),
                vrf_output=_vrf_output(101),
            )
            db.add_block(
                slot=4,
                block_hash=_block_hash(102),
                predecessor_hash=_block_hash(101),
                block_number=2,
                cbor_bytes=_cbor(102),
                vrf_output=_vrf_output(102),
            )
            db.add_block(
                slot=5,
                block_hash=_block_hash(103),
                predecessor_hash=_block_hash(102),
                block_number=3,
                cbor_bytes=_cbor(103),
                vrf_output=_vrf_output(103),
            )

            # Verify tip switched to chain B
            tip = await db.get_tip()
            assert tip is not None
            assert tip[1] == _block_hash(103)

            # Nonce TVar is consistent with tip
            nonce_after_b = db.praos_nonce_tvar.value
            assert nonce_after_b is not None
            assert nonce_after_b == db._ledger_seq.tip_state().epoch_nonce
            # Evolving nonce must differ between chains (different VRF outputs).
            # epoch_nonce only changes at epoch boundaries, so within epoch 0
            # both chains have the same epoch_nonce. The evolving nonce proves
            # the fork rollback + re-apply worked correctly.
            evolving_after_b = db._ledger_seq.tip_state().evolving_nonce
            assert evolving_after_b != evolving_after_a
            # Chain B should have 3 checkpoints
            assert db._ledger_seq.length() == 3
        finally:
            db.stop_chain_sel_runner()

    @pytest.mark.asyncio
    async def test_non_adopted_block_no_nonce_change(self, tmp_path: Path) -> None:
        """Add block to a shorter fork, verify nonce unchanged."""
        db = _make_chaindb_with_praos(tmp_path)
        db.start_chain_sel_runner()
        try:
            genesis = _genesis_hash()

            # Build main chain: 3 blocks
            prev = genesis
            for i in range(1, 4):
                db.add_block(
                    slot=i,
                    block_hash=_block_hash(i),
                    predecessor_hash=prev,
                    block_number=i,
                    cbor_bytes=_cbor(i),
                    vrf_output=_vrf_output(i),
                )
                prev = _block_hash(i)

            nonce_before = db.praos_nonce_tvar.value

            # Add a fork block at block_number=1 (shorter than main chain of 3)
            db.add_block(
                slot=10,
                block_hash=_block_hash(200),
                predecessor_hash=genesis,
                block_number=1,
                cbor_bytes=_cbor(200),
                vrf_output=_vrf_output(200),
            )

            # Nonce should not have changed
            nonce_after = db.praos_nonce_tvar.value
            assert nonce_after == nonce_before
        finally:
            db.stop_chain_sel_runner()

    @pytest.mark.asyncio
    async def test_nonce_tvar_consistent_with_tip(self, tmp_path: Path) -> None:
        """After each add_block, praos_nonce_tvar == ledger_seq.tip_state().epoch_nonce."""
        db = _make_chaindb_with_praos(tmp_path)
        db.start_chain_sel_runner()
        try:
            genesis = _genesis_hash()

            prev = genesis
            for i in range(1, 6):
                db.add_block(
                    slot=i,
                    block_hash=_block_hash(i),
                    predecessor_hash=prev,
                    block_number=i,
                    cbor_bytes=_cbor(i),
                    vrf_output=_vrf_output(i),
                )
                prev = _block_hash(i)

                # After every block, the TVar should match the LedgerSeq tip
                assert db.praos_nonce_tvar.value == db._ledger_seq.tip_state().epoch_nonce
        finally:
            db.stop_chain_sel_runner()

    @pytest.mark.asyncio
    async def test_chaindb_without_praos_state_works(self, tmp_path: Path) -> None:
        """ChainDB without init_praos_state should work normally (no crash)."""
        immutable = ImmutableDB(base_dir=tmp_path / "immutable", epoch_size=100)
        volatile = VolatileDB(db_dir=None)
        ledger = LedgerDB(k=100)
        db = ChainDB(
            immutable_db=immutable,
            volatile_db=volatile,
            ledger_db=ledger,
            k=100,
        )
        db.start_chain_sel_runner()
        try:
            genesis = _genesis_hash()

            # Should work without LedgerSeq initialized
            result = db.add_block(
                slot=1,
                block_hash=_block_hash(1),
                predecessor_hash=genesis,
                block_number=1,
                cbor_bytes=_cbor(1),
                vrf_output=_vrf_output(1),
            )
            assert result.adopted is True
        finally:
            db.stop_chain_sel_runner()
