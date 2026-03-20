"""Tests for KES (Key-Evolving Signatures) — sum-composition over Ed25519.

Tests cover:
    * Sign/verify round-trip for depths 1, 2, 3, and 6 (Cardano mainnet)
    * Key evolution (update) — forward security property
    * Rejection of wrong periods, tampered signatures, wrong VKs
    * Signature size correctness
    * Hypothesis property tests for any-period sign+verify

Spec references:
    * Shelley formal spec, Figure 2 — KES cryptographic definitions
    * MMM paper (Section 3.1) — iterated sum construction
"""

from __future__ import annotations

import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.crypto.kes import (
    CARDANO_KES_DEPTH,
    ED25519_SIG_SIZE,
    ED25519_VK_SIZE,
    kes_derive_vk,
    kes_keygen,
    kes_sig_size,
    kes_sign,
    kes_update,
    kes_verify,
)


# ---------------------------------------------------------------------------
# Signature size tests
# ---------------------------------------------------------------------------


class TestKesSigSize:
    """Verify the KES signature size formula."""

    def test_depth_0(self) -> None:
        """Depth 0 = raw Ed25519 signature = 64 bytes."""
        assert kes_sig_size(0) == ED25519_SIG_SIZE

    def test_depth_1(self) -> None:
        """Depth 1 = 64 + 2*32 = 128 bytes."""
        assert kes_sig_size(1) == 128

    def test_depth_2(self) -> None:
        """Depth 2 = 64 + 2*64 = 192 bytes."""
        assert kes_sig_size(2) == 192

    def test_depth_6_cardano(self) -> None:
        """Depth 6 (Cardano mainnet) = 64 * 7 = 448 bytes."""
        assert kes_sig_size(CARDANO_KES_DEPTH) == 448

    def test_formula(self) -> None:
        """sig_size(d) = 64 * (d + 1)."""
        for d in range(10):
            assert kes_sig_size(d) == ED25519_SIG_SIZE * (1 + d)


# ---------------------------------------------------------------------------
# VK derivation tests
# ---------------------------------------------------------------------------


class TestKesVkDerivation:
    """Verify that VK derivation produces 32-byte keys."""

    @pytest.mark.parametrize("depth", [0, 1, 2, 3])
    def test_vk_size(self, depth: int) -> None:
        """VK is always 32 bytes regardless of depth."""
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        assert len(vk) == ED25519_VK_SIZE

    def test_vk_deterministic(self) -> None:
        """Deriving VK from the same SK yields the same result."""
        sk = kes_keygen(2)
        vk1 = kes_derive_vk(sk)
        vk2 = kes_derive_vk(sk)
        assert vk1 == vk2


# ---------------------------------------------------------------------------
# Sign/Verify round-trip tests
# ---------------------------------------------------------------------------


class TestKesSignVerify:
    """Test sign+verify round-trips at various depths."""

    @pytest.mark.parametrize("depth", [0, 1, 2, 3])
    def test_roundtrip_period_0(self, depth: int) -> None:
        """Sign at period 0 and verify — should succeed."""
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        msg = b"test message for KES"
        sig = kes_sign(sk, 0, msg)
        assert kes_verify(vk, depth, 0, sig, msg)

    @pytest.mark.parametrize("depth", [1, 2, 3])
    def test_roundtrip_last_period(self, depth: int) -> None:
        """Sign at the last valid period and verify."""
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        last_period = (1 << depth) - 1
        msg = b"last period message"
        sig = kes_sign(sk, last_period, msg)
        assert kes_verify(vk, depth, last_period, sig, msg)

    @pytest.mark.parametrize("depth", [1, 2, 3])
    def test_roundtrip_all_periods(self, depth: int) -> None:
        """Sign and verify at every period for small depths."""
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        total = 1 << depth
        msg = b"verify all periods"
        for period in range(total):
            sig = kes_sign(sk, period, msg)
            assert kes_verify(vk, depth, period, sig, msg), (
                f"Verification failed at period {period}"
            )

    def test_roundtrip_depth_6_sample_periods(self) -> None:
        """Test a few periods at Cardano mainnet depth (6)."""
        sk = kes_keygen(6)
        vk = kes_derive_vk(sk)
        msg = b"cardano mainnet depth test"
        for period in [0, 1, 31, 32, 63]:
            sig = kes_sign(sk, period, msg)
            assert kes_verify(vk, 6, period, sig, msg), (
                f"Depth 6 verification failed at period {period}"
            )


# ---------------------------------------------------------------------------
# Signature size correctness
# ---------------------------------------------------------------------------


class TestKesSignatureSize:
    """Verify that produced signatures have the expected size."""

    @pytest.mark.parametrize("depth", [0, 1, 2, 3, 6])
    def test_sig_size(self, depth: int) -> None:
        sk = kes_keygen(depth)
        sig = kes_sign(sk, 0, b"size test")
        assert len(sig) == kes_sig_size(depth)


# ---------------------------------------------------------------------------
# Rejection tests
# ---------------------------------------------------------------------------


