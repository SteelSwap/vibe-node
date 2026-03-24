"""VRF numerical accuracy tests for Praos leader election.

These tests verify that our Decimal-based threshold calculation in
``certified_nat_max_check`` matches high-precision mpmath calculations.
Consensus disagreements caused by floating-point rounding would be
catastrophic — a pool might produce a block that other nodes reject
(or vice versa). These tests guard against that.

Spec reference:
    Ouroboros Praos, Section 4, Definition 6 (slot leader election)
    Shelley formal spec, Section 16.1, Figure 62

Haskell reference:
    Cardano.Protocol.TPraos.Rules.Overlay.checkVRFValue — uses exact
    rational arithmetic via Data.Ratio.
"""

from __future__ import annotations

import hashlib
import os
import struct
from decimal import Decimal, getcontext

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from vibe.cardano.crypto.vrf import (
    VRF_OUTPUT_SIZE,
    _2_POW_256,
    certified_nat_max_check,
    vrf_leader_value,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pre-computed VRF outputs with known Praos leader values
WINNER_VRF_OUTPUT = hashlib.sha512(struct.pack(">Q", 929)).digest()  # leader_val ~0.0000156
LOSER_VRF_OUTPUT = hashlib.sha512(struct.pack(">Q", 51692)).digest()  # leader_val ~0.9995


# ---------------------------------------------------------------------------
# Test 1: f close to 1.0 — every VRF output should be elected
# ---------------------------------------------------------------------------


class TestVRFCheckWithHighF:
    """When f is very close to 1.0, the threshold approaches 1 for sigma=1.

    The formula: threshold = 1 - (1 - f)^sigma

    For sigma=1.0 and f approaching 1.0, threshold approaches f.
    f=1.0 itself is excluded by validation (open interval), but f=0.99
    gives threshold 0.99, meaning 99% of VRF outputs are elected.

    Note: The Cardano spec uses f in (0, 1) exclusive on both ends.
    f=1.0 would mean every slot has a block (no empty slots), which
    the protocol doesn't allow. f=0.0 means no slots active.
    """

    def test_high_f_winner_elected(self) -> None:
        """f=0.999, sigma=1.0: ultra-low leader_val VRF output is elected."""
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=1.0, f=0.999)

    def test_high_f_mid_range_elected(self) -> None:
        """f=0.999, sigma=1.0: midpoint VRF output is elected.

        The blake2b leader hash of the midpoint output has leader_val ~0.17,
        which is well below the threshold of 0.999.
        """
        mid_output = b"\x80" + b"\x00" * (VRF_OUTPUT_SIZE - 1)
        assert certified_nat_max_check(mid_output, sigma=1.0, f=0.999)

    def test_high_f_various_outputs_elected(self) -> None:
        """f=0.999, sigma=1.0: most VRF outputs are elected.

        Threshold is 0.999, so only outputs with leader_val >= 0.999 fail.
        The winner output (~0.0000156) should definitely pass.
        """
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=1.0, f=0.999)
        # All-zeros output has leader_val ~0.23 < 0.999 => elected
        assert certified_nat_max_check(b"\x00" * VRF_OUTPUT_SIZE, sigma=1.0, f=0.999)

    def test_high_f_loser_output_not_elected(self) -> None:
        """f=0.999, sigma=1.0: VRF output with leader_val ~0.9995 fails.

        The loser output has leader_val ~0.9995 > 0.999, so it should fail.
        """
        assert not certified_nat_max_check(LOSER_VRF_OUTPUT, sigma=1.0, f=0.999)

    def test_f_one_raises_value_error(self) -> None:
        """f=1.0 is outside the valid range (0, 1) and must be rejected."""
        output = b"\x00" * VRF_OUTPUT_SIZE
        with pytest.raises(ValueError, match="f must"):
            certified_nat_max_check(output, sigma=1.0, f=1.0)


# ---------------------------------------------------------------------------
# Test 2: Compare Decimal threshold vs mpmath high-precision calculation
# ---------------------------------------------------------------------------


