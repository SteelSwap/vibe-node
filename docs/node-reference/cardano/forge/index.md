# Forge

Block production — VRF leadership check and block assembly.

## Modules

### Leader Election

Checks whether the node is elected slot leader using the VRF and relative stake.

::: vibe.cardano.forge.leader
    options:
      show_source: false
      members_order: source

### Block Assembly

Assembles a complete block from a leadership proof, mempool transactions, and cryptographic credentials.

::: vibe.cardano.forge.block
    options:
      show_source: false
      members_order: source
