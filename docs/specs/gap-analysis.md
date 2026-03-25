# Gap Analysis

## The Spec Is the Ideal. The Code Is the Reality. The Gap Is the Delta.

Cardano has formal specifications — mathematical descriptions of how the system should work. The Haskell node is the implementation — how it actually works. These don't always agree.

This section documents every divergence we discover, published like errata in a scientific publication. Where the spec says one thing and the Haskell node does another, we record it: what, where, why it matters, and how it affects our implementation.

## Why This Matters

1. **Correctness** — If we implement the spec but the Haskell node deviates, our node will disagree with the network. We need to follow the Haskell node (it's the oracle), but we need to know where we're deviating from the spec to do it.
2. **Community value** — The Cardano community benefits from a clear catalog of where reality diverges from the published specifications.
3. **Spec improvement** — Documented gaps can feed back into the formal specification process, making the specs more accurate over time.

## This Is Not a Phase

Gap analysis is **not** a discrete phase of development. It is a discipline woven into every implementation step. Every time we implement a protocol rule, a ledger validation, or a consensus mechanism, we:

1. Read the spec (via the Search MCP)
2. Implement against the spec
3. Test against the Haskell node
4. Document any divergence we observe

## Data Sources

- **Knowledge base**: 1,493 spec-vs-Haskell gaps in the `gap_analysis` PostgreSQL table (376 critical, 479 important, 608 informational)
- **Code audit**: M6.10 subsystem audits comparing our Python code against Haskell vendor code and upstream GitHub issues/PRs/tags
- **Devnet testing**: Block acceptance verification at 0.1s–1.0s slot times

## Summary by Subsystem

| Subsystem | KB Gaps | Critical | Important | Code Audit Findings |
|-----------|---------|----------|-----------|---------------------|
| Ledger | 384 | 104 | 121 | 18 |
| Consensus | 230 | 73 | 73 | 12 |
| Networking | 249 | 67 | 97 | 14 |
| Storage | 147 | 28 | 54 | 18 |
| Plutus | 145 | 34 | 31 | 16 |
| Block Production | 141 | 28 | 42 | — |
| Serialization | 103 | 26 | 28 | 16 |
| Mempool | 46 | 10 | 17 | — |
| Miniprotocols N2N | 44 | 4 | 16 | — |
| Miniprotocols N2C | 4 | 2 | 0 | — |
| **Total** | **1,493** | **376** | **479** | **94** |

---

## Consensus — Critical Gaps

### Chain selection doesn't construct candidate chains from successor map

**Severity:** critical
**Our code:** `storage/chaindb.py` `add_block` — compares new block's block_number against tip
**Haskell code:** `ChainDB.Impl.ChainSel.chainSelectionForBlock` + `Paths.maximalCandidates`
**Delta:** Haskell constructs ALL maximal candidate chains from VolatileDB's successor map, then compares each against the current chain. We only extend by one block at a time. Multi-block forks arriving out of order are never re-evaluated.
**Implications:** We miss valid fork switches where multiple blocks arrive out of order or where a fork becomes preferable only when extended by successors.

### Missing OCert issue number tiebreaker

**Severity:** high
**Our code:** `consensus/chain_selection.py` `compare_chains`
**Haskell code:** `Ouroboros.Consensus.Protocol.Praos.Common.comparePraos`
**Delta:** Haskell uses three-tier tiebreaker: (1) OCert issue number for same issuer + same slot, (2) VRF tiebreaker with optional `VRFTiebreakerFlavor` restricting comparison distance, (3) no further tiebreaker. We have: (1) block number, (2) VRF output, (3) block hash fallback (non-standard).
**Implications:** Could select wrong chain in compromised hot key scenarios. Block hash fallback is non-standard.

### checkLeaderVal must match Haskell's Taylor expansion exactly

**Severity:** critical (KB)
**Delta:** Haskell uses exactly 3-iteration Taylor expansion with conservative tie-breaking (MaxReached→False, ABOVE→False, BELOW→True) and fixed-point arithmetic with 34 decimal bits precision. Any deviation produces different results on boundary cases.

### Stake distribution must include reward balances

**Severity:** critical (KB)
**Delta:** Stake distribution must filter active delegations to credentials in rewards map delegating to registered pools, AND include reward account balances alongside UTxO-derived stake, AND resolve pointer addresses.

---

## Networking — Critical Gaps

### No SDU segmentation for large payloads

**Severity:** critical
**Our code:** `vibe-core/multiplexer/mux.py` `_sender_loop`
**Haskell code:** `Network.Mux.Egress.processSingleWanton` — splits at 12,288 bytes
**Delta:** Haskell splits payloads > `sduSize` (12,288 bytes) into multiple segments. We send full payloads as single segments. Block-fetch MsgBlock messages (hundreds of KB) violate the SDU size constraint.
**Implications:** Haskell peers may reject or fail to parse oversized segments.

### No direction-aware mux demuxing

**Severity:** critical
**Our code:** `vibe-core/multiplexer/mux.py` — channels keyed by `protocol_id` only
**Haskell code:** `Network.Mux.Ingress` — channels keyed by `(MiniProtocolNum, MiniProtocolDir)`, direction flipped on receive
**Delta:** Haskell demuxer flips initiator/responder direction when routing segments to channels. Our channels are keyed by protocol_id only.
**Implications:** Could deliver segments to wrong protocol handler in bidirectional connections.

---

## Ledger — Critical Gaps

### Value preservation missing certificate deposits/refunds

**Severity:** critical
**Our code:** `ledger/shelley.py` `validate_shelley_utxo`
**Delta:** UTxO value preservation check must account for certificate deposits (key registration, pool registration) and refunds (key deregistration, pool retirement). We check consumed vs produced without these terms.
**Implications:** Transactions with deposit/refund operations would fail our validation but pass the Haskell node, or vice versa.

### Conway governance not implemented at epoch boundaries

**Severity:** critical (KB)
**Delta:** Conway epoch boundary requires DRep pulsing, proposal enactment/expiration, committee/constitution updates, PParams rotation, proposal deposit returns. None implemented.

---

## Storage — Critical Gaps

### No ledger validation during chain selection

**Severity:** critical
**Our code:** `storage/chaindb.py` `add_block` — purely compares block numbers and VRF
**Haskell code:** `ChainDB.Impl.ChainSel.chainSelection` calls `validateCandidate`
**Delta:** Haskell validates candidate chains against the ledger (ExtLedgerState) before adoption. We perform no ledger validation in chain selection.
**Implications:** We can adopt chains containing invalid blocks.

### ImmutableDB promotion copies fork blocks

**Severity:** high
**Our code:** `chaindb.py` `advance_immutable` — promotes ALL blocks at target slot
**Haskell code:** `ChainDB.Impl.Background.copyToImmutableDB` — walks current chain fragment only
**Delta:** Haskell copies only blocks on the selected chain. We promote all blocks at or below the target slot, including fork blocks.
**Implications:** Fork blocks in ImmutableDB violate its invariant (only selected chain).

---

## Serialization — Critical Gaps

### Body hash uses wrong algorithm

**Severity:** critical
**Our code:** `forge/block.py` `forge_block` — `blake2b(body_cbor)`
**Haskell code:** `hashShelleySegWits` / `hashAlonzoSegWits` — merkle bonsai (hash of individually-hashed segments)
**Delta:** Haskell computes body hash as `hash(hash(tx_bodies) || hash(witnesses) || hash(aux_data))` (3 parts for Shelley-Mary) or 4 parts for Alonzo+. We hash the entire body blob.
**Implications:** Forged blocks have incorrect body_hash in header. Other nodes reject them.

### Re-serialized CBOR for hash computation

**Severity:** critical
**Our code:** `serialization/block.py` `decode_block_header` — re-encodes via `cbor2.dumps`
**Haskell code:** Uses `MemoBytes`/`Annotator` to preserve original CBOR bytes
**Delta:** CBOR has multiple valid encodings. Re-serialization changes bytes, changing hashes.
**Implications:** Block hashes and tx hashes may not match Haskell's computation.

---

## Plutus — Critical Gaps

### V3 ScriptContext uses ScriptPurpose instead of ScriptInfo

**Severity:** critical
**Our code:** `plutus/context.py` `build_script_context_v3`
**Haskell code:** `PlutusLedgerApi/V3/Contexts.hs:ScriptContext`
**Delta:** V3 uses `ScriptInfo` (6 constructors including `SpendingScript` with TxOutRef AND Maybe Datum), not `ScriptPurpose`. Our code uses V1/V2 ScriptPurpose for all versions.
**Implications:** Every PlutusV3 script evaluation receives incorrect context.

### Missing BuiltinSemanticsVariant support

**Severity:** critical
**Our code:** `vendor/uplc/uplc/ast.py` — single static implementation per builtin
**Haskell code:** `PlutusCore/Default/Builtins.hs:BuiltinSemanticsVariant` (variants A-E)
**Delta:** Haskell selects semantics variant based on (PlutusLedgerLanguage, MajorProtocolVersion). ConsByteString behavior differs between variants.
**Implications:** Consensus-critical divergence for scripts using ConsByteString with out-of-range values.

---

## Gaps Already Fixed (M6.13)

- VRF leader value: `blake2b_256("L" || vrf_output) / 2^256` (was raw output / 2^512)
- VRF nonce value: `blake2b_256(blake2b_256("N" || vrf_output))` (was blake2b of raw output)
- 5-nonce model: evolving, candidate, lab, lastEpochBlock, epoch nonces
- Chain fragment: last k blocks of selected chain in memory
- Follower state machine: per-client chain-sync with fork switch rollback
- Nonce checkpoints: per-block snapshots for fork switch re-accumulation
- STM consistency: atomic reads of tip + nonce + stake in forge loop

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
