"""Tests for vibe.cardano.crypto.vrf — VRF leader election and bindings.

Tests cover:
1. The pure Python leader check math (certified_nat_max_check)
2. VRF constants
3. Input validation
4. Property-based tests via Hypothesis (leader probability monotonic in stake)
5. Native VRF verification (only when IOG libsodium fork is available)

Key insight: sigma=1.0 does NOT mean "always elected." The Praos formula is:
    elected iff vrf_nat / 2^512 < 1 - (1 - f)^sigma
For sigma=1.0, the threshold is f (e.g., 5% on mainnet). The pool is elected
with probability f per slot, which is the maximum possible probability.
"""

from __future__ import annotations

from decimal import Decimal, getcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.crypto.vrf import (
    HAS_VRF_NATIVE,
    VRF_OUTPUT_SIZE,
    VRF_PK_SIZE,
    VRF_PROOF_SIZE,
    VRF_SK_SIZE,
    certified_nat_max_check,
    vrf_proof_to_hash,
    vrf_verify,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mainnet active slot coefficient
MAINNET_F: float = 0.05


class TestVRFConstants:
    """VRF size constants match the ECVRF-ED25519-SHA512-Elligator2 spec."""

    def test_proof_size(self) -> None:
        assert VRF_PROOF_SIZE == 80

    def test_output_size(self) -> None:
        assert VRF_OUTPUT_SIZE == 64

    def test_pk_size(self) -> None:
        assert VRF_PK_SIZE == 32

    def test_sk_size(self) -> None:
        assert VRF_SK_SIZE == 64


# ---------------------------------------------------------------------------
# certified_nat_max_check — pure Python leader election math
# ---------------------------------------------------------------------------


class TestCertifiedNatMaxCheck:
    """Test the Praos leader eligibility formula.

    The check is: natural_number(vrf_output) / 2^512 < 1 - (1-f)^sigma

    With sigma=1.0 and f=0.05, the threshold is 0.05 — so only VRF outputs
    in the bottom 5% of the range will pass. This is by design: even a pool
    with ALL the stake only produces a block ~5% of slots (on mainnet).
    """

    def test_full_stake_low_output_elected(self) -> None:
        """sigma=1.0 with a zero VRF output is elected (0 < threshold)."""
        min_output = b"\x00" * VRF_OUTPUT_SIZE
        assert certified_nat_max_check(min_output, sigma=1.0, f=MAINNET_F)

    def test_full_stake_max_output_not_elected(self) -> None:
        """sigma=1.0 with the max VRF output is NOT elected.

        The threshold is only f=0.05, so the max output (which represents
        ~1.0 as a fraction) is well above the threshold.
        """
        max_output = b"\xff" * VRF_OUTPUT_SIZE
        assert not certified_nat_max_check(max_output, sigma=1.0, f=MAINNET_F)

    def test_zero_stake_never_elected(self) -> None:
        """A pool with 0% of stake is never elected."""
        min_output = b"\x00" * VRF_OUTPUT_SIZE
        assert not certified_nat_max_check(min_output, sigma=0.0, f=MAINNET_F)

    def test_zero_stake_never_elected_max_output(self) -> None:
        """sigma=0.0 is not elected even with the lowest VRF output."""
        max_output = b"\xff" * VRF_OUTPUT_SIZE
        assert not certified_nat_max_check(max_output, sigma=0.0, f=MAINNET_F)

    def test_zero_vrf_output_always_wins(self) -> None:
        """A VRF output of all zeros beats any positive threshold."""
        zero_output = b"\x00" * VRF_OUTPUT_SIZE
        # Any positive sigma with f > 0 produces a positive threshold,
        # and 0 < positive_threshold is always true.
        assert certified_nat_max_check(zero_output, sigma=0.001, f=MAINNET_F)

    def test_max_vrf_output_never_wins_with_low_stake(self) -> None:
        """The maximum VRF output (all 0xff) never wins with low stake."""
        max_output = b"\xff" * VRF_OUTPUT_SIZE
        assert not certified_nat_max_check(max_output, sigma=0.5, f=MAINNET_F)

    def test_known_threshold_sigma_1(self) -> None:
        """Verify the threshold formula with sigma=1.0, f=0.05.

        For f=0.05, sigma=1.0:
            q = 1 - (1-0.05)^1.0 = 1 - 0.95 = 0.05

        threshold_nat = floor(0.05 * 2^512)
        """
        getcontext().prec = 40
        threshold_nat = int(Decimal("0.05") * Decimal(2**512))

        # A VRF output just below the threshold should win.
        just_below = (threshold_nat - 1).to_bytes(64, byteorder="big")
        assert certified_nat_max_check(just_below, sigma=1.0, f=MAINNET_F)

        # A VRF output at the threshold should NOT win (strict <).
        at_threshold = threshold_nat.to_bytes(64, byteorder="big")
        assert not certified_nat_max_check(at_threshold, sigma=1.0, f=MAINNET_F)

    def test_known_threshold_sigma_half(self) -> None:
        """Verify with sigma=0.5, f=0.05.

        q = 1 - (1-0.05)^0.5 = 1 - sqrt(0.95) ~ 0.02532...
        """
        getcontext().prec = 40
        one = Decimal(1)
        q = one - (one - Decimal("0.05")).ln() * Decimal("0.5")
        # Actually compute properly: (1-f)^sigma = exp(sigma * ln(1-f))
        q = one - ((one - Decimal("0.05")).ln() * Decimal("0.5")).exp()

        # Zero output should win (0 < q for any positive q).
        zero_output = b"\x00" * VRF_OUTPUT_SIZE
        assert certified_nat_max_check(zero_output, sigma=0.5, f=MAINNET_F)

    def test_threshold_increases_with_stake(self) -> None:
        """Higher stake means a higher threshold (more likely to be elected)."""
        getcontext().prec = 40

        f = Decimal("0.05")
        one = Decimal(1)

        # q(sigma) = 1 - (1-f)^sigma is strictly increasing in sigma.
        q_low = one - (one - f) ** Decimal("0.1")
        q_high = one - (one - f) ** Decimal("0.9")
        assert q_high > q_low

    def test_half_stake_reasonable_probability(self) -> None:
        """With sigma=0.5 and f=0.05, the probability should be ~2.5%."""
        getcontext().prec = 40

        f = Decimal("0.05")
        one = Decimal(1)
        sigma = Decimal("0.5")

        q = one - (one - f) ** sigma
        # q should be approximately 0.0253 (1 - sqrt(0.95))
        assert Decimal("0.02") < q < Decimal("0.03")

    def test_high_f_full_stake_high_threshold(self) -> None:
        """With f=0.99, sigma=1.0, almost all VRF outputs win.

        q = 1 - (1-0.99)^1 = 0.99, so 99% of VRF outputs pass.
        """
        # An output at 50% of the range should pass since threshold is 99%.
        mid_output = b"\x80" + b"\x00" * (VRF_OUTPUT_SIZE - 1)
        assert certified_nat_max_check(mid_output, sigma=1.0, f=0.99)


class TestCertifiedNatMaxCheckValidation:
    """Input validation for certified_nat_max_check."""

    def test_wrong_output_size(self) -> None:
        with pytest.raises(ValueError, match="64 bytes"):
            certified_nat_max_check(b"\x00" * 32, sigma=0.5, f=MAINNET_F)

    def test_sigma_below_range(self) -> None:
        output = b"\x00" * VRF_OUTPUT_SIZE
        with pytest.raises(ValueError, match="sigma"):
            certified_nat_max_check(output, sigma=-0.1, f=MAINNET_F)

    def test_sigma_above_range(self) -> None:
        output = b"\x00" * VRF_OUTPUT_SIZE
        with pytest.raises(ValueError, match="sigma"):
            certified_nat_max_check(output, sigma=1.1, f=MAINNET_F)

    def test_f_zero(self) -> None:
        output = b"\x00" * VRF_OUTPUT_SIZE
        with pytest.raises(ValueError, match="f must"):
            certified_nat_max_check(output, sigma=0.5, f=0.0)

    def test_f_one(self) -> None:
        output = b"\x00" * VRF_OUTPUT_SIZE
        with pytest.raises(ValueError, match="f must"):
            certified_nat_max_check(output, sigma=0.5, f=1.0)

    def test_f_negative(self) -> None:
        output = b"\x00" * VRF_OUTPUT_SIZE
        with pytest.raises(ValueError, match="f must"):
            certified_nat_max_check(output, sigma=0.5, f=-0.01)


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------


class TestCertifiedNatMaxCheckProperties:
    """Property-based tests for the leader election formula.

    These are designed to be compatible with Antithesis/Moog:
    deterministic given the same random seed, with clear invariants.
    """

    @given(
        vrf_bytes=st.binary(min_size=VRF_OUTPUT_SIZE, max_size=VRF_OUTPUT_SIZE),
        sigma_low=st.floats(min_value=0.001, max_value=0.999),
    )
    @settings(max_examples=200)
    def test_monotonic_in_stake(
        self, vrf_bytes: bytes, sigma_low: float
    ) -> None:
        """If elected at stake sigma, must also be elected at any higher stake.

        This is the core monotonicity property: more stake => higher
        threshold => more likely to be elected.
        """
        f = MAINNET_F
        sigma_high = min(sigma_low + 0.001, 1.0)
        result_low = certified_nat_max_check(vrf_bytes, sigma=sigma_low, f=f)
        if result_low:
            result_high = certified_nat_max_check(
                vrf_bytes, sigma=sigma_high, f=f
            )
            assert result_high, (
                f"Elected at sigma={sigma_low} but not at sigma={sigma_high}"
            )

    @given(
        vrf_bytes=st.binary(min_size=VRF_OUTPUT_SIZE, max_size=VRF_OUTPUT_SIZE),
        f_low=st.floats(min_value=0.01, max_value=0.98),
    )
    @settings(max_examples=200)
    def test_monotonic_in_f(self, vrf_bytes: bytes, f_low: float) -> None:
        """Higher active slot coefficient means higher election probability.

        For a fixed VRF output and sigma, if elected at f_low, must also be
        elected at f_high > f_low.
        """
        sigma = 0.5
        f_high = min(f_low + 0.01, 0.99)
        result_low = certified_nat_max_check(vrf_bytes, sigma=sigma, f=f_low)
        if result_low:
            result_high = certified_nat_max_check(
                vrf_bytes, sigma=sigma, f=f_high
            )
            assert result_high, (
                f"Elected at f={f_low} but not at f={f_high}"
            )

    @given(
        vrf_bytes=st.binary(min_size=VRF_OUTPUT_SIZE, max_size=VRF_OUTPUT_SIZE),
    )
    @settings(max_examples=100)
    def test_zero_stake_never_wins(self, vrf_bytes: bytes) -> None:
        """sigma=0 never wins regardless of VRF output."""
        assert not certified_nat_max_check(vrf_bytes, sigma=0.0, f=MAINNET_F)

    @given(
        vrf_bytes=st.binary(min_size=VRF_OUTPUT_SIZE, max_size=VRF_OUTPUT_SIZE),
    )
    @settings(max_examples=100)
    def test_zero_output_always_wins_with_positive_stake(
        self, vrf_bytes: bytes
    ) -> None:
        """A VRF output of all zeros should always win if sigma > 0.

        The VRF value 0 is always below any positive threshold.
        """
        zero_output = b"\x00" * VRF_OUTPUT_SIZE
        assert certified_nat_max_check(zero_output, sigma=0.001, f=MAINNET_F)


# ---------------------------------------------------------------------------
# VRF native bindings (conditional on IOG libsodium)
# ---------------------------------------------------------------------------


class TestVRFVerify:
    """Tests for vrf_verify — requires IOG libsodium fork."""

    @pytest.mark.skipif(HAS_VRF_NATIVE, reason="Testing fallback behavior")
    def test_raises_without_native(self) -> None:
        """vrf_verify raises NotImplementedError without IOG libsodium."""
        with pytest.raises(NotImplementedError, match="IOG libsodium"):
            vrf_verify(
                pk=b"\x00" * VRF_PK_SIZE,
                proof=b"\x00" * VRF_PROOF_SIZE,
                alpha=b"test",
            )

    @pytest.mark.skipif(
        not HAS_VRF_NATIVE, reason="IOG libsodium not available"
    )
    def test_invalid_proof_returns_none(self) -> None:
        """An all-zeros proof should fail verification."""
        result = vrf_verify(
            pk=b"\x00" * VRF_PK_SIZE,
            proof=b"\x00" * VRF_PROOF_SIZE,
            alpha=b"test",
        )
        assert result is None

    def test_wrong_pk_size(self) -> None:
        """Wrong public key size raises ValueError."""
        if not HAS_VRF_NATIVE:
            pytest.skip("IOG libsodium not available")
        with pytest.raises(ValueError, match=f"{VRF_PK_SIZE} bytes"):
            vrf_verify(
                pk=b"\x00" * 16,
                proof=b"\x00" * VRF_PROOF_SIZE,
                alpha=b"x",
            )

    def test_wrong_proof_size(self) -> None:
        """Wrong proof size raises ValueError."""
        if not HAS_VRF_NATIVE:
            pytest.skip("IOG libsodium not available")
        with pytest.raises(ValueError, match=f"{VRF_PROOF_SIZE} bytes"):
            vrf_verify(
                pk=b"\x00" * VRF_PK_SIZE,
                proof=b"\x00" * 32,
                alpha=b"x",
            )


class TestVRFProofToHash:
    """Tests for vrf_proof_to_hash — requires IOG libsodium fork."""

    @pytest.mark.skipif(HAS_VRF_NATIVE, reason="Testing fallback behavior")
    def test_raises_without_native(self) -> None:
        """vrf_proof_to_hash raises NotImplementedError without libsodium."""
        with pytest.raises(NotImplementedError, match="IOG libsodium"):
            vrf_proof_to_hash(proof=b"\x00" * VRF_PROOF_SIZE)

    def test_wrong_proof_size(self) -> None:
        """Wrong proof size raises ValueError."""
        if not HAS_VRF_NATIVE:
            pytest.skip("IOG libsodium not available")
        with pytest.raises(ValueError, match=f"{VRF_PROOF_SIZE} bytes"):
            vrf_proof_to_hash(proof=b"\x00" * 32)


# ---------------------------------------------------------------------------
# HAS_VRF_NATIVE flag
# ---------------------------------------------------------------------------


class TestHasVRFNative:
    """The HAS_VRF_NATIVE flag should be a bool."""

    def test_is_bool(self) -> None:
        assert isinstance(HAS_VRF_NATIVE, bool)

    def test_consistent_with_verify(self) -> None:
        """If HAS_VRF_NATIVE is False, verify should raise."""
        if not HAS_VRF_NATIVE:
            with pytest.raises(NotImplementedError):
                vrf_verify(
                    b"\x00" * VRF_PK_SIZE,
                    b"\x00" * VRF_PROOF_SIZE,
                    b"test",
                )
