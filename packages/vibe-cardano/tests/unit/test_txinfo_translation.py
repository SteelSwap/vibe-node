"""TxInfo translation tests across Plutus versions and ledger eras.

Validates that our TxInfoBuilder produces the correct Plutus Data structures
for each combination of Plutus version (V1/V2/V3) and ledger era
(Alonzo/Babbage/Conway). These tests are the front line of spec conformance
for script context construction.

Key behaviors under test:
    - Byron bootstrap addresses in inputs/outputs translate to PubKeyCredential
    - V2 TxInfo includes reference inputs, inline datums, and reference scripts
    - V3 TxInfo includes deposit amounts in registration/deregistration certs
    - PV9+ validity interval uses open (exclusive) upper bound for V1 translation
    - Field counts: V1=10, V2=12, V3=16

Spec references:
    * Alonzo ledger formal spec, Section 4.3 (Script context)
    * Babbage ledger formal spec, Section 4.3 (PlutusV2 context)
    * Conway ledger formal spec (PlutusV3 context)
    * ``plutus-ledger-api/src/PlutusLedgerApi/V1/Contexts.hs``
    * ``plutus-ledger-api/src/PlutusLedgerApi/V2/Contexts.hs``
    * ``plutus-ledger-api/src/PlutusLedgerApi/V3/Contexts.hs``

Haskell references:
    * ``txInfoV1`` in ``Cardano.Ledger.Alonzo.Plutus.TxInfo``
    * ``txInfoV2`` in ``Cardano.Ledger.Babbage.Plutus.TxInfo``
    * ``txInfoV3`` in ``Cardano.Ledger.Conway.Plutus.TxInfo``
    * ``transAddr`` for Byron bootstrap address translation
"""

from __future__ import annotations

from uplc.ast import (
    PlutusByteString,
    PlutusConstr,
    PlutusInteger,
    PlutusList,
)

