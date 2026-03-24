# Threading Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the node into 3 OS threads (forge, receive, serve) to eliminate the one-slot forge lag and improve block acceptance at fast slot times.

**Architecture:** The forge loop runs on the main thread using `threading.Event.wait()` for slot timing. Block reception runs on a daemon thread with its own asyncio event loop. Block serving runs on another daemon thread. Shared state (ChainDB, NodeKernel) is protected by read-write locks. A `threading.Event` signals the forge thread when new blocks arrive.

**Tech Stack:** Python 3.14, `threading`, `asyncio`, pytest

**Spec:** `docs/superpowers/specs/2026-03-24-threading-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `packages/vibe-cardano/src/vibe/cardano/core/rwlock.py` | Create | RWLock with context managers for read/write. |
| `packages/vibe-cardano/src/vibe/cardano/node/run.py` | Modify | Thread orchestrator: create 3 threads, shared locks/events, shutdown. |
| `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py` | Modify | Convert from async to sync. Use `threading.Event.wait()`. Acquire locks. |
| `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py` | Modify | Add `add_block_sync()` wrapper. Accept RWLock, wrap public methods. |
| `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py` | Modify | Set `block_received_event` after add_block. |
| `packages/vibe-cardano/src/vibe/cardano/node/kernel.py` | Modify | Accept RWLock, wrap nonce/stake access. |
| `packages/vibe-cardano/src/vibe/cardano/storage/chain_follower.py` | Modify | Acquire read lock when reading fragment. |
| `packages/vibe-cardano/tests/core/test_rwlock.py` | Create | Unit tests for RWLock. |
| `packages/vibe-cardano/tests/node/test_threading.py` | Create | Integration tests for thread startup, forge wake-on-block. |

---

### Task 1: RWLock Implementation

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/core/rwlock.py`
- Create: `packages/vibe-cardano/tests/core/test_rwlock.py`

- [ ] **Step 1: Write failing tests for RWLock**

Create `packages/vibe-cardano/tests/core/test_rwlock.py`:

```python
"""Tests for RWLock — read-write lock with context managers."""

from __future__ import annotations

import threading
import time

from vibe.cardano.core.rwlock import RWLock


class TestRWLockBasic:
    def test_write_lock_exclusive(self):
        lock = RWLock()
        results = []

        def writer(val):
            with lock.write():
                results.append(f"start-{val}")
                time.sleep(0.05)
                results.append(f"end-{val}")

        t1 = threading.Thread(target=writer, args=(1,))
        t2 = threading.Thread(target=writer, args=(2,))
        t1.start()
        time.sleep(0.01)  # ensure t1 gets the lock first
        t2.start()
        t1.join()
        t2.join()
        # Writers should not interleave
        assert results[:2] == ["start-1", "end-1"] or results[:2] == ["start-2", "end-2"]

    def test_concurrent_readers(self):
        lock = RWLock()
        active_readers = []
        max_concurrent = [0]

        def reader():
            with lock.read():
                count = threading.active_count()
                active_readers.append(time.monotonic())
                time.sleep(0.05)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # All 5 readers should have overlapped (started within 50ms of each other)
        times = sorted(active_readers)
        assert times[-1] - times[0] < 0.1  # All started roughly together

    def test_writer_blocks_readers(self):
        lock = RWLock()
        order = []

        def writer():
            with lock.write():
                order.append("write-start")
                time.sleep(0.1)
                order.append("write-end")

        def reader():
            time.sleep(0.02)  # Start after writer
            with lock.read():
                order.append("read")

        wt = threading.Thread(target=writer)
        rt = threading.Thread(target=reader)
        wt.start()
        rt.start()
        wt.join()
        rt.join()
        # Reader should come after writer finishes
        assert order.index("read") > order.index("write-end")

    def test_context_manager_syntax(self):
        lock = RWLock()
        with lock.read():
            pass  # Should not raise
        with lock.write():
            pass  # Should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/vibe-cardano && uv run pytest tests/core/test_rwlock.py -v`
