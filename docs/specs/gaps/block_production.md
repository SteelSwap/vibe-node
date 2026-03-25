# Block Production — Critical Gap Analysis

**28 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. 00388d12

**Era:** multi-era

**Spec says:** Block production MUST be disabled while the node is not up to date (syncing/catching up to chain tip). It should only be enabled once the node considers itself caught up.

**Haskell does:** No implementing code was found in the provided codebase for this rule.

**Delta:** The rule about disabling block production while syncing has no identified implementing code. This logic is likely implemented in the consensus layer's forge loop (e.g., in Ouroboros.Consensus.Node or similar modules) via a 'CurrentSlot' or 'SyncState' check, but the specific code was not provided for analysis.

**Implications:** For the Python implementation, we must implement a sync-state gate that prevents the block forging pathway from executing when the node is not caught up. The exact definition of 'caught up' (e.g., how many slots behind is acceptable) needs to be determined from the Haskell consensus implementation (likely related to the 'MaxClockSkew' or a similar threshold). Without seeing the Haskell code, we risk implementing the wrong threshold or check mechanism.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. 06eb85d9

**Era:** shelley-ma

**Spec says:** evalMPSScript takes 6 inputs: (1) the script being evaluated, (2) the PolicyID of the asset being forged, (3) the current slot number, (4) a set of key hashes for MSig compatibility, (5) the transaction body, and (6) the inputs of the transaction as a UTxO finite map (TxIn → UTxOOut with addresses and values).

**Haskell does:** No implementing Haskell code was found for evalMPSScript.

**Delta:** The function evalMPSScript is specified but has no corresponding Haskell implementation provided. This means we cannot verify whether the implementation matches the spec's 6-argument signature, nor confirm the behavior of script evaluation against monetary policies.

**Implications:** The Python implementation must faithfully implement the 6-argument interface as described in the spec. Without a reference Haskell implementation to compare against, we must derive all behavior from the spec alone. Special attention is needed for: (a) ensuring the UTxO map correctly resolves TxIn to (address, value) pairs, (b) the interaction between MSig key hash sets and MPS script evaluation, and (c) correct threading of the current slot number for time-locked policies.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 3. 0e2f1955

**Era:** shelley

**Spec says:** The actual reward for a stake pool is calculated by poolReward, where p̄ = n / max(1, N̄) is the ratio of blocks produced by the pool to total blocks, and the result satisfies 0 ≤ ⌊p̄ · maxP⌋ ≤ maxP for all γ ∈ [0,1]. The reward is non-negative and bounded by maxPool.

**Haskell does:** The Haskell implementation computes maxP via maxPool (which uses a0, nopt, sigma, pledge ratio), then computes appPerf = mkApparentPerformance(decentralization, sigmaA, blocksN, blocksTotal), and finally poolR = floor(appPerf * maxP). If pledge > ostake (owner stake), maxP is set to 0 (mempty). The apparent performance calculation incorporates the decentralization parameter (ppDG), which modulates

**Delta:** The spec describes p̄ as simply n/max(1,N̄), but the Haskell code uses mkApparentPerformance which factors in the decentralization parameter (ppDG) and sigmaA (active stake fraction). The apparent performance may differ from the simple block ratio. Also, the pledge-exceeds-owner-stake check (pledge <= ostake guard) is an implementation detail not explicitly described in this particular spec excerpt.

**Implications:** Python implementation must: (1) use mkApparentPerformance with decentralization parameter rather than naive n/max(1,N̄), (2) implement the pledge <= ostake guard that zeroes maxP when pledge is not met, (3) ensure floor rounding matches rationalToCoinViaFloor semantics.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 4. 15c317bf

**Era:** shelley

**Spec says:** The slot leader schedule for an upcoming epoch is computed using a past snapshot from slot s_stakedist. The process: (1) compute stake distribution (amount of stake per pool), (2) create leader schedule by sampling pools weighted by their delegated stake, (3) retain the snapshot for reward calculation. Delegation must be accounted for: stake used is delegated stake held by pools, not individual ke

**Haskell does:** mkStakeDistrs aggregates stake by delegations, combining the snapshot stake with governance deposit stake (gaDepositStake govSt ds). The formula is: aggregateBy |delegations| (Snapshot.stake ss ∪⁺ gaDepositStake govSt ds). This means the stake distribution includes not just the delegated snapshot stake but also governance-related deposit stake (e.g., DRep deposits, proposal deposits). The test cod

