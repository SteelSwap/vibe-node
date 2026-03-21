"""vibe.cardano.node -- Top-level node orchestration for the vibe Cardano node.

This package provides:

* **NodeConfig** -- Configuration for the full node (network, keys, peers, genesis)
* **PoolKeys** -- Pool operator key material (cold, KES, VRF, operational cert)
* **run_node** -- The top-level async entry point that ties everything together
* **SlotClock** -- Asyncio loop that fires at each slot boundary
* **PeerManager** -- Manages outbound peer connections with reconnect backoff

Haskell references:
    - Ouroboros.Consensus.Node (run)
    - Ouroboros.Consensus.Node.Run (RunNode)
    - Ouroboros.Consensus.BlockchainTime.WallClock.Default (defaultSystemTime)
    - Ouroboros.Network.Diffusion (run)
"""

from .config import NodeConfig, PeerAddress, PoolKeys
from .kernel import StakeDistribution
from .run import PeerManager, SlotClock, run_node

__all__ = [
    "NodeConfig",
    "PeerAddress",
    "PeerManager",
    "PoolKeys",
    "SlotClock",
    "StakeDistribution",
    "run_node",
]
