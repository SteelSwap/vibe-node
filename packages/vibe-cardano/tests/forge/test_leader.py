"""Tests for leader schedule check (vibe.cardano.forge.leader).

Tests cover:
    * VRF seed construction (mkSeed: blake2b(slot||nonce) XOR seedConstant)
    * Leader election: elected with high stake
    * Leader election: not elected with zero stake
    * LeaderProof validation (correct sizes)
    * VRF proof verifies with pool's VRF VK (mocked native VRF)
    * Hypothesis: leader probability monotonic in stake

Spec references:
    - Ouroboros Praos, Section 4, Definition 6
    - Shelley formal spec, Section 16.1
    - Haskell ref: Cardano.Protocol.TPraos.BHeader.mkSeed
"""

from __future__ import annotations

import hashlib
import struct
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.crypto.vrf import VRF_OUTPUT_SIZE, VRF_PROOF_SIZE
from vibe.cardano.forge.leader import (
    SEED_ETA,
    SEED_L,
    LeaderProof,
    _make_vrf_input,
    _mk_input_vrf,
    _mk_seed,
    check_leadership,
)

# ---------------------------------------------------------------------------
# VRF input construction
# ---------------------------------------------------------------------------


class TestMkInputVrf:
    """Test the Praos mkInputVRF seed construction (Babbage/Conway)."""

    def test_output_length(self) -> None:
        """mkInputVRF produces 32 bytes (blake2b-256, no XOR)."""
        nonce = b"\xab" * 32
        seed = _make_vrf_input(nonce, 12345)
        assert len(seed) == 32

    def test_mk_input_vrf_manual(self) -> None:
        """Verify mkInputVRF = blake2b(slot_be64 || epoch_nonce) — no XOR."""
        epoch_nonce = b"\x02" * 32
        slot = 42
        payload = struct.pack(">Q", slot) + epoch_nonce
        expected = hashlib.blake2b(payload, digest_size=32).digest()
        assert _mk_input_vrf(slot, epoch_nonce) == expected

    def test_make_vrf_input_uses_mk_input_vrf(self) -> None:
        """_make_vrf_input delegates to mkInputVRF (Praos, no XOR)."""
        nonce = b"\xaa" * 32
        slot = 100
        assert _make_vrf_input(nonce, slot) == _mk_input_vrf(slot, nonce)

    def test_mk_seed_differs_from_mk_input_vrf(self) -> None:
        """mkSeed (TPraos) differs from mkInputVRF (Praos) due to XOR."""
        nonce = b"\xaa" * 32
        slot = 100
        praos_input = _mk_input_vrf(slot, nonce)
        tpraos_input = _mk_seed(SEED_L, slot, nonce)
        assert praos_input != tpraos_input

    def test_seed_constants(self) -> None:
        """seedEta = blake2b(0_u64), seedL = blake2b(1_u64)."""
        assert SEED_ETA == hashlib.blake2b(struct.pack(">Q", 0), digest_size=32).digest()
        assert SEED_L == hashlib.blake2b(struct.pack(">Q", 1), digest_size=32).digest()
        assert SEED_ETA != SEED_L

    def test_different_slots_different_seeds(self) -> None:
        """Different slots produce different VRF seeds."""
        nonce = b"\xcc" * 32
        seed1 = _make_vrf_input(nonce, 1)
        seed2 = _make_vrf_input(nonce, 2)
        assert seed1 != seed2

    def test_different_nonces_different_seeds(self) -> None:
        """Different epoch nonces produce different VRF seeds."""
        seed1 = _make_vrf_input(b"\x00" * 32, 100)
        seed2 = _make_vrf_input(b"\xff" * 32, 100)
        assert seed1 != seed2


# ---------------------------------------------------------------------------
# LeaderProof dataclass validation
# ---------------------------------------------------------------------------


class TestLeaderProof:
    """Test LeaderProof dataclass invariants."""

    def test_valid_proof(self) -> None:
        """Valid sizes accepted."""
        proof = LeaderProof(
            vrf_proof=b"\x00" * VRF_PROOF_SIZE,
            vrf_output=b"\x00" * VRF_OUTPUT_SIZE,
            slot=100,
        )
        assert proof.slot == 100

    def test_wrong_proof_size(self) -> None:
        """Wrong VRF proof size rejected."""
        with pytest.raises(ValueError, match="VRF proof must be"):
            LeaderProof(
                vrf_proof=b"\x00" * 10,
                vrf_output=b"\x00" * VRF_OUTPUT_SIZE,
                slot=1,
            )

    def test_wrong_output_size(self) -> None:
        """Wrong VRF output size rejected."""
        with pytest.raises(ValueError, match="VRF output must be"):
            LeaderProof(
                vrf_proof=b"\x00" * VRF_PROOF_SIZE,
                vrf_output=b"\x00" * 10,
                slot=1,
            )


# ---------------------------------------------------------------------------
# Leader check with mocked VRF
# ---------------------------------------------------------------------------


def _mock_vrf_prove(sk: bytes, alpha: bytes) -> bytes:
    """Mock VRF prove: returns deterministic 80-byte proof."""
    import hashlib

    h = hashlib.sha512(sk + alpha).digest()
    # Pad to 80 bytes
    return (h + h[:16])[:VRF_PROOF_SIZE]


