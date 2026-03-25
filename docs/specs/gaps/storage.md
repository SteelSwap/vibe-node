# Storage — Critical Gap Analysis

**28 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. 060aa08f

**Era:** multi-era

**Spec says:** The intersection between the upstream chain and our chain must lie on our fragment, which is anchored k blocks back from our tip. The fragment length dictates the maximum rollback, so the suffix from intersection to our tip must be at most k blocks (or the fragment length if shorter than k).

**Haskell does:** forksAtMostKWeight uses a weight-based comparison rather than a block-count comparison. It computes totalWeightOfFragment on the suffix from the intersection to our tip and checks that this is <= maxWeight. The intersection is found via AF.intersect. If no intersection exists, it returns False.

**Delta:** The spec describes the invariant in terms of block count (at most k blocks of rollback), but the Haskell implementation generalizes this to a weight-based metric (totalWeightOfFragment <= maxWeight). This means the rollback limit is not strictly 'k blocks' but rather 'maxWeight units of weight', which could diverge from a naive block-counting implementation. Additionally, the spec mentions edge cases (volatile DB corruption, near genesis) where the fragment may be shorter than k, but the code do

**Implications:** A Python implementation must decide whether to use block-count-based rollback limits (as the spec literally says) or weight-based limits (as the Haskell code does). If using weight-based, the weight function and maxWeight parameter must be correctly configured. A block-count-only implementation would be spec-compliant but diverge from the Haskell behavior when block weights are non-uniform.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. 099ed598

**Era:** shelley

**Spec says:** The fee formula is fee = a + b * x, where 'a' is the fixed per-transaction overhead constant and 'b * x' is the linear component (b = per-byte cost, x = transaction size in bytes). The fixed component 'a' covers per-transaction overheads; the linear component 'b * x' reflects processing/storage cost scaling with transaction size.

**Haskell does:** The Haskell implementation computes: minfee = pp.a * tx.body.txsize + pp.b + txscriptfee(pp.prices, totExUnits tx) + scriptsCost pp (refScriptsSize utxo tx). Here 'a' is the per-byte multiplier (linear coefficient) and 'b' is the fixed constant, which is the OPPOSITE naming convention from the spec description. Additionally, two extra terms are added: txscriptfee for script execution units and scr

**Delta:** 1) Parameter naming inversion: In the spec, 'a' is the fixed constant and 'b' is the per-byte rate. In the Haskell code, 'a' is the per-byte rate (multiplied by txsize) and 'b' is the fixed constant. This is a naming/convention swap. 2) The Haskell implementation includes two additional fee components not mentioned in the basic spec formula: a script execution fee (txscriptfee based on ExUnits and prices) and a reference scripts cost (scriptsCost based on reference script sizes in the UTxO).

**Implications:** For the Python implementation: (1) The protocol parameter mapping must use the Haskell convention where 'a' (often called 'minFeeA' or 'txFeePerByte') is the per-byte coefficient and 'b' (often called 'minFeeB' or 'txFeeFixed') is the fixed fee, NOT the spec document's naming. Getting this backwards would produce wildly incorrect fee calculations. (2) The Python minfee function must also include the txscriptfee and scriptsCost components to match the actual ledger behavior in Alonzo+ eras. Omitt

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 3. 0bc3be72

**Era:** multi-era

**Spec says:** The type is called `ChainHash b` and is parameterized by a block type `b`, with constructor `BlockHash !(HeaderHash b)` where `HeaderHash` is a type family indexed by the block type.

**Haskell does:** The implementing code uses a concrete (non-parameterized) type called `PrevHash` with constructor `BlockHash !HashHeader`, where `HashHeader` is a concrete type rather than a type family application.

**Delta:** The spec describes a polymorphic type `ChainHash b` parameterized over a block type, while the implementation uses a monomorphic type `PrevHash` specialized to a single concrete hash type `HashHeader`. The naming also differs: `ChainHash` vs `PrevHash`.

**Implications:** For the Python implementation, we should use the concrete approach (`PrevHash` with a fixed hash type) since this is what the actual implementation does. The polymorphic `ChainHash b` from the spec is a generalization from the Consensus layer; the concrete `PrevHash` is sufficient for our purposes. We should name it `PrevHash` to match the implementation rather than `ChainHash`.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 4. 221e1d79

**Era:** multi-era

