# Mempool — Critical Gap Analysis

**10 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. 2ea7c965

**Era:** multi-era

**Spec says:** The SnapshotInterval defaults to 2*k slots when not explicitly configured.

**Haskell does:** The default snapshot interval is 2*k seconds (not slots), as shown by `secondsToDiffTime (fromIntegral $ unNonZero k * 2)`. The comment in the code says 'k * 2 seconds'.

**Delta:** The spec says the default is '2*k slots' but the implementation uses '2*k seconds'. Slots and seconds are not the same unit — slot duration varies by era (e.g., 1 second in Shelley, 20 seconds in Byron). The implementation explicitly converts to seconds via secondsToDiffTime.

**Implications:** Python implementation must use 2*k seconds (matching the Haskell code), not 2*k slots. If implemented as slots, the snapshot interval would be wrong for any era where slot duration != 1 second. The time-based comparison uses wall-clock DiffTime, not slot counts.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. 323fd92b

**Era:** multi-era

**Spec says:** Chain selection rule: When a server becomes aware of an alternative blockchain B0 B'1...B's where s > l (the alternative chain is strictly longer), it replaces its local chain with the new chain provided the new chain is valid. Validity requires: (a) proper slot leader signatures, (b) hash chain integrity, and (c) ledger-consistent transactions. The rule is simple longest-chain-wins with full vali

**Haskell does:** The Ouroboros Consensus implementation uses a ChainDiff-based approach with rollback and suffix. Validation is delegated to LedgerDB.validateFork which validates the suffix against the ledger state. On validation failure, the chain is truncated to the last valid block (ValidPrefix), rather than fully rejecting the candidate. Invalid blocks are recorded and the offending peer may be punished. The c

**Delta:** 1) The spec says the entire alternative chain is rejected if any block is invalid; the Haskell code truncates to the last valid prefix (ValidPrefix) and may still adopt that prefix if it's longer. 2) The spec uses a simple 'longer chain wins' rule (s > l); the actual Ouroboros consensus uses a more sophisticated chain selection (e.g., preferCandidate based on block number, chain density in Praos, etc.) not visible in this snippet. 3) The spec describes validation of individual block fields (sign

**Implications:** For the Python implementation: (1) Decide whether to implement truncation-to-valid-prefix semantics or strict reject-entire-chain semantics — the spec suggests rejection but the production code does truncation. (2) Chain comparison should be carefully implemented; simple length comparison may suffice for the basic protocol but won't match production behavior. (3) Block validation must cover all three spec requirements (signatures, hash linkage, ledger consistency) even though the Haskell code bu

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 3. 341797f0

**Era:** multi-era

**Spec says:** Each block in Ouroboros-BFT is a 5-tuple (h, d, slj, σ_sl, σ_block) where h is the hash of the previous block, d is a sequence of transactions, slj is the time slot identifier, σ_sl is a signature for the time slot, and σ_block is a signature over the entire block.

**Haskell does:** No implementing Haskell code was found for this block structure definition.

**Delta:** No implementation exists to compare against. The spec requires a precise 5-field block structure with two distinct signatures (slot signature and block signature) plus a previous-block hash, transaction payload, and slot identifier.

**Implications:** The Python implementation must ensure the Block dataclass/namedtuple contains exactly these 5 fields with correct types. Missing either signature field (σ_sl or σ_block) or conflating them would violate the spec. The previous block hash field must reference the hash of the predecessor block (genesis for the first block). The slot identifier must be a valid slot number.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 4. 4bd26e32

**Era:** multi-era

**Spec says:** The chain selection rule for Permissive BFT prefers longer chains only if the intersection (fork point) between the candidate chain and the node's own chain is no more than k blocks away from the node's tip. This constrains rollback to at most k blocks.

**Haskell does:** The forkTooLong predicate checks whether BOTH fork lengths (from intersection to tip1 AND from intersection to tip2) exceed k. A consensus failure is only declared when both sides of the fork exceed k, not when just one side does. This means a node can still prefer a longer chain even if the fork point is more than k blocks from the node's tip, as long as the OTHER chain's fork length is within k.

