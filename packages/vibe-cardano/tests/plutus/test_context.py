"""Tests for ScriptContext construction.

Tests cover:
    - ScriptPurpose encoding (Spending, Minting, Rewarding, Certifying)
    - TxOutRef data encoding
    - Address data encoding
    - Value data encoding (ADA + multi-asset)
    - Interval/time range encoding
    - TxInfoBuilder: V1, V2, V3 TxInfo construction
    - ScriptContext assembly for all three versions
"""

from __future__ import annotations

from uplc.ast import (
    PlutusByteString,
    PlutusConstr,
    PlutusInteger,
    PlutusList,
    PlutusMap,
)

from vibe.cardano.plutus.context import (
    TxInfoBuilder,
    address_to_data,
    build_script_context_v1,
    build_script_context_v2,
    build_script_context_v3,
    certifying_purpose,
    interval_to_data,
    minting_purpose,
    rewarding_purpose,
    spending_purpose,
    tx_out_ref_to_data,
    value_to_data,
)

# ---------------------------------------------------------------------------
# ScriptPurpose
# ---------------------------------------------------------------------------


class TestScriptPurpose:
    """Tests for ScriptPurpose construction and encoding."""

    def test_spending_purpose(self) -> None:
        out_ref = tx_out_ref_to_data(b"\xaa" * 32, 0)
        purpose = spending_purpose(out_ref)
        data = purpose.to_plutus_data()
        assert isinstance(data, PlutusConstr)
        assert data.constructor == 1  # Spending tag
        assert len(data.fields) == 1

    def test_minting_purpose(self) -> None:
        policy_id = b"\xbb" * 28
        purpose = minting_purpose(policy_id)
        data = purpose.to_plutus_data()
        assert isinstance(data, PlutusConstr)
        assert data.constructor == 0  # Minting tag
        assert isinstance(data.fields[0], PlutusByteString)
        assert data.fields[0].value == policy_id

    def test_rewarding_purpose(self) -> None:
        cred = PlutusConstr(0, [PlutusByteString(b"\xcc" * 28)])
        purpose = rewarding_purpose(cred)
        data = purpose.to_plutus_data()
        assert data.constructor == 2  # Rewarding tag

    def test_certifying_purpose(self) -> None:
        dcert = PlutusConstr(0, [PlutusByteString(b"\xdd" * 28)])
        purpose = certifying_purpose(dcert)
        data = purpose.to_plutus_data()
        assert data.constructor == 3  # Certifying tag


# ---------------------------------------------------------------------------
# TxOutRef
# ---------------------------------------------------------------------------


class TestTxOutRef:
    """Tests for TxOutRef encoding."""

    def test_basic_encoding(self) -> None:
        tx_id = b"\x01" * 32
        ref = tx_out_ref_to_data(tx_id, 5)
        assert isinstance(ref, PlutusConstr)
        assert ref.constructor == 0
        # Fields: [TxId, index]
        assert len(ref.fields) == 2
        # TxId is Constr 0 [ByteString]
        tx_id_data = ref.fields[0]
        assert isinstance(tx_id_data, PlutusConstr)
        assert tx_id_data.constructor == 0
        assert tx_id_data.fields[0] == PlutusByteString(tx_id)
        # Index
        assert ref.fields[1] == PlutusInteger(5)

    def test_zero_index(self) -> None:
        ref = tx_out_ref_to_data(b"\x00" * 32, 0)
        assert ref.fields[1] == PlutusInteger(0)


# ---------------------------------------------------------------------------
# Value encoding
# ---------------------------------------------------------------------------


class TestValueEncoding:
    """Tests for Value -> Plutus Data encoding."""

    def _lookup(self, m: PlutusMap, key):
        """Helper: lookup key in PlutusMap (tuple of pairs)."""
        for k, v in m.items():
            if k == key:
                return v
        raise KeyError(key)

    def test_ada_only(self) -> None:
        val = value_to_data(2_000_000)
        assert isinstance(val, PlutusMap)
        # Should have ADA entry
        ada_cs = PlutusByteString(b"")
        keys = [k for k, v in val.items()]
        assert ada_cs in keys
        inner = self._lookup(val, ada_cs)
        assert isinstance(inner, PlutusMap)
        ada_tn = PlutusByteString(b"")
        assert self._lookup(inner, ada_tn) == PlutusInteger(2_000_000)

    def test_multi_asset(self) -> None:
        policy = b"\xab" * 28
        val = value_to_data(
            5_000_000,
            multi_asset={policy: {b"TOKEN": 100}},
        )
        assert isinstance(val, PlutusMap)
        # Should have ADA and policy entries
        assert len(val.value) == 2
        # Check token entry
        cs = PlutusByteString(policy)
        keys = [k for k, v in val.items()]
        assert cs in keys
        inner = self._lookup(val, cs)
        assert isinstance(inner, PlutusMap)
        assert self._lookup(inner, PlutusByteString(b"TOKEN")) == PlutusInteger(100)


