"""Tests for vibe.cardano.consensus.nonce — epoch nonce evolution.

Tests cover:
1. EpochNonce construction and validation
2. Stability window boundary checks
3. VRF output accumulation (hash chaining)
4. Nonce evolution with and without extra entropy
5. Hypothesis property-based tests for accumulator determinism
"""

from __future__ import annotations

import hashlib
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.consensus.nonce import (
    NEUTRAL_NONCE,
    STABILITY_WINDOW_FRACTION,
    EpochNonce,
    accumulate_vrf_output,
    evolve_nonce,
    is_in_stability_window,
    mk_nonce,
)


# ---------------------------------------------------------------------------
# EpochNonce construction
# ---------------------------------------------------------------------------


class TestEpochNonce:
    """EpochNonce dataclass validation."""

    def test_valid_32_bytes(self) -> None:
        nonce = EpochNonce(b"\xab" * 32)
        assert len(nonce.value) == 32

    def test_rejects_short_bytes(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            EpochNonce(b"\x00" * 16)

    def test_rejects_long_bytes(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            EpochNonce(b"\x00" * 64)

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            EpochNonce(b"")

    def test_neutral_nonce_is_zeros(self) -> None:
        assert NEUTRAL_NONCE.value == b"\x00" * 32

    def test_frozen(self) -> None:
        nonce = EpochNonce(b"\x01" * 32)
        with pytest.raises(AttributeError):
            nonce.value = b"\x02" * 32  # type: ignore[misc]

    def test_repr(self) -> None:
        nonce = EpochNonce(b"\xde\xad" + b"\x00" * 30)
        r = repr(nonce)
        assert "EpochNonce(" in r
        assert "dead" in r


class TestMkNonce:
    """mk_nonce helper."""

    def test_produces_32_bytes(self) -> None:
        nonce = mk_nonce(b"hello world")
        assert len(nonce.value) == 32

    def test_deterministic(self) -> None:
        a = mk_nonce(b"same input")
        b = mk_nonce(b"same input")
        assert a == b

    def test_different_inputs_different_nonces(self) -> None:
        a = mk_nonce(b"input A")
        b = mk_nonce(b"input B")
        assert a != b


# ---------------------------------------------------------------------------
# Stability window
# ---------------------------------------------------------------------------


class TestStabilityWindow:
    """Stability window boundary checks."""

    def test_fraction_is_two_thirds(self) -> None:
        assert STABILITY_WINDOW_FRACTION == Fraction(2, 3)

    def test_first_slot_in_window(self) -> None:
        """Slot 0 of an epoch is always in the stability window."""
        assert is_in_stability_window(slot=0, epoch_start_slot=0, epoch_length=432000)

    def test_last_slot_in_window(self) -> None:
        """The last slot before 2/3 is in the window."""
        # epoch_length=432000, 2/3 = 288000
        # Slot 287999 should be in the window
        assert is_in_stability_window(
            slot=287999, epoch_start_slot=0, epoch_length=432000
        )

    def test_first_slot_outside_window(self) -> None:
        """Slot at exactly 2/3 is NOT in the window."""
        # slot_in_epoch=288000, 288000*3 = 864000, epoch_length*2 = 864000
        # 864000 < 864000 is False
        assert not is_in_stability_window(
            slot=288000, epoch_start_slot=0, epoch_length=432000
        )

    def test_last_slot_outside_window(self) -> None:
        """Last slot of epoch is outside the window."""
        assert not is_in_stability_window(
            slot=431999, epoch_start_slot=0, epoch_length=432000
        )

    def test_non_zero_epoch_start(self) -> None:
        """Works with arbitrary epoch start slot."""
        epoch_start = 432000  # epoch 1
        epoch_len = 432000
        # First slot of epoch 1 is in the window
        assert is_in_stability_window(slot=432000, epoch_start_slot=epoch_start, epoch_length=epoch_len)
        # 2/3 mark of epoch 1 is NOT in the window
        assert not is_in_stability_window(
            slot=432000 + 288000, epoch_start_slot=epoch_start, epoch_length=epoch_len
        )

    def test_small_epoch_length(self) -> None:
        """Edge case with small epoch (e.g., testnet with epoch_length=100)."""
        # 2/3 of 100 = 66.67, so slots 0-65 are in, 66+ are out
        # slot_in_epoch * 3 < 100 * 2 => slot_in_epoch * 3 < 200
        # slot 66: 66*3=198 < 200 => True (in window)
        assert is_in_stability_window(slot=66, epoch_start_slot=0, epoch_length=100)
        # slot 67: 67*3=201 < 200 => False (out of window)
        assert not is_in_stability_window(slot=67, epoch_start_slot=0, epoch_length=100)


# ---------------------------------------------------------------------------
# VRF accumulation
# ---------------------------------------------------------------------------


class TestAccumulateVrfOutput:
    """VRF output hash-chain accumulation."""

    def test_deterministic(self) -> None:
        """Same inputs produce same output."""
        eta = b"\x00" * 32
        vrf = b"\x01" * 32
        a = accumulate_vrf_output(eta, vrf)
        b = accumulate_vrf_output(eta, vrf)
        assert a == b

    def test_produces_32_bytes(self) -> None:
        result = accumulate_vrf_output(b"\x00" * 32, b"\xff" * 64)
        assert len(result) == 32

    def test_different_vrf_different_result(self) -> None:
        eta = b"\x00" * 32
        a = accumulate_vrf_output(eta, b"\x01" * 32)
        b = accumulate_vrf_output(eta, b"\x02" * 32)
        assert a != b

    def test_matches_blake2b_manual(self) -> None:
        """Verify the implementation matches Blake2b-256(eta || vrf_output)."""
        eta = b"\xab" * 32
        vrf = b"\xcd" * 48
        expected = hashlib.blake2b(eta + vrf, digest_size=32).digest()
        assert accumulate_vrf_output(eta, vrf) == expected

    def test_chaining(self) -> None:
        """Multiple accumulations form a hash chain."""
        eta = b"\x00" * 32
        vrf_outputs = [bytes([i]) * 32 for i in range(5)]

        for vrf in vrf_outputs:
            eta = accumulate_vrf_output(eta, vrf)

        assert len(eta) == 32
        # The result is deterministic
        eta2 = b"\x00" * 32
        for vrf in vrf_outputs:
            eta2 = accumulate_vrf_output(eta2, vrf)
        assert eta == eta2


# ---------------------------------------------------------------------------
# Nonce evolution
# ---------------------------------------------------------------------------


class TestEvolveNonce:
    """Epoch nonce evolution at epoch boundaries."""

    def test_basic_evolution(self) -> None:
        """Nonce evolves deterministically from prev_nonce and eta_v."""
        prev = mk_nonce(b"epoch 5 nonce")
        eta_v = b"\x42" * 32
        result = evolve_nonce(prev, eta_v)
        assert isinstance(result, EpochNonce)
        assert len(result.value) == 32
        assert result != prev

    def test_matches_blake2b_manual(self) -> None:
        """Verify: new_nonce = Blake2b-256(prev_nonce || eta_v)."""
        prev = EpochNonce(b"\x11" * 32)
        eta_v = b"\x22" * 32
        expected = hashlib.blake2b(prev.value + eta_v, digest_size=32).digest()
        result = evolve_nonce(prev, eta_v)
        assert result.value == expected

    def test_extra_entropy_mixed_in(self) -> None:
        """Extra entropy produces a different nonce."""
        prev = mk_nonce(b"epoch nonce")
        eta_v = b"\x33" * 32
        without = evolve_nonce(prev, eta_v)
        with_extra = evolve_nonce(prev, eta_v, extra_entropy=b"\x99" * 16)
        assert without != with_extra

    def test_extra_entropy_manual(self) -> None:
        """Verify: with extra = Blake2b-256(Blake2b-256(prev||eta_v) || extra)."""
        prev = EpochNonce(b"\xaa" * 32)
        eta_v = b"\xbb" * 32
        extra = b"\xcc" * 8

        step1 = hashlib.blake2b(prev.value + eta_v, digest_size=32).digest()
        expected = hashlib.blake2b(step1 + extra, digest_size=32).digest()

        result = evolve_nonce(prev, eta_v, extra_entropy=extra)
        assert result.value == expected

    def test_neutral_nonce_evolves(self) -> None:
        """Even the neutral nonce can be evolved."""
        eta_v = b"\x01" * 32
        result = evolve_nonce(NEUTRAL_NONCE, eta_v)
        assert result != NEUTRAL_NONCE

    def test_no_extra_entropy_is_none_not_empty(self) -> None:
        """None extra_entropy != empty bytes extra_entropy."""
        prev = mk_nonce(b"test")
        eta_v = b"\x44" * 32
        with_none = evolve_nonce(prev, eta_v, extra_entropy=None)
        with_empty = evolve_nonce(prev, eta_v, extra_entropy=b"")
        assert with_none != with_empty


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------


class TestNonceProperties:
    """Property-based tests for nonce operations."""

    @given(data=st.binary(min_size=1, max_size=256))
    @settings(max_examples=50)
    def test_mk_nonce_always_32_bytes(self, data: bytes) -> None:
        nonce = mk_nonce(data)
        assert len(nonce.value) == 32

    @given(
        eta=st.binary(min_size=32, max_size=32),
        vrf=st.binary(min_size=1, max_size=128),
    )
    @settings(max_examples=50)
    def test_accumulate_always_32_bytes(self, eta: bytes, vrf: bytes) -> None:
        result = accumulate_vrf_output(eta, vrf)
        assert len(result) == 32

    @given(
        prev=st.binary(min_size=32, max_size=32),
        eta_v=st.binary(min_size=32, max_size=32),
    )
    @settings(max_examples=50)
    def test_evolve_produces_valid_nonce(self, prev: bytes, eta_v: bytes) -> None:
        result = evolve_nonce(EpochNonce(prev), eta_v)
        assert isinstance(result, EpochNonce)
        assert len(result.value) == 32

    @given(
        slot_offset=st.integers(min_value=0, max_value=431999),
        epoch_length=st.integers(min_value=3, max_value=1000000),
    )
    @settings(max_examples=100)
    def test_stability_window_partition(
        self, slot_offset: int, epoch_length: int
    ) -> None:
        """Every slot is either in or out of the stability window — never both."""
        slot_offset = slot_offset % epoch_length
        result = is_in_stability_window(
            slot=slot_offset, epoch_start_slot=0, epoch_length=epoch_length
        )
        assert isinstance(result, bool)

        # The boundary is at 2/3: slot_in_epoch * 3 < epoch_length * 2
        if slot_offset * 3 < epoch_length * 2:
            assert result is True
        else:
            assert result is False
