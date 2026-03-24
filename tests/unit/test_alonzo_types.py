"""Tests for Alonzo-era types: ExUnits, Redeemer, CostModel, ScriptPurpose.

Tests cover:
    - ExUnits arithmetic (addition, comparison, exceeds)
    - ExUnits validation (non-negative constraints)
    - Redeemer construction and validation
    - RedeemerTag enum values
    - ScriptPurpose variants
    - ExUnitPrices fee calculation
    - AlonzoProtocolParams defaults
    - Script integrity hash computation
    - Hypothesis property tests for ExUnits associativity and monotonicity

Spec references:
    - Alonzo ledger formal spec, Section 4 (Transactions)
    - Alonzo ledger formal spec, Section 5 (Scripts and Validation)
    - ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Scripts.hs``
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.ledger.alonzo_types import (
    ALONZO_MAINNET_PARAMS,
    AlonzoProtocolParams,
    CertifyingPurpose,
    ExUnitPrices,
    ExUnits,
    Language,
    MintingPurpose,
    Redeemer,
    RedeemerTag,
    RewardingPurpose,
    SpendingPurpose,
    compute_script_integrity_hash,
)

# ---------------------------------------------------------------------------
# ExUnits tests
# ---------------------------------------------------------------------------


class TestExUnits:
    """Tests for ExUnits execution budget type."""

    def test_default_is_zero(self):
        """Default ExUnits should be (0, 0)."""
        eu = ExUnits()
        assert eu.mem == 0
        assert eu.steps == 0

    def test_construction(self):
        """ExUnits with explicit values."""
        eu = ExUnits(mem=1000, steps=2000)
        assert eu.mem == 1000
        assert eu.steps == 2000

    def test_negative_mem_rejected(self):
        """Negative memory should raise ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            ExUnits(mem=-1, steps=0)

    def test_negative_steps_rejected(self):
        """Negative steps should raise ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            ExUnits(mem=0, steps=-1)

    def test_addition(self):
        """Component-wise addition."""
        a = ExUnits(mem=100, steps=200)
        b = ExUnits(mem=300, steps=400)
        result = a + b
        assert result.mem == 400
        assert result.steps == 600

    def test_addition_identity(self):
        """Adding zero ExUnits is identity."""
        a = ExUnits(mem=100, steps=200)
        zero = ExUnits()
        assert a + zero == a
        assert zero + a == a

    def test_le_both_less(self):
        """Both components less should be <=."""
        a = ExUnits(mem=100, steps=200)
        b = ExUnits(mem=200, steps=300)
        assert a <= b

    def test_le_equal(self):
        """Equal ExUnits should be <=."""
        a = ExUnits(mem=100, steps=200)
        assert a <= a

    def test_le_one_greater(self):
        """One component greater should not be <=."""
        a = ExUnits(mem=100, steps=300)
        b = ExUnits(mem=200, steps=200)
        assert not (a <= b)

    def test_lt_strict(self):
        """Strictly less in at least one dimension."""
        a = ExUnits(mem=100, steps=200)
        b = ExUnits(mem=200, steps=300)
        assert a < b

    def test_lt_equal_not_strict(self):
        """Equal ExUnits should not be strictly less."""
        a = ExUnits(mem=100, steps=200)
        assert not (a < a)

    def test_exceeds_neither(self):
        """Neither dimension exceeds limit."""
        eu = ExUnits(mem=100, steps=200)
        limit = ExUnits(mem=200, steps=300)
        assert not eu.exceeds(limit)

    def test_exceeds_mem(self):
        """Memory exceeds limit."""
        eu = ExUnits(mem=300, steps=200)
        limit = ExUnits(mem=200, steps=300)
        assert eu.exceeds(limit)

    def test_exceeds_steps(self):
        """Steps exceeds limit."""
        eu = ExUnits(mem=100, steps=400)
        limit = ExUnits(mem=200, steps=300)
        assert eu.exceeds(limit)

    def test_exceeds_both(self):
        """Both dimensions exceed limit."""
        eu = ExUnits(mem=300, steps=400)
        limit = ExUnits(mem=200, steps=300)
        assert eu.exceeds(limit)

    def test_exceeds_at_limit(self):
        """Exactly at limit should not exceed."""
        eu = ExUnits(mem=200, steps=300)
        limit = ExUnits(mem=200, steps=300)
        assert not eu.exceeds(limit)

    def test_frozen(self):
        """ExUnits should be immutable."""
        eu = ExUnits(mem=100, steps=200)
        with pytest.raises(AttributeError):
            eu.mem = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Hypothesis property tests for ExUnits
# ---------------------------------------------------------------------------


# Strategy for reasonable ExUnits values
ex_units_st = st.builds(
    ExUnits,
    mem=st.integers(min_value=0, max_value=10**12),
    steps=st.integers(min_value=0, max_value=10**12),
)


class TestExUnitsProperties:
    """Hypothesis property tests for ExUnits arithmetic."""

    @given(a=ex_units_st, b=ex_units_st, c=ex_units_st)
    @settings(max_examples=100)
    def test_addition_associative(self, a: ExUnits, b: ExUnits, c: ExUnits):
        """ExUnits addition should be associative: (a + b) + c == a + (b + c)."""
        assert (a + b) + c == a + (b + c)

    @given(a=ex_units_st, b=ex_units_st)
    @settings(max_examples=100)
    def test_addition_commutative(self, a: ExUnits, b: ExUnits):
        """ExUnits addition should be commutative: a + b == b + a."""
        assert a + b == b + a

    @given(a=ex_units_st)
    @settings(max_examples=50)
    def test_addition_identity(self, a: ExUnits):
        """Adding zero is identity."""
        assert a + ExUnits() == a

    @given(a=ex_units_st, b=ex_units_st)
    @settings(max_examples=100)
    def test_le_reflexive(self, a: ExUnits, b: ExUnits):
        """A <= a should always hold."""
        assert a <= a

    @given(a=ex_units_st)
    @settings(max_examples=50)
    def test_exceeds_complement_of_le(self, a: ExUnits):
        """exceeds(limit) should be the negation of <= limit."""
        limit = ExUnits(mem=500, steps=500)
        assert a.exceeds(limit) == (not (a <= limit))


# ---------------------------------------------------------------------------
# RedeemerTag tests
# ---------------------------------------------------------------------------


class TestRedeemerTag:
    """Tests for RedeemerTag enum."""

    def test_spend_value(self):
        assert RedeemerTag.SPEND == 0

    def test_mint_value(self):
        assert RedeemerTag.MINT == 1

    def test_cert_value(self):
        assert RedeemerTag.CERT == 2

    def test_reward_value(self):
        assert RedeemerTag.REWARD == 3

    def test_all_variants(self):
        """All four variants should exist."""
        assert len(RedeemerTag) == 4


# ---------------------------------------------------------------------------
# Redeemer tests
# ---------------------------------------------------------------------------


class TestRedeemer:
    """Tests for Redeemer type."""

    def test_construction(self):
        """Basic redeemer construction."""
        r = Redeemer(
            tag=RedeemerTag.SPEND,
            index=0,
            data=b"\xa0",  # CBOR empty map
            ex_units=ExUnits(mem=1000, steps=2000),
        )
        assert r.tag == RedeemerTag.SPEND
        assert r.index == 0
        assert r.ex_units.mem == 1000

    def test_negative_index_rejected(self):
        """Negative index should raise ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            Redeemer(
                tag=RedeemerTag.MINT,
                index=-1,
                data=b"\xa0",
                ex_units=ExUnits(),
            )

    def test_frozen(self):
        """Redeemer should be immutable."""
        r = Redeemer(tag=RedeemerTag.SPEND, index=0, data=b"\xa0", ex_units=ExUnits())
        with pytest.raises(AttributeError):
            r.index = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ScriptPurpose tests