**Spec says:** Headers with slot numbers past the wallclock time should be considered invalid if the distance from the immutable tip exceeds s slots, even if the header's slot would otherwise fall within the permissible clock skew allowance. This is a two-condition check: (1) header is in the future past wallclock, AND (2) distance from immutable tip exceeds s slots.

**Haskell does:** The realHeaderInFutureCheck function only checks whether the header's onset time is more than clockSkew seconds before the arrival time (i.e., the header is too far in the future relative to the clock skew). It does NOT check the distance from the immutable tip. The check is purely time-based: if negate(ageUponArrival) > clockSkew, it throws FarFutureHeaderException. There is no parameter 's' (sta

**Delta:** The spec describes a compound condition involving both clock skew AND distance from the immutable tip (exceeding s slots), but the Haskell implementation only checks clock skew. The immutable-tip-distance check for the Genesis-related constraint described in the spec is either implemented elsewhere (likely in the chain sync client's intersection/rollback logic or Genesis-specific code, e.g., section 21.5.3) or is not yet implemented in this code path. This function handles the simpler 'header in

**Implications:** For the Python implementation: (1) The basic future header check (clock skew only) should match this Haskell code. (2) The additional Genesis-related constraint about immutable tip distance needs to be identified in other parts of the codebase or treated as a separate rule. Our Python implementation should implement both checks but should be aware they may live in different modules. The basic check rejects headers whose slot onset is more than clockSkew seconds before the current time.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 5. 309a05d6

**Era:** multi-era

**Spec says:** To append a block: (1) Lock state, (2) Append serialised block to chunk file, (3) Append info to primary and secondary indices, (4) Unlock state with updated info. Writes are not flushed to disk.

**Haskell does:** The implementation does all of the above but also: (a) validates that the block is newer than the current tip (throws AppendBlockNotNewerThanTipError if not), (b) handles chunk boundaries by finalising the current chunk and starting new chunks (possibly skipping chunks), (c) computes backfill offsets for gaps between slots, (d) writes a CRC checksum alongside the block data. The ordering is also s

**Delta:** The spec omits several important implementation details: (1) the monotonicity check that rejects blocks not newer than current tip, (2) chunk boundary handling and chunk skipping logic, (3) backfill slot computation for sparse slots, (4) CRC checksum computation and storage. The write order is chunk file -> secondary index -> primary index, which matters for crash recovery.

**Implications:** Python implementation must: (1) enforce monotonicity of appended blocks (reject blocks <= current tip), (2) handle chunk transitions including skipping multiple chunks, (3) compute and write backfill entries for gaps in relative slots, (4) compute CRC checksums for block data, (5) write in the correct order (chunk, secondary, primary) for crash consistency.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 6. 31d9ffc4

**Era:** multi-era

**Spec says:** When truncating the chain, the resulting chain must always end with a block (filled slot), never an empty slot. If necessary, truncation extends back to the previous chunk.

**Haskell does:** No implementing Haskell production code was provided for analysis. The Haskell test (rollbackToLastFilledSlotBefore) validates that: (1) if no blocks exist before the chunk boundary, the result is Origin, and (2) otherwise the result is the tip of the last block before the chunk boundary. The test uses blocksBeforeInAfterChunk to partition the DB model.

**Delta:** Cannot confirm implementation correctness since no production code was provided. The Haskell test covers the two main cases (Origin vs NotOrigin) but the test appears to be a model-based property test that relies on a blocksBeforeInAfterChunk helper to partition blocks. Our Python implementation must ensure equivalent logic exists.

**Implications:** The Python implementation must: (1) implement a function equivalent to rollbackToLastFilledSlotBefore that scans backwards from a chunk boundary to find the last filled slot, (2) return Origin when no filled slots exist before the given point, (3) correctly cross chunk boundaries when the current chunk has no filled slots, and (4) the tip returned must reference an actual block (not just a slot number).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 7. 3804d1b5

**Era:** multi-era

**Spec says:** Any upstream node whose chain forks from our chain more than k blocks ago should cause disconnection. This includes nodes on the same chain but more than k blocks behind our tip.

**Haskell does:** The Haskell implementation defines four distinct result variants for chain sync client termination: ForkTooDeep (initial intersection too deep), NoMoreIntersection (chain changed and no new intersection found), RolledBackPastIntersection (server asked rollback past candidate anchor), and AskedToTerminate (explicit control message). The spec's single rule about 'fork more than k blocks ago' is enfo

**Delta:** The spec describes a single disconnection rule, but the Haskell code implements it as three distinct result types that each handle a different scenario where the k-block fork invariant is violated (at initial intersection, after our chain changes, or after a server-requested rollback). A Python implementation must handle all three cases to be spec-compliant, not just the obvious 'initial fork too deep' case.

**Implications:** Our Python implementation must define all four ChainSyncClientResult variants and ensure that the k-block fork depth check is applied in all three relevant scenarios: (1) during initial intersection finding, (2) when re-intersecting after our chain changes, and (3) when processing rollback requests from the server. Missing any of these three code paths would leave a gap where a too-deep fork could go undetected.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 8. 3d2c1d14

**Era:** multi-era

**Spec says:** A node becomes alert (caught up) when BOTH conditions hold: (1) We see every peer up to its tip, AND (2) None of the peers' chains is binary-preferable to our current chain. When alert, valency lower-bound is removed and the Network Layer may reduce valency.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Missing implementation — the alert/caught-up predicate and its downstream effects (valency relaxation, prefix selection without valency constraint) have no corresponding code to verify against.

**Implications:** The Python implementation must encode the alert predicate as a conjunction of two conditions. Without a reference implementation, we must rely solely on the spec to define correct behavior. Risk of misinterpreting 'see every peer to its tip' (does it mean we have fetched all headers, or that our local view of each peer's chain extends to the peer's announced tip?) and 'binary-preferable' (which specific comparison function?).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 9. 57b98106

**Era:** multi-era

**Spec says:** DecodeDiskDep is a type class with method decodeDiskDep :: CodecConfig blk -> f blk a -> forall s. Decoder s (ByteString -> a). The context value (f blk a) determines how raw bytes are interpreted, and the decoder produces a function from ByteString to the final decoded value 'a'.

**Haskell does:** No implementing Haskell code was found for analysis.

**Delta:** Cannot verify whether the Python implementation (if any) correctly mirrors the two-phase decoding pattern: first running a CBOR decoder to obtain a function, then applying that function to a raw ByteString slice. Without the Haskell implementation, we cannot confirm the concrete instances (e.g., for Header, AnnTip, etc.) or their encoding formats.

**Implications:** The Python implementation must faithfully reproduce the two-stage decode pattern: (1) decode metadata/context from CBOR to obtain a closure/function, (2) apply that function to the raw byte slice to produce the final value. If this is flattened into a single-step decode, it will diverge from the spec's design and may break compatibility with on-disk formats written by Haskell nodes. Particular attention is needed for the forall s quantification (rank-2 type) which in Python translates to ensurin

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 10. 5989eb49

**Era:** multi-era

**Spec says:** A block is considered stable if it is more than k blocks away from the tip of the chain. Stable blocks are immutable and not subject to rollback.

**Haskell does:** No implementing Haskell code was found for the stability rule itself. The Haskell test (calculateStability) computes a stability window by finding the first active slot in a chain schema, adding 1 for the block itself, plus s (the stability/security parameter), all within a window of size winA. This uses the Ouroboros consensus chain growth window abstraction.

**Delta:** No implementation code to compare against spec. The Haskell test reveals that stability calculation involves: (1) finding the first active (block-producing) slot in a chain schema window, (2) adding 1 for the block itself, (3) adding the security parameter s (SCG parameter), and (4) evaluating this within a consensus window. This is more nuanced than the simple 'more than k blocks from tip' description in the spec.

**Implications:** The Python implementation must correctly model the stability window calculation. The simple 'k blocks from tip' rule from the spec is a simplification; the actual calculation involves chain growth windows and active slot finding. Python tests should verify both the simple conceptual rule and the more detailed window-based calculation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 11. 5f80d4e2

**Era:** multi-era

**Spec says:** After any truncation during recovery, the resulting chain must end with a block occupying a filled slot. It must not end at an empty slot. If the last filled slot in the current chunk has been removed, truncation continues backward into the previous chunk until a filled slot is found.

**Haskell does:** No implementing Haskell code was provided for the core truncation logic. However, the test code shows that corruption handling (DeleteFile, DropLastBytes, Corrupt) delegates to rollbackToLastFilledSlotBefore and findRollBackPointForOffsetInChunk, which implement the spec invariant by finding the last valid block position.

**Delta:** No implementation code available to compare against the spec. The test code reveals three corruption modes (DeleteFile, DropLastBytes, Corrupt) and two rollback strategies (rollbackToLastFilledSlotBefore for full file deletion, findRollBackPointForOffsetInChunk for partial corruption). The exact algorithm for cross-chunk rollback is not visible.

**Implications:** Python implementation must: (1) handle all three corruption types, (2) ensure rollback always lands on a filled slot, (3) correctly handle cross-chunk rollback when all blocks in current chunk are invalidated, (4) correctly compute valid bytes remaining after partial corruption using the same arithmetic (totalBytes - n for DropLastBytes, n mod totalBytes for Corrupt).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 12. 64013e90

**Era:** multi-era

**Spec says:** garbageCollect removes all blocks with a slot number strictly less than the given SlotNo (not less than or equal to). This ensures EBBs (which share a slot number with their successor) don't cause the successor to be garbage collected before it is copied to the Immutable DB. The block just copied to the Immutable DB is not itself GC'd until its successor triggers GC.

**Haskell does:** No implementing Haskell code was provided for analysis.

**Delta:** Cannot verify implementation correctness without code. The critical invariant is the strict less-than comparison in the garbage collection predicate.

**Implications:** The Python implementation must use strict less-than (slot < gcSlot) not less-than-or-equal (slot <= gcSlot) when garbage collecting from the Volatile DB. This is a subtle but critical correctness requirement: using <= would cause data loss when EBBs are present, since an EBB and its successor share the same slot number.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 13. 65246dd6

**Era:** multi-era

**Spec says:** The spec defines a clear mapping of VolatileDB operations to RAW lock access levels: getBlockComponent→read, putBlock→append, garbageCollect→write, with specific concurrency semantics (multiple concurrent reads allowed, append concurrent with reads but serialized with other appends, GC requires exclusive lock).

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify whether the implementation correctly maps operations to RAW lock access levels or enforces the specified concurrency constraints, since no code was provided.

**Implications:** The Python implementation must ensure: (1) getBlockComponent uses read-level access allowing full concurrency, (2) putBlock uses append-level access that is concurrent with reads but serialized among appends, (3) garbageCollect uses write-level (exclusive) access blocking all other operations. Without reference implementation code, we must test these properties directly against the spec.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 14. 66d627ee

**Era:** multi-era

**Spec says:** When adding a new block B, the block should be ignored if it is already recorded as known invalid in the invalid blocks cache. Any block in this set is discarded without further processing.

**Haskell does:** The implementation has a nuance based on diffusion pipelining support: when pipelining is OFF, it checks whether the block itself (headerHash hdr) is in the invalid block set. When pipelining is ON, it only checks whether the block's PARENT (headerPrevHash hdr) is in the invalid block set — meaning the tip of the candidate fragment is forgiven for being invalid, but not if it extends an invalid bl

**Delta:** 1) The spec describes a simple 'block is known invalid → discard it' rule, but the implementation conditionally checks either the block itself or its parent depending on diffusion pipelining mode. When pipelining is ON, a block that is itself known invalid will NOT be rejected — only blocks whose parent is invalid are rejected. 2) GenesisHash parent is never checked (vacuously passes). 3) The action on detection is peer disconnection with an InvalidBlock reason, not silent discarding.

