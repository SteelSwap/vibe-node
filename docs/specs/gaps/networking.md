# Networking — Critical Gap Analysis

**67 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. 004772a1

**Era:** multi-era

**Spec says:** When any mini-protocol terminates, the inbound governor restarts the responder and updates internal state. Two cases: (1) clean termination → restart responder; (2) error → multiplexer closes, connection thread exits, inbound governor forgets connection (MuxTerminated). The inbound governor does not notify the connection manager about a terminating responder.

**Haskell does:** The provided `runResponder` function only shows how a single responder is run on the mux. It uses `tryJust` to catch synchronous exceptions (letting async exceptions propagate). It dispatches based on whether the mini-protocol is ResponderProtocolOnly or InitiatorAndResponderProtocol. However, the restart logic and the distinction between clean termination vs error (triggering MuxTerminated) is NO

**Delta:** The provided code only covers the invocation of a single responder run, not the restart-on-termination or forget-on-error logic described in the spec. The critical branching (clean termination → restart vs error → MuxTerminated/forget connection) is implemented elsewhere, likely in the main inbound governor event loop. The exception filtering (tryJust excluding async exceptions) is consistent with the spec's statement that errors in the multiplexer cause it to close, but the actual state transit

**Implications:** A Python implementation must: (1) implement a wrapper around responder execution that catches only synchronous/recoverable errors; (2) on clean termination, automatically restart the responder and update the STM-like tracking state; (3) on error, trigger a MuxTerminated-equivalent path that forgets the connection; (4) NOT notify the connection manager when a responder mini-protocol terminates. The restart loop and error-vs-termination branching must be implemented at a higher level than the sing

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. 0153ea6c

**Era:** multi-era

**Spec says:** When requestOutboundConnection is called and the connection is in TerminatingState, the call blocks until the connection reaches TerminatedState, then restarts the connection process from the initial state.

**Haskell does:** No implementing Haskell code was provided for analysis.

**Delta:** Cannot verify implementation correctness — no code available to compare against the spec rule.

**Implications:** The Python implementation must ensure that requestOutboundConnection correctly blocks (awaits) when the connection is in TerminatingState, waits for the transition to TerminatedState, and then re-initiates the connection from the initial state. Without reference implementation code, we must rely solely on the spec for correctness.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 3. 027fed42

**Era:** multi-era

**Spec says:** The Ledger kind defines two associated type families: AuxLedgerEvent l (auxiliary events produced during ledger state transitions) and LedgerErr l (the error type for ledger rule failures), both parameterized by a ledger type l.

**Haskell does:** No implementing Haskell code was found for analysis.

**Delta:** Cannot verify whether the Python implementation correctly defines and uses these associated type families since no Haskell reference implementation was provided. The spec requires that any Ledger instance must define both AuxLedgerEvent and LedgerErr as associated types.

**Implications:** The Python implementation must ensure that: (1) every concrete ledger type defines both an auxiliary event type and an error type, (2) the error type is used consistently in ledger rule failure paths, and (3) auxiliary events are emitted during state transitions. Without reference code, we must test against the spec directly.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 4. 02ca84cb

**Era:** multi-era

**Spec says:** The node-to-node protocol consists of exactly three mini-protocols: chain-sync, block-fetch, and tx-submission.

**Haskell does:** The NodeToNodeProtocols data type includes five mini-protocols: chain-sync, block-fetch, tx-submission, keep-alive, and peer-sharing.

**Delta:** The Haskell implementation includes two additional mini-protocols (keepAliveProtocol and peerSharingProtocol) beyond what the spec describes. The spec enumerates only three mini-protocols, but the implementation has evolved to include keep-alive (for connection liveness detection) and peer-sharing (for peer discovery) as mandatory fields in the protocol bundle.

**Implications:** A Python implementation that strictly follows the spec would only implement three mini-protocols and would fail to interoperate with real Cardano nodes that expect keep-alive and peer-sharing negotiation. The Python implementation must include keep-alive and peer-sharing mini-protocols to be compatible with the actual network. The spec appears to be outdated relative to the implementation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 5. 06d60826

**Era:** shelley

**Spec says:** A stake pool retirement certificate contains (1) the public key hash H(vk_pool) of the pool, and (2) the epoch number starting from which the pool will cease to operate. It requires a witness for the pool key sk_pool only.

**Haskell does:** The RetirePoolTxCert pattern matches on KeyHash StakePool and EpochNo, which directly corresponds to the spec. The Haskell test poolRetirement checks a property poolRetirementProp that validates the retirement epoch is within bounds (currentEpoch to currentEpoch + maxEpoch as defined by the ppEMax protocol parameter). The spec does not explicitly mention the eMax bound in this section, but the led

**Delta:** The spec description does not mention the eMax protocol parameter constraint on the retirement epoch, but the Haskell implementation and tests enforce that the retirement epoch must satisfy: currentEpoch < retireEpoch <= currentEpoch + eMax. This is an implicit ledger rule not stated in the certificate description.

**Implications:** The Python implementation must enforce the eMax bound on the retirement epoch when validating retirement certificates in transaction processing. Simply storing the two fields is not sufficient for full validation; the retirement epoch range check must also be implemented.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 6. 07982393

**Era:** conway

**Spec says:** LEDGERS applies LEDGER repeatedly for each transaction in a list of transactions. No mention of transaction indices being passed to each LEDGER invocation.

**Haskell does:** The implementation zips the transaction list with [minBound..] to produce incrementing transaction indices (TxIx), starting from minBound (which is 0 for Word32/Word16). Each LEDGER call receives its positional index via LedgerEnv. It also passes 'Just epochNo' rather than a plain epochNo, and uses strict left fold (foldM with bang pattern on accumulator).

**Delta:** The spec describes simple repeated application of LEDGER, but the implementation adds: (1) transaction index tracking via zip [minBound..], where each transaction receives its sequential position index; (2) the epoch number is wrapped in Just (Maybe type) in the LedgerEnv; (3) strict evaluation via bang pattern on the accumulator state. The transaction index is an implementation detail not mentioned in the abstract spec rule.

**Implications:** Python implementation must: (1) zip transactions with indices starting from 0 (matching minBound for the TxIx type) and pass the index to each LEDGER call; (2) wrap epoch number in Optional/Maybe when constructing the ledger environment; (3) ensure sequential (left-fold) processing with each step's output feeding the next step's input. The strictness bang pattern is a Haskell-specific optimization and not relevant to Python.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 7. 07997f1d

**Era:** conway

**Spec says:** For CC voters: 'just c ∈ range (gState .ccHotKeys)' — the credential c must appear wrapped in 'just' (i.e., the Maybe/Optional value must be 'Just c', not 'Nothing') in the range of the ccHotKeys mapping. This distinguishes active committee hot keys from resigned ones (mapped to Nothing).

**Haskell does:** No implementing Haskell code was found to verify. The implementation may or may not correctly handle the 'just c' (Some vs None) distinction for CC hot keys.

**Delta:** Without implementation code, we cannot verify that the CC check properly requires 'Just c' in the range rather than merely checking that c appears anywhere in ccHotKeys (e.g., as a domain key, or ignoring the Just/Nothing distinction). The 'just c' wrapping is a subtle but critical detail — a resigned CC member (mapped to Nothing) should NOT count as registered.

**Implications:** The Python implementation must ensure: (1) CC registration checks that Just(credential) is in the VALUES of ccHotKeys, not the keys; (2) Nothing entries in ccHotKeys (resigned members) do not count as registered; (3) SPO registration only accepts KeyHashObj credentials, rejecting ScriptHashObj even if the hash matches; (4) DRep registration checks domain membership of the dreps map.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 8. 09983c54

**Era:** shelley

**Spec says:** The spec describes a hot/cold key delegation scheme where: (1) a pool is registered with cold key vk_pool, (2) sk_pool signs an operational certificate C delegating to hot key vk_hot, (3) blocks signed with sk_hot are valid if C is in the header, (4) key rotation is possible by issuing a new certificate C' to a new hot key.

**Haskell does:** The Haskell test code only creates a cold key pair (alicePoolColdKeys) from a deterministic seed (RawSeed 0 0 0 0 1) using mkKeyPair. No implementation of operational certificate creation, block header validation with opcert inclusion, or key rotation logic was provided.

**Delta:** No implementing code was found for the full hot/cold key lifecycle (opcert creation, block header validation requiring opcert, key rotation with counter monotonicity). Only the cold key pair generation helper exists in the test suite.

**Implications:** The Python implementation must implement the full hot/cold key delegation chain: (1) deterministic key pair generation compatible with Haskell's mkKeyPair/RawSeed, (2) operational certificate structure and signing, (3) block header validation that checks both the opcert and the hot key block signature, (4) key rotation with monotonically increasing counters. Without the Haskell implementation code, we must rely on the spec and the Shelley formal spec (especially the OCert data type with its kes_

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 9. 0a3df59a

**Era:** shelley

**Spec says:** An operational key certificate specifies a transfer of stake rights from a cold stake pool verification key vk_pool to a hot verification key vk_hot. The certificate is included in the message (e.g., block header), and the message itself is signed with the corresponding hot signing key sk_hot.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** No implementation exists to compare against. The spec defines the structure and usage of operational key certificates (OpCert) linking cold pool keys to hot keys, with the hot key used to sign messages (block headers).

**Implications:** The Python implementation must ensure: (1) the OpCert data structure contains both vk_pool and vk_hot, (2) the certificate is embedded in block headers, (3) block header signatures are verified against vk_hot (not vk_pool), and (4) the chain of trust from vk_pool -> OpCert -> vk_hot -> signature is correctly validated.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 10. 10b5da6b

**Era:** shelley

**Spec says:** If a stake pool's reward address (A_{s,reward}) is unregistered, the pool operator cannot receive rewards. Any rewards due to the operator are sent back to the reserves. However, stake pool members (delegators) still receive their usual rewards.

**Haskell does:** No implementing Haskell code was provided for analysis. The logic is likely embedded in the reward calculation/distribution functions (e.g., in Shelley.Spec.Ledger.Rewards or similar modules) but was not surfaced for this review.

**Delta:** Cannot confirm whether the Haskell implementation correctly handles the unregistered reward address case — specifically whether operator rewards are redirected to reserves and delegator rewards remain unaffected. No code was available to verify.