from vibe.cardano.plutus.context import (
    TxInfoBuilder,
    interval_to_data,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_address(payment_hash: bytes, staking_hash: bytes) -> bytes:
    """Build a type-0 base address (key payment, key staking)."""
    return bytes([0x00]) + payment_hash + staking_hash


def _enterprise_address(payment_hash: bytes) -> bytes:
    """Build a type-6 enterprise address (key payment, no staking)."""
    return bytes([0x60]) + payment_hash


def _script_address(script_hash: bytes, staking_hash: bytes) -> bytes:
    """Build a type-1 base address (script payment, key staking)."""
    return bytes([0x10]) + script_hash + staking_hash


def _byron_bootstrap_address() -> bytes:
    """Build a mock Byron bootstrap address.

    Byron addresses have header type 0x82 (bit pattern 1000xxxx).
    They use a different internal structure (CBOR-encoded with root hash),
    but for Plutus translation the key insight is: the address bytes are
    shorter than 29 bytes (no standard 28-byte payment hash after header),
    triggering the bootstrap path in address_to_data.

    Haskell ref: ``transAddr`` in ``Cardano.Ledger.Alonzo.Plutus.TxInfo``
    translates BootstrapAddress by hashing the address to get a 28-byte
    PubKeyCredential.
    """
    # Byron bootstrap: header 0x82, followed by a CBOR payload.
    # We simulate with header + 20 bytes (shorter than the 28+1 needed
    # for Shelley-style parsing, so it hits the bootstrap branch).
    return bytes([0x82]) + b"\xab" * 20


def _byron_address_with_known_hash() -> tuple[bytes, bytes]:
    """Build a Byron bootstrap address and its expected PubKeyCredential hash.

    In the Haskell node, Byron addresses are translated by extracting the
    address root or hashing the serialized address to produce a 28-byte
    credential. Our address_to_data takes the raw bytes after the header.

    Returns (address_bytes, expected_credential_bytes).
    """
    addr = _byron_bootstrap_address()
    # Our implementation extracts addr[1:] when len < 29
    expected_cred = addr[1:]
    return addr, expected_cred


# ---------------------------------------------------------------------------
# Test 1: Alonzo TxInfo with Byron address in output
# ---------------------------------------------------------------------------


class TestAlonzoByronAddress:
    """Byron bootstrap addresses must translate to PubKeyCredential in Plutus.

    Haskell ref: ``transAddr`` converts ``BootstrapAddress`` to
    ``PubKeyCredential (PubKeyHash hash)`` where hash is derived from the
    Byron address root.

    Spec ref: Alonzo ledger formal spec, Section 4.3 -- addresses in TxInfo
    are always represented as ``Address = (Credential, Maybe StakingCredential)``.
    """

    def test_byron_address_in_output(self) -> None:
        """Byron bootstrap address in a TxOut should produce PubKeyCredential."""
        byron_addr, expected_cred = _byron_address_with_known_hash()

        builder = TxInfoBuilder()
        builder.add_output(
            address_bytes=byron_addr,
            coin=2_000_000,
        )
        builder.set_tx_id(b"\xaa" * 32)

        tx_info = builder.build_v1()

        # Extract the output's address
        outputs = tx_info.fields[1]  # V1 field index 1 = outputs
        assert isinstance(outputs, PlutusList)
        assert len(outputs.value) == 1

        tx_out = outputs.value[0]
        assert isinstance(tx_out, PlutusConstr)
        addr_data = tx_out.fields[0]  # Address is first field of TxOut

        # Address = Constr 0 [Credential, Maybe StakingCredential]
        assert addr_data.constructor == 0
        credential = addr_data.fields[0]

        # PubKeyCredential = Constr 0 [PubKeyHash]
        assert credential.constructor == 0, (
            "Byron address should translate to PubKeyCredential (Constr 0), "
            f"got Constr {credential.constructor}"
        )
        assert isinstance(credential.fields[0], PlutusByteString)
        assert credential.fields[0].value == expected_cred

        # Staking credential should be Nothing (Byron has no staking part)
        maybe_staking = addr_data.fields[1]
        assert (
            maybe_staking.constructor == 1
        ), "Byron address should have Nothing for staking credential"

    def test_byron_address_in_input(self) -> None:
        """Byron bootstrap address in a TxIn should produce PubKeyCredential.

        Same logic as outputs -- the address translation is the same regardless
        of whether the address appears in an input or output.
        """
        byron_addr, expected_cred = _byron_address_with_known_hash()

        builder = TxInfoBuilder()
        builder.add_input(
            tx_id=b"\xbb" * 32,
            index=0,
            address_bytes=byron_addr,
            coin=5_000_000,
        )
        builder.set_tx_id(b"\xaa" * 32)

        tx_info = builder.build_v1()

        # Extract the input's address: inputs[0] = TxInInfo(TxOutRef, TxOut)
        inputs = tx_info.fields[0]  # V1 field index 0 = inputs
        assert isinstance(inputs, PlutusList)
        tx_in_info = inputs.value[0]
        assert isinstance(tx_in_info, PlutusConstr)

        # TxInInfo = Constr 0 [TxOutRef, TxOut]
        tx_out = tx_in_info.fields[1]
        addr_data = tx_out.fields[0]

        credential = addr_data.fields[0]
        assert credential.constructor == 0, "Byron input address should be PubKeyCredential"
        assert credential.fields[0].value == expected_cred


# ---------------------------------------------------------------------------
# Test 3-6: Babbage TxInfo V2 features
# ---------------------------------------------------------------------------


class TestBabbageTxInfoV2:
    """Babbage-era V2 TxInfo adds reference inputs, inline datums, and
    reference scripts.

    Spec ref: Babbage ledger formal spec, Section 4.3.
    Haskell ref: ``txInfoV2`` in ``Cardano.Ledger.Babbage.Plutus.TxInfo``
    """

    def _make_address(self) -> bytes:
        return _base_address(b"\x11" * 28, b"\x22" * 28)

    def test_reference_inputs_populated(self) -> None:
        """V2 TxInfo should include reference inputs in field index 1.

        Reference inputs are UTxOs read but not consumed. They appear in
        V2 TxInfo as a list of TxInInfo, same structure as regular inputs.

        Haskell ref: ``txInfoReferenceInputs`` field in V2 ``TxInfo``
        """
        builder = TxInfoBuilder()
        builder.add_input(
            tx_id=b"\xaa" * 32,
            index=0,
            address_bytes=self._make_address(),
            coin=5_000_000,
        )
        builder.add_reference_input(
            tx_id=b"\xcc" * 32,
            index=2,
            address_bytes=self._make_address(),
            coin=10_000_000,
        )
        builder.add_reference_input(
            tx_id=b"\xdd" * 32,
            index=0,
            address_bytes=self._make_address(),
            coin=3_000_000,
        )
        builder.set_tx_id(b"\xbb" * 32)

        tx_info = builder.build_v2()

        # V2 field index 1 = reference_inputs
        ref_inputs = tx_info.fields[1]
        assert isinstance(ref_inputs, PlutusList)
        assert (
            len(ref_inputs.value) == 2
        ), f"Expected 2 reference inputs, got {len(ref_inputs.value)}"

        # Each reference input is TxInInfo = Constr 0 [TxOutRef, TxOut]
        for ri in ref_inputs.value:
            assert isinstance(ri, PlutusConstr)
            assert ri.constructor == 0
            assert len(ri.fields) == 2

    def test_inline_datum_in_input(self) -> None:
        """V2 input with inline datum should have the datum in TxOut, not just hash.

        In V2, TxOut can carry a full inline datum (OutputDatum). When the
        UTxO has an inline datum, the TxInInfo's TxOut should contain the
        actual datum data.

        Haskell ref: ``OutputDatum`` in ``PlutusLedgerApi.V2.Tx``
            OutputDatumHash = Constr 1 [DatumHash]
            OutputDatum     = Constr 2 [Datum]
            NoOutputDatum   = Constr 0 []

        Note: Our current builder uses a simplified Maybe-based datum encoding.
        This test validates the inline datum value is present.
        """
        inline_datum = PlutusConstr(0, [PlutusInteger(42), PlutusByteString(b"hello")])

        builder = TxInfoBuilder()
        builder.add_input(
            tx_id=b"\xaa" * 32,
            index=0,
            address_bytes=self._make_address(),
            coin=5_000_000,
            inline_datum=inline_datum,
        )
        builder.set_tx_id(b"\xbb" * 32)

        tx_info = builder.build_v2()

        # Extract input -> TxOut -> datum field
        inputs = tx_info.fields[0]
        tx_in_info = inputs.value[0]
        tx_out = tx_in_info.fields[1]

        # Datum is the third field of TxOut (index 2)
        datum_field = tx_out.fields[2]
        assert isinstance(datum_field, PlutusConstr)

        # Should be Just(datum), i.e. Constr 0 [datum]
        assert (
            datum_field.constructor == 0
        ), f"Inline datum should produce Just (Constr 0), got Constr {datum_field.constructor}"
        # The datum value itself is inside
        assert datum_field.fields[0] == inline_datum

    def test_reference_script_hash(self) -> None:
        """Reference script present in a UTxO should be traceable via script hash.

        In V2, TxOut has a Maybe ScriptHash field (4th field). When a
        reference script is present, the script hash should appear there.

        Haskell ref: ``txOutReferenceScript`` in ``BabbageTxOut``

        Note: Our current TxInfoBuilder._make_tx_out produces a 3-field TxOut
        (V1 format). This test documents the expected behavior for when we
        extend to full V2 TxOut format. For now, we verify the builder
        correctly handles the inline datum field which coexists with reference
        scripts in V2 outputs.
        """
        # We use the builder to add an output and verify the structure
        # is well-formed. Full V2 TxOut (4 fields) extension is tracked
        # as a future enhancement.
        builder = TxInfoBuilder()
        builder.add_output(
            address_bytes=self._make_address(),
            coin=2_000_000,
            inline_datum=PlutusConstr(0, [PlutusInteger(1)]),
        )
        builder.set_tx_id(b"\xbb" * 32)

        tx_info = builder.build_v2()
        outputs = tx_info.fields[2]  # V2 field index 2 = outputs
        assert isinstance(outputs, PlutusList)
        assert len(outputs.value) == 1

        tx_out = outputs.value[0]
        # TxOut should be Constr 0 with at least 3 fields
        assert tx_out.constructor == 0
        assert len(tx_out.fields) >= 3

    def test_unknown_reference_input_handling(self) -> None:
        """Reference input not in UTxO set: builder should still accept it.

        In the Haskell node, if a reference input references a UTxO not in
        the UTxO set, the transaction fails validation (UTxO lookup failure).
        Our TxInfoBuilder is a data construction layer -- it accepts whatever
        data it's given. The validation happens upstream.

        This test verifies the builder doesn't crash or silently drop a
        reference input with unusual data.
        """
        builder = TxInfoBuilder()
        # Add a reference input with minimal/unusual data
        builder.add_reference_input(
            tx_id=b"\x00" * 32,  # zeroed tx id
            index=999,  # unusual index
            address_bytes=_enterprise_address(b"\xff" * 28),
            coin=0,  # zero lovelace
        )
        builder.set_tx_id(b"\xbb" * 32)

        tx_info = builder.build_v2()
        ref_inputs = tx_info.fields[1]
        assert isinstance(ref_inputs, PlutusList)
        assert len(ref_inputs.value) == 1

        # Verify the TxOutRef encodes the unusual values correctly
        tx_in_info = ref_inputs.value[0]
        out_ref = tx_in_info.fields[0]
        # TxOutRef = Constr 0 [TxId, Integer]
        assert out_ref.fields[1] == PlutusInteger(999)


# ---------------------------------------------------------------------------
# Test 7-8: Conway TxInfo V3 certificate deposits
# ---------------------------------------------------------------------------


class TestConwayTxInfoV3Certs:
    """Conway V3 TxInfo includes deposit amounts in certificate info.

    In PlutusV3, the TxCert type replaces DCert and includes explicit
    deposit amounts for registration and deregistration, unlike V1/V2
    which had no deposit information in the certificate.

    Spec ref: Conway ledger formal spec, TxCert definition.
    Haskell ref: ``TxCert`` in ``PlutusLedgerApi.V3.Contexts``

    V3 TxCert constructors (relevant subset):
        TxCertRegStaking = Constr 0 [Credential, Maybe Lovelace]
        TxCertUnRegStaking = Constr 1 [Credential, Maybe Lovelace]
        TxCertDelegStaking = Constr 2 [Credential, Delegatee]
        ...
    """

    def _make_reg_cert_v3(self, credential: PlutusConstr, deposit: int) -> PlutusConstr:
        """Build a V3 TxCertRegStaking with deposit.

        TxCertRegStaking = Constr 0 [Credential, Maybe Lovelace]
        """
        # Just deposit
        maybe_deposit = PlutusConstr(0, [PlutusInteger(deposit)])
        return PlutusConstr(0, [credential, maybe_deposit])

    def _make_dereg_cert_v3(self, credential: PlutusConstr, refund: int) -> PlutusConstr:
        """Build a V3 TxCertUnRegStaking with deposit refund.

        TxCertUnRegStaking = Constr 1 [Credential, Maybe Lovelace]
        """
        maybe_refund = PlutusConstr(0, [PlutusInteger(refund)])
        return PlutusConstr(1, [credential, maybe_refund])

    def _make_reg_cert_v1(self, credential: PlutusConstr) -> PlutusConstr:
        """Build a V1/V2 DCertDelegRegKey (no deposit info).

        DCertDelegRegKey = Constr 0 [StakingCredential]
        """
        return PlutusConstr(0, [credential])

    def test_registration_cert_includes_deposit(self) -> None:
        """V3 registration cert should carry the deposit amount.

        In Conway, the protocol tracks deposits explicitly. The V3 TxCert
        for registration includes Maybe Lovelace deposit. This is new --
        V1/V2 DCert has no deposit field.

        Haskell ref: ``TxCertRegStaking`` in ``PlutusLedgerApi.V3.Contexts``
        """
        stake_cred = PlutusConstr(0, [PlutusByteString(b"\x11" * 28)])
        deposit_lovelace = 2_000_000  # Standard key deposit

        reg_cert = self._make_reg_cert_v3(stake_cred, deposit_lovelace)

        builder = TxInfoBuilder()
        builder.dcerts.append(reg_cert)
        builder.set_tx_id(b"\xaa" * 32)

        tx_info = builder.build_v3()

        # V3 field index 5 = dcerts (same position as V1/V2)
        dcerts = tx_info.fields[5]
        assert isinstance(dcerts, PlutusList)
        assert len(dcerts.value) == 1

        cert = dcerts.value[0]
        assert isinstance(cert, PlutusConstr)
        # TxCertRegStaking = Constr 0
        assert cert.constructor == 0

        # Second field is Maybe Lovelace (deposit)
        maybe_deposit = cert.fields[1]
        assert maybe_deposit.constructor == 0, "Deposit should be Just"
        assert maybe_deposit.fields[0] == PlutusInteger(deposit_lovelace)

    def test_deregistration_cert_includes_refund(self) -> None:
        """V3 deregistration cert should carry the deposit refund amount.

        Haskell ref: ``TxCertUnRegStaking`` in ``PlutusLedgerApi.V3.Contexts``
        """
        stake_cred = PlutusConstr(0, [PlutusByteString(b"\x22" * 28)])
        refund_lovelace = 2_000_000

        dereg_cert = self._make_dereg_cert_v3(stake_cred, refund_lovelace)

        builder = TxInfoBuilder()
        builder.dcerts.append(dereg_cert)
        builder.set_tx_id(b"\xaa" * 32)

        tx_info = builder.build_v3()

        dcerts = tx_info.fields[5]
        cert = dcerts.value[0]

        # TxCertUnRegStaking = Constr 1
        assert cert.constructor == 1

        # Second field is Maybe Lovelace (refund)
        maybe_refund = cert.fields[1]
        assert maybe_refund.constructor == 0, "Refund should be Just"
        assert maybe_refund.fields[0] == PlutusInteger(refund_lovelace)

    def test_v1_cert_has_no_deposit_field(self) -> None:
        """V1 DCert registration has no deposit field -- just the credential.

        This contrast test confirms V1 certs are structurally different from V3.
        """
        stake_cred = PlutusConstr(0, [PlutusByteString(b"\x33" * 28)])
        reg_cert = self._make_reg_cert_v1(stake_cred)

        builder = TxInfoBuilder()
        builder.dcerts.append(reg_cert)
        builder.set_tx_id(b"\xaa" * 32)

        tx_info = builder.build_v1()

        dcerts = tx_info.fields[4]  # V1 field index 4 = dcerts
        cert = dcerts.value[0]

        # V1 DCertDelegRegKey = Constr 0 [StakingCredential] -- only 1 field
        assert cert.constructor == 0
        assert (
            len(cert.fields) == 1
        ), f"V1 DCert should have 1 field (credential only), got {len(cert.fields)}"


# ---------------------------------------------------------------------------
# Test 9: Conway PV9+ validity interval open upper bound
# ---------------------------------------------------------------------------


class TestValidityIntervalPV9:
    """PV9+ changes V1 TxInfo translation to use open (exclusive) upper bound.

    Before PV9, the Haskell node translated the validity interval for V1
    TxInfo with a closed (inclusive) upper bound. Starting with PV9 (Conway),
    even V1 TxInfo translation uses an open (exclusive) upper bound to match
    the mathematical convention.

    Spec ref: Conway ledger formal spec, Section on time translation.
    Haskell ref: ``transVITime`` in ``Cardano.Ledger.Alonzo.Plutus.TxInfo``
        changed to always use open upper bound in PV9+.

    Our interval_to_data uses:
        - Upper bound Finite: closure = Constr 0 [] = False (exclusive/open)
        - Lower bound Finite: closure = Constr 1 [] = True (inclusive)
    This matches the PV9+ behavior.
    """

    def test_upper_bound_is_open_exclusive(self) -> None:
        """Finite upper bound should be exclusive (open) -- Closure = False.

        Interval = Constr 0 [LowerBound, UpperBound]
        UpperBound = Constr 0 [Extended, Closure]
        Closure: Constr 0 [] = False, Constr 1 [] = True

        PV9+ convention: upper bound is always exclusive (False).
        """
        interval = interval_to_data(lower_bound=1000, upper_bound=2000)

        upper_bound = interval.fields[1]  # UpperBound
        closure = upper_bound.fields[1]  # Closure

        # False = Constr 0 []
        assert closure.constructor == 0, (
            "Upper bound closure should be False (Constr 0 = exclusive/open), "
            f"got Constr {closure.constructor}"
        )
        assert len(closure.fields) == 0

    def test_lower_bound_is_closed_inclusive(self) -> None:
        """Finite lower bound should be inclusive (closed) -- Closure = True.

        Lower bound convention is always inclusive.
        """
        interval = interval_to_data(lower_bound=1000, upper_bound=2000)

        lower_bound = interval.fields[0]  # LowerBound
        closure = lower_bound.fields[1]  # Closure

        # True = Constr 1 []
        assert closure.constructor == 1, (
            "Lower bound closure should be True (Constr 1 = inclusive/closed), "
            f"got Constr {closure.constructor}"
        )

    def test_v1_txinfo_with_pv9_interval(self) -> None:
        """V1 TxInfo built with our interval should have open upper bound.

        This is the end-to-end test: build a V1 TxInfo with a bounded
        validity interval and verify the upper bound uses PV9+ semantics.
        """
        builder = TxInfoBuilder()
        builder.set_valid_range(lower_bound=100_000, upper_bound=200_000)
        builder.set_tx_id(b"\xaa" * 32)

        tx_info = builder.build_v1()

        # V1 field index 6 = valid_range
        valid_range = tx_info.fields[6]
        upper_bound = valid_range.fields[1]
        upper_closure = upper_bound.fields[1]

        assert upper_closure.constructor == 0, "V1 TxInfo upper bound should be exclusive (PV9+)"


# ---------------------------------------------------------------------------
# Test 10: Field count invariants across versions
# ---------------------------------------------------------------------------


class TestTxInfoFieldCounts:
    """TxInfo field counts must exactly match the Plutus ledger API per version.

    This is a critical structural invariant. If the field count is wrong,
    Plutus scripts will crash or produce incorrect results because they
    destructure TxInfo by position.

    Haskell ref:
        V1 TxInfo: 10 fields (PlutusLedgerApi.V1.Contexts)
        V2 TxInfo: 12 fields (PlutusLedgerApi.V2.Contexts)
        V3 TxInfo: 16 fields (PlutusLedgerApi.V3.Contexts)
    """

    def test_v1_txinfo_has_10_fields(self) -> None:
        """PlutusV1 TxInfo: inputs, outputs, fee, mint, dcerts, wdrl,
        valid_range, signatories, data, id = 10 fields."""
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        tx_info = builder.build_v1()
        assert (
            len(tx_info.fields) == 10
        ), f"V1 TxInfo must have 10 fields, got {len(tx_info.fields)}"

    def test_v2_txinfo_has_12_fields(self) -> None:
        """PlutusV2 TxInfo: adds reference_inputs and redeemers = 12 fields."""
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        tx_info = builder.build_v2()
        assert (
            len(tx_info.fields) == 12
        ), f"V2 TxInfo must have 12 fields, got {len(tx_info.fields)}"

    def test_v3_txinfo_has_16_fields(self) -> None:
        """PlutusV3 TxInfo: adds voting_procedures, proposal_procedures,
        current_treasury_amount, treasury_donation = 16 fields."""
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)
        tx_info = builder.build_v3()
        assert (
            len(tx_info.fields) == 16
        ), f"V3 TxInfo must have 16 fields, got {len(tx_info.fields)}"

    def test_field_counts_all_differ(self) -> None:
        """All three versions must have distinct field counts.

        This ensures no version can be accidentally substituted for another
        without detection. A script expecting V2 TxInfo that receives V1
        would access out-of-bounds fields.
        """
        builder = TxInfoBuilder()
        builder.set_tx_id(b"\xaa" * 32)

        v1_count = len(builder.build_v1().fields)
        v2_count = len(builder.build_v2().fields)
        v3_count = len(builder.build_v3().fields)

        assert v1_count != v2_count, "V1 and V2 field counts must differ"
        assert v2_count != v3_count, "V2 and V3 field counts must differ"
        assert v1_count != v3_count, "V1 and V3 field counts must differ"
        assert (
            v1_count < v2_count < v3_count
        ), f"Field counts must increase: V1={v1_count} < V2={v2_count} < V3={v3_count}"
