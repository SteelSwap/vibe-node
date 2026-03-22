# Forge Loop: Haskell vs vibe-node Comparison

Step-by-step comparison of the Haskell `forkBlockForging` (NodeKernel.hs:566-740) against our `_forge_loop` (run.py:827-1082). Each difference is flagged as a potential bug.

---

## Step 1: Block Context (prev_hash + block_number)

### Haskell (lines 574-584)
```haskell
BlockContext{bcBlockNo, bcPrevPoint} <- do
  eBlkCtx <- atomically $
    mkCurrentBlockContext currentSlot <$> ChainDB.getCurrentChain chainDB
  case eBlkCtx of
    Right blkCtx -> return blkCtx
    Left failure -> exitEarly
```
- Reads the **current chain fragment** from ChainDB (volatile tip + headers)
- `mkCurrentBlockContext` (line 836) finds the tip header
- `bcBlockNo = succ (blockNo tipHeader)` — block number is **previous block's number + 1**
- `bcPrevPoint = headerPoint tipHeader` — point is the tip header's **(slot, hash)** where hash = `hashAnnotated` of the header

### vibe-node (lines 1014-1030)
```python
tip = await chain_db.get_tip()
if tip is not None:
    tip_slot = tip[0]
    prev_header_hash = tip[1]
    prev_block_number = tip_slot  # ← BUG: uses slot as block number
```

### **BUG 1: `prev_block_number = tip_slot`**
We use the **slot number** as the block number. The Haskell node uses `succ (blockNo tipHeader)` — the actual block number from the header, which is different from the slot number. Slots can be empty (no block produced), so slot numbers grow faster than block numbers. On a chain with 10% active slots, slot 100 might have block number 10.

**Impact:** Our forged blocks have wrong `block_number` in the header. The receiving Haskell node checks `blockNo == prev_blockNo + 1` and this will fail.

**Fix:** ChainDB.get_tip() should return `(slot, hash, block_number)`, or we need to read the actual block number from the stored block header.

---

## Step 2: Ledger State and Forecast

### Haskell (lines 594-627)
```haskell
forker <- ChainDB.getReadOnlyForkerAtPoint chainDB reg (SpecificPoint bcPrevPoint)
unticked <- atomically $ LedgerDB.roforkerGetLedgerState forker
ledgerView <- forecastFor (ledgerViewForecastAt (configLedger cfg) (ledgerState unticked)) currentSlot
```
- Gets a **read-only fork** of the ledger state at the previous block's point
- Computes the **ledger view** (protocol parameters, stake distribution) at the current slot via forecast
- **If forecast fails** (too far from tip): exits early — this is the sync gate

### vibe-node (lines 1001-1012, 917-932)
```python
epoch_nonce = node_kernel.epoch_nonce.value  # computed once at startup
relative_stake = ...  # computed once at startup from genesis
proof = check_leadership(slot, vrf_sk, ..., relative_stake, active_slot_coeff, epoch_nonce)
```

### **BUG 2: Epoch nonce is stale**
We compute `epoch_nonce` once at startup from the genesis hash and only evolve it via `on_epoch_boundary()` during block sync. The Haskell node ticks the chain-dependent state **per slot** to get the current nonce for leader checking. If we're multiple epochs into the chain, our nonce is wrong.

**Impact:** VRF proofs are computed with the wrong nonce. The receiving Haskell node recomputes the VRF with the correct nonce and our proof fails verification.

**Fix:** Re-read `epoch_nonce` from `node_kernel` inside the per-slot loop, not once at startup.

### **BUG 3: Relative stake is stale**
We compute `relative_stake` once at startup from genesis. The Haskell node uses the ledger view from the ticked state, which has the stake distribution from the **2-epoch-old snapshot**. After the first epoch boundary, our stake is wrong.

**Impact:** Leader threshold check uses wrong stake, but since this only affects whether WE think we're a leader (not the VRF proof itself), the impact is: we might forge when we shouldn't, or miss slots we should lead.

**Fix:** Re-read stake distribution from `node_kernel` inside the per-slot loop.

---

## Step 3: Leader Check

### Haskell (lines 643-668)
```haskell
shouldForge <- checkShouldForge blockForging ... cfg currentSlot tickedChainDepState
```
- Calls `checkShouldForge` which first does `updateForgeState` (KES evolution), then `checkIsLeader`
- The `tickedChainDepState` is the protocol state **ticked to the current slot**
- VRF input uses `mkSeed seedEta slot eta0` and `mkSeed seedL slot eta0`

### vibe-node (lines 1001-1012)
```python
proof = check_leadership(slot, vrf_sk, pool_vrf_vk, relative_stake, active_slot_coeff, epoch_nonce)
```

### **BUG 4: VRF seed construction may differ**
Our `check_leadership` computes `alpha = epoch_nonce || slot_be64`. The Haskell `mkSeed` computes:
```haskell
mkSeed seedEta slot nonce = hashToNonce(certNatMax(VRF.eval(sk, nonce || slot_bytes)))
```
Actually `mkSeed` computes `hash(nonce ⊕ slotToSeed slot ⊕ extraEntropy)`. Need to verify our VRF input matches.