**Implications:** The Python implementation must explicitly check the registration status of the pool's reward address during reward distribution. If unregistered: (1) operator rewards (leader rewards) must be computed but redirected to reserves, (2) delegator (member) rewards must be distributed normally, (3) the total reward pot accounting must balance (delegator rewards + reserves increment = total pool reward).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 11. 16548b5b

**Era:** conway

**Spec says:** refScriptsSize computes the total size of all reference scripts by collecting refScripts tx utxo (which may include duplicates), mapping scriptSize over each, and summing the results. The result is a natural number representing total byte size.

**Haskell does:** getReferenceScripts builds a Map (via Map.fromList) from a non-distinct list of reference scripts. Map.fromList deduplicates by key, so if multiple UTxO inputs reference the same script (by script hash), only one copy is retained. The total size computation downstream would therefore count each distinct script only once, whereas the spec's refScripts may include duplicates depending on how it is d

**Delta:** The Haskell implementation deduplicates reference scripts by converting to a Map (Map.fromList keeps the last value for duplicate keys), while the spec sums over the full list returned by refScripts. If refScripts in the spec can return duplicate scripts (e.g., when two inputs reference the same script), the spec would sum their sizes multiple times, but the Haskell code would count each script only once. Alternatively, if refScripts in the spec is also defined to deduplicate, there is no gap — 

**Implications:** For our Python implementation, we need to determine whether refScripts is meant to return a set (deduplicated) or a list (with possible duplicates). If we follow the Haskell implementation, we should deduplicate reference scripts by script hash before computing the total size. If we follow the spec literally (sum over all reference scripts), duplicates would be counted multiple times, leading to a larger refScriptsSize. This could affect transaction validation if refScriptsSize is compared again

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 12. 18cc2f3d

**Era:** shelley

**Spec says:** minfee pp tx = (a pp) · txSize tx + (b pp) — the minimum fee is a simple linear function of transaction size with two protocol parameters: a per-byte fee coefficient and a fixed constant.

**Haskell does:** The Haskell implementation adds two extra terms beyond the spec's linear formula: (1) txscriptfee (pp.prices) (totExUnits tx) — a fee for script execution units based on memory and step prices, and (2) scriptsCost pp (refScriptsSize utxo tx) — a cost for reference scripts based on their total size. The function also takes a UTxO parameter not present in the spec signature.

**Delta:** The spec defines minfee as a two-term linear function (a*txSize + b), but the Haskell implementation (post-Alonzo) adds script execution fee and reference script cost terms. The function signature also gains a 'utxo' parameter. This reflects the evolution from Shelley-era spec to Alonzo/Babbage eras where Plutus scripts introduce additional fee components.

**Implications:** The Python implementation must include all four fee components for Alonzo+ eras: (1) per-byte fee × tx size, (2) fixed fee, (3) script execution unit fee (prices · exunits), and (4) reference script size cost. The UTxO must be passed to compute reference script sizes. For pre-Alonzo eras, only the original two-term formula applies.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 13. 1984cfdc

**Era:** multi-era

**Spec says:** The inbound protocol governor always starts/restarts all mini-protocols using the StartOnDemand strategy. When the multiplexer detects ingress traffic on responder protocols, a PromotedToWarm^Duplex_Remote transition is triggered via promotedToWarmRemote. This describes a multi-step process: StartOnDemand configuration, traffic detection by the multiplexer, and then the state transition call.

**Haskell does:** The Haskell implementation of promotedToWarmRemote is a simple composition: icmPromotedToWarmRemote . withResponderMode . getConnectionManager. It delegates to the connection manager's internal implementation. The StartOnDemand strategy configuration and the multiplexer traffic detection logic are not visible in this code - they reside elsewhere (likely in the multiplexer and inbound governor setu

**Delta:** The implementing code shown is only the thin delegation layer for promotedToWarmRemote. The StartOnDemand strategy setup and the multiplexer ingress traffic detection that triggers this call are implemented in separate modules not shown here. A Python implementation must ensure all three components are implemented: (1) StartOnDemand strategy for mini-protocol lifecycle, (2) multiplexer ingress traffic detection, and (3) the promotedToWarmRemote state transition itself.

**Implications:** For the Python implementation, we need to ensure that: (1) the promotedToWarmRemote function correctly accesses the connection manager in responder mode (withResponderMode is a guard/accessor that ensures the connection supports responder functionality), (2) the multiplexer layer is wired to detect ingress traffic and trigger this transition, and (3) mini-protocols are configured with StartOnDemand rather than being eagerly started. Missing any of these pieces would break the cold-to-warm promot

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 14. 19cdb2b8

**Era:** conway

**Spec says:** CHAIN is the top-level transition that applies NEWEPOCH when crossing an epoch boundary, and LEDGERS on the list of transactions in the block body.

**Haskell does:** The provided code implements only the NEWEPOCH transition (newEpochTransition), not the full CHAIN rule. It handles epoch boundary crossing (eNo /= succ eL check), reward pulsing completion, EPOCH sub-transition, pool distribution updates, and DRep pulsingState advancement when NOT crossing an epoch boundary. The CHAIN rule itself (which orchestrates NEWEPOCH + LEDGERS) is not shown.

**Delta:** The code shown is the NEWEPOCH transition, which is a sub-component of CHAIN. The full CHAIN rule that sequences NEWEPOCH then LEDGERS on the block's transaction list is not provided. Additionally, when not crossing an epoch boundary, the code pulses DRep state and predicts future protocol parameters - behaviors that are part of the Conway-specific NEWEPOCH but not explicitly described in the high-level CHAIN spec text.

**Implications:** Python implementation must: (1) implement CHAIN as the top-level orchestrator that calls NEWEPOCH then LEDGERS; (2) in NEWEPOCH, when NOT at epoch boundary, pulse DRep state and predict future PParams; (3) when AT epoch boundary, complete reward pulsing if in progress, call EPOCH sub-transition, update pool distribution from stake mark snapshot, reset block counts, and clear reward update state.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 15. 202d64a8

**Era:** shelley

**Spec says:** The UTxO-inductive rule defines 11 preconditions for transaction validation in the Shelley era, plus state transition logic for utxo, deposits, fees, and protocol parameter updates.

**Haskell does:** No implementing Haskell code was provided for analysis.

**Delta:** Cannot verify implementation correctness without source code. The rule is complex with 11 preconditions and 4 state updates, so divergences in any of these are plausible.

**Implications:** Python implementation must faithfully implement all 11 preconditions and the exact state transition. Each precondition maps to a specific validation failure. The consumed/produced balance equation and deposit change calculation are particularly error-prone.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 16. 29e9438b

**Era:** conway

**Spec says:** txinsVKey filters a set of TxIn by intersecting it with the domain of the UTxO range-restricted to entries where the address (proj₁ of TxOut) satisfies isVKeyAddr. Formally: txinsVKey txins utxo = txins ∩ dom (utxo ∣^' (isVKeyAddr ∘ proj₁))

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Implementation is missing entirely. Cannot verify correctness of the filtering logic, the range-restriction operation, or the isVKeyAddr predicate integration.

**Implications:** The Python implementation must be written from scratch based on the spec. Key concerns: (1) correctly implementing range-restriction (∣^') on UTxO by predicate on address, (2) correctly identifying VKey addresses vs script addresses, (3) correctly intersecting the filtered domain with the input txins set. Without a reference implementation, we must rely heavily on spec-based tests.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 17. 2c1377df

**Era:** conway

**Spec says:** addAction unconditionally inserts a new governance action into the GovState using insertGovAction, which maintains priority ordering. The function always succeeds - it constructs a GovStatePair via mkGovStatePair and inserts it.

**Haskell does:** runProposalsAddAction uses withGovActionParent to validate the parent lineage before inserting. It returns Maybe (Proposals era), returning Nothing when the parent reference is invalid (i.e., the parent is neither the current root nor a known node in the governance graph). It also maintains a tree/graph structure with parent-child edges (PEdges), root children tracking, and an ordered map (OMap) -

**Delta:** 1) The Haskell implementation can FAIL (return Nothing) when the governance action's parent reference is invalid, while the spec's addAction always succeeds unconditionally. 2) The Haskell implementation maintains a rich graph structure (PEdges with parent/children, roots with prRootL/prChildrenL, pGraphNodesL) that is not described in the spec's simple insertGovAction. 3) The Haskell implementation distinguishes between actions whose parent is the current root vs. actions whose parent is an exi

**Implications:** Python implementation must: 1) Handle the case where addAction can fail due to invalid parent references - this is a validation step not visible in the spec's addAction but enforced in Haskell. 2) Maintain a governance action graph/tree structure (not just a priority-ordered list) with parent-child relationships. 3) Implement the three-way branching: parent-is-root (insert as root child), parent-is-known-node (insert as that node's child), or parent-is-unknown (reject/fail). A naive implementati

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 18. 38a67f96

**Era:** shelley

**Spec says:** consumed(pp, utxo, txb) = produced(pp, poolParams, txb) where consumed = sum of input UTxOs + refunds + withdrawals, and produced = sum of output UTxOs + fees + deposits + donations. When equality holds, value is only moved between outputs, reward accounts, fee pot, and deposit pot.

**Haskell does:** The `produced` function includes txdonation (inject (txb .txdonation)) which is a Conway-era addition not mentioned in the original spec text. The test (`preserveBalance`) checks the property differently from the spec's consumed/produced functions: it computes created = sumCoinUTxO(u') + fee + totalDeposits and consumed = sumCoinUTxO(u) + totalRefunds + withdrawals, comparing post-state UTxO again

**Delta:** 1) The Haskell `produced` includes `txdonation` which is a Conway-era extension beyond the basic spec rule. 2) The test formulation uses a different but equivalent algebraic rearrangement: it compares (UTxO_after + fee + newDeposits) vs (UTxO_before + refunds + withdrawals) rather than the spec's consumed vs produced functions directly. 3) The test explicitly exempts transactions with failed scripts from the balance check.

