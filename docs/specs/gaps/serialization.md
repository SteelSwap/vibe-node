# Serialization — Critical Gap Analysis

**26 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. 03388217

**Era:** multi-era

**Spec says:** A canonical encoding must conform to CBOR's defined canonical format, meaning each logical value maps to exactly one byte sequence. Non-canonical encodings (e.g., encoding 0 in four bytes instead of one) are valid CBOR but not canonical.

**Haskell does:** The `toCanonicalCBOR` implementation uses `assumeCanonicalEncoding` which wraps the result of `toEraCBOR` and simply *asserts/assumes* the encoding is canonical without performing any validation or canonicalization. The `isCanonical` property test checks this assumption holds for arbitrary values.

**Delta:** The Haskell code relies on `assumeCanonicalEncoding` as a trust boundary — it assumes the underlying `EncCBOR` instances always produce canonical output, and validates this assumption only through property tests (propTypeIsCanonical). There is no runtime enforcement or canonicalization step. A Python implementation must either (1) ensure its CBOR encoder always produces canonical output by construction, or (2) add a canonicalization/validation pass.

**Implications:** Our Python implementation must guarantee canonical CBOR output. We cannot simply trust an off-the-shelf CBOR library (e.g., cbor2) to produce canonical encodings by default — we need to verify or enforce minimal-length integer encoding, sorted map keys (by raw encoded bytes, length-first), definite-length containers, and no unnecessary tags. Property tests equivalent to propTypeIsCanonical are essential to catch regressions.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. 062b1808

**Era:** shelley-ma

**Spec says:** produced(pp, stpools, txb) = ubalance(outs(txb)) + coinToValue(txfee(txb) + totalDeposits(pp, stpools, txcerts(txb))). The function sums only three components: (1) balance of outputs, (2) transaction fee, and (3) total new deposits.

**Haskell does:** The Haskell implementation computes: balance(outs(txb)) + inject(txb.txfee) + inject(newDeposits pp st txb) + inject(txb.txdonation). It includes a fourth component: txdonation, which represents treasury donations from Conway era onwards.

**Delta:** The Haskell code includes an additional `txdonation` term not present in the spec rule provided. This reflects a Conway-era extension where transactions can donate to the treasury. The spec rule shown appears to be from the Shelley/Mary/Alonzo era before treasury donations were introduced. Additionally, the Haskell code uses `newDeposits` (which may have different semantics than `totalDeposits` depending on era) and `inject` instead of `coinToValue`, though these are likely equivalent.

**Implications:** A Python implementation following only the provided spec rule would fail the preservation-of-value check for any transaction that includes a non-zero treasury donation (Conway era). The Python implementation must include txdonation in the produced calculation to be compatible with the current Haskell implementation. Additionally, care must be taken that `newDeposits` matches `totalDeposits` semantics for the target era.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 3. 112280c8

**Era:** multi-era

**Spec says:** CodecConfig blk is a data family indexed by block type that defines extra configuration needed for (de)serialisation, such as slots per epoch for EBB deserialisation. The configuration is kept as small as possible and ideally empty.

**Haskell does:** The provided code only shows the EncodeDisk typeclass with a default implementation that ignores CodecConfig entirely when a Serialise instance exists. The data family declaration for CodecConfig itself is not shown, nor are any concrete instances for specific block types (e.g., EBB blocks that require epoch size).

**Delta:** The code snippet is only the EncodeDisk class with its default method. It does not show the CodecConfig data family declaration or any instance that actually uses the CodecConfig parameter (such as EBB encoding requiring slots-per-epoch). The default implementation explicitly discards the config (_ccfg), which is only valid for the trivial case where no extra config is needed.

**Implications:** For the Python implementation: (1) We must define CodecConfig as a per-block-type configuration container, potentially as a generic/parameterized class. (2) The default encode path should ignore the config and delegate to a standard serialization method. (3) For block types like EBBs that need slots-per-epoch, we must implement custom encode_disk that actually reads from the CodecConfig. (4) We need to ensure the data family pattern is correctly translated—likely via a registry or type-dispatch 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 4. 16aaa0d8

**Era:** shelley-ma

**Spec says:** produced(pp, stpools, txb) = ubalance(outs(txb)) + coinToValue(txfee(txb) + totalDeposits(pp, stpools, txcerts(txb))). The function sums the unspent balance of outputs, the fee, and total deposits from certificates. There is no donation term.

