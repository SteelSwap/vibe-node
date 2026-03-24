# Code Style Guide

Enforced by **ruff** (lint + isort) and **black** (format). Configuration in `pyproject.toml`.

## Formatting

- **Line length:** 99 characters
- **Formatter:** black + ruff format
- **Pre-commit:** hooks run automatically on `git commit`
- **CI:** fails on violations

## Imports

Ordered by ruff isort (rule `I`):

1. Standard library (`import os`, `from datetime import datetime`)
2. Third-party (`import cbor2pure as cbor2`, `from cryptography...`)
3. Local (`from vibe.cardano.consensus...`, `from vibe.core...`)

Blank line between each group. Enforced automatically.

## Type Annotations

Required on all public API functions and class methods:

```python
def check_leadership(
    slot: int,
    vrf_sk: bytes,
    pool_vrf_vk: bytes,
    relative_stake: float,
    active_slot_coeff: float,
    epoch_nonce: bytes,
) -> LeadershipProof | None:
```

Internal helpers and test functions don't require annotations.

## Naming

- **Functions/variables:** `snake_case`
- **Classes:** `PascalCase`
- **Constants:** `UPPER_CASE`
- **Private:** prefix with `_` (e.g., `_chain_fragment`, `_combine_nonces`)

## Dataclasses

Use `frozen=True` and `slots=True` by default:

```python
@dataclass(frozen=True, slots=True)
class EpochNonce:
    value: bytes
```

Mutable dataclasses only when mutation is required (e.g., `_PeerConnection` tracking state).

## CBOR

Always use the pure Python binding:

```python
import cbor2pure as cbor2
```

Never `import cbor2` directly — the C bindings have known bugs with indefinite-length encoding and tag handling.

## Logging

Use structured logging with `extra` fields for machine-parseable events:

```python
logger = logging.getLogger(__name__)

logger.info(
    "Forged block #%d at slot %d (%d txs, %d bytes)",
    block_number, slot, tx_count, size,
    extra={
        "event": "forge.block",
        "block_number": block_number,
        "slot": slot,
        "tx_count": tx_count,
        "size_bytes": size,
    },
)
```

## Error Handling

- No bare `except:` — always catch specific exception types
- Use custom exceptions for domain errors
- Log errors with `exc_info=True` for stack traces
- Validation at system boundaries (user input, network, external APIs)
- Trust internal code and framework guarantees

## Haskell References

When implementing from Haskell source, include a reference comment:

```python
def on_block(self, slot: int, prev_hash: bytes, vrf_output: bytes) -> None:
    """Update Praos chain-dependent state for a block.

    Haskell ref: reupdateChainDepState from Praos.hs
    """
```

## Spec References

When implementing from formal specs, include document and section:

```python
# Spec ref: Shelley ledger formal spec, Section 11.1 (Evolving the nonce)
# Spec ref: Ouroboros Praos paper, Section 7 (Nonce evolution)
```
