# Multi-Peer Parallel Block-Fetch Design

**Goal:** Download blocks from multiple peers simultaneously, increasing sync throughput beyond the single-peer bandwidth ceiling (~340 bps).

**Covers:** M6.14 Task 10 (Multi-peer parallel block-fetch).

## Problem

We currently run pipelined block-fetch on a single peer. Other connected peers do chain-sync but not block-fetch. Throughput is capped by one peer's bandwidth. With the pipelined architecture, block processing is no longer the bottleneck — the network pipe is.

Previous multi-peer attempts (4 total) failed because `_on_block` requires blocks in chain order for nonce accumulation and ledger state. Out-of-order delivery from multiple peers corrupted nonce state.

## Key Insight: Store-First, Nonce-Later

During bulk sync, nonce accumulation and ledger state updates don't need to happen per-block inline. We can:

1. **Store blocks in any order** — VolatileDB is hash-indexed, ChainDB chain selection handles out-of-order arrival via the successor map (matching the Haskell node's design)
2. **Accumulate nonce separately** — a dedicated worker walks the chain fragment in order after blocks are stored

This eliminates the reorder buffer requirement that made previous attempts complex.

## Prerequisite: ChainDB Chain Selection Fix

Our current `add_block` does a simple `block_number > tip.block_number` comparison. This breaks with out-of-order delivery — if block N+2 arrives before N+1, N+2 is adopted as tip but the fragment can't walk back through the missing N+1.

The Haskell node's `chainSelectionForBlock` handles this correctly by walking the successor map forward from the newly stored block to find the longest chain. Our `add_block` must be upgraded to match.

**Required changes to `chaindb.py` `add_block`:**

1. **Always store in VolatileDB first** (already done)
2. **Walk the successor map forward** from the new block to find the longest chain extension via `maximalCandidates` — recursively follow successors to enumerate all maximal paths
3. **Walk backward** from the new block through `predecessor_hash` links to find where the candidate chain intersects the current chain (or immutable tip)
4. **Compare the complete candidate chain** (backward path + forward extension) against the current chain. Switch if preferred.
5. **"Store but don't change"** — if the block's predecessor is not reachable from the current chain at all, store it in VolatileDB but don't modify the chain fragment. A future gap-filling block will trigger re-evaluation.

This is a spec-compliance fix regardless of multi-peer — it makes our chain selection match `chainSelectionForBlock` in the Haskell node.

Haskell references:
- `ChainSel.hs`: `chainSelectionForBlock`, `addToCurrentChain`, `switchToAFork`
- `Paths.hs`: `isReachable`, `computeReversePath`, `maximalCandidates`, `extendWithSuccessors`

## Architecture

```
                    [CHAIN-SYNC]  (one peer, discovers headers)
                         |
                    fetch_queue
                         |
                    [RANGE BUILDER]  (batches points into ranges)
                         |
                    range_queue  (SHARED)
                    /    |    \
            [PEER 1]  [PEER 2]  [PEER N]   (each runs run_block_fetch_pipelined)
                    \    |    /
                    block_queue  (SHARED)
                         |
                    [PROCESSOR]  (single — decode, store in VolatileDB, chain selection)
                         |
                    [NONCE WORKER]  (sequential — walks chain in order, accumulates nonce)
```

- **range_queue is shared** across all peers. Each peer's sender grabs the next available range independently.
- **block_queue is shared** — all peers' receivers put blocks here.
- **One processor task** for all peers. Stores in VolatileDB and runs chain selection. Order doesn't matter — ChainDB handles out-of-order via successor map walking.
- **Nonce worker** — separate task that periodically walks the chain fragment in order and accumulates nonce for new blocks since its last pass.

## Peer Management

- **Chain-sync**: One peer runs chain-sync, feeding fetch_queue → range_builder → range_queue.
- **Block-fetch**: All connected peers run `run_block_fetch_pipelined`, pulling from the shared range_queue and pushing to the shared block_queue.
- **Peer disconnect**: If a peer disconnects mid-range, its in-flight ranges are lost. The range tracker (see below) re-enqueues uncompleted ranges.
- **Peer connect**: New peers immediately start pulling from range_queue. No warmup.

### Range Tracking and Recovery

When a range is pulled from `range_queue`, it's tracked as "in-flight" with a mapping of `(point_from, point_to) → peer_id`. When a peer completes a range (BatchDone received), the range is marked complete. When a peer disconnects, all its in-flight ranges are re-enqueued to `range_queue`.

Similarly, if a peer responds with `NoBlocks` for a range, that range is re-enqueued so another peer can try it.

## Splitting `_on_block`

Currently `_on_block` does everything: decode, validate, ledger mutations, ChainDB store, nonce accumulation.

**Processor** (runs per block, any order):
- CBOR decode block
- Extract header (slot, hash, predecessor, block_number)
- Decode body + validate (currently skipped — protocol_params is raw dict)
- Ledger state mutations
- Store in ChainDB (VolatileDB + chain selection with successor map walking)
- Logging

**Nonce worker** (runs periodically, sequential):
- Walks chain fragment from last processed block to current tip
- For each new block: calls `node_kernel.on_block_adopted(slot, hash, prev_hash, vrf_output)`
- Tracks `last_nonce_block_hash` and `last_nonce_block_number` to know where to resume
- Initialized on startup from the chain fragment tip (or genesis if empty)
- Runs on a timer (every 0.5s) or triggered after N blocks stored
- Fork switch detection: if `last_nonce_block_hash` is no longer in the fragment, calls `node_kernel.on_fork_switch` with the new chain
- Reads from chain fragment (protected by STM TVar for consistency) and VolatileDB block_info (VRF outputs). No raw block bytes needed.

## Chain-Sync Scaling

With N peers draining range_queue N times faster, chain-sync must keep up. PIPELINE_DEPTH scales proportionally:

```python
PIPELINE_DEPTH = 200 * num_block_fetch_peers
```

This is set statically based on the number of configured peers. We validated that depth=200 works for 1 peer; depth=400 for 2 peers, etc.

## Code Changes

**`chaindb.py`** — prerequisite (chain selection fix):
- Rewrite chain selection in `add_block` to walk successor map forward (`maximalCandidates`) and backward (`computeReversePath`) instead of simple tip comparison
- Add `_maximal_candidates(start_hash)` — recursive successor walk returning longest chain
- Add `_is_reachable(block_hash)` — backward walk through predecessor links to find intersection with current chain
- Handle "store but don't change" case for unreachable blocks

**`blockfetch_protocol.py`** — minor:
- Add optional `block_queue` parameter to `run_block_fetch_pipelined`. When provided, receiver puts blocks there directly and no internal processor is created. When not provided, creates its own (backward compatible).

**`peer_manager.py`** — main changes:
- Move `range_queue`, `block_queue`, processor task to `PeerManager` level (shared across peers)
- Each peer's `_block_fetch_worker` receives shared queues
- Split `_on_block` into processor (any-order decode+store) and nonce worker (sequential)
- New `_nonce_worker` coroutine
- Range tracking with re-enqueue on disconnect/NoBlocks
- Scale PIPELINE_DEPTH by peer count

**No changes to**: `volatile.py`, `mux.py`, `bearer.py`, `blockfetch.py`

## Edge Cases

- **All peers disconnect**: Processor drains block_queue, nonce worker catches up to chain fragment tip. On reconnect, chain-sync restarts from `known_points` (ChainDB tip). Orphaned VolatileDB blocks beyond the chain fragment are harmless — they'll be linked when future blocks fill gaps, or GC'd if they're below the immutable tip.
- **Slow peer**: The shared range_queue naturally load-balances — faster peers take more ranges. A slow peer just contributes less throughput.
- **in_flight counter**: Per-peer (inside each `run_block_fetch_pipelined` instance), not shared. Each peer manages its own pipeline depth independently.

## Testing

**Unit tests** (`test_multi_peer_blockfetch.py`):
- Two fake channels sharing range_queue and block_queue — verify both peers fetch different ranges
- Verify processor receives blocks from both peers
- Verify peer disconnect re-enqueues in-flight ranges
- Verify NoBlocks response re-enqueues the range
- Verify nonce worker walks chain fragment sequentially
- Verify ChainDB handles out-of-order block arrival (gap-filling via successor walk)

**Integration**: Devnet with 2 Haskell nodes (we have this already).

**Devnet soak**: 15-minute test verifying block production still works.

**Existing tests**: All current blockfetch and chaindb tests stay green — backward compatible.

## Success Criteria

bps measurably above 340 on Preview testnet with multiple peers. Each additional peer should contribute incremental throughput since we're bandwidth-bound per peer. Multiple Preview relay endpoints will need to be configured in `VIBE_PEERS` (e.g. multiple IOG relays or discovered peers). Devnet soak test confirms block production still works.

**Benchmark methodology:** Do NOT clear the existing Preview sync volume. Resume from the current chain position so we're comparing bps at the same chain depth and block density. Wiping the volume restarts from genesis where blocks are tiny and artificially inflates bps numbers.