# ---------------------------------------------------------------------------
# Interval encoding
# ---------------------------------------------------------------------------


class TestIntervalEncoding:
    """Tests for POSIXTimeRange encoding."""

    def test_unbounded_interval(self) -> None:
        interval = interval_to_data()
        assert isinstance(interval, PlutusConstr)
        assert interval.constructor == 0
        # [LowerBound, UpperBound]
        lower = interval.fields[0]
        upper = interval.fields[1]
        # Lower: NegInf
        assert lower.fields[0].constructor == 0  # NegInf
        # Upper: PosInf
        assert upper.fields[0].constructor == 2  # PosInf

    def test_bounded_interval(self) -> None:
        interval = interval_to_data(lower_bound=1000, upper_bound=2000)
        lower = interval.fields[0]
        upper = interval.fields[1]
        # Lower: Finite 1000
        assert lower.fields[0].constructor == 1  # Finite
        assert lower.fields[0].fields[0] == PlutusInteger(1000)
        # Upper: Finite 2000
        assert upper.fields[0].constructor == 1  # Finite
        assert upper.fields[0].fields[0] == PlutusInteger(2000)

    def test_lower_bound_only(self) -> None:
        interval = interval_to_data(lower_bound=500)
        lower = interval.fields[0]
        upper = interval.fields[1]
        assert lower.fields[0].constructor == 1  # Finite
        assert upper.fields[0].constructor == 2  # PosInf

    def test_upper_bound_only(self) -> None:
        interval = interval_to_data(upper_bound=9999)
        lower = interval.fields[0]
        upper = interval.fields[1]
        assert lower.fields[0].constructor == 0  # NegInf
        assert upper.fields[0].constructor == 1  # Finite


# ---------------------------------------------------------------------------
# Address encoding
# ---------------------------------------------------------------------------


class TestAddressEncoding:
    """Tests for Address -> Plutus Data encoding."""

    def test_base_address_key_key(self) -> None:
        """Type 0x00: base address, key payment, key staking."""
        payment_hash = b"\x11" * 28
        staking_hash = b"\x22" * 28
        addr_bytes = bytes([0x00]) + payment_hash + staking_hash
        addr = address_to_data(addr_bytes)
        assert isinstance(addr, PlutusConstr)
        assert addr.constructor == 0
        # Payment credential: PubKeyCredential (Constr 0)
        assert addr.fields[0].constructor == 0
        assert addr.fields[0].fields[0] == PlutusByteString(payment_hash)
        # Staking: Just (StakingHash (PubKeyCredential))
        maybe_staking = addr.fields[1]
        assert maybe_staking.constructor == 0  # Just

    def test_enterprise_address_no_staking(self) -> None:
        """Type 0x60: enterprise address, key payment, no staking."""
        payment_hash = b"\x33" * 28
        addr_bytes = bytes([0x60]) + payment_hash
        addr = address_to_data(addr_bytes)
        assert isinstance(addr, PlutusConstr)
        # Staking: Nothing
        assert addr.fields[1].constructor == 1  # Nothing

    def test_script_payment(self) -> None:
        """Type 0x10: base address, script payment, key staking."""
        payment_hash = b"\x44" * 28
        staking_hash = b"\x55" * 28
        addr_bytes = bytes([0x10]) + payment_hash + staking_hash
        addr = address_to_data(addr_bytes)
        # Payment credential: ScriptCredential (Constr 1)
        assert addr.fields[0].constructor == 1


# ---------------------------------------------------------------------------
# TxInfoBuilder
# ---------------------------------------------------------------------------


