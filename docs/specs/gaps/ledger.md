# Ledger — Critical Gap Analysis

**104 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. 00f80587

**Era:** shelley

**Spec says:** LEnv is a product type with four fields: (1) slot : Slot, (2) txIx : Ix — the transaction index within the current block, (3) pp : PParams, and (4) acnt : Acnt — the accounting state.

**Haskell does:** LEnv is a record type with five fields: (1) slot : Slot, (2) ppolicy : Maybe ScriptHash, (3) pparams : PParams, (4) enactState : EnactState, and (5) treasury : Coin.

**Delta:** Three significant divergences: (A) The spec's 'txIx : Ix' field is replaced by 'ppolicy : Maybe ScriptHash' in the Haskell implementation — these are entirely different concepts (transaction index vs. optional constitution script hash). (B) The spec's 'acnt : Acnt' (accounting state) is replaced by 'enactState : EnactState' — EnactState is a richer type that likely contains accounting info but is structurally different. (C) The Haskell implementation adds a fifth field 'treasury : Coin' which ha

**Implications:** The Python implementation must follow the Haskell implementation's field set (slot, ppolicy, pparams, enactState, treasury) rather than the spec's four-field definition. Using the spec's txIx field instead of ppolicy would cause failures in downstream LEDGER rule transitions that rely on the constitution policy hash. Similarly, using a simple Acnt instead of EnactState would lose governance enactment context, and omitting treasury would break treasury-related validation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. 03b5367a

**Era:** shelley

**Spec says:** The DELEG-DELEG rule requires: (1) c ∈ DCertDeleg, (2) hk = cwitness(c), (3) hk ∈ dom(rewards) — i.e., the delegating credential must be registered. The transition updates delegations via union-override-right with {hk ↦ dpool(c)}, leaving all other state unchanged.

**Haskell does:** The Haskell test demonstrates a DelegateeNotRegisteredDELEG error for the Alonzo era, which is an additional check not explicitly stated in the Shelley-era DELEG-DELEG rule. This error validates that the target pool (dpool(c)) must be registered in the stake pool registry. The Shelley spec rule as written only checks that the delegator credential is in dom(rewards), but the implementation adds a c

**Delta:** The Haskell implementation enforces an additional precondition not shown in the extracted spec rule: the target stake pool (dpool(c)) must be registered in the pool parameters. The DelegateeNotRegisteredDELEG error is raised when the pool identified by dpool(c) is not found in the registered pools. This check may be part of a different layer (DELPL or DELEG in later eras) or an implicit precondition in the spec.

**Implications:** The Python implementation must include a check that the target pool (dpool(c)) is registered in the pool parameters, not just that the delegator credential is registered. Failing to implement this will allow delegations to non-existent pools, diverging from the Haskell ledger behavior. The DelegateeNotRegisteredDELEG error with mkKeyHash 1 serves as a golden test vector for this failure case.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 3. 042a6d29

**Era:** byron

**Spec says:** CHAIN rule for EBBs requires two preconditions: (1) bIsEBB b must be true, and (2) bSize b ≤ 2^21 (2097152 bytes). When both hold, only the block hash h is updated to h' := bhHash(bHead b), while all other chain state components (s_last, sgs, utxoSt, ds, us) remain unchanged.

