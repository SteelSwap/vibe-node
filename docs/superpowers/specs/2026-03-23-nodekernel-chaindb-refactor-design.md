# NodeKernel-ChainDB Refactor — Design Spec

**Date:** 2026-03-23
**Status:** Approved
**Fixes:** Bug #14 (UnexpectedPrevHash), NodeKernel chain management

---

## Problem

`NodeKernel._chain` is a hand-maintained list that breaks when blocks arrive from multiple peers or when forged blocks interleave with received blocks. This causes `UnexpectedPrevHash` errors when Haskell nodes chain-sync from us. We have `VolatileDB`, `ChainDB`, and `chain_selection.py` already implemented but unused by the chain-sync serving path.

## Solution

Align with the Haskell architecture: ChainDB becomes the single source of truth for the selected chain, maintains an in-memory chain fragment, and owns follower notification. NodeKernel becomes a thin coordination layer holding only the header cache and follower registry.

## Haskell Reference Architecture

```
NodeKernel
  └── getChainDB: ChainDB
        ├── cdbChain: TVar (AnchoredFragment)    ← selected chain fragment (last k blocks)
        ├── cdbVolatileDB: VolatileDB             ← all recent blocks (any fork)
        ├── cdbImmutableDB: ImmutableDB            ← finalized blocks
        ├── cdbFollowers: TVar (Map FollowerId FollowerHandle)
        └── chainSelQueue: TBQueue                 ← block processing queue

Forge loop:
  addBlockAsync(block) → blockProcessed → check adopted

Chain-sync server:
  ChainDB.newFollower → followerInstruction / followerInstructionBlocking

switchTo (fork switch):
  atomically { writeTVar cdbChain newChain; notify all followers }
```

Key Haskell refs:
- `ChainSel.hs:904` — atomic chain update + follower notification in same transaction
- `ChainSel.hs:923-929` — `fhSwitchFork` on all followers when `getRollback > 0`
- `Follower.hs:428-439` — `instructionSTM` uses `AF.successorBlock` on chain fragment
- `NodeKernel.hs:750-755` — forge loop checks `blockProcessed` against block point
- `Query.hs:106-140` — `getCurrentChain` trims `cdbChain` to last k blocks

---

## Architecture

### Data Flow

```
Block arrives (peer_manager or forge_loop)
  │
  └──→ chain_db.add_block(slot, hash, pred, bn, cbor, header_cbor)
         │
         ├── volatile_db.add_block(...)              # Store (all blocks, any fork)
         ├── _chain_selection(new_block_hash)         # Pick best chain
         │     ├── Extends current tip? → append to fragment
         │     └── Better fork? → compute diff, switch fragment, notify followers
         ├── _notify_followers(removed, intersection)  # Inside the selection, not after
         ├── Update _chain_fragment atomically
         └── return ChainSelectionResult
               │
  node_kernel.on_block_added(result, header_cbor)
         ├── Cache header_cbor
         ├── Fire tip_changed event
         └── (Follower notification already happened in ChainDB)
```

### ChainDB Changes

**New fields:**
```python
_chain_fragment: list[FragmentEntry]    # Ordered, oldest-first, last k blocks
_fragment_index: dict[bytes, int]       # hash → index in fragment
_followers: dict[int, ChainFollower]    # Per-peer followers
_next_follower_id: int
```

**FragmentEntry:**
```python
@dataclass(frozen=True, slots=True)
class FragmentEntry:
    slot: int
    block_hash: bytes
    block_number: int
    predecessor_hash: bytes
    header_cbor: Any           # Wrapped header for chain-sync serving
```

**New/modified methods:**

`add_block(slot, hash, pred, bn, cbor, header_cbor) → ChainSelectionResult`:
1. Store in VolatileDB (unchanged)
2. Compute chain diff: is this block on a better chain?
   - If extends current tip: append to `_chain_fragment`
   - If better fork: compute rollback via `_compute_chain_diff`, rebuild fragment, notify followers
   - If not better: store but don't change (returned as not adopted)
3. Trim fragment to last k entries
4. Return `ChainSelectionResult(adopted, new_tip, rollback_depth, removed_hashes, intersection_hash)`

Follower notification happens **inside** `add_block`, atomically with the fragment update. Since we're in asyncio (single-threaded cooperative), "atomically" means no `await` between fragment update and follower notification.

`_compute_chain_diff(new_block_hash) → (rollback_depth, removed_hashes, intersection_hash)`:
Walk backward from new block through VolatileDB predecessors until finding intersection with current chain. Walk backward from old tip to count rollback depth and collect removed hashes.

