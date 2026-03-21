"""Allow running vibe-node via ``python -m vibe.cardano.node``.

Reads configuration from environment variables (same as ``vibe-node serve``).
This is the Docker entrypoint for the devnet container.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from vibe.cardano.node.config import NodeConfig, PeerAddress, PoolKeys


def _read_key_bytes(path: str) -> bytes:
    """Read raw key bytes from a cardano-cli JSON key file."""
    with open(path) as f:
        data = json.load(f)
    cbor_hex = data["cborHex"]
    return bytes.fromhex(cbor_hex[4:])


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("vibe.cardano.node")

    host = os.environ.get("VIBE_HOST", "0.0.0.0")
    port = int(os.environ.get("VIBE_NODE_PORT", "3001"))
    network_magic = int(os.environ.get("VIBE_NETWORK_MAGIC", "764824073"))
    genesis_dir = os.environ.get("VIBE_GENESIS_DIR")
    db_path = os.environ.get("VIBE_DATA_DIR", "./db")
    socket_path = os.environ.get("VIBE_SOCKET_PATH")
    peers_str = os.environ.get("VIBE_PEERS", "")

    # Genesis parameters
    system_start = datetime(2017, 9, 23, 21, 44, 51, tzinfo=timezone.utc)
    slot_length = 1.0
    epoch_length = 432000
    security_param = 2160
    active_slot_coeff = 0.05

    if genesis_dir:
        genesis_path = Path(genesis_dir) / "shelley-genesis.json"
        if genesis_path.exists():
            with open(genesis_path) as f:
                sg = json.load(f)
            system_start = datetime.fromisoformat(sg["systemStart"])
            if system_start.tzinfo is None:
                system_start = system_start.replace(tzinfo=timezone.utc)
            slot_length = sg.get("slotLength", slot_length)
            epoch_length = sg.get("epochLength", epoch_length)
            security_param = sg.get("securityParam", security_param)
            active_slot_coeff = sg.get("activeSlotsCoeff", active_slot_coeff)

    # Parse peers
    peer_list: list[PeerAddress] = []
    for p in peers_str.split(","):
        p = p.strip()
        if not p:
            continue
        if ":" in p:
            h, pt = p.rsplit(":", 1)
            peer_list.append(PeerAddress(host=h, port=int(pt)))
        else:
            peer_list.append(PeerAddress(host=p, port=3001))

    # Pool keys (optional — need VRF sk + cold sk for block production)
    pool_keys: PoolKeys | None = None
    vrf_key = os.environ.get("VIBE_VRF_KEY")
    cold_skey = os.environ.get("VIBE_COLD_SKEY")
    if vrf_key and cold_skey:
        cold_vkey = os.environ.get("VIBE_COLD_VKEY")
        vrf_vkey = os.environ.get("VIBE_VRF_VKEY")
        pool_keys = PoolKeys(
            cold_vk=_read_key_bytes(cold_vkey) if cold_vkey else b"",
            cold_sk=_read_key_bytes(cold_skey),
            vrf_sk=_read_key_bytes(vrf_key),
            vrf_vk=_read_key_bytes(vrf_vkey) if vrf_vkey else b"",
        )

    config = NodeConfig(
        network_magic=network_magic,
        slot_length=slot_length,
        epoch_length=epoch_length,
        security_param=security_param,
        active_slot_coeff=active_slot_coeff,
        system_start=system_start,
        host=host,
        port=port,
        socket_path=socket_path,
        pool_keys=pool_keys,
        peers=peer_list,
        db_path=Path(db_path),
    )

    logger.info(
        "vibe-node starting (magic=%d, %s:%d, peers=%d, producer=%s)",
        config.network_magic, config.host, config.port,
        len(config.peers), config.is_block_producer,
    )

    from vibe.cardano.node.run import run_node
    asyncio.run(run_node(config))


if __name__ == "__main__":
    main()
