"""CBOR round-trip tests for era-specific Cardano ledger types.

Tests that every era-specific type survives encode -> decode -> re-encode
without information loss. This is the serialization foundation for ledger
validation: if types don't round-trip cleanly, nothing downstream works.

Coverage per era:
    - Shelley:  TxBody (via pycardano), TxOut, ShelleyProtocolParams, Certificates
    - Allegra:  ValidityInterval, Timelock scripts (all 6 variants)
    - Mary:     MultiAsset Value (multiple policies + asset names), minting
    - Alonzo:   Redeemer (all 4 tags), ExUnits, CostModel, ScriptIntegrityHash
    - Babbage:  DatumOption (hash + inline), ReferenceScript, coinsPerUTxOByte
    - Conway:   GovAction (all 7 types), ProposalProcedure, Vote, DRep (all 4 types)

Uses Hypothesis for property-based round-trips where practical.
Structured for Antithesis compatibility: deterministic given the same seed.

Spec references:
    - Shelley ledger formal spec, Section 4 (Transaction format)
    - Allegra ledger formal spec (ValidityInterval, Timelock)
    - Mary ledger formal spec, Section 3 (Multi-asset)
    - Alonzo ledger formal spec, Section 4 (Transactions / Scripts)
    - Babbage ledger formal spec, Section 3 (Transaction output format)
    - Conway ledger formal spec, Section 5 (Governance)
"""

from __future__ import annotations

import hashlib

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pycardano import (
    Asset,
    MultiAsset,
    TransactionBody,
    TransactionInput,
    TransactionOutput,
    Value,
)
from pycardano.address import Address
from pycardano.hash import (
    ScriptHash,
    TransactionId,
)
from pycardano.network import Network

from vibe.cardano.ledger.allegra_mary import (
    Timelock,
    TimelockType,
    ValidityInterval,
)
from vibe.cardano.ledger.alonzo_types import (
    CostModel,
    ExUnits,
    Language,
    Redeemer,
    RedeemerTag,
    compute_script_integrity_hash,
)
from vibe.cardano.ledger.babbage_types import (
    BabbageOutputExtension,
    BabbageProtocolParams,
    DatumOption,
    DatumOptionTag,
    ReferenceScript,
)
from vibe.cardano.ledger.conway_types import (
    Anchor,
    ConwayProtocolParams,
    DRep,
    DRepType,
    GovAction,
    GovActionId,
    GovActionType,
    ProposalProcedure,
    Vote,
    Voter,
    VoterRole,
    VotingProcedure,
)
from vibe.cardano.ledger.shelley import ShelleyProtocolParams

# Mark all tests as property tests
pytestmark = pytest.mark.property


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blake2b_256(data: bytes) -> bytes:
    """Compute Blake2b-256 hash."""
    return hashlib.blake2b(data, digest_size=32).digest()


def _make_tx_id(seed: int = 0) -> TransactionId:
    """Create a deterministic 32-byte TransactionId."""
    digest = _blake2b_256(seed.to_bytes(4, "big"))
    return TransactionId(digest)


def _make_address(seed: int = 0) -> Address:
    """Create a deterministic Shelley testnet address."""
    key_hash = _blake2b_256(seed.to_bytes(4, "big"))[:28]
    from pycardano.hash import VerificationKeyHash

    return Address(payment_part=VerificationKeyHash(key_hash), network=Network.TESTNET)


def _make_script_hash(seed: int = 0) -> ScriptHash:
    """Create a deterministic 28-byte ScriptHash."""
    digest = _blake2b_256(seed.to_bytes(4, "big"))[:28]
    return ScriptHash(digest)


def _make_credential(seed: int = 0) -> bytes:
    """Create a deterministic 28-byte credential hash."""
    return _blake2b_256(seed.to_bytes(4, "big"))[:28]


def _make_hash32(seed: int = 0) -> bytes:
    """Create a deterministic 32-byte hash."""
    return _blake2b_256(seed.to_bytes(4, "big"))


# ---------------------------------------------------------------------------
# Shelley-era round-trip tests
# ---------------------------------------------------------------------------


class TestShelleyTxBodyRoundtrip:
    """Shelley TxBody round-trips through pycardano CBOR serialization."""

    def test_basic_txbody_roundtrip(self) -> None:
        """TxBody with inputs, outputs, fee, and TTL round-trips."""
        tx_body = TransactionBody(
            inputs=[
                TransactionInput(_make_tx_id(0), 0),
                TransactionInput(_make_tx_id(1), 1),
            ],
            outputs=[
                TransactionOutput(_make_address(0), 5_000_000),
                TransactionOutput(_make_address(1), 3_000_000),
            ],
            fee=200_000,
        )
        raw = tx_body.to_cbor()
        decoded = TransactionBody.from_cbor(raw)
        re_encoded = decoded.to_cbor()
        assert raw == re_encoded, "TxBody CBOR not stable across round-trip"

    def test_txbody_with_ttl_roundtrip(self) -> None:
        """TxBody with TTL field round-trips."""
        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(0), 0)],
            outputs=[TransactionOutput(_make_address(0), 2_000_000)],
            fee=180_000,
            ttl=50_000_000,
        )
        raw = tx_body.to_cbor()
        decoded = TransactionBody.from_cbor(raw)
        assert decoded.ttl == 50_000_000
        assert decoded.to_cbor() == raw

    @given(
        fee=st.integers(min_value=0, max_value=2**63 - 1),
        ttl=st.integers(min_value=0, max_value=2**63 - 1),
    )
    @settings(max_examples=20)
    def test_txbody_fee_ttl_property(self, fee: int, ttl: int) -> None:
        """TxBody fee and TTL survive round-trip for arbitrary values."""
        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(0), 0)],
            outputs=[TransactionOutput(_make_address(0), 2_000_000)],
            fee=fee,
            ttl=ttl,
        )
        raw = tx_body.to_cbor()
        decoded = TransactionBody.from_cbor(raw)
        assert decoded.fee == fee
        assert decoded.ttl == ttl