Haskell ref: `Paths.isReachable` + `computeReversePath`

`_rebuild_fragment_from_tip(tip_hash) → list[FragmentEntry]`:
Walk backward from tip through VolatileDB predecessor links, collect up to k entries, reverse to oldest-first order. Used after fork switches.

`get_current_chain() → list[FragmentEntry]`:
Returns `_chain_fragment` (read-only snapshot). Haskell ref: `Query.getCurrentChain`

`new_follower() → ChainFollower`:
Creates a follower starting at Origin. Registered in `_followers`.

`close_follower(follower_id)`:
Removes from `_followers`.

`_notify_fork_switch(removed_hashes, intersection_point)`:
Iterates all followers, calls `notify_fork_switch` on each. Called inside `add_block` during fork switch.

**ChainSelectionResult:**
```python
@dataclass(frozen=True, slots=True)
class ChainSelectionResult:
    adopted: bool                       # Block became new tip?
    new_tip: tuple[int, bytes, int] | None  # (slot, hash, block_number)
    rollback_depth: int                 # 0 = extension, >0 = fork switch
    removed_hashes: set[bytes]          # Orphaned block hashes
    intersection_hash: bytes | None     # Fork point (None if no rollback)
```

### NodeKernel Changes

**Removed:**
- `_chain: list[BlockEntry]` — replaced by ChainDB's `_chain_fragment`
- `_hash_index: dict[bytes, int]` — replaced by ChainDB's `_fragment_index`
- `add_block()` — callers use `chain_db.add_block()` directly
- `_notify_fork_switch()` — moved to ChainDB
- `_followers` registry — moved to ChainDB
- `new_follower()` / `close_follower()` — moved to ChainDB
- `ChainProvider` / `BlockProvider` interfaces — ChainDB handles serving

**Kept:**
- `_header_cache: dict[bytes, Any]` — **removed, moved to ChainDB** (header_cbor is stored in FragmentEntry)
- `tip_changed: asyncio.Event` — wakes chain-sync servers
- All nonce/epoch/delegation/stake state (unchanged)
- `_chain_db: ChainDB` reference

**New:**
- `on_block_added(result: ChainSelectionResult)` — fires `tip_changed` if adopted. (Follower notification already happened in ChainDB.)

Actually, on reflection: `tip_changed` should also move to ChainDB since it's fired as part of the chain update. NodeKernel then just holds nonce/delegation/stake state.

**Revised NodeKernel:**
```python
class NodeKernel:
    _chain_db: ChainDB              # Source of truth
    # Praos chain-dependent state
    _epoch_nonce: EpochNonce
    _evolving_nonce, _candidate_nonce, _lab_nonce, _last_epoch_block_nonce: bytes
    _current_epoch: int
    _epoch_length, _security_param: int
    _active_slot_coeff: float
    # Delegation / stake
    _delegation_state: DelegationState
    _stake_distribution: dict[bytes, int]
    _protocol_params: dict[str, Any]
```

### ChainFollower Changes

`ChainFollower` moves to ChainDB (or stays in kernel.py but references ChainDB). The `instruction()` method reads from ChainDB's `_chain_fragment`:

```python
async def instruction(self) -> tuple[str, Any | None, PointOrOrigin | None, Tip]:
    # 1. Pending rollback?
    if self._pending_rollback is not None:
        rollback_point = self._pending_rollback
        self._pending_rollback = None
        self.client_point = rollback_point
        return ("roll_backward", None, rollback_point, tip)

    # 2. Find next block in chain fragment
    fragment = self._chain_db._chain_fragment
    fragment_index = self._chain_db._fragment_index

    if client_point is ORIGIN:
        next_idx = 0
    else:
        idx = fragment_index.get(client_point.hash)
        if idx is not None:
            next_idx = idx + 1
        else:
            # Point not in fragment — rollback to fragment anchor
            if fragment:
                anchor = Point(slot=fragment[0].slot, hash=fragment[0].block_hash)
                self.client_point = anchor
                return ("roll_backward", None, anchor, tip)
            return ("roll_backward", None, ORIGIN, tip)

    if next_idx < len(fragment):
        entry = fragment[next_idx]
        point = Point(slot=entry.slot, hash=entry.block_hash)
        self.client_point = point
        return ("roll_forward", entry.header_cbor, point, tip)

    # 3. At tip — wait
    await chain_db.tip_changed.wait() (with timeout)
    ... re-check ...
```

