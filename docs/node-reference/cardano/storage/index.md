# Storage

Chain storage — the ChainDB architecture with VolatileDB, ImmutableDB, and LedgerDB.

## Architecture

```
ChainDB
├── VolatileDB     — recent blocks (last k), in-memory with on-disk backing
├── ImmutableDB    — finalized blocks, epoch-based Arrow IPC files
├── LedgerDB       — UTxO state, periodic snapshots
├── Chain Fragment — last k blocks of the selected chain (in-memory)
└── Followers      — per-client chain-sync state machines
```

## Modules

### ChainDB

Top-level storage coordinator — chain selection, block addition, tip management, follower registry. Uses STM TVars for cross-thread consistency.

::: vibe.cardano.storage.chaindb
    options:
      show_source: false
      members_order: source

### Chain Follower

Per-client chain-sync state machine — tracks read position, detects fork switches, produces roll-forward/roll-backward instructions.

::: vibe.cardano.storage.chain_follower
    options:
      show_source: false
      members_order: source

### Volatile DB

In-memory block storage for recent (non-finalized) blocks. Keyed by block hash with predecessor index for chain traversal.

::: vibe.cardano.storage.volatile
    options:
      show_source: false
      members_order: source

### Immutable DB

Epoch-based archival storage using Arrow IPC format. Blocks are moved here once they're deeper than k in the chain.

::: vibe.cardano.storage.immutable
    options:
      show_source: false
      members_order: source

### Ledger DB

UTxO state storage with periodic snapshots for crash recovery.

::: vibe.cardano.storage.ledger
    options:
      show_source: false
      members_order: source
