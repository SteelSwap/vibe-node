# vibe-cardano

The Cardano protocol implementation package. All domain-specific logic lives here — from CBOR wire encoding to Ouroboros Praos consensus to Plutus script evaluation.

## Architecture

```
vibe.cardano
├── consensus/     # Praos consensus — nonces, slots, leader election
├── crypto/        # VRF, KES, operational certificates
├── forge/         # Block production — leadership + assembly
├── ledger/        # Delegation, stake distribution, UTxO
├── mempool/       # Transaction pool — validate, evict, serve
├── network/       # Ouroboros miniprotocols (N2N + N2C)
├── node/          # Node orchestration — 3-thread model + STM
├── plutus/        # Script evaluation and cost models
├── serialization/ # CBOR encode/decode for all eras
├── storage/       # ChainDB, VolatileDB, ImmutableDB
└── sync/          # Mithril snapshot import
```

## Data Flow

Blocks arrive via **network** (chain-sync headers, block-fetch bodies), get decoded by **serialization**, validated by **ledger** + **plutus**, stored in **storage** (ChainDB), and trigger **consensus** state updates (nonce evolution, stake snapshots). The **forge** subsystem produces new blocks when the node is elected leader via VRF. The **node** package orchestrates all of this across 3 OS threads with **STM** for shared state consistency.
