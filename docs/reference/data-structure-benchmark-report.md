# Data Structure Benchmark Report — Phase 6 M6.3

**Date:** 2026-03-22
**Python:** 3.14.3 (Apple Silicon)
**Benchmark:** 11-field struct, 1M instantiations, 5M field accesses

## Hot-Path Data Structures

| Type | Module | Fields | `__slots__` | Frequency |
|------|--------|--------|-------------|-----------|
| BlockHeader | serialization/block.py | 11 | Yes (frozen) | Per-block |
| DecodedTransaction | serialization/transaction.py | 7 | Yes (frozen) | Per-tx |
| Point | network/chainsync.py | 2 | Yes (frozen) | Per-message |
| Tip | network/chainsync.py | 2 | Yes (frozen) | Per-message |
| BlockEntry | node/kernel.py | 6 | **No** | Per-block |
| BlockInfo | storage/volatile.py | 4 | Yes (frozen) | Per-block |
| _ChainTip | storage/chaindb.py | 3 | Yes (frozen) | Per-block |
| BlockDiff | storage/ledger.py | 3 | Yes (frozen) | Per-block |

**Quick win:** `BlockEntry` in kernel.py is the only hot-path type missing `slots=True`.

## Benchmark Results

### Instantiation (1M instances)

| Candidate | Time (s) | Per instance (ns) | Relative |
|-----------|----------|-------------------|----------|
| **plain `__slots__`** | 0.257 | 257 | **1.0x (fastest)** |
| NamedTuple | 0.288 | 288 | 1.1x |
| attrs.define | 0.605 | 605 | 2.4x |
| dataclass(frozen,slots) | 0.741 | 741 | 2.9x |
| dataclass(frozen) | 0.753 | 753 | 2.9x |
| pydantic.BaseModel | 0.955 | 955 | 3.7x |

### Field Access (5M iterations, 3 fields each)

| Candidate | Per access (ns) | Relative |
|-----------|----------------|----------|
| **dataclass(frozen)** | 5.7 | **1.0x** |
| dataclass(frozen,slots) | 5.7 | 1.0x |
| attrs.define | 5.8 | 1.0x |
| plain `__slots__` | 5.9 | 1.0x |
| NamedTuple | 11.6 | 2.0x |
| pydantic.BaseModel | 21.2 | 3.7x |

### Memory (10K instances)

| Candidate | tracemalloc (B/inst) | getsizeof (B) |
|-----------|---------------------|---------------|
| **dataclass(frozen,slots)** | 129 | 120 |
| **plain `__slots__`** | 129 | 120 |
| attrs.define | 145 | 136 |
| NamedTuple | 153 | 136 |
| dataclass(frozen) | 177 | 48* |
| pydantic.BaseModel | 1,297 | 72* |

*getsizeof underreports for dict-backed objects

## Recommendation

**Keep dataclass(frozen=True, slots=True) for all hot-path types.**

Rationale:
- **Field access is identical** across dataclass, attrs, and plain `__slots__` (~5.7ns). This is the dominant operation during sync (millions of field reads per second). No library wins here.
- **Instantiation is 2.9x slower than plain `__slots__`** but the absolute difference is 484ns per instance. At 15,000 blocks/sec sync rate, that's 7.3ms per second — negligible.
- **Memory is tied for smallest** with plain `__slots__` at 129 bytes/instance.
- **attrs** is slightly faster to instantiate (2.4x vs 2.9x) but adds a dependency for marginal gain.
- **pydantic** is 3.7x slower to instantiate and 3.7x slower for field access — inappropriate for hot paths.
- **msgspec** was not benchmarkable (Struct doesn't support the same patterns) but is designed for serialization, not general data containers.

### Action Items for Phase 7

1. Add `slots=True` to `BlockEntry` in kernel.py (quick win, ~10% memory reduction)
2. No library migration needed — current `dataclass(frozen=True, slots=True)` is optimal
3. If instantiation becomes a bottleneck (profiling shows >5% CPU in `__init__`), consider `NamedTuple` for the smallest types (Point, Tip) — 2.6x faster instantiation at the cost of immutable tuple semantics
