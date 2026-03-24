"""Tests for vibe.cardano.consensus.slot_arithmetic.

Covers:
- Slot/epoch conversions with Byron and Shelley configs
- Wall-clock time conversions
- KES period calculations
- Boundary conditions (epoch 0, slot 0, epoch boundaries)
- Round-trip properties (Hypothesis)
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.consensus.slot_arithmetic import (
    BYRON_CONFIG,
    BYRON_EPOCH_LENGTH,
    BYRON_SLOT_LENGTH,
    MAINNET_SLOTS_PER_KES_PERIOD,
    MAINNET_SYSTEM_START,
    SHELLEY_CONFIG,
    SHELLEY_EPOCH_LENGTH,
    SHELLEY_SLOT_LENGTH,
    SlotConfig,
    epoch_to_first_slot,
    slot_to_epoch,
    slot_to_kes_period,
    slot_to_wall_clock,
    wall_clock_to_slot,
)

# ---------------------------------------------------------------------------
# SlotConfig validation
# ---------------------------------------------------------------------------


class TestSlotConfig:
    def test_valid_config(self) -> None:
        config = SlotConfig(
            system_start=MAINNET_SYSTEM_START,
            slot_length=1.0,
            epoch_length=432000,
        )
        assert config.slot_length == 1.0
        assert config.epoch_length == 432000

    def test_invalid_slot_length(self) -> None:
        with pytest.raises(ValueError, match="slot_length must be positive"):
            SlotConfig(
                system_start=MAINNET_SYSTEM_START,
                slot_length=0.0,
                epoch_length=432000,
            )

    def test_negative_slot_length(self) -> None:
        with pytest.raises(ValueError, match="slot_length must be positive"):
            SlotConfig(
                system_start=MAINNET_SYSTEM_START,
                slot_length=-1.0,
                epoch_length=432000,
            )

    def test_invalid_epoch_length(self) -> None:
        with pytest.raises(ValueError, match="epoch_length must be positive"):
            SlotConfig(
                system_start=MAINNET_SYSTEM_START,
                slot_length=1.0,
                epoch_length=0,
            )

    def test_byron_config_constants(self) -> None:
        assert BYRON_CONFIG.slot_length == 20.0
        assert BYRON_CONFIG.epoch_length == 21600

    def test_shelley_config_constants(self) -> None:
        assert SHELLEY_CONFIG.slot_length == 1.0
        assert SHELLEY_CONFIG.epoch_length == 432000


# ---------------------------------------------------------------------------
# Slot <-> Epoch conversions
# ---------------------------------------------------------------------------


class TestSlotToEpoch:
    def test_slot_zero_is_epoch_zero(self) -> None:
        assert slot_to_epoch(0, SHELLEY_CONFIG) == 0

    def test_first_slot_of_epoch_1_shelley(self) -> None:
        assert slot_to_epoch(432000, SHELLEY_CONFIG) == 1

    def test_last_slot_of_epoch_0_shelley(self) -> None:
        assert slot_to_epoch(431999, SHELLEY_CONFIG) == 0

    def test_shelley_epoch_2(self) -> None:
        assert slot_to_epoch(864000, SHELLEY_CONFIG) == 2

    def test_byron_slot_zero(self) -> None:
        assert slot_to_epoch(0, BYRON_CONFIG) == 0

    def test_byron_epoch_1(self) -> None:
        assert slot_to_epoch(21600, BYRON_CONFIG) == 1

    def test_byron_last_slot_epoch_0(self) -> None:
        assert slot_to_epoch(21599, BYRON_CONFIG) == 0

    def test_negative_slot_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            slot_to_epoch(-1, SHELLEY_CONFIG)


class TestEpochToFirstSlot:
    def test_epoch_zero(self) -> None:
        assert epoch_to_first_slot(0, SHELLEY_CONFIG) == 0

    def test_epoch_one_shelley(self) -> None:
        assert epoch_to_first_slot(1, SHELLEY_CONFIG) == 432000

    def test_epoch_two_shelley(self) -> None:
        assert epoch_to_first_slot(2, SHELLEY_CONFIG) == 864000

    def test_epoch_one_byron(self) -> None:
        assert epoch_to_first_slot(1, BYRON_CONFIG) == 21600

    def test_negative_epoch_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            epoch_to_first_slot(-1, SHELLEY_CONFIG)


class TestSlotEpochRoundTrip:
    """The first slot of epoch E should map back to epoch E."""

    @given(epoch=st.integers(min_value=0, max_value=10000))
    @settings(max_examples=200)
    def test_shelley_round_trip(self, epoch: int) -> None:
        first_slot = epoch_to_first_slot(epoch, SHELLEY_CONFIG)
        assert slot_to_epoch(first_slot, SHELLEY_CONFIG) == epoch

    @given(epoch=st.integers(min_value=0, max_value=10000))
    @settings(max_examples=200)
    def test_byron_round_trip(self, epoch: int) -> None:
        first_slot = epoch_to_first_slot(epoch, BYRON_CONFIG)
        assert slot_to_epoch(first_slot, BYRON_CONFIG) == epoch


# ---------------------------------------------------------------------------
# Slot <-> Wall-clock conversions
# ---------------------------------------------------------------------------


class TestSlotToWallClock:
    def test_slot_zero_is_system_start(self) -> None:
        assert slot_to_wall_clock(0, SHELLEY_CONFIG) == MAINNET_SYSTEM_START

    def test_slot_one_shelley(self) -> None:
        expected = MAINNET_SYSTEM_START + timedelta(seconds=1)
        assert slot_to_wall_clock(1, SHELLEY_CONFIG) == expected

    def test_slot_one_byron(self) -> None:
        expected = MAINNET_SYSTEM_START + timedelta(seconds=20)
        assert slot_to_wall_clock(1, BYRON_CONFIG) == expected

    def test_large_slot_shelley(self) -> None:
        slot = 432000  # 5 days worth
        expected = MAINNET_SYSTEM_START + timedelta(seconds=432000)
        assert slot_to_wall_clock(slot, SHELLEY_CONFIG) == expected

    def test_negative_slot_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            slot_to_wall_clock(-1, SHELLEY_CONFIG)


class TestWallClockToSlot:
    def test_system_start_is_slot_zero(self) -> None:
        assert wall_clock_to_slot(MAINNET_SYSTEM_START, SHELLEY_CONFIG) == 0

    def test_one_second_after_start_shelley(self) -> None:
        t = MAINNET_SYSTEM_START + timedelta(seconds=1)
        assert wall_clock_to_slot(t, SHELLEY_CONFIG) == 1

    def test_twenty_seconds_after_start_byron(self) -> None:
        t = MAINNET_SYSTEM_START + timedelta(seconds=20)
        assert wall_clock_to_slot(t, BYRON_CONFIG) == 1

    def test_mid_slot_truncates_down(self) -> None:
        """A time in the middle of a slot maps to that slot's start."""
        t = MAINNET_SYSTEM_START + timedelta(seconds=1.5)
        assert wall_clock_to_slot(t, SHELLEY_CONFIG) == 1

    def test_before_system_start_clamps_to_zero(self) -> None:
        t = MAINNET_SYSTEM_START - timedelta(hours=1)
        assert wall_clock_to_slot(t, SHELLEY_CONFIG) == 0


