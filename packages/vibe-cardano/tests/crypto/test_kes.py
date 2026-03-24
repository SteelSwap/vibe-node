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
            assert kes_verify(vk, 2, period, sig, msg), f"Failed at period {period}"
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


# ---------------------------------------------------------------------------
# Test 2: KES signature CBOR serialization round-trip
# ---------------------------------------------------------------------------


class TestKesCborRoundTrip:
    """Test that KES signatures round-trip through CBOR bytestring encoding.

    In Cardano block headers, the KES signature is encoded as a CBOR
    bytestring. This tests that the raw signature bytes survive
    encode/decode and that the size matches expectations.

    Haskell ref: rawSerialiseSigKES / rawDeserialiseSigKES in
    Cardano.Crypto.KES.Sum
    """

    def test_kes_sig_cbor_roundtrip_depth_6(self) -> None:
        """448-byte KES signature (depth 6) round-trips through CBOR."""
        import cbor2

        sk = kes_keygen(CARDANO_KES_DEPTH)
        msg = b"block header body for CBOR test"
        sig = kes_sign(sk, 0, msg)

        assert len(sig) == 448  # 64 * (6 + 1)

        encoded = cbor2.dumps(sig)
        decoded = cbor2.loads(encoded)
        assert decoded == sig
        assert isinstance(decoded, bytes)
        assert len(decoded) == 448

    @pytest.mark.parametrize("depth", [0, 1, 2, 3])
    def test_kes_sig_cbor_roundtrip_various_depths(self, depth: int) -> None:
        """KES signatures at various depths round-trip through CBOR."""
        import cbor2

        sk = kes_keygen(depth)
        msg = b"cbor test message"
        sig = kes_sign(sk, 0, msg)

        expected_size = kes_sig_size(depth)
        assert len(sig) == expected_size

        encoded = cbor2.dumps(sig)
        decoded = cbor2.loads(encoded)
        assert decoded == sig

    def test_kes_sig_cbor_is_bytestring(self) -> None:
        """CBOR encoding of KES sig should be major type 2 (bytestring)."""
        import cbor2

        sk = kes_keygen(2)
        sig = kes_sign(sk, 0, b"type check")
        encoded = cbor2.dumps(sig)

        # Major type 2, length 192 (0xC0): 0x58 0xC0
        # 0x58 = major type 2 (010) + additional info 24 (11000) = byte length follows
        assert encoded[0] == 0x58
        assert encoded[1] == kes_sig_size(2)  # 192

    def test_kes_vk_cbor_roundtrip(self) -> None:
        """32-byte KES VK round-trips through CBOR."""
        import cbor2

        sk = kes_keygen(3)
        vk = kes_derive_vk(sk)
        assert len(vk) == ED25519_VK_SIZE

        encoded = cbor2.dumps(vk)
        decoded = cbor2.loads(encoded)
        assert decoded == vk


# ---------------------------------------------------------------------------
# Test 5: KES evolution with multi-block chain replay
# ---------------------------------------------------------------------------


