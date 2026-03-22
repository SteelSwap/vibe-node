# Phase 6 — Hardening & Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen vibe-node's foundations — fix dependencies, eliminate duplication, benchmark, achieve Haskell test parity, harden for production, and validate with a 48-hour preview soak test.

**Architecture:** 10 modules across 4 waves. Wave 1 (M6.1, M6.4, M6.5, M6.6) runs in parallel with no dependencies. Wave 2 (M6.2, M6.3) depends on M6.1. Wave 3 (M6.7, M6.9) depends on Waves 1+2. Wave 4 (M6.8, M6.10) validates everything. Each module gets its own branch and PR — no worktrees with manual file copying.

**Tech Stack:** Python 3.14, cbor2pure, pycardano, uplc, pytest-benchmark, prometheus_client, aiohttp (health/metrics server)

**Spec:** `docs/superpowers/specs/2026-03-22-phase6-hardening-design.md`

---

## Wave 1 — No Dependencies (Parallel)

### Task 1: M6.1 — Dependency Audit & Forking

**Branch:** `m6.1-dependency-audit`

**Files:**
- Modify: `pyproject.toml` (root + packages/vibe-cardano/pyproject.toml)
- Create: `docs/reference/dependency-audit.md`
- Modify: various source files where workarounds exist

**Work Items:**

- [ ] **1.1: Catalog all dependency workarounds in the codebase**
    - Search for `try/except` blocks around cbor2pure, pycardano, uplc calls
    - Search for `# workaround`, `# hack`, `# TODO`, `# FIXME` related to dependencies
    - Search for re-encoding patterns (e.g., `cbor2.dumps(cbor2.loads(...))` roundtrips)
    - Document each workaround with file path, line number, and root cause
    - Commit: `docs(m6.1): catalog dependency workarounds`

- [ ] **1.2: Fork cbor2pure to SteelSwap**
    - Fork https://github.com/agronholm/cbor2 (cbor2pure is the pure-Python path)
    - Audit our usage: `CBORDecoder`, `loads`, `dumps`, `CBORTag` across 32+ files
    - Fix any edge cases found during audit
    - Update `pyproject.toml` to point to SteelSwap fork
    - Run full test suite: `uv run pytest -x -q`
    - Commit: `feat(m6.1): fork cbor2pure to SteelSwap, fix edge cases`

- [ ] **1.3: Fork uplc to SteelSwap**
    - Fork https://github.com/OpShin/uplc
    - Fix string-04 conformance failure (escape sequence parsing)
    - Run conformance suite: `uv run pytest tests/conformance/ -v`
    - Verify string-04 passes
    - Update `pyproject.toml` to point to SteelSwap fork
    - Commit: `fix(m6.1): fork uplc, fix string escape conformance`

- [ ] **1.4: Fork pycardano to SteelSwap**
    - Fork https://github.com/Python-Cardano/pycardano
    - Audit type stubs and correctness issues
    - Verify pycardano.cbor shim uses cbor2pure by default (confirmed: it does)
    - Fix any type annotation gaps
    - Update `pyproject.toml` to point to SteelSwap fork
    - Run full test suite
    - Commit: `feat(m6.1): fork pycardano to SteelSwap, fix type stubs`

- [ ] **1.5: Audit cryptography usage**
    - Compare KES/VRF outputs against Haskell test vectors
    - Verify Ed25519 sign/verify matches Haskell for known inputs
    - Document results in `docs/reference/dependency-audit.md`
    - No fork unless issues found
    - Commit: `docs(m6.1): cryptography audit — verified against Haskell vectors`

- [ ] **1.6: Remove all dependency workarounds**
    - For each workaround cataloged in 1.1, verify the fork fixes it
    - Remove the workaround code
    - Run full test suite after each removal
    - Commit: `refactor(m6.1): remove dependency workarounds, fixed in forks`