Expected: FAIL — `vibe.cardano.core.rwlock` doesn't exist.

- [ ] **Step 3: Implement RWLock**

Create `packages/vibe-cardano/src/vibe/cardano/core/rwlock.py`:

```python
"""Read-write lock for thread-safe shared state access.

Multiple concurrent readers, exclusive writer. Matches the semantics
of Haskell STM TVars where multiple threads can read atomically but
writes are exclusive.

Usage:
    lock = RWLock()
    with lock.read():
        data = shared_state.read()
    with lock.write():
        shared_state.mutate()
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator


class RWLock:
    """Read-write lock. Multiple concurrent readers, exclusive writer.

    Haskell equivalent: STM TVar (multiple readers, atomic writer).
    Uses a write-preferring policy to prevent writer starvation.
    """

    def __init__(self) -> None:
        self._read_ready = threading.Condition(threading.Lock())
        self._readers: int = 0
        self._writers_waiting: int = 0
        self._writer_active: bool = False

    @contextmanager
    def read(self) -> Generator[None, None, None]:
        """Acquire read lock. Multiple readers can hold simultaneously."""
        with self._read_ready:
            while self._writer_active or self._writers_waiting > 0:
                self._read_ready.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._read_ready:
                self._readers -= 1
                if self._readers == 0:
                    self._read_ready.notify_all()

    @contextmanager
    def write(self) -> Generator[None, None, None]:
        """Acquire write lock. Exclusive access, blocks all readers."""
        with self._read_ready:
            self._writers_waiting += 1
            while self._readers > 0 or self._writer_active:
                self._read_ready.wait()
            self._writers_waiting -= 1
            self._writer_active = True
        try:
            yield
        finally:
            with self._read_ready:
                self._writer_active = False
                self._read_ready.notify_all()
```

Also create `packages/vibe-cardano/src/vibe/cardano/core/__init__.py` if it doesn't exist.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/vibe-cardano && uv run pytest tests/core/test_rwlock.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/core/rwlock.py \
       packages/vibe-cardano/src/vibe/cardano/core/__init__.py \
       packages/vibe-cardano/tests/core/test_rwlock.py
git commit -m "feat: RWLock — read-write lock for threaded ChainDB access

Write-preferring policy prevents writer starvation. Context managers
for clean read/write syntax.

Haskell ref: STM TVar semantics (concurrent reads, exclusive writes)"
```

---

### Task 2: Add Locks to ChainDB and NodeKernel

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chain_follower.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py`

- [ ] **Step 1: Add optional RWLock to ChainDB**

In `chaindb.py`, add to `__init__`:
```python
from vibe.cardano.core.rwlock import RWLock

def __init__(self, ..., lock: RWLock | None = None) -> None:
    ...
    self._lock = lock or RWLock()  # Default no-op if not threaded
```

Add `add_block_sync()` — a synchronous wrapper for the forge thread:
```python
def add_block_sync(self, **kwargs) -> ChainSelectionResult:
    """Synchronous version of add_block for the forge thread."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(self.add_block(**kwargs))
    finally:
        loop.close()
```

Wrap `add_block` body with `self._lock.write()`, `get_current_chain` with `self._lock.read()`, `get_tip` with `self._lock.read()`, `get_block` with `self._lock.read()`, `get_blocks` with `self._lock.read()`.

- [ ] **Step 2: Add optional RWLock to NodeKernel**

In `kernel.py`, add to `__init__`:
```python
from vibe.cardano.core.rwlock import RWLock

def __init__(self, chain_db=None, lock: RWLock | None = None) -> None:
    self._lock = lock or RWLock()
    ...
```

Wrap `epoch_nonce` property with `self._lock.read()`, `on_block_adopted` with `self._lock.write()`, `on_epoch_boundary` with `self._lock.write()`.

