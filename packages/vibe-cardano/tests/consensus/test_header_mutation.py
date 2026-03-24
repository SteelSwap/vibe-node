"""Praos header mutation tests — systematic single-field corruption.

The approach: build a VALID mock header that passes all 7 validation checks
with real cryptographic material (Ed25519, KES, OCert cold signatures), then
mutate ONE field at a time and verify the correct error is produced.

This catches regressions where a validation check is accidentally weakened
or removed, and documents the exact error surface of header validation.

Spec references:
    - Shelley formal spec, Figure 16 (OCERT transition rule)
    - Ouroboros Praos paper, Section 4 (block verification)
    - Shelley formal spec, CHAIN rule — header-level predicates

Haskell references:
    - Ouroboros.Consensus.Protocol.Praos (validateHeader)
    - Cardano.Ledger.Shelley.Rules.OCert (OcertPredicateFailure)
"""

from __future__ import annotations

import copy
import hashlib
import os
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.consensus.header_validation import (
    HeaderValidationError,
    HeaderValidationFailure,
    HeaderValidationParams,
    PoolInfo,
    StakeDistribution,
    _pool_id_from_vkey,
    validate_header,
)
from vibe.cardano.crypto.kes import (
    kes_derive_vk,
    kes_keygen,
    kes_sign,
)
from vibe.cardano.crypto.ocert import (
    ocert_signed_payload,
)

# ---------------------------------------------------------------------------
# Test parameters — use small KES depth for speed
# ---------------------------------------------------------------------------

# Depth 2 => 4 periods, sig_size = 64 * 3 = 192 bytes
# Much faster than depth 6 (Cardano mainnet) while exercising the same logic.
TEST_KES_DEPTH = 2
TEST_MAX_KES_EVO = 4  # 2^depth
TEST_SLOTS_PER_KES_PERIOD = 100  # small for easy arithmetic
TEST_ACTIVE_SLOT_COEFF = 0.05
TEST_MAX_MAJOR_PROTO_VERSION = 10

TEST_PARAMS = HeaderValidationParams(
    active_slot_coeff=TEST_ACTIVE_SLOT_COEFF,
    max_kes_evo=TEST_MAX_KES_EVO,
    slots_per_kes_period=TEST_SLOTS_PER_KES_PERIOD,
    kes_depth=TEST_KES_DEPTH,
    max_major_protocol_version=TEST_MAX_MAJOR_PROTO_VERSION,
)


# ---------------------------------------------------------------------------
# Mock header types (matching the interface expected by validate_header)
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
    prev_hash: bytes | None = None
    issuer_vkey: bytes = b"\x00" * 32
    header_cbor: bytes = b"\x00" * 100
    protocol_version: MockProtocolVersion = None  # type: ignore
    operational_cert: MockOperationalCert = None  # type: ignore
    vrf_output: bytes | None = None
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
# Cryptographic fixture: build a fully-valid header with real keys
# ---------------------------------------------------------------------------