**Implications:** A Python implementation must: (1) account for diffusion pipelining support as a configuration parameter that changes which hash is looked up in the invalid blocks set; (2) handle GenesisHash as a no-op (no parent to check); (3) implement the disconnect/rejection semantics rather than simple silent discard. Implementing only the spec's simple 'discard if invalid' logic would be incorrect when pipelining is enabled, as it would reject blocks that Haskell would accept (the tip itself being invalid 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 15. 6f86559d

**Era:** multi-era

**Spec says:** When recovering from a backward clock change, the system should reach a state equivalent to one where the clock was never wrong. This may require moving blocks from the immutable DB back to the volatile DB, depending on how far back the clock moved and the overlap between immutable and volatile DBs.

**Haskell does:** No implementing code was found for this rule. The Haskell consensus layer likely handles this in the ChainDB initialization/recovery logic, but the specific code was not provided for analysis.

**Delta:** Cannot verify whether the Haskell implementation faithfully moves blocks from immutable DB back to volatile DB on backward clock change recovery, or whether it correctly accounts for the two key factors (clock offset magnitude and DB overlap size).

**Implications:** The Python implementation must handle backward clock changes by: (1) detecting that the system clock has moved backward, (2) determining which blocks in the immutable DB were prematurely immutabilized due to the incorrect clock, (3) moving those blocks back to the volatile DB if the overlap is sufficient, and (4) re-running chain selection. Without reference Haskell code, we must design this from the spec description and test thoroughly against edge cases.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 16. 7a7cf51d