**Haskell does:** The Haskell implementation computes: balance(outs(txb)) + inject(txb.txfee) + inject(newDeposits pp st txb) + inject(txb.txdonation). It includes an additional 'txdonation' term that is not present in the MA-era spec rule. Additionally, it uses 'newDeposits' rather than 'totalDeposits', and 'balance' rather than 'ubalance'.

**Delta:** 1) The Haskell code includes a 'txdonation' term (inject(txb.txdonation)) which is absent from the MA-era spec formula. This was likely added in the Conway era. 2) The function name 'newDeposits' is used instead of 'totalDeposits' — this may be a renaming or a semantic change in how deposits are computed across eras. 3) 'balance' vs 'ubalance' naming difference (likely cosmetic — both compute the sum of values in a UTxO set).

**Implications:** For a Python implementation targeting the MA (Mary/Allegra) era spec: (1) Do NOT include txdonation in the produced calculation — it does not exist in the MA spec. (2) Use totalDeposits as specified. (3) If implementing for Conway era, the txdonation term must be added. The discrepancy means era-conditional logic may be needed. The 'newDeposits' vs 'totalDeposits' difference should be investigated to ensure deposit calculation semantics match.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 5. 45b9a051

**Era:** multi-era

**Spec says:** When deserialising a block, the original byte-level encoding (possibly non-canonical) must be retained and used to annotate the block. Hashing must be performed on the original annotated serialisation, not a re-serialised canonical encoding.

**Haskell does:** The BlockBody implementation shown is a trivial encode/decode of raw bytes. The actual annotation-preserving logic lives in the 'Annotated' infrastructure (e.g., decodeAnnotator, Annotator types) used by higher-level types like Data, TxDats, Redeemers etc. The roundTripAnnEraTypeSpec test specifically tests that annotated types survive a roundtrip with their original encoding preserved. The BlockB

**Delta:** The provided Haskell code snippet (BlockBody Serialise instance) does not show the annotation-preservation mechanism. The real implementation uses Annotator-based decoding for types like Data, TxDats, and Redeemers. The test suite uses roundTripAnnEraTypeSpec (annotated roundtrip) alongside roundTripEraTypeSpec (plain roundtrip) to verify both paths. A Python implementation must separately handle the annotated decode path to preserve original bytes.

**Implications:** Python implementation must: (1) implement an annotation mechanism that captures original bytes during CBOR decoding, (2) ensure hash computation uses the captured original bytes rather than re-encoded bytes, (3) handle the known Datum non-roundtrip issue (NoDatum is not encoded/decoded), (4) ensure types like Data, BinaryData, TxDats, Redeemers all roundtrip correctly through both annotated and plain paths.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 6. 57a18e8e

**Era:** multi-era

**Spec says:** The storage decoder for annotated types has type `forall s. Decoder s (ByteString -> blk)` — it returns a function that must be applied to the original encoding bytes to produce the fully annotated block. This asymmetry between encoder (blk -> Encoding) and decoder (Decoder s (ByteString -> blk)) is the reason for splitting serialisation classes for storage. Network serialisation handles this diff

**Haskell does:** No implementing code was found to verify the pattern is correctly implemented.

**Delta:** Cannot verify that the annotated decoder pattern (returning ByteString -> blk function) is implemented, nor that the serialisation class split (EncodeDisk/DecodeDisk vs EncodeNodeToNode/DecodeNodeToNode) is properly maintained. Without code, we cannot confirm the asymmetry is handled correctly.

**Implications:** The Python implementation must replicate this asymmetry: the storage decoder must return a callable that accepts the original bytes and produces an annotated block. If this pattern is not followed, annotated blocks will lose their original byte representation, which is needed for hashing and integrity checks. The Python implementation should also maintain separate serialisation interfaces for storage vs network, with the network path using CBOR-in-CBOR instead of the function-returning decoder p

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 7. 61d6bbdb

**Era:** multi-era

**Spec says:** The SerialiseNodeToNode class requires explicit implementations of encodeNodeToNode and decodeNodeToNode parameterised by CodecConfig and BlockNodeToNodeVersion.

**Haskell does:** The Haskell implementation provides default method implementations via the Serialise class that completely ignore both the CodecConfig and the BlockNodeToNodeVersion arguments, falling back to unversioned encode/decode.