- [ ] **Step 3: Add read lock to ChainFollower.instruction()**

In `chain_follower.py`, wrap the fragment read section with `self._chain_db._lock.read()`.

- [ ] **Step 4: Run existing tests to verify nothing breaks**

Run: `cd packages/vibe-cardano && uv run pytest tests/storage/test_chaindb_fragment.py tests/node/test_chain_follower.py -v`
Expected: All PASS (locks are transparent in single-threaded tests).

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py \
       packages/vibe-cardano/src/vibe/cardano/storage/chain_follower.py \
       packages/vibe-cardano/src/vibe/cardano/node/kernel.py
git commit -m "feat: add RWLock to ChainDB and NodeKernel

Thread-safe access to shared state. Read lock for chain fragment
queries, write lock for add_block and nonce updates. Transparent
in single-threaded mode (default RWLock instance)."
```

---

### Task 3: Convert Forge Loop to Synchronous Thread

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py`

This is the core change. The forge loop becomes a regular function (not async) that uses `threading.Event.wait()` for slot timing.

- [ ] **Step 1: Rewrite forge_loop as sync function**

The new signature:
```python
def forge_loop(
    config: NodeConfig,
    slot_config: SlotConfig,
    shutdown_event: threading.Event,
    block_received_event: threading.Event,
    chain_db: Any = None,
    node_kernel: Any = None,
    mempool: Any = None,
) -> None:
```

Key changes from async version:
- `await slot_clock.wait_for_next_slot()` → `block_received_event.wait(timeout=time_to_next_slot)`
- `await chain_db.get_tip()` → read from `chain_db._tip` under read lock
- `await chain_db.add_block(...)` → `chain_db.add_block_sync(...)` under write lock
- `await mempool.get_txs_for_block(...)` → skip mempool for now (empty blocks), or use sync wrapper

The slot timing uses wall-clock math directly:
```python
from vibe.cardano.consensus.slot_arithmetic import slot_to_wall_clock, wall_clock_to_slot

def _time_to_next_slot(slot_config: SlotConfig) -> float:
    current = wall_clock_to_slot(datetime.now(timezone.utc), slot_config)
    next_time = slot_to_wall_clock(current + 1, slot_config)
    return max(0, (next_time - datetime.now(timezone.utc)).total_seconds())
```

The main loop:
```python
while not shutdown_event.is_set():
    # Wait for next slot OR new block (whichever first)
    timeout = _time_to_next_slot(slot_config)
    block_received_event.wait(timeout=timeout)
    block_received_event.clear()

    slot = wall_clock_to_slot(datetime.now(timezone.utc), slot_config)

    # Read tip under read lock
    with chain_db._lock.read():
        tip = chain_db._tip
        if tip and tip.slot >= slot:
            continue
        fragment = chain_db._chain_fragment
        prev_hash = fragment[-1].block_hash if fragment else None
        prev_bn = fragment[-1].block_number if fragment else 0

    # Tick epoch if needed (write lock on kernel)
    current_epoch = slot // config.epoch_length if config.epoch_length > 0 else 0
    with node_kernel._lock.write():
        if current_epoch > node_kernel.current_epoch:
            node_kernel.on_epoch_boundary(current_epoch)
        epoch_nonce = node_kernel.epoch_nonce.value
        # ... read stake distribution ...

    # VRF check (no lock — pure computation)
    proof = check_leadership(slot, vrf_sk, ..., epoch_nonce)
    if proof is None:
        continue

    # Forge block (no lock — pure computation)
    forged = forge_block(...)

    # Write to ChainDB (write lock)
    with chain_db._lock.write():
        result = chain_db.add_block_sync(...)

    if result.adopted:
        with node_kernel._lock.write():
            node_kernel.on_block_adopted(...)
```

- [ ] **Step 2: Run existing tests**

