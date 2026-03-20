"""Ouroboros Praos consensus subsystem — epoch boundary, rewards, nonce evolution.

This package implements the epoch-level consensus rules from the Shelley
ledger formal spec and the Ouroboros Praos paper:

- **epoch_boundary** — epoch transition processing (TICK/NEWEPOCH rules)
- **rewards** — per-epoch reward calculation (Shelley spec Section 5.5.3)
- **nonce** — epoch nonce evolution from VRF outputs

Haskell references:
    * ``Cardano.Ledger.Shelley.Rules.Tick`` (TICK transition)
    * ``Cardano.Ledger.Shelley.Rules.NewEpoch`` (NEWEPOCH transition)
    * ``Cardano.Ledger.Shelley.Rewards`` (reward calculation)
    * ``Cardano.Ledger.Shelley.Rules.PoolReap`` (pool retirement at epoch boundary)
"""