**Delta:** The spec describes a versioned, config-aware serialisation interface, but the Haskell code provides a convenience default that silently discards version and config information. Any type that relies on the default implementation will not support version-differentiated wire formats, which may be intentional for simple types but could mask missing version-aware implementations for types that need them.

**Implications:** In a Python implementation: (1) We must be aware that some types may use a trivial CBOR Serialise encoding that ignores config and version — our Python equivalent should handle this case. (2) We should not assume all types use versioned encoding; we need to determine per-type whether the default or a custom implementation is used. (3) For types that do override with version-aware logic, our Python code must faithfully replicate that version-dependent encoding to maintain wire compatibility.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 8. 63479c53

**Era:** multi-era

**Spec says:** Tx is a record with four fields: body (TxBody), wits (TxWitnesses), txsize (N), and txid (TxId). txsize and txid are derived from the serialized form and must be preserved since Cardano serialization is not canonical.

**Haskell does:** AlonzoTx has four fields: atBody (TxBody), atWits (TxWits), atIsValid (IsValid), and atAuxData (StrictMaybe TxAuxData). It does NOT store txsize or txid as explicit fields. Instead, txsize is computed on-the-fly from the serialized bytes (via the Sized wrapper or during validation), and txid is computed by hashing the body. Additionally, AlonzoTx includes atIsValid (a phase-2 validation flag) and 

**Delta:** 1) The spec's txsize and txid fields are not stored in AlonzoTx; they are computed lazily/on-demand. 2) AlonzoTx adds atIsValid and atAuxData fields not present in the spec's Tx record. 3) The spec treats txsize/txid as first-class preserved data from deserialization, while Haskell recomputes them. This works because Haskell preserves the original serialized bytes via 'Memo' pattern for non-canonical serialization support.

**Implications:** Python implementation must decide whether to store txsize and txid explicitly (matching the spec) or compute them on demand (matching Haskell). If storing explicitly, deserialization must capture the original bytes to derive both values. The Python Tx type should also account for IsValid and AuxData fields present in Haskell but absent from the formal spec, as they are needed for real transaction processing.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 9. 6d82dc73

**Era:** byron

**Spec says:** A Byron public key ('pubkey') is defined as raw bytes ('bytes') with no specific length constraint in the CDDL specification.

**Haskell does:** The Haskell implementation serializes/deserializes Byron verification keys as XPub (extended public key) raw bytes via Crypto.HD.xpub/unXPub. The Crypto.HD.xpub function enforces that the input must be exactly 64 bytes (32-byte Ed25519 public key + 32-byte chain code), returning an error for any other length.

**Delta:** The spec says 'bytes' (unbounded), but the implementation constrains this to exactly 64 bytes representing a cardano-crypto XPub (extended verification key). The deserialisation rejects any byte string that is not a valid 64-byte XPub.

**Implications:** Our Python implementation must enforce the 64-byte XPub constraint when deserializing Byron public keys. Simply accepting arbitrary bytes would diverge from the Haskell behavior. We need to use an equivalent Ed25519 extended public key library (e.g., emip3 or PyNaCl with chain code handling) that validates the 64-byte format.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 10. 77805015

**Era:** plutus

**Spec says:** dHead decodes the first byte of a CBOR-encoded bytestring into (remaining bytes, major type 0-7, argument 0 to 2^64-1). The first byte n is split: major_type = div(n,32), additional_info = mod(n,32). If additional_info ≤ 23, argument = additional_info directly. If 24, read 1 byte. If 25, read 2 bytes. If 26, read 4 bytes. If 27, read 8 bytes. Undefined for empty input, too-short input, or addition

**Haskell does:** No implementing Haskell code was found for dHead.

**Delta:** No implementation exists to compare against. The spec defines a partial function (undefined for empty input, too-short input, and additional info values 28-31) that must be faithfully implemented.

**Implications:** The Python implementation must handle all cases: (1) direct argument for additional_info 0-23, (2) multi-byte argument reads for 24-27, (3) raise appropriate errors for additional_info 28-31, empty input, and insufficient bytes. Care must be taken with big-endian byte interpretation for bsToInt_k and ensuring the argument fits in a 64-bit unsigned integer.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 11. 87bb4dba

**Era:** shelley-ma