# ---------------------------------------------------------------------------


class TestScriptPurpose:
    """Tests for ScriptPurpose variant types."""

    def test_spending_purpose(self):
        sp = SpendingPurpose(tx_in_id=b"\x00" * 32, tx_in_index=0)
        assert sp.tx_in_id == b"\x00" * 32
        assert sp.tx_in_index == 0

    def test_minting_purpose(self):
        mp = MintingPurpose(policy_id=b"\x01" * 28)
        assert mp.policy_id == b"\x01" * 28

    def test_rewarding_purpose(self):
        rp = RewardingPurpose(stake_credential=b"\x02" * 28)
        assert rp.stake_credential == b"\x02" * 28

    def test_certifying_purpose(self):
        cp = CertifyingPurpose(cert_index=3)
        assert cp.cert_index == 3


# ---------------------------------------------------------------------------
# ExUnitPrices tests
# ---------------------------------------------------------------------------


class TestExUnitPrices:
    """Tests for execution unit price calculations."""

    def test_default_prices(self):
        """Default prices match Alonzo mainnet values."""
        prices = ExUnitPrices()
        assert prices.mem_price_numerator == 577
        assert prices.mem_price_denominator == 10000
        assert prices.step_price_numerator == 721
        assert prices.step_price_denominator == 10000000

    def test_fee_for_zero(self):
        """Zero execution units should produce zero fee."""
        prices = ExUnitPrices()
        assert prices.fee_for(ExUnits()) == 0

    def test_fee_for_simple(self):
        """Fee calculation with simple values."""
        # Use round numbers for easy verification
        prices = ExUnitPrices(
            mem_price_numerator=1,
            mem_price_denominator=1,
            step_price_numerator=1,
            step_price_denominator=1,
        )
        eu = ExUnits(mem=100, steps=200)
        assert prices.fee_for(eu) == 300

    def test_fee_for_ceiling(self):
        """Fee calculation should use ceiling arithmetic."""
        # mem = 1 unit at price 1/3 => ceil(1/3) = 1
        prices = ExUnitPrices(
            mem_price_numerator=1,
            mem_price_denominator=3,
            step_price_numerator=0,
            step_price_denominator=1,
        )
        eu = ExUnits(mem=1, steps=0)
        assert prices.fee_for(eu) == 1  # ceil(1/3) = 1

    def test_fee_for_realistic(self):
        """Fee with Alonzo mainnet prices."""
        prices = ExUnitPrices()
        eu = ExUnits(mem=1_000_000, steps=1_000_000_000)
        # mem_fee = ceil(1M * 577 / 10000) = ceil(57700) = 57700
        # step_fee = ceil(1B * 721 / 10M) = ceil(72100) = 72100
        fee = prices.fee_for(eu)
        assert fee == 57700 + 72100