**Delta:** The spec describes stake distribution as simply 'the amount of stake per stake pool' from the snapshot. The Haskell implementation additionally includes governance deposit stake (gaDepositStake) via a union-plus (∪⁺) operation with the snapshot stake before aggregation. This means pools' effective stake includes governance-related deposits that are not mentioned in the original Shelley spec text. This is likely a Conway-era enhancement.

**Implications:** The Python implementation must include governance deposit stake when computing the stake distribution for leader scheduling. Simply aggregating snapshot stake by delegations is insufficient in Conway era - governance deposits (from DReps, proposals, etc.) must be unioned into the stake before aggregation. The ∪⁺ operator (union-plus, which sums values for overlapping keys) must be correctly implemented.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 5. 247ef0b5

**Era:** shelley

**Spec says:** Six abstract functions are declared for block processing: bhHash (header hashing), bHeaderSize (header serialized size), bBodySize (body serialized size), slotToSeed (slot to seed conversion), prevHashToNonce (optional header hash to nonce), and bbodyhash (body hashing). These are abstract — their implementations are not specified in the ledger spec, only their type signatures.

**Haskell does:** No implementing Haskell code was found for these abstract functions in the provided codebase. In practice, these are implemented in the concrete Shelley/cardano-ledger modules (e.g., using CBOR serialization for sizes, Blake2b for hashes, and specific nonce construction logic), but the formal spec leaves them abstract.

**Delta:** These functions are left abstract in the spec and no single canonical Haskell implementation was provided for review. The concrete implementations live in downstream modules (e.g., cardano-ledger-shelley) and involve specific serialization formats (CBOR), hash algorithms (Blake2b-256), and nonce derivation logic. A Python implementation must choose concrete algorithms consistent with the Cardano chain.