**Spec says:** The UTxO-inductive rule for MA includes precondition 8: adaID ∉ dom(forge(tx)) — no Ada forging allowed, and precondition 9: for all txout in txouts(txb), getValue(txout) ≥ 0 (all multi-asset output quantities must be non-negative). The min UTxO check is: getCoin(txout) ≥ valueSize(getValue(txout)) * minUTxOValue(pp), scaling by output size.

**Haskell does:** The Haskell implementation does NOT check adaID ∉ dom(forge(tx)) (no Ada forging check) and does NOT explicitly check getValue(txout) ≥ 0 (non-negative multi-asset quantities). The min UTxO check is delegated to validateOutputTooSmallUTxO which may use a simpler check (c ≥ minUTxOValue pp) rather than the size-scaled version. Additionally, the Haskell code includes two extra network ID validation 

**Delta:** Three spec preconditions (no-Ada-forge, non-negative multi-asset quantities, size-scaled minUTxO) appear absent or simplified in the Haskell code. Two network ID checks are present in Haskell but not in the spec excerpt. The fee validation function (validateFeeTooSmallUTxO) takes utxo as an extra parameter beyond what the spec's minfee(pp, tx) suggests, possibly for reference script size calculations in later eras.

**Implications:** Python implementation should: (1) implement the adaID forge check if targeting the MA era spec, (2) implement non-negative multi-asset quantity checks on outputs, (3) implement size-scaled minUTxO checks for MA outputs, (4) include network ID validation checks matching Haskell behavior even though they aren't in this spec excerpt, (5) be aware that validateFeeTooSmallUTxO may need access to the UTxO for reference script fee calculations.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 12. 8a1184b6

**Era:** shelley-ma

**Spec says:** valueSize(v) = k + k' * |{ (pid, aid) : v pid aid ≠ 0 ∧ (pid, aid) ≠ (adaID, adaToken) }|, where k and k' are constants and the set counts the number of distinct non-zero non-Ada (PolicyID, AssetID) pairs in the Value.

**Haskell does:** The Haskell implementation uses utxoEntrySize which computes utxoEntrySizeWithoutVal (=27) + size(v) + dataHashSize(dh). The 'size' function on MaryValue accounts for the serialized size of the entire Value including policy IDs, asset names, and their byte lengths — not just the count of distinct non-zero non-Ada pairs. The spec formula uses only the count of (pid, aid) pairs multiplied by a const

**Delta:** The spec's valueSize formula is a simplified abstraction: k + k' * numAssets. The Haskell implementation computes a more granular size that accounts for (1) the number of distinct policy IDs, (2) the number of assets per policy, and (3) the byte lengths of asset names. This is why outputs with the same number of assets but different name sizes (e.g., smallestName vs largestName 65) yield different min UTxO values in the golden tests. The spec formula would produce the same result for both since 