**Implications:** Python implementation must: (1) include txdonation in the produced calculation for Conway era, (2) handle failed-script transactions separately (they don't preserve balance in the same way since collateral is consumed), (3) ensure the consumed/produced functions are algebraically consistent with the UTxO-diff formulation used in the test.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 19. 38c8bcc4

**Era:** shelley

**Spec says:** consumed pp utxo tx = ubalance(txins tx ◁ utxo) + wbalance(txwdrls tx) + keyRefunds pp tx. The function takes three arguments: PParams, UTxO, and TxBody. It sums: (1) the balance of inputs restricted from UTxO, (2) withdrawal balances, and (3) key deposit refunds (keyRefunds pp tx, which only depends on pp and tx).

**Haskell does:** consumed pp st txb = balance(st.utxo | txb.txins) + txb.mint + inject(depositRefunds pp st txb) + inject(getCoin(txb.txwdrls)). The function takes pp, st (full state, not just UTxO), and txb. It includes an additional term 'txb.mint' (minted value) not present in the spec rule. Also, depositRefunds takes the full state 'st' as an argument (not just pp and tx), suggesting it may consult additional 

**Delta:** Two key divergences: (1) The Haskell implementation adds 'txb.mint' (the value minted by the transaction) to the consumed calculation, which is entirely absent from the spec rule. (2) depositRefunds takes the full ledger state 'st' rather than just PParams and TxBody, indicating a richer refund calculation that may depend on current delegation state. The spec's keyRefunds only depends on pp and tx. This likely reflects a later era (e.g., Babbage/Conway) where the consumed function was extended t

**Implications:** For Python implementation: (1) If targeting a post-Shelley era, the consumed function MUST include the minted value (txb.mint) as a consumed term — omitting it will cause transaction validation failures for any tx that mints or burns tokens. (2) The deposit refund calculation may need access to the full ledger state (e.g., registered stake credentials and their deposits), not just protocol parameters and the transaction body. (3) The UTxO is accessed via a state object (st.utxo) rather than pass

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 20. 3e82905d

**Era:** conway

**Spec says:** POOL transition handles registering and retiring stake pools with basic validation (network ID, pool cost, metadata hash size).

**Haskell does:** The implementation adds several hardfork-gated checks beyond the basic spec: (1) Alonzo hardfork gates network ID validation via hardforkAlonzoValidatePoolAccountAddressNetID, (2) SoftForks.restrictPoolMetadataHash gates metadata hash size check, (3) Conway hardfork gates VRF key uniqueness via hardforkConwayDisallowDuplicatedVRFKeys with complex logic for new registration vs re-registration (chec

**Delta:** VRF key hash uniqueness enforcement (Conway-era), protocol-version-gated validation checks, and future stake pool parameter handling during re-registration are implementation additions beyond the simple spec description. The re-registration path has complex VRF key hash map maintenance involving psFutureStakePoolParams lookups.

**Implications:** Python implementation must: (1) gate network ID check on protocol version (Alonzo+), (2) gate metadata hash size check on protocol version, (3) gate VRF key uniqueness on Conway protocol version, (4) handle both new registration and re-registration paths differently for VRF keys, (5) maintain psVRFKeyHashes map with proper reference counting (knownNonZeroBounded), (6) clean up future VRF key hashes from psFutureStakePoolParams during re-registration.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 21. 4014aa33

**Era:** shelley

**Spec says:** The randomness factor r_e is defined as r_e = N / (σ_a · max(1, N̄)), where N is the number of slots in which the pool was elected as leader, σ_a is the relative active stake of the pool, and N̄ is the total number of blocks that were added to the chain during the epoch.

**Haskell does:** No implementing code was found for the direct r_e formula. The Haskell test (alicePerfEx8) computes pool performance via the 'likelihood' function which uses leader probability, active slot coefficient, relative stake, and the number of blocks produced. The likelihood function is a more general statistical computation that encompasses the r_e calculation but uses a different formulation (log-likel

**Delta:** The spec presents r_e as a simple ratio N / (σ_a · max(1, N̄)), but the Haskell implementation uses a likelihood-based approach that computes the probability of observing N blocks given the expected number of blocks (derived from leader probability, relative stake, and epoch size). The likelihood function is StakePoolPerformance = Likelihood [LogWeight], not a direct implementation of the r_e formula. The r_e formula may be a simplified/conceptual description while the actual implementation uses

**Implications:** For the Python implementation, we need to decide whether to implement the simple r_e formula from the spec or the likelihood-based approach from the Haskell code. If we implement the simple formula, our results will diverge from the Haskell reference implementation. The likelihood approach involves computing log-likelihoods for each slot and aggregating them, which is significantly more complex than the ratio formula.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 22. 43703206

**Era:** conway

**Spec says:** The ledger is modeled as a state machine s →[X]{b} s', where a state s transitions to s' given a signal (block) b under transition rule X. This is a general, abstract model.

**Haskell does:** The ledger transition implementation (1) passes the ORIGINAL certState (not the updated certState') to the UTXOW environment, meaning UTXOW does not see delegation changes from the same transaction, and (2) conditionally skips the DELEGS sub-rule entirely when IsValid=False, and (3) drains withdrawal accounts before passing them to DELEGS rather than having DELEGS handle the drainage itself.

**Delta:** Three implementation details diverge from or are not captured by the abstract spec description: (a) The ordering — UTXOW receives pre-DELEGS certState in its environment, not the post-transition certState'. This means script validation cannot depend on delegation changes from the same tx. (b) The conditional DELEGS skip for IsValid=False is an implementation-level optimization for Alonzo+ eras not present in the abstract model. (c) The drainAccounts pre-processing of withdrawals before DELEGS is

**Implications:** The Python implementation must (1) pass the original certState (not certState') to the UTXOW sub-rule environment, (2) conditionally skip DELEGS processing when the transaction's IsValid flag is False, and (3) apply drainAccounts to the reward accounts map before invoking the DELEGS equivalent. Getting any of these wrong would cause state divergence from the Haskell reference implementation.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 23. 44cff96a

**Era:** conway

**Spec says:** SNAP computes new stake distribution snapshots at the epoch boundary. The new mark snapshot is computed from the current UTxO, DState, and PState via stakeDistr.

**Haskell does:** The Haskell implementation uses `instantStake` (via `instantStakeG` lens on the LedgerState) rather than directly calling `stakeDistr utxo dstate pstate`. It converts this via `snapShotFromInstantStake` which uses an incremental/cached stake distribution. The comment in the code explicitly notes 'per the spec: stakeSnap = stakeDistr @era utxo dstate pstate' acknowledging the divergence is intentio

**Delta:** The spec defines snapshot computation as a pure function `stakeDistr(utxo, dstate, pstate)` but the implementation uses an incremental/cached instant stake representation (`instantStakeG`) and converts it via `snapShotFromInstantStake`. Also, `ssStakeMarkPoolDistr` is an extra field not in the spec, computed eagerly for performance.

**Implications:** Python implementation should follow the spec's `stakeDistr` approach directly (computing from UTxO, DState, PState) since we don't need the performance optimization of incremental stake. The `ssStakeMarkPoolDistr` field can be omitted or computed lazily. The rotation logic (mark->set->go) is faithfully implemented and should be replicated exactly.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 24. 4af147df

**Era:** conway

**Spec says:** LEDGER includes the UTXOW, GOV, and CERTS sub-rules as its components for processing a single transaction.

**Haskell does:** The Haskell implementation invokes DELEGS (not CERTS) and UTXOW, but does not explicitly invoke a GOV sub-rule. The DELEGS rule likely subsumes CERTS functionality, and GOV may be handled within UTXOW or DELEGS indirectly. Additionally, the code conditionally executes the DELEGS/CERTS path only when the transaction is valid (IsValid True), skipping certificate processing for invalid transactions. 

**Delta:** 1) The spec says CERTS and GOV, but the code invokes DELEGS (which may wrap CERTS). GOV is not explicitly invoked as a separate sub-rule. 2) Certificate/delegation processing is conditional on transaction validity (IsValid True), which is not explicitly stated in the spec description. 3) The order is DELEGS then UTXOW, meaning certState' is computed before utxoSt', but utxoSt' uses the original certState (not certState'). This ordering and data flow matters for correctness. 4) Withdrawal drainin

**Implications:** Python implementation must: (1) use DELEGS (or equivalent combined delegation rule) rather than separate CERTS and GOV invocations, matching the actual Haskell structure; (2) conditionally skip certificate processing for invalid (phase-2 failure) transactions; (3) pass the original certState to UTXOW, not the updated certState'; (4) implement withdrawal draining and incomplete withdrawal validation before delegation processing; (5) correctly handle the epoch number resolution from slot when mbCu

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 25. 4d9b4359

**Era:** conway

**Spec says:** GOV is a transition rule that handles voting and submitting governance proposals, as defined in the Conway-era governance section.

**Haskell does:** No implementing Haskell code was found for analysis.

**Delta:** Cannot verify implementation fidelity — no Haskell source was provided for the GOV transition rule.

**Implications:** The Python implementation must be built directly from the spec. Without a reference Haskell implementation to compare against, we need thorough spec-driven tests covering voting submission, proposal submission, and their interaction with the broader Conway governance framework.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 26. 5504d241

**Era:** multi-era

**Spec says:** ConnectionState has 10 constructors: ReservedOutboundState, UnnegotiatedState Provenance, OutboundStateᵗ DataFlow, OutboundState DataFlow, InboundIdleStateᵗ DataFlow, InboundState DataFlow, DuplexState, OutboundIdleStateᵗ, TerminatingState, TerminatedState. OutboundState variants carry a DataFlow parameter. InboundIdleState carries a timeout annotation (τ). OutboundIdleState has no DataFlow parame

**Haskell does:** AbstractState has 12 constructors including several divergences: (1) UnknownConnectionSt is added (not in spec). (2) OutboundStateᵗ DataFlow and OutboundState DataFlow are split into OutboundUniSt (no parameters) and OutboundDupSt TimeoutExpired (encodes DataFlow and timeout into separate constructors). (3) OutboundIdleSt carries a DataFlow parameter, unlike the spec's OutboundIdleStateᵗ which has

**Delta:** Multiple structural differences: (a) Spec's two OutboundState variants (with/without τ) parameterized by DataFlow become OutboundUniSt (always no-timeout unidirectional) and OutboundDupSt TimeoutExpired (duplex with explicit timeout flag). (b) OutboundIdleSt gains a DataFlow parameter not in spec. (c) UnknownConnectionSt and WaitRemoteIdleSt are extra states in implementation. (d) InboundIdleSt loses its τ annotation — timeout handling is implicit.

**Implications:** Python implementation must decide whether to follow the spec's parameterization (DataFlow on OutboundState variants, no DataFlow on OutboundIdleState) or the Haskell implementation's refactored constructors. The extra states (UnknownConnectionSt, WaitRemoteIdleSt) need to be accounted for in state machine transitions. The OutboundUniSt/OutboundDupSt split means DataFlow is baked into constructor choice rather than being a parameter — this affects pattern matching and state transition logic.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 27. 5a197260

