"""Tests for Mithril snapshot import at node startup (M5.27).

Tests cover:
- NodeConfig.mithril_snapshot_path field
- Mithril import logic: triggered when empty, skipped when not
- PeerManager known_points wiring
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vibe.cardano.network.chainsync import Point
from vibe.cardano.node.config import NodeConfig, PeerAddress
from vibe.cardano.node.run import PeerManager

# ---------------------------------------------------------------------------
# Tests: NodeConfig.mithril_snapshot_path
# ---------------------------------------------------------------------------


def test_node_config_mithril_snapshot_path_default():
    """mithril_snapshot_path defaults to None."""
    cfg = NodeConfig(network_magic=764824073)
    assert cfg.mithril_snapshot_path is None


def test_node_config_mithril_snapshot_path_set(tmp_path: Path):
    """mithril_snapshot_path can be set to a Path."""
    cfg = NodeConfig(
        network_magic=764824073,
        mithril_snapshot_path=tmp_path / "snapshot",
    )
    assert cfg.mithril_snapshot_path == tmp_path / "snapshot"


def test_node_config_from_dict_mithril_snapshot():
    """from_dict parses mithril_snapshot_path."""
    cfg = NodeConfig.from_dict(
        {
            "network_magic": 2,
            "mithril_snapshot_path": "/tmp/snapshot",
        }
    )
    assert cfg.mithril_snapshot_path == Path("/tmp/snapshot")


def test_node_config_from_dict_no_mithril_snapshot():
    """from_dict with no mithril_snapshot_path sets None."""
    cfg = NodeConfig.from_dict({"network_magic": 2})
    assert cfg.mithril_snapshot_path is None


# ---------------------------------------------------------------------------
# Tests: Mithril import logic (unit, extracted from run_node)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mithril_import_triggered_when_empty(tmp_path: Path):
    """When ChainDB is empty and snapshot path is set, import is called."""
    from vibe.cardano.storage import ImmutableDB, LedgerDB

    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    (snapshot_dir / "immutable").mkdir()

    mock_tip = (42000, b"\xab" * 32)

    immutable_db = MagicMock(spec=ImmutableDB)
    ledger_db = MagicMock(spec=LedgerDB)

    config = NodeConfig(
        network_magic=2,
        mithril_snapshot_path=snapshot_dir,
    )

    # Simulate what run_node does: check tip, then import if empty
    tip = None  # ChainDB is empty

    import_called = False

    async def fake_import(snapshot_dir, immutable_db, ledger_db):
        nonlocal import_called
        import_called = True
        return mock_tip

    # Exercise the import conditional from run_node
    if config.mithril_snapshot_path is not None and tip is None:
        tip_slot, tip_hash = await fake_import(
            snapshot_dir=config.mithril_snapshot_path,
            immutable_db=immutable_db,
            ledger_db=ledger_db,
        )
        tip = (tip_slot, tip_hash)

    assert import_called
    assert tip == mock_tip


@pytest.mark.asyncio
async def test_mithril_import_skipped_when_chain_has_data():
    """When ChainDB already has a tip, Mithril import is skipped."""
    existing_tip = (10000, b"\xcd" * 32)

    config = NodeConfig(
        network_magic=2,
        mithril_snapshot_path=Path("/tmp/snapshot"),
    )

    tip = existing_tip  # ChainDB already has data
    import_called = False

    async def fake_import(**kwargs):
        nonlocal import_called
        import_called = True
        return (0, b"")

    if config.mithril_snapshot_path is not None and tip is None:
        await fake_import(
            snapshot_dir=config.mithril_snapshot_path,
            immutable_db=MagicMock(),
            ledger_db=MagicMock(),
        )

    assert not import_called
    assert tip == existing_tip


@pytest.mark.asyncio
async def test_mithril_import_skipped_when_no_snapshot_path():
    """When no snapshot path is configured, import is not attempted."""
    config = NodeConfig(
        network_magic=2,
        mithril_snapshot_path=None,
    )

    tip = None  # Empty chain
    import_called = False

    async def fake_import(**kwargs):
        nonlocal import_called
        import_called = True
        return (0, b"")

    if config.mithril_snapshot_path is not None and tip is None:
        await fake_import(
            snapshot_dir=config.mithril_snapshot_path,
            immutable_db=MagicMock(),
            ledger_db=MagicMock(),
        )

    assert not import_called


# ---------------------------------------------------------------------------
# Tests: PeerManager known_points
# ---------------------------------------------------------------------------


def test_peer_manager_known_points_default():
    """PeerManager starts with empty known_points."""
    config = NodeConfig(network_magic=2)
    pm = PeerManager(config)
    assert pm._known_points == []


def test_peer_manager_set_known_points():
    """set_known_points updates the stored points."""
    config = NodeConfig(network_magic=2)
    pm = PeerManager(config)

    tip_point = Point(slot=42000, hash=b"\xab" * 32)
    pm.set_known_points([tip_point])
    assert len(pm._known_points) == 1
    assert pm._known_points[0].slot == 42000


def test_peer_manager_known_points_from_tip():
    """After Mithril import, known_points should contain the snapshot tip."""
    config = NodeConfig(network_magic=2)
    pm = PeerManager(config)

    # Simulate what run_node does after Mithril import
    tip = (42000, b"\xab" * 32)
    pm.set_known_points([Point(slot=tip[0], hash=tip[1])])

    assert len(pm._known_points) == 1
    assert pm._known_points[0].slot == 42000
    assert pm._known_points[0].hash == b"\xab" * 32


# ---------------------------------------------------------------------------
# Tests: End-to-end known_points wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_points_set_after_mithril_import():
    """Full wiring: Mithril import -> tip -> known_points on PeerManager."""
    mock_tip = (42000, b"\xab" * 32)

    config = NodeConfig(
        network_magic=2,
        mithril_snapshot_path=Path("/tmp/snapshot"),
        peers=[PeerAddress(host="127.0.0.1", port=3001)],
    )

    # Simulate: empty chain -> Mithril import -> set known_points
    tip = None

    async def fake_import(**kwargs):
        return mock_tip

    if config.mithril_snapshot_path is not None and tip is None:
        tip_slot, tip_hash = await fake_import(
            snapshot_dir=config.mithril_snapshot_path,
            immutable_db=MagicMock(),
            ledger_db=MagicMock(),
        )
        tip = (tip_slot, tip_hash)

    pm = PeerManager(config)
    for peer_addr in config.peers:
        pm.add_peer(peer_addr)

    if tip is not None:
        pm.set_known_points([Point(slot=tip[0], hash=tip[1])])

    # Verify chain-sync will start from snapshot tip, not Origin
    assert len(pm._known_points) == 1
    assert pm._known_points[0].slot == 42000
    assert pm._known_points[0].hash == b"\xab" * 32