# ---------------------------------------------------------------------------
# Hypothesis: collateral is monotonic in fees
# ---------------------------------------------------------------------------


class TestCollateralMonotonicity:
    """Property test: collateral requirement is monotonic in script fees."""

    @given(
        fee_a=st.integers(min_value=0, max_value=10**9),
        fee_b=st.integers(min_value=0, max_value=10**9),
        percentage=st.integers(min_value=100, max_value=500),
    )
    @settings(max_examples=100)
    def test_higher_fees_need_more_collateral(self, fee_a: int, fee_b: int, percentage: int):
        """If fee_a <= fee_b, then required collateral for a <= required for b."""
        required_a = (fee_a * percentage + 99) // 100
        required_b = (fee_b * percentage + 99) // 100
        if fee_a <= fee_b:
            assert required_a <= required_b


# ---------------------------------------------------------------------------
# Language tests
# ---------------------------------------------------------------------------


class TestLanguage:
    """Tests for Language enum."""

    def test_plutus_v1(self):
        assert Language.PLUTUS_V1 == 0

    def test_plutus_v2(self):
        assert Language.PLUTUS_V2 == 1

    def test_plutus_v3(self):
        assert Language.PLUTUS_V3 == 2


# ---------------------------------------------------------------------------
# AlonzoProtocolParams tests
# ---------------------------------------------------------------------------


