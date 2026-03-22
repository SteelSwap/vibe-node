# Phase 6 — Hardening & Foundations

## Goal

Strengthen vibe-node's foundations: fix dependency issues, eliminate code duplication, establish performance baselines, achieve full Haskell test parity, harden the node for production, and validate with a 48-hour soak test on preview.

## Context

Phase 5 delivered a node that forges blocks accepted by Haskell. But the journey exposed fragility: dependency bugs (cbor2 C bindings), code duplication (parallel protocol implementations), missing test coverage, and optimistic self-assessment that required multiple correction rounds. Phase 6 fixes the foundations before we attempt the 10-day conformance window in Phase 7.

## Architecture: 10 Modules, 3 Tracks

### Track A — Code Quality (parallelizable)

#### M6.1 — Dependency Audit & Forking

**Goal:** Eliminate dependency-caused bugs by forking, fixing, and maintaining our critical dependencies.

**Dependencies to audit:**

| Dependency | Known Issues | Action |
|-----------|-------------|--------|
| **cbor2pure** | Pure Python CBOR library (NOT cbor2 which has broken C bindings). We use cbor2pure exclusively — `import cbor2pure as cbor2` across all 32+ files. Audit for edge cases, optimize hot paths. | Fork to SteelSwap, fix any issues found, open upstream PRs |
| **uplc** | string-04 conformance failure (escape sequences); CEK machine edge cases | Fork to SteelSwap, fix string parsing, run full conformance suite |
| **pycardano** | Uses cbor2pure by default (via `pycardano.cbor` shim that checks `CBOR_C_EXTENSION` env var). Deeply integrated — 13 files, 32 import sites for tx types, certs, addresses. Some type stubs missing. | Fork to SteelSwap, audit for correctness issues, fix type stubs, open upstream PRs |
| **cryptography** | No known issues, but audit KES/VRF usage for correctness | Audit: compare outputs against Haskell for known test vectors. No fork unless issues found |

**Process per dependency:**
1. Catalog every workaround/catch in our codebase that compensates for the dependency
2. Fork to SteelSwap GitHub org
3. Fix issues in the fork
4. Open PRs upstream
5. Update our pyproject.toml to point to the fork
6. Document the fork rationale in docs/reference/

**Fork maintenance strategy:**
- Pin our packages to the fork via pyproject.toml git references
- Track upstream releases — rebase our patches on each upstream release
- If upstream merges our PRs, switch back to upstream and drop the fork
- Acceptable divergence window: 6 months before we escalate (write our own minimal replacement)

**Deliverable:** All dependency workarounds removed, replaced by fixes in forked packages. Upstream PRs open for every fix.

---

#### M6.2 — Code Deduplication & Cleanup

**Goal:** One canonical implementation for every concept. No parallel files, no dead code, no scattered logic.

**Audit scope:**
- Protocol implementations: `handshake.py` vs `handshake_protocol.py`, `chainsync.py` vs `chainsync_protocol.py`, etc.
- Block decoding: scattered across `run.py`, `blockfetch.py`, `serialization/block.py`
- CBOR encoding/decoding: multiple patterns for the same operations
- Dead imports, unused functions, vestigial code from earlier phases
- Overly large files (especially `run.py` at 1700+ lines) — split by responsibility. Target structure determined during audit, but likely candidates: `startup.py`, `peer_manager.py`, `sync_loop.py`, `forge_loop.py`, `inbound_server.py`

**Reusability review:**

During deduplication, verify that the monorepo package boundaries are correct:

- **vibe-core** must remain protocol-agnostic with ZERO Cardano-specific code. It provides: multiplexer, typed protocol framework, pipelining, bearer abstraction, codec interfaces, storage interfaces. These are generic building blocks for any binary protocol node. Use Python `Protocol` types for interfaces, not base class inheritance.
- **vibe-cardano** contains all Cardano-specific logic. Code that's currently in vibe-cardano but is actually generic (e.g., binary codec patterns, append-only storage, snapshot/recovery patterns, connection management) should be extracted to vibe-core.
- **vibe-tools** is dev infrastructure only — no runtime code leaks.

Specific extraction candidates to evaluate:
- Codec framework (CBOR encode/decode patterns → generic codec interface in vibe-core)
- Storage abstractions (append-only + mutable + snapshot patterns → storage interface in vibe-core)
- Connection/peer management (reconnect logic, backoff, health tracking → vibe-core)
- Consensus interfaces (thin Protocol types for leader election, chain selection → vibe-core)

