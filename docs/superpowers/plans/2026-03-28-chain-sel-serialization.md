# Chain Selection Serialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serialize all chain selection through a single dedicated thread, eliminating the cross-thread data races that cause VRFKeyBadProof and fragment corruption.

**Architecture:** A dedicated "vibe-chainsel" thread runs a `while True` loop pulling `BlockToAdd` entries from a `queue.Queue`. The public `add_block()` becomes synchronous (enqueue + wait on `threading.Event`). Callers on async event loops use `add_block_async()` which wraps via `asyncio.to_thread`.

**Tech Stack:** Python stdlib `queue.Queue`, `threading.Thread`, `threading.Event`, `threading.Lock`, `asyncio.to_thread`

**Spec:** `docs/superpowers/specs/2026-03-28-chain-sel-serialization-design.md`

---

### Task 1: Add BlockToAdd dataclass and queue infrastructure to ChainDB

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`
- Test: `packages/vibe-cardano/tests/storage/test_chaindb.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/vibe-cardano/tests/storage/test_chaindb.py`:

```python
def test_block_to_add_dataclass():
    """BlockToAdd holds block params + signaling fields."""
    import threading
    from vibe.cardano.storage.chaindb import BlockToAdd

    entry = BlockToAdd(
        slot=100,
        block_hash=b"\x01" * 32,
        predecessor_hash=b"\x00" * 32,
        block_number=5,
        cbor_bytes=b"\xff" * 64,
        header_cbor=None,
        vrf_output=None,
    )
    assert entry.slot == 100
    assert entry.result is None
    assert entry.error is None
    assert isinstance(entry.done, threading.Event)
    assert not entry.done.is_set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/vibe-cardano && python -m pytest tests/storage/test_chaindb.py::test_block_to_add_dataclass -v`
Expected: FAIL with `ImportError: cannot import name 'BlockToAdd'`

- [ ] **Step 3: Implement BlockToAdd and add queue to ChainDB.__init__**

In `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`, add after the `ChainSelectionResult` class (around line 107):

```python
@dataclass
class BlockToAdd:
    """Queue entry for the chain selection runner.

    Holds all parameters for add_block plus signaling fields for the
    caller to wait on the result.

    Haskell ref: BlockToAdd in ChainDB.Impl.Types
    """

    slot: int
    block_hash: bytes
    predecessor_hash: bytes
    block_number: int
    cbor_bytes: bytes
    header_cbor: Any = None
    vrf_output: bytes | None = None
    result: ChainSelectionResult | None = field(default=None, init=False)
    error: Exception | None = field(default=None, init=False)
    done: threading.Event = field(default_factory=threading.Event, init=False)
```

Update `__all__` to include `"BlockToAdd"`.

In `ChainDB.__init__`, add after the `praos_nonce_tvar` line (around line 177):

```python
        # Chain selection queue — serializes all add_block processing
        # through a single thread. Haskell ref: cdbChainSelQueue (TBQueue)
        import queue
        self._chain_sel_queue: queue.Queue[BlockToAdd | None] = queue.Queue()
        self._chain_sel_thread: threading.Thread | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/vibe-cardano && python -m pytest tests/storage/test_chaindb.py::test_block_to_add_dataclass -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py packages/vibe-cardano/tests/storage/test_chaindb.py
git commit -m "feat(chainsel): add BlockToAdd dataclass and queue infrastructure"
```

---

### Task 2: Add followers lock for thread-safe follower management

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`
- Test: `packages/vibe-cardano/tests/storage/test_chaindb.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/vibe-cardano/tests/storage/test_chaindb.py`:

```python
def test_followers_lock_exists(tmp_path):
    """ChainDB has a _followers_lock for thread-safe follower access."""
    db = _make_chaindb(tmp_path)
    assert hasattr(db, '_followers_lock')
    import threading
    assert isinstance(db._followers_lock, threading.Lock)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/vibe-cardano && python -m pytest tests/storage/test_chaindb.py::test_followers_lock_exists -v`
Expected: FAIL with `AssertionError`

- [ ] **Step 3: Add _followers_lock and protect all follower dict access**

In `ChainDB.__init__`, add after `self._next_follower_id = 0` (line 172):

```python
        self._followers_lock = threading.Lock()
```

Modify `new_follower()` (line 515):

```python
    def new_follower(self) -> Any:
        """Create a new chain-sync follower starting at Origin."""
        from vibe.cardano.storage.chain_follower import ChainFollower

        with self._followers_lock:
            fid = self._next_follower_id
            self._next_follower_id += 1
            self._follower_events[fid] = threading.Event()
            follower = ChainFollower(fid, self)
            self._followers[fid] = follower
        return follower
```

Modify `close_follower()` (line 529):

