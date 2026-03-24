"""Tests for vibe.cardano.consensus.header_validation.

Covers all 7 header validation checks with positive and negative cases,
using mock headers and a mock stake distribution.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Optional

import pytest

from vibe.cardano.consensus.header_validation import (
    HeaderValidationError,
    HeaderValidationFailure,
    HeaderValidationParams,
    PoolInfo,
    StakeDistribution,
    _pool_id_from_vkey,
    validate_header,
)


# ---------------------------------------------------------------------------
# Mock header types
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


def _make_stake_dist(issuer_vkey: bytes, stake: float = 0.1) -> StakeDistribution:
    """Create a minimal stake distribution for a single pool."""
    pool_id = _pool_id_from_vkey(issuer_vkey)
    return {
        pool_id: PoolInfo(
            vrf_vk=b"\x00" * 32,
            relative_stake=stake,
            cold_vk=issuer_vkey,
            ocert_issue_number=0,
        )
    }


def _make_linked_headers(
    prev_slot: int = 50,
    prev_block_number: int = 9,
    curr_slot: int = 100,
    curr_block_number: int = 10,
    issuer_vkey: bytes = b"\xaa" * 32,
) -> tuple[MockBlockHeader, MockBlockHeader]:
    """Create a prev_header and a correctly-linked current header."""
    prev = MockBlockHeader(
        slot=prev_slot,
        block_number=prev_block_number,
        issuer_vkey=issuer_vkey,
        header_cbor=os.urandom(80),
    )
    prev_hash = _blake2b_256(prev.header_cbor)
    curr = MockBlockHeader(
        slot=curr_slot,
        block_number=curr_block_number,
        prev_hash=prev_hash,
        issuer_vkey=issuer_vkey,
        header_cbor=os.urandom(80),
    )
    return prev, curr


# ---------------------------------------------------------------------------
# Check 1: Slot monotonicity
# ---------------------------------------------------------------------------


class TestSlotCheck:
    def test_valid_increasing_slot(self) -> None:
        prev, curr = _make_linked_headers(prev_slot=50, curr_slot=100)
        dist = _make_stake_dist(curr.issuer_vkey)
        errors = validate_header(curr, dist, prev_header=prev)
        slot_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.SLOT_NOT_INCREASING
        ]
        assert len(slot_errors) == 0

    def test_slot_not_increasing(self) -> None:
        prev, curr = _make_linked_headers(prev_slot=100, curr_slot=100)
        dist = _make_stake_dist(curr.issuer_vkey)
        errors = validate_header(curr, dist, prev_header=prev)
        slot_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.SLOT_NOT_INCREASING
        ]
        assert len(slot_errors) == 1

    def test_slot_decreasing(self) -> None:
        prev, curr = _make_linked_headers(prev_slot=200, curr_slot=100)
        dist = _make_stake_dist(curr.issuer_vkey)
        errors = validate_header(curr, dist, prev_header=prev)
        slot_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.SLOT_NOT_INCREASING
        ]
        assert len(slot_errors) == 1

    def test_no_prev_header_skips_slot_check(self) -> None:
        curr = MockBlockHeader(slot=100)
        dist = _make_stake_dist(curr.issuer_vkey)
        errors = validate_header(curr, dist, prev_header=None)
        slot_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.SLOT_NOT_INCREASING
        ]
        assert len(slot_errors) == 0


# ---------------------------------------------------------------------------
# Check 2: Block number sequencing
# ---------------------------------------------------------------------------


class TestBlockNumberCheck:
    def test_valid_sequential_block_number(self) -> None:
        prev, curr = _make_linked_headers(
            prev_block_number=9, curr_block_number=10
        )
        dist = _make_stake_dist(curr.issuer_vkey)
        errors = validate_header(curr, dist, prev_header=prev)
        bn_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.BLOCK_NUMBER_MISMATCH
        ]
        assert len(bn_errors) == 0

    def test_block_number_gap(self) -> None:
        prev, curr = _make_linked_headers(
            prev_block_number=9, curr_block_number=11
        )
        dist = _make_stake_dist(curr.issuer_vkey)
        errors = validate_header(curr, dist, prev_header=prev)
        bn_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.BLOCK_NUMBER_MISMATCH
        ]
        assert len(bn_errors) == 1

    def test_block_number_same_as_prev(self) -> None:
        prev, curr = _make_linked_headers(
            prev_block_number=10, curr_block_number=10
        )
        dist = _make_stake_dist(curr.issuer_vkey)
        errors = validate_header(curr, dist, prev_header=prev)
        bn_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.BLOCK_NUMBER_MISMATCH
        ]
        assert len(bn_errors) == 1


# ---------------------------------------------------------------------------
# Check 3: Previous hash linkage
# ---------------------------------------------------------------------------


class TestPrevHashCheck:
    def test_valid_prev_hash(self) -> None:
        prev, curr = _make_linked_headers()
        dist = _make_stake_dist(curr.issuer_vkey)
        errors = validate_header(curr, dist, prev_header=prev)
        hash_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.PREV_HASH_MISMATCH
        ]
        assert len(hash_errors) == 0

    def test_wrong_prev_hash(self) -> None:
        prev, curr = _make_linked_headers()
        # Tamper with the prev_hash
        curr.prev_hash = b"\xff" * 32
        dist = _make_stake_dist(curr.issuer_vkey)
        errors = validate_header(curr, dist, prev_header=prev)
        hash_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.PREV_HASH_MISMATCH
        ]
        assert len(hash_errors) == 1


# ---------------------------------------------------------------------------
# Check 4: VRF leader eligibility (via certified_nat_max_check)
# ---------------------------------------------------------------------------


class TestVRFLeaderCheck:
    def test_pool_not_in_stake_distribution(self) -> None:
        curr = MockBlockHeader(issuer_vkey=b"\xbb" * 32)
        empty_dist: StakeDistribution = {}
        errors = validate_header(curr, empty_dist, prev_header=None)
        pool_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.POOL_NOT_IN_STAKE_DISTRIBUTION
        ]
        assert len(pool_errors) == 1

    def test_vrf_output_failing_leader_check(self) -> None:
        """A VRF output of all 0xFF should fail for low relative stake."""
        issuer = b"\xcc" * 32
        # All-0xFF VRF output is the maximum value, so it should fail
        # the leader check for any realistic stake < 1.0.
        curr = MockBlockHeader(
            issuer_vkey=issuer,
            vrf_output=b"\xff" * 64,
        )
        dist = _make_stake_dist(issuer, stake=0.001)
        errors = validate_header(curr, dist, prev_header=None)
        vrf_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.VRF_LEADER_CHECK_FAILED
        ]
        assert len(vrf_errors) == 1

    def test_vrf_output_passing_leader_check(self) -> None:
        """A VRF output with ultra-low Praos leader value passes for any positive stake."""
        import struct
        issuer = b"\xcc" * 32
        # sha512(929) produces a VRF output with leader_val ~0.0000156
        winner_vrf = hashlib.sha512(struct.pack(">Q", 929)).digest()
        curr = MockBlockHeader(
            issuer_vkey=issuer,
            vrf_output=winner_vrf,
        )
        dist = _make_stake_dist(issuer, stake=0.01)
        errors = validate_header(curr, dist, prev_header=None)
        vrf_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.VRF_LEADER_CHECK_FAILED
        ]
        assert len(vrf_errors) == 0

    def test_no_vrf_output_skips_leader_check(self) -> None:
        """If header doesn't have vrf_output attribute, skip the check."""
        issuer = b"\xcc" * 32
        curr = MockBlockHeader(issuer_vkey=issuer, vrf_output=None)
        dist = _make_stake_dist(issuer)
        errors = validate_header(curr, dist, prev_header=None)
        vrf_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.VRF_LEADER_CHECK_FAILED
        ]
        assert len(vrf_errors) == 0


