"""Node configuration -- network identity, key material, and peer topology.

Captures everything needed to bootstrap a full Cardano node: which network
to connect to, where to listen, what keys to sign with, and who to talk to.

Haskell references:
    - Ouroboros.Consensus.Node (NodeArgs)
    - Ouroboros.Consensus.Config (TopLevelConfig)
    - Cardano.Node.Configuration.Topology (NetworkTopology, NodeAddress)

Spec references:
    - Ouroboros network spec, Chapter 2 -- "Connection Manager"
    - Shelley formal spec, Section 3 -- protocol parameters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PoolKeys:
    """Pool operator key material for block production.

    A relay node does not need pool keys -- it only forwards blocks
    and transactions.  A block-producing node needs all of these to
    sign blocks (KES), prove leadership (VRF), and delegate hot keys
    (operational certificate).

    Haskell ref: ``Ouroboros.Consensus.Shelley.Node.Forging``
        The Haskell forging loop requires ``HotKey`` (KES),
        ``SignKeyVRF``, ``VerKeyVRF``, and ``OCert``.

    Attributes:
        cold_vk: Pool's cold verification key (32 bytes).
        cold_sk: Pool's cold signing key (64 bytes). Only needed for
            OCert generation -- can be None if OCert is pre-generated.
        kes_sk: Current KES secret key (bytes). Evolves each KES period.
        kes_vk: KES verification key (32 bytes).
        vrf_sk: VRF secret key (64 bytes).
        vrf_vk: VRF verification key (32 bytes).
        ocert: Serialised operational certificate (CBOR bytes).
    """

    cold_vk: bytes = b""
    cold_sk: bytes = b""
    kes_sk: bytes = b""
    kes_vk: bytes = b""
    vrf_sk: bytes = b""
    vrf_vk: bytes = b""
    ocert: bytes = b""


@dataclass(frozen=True, slots=True)
class PeerAddress:
    """Address of a peer node for outbound connections.

    Haskell ref: ``Ouroboros.Network.NodeToNode.Types.NodeToNodeAddress``
    """

    host: str
    port: int

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class NodeConfig:
    """Full node configuration.

    Captures the network identity (magic), listening addresses, pool key
    material (if block-producing), genesis parameters, and initial peer
    topology.

    Haskell ref:
        ``Ouroboros.Consensus.Node.NodeArgs`` -- the top-level config
        passed to ``Ouroboros.Consensus.Node.run``.

    Attributes:
        network_magic: Network discriminator (764824073 for mainnet,
            1 for preprod, 2 for preview).
        slot_length: Slot duration in seconds (1.0 for Shelley+).
        epoch_length: Slots per epoch (432000 for Shelley+).
        security_param: The k parameter -- number of blocks for
            finality (2160 on mainnet).
        active_slot_coeff: The f parameter (0.05 on mainnet).
        system_start: UTC datetime of slot 0 (genesis).
        host: Bind address for the N2N TCP listener.
        port: Bind port for the N2N TCP listener.
        socket_path: Unix socket path for N2C clients (e.g. cardano-cli).
            None means no N2C listener.
        pool_keys: Pool operator keys. None means relay-only mode.
        peers: List of outbound peer addresses.
        db_path: Path to the node's data directory (chaindb, ledger, etc.).
    """

    network_magic: int
    slot_length: float = 1.0
    epoch_length: int = 432000
    security_param: int = 2160
    active_slot_coeff: float = 0.05
    system_start: datetime = datetime(2017, 9, 23, 21, 44, 51, tzinfo=timezone.utc)
    host: str = "0.0.0.0"
    port: int = 3001
    socket_path: str | None = None
    pool_keys: PoolKeys | None = None
    peers: list[PeerAddress] = field(default_factory=list)
    db_path: Path = field(default_factory=lambda: Path("./db"))
    genesis_hash: bytes = b""
    protocol_params: dict[str, Any] | None = None
    permissive_validation: bool = False
    slots_per_kes_period: int = 129600

    @property
    def is_block_producer(self) -> bool:
        """True if this node has pool keys and can forge blocks."""
        return self.pool_keys is not None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NodeConfig:
        """Construct a NodeConfig from a plain dict (e.g., loaded from JSON/YAML).

        Supports nested ``pool_keys`` and ``peers`` dicts/lists.

        Args:
            d: Configuration dictionary.

        Returns:
            A NodeConfig instance.
        """
        pool_keys_raw = d.get("pool_keys")
        pool_keys: PoolKeys | None = None
        if pool_keys_raw is not None:
            pool_keys = PoolKeys(**pool_keys_raw)

        peers_raw = d.get("peers", [])
        peers = [
            PeerAddress(host=p["host"], port=p["port"])
            for p in peers_raw
        ]

        system_start = d.get("system_start")
        if isinstance(system_start, str):
            system_start = datetime.fromisoformat(system_start)

        return cls(
            network_magic=d["network_magic"],
            slot_length=d.get("slot_length", 1.0),
            epoch_length=d.get("epoch_length", 432000),
            security_param=d.get("security_param", 2160),
            active_slot_coeff=d.get("active_slot_coeff", 0.05),
            system_start=system_start or cls.system_start,
            host=d.get("host", "0.0.0.0"),
            port=d.get("port", 3001),
            socket_path=d.get("socket_path"),
            pool_keys=pool_keys,
            peers=peers,
            db_path=Path(d.get("db_path", "./db")),
        )