```python
    def close_follower(self, follower_id: int) -> None:
        """Remove a follower when the peer disconnects."""
        with self._followers_lock:
            self._followers.pop(follower_id, None)
            self._follower_events.pop(follower_id, None)
            self._async_follower_events.pop(follower_id, None)
```

Modify `_register_async_follower()` (line 535):

```python
    def _register_async_follower(
        self, follower_id: int, async_event: Any, loop: Any,
    ) -> None:
        with self._followers_lock:
            self._async_follower_events[follower_id] = (async_event, loop)
```

Modify `_notify_tip_changed()` (line 545) to copy dicts under lock:

```python
    def _notify_tip_changed(self) -> None:
        """Wake all follower events so each sees the new tip."""
        with self._followers_lock:
            async_items = list(self._async_follower_events.items())
            event_items = list(self._follower_events.values())

        for fid, (async_evt, loop) in async_items:
            try:
                loop.call_soon_threadsafe(async_evt.set)
            except RuntimeError:
                with self._followers_lock:
                    self._async_follower_events.pop(fid, None)

        for evt in event_items:
            evt.set()
```

Modify `_notify_fork_switch()` (line 564) to copy under lock:

```python
    def _notify_fork_switch(
        self,
        removed_hashes: set[bytes],
        intersection_point: Any,
    ) -> None:
        """Notify all followers of a fork switch."""
        with self._followers_lock:
            followers = list(self._followers.values())
        for follower in followers:
            follower.notify_fork_switch(removed_hashes, intersection_point)
```

- [ ] **Step 4: Run all existing chaindb tests to verify nothing breaks**

Run: `cd packages/vibe-cardano && python -m pytest tests/storage/test_chaindb.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py packages/vibe-cardano/tests/storage/test_chaindb.py
git commit -m "feat(chainsel): add followers lock for thread-safe follower management"
```

---

### Task 3: Fix get_blocks() to read from fragment_tvar

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`

- [ ] **Step 1: Modify get_blocks() to use fragment_tvar.value**

Replace the body of `get_blocks()` (lines 897-946) with:

```python
    async def get_blocks(
        self,
        point_from: Any,
        point_to: Any,
    ) -> list[bytes] | None:
        """Get blocks in a range, for block-fetch serving.

        Reads from fragment_tvar (thread-safe snapshot) instead of the
        raw _chain_fragment list, preventing races with the chain
        selection runner on Thread 4.

        Haskell ref: ChainDB iterator API
        """
        from vibe.cardano.network.chainsync import ORIGIN, Point

        fragment, fragment_index = self.fragment_tvar.value

        if not fragment:
            return None

        # Find start index
        if point_from is ORIGIN or point_from == ORIGIN:
            start_idx = 0
        elif isinstance(point_from, Point):
            idx = fragment_index.get(point_from.hash)
            if idx is None:
                return None
            start_idx = idx
        else:
            start_idx = 0

        # Find end index
        if point_to is ORIGIN or point_to == ORIGIN:
            end_idx = 0
        elif isinstance(point_to, Point):
            idx = fragment_index.get(point_to.hash)
            if idx is None:
                return None
            end_idx = idx
        else:
            end_idx = len(fragment) - 1

        if start_idx > end_idx:
            return None

        # Fetch block CBOR for each entry in range
        blocks: list[bytes] = []
        for i in range(start_idx, end_idx + 1):
            entry = fragment[i]
            cbor = await self.get_block(entry.block_hash)
            if cbor is not None:
                blocks.append(cbor)
        return blocks if blocks else None
```

- [ ] **Step 2: Run existing tests**

Run: `cd packages/vibe-cardano && python -m pytest tests/storage/test_chaindb.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py
git commit -m "fix(chainsel): get_blocks reads fragment_tvar instead of raw list"
```

---

### Task 4: Rename add_block to _process_block and implement the queue-based add_block

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`
- Test: `packages/vibe-cardano/tests/storage/test_chaindb.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/vibe-cardano/tests/storage/test_chaindb.py`:

```python
def test_add_block_is_sync(tmp_path):
    """add_block() is synchronous and returns ChainSelectionResult."""
    import inspect
    db = _make_chaindb(tmp_path)
    db.start_chain_sel_runner()
    try:
        # add_block should be a regular function, not a coroutine
        assert not inspect.iscoroutinefunction(db.add_block)
        result = db.add_block(
            slot=1,
            block_hash=_block_hash(1),
            predecessor_hash=_genesis_hash(),
            block_number=1,
            cbor_bytes=_cbor(1),
        )
        assert result.adopted is True
        assert result.new_tip is not None
        assert result.new_tip[2] == 1  # block_number
    finally:
        db.stop_chain_sel_runner()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/vibe-cardano && python -m pytest tests/storage/test_chaindb.py::test_add_block_is_sync -v`
