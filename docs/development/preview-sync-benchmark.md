# Preview Sync Benchmark

This document describes the methodology for benchmarking vibe-node's full sync performance against the Haskell cardano-node on the Cardano **preview testnet**.

## Motivation

Acceptance criterion #6 requires vibe-node to **match or beat the Haskell node in average memory usage across 10 days**. Before attempting that 10-day soak test, we need to understand baseline sync performance: how long does it take to sync the full preview chain, and what are the memory and throughput characteristics?

This benchmark provides:

- **Baseline sync time** — wall-clock time to reach chain tip from genesis
- **Memory profile** — peak RSS, mean RSS, and P95 RSS throughout the sync
- **Throughput curve** — blocks/second at various points in the sync (historical vs. near-tip)
- **Apples-to-apples comparison** — both nodes run on the same hardware, same network, same metrics capture

## Methodology

### Setup

Both nodes sync the **preview testnet** (network magic 2) from genesis, connecting to the public relay at `relays-new.cardano-testnet.iohkdev.io:3001`.

| Parameter | vibe-node | Haskell node |
|-----------|-----------|--------------|
| Image | Custom (Dockerfile.preview-sync) | `ghcr.io/intersectmbo/cardano-node:10.4.1` |
| Network | Preview (magic 2) | Preview (magic 2) |
| Relay | `relays-new.cardano-testnet.iohkdev.io:3001` | Same |
| Storage | Docker volume | Docker volume |
| Metrics interval | 30s (configurable) | 30s (configurable) |

### Metrics Captured

Every `METRICS_INTERVAL` seconds (default 30), the metrics sidecar captures:

| Metric | Source (vibe-node) | Source (Haskell) |
|--------|-------------------|-----------------|
| Wall-clock elapsed | `time.monotonic()` | `date +%s` |
| Current RSS | `/proc/PID/status` VmRSS | `/proc/PID/status` VmRSS |
| Peak RSS | `/proc/PID/status` VmPeak | `/proc/PID/status` VmPeak |
| Block height | Node query (TODO) | `cardano-cli query tip` |
| Sync progress | Computed | `cardano-cli query tip` syncProgress |

### Analysis

The analysis script (`scripts/analyze-sync-results.py`) computes:

- **Overall throughput**: final_block_height / total_elapsed_seconds
- **Interval throughput**: blocks synced between consecutive samples, divided by time delta
- **Throughput percentiles**: P50, P95, P99 of interval throughput values
- **Memory statistics**: peak, mean, and P95 of RSS samples
- **Comparison delta**: ratio of vibe-node value to Haskell value for key metrics

## Hardware Specs

*To be filled when the actual benchmark is run.*

| Spec | Value |
|------|-------|
| Machine | TBD |
| CPU | TBD |
| Cores | TBD |
| RAM | TBD |
| Storage | TBD |
| OS | TBD |
| Docker version | TBD |

## Results

*Placeholder — to be populated after running the benchmark.*

### Sync Performance Comparison

| Metric | vibe-node | Haskell node | Delta |
|--------|-----------|--------------|-------|
| Wall-clock time | TBD | TBD | TBD |
| Final block height | TBD | TBD | — |
| Overall throughput | TBD blocks/s | TBD blocks/s | TBD |
| Throughput (P50) | TBD blocks/s | TBD blocks/s | TBD |
| Throughput (P95) | TBD blocks/s | TBD blocks/s | TBD |
| Throughput (P99) | TBD blocks/s | TBD blocks/s | TBD |
| Peak RSS | TBD MiB | TBD MiB | TBD |
| Mean RSS | TBD MiB | TBD MiB | TBD |
| P95 RSS | TBD MiB | TBD MiB | TBD |

## Reproducing the Benchmark

### Prerequisites

- Docker and Docker Compose
- ~50 GB free disk space (for both nodes' chain data)
- Stable internet connection to preview testnet relays

### Run vibe-node sync

```bash
# From the repository root:
./scripts/run-sync-benchmark.sh --interval 30

# Or in background:
./scripts/run-sync-benchmark.sh --interval 30 --detach
```

### Run Haskell node sync

```bash
# From the repository root:
./scripts/run-haskell-sync-benchmark.sh --interval 30

# Or in background:
./scripts/run-haskell-sync-benchmark.sh --interval 30 --detach
```

### Analyze results

```bash
python scripts/analyze-sync-results.py \
    --vibe infra/preview-sync/results/vibe-node-metrics.json \
    --haskell infra/preview-sync/results/haskell-node-metrics.json \
    --hardware infra/preview-sync/results/hardware-info.json \
    --output benchmarks/preview-sync/
```

This produces:

- `benchmarks/preview-sync/comparison-report.md` — Markdown table
- `benchmarks/preview-sync/comparison-summary.json` — machine-readable JSON

### Notes

- Run both benchmarks on the **same machine** for a fair comparison
- Avoid running them simultaneously (they compete for network and disk I/O)
- The Haskell node image is `linux/amd64` — on ARM Macs, it runs under Rosetta/QEMU which adds overhead. For fair comparison, use an x86_64 host or run both under the same emulation.
- Preview testnet sync typically takes several hours to a day depending on hardware
- Metrics capture is resilient to node restarts (it waits for the target process)
