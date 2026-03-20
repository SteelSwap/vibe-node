"""Tests for Operational Certificate (OCert) verification.

Tests cover:
    * Cold key signature verification (valid/invalid)
    * Full OCERT transition validation with all predicate failures
    * KES period bounds checking
    * Certificate counter validation
    * slot_to_kes_period helper
    * Hypothesis property tests

Spec references:
    * Shelley formal spec, Figure 16 (OCERT rule) — six predicate failures
    * Shelley delegation design spec — Operational Key Certificates
"""

from __future__ import annotations

import struct

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.crypto.kes import (
    kes_derive_vk,
    kes_keygen,
    kes_sign,
)
from vibe.cardano.crypto.ocert import (
    MAX_KES_EVOLUTIONS,
    SLOTS_PER_KES_PERIOD,
    OCertError,
    OCertFailure,
    OperationalCert,
    ocert_signed_payload,
    slot_to_kes_period,
    validate_ocert,
    verify_ocert_cold_sig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cold_keypair() -> tuple[Ed25519PrivateKey, bytes]:
    """Generate a cold key pair, returning (private_key, public_key_bytes)."""
    sk = Ed25519PrivateKey.generate()
    vk = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return sk, vk


def _make_ocert(
    cold_sk: Ed25519PrivateKey,
    kes_vk: bytes,
    cert_count: int = 0,
    kes_period_start: int = 0,
) -> OperationalCert:
    """Create a valid operational certificate signed by the cold key."""
    payload = ocert_signed_payload(kes_vk, cert_count, kes_period_start)
    cold_sig = cold_sk.sign(payload)
    return OperationalCert(
        kes_vk=kes_vk,
        cert_count=cert_count,
        kes_period_start=kes_period_start,
        cold_sig=cold_sig,
    )


def _make_full_test_data(
    kes_depth: int = 2,
    cert_count: int = 0,
    kes_period_start: int = 0,
    current_kes_period: int = 0,
) -> dict:
    """Create a complete set of test data for OCERT validation."""
    cold_sk, cold_vk = _make_cold_keypair()
    kes_sk = kes_keygen(kes_depth)
    kes_vk = kes_derive_vk(kes_sk)
    ocert = _make_ocert(cold_sk, kes_vk, cert_count, kes_period_start)

    msg = b"test block header body"
    relative_period = current_kes_period - kes_period_start
    kes_sig = kes_sign(kes_sk, relative_period, msg)

    return {
        "cold_sk": cold_sk,
        "cold_vk": cold_vk,
        "kes_sk": kes_sk,
        "kes_vk": kes_vk,
        "ocert": ocert,
        "msg": msg,
        "kes_sig": kes_sig,
        "current_kes_period": current_kes_period,
        "kes_depth": kes_depth,
    }


# ---------------------------------------------------------------------------
# OCert signed payload tests
# ---------------------------------------------------------------------------


class TestOcertSignedPayload:
    """Test the OCert signing payload construction."""

    def test_payload_length(self) -> None:
        """Payload should be 32 + 8 + 8 = 48 bytes."""
        kes_vk = b"\x00" * 32
        payload = ocert_signed_payload(kes_vk, 0, 0)
        assert len(payload) == 48

    def test_payload_structure(self) -> None:
        """Payload = kes_vk || cert_count(BE64) || kes_period(BE64)."""
        kes_vk = bytes(range(32))
        payload = ocert_signed_payload(kes_vk, 42, 100)
        assert payload[:32] == kes_vk
        assert struct.unpack(">Q", payload[32:40])[0] == 42
        assert struct.unpack(">Q", payload[40:48])[0] == 100


# ---------------------------------------------------------------------------
# Cold signature verification tests
# ---------------------------------------------------------------------------


class TestColdSigVerification:
    """Test OCert cold key signature verification."""

    def test_valid_signature(self) -> None:
        """A properly signed OCert should verify."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_vk = b"\xab" * 32
        ocert = _make_ocert(cold_sk, kes_vk, cert_count=5, kes_period_start=10)
        assert verify_ocert_cold_sig(cold_vk, ocert)

    def test_wrong_cold_key(self) -> None:
        """Verifying with wrong cold key should fail."""
        cold_sk, _ = _make_cold_keypair()
        _, wrong_vk = _make_cold_keypair()
        kes_vk = b"\xab" * 32
        ocert = _make_ocert(cold_sk, kes_vk)
        assert not verify_ocert_cold_sig(wrong_vk, ocert)

    def test_tampered_kes_vk(self) -> None:
        """Changing the KES VK after signing should invalidate."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_vk = b"\xab" * 32
        ocert = _make_ocert(cold_sk, kes_vk)
        # Tamper with the KES VK
        tampered = OperationalCert(
            kes_vk=b"\xcd" * 32,
            cert_count=ocert.cert_count,
            kes_period_start=ocert.kes_period_start,
            cold_sig=ocert.cold_sig,
        )
        assert not verify_ocert_cold_sig(cold_vk, tampered)

    def test_tampered_counter(self) -> None:
        """Changing the cert counter after signing should invalidate."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_vk = b"\xab" * 32
        ocert = _make_ocert(cold_sk, kes_vk, cert_count=5)
        tampered = OperationalCert(
            kes_vk=ocert.kes_vk,
            cert_count=6,  # changed
            kes_period_start=ocert.kes_period_start,
            cold_sig=ocert.cold_sig,
        )
        assert not verify_ocert_cold_sig(cold_vk, tampered)

    def test_tampered_kes_period(self) -> None:
        """Changing the KES period after signing should invalidate."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_vk = b"\xab" * 32
        ocert = _make_ocert(cold_sk, kes_vk, kes_period_start=10)
        tampered = OperationalCert(
            kes_vk=ocert.kes_vk,
            cert_count=ocert.cert_count,
            kes_period_start=11,  # changed
            cold_sig=ocert.cold_sig,
        )
        assert not verify_ocert_cold_sig(cold_vk, tampered)


# ---------------------------------------------------------------------------
# Full OCERT validation tests
# ---------------------------------------------------------------------------


class TestValidateOcert:
    """Test the full OCERT transition rule validation."""

    def test_valid_ocert(self) -> None:
        """A fully valid OCert should pass all checks."""
        data = _make_full_test_data(
            kes_depth=2,
            cert_count=0,
            kes_period_start=0,
            current_kes_period=0,
        )
        errors = validate_ocert(
            ocert=data["ocert"],
            cold_vk=data["cold_vk"],
            current_kes_period=data["current_kes_period"],
            current_issue_no=0,
            header_body_cbor=data["msg"],
            kes_sig=data["kes_sig"],
            max_kes_evo=4,  # depth 2 = 4 periods
            kes_depth=data["kes_depth"],
        )
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_kes_before_start(self) -> None:
        """KES period before cert start should fail."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_sk = kes_keygen(2)
        kes_vk = kes_derive_vk(kes_sk)
        ocert = _make_ocert(cold_sk, kes_vk, kes_period_start=10)

        errors = validate_ocert(
            ocert=ocert,
            cold_vk=cold_vk,
            current_kes_period=5,  # before start
            current_issue_no=0,
            header_body_cbor=b"msg",
            kes_sig=b"\x00" * 192,  # will also fail KES sig
            max_kes_evo=4,
            kes_depth=2,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.KES_BEFORE_START in failures

    def test_kes_after_end(self) -> None:
        """KES period at or after cert end should fail."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_sk = kes_keygen(2)
        kes_vk = kes_derive_vk(kes_sk)
        ocert = _make_ocert(cold_sk, kes_vk, kes_period_start=0)

        errors = validate_ocert(
            ocert=ocert,
            cold_vk=cold_vk,
            current_kes_period=4,  # at the end (max_kes_evo=4)
            current_issue_no=0,
            header_body_cbor=b"msg",
            kes_sig=b"\x00" * 192,
            max_kes_evo=4,
            kes_depth=2,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.KES_AFTER_END in failures

    def test_counter_too_small(self) -> None:
        """On-chain counter > cert counter should fail."""
        data = _make_full_test_data(
            kes_depth=2, cert_count=3, current_kes_period=0,
        )
        errors = validate_ocert(
            ocert=data["ocert"],
            cold_vk=data["cold_vk"],
            current_kes_period=0,
            current_issue_no=5,  # > cert_count of 3
            header_body_cbor=data["msg"],
            kes_sig=data["kes_sig"],
            max_kes_evo=4,
            kes_depth=2,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.COUNTER_TOO_SMALL in failures

    def test_counter_equal_is_valid(self) -> None:
        """On-chain counter == cert counter is valid (m <= n)."""
        data = _make_full_test_data(
            kes_depth=2, cert_count=5, current_kes_period=0,
        )
        errors = validate_ocert(
            ocert=data["ocert"],
            cold_vk=data["cold_vk"],
            current_kes_period=0,
            current_issue_no=5,  # == cert_count
            header_body_cbor=data["msg"],
            kes_sig=data["kes_sig"],
            max_kes_evo=4,
            kes_depth=2,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.COUNTER_TOO_SMALL not in failures

    def test_no_counter_for_key_hash(self) -> None:
        """Missing counter entry should fail."""
        data = _make_full_test_data(kes_depth=2, current_kes_period=0)
        errors = validate_ocert(
            ocert=data["ocert"],
            cold_vk=data["cold_vk"],
            current_kes_period=0,
            current_issue_no=None,  # no entry
            header_body_cbor=data["msg"],
            kes_sig=data["kes_sig"],
            max_kes_evo=4,
            kes_depth=2,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.NO_COUNTER_FOR_KEY_HASH in failures

    def test_invalid_cold_signature(self) -> None:
        """Invalid cold signature should fail."""
        data = _make_full_test_data(kes_depth=2, current_kes_period=0)
        # Create an OCert with a bad cold signature
        bad_ocert = OperationalCert(
            kes_vk=data["ocert"].kes_vk,
            cert_count=data["ocert"].cert_count,
            kes_period_start=data["ocert"].kes_period_start,
            cold_sig=b"\x00" * 64,  # invalid signature
        )
        errors = validate_ocert(
            ocert=bad_ocert,
            cold_vk=data["cold_vk"],
            current_kes_period=0,
            current_issue_no=0,
            header_body_cbor=data["msg"],
            kes_sig=data["kes_sig"],
            max_kes_evo=4,
            kes_depth=2,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.INVALID_SIGNATURE in failures

    def test_invalid_kes_signature(self) -> None:
        """Invalid KES signature should fail."""
        data = _make_full_test_data(kes_depth=2, current_kes_period=0)
        errors = validate_ocert(
            ocert=data["ocert"],
            cold_vk=data["cold_vk"],
            current_kes_period=0,
            current_issue_no=0,
            header_body_cbor=data["msg"],
            kes_sig=b"\x00" * 192,  # invalid KES sig
            max_kes_evo=4,
            kes_depth=2,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.INVALID_KES_SIGNATURE in failures

    def test_valid_at_nonzero_period(self) -> None:
        """Valid OCert at a non-zero KES period."""
        kes_depth = 2
        kes_period_start = 5
        current_kes_period = 7  # relative period = 2

        cold_sk, cold_vk = _make_cold_keypair()
        kes_sk = kes_keygen(kes_depth)
        kes_vk = kes_derive_vk(kes_sk)
        ocert = _make_ocert(
            cold_sk, kes_vk,
            cert_count=0,
            kes_period_start=kes_period_start,
        )

        msg = b"nonzero period block"
        relative_period = current_kes_period - kes_period_start
        kes_sig = kes_sign(kes_sk, relative_period, msg)

        errors = validate_ocert(
            ocert=ocert,
            cold_vk=cold_vk,
            current_kes_period=current_kes_period,
            current_issue_no=0,
            header_body_cbor=msg,
            kes_sig=kes_sig,
            max_kes_evo=4,
            kes_depth=kes_depth,
        )
        assert errors == []


# ---------------------------------------------------------------------------
# slot_to_kes_period tests
# ---------------------------------------------------------------------------


class TestSlotToKesPeriod:
    """Test the slot-to-KES-period conversion."""

    def test_zero(self) -> None:
        assert slot_to_kes_period(0) == 0

    def test_within_first_period(self) -> None:
        assert slot_to_kes_period(SLOTS_PER_KES_PERIOD - 1) == 0

    def test_second_period(self) -> None:
        assert slot_to_kes_period(SLOTS_PER_KES_PERIOD) == 1

    def test_custom_slots_per_period(self) -> None:
        assert slot_to_kes_period(100, slots_per_kes_period=50) == 2

    def test_large_slot(self) -> None:
        """Slot 10 million / 129600 = 77."""
        assert slot_to_kes_period(10_000_000) == 10_000_000 // SLOTS_PER_KES_PERIOD


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


class TestOcertHypothesis:
    """Property-based tests for OCert validation."""

    @given(
        cert_count=st.integers(min_value=0, max_value=1000),
        issue_no=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=50, deadline=10000)
    def test_counter_monotonicity(
        self, cert_count: int, issue_no: int
    ) -> None:
        """Counter check: fails iff issue_no > cert_count."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_sk = kes_keygen(1)
        kes_vk = kes_derive_vk(kes_sk)
        ocert = _make_ocert(cold_sk, kes_vk, cert_count=cert_count)

        msg = b"counter test"
        kes_sig = kes_sign(kes_sk, 0, msg)

        errors = validate_ocert(
            ocert=ocert,
            cold_vk=cold_vk,
            current_kes_period=0,
            current_issue_no=issue_no,
            header_body_cbor=msg,
            kes_sig=kes_sig,
            max_kes_evo=2,
            kes_depth=1,
        )
        failures = {e.failure for e in errors}

        if issue_no > cert_count:
            assert OCertFailure.COUNTER_TOO_SMALL in failures
        else:
            assert OCertFailure.COUNTER_TOO_SMALL not in failures

    @given(
        kes_period_start=st.integers(min_value=0, max_value=100),
        current_period=st.integers(min_value=0, max_value=200),
    )
    @settings(max_examples=50, deadline=10000)
    def test_kes_period_bounds(
        self, kes_period_start: int, current_period: int
    ) -> None:
        """KES period bounds: c_0 <= current < c_0 + max_kes_evo."""
        max_kes_evo = 2  # small for testing
        cold_sk, cold_vk = _make_cold_keypair()
        kes_sk = kes_keygen(1)
        kes_vk = kes_derive_vk(kes_sk)
        ocert = _make_ocert(
            cold_sk, kes_vk, kes_period_start=kes_period_start
        )

        errors = validate_ocert(
            ocert=ocert,
            cold_vk=cold_vk,
            current_kes_period=current_period,
            current_issue_no=0,
            header_body_cbor=b"bounds test",
            kes_sig=b"\x00" * 128,  # we only care about period checks
            max_kes_evo=max_kes_evo,
            kes_depth=1,
        )
        failures = {e.failure for e in errors}

        if current_period < kes_period_start:
            assert OCertFailure.KES_BEFORE_START in failures
        else:
            assert OCertFailure.KES_BEFORE_START not in failures

        if current_period >= kes_period_start + max_kes_evo:
            assert OCertFailure.KES_AFTER_END in failures
        else:
            assert OCertFailure.KES_AFTER_END not in failures