Expected: FAIL — `add_block` is still async

- [ ] **Step 3: Rename add_block to _process_block, implement new add_block + runner**

In `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`:

**A. Rename the existing `async def add_block(` (line 584) to `async def _process_block(`.**

Change the docstring to note it's private and only called by the runner.

**B. Remove `add_block_sync` and `_forge_loop`** (lines 863-875). Delete completely.

**C. Add the runner and public API methods** after `_process_block` ends (after the old `add_block_sync`):

```python
    # ------------------------------------------------------------------
    # Chain selection runner (serialized on dedicated thread)
    # ------------------------------------------------------------------

    def start_chain_sel_runner(self) -> None:
        """Launch the chain selection background thread.

        Must be called before any add_block() calls. The thread runs
        a while-loop pulling BlockToAdd entries from the queue and
        processing them one at a time.

        Haskell ref: addBlockRunner in Background.hs
        """
        import asyncio as _asyncio

        def _runner() -> None:
            loop = _asyncio.new_event_loop()
            try:
                while True:
                    entry = self._chain_sel_queue.get()
                    if entry is None:
                        break  # Shutdown sentinel
                    try:
                        result = loop.run_until_complete(
                            self._process_block(
                                slot=entry.slot,
                                block_hash=entry.block_hash,
                                predecessor_hash=entry.predecessor_hash,
                                block_number=entry.block_number,
                                cbor_bytes=entry.cbor_bytes,
                                header_cbor=entry.header_cbor,
                                vrf_output=entry.vrf_output,
                            )
                        )
                        entry.result = result
                    except Exception as exc:
                        entry.error = exc
                    finally:
                        entry.done.set()
            finally:
                loop.close()

        self._chain_sel_thread = threading.Thread(
            target=_runner, daemon=True, name="vibe-chainsel",
        )
        self._chain_sel_thread.start()
        logger.info("Chain selection runner started (thread=%s)", self._chain_sel_thread.name)

    def stop_chain_sel_runner(self) -> None:
        """Stop the chain selection background thread.

        Sends a None sentinel and waits for the thread to exit.
        """
        if self._chain_sel_thread is not None:
            self._chain_sel_queue.put(None)
            self._chain_sel_thread.join(timeout=5)
            self._chain_sel_thread = None
            logger.info("Chain selection runner stopped")

    def add_block(
        self,
        slot: int,
        block_hash: bytes,
        predecessor_hash: bytes,
        block_number: int,
        cbor_bytes: bytes,
        header_cbor: Any = None,
        vrf_output: bytes | None = None,
    ) -> ChainSelectionResult:
        """Enqueue a block for chain selection and wait for the result.

        This is the public API. It is synchronous — callers on async
        event loops should use add_block_async() instead.

        Haskell ref: addBlockAsync + atomically (blockProcessed promise)
        """
        entry = BlockToAdd(
            slot=slot,
            block_hash=block_hash,
            predecessor_hash=predecessor_hash,
            block_number=block_number,
            cbor_bytes=cbor_bytes,
            header_cbor=header_cbor,
            vrf_output=vrf_output,
        )
        self._chain_sel_queue.put(entry)
        entry.done.wait()
        if entry.error is not None:
            raise entry.error
        assert entry.result is not None
        return entry.result

    async def add_block_async(
        self,
        **kwargs: Any,
    ) -> ChainSelectionResult:
        """Async wrapper for add_block, for callers on event loops.

        Uses asyncio.to_thread to avoid blocking the caller's event loop.
        """
        import asyncio as _asyncio
        return await _asyncio.to_thread(self.add_block, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/vibe-cardano && python -m pytest tests/storage/test_chaindb.py::test_add_block_is_sync -v`
Expected: PASS

- [ ] **Step 5: Run all existing chaindb tests**

Run: `cd packages/vibe-cardano && python -m pytest tests/storage/test_chaindb.py tests/storage/test_chaindb_fragment.py tests/storage/test_chaindb_gaps2.py tests/storage/test_chaindb_nonce.py -v`

Some tests may need updating because they call `await chain_db.add_block(...)` — the old async API. These tests should be updated to either:
- Call `chain_db.add_block(...)` directly (sync), OR
- Call `await chain_db.add_block_async(...)` (async wrapper)

And they need to call `chain_db.start_chain_sel_runner()` in setup and `chain_db.stop_chain_sel_runner()` in teardown.

Fix any test failures by making these changes.

- [ ] **Step 6: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py packages/vibe-cardano/tests/storage/
git commit -m "feat(chainsel): serialize chain selection through dedicated runner thread"
```

---

### Task 5: Update forge_loop.py to use sync add_block

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py`

