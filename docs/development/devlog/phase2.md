# Phase 2 — Serialization & Networking

**Date:** 2026-03-19
**Status:** Complete
**Version:** v0.2.0

Phase 2 built the foundation for talking to Cardano: CBOR block decoders, the Ouroboros TCP multiplexer, a typed protocol state machine framework, and the handshake + chain-sync miniprotocols. The gate test proved it works end-to-end: connect to a real Haskell cardano-node, negotiate version 15, and sync 1,000 block headers.

---

## M2.1 — CBOR Block Decoder

### What We Built

- **Block header decoder** — decodes all-era block headers (Shelley through Conway), computes Blake2b-256 block hashes, detects era from CBOR tag byte
- **Block body decoder** — parses transactions, witnesses, and auxiliary data using pycardano types with graceful fallback to raw cbor2
- **pycardano evaluation** — discovered pycardano has no Block/BlockHeader types (must build custom), strong Shelley+ transaction coverage, no Byron support

### Key Findings

- cbor2 C extension validates tags 0-5 semantically (datetime/bignum) before tag_hook runs — must strip tag byte manually for Cardano era tags
- Ogmios v6 returns JSON, not raw CBOR — for true CBOR conformance testing we need the N2N protocol
- Babbage/Conway headers have 14 fields with single vrf_result; Shelley-Alonzo have 15 fields with two VRF certs

---

## M2.2 — TCP Multiplexer

### What We Built

- **Segment framing** — encode/decode 8-byte Ouroboros mux headers (timestamp, protocol ID with initiator bit, payload length)
- **Async TCP bearer** — read_segment/write_segment over asyncio streams with error handling
- **Mux/demux** — route segments to per-miniprotocol channels with round-robin fair scheduling, bounded ingress queues (qMax), and IngressOverflowError

### Key Finding

The initiator bit direction: **M=0 for initiator, M=1 for responder** — opposite of what the task description assumed. Verified against Haskell `Network.Mux.Codec.encodeSDU`.

### Behavioral Divergence

We DROP unknown miniprotocol IDs (log warning). Haskell escalates to ShutdownNode. Acceptable until connection manager exists — documented in tests.

---

## M2.3 — Typed Protocol Framework

### What We Built

- **Agency model** — Client/Server/Nobody enum, PeerRole (Initiator/Responder)
- **Protocol ABC** — abstract base defining states, agency map, valid transitions
- **Peer class** — async send/recv with agency validation
- **Protocol runner** — drives typed FSM over a mux channel via a Codec interface
- **Codec protocol** — encode/decode abstraction that each miniprotocol implements

---

## M2.4 — Handshake Protocol

### What We Built

- **CBOR messages** — MsgProposeVersions, MsgAcceptVersion, MsgRefuse with all refuse reason variants
- **Version negotiation** — derived from Haskell's `pureHandshake`: highest common version, OR-merge initiator_only, server wins peer_sharing
- **HandshakeProtocol FSM** — StPropose → StConfirm → StDone
- **run_handshake_client** — high-level async function with timeout support

### Constants

- N2N versions: V14, V15
- Network magic: mainnet=764824073, preprod=1, preview=2
- Handshake timeout: 10 seconds

---

## M2.5 — Chain-Sync Client

### What We Built

- **CBOR messages** — all 8 chain-sync messages with Point/Origin/Tip domain types
- **ChainSyncProtocol FSM** — StIdle, StNext, StIntersect, StDone with AwaitReply self-transition
- **ChainSyncClient** — find_intersection, request_next, recv_after_await, done
- **run_chain_sync** — full sync loop with callbacks, AwaitReply handling, stop_event

### Wire Format

Matches Haskell `codecChainSync` exactly. Verified by reading the Haskell source from our `code_chunks` table during development.

---

## M2.6 — Conformance Test Harness

### What We Built

- **Ogmios fixtures** — conftest.py with WebSocket client, health check, skip-when-Docker-down
- **Block metadata conformance** — verify block IDs, heights, ancestor chain, era detection against Ogmios
- **Integration tests** — handshake with real node (accept, version selection, wrong-magic refuse), chain-sync (1,000 headers from origin)

---

## Pipeline Improvements

### is_test Column

Added `is_test` boolean to `code_chunks` — auto-detected during ingestion via path convention. Backfilled 329,538 test chunks (11,611 unique functions) across all 6 repos.

### Split Search

Stage 2 now searches production code and test code separately:
- 10 production code candidates (vector search, `is_test=FALSE`)
- 10 test code candidates (vector search, `is_test=TRUE`)
- 10 test code candidates (keyword search: golden*, prop_*, roundTrip*, ts_*)
- Unified deduplication across all methods

### Continuation Search

After Stage 3 evaluation, if >=60% of candidates linked, automatically search deeper (up to 3 rounds) by excluding already-seen IDs.

### CLI Improvements

- `vibe-node research extract-rules all` — runs all 10 subsystems
- `vibe-node research qa-validate all` — validates all subsystems
- `vibe-node research reset` — clears all pipeline output for clean re-extraction

---

## Test Audit

Conducted a thorough test audit comparing our implementation against:
1. The `test_specifications` database (16,646 proposed tests)
2. Haskell vendor test suites (11,611 indexed test functions)

Found and filled 87 test gaps across mux/demux (qMax, fairness), metadata validation, protocol semantics, and CBOR property tests.

---

## Issues Encountered & Fixed

| Issue | Fix |
|-------|-----|
| cbor2 C extension tag validation blocks era detection | Strip tag byte manually before decoding |
| Ogmios returns JSON not CBOR | Use for metadata conformance; raw CBOR via N2N (Track B) |
| Conformance tests timeout in worktree (Docker unreachable) | Run integration tests inline, not in agents |
| Dead agent's broken test file merged via conflict resolution | Replaced with clean version (PR #30) |
| asyncpg "another operation in progress" in QA pipeline | Pool-per-task instead of shared connection |
| git grep UTF-8 decode crash on binary files in vendor repos | `errors="replace"` instead of `text=True` |
| Progress bars cross-contaminated between gap/xref phases | Explicit task_id parameter |
| Agents can't run `gh pr create` | Open PRs from main session after agent completes |