class TestWallClockRoundTrip:
    """slot_to_wall_clock(wall_clock_to_slot(t)) <= t (floor semantics)."""

    @given(slot=st.integers(min_value=0, max_value=100_000_000))
    @settings(max_examples=200)
    def test_shelley_slot_round_trip(self, slot: int) -> None:
        """Converting slot -> time -> slot should be identity."""
        time = slot_to_wall_clock(slot, SHELLEY_CONFIG)
        assert wall_clock_to_slot(time, SHELLEY_CONFIG) == slot

    @given(slot=st.integers(min_value=0, max_value=100_000_000))
    @settings(max_examples=200)
    def test_byron_slot_round_trip(self, slot: int) -> None:
        time = slot_to_wall_clock(slot, BYRON_CONFIG)
        assert wall_clock_to_slot(time, BYRON_CONFIG) == slot


# ---------------------------------------------------------------------------
# Slot -> KES period
# ---------------------------------------------------------------------------


class TestSlotToKesPeriod:
    def test_slot_zero(self) -> None:
        assert slot_to_kes_period(0) == 0

    def test_just_before_first_period(self) -> None:
        assert slot_to_kes_period(MAINNET_SLOTS_PER_KES_PERIOD - 1) == 0

    def test_first_period_boundary(self) -> None:
        assert slot_to_kes_period(MAINNET_SLOTS_PER_KES_PERIOD) == 1

    def test_custom_period_length(self) -> None:
        assert slot_to_kes_period(100, slots_per_kes_period=50) == 2

    def test_negative_slot_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            slot_to_kes_period(-1)

    def test_zero_period_length_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            slot_to_kes_period(100, slots_per_kes_period=0)


# ---------------------------------------------------------------------------
# Monotonicity property (Hypothesis)
# ---------------------------------------------------------------------------


class TestMonotonicity:
    """Slot arithmetic should be monotonically non-decreasing."""

    @given(
        a=st.integers(min_value=0, max_value=100_000_000),
        b=st.integers(min_value=0, max_value=100_000_000),
    )
    @settings(max_examples=200)
    def test_slot_to_epoch_monotonic(self, a: int, b: int) -> None:
        if a <= b:
            assert slot_to_epoch(a, SHELLEY_CONFIG) <= slot_to_epoch(b, SHELLEY_CONFIG)

    @given(
        a=st.integers(min_value=0, max_value=100_000_000),
        b=st.integers(min_value=0, max_value=100_000_000),
    )
    @settings(max_examples=200)
    def test_slot_to_wall_clock_monotonic(self, a: int, b: int) -> None:
        if a <= b:
            assert slot_to_wall_clock(a, SHELLEY_CONFIG) <= slot_to_wall_clock(b, SHELLEY_CONFIG)

    @given(
        a=st.integers(min_value=0, max_value=100_000_000),
        b=st.integers(min_value=0, max_value=100_000_000),
    )
    @settings(max_examples=200)
    def test_slot_to_kes_period_monotonic(self, a: int, b: int) -> None:
        if a <= b:
            assert slot_to_kes_period(a) <= slot_to_kes_period(b)


# ---------------------------------------------------------------------------
# Era-specific 5-day epoch invariant
# ---------------------------------------------------------------------------


class TestEpochDuration:
    """Both Byron and Shelley epochs are 5 days in wall-clock time."""

    def test_byron_epoch_is_five_days(self) -> None:
        epoch_seconds = BYRON_EPOCH_LENGTH * BYRON_SLOT_LENGTH
        assert epoch_seconds == 432000  # 5 * 24 * 60 * 60

    def test_shelley_epoch_is_five_days(self) -> None:
        epoch_seconds = SHELLEY_EPOCH_LENGTH * SHELLEY_SLOT_LENGTH
        assert epoch_seconds == 432000  # 5 * 24 * 60 * 60