**Era:** conway

**Spec says:** UTXOW is a transition rule that checks correct witnessing with appropriate signatures, datums, and scripts, and includes the UTXO transition rule as a sub-rule.

**Haskell does:** No implementing code was provided for analysis. However, the Haskell test suite includes a golden test (goldenDuplicateNativeScriptsDisallowed) that verifies CBOR decoding of TxWits rejects duplicate native scripts, which is part of the witnessing infrastructure.

**Delta:** No implementation code available to compare against spec. The existing Haskell test covers a CBOR-level constraint (no duplicate native scripts in witness set) that is an implicit requirement of the spec's 'appropriate scripts' witnessing check but is enforced at the deserialization layer rather than the transition rule itself.

**Implications:** Python implementation must: (1) enforce no-duplicate-native-scripts at the CBOR deserialization layer for TxWits, raising appropriate errors; (2) implement the full UTXOW transition rule checking VKey signatures cover all required signers, all required datums are present, all required scripts are present, and the UTXO sub-rule passes. Without reference Haskell implementation code, we must rely on the spec and test vectors to ensure correctness.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 28. 5da6bcc5

**Era:** shelley

**Spec says:** The second nibble (bits 0-3) of the header byte encodes the network identifier. Testnets = 0000 (0x0), Mainnet = 0001 (0x1), and future networks = 0010-0xF are reserved. Bootstrap addresses are excluded from this scheme.

**Haskell does:** The function headerNetworkId only checks bit 0 of the header. If bit 0 is set, it returns Mainnet; otherwise it returns Testnet. This means: (1) It collapses the entire 4-bit network nibble into a single-bit check. (2) Any value with bit 0 set (0x1, 0x3, 0x5, 0x7, 0x9, 0xB, 0xD, 0xF) is treated as Mainnet. (3) Any value with bit 0 unset (0x0, 0x2, 0x4, 0x6, 0x8, 0xA, 0xC, 0xE) is treated as Testne

**Delta:** The spec defines a 4-bit network discriminator with three categories (testnet=0, mainnet=1, future=2-15), but the Haskell implementation reduces this to a 1-bit check (bit 0 only), collapsing future network values into either Mainnet or Testnet based solely on the LSB. Future network nibble values 0x2-0xF are not rejected or handled separately.

**Implications:** For our Python implementation, we need to decide whether to (a) faithfully implement the spec's 3-category scheme (testnet=0, mainnet=1, future=2-15 as error/reserved), or (b) match the Haskell behavior of a simple bit-0 check. For conformance testing against the Cardano node, we should match the Haskell behavior. However, we should be aware that network nibble values >= 2 are technically 'future networks' per spec. We should also ensure bootstrap (Byron) addresses bypass this network nibble log

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 29. 62b945be

**Era:** shelley

**Spec says:** Pool retirement certificate validation requires a witness for the pool key (sk_pool) only; it does not need to be signed by any of the pool owners.

**Haskell does:** No implementing Haskell code was found for this rule. The witness-checking logic for pool retirement certificates could not be located for comparison.

**Delta:** Cannot confirm whether the Haskell implementation correctly restricts the required witness set to only the pool cold key for retirement certificates. There may be additional checks or the logic may be embedded in a generic certificate witness function that was not provided.

**Implications:** The Python implementation must ensure that the witness requirement computation for pool retirement certificates returns exactly {pool_cold_key_hash} and does NOT include any owner key hashes. This is a key distinction from pool registration certificates which require owner witnesses. Without the Haskell reference code, we must rely purely on the spec and validate thoroughly with tests.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 30. 698d245d

**Era:** shelley

**Spec says:** Each operational key certificate contains an additional integer field (counter). Certificates with a larger counter value take precedence, allowing invalidation of compromised hot keys.

**Haskell does:** The Haskell test helper setOCertCounter uses Map.insert to directly set the counter for a key hash in the chain state's chainOCertIssue map. No implementing validation code was provided to verify the precedence/rejection logic.

**Delta:** No implementing Haskell code was provided for the actual validation rule that enforces higher-counter-takes-precedence semantics (e.g., rejecting certificates with counter <= current). Only the test helper that sets counters in chain state was found. The Python implementation must ensure it implements both the state tracking (map of key hash to counter) AND the validation rule (reject certificates with counter not strictly greater than current).

**Implications:** The Python implementation must: (1) maintain a mapping from pool cold key hashes to their current OCert counter values, (2) when processing a new OCert, compare its counter against the stored value and only accept if strictly greater (or if no prior entry exists), (3) reject certificates with equal or lower counters. Without the Haskell validation code as reference, the Python implementation should be carefully tested against both the spec rule and edge cases (equal counters, lower counters, fir

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 31. 6b2cc242

**Era:** conway

**Spec says:** RATIFY is a transition rule that decides whether a pending governance action has reached the voting thresholds it needs to be ratified. It processes pending governance actions and determines if they meet the required thresholds defined in the ratification section.

**Haskell does:** No implementing Haskell code was provided for analysis.

**Delta:** Cannot verify implementation correctness without the Haskell source. The RATIFY rule likely involves checking DRep, SPO, and Constitutional Committee voting thresholds against governance action type-specific requirements.

**Implications:** The Python implementation must faithfully implement the RATIFY transition rule: iterating over pending governance actions, computing acceptance by each voting body (CC, DRep, SPO) against the required thresholds for each action type, and producing ratified vs. remaining actions. Without reference Haskell code, we must rely solely on the spec for correctness.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 32. 6f82b87e

**Era:** shelley

**Spec says:** The retirement certificate requires a witness for the pool key sk_pool. The spec also implicitly requires the retirement epoch to be bounded (this is enforced by protocol parameter eMax in the formal ledger rules, though not explicitly stated in this excerpt). After the retirement epoch, delegated stake is disregarded.

**Haskell does:** The Haskell pattern `RetirePoolTxCert` captures KeyHash StakePool and EpochNo. The Haskell test `poolRetirement` explicitly validates that the retirement epoch satisfies: currentEpoch < retirementEpoch <= currentEpoch + eMax (via ppEMaxL protocol parameter). This eMax bound is a critical validation rule enforced in the POOL transition but only implied in this spec excerpt.

**Delta:** The spec excerpt describes the certificate structure and witness requirements but does not explicitly mention the eMax bound on the retirement epoch. The Haskell implementation and tests enforce that the retirement epoch must be at most currentEpoch + eMax (the protocol parameter). This bound is part of the formal POOL STS rules but is absent from this particular spec text.

**Implications:** The Python implementation MUST enforce the eMax bound on retirement epoch (currentEpoch < retirementEpoch <= currentEpoch + eMax) during transaction validation, even though this spec excerpt doesn't mention it. Failing to enforce this would allow unbounded retirement epochs, which diverges from the Haskell ledger behavior. The witness check must verify only the pool key signature, not owner signatures.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 33. 7098fbe5

**Era:** multi-era

**Spec says:** After a connection is closed, it is kept in TerminatingState^τ for the duration of the wait time timeout. When the timeout expires, the connection entry is removed from the connection manager's state (the connection is forgotten).

**Haskell does:** No implementing code was found. The Haskell test `verifyTimeouts` traces state transitions and tracks when a connection enters TerminatingSt, recording the timestamp, but the test structure implies it verifies that the time spent in TerminatingSt does not exceed the configured wait time timeout before the connection is removed.

**Delta:** No implementation code is available to verify correctness against the spec. The test code shows TerminatingSt is one of the timed states (alongside InboundIdleSt, OutboundDupSt Ticking, OutboundIdleSt) whose duration is checked against configured timeouts, but the removal logic itself is not visible.

**Implications:** The Python implementation must: (1) keep a connection in TerminatingState for exactly the configured wait time timeout duration, (2) remove the connection entry from state after that timeout expires, (3) not allow the connection to linger beyond the timeout. Tests must verify both the timeout duration constraint and the actual removal of the connection entry.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 34. 71e736c5

**Era:** conway

**Spec says:** pparamThreshold maps each PParamGroup to a pair (Maybe ℚ × Maybe ℚ) representing (DRep threshold, SPO threshold). NetworkGroup=(P5a, ─), EconomicGroup=(P5b, ─), TechnicalGroup=(P5c, ─), GovernanceGroup=(P5d, ─), SecurityGroup=(─, Q5). The function returns a pair where either component can be Nothing (─), and SecurityGroup is the only group with an SPO threshold.

**Haskell does:** pparamsUpdateThreshold does NOT return a (Maybe ℚ, Maybe ℚ) pair per group. Instead, it takes a PPU (protocol parameter update), finds all modified parameter groups via modifiedPPGroups, maps each group to a single DRep voting threshold via a lens (dvtPPNetworkGroupL, dvtPPGovGroupL, dvtPPTechnicalGroupL, dvtPPEconomicGroupL), and then takes the maximum. SecurityGroup is completely absent from the

**Delta:** 1) The spec defines pparamThreshold as returning a pair (DRep, SPO) for each group, but the Haskell implementation only computes a single DRep threshold (no SPO threshold logic). 2) SecurityGroup is missing entirely from the Haskell thresholdLens — the case expression has no branch for it. 3) The Haskell code computes a single maximum across all modified groups rather than returning per-group pairs. The SPO threshold (Q5 for SecurityGroup) must be handled elsewhere in the Haskell codebase, meani

**Implications:** The Python implementation must handle both DRep AND SPO thresholds for protocol parameter updates. The spec clearly defines SecurityGroup → (─, Q5) meaning SPO votes are needed for security parameters. The Python pparamThreshold function should return the full (Maybe Rational, Maybe Rational) pair as specified. When computing the effective threshold for a PPU, the Python code needs to: (1) compute max DRep threshold across all non-Security groups the modified params belong to, AND (2) check if a

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 35. 7444be03

**Era:** conway

**Spec says:** CERTS-PoV theorem states that for any valid CERTS transition from s₁ to sₙ under environment Γ, getCoin(s₁) = getCoin(sₙ) + getCoin(wdrlsOf(Γ)). This is a universal conservation law: the coin difference between initial and final certificate states is exactly the withdrawals amount. This holds for any list of certificates l.