**Era:** multi-era

**Spec says:** selectPrefix takes a NonEmpty list of (AnchoredFragment x, IsPeerTip) pairs and returns an AnchoredFragment x that is a prefix of one of the given fragments. PRECONDITION: all fragments are anchored at the same point. The algorithm finds the common prefix P of all fragments, anchors the lookahead window there, applies Steps 1 & 2 from the Report, and prepends P to the result.

**Haskell does:** The provided code is sharedCandidatePrefix (a helper/wrapper), not selectPrefix itself. sharedCandidatePrefix takes curChain and candidates, splits each candidate after the immutable tip, and when there is no intersection with the immutable tip, it assumes the candidate fragment is empty and anchored at the immutable tip (see Note [CSJ truncates the candidate fragments]). It then calls stripCommon

**Delta:** 1) The implementing code shown is sharedCandidatePrefix, a preprocessing step that normalizes candidate fragments relative to the immutable tip before common-prefix extraction — it is not the full selectPrefix algorithm. 2) The fallback behavior when a candidate doesn't intersect the immutable tip (returning an empty fragment anchored at the immutable tip) is an implementation detail not described in the spec's selectPrefix contract. 3) The spec's precondition that all fragments are anchored at 

**Implications:** Python implementation must: (1) handle the case where a candidate fragment does not intersect the immutable tip by treating it as an empty fragment anchored at that tip; (2) split candidate fragments after the immutable tip before computing the common prefix; (3) use stripCommonPrefix (or equivalent) to factor out the shared prefix from the suffixes; (4) ensure the full selectPrefix pipeline (Steps 0-3) is implemented, not just this preprocessing step.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 17. 8d81c0ba

