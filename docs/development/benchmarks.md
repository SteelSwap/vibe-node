# Benchmark Suite & Bottleneck Analysis

Performance benchmarks for vibe-node's critical code paths, measured with
[pytest-benchmark](https://pytest-benchmark.readthedocs.io/) on Apple M-series
silicon (Python 3.14, cbor2pure).

## Running Benchmarks

```bash
# Run all benchmarks
uv run pytest tests/benchmark/ -v -o "addopts=" -p benchmark --benchmark-only

# Save results as JSON
uv run pytest tests/benchmark/ -o "addopts=" -p benchmark \
    --benchmark-only --benchmark-json=/tmp/bench-new.json

# Check for regressions against baselines
python scripts/check-benchmark-regression.py /tmp/bench-new.json
```

## Baseline Results

Baselines are stored in `benchmarks/baselines.json` and checked for regressions
in CI. The threshold is 20% — any benchmark that regresses more than 20% from
baseline causes a failure.

### CBOR Decode (M6.7.1)

Block CBOR deserialization across all Cardano eras:

| Operation | Era | Mean | Notes |
|-----------|-----|------|-------|
| Raw `cbor2.loads` | Byron EBB | 4.2 us | Smallest block structure |
| Raw `cbor2.loads` | Byron Main | 6.5 us | |
| Raw `cbor2.loads` | Shelley-Alonzo | 9.7 us | Two-VRF-cert format |
| Raw `cbor2.loads` | Babbage-Conway | 9.3 us | Single vrf_result format |
| Era detection | All | 9.7 us | Tag parse via cbor2.loads |
| Header decode | Shelley-Alonzo | 22.2 us | Full decode + dataclass construction |
| Header decode | Babbage-Conway | 22.0 us | Slightly fewer fields |
| Round-trip | Shelley/Conway | 23.9 us | Decode + re-encode |

**Finding:** CBOR decode is dominated by cbor2pure overhead (~10us per loads call).
Era detection does a full decode — there's room for optimization with a fast-path
tag parser that reads only the first few CBOR bytes.

### Cryptographic Operations (M6.7.2)

| Operation | Mean | Notes |
|-----------|------|-------|
| Blake2b-256 (32B) | 0.31 us | Hash header/tx |
| Blake2b-256 (1KB) | 1.1 us | Typical transaction |
| Blake2b-256 (64KB) | 60.9 us | Large block body |
| Ed25519 keygen | 67.6 us | |
| Ed25519 sign | 80.5 us | |
| Ed25519 verify | 162.7 us | Via `cryptography` library |
| KES sign (depth 6) | 62.1 us | Mainnet config (Sum6KES) |
| KES verify (depth 6) | 140.5 us | 7 Ed25519 verifications |
| KES keygen (depth 3) | 530.4 us | 8 Ed25519 keypairs |
| KES derive VK | 0.38 us | Cached — no crypto needed |
| VRF prove | N/A | Requires native extension |
| VRF verify | N/A | Requires native extension |

**Finding:** Ed25519 verify (163us) is the most expensive single crypto op.
KES verify at depth 6 costs ~140us because it performs 7 sequential Ed25519
verifications (one per tree level + leaf). KES sign is faster (~62us) because
it only signs at the leaf level with minimal tree traversal.

### Chain Selection & Operations (M6.7.3)

| Operation | Mean | Notes |
|-----------|------|-------|
| Chain comparison (different length) | 0.09 us | Fast-path: just compare block numbers |
| Chain comparison (VRF tiebreak) | 0.39 us | Converts 64-byte VRF to int |
| `should_switch_to` with fork point | 0.22 us | Full k-deep check |
| Select best of 10 candidates | 0.63 us | Linear scan |
| Select best of 100 candidates | 5.5 us | Linear scan |
| Mempool add_tx | 35 us | asyncio overhead dominates |
| Mempool add 100 txs | 3.4 ms | ~34us per tx |
| Mempool snapshot (100 txs) | 33 us | |
| VolatileDB add_block | 34 us | In-memory, no disk |
| VolatileDB get_block (from 1K) | 33 us | Dict lookup + asyncio |
| UTxO lookup hit (10K set) | 4.3 us | Arrow table row read |
| UTxO lookup miss | 0.04 us | Dict miss — near zero |
| UTxO lookup (100K set) | 5.0 us | Scales well |
| Apply block (300 mutations) | 2.0 ms | 150 consume + 150 create |
| Rollback single block | 1.4 ms | Diff reversal |

**Finding:** Chain selection is negligible (<1us for typical operations).
Mempool and storage ops are dominated by asyncio event loop overhead (~27us
per `loop.run_until_complete` call). The UTxO lookup hit path (4.3us) is
bottlenecked by Arrow table row reading — the dict index lookup itself is
sub-microsecond.

### Forge Loop (M6.7.4)

| Operation | Mean | Notes |
|-----------|------|-------|
| Body hash | 0.17 us | Blake2b-256 of small body |
| Header body CBOR encode | 8.4 us | |
| KES sign header | 62.3 us | **Bottleneck** |
| Full block CBOR encode | 12.1 us | |
| **Forge empty block** | **106.9 us** | |
| **Forge 10 txs** | **115.9 us** | |
| **Forge 100 txs** | **194.9 us** | |

**Finding:** The forge loop is well under the 200ms target at all transaction
counts. The primary bottleneck is KES signing (~62us, 60% of empty forge time).
CBOR encoding scales linearly with tx count but adds only ~1us per transaction.

## Bottleneck Analysis

### Critical Path: Block Receipt to Validated

```
Network receive → CBOR decode (22us) → Header verify:
  ├── KES verify (140us)  ← BOTTLENECK
  ├── VRF verify (TBD — needs native ext)
  └── Blake2b hash (0.3us)
Total: ~163us per block header
```

### Critical Path: Slot Tick to Block Forged

```
Leader check:
  ├── VRF prove (TBD — needs native ext)
  └── Threshold check (<1us)
Block construction:
  ├── Body assembly + hash (8-12us)
  ├── Header CBOR encode (8us)
  ├── KES sign (62us)  ← BOTTLENECK
  └── Full block CBOR encode (12us)
Total: ~107-195us (0-100 txs)
```

### Optimization Opportunities

1. **CBOR decode** — Replace `cbor2pure` with a Rust/C extension for 5-10x
   speedup on block decode. The pure Python implementation adds ~10us per
   `loads` call.

2. **Era detection** — Fast-path the tag byte parse to avoid a full CBOR
   decode. Can read era from the first 1-2 bytes directly.

3. **Asyncio overhead** — The VolatileDB and mempool operations pay ~27us
   per `run_until_complete`. For the forge hot path, consider synchronous
   alternatives.

4. **Arrow UTxO reads** — The `_read_row` method iterates column-by-column
   (4.3us for a hit). A batch-read or cached row approach could reduce this.

5. **VRF native extension** — Currently not benchmarked. Once built, VRF
   prove/verify will add to both the forge and validation paths.

## Regression Detection

The `scripts/check-benchmark-regression.py` script compares new benchmark
results against `benchmarks/baselines.json`:

```bash
# Run new benchmarks
uv run pytest tests/benchmark/ -o "addopts=" -p benchmark \
    --benchmark-only --benchmark-json=/tmp/new.json

# Check for regressions (default: 20% threshold)
python scripts/check-benchmark-regression.py /tmp/new.json

# Stricter threshold (10%)
python scripts/check-benchmark-regression.py /tmp/new.json --threshold 0.10
```

Exit code 0 = no regressions. Exit code 1 = regressions detected.

## Updating Baselines

After intentional performance changes (optimizations or new features that
affect benchmarks), update the baselines:

```bash
uv run pytest tests/benchmark/ -o "addopts=" -p benchmark \
    --benchmark-only --benchmark-json=benchmarks/baselines.json
git add benchmarks/baselines.json
git commit -m "chore: update benchmark baselines"
```