**Process:**
1. Generate a full duplication report (function-level similarity analysis)
2. For each duplicate pair: decide which is canonical, merge the best parts, delete the other
3. For scattered logic: consolidate into single-responsibility modules
4. For large files: split along natural boundaries
5. Review every module against vibe-core vs vibe-cardano boundary — extract generics
6. Run full test suite after each consolidation to catch regressions

**Deliverable:** Every file has one clear responsibility. No parallel implementations. `run.py` split into focused modules. vibe-core contains all protocol-agnostic abstractions with clean interfaces.

---

#### M6.3 — Data Structure Profiling & Optimization

**Goal:** Evidence-based decision on data structure libraries for hot paths.

**Candidates:**
- Current: `dataclasses` (zero overhead, no validation)
- `pydantic v2`: runtime validation, JSON serialization, good DX
- `msgspec`: fastest serialization, struct types, minimal overhead
- `attrs`: lightweight, validators, `__slots__` by default

**Benchmark methodology:**
1. Identify hot-path data structures (block headers, UTxO entries, tx bodies, protocol messages)
2. Benchmark instantiation, field access, serialization for each candidate
3. Measure memory footprint per instance at scale (1M UTxO entries)
4. Profile real workloads: full block decode → validate → store cycle
5. Recommend: which library for which layer (wire protocol vs internal vs storage)

**Deliverable:** Benchmark report with numbers and recommendation. Proof-of-concept on one hot path to validate the recommendation. Full migration deferred to Phase 7 — this module produces the evidence and plan, not the refactor.

---

### Track B — Robustness (parallelizable with Track A)

#### M6.4 — Haskell Test Parity

**Goal:** Systematic pass through Haskell test functions, prioritized by subsystem coverage gaps.

**Scoping:** The knowledge base indexes 11,611 Haskell test functions. Full 1:1 parity is a multi-phase effort. M6.4 focuses on: (1) all tests tagged critical/important in the gap analysis, (2) subsystems with the weakest existing coverage, (3) any test that exercises code paths affecting block production, validation, or chain selection. Tests for deprecated features, Byron-only edge cases, and Haskell-internal plumbing are out of scope.

**Scope:** All 10 subsystems (prioritized by gap severity):
1. Serialization (CBOR encode/decode, all eras)
2. Networking (mux, handshake, chain-sync, block-fetch, tx-submission, keep-alive)
3. Ledger (Byron through Conway, UTxO rules, delegation, rewards)
4. Storage (ImmutableDB, VolatileDB, LedgerDB, ChainDB)
5. Consensus (Praos VRF, KES, chain selection, epoch boundary)
6. Crypto (VRF, KES, Ed25519, hashing)
7. Mempool (validation, capacity, tx selection)
8. Forge (leader election, block construction, header format)
9. Plutus (CEK machine, cost models, script evaluation)
10. Node integration (startup, shutdown, peer management)

**Process per subsystem:**
1. Query knowledge base for all Haskell test functions in that subsystem
2. Map each to an existing Python test (or mark as missing)
3. Write missing tests
4. Run and verify all pass
5. Document the mapping in a test parity matrix

**Exit criteria:** Test parity matrix with coverage percentage per subsystem. All critical/important tests passing. Remaining gaps documented with Phase 7 plan.

---

#### M6.5 — Node Hardening

**Goal:** The node survives adversarial conditions without human intervention.

**Sub-modules:**

**Power-loss recovery:**
- kill -9 during active sync at random points
- Verify clean restart from latest snapshot + diff replay
- Measure recovery time (target: <5 seconds)
- Automated test harness (not manual)

**Connection resilience:**
- Reconnect on peer disconnect with exponential backoff
- Handle MuxClosedError in all miniprotocol handlers
- Survive peer churn (peers coming and going)
- No leaked tasks or sockets on disconnect

**Resource limits:**
- Memory cap with graceful degradation (not OOM kill)
- File descriptor tracking and limits
- Chain DB size limits with pruning

**Error handling audit:**
- Find and fix bare `except Exception` that swallows errors
- Ensure all errors are logged with context
- No silent failures in critical paths (forge, chain-sync, block-fetch)