**Implications:** Our Python implementation must provide concrete implementations for all six functions. Key risks: (1) bhHash and bbodyhash must use the exact same hash algorithm and serialization as the Haskell node (Blake2b-256 over CBOR-encoded data); (2) bHeaderSize and bBodySize must match CBOR serialized byte lengths; (3) slotToSeed and prevHashToNonce must match the specific Shelley-era nonce derivation (slotToSeed converts slot to big-endian bytes then wraps as Nonce, prevHashToNonce maps Nothing to Neut

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 6. 2c6f7e02

**Era:** multi-era

**Spec says:** A candidate chain is preferred over our current chain if (1) it is strictly longer than our current chain, AND (2) the intersection point is no more than k blocks away from the tip of our current chain. This is a binary comparison: one candidate chain vs. our current chain, checking fork depth from OUR tip only.

**Haskell does:** The Haskell implementation checks a consensus condition across ALL pairs of chains (not just candidate vs. current). It declares a consensus failure only when BOTH forks from the intersection exceed k (maxRollbacks), i.e., forkLen(tip1) > k AND forkLen(tip2) > k. This means if only one side of the fork exceeds k, it is still considered acceptable (the comment says 'that node can still recover by r

**Delta:** Three key divergences: (1) The spec checks candidate length > current length as the first condition; the Haskell code does not check relative chain length at all — it only checks fork depth. (2) The spec checks intersection distance from OUR tip only (one-sided); the Haskell code requires BOTH sides of the fork to exceed k before declaring failure (two-sided check). (3) The spec describes a pairwise candidate-vs-current comparison; the Haskell code checks all pairs of chains in a multi-chain set

**Implications:** A Python implementation following the spec literally would: (a) reject a candidate chain that is not strictly longer even if the fork is within k blocks, (b) reject a candidate if the fork from our tip exceeds k blocks regardless of the candidate's fork length, and (c) only compare candidate chains against our current chain, not all pairs against each other. The Haskell implementation is a monitoring/consensus-health check rather than a chain selection preference function. Our Python implementat

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 7. 2f962769

**Era:** multi-era

**Spec says:** Block production MUST be disabled while the node is not up to date (i.e., not fully synchronized with the network). Two rationales: (1) produced blocks would be discarded immediately as the node prefers the existing honest chain, and (2) such blocks may help an adversary.

**Haskell does:** No implementing code was found for this rule. The Haskell implementation likely enforces this in the block forging/leadership check pipeline (e.g., in Ouroboros.Consensus.NodeKernel or similar), but the specific code was not provided for analysis.

**Delta:** Cannot confirm implementation exists. The rule is a critical security/liveness property that must be enforced, but no code was located to verify compliance.

**Implications:** The Python implementation must include an explicit check that block production (leadership checks, block forging) is gated on a 'node is caught up' / 'synchronized' predicate. Without this, the node could waste resources producing blocks that will be discarded and could inadvertently aid adversaries.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 8. 3839214a

**Era:** alonzo

**Spec says:** produced slot pp stpools txb = ubalance(outs(slot, txb)) + coinToValue(txfee(txb) + deposits pp stpools (txcerts(txb))). The function takes a Slot parameter and uses it in computing outs. There is no donation term.

**Haskell does:** produced pp st txb = balance (outs txb) + inject (txb .txfee) + inject (newDeposits pp st txb) + inject (txb .txdonation). The function does NOT take a Slot parameter, does NOT pass slot to outs, and includes an additional txdonation term not present in the spec.

**Delta:** Two divergences: (1) The Haskell implementation includes a txdonation term (inject (txb .txdonation)) that is not in the spec rule. This reflects a later Conway-era addition for treasury donations. (2) The Haskell implementation drops the Slot parameter entirely — the spec passes slot to outs(slot, txb) but the Haskell code calls outs txb without a slot. The Slot parameter in the spec may have been used for time-locked output filtering in an earlier era and was later removed.

**Implications:** Python implementation must include the txdonation term to match the actual ledger behavior (Conway era). The Slot parameter can be omitted from the produced function signature, matching the Haskell implementation. When computing produced value, ensure txdonation (which defaults to Coin 0 for pre-Conway transactions) is added. The deposits computation uses newDeposits which may differ from the spec's deposits function in how it handles certificate deposit calculations.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 9. 48d03a9e

**Era:** shelley

**Spec says:** Three abstract VRF functions are defined: seedOp (Seed → Seed → Seed) for combining two seeds, vrf_T (SKey → Seed → T × Proof) for producing a VRF output and proof, and verifyVrf_T (VKey → Seed → Proof × T → Bool) for verifying a VRF proof. These are parameterized over an arbitrary type T.

**Haskell does:** No implementing code was found in the provided Haskell codebase for these abstract functions.

**Delta:** These are abstract/axiomatic functions in the spec (type-class style interface). The Haskell implementation likely delegates to a concrete VRF crypto class (e.g., Cardano.Crypto.VRF). Without seeing the concrete instantiation, we cannot verify alignment. The Python implementation must provide concrete implementations of all three functions.

**Implications:** The Python implementation must: (1) implement seedOp as a binary operation on seeds (likely XOR of 32-byte values based on Shelley conventions), (2) implement vrf_T using a concrete VRF scheme (likely ECVRF/Praos VRF) that produces both output and proof, (3) implement verifyVrf_T that validates a proof against a verification key and seed. The relationship vrf/verifyVrf must satisfy the correctness property: for any (sk, vk) key pair and seed s, verifyVrf_T(vk, s, vrf_T(sk, s)) == True.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 10. 4cdaab8c

**Era:** shelley

**Spec says:** f(s, σ) := (R / (1 + a₀)) · (σ' + s' · a₀ · (σ' - s' · (z₀ - σ') / z₀) / z₀) computes optimal pool rewards. If pledge is not honoured, f = 0. The formula uses σ (relative stake including owner pledge) and s (relative owner pledge stake), both clamped to z₀ = 1/k.

**Haskell does:** rewardOnePool checks pledge ≤ ownerStake (sum of all owner-delegated stake, not just pledge), computes maxPool (the spec formula) if pledge is honoured, then multiplies by apparentPerformance (based on blocks produced vs expected), floors the result, and distributes between owners (via rewardOwners) and members (via rewardMember). The test implementation mirrors this: it computes maxP via maxPool,

**Delta:** 1) The spec formula f(s,σ) gives the *optimal* (maximum possible) pool reward. The implementation multiplies this by apparentPerformance (n/N ratio adjusted by decentralization parameter d), which is not in the core formula but is part of the broader rewards calculation. 2) The spec uses s as relative pledge stake, but the implementation uses the actual owner-delegated stake (ownerStake) for pledge-honour checking and for the operator reward share calculation — owner stake can exceed pledge. 3) 

**Implications:** Python implementation must: (1) incorporate apparentPerformance multiplication on top of maxPool, (2) use ownerStake (total delegated by owners) for pledge check but pledge for the s parameter in maxPool, (3) floor the final pool reward after multiplication, (4) handle era-specific reward aggregation if targeting multiple eras, (5) filter zero rewards from final output.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 11. 4edb1d19

**Era:** alonzo

**Spec says:** minfee n pp tx = (a pp) · txSize(tx) + (b pp) + txscrfee n (prices pp) (txexunits (txbody tx)). The function takes three arguments: a natural number n (script count), protocol parameters pp, and a transaction tx. The fee is the sum of the size-based linear fee and the script execution fee (txscrfee). There is no reference-script cost component.

**Haskell does:** minfee pp utxo tx = pp.a * tx.body.txsize + pp.b + txscriptfee (pp.prices) (totExUnits tx) + scriptsCost pp (refScriptsSize utxo tx). The function takes three arguments: protocol parameters pp, a UTxO set utxo, and a transaction tx. It adds a fourth term 'scriptsCost pp (refScriptsSize utxo tx)' that accounts for reference script sizes. It also takes a UTxO parameter instead of a natural number n,

**Delta:** Two divergences: (1) The Haskell implementation adds an extra fee component 'scriptsCost pp (refScriptsSize utxo tx)' for reference scripts that is not present in the spec. This is a post-Alonzo addition (likely Conway era). (2) The function signature differs: spec takes a natural number n and passes it to txscrfee, while Haskell takes a UTxO set and does not pass n to txscriptfee. The txscriptfee in Haskell only takes prices and total execution units, not a script count.

**Implications:** For Python implementation: (1) If targeting the Alonzo-era spec exactly, do NOT include the scriptsCost/refScriptsSize term. If targeting a later era (Babbage/Conway), this additional term must be included. (2) The txscriptfee function signature should match whichever era is being implemented. The spec's 'n' parameter for txscrfee may relate to an earlier version where script count affected fee calculation. The Haskell code uses totExUnits which sums all execution units from the transaction, whi

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 12. 5bf61257

**Era:** shelley

**Spec says:** Every registered stake address has an associated account using account-style book-keeping. Rewards from multiple epochs accumulate in these accounts. The filtering partitions rewards into registered (account-based) and unregistered, with only registered credentials receiving reward updates.

**Haskell does:** filterAllRewards' partitions the rewards map by checking isAccountRegistered against the DState's unified account map. It also applies a secondary filter (filterRewards) based on protocol version to the registered partition, producing a 'shelleyIgnored' set. The function uses aggregateRewards which behaves differently depending on protocol version (pre/post Shelley treats duplicate reward types di

**Delta:** The spec describes simple accumulation into registered accounts, but the implementation has additional complexity: (1) a protocol-version-dependent filterRewards step that can ignore some rewards even for registered credentials (shelleyIgnored), and (2) aggregateRewards behaves differently across protocol versions. The spec does not mention era-specific reward filtering or the concept of ignored rewards for registered accounts.

**Implications:** Python implementation must replicate: (1) the partition by registration status using account membership check, (2) the protocol-version-dependent aggregateRewards logic, (3) the secondary filterRewards step that produces shelleyIgnored for registered credentials. Simply accumulating all rewards for registered accounts without era-aware filtering would diverge from the Haskell behavior in Shelley-era scenarios.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 13. 6d03e3b3

**Era:** shelley-ma

**Spec says:** Binary relations on Coin are extended pointwise to Value: v R w ⟺ ∀ pid aid, (v pid aid) R (w pid aid), where looking up an undefined (pid, aid) defaults to zero.

**Haskell does:** No implementing code was found for this rule.

**Delta:** No implementation to compare against. The key semantic requirement is that Value lookup defaults to 0 for undefined (pid, aid) pairs, meaning the relation must be checked over the union of all keys from both values (not just the intersection or keys present in one value). Any implementation must handle: (1) canonical treatment of zero entries vs missing entries, (2) checking all (pid, aid) pairs from both values.

**Implications:** Python implementation must ensure: (1) Value comparison methods (==, ≤, etc.) treat missing keys as having quantity 0; (2) the union of all (pid, aid) keys from both Values is checked, not just the intersection; (3) Values with explicit zero entries are considered equal to Values with those entries absent. This is critical for transaction validation where Value comparisons determine whether outputs cover inputs.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 14. 77b47fc8

**Era:** shelley

**Spec says:** The spec computes mRewards by iterating over all stake entries where hk ≠ poolHK (the pool's key hash), meaning it excludes only the pool operator's key hash from member rewards. The leader reward is computed via r_operator and assigned to poolRAcnt pool. The final result is filtered by addrs_rew (active reward accounts) via domain restriction (addrs_rew ◁ potentialRewards). The spec passes the po

**Haskell does:** The Haskell code computes memberRewards by excluding ALL pool owners (stakeDistr ∣ owners ᶜ), not just the single poolHK. It uses rewardOwners (not r_operator) for the combined owner reward assigned to pool.rewardAccount. It uses ∪⁺ (union with addition) to combine memberRewards and ownersRewards, rather than simple map union. Crucially, there is NO final domain restriction by addrs_rew — the Hask

**Delta:** 1) Member exclusion: Spec excludes only the single pool operator key (hk ≠ poolHK); Haskell excludes ALL pool owners from member rewards. 2) Owner reward: Spec uses r_operator for the leader; Haskell uses rewardOwners which aggregates all owner stakes. 3) Domain restriction: Spec filters final rewards by addrs_rew (active reward accounts); Haskell omits this filtering entirely (no addrs_rew parameter). 4) Reward combination: Spec uses simple map union (∪); Haskell uses ∪⁺ (additive union). 5) σ 