class TestAlonzoProtocolParams:
    """Tests for Alonzo protocol parameter defaults."""

    def test_inherits_mary(self):
        """Alonzo params should inherit Mary/Shelley defaults."""
        p = AlonzoProtocolParams()
        assert p.min_fee_a == 44
        assert p.min_fee_b == 155381
        assert p.min_utxo_value == 1000000

    def test_alonzo_defaults(self):
        """Alonzo-specific defaults should be set."""
        p = AlonzoProtocolParams()
        assert p.collateral_percentage == 150
        assert p.max_collateral_inputs == 3
        assert p.max_val_size == 5000
        assert p.coins_per_utxo_word == 4310

    def test_mainnet_params(self):
        """ALONZO_MAINNET_PARAMS should be an AlonzoProtocolParams."""
        assert isinstance(ALONZO_MAINNET_PARAMS, AlonzoProtocolParams)

    def test_ex_units_limits(self):
        """Default ExUnits limits should be positive."""
        p = AlonzoProtocolParams()
        assert p.max_tx_ex_units.mem > 0
        assert p.max_tx_ex_units.steps > 0
        assert p.max_block_ex_units.mem > 0
        assert p.max_block_ex_units.steps > 0

    def test_block_limits_greater_than_tx_limits(self):
        """Block ExUnits limits should be >= tx limits."""
        p = AlonzoProtocolParams()
        assert p.max_block_ex_units.mem >= p.max_tx_ex_units.mem
        assert p.max_block_ex_units.steps >= p.max_tx_ex_units.steps


# ---------------------------------------------------------------------------
# Script integrity hash tests
# ---------------------------------------------------------------------------


class TestScriptIntegrityHash:
    """Tests for script integrity hash computation."""

    def test_deterministic(self):
        """Same inputs should produce the same hash."""
        import cbor2

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(42),
                ex_units=ExUnits(mem=100, steps=200),
            )
        ]
        datums = [cbor2.dumps(99)]
        cost_models: dict[Language, dict[str, int]] = {
            Language.PLUTUS_V1: {"addInteger-cpu": 100, "addInteger-mem": 50}
        }
        languages = {Language.PLUTUS_V1}

        h1 = compute_script_integrity_hash(redeemers, datums, cost_models, languages)
        h2 = compute_script_integrity_hash(redeemers, datums, cost_models, languages)
        assert h1 == h2

    def test_hash_is_32_bytes(self):
        """Output should be a 32-byte Blake2b-256 hash."""
        import cbor2

        h = compute_script_integrity_hash(
            redeemers=[
                Redeemer(
                    tag=RedeemerTag.MINT,
                    index=0,
                    data=cbor2.dumps(0),
                    ex_units=ExUnits(mem=1, steps=1),
                )
            ],
            datums=[cbor2.dumps(0)],
            cost_models={Language.PLUTUS_V1: {"a": 1}},
            languages_used={Language.PLUTUS_V1},
        )
        assert isinstance(h, bytes)
        assert len(h) == 32

    def test_different_redeemers_different_hash(self):
        """Different redeemer data should produce different hashes."""
        import cbor2

        base_args = dict(
            datums=[cbor2.dumps(0)],
            cost_models={Language.PLUTUS_V1: {"a": 1}},
            languages_used={Language.PLUTUS_V1},
        )
        h1 = compute_script_integrity_hash(
            redeemers=[
                Redeemer(
                    tag=RedeemerTag.SPEND,
                    index=0,
                    data=cbor2.dumps(1),
                    ex_units=ExUnits(mem=100, steps=200),
                )
            ],
            **base_args,
        )
        h2 = compute_script_integrity_hash(
            redeemers=[
                Redeemer(
                    tag=RedeemerTag.SPEND,
                    index=0,
                    data=cbor2.dumps(2),
                    ex_units=ExUnits(mem=100, steps=200),
                )
            ],
            **base_args,
        )
        assert h1 != h2

    def test_empty_redeemers_and_datums(self):
        """Empty redeemers and datums should still produce a valid hash."""
        h = compute_script_integrity_hash(
            redeemers=[],
            datums=[],
            cost_models={},
            languages_used=set(),
        )
        assert isinstance(h, bytes)
        assert len(h) == 32