- [ ] **1.7: Open upstream PRs and document fork maintenance**
    - Open PR on upstream cbor2 with our fixes
    - Open PR on upstream uplc with string escape fix
    - Open PR on upstream pycardano with type stub fixes
    - Document PR links in `docs/reference/dependency-audit.md`
    - Document fork maintenance strategy: pyproject.toml git references, rebase on upstream releases, 6-month divergence window before replacement
    - Commit: `docs(m6.1): upstream PRs opened, fork maintenance strategy documented`

---

### Task 2: M6.4 — Haskell Test Parity

**Branch:** `m6.4-haskell-test-parity`

**Files:**
- Create: `docs/reference/test-parity-matrix.md`
- Modify/Create: test files across all `packages/vibe-cardano/tests/` subdirectories

**Work Items:**

- [ ] **2.1: Query knowledge base for Haskell test inventory**
    - Use `vibe-search` MCP to query all indexed Haskell test functions
    - Group by subsystem (serialization, networking, ledger, storage, consensus, crypto, mempool, forge, plutus, node)
    - Count existing Python tests per subsystem
    - Produce gap report: which subsystems have weakest coverage
    - Commit: `docs(m6.4): Haskell test inventory and gap report`

- [ ] **2.2: Serialization test parity**
    - Map Haskell CBOR encode/decode tests to existing Python tests
    - Write missing tests for all-era round-trip encoding
    - Run: `uv run pytest packages/vibe-cardano/tests/unit/ -v`
    - Commit: `test(m6.4): serialization test parity — [N] new tests`

- [ ] **2.3: Networking test parity**
    - Map Haskell mux, handshake, chain-sync, block-fetch tests
    - Write missing protocol state machine tests
    - Run: `uv run pytest packages/vibe-cardano/tests/network/ -v`
    - Commit: `test(m6.4): networking test parity — [N] new tests`

- [ ] **2.4: Ledger test parity**
    - Map Haskell UTxO rules, delegation, rewards tests (Byron-Conway)
    - Focus on critical paths: tx validation, certificate processing
    - Run: `uv run pytest packages/vibe-cardano/tests/ledger/ -v`
    - Commit: `test(m6.4): ledger test parity — [N] new tests`

- [ ] **2.5: Storage test parity**
    - Map Haskell ImmutableDB, VolatileDB, ChainDB tests
    - Focus on crash recovery, chain selection, gap handling
    - Run: `uv run pytest packages/vibe-cardano/tests/storage/ -v`
    - Commit: `test(m6.4): storage test parity — [N] new tests`

- [ ] **2.6: Consensus + Crypto test parity**
    - Map Haskell VRF, KES, Praos, epoch boundary, chain selection tests
    - Write missing property tests for leader election monotonicity
    - Run: `uv run pytest packages/vibe-cardano/tests/consensus/ packages/vibe-cardano/tests/crypto/ -v`
    - Commit: `test(m6.4): consensus + crypto test parity — [N] new tests`

- [ ] **2.7: Mempool + Forge test parity**
    - Map Haskell mempool capacity, tx selection, eviction tests
    - Map Haskell forge loop, block construction, header format tests
    - Write missing tests
    - Run: `uv run pytest packages/vibe-cardano/tests/mempool/ packages/vibe-cardano/tests/forge/ -v`
    - Commit: `test(m6.4): mempool + forge test parity — [N] new tests`

- [ ] **2.8: Plutus + Node integration test parity**
    - Map Haskell CEK machine, cost model, script evaluation tests
    - Map Haskell node startup, shutdown, peer management tests
    - Write missing tests
    - Run: `uv run pytest packages/vibe-cardano/tests/plutus/ packages/vibe-cardano/tests/node/ -v`
    - Commit: `test(m6.4): plutus + node test parity — [N] new tests`

- [ ] **2.9: Compile test parity matrix**
    - Create `docs/reference/test-parity-matrix.md` with per-subsystem coverage %
    - Document remaining gaps with Phase 7 plan
    - Run full suite: `uv run pytest -q`
    - Commit: `docs(m6.4): test parity matrix — [X]% coverage across 10 subsystems`

