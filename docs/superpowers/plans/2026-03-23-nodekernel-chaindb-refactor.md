# NodeKernel-ChainDB Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace NodeKernel's broken `_chain` list with ChainDB-backed chain fragment and follower management, eliminating UnexpectedPrevHash errors.

**Architecture:** ChainDB becomes the source of truth for the selected chain. It maintains an in-memory chain fragment (last k blocks), owns follower lifecycle, and notifies followers atomically during fork switches. NodeKernel becomes a thin wrapper holding only Praos nonce/delegation/stake state. Callers use `chain_db.add_block()` instead of separate ChainDB + NodeKernel calls.

**Tech Stack:** Python 3.14, asyncio, pytest

**Spec:** `docs/superpowers/specs/2026-03-23-nodekernel-chaindb-refactor-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py` | Modify | Add chain fragment, follower registry, ChainSelectionResult, fork switch detection + notification, header CBOR storage. |
| `packages/vibe-cardano/src/vibe/cardano/node/kernel.py` | Modify | Remove `_chain`, `_hash_index`, `add_block`, followers. Add `_chain_db` ref. Keep nonce/delegation/stake. Simplify `ChainFollower` to read from ChainDB. |
| `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py` | Modify | Remove `node_kernel.add_block()`. Pass header_cbor to `chain_db.add_block()`. |
| `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py` | Modify | Remove `node_kernel.add_block()`. Use `chain_db.add_block()` result. |
| `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py` | Modify | Create/close followers from `chain_db`. Pass `chain_db` for block-fetch. |
| `packages/vibe-cardano/src/vibe/cardano/node/run.py` | Modify | Pass `chain_db` to NodeKernel. Pass `chain_db` to N2N server. |
| `packages/vibe-cardano/tests/node/test_chain_follower.py` | Modify | Rewrite to use ChainDB + VolatileDB fixtures instead of NodeKernel directly. |
| `packages/vibe-cardano/tests/storage/test_chaindb_fragment.py` | Create | Unit tests for chain fragment, fork switch, ChainSelectionResult. |

---

### Task 1: Add ChainSelectionResult and Chain Fragment to ChainDB

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`
- Create: `packages/vibe-cardano/tests/storage/test_chaindb_fragment.py`

This is the foundation. ChainDB gets: `FragmentEntry`, `ChainSelectionResult`, `_chain_fragment`, `_fragment_index`, `tip_changed` event, and `_rebuild_fragment_from_tip()`.

- [ ] **Step 1: Write failing tests**

Create `packages/vibe-cardano/tests/storage/test_chaindb_fragment.py`:

```python
"""Tests for ChainDB chain fragment and ChainSelectionResult."""

from __future__ import annotations

import asyncio

import pytest

from vibe.cardano.storage.chaindb import ChainDB, ChainSelectionResult, FragmentEntry
from vibe.cardano.storage.volatile import VolatileDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB


def _hash(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _hdr(n: int) -> list:
    """Dummy header CBOR for block n."""
    return [6, b"header" + n.to_bytes(4, "big")]


@pytest.fixture
def chain_db(tmp_path):
    """Create a ChainDB with in-memory volatile and minimal immutable/ledger."""
    vol = VolatileDB(db_dir=None)  # in-memory
    imm = ImmutableDB(db_dir=tmp_path / "immutable")
    led = LedgerDB()
    return ChainDB(imm, vol, led, k=10)


class TestChainFragment:
    """Test that add_block maintains the chain fragment correctly."""

    @pytest.mark.asyncio
    async def test_first_block_creates_fragment(self, chain_db):
        result = await chain_db.add_block(
            slot=1, block_hash=_hash(1), predecessor_hash=_hash(0),
            block_number=1, cbor_bytes=b"block1", header_cbor=_hdr(1),
        )
        assert result.adopted is True
        frag = chain_db.get_current_chain()
        assert len(frag) == 1
        assert frag[0].block_hash == _hash(1)

    @pytest.mark.asyncio
    async def test_extending_chain_appends_to_fragment(self, chain_db):
        await chain_db.add_block(
            slot=1, block_hash=_hash(1), predecessor_hash=_hash(0),
            block_number=1, cbor_bytes=b"b1", header_cbor=_hdr(1),
        )
        result = await chain_db.add_block(
            slot=2, block_hash=_hash(2), predecessor_hash=_hash(1),
            block_number=2, cbor_bytes=b"b2", header_cbor=_hdr(2),
        )
        assert result.adopted is True
        assert result.rollback_depth == 0
        frag = chain_db.get_current_chain()
        assert len(frag) == 2
        assert frag[0].block_hash == _hash(1)
        assert frag[1].block_hash == _hash(2)

    @pytest.mark.asyncio
    async def test_worse_block_not_adopted(self, chain_db):
        await chain_db.add_block(
            slot=1, block_hash=_hash(1), predecessor_hash=_hash(0),
            block_number=1, cbor_bytes=b"b1", header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2, block_hash=_hash(2), predecessor_hash=_hash(1),
            block_number=2, cbor_bytes=b"b2", header_cbor=_hdr(2),
        )
        # Block at same height — not adopted (no improvement)
        result = await chain_db.add_block(
            slot=3, block_hash=_hash(99), predecessor_hash=_hash(1),
            block_number=2, cbor_bytes=b"b99", header_cbor=_hdr(99),
        )
        assert result.adopted is False

    @pytest.mark.asyncio
    async def test_fragment_trimmed_to_k(self, chain_db):
        # k=10, add 15 blocks
        prev = _hash(0)
        for i in range(1, 16):
            await chain_db.add_block(
                slot=i, block_hash=_hash(i), predecessor_hash=prev,
                block_number=i, cbor_bytes=f"b{i}".encode(), header_cbor=_hdr(i),
            )
            prev = _hash(i)
        frag = chain_db.get_current_chain()
        assert len(frag) <= 10  # trimmed to k


class TestChainSelectionResult:
    """Test ChainSelectionResult fields for different scenarios."""

    @pytest.mark.asyncio
    async def test_fork_switch_result(self, chain_db):
        # Build chain: 0 → 1 → 2
        await chain_db.add_block(
            slot=1, block_hash=_hash(1), predecessor_hash=_hash(0),
            block_number=1, cbor_bytes=b"b1", header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2, block_hash=_hash(2), predecessor_hash=_hash(1),
            block_number=2, cbor_bytes=b"b2", header_cbor=_hdr(2),
        )
        # Fork: 0 → 1 → 3 (block_number=3, better than 2)
        result = await chain_db.add_block(
            slot=3, block_hash=_hash(3), predecessor_hash=_hash(1),
            block_number=3, cbor_bytes=b"b3", header_cbor=_hdr(3),
        )
        assert result.adopted is True
        assert result.rollback_depth == 1
        assert _hash(2) in result.removed_hashes
        assert result.intersection_hash == _hash(1)

    @pytest.mark.asyncio
    async def test_fragment_correct_after_fork_switch(self, chain_db):
        await chain_db.add_block(
            slot=1, block_hash=_hash(1), predecessor_hash=_hash(0),
            block_number=1, cbor_bytes=b"b1", header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2, block_hash=_hash(2), predecessor_hash=_hash(1),
            block_number=2, cbor_bytes=b"b2", header_cbor=_hdr(2),
        )
        await chain_db.add_block(
            slot=3, block_hash=_hash(3), predecessor_hash=_hash(1),
            block_number=3, cbor_bytes=b"b3", header_cbor=_hdr(3),
        )
        frag = chain_db.get_current_chain()
        hashes = [e.block_hash for e in frag]
        assert _hash(1) in hashes
        assert _hash(3) in hashes
        assert _hash(2) not in hashes  # orphaned
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/vibe-cardano && uv run pytest tests/storage/test_chaindb_fragment.py -v`
Expected: FAIL — `ChainDB.add_block` doesn't accept `header_cbor` or return `ChainSelectionResult`.

- [ ] **Step 3: Implement FragmentEntry, ChainSelectionResult, and chain fragment in ChainDB**

In `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`:

Add imports: `import asyncio` and `from vibe.cardano.network.chainsync import Point, Tip, ORIGIN, PointOrOrigin`

Add dataclasses after `_ChainTip`:

```python
@dataclass(frozen=True, slots=True)
class FragmentEntry:
    """A block in the in-memory chain fragment."""
    slot: int
    block_hash: bytes
    block_number: int
    predecessor_hash: bytes
    header_cbor: Any  # Wrapped header for chain-sync: [era_tag, CBORTag(24, bytes)]


@dataclass(frozen=True, slots=True)
class ChainSelectionResult:
    """Result of adding a block to ChainDB."""
    adopted: bool
    new_tip: tuple[int, bytes, int] | None  # (slot, hash, block_number)
    rollback_depth: int = 0
    removed_hashes: set[bytes] = field(default_factory=set)
    intersection_hash: bytes | None = None
```

Add to `ChainDB.__init__`:
```python
self._chain_fragment: list[FragmentEntry] = []
self._fragment_index: dict[bytes, int] = {}
self.tip_changed: asyncio.Event = asyncio.Event()
```

Add method `get_current_chain`:
```python
def get_current_chain(self) -> list[FragmentEntry]:
    return list(self._chain_fragment)
```

Add method `_rebuild_fragment_from_tip`:
```python
def _rebuild_fragment_from_tip(self, tip_hash: bytes, header_cbor_map: dict[bytes, Any]) -> None:
    """Rebuild chain fragment by walking backward from tip through VolatileDB."""
    fragment: list[FragmentEntry] = []
    h = tip_hash
    while h and h in self.volatile_db._block_info and len(fragment) < self._k:
        info = self.volatile_db._block_info[h]
        hdr = header_cbor_map.get(h)
        fragment.append(FragmentEntry(
            slot=info.slot,
            block_hash=info.block_hash,
            block_number=info.block_number,
            predecessor_hash=info.predecessor_hash,
            header_cbor=hdr,
        ))
        h = info.predecessor_hash
    fragment.reverse()  # oldest first
    self._chain_fragment = fragment
    self._fragment_index = {e.block_hash: i for i, e in enumerate(fragment)}
```

Add method `_compute_chain_diff`:
```python
def _compute_chain_diff(self, new_block_hash: bytes) -> tuple[int, set[bytes], bytes | None]:
    """Compute rollback depth and removed hashes for a fork switch.

    Haskell ref: Paths.isReachable + computeReversePath
    """
    current_hashes = {e.block_hash for e in self._chain_fragment}

    # Walk new block backward to find intersection with current chain
    h = new_block_hash
    new_path: list[bytes] = []
    intersection: bytes | None = None
    while h and h in self.volatile_db._block_info:
        if h in current_hashes:
            intersection = h
            break
        new_path.append(h)
        h = self.volatile_db._block_info[h].predecessor_hash

    if intersection is None:
        return (0, set(), None)

    # Count rollback: blocks on current chain after intersection
    removed = set()
    idx = self._fragment_index.get(intersection)
    if idx is not None:
        for e in self._chain_fragment[idx + 1:]:
            removed.add(e.block_hash)

    return (len(removed), removed, intersection)
```

Modify `add_block` signature and body:
```python
async def add_block(
    self,
    slot: int,
    block_hash: bytes,
    predecessor_hash: bytes,
    block_number: int,
    cbor_bytes: bytes,
    header_cbor: Any = None,
) -> ChainSelectionResult:
```

Replace the chain selection section (lines 168-183) with:
```python
    old_tip = self._tip

    # Chain selection: highest block_number wins
    if self._tip is None or block_number > self._tip.block_number:
        new_tip = _ChainTip(slot=slot, block_hash=block_hash, block_number=block_number)

        rollback_depth = 0
        removed_hashes: set[bytes] = set()
        intersection_hash: bytes | None = None

        if old_tip is not None and predecessor_hash != old_tip.block_hash:
            # Fork switch — compute diff
            rollback_depth, removed_hashes, intersection_hash = (
                self._compute_chain_diff(block_hash)
            )
            # Notify followers BEFORE updating fragment
            if rollback_depth > 0 and intersection_hash is not None:
                intersection_info = self.volatile_db._block_info.get(intersection_hash)
                if intersection_info:
                    ipoint = Point(slot=intersection_info.slot, hash=intersection_hash)
                    self._notify_fork_switch(removed_hashes, ipoint)

        self._tip = new_tip

        # Rebuild or extend fragment
        if rollback_depth > 0 or old_tip is None:
            # Full rebuild needed (fork switch or first block)
            header_map = {e.block_hash: e.header_cbor for e in self._chain_fragment}
            header_map[block_hash] = header_cbor
            self._rebuild_fragment_from_tip(block_hash, header_map)
        else:
            # Simple extend — append to fragment
            entry = FragmentEntry(
                slot=slot, block_hash=block_hash, block_number=block_number,
                predecessor_hash=predecessor_hash, header_cbor=header_cbor,
            )
            idx = len(self._chain_fragment)
            self._chain_fragment.append(entry)
            self._fragment_index[block_hash] = idx
            # Trim to k
            if len(self._chain_fragment) > self._k:
                removed_entry = self._chain_fragment.pop(0)
                self._fragment_index.pop(removed_entry.block_hash, None)
                # Reindex
                self._fragment_index = {
                    e.block_hash: i for i, e in enumerate(self._chain_fragment)
                }

        # Fire tip_changed
        self.tip_changed.set()
        self.tip_changed.clear()

        await self._maybe_advance_immutable()

        return ChainSelectionResult(
            adopted=True,
            new_tip=(slot, block_hash, block_number),
            rollback_depth=rollback_depth,
            removed_hashes=removed_hashes,
            intersection_hash=intersection_hash,
        )
    else:
        # Not adopted — store but don't change tip
        await self._maybe_advance_immutable()
        tip_tuple = (self._tip.slot, self._tip.block_hash, self._tip.block_number) if self._tip else None
        return ChainSelectionResult(adopted=False, new_tip=tip_tuple)
```

Also handle the "below immutable tip" early return — change `return` to `return ChainSelectionResult(adopted=False, new_tip=...)`.

Add follower registry to `__init__`:
```python
self._followers: dict[int, Any] = {}  # Will hold ChainFollower instances
self._next_follower_id: int = 0
```

Add `_notify_fork_switch`:
```python
def _notify_fork_switch(self, removed_hashes: set[bytes], intersection_point: Point) -> None:
    for follower in self._followers.values():
        follower.notify_fork_switch(removed_hashes, intersection_point)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/vibe-cardano && uv run pytest tests/storage/test_chaindb_fragment.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py \
       packages/vibe-cardano/tests/storage/test_chaindb_fragment.py
git commit -m "feat: ChainDB chain fragment, ChainSelectionResult, fork switch detection

ChainDB now maintains an in-memory chain fragment (last k blocks),
returns ChainSelectionResult from add_block, and computes fork diffs.

Haskell ref: cdbChain TVar, chainSelectionForBlock, Paths.isReachable"
```

---

### Task 2: Move ChainFollower to ChainDB

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py`
- Modify: `packages/vibe-cardano/tests/node/test_chain_follower.py`

Move `ChainFollower` from kernel.py to chaindb.py. Rewrite `instruction()` to use ChainDB's `_chain_fragment` and `_fragment_index`. Add `new_follower()` and `close_follower()` to ChainDB.

- [ ] **Step 1: Rewrite test_chain_follower.py to use ChainDB fixtures**

Replace the test file to create ChainDB instances instead of bare NodeKernel:

```python
"""Tests for ChainFollower with ChainDB-backed chain fragment."""

from __future__ import annotations

import asyncio

import pytest

from vibe.cardano.storage.chaindb import ChainDB, ChainFollower
from vibe.cardano.storage.volatile import VolatileDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.network.chainsync import Point, ORIGIN


def _hash(n: int) -> bytes:
    return n.to_bytes(32, "big")

def _hdr(n: int) -> list:
    return [6, b"hdr" + n.to_bytes(4, "big")]


@pytest.fixture
def chain_db(tmp_path):
    vol = VolatileDB(db_dir=None)
    imm = ImmutableDB(db_dir=tmp_path / "imm")
    led = LedgerDB()
    return ChainDB(imm, vol, led, k=10)


class TestFollowerBasic:
    def test_new_follower_at_origin(self, chain_db):
        f = chain_db.new_follower()
        assert f.client_point is ORIGIN or f.client_point == ORIGIN
        assert f._pending_rollback is None

    def test_close_follower(self, chain_db):
        f = chain_db.new_follower()
        assert f.id in chain_db._followers
        chain_db.close_follower(f.id)
        assert f.id not in chain_db._followers

    def test_multiple_followers(self, chain_db):
        f1 = chain_db.new_follower()
        f2 = chain_db.new_follower()
        assert f1.id != f2.id


class TestFollowerInstruction:
    @pytest.mark.asyncio
    async def test_await_on_empty(self, chain_db):
        f = chain_db.new_follower()
        action, _, _, _ = await asyncio.wait_for(f.instruction(), timeout=0.3)
        assert action == "await"

    @pytest.mark.asyncio
    async def test_roll_forward(self, chain_db):
        f = chain_db.new_follower()
        await chain_db.add_block(
            slot=1, block_hash=_hash(1), predecessor_hash=_hash(0),
            block_number=1, cbor_bytes=b"b1", header_cbor=_hdr(1),
        )
        action, header, point, tip = await f.instruction()
        assert action == "roll_forward"
        assert point == Point(slot=1, hash=_hash(1))
        assert header == _hdr(1)

    @pytest.mark.asyncio
    async def test_advances_through_chain(self, chain_db):
        f = chain_db.new_follower()
        await chain_db.add_block(
            slot=1, block_hash=_hash(1), predecessor_hash=_hash(0),
            block_number=1, cbor_bytes=b"b1", header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2, block_hash=_hash(2), predecessor_hash=_hash(1),
            block_number=2, cbor_bytes=b"b2", header_cbor=_hdr(2),
        )
        a1, _, p1, _ = await f.instruction()
        assert p1 == Point(slot=1, hash=_hash(1))
        a2, _, p2, _ = await f.instruction()
        assert p2 == Point(slot=2, hash=_hash(2))


class TestFollowerForkSwitch:
    @pytest.mark.asyncio
    async def test_rollback_on_fork(self, chain_db):
        f = chain_db.new_follower()
        # Chain: 1 → 2
        await chain_db.add_block(
            slot=1, block_hash=_hash(1), predecessor_hash=_hash(0),
            block_number=1, cbor_bytes=b"b1", header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2, block_hash=_hash(2), predecessor_hash=_hash(1),
            block_number=2, cbor_bytes=b"b2", header_cbor=_hdr(2),
        )
        # Follower reads both
        await f.instruction()  # block 1
        await f.instruction()  # block 2
        # Fork: 1 → 3 (better, block_number=3)
        await chain_db.add_block(
            slot=3, block_hash=_hash(3), predecessor_hash=_hash(1),
            block_number=3, cbor_bytes=b"b3", header_cbor=_hdr(3),
        )
        # Should rollback to block 1
        action, _, point, _ = await f.instruction()
        assert action == "roll_backward"
        assert point == Point(slot=1, hash=_hash(1))
        # Then roll forward with block 3
        action2, _, point2, _ = await f.instruction()
        assert action2 == "roll_forward"
        assert point2 == Point(slot=3, hash=_hash(3))

    @pytest.mark.asyncio
    async def test_unaffected_follower_continues(self, chain_db):
        f_affected = chain_db.new_follower()
        f_safe = chain_db.new_follower()
        await chain_db.add_block(
            slot=1, block_hash=_hash(1), predecessor_hash=_hash(0),
            block_number=1, cbor_bytes=b"b1", header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2, block_hash=_hash(2), predecessor_hash=_hash(1),
            block_number=2, cbor_bytes=b"b2", header_cbor=_hdr(2),
        )
        await f_affected.instruction()  # block 1
        await f_affected.instruction()  # block 2
        await f_safe.instruction()      # block 1 only
        # Fork switch
        await chain_db.add_block(
            slot=3, block_hash=_hash(3), predecessor_hash=_hash(1),
            block_number=3, cbor_bytes=b"b3", header_cbor=_hdr(3),
        )
        a_aff, _, _, _ = await f_affected.instruction()
        assert a_aff == "roll_backward"
        a_safe, _, p_safe, _ = await f_safe.instruction()
        assert a_safe == "roll_forward"
        assert p_safe == Point(slot=3, hash=_hash(3))
```

- [ ] **Step 2: Move ChainFollower class to chaindb.py**

Move the `ChainFollower` class from `kernel.py` to `chaindb.py`. Update it to reference `self._chain_db` (a ChainDB instance) instead of `self._kernel` (a NodeKernel). Update `instruction()` to read `_chain_db._chain_fragment` and `_chain_db._fragment_index`.

Add `new_follower()` and `close_follower()` methods to ChainDB (same pattern as was on NodeKernel).

Add `get_tip_as_tip()` to ChainDB for the Tip object followers need:
```python
def get_tip_as_tip(self) -> Tip:
    if self._tip:
        return Tip(point=Point(slot=self._tip.slot, hash=self._tip.block_hash),
                    block_number=self._tip.block_number)
    return Tip(point=Point(slot=0, hash=b"\x00" * 32), block_number=0)
```

- [ ] **Step 3: Run tests**

Run: `cd packages/vibe-cardano && uv run pytest tests/node/test_chain_follower.py tests/storage/test_chaindb_fragment.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py \
       packages/vibe-cardano/src/vibe/cardano/node/kernel.py \
       packages/vibe-cardano/tests/node/test_chain_follower.py
git commit -m "refactor: move ChainFollower from NodeKernel to ChainDB

ChainFollower now reads the chain fragment from ChainDB instead of
NodeKernel's _chain list. Followers are created/closed via ChainDB.

Haskell ref: ChainDB.newFollower, Follower.instructionSTM"
```

---

### Task 3: Strip NodeKernel Down

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py`

Remove from NodeKernel: `_chain`, `_hash_index`, `add_block()`, `_followers`, `new_follower()`, `close_follower()`, `_notify_fork_switch()`, `ChainProvider`/`BlockProvider` interface implementations (`next_block`, `find_intersect`, `get_blocks`, `get_tip`).

Add: `_chain_db` reference, `on_block_adopted(slot, prev_hash, vrf_output)` for Praos nonce updates.

- [ ] **Step 1: Remove chain/follower code from NodeKernel**

Remove:
- `_chain`, `_hash_index` from `__init__`
- `_followers`, `_next_follower_id` from `__init__`
- `add_block()` method entirely
- `new_follower()`, `close_follower()`, `_notify_fork_switch()` methods
- `next_block()`, `find_intersect()`, `get_blocks()`, `get_tip()` methods
- `_genesis_tip()` method
- `ChainProvider` and `BlockProvider` from class bases
- `BlockEntry` class (replaced by `FragmentEntry` in chaindb.py)
- The `ChainFollower` class (moved to chaindb.py in Task 2)

Add:
```python
def __init__(self, chain_db: Any = None) -> None:
    self._chain_db = chain_db
    # ... keep all nonce/delegation/stake state ...
```

Add `on_block_adopted`:
```python
def on_block_adopted(self, slot: int, prev_hash: bytes, vrf_output: bytes | None) -> None:
    """Update Praos chain-dependent state after a block is adopted.

    Called by peer_manager and forge_loop after chain_db.add_block returns adopted=True.
    """
    epoch_len = self._epoch_length
    if epoch_len <= 0:
        return
    block_epoch = slot // epoch_len
    if block_epoch > self._current_epoch:
        self.on_epoch_boundary(block_epoch)
    if vrf_output:
        self.on_block(slot, prev_hash, vrf_output)
```

- [ ] **Step 2: Run existing tests to check what breaks**

Run: `cd packages/vibe-cardano && uv run pytest tests/ -x -q --timeout=30 2>&1 | tail -20`

Fix any import errors (tests that reference `NodeKernel.add_block` or `BlockEntry` from kernel.py).

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/kernel.py
git commit -m "refactor: strip NodeKernel to nonce/delegation/stake state only

NodeKernel no longer maintains _chain or followers. ChainDB is now
the source of truth. NodeKernel.on_block_adopted handles Praos nonce
updates.

Haskell ref: NodeKernel holds ChainDB reference, delegates chain ops"
```

---

### Task 4: Update peer_manager to Use ChainDB Directly

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py`

Replace the dual `chain_db.add_block()` + `node_kernel.add_block()` pattern with a single `chain_db.add_block()` call that includes `header_cbor`, then call `node_kernel.on_block_adopted()` for nonce updates.

- [ ] **Step 1: Update block storage section (around line 549-587)**

Replace:
```python
# --- Store in ChainDB ---
if chain_db is not None:
    await chain_db.add_block(
        slot=slot, block_hash=block_hash,
        predecessor_hash=prev_hash,
        block_number=block_number, cbor_bytes=raw_block,
    )

# --- Add to NodeKernel for serving to peers ---
if node_kernel is not None:
    node_kernel.add_block(
        slot=slot, block_hash=block_hash,
        block_number=block_number,
        header_cbor=[...],
        block_cbor=raw_block,
        predecessor_hash=prev_hash,
    )

    # --- Praos chain-dependent state update ---
    epoch_len = node_kernel.epoch_length
    ...
```

With:
```python
# --- Store in ChainDB (includes chain selection + follower notification) ---
if chain_db is not None:
    header_cbor_wrapped = [
        max(0, era_tag - 1) if era_tag >= 2 else 0,
        cbor2.CBORTag(24, hdr_cbor),
    ]
    result = await chain_db.add_block(
        slot=slot, block_hash=block_hash,
        predecessor_hash=prev_hash,
        block_number=block_number, cbor_bytes=raw_block,
        header_cbor=header_cbor_wrapped,
    )

    # --- Praos chain-dependent state update (only if adopted) ---
    if result.adopted and node_kernel is not None:
        vrf_out = getattr(hdr, 'vrf_output', None)
        node_kernel.on_block_adopted(slot, prev_hash, vrf_out)
```

- [ ] **Step 2: Run tests**

Run: `cd packages/vibe-cardano && uv run pytest tests/ -x -q --timeout=30 2>&1 | tail -20`

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py
git commit -m "refactor: peer_manager uses chain_db.add_block directly

Single call to chain_db.add_block replaces dual ChainDB + NodeKernel
calls. Praos nonce updates via node_kernel.on_block_adopted."
```

---

### Task 5: Update forge_loop to Use ChainDB Directly

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py`

Replace the `node_kernel.add_block(..., is_forged=True)` call with `chain_db.add_block()` and check `result.adopted`.

- [ ] **Step 1: Update forged block storage (around line 280-320)**

Replace the `node_kernel.add_block(...)` section with:
```python
# Add to ChainDB (includes chain selection + follower notification)
if chain_db is not None:
    result = await chain_db.add_block(
        slot=forged.block.slot,
        block_hash=forged.block.block_hash,
        predecessor_hash=forged_predecessor,
        block_number=forged.block.block_number,
        cbor_bytes=forged.cbor,
        header_cbor=[6, cbor2.CBORTag(24, forged.block.header_cbor)],
    )
    if not result.adopted:
        logger.info(
            "Forged block #%d at slot %d orphaned (tip changed)",
            forged.block.block_number, forged.block.slot,
        )
        prev_header_hash = forged_predecessor
        prev_block_number = forged.block.block_number - 1
        continue

    # Praos nonce update for our own forged block
    if node_kernel is not None:
        node_kernel.on_block_adopted(
            forged.block.slot, forged_predecessor, proof.vrf_output,
        )
```

Remove the old `node_kernel.add_block(...)` call and the separate `chain_db.add_block(...)` call above it (consolidate into single call).

- [ ] **Step 2: Run tests**

Run: `cd packages/vibe-cardano && uv run pytest tests/forge/ tests/node/ -x -q --timeout=30`

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py
git commit -m "refactor: forge_loop uses chain_db.add_block directly

Single call replaces dual ChainDB + NodeKernel. Checks result.adopted
to detect orphaned forged blocks."
```

---

### Task 6: Update inbound_server and run.py Wiring

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py`

Wire `chain_db` through to inbound_server. Create/close followers from ChainDB. Pass ChainDB for block-fetch.

- [ ] **Step 1: Update run.py to pass chain_db to NodeKernel and N2N server**

In `run.py`:
```python
# Change NodeKernel creation:
node_kernel = NodeKernel(chain_db=chain_db)

# Change N2N server call to include chain_db:
_run_n2n_server(
    config.host, config.port, config.network_magic,
    node_kernel, mempool, shutdown_event,
    chain_db=chain_db,
)
```

- [ ] **Step 2: Update inbound_server.py**

Add `chain_db` parameter to `run_n2n_server`:
```python
async def run_n2n_server(
    host, port, network_magic, node_kernel, mempool, shutdown_event,
    chain_db=None,
):
```

In `handle_connection`, create follower from chain_db:
```python
follower = None
if chain_db is not None:
    follower = chain_db.new_follower()

# Chain-sync server uses follower
if follower is not None:
    asyncio.create_task(
        _safe_server(
            run_chain_sync_server(
                channels[CHAIN_SYNC_N2N_ID],
                follower=follower,
                stop_event=stop,
            ),
            "chain-sync",
        ),
    )

# Block-fetch server uses chain_db for block lookup
if chain_db is not None:
    asyncio.create_task(
        _safe_server(
            run_block_fetch_server(
                channels[BLOCK_FETCH_N2N_ID],
                block_provider=chain_db,  # ChainDB has get_block()
                stop_event=stop,
            ),
            "block-fetch",
        ),
    )
```

In `finally` block:
```python
if follower is not None and chain_db is not None:
    chain_db.close_follower(follower.id)
```

- [ ] **Step 3: Run all tests**

Run: `cd packages/vibe-cardano && uv run pytest tests/ -x -q --timeout=30 2>&1 | tail -20`

- [ ] **Step 4: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/run.py \
       packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py
git commit -m "refactor: wire chain_db through N2N server and inbound connections

Followers created from chain_db. Block-fetch uses chain_db for lookups.
NodeKernel receives chain_db reference at init."
```

---

### Task 7: Integration Test — Devnet Verification

**Files:** None (runtime test)

- [ ] **Step 1: Rebuild vibe-node container**

```bash
cd infra/devnet
docker compose -f docker-compose.devnet.yml down -v
docker compose -f docker-compose.devnet.yml build vibe-node
```

- [ ] **Step 2: Start devnet and wait**

```bash
docker compose -f docker-compose.devnet.yml up -d
sleep 120
```

- [ ] **Step 3: Check for zero errors**

```bash
docker logs devnet-haskell-node-1-1 2>&1 | \
  grep -i "VRFLeaderValueTooBig\|VRFKeyBadProof\|UnexpectedPrevHash\|InvalidBlock\|HeaderError" | \
  grep -v "Configuration\|ErrorPolicy\|ConnectionError\|ConnectError"
```

Expected: No output.

- [ ] **Step 4: Verify forged blocks accepted**

```bash
HASKELL_SLOTS=$(docker logs devnet-haskell-node-1-1 2>&1 | \
  grep "AddedToCurrentChain" | sed 's/.*slot //' | sed 's/[^0-9].*//')
VIBE_SLOTS=$(docker logs devnet-vibe-node-1 2>&1 | \
  grep "Forged block" | sed 's/.*slot //' | sed 's/ .*//' | sort -un)
accepted=0; total=0
while read -r slot; do
    [ -z "$slot" ] && continue
    total=$((total+1))
    if echo "$HASKELL_SLOTS" | grep -qx "$slot"; then
        accepted=$((accepted+1))
        echo "  Slot $slot: ACCEPTED"
    fi
done <<< "$VIBE_SLOTS"
echo "RESULT: $accepted/$total forged blocks accepted"
```

Expected: Majority accepted. Zero validation errors.

- [ ] **Step 5: Tear down**

```bash
docker compose -f docker-compose.devnet.yml down -v
```
