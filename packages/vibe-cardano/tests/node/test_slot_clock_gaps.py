"""Slot clock gap tests -- delay calculation, clock-jump recovery, monotonicity.

Tests the SlotClock class from vibe.cardano.node.run against various
timing scenarios to ensure correct slot boundary calculations and
resilience to clock anomalies.

Haskell ref:
    Ouroboros.Consensus.BlockchainTime.WallClock.Default -- defaultSystemTime
    uses STM threadDelay between slot boundaries with drift correction.

Spec ref:
    Ouroboros Praos paper, Section 4 -- slot timing must be monotonic
    and slot boundaries must align with wall-clock time.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from vibe.cardano.consensus.slot_arithmetic import SlotConfig, slot_to_wall_clock
from vibe.cardano.node.run import SlotClock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def slot_config() -> SlotConfig:
    """A slot config with 1-second slots starting at a known time."""
    return SlotConfig(
        system_start=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        slot_length=1.0,
        epoch_length=100,
    )


@pytest.fixture
def clock(slot_config: SlotConfig) -> SlotClock:
    return SlotClock(slot_config)


# ---------------------------------------------------------------------------
# Test 1: Correct delay calculation for next slot
# ---------------------------------------------------------------------------

class TestDelayCalculation:
    """Verify wait_for_slot computes correct sleep durations."""

    @pytest.mark.asyncio
    async def test_delay_at_slot_start(self, slot_config: SlotConfig) -> None:
        """At exact slot boundary, delay to next slot should be ~1 slot_length."""
        clock = SlotClock(slot_config)
        target_slot = 100

        # Mock time to be exactly at slot 99 boundary
        slot_99_time = slot_to_wall_clock(99, slot_config)

        with patch("vibe.cardano.node.run.datetime") as mock_dt:
            mock_dt.now.return_value = slot_99_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await clock.wait_for_slot(target_slot)

                # Should sleep for exactly 1 second (slot 99 -> slot 100)
                mock_sleep.assert_called_once()
                delay = mock_sleep.call_args[0][0]
                assert abs(delay - 1.0) < 0.001, f"Expected ~1.0s delay, got {delay}"

    @pytest.mark.asyncio
    async def test_delay_mid_slot(self, slot_config: SlotConfig) -> None:
        """Midway through a slot, delay should be fractional."""
        clock = SlotClock(slot_config)
        target_slot = 100

        # Mock time to be 0.3s into slot 99
        slot_99_time = slot_to_wall_clock(99, slot_config)
        mid_time = slot_99_time + timedelta(seconds=0.3)

        with patch("vibe.cardano.node.run.datetime") as mock_dt:
            mock_dt.now.return_value = mid_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await clock.wait_for_slot(target_slot)

                mock_sleep.assert_called_once()
                delay = mock_sleep.call_args[0][0]
                assert abs(delay - 0.7) < 0.001, f"Expected ~0.7s delay, got {delay}"

    @pytest.mark.asyncio
    async def test_delay_past_target_returns_immediately(
        self, slot_config: SlotConfig
    ) -> None:
        """If target slot is in the past, return immediately without sleeping."""
        clock = SlotClock(slot_config)
        target_slot = 50

        # Mock time well past slot 50
        future_time = slot_to_wall_clock(100, slot_config)

        with patch("vibe.cardano.node.run.datetime") as mock_dt:
            mock_dt.now.return_value = future_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await clock.wait_for_slot(target_slot)

                # Should NOT sleep -- target is in the past
                mock_sleep.assert_not_called()
                assert result == target_slot


# ---------------------------------------------------------------------------
# Test 2: Recovery after simulated clock jump forward
# ---------------------------------------------------------------------------

class TestClockJumpRecovery:
    """Verify SlotClock handles time jumps gracefully.

    Haskell ref:
        Ouroboros.Consensus.BlockchainTime.WallClock.Default handles
        clock jumps by recomputing the current slot from wall-clock time
        on each iteration -- it never assumes slots are contiguous.
    """

    @pytest.mark.asyncio
    async def test_clock_jump_forward_skips_slots(
        self, slot_config: SlotConfig
    ) -> None:
        """After a clock jump forward, current_slot reflects the new time."""
        clock = SlotClock(slot_config)

        # First call: at slot 100
        time_at_100 = slot_to_wall_clock(100, slot_config)
        with patch("vibe.cardano.node.run.datetime") as mock_dt:
            mock_dt.now.return_value = time_at_100
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            slot_before = clock.current_slot()

        assert slot_before == 100

        # Simulate clock jump: time is now at slot 200
        time_at_200 = slot_to_wall_clock(200, slot_config)
        with patch("vibe.cardano.node.run.datetime") as mock_dt:
            mock_dt.now.return_value = time_at_200
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            slot_after = clock.current_slot()

        # Should reflect the jumped-to slot, not slot 101
        assert slot_after == 200
        assert slot_after - slot_before == 100


# ---------------------------------------------------------------------------
# Test 3: Monotonically increasing slot numbers under stable clock
# ---------------------------------------------------------------------------

class TestSlotMonotonicity:
    """Verify slots increase monotonically when time advances normally."""

    @pytest.mark.asyncio
    async def test_monotonic_slots_over_sequence(
        self, slot_config: SlotConfig
    ) -> None:
        """Sequential calls with advancing time yield non-decreasing slots."""
        clock = SlotClock(slot_config)

        base_time = slot_to_wall_clock(50, slot_config)
        prev_slot = -1

        for i in range(20):
            t = base_time + timedelta(seconds=i * 0.5)
            with patch("vibe.cardano.node.run.datetime") as mock_dt:
                mock_dt.now.return_value = t
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                current = clock.current_slot()

            assert current >= prev_slot, (
                f"Slot went backwards: {current} < {prev_slot} at offset {i * 0.5}s"
            )
            prev_slot = current

    @pytest.mark.asyncio
    async def test_same_slot_within_slot_boundary(
        self, slot_config: SlotConfig
    ) -> None:
        """Multiple calls within the same slot return the same slot number."""
        clock = SlotClock(slot_config)

        slot_start = slot_to_wall_clock(42, slot_config)

        for offset_ms in [0, 100, 250, 500, 750, 999]:
            t = slot_start + timedelta(milliseconds=offset_ms)
            with patch("vibe.cardano.node.run.datetime") as mock_dt:
                mock_dt.now.return_value = t
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                assert clock.current_slot() == 42, (
                    f"Expected slot 42 at offset {offset_ms}ms"
                )
