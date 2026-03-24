"""Tests for Allegra and Mary era ledger validation rules.

Tests cover:
    - ValidityInterval edge cases (both bounds, one bound, neither)
    - Timelock script evaluation (AllOf, AnyOf, MOfN, RequireSignature,
      RequireTimeAfter, RequireTimeBefore)
    - Multi-asset value preservation (with and without minting)
    - Min UTxO with multi-asset outputs
    - Mary full transaction validation

Spec references:
    - Allegra ledger formal spec (ValidityInterval, Timelock)
    - Mary ledger formal spec, Section 3 (Multi-asset)
    - ``cardano-ledger/eras/allegra/impl/src/Cardano/Ledger/Allegra/Rules/Utxo.hs``
    - ``cardano-ledger/eras/mary/impl/src/Cardano/Ledger/Mary/Rules/Utxo.hs``
"""

from __future__ import annotations

import hashlib

import pytest
from pycardano import (
    Asset,
    MultiAsset,
    TransactionBody,
    TransactionInput,
    TransactionOutput,
    Value,
)
from pycardano.address import Address
from pycardano.hash import ScriptHash, TransactionId
from pycardano.key import PaymentSigningKey, PaymentVerificationKey
from pycardano.network import Network
from pycardano.witness import TransactionWitnessSet

from vibe.cardano.ledger.allegra_mary import (
    MARY_MAINNET_PARAMS,
    AllegraValidationError,
    MaryProtocolParams,
    Timelock,
    TimelockType,
    ValidityInterval,
    _output_value,
    _sum_values,
    _value_eq,
    evaluate_timelock,
    mary_min_utxo_value,
    validate_allegra_utxo,
    validate_mary_tx,
    validate_mary_value_preservation,
    validate_validity_interval,
)
from vibe.cardano.ledger.shelley import ShelleyUTxO

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

TEST_PARAMS = MaryProtocolParams(
    min_fee_a=1,
    min_fee_b=100,
    max_tx_size=16384,
    min_utxo_value=1_000_000,
    key_deposit=2_000_000,
    pool_deposit=500_000_000,
)


def make_tx_id(seed: int = 0) -> TransactionId:
    """Create a deterministic TransactionId from a seed."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=32).digest()
    return TransactionId(digest)


def make_key_pair(
    seed: int = 0,
) -> tuple[PaymentSigningKey, PaymentVerificationKey]:
    """Create a deterministic signing/verification key pair."""
    seed_bytes = seed.to_bytes(32, "big")
    sk = PaymentSigningKey(seed_bytes)
    vk = sk.to_verification_key()
    return sk, vk


def make_address(vk: PaymentVerificationKey) -> Address:
    """Create a Shelley enterprise address from a verification key."""
    return Address(payment_part=vk.hash(), network=Network.TESTNET)


def make_key_hash(seed: int = 0) -> bytes:
    """Create a deterministic 28-byte key hash."""
    return hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=28).digest()


def make_policy_id(seed: int = 0) -> ScriptHash:
    """Create a deterministic ScriptHash (28 bytes)."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=28).digest()
    return ScriptHash(digest)


def make_simple_utxo(
    tx_id_seed: int = 0,
    index: int = 0,
    value: int | Value = 10_000_000,
    seed: int = 0,
) -> tuple[ShelleyUTxO, TransactionInput, PaymentSigningKey, PaymentVerificationKey]:
    """Create a simple UTxO set with one entry."""
    sk, vk = make_key_pair(seed)
    addr = make_address(vk)
    tx_id = make_tx_id(tx_id_seed)
    txin = TransactionInput(tx_id, index)
    txout = TransactionOutput(addr, value)
    utxo_set: ShelleyUTxO = {txin: txout}
    return utxo_set, txin, sk, vk


# ---------------------------------------------------------------------------
# ValidityInterval tests
# ---------------------------------------------------------------------------