**Delta:** The spec description says the intersection must be 'no more than k blocks away from the node's tip' (single-chain constraint), but the implementation uses a bilateral check: consensus failure requires BOTH chains to have fork lengths exceeding k. A single chain exceeding k from the fork point is tolerated. This is a meaningful difference: the implementation is more permissive than the spec text suggests.

**Implications:** Python implementation must replicate the bilateral fork-length check (both sides > k), not a unilateral check (one side > k). If we implement the spec text literally (reject candidate chains whose fork point is > k from our tip), we will be too restrictive and reject chains that the Haskell implementation would accept.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 5. 57aef4f4

**Era:** multi-era

**Spec says:** A proposal is 'stably confirmed' when the threshold-satisfying vote's containing block is at least 2k slots deep. The stability check uses 2k slots.

**Haskell does:** The stability check uses `kSlotSecurityParam k` which equals k (not 2k). The code checks `addSlotCount (kSlotSecurityParam k) x <= currentSlot`, meaning it only requires k slots of depth, not 2k as the spec states.

**Delta:** The spec says '2k slots deep' for stability, but the Haskell implementation uses `kSlotSecurityParam k` which is just k. This is a factor-of-2 discrepancy. Note: There may be a convention where `k` in the environment already represents 2k, or `kSlotSecurityParam` may double the value internally, but on face value the code uses k not 2k.

**Implications:** The Python implementation must carefully determine whether kSlotSecurityParam already accounts for the 2k factor. If it does not, there is a genuine divergence. Our Python implementation should match the Haskell behavior (using kSlotSecurityParam) for conformance, but we should document this discrepancy with the spec.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 6. 6bb02fd7

**Era:** multi-era

**Spec says:** The mempool maintains transactions as a list ordered by arrival time. The longest possible prefix of valid transactions that fits in a block is taken from this list.

**Haskell does:** Uses a `Seq (WithIndex tx)` (finger tree sequence) with a `Set txid` for fast membership lookup and an auto-incrementing `nextIdx` for arrival ordering. The `foldTxs` function iterates through transactions in order, skipping invalid ones and ones that would exceed capacity, but does NOT stop at the first invalid/non-fitting transaction — it continues scanning subsequent transactions.

**Delta:** The spec says 'the longest possible prefix' is taken, implying the process stops at the first transaction that doesn't fit or is invalid. However, `foldTxs` in the Haskell implementation skips invalid transactions and transactions that exceed capacity, continuing to process remaining transactions. This means it does NOT strictly take a prefix — it can include transactions from later in the sequence while skipping earlier ones.

**Implications:** A Python implementation must replicate the skip-invalid-continue behavior rather than the strict prefix semantics described in the spec. If our Python code stops at the first invalid or non-fitting transaction, it will produce different block contents than the Haskell node. This is a significant behavioral difference between spec and implementation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 7. 6d4361ff

**Era:** multi-era

**Spec says:** The mempool is a buffer that holds transactions until the node is able to mint a block containing those transactions. Transactions enter via local or node-to-node submission protocols.

**Haskell does:** The Mempool type provides an addTx function that validates transactions against the current ledger state (obtained by applying all already-in-mempool transactions), blocks until there is capacity, returns MempoolTxAdded or MempoolTxRejected, and includes a background revalidation mechanism that can drop transactions that become invalid due to ledger state changes. It also distinguishes AddTxOnBeha

**Delta:** The Haskell implementation adds significant behavioral details beyond the spec's simple 'buffer' description: (1) blocking semantics when mempool is full, (2) ordered validation against cumulative ledger state, (3) background revalidation that can evict previously-valid transactions, (4) distinction between local and remote submission origins (AddTxOnBehalfOf), (5) already-on-chain transactions are treated as invalid. The spec does not describe any of these behaviors.

**Implications:** A Python implementation must account for: blocking/capacity behavior, validation ordering, the AddTxOnBehalfOf discriminator for fairness between local and remote submissions, background revalidation against evolving ledger state, and the postcondition that the returned transaction (whether accepted or rejected) is the same as the one submitted.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 8. 917d84e2

**Era:** multi-era

**Spec says:** Once a transaction is added to the mempool, it is maintained there for exactly u rounds, where u is a configurable protocol parameter. After u rounds the transaction is removed from the mempool if it has not been included in a block.