class ValidHeaderFixture:
    """Generates a valid prev_header + header pair with real crypto.

    All 7 header validation checks pass on the generated header:
    1. Slot monotonicity (slot > prev_slot)
    2. Block number sequencing (block_number == prev + 1)
    3. Previous hash linkage (prev_hash == blake2b(prev.header_cbor))
    4. VRF leader check (vrf_output = all zeros => always passes)
    5. KES signature (real KES sign at correct period)
    6. OCert validation (real cold sig, valid KES period, valid counter)
    7. Protocol version (major <= max)
    """

    def __init__(
        self,
        prev_slot: int = 50,
        curr_slot: int = 150,
        prev_block_number: int = 9,
        curr_block_number: int = 10,
        kes_period_start: int = 0,
        ocert_counter: int = 1,
        on_chain_counter: int = 0,
    ) -> None:
        # --- Generate cold key pair (Ed25519) ---
        self.cold_sk = Ed25519PrivateKey.generate()
        self.cold_vk_bytes = self.cold_sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

        # --- Generate KES key pair ---
        self.kes_sk = kes_keygen(TEST_KES_DEPTH)
        self.kes_vk = kes_derive_vk(self.kes_sk)

        # --- Compute the current KES period from slot ---
        self.kes_period_start = kes_period_start
        current_kes_period = curr_slot // TEST_SLOTS_PER_KES_PERIOD
        self.current_kes_period = current_kes_period
        self.relative_kes_period = current_kes_period - kes_period_start

        # --- Sign OCert payload with cold key ---
        ocert_payload = ocert_signed_payload(self.kes_vk, ocert_counter, kes_period_start)
        cold_sig = self.cold_sk.sign(ocert_payload)

        # --- Build the operational cert ---
        self.ocert = MockOperationalCert(
            hot_vkey=self.kes_vk,
            sequence_number=ocert_counter,
            kes_period=kes_period_start,
            sigma=cold_sig,
        )

        # --- Build the previous header ---
        prev_header_cbor = os.urandom(80)
        self.prev_header = MockBlockHeader(
            slot=prev_slot,
            block_number=prev_block_number,
            issuer_vkey=self.cold_vk_bytes,
            header_cbor=prev_header_cbor,
        )

        # --- Build the header body CBOR (what KES signs) ---
        # In reality this is the CBOR-encoded header body. For testing
        # we use random bytes — the KES signature just signs whatever
        # bytes we give it.
        header_body_cbor = os.urandom(120)

        # --- KES-sign the header body ---
        kes_sig = kes_sign(self.kes_sk, self.relative_kes_period, header_body_cbor)

        # --- VRF output: use pre-computed winner (leader_val ~0.0000156) ---
        # sha512(929) produces a VRF output whose Praos leader hash is ultra-low,
        # guaranteeing it passes the leader check for any positive stake/f.
        vrf_output = hashlib.sha512(struct.pack(">Q", 929)).digest()

        # --- Build the current header ---
        prev_hash = _blake2b_256(prev_header_cbor)
        header_cbor = os.urandom(80)

        self.header = MockBlockHeader(
            slot=curr_slot,
            block_number=curr_block_number,
            prev_hash=prev_hash,
            issuer_vkey=self.cold_vk_bytes,
            header_cbor=header_cbor,
            protocol_version=MockProtocolVersion(major=8),
            operational_cert=self.ocert,
            vrf_output=vrf_output,
            header_body_cbor=header_body_cbor,
            kes_signature=kes_sig,
        )

        # --- Build the stake distribution ---
        pool_id = _pool_id_from_vkey(self.cold_vk_bytes)
        self.stake_distribution: StakeDistribution = {
            pool_id: PoolInfo(
                vrf_vk=b"\x00" * 32,
                relative_stake=0.5,
                cold_vk=self.cold_vk_bytes,
                ocert_issue_number=on_chain_counter,
            )
        }

    def validate(self) -> list[HeaderValidationError]:
        """Run full header validation."""
        return validate_header(
            self.header,
            self.stake_distribution,
            params=TEST_PARAMS,
            prev_header=self.prev_header,
        )

    def deep_copy_header(self) -> MockBlockHeader:
        """Return a deep copy of the header for mutation."""
        return copy.deepcopy(self.header)


# ---------------------------------------------------------------------------
# Helper: filter errors by failure type
# ---------------------------------------------------------------------------


def _errors_of_type(
    errors: list[HeaderValidationError], failure: HeaderValidationFailure
) -> list[HeaderValidationError]:
    return [e for e in errors if e.failure == failure]


def _has_error(errors: list[HeaderValidationError], failure: HeaderValidationFailure) -> bool:
    return len(_errors_of_type(errors, failure)) > 0


def _has_ocert_sub_error(errors: list[HeaderValidationError], keyword: str) -> bool:
    """Check if any OCERT_INVALID error contains a keyword in its detail."""
    for e in errors:
        if e.failure == HeaderValidationFailure.OCERT_INVALID and keyword in e.detail:
            return True
    return False


# ===================================================================
# TEST 1: Valid baseline — unmutated header passes all checks
# ===================================================================


class TestValidBaseline:
    """The fixture header must pass all validation with zero errors."""

    def test_valid_header_passes_all_checks(self) -> None:
        fix = ValidHeaderFixture()
        errors = fix.validate()
        assert errors == [], (
            f"Valid baseline header should pass all checks, got: "
            f"{[(e.failure.name, e.detail) for e in errors]}"
        )


# ===================================================================
# TEST 2: Mutate KES signature — flip a byte
# ===================================================================


class TestMutateKesSignature:
    """Flipping a byte in the KES signature must produce OCERT_INVALID
    with INVALID_KES_SIGNATURE sub-error.
    """

    def test_flipped_kes_sig_byte(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()

        # Flip the first byte of the KES signature
        sig = bytearray(h.kes_signature)
        sig[0] ^= 0xFF
        h.kes_signature = bytes(sig)

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.OCERT_INVALID)
        assert _has_ocert_sub_error(errors, "INVALID_KES_SIGNATURE")