**Implications:** A Python implementation that literally follows the spec formula (k + k' * numAssets) will NOT match the golden test vectors. The Python implementation must replicate the actual Haskell size calculation for MaryValue, which sums up: (1) a base overhead, (2) per-policy overhead (28 bytes for each policy ID), (3) per-asset overhead, and (4) the actual byte length of each asset name. The coinsPerUTxOWord (or coinsPerUTxOByte in Babbage+) parameter is then applied to this size.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 13. 8b36783b

**Era:** plutus

**Spec says:** An encoder e_X : X → B* is a total function from a set X to a finite bytestring. It is a pure mathematical function with no additional parameters.

**Haskell does:** The Haskell Encoding type is defined as `newtype Encoding = Encoding (Version -> C.Encoding)`, meaning the encoder is parameterized by a Version. The actual CBOR output depends on which protocol version is supplied, making it a family of encoders indexed by Version rather than a single pure function.

**Delta:** The spec defines a single encoder per type, but the Haskell implementation makes encoding version-dependent. The same value can produce different CBOR bytes depending on the Version parameter. This is not captured in the abstract spec.

**Implications:** The Python implementation must account for version-dependent encoding. When translating golden tests, the version/era context (e.g., Alonzo) must be matched exactly. The Python CBOR serialization layer should either accept a version parameter or be configured per-era to match the Haskell behavior. Golden test vectors are only valid for the specific era/version they were generated with.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 14. 8c9d3cea

**Era:** multi-era

**Spec says:** The in-memory representation of blocks, headers, transactions etc. must carry the original serialisation bytes (annotation) alongside the logical fields, because non-canonical CBOR encodings mean multiple distinct byte representations can decode to the same logical value, and the hash must be computed over the original bytes.

**Haskell does:** The Haskell implementation uses the Annotator pattern and roundTripAnnEraTypeSpec to verify that annotated types preserve byte-level identity through serialization round-trips. Types like Data have both annotated (Ann) and non-annotated round-trip tests. The Datum type is known NOT to round-trip (NoDatum is not encoded), which is acknowledged via xdescribe.

**Delta:** No implementing Python code was found. The annotation pattern (carrying original bytes alongside decoded values) needs to be implemented in the Python codebase. Without it, hashing of deserialized-then-reserialized values may produce different hashes than the original, which is a correctness-critical issue for block/transaction validation.

**Implications:** The Python implementation must: (1) implement an annotation mechanism that stores original CBOR bytes alongside decoded values, (2) ensure hash computation uses the original bytes not re-serialized bytes, (3) handle the Datum/NoDatum edge case explicitly, (4) ensure all annotated types (Data, block headers, transactions, etc.) preserve byte-level identity through deserialization.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 15. 9ac64613

**Era:** shelley-ma

**Spec says:** ubalance : UTxO → Value computes the total balance by summing getValue(u) for all entries, returning a Value (multi-asset type encompassing Coin and native tokens with PolicyID/AssetID quantities).

**Haskell does:** The `balance` function sums only Lovelace (Coin) via `sumLovelace . fmap compactTxOutValue`, where compactTxOutValue extracts only the Lovelace component via `txOutValue . fromCompactTxOut`. The existing test `txInBalance` also uses `sumCoinUTxO` which sums only Coin. Multi-asset token quantities are ignored.

**Delta:** The spec defines ubalance as returning a full multi-asset Value (summing all PolicyID/AssetID quantities), but the Haskell implementation only sums the Lovelace/Coin component, discarding native token balances. This is a deliberate simplification in the Shelley-era implementation where multi-asset was not yet supported, but it diverges from the general Babbage/Conway-era spec.

**Implications:** The Python implementation must decide which era to target. For Babbage/Conway conformance, ubalance MUST sum full multi-asset Values (Coin + native tokens). If we only sum Lovelace, we will fail multi-asset balance checks in UTXOW and UTXO rules. The Python implementation should sum the complete Value type to be spec-compliant. Test coverage must verify both the Coin-only path (for Shelley compatibility) and the full multi-asset path.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 16. 9d9e96de

**Era:** shelley-ma

**Spec says:** scriptsNeeded is the union of four sets: (1) validator hashes from script-locked inputs, (2) script credential hashes from script-based reward withdrawals, (3) script addresses intersected with certWitsNeeded, and (4) dom(forge(txb)) — the policy IDs of all tokens being forged/burned. The fourth component is the MA-era addition.

**Haskell does:** The getShelleyScriptsNeeded function computes only three of the four sets: (1) script hashes from script-locked inputs via txinsScriptHashes, (2) script hashes from withdrawal credentials, and (3) script hashes from certificates via getScriptWitnessTxCert. It does NOT include dom(forge(txb)) — the minting/forging policy IDs. This is the Shelley-era implementation; the MA-era must override or exten

**Delta:** The provided Haskell code (getShelleyScriptsNeeded) is the Shelley-era base implementation and is missing the fourth union component: dom(forge(txb)). The MA (Mary) era must add this component, likely via an era-specific override or extension. The spec rule shown is the MA-era version of scriptsNeeded, but the Haskell code shown is the Shelley base. A Python implementation targeting the MA era must include all four components, including minting policy IDs.

**Implications:** A Python implementation must: (1) ensure the MA-era scriptsNeeded includes dom(mint(txBody)) as the fourth component, (2) be aware that the Shelley base only has three components, and (3) correctly layer the MA extension on top of the Shelley base. If we only translate the shown Haskell code, we will miss minting policy script requirements, leading to transactions that forge tokens without requiring the corresponding policy scripts — a critical validation gap.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 17. 9de0dee9

**Era:** byron

**Spec says:** addressid is defined as blake2b-224 hash, implying a single Blake2b-224 hash of the address data.

**Haskell does:** The Haskell implementation uses a two-step hashing process: first it CBOR-serializes the input and hashes it with SHA3-256, then it hashes the resulting SHA3-256 digest with Blake2b-224. The final output is indeed a Blake2b-224 digest, but the input to Blake2b-224 is not the raw address data — it is the SHA3-256 hash of the CBOR-serialized address data.

**Delta:** The spec's CDDL definition only states the output type (blake2b-224), but the Haskell code reveals a double-hashing scheme: CBOR-serialize → SHA3-256 → Blake2b-224. A naive implementation that applies Blake2b-224 directly to the address data (or even to CBOR-serialized data without the intermediate SHA3-256 step) would produce incorrect address identifiers.

**Implications:** The Python implementation MUST replicate the exact two-step process: (1) CBOR-serialize the input using Byron-era protocol version encoding, (2) compute SHA3-256 of the serialized bytes, (3) compute Blake2b-224 of the SHA3-256 digest. Missing either the CBOR serialization step or the intermediate SHA3-256 hash will produce completely wrong address IDs that won't match any Byron-era addresses on-chain.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 18. a8c6d74d

**Era:** shelley-ma

**Spec says:** getOut transforms a TxOut into a UTxOOut by extracting the address and value: getOut(txout) = (getAddr(txout), getValue(txout)). This implies UTxO outputs are (Address, Value) pairs, a projection from TxOut.

**Haskell does:** The Haskell implementation (txouts) does NOT apply a getOut projection. It builds a UTxO map from TxIn to the full TxOut (called 'out') without stripping any fields. The TxOut is used as-is as the UTxO entry value. In later eras (Mary, Alonzo, Babbage), TxOut carries additional fields (e.g., datum hashes, reference scripts, inline datums) that are all preserved in the UTxO.

**Delta:** The spec defines getOut as a projection that extracts only (address, value) from a TxOut, but the Haskell code retains the full TxOut in the UTxO without any projection. In the Shelley era this is effectively equivalent since TxOut is essentially (Address, Value), but in later eras the distinction matters because TxOut contains additional fields (datum hash, inline datum, reference script) that the spec's getOut would discard.

**Implications:** For a Python implementation: (1) In Shelley era, UTxO entries can be modeled as (Address, Value) pairs matching the spec literally. (2) In later eras, we need to decide whether to follow the spec's getOut projection or the Haskell approach of keeping full TxOut. The Haskell approach is the pragmatic one since later specs update getOut to include additional fields. (3) The txouts function also handles the construction of TxIn keys (pairing txId with output indices starting from minBound/0), which

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 19. b0a8e8a3

**Era:** multi-era

**Spec says:** Ix is an abstract type representing an index used to identify a specific output within a transaction. The spec treats Ix as an abstract type without specifying its concrete representation or range.

**Haskell does:** TxIx is implemented as a newtype wrapper around Word16, giving it a concrete range of 0 to 65535. It derives Enum and Bounded, meaning minBound = TxIx 0 and maxBound = TxIx 65535.

**Delta:** The spec leaves Ix abstract, but the Haskell implementation concretizes it as Word16 (unsigned 16-bit integer). This constrains the maximum number of outputs per transaction to 65536 (indices 0-65535). Any Python implementation must match this Word16 representation to ensure serialization compatibility and proper bounds checking.

**Implications:** The Python implementation must: (1) use a 16-bit unsigned integer for TxIx (range 0-65535), (2) ensure CBOR encoding/decoding matches Word16 semantics, (3) reject values outside the 0-65535 range, (4) maintain the same Eq/Ord behavior as unsigned integer comparison.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 20. c06bf8f1

**Era:** plutus

**Spec says:** Extra padding bits are appended at the end of the encoding to ensure the total number of bits is a multiple of 8, allowing the serialised output to be treated as a bytestring.

**Haskell does:** No implementing code was found in the provided sources. The actual implementation likely lives in the 'flat' serialisation library used by plutus-core (the 'flat' Haskell package), which uses a specific padding convention: padding bits are all 1-bits followed by enough bits to reach a byte boundary, with a minimum of 1 padding bit.

**Delta:** The spec describes the padding requirement abstractly without specifying the exact padding bit values or the minimum padding. The actual 'flat' encoding convention uses a specific scheme (a 0 bit to mark end-of-content, then 1-bits to fill the byte) or similar. Without the implementing code, the exact padding convention cannot be verified against the spec text alone.

**Implications:** The Python implementation must match the exact padding convention used by the Haskell 'flat' library (not just any padding to a byte boundary). If the padding scheme differs, serialised programs will not be interoperable. The Python implementation should be tested against Haskell-produced reference bytestrings to ensure byte-level compatibility.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 21. d70b1ed3

**Era:** shelley

**Spec says:** address_id = blake2b44(sha3_256(b)) where b = 0x830082005840 | pubkey_bytes | chain_code_bytes | attributes_bytes. The blake2b output is 224 bits (28 bytes).

**Haskell does:** The implementation constructs `bytes = prefix <> keyBytes <> cc <> attributes` where prefix is the literal bytestring '\131\00\130\00\88\64' (which is 0x830082005840 in hex). It then applies SHA3-256 via `hash_SHA3_256`, followed by `hash_crypto` which uses ADDRHASH (Blake2b_224) to produce the final KeyHash. The two-step hash matches the spec. However, the hash_crypto function uses `hashWith @ADD

**Delta:** The Haskell `Hash.hashWith @ADDRHASH id` applies Blake2b_224 directly to the raw SHA3-256 output bytes without any additional CBOR tag wrapping. However, the cardano-ledger Hash module's `hashWith` may include a CBOR tag prefix depending on the version. A Python implementation must ensure it applies plain Blake2b-224 to the raw SHA3-256 digest bytes, matching the exact behavior of `Hash.hashWith @ADDRHASH id` (which passes bytes through `id` — i.e., no additional serialization).

**Implications:** Python implementation must: (1) construct the prefix as exactly bytes 0x830082005840, (2) concatenate pubkey (32 bytes) + chaincode (32 bytes) + attributes (CBOR-encoded), (3) apply SHA3-256, (4) apply Blake2b-224 (28-byte output) to the SHA3-256 digest. The `id` in `hashWith @ADDRHASH id` means no extra wrapping — just raw Blake2b-224 on raw bytes. Must verify against golden vectors from the Haskell test.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 22. db403a6b

**Era:** byron

**Spec says:** A Byron main block ('mainblock') is serialized as a 3-element CBOR structure containing [header (blockhead), body (blockbody), extra (attributes array)]. This is the top-level wire format.

**Haskell does:** The Haskell implementation wraps Byron blocks in a 2-element discriminated union: [tag, pre-encoded-block-bytes]. Tag 0 = boundary block (EBB), tag 1 = main block. The inner pre-encoded bytes for a main block (tag=1) presumably contain the 3-element [header, body, extra] structure from the spec, but the top-level encoding is NOT the 3-element mainblock directly — it is a 2-element [discriminator, 

**Delta:** The spec defines 'mainblock' as the 3-element [header, body, extra] structure, but the actual on-wire format has an additional outer layer: a 2-element CBOR list [Word tag, pre-encoded block bytes]. The spec's 'mainblock' structure corresponds to the inner payload when tag=1, not to the outermost serialization. The Haskell code uses CBOR.encodePreEncoded to embed already-serialized block bytes, meaning the 3-element structure exists within the annotation bytes but is not directly constructed by 

**Implications:** Our Python implementation must NOT serialize a Byron main block as just the 3-element [header, body, extra]. Instead, it must wrap all Byron blocks in a 2-element list [tag, block_bytes] where tag distinguishes main (1) from boundary (0) blocks. The 3-element mainblock structure from the spec applies only to the inner block payload. Failing to include the outer discriminated union wrapper will produce wire-incompatible serialization that Cardano nodes will reject.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 23. dc03f986

**Era:** multi-era

**Spec says:** TxOut is a triple of (Addr, Value, Maybe DataHash) — three fields where the third is an optional data hash.

**Haskell does:** TxOut has four fields: Address, Value, OutputDatum (which generalizes Maybe DataHash to include inline datums), and Maybe ScriptHash (reference script). This reflects the Babbage-era evolution beyond the Alonzo spec.

**Delta:** The Haskell implementation extends the spec's 3-tuple to a 4-tuple, replacing Maybe DataHash with the richer OutputDatum type (which can be NoOutputDatum, OutputDatumHash, or OutputDatum with inline datum) and adding an optional reference script field. The Alonzo-era AlonzoTxOut used in tests matches the spec more closely with (Addr, Value, StrictMaybe DataHash).

**Implications:** Our Python implementation must support both the Alonzo-era 3-field TxOut (Addr, Value, Maybe DataHash) for Alonzo-era validation and the Babbage+ 4-field TxOut for later eras. The min UTxO calculation depends on the serialized size of TxOut, so the field structure directly impacts correctness. We need to ensure AlonzoTxOut and BabbageTxOut are both modeled correctly.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 24. e7a21c6a

**Era:** multi-era

**Spec says:** TxBody is a record with exactly 5 fields: txins (P TxIn), txouts (Ix ⇀ TxOut), txfee (Coin), txvote (List GovVote), and txprop (List GovProposal). The txouts field is an indexed finite map (Ix ⇀ TxOut), and the spec includes governance fields (txvote, txprop) suggesting Conway-era modeling.

**Haskell does:** BabbageTxBodyRaw has 16 fields including txins, outputs (as StrictSeq of Sized TxOut, not an Ix-keyed map), fee, plus many additional fields not in the spec: collateralInputs, referenceInputs, collateralReturn, totalCollateral, certs, withdrawals, validityInterval, update, reqSignerHashes, mint, scriptIntegrityHash, auxDataHash, networkId. Notably, governance fields txvote and txprop are entirely 

**Delta:** 1) The spec's txouts is modeled as Ix ⇀ TxOut (explicit finite map), while Haskell uses StrictSeq (Sized (TxOut era)) where the index is implicit from position. 2) The spec includes txvote and txprop (Conway governance), but the Babbage implementation has neither — these would appear in ConwayTxBody instead. 3) Haskell has 11 additional fields (collateral inputs, reference inputs, collateral return, total collateral, certs, withdrawals, validity interval, update, required signer hashes, mint, sc

**Implications:** For a Python implementation: (1) If targeting the spec literally, txouts should be a dict-like mapping from Ix to TxOut, but the Haskell approach of using a sequence with implicit indexing is equivalent and may be simpler. (2) Governance fields (txvote, txprop) are Conway-era and should not be included in Babbage-era TxBody — the Python implementation must be era-aware. (3) Many Haskell fields (collateral, reference inputs, mint, validity interval, etc.) are needed for real transaction processin

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 25. f6751015

**Era:** byron

**Spec says:** vsssec is encoded as raw bytes using the Binary instance for Scrape.Secret, a type from the SCRAPE Verifiable Secret Sharing scheme.

**Haskell does:** No implementing Haskell code was found for this rule. The Binary instance for Scrape.Secret (from the pvss-haskell / cardano-crypto package) determines the exact byte layout, but this implementation was not provided for review.

**Delta:** Without the Haskell implementation of the Binary instance for Scrape.Secret, we cannot verify the exact byte-level encoding format (e.g., compressed vs uncompressed point, endianness, length prefixing). The spec only says 'bytes' which is maximally permissive in CDDL, but the actual encoding is determined entirely by the Binary instance which is opaque from the spec alone.

**Implications:** The Python implementation must exactly match the Binary instance serialization format for Scrape.Secret from the pvss-haskell / cardano-crypto library. Without the reference implementation, we risk encoding mismatches. We should extract test vectors from real Byron-era blocks or the Haskell test suite to validate our encoding. Key unknowns: (1) exact byte length of the encoded secret, (2) whether it uses compressed or uncompressed curve point representation, (3) any length prefix or framing with

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 26. f7671b7b

**Era:** plutus

**Spec says:** stoi(l) is defined as big-endian: for l = l' · n (where n is the LAST byte), stoi(l) = 256 × stoi(l') + n. This means the leftmost byte is the most significant.

**Haskell does:** byteStringToNum uses BS.foldr with (\w i -> i `shiftL` 8 + fromIntegral w) 0, which processes bytes from right to left, accumulating by shifting left. For a ByteString [b0, b1, b2], foldr processes b0 first (outermost), then b1, then b2 (innermost). The innermost (b2) gets shifted the most. However, BS.foldr iterates from index 0 (leftmost) outward, so the final result is: b2 is processed first as

**Delta:** The spec defines stoi as big-endian (leftmost byte is most significant), but the Haskell implementation computes a little-endian interpretation (rightmost byte is most significant). For bytestring [0x01, 0x02], the spec gives 258 (1*256+2), but the Haskell code gives 513 (2*256+1).

**Implications:** The Python implementation MUST follow the spec (big-endian), i.e., equivalent to int.from_bytes(bs, 'big'). If we naively translated the Haskell foldr pattern, we would get little-endian which is wrong per the spec. However, the Haskell code may be correct in context if ByteStrings in the Cardano codebase are stored in reversed/little-endian order internally, or if itos also uses the matching little-endian convention, making roundtrips consistent. The Python implementation should use big-endian 

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