**Haskell does:** The conwayCertsTransition implementation processes certificates recursively (right-to-left via gamma :|> txCert pattern). On the Empty case (base case), it either just returns certState (post-hardfork) or validates withdrawals and drains accounts. The withdrawal draining (drainAccounts) happens only at the Empty/base case, not distributed across certificate processing. Additionally, post-hardfork 

**Delta:** 1) The PoV property as stated in the spec (getCoin s₁ = getCoin sₙ + getCoin(wdrlsOf Γ)) applies universally, but in the Haskell implementation there is a protocol-version-dependent hardfork flag that moves withdrawal processing out of CERTS to LEDGER. Post-hardfork, CERTS returns certState unchanged for the Empty case, so getCoin(s₁) = getCoin(sₙ) and the withdrawal component is zero from CERTS's perspective. 2) The spec treats wdrlsOf as coming from the CertEnv, but the Haskell code extracts w

**Implications:** Python implementation must: (1) account for the hardfork boundary where withdrawal processing moves from CERTS to LEDGER, (2) ensure that the PoV invariant is tested both pre- and post-hardfork, (3) correctly model where withdrawals are sourced from (tx body vs. environment field), and (4) verify that individual CERT transitions (DELEG, POOL, GOVCERT) preserve coin values independently (since only the base case touches withdrawals).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 36. 76961c8a

**Era:** multi-era

**Spec says:** The multiplexer MUST use a fair scheduling policy (round-robin) for mini-protocols: each gets a turn in order, skipped if no data, at most one segment per turn, only rescheduled immediately if no other protocol is ready.

**Haskell does:** No implementing Haskell code was provided for the multiplexer scheduler itself. The test (prop_mux_starvation) validates the fairness property by setting up two mini-protocols with uneven payload sizes (both > 2*SDU size of 1280 bytes) and checking that headers from both protocols are interleaved in the trace, confirming neither protocol starves the other.

**Delta:** No implementation code available to compare against spec. The Haskell test uses specific infrastructure (TBQueue-based bearers, MiniProtocolInfo, TraceRecvHeaderEnd tracing) to validate fairness. A Python implementation must ensure the same round-robin fairness guarantees are met.

**Implications:** The Python multiplexer implementation must implement round-robin scheduling with the 4 specified properties. Tests must verify interleaving of segments from multiple mini-protocols, especially when payloads are uneven in size, to ensure no starvation occurs.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 37. 79d94004

**Era:** shelley

**Spec says:** consumed(pp, utxo, txBody) = ubalance(txins(tx) ◁ utxo) + wbalance(txwdrls(tx)) + keyRefunds(pp, tx). The function takes PParams, UTxO, and TxBody as arguments. The result type is Coin. There are exactly three summands: (1) balance of restricted UTxO, (2) withdrawal balance, and (3) key refunds.

**Haskell does:** consumed(pp, st, txb) = balance(st.utxo | txb.txins) + txb.mint + inject(depositRefunds(pp, st, txb)) + inject(getCoin(txb.txwdrls)). The function takes a full state `st` (not just UTxO), uses multi-asset `balance` (not coin-only `ubalance`), includes a `txb.mint` term for minted tokens, uses `depositRefunds` (which may differ from `keyRefunds`), and has four summands instead of three. The result 

**Delta:** Three key divergences: (1) The Haskell code adds `txb.mint` (minted/burned tokens) as a fourth summand, which is absent from the spec rule. This reflects the Mary/Alonzo-era extension for multi-asset support. (2) The result type is multi-asset Value rather than Coin, and `balance` replaces `ubalance`. (3) The second argument is the full ledger state `st` rather than just the UTxO; `depositRefunds` takes the state (which may include DState information for computing refunds) rather than just PPara

**Implications:** For our Python implementation: (1) We must include the mint field in the consumed calculation if targeting Mary+ eras. Omitting it would break the preservation-of-value (POV) property for transactions that mint or burn tokens. (2) We should use multi-asset Value arithmetic, not just Coin. (3) We need to pass the full ledger state (or at least the DState) to compute deposit refunds, not just PParams and TxBody. (4) The `depositRefunds` function may need to account for governance-related deposits 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 38. 7b24711f

**Era:** conway

**Spec says:** UTXOS checks that any relevant scripts needed by the transaction evaluate to true. This is a defined transition rule in the utxo section.

**Haskell does:** No implementing Haskell code was found or provided for analysis.

**Delta:** Cannot verify correctness of implementation against spec because no Haskell code was provided. The rule likely involves: (1) collecting all relevant scripts (spending, minting, rewarding, certifying), (2) evaluating each against its redeemer/datum/context, (3) ensuring all return true, and (4) handling phase-2 failure via collateral. Without code, we cannot confirm these behaviors are correctly implemented.

**Implications:** The Python implementation must ensure: (1) all relevant scripts are identified from the transaction (spending inputs, minting policies, reward withdrawals, certificate scripts), (2) each script is evaluated with the correct arguments, (3) all must pass for the transaction to succeed, (4) phase-2 failure handling (collateral consumption) is correctly implemented. Without a reference implementation to compare against, we must rely heavily on the formal spec and test vectors.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 39. 814eb961

**Era:** conway

**Spec says:** GOVCERT is a transition rule that handles registering and delegating to DReps (Delegated Representatives). It covers DRep registration, DRep deregistration, DRep update, and vote delegation certificates. The rule validates deposits, credential checks, and delegation targets.

**Haskell does:** No implementing Haskell code was provided for analysis.

**Delta:** Cannot verify implementation correctness without code. The GOVCERT rule in the Conway spec typically includes: (1) RegDRep — register a DRep with a deposit, (2) UnRegDRep — deregister a DRep and reclaim deposit, (3) UpdateDRep — update DRep metadata anchor, (4) DelegVote — delegate voting power to a DRep, Always-Abstain, or Always-NoConfidence. Each sub-rule has specific preconditions regarding deposits, credential existence, and state transitions.

**Implications:** Python implementation must faithfully implement all GOVCERT sub-rules with correct precondition checks, deposit handling, credential management, and delegation state updates. Without reference Haskell code, tests must be derived directly from the formal spec.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 40. 8d143428

**Era:** conway

**Spec says:** certRefund is a pure function mapping a single DCert to a set of DepositPurpose values: dereg yields {CredentialDeposit c}, deregdrep yields {DRepDeposit c}, all others yield ∅.

**Haskell does:** The Haskell implementation splits this into two separate functions with stateful fold logic: (1) conwayDRepRefundsTxCerts handles DRep deregistration refunds by tracking same-tx DRep registrations and using a lookupDRepDeposit callback for previously registered DReps, accumulating a total Coin refund rather than returning a set of DepositPurpose. (2) keyTxRefunds handles credential deregistration 

**Delta:** The spec defines certRefund as a simple per-certificate function returning DepositPurpose sets, but the Haskell implementation merges this with deposit lookup and aggregation into stateful folds over entire transaction certificate sequences. The Haskell code also handles the edge case of register-then-deregister within the same transaction (using the registration deposit amount directly), which is not explicitly mentioned in the spec's certRefund but is an implementation concern for correct refu

**Implications:** The Python implementation should implement certRefund as a pure per-certificate function matching the spec (returning sets of DepositPurpose), but must also implement the higher-level refund aggregation logic that folds over certificate lists, handles same-tx register/deregister patterns, and looks up deposit amounts from state. Tests must cover both the pure certRefund function and the stateful aggregation behavior.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 41. 8e29bae6

**Era:** conway

**Spec says:** TxBody contains fields: txouts as Ix ⇀ TxOut (partial map from index to TxOut), txcerts as List DCert, txvote as List GovVote, txprop as List GovProposal, txvldt as Maybe Slot × Maybe Slot, mint as Value, txsize as ℕ, txid as TxId, txup as Maybe Update. No collateral return or total collateral fields are specified.