class TestValidityInterval:
    """Tests for Allegra ValidityInterval validation."""

    def test_both_bounds_valid(self):
        """Slot within both bounds should pass."""
        interval = ValidityInterval(invalid_before=10, invalid_hereafter=100)
        errors = validate_validity_interval(interval, current_slot=50)
        assert errors == []

    def test_both_bounds_at_lower_boundary(self):
        """Slot exactly at invalid_before should pass (inclusive)."""
        interval = ValidityInterval(invalid_before=50, invalid_hereafter=100)
        errors = validate_validity_interval(interval, current_slot=50)
        assert errors == []

    def test_both_bounds_just_below_upper(self):
        """Slot one less than invalid_hereafter should pass."""
        interval = ValidityInterval(invalid_before=10, invalid_hereafter=100)
        errors = validate_validity_interval(interval, current_slot=99)
        assert errors == []

    def test_both_bounds_at_upper_boundary(self):
        """Slot exactly at invalid_hereafter should fail (exclusive)."""
        interval = ValidityInterval(invalid_before=10, invalid_hereafter=100)
        errors = validate_validity_interval(interval, current_slot=100)
        assert any("OutsideValidityIntervalUTxO" in e for e in errors)
        assert any("invalid_hereafter" in e for e in errors)

    def test_below_lower_bound(self):
        """Slot below invalid_before should fail."""
        interval = ValidityInterval(invalid_before=50, invalid_hereafter=100)
        errors = validate_validity_interval(interval, current_slot=49)
        assert any("OutsideValidityIntervalUTxO" in e for e in errors)
        assert any("invalid_before" in e for e in errors)

    def test_above_upper_bound(self):
        """Slot above invalid_hereafter should fail."""
        interval = ValidityInterval(invalid_before=10, invalid_hereafter=100)
        errors = validate_validity_interval(interval, current_slot=200)
        assert any("OutsideValidityIntervalUTxO" in e for e in errors)

    def test_only_lower_bound(self):
        """Only invalid_before set — no upper bound constraint."""
        interval = ValidityInterval(invalid_before=50, invalid_hereafter=None)
        # Valid: at lower bound
        assert validate_validity_interval(interval, current_slot=50) == []
        # Valid: well past lower bound
        assert validate_validity_interval(interval, current_slot=999999) == []
        # Invalid: below lower bound
        errors = validate_validity_interval(interval, current_slot=49)
        assert any("OutsideValidityIntervalUTxO" in e for e in errors)

    def test_only_upper_bound(self):
        """Only invalid_hereafter set — no lower bound constraint."""
        interval = ValidityInterval(invalid_before=None, invalid_hereafter=100)
        # Valid: slot 0
        assert validate_validity_interval(interval, current_slot=0) == []
        # Valid: just below
        assert validate_validity_interval(interval, current_slot=99) == []
        # Invalid: at upper bound
        errors = validate_validity_interval(interval, current_slot=100)
        assert any("OutsideValidityIntervalUTxO" in e for e in errors)

    def test_neither_bound(self):
        """No bounds — always valid."""
        interval = ValidityInterval(invalid_before=None, invalid_hereafter=None)
        assert validate_validity_interval(interval, current_slot=0) == []
        assert validate_validity_interval(interval, current_slot=999999) == []

    def test_zero_width_interval(self):
        """Interval where invalid_before == invalid_hereafter — never valid.

        If invalid_before=50 and invalid_hereafter=50, then we need
        current_slot >= 50 AND current_slot < 50, which is impossible.
        """
        interval = ValidityInterval(invalid_before=50, invalid_hereafter=50)
        # At slot 50: passes lower (50 >= 50) but fails upper (50 >= 50)
        errors = validate_validity_interval(interval, current_slot=50)
        assert any("invalid_hereafter" in e for e in errors)
        # At slot 49: fails lower (49 < 50)
        errors = validate_validity_interval(interval, current_slot=49)
        assert any("invalid_before" in e for e in errors)

    def test_both_bounds_violated(self):
        """Absurd interval that fails both sides should report both errors.

        E.g., invalid_before=100, invalid_hereafter=50 — slot 75 is
        >= 50 (fails upper) and < 100 (fails lower).
        """
        interval = ValidityInterval(invalid_before=100, invalid_hereafter=50)
        errors = validate_validity_interval(interval, current_slot=75)
        assert len(errors) == 2
        assert any("invalid_before" in e for e in errors)
        assert any("invalid_hereafter" in e for e in errors)


# ---------------------------------------------------------------------------
# Timelock script tests
# ---------------------------------------------------------------------------


