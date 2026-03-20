"""Hypothesis RuleBasedStateMachine for VolatileDB.

Operations: put_block, get_block, get_successors, garbage_collect,
get_max_slot, close_and_reopen, put_duplicate.

Reference model: pure Python dicts mirroring VolatileDB's internal state.
Verify agreement between the real VolatileDB and the reference model at
every step.

Haskell reference:
    The Haskell ouroboros-consensus test suite uses QuickCheck state machine
    testing for VolatileDB (Test.Ouroboros.Storage.VolatileDB.StateMachine).
    This is our Hypothesis equivalent.

Structured for Antithesis compatibility:
    - Deterministic given the same random seed
    - Property invariants are assertions Antithesis can discover violations of
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from hypothesis import settings, HealthCheck
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)
from hypothesis import strategies as st

from vibe.cardano.storage.volatile import BlockInfo, VolatileDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GENESIS_HASH = b"\x00" * 32


def run_async(coro):
    """Run an async coroutine synchronously for use in stateful tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Strategy for 32-byte block hashes (using small ints for readable shrinking)
hash_ids = st.integers(min_value=1, max_value=500)


def make_hash(n: int) -> bytes:
    """Create a deterministic 32-byte hash from an integer."""
    return n.to_bytes(32, "big")


def make_cbor(n: int) -> bytes:
    """Create deterministic fake CBOR bytes for block n."""
    return f"cbor-block-{n}".encode()


# ---------------------------------------------------------------------------
# Reference model
# ---------------------------------------------------------------------------


