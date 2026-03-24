# Chain Follower Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a per-client follower state machine in NodeKernel so chain-sync servers correctly handle fork switches with MsgRollBackward, eliminating UnexpectedPrevHash errors.

**Architecture:** Each chain-sync server gets a `ChainFollower` object that tracks the client's position on the chain. When `NodeKernel.add_block()` performs a fork switch (removing orphaned blocks), it notifies all followers. Any follower whose position is on the orphaned suffix transitions to a `ROLL_BACK` state. The chain-sync server checks the follower state before serving — if a rollback is pending, it sends `MsgRollBackward` before continuing with new blocks.

**Tech Stack:** Python 3.14, asyncio, pytest

**Spec:** `docs/superpowers/specs/2026-03-23-chain-follower-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `packages/vibe-cardano/src/vibe/cardano/node/kernel.py` | Modify | Add `ChainFollower` class, follower registry, `_notify_fork_switch()`. Modify `add_block() → bool`. Move chain-sync serving logic into follower. |
| `packages/vibe-cardano/src/vibe/cardano/network/chainsync_protocol.py` | Modify | Update `run_chain_sync_server` to accept `ChainFollower` instead of `ChainProvider`. Update `ChainProvider` interface. |
| `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py` | Modify | Create follower on peer connect, close on disconnect. |
| `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py` | Modify | Check `add_block` return value. Remove kernel tip cross-check. |
| `packages/vibe-cardano/tests/node/test_chain_follower.py` | Create | Unit tests for follower state machine, fork switch notification, `add_block` return value. |

---

### Task 1: ChainFollower Class and Follower Registry

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py`
- Create: `packages/vibe-cardano/tests/node/test_chain_follower.py`

- [ ] **Step 1: Write failing tests for ChainFollower state machine**

Create `packages/vibe-cardano/tests/node/test_chain_follower.py`:

