"""Tests for vibe.cardano.node -- node main loop orchestration.

Tests cover:
- NodeConfig construction and from_dict deserialization
- PoolKeys dataclass
- SlotClock timing (with short slot_length for fast tests)
- PeerManager connect/disconnect/reconnect
- N2N and N2C miniprotocol bundle registration
- Forge loop structure (mock leadership check)
- Graceful shutdown via signal / event
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe.cardano.node.config import NodeConfig, PeerAddress, PoolKeys
from vibe.cardano.node.run import (
    N2C_PROTOCOL_IDS,
    N2N_PROTOCOL_IDS,
    PeerManager,
    SlotClock,
    _setup_n2c_mux,
    _setup_n2n_mux,
)
from vibe.cardano.consensus.slot_arithmetic import SlotConfig
from vibe.core.multiplexer import Bearer, Multiplexer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_slot_config() -> SlotConfig:
    """SlotConfig with 10ms slots for fast testing."""
    return SlotConfig(
        system_start=datetime.now(timezone.utc),
        slot_length=0.01,
        epoch_length=100,
    )


@pytest.fixture
def sample_pool_keys() -> PoolKeys:
    """Minimal PoolKeys for testing."""
    return PoolKeys(
        cold_vk=b"\x01" * 32,
        cold_sk=b"\x02" * 64,
        kes_sk=b"\x03" * 64,
        kes_vk=b"\x04" * 32,
        vrf_sk=b"\x05" * 64,
        vrf_vk=b"\x06" * 32,
        ocert=b"\x07" * 100,
    )


@pytest.fixture
def sample_config(sample_pool_keys: PoolKeys) -> NodeConfig:
    """A NodeConfig for testing."""
    return NodeConfig(
        network_magic=2,  # preview
        slot_length=0.01,
        epoch_length=100,
        security_param=10,
        active_slot_coeff=0.05,
        system_start=datetime.now(timezone.utc),
        host="127.0.0.1",
        port=13001,
        socket_path="/tmp/test-node.sock",
        pool_keys=sample_pool_keys,
        peers=[
            PeerAddress(host="127.0.0.1", port=3001),
            PeerAddress(host="127.0.0.1", port=3002),
        ],
    )


@pytest.fixture
def relay_config() -> NodeConfig:
    """A relay-only NodeConfig (no pool keys)."""
    return NodeConfig(
        network_magic=2,
        host="127.0.0.1",
        port=13002,
        pool_keys=None,
    )


# ---------------------------------------------------------------------------
# NodeConfig tests
# ---------------------------------------------------------------------------


class TestNodeConfig:
    """Tests for NodeConfig and PoolKeys data structures."""

    def test_pool_keys_construction(self, sample_pool_keys: PoolKeys) -> None:
        """PoolKeys stores all key material."""
        assert len(sample_pool_keys.cold_vk) == 32
        assert len(sample_pool_keys.vrf_sk) == 64
        assert sample_pool_keys.cold_sk is not None

    def test_pool_keys_optional_cold_sk(self) -> None:
        """cold_sk defaults to empty bytes (pre-generated OCert case)."""
        keys = PoolKeys(cold_vk=b"\x00" * 32)
        assert keys.cold_sk == b""

    def test_config_is_block_producer(self, sample_config: NodeConfig) -> None:
        """Node with pool_keys is a block producer."""
        assert sample_config.is_block_producer is True

    def test_config_is_relay(self, relay_config: NodeConfig) -> None:
        """Node without pool_keys is a relay."""
        assert relay_config.is_block_producer is False

    def test_config_from_dict(self) -> None:
        """NodeConfig.from_dict handles nested pool_keys and peers."""
        d = {
            "network_magic": 764824073,
            "slot_length": 1.0,
            "epoch_length": 432000,
            "security_param": 2160,
            "active_slot_coeff": 0.05,
            "host": "0.0.0.0",
            "port": 3001,
            "socket_path": "/tmp/node.sock",
            "pool_keys": {
                "cold_vk": b"\x01" * 32,
                "vrf_sk": b"\x02" * 64,
                "vrf_vk": b"\x03" * 32,
            },
            "peers": [
                {"host": "10.0.0.1", "port": 3001},
                {"host": "10.0.0.2", "port": 3001},
            ],
        }
        config = NodeConfig.from_dict(d)
        assert config.network_magic == 764824073
        assert config.is_block_producer is True
        assert len(config.peers) == 2
        assert config.peers[0].host == "10.0.0.1"
        assert config.socket_path == "/tmp/node.sock"

    def test_config_from_dict_relay(self) -> None:
        """from_dict without pool_keys produces a relay config."""
        d = {"network_magic": 2}
        config = NodeConfig.from_dict(d)
        assert config.is_block_producer is False
        assert config.pool_keys is None

    def test_config_from_dict_iso_system_start(self) -> None:
        """from_dict parses ISO format system_start string."""
        d = {
            "network_magic": 2,
            "system_start": "2017-09-23T21:44:51+00:00",
        }
        config = NodeConfig.from_dict(d)
        assert config.system_start.year == 2017

    def test_peer_address_str(self) -> None:
        """PeerAddress.__str__ returns host:port."""
        addr = PeerAddress(host="10.0.0.1", port=3001)
        assert str(addr) == "10.0.0.1:3001"


# ---------------------------------------------------------------------------
# SlotClock tests
# ---------------------------------------------------------------------------


class TestSlotClock:
    """Tests for the SlotClock timing mechanism."""

    def test_current_slot(self, fast_slot_config: SlotConfig) -> None:
        """current_slot returns slot 0 immediately after system_start."""
        clock = SlotClock(fast_slot_config)
        slot = clock.current_slot()
        # With 10ms slots and system_start=now, we should be at slot 0 or 1.
        assert slot >= 0

    @pytest.mark.asyncio
    async def test_wait_for_next_slot(self, fast_slot_config: SlotConfig) -> None:
        """wait_for_next_slot returns the next slot after a short wait."""
        clock = SlotClock(fast_slot_config)
        before = clock.current_slot()
        slot = await clock.wait_for_next_slot()
        assert slot >= before + 1

    @pytest.mark.asyncio
    async def test_wait_for_slot_past(self, fast_slot_config: SlotConfig) -> None:
        """wait_for_slot returns immediately for a past slot."""
        clock = SlotClock(fast_slot_config)
        result = await clock.wait_for_slot(0)
        assert result == 0

    @pytest.mark.asyncio
    async def test_wait_for_slot_fires_at_boundary(
        self, fast_slot_config: SlotConfig
    ) -> None:
        """wait_for_slot with a near-future slot completes quickly."""
        clock = SlotClock(fast_slot_config)
        current = clock.current_slot()
        target = current + 2

        import time
        start = time.monotonic()
        result = await clock.wait_for_slot(target)
        elapsed = time.monotonic() - start

        assert result == target
        # With 10ms slots, waiting 2 slots should take ~20ms.
        # Allow generous tolerance for CI.
        assert elapsed < 0.5

    def test_stop(self, fast_slot_config: SlotConfig) -> None:
        """stop() sets the stopped flag."""
        clock = SlotClock(fast_slot_config)
        assert clock._stopped is False
        clock.stop()
        assert clock._stopped is True

    def test_slot_config_property(self, fast_slot_config: SlotConfig) -> None:
        """slot_config property exposes the underlying config."""
        clock = SlotClock(fast_slot_config)
        assert clock.slot_config is fast_slot_config


# ---------------------------------------------------------------------------
# PeerManager tests
# ---------------------------------------------------------------------------


class TestPeerManager:
    """Tests for PeerManager connection management."""

    def test_add_peer(self, relay_config: NodeConfig) -> None:
        """add_peer registers a peer."""
        pm = PeerManager(relay_config)
        addr = PeerAddress(host="10.0.0.1", port=3001)
        pm.add_peer(addr)
        assert "10.0.0.1:3001" in pm.peer_ids

    def test_add_peer_deduplicate(self, relay_config: NodeConfig) -> None:
        """Adding the same peer twice doesn't create duplicates."""
        pm = PeerManager(relay_config)
        addr = PeerAddress(host="10.0.0.1", port=3001)
        pm.add_peer(addr)
        pm.add_peer(addr)
        assert len(pm.peer_ids) == 1

    def test_initial_connected_count(self, relay_config: NodeConfig) -> None:
        """No peers are connected initially."""
        pm = PeerManager(relay_config)
        pm.add_peer(PeerAddress(host="10.0.0.1", port=3001))
        assert pm.connected_count == 0

    @pytest.mark.asyncio
    async def test_stop_without_start(self, relay_config: NodeConfig) -> None:
        """stop() is safe to call even if start() was never called."""
        pm = PeerManager(relay_config)
        pm.add_peer(PeerAddress(host="10.0.0.1", port=3001))
        await pm.stop()  # Should not raise.