class VolatileDBModel:
    """Pure Python reference model for VolatileDB.

    Mirrors the VolatileDB's state with simple dicts so we can verify
    agreement after every operation.
    """

    def __init__(self):
        # block_hash -> (BlockInfo, cbor_bytes)
        self.blocks: dict[bytes, tuple[BlockInfo, bytes]] = {}
        # predecessor_hash -> list[successor_hash]
        self.successors: dict[bytes, list[bytes]] = {}

    @property
    def max_slot(self) -> int:
        if not self.blocks:
            return -1
        return max(info.slot for info, _ in self.blocks.values())

    def add_block(
        self,
        block_hash: bytes,
        slot: int,
        predecessor_hash: bytes,
        block_number: int,
        cbor_bytes: bytes,
    ) -> None:
        info = BlockInfo(
            block_hash=block_hash,
            slot=slot,
            predecessor_hash=predecessor_hash,
            block_number=block_number,
        )
        self.blocks[block_hash] = (info, cbor_bytes)

        if predecessor_hash not in self.successors:
            self.successors[predecessor_hash] = []
        if block_hash not in self.successors[predecessor_hash]:
            self.successors[predecessor_hash].append(block_hash)

    def get_block(self, block_hash: bytes) -> bytes | None:
        entry = self.blocks.get(block_hash)
        return entry[1] if entry else None

    def get_successors(self, block_hash: bytes) -> list[bytes]:
        return list(self.successors.get(block_hash, []))

    def gc(self, immutable_tip_slot: int) -> int:
        to_remove = [
            h for h, (info, _) in self.blocks.items()
            if info.slot <= immutable_tip_slot
        ]
        for h in to_remove:
            self._remove_block(h)
        return len(to_remove)

    def _remove_block(self, block_hash: bytes) -> None:
        entry = self.blocks.pop(block_hash, None)
        if entry is None:
            return
        info = entry[0]
        # Clean successor map
        succs = self.successors.get(info.predecessor_hash)
        if succs is not None:
            try:
                succs.remove(block_hash)
            except ValueError:
                pass
            if not succs:
                del self.successors[info.predecessor_hash]


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class VolatileDBStateMachine(RuleBasedStateMachine):
    """State machine test for VolatileDB.

    Maintains a real VolatileDB and a pure Python reference model.
    Every operation is applied to both, and invariants verify agreement.
    """

    def __init__(self):
        super().__init__()
        self._tmpdir = Path(tempfile.mkdtemp())
        self._db = VolatileDB(db_dir=self._tmpdir)
        self._model = VolatileDBModel()
        self._closed = False

        # Track added block hashes and slots for targeted lookups
        self._added_hashes: list[bytes] = []
        self._next_slot = 1

    def teardown(self):
        if not self._closed:
            self._db.close()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # -- Rules --

    @rule(
        hash_id=hash_ids,
        slot_bump=st.integers(min_value=0, max_value=5),
        block_number=st.integers(min_value=0, max_value=10000),
    )
    @precondition(lambda self: not self._closed)
    def put_block(self, hash_id: int, slot_bump: int, block_number: int):
        """Add a random block, verify both real and model agree."""
        block_hash = make_hash(hash_id)

        # Skip if this hash is already in the model (handled by put_duplicate)
        if block_hash in self._model.blocks:
            return

        slot = self._next_slot + slot_bump
        self._next_slot = slot + 1
        cbor = make_cbor(hash_id)

        # Pick predecessor: from existing blocks or genesis
        if self._added_hashes:
            pred = self._added_hashes[-1]
        else:
            pred = GENESIS_HASH

        run_async(self._db.add_block(block_hash, slot, pred, block_number, cbor))
        self._model.add_block(block_hash, slot, pred, block_number, cbor)
        self._added_hashes.append(block_hash)

        # Immediate verification
        result = run_async(self._db.get_block(block_hash))
        assert result == cbor

    @rule(data=st.data())
    @precondition(lambda self: len(self._added_hashes) > 0 and not self._closed)
    def get_block(self, data):
        """Look up a random hash, verify both return same result."""
        idx = data.draw(st.integers(min_value=0, max_value=len(self._added_hashes) - 1))
        block_hash = self._added_hashes[idx]

        real_result = run_async(self._db.get_block(block_hash))
        model_result = self._model.get_block(block_hash)

        assert real_result == model_result, (
            f"get_block mismatch for hash {block_hash.hex()[:16]}: "
            f"real={real_result!r}, model={model_result!r}"
        )

    @rule(data=st.data())
    @precondition(lambda self: len(self._added_hashes) > 0 and not self._closed)
    def get_successors(self, data):
        """Look up successors of a random hash, verify agreement."""
        idx = data.draw(st.integers(min_value=0, max_value=len(self._added_hashes) - 1))
        block_hash = self._added_hashes[idx]

        real_succs = run_async(self._db.get_successors(block_hash))
        model_succs = self._model.get_successors(block_hash)

        assert set(real_succs) == set(model_succs), (
            f"get_successors mismatch for {block_hash.hex()[:16]}: "
            f"real={[h.hex()[:8] for h in real_succs]}, "
            f"model={[h.hex()[:8] for h in model_succs]}"
        )

    @rule(data=st.data())
    @precondition(lambda self: len(self._added_hashes) > 0 and not self._closed)
    def garbage_collect(self, data):
        """GC at a random slot, verify both remove the same blocks."""
        max_slot = self._model.max_slot
        if max_slot < 0:
            return

        gc_slot = data.draw(st.integers(min_value=0, max_value=max_slot + 2))

        real_removed = run_async(self._db.gc(gc_slot))
        model_removed = self._model.gc(gc_slot)

        assert real_removed == model_removed, (
            f"GC at slot {gc_slot}: real removed {real_removed}, "
            f"model removed {model_removed}"
        )

        # Clean up _added_hashes to reflect GC
        self._added_hashes = [
            h for h in self._added_hashes if h in self._model.blocks
        ]

    @rule()
    @precondition(lambda self: not self._closed)
    def get_max_slot(self):
        """Verify both agree on max slot number."""
        real_max = run_async(self._db.get_max_slot())
        model_max = self._model.max_slot

        assert real_max == model_max, (
            f"max_slot mismatch: real={real_max}, model={model_max}"
        )

    @rule()
    @precondition(lambda self: not self._closed)
    def close_and_reopen(self):
        """Close DB, reopen, verify state is preserved (model unchanged)."""
        self._db.close()

        # Reopen: new instance scanning disk to rebuild indices
        self._db = VolatileDB(db_dir=self._tmpdir)

        def parse_header(cbor_bytes: bytes) -> BlockInfo:
            """Reverse-engineer BlockInfo from our fake CBOR format."""
            # Our make_cbor produces "cbor-block-N"
            text = cbor_bytes.decode()
            n = int(text.split("-")[-1])
            block_hash = make_hash(n)
            # Look up the model to get the correct metadata
            entry = self._model.blocks.get(block_hash)
            if entry is None:
                raise ValueError(f"Unknown block {n}")
            return entry[0]  # The BlockInfo

        run_async(self._db.load_from_disk(parse_header))
        self._closed = False

        # Verify block count matches
        assert self._db.block_count == len(self._model.blocks), (
            f"After reopen: real count={self._db.block_count}, "
            f"model count={len(self._model.blocks)}"
        )

        # Verify max slot matches
        real_max = run_async(self._db.get_max_slot())
        assert real_max == self._model.max_slot

    @rule(data=st.data())
    @precondition(lambda self: len(self._added_hashes) > 0 and not self._closed)
    def put_duplicate(self, data):
        """Re-add an existing block, verify idempotent."""
        idx = data.draw(st.integers(min_value=0, max_value=len(self._added_hashes) - 1))
        block_hash = self._added_hashes[idx]

        entry = self._model.blocks.get(block_hash)
        if entry is None:
            # Block was GC'd, skip
            return

        info, cbor = entry
        count_before = self._db.block_count

        run_async(self._db.add_block(
            block_hash, info.slot, info.predecessor_hash,
            info.block_number, cbor,
        ))
        # Model: re-add is idempotent (same hash overwrites same data)
        self._model.add_block(
            block_hash, info.slot, info.predecessor_hash,
            info.block_number, cbor,
        )

        # Block count should not increase
        assert self._db.block_count == count_before, (
            f"Duplicate add changed count: {count_before} -> {self._db.block_count}"
        )

    # -- Invariants (checked after every step) --

    @invariant()
    def block_count_matches(self):
        """len(real.all_blocks) == len(model)."""
        if self._closed:
            return
        assert self._db.block_count == len(self._model.blocks), (
            f"Block count: real={self._db.block_count}, "
            f"model={len(self._model.blocks)}"
        )

    @invariant()
    def max_slot_matches(self):
        """real.max_slot == model.max_slot."""
        if self._closed:
            return
        real_max = run_async(self._db.get_max_slot())
        model_max = self._model.max_slot
        assert real_max == model_max, (
            f"Max slot: real={real_max}, model={model_max}"
        )

    @invariant()
    def successor_map_consistent(self):
        """For every block in the model, successors match."""
        if self._closed:
            return
        for block_hash in self._model.blocks:
            real_succs = run_async(self._db.get_successors(block_hash))
            model_succs = self._model.get_successors(block_hash)
            assert set(real_succs) == set(model_succs), (
                f"Successor mismatch for {block_hash.hex()[:16]}: "
                f"real={[h.hex()[:8] for h in real_succs]}, "
                f"model={[h.hex()[:8] for h in model_succs]}"
            )


# ---------------------------------------------------------------------------
# Pytest wrapper
# ---------------------------------------------------------------------------

TestVolatileDBStateMachine = VolatileDBStateMachine.TestCase
TestVolatileDBStateMachine.settings = settings(
    max_examples=30,
    stateful_step_count=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
