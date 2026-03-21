"""vibe.cardano.forge -- Block forging for Ouroboros Praos.

This package provides:

* **Leader Schedule Check** -- VRF-based slot leader election. Given a
  pool's VRF secret key and relative stake, determines whether the pool
  is elected to produce a block in a given slot and returns the VRF proof.

* **Block Construction** -- Assembles a valid Cardano block from mempool
  transactions, signs the header with KES, and produces a wire-ready
  CBOR-encoded block.

Spec references:
    - Ouroboros Praos paper, Section 4 (leader election)
    - Shelley formal spec, Section 16.1 (VRF leader check)
    - Shelley formal spec, Figure 10 (block structure)
    - babbage.cddl / conway.cddl (block CDDL schema)

Haskell references:
    - Ouroboros.Consensus.Shelley.Node.Forging (forgeShelleyBlock)
    - Cardano.Ledger.Shelley.BlockChain (constructMetadata, bbody)
    - Cardano.Protocol.TPraos.Rules.Overlay (checkVRFValue)
"""

from .block import Block, ForgedBlock, forge_block
from .leader import LeaderProof, check_leadership

__all__ = [
    "Block",
    "ForgedBlock",
    "LeaderProof",
    "check_leadership",
    "forge_block",
]