**Impact:** If the VRF input differs, the proof is invalid.

**Fix:** Compare `_make_vrf_input` against `mkSeed` byte-for-byte.

---

## Step 4: Tick Ledger State

### Haskell (lines 674-683)
```haskell
let tickedLedgerState = applyChainTick OmitLedgerEvents (configLedger cfg) currentSlot (ledgerState unticked)
_ <- evaluate tickedLedgerState
```
- **Ticks the full ledger state** to the current slot (epoch transitions, etc.)
- This ticked state is used for mempool snapshot and block construction

### vibe-node
**Missing entirely.** We don't tick the ledger state. We just read the latest ChainDB tip.

### **BUG 5: No ledger tick**
Without ticking, the ledger state used for mempool tx selection and block construction doesn't reflect the current slot's epoch/protocol parameters. For simple empty blocks this doesn't matter, but for blocks with transactions it would cause validation failures.

---

## Step 5: Mempool Snapshot

### Haskell (lines 692-711)
```haskell
mempoolSnapshot <- getSnapshotFor mempool currentSlot tickedLedgerState readTables
let (txs, txssz) = snapshotTake mempoolSnapshot $ blockCapacityTxMeasure ...
```
- Gets a mempool snapshot **consistent with the ticked ledger state**
- Selects txs that fit within the block capacity at the current protocol parameters

### vibe-node (lines 1038-1041)
```python
mempool_txs=[vtx.tx_cbor for vtx in (await mempool.get_txs_for_block(65536))] if mempool else []
```

### Difference: Minor
We use a hardcoded 65536 byte limit instead of computing from the ticked ledger's `maxBlockBodySize`. For empty devnet blocks this doesn't matter.

---

## Step 6: Block Construction

### Haskell (lines 721-731)
```haskell
newBlock <- Block.forgeBlock blockForging cfg bcBlockNo currentSlot (forgetLedgerTables tickedLedgerState) txs proof
```
- Passes `bcBlockNo` (correct block number from chain tip + 1)
- Passes `proof` (IsLeader proof with correct VRF outputs)
- Internally calls `forgeShelleyBlock` which builds BHBody with all 14 fields

### vibe-node (lines 1034-1047)
```python
forged = forge_block(
    leader_proof=proof,
    prev_block_number=prev_block_number,  # ← BUG: slot number, not block number
    prev_header_hash=prev_header_hash,
    ...
)
```

### BUG 1 repeated: `prev_block_number` is wrong (uses slot number as proxy)

---

## Step 7: Post-Forge

### Haskell (lines 740-748)
```haskell
result <- lift $ ChainDB.addBlockAsync chainDB invalidBlockPunishment newBlock
_ <- lift $ atomically $ ChainDB.blockProcessed result
```
- Adds block to ChainDB via the async path
- **Waits for processing** — this ensures chain selection runs before continuing
- The block becomes part of the selected chain BEFORE the next slot

### vibe-node (lines 1053-1075)
```python
await chain_db.add_block(slot=..., block_hash=..., ...)
node_kernel.add_block(slot=..., block_hash=..., ...)
```

### Difference: We don't wait for chain selection
We store the block but don't trigger or wait for chain selection. The Haskell node's `addBlockAsync` + `blockProcessed` ensures the block is fully integrated (validated, chain selection done, followers notified) before the forge loop continues. We just store and move on.

**Impact:** Our chain-sync server may not immediately serve the new block to peers. The ChainDB follower notification path is disconnected.

---

## Summary of Bugs

| # | Bug | Severity | Status | Fix |
|---|-----|----------|--------|-----|
| **1** | `prev_block_number` uses slot number, not actual block number | **CRITICAL** | FIXED | ChainDB.get_tip() returns (slot, hash, block_number); forge loop uses real block_number |
| **2** | `epoch_nonce` read once at startup, not per-slot | **CRITICAL** | FIXED | Re-read from node_kernel each slot in forge loop |
| **3** | `relative_stake` read once at startup | **HIGH** | FIXED | Re-read from node_kernel stake_distribution each slot |
| **4** | VRF seed uses wrong algorithm (TPraos mkSeed vs Praos mkInputVRF) | **CRITICAL** | FIXED | Conway uses `mkInputVRF = blake2b(slot_be64 \|\| epochNonce)` — NO XOR with seedL constant. TPraos `mkSeed` (with XOR) is only for Shelley-Mary eras. |
| **5** | No ledger state tick before forging | **MEDIUM** | OPEN | Empty blocks work; needed for tx-bearing blocks |
| **6** | No chain selection wait after addBlock | **LOW** | OPEN | Blocks eventually propagate via tip_changed event |
| **7** | Header body used 14-field Shelley format | **CRITICAL** | FIXED | Babbage/Conway uses 10 fields with nested opcert + protver sub-arrays |
| **8** | Genesis hash from re-encoded JSON | **CRITICAL** | FIXED | Now uses raw file bytes: `genesis_path.read_bytes()` |
| **9** | NodeKernel served non-linear chain (fork mixing) | **HIGH** | FIXED | Chain selection in NodeKernel with is_forged flag; forged blocks only extend tip |

**Bugs 1 and 2 are almost certainly why Haskell nodes reject our blocks.**
