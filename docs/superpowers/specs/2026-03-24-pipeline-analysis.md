# Block Production Pipeline Analysis

**Date:** 2026-03-24
**Purpose:** Understand the actual code paths before optimizing further

---

## Current Thread Swimlane (STM Architecture)

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
                               chain_db.add_block()
                                  │ writes tip_tvar, fragment_tvar
                                  │ via TVar._write()
                               if adopted:
                                  set block_received_event
                                  ──→ wakes Thread 1
                                  │
                               on_block_adopted()
                                  │ writes nonce_tvar
                                  │ via TVar._write()
                                  │
wait(slot | event)                                            follower.instruction()
   │                                                             │
atomically(_forge_tx):                                        read fragment_tvar.value
   tip = tx.read(tip_tvar)                                       │ consistent snapshot
   nonce = tx.read(nonce_tvar)                                if at tip: wait tip_changed
   stake = tx.read(stake_tvar)                                   │ BLOCKS (executor)
   │ snapshot — if any TVar
   │ changes, transaction retries
   │
check_leadership (CPU)
   │
forge_block (CPU)
   │
atomically(_store_tx):
   verify nonce_tvar unchanged                                wake: read fragment_tvar.value
   chain_db.add_block_sync()                                     │ consistent snapshot
   │ writes tip_tvar, fragment_tvar                           send MsgRollForward
set tip_changed
   ──→ wakes Thread 3
on_block_adopted()
   │ writes nonce_tvar
```

### STM TVar Flow

```
           ┌─────────────────────────────────────────┐
           │           STM TVars (shared state)       │
           │                                          │
           │  tip_tvar ──── ChainDB._tip              │
           │  fragment_tvar ── (fragment, index)      │
           │  nonce_tvar ── epoch nonce bytes          │
           │  stake_tvar ── pool stake distribution    │
           └──┬────────┬────────────────┬─────────────┘
              │        │                │
     THREAD 1 │  THREAD 2              │ THREAD 3
     (FORGE)  │  (RECEIVE)             │ (SERVE)
              │        │                │
     atomically()      │                │
     reads tip+nonce   writes tip+nonce reads fragment
     detects conflicts writes fragment  via .value
     via versioned     via ._write()    (GIL-safe)
     optimistic CC
```

## Problems Found (Original — All Fixed by STM)

### P1: Thread 2 has NO LOCKS on shared state mutations ✅ FIXED
- Now: `add_block()` writes `tip_tvar._write()` and `fragment_tvar._write()`
- `on_block_adopted()` writes `nonce_tvar._write()`
- STM version bumps ensure forge loop detects changes

### P2: Thread 3 has NO LOCKS on shared state reads ✅ FIXED
- Now: Follower reads `fragment_tvar.value` for consistent snapshot
- Python GIL ensures reference reads are atomic
- `TVar._write()` replaces value in one shot

### P3: 2-slot receive lag ⚠️ PARTIALLY ADDRESSED
- Nonce is updated after ChainDB adoption (not from header — see P4 note)
- Tip updates after body validation — same as before
- STM retry ensures forge always uses latest nonce, but doesn't reduce lag
- Future: header-first tentative processing (like Haskell pipelining)

### P4: Nonce accumulation coupled to block body ✅ FIXED
- Nonce updates only after ChainDB confirms adoption (correctness first)
- STM forge transaction reads nonce atomically with tip
- If nonce changes during forging, STM transaction retries
- No more VRFKeyBadProof from stale nonce — forge always gets consistent snapshot

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