class TestTxInfoBuilder:
    """Tests for TxInfoBuilder and TxInfo construction."""

    def _make_address(self) -> bytes:
        """Create a dummy base address."""
        return bytes([0x00]) + b"\x11" * 28 + b"\x22" * 28

    def test_build_v1_basic(self) -> None:
        builder = TxInfoBuilder()
        builder.add_input(
            tx_id=b"\xaa" * 32,
            index=0,
            address_bytes=self._make_address(),
            coin=5_000_000,
        )
        builder.add_output(
            address_bytes=self._make_address(),
            coin=3_000_000,
        )
        builder.set_fee(200_000)
        builder.set_tx_id(b"\xbb" * 32)

        tx_info = builder.build_v1()
        assert isinstance(tx_info, PlutusConstr)
        assert tx_info.constructor == 0
        # V1 TxInfo has 10 fields
        assert len(tx_info.fields) == 10

    def test_build_v2_has_reference_inputs(self) -> None:
        builder = TxInfoBuilder()
        builder.add_input(
            tx_id=b"\xaa" * 32,
            index=0,
            address_bytes=self._make_address(),
            coin=5_000_000,
        )
        builder.add_reference_input(
            tx_id=b"\xcc" * 32,
            index=1,
            address_bytes=self._make_address(),
            coin=10_000_000,
        )
        builder.set_tx_id(b"\xbb" * 32)

        tx_info = builder.build_v2()
        assert isinstance(tx_info, PlutusConstr)
        # V2 TxInfo has 12 fields
        assert len(tx_info.fields) == 12
        # Reference inputs is the second field
        ref_inputs = tx_info.fields[1]
        assert isinstance(ref_inputs, PlutusList)
        assert len(ref_inputs.value) == 1

    def test_build_v3_has_governance_fields(self) -> None:
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xdd" * 32)
        builder.current_treasury_amount = PlutusInteger(1_000_000_000)
        builder.treasury_donation = PlutusInteger(500_000)

        tx_info = builder.build_v3()
        assert isinstance(tx_info, PlutusConstr)
        # V3 TxInfo has 16 fields
        assert len(tx_info.fields) == 16

    def test_build_v1_with_signatories(self) -> None:
        builder = TxInfoBuilder()
        builder.add_signatory(b"\x11" * 28)
        builder.add_signatory(b"\x22" * 28)
        builder.set_tx_id(b"\xff" * 32)

        tx_info = builder.build_v1()
        # Signatories are field index 7 in V1
        sigs = tx_info.fields[7]
        assert isinstance(sigs, PlutusList)
        assert len(sigs.value) == 2

    def test_build_v1_with_minted(self) -> None:
        builder = TxInfoBuilder()
        policy_id = b"\xab" * 28
        builder.set_minted({policy_id: {b"TOKEN": 50}})
        builder.set_tx_id(b"\xff" * 32)

        tx_info = builder.build_v1()
        # Minted is field index 3 in V1
        minted = tx_info.fields[3]
        assert isinstance(minted, PlutusMap)

    def test_build_v1_with_valid_range(self) -> None:
        builder = TxInfoBuilder()
        builder.set_valid_range(lower_bound=1000, upper_bound=2000)
        builder.set_tx_id(b"\xff" * 32)

        tx_info = builder.build_v1()
        # Valid range is field index 6 in V1
        valid_range = tx_info.fields[6]
        assert isinstance(valid_range, PlutusConstr)

    def test_v3_treasury_none(self) -> None:
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xff" * 32)
        # Don't set treasury amounts -- should be Nothing

        tx_info = builder.build_v3()
        # Treasury fields are last two (indices 14 and 15)
        treasury = tx_info.fields[14]
        donation = tx_info.fields[15]
        # Both should be Nothing (Constr 1 [])
        assert treasury.constructor == 1
        assert donation.constructor == 1


# ---------------------------------------------------------------------------
# ScriptContext assembly
# ---------------------------------------------------------------------------


class TestScriptContext:
    """Tests for full ScriptContext construction."""

    def _make_minimal_tx_info_v1(self) -> PlutusConstr:
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        return builder.build_v1()

    def _make_minimal_tx_info_v2(self) -> PlutusConstr:
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        return builder.build_v2()

    def _make_minimal_tx_info_v3(self) -> PlutusConstr:
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        return builder.build_v3()

    def test_v1_script_context(self) -> None:
        tx_info = self._make_minimal_tx_info_v1()
        purpose = minting_purpose(b"\xbb" * 28)
        ctx = build_script_context_v1(tx_info, purpose)
        assert isinstance(ctx, PlutusConstr)
        assert ctx.constructor == 0
        # V1 ScriptContext: [TxInfo, ScriptPurpose]
        assert len(ctx.fields) == 2

    def test_v2_script_context(self) -> None:
        tx_info = self._make_minimal_tx_info_v2()
        out_ref = tx_out_ref_to_data(b"\xcc" * 32, 0)
        purpose = spending_purpose(out_ref)
        ctx = build_script_context_v2(tx_info, purpose)
        assert isinstance(ctx, PlutusConstr)
        assert len(ctx.fields) == 2

    def test_v3_script_context_includes_redeemer(self) -> None:
        tx_info = self._make_minimal_tx_info_v3()
        redeemer = PlutusConstr(0, [PlutusInteger(42)])
        purpose = minting_purpose(b"\xdd" * 28)
        ctx = build_script_context_v3(tx_info, redeemer, purpose)
        assert isinstance(ctx, PlutusConstr)
        # V3 ScriptContext: [TxInfo, Redeemer, ScriptPurpose]
        assert len(ctx.fields) == 3
        # Redeemer is the second field
        assert ctx.fields[1] == redeemer


