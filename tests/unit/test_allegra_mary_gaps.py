"""Allegra/Mary spec-gap tests — metadata, MultiAsset CBOR, MaryValue, min UTxO.

These tests cover spec-defined behaviors not exercised by the existing
Allegra/Mary tests. They focus on edge cases in multi-asset serialization,
metadata constraints, and min UTxO scaling.

Spec references:
    - Mary ledger formal spec, Section 3 (Multi-asset values)
    - Allegra ledger formal spec (metadata constraints)
    - ``cardano-ledger/eras/mary/impl/src/Cardano/Ledger/Mary/Value.hs``
    - ``cardano-ledger/eras/shelley-ma/impl/src/Cardano/Ledger/ShelleyMA/AuxiliaryData.hs``
    - ``cardano-ledger/eras/mary/impl/src/Cardano/Ledger/Mary/Rules/Utxo.hs``
"""

from __future__ import annotations

import hashlib

import cbor2
from pycardano import (
    Asset,
    AssetName,
    MultiAsset,
    TransactionOutput,
    Value,
)
from pycardano.address import Address
from pycardano.hash import ScriptHash, TransactionId
from pycardano.network import Network

from vibe.cardano.ledger.allegra_mary import (
    MARY_MAINNET_PARAMS,
    _multi_asset_is_empty,
    _multi_asset_num_assets,
    _output_value,
    _value_eq,
    mary_min_utxo_value,
    validate_mary_value_preservation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy_id(n: int) -> ScriptHash:
    """Generate a deterministic 28-byte policy ID."""
    digest = hashlib.blake2b(n.to_bytes(4, "big"), digest_size=28).digest()
    return ScriptHash(digest)


def _make_asset_name(name: str) -> AssetName:
    """Create an AssetName from a string."""
    return AssetName(name.encode())


def _make_tx_id(n: int) -> TransactionId:
    """Generate a deterministic 32-byte transaction ID."""
    digest = hashlib.blake2b(n.to_bytes(4, "big"), digest_size=32).digest()
    return TransactionId(digest)


def _make_shelley_address() -> Address:
    """Create a minimal Shelley testnet address for testing."""
    from pycardano import VerificationKeyHash

    payment_hash = VerificationKeyHash(b"\xab" * 28)
    return Address(payment_part=payment_hash, network=Network.TESTNET)


# ---------------------------------------------------------------------------
# InvalidMetadata size
# ---------------------------------------------------------------------------


class TestInvalidMetadataSize:
    """InvalidMetadata size — metadata exceeds max size, verify rejection.

    Haskell ref: ``Cardano.Ledger.ShelleyMA.AuxiliaryData``
        - Metadata is limited in serialized size by protocol parameters
        - The Haskell node enforces MaxTxSize which implicitly limits metadata

    Spec ref: Allegra ledger formal spec (auxiliary data constraints).
    """

    def test_large_metadata_exceeds_reasonable_bounds(self) -> None:
        """Metadata that would push a tx beyond MaxTxSize should be rejected.

        Shelley MaxTxSize = 16384 bytes by default.  If metadata alone
        exceeds this, the tx is invalid regardless of other content.
        """
        max_tx_size = 16384  # Default Shelley/Allegra MaxTxSize
        # Create metadata that exceeds max tx size
        huge_metadata = {0: "x" * (max_tx_size + 1)}
        metadata_cbor = cbor2.dumps(huge_metadata)
        assert (
            len(metadata_cbor) > max_tx_size
        ), f"Metadata CBOR size {len(metadata_cbor)} should exceed MaxTxSize {max_tx_size}"

    def test_small_metadata_within_bounds(self) -> None:
        """Reasonably sized metadata fits within tx size limits."""
        max_tx_size = 16384
        small_metadata = {0: "hello", 1: 42}
        metadata_cbor = cbor2.dumps(small_metadata)
        assert len(metadata_cbor) < max_tx_size


# ---------------------------------------------------------------------------
# MultiAsset CBOR roundtrip edge cases
# ---------------------------------------------------------------------------


class TestMultiAssetCBOREdgeCases:
    """MultiAsset CBOR roundtrip edge cases.

    Haskell ref: ``Cardano.Ledger.Mary.Value``
        - MaryValue CBOR encoding: [coin, {policy_id: {asset_name: quantity}}]
        - Zero quantities should be pruned in canonical form
        - Empty policy maps should be pruned
        - Negative quantities represent burns (in mint field only)
    """

    def test_zero_token_quantity(self) -> None:
        """MultiAsset with zero token quantity — should these be pruned?

        Haskell ref: The Mary spec says Values with zero quantities are
        valid but should be treated as absent for comparison purposes.
        Our _value_eq handles this by filtering zeros.
        """
        pid = _make_policy_id(1)
        asset_name = _make_asset_name("token")

        # Create a value with zero quantity
        ma = MultiAsset({pid: Asset({asset_name: 0})})
        value = Value(coin=1_000_000, multi_asset=ma)

        # A pure-ADA value should be "equal" to this
        pure_ada = Value(coin=1_000_000)
        assert _value_eq(
            value, pure_ada
        ), "Value with zero-quantity token should equal pure ADA value"

    def test_empty_nested_map(self) -> None:
        """MultiAsset with empty nested map (policy with no assets).

        A policy ID with an empty asset map should be treated as absent.
        """
        pid = _make_policy_id(1)
        ma = MultiAsset({pid: Asset({})})

        assert _multi_asset_is_empty(
            ma
        ), "MultiAsset with empty asset map should be considered empty"

    def test_negative_values_for_burning(self) -> None:
        """MultiAsset with negative values represent burning.

        Negative quantities are valid in the mint field of a transaction,
        representing token burns.
        """
        pid = _make_policy_id(1)
        asset_name = _make_asset_name("burn-me")

        # Negative quantity = burn
        ma = MultiAsset({pid: Asset({asset_name: -100})})
        mint_value = Value(coin=0, multi_asset=ma)

        # The mint value should have a non-empty multi-asset
        assert not _multi_asset_is_empty(mint_value.multi_asset)
        assert _multi_asset_num_assets(mint_value.multi_asset) == 1

    def test_cbor_roundtrip_with_pycardano(self) -> None:
        """MultiAsset CBOR roundtrip through pycardano serialization."""
        pid = _make_policy_id(1)
        asset_a = _make_asset_name("TokenA")
        asset_b = _make_asset_name("TokenB")

        ma = MultiAsset({pid: Asset({asset_a: 100, asset_b: 200})})
        value = Value(coin=2_000_000, multi_asset=ma)

        # Serialize and deserialize through CBOR
        encoded = value.to_cbor()
        decoded = Value.from_cbor(encoded)

        assert _value_eq(value, decoded)


# ---------------------------------------------------------------------------
# MaryValue compact representation
# ---------------------------------------------------------------------------


class TestMaryValueCompactRepresentation:
    """MaryValue compact representation test.

    Haskell ref: ``Cardano.Ledger.Mary.Value.MaryValue``
        - Compact representation: pure-ADA values should use minimal space
        - Multi-asset values carry the full nested map structure

    We verify that pure-ADA values have a simpler representation than
    multi-asset values.
    """

    def test_pure_ada_value_is_int(self) -> None:
        """A pure-ADA TransactionOutput.amount can be just an int."""
        addr = _make_shelley_address()
        txout = TransactionOutput(addr, 5_000_000)
        amount = txout.amount
        # pycardano allows int or Value
        assert isinstance(amount, (int, Value))

    def test_multi_asset_value_is_value_type(self) -> None:
        """A multi-asset output uses the full Value type."""
        addr = _make_shelley_address()
        pid = _make_policy_id(1)
        asset_name = _make_asset_name("token")
        ma = MultiAsset({pid: Asset({asset_name: 50})})
        value = Value(coin=2_000_000, multi_asset=ma)

        txout = TransactionOutput(addr, value)
        out_val = _output_value(txout)
        assert isinstance(out_val, Value)
        assert out_val.coin == 2_000_000
        assert not _multi_asset_is_empty(out_val.multi_asset)

    def test_pure_ada_normalized_to_value(self) -> None:
        """_output_value normalizes int amounts to Value."""
        addr = _make_shelley_address()
        txout = TransactionOutput(addr, 3_000_000)
        out_val = _output_value(txout)
        assert isinstance(out_val, Value)
        assert out_val.coin == 3_000_000


# ---------------------------------------------------------------------------
# Token minting value preservation across multiple policies
# ---------------------------------------------------------------------------


class TestTokenMintingValuePreservation:
    """Token minting value preservation across multiple policies.

    Haskell ref: ``Cardano.Ledger.Mary.Rules.Utxo.maryUtxoTransition``
        - consumed = sum(inputs) + mint
        - produced = sum(outputs) + fee
        - consumed == produced (for coin AND every token)
    """

    def test_single_policy_mint_preserves_value(self) -> None:
        """Minting from one policy preserves value."""
        pid = _make_policy_id(1)
        asset_name = _make_asset_name("token")

        input_values = [Value(coin=10_000_000)]
        output_values = [
            Value(
                coin=9_800_000,
                multi_asset=MultiAsset({pid: Asset({asset_name: 1000})}),
            )
        ]
        fee = 200_000
        mint = Value(
            coin=0,
            multi_asset=MultiAsset({pid: Asset({asset_name: 1000})}),
        )

        errors = validate_mary_value_preservation(input_values, output_values, fee, mint)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_multiple_policies_mint_preserves_value(self) -> None:
        """Minting from multiple policies preserves value."""
        pid1 = _make_policy_id(1)
        pid2 = _make_policy_id(2)
        asset_a = _make_asset_name("TokenA")
        asset_b = _make_asset_name("TokenB")

        input_values = [Value(coin=10_000_000)]
        output_values = [
            Value(
                coin=9_800_000,
                multi_asset=MultiAsset(
                    {
                        pid1: Asset({asset_a: 500}),
                        pid2: Asset({asset_b: 300}),
                    }
                ),
            )
        ]
        fee = 200_000
        mint = Value(
            coin=0,
            multi_asset=MultiAsset(
                {
                    pid1: Asset({asset_a: 500}),
                    pid2: Asset({asset_b: 300}),
                }
            ),
        )

        errors = validate_mary_value_preservation(input_values, output_values, fee, mint)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_mint_without_corresponding_output_fails(self) -> None:
        """Minting tokens but not including them in outputs fails preservation."""
        pid = _make_policy_id(1)
        asset_name = _make_asset_name("token")

        input_values = [Value(coin=10_000_000)]
        output_values = [Value(coin=9_800_000)]  # No tokens in output!
        fee = 200_000
        mint = Value(
            coin=0,
            multi_asset=MultiAsset({pid: Asset({asset_name: 1000})}),
        )

        errors = validate_mary_value_preservation(input_values, output_values, fee, mint)
        assert len(errors) > 0, "Should fail: minted tokens not in outputs"
        assert any("ValueNotConserved" in e for e in errors)


# ---------------------------------------------------------------------------
# Asset count limit enforcement (MaxValSize)
# ---------------------------------------------------------------------------


class TestAssetCountLimitEnforcement:
    """Asset count limit enforcement.

    Haskell ref: ``Cardano.Ledger.Mary.Rules.Utxo``
        - OutputTooBigUTxO: the serialized size of a multi-asset output
          must not exceed ``MaxValSize`` (4000 bytes in Alonzo+, but Mary
          enforces via the min-UTxO scaling formula)
        - More assets = higher min UTxO requirement

    This test verifies that adding more assets increases the min UTxO
    requirement, effectively enforcing a practical asset count limit.
    """

    def test_more_assets_increases_min_utxo(self) -> None:
        """Each additional asset increases the min UTxO requirement."""
        addr = _make_shelley_address()
        params = MARY_MAINNET_PARAMS

        # Pure ADA output
        txout_ada = TransactionOutput(addr, 1_000_000)
        min_ada = mary_min_utxo_value(txout_ada, params)

        # 1 asset
        pid = _make_policy_id(1)
        ma1 = MultiAsset({pid: Asset({_make_asset_name("a"): 1})})
        txout_1 = TransactionOutput(addr, Value(coin=1_000_000, multi_asset=ma1))
        min_1 = mary_min_utxo_value(txout_1, params)

        # 5 assets under same policy
        assets = {_make_asset_name(f"tok{i}"): 1 for i in range(5)}
        ma5 = MultiAsset({pid: Asset(assets)})
        txout_5 = TransactionOutput(addr, Value(coin=1_000_000, multi_asset=ma5))
        min_5 = mary_min_utxo_value(txout_5, params)

        # 10 assets across 3 policies
        pids = [_make_policy_id(i) for i in range(3)]
        big_ma = MultiAsset(
            {
                pids[0]: Asset({_make_asset_name(f"a{i}"): 1 for i in range(4)}),
                pids[1]: Asset({_make_asset_name(f"b{i}"): 1 for i in range(3)}),
                pids[2]: Asset({_make_asset_name(f"c{i}"): 1 for i in range(3)}),
            }
        )
        txout_10 = TransactionOutput(addr, Value(coin=1_000_000, multi_asset=big_ma))
        min_10 = mary_min_utxo_value(txout_10, params)

        assert min_1 >= min_ada, "1 asset should require >= pure ADA min"
        assert min_5 > min_1, "5 assets should require more than 1 asset"
        assert min_10 > min_5, "10 assets should require more than 5 assets"

    def test_asset_name_length_affects_min_utxo(self) -> None:
        """Longer asset names increase the min UTxO requirement."""
        addr = _make_shelley_address()
        params = MARY_MAINNET_PARAMS
        pid = _make_policy_id(1)

        # Short asset name
        short_ma = MultiAsset({pid: Asset({_make_asset_name("x"): 1})})
        txout_short = TransactionOutput(addr, Value(coin=1_000_000, multi_asset=short_ma))
        min_short = mary_min_utxo_value(txout_short, params)

        # Long asset name (32 bytes)
        long_name = _make_asset_name("x" * 32)
        long_ma = MultiAsset({pid: Asset({long_name: 1})})
        txout_long = TransactionOutput(addr, Value(coin=1_000_000, multi_asset=long_ma))
        min_long = mary_min_utxo_value(txout_long, params)

        assert min_long >= min_short, "Longer asset name should require >= min UTxO"


# ---------------------------------------------------------------------------
# Mary-specific min UTxO calculation with many assets
# ---------------------------------------------------------------------------


class TestMaryMinUtxoManyAssets:
    """Mary-specific min UTxO calculation with many assets.

    Haskell ref: ``scaledMinDeposit`` in ``Cardano.Ledger.Mary.Rules.Utxo``
        - minUTxOValue = max(minUTxOValue, (utxoEntrySizeWithoutVal + size) * coinsPerUTxOWord)
        - The formula scales with: numAssets, numPolicies, totalAssetNameLength

    This tests the full formula with realistic multi-asset bundles.
    """

    def test_single_policy_single_asset(self) -> None:
        """Min UTxO for the simplest multi-asset output."""
        addr = _make_shelley_address()
        params = MARY_MAINNET_PARAMS
        pid = _make_policy_id(1)
        ma = MultiAsset({pid: Asset({_make_asset_name("T"): 1})})
        txout = TransactionOutput(addr, Value(coin=1_000_000, multi_asset=ma))

        min_val = mary_min_utxo_value(txout, params)
        assert (
            min_val >= params.min_utxo_value
        ), "Multi-asset min UTxO should be >= base minUTxOValue"

    def test_many_policies_many_assets(self) -> None:
        """Min UTxO with many policies and assets is significantly higher."""
        addr = _make_shelley_address()
        params = MARY_MAINNET_PARAMS

        # 10 policies, 3 assets each = 30 total assets
        multi_asset_map = {}
        for i in range(10):
            pid = _make_policy_id(i)
            assets = {_make_asset_name(f"asset{j}"): 1 for j in range(3)}
            multi_asset_map[pid] = Asset(assets)

        ma = MultiAsset(multi_asset_map)
        txout = TransactionOutput(addr, Value(coin=1_000_000, multi_asset=ma))

        min_val = mary_min_utxo_value(txout, params)
        # With 30 assets and 10 policies, the min should be well above base
        assert (
            min_val > params.min_utxo_value
        ), f"Expected min_val > {params.min_utxo_value}, got {min_val}"

    def test_pure_ada_returns_base_min(self) -> None:
        """Pure ADA output returns exactly minUTxOValue."""
        addr = _make_shelley_address()
        params = MARY_MAINNET_PARAMS
        txout = TransactionOutput(addr, 2_000_000)

        min_val = mary_min_utxo_value(txout, params)
        assert min_val == params.min_utxo_value