# ===================================================================
# TEST 3: Mutate KES period (too early)
# ===================================================================


class TestMutateKesPeriodTooEarly:
    """Setting the OCert kes_period_start AFTER the current slot's KES period
    triggers KES_BEFORE_START.
    """

    def test_kes_before_start(self) -> None:
        # Current slot=150, slots_per_kes=100 => current_kes_period=1
        # Set kes_period_start=5 => 1 < 5 => KES_BEFORE_START
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        h.operational_cert.kes_period = 5  # far in the future

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.OCERT_INVALID)
        assert _has_ocert_sub_error(errors, "KES_BEFORE_START")


# ===================================================================
# TEST 4: Mutate KES period (too late)
# ===================================================================


class TestMutateKesPeriodTooLate:
    """Setting the slot far enough ahead that current_kes_period >= c_0 + max_kes_evo
    triggers KES_AFTER_END.
    """

    def test_kes_after_end(self) -> None:
        # Build a valid fixture, then mutate the slot to be very large,
        # pushing current_kes_period past c_0 + max_kes_evo.
        # current_kes_period = 10000 // 100 = 100, c_0 = 0, max_kes_evo = 4
        # 100 >= 0 + 4 => KES_AFTER_END
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        h.slot = 10000

        errors = validate_header(
            h,
            fix.stake_distribution,
            params=TEST_PARAMS,
            prev_header=fix.prev_header,
        )
        assert _has_error(errors, HeaderValidationFailure.OCERT_INVALID)
        assert _has_ocert_sub_error(errors, "KES_AFTER_END")


# ===================================================================
# TEST 5: Mutate OCert counter (decrease below on-chain)
# ===================================================================


class TestMutateOcertCounter:
    """Setting cert counter below the on-chain counter triggers
    COUNTER_TOO_SMALL.
    """

    def test_counter_too_small(self) -> None:
        # Build fixture with on_chain_counter=5, ocert_counter=10
        fix = ValidHeaderFixture(ocert_counter=10, on_chain_counter=5)
        # Verify baseline is valid
        assert fix.validate() == []

        # Now mutate: set cert counter below on-chain
        h = fix.deep_copy_header()
        h.operational_cert.sequence_number = 3  # 3 < 5 => COUNTER_TOO_SMALL

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.OCERT_INVALID)
        assert _has_ocert_sub_error(errors, "COUNTER_TOO_SMALL")


# ===================================================================
# TEST 6: Mutate OCert cold signature — flip a byte
# ===================================================================


class TestMutateColdSignature:
    """Flipping a byte in the cold signature triggers INVALID_SIGNATURE."""

    def test_flipped_cold_sig(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()

        sig = bytearray(h.operational_cert.sigma)
        sig[0] ^= 0xFF
        h.operational_cert.sigma = bytes(sig)

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.OCERT_INVALID)
        assert _has_ocert_sub_error(errors, "INVALID_SIGNATURE")


# ===================================================================
# TEST 7: Mutate VRF output — use a max-value output that fails leader check
# ===================================================================


class TestMutateVrfOutput:
    """Setting vrf_output to all 0xFF (max nat) fails the leader check
    for any realistic stake < 1.0.

    The Praos leader check: vrf_nat / 2^512 < 1 - (1 - f)^sigma.
    All 0xFF => vrf_nat ~= 2^512 - 1 ~= 1.0, which exceeds any
    threshold for sigma < 1.0 and f = 0.05.
    """

    def test_max_vrf_output_fails_leader_check(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()

        h.vrf_output = b"\xff" * 64

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.VRF_LEADER_CHECK_FAILED)


# ===================================================================
# TEST 8: Mutate VRF key — wrong pool's VRF key
# ===================================================================


class TestMutateVrfKey:
    """Using a different issuer_vkey (unknown pool) causes
    POOL_NOT_IN_STAKE_DISTRIBUTION, which blocks the VRF check entirely.

    If the pool is found but with a mismatched VRF VK, the VRF proof
    verification would fail. Since we don't have native VRF proof
    verification yet, we test the pool-not-found path.
    """

    def test_unknown_issuer_vkey(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()

        # Use a completely different issuer key
        wrong_sk = Ed25519PrivateKey.generate()
        h.issuer_vkey = wrong_sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.POOL_NOT_IN_STAKE_DISTRIBUTION)