```python
"""Tests for ChainFollower state machine and NodeKernel follower management."""

from __future__ import annotations

import asyncio

import pytest

from vibe.cardano.node.kernel import BlockEntry, NodeKernel
from vibe.cardano.network.chainsync import Point, ORIGIN


def _make_block_entry(slot: int, block_number: int, block_hash: bytes,
                      predecessor_hash: bytes = b"\x00" * 32,
                      header_cbor: bytes = b"hdr",
                      block_cbor: bytes = b"blk") -> dict:
    """Helper to build add_block kwargs."""
    return dict(
        slot=slot,
        block_hash=block_hash,
        block_number=block_number,
        predecessor_hash=predecessor_hash,
        header_cbor=header_cbor,
        block_cbor=block_cbor,
    )


def _hash(n: int) -> bytes:
    """Generate a deterministic 32-byte hash from an integer."""
    return n.to_bytes(32, "big")


class TestChainFollowerBasic:
    """Test follower creation, lifecycle, and basic state."""

    def test_new_follower_starts_at_origin(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()
        assert follower.client_point is ORIGIN or follower.client_point == ORIGIN
        assert follower._pending_rollback is None

    def test_close_follower_removes_from_registry(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()
        fid = follower.id
        assert fid in kernel._followers
        kernel.close_follower(fid)
        assert fid not in kernel._followers

    def test_multiple_followers_independent(self):
        kernel = NodeKernel()
        f1 = kernel.new_follower()
        f2 = kernel.new_follower()
        assert f1.id != f2.id
        assert len(kernel._followers) == 2


class TestFollowerInstruction:
    """Test follower.instruction() returns correct actions."""

    @pytest.mark.asyncio
    async def test_instruction_on_empty_chain_awaits(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()
        action, header, point, tip = await asyncio.wait_for(
            follower.instruction(), timeout=0.2,
        )
        assert action == "await"

    @pytest.mark.asyncio
    async def test_instruction_rolls_forward_after_block(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()
        kernel.add_block(**_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1),
        ))
        action, header, point, tip = await follower.instruction()
        assert action == "roll_forward"
        assert point == Point(slot=1, hash=_hash(1))

    @pytest.mark.asyncio
    async def test_instruction_advances_client_point(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()
        kernel.add_block(**_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1),
        ))
        kernel.add_block(**_make_block_entry(
            slot=2, block_number=2, block_hash=_hash(2),
            predecessor_hash=_hash(1),
        ))
        # First instruction: block 1
        action1, _, point1, _ = await follower.instruction()
        assert action1 == "roll_forward"
        assert point1 == Point(slot=1, hash=_hash(1))
        # Second instruction: block 2
        action2, _, point2, _ = await follower.instruction()
        assert action2 == "roll_forward"
        assert point2 == Point(slot=2, hash=_hash(2))


class TestFollowerForkSwitch:
    """Test follower rollback on fork switch."""

    @pytest.mark.asyncio
    async def test_fork_switch_triggers_rollback(self):
        kernel = NodeKernel()
        follower = kernel.new_follower()

        # Build chain: block1 → block2_forged
        kernel.add_block(**_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1),
        ))
        kernel.add_block(**_make_block_entry(
            slot=2, block_number=2, block_hash=_hash(2),
            predecessor_hash=_hash(1), is_forged=True,
        ))

        # Follower reads both blocks
        await follower.instruction()  # block 1
        await follower.instruction()  # block 2 (forged)

        # Now a received block at block_number=3 with pred=block1 (forks off)
        kernel.add_block(**_make_block_entry(
            slot=3, block_number=3, block_hash=_hash(3),
            predecessor_hash=_hash(1),
        ))

        # Follower's position (block2_forged) was orphaned.
        # Next instruction should be a rollback to block1.
        action, _, point, _ = await follower.instruction()
        assert action == "roll_backward"
        assert point == Point(slot=1, hash=_hash(1))

        # After rollback, should roll forward with the new block
        action2, _, point2, _ = await follower.instruction()
        assert action2 == "roll_forward"
        assert point2 == Point(slot=3, hash=_hash(3))

    @pytest.mark.asyncio
    async def test_fork_switch_does_not_affect_unrelated_follower(self):
        kernel = NodeKernel()
        f_affected = kernel.new_follower()
        f_unaffected = kernel.new_follower()

        # Build chain: block1 → block2_forged
        kernel.add_block(**_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1),
        ))
        kernel.add_block(**_make_block_entry(
            slot=2, block_number=2, block_hash=_hash(2),
            predecessor_hash=_hash(1), is_forged=True,
        ))

        # f_affected reads both; f_unaffected only reads block1
        await f_affected.instruction()  # block 1
        await f_affected.instruction()  # block 2
        await f_unaffected.instruction()  # block 1 only

        # Fork switch
        kernel.add_block(**_make_block_entry(
            slot=3, block_number=3, block_hash=_hash(3),
            predecessor_hash=_hash(1),
        ))

        # f_affected should rollback
        action_a, _, _, _ = await f_affected.instruction()
        assert action_a == "roll_backward"

        # f_unaffected was at block1 (not orphaned) — should roll forward
        action_u, _, point_u, _ = await f_unaffected.instruction()
        assert action_u == "roll_forward"
        assert point_u == Point(slot=3, hash=_hash(3))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/vibe-cardano && uv run pytest tests/node/test_chain_follower.py -v`
Expected: FAIL — `NodeKernel` has no `new_follower()`, `close_follower()`, or `ChainFollower` class yet.

- [ ] **Step 3: Implement ChainFollower class and follower registry in NodeKernel**

In `packages/vibe-cardano/src/vibe/cardano/node/kernel.py`, add after `BlockEntry`:

```python
class ChainFollower:
    """Per-client chain-sync follower state machine.

    Tracks the client's read position on the chain and detects when a
    fork switch invalidates that position, producing a rollback instruction.

    Haskell ref: Ouroboros.Consensus.Storage.ChainDB.Impl.Follower
    """

    def __init__(self, follower_id: int, kernel: NodeKernel) -> None:
        self.id = follower_id
        self._kernel = kernel
        self.client_point: PointOrOrigin = ORIGIN
        self._pending_rollback: Point | None = None

    def notify_fork_switch(
        self, removed_hashes: set[bytes], intersection_point: Point,
    ) -> None:
        """Called by NodeKernel when a fork switch removes blocks.

        If this follower's client_point is in the removed set,
        transition to ROLL_BACK state.

        Haskell ref: fhSwitchFork in Follower.hs
        """
        if isinstance(self.client_point, Point):
            if self.client_point.hash in removed_hashes:
                self._pending_rollback = intersection_point

    async def find_intersect(
        self, points: list[PointOrOrigin],
    ) -> tuple[PointOrOrigin | None, Tip]:
        """Find intersection and update follower position."""
        tip = self._kernel._tip or self._kernel._genesis_tip()
        for point in points:
            if point is ORIGIN or point == ORIGIN:
                self.client_point = ORIGIN
                self._pending_rollback = None
                return ORIGIN, tip
            if isinstance(point, Point) and point.hash in self._kernel._hash_index:
                self.client_point = point
                self._pending_rollback = None
                return point, tip
        return ORIGIN, tip

    async def instruction(
        self,
    ) -> tuple[str, Any | None, PointOrOrigin | None, Tip]:
        """Get the next chain-sync instruction for this follower.

        Returns (action, header, point, tip):
        - ("roll_backward", None, rollback_point, tip) if fork switch pending
        - ("roll_forward", header_cbor, block_point, tip) if next block available
        - ("await", None, None, tip) if client is at tip

        Haskell ref: instructionSTM in Follower.hs
        """
        tip = self._kernel._tip or self._kernel._genesis_tip()

        # Check for pending rollback first (fork switch happened)
        if self._pending_rollback is not None:
            rollback_point = self._pending_rollback
            self._pending_rollback = None
            self.client_point = rollback_point
            return ("roll_backward", None, rollback_point, tip)

        chain = self._kernel._chain
        if not chain:
            return ("await", None, None, tip)

        # Find next block after client_point
        if self.client_point is ORIGIN or self.client_point == ORIGIN:
            next_idx = 0
        elif isinstance(self.client_point, Point):
            idx = self._kernel._hash_index.get(self.client_point.hash)
            if idx is not None:
                next_idx = idx + 1
            else:
                # Client's point no longer in chain — rollback to first block
                if chain:
                    rollback_point = Point(slot=chain[0].slot, hash=chain[0].block_hash)
                    self.client_point = rollback_point
                    return ("roll_backward", None, rollback_point, tip)
                return ("roll_backward", None, ORIGIN, tip)
        else:
            next_idx = 0

        if next_idx < len(chain):
            entry = chain[next_idx]
            point = Point(slot=entry.slot, hash=entry.block_hash)
            self.client_point = point
            return ("roll_forward", entry.header_cbor, point, tip)

        # Client is at tip — wait briefly for new blocks
        try:
            await asyncio.wait_for(
                self._kernel.tip_changed.wait(), timeout=0.5,
            )
        except TimeoutError:
            pass

        # Re-check after wake (tip may have changed)
        tip = self._kernel._tip or self._kernel._genesis_tip()

        # Check rollback again (fork switch during wait)
        if self._pending_rollback is not None:
            rollback_point = self._pending_rollback
            self._pending_rollback = None
            self.client_point = rollback_point
            return ("roll_backward", None, rollback_point, tip)

        chain = self._kernel._chain
        if next_idx < len(chain):
            entry = chain[next_idx]
            point = Point(slot=entry.slot, hash=entry.block_hash)
            self.client_point = point
            return ("roll_forward", entry.header_cbor, point, tip)

        return ("await", None, None, tip)
```

Add follower registry to `NodeKernel.__init__`:

```python
self._followers: dict[int, ChainFollower] = {}
self._next_follower_id: int = 0
```

Add methods to `NodeKernel`:

```python
def new_follower(self) -> ChainFollower:
    """Create a new chain-sync follower starting at Origin."""
    fid = self._next_follower_id
    self._next_follower_id += 1
    follower = ChainFollower(fid, self)
    self._followers[fid] = follower
    return follower

def close_follower(self, follower_id: int) -> None:
    """Remove a follower when the peer disconnects."""
    self._followers.pop(follower_id, None)

def _notify_fork_switch(
    self, removed: list[BlockEntry], intersection_point: Point,
) -> None:
    """Notify all followers of a fork switch.

    Haskell ref: switchTo in ChainSel.hs — notifies followers atomically
    """
    removed_hashes = {r.block_hash for r in removed}
    for follower in self._followers.values():
        follower.notify_fork_switch(removed_hashes, intersection_point)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/vibe-cardano && uv run pytest tests/node/test_chain_follower.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/kernel.py \
       packages/vibe-cardano/tests/node/test_chain_follower.py
git commit -m "feat: add ChainFollower state machine to NodeKernel

Implements the Haskell ChainDB Follower pattern for chain-sync serving.
Each follower tracks client position and detects fork switches, producing
MsgRollBackward when the client's position is orphaned.

Haskell ref: Ouroboros.Consensus.Storage.ChainDB.Impl.Follower"
```

---

### Task 2: Wire Fork Switch Notification into add_block

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py`
- Modify: `packages/vibe-cardano/tests/node/test_chain_follower.py`

- [ ] **Step 1: Write failing test for add_block return value**

Add to `test_chain_follower.py`:

```python
class TestAddBlockReturnValue:
    """Test that add_block returns bool indicating adoption."""

    def test_add_block_returns_true_on_adoption(self):
        kernel = NodeKernel()
        result = kernel.add_block(**_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1),
        ))
        assert result is True

    def test_add_block_returns_false_for_orphaned_forged(self):
        kernel = NodeKernel()
        kernel.add_block(**_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1),
        ))
        # Forged block extends block1
        kernel.add_block(**_make_block_entry(
            slot=2, block_number=2, block_hash=_hash(2),
            predecessor_hash=_hash(1), is_forged=True,
        ))
        # Now the chain tip is block2. Try forging block3 with stale pred
        result = kernel.add_block(**_make_block_entry(
            slot=3, block_number=3, block_hash=_hash(99),
            predecessor_hash=_hash(1),  # pred is block1, not block2
            is_forged=True,
        ))
        assert result is False

    def test_add_block_returns_false_for_duplicate(self):
        kernel = NodeKernel()
        kernel.add_block(**_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1),
        ))
        result = kernel.add_block(**_make_block_entry(
            slot=1, block_number=1, block_hash=_hash(1),
        ))
        assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/vibe-cardano && uv run pytest tests/node/test_chain_follower.py::TestAddBlockReturnValue -v`
Expected: FAIL — `add_block` currently returns `None`.

- [ ] **Step 3: Modify add_block to return bool and call _notify_fork_switch**

In `kernel.py`, change `add_block` signature to `-> bool` and:
- Return `False` at every early-return point (skipped forged, duplicate, etc.)
- Return `True` after the block is added and tip is updated
- At both fork switch locations (lines 358-366 and 378-386), call `self._notify_fork_switch(removed, intersection_point)` before appending the new block

The fork switch sections become:

```python
# Fork — find fork point and switch.
fork_idx = self._hash_index.get(predecessor_hash)
if fork_idx is not None:
    removed = self._chain[fork_idx + 1:]
    intersection_point = Point(
        slot=self._chain[fork_idx].slot,
        hash=self._chain[fork_idx].block_hash,
    )
    for r in removed:
        self._hash_index.pop(r.block_hash, None)
    self._chain = self._chain[:fork_idx + 1]
    self._notify_fork_switch(removed, intersection_point)
    idx = len(self._chain)
    self._chain.append(entry)
    self._hash_index[block_hash] = idx
    logger.info(...)
```

Apply this pattern to both fork switch locations (block_number > tip and block_number == tip).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/vibe-cardano && uv run pytest tests/node/test_chain_follower.py -v`
Expected: All tests PASS (both new and existing).

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/kernel.py \
       packages/vibe-cardano/tests/node/test_chain_follower.py
git commit -m "feat: add_block returns bool, notifies followers on fork switch