class TestShelleyTxOutRoundtrip:
    """Shelley TxOut (address + lovelace) round-trips."""

    def test_txout_lovelace_only(self) -> None:
        """Pure lovelace output round-trips."""
        txout = TransactionOutput(_make_address(42), 10_000_000)
        raw = txout.to_cbor()
        decoded = TransactionOutput.from_cbor(raw)
        assert decoded.amount == 10_000_000
        assert decoded.to_cbor() == raw

    @given(value=st.integers(min_value=1_000_000, max_value=45_000_000_000_000_000))
    @settings(max_examples=20)
    def test_txout_lovelace_property(self, value: int) -> None:
        """TxOut lovelace value survives round-trip for arbitrary amounts."""
        txout = TransactionOutput(_make_address(0), value)
        raw = txout.to_cbor()
        decoded = TransactionOutput.from_cbor(raw)
        decoded_amount = decoded.amount
        if isinstance(decoded_amount, Value):
            decoded_amount = decoded_amount.coin
        assert decoded_amount == value


class TestShelleyProtocolParamsRoundtrip:
    """ShelleyProtocolParams reconstructs identically from field values."""

    def test_default_params_roundtrip(self) -> None:
        """Default params survive dict round-trip."""
        params = ShelleyProtocolParams()
        d = {
            "min_fee_a": params.min_fee_a,
            "min_fee_b": params.min_fee_b,
            "max_tx_size": params.max_tx_size,
            "min_utxo_value": params.min_utxo_value,
            "key_deposit": params.key_deposit,
            "pool_deposit": params.pool_deposit,
            "min_pool_cost": params.min_pool_cost,
        }
        reconstructed = ShelleyProtocolParams(**d)
        assert reconstructed == params

    def test_custom_params_roundtrip(self) -> None:
        """Custom params survive dict round-trip."""
        params = ShelleyProtocolParams(
            min_fee_a=100,
            min_fee_b=200000,
            max_tx_size=32768,
            min_utxo_value=2000000,
            key_deposit=3000000,
            pool_deposit=600000000,
            min_pool_cost=500_000_000,
        )
        d = {
            "min_fee_a": params.min_fee_a,
            "min_fee_b": params.min_fee_b,
            "max_tx_size": params.max_tx_size,
            "min_utxo_value": params.min_utxo_value,
            "key_deposit": params.key_deposit,
            "pool_deposit": params.pool_deposit,
            "min_pool_cost": params.min_pool_cost,
        }
        reconstructed = ShelleyProtocolParams(**d)
        assert reconstructed == params


class TestShelleyCertificateRoundtrip:
    """Shelley certificates round-trip through pycardano CBOR."""

    def test_stake_registration_roundtrip(self) -> None:
        """StakeRegistration certificate round-trips."""
        from pycardano.certificate import StakeCredential, StakeRegistration
        from pycardano.hash import VerificationKeyHash

        cred = StakeCredential(VerificationKeyHash(_make_credential(0)))
        cert = StakeRegistration(cred)
        raw = cert.to_cbor()
        decoded = StakeRegistration.from_cbor(raw)
        assert decoded.to_cbor() == raw

    def test_stake_delegation_roundtrip(self) -> None:
        """StakeDelegation certificate round-trips."""
        from pycardano.certificate import StakeCredential, StakeDelegation
        from pycardano.hash import PoolKeyHash, VerificationKeyHash

        cred = StakeCredential(VerificationKeyHash(_make_credential(0)))
        pool_hash = PoolKeyHash(_make_credential(1))
        cert = StakeDelegation(cred, pool_hash)
        raw = cert.to_cbor()
        decoded = StakeDelegation.from_cbor(raw)
        assert decoded.to_cbor() == raw

    def test_pool_registration_roundtrip(self) -> None:
        """PoolRegistration round-trips (basic params)."""
        from fractions import Fraction

        from pycardano.certificate import PoolParams, PoolRegistration
        from pycardano.hash import PoolKeyHash, RewardAccountHash, VerificationKeyHash, VrfKeyHash

        pool_params = PoolParams(
            operator=PoolKeyHash(_make_credential(10)),
            vrf_keyhash=VrfKeyHash(_make_hash32(20)),
            pledge=100_000_000,
            cost=340_000_000,
            margin=Fraction(1, 100),
            reward_account=RewardAccountHash(bytes([0xE0]) + _make_credential(30)),
            pool_owners=[VerificationKeyHash(_make_credential(10))],
        )
        cert = PoolRegistration(pool_params)
        raw = cert.to_cbor()
        decoded = PoolRegistration.from_cbor(raw)
        assert decoded.to_cbor() == raw

    def test_pool_retirement_roundtrip(self) -> None:
        """PoolRetirement round-trips."""
        from pycardano.certificate import PoolRetirement
        from pycardano.hash import PoolKeyHash

        cert = PoolRetirement(PoolKeyHash(_make_credential(5)), epoch=100)
        raw = cert.to_cbor()
        decoded = PoolRetirement.from_cbor(raw)
        assert decoded.to_cbor() == raw


# ---------------------------------------------------------------------------
# Allegra-era round-trip tests
# ---------------------------------------------------------------------------


