"""Pipeline benchmarks — end-to-end block processing paths.

Measures the complete block processing pipeline that determines
how fast vibe-node can keep up with the Haskell chain:

1. ChainDB.add_block (store + chain selection + fragment rebuild)
2. ChainFollower.instruction (how fast we serve headers)
3. Block-fetch get_blocks (serving block bodies)
4. Full receive→store→serve round-trip

These are the bottlenecks identified during devnet testing:
- At 0.2s slots (5 blocks/sec): 35% acceptance
- At 0.1s slots (10 blocks/sec): 7% acceptance
- At 0.05s slots (20 blocks/sec): 1% acceptance

Run: uv run pytest tests/benchmark/test_bench_pipeline.py -v -o 'addopts='
"""

from __future__ import annotations

import asyncio
import hashlib
import struct

import pytest

from vibe.cardano.network.chainsync import Point
from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import VolatileDB


def _hash(n: int) -> bytes:
    """Deterministic 32-byte hash."""
    return hashlib.blake2b(struct.pack(">Q", n), digest_size=32).digest()


def _hdr(n: int) -> list:
    """Dummy header CBOR."""
    return [6, b"header" + n.to_bytes(4, "big")]


def _vrf(n: int) -> bytes:
    """Deterministic 64-byte VRF output."""
    return hashlib.sha512(struct.pack(">Q", n)).digest()


def _block_cbor(n: int) -> bytes:
    """Dummy block CBOR (~850 bytes, similar to devnet empty blocks)."""
    return b"\xd8\x18\x59\x03" + b"\x00" * 850 + n.to_bytes(4, "big")


@pytest.fixture
def chain_db(tmp_path):
    vol = VolatileDB(db_dir=None)
    imm = ImmutableDB(base_dir=tmp_path / "imm")
    led = LedgerDB()
    return ChainDB(imm, vol, led, k=100)


@pytest.fixture
def populated_chain_db(chain_db):
    """ChainDB with 50 blocks already added."""

    async def _populate():
        prev = _hash(0)
        for i in range(1, 51):
            await chain_db.add_block(
                slot=i * 10,
                block_hash=_hash(i),
                predecessor_hash=prev,
                block_number=i,
                cbor_bytes=_block_cbor(i),
                header_cbor=_hdr(i),
                vrf_output=_vrf(i),
            )
            prev = _hash(i)

    asyncio.run(_populate())
    return chain_db


# ---------------------------------------------------------------------------
# Benchmark: ChainDB.add_block (the critical receive path)
# ---------------------------------------------------------------------------


class TestChainDBAddBlock:
    """Benchmark block reception: store + chain selection + fragment update."""

    def test_add_block_extend_tip(self, benchmark, populated_chain_db):
        """Add a block that extends the current tip (common case)."""
        db = populated_chain_db
        counter = [51]

        def add_one():
            i = counter[0]
            counter[0] += 1
            asyncio.run(
                db.add_block(
                    slot=i * 10,
                    block_hash=_hash(i),
                    predecessor_hash=_hash(i - 1),
                    block_number=i,
                    cbor_bytes=_block_cbor(i),
                    header_cbor=_hdr(i),
                    vrf_output=_vrf(i),
                )
            )

        benchmark(add_one)

    def test_add_block_fork_switch(self, benchmark, populated_chain_db):
        """Add a block that causes a fork switch (rollback + rebuild)."""
        db = populated_chain_db
        counter = [51]

        def add_fork():
            i = counter[0]
            counter[0] += 1
            # Fork from block 45 (5 blocks of rollback)
            asyncio.run(
                db.add_block(
                    slot=i * 10 + 5,
                    block_hash=_hash(10000 + i),
                    predecessor_hash=_hash(45),
                    block_number=i,
                    cbor_bytes=_block_cbor(i),
                    header_cbor=_hdr(i),
                    vrf_output=_vrf(10000 + i),
                )
            )

        benchmark(add_fork)

    def test_add_block_same_height_vrf_tiebreak(self, benchmark, populated_chain_db):
        """Add a block at same height — VRF tiebreak comparison."""
        db = populated_chain_db
        counter = [0]

        def add_tiebreak():
            i = counter[0]
            counter[0] += 1
            asyncio.run(
                db.add_block(
                    slot=500 + i,
                    block_hash=_hash(20000 + i),
                    predecessor_hash=_hash(49),
                    block_number=50,
                    cbor_bytes=_block_cbor(50),
                    header_cbor=_hdr(50),
                    vrf_output=_vrf(20000 + i),
                )
            )

        benchmark(add_tiebreak)


