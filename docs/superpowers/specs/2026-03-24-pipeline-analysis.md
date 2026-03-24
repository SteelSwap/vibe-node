# Block Production Pipeline Analysis

**Date:** 2026-03-24
**Purpose:** Understand the actual code paths before optimizing further

---

## Original Thread Swimlane (before WI changes)

```
THREAD 1 (FORGE)              THREAD 2 (RECEIVE)              THREAD 3 (SERVE)
────────────────              ──────────────────              ─────────────────
                               chain-sync: recv header
                                  │ SYNC callback
                               decode header (has VRF out!)
                                  │
                               queue Point → fetch_queue
                                  │
                               block-fetch: request body
                                  │ AWAIT (network I/O)
                               recv body
                                  │
                               decode CBOR body
                                  │
                               validate txs
                                  │
                               add_block ⚠️NO LOCK
                                  │ updates tip, fragment
                               set block_received_event
                                  ──→ wakes Thread 1
wait(slot | event)             on_block_adopted ⚠️NO LOCK
   │                              │ updates nonces
read tip [READ LOCK]
   │
tick epoch [WRITE LOCK]                                       follower.instruction()
   │                                                             │
read nonce [READ LOCK]                                        read fragment ⚠️NO LOCK
   │                                                             │
check_leadership (CPU)                                        if at tip: wait tip_changed
   │                                                             │ BLOCKS (executor)
forge_block (CPU)
   │
add_block_sync [WRITE LOCK]
   │ updates tip, fragment
set tip_changed
   ──→ wakes Thread 3                                         wake: read fragment ⚠️NO LOCK
on_block_adopted [WRITE LOCK]                                    │
                                                              send MsgRollForward
```

## Current Thread Swimlane (after WI-1 through WI-5)

```
THREAD 1 (FORGE)              THREAD 2 (RECEIVE)              THREAD 3 (SERVE)
────────────────              ──────────────────              ─────────────────
                               chain-sync: recv header
                                  │ SYNC callback
                               decode header (has VRF out!)
                                  │
                               ┌─ on_block_adopted [WRITE LOCK]   (WI-3: nonce from header)
                               │  updates evolving_nonce, epoch
                               │
                               └─ create_task: add_block [WRITE LOCK]  (WI-4: tip from header)
                                  │ fire-and-forget via run_in_executor
                                  │ updates _tip, _chain_fragment
                                  │ sets block_received_event ──→ wakes Thread 1
                                  │ sets tip_changed ──→ wakes Thread 3
                               │
                               queue Point → fetch_queue
                                  │
                               block-fetch: request body
                                  │ AWAIT (network I/O)
                               recv body
                                  │
                               decode CBOR body
                                  │
                               validate txs
                                  │
                               store body in VolatileDB
                                  │
                               add_block [WRITE LOCK] (WI-1: locked)
                                  │ mostly no-op (tip already set)
                                  │
wait(slot | event)
   │
read tip [READ LOCK]                                          follower.instruction()
   │                                                             │
read nonce [READ LOCK]   (WI-5: no epoch tick)                snapshot fragment [READ LOCK] (WI-2)
   │                                                             │
check_leadership (CPU)                                        if at tip: wait tip_changed
   │                                                             │ run_in_executor
forge_block (CPU)
   │
add_block_sync [WRITE LOCK]
   │ updates tip, fragment
set tip_changed ──→ wakes Thread 3                            wake: snapshot fragment [READ LOCK]
   │                                                             │
on_block_adopted [WRITE LOCK]                                 send MsgRollForward
```

### What Changed vs Original

| Step | Before | After | WI |
|------|--------|-------|-----|
| Nonce update | After body in _on_block (no lock) | At header in _on_roll_forward [WRITE LOCK] | WI-3 |
| Tip update | After body in _on_block (no lock) | At header via create_task [WRITE LOCK] | WI-4 |
| _on_block chain_db.add_block | No lock | run_in_executor [WRITE LOCK] | WI-1 |
| Follower fragment read | No lock | Snapshot under [READ LOCK] | WI-2 |
| Forge epoch tick | Wall-clock based [WRITE LOCK] | Removed — reads from header processing | WI-5 |

## Problems Found

### P1: Thread 2 has NO LOCKS on shared state mutations
- `chain_db.add_block()` called without `chain_db._lock`
- `node_kernel.on_block_adopted()` called without `node_kernel._lock`
- Race with Thread 1 which does hold locks

### P2: Thread 3 has NO LOCKS on shared state reads
- `_chain_fragment` and `_fragment_index` read without `chain_db._lock`
- Race with Threads 1 and 2 which modify fragment

### P3: 2-slot receive lag (the performance bottleneck)
- Header arrives at Thread 2 step 1
- Tip doesn't update until step 7 (after block-fetch + decode + validate + add_block)
- The VRF output IS in the header (step 2) but we don't use it until step 7
- Forge loop reads stale tip, forges 2 slots behind Haskell

### P4: Nonce accumulation coupled to block body
- `on_block_adopted()` called after body processing
- Epoch boundary tick in forge loop uses current slot
- At epoch boundaries, forge loop ticks epoch before body processing catches up
- Result: VRFKeyBadProof when nonce is based on incomplete VRF accumulation

---

## Haskell Reference

### How Haskell avoids these problems:

1. **STM for all shared state** — no explicit locks, atomic transactions
2. **Chain selection runs on header** — `chainSelectionForBlock` in ChainSel.hs:590 receives the header and runs chain selection immediately
3. **VRF nonce from header** — `reupdateChainDepState` in Praos.hs:501 reads VRF output from the header view (`Views.hvVrfRes b`), not from the block body
4. **Body fetched in background** — body validation happens after chain selection, not before
5. **blockProcessed blocks forge** — forge loop waits for chain selection to complete before reading tip