**Haskell does:** The implementing code `blockToIsEBB = headerToIsEBB . getHeader` only shows the EBB detection logic (extracting the header and checking if it's an EBB). The block size check (≤ 2^21) is not visible in the provided snippet — it may be enforced elsewhere in the chain validation pipeline. The test helper `mkNextEBB'` constructs an EBB block with a previous hash linkage and epoch number but does not e

**Delta:** The size constraint (bSize b ≤ 2^21) enforcement is not visible in the provided implementation code. The test helper creates EBBs but doesn't appear to test: (1) rejection of oversized EBBs, (2) that non-hash state components are unchanged after EBB processing, (3) that the hash is correctly updated to bhHash(bHead b).

**Implications:** Python implementation must: (1) implement the bIsEBB check, (2) enforce the 2^21 byte size limit for EBBs, (3) ensure only the hash field is updated in chain state when processing EBBs, (4) ensure all other state fields (s_last, sgs, utxoSt, ds, us) are preserved exactly. Missing the size check would allow oversized EBBs to be accepted.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 4. 06c01695

**Era:** shelley

**Spec says:** rewardOnePool takes parameters (pp, R, n, N̄, poolHK, pool, stake, tot, addrs_rew) and: (1) computes pstake as sum of all delegated stake, (2) computes ostake as sum of owner stake, (3) σ = pstake/tot, (4) p_r = pledge/tot, (5) maxP = maxPool pp R σ p_r if pledge ≤ ostake else 0, (6) poolR = poolReward(d pp) σ n N̄ maxP, (7) mRewards maps each non-owner member to r_member reward, (8) lReward = r_o

**Haskell does:** The Haskell implementation takes σ and σa (sigma and sigmaA, the pool's relative stake over total and active stake respectively) as pre-computed parameters rather than computing them internally. It does NOT take poolHK or addrs_rew as parameters. It does NOT filter rewards by addrs_rew at the end. The pledge ratio p_r is computed as mkRelativeStake(pledge) = clamp(pledge / tot) rather than pledge/

**Delta:** Multiple divergences: (1) σ and σa are passed in rather than derived from stake/tot - the caller computes them. (2) addrs_rew filtering is absent - all computed rewards are returned without restricting to active reward addresses. (3) The pledge ratio uses clamp(pledge/tot) which bounds it to [0,1] rather than raw division. (4) Leader and member rewards are combined with ∪⁺ (additive union) not plain ∪, so if the pool's reward account also appears as a member delegator, the rewards accumulate rat

**Implications:** Python implementation must decide which interface to follow. Key considerations: (1) If following the Haskell approach, σ and σa must be pre-computed by the caller. (2) The addrs_rew filtering may need to happen at a higher level if following Haskell. (3) The ∪⁺ behavior is important: if a pool operator is also a delegator in the same pool, their member reward and leader reward should be summed, not have one overwrite the other. (4) The clamp on pledge ratio should be replicated to ensure it sta

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 5. 07d442b1

**Era:** shelley

**Spec says:** The DELEGS transition preserves value: Val(s) = Val(s') + w, where w = wbalance(txwdrls(t)). The proof accounts for withdrawals being subtracted from reward accounts, with the withdrawn amount w bridging the value difference between source and target states.

**Haskell does:** The Haskell test (balancesSumInvariant) checks a simplified version: (1) sum of all reward balances does not change between source and target, (2) any accounts removed from source had zero balance, (3) any accounts added in target have zero balance. This test does NOT account for the withdrawal amount w from the spec lemma — it checks that the total balance sum is invariant, which is a different (

**Delta:** The Haskell test checks balance-sum invariance of reward accounts only (no withdrawal offset w), while the spec states a broader value preservation property involving the full state valuation Val() and the withdrawal amount w. The Haskell test is a necessary but not sufficient check for the full spec property. Additionally, the implementation processes certificates right-to-left (gamma :|> txCert pattern matches the last element), which is an implementation detail not visible in the spec's induc

**Implications:** Python implementation should: (1) ensure DELEGS processes certificates sequentially (the Haskell code recurses on init then processes last cert, effectively left-to-right processing), (2) test both the narrow reward-balance-sum invariant (matching the Haskell test) and the broader Val preservation with withdrawal offset, (3) verify that newly registered accounts start with zero balance and deregistered accounts must have zero balance.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 6. 0ad58a47

**Era:** shelley

**Spec says:** stakeRelation is computed as ((stakeCred_b⁻¹ ∪ (addrPtr ∘ ptr)⁻¹) ∘ range(utxo)) ∪ (stakeCred_r⁻¹ ∘ rewards). This combines UTxO-based stake (from both base addresses and pointer addresses) with reward-based stake into a single credential-to-coin relation.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Implementation is missing entirely. Cannot verify correctness of the stakeRelation computation against the spec.

**Implications:** The Python implementation must faithfully implement all four components: (1) inverse of stakeCred_b to map base address credentials to addresses, (2) inverse of addrPtr∘ptr to map pointer address credentials to addresses, (3) composition with range(utxo) to get coin values, and (4) union with stakeCred_r⁻¹∘rewards to include reward balances. Without reference Haskell code, the Python implementation must be validated purely against the spec.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 7. 0d602e28

**Era:** shelley

**Spec says:** rewards = union of all individual pool reward maps from results. The spec uses set union (∪) over the reward maps, meaning if two pools assign rewards to the same address, the behavior depends on whether union or aggregation is used. The spec text says 'union' but the truncated formula likely implies simple map union.

**Haskell does:** The implementation uses `aggregateBy` to combine rewards, which sums (aggregates) rewards for the same credential across different pools. Additionally, the old test code shows version-dependent behavior: pre-Allegra uses Map.unions (left-biased, last-writer-wins) while post-Allegra uses Map.unionsWith (<>) (additive aggregation). The implementation also uses `uncurryᵐ` to flatten (KeyHash, Credent

**Delta:** 1) The spec passes `tot` (sum of stake) to rewardOnePool, but the implementation passes pre-computed `Σ_/total` and `Σ_/active` ratios with clamping. 2) The spec uses simple set union for combining reward maps; the implementation uses `aggregateBy` which sums rewards per credential. 3) The spec's pdata joins poolParams and blocks by key; the implementation uses mapMaybeWithKeyᵐ on poolParams with lookupᵐ? into blocks, which is equivalent but structurally different. 4) The old Haskell test reveal

**Implications:** Python implementation must: (1) pre-compute sigma/total and sigma/active with clamping before calling rewardOnePool; (2) use additive aggregation (sum) when combining reward maps from multiple pools for post-Allegra eras; (3) handle the case where a credential delegates to one pool but also appears as reward address for another pool's operator — rewards should be summed, not overwritten; (4) the `active` variable (sum of stake in the stake map) may differ from `total` parameter, and both are use

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 8. 0e35ba08

**Era:** byron

**Spec says:** dms is a map from VKeyGen to VKey (a standard map/function)

**Haskell does:** dms is implemented as a Bimap VKeyGenesis VKey, which enforces a bijection (both keys and values are unique). This means no two genesis keys can delegate to the same VKey.

**Delta:** The spec defines dms as a plain map (VKeyGen → VKey), which does not inherently enforce injectivity. The Haskell implementation uses Bimap which enforces a bijective (one-to-one) mapping. This means inserting a second genesis key delegating to an already-delegated VKey would silently remove the prior mapping in Bimap, whereas a plain map would allow both entries.

**Implications:** In our Python implementation, if we use a plain dict for dms, we must either (a) additionally enforce the bijection invariant (no two genesis keys map to the same VKey) to match Haskell behavior, or (b) use a custom bidirectional map. Failing to enforce bijectivity could lead to divergent state where multiple genesis keys delegate to the same delegate, which the Haskell implementation prevents.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 9. 170a3341

**Era:** shelley

**Spec says:** DPSEnv (Certificate Sequence Environment) has five fields: slot (Slot), txIx (Ix), pp (PParams), tx (Tx), and acnt (Acnt - accounting state). The slot and txIx are used together with certificate position to construct certificate pointers.

**Haskell does:** CertsEnv has five fields but they are substantially different: certsTx (Tx), certsPParams (PParams), certsCurrentEpoch (EpochNo), certsCurrentCommittee (StrictMaybe (Committee era)), and certsCommitteeProposals (Map (GovPurposeId CommitteePurpose) (GovActionState era)). The 'slot' field is replaced by 'certsCurrentEpoch', 'txIx' is removed entirely, 'acnt' is removed, and two new governance-relate

**Delta:** Major structural divergence: (1) slot→certsCurrentEpoch (Slot replaced by EpochNo, coarser granularity), (2) txIx field is absent (certificate pointers may not be constructed this way in implementation), (3) acnt (accounting state) field is absent, (4) two new governance fields (certsCurrentCommittee, certsCommitteeProposals) are added that don't exist in the spec. This reflects the Conway-era evolution of the ledger where certificate pointer semantics changed and governance was introduced.

**Implications:** Python implementation must decide which version to follow. If targeting Conway era, the Haskell CertsEnv structure is the correct reference. The spec appears to describe the Shelley-era DPSEnv. Key impacts: (1) No need for slot or txIx fields if following Conway implementation, (2) Must include governance committee fields, (3) Accounting state (acnt) is not passed through the certificate environment in Conway, (4) EpochNo is used instead of Slot for time reference.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 10. 1999b48a

**Era:** shelley-ma

**Spec says:** evalMPSScript takes a UTxO parameter which represents only the outputs THIS transaction is spending: spentouts = (txins txb) ◁ utxo. The domain restriction filters the global UTxO to only entries whose keys are in the transaction's input set.

**Haskell does:** No implementing Haskell code was found for evalMPSScript.

**Delta:** Implementation is missing entirely. The critical semantic detail is that the UTxO passed to the script evaluator must be pre-filtered via domain restriction (txins ◁ utxo), not the full global UTxO. Without implementation, there is a risk that a Python implementation might incorrectly pass the full UTxO.

**Implications:** The Python implementation must ensure that before calling evalMPSScript (or its equivalent), the UTxO is domain-restricted to only the inputs being spent by the transaction. Passing the full UTxO would be a semantic error that could allow scripts to observe outputs they shouldn't have access to, potentially affecting security properties of minting policy scripts.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 11. 1d519e72

**Era:** shelley

**Spec says:** poolReward d σ n N̄ f = floor(p̄ · f), where β = n / max(1, N̄), p̄ = β/σ if d < 0.8, otherwise p̄ = 1. The function takes parameters (d, σ, n, N̄, f) and returns a Coin value.

**Haskell does:** The Haskell implementation uses mkApparentPerformance to compute the performance ratio (which encapsulates the d < 0.8 threshold logic), then computes poolReward = posPart(floor(apparentPerformance * fromℕ maxP)). The maxP value is computed via maxPool (which itself involves the pledge mechanism and σ), not passed directly as the 'f' parameter. Additionally, poolReward is wrapped in posPart (clamp

**Delta:** 1) The spec's poolReward is a clean standalone function taking (d, σ, n, N̄, f), but the Haskell code embeds it inside rewardOnePool with maxP (computed from maxPool with pledge checking) substituted for f. 2) The Haskell code applies posPart (max(0, ...)) to the result, which the spec formula doesn't mention explicitly. 3) The apparent performance computation is factored out into mkApparentPerformance (not shown), which presumably implements the d < 0.8 threshold. 4) The spec uses σ for the per

**Implications:** Python implementation must: (1) Use σa (apparent/active stake) rather than σ (relative stake) in the apparent performance calculation — this is a critical distinction. (2) Apply posPart (clamp to non-negative) after floor, since apparentPerformance * maxP could theoretically be negative if intermediate computations go awry. (3) The standalone poolReward function from the spec is used as a sub-computation within a larger reward distribution function. (4) Need to verify what mkApparentPerformance 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 12. 22007a00

**Era:** byron

**Spec says:** Delegation activation no-op rule: A scheduled delegation (s, (vk_s, vk_d)) is silently ignored (state unchanged) if EITHER: (1) vk_d is already in range(dms) — injectivity would be violated, OR (2) vk_s already has a delegation slot s_p in dws where s ≤ s_p — a later or equal delegation was already activated.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Missing implementation. The delegation activation no-op rule has no corresponding Haskell code provided for analysis.

**Implications:** The Python implementation must implement both no-op conditions precisely: (1) check if vk_d is in range of dms and skip if so, (2) check if vk_s maps to s_p in dws where s ≤ s_p and skip if so. The state (dms, dws) must remain completely unchanged in both cases. This is critical for maintaining delegation map injectivity and ensuring slot-ordering of activations.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 13. 27211a01

**Era:** shelley

**Spec says:** TxOut is a triple: Addr × Value × Script (data script). The Extended UTxO model defines a transaction output as exactly three components: an address, a value, and a data script.

**Haskell does:** TxOut is a four-field record with: txOutAddress (Address), txOutValue (Value), txOutDatum (OutputDatum), and txOutReferenceScript (Maybe ScriptHash). The 'Script' from the spec is split into two separate concepts: (1) OutputDatum replaces the data script with a richer type that can be NoOutputDatum, OutputDatumHash, or OutputDatum inline, and (2) an optional reference script (Maybe ScriptHash) is 

**Delta:** Two divergences: (1) The spec's single 'Script' field (data script) is implemented as 'OutputDatum', which is an ADT that can represent the absence of a datum (NoOutputDatum), a datum hash, or an inline datum — the spec implies a Script is always present, but the implementation allows it to be absent. (2) The implementation adds a fourth field 'txOutReferenceScript :: Maybe ScriptHash' which has no counterpart in the original EUTxO spec rule. This reflects the evolution from the original EUTxO p

**Implications:** For the Python implementation: (1) TxOut must be modeled with four fields, not three, to match the actual on-chain representation. (2) The datum field must support three variants (no datum, datum hash, inline datum) rather than being a simple required Script. (3) The reference script field must be Optional. (4) Serialization/deserialization must handle all OutputDatum variants and the optional reference script. (5) When validating against the original spec rule, be aware that 'no datum' is a val

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 14. 27557092

**Era:** alonzo

**Spec says:** The protocol parameter 'costmdls' is a mapping from Language to CostModel, stored in PParams. Each script language version (PlutusV1, PlutusV2, etc.) has its own cost model.

**Haskell does:** No implementing code was found for the costmdls parameter definition itself. However, the Haskell test suite exercises CostModels round-trip serialization with genValidCostModels [PlutusV1, PlutusV2] for the Alonzo era, and notes that Conway era requires a different generator due to drastic serialization changes.

**Delta:** No implementation code found to compare against. The Haskell tests reveal that CostModels serialization varies significantly between eras (Alonzo/Babbage vs Conway), which is an important implementation detail not captured in the spec rule alone. The spec does not mention serialization format differences across eras.

**Implications:** Python implementation must: (1) correctly model the Language -> CostModel mapping, (2) handle era-specific CBOR serialization formats for CostModels, (3) support PlutusV1, PlutusV2, and potentially PlutusV3 cost models, (4) ensure round-trip CBOR serialization fidelity. The era-dependent serialization is a key concern for conformance.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 15. 2a8b18f5

**Era:** shelley

**Spec says:** The Deleg-Mir-Treasury rule operates at the DELEG transition level: when a DCertMir certificate with mirPot=TreasuryMIR is received, it checks the slot is before the stability window, computes combinedT = irTreasury ∪override-right moveRewards(c), checks sum(combinedT) ≤ treasury, and updates i_rwd to (irReserves, combinedT). This is a per-certificate rule within an epoch.

**Haskell does:** The implementing code (mirTransition) operates at the MIR epoch boundary transition (not per-certificate DELEG). It intersects irTreasury with the accounts map (filtering out credentials without reward accounts), combines irwdR and irwdT with unionWith (<>) (additive merge, not override-right), checks totR ≤ availableReserves && totT ≤ availableTreasury (using delta-adjusted values), then distribu

**Delta:** Multiple divergences: (1) The spec rule uses ∪override-right (last write wins for duplicate keys) for combining irTreasury with new MIR entries, but the Haskell epoch-boundary code uses unionWith (<>) (additive combination) - though the Haskell test confirms that post-Alonzo the per-certificate DELEG rule also uses additive semantics. (2) The spec checks sum(combinedT) ≤ treasury, but Haskell checks against availableTreasury = treasury + deltaTreasury (which accounts for SendToOppositeReserveMIR

**Implications:** Python implementation must decide which semantics to follow. For Alonzo+ eras, duplicate MIR entries should be combined additively (not override-right). The available treasury calculation must include deltaTreasury. The intersection with accounts map filtering is important for correctness. The epoch-boundary MIR transfer must handle the failure case by clearing IR rewards regardless.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 16. 2ba83012

**Era:** shelley

**Spec says:** Snapshot is a record with three fields: (1) stake: Stake (Credential → Coin), (2) delegations: Credential → KeyHash_pool, and (3) poolParameters: KeyHash_pool → PoolParam. These are three distinct, independently stored fields.

**Haskell does:** SnapShot has three fields but they differ structurally from the spec: (1) ssActiveStake (ActiveStake) replaces 'stake' — it only includes stake for credentials that have a delegation to a pool, not all registered stake. (2) ssTotalActiveStake (NonZero Coin) is an entirely new field not in the spec — it caches the total active stake sum and enforces it is non-zero (defaulting to 1). (3) ssStakePool

**Delta:** Three major divergences: (a) The 'delegations' field (Credential → KeyHash_pool) is missing entirely from the Haskell SnapShot type — delegation information is presumably folded into ActiveStake or resolved elsewhere. (b) An extra field 'ssTotalActiveStake :: NonZero Coin' is added with a non-zero invariant (defaults to 1 if zero), which does not exist in the spec. (c) 'poolParameters' uses StakePoolSnapShot instead of the full PoolParam type, and 'stake' uses ActiveStake (filtered to only deleg

**Implications:** A Python implementation following the spec literally would have a 'delegations' field that the Haskell code lacks. The Python implementation should decide whether to follow the spec (three fields including delegations) or the Haskell optimization (pre-filtered active stake, cached total, no standalone delegations). The NonZero invariant on total active stake is important for reward calculations to avoid division by zero — this must be handled regardless of which structure is followed. StakePoolS

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 17. 2ca30cec

**Era:** shelley

**Spec says:** pr = { hk ↦ poolDeposit(pp) | hk ∈ retired } — each retiring pool's deposit refund is the poolDeposit protocol parameter value. rewardAcnts = { hk ↦ poolRAcnt(pool) | hk ↦ pool ∈ retired ◁ poolParams } — reward accounts come from poolParams lookup. rewardAcnts' joins pr and rewardAcnts by pool key hash to produce a map from reward account to deposit amount.

**Haskell does:** The Haskell implementation uses spsDeposit (the deposit stored in the StakePoolState for each pool) rather than poolDeposit(pp) from the protocol parameters. It also computes accountRefunds by extracting (spsAccountId, spsDeposit) directly from StakePoolState entries, using Map.fromListWith (<>) to handle the case where multiple pools share the same reward account (deposits are summed). Additional

**Delta:** 1) Deposit refund source: Spec uses poolDeposit(pp) (current protocol parameter) for all retiring pools uniformly; implementation uses spsDeposit (per-pool stored deposit), which may differ from the current protocol parameter if it changed since the pool was registered. 2) Future pool param activation: The implementation merges psFutureStakePoolParams into psStakePools and clears the future map before computing retirements. The spec treats poolParams and fPoolParams as separate maps that are ind

**Implications:** For the Python implementation: (1) Use the per-pool stored deposit amount (not the current protocol parameter) when computing refunds — this matches the Haskell behavior and is the economically correct approach. (2) Implement future pool parameter activation (merge future into current) before processing retirements. (3) When multiple retiring pools share the same reward account, sum their deposits. (4) Consider whether VRF key hash cleanup is needed for the target era.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 18. 2f4b78ac

**Era:** shelley

**Spec says:** For every transaction input tuple (_, _, validator, redeemer) ∈ txins tx, scriptValidate is called with (state, validator, redeemer) and must return true. The spec presents a simple 3-argument validation: scriptValidate state validator redeemer.

**Haskell does:** The Haskell/Agda implementation uses a much more elaborate process: (1) collectPhaseTwoScriptInputs gathers phase-2 script inputs by iterating over scriptsNeeded (not just txins), (2) for each script purpose + script hash, it looks up the script via lookupScriptHash, checks it is a phase-2 script (isInj₂), retrieves the indexed redeemer, constructs a Data list containing datum ++ redeemer ++ valCo

**Delta:** The spec's scriptValidate(state, validator, redeemer) is an abstraction. The implementation: (a) validates all scriptsNeeded (spending, minting, certifying, rewarding, voting, proposing), not just txins; (b) constructs a validation context (valContext) from txInfo as a third Data argument appended after datum and redeemer; (c) requires ExUnits and CostModel parameters for PLC script execution; (d) only validates phase-2 (Plutus) scripts, skipping phase-1 (native) scripts; (e) uses getDatum to re

**Implications:** Python implementation must: (1) use scriptsNeeded to determine all scripts requiring validation, not just iterate txins; (2) construct the full Data list [datum, redeemer, scriptContext] for each Plutus script invocation; (3) pass CostModel and ExUnits to the Plutus evaluator; (4) distinguish phase-1 (native) from phase-2 (Plutus) scripts and only run PLC evaluation on phase-2; (5) handle the nothing/failure cases where script lookup fails, script is not phase-2, or redeemer is missing — these s

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 19. 3325a206

**Era:** shelley

**Spec says:** The New-Proto-Param-Denied rule checks three denial conditions: (1) pp_new = Nothing, (2) reserves + diff < sum of instant rewards, (3) maxTxSize(pp_new) + maxHeaderSize(pp_new) >= maxBlockSize(pp_new). When denied, utxoSt' = updatePpup(utxoSt, pp) cleans up the proposal state using the OLD current params, and the output is (utxoSt', acnt, pp) — accounting and protocol parameters remain unchanged.

**Haskell does:** The provided Haskell function `updatePpup` does not implement the three-way denial condition check (pp_new = Nothing, reserves check, block size constraint). Instead, it unconditionally constructs a NewppState with the given pp, moves future proposals to current (if they have legal protocol version updates), clears future proposals, and computes votedFuturePParams. The denial logic (the three disj

**Delta:** The provided Haskell code is the `updatePpup` helper function, not the full NEWPP transition rule. It handles proposal state management (rotating future proposals to current, filtering by legal protocol version updates, computing voted future params) but does NOT contain: (1) the three denial conditions (pp_new check, reserves+diff check, block size invariant), (2) obligation calculations (oblg_cur, oblg_new, diff), (3) the reserves/instant-rewards comparison. The denial condition logic and the 

**Implications:** For the Python implementation: (1) The updatePpup helper and the NEWPP denial logic must be implemented as separate concerns. (2) The three denial conditions must be checked explicitly in the NEWPP transition function. (3) The updatePpup function's behavior of rotating future proposals to current (with legal protocol version filtering) and computing votedFuturePParams is independent of the denial check. (4) The obligation calculation and reserves comparison are not part of updatePpup and must be

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 20. 34270c33

**Era:** shelley

**Spec says:** The Deleg-Mir-Reserves rule uses union-override-right (∪override-right) to combine irReserves with moveRewards(c), meaning existing entries in irReserves are overwritten by entries from the certificate's reward mapping.

**Haskell does:** The Haskell implementation has era-dependent behavior: prior to Alonzo, repeated fields are overridden (matching the spec's union-override-right semantics), but in the Alonzo era and later, repeated fields are *added* together (addDeltaCoin) rather than overridden. This is controlled by the hardforkAlonzoAllowMIRTransfer flag based on protocol version.

**Delta:** The spec describes a single union-override-right operation, but the implementation bifurcates behavior by era: pre-Alonzo uses override semantics (matching spec), while Alonzo+ uses additive semantics for overlapping keys. The spec as written does not capture this Alonzo-era change.

**Implications:** Python implementation must handle both semantics: (1) pre-Alonzo: union-override-right where certificate values replace existing irReserves entries, and (2) Alonzo+: additive combination where overlapping DeltaCoin values are summed. The protocol version / era must be checked to determine which path to take. The sum constraint (combinedR sum ≤ reserves) applies in both cases but over differently-computed combinedR values.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 21. 35d9a691

**Era:** shelley

**Spec says:** PoolParam is a tuple: ℙ(KeyHash) × Coin × UnitInterval × Coin × AddrRWD × KeyHash_vrf × Seq(URL) × PoolMD?. The spec does NOT include a pool operator key hash as a separate field — the first component is the set of pool owners.

**Haskell does:** The Haskell PoolParams pattern includes an additional first field `KeyHash StakePool` (the pool operator/ID), which is not part of the spec's PoolParam type. The Haskell type has 9 fields: pool operator key hash, VRF key hash, cost (Coin), pledge (Coin), margin (UnitInterval), reward account (AccountAddress), owners (Set KeyHash Staking), relays (StrictSeq StakePoolRelay), and optional metadata (S

**Delta:** The Haskell implementation adds a pool operator KeyHash (StakePool role) as the first field, which is absent from the spec's PoolParam definition. The spec has 8 components while Haskell has 9. Additionally, the field ordering differs significantly: spec orders (owners, cost, margin, pledge, rewardAcct, vrfHash, relays, metadata) while Haskell orders (operatorHash, vrfHash, cost, pledge, margin, rewardAcct, owners, relays, metadata). Also, relays in the spec are Seq(URL) but Haskell uses StrictS

**Implications:** Python implementation must decide whether to include the pool operator key hash as a separate field (following Haskell) or omit it (following spec). Field ordering in constructors/serialization must be carefully matched to whichever convention is chosen. The relay type needs to accommodate StakePoolRelay (which can be IP addresses, DNS names, etc.) rather than just URLs. Serialization and deserialization code must account for all 9 Haskell fields if interoperability with the chain is needed.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 22. 366894ee

**Era:** shelley

**Spec says:** stakeDistr returns a triple (stake, delegations, poolParams) where stake = (dom activeDelegs) ◁ (aggregate₊ stakeRelation), and the full delegations and poolParams maps are included in the snapshot. stakeRelation includes pointer address resolution via (addrPtr ∘ ptr)⁻¹, and activeDelegs = (dom rewards) ◁ delegations ▷ (dom poolParams).

**Haskell does:** The Agda implementation computes stakeRelation differently: it maps over (dom rewards) computing cbalance of UTxO filtered by getStakeCred, then unions with |rewards|. It returns only (aggregate₊ stakeRelation, stakeDelegs) — a pair, not a triple. The Haskell conformance test (cardano-ledger) uses aggregateUtxoCoinByCredential which resolves pointer addresses via ptrs', and filters activeDelegs by

**Delta:** 1) The Agda implementation omits pointer address resolution — it only uses getStakeCred (which handles base addresses) but does not resolve pointer addresses through the ptrs map. The spec explicitly includes (addrPtr ∘ ptr)⁻¹ for pointer addresses. 2) The Agda implementation returns a pair (stake, stakeDelegs) rather than the spec's triple (stake, delegations, poolParams) — poolParams is missing from the return value. 3) The Agda implementation does not apply the activeDelegs domain restriction

**Implications:** The Python implementation must: (1) resolve pointer addresses when computing stakeRelation, (2) return the full triple including poolParams, (3) apply the activeDelegs domain restriction to filter the aggregated stake to only registered credentials delegated to active pools. The Agda code should NOT be used as the reference — the spec and the Haskell conformance test should be followed instead.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 23. 38b57f54

**Era:** shelley

**Spec says:** The POOLREAP rule computes deposit refunds using pr = { hk ↦ poolDeposit(pp) | hk ∈ retired }, meaning every retiring pool gets a refund equal to the protocol parameter poolDeposit, regardless of what deposit was actually paid when the pool was registered.

**Haskell does:** The Haskell implementation uses the actual deposit stored in the StakePoolState (spsDeposit sps) for each retiring pool, not the current protocol parameter poolDeposit(pp). The accountRefunds map is built from spsDeposit of the retiring pool states. Additionally, the Haskell code performs two extra operations not in the spec: (1) it activates future stake pool parameters before processing retireme

**Delta:** Two divergences: (1) Deposit refund amount comes from stored per-pool deposit (spsDeposit) rather than the current protocol parameter poolDeposit(pp). This means if the protocol parameter changed since registration, the refund reflects the original deposit, not the current one. (2) Future pool parameter activation and VRF key hash cleanup are implementation details not described in the spec rule.

**Implications:** Python implementation must use the stored per-pool deposit amount (not the current protocol parameter) when computing refunds, matching the Haskell behavior. It must also handle future pool parameter activation before retirement processing. Tests should verify refund amounts use stored deposits, not current pp.poolDeposit.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 24. 3d86daa9

**Era:** shelley

**Spec says:** The CHAIN transition is defined as a relation over (ChainState × Block × ChainState) with no environment. The signal is a Block and the state is a ChainState.

**Haskell does:** No implementing Haskell code was found for the CHAIN transition rule.

**Delta:** The CHAIN rule has no corresponding Haskell implementation identified. This means we cannot verify whether the implementation matches the spec's type signature (no environment, ChainState state, Block signal) or confirm the transition's structural correctness.

**Implications:** For the Python implementation, we must rely solely on the formal spec to define the CHAIN transition. We need to ensure: (1) the transition function takes only (ChainState, Block) with no environment parameter, (2) ChainState and Block types are correctly defined, and (3) the transition composes correctly with sub-rules (e.g., BBODY, TICK). Without reference Haskell code, we cannot cross-check edge cases or error handling behavior.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 25. 3f26b881

**Era:** shelley

**Spec says:** consumed(pp, utxo, t) = Val(txins(t) ◁ utxo) + w + k, where w = wbalance(txwdrls(t)) and k = keyRefunds(pp, stkCreds, t). The spec defines consumed as the sum of: (1) the value of inputs restricted from the UTxO, (2) the withdrawal balance, and (3) key refunds. There is no mention of a 'mint' component in the consumed side of the preservation equation.

**Haskell does:** consumed pp st txb = balance (st.utxo | txb.txins) + txb.mint + inject (depositRefunds pp st txb) + inject (getCoin (txb.txwdrls)). The Haskell implementation adds txb.mint (the minting/burning field from the transaction body) as an additional term in the consumed calculation.

**Delta:** The Haskell implementation includes a 'mint' (multi-asset minting/burning) term that is not present in the spec rule as stated. This reflects the Mary-era (multi-asset) extension to the Shelley-era spec rule. The original Shelley spec had no minting, so the spec rule provided is from the Shelley era, while the Haskell code implements the post-Mary generalization that accounts for minted/burned tokens on the consumed side.

**Implications:** The Python implementation must include the mint field from the transaction body in the consumed calculation. If we only implement the Shelley-era equation without the mint term, multi-asset transactions will fail the preservation-of-value check. The mint value can be negative (burning), so it must be handled as a signed multi-asset value addition.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 26. 3fbf4dca

**Era:** shelley

**Spec says:** The POOL rule has exactly four predicate failures: StakePoolCostTooLow, StakePoolNotRegisteredOnKey, StakePoolRetirementWrongEpoch, and WrongCertificateType.

**Haskell does:** The Haskell implementation includes additional predicate failures beyond the four specified: WrongNetworkPOOL (network ID mismatch on pool account address, post-Alonzo), PoolMedataHashTooBig (metadata hash exceeds expected size, post-restrictPoolMetadataHash softfork), and VRFKeyHashAlreadyRegistered (duplicate VRF key hash, post-Conway hardfork). Additionally, StakePoolNotRegisteredOnKey is not e

**Delta:** The implementation has at least 3 additional failure modes (WrongNetworkPOOL, PoolMedataHashTooBig, VRFKeyHashAlreadyRegistered) that are era-gated via hardfork predicates and not mentioned in the base spec. The spec's StakePoolNotRegisteredOnKey and StakePoolRetirementWrongEpoch checks are presumably in the RetirePool branch which is not shown. The spec describes a strict inequality for retirement epoch (cepoch < e <= cepoch + emax) which the test confirms.

**Implications:** Python implementation must account for era-dependent checks beyond the four base failures. For Conway era, VRF key uniqueness must be enforced. For Alonzo+, network ID validation on pool reward account is required. Metadata hash size validation is also needed. The retirement epoch range check uses strict lower bound (cepoch < e) and inclusive upper bound (e <= cepoch + emax).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 27. 405b324e

**Era:** shelley

**Spec says:** RewardUpdate has exactly four fields: Δt (Coin), Δr (Coin), rs (AddrRWD ↦ Coin mapping reward addresses to Coin), and Δf (Coin). The rs field maps full reward addresses (AddrRWD) to Coin values.

**Haskell does:** The Haskell RewardUpdate has five fields, not four: deltaT (DeltaCoin), deltaR (DeltaCoin), rs (Map (Credential Staking) (Set Reward)) — which maps staking credentials to sets of Reward rather than AddrRWD to Coin, deltaF (DeltaCoin), and an additional nonMyopic (NonMyopic) field not in the spec. Additionally, all Coin fields use DeltaCoin (which can be negative) instead of Coin.

**Delta:** Three divergences: (1) An extra field 'nonMyopic' exists in the implementation that is absent from the spec. (2) The 'rs' field maps Credential Staking to Set Reward instead of AddrRWD to Coin — the key type is narrower (just the credential, not the full reward address including network) and the value type is richer (a set of Reward structs rather than a single Coin). (3) Coin fields are typed as DeltaCoin, which supports negative values, whereas the spec uses Coin (which is typically non-negati

**Implications:** For the Python implementation: (1) We need to decide whether to include a nonMyopic field or omit it to stay closer to the spec — if interoperability with on-chain data is needed, we must include it. (2) The rs field should use Credential (staking) as the key and a set of Reward objects as the value, not AddrRWD to Coin, to match the actual Haskell implementation. (3) DeltaCoin (signed integer) should be used for deltaT, deltaR, and deltaF rather than unsigned Coin. This is important because res

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 28. 41a544c6

**Era:** shelley-ma

**Spec says:** evalMPSScript SignedByPIDToken pid slot vhks txb spentouts checks that there exists a token name t in range(pid ◁ (ubalance spentouts)) such that t ∈ vhks. That is, filter the combined balance of spent outputs by the policy ID, extract the token names, and verify at least one token name appears in the set of verified (signing) key hashes.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** The implementation is entirely missing. The spec requires: (1) computing ubalance of spentouts (union balance of UTxO entries), (2) domain-restricting the multi-asset map by the given policy ID (pid), (3) extracting token names from the range, (4) checking existential membership of at least one token name in vhks. None of this logic has been located in the codebase.

**Implications:** The Python implementation must faithfully implement this existential check. Key subtlety: token names are being compared against verified key hashes (VKeyHash values), meaning the token name bytes are interpreted as / compared to key hash bytes. The Python code must ensure type compatibility between token names and key hashes. Additionally, ubalance must correctly aggregate multi-asset values across all spent outputs before filtering.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 29. 43b32888

**Era:** byron

**Spec says:** The UPIREG rule delegates to the UPREG transition unconditionally — it always attempts both protocol update registration and software update registration via the UPREG sub-rule. The only precondition is that UPREG succeeds. There is no concept of 'null update proposals' or exemptions for specific networks/slots.

**Haskell does:** The Haskell implementation (1) adds a NullUpdateProposal check that rejects proposals where neither protocol version nor software version changed, unless a specific staging network exemption applies (protocolMagic 633343913 at slots 969188 or 1915231). (2) It conditionally registers protocol updates only if protocolVersionChanged, and software updates only if softwareVersionChanged, rather than al

**Delta:** Three divergences: (a) NullUpdateProposal rejection is not in the spec — the spec allows any proposal that passes UPREG. (b) Network-specific null-update exemptions (staging network magic + specific slots) are entirely extra-spec. (c) Conditional registration (skip protocol update if version unchanged, skip software update if version unchanged) differs from spec which always runs UPREG as a single atomic transition on both components.

**Implications:** Python implementation must decide whether to follow the spec literally (always delegate to UPREG, no null-update check) or match Haskell behavior (add null-update rejection + conditional registration). For mainnet conformance, the null-update check is effectively enforced. The staging network exemptions are only needed for that specific test network. The conditional skip of sub-registrations means edge cases where a proposal has unchanged versions but would still be processed differently under U

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 30. 474b1d3a

**Era:** shelley

**Spec says:** Rule Reward-Too-Early: If ru is Nothing AND slot s <= firstSlot(epoch(s)) + StabilityWindow, then the state remains unchanged (ru stays Nothing). The rule has two preconditions that must both hold: (1) ru = Nothing, and (2) s <= firstSlot(epoch(s)) + StabilityWindow.

**Haskell does:** The Haskell code computes `determineRewardTiming s slot slotForce` where `slot = epochInfoFirst(e) + Duration(randomnessStabilisationWindow)` and `slotForce = slot + Duration(randomnessStabilisationWindow)`. When the result is `RewardsTooEarly`, it unconditionally returns `SNothing` regardless of the current value of `ru`. The spec says the rule only applies when `ru = Nothing`, but the Haskell co

**Delta:** 1) The spec's Reward-Too-Early rule requires ru = Nothing as a precondition, but the Haskell implementation unconditionally returns SNothing when timing is RewardsTooEarly, discarding any existing reward update state. This means if somehow ru were SJust in the too-early window, the spec has no matching rule (would get stuck), while Haskell silently resets to SNothing. 2) The Haskell code introduces a third timing category (RewardsTooLate with a force-completion window) that doesn't appear in the

**Implications:** For Python implementation: (1) The RewardsTooEarly branch should return SNothing unconditionally (matching Haskell), not check ru first. (2) Must implement the three-way timing logic (RewardsTooEarly/RewardsJustRight/RewardsTooLate) rather than the spec's simpler two-rule system. (3) Need to use `randomnessStabilisationWindow` for the threshold computation. (4) The force-completion (RewardsTooLate) logic must be implemented even though it's not in the spec.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 31. 49ad3991

**Era:** shelley

**Spec says:** MIR-Skip compares totR > reserves and totT > treasury directly against the raw reserve and treasury pots. The filtering uses (dom(rewards)) ◁ irReserves, meaning it filters by credential keys present in the rewards map.

**Haskell does:** The Haskell implementation computes availableReserves = reserves + deltaReserves(dsIRewards) and availableTreasury = treasury + deltaTreasury(dsIRewards), then checks totR <= availableReserves && totT <= availableTreasury. This means the skip condition uses adjusted pot values (incorporating delta fields from InstantaneousRewards) rather than raw pot values. The delta fields represent pending MIR 

**Delta:** The spec's skip condition is totR > reserves OR totT > treasury (raw pots), but the implementation uses totR > availableReserves OR totT > availableTreasury where availableReserves/Treasury incorporate deltaReserves/deltaTreasury adjustments. This is a post-spec extension for Alonzo-era MIR pot transfers. The condition logic is also inverted: spec checks totR > reserves || totT > treasury for skip, code checks !(totR <= availableReserves && totT <= availableTreasury) for skip, which is logically

**Implications:** Python implementation must account for deltaReserves and deltaTreasury fields in InstantaneousRewards when computing available pot sizes. If implementing only the Shelley-era spec without deltas, the skip condition will be incorrect for cases where delta fields are non-zero. The InstantaneousRewards data structure must include deltaReserves and deltaTreasury fields beyond what the original Shelley spec describes.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 32. 4b15b0e9

**Era:** shelley

**Spec says:** The DELEG rule has exactly ten predicate failures: (1) StakeKeyAlreadyRegistered, (2) StakeKeyNotRegistered, (3) StakeKeyNonZeroAccountBalance, (4) StakeDelegationImpossible, (5) WrongCertificateType, (6) GenesisKeyNotInMapping, (7) DuplicateGenesisDelegate, (8) InsufficientForInstantaneousRewards, (9) MIRCertificateTooLateinEpoch, (10) DuplicateGenesisVRF.

**Haskell does:** The Haskell implementation defines 16 predicate failure constructors, not 10. In addition to the spec's 10, it adds: (11) MIRTransferNotCurrentlyAllowed, (12) MIRNegativesNotCurrentlyAllowed, (13) InsufficientForTransferDELEG, (14) MIRProducesNegativeUpdate, (15) MIRNegativeTransfer, (16) DelegateeNotRegisteredDELEG. Also, the spec's StakeDelegationImpossible refers to 'non-existing stake pool key

**Delta:** Six additional predicate failures beyond the spec's ten. The semantic split is also different: the spec's StakeDelegationImpossible (pool not registered) maps to DelegateeNotRegisteredDELEG in code, while the code's StakeDelegationImpossibleDELEG checks that the delegator credential is registered — a condition not explicitly listed in the spec's ten failures. The extra MIR-related failures (MIRTransferNotCurrentlyAllowed, MIRNegativesNotCurrentlyAllowed, InsufficientForTransferDELEG, MIRProduces

**Implications:** Python implementation must handle all 16 failure cases, not just the 10 from the spec. StakeDelegationImpossible must check the delegator credential is registered (not the pool), and DelegateeNotRegisteredDELEG must check the target pool is registered. MIR transfer validation requires five distinct failure types beyond what the spec enumerates. Mapping spec names to code names requires care.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 33. 4d9d4cb2

**Era:** shelley

**Spec says:** The TICK rule decomposes the original nes to extract b_prev and es, then applies the RUPD (reward update) transition with environment (b_prev, es) and state ru' (from nes') to produce ru''. The final nes'' includes ru'' (the updated reward update) while keeping all other fields from nes'. The NEWEPOCH environment includes (slot, gkeys).

**Haskell does:** The Haskell implementation (1) calls solidifyNextEpochPParams to get curEpochNo and a potentially modified nes, (2) passes an empty environment () to NEWEPOCH instead of (slot, gkeys), (3) does NOT perform the RUPD transition at all — there is no reward update computation in the TICK rule itself, and (4) does not decompose the original nes to extract b_prev/es for RUPD.

**Delta:** Two major divergences: (A) The RUPD transition is completely absent from the Haskell TICK implementation. The reward update calculation appears to have been moved elsewhere (likely into the Praos consensus layer or is computed incrementally). (B) The NEWEPOCH environment is () rather than (slot, gkeys) as specified. Additionally, solidifyNextEpochPParams is called as a preprocessing step not mentioned in the spec. The gkeys parameter from the spec is absent entirely.

**Implications:** For a Python implementation: (1) If following the spec literally, we would implement RUPD within TICK, but the Haskell implementation has moved reward update computation out of TICK. We need to decide whether to follow the spec or the Haskell implementation. (2) The NEWEPOCH environment difference means we need to understand how the Haskell NEWEPOCH rule receives slot/gkeys info (likely through the era's environment or global state). (3) solidifyNextEpochPParams is an implementation detail for n

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 34. 4ec7bbf8

**Era:** shelley

**Spec says:** The updatePpup function decomposes UTxOState as (utxo, deposits, fees, (pup, fpup)). The canFollow predicate checks all ps in range(pup) — i.e., range of the CURRENT proposals (pup) — to verify protocol version constraints. If canFollow holds, the result promotes fpup (future proposals) to current: (utxo, deposits, fees, (fpup, ∅)). If not, it clears both: (utxo, deposits, fees, (∅, ∅)).

**Haskell does:** The Haskell implementation checks `allᵇ (isViableUpdate pparams) (range fpup)` — i.e., it checks the viability constraint against range(fpup), the FUTURE proposals, not range(pup) the current proposals. The conditional logic for promotion/clearing is the same (promote fpup to pup if check passes, clear both otherwise).

**Delta:** The spec checks canFollow against range(pup) (current proposals), but the Haskell code checks isViableUpdate against range(fpup) (future proposals). This is a significant divergence in which set of proposals is validated. Either the spec or the implementation has a bug, or the naming conventions differ from what the spec intends.

**Implications:** The Python implementation must decide which behavior to follow. If following the spec literally, we check range(pup) (current proposals). If following the Haskell implementation, we check range(fpup) (future proposals). This could lead to different promotion/clearing behavior when pup and fpup contain different protocol version mappings. This needs clarification — the Haskell implementation likely reflects the intended semantics since it's the reference implementation, and the spec may have a na

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 35. 50b3207b

**Era:** shelley

**Spec says:** The DELPL transition rule Delpl-Pool delegates pool certificates to the POOL sub-transition, passing (slot, pp) as environment, updating only pstate while leaving dstate unchanged. Pool certificates and delegation certificates are disjoint, so exactly one of Delpl-Deleg or Delpl-Pool fires for any given certificate.

**Haskell does:** No implementing Haskell code was provided for direct comparison. The existing test exercises the Delpl-Deleg path (DelegFailure/DelegateeNotRegisteredDELEG) rather than the Delpl-Pool path directly, though it does confirm the DELPL dispatch mechanism exists.

**Delta:** No direct implementation code available to compare against spec. The existing Haskell test covers the delegation failure path through DELPL but does not exercise the Delpl-Pool rule specifically. There is no test for the pool certificate path through DELPL.

**Implications:** Python implementation must ensure: (1) DELPL correctly dispatches pool certificates to the POOL sub-transition, (2) only (slot, pp) are passed as environment to POOL (not ptr or acnt), (3) dstate is preserved unchanged when a pool certificate is processed, (4) pool and delegation certificates are mutually exclusive in dispatch. The existing Haskell test golden vector (DelegateeNotRegisteredDELEG with mkKeyHash 1) should be replicated for the delegation failure path.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 36. 53e35178

**Era:** shelley

**Spec says:** Snapshot is a record with three fields: (1) stake: Stake (Credential → Coin), (2) delegations: Credential → KeyHash_pool, and (3) poolParameters: KeyHash_pool → PoolParam. These are three independent fields capturing stake distribution, delegation map, and pool parameters separately.

**Haskell does:** SnapShot has three fields: (1) ssActiveStake: ActiveStake (which bundles stake AND delegations together, containing only stake for credentials that have a delegation), (2) ssTotalActiveStake: NonZero Coin (a precomputed total that does NOT exist in the spec), (3) ssStakePoolsSnapShot: VMap KeyHash StakePool StakePoolSnapShot (uses StakePoolSnapShot instead of PoolParam, which is a reduced version 

**Delta:** Three significant divergences: (1) The spec has a separate 'delegations' field; Haskell folds delegation info into ActiveStake and the pool snapshot. (2) Haskell adds ssTotalActiveStake (NonZero Coin, defaulting to 1 if zero) which is not in the spec — this is a performance optimization to precompute the denominator for reward calculations. (3) The spec's 'stake' includes ALL registered staking credentials, but Haskell's ssActiveStake is filtered to only those with active delegations. (4) StakeP

**Implications:** For the Python implementation: (1) We must decide whether to follow the spec's clean three-field structure or the Haskell optimization. Following the spec is simpler and more correct; the Haskell restructuring is an optimization. (2) If following the spec, we need Stake, delegations, and poolParameters as separate fields. (3) If we need interop/conformance with Haskell serialization, we need to handle the ActiveStake bundling and NonZero Coin field. (4) The NonZero Coin invariant (defaulting to 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 37. 562d5305

**Era:** shelley

**Spec says:** Two special certificate types exist: (1) Genesis key delegation certificates maintaining a mapping from genesis keys to cold keys in the delegation state, and (2) MIR certificates that transfer rewards from reserves or treasury to reward addresses, requiring Quorum-many genesis key delegate signatures.

**Haskell does:** The provided Haskell code only implements the Key typeclass for GenesisDelegateKey, covering key generation, verification key derivation, and hashing. It does not implement the genesis key delegation certificate construction, the MIR certificate construction, the quorum signature verification, or the delegation state mapping. These are likely implemented elsewhere (e.g., in cardano-ledger-spec for

**Delta:** The Haskell code shown is only the cryptographic key infrastructure for genesis delegate keys. The spec's core requirements — genesis delegation certificates, MIR certificates, quorum checking, and delegation state updates — are not present in this code snippet. The code is a necessary but insufficient piece of the full spec rule implementation.

**Implications:** For Python implementation: (1) We need to implement GenesisDelegateKey with the same key derivation and hashing behavior shown here. (2) We must also implement the certificate types (GenesisDelegatetion and MIR) and the quorum verification logic separately, which are not covered by this code snippet. (3) The delegation state must maintain a genesis-key-to-cold-key mapping. (4) MIR certificate transactions must validate that Quorum-many genesis delegate signatures are present.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 38. 58cd2079

**Era:** shelley

**Spec says:** η = blocksMade / (slotsPerEpoch · ActiveSlotCoeff). The ratio η is simply total blocks made divided by the product of slots per epoch and the active slot coefficient.

**Haskell does:** The Haskell implementation introduces a decentralization parameter 'd' into the η calculation. When d >= 0.8, η is hardcoded to 1 (meaning full monetary expansion regardless of blocks made). When d < 0.8, expectedBlocks = floor((1 - d) · ActiveSlotCoeff · slotsPerEpoch), and η = blocksMade / expectedBlocks. This means the expected blocks are scaled down by (1-d) to account for the fact that in a p

**Delta:** The spec formula η = blocksMade / (slotsPerEpoch · ActiveSlotCoeff) does not mention the decentralization parameter 'd'. The implementation adjusts expectedBlocks by (1-d) and has a special case where d >= 0.8 forces η = 1. This means: (1) when d >= 0.8, deltaR1 always equals floor(ρ · reserves) regardless of actual block production; (2) when d < 0.8, the denominator is reduced by factor (1-d), making η larger for the same number of blocks produced.

**Implications:** The Python implementation must include the decentralization parameter 'd' (ppDG from previous epoch params) in the η calculation. It must implement the d >= 0.8 threshold check that forces η = 1, and the (1-d) scaling of expected blocks. If we follow only the spec formula without the d adjustment, we will compute incorrect deltaR1 values for any era where d != 0 (i.e., before full decentralization). Additionally, expectedBlocks uses floor() and the division blocksMade / expectedBlocks is an exac

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 39. 5c71c2db

**Era:** shelley

**Spec says:** For any CHAIN transition e ⊢ s →(CHAIN, b) s', the total value Val(s) = Val(s'), where Val is the sum of Val(utxo) + Val(deposits) + Val(fees) + Val(reserves) + Val(treasury) + Val(rewards). No CHAIN transition may create or destroy Lovelace.

**Haskell does:** The implementation has two layers: (1) validateValueNotConservedUTxO checks consumed == produced at the UTxO transaction level using pp/certState/utxo/txBody, and (2) the property test preserveBalance checks a per-ledger-transaction invariant: sumCoinUTxO(u') + fees + totalDeposits == sumCoinUTxO(u) + totalRefunds + withdrawals, but explicitly skips transactions with failed scripts (failedScripts 

**Delta:** The Haskell property test exempts transactions with failed scripts from the balance check (failedScripts .||. ediffEq created consumed_). Failed script transactions still consume collateral and produce change, so the accounting differs. The spec theorem is stated unconditionally. Additionally, the Haskell test checks a per-transaction ledger-level invariant (UTxO + fees + deposits), not the full CHAIN-level Val which includes reserves, treasury, and rewards.

**Implications:** Python implementation must: (1) ensure the value conservation validation (consumed == produced) is correct for the UTxO rule, (2) understand that failed-script transactions have different accounting (collateral is consumed, no regular inputs/outputs apply), (3) for full spec compliance, verify the broader CHAIN-level invariant including reserves/treasury/rewards, not just the UTxO-level balance.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 40. 5e3f65e9

**Era:** alonzo

**Spec says:** The BBODY rule requires five checks: (1) body size matches header declaration, (2) body hash matches header declaration, (3) sum of execution units across all txs ≤ maxBlockExUnits from protocol parameters, (4) LEDGERS transition processes all txs successfully, and (5) block count is incremented via incrBlocks recording overlay slot status for the issuer.

**Haskell does:** No implementing Haskell code was provided for analysis.

**Delta:** Cannot verify implementation correctness without code. Key areas of concern: how bBodySize is computed (serialized size vs logical size), how txexunits are summed (per-phase or total), how overlay slot membership is determined, and whether ExUnits comparison uses component-wise ≤ (both memory and steps).

**Implications:** Python implementation must ensure all five preconditions are checked in order, that ExUnits uses component-wise comparison (both memory AND steps must be ≤ maxBlockExUnits), and that incrBlocks correctly tracks overlay slot membership for the block issuer.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 41. 61891fd5

**Era:** shelley

**Spec says:** MIR-Skip uses simple reserves and treasury values directly for the insufficiency check: totR > reserves OR totT > treasury. The filtering is done via (dom(rewards)) ◁ irReserves, domain-restricting the irReserves map to keys present in the rewards map.

**Haskell does:** The Haskell implementation introduces deltaReserves and deltaTreasury adjustments: availableReserves = reserves + deltaReserves(dsIRewards), availableTreasury = treasury + deltaTreasury(dsIRewards). The insufficiency check is NOT (totR > reserves || totT > treasury) but rather negation of (totR <= availableReserves && totT <= availableTreasury). Also, the filtering uses Map.intersection with accou

**Delta:** 1) The spec checks totR > reserves and totT > treasury against raw pot values, while the Haskell code checks against availableReserves/availableTreasury which include delta adjustments (deltaReserves, deltaTreasury from InstantaneousRewards). This means the Haskell implementation can skip MIR distribution in cases the spec wouldn't (or vice versa) when deltas are non-zero. 2) The data model difference: spec uses 'rewards' map directly, Haskell uses 'accountsMap' from an accounts lens — these sho

**Implications:** Python implementation must use the delta-adjusted available reserves/treasury for the insufficiency check (matching Haskell), not the raw pot values (matching spec literally). When deltaReserves or deltaTreasury are non-zero, using raw values would produce different skip/proceed decisions. The InstantaneousRewards type must carry deltaReserves and deltaTreasury fields.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 42. 61e8e36a

**Era:** byron

**Spec says:** Delegation scheduling rule requires: (1) valid signature verification with vk_s in allowed delegators K, (2) (e_d, vk_s) not already in eks, (3) 0 ≤ e_d - e ≤ 1, (4) d = 2*k and no existing (s+d, (vk_s, _)) in sds. On success, append (s+d, (vk_s, vk_d)) to sds and add (e_d, vk_s) to eks.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify implementation correctness since no Haskell code was located. The Python implementation must be built purely from the spec.

**Implications:** The Python implementation must faithfully encode all five preconditions and both state updates. Without reference Haskell code to compare, extra care must be taken to match the spec exactly — particularly: (a) sds is a sequence (order matters, append semantics), (b) eks is a set (union semantics), (c) the slot offset d = 2*k is applied consistently, (d) the epoch check is inclusive on both bounds.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 43. 63cf8357

**Era:** shelley

**Spec says:** No-Double-Spend: |txins tx| = |outRefs tx|. The number of transaction inputs (as a list) must equal the number of distinct output references (as a set). This explicitly checks that no two inputs refer to the same UTxO output reference.

**Haskell does:** The function spentOutputsTx constructs a Set from the list of output references via `Set.fromList . map refTI . inputsTX`. By converting to a Set, duplicate output references are silently deduplicated. There is no explicit check that |list| == |set|; the deduplication happens implicitly. If two inputs reference the same UTxO, the Set will simply have fewer elements than the input list, but no vali

**Delta:** The spec requires an explicit validation that the count of inputs equals the count of distinct output references (failing if duplicates exist). The Haskell implementation builds a Set (which inherently deduplicates) but does not appear to perform the cardinality comparison |inputs| == |Set.size(outRefs)| at this code site. The validation may happen elsewhere (e.g., in a UTXOW or UTXO rule predicate check), or it may rely on the fact that the ledger rules call this function and separately validat

**Implications:** In the Python implementation, we must NOT silently deduplicate inputs into a set. We need an explicit validation step that compares len(tx.inputs) == len(set(input.output_ref for input in tx.inputs)) and raises a validation error if they differ. If we only convert to a set without checking, we would silently accept double-spend transactions.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 44. 69ae53f8

**Era:** shelley

**Spec says:** Only-Evolve rule: When slot s >= firstSlot(epoch(s) + 1) - RandomnessStabilisationWindow, only the evolving nonce η_v is updated to η_v ⊕ η, while the candidate nonce η_c remains unchanged (frozen).

**Haskell does:** No implementing Haskell code was found for analysis.

**Delta:** Cannot verify implementation correctness since no Haskell code is available. The Python implementation must be built purely from the spec.

**Implications:** The Python implementation must correctly: (1) compute the stability window boundary using firstSlot(epoch(s) + 1) - RandomnessStabilisationWindow, (2) freeze η_c when s >= that boundary while still evolving η_v, (3) use the correct seed operation (⊕) for combining nonces. Any mistake in the boundary calculation or nonce update logic would lead to incorrect leader schedules in subsequent epochs.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 45. 723a4909

**Era:** shelley

**Spec says:** hash : Script → Addr computes a script address from a Script by hashing a validator script to produce an address.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify the implementation details (hash algorithm, serialization format before hashing, address construction from hash digest) since no Haskell code is available. The spec is silent on whether the hash is Blake2b-224 (as used elsewhere in Cardano for credentials), how the Script is serialized/tagged before hashing, and whether the resulting Addr includes network discrimination or staking credentials.

**Implications:** The Python implementation must ensure: (1) the correct hash algorithm (Blake2b-224) is used, (2) the script is serialized with the correct CBOR wrapping and language tag before hashing (Plutus scripts are double-CBOR-wrapped), (3) the resulting Addr uses a ScriptCredential, and (4) the address format matches Cardano conventions. Without reference Haskell code, these details must be validated against on-chain data or the cardano-ledger source.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 46. 73ebb442

**Era:** shelley

**Spec says:** overlaySchedule produces a schedule osched with 4 invariants: (1) range(osched) ⊆ gkeys, (2) |osched| = ⌊d(pp) · SlotsPerEpoch⌋, (3) number of non-Nothing entries = ⌊ActiveSlotCoeff · d(pp) · SlotsPerEpoch⌋, (4) all slots in dom(osched) belong to epoch e.

**Haskell does:** No implementing Haskell code was found for overlaySchedule.

**Delta:** Missing implementation — cannot verify any of the four invariants are enforced in code.

**Implications:** The Python implementation must be built purely from the spec. All four invariants must be explicitly tested since there is no reference implementation to compare against. Special attention needed for edge cases: d=0 (fully decentralized, no overlay slots), d=1 (fully federated), and boundary values of ActiveSlotCoeff.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 47. 748ea783

**Era:** byron

**Spec says:** In general, deserialization composed with serialization does not equal the identity function: ⟦·⟧⁻¹_A ∘ ⟦·⟧_A ≠ id_A. This is a fundamental property of CBOR serialization in Cardano — round-tripping through serialize then deserialize may not preserve the original value due to non-canonical encodings, map ordering, tag variations, etc.

**Haskell does:** No implementing code was found for this specific rule. However, the Cardano codebase handles this via 'Annotated' types and the MemoBytes pattern which preserves original bytes to avoid round-trip issues.

**Delta:** No direct implementation of this axiom was located. The spec states this as a motivating property (non-invertibility) that justifies the design of distributive deserialization. The Haskell codebase addresses this implicitly through patterns like MemoBytes/Annotator that retain original serialized bytes.

**Implications:** The Python implementation must be aware that CBOR round-tripping (serialize → deserialize → re-serialize) may produce different bytes. This means: (1) transaction ID computation must use original bytes, not re-serialized bytes; (2) any hash-based verification must preserve original serialized form; (3) the implementation should consider a MemoBytes-like pattern to store original bytes alongside decoded values.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 48. 7540a062

**Era:** shelley

**Spec says:** The MIR transition is defined as a relation over EpochState with no environment and no signal: ⊢ _ →(mir) _ ⊆ P(EpochState × EpochState). This is a pure state-to-state transition.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify implementation correctness since no Haskell code was provided. The spec defines a clear type signature (no environment, no signal, EpochState → EpochState) but without code we cannot confirm the transition logic, guard conditions, or how instantaneous rewards are actually processed.

**Implications:** The Python implementation must ensure: (1) MIR transition takes only EpochState as input (no environment/signal), (2) it returns a new EpochState, (3) it must correctly process InstantaneousRewards from both reserves and treasury pots, (4) it must handle edge cases like insufficient funds in pots. Without reference Haskell code, the Python implementation must be derived directly from the full spec rules (not just the type signature shown here).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 49. 7832b1c6

**Era:** shelley

**Spec says:** validateScript takes a Script_plc and returns a function (Tx -> Bool). The spec defines it as an abstract Plutus script interpreter with signature Script_plc -> (Tx -> B).

**Haskell does:** isValidPlutusScript takes a protocol version (pv) as an additional first argument and a PlutusScript (ps), then delegates to isValidPlutus via withPlutusScript. The signature is effectively ProtocolVersion -> PlutusScript -> Bool (the Tx/context argument is likely threaded through isValidPlutus or withPlutusScript). The protocol version parameter is not part of the abstract spec signature.

**Delta:** The Haskell implementation adds a protocol version parameter (pv) not present in the spec's abstract signature (Script_plc -> Tx -> B). The protocol version controls which Plutus language version / cost model is used for evaluation. Additionally, the Haskell code uses withPlutusScript to unwrap the script representation before passing to isValidPlutus, which is an implementation detail not captured in the spec.

**Implications:** The Python implementation must accept and correctly pass through a protocol version parameter to the Plutus evaluator, even though the formal spec omits it from the abstract signature. Without the protocol version, the evaluator cannot select the correct Plutus language semantics (V1 vs V2 vs V3) or cost model. The Python wrapper should follow the Haskell pattern: (protocol_version, plutus_script) -> bool, ensuring the protocol version is available at the call site.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 50. 788ab9be

**Era:** shelley

**Spec says:** The spec defines abstract cryptographic types: SKey (private signing key), VKey (public verifying key), KeyHash (hash of a key), Sig (signature), Ser (serialized data), Script (multi-signature script), and HashScr (hash of a script). These are abstract placeholders whose exact implementation remains open.

**Haskell does:** The Haskell implementation concretizes these abstract types for StakeKey specifically: VKey is implemented as Shelley.VKey using Ed25519 DSIGN (via the DSIGN type family), SKey is implemented as SignKeyDSIGN DSIGN, and KeyHash is produced via Shelley.hashKey (which uses Blake2b-224 hashing of the verification key). The implementation provides deterministic key generation from seeds, derivation of 

**Delta:** The spec leaves all crypto types fully abstract, while the Haskell code commits to concrete algorithms: Ed25519 for signing/verification (DSIGN type family) and Blake2b-224 for key hashing (via hashKey). The seed size for key generation is determined by the DSIGN algorithm. Additionally, the Haskell code only covers StakeKey here — the spec's types apply generically across all key roles.

**Implications:** The Python implementation must: (1) use Ed25519 for signing key and verification key operations to be compatible, (2) use Blake2b-224 for key hashing to produce matching KeyHash values, (3) support deterministic key generation from seeds of the correct size (32 bytes for Ed25519), (4) ensure the VKey-to-KeyHash derivation matches (hash the raw VKey bytes with Blake2b-224), and (5) support CBOR serialization/deserialization that is byte-compatible with the Haskell encoding.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 51. 80c67ecb

**Era:** shelley

**Spec says:** Update-Both rule: When slot s < firstSlot(epoch(s) + 1) - RandomnessStabilisationWindow, both the evolving nonce η_v and the candidate nonce η_c are updated to η_v ⊕ η (the evolving nonce XOR-combined with the block nonce η). Critically, η_c is set to η_v ⊕ η (not η_c ⊕ η), so both nonces track identically until the candidate is frozen.

**Haskell does:** No implementing Haskell code was found for the UPDN Update-Both rule.

**Delta:** Missing implementation. The Update-Both rule for the UPDN transition has no corresponding Haskell code provided for analysis. This rule is critical for nonce evolution during the early/middle portion of each epoch.

**Implications:** The Python implementation must correctly implement: (1) the slot boundary condition s < firstSlot(epoch(s)+1) - RandomnessStabilisationWindow, (2) both η_v and η_c are set to the SAME value η_v ⊕ η (not η_c ⊕ η for the candidate), (3) the seed operation (⊕) which is nonce combination/XOR. A common bug would be to update η_c as η_c ⊕ η instead of η_v ⊕ η.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 52. 81bdb144

**Era:** shelley

**Spec says:** adoptGenesisDelegs filters future genesis delegations (fGenDelegs) where slot s ≤ current slot, removes them from fGenDelegs, selects the delegation with maximum slot per genesis key hash, and overrides genDelegs with those selections via right-biased union.

**Haskell does:** No implementing Haskell code was found for analysis.

**Delta:** Cannot verify implementation correctness — no Haskell code provided. Key spec subtleties to watch: (1) the 'max slot' selection per gkh when multiple future delegations exist for the same genesis key, (2) right-biased union override semantics (new genDelegs' overrides existing genDelegs), (3) entries with s exactly equal to slot ARE included in curr.

**Implications:** Python implementation must faithfully implement: filtering fGenDelegs by s ≤ slot, grouping by gkh and selecting max-slot entry per group, right-biased union override of genDelegs, and removal of adopted entries from fGenDelegs. Without reference Haskell code, extra care is needed to match spec semantics exactly.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 53. 81f75404

**Era:** byron

**Spec says:** The BBODY transition rule validates a block body by checking: (1) block size ≤ maxBlockSize from protocol parameters, (2) three hash integrity checks (UTxO payload, delegation certs, update payload) against the block header, and (3) three sub-transitions (BUPI for updates, DELEG for delegation, UTXOWS for UTxO) that transform the state components (us, ds, utxoSt) to (us', ds', utxoSt').

**Haskell does:** No implementing Haskell code was found for the BBODY rule.

**Delta:** Missing implementation. The BBODY rule has no corresponding Haskell code to analyze, so we cannot verify correctness of any implementation against the spec.

**Implications:** The Python implementation must be built directly from the spec. All six conditions (block size check, three hash integrity checks, three sub-transitions) must be implemented. The environment tuple (pps, e_n, utxo_0) and state tuple (utxoSt, ds, us) must be correctly threaded. Special attention needed for: the spelling 'bEndorsment' (missing 'e') which may appear in data types, the correct domain extraction dom(dms(ds)) passed to DELEG, and the correct pairing of environments to sub-rules.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 54. 82026a22

**Era:** shelley

**Spec says:** The BBODY rule requires two preconditions: (1) bBodySize(txs) == hBbsize(bhb) — actual body size must match declared size in header, and (2) bbodyhash(txs) == bhash(bhb) — actual body hash must match declared hash in header. If either fails, corresponding predicate failures (WrongBlockBodySize, InvalidBodyHash) are raised. On success, ledger state is updated via LEDGERS sub-transition and block co

**Haskell does:** No implementing BBODY transition code was found. The mkBlock test helper constructs a TestBlock where thBodyHash = hashBody testBody (ensuring the hash precondition is satisfied by construction) but does not explicitly test the size precondition, the incrBlocks logic, or the predicate failure paths. The test helper is for block construction, not for BBODY rule validation.

**Delta:** No implementation of the BBODY transition rule exists in the codebase. The mkBlock helper only ensures valid block construction (body hash matches by construction) but never tests: (1) WrongBlockBodySize failure, (2) InvalidBodyHash failure, (3) the incrBlocks conditional logic based on overlay slot membership, (4) the LEDGERS sub-transition invocation with correct environment.

**Implications:** The Python implementation must implement all aspects of the BBODY rule from scratch based on the spec. Tests must cover both precondition checks (size and hash matching), predicate failure cases, the overlay slot logic in incrBlocks, and correct threading of ledger state through the LEDGERS sub-transition.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 55. 8213725c

**Era:** shelley

**Spec says:** The OCERT transition relation is typed as a subset of (OCertEnv × (KeyHash_pool ↦ ℕ) × BHeader × (KeyHash_pool ↦ ℕ)), defining the environment, input state, signal, and output state types precisely.

**Haskell does:** No implementing Haskell code was found for the OCERT transition rule.

**Delta:** Missing implementation means we cannot verify whether the actual types, state update logic, or transition preconditions match the spec. The spec defines a clear type signature but without code we cannot confirm the mapping update semantics, certificate validation predicates, or issue number monotonicity requirements.

**Implications:** The Python implementation must be built directly from the spec. Key risks: (1) the state map update logic for operational certificate issue numbers must be implemented correctly with no reference implementation to compare against, (2) all preconditions for valid OCERT transitions (e.g., issue number checks, KES period validity, signature verification) must be inferred from related spec rules, (3) conformance testing will need to rely on spec-derived test vectors rather than cross-checking with H

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 56. 8444ad59

**Era:** shelley

**Spec says:** DCert is a disjoint union of exactly seven certificate types: DCertRegKey (stake registration), DCertDeRegKey (stake de-registration), DCertDeleg (stake delegation), DCertRegPool (pool registration), DCertRetirePool (pool retirement), DCertGen (genesis key delegation), and DCertMir (move instantaneous rewards).

**Haskell does:** The Haskell (Agda-derived) implementation defines DCert with seven constructors but they are significantly different: delegate (combines registration, delegation, and deposit into one), dereg (de-registration with optional coin refund), regpool (pool registration), retirepool (pool retirement), regdrep (DRep registration - new in Conway), deregdrep (DRep de-registration - new in Conway), ccreghot 

**Delta:** The spec describes Shelley/Mary/Alonzo-era certificate types while the Haskell implementation reflects the Conway era. Key differences: (1) DCertRegKey + DCertDeleg are merged into a single 'delegate' constructor that carries Credential, Maybe VDeleg, Maybe KeyHash, and Coin; (2) DCertDeRegKey becomes 'dereg' with an optional Coin for deposit refund; (3) DCertGen and DCertMir are completely removed; (4) Three new Conway-era constructors added: regdrep, deregdrep, ccreghot for DRep and constituti

**Implications:** The Python implementation must target the Conway-era certificate model, not the Shelley-era spec. This means: (1) implement 'delegate' as a unified constructor rather than separate RegKey/Deleg types; (2) implement 'dereg' with optional deposit refund; (3) do NOT implement DCertGen or DCertMir as they no longer exist; (4) implement the three new governance certificate types (regdrep, deregdrep, ccreghot). Any code referencing DCertGen or DCertMir from the spec will be dead code in Conway.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 57. 8796edcd

**Era:** shelley

**Spec says:** hashScript takes a Script and returns a ScriptHash by hashing the serialized script representation. The spec treats this as an abstract function.

**Haskell does:** No implementing code was found in the provided codebase. In the actual cardano-ledger Haskell implementation, hashScript serializes the script to CBOR, prepends a language/type tag byte (0x00 for native scripts, 0x01 for PlutusV1, 0x02 for PlutusV2, 0x03 for PlutusV3), and then applies Blake2b-224 to produce a 28-byte ScriptHash.

**Delta:** The spec is abstract and does not specify the concrete hash algorithm (Blake2b-224), the serialization format (CBOR), or the language tag prefix byte. The actual implementation requires these concrete details which are only found in the Haskell source code.

**Implications:** The Python implementation must replicate the exact serialization and hashing procedure: (1) CBOR-serialize the script, (2) prepend the correct language tag byte, (3) apply Blake2b-224. Any deviation in serialization order, CBOR encoding, or tag byte value will produce incorrect script hashes, breaking script address derivation and witness validation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 58. 881872a1

**Era:** alonzo

**Spec says:** The general accounting property holds for every accepted transaction: total Ada is preserved whether the transaction is fully processed (all scripts validate) or only pays fees (phase-2 script validation failure). The balance equation is: UTxO_out + fees + deposits_created = UTxO_in + refunds + withdrawals.

**Haskell does:** The Haskell test `preserveBalance` checks this property for every ledger transition in a block. For fully-processed transactions it verifies created == consumed (where created = sumCoinUTxO(u') + fees + totalDeposits, consumed = sumCoinUTxO(u) + totalRefunds + withdrawals). For failed-script transactions, the check is skipped (failedScripts short-circuits to True via `.||.`). The `validValuesTx` f

**Delta:** The Haskell test skips the balance check for transactions with failed scripts (hasFailedScripts returns True, and the disjunction short-circuits). This means the test does NOT actually verify the spec claim that the accounting property holds for fee-only (failed script) transactions - it only verifies it for fully-processed ones. The spec explicitly says the property must hold in BOTH cases.

**Implications:** Our Python implementation must ensure the balance/preservation equation holds for both fully-processed AND fee-only transactions. We should test both paths explicitly rather than skipping the failed-scripts case. For fee-only transactions, the balance equation simplifies (no new outputs beyond change for fee collection, no withdrawals processed, no deposit changes) but must still hold.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 59. 8899d8cc

**Era:** byron

**Spec says:** The BUPI rule sequences three sub-transitions: (1) UPIREG processes the proposal 'prop' transitioning us -> us', (2) UPIVOTES processes 'votes' transitioning us' -> us'', and (3) UPIEND processes 'end' (endorsement) transitioning us'' -> us'''. The final state us''' is the result of the BUPI transition with signal (prop, votes, end).

**Haskell does:** No implementing Haskell code was found for the BUPI rule.

**Delta:** The BUPI rule has no corresponding implementation in the Haskell codebase that could be located. This means we cannot verify whether the sequential composition of UPIREG -> UPIVOTES -> UPIEND is correctly implemented.

**Implications:** The Python implementation must faithfully implement the three-step sequential composition: UPIREG first, then UPIVOTES on the intermediate state, then UPIEND on the second intermediate state. State threading order is critical — each sub-transition consumes the output state of the previous one. Any reordering or parallel application would be a spec violation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 60. 8b600730

**Era:** shelley-ma

**Spec says:** evalMPSScript SignedByPIDToken pid slot vhks txb spentouts = there exists a token name t in range(pid ◁ (ubalance spentouts)) such that t ∈ vhks. This filters the spent outputs' combined balance by the policy ID, extracts the token names from the resulting multi-asset map, and checks that at least one token name (interpreted as a key hash) appears in the set of verified (signing) key hashes.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** The implementation for evalMPSScript with the SignedByPIDToken constructor is missing entirely. There is no code to compare against the spec.

**Implications:** The Python implementation must be built directly from the spec. Key design decisions: (1) ubalance computes the combined Value of a set of UTxO outputs; (2) pid ◁ filters the multi-asset portion of that Value to only entries under the given policy ID; (3) the 'range' extracts token names from the filtered map; (4) token names are compared as key hashes against vhks (the set of verified key hashes from transaction witnesses). Care must be taken that token names and key hashes use the same represe

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 61. 8bab207b

**Era:** shelley

**Spec says:** The TICK rule performs three steps: (1) NEWEPOCH transition on nes to get nes', (2) extracts b_prev and es from the ORIGINAL nes (before NEWEPOCH), then applies RUPD transition with environment (b_prev, es) on ru' (from nes') and signal slot to get ru'', (3) destructures nes', applies adoptGenesisDelegs to es' and slot to get es'', and reassembles nes'' with both es'' and ru''.

**Haskell does:** The Haskell implementation (validatingTickTransition) performs: (1) solidifyNextEpochPParams (not in spec), (2) NEWEPOCH transition, (3) adoptGenesisDelegs on nes'. It does NOT perform the RUPD (reward update) transition at all within TICK. The reward update computation is handled elsewhere in the Haskell implementation (likely pulled into the NEWEPOCH or handled via a different mechanism such as 

**Delta:** The RUPD transition step is completely absent from the Haskell TICK implementation. Additionally, the Haskell code calls solidifyNextEpochPParams (which solidifies next-epoch protocol parameters) before NEWEPOCH, which is not mentioned in the spec. The epoch number is computed via solidifyNextEpochPParams rather than directly from epochInfoEpoch on the slot. The RUPD step that transitions ru' to ru'' using (b_prev, es) from the original nes as environment is missing.

**Implications:** For a Python implementation: (1) The RUPD transition must be included in TICK as specified, since the spec requires reward updates to happen during tick processing. The Haskell code likely handles reward updates through a different architectural path (possibly incremental/pulser-based rewards integrated into NEWEPOCH). (2) The solidifyNextEpochPParams call is an implementation detail for handling protocol parameter updates that may need to be replicated. (3) The Python implementation should foll

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 62. 8d7c07aa

**Era:** shelley

**Spec says:** The preservation of value lemma states Val(s) + w = Val(s') where w = wbalance(txwdrls(t)). The consumed function in the spec for Shelley era is: balance(utxo ∣ txins) + depositRefunds + getCoin(txwdrls). There is no 'mint' term in Shelley.

**Haskell does:** The Haskell consumed function includes a '+ txb.mint' term (multi-asset minting value) in addition to balance(utxo ∣ txins), depositRefunds, and getCoin(txwdrls). This is the Mary/Alonzo-era generalization.

**Delta:** The implementing Haskell code is a post-Shelley (Mary+) version of consumed that includes multi-asset minting (txb.mint). The spec rule as stated is the Shelley-era preservation lemma which does not account for minting. The algebraic identity still holds in the generalized case because produced also includes mint on its side, but the consumed/produced definitions differ from the Shelley spec.

**Implications:** The Python implementation must use the era-appropriate consumed/produced definitions. For Shelley era, mint is not present. For Mary era onwards, both consumed and produced must include the mint term. If implementing only Shelley, do NOT add mint. If implementing Mary+, ensure mint appears on both sides of the equation to maintain the preservation invariant.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 63. 924611a4

**Era:** shelley

**Spec says:** UTxO maps OutRef (TxId × Ix) to TxOut (Addr × Value), where TxOut is the full pair of address and value.

**Haskell does:** The Haskell function `unspentOutputsTx` maps each OutRef to `addressTO txOut` — extracting only the address from the transaction output, not the full TxOut (Addr × Value) pair.

**Delta:** The Haskell code stores only the address (`addressTO txOut`) as the map value rather than the complete TxOut (which should include both the address and the value). This means the resulting map is OutRef → Addr instead of OutRef → TxOut.

**Implications:** Our Python implementation must map OutRef to the full TxOut (address AND value). If we faithfully follow the Haskell code, we would lose the value component and break downstream rules that need to look up output values from the UTxO (e.g., value preservation, fee calculation, balance checking). This appears to be either a bug in the Haskell implementation or `addressTO` is misleadingly named and actually returns the full TxOut. We should verify the definition of `addressTO` — if it truly returns

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 64. 9704745f

**Era:** shelley

**Spec says:** η = blocksMade / (slotsPerEpoch · ActiveSlotCoeff). There is no special casing based on the decentralization parameter d. The formula uses a simple ratio of blocks made to expected blocks.

**Haskell does:** The Haskell implementation computes expectedBlocks = floor((1 - d) * activeSlotVal(asc) * slotsPerEpoch) and has a special case: when d >= 0.8, eta is forced to 1 regardless of actual block production. Otherwise eta = blocksMade / expectedBlocks. The denominator incorporates (1-d) to account for the fraction of slots available to stake pools (vs. federated BFT nodes).

**Delta:** The spec formula for η uses a simple denominator (slotsPerEpoch · ActiveSlotCoeff) without the (1-d) factor and without the d >= 0.8 special case. The Haskell implementation adjusts expected blocks by (1-d) to reflect that only a fraction of slots are available to stake pools, and forces eta=1 when d >= 0.8 (high decentralization) to avoid division by very small numbers or zero. This is a significant semantic difference: the spec's eta can exceed 1 naturally (capped by min(1,·)), while the Haske

**Implications:** Python implementation must follow the Haskell behavior (incorporating (1-d) in expectedBlocks and the d >= 0.8 => eta=1 guard) rather than the simplified spec formula. Failing to include the d factor would produce incorrect deltaR1 values, especially during the Byron-to-Shelley transition period when d is high. The d >= 0.8 edge case is critical to avoid division-by-zero or near-zero when most slots are federated.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 65. 98e7b5bd

**Era:** shelley

**Spec says:** The RUPD transition has state type RewardUpdate? (optional RewardUpdate), environment RUpdEnv, and signal Slot. The state is either Nothing or a fully computed RewardUpdate.

**Haskell does:** The Haskell implementation uses `StrictMaybe PulsingRewUpdate` as the state type instead of `StrictMaybe RewardUpdate`. PulsingRewUpdate is a pulsing/incremental computation that may not yet be a fully resolved RewardUpdate — it supports incremental (chunked) reward calculation across multiple slots rather than computing the full RewardUpdate atomically.

**Delta:** The spec models RewardUpdate as an atomic optional value, but the implementation uses a PulsingRewUpdate which represents an incremental/pulsing computation that is stepped over multiple slots before producing a final RewardUpdate. This is an implementation optimization not reflected in the spec's abstract model.

**Implications:** A Python implementation could follow the spec's simpler model (computing RewardUpdate atomically) for correctness, but must be aware that conformance tests against the Haskell node may involve pulsing behavior. If implementing pulsing, the intermediate states (partially computed reward updates) need to be handled. The key invariant is that once the pulsing computation completes, it should yield the same RewardUpdate the spec would produce atomically. Additionally, PredicateFailure is Void (no fa

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 66. 99f770ee

**Era:** shelley

**Spec says:** The function `toShelley` converts a Byron CEState, genesis delegation map, and block number into an initial Shelley ChainState by calling `initialShelleyState` with specific arguments derived from the Byron state: epoch from s_last, protocol parameters from the update state, UTxO and reserves from the ledger state, the previous block hash converted to a nonce, and an overlay schedule computed from

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Missing implementation. The `toShelley` translation function that bridges Byron to Shelley chain state has no corresponding Haskell code provided for analysis. This is the critical era-transition function.

**Implications:** The Python implementation must be built entirely from the spec. Key concerns: (1) correct destructuring of the Byron CEState tuple (6 components with wildcards at positions 2 and 5), (2) correct argument ordering to initialShelleyState (9 arguments), (3) correct computation of epoch from s_last, (4) correct extraction of protocol parameters via pps(us), (5) correct conversion of previous block hash to nonce via prevHashToNonce, (6) correct computation of overlay schedule, (7) the hash of the fin

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 67. 9a2ee8a8

**Era:** byron

**Spec says:** The delegation interface transition (DELEG) is defined as a relation in the powerset of (DIEnv × DIState × seqof(DCert) × DIState). Given an environment, initial state, and sequence of delegation certificates, it produces a new delegation interface state.

**Haskell does:** No implementing Haskell code was provided for analysis. However, the existing Haskell test (ledgerExamples) demonstrates that a DelegateeNotRegisteredDELEG error is raised when attempting to delegate to a stake pool that is not registered (mkKeyHash 1), propagated through the chain DelegsFailure -> DelplFailure -> DelegFailure.

**Delta:** No implementation code to compare against the spec. The test reveals that the DELEG transition includes a validation check that the delegatee (target stake pool) must be registered, which is an implicit part of the spec's transition relation (invalid transitions are not in the relation). This check is wrapped in era-specific error types (AllegraApplyTxError).

**Implications:** The Python implementation must: (1) model DIEnv, DIState, and DCert types correctly, (2) implement the DELEG transition as a function that validates a sequence of delegation certificates, (3) raise appropriate errors (e.g., DelegateeNotRegisteredDELEG) when the delegatee stake pool is not registered, and (4) propagate errors through the correct hierarchy (DelegsFailure > DelplFailure > DelegFailure).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 68. 9aa44ff9

**Era:** shelley

**Spec says:** The Deleg-Dereg rule requires: (1) c is DCertDeRegKey, (2) hk = cwitness(c), (3) hk ↦ 0 ∈ rewards (credential registered with zero reward balance). On success: {hk} is domain-subtracted from rewards, {hk} is domain-subtracted from delegations, ptrs is range-subtracted by {hk}. fGenDelegs, genDelegs, i_rwd unchanged.

**Haskell does:** The implementing code only shows the STS instance declaration for ShelleyDELEG with type families and delegates to delegationTransition. The actual transition logic (delegationTransition function) is not shown, so we cannot verify the precondition check (reward balance must be zero) or the state update (domain/range subtractions). The implementation operates on CertState era which bundles DState a

**Delta:** The full implementation of delegationTransition is not provided for inspection. The CertState bundling means the deregistration logic must correctly reach into nested DState fields (rewards map, delegations map, ptrs map) and perform the three subtractions. There is a risk that the zero-reward-balance precondition or the pointer cleanup (range subtraction on ptrs) could diverge from spec if delegationTransition handles them differently.

**Implications:** Python implementation must: (1) check that the credential exists in rewards with exactly 0 balance before allowing deregistration (raising StakeKeyNotRegisteredDELEG if not registered, or StakeKeyNonZeroAccountBalanceDELEG if balance > 0), (2) remove the credential from the rewards map, (3) remove the credential from the delegations map, (4) remove all pointer entries whose range value equals the deregistering credential. All other state fields must remain unchanged.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 69. 9b664efb

**Era:** shelley

**Spec says:** For all valid ledger states, when a transaction tx is applied via the UTXOW rule (lenv ⊢ u →(utxow, tx) u'), then for all out in outs(tx), out is in getUTxO(u'). All transaction outputs must appear in the resulting UTxO set.

**Haskell does:** In the IsValid True branch, updateUTxOState is called which adds new outputs to the UTxO. However, in the IsValid False branch (phase-2 validation failure / collateral collection), the UTxO is updated by removing collateral inputs only — the transaction outputs are NOT added to the resulting UTxO set. The spec property 'outputs in new UTxO' only holds for valid (IsValid True) transactions.

**Delta:** The spec property as stated universally quantifies over all transactions, but the implementation only adds outputs to the UTxO for valid transactions (IsValid True). For invalid transactions (IsValid False), collateral is consumed but outputs are discarded. The property implicitly only applies to valid transactions, or alternatively the UTXOW transition for invalid txs is considered a different transition.

**Implications:** In our Python implementation, we must ensure that: (1) for IsValid True transactions, all outputs of tx are added to the new UTxO, and (2) for IsValid False transactions, outputs are NOT added — only collateral inputs are removed. The spec property should be tested only for valid transactions. This is a well-known Alonzo-era design choice but creates a subtle spec-vs-implementation nuance.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 70. a41d223e

**Era:** shelley

**Spec says:** Rule New-Proto-Param-Denied specifies three denial conditions: (1) pp_new = Nothing, (2) reserves + diff < sum of instant rewards, (3) maxTxSize(pp_new) + maxHeaderSize(pp_new) >= maxBlockSize(pp_new). When denied, the old pp is kept, acnt unchanged, and utxoSt is updated via updatePpup(utxoSt, pp) using OLD parameters. The denial logic involves obligation calculations and reserve/reward balance c

**Haskell does:** The provided Haskell function `updatePpup` handles the proposal update mechanism (rotating future proposals to current, computing voted future params) but does NOT implement the denial conditions from the spec rule. It focuses on the ppup state rotation: moving future proposals to current (if they have legal protocol version updates), clearing future proposals, and computing votedFuturePParams. Th

**Delta:** The provided Haskell code (`updatePpup`) is a helper for managing proposal state rotation, not the implementation of the denial conditions themselves. The core denial logic—checking pp_new == Nothing, reserves + diff < sum(i_rwd), and maxTxSize + maxHeaderSize >= maxBlockSize—is not present in this code. The full NEWPP transition rule that checks these conditions and decides between accepted/denied paths is not shown.

**Implications:** For our Python implementation: (1) We need to implement the three denial conditions as a separate check in the NEWPP transition, not conflate them with the updatePpup helper. (2) The updatePpup function should be implemented as a proposal rotation helper that is called in BOTH the accepted and denied paths. (3) The obligation calculation (oblg_cur vs oblg_new) and the reserve sufficiency check must be implemented at the epoch boundary transition level. (4) The block size invariant check (maxTxSi

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 71. a8070884

**Era:** shelley

**Spec says:** The BBODY transition rule requires: (1) bBodySize(txs) = hBbsize(bhb), (2) bbodyhash(txs) = bhash(bhb), (3) LEDGERS sub-transition succeeds, and updates state with ls' and incrBlocks(bslot(bhb) ∈ oslots, hk, b).

**Haskell does:** No implementing Haskell code was provided for analysis.

**Delta:** Cannot verify implementation fidelity — no Haskell code available. Key areas of concern: (a) body size check against header, (b) body hash check against header, (c) correct invocation of LEDGERS sub-rule, (d) incrBlocks logic conditional on overlay slot membership.

**Implications:** Python implementation must be tested purely against the spec. Special attention to: the predicate failure types (WrongBlockBodySize, InvalidBodyHash), the overlay-slot conditional in incrBlocks, and correct threading of ledger state through LEDGERS.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 72. a8098d3b

**Era:** shelley

**Spec says:** Rule New-Proto-Param-Accept defines the conditions under which new protocol parameters pp_new are accepted at an epoch boundary. It requires: (1) pp_new ≠ Nothing, (2) oblg_cur = deposits, (3) reserves + diff ≥ Σ instant_rewards, (4) maxTxSize(pp_new) + maxHeaderSize(pp_new) < maxBlockSize(pp_new). On acceptance, deposits become oblg_new, reserves adjusted by diff, ppup cleaned, and pp updated to 

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Missing implementation. The rule for accepting new protocol parameters at epoch boundaries has no corresponding Haskell code provided for analysis. This is a critical epoch transition rule in the Shelley era.

**Implications:** The Python implementation must be built entirely from the spec. All six preconditions and the state transformations (deposits update, reserves adjustment, ppup cleanup, pp replacement) must be carefully implemented and thoroughly tested since there is no reference implementation to cross-check against.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 73. a9038ea8

**Era:** shelley

**Spec says:** KES private signing keys are indexed by natural number evolution step (sk : ℕ → SKeyEv), meaning the key evolves incrementally through discrete steps while the public verifying key (vk : VKeyEv) remains constant across all evolution steps.

**Haskell does:** The implementation uses an `evolveKey` function that mutates key state in an MVar, with destructive memory updates (forgetSignKeyKES) on old keys. It handles edge cases not in the abstract spec: BeforeKESStart (key not yet valid), AfterKESEnd (key expired and poisoned), KESKeyPoisoned (already destroyed key). The evolution is done iteratively step-by-step via a recursive `go` function, and the imp

**Delta:** The spec is purely abstract (sk is a mathematical function ℕ → SKeyEv), while the implementation adds: (1) key poisoning for expired/already-destroyed keys, (2) a bounded KES range with BeforeKESStart/InKESRange/AfterKESEnd status, (3) destructive in-place key evolution with memory cleanup, (4) error handling for edge cases (KESKeyAlreadyPoisoned, KESCouldNotEvolve). The spec does not define bounds on evolution steps or error/poison states.

**Implications:** Python implementation must: (1) model KES key state with evolution tracking including current evolution number, (2) implement bounded evolution range (start period, end period) rather than unbounded ℕ, (3) handle poison/expired states appropriately, (4) ensure forward-only evolution (targetEvolution must be >= current), (5) not need destructive memory semantics but should model the state transitions correctly.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 74. aa109285

**Era:** shelley

**Spec says:** Rule Reward-Update-Exists: When ru ≠ Nothing, the RUPD transition leaves the state unchanged — ru transitions to ru. No new reward update is computed regardless of the slot timing.

**Haskell does:** When ru is SJust, the implementation does NOT simply return ru unchanged. Instead, it checks timing (RewardsTooEarly, RewardsJustRight, RewardsTooLate) and: (1) For RewardsTooEarly, returns SNothing (ignoring the existing ru entirely). (2) For RewardsJustRight with SJust (Pulsing _ _), it runs another pulse step via pulseStep, mutating the state. (3) For RewardsJustRight with SJust (Complete _), i

**Delta:** The spec's Reward-Update-Exists rule is a simple identity transition (ru → ru when ru ≠ Nothing). The Haskell implementation is far more complex: it incorporates an incremental pulsing mechanism with three timing phases and can actively mutate the reward update state (pulse it forward, force-complete it, or even discard it). The spec rule covers only the 'already complete, no further work needed' case. The pulsing/incremental computation is an implementation detail not captured in the formal spe

**Implications:** For a Python implementation: (1) The spec alone is insufficient to implement this rule correctly — the pulsing mechanism is essential for correctness in the real protocol. (2) A literal spec implementation (identity when ru ≠ Nothing) would never advance the reward pulsing computation, meaning rewards would never be computed. (3) The Python implementation must decide whether to implement the full pulsing mechanism or compute rewards in one shot. (4) The RewardsTooEarly case returning SNothing ev

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 75. abef53cf

**Era:** shelley

**Spec says:** Rule Reward-Update-Exists: If ru ≠ Nothing, the state remains unchanged — ru transitions to ru with no modification, regardless of the current slot s.

**Haskell does:** The Haskell implementation does NOT simply pass through an existing ru unchanged. Instead, it implements a complex pulsing reward calculation state machine with three timing phases (RewardsTooEarly, RewardsJustRight, RewardsTooLate) and three states (SNothing, Pulsing, Complete). When ru is SJust (Pulsing _ _), it calls pulseStep to advance computation. When ru is SJust (Complete _), it returns it

**Delta:** The spec's Reward-Update-Exists rule is a trivial identity transition (ru → ru when ru ≠ Nothing), but the Haskell implementation is a full incremental reward computation engine. The spec rule only captures one narrow case (Complete state passthrough), while the implementation handles pulsing progression, forced completion, and initial startup — none of which appear in this spec rule. The implementation merges what would be multiple spec rules (including the companion Reward-Update-Empty rule fo

**Implications:** A Python implementation faithful only to the Reward-Update-Exists spec rule would be a trivial no-op for non-Nothing states, which would be correct for the Complete case but would miss the critical pulsing advancement logic. The Python implementation needs to replicate the full state machine: (1) determine reward timing based on slot position relative to stability window, (2) handle SNothing by starting the pulser, (3) handle Pulsing by calling pulseStep or completeStep depending on timing, (4) 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 76. ac187ba6

**Era:** shelley

**Spec says:** Certificate types include DCertRegKey (with regCred accessor), DCertDeleg (with dpool accessor), DCertRegPool (with poolParam accessor), DCertRetirePool (with retire accessor), DCertGen (with genesisDeleg accessor returning a triple of KeyHashGen, KeyHash, KeyHash_vrf), and DCertMir (with moveRewards and mirPot accessors). These are distinct certificate types with dedicated accessor functions.

**Haskell does:** The Haskell (Agda) implementation uses a unified DCert type with constructors: delegate (Credential, Maybe VDeleg, Maybe KeyHash, Coin), dereg (Credential, Maybe Coin), regpool (KeyHash, PoolParams), retirepool (KeyHash, Epoch), regdrep (Credential, Coin, Anchor), deregdrep (Credential, Coin), ccreghot (Credential, Maybe Credential). There are no DCertGen or DCertMir constructors, no genesisDeleg/

**Delta:** Major structural divergence: (1) The spec's separate DCertRegKey and DCertDeleg are merged into a single 'delegate' constructor that optionally registers and optionally delegates. (2) DCertGen (genesis delegation) is entirely absent — no genesis delegation certificates exist in the implementation. (3) DCertMir (MIR certificates with moveRewards and mirPot) is entirely absent — no instantaneous rewards mechanism. (4) regCred is implicit in the Credential field of delegate/dereg. (5) dpool is the 

**Implications:** The Python implementation must follow the Conway-era Agda model, not the Shelley-era spec. This means: (1) Use a single DCert sum type with the 7 constructors shown. (2) Do NOT implement DCertGen or DCertMir — these are removed in Conway. (3) The 'delegate' constructor combines credential registration and pool delegation into one action. (4) Pool registration uses (KeyHash, PoolParams) not (DCertRegPool → PoolParam). (5) 'dereg' carries an optional deposit refund amount. (6) Must implement DRep-

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 77. b0648ff0

**Era:** shelley-ma

**Spec says:** evalMPSScript (RequireAll ls) pid slot vhks txb spentouts = ∀ s' ∈ ls : evalMPSScript s' pid slot vhks txb spentouts. All sub-scripts in the list must evaluate to True, including the vacuous truth case for an empty list.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify whether the implementation exists or correctly implements the universal quantifier (∀) semantics, including the empty-list edge case (vacuous truth).

**Implications:** The Python implementation must ensure: (1) RequireAll over an empty list returns True (vacuous truth), (2) RequireAll returns False as soon as any sub-script is False, (3) all context parameters (pid, slot, vhks, txb, spentouts) are passed unchanged to each recursive call. Without reference Haskell code, we must rely purely on the spec for correctness.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 78. b151486b

**Era:** shelley

**Spec says:** PState contains three fields: (1) poolParams: KeyHash_pool ↦ PoolParam mapping registered pools to their parameters, (2) fPoolParams: KeyHash_pool ↦ PoolParam for future pool parameter changes, (3) retiring: KeyHash_pool ↦ Epoch for retiring stake pools.

**Haskell does:** PState contains four fields: (1) psVRFKeyHashes: Map VRFVerKeyHash (NonZero Word64) — an extra field not in the spec that tracks VRF key hash registrations with a reference count, (2) psStakePools: Map (KeyHash StakePool) StakePoolState — replaces the spec's poolParams but uses StakePoolState instead of PoolParam, (3) psFutureStakePoolParams: Map (KeyHash StakePool) StakePoolParams — corresponds t

**Delta:** Two divergences: (a) The Haskell implementation adds an extra field psVRFKeyHashes that is not present in the spec. This field maintains a reference-counted mapping of VRF verification key hashes to prevent duplicate VRF key registrations across pools. (b) The spec's poolParams maps to PoolParam directly, while the Haskell psStakePools maps to StakePoolState which may wrap or differ from the raw PoolParam type. The field name also changed from poolParams to psStakePools, and the value type from 

**Implications:** For the Python implementation: (1) We need to decide whether to include the psVRFKeyHashes field. If we aim for spec-fidelity, we omit it; if we aim for Haskell-compatibility (e.g., for conformance testing against the Haskell node), we must include it. (2) We need to understand the difference between PoolParam (spec) and StakePoolState (Haskell) — if StakePoolState is an enum or wrapper (e.g., tracking whether a pool is active vs. just registered), our Python model must account for this. (3) Ser

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 79. b44a3e4b

**Era:** shelley

**Spec says:** After a pool registration certificate c ∈ DCertRegPool causes a POOL transition p → p', the certificate witness hk must be in getStPools(p') AND hk must NOT be in getRetiring(p'). This must hold for all valid ledger states.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Missing implementation. Cannot verify whether the pool registration transition correctly adds the pool key to registered pools and removes it from retiring pools.

**Implications:** The Python implementation must ensure: (1) processing a RegPool certificate adds the pool's key hash to the registered stake pools set, (2) processing a RegPool certificate removes the pool's key hash from the retiring pools map if it was previously there, (3) both conditions hold simultaneously after the transition. Without reference implementation code, we must test purely against the spec.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 80. b6f3d610

**Era:** shelley

**Spec says:** When e = e_ℓ + 1 and ru = Nothing, the new epoch state (nes) is returned completely unchanged. No epoch transition processing occurs at all — the state is passed through as-is.

**Haskell does:** When e = lastEpoch + 1 and ru = nothing, the Haskell implementation still runs the EPOCH transition on the epoch state (eps ⇀⦇ e ,EPOCH⦈ eps'), updates lastEpoch to e, and returns ⟦ e , eps' , nothing ⟧. This means epoch-level processing (via the EPOCH rule) IS performed even when the reward update is Nothing.

**Delta:** The spec says the state should be returned unchanged (nes → nes) when ru = Nothing, but the Haskell implementation applies the EPOCH transition and updates the epoch number. This is a significant semantic divergence: the spec's No-Reward-Update is a no-op, while the Haskell code's NEWEPOCH-No-Reward-Update still triggers epoch processing. The Haskell implementation essentially merges the behavior — it always runs the EPOCH sub-transition at epoch boundaries regardless of whether a reward update 

**Implications:** For our Python implementation, we must decide which behavior to follow. If we follow the spec literally, we return the state unchanged when ru=Nothing (true no-op). If we follow the Haskell implementation, we still run the EPOCH transition but skip reward application. This is a critical design decision. The Haskell behavior likely reflects the intended on-chain behavior since the formal spec may have been simplified. We should verify against actual ledger behavior and likely follow the Haskell i

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 81. b71c028e

**Era:** shelley

**Spec says:** η = blocksMade / (slotsPerEpoch · ActiveSlotCoeff) with min(1, η) applied to the monetary expansion calculation. This is a straightforward ratio regardless of the decentralization parameter d.

**Haskell does:** When d >= 0.8, η is hardcoded to 1 (effectively disabling the performance-based scaling). Otherwise, η = blocksMade / expectedBlocks where expectedBlocks = floor((1-d) · activeSlotVal(asc) · slotsPerEpoch). This means η depends on the decentralization parameter d, not just on ActiveSlotCoeff as the spec suggests.

**Delta:** The spec defines η = blocksMade / (slotsPerEpoch · ActiveSlotCoeff) as a simple ratio. The Haskell implementation introduces a d-parameter dependency: when d >= 0.8, η=1; otherwise expectedBlocks = floor((1-d) · activeSlotVal(asc) · slotsPerEpoch) and η = blocksMade / expectedBlocks. The denominator includes (1-d) factor and uses floor(), which the spec omits. This is a known divergence between the Shelley-era formal spec and the actual implementation.

**Implications:** The Python implementation must replicate the Haskell behavior (d-dependent η), not the simplified spec formula. When d >= 0.8, η must be 1. Otherwise, expectedBlocks = floor((1-d) · activeSlotCoeff · slotsPerEpoch) and η = blocksMade / expectedBlocks. Using the spec formula directly would produce incorrect Δr₁ values for any epoch where d != 0.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 82. b740e052

**Era:** shelley

**Spec says:** The MIR rule separates instantaneous rewards into two sources (irReserves and irTreasury), filters each by registered credentials, computes separate totals (totR, totT), checks totR ≤ reserves AND totT ≤ treasury as preconditions, subtracts each total from its respective pot (treasury - totT, reserves - totR), unions both filtered reward maps into rewards (rewards ∪+ irwdR ∪+ irwdT), and resets bo

**Haskell does:** The Haskell implementation (applyRUpd) operates on a pre-computed RewardUpdate (Δt, Δr, Δf, rs) rather than raw irReserves/irTreasury. It filters rs by registered credentials (regRU = rs ∣ dom rewards), sums unregistered rewards (unregRU'), adds unregRU' back to treasury, computes new treasury as posPart(treasury + Δt + unregRU'), new reserves as posPart(reserves + Δr), new fees as posPart(fees + 

**Delta:** 1) The spec has two separate instantaneous reward sources (irReserves, irTreasury) with separate filtering and precondition checks; the Haskell code has a single merged reward map (rs) with deltas (Δt, Δr, Δf). 2) The spec requires totR ≤ reserves and totT ≤ treasury as hard preconditions (rule doesn't fire otherwise); the Haskell code uses posPart to clamp to zero, never failing. 3) The spec discards rewards for unregistered credentials silently; the Haskell code returns unregistered reward amo

**Implications:** Python implementation must decide which model to follow. If following the Shelley-era MIR spec literally, we need two separate IR maps and hard precondition checks. If following the Conway-era Haskell (applyRUpd), we need: single reward map rs, posPart clamping, unregistered rewards returned to treasury, and fee adjustment. The unregRU-to-treasury behavior is important for accounting correctness. The posPart vs precondition difference means the Haskell version is more permissive (never fails).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 83. b82d9a51

**Era:** byron

**Spec says:** CEState is a record with 6 fields: s_last (Slot), sgs (VKey_G* - sequence of genesis verification keys representing last signers), h (Hash - current block hash), utxoSt (UTxO state), ds (DIState - delegation state), us (UPIState - update interface state).

**Haskell does:** No implementing Haskell code was found for this type definition.

**Delta:** Cannot verify whether a Haskell implementation exists or matches the spec. The CEState type may be defined elsewhere in the codebase (e.g., in cardano-ledger Byron chain modules) but was not provided for analysis.

**Implications:** The Python implementation must define a CEState dataclass/NamedTuple with exactly these 6 fields and their correct types. Special attention needed for: (1) sgs is a sequence of genesis verification keys (not arbitrary keys), (2) utxoSt is UTxO (not a wrapper UTxOState), (3) all sub-state types (DIState, UPIState) must also be correctly defined.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 84. bcf39e53

**Era:** shelley-ma

**Spec says:** evalMPSScript (SpendsCur pid') pid slot vhks txb spentouts = (pid' ≠ Nothing ∧ pid' ∈ dom(ubalance spentouts)) ∨ (pid' = Nothing ∧ pid ∈ dom(ubalance spentouts)). When pid' is specified (not Nothing), check that pid' appears in the policy IDs of the balanced spent outputs. When pid' is Nothing, check that the script's own policy ID (pid) appears in the policy IDs of the balanced spent outputs.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Missing implementation. The spec defines a two-branch disjunction for SpendsCur: explicit pid' lookup vs. self-referential pid lookup. Without code, we cannot verify correctness of either branch or the Nothing/Just discrimination.

**Implications:** Python implementation must faithfully implement both branches: (1) when pid' is a specific policy ID, check that policy ID is in dom(ubalance(spentouts)); (2) when pid' is None/Nothing, fall back to the script's own policy ID (pid) and check that. The ubalance function aggregates UTxO values and dom extracts the set of policy IDs present. Care must be taken that 'dom' of a multi-asset value means the set of policy IDs, not token names.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 85. bed11226

**Era:** byron

**Spec says:** The PVBUMP rule has two separate inference rules: the no-change rule (when filtering fads to entries with slot ≤ s_n - 4·k yields ε, pv/pps remain unchanged) and an adoption rule (when the filtered sequence is non-empty, the last entry is adopted). These are two distinct rules with separate preconditions.

**Haskell does:** The Haskell implementation combines both rules into a single transition rule using a case expression: it computes `s_n -. 4 *. k <=◁ fads` and pattern matches on [] (no change) vs the first element of the filtered list `(_s, (pv_c, pps_c)) : _xs` (adoption). Critically, the adoption case takes the FIRST element of the filtered list, not the LAST. Additionally, the environment includes BlockCount k

**Delta:** 1) The Haskell code takes the FIRST element of the domain-restricted fads list when adopting, whereas the spec's companion adoption rule likely refers to the last/most recent candidate. The ordering depends on how fads is constructed - if fads is ordered by slot ascending, taking the first means taking the oldest qualifying candidate rather than the newest. 2) k is parameterized in the environment rather than being a global constant. 3) Saturating subtraction is used to handle the case where s_n

**Implications:** For the Python implementation: (1) Need to use saturating subtraction when computing s_n - 4*k to avoid negative slot values. (2) Need to carefully match which element of the filtered fads list is selected for adoption - the Haskell code takes the first (head) element, so our implementation should do the same. (3) k should be a parameter (not hardcoded) for testability. (4) The domain restriction operator `<=◁` filters to slots ≤ the threshold value.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 86. c9379484

**Era:** shelley

**Spec says:** Value is a finite map from Currency to Quantity (Currency ↦ Quantity), a single-level flat map where each currency identifier maps directly to a quantity.

**Haskell does:** Value is defined as a nested two-level map: Map CurrencySymbol (Map TokenName Integer). The outer map keys on CurrencySymbol (policy ID), and the inner map keys on TokenName, mapping to Integer. This means a 'currency' in Plutus is identified by the pair (CurrencySymbol, TokenName), not a single Currency key.

**Delta:** The spec describes a flat map Currency ↦ Quantity, but the Haskell implementation uses a nested/grouped map CurrencySymbol ↦ (TokenName ↦ Integer). The effective key is a composite (CurrencySymbol, TokenName) pair rather than a single atomic Currency identifier. The quantity type is Integer (arbitrary precision) rather than an abstract Quantity type. This is a structural difference: the spec's flat representation vs Haskell's grouped-by-policy-id representation.

**Implications:** The Python implementation must use the nested two-level map structure (dict[CurrencySymbol, dict[TokenName, int]]) to match the Haskell implementation and be compatible with on-chain serialization (PlutusData encoding). A flat dict[Currency, Quantity] would not serialize/deserialize correctly against Plutus. All Value operations (addition, subtraction, comparison, lookup) must account for the two-level nesting. ADA is represented with empty bytestring as CurrencySymbol and empty bytestring as To

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 87. ce324e11

**Era:** shelley

**Spec says:** sk_n = sk(n) denotes the n-th evolution of the private signing key sk, where sk is a pure function from ℕ (natural numbers) to evolved private keys. The evolution is a total mathematical function mapping any natural number n to the corresponding evolved key.

**Haskell does:** The implementation evolves keys incrementally and destructively: it walks from the current evolution to the target evolution one step at a time via updateKES, clearing old key material from memory after each step (forgetSignKeyKES). The key can become 'poisoned' (KESKeyPoisoned) if the target period is past the KES end, making further operations impossible. Evolution is bounded by the KES period r

**Delta:** The spec models KES key evolution as a pure total function ℕ → SKeyEv, but the implementation is: (1) incremental — must evolve step-by-step from current to target, cannot jump or go backwards; (2) destructive — old keys are erased from memory via forgetSignKeyKES; (3) partial — evolution fails when the key is poisoned or the target period is out of KES range; (4) stateful — uses mutable state (MVar) with concurrency protection. The spec's backward-reachability (sk(0), sk(1), ...) is not possibl

**Implications:** Python implementation should: (1) model key evolution as an incremental forward-only process — once evolved to period n, you cannot go back to period < n; (2) handle the three states: BeforeKESStart (key not yet valid), InKESRange (normal operation), AfterKESEnd (key expired/poisoned); (3) ensure that evolving to the same or earlier period is a no-op (targetEvolution <= kesEvolution returns Updated without change); (4) consider whether to implement destructive key erasure or simply track the cur

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 88. d2e65e88

**Era:** shelley

**Spec says:** Deleg-Reg rule updates rewards via union with {hk ↦ 0} to create a new reward account with zero balance, and updates ptrs via union with {ptr ↦ hk} to map the certificate pointer to the credential. The precondition is that hk ∉ dom(rewards), i.e., the credential is not already registered. The only deposit concept is implicit (zero initial balance).

**Haskell does:** The Haskell implementation uses `registerShelleyAccount cred ptr compactDeposit Nothing` where compactDeposit is derived from `pp ^. ppKeyDepositL` (the protocol parameter for key deposit). This means the implementation stores a deposit amount from protocol parameters alongside the account registration, rather than simply mapping the credential to a zero reward balance as the spec indicates. The r

**Delta:** The spec shows rewards updated with {hk ↦ 0} (pure zero balance), while the implementation additionally stores a compactDeposit from protocol parameters via registerShelleyAccount. The deposit tracking is an implementation detail beyond what the Shelley spec formula shows. Additionally, the spec uses a simple rewards map but the implementation uses a richer AccountState structure with separate balance and deposit fields.

**Implications:** Python implementation must: (1) track the key deposit from protocol parameters during registration, not just set balance to 0; (2) use the richer account state structure that separates reward balance from deposit; (3) ensure the deposit amount comes from ppKeyDeposit protocol parameter. A naive implementation following only the spec formula (rewards ∪ {hk ↦ 0}) would miss the deposit tracking.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 89. d36f6556

**Era:** shelley

**Spec says:** TxWitness is a pair of (VKey ↦ Sig, ScriptHash ↦ Script) — two maps: verification key witnesses and script witnesses.

**Haskell does:** ShelleyTxWits pattern includes three components: Set (WitVKey Witness), Map ScriptHash (Script era), and Set BootstrapWitness. Later eras extend this further with plutusV1/V2/V3 scripts, plutus data, and redeemers (fields 0-7 in CBOR map). The CBOR encoding uses a tagged map with field indices 0-7, and empty fields are explicitly forbidden during deserialization.

**Delta:** The spec defines TxWitness as a 2-tuple (key witnesses, script witnesses), but the Haskell implementation adds a third component (BootstrapWitness for Byron-era backward compatibility) and later eras add plutus scripts (V1/V2/V3), plutus data, and redeemers as additional fields. The CBOR encoding enforces that no field may be present as an empty collection — this is an implementation-level constraint not stated in the spec.

**Implications:** Python implementation must: (1) include BootstrapWitness as a third witness component even in Shelley era, (2) in later eras support fields 0-7 in the CBOR witness map, (3) enforce that empty fields are rejected during CBOR deserialization with appropriate error messages, (4) support both tagged and untagged CBOR encoding variants.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 90. d4c3a180

**Era:** shelley

**Spec says:** TxBody is defined as the product ℙ TxIn × (Ix ↦ TxOut), consisting of only two fields: a set of transaction inputs (txins) and a finite map from index to transaction output (txouts).

**Haskell does:** The Haskell/Agda implementation defines TxBody as a record with 20 fields: txins, refInputs, txouts, txfee, mint, txvldt, txcerts, txwdrls, txvote, txprop, txdonation, txup, txADhash, txNetworkId, curTreasury, txsize, txid, collateral, reqSigHash, and scriptIntHash.

**Delta:** The spec defines TxBody as a minimal 2-field product type (txins, txouts), while the implementation extends it with 18 additional fields covering fees, minting, validity intervals, certificates, withdrawals, governance votes/proposals, donations, updates, auxiliary data hash, network ID, treasury, transaction size, transaction ID, collateral inputs, required signer hashes, and script integrity hash. This is a significant structural divergence — the spec rule shown is likely from an earlier/simpl

**Implications:** The Python implementation must include all 20 fields from the Agda/Haskell implementation, not just the 2 fields from the abstract spec. The minimal spec definition is insufficient for conformance with the actual ledger. Every downstream rule that references TxBody fields (fee validation, minting policy checks, validity interval checks, collateral validation, governance, etc.) depends on these extra fields being present. Our Python TxBody dataclass must mirror the full record.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 91. d54b3905

**Era:** shelley

**Spec says:** When e = e_ℓ + 1 and ru = Nothing, the NEWEPOCH transition produces the SAME state as input (nes remains unchanged). No sub-transitions are invoked.

**Haskell does:** When e = lastEpoch + 1 and ru = nothing, the Haskell implementation still invokes the EPOCH sub-transition (_ ⊢ eps ⇀⦇ e ,EPOCH⦈ eps'), updating eps to eps'. The output state is ⟦ e , eps' , nothing ⟧ which differs from input ⟦ lastEpoch , eps , nothing ⟧ in both the epoch field (updated to e) and the epoch state (updated to eps').

**Delta:** The spec says the output state is identical to the input state (no-op). The Haskell implementation updates the lastEpoch to e and runs the EPOCH transition on the epoch sub-state, producing a potentially modified eps'. This is a substantive behavioral difference: the Haskell code does more work than the spec prescribes for the No-Reward-Update case.

**Implications:** The Python implementation must decide which semantics to follow. If following the spec literally, the state should be returned unchanged. If following the Haskell implementation, the EPOCH sub-transition must be invoked and lastEpoch updated even when ru=Nothing. This affects epoch boundary processing: the Haskell approach ensures epoch housekeeping (via EPOCH) always happens at epoch boundaries regardless of reward availability, while the spec approach would skip all epoch processing. The Haske

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 92. d5d92765

**Era:** shelley

**Spec says:** The DELPL transition rule Delpl-Deleg delegates delegation certificates (non-pool certificates) to the DELEG sub-transition, passing environment (slot, ptr, acnt) and updating only dstate while pstate remains unchanged. The full DELPL environment is (slot, ptr, pp, acnt).

**Haskell does:** No implementing Haskell code was provided for analysis. The existing test shows a DelegateeNotRegisteredDELEG error propagation path: DelplFailure wrapping DelegFailure wrapping DelegateeNotRegisteredDELEG, confirming the delegation path exists and errors propagate through DELPL → DELEG.

**Delta:** Cannot confirm implementation details without source code. The test reveals the error wrapping chain: AllegraApplyTxError → DelegsFailure → DelplFailure → DelegFailure → DelegateeNotRegisteredDELEG, which is consistent with the spec's delegation path through DELPL to DELEG.

**Implications:** Python implementation must: (1) route delegation certificates through DELEG sub-transition, (2) pass only (slot, ptr, acnt) to DELEG (not pp), (3) leave pstate unchanged when processing delegation certs, (4) propagate DELEG errors wrapped in DELPL failure context. Error wrapping hierarchy must match: DelplFailure(DelegFailure(specific_error)).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 93. d87cfe29

**Era:** shelley

**Spec says:** Pool-reReg rule: when hk is already in dom(poolParams), poolParams remains unchanged, fPoolParams is updated with right-biased union override {hk -> pool}, and retiring has hk removed from its domain. The only preconditions are (1) hk in dom(poolParams) and (2) poolCost(pool) >= minPoolCost(pp).

**Haskell does:** The Haskell implementation adds several additional checks beyond the spec: (1) After Alonzo hardfork, validates that the pool account address network ID matches the actual network ID (WrongNetworkPOOL). (2) After SoftForks.restrictPoolMetadataHash, validates metadata hash size. (3) After Conway hardfork, checks VRF key hash uniqueness — on re-registration, allows same VRF key or a fresh one not al

**Delta:** Three additional validation checks (network ID, metadata hash size, VRF key uniqueness) are enforced in the implementation that are not present in the Shelley-era spec rule. The state representation is richer (StakePoolState wrapping StakePoolParams with deposit/creation info, plus a psVRFKeyHashes map). On re-reg, the implementation also manages future VRF key hash entries (removing stale ones from previous re-registrations in the same epoch).

**Implications:** Python implementation must decide which era to target. For Shelley-era conformance, only the two spec preconditions matter. For Conway-era conformance, all three extra checks must be implemented. The VRF key hash tracking on re-registration is particularly complex — it requires maintaining a separate VRF key hash map and handling the case where a pool re-registers multiple times within the same epoch. The psStakePools entries use StakePoolState (not raw params), so the Python model needs an equi

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 94. db32f4cc

**Era:** shelley

**Spec says:** Property 11 (Pool Reaping): When a POOLREAP transition occurs at epoch e, all pools scheduled to retire at epoch e (retire set) must satisfy: (1) retire ≠ ∅, (2) retire ⊆ dom(getStPool(p)), (3) retire ∩ dom(getStPool(p')) = ∅, (4) retire ∩ dom(getRetiring(p')) = ∅. Retiring pools are removed from both stpools and retiring maps.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** No implementation found to compare against. The spec defines a critical invariant for the POOLREAP transition that must be implemented in Python.

**Implications:** The Python implementation must ensure that when pool reaping occurs at epoch boundary: (1) the retiring set for the current epoch is non-empty (the transition fires only when there are pools to reap), (2) all pools in the retire set were previously registered, (3) after reaping, none of the retired pools remain in the stake pool registry, and (4) none of the retired pools remain in the retiring schedule. Any deviation would leave ghost pool entries or stale retirement records.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 95. e0bdbcbb

**Era:** shelley-ma

**Spec says:** evalMPSScript (RequireAll ls) pid slot vhks txb spentouts = ∀ s' ∈ ls : evalMPSScript s' pid slot vhks txb spentouts. All sub-scripts must evaluate to True.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Missing implementation. Cannot verify whether the code correctly implements universal quantification (especially the vacuous truth case for empty lists) or correctly threads all parameters (pid, slot, vhks, txb, spentouts) to recursive calls.

**Implications:** Python implementation must ensure: (1) empty list returns True (vacuous truth), (2) all parameters are passed unchanged to each recursive evalMPSScript call, (3) result is the conjunction of all sub-script evaluations. Without reference Haskell code, we must rely solely on the spec for correctness validation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 96. e4de653a

**Era:** shelley

**Spec says:** canFollow checks all ps in range(pup): for all proposal sets in the range of the CURRENT proposals map (pup), every protocol version mapping pv↦v must satisfy pvCanFollow (pv pp) v. The condition is evaluated against the current proposals (pup), not the future proposals (fpup).

**Haskell does:** The Haskell implementation checks `allᵇ ¿ isViableUpdate pparams ¿¹ (range fpup)` — it evaluates the viability condition against the range of fpup (future proposals), not pup (current proposals). The pattern match destructures the state and only binds fpup, ignoring pup entirely for the check.

**Delta:** The spec checks viability of CURRENT proposals (pup) to decide whether to promote future proposals (fpup). The Haskell implementation checks viability of FUTURE proposals (fpup) to decide whether to promote them. This means: (1) if pup has invalid proposals but fpup is valid, spec clears both but Haskell promotes fpup; (2) if pup is valid but fpup has invalid proposals, spec promotes fpup but Haskell clears both.

**Implications:** For our Python implementation, we need to decide which behavior to follow. The spec and Haskell implementation disagree on WHICH map's proposals are checked. This is likely a spec vs implementation divergence where one or the other has a bug. Since the semantic intent is to check whether future proposals can follow the current protocol version before promoting them, the Haskell behavior (checking fpup) arguably makes more sense — you want to validate what you're about to promote. Our Python impl

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 97. e8dce8ec

**Era:** alonzo

**Spec says:** If a transaction is accepted but marked as paying fees only (phase-2 script validation failure), the only ledger state change is that collateral inputs are consumed and their value is moved to the fee pot. No other UTxO changes, no minting, and no other state changes occur.

**Haskell does:** In the IsValid False branch, the code does three things: (1) removes collateral inputs from UTxO and unions with collateral outputs (collOuts txBody) — this is a Babbage-era extension where collateral change outputs are created, (2) adds collateral fees (the ada balance difference) to the fee pot, and (3) updates instantStake by deleting the stake from consumed UTxO and adding stake from collatera

**Delta:** The spec description says 'inputs marked for paying fees are moved to the fee pot' implying all collateral input value becomes fees. The Babbage-era implementation actually supports collateral return outputs (collOuts), so only the *difference* between collateral inputs and collateral outputs goes to fees. Additionally, instantStake is updated (removing stake from consumed collateral inputs, adding stake from collateral outputs), which is an additional state change beyond what the simplified spe

**Implications:** Python implementation must: (1) support collateral return outputs (Babbage+), computing the new UTxO as collateral inputs removed then collateral outputs added; (2) compute collateral fees as the ada balance difference (collateral input ada minus collateral output ada), not the total collateral input value; (3) update instant stake tracking accordingly; (4) ensure no other state fields (deposits, donations, staking state, governance state) are modified.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 98. eb5ee450

**Era:** shelley

**Spec says:** The LEDGER rule applies DELEGS first (processing txcerts), then uses the *original* dpstate (not dpstate') to extract genDelegs and poolParams for the UTXOW environment. Specifically, genDelegs comes from the 5th component of dstate, and poolParams from the 1st component of pstate, both from the pre-transition dpstate.

**Haskell does:** No implementing code was provided for direct comparison. However, the spec description states that genDelegs and poolParams from the *updated* dpstate feed into UTXOW, which contradicts the inference rule notation where dpstate (not dpstate') is destructured. The extracted description says 'the results of DELEGS (specifically genDelegs and poolParams from the updated dpstate) feed into the UTXOW e

**Delta:** Ambiguity in the spec extraction: the formal inference rule destructures dpstate (pre-DELEGS state) to get genDelegs and poolParams for UTXOW, but the textual description claims the updated dpstate' feeds into UTXOW. This is a critical semantic difference — if poolParams or genDelegs change during DELEGS, the UTXOW transition would see different values depending on which interpretation is used. The formal notation should be authoritative (use pre-DELEGS dpstate).

**Implications:** Python implementation must carefully decide whether to use pre-DELEGS or post-DELEGS dpstate for extracting genDelegs and poolParams. Following the formal notation strictly, the pre-DELEGS dpstate should be used. This could matter when a transaction both registers a pool and tries to use that pool in the same transaction, or when genesis delegations change within the same transaction's certificates.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 99. ef76f493

**Era:** shelley

**Spec says:** After a key deregistration certificate (DCertDeRegKey) is applied via the delegation transition, the credential (hk = cwitness(c)) must be completely removed from: (1) the set of staking credentials (getStDelegs), (2) the domain of the rewards mapping (getRewards), and (3) the domain of the delegations mapping (getDelegations) in the resulting state d'.

**Haskell does:** No implementing Haskell code was found for this property.

**Delta:** No implementation exists to verify against. This is a ledger-level property that must be ensured by the DELEG transition rule for deregistration certificates. The property asserts complete cleanup of all delegation-related state for a deregistered key.

**Implications:** The Python implementation must ensure that when processing a stake key deregistration certificate, the key is removed from all three maps/sets: (1) the registered staking credentials set, (2) the rewards map, and (3) the delegations map. Partial removal (e.g., removing from staking credentials but leaving a rewards entry) would violate this invariant.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 100. f2b9155b

**Era:** alonzo

**Spec says:** stakeDistr computes stake distribution where: (1) stakeRelation combines UTxO stake (via inverse stakeCred_b and pointer address resolution via addrPtr∘ptr) with rewards stake (via inverse stakeCred_r), (2) activeDelegs = (dom(stdelegs)) ◁ delegations ▷ (dom(stpools)), i.e. delegations restricted to registered stake credentials AND delegatee pools in registered pools, (3) result = dom(activeDelegs

**Haskell does:** The Agda implementation computes stakeRelation as: m = mapˢ(λ a → (a, cbalance(utxo ∣^' λ i → getStakeCred i ≡ just a))) (dom rewards) ∪ |rewards|. This iterates over dom(rewards) rather than using pointer address resolution (addrPtr∘ptr inverse). The Haskell test implementation uses aggregateUtxoCoinByCredential which does handle pointers via ptrs', and activeDelegs filters by both membership in 

**Delta:** Three divergences: (1) The Agda implementation does not resolve pointer addresses - it only matches UTxO outputs by stake credential in dom(rewards), missing any UTxO locked to pointer addresses. (2) The Agda code uses dom(rewards) as the credential universe for UTxO scanning, while the spec uses the broader inverse of stakeCred_b (all base addresses in UTxO). (3) The activeDelegs computation in the Agda code appears to use stakeDelegs directly without the explicit range restriction to dom(stpoo

**Implications:** Python implementation must: (1) correctly resolve pointer addresses when computing stakeRelation - iterate UTxO and match both base address credentials and pointer-addressed credentials via the ptr map, (2) use the full UTxO credential extraction (not just dom(rewards)) for stake aggregation, (3) ensure activeDelegs is properly domain-restricted to registered credentials AND range-restricted to registered pools. If following the Agda code, pointer-addressed UTxO stake will be silently dropped.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 101. f3b8b91e

**Era:** byron

**Spec says:** Delegation activation change rule requires two preconditions: (1) vk_d ∉ range(dms) — the delegatee must not already be delegated to by any genesis key (injectivity), and (2) if vk_s ↦ s_p ∈ dws then s_p < s — the new slot must be strictly later than any previous delegation slot for the same source key. When both hold, dms is updated with {vk_s ↦ vk_d} via union-override-right and dws is updated w

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** No implementation exists to compare against. The rule must be implemented from scratch in Python, ensuring both preconditions and the union-override-right semantics are correctly captured.

**Implications:** The Python implementation must carefully handle: (1) the injectivity check on dms range (vk_d not already a value in dms), (2) the slot ordering check for existing entries in dws, (3) union-override-right semantics (existing entries for vk_s are overwritten), and (4) the rule should fail/not apply when either precondition is violated.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 102. f6c30cb3

**Era:** shelley

**Spec says:** The Deleg-Gen rule schedules a future genesis delegation by computing fdeleg = {(s', gkh) ↦ (vkh, vrf)} where s' = slot + StabilityWindow, and updating fGenDelegs via union-override-right (⋃⁺) with fdeleg. It also enforces preconditions: gkh must be in dom(genDelegs), the delegate vkh must not duplicate any other current or future delegate's cold key hash, and the vrf must not duplicate any other 

**Haskell does:** The provided Haskell code implements `adoptGenesisDelegs`, which is the adoption/activation side of genesis delegation — it processes future genesis delegations whose scheduled slot has arrived (s <= slot), selects the latest per genesis key, and merges them into genDelegs using Map.union (left-biased, meaning new delegations override existing ones). This is NOT the Deleg-Gen scheduling rule itsel

**Delta:** The provided Haskell code does not implement the Deleg-Gen transition rule. It implements the adoption of already-scheduled future genesis delegations (the TICK/epoch boundary logic). The actual Deleg-Gen rule — which validates the certificate, checks uniqueness of vkh and vrf, computes s' = slot + StabilityWindow, and inserts into fGenDelegs — must be implemented elsewhere (likely in the DELEG STS rule). The code we have is complementary but different functionality.

**Implications:** For our Python implementation, we need two distinct pieces: (1) The Deleg-Gen scheduling rule that validates DCertGen certificates and inserts into fGenDelegs with the uniqueness checks, and (2) The adoption logic (shown here) that at each slot/tick moves mature future delegations into genDelegs. The adoption logic uses left-biased Map.union (genDelegs' `union` genDelegs) which means new delegations override old ones — equivalent to the spec's union-override-right. The adoption also resolves con

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 103. faf4f105

**Era:** shelley

**Spec says:** txinsScript txins utxo = txins ∩ dom(utxo ▷ (Addr^script × Coin)) — a set-theoretic operation that filters inputs by checking if their UTxO entry has a script address (Addr^script). The function returns a set of TxIn.

**Haskell does:** getSpendingScriptsNeeded iterates over txBody inputs, looks up each in the UTxO map, extracts the address, calls getScriptHash to check if it's a script address, and if so returns (SpendingPurpose asIxItem, hash) — i.e., it returns the script hash paired with a spending purpose/index, not just the TxIn set. This is an Alonzo-era generalization that collects script hashes needed for spending, tagge

**Delta:** The spec defines txinsScript as returning a plain set of TxIn (the script-addressed inputs). The Haskell implementation (Alonzo era) returns a list of (ScriptPurpose, ScriptHash) pairs — it extracts the script hash from the address and pairs it with a SpendingPurpose indexed item. The semantic filtering (script vs non-script) is equivalent, but the return type carries additional information (script hashes and purpose tags) needed for Alonzo-era script validation. The Shelley-era spec's simple se

**Implications:** For a Python implementation targeting the Shelley-era spec, txinsScript should return a plain set of TxIn. If targeting Alonzo+, the implementation needs to also extract script hashes and tag them with spending purpose. The core filtering logic (is this a script address?) is the same in both cases; the difference is in what data is collected and returned.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 104. fe3a9e69

**Era:** shelley

**Spec says:** Pool-Reg rule: When hk is NOT in dom(poolParams), add {hk -> pool} to poolParams. fPoolParams and retiring remain unchanged. Only preconditions are: hk not in dom(poolParams) and poolCost(pool) >= minPoolCost(pp).

**Haskell does:** The Haskell implementation adds several checks beyond the spec: (1) After Alonzo hardfork, validates pool account address network ID matches actual network ID (WrongNetworkPOOL). (2) After soft fork, validates pool metadata hash size <= HASH size (PoolMedataHashTooBig). (3) After Conway hardfork, checks VRF key hash uniqueness across pools (VRFKeyHashAlreadyRegistered) and maintains a psVRFKeyHash

**Delta:** The implementation extends the spec with: (a) network ID validation for pool reward account, (b) metadata hash size validation, (c) VRF key hash uniqueness enforcement (Conway), (d) VRF key hash tracking state (psVRFKeyHashes). These are era-specific extensions not present in the Shelley-era formal spec rule. The core Pool-Reg logic (new registration path) matches the spec: poolParams is updated with the new mapping, fPoolParams and retiring are unchanged.

**Implications:** Python implementation must: (1) implement the core Pool-Reg logic matching the spec, (2) be aware that post-Alonzo eras require network ID checks on pool reward accounts, (3) be aware that Conway requires VRF key uniqueness checks, (4) handle both registration (new pool) and re-registration (existing pool) paths in the same certificate handler, (5) track pool deposit amount in the pool state.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