---

### Task 3: M6.5 — Node Hardening

**Branch:** `m6.5-node-hardening`

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/node/resilience.py`
- Create: `packages/vibe-cardano/src/vibe/cardano/security.py`
- Create: `packages/vibe-cardano/tests/node/test_power_loss.py`
- Create: `packages/vibe-cardano/tests/node/test_resilience.py`
- Create: `packages/vibe-cardano/tests/node/test_security.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py`

**Work Items:**

- [ ] **3.1: Power-loss recovery test harness**
    - Write automated test that starts node, syncs N blocks, sends SIGKILL, restarts, verifies state
    - Verify recovery from snapshot + diff replay in < 5 seconds
    - Test at multiple kill points (during sync, during forge, during snapshot write)
    - Commit: `test(m6.5): power-loss recovery harness — kill -9 survival`

- [ ] **3.2: Connection resilience**
    - Implement reconnect with exponential backoff in peer connection logic
    - Audit all miniprotocol handlers for MuxClosedError handling
    - Test peer churn: connect/disconnect/reconnect cycle
    - Verify no leaked tasks or sockets via `asyncio.all_tasks()` assertions
    - Commit: `feat(m6.5): connection resilience — reconnect with backoff`

- [ ] **3.3: Resource limits**
    - Add configurable memory soft limit with GC pressure on approach
    - Add file descriptor tracking and warning at 80% of ulimit
    - Add ChainDB volatile pruning beyond k blocks
    - Commit: `feat(m6.5): resource limits — memory cap, FD tracking, DB pruning`

- [ ] **3.4: Error handling audit**
    - Search codebase for bare `except Exception` and `except:` — replace with specific exceptions
    - Ensure all error paths log with context (slot, peer, block_hash)
    - Verify no silent failures in forge loop, chain-sync, block-fetch
    - Commit: `fix(m6.5): error handling audit — no bare except, contextual logging`

- [ ] **3.5: Security hardening**
    - Add CBOR decode limits: max depth (256), max size (64MB), max array length (65536)
    - Add malformed block rejection with detailed error logging
    - Add wire protocol state machine validation (reject out-of-order messages)
    - Verify no command injection via config/env vars (audit all `os.environ.get` + subprocess calls)
    - Commit: `feat(m6.5): security hardening — CBOR limits, malformed block handling`

- [ ] **3.6: Graceful shutdown verification**
    - Test SIGTERM during active sync — verify in-flight block completes before exit
    - Verify all async tasks cancelled cleanly (no "Task was destroyed but it is pending" warnings)
    - Verify socket FDs are closed on shutdown
    - Verify no corrupted storage state after SIGTERM
    - Commit: `test(m6.5): graceful shutdown verification — clean exit under all conditions`

---

### Task 4: M6.6 — Observability & Logging Overhaul

**Branch:** `m6.6-observability`

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/node/metrics.py`
- Create: `packages/vibe-cardano/src/vibe/cardano/node/health.py`
- Create: `packages/vibe-cardano/src/vibe/cardano/node/logging_config.py`
- Create: `packages/vibe-cardano/tests/node/test_metrics.py`
- Create: `packages/vibe-cardano/tests/node/test_health.py`
- Modify: all files with `logger.` calls (~40+ files)

**Work Items:**

- [ ] **4.1: Logging audit — remove stale debug output**
    - Find all `logger.debug()` and `logger.info()` calls across the codebase
    - Remove Phase 5 diagnostic output: hex dumps, "BLOCK-FETCH: received X bytes", temporary traces
    - Guard expensive debug formatting with `if logger.isEnabledFor(logging.DEBUG)`
    - Commit: `refactor(m6.6): remove stale debug logs, guard expensive formatting`

