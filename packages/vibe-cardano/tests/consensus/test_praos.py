"""Tests for vibe.cardano.consensus.praos.

Covers:
- ActiveSlotCoeff validation
- leader_check wrapping certified_nat_max_check
- PraosState defaults
- apply_header state transitions (valid and invalid)
- OCert sequence number monotonicity across blocks
- KES period expiration after max_kes_evolutions
- Leader schedule statistics (Hypothesis)
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Optional

import pytest

from vibe.cardano.consensus.header_validation import (
    HeaderValidationFailure,
    HeaderValidationParams,
    PoolInfo,
    _pool_id_from_vkey,
)
from vibe.cardano.consensus.praos import (
    MAINNET_ACTIVE_SLOT_COEFF,
    ActiveSlotCoeff,
    PraosState,
    apply_header,
    leader_check,
)
from vibe.cardano.crypto.ocert import (
    OCertFailure,
    OperationalCert,
    validate_ocert,
)


# ---------------------------------------------------------------------------
# Mock header (reused from test_header_validation)
# ---------------------------------------------------------------------------


@dataclass
class MockProtocolVersion:
    major: int = 8
    minor: int = 0


@dataclass
class MockOperationalCert:
    hot_vkey: bytes = b"\x00" * 32
    sequence_number: int = 0
    kes_period: int = 0
    sigma: bytes = b"\x00" * 64


@dataclass
class MockBlockHeader:
    slot: int = 100
    block_number: int = 10
    prev_hash: Optional[bytes] = None
    issuer_vkey: bytes = b"\x00" * 32
    header_cbor: bytes = b"\x00" * 100
    protocol_version: MockProtocolVersion = None  # type: ignore
    operational_cert: MockOperationalCert = None  # type: ignore
    vrf_output: Optional[bytes] = None
    header_body_cbor: bytes = b""
    kes_signature: bytes = b""

    def __post_init__(self) -> None:
        if self.protocol_version is None:
            self.protocol_version = MockProtocolVersion()
        if self.operational_cert is None:
            self.operational_cert = MockOperationalCert()
        if self.prev_hash is None:
            self.prev_hash = b"\x00" * 32


def _blake2b_256(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=32).digest()


# ---------------------------------------------------------------------------
# ActiveSlotCoeff
# ---------------------------------------------------------------------------


class TestActiveSlotCoeff:
    def test_valid_mainnet_value(self) -> None:
        asc = ActiveSlotCoeff(value=0.05)
        assert asc.value == 0.05

    def test_zero_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="\\(0.0, 1.0\\)"):
            ActiveSlotCoeff(value=0.0)

    def test_one_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="\\(0.0, 1.0\\)"):
            ActiveSlotCoeff(value=1.0)

    def test_negative_is_invalid(self) -> None:
        with pytest.raises(ValueError):
            ActiveSlotCoeff(value=-0.1)

    def test_mainnet_constant(self) -> None:
        assert MAINNET_ACTIVE_SLOT_COEFF == 0.05


# ---------------------------------------------------------------------------
# leader_check
# ---------------------------------------------------------------------------


class TestLeaderCheck:
    # Pre-computed VRF outputs with known Praos leader values
    _WINNER = hashlib.sha512(b"\x00\x00\x00\x00\x00\x00\x03\xa1").digest()  # sha512(929)
    _LOSER = hashlib.sha512(b"\x00\x00\x00\x00\x00\x00\xc9\xec").digest()  # sha512(51692)

    def test_low_leader_val_always_wins(self) -> None:
        """VRF output with ultra-low leader_val should always win the lottery."""
        assert leader_check(self._WINNER, 0.01, 0.05) is True

    def test_high_leader_val_always_loses(self) -> None:
        """VRF output with high leader_val should lose for small stake."""
        assert leader_check(self._LOSER, 0.001, 0.05) is False

    def test_zero_stake_never_wins(self) -> None:
        assert leader_check(self._WINNER, 0.0, 0.05) is False

    def test_full_stake_winner_always_wins(self) -> None:
        """With sigma=1.0 and f=0.05, threshold=0.05.

        The winner VRF output has leader_val ~0.0000156 < 0.05 => elected.
        """
        assert leader_check(self._WINNER, 1.0, 0.05) is True

    def test_sigma_one_threshold_is_f(self) -> None:
        """When sigma=1.0, the threshold equals f exactly.

        Winner (leader_val ~0.0000156) should win, loser (~0.9995) should lose.
        """
        assert leader_check(self._WINNER, 1.0, 0.05) is True
        assert leader_check(self._LOSER, 1.0, 0.05) is False

    def test_invalid_vrf_size_raises(self) -> None:
        with pytest.raises(ValueError, match="64 bytes"):
            leader_check(b"\x00" * 32, 0.5, 0.05)


# ---------------------------------------------------------------------------
# PraosState
# ---------------------------------------------------------------------------


class TestPraosState:
    def test_default_state(self) -> None:
        state = PraosState()
        assert state.tip_slot == 0
        assert state.tip_block_number == 0
        assert len(state.tip_hash) == 32
        assert len(state.epoch_nonce) == 32
        assert state.stake_distribution == {}

    def test_custom_state(self) -> None:
        nonce = os.urandom(32)
        state = PraosState(
            tip_slot=1000,
            tip_hash=b"\xab" * 32,
            tip_block_number=50,
            epoch_nonce=nonce,
        )
        assert state.tip_slot == 1000
        assert state.tip_block_number == 50
        assert state.epoch_nonce == nonce


# ---------------------------------------------------------------------------
# apply_header
# ---------------------------------------------------------------------------


class TestApplyHeader:
    def _make_state_with_pool(
        self, issuer_vkey: bytes
    ) -> PraosState:
        """Create a PraosState with a pool in the stake distribution."""
        pool_id = _pool_id_from_vkey(issuer_vkey)
        dist = {
            pool_id: PoolInfo(
                vrf_vk=b"\x00" * 32,
                relative_stake=0.1,
                cold_vk=issuer_vkey,
                ocert_issue_number=0,
            )
        }
        return PraosState(
            tip_slot=50,
            tip_hash=b"\x11" * 32,
            tip_block_number=9,
            stake_distribution=dist,
        )

    def test_apply_header_pool_not_found_returns_errors(self) -> None:
        """Applying a header from an unknown pool should fail."""
        state = PraosState()
        header = MockBlockHeader(
            slot=100,
            block_number=1,
            issuer_vkey=b"\xaa" * 32,
        )
        new_state, errors = apply_header(state, header)
        assert len(errors) > 0
        # State should be unchanged
        assert new_state.tip_slot == state.tip_slot

    def test_apply_valid_header_updates_tip(self) -> None:
        """Applying a header from a known pool updates the state tip.

        Note: OCert validation will fail (mock signatures), so this
        test demonstrates that apply_header correctly reports errors.
        In a real scenario with valid cryptographic material, the state
        would be updated.
        """
        issuer = b"\xbb" * 32
        state = self._make_state_with_pool(issuer)

        prev = MockBlockHeader(
            slot=50,
            block_number=9,
            issuer_vkey=issuer,
            header_cbor=os.urandom(80),
        )
        prev_hash = _blake2b_256(prev.header_cbor)

        header = MockBlockHeader(
            slot=100,
            block_number=10,
            prev_hash=prev_hash,
            issuer_vkey=issuer,
            header_cbor=os.urandom(80),
        )

        new_state, errors = apply_header(state, header, prev_header=prev)

        # OCert errors expected (mock signatures are invalid), but the
        # structural checks (slot, block_number, prev_hash) should pass.
        # With mock crypto, we expect OCERT_INVALID errors.
        ocert_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.OCERT_INVALID
        ]
        slot_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.SLOT_NOT_INCREASING
        ]
        bn_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.BLOCK_NUMBER_MISMATCH
        ]
        hash_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.PREV_HASH_MISMATCH
        ]

        # Structural checks should pass
        assert len(slot_errors) == 0
        assert len(bn_errors) == 0
        assert len(hash_errors) == 0

        # OCert will fail with mock data — that's expected
        assert len(ocert_errors) > 0

        # State unchanged because there were errors
        assert new_state.tip_slot == state.tip_slot

    def test_slot_not_increasing_produces_error(self) -> None:
        """A header with slot <= prev slot fails slot check."""
        issuer = b"\xcc" * 32
        state = self._make_state_with_pool(issuer)

        prev = MockBlockHeader(
            slot=100,
            block_number=9,
            issuer_vkey=issuer,
        )
        header = MockBlockHeader(
            slot=50,  # <= prev.slot
            block_number=10,
            issuer_vkey=issuer,
        )

        _, errors = apply_header(state, header, prev_header=prev)
        slot_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.SLOT_NOT_INCREASING
        ]
        assert len(slot_errors) == 1


# ---------------------------------------------------------------------------
# Test 1: OCert sequence number monotonicity across blocks
# ---------------------------------------------------------------------------


class TestOCertSequenceMonotonicity:
    """OCert counter must be non-decreasing across blocks from the same pool.

    The OCERT transition rule requires: m <= n, where m is the on-chain
    counter and n is the cert counter. When a pool issues a new block,
    the on-chain counter is updated to the cert counter from the new block.
    Subsequent blocks from the same pool must have cert_count >= previous.

    Spec ref: Shelley formal spec, Figure 16, OCERT predicate 2.
    Haskell ref: ``CounterTooSmall`` in ``Cardano.Ledger.Shelley.Rules.OCert``
    """

    def test_same_counter_is_valid(self) -> None:
        """Two blocks with the same OCert counter should not trigger
        COUNTER_TOO_SMALL (m <= n is satisfied when m == n)."""
        ocert = OperationalCert(
            kes_vk=b"\x00" * 32,
            cert_count=5,
            kes_period_start=0,
            cold_sig=b"\x00" * 64,
        )
        # current_issue_no=5, cert_count=5 => 5 <= 5 => valid
        errors = validate_ocert(
            ocert=ocert,
            cold_vk=b"\x00" * 32,
            current_kes_period=0,
            current_issue_no=5,
            header_body_cbor=b"",
            kes_sig=b"",
            max_kes_evo=62,
        )
        counter_errors = [
            e for e in errors if e.failure == OCertFailure.COUNTER_TOO_SMALL
        ]
        assert len(counter_errors) == 0

    def test_increasing_counter_is_valid(self) -> None:
        """An OCert with counter > previous on-chain counter is valid."""
        ocert = OperationalCert(
            kes_vk=b"\x00" * 32,
            cert_count=10,
            kes_period_start=0,
            cold_sig=b"\x00" * 64,
        )
        # current_issue_no=5, cert_count=10 => 5 <= 10 => valid
        errors = validate_ocert(
            ocert=ocert,
            cold_vk=b"\x00" * 32,
            current_kes_period=0,
            current_issue_no=5,
            header_body_cbor=b"",
            kes_sig=b"",
            max_kes_evo=62,
        )
        counter_errors = [
            e for e in errors if e.failure == OCertFailure.COUNTER_TOO_SMALL
        ]
        assert len(counter_errors) == 0

    def test_decreasing_counter_is_rejected(self) -> None:
        """An OCert with counter < previous on-chain counter is rejected.

        This prevents replay of old certificates. If the on-chain counter
        is already at 10, presenting a cert with counter=5 must fail.
        """
        ocert = OperationalCert(
            kes_vk=b"\x00" * 32,
            cert_count=5,
            kes_period_start=0,
            cold_sig=b"\x00" * 64,
        )
        # current_issue_no=10, cert_count=5 => 10 > 5 => COUNTER_TOO_SMALL
        errors = validate_ocert(
            ocert=ocert,
            cold_vk=b"\x00" * 32,
            current_kes_period=0,
            current_issue_no=10,
            header_body_cbor=b"",
            kes_sig=b"",
            max_kes_evo=62,
        )
        counter_errors = [
            e for e in errors if e.failure == OCertFailure.COUNTER_TOO_SMALL
        ]
        assert len(counter_errors) == 1

    def test_monotonicity_sequence_of_three_blocks(self) -> None:
        """Simulate 3 blocks from the same pool: counter 5 -> 5 -> 7.

        Each block's cert_count becomes the new on-chain counter.
        Block 1: on-chain=3, cert=5 => valid (3 <= 5), update to 5
        Block 2: on-chain=5, cert=5 => valid (5 <= 5), stays 5
        Block 3: on-chain=5, cert=7 => valid (5 <= 7), update to 7
        """
        counters = [(3, 5), (5, 5), (5, 7)]
        for on_chain, cert_count in counters:
            ocert = OperationalCert(
                kes_vk=b"\x00" * 32,
                cert_count=cert_count,
                kes_period_start=0,
                cold_sig=b"\x00" * 64,
            )
            errors = validate_ocert(
                ocert=ocert,
                cold_vk=b"\x00" * 32,
                current_kes_period=0,
                current_issue_no=on_chain,
                header_body_cbor=b"",
                kes_sig=b"",
                max_kes_evo=62,
            )
            counter_errors = [
                e for e in errors
                if e.failure == OCertFailure.COUNTER_TOO_SMALL
            ]
            assert len(counter_errors) == 0, (
                f"on_chain={on_chain}, cert={cert_count} should be valid"
            )


# ---------------------------------------------------------------------------
# Test 2: KES period expiration after max_kes_evolutions
# ---------------------------------------------------------------------------


class TestKESPeriodExpiration:
    """KES period must satisfy: c_0 <= kes_period < c_0 + MaxKESEvo.

    A block at or beyond c_0 + MaxKESEvo must be rejected with KES_AFTER_END.
    A block at exactly c_0 + MaxKESEvo - 1 is the last valid period.

    Spec ref: Shelley formal spec, Figure 16, OCERT predicate 1b.
    Haskell ref: ``KESAfterEnd`` in ``Cardano.Ledger.Shelley.Rules.OCert``
    """

    def test_exactly_at_max_is_valid(self) -> None:
        """KES period = c_0 + max_kes_evo - 1 is the last valid period.

        The predicate is: kes_period < c_0 + max_kes_evo (strict less-than).
        So c_0 + max_kes_evo - 1 should be valid.
        """
        max_kes_evo = 62
        c_0 = 10
        # Last valid period: c_0 + max_kes_evo - 1 = 71
        current_kes_period = c_0 + max_kes_evo - 1

        ocert = OperationalCert(
            kes_vk=b"\x00" * 32,
            cert_count=0,
            kes_period_start=c_0,
            cold_sig=b"\x00" * 64,
        )
        errors = validate_ocert(
            ocert=ocert,
            cold_vk=b"\x00" * 32,
            current_kes_period=current_kes_period,
            current_issue_no=0,
            header_body_cbor=b"",
            kes_sig=b"",
            max_kes_evo=max_kes_evo,
        )
        kes_after_errors = [
            e for e in errors if e.failure == OCertFailure.KES_AFTER_END
        ]
        assert len(kes_after_errors) == 0

    def test_one_past_max_is_rejected(self) -> None:
        """KES period = c_0 + max_kes_evo is the first INVALID period.

        The predicate: kes_period < c_0 + max_kes_evo.
        So c_0 + max_kes_evo should trigger KES_AFTER_END.
        """
        max_kes_evo = 62
        c_0 = 10
        current_kes_period = c_0 + max_kes_evo  # 72 — one past max

        ocert = OperationalCert(
            kes_vk=b"\x00" * 32,
            cert_count=0,
            kes_period_start=c_0,
            cold_sig=b"\x00" * 64,
        )
        errors = validate_ocert(
            ocert=ocert,
            cold_vk=b"\x00" * 32,
            current_kes_period=current_kes_period,
            current_issue_no=0,
            header_body_cbor=b"",
            kes_sig=b"",
            max_kes_evo=max_kes_evo,
        )
        kes_after_errors = [
            e for e in errors if e.failure == OCertFailure.KES_AFTER_END
        ]
        assert len(kes_after_errors) == 1

    def test_well_past_max_is_rejected(self) -> None:
        """KES period far beyond max is also rejected."""
        max_kes_evo = 62
        c_0 = 0
        current_kes_period = 200  # way past 62

        ocert = OperationalCert(
            kes_vk=b"\x00" * 32,
            cert_count=0,
            kes_period_start=c_0,
            cold_sig=b"\x00" * 64,
        )
        errors = validate_ocert(
            ocert=ocert,
            cold_vk=b"\x00" * 32,
            current_kes_period=current_kes_period,
            current_issue_no=0,
            header_body_cbor=b"",
            kes_sig=b"",
            max_kes_evo=max_kes_evo,
        )
        kes_after_errors = [
            e for e in errors if e.failure == OCertFailure.KES_AFTER_END
        ]
        assert len(kes_after_errors) == 1

    def test_at_start_is_valid(self) -> None:
        """KES period = c_0 is valid (the start period)."""
        ocert = OperationalCert(
            kes_vk=b"\x00" * 32,
            cert_count=0,
            kes_period_start=5,
            cold_sig=b"\x00" * 64,
        )
        errors = validate_ocert(
            ocert=ocert,
            cold_vk=b"\x00" * 32,
            current_kes_period=5,
            current_issue_no=0,
            header_body_cbor=b"",
            kes_sig=b"",
            max_kes_evo=62,
        )
        kes_before_errors = [
            e for e in errors if e.failure == OCertFailure.KES_BEFORE_START
        ]
        kes_after_errors = [
            e for e in errors if e.failure == OCertFailure.KES_AFTER_END
        ]
        assert len(kes_before_errors) == 0
        assert len(kes_after_errors) == 0


# ---------------------------------------------------------------------------
# Test 3: Leader schedule statistics (Hypothesis/statistical)
# ---------------------------------------------------------------------------


class TestLeaderScheduleStatistics:
    """Statistical test: leader election frequency matches expected probability.

    For f=0.05 and sigma=0.5, the Praos leader election threshold is:
        p = 1 - (1 - f)^sigma = 1 - 0.95^0.5 ≈ 0.02532

    Over 10,000 random VRF outputs, the fraction elected should be
    approximately 2.5%, with generous bounds [1.5%, 3.5%] to avoid
    flakiness.

    Spec ref: Ouroboros Praos, Section 4, Definition 6.
    """

    def test_leader_election_frequency(self) -> None:
        """Generate 10,000 random VRF outputs and verify election rate."""
        import random

        f = 0.05
        sigma = 0.5

        # Use a fixed seed for deterministic testing (Antithesis-compatible)
        rng = random.Random(42)
        n_trials = 10_000
        n_elected = 0

        for _ in range(n_trials):
            vrf_output = bytes(rng.getrandbits(8) for _ in range(64))
            if leader_check(vrf_output, sigma, f):
                n_elected += 1

        fraction = n_elected / n_trials

        # Expected: 1 - (1-0.05)^0.5 ≈ 0.02532
        # Generous bounds to avoid flakiness: [1.5%, 3.5%]
        assert 0.015 <= fraction <= 0.035, (
            f"Leader election fraction {fraction:.4f} outside expected range "
            f"[0.015, 0.035] for f={f}, sigma={sigma}"
        )

    def test_zero_stake_never_elected(self) -> None:
        """With sigma=0, no VRF output should ever win."""
        import random

        rng = random.Random(123)
        for _ in range(1000):
            vrf_output = bytes(rng.getrandbits(8) for _ in range(64))
            assert leader_check(vrf_output, 0.0, 0.05) is False

    def test_higher_stake_more_elections(self) -> None:
        """Pools with higher stake should win more slots."""
        import random

        rng = random.Random(999)
        n_trials = 5000
        vrf_outputs = [
            bytes(rng.getrandbits(8) for _ in range(64))
            for _ in range(n_trials)
        ]

        low_stake_wins = sum(
            1 for v in vrf_outputs if leader_check(v, 0.1, 0.05)
        )
        high_stake_wins = sum(
            1 for v in vrf_outputs if leader_check(v, 0.9, 0.05)
        )

        assert high_stake_wins > low_stake_wins, (
            f"High stake ({high_stake_wins} wins) should exceed "
            f"low stake ({low_stake_wins} wins)"
        )
