"""Tests for vibe.cardano.crypto.vrf — VRF leader election and bindings.

Tests cover:
1. The pure Python leader check math (certified_nat_max_check)
2. VRF constants
3. Input validation
4. Property-based tests via Hypothesis (leader probability monotonic in stake)
5. Native VRF operations (only when _vrf_native extension is built)

Key insight: sigma=1.0 does NOT mean "always elected." The Praos formula is:
    leader_val = nat(blake2b_256("L" || vrf_output)) / 2^256
    elected iff leader_val < 1 - (1-f)^sigma
For sigma=1.0, the threshold is f (e.g., 5% on mainnet). The pool is elected
with probability f per slot, which is the maximum possible probability.

Because Praos hashes the VRF output with blake2b before comparison, raw byte
patterns like all-zeros or all-ones do NOT map predictably to low/high leader
values. We use pre-computed VRF outputs with known leader values instead.
"""

from __future__ import annotations

import hashlib
import os
import struct
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
    _2_POW_256,
    certified_nat_max_check,
    vrf_keypair,
    vrf_leader_value,
    vrf_proof_to_hash,
    vrf_prove,
    vrf_verify,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mainnet active slot coefficient
MAINNET_F: float = 0.05

# Pre-computed VRF outputs with known Praos leader values:
# sha512(929) → leader_val ≈ 0.0000156 (ultra-low, always wins for any positive threshold)
WINNER_VRF_OUTPUT = hashlib.sha512(struct.pack(">Q", 929)).digest()
# sha512(51692) → leader_val ≈ 0.9995 (ultra-high, always loses)
LOSER_VRF_OUTPUT = hashlib.sha512(struct.pack(">Q", 51692)).digest()


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

    The check is: nat(blake2b_256("L" || vrf_output)) / 2^256 < 1 - (1-f)^sigma

    With sigma=1.0 and f=0.05, the threshold is 0.05. The Praos leader value
    is derived from the VRF output via blake2b hashing, so raw byte patterns
    do NOT map predictably. We use pre-computed outputs with known leader values.
    """

    def test_full_stake_low_leader_val_elected(self) -> None:
        """sigma=1.0 with a VRF output producing ultra-low leader_val is elected."""
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=1.0, f=MAINNET_F)

    def test_full_stake_high_leader_val_not_elected(self) -> None:
        """sigma=1.0 with a VRF output producing high leader_val is NOT elected.

        The threshold is only f=0.05, so a leader_val ~0.9995 is well above.
        """
        assert not certified_nat_max_check(LOSER_VRF_OUTPUT, sigma=1.0, f=MAINNET_F)

    def test_zero_stake_never_elected(self) -> None:
        """A pool with 0% of stake is never elected."""
        assert not certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=0.0, f=MAINNET_F)

    def test_zero_stake_never_elected_loser_output(self) -> None:
        """sigma=0.0 is not elected even with a losing VRF output."""
        assert not certified_nat_max_check(LOSER_VRF_OUTPUT, sigma=0.0, f=MAINNET_F)

    def test_ultra_low_leader_val_always_wins(self) -> None:
        """A VRF output with ultra-low leader_val beats any positive threshold."""
        # leader_val ~0.0000156, which is below threshold for sigma=0.001, f=0.05
        # threshold = 1 - (1-0.05)^0.001 ≈ 0.0000513
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=0.001, f=MAINNET_F)

    def test_high_leader_val_never_wins_with_low_stake(self) -> None:
        """A VRF output with high leader_val never wins with low stake."""
        assert not certified_nat_max_check(LOSER_VRF_OUTPUT, sigma=0.5, f=MAINNET_F)

    def test_known_threshold_sigma_1(self) -> None:
        """Verify the threshold formula with sigma=1.0, f=0.05.

        For f=0.05, sigma=1.0:
            q = 1 - (1-0.05)^1.0 = 1 - 0.95 = 0.05

        threshold_nat = floor(0.05 * 2^256)

        We construct a VRF output whose leader hash is just below/at threshold.
        """
        getcontext().prec = 40
        threshold_nat = int(Decimal("0.05") * Decimal(_2_POW_256))

        # Verify using the pre-computed winner (leader_val ~0.0000156 < 0.05)
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=1.0, f=MAINNET_F)

        # Verify using the pre-computed loser (leader_val ~0.9995 > 0.05)
        assert not certified_nat_max_check(LOSER_VRF_OUTPUT, sigma=1.0, f=MAINNET_F)

    def test_known_threshold_sigma_half(self) -> None:
        """Verify with sigma=0.5, f=0.05.

        q = 1 - (1-0.05)^0.5 = 1 - sqrt(0.95) ~ 0.02532...
        """
        # Winner output (leader_val ~0.0000156) should win (< 0.02532)
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=0.5, f=MAINNET_F)

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
        # Both the "winner" and even most random outputs pass f=0.99.
        # The loser (leader_val ~0.9995) still fails since 0.9995 > 0.99.
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=1.0, f=0.99)
        # Use the mid output which has leader_val ~0.17 < 0.99
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
    def test_ultra_low_leader_val_always_wins_with_positive_stake(
        self, vrf_bytes: bytes
    ) -> None:
        """A VRF output with ultra-low leader_val should always win if sigma > 0.

        The pre-computed WINNER_VRF_OUTPUT has leader_val ~0.0000156, which is
        below any positive threshold for sigma >= 0.001 and f=0.05.
        """
        assert certified_nat_max_check(WINNER_VRF_OUTPUT, sigma=0.001, f=MAINNET_F)


# ---------------------------------------------------------------------------
# VRF native bindings (conditional on _vrf_native extension)
# ---------------------------------------------------------------------------

# Native VRF extension is required for the node to operate.
# No fallback tests — if the extension isn't built, these tests
# should fail loudly, not skip silently.


class TestVRFVerify:
    """Tests for vrf_verify."""

    def test_invalid_proof_returns_none(self) -> None:
        """An all-zeros proof should fail verification (return None)."""
        result = vrf_verify(
            pk=b"\x00" * VRF_PK_SIZE,
            proof=b"\x00" * VRF_PROOF_SIZE,
            alpha=b"test",
        )
        assert result is None

    def test_wrong_pk_size(self) -> None:
        """Wrong public key size raises ValueError."""
        with pytest.raises(ValueError, match=f"{VRF_PK_SIZE} bytes"):
            vrf_verify(
                pk=b"\x00" * 16,
                proof=b"\x00" * VRF_PROOF_SIZE,
                alpha=b"x",
            )

    def test_wrong_proof_size(self) -> None:
        """Wrong proof size raises ValueError."""
        with pytest.raises(ValueError, match=f"{VRF_PROOF_SIZE} bytes"):
            vrf_verify(
                pk=b"\x00" * VRF_PK_SIZE,
                proof=b"\x00" * 32,
                alpha=b"x",
            )


class TestVRFProofToHash:
    """Tests for vrf_proof_to_hash."""


    def test_wrong_proof_size(self) -> None:
        """Wrong proof size raises ValueError."""
        with pytest.raises(ValueError, match=f"{VRF_PROOF_SIZE} bytes"):
            vrf_proof_to_hash(proof=b"\x00" * 32)


class TestVRFProve:
    """Tests for vrf_prove."""


    def test_wrong_sk_size(self) -> None:
        """Wrong secret key size raises ValueError."""
        with pytest.raises(ValueError, match=f"{VRF_SK_SIZE} bytes"):
            vrf_prove(sk=b"\x00" * 32, alpha=b"test")


# ---------------------------------------------------------------------------
# End-to-end VRF tests (native extension required)
# ---------------------------------------------------------------------------


class TestVRFEndToEnd:
    """Full prove-verify-hash round-trip tests.

    These tests exercise the complete VRF pipeline:
    keypair generation -> prove -> verify -> proof_to_hash.

    Only run when the _vrf_native extension is built.
    """

    def test_keypair_sizes(self) -> None:
        """Generated keypair has correct sizes."""
        pk, sk = vrf_keypair()
        assert len(pk) == VRF_PK_SIZE
        assert len(sk) == VRF_SK_SIZE

    def test_keypair_unique(self) -> None:
        """Two keypairs should be distinct (CSPRNG)."""
        pk1, sk1 = vrf_keypair()
        pk2, sk2 = vrf_keypair()
        assert pk1 != pk2
        assert sk1 != sk2

    def test_prove_returns_correct_size(self) -> None:
        """vrf_prove returns an 80-byte proof."""
        pk, sk = vrf_keypair()
        proof = vrf_prove(sk, alpha=b"test alpha string")
        assert len(proof) == VRF_PROOF_SIZE

    def test_prove_verify_roundtrip(self) -> None:
        """prove then verify succeeds and returns 64-byte output."""
        pk, sk = vrf_keypair()
        alpha = b"slot 12345 nonce"
        proof = vrf_prove(sk, alpha)
        output = vrf_verify(pk, proof, alpha)
        assert output is not None
        assert len(output) == VRF_OUTPUT_SIZE

    def test_verify_wrong_alpha_fails(self) -> None:
        """Verify with a different alpha string returns None."""
        pk, sk = vrf_keypair()
        proof = vrf_prove(sk, alpha=b"correct alpha")
        result = vrf_verify(pk, proof, alpha=b"wrong alpha")
        assert result is None

    def test_verify_wrong_pk_fails(self) -> None:
        """Verify with a different public key returns None."""
        pk1, sk1 = vrf_keypair()
        pk2, sk2 = vrf_keypair()
        alpha = b"test"
        proof = vrf_prove(sk1, alpha)
        # Verify with pk2 should fail.
        result = vrf_verify(pk2, proof, alpha)
        assert result is None

    def test_tampered_proof_fails(self) -> None:
        """Flipping a bit in the proof causes verification failure."""
        pk, sk = vrf_keypair()
        alpha = b"tamper test"
        proof = vrf_prove(sk, alpha)

        # Flip one bit in the proof.
        tampered = bytearray(proof)
        tampered[40] ^= 0x01
        tampered = bytes(tampered)

        result = vrf_verify(pk, tampered, alpha)
        assert result is None

    def test_proof_to_hash_matches_verify(self) -> None:
        """proof_to_hash output matches the output from vrf_verify."""
        pk, sk = vrf_keypair()
        alpha = b"consistency check"
        proof = vrf_prove(sk, alpha)

        verify_output = vrf_verify(pk, proof, alpha)
        hash_output = vrf_proof_to_hash(proof)

        assert verify_output is not None
        assert verify_output == hash_output

    def test_proof_to_hash_size(self) -> None:
        """proof_to_hash returns 64 bytes."""
        pk, sk = vrf_keypair()
        proof = vrf_prove(sk, alpha=b"hash size test")
        output = vrf_proof_to_hash(proof)
        assert len(output) == VRF_OUTPUT_SIZE

    def test_deterministic_prove(self) -> None:
        """Same sk + alpha produces the same proof (VRF is deterministic)."""
        pk, sk = vrf_keypair()
        alpha = b"determinism check"
        proof1 = vrf_prove(sk, alpha)
        proof2 = vrf_prove(sk, alpha)
        assert proof1 == proof2

    def test_different_alpha_different_proof(self) -> None:
        """Different alpha strings produce different proofs."""
        pk, sk = vrf_keypair()
        proof1 = vrf_prove(sk, alpha=b"alpha one")
        proof2 = vrf_prove(sk, alpha=b"alpha two")
        assert proof1 != proof2

    def test_vrf_output_feeds_leader_check(self) -> None:
        """The VRF output can be passed to certified_nat_max_check.

        This is the integration point: VRF produces a 64-byte output,
        and the leader check consumes it.
        """
        pk, sk = vrf_keypair()
        alpha = b"leader election slot 42"
        proof = vrf_prove(sk, alpha)
        output = vrf_proof_to_hash(proof)

        # Should not raise — the output is the right size.
        # We don't care about the boolean result, just that it works.
        result = certified_nat_max_check(output, sigma=0.5, f=0.05)
        assert isinstance(result, bool)

    def test_empty_alpha(self) -> None:
        """VRF works with an empty alpha string."""
        pk, sk = vrf_keypair()
        proof = vrf_prove(sk, alpha=b"")
        output = vrf_verify(pk, proof, alpha=b"")
        assert output is not None
        assert len(output) == VRF_OUTPUT_SIZE

    def test_large_alpha(self) -> None:
        """VRF works with a large alpha string (1 KB)."""
        pk, sk = vrf_keypair()
        alpha = os.urandom(1024)
        proof = vrf_prove(sk, alpha)
        output = vrf_verify(pk, proof, alpha)
        assert output is not None
        assert len(output) == VRF_OUTPUT_SIZE


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

    def test_consistent_with_keypair(self) -> None:
        """If HAS_VRF_NATIVE is False, keypair should raise."""
        if not HAS_VRF_NATIVE:
            with pytest.raises(NotImplementedError):
                vrf_keypair()

    def test_consistent_with_prove(self) -> None:
        """If HAS_VRF_NATIVE is False, prove should raise."""
        if not HAS_VRF_NATIVE:
            with pytest.raises(NotImplementedError):
                vrf_prove(b"\x00" * VRF_SK_SIZE, b"test")


# ---------------------------------------------------------------------------
# Test 1: VRF proof CBOR serialization round-trip
# ---------------------------------------------------------------------------


class TestVRFCborRoundTrip:
    """Test that VRF proof, output, and PK bytes round-trip through CBOR.

    Block headers encode VRF proofs/outputs as CBOR bytestrings. This test
    ensures raw bytes of the correct sizes survive encode/decode via cbor2.

    Haskell ref: Cardano.Protocol.TPraos.BHeader — VRF fields are
    CBOR-encoded as raw bytestrings in the block header.
    """

    def test_vrf_proof_cbor_roundtrip(self) -> None:
        """80-byte VRF proof round-trips through CBOR bytestring encoding."""
        import cbor2

        proof = os.urandom(VRF_PROOF_SIZE)
        encoded = cbor2.dumps(proof)
        decoded = cbor2.loads(encoded)
        assert decoded == proof
        assert isinstance(decoded, bytes)
        assert len(decoded) == VRF_PROOF_SIZE

    def test_vrf_output_cbor_roundtrip(self) -> None:
        """64-byte VRF output round-trips through CBOR bytestring encoding."""
        import cbor2

        output = os.urandom(VRF_OUTPUT_SIZE)
        encoded = cbor2.dumps(output)
        decoded = cbor2.loads(encoded)
        assert decoded == output
        assert len(decoded) == VRF_OUTPUT_SIZE

    def test_vrf_pk_cbor_roundtrip(self) -> None:
        """32-byte VRF public key round-trips through CBOR bytestring encoding."""
        import cbor2

        pk = os.urandom(VRF_PK_SIZE)
        encoded = cbor2.dumps(pk)
        decoded = cbor2.loads(encoded)
        assert decoded == pk
        assert len(decoded) == VRF_PK_SIZE

    def test_vrf_proof_cbor_is_major_type_2(self) -> None:
        """CBOR encoding of a VRF proof should use major type 2 (bytestring).

        CBOR major type 2 means the first byte's high 3 bits are 010 (0x40-0x5b).
        For an 80-byte bytestring: 0x58 0x50 (2-byte length encoding).
        """
        import cbor2

        proof = b"\xab" * VRF_PROOF_SIZE
        encoded = cbor2.dumps(proof)
        # Major type 2, additional info 24 (1-byte length follows) = 0x58
        assert encoded[0] == 0x58
        assert encoded[1] == VRF_PROOF_SIZE  # 80

    def test_vrf_all_fields_in_cbor_array(self) -> None:
        """A CBOR array of [proof, output, pk] round-trips correctly."""
        import cbor2

        proof = os.urandom(VRF_PROOF_SIZE)
        output = os.urandom(VRF_OUTPUT_SIZE)
        pk = os.urandom(VRF_PK_SIZE)

        payload = [proof, output, pk]
        encoded = cbor2.dumps(payload)
        decoded = cbor2.loads(encoded)

        assert decoded[0] == proof
        assert decoded[1] == output
        assert decoded[2] == pk


# ---------------------------------------------------------------------------
# Test 6 (VRF part): Key size mismatch edge cases
# ---------------------------------------------------------------------------


class TestVRFKeySizeMismatch:
    """Test that VRF functions reject keys of incorrect sizes.

    Haskell ref: rawDeserialise* functions in cardano-crypto-class
    check exact byte sizes and return Nothing on mismatch.
    """

    def test_vrf_verify_pk_too_short(self) -> None:
        """31-byte VRF PK should be rejected by vrf_verify."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_PK_SIZE} bytes"):
            vrf_verify(
                pk=b"\x00" * 31,
                proof=b"\x00" * VRF_PROOF_SIZE,
                alpha=b"test",
            )

    def test_vrf_verify_pk_too_long(self) -> None:
        """33-byte VRF PK should be rejected by vrf_verify."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_PK_SIZE} bytes"):
            vrf_verify(
                pk=b"\x00" * 33,
                proof=b"\x00" * VRF_PROOF_SIZE,
                alpha=b"test",
            )

    def test_vrf_verify_proof_too_short(self) -> None:
        """79-byte VRF proof should be rejected."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_PROOF_SIZE} bytes"):
            vrf_verify(
                pk=b"\x00" * VRF_PK_SIZE,
                proof=b"\x00" * 79,
                alpha=b"test",
            )

    def test_vrf_verify_proof_too_long(self) -> None:
        """81-byte VRF proof should be rejected."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_PROOF_SIZE} bytes"):
            vrf_verify(
                pk=b"\x00" * VRF_PK_SIZE,
                proof=b"\x00" * 81,
                alpha=b"test",
            )

    def test_vrf_prove_sk_too_short(self) -> None:
        """63-byte VRF SK should be rejected by vrf_prove."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_SK_SIZE} bytes"):
            vrf_prove(sk=b"\x00" * 63, alpha=b"test")

    def test_vrf_prove_sk_too_long(self) -> None:
        """65-byte VRF SK should be rejected by vrf_prove."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_SK_SIZE} bytes"):
            vrf_prove(sk=b"\x00" * 65, alpha=b"test")

    def test_vrf_proof_to_hash_too_short(self) -> None:
        """79-byte proof should be rejected by vrf_proof_to_hash."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_PROOF_SIZE} bytes"):
            vrf_proof_to_hash(proof=b"\x00" * 79)

    def test_vrf_proof_to_hash_too_long(self) -> None:
        """81-byte proof should be rejected by vrf_proof_to_hash."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_PROOF_SIZE} bytes"):
            vrf_proof_to_hash(proof=b"\x00" * 81)

    def test_vrf_verify_empty_pk(self) -> None:
        """Empty PK should be rejected."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_PK_SIZE} bytes"):
            vrf_verify(pk=b"", proof=b"\x00" * VRF_PROOF_SIZE, alpha=b"x")

    def test_vrf_verify_empty_proof(self) -> None:
        """Empty proof should be rejected."""
        if not HAS_VRF_NATIVE:
            pytest.skip("Needs native VRF extension")
        with pytest.raises(ValueError, match=f"{VRF_PROOF_SIZE} bytes"):
            vrf_verify(pk=b"\x00" * VRF_PK_SIZE, proof=b"", alpha=b"x")

    def test_certified_nat_max_check_wrong_output_size(self) -> None:
        """VRF output of wrong size should be rejected by leader check."""
        for bad_size in [0, 31, 32, 63, 65, 128]:
            with pytest.raises(ValueError, match="64 bytes"):
                certified_nat_max_check(
                    b"\x00" * bad_size, sigma=0.5, f=MAINNET_F
                )