class TestKesRejection:
    """Test that invalid signatures are rejected."""

    def test_wrong_period(self) -> None:
        """Signature verified at wrong period should fail."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)
        msg = b"wrong period"
        sig = kes_sign(sk, 0, msg)
        # Verify at period 1 (signed at 0) — should fail
        assert not kes_verify(vk, 2, 1, sig, msg)

    def test_wrong_message(self) -> None:
        """Signature verified against wrong message should fail."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)
        sig = kes_sign(sk, 0, b"correct message")
        assert not kes_verify(vk, 2, 0, sig, b"wrong message")

    def test_wrong_vk(self) -> None:
        """Signature verified with wrong VK should fail."""
        sk1 = kes_keygen(2)
        sk2 = kes_keygen(2)
        vk2 = kes_derive_vk(sk2)
        msg = b"wrong vk"
        sig = kes_sign(sk1, 0, msg)
        assert not kes_verify(vk2, 2, 0, sig, msg)

    def test_tampered_signature(self) -> None:
        """Flipping a bit in the signature should cause rejection."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)
        msg = b"tampered sig"
        sig = kes_sign(sk, 0, msg)
        # Flip a bit in the middle of the signature
        tampered = bytearray(sig)
        tampered[len(sig) // 2] ^= 0x01
        assert not kes_verify(vk, 2, 0, bytes(tampered), msg)

    def test_period_out_of_range(self) -> None:
        """Period >= 2^depth should fail verification."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)
        msg = b"out of range"
        sig = kes_sign(sk, 0, msg)
        # Period 4 is out of range for depth 2 (max = 3)
        assert not kes_verify(vk, 2, 4, sig, msg)

    def test_negative_period(self) -> None:
        """Negative period should fail."""
        sk = kes_keygen(1)
        vk = kes_derive_vk(sk)
        assert not kes_verify(vk, 1, -1, b"\x00" * 128, b"msg")

    def test_wrong_sig_size(self) -> None:
        """Wrong signature size should be rejected."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)
        assert not kes_verify(vk, 2, 0, b"\x00" * 10, b"msg")

    def test_sign_out_of_range_raises(self) -> None:
        """Signing at out-of-range period raises ValueError."""
        sk = kes_keygen(2)
        with pytest.raises(ValueError, match="out of range"):
            kes_sign(sk, 4, b"msg")
        with pytest.raises(ValueError, match="out of range"):
            kes_sign(sk, -1, b"msg")


# ---------------------------------------------------------------------------
# Key evolution (update) tests
# ---------------------------------------------------------------------------


class TestKesUpdate:
    """Test KES key evolution — forward security property."""

    def test_update_simple(self) -> None:
        """After update, signing at the next period works."""
        sk = kes_keygen(1)
        vk = kes_derive_vk(sk)
        msg = b"evolution test"

        # Sign at period 0
        sig0 = kes_sign(sk, 0, msg)
        assert kes_verify(vk, 1, 0, sig0, msg)

        # Update to period 1
        sk1 = kes_update(sk, 0)
        assert sk1 is not None

        # Sign at period 1 with updated key
        sig1 = kes_sign(sk1, 1, msg)
        assert kes_verify(vk, 1, 1, sig1, msg)

    def test_update_exhausted(self) -> None:
        """Update returns None when all periods are exhausted."""
        sk = kes_keygen(1)  # 2 periods: 0, 1

        sk = kes_update(sk, 0)
        assert sk is not None

        # Period 1 is the last one
        result = kes_update(sk, 1)
        assert result is None

    def test_update_chain_depth_2(self) -> None:
        """Full update chain for depth 2 (4 periods)."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)
        msg = b"chain test"

        for period in range(4):
            sig = kes_sign(sk, period, msg)
            assert kes_verify(vk, 2, period, sig, msg), (
                f"Failed at period {period}"
            )
            if period < 3:
                sk = kes_update(sk, period)
                assert sk is not None

        # Exhausted
        assert kes_update(sk, 3) is None

    def test_vk_unchanged_after_update(self) -> None:
        """The verification key stays the same after updates."""
        sk = kes_keygen(2)
        vk_original = kes_derive_vk(sk)

        for period in range(3):
            sk = kes_update(sk, period)
            assert sk is not None
            vk_new = kes_derive_vk(sk)
            assert vk_new == vk_original


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------


class TestKesHypothesis:
    """Property-based tests using Hypothesis."""

    @given(
        depth=st.integers(min_value=0, max_value=3),
        msg=st.binary(min_size=1, max_size=256),
    )
    @settings(max_examples=50, deadline=10000)
    def test_sign_verify_any_period(self, depth: int, msg: bytes) -> None:
        """For any depth and any valid period, sign+verify succeeds."""
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        total = 1 << depth
        # Pick a deterministic period based on the message hash
        period = int.from_bytes(msg[:4].ljust(4, b"\x00"), "big") % total
        sig = kes_sign(sk, period, msg)
        assert kes_verify(vk, depth, period, sig, msg)

    @given(
        depth=st.integers(min_value=1, max_value=3),
        msg=st.binary(min_size=1, max_size=64),
    )
    @settings(max_examples=30, deadline=10000)
    def test_wrong_period_rejects(self, depth: int, msg: bytes) -> None:
        """For any depth, verifying at the wrong period fails."""
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        total = 1 << depth
        # Sign at period 0, verify at a different period
        sig = kes_sign(sk, 0, msg)
        for wrong_period in range(1, min(total, 4)):
            assert not kes_verify(vk, depth, wrong_period, sig, msg)

    @given(msg=st.binary(min_size=1, max_size=64))
    @settings(max_examples=20, deadline=10000)
    def test_out_of_range_period_rejects(self, msg: bytes) -> None:
        """Periods >= 2^depth always fail verification."""
        depth = 2
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        sig = kes_sign(sk, 0, msg)
        assert not kes_verify(vk, depth, 4, sig, msg)
        assert not kes_verify(vk, depth, 100, sig, msg)
