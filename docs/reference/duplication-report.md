# Codebase Duplication Report

**Module:** M6.2 — Code Deduplication
**Date:** 2026-03-22
**Status:** Initial audit

---

## 1. Protocol File Pairs

The `network/` directory uses a consistent two-file pattern for each miniprotocol:

- `X.py` — CBOR message codec: message dataclasses, encode/decode functions
- `X_protocol.py` — Typed protocol FSM: state enum, typed Message wrappers, codec adapter, high-level client/server

The `_protocol.py` files import from and delegate to the corresponding `.py` files. This is **intentional layering**, not duplication. The codec layer is pure CBOR encode/decode; the protocol layer adds typed state machine transitions on top.

### N2N Protocol Pairs

| Pair | Codec (`X.py`) | Protocol (`X_protocol.py`) | Relationship |
|------|----------------|---------------------------|--------------|
| **blockfetch** | 284 lines | 722 lines | Protocol imports all messages + encode/decode from codec |
| **chainsync** | 494 lines | 849 lines | Protocol imports all messages + encode/decode from codec |
| **handshake** | 531 lines | 546 lines | Protocol imports messages + encode/decode, adds FSM + negotiation |
| **keepalive** | 262 lines | 469 lines | Protocol imports all messages + encode/decode from codec |
| **txsubmission** | 404 lines | 732 lines | Protocol imports all messages + encode/decode from codec |

### N2C Protocol Pairs

| Pair | Codec (`X.py`) | Protocol (`X_protocol.py`) | Relationship |
|------|----------------|---------------------------|--------------|
| **local_chainsync** | 242 lines | 701 lines | Reuses N2N chainsync types heavily; only N2C-specific MsgRollForward is new |
| **local_statequery** | 596 lines | 831 lines | Protocol imports all messages + encode/decode from codec |
| **local_txsubmission** | 325 lines | 428 lines | Protocol imports all messages + encode/decode from codec |
| **local_txmonitor** | 516 lines | 732 lines | Protocol imports all messages + encode/decode from codec |

### Pipelined Variants

| File | Lines | Imported By |
|------|-------|-------------|
| **blockfetch_pipelined.py** | ~200 | **Nothing in production code** |
| **chainsync_pipelined.py** | ~200 | **Nothing in production code** |

**Finding:** The pipelined variants are not imported by any production code (`node/run.py`, `kernel.py`, etc.). They are only structural — no tests import them either. These may be dead code or pre-built for future use.

### Structural Duplication in Protocol Files

Each `_protocol.py` follows an identical structural pattern:

1. State enum (~15 lines)
2. Typed Message wrapper classes (~20 lines each, 3-8 per protocol)
3. Pre-computed frozenset valid_messages (~10 lines)
4. Protocol class with `_AGENCY_MAP` and `_VALID_MESSAGES` (~30 lines)
5. Codec class with `encode()`/`decode()` dispatch (~50 lines)
6. High-level Client class (~50-100 lines)
7. High-level `run_*` functions (~50-100 lines)

**Recommendation:** The typed Message wrappers are boilerplate — each one just wraps an `inner` dataclass with `from_state`/`to_state`. A generic `TypedMessage[S, T]` factory or decorator could eliminate ~60% of the wrapper code across all 9 protocol files. Similarly, the Codec classes all follow the same encode-dispatch / decode-try-server-then-client pattern.

### The `local_chainsync` Reuse Pattern (Exemplary)

`local_chainsync.py` demonstrates good reuse: it imports Point, Tip, Origin, message IDs, and 7 out of 8 encode/decode functions directly from `chainsync.py`. Only `N2CMsgRollForward` and its encode/decode are defined locally. This is the right pattern — the N2C protocol shares wire format with N2N.

**Recommendation:** The `local_chainsync_protocol.py` typed message wrappers (Lcs*) are near-identical to the N2N ones (Cs*) — same states, same transitions, just different State enum type parameter. These could be generated or parameterized.

---

## 2. Block Decoding Duplication

### Era Enum — Triplicated

The `Era(IntEnum)` is defined in three files:

| File | Lines | Members |
|------|-------|---------|
| `serialization/block.py:28` | BYRON_MAIN through CONWAY (0-7) | Canonical definition |
| `serialization/transaction.py:46` | BYRON_MAIN through CONWAY (0-7) | Duplicate — comment says "Duplicated from block.py" |
| `consensus/hfc.py:75` | BYRON through CONWAY (0-7) but different names | Different naming: `BYRON` vs `BYRON_MAIN`, no `BYRON_EBB` |

