# Multi-Peer Parallel Block-Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download blocks from multiple peers simultaneously by sharing a range_queue across peers, with ChainDB chain selection that handles out-of-order arrival, and a separate nonce worker for sequential accumulation.

**Architecture:** Store-first/nonce-later. All peers dump blocks into VolatileDB in any order. ChainDB chain selection walks the successor map forward from each new block to find the best chain (matching Haskell's `chainSelectionForBlock`). A separate nonce worker walks the chain fragment sequentially to accumulate nonce state.

**Tech Stack:** Python asyncio, existing VolatileDB successor map, existing pipelined block-fetch

**Spec:** `docs/superpowers/specs/2026-03-26-multi-peer-block-fetch-design.md`

---

## File Structure

- **Modify:** `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py` — rewrite chain selection in `add_block` to handle out-of-order arrival
- **Modify:** `packages/vibe-cardano/src/vibe/cardano/network/blockfetch_protocol.py` — add `block_queue` parameter + range lifecycle callbacks to `run_block_fetch_pipelined`
- **Modify:** `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py` — shared queues, split `_on_block`, nonce worker, range tracker, multi-peer wiring
- **Modify:** `packages/vibe-cardano/src/vibe/cardano/network/chainsync_protocol.py` — accept `pipeline_depth` parameter
- **Create:** `tests/unit/test_chaindb_out_of_order.py` — out-of-order chain selection tests
- **Create:** `tests/unit/test_multi_peer_blockfetch.py` — multi-peer integration tests

---

### Task 1: ChainDB chain selection — handle out-of-order block arrival

The prerequisite. Current `add_block` does `block_number > tip.block_number` which breaks when blocks arrive out of order. We need to walk the successor map forward from the new block's **predecessor's all successors** to find the best chain.

**Files:**
- Create: `tests/unit/test_chaindb_out_of_order.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`

- [ ] **Step 1: Write failing tests for out-of-order block arrival**

```python
"""Tests for ChainDB out-of-order block arrival (multi-peer support)."""

from __future__ import annotations

import pytest

from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import VolatileDB


def _make_hash(n: int) -> bytes:
    """Create a deterministic 32-byte hash from an integer."""
    return n.to_bytes(32, "big")


def _make_chaindb(tmp_path, k: int = 10) -> ChainDB:
    """Create a ChainDB with disk-backed stores (matches existing test pattern)."""
    imm = ImmutableDB(base_dir=tmp_path / "immutable", epoch_size=1000)
    vol = VolatileDB(db_dir=tmp_path / "volatile")
    led = LedgerDB(k=k, snapshot_dir=tmp_path / "ledger")
    return ChainDB(immutable_db=imm, volatile_db=vol, ledger_db=led, k=k)


class TestOutOfOrderArrival:
    """Verify ChainDB handles blocks arriving out of chain order."""

    @pytest.mark.asyncio
    async def test_successor_arrives_before_predecessor(self, tmp_path):
        """Block N+2 arrives before N+1. After N+1 arrives, chain extends to N+2."""
        db = _make_chaindb(tmp_path)

        # Block 1 (genesis child)
        r1 = await db.add_block(
            slot=1, block_hash=_make_hash(1), predecessor_hash=_make_hash(0),
            block_number=1, cbor_bytes=b"block1",
        )
        assert r1.adopted

        # Block 3 arrives BEFORE block 2 — predecessor not yet stored
        r3 = await db.add_block(
            slot=3, block_hash=_make_hash(3), predecessor_hash=_make_hash(2),
            block_number=3, cbor_bytes=b"block3",
        )
        # Block 3 stored but chain can't extend (predecessor not reachable)
        assert db._tip.block_number == 1

        # Block 2 arrives — fills the gap
        r2 = await db.add_block(
            slot=2, block_hash=_make_hash(2), predecessor_hash=_make_hash(1),
            block_number=2, cbor_bytes=b"block2",
        )
        # Now chain should extend through 1 -> 2 -> 3
        assert r2.adopted
        assert db._tip.block_number == 3

    @pytest.mark.asyncio
    async def test_multiple_successors_picks_longest(self, tmp_path):
        """Multiple forward paths from a new block — picks the longest."""
        db = _make_chaindb(tmp_path)

        # Block 1
        await db.add_block(
            slot=1, block_hash=_make_hash(1), predecessor_hash=_make_hash(0),
            block_number=1, cbor_bytes=b"block1",
        )

        # Blocks 3, 4, 5 arrive (chain fragment without block 2)
        for i in [3, 4, 5]:
            await db.add_block(
                slot=i, block_hash=_make_hash(i), predecessor_hash=_make_hash(i - 1),
                block_number=i, cbor_bytes=b"block",
            )
        assert db._tip.block_number == 1  # can't extend yet

        # Block 2 fills the gap — chain extends to 5
        await db.add_block(
            slot=2, block_hash=_make_hash(2), predecessor_hash=_make_hash(1),
            block_number=2, cbor_bytes=b"block2",
        )
        assert db._tip.block_number == 5

    @pytest.mark.asyncio
    async def test_unreachable_block_stored_but_no_switch(self, tmp_path):
        """Block whose predecessor is not reachable is stored but tip unchanged."""
        db = _make_chaindb(tmp_path)

        await db.add_block(
            slot=1, block_hash=_make_hash(1), predecessor_hash=_make_hash(0),
            block_number=1, cbor_bytes=b"block1",
        )

        # Block on a different chain (predecessor 99, not stored)
        await db.add_block(
            slot=10, block_hash=_make_hash(10), predecessor_hash=_make_hash(99),
            block_number=10, cbor_bytes=b"orphan",
        )
        assert db._tip.block_number == 1
        assert _make_hash(10) in db.volatile_db._blocks

    @pytest.mark.asyncio
    async def test_sibling_chain_picked_when_longer(self, tmp_path):
        """When gap-filler arrives, evaluate ALL successor paths from predecessor."""
        db = _make_chaindb(tmp_path)

        # Main chain: 0 -> 1
        await db.add_block(
            slot=1, block_hash=_make_hash(1), predecessor_hash=_make_hash(0),
            block_number=1, cbor_bytes=b"block1",
        )

        # Fork A (stored out of order): 1 -> 2a -> 3a
        await db.add_block(
            slot=3, block_hash=_make_hash(30), predecessor_hash=_make_hash(20),
            block_number=3, cbor_bytes=b"block3a",
        )
        await db.add_block(
            slot=2, block_hash=_make_hash(20), predecessor_hash=_make_hash(1),
            block_number=2, cbor_bytes=b"block2a",
        )
        # Should extend to 3a via successor walk
        assert db._tip.block_number == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_chaindb_out_of_order.py -xvs --timeout=10`
Expected: FAIL — current code adopts block 3 as tip immediately when it arrives

- [ ] **Step 3: Implement chain selection with successor map walking**

Add two helper methods to `ChainDB` in `chaindb.py`:

```python
def _best_candidate_from(self, start_hash: bytes) -> tuple[int, bytes]:
    """Walk successor map forward to find the best reachable chain tip.

    Starts from start_hash's predecessor and evaluates ALL successor
    paths (not just paths through start_hash). This ensures sibling
    chains are considered when a gap-filling block arrives.

    Returns (block_number, tip_hash) of the best candidate.

    Haskell ref: Paths.maximalCandidates — evaluates all forward
    paths from the new block's predecessor's successors.
    """
    info = self.volatile_db._block_info.get(start_hash)
    if info is None:
        return (0, start_hash)

    # Start from the predecessor's successors (all of them)
    pred_hash = info.predecessor_hash
    roots = self.volatile_db._successors.get(pred_hash, [start_hash])

    best_bn = 0
    best_hash = start_hash

    # DFS from each root to find the longest path
    for root in roots:
        stack = [root]
        visited: set[bytes] = set()
        while stack:
            h = stack.pop()
            if h in visited:
                continue
            visited.add(h)
            bi = self.volatile_db._block_info.get(h)
            if bi is None:
                continue
            if bi.block_number > best_bn:
                best_bn = bi.block_number
                best_hash = bi.block_hash
            for succ in self.volatile_db._successors.get(h, []):
                stack.append(succ)

    return best_bn, best_hash

def _is_reachable_from_chain(self, block_hash: bytes) -> bool:
    """Walk backward from block_hash through predecessor links.

    Returns True if we reach a block on the current chain fragment
    or the immutable tip.

    Haskell ref: Paths.isReachable / computeReversePath
    """
    h = block_hash
    visited: set[bytes] = set()
    while h:
        if h in visited:
            return False  # cycle
        visited.add(h)
        # On current chain fragment?
        if h in self._fragment_index:
            return True
        # Is it the immutable tip?
        imm_tip_hash = self.immutable_db.get_tip_hash()
        if imm_tip_hash is not None and h == imm_tip_hash:
            return True
        # Walk backward
        info = self.volatile_db._block_info.get(h)
        if info is None:
            return False
        h = info.predecessor_hash
    return False
```

Then replace the chain selection section in `add_block` (lines 547-678) with:

```python
        # --- Chain selection (out-of-order safe) ---
        # Haskell ref: chainSelectionForBlock in ChainSel.hs
        #   1. Store block (done above)
        #   2. Check if block is reachable from current chain
        #   3. Walk successor map forward from predecessor's ALL successors
        #      to find the best candidate tip
        #   4. Switch if candidate is preferred over current tip
        old_tip = self._tip

        # Check reachability first — if block is unreachable, store but don't change
        if not self._is_reachable_from_chain(block_hash):
            await self._maybe_advance_immutable()
            tip_tuple = (
                (old_tip.slot, old_tip.block_hash, old_tip.block_number)
                if old_tip else None
            )
            return ChainSelectionResult(adopted=False, new_tip=tip_tuple)

        # Walk successors forward from this block's predecessor's ALL successors
        candidate_bn, candidate_hash = self._best_candidate_from(block_hash)

        # Determine if the candidate chain is better than current tip
        should_switch = False
        new_vrf = vrf_output or b""
        if old_tip is None:
            should_switch = True
        elif candidate_bn > old_tip.block_number:
            should_switch = True
        elif candidate_bn == old_tip.block_number:
            # VRF tiebreaker: only if the candidate tip IS this block
            if candidate_hash == block_hash and new_vrf and old_tip.vrf_output:
                if new_vrf < old_tip.vrf_output:
                    should_switch = True
                    logger.info(
                        "ChainDB: VRF tiebreak — switching to block %s at slot %d "
                        "(new_vrf=%s < tip_vrf=%s)",
                        block_hash.hex()[:16], slot,
                        new_vrf.hex()[:16], old_tip.vrf_output.hex()[:16],
                    )

        if not should_switch:
            await self._maybe_advance_immutable()
            tip_tuple = (
                (old_tip.slot, old_tip.block_hash, old_tip.block_number)
                if old_tip else None
            )
            return ChainSelectionResult(adopted=False, new_tip=tip_tuple)

        # Switch to the candidate chain
        ct_info = self.volatile_db._block_info[candidate_hash]
        new_tip = _ChainTip(
            slot=ct_info.slot,
            block_hash=candidate_hash,
            block_number=candidate_bn,
            vrf_output=new_vrf if candidate_hash == block_hash else b"",
        )

        rollback_depth = 0
        removed_hashes: set[bytes] = set()
        intersection_hash: bytes | None = None

        if old_tip is not None:
            # Compute diff — handles both fork switches and gap-fill extensions
            rollback_depth, removed_hashes, intersection_hash = self._compute_chain_diff(
                candidate_hash
            )
            if rollback_depth > 0 and intersection_hash is not None:
                from vibe.cardano.network.chainsync import Point
                intersection_info = self.volatile_db._block_info.get(intersection_hash)
                if intersection_info:
                    ipoint = Point(slot=intersection_info.slot, hash=intersection_hash)
                    self._notify_fork_switch(removed_hashes, ipoint)

        self._tip = new_tip
        self.tip_tvar._write(new_tip)

        # Rebuild fragment from the new tip
        header_map = {e.block_hash: e.header_cbor for e in self._chain_fragment}
        header_map[block_hash] = header_cbor
        self._rebuild_fragment_from_tip(candidate_hash, header_map)

        # Update STM TVar (atomic snapshot for nonce worker to read)
        self.fragment_tvar._write(
            (list(self._chain_fragment), dict(self._fragment_index))
        )

        logger.debug(
            "ChainDB: new tip block %s at slot %d, blockNo %d "
            "(rollback=%d, fragment=%d)",
            candidate_hash.hex()[:16], ct_info.slot, candidate_bn,
            rollback_depth, len(self._chain_fragment),
        )

        self._tip_generation += 1
        self.tip_changed.set()
        await self._maybe_advance_immutable()

        return ChainSelectionResult(
            adopted=True,
            new_tip=(ct_info.slot, candidate_hash, candidate_bn),
            rollback_depth=rollback_depth,
            removed_hashes=removed_hashes,
            intersection_hash=intersection_hash,
        )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/test_chaindb_out_of_order.py -xvs --timeout=10`
Expected: All PASS

- [ ] **Step 5: Run existing ChainDB tests for regressions**

Run: `.venv/bin/pytest tests/unit/test_chaindb.py tests/unit/test_chaindb_gaps.py -x -q --timeout=60`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_chaindb_out_of_order.py packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py
git commit -m "feat(m6.14): ChainDB chain selection handles out-of-order block arrival

Prompt: Rewrite add_block chain selection to walk successor map forward
from predecessor's ALL successors (_best_candidate_from) and backward
(_is_reachable_from_chain) per Haskell's chainSelectionForBlock.
Prerequisite for multi-peer block-fetch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Add external block_queue + range lifecycle callbacks to `run_block_fetch_pipelined`

Allow callers to pass a shared `block_queue` and get notified when ranges are sent/completed.

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/network/blockfetch_protocol.py`
- Modify: `tests/unit/test_blockfetch_pipelined.py`

- [ ] **Step 1: Write test for external block_queue**

Add to `tests/unit/test_blockfetch_pipelined.py`:

```python
class TestExternalBlockQueue:
    """Verify run_block_fetch_pipelined works with an externally provided block_queue."""

    @pytest.mark.asyncio
    async def test_external_block_queue_receives_blocks(self):
        """When block_queue is provided, blocks go there and no internal processor runs."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()
        block_queue: asyncio.Queue = asyncio.Queue()
        range_queue.put_nowait((POINT_A, POINT_B))

        stop = asyncio.Event()

        channel.inject(encode_start_batch())
        channel.inject(encode_block(SAMPLE_BLOCK))
        channel.inject(encode_batch_done())

        async def stop_after():
            await asyncio.sleep(0.2)
            stop.set()

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        stopper = asyncio.create_task(stop_after())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=None,
            stop_event=stop,
            block_queue=block_queue,
        )
        await stopper

        assert not block_queue.empty()
        block = block_queue.get_nowait()
        assert block == SAMPLE_BLOCK
```

- [ ] **Step 2: Implement external block_queue + range callbacks**

Update `run_block_fetch_pipelined` signature:

```python
async def run_block_fetch_pipelined(
    channel: object,
    range_queue: asyncio.Queue,
    on_block_received: OnBlockReceived | None = None,
    on_no_blocks: OnNoBlocks | None = None,
    *,
    stop_event: asyncio.Event | None = None,
    max_in_flight: int = 3,
    block_queue_size: int = 200,
    block_queue: asyncio.Queue | None = None,
    on_range_sent: Callable[[tuple], None] | None = None,
    on_range_complete: Callable[[tuple], None] | None = None,
) -> None:
```

At the top, detect external queue:
```python
    _external_queue = block_queue is not None
    if block_queue is None:
        block_queue = asyncio.Queue(maxsize=block_queue_size)
```

In `_sender`, after sending a range, call the callback:
```python
    # Track the range for the caller
    current_range = (point_from, point_to)
    data = encode_request_range(point_from, point_to)
    await channel.send(data)
    in_flight += 1
    if on_range_sent is not None:
        on_range_sent(current_range)
```

In `_receiver`, on BatchDone, signal completion (need to track current range — use a queue of in-flight ranges):
```python
    # Track which range each BatchDone corresponds to
    _range_fifo: list[tuple] = []  # FIFO of sent ranges
```

In `_sender`, append to `_range_fifo` after send. In `_receiver`, on BatchDone, pop from `_range_fifo` and call `on_range_complete`. On NoBlocks, pop and call `on_no_blocks` with the range tuple.

Skip internal processor when external queue is provided:
```python
    sender_task = asyncio.create_task(_sender())
    processor_task = None
    if not _external_queue:
        processor_task = asyncio.create_task(_processor())
```

In finally, only manage processor if created:
```python
    if processor_task is not None:
        if stop_event is not None:
            stop_event.set()
        try:
            await asyncio.wait_for(processor_task, timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            processor_task.cancel()
            try:
                await processor_task
            except asyncio.CancelledError:
                pass
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/pytest tests/unit/test_blockfetch_pipelined.py -xvs --timeout=10`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/network/blockfetch_protocol.py tests/unit/test_blockfetch_pipelined.py
git commit -m "feat(m6.14): external block_queue + range lifecycle callbacks

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Multi-peer wiring — shared queues, split _on_block, nonce worker

The main integration. Restructure `peer_manager.py` so all peers share queues, with a single processor and nonce worker.

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/network/chainsync_protocol.py`
- Create: `tests/unit/test_multi_peer_blockfetch.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for multi-peer parallel block-fetch."""

from __future__ import annotations

import asyncio

import pytest

from vibe.cardano.network.blockfetch import (
    encode_batch_done,
    encode_block,
    encode_no_blocks,
    encode_start_batch,
)
from vibe.cardano.network.chainsync import Point


SAMPLE_BLOCK = b"\xde\xad" * 50


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self._responses: asyncio.Queue[bytes] = asyncio.Queue()

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> bytes:
        return await asyncio.wait_for(self._responses.get(), timeout=0.5)

    def inject(self, data: bytes) -> None:
        self._responses.put_nowait(data)


class TestMultiPeerRangeDistribution:
    @pytest.mark.asyncio
    async def test_two_peers_fetch_different_ranges(self):
        """Two peers pull from same range_queue — each gets unique ranges."""
        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        ch1, ch2 = FakeChannel(), FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()
        block_queue: asyncio.Queue = asyncio.Queue()
        stop = asyncio.Event()

        for i in range(4):
            p = Point(slot=i * 100, hash=b"\x00" * 31 + bytes([i]))
            range_queue.put_nowait((p, p))

        for ch in [ch1, ch2]:
            for _ in range(2):
                ch.inject(encode_start_batch())
                ch.inject(encode_block(SAMPLE_BLOCK))
                ch.inject(encode_batch_done())

        async def stop_after():
            await asyncio.sleep(0.5)
            stop.set()

        stopper = asyncio.create_task(stop_after())
        t1 = asyncio.create_task(run_block_fetch_pipelined(
            ch1, range_queue=range_queue, on_block_received=None,
            stop_event=stop, block_queue=block_queue, max_in_flight=2,
        ))
        t2 = asyncio.create_task(run_block_fetch_pipelined(
            ch2, range_queue=range_queue, on_block_received=None,
            stop_event=stop, block_queue=block_queue, max_in_flight=2,
        ))
        await asyncio.gather(t1, t2, stopper, return_exceptions=True)

        assert len(ch1.sent) >= 1
        assert len(ch2.sent) >= 1
        assert len(ch1.sent) + len(ch2.sent) == 4

        blocks = []
        while not block_queue.empty():
            blocks.append(block_queue.get_nowait())
        assert len(blocks) == 4


class TestRangeRecovery:
    @pytest.mark.asyncio
    async def test_no_blocks_re_enqueues_range(self):
        """NoBlocks response puts the range back on range_queue."""
        from vibe.cardano.node.peer_manager import _RangeTracker

        range_queue: asyncio.Queue = asyncio.Queue()
        tracker = _RangeTracker(range_queue)

        r = (Point(slot=1, hash=b"\x01" * 32), Point(slot=100, hash=b"\x02" * 32))
        tracker.on_no_blocks(r)

        assert not range_queue.empty()
        recovered = range_queue.get_nowait()
        assert recovered == r

    @pytest.mark.asyncio
    async def test_disconnect_re_enqueues_in_flight(self):
        """Peer disconnect puts all in-flight ranges back on range_queue."""
        from vibe.cardano.node.peer_manager import _RangeTracker

        range_queue: asyncio.Queue = asyncio.Queue()
        tracker = _RangeTracker(range_queue)

        r1 = (Point(slot=1, hash=b"\x01" * 32), Point(slot=50, hash=b"\x02" * 32))
        r2 = (Point(slot=51, hash=b"\x03" * 32), Point(slot=100, hash=b"\x04" * 32))
        tracker.on_range_sent("peer1", r1)
        tracker.on_range_sent("peer1", r2)
        tracker.on_peer_disconnect("peer1")

        recovered = []
        while not range_queue.empty():
            recovered.append(range_queue.get_nowait())
        assert len(recovered) == 2
```

- [ ] **Step 2: Restructure peer_manager.py**

Add to `PeerManager.__slots__`:
```python
"_shared_range_queue",
"_shared_block_queue",
"_processor_task",
"_nonce_worker_task",
"_range_tracker",
"_chain_sync_peer",
"_block_notify",
```

Add to `__init__`:
```python
self._shared_range_queue: asyncio.Queue | None = None
self._shared_block_queue: asyncio.Queue | None = None
self._processor_task: asyncio.Task | None = None
self._nonce_worker_task: asyncio.Task | None = None
self._range_tracker: _RangeTracker | None = None
self._chain_sync_peer: str | None = None  # address of the chain-sync peer
self._block_notify = asyncio.Event()  # wake nonce worker on new blocks
```

Add `_RangeTracker` class (at module level):
```python
class _RangeTracker:
    """Track in-flight ranges per peer for re-enqueue on disconnect."""

    def __init__(self, range_queue: asyncio.Queue) -> None:
        self._range_queue = range_queue
        self._in_flight: dict[str, list[tuple]] = {}

    def on_range_sent(self, peer_addr: str, range_tuple: tuple) -> None:
        self._in_flight.setdefault(peer_addr, []).append(range_tuple)

    def on_range_complete(self, peer_addr: str, range_tuple: tuple) -> None:
        if peer_addr in self._in_flight:
            try:
                self._in_flight[peer_addr].remove(range_tuple)
            except ValueError:
                pass

    def on_peer_disconnect(self, peer_addr: str) -> None:
        ranges = self._in_flight.pop(peer_addr, [])
        for r in ranges:
            self._range_queue.put_nowait(r)

    def on_no_blocks(self, range_tuple: tuple) -> None:
        self._range_queue.put_nowait(range_tuple)
```

Add shared queue initialization:
```python
def _ensure_shared_queues(self) -> tuple[asyncio.Queue, asyncio.Queue]:
    if self._shared_range_queue is None:
        self._shared_range_queue = asyncio.Queue()
        self._shared_block_queue = asyncio.Queue(maxsize=500)
        self._range_tracker = _RangeTracker(self._shared_range_queue)
    return self._shared_range_queue, self._shared_block_queue
```

In `_connect_peer`:
- First peer becomes chain-sync peer (`self._chain_sync_peer = peer.address`)
- Only chain-sync peer runs chain-sync → fetch_queue → range_builder → shared range_queue
- ALL peers run `run_block_fetch_pipelined(channel, range_queue=shared_range_queue, block_queue=shared_block_queue, on_range_sent=..., on_range_complete=...)`

Add `_nonce_worker`:
```python
async def _nonce_worker(self, stop_event: asyncio.Event) -> None:
    """Walk chain fragment sequentially, accumulate nonce for new blocks.

    Reads from fragment_tvar (atomic snapshot) — NOT the mutable
    _chain_fragment list — to avoid races with the processor.
    """
    last_bn = 0
    last_hash = b""
    last_generation = 0

    while not stop_event.is_set():
        # Wait for new blocks or timeout
        try:
            await asyncio.wait_for(self._block_notify.wait(), timeout=0.5)
            self._block_notify.clear()
        except TimeoutError:
            pass

        if self._chain_db is None or self._node_kernel is None:
            continue

        # Check if tip has changed
        current_gen = self._chain_db._tip_generation
        if current_gen == last_generation:
            continue
        last_generation = current_gen

        # Read atomic snapshot from TVar
        fragment_snapshot, index_snapshot = self._chain_db.fragment_tvar.read()
        if not fragment_snapshot:
            continue

        # Find where we left off
        start_idx = 0
        if last_hash:
            idx = index_snapshot.get(last_hash)
            if idx is not None:
                start_idx = idx + 1
            else:
                # Fork switch — last_hash no longer in fragment.
                # Use _compute_chain_diff result from ChainSelectionResult
                # to determine the intersection. For simplicity, re-apply
                # nonce from fragment start.
                new_blocks = [
                    (e.slot, e.block_hash, e.predecessor_hash,
                     getattr(e, 'vrf_output', None))
                    for e in fragment_snapshot
                ]
                if new_blocks:
                    self._node_kernel.on_fork_switch(
                        fragment_snapshot[0].predecessor_hash,
                        new_blocks,
                    )
                    last_bn = fragment_snapshot[-1].block_number
                    last_hash = fragment_snapshot[-1].block_hash
                continue

        # Process new blocks sequentially
        for entry in fragment_snapshot[start_idx:]:
            vrf_out = getattr(entry, 'vrf_output', None)
            self._node_kernel.on_block_adopted(
                entry.slot, entry.block_hash,
                entry.predecessor_hash, vrf_out,
            )
            last_bn = entry.block_number
            last_hash = entry.block_hash
```

The processor task sets `self._block_notify.set()` after each successful `add_block`.

Scale PIPELINE_DEPTH in `chainsync_protocol.py`:
- Change `run_chain_sync` to accept a `pipeline_depth` parameter (default 200)
- Caller passes `200 * len(self._config.peers)` from peer_manager

- [ ] **Step 3: Run all tests**

Run: `.venv/bin/pytest tests/ -x -q --timeout=60 --deselect tests/unit/test_chainsync_protocol.py::TestRunChainSync::test_sync_loop_empty_points_uses_origin`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py packages/vibe-cardano/src/vibe/cardano/network/chainsync_protocol.py tests/unit/test_multi_peer_blockfetch.py
git commit -m "feat(m6.14): multi-peer block-fetch with shared queues and nonce worker

Prompt: All peers share range_queue and block_queue. Single processor
stores blocks in any order. Nonce worker reads from fragment_tvar
(atomic snapshot), woken by asyncio.Event. Range tracker re-enqueues
on disconnect/NoBlocks. PIPELINE_DEPTH scales with peer count.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Integration test — devnet soak + Preview benchmark

**Files:**
- No code changes — benchmark runs

- [ ] **Step 1: Devnet soak test (5 minutes)**

```bash
cd /Users/eldermillenial/Cardano/vibe-node
docker compose -f infra/devnet/docker-compose.devnet.yml down -v
docker compose -f infra/devnet/docker-compose.devnet.yml up -d --build
sleep 300
docker compose -f infra/devnet/docker-compose.devnet.yml logs vibe-node 2>&1 | grep -c "Forged block"
docker compose -f infra/devnet/docker-compose.devnet.yml logs vibe-node 2>&1 | grep -c "ERROR"
```

Expected: >20 forged blocks, 0 errors

- [ ] **Step 2: Preview sync benchmark (keep existing volume)**

Do NOT clear the volume. Stop, rebuild, restart:

```bash
cd /Users/eldermillenial/Cardano/vibe-node/infra/preview-sync
docker compose -f docker-compose.preview-sync.yml stop vibe-node
# Add additional Preview peers to VIBE_PEERS if available
docker compose -f docker-compose.preview-sync.yml up -d --build vibe-node
```

Wait 60s for warmup, then measure 30s window:
```bash
sleep 60
docker compose -f docker-compose.preview-sync.yml logs vibe-node 2>&1 | grep "stored" | tail -1
sleep 30
docker compose -f docker-compose.preview-sync.yml logs vibe-node 2>&1 | grep "stored" | tail -1
```

Calculate: `(total_end - total_start) / 30 = bps`
Expected: bps > 340 (baseline at current chain depth)

- [ ] **Step 3: Record results and commit**

Record benchmark results in the plan doc or a devlog entry.