class TestTimelock:
    """Tests for Allegra timelock script evaluation."""

    def test_require_signature_present(self):
        """RequireSignature passes when key hash is in signers."""
        kh = make_key_hash(0)
        script = Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh)
        assert evaluate_timelock(script, frozenset({kh}), current_slot=0) is True

    def test_require_signature_missing(self):
        """RequireSignature fails when key hash is not in signers."""
        kh = make_key_hash(0)
        other = make_key_hash(1)
        script = Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh)
        assert evaluate_timelock(script, frozenset({other}), current_slot=0) is False

    def test_require_signature_empty_signers(self):
        """RequireSignature fails with empty signers set."""
        kh = make_key_hash(0)
        script = Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh)
        assert evaluate_timelock(script, frozenset(), current_slot=0) is False

    def test_all_of_all_satisfied(self):
        """AllOf passes when all sub-scripts are satisfied."""
        kh0 = make_key_hash(0)
        kh1 = make_key_hash(1)
        script = Timelock(
            type=TimelockType.REQUIRE_ALL_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh0),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh1),
            ),
        )
        assert evaluate_timelock(script, frozenset({kh0, kh1}), current_slot=0)

    def test_all_of_one_missing(self):
        """AllOf fails when one sub-script is not satisfied."""
        kh0 = make_key_hash(0)
        kh1 = make_key_hash(1)
        script = Timelock(
            type=TimelockType.REQUIRE_ALL_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh0),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh1),
            ),
        )
        assert not evaluate_timelock(script, frozenset({kh0}), current_slot=0)

    def test_all_of_empty(self):
        """AllOf with no sub-scripts is vacuously true."""
        script = Timelock(type=TimelockType.REQUIRE_ALL_OF, scripts=())
        assert evaluate_timelock(script, frozenset(), current_slot=0)

    def test_any_of_one_satisfied(self):
        """AnyOf passes when at least one sub-script is satisfied."""
        kh0 = make_key_hash(0)
        kh1 = make_key_hash(1)
        script = Timelock(
            type=TimelockType.REQUIRE_ANY_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh0),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh1),
            ),
        )
        assert evaluate_timelock(script, frozenset({kh1}), current_slot=0)

    def test_any_of_none_satisfied(self):
        """AnyOf fails when no sub-scripts are satisfied."""
        kh0 = make_key_hash(0)
        kh1 = make_key_hash(1)
        script = Timelock(
            type=TimelockType.REQUIRE_ANY_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh0),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh1),
            ),
        )
        assert not evaluate_timelock(script, frozenset(), current_slot=0)

    def test_any_of_empty(self):
        """AnyOf with no sub-scripts fails (no script to satisfy)."""
        script = Timelock(type=TimelockType.REQUIRE_ANY_OF, scripts=())
        assert not evaluate_timelock(script, frozenset(), current_slot=0)

    def test_m_of_n_exact(self):
        """MOfN passes when exactly M of N sub-scripts are satisfied."""
        kh0 = make_key_hash(0)
        kh1 = make_key_hash(1)
        kh2 = make_key_hash(2)
        script = Timelock(
            type=TimelockType.REQUIRE_M_OF_N,
            required=2,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh0),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh1),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh2),
            ),
        )
        assert evaluate_timelock(script, frozenset({kh0, kh2}), current_slot=0)

    def test_m_of_n_too_few(self):
        """MOfN fails when fewer than M sub-scripts are satisfied."""
        kh0 = make_key_hash(0)
        kh1 = make_key_hash(1)
        kh2 = make_key_hash(2)
        script = Timelock(
            type=TimelockType.REQUIRE_M_OF_N,
            required=2,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh0),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh1),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh2),
            ),
        )
        assert not evaluate_timelock(script, frozenset({kh0}), current_slot=0)

    def test_m_of_n_more_than_required(self):
        """MOfN passes when more than M sub-scripts are satisfied."""
        kh0 = make_key_hash(0)
        kh1 = make_key_hash(1)
        kh2 = make_key_hash(2)
        script = Timelock(
            type=TimelockType.REQUIRE_M_OF_N,
            required=2,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh0),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh1),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh2),
            ),
        )
        assert evaluate_timelock(script, frozenset({kh0, kh1, kh2}), current_slot=0)

    def test_require_time_after_satisfied(self):
        """RequireTimeAfter passes when current_slot >= slot."""
        script = Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=100)
        assert evaluate_timelock(script, frozenset(), current_slot=100)
        assert evaluate_timelock(script, frozenset(), current_slot=200)

    def test_require_time_after_not_satisfied(self):
        """RequireTimeAfter fails when current_slot < slot."""
        script = Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=100)
        assert not evaluate_timelock(script, frozenset(), current_slot=99)

    def test_require_time_before_satisfied(self):
        """RequireTimeBefore passes when current_slot < slot."""
        script = Timelock(type=TimelockType.REQUIRE_TIME_BEFORE, slot=100)
        assert evaluate_timelock(script, frozenset(), current_slot=99)
        assert evaluate_timelock(script, frozenset(), current_slot=0)

    def test_require_time_before_not_satisfied(self):
        """RequireTimeBefore fails when current_slot >= slot."""
        script = Timelock(type=TimelockType.REQUIRE_TIME_BEFORE, slot=100)
        assert not evaluate_timelock(script, frozenset(), current_slot=100)
        assert not evaluate_timelock(script, frozenset(), current_slot=200)

    def test_nested_timelock(self):
        """Nested timelock: AllOf(RequireSignature, RequireTimeAfter)."""
        kh = make_key_hash(0)
        script = Timelock(
            type=TimelockType.REQUIRE_ALL_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh),
                Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=50),
            ),
        )
        # Both satisfied
        assert evaluate_timelock(script, frozenset({kh}), current_slot=50)
        # Signature present but too early
        assert not evaluate_timelock(script, frozenset({kh}), current_slot=49)
        # Right time but no signature
        assert not evaluate_timelock(script, frozenset(), current_slot=50)