**Era:** shelley

**Spec says:** Reward accounts are account-style (not UTxO), can only receive funds via the reward payout mechanism (never via normal transactions), and can only be withdrawn from by normal transactions that include a witness for the stake address.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify implementation correctness without code. The rule defines fundamental invariants about reward accounts that must be enforced across transaction validation, reward distribution, and withdrawal processing.

**Implications:** The Python implementation must enforce three key invariants: (1) reward accounts use account-style balance tracking (a single running balance, not individual UTxOs), (2) no transaction output can target a reward account address — only the epoch reward payout mechanism can credit them, (3) withdrawals from reward accounts require a valid witness (signature or script) for the corresponding stake credential.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 18. 8e68d7e6

**Era:** multi-era

**Spec says:** The chain database effectively performs longest-chain selection (rather than density-based prefix selection), so the existing chain selection lemma and implementation can be reused without modification. This avoids needing to implement a full prefix selection mechanism that examines the entire volatile database on every new block.

**Haskell does:** The implementation in chainSelectionForBlock constructs preferable candidates via constructPreferableCandidates (which takes a 'weights' parameter from getPerasWeightSnapshot), then selects the best valid candidate via chainSelection with a chainSelEnv that includes those weights. This suggests the implementation does NOT purely use longest-chain selection — it incorporates Peras weight/boosting i

**Delta:** The spec rule states that longest-chain selection is sufficient and the existing lemma/implementation can be used 'as-is'. However, the Haskell code integrates a Peras weight snapshot (via getPerasWeightSnapshot) into both candidate construction (constructPreferableCandidates) and the chain selection environment (mkChainSelEnv). This means chain selection is not purely length-based but also considers protocol-specific weights, which is a modification beyond the 'existing implementation used as-i

**Implications:** For the Python implementation: (1) We need to decide whether to implement pure longest-chain selection or also incorporate weight-based selection as the Haskell code does. (2) If we follow the Haskell implementation, we need to implement weight snapshot retrieval and integrate it into candidate construction and selection. (3) The spec's claim that no modification is needed appears to be aspirational or outdated — the actual implementation has been extended with weight-based selection. (4) Our Py

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 19. 92489dcf

**Era:** multi-era

**Spec says:** When garbage collection is triggered for slot s, all blocks with a slot number strictly less than s must be removed from the Volatile DB.

