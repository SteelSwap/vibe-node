"""ScriptContext construction for Plutus script evaluation.

Builds the ScriptContext (TxInfo + ScriptPurpose) that is passed to Plutus
validators during script evaluation. The context construction differs per
Plutus version:

    - PlutusV1: Basic TxInfo with inputs, outputs, fee, minted, dcerts,
      withdrawals, valid_range, signatories, data map.
    - PlutusV2: Adds reference_inputs, outputs with inline datums,
      and reference scripts.
    - PlutusV3: Adds voting_procedures, proposal_procedures,
      current_treasury_amount, treasury_donation. Redeemer is inlined
      in the ScriptContext rather than passed as a separate argument.

The ScriptPurpose identifies why a script is being evaluated:
    - Spending(TxOutRef) -- spending a UTxO locked by a script
    - Minting(CurrencySymbol) -- minting/burning tokens under a policy
    - Rewarding(StakingCredential) -- withdrawing staking rewards
    - Certifying(DCert) -- delegating/registering/deregistering stake

Spec references:
    * Alonzo ledger formal spec, Section 4.3 (Script context)
    * Babbage ledger formal spec, Section 4.3 (PlutusV2 context)
    * Conway ledger formal spec (PlutusV3 context)
    * ``plutus-ledger-api/src/PlutusLedgerApi/V1/Contexts.hs``
    * ``plutus-ledger-api/src/PlutusLedgerApi/V2/Contexts.hs``
    * ``plutus-ledger-api/src/PlutusLedgerApi/V3/Contexts.hs``

Haskell references:
    * ``ScriptContext`` in ``PlutusLedgerApi.V1.Contexts``
    * ``TxInfo`` in ``PlutusLedgerApi.V1.Contexts`` / V2 / V3
    * ``ScriptPurpose`` in ``PlutusLedgerApi.V1.Contexts``
    * ``txInfoV1`` / ``txInfoV2`` / ``txInfoV3`` in
      ``Cardano.Ledger.Alonzo.Plutus.TxInfo``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

from uplc.ast import (
    PlutusByteString,
    PlutusConstr,
    PlutusData,
    PlutusInteger,
    PlutusList,
    PlutusMap,
)

if TYPE_CHECKING:
    from pycardano import TransactionBody, TransactionInput, TransactionOutput
    from pycardano.hash import ScriptHash, TransactionId


# ---------------------------------------------------------------------------
# ScriptPurpose
# ---------------------------------------------------------------------------


class ScriptPurposeTag(Enum):
    """Tags for the ScriptPurpose sum type.

    Haskell ref: ``ScriptPurpose`` in ``PlutusLedgerApi.V1.Contexts``
    """

    MINTING = 0
    SPENDING = 1
    REWARDING = 2
    CERTIFYING = 3
    # PlutusV3 additions:
    VOTING = 4
    PROPOSING = 5


@dataclass(frozen=True, slots=True)
class ScriptPurpose:
    """Identifies why a Plutus script is being evaluated.

    Encoded as a PlutusConstr where the constructor tag matches
    ScriptPurposeTag and the fields carry the relevant context.

    Spec ref: Alonzo ledger formal spec, ``ScriptPurpose``.
    Haskell ref: ``ScriptPurpose`` in ``PlutusLedgerApi.V1.Contexts``
    """

    tag: ScriptPurposeTag
    data: PlutusData

    def to_plutus_data(self) -> PlutusConstr:
        """Encode as uplc PlutusConstr."""
        return PlutusConstr(self.tag.value, [self.data])


# ---------------------------------------------------------------------------
# ScriptPurpose constructors
# ---------------------------------------------------------------------------


def spending_purpose(tx_out_ref: PlutusData) -> ScriptPurpose:
    """Create a Spending ScriptPurpose.

    Args:
        tx_out_ref: TxOutRef as PlutusConstr(0, [tx_id_bytes, index]).
    """
    return ScriptPurpose(ScriptPurposeTag.SPENDING, tx_out_ref)


def minting_purpose(currency_symbol: bytes) -> ScriptPurpose:
    """Create a Minting ScriptPurpose.

    Args:
        currency_symbol: The policy ID (28-byte hash) being minted.
    """
    return ScriptPurpose(ScriptPurposeTag.MINTING, PlutusByteString(currency_symbol))


def rewarding_purpose(staking_credential: PlutusData) -> ScriptPurpose:
    """Create a Rewarding ScriptPurpose.

    Args:
        staking_credential: StakingCredential as PlutusConstr.
    """
    return ScriptPurpose(ScriptPurposeTag.REWARDING, staking_credential)


def certifying_purpose(dcert: PlutusData) -> ScriptPurpose:
    """Create a Certifying ScriptPurpose.

    Args:
        dcert: DCert as PlutusConstr.
    """
    return ScriptPurpose(ScriptPurposeTag.CERTIFYING, dcert)


# ---------------------------------------------------------------------------
# Data conversion helpers -- pycardano types to Plutus Data
# ---------------------------------------------------------------------------


def tx_out_ref_to_data(tx_id: bytes, index: int) -> PlutusConstr:
    """Encode a TxOutRef as Plutus Data.

    TxOutRef = Constr 0 [TxId, Integer]
    TxId = Constr 0 [ByteString]

    Haskell ref: ``TxOutRef`` in ``PlutusLedgerApi.V1.Tx``
    """
    tx_id_data = PlutusConstr(0, [PlutusByteString(tx_id)])
    return PlutusConstr(0, [tx_id_data, PlutusInteger(index)])


def address_to_data(address_bytes: bytes) -> PlutusConstr:
    """Encode a Cardano address as Plutus Data (Address type).

    Address = Constr 0 [Credential, Maybe StakingCredential]

    Credential =
        PubKeyCredential(hash) = Constr 0 [ByteString]
        ScriptCredential(hash) = Constr 1 [ByteString]

    StakingCredential =
        StakingHash(Credential) = Constr 0 [Credential]
        StakingPtr(slot, txIx, certIx) = Constr 1 [Integer, Integer, Integer]

    Maybe a =
        Nothing = Constr 1 []
        Just a  = Constr 0 [a]

    Haskell ref: ``Address`` in ``PlutusLedgerApi.V1.Address``
    """
    if len(address_bytes) < 1:
        raise ValueError("Address bytes too short")

    header = address_bytes[0]
    addr_type = (header >> 4) & 0x0F

    # Extract payment credential (first 28 bytes after header)
    if len(address_bytes) < 29:
        # Bootstrap address or other format -- encode as raw bytes
        return PlutusConstr(0, [
            PlutusConstr(0, [PlutusByteString(address_bytes[1:29] if len(address_bytes) >= 29 else address_bytes[1:])]),
            PlutusConstr(1, []),  # Nothing
        ])

    payment_hash = address_bytes[1:29]

    # Bit 4 of header: 0 = key credential, 1 = script credential
    if (header & 0x10) == 0:
        payment_cred = PlutusConstr(0, [PlutusByteString(payment_hash)])  # PubKeyCredential
    else:
        payment_cred = PlutusConstr(1, [PlutusByteString(payment_hash)])  # ScriptCredential

    # Staking credential (from remaining bytes, if present)
    if len(address_bytes) >= 57:
        staking_hash = address_bytes[29:57]
        # Bit 5 of header: 0 = key staking, 1 = script staking
        if (header & 0x20) == 0:
            staking_cred = PlutusConstr(0, [PlutusByteString(staking_hash)])
        else:
            staking_cred = PlutusConstr(1, [PlutusByteString(staking_hash)])
        maybe_staking = PlutusConstr(0, [PlutusConstr(0, [staking_cred])])  # Just (StakingHash cred)
    else:
        maybe_staking = PlutusConstr(1, [])  # Nothing

    return PlutusConstr(0, [payment_cred, maybe_staking])


def value_to_data(coin: int, multi_asset: dict[bytes, dict[bytes, int]] | None = None) -> PlutusData:
    """Encode a Value as Plutus Data.

    Value is a map: CurrencySymbol -> Map TokenName -> Integer.
    ADA is represented as CurrencySymbol = "" (empty bytestring),
    TokenName = "" (empty bytestring).

    Haskell ref: ``Value`` in ``PlutusLedgerApi.V1.Value``
    """
    entries: dict[PlutusData, PlutusData] = {}

    # ADA entry (always present)
    ada_cs = PlutusByteString(b"")
    ada_tn = PlutusByteString(b"")
    entries[ada_cs] = PlutusMap({ada_tn: PlutusInteger(coin)})

    # Multi-asset entries
    if multi_asset:
        for policy_id, assets in multi_asset.items():
            cs = PlutusByteString(policy_id)
            token_map: dict[PlutusData, PlutusData] = {}
            for asset_name, quantity in assets.items():
                token_map[PlutusByteString(asset_name)] = PlutusInteger(quantity)
            entries[cs] = PlutusMap(token_map)

    return PlutusMap(entries)


def interval_to_data(
    lower_bound: int | None = None,
    upper_bound: int | None = None,
) -> PlutusConstr:
    """Encode a POSIXTimeRange as Plutus Data.

    Interval a = Constr 0 [LowerBound a, UpperBound a]
    LowerBound a = Constr 0 [Extended a, Closure]
    UpperBound a = Constr 0 [Extended a, Closure]
    Extended a =
        NegInf = Constr 0 []
        Finite a = Constr 1 [a]
        PosInf  = Constr 2 []
    Closure = bool (True = inclusive)

    Haskell ref: ``Interval`` in ``PlutusLedgerApi.V1.Interval``
    """
    # Lower bound
    if lower_bound is None:
        lower_ext = PlutusConstr(0, [])  # NegInf
        lower_closure = PlutusConstr(1, [])  # True (convention: NegInf is always True closure)
    else:
        lower_ext = PlutusConstr(1, [PlutusInteger(lower_bound)])  # Finite
        lower_closure = PlutusConstr(1, [])  # True (inclusive)

    lower = PlutusConstr(0, [lower_ext, lower_closure])

    # Upper bound
    if upper_bound is None:
        upper_ext = PlutusConstr(2, [])  # PosInf
        upper_closure = PlutusConstr(1, [])  # True
    else:
        upper_ext = PlutusConstr(1, [PlutusInteger(upper_bound)])  # Finite
        upper_closure = PlutusConstr(0, [])  # False (exclusive, matching Haskell convention)

    upper = PlutusConstr(0, [upper_ext, upper_closure])

    return PlutusConstr(0, [lower, upper])


# ---------------------------------------------------------------------------
# TxInfo construction
# ---------------------------------------------------------------------------


@dataclass
class TxInfoBuilder:
    """Builder for constructing TxInfo as Plutus Data.

    This accumulates transaction information and produces the TxInfo
    structure expected by the Plutus script for a given version.

    Spec ref: Alonzo ledger formal spec, Section 4.3 (TxInfo).
    Haskell ref: ``TxInfo`` in ``PlutusLedgerApi.V1.Contexts``
    """

    # Transaction inputs (list of TxInInfo)
    inputs: list[PlutusConstr] = field(default_factory=list)

    # Reference inputs (PlutusV2+)
    reference_inputs: list[PlutusConstr] = field(default_factory=list)

    # Transaction outputs (list of TxOut)
    outputs: list[PlutusConstr] = field(default_factory=list)

    # Fee (as Value)
    fee: PlutusData = field(default_factory=lambda: value_to_data(0))

    # Minted value
    minted: PlutusData = field(default_factory=lambda: PlutusMap({}))

    # Certificates (list of DCert)
    dcerts: list[PlutusData] = field(default_factory=list)

    # Withdrawals (map: StakingCredential -> Integer)
    withdrawals: PlutusData = field(default_factory=lambda: PlutusMap({}))

    # Valid range (POSIXTimeRange)
    valid_range: PlutusConstr = field(default_factory=lambda: interval_to_data())

    # Signatories (list of PubKeyHash)
    signatories: list[PlutusByteString] = field(default_factory=list)

    # Redeemers (PlutusV3: map ScriptPurpose -> Redeemer)
    redeemers: PlutusData = field(default_factory=lambda: PlutusMap({}))

    # Data map (map DatumHash -> Datum)
    data_map: PlutusData = field(default_factory=lambda: PlutusMap({}))

    # Transaction ID
    tx_id: PlutusByteString = field(default_factory=lambda: PlutusByteString(b"\x00" * 32))

    # PlutusV3 additions
    voting_procedures: PlutusData = field(default_factory=lambda: PlutusMap({}))
    proposal_procedures: list[PlutusData] = field(default_factory=list)
    current_treasury_amount: PlutusData | None = None
    treasury_donation: PlutusData | None = None

    def add_input(
        self,
        tx_id: bytes,
        index: int,
        address_bytes: bytes,
        coin: int,
        multi_asset: dict[bytes, dict[bytes, int]] | None = None,
        datum_hash: bytes | None = None,
        inline_datum: PlutusData | None = None,
    ) -> None:
        """Add a transaction input (TxInInfo).

        TxInInfo = Constr 0 [TxOutRef, TxOut]

        Haskell ref: ``TxInInfo`` in ``PlutusLedgerApi.V1.Contexts``
        """
        out_ref = tx_out_ref_to_data(tx_id, index)
        tx_out = self._make_tx_out(address_bytes, coin, multi_asset, datum_hash, inline_datum)
        self.inputs.append(PlutusConstr(0, [out_ref, tx_out]))

    def add_reference_input(
        self,
        tx_id: bytes,
        index: int,
        address_bytes: bytes,
        coin: int,
        multi_asset: dict[bytes, dict[bytes, int]] | None = None,
        datum_hash: bytes | None = None,
        inline_datum: PlutusData | None = None,
    ) -> None:
        """Add a reference input (PlutusV2+)."""
        out_ref = tx_out_ref_to_data(tx_id, index)
        tx_out = self._make_tx_out(address_bytes, coin, multi_asset, datum_hash, inline_datum)
        self.reference_inputs.append(PlutusConstr(0, [out_ref, tx_out]))

    def add_output(
        self,
        address_bytes: bytes,
        coin: int,
        multi_asset: dict[bytes, dict[bytes, int]] | None = None,
        datum_hash: bytes | None = None,
        inline_datum: PlutusData | None = None,
    ) -> None:
        """Add a transaction output."""
        tx_out = self._make_tx_out(address_bytes, coin, multi_asset, datum_hash, inline_datum)
        self.outputs.append(tx_out)

    def _make_tx_out(
        self,
        address_bytes: bytes,
        coin: int,
        multi_asset: dict[bytes, dict[bytes, int]] | None = None,
        datum_hash: bytes | None = None,
        inline_datum: PlutusData | None = None,
    ) -> PlutusConstr:
        """Construct a TxOut as PlutusConstr.

        PlutusV1 TxOut = Constr 0 [Address, Value, Maybe DatumHash]
        PlutusV2 TxOut = Constr 0 [Address, Value, OutputDatum, Maybe ScriptHash]

        For simplicity, we use the V1 format by default and extend for V2.
        """
        addr_data = address_to_data(address_bytes)
        val_data = value_to_data(coin, multi_asset)

        if datum_hash is not None:
            maybe_datum = PlutusConstr(0, [PlutusByteString(datum_hash)])  # Just hash
        elif inline_datum is not None:
            maybe_datum = PlutusConstr(0, [inline_datum])  # Just datum
        else:
            maybe_datum = PlutusConstr(1, [])  # Nothing

        return PlutusConstr(0, [addr_data, val_data, maybe_datum])

    def set_fee(self, fee_lovelace: int) -> None:
        """Set the transaction fee."""
        self.fee = value_to_data(fee_lovelace)

    def set_valid_range(
        self,
        lower_bound: int | None = None,
        upper_bound: int | None = None,
    ) -> None:
        """Set the validity range as POSIX time interval."""
        self.valid_range = interval_to_data(lower_bound, upper_bound)

    def add_signatory(self, pub_key_hash: bytes) -> None:
        """Add a required signatory."""
        self.signatories.append(PlutusByteString(pub_key_hash))

    def set_tx_id(self, tx_id: bytes) -> None:
        """Set the transaction ID."""
        self.tx_id = PlutusByteString(tx_id)

    def set_minted(self, multi_asset: dict[bytes, dict[bytes, int]]) -> None:
        """Set the minted value."""
        entries: dict[PlutusData, PlutusData] = {}
        for policy_id, assets in multi_asset.items():
            cs = PlutusByteString(policy_id)
            token_map: dict[PlutusData, PlutusData] = {}
            for asset_name, quantity in assets.items():
                token_map[PlutusByteString(asset_name)] = PlutusInteger(quantity)
            entries[cs] = PlutusMap(token_map)
        self.minted = PlutusMap(entries)

    def build_v1(self) -> PlutusConstr:
        """Build PlutusV1 TxInfo.

        TxInfo = Constr 0 [
            inputs,         -- [TxInInfo]
            outputs,        -- [TxOut]
            fee,            -- Value
            minted,         -- Value (forge in V1 spec)
            dcerts,         -- [DCert]
            withdrawals,    -- Map StakingCredential Integer
            valid_range,    -- POSIXTimeRange
            signatories,    -- [PubKeyHash]
            data,           -- Map DatumHash Datum
            id              -- TxId
        ]

        Haskell ref: ``TxInfo`` in ``PlutusLedgerApi.V1.Contexts``
        """
        tx_id_constr = PlutusConstr(0, [self.tx_id])
        return PlutusConstr(0, [
            PlutusList(self.inputs),
            PlutusList(self.outputs),
            self.fee,
            self.minted,
            PlutusList(self.dcerts),
            self.withdrawals,
            self.valid_range,
            PlutusList(self.signatories),
            self.data_map,
            tx_id_constr,
        ])

    def build_v2(self) -> PlutusConstr:
        """Build PlutusV2 TxInfo.

        TxInfo = Constr 0 [
            inputs,             -- [TxInInfo]
            reference_inputs,   -- [TxInInfo]
            outputs,            -- [TxOut]
            fee,                -- Value
            minted,             -- Value
            dcerts,             -- [DCert]
            withdrawals,        -- Map StakingCredential Integer
            valid_range,        -- POSIXTimeRange
            signatories,        -- [PubKeyHash]
            redeemers,          -- Map ScriptPurpose Redeemer
            data,               -- Map DatumHash Datum
            id                  -- TxId
        ]

        Haskell ref: ``TxInfo`` in ``PlutusLedgerApi.V2.Contexts``
        """
        tx_id_constr = PlutusConstr(0, [self.tx_id])
        return PlutusConstr(0, [
            PlutusList(self.inputs),
            PlutusList(self.reference_inputs),
            PlutusList(self.outputs),
            self.fee,
            self.minted,
            PlutusList(self.dcerts),
            self.withdrawals,
            self.valid_range,
            PlutusList(self.signatories),
            self.redeemers,
            self.data_map,
            tx_id_constr,
        ])

    def build_v3(self) -> PlutusConstr:
        """Build PlutusV3 TxInfo.

        TxInfo = Constr 0 [
            inputs,                     -- [TxInInfo]
            reference_inputs,           -- [TxInInfo]
            outputs,                    -- [TxOut]
            fee,                        -- Lovelace (integer, not Value!)
            minted,                     -- Value
            dcerts,                     -- [TxCert] (renamed from DCert)
            withdrawals,                -- Map Credential Lovelace
            valid_range,                -- POSIXTimeRange
            signatories,                -- [PubKeyHash]
            redeemers,                  -- Map ScriptPurpose Redeemer
            data,                       -- Map DatumHash Datum
            id,                         -- TxId
            voting_procedures,          -- Map Voter (Map GovernanceActionId Vote)
            proposal_procedures,        -- [ProposalProcedure]
            current_treasury_amount,    -- Maybe Lovelace
            treasury_donation           -- Maybe Lovelace
        ]

        Haskell ref: ``TxInfo`` in ``PlutusLedgerApi.V3.Contexts``
        """
        tx_id_constr = PlutusConstr(0, [self.tx_id])

        # Treasury amounts: Maybe Lovelace
        treasury = (
            PlutusConstr(0, [self.current_treasury_amount])
            if self.current_treasury_amount is not None
            else PlutusConstr(1, [])
        )
        donation = (
            PlutusConstr(0, [self.treasury_donation])
            if self.treasury_donation is not None
            else PlutusConstr(1, [])
        )

        return PlutusConstr(0, [
            PlutusList(self.inputs),
            PlutusList(self.reference_inputs),
            PlutusList(self.outputs),
            self.fee,
            self.minted,
            PlutusList(self.dcerts),
            self.withdrawals,
            self.valid_range,
            PlutusList(self.signatories),
            self.redeemers,
            self.data_map,
            tx_id_constr,
            self.voting_procedures,
            PlutusList(self.proposal_procedures),
            treasury,
            donation,
        ])


# ---------------------------------------------------------------------------
# ScriptContext construction
# ---------------------------------------------------------------------------


def build_script_context_v1(
    tx_info: PlutusConstr,
    purpose: ScriptPurpose,
) -> PlutusConstr:
    """Build a PlutusV1 ScriptContext.

    ScriptContext = Constr 0 [TxInfo, ScriptPurpose]

    Haskell ref: ``ScriptContext`` in ``PlutusLedgerApi.V1.Contexts``
    """
    return PlutusConstr(0, [tx_info, purpose.to_plutus_data()])


def build_script_context_v2(
    tx_info: PlutusConstr,
    purpose: ScriptPurpose,
) -> PlutusConstr:
    """Build a PlutusV2 ScriptContext.

    ScriptContext = Constr 0 [TxInfo, ScriptPurpose]

    Haskell ref: ``ScriptContext`` in ``PlutusLedgerApi.V2.Contexts``
    """
    return PlutusConstr(0, [tx_info, purpose.to_plutus_data()])


def build_script_context_v3(
    tx_info: PlutusConstr,
    redeemer: PlutusData,
    purpose: ScriptPurpose,
) -> PlutusConstr:
    """Build a PlutusV3 ScriptContext.

    In V3, the ScriptContext includes the redeemer directly:
    ScriptContext = Constr 0 [TxInfo, Redeemer, ScriptPurpose]

    Haskell ref: ``ScriptContext`` in ``PlutusLedgerApi.V3.Contexts``
    """
    return PlutusConstr(0, [tx_info, redeemer, purpose.to_plutus_data()])
