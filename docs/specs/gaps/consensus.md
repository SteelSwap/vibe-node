# Consensus — Critical Gap Analysis

**73 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. 01772673

**Era:** shelley

**Spec says:** Active stake is stake correctly delegated to an existing (non-retired) pool. The slot leader schedule only considers active stake, excluding unregistered or undelegated stake.

**Haskell does:** The activeDelegs filter requires BOTH that the credential is present in the rewards map (Map.member k rewards') AND that the delegation target pool is present in psStakePools (Map.member v psStakePools). The rewards map presence acts as a proxy for 'registered stake credential'. This is a conjunction of two conditions.

**Delta:** The spec describes the concept at a high level ('correctly delegated to an existing pool'), while the Haskell implementation makes the registration check explicit via rewards map membership. A Python implementation must replicate both conditions: (1) credential must be registered (present in rewards/accounts), AND (2) delegation target must be an active (non-retired) pool in the stake pool registry. Missing either condition would be a divergence.

**Implications:** The Python implementation must ensure that the active stake filtering applies both the registration check and the pool-existence check as a conjunction. If only the pool-existence check is applied (a natural reading of 'delegated to an existing pool'), unregistered credentials could leak into the active stake, leading to incorrect leader schedules and reward calculations.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. 04d2e1b2

**Era:** multi-era

**Spec says:** The type family 'LedgerState :: B→L' defines a mapping from a block type (kind B) to its associated ledger state type (kind L). This is the primary structural link from the Block domain to the Ledger domain.

**Haskell does:** No implementing Haskell code was found for this type family mapping. It is likely defined as an associated type family in a type class (e.g., class HasLedgerState b where type LedgerState b :: Type) but the specific code was not provided for analysis.

**Delta:** Cannot verify whether the Haskell implementation faithfully implements the spec's B→L type family, nor confirm which concrete block/ledger type pairs are instantiated. The Python implementation must define this mapping explicitly (e.g., via a dictionary or class registry) since Python lacks type families.

**Implications:** The Python implementation needs an explicit registry or mapping mechanism to associate block types with ledger state types. Without seeing the Haskell instances, we must infer the correct pairings from era-specific knowledge. Risk of missing or incorrect pairings if the Haskell code defines additional or different instances than expected.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 3. 0ee85534

**Era:** multi-era

**Spec says:** BlockSupportsProtocol has two methods: validateView (for header validation) and selectView (for chain selection, using Ord on SelectView). The superclass constraints are GetPrevHash b and ConsensusProtocol p. The first argument 'bc' to both methods is a generic block config type.

**Haskell does:** The actual implementation differs in several ways: (1) The superclass constraints are much richer: GetHeader blk, GetPrevHash blk, ConsensusProtocol (BlockProtocol blk), plus NoThunks constraints on Header, BlockConfig, CodecConfig, and StorageConfig. (2) There is no 'selectView' method at all. Instead, chain selection is decomposed into two separate mechanisms: 'tiebreakerView' (projecting a Tieb

**Delta:** The spec's 'selectView' method does not exist in the implementation. Chain selection in the implementation is handled by a separate 'ChainOrder' class and the 'SelectView' is derived elsewhere (likely from ConsensusProtocol), while BlockSupportsProtocol only contributes a 'tiebreakerView' and 'projectChainOrderConfig'. Additionally, the implementation has many more superclass constraints (GetHeader, multiple NoThunks), and uses an associated type 'BlockProtocol blk' instead of a separate type pa

**Implications:** For the Python implementation: (1) Do NOT implement a 'selectView' method on BlockSupportsProtocol — it doesn't exist in the real code. (2) Instead implement 'tiebreakerView' (with a default returning NoTiebreaker) and 'projectChainOrderConfig' (with a default returning unit/None). (3) The superclass requirements are more extensive than the spec suggests — include GetHeader, GetPrevHash, and ensure the block protocol satisfies ConsensusProtocol. (4) Chain selection ordering (SelectView compariso

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 4. 153a83a3

**Era:** multi-era

**Spec says:** When a fragment is empty, the consensus protocol's chain selection cannot be used because there is no header available to extract a view from. It is possible that a non-empty fragment should not be preferred over an empty one, or that an empty fragment should be preferred over a non-empty one.

**Haskell does:** When both fragments are empty, returns ShouldNotSwitch EQ. When ours is non-empty and candidate is empty, returns ShouldNotSwitch GT (never switch to empty candidate). When ours is empty and candidate is non-empty, it does NOT use the consensus protocol's chain selection (no selectView call); instead it compares the candidate's tip blockPoint against our anchor point - if they differ, it returns S

**Delta:** The spec describes a general principle about empty fragments and chain selection limitations. The implementation makes specific choices: (1) An empty candidate is NEVER preferred (ShouldNotSwitch GT), contradicting the spec's statement that 'an empty fragment should be preferred over a non-empty one' is possible in principle. (2) When ours is empty and candidate is non-empty, the decision is based on blockPoint equality with our anchor rather than any chain quality metric. (3) The entire empty-f

**Implications:** Python implementation must replicate the exact branching logic: (1) Empty vs Empty -> no switch, (2) Non-empty vs Empty -> no switch, (3) Empty vs Non-empty -> switch only if candidate tip differs from our anchor point (using Longer comparison with anchor's block number vs tip's block number), (4) Non-empty vs Non-empty -> delegate to consensus preferCandidate. Must also implement the Peras weight bifurcation where non-empty weights use intersection-based weighted comparison instead.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 5. 1598d63f

**Era:** multi-era

**Spec says:** When comparing two non-empty chain fragments for chain selection, the procedure is: (1) take the most recent header (tip) of each fragment, (2) extract the protocol-specific view on that header as defined by BlockSupportsProtocol, and (3) use the consensus protocol's chain selection interface to compare the two views.

**Haskell does:** The Haskell implementation handles multiple cases beyond the spec's 'non-empty fragments' scenario: (1) Both empty fragments → EQ, (2) One empty fragment → checks if the non-empty fragment's tip equals the empty fragment's anchor (EQ if same point, otherwise the non-empty side wins), (3) Both non-empty → uses selectView on tips and compares (matching the spec), (4) When Peras weights are enabled, 

**Delta:** Three divergences: (A) The Haskell code handles empty fragment cases not described by the spec rule (which explicitly says 'non-empty'). (B) When Peras weights are active (isEmptyPerasWeightSnapshot is false), the comparison uses weightedSelectView on intersection suffixes rather than just tip selectView, which is a fundamentally different comparison strategy. (C) There is a precondition assertion that fragments must intersect, which is implicit in the spec.

**Implications:** For a Python implementation: (1) The non-empty/non-empty case (Case 4) is the core spec logic and must use selectView on tips with standard compare. (2) Empty fragment cases must also be implemented for completeness. (3) The Peras weighted selection path is an extension that may or may not need implementation depending on scope. (4) A precondition check that fragments intersect should be enforced.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 6. 1b5fc37f

**Era:** multi-era

**Spec says:** When a follower's ImmutableDB iterator reaches its end, the implementation must: (1) check whether more blocks have been appended to the Immutable DB, (2) if yes, open a new iterator to stream the newly appended blocks, (3) if no, switch the follower over to the in-memory fragment.

**Haskell does:** The provided code shows the `instructionHelper` function which handles follower state transitions. It handles three states: FollowerInit (rollback to genesis), FollowerInImmutableDB (return rollState and iterator), and FollowerInMem (either serve from in-memory fragment if point is within fragment bounds, or switch back to ImmutableDB state by calling streamAfterKnownPoint). The critical logic for

**Delta:** The code snippet is truncated and does not include `rollForwardImmutableDB`, which is the function that implements the core spec logic of checking for newly appended immutable blocks and opening new iterators or switching to in-memory. The visible code primarily handles state dispatch and the FollowerInMem-to-ImmutableDB transition. Without `rollForwardImmutableDB`, we cannot fully verify spec compliance for the iterator-end behavior.

**Implications:** The Python implementation must implement the full state machine: (1) When streaming from ImmutableDB and the iterator is exhausted, check the current ImmutableDB tip to see if new blocks were appended. (2) If new blocks exist, open a fresh iterator from the last-streamed point. (3) If no new blocks, transition to FollowerInMem state. Additionally, the FollowerInMem state must handle the case where the follower's point has fallen off the in-memory fragment (due to GC moving blocks to immutable), 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 7. 1bd10ca1

**Era:** multi-era

**Spec says:** The type family 'ConsensusConfig :: P→*' maps a protocol type 'p' to a single static consensus configuration type 'cc'. This is abstract static configuration data for the consensus protocol.

**Haskell does:** The CardanoConsensusConfig pattern synonym decomposes the consensus config into a product of 8 PartialConsensusConfig values — one per era: Byron, Shelley (TPraos), Allegra (TPraos), Mary (TPraos), Alonzo (TPraos), Babbage (Praos), Conway (Praos), and Dijkstra (Praos). Each era's partial config is parameterized by its specific block protocol. The Cardano consensus config is thus an HardForkConsens

**Delta:** The spec presents ConsensusConfig as a single opaque type-level mapping (P → *), but the Haskell implementation for Cardano concretizes it as a product of 8 era-specific partial consensus configs. The pattern synonym provides convenient access to each era's partial config. Notably, the implementation includes DijkstraEra (8 eras total) and distinguishes between TPraos (Shelley through Alonzo) and Praos (Babbage through Dijkstra) protocol families. A Python implementation must model this composit

**Implications:** A Python implementation must: (1) represent ConsensusConfig for Cardano as a composite of 8 per-era partial configs; (2) correctly distinguish TPraos vs Praos protocol variants for different eras; (3) include DijkstraEra as the 8th era; (4) support construction and pattern-matching equivalent to the pattern synonym; (5) the 'Partial' nature of each config means these are incomplete configs that get completed by combining with additional data (e.g., from the ledger state) at runtime.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 8. 1d2b9027

**Era:** multi-era

**Spec says:** Chain selection chooses between competing chains by preferring longer chains (higher block number at the tip) in the simplest case. The spec describes comparing entire chains conceptually, but in practice compares information at the tips.

**Haskell does:** The Haskell implementation uses a sophisticated chain selection algorithm that: (1) sorts candidates using compareChainDiffs with a configurable bcfg and weights, not just chain length; (2) validates candidates iteratively - if only a prefix is valid, it truncates rejected blocks and re-sorts; (3) uses preferAnchoredCandidate with weights to determine if a candidate should be preferred; (4) suppor

**Delta:** The spec describes chain selection as primarily length-based ('longer chains preferred'), but the implementation uses compareChainDiffs with configurable weights (bcfg, weights parameters), iterative validation with truncation of invalid block suffixes, tentative header management, and re-sorting after truncation. The comparison function is protocol-specific and not purely length-based.

**Implications:** A Python implementation must: (1) implement compareChainDiffs as the core comparison, not just chain length; (2) handle the iterative validation loop where invalid candidates get truncated to valid prefixes and re-sorted; (3) implement preferAnchoredCandidate with weights support; (4) handle the ShouldSwitch/ShouldNotSwitch logic for truncated candidates; (5) consider tentative header state management. Simply comparing chain lengths would be insufficient.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 9. 1fcf9a26

**Era:** byron

**Spec says:** Cardano's evolution is split into three protocol eras: Byron/Ouroboros, Handover (Ouroboros BFT), and Shelley/Praos. The spec describes exactly three eras with distinct consensus protocols.

**Haskell does:** The ProtocolCardano type defines seven eras via HardForkProtocol: ByronBlock, then six Shelley-based eras (Shelley, Allegra, Mary, Alonzo, Babbage, Conway). The Shelley-era blocks use TPraos for Shelley through Alonzo, and Praos for Babbage and Conway. There is no explicit 'Handover/BFT' era in the type-level list; the Byron-to-Shelley transition implicitly covers it.

**Delta:** The spec describes 3 conceptual protocol eras, but the implementation has 7 hard-fork eras. The 'Handover' (Ouroboros BFT) era is not represented as a distinct era in the HardForkProtocol type — it was a transient phase within Byron. Additionally, post-Shelley eras (Allegra, Mary, Alonzo, Babbage, Conway) are not mentioned in the spec at all. The consensus protocol also evolved from TPraos to Praos (starting at Babbage), which the spec does not distinguish.

**Implications:** A Python implementation must model all 7 hard-fork eras, not just the 3 conceptual eras described in the spec. The Handover/BFT phase is folded into the Byron era's block validation logic rather than being a separate era. The distinction between TPraos (Shelley-Alonzo) and Praos (Babbage-Conway) must be handled. Relying solely on the spec's 3-era model would miss the Allegra, Mary, Alonzo, Babbage, and Conway eras entirely.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 10. 26aa30e4

**Era:** shelley

**Spec says:** The stake distribution automatically excludes (1) addresses with no UTxO entries, and (2) addresses that have stake rights but have not correctly registered their stake address or delegation certificate. Only properly delegated stake should appear in the distribution.

**Haskell does:** The totalStakes function maps over TxOut entries. If an address is found in addrDist and maps to a CoreId, the stake is assigned to StakeCore. For ALL other cases (address not in addrDist, address not delegated, or address delegated to a non-CoreId), the stake is lumped into a single StakeEverybodyElse bucket rather than being excluded.

**Delta:** The spec says unregistered/undelegated stake is excluded from the distribution. The Haskell implementation does NOT exclude it — instead it aggregates all non-core-delegated stake (including unregistered and improperly delegated addresses) into a catch-all StakeEverybodyElse bucket. This means stake from unregistered addresses still influences the distribution rather than being dropped entirely.

**Implications:** A Python implementation must decide whether to follow the spec (exclude unregistered/undelegated stake entirely) or the Haskell implementation (bucket it into StakeEverybodyElse). The StakeEverybodyElse bucket is likely used downstream for protocol-level calculations (e.g., distributing rewards or voting weight). If our Python implementation strictly follows the spec and drops this stake, it will produce different total stake sums and potentially different reward/voting calculations compared to 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 11. 2c35b5ba

**Era:** multi-era

**Spec says:** CanBeLeader is a type family indexed by protocol type 'p', where a value indicates the node has required configuration (keys and other data) to produce blocks under that protocol, but does NOT indicate slot-level leadership rights.

**Haskell does:** No implementing Haskell code was provided for analysis. The type family declaration `type family CanBeLeader p :: Type` should have instances for each concrete protocol (Praos, TPraos, etc.) mapping to their respective credential/configuration types.

**Delta:** Cannot verify the actual type family instances and their associated data types without the implementing code. The gap is that we have the abstract specification but no concrete implementation to validate against.

**Implications:** The Python implementation must define a protocol-indexed mapping from protocol type to credential/configuration class. Each protocol variant (Praos, TPraos, etc.) needs its own CanBeLeader dataclass containing the appropriate signing keys and certificates. Care must be taken to ensure CanBeLeader is purely about block-production capability (having the right keys) and is strictly separated from per-slot leadership election (IsLeader).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 12. 3044f972

**Era:** shelley

**Spec says:** Any block purportedly produced in a non-active OBFT slot shall be considered invalid by all nodes. Non-active OBFT slots are those OBFT slots (from the d * n_s randomly selected slots) that were not chosen as active OBFT slots (the fraction f of OBFT slots). Nodes must reject blocks with timestamps corresponding to non-active OBFT slots.

**Haskell does:** No implementing code was found for this validation rule.

**Delta:** The spec explicitly requires that blocks in non-active OBFT slots be rejected, but no Haskell implementation was located. This could mean the validation is embedded in a different module, handled implicitly by the slot leader schedule, or is genuinely missing.

**Implications:** For the Python implementation, we must ensure that the slot classification logic (active vs non-active OBFT slots) is correctly implemented and that block validation rejects any block whose slot is classified as a non-active OBFT slot. Without a reference implementation, we must derive the validation purely from the spec, paying careful attention to: (1) how d * n_s OBFT slots are randomly selected from all slots in an epoch, (2) how the fraction f of those are marked active, and (3) that the re

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 13. 34a09442

**Era:** multi-era

**Spec says:** tickChainDepState takes a ConsensusConfig p, a Ticked (LedgerView p), a SlotNo, and a ChainDepState p, and produces a Ticked (ChainDepState p). It is a straightforward per-protocol operation that advances the chain-dependent state to a target slot.

**Haskell does:** The HardFork combinator implementation wraps this in a multi-era alignment step using State.align. It (1) computes epoch info from the hard fork shape, transition info, and ledger view, (2) uses translateConsensus for cross-era translation when needed, (3) completes each era's partial consensus config with the computed epoch info before delegating to the per-era tickChainDepState, and (4) stores t

**Delta:** The spec describes a simple per-protocol tick function, but the HardFork combinator adds significant machinery: epoch info precomputation, per-era config completion via completeConsensusConfig', era alignment via State.align, and potential cross-era translation via translateConsensus. A Python implementation must replicate all of these HardFork combinator layers, not just the per-era tick logic. Additionally, the same slot is passed to all eras (no per-era slot adjustment), and the epoch info is

**Implications:** A Python implementation must: (1) correctly implement State.align to pair per-era configs, ledger views, and chain dep states (handling the telescope structure), (2) implement epochInfoPrecomputedTransitionInfo for epoch boundary calculations, (3) implement completeConsensusConfig' for each era to turn partial configs into full configs using the epoch info, (4) implement translateConsensus for cross-era chain dep state translation, and (5) ensure the epoch info is stored in the ticked result for

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 14. 3754c069

**Era:** shelley

**Spec says:** praosVrfChecks checks three conjunctive conditions: (1) the block issuer's cold key hash maps to (σ, hk_vrf) in pool distribution where hk_vrf matches the VRF key hash from the header, (2) vrfChecks on the epoch nonce and header body passes, and (3) checkLeaderVal on the leader VRF output, relative stake σ, and active slot coefficient f passes.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify implementation correctness — no code to compare against. The spec requires all three conditions to be checked conjunctively, including the VRF key hash lookup match from the pool distribution.

**Implications:** Python implementation must faithfully implement all three checks. Key risks: (1) forgetting to verify the VRF key hash match (hk_vrf) against the pool distribution entry, (2) incorrectly computing hk from bvkcold vs bvkvrf, (3) short-circuiting in a way that changes observable behavior in error reporting.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 15. 3e33d374

**Era:** multi-era

**Spec says:** The server replaces its local chain with an alternative blockchain B_0 B_1' ... B'_s if and only if s > l (strictly longer than local chain) AND the chain is valid. Validity requires: (1) proper signatures for time slot and entire block by the correct round-robin server, (2) hash linkage to previous block, (3) valid transaction sequences w.r.t. ledger state from previous blocks.

**Haskell does:** The Haskell implementation in validateCandidate performs ledger validation via LedgerDB.validateFork but does not explicitly check the BFT-specific signature or round-robin leader schedule constraints at this level. Those checks are delegated to the block validation rules within the ledger layer. Additionally, the implementation supports partial validation: when a ledger error is encountered, it t

**Delta:** Three key divergences: (1) The spec describes a simple binary accept/reject for chain replacement, while Haskell supports a ValidPrefix result that truncates to the last valid block. (2) The spec requires strict length comparison (s > l), but this check happens elsewhere in chain selection (not in validateCandidate). (3) The spec's BFT-specific signature and round-robin leader checks (i - 1 = (j - 1) mod n) are not visible at this level — they are embedded in the ledger validation rules called b

**Implications:** For the Python implementation: (1) We must ensure BFT signature verification and round-robin leader assignment are checked during block validation, even if at a different layer. (2) We need to decide whether to support ValidPrefix (partial chain adoption) or follow the spec's all-or-nothing approach. (3) Chain length comparison (s > l) must be implemented as part of chain selection, separate from validation. (4) We do not need to handle EBBs or peer punishment in a spec-conformant implementation

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 16. 3e5c530e

**Era:** shelley

**Spec says:** The EPOCH transition system covers epoch boundary operations: (A) taking a stake distribution snapshot at epoch beginning, (C) epoch beginning, (D) taking snapshots of stake pool performance/fee pot/decayed deposits at epoch end, and (G) distributing rewards.

**Haskell does:** The Conway-era epochTransition implementation goes significantly beyond the spec's listed items. It also: (1) runs POOLREAP to retire pools and return deposits, (2) extracts DRep pulsing state for governance ratification, (3) applies enacted governance withdrawals via applyEnactedWithdrawals, (4) applies proposal enactment/expiration via proposalsApplyEnactment removing enacted/expired actions and

**Delta:** The spec description covers only the classic Shelley-era epoch boundary concerns (snapshots, rewards). The Conway implementation adds substantial governance-related processing (DRep pulsing, proposal enactment/expiration, committee/constitution updates, PParams rotation, proposal deposit returns) that is not mentioned in the high-level spec description provided. This means the EPOCH rule in Conway is a superset of what the spec excerpt describes.

**Implications:** A Python implementation must handle all Conway governance epoch boundary logic, not just the four items (A,C,D,G) listed in the spec excerpt. Missing governance proposal enactment, DRep pulsing extraction, committee/constitution updates, or PParams rotation at epoch boundaries would be a critical conformance gap.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 17. 3ebe0c99

**Era:** multi-era

**Spec says:** A strict extension of a chain (the same chain with one or more additional valid blocks appended) is always preferred over that chain in chain selection.

**Haskell does:** The chain selection code asserts (via `shouldSwitch . preferAnchoredCandidate`) that all candidates presented to it are already preferred over the current chain. The preference logic itself is in `preferAnchoredCandidate` and `compareChainDiffs`, not directly in this function. The function also handles the case where a candidate is only partially valid (ValidPrefix), in which case the truncated pr

**Delta:** The spec rule about strict extensions being preferred is treated as an axiomatic precondition (assertion) in the Haskell code rather than being explicitly enforced or computed here. The actual preference comparison logic (preferAnchoredCandidate, compareChainDiffs) must ensure this property holds. If a strict extension were somehow not preferred by the comparison function, the assertion would fire at runtime in debug builds but would be silently ignored in production builds.

**Implications:** In the Python implementation, we must ensure that the chain comparison/preference function always returns 'prefer' when comparing a strict extension against its base chain. This is a fundamental invariant of the chain selection algorithm. We should both (1) implement this correctly in the comparison function and (2) add explicit checks/assertions for this property.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 18. 44185158

**Era:** multi-era

**Spec says:** The oldest ledger state that may need to be reconstructed is at most k blocks behind the current tip. The Ledger Database exploits the k bound to efficiently reconstruct any of the k most recent historical ledger states. Rollbacks beyond k are not permitted.

**Haskell does:** The ExceededRollback data type captures when a rollback is requested that exceeds the maximum allowed (rollbackMaximum vs rollbackRequested, both Word64). The mockMaxRollback test function computes rollback distance by counting blocks from the tip back to a restore point in a mock ledger, returning 0 when the restore point is found or when the list is exhausted.

**Delta:** The implementation is minimal — ExceededRollback is just a data type recording the violation, and mockMaxRollback is a test helper that counts distance to a restore point. The actual enforcement logic (rejecting rollbacks > k) and the efficient reconstruction mechanism are elsewhere in the codebase. The test helper returns 0 if the restore point is not found (list exhausted), which could mask errors where the restore point doesn't exist in the ledger at all.

**Implications:** Python implementation must: (1) track a security parameter k and reject rollback requests exceeding it, (2) maintain enough ledger state history to reconstruct any of the k most recent states, (3) raise an equivalent ExceededRollback error when rollback distance > k. The mockMaxRollback returning 0 on empty list means our equivalent should also handle the edge case where the restore point is not found.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 19. 4592482b

**Era:** shelley

**Spec says:** The RUPD transition covers the reward calculation between step (E) (snapshots stable) and step (F) (reward calculation finished). The applyRUpd function applies the reward update to the epoch state: treasury gets posPart(pos treasury + Δt + pos unregRU'), reserves gets posPart(pos reserves + Δr), fees gets posPart(pos fees + Δf), and rewards map is updated via rewards ∪⁺ regRU, where regRU = rs re

**Haskell does:** The Haskell test (createRUpdOld_) focuses on the *creation* of the RewardUpdate (computing Δt, Δr, rs, Δf) rather than testing applyRUpd itself. It computes deltaR1 from reserves × ρ × min(1, η), rPot from fees + deltaR1, deltaT1 from rPot × τ, _R = rPot - deltaT1, then calls rewardOld to distribute _R among stake pools. The η calculation has a special case: η=1 when d ≥ 0.8, otherwise η = blocksM

**Delta:** The spec rule describes applyRUpd (applying a computed reward update to the epoch state), but the Haskell test covers createRUpd (computing the reward update parameters). These are complementary but distinct operations. The applyRUpd logic of partitioning rewards into registered/unregistered credentials, sending unclaimed rewards to treasury, and using posPart for safety, is not directly tested by the existing Haskell test. The createRUpd logic (ρ, τ, η calculations, reward pot splitting) is wha

**Implications:** Python implementation must cover both: (1) createRUpd - computing Δt, Δr, Δf, rs from protocol parameters, block production, snapshots, and stake distribution; and (2) applyRUpd - applying the computed update to epoch state with the regRU/unregRU partitioning logic. The η special case (d ≥ 0.8 → η=1) is a critical branching point. The posPart safety on treasury, reserves, and fees in applyRUpd must be preserved.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 20. 469fe091

**Era:** multi-era

**Spec says:** Lemma [adversarial-within-s] guarantees the adversary cannot construct a chain forking off more than k blocks from an alert node's chain that is also longer. However, the adversarial chain CAN contain more than k blocks after the fork intersection. Therefore, dropping the Genesis requirement (density rule, N_rs peer connectivity) prematurely — merely upon being within s slots of the wall clock — c

**Haskell does:** The Haskell test prop_longRangeAttack explicitly tests under Praos (not Genesis) that the honest chain is NOT selected when a long-range attack is performed. It generates a block tree with 1 alternative adversarial chain, creates a longRangeAttack schedule, and asserts `not . selectedHonestChain` — confirming that under Praos without Genesis, the node adopts the adversarial chain and cannot roll b

**Delta:** The Haskell test explicitly encodes the vulnerability described in the spec: under Praos (without Genesis), a long-range attack succeeds and the node gets stuck on the adversarial chain. The test is a negative test (asserting the honest chain is NOT selected) and is annotated as needing reversal when Genesis is fully implemented. No implementing defense code was found, which is consistent with the spec describing a caveat/requirement rather than a concrete algorithm.

**Implications:** For the Python implementation: (1) We must ensure that the Genesis density rule and peer connectivity requirements (N_rs) are maintained until the node is fully synced, not dropped prematurely when within s slots of the wall clock. (2) We need both a negative test (Praos-only behavior where long-range attack succeeds) and a positive test (Genesis behavior where long-range attack is defeated). (3) The rollback limit k must be enforced and tested — if a node has adopted an adversarial chain with >

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 21. 4855a2b5

**Era:** shelley

**Spec says:** The duration between step D (epoch end/snapshot taking) and step E (snapshots becoming stable) is 2k blocks. The duration between F (reward calculation finished) and G (rewards distributed) is also 2k blocks. Between E and F, a single honest block is sufficient for a random nonce.

**Haskell does:** The implementation uses a pulsing mechanism where the reward calculation is spread across blocks. The pulse size is ceil(numStakeCreds / (4*k)). The comment states the calculation begins (4k/f) slots into the epoch and must end (2k/f) slots before epoch end. The 2k block constraint from the spec is translated to slot-based timing using the active slot coefficient f, and the calculation window is d

**Delta:** The spec describes timing constraints in terms of blocks (2k blocks between D-E, 2k blocks between F-G, and a single block between E-F), but the implementation converts these to slot-based timing (4k/f and 2k/f slots) and uses a pulsing mechanism with forced completion fallback. The spec's 'single honest block between E and F' constraint becomes an implicit assumption in the pulsing design. The pulse size formula (numStakeCreds / 4k) is an implementation optimization not described in the spec.

**Implications:** Python implementation must: (1) correctly compute pulseSize as max(1, ceil(numStakeCreds / (4*k))), (2) implement the forced completion semantics if pulsing doesn't finish in time, (3) handle the eta calculation with the d >= 0.8 threshold correctly, (4) use floor rounding for deltaR1 (rationalToCoinViaFloor) and deltaT1 (floor). The pulsing mechanism is an implementation detail that may or may not need to be replicated depending on whether conformance testing requires step-by-step matching or o

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 22. 5161c583

**Era:** multi-era

**Spec says:** The Genesis chain selection rule defines two cases: (1) Short-range fork (intersection ≤ k blocks back): prefer the candidate if it is strictly longer. (2) Long-range fork (intersection > k blocks back): prefer the candidate if it is denser in a window of s slots from the intersection. The rule is about selecting/preferring one chain over another.

**Haskell does:** The Haskell code implements a 'consensusCondition' function that checks whether ANY pair of chains has BOTH fork lengths exceeding k (the security parameter). If so, it reports a ConsensusFailure. If no such pair exists, it reports ConsensusSuccess. It does NOT implement chain selection/preference at all — it implements a consensus safety check (detecting when two chains have diverged beyond the s

**Delta:** The spec describes a chain SELECTION rule (which chain to prefer), while the Haskell code implements a consensus SAFETY CHECK (detecting dangerous fork situations). Specifically: (1) The spec's short-range case says 'prefer longer chain' — the code doesn't select chains at all, it only checks if forks are too long. (2) The spec's long-range case requires density comparison in an s-slot window — the code has no density/slot-based logic whatsoever, only block-number-based fork length checks. (3) T

**Implications:** The Python implementation should NOT use this Haskell code as a reference for implementing the Genesis chain selection rule. This code implements a different concern (consensus failure detection). For the actual Genesis chain selection rule, the Python implementation needs: (1) a longest-chain comparison for short-range forks, (2) a density comparison over an s-slot window for long-range forks, and (3) proper parameterization with both k and s. The Haskell consensus failure detection logic could

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 23. 56cdc4c0

**Era:** multi-era

**Spec says:** After full block validation, verify that the block's slot number is not ahead of wallclock time. If the block is far ahead (beyond permissible clock skew), mark the block as invalid (treated as a validation error).

**Haskell does:** The implementation has a nuanced two-phase approach: (1) It records arrival time, then uses the ledger's HardForkSummary to translate the block's slot to a wall clock onset time. (2) It computes ageUponArrival = arrivalTime - onset. If negate(ageUponArrival) > clockSkew, the block is 'tooEarly' and a FarFutureHeaderException is thrown. (3) If the block is NOT too early (i.e., within skew or in the

**Delta:** The spec describes a simple binary check (invalid if far ahead), but the implementation also includes a synthetic delay mechanism for blocks that are slightly in the future (within clock skew tolerance). Additionally, the check is based on arrival time rather than current wallclock time at the moment of judgment, which is a subtle but important distinction. The slot-to-wallclock translation depends on the HardForkSummary derived from the ledger state, which can fail (liftEither on runQuery).

**Implications:** Python implementation must: (1) Use arrival time (not judgment time) for the too-early check. (2) Implement the clock skew tolerance correctly: ageUponArrival = arrivalTime - slotOnset, then tooEarly = clockSkew < negate(ageUponArrival), meaning the block's slot onset is more than clockSkew seconds after arrival. (3) Handle the case where slot-to-wallclock translation fails (e.g., slot beyond the safe zone of the HardForkSummary). (4) Optionally implement the synthetic delay for near-future bloc

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 24. 604982c2

**Era:** shelley

**Spec says:** For a given decentralization parameter d and epoch with n_s slots, randomly select d * n_s slots as OBFT slots. For OBFT slots, the Praos leader schedule is overridden and core nodes create blocks. A fraction f (active slots coefficient) of OBFT slots become 'active OBFT slots' to maintain constant block frequency.

**Haskell does:** The getLeaderSchedule function filters epoch slots using `not (isOverlaySlot a (pp ^. ppDG) slotNo)` — a pool is only a leader if the slot is NOT an overlay (OBFT) slot AND the VRF check passes. The overlay slot determination uses `isOverlaySlot` which takes the epoch start slot and the decentralization parameter d. The test `secondEraOverlaySlots` validates overlay slot computation across era bou

**Delta:** The spec says OBFT slots are 'randomly selected', but the implementation uses a deterministic function `overlaySlots`/`isOverlaySlot` that evenly distributes d*n_s overlay slots across the epoch (round-robin style placement). This is a deliberate design choice where 'randomly' in the spec is implemented as deterministic even spacing. The test confirms this by checking overlay slots across multiple epochs in a second era with era-boundary shifting.

**Implications:** Python implementation must use the same deterministic overlay slot placement algorithm (evenly spaced slots based on d and epoch size), NOT truly random selection. The `overlaySlots` function must be replicated exactly. Additionally, the era-boundary offset (numFirstEraSlots shift) must be handled correctly when computing overlay slots in multi-era scenarios.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 25. 6238c3b6

**Era:** multi-era

**Spec says:** When a node is catching up (syncing), even a one-minute eclipse attack is critical because an attacker can feed k blocks in that period, after which the node cannot switch to the honest chain. Eclipse resistance requirements are significantly stricter during the syncing phase.

**Haskell does:** No implementing code was found for this rule. There is no identified Haskell code that enforces stricter eclipse resistance during the syncing phase versus the fully-synced phase.

**Delta:** The spec describes a critical security property that distinguishes syncing-phase vs synced-phase eclipse vulnerability, but no corresponding implementation was provided. It is unclear whether the Haskell codebase enforces differentiated eclipse resistance based on sync state, or whether this is handled implicitly through other mechanisms (e.g., Genesis, Limit on Patience, peer selection).

**Implications:** For the Python implementation, we must be aware that syncing nodes need stricter eclipse protection. If we implement chain sync without distinguishing sync phase from steady state, a brief eclipse during catch-up could permanently lock the node onto an attacker's fork. The Python implementation should either (1) implement explicit stricter peer diversification during sync, (2) implement the Ouroboros Genesis protocol which addresses this, or (3) at minimum detect and flag when the node may be vu

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 26. 6d3476e6

**Era:** multi-era

**Spec says:** A preferred prefix is a prefix Π of one of the fragments in S, such that Π is guaranteed to be a prefix of a preferred fragment in the lookahead-closure of S. The definition requires that the prefix will definitely be part of the eventually-preferred chain even before the full lookahead closure is available.

**Haskell does:** The implementation uses an iterative approach: it sorts candidates by chain comparison, validates the top candidate, and if only a valid prefix remains (due to rejected/invalid blocks), it truncates that candidate and other candidates containing rejected blocks, re-sorts, and repeats. The 'preferred prefix' concept is realized through the ValidPrefix case where a truncated candidate is only re-add

**Delta:** The spec defines preferred prefix abstractly via lookahead-closure of the candidate set, guaranteeing the prefix is part of the eventually-preferred chain. The implementation approximates this by: (1) sorting candidates using compareChainDiffs rather than computing an explicit lookahead-closure, (2) handling invalid blocks by truncation and re-insertion rather than recomputing candidates from scratch (as the spec suggests), and (3) checking preference of truncated prefixes only against the curre

**Implications:** Python implementation should: (1) understand that the iterative sort-validate-truncate loop is the concrete algorithm for preferred prefix selection, (2) replicate the truncation-based approach rather than the spec's recomputation approach for handling rejected blocks, (3) ensure compareChainDiffs ordering is consistent with the Haskell implementation, (4) handle the edge case where a truncated prefix is no longer preferred over the current chain (should be dropped).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 27. 6da13b01

**Era:** multi-era

**Spec says:** A candidate chain is preferred over the current chain if it is denser (contains more blocks) in a window of s slots anchored at the intersection between the two chains. The Density Rule always considers density at the intersection point and can roll back more than k blocks if necessary.

**Haskell does:** The implementation adds several practical refinements: (1) It requires a peer to offer more than k blocks total after the intersection before it can compete by density (offersMoreThanK guard). (2) It computes density bounds (lowerBound/upperBound) using clipped fragments within the genesis window, accounting for potential unseen slots. (3) It uses hasBlockAfter to determine if potential trailing s

**Delta:** The spec describes a simple density comparison (more blocks in s-slot window = preferred), but the implementation uses density bounds (lower/upper) to handle incomplete information, requires offersMoreThanK before density comparison applies, and disconnects losers rather than simply selecting winners. The implementation is a practical refinement of the abstract spec rule with uncertainty handling.

**Implications:** Python implementation must: (1) Track density bounds (lower/upper) not just exact counts. (2) Implement the offersMoreThanK guard using SecurityParam k. (3) Clip candidate suffixes to the genesis window for density calculation. (4) Handle the hasBlockAfter optimization for potentialSlots. (5) Handle idling peers and peers without headers. (6) Implement the pairwise comparison logic for determining losing peers.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 28. 777b2746

**Era:** multi-era

**Spec says:** Nodes will prefer longer chains over their own, provided that the fork point is no more than k blocks away from the node's tip. The spec describes a per-node check: the fork point must be within k of the node's own tip.

**Haskell does:** The implementation checks all pairs of chains and declares a consensus failure only when BOTH chains in a pair have fork lengths exceeding k (i.e., forkLen tip1 > k AND forkLen tip2 > k). A single chain exceeding k from the fork point is considered recoverable. Additionally, the check is pairwise across all chains, not just between a candidate and the node's own chain.

**Delta:** The spec says the fork point must be no more than k blocks from the node's tip (a unilateral constraint), but the implementation requires BOTH sides of the fork to exceed k before declaring failure. A fork where one side is k+1 and the other is 1 would be acceptable in the implementation but arguably violates the spec's constraint. The implementation is more permissive than the spec describes.

**Implications:** Python implementation must replicate the bilateral check (both fork lengths > k) rather than a unilateral check (either fork length > k). If we implement the spec literally, we would reject forks that the Haskell node accepts, causing divergence. The pairwise nature of the check (all pairs of chains, not just candidate vs own) must also be preserved.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 29. 7953c499

**Era:** multi-era

**Spec says:** The two fragments must either both be non-empty, or they must intersect. The comparison is only definable under this precondition.

**Haskell does:** The implementation has two distinct code paths: (1) When Peras weights are empty (disabled), it asserts the precondition and then handles four cases (both empty, first empty, second empty, both non-empty) using anchor/tip comparisons and selectView. (2) When Peras weights are non-empty, it computes the intersection of the two fragments and errors if they don't intersect, then compares weighted sel

**Delta:** The Peras-enabled code path enforces the intersection precondition at runtime via a hard error rather than an assertion, and lacks the special-case optimizations for empty fragments. The precondition assertion (assertWithMsg) is only applied in the Peras-disabled path. Additionally, the Peras-enabled path uses weightedSelectView on suffixes (a different comparison mechanism than the tip-based selectView in the disabled path).

**Implications:** Python implementation must handle both paths: (1) standard comparison using tip-based selectView when no Peras weights, with the four cases for empty/non-empty combinations, and (2) intersection-based weighted comparison when Peras weights are present. The precondition must be enforced in both paths. The Python implementation should also replicate the optimization where empty-anchor comparisons check if the anchor equals the tip to determine EQ vs LT/GT.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 30. 79af2ab0

**Era:** multi-era

**Spec says:** A node will refuse to produce a new block if the slot distance between the new block and the previous block on the chain exceeds the stability window (3k/f slots). This creates a liveness problem where the system halts and cannot resume.

**Haskell does:** No implementing code was found for the block production refusal logic itself. However, the Haskell test suite has a prop_downtime test that simulates downtime with security parameter awareness (DowntimeWithSecurityParam), uses 1-4 chain generators, enables LoE (Limit on Eagerness), LoP (Limit on Patience), and CSJ (ChainSync Jumping), sets scDowntime=11, and verifies the node can recover from down

**Delta:** The spec describes a fundamental constraint (block gap > stability window => refusal to produce) but no implementing code was provided. The test exercises the Genesis consensus layer's behavior during downtime with specific configuration (LoE, LoP, CSJ enabled) rather than directly testing the block production refusal at the stability window boundary. The test uses DowntimeWithSecurityParam which ties downtime generation to k, suggesting the test exercises downtime scenarios that are bounded rel

**Implications:** The Python implementation must: (1) enforce that block production is refused when slot gap exceeds 3k/f, (2) correctly compute the stability window as 3k/f slots, (3) handle the chain validation constraint that ledger views cannot be obtained beyond the stability window, and (4) the Genesis protocol extensions (LoE, LoP, CSJ) should enable recovery from downtime scenarios that would otherwise halt the chain.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 31. 7b23cbbf

**Era:** shelley

**Spec says:** The EPOCH transition has no environment (unit type). It is a relation that is a subset of the powerset of (EpochState × Epoch × EpochState). The signal is an Epoch value, and the transition maps one EpochState to another EpochState.

**Haskell does:** The Haskell implementation uses `()` as the environment (matching spec), takes an EpochState and Epoch signal, and produces a new EpochState. However, it performs a complex sequence of sub-transitions and state manipulations: SNAP transition, POOLREAP transition, DRep pulser extraction, enactment of governance actions (applying enacted withdrawals, processing proposals via proposalsApplyEnactment)

**Delta:** The spec rule shown is just the type signature of the EPOCH transition. The Haskell implementation reveals the full internal logic which includes: (1) SNAP sub-transition for snapshots, (2) POOLREAP sub-transition for pool retirement, (3) DRep pulsing state extraction and ratification result application, (4) Governance proposal enactment including removal of enacted/expired actions and their subtree siblings, (5) Protocol parameter rotation (cur->prev, future->cur), (6) Return of proposal deposi

**Implications:** The Python implementation must faithfully replicate all sub-steps: snapshot transitions, pool reaping, DRep pulser extraction, governance enactment pipeline (proposalsApplyEnactment), protocol parameter rotation (nextEpochPParams -> curPParams, curPParams -> prevPParams, future reset to Nothing), proposal deposit returns, and cert state updates including dormant epoch counter. The ordering matters - SNAP before POOLREAP, then governance processing. The proposal processing must handle enactment, 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 32. 7d1d0d52

**Era:** multi-era

**Spec says:** A node is considered 'up to date' (alert) when prefix selection can see all available chains to their tips and the node has selected and adopted the best one. When NOT up to date: must insist on a quota of peers before chain selection, must not produce blocks. Transition back to 'not up to date' is an open question (proposal: stay up to date as long as connected to current peers).

**Haskell does:** The Haskell implementation uses a LedgerStateJudgement (TooOld vs YoungEnough) combined with UseBootstrapPeers flag to determine caught-up state. When not caught up (TooOld), the governor restricts known peers to only 'trustable' peers (local root peers clamped to trustable + bootstrap peers from public root peers). Non-trustable peers must not be present in the known peer set before the node reac

**Delta:** The spec describes 'up to date' in terms of prefix selection seeing all chains to their tips. The implementation operationalizes this as LedgerStateJudgement (TooOld/YoungEnough) and enforces the 'quota of peers' requirement by restricting to trustable peers (bootstrap peers + trustable local root peers) when not caught up, rather than requiring a numeric quorum. The spec's open question about transitioning back to 'not up to date' is resolved in implementation via the ledger state judgement mec

**Implications:** Python implementation must: (1) model LedgerStateJudgement with TooOld/YoungEnough states, (2) implement UseBootstrapPeers flag, (3) when LedgerStateJudgement is TooOld and bootstrap peers are in use, restrict the known peer set to only trustable peers (trustable local roots + bootstrap peers), (4) ensure no non-trustable peers appear in the known set before caught-up state is reached.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 33. 858f4e16

**Era:** shelley

**Spec says:** The EPOCH transition is a relation over (EpochState × Epoch × EpochState) with no environment (unit environment). It maps an input EpochState and an Epoch signal to a new EpochState.

**Haskell does:** The Haskell implementation uses unit `()` as the environment and destructures the EpochState into components (snapshots, ledger state, chain account state, gov state, etc.), then sequences sub-transitions (SNAP, POOLREAP) and applies ratification/enactment results (DRep pulsing state extraction, proposal enactment, withdrawal application, deposit returns, gov state updates including committee/cons

**Delta:** The spec gives a high-level type signature only (EpochState × Epoch → EpochState), while the Haskell implementation reveals extensive Conway-era logic: (1) SNAP sub-transition for snapshots, (2) POOLREAP sub-transition for pool retirement, (3) DRep pulsing state extraction and ratification application, (4) proposalsApplyEnactment to remove enacted/expired governance actions and their subtrees, (5) returnProposalDeposits for removed governance actions, (6) gov state field updates (committee, cons

**Implications:** A Python implementation must replicate all sub-transitions and side-effects: SNAP snapshot rotation, POOLREAP pool retirement processing, DRep pulser extraction, governance proposal enactment/expiry with subtree removal, proposal deposit returns, pparams rotation (cur→prev, future→cur), committee/constitution updates from enact state, and treasury withdrawal application. Missing any of these steps would cause epoch boundary divergence.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 34. 89c2c62f

**Era:** multi-era

**Spec says:** The type family 'Ticked :: *→*' maps a state type 's' to its ticked version 's'', representing time-related changes applied to ledger state ('l'), ledger view ('ledvw'), and chain-dependent state ('cds').

**Haskell does:** No implementing code was found for the Ticked type family or its instances for the three specified state types.

**Delta:** The Ticked type family and its instances for 'l', 'ledvw', and 'cds' are not present in the provided codebase. This is a fundamental type-level construct that the spec relies upon for representing slot/epoch progression effects on state.

**Implications:** The Python implementation must define a Ticked wrapper or equivalent mechanism (e.g., a generic class Ticked[S] or separate TickedLedgerState, TickedLedgerView, TickedChainDepState types) that clearly distinguishes between pre-tick and post-tick states. Without the Haskell reference implementation, the Python code must be derived directly from the spec, increasing the risk of misinterpretation of what 'time-related changes' entail for each state type.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 35. 8d5b3117

**Era:** multi-era

**Spec says:** The upper bound of a ValidityInterval with both bounds present uses PV1.to semantics (inclusive) in general Plutus interval construction, consistent with the other single-bound cases.

**Haskell does:** When both bounds are present (SJust i, SJust j), the code uses PV1.strictUpperBound for the upper bound (open/exclusive), whereas the single upper-bound case (SNothing, SJust i) uses PV1.to which creates a closed/inclusive upper bound. This means the interval semantics differ depending on whether a lower bound is also present.

**Delta:** Asymmetric upper bound treatment: with only an upper bound, PV1.to gives an inclusive upper bound; with both bounds, strictUpperBound gives an exclusive upper bound. The single-bound 'to' case includes the endpoint, while the dual-bound case excludes it. This is intentional Plutus V1 design but could be surprising.

**Implications:** Python implementation must replicate this exact asymmetry: when constructing a POSIXTimeRange from a ValidityInterval with both bounds, the upper bound must be strict (open/exclusive, Closure=False), but when only an upper bound is present, use PV1.to which is inclusive (Closure=True). Getting this wrong would cause Plutus script validation mismatches.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 36. 902785a9

**Era:** multi-era

**Spec says:** A genuinely empty candidate fragment (representing an empty candidate chain) is never preferred over our chain. The candidate fragment can become temporarily empty during switch-to-fork operations (rollback + roll forward).

**Haskell does:** The empty-candidate check (_, Empty _) -> ShouldNotSwitch GT is only performed when isEmptyPerasWeightSnapshot is true. When Peras weights are active (the 'otherwise' branch), the function computes AF.intersect and uses weightedSelectView on the suffixes. If the candidate is empty in the Peras-weights-active branch, the behavior depends on AF.intersect and weightedSelectView rather than the explic

**Delta:** The explicit 'empty candidate is never preferred' guard is only in the non-Peras branch. In the Peras-weighted branch, an empty candidate fragment might be handled differently — it would go through intersection logic. If the empty candidate's anchor intersects with our chain, the candidate suffix would be empty, and the comparison would depend on weightedSelectView behavior with an empty suffix. This could potentially allow different behavior than the spec's categorical 'never preferred' rule if

**Implications:** In the Python implementation, we should ensure that the 'empty candidate is never preferred' rule is enforced unconditionally, as the spec states, regardless of whether Peras weights are active. Either add an explicit empty-candidate check before the Peras weight branch, or verify that the Peras-weighted path correctly handles empty candidates to produce ShouldNotSwitch.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 37. 945b465a

**Era:** multi-era

**Spec says:** The chain is divided into two parts based on the security parameter k: (1) the immutable chain consisting of all blocks more than k blocks from the tip, which are known to be stable and will never be rolled back; and (2) the volatile chain consisting of the most recent blocks near the tip that are still subject to rollback.

**Haskell does:** The Haskell implementation uses a weight-based rollback calculation rather than a simple block-count-based one. The `immutableChain` function uses `dropAtMostWeight (maxRollbackWeight k)` which accounts for Peras weight boosts on individual blocks. This means the immutable/volatile boundary is determined by cumulative weight (including per-block Peras weight boosts) rather than by a simple count o

**Delta:** The spec describes the immutable/volatile split as purely count-based (blocks more than k from the tip), but the implementation uses a weight-based budget (maxRollbackWeight k) that incorporates Peras weight boosts per block. With weight boosts, fewer than k blocks may constitute the volatile portion (since boosted blocks consume more of the rollback weight budget). Additionally, the immutable chain is the longer of the weight-trimmed chain and the existing immutable DB chain, providing a monoto

**Implications:** The Python implementation must use weight-based rollback depth calculation (not simple block counting) when determining the immutable/volatile boundary. It must account for Peras weight boosts on individual blocks, compute maxRollbackWeight from k, and implement the monotonicity invariant (immutable chain never shrinks) by taking the max-by-length of the computed immutable prefix and the existing immutable DB chain.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 38. 96e39ee5

**Era:** multi-era

**Spec says:** When a node is syncing/catching up, it MUST connect to a representative sample of N_rs upstream peers such that the probability that none of them serve the honest chain is negligible. The node MUST avoid performing prefix selection (chain selection) until it has connected to at least N_rs peers meeting this threshold.

**Haskell does:** The Haskell code defines `defaultSyncTargets` as a `PeerSelectionTargets` record with specific numeric targets for different peer categories during syncing. Key values: 30 active big ledger peers, 40 established big ledger peers, 5 active peers, 10 established peers. This structure parameterizes the peer selection governor during the CatchingUp/Syncing state, but the code shown does not directly e

**Delta:** The spec defines N_rs as a single conceptual threshold of representative peers before chain selection can proceed. The Haskell implementation decomposes this into multiple granular peer category targets (root, known, established, active × normal and big-ledger). The mapping from the spec's N_rs to these concrete targets is implicit — it is not clear which specific target(s) correspond to the N_rs threshold. The big-ledger-peer targets (30 active, 40 established) appear to be the primary mechanis

**Implications:** A Python implementation must: (1) define equivalent peer selection targets with the same default values during sync mode, (2) implement the gating mechanism that prevents chain/prefix selection until sufficient peers (especially big ledger peers) are connected, and (3) understand that the N_rs concept maps primarily to the big-ledger-peer targets. The exact numeric values (30 active big ledger peers, etc.) should be replicated as defaults. Missing the gating logic would be a critical safety viol

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 39. 970f0fc0

**Era:** multi-era

**Spec says:** LedgerSupportsMempool requires only UpdateLedger b as a superclass constraint, and provides methods: txInvariant, applyTx, reapplyTx, txsMaxBytes, txInBlockSize, txForgetValidated. reapplyTx takes (lc, SlotNo, Validated tx, tls) and returns Except txerr tls. applyTx takes (lc, WhetherToIntervene, SlotNo, tx, tls) returning Except txerr (tls, Validated tx).

**Haskell does:** LedgerSupportsMempool has additional superclass constraints: TxLimits blk, NoThunks (GenTx blk), NoThunks (Validated (GenTx blk)), Show instances for GenTx, Validated GenTx, and ApplyTxErr. txInvariant has a default implementation of 'const True'. applyTx takes TickedLedgerState blk ValuesMK and returns TickedLedgerState blk DiffMK (not the same MK). reapplyTx has an extra HasCallStack constraint 

**Delta:** 1) Additional superclass constraints (TxLimits, NoThunks, Show) beyond UpdateLedger. 2) txInvariant defaults to 'const True' (always passes). 3) applyTx input uses ValuesMK and output uses DiffMK (map-kind-indexed ledger states), differing from the spec's generic tls. 4) reapplyTx has extra ComputeDiffs parameter and HasCallStack constraint, returns TrackingMK instead of same tls. 5) New batch method reapplyTxs not in spec. 6) txsMaxBytes, txInBlockSize, txForgetValidated appear to have been fac

**Implications:** Python implementation must account for: (1) the MapKind distinctions (ValuesMK input, DiffMK/TrackingMK output) which affect how ledger state diffs are tracked and composed; (2) the ComputeDiffs parameter in reapplyTx which controls whether diffs are computed; (3) the batch reapplyTxs method for efficient reapplication; (4) txInvariant defaulting to True; (5) txsMaxBytes/txInBlockSize/txForgetValidated may need to be sourced from TxLimits rather than this class.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 40. 986ff07a

**Era:** shelley

**Spec says:** PRTCL is a transition relation: a subset of P(PrtclEnv × PrtclState × BHeader × PrtclState). It takes a protocol environment, current protocol state, and block header signal, producing a new protocol state.

**Haskell does:** No implementing Haskell code was found for the PRTCL transition rule.

**Delta:** The PRTCL transition rule has no corresponding implementation discovered in the codebase scan. This means we cannot verify whether the implementation matches the spec's type signature or its sub-rule invocations (OVERLAY, UPDN).

**Implications:** The Python implementation must be built directly from the spec. Key risks: (1) the type signature (PrtclEnv, PrtclState, BHeader) → PrtclState must be faithfully represented, (2) sub-rule composition (OVERLAY for slot leader validation, UPDN for nonce evolution) must be correctly integrated, (3) without a reference Haskell implementation to compare against, conformance testing must rely on hand-computed golden vectors derived from the spec's mathematical definitions.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 41. 99b28fae

**Era:** shelley

**Spec says:** The stake distribution is computed by composing the address delegation relation (payment addresses → stake credentials) with the stake pool delegation relation (stake credentials → stake pools), then aggregating all UTxO coins for each stake pool. The spec treats this as a straightforward relational composition followed by aggregation.

**Haskell does:** The Haskell implementation adds several refinements not explicit in the spec: (1) It filters 'activeDelegs' to only include credentials that exist in both the rewards map AND whose target pool exists in psStakePools (registered pools). (2) It aggregates UTxO coins by credential using pointer addresses (ptrs') in addition to direct stake credentials. (3) It unions the UTxO-derived stake with the re

**Delta:** Four key differences: (a) Active delegation filtering requires credential to be registered (in rewards map) AND pool to be registered (in psStakePools) - spec doesn't explicitly mention these filters. (b) Pointer address resolution is used alongside direct credential extraction. (c) Reward account balances are added to UTxO-derived stake per credential. (d) Registered pools with zero delegated stake still appear in the distribution. The Agda formal spec partially captures these with 'm ∪ |reward

**Implications:** Python implementation must: (1) Filter delegations to only registered credentials with registered target pools. (2) Resolve pointer addresses when extracting stake credentials from UTxO outputs. (3) Include reward balances in stake aggregation per credential. (4) Ensure all registered stake pools appear in the final distribution even with zero stake.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 42. a04df8bd

**Era:** multi-era

**Spec says:** The chain preference relation (⊑) is lifted to sets of fragments: S ⊑ F iff there does not exist F' ∈ S such that F ⊏ F'. F must be at least as preferred as every fragment in S. If F ∈ S, then F is a maximal element. All fragments in S must intersect with F (inherited precondition).

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** The set-level chain preference relation (S ⊑ F) has no known Haskell implementation to compare against. This is a specification-only rule that needs to be implemented and tested in Python.

**Implications:** The Python implementation must correctly implement the lifting of the pairwise fragment preference (⊑) to sets. Key concerns: (1) the quantifier is universal-via-negation — no F' in S strictly dominates F; (2) the precondition that all fragments in S must intersect with F must be enforced or checked; (3) when F ∈ S, F should be maximal in S under ⊑.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 43. a245f86f

**Era:** multi-era

**Spec says:** The consensus layer must never switch to a chain that is shorter than the currently selected chain. This is a hard invariant.

**Haskell does:** The chainSelection function uses preferAnchoredCandidate and compareChainDiffs to compare candidates against the current chain. It asserts that all candidates should be switched to (shouldSwitch check) before processing. The candidate selection sorts by compareChainDiffs and only includes truncated prefixes if they are still preferred (ShouldSwitch). The immutableChain test uses maxBy Chain.length

**Delta:** The spec states 'never switch to a shorter chain' as a simple length comparison, but the implementation uses a more nuanced weight-based comparison (compareChainDiffs, preferAnchoredCandidate) that incorporates Peras weight boosts. A chain could theoretically be shorter in block count but preferred due to higher weight. The invariant in practice is 'never switch to a less-preferred chain' where preference is determined by weight, not purely length. The immutableChain function also uses weight-ba

**Implications:** Python implementation must use weight-based chain comparison (not just length) when determining whether to switch chains. The 'shorter chain' invariant from the spec should be interpreted as 'less preferred chain' in weight-aware contexts. The immutable chain computation must account for Peras weight boosts when calculating the rollback budget. A pure block-count implementation would diverge from the Haskell behavior when Peras weights are non-trivial.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 44. ad04678a

**Era:** multi-era

**Spec says:** SelectView has an Ord instance and one chain is strictly preferred over another if its SelectView is greater (via Ord comparison). If two chains have the same SelectView, neither is preferred. The comparison is a simple Ord-based total order.

**Haskell does:** The Haskell implementation does NOT use a simple Ord comparison on SelectView. Instead, it implements a ChainOrder instance that first compares by block number (svBlockNo), and only when block numbers are equal does it delegate to a tiebreaker mechanism (svTiebreakerView via preferCandidate). When the candidate's block number is less than ours (GT case), it returns ShouldNotSwitch without consulti

**Delta:** The spec describes a straightforward Ord-based comparison on SelectView where greater means preferred. The implementation uses a two-phase comparison: (1) compare block numbers, and (2) only on equality, delegate to a TiebreakerView's ChainOrder. This means the SelectView comparison is not a simple Ord but a composite chain ordering with block number as primary key and a pluggable tiebreaker as secondary key. Additionally, the tiebreaker itself uses preferCandidate (ChainOrder) rather than Ord's

**Implications:** A Python implementation must NOT implement SelectView comparison as a simple __lt__/__gt__ on a single comparable value. Instead it must: (1) compare block numbers first, (2) only on block number equality, invoke a protocol-specific tiebreaker mechanism. The tiebreaker mechanism is itself pluggable via the ChainOrder typeclass. The return type carries a reason for switching (Longer vs SelectViewTiebreak) which may need to be modeled. Simply implementing Ord on SelectView would miss the tiebreake

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 45. adc42bb3

**Era:** multi-era

**Spec says:** The consensus design insists on a maximum rollback length of K blocks. Any fork that exceeds K blocks must be rejected, choosing consistency over liveness.

**Haskell does:** The forkTooLong predicate only declares a consensus failure when BOTH branches of a fork exceed K blocks (forkLen tip1 > K AND forkLen tip2 > K). If only one branch is longer than K, it is considered recoverable via a rollback instruction and is NOT a failure.

**Delta:** The spec says there is a hard maximum rollback limit of K blocks, implying any rollback beyond K is disallowed. The implementation is more permissive: it only flags a consensus failure when both sides of a fork exceed K. A single chain diverging more than K from the intersection while the other stays within K is still considered acceptable (the longer chain node can recover via rollback). This is a meaningful relaxation of the strict 'max-K rollback' rule.

**Implications:** A Python implementation must replicate the two-sided check: consensus failure occurs only when BOTH fork branches exceed K, not when just one does. Implementing a naive single-sided check (any fork > K is failure) would be stricter than the Haskell implementation and would produce false consensus failures.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 46. b1b77d93

**Era:** multi-era

**Spec says:** During catch-up/syncing phase, a node MUST NOT perform prefix selection until it has connected to the required representative sample N_rs of upstream peers. This prevents premature adoption of an adversarial chain that would later require rolling back more than k blocks.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Implementation status unknown — no Haskell code located that enforces the N_rs threshold gate before prefix selection during syncing.

**Implications:** The Python implementation must explicitly gate prefix selection on having connected to at least N_rs upstream peers during the catch-up phase. Without this guard, a syncing node could adopt an adversarial chain and later need to roll back beyond k blocks when the honest chain arrives, violating the security model.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 47. b381679e

**Era:** multi-era

**Spec says:** The density of the upstream peer's chain is 'known' when n = m (the downstream peer has validated all headers up to the upstream peer's tip). When n ≠ m, the density is 'unknown'.

**Haskell does:** The implementation uses a more nuanced model: it computes density bounds (lowerBound, upperBound) within a Genesis window, where 'known' density corresponds to upperBound == lowerBound (potentialSlots == 0), which happens when hasBlockAfter is True (i.e., the latest known slot >= firstSlotAfterGenesisWindow) OR the peer is idling with no trailing unknown slots. When the peer hasn't caught up, unkn

**Delta:** The spec describes a simple binary known/unknown based on n=m equality. The implementation uses a continuous density bounds model (lower/upper) clipped to a Genesis window, with special handling for: (1) peers with blocks after the Genesis window (potentialSlots=0, effectively 'known'), (2) the offersMoreThanK qualification threshold, (3) skipping peers with no headers at all, and (4) idling state. The 'known' condition is effectively potentialSlots == 0 rather than a direct tip comparison.

**Implications:** Python implementation must replicate the full density bounds computation including: Genesis window clipping via splitAtSlot, the hasBlockAfter check, potentialSlots/unknownTrailingSlots calculation, the offersMoreThanK guard using SecurityParam k, and the idling flag. A naive n==m check would be insufficient.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 48. b6bf60a2

**Era:** shelley

**Spec says:** The stake distribution is computed by composing the address delegation relation (payment addresses → stake addresses) and the stake pool delegation relation (stake addresses → stake pools), then aggregating all coins from UTxO outputs whose payment addresses map to each stake pool via this composed relation. The result includes ALL registered stake pools and their aggregate stake.

**Haskell does:** The Haskell implementation filters active delegations to only include credentials that (1) exist in the rewards map AND (2) delegate to a pool that exists in psStakePools. It also incorporates reward account balances into the stake computation (stakeRelation = aggregateUtxoCoinByCredential which merges UTxO-derived stake with reward balances), and includes pointer address resolution via ptrs'. The

**Delta:** Three divergences: (1) The spec does not mention filtering delegations by whether the credential is in the rewards map or the pool is registered — the Haskell impl requires both conditions (activeDelegs filter). (2) The spec mentions only UTxO coin aggregation, but the implementation also adds reward account balances to the stake relation. (3) The spec does not mention pointer address resolution, but the implementation resolves pointer addresses via ptrs' when aggregating UTxO coins by credentia

**Implications:** A Python implementation must: (1) filter active delegations to only credentials present in the rewards map delegating to registered pools, (2) include reward balances in the stake computation alongside UTxO-derived stake, (3) resolve pointer addresses when mapping UTxO outputs to stake credentials, and (4) ensure all registered stake pools appear in the output (even with zero stake). Omitting any of these will produce incorrect stake distributions.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 49. be4a8635

**Era:** shelley

**Spec says:** The EPOCH transition covers four distinct events: (A) taking a stake distribution snapshot at epoch beginning, (C) starting a new epoch, (D) taking snapshots of stake pool performance, fee pot, and decayed deposit values at epoch end, and (G) distributing rewards.

**Haskell does:** The Haskell implementation combines all these events into a single epochTransition function that additionally handles Conway-era governance: extracting DRep pulsing state, applying ratification results (enactment and expiration of governance actions), returning proposal deposits, updating committee/constitution/protocol parameters from EnactState, and incrementing the dormant epoch counter. The go

**Delta:** The spec description of EPOCH lists four high-level events (A, C, D, G), but the Conway-era Haskell implementation adds significant governance processing: DRep pulser extraction, ratification state application (rsEnacted/rsExpired), proposal deposit returns, GovState updates (committee, constitution, pparams rotation, future pparams reset), and dormant epoch counter updates. These are Conway-specific extensions not captured in the original EPOCH spec description.

**Implications:** A Python implementation must handle not only the four classical epoch boundary events but also the full Conway governance epoch processing. Missing the governance enactment/expiration logic, proposal deposit returns, or pparams rotation would produce incorrect epoch transitions in the Conway era. The applyEnactedWithdrawals and proposalsApplyEnactment functions are critical and need faithful reimplementation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 50. bfe0c113

**Era:** multi-era

**Spec says:** If the slot is in the next era, the HFC calls a user-provided CrossEraForecaster function. The HFC fully offloads the task of determining safe cross-era forecast ranges to the user.

**Haskell does:** In forecastAcrossShelley, when the slot is in the next era but within maxFor, it calls the current era's ledgerViewForecastAt (Shelley's own forecaster) and then translates the result via translateLedgerView. If the underlying Shelley forecaster fails, it calls 'error' (a partial function causing a crash) rather than returning a proper error. The comment notes that SL.futureLedgerView imposes its 

**Delta:** The spec says the HFC delegates cross-era forecasting to a user-provided function, but the implementation actually reuses the current era's own forecaster and translates the result, with a partial 'error' call if the inner forecaster fails. This means: (1) the cross-era forecast is not truly an independent user-provided function but a composition of within-era forecast + translation, and (2) there is no graceful error handling if the inner forecast's bounds are violated — it crashes with 'error'

**Implications:** The Python implementation must: (1) replicate the composition pattern of calling the current era's forecaster then translating, rather than expecting a standalone cross-era forecast function. (2) Be aware that the maxFor bound computed by crossEraForecastBound gates access, so the inner forecaster 'should' never fail — but if it does, behavior diverges from clean error handling. (3) The crossEraForecastBound function combines ledger tip, era boundary, and both eras' stability windows to compute 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 51. c0146bb5

**Era:** shelley

**Spec says:** The EPOCH rule decomposes pstate into (poolParams, fPoolParams, retiring) and constructs pstate' = (poolParams ∪override fPoolParams, ∅, retiring) before passing to POOLREAP. Future pool parameters are adopted explicitly before the POOLREAP transition. The NEWPP transition is used with signal pp_new = votedValue(pup, pp, Quorum) to update protocol parameters.

**Haskell does:** The Haskell implementation does NOT perform the explicit future pool parameter adoption step (poolParams ∪override fPoolParams, ∅, retiring) before calling POOLREAP. Instead, it passes the certState directly to POOLREAP and relies on the POOLREAP rule itself (or a sub-rule) to handle future parameter adoption internally. Additionally, the Haskell code uses UPEC (Update Proposal Evaluation and Conf

**Delta:** Three divergences: (1) Future pool parameter adoption (poolParams ∪override fPoolParams) is NOT done as a separate step before POOLREAP in the implementation - it's either folded into POOLREAP or handled differently. (2) NEWPP is replaced by UPEC for protocol parameter updates. (3) An additional deposit obligation recomputation step (utxosDeposited = totalObligation) is performed after UPEC that is not in the spec. The PoolreapState wrapper bundles utxoSt, chainAccountState, and full certState r

**Implications:** For the Python implementation: (1) We need to decide whether to follow the spec (explicit future pool param adoption before POOLREAP) or the implementation (let POOLREAP handle it). Following the spec is safer for conformance testing. (2) We must implement UPEC rather than NEWPP if targeting the actual ledger behavior. (3) The deposit recomputation step (totalObligation) must be included to maintain the invariant utxosDeposited == obligationCertState. (4) The construction of ls' happens at a dif

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 52. c1b72f07

**Era:** shelley

**Spec says:** T is the total amount of ada in circulation at the beginning of the epoch. It is used in the monetary expansion equation min(η, 1) · ρ · (T∞ − T), where T∞ − T represents remaining ada for future distribution, ensuring exponentially decreasing rewards over time.

**Haskell does:** No implementing code was found for the definition of T itself. However, the Haskell test 'rewardsBoundedByPot' generates totalLovelace = undelegatedLovelace + fold(stake) and passes it to mkRewardAns, which uses it as the circulation parameter. The test verifies that total distributed rewards never exceed the rewardPot.

**Delta:** The spec defines T as ada in circulation at epoch start used in the monetary expansion formula min(η,1)·ρ·(T∞−T). The Haskell test does not directly test the monetary expansion formula or the T parameter's role in computing the rewards pot; instead it tests a downstream invariant that total rewards distributed ≤ rewardPot. The computation of rewardPot from T via the expansion formula is not tested here.

**Implications:** The Python implementation must: (1) correctly compute T as the sum of all ada in circulation (delegated + undelegated) at epoch boundary, (2) use T in the expansion formula to derive the rewards pot, and (3) ensure that the sum of all individual rewards never exceeds the computed rewards pot. We need tests for both the pot computation from T and the bounded-rewards invariant.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 53. c3f7ac46

**Era:** shelley

**Spec says:** Shelley defines exactly six certificate types: (1) Stake address registration, (2) Stake address de-registration, (3) Delegation, (4) Stake pool registration, (5) Stake pool retirement, and (6) Operational key certificate. The first five are posted to the blockchain; the sixth is presented when used.

**Haskell does:** The ConwayDelegCert type defines four constructors: ConwayRegCert (registration with optional deposit), ConwayUnRegCert (de-registration with optional deposit), ConwayDelegCert (delegation to a Delegatee which can be a pool, DRep, or both), and ConwayRegDelegCert (combined registration and delegation with required deposit). Pool registration, pool retirement, and operational key certificates are h

**Delta:** Three key divergences: (1) Conway adds ConwayRegDelegCert (combined register+delegate) which does not exist in Shelley. (2) Registration and de-registration certificates carry an optional Coin deposit field (StrictMaybe Coin) not mentioned in the Shelley spec. (3) Delegation targets a 'Delegatee' type that can represent delegation to a DRep or combined pool+DRep delegation, reflecting Conway governance features beyond Shelley's pool-only delegation. Pool registration, pool retirement, and operat

**Implications:** Our Python implementation must: (1) Model both Shelley-era and Conway-era certificate types, understanding that ConwayDelegCert is an evolution of Shelley's simpler model. (2) Handle the optional deposit field on registration/de-registration certificates. (3) Support the Delegatee type with its multiple delegation targets (pool, DRep, pool+DRep). (4) Implement ConwayRegDelegCert as a Conway-specific addition. (5) Ensure pool registration, pool retirement, and operational key certificates are mod

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 54. c40872be

**Era:** multi-era

**Spec says:** The decentralization parameter `d` cannot change within the stability window. If it did, honest overlay headers could become invalid because the overlay schedule computed with the reduced `d` might differ from the schedule computed with the unreduced `d`, leading to false negatives for honest headers. The influence of `d` on overlay slot determination is non-monotonic, so even restricting `d` to o

**Haskell does:** The OVERLAY transition rule implementation takes `dval` (the decentralization parameter) as an input from the environment (`OverlayEnv`) and uses it directly in `lookupInOverlaySchedule` to determine whether a slot is an overlay slot, an active genesis key slot, or a free PRAOS slot. The code itself does not enforce the invariant that `d` cannot change within the stability window — this constraint

**Delta:** The spec describes a critical invariant about `d` stability that is enforced by the protocol's parameter update mechanism (PPUP/NEWPP rules and the epoch boundary), not by the OVERLAY transition rule directly. The Haskell OVERLAY code consumes `d` but does not validate that `d` has not changed within the stability window. This is a design-level constraint enforced elsewhere, not a gap in the OVERLAY rule per se, but it means the OVERLAY rule is correct only under the assumption that the caller p

**Implications:** For a Python implementation: (1) The OVERLAY equivalent must accept `d` from the environment and use it in overlay schedule lookup, matching the Haskell code. (2) The invariant that `d` does not change within the stability window must be enforced at the epoch boundary / parameter update level, not inside the overlay transition. (3) Tests should verify that the overlay schedule classification is consistent when `d` is held constant, and that changing `d` can indeed cause slot classification to fl

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 55. c4f1343a

**Era:** shelley

**Spec says:** The monetary expansion contribution is min(η, 1) · ρ · (T∞ − T), where η is the ratio of blocks produced to expected blocks. For Ouroboros Praos, expected blocks = slots_per_epoch × active_slot_coefficient f. T∞ is the max supply (45×10^9 ada) and T is current circulation.

**Haskell does:** The implementation computes deltaR1 = floor(min(1, eta) * ρ * reserves), where reserves = T∞ − T (i.e., it uses reserves directly, not T∞ − T explicitly). Critically, when the decentralization parameter d ≥ 0.8, eta is hardcoded to 1 regardless of actual block production. Also, expectedBlocks = floor((1 - d) * activeSlotVal(asc) * slotsPerEpoch), which factors in the decentralization parameter d —

**Delta:** Two deviations: (1) When d ≥ 0.8 (highly centralized), eta is forced to 1 regardless of actual block production ratio, meaning monetary expansion always proceeds at full rate. (2) The expected blocks formula includes a (1-d) factor, so only non-federated slots contribute to the expected block count. The spec's description of expected blocks as 'slots_per_epoch × f' omits the (1-d) factor. Additionally, the result is floored via rationalToCoinViaFloor (truncation toward zero).

**Implications:** Python implementation must: (1) apply the d ≥ 0.8 override setting eta=1, (2) compute expectedBlocks as floor((1-d) * activeSlotVal(asc) * slotsPerEpoch), (3) use floor (truncation) when converting the rational monetary expansion to Coin, (4) compute reserves as maxSupply - circulation (the 'circulation' function in Haskell accounts for treasury, reserves, fees, deposits, and rewards).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 56. c6d5c866

**Era:** shelley

**Spec says:** Every epoch, monetary expansion contribution = min(η, 1) · ρ · (T∞ − T), where η = blocks_made / expected_blocks. Expected blocks for Praos = slots_per_epoch × active_slot_coefficient f. T∞ is the max supply (45×10⁹ ada), and T is current circulation.

**Haskell does:** The implementation computes deltaR1 = floor(min(1, η) · ρ · reserves), where reserves = T∞ − T (reserves, not maxSupply directly). Expected blocks = floor((1 - d) · activeSlotVal(asc) · slotsPerEpoch), which factors in the decentralization parameter d. When d >= 0.8, η is forced to 1 (bypassing the ratio entirely). The monetary expansion is applied to reserves (not maxSupply minus circulation comp

**Delta:** Three differences: (1) The spec says expected_blocks = slots_per_epoch × f, but the implementation multiplies by (1-d) to account for decentralization, so expected_blocks = floor((1-d) · f · slotsPerEpoch). (2) When d >= 0.8, η is hardcoded to 1, which the spec does not mention. (3) The spec describes the formula in terms of T∞ − T, while the code uses reserves directly from the accounting state (which should equal T∞ − T but is tracked as a separate ledger field).

**Implications:** Python implementation must: (1) include the (1-d) factor in expected blocks calculation, (2) implement the d >= 0.8 → η=1 override, (3) use reserves from ledger state directly rather than computing T∞ − T, and (4) use floor rounding (rationalToCoinViaFloor) for deltaR1.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 57. c843241b

**Era:** multi-era

**Spec says:** Under Ouroboros Genesis, a syncing node must connect to a sufficiently large number of upstream peers and must refuse to make chain selection decisions if that peer quota is not reached. When syncing, prefix selection will always pick the honest chain at every intersection provided it can see it. The key risk is eclipse attacks during syncing where an adversary feeds k blocks from an adversarial c

**Haskell does:** The Haskell test prop_longRangeAttack explicitly tests Praos behavior (not Genesis) and asserts that the honest chain is NOT selected (i.e., the long-range attack succeeds under Praos). The test comment says 'This is the expected behaviour of Praos to be reversed with Genesis. But we are testing Praos for the moment.' The negation `not . selectedHonestChain` confirms this is testing the vulnerabil

**Delta:** The Haskell test verifies that Praos is VULNERABLE to long-range attacks (honest chain is not selected), serving as a baseline/regression test. Genesis mitigation (peer quota enforcement, refusing chain selection without sufficient peers) is not yet implemented or tested. The spec describes the Genesis solution but the test only validates the Praos failure mode.

**Implications:** Our Python implementation should test both: (1) that without Genesis protections (Praos mode), a long-range attack succeeds (adversary chain adopted), matching the Haskell test; and (2) that with Genesis protections enabled (peer quota enforcement), the honest chain is selected and the attack fails. We must be careful to model both the block tree with an alternative adversarial chain and the peer schedule that simulates a long-range attack pattern.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 58. c9c58838

**Era:** multi-era

**Spec says:** The Follower type provides four operations: followerInstruction (non-blocking, Maybe), followerInstructionBlocking (blocking), followerForward (list of points, returns Maybe Point), and followerClose. The spec description does not mention specific behavioral details beyond the basic API.

**Haskell does:** The Haskell implementation adds several important behavioral semantics beyond the basic API: (1) followerClose is idempotent - after closing, all other operations throw ClosedFollowerError; (2) followerForward must be given points in order of preference and moves to the first point on the current chain; (3) after a successful followerForward, the first followerInstruction will be a RollBack to tha

**Delta:** The Haskell implementation specifies critical behavioral invariants not captured in the extracted spec: (a) idempotent close with ClosedFollowerError on subsequent operations, (b) followerForward uses preference ordering and the next instruction after forward is always a RollBack, (c) immutable-part followers never see rollbacks, (d) Functor instance is derived allowing mapping over the block component type 'a'.

**Implications:** Python implementation must: (1) implement idempotent close() that raises ClosedFollowerError on subsequent calls to any method, (2) ensure followerForward processes points in order and returns the first match on the current chain, (3) guarantee the RollBack-after-forward invariant, (4) implement the Functor-like fmap capability over the block component type, (5) ensure followers in the immutable portion never receive rollback instructions.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 59. cdd4df15

**Era:** byron

**Spec says:** The EBB header is a 5-element CDDL array with fields: protocolMagic (u32), prevBlock (blockid), bodyProof (hash), consensusData (ebbcons), extraData ([attributes]). The bodyProof is described generically as 'a hash serving as proof of the block body contents'. The extraData is '[attributes]' — an array of attributes. The consensusData is 'ebbcons' without further detail on its internal structure i

**Haskell does:** The implementation encodes the 5-element structure but with several notable specifics: (1) bodyProof is always hardcoded as the CBOR-serialized hash of an empty list `([] :: [()])`, meaning the body is always assumed to be an empty slot leader schedule. (2) consensusData is encoded as a 2-element list containing epoch number and chain difficulty. (3) extraData is a 1-element list containing a 'gen

**Delta:** Three divergences: (a) The bodyProof is not computed from actual body contents but is always the hash of an empty list — this is a semantic simplification/assumption not visible in the spec. (b) The extraData genesisTag logic (key 255 -> 'Genesis' string for non-zero epoch genesis blocks, empty map otherwise) is an implementation-specific convention not described in the CDDL spec rule. (c) The prevBlock field uses an Either type to distinguish genesis hash from regular block hash, which is an im

**Implications:** For Python implementation: (1) The bodyProof must be computed as the CBOR hash of an empty list serialized as CBOR — not from any actual body data. Use `hash(cbor_encode([]))`. (2) The extraData encoding must replicate the genesisTag logic: if the previous block is a genesis hash and epoch > 0, include `{255: b'Genesis'}` in the attributes map; otherwise use an empty map. (3) The prevBlock field must handle the genesis block case where the previous hash comes from the genesis block hash rather t

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 60. ced253d3

**Era:** multi-era

**Spec says:** When the clock moves backward, the node must rollback (potentially to a strictly smaller chain) by re-initialising the chain DB from scratch, because the ledger DB does not support such rollback directly. Blocks previously marked immutable may no longer be truly immutable.

**Haskell does:** No implementing code was found. The spec describes a complex recovery mechanism involving chain DB re-initialization on clock regression, but no corresponding Haskell implementation was provided for analysis.

**Delta:** Cannot verify whether the described re-initialization logic, immutability reconsideration, and backward-clock rollback are actually implemented. The spec outlines a critical safety requirement with no visible implementation.

**Implications:** For the Python implementation: (1) We must implement a mechanism to detect backward clock movement and trigger chain DB re-initialization rather than relying on standard ledger rollback. (2) We must handle the case where previously immutable blocks become mutable again. (3) This is a critical security concern -- without proper handling, an attacker could exploit clock skew to get future blocks accepted permanently. (4) The absence of reference implementation code means we must rely solely on the

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 61. d0062b37

**Era:** shelley

**Spec says:** For non-active OBFT slots (the (1-f) fraction where f is the active slots coefficient), no node shall produce a block — neither old core nodes nor stake pool nodes.

**Haskell does:** The Haskell test expectedCannotForge checks that the CannotForge reason is specifically PBftCannotForgeThresholdExceeded, returning True only for that variant and False for all others. No implementing production code was provided to verify the slot-level enforcement logic itself.

**Delta:** No implementing code was found for the slot-level active/non-active determination and enforcement. The Haskell test only checks the CannotForge error variant (PBftCannotForgeThresholdExceeded) but does not directly test the (1-f) slot fraction logic or explicitly distinguish between core nodes and stake pool nodes as the spec requires.

**Implications:** The Python implementation must: (1) implement the active slot coefficient-based slot selection that determines which OBFT slots are active vs non-active, (2) enforce that no block is produced in non-active slots regardless of node type, and (3) produce a specific CannotForge error (equivalent to PBftCannotForgeThresholdExceeded) when forging is attempted in such slots. Without the production code, we must derive the slot selection logic from the spec and ensure both core nodes and stake pool nod

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 62. dd982c2b

**Era:** shelley

**Spec says:** During the decentralization transition, for any slot designated as an OBFT slot (one of the d * n_s randomly selected slots in the epoch), no stake pool node shall create a block, even if it was elected as a Praos slot leader for that slot. The Praos leader schedule is overridden for OBFT slots.

**Haskell does:** The Haskell code defines an OBftSlot data type with two constructors: NonActiveSlot (no one leads) and ActiveSlot (a specific genesis key holder leads). The type only models which genesis key is active or whether the slot is non-active — it does not explicitly encode the enforcement logic that prevents stake pool nodes from creating blocks in OBFT slots. The actual enforcement (checking whether a 

**Delta:** The provided code is only the data type definition for OBftSlot. It distinguishes between NonActiveSlot and ActiveSlot (with a genesis key hash), but the critical enforcement rule — that stake pool nodes must NOT forge blocks for OBFT slots — is not visible in this snippet. The spec rule is about enforcement behavior, while the code shown is only the classification data type. The actual filtering/rejection logic is missing from the provided code.

**Implications:** In the Python implementation, we need to: (1) Define an equivalent OBftSlot type with NonActiveSlot and ActiveSlot variants, (2) Critically, implement the enforcement logic that checks whether a given slot is an OBFT slot and, if so, rejects any block produced by a stake pool (non-genesis) node. We must not rely solely on the data type — we must also implement the slot overlay schedule computation (selecting d * n_s slots per epoch) and the block validation check that a Praos leader cannot forge

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 63. e01bc5ee

**Era:** shelley

**Spec says:** The leader eligibility check is ℓ < 1 - (1-f)^σ, equivalently (1/(1-ℓ)) < exp(-σ · ln(1-f)). The leader value ℓ is derived from the VRF output, f is the active slot coefficient, and σ is relative stake.

**Haskell does:** The implementation has two special cases diverging from the pure mathematical formula: (1) When activeSlotVal f == maxBound (i.e., f=1), it always returns True since ln(1-f) is undefined. (2) It uses taylorExpCmp with only 3 iterations to approximate the exponential comparison, and when MaxReached (i.e., the Taylor expansion is inconclusive after 3 terms), it returns False (conservative: node does

**Delta:** Three divergences: (1) f=1 degenerate case always succeeds - not in spec. (2) Taylor approximation with only 3 terms plus conservative MaxReached→False policy means some borderline-eligible leaders will be incorrectly rejected. (3) When certNat == certNatMax, the code clamps 1/(1-ℓ) to certNatMax instead of infinity, which could theoretically cause a false negative for a node that should always lead (ℓ=1 means the VRF output is maximal).

**Implications:** Python implementation must replicate: (1) the f=1 special case returning True, (2) the Taylor expansion comparison with exactly 3 iterations and the same conservative tie-breaking (MaxReached→False, ABOVE→False, BELOW→True), (3) the same fixed-point arithmetic precision (FixedPoint type), and (4) the certNat==certNatMax clamping behavior. Using arbitrary-precision or floating-point math instead of matching the Taylor/fixed-point approach will produce different results on boundary cases.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 64. e4c8f8da

**Era:** multi-era

**Spec says:** The type family SelectView maps a protocol type p to hdrVwCS, used for chain selection via Ord. This is often BlockNo.

**Haskell does:** No implementing code was found to analyze.

**Delta:** Cannot verify that the Haskell implementation correctly defines SelectView as a type family mapping to BlockNo for the concrete protocol instantiations, nor that Ord on the resulting type is used consistently for chain selection.

**Implications:** The Python implementation must define a SelectView equivalent (likely a function or type alias) that projects headers to a comparable chain-selection view (typically BlockNo). The Ord-based comparison must be the sole mechanism for chain selection preference. Without reference Haskell code, we must rely on the spec to ensure our implementation uses BlockNo comparison for standard protocols and supports alternative SelectView types for custom protocols.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 65. e8017b77

**Era:** shelley

**Spec says:** The EPOCH rule decomposes pstate into (poolParams, fPoolParams, retiring), computes pstate' = (poolParams ∪override fPoolParams, ∅, retiring) to adopt future pool parameters before POOLREAP, then passes pstate' into the POOLREAP transition. The spec has explicit pool parameter adoption (merging future pool params and clearing fPoolParams) as a distinct step within the EPOCH rule itself.

**Haskell does:** The Haskell implementation does NOT perform the explicit pstate' = (poolParams ∪override fPoolParams, ∅, retiring) computation within the epochTransition function. Instead, it passes the certState directly to POOLREAP without this intermediate step. The pool parameter adoption (merging fPoolParams into poolParams) is presumably handled inside the POOLREAP sub-rule or elsewhere in the era-specific 

**Delta:** 1) Pool parameter adoption (fPoolParams merge): The spec performs this explicitly between SNAP and POOLREAP in the EPOCH rule. The Haskell code delegates this to the POOLREAP sub-rule or handles it implicitly. 2) Protocol parameter updates: The spec uses votedValue(pup, pp, Quorum) followed by NEWPP. The Haskell code uses a single UPEC rule that consolidates both steps. 3) Deposit recalculation: The Haskell code explicitly recomputes utxosDeposited = totalObligation after all transitions, which 

**Implications:** For the Python implementation: (1) We must decide whether to follow the spec's explicit fPoolParams adoption step or the Haskell approach of delegating it. Following the spec is cleaner and more auditable. (2) We need to understand whether UPEC is equivalent to votedValue+NEWPP or if behavior differs. (3) The deposit recomputation at the end of the epoch transition is a defensive measure in Haskell; we should decide whether to replicate it or trust the sub-rules. (4) NonMyopic field needs to be 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 66. ea8687ac

**Era:** multi-era

**Spec says:** Comparing two anchored fragments proceeds by four cases based on emptiness, with the precondition that fragments must intersect. Case 4 (both non-empty) compares the two most recent headers using the consensus protocol chain selection API.

**Haskell does:** The Haskell implementation adds an optimization branch: when 'Peras weights' are non-empty (isEmptyPerasWeightSnapshot returns false), it bypasses the four-case analysis entirely and instead computes the intersection of the two fragments, extracts suffixes, and compares using a weightedSelectView that incorporates Peras weights. The spec's four-case logic only runs when Peras is disabled. Addition

**Delta:** The implementation has a secondary code path (Peras-weighted comparison) not described in the spec. When Peras weights are active: (1) the four-case analysis is skipped, (2) comparison uses weighted select views over suffixes from the intersection point rather than comparing tips, and (3) the precondition is enforced via a runtime error ('error') rather than assertWithMsg. This means the spec's 'prefer extension' rule (cases 2/3) is not applied when Peras weights are active — instead, weighted s

**Implications:** A Python implementation following only the spec will not handle the Peras-weighted case. If Peras weights are irrelevant (e.g., always empty/disabled), the four-case spec logic suffices. For Case 4 (both non-empty), the Python implementation must use selectView on the tip headers and compare them using the consensus protocol's ordering. The precondition (fragments must intersect) must be validated. The Peras branch can be deferred unless Peras protocol support is needed.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 67. ec776307

**Era:** multi-era

**Spec says:** A candidate chain is preferred over the current chain if (1) it is longer than the current chain, and (2) the intersection point is no more than k blocks away from the tip of the current chain. This is a pairwise comparison: candidate vs. current chain.

**Haskell does:** The implementation checks ALL pairs of chains (not just candidate vs current), and declares a consensus failure only when BOTH forks from the intersection exceed k blocks (i.e., forkLen tip1 > k AND forkLen tip2 > k). This is a multi-chain consensus condition check rather than a simple binary chain-preference rule. A single chain exceeding k from the intersection is considered recoverable.

**Delta:** Three divergences: (1) The spec describes a binary preference rule (candidate vs current), but the Haskell code checks all pairwise combinations of chains, acting as a global consensus health monitor. (2) The spec says the intersection must be no more than k blocks from 'our tip' (one chain), but the code requires BOTH chains to exceed k from the intersection before declaring failure - meaning a fork where only one side exceeds k is tolerated. (3) The spec uses chain length comparison for prefer

**Implications:** The Python implementation must decide whether to implement: (a) the spec's simple binary chain preference rule, or (b) the Haskell's multi-chain consensus monitoring approach. If implementing the spec, chain selection should compare lengths and check rollback depth from our tip only. If matching Haskell behavior, both fork lengths from the intersection must exceed k for a failure. The asymmetry in the Haskell code (tolerating one-sided long forks) is a deliberate design choice not captured in th

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 68. ec841801

**Era:** multi-era

**Spec says:** The type family 'CodecConfig :: B→*' maps a block type 'b' to its codec configuration type 'codecc', used for serialisation and deserialisation. This ensures each block type has an associated codec configuration that governs how data is serialised/deserialised.

**Haskell does:** No implementing Haskell code was provided for the CodecConfig type family mapping itself. However, the Haskell test suite exercises this via roundTripAlonzoCommonSpec which calls roundTripAlonzoEraTypesSpec and roundTripShelleyCommonSpec to verify round-trip serialisation/deserialisation for all era-specific types.

**Delta:** No implementation code available for direct comparison. The spec defines a type-level mapping (CodecConfig :: B→*) while the Haskell tests validate the contract indirectly through round-trip serialisation tests for Alonzo and Shelley era types. Without the Python codec implementation, we cannot verify structural alignment.

**Implications:** The Python implementation must: (1) define a codec configuration type/class for each block type (era), (2) ensure that every serialisable type can round-trip through CBOR encode/decode using the appropriate codec config, (3) cover both Shelley-common types and Alonzo-era-specific types.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 69. f017d404

**Era:** multi-era

**Spec says:** The Forecast type has a `forecastAt :: WithOrigin SlotNo` anchor and a `forecastFor :: SlotNo -> Except OutsideForecastRange (Ticked a)` function with the precondition that `At s >= forecastAt`.

**Haskell does:** No implementing Haskell code was found for analysis.

**Delta:** No implementation to compare against; the spec defines a data type with a precondition that must be enforced by any implementation.

**Implications:** The Python implementation must: (1) represent the Forecast type with an anchor slot (WithOrigin SlotNo) and a forecast function, (2) enforce or document the precondition that the queried slot is >= forecastAt, (3) return either a Ticked value or an OutsideForecastRange error, (4) handle the WithOrigin type (which can be Origin or At slot).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 70. f289e74c

**Era:** shelley

**Spec says:** The hash of the VRF verification key H(vk_VRF) is included in the stake pool registration certificate. During leader election, the VRF key pair is used to prove a pool won its private lottery for a given slot.

**Haskell does:** The doValidateVRFSignature function performs a multi-step validation: (1) looks up the pool's registered VRF key hash from the pool distribution, (2) compares the registered VRF key hash (vrfHKStake) against the hash of the VRF verification key presented in the block header (vrfHKBlock), (3) verifies the VRF certificate against the slot and epoch nonce, (4) checks the VRF leader value against the 

**Delta:** The implementation enforces four distinct failure modes (VRFKeyUnknown, VRFKeyWrongVRFKey, VRFKeyBadProof, VRFLeaderValueTooBig) that are not explicitly described in the spec. The spec also does not mention the inputs to the VRF (slot + eta0 epoch nonce) or the leader nat value comparison against stake fraction and active slot coefficient f.

**Implications:** The Python implementation must replicate all four validation checks in sequence: (1) pool lookup in distribution, (2) VRF key hash comparison, (3) VRF certificate verification with mkInputVRF(slot, eta0), (4) leader nat value check against sigma and f. Each must produce the corresponding error type on failure.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 71. f3890042

**Era:** shelley

**Spec says:** T is the amount of ada in circulation at the beginning of the epoch for which rewards are being calculated, used in the formula min(η, 1) · ρ · (T∞ − T).

**Haskell does:** No implementing code was found for review.

**Delta:** Cannot verify whether the Haskell implementation correctly computes T as the total ada in circulation at epoch boundary, or whether it correctly uses T in the monetary expansion formula. The definition of 'ada in circulation' (whether it includes reserves, treasury, deposits, etc.) cannot be verified without code.

**Implications:** The Python implementation must carefully define T as total lovelace in circulation at the epoch boundary snapshot. This likely equals T∞ minus the reserves. The precise components (UTxO + rewards + treasury + deposits + fees) must be validated against the Shelley spec Section 5.5.3 and the actual ledger implementation to ensure T is computed consistently.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 72. fba4de28

**Era:** multi-era

**Spec says:** A shorter chain is never preferred over a longer chain. This is a stronger requirement than prefer-extension. It says nothing about chains of equal length (allowing tie-breaking rules like in Praos). Ouroboros Genesis violates this assumption but not prefer-extension.

**Haskell does:** The implementation in preferAnchoredCandidate has two branches: (1) when Peras weights are empty (standard mode), it delegates to preferCandidate which compares SelectView (block number-based chain ordering) - this respects never-shrink because SelectView comparison is based on block number which correlates with chain length. However, when comparing tip-to-tip via preferCandidate/selectView, the c

**Delta:** The Peras-weighted branch (otherwise clause) can prefer a shorter chain over a longer chain based on accumulated Peras voting weight on the suffix after the intersection point. This is an intentional violation of the never-shrink assumption, analogous to the Genesis rule mentioned in the spec. The standard (non-weighted) branch respects never-shrink because preferCandidate on SelectView respects block number ordering, but the comparison is technically on block number of the tip rather than chain

**Implications:** Python implementation must: (1) When Peras weights are empty/absent, ensure that chain selection never prefers a shorter chain - the standard SelectView comparison by BlockNo achieves this. (2) When Peras weights are present, correctly compute weighted views and allow shorter chains to win if they have sufficient weight. (3) Handle the edge cases: Empty vs Empty (EQ, no switch), non-empty vs Empty (no switch), Empty anchor vs candidate tip (switch only if tip differs from anchor point). (4) Equa

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 73. fbd956ab

**Era:** shelley

**Spec says:** For non-active OBFT slots, no block shall be considered valid by any node. Even if a block were produced for a non-active OBFT slot, all nodes must reject it as invalid. Non-active OBFT slots are OBFT slots not selected as active OBFT slots.

**Haskell does:** No implementing code was found for this rule.

**Delta:** The rule requiring rejection of blocks from non-active OBFT slots has no identified Haskell implementation to compare against. This could mean the logic is embedded in a broader block validation pipeline not yet located, or it is enforced implicitly through slot leader schedule filtering.

**Implications:** The Python implementation must explicitly validate that blocks produced in non-active OBFT slots are rejected during block validation. Without a reference implementation, the Python code must be built directly from the spec. Care must be taken to correctly classify OBFT slots as active vs non-active and to reject blocks from the latter category at the appropriate point in the validation pipeline.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

