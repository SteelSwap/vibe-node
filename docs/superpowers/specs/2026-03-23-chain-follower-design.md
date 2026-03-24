# Chain Follower State Machine — Design Spec

**Date:** 2026-03-23
**Status:** Approved
**Fixes:** Bug #14 (UnexpectedPrevHash) from forge-loop-comparison.md

---

## Problem

When `NodeKernel` does a fork switch (removing a forged block in favor of a received block), any chain-sync client that already received the forged block's header gets `UnexpectedPrevHash` on the next block. The predecessor link is broken because the served chain mutated under the client.

## Solution

Implement the Haskell ChainDB Follower pattern: a per-client state machine that tracks position on the chain and detects when fork switches invalidate that position, sending `MsgRollBackward` before continuing with the new chain.

## Architecture

### ChainFollower State Machine

```
┌─────────────────────┐     fork switch orphans      ┌──────────────────┐
│ ROLL_FORWARD(point)  │ ───── client_point ────────> │ ROLL_BACK(point)  │
└─────────────────────┘                               └──────────────────┘
         ▲                                                     │
         │              instruction() consumed                 │
         └─────────────────────────────────────────────────────┘
```

**States:**
- `ROLL_FORWARD` — Normal. `instruction()` returns `AddBlock(next_header)` or waits.
- `ROLL_BACK` — Must rollback. `instruction()` returns `RollBack(rollback_point)`, then transitions to `ROLL_FORWARD` from that point.

**Haskell ref:** `Ouroboros.Consensus.Storage.ChainDB.Impl.Follower` — `switchFork`, `instructionSTM`

### ChainFollower Class

```python
class ChainFollower:
    id: int
    _kernel: NodeKernel          # Back-reference for chain access
    client_point: PointOrOrigin  # Where the client currently is
    _pending_rollback: Point | None  # Set during fork switch
```

**Methods:**
- `find_intersect(points) → (point | None, Tip)` — Sets client_point to intersection
- `instruction() → (action, header | None, point | None, Tip)` — Returns next chain-sync message
  - If `_pending_rollback` is set: returns `("roll_backward", None, rollback_point, tip)`, clears rollback, sets client_point to rollback_point
  - Else: finds next block after client_point in kernel's chain, returns `("roll_forward", header, point, tip)` or `("await", None, None, tip)`
- `notify_fork_switch(removed_hashes: set[bytes], intersection_point: Point)` — If `client_point.hash` is in `removed_hashes`, sets `_pending_rollback = intersection_point`

### NodeKernel Changes

**New fields:**
```python
_followers: dict[int, ChainFollower]
_next_follower_id: int
```

**New methods:**
- `new_follower() → ChainFollower` — Creates follower at Origin, registers in `_followers`
- `close_follower(follower_id)` — Removes from `_followers`

**Modified: `add_block() → bool`**
- Returns `True` if block became tip, `False` if skipped/orphaned
- On fork switch (where blocks are removed from chain): calls `_notify_fork_switch(removed_hashes, intersection_point)` which iterates all followers

**Removed from NodeKernel:**
- `next_block()` — logic moves to `ChainFollower.instruction()`
- `find_intersect()` — logic moves to `ChainFollower.find_intersect()`
- `get_tip()` stays (stateless)
- `get_blocks()` stays (stateless, used by block-fetch)

### Chain-Sync Server Changes

**`chainsync_protocol.py` — `run_chain_sync_server`:**
- Parameter changes: accepts `ChainFollower` instead of `ChainProvider`
- `MsgFindIntersect` → `follower.find_intersect(points)`
- `MsgRequestNext` → `follower.instruction()`
- Removes local `client_point` tracking (follower owns this state)

**`ChainProvider` interface:**
- `next_block()` and `find_intersect()` removed from the interface
- `get_tip()` remains
- Classes implementing `ChainProvider` only need `get_tip()` now

### Inbound Server Changes

**`inbound_server.py`:**
- On peer connect: `follower = node_kernel.new_follower()`
- Pass `follower` to `run_chain_sync_server`
- On peer disconnect: `node_kernel.close_follower(follower.id)`

### Forge Loop Changes

**`forge_loop.py`:**
- `add_block()` now returns `bool` — check return value
- If `False` (orphaned): don't update `prev_header_hash` / `prev_block_number`
- Remove the NodeKernel tip cross-check added earlier (follower makes it unnecessary)

## Concurrency Model

All code runs in a single asyncio event loop. `add_block` is synchronous (not async), so follower notification happens atomically with the chain mutation — no race between chain update and follower state update. This matches the Haskell STM transaction that updates `cdbChain` and notifies followers atomically.

The only async boundary is `instruction()` waiting for `tip_changed` when the client is at tip. This uses `asyncio.Event` (existing pattern).

## File Change Map

| File | Change |
|------|--------|
| `kernel.py` | Add `ChainFollower`, follower registry, `_notify_fork_switch`. Modify `add_block → bool`. Move `next_block`/`find_intersect` to follower. |
| `chainsync_protocol.py` | `run_chain_sync_server` takes `ChainFollower` instead of `ChainProvider` + local state. |
| `inbound_server.py` | Create/close followers on peer connect/disconnect. |
| `forge_loop.py` | Check `add_block` return value. Remove kernel tip cross-check. |

## Not Changed

- `blockfetch_protocol.py` — uses `get_blocks(from, to)` which is point-based, not streaming
- `peer_manager.py` — calls `add_block` for received blocks, no follower needed (it's a consumer, not a server)

## Testing

- Unit test: follower state transitions (roll_forward → fork_switch → roll_back → roll_forward)
- Unit test: `add_block` returns False for orphaned forged blocks
- Integration test: devnet — zero `UnexpectedPrevHash` errors from Haskell nodes over 5+ minutes
- Integration test: vibe-forged blocks appear in Haskell chain (`AddedToCurrentChain` at forged slots)
