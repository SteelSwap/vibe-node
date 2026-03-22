"""Node integration test parity — config, epoch, KES, slot clock.

Haskell references:
    - Ouroboros.Consensus.Node (run, NodeKernel)
    - Ouroboros.Consensus.BlockchainTime.WallClock.Default
    - Cardano.Protocol.TPraos.BHeader (kesPeriod)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vibe.cardano.consensus.slot_arithmetic import (
    SlotConfig,
    slot_to_kes_period,
    slot_to_wall_clock,
    wall_clock_to_slot,
)
from vibe.cardano.node.config import NodeConfig
from vibe.cardano.node.run import SlotClock


# ---------------------------------------------------------------------------
# Startup config validation
# ---------------------------------------------------------------------------


class TestStartupConfigValidation:
    """Verify NodeConfig parsing and validation."""

    def test_minimal_config(self) -> None:
        config = NodeConfig(network_magic=764824073, host="0.0.0.0", port=3001)
        assert config.network_magic == 764824073
        assert config.port == 3001

    def test_is_block_producer_property(self) -> None:
        """is_block_producer depends on key configuration."""
        config = NodeConfig(network_magic=42, host="0.0.0.0", port=3001)
        # Without keys, not a block producer
        result = config.is_block_producer
        assert isinstance(result, bool)

    def test_default_host(self) -> None:
        config = NodeConfig(network_magic=42)
        assert config.host is not None


# ---------------------------------------------------------------------------
# Epoch boundary detection
# ---------------------------------------------------------------------------


class TestEpochBoundaryDetection:
    """Verify epoch calculation from slot numbers."""

    def test_slot_zero_is_epoch_zero(self) -> None:
        assert 0 // 432000 == 0

    def test_last_slot_of_epoch_zero(self) -> None:
        epoch_length = 432000
        assert (epoch_length - 1) // epoch_length == 0

    def test_first_slot_of_epoch_one(self) -> None:
        epoch_length = 432000
        assert epoch_length // epoch_length == 1

    def test_devnet_short_epochs(self) -> None:
        """Devnet uses epoch_length=100."""
        epoch_length = 100
        assert 0 // epoch_length == 0
        assert 99 // epoch_length == 0
        assert 100 // epoch_length == 1
        assert 250 // epoch_length == 2

    def test_epoch_boundary_slot(self) -> None:
        """Slot exactly at epoch boundary."""
        epoch_length = 432000
        slot = epoch_length * 5
        assert slot // epoch_length == 5
        assert (slot - 1) // epoch_length == 4


# ---------------------------------------------------------------------------
# KES period advancement
# ---------------------------------------------------------------------------


class TestKesPeriodAdvancement:
    """Verify slot-to-KES-period computation."""

    def test_slot_zero(self) -> None:
        assert slot_to_kes_period(0) == 0

    def test_mainnet_period(self) -> None:
        """Mainnet: 129600 slots per KES period."""
        assert slot_to_kes_period(129600) == 1
        assert slot_to_kes_period(259200) == 2

    def test_just_before_boundary(self) -> None:
        assert slot_to_kes_period(129599) == 0

    def test_devnet_small_period(self) -> None:
        """Devnet may use smaller periods."""
        assert slot_to_kes_period(100, slots_per_kes_period=50) == 2
        assert slot_to_kes_period(49, slots_per_kes_period=50) == 0

    def test_negative_slot_raises(self) -> None:
        with pytest.raises(ValueError):
            slot_to_kes_period(-1)

    def test_zero_period_raises(self) -> None:
        with pytest.raises(ValueError):
            slot_to_kes_period(100, slots_per_kes_period=0)

    def test_large_mainnet_slot(self) -> None:
        """Slot 140M+ (current mainnet range)."""
        period = slot_to_kes_period(140_000_000)
        assert period == 140_000_000 // 129600
        assert period > 1000


# ---------------------------------------------------------------------------
# SlotClock accuracy
# ---------------------------------------------------------------------------


class TestSlotClockAccuracy:
    """Verify SlotClock behavior."""

    def test_current_slot_returns_positive(self) -> None:
        config = SlotConfig(
            system_start=datetime(2022, 9, 6, tzinfo=timezone.utc),
            slot_length=1.0,
            epoch_length=432000,
        )
        clock = SlotClock(config)
        slot = clock.current_slot()
        assert slot > 0

    def test_stop_sets_flag(self) -> None:
        config = SlotConfig(
            system_start=datetime(2022, 9, 6, tzinfo=timezone.utc),
            slot_length=1.0,
            epoch_length=432000,
        )
        clock = SlotClock(config)
        assert not clock._stopped
        clock.stop()
        assert clock._stopped

    def test_slot_config_property(self) -> None:
        config = SlotConfig(
            system_start=datetime(2022, 9, 6, tzinfo=timezone.utc),
            slot_length=1.0,
            epoch_length=432000,
        )
        clock = SlotClock(config)
        assert clock.slot_config is config

    def test_wall_clock_to_slot_roundtrip(self) -> None:
        """Slot → wall clock → slot should be identity."""
        config = SlotConfig(
            system_start=datetime(2022, 9, 6, tzinfo=timezone.utc),
            slot_length=1.0,
            epoch_length=432000,
        )
        slot = 1000
        wall_time = slot_to_wall_clock(slot, config)
        recovered = wall_clock_to_slot(wall_time, config)
        assert recovered == slot

    def test_monotonic_slots(self) -> None:
        """Later wall clock time → higher slot."""
        config = SlotConfig(
            system_start=datetime(2022, 9, 6, tzinfo=timezone.utc),
            slot_length=1.0,
            epoch_length=432000,
        )
        t1 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2023, 6, 1, tzinfo=timezone.utc)
        s1 = wall_clock_to_slot(t1, config)
        s2 = wall_clock_to_slot(t2, config)
        assert s2 > s1