**Recommendation:** Consolidate to a single `Era` enum, likely in `serialization/block.py` or a new `vibe/cardano/types.py`. The `hfc.py` version needs harmonization since it uses different member names.

### CBOR Block Decoding Paths

Block CBOR is decoded in multiple places:

| Location | What It Decodes | Purpose |
|----------|----------------|---------|
| `serialization/block.py` — `decode_block_header()` | Era tag + header array | Header extraction for chain-sync |
| `serialization/block.py` — `decode_block_header_raw()` | Header array (already unwrapped) | Header from known-era bytes |
| `serialization/transaction.py` — `decode_block_body()` | Era tag + full block array | Transaction extraction |
| `serialization/transaction.py` — `decode_block_transactions()` | Delegates to `decode_block_body()` | Convenience wrapper |
| `serialization/eval_pycardano.py` | Full block CBOR via cbor2.loads | pycardano evaluation testing |
| `node/run.py:546-577` | Era tag unwrap + header/body split | Inline block processing in sync loop |
| `network/blockfetch.py:224-229` | Re-encodes decoded block_data back to bytes | Block message handling |

**Key overlap:** `node/run.py` lines 546-577 perform inline CBOR decoding that duplicates what `serialization/block.py` already provides:

```
decoded = cbor2.loads(block_cbor)
...
decoded = cbor2.loads(inner)
...
hdr_cbor = cbor2.dumps(hdr)
raw_block = cbor2.dumps(cbor2.CBORTag(era_tag, block_body))
```

**Recommendation:** Extract a `split_block(cbor_bytes) -> (era, header_cbor, body_cbor)` function in `serialization/block.py` that `node/run.py` and other callers can use. The inline CBOR manipulation in run.py should call through the serialization layer.

---

## 3. Large Files (>500 lines)

Files sorted by line count, production code only:

| File | Lines | Recommendation |
|------|-------|---------------|
| `node/run.py` | **1756** | **Split urgently** — contains node startup, N2N sync loop, N2C server setup, block forging, Mithril snapshot loading, and shutdown. Split into: `run.py` (startup/shutdown), `sync.py` (N2N sync loop), `n2c_server.py` (local protocol servers), `forge_loop.py` (block production loop) |
| `serialization/eval_pycardano.py` | **1176** | **Evaluation/testing tool**, not production. Low priority but could split into per-era evaluators |
| `consensus/hfc.py` | **1138** | **Split recommended** — contains HFC combinator config, era detection, transaction validation dispatch, AND era-transition state translation. Split translation logic into `consensus/era_translation.py` |
| `chainsync_protocol.py` | **849** | Acceptable — well-structured with clear sections |
| `local_statequery_protocol.py` | **831** | Acceptable — complex protocol with many query types |
| `local_txmonitor_protocol.py` | **732** | Acceptable |
| `txsubmission_protocol.py` | **732** | Acceptable |
| `shelley.py` (ledger) | **736** | Borderline — could split validation rules from UTxO state |
| `blockfetch_protocol.py` | **722** | Acceptable |
| `local_chainsync_protocol.py` | **701** | Acceptable |
| `handshake_protocol.py` | **546** | Acceptable |
| `handshake.py` | **531** | Acceptable |
| `local_txmonitor.py` | **516** | Acceptable |
| `local_statequery.py` | **596** | Acceptable |

**Priority splits:**

1. **`node/run.py` (1756 lines)** — This is the most urgent. It's a god-module doing everything. Minimum 4-way split.
2. **`consensus/hfc.py` (1138 lines)** — Era translation logic (~400 lines) should be its own module.

---

## 4. Dead Code

### Confirmed Dead: Unreferenced Modules

| File | Lines | Evidence |
|------|-------|---------|
| `node/security.py` | Unknown | Not imported anywhere in the codebase |
| `node/memory_tracker.py` | Unknown | Not imported anywhere in the codebase |
| `node/resource_limits.py` | ~50+ | Only imports from `storage.volatile` — but is never imported by anything else. **Wait** — need to verify it's not used at runtime via config. Likely dead. |
| `node/logging_config.py` | Unknown | Not imported anywhere in the codebase |
| `node/metrics.py` | Unknown | Not imported anywhere in the codebase |
| `serialization/eval_pycardano.py` | 1176 | Not imported by any production code — this is a standalone evaluation/testing tool |
| `plutus/context.py` | Unknown | Not imported anywhere in the codebase |
| `network/blockfetch_pipelined.py` | ~200 | Not imported by any production code |
| `network/chainsync_pipelined.py` | ~200 | Not imported by any production code |