add_block now returns True if the block became the new tip, False if
skipped. Fork switches call _notify_fork_switch to set pending rollback
on any follower whose position was orphaned."
```

---

### Task 3: Update Chain-Sync Server to Use ChainFollower

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/network/chainsync_protocol.py` (lines 740-830)
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py` (lines 192-203, 264-266)

- [ ] **Step 1: Update run_chain_sync_server signature**

In `chainsync_protocol.py`, change `run_chain_sync_server` to accept a `follower` parameter instead of `chain_provider`:

```python
async def run_chain_sync_server(
    channel: MiniProtocolChannel,
    follower: Any = None,          # ChainFollower (new)
    chain_provider: Any = None,    # Deprecated — kept for backward compat
    stop_event: asyncio.Event | None = None,
) -> None:
```

If `follower` is provided, use it. Otherwise fall back to `chain_provider` (backward compat for tests).

- [ ] **Step 2: Route MsgFindIntersect through follower**

Replace the `MsgFindIntersect` handler:

```python
if isinstance(msg, CsMsgFindIntersect):
    if follower is not None:
        intersect, tip = await follower.find_intersect(msg.points)
    else:
        intersect, tip = await chain_provider.find_intersect(msg.points)
    if intersect is not None:
        await runner.send_message(
            CsMsgIntersectFound(point=intersect, tip=tip)
        )
    else:
        await runner.send_message(CsMsgIntersectNotFound(tip=tip))
```

- [ ] **Step 3: Route MsgRequestNext through follower**

Replace the `MsgRequestNext` handler — remove the local `client_point` tracking:

```python
elif isinstance(msg, CsMsgRequestNext):
    if follower is not None:
        action, header, point, tip = await follower.instruction()
    else:
        action, header, point, tip = await chain_provider.next_block(client_point)

    if action == "roll_forward" and header is not None:
        if follower is None:
            client_point = point
        await runner.send_message(
            CsMsgRollForward(header=header, tip=tip)
        )
    elif action == "roll_backward" and point is not None:
        if follower is None:
            client_point = point
        await runner.send_message(
            CsMsgRollBackward(point=point, tip=tip)
        )
    elif action == "await":
        await runner.send_message(CsMsgAwaitReply())
        # Poll for data in MustReply state
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return
                if follower is not None:
                    action2, header2, point2, tip2 = await follower.instruction()
                else:
                    action2, header2, point2, tip2 = await chain_provider.next_block(client_point)
                if action2 == "roll_forward" and header2 is not None:
                    if follower is None:
                        client_point = point2
                    await runner.send_message(
                        CsMsgRollForward(header=header2, tip=tip2)
                    )
                    break
                elif action2 == "roll_backward" and point2 is not None:
                    if follower is None:
                        client_point = point2
                    await runner.send_message(
                        CsMsgRollBackward(point=point2, tip=tip2)
                    )
                    break
                await asyncio.sleep(0.1)
        except (asyncio.CancelledError, Exception) as exc:
            ...  # existing error handling
```

- [ ] **Step 4: Update inbound_server.py to create/close followers**

In `inbound_server.py`, in `handle_connection`:

```python
# Before the chain-sync server launch (line ~192):
follower = None
if node_kernel is not None:
    follower = node_kernel.new_follower()

# Launch chain-sync server with follower:
if node_kernel is not None:
    asyncio.create_task(
        _safe_server(
            run_chain_sync_server(
                channels[CHAIN_SYNC_N2N_ID],
                follower=follower,
                stop_event=stop,
            ),
            "chain-sync",
        ),
        name=f"cs-server-{peer_info}",
    )
```

In the `finally` block (line ~264):

```python
finally:
    stop.set()
    if follower is not None and node_kernel is not None:
        node_kernel.close_follower(follower.id)
    await mux.close()
