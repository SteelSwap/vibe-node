# Logging Audit — Phase 6 M6.6

**Date:** 2026-03-22
**Scope:** Production codebase (packages/vibe-cardano/src, packages/vibe-core/src)

## Summary

153 logger calls across 24 files. Zero `isEnabledFor` guards anywhere.

| Level | Count |
|-------|-------|
| debug | 62 |
| info | 61 |
| warning | 21 |
| error | 8 |
| exception | 1 |
| **Total** | **153** |

## Action Items

### Remove (2 lines)
1. `run.py:522-525` — Stale `"BLOCK-FETCH: received %d bytes, hex[:8]=%s"` — fires every block, hex dump diagnostic
2. `run.py:1094-1102` — Duplicate forged block log (already logged in `forge/block.py:363`)

### Downgrade INFO → DEBUG (11 lines)
1. `run.py:1241` — inbound tx added to mempool (per-tx)
2. `chainsync_protocol.py:767` — "Chain-sync server started" (per-connection)
3. `chainsync_protocol.py:838` — client disconnected during await
4. `chainsync_protocol.py:845` — client sent Done
5. `keepalive_protocol.py:385` — keep-alive stop requested
6. `keepalive_protocol.py:400` — keep-alive stop during wait
7. `local_chainsync_protocol.py:660` — local chain-sync MsgDone
8. `local_txsubmission_protocol.py:410` — local tx-submission MsgDone
9. `local_txmonitor_protocol.py:702` — local tx-monitor MsgDone
10. `txsubmission_protocol.py:594` — tx-submission stop requested
11. `txsubmission_protocol.py:610` — tx-submission MsgDone

### Add `isEnabledFor` guards (14 hot-path call sites)
- `vibe-core/protocols/runner.py:177, :269` — every protocol send/recv
- `vibe-core/protocols/pipelining.py:178, :217` — every pipelined send/recv
- `storage/volatile.py:230` — every block add
- `storage/chaindb.py:150, :178, :272, :280, :290` — per-block chain ops
- `node/kernel.py:323` — every block added to kernel
- `consensus/praos.py:226` — every header validated
- `ledger/delegation.py:170, :178, :189, :199, :206` — every delegation cert