### Key Haskell insight:
The VRF output (`hvVrfRes`) is a **header field**. The Haskell node updates:
- Chain selection (tip) from the header
- Nonce accumulation (`reupdateChainDepState`) from the header
- Body validation happens separately, after adoption

We can do the same: process BOTH tip AND nonce from the header in `_on_roll_forward`.

---

## Work Items

### WI-1: Add locks to Thread 2 (receive)

**Problem:** P1 — Thread 2 mutates shared state without locks
**Fix:** Wrap `chain_db.add_block()` and `node_kernel.on_block_adopted()` calls in peer_manager with appropriate locks
**Challenge:** `add_block()` is async — can't hold a sync lock across `await`. Options:
  - (a) Use `asyncio.Lock` within Thread 2's event loop (protects against intra-loop races but not cross-thread)
  - (b) Use `loop.run_in_executor()` to hold the sync RWLock on a thread pool thread
  - (c) Make `add_block` sync and run it in executor
**Recommended:** (c) — create `add_block_sync` wrapper (already exists), call via `run_in_executor` with write lock

### WI-2: Add locks to Thread 3 (serve)

**Problem:** P2 — Thread 3 reads fragment without locks
**Fix:** Wrap fragment reads in `chain_follower.instruction()` with `chain_db._lock.read()` via `run_in_executor`
**Challenge:** Same async-vs-sync lock issue. Read locks are brief (microseconds) so blocking the thread pool briefly is acceptable.

### WI-3: Process nonce from header (eliminate nonce lag)

**Problem:** P4 — nonce accumulated from block body, not header
**Fix:** In `_on_roll_forward`, call `node_kernel.on_block_adopted()` synchronously with the VRF output from the decoded header. This is safe because:
  - VRF output is a header field (already decoded)
  - `on_block_adopted()` is a sync method
  - We're on Thread 2's event loop, so no async conflict
  - Need `node_kernel._lock.write()` — brief sync lock, OK in callback

### WI-4: Process tip from header (eliminate tip lag)

**Problem:** P3 — tip updates after block body arrives
**Fix:** In `_on_roll_forward`, call `chain_db.add_block()` with empty body via `asyncio.create_task()` (fire-and-forget, doesn't block callback). When body arrives in `_on_block`, update VolatileDB with actual body bytes.
**Depends on:** WI-3 (nonce must be correct first)
**Note:** Previous attempt failed because nonce was coupled to body. With WI-3 done first, this should work.

### WI-5: Remove epoch tick from forge loop

**Problem:** Forge loop ticks epoch from wall-clock slot, conflicting with header-based nonce processing
**Fix:** After WI-3, all epoch ticks happen via `on_block_adopted()` from headers. Remove the forge loop epoch tick entirely — just read `node_kernel.epoch_nonce.value`.
**Depends on:** WI-3

### WI-6: Devnet verification

Test at 0.05s, 0.1s, 0.2s slots. Verify:
- Zero VRFKeyBadProof errors
- Zero UnexpectedPrevHash errors
- Acceptance rate improved (target: >20% at 0.05s, >30% at 0.2s)

---

## Implementation Order

```
WI-1 (locks on Thread 2) — safety first
  │
WI-2 (locks on Thread 3) — safety first
  │
WI-3 (nonce from header) — enables WI-4 and WI-5
  │
  ├── WI-4 (tip from header) — eliminates lag
  │
  └── WI-5 (remove forge epoch tick) — cleanup
       │
       WI-6 (devnet test)
```

WI-1 and WI-2 are safety fixes (race conditions).
WI-3 is the key enabler — once nonce comes from headers, everything else follows.
WI-4 and WI-5 are the performance fixes that depend on WI-3.

---

## Haskell Cross-Reference Verification

All three key claims verified against vendor/ source:

### WI-3 Verified: VRF output IS a header field
- `Views.hvVrfRes` is a `HeaderView` field (Views.hs:29)
- `reupdateChainDepState` (Praos.hs:501-533) reads VRF from header view, never touches block body
- `vrfNonceValue (Proxy @c) $ Views.hvVrfRes b` — `b` is a HeaderView, not a Block

### WI-4 Verified: Chain selection runs on headers
- `chainSelectionForBlock` signature takes `Header blk`, not `Block blk` (ChainSel.hs:590)
- Body validation happens inside `validateCandidate` (ChainSel.hs:1260), AFTER chain selection picks the candidate
- Chain selection constructs candidate fragments from headers only

### WI-5 Verified: No wall-clock epoch tick in forge loop
- Forge loop uses `ledgerViewForecastAt` to forecast the epoch context from the ledger state (NodeKernel.hs:631-640)
- `tickChainDepState` uses the forecast ledger view, not wall-clock math
- Epoch nonce comes from ledger history, not re-derived

### Additional Haskell Patterns Not Yet Implemented
1. **Tentative header pipelining** — set header speculatively before body validates (optimization, not required for correctness)
2. **Invalid block cache** — skip candidates containing known-invalid blocks (correctness for malicious peers)
3. **Ledger forecast failure** — handle case when forecast window exceeded (we have the 10-slot sync gate, close enough)

### Key Ordering in Haskell Forge Loop (NodeKernel.hs:602-640)
1. Get unticked ledger state from ChainDB
2. **Forecast** ledger view for current slot (includes epoch info)
3. Tick chain dep state using forecast (NOT wall-clock)
4. Check leadership using ticked state
5. If leader: tick full ledger state, forge block

Our forge loop uses wall-clock for epoch tick (step 3) instead of forecasting from ledger. After WI-3 and WI-5, the nonce will come from header-based accumulation, matching the Haskell approach.