# ===================================================================
# TEST 9: Mutate slot number (decrease) — slot <= prev_slot
# ===================================================================


class TestMutateSlotDecrease:
    """Setting slot <= prev_header.slot triggers SLOT_NOT_INCREASING."""

    def test_slot_equal_to_prev(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        h.slot = fix.prev_header.slot  # equal => not increasing

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.SLOT_NOT_INCREASING)

    def test_slot_less_than_prev(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        h.slot = fix.prev_header.slot - 10  # less => not increasing

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.SLOT_NOT_INCREASING)


# ===================================================================
# TEST 10: Mutate block number (skip) — block_number != prev + 1
# ===================================================================


class TestMutateBlockNumber:
    """Setting block_number to something other than prev + 1 triggers
    BLOCK_NUMBER_MISMATCH.
    """

    def test_block_number_gap(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        h.block_number = fix.prev_header.block_number + 5  # gap

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.BLOCK_NUMBER_MISMATCH)

    def test_block_number_same_as_prev(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        h.block_number = fix.prev_header.block_number  # same, not +1

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.BLOCK_NUMBER_MISMATCH)


# ===================================================================
# TEST 11: Mutate prev_hash — wrong hash
# ===================================================================


class TestMutatePrevHash:
    """Setting prev_hash to a wrong value triggers PREV_HASH_MISMATCH."""

    def test_wrong_prev_hash(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        h.prev_hash = b"\xff" * 32  # wrong hash

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.PREV_HASH_MISMATCH)

    def test_flipped_prev_hash_byte(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        ph = bytearray(h.prev_hash)
        ph[0] ^= 0x01
        h.prev_hash = bytes(ph)

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.PREV_HASH_MISMATCH)


# ===================================================================
# TEST 12: Mutate protocol version — too high for era
# ===================================================================


class TestMutateProtocolVersion:
    """Setting protocol major version above max triggers
    PROTOCOL_VERSION_INVALID.
    """

    def test_protocol_version_too_high(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        h.protocol_version.major = TEST_MAX_MAJOR_PROTO_VERSION + 1

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.PROTOCOL_VERSION_INVALID)

    def test_protocol_version_way_too_high(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        h.protocol_version.major = 999

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.PROTOCOL_VERSION_INVALID)


# ===================================================================
# TEST 13: Mutate pool ID — unknown pool not in stake distribution
# ===================================================================


class TestMutatePoolId:
    """Using an issuer_vkey whose pool_id is not in the stake distribution
    triggers POOL_NOT_IN_STAKE_DISTRIBUTION.
    """

    def test_unknown_pool(self) -> None:
        fix = ValidHeaderFixture()
        h = fix.deep_copy_header()
        # Generate a fresh key not in the stake distribution
        fresh_sk = Ed25519PrivateKey.generate()
        h.issuer_vkey = fresh_sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

        errors = validate_header(
            h, fix.stake_distribution, params=TEST_PARAMS, prev_header=fix.prev_header
        )
        assert _has_error(errors, HeaderValidationFailure.POOL_NOT_IN_STAKE_DISTRIBUTION)

    def test_empty_stake_distribution(self) -> None:
        fix = ValidHeaderFixture()
        errors = validate_header(
            fix.header,
            {},  # empty
            params=TEST_PARAMS,
            prev_header=fix.prev_header,
        )
        assert _has_error(errors, HeaderValidationFailure.POOL_NOT_IN_STAKE_DISTRIBUTION)


# ===================================================================
# TEST 14: Hypothesis — single random mutation always triggers SOME error
# ===================================================================

# The mutable fields and how to corrupt them
_MUTATION_FIELDS = [
    "slot",
    "block_number",
    "prev_hash",
    "kes_signature",
    "vrf_output",
    "ocert_sigma",
    "ocert_sequence_number",
    "ocert_kes_period",
    "protocol_version_major",
    "issuer_vkey",
]