**Haskell does:** The provided function `implRemoveTxsEvenIfValid` removes transactions from the mempool based on an explicit list of transaction IDs (`toRemove`), not based on a TTL/age counter or round tracking. There is no visible mechanism in this code that tracks how many rounds a transaction has been in the mempool or automatically evicts transactions after u rounds. The removal is imperative and list-driven 

**Delta:** The spec describes an automatic time-to-live (TTL) expiry mechanism parameterized by u rounds, but the implementing code shows a manual removal function that filters transactions by explicit ID lists. The TTL-based eviction logic is either implemented elsewhere (e.g., during slot ticking or block adoption) or is not directly represented in this code path. The function name 'RemoveTxsEvenIfValid' suggests this is a forced-removal path rather than the TTL expiry path.

**Implications:** For the Python implementation: (1) We need to identify where TTL-based expiry actually occurs — it is likely in a separate code path triggered on each new slot/round rather than in this removal function. (2) This function represents a different concern (forced removal, e.g., when transactions conflict with a newly adopted block). (3) We must implement both mechanisms: forced removal by ID and automatic TTL-based expiry after u rounds. (4) The parameter u must be configurable and the round counte

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 9. 99b70e8b

**Era:** multi-era

**Spec says:** The Byron update proposal lifecycle uses slot-based stability: a proposal becomes 'stably confirmed' 2k slots after confirmation, and a 'stable candidate' 2k slots after becoming a candidate. The stability window is measured in slots.

**Haskell does:** The Haskell implementation (ByronTransition) tracks candidate proposals by BlockNo (block number) rather than SlotNo (slot number). The code comment explicitly explains this divergence: using SlotNo would mean that switching to a denser fork could cause something previously deemed stable to suddenly appear unstable. Therefore stability is determined by BlockNo instead. The Byron ledger itself does

**Delta:** Stability window for candidate proposals is measured in block numbers (BlockNo) in the implementation, not in slot numbers as the spec's '2k slots later' language suggests. This is a deliberate design choice to handle fork-density variations correctly. Additionally, the ByronTransitionInfo only tracks candidate proposals (the later stage), not the 'confirmed → stably confirmed' transition, suggesting that earlier stability tracking may be handled differently (possibly within the Byron ledger its

**Implications:** A Python implementation must: (1) track candidate proposal stability using block numbers, not slot numbers, to match the Haskell behavior and avoid instability on fork switches; (2) maintain a Map from ProtocolVersion to BlockNo for candidate proposals; (3) ensure the domain of this map is kept in sync with the set of current candidate proposals (as stated in the invariant); (4) understand that the spec's '2k slots' language is an approximation — the real security parameter k is applied to block

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 10. eaffb8af

**Era:** multi-era

**Spec says:** A transaction tx is added to the mempool if and only if it is consistent with (i) existing mempool transactions and (ii) the local blockchain contents. Both conditions must hold. No distinction is made based on transaction origin.

**Haskell does:** The implementation adds fairness/priority mechanisms not mentioned in the spec: (1) a dual-MVar FIFO queuing system where remote peers must acquire two locks (remoteFifo then allFifo) while local clients only acquire one (allFifo), giving local clients priority; (2) a WhetherToIntervene flag (Intervene for local, DoNotIntervene for remote) that is passed downstream to doAddTx, potentially affectin

**Delta:** The spec describes a simple consistency check (mempool + blockchain), but the implementation introduces: (a) origin-based priority queuing (local vs remote), (b) a WhetherToIntervene mechanism that may alter transaction processing semantics, and (c) a testing-specific code path where transactions can silently not be added (returning Nothing). The core validation logic is delegated to doAddTx which is not shown, so the actual consistency checks are not visible in this code.

**Implications:** Python implementation must: (1) decide whether to implement the local/remote priority distinction — it is not required by the spec but is part of the production behavior; (2) ensure the core validation in the equivalent of doAddTx checks both mempool consistency and blockchain consistency; (3) be aware that WhetherToIntervene may affect transaction ordering or capacity management in ways not visible here; (4) the testing path (returning None/Nothing for unprocessed txs) may need to be replicated

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

