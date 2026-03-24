"""M6.7.3 — Chain selection, mempool, storage, and UTxO benchmarks.

Measures performance of the core operational code paths:
- Chain selection with N candidates
- Mempool tx add/remove operations
- VolatileDB read/write
- LedgerDB UTxO lookup and block application

Run: uv run pytest tests/benchmark/test_bench_operations.py -v --benchmark-only
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any

import pytest

from vibe.cardano.consensus.chain_selection import (
    ChainCandidate,
    Preference,
    compare_chains,
    is_chain_better,
    should_switch_to,
)
from vibe.cardano.mempool.mempool import Mempool
from vibe.cardano.mempool.types import MempoolConfig, MempoolSnapshot
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import BlockInfo, VolatileDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hash(seed: int) -> bytes:
    """Deterministic 32-byte hash from an integer seed."""
    return hashlib.blake2b(seed.to_bytes(8, "big"), digest_size=32).digest()


def _make_vrf_output(seed: int) -> bytes:
    """Deterministic 64-byte VRF output from an integer seed."""
    return hashlib.sha512(seed.to_bytes(8, "big")).digest()


def _make_candidate(block_number: int, slot: int, seed: int) -> ChainCandidate:
    """Create a chain candidate with deterministic hashes."""
    return ChainCandidate(
        tip_slot=slot,
        tip_block_number=block_number,
        tip_hash=_make_hash(seed),
        chain_length=block_number,
        vrf_output=_make_vrf_output(seed),
    )


def _make_txin_key(tx_idx: int) -> bytes:
    """Create a 34-byte TxIn key: 32-byte tx_hash + 2-byte index."""
    tx_hash = _make_hash(tx_idx)
    return tx_hash + (tx_idx % 65536).to_bytes(2, "big")


def _make_utxo_entry(tx_idx: int) -> tuple[bytes, dict[str, Any]]:
    """Create a (key, column_values) pair for LedgerDB insertion."""
    key = _make_txin_key(tx_idx)
    tx_hash = key[:32]
    tx_index = tx_idx % 65536
    return key, {
        "tx_hash": tx_hash,
        "tx_index": tx_index,
        "address": f"addr_test1qz{tx_idx:040d}",
        "value": 2_000_000 + tx_idx,
        "datum_hash": b"",
    }


# ---------------------------------------------------------------------------
# Chain selection benchmarks
# ---------------------------------------------------------------------------

class TestChainSelection:
    """Benchmark chain selection comparisons.

    Chain selection runs on every new block received, so it must be fast.
    We measure pairwise comparison and N-candidate best-chain selection.
    """

    def test_compare_two_chains_different_length(self, benchmark) -> None:
        """Compare two candidates with different block numbers (fast path)."""
        a = _make_candidate(1000, 20000, seed=1)
        b = _make_candidate(999, 19990, seed=2)
        result = benchmark.pedantic(compare_chains, args=(a, b), rounds=100)
        assert result == Preference.PREFER_FIRST

    def test_compare_two_chains_same_length_vrf_tiebreak(self, benchmark) -> None:
        """Compare two candidates with same block number (VRF tiebreak)."""
        a = _make_candidate(1000, 20000, seed=1)
        b = _make_candidate(1000, 20000, seed=2)
        benchmark.pedantic(compare_chains, args=(a, b), rounds=100)

    def test_should_switch_to_with_fork_point(self, benchmark) -> None:
        """Full should_switch_to check including k-deep finality."""
        our = _make_candidate(1000, 20000, seed=1)
        candidate = _make_candidate(1001, 20010, seed=2)
        result = benchmark.pedantic(
            should_switch_to,
            args=(our, candidate),
            kwargs={"fork_point_block_number": 999},
            rounds=100,
        )
        assert result is True

    def test_select_best_of_10_candidates(self, benchmark) -> None:
        """Select the best chain from 10 candidates."""
        candidates = [_make_candidate(1000 + i, 20000 + i * 10, seed=i) for i in range(10)]

        def select_best(chains: list[ChainCandidate]) -> ChainCandidate:
            best = chains[0]
            for c in chains[1:]:
                if compare_chains(c, best) == Preference.PREFER_FIRST:
                    best = c
            return best

        result = benchmark.pedantic(select_best, args=(candidates,), rounds=100)
        assert result.tip_block_number == 1009

    def test_select_best_of_100_candidates(self, benchmark) -> None:
        """Select the best chain from 100 candidates."""
        candidates = [_make_candidate(1000 + i, 20000 + i * 10, seed=i) for i in range(100)]

        def select_best(chains: list[ChainCandidate]) -> ChainCandidate:
            best = chains[0]
            for c in chains[1:]:
                if compare_chains(c, best) == Preference.PREFER_FIRST:
                    best = c
            return best

        result = benchmark.pedantic(select_best, args=(candidates,), rounds=100)
        assert result.tip_block_number == 1099


# ---------------------------------------------------------------------------
# Mempool benchmarks (sync-only operations — avoid asyncio in benchmarks)
# ---------------------------------------------------------------------------

class _AlwaysValidValidator:
    """A validator that always accepts transactions."""

    def validate_tx(self, tx_cbor: bytes, current_slot: int) -> list[str]:
        return []

    def apply_tx(self, tx_cbor: bytes, current_slot: int) -> None:
        pass

    def snapshot_state(self) -> Any:
        return None

    def restore_state(self, state: Any) -> None:
        pass


class TestMempool:
    """Benchmark mempool operations.

    The mempool is on the hot path for tx-submission and block forging.
    We benchmark the synchronous internals where possible.
    """

    def test_mempool_add_tx(self, benchmark) -> None:
        """Add a transaction to the mempool (async)."""
        loop = asyncio.new_event_loop()
        config = MempoolConfig(capacity_bytes=10_000_000)
        validator = _AlwaysValidValidator()

        def add_one():
            mempool = Mempool(config, validator, current_slot=100)
            tx_cbor = os.urandom(256)
            loop.run_until_complete(mempool.add_tx(tx_cbor))

        benchmark.pedantic(add_one, rounds=100)
        loop.close()

    def test_mempool_add_100_txs(self, benchmark) -> None:
        """Add 100 transactions to a fresh mempool."""
        loop = asyncio.new_event_loop()
        config = MempoolConfig(capacity_bytes=10_000_000)
        validator = _AlwaysValidValidator()
        txs = [os.urandom(256) for _ in range(100)]

        def add_batch():
            mempool = Mempool(config, validator, current_slot=100)
            for tx in txs:
                loop.run_until_complete(mempool.add_tx(tx))

        benchmark.pedantic(add_batch, rounds=100)
        loop.close()

    def test_mempool_remove_txs(self, benchmark) -> None:
        """Remove 50 transactions from a mempool with 100."""
        loop = asyncio.new_event_loop()
        config = MempoolConfig(capacity_bytes=10_000_000)
        validator = _AlwaysValidValidator()
        txs = [os.urandom(256) for _ in range(100)]

        def remove_batch():
            mempool = Mempool(config, validator, current_slot=100)
            for tx in txs:
                loop.run_until_complete(mempool.add_tx(tx))
            # Get the tx IDs of the first 50
            snapshot = loop.run_until_complete(mempool.get_snapshot())
            tx_ids = [t.validated_tx.tx_id for t in snapshot.tickets[:50]]
            loop.run_until_complete(mempool.remove_txs(tx_ids))

        benchmark.pedantic(remove_batch, rounds=100)
        loop.close()

    def test_mempool_snapshot(self, benchmark) -> None:
        """Take a snapshot of a mempool with 100 transactions."""
        loop = asyncio.new_event_loop()
        config = MempoolConfig(capacity_bytes=10_000_000)
        validator = _AlwaysValidValidator()
        mempool = Mempool(config, validator, current_slot=100)
        for _ in range(100):
            loop.run_until_complete(mempool.add_tx(os.urandom(256)))

        def take_snapshot():
            return loop.run_until_complete(mempool.get_snapshot())

        result = benchmark.pedantic(take_snapshot, rounds=100)
        assert len(result.tickets) == 100
        loop.close()


# ---------------------------------------------------------------------------
# VolatileDB benchmarks
# ---------------------------------------------------------------------------

class TestVolatileDB:
    """Benchmark VolatileDB read/write (in-memory mode)."""

    def test_volatile_add_block(self, benchmark) -> None:
        """Add a block to the VolatileDB."""
        loop = asyncio.new_event_loop()
        cbor_data = os.urandom(4096)

        def add_one():
            db = VolatileDB(db_dir=None)
            h = _make_hash(42)
            pred = _make_hash(41)
            loop.run_until_complete(
                db.add_block(
                    block_hash=h,
                    slot=1000,
                    predecessor_hash=pred,
                    block_number=100,
                    cbor_bytes=cbor_data,
                )
            )

        benchmark.pedantic(add_one, rounds=100)
        loop.close()

    def test_volatile_get_block(self, benchmark) -> None:
        """Retrieve a block from a VolatileDB with 1000 blocks."""
        loop = asyncio.new_event_loop()
        db = VolatileDB(db_dir=None)
        cbor_data = os.urandom(4096)
        target_hash = _make_hash(500)

        for i in range(1000):
            h = _make_hash(i)
            pred = _make_hash(i - 1) if i > 0 else b"\x00" * 32
            loop.run_until_complete(
                db.add_block(
                    block_hash=h,
                    slot=i * 10,
                    predecessor_hash=pred,
                    block_number=i,
                    cbor_bytes=cbor_data,
                )
            )

        def get_one():
            return loop.run_until_complete(db.get(target_hash))

        result = benchmark.pedantic(get_one, rounds=100)
        assert result is not None
        loop.close()

    def test_volatile_add_100_blocks(self, benchmark) -> None:
        """Add 100 blocks to the VolatileDB."""
        loop = asyncio.new_event_loop()
        cbor_data = os.urandom(4096)

        def add_batch():
            db = VolatileDB(db_dir=None)
            for i in range(100):
                h = _make_hash(i)
                pred = _make_hash(i - 1) if i > 0 else b"\x00" * 32
                loop.run_until_complete(
                    db.add_block(
                        block_hash=h,
                        slot=i * 10,
                        predecessor_hash=pred,
                        block_number=i,
                        cbor_bytes=cbor_data,
                    )
                )

        benchmark.pedantic(add_batch, rounds=100)
        loop.close()


# ---------------------------------------------------------------------------
# LedgerDB / UTxO benchmarks
# ---------------------------------------------------------------------------

class TestLedgerDB:
    """Benchmark LedgerDB UTxO operations.

    The LedgerDB is the performance-critical component for block
    validation. UTxO lookup and block application must be fast.
    """

    def test_utxo_lookup_hit(self, benchmark) -> None:
        """Look up an existing UTxO by TxIn key."""
        db = LedgerDB(k=100)
        # Seed with 10,000 UTxOs
        entries = [_make_utxo_entry(i) for i in range(10_000)]
        db.apply_block(consumed=[], created=entries, block_slot=0)
        target_key = _make_txin_key(5000)

        result = benchmark.pedantic(db.get_utxo, args=(target_key,), rounds=100)
        assert result is not None

    def test_utxo_lookup_miss(self, benchmark) -> None:
        """Look up a non-existent UTxO (miss path)."""
        db = LedgerDB(k=100)
        entries = [_make_utxo_entry(i) for i in range(10_000)]
        db.apply_block(consumed=[], created=entries, block_slot=0)
        missing_key = _make_txin_key(99999)

        result = benchmark.pedantic(db.get_utxo, args=(missing_key,), rounds=100)
        assert result is None

    def test_apply_block_300_mutations(self, benchmark) -> None:
        """Apply a block with 150 consumed + 150 created UTxOs.

        This is the typical block application workload — roughly 300 total
        UTxO mutations per block on mainnet.
        """
        def apply_one():
            db = LedgerDB(k=100)
            # Seed with initial UTxOs
            initial = [_make_utxo_entry(i) for i in range(1000)]
            db.apply_block(consumed=[], created=initial, block_slot=0)

            # Apply a block: consume 150, create 150 new
            consumed_keys = [_make_txin_key(i) for i in range(150)]
            created = [_make_utxo_entry(1000 + i) for i in range(150)]
            db.apply_block(consumed=consumed_keys, created=created, block_slot=1)

        benchmark.pedantic(apply_one, rounds=100)

    def test_rollback_single_block(self, benchmark) -> None:
        """Roll back a single block."""
        def rollback_one():
            db = LedgerDB(k=100)
            initial = [_make_utxo_entry(i) for i in range(1000)]
            db.apply_block(consumed=[], created=initial, block_slot=0)

            consumed_keys = [_make_txin_key(i) for i in range(50)]
            created = [_make_utxo_entry(1000 + i) for i in range(50)]
            db.apply_block(consumed=consumed_keys, created=created, block_slot=1)

            db.rollback(1)

        benchmark.pedantic(rollback_one, rounds=100)

    def test_utxo_lookup_in_large_set(self, benchmark) -> None:
        """UTxO lookup in a set of 100,000 entries."""
        db = LedgerDB(k=10)
        # Build in batches to avoid huge single-block inserts
        batch_size = 10_000
        for batch in range(10):
            start = batch * batch_size
            entries = [_make_utxo_entry(start + i) for i in range(batch_size)]
            db.apply_block(consumed=[], created=entries, block_slot=batch)

        target_key = _make_txin_key(50_000)

        result = benchmark.pedantic(db.get_utxo, args=(target_key,), rounds=100)
        assert result is not None