# ---------------------------------------------------------------------------
# Multi-asset value preservation tests
# ---------------------------------------------------------------------------


class TestMaryValuePreservation:
    """Tests for Mary multi-asset value preservation."""

    def test_ada_only_balanced(self):
        """Pure ADA transaction — balanced."""
        inputs = [Value(coin=10_000_000)]
        outputs = [Value(coin=8_000_000)]
        errors = validate_mary_value_preservation(inputs, outputs, fee=2_000_000)
        assert errors == []

    def test_ada_only_unbalanced(self):
        """Pure ADA transaction — unbalanced."""
        inputs = [Value(coin=10_000_000)]
        outputs = [Value(coin=9_000_000)]
        errors = validate_mary_value_preservation(inputs, outputs, fee=2_000_000)
        assert any("ValueNotConservedUTxO" in e for e in errors)

    def test_multi_asset_balanced(self):
        """Multi-asset transaction — balanced (no minting)."""
        pid = make_policy_id(0)
        an = b"token"
        from pycardano import AssetName

        asset_name = AssetName(an)
        input_val = Value(
            coin=10_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 100})}),
        )
        out1 = Value(
            coin=4_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 60})}),
        )
        out2 = Value(
            coin=4_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 40})}),
        )
        errors = validate_mary_value_preservation([input_val], [out1, out2], fee=2_000_000)
        assert errors == []

    def test_multi_asset_unbalanced_token(self):
        """Multi-asset transaction — token amounts don't match."""
        pid = make_policy_id(0)
        from pycardano import AssetName

        asset_name = AssetName(b"token")
        input_val = Value(
            coin=10_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 100})}),
        )
        # Output only has 80 tokens, missing 20 and no mint/burn
        out = Value(
            coin=8_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 80})}),
        )
        errors = validate_mary_value_preservation([input_val], [out], fee=2_000_000)
        assert any("ValueNotConservedUTxO" in e for e in errors)

    def test_minting_balanced(self):
        """Minting: input ADA + mint = output ADA + tokens + fee."""
        pid = make_policy_id(0)
        from pycardano import AssetName

        asset_name = AssetName(b"coin")
        input_val = Value(coin=10_000_000)
        mint_val = Value(coin=0, multi_asset=MultiAsset({pid: Asset({asset_name: 500})}))
        out = Value(
            coin=8_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 500})}),
        )
        errors = validate_mary_value_preservation([input_val], [out], fee=2_000_000, mint=mint_val)
        assert errors == []

    def test_burning_balanced(self):
        """Burning: input tokens - burn = output tokens."""
        pid = make_policy_id(0)
        from pycardano import AssetName

        asset_name = AssetName(b"burn")
        input_val = Value(
            coin=10_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 100})}),
        )
        # Burn 30 tokens
        mint_val = Value(coin=0, multi_asset=MultiAsset({pid: Asset({asset_name: -30})}))
        out = Value(
            coin=8_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 70})}),
        )
        errors = validate_mary_value_preservation([input_val], [out], fee=2_000_000, mint=mint_val)
        assert errors == []

    def test_multiple_policies_balanced(self):
        """Multiple policy IDs — all balanced."""
        pid1 = make_policy_id(1)
        pid2 = make_policy_id(2)
        from pycardano import AssetName

        an1 = AssetName(b"alpha")
        an2 = AssetName(b"beta")
        input_val = Value(
            coin=10_000_000,
            multi_asset=MultiAsset(
                {
                    pid1: Asset({an1: 50}),
                    pid2: Asset({an2: 200}),
                }
            ),
        )
        out1 = Value(
            coin=4_000_000,
            multi_asset=MultiAsset({pid1: Asset({an1: 30})}),
        )
        out2 = Value(
            coin=4_000_000,
            multi_asset=MultiAsset(
                {
                    pid1: Asset({an1: 20}),
                    pid2: Asset({an2: 200}),
                }
            ),
        )
        errors = validate_mary_value_preservation([input_val], [out1, out2], fee=2_000_000)
        assert errors == []

    def test_empty_inputs_and_outputs(self):
        """Empty inputs and outputs with zero fee is balanced."""
        errors = validate_mary_value_preservation([], [], fee=0)
        assert errors == []


