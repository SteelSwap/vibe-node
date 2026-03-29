# Chain Selection Serialization Design

## Problem

ChainDB's `add_block()` is called from two threads with no serialization:

- **Thread 1 (forge)**: `chain_db.add_block_sync()` via a private cached event loop
- **Thread 2 (receive)**: `await chain_db.add_block()` on the receive thread's event loop

Both threads mutate shared state (`_tip`, `_chain_fragment`, `_fragment_index`, `_ledger_seq`, TVars) concurrently. This causes:

1. **VRFKeyBadProof**: The forge loop reads `tip_tvar` (updated) + `praos_nonce_tvar` (not yet updated) in a single STM transaction, producing blocks with stale epoch nonces that Haskell rejects. Every block we forge is rejected — zero blocks accepted by Haskell peers.

2. **Fragment corruption**: Concurrent fragment mutations from two threads can produce inconsistent `_chain_fragment` / `_fragment_index` state.

3. **Excessive fork switches**: Concurrent chain selection can produce conflicting tip decisions.

Haskell solves this with a single `addBlockRunner` thread that processes all blocks from a `TBQueue`. We adopt the same pattern.

## Architecture

A dedicated chain selection thread (Thread 4, `"vibe-chainsel"`) runs a single asyncio event loop and processes all `add_block` calls sequentially. Callers enqueue blocks onto a thread-safe queue and block until processing completes.

```
Thread 1 (forge)      ──enqueue──>  Thread 4 (chainsel)  <──enqueue──  Thread 2 (receive)
     |                                    |
     v                                    | processes one block at a time
  wait on Event                           | all ChainDB mutation here
     |                                    |
     <───── Event.set() ─────────────────/
```

### Haskell reference

- `addBlockAsync` enqueues to `TBQueue` in `ChainSel.hs:299-307`
- `addBlockRunner` in `Background.hs:606-657` dequeues and calls `chainSelSync`
- `blockProcessed` uses `TMVar` for signaling completion to waiters
- `switchTo` in `ChainSel.hs:856-951` atomically updates chain + ledger + followers in one STM transaction

## Components

### BlockToAdd (dataclass)

Queue entry containing all parameters for `add_block` plus signaling:

- `slot`, `block_hash`, `predecessor_hash`, `block_number`, `cbor_bytes`, `header_cbor`, `vrf_output` — block data
- `result: ChainSelectionResult | None` — filled by the runner after processing
- `done: threading.Event` — signaled when processing completes (success or failure)
- `error: Exception | None` — filled if processing raises

### _chain_sel_queue (queue.Queue)

Standard library thread-safe unbounded queue. Holds `BlockToAdd` entries. A `None` sentinel signals shutdown.

### _chain_sel_runner() (method on ChainDB)

Runs on Thread 4 in a `while True` loop:

1. `entry = self._chain_sel_queue.get()` — blocks until work available
2. If `entry is None` — break (shutdown)
3. Call `self._process_block(...)` with the entry's parameters
4. Set `entry.result` with the return value
5. `entry.done.set()` — wake the caller
6. On exception: set `entry.error`, `entry.done.set()` — runner continues

The runner creates its own `asyncio.new_event_loop()` at startup for the async operations inside `_process_block` (specifically `volatile_db.add_block`).

### add_block() — public sync API

The new public `add_block()` is synchronous:

1. Create a `BlockToAdd` with a fresh `threading.Event`
2. Put it on `_chain_sel_queue`
3. `entry.done.wait()` — blocks the caller until the runner processes it
4. If `entry.error` is set, raise it
5. Return `entry.result`

### add_block_async() — async wrapper

For callers on async event loops (Thread 2):

```python
async def add_block_async(self, **kwargs) -> ChainSelectionResult:
    return await asyncio.to_thread(self.add_block, **kwargs)
```

### _process_block() — renamed from add_block()

The existing `add_block()` logic (volatile store, chain selection, fragment rebuild, LedgerSeq update, TVar writes, follower notification) is renamed to `_process_block()`. It is private and only called by the runner. No logic changes — just renamed and made private.

