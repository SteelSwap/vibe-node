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
    SLOTS_PER_KES_PERIOD,
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
            kes_depth=2,
            cert_count=3,
            current_kes_period=0,
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
            kes_depth=2,
            cert_count=5,
            current_kes_period=0,
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
            cold_sk,
            kes_vk,
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
    def test_counter_monotonicity(self, cert_count: int, issue_no: int) -> None:
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
    def test_kes_period_bounds(self, kes_period_start: int, current_period: int) -> None:
        """KES period bounds: c_0 <= current < c_0 + max_kes_evo."""
        max_kes_evo = 2  # small for testing
        cold_sk, cold_vk = _make_cold_keypair()
        kes_sk = kes_keygen(1)
        kes_vk = kes_derive_vk(kes_sk)
        ocert = _make_ocert(cold_sk, kes_vk, kes_period_start=kes_period_start)

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


# ---------------------------------------------------------------------------
# Test 3: OCert CBOR golden test
# ---------------------------------------------------------------------------


class TestOcertCborGolden:
    """Test OCert CBOR serialization against the Haskell format.

    The Haskell OCert is serialized as a 4-element CBOR array:
        [kes_vk, cert_counter, kes_period, cold_sig]

    where kes_vk and cold_sig are CBOR bytestrings, and cert_counter
    and kes_period are CBOR unsigned integers.

    Haskell ref: toCBOR for OCert in Cardano.Protocol.TPraos.OCert —
        encodeListLen 4
        <> toCBOR vk_hot
        <> toCBOR n
        <> toCBOR c_0
        <> toCBOR tau
    """

    def test_ocert_cbor_golden_known_values(self) -> None:
        """Serialize an OCert with known values and verify exact CBOR bytes."""
        import cbor2

        # Use deterministic known values
        kes_vk = bytes(range(32))  # 0x00..0x1f
        cert_count = 42
        kes_period = 100
        cold_sig = bytes(range(64, 128))  # 0x40..0x7f

        # Encode as Haskell-format CBOR array: [kes_vk, n, c_0, tau]
        ocert_cbor = cbor2.dumps([kes_vk, cert_count, kes_period, cold_sig])

        # Decode and verify structure
        decoded = cbor2.loads(ocert_cbor)
        assert isinstance(decoded, list)
        assert len(decoded) == 4
        assert decoded[0] == kes_vk
        assert decoded[1] == cert_count
        assert decoded[2] == kes_period
        assert decoded[3] == cold_sig

    def test_ocert_cbor_golden_exact_bytes(self) -> None:
        """Verify the exact CBOR encoding of a known OCert.

        CBOR encoding of [h'0000...00' (32 bytes), 0, 0, h'0000...00' (64 bytes)]:
          84                 -- array(4)
          5820               -- bytes(32)
          00*32              -- 32 zero bytes
          00                 -- unsigned(0)
          00                 -- unsigned(0)
          5840               -- bytes(64)
          00*64              -- 64 zero bytes
        """
        import cbor2

        kes_vk = b"\x00" * 32
        cert_count = 0
        kes_period = 0
        cold_sig = b"\x00" * 64

        ocert_cbor = cbor2.dumps([kes_vk, cert_count, kes_period, cold_sig])

        # Verify the CBOR structure byte by byte
        assert ocert_cbor[0] == 0x84  # array(4)
        assert ocert_cbor[1] == 0x58  # bytes, 1-byte length follows
        assert ocert_cbor[2] == 32  # length = 32
        assert ocert_cbor[3:35] == b"\x00" * 32  # kes_vk
        assert ocert_cbor[35] == 0x00  # unsigned(0) = cert_count
        assert ocert_cbor[36] == 0x00  # unsigned(0) = kes_period
        assert ocert_cbor[37] == 0x58  # bytes, 1-byte length follows
        assert ocert_cbor[38] == 64  # length = 64
        assert ocert_cbor[39:103] == b"\x00" * 64  # cold_sig
        assert len(ocert_cbor) == 103

    def test_ocert_cbor_roundtrip_with_real_sig(self) -> None:
        """Create a real OCert and verify CBOR round-trip preserves all fields."""
        import cbor2

        cold_sk, cold_vk = _make_cold_keypair()
        kes_sk = kes_keygen(2)
        kes_vk = kes_derive_vk(kes_sk)
        ocert = _make_ocert(cold_sk, kes_vk, cert_count=7, kes_period_start=15)

        # Serialize in Haskell format
        ocert_cbor = cbor2.dumps(
            [
                ocert.kes_vk,
                ocert.cert_count,
                ocert.kes_period_start,
                ocert.cold_sig,
            ]
        )

        # Deserialize and reconstruct
        decoded = cbor2.loads(ocert_cbor)
        reconstructed = OperationalCert(
            kes_vk=decoded[0],
            cert_count=decoded[1],
            kes_period_start=decoded[2],
            cold_sig=decoded[3],
        )

        # Verify the reconstructed OCert matches the original
        assert reconstructed.kes_vk == ocert.kes_vk
        assert reconstructed.cert_count == ocert.cert_count
        assert reconstructed.kes_period_start == ocert.kes_period_start
        assert reconstructed.cold_sig == ocert.cold_sig

        # And the cold signature still verifies
        assert verify_ocert_cold_sig(cold_vk, reconstructed)