**Haskell does:** The implementation delegates to VolatileDB.garbageCollect which operates at the file level, not individual block level. The model test (garbageCollectModel) removes entire files where: (1) the file is NOT the current file, AND (2) the maximum slot number in the file is strictly less than the GC slot. This means blocks with slot < s that reside in the current file or in a file containing any block 

**Delta:** The spec says ALL blocks with slot < s are removed. The Haskell implementation removes blocks at file granularity: only entire files whose maximum slot is < s (and which are not the current file) are removed. Blocks with slot < s that share a file with blocks having slot >= s, or that are in the current file, survive garbage collection. This is a deliberate implementation trade-off (coarser granularity) that is weaker than the spec guarantee.

**Implications:** A Python implementation could either: (1) faithfully implement the spec and remove all individual blocks with slot < s (stricter, simpler), or (2) mirror the Haskell file-based approach. If we implement the spec literally, our GC will be more aggressive than Haskell's. Tests should verify the core invariant (blocks with slot < s are eligible for removal) but also account for which granularity model we choose. The invalid blocks cache filtering (slot >= slotNo) should also be replicated.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 20. 941f5231

**Era:** shelley

**Spec says:** At the end of each epoch, the system identifies all stake addresses contributing to each pool and computes rewards per stake address. Rewards are paid out to reward accounts and accumulate if not withdrawn.

**Haskell does:** mkPoolRewardInfo computes per-pool reward info including: (1) If a pool made no blocks, returns Left with relative stake (StakeShare sigma) for ranking purposes only. (2) If pool made blocks, computes maxPool reward (set to zero if pledge > selfDelegatedOwnersStake), apparent performance, pool reward pot (floor of appPerf * maxP), and operator reward. The rewardOld test function aggregates rewards

**Delta:** Two notable implementation details beyond the spec: (1) Pledge checking: if pledge exceeds self-delegated owner stake, maxPool is set to mempty (zero), effectively punishing pools that don't meet their pledge. (2) Post-Allegra hardfork changes reward aggregation from Map.unions (first-writer-wins for duplicate keys) to Map.unionsWith (<>) (additive aggregation for stake addresses delegating to multiple pools or appearing in multiple reward maps). The spec doesn't mention these mechanics explicit

**Implications:** Python implementation must: (1) Handle the pledge vs self-delegated-owners-stake comparison correctly (zero reward if pledge not met). (2) Use floor (not round/ceiling) when converting rational pool reward to Coin (rationalToCoinViaFloor). (3) Implement the correct reward aggregation strategy based on protocol version (unions vs unionsWith for Allegra hardfork). (4) Return only relative stake (not rewards) for pools that produced no blocks. (5) Handle potential division-by-zero for totalStake us

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 21. a41bd8e3

**Era:** shelley

**Spec says:** The transaction fee is calculated as: fee = a + b * x, where 'a' is a fixed constant (per-transaction overhead), 'b' is a per-byte cost constant, and 'x' is the transaction size in bytes. The formula is strictly: a + b * x.

**Haskell does:** The Haskell implementation computes: minfee = a * txsize + b + txscriptfee(prices, totExUnits) + scriptsCost(pp, refScriptsSize). Note two divergences: (1) the roles of 'a' and 'b' are swapped — 'a' is used as the per-byte multiplier (a * txsize) and 'b' is the fixed constant, whereas the spec says 'a' is the fixed constant and 'b' is the per-byte cost; (2) two additional additive terms are includ

**Delta:** 1) Parameter naming is swapped: in the spec fee = a + b*x (a=fixed, b=per-byte), but in Haskell it is a*txsize + b (a=per-byte, b=fixed). This is a naming/convention difference — the underlying linear formula is the same, just with swapped parameter names. 2) The Haskell implementation adds two extra fee components not mentioned in the basic spec formula: (a) txscriptfee covering Plutus script execution costs based on execution units and prices, and (b) scriptsCost covering reference script size

**Implications:** For the Python implementation: (1) Be very careful about parameter naming — if following the spec literally, 'a' is the fixed fee and 'b' is per-byte, but if following the Haskell code, the convention is reversed. The protocol parameter fields in the Haskell codebase use 'a' as per-byte and 'b' as fixed. Our Python implementation must match the actual on-chain protocol parameter semantics (a=per-byte, b=fixed) rather than the spec's stated convention. (2) The minimum fee calculation must also in

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 22. abbd8f72

**Era:** multi-era