# ---------------------------------------------------------------------------
# Min UTxO value tests (Mary)
# ---------------------------------------------------------------------------


class TestMaryMinUtxoValue:
    """Tests for Mary-era min UTxO value calculation."""

    def test_pure_ada_output(self):
        """Pure ADA output uses flat minUTxOValue."""
        _, vk = make_key_pair()
        addr = make_address(vk)
        txout = TransactionOutput(addr, 2_000_000)
        assert mary_min_utxo_value(txout, TEST_PARAMS) == TEST_PARAMS.min_utxo_value

    def test_multi_asset_output_higher_min(self):
        """Multi-asset output requires more lovelace than flat min."""
        _, vk = make_key_pair()
        addr = make_address(vk)
        pid = make_policy_id(0)
        from pycardano import AssetName

        # Create an output with many distinct assets to push up the min
        assets = {}
        for i in range(10):
            assets[AssetName(f"token_{i:04d}".encode())] = 1
        val = Value(
            coin=2_000_000,
            multi_asset=MultiAsset({pid: Asset(assets)}),
        )
        txout = TransactionOutput(addr, val)
        min_val = mary_min_utxo_value(txout, TEST_PARAMS)
        # Multi-asset output should require at least minUTxOValue
        assert min_val >= TEST_PARAMS.min_utxo_value

    def test_multi_asset_more_policies_higher_min(self):
        """More policy IDs increase the min UTxO value."""
        _, vk = make_key_pair()
        addr = make_address(vk)
        from pycardano import AssetName

        an = AssetName(b"t")

        # One policy
        val1 = Value(
            coin=2_000_000,
            multi_asset=MultiAsset({make_policy_id(0): Asset({an: 1})}),
        )
        txout1 = TransactionOutput(addr, val1)
        min1 = mary_min_utxo_value(txout1, TEST_PARAMS)

        # Three policies
        val3 = Value(
            coin=2_000_000,
            multi_asset=MultiAsset(
                {
                    make_policy_id(0): Asset({an: 1}),
                    make_policy_id(1): Asset({an: 1}),
                    make_policy_id(2): Asset({an: 1}),
                }
            ),
        )
        txout3 = TransactionOutput(addr, val3)
        min3 = mary_min_utxo_value(txout3, TEST_PARAMS)

        assert min3 >= min1

    def test_empty_multi_asset_uses_flat_min(self):
        """Value with empty MultiAsset should use flat minUTxOValue."""
        _, vk = make_key_pair()
        addr = make_address(vk)
        val = Value(coin=2_000_000, multi_asset=MultiAsset())
        txout = TransactionOutput(addr, val)
        assert mary_min_utxo_value(txout, TEST_PARAMS) == TEST_PARAMS.min_utxo_value


# ---------------------------------------------------------------------------
# Allegra UTXO validation tests
# ---------------------------------------------------------------------------