Run: `cd packages/vibe-cardano && uv run pytest tests/node/ tests/forge/ -v --timeout=30 -q`
Expected: Existing tests still pass (forge_loop tests may need updates since signature changed).

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py
git commit -m "feat: convert forge loop to synchronous thread function

Uses threading.Event.wait() for slot timing with block_received_event
wake. Acquires RWLock for ChainDB/kernel access. No async — runs
as a regular OS thread function."
```

---

### Task 4: Update peer_manager to Signal Block Arrival

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py`

- [ ] **Step 1: Add block_received_event parameter**

Add `block_received_event: threading.Event | None = None` to `PeerManager.__init__` and `_connect_and_run`.

After `chain_db.add_block()` succeeds, set the event:
```python
result = await chain_db.add_block(...)
if result.adopted and self._block_received_event is not None:
    self._block_received_event.set()
```

- [ ] **Step 2: Run tests**

Run: `cd packages/vibe-cardano && uv run pytest tests/ -q --timeout=30 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py
git commit -m "feat: peer_manager sets block_received_event on new blocks

Signals the forge thread to wake immediately when a new block
arrives, eliminating one-slot processing lag."
```

---

### Task 5: Rewrite run.py as Thread Orchestrator

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py`

- [ ] **Step 1: Create thread entry point functions**

```python
def _run_receive_thread(
    config, chain_db, node_kernel, block_received_event, shutdown_event,
):
    """Thread 2: block reception (peer_manager + outbound connections)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _receive_main(config, chain_db, node_kernel,
                          block_received_event, shutdown_event)
        )
    finally:
        loop.close()


def _run_serve_thread(
    config, chain_db, mempool, shutdown_event,
):
    """Thread 3: block serving (inbound server + N2C)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _serve_main(config, chain_db, mempool, shutdown_event)
        )
    finally:
        loop.close()
```

`_receive_main` runs peer_manager.start() + snapshot_loop.
`_serve_main` runs N2N inbound server + N2C server.

- [ ] **Step 2: Rewrite run_node as orchestrator**

```python
async def run_node(config):
    # ... create storage, kernel, mempool (same as before) ...

    # Shared threading primitives
    import threading as _threading
    block_received = _threading.Event()
    shutdown = _threading.Event()

    # Install signal handlers on main thread
    import signal
    def _handle_signal(signum, frame):
        shutdown.set()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Thread 2: RECEIVE
    receive_thread = _threading.Thread(
        target=_run_receive_thread,
        args=(config, chain_db, node_kernel, block_received, shutdown),
        daemon=True, name="vibe-receive",
    )

    # Thread 3: SERVE
    serve_thread = _threading.Thread(
        target=_run_serve_thread,
        args=(config, chain_db, mempool, shutdown),
        daemon=True, name="vibe-serve",
    )

    receive_thread.start()
    serve_thread.start()

    # Thread 1: FORGE (runs on main thread)
    if config.is_block_producer:
        forge_loop(
            config, slot_config, shutdown, block_received,
            chain_db, node_kernel, mempool,
        )
    else:
        # Relay-only: just wait for shutdown
        shutdown.wait()

    # Graceful shutdown
    shutdown.set()
    receive_thread.join(timeout=5)
    serve_thread.join(timeout=5)
    chain_db.close()
```

- [ ] **Step 3: Run full test suite**

Run: `cd packages/vibe-cardano && uv run pytest tests/ -q --timeout=30 2>&1 | tail -5`

- [ ] **Step 4: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/run.py
git commit -m "feat: run_node spawns 3 threads (forge, receive, serve)

Forge thread runs on main (signal handling). Receive thread runs
peer_manager with its own asyncio loop. Serve thread runs inbound
server. Shared ChainDB/kernel protected by RWLock."
```

---

### Task 6: Integration Test — Threading Wake-on-Block

**Files:**
- Create: `packages/vibe-cardano/tests/node/test_threading.py`

