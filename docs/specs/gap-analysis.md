# Gap Analysis

## The Spec Is the Ideal. The Code Is the Reality. The Gap Is the Delta.

Cardano has formal specifications — mathematical descriptions of how the system should work. The Haskell node is the implementation — how it actually works. These don't always agree.

This section documents every divergence we discover, published like errata in a scientific publication. Where the spec says one thing and the Haskell node does another, we record it: what, where, why it matters, and how it affects our implementation.

## Data Sources

- **Knowledge base**: 1,493 spec-vs-Haskell gaps in the `gap_analysis` PostgreSQL table
- **Code audit**: M6.10 agents cross-referenced 376 critical gaps against our Python code
- **Devnet testing**: Block acceptance verification at 0.1s–1.0s slot times (M6.13)

## Aggregate Results

| Subsystem | Critical Gaps | MISSING | PARTIAL | ADDRESSED | WRONG | N/A |
|-----------|-------------|---------|---------|-----------|-------|-----|
| Ledger+Mempool | 114 | 68 | 34 | 6 | 0 | 6 |
| Consensus | 73 | 48 | 8 | 1 | 0 | 16 |
| Networking | 73 | 14 | 5 | 2 | 0 | 52† |
| Plutus | 34 | 17 | 8 | 9 | 0 | 0 |
| Storage | 28 | 17 | 7 | 0 | 1 | 3 |
| Serialization | 26 | 18 | 5 | 3 | 0 | 0 |
| **Total** | **348** | **182** | **67** | **21** | **1** | **77** |

†52 networking N/A = gaps miscategorized in DB (actually ledger/governance gaps)

**Of 348 critical gaps: 182 MISSING (52%), 67 PARTIAL (19%), 21 ADDRESSED (6%), 1 WRONG, 77 N/A (22%)**

---

## Priority 1: Block Production Correctness

These gaps cause our forged blocks to be structurally wrong. They work on devnet (empty blocks, same CBOR library) but will fail with real transactions.

### Body hash uses wrong algorithm
**Status:** MISSING
**Our code:** `forge/block.py` — `blake2b(body_cbor)` (simple hash of entire body)
**Haskell:** `hashShelleySegWits` — merkle bonsai: `hash(hash(tx_bodies) || hash(witnesses) || hash(aux_data))` (3 parts for Shelley-Mary, 4 for Alonzo+)
**Impact:** Every forged block has wrong body_hash in header.

### Re-serialized CBOR for hash computation
**Status:** MISSING
**Our code:** `serialization/block.py` — re-encodes via `cbor2.dumps()` then hashes
**Haskell:** Preserves original bytes via `MemoBytes`/`Annotator` pattern
**Impact:** CBOR has multiple valid encodings. Re-serialization changes bytes, changing hashes. Works now because cbor2pure happens to produce compatible output for our simple blocks.

### Forged block body not segregated
**Status:** PARTIAL
**Our code:** `forge/block.py` `_build_block_body` — builds 4 arrays but tx_bodies contains raw CBOR blobs instead of extracted body maps; witnesses always empty
**Haskell:** Block body = `[tx_bodies, witnesses, aux_data_map, invalid_txs]` (parallel arrays)

### Era tag wrapper missing on forged blocks
**Status:** MISSING
**Our code:** `forge_block` outputs raw block array; no HFC era tag wrapping
**Impact:** Peers using HFC-aware decoding would reject our blocks.

---

## Priority 2: Chain Selection Correctness

### No candidate chain construction from successor map
**Status:** MISSING (Storage)
**Our code:** `chaindb.py` `add_block` — compares new block vs tip only
**Haskell:** `ChainSel.chainSelectionForBlock` constructs ALL maximal candidates from VolatileDB successor map
**Impact:** Multi-block forks arriving out of order are never re-evaluated.

### No ledger validation in chain selection
**Status:** MISSING (Storage)
**Our code:** Purely compares block numbers and VRF tiebreakers
**Haskell:** Validates candidate chains against ExtLedgerState before adoption
**Impact:** Can adopt chains containing invalid blocks.

### VolatileDB GC uses <= instead of <
**Status:** WRONG (Storage)
**Our code:** `volatile.py:314` — `slot <= immutable_tip_slot`
**Haskell:** `slot < gcSlot` (strict less-than, avoids EBB issues)
**Impact:** Could GC blocks still needed during immutable promotion.

---

## Priority 3: Ledger State (Epoch Boundary)

Entire epoch boundary subsystem is missing:

| Component | Status | Impact |
|-----------|--------|--------|
| NEWEPOCH transition | MISSING | No epoch boundary processing |
| TICK/RUPD transitions | MISSING | No reward calculation trigger |
| Reward pulsing | MISSING | No incremental reward computation |
| MIR transitions | MISSING | No reserves/treasury moves |
| POOLREAP | MISSING | No pool retirement at epoch boundary |
| NEWPP | MISSING | No protocol parameter updates |
| Eta/monetary expansion | MISSING | No inflation calculation |
| Stake snapshots (SNAP) | MISSING | No proper SnapShot type |

---

## Priority 4: Plutus Script Context

### V3 ScriptContext uses ScriptPurpose not ScriptInfo
**Status:** MISSING (from earlier agent audit)
**Our code:** `plutus/context.py` `build_script_context_v3` uses V1/V2 ScriptPurpose
**Haskell:** V3 uses ScriptInfo (6 constructors, SpendingScript carries datum inline)

### V2/V3 TxOut missing 4th field
**Status:** PARTIAL
**Our code:** Always 3-field PlutusConstr (Address, Value, MaybeDatum)
**Haskell:** V2+ has 4 fields: Address, Value, OutputDatum (3-constructor sum), Maybe ScriptHash

### Reference script collection not implemented
**Status:** MISSING
**Our code:** No `indexedScripts` or `allInsScrts` that merges witness + reference scripts

---

## Priority 5: Networking

### Connection Manager / Peer Governor
**Status:** MISSING (14 gaps)
No formal ConnectionState machine (10 constructors), no inbound governor warm/hot/cold state management, no TerminatingState timeout handling, no per-protocol timeout enforcement.

### SDU Segmentation
**Status:** MISSING
Payloads > 12,288 bytes sent as single segments. Haskell splits at `sduSize`.

---

## Gaps Already Fixed (M6.13)

| Gap | Status |
|-----|--------|
| VRF leader value (blake2b_256("L" \|\| output)) | ADDRESSED |
| VRF nonce value (double-hashed "N" prefix) | ADDRESSED |
| 5-nonce model (evolving, candidate, lab, etc.) | ADDRESSED |
| Chain fragment (last k blocks in memory) | ADDRESSED |
| Follower state machine (fork switch rollback) | ADDRESSED |
| Nonce checkpoints (per-block snapshots) | ADDRESSED |
| STM consistency (atomic tip+nonce+stake reads) | ADDRESSED |

## Entry Format

```markdown
## [Subsystem] — [Brief description of divergence]

**Spec reference:** [Document, section, page/equation number]
**Era:** [Which era this applies to]
**Spec says:** [What the spec defines]
**Haskell does:** [What the Haskell node actually implements]
**Delta:** [The specific difference]
**Implications:** [How this affects our implementation]
**Discovered during:** [Which phase/task uncovered this]
```