**Haskell does:** ConwayTxBodyRaw has several structural differences: (1) txouts is StrictSeq (Sized (TxOut era)) — a strict sequence, not a partial map from Ix; (2) txcerts is OSet (TxCert era) — an ordered set, not a List; (3) txvote is VotingProcedures era — a nested map structure, not List GovVote; (4) txprop is OSet (ProposalProcedure era), not List GovProposal; (5) mint is MultiAsset, not full Value (no ADA c

**Delta:** Key structural divergences: (a) outputs represented as sequence vs partial map; (b) certs as ordered set vs list; (c) votes as VotingProcedures map vs list of GovVote; (d) proposals as ordered set vs list; (e) mint is MultiAsset not Value; (f) Haskell adds collateral return/total collateral fields not in spec; (g) txsize and txid are computed rather than stored; (h) txup field from spec is absent in Conway Haskell implementation; (i) StrictMaybe vs Maybe.

**Implications:** Python implementation must decide whether to follow the spec (partial map for outputs, lists for certs/votes/proposals) or the Haskell implementation (sequence for outputs, ordered set for certs/proposals, nested map for votes). For serialization/deserialization compatibility, Haskell's structure must be matched. The mint field should be MultiAsset (no ADA component). Collateral return and total collateral must be included for Conway era even though spec omits them. txsize and txid should be com

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 42. 8e61fd38

**Era:** multi-era

**Spec says:** DemotedToCold^Unidirectional_Remote and DemotedToCold^Duplex_Remote are edge-triggered transitions performed by `demotedToColdRemote`. The connection manager is notified by the inbound protocol governor once all responder mini-protocols become idle. Detection of idleness during the protocol idle timeout is done in a separate subsequent step (Commit^Remote) which is triggered immediately.

**Haskell does:** No implementing code was found for analysis.

**Delta:** Cannot verify whether the implementation correctly implements edge-triggered semantics, proper notification from inbound protocol governor, or immediate triggering of the Commit^Remote step. The function `demotedToColdRemote` was not located in the provided code.

**Implications:** The Python implementation must ensure: (1) DemotedToCold remote transitions are edge-triggered (fire only on state change, not level), (2) the connection manager is notified by the inbound protocol governor (not self-detected), (3) idleness detection and the Commit^Remote transition are separate steps but Commit^Remote fires immediately after, (4) both Unidirectional_Remote and Duplex_Remote variants are handled.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 43. 9032672a

**Era:** shelley

**Spec says:** UTxOEnv is a tuple of four fields: (1) slot : Slot, (2) pp : PParams, (3) poolParams : KeyHash_pool ↦ PoolParam (registered stake pools mapping), and (4) genDelegs : GenesisDelegation (genesis key delegation mapping).

**Haskell does:** The Agda/Haskell implementation defines UTxOEnv with only three fields: slot : Slot, pparams : PParams, and treasury : Coin. It omits poolParams and genDelegs entirely, and adds a treasury field not present in the spec.

**Delta:** Two spec fields (poolParams, genDelegs) are missing from the implementation, and one implementation field (treasury) is absent from the spec. This is a significant structural divergence — the implementation has a fundamentally different environment shape than the spec describes. The field 'pp'/'pparams' naming also differs but is cosmetic.

**Implications:** For a Python implementation: (1) We must decide whether to follow the spec (4 fields) or the Haskell implementation (3 fields). The Conway-era ledger spec may have evolved to remove poolParams/genDelegs and add treasury. (2) Any code that passes UTxOEnv to sub-rules expecting poolParams or genDelegs will fail if we follow the Haskell structure. (3) The treasury field suggests the implementation targets a newer era (Conway) where treasury is threaded through the UTxO rule for donation/treasury in

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 44. 939c8fb4

**Era:** shelley

**Spec says:** After the retirement epoch, any stake delegated to the retired stake pool is disregarded by the PoS protocol and does not participate in leader election (analogous to enterprise address stake exclusion).

**Haskell does:** The Haskell test (poolRetirementProp) only verifies the mechanics of the RetirePool signal processing: that the retirement epoch is well-formed (currentEpoch < e < currentEpoch + maxEpoch), that the pool hash remains in stPools in both source and target states, and that the pool hash appears in the retiring map of the target state. It does NOT test that stake delegated to a retired pool is actuall

**Delta:** The spec requires that post-retirement-epoch stake is disregarded for PoS leader election, but the existing Haskell test only validates the retirement certificate processing (epoch bounds, pool membership, retiring map update). The actual stake exclusion behavior during leader election is not covered by this test. No implementing code was found for the stake-disregard logic itself.

**Implications:** Our Python implementation must ensure two things: (1) RetirePool signal processing correctly validates epoch bounds and updates the retiring map (what the Haskell test covers), and (2) after the retirement epoch, the stake snapshot / leader election logic excludes stake delegated to the retired pool. The second aspect is the core spec requirement and needs dedicated testing beyond what the Haskell test provides.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 45. 96e886e8

**Era:** multi-era

**Spec says:** The node-to-client protocol is composed of three mini-protocols: chain-sync, local-tx-submission, and local-state-query.

**Haskell does:** The NodeToClientProtocols data type includes four mini-protocols: localChainSyncProtocol, localTxSubmissionProtocol, localStateQueryProtocol, and localTxMonitorProtocol.

**Delta:** The Haskell implementation includes an additional mini-protocol (local-tx-monitor) that is not mentioned in the spec. The spec lists only three mini-protocols while the code has four.

**Implications:** Our Python implementation must include all four mini-protocols (including local-tx-monitor) to be compatible with actual Cardano nodes. The spec appears to be outdated or incomplete — local-tx-monitor was added later to allow monitoring of the local mempool. If we only implement the three protocols from the spec, we will fail to interoperate with nodes that expect or offer the tx-monitor protocol.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 46. 9d0f1550

**Era:** conway

**Spec says:** P/Q5 returns a pair (Maybe ℚ × Maybe ℚ) representing (maxDRepThreshold, maxSPOThreshold) by projecting both proj₁ (DRep) and proj₂ (SPO) from pparamThreshold for each update group, then taking the max of each independently.

**Haskell does:** pparamsUpdateThreshold only computes a single threshold (the DRep voting threshold) by looking up dvtPP*GroupL lenses from DRepVotingThresholds. It does not compute the SPO threshold at all — it returns a single value, not a pair. The test also only checks membership in the set of DRep thresholds.

**Delta:** The spec defines P/Q5 as returning a pair of (Maybe DRepThreshold, Maybe SPOThreshold), but the Haskell implementation only computes the DRep threshold portion. The SPO threshold computation for ChangePParams is either handled elsewhere or is missing. This means the Haskell code implements only proj₁ of the spec's P/Q5.

**Implications:** The Python implementation should implement the full spec: P/Q5 must return a pair of (max_drep_threshold, max_spo_threshold). We need to ensure both DRep and SPO thresholds are computed for ChangePParams governance actions. The SPO threshold lookup will use a different set of thresholds (pool voting thresholds) mapped per parameter group. Do not follow the Haskell simplification of returning only a single value.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 47. a399f4f3

**Era:** shelley

**Spec says:** β = n / max(1, N̄), where n is the number of blocks the pool produced and N̄ is the total number of blocks added to the chain during the epoch. This is derived from β = σ_a · p · r_e where p = n/max(N,1) and r_e = N/(σ_a · max(1, N̄)). The apparent performance is then β/σ (i.e., n / (max(1, N̄) · σ)).

**Haskell does:** The Haskell code computes beta = blocksN / max(1, blocksTotal), which matches the spec's β = n / max(1, N̄). However, it also includes two additional branches not described in the spec formula: (1) if sigma == 0, return 0 (guard against division by zero since apparent performance = β/σ), and (2) if the decentralization parameter d >= 0.8, return 1 (apparent performance is fixed at 1, meaning all p

**Delta:** The Haskell implementation adds two behavioral branches beyond the spec formula: (1) a sigma==0 guard returning 0, which is a reasonable defensive check against division by zero not explicitly in the spec, and (2) a d >= 0.8 threshold that returns apparent performance of 1 regardless of actual block production. The d >= 0.8 behavior is specified elsewhere in the Shelley spec (Section 5.5.3) but is not part of the formula snippet provided. The core β computation itself matches the spec exactly.

**Implications:** Python implementation must: (1) handle sigma==0 by returning 0 to avoid ZeroDivisionError, (2) implement the d >= 0.8 threshold check returning 1.0 for apparent performance, (3) use integer/rational arithmetic for beta = n / max(1, N̄) to maintain precision, and (4) compute apparent performance as beta/sigma when d < 0.8. The comparison d < 0.8 uses unboundRational (converting from BoundedRatio), so Python must correctly compare the decentralization parameter.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 48. a4b3abc2

**Era:** multi-era

**Spec says:** When requestOutboundConnection is called and the connection is in any state not explicitly handled (e.g., UnnegotiatedState Outbound, OutboundState dataFlow, DuplexState), the connection manager signals the caller with a ConnectionExists error.

**Haskell does:** The Haskell implementation defines a comprehensive AbstractState ADT with states: UnknownConnectionSt, ReservedOutboundSt, UnnegotiatedSt Provenance, InboundIdleSt DataFlow, InboundSt DataFlow, OutboundUniSt, OutboundDupSt TimeoutExpired, OutboundIdleSt DataFlow, DuplexSt, WaitRemoteIdleSt, TerminatingSt, TerminatedSt. The requestOutboundConnection function has explicit handling for certain states

**Delta:** The spec uses informal examples ('e.g.') for which states trigger ConnectionExists, while the Haskell code has a precise exhaustive pattern match. The exact set of states that produce ConnectionExists vs. states that are explicitly handled (allowing reconnection or promotion) must be derived from the full requestOutboundConnection implementation, not just the AbstractState type. States like InboundIdleSt and InboundSt may be promotable to Duplex rather than erroring, which the spec's 'any other 

**Implications:** The Python implementation must replicate the exact pattern-match logic: certain states (ReservedOutboundSt, InboundIdleSt, InboundSt, TerminatedSt, TerminatingSt) have special handling in requestOutboundConnection, while all remaining states (UnnegotiatedSt Outbound, OutboundUniSt, OutboundDupSt, OutboundIdleSt, DuplexSt, WaitRemoteIdleSt) must raise ConnectionExists. Getting the exact partition wrong would either allow duplicate connections or block valid promotions.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 49. b5cff8f5

**Era:** shelley

**Spec says:** An operational key certificate has a lifetime of 90 days. The certificate specifies a starting slot from which it is considered valid; it becomes invalid 90 days after that slot.

**Haskell does:** The formal specification uses MaxKESEvo (a protocol parameter representing the maximum number of KES evolutions) rather than a literal 90-day count. The validity check is: c₀ ≤ kp < c₀ + MaxKESEvo, where c₀ is the certificate's starting KES period and kp is the current KES period. The '90 days' is an approximation based on typical protocol parameters (e.g., MaxKESEvo=62, slotsPerKESPeriod=129600, 

**Delta:** The spec text says '90 days' as a fixed lifetime, but the implementation parameterizes this via MaxKESEvo (max KES evolutions). The actual lifetime depends on MaxKESEvo × slotsPerKESPeriod × slotLength. With mainnet parameters this is approximately 90 days but not exactly 90 days. The validity window is expressed in KES periods, not calendar days.

**Implications:** Python implementation must use MaxKESEvo (protocol parameter) and KES period arithmetic, not a literal 90-day / slot calculation. The validity check must be: c₀ ≤ kesPeriod(currentSlot) < c₀ + MaxKESEvo. The kesPeriod function divides the slot number by slotsPerKESPeriod.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 50. b66ed888

**Era:** shelley

**Spec says:** The metadata schema defines metadata_key as uint and metadata_value as a recursive type with leaf constraints: bytes .size 64 and text .size 64 (at most 64 bytes). Nested maps within metadata_value use metadata_value as keys (not uint).

**Haskell does:** No implementing code was found to analyze.

**Delta:** Without implementation code, we cannot verify: (1) whether the 64-byte limit on text is enforced on UTF-8 byte length vs character count, (2) whether nested map keys correctly allow any metadata_value (not just uint), (3) whether the recursive structure has any depth limits not in the spec. These are common implementation pitfalls.

**Implications:** The Python implementation must carefully distinguish: top-level metadata map keys (uint only) vs nested metadata_value map keys (any metadata_value). The .size 64 constraint in CDDL means at most 64 bytes for the raw encoding, so text .size 64 means at most 64 UTF-8 bytes, not 64 characters. The recursive structure must be handled without artificial depth limits.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 51. bf48fa1a

**Era:** shelley

**Spec says:** After the retirement epoch, any stake delegated to the retired pool is completely disregarded for PoS leader election, analogous to enterprise address stake.

**Haskell does:** The Haskell test (poolRetirementProp) only verifies the mechanics of the RetirePool transition signal: that the retirement epoch is well-formed (currentEpoch < e < currentEpoch + maxEpoch), the pool key remains in stPools in both source and target states, and the pool key is added to the retiring map. It does NOT test the core spec behavior that stake delegated to a retired pool is actually exclud

**Delta:** The Haskell property test covers the retirement certificate processing (POOL rule transition) but not the downstream effect on stake distribution / leader election after the retirement epoch. The spec's central claim — that retired-pool stake is disregarded — is not directly tested by poolRetirementProp.

**Implications:** Our Python implementation must test both (a) the RetirePool signal processing (epoch bounds, pool presence, retiring map update) AND (b) the actual exclusion of retired-pool-delegated stake from the PoS stake snapshot after the retirement epoch. We should not assume the Haskell test fully covers the spec — we need additional integration-level tests for the stake-disregard behavior.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 52. c28cbba5

**Era:** conway

**Spec says:** Overlap is a type-level relation on pairs of GovActionType values. NoConfidence and UpdateCommittee overlap bidirectionally (both return ⊤), and otherwise two action types overlap only when they are identical (a ≡ a').

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Missing implementation. The Overlap relation must be implemented as a function or predicate in Python to determine whether two governance actions conflict. Without it, the governance action enactment pipeline cannot correctly detect conflicting proposals.

**Implications:** Our Python implementation must encode this relation as a function `overlap(a, b) -> bool` that returns True for (NoConfidence, UpdateCommittee), (UpdateCommittee, NoConfidence), and any (x, x) pair where x == x, and False for all other distinct pairs. This is critical for governance action ordering and conflict detection in the RATIFY rule.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 53. c418526e

**Era:** multi-era

**Spec says:** When the p2p governor demotes a peer to cold state, three specific transitions are defined: (1) OutboundState dataFlow → OutboundIdleState dataFlow, (2) OutboundState Duplex → InboundIdleState Duplex, (3) DuplexState → InboundState Duplex. These are performed by calling unregisterOutboundConnection.

**Haskell does:** The Haskell implementation defines a DemoteToColdLocal ADT with four constructors: (1) DemotedToColdLocal for transitions that terminate the connection (any state → TerminatingState), (2) DemoteToColdLocalNoop for transitions that don't terminate (OutboundState Duplex → InboundIdleState, or already in Terminating/Terminated), (3) PruneConnections for duplex demotions that trigger connection prunin

**Delta:** The spec describes OutboundState dataFlow → OutboundIdleState dataFlow as a transition, but the Haskell code's DemotedToColdLocal constructor comment indicates it goes to TerminatingState (i.e., the connection is terminated). The OutboundIdleState appears to be an intermediate/transient state that quickly leads to termination in the unidirectional case. Additionally, the Haskell code adds PruneConnections and DemoteToColdLocalError cases not mentioned in the spec rule, and handles the case where

**Implications:** Python implementation must handle all four cases: (1) For unidirectional OutboundState, transition through OutboundIdleState to TerminatingState; (2) For duplex OutboundState, transition to InboundIdleState (noop from outbound perspective); (3) For DuplexState, transition to InboundState; (4) Handle pruning logic when duplex connections are demoted. Must also handle error cases and already-terminating/terminated connections gracefully.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 54. c5371085

**Era:** conway

**Spec says:** GovState is defined as a List of (GovActionID × GovActionState) pairs, behaving like a queue where new proposals are appended at the end, any proposal can be removed at epoch boundary, and earlier proposals take priority for enactment.

**Haskell does:** The Haskell implementation uses a Map (proposalsActionsMap) rather than a plain list for GovState. mkGovActionState initializes with empty vote maps (mempty) and computes gasExpiresAfter by adding expiryInterval to curEpoch. The proposalsActionsMap is accessed via Map.toList which returns keys in ascending order, not necessarily insertion order.

**Delta:** The spec defines GovState as an ordered List (queue semantics with insertion-order priority), but the Haskell implementation uses a Map keyed by GovActionID. Map.toList returns entries sorted by key, not by insertion order. This means enactment priority in the implementation is determined by GovActionID ordering rather than strict insertion order. The queue semantics (append at end, earlier = higher priority) may not be faithfully preserved if GovActionID ordering diverges from insertion order.

**Implications:** The Python implementation must decide whether to use an ordered list (matching the spec literally) or a dict/map (matching Haskell). If using a dict, the Python implementation should be aware that enactment priority should follow proposal ordering (insertion order or GovActionID order). Python's dict preserves insertion order since 3.7, which may actually be closer to the spec's queue semantics than Haskell's Map. However, for conformance with the Haskell implementation, tests should verify the 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 55. c7b40bce

**Era:** conway

**Spec says:** The `threshold` function maps (PParams, Maybe ℚ, GovAction, GovRole) → Maybe ℚ, with a well-defined table of thresholds per governance action type and role. CC approval is indicated by ✓ (using ccThreshold), ─ means Nothing (role doesn't participate), ✓† means a special 'always exceeds' threshold for Info actions, and specific protocol parameters (P1-P6, Q1, Q4) are used for DRep/SPO thresholds.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** No implementation exists to compare against the spec. The full threshold lookup table, including the special handling of UpdateCommittee (P/Q2a/b depending on ccThreshold presence), ChangePParams (P/Q5 depending on parameter group), and Info (✓† never-enacted semantics), must be implemented from the spec alone.

**Implications:** The Python implementation must faithfully encode the entire threshold table. Key risks: (1) UpdateCommittee has conditional logic — if ccThreshold is Nothing (no-confidence state), use Q2a/P2a, otherwise Q2b/P2b; (2) ChangePParams thresholds depend on which parameter group is being changed (P/Q5 with sub-parameter x); (3) Info actions must return a special threshold that ensures the action is never enacted (e.g., Just (some value > 1) or a sentinel); (4) ─ must map to Nothing (role excluded from

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 56. c94cb84c

**Era:** conway

**Spec says:** EPOCH transition includes sub-rules ENACT, RATIFY, and SNAP as defined in the epoch boundary section of the Conway spec.

**Haskell does:** The Shelley-era epochTransition implements SNAP, POOLREAP, and UPEC sub-rules instead of ENACT, RATIFY, and SNAP. This is because the provided Haskell code is the Shelley-era EPOCH rule, not the Conway-era EPOCH rule. Conway's EPOCH rule would include SNAP, POOLREAP (or equivalent), and then RATIFY/ENACT for governance. The Shelley implementation uses UPEC (Update Proposal Election Check) for prot

**Delta:** The spec describes the Conway-era EPOCH rule with ENACT/RATIFY/SNAP sub-transitions for governance, but the provided Haskell code is the Shelley-era implementation using SNAP/POOLREAP/UPEC. The Conway-era implementation would replace UPEC with RATIFY and ENACT transitions and include governance-specific logic (DRep expiry, committee updates, treasury withdrawals, etc.).

**Implications:** For a Python implementation targeting Conway, we must NOT follow this Shelley-era code. We need to find and implement the Conway-era EPOCH rule which includes: (1) SNAP for snapshot rotation, (2) POOLREAP for pool retirement processing, (3) RATIFY for governance proposal ratification, (4) ENACT for enacting ratified governance actions, plus Conway-specific adjustments like DRep activity tracking, treasury donations, and updated deposit obligation calculations.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 57. cdbbcd1f

**Era:** shelley

**Spec says:** produced(pp, poolParams, tx) = ubalance(outs(tx)) + txfee(tx) + totalDeposits(pp, poolParams, txcerts(tx)). The function takes exactly three components: output balance, fee, and total deposits.

**Haskell does:** The Haskell implementation computes: balance(outs(txb)) + inject(txb.txfee) + inject(newDeposits(pp, st, txb)) + inject(txb.txdonation). It includes a fourth term: txdonation, which is not present in the spec rule. Additionally, 'st' appears to be a broader state type rather than just poolParams, and 'newDeposits' may differ from 'totalDeposits'.

**Delta:** The Haskell code adds a txdonation term that is absent from the spec rule. This means the produced value in the implementation is strictly greater than or equal to the spec's produced value whenever txdonation > 0. The naming also differs: totalDeposits vs newDeposits and poolParams vs st (broader state).

**Implications:** A Python implementation following only the spec rule would be missing the txdonation component, causing the produced value to be too low for any transaction that includes a treasury donation. This would cause the preservation-of-value (UTxO balance) check to fail for transactions with donations. The Python implementation must include txdonation in the produced calculation. Additionally, the state parameter may need to be broader than just poolParams depending on the era.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 58. d0f02111

**Era:** multi-era

**Spec says:** The 'promotedToWarmRemote' method notifies the ConnectionManager that the remote end promoted the local node to a warm peer. It requires HasInitiator muxMode ~ True, takes a ConnectionManager and peerAddr, returns m (OperationResult InState). It executes two transitions: (1) PromotedToWarm^{Duplex}_{Remote} and (2) Awake*_Remote.

**Haskell does:** No implementing Haskell code was found for analysis.

**Delta:** Cannot verify implementation correctness against spec — no Haskell source provided. The spec defines two specific state transitions that must occur, and the HasInitiator constraint restricts this to initiator-capable (duplex) connections only.

**Implications:** Python implementation must: (1) enforce that promotedToWarmRemote is only callable on connections where the local side is an initiator (duplex mode), (2) execute PromotedToWarm^{Duplex}_{Remote} transition moving the connection state appropriately, (3) execute Awake*_Remote transition to activate the remote mini-protocols, (4) return an OperationResult wrapping an InState value indicating the resulting connection state. Without reference implementation code, we must test strictly against the spe

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 59. da20d118

**Era:** shelley

**Spec says:** Validating a stake pool registration certificate requires witnesses (signatures) from ALL owner stake addresses listed in the certificate, as well as a witness for the pool key (vk_pool / sk_pool).

**Haskell does:** The poolCertKeyHashWitness function only extracts the pool key hash (sppId) for RegPool certificates, not the owner stake address key hashes. The owner witness requirement appears to be handled elsewhere (likely in the 'witness univ poolParams' constraint in the test, which generates valid witnesses for the full poolParams structure including owners). The production code snippet shown only covers 

**Delta:** The shown Haskell code (poolCertKeyHashWitness) only returns the pool operator key hash for RegPool, not the owner stake key hashes. The owner witness checking must be implemented in a separate code path (likely in the general witness validation or the 'witness' constraint solver). A Python implementation must ensure BOTH the pool key AND all owner stake key hashes are required as witnesses.

**Implications:** Python implementation must explicitly collect witnesses from two sources for RegPool: (1) the pool operator key (sppId/pool_id), and (2) ALL owner stake address key hashes from the pool parameters. Missing either source would be a spec violation. The poolCertKeyHashWitness function alone is insufficient - there must be additional witness collection logic for owners.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 60. db9f9937

**Era:** multi-era

**Spec says:** Three awake transitions exist: (1) Awake^Duplex_Local triggered by requestOutboundConnection from p2p governor, starting at InboundIdleState^τ dataFlow. (2) Awake^Duplex_Remote triggered by incoming traffic on responder mini-protocols, can start at InboundIdleState^τ dataFlow OR OutboundIdleState^τ Duplex. (3) Awake^Unidirectional_Remote triggered by incoming traffic on responder mini-protocols, s

**Haskell does:** The RemoteState type models the remote side of the state machine with RemoteIdle (corresponding to InboundIdleState), RemoteWarm (after PromotedToWarm), RemoteHot, and RemoteCold states. RemoteCold for Duplex connections supports on-demand responder startup so remote peers can awaken the connection. RemoteIdle includes an STM timeout check for protocol idle detection. However, the provided code is

**Delta:** The data type definition covers the remote states but does not directly encode: (1) the distinction between Awake^Duplex_Local (triggered by requestOutboundConnection) vs Awake^Duplex_Remote vs Awake^Unidirectional_Remote as separate transitions, (2) the fact that Awake^Duplex_Remote can start from OutboundIdleState^τ Duplex (not just InboundIdleState), and (3) the asynchronous detection mechanism for warm/hot transitions. These are handled by transition logic not present in the provided snippet

**Implications:** Python implementation must: (1) Model all three awake transitions distinctly, not just remote state changes. (2) Ensure Awake^Duplex_Remote can be triggered from both InboundIdleState and OutboundIdleState^Duplex — this dual-origin is easy to miss. (3) Implement asynchronous detection of warm/hot mini-protocol activity for remote awake transitions. (4) Distinguish between local-triggered (requestOutboundConnection) and remote-triggered (incoming traffic) awake paths.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 61. e6eaa7a0

**Era:** shelley

**Spec says:** The lower 4 bits (bits 3-0) of the address header byte encode the network id, supporting values 0-15. The spec defines specific network ids but does not restrict to a single bit.

**Haskell does:** The headerNetworkId function only tests bit 0 of the header to determine Mainnet vs Testnet, effectively treating the network id as a 1-bit field (0=Testnet, 1=Mainnet). However, the getAccountAddress test code correctly extracts the full 4-bit network id via (header .&. 0x0F) and uses word8ToNetwork to validate it, failing on unknown network ids.

**Delta:** There are two different implementations: headerNetworkId uses only bit 0 (a simplification), while the account address deserialization uses the full 4-bit network id and validates it. The simplified headerNetworkId would classify network ids 2,4,6,8,10,12,14 as Testnet and 1,3,5,7,9,11,13,15 as Mainnet, which is incorrect per the spec. The account address parser is more correct but still relies on word8ToNetwork for validation.

**Implications:** Python implementation should extract the full 4-bit network id (header & 0x0F) and validate it against known network ids (typically 0=Testnet, 1=Mainnet), rejecting unknown values. Do NOT use only bit 0 to determine the network.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 62. eaeac1ac

**Era:** multi-era

**Spec says:** PromotedToWarm^Duplex_Local transition: When the local p2p governor promotes a cold peer to warm state, the connection manager provides a handle to an existing connection so the p2p governor can drive the connection's state. This transition is performed by `requestOutboundConnection`. The connection transitions to Duplex state from a local perspective.

**Haskell does:** No implementing code was found for analysis.

**Delta:** Cannot verify implementation correctness since no Haskell code was provided. The transition PromotedToWarm^Duplex_Local should be triggered via requestOutboundConnection on an existing duplex connection, promoting it from cold to warm.

**Implications:** Python implementation must ensure that: (1) requestOutboundConnection on an already-established duplex connection returns a connection handle, (2) the connection state transitions to warm from cold in duplex mode, (3) the p2p governor can use the returned handle to further drive state changes. Without reference code, we must implement strictly from the spec.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 63. f09f2feb

**Era:** shelley

**Spec says:** The performance p of a pool is defined as p = n / max(N, 1), where n is the number of blocks the pool successfully added to the chain during the epoch, and N is the number of slots in which the pool was elected as a slot leader during that epoch.

**Haskell does:** The Haskell implementation uses a PerformanceEstimate newtype wrapping a Double, but the actual performance calculation is done through a 'likelihood' function that computes a log-likelihood over the epoch rather than a simple n/max(N,1) ratio. The likelihood function incorporates leader probability, active slot coefficient, relative stake, and decentralization parameter, and accumulates across ep

**Delta:** The spec describes a simple ratio p = n/max(N,1), but the Haskell code uses a likelihood-based performance estimation that incorporates Bayesian/statistical methods with exponential decay across epochs. The simple formula may be a high-level description of the concept, while the implementation uses a more nuanced approach involving the likelihood of observed block production given expected leader slots.

**Implications:** The Python implementation needs to decide whether to implement the simple spec formula or the more sophisticated likelihood-based approach from Haskell. For conformance with the Haskell node, the likelihood-based approach with decay should be used. The simple formula may still be useful as a per-epoch apparent performance metric, but reward calculations likely depend on the likelihood-based estimate.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 64. f5720856

**Era:** shelley

**Spec says:** Byron addresses have bits 7-4 = 1000 (header top nibble is exactly 0x8). The spec enumerates address types based on bit patterns: base (0b00xx), pointer (0b010x), enterprise (0b011x), reward (0b111x), and Byron (0b1000).

**Haskell does:** The Haskell implementation uses `testBit header byron` (testing bit 7) as the primary discriminator between Shelley and non-Shelley addresses. The constant `headerNonShelleyBits = headerByron .|. 0b00001100` suggests that non-Shelley detection may use an OR mask with 0x0C, which could match more header patterns than just 0x8x. The `getShortShortAddr` function only checks bit 7 (the byron bit) to d

**Delta:** The spec defines distinct header ranges (0x8x for Byron, 0xEx/0xFx for reward), but the Haskell deserialization shown only tests bit 7 as the primary branch. Headers with top nibbles 0x9-0xD (bits 7-4 values 1001-1101) are not explicitly handled — they would fall into the Byron branch despite not being valid Byron addresses. The headerNonShelleyBits constant (Byron | 0x0C) further suggests the implementation may have a broader non-Shelley detection than the spec's strict 1000 pattern.

**Implications:** Python implementation should be careful to either (1) match the Haskell behavior of routing all bit-7-set addresses to Byron (for compatibility) or (2) strictly validate the header type nibble per spec and reject invalid header patterns 0x9x-0xDx. If matching Haskell for interoperability, document that headers 0x9x-0xDx will attempt Byron decoding and likely fail at a later stage. Consider adding explicit validation for the header type nibble.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 65. f8688988

**Era:** conway

**Spec says:** getInputHashes returns a single set of DataHash values (ℙ DataHash). It filters UTxO outputs at two-phase script addresses and extracts their data hashes via getDataHashes. There is no special handling for different Plutus language versions or for inputs missing datums.

**Haskell does:** getInputDataHashesTxBody returns a PAIR (Set DataHash, Set TxIn) — the first set is data hashes found on Plutus script inputs, the second set is TxIns that are spending Plutus scripts (pre-V3) but have NoDatum. Additionally, PlutusV3 scripts no longer require spending datums (CIP-0069), so NoDatum with PlutusV3 is silently accepted (not added to either set). The function also uses a ScriptsProvide

**Delta:** 1) The Haskell implementation returns (Set DataHash, Set TxIn) — a pair — whereas the spec returns only ℙ DataHash. The second component tracks inputs that should have datums but don't (used for validation errors). 2) The Haskell code has PlutusV3-specific logic (CIP-0069) where spending datums are no longer required, which is absent from the spec. 3) The Haskell implementation takes a ScriptsProvided argument and uses lookupPlutusScript to determine two-phase script status, while the spec uses 

**Implications:** A Python implementation following only the spec would: (1) miss the second return component (set of TxIns missing datums), which is needed for proper validation error reporting; (2) not handle the PlutusV3 CIP-0069 exemption for spending datums; (3) need to decide how to resolve script lookup — either faithfully following the spec's isTwoPhaseScriptAddress′ or matching the Haskell approach with explicit script provision.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 66. fa14455f

**Era:** shelley

**Spec says:** In the Shelley era, protocol parameter updates can only be proposed and voted on by owners of genesis keys (KeyHashGen / VKeyGen). The update proposal mechanism remains federated throughout the Shelley era.

**Haskell does:** No implementing code was found for the authorization check itself, but the Haskell test (mkMASetDecentralizationParamTxs) constructs a valid update proposal transaction where every core node (genesis key holder) signs the transaction body, and the update is embedded in the transaction body via updateTxBodyL. The test assumes all core nodes must sign, and uses cnDelegateKey (genesis delegate keys) 

**Delta:** No authorization enforcement code was provided to verify that non-genesis-key proposals are rejected. The test only covers the happy path where all genesis key holders sign. There is no negative test showing that a proposal from a non-genesis key is rejected.

**Implications:** The Python implementation must enforce that only genesis key hash holders can propose/vote on parameter updates. We need both positive tests (valid genesis key proposals accepted) and negative tests (non-genesis key proposals rejected). The transaction structure with update field, validity interval, and multi-signature from all core nodes must be faithfully reproduced.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 67. fdb91377

**Era:** conway

**Spec says:** GOV-Propose requires 7 preconditions (actionWellFormed, actionValid, deposit match, validHFAction, hasParent, correct NetworkId, credential in rewardCreds) and transitions the state via addAction with govActionLifetime + epoch, (txid, k), addr, action, and prevAction.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** No implementation to compare against — the spec rule is unimplemented or the code was not located. This means we cannot verify whether any of the 7 preconditions are enforced or whether addAction correctly constructs the new governance state.

**Implications:** The Python implementation must faithfully implement all 7 preconditions and the addAction state transition. Without a reference Haskell implementation to cross-check, tests must be derived purely from the spec. Special attention needed for: (1) actionWellFormed semantics for each action type, (2) actionValid which checks policy and reward credentials, (3) deposit equality check, (4) validHFAction version chain logic, (5) hasParent lineage logic, (6) network ID matching, (7) credential membership

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