# ---------------------------------------------------------------------------
# Benchmark: ChainFollower.instruction (chain-sync serving)
# ---------------------------------------------------------------------------


class TestFollowerInstruction:
    """Benchmark how fast we serve headers to peers."""

    def test_follower_roll_forward(self, benchmark, populated_chain_db):
        """Follower reads next block from chain fragment."""
        db = populated_chain_db

        def serve_one():
            # Create fresh follower per call to avoid event loop binding issues
            f = db.new_follower()
            result = asyncio.run(f.instruction())
            db.close_follower(f.id)
            return result

        benchmark(serve_one)

    def test_follower_catch_up_10_blocks(self, benchmark, populated_chain_db):
        """Follower catches up 10 blocks (common after reconnect)."""
        db = populated_chain_db

        def catch_up():
            f = db.new_follower()
            for _ in range(10):
                asyncio.run(f.instruction())
            db.close_follower(f.id)

        benchmark(catch_up)


# ---------------------------------------------------------------------------
# Benchmark: get_blocks (block-fetch serving)
# ---------------------------------------------------------------------------


class TestBlockFetchServing:
    """Benchmark block body delivery to peers."""

    def test_get_single_block(self, benchmark, populated_chain_db):
        """Fetch a single block by hash."""
        db = populated_chain_db

        def fetch_one():
            return asyncio.run(db.get_block(_hash(25)))

        benchmark(fetch_one)

    def test_get_blocks_range_10(self, benchmark, populated_chain_db):
        """Fetch a range of 10 blocks (typical block-fetch batch)."""
        db = populated_chain_db
        p_from = Point(slot=200, hash=_hash(20))
        p_to = Point(slot=300, hash=_hash(30))

        def fetch_range():
            return asyncio.run(db.get_blocks(p_from, p_to))

        benchmark(fetch_range)


# ---------------------------------------------------------------------------
# Benchmark: Full pipeline round-trip
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """End-to-end: receive block → store → serve header to follower."""

    def test_receive_and_serve(self, benchmark, populated_chain_db):
        """Full path: add_block + follower.instruction."""
        db = populated_chain_db
        follower = db.new_follower()
        # Advance follower to tip first
        for _ in range(50):
            asyncio.run(follower.instruction())

        counter = [51]

        def receive_and_serve():
            i = counter[0]
            counter[0] += 1
            # Receive block
            asyncio.run(
                db.add_block(
                    slot=i * 10,
                    block_hash=_hash(i),
                    predecessor_hash=_hash(i - 1),
                    block_number=i,
                    cbor_bytes=_block_cbor(i),
                    header_cbor=_hdr(i),
                    vrf_output=_vrf(i),
                )
            )
            # Serve to follower
            asyncio.run(follower.instruction())

        benchmark(receive_and_serve)

    def test_under_200ms_target(self, populated_chain_db):
        """Verify full pipeline completes under 200ms (devnet target)."""
        import time

        db = populated_chain_db
        follower = db.new_follower()
        for _ in range(50):
            asyncio.run(follower.instruction())

        times = []
        for i in range(51, 61):
            start = time.perf_counter_ns()
            asyncio.run(
                db.add_block(
                    slot=i * 10,
                    block_hash=_hash(i),
                    predecessor_hash=_hash(i - 1),
                    block_number=i,
                    cbor_bytes=_block_cbor(i),
                    header_cbor=_hdr(i),
                    vrf_output=_vrf(i),
                )
            )
            asyncio.run(follower.instruction())
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            times.append(elapsed_ms)

        avg_ms = sum(times) / len(times)
        max_ms = max(times)
        assert avg_ms < 200, f"Average pipeline time {avg_ms:.1f}ms exceeds 200ms target"
        assert max_ms < 500, f"Max pipeline time {max_ms:.1f}ms exceeds 500ms limit"
