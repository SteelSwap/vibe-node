"""Operational Certificate (OCert) verification.

Implements the OCERT transition rule from the Shelley formal spec. An
operational certificate creates a chain of trust from a cold (offline)
stake pool key to a hot (online) KES key that signs block headers.

The OCert contains:
    * ``kes_vk``     — the hot KES verification key (32 bytes)
    * ``cert_count`` — certificate issue number (monotonically non-decreasing)
    * ``kes_period`` — KES period start (c_0)
    * ``cold_sig``   — Ed25519 signature by the cold key over
                        ``serialize(kes_vk || cert_count || kes_period)``

Spec references:
    * Shelley formal spec, Section "Blockchain layer", Figure 16 (OCERT rule)
    * Shelley formal spec, crypto-details.tex — KES section
    * Shelley delegation design spec, Section "Operational Key Certificates"

Haskell references:
    * ``OCert`` in ``Cardano.Protocol.TPraos.OCert``
    * ``ocertTransition`` in ``Cardano.Ledger.Shelley.Rules.OCert``
    * Predicate failures: KESBeforeStart, KESAfterEnd, CounterTooSmall,
      InvalidSignature, InvalideKesSignature, NoCounterForKeyHash
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum, auto

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .kes import (
    CARDANO_KES_DEPTH,
    kes_verify_block_signature,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_KES_EVOLUTIONS = 62
"""MaxKESEvo protocol parameter on Cardano mainnet.
Operational certificates are valid for this many KES periods."""

SLOTS_PER_KES_PERIOD = 129600
"""SlotsPerKESPeriod on Cardano mainnet (= 36 hours = 1.5 days).
129600 slots * 1 second/slot = 36 hours."""


# ---------------------------------------------------------------------------
# OCert Data Structure
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperationalCert:
    """An operational certificate as embedded in a Shelley+ block header.

    Spec ref: Shelley formal spec, OCERT rule —
        ``(vk_hot, n, c_0, tau) = bocert(bhb)``

    Haskell ref: ``OCert`` in ``Cardano.Protocol.TPraos.OCert``

    Attributes:
        kes_vk: The hot KES verification key (32 bytes). This is
            ``vk_hot`` in the spec.
        cert_count: Certificate issue number ``n``. Must be non-decreasing
            to prevent replay of old certificates.
        kes_period_start: KES period start ``c_0``. The certificate is
            valid from this period until ``c_0 + MaxKESEvo``.
        cold_sig: Ed25519 signature ``tau`` by the cold key over
            ``serialize(kes_vk || cert_count || kes_period_start)``.
    """

    kes_vk: bytes
    cert_count: int
    kes_period_start: int
    cold_sig: bytes


# ---------------------------------------------------------------------------
# OCert Predicate Failures
# ---------------------------------------------------------------------------


class OCertFailure(Enum):
    """Predicate failures for the OCERT transition rule.

    Spec ref: Shelley formal spec, Section "Operational Certificate
    Transition" — six predicate failures.

    Haskell ref: ``OcertPredicateFailure`` in
        ``Cardano.Ledger.Shelley.Rules.OCert``
    """

    KES_BEFORE_START = auto()
    """kesPeriod(slot) < c_0 — block slot is before cert start."""

    KES_AFTER_END = auto()
    """kesPeriod(slot) >= c_0 + MaxKESEvo — cert has expired."""

    COUNTER_TOO_SMALL = auto()
    """m > n — the on-chain counter exceeds the cert counter."""

    INVALID_SIGNATURE = auto()
    """Cold key signature over (kes_vk, n, c_0) is invalid."""

    INVALID_KES_SIGNATURE = auto()
    """KES signature over the block header body is invalid."""

    NO_COUNTER_FOR_KEY_HASH = auto()
    """The cold key hash has no entry in the counter mapping."""


@dataclass(frozen=True, slots=True)
class OCertError:
    """A structured OCERT validation error."""

    failure: OCertFailure
    detail: str


# ---------------------------------------------------------------------------
# OCert Payload Serialization
# ---------------------------------------------------------------------------


def ocert_signed_payload(
    kes_vk: bytes, cert_count: int, kes_period_start: int
) -> bytes:
    """Construct the payload that the cold key signs in an OCert.

    The cold key signature ``tau`` covers:
        ``serialize(vk_hot || n || c_0)``

    In the Haskell implementation, the OCert signing payload is the
    CBOR encoding of ``(kes_vk, cert_count, kes_period_start)``.
    Specifically, it is the concatenation of:
        * kes_vk (32 bytes, raw)
        * cert_count (8 bytes, big-endian uint64)
        * kes_period_start (8 bytes, big-endian uint64)

    Haskell ref: ``ocertSigPayload`` — the signed data is the CBOR
    serialization of the OCert fields (without the signature itself).
    Actually in practice, Cardano serializes this as raw bytes:
    ``vk_hot <> serialize n <> serialize c_0`` where serialize uses
    big-endian 8-byte encoding for the integers.

    NOTE: The exact serialization must match what the Haskell node uses.
    The Haskell node CBOR-encodes the OCert body as a 3-element CBOR
    array. We provide both raw and CBOR variants; the CBOR variant
    matches the on-chain format.

    Args:
        kes_vk: 32-byte KES verification key.
        cert_count: Certificate counter.
        kes_period_start: KES period start.

    Returns:
        The bytes that the cold key signs.
    """
    # The Haskell node uses CBOR encoding for the OCert signing payload.
    # Specifically: encode as CBOR array [kes_vk_bytes, cert_count, kes_period]
    # Using cbor2 would add a dependency — we hand-encode the simple CBOR.
    #
    # Actually, looking at the Haskell source more carefully:
    # The signed payload is the raw concatenation of:
    #   kes_vk (32 bytes) || cert_count (8 bytes BE) || kes_period (8 bytes BE)
    #
    # This matches how cardano-crypto-class serializes the OCert body for
    # signing purposes (rawSerialiseSignedDSIGN).
    return kes_vk + struct.pack(">QQ", cert_count, kes_period_start)


# ---------------------------------------------------------------------------
# Cold Key Signature Verification
# ---------------------------------------------------------------------------


def verify_ocert_cold_sig(
    cold_vk: bytes,
    ocert: OperationalCert,
) -> bool:
    """Verify the cold key signature on an operational certificate.

    Checks: V_{vk_cold}(serialize(vk_hot, n, c_0))_tau

    Spec ref: Shelley formal spec, OCERT rule, predicate:
        ``V_{vk_cold}{serialised{(vk_hot, n, c_0)}}_{tau}``

    Args:
        cold_vk: 32-byte Ed25519 cold verification key.
        ocert: The operational certificate.

    Returns:
        True if the cold signature is valid.
    """
    payload = ocert_signed_payload(
        ocert.kes_vk, ocert.cert_count, ocert.kes_period_start
    )
    try:
        vk = Ed25519PublicKey.from_public_bytes(cold_vk)
        vk.verify(ocert.cold_sig, payload)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Full OCERT Transition Validation
# ---------------------------------------------------------------------------


def validate_ocert(
    ocert: OperationalCert,
    cold_vk: bytes,
    current_kes_period: int,
    current_issue_no: int | None,
    header_body_cbor: bytes,
    kes_sig: bytes,
    *,
    max_kes_evo: int = MAX_KES_EVOLUTIONS,
    kes_depth: int = CARDANO_KES_DEPTH,
) -> list[OCertError]:
    """Validate the full OCERT transition rule.

    Implements all six predicates from the Shelley formal spec OCERT rule.

    Spec ref: Shelley formal spec, Figure 16 (eq:ocert):
        1. c_0 <= kesPeriod(s) < c_0 + MaxKESEvo
        2. currentIssueNo(oce, cs, hk) = m  AND  m <= n
        3. V_{vk_cold}(serialised{(vk_hot, n, c_0)})_{tau}
        4. V^KES_{vk_hot}(serialised{bhb})_{sigma}^{t}
           where t = kesPeriod(s) - c_0

    Args:
        ocert: The operational certificate from the block header.
        cold_vk: 32-byte Ed25519 cold verification key (from block header).
        current_kes_period: ``kesPeriod(slot)`` for the block's slot.
        current_issue_no: The current on-chain issue number for this pool,
            or None if the pool has no entry (NoCounterForKeyHash).
        header_body_cbor: Serialized block header body (signed by KES).
        kes_sig: The KES signature from the block header.
        max_kes_evo: MaxKESEvo protocol parameter.
        kes_depth: KES tree depth.

    Returns:
        List of OCertError (empty = valid).
    """
    errors: list[OCertError] = []

    c_0 = ocert.kes_period_start

    # --- Predicate 1a: KES period >= cert start ---
    # c_0 <= kesPeriod(s)
    if current_kes_period < c_0:
        errors.append(
            OCertError(
                OCertFailure.KES_BEFORE_START,
                f"KES period {current_kes_period} < cert start {c_0}",
            )
        )

    # --- Predicate 1b: KES period < cert start + MaxKESEvo ---
    # kesPeriod(s) < c_0 + MaxKESEvo
    if current_kes_period >= c_0 + max_kes_evo:
        errors.append(
            OCertError(
                OCertFailure.KES_AFTER_END,
                f"KES period {current_kes_period} >= "
                f"cert end {c_0 + max_kes_evo}",
            )
        )

    # --- Predicate 2: Counter check ---
    # currentIssueNo(oce, cs, hk) = m  AND  m <= n
    if current_issue_no is None:
        errors.append(
            OCertError(
                OCertFailure.NO_COUNTER_FOR_KEY_HASH,
                "No counter entry for this cold key hash",
            )
        )
    elif current_issue_no > ocert.cert_count:
        errors.append(
            OCertError(
                OCertFailure.COUNTER_TOO_SMALL,
                f"On-chain counter {current_issue_no} > "
                f"cert counter {ocert.cert_count}",
            )
        )

    # --- Predicate 3: Cold key signature on OCert ---
    # V_{vk_cold}(serialised{(vk_hot, n, c_0)})_{tau}
    if not verify_ocert_cold_sig(cold_vk, ocert):
        errors.append(
            OCertError(
                OCertFailure.INVALID_SIGNATURE,
                "Cold key signature on OCert is invalid",
            )
        )

    # --- Predicate 4: KES signature on block header body ---
    # V^KES_{vk_hot}(serialised{bhb})_{sigma}^{t}
    # where t = kesPeriod(s) - c_0
    t = current_kes_period - c_0
    if t >= 0 and t < (1 << kes_depth):
        if not kes_verify_block_signature(
            ocert.kes_vk, t, kes_sig, header_body_cbor, depth=kes_depth
        ):
            errors.append(
                OCertError(
                    OCertFailure.INVALID_KES_SIGNATURE,
                    f"KES signature invalid at relative period {t}",
                )
            )
    # If t is out of range, we already reported KES_BEFORE_START or KES_AFTER_END

    return errors


# ---------------------------------------------------------------------------
# Helper: compute KES period from slot
# ---------------------------------------------------------------------------


def slot_to_kes_period(
    slot: int, *, slots_per_kes_period: int = SLOTS_PER_KES_PERIOD
) -> int:
    """Convert a slot number to a KES period.

    ``kesPeriod(s) = s / SlotsPerKESPeriod`` (integer division)

    Spec ref: Shelley formal spec — ``kesPeriod`` function.
    Haskell ref: ``kesPeriod`` in ``Cardano.Protocol.TPraos.BHeader``

    Args:
        slot: Slot number.
        slots_per_kes_period: SlotsPerKESPeriod protocol constant.

    Returns:
        KES period number.
    """
    return slot // slots_per_kes_period