- [ ] **4.2: Standardize INFO log events to match Haskell**
    - Define target INFO events: forge stats, chain-sync progress, block validation, peer connect/disconnect, tip change, epoch transition, KES evolution, mempool activity
    - Rewrite INFO messages to be human-readable: `Forged block #42 at slot 1000 (0 txs, 848 bytes)`
    - Add structured `extra` fields for machine parsing
    - Commit: `refactor(m6.6): standardize INFO logs — Haskell event parity, human-readable`

- [ ] **4.3: JSON logging format option**
    - Create `logging_config.py` with configurable formatters
    - Support `VIBE_LOG_FORMAT=json` env var for structured JSON output
    - Default to human-readable format for terminal
    - Commit: `feat(m6.6): JSON log format via VIBE_LOG_FORMAT=json`

- [ ] **4.4: Prometheus metrics endpoint**
    - Add `prometheus_client` dependency
    - Create `metrics.py` with all gauges, counters, histograms from spec
    - Instrument: tip_slot, blocks_synced, blocks_forged, peers_connected, memory_rss, forge_duration, validation_duration
    - Expose `/metrics` endpoint via lightweight aiohttp server on configurable port
    - Write tests verifying metric values update correctly
    - Commit: `feat(m6.6): Prometheus metrics endpoint with 7 metric families`

- [ ] **4.5: Health endpoint**
    - Create `health.py` with `/health` HTTP endpoint
    - Return `{"status": "ok", "tip_slot": N, "peers": N, "syncing": bool, "version": "0.5.0"}`
    - Run on same port as metrics (default 9100)
    - Write tests
    - Commit: `feat(m6.6): HTTP health endpoint at /health`

- [ ] **4.6: Memory tracking for leak detection**
    - Add periodic RSS sampling (every 60s) via `resource.getrusage`
    - Log RSS at INFO level with delta from previous sample
    - Add top-N object type count via `gc.get_objects()` at DEBUG level
    - Expose as Prometheus gauge (`vibe_node_memory_rss_bytes`)
    - Commit: `feat(m6.6): memory leak detection — periodic RSS + object tracking`

---

## Wave 2 — Depends on M6.1

### Task 5: M6.2 — Code Deduplication & Cleanup

**Branch:** `m6.2-code-dedup`

**Files:**
- Modify/Delete: `packages/vibe-cardano/src/vibe/cardano/network/*.py` (consolidate protocol pairs)
- Create: `packages/vibe-cardano/src/vibe/cardano/node/startup.py`
- Create: `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py`
- Create: `packages/vibe-cardano/src/vibe/cardano/node/sync_loop.py`
- Create: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py`
- Create: `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py`
- Modify: `packages/vibe-core/src/vibe/core/` (extract generic abstractions)
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py` (1785 lines → split)

**Work Items:**

- [ ] **5.1: Generate duplication report**
    - Analyze all `*_protocol.py` vs base protocol files for duplicated logic
    - Identify scattered block decoding across run.py, blockfetch.py, serialization/block.py
    - Identify dead imports and unused functions
    - Document in a duplication report with recommended consolidation plan
    - Commit: `docs(m6.2): codebase duplication report`

- [ ] **5.2: Consolidate network protocol pairs**
    - For each pair (handshake.py + handshake_protocol.py, etc.): merge into single canonical file
    - Keep the better implementation, incorporate missing pieces from the other
    - Delete the redundant file
    - Update all imports across the codebase
    - Run full test suite after each merge
    - Commit per protocol: `refactor(m6.2): consolidate handshake protocol`, etc.

- [ ] **5.3: Consolidate block decoding**
    - Single canonical block decode function in `serialization/block.py`
    - Remove inline decoding from `run.py` and `blockfetch.py`
    - All callers use the canonical decoder
    - Run full test suite
    - Commit: `refactor(m6.2): consolidate block decoding into serialization/block.py`

- [ ] **5.4: Split run.py into focused modules**
    - Extract `_forge_loop` → `forge_loop.py`
    - Extract `_run_n2n_server`, `_run_n2c_server` → `inbound_server.py`
    - Extract peer connection logic → `peer_manager.py`
    - Extract initialization logic → `startup.py`
    - Extract sync pipeline → `sync_loop.py`
    - `run.py` becomes orchestrator that imports and calls these
    - Run full test suite after each extraction
    - Commit per extraction: `refactor(m6.2): extract forge_loop from run.py`, etc.

