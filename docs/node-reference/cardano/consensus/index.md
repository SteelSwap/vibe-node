# Consensus

Ouroboros Praos consensus primitives — epoch nonce evolution, slot arithmetic, and the Hard Fork Combinator validation layer.

## Modules

### Nonce Evolution

Epoch nonces are the source of per-slot leader-election randomness. Each epoch's nonce derives from the previous epoch's nonce combined with VRF outputs from the stability window (first 2/3 of the epoch).

::: vibe.cardano.consensus.nonce
    options:
      show_source: false
      members_order: source

### Slot Arithmetic

Wall-clock to slot conversion, epoch boundary detection, and slot timing for the forge loop.

::: vibe.cardano.consensus.slot_arithmetic
    options:
      show_source: false
      members_order: source

### Hard Fork Combinator

Multi-era block validation dispatching — routes validation to the correct era handler.

::: vibe.cardano.consensus.hfc
    options:
      show_source: false
      members_order: source