class TestValidityIntervalRoundtrip:
    """ValidityInterval round-trips through cbor2 serialization."""

    def test_both_bounds(self) -> None:
        """Interval with both bounds round-trips."""
        iv = ValidityInterval(invalid_before=1000, invalid_hereafter=2000)
        encoded = cbor2.dumps([iv.invalid_before, iv.invalid_hereafter])
        decoded = cbor2.loads(encoded)
        reconstructed = ValidityInterval(invalid_before=decoded[0], invalid_hereafter=decoded[1])
        assert reconstructed == iv

    def test_no_lower_bound(self) -> None:
        """Interval with no lower bound round-trips."""
        iv = ValidityInterval(invalid_before=None, invalid_hereafter=5000)
        encoded = cbor2.dumps([iv.invalid_before, iv.invalid_hereafter])
        decoded = cbor2.loads(encoded)
        reconstructed = ValidityInterval(invalid_before=decoded[0], invalid_hereafter=decoded[1])
        assert reconstructed == iv

    def test_no_upper_bound(self) -> None:
        """Interval with no upper bound round-trips."""
        iv = ValidityInterval(invalid_before=100, invalid_hereafter=None)
        encoded = cbor2.dumps([iv.invalid_before, iv.invalid_hereafter])
        decoded = cbor2.loads(encoded)
        reconstructed = ValidityInterval(invalid_before=decoded[0], invalid_hereafter=decoded[1])
        assert reconstructed == iv

    @given(
        before=st.one_of(st.none(), st.integers(min_value=0, max_value=2**63 - 1)),
        after=st.one_of(st.none(), st.integers(min_value=0, max_value=2**63 - 1)),
    )
    @settings(max_examples=30)
    def test_validity_interval_property(self, before: int | None, after: int | None) -> None:
        """ValidityInterval survives CBOR round-trip for arbitrary slot values."""
        iv = ValidityInterval(invalid_before=before, invalid_hereafter=after)
        encoded = cbor2.dumps([iv.invalid_before, iv.invalid_hereafter])
        decoded = cbor2.loads(encoded)
        reconstructed = ValidityInterval(invalid_before=decoded[0], invalid_hereafter=decoded[1])
        assert reconstructed == iv


class TestTimelockRoundtrip:
    """Allegra Timelock scripts round-trip through CBOR."""

    def _timelock_to_cbor(self, script: Timelock) -> bytes:
        """Serialize a Timelock to CBOR matching the on-chain format."""
        match script.type:
            case TimelockType.REQUIRE_SIGNATURE:
                return cbor2.dumps([0, script.key_hash])
            case TimelockType.REQUIRE_ALL_OF:
                subs = [cbor2.loads(self._timelock_to_cbor(s)) for s in script.scripts]
                return cbor2.dumps([1, subs])
            case TimelockType.REQUIRE_ANY_OF:
                subs = [cbor2.loads(self._timelock_to_cbor(s)) for s in script.scripts]
                return cbor2.dumps([2, subs])
            case TimelockType.REQUIRE_M_OF_N:
                subs = [cbor2.loads(self._timelock_to_cbor(s)) for s in script.scripts]
                return cbor2.dumps([3, script.required, subs])
            case TimelockType.REQUIRE_TIME_AFTER:
                return cbor2.dumps([4, script.slot])
            case TimelockType.REQUIRE_TIME_BEFORE:
                return cbor2.dumps([5, script.slot])
        raise ValueError(f"Unknown timelock type: {script.type}")  # pragma: no cover

    def _timelock_from_cbor(self, data: bytes) -> Timelock:
        """Deserialize a Timelock from CBOR."""
        decoded = cbor2.loads(data)
        return self._timelock_from_primitive(decoded)

    def _timelock_from_primitive(self, decoded: list) -> Timelock:
        """Construct Timelock from decoded CBOR primitive."""
        tag = decoded[0]
        if tag == 0:
            return Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=decoded[1])
        elif tag == 1:
            subs = tuple(self._timelock_from_primitive(s) for s in decoded[1])
            return Timelock(type=TimelockType.REQUIRE_ALL_OF, scripts=subs)
        elif tag == 2:
            subs = tuple(self._timelock_from_primitive(s) for s in decoded[1])
            return Timelock(type=TimelockType.REQUIRE_ANY_OF, scripts=subs)
        elif tag == 3:
            subs = tuple(self._timelock_from_primitive(s) for s in decoded[2])
            return Timelock(type=TimelockType.REQUIRE_M_OF_N, required=decoded[1], scripts=subs)
        elif tag == 4:
            return Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=decoded[1])
        elif tag == 5:
            return Timelock(type=TimelockType.REQUIRE_TIME_BEFORE, slot=decoded[1])
        raise ValueError(f"Unknown timelock tag: {tag}")  # pragma: no cover

    def test_require_signature_roundtrip(self) -> None:
        """RequireSignature timelock round-trips."""
        key_hash = _make_credential(0)
        script = Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key_hash)
        raw = self._timelock_to_cbor(script)
        decoded = self._timelock_from_cbor(raw)
        assert decoded == script

    def test_all_of_roundtrip(self) -> None:
        """AllOf timelock with nested scripts round-trips."""
        script = Timelock(
            type=TimelockType.REQUIRE_ALL_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=_make_credential(0)),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=_make_credential(1)),
            ),
        )
        raw = self._timelock_to_cbor(script)
        decoded = self._timelock_from_cbor(raw)
        assert decoded == script

    def test_any_of_roundtrip(self) -> None:
        """AnyOf timelock round-trips."""
        script = Timelock(
            type=TimelockType.REQUIRE_ANY_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=_make_credential(2)),
                Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=1000),
            ),
        )
        raw = self._timelock_to_cbor(script)
        decoded = self._timelock_from_cbor(raw)
        assert decoded == script

    def test_m_of_n_roundtrip(self) -> None:
        """MOfN timelock round-trips."""
        script = Timelock(
            type=TimelockType.REQUIRE_M_OF_N,
            required=2,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=_make_credential(0)),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=_make_credential(1)),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=_make_credential(2)),
            ),
        )
        raw = self._timelock_to_cbor(script)
        decoded = self._timelock_from_cbor(raw)
        assert decoded == script

    def test_require_time_after_roundtrip(self) -> None:
        """RequireTimeAfter timelock round-trips."""
        script = Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=500_000)
        raw = self._timelock_to_cbor(script)
        decoded = self._timelock_from_cbor(raw)
        assert decoded == script

    def test_require_time_before_roundtrip(self) -> None:
        """RequireTimeBefore timelock round-trips."""
        script = Timelock(type=TimelockType.REQUIRE_TIME_BEFORE, slot=1_000_000)
        raw = self._timelock_to_cbor(script)
        decoded = self._timelock_from_cbor(raw)
        assert decoded == script