- [ ] **Step 1: Remove the nonce consistency check and change add_block_sync to add_block**

In `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py`, replace lines 331-355 (the nonce check + add_block_sync call):

Before:
```python
            if chain_db is not None:
                current_nonce = chain_db.praos_nonce_tvar.value
                if current_nonce != epoch_nonce:
                    logger.info(
                        "Forged block #%d at slot %d discarded (nonce changed)",
                        forged.block.block_number,
                        forged.block.slot,
                    )
                    continue

                result = chain_db.add_block_sync(
```

After:
```python
            if chain_db is not None:
                result = chain_db.add_block(
```

Keep all the keyword arguments the same. Just remove the 7-line nonce check and change `add_block_sync` to `add_block`.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py
git commit -m "feat(chainsel): forge loop uses sync add_block (no more add_block_sync)"
```

---

### Task 6: Update peer_manager.py to use add_block_async

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py`

- [ ] **Step 1: Change both add_block call sites to add_block_async**

At line 818, change:
```python
                result = await chain_db.add_block(
```
to:
```python
                result = await chain_db.add_block_async(
```

At line 1032, change:
```python
                    result = await chain_db.add_block(
```
to:
```python
                    result = await chain_db.add_block_async(
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py
git commit -m "feat(chainsel): peer manager uses add_block_async wrapper"
```

---

### Task 7: Update run.py to start/stop the chain selection runner

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py`

- [ ] **Step 1: Add start_chain_sel_runner before threads start**

After `peer_tip_tvar = TVar(0)` (line 523) and before the thread creation (line 525), add:

```python
    # Start chain selection runner (Thread 4) — must be running before
    # any thread calls add_block or add_block_async.
    chain_db.start_chain_sel_runner()
```

- [ ] **Step 2: Add stop_chain_sel_runner during shutdown**

After `serve_thread.join(timeout=5)` (line 569), before `chain_db.close()` (line 570), add:

```python
    chain_db.stop_chain_sel_runner()
```

- [ ] **Step 3: Update the log message**

Change line 548:
```python
    logger.info("Node started — 3 threads (forge, receive, serve)")
```
to:
```python
    logger.info("Node started — 4 threads (forge, receive, serve, chainsel)")
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('packages/vibe-cardano/src/vibe/cardano/node/run.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/run.py
git commit -m "feat(chainsel): start/stop chain selection runner in node lifecycle"
```

---

### Task 8: Run full test suite and devnet verification

**Files:**
- No new files

- [ ] **Step 1: Run the full test suite**

Run: `cd packages/vibe-cardano && python -m pytest tests/ -v --timeout=60`

Fix any remaining failures. Common issues:
- Tests that `await chain_db.add_block(...)` need to change to either `chain_db.add_block(...)` (sync) or `await chain_db.add_block_async(...)` (async)
- Tests that create a ChainDB need to call `start_chain_sel_runner()` in setup and `stop_chain_sel_runner()` in teardown

- [ ] **Step 2: Build the Docker image**

Run: `docker compose -f infra/devnet/docker-compose.devnet.yml build vibe-node`
Expected: Build succeeds

- [ ] **Step 3: Run clean devnet test (3 minutes)**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml down -v
docker compose -f infra/devnet/docker-compose.devnet.yml up -d
sleep 180
```

- [ ] **Step 4: Verify zero VRFKeyBadProof**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color 2>&1 | grep -c "VRFKeyBadProof"
```
Expected: `0`

- [ ] **Step 5: Verify Haskell adopts our blocks**

```bash
# Get a recent vibe-forged block hash
HASH=$(docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color vibe-node 2>&1 | grep "ForgedBlock" | tail -1 | sed 's/.*hash=//;s/ .*//' | cut -c1-16)
# Check if Haskell adopted it
docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color haskell-node-1 2>&1 | grep "AddedToCurrentChain.*$HASH"
```
Expected: At least one match

- [ ] **Step 6: Verify forge share**

```bash
VIBE=$(docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color vibe-node 2>&1 | grep -c "ForgedBlock")
H1=$(docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color haskell-node-1 2>&1 | grep -c "ForgedBlock")
H2=$(docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color haskell-node-2 2>&1 | grep -c "ForgedBlock")
echo "Vibe: $VIBE  H1: $H1  H2: $H2"
```
Expected: Vibe approximately equal to H1 and H2 (each ~33% of total)

- [ ] **Step 7: Verify zero protocol errors**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color 2>&1 | grep -c "ExceededTimeLimit"
docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color 2>&1 | grep -ci "UnexpectedBlockNo"
```
Expected: Both `0`

- [ ] **Step 8: Commit any remaining fixes**

```bash
git add -A
git commit -m "fix(chainsel): test suite and devnet verification"
```