# ---------------------------------------------------------------------------
# Miniprotocol bundle tests
# ---------------------------------------------------------------------------


class TestMiniprotocolBundles:
    """Tests for N2N and N2C miniprotocol registration."""

    def test_n2n_protocol_ids(self) -> None:
        """N2N bundle includes handshake, chain-sync, block-fetch, tx-submission, keep-alive."""
        assert 0 in N2N_PROTOCOL_IDS  # handshake
        assert 2 in N2N_PROTOCOL_IDS  # chain-sync
        assert 3 in N2N_PROTOCOL_IDS  # block-fetch
        assert 4 in N2N_PROTOCOL_IDS  # tx-submission
        assert 8 in N2N_PROTOCOL_IDS  # keep-alive

    def test_n2c_protocol_ids(self) -> None:
        """N2C bundle includes handshake, local-chain-sync, local-tx-submission, local-state-query, local-tx-monitor."""
        assert 0 in N2C_PROTOCOL_IDS  # handshake
        assert 5 in N2C_PROTOCOL_IDS  # local chain-sync
        assert 6 in N2C_PROTOCOL_IDS  # local tx-submission
        assert 7 in N2C_PROTOCOL_IDS  # local state-query
        assert 9 in N2C_PROTOCOL_IDS  # local tx-monitor

    def test_n2n_mux_setup(self) -> None:
        """_setup_n2n_mux registers all N2N protocols on the multiplexer."""
        reader = MagicMock()
        writer = MagicMock()
        bearer = Bearer(reader, writer)
        mux = _setup_n2n_mux(bearer, is_initiator=True)

        # Verify all N2N protocol channels are registered.
        for proto_id in N2N_PROTOCOL_IDS:
            assert proto_id in mux._channels

        assert mux.is_initiator is True

    def test_n2c_mux_setup(self) -> None:
        """_setup_n2c_mux registers all N2C protocols on the multiplexer."""
        reader = MagicMock()
        writer = MagicMock()
        bearer = Bearer(reader, writer)
        mux = _setup_n2c_mux(bearer)

        for proto_id in N2C_PROTOCOL_IDS:
            assert proto_id in mux._channels

        # N2C is always responder-side.
        assert mux.is_initiator is False

    def test_n2n_and_n2c_no_overlap_except_handshake(self) -> None:
        """N2N and N2C protocol ID sets only share the handshake (0)."""
        shared = set(N2N_PROTOCOL_IDS) & set(N2C_PROTOCOL_IDS)
        assert shared == {0}, f"Unexpected shared protocols: {shared}"