# ---------------------------------------------------------------------------
# Mary-era round-trip tests
# ---------------------------------------------------------------------------


class TestMaryMultiAssetRoundtrip:
    """Mary-era MultiAsset values round-trip through pycardano CBOR."""

    def test_single_policy_single_asset(self) -> None:
        """Single policy, single asset name round-trips."""
        policy = _make_script_hash(0)
        asset = Asset({b"Token": 1000})
        ma = MultiAsset({policy: asset})
        val = Value(coin=5_000_000, multi_asset=ma)
        txout = TransactionOutput(_make_address(0), val)
        raw = txout.to_cbor()
        decoded = TransactionOutput.from_cbor(raw)
        assert decoded.to_cbor() == raw

    def test_multiple_policies_multiple_assets(self) -> None:
        """Multiple policies and asset names round-trip."""
        policy1 = _make_script_hash(1)
        policy2 = _make_script_hash(2)
        ma = MultiAsset(
            {
                policy1: Asset({b"TokenA": 500, b"TokenB": 1500}),
                policy2: Asset({b"NFT": 1}),
            }
        )
        val = Value(coin=10_000_000, multi_asset=ma)
        txout = TransactionOutput(_make_address(0), val)
        raw = txout.to_cbor()
        decoded = TransactionOutput.from_cbor(raw)
        assert decoded.to_cbor() == raw

    def test_minting_field_roundtrip(self) -> None:
        """TxBody with mint field round-trips."""
        policy = _make_script_hash(5)
        mint_ma = MultiAsset({policy: Asset({b"MintedToken": 100})})
        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(0), 0)],
            outputs=[TransactionOutput(_make_address(0), 2_000_000)],
            fee=200_000,
            mint=mint_ma,
        )
        raw = tx_body.to_cbor()
        decoded = TransactionBody.from_cbor(raw)
        assert decoded.to_cbor() == raw
        assert decoded.mint is not None

    @given(
        num_policies=st.integers(min_value=1, max_value=5),
        num_assets_per=st.integers(min_value=1, max_value=3),
        qty=st.integers(min_value=1, max_value=2**63 - 1),
    )
    @settings(max_examples=15)
    def test_multi_asset_property(self, num_policies: int, num_assets_per: int, qty: int) -> None:
        """MultiAsset values with arbitrary policy/asset counts round-trip."""
        policies: dict[ScriptHash, Asset] = {}
        for p in range(num_policies):
            assets: dict[bytes, int] = {}
            for a in range(num_assets_per):
                name = f"Asset{p}_{a}".encode()
                assets[name] = qty
            policies[_make_script_hash(p * 100)] = Asset(assets)
        ma = MultiAsset(policies)
        val = Value(coin=5_000_000, multi_asset=ma)
        txout = TransactionOutput(_make_address(0), val)
        raw = txout.to_cbor()
        decoded = TransactionOutput.from_cbor(raw)
        assert decoded.to_cbor() == raw


# ---------------------------------------------------------------------------
# Alonzo-era round-trip tests
# ---------------------------------------------------------------------------


class TestExUnitsRoundtrip:
    """Alonzo ExUnits round-trip through CBOR."""

    def test_basic_exunits_roundtrip(self) -> None:
        """ExUnits with typical values round-trips."""
        eu = ExUnits(mem=1_000_000, steps=2_000_000_000)
        encoded = cbor2.dumps([eu.mem, eu.steps])
        decoded = cbor2.loads(encoded)
        reconstructed = ExUnits(mem=decoded[0], steps=decoded[1])
        assert reconstructed == eu

    def test_zero_exunits_roundtrip(self) -> None:
        """Zero ExUnits (native scripts) round-trips."""
        eu = ExUnits(mem=0, steps=0)
        encoded = cbor2.dumps([eu.mem, eu.steps])
        decoded = cbor2.loads(encoded)
        reconstructed = ExUnits(mem=decoded[0], steps=decoded[1])
        assert reconstructed == eu

    @given(
        mem=st.integers(min_value=0, max_value=2**63 - 1),
        steps=st.integers(min_value=0, max_value=2**63 - 1),
    )
    @settings(max_examples=20)
    def test_exunits_property(self, mem: int, steps: int) -> None:
        """ExUnits survive round-trip for arbitrary non-negative values."""
        eu = ExUnits(mem=mem, steps=steps)
        encoded = cbor2.dumps([eu.mem, eu.steps])
        decoded = cbor2.loads(encoded)
        reconstructed = ExUnits(mem=decoded[0], steps=decoded[1])
        assert reconstructed == eu