class TestAllegraUtxo:
    """Tests for Allegra-era UTXO validation."""

    def test_valid_with_validity_interval(self):
        """Valid tx with validity interval should pass."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        interval = ValidityInterval(invalid_before=10, invalid_hereafter=100)
        errors = validate_allegra_utxo(
            tx_body,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            validity_interval=interval,
        )
        assert errors == []

    def test_outside_validity_interval(self):
        """Tx outside validity interval should fail."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        interval = ValidityInterval(invalid_before=60, invalid_hereafter=100)
        errors = validate_allegra_utxo(
            tx_body,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            validity_interval=interval,
        )
        assert any("OutsideValidityIntervalUTxO" in e for e in errors)

    def test_fallback_to_ttl(self):
        """Without validity_interval, falls back to TTL checking."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=50,
        )
        errors = validate_allegra_utxo(
            tx_body,
            utxo_set,
            TEST_PARAMS,
            current_slot=100,
            tx_size=200,
        )
        assert any("ExpiredUTxO" in e for e in errors)


# ---------------------------------------------------------------------------
# Mary full transaction validation tests
# ---------------------------------------------------------------------------


class TestMaryTx:
    """Tests for Mary-era full transaction validation."""

    def test_valid_ada_only_tx(self):
        """Pure ADA Mary tx should pass."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        witness_set = TransactionWitnessSet()
        errors = validate_mary_tx(
            tx_body,
            witness_set,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert errors == []

    def test_valid_multi_asset_tx(self):
        """Multi-asset Mary tx with balanced values should pass."""
        pid = make_policy_id(0)
        from pycardano import AssetName

        asset_name = AssetName(b"vibe")
        input_val = Value(
            coin=10_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 100})}),
        )
        utxo_set, txin, sk, vk = make_simple_utxo(value=input_val)
        dest_addr = make_address(vk)
        out_val = Value(
            coin=8_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 100})}),
        )
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, out_val)],
            fee=2_000_000,
        )
        witness_set = TransactionWitnessSet()
        errors = validate_mary_tx(
            tx_body,
            witness_set,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert errors == []

    def test_multi_asset_value_not_conserved(self):
        """Mary tx with unbalanced tokens should fail."""
        pid = make_policy_id(0)
        from pycardano import AssetName

        asset_name = AssetName(b"vibe")
        input_val = Value(
            coin=10_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 100})}),
        )
        utxo_set, txin, sk, vk = make_simple_utxo(value=input_val)
        dest_addr = make_address(vk)
        # Output only has 50 tokens — 50 missing
        out_val = Value(
            coin=8_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 50})}),
        )
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, out_val)],
            fee=2_000_000,
        )
        witness_set = TransactionWitnessSet()
        errors = validate_mary_tx(
            tx_body,
            witness_set,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("ValueNotConservedUTxO" in e for e in errors)

    def test_minting_tx(self):
        """Mary tx with minting should pass when balanced."""
        pid = make_policy_id(0)
        from pycardano import AssetName

        asset_name = AssetName(b"new_token")
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        out_val = Value(
            coin=8_000_000,
            multi_asset=MultiAsset({pid: Asset({asset_name: 1000})}),
        )
        mint_val = Value(coin=0, multi_asset=MultiAsset({pid: Asset({asset_name: 1000})}))
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, out_val)],
            fee=2_000_000,
        )
        witness_set = TransactionWitnessSet()
        errors = validate_mary_tx(
            tx_body,
            witness_set,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            mint=mint_val,
        )
        assert errors == []

    def test_output_below_min_utxo(self):
        """Mary tx with output below min UTxO should fail."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 500_000)],
            fee=9_500_000,
        )
        witness_set = TransactionWitnessSet()
        errors = validate_mary_tx(
            tx_body,
            witness_set,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("OutputTooSmallUTxO" in e for e in errors)

    def test_missing_input(self):
        """Mary tx spending non-existent input should fail."""
        utxo_set, _, sk, vk = make_simple_utxo(value=10_000_000)
        fake_txin = TransactionInput(make_tx_id(999), 0)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[fake_txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        witness_set = TransactionWitnessSet()
        errors = validate_mary_tx(
            tx_body,
            witness_set,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("InputsNotInUTxO" in e for e in errors)

    def test_validity_interval_in_mary(self):
        """Mary tx respects Allegra validity interval."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        interval = ValidityInterval(invalid_before=100, invalid_hereafter=200)
        witness_set = TransactionWitnessSet()
        errors = validate_mary_tx(
            tx_body,
            witness_set,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            validity_interval=interval,
        )
        assert any("OutsideValidityIntervalUTxO" in e for e in errors)


# ---------------------------------------------------------------------------
# Value helper tests
# ---------------------------------------------------------------------------


class TestValueHelpers:
    """Tests for internal value helper functions."""

    def test_output_value_from_int(self):
        """_output_value normalizes int to Value."""
        _, vk = make_key_pair()
        addr = make_address(vk)
        txout = TransactionOutput(addr, 5_000_000)
        val = _output_value(txout)
        assert isinstance(val, Value)
        assert val.coin == 5_000_000

    def test_output_value_from_value(self):
        """_output_value passes through Value."""
        _, vk = make_key_pair()
        addr = make_address(vk)
        v = Value(coin=3_000_000)
        txout = TransactionOutput(addr, v)
        val = _output_value(txout)
        assert val.coin == 3_000_000

    def test_sum_values_empty(self):
        """_sum_values of empty list returns zero Value."""
        result = _sum_values([])
        assert result.coin == 0

    def test_sum_values_multi(self):
        """_sum_values adds coins and multi-assets."""
        pid = make_policy_id(0)
        from pycardano import AssetName

        an = AssetName(b"t")
        v1 = Value(coin=100, multi_asset=MultiAsset({pid: Asset({an: 10})}))
        v2 = Value(coin=200, multi_asset=MultiAsset({pid: Asset({an: 20})}))
        result = _sum_values([v1, v2])
        assert result.coin == 300

    def test_value_eq_identical(self):
        """_value_eq returns True for identical Values."""
        pid = make_policy_id(0)
        from pycardano import AssetName

        an = AssetName(b"x")
        v = Value(coin=100, multi_asset=MultiAsset({pid: Asset({an: 5})}))
        assert _value_eq(v, v)

    def test_value_eq_different_coin(self):
        """_value_eq returns False for different coin."""
        v1 = Value(coin=100)
        v2 = Value(coin=200)
        assert not _value_eq(v1, v2)

    def test_value_eq_different_tokens(self):
        """_value_eq returns False for different token quantities."""
        pid = make_policy_id(0)
        from pycardano import AssetName

        an = AssetName(b"x")
        v1 = Value(coin=100, multi_asset=MultiAsset({pid: Asset({an: 5})}))
        v2 = Value(coin=100, multi_asset=MultiAsset({pid: Asset({an: 10})}))
        assert not _value_eq(v1, v2)