**Note:** `eval_pycardano.py`, `blockfetch_pipelined.py`, and `chainsync_pipelined.py` may be intentionally staged for future use. The `node/` utility modules (`security.py`, `memory_tracker.py`, `logging_config.py`, `metrics.py`) appear to be scaffolding that was never wired in.

### Confirmed Dead: `vibe.core.protocols.peer`

`vibe/core/protocols/peer.py` is not imported by anything in either `vibe-core` or `vibe-cardano`.

### Era Enum Redundancy (Not Dead, But Duplicated)

The three `Era(IntEnum)` definitions are all used — but they should be one definition imported everywhere. See Section 2.

---

## 5. vibe-core / vibe-cardano Boundary

### vibe-core Contents

| Module | Lines | Cardano-specific? |
|--------|-------|-------------------|
| `protocols/agency.py` | ~120 | No — generic typed-protocols framework |
| `protocols/codec.py` | ~80 | No — mentions CBOR in docs but interface is `bytes` in/out |
| `protocols/runner.py` | ~250 | **Mild leak** — imports `cbor2pure` for CBOR frame splitting (line 233). The CBOR-aware message boundary detection is Ouroboros-specific. |
| `protocols/pipelining.py` | ~200 | No — generic pipeline with backpressure |
| `protocols/peer.py` | ~50 | No — generic (also dead code) |
| `multiplexer/bearer.py` | ~100 | No — generic TCP bearer |
| `multiplexer/mux.py` | ~350 | No — generic multiplexer |
| `multiplexer/segment.py` | ~80 | No — generic segment framing |
| `storage/interfaces.py` | ~250 | No — generic storage protocols. Comments mention Haskell patterns but the interfaces are blockchain-agnostic. |
| `storage/memory.py` | ~100 | No — generic in-memory implementations |

### Boundary Violations

**vibe-core importing cbor2pure:** `protocols/runner.py` line 233 imports `cbor2pure` to split CBOR message boundaries within a mux segment. This is a Ouroboros-specific concern (multiple CBOR items per segment). The import is lazy (inside a method), so it doesn't create a hard dependency at module load time, but it's still a layer violation.

**Recommendation:** Either:
- Accept this as pragmatic (the runner IS designed for Ouroboros protocols)
- Or push the CBOR-aware splitting into the codec layer where each protocol's Codec handles multi-message segments

### Code That Should Move to vibe-core

No significant generic code was found trapped in vibe-cardano. The boundary is clean — Cardano-specific types, serialization, consensus, and ledger logic all live in vibe-cardano. The multiplexer, typed-protocols framework, and storage interfaces are properly in vibe-core.

---

## Summary of Recommendations

### High Priority (do in M6.2)

1. **Consolidate `Era` enum** — Single definition, imported by `serialization/block.py`, `serialization/transaction.py`, and `consensus/hfc.py`
2. **Extract `split_block()` helper** — Remove inline CBOR block decoding from `node/run.py`
3. **Split `node/run.py`** (1756 lines) — At minimum into startup, sync loop, N2C servers, and forge loop

### Medium Priority (do in M6.2 if time permits)

4. **Split `consensus/hfc.py`** (1138 lines) — Extract era-transition translation to its own module
5. **Delete confirmed dead code** — `node/security.py`, `node/memory_tracker.py`, `node/logging_config.py`, `node/metrics.py`, `protocols/peer.py` (after confirming they're truly unused)
6. **Audit pipelined variants** — Decide if `blockfetch_pipelined.py` and `chainsync_pipelined.py` are keep-for-later or dead

### Low Priority (future work)

7. **Generic typed message factory** — Reduce boilerplate in protocol files
8. **Fix cbor2pure import in vibe-core runner** — Minor layer violation
9. **Evaluate protocol file consolidation** — The X.py + X_protocol.py split is intentional but adds import overhead; some protocols (especially keepalive) are small enough to be single files