**Spec says:** Algorithm maxvalid-bg iterates over candidates sequentially, comparing each Ci against the current Cmax. For each candidate within k blocks of the fork point: Condition A checks if |Ci| > |Cmax| (longer chain wins), and Condition B checks density in a window of s slots after the last common block. The comparison is always between the current candidate and the running Cmax.

**Haskell does:** The Haskell implementation sorts all candidates by compareChainDiffs (which incorporates both chain length preference and density-based comparison via ChainOrderConfig/weights), then processes them in sorted order via a 'go' loop. It validates candidates (checking block validity), handles truncation of rejected blocks, and re-sorts remaining candidates when a prefix is valid. The comparison uses p

**Delta:** 1) The spec iterates sequentially updating Cmax; Haskell sorts candidates best-first and takes the first fully valid one. This is semantically different when candidates have invalid blocks: Haskell can fall back to the next-best candidate, while the spec assumes all candidates are valid. 2) The spec's Condition B uses a fixed density window parameter 's'; Haskell uses SelectionWeights and compareChainDiffs which encapsulates this logic but may parameterize it differently. 3) The Haskell implemen

**Implications:** Python implementation must: (1) Decide whether to follow spec's sequential Cmax update or Haskell's sort-then-validate approach — for pure chain selection without validation, they should yield the same result. (2) Correctly implement both Condition A (length comparison) and Condition B (density in s-slot window). (3) Ensure the fork-distance check (at most k blocks) is applied correctly. (4) If implementing LoE trimming, follow Haskell's trimToLoE logic which is not in the spec. (5) The density 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 23. b52d5391

**Era:** multi-era

**Spec says:** The closeDB operation closes the Volatile DB and releases all opened resources (including open file handles). After closeDB has been called, invoking any other operation on the database must result in an exception.

**Haskell does:** No implementing code was provided for analysis.

**Delta:** Cannot verify whether the Haskell implementation correctly guards all API operations against use after close, whether closeDB is idempotent, or whether resource release is complete. Without code, we cannot confirm the exception type used or whether edge cases (double close, concurrent close) are handled.

**Implications:** The Python implementation must: (1) track an 'is_closed' state and check it at the entry point of every public API method, raising a specific ClosedDBError; (2) ensure all file handles and resources are released on close; (3) decide on idempotency semantics for double-close. Without reference Haskell code, we rely solely on the spec and should test all API surface methods for post-close behavior.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 24. bb1435ff

**Era:** shelley

**Spec says:** Reward accounts are account-style (not UTxO), paid into only by the reward payout mechanism (never by normal transactions), and withdrawn from only by normal transactions that include a witness for the corresponding stake address.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify implementation conformance since no Haskell code was provided. The Python implementation must be built directly from the spec.

**Implications:** The Python implementation must enforce three invariants: (1) reward accounts use account-style balance tracking (a single running balance, not a set of UTxOs), (2) only the reward payout mechanism can credit reward accounts, (3) withdrawals require a valid witness for the stake address. Any deviation from these invariants is a spec violation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 25. c2de547c

**Era:** multi-era

**Spec says:** During Volatile DB recovery, when a block fails to deserialise or is detected as corrupt (with full validation enabled), the file is truncated to the last valid block before the corrupt one. No attempt is made to recover blocks after the corrupt block in the same file.

