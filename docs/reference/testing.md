# Testing Guide

## Quick Start

```bash
# Run ALL tests (default — just works)
uv run pytest

# Run with verbose output
uv run pytest -v

# Run with coverage
uv run pytest --cov=packages/vibe-cardano/src --cov-report=term-missing
```

## Test Locations

Tests are split across two directories, both auto-discovered by pytest:

| Directory | Contents |
|-----------|----------|
| `tests/` | Integration, conformance, property, and unit tests for the full node |
| `packages/vibe-cardano/tests/` | Unit tests for vibe-cardano subsystems (crypto, consensus, network, plutus) |

## Running Specific Test Subsets

### By directory

```bash
# Crypto (VRF, KES, OCert)
uv run pytest packages/vibe-cardano/tests/crypto/

# Consensus (Praos, chain selection, epoch boundary, HFC)
uv run pytest packages/vibe-cardano/tests/consensus/

# Network (handshake, chain-sync, block-fetch, tx-submission, keep-alive)
uv run pytest packages/vibe-cardano/tests/network/

# Plutus (evaluation, ScriptContext, cost models)
uv run pytest packages/vibe-cardano/tests/plutus/

# Ledger rules (Byron, Shelley, Allegra, Mary, Alonzo, Babbage, Conway)
uv run pytest tests/unit/

# Conformance tests (Ogmios fixtures + live Haskell node)
uv run pytest tests/conformance/

# Integration tests (Docker Compose, devnet)
uv run pytest tests/integration/
```

### By marker

```bash
# Only conformance tests
uv run pytest -m conformance

# Only integration tests (requires Docker)
uv run pytest -m integration

# Only devnet infrastructure tests
uv run pytest -m devnet

# Only fixture-based conformance (no Docker needed)
uv run pytest -m fixture_only

# Skip slow tests
uv run pytest -m "not slow"

# Skip integration and conformance (fast local run)
uv run pytest -m "not integration and not conformance"
```

### By keyword

```bash
# All Alonzo-related tests
uv run pytest -k alonzo

# All VRF tests
uv run pytest -k vrf

# All Conway governance tests
uv run pytest -k conway

# A specific test class
uv run pytest -k TestChainSelection

# A specific test function
uv run pytest -k test_leader_check_zero_stake
```

### By file

```bash
# Single file
uv run pytest packages/vibe-cardano/tests/consensus/test_praos.py

# Single test
uv run pytest packages/vibe-cardano/tests/consensus/test_praos.py::TestLeaderCheck::test_zero_stake
```

## Markers

| Marker | Description | Requires |
|--------|-------------|----------|
| `unit` | Isolated function/module correctness | Nothing |
| `property` | Hypothesis-based invariant verification | Nothing |
| `conformance` | Bit-for-bit match with Haskell node | Docker (Ogmios) |
| `integration` | Multi-component with Docker Compose | Docker |
| `fixture_only` | Cached Ogmios fixtures, always runs | Nothing |
| `devnet` | 3-node private cluster validation | Docker |
| `slow` | Benchmarks, statistical tests, large data | Nothing (just slow) |

## Plugins

| Plugin | What it does | Usage |
|--------|-------------|-------|
| **pytest-asyncio** | Async test support | `async def test_*` just works (`asyncio_mode = "auto"`) |
| **pytest-hypothesis** | Property-based testing | `@given(...)` decorators |
| **pytest-xdist** | Parallel execution | `uv run pytest -n auto` |
| **pytest-cov** | Coverage reporting | `uv run pytest --cov=...` |
| **pytest-benchmark** | Performance benchmarks | `uv run pytest --benchmark-enable` (disabled by default) |
| **pytest-sugar** | Pretty output | Automatic in terminal |
| **pytest-timeout** | Prevent hangs | Default 300s per test |

## CI vs Local

Benchmarks and sugar are disabled in CI:

```bash
# CI run (no sugar, no benchmarks, xdist for speed)
uv run pytest -p no:sugar -p no:benchmark -n auto

# Local run (sugar enabled, benchmarks disabled by default)
uv run pytest
```

To enable benchmarks locally:

```bash
uv run pytest --benchmark-enable -k benchmark
```

## Test Counts by Subsystem

*As of Phase 4 completion:*

| Subsystem | Tests |
|-----------|-------|
| Crypto (VRF, KES, OCert) | ~190 |
| Consensus (Praos, chain selection, epoch, HFC) | ~400 |
| Network (all miniprotocols) | ~420 |
| Plutus (evaluation, context, cost models) | ~140 |
| Ledger (Byron → Conway) | ~370 |
| Conformance (fixtures + Ogmios) | ~120 |
| Integration (devnet, infrastructure) | ~50 |
| **Total** | **~2,400** |