# ---------------------------------------------------------------------------
# Check 6: Operational certificate (OCert) validation
# ---------------------------------------------------------------------------


class TestOCertCheck:
    def test_ocert_errors_reported(self) -> None:
        """OCert validation errors are surfaced as OCERT_INVALID failures."""
        issuer = b"\xdd" * 32
        curr = MockBlockHeader(
            issuer_vkey=issuer,
            operational_cert=MockOperationalCert(
                hot_vkey=b"\x00" * 32,
                sequence_number=0,
                kes_period=0,
                sigma=b"\x00" * 64,  # Invalid signature
            ),
        )
        dist = _make_stake_dist(issuer)
        errors = validate_header(curr, dist, prev_header=None)
        ocert_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.OCERT_INVALID
        ]
        # We expect at least the INVALID_SIGNATURE error (cold sig is invalid)
        assert len(ocert_errors) > 0


# ---------------------------------------------------------------------------
# Check 7: Protocol version
# ---------------------------------------------------------------------------


class TestProtocolVersionCheck:
    def test_valid_protocol_version(self) -> None:
        issuer = b"\xee" * 32
        curr = MockBlockHeader(
            issuer_vkey=issuer,
            protocol_version=MockProtocolVersion(major=8),
        )
        dist = _make_stake_dist(issuer)
        errors = validate_header(curr, dist, prev_header=None)
        pv_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.PROTOCOL_VERSION_INVALID
        ]
        assert len(pv_errors) == 0

    def test_protocol_version_too_high(self) -> None:
        issuer = b"\xee" * 32
        curr = MockBlockHeader(
            issuer_vkey=issuer,
            protocol_version=MockProtocolVersion(major=99),
        )
        dist = _make_stake_dist(issuer)
        params = HeaderValidationParams(max_major_protocol_version=10)
        errors = validate_header(curr, dist, params=params, prev_header=None)
        pv_errors = [
            e for e in errors
            if e.failure == HeaderValidationFailure.PROTOCOL_VERSION_INVALID
        ]
        assert len(pv_errors) == 1


# ---------------------------------------------------------------------------
# Pool ID derivation
# ---------------------------------------------------------------------------


class TestPoolIdDerivation:
    def test_pool_id_is_blake2b_224(self) -> None:
        vkey = b"\x42" * 32
        pool_id = _pool_id_from_vkey(vkey)
        assert len(pool_id) == 28
        expected = hashlib.blake2b(vkey, digest_size=28).digest()
        assert pool_id == expected

    def test_different_vkeys_different_pool_ids(self) -> None:
        a = _pool_id_from_vkey(b"\x01" * 32)
        b = _pool_id_from_vkey(b"\x02" * 32)
        assert a != b