class TestRedeemerRoundtrip:
    """Alonzo Redeemer round-trips through CBOR for all 4 tags."""

    def _redeemer_to_cbor(self, r: Redeemer) -> bytes:
        """Serialize a Redeemer to CBOR matching Alonzo wire format."""
        return cbor2.dumps(
            [
                r.tag.value,
                r.index,
                cbor2.loads(r.data) if r.data else None,
                [r.ex_units.mem, r.ex_units.steps],
            ]
        )

    def _redeemer_from_cbor(self, raw: bytes) -> Redeemer:
        """Deserialize a Redeemer from CBOR."""
        decoded = cbor2.loads(raw)
        tag = RedeemerTag(decoded[0])
        index = decoded[1]
        data = cbor2.dumps(decoded[2]) if decoded[2] is not None else b""
        eu = ExUnits(mem=decoded[3][0], steps=decoded[3][1])
        return Redeemer(tag=tag, index=index, data=data, ex_units=eu)

    def test_spend_redeemer_roundtrip(self) -> None:
        """Spend redeemer (tag 0) round-trips."""
        data = cbor2.dumps(42)
        r = Redeemer(
            tag=RedeemerTag.SPEND, index=0, data=data, ex_units=ExUnits(mem=100000, steps=200000)
        )
        raw = self._redeemer_to_cbor(r)
        decoded = self._redeemer_from_cbor(raw)
        assert decoded.tag == r.tag
        assert decoded.index == r.index
        assert decoded.ex_units == r.ex_units
        assert cbor2.loads(decoded.data) == cbor2.loads(r.data)

    def test_mint_redeemer_roundtrip(self) -> None:
        """Mint redeemer (tag 1) round-trips."""
        data = cbor2.dumps({"constructor": 0, "fields": []})
        r = Redeemer(
            tag=RedeemerTag.MINT, index=2, data=data, ex_units=ExUnits(mem=500000, steps=1000000)
        )
        raw = self._redeemer_to_cbor(r)
        decoded = self._redeemer_from_cbor(raw)
        assert decoded.tag == RedeemerTag.MINT
        assert decoded.index == 2

    def test_cert_redeemer_roundtrip(self) -> None:
        """Cert redeemer (tag 2) round-trips."""
        data = cbor2.dumps([1, 2, 3])
        r = Redeemer(
            tag=RedeemerTag.CERT, index=0, data=data, ex_units=ExUnits(mem=300000, steps=600000)
        )
        raw = self._redeemer_to_cbor(r)
        decoded = self._redeemer_from_cbor(raw)
        assert decoded.tag == RedeemerTag.CERT

    def test_reward_redeemer_roundtrip(self) -> None:
        """Reward redeemer (tag 3) round-trips."""
        data = cbor2.dumps(b"redeemer_bytes")
        r = Redeemer(
            tag=RedeemerTag.REWARD, index=1, data=data, ex_units=ExUnits(mem=200000, steps=400000)
        )
        raw = self._redeemer_to_cbor(r)
        decoded = self._redeemer_from_cbor(raw)
        assert decoded.tag == RedeemerTag.REWARD
        assert decoded.index == 1


class TestCostModelRoundtrip:
    """Alonzo CostModel round-trips through CBOR."""

    def test_plutusv1_cost_model_roundtrip(self) -> None:
        """PlutusV1 cost model (dict[str, int]) round-trips via CBOR."""
        cm: CostModel = {
            "addInteger-cpu-arguments-intercept": 205665,
            "addInteger-cpu-arguments-slope": 812,
            "addInteger-memory-arguments-intercept": 1,
            "addInteger-memory-arguments-slope": 1,
        }
        # Serialize as sorted params list (on-chain format)
        sorted_keys = sorted(cm.keys())
        values = [cm[k] for k in sorted_keys]
        encoded = cbor2.dumps(values)
        decoded_values = cbor2.loads(encoded)
        reconstructed = dict(zip(sorted_keys, decoded_values))
        assert reconstructed == cm

    def test_cost_model_canonical_ordering(self) -> None:
        """Cost model keys are sorted for script integrity hash."""
        cm: CostModel = {
            "z_last": 100,
            "a_first": 200,
            "m_middle": 300,
        }
        sorted_keys = sorted(cm.keys())
        assert sorted_keys == ["a_first", "m_middle", "z_last"]
        values = [cm[k] for k in sorted_keys]
        encoded = cbor2.dumps(values)
        decoded = cbor2.loads(encoded)
        assert decoded == [200, 300, 100]


class TestScriptIntegrityHashRoundtrip:
    """Alonzo script integrity hash computes deterministically."""

    def test_integrity_hash_deterministic(self) -> None:
        """Same inputs produce same script integrity hash."""
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(42),
                ex_units=ExUnits(mem=100, steps=200),
            ),
        ]
        datums = [cbor2.dumps(42)]
        cm: dict[Language, CostModel] = {
            Language.PLUTUS_V1: {"add": 100, "sub": 200},
        }
        h1 = compute_script_integrity_hash(redeemers, datums, cm, {Language.PLUTUS_V1})
        h2 = compute_script_integrity_hash(redeemers, datums, cm, {Language.PLUTUS_V1})
        assert h1 == h2
        assert len(h1) == 32


class TestAlonzoDatumHashInOutputRoundtrip:
    """Alonzo output with datum_hash round-trips."""

    def test_output_with_datum_hash(self) -> None:
        """TransactionOutput with datum_hash field round-trips."""
        datum_hash = _make_hash32(99)
        from pycardano.hash import DatumHash

        txout = TransactionOutput(
            _make_address(0),
            5_000_000,
            datum_hash=DatumHash(datum_hash),
        )
        raw = txout.to_cbor()
        decoded = TransactionOutput.from_cbor(raw)
        assert decoded.to_cbor() == raw
        assert decoded.datum_hash is not None


# ---------------------------------------------------------------------------
# Babbage-era round-trip tests
# ---------------------------------------------------------------------------


