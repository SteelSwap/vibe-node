# Node Reference

Auto-generated API documentation for the vibe-node codebase. Organized by package and subsystem, mirroring the source tree.

## Packages

### [vibe-cardano](cardano/index.md)

The Cardano protocol implementation. Contains all domain-specific logic: consensus, networking, ledger rules, block production, serialization, storage, and Plutus script evaluation.

| Subsystem | Description |
|-----------|-------------|
| [consensus](cardano/consensus/index.md) | Ouroboros Praos — epoch nonces, slot arithmetic, VRF leader election |
| [crypto](cardano/crypto/index.md) | Cryptographic primitives — VRF, KES, operational certificates |
| [forge](cardano/forge/index.md) | Block production — leadership check, block assembly |
| [ledger](cardano/ledger/index.md) | Ledger rules — delegation, stake distribution, UTxO |
| [mempool](cardano/mempool/index.md) | Transaction mempool — validation, eviction, capacity |
| [network](cardano/network/index.md) | Ouroboros miniprotocols — chain-sync, block-fetch, tx-submission, handshake |
| [node](cardano/node/index.md) | Node orchestration — forge loop, peer manager, kernel, threading |
| [plutus](cardano/plutus/index.md) | Plutus script evaluation — cost models, data types |
| [serialization](cardano/serialization/index.md) | CBOR encoding/decoding — blocks, headers, transactions (all eras) |
| [storage](cardano/storage/index.md) | Chain storage — ChainDB, VolatileDB, ImmutableDB, chain follower |
| [sync](cardano/sync/index.md) | Chain synchronization — Mithril snapshot import |

### [vibe-core](core/index.md)

Shared infrastructure used by all packages. Protocol-agnostic networking, storage interfaces, and concurrency primitives.

| Module | Description |
|--------|-------------|
| [multiplexer](core/multiplexer.md) | Ouroboros multiplexer — bearer, segment framing, channel management |
| [protocols](core/protocols.md) | Protocol framework — agency, codec, runner, pipelining |
| [storage](core/storage.md) | Storage interfaces — abstract base classes for DB backends |
| [stm](core/stm.md) | Software Transactional Memory — TVar, atomically, RetryTransaction |
| [rwlock](core/rwlock.md) | Read-write lock — write-preferring RWLock with context managers |