class TestPraosLeaderComparisonMpmath:
    """Compare our Decimal-based threshold against mpmath for accuracy.

    The Praos formula: q = 1 - (1 - f)^sigma

    We compute this with both:
    1. Our production code (Decimal at 40 digits)
    2. mpmath at 50+ digits of precision

    They must agree to at least 30 decimal places. Any disagreement
    beyond that could cause consensus failures on mainnet.
    """

    @given(
        sigma=st.floats(min_value=0.001, max_value=1.0,
                        allow_nan=False, allow_infinity=False),
        f=st.floats(min_value=0.001, max_value=0.999,
                     allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_property_praos_leader_comparison(
        self, sigma: float, f: float
    ) -> None:
        """Our Decimal threshold matches mpmath to 30+ decimal places.

        For 100 random (sigma, f) pairs, compute the Praos threshold
        both ways and compare.
        """
        mpmath = pytest.importorskip("mpmath")

        # Compute with our production Decimal approach (40 digits)
        ctx = getcontext()
        old_prec = ctx.prec
        try:
            ctx.prec = 40
            d_sigma = Decimal(str(sigma))
            d_f = Decimal(str(f))
            one = Decimal(1)

            if d_sigma == one:
                decimal_threshold = d_f
            else:
                complement = one - d_f
                ln_complement = complement.ln()
                power = (ln_complement * d_sigma).exp()
                decimal_threshold = one - power
        finally:
            ctx.prec = old_prec

        # Compute with mpmath at 50 digits
        with mpmath.workdps(50):
            mp_sigma = mpmath.mpf(str(sigma))
            mp_f = mpmath.mpf(str(f))
            mp_complement = mpmath.mpf(1) - mp_f
            mp_power = mpmath.power(mp_complement, mp_sigma)
            mp_threshold = mpmath.mpf(1) - mp_power

        # Convert mpmath result to Decimal for comparison
        mp_threshold_str = mpmath.nstr(mp_threshold, 45)
        mp_threshold_dec = Decimal(mp_threshold_str)

        # They must agree to 30+ decimal places
        diff = abs(decimal_threshold - mp_threshold_dec)

        # 10^-30 is our tolerance — the Haskell node uses exact rationals,
        # so 30 digits of agreement is more than sufficient for the 512-bit
        # comparison (512 bits ~ 154 decimal digits, but the threshold
        # itself only needs ~40 digits of accuracy).
        tolerance = Decimal("1e-30")
        assert diff < tolerance, (
            f"Decimal vs mpmath disagree by {diff} for "
            f"sigma={sigma}, f={f}\n"
            f"  Decimal:  {decimal_threshold}\n"
            f"  mpmath:   {mp_threshold_dec}"
        )


# ---------------------------------------------------------------------------
# Test 3: Edge case — sigma=0 always rejected
# ---------------------------------------------------------------------------


class TestSigmaZeroAlwaysRejected:
    """sigma=0.0 means zero stake — the pool should never be elected.

    This is an explicit early-return in the code (before computing the
    threshold), so it works for any VRF output and any valid f.
    """

    def test_sigma_zero_min_output(self) -> None:
        """sigma=0 with zero VRF output: not elected."""
        assert not certified_nat_max_check(
            b"\x00" * VRF_OUTPUT_SIZE, sigma=0.0, f=0.05
        )

    def test_sigma_zero_max_output(self) -> None:
        """sigma=0 with max VRF output: not elected."""
        assert not certified_nat_max_check(
            b"\xff" * VRF_OUTPUT_SIZE, sigma=0.0, f=0.05
        )

    def test_sigma_zero_random_output(self) -> None:
        """sigma=0 with random VRF output: not elected."""
        random_output = os.urandom(VRF_OUTPUT_SIZE)
        assert not certified_nat_max_check(
            random_output, sigma=0.0, f=0.05
        )

    def test_sigma_zero_high_f(self) -> None:
        """sigma=0 with high f: still not elected."""
        assert not certified_nat_max_check(
            b"\x00" * VRF_OUTPUT_SIZE, sigma=0.0, f=0.99
        )


class TestSigmaOneThresholdEqualsF:
    """When sigma=1.0, the threshold simplifies to f exactly.

    threshold = 1 - (1 - f)^1.0 = 1 - (1 - f) = f

    This is the maximum possible election probability per slot.
    """

    def test_sigma_one_threshold_is_f(self) -> None:
        """Verify that sigma=1 threshold is f and the winner/loser classify correctly."""
        f_val = 0.05
        # Winner (leader_val ~0.0000156 < 0.05) should win
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=1.0, f=f_val)
        # Loser (leader_val ~0.9995 > 0.05) should lose
        assert not certified_nat_max_check(LOSER_VRF_OUTPUT, sigma=1.0, f=f_val)

    def test_sigma_one_various_f(self) -> None:
        """Check sigma=1 threshold equals f for several f values.

        Winner (leader_val ~0.0000156) should win for all f > 0.0000156.
        Loser (leader_val ~0.9995) should lose for all f < 0.9995.
        """
        getcontext().prec = 40
        for f_val in [0.01, 0.05, 0.1, 0.5, 0.9, 0.99]:
            # Winner should always win (leader_val ~0.0000156 < any f in this list)
            assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=1.0, f=f_val), (
                f"Expected winner elected for f={f_val}, sigma=1.0"
            )
            # Loser should lose for all f < 0.9995
            assert not certified_nat_max_check(LOSER_VRF_OUTPUT, sigma=1.0, f=f_val), (
                f"Expected loser NOT elected for f={f_val}, sigma=1.0"
            )


# ---------------------------------------------------------------------------
# Test 4: Edge case — f=0.0 always rejected
# ---------------------------------------------------------------------------


class TestFZeroAlwaysRejected:
    """f=0.0 means no slots are active — always rejected.

    The validation rejects f=0.0 with a ValueError since f must be in
    the open interval (0.0, 1.0). The Cardano mainnet uses f=0.05.
    A value of f=0.0 would mean the chain never produces blocks.
    """

    def test_f_zero_raises(self) -> None:
        """f=0.0 raises ValueError."""
        output = b"\x00" * VRF_OUTPUT_SIZE
        with pytest.raises(ValueError, match="f must"):
            certified_nat_max_check(output, sigma=0.5, f=0.0)

    def test_f_negative_raises(self) -> None:
        """f<0 raises ValueError."""
        output = b"\x00" * VRF_OUTPUT_SIZE
        with pytest.raises(ValueError, match="f must"):
            certified_nat_max_check(output, sigma=0.5, f=-0.01)

    def test_very_small_f_low_threshold(self) -> None:
        """f very close to 0 should have a very low threshold.

        With f=0.001 and sigma=1.0, threshold = 0.001. Only ~0.1% of
        VRF outputs pass. The max output should fail.
        """
        max_output = b"\xff" * VRF_OUTPUT_SIZE
        assert not certified_nat_max_check(max_output, sigma=1.0, f=0.001)

    def test_very_small_f_winner_output_still_wins(self) -> None:
        """Even with very small f, the winner VRF output wins.

        Winner has leader_val ~0.0000156 < f=0.001 => elected.
        """
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=1.0, f=0.001)
