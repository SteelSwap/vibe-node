# Plutus — Critical Gap Analysis

**34 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. 219ac8e1

**Era:** plutus

**Spec says:** A partial builtin application (pba) is well-formed if: (1) bare builtin is always well-formed, (2) value application [pba' V] requires pba' well-formed AND the current signature element ι is NOT a quantified type variable (ι ∉ QVar), (3) force application (force pba') requires pba' well-formed AND ι ∈ QVar. Additionally, |pba| < n must hold (builtin not fully applied).

**Haskell does:** No implementing Haskell code was provided for analysis.

**Delta:** Cannot verify implementation correctness without code. The spec defines a recursive well-formedness check on partial builtin applications that must be faithfully implemented, including correct indexing into the signature (ι = ι_{|pba|}), the distinction between value arguments and force arguments, and the not-fully-applied prerequisite.

**Implications:** The Python implementation must: (1) maintain a signature registry α mapping each builtin to its argument-kind list, (2) implement β to extract the builtin name from a partial application, (3) implement |·| to count the number of applied arguments/forces, (4) check |pba| < n before allowing further application, (5) correctly distinguish QVar (expecting force) from Uni#/★ (expecting value application) at each position in the signature.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. 333a5614

**Era:** plutus

**Spec says:** When the CEK machine is in a compute state with the term being (error), regardless of the current stack s and environment ρ, the machine immediately transitions to the error state ◆, halting execution.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify implementation correctness since no Haskell code was located. The rule may be implemented inline in a pattern match within the CEK machine stepper but was not provided for review.

**Implications:** The Python implementation must ensure that encountering an (error) term in compute mode immediately produces the error state ◆, regardless of what is on the stack or in the environment. No further reduction steps should occur — the error must not be caught, wrapped, or deferred.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 3. 392a5bf3

**Era:** alonzo

**Spec says:** allInsScrts collects, for each spending input in txinputs(txbody(tx)), the tuple (script_v, [d, r, valContext(utxo, tx, (txid,ix,hash_r))], cm) by: (1) finding the redeemer via findRdmr, (2) looking up the UTxO entry to get address a, value v, datum hash h_d, (3) resolving h_d to datum d via indexedDats(tx), (4) resolving validatorHash(a) to script_v via indexedScripts(tx), (5) resolving language(

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify correctness of implementation against spec since no Haskell code is available. Key concerns: (a) the set comprehension implicitly filters — inputs where any lookup fails (no redeemer, no UTxO entry, no datum, no script, no cost model) are silently excluded, (b) the validation context receives (txid, ix, hash_r) where hash_r appears to be the redeemer hash, (c) the data sequence for spending scripts is [datum, redeemer, valContext] — 3 elements, unlike minting/reward scripts which h

**Implications:** Python implementation must: (1) correctly iterate over txinputs only (not reference inputs or collateral), (2) silently skip inputs where any lookup fails (set comprehension semantics), (3) construct the 3-element data list [datum, redeemer, script_context] specifically for spending validators, (4) correctly resolve all five lookups in the correct order, (5) pair each script with its language-specific cost model from protocol parameters.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 4. 3cf0aff0

**Era:** alonzo

**Spec says:** feesOK checks four conjunctive conditions: (1) range of UTxO restricted to fee-marked inputs (txinputs_vf) is subset of TxOutND (non-Plutus-locked outputs), (2) ubalance of fee-marked UTxO is in Coin (Ada-only, no multi-asset), (3) ubalance of fee-marked UTxO >= txfee (fee-marked inputs cover stated fee), (4) minfee(n, pp, tx) <= txfee (minimum fee satisfied). The function takes a block number n a

**Haskell does:** The Haskell implementation restructures the logic significantly: (1) minfee check is always performed (minfee pp utxo tx ≤ txfee), but notably minfee takes utxo as an additional argument and does NOT take a block number n. (2) The remaining conditions (VKey-only collateral addresses, Ada-only balance, and sufficient collateral) are only checked conditionally — when txrdmrs (redeemers) is non-empty

**Delta:** Multiple divergences: (a) The spec's flat 4-condition conjunction becomes a conditional structure where collateral checks only apply when redeemers are present — this is a later era refinement (Alonzo+) vs the spec's Goguen-era definition. (b) The collateral sufficiency check uses a percentage formula (coin bal * 100 ≥ txfee * collateralPercentage) instead of the spec's simple ubalance ≥ txfee. (c) The spec takes a block number n; the implementation drops it but passes utxo to minfee. (d) An ext

**Implications:** For the Python implementation: (1) Must decide which era's feesOK to implement — the Haskell code reflects a more mature Alonzo/Babbage-era version with collateralPercentage and conditional checks. (2) The collateral percentage-based check is critical for Alonzo+ correctness. (3) The conditional logic (only check collateral when redeemers present) must be implemented. (4) The minfee function signature differs — Python must pass utxo to minfee. (5) The collateral non-emptiness check must be inclu

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 5. 3f509f39

**Era:** shelley

**Spec says:** A stake_credential is a two-element array that is either [0, addr_keyhash] (key-based credential) or [1, scripthash] (script-based credential). These are the only two variants.

**Haskell does:** The Haskell implementation defines StakingCredential with TWO constructors: (1) StakingHash Credential, which wraps a Credential type (covering both key hash and script hash variants, corresponding to tags 0 and 1), and (2) StakingPtr Integer Integer Integer, which represents a certificate pointer constructed from slot number, transaction index, and certificate index. The StakingPtr variant has no

**Delta:** The Haskell type includes an additional StakingPtr variant (certificate pointer with slot, tx index, cert index) that is not part of the CDDL stake_credential definition. The CDDL spec only defines key-hash (tag 0) and script-hash (tag 1) variants. Certificate pointers are a separate concept in the Cardano address encoding (used in pointer addresses) and should not be conflated with stake_credential as defined in the CDDL. Additionally, the Haskell type names it 'StakingCredential' rather than '

**Implications:** The Python implementation of stake_credential should strictly follow the CDDL spec with only two variants: tag 0 (addr_keyhash) and tag 1 (scripthash). It should NOT include a pointer variant. If interoperating with Plutus/Haskell code that uses StakingCredential, be aware that StakingPtr values cannot be represented as a stake_credential in CDDL serialization. The Python type should be a tagged union with exactly two cases, each serialized as a 2-element CBOR array.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 6. 43a57fdc

**Era:** plutus

**Spec says:** Compatibility of inputs V̄ with a reduced arity ᾱ via type assignment S requires: (1) n=m (lengths match), (2) for each index i where τᵢ ∈ Uni# there exists a monomorphic type Tᵢ such that Vᵢ is a constant of type Tᵢ and Tᵢ ⪯_{Sᵢ} τᵢ, (3) all Sᵢ are consistent (agree on shared type variables), (4) S is the union of all Sᵢ. Positions where τⱼ = ★ accept any term.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** No implementation found to compare against. This is a core definition that underpins built-in function application type checking. A Python implementation must be created from scratch.

**Implications:** The Python implementation must correctly implement: (a) length checking between args and arity, (b) type matching at Uni# positions via the ⪯ relation, (c) consistency checking of type assignments across all constrained positions, (d) merging of consistent type assignments into a single S, (e) accepting any value at ★ positions without contributing to S. Errors in any of these steps could cause built-in functions to accept ill-typed arguments or reject well-typed ones.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 7. 48bfce5b

**Era:** alonzo

**Spec says:** indexedScripts(tx) constructs a map from PolicyID to Script by taking all scripts s from txscripts(txwits(tx)) — i.e., only the scripts embedded in the transaction witnesses — and indexing each by hashScript(s).

**Haskell does:** The Haskell implementation of txscripts includes both the scripts from tx.wits (transaction witnesses) AND reference scripts resolved from the UTxO: `txscripts tx utxo = scripts (tx.wits) ∪ fromList (refScripts tx utxo)`. This means txscripts takes an additional utxo parameter and unions witness scripts with reference scripts.

**Delta:** The spec defines indexedScripts purely over txscripts(txwits(tx)) which is just witness scripts, but the Haskell txscripts function also includes reference scripts from the UTxO. This means the indexed script map in the implementation can contain scripts not present in the transaction witnesses themselves. The spec's indexedScripts is a simpler function of just the transaction, while the Haskell version effectively requires UTxO context.

**Implications:** Our Python implementation of indexedScripts must decide whether to follow the spec (witness scripts only) or the Haskell implementation (witness scripts + reference scripts). If we follow the spec literally, we may miss reference scripts needed for validation in Babbage+ eras. The safest approach is to follow the Haskell implementation and include reference scripts, but document the divergence from the Goguen-era spec. The function signature should accept both tx and utxo as parameters.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 8. 5466c016

**Era:** shelley

**Spec says:** Pool^Tot is calculated as Pool^Pledge + Pool^Deleg, and Pool^% is calculated as Pool^Tot / Ada^Circ, where Ada^Circ represents all ADA in circulation.

**Haskell does:** PoolDistr stores individualPoolStake as a Rational (fraction of active stake) and pdTotalActiveStake as the total stake delegated to registered pools (plus proposal deposits). The denominator is total *active* stake (delegated to registered pools), not total circulating ADA. Additionally, proposal deposits are added to pdTotalActiveStake but are not part of the spec's definition of Pool^Tot.

**Delta:** The spec defines Pool^% as Pool^Tot / Ada^Circ (fraction of ALL circulating ADA), but the Haskell implementation computes the pool's stake fraction as pool_stake / total_active_stake (fraction of only actively delegated stake). Furthermore, pdTotalActiveStake includes proposal deposits which are not mentioned in the spec's pool stake parameters. This means Pool^% in the implementation will be larger than the spec's definition whenever not all ADA is actively delegated.

**Implications:** Python implementation must use total active stake (not total circulating supply) as the denominator when computing individual pool stake fractions, matching the Haskell behavior rather than the literal spec. Must also account for proposal deposits being included in the total active stake denominator.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 9. 5b7bbb3c

**Era:** shelley

**Spec says:** On average, each stake pool obtains rewards proportional to the stake it holds. The spec describes a simplified scheme based on total blocks produced and a fixed ADA distribution per epoch, with treasury split T_E = Distr_E × T and R_E = Distr_E - T_E.

**Haskell does:** The Haskell implementation uses a more complex formula involving: (1) maxPool calculation gated by pledge satisfaction (pledge <= selfDelegatedOwnersStake), returning mempty if pledge is not met; (2) apparent performance (mkApparentPerformance) factoring in decentralization parameter d; (3) pool-specific parameters a0 (pledge influence), nOpt (desired number of pools), cost, and margin; (4) floor-

**Delta:** The spec describes a simplified proportional-to-stake model, while the implementation includes pledge influence (a0), saturation via nOpt, apparent performance based on actual blocks vs expected, pool cost/margin deductions, and a pledge-satisfaction gate. The proportionality holds only 'on average' and 'in the simplified scheme' — the actual implementation is significantly more nuanced with multiple multiplicative factors.

**Implications:** Python implementation must replicate the full formula including: (1) pledge satisfaction check (pledge <= owner_stake, else zero reward), (2) maxPool calculation with a0 and nOpt, (3) apparent performance with decentralization parameter, (4) floor-based rounding for rational-to-coin, (5) separate leader vs member reward calculation, (6) filtering of zero rewards. Simply implementing proportional rewards would be incorrect.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 10. 5eae0f0c

**Era:** plutus

**Spec says:** The CEK machine State Σ has four variants: (1) s;ρ ▷ M (compute), (2) s ◁ V (return), (3) ◆ (error), (4) □(V) (halt). The Compute state consists of stack s, environment ρ, and term M — three components.

**Haskell does:** The Haskell Compute constructor C__'894'_'9659'__222 takes four arguments: Integer, T_Stack_6, T_Env_16, and T__'8866'_14 (term). The first Integer field is not present in the spec's state grammar.

**Delta:** The Haskell implementation adds an Integer (step/budget counter) as the first field of the Compute state, which is not part of the formal spec grammar. The Return, Halt, and Error states match the spec (Return has stack + value, Halt has value, Error has no fields). This Integer likely represents the remaining execution budget or step counter for cost tracking.

**Implications:** The Python implementation must decide whether to include a step/budget counter in the Compute state. If the goal is conformance testing against the spec, the counter is an implementation detail. However, for faithful reimplementation of the Haskell CEK machine (which enforces budget limits), this counter must be included. The counter affects only the Compute state, not Return/Halt/Error states.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 11. 5f4d4316

**Era:** byron

**Spec says:** addrtype is a choice of PubKey=0, Script=1, Redeem=2, or any u64 value strictly greater than 2. All four categories are valid: 0, 1, 2, and any integer 3..2^64-1.

**Haskell does:** The Haskell implementation (1) uses decodeWord8Canonical, limiting to 0-255 instead of u64 (0 to 2^64-1); (2) only accepts values 0 (ATVerKey) and 2 (ATRedeem); (3) REJECTS value 1 (Script) by falling through to the error case; (4) REJECTS all values > 2 (including 3-255) with DecoderErrorUnknownTag.

**Delta:** Three divergences: (A) Script (value 1) is spec-valid but rejected by Haskell — this is the most surprising gap. (B) Values > 2 are spec-valid for future extension but rejected by Haskell. (C) The type is narrowed from u64 to Word8, so values 256-2^64-1 are also rejected. The Haskell implementation is strictly more restrictive than the spec.

**Implications:** Our Python implementation must match the Haskell behavior (accept only 0 and 2, reject everything else including 1) to maintain chain compatibility. If we implement the spec literally (accepting 1 and values > 2), we would accept addresses that the Haskell node rejects, causing consensus divergence. We should decode as a single byte (not u64) and only accept 0 and 2.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 12. 61ed2d96

**Era:** shelley

**Spec says:** Transaction metadata is a mapping from unsigned 64-bit integer keys to values. Values are simple structured terms consisting of integers, text strings, byte strings, lists, and maps.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify implementation conformance since no Haskell code was provided. The Python implementation must be validated directly against the spec.

**Implications:** The Python implementation must ensure: (1) metadata keys are unsigned integers in range [0, 2^64 - 1], (2) metadata values only contain the five allowed types (integers, text strings, byte strings, lists, maps), (3) maps within values may be nested/recursive, (4) the top-level structure is a map, not a list or other type.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 13. 64893bcd

**Era:** shelley

**Spec says:** There are no special fees for metadata. Metadata simply contributes to the transaction size and fees are calculated based on total transaction size. The ledger validation rules affected by metadata are limited to: metadata syntax validation, metadata size limits, and the effect of metadata on transaction size calculation and thus transaction fees.

**Haskell does:** The validateMetadata function performs hash consistency checks (auxDataHash in body must match hash of actual auxData), checks metadata value sizes via validateTxAuxData (gated by protocol version via SoftForks.validMetadata), and enforces presence consistency (both hash and data must be present or both absent). There is no special fee calculation for metadata — fees come from overall transaction 

**Delta:** The spec is high-level about 'no special fees' and 'metadata syntax validation / size limits', while the implementation additionally enforces: (1) hash consistency between tx body auxDataHash and the actual auxiliary data hash, (2) mutual presence — if one of hash or data is present, the other must be too, (3) protocol-version-gated metadata validation via validateTxAuxData. These are implicit in the spec's 'metadata syntax validation' but the hash consistency and mutual presence checks are not 

**Implications:** Python implementation must replicate all four validation paths: (SNothing, SNothing) → ok, (SJust mdh, SNothing) → MissingTxMetadata, (SNothing, SJust md') → MissingTxBodyMetadataHash, (SJust mdh, SJust md') → check hash match AND conditionally validate metadata content. Must also ensure no separate metadata fee is charged — metadata only affects fees through serialized transaction size.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 14. 6eb0f61b

**Era:** shelley

**Spec says:** Ada^Rsv = Ada^Tot - Ada^Circ where Ada^Tot = 45bn ADA and Ada^Circ = 31bn ADA, yielding Ada^Rsv = 14bn ADA. This is a constant defined at Shelley launch.

**Haskell does:** No direct implementation of the constant was found in the provided code. However, the Haskell test deltaR1Ex9 uses a 'reserves9' value in a reward expansion formula: floor((blocksMadeEpoch3 / expectedBlocks) * 0.0021 * reserves9), suggesting reserves are consumed downstream in reward calculations. The exact value of reserves9 and whether it starts at 14bn ADA is not visible from the snippet.

**Delta:** No implementing code was found for the initial reserves constant. The spec defines a precise genesis constant (14bn ADA = 14_000_000_000_000_000 lovelace) but we cannot confirm whether the Haskell codebase initializes reserves to exactly this value or derives it. The test snippet shows reserves being used but not initialized.

**Implications:** The Python implementation must hardcode or derive Ada^Rsv = 14_000_000_000_000_000 lovelace (14bn ADA) at Shelley genesis. The reward expansion formula deltaR1 = floor((blocks_made / expected_blocks) * rho * reserves) must use exact rational arithmetic with floor rounding (rationalToCoinViaFloor). Python's fractions.Fraction or similar exact arithmetic should be used to avoid floating-point errors on these large values.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 15. 7600d638

**Era:** shelley

**Spec says:** For multi-sig scripts, a witness consists of (1) the validator script matching the hash in the script credential, and (2) a set of witnesses for individual key credentials. The validator script determines whether the provided key credential witnesses are sufficient for the funds to be spent.

**Haskell does:** The implementation enforces three conditions: (a) the number of signatures equals requiredSigCount exactly, (b) all signatures are disjoint (no duplicates), and (c) every provided signature verifies against at least one of the listed public keys using SHA256. The test helper `makeWitnessesFromScriptKeys` restricts a key map to only keys matching script hashes and creates VKey witnesses from those,

**Delta:** The spec describes a general framework where 'the validator script determines sufficiency' without specifying the exact validation logic. The Haskell implementation locks down a specific m-of-n scheme with strict equality on signature count, a disjointness check (preventing duplicate signatures), and SHA256-based verification. The test helper only covers witness construction (filtering keys by script hashes and signing), not the actual multi-sig validation conditions (threshold, disjointness, ve

**Implications:** A Python implementation must replicate: (1) exact signature count matching (not >=, but ==), (2) disjointness of signatures (no duplicate sigs allowed), (3) each signature must verify against at least one pubkey in the authorized set using SHA256. The test coverage gap in Haskell means we should add tests for the validator logic itself, not just witness construction.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 16. 7e7d66c9

**Era:** plutus

**Spec says:** ecTag(i) handles three ranges: [0,6] maps to CBOR tag 121+i, [7,127] maps to CBOR tag 1280+(i-7), and all other values use tag 102 with a 2-element array encoding containing i.

**Haskell does:** No implementing Haskell code was found for this rule. Cannot verify implementation correctness.

**Delta:** Missing implementation reference — cannot confirm that the Haskell implementation correctly handles all three ranges, especially boundary values (i=6/7 and i=127/128), negative constructor indices, or very large constructor indices.

**Implications:** Python implementation must carefully implement the three-way branching with correct boundary conditions. Special attention needed for: (1) the boundary between compact ranges at i=6/7, (2) the boundary between medium and general encoding at i=127/128, (3) negative constructor indices falling into the 'otherwise' case, (4) correct CBOR major type 6 encoding for tag headers and major type 4 for the array head in the general case.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 17. 90c09f64

**Era:** alonzo

**Spec says:** runPLCScript returns a pair (IsValidating × ExUnits), meaning it returns both the validation result AND the remaining execution units after script execution. This allows tracking of remaining budget.

**Haskell does:** The Haskell/Agda implementation defines ⟦_⟧,_,_,_ as returning Bool (not a pair). It calls runPLCScript cm s eu d and returns only a Bool. The remaining ExUnits are not returned or tracked. Additionally, the argument order differs: the spec says (CostMod, ScriptPlutus, [Data], ExUnits) but the implementation passes (CostModel, Script, ExUnits, [Data]) - ExUnits and Data are swapped.

**Delta:** 1) Return type mismatch: spec returns (IsValidating × ExUnits) but implementation returns Bool only - remaining execution units are discarded. 2) Argument order: spec has [Data] before ExUnits, implementation has ExUnits before [Data].

**Implications:** For the Python implementation: (1) We need to decide whether runPLCScript should return remaining ExUnits or just a bool. The Agda formal spec simplifies this to Bool, suggesting the remaining-units tracking may be an implementation detail handled elsewhere (e.g., by the Plutus evaluator internally). (2) The argument order for runPLCScript should follow whichever convention we choose, but we must be consistent. (3) The collectPhaseTwoScriptInputs function assembles Data arguments as: getDatum ++

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 18. a8788209

**Era:** alonzo

**Spec says:** The `indexof` function is overloaded with four signatures that find the index of an item in the ordered representation of a collection: (1) DCert in a certificate sequence, (2) AddrRWD in a withdrawal map, (3) TxIn in a set of transaction inputs, (4) CurrencyId in a Value. The ordering of sets/maps is implementation-dependent, but list ordering is unambiguous.

**Haskell does:** No implementing Haskell code was found for `indexof`.

**Delta:** The function is specified in the formal spec but no Haskell implementation was located. This means we cannot verify implementation-specific ordering choices (e.g., how TxIn sets or Wdrl maps are sorted). The Python implementation must choose a canonical ordering for sets and maps that is consistent with whatever the ledger uses on-chain (likely lexicographic/CBOR-canonical ordering).

**Implications:** The Python implementation must define a deterministic ordering for each overload. For DCert lists, the index is simply the list position. For Wdrl (a map), AddrRWD keys must be sorted in some canonical order. For TxIn sets, (TxId, Ix) pairs must be sorted canonically. For Value, CurrencyId (PolicyId) keys must be sorted. The chosen ordering must match the Cardano node's CBOR canonical ordering to produce correct redeemer pointers/indices.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 19. abb7b18b

**Era:** plutus

**Spec says:** The CBOR encoder for Data objects is defined with five cases: Map uses definite-length head (major type 5), List uses indefinite-length array (major type 4) with break byte, Constr uses ecTag followed by indefinite-length array with break, I uses eZ integer encoding, B uses eBS bytestring encoding.

**Haskell does:** No implementing Haskell code was found for review. The Haskell test witsDuplicatePlutusData shows a witness set encoding with a map of length 1, key 4, value being a tag-258 set of length 2 containing two copies of Data (I 0), which tests duplicate plutus data in witness sets rather than the core Data encoder directly.

**Delta:** Cannot verify implementation correctness since no Haskell source for the Data encoder was provided. The Haskell test focuses on a higher-level witness set structure (duplicate plutus data) rather than directly testing each case of the e_data encoder. Key areas that need verification: (1) Map uses definite-length vs indefinite-length encoding, (2) List and Constr use indefinite-length encoding, (3) ecTag mapping for constructor indices (121-127 for 0-6, 1280+ for 7-13, tag 102 fallback for others

**Implications:** Python implementation must ensure: Maps use definite-length CBOR major type 5 heads, Lists use indefinite-length arrays (0x9f...0xff), Constr uses the correct tag mapping (121+i for i<7, 1280+(i-7) for 7<=i<14 or similar, tag 102 for general case) followed by indefinite array, integers use proper eZ encoding, bytestrings use eBS with chunking for long values.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 20. abfa2cc8

**Era:** alonzo

**Spec says:** TxBody is a product of 12 fields: (1) ℙ(TxIn) inputs, (2) Ix→TxOut indexed outputs, (3) [DCert] certificates, (4) Value forge, (5) ExUnits txexunits, (6) Coin txfee, (7) Slot×Slot validity interval, (8) Wdrl withdrawals, (9) Update proposals, (10) PPHash? optional, (11) RdmrsHash? optional, (12) MetaDataHash? optional.

**Haskell does:** AlonzoTxBody pattern has 14 fields: (1) Set TxIn (inputs), (2) Set TxIn (collateral inputs - not in spec), (3) StrictSeq TxOut (outputs as sequence, not Ix→TxOut map), (4) StrictSeq TxCert (certificates), (5) Withdrawals, (6) Coin (fee), (7) ValidityInterval, (8) StrictMaybe Update, (9) Set (KeyHash Guard) (required signers - not in spec), (10) MultiAsset (mint/forge - MultiAsset not full Value), 

**Delta:** Major structural divergences: (A) Spec has ExUnits in TxBody; Haskell does not (ExUnits are per-redeemer in the witness set instead). (B) Spec has separate PPHash? and RdmrsHash?; Haskell merges them into single ScriptIntegrityHash. (C) Haskell adds collateral inputs (Set TxIn), required signers (Set KeyHash), and optional Network fields not in spec. (D) Outputs are StrictSeq (positional indexing) rather than explicit Ix→TxOut map. (E) Forge/mint field is MultiAsset (no Ada component) rather tha

**Implications:** Python implementation must follow the Haskell/on-chain reality rather than the spec for serialization and validation correctness: (1) No ExUnits field in TxBody - execution units are per-redeemer in witnesses. (2) Use ScriptIntegrityHash as a single optional hash covering both protocol params and redeemers. (3) Include collateral inputs, required signers, and optional network ID fields. (4) Outputs should be a sequence (index derived from position) not an explicit map. (5) Mint/forge field shoul

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 21. b45f716e

**Era:** plutus

**Spec says:** Bytestrings in Plutus Data CBOR encoding must be serialised as sequences of blocks, each block at most 64 bytes long. Not all valid CBOR bytestring encodings are accepted — only those conforming to this chunking restriction.

**Haskell does:** No implementing Haskell code was provided for analysis. The implementation likely uses indefinite-length CBOR bytestring encoding with 64-byte maximum chunk sizes, and the decoder rejects any bytestring chunk exceeding 64 bytes.

**Delta:** Without the Haskell implementation, we cannot verify the exact chunking strategy (e.g., whether short bytestrings <= 64 bytes use definite-length encoding or still use indefinite-length with a single chunk, and the exact error handling for oversized chunks). The Python implementation must match the exact encoding choices to ensure binary compatibility.

**Implications:** The Python implementation must: (1) split bytestrings into chunks of at most 64 bytes when encoding Plutus Data to CBOR, (2) reject any CBOR-encoded bytestring where a chunk exceeds 64 bytes during decoding, (3) produce byte-identical output to the Haskell implementation for the same input to ensure on-chain compatibility. Without the reference implementation, we need to use golden test vectors from the Haskell test suite or on-chain data to validate exact encoding format.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 22. b5aed901

**Era:** shelley

**Spec says:** The hash of the transaction metadata is included in the transaction body. Because it is part of the body, it is covered by all transaction signatures, enabling integrity checking and authentication of the metadata.

**Haskell does:** The provided Haskell code snippet `transDataHash safe = PV1.DatumHash (transSafeHash safe)` translates a SafeHash into a PV1.DatumHash. This is a datum hash translation function, not a metadata hash inclusion function. The actual metadata hash inclusion in the transaction body is handled elsewhere in the codebase (likely in the TxBody data type definition where an optional metadata hash field is i

**Delta:** The provided Haskell code does not implement the spec rule about metadata hash inclusion in the transaction body. It implements datum hash translation for Plutus, which is a different concept. The actual metadata hash inclusion is likely in the TxBody type definition (e.g., `adHash` or `txMDHash` field) and the body hash computation that feeds into signature verification.

**Implications:** For the Python implementation: (1) The metadata hash field must be included in the transaction body serialization so that it is covered by signatures. (2) Do not confuse datum hashes (Plutus script data) with metadata/auxiliary data hashes. (3) The Python TxBody class must have an optional metadata hash field, and CBOR serialization of the body must include it when present. (4) Signature verification must implicitly cover the metadata hash since it covers the entire body hash.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 23. b7d0bb22

**Era:** alonzo

**Spec says:** The UTxO-inductive rule checks that all inputs exist in UTxO: txins(txb) ⊆ dom(utxo). The spec only checks transaction inputs against the UTxO domain.

**Haskell does:** The Haskell implementation computes inputsAndCollateral = txins(txb) ∪ collateral(txb) and checks (txins txb) ∪ (collateral txb) ⊆ dom utxo. This means collateral inputs are also validated to exist in the UTxO, which is stricter than the spec's stated precondition 4.

**Delta:** The Haskell code validates that both regular inputs AND collateral inputs exist in the UTxO, whereas the spec rule only explicitly requires txins(txb) ⊆ dom(utxo). Additionally, the Haskell code includes several checks not in the extracted spec: (1) validateOutsideForecast for epoch info slot-to-UTC conversion, (2) validateOutputTooBigUTxO (max value size per output), (3) validateOutputBootAddrAttrsTooBig (bootstrap address attribute size ≤ 64), (4) validateWrongNetwork / validateWrongNetworkWit

**Implications:** Python implementation must: (1) validate collateral inputs exist in UTxO in addition to regular inputs, (2) implement all the additional network/size/forecast validations the Haskell code performs, (3) can skip the adaID forge check if the MultiAsset type structurally excludes Ada, (4) handle the IsValid True vs False branching for phase-2 validation failure (collateral processing).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 24. c5cc6323

**Era:** plutus

**Spec says:** When inputs [V_1, ..., V_n] are compatible with the type signature αbar(b) = [τ_1, ..., τ_n] of built-in function b under some type substitution S, each input V_i is denotated at type T_i = S*(τ_i), the denotation of b under S is applied, and the result is reified back into a syntactic value.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify whether the implementation correctly performs type-directed denotation of each argument, applies the built-in's semantic function under the inferred type substitution, and reifies the result. The entire Eval(b, [V_1,...,V_n]) pipeline is unverified.

**Implications:** The Python implementation must correctly implement: (1) type unification to find substitution S such that [V_1,...,V_n] ≈_S αbar(b), (2) extension of S to each τ_i to produce concrete types T_i, (3) denotation of each V_i at type T_i, (4) application of ⟦b⟧_S to the denotations, and (5) reification of the result. Without reference code, we must test against the spec directly.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 25. c6cc26ef

**Era:** plutus

**Spec says:** When returning value V to a right frame containing VBuiltin(b, V̄, [ι]) where ι ∈ Uni# ∪ * (indicating the last expected argument is a base/ground type or kind *), transition to EvalCEK(s, b, V̄ ⌢ V) to evaluate the fully-saturated builtin.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** The implementation for this CEK return rule (builtin final term argument via right frame) is missing. The rule requires: (1) pattern matching on the top continuation frame being a right frame with VBuiltin, (2) checking that the remaining expected argument type list is a singleton [ι] with ι ∈ Uni# ∪ *, (3) appending the returned value V to the accumulated args V̄, and (4) transitioning to builtin evaluation.

**Implications:** The Python implementation must correctly handle this specific transition: when the last expected argument for a builtin is delivered via the return path, the builtin must be immediately evaluated with all accumulated arguments. The condition ι ∈ Uni# ∪ * distinguishes this final-argument rule from the non-final-argument accumulation rule. Getting this wrong could cause builtins to never execute or to execute with incomplete arguments.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 26. ca99a5bb

**Era:** plutus

**Spec says:** CEK stack frames are: (1) force frame, (2) left application to term [_ (M,ρ)], (3) left application to value [_ V], (4) right application of value [V _], (5) constructor frame (constr i V̄ (M̄, ρ)), (6) case scrutinee frame (case (M̄, ρ)). These are the frames for the CEK machine as specified in the Plutus Core specification.

**Haskell does:** The Haskell Frame type defines: FrameApplyFun (Environment, Value) corresponding to [V _], FrameApplyArg (Environment, Term) corresponding to [_ N], FrameTyInstArg (Type) corresponding to {_ A} type instantiation, FrameUnwrap corresponding to (unwrap _), and FrameWrap for wrapping. It lacks: force frame, constructor frame (constr i V̄ (M̄, ρ)), and case scrutinee frame (case (M̄, ρ)). It has extra

**Delta:** Major structural divergence: (1) The spec defines 6 frame types for a modern Plutus Core CEK machine (with force, constr, case), while the Haskell code defines 5 different frame types for an older/different variant (with type instantiation, unwrap, wrap). (2) The spec's force frame is absent; instead FrameTyInstArg handles type-level application. (3) The spec's constructor and case frames are entirely missing from the Haskell code, suggesting this implementation predates the addition of sums-of-

**Implications:** The Python implementation should follow the spec, not this Haskell code. The Haskell code appears to be from an older or simplified CEK machine variant (possibly the untyped or typed lambda calculus subset without sums-of-products). For our Python implementation: (1) We must implement all 6 spec frame types including force, constr, and case. (2) We should NOT implement FrameTyInstArg, FrameUnwrap, or FrameWrap unless required by a different spec rule for the typed variant. (3) The distinction be

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 27. cb8494a7

**Era:** shelley

**Spec says:** Perf_E is the ratio of actual blocks produced in Epoch E to the expected average number of blocks that should be produced in an Epoch, derived from the number of slots in the Epoch.

**Haskell does:** The Haskell test (alicePerfEx9) computes performance using the `likelihood` function which takes (blocks, leaderProbability, epochSize) — this is a log-likelihood computation, not a simple ratio. The leaderProbability itself factors in activeSlotCoeff, pool relative stake, and the decentralisation parameter d. This is more sophisticated than a simple ratio: it's a probabilistic model of expected b

**Delta:** The spec describes Perf_E as a simple ratio (actual/expected), but the implementation uses a likelihood-based probabilistic model that accounts for per-pool leader probability (which depends on stake, active slot coefficient, and decentralisation parameter). The 'expected average' in the spec is operationalized as a binomial likelihood rather than a simple division.

**Implications:** The Python implementation must use the likelihood function (essentially a binomial/Poisson log-likelihood over epoch slots) rather than implementing a naive ratio. The function signature is likelihood(blocks, leader_probability, epoch_size) where leader_probability = leaderProbability(activeSlotCoeff, poolRelativeStake, d). Getting the math wrong here would produce incorrect pool reward calculations.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 28. de4cb349

**Era:** plutus

**Spec says:** EvalCEK(s, b, [V_1,...,V_n]) evaluates a fully-saturated builtin by calling Eval(b, [V_1,...,V_n]). On error, the CEK machine transitions to the error state. On success with result (V' | V'_1,...,V'_m), it pushes AppLeftFrames for extra values V'_m...V'_1 onto the stack and returns V'.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** Cannot verify implementation correctness since no Haskell code was provided. The spec describes a specific stack manipulation pattern where extra result values are pushed as application frames in reverse order (V'_m outermost/top, V'_1 innermost/closest to original stack s).

**Implications:** Python implementation must: (1) correctly invoke the builtin evaluator, (2) handle error results by transitioning to the CekError state, (3) on success with extra values, push AppLeftFrames in the correct order (V'_m on top down to V'_1), and (4) transition to the Return state with the primary value V'. The frame ordering is critical — V'_1 is applied first to V', then V'_2 to that result, etc.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 29. e1c57fb3

**Era:** shelley

**Spec says:** T_E = Distr_E × T, where T is the Treasury Top Slice Percentage (10%), and T_E is expected to be ADA 384K. This amount is deducted from the total distribution before rewards are allocated to StakePools.

**Haskell does:** No implementing Haskell code was found for this specific treasury top slice calculation.

**Delta:** Cannot verify whether the implementation correctly applies the formula T_E = Distr_E × T, whether it uses integer arithmetic (floor/truncation) for the lovelace computation, or whether the deduction happens before stake pool reward distribution. The rounding behavior is particularly important since Distr_E × T may not yield an exact integer in lovelace.

**Implications:** The Python implementation must: (1) implement T_E = Distr_E × T with the correct rounding/truncation semantics (likely floor to lovelace), (2) ensure T_E is deducted from Distr_E before any stake pool reward calculation, (3) use T = 0.10 (or the protocol parameter tau) as the treasury fraction. Without reference Haskell code, the rounding behavior should be tested against known on-chain values or golden test vectors from the Cardano testnet.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 30. ebe8d68d

**Era:** plutus

**Spec says:** The extended universe of polymorphic types U# is defined inductively as U#_0 = Uni_0 ∪ Var_#, then closed under type operators, yielding U# = ⋃{U#_i : i ∈ N+}. This allows type variables from Var_# to appear anywhere ground types could appear in built-in type expressions.

**Haskell does:** No implementing Haskell code was found for this rule.

**Delta:** No implementation exists to compare against. The spec defines a fundamental type universe construction that must be faithfully represented in any implementation — ground built-in types and #-variables as the base, with recursive application of type operators to build polymorphic types.

**Implications:** The Python implementation must: (1) represent the base universe Uni_0 of ground built-in types, (2) represent Var_# (hash-variables / polymorphic type variables), (3) allow type operators to be applied to elements of U# recursively, (4) ensure that membership in U# is decidable (i.e., we can validate that a given type expression is well-formed in U#), and (5) clearly distinguish U# from the monomorphic universe Uni (which does not contain Var_# elements).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 31. ef1e8117

**Era:** shelley

**Spec says:** Pool^% = Pool^Tot / Ada^Circ, where Ada^Circ is the total ADA in circulation. The denominator is all circulating ADA.

**Haskell does:** The PoolDistr type uses pdTotalActiveStake (total stake delegated to registered stake pools, plus proposal-deposits) as the denominator, not total circulating ADA. The individualPoolStake Rational is computed as pool's stake / pdTotalActiveStake. The existing test confirms this: bobPoolStake = bobInitCoin / activeStakeEx5, where activeStakeEx5 is the total active (delegated) stake, not total circu

**Delta:** The denominator differs: spec says Ada^Circ (all circulating ADA), but implementation uses total active delegated stake (which excludes undelegated ADA, ADA in the reserves, treasury, etc.). Additionally, pdTotalActiveStake includes proposal-deposits which are not mentioned in the spec formula.

**Implications:** Python implementation must use total active delegated stake as the denominator (not total circulating ADA) to match the Haskell implementation. The pool stake fraction is relative to delegated stake, not circulating supply. Proposal deposits are added to the total active stake denominator. This is a significant semantic difference from the spec that affects reward calculations.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 32. f74b4772

**Era:** plutus

**Spec says:** The Constr case of the Data type is encoded using CBOR tags based on an early version of a proposed CBOR extension for discriminated unions (CBOR alternatives). The encoding scheme maps constructor indices to specific CBOR tags: indices 0-6 map to tags 121-127, indices 7-127 map to tags 1280-1400, and all other indices use tag 102 with a general two-element list encoding.

**Haskell does:** No implementing Haskell code was provided for review. The existing test (witsDuplicatePlutusData) tests a witness set containing duplicate Plutus Data items encoded as integers (I 0) within a tag-258 (set) tagged list, embedded in a map with key 4.

**Delta:** Cannot verify implementation correctness since no Haskell encoding/decoding code was provided. The test only exercises the trivial I(0) data case within a witness structure, not the Constr tag encoding scheme itself (tags 121-127, 1280-1400, or 102).

**Implications:** The Python implementation must correctly implement all three tag ranges for Constr encoding: compact (121+i for i in 0..6), medium (1280+(i-7) for i in 7..127), and general (tag 102 with [index, args] for i >= 128 or i < 0). Without reference Haskell implementation code, we must rely on the spec and the plutus-core documentation for correctness. The duplicate data test suggests that plutus data witness sets (tag 258) must handle duplicates properly.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 33. f75021ca

**Era:** plutus

**Spec says:** Unload(ρ, M) performs iterated capture-avoiding substitution: for an environment ρ = [x₁ ↦ V₁, …, xₙ ↦ Vₙ], it substitutes unload(Vᵢ) for xᵢ in M, with the rightmost (most recent) bindings substituted first. Each Vᵢ is first recursively discharged from a CEK value to a Plutus Core term via unload before substitution.

**Haskell does:** No implementing Haskell code was found for this rule. The CEK machine in the Haskell reference implementation likely implements this as part of its discharge/readback mechanism, but the specific code was not provided for analysis.

**Delta:** Cannot confirm whether the Haskell implementation matches the spec regarding: (1) substitution order (rightmost-first), (2) capture-avoiding substitution correctness, (3) recursive discharge of nested CEK values before substitution. The absence of code means we must implement purely from the spec.

**Implications:** The Python implementation must: (1) implement Unload as iterated substitution over all environment bindings, (2) ensure rightmost-first substitution order (which matters if the environment has shadowed bindings or if substitution order affects capture-avoidance), (3) recursively call unload on each CEK value before substituting, (4) use proper capture-avoiding substitution (alpha-renaming bound variables as needed to avoid capture).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 34. f88285fa

**Era:** plutus

**Spec says:** When returning VBuiltin(b, V̄, (ι :: η)) into a force frame and ι ∈ QVar, transition to s ◁ VBuiltin(b, V̄, η), consuming the type argument by dropping ι from expected args while keeping accumulated values V̄ unchanged.

**Haskell does:** No implementing Haskell code was found for this rule. The implementation may exist in the CEK machine module but was not provided for analysis.

**Delta:** Cannot verify implementation correctness since no Haskell code was provided. Key concerns: (1) whether the QVar check is correctly implemented, (2) whether V̄ is truly left unchanged, (3) whether the distinction between this rule (non-final type arg) and a saturated builtin type arg rule is correctly handled.

**Implications:** The Python implementation must: (1) correctly distinguish QVar (type/polymorphic) arguments from term arguments in the expected args list of VBuiltin, (2) only drop the head of expected args without modifying accumulated values V̄, (3) transition to return state (not compute) after consuming the type arg, (4) handle the case where force is applied to a non-QVar head as an error rather than silently consuming it.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