# ---------------------------------------------------------------------------
# Forge loop tests
# ---------------------------------------------------------------------------


class TestForgeLoop:
    """Tests for the forge loop structure."""

    def test_forge_loop_skips_relay(self) -> None:
        """Forge loop returns immediately if no pool keys."""
        import threading
        from vibe.cardano.node.forge_loop import forge_loop

        config = NodeConfig(network_magic=2, pool_keys=None)
        slot_config = SlotConfig(
            system_start=datetime.now(timezone.utc),
            slot_length=0.01,
            epoch_length=100,
        )
        shutdown = threading.Event()
        block_received = threading.Event()

        # Should return immediately (no pool keys).
        forge_loop(config, slot_config, shutdown, block_received)

    def test_forge_loop_respects_shutdown(self) -> None:
        """Forge loop exits when shutdown_event is set."""
        import threading
        from vibe.cardano.node.forge_loop import forge_loop

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        cold_sk_obj = Ed25519PrivateKey.generate()
        cold_sk_bytes = cold_sk_obj.private_bytes_raw()
        cold_vk_bytes = cold_sk_obj.public_key().public_bytes_raw()
        keys = PoolKeys(
            cold_vk=cold_vk_bytes,
            cold_sk=cold_sk_bytes,
            vrf_sk=b"\x05" * 64,
            vrf_vk=b"\x06" * 32,
        )
        config = NodeConfig(
            network_magic=2,
            pool_keys=keys,
            slot_length=0.01,
            epoch_length=100,
            system_start=datetime.now(timezone.utc),
        )
        slot_config = SlotConfig(
            system_start=config.system_start,
            slot_length=config.slot_length,
            epoch_length=config.epoch_length,
        )
        shutdown = threading.Event()
        block_received = threading.Event()

        # Set shutdown immediately — forge loop should exit promptly.
        shutdown.set()
        forge_loop(config, slot_config, shutdown, block_received)
        # If we get here, the forge loop exited cleanly.


# ---------------------------------------------------------------------------
# Graceful shutdown tests
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    """Tests for the shutdown mechanism."""

    @pytest.mark.skip(reason="run_node is now sync and registers signal handlers — requires main thread, not testable as unit test")
    def test_run_node_shutdown_via_event(self) -> None:
        """run_node exits cleanly when the shutdown event is triggered.

        run_node is now a sync function that registers signal handlers on the
        main thread and spawns OS threads. Cannot be unit-tested from a pytest
        thread. Tested manually via devnet integration.
        """
        pass
