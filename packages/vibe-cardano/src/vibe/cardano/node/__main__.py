"""Allow running vibe-node via ``python -m vibe.cardano.node``.

Reads configuration from environment variables (same as ``vibe-node serve``).
This is the Docker entrypoint for the devnet container.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
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
    permissive = os.environ.get("VIBE_PERMISSIVE_VALIDATION", "").lower() in ("1", "true", "yes")

    # Genesis parameters
    system_start = datetime(2017, 9, 23, 21, 44, 51, tzinfo=UTC)
    slot_length = 1.0
    epoch_length = 432000
    security_param = 2160
    active_slot_coeff = 0.05
    slots_per_kes_period = 129600
    protocol_params = None
    genesis_hash = b""
    initial_pool_stakes: dict[bytes, int] = {}

    if genesis_dir:
        genesis_path = Path(genesis_dir) / "shelley-genesis.json"
        if genesis_path.exists():
            with open(genesis_path) as f:
                sg = json.load(f)
            system_start = datetime.fromisoformat(sg["systemStart"])
            if system_start.tzinfo is None:
                system_start = system_start.replace(tzinfo=UTC)
            slot_length = sg.get("slotLength", slot_length)
            epoch_length = sg.get("epochLength", epoch_length)
            security_param = sg.get("securityParam", security_param)
            active_slot_coeff = sg.get("activeSlotsCoeff", active_slot_coeff)
            slots_per_kes_period = sg.get("slotsPerKESPeriod", 129600)
            protocol_params = sg.get("protocolParams", None)
            genesis_bytes = genesis_path.read_bytes()  # Hash raw file bytes, not re-encoded JSON
            import hashlib

            genesis_hash = hashlib.blake2b(genesis_bytes, digest_size=32).digest()
            # Parse initial stake distribution
            initial_pool_stakes: dict[bytes, int] = {}
            staking = sg.get("staking", {})
            pools_data = staking.get("pools", {})
            stake_delegations = staking.get("stake", {})
            initial_funds = sg.get("initialFunds", {})
            if initial_funds and stake_delegations:
                staker_to_pool: dict[str, bytes] = {}
                for sk_hex, pid_hex in stake_delegations.items():
                    staker_to_pool[sk_hex.lower()] = bytes.fromhex(pid_hex)
                for addr_hex, lovelace in initial_funds.items():
                    if len(addr_hex) >= 114:
                        sc = addr_hex[-56:].lower()
                        pid = staker_to_pool.get(sc)
                        if pid is not None:
                            initial_pool_stakes[pid] = initial_pool_stakes.get(pid, 0) + lovelace
            if not initial_pool_stakes and pools_data:
                for pid_hex, pinfo in pools_data.items():
                    initial_pool_stakes[bytes.fromhex(pid_hex)] = pinfo.get("pledge", 0)

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
        kes_key = os.environ.get("VIBE_KES_KEY")
        opcert_path = os.environ.get("VIBE_OPCERT")
        import cbor2pure as _cbor2

        kes_sk_bytes = b""
        if kes_key:
            raw = _read_key_bytes(kes_key)
            # KES skey is CBOR-wrapped: the cborHex after stripping prefix gives
            # another CBOR layer containing the raw bytes
            try:
                kes_sk_bytes = _cbor2.loads(bytes.fromhex(json.load(open(kes_key))["cborHex"]))
                if not isinstance(kes_sk_bytes, bytes):
                    kes_sk_bytes = raw
            except Exception:
                kes_sk_bytes = raw
        ocert_bytes = b""
        if opcert_path:
            try:
                ocert_bytes = bytes.fromhex(json.load(open(opcert_path))["cborHex"])
            except Exception:
                ocert_bytes = Path(opcert_path).read_bytes()
        pool_keys = PoolKeys(
            cold_vk=_read_key_bytes(cold_vkey) if cold_vkey else b"",
            cold_sk=_read_key_bytes(cold_skey),
            vrf_sk=_read_key_bytes(vrf_key),
            vrf_vk=_read_key_bytes(vrf_vkey) if vrf_vkey else b"",
            kes_sk=kes_sk_bytes,
            ocert=ocert_bytes,
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
        genesis_hash=genesis_hash,
        protocol_params=protocol_params,
        permissive_validation=permissive,
        slots_per_kes_period=slots_per_kes_period,
        initial_pool_stakes=initial_pool_stakes,
    )

    logger.info(
        "vibe-node starting (magic=%d, %s:%d, %d peers, producer=%s)",
        config.network_magic,
        config.host,
        config.port,
        len(config.peers),
        config.is_block_producer,
        extra={
            "event": "node.init",
            "network_magic": config.network_magic,
            "host": config.host,
            "port": config.port,
            "peer_count": len(config.peers),
            "block_producer": config.is_block_producer,
        },
    )

    from vibe.cardano.node.run import run_node

    run_node(config)  # Sync — handles its own asyncio for init, then threads


if __name__ == "__main__":
    main()