- [ ] **5.5: Extract generic abstractions to vibe-core**
    - Evaluate codec interface extraction (CBOR patterns → generic codec Protocol)
    - Evaluate storage abstraction extraction (append-only + snapshot patterns)
    - Evaluate connection management extraction (reconnect, backoff, health)
    - For each: create Protocol type in vibe-core, implement in vibe-cardano
    - Run full test suite
    - Commit: `refactor(m6.2): extract generic abstractions to vibe-core`

- [ ] **5.6: Remove dead code**
    - Delete unused imports, functions, and vestigial code from earlier phases
    - Run full test suite
    - Commit: `refactor(m6.2): remove dead code — [N] functions, [M] imports`

---

### Task 6: M6.3 — Data Structure Profiling

**Branch:** `m6.3-data-structure-profiling`

**Files:**
- Create: `benchmarks/data_structures/bench_instantiation.py`
- Create: `benchmarks/data_structures/bench_serialization.py`
- Create: `benchmarks/data_structures/bench_memory.py`
- Create: `benchmarks/data_structures/bench_real_workload.py`
- Create: `docs/reference/data-structure-benchmark-report.md`

**Work Items:**

- [ ] **6.1: Identify hot-path data structures**
    - Profile a real block sync (100 blocks) to find most-instantiated types
    - List: block headers, UTxO entries, tx bodies, protocol messages, CBOR tags
    - Document in benchmark report
    - Commit: `docs(m6.3): hot-path data structure inventory`

- [ ] **6.2: Benchmark instantiation across candidates**
    - For each hot-path type: implement as dataclass, pydantic v2, msgspec Struct, attrs
    - Benchmark 1M instantiations for each
    - Record results in JSON + markdown table
    - Commit: `bench(m6.3): instantiation benchmarks — dataclass vs pydantic vs msgspec vs attrs`

- [ ] **6.3: Benchmark serialization and memory**
    - Benchmark CBOR round-trip (encode + decode) for each candidate
    - Benchmark memory footprint at 1M instances (via `sys.getsizeof` + `tracemalloc`)
    - Benchmark field access latency
    - Commit: `bench(m6.3): serialization + memory benchmarks`

- [ ] **6.4: Profile real workload**
    - Run full block decode → validate → store cycle with each candidate on one hot path
    - Measure wall-clock time for 1000 blocks
    - Commit: `bench(m6.3): real workload profiling — 1000 block cycle`

- [ ] **6.5: Write recommendation report**
    - Compile all results into `docs/reference/data-structure-benchmark-report.md`
    - Recommend: which library for which layer (wire protocol, internal, storage)
    - Include proof-of-concept implementation on one hot path
    - Full migration plan for Phase 7
    - Commit: `docs(m6.3): data structure recommendation — [winner] for hot paths`

---

## Wave 3 — Depends on Waves 1 + 2

### Task 7: M6.7 — Benchmarking Suite

**Branch:** `m6.7-benchmarking-suite`

**Files:**
- Create: `benchmarks/critical_paths/bench_cbor_decode.py`
- Create: `benchmarks/critical_paths/bench_block_validation.py`
- Create: `benchmarks/critical_paths/bench_vrf.py`
- Create: `benchmarks/critical_paths/bench_kes.py`
- Create: `benchmarks/critical_paths/bench_chain_selection.py`
- Create: `benchmarks/critical_paths/bench_mempool.py`
- Create: `benchmarks/critical_paths/bench_storage.py`
- Create: `benchmarks/critical_paths/bench_forge_loop.py`
- Create: `benchmarks/baselines.json`
- Create: `docs/reference/benchmark-report.md`

**Work Items:**