- [ ] **Step 1: Write test verifying forge wakes on block**

```python
"""Test that the forge thread wakes when a block arrives mid-slot."""

import threading
import time

from vibe.cardano.core.rwlock import RWLock


class TestForgeWakeOnBlock:
    def test_event_wakes_before_timeout(self):
        """threading.Event.wait should return early when set."""
        event = threading.Event()
        woke_early = [False]

        def waiter():
            start = time.monotonic()
            event.wait(timeout=5.0)  # 5 second timeout
            elapsed = time.monotonic() - start
            woke_early[0] = elapsed < 1.0

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        event.set()  # Should wake the waiter
        t.join(timeout=2)
        assert woke_early[0], "Event.wait didn't wake early"

    def test_concurrent_read_write_locks(self):
        """Verify RWLock allows concurrent reads during write gaps."""
        lock = RWLock()
        timeline = []

        def reader(n):
            with lock.read():
                timeline.append(f"R{n}-start")
                time.sleep(0.02)
                timeline.append(f"R{n}-end")

        def writer():
            with lock.write():
                timeline.append("W-start")
                time.sleep(0.05)
                timeline.append("W-end")

        # Start readers, then writer, then more readers
        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=reader, args=(i,)))
        threads.append(threading.Thread(target=writer))
        for i in range(3, 6):
            threads.append(threading.Thread(target=reader, args=(i,)))

        for t in threads:
            t.start()
            time.sleep(0.01)
        for t in threads:
            t.join()

        # Writer should have exclusive access
        w_start = timeline.index("W-start")
        w_end = timeline.index("W-end")
        # No reader events between W-start and W-end
        between = timeline[w_start+1:w_end]
        assert all(not e.startswith("R") for e in between), \
            f"Reader interleaved with writer: {between}"
```

- [ ] **Step 2: Run tests**

Run: `cd packages/vibe-cardano && uv run pytest tests/node/test_threading.py -v`

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/tests/node/test_threading.py
git commit -m "test: threading wake-on-block and RWLock concurrency"
```

---

### Task 7: Integration Test — Devnet Verification

**Files:** None (runtime test)

- [ ] **Step 1: Rebuild and test at 0.05s slots**

```bash
cd /Users/eldermillenial/Cardano/vibe-node
python3 -c "
import json
with open('infra/devnet/genesis/shelley-genesis.json') as f: d = json.load(f)
d['slotLength'] = 0.05
with open('infra/devnet/genesis/shelley-genesis.json', 'w') as f: json.dump(d, f, indent=2); f.write('\n')
"
cd infra/devnet
docker compose -f docker-compose.devnet.yml down -v
docker compose -f docker-compose.devnet.yml build vibe-node
docker compose -f docker-compose.devnet.yml up -d
sleep 120
```

- [ ] **Step 2: Check acceptance rate**

Expected: Significant improvement from 1% at 0.05s. Target: > 10%.

- [ ] **Step 3: Test at 0.2s to verify no regression**

Expected: Still ~33% acceptance.

- [ ] **Step 4: Verify zero errors at both slot times**

```bash
docker logs devnet-haskell-node-1-1 2>&1 | \
  grep -o "UnexpectedSlotNo\|UnexpectedPrevHash\|VRFKeyBadProof\|VRFLeaderValueTooBig" | \
  sort | uniq -c
```

Expected: Zero.

- [ ] **Step 5: Revert slot length and tear down**

```bash
cd /Users/eldermillenial/Cardano/vibe-node
python3 -c "
import json
with open('infra/devnet/genesis/shelley-genesis.json') as f: d = json.load(f)
d['slotLength'] = 0.2
with open('infra/devnet/genesis/shelley-genesis.json', 'w') as f: json.dump(d, f, indent=2); f.write('\n')
"
cd infra/devnet
docker compose -f docker-compose.devnet.yml down -v
```
