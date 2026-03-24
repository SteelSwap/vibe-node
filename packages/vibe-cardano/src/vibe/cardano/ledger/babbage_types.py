"""Babbage-era types: inline datums, reference scripts, collateral return.

Babbage extends Alonzo with:
    - Inline datums: outputs can contain full datum data, not just hashes
    - Reference scripts: outputs can contain scripts for reference (not spending)
    - Reference inputs: UTxOs read but not consumed
    - Collateral return: excess collateral returned to a specified output
    - Total collateral: explicit total collateral amount in tx body
    - coinsPerUTxOByte: replaces coinsPerUTxOWord for min UTxO calculation

Spec references:
    * Babbage ledger formal spec, Section 3 (Transactions)
    * Babbage ledger formal spec, Section 4 (UTxO output format)
    * ``cardano-ledger/eras/babbage/impl/src/Cardano/Ledger/Babbage/TxBody.hs``
    * ``cardano-ledger/eras/babbage/impl/src/Cardano/Ledger/Babbage/PParams.hs``

Haskell references:
    * ``BabbageTxOut`` in ``Cardano.Ledger.Babbage.TxOut``
    * ``BabbageEraPParams`` in ``Cardano.Ledger.Babbage.PParams``
    * ``BabbageTxBody`` in ``Cardano.Ledger.Babbage.TxBody``
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from vibe.cardano.ledger.alonzo_types import AlonzoProtocolParams

# ---------------------------------------------------------------------------
# Datum option — inline datum vs datum hash
# ---------------------------------------------------------------------------


class DatumOptionTag(IntEnum):
    """Tag for the datum option in a Babbage-era output.

    Spec ref: Babbage formal spec, ``DatumOption``.
    Haskell ref: ``Datum`` in ``Cardano.Ledger.Babbage.TxOut``

    CBOR encoding:
        [0, datum_hash]  — datum hash only (Alonzo-compatible)
        [1, datum]       — inline datum (full datum embedded in output)
    """

    HASH = 0
    """Datum hash only (32-byte Blake2b-256 hash)."""

    INLINE = 1
    """Inline datum: full Plutus data embedded in the output."""


@dataclass(frozen=True, slots=True)
class DatumOption:
    """Babbage-era datum option for a transaction output.

    In Babbage, outputs can contain either a datum hash (Alonzo-style)
    or a full inline datum. The tag distinguishes the two cases.

    Spec ref: Babbage formal spec, ``DatumOption``.
    Haskell ref: ``Datum`` in ``Cardano.Ledger.Babbage.TxOut``
    """

    tag: DatumOptionTag
    """Whether this is a hash or inline datum."""

    data: bytes
    """For HASH: 32-byte datum hash. For INLINE: CBOR-encoded Plutus data."""


# ---------------------------------------------------------------------------
# Reference script
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReferenceScript:
    """A script stored in a UTxO output for reference.

    Babbage allows outputs to carry scripts that other transactions can
    reference without including the script in their witness set.

    Spec ref: Babbage formal spec, ``Script`` in output format.
    Haskell ref: ``referenceScript`` field in ``BabbageTxOut``
    """

    script_bytes: bytes
    """CBOR-encoded script (native or Plutus)."""

    script_hash: bytes
    """28-byte Blake2b-224 hash of the script."""


# ---------------------------------------------------------------------------
# Babbage transaction output
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BabbageOutputExtension:
    """Babbage-specific extensions to a transaction output.

    These fields augment pycardano's TransactionOutput with Babbage features.
    We use this as a sidecar rather than replacing the pycardano type.

    Spec ref: Babbage formal spec, output format:
        [address, value, datum_option, script_ref]
    Haskell ref: ``BabbageTxOut`` in ``Cardano.Ledger.Babbage.TxOut``
    """

    datum_option: DatumOption | None = None
    """Optional inline datum or datum hash."""

    reference_script: ReferenceScript | None = None
    """Optional reference script stored in this output."""


# ---------------------------------------------------------------------------
# Babbage protocol parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BabbageProtocolParams(AlonzoProtocolParams):
    """Babbage-era protocol parameters extending Alonzo.

    Spec ref: Babbage ledger formal spec, protocol parameters.
    Haskell ref: ``BabbageEraPParams`` in ``Cardano.Ledger.Babbage.PParams``

    Key change: ``coinsPerUTxOByte`` replaces ``coinsPerUTxOWord``.
    The Alonzo ``coinsPerUTxOWord`` is still inherited but not used
    for min UTxO calculation in Babbage.
    """

    coins_per_utxo_byte: int = 4310
    """Lovelace per byte for Babbage min-UTxO calculation.
    Replaces Alonzo's ``coinsPerUTxOWord``.
    Babbage mainnet: 4310.

    Spec ref: ``coinsPerUTxOByte`` in Babbage formal spec.
    Haskell ref: ``bppCoinsPerUTxOByte`` in ``BabbageEraPParams``
    """


# Babbage mainnet defaults (for testing)
BABBAGE_MAINNET_PARAMS = BabbageProtocolParams()