- [ ] **7.1: CBOR decode benchmarks (all eras)**
    - Benchmark block decode for Byron, Shelley, Allegra, Mary, Alonzo, Babbage, Conway
    - Use real block samples from test fixtures
    - pytest-benchmark with min_rounds=100
    - Commit: `bench(m6.7): CBOR decode — all eras baselined`

- [ ] **7.2: Block validation + VRF + KES benchmarks**
    - Benchmark ledger rule validation per block
    - Benchmark VRF prove + verify
    - Benchmark KES sign + verify + evolve
    - Commit: `bench(m6.7): validation + crypto baselined`

- [ ] **7.3: Chain selection + mempool + storage benchmarks**
    - Benchmark chain selection with N candidates
    - Benchmark mempool tx add + validate + get_txs_for_block
    - Benchmark Arrow IPC write + read + UTxO lookup
    - Commit: `bench(m6.7): chain selection + mempool + storage baselined`

- [ ] **7.4: Forge loop end-to-end benchmark**
    - Benchmark full forge cycle: slot tick → leader check → block build → KES sign → store
    - Must complete in < 200ms (1s mainnet slot with safety margin)
    - Commit: `bench(m6.7): forge loop E2E — [X]ms per block`

- [ ] **7.5: Store baselines and write report**
    - Save all results to `benchmarks/baselines.json`
    - Write `docs/reference/benchmark-report.md` with bottleneck analysis
    - Add CI check script that compares against baselines (>10% regression = warning)
    - Commit: `docs(m6.7): benchmark baselines stored, bottleneck report written`

---

### Task 8: M6.9 — Preview Full Sync Benchmark

**Branch:** `m6.9-preview-sync-benchmark`

**Files:**
- Create: `infra/preview/docker-compose.preview.yml`
- Create: `infra/preview/scripts/sync-benchmark.py`
- Create: `docs/reference/preview-sync-report.md`

**Work Items:**

- [ ] **8.1: Set up preview sync infrastructure**
    - Docker Compose with vibe-node connecting to preview relays
    - Instrumentation: periodic metrics logging (every 10,000 blocks)
    - Script to capture wall-clock time, RSS, blocks/sec
    - Commit: `infra(m6.9): preview sync benchmark infrastructure`

- [ ] **8.2: Run vibe-node full sync from genesis**
    - Fresh data directory
    - Sync from genesis to tip
    - Record: wall-clock time, peak RSS, final chain size (Arrow IPC), UTxO count
    - Record throughput: avg, P50, P95, P99 blocks/sec
    - Commit: `docs(m6.9): vibe-node preview sync — [X] hours, [Y] blocks/sec`

- [ ] **8.3: Run Haskell node full sync (same hardware)**
    - Same machine, same network, fresh DB
    - Record same metrics for comparison
    - Commit: `docs(m6.9): Haskell preview sync — [X] hours, [Y] blocks/sec`

- [ ] **8.4: Write comparison report and update README**
    - Side-by-side comparison table in `docs/reference/preview-sync-report.md`
    - Update README.md benchmarks section with real preview numbers
    - Commit: `docs(m6.9): preview sync comparison report — vibe-node vs Haskell`

---

## Wave 4 — Depends on All Above

### Task 9: M6.8 — 48-Hour Soak Test on Preview

**Branch:** `m6.8-48h-soak-preview`

**Files:**
- Create: `infra/preview/docker-compose.soak.yml`
- Create: `infra/preview/grafana/dashboards/vibe-node.json`
- Create: `infra/preview/prometheus/prometheus.yml`
- Create: `infra/preview/scripts/soak-report.py`
- Create: `docs/reference/soak-test-report.md`

**Work Items:**

- [ ] **9.1: Set up soak test monitoring stack**
    - Docker Compose: vibe-node + Prometheus + Grafana
    - Prometheus scrapes vibe-node /metrics every 15s
    - Grafana dashboard: tip slot, memory, peers, block rate, errors
    - Alert rules: tip drift > 120s, memory spike > 2x baseline
    - Commit: `infra(m6.8): soak test monitoring stack — Prometheus + Grafana`

