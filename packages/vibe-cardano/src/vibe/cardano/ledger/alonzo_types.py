"""Alonzo-era types: execution units, redeemers, cost models, script purposes.

Alonzo introduces Plutus script support to Cardano, adding:
    - ExUnits: execution budgets (memory + CPU steps)
    - Redeemers: script inputs paired with execution budgets
    - CostModels: per-language cost parameters for Plutus evaluation
    - ScriptPurpose: the reason a script is being run (spending, minting, etc.)
    - Extended protocol parameters for script execution limits and collateral

Spec references:
    * Alonzo ledger formal spec, Section 4 (Transactions)
    * Alonzo ledger formal spec, Section 5 (Scripts and Validation)
    * Alonzo ledger formal spec, Figure 1 (Protocol parameters)
    * ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Scripts.hs``
    * ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/TxWits.hs``
    * ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/PParams.hs``

Haskell references:
    * ``ExUnits`` in ``Cardano.Ledger.Alonzo.Scripts``
    * ``Redeemers`` in ``Cardano.Ledger.Alonzo.TxWits``
    * ``CostModels`` in ``Cardano.Ledger.Alonzo.Scripts``
    * ``AlonzoEraPParams`` in ``Cardano.Ledger.Alonzo.PParams``
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import IntEnum

from vibe.cardano.ledger.allegra_mary import MaryProtocolParams

# ---------------------------------------------------------------------------
# ExUnits — execution budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExUnits:
    """Execution units: memory and CPU step budget for Plutus scripts.

    Spec ref: Alonzo formal spec, ``ExUnits = (Natural, Natural)``.
    Haskell ref: ``ExUnits`` in ``Cardano.Ledger.Alonzo.Scripts``

    Both components must be non-negative. Zero is allowed (native scripts
    don't consume execution units).
    """

    mem: int = 0
    """Memory units consumed."""

    steps: int = 0
    """CPU step units consumed."""

    def __post_init__(self) -> None:
        if self.mem < 0:
            raise ValueError(f"ExUnits mem must be non-negative, got {self.mem}")
        if self.steps < 0:
            raise ValueError(f"ExUnits steps must be non-negative, got {self.steps}")

    def __add__(self, other: ExUnits) -> ExUnits:
        """Component-wise addition of execution units."""
        if not isinstance(other, ExUnits):
            return NotImplemented
        return ExUnits(mem=self.mem + other.mem, steps=self.steps + other.steps)

    def __le__(self, other: ExUnits) -> bool:
        """Component-wise less-than-or-equal (both mem and steps)."""
        if not isinstance(other, ExUnits):
            return NotImplemented
        return self.mem <= other.mem and self.steps <= other.steps

    def __lt__(self, other: ExUnits) -> bool:
        """Component-wise less-than (at least one strictly less, both <=)."""
        if not isinstance(other, ExUnits):
            return NotImplemented
        return self <= other and (self.mem < other.mem or self.steps < other.steps)

    def exceeds(self, limit: ExUnits) -> bool:
        """Check if this ExUnits exceeds the given limit in either dimension.

        Returns True if mem > limit.mem OR steps > limit.steps.
        This is the negation of __le__, used for clarity in validation code.
        """
        return self.mem > limit.mem or self.steps > limit.steps


# ---------------------------------------------------------------------------
# RedeemerTag — script purpose tag in the redeemer map
# ---------------------------------------------------------------------------


class RedeemerTag(IntEnum):
    """Redeemer tag identifying the script purpose.

    Spec ref: Alonzo formal spec, ``RdmrPtr = Tag x Ix``.
    Haskell ref: ``Tag`` in ``Cardano.Ledger.Alonzo.Scripts``

    The integer values match the CBOR encoding used on-chain.
    """

    SPEND = 0
    """Spending a UTxO locked by a Plutus script."""

    MINT = 1
    """Minting tokens under a Plutus minting policy."""

    CERT = 2
    """Certifying (stake delegation, pool registration, etc.)."""

    REWARD = 3
    """Withdrawing rewards from a Plutus-locked reward account."""


# ---------------------------------------------------------------------------
# Redeemer
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Redeemer:
    """A redeemer entry: script input data paired with an execution budget.

    Spec ref: Alonzo formal spec, ``Redeemers = RdmrPtr -> (Data x ExUnits)``.
    Haskell ref: ``Redeemers`` in ``Cardano.Ledger.Alonzo.TxWits``

    The (tag, index) pair forms the ``RdmrPtr`` that identifies which
    script purpose this redeemer is for:
        - (Spend, i): redeemer for the i-th sorted spending input
        - (Mint, i): redeemer for the i-th sorted minting policy
        - (Cert, i): redeemer for the i-th certificate
        - (Reward, i): redeemer for the i-th sorted reward withdrawal
    """

    tag: RedeemerTag
    """Which type of script purpose this redeemer targets."""

    index: int
    """Index into the sorted list of items for this tag."""

    data: bytes
    """Plutus data (PlutusData CBOR encoding). Opaque at this layer."""

    ex_units: ExUnits
    """Execution budget allocated for this script evaluation."""

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError(f"Redeemer index must be non-negative, got {self.index}")


# ---------------------------------------------------------------------------
# ScriptPurpose — resolved from redeemer pointers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpendingPurpose:
    """Script purpose: spending a UTxO.

    Spec ref: Alonzo formal spec, ``Spending TxIn``.
    """

    tx_in_id: bytes
    """Transaction ID of the UTxO being spent (32 bytes)."""

    tx_in_index: int
    """Output index of the UTxO being spent."""


@dataclass(frozen=True, slots=True)
class MintingPurpose:
    """Script purpose: minting tokens under a policy.

    Spec ref: Alonzo formal spec, ``Minting PolicyID``.
    """

    policy_id: bytes
    """28-byte policy ID (script hash) of the minting policy."""


@dataclass(frozen=True, slots=True)
class RewardingPurpose:
    """Script purpose: withdrawing rewards from a script-locked account.

    Spec ref: Alonzo formal spec, ``Rewarding StakeCredential``.
    """

    stake_credential: bytes
    """28-byte stake credential hash."""


@dataclass(frozen=True, slots=True)
class CertifyingPurpose:
    """Script purpose: a certificate referencing a script credential.

    Spec ref: Alonzo formal spec, ``Certifying DCert``.
    """

    cert_index: int
    """Index of the certificate in the transaction body."""


# Union type for all script purposes
ScriptPurpose = SpendingPurpose | MintingPurpose | RewardingPurpose | CertifyingPurpose


# ---------------------------------------------------------------------------
# CostModel
# ---------------------------------------------------------------------------


CostModel = dict[str, int]
"""Per-language cost model: maps builtin function names to cost parameters.

Spec ref: Alonzo formal spec, ``CostModel = Map Text Integer``.
Haskell ref: ``CostModel`` in ``Cardano.Ledger.Alonzo.Scripts``

Each Plutus language version (PlutusV1, PlutusV2, ...) has its own cost model
with a specific set of required parameter names.
"""


class Language(IntEnum):
    """Plutus language versions.

    Spec ref: Alonzo formal spec, ``Language``.
    Haskell ref: ``Language`` in ``Cardano.Ledger.Alonzo.Scripts``
    """

    PLUTUS_V1 = 0
    PLUTUS_V2 = 1
    PLUTUS_V3 = 2


# ---------------------------------------------------------------------------
# Execution unit prices
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExUnitPrices:
    """Prices for execution units, used to calculate script fees.

    Spec ref: Alonzo formal spec, ``Prices = (prMem, prSteps)``.
    Haskell ref: ``Prices`` in ``Cardano.Ledger.Alonzo.PParams``

    Stored as rational numbers (numerator/denominator) to avoid floating
    point imprecision, matching the Haskell ``Rational`` representation.
    """

    mem_price_numerator: int = 577
    """Memory price numerator. Alonzo mainnet: 577/10000 = 0.0577 lovelace/unit."""

    mem_price_denominator: int = 10000
    """Memory price denominator."""

    step_price_numerator: int = 721
    """Step price numerator. Alonzo mainnet: 721/10000000 = 0.0000721 lovelace/unit."""

    step_price_denominator: int = 10000000
    """Step price denominator."""

    def fee_for(self, ex_units: ExUnits) -> int:
        """Calculate the fee in lovelace for given execution units.

        fee = ceil(mem * prMem) + ceil(steps * prSteps)

        Uses ceiling arithmetic to ensure the fee is never underpaid.

        Spec ref: Alonzo formal spec, ``txscriptfee``.
        Haskell ref: ``txscriptfee`` in ``Cardano.Ledger.Alonzo.TxInfo``
        """
        # Ceiling division: ceil(a * n / d) = (a * n + d - 1) // d
        mem_fee = (
            ex_units.mem * self.mem_price_numerator + self.mem_price_denominator - 1
        ) // self.mem_price_denominator
        step_fee = (
            ex_units.steps * self.step_price_numerator + self.step_price_denominator - 1
        ) // self.step_price_denominator
        return mem_fee + step_fee


# ---------------------------------------------------------------------------
# Alonzo protocol parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlonzoProtocolParams(MaryProtocolParams):
    """Alonzo-era protocol parameters extending Mary.

    Spec ref: Alonzo ledger formal spec, Figure 1 (Protocol parameters).
    Haskell ref: ``AlonzoEraPParams`` in ``Cardano.Ledger.Alonzo.PParams``

    Adds parameters for Plutus script execution, collateral, and
    script integrity verification.
    """

    collateral_percentage: int = 150
    """Collateral must be >= this percentage of total script fees.
    Alonzo mainnet: 150 (i.e., 150% of script fees).

    Spec ref: ``collateralPercentage`` in Alonzo formal spec.
    Haskell ref: ``appCollateralPercentage`` in ``AlonzoEraPParams``
    """

    max_collateral_inputs: int = 3
    """Maximum number of collateral inputs allowed per transaction.
    Alonzo mainnet: 3.

    Spec ref: ``maxCollateralInputs`` in Alonzo formal spec.
    Haskell ref: ``appMaxCollateralInputs`` in ``AlonzoEraPParams``
    """

    cost_models: dict[Language, CostModel] = field(default_factory=dict)
    """Cost models per Plutus language version.

    Spec ref: ``costmdls`` in Alonzo formal spec.
    Haskell ref: ``appCostModels`` in ``AlonzoEraPParams``
    """

    execution_unit_prices: ExUnitPrices = field(default_factory=ExUnitPrices)
    """Prices for script execution units.

    Spec ref: ``prices`` in Alonzo formal spec.
    Haskell ref: ``appPrices`` in ``AlonzoEraPParams``
    """

    max_tx_ex_units: ExUnits = field(
        default_factory=lambda: ExUnits(mem=10_000_000_000, steps=10_000_000_000_000)
    )
    """Maximum total execution units per transaction.
    Alonzo mainnet: mem=10B, steps=10T (approximately).

    Spec ref: ``maxTxExUnits`` in Alonzo formal spec.
    Haskell ref: ``appMaxTxExUnits`` in ``AlonzoEraPParams``
    """

    max_block_ex_units: ExUnits = field(
        default_factory=lambda: ExUnits(mem=50_000_000_000, steps=40_000_000_000_000)
    )
    """Maximum total execution units per block.
    Alonzo mainnet: mem=50B, steps=40T (approximately).

    Spec ref: ``maxBlockExUnits`` in Alonzo formal spec.
    Haskell ref: ``appMaxBlockExUnits`` in ``AlonzoEraPParams``
    """

    max_val_size: int = 5000
    """Maximum serialized size (in bytes) of a transaction output value.
    Alonzo mainnet: 5000.

    Spec ref: ``maxValSize`` in Alonzo formal spec.
    Haskell ref: ``appMaxValSize`` in ``AlonzoEraPParams``
    """

    coins_per_utxo_word: int = 4310
    """Lovelace per UTxO word for the Alonzo min-UTxO calculation.
    Replaces Mary's minUTxOValue-based formula.
    Alonzo mainnet: 4310.

    Spec ref: ``coinsPerUTxOWord`` in Alonzo formal spec.
    Haskell ref: ``appCoinsPerUTxOWord`` in ``AlonzoEraPParams``
    """


# Alonzo mainnet defaults (genesis-like values for testing)
ALONZO_MAINNET_PARAMS = AlonzoProtocolParams()


# ---------------------------------------------------------------------------
# Script integrity hash computation
# ---------------------------------------------------------------------------


def _serialize_cost_models_for_integrity(
    cost_models: dict[Language, CostModel],
    languages_used: set[Language],
) -> bytes:
    """Serialize cost models for script integrity hash computation.

    Only includes cost models for languages actually used in the transaction.
    Cost model parameters are serialized in canonical (sorted key) order.

    Spec ref: Alonzo formal spec, ``hashScriptIntegrity``.
    Haskell ref: ``hashScriptIntegrity`` in
        ``Cardano.Ledger.Alonzo.TxBody``

    Args:
        cost_models: All available cost models from protocol parameters.
        languages_used: Set of Plutus language versions used in the tx.

    Returns:
        CBOR-encoded cost model data for hashing.
    """
    import cbor2pure as cbor2

    # Build a map: language_tag -> [cost_params_sorted_by_key]
    result: dict[int, list[int]] = {}
    for lang in sorted(languages_used, key=lambda l: l.value):
        if lang in cost_models:
            cm = cost_models[lang]
            # Parameters sorted by key name, values in that order
            result[lang.value] = [cm[k] for k in sorted(cm)]
    return cbor2.dumps(result)


def compute_script_integrity_hash(
    redeemers: list[Redeemer],
    datums: list[bytes],
    cost_models: dict[Language, CostModel],
    languages_used: set[Language],
) -> bytes:
    """Compute the script integrity hash for an Alonzo transaction.

    scriptIntegrityHash = hash(redeemers || datums || language_views)

    This binds the script execution context to the transaction, preventing
    malleability of redeemer data and ensuring cost model agreement.

    Spec ref: Alonzo formal spec, ``hashScriptIntegrity``.
    Haskell ref: ``hashScriptIntegrity`` in
        ``Cardano.Ledger.Alonzo.TxBody``

    Args:
        redeemers: List of redeemers in the transaction.
        datums: List of datum CBOR encodings witnessed in the transaction.
        cost_models: Cost models from protocol parameters.
        languages_used: Plutus language versions used in the transaction.

    Returns:
        32-byte Blake2b-256 hash.
    """
    import cbor2pure as cbor2

    # Encode redeemers as a CBOR array of [tag, index, data, [mem, steps]]
    redeemer_entries = []
    for r in sorted(redeemers, key=lambda x: (x.tag.value, x.index)):
        redeemer_entries.append(
            [
                r.tag.value,
                r.index,
                cbor2.loads(r.data) if r.data else None,
                [r.ex_units.mem, r.ex_units.steps],
            ]
        )
    redeemers_cbor = cbor2.dumps(redeemer_entries)

    # Encode datums as a CBOR array
    datum_values = [cbor2.loads(d) for d in datums]
    datums_cbor = cbor2.dumps(datum_values)

    # Encode language views (cost models for used languages)
    lang_views_cbor = _serialize_cost_models_for_integrity(cost_models, languages_used)

    # Concatenate and hash
    preimage = redeemers_cbor + datums_cbor + lang_views_cbor
    return hashlib.blake2b(preimage, digest_size=32).digest()
