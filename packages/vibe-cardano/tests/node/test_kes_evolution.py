"""Tests for KES key evolution in the forge loop.

Validates that:
- KES period is correctly computed from slot number
- KES key evolves when the period boundary is crossed
- KES expiry is detected and reported

Spec ref: Shelley formal spec, OCERT rule --
    t = kesPeriod(slot) - c_0   (relative KES period)
Haskell ref: Ouroboros.Consensus.Shelley.Node.Forging -- HotKey evolution
"""

from __future__ import annotations

import pytest

from vibe.cardano.crypto.kes import (
    CARDANO_KES_DEPTH,
    KesSecretKey,
    kes_derive_vk,
    kes_keygen,
    kes_sign,
    kes_update,
    kes_verify,
)
from vibe.cardano.crypto.ocert import slot_to_kes_period


# ---------------------------------------------------------------------------
# test_kes_period_computed_from_slot
# ---------------------------------------------------------------------------


class TestKesPeriodFromSlot:
    """Verify slot_to_kes_period matches integer division semantics."""

    def test_period_zero_at_slot_zero(self) -> None:
        assert slot_to_kes_period(0, slots_per_kes_period=129600) == 0

    def test_period_zero_just_before_boundary(self) -> None:
        assert slot_to_kes_period(129599, slots_per_kes_period=129600) == 0

    def test_period_one_at_boundary(self) -> None:
        assert slot_to_kes_period(129600, slots_per_kes_period=129600) == 1

    def test_period_with_small_slots_per_period(self) -> None:
        """Devnets use small slotsPerKESPeriod (e.g. 100)."""
        assert slot_to_kes_period(0, slots_per_kes_period=100) == 0
        assert slot_to_kes_period(99, slots_per_kes_period=100) == 0
        assert slot_to_kes_period(100, slots_per_kes_period=100) == 1
        assert slot_to_kes_period(250, slots_per_kes_period=100) == 2

    def test_large_slot_number(self) -> None:
        # Mainnet: slot 12_960_000 = period 100
        assert slot_to_kes_period(12_960_000, slots_per_kes_period=129600) == 100


# ---------------------------------------------------------------------------
# test_kes_evolves_on_period_boundary
# ---------------------------------------------------------------------------


class TestKesEvolvesOnPeriodBoundary:
    """Verify KES key evolution produces valid signatures at each period."""

    @pytest.fixture
    def kes_key(self) -> KesSecretKey:
        """Generate a small KES key (depth 2 = 4 periods) for fast tests."""
        return kes_keygen(2)

    def test_sign_at_period_zero(self, kes_key: KesSecretKey) -> None:
        vk = kes_derive_vk(kes_key)
        msg = b"block header body at period 0"
        sig = kes_sign(kes_key, 0, msg)
        assert kes_verify(vk, 2, 0, sig, msg)

    def test_evolve_and_sign_period_one(self, kes_key: KesSecretKey) -> None:
        vk = kes_derive_vk(kes_key)
        evolved = kes_update(kes_key, 0)
        assert evolved is not None

        msg = b"block header body at period 1"
        sig = kes_sign(evolved, 1, msg)
        assert kes_verify(vk, 2, 1, sig, msg)

    def test_evolve_through_all_periods(self, kes_key: KesSecretKey) -> None:
        """Walk through all 4 periods of a depth-2 key."""
        vk = kes_derive_vk(kes_key)
        sk = kes_key

        for period in range(4):
            msg = f"block at period {period}".encode()
            sig = kes_sign(sk, period, msg)
            assert kes_verify(vk, 2, period, sig, msg), (
                f"Signature invalid at period {period}"
            )
            if period < 3:
                evolved = kes_update(sk, period)
                assert evolved is not None
                sk = evolved

    def test_forge_loop_evolution_pattern(self) -> None:
        """Simulate the forge loop's evolution logic.

        Mimics the pattern in run.py: compute kes_period_offset from
        ocert.kes_period_start, evolve key, then sign.
        """
        depth = 2  # 4 periods
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        kes_period_start = 5  # ocert starts at KES period 5

        # Simulate starting at slot corresponding to KES period 7
        # so kes_period_offset = 7 - 5 = 2
        kes_period_offset = 2

        for p in range(kes_period_offset):
            evolved = kes_update(sk, p)
            assert evolved is not None
            sk = evolved

        # Now sign at the offset period
        msg = b"block header at offset period 2"
        sig = kes_sign(sk, kes_period_offset, msg)
        assert kes_verify(vk, depth, kes_period_offset, sig, msg)


# ---------------------------------------------------------------------------
# test_kes_expiry_detected
# ---------------------------------------------------------------------------


class TestKesExpiryDetected:
    """Verify that kes_update returns None when all periods are exhausted."""

    def test_expiry_at_max_period(self) -> None:
        """Depth 1 = 2 periods. After period 1, key is exhausted."""
        sk = kes_keygen(1)

        # Evolve period 0 -> 1
        evolved = kes_update(sk, 0)
        assert evolved is not None

        # Try to evolve past the end
        expired = kes_update(evolved, 1)
        assert expired is None, "Expected None for exhausted KES key"

    def test_expiry_depth_two(self) -> None:
        """Depth 2 = 4 periods. Key should expire after period 3."""
        sk = kes_keygen(2)
        for p in range(3):
            sk = kes_update(sk, p)
            assert sk is not None

        # Period 3 is the last valid period; evolving past it returns None
        expired = kes_update(sk, 3)
        assert expired is None

    def test_forge_loop_detects_expiry(self) -> None:
        """Simulate the forge loop's expiry detection path."""
        depth = 1  # 2 periods only
        sk = kes_keygen(depth)

        # Try to evolve to period 3 (beyond max of 2)
        # The forge loop iterates range(target_period)
        target = 3
        expired_at = None
        for p in range(target):
            evolved = kes_update(sk, p)
            if evolved is None:
                expired_at = p
                break
            sk = evolved

        assert expired_at is not None, "Should have detected expiry"
        assert expired_at == 1, "Should expire when trying to evolve past period 1"