```

- [ ] **Step 5: Run existing tests to verify nothing breaks**

Run: `cd packages/vibe-cardano && uv run pytest tests/ -x -q --timeout=30`
Expected: All existing tests PASS (backward compat preserved via `chain_provider` fallback).

- [ ] **Step 6: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/network/chainsync_protocol.py \
       packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py
git commit -m "feat: chain-sync server uses ChainFollower for fork-safe serving

run_chain_sync_server now accepts a ChainFollower that handles
client position tracking and fork switch rollbacks. Inbound server
creates a follower per peer and cleans up on disconnect.

Backward compat: chain_provider parameter still works for existing tests."
```

---

### Task 4: Update Forge Loop

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py`

- [ ] **Step 1: Check add_block return value**

In `forge_loop.py`, change the `node_kernel.add_block(...)` call (around line 280) to check the return:

```python
if node_kernel is not None:
    adopted = node_kernel.add_block(
        slot=forged.block.slot,
        block_hash=forged.block.block_hash,
        block_number=forged.block.block_number,
        header_cbor=[6, cbor2.CBORTag(24, forged.block.header_cbor)],
        block_cbor=forged.cbor,
        predecessor_hash=forged_predecessor,
        is_forged=True,
    )
    if not adopted:
        logger.info(
            "Forged block #%d at slot %d orphaned (tip changed)",
            forged.block.block_number, forged.block.slot,
        )
        # Don't update prev_header_hash — it's stale
        prev_header_hash = forged_predecessor
        prev_block_number = forged.block.block_number - 1
        continue
```

- [ ] **Step 2: Remove the kernel tip cross-check**

Remove the block added earlier in this session that cross-checks `node_kernel.tip` against `prev_header_hash` (the `if node_kernel is not None and node_kernel.tip is not None:` block around line 216). The follower makes this unnecessary.

- [ ] **Step 3: Run existing forge tests**

Run: `cd packages/vibe-cardano && uv run pytest tests/forge/ tests/node/ -x -q --timeout=30`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py
git commit -m "feat: forge loop checks add_block adoption, removes tip cross-check

If add_block returns False (block orphaned by concurrent received block),
the forge loop resets local state instead of corrupting predecessor tracking."
```

---

### Task 5: Integration Test — Devnet Verification

**Files:** None (runtime test)

- [ ] **Step 1: Rebuild vibe-node container**

```bash
cd infra/devnet
docker compose -f docker-compose.devnet.yml down -v
docker compose -f docker-compose.devnet.yml build vibe-node
```

- [ ] **Step 2: Start devnet**

```bash
docker compose -f docker-compose.devnet.yml up -d
```

- [ ] **Step 3: Wait 90 seconds for blocks to accumulate**

```bash
sleep 90
```

- [ ] **Step 4: Check for zero VRF/header errors**

```bash
docker logs devnet-haskell-node-1-1 2>&1 | \
  grep -i "VRFLeaderValueTooBig\|VRFKeyBadProof\|UnexpectedPrevHash\|InvalidBlock\|HeaderError" | \
  grep -v "Configuration\|ErrorPolicy\|ConnectionError\|ConnectError"
```

Expected: No output (zero errors).

- [ ] **Step 5: Verify vibe-forged blocks in Haskell chain**

```bash
HASKELL_SLOTS=$(docker logs devnet-haskell-node-1-1 2>&1 | \
  grep "AddedToCurrentChain" | sed 's/.*slot //' | sed 's/[^0-9].*//')
VIBE_SLOTS=$(docker logs devnet-vibe-node-1 2>&1 | \
  grep "Forged block" | sed 's/.*slot //' | sed 's/ .*//' | sort -un)
echo "Vibe forged slots:"
echo "$VIBE_SLOTS"
echo ""
echo "In Haskell chain:"
while read -r slot; do
    [ -z "$slot" ] && continue
    if echo "$HASKELL_SLOTS" | grep -qx "$slot"; then
        echo "  Slot $slot: ACCEPTED"
    else
        echo "  Slot $slot: not in chain"
    fi
done <<< "$VIBE_SLOTS"
```

Expected: Majority of forged slots show ACCEPTED. Some may be "not in chain" due to legitimate chain selection (another pool had a better block for that slot), but zero should be due to validation errors.

- [ ] **Step 6: Tear down devnet**

```bash
docker compose -f docker-compose.devnet.yml down -v
```