**Haskell does:** No implementing code was found. The Haskell test `fileTruncateTo` implements a pure function that, given a codec config, a `validUntil` byte offset, and a list of blocks in a file, returns only those blocks whose cumulative serialised size fits within `validUntil`. It walks the block list accumulating offsets and stops (drops all remaining blocks) as soon as the next block would exceed the `validU

**Delta:** No production implementation was provided to compare against. The Haskell test helper `fileTruncateTo` serves as a reference/oracle for the truncation logic: it is a pure fold that accumulates block sizes and truncates at the first block whose end offset exceeds `validUntil`. This implicitly confirms the spec rule that no blocks after the corrupt point are recovered.

**Implications:** The Python implementation must replicate this truncation semantics exactly: (1) walk blocks in order accumulating byte offsets, (2) stop including blocks as soon as any block's end offset exceeds the valid-until boundary, (3) never attempt to recover subsequent blocks even if they might individually be valid. The `validUntil` offset must be computed as the byte offset of the last successfully validated block's end.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 26. c4d8e69f

**Era:** multi-era

**Spec says:** Corrupted blocks must be detected and deleted from the Volatile DB. Full recoverability is not paramount due to small size and ability to re-download.

**Haskell does:** The Haskell model test simulates three corruption modes: (1) DeleteFile - removes the file entirely from the index, (2) DropLastBytes n - truncates the file by removing the last n bytes (clamped to 0), (3) Corrupt offset - simulates a bitflip by truncating to (offset mod size) bytes. In all cases, the model adjusts the fileIndex to reflect the expected post-recovery state, where corruption is dete

**Delta:** No implementing Python code exists yet. The Haskell test uses a model-based approach where corruption in the real filesystem (bitflip) is modeled as truncation in the model, because the implementation detects corruption via integrity checks and truncates to the last known-good boundary. This implies the Volatile DB must have integrity checking (e.g., checksums) that detects mid-block corruption and truncates accordingly.

**Implications:** The Python implementation must: (1) detect corrupted blocks via integrity checks (checksums/hashing), (2) delete or truncate corrupted data rather than serving bad blocks, (3) handle file deletion gracefully during recovery, (4) handle partial file truncation, and (5) model corruption-as-truncation behavior where a bitflip at offset X causes data from X onward to be discarded.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 27. d9973ace

**Era:** shelley

**Spec says:** The transaction fee is calculated as: fee = a + b * x, where 'a' is a fixed constant (per-transaction overhead), 'b' is a per-byte cost, and 'x' is the transaction size in bytes. The formula is a + b * x.

**Haskell does:** The Haskell implementation computes minfee as: pp.a * tx.body.txsize + pp.b + txscriptfee(pp.prices)(totExUnits tx) + scriptsCost pp (refScriptsSize utxo tx). This means: (1) the roles of 'a' and 'b' are swapped compared to the spec — 'a' is used as the per-byte multiplier and 'b' is used as the fixed constant, and (2) there are two additional additive terms: a script execution fee based on ExUnit

**Delta:** Two divergences: (1) The parameter naming is swapped — in the spec 'a' is the fixed constant and 'b' is the per-byte rate, but in Haskell 'a' is the per-byte rate (multiplied by txsize) and 'b' is the fixed constant. This is effectively a notational swap: spec says a + b*x, code computes a*x + b. (2) The Haskell code adds two extra fee components not mentioned in the basic spec formula: txscriptfee (for Plutus script execution units) and scriptsCost (for reference script sizes). These reflect la

**Implications:** For a Python implementation: (1) Be very careful about which protocol parameter is the fixed fee and which is the per-byte fee — the Haskell code uses 'a' as per-byte and 'b' as fixed, opposite to the spec's naming convention. (2) The basic fee formula from the Shelley spec is necessary but not sufficient for post-Alonzo eras. The Python implementation must also add the script execution fee (based on ExUnit prices) and the reference scripts cost to compute the correct minimum fee. If only the ba

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 28. fd1d2386

**Era:** multi-era

**Spec says:** When the chain sync client looks for an intersection, it sends points from the current volatile chain fragment. The offsets used to select points should be computed based on the security parameter k and the actual length of the volatile fragment (maxOffset). If the volatile fragment is shorter than k, fewer points are sent. If the volatile DB is entirely erased, only the immutable tip (the anchor 

**Haskell does:** The implementation computes maxOffset = AF.length ourFrag (the length of the volatile/current chain fragment), then calls mkOffsets k maxOffset to generate offset indices, and selects points from ourFrag at those offsets via AF.selectPoints. When ourFrag is empty (volatile DB erased), maxOffset=0, offsets will be minimal/empty, and the only point available would be the anchor point of ourFrag (the

**Delta:** The spec states that in the extreme case (empty volatile DB), 'only a single point is available (the tip of the immutable database I)'. The code relies on AF.selectPoints on an empty fragment returning an empty list, and then SendMsgFindIntersect with an empty points list. The immutable tip (anchor) is NOT explicitly added to the points list. This means with a completely empty volatile fragment, the node sends zero intersection points rather than the single immutable tip point. The upstream peer

**Implications:** In Python implementation, we need to decide: (1) Follow the Haskell code literally — send only points from AF.selectPoints on the volatile fragment (empty list when volatile DB is erased), OR (2) Follow the spec — explicitly include the immutable tip/anchor as a fallback intersection point when the volatile fragment is empty. The Haskell behavior may be intentional (the anchor is genesis when immutable chain is empty) or may be a subtle divergence. Our Python implementation should document this 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