## What changes for callers

| Caller | Before | After |
|--------|--------|-------|
| `forge_loop.py` | `chain_db.add_block_sync(...)` | `chain_db.add_block(...)` |
| `peer_manager.py` (inline) | `await chain_db.add_block(...)` | `await chain_db.add_block_async(...)` |
| `peer_manager.py` (shared processor) | `await chain_db.add_block(...)` | `await chain_db.add_block_async(...)` |

## What goes away

- `add_block_sync()` and the private `_forge_loop` event loop — replaced by the queue
- The post-forge nonce consistency check in `forge_loop.py` (lines 338-345) — no longer needed; the runner serializes nonce updates with block processing

## Thread lifecycle

### Startup (in run.py)

`chain_db.start_chain_sel_runner()` launches Thread 4 before Thread 2 and Thread 1 start. The thread is a daemon thread named `"vibe-chainsel"`. It creates its own asyncio event loop internally.

### Shutdown

1. `chain_db.stop_chain_sel_runner()` puts `None` on the queue
2. The runner sees `None`, breaks, closes its event loop
3. `stop_chain_sel_runner()` calls `thread.join(timeout=5)`
4. Called from `run.py` during shutdown, after forge loop and receive thread have stopped

### Error handling

If `_process_block()` raises, the exception is captured in `entry.error` and `entry.done.set()` fires. The caller re-raises the exception in its own thread context. The runner thread continues processing the next entry.

## Ancillary race fixes

The serialization refactor moves all `add_block` mutations to Thread 4, but two existing cross-thread races remain between Thread 4 (chainsel) and Thread 3 (serve). We fix both as part of this work.

### Fix A: `get_blocks()` reads raw `_chain_fragment` directly

The block-fetch server on Thread 3 calls `get_blocks()` which reads `self._chain_fragment` and `self._fragment_index` — the raw mutable list/dict, not the TVar snapshot. Thread 4 mutates these during `_process_block()`.

**Fix**: Change `get_blocks()` to read from `self.fragment_tvar.value` instead of the raw fields. The TVar always holds a consistent `(list, dict)` tuple created via `list()` / `dict()` copy, so readers always see a complete snapshot.

### Fix B: `_followers` dict concurrent modification

`new_follower()` and `close_follower()` are called on Thread 3 (serve) and modify `self._followers`. `_notify_fork_switch()` and `_notify_tip_changed()` iterate `self._followers` on Thread 4 (chainsel). This is a concurrent dict modification hazard.

**Fix**: Add a `threading.Lock` (`self._followers_lock`) protecting all reads and writes of `self._followers`, `self._follower_events`, and `self._async_follower_events`. The lock is held briefly (dict insert/remove/iterate) so contention is negligible.

## Ordering guarantees

Since all ChainDB mutations run on one thread:

- `praos_nonce_tvar` and `tip_tvar` are always written from the same thread in the correct order (nonce before tip). The forge loop's STM transaction always sees a consistent pair.
- `_chain_fragment` and `_fragment_index` are never modified concurrently. Fragment corruption is impossible.
- `_notify_fork_switch()` and fragment rebuild happen atomically from the caller's perspective — no interleaving.
- `_notify_tip_changed()` uses `loop.call_soon_threadsafe()` targeting Thread 3. This works from any source thread, including the new Thread 4.
- Thread 3 readers (`get_blocks`, followers) always see consistent snapshots via TVar reads or lock-protected dict copies.

## Success criteria

1. **Zero VRFKeyBadProof** — forge loop always sees consistent tip+nonce
2. **Zero data races** — only Thread 4 touches ChainDB mutable state
3. **No performance regression** — queue overhead is microseconds; callers already blocked on the result
4. **Haskell adopts our blocks** — verified by `AddedToCurrentChain` matching our forged block hashes
5. **Forge share ~33%** — measured over 3+ minute devnet runs