# ---------------------------------------------------------------------------
# Test 4: OCert counter increment across blocks
# ---------------------------------------------------------------------------


class TestOcertCounterSequence:
    """Simulate a sequence of blocks from the same pool where the OCert
    counter must be non-decreasing.

    The OCERT rule requires: m <= n, where m is the on-chain counter and
    n is the cert's counter. When a new cert is issued, the on-chain
    counter updates to max(m, n).

    Spec ref: Shelley formal spec, Figure 16 (OCERT rule), predicate:
        currentIssueNo(oce, cs, hk) = m AND m <= n

    Haskell ref: ocertTransition in Cardano.Ledger.Shelley.Rules.OCert
    """

    def test_incrementing_counters_accepted(self) -> None:
        """A sequence of OCerts with increasing counters should all validate."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_depth = 2
        kes_sk = kes_keygen(kes_depth)
        kes_vk = kes_derive_vk(kes_sk)

        on_chain_counter = 0

        for cert_count in [0, 1, 2, 5, 10]:
            ocert = _make_ocert(
                cold_sk,
                kes_vk,
                cert_count=cert_count,
                kes_period_start=0,
            )
            msg = f"block with counter {cert_count}".encode()
            kes_sig = kes_sign(kes_sk, 0, msg)

            errors = validate_ocert(
                ocert=ocert,
                cold_vk=cold_vk,
                current_kes_period=0,
                current_issue_no=on_chain_counter,
                header_body_cbor=msg,
                kes_sig=kes_sig,
                max_kes_evo=4,
                kes_depth=kes_depth,
            )
            failures = {e.failure for e in errors}
            assert OCertFailure.COUNTER_TOO_SMALL not in failures, (
                f"Counter {cert_count} rejected with on-chain {on_chain_counter}"
            )

            # Simulate on-chain counter update: max(m, n)
            on_chain_counter = max(on_chain_counter, cert_count)

    def test_decremented_counter_rejected(self) -> None:
        """An OCert with counter lower than on-chain should be rejected."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_depth = 2
        kes_sk = kes_keygen(kes_depth)
        kes_vk = kes_derive_vk(kes_sk)

        # Simulate: on-chain counter is 5, new cert says 3
        ocert = _make_ocert(
            cold_sk,
            kes_vk,
            cert_count=3,
            kes_period_start=0,
        )
        msg = b"block with stale counter"
        kes_sig = kes_sign(kes_sk, 0, msg)

        errors = validate_ocert(
            ocert=ocert,
            cold_vk=cold_vk,
            current_kes_period=0,
            current_issue_no=5,  # on-chain > cert counter
            header_body_cbor=msg,
            kes_sig=kes_sig,
            max_kes_evo=4,
            kes_depth=kes_depth,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.COUNTER_TOO_SMALL in failures

    def test_equal_counter_accepted(self) -> None:
        """An OCert with counter equal to on-chain should be accepted."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_depth = 2
        kes_sk = kes_keygen(kes_depth)
        kes_vk = kes_derive_vk(kes_sk)

        ocert = _make_ocert(
            cold_sk,
            kes_vk,
            cert_count=5,
            kes_period_start=0,
        )
        msg = b"block with equal counter"
        kes_sig = kes_sign(kes_sk, 0, msg)

        errors = validate_ocert(
            ocert=ocert,
            cold_vk=cold_vk,
            current_kes_period=0,
            current_issue_no=5,  # equal to cert counter
            header_body_cbor=msg,
            kes_sig=kes_sig,
            max_kes_evo=4,
            kes_depth=kes_depth,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.COUNTER_TOO_SMALL not in failures

    def test_counter_sequence_with_gaps(self) -> None:
        """Non-contiguous counter increments (0, 3, 7, 100) should all pass.

        The spec only requires m <= n, not n == m + 1.
        """
        cold_sk, cold_vk = _make_cold_keypair()
        kes_depth = 2
        kes_sk = kes_keygen(kes_depth)
        kes_vk = kes_derive_vk(kes_sk)

        on_chain_counter = 0
        for cert_count in [0, 3, 7, 100]:
            ocert = _make_ocert(
                cold_sk,
                kes_vk,
                cert_count=cert_count,
                kes_period_start=0,
            )
            msg = f"gap-counter-{cert_count}".encode()
            kes_sig = kes_sign(kes_sk, 0, msg)

            errors = validate_ocert(
                ocert=ocert,
                cold_vk=cold_vk,
                current_kes_period=0,
                current_issue_no=on_chain_counter,
                header_body_cbor=msg,
                kes_sig=kes_sig,
                max_kes_evo=4,
                kes_depth=kes_depth,
            )
            failures = {e.failure for e in errors}
            assert OCertFailure.COUNTER_TOO_SMALL not in failures
            on_chain_counter = max(on_chain_counter, cert_count)

    def test_replay_old_counter_after_increment(self) -> None:
        """After counter advances to 5, replaying counter=2 fails."""
        cold_sk, cold_vk = _make_cold_keypair()
        kes_depth = 2
        kes_sk = kes_keygen(kes_depth)
        kes_vk = kes_derive_vk(kes_sk)

        # First: valid cert with counter 5
        ocert5 = _make_ocert(cold_sk, kes_vk, cert_count=5, kes_period_start=0)
        msg = b"valid block"
        kes_sig = kes_sign(kes_sk, 0, msg)

        errors = validate_ocert(
            ocert=ocert5,
            cold_vk=cold_vk,
            current_kes_period=0,
            current_issue_no=0,
            header_body_cbor=msg,
            kes_sig=kes_sig,
            max_kes_evo=4,
            kes_depth=kes_depth,
        )
        assert not any(e.failure == OCertFailure.COUNTER_TOO_SMALL for e in errors)

        # Now on-chain counter is 5. Replay counter=2 should fail.
        ocert2 = _make_ocert(cold_sk, kes_vk, cert_count=2, kes_period_start=0)
        msg2 = b"replay block"
        kes_sig2 = kes_sign(kes_sk, 0, msg2)

        errors = validate_ocert(
            ocert=ocert2,
            cold_vk=cold_vk,
            current_kes_period=0,
            current_issue_no=5,
            header_body_cbor=msg2,
            kes_sig=kes_sig2,
            max_kes_evo=4,
            kes_depth=kes_depth,
        )
        failures = {e.failure for e in errors}
        assert OCertFailure.COUNTER_TOO_SMALL in failures