- [ ] **9.2: Run 48-hour soak test**
    - Start vibe-node connected to preview relays
    - Let run for 48 continuous hours
    - Collect: tip agreement logs, memory samples, error counts, restart count
    - Fallback: if preview unstable, switch to local devnet with extended params
    - No commit — just data collection

- [ ] **9.3: Generate soak test report**
    - Script to analyze collected metrics
    - Pass/fail on each criterion: tip within 120s, no OOM, no exceptions, memory growth < 10%, zero interventions
    - Export Grafana screenshots/PNG dashboards
    - Write `docs/reference/soak-test-report.md`
    - Commit: `docs(m6.8): 48-hour soak test report — [PASS/FAIL]`

---

### Task 10: M6.10 — Haskell Conformance Gap Analysis

**Branch:** `m6.10-conformance-gap-analysis`

**Files:**
- Create: `tools/conformance/cbor_diff.py`
- Create: `tools/conformance/utxo_diff.py`
- Create: `tools/conformance/tip_logger.py`
- Create: `tools/conformance/header_compare.py`
- Create: `tools/conformance/run_comparison.py`
- Create: `docs/reference/conformance-report.md`

**Work Items:**

- [ ] **10.1: Build CBOR wire protocol diff tool**
    - Capture CBOR bytes for each miniprotocol message type from both nodes
    - Field-by-field comparison and diff output
    - Commit: `feat(m6.10): CBOR wire protocol diff tool`

- [ ] **10.2: Build block header comparison tool**
    - In shared devnet, capture headers from both nodes at same slots
    - Byte-by-byte comparison of all 10 header fields
    - VRF output, KES sig structure, opcert encoding, body hash
    - Commit: `feat(m6.10): block header comparison tool`

- [ ] **10.3: Build UTxO, tip, and tx validation comparison tools**
    - Dump UTxO sets at epoch boundaries from both nodes, diff
    - Log tip slot from all nodes every slot, detect divergence > k slots
    - Submit identical transactions to both nodes, compare accept/reject results
    - Commit: `feat(m6.10): UTxO diff + tip tracker + tx validation comparator`

- [ ] **10.4: Run extended devnet comparison (1000+ epochs)**
    - Start 3-node devnet (2 Haskell + 1 vibe-node)
    - Run for ~6 hours (1000 epochs at 100 slots, 0.2s each)
    - Collect all comparison data
    - No commit — data collection

- [ ] **10.5: Analyze and fix divergences**
    - Triage every divergence by severity (critical/high/medium/low)
    - Fix all critical and high divergences
    - Document remaining low-severity for Phase 7
    - Run comparison again to verify fixes
    - Commit: `fix(m6.10): [N] conformance divergences fixed`

- [ ] **10.6: Write conformance report**
    - Compile results into `docs/reference/conformance-report.md`
    - Zero critical/high divergences remaining
    - Comparison tooling committed for future regression testing
    - Commit: `docs(m6.10): conformance report — zero critical/high divergences`

---

## Plane Work Item Summary

Each numbered work item above (1.1, 1.2, ... 10.6) should be created as a Plane issue under its corresponding module. Total: **49 work items across 10 modules**.

| Module | Work Items | Wave |
|--------|-----------|------|
| M6.1 — Dependency Audit | 7 | 1 |
| M6.4 — Haskell Test Parity | 9 | 1 |
| M6.5 — Node Hardening | 6 | 1 |
| M6.6 — Observability | 6 | 1 |
| M6.2 — Code Dedup | 6 | 2 |
| M6.3 — Data Structure Profiling | 5 | 2 |
| M6.7 — Benchmarking Suite | 5 | 3 |
| M6.9 — Preview Sync Benchmark | 4 | 3 |
| M6.8 — 48h Soak Test | 3 | 4 |
| M6.10 — Conformance Gap Analysis | 6 | 4 |