**Implications:** For Python implementation: (1) Need to decide whether to follow spec (exclude only operator) or Haskell (exclude all owners) for member rewards — the Haskell approach is likely the intended on-chain behavior. (2) The addrs_rew filtering may happen at a higher level in Haskell but must be implemented somewhere. (3) Use additive union (∪⁺) when combining member and owner rewards to handle the case where an owner might also appear in member rewards. (4) Apply clamping to relative stake values to en

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 15. 89a73a8e

**Era:** shelley

**Spec says:** The apparent performance uses the total number of blocks produced in non-OBFT slots as the denominator (\overline{N}). During the transition phase, OBFT blocks are excluded from the total block count to avoid diluting pool performance metrics.

**Haskell does:** The implementation uses a threshold on the decentralization parameter d: when d >= 0.8 (meaning 80%+ federated), it returns a flat performance of 1 for all pools (with non-zero stake), bypassing the block-counting formula entirely. When d < 0.8, it computes beta/sigma where beta = blocksN / max(1, blocksTotal). The filtering of OBFT blocks from blocksTotal is assumed to happen upstream (in the cal

**Delta:** The spec describes conceptually filtering out OBFT blocks from the total count. The Haskell implementation takes a two-pronged approach: (1) when d >= 0.8, it entirely skips the calculation and returns 1 (generous to all pools during heavy federation), and (2) when d < 0.8, it trusts that the caller already passed in a blocksTotal that excludes OBFT blocks. The d >= 0.8 threshold and the flat return of 1 are implementation details not explicitly stated in the spec excerpt. The Python implementat

**Implications:** Python implementation must: (1) implement the d < 0.8 threshold check, (2) return 1 when d >= 0.8 and sigma > 0, (3) return 0 when sigma == 0, (4) use max(1, blocksTotal) to guard against division by zero, and (5) ensure the blocksTotal passed to this function already excludes OBFT blocks (matching whatever upstream filtering Cardano does). The Rational arithmetic (exact fractions) should be preserved to avoid floating-point divergence.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 16. 8b8b5ad2

**Era:** shelley

**Spec says:** The reward function computes `results` as a map from pool KeyHash to per-pool reward maps (AddrRWD ↦ Coin), then unions all per-pool reward maps together with ⋃. The pdata is constructed by joining poolParams and blocks on the same key (hk). rewardOnePool receives parameters: pp, R, n, N̄, hk, p, s, tot, addrs_rew.

**Haskell does:** The Haskell implementation (1) computes both `Σ_/total` (sigma = pool_stake/total) and `Σ_/active` (sigmaA = pool_stake/active_stake) and passes both to rewardOnePool, whereas the spec only passes `s` (the stake distribution) and `tot`. (2) The results map is keyed by (KeyHash × Credential) pairs rather than just KeyHash, and uses `uncurryᵐ` to flatten the per-pool reward maps into a single flat m

**Delta:** Multiple divergences: (a) sigma and sigmaA are computed and passed separately in Haskell but spec only shows stake distribution s and tot; (b) reward aggregation uses aggregateBy (summation) rather than simple union, which matters when the same credential appears in multiple pool reward maps; (c) hardfork-conditional logic for Allegra (aggregated vs last-writer-wins) and Babbage (forgo reward prefilter) is not in the spec; (d) clamping of ratios not in spec.

**Implications:** Python implementation must: (1) compute both sigma (pool_stake/total_stake) and sigmaA (pool_stake/active_stake) and pass both to rewardOnePool; (2) use summation-based aggregation (not simple dict merge) when combining per-pool reward maps, to correctly handle credentials delegating to or receiving rewards from multiple pools; (3) implement era-dependent behavior for Allegra and Babbage hardforks; (4) clamp sigma/sigmaA ratios to [0,1] range.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 17. 97d1f510

**Era:** shelley

**Spec says:** The URL field in a stake pool registration certificate must be at most 64 bytes in length.

**Haskell does:** The PoolMetadata type holds a Url (pmUrl) and a ByteArray (pmHash), but the shown code does not include an explicit length validation check on the URL. The Url type or its deserialization/construction elsewhere may enforce the 64-byte limit, but it is not visible in this snippet.

**Delta:** The 64-byte URL length constraint is not visible in the PoolMetadata data type definition itself. It is likely enforced either in the Url newtype's smart constructor, its CBOR deserialization instance, or in the ledger validation rules — but this is not confirmed from the provided code alone.

**Implications:** The Python implementation must explicitly enforce the 64-byte maximum length on the pool metadata URL at both construction time (validation) and deserialization time. The byte-length check must measure raw bytes (not Unicode characters). Without explicit enforcement, oversized URLs could slip through and produce invalid transactions.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 18. 9826a26c

**Era:** alonzo

**Spec says:** Addition on the Value type is defined pointwise over PolicyID and AssetID: (m1 + m2) pid aid := (m1 pid aid) + (m2 pid aid), where missing entries default to 0. Two Values that differ only by zero-quantity tokens are considered equal.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** No implementation to compare against — the spec rule for Value addition is unimplemented or the code was not located.

**Implications:** The Python implementation must define Value addition as pointwise integer addition over the (PolicyID, AssetID) key space, treating absent keys as 0, and must treat Values that differ only in zero-quantity entries as equal. Without a reference implementation, we must test purely against the spec semantics.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 19. bbd1518b

**Era:** shelley

**Spec says:** When multiple blocks exist for the same slot from the same stake pool, each signed with a valid operational key certificate, the block whose operational key certificate has the highest counter value takes precedence. This is a tie-breaking mechanism among competing blocks from the same pool in the same slot.

**Haskell does:** The SelectView Ord instance compares first by svBlockNo (block number), then falls back to svTiebreakerView for tie-breaking. The actual tiebreaker logic is delegated to the Ord instance of TiebreakerView for the specific protocol 'p'. The operational certificate counter comparison is not directly visible in this code snippet — it depends on how TiebreakerView is defined for the concrete protocol 

**Delta:** The spec describes a narrow rule: same slot, same pool, highest operational cert counter wins. The Haskell implementation abstracts this into a generic two-level comparison (block number, then tiebreaker view). The operational cert counter logic is hidden inside the protocol-specific TiebreakerView type. Without seeing the Praos-specific TiebreakerView definition, we cannot confirm the cert counter is the actual tiebreaker criterion. Additionally, the same-slot and same-pool preconditions from t

**Implications:** For the Python implementation: (1) We need to ensure chain selection first compares by block number, then uses a protocol-specific tiebreaker. (2) For Praos, the tiebreaker must compare operational certificate counters (higher wins). (3) The same-slot, same-pool preconditions may be implicitly satisfied by the context in which this comparison is invoked, but we should verify this. (4) We must find and replicate the Praos-specific TiebreakerView to confirm the cert counter is used.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 20. bdce7c03

**Era:** shelley

**Spec says:** For each registered stake address, the rewards calculated are added to the balance of the associated reward account.

**Haskell does:** The implementation uses applyRUpdFiltered which partitions rewards into registered, unregistered, and 'shelley-ignored' (frShelleyIgnored) categories. Only registered rewards are applied. Unregistered and shelley-ignored rewards are filtered out and reported via events but not credited to any account.

**Delta:** The spec describes a simple addition of rewards to registered accounts. The Haskell implementation has additional complexity: (1) it filters rewards through applyRUpdFiltered which distinguishes between registered, unregistered, and shelley-ignored credentials, (2) it enforces a conservation invariant (dt + dr + totalRewards + df == 0) via assertion, and (3) rewards can come from multiple sources per address and must be aggregated via sumRewards which is protocol-version-aware. The shelley-ignor

**Implications:** Python implementation must: (1) correctly filter rewards to only apply to currently-registered stake addresses at the time of the reward update, (2) handle the case where credentials were deregistered between reward calculation and application, (3) aggregate multiple reward entries per credential (member + leader rewards) using protocol-version-aware summing, (4) maintain the conservation invariant across treasury delta, reserves delta, rewards, and fee delta.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 21. c0ca6957

**Era:** shelley-ma

**Spec says:** evalMPSScript takes six specific inputs: (1) the script, (2) PolicyID of the asset being forged, (3) current slot number, (4) a set of key hashes for MSig-as-MPS usage, (5) the transaction body, and (6) the transaction inputs as a UTxO finite map (TxIn → UTxOOut with addresses and values).

**Haskell does:** No implementing Haskell code was found for evalMPSScript.

**Delta:** The implementation of evalMPSScript is missing entirely. Without code, we cannot verify that all six inputs are used correctly, that MSig scripts properly consult the key hash set, that the slot number is used for timelock evaluation, or that the UTxO map is threaded through to the script evaluation context.

**Implications:** The Python implementation must ensure evalMPSScript accepts exactly these six inputs with the correct types. Special attention is needed for: (1) the key hash set being used when MSig scripts serve as MPS scripts, (2) the UTxO map type being TxIn → (Addr, Value) not just TxIn → TxOut, and (3) the slot number being available for time-based script conditions. Without a reference implementation, the Python code must be built directly from the spec, increasing the risk of misinterpretation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 22. cbac7bea

**Era:** shelley

**Spec says:** r_member(f̂, pool, t, σ) = floor((f̂ - c) · (1 - m) · t / σ) when f̂ > c, else 0. The computation is straightforward: subtract cost, multiply by (1-margin), multiply by member's relative stake fraction (t/σ).

**Haskell does:** The Haskell implementation computes (fromℕ rewards - fromℕ cost) * ((1 - margin) * ratioStake) where ratioStake = memberStake ÷₀ stake, then applies floor and posPart. Two differences: (1) It groups the multiplication as (rewards - cost) * ((1 - margin) * ratioStake) rather than (rewards - cost) * (1 - margin) * (t / σ), which due to floating-point/rational arithmetic ordering could yield differen

**Delta:** The Haskell code applies posPart (clamp to non-negative) after floor, which is defensive but not in the spec. The multiplication grouping ((1-m) * (t/σ)) vs spec's ((1-m) * t / σ) could cause subtle rounding differences in rational arithmetic. The ÷₀ operator handles division by zero gracefully (returns 0) whereas the spec constrains σ to UnitIntervalNonNull (non-zero).

**Implications:** Python implementation should: (1) apply the same defensive posPart/max(0, ...) after floor, (2) ensure multiplication ordering matches Haskell for consistency, (3) handle the σ=0 edge case gracefully even though the spec says σ is non-zero. When using Python's Fraction or Decimal, verify rounding matches Haskell's floor behavior.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 23. ce28e7c9

**Era:** shelley

**Spec says:** Active stake is stake correctly delegated to a non-retired pool. The normalization base must be explicitly chosen between active and total stake when computing stake fractions.

**Haskell does:** sumAllActiveStake folds over the ActiveStake map summing all entries, but applies a `nonZeroOr knownNonZeroCoin @1` fallback that clamps the result to a minimum of 1 lovelace when the map is empty. Additionally, entries in the ActiveStake map are NonZero values (enforced by the swdStake type), meaning zero-stake entries are structurally excluded.

**Delta:** The spec does not mention a minimum floor of 1 lovelace for active stake; this is an implementation guard to prevent division-by-zero when active stake is used as a denominator in stake fraction calculations. The NonZero constraint on individual stake entries is also an implementation-level invariant not explicitly stated in the spec. A Python implementation that allows zero active stake without the floor would cause division-by-zero errors in leader election and reward calculations.

**Implications:** The Python implementation must (1) ensure sumAllActiveStake returns at least 1 lovelace (Coin) even when no stake is delegated, to prevent division by zero, and (2) ensure individual stake entries in the active stake distribution are always positive (non-zero). Failing to replicate the floor guard would cause runtime errors in downstream stake fraction computations.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 24. d8185e8b

**Era:** multi-era

**Spec says:** Blocks cannot influence the active stake distribution until some time in the future, ensuring fork resistance by preventing attackers from manipulating the leadership schedule near a fork intersection point.

**Haskell does:** No implementing code was provided for analysis. The Cardano Haskell implementation is expected to enforce a two-epoch lag via the mark/set/go snapshot rotation mechanism in the ledger state, but this could not be verified.

**Delta:** Cannot confirm implementation matches spec due to missing code. The spec describes a critical security invariant (stake distribution lag for fork resistance) but no corresponding implementation code was provided for review.

**Implications:** The Python implementation MUST enforce the same snapshot lag mechanism (typically two epochs in Praos). If the lag is incorrect (too short or absent), an attacker could manipulate their stake to gain disproportionate leader election probability on a private fork, breaking the chain density argument that underpins Ouroboros Praos security. The mark/set/go snapshot rotation must be faithfully replicated.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 25. e5addf0b

**Era:** shelley

**Spec says:** The probability P(X >= k) is computed where X ~ BetaBinomial(2k, a+1, b+1), using Bayes' Prior B(1,1) as a uniform prior. The parameters a (faithfully created slots) and b (missed slots) are shifted by +1 to incorporate the prior.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** No implementation exists to verify against. Key areas of potential divergence include: (1) whether the +1 prior shift is correctly applied to both a and b, (2) whether the number of trials is correctly set to 2k rather than k, (3) the correct computation of the survival function P(X >= k) rather than the CDF P(X <= k), and (4) the sufficiency threshold comparison (e.g., > 1 - 1e-10).

**Implications:** The Python implementation must carefully match the parameterization: n=2k trials, alpha=a+1, beta=b+1. scipy.stats.betabinom can be used with sf(k-1) to compute P(X >= k). The +1 shift from the uniform prior and the 2k trial count are the most likely sources of off-by-one bugs.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 26. e95c89ae

**Era:** multi-era

**Spec says:** A node will refuse to produce a new block if the slot distance between the new block and the previous block on the chain exceeds the stability window (3k/f slots). If all nodes are unable to produce blocks for a period exceeding the stability window, the system halts and cannot resume.

**Haskell does:** No implementing production code was found. The Haskell test suite has a property test (prop_downtime) that simulates downtime using genesis test infrastructure with 1-4 chains, LoE/LoP/CSJ enabled, a downtime of 11 slots, and a DowntimeWithSecurityParam points generator. The test verifies behavior when a node is shut down and restarted, checking that the chain selection and peer scheduling handle 

**Delta:** No production implementation code was provided to compare against the spec. The Haskell test uses a specific downtime value of 11 slots and DowntimeWithSecurityParam to generate point schedules that create gaps around the security parameter boundary. The test infrastructure (genChains, uniformPoints, ensureScheduleDuration, theProperty) is opaque — the exact assertions in theProperty are not visible but likely verify that the node either correctly resumes or correctly halts depending on whether 

**Implications:** Python implementation must enforce the stability window check: refuse block production when slot gap > 3k/f. The test must verify both the rejection case (gap exceeds window) and the acceptance case (gap within window). The Haskell test's DowntimeWithSecurityParam generator creates downtime scenarios calibrated to the security parameter, which we need to replicate.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 27. eba3463e

**Era:** shelley-ma

**Spec says:** The transaction body contains a 'forge' field of type Value for minting/burning tokens. Ada cannot be forged. Administrative fields are unaffected by forging.

**Haskell does:** No implementing Haskell code was found for the forge field validation logic itself. The test (testMint) only constructs a MultiAsset with a single policy and asset with quantity 2, but does not test negative quantities (burning), Ada exclusion from minting, or administrative field isolation.

**Delta:** The spec defines several constraints (Ada cannot be forged, admin fields unaffected, positive = mint, negative = burn) but no implementation code was provided to verify these constraints are enforced. The existing Haskell test only covers the positive minting case with a trivial script.

**Implications:** Python implementation must enforce: (1) Ada (empty policy ID) cannot appear in the mint/forge field, (2) the mint field uses Value/MultiAsset type supporting both positive and negative quantities, (3) administrative fields (fee, deposits, etc.) remain Ada-only and unaffected by the mint field. Without reference implementation code, we must rely on spec-driven testing to ensure correctness.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 28. fe11bfd3

**Era:** shelley

**Spec says:** The content hash ensures metadata integrity: metadata retrieved from a URL or proxy must match the on-chain content hash. This prevents forged metadata from being displayed. The spec implies an active verification step where retrieved metadata is checked against the hash.

**Haskell does:** The PoolMetadata data type stores pmUrl and pmHash as fields but the shown code is purely a data declaration. It does not contain any verification logic that computes a hash of retrieved metadata and compares it to pmHash. The actual verification must happen elsewhere (likely in the chain validation or client-side code), but it is not present in this snippet.

**Delta:** The data type definition alone does not enforce the integrity invariant described in the spec. The hash is stored but no verification function is shown. A Python implementation must ensure there is an explicit verification step that computes SHA256 of fetched metadata and compares it against the stored hash — this cannot be left as just a stored field.

**Implications:** In our Python implementation, we must: (1) store the metadata hash alongside the URL in the PoolMetadata equivalent, (2) implement an explicit verification function that fetches metadata and checks SHA256(content) == stored_hash, and (3) ensure this check is invoked at the appropriate point (e.g., when displaying pool info or during off-chain metadata aggregation). Without seeing the Haskell verification call site, we should look for it in the ledger validation or node client code to ensure we r

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

