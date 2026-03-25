# vibe-core

Shared infrastructure used by all packages. Protocol-agnostic networking, storage interfaces, and concurrency primitives.

## Architecture

```
vibe.core
├── multiplexer/  # Ouroboros mux — bearer, segments, channels
├── protocols/    # Protocol framework — agency, codec, runner
├── storage/      # Abstract storage interfaces
├── stm.py        # Software Transactional Memory
└── rwlock.py     # Read-write lock
```

These modules are Cardano-agnostic — they implement the Ouroboros networking layer and general-purpose concurrency tools that could be reused for other protocols.