# ---------------------------------------------------------------------------
# AllegraValidationError tests
# ---------------------------------------------------------------------------


class TestAllegraValidationError:
    """Tests for the error type."""

    def test_error_message(self):
        """Error message should contain all failures."""
        err = AllegraValidationError(["err1", "err2"])
        assert "err1" in str(err)
        assert "err2" in str(err)
        assert err.errors == ["err1", "err2"]

    def test_is_exception(self):
        """AllegraValidationError should be an Exception."""
        with pytest.raises(AllegraValidationError):
            raise AllegraValidationError(["test"])


# ---------------------------------------------------------------------------
# MaryProtocolParams tests
# ---------------------------------------------------------------------------


class TestMaryProtocolParams:
    """Tests for Mary protocol parameters."""

    def test_inherits_shelley(self):
        """MaryProtocolParams should inherit Shelley params."""
        p = MARY_MAINNET_PARAMS
        assert p.min_fee_a == 44
        assert p.min_fee_b == 155381
        assert p.min_utxo_value == 1_000_000

    def test_mary_specific_params(self):
        """MaryProtocolParams has utxo_entry_size_without_val."""
        p = MARY_MAINNET_PARAMS
        assert p.utxo_entry_size_without_val == 27

    def test_immutability(self):
        """Mary params should be frozen."""
        p = MaryProtocolParams()
        with pytest.raises(AttributeError):
            p.min_fee_a = 99  # type: ignore


# ---------------------------------------------------------------------------
# Mary minting value preservation property
#
# Spec ref: Mary ledger formal spec, Section 3 — multi-asset value
# preservation with minting.
# Haskell ref: maryUtxoTransition consumed/produced equations.
# ---------------------------------------------------------------------------


class TestMaryMintingPreservation:
    """Property tests for Mary-era minting and value preservation."""

    def test_mary_minting_preserves_total_value(self):
        """Property: with minting, total value in + mint = total value out + fee.

        The fundamental Mary invariant:
            sum(inputs) + mint == sum(outputs) + fee

        This must hold for both the ADA component and all token components.
        """
        from pycardano import AssetName

        pid = make_policy_id(0)
        an = AssetName(b"vibetoken")

        # Input: 10 ADA, 50 tokens
        input_val = Value(
            coin=10_000_000,
            multi_asset=MultiAsset({pid: Asset({an: 50})}),
        )

        # Mint: 100 new tokens
        mint_val = Value(
            coin=0,
            multi_asset=MultiAsset({pid: Asset({an: 100})}),
        )

        # Output: 8 ADA, 150 tokens (50 from input + 100 minted)
        output_val = Value(
            coin=8_000_000,
            multi_asset=MultiAsset({pid: Asset({an: 150})}),
        )

        fee = 2_000_000

        # This should pass: input(10M, 50t) + mint(0, 100t) = output(8M, 150t) + fee(2M)
        errors = validate_mary_value_preservation(
            [input_val],
            [output_val],
            fee=fee,
            mint=mint_val,
        )
        assert errors == [], f"Expected no errors, got: {errors}"

        # Verify the invariant manually:
        consumed = _sum_values([input_val])
        consumed = consumed + mint_val
        produced = _sum_values([output_val]) + Value(coin=fee)
        assert _value_eq(consumed, produced)

    def test_mary_minting_unbalanced_detected(self):
        """Minting that doesn't balance should fail validation."""
        from pycardano import AssetName

        pid = make_policy_id(0)
        an = AssetName(b"vibetoken")

        input_val = Value(coin=10_000_000)
        mint_val = Value(
            coin=0,
            multi_asset=MultiAsset({pid: Asset({an: 100})}),
        )
        # Output claims 200 tokens but only 100 were minted
        output_val = Value(
            coin=8_000_000,
            multi_asset=MultiAsset({pid: Asset({an: 200})}),
        )

        errors = validate_mary_value_preservation(
            [input_val],
            [output_val],
            fee=2_000_000,
            mint=mint_val,
        )
        assert any("ValueNotConservedUTxO" in e for e in errors)


# ---------------------------------------------------------------------------
# Timelock determinism test
#
# Spec ref: Allegra ledger formal spec, evalTimelock.
# Haskell ref: validateTimelock in Cardano.Ledger.Allegra.Scripts
# ---------------------------------------------------------------------------