def _mock_vrf_proof_to_hash(proof: bytes) -> bytes:
    """Mock VRF proof_to_hash: returns deterministic 64-byte output."""
    import hashlib

    return hashlib.sha512(proof).digest()


def _mock_vrf_proof_to_hash_low(proof: bytes) -> bytes:
    """Mock that returns a VRF output with ultra-low Praos leader value.

    sha512(929) produces a VRF output whose blake2b_256("L"||output) leader
    value is ~0.0000156, which passes the leader check for any positive stake.
    """
    return hashlib.sha512(struct.pack(">Q", 929)).digest()


def _mock_vrf_proof_to_hash_high(proof: bytes) -> bytes:
    """Mock that returns a VRF output with ultra-high Praos leader value.

    sha512(51692) produces a VRF output whose blake2b_256("L"||output) leader
    value is ~0.9995, which fails the leader check for any realistic stake.
    """
    return hashlib.sha512(struct.pack(">Q", 51692)).digest()


class TestCheckLeadership:
    """Test check_leadership with mocked VRF native operations."""

    @patch("vibe.cardano.forge.leader.vrf_prove", side_effect=_mock_vrf_prove)
    @patch(
        "vibe.cardano.forge.leader.vrf_proof_to_hash",
        side_effect=_mock_vrf_proof_to_hash_low,
    )
    def test_elected_high_stake(self, mock_p2h, mock_prove) -> None:
        """Pool with any positive stake elected when VRF output is low."""
        result = check_leadership(
            slot=1000,
            vrf_sk=b"\x01" * 64,
            pool_vrf_vk=b"\x02" * 32,
            relative_stake=0.5,
            active_slot_coeff=0.05,
            epoch_nonce=b"\xaa" * 32,
        )
        assert result is not None
        assert isinstance(result, LeaderProof)
        assert result.slot == 1000
        assert len(result.vrf_proof) == VRF_PROOF_SIZE
        assert len(result.vrf_output) == VRF_OUTPUT_SIZE

    @patch("vibe.cardano.forge.leader.vrf_prove", side_effect=_mock_vrf_prove)
    @patch(
        "vibe.cardano.forge.leader.vrf_proof_to_hash",
        side_effect=_mock_vrf_proof_to_hash_high,
    )
    def test_not_elected_high_output(self, mock_p2h, mock_prove) -> None:
        """Pool not elected when VRF output is max (all 0xFF)."""
        result = check_leadership(
            slot=1000,
            vrf_sk=b"\x01" * 64,
            pool_vrf_vk=b"\x02" * 32,
            relative_stake=0.5,
            active_slot_coeff=0.05,
            epoch_nonce=b"\xaa" * 32,
        )
        assert result is None

    @patch("vibe.cardano.forge.leader.vrf_prove", side_effect=_mock_vrf_prove)
    @patch(
        "vibe.cardano.forge.leader.vrf_proof_to_hash",
        side_effect=_mock_vrf_proof_to_hash_low,
    )
    def test_not_elected_zero_stake(self, mock_p2h, mock_prove) -> None:
        """Pool with zero stake is never elected (even with low VRF output)."""
        result = check_leadership(
            slot=1000,
            vrf_sk=b"\x01" * 64,
            pool_vrf_vk=b"\x02" * 32,
            relative_stake=0.0,
            active_slot_coeff=0.05,
            epoch_nonce=b"\xaa" * 32,
        )
        assert result is None

    @patch("vibe.cardano.forge.leader.vrf_prove", side_effect=_mock_vrf_prove)
    @patch(
        "vibe.cardano.forge.leader.vrf_proof_to_hash",
        side_effect=_mock_vrf_proof_to_hash_low,
    )
    def test_elected_full_stake(self, mock_p2h, mock_prove) -> None:
        """Pool with 100% stake is always elected when VRF output is low."""
        result = check_leadership(
            slot=42,
            vrf_sk=b"\x01" * 64,
            pool_vrf_vk=b"\x02" * 32,
            relative_stake=1.0,
            active_slot_coeff=0.05,
            epoch_nonce=b"\x00" * 32,
        )
        assert result is not None
        assert result.slot == 42


# ---------------------------------------------------------------------------
# Hypothesis: leader probability monotonic in stake
# ---------------------------------------------------------------------------


class TestLeaderProbabilityMonotonic:
    """Property test: higher stake should never decrease election probability."""

    @given(
        vrf_output=st.binary(min_size=VRF_OUTPUT_SIZE, max_size=VRF_OUTPUT_SIZE),
        low_stake=st.floats(min_value=0.0, max_value=0.5),
        high_stake_delta=st.floats(min_value=0.0, max_value=0.5),
    )
    @settings(max_examples=200)
    def test_monotonic_in_stake(
        self, vrf_output: bytes, low_stake: float, high_stake_delta: float
    ) -> None:
        """If elected at low stake, must also be elected at higher stake."""
        from vibe.cardano.crypto.vrf import certified_nat_max_check

        high_stake = min(low_stake + high_stake_delta, 1.0)
        f = 0.05

        # Skip edge cases where f validation would fail
        if low_stake < 0.0 or high_stake > 1.0:
            return

        elected_low = certified_nat_max_check(vrf_output, low_stake, f)
        elected_high = certified_nat_max_check(vrf_output, high_stake, f)

        # Monotonicity: if elected at lower stake, must be elected at higher
        if elected_low:
            assert elected_high, f"Elected at stake {low_stake} but not at {high_stake}"