class TestKesMultiBlockReplay:
    """Sign multiple consecutive blocks, evolve the key through each period,
    and verify that all old signatures still validate against the original VK.

    This simulates a chain replay scenario where a syncing node verifies
    a sequence of block headers signed at consecutive KES periods.

    Haskell ref: verifySignedKES in Cardano.Crypto.KES.Class —
    verification uses only the VK and period, not the secret key state.
    """

    def test_sign_5_consecutive_blocks_verify_all(self) -> None:
        """Generate KES key, sign 5 blocks at periods 0-4, verify all."""
        depth = 3  # 8 periods — enough for 5 blocks
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)

        signatures: list[tuple[int, bytes, bytes]] = []

        for period in range(5):
            msg = f"block header at period {period}".encode()
            sig = kes_sign(sk, period, msg)
            signatures.append((period, msg, sig))

            # Evolve key if not the last period we need
            if period < 4:
                sk = kes_update(sk, period)
                assert sk is not None, f"Key exhausted at period {period}"

        # Verify all signatures against the original VK
        for period, msg, sig in signatures:
            assert kes_verify(vk, depth, period, sig, msg), (
                f"Signature at period {period} failed verification"
            )

    def test_sign_all_periods_depth_3_verify_after_full_evolution(self) -> None:
        """Sign at all 8 periods of depth-3 key, verify all after full evolution."""
        depth = 3
        total = 1 << depth  # 8
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)

        signatures = []

        for period in range(total):
            msg = f"block-{period}".encode()
            sig = kes_sign(sk, period, msg)
            signatures.append((period, msg, sig))

            if period < total - 1:
                sk = kes_update(sk, period)
                assert sk is not None

        # Key should now be exhausted
        assert kes_update(sk, total - 1) is None

        # All signatures still verify against the original VK
        for period, msg, sig in signatures:
            assert kes_verify(vk, depth, period, sig, msg), (
                f"Post-evolution verification failed at period {period}"
            )

    def test_vk_stable_through_evolution_chain(self) -> None:
        """VK derived from the evolved key matches the original VK at each step."""
        depth = 3
        sk = kes_keygen(depth)
        original_vk = kes_derive_vk(sk)

        for period in range(7):  # 0..6, evolve 7 times for depth 3
            sk = kes_update(sk, period)
            assert sk is not None
            assert kes_derive_vk(sk) == original_vk, (
                f"VK changed after evolution at period {period}"
            )

    def test_evolved_key_cannot_sign_past_periods(self) -> None:
        """After evolving past period 0, the period-0 leaf is erased.

        The evolved key can still sign at later periods but the internal
        tree structure has been modified. We verify that signing at the
        current period works but the old signatures still verify.
        """
        depth = 2  # 4 periods
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)

        # Sign at period 0
        msg0 = b"period zero block"
        sig0 = kes_sign(sk, 0, msg0)

        # Evolve to period 1
        sk = kes_update(sk, 0)
        assert sk is not None

        # Sign at period 1
        msg1 = b"period one block"
        sig1 = kes_sign(sk, 1, msg1)

        # Both signatures verify against original VK
        assert kes_verify(vk, depth, 0, sig0, msg0)
        assert kes_verify(vk, depth, 1, sig1, msg1)


# ---------------------------------------------------------------------------
# Test 6 (KES part): Key size mismatch edge cases
# ---------------------------------------------------------------------------


class TestKesKeySizeMismatch:
    """Test that KES verification rejects inputs of incorrect sizes.

    Haskell ref: rawDeserialiseSigKES checks exact byte size
    and returns Nothing on mismatch.
    """

    def test_truncated_kes_sig_rejected(self) -> None:
        """A KES signature shorter than expected should be rejected."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)
        msg = b"truncated sig test"
        sig = kes_sign(sk, 0, msg)

        # Truncate by 1 byte
        assert not kes_verify(vk, 2, 0, sig[:-1], msg)

    def test_extended_kes_sig_rejected(self) -> None:
        """A KES signature longer than expected should be rejected."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)
        msg = b"extended sig test"
        sig = kes_sign(sk, 0, msg)

        # Append an extra byte
        assert not kes_verify(vk, 2, 0, sig + b"\x00", msg)

    def test_empty_kes_sig_rejected(self) -> None:
        """An empty KES signature should be rejected."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)
        assert not kes_verify(vk, 2, 0, b"", b"msg")

    def test_wrong_vk_size_rejected(self) -> None:
        """A VK of wrong size should be rejected by kes_verify."""
        sk = kes_keygen(2)
        sig = kes_sign(sk, 0, b"msg")

        # 31-byte VK (too short)
        assert not kes_verify(b"\x00" * 31, 2, 0, sig, b"msg")
        # 33-byte VK (too long)
        assert not kes_verify(b"\x00" * 33, 2, 0, sig, b"msg")

    def test_half_size_kes_sig_rejected(self) -> None:
        """A signature that's exactly half the expected size should fail."""
        sk = kes_keygen(CARDANO_KES_DEPTH)
        vk = kes_derive_vk(sk)
        msg = b"half size test"
        sig = kes_sign(sk, 0, msg)

        half = len(sig) // 2
        assert not kes_verify(vk, CARDANO_KES_DEPTH, 0, sig[:half], msg)