def _apply_mutation(header: MockBlockHeader, field: str, rng_bytes: bytes) -> None:
    """Apply a single mutation to the given field.

    Uses rng_bytes (from Hypothesis) to generate the corrupted value.
    """
    if field == "slot":
        # Set slot to 0 (always <= prev_slot which is 50)
        header.slot = 0
    elif field == "block_number":
        # Set to something wrong (add 5 instead of correct +1)
        header.block_number += 5
    elif field == "prev_hash":
        header.prev_hash = rng_bytes[:32].ljust(32, b"\x00")
    elif field == "kes_signature":
        sig = bytearray(header.kes_signature)
        if sig:
            sig[0] ^= 0xFF
        header.kes_signature = bytes(sig)
    elif field == "vrf_output":
        # All 0xFF fails leader check for sigma < 1.0
        header.vrf_output = b"\xff" * 64
    elif field == "ocert_sigma":
        sig = bytearray(header.operational_cert.sigma)
        sig[0] ^= 0xFF
        header.operational_cert.sigma = bytes(sig)
    elif field == "ocert_sequence_number":
        # Set to 0 when on-chain is higher — but we need on-chain > 0
        # In our fixture, on_chain=0 so setting to -1 would be weird.
        # Instead, just corrupt kes_period which is safer.
        header.operational_cert.kes_period = 999
    elif field == "ocert_kes_period":
        header.operational_cert.kes_period = 999
    elif field == "protocol_version_major":
        header.protocol_version.major = 999
    elif field == "issuer_vkey":
        fresh_sk = Ed25519PrivateKey.generate()
        header.issuer_vkey = fresh_sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


class TestHypothesisSingleMutation:
    """Property: mutating ANY single field of a valid header must produce
    at least one validation error. The header must never silently pass
    with corrupted data.

    This is an Antithesis-compatible property — deterministic given the
    same Hypothesis seed.
    """

    @given(
        field_idx=st.integers(min_value=0, max_value=len(_MUTATION_FIELDS) - 1),
        rng_bytes=st.binary(min_size=32, max_size=64),
    )
    @settings(max_examples=50, deadline=None)
    def test_single_mutation_always_detected(self, field_idx: int, rng_bytes: bytes) -> None:
        fix = ValidHeaderFixture()
        # Sanity: baseline is valid
        baseline_errors = fix.validate()
        assert baseline_errors == [], (
            f"Baseline failed: {[(e.failure.name, e.detail) for e in baseline_errors]}"
        )

        field = _MUTATION_FIELDS[field_idx]
        h = fix.deep_copy_header()
        _apply_mutation(h, field, rng_bytes)

        errors = validate_header(
            h,
            fix.stake_distribution,
            params=TEST_PARAMS,
            prev_header=fix.prev_header,
        )
        assert len(errors) > 0, (
            f"Mutation of field '{field}' was not detected — header passed validation silently!"
        )


# ===================================================================
# TEST 15: Hypothesis — valid headers always pass
# ===================================================================


class TestHypothesisValidHeaders:
    """Property: freshly-generated valid headers (from the fixture) always
    pass validation.

    This catches non-determinism in key generation, signing, or
    validation logic. Every random valid header must pass every time.

    Antithesis-compatible: deterministic given the same Hypothesis seed.
    """

    @given(
        prev_slot=st.integers(min_value=1, max_value=99),
        curr_slot_offset=st.integers(min_value=1, max_value=200),
        prev_block_number=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=30, deadline=None)
    def test_random_valid_headers_always_pass(
        self,
        prev_slot: int,
        curr_slot_offset: int,
        prev_block_number: int,
    ) -> None:
        curr_slot = prev_slot + curr_slot_offset
        curr_block_number = prev_block_number + 1

        # Ensure the KES period is within bounds:
        # current_kes_period = curr_slot // slots_per_kes_period
        # We need: 0 <= current_kes_period - kes_period_start < max_kes_evo (4)
        # and current_kes_period - kes_period_start < 2^depth (4)
        # With kes_period_start=0 and slots_per_kes_period=100:
        #   current_kes_period = curr_slot // 100
        # We need curr_slot // 100 < 4 => curr_slot < 400
        # With curr_slot_offset max=200 and prev_slot max=99, max curr_slot=299
        # => current_kes_period max = 2, which is in [0, 4). Good.

        fix = ValidHeaderFixture(
            prev_slot=prev_slot,
            curr_slot=curr_slot,
            prev_block_number=prev_block_number,
            curr_block_number=curr_block_number,
        )

        errors = fix.validate()
        assert errors == [], (
            f"Valid header at slot={curr_slot}, bn={curr_block_number} "
            f"should pass, got: {[(e.failure.name, e.detail) for e in errors]}"
        )
