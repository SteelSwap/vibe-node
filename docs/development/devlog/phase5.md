# Phase 5 — Block Production & Haskell Acceptance

**Status: COMPLETE** — vibe-node forges blocks accepted by Haskell cardano-nodes. v0.6.0.

Phase 5 transformed vibe-node from a passive chain follower into an active block producer. The milestone was achieved when Haskell nodes in a 3-node private devnet validated and adopted blocks forged by vibe-node — passing VRF proof verification, KES signature checks, header envelope validation, and chain selection.

---

## Key Achievement: Haskell Block Acceptance

The definitive test: Haskell cardano-node 10.4.1 chain-syncs from vibe-node, downloads headers, validates VRF proofs, verifies KES signatures, checks block numbers and prev-hashes, and extends its chain with our blocks.

```
ChainDB.AddBlockEvent.AddBlockValidation.ValidCandidate at slot 427
ChainDB.AddBlockEvent.AddedToCurrentChain: new tip at slot 427
```

This required fixing 9 bugs found through systematic comparison of our forge loop against the Haskell implementation (see [Forge Loop Comparison](../../reference/pipelines/forge-loop-comparison.md)).

---

## Bugs Found & Fixed

| # | Bug | Root Cause | Fix |
|---|-----|-----------|-----|
| 1 | Wrong block number | Used slot as block number | ChainDB returns real block_number from header |
| 2 | Stale epoch nonce | Read once at startup | Re-read from node_kernel per slot |
| 3 | Stale relative stake | Read once at startup | Re-read from node_kernel per slot |
| 4 | Wrong VRF seed algorithm | Used TPraos `mkSeed` (with XOR) | Conway uses Praos `mkInputVRF` (no XOR) |
| 5 | Wrong header format | 14-field Shelley format | 10-field Babbage/Conway with nested sub-arrays |
| 6 | Wrong genesis hash | Re-encoded JSON bytes | Raw file bytes: `genesis_path.read_bytes()` |
| 7 | Chain-sync era index | CBOR tag 7 (Conway) | HFC index 6 (CBOR tags offset by 1 for Byron EBB) |
| 8 | Non-linear chain in NodeKernel | Appended all blocks without chain selection | Chain selection with fork switching and `is_forged` flag |
| 9 | cbor2 C binding bug | `CBORDecoder.fp.tell()` returns full buffer length | Switched to cbor2pure (pure Python) across 32 files |

### The Critical Era Insight

The single most important discovery: **Conway (Praos) uses a different VRF input than Shelley-Mary (TPraos).**

- **TPraos** (Shelley-Mary): `mkSeed seedL slot epochNonce` = `blake2b(slot_be64 || epochNonce) XOR seedL`
- **Praos** (Babbage+): `mkInputVRF slot epochNonce` = `blake2b(slot_be64 || epochNonce)` — **no XOR**

This is because Praos uses a single unified VRF evaluation per slot (with the output split for leader/nonce), while TPraos used two separate VRF evaluations with different universal constants.

Found via the vendor submodule: `ouroboros-consensus-protocol/src/.../Praos/VRF.hs` vs `cardano-protocol-tpraos/src/.../BHeader.hs`.

---

## Modules Delivered

### Block Production
- VRF leader election with Praos `mkInputVRF`
- KES-signed headers (sum-composition MMM tree, depth 6)
- Operational certificate validation
- Block body construction with mempool tx selection
- Babbage/Conway 10-field header format

### N2N Server Protocols
- Chain-sync server (header streaming with tip tracking)
- Block-fetch server (block delivery)
- Tx-submission server
- Keep-alive server

### N2C Local Protocols
- Local chain-sync
- Local tx-submission
- Local state-query
- Local tx-monitor

### Integration
- NodeKernel with chain selection (fork switching, forged vs received blocks)
- Full-duplex mux with concurrent miniprotocols
- Continuous block-fetch with range queue
- Forge sync gate (within 10 slots of tip)
- KES key evolution per period

---

## Test Results

| Metric | Value |
|--------|-------|
| Total tests | 4,290+ |
| VRF/KES crypto tests | 64 |
| Forge/leader tests | 15 |
| Haskell acceptance | ValidCandidate + AddedToCurrentChain (zero errors) |

---

## Remaining Work (Phase 6)

- Fix `UnexpectedPrevHash` during fork switches (chain ordering edge case)
- Ledger state ticking for transaction-bearing blocks
- 48-hour devnet soak test
- Preprod block production
- Power-loss recovery validation
- Memory optimization for 10-day conformance window