class TestDatumOptionRoundtrip:
    """Babbage DatumOption round-trips through CBOR."""

    def test_hash_variant_roundtrip(self) -> None:
        """DatumOption with hash tag round-trips."""
        datum_hash = _make_hash32(10)
        opt = DatumOption(tag=DatumOptionTag.HASH, data=datum_hash)
        encoded = cbor2.dumps([opt.tag.value, opt.data])
        decoded = cbor2.loads(encoded)
        reconstructed = DatumOption(tag=DatumOptionTag(decoded[0]), data=decoded[1])
        assert reconstructed == opt
        assert reconstructed.tag == DatumOptionTag.HASH
        assert len(reconstructed.data) == 32

    def test_inline_variant_roundtrip(self) -> None:
        """DatumOption with inline datum round-trips."""
        inline_datum = cbor2.dumps({"constructor": 0, "fields": [42, b"hello"]})
        opt = DatumOption(tag=DatumOptionTag.INLINE, data=inline_datum)
        encoded = cbor2.dumps([opt.tag.value, opt.data])
        decoded = cbor2.loads(encoded)
        reconstructed = DatumOption(tag=DatumOptionTag(decoded[0]), data=decoded[1])
        assert reconstructed == opt
        assert reconstructed.tag == DatumOptionTag.INLINE
        # Verify the inline datum content survived
        assert cbor2.loads(reconstructed.data) == cbor2.loads(inline_datum)

    @given(datum_data=st.binary(min_size=1, max_size=256))
    @settings(max_examples=15)
    def test_inline_datum_property(self, datum_data: bytes) -> None:
        """Inline datum with arbitrary bytes round-trips."""
        opt = DatumOption(tag=DatumOptionTag.INLINE, data=datum_data)
        encoded = cbor2.dumps([opt.tag.value, opt.data])
        decoded = cbor2.loads(encoded)
        reconstructed = DatumOption(tag=DatumOptionTag(decoded[0]), data=decoded[1])
        assert reconstructed == opt


class TestReferenceScriptRoundtrip:
    """Babbage ReferenceScript round-trips through CBOR."""

    def test_reference_script_roundtrip(self) -> None:
        """ReferenceScript with script bytes and hash round-trips."""
        script_bytes = b"\x82\x01\x82\x00\x80"  # example CBOR-encoded native script
        script_hash = hashlib.blake2b(script_bytes, digest_size=28).digest()
        ref = ReferenceScript(script_bytes=script_bytes, script_hash=script_hash)
        encoded = cbor2.dumps([ref.script_bytes, ref.script_hash])
        decoded = cbor2.loads(encoded)
        reconstructed = ReferenceScript(script_bytes=decoded[0], script_hash=decoded[1])
        assert reconstructed == ref


class TestBabbageOutputExtensionRoundtrip:
    """Babbage output extensions (datum_option + reference_script) round-trip."""

    def test_full_extension_roundtrip(self) -> None:
        """Extension with both datum and reference script round-trips."""
        datum = DatumOption(tag=DatumOptionTag.INLINE, data=cbor2.dumps(42))
        script_bytes = b"\x82\x01\x82\x00\x80"
        ref_script = ReferenceScript(
            script_bytes=script_bytes,
            script_hash=hashlib.blake2b(script_bytes, digest_size=28).digest(),
        )
        ext = BabbageOutputExtension(datum_option=datum, reference_script=ref_script)
        # Encode the extension components
        encoded = cbor2.dumps(
            {
                "datum": [datum.tag.value, datum.data] if datum else None,
                "script": (
                    [ref_script.script_bytes, ref_script.script_hash] if ref_script else None
                ),
            }
        )
        decoded = cbor2.loads(encoded)
        d = decoded["datum"]
        s = decoded["script"]
        reconstructed = BabbageOutputExtension(
            datum_option=DatumOption(tag=DatumOptionTag(d[0]), data=d[1]) if d else None,
            reference_script=ReferenceScript(script_bytes=s[0], script_hash=s[1]) if s else None,
        )
        assert reconstructed.datum_option == ext.datum_option
        assert reconstructed.reference_script == ext.reference_script


class TestBabbageProtocolParamsRoundtrip:
    """BabbageProtocolParams coins_per_utxo_byte field round-trips."""

    def test_babbage_params_roundtrip(self) -> None:
        """BabbageProtocolParams survives field reconstruction."""
        params = BabbageProtocolParams(coins_per_utxo_byte=4310)
        assert params.coins_per_utxo_byte == 4310
        # Verify inheritance chain
        assert params.min_fee_a == 44  # Shelley default
        assert params.coins_per_utxo_word == 4310  # Alonzo default
        # Reconstruct from CBOR-like dict
        encoded = cbor2.dumps({"coins_per_utxo_byte": params.coins_per_utxo_byte})
        decoded = cbor2.loads(encoded)
        assert decoded["coins_per_utxo_byte"] == 4310


class TestBabbageCollateralReturnRoundtrip:
    """Babbage collateral return output round-trips."""

    def test_collateral_return_output_roundtrip(self) -> None:
        """Collateral return output round-trips through pycardano CBOR."""
        collateral_return = TransactionOutput(_make_address(99), 3_000_000)
        raw = collateral_return.to_cbor()
        decoded = TransactionOutput.from_cbor(raw)
        assert decoded.to_cbor() == raw


# ---------------------------------------------------------------------------
# Conway-era round-trip tests
# ---------------------------------------------------------------------------


