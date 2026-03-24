# Threading Model — Design Spec

**Date:** 2026-03-24
**Status:** Approved
**Fixes:** One-slot forge lag at fast slot times

---

## Problem

The forge loop and block reception share a single asyncio event loop. When a block arrives mid-slot, the forge loop is sleeping in `wait_for_next_slot()` and doesn't wake until the next slot boundary. This creates a one-slot processing lag that prevents block acceptance at fast slot times (< 0.2s).

At 0.05s slots: 1% acceptance. At 0.2s slots: 35%. The bottleneck is not computation (838μs pipeline) but scheduling — the forge loop can't run while block reception is processing.

## Solution

Split the node into three OS threads matching the Haskell architecture:

1. **Forge thread** — slot-by-slot leadership check and block forging
2. **Receive thread** — peer connections, chain-sync clients, block-fetch clients
3. **Serve thread** — inbound connections, chain-sync servers, block-fetch servers

Threads share ChainDB and NodeKernel state via a read-write lock. The forge thread wakes on either the next slot boundary OR a `threading.Event` set by the receive thread when a new block arrives.

## Haskell Reference

The Haskell node uses OS threads with STM coordination:
- Chain selection thread processes blocks from a queue
- Forge thread blocks on `blockProcessed` TMVar
- Per-peer chain-sync/block-fetch threads (both client and server)
- STM TVars give atomic reads/writes without locks

Our 3-thread model consolidates per-peer threads into two async event loops (receive and serve). This diverges from Haskell but works for moderate peer counts (< 20) since asyncio efficiently multiplexes I/O within each thread.

**Scaling path:** If peer count becomes a bottleneck, split receive/serve into per-peer threads, each with its own event loop. The RWLock already supports concurrent readers.

---

## Architecture

### Thread Layout

```
Thread 1: FORGE (main thread)
  ├── Slot clock timing (threading.Event.wait with timeout)
  ├── VRF leadership check (pure computation, no lock)
  ├── forge_block (pure computation, no lock)
  ├── chain_db.add_block (write lock)
  └── node_kernel.on_block_adopted (write lock)

Thread 2: RECEIVE (daemon thread, own asyncio loop)
  ├── Peer manager (outbound connections)
  ├── Chain-sync clients (receive headers)
  ├── Block-fetch clients (receive bodies)
  ├── chain_db.add_block (write lock)
  ├── node_kernel.on_block_adopted (write lock)
  └── Sets block_received_event after each block

Thread 3: SERVE (daemon thread, own asyncio loop)
  ├── Inbound server (accept connections)
  ├── Chain-sync servers (serve headers via followers, read lock)
  ├── Block-fetch servers (serve bodies, read lock)
  └── Keep-alive servers
```

### Shared State

| State | Read by | Written by | Lock |
|-------|---------|------------|------|
| ChainDB._chain_fragment | Forge, Serve | Receive, Forge | chaindb_lock |
| ChainDB._tip | Forge, Serve | Receive, Forge | chaindb_lock |
| ChainDB._tip_generation | Forge, Serve | Receive, Forge | chaindb_lock |
| VolatileDB._blocks | Serve | Receive, Forge | chaindb_lock |
| ChainDB._followers | Serve | Serve | chaindb_lock |
| NodeKernel._epoch_nonce | Forge | Receive, Forge | kernel_lock |
| NodeKernel._stake_distribution | Forge | Receive | kernel_lock |

### RWLock

```python
class RWLock:
    """Read-write lock. Multiple concurrent readers, exclusive writer.

    Haskell equivalent: STM TVar (multiple readers, atomic writer).
    """
    def read(self) -> ContextManager: ...   # Acquire read lock
    def write(self) -> ContextManager: ...  # Acquire write lock
```

Two instances: `chaindb_lock` (protects ChainDB + VolatileDB) and `kernel_lock` (protects NodeKernel nonce/stake state).

### Inter-Thread Communication

**Block arrival notification:**
- `threading.Event` — `block_received_event`
- Set by Receive thread after `chain_db.add_block()` succeeds
- Forge thread: `block_received_event.wait(timeout=time_to_next_slot)`
- Wakes forge thread immediately when a new block arrives

**Shutdown:**
- `threading.Event` — `shutdown_event`
- Set by main thread on SIGINT/SIGTERM
- All threads check it in their main loops

### Forge Thread (Not Async)

The forge loop becomes a regular thread function using `threading.Event.wait()` for timing instead of `asyncio.sleep()`:

```python
def _forge_thread_main(...):
    while not shutdown.is_set():
        # Wait for next slot OR new block
        time_to_next = _time_to_next_slot(slot_config)
        block_received.wait(timeout=time_to_next)
        block_received.clear()

        slot = _current_slot(slot_config)

        # Read tip (read lock, microseconds)
        with chaindb_lock.read():
            tip = chain_db._tip
            ...

        # VRF check (no lock, ~90μs)
        proof = check_leadership(...)

        # Forge (no lock, ~110μs)
        forged = forge_block(...)

        # Write (write lock, ~400μs)
        with chaindb_lock.write():
            result = chain_db.add_block_sync(...)

        if result.adopted:
            with kernel_lock.write():
                node_kernel.on_block_adopted(...)
```

### Receive and Serve Threads

Each creates its own asyncio event loop:

```python
def _run_receive_thread(...):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_receive_main(...))

def _run_serve_thread(...):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_serve_main(...))
```

Network I/O (socket read/write) releases the GIL, so the three threads run concurrently on I/O operations despite the GIL.

---

## File Changes

| File | Change |
|------|--------|
| `core/rwlock.py` | **New.** RWLock implementation with context managers. |
| `node/run.py` | Rewrite `run_node()` as thread orchestrator. Create threads, pass shared locks/events. |
| `node/forge_loop.py` | Convert from async to sync. Use `threading.Event.wait()`. Acquire locks for ChainDB/kernel access. Add `chain_db.add_block_sync()` wrapper. |
| `node/peer_manager.py` | Acquire write lock around `chain_db.add_block()`. Set `block_received_event`. |
| `node/inbound_server.py` | No structural change. Runs on Serve thread's event loop. |
| `storage/chaindb.py` | Add `_lock: RWLock` field. Add `add_block_sync()` wrapper. Wrap public methods with lock. |
| `storage/chain_follower.py` | Acquire read lock in `instruction()`. |
| `node/kernel.py` | Add `_lock: RWLock` field. Wrap nonce/stake reads and writes. |
| `docs/reference/pipelines/block-production-validation.md` | Add Threading Model section. |

---

## GIL and Performance

Python 3.14 has the GIL enabled in our build. This is fine because:

1. **I/O releases the GIL** — socket recv/send, file I/O, asyncio sleep
2. **Threads barely overlap on CPU** — forge check is 90μs, then waits. Block decode is brief, then waits for network.
3. **Lock contention is minimal** — write locks held for < 1ms, reads are concurrent

If we build with `--disable-gil` (free-threaded Python 3.14t), we get true parallel CPU execution for free with no code changes. The RWLock still works correctly in both modes.

---

## Testing

- Unit test: RWLock concurrent readers, exclusive writer
- Unit test: Forge thread wakes on block_received_event within same slot
- Integration: devnet at 0.05s slots — acceptance rate should improve from 1% toward 33%
- Integration: devnet at 0.2s slots — acceptance rate stays at ~33%
- Benchmark: lock contention under load (multiple threads hitting ChainDB)
