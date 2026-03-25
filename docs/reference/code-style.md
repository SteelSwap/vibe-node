# Code Style Guide

Enforced by **ruff** (lint, isort, format, docstrings). Configuration in `pyproject.toml`.

## Formatting

- **Line length:** 99 characters
- **Formatter:** ruff format (black-compatible)
- **Docstrings:** Google style (enforced by ruff pydocstyle `D` rules)
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

## Docstrings

Follow **Google style** (enforced by ruff `D` rules with `convention = "google"`):

```python
def evolve_nonce(
    prev_nonce: EpochNonce,
    eta_v: bytes,
    extra_entropy: bytes | None = None,
) -> EpochNonce:
    """Evolve the epoch nonce at an epoch boundary.

    At the transition from epoch N to epoch N+1, combines the previous
    nonce with accumulated VRF outputs.

    Args:
        prev_nonce: The nonce from the previous epoch.
        eta_v: The accumulated VRF hash from the stability window.
        extra_entropy: Optional extra entropy from protocol param updates.

    Returns:
        The new epoch nonce for the next epoch.

    Raises:
        ValueError: If nonce bytes are not 32 bytes.
    """
```

Key rules:
- First line is a one-sentence summary ending with a period
- Blank line between summary and body (if multi-line)
- Use `Args:`, `Returns:`, `Raises:` sections (Google convention)
- Section names must end with a colon
- First word of summary is capitalized

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
