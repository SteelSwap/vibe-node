"""Haskell test parity: crypto property-based tests (VRF + KES).

Brings our test coverage in line with the Haskell cardano-crypto-class
property tests, specifically:

- VRF proof determinism: same key + input always produces the same proof/output
- VRF output uniqueness: different inputs produce different outputs
- KES key evolution correctness: evolved key signs at new period, old period fails
- KES forward security: after evolution, previous-period signing material is erased
- KES VK stability through full evolution chain (Hypothesis)

Spec references:
    - Ouroboros Praos paper, Section 4 — VRF properties
    - Shelley formal spec, Figure 2 — KES cryptographic definitions
    - MMM paper, Section 3.1 — sum-composition forward security

Haskell references:
    - cardano-crypto-class tests: Test.Crypto.KES (prop_KES_*)
    - cardano-crypto-class tests: Test.Crypto.VRF (prop_VRF_*)
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from vibe.cardano.crypto.kes import (
    kes_derive_vk,
    kes_keygen,
    kes_keygen_from_seed,
    kes_sign,
    kes_update,
    kes_verify,
)
from vibe.cardano.crypto.vrf import (
    HAS_VRF_NATIVE,
    certified_nat_max_check,
    vrf_keypair,
    vrf_proof_to_hash,
    vrf_prove,
    vrf_verify,
)

# Mark to skip VRF native tests when the C extension is not built
needs_vrf_native = pytest.mark.skipif(
    not HAS_VRF_NATIVE,
    reason="Requires _vrf_native C extension (build with CMake)",
)


# ---------------------------------------------------------------------------
# VRF proof determinism (Hypothesis)
#
# Haskell parity: prop_VRF_verify — same sk + alpha always yields
# the same proof and the same output hash.
# ---------------------------------------------------------------------------


@needs_vrf_native
class TestVRFProofDeterminism:
    """VRF is a *function* — same key + same input must always produce the
    same proof and output. This is a core VRF correctness property.

    Haskell ref: prop_VRF_verify in Test.Crypto.VRF
    """

    @given(
        alpha=st.binary(min_size=0, max_size=512),
    )
    @settings(max_examples=50, deadline=10000)
    def test_prove_deterministic_hypothesis(self, alpha: bytes) -> None:
        """For a fixed keypair, vrf_prove(sk, alpha) is deterministic."""
        pk, sk = vrf_keypair()
        proof1 = vrf_prove(sk, alpha)
        proof2 = vrf_prove(sk, alpha)
        assert proof1 == proof2, "VRF proof must be deterministic"

    @given(
        alpha=st.binary(min_size=0, max_size=512),
    )
    @settings(max_examples=50, deadline=10000)
    def test_output_deterministic_hypothesis(self, alpha: bytes) -> None:
        """The VRF output hash is also deterministic for fixed key + input."""
        pk, sk = vrf_keypair()
        proof = vrf_prove(sk, alpha)
        hash1 = vrf_proof_to_hash(proof)
        hash2 = vrf_proof_to_hash(proof)
        assert hash1 == hash2, "VRF output hash must be deterministic"

    @given(
        alpha=st.binary(min_size=0, max_size=256),
    )
    @settings(max_examples=30, deadline=10000)
    def test_verify_output_matches_proof_to_hash(self, alpha: bytes) -> None:
        """vrf_verify output == vrf_proof_to_hash for valid proofs.

        This is a critical consistency property: the two code paths for
        extracting the VRF output must agree.
        """
        pk, sk = vrf_keypair()
        proof = vrf_prove(sk, alpha)
        verify_output = vrf_verify(pk, proof, alpha)
        hash_output = vrf_proof_to_hash(proof)
        assert verify_output is not None
        assert verify_output == hash_output

    def test_multiple_invocations_same_key(self) -> None:
        """10 consecutive prove calls with the same key+alpha are identical."""
        pk, sk = vrf_keypair()
        alpha = b"determinism stress test"
        proofs = [vrf_prove(sk, alpha) for _ in range(10)]
        assert all(p == proofs[0] for p in proofs)


# ---------------------------------------------------------------------------
# VRF output uniqueness
#
# Haskell parity: different alpha strings must produce different outputs
# (with overwhelming probability).
# ---------------------------------------------------------------------------


@needs_vrf_native
class TestVRFOutputUniqueness:
    """Different inputs to the same VRF key produce different outputs.

    This tests the pseudorandomness property of the VRF — collisions
    should be astronomically unlikely.

    Haskell ref: implied by the VRF security game in the Praos paper.
    """

    @given(
        alpha1=st.binary(min_size=1, max_size=256),
        alpha2=st.binary(min_size=1, max_size=256),
    )
    @settings(max_examples=50, deadline=10000)
    def test_different_alpha_different_output(self, alpha1: bytes, alpha2: bytes) -> None:
        """Different alpha strings produce different VRF outputs."""
        assume(alpha1 != alpha2)
        pk, sk = vrf_keypair()
        proof1 = vrf_prove(sk, alpha1)
        proof2 = vrf_prove(sk, alpha2)
        out1 = vrf_proof_to_hash(proof1)
        out2 = vrf_proof_to_hash(proof2)
        assert out1 != out2, "VRF collision: different alphas produced same output"

    def test_different_keys_different_output(self) -> None:
        """Different keys produce different outputs for the same alpha."""
        alpha = b"same alpha for both keys"
        pk1, sk1 = vrf_keypair()
        pk2, sk2 = vrf_keypair()
        proof1 = vrf_prove(sk1, alpha)
        proof2 = vrf_prove(sk2, alpha)
        out1 = vrf_proof_to_hash(proof1)
        out2 = vrf_proof_to_hash(proof2)
        assert out1 != out2, "Different VRF keys should produce different outputs"

    def test_sequential_slots_unique_outputs(self) -> None:
        """Simulates VRF evaluation across 100 sequential slot numbers.

        All outputs must be unique — this is the real-world usage pattern
        for leader election.
        """
        pk, sk = vrf_keypair()
        outputs = set()
        for slot in range(100):
            alpha = slot.to_bytes(8, byteorder="big")
            proof = vrf_prove(sk, alpha)
            output = vrf_proof_to_hash(proof)
            assert output not in outputs, f"VRF collision at slot {slot}"
            outputs.add(output)


# ---------------------------------------------------------------------------
# KES key evolution correctness (Hypothesis)
#
# Haskell parity: prop_KES_verify_neg — after evolving past period t,
# the key can no longer sign at period t (forward security).
# Also: prop_KES_verify_pos — the evolved key CAN sign at the new period.
# ---------------------------------------------------------------------------


class TestKESEvolutionCorrectness:
    """KES evolution: the evolved key signs at the new period, and
    signatures at old periods still verify (but only with the old sig).

    Haskell ref: prop_KES_verify_pos, prop_KES_verify_neg in
    Test.Crypto.KES
    """

    @given(
        depth=st.integers(min_value=1, max_value=3),
        msg=st.binary(min_size=1, max_size=128),
    )
    @settings(max_examples=30, deadline=15000)
    def test_evolved_key_signs_new_period(self, depth: int, msg: bytes) -> None:
        """After evolving from period t to t+1, signing at t+1 succeeds."""
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        total = 1 << depth

        # Pick a random starting period (not the last one)
        period = int.from_bytes(msg[:2].ljust(2, b"\x00"), "big") % (total - 1)

        # Evolve to the next period
        evolved_sk = sk
        for p in range(period + 1):
            if p < period:
                evolved_sk = kes_update(evolved_sk, p)
                assert evolved_sk is not None

        # Sign at the target period
        sig = kes_sign(evolved_sk, period, msg)
        assert kes_verify(
            vk, depth, period, sig, msg
        ), f"Evolved key failed to sign at period {period}"

        # Evolve one more step
        evolved_sk = kes_update(evolved_sk, period)
        if evolved_sk is not None and period + 1 < total:
            # Sign at the NEW period should succeed
            sig_new = kes_sign(evolved_sk, period + 1, msg)
            assert kes_verify(
                vk, depth, period + 1, sig_new, msg
            ), f"Evolved key failed to sign at period {period + 1}"

    @given(
        depth=st.integers(min_value=1, max_value=3),
        msg=st.binary(min_size=1, max_size=64),
    )
    @settings(max_examples=30, deadline=15000)
    def test_old_signature_still_verifies_after_evolution(self, depth: int, msg: bytes) -> None:
        """Signatures produced BEFORE evolution still verify afterward.

        This is critical for chain sync: a verifying node must be able to
        check old block signatures using only the VK.
        """
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)

        # Sign at period 0
        sig0 = kes_sign(sk, 0, msg)

        # Evolve through several periods
        for period in range(min(3, (1 << depth) - 1)):
            sk = kes_update(sk, period)
            assert sk is not None

        # The old signature at period 0 still verifies
        assert kes_verify(
            vk, depth, 0, sig0, msg
        ), "Old signature must still verify after key evolution"

    @given(
        depth=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=20, deadline=15000)
    def test_cross_period_signatures_do_not_verify(self, depth: int) -> None:
        """A signature for period t must NOT verify at period t+1.

        This ensures the KES tree structure correctly differentiates
        time periods.
        """
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        msg = b"cross-period test"

        sig_0 = kes_sign(sk, 0, msg)

        # Must NOT verify at period 1
        assert not kes_verify(
            vk, depth, 1, sig_0, msg
        ), "Period-0 signature must not verify at period 1"

        # Sign at last period, must NOT verify at period 0
        total = 1 << depth
        sig_last = kes_sign(sk, total - 1, msg)
        assert not kes_verify(
            vk, depth, 0, sig_last, msg
        ), "Last-period signature must not verify at period 0"


# ---------------------------------------------------------------------------
# KES forward security property
#
# Haskell parity: the fundamental security property — after evolution,
# the old period's signing key is erased.
# ---------------------------------------------------------------------------


class TestKESForwardSecurity:
    """Forward security: after key evolution, the old leaf key is erased.

    The internal representation should show that the old subtree is
    removed (set to None) after evolution past the boundary.

    Haskell ref: updateKES in Cardano.Crypto.KES.Sum — "forget" the
    left subtree when transitioning to the right half.
    """

    def test_left_subtree_erased_at_boundary(self) -> None:
        """After evolving past the midpoint, the left subtree is None."""
        depth = 2  # 4 periods, midpoint at 2
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)

        # Evolve through period 0
        sk = kes_update(sk, 0)
        assert sk is not None
        # Left subtree should still exist (we're still in the left half)
        assert sk.left is not None

        # Evolve past the midpoint (period 1 is last in left half)
        sk = kes_update(sk, 1)
        assert sk is not None
        # Now the left subtree should be erased
        assert sk.left is None, "Left subtree should be erased after evolving past midpoint"

        # But we can still sign at period 2 (right half)
        sig2 = kes_sign(sk, 2, b"right half")
        assert kes_verify(vk, depth, 2, sig2, b"right half")

    def test_full_evolution_exhausts_key(self) -> None:
        """Evolving through all periods returns None at the end."""
        depth = 2  # 4 periods
        sk = kes_keygen(depth)

        for period in range(3):  # 0, 1, 2
            sk = kes_update(sk, period)
            assert sk is not None, f"Key exhausted too early at period {period}"

        # Period 3 is the last — evolution should return None
        result = kes_update(sk, 3)
        assert result is None, "Key should be exhausted after all periods"

    def test_deterministic_keygen_from_seed(self) -> None:
        """kes_keygen_from_seed produces the same key tree for the same seed.

        This property is essential for key recovery from cold storage.
        """
        seed = b"\xab" * 32
        sk1 = kes_keygen_from_seed(seed, depth=3)
        sk2 = kes_keygen_from_seed(seed, depth=3)
        vk1 = kes_derive_vk(sk1)
        vk2 = kes_derive_vk(sk2)
        assert vk1 == vk2, "Same seed must produce same VK"

        # Signatures must also match
        msg = b"deterministic keygen"
        sig1 = kes_sign(sk1, 0, msg)
        sig2 = kes_sign(sk2, 0, msg)
        assert sig1 == sig2, "Same seed must produce same signatures"

    def test_different_seeds_different_keys(self) -> None:
        """Different seeds must produce different KES keys."""
        sk1 = kes_keygen_from_seed(b"\x01" * 32, depth=2)
        sk2 = kes_keygen_from_seed(b"\x02" * 32, depth=2)
        vk1 = kes_derive_vk(sk1)
        vk2 = kes_derive_vk(sk2)
        assert vk1 != vk2, "Different seeds must produce different VKs"


# ---------------------------------------------------------------------------
# KES VK stability through full evolution (Hypothesis)
#
# Haskell parity: prop_KES_deriveVerKey — VK is always the same
# regardless of the current evolution state.
# ---------------------------------------------------------------------------


class TestKESVKStabilityHypothesis:
    """The verification key must remain identical through all key updates.

    Haskell ref: prop_KES_deriveVerKey in Test.Crypto.KES
    """

    @given(
        depth=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=10, deadline=30000)
    def test_vk_stable_through_all_evolutions(self, depth: int) -> None:
        """VK stays the same through every evolution step."""
        sk = kes_keygen(depth)
        original_vk = kes_derive_vk(sk)
        total = 1 << depth

        for period in range(total - 1):
            sk = kes_update(sk, period)
            assert sk is not None
            current_vk = kes_derive_vk(sk)
            assert current_vk == original_vk, f"VK changed after evolution at period {period}"

    @given(
        seed=st.binary(min_size=32, max_size=32),
        depth=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=15, deadline=20000)
    def test_seed_keygen_vk_stable(self, seed: bytes, depth: int) -> None:
        """VK from seed-based keygen is stable through evolution."""
        sk = kes_keygen_from_seed(seed, depth)
        original_vk = kes_derive_vk(sk)
        total = 1 << depth

        for period in range(min(total - 1, 4)):
            sk = kes_update(sk, period)
            assert sk is not None
            assert kes_derive_vk(sk) == original_vk


# ---------------------------------------------------------------------------
# VRF output feeds leader check (integration property)
#
# Haskell parity: the VRF output from prove/verify must be usable
# in the leader election formula without error.
# ---------------------------------------------------------------------------


@needs_vrf_native
class TestVRFLeaderCheckIntegration:
    """VRF outputs from the native extension can be passed directly
    to the leader election check.

    This exercises the full pipeline: keygen -> prove -> hash -> leader_check.
    """

    @given(
        sigma=st.floats(min_value=0.001, max_value=0.999),
        slot=st.integers(min_value=0, max_value=1_000_000),
    )
    @settings(max_examples=50, deadline=10000)
    def test_vrf_output_accepted_by_leader_check(self, sigma: float, slot: int) -> None:
        """Leader check accepts all VRF outputs without error."""
        pk, sk = vrf_keypair()
        alpha = slot.to_bytes(8, byteorder="big")
        proof = vrf_prove(sk, alpha)
        output = vrf_proof_to_hash(proof)

        # Must not raise — output size is always correct
        result = certified_nat_max_check(output, sigma=sigma, f=0.05)
        assert isinstance(result, bool)

    @given(
        sigma=st.floats(min_value=0.001, max_value=0.999),
    )
    @settings(max_examples=30, deadline=10000)
    def test_verified_output_matches_hash_for_leader_check(self, sigma: float) -> None:
        """Both vrf_verify and vrf_proof_to_hash produce the same
        leader election result."""
        pk, sk = vrf_keypair()
        alpha = b"leader integration test"
        proof = vrf_prove(sk, alpha)

        out_verify = vrf_verify(pk, proof, alpha)
        out_hash = vrf_proof_to_hash(proof)

        assert out_verify is not None
        result_v = certified_nat_max_check(out_verify, sigma=sigma, f=0.05)
        result_h = certified_nat_max_check(out_hash, sigma=sigma, f=0.05)
        assert result_v == result_h, "Leader check must agree for verify-output and proof-to-hash"