# ---------------------------------------------------------------------------
# Test 6: V1 context should NOT parse as V2/V3
# ---------------------------------------------------------------------------


class TestScriptContextVersionIncompatibility:
    """Test that ScriptContext built for one version cannot be misinterpreted as another.

    Each Plutus version has a different TxInfo structure:
        - V1 TxInfo: 10 fields
        - V2 TxInfo: 12 fields (adds reference_inputs, redeemers)
        - V3 TxInfo: 16 fields (adds governance fields)

    And ScriptContext itself differs:
        - V1/V2 ScriptContext: 2 fields [TxInfo, ScriptPurpose]
        - V3 ScriptContext: 3 fields [TxInfo, Redeemer, ScriptPurpose]

    A V1 context passed to a V2/V3 script would have the wrong number of
    fields, causing the script to fail or produce wrong results.

    Haskell ref: ``TxInfo`` in ``PlutusLedgerApi.V1/V2/V3.Contexts``
    """

    def _make_address(self) -> bytes:
        return bytes([0x00]) + b"\x11" * 28 + b"\x22" * 28

    def test_v1_txinfo_has_10_fields(self) -> None:
        """V1 TxInfo must have exactly 10 fields."""
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        tx_info = builder.build_v1()
        assert len(tx_info.fields) == 10

    def test_v2_txinfo_has_12_fields(self) -> None:
        """V2 TxInfo must have exactly 12 fields."""
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        tx_info = builder.build_v2()
        assert len(tx_info.fields) == 12

    def test_v3_txinfo_has_16_fields(self) -> None:
        """V3 TxInfo must have exactly 16 fields."""
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        tx_info = builder.build_v3()
        assert len(tx_info.fields) == 16

    def test_v1_txinfo_field_count_differs_from_v2(self) -> None:
        """V1 TxInfo cannot be mistaken for V2 TxInfo (different field count).

        If a script expects V2 TxInfo (12 fields) but receives V1 TxInfo
        (10 fields), accessing field index 10 or 11 would fail.
        """
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        v1_info = builder.build_v1()
        v2_info = builder.build_v2()
        assert len(v1_info.fields) != len(v2_info.fields), (
            "V1 and V2 TxInfo should have different field counts"
        )

    def test_v1_txinfo_field_count_differs_from_v3(self) -> None:
        """V1 TxInfo cannot be mistaken for V3 TxInfo (different field count)."""
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        v1_info = builder.build_v1()
        v3_info = builder.build_v3()
        assert len(v1_info.fields) != len(v3_info.fields), (
            "V1 and V3 TxInfo should have different field counts"
        )

    def test_v2_txinfo_field_count_differs_from_v3(self) -> None:
        """V2 TxInfo cannot be mistaken for V3 TxInfo (different field count)."""
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        v2_info = builder.build_v2()
        v3_info = builder.build_v3()
        assert len(v2_info.fields) != len(v3_info.fields), (
            "V2 and V3 TxInfo should have different field counts"
        )

    def test_v1_v2_script_context_same_shape_different_txinfo(self) -> None:
        """V1 and V2 ScriptContext have same outer shape (2 fields) but different TxInfo.

        Both have [TxInfo, ScriptPurpose], but the TxInfo differs.
        A V1 context in a V2 validator would have wrong TxInfo field count.
        """
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        purpose = minting_purpose(b"\xbb" * 28)

        ctx_v1 = build_script_context_v1(builder.build_v1(), purpose)
        ctx_v2 = build_script_context_v2(builder.build_v2(), purpose)

        # Both have 2 fields at the ScriptContext level
        assert len(ctx_v1.fields) == 2
        assert len(ctx_v2.fields) == 2

        # But the TxInfo inside has different field count
        v1_txinfo = ctx_v1.fields[0]
        v2_txinfo = ctx_v2.fields[0]
        assert len(v1_txinfo.fields) != len(v2_txinfo.fields)

    def test_v3_script_context_has_different_shape(self) -> None:
        """V3 ScriptContext has 3 fields (TxInfo, Redeemer, ScriptPurpose).

        A V1/V2 context (2 fields) passed to a V3 validator would fail
        because the validator expects 3 fields.
        """
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        purpose = minting_purpose(b"\xbb" * 28)
        redeemer = PlutusConstr(0, [PlutusInteger(42)])

        ctx_v1 = build_script_context_v1(builder.build_v1(), purpose)
        ctx_v3 = build_script_context_v3(builder.build_v3(), redeemer, purpose)

        assert len(ctx_v1.fields) == 2
        assert len(ctx_v3.fields) == 3
        assert len(ctx_v1.fields) != len(ctx_v3.fields), (
            "V1 and V3 ScriptContext must have different field counts"
        )