class TestTimelockDeterminism:
    """Determinism tests for timelock script evaluation."""

    def test_timelock_script_evaluation_deterministic(self):
        """Same timelock script, same slot -> same result always.

        Timelock evaluation is a pure function of (script, signers, slot).
        Evaluating it multiple times must always produce the same result.
        This is critical for consensus — all nodes must agree on script
        validity.
        """
        kh = make_key_hash(42)
        script = Timelock(
            type=TimelockType.REQUIRE_ALL_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh),
                Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=100),
                Timelock(
                    type=TimelockType.REQUIRE_M_OF_N,
                    required=1,
                    scripts=(
                        Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=make_key_hash(0)),
                        Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=kh),
                    ),
                ),
            ),
        )

        signers = frozenset({kh})

        # Evaluate 100 times at the same slot — must all be identical
        results_at_100 = [evaluate_timelock(script, signers, current_slot=100) for _ in range(100)]
        assert all(
            r == results_at_100[0] for r in results_at_100
        ), "Timelock evaluation is not deterministic"
        assert results_at_100[0] is True

        # And at a failing slot
        results_at_99 = [evaluate_timelock(script, signers, current_slot=99) for _ in range(100)]
        assert all(r == results_at_99[0] for r in results_at_99)
        assert results_at_99[0] is False

    def test_timelock_empty_nested_deterministic(self):
        """Nested empty scripts evaluate deterministically."""
        # AllOf(AnyOf()) — AllOf is vacuously true, but contains AnyOf
        # which is vacuously false.  The overall result depends on whether
        # AllOf short-circuits.
        script = Timelock(
            type=TimelockType.REQUIRE_ALL_OF,
            scripts=(Timelock(type=TimelockType.REQUIRE_ANY_OF, scripts=()),),
        )
        results = [evaluate_timelock(script, frozenset(), current_slot=0) for _ in range(50)]
        assert all(r == results[0] for r in results)
        # AnyOf() is false, so AllOf(AnyOf()) is false
        assert results[0] is False


# ---------------------------------------------------------------------------
# Validity interval subsumes TTL
#
# Spec ref: Allegra ledger formal spec — ValidityInterval replaced TTL.
# A Shelley TTL is equivalent to ValidityInterval(None, ttl).
# ---------------------------------------------------------------------------


class TestValidityIntervalSubsumesTTL:
    """Test that ValidityInterval(None, ttl) behaves identically to Shelley TTL."""

    def test_validity_interval_subsumes_ttl(self):
        """A TTL is equivalent to a ValidityInterval with only invalid_hereafter set.

        Shelley: tx is valid iff current_slot < ttl
        Allegra: tx is valid iff current_slot < invalid_hereafter

        These must produce identical results for all slot/ttl combinations.
        """
        test_cases = [
            # (ttl/hereafter, current_slot, expected_valid)
            (100, 0, True),
            (100, 50, True),
            (100, 99, True),
            (100, 100, False),  # at boundary: expired
            (100, 101, False),
            (100, 200, False),
            (1, 0, True),
            (1, 1, False),
            (0, 0, False),
        ]

        for ttl, current_slot, expected_valid in test_cases:
            # Allegra: ValidityInterval with only invalid_hereafter
            interval = ValidityInterval(invalid_before=None, invalid_hereafter=ttl)
            errors = validate_validity_interval(interval, current_slot)
            allegra_valid = len(errors) == 0

            assert allegra_valid == expected_valid, (
                f"TTL={ttl}, slot={current_slot}: "
                f"expected valid={expected_valid}, got valid={allegra_valid}"
            )

    def test_validity_interval_with_both_bounds_strictly_more_expressive(self):
        """ValidityInterval with both bounds is strictly more expressive than TTL.

        TTL can only express "valid before slot X". ValidityInterval can
        also express "valid after slot Y", which TTL cannot.
        """
        # This interval is not expressible as a TTL
        interval = ValidityInterval(invalid_before=50, invalid_hereafter=100)

        # Slot 49: fails lower bound (TTL would pass this!)
        errors_49 = validate_validity_interval(interval, current_slot=49)
        assert any("invalid_before" in e for e in errors_49)

        # Slot 50: passes both bounds
        errors_50 = validate_validity_interval(interval, current_slot=50)
        assert errors_50 == []

        # Slot 99: passes both bounds
        errors_99 = validate_validity_interval(interval, current_slot=99)
        assert errors_99 == []

        # Slot 100: fails upper bound (same as TTL behavior)
        errors_100 = validate_validity_interval(interval, current_slot=100)
        assert any("invalid_hereafter" in e for e in errors_100)