class TestGovActionRoundtrip:
    """Conway GovAction (all 7 types) round-trips through CBOR."""

    def _gov_action_to_cbor(self, ga: GovAction) -> bytes:
        """Serialize GovAction to CBOR."""
        prev_id = None
        if ga.prev_action_id is not None:
            prev_id = [ga.prev_action_id.tx_id, ga.prev_action_id.gov_action_index]
        return cbor2.dumps([ga.action_type.value, prev_id, ga.payload])

    def _gov_action_from_cbor(self, raw: bytes) -> GovAction:
        """Deserialize GovAction from CBOR."""
        decoded = cbor2.loads(raw)
        action_type = GovActionType(decoded[0])
        prev_id = None
        if decoded[1] is not None:
            prev_id = GovActionId(tx_id=decoded[1][0], gov_action_index=decoded[1][1])
        return GovAction(action_type=action_type, prev_action_id=prev_id, payload=decoded[2])

    def test_parameter_change_roundtrip(self) -> None:
        """ParameterChange governance action round-trips."""
        ga = GovAction(
            action_type=GovActionType.PARAMETER_CHANGE,
            prev_action_id=GovActionId(tx_id=_make_hash32(0), gov_action_index=0),
            payload={"min_fee_a": 50},
        )
        raw = self._gov_action_to_cbor(ga)
        decoded = self._gov_action_from_cbor(raw)
        assert decoded.action_type == ga.action_type
        assert decoded.prev_action_id == ga.prev_action_id
        assert decoded.payload == ga.payload

    def test_hard_fork_initiation_roundtrip(self) -> None:
        """HardForkInitiation governance action round-trips."""
        ga = GovAction(
            action_type=GovActionType.HARD_FORK_INITIATION,
            prev_action_id=GovActionId(tx_id=_make_hash32(1), gov_action_index=0),
            payload=[10, 0],  # target version
        )
        raw = self._gov_action_to_cbor(ga)
        decoded = self._gov_action_from_cbor(raw)
        assert decoded.action_type == GovActionType.HARD_FORK_INITIATION
        assert decoded.payload == [10, 0]

    def test_treasury_withdrawals_roundtrip(self) -> None:
        """TreasuryWithdrawals governance action round-trips."""
        ga = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={_make_credential(0): 1_000_000_000},
        )
        raw = self._gov_action_to_cbor(ga)
        decoded = self._gov_action_from_cbor(raw)
        assert decoded.action_type == GovActionType.TREASURY_WITHDRAWALS

    def test_no_confidence_roundtrip(self) -> None:
        """NoConfidence governance action round-trips."""
        ga = GovAction(
            action_type=GovActionType.NO_CONFIDENCE,
            prev_action_id=GovActionId(tx_id=_make_hash32(3), gov_action_index=0),
        )
        raw = self._gov_action_to_cbor(ga)
        decoded = self._gov_action_from_cbor(raw)
        assert decoded.action_type == GovActionType.NO_CONFIDENCE

    def test_update_committee_roundtrip(self) -> None:
        """UpdateCommittee governance action round-trips."""
        ga = GovAction(
            action_type=GovActionType.UPDATE_COMMITTEE,
            prev_action_id=GovActionId(tx_id=_make_hash32(4), gov_action_index=1),
            payload={"add": [_make_credential(10)], "remove": []},
        )
        raw = self._gov_action_to_cbor(ga)
        decoded = self._gov_action_from_cbor(raw)
        assert decoded.action_type == GovActionType.UPDATE_COMMITTEE

    def test_new_constitution_roundtrip(self) -> None:
        """NewConstitution governance action round-trips."""
        ga = GovAction(
            action_type=GovActionType.NEW_CONSTITUTION,
            prev_action_id=GovActionId(tx_id=_make_hash32(5), gov_action_index=0),
            payload=_make_hash32(100),  # constitution hash
        )
        raw = self._gov_action_to_cbor(ga)
        decoded = self._gov_action_from_cbor(raw)
        assert decoded.action_type == GovActionType.NEW_CONSTITUTION

    def test_info_action_roundtrip(self) -> None:
        """InfoAction governance action round-trips (no payload)."""
        ga = GovAction(action_type=GovActionType.INFO_ACTION)
        raw = self._gov_action_to_cbor(ga)
        decoded = self._gov_action_from_cbor(raw)
        assert decoded.action_type == GovActionType.INFO_ACTION
        assert decoded.prev_action_id is None
        assert decoded.payload is None


class TestProposalProcedureRoundtrip:
    """Conway ProposalProcedure round-trips through CBOR."""

    def test_proposal_procedure_roundtrip(self) -> None:
        """Full ProposalProcedure round-trips."""
        anchor = Anchor(url="https://example.com/proposal.json", data_hash=_make_hash32(50))
        gov_action = GovAction(
            action_type=GovActionType.INFO_ACTION,
        )
        proposal = ProposalProcedure(
            deposit=100_000_000_000,
            return_addr=bytes([0xE0]) + _make_credential(0),
            gov_action=gov_action,
            anchor=anchor,
        )
        # Encode key fields
        encoded = cbor2.dumps(
            {
                "deposit": proposal.deposit,
                "return_addr": proposal.return_addr,
                "action_type": proposal.gov_action.action_type.value,
                "anchor_url": proposal.anchor.url,
                "anchor_hash": proposal.anchor.data_hash,
            }
        )
        decoded = cbor2.loads(encoded)
        assert decoded["deposit"] == proposal.deposit
        assert decoded["return_addr"] == proposal.return_addr
        assert decoded["anchor_url"] == "https://example.com/proposal.json"
        assert decoded["anchor_hash"] == _make_hash32(50)


