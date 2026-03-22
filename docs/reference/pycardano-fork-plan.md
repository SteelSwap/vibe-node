# pycardano Fork Plan

## Package Info
- **Current version:** 0.19.2
- **PyPI:** https://pypi.org/project/pycardano/
- **Source:** https://github.com/Python-Cardano/pycardano
- **Our usage:** 13 files, 32 import sites

## Usage Profile

**Most-used modules:**
- `pycardano.hash` — ScriptHash, TransactionId, VerificationKeyHash, PoolKeyHash (7 files)
- `pycardano.certificate` — StakeRegistration, StakeDelegation, StakeDeregistration, PoolRegistration, PoolRetirement, PoolParams (3 files)
- `pycardano.witness` — TransactionWitnessSet, VerificationKeyWitness (4 files)
- `pycardano.address` — Address (2 files)
- `pycardano.plutus` — RawPlutusData, PlutusData (2 files)
- `pycardano.transaction` — Transaction, TransactionBody (1 file)
- `pycardano.metadata` — AuxiliaryData (2 files)
- `pycardano.nativescript` — NativeScript (1 file)
- `pycardano.key` — VerificationKey (1 file)
- `pycardano.network` — Network (1 file)

## Known Issues (from dependency audit — 11 workarounds)

### Issue #1: Incomplete Conway/Babbage field support (CRITICAL)
- `TransactionBody.from_cbor()` fails on Conway fields: `voting_procedures`, `proposal_procedures`, `treasury_value`, `donation`
- Our code wraps every deserialization in `try/except` and falls back to raw dicts
- Body type throughout codebase is `TransactionBody | dict`
- **Fix:** Add Conway field definitions to `TransactionBody`

### Issue #2: No Block or BlockHeader types (HIGH)
- pycardano has zero block-level types — only handles transactions
- Our entire block decoding is custom
- **Fix:** Out of scope for fork — this is a fundamental pycardano design decision. We keep our custom block types.

### Issue #3: Address dual-interface (MEDIUM)
- Code must handle both pycardano `Address` objects and raw `bytes` for addresses
- Pervasive `hasattr(addr, 'payment_part')` checks
- **Fix:** Define a unified `AddressLike` Protocol type in our code (not a pycardano fix)

### Issue #4: TransactionId.payload wrapping (MEDIUM)
- pycardano wraps tx hash bytes in `TransactionId.payload`
- Raw dicts use plain bytes
- Code needs `getattr(tx_id, "payload", tx_id)` everywhere
- **Fix:** Normalize in our deserialization layer (not a pycardano fix)

### Issue #5: AuxiliaryData location mismatch (LOW)
- pycardano stores `auxiliary_data` on `Transaction`, not `TransactionWitnessSet`
- Our validation receives witness set separately
- **Fix:** Architectural difference — work around in our code

### Issue #6: Missing type stubs (LOW)
- Some type annotations incomplete or missing
- Affects IDE experience but not runtime
- **Fix:** Add type stubs in fork

## Fork Priority

Only Issue #1 (Conway fields) justifies a fork. Issues #2-5 are architectural mismatches best handled in our code. Issue #6 is nice-to-have.

## Fork Steps

1. Fork https://github.com/Python-Cardano/pycardano to SteelSwap/pycardano
2. Add Conway-era fields to `TransactionBody` (voting_procedures, proposal_procedures, treasury_value, donation)
3. Verify existing tests pass
4. Add Conway round-trip tests
5. Fix type stubs
6. Open upstream PR
7. Update vibe-node pyproject.toml to point to fork
8. Simplify our `try/except` fallback code where Conway fields now deserialize correctly