**Security hardening:**
- CBOR bomb protection (max decode depth, max size)
- Malformed block handling (don't crash on garbage input)
- Wire protocol message validation (reject invalid state transitions)
- No command injection via config or environment variables

**Graceful shutdown:**
- SIGTERM completes in-flight operations before exit
- No corrupted state on shutdown
- All async tasks properly cancelled
- Socket cleanup verified

**Deliverable:** Automated test suite for each sub-module. Node survives kill -9, peer churn, malformed input, and resource pressure.

---

#### M6.6 — Observability

**Goal:** Real-time visibility into node health for soak tests and production.

**Components:**

- **Logging audit & overhaul:**
    - Full codebase review of every `logger.debug()`, `logger.info()`, `logger.warning()`, `logger.error()` call
    - Remove stale debug logs from Phase 5 development (hex dumps, "BLOCK-FETCH: received X bytes", temporary diagnostic output)
    - Ensure debug-level logs are guarded with `if logger.isEnabledFor(logging.DEBUG)` when they involve string formatting or object serialization — no performance penalty when debug is off
    - INFO messages should mirror Haskell node log events but be human-readable: `Forged block #42 at slot 1000 (0 txs, 848 bytes)` not `[2026-03-22 01:07:00][Node.Forge](Info) {"kind":"TraceForgedBlock","slot":1000,"blockNo":42}`
    - Target log events to match (at INFO level): forge stats, chain-sync progress, block validation results, peer connect/disconnect, tip changes, epoch transitions, KES evolution, mempool activity
    - Structured fields via Python's `extra` dict for machine parsing, but keep the format string human-readable for terminal output
    - JSON format option via env var (`VIBE_LOG_FORMAT=json`) for log aggregation pipelines
- **Prometheus metrics:** Expose `/metrics` endpoint with:
  - `vibe_node_tip_slot` (gauge)
  - `vibe_node_blocks_synced_total` (counter)
  - `vibe_node_blocks_forged_total` (counter)
  - `vibe_node_peers_connected` (gauge)
  - `vibe_node_memory_rss_bytes` (gauge)
  - `vibe_node_forge_duration_seconds` (histogram)
  - `vibe_node_block_validation_duration_seconds` (histogram)
- **Health endpoint:** HTTP `/health` returning `{"status": "ok", "tip_slot": N, "peers": N, "syncing": bool}`
- **Memory tracking:** Periodic RSS sampling, object count by type (for leak detection)

**Deliverable:** Prometheus-scrapeable metrics, health endpoint, structured logs. Dashboard-ready for soak test monitoring.

---

### Track C — Validation (depends on A + B)

#### M6.7 — Benchmarking Suite

**Goal:** Baseline numbers for all critical paths. Identify bottlenecks. Regression-testable.

**Critical paths to benchmark:**
- CBOR block decode (all eras)
- Block validation (ledger rules)
- VRF evaluation
- KES sign/verify
- Chain selection
- Mempool tx validation
- Arrow IPC read/write
- UTxO lookup
- Forge loop end-to-end (slot → block ready)

**Approach:**
- `pytest-benchmark` fixtures for each critical path
- Run on standardized hardware (document specs)
- Store baseline numbers in `benchmarks/` as JSON
- CI job that flags >10% regression

**Deliverable:** Benchmark suite with baselines. Bottleneck report with optimization recommendations.

---

#### M6.8 — 48-Hour Soak Test on Preview

**Goal:** Prove the hardened node runs for 48 continuous hours on preview without intervention.

**Setup:**
- vibe-node connects to preview network via public relays
- Sync from genesis (or Mithril snapshot for speed)
- Passive sync mode (no forging) — forging soak test deferred to Phase 7 devnet with controlled stake
- Monitor: tip agreement, memory, restarts, errors

**Fallback:** If preview is unstable during the test window, run against a local 3-node devnet with extended epoch parameters instead. Document which environment was used.

**Success criteria:**
- Tip within 120 seconds of Haskell relay tip for 48 continuous hours
- No OOM kills
- No unhandled exceptions
- Memory growth < 10% over 48 hours (no leaks)
- Zero manual interventions

**Infrastructure:**
- Docker Compose with vibe-node + monitoring stack
- Prometheus + Grafana for metrics visualization
- Alerting on tip drift > 120s or memory spike
- Automated log collection

**Deliverable:** 48-hour run report with metrics graphs, memory profile, and pass/fail on each criterion.

---

#### M6.9 — Preview Sync Benchmark

**Goal:** Concrete numbers for syncing the full preview chain.

**Measurements:**
- Wall-clock time: genesis → tip
- Peak memory (RSS) during sync
- Final chain size in Arrow IPC format
- Final UTxO count
- Blocks/second throughput (average and P50/P95/P99)
- Comparison against Haskell node syncing the same chain on same hardware

**Process:**
1. Clean slate — fresh data directory
2. Sync from genesis with timing instrumentation
3. Record metrics at regular intervals (every 10,000 blocks)
4. After reaching tip, measure final state sizes
5. Repeat with Haskell cardano-node on same machine
6. Compare and document

**Deliverable:** Sync benchmark report with comparison table. Numbers for README.

---

#### M6.10 — Haskell Conformance Gap Analysis

**Goal:** Systematic behavioral comparison between vibe-node and Haskell cardano-node. Catch everything tests miss.

**Comparison layers:**

1. **Wire protocol** — Capture CBOR bytes for every miniprotocol message type from both nodes. Diff field by field. Document any encoding differences.

2. **Block production** — In a shared devnet, have both nodes forge blocks. Compare header fields byte-by-byte: VRF output, KES signature structure, opcert encoding, body hash computation.

3. **Ledger state** — At epoch boundaries in the devnet, dump UTxO sets from both nodes. Diff. Any disagreement is a bug.

4. **Chain selection** — Log tip slot from all nodes every slot. Verify they converge within k slots. Any sustained divergence is a bug.

5. **Transaction validation** — Submit identical transactions to both nodes. Compare acceptance/rejection. Any disagreement on validity is a bug.

**Process:**
1. Build comparison tooling (CBOR diff, UTxO diff, tip logger)
2. Run shared devnet for extended period (devnet uses 100-slot epochs at 0.2s slots, so 1000 epochs = ~5.5 hours)
3. Analyze results
4. File bugs for every divergence
5. Fix critical/high divergences in Phase 6
6. Document remaining low-severity divergences with Phase 7 fix plan

**Exit criteria:** Zero critical/high behavioral divergences. All remaining divergences documented with severity rating. Comparison tooling committed for continuous regression testing.

---

## Module Dependencies

```
Wave 1 (parallel — no dependencies)
┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
│  M6.1   │   │  M6.4   │   │  M6.5   │   │  M6.6   │
│  Deps   │   │  Tests  │   │ Harden  │   │  Obsrv  │
└────┬────┘   └─────────┘   └────┬────┘   └────┬────┘
     │                            │              │
     ▼                            │              │
Wave 2 (depends on M6.1)         │              │
┌─────────┐   ┌─────────┐        │              │
│  M6.2   │   │  M6.3   │        │              │
│  Dedup  │   │  Data   │        │              │
└────┬────┘   └─────────┘        │              │
     │                            │              │
     └──────────┬─────────────────┘              │
                ▼                                │
Wave 3 (depends on M6.1 + M6.2 + M6.5 + M6.6)  │
┌─────────┐   ┌─────────┐                       │
│  M6.7   │   │  M6.9   │◄──────────────────────┘
│  Bench  │   │  Sync   │
└────┬────┘   └─────────┘
     │
     ▼
Wave 4 (depends on all above)
┌─────────┐   ┌─────────┐
│  M6.8   │   │  M6.10  │
│  48h    │   │  Conform│
└─────────┘   └─────────┘
```

**Ordering rationale:**
- M6.1 (deps) must complete before M6.2 (dedup) — forking pycardano changes imports that dedup will touch
- M6.5 (hardening) and M6.6 (observability) must complete before M6.8 (48h soak) — can't soak-test without crash resilience and metrics
- M6.1 (deps) must complete before M6.9 (sync benchmark) — cbor2pure bugs would crash sync
- M6.8 and M6.10 run last — they validate everything else

**Interaction risk:** M6.1 (forking pycardano) and M6.2 (dedup) will touch overlapping files. M6.1 completes first to avoid merge conflicts.

## Branch Strategy

Each module gets its own branch and PR:
- `m6.1-dependency-audit`
- `m6.2-code-dedup`
- `m6.3-data-structure-profiling`
- `m6.4-haskell-test-parity`
- `m6.5-node-hardening`
- `m6.6-observability`
- `m6.7-benchmarking-suite`
- `m6.8-48h-soak-preview`
- `m6.9-preview-sync-benchmark`
- `m6.10-conformance-gap-analysis`

**No worktrees with manual file copying. Ever.**

## Success Criteria

Phase 6 is complete when:
- [ ] All dependency workarounds replaced by fixes in forked packages (upstream PRs open)
- [ ] Zero code duplication — one canonical implementation per concept
- [ ] Data structure benchmark report with recommendation (migration deferred to Phase 7)
- [ ] Haskell test parity matrix with coverage % per subsystem; all critical/important tests passing
- [ ] Node survives kill -9, peer churn, malformed input, resource pressure
- [ ] Prometheus metrics, health endpoint, structured logging operational
- [ ] Benchmark baselines established for all critical paths
- [ ] 48-hour soak test on preview passed (tip agreement, no leaks, no crashes)
- [ ] Preview full sync completed with published numbers
- [ ] Zero critical/high behavioral divergences from Haskell node (low-severity documented for Phase 7)

## What Phase 6 Does NOT Include

- 10-day conformance window (Phase 7)
- Preprod block production (Phase 7)
- Mainnet readiness (Phase 7)
- Memory optimization to beat Haskell (informed by M6.7/M6.9, executed in Phase 7)