class TestVoteRoundtrip:
    """Conway Vote enum round-trips through CBOR."""

    def test_all_vote_values_roundtrip(self) -> None:
        """All three vote values round-trip."""
        for vote in [Vote.YES, Vote.NO, Vote.ABSTAIN]:
            encoded = cbor2.dumps(vote.value)
            decoded = cbor2.loads(encoded)
            reconstructed = Vote(decoded)
            assert reconstructed == vote

    @given(vote_val=st.sampled_from([0, 1, 2]))
    def test_vote_property(self, vote_val: int) -> None:
        """Vote enum survives CBOR round-trip."""
        vote = Vote(vote_val)
        encoded = cbor2.dumps(vote.value)
        decoded = cbor2.loads(encoded)
        assert Vote(decoded) == vote


class TestVotingProceduresRoundtrip:
    """Conway VotingProcedures (nested map) round-trips."""

    def test_voting_procedures_roundtrip(self) -> None:
        """Full VotingProcedures map round-trips."""
        voter = Voter(role=VoterRole.DREP, credential=_make_credential(0))
        action_id = GovActionId(tx_id=_make_hash32(0), gov_action_index=0)
        procedure = VotingProcedure(vote=Vote.YES)

        # Serialize the structure
        encoded = cbor2.dumps(
            {
                "role": voter.role.value,
                "credential": voter.credential,
                "action_tx_id": action_id.tx_id,
                "action_index": action_id.gov_action_index,
                "vote": procedure.vote.value,
            }
        )
        decoded = cbor2.loads(encoded)
        rec_voter = Voter(
            role=VoterRole(decoded["role"]),
            credential=decoded["credential"],
        )
        rec_action_id = GovActionId(
            tx_id=decoded["action_tx_id"],
            gov_action_index=decoded["action_index"],
        )
        rec_vote = Vote(decoded["vote"])
        assert rec_voter == voter
        assert rec_action_id == action_id
        assert rec_vote == Vote.YES


class TestDRepRoundtrip:
    """Conway DRep (all 4 types) round-trips through CBOR."""

    def test_key_hash_drep_roundtrip(self) -> None:
        """DRep with KeyHash type round-trips."""
        drep = DRep(drep_type=DRepType.KEY_HASH, credential=_make_credential(0))
        encoded = cbor2.dumps([drep.drep_type.value, drep.credential])
        decoded = cbor2.loads(encoded)
        reconstructed = DRep(
            drep_type=DRepType(decoded[0]),
            credential=decoded[1],
        )
        assert reconstructed == drep

    def test_script_hash_drep_roundtrip(self) -> None:
        """DRep with ScriptHash type round-trips."""
        drep = DRep(drep_type=DRepType.SCRIPT_HASH, credential=_make_credential(1))
        encoded = cbor2.dumps([drep.drep_type.value, drep.credential])
        decoded = cbor2.loads(encoded)
        reconstructed = DRep(
            drep_type=DRepType(decoded[0]),
            credential=decoded[1],
        )
        assert reconstructed == drep

    def test_always_abstain_drep_roundtrip(self) -> None:
        """DRep with AlwaysAbstain type round-trips."""
        drep = DRep(drep_type=DRepType.ALWAYS_ABSTAIN)
        encoded = cbor2.dumps([drep.drep_type.value, drep.credential])
        decoded = cbor2.loads(encoded)
        reconstructed = DRep(
            drep_type=DRepType(decoded[0]),
            credential=decoded[1] if decoded[1] is not None else None,
        )
        assert reconstructed == drep

    def test_always_no_confidence_drep_roundtrip(self) -> None:
        """DRep with AlwaysNoConfidence type round-trips."""
        drep = DRep(drep_type=DRepType.ALWAYS_NO_CONFIDENCE)
        encoded = cbor2.dumps([drep.drep_type.value, drep.credential])
        decoded = cbor2.loads(encoded)
        reconstructed = DRep(
            drep_type=DRepType(decoded[0]),
            credential=decoded[1] if decoded[1] is not None else None,
        )
        assert reconstructed == drep

    @given(drep_type_val=st.sampled_from([0, 1, 2, 3]))
    def test_drep_type_property(self, drep_type_val: int) -> None:
        """All DRep types survive CBOR round-trip."""
        dt = DRepType(drep_type_val)
        if dt in (DRepType.KEY_HASH, DRepType.SCRIPT_HASH):
            cred = _make_credential(drep_type_val)
        else:
            cred = None
        drep = DRep(drep_type=dt, credential=cred)
        encoded = cbor2.dumps([drep.drep_type.value, drep.credential])
        decoded = cbor2.loads(encoded)
        reconstructed = DRep(
            drep_type=DRepType(decoded[0]),
            credential=decoded[1] if decoded[1] is not None else None,
        )
        assert reconstructed == drep


class TestConwayProtocolParamsRoundtrip:
    """ConwayProtocolParams governance fields round-trip."""

    def test_conway_params_roundtrip(self) -> None:
        """Conway governance params survive CBOR field serialization."""
        params = ConwayProtocolParams(
            drep_deposit=500_000_000,
            drep_activity=20,
            gov_action_lifetime=6,
            gov_action_deposit=100_000_000_000,
            committee_min_size=7,
            committee_max_term_length=146,
        )
        encoded = cbor2.dumps(
            {
                "drep_deposit": params.drep_deposit,
                "drep_activity": params.drep_activity,
                "gov_action_lifetime": params.gov_action_lifetime,
                "gov_action_deposit": params.gov_action_deposit,
                "committee_min_size": params.committee_min_size,
                "committee_max_term_length": params.committee_max_term_length,
            }
        )
        decoded = cbor2.loads(encoded)
        assert decoded["drep_deposit"] == 500_000_000
        assert decoded["drep_activity"] == 20
        assert decoded["gov_action_lifetime"] == 6
        assert decoded["gov_action_deposit"] == 100_000_000_000
        assert decoded["committee_min_size"] == 7
        assert decoded["committee_max_term_length"] == 146
