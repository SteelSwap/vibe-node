"""Hypothesis RuleBasedStateMachine for ImmutableDB.

Operations: append, read_by_slot, iterate, delete_after, close, reopen.
Reference model: simple list of (slot, hash, data) tuples.
Verify agreement between the ImmutableDB and the reference model at every step.

Haskell reference:
    The Haskell ouroboros-consensus test suite uses QuickCheck state machine
    testing for ImmutableDB (Test.Ouroboros.Storage.ImmutableDB.StateMachine).
    This is our Hypothesis equivalent.

Structured for Antithesis compatibility:
    - Deterministic given the same random seed
    - Property invariants are assertions Antithesis can discover violations of
"""

from __future__ import annotations

import asyncio
import shutil
import struct
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
)

from vibe.cardano.storage.immutable import (
    ImmutableDB,
)


def make_hash(n: int) -> bytes:
    """Create a deterministic 32-byte hash from an integer."""
    return n.to_bytes(32, "big")


def run_async(coro):
    """Run an async coroutine synchronously for use in stateful tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ImmutableDBStateMachine(RuleBasedStateMachine):
    """State machine test for ImmutableDB.

    Reference model: a sorted list of (slot, hash, data) tuples.
    The ImmutableDB under test must agree with the reference at every step.
    """

    def __init__(self):
        super().__init__()
        self._tmpdir = Path(tempfile.mkdtemp())
        self._db = ImmutableDB(str(self._tmpdir), epoch_size=20)
        self._model: list[tuple[int, bytes, bytes]] = []
        self._next_slot = 1
        self._closed = False

    def teardown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # -- Operations --

    @rule(size=st.integers(min_value=10, max_value=200))
    def append_block(self, size: int):
        """Append a block at the next sequential slot."""
        if self._closed:
            return

        slot = self._next_slot
        block_hash = make_hash(slot)
        data = bytes([slot % 256]) * size

        run_async(self._db.append_block(slot, block_hash, data))
        self._model.append((slot, block_hash, data))
        self._next_slot = slot + 1

    @rule(
        gap=st.integers(min_value=2, max_value=10), size=st.integers(min_value=10, max_value=100)
    )
    def append_with_gap(self, gap: int, size: int):
        """Append a block with a slot gap (simulates empty slots)."""
        if self._closed:
            return

        slot = self._next_slot + gap
        block_hash = make_hash(slot)
        data = bytes([slot % 256]) * size

        run_async(self._db.append_block(slot, block_hash, data))
        self._model.append((slot, block_hash, data))
        self._next_slot = slot + 1

    @rule()
    @precondition(lambda self: len(self._model) > 0 and not self._closed)
    def read_by_slot(self):
        """Read a block by slot and verify it matches the model."""
        # Pick the last block (guaranteed to exist)
        slot, block_hash, expected_data = self._model[-1]
        result = run_async(self._db.get_block(block_hash))
        assert result == expected_data, (
            f"Data mismatch at slot {slot}: "
            f"expected {len(expected_data)} bytes, got {len(result) if result else 'None'}"
        )

    @rule()
    @precondition(lambda self: len(self._model) > 0 and not self._closed)
    def read_random_block(self):
        """Read a random block from the model and verify."""
        import random

        idx = random.randrange(len(self._model))
        slot, block_hash, expected_data = self._model[idx]
        result = run_async(self._db.get_block(block_hash))
        assert result == expected_data

    @rule()
    @precondition(lambda self: len(self._model) > 0 and not self._closed)
    def iterate_all(self):
        """Iterate all blocks and verify order and content match model."""
        it = self._db.stream(start_slot=0)
        collected = []
        while it.has_next():
            key, data = it.next()
            slot = struct.unpack(">Q", key[:8])[0]
            collected.append((slot, data))
        it.close()

        assert len(collected) == len(
            self._model
        ), f"Block count mismatch: DB has {len(collected)}, model has {len(self._model)}"

        for (db_slot, db_data), (model_slot, _, model_data) in zip(collected, self._model):
            assert db_slot == model_slot, f"Slot mismatch: {db_slot} vs {model_slot}"
            assert db_data == model_data, f"Data mismatch at slot {db_slot}"

    @rule()
    @precondition(lambda self: len(self._model) >= 2 and not self._closed)
    def delete_after(self):
        """Delete blocks after the midpoint slot."""
        mid = len(self._model) // 2
        cutoff_slot = self._model[mid][0]

        run_async(self._db.delete_after(cutoff_slot))

        # Update model: keep only blocks with slot <= cutoff
        self._model = [(s, h, d) for s, h, d in self._model if s <= cutoff_slot]

        # Update next_slot
        if self._model:
            self._next_slot = self._model[-1][0] + 1
        else:
            self._next_slot = 1

    @rule()
    @precondition(lambda self: not self._closed)
    def close_and_reopen(self):
        """Close the DB and reopen it, verifying recovery."""
        self._db.close()
        # Reopen
        self._db = ImmutableDB(str(self._tmpdir), epoch_size=20)
        self._closed = False

        # Verify tip matches model
        if self._model:
            expected_tip_slot = self._model[-1][0]
            assert self._db.get_tip_slot() == expected_tip_slot
        else:
            assert self._db.get_tip_slot() is None

    # -- Invariants --

    @invariant()
    def tip_matches_model(self):
        """The DB tip always matches the model's last entry."""
        if self._closed:
            return
        if self._model:
            expected_slot = self._model[-1][0]
            expected_hash = self._model[-1][1]
            assert self._db.get_tip_slot() == expected_slot
            assert self._db.get_tip_hash() == expected_hash
        else:
            assert self._db.get_tip_slot() is None

    @invariant()
    def block_count_matches_model(self):
        """The number of blocks in hash index matches the model."""
        if self._closed:
            return
        assert len(self._db._hash_index) == len(
            self._model
        ), f"Hash index has {len(self._db._hash_index)} entries, model has {len(self._model)}"


# Wrap as a pytest test with reasonable settings
TestImmutableDBStateMachine = ImmutableDBStateMachine.TestCase
TestImmutableDBStateMachine.settings = settings(
    max_examples=30,
    stateful_step_count=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