Haskell ref: `instructionSTM` uses `AF.successorBlock(pt, curChain)` — our `fragment_index[pt.hash] + 1` is the equivalent.

### Caller Changes

**peer_manager.py:**
```python
# Before (two calls):
await chain_db.add_block(slot, hash, pred, bn, cbor)
node_kernel.add_block(slot, hash, bn, header_cbor, cbor, pred)

# After (one call):
result = await chain_db.add_block(slot, hash, pred, bn, cbor, header_cbor)
# Praos nonce updates (still on NodeKernel):
if result.adopted:
    node_kernel.on_block_adopted(slot, pred, vrf_output)
```

**forge_loop.py:**
```python
# Before:
await chain_db.add_block(...)
node_kernel.add_block(..., is_forged=True)

# After:
result = await chain_db.add_block(slot, hash, pred, bn, cbor, header_cbor)
if not result.adopted:
    logger.info("Forged block orphaned")
    continue
node_kernel.on_block_adopted(slot, pred, vrf_output)
```

**inbound_server.py:**
```python
# Before:
follower = node_kernel.new_follower()
node_kernel.close_follower(follower.id)

# After:
follower = chain_db.new_follower()
chain_db.close_follower(follower.id)
```

**run.py:**
```python
# Pass chain_db to NodeKernel
node_kernel = NodeKernel(chain_db=chain_db)
```

### BlockProvider (block-fetch)

Block-fetch serves full block CBOR, not headers. It uses point-based lookup:
```python
async def get_blocks(self, point_from, point_to) -> list[bytes]:
    # Walk from point_from to point_to through VolatileDB/ImmutableDB
    # Return block CBOR bytes
```

This moves to ChainDB (which already has `get_block(hash)` for lookups). The block-fetch server references ChainDB directly instead of NodeKernel.

---

## File Change Map

| File | Change |
|------|--------|
| `storage/chaindb.py` | Add `_chain_fragment`, `_fragment_index`, `_followers`, `tip_changed`. Add `_compute_chain_diff`, `_rebuild_fragment_from_tip`, `new_follower`, `close_follower`, `_notify_fork_switch`. Modify `add_block` to accept `header_cbor`, return `ChainSelectionResult`, maintain fragment, notify followers. Add `get_current_chain()`. Add `get_blocks()` for block-fetch. |
| `node/kernel.py` | Remove `_chain`, `_hash_index`, `add_block`, `_followers`, `new_follower`, `close_follower`, `_notify_fork_switch`, `ChainProvider`/`BlockProvider` interfaces. Add `_chain_db` reference. Simplify to nonce/delegation/stake state + `on_block_adopted()`. Move `ChainFollower` to reference ChainDB. |
| `node/peer_manager.py` | Remove `node_kernel.add_block()` call. Use `chain_db.add_block()` result. Call `node_kernel.on_block_adopted()` for nonce updates. |
| `node/forge_loop.py` | Remove `node_kernel.add_block()` call. Use `chain_db.add_block()` result. Check `result.adopted`. |
| `node/inbound_server.py` | Create/close followers from `chain_db` instead of `node_kernel`. Pass `chain_db` for block-fetch. |
| `node/run.py` | Pass `chain_db` to `NodeKernel.__init__`. |
| `network/chainsync_protocol.py` | No changes (already uses follower). |
| `tests/node/test_chain_follower.py` | Update to create ChainDB + VolatileDB fixtures. Test follower via ChainDB. |

---

## Concurrency Model

All code runs in a single asyncio event loop. `chain_db.add_block()` is async but follower notification happens synchronously (no `await`) within the same call, before returning. This gives us the Haskell equivalent of "atomic transaction" — no other coroutine runs between the fragment update and follower notification.

The `tip_changed` event (on ChainDB) is set after notification, waking any followers blocked in `instruction()`.

---

## Testing

### Unit tests
- ChainDB: `add_block` returns correct `ChainSelectionResult` for extend, fork switch, not-adopted
- ChainDB: `_chain_fragment` is correct after series of blocks
- ChainDB: `_compute_chain_diff` returns correct rollback depth and removed hashes
- ChainFollower: `instruction()` returns roll_forward from fragment
- ChainFollower: fork switch triggers rollback, then roll_forward with new chain
- ChainFollower: unaffected follower continues normally after fork switch

### Integration test
- Devnet: zero `UnexpectedPrevHash` errors from Haskell nodes over 5+ minutes
- Devnet: majority of vibe-forged blocks appear in Haskell chain (`AddedToCurrentChain`)
