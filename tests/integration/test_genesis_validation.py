"""Genesis file validation tests -- verify devnet genesis files are well-formed.

Validates the genesis JSON files in infra/devnet/genesis/ have all required
fields, correct structure, and no bech32 addresses (Cardano genesis files
use hex-encoded keys/addresses exclusively).

Haskell ref:
    Cardano.Ledger.Shelley.Genesis (ShelleyGenesis) -- required fields
    Cardano.Chain.Genesis.Config (GenesisData) -- Byron genesis structure
    Cardano.Ledger.Alonzo.Genesis (AlonzoGenesis) -- cost models
    Cardano.Ledger.Conway.Genesis (ConwayGenesis) -- governance params

Spec ref:
    Shelley formal spec, Section 2.1 -- genesis parameters
    CIP-1694 -- Conway governance parameters
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GENESIS_DIR = Path(__file__).resolve().parents[2] / "infra" / "devnet" / "genesis"


@pytest.fixture
def shelley_genesis() -> dict:
    return json.loads((GENESIS_DIR / "shelley-genesis.json").read_text())


@pytest.fixture
def byron_genesis() -> dict:
    return json.loads((GENESIS_DIR / "byron-genesis.json").read_text())


@pytest.fixture
def alonzo_genesis() -> dict:
    return json.loads((GENESIS_DIR / "alonzo-genesis.json").read_text())


@pytest.fixture
def conway_genesis() -> dict:
    return json.loads((GENESIS_DIR / "conway-genesis.json").read_text())


# ---------------------------------------------------------------------------
# Bech32 detection pattern
# ---------------------------------------------------------------------------

# Bech32 addresses start with a human-readable part followed by "1" and then
# the data part using the bech32 character set (qpzry9x8gf2tvdw0s3jn54khce6mua7l).
# Common Cardano prefixes: addr1, stake1, addr_test1, stake_test1, pool1, etc.
BECH32_PATTERN = re.compile(
    r"\b(?:addr|stake|pool|drep|cc_cold|cc_hot|addr_test|stake_test)"
    r"1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{6,}\b"
)


# ---------------------------------------------------------------------------
# Test 1: Shelley genesis required fields
# ---------------------------------------------------------------------------


class TestShelleyGenesis:
    """Verify shelley-genesis.json has all required fields.

    Haskell ref: ShelleyGenesis type in Cardano.Ledger.Shelley.Genesis
    """

    REQUIRED_FIELDS = [
        "activeSlotsCoeff",
        "epochLength",
        "genDelegs",
        "maxLovelaceSupply",
        "networkId",
        "networkMagic",
        "protocolParams",
        "securityParam",
        "slotLength",
        "slotsPerKESPeriod",
        "systemStart",
        "updateQuorum",
        "maxKESEvolutions",
    ]

    REQUIRED_PROTOCOL_PARAMS = [
        "a0",
        "decentralisationParam",
        "eMax",
        "keyDeposit",
        "maxBlockBodySize",
        "maxBlockHeaderSize",
        "maxTxSize",
        "minFeeA",
        "minFeeB",
        "minPoolCost",
        "nOpt",
        "poolDeposit",
        "protocolVersion",
        "rho",
        "tau",
    ]

    def test_has_all_required_top_level_fields(self, shelley_genesis: dict) -> None:
        for field_name in self.REQUIRED_FIELDS:
            assert (
                field_name in shelley_genesis
            ), f"Missing required field '{field_name}' in shelley-genesis.json"

    def test_has_all_required_protocol_params(self, shelley_genesis: dict) -> None:
        pp = shelley_genesis.get("protocolParams", {})
        for field_name in self.REQUIRED_PROTOCOL_PARAMS:
            assert field_name in pp, f"Missing required protocolParams field '{field_name}'"

    def test_active_slots_coeff_in_range(self, shelley_genesis: dict) -> None:
        coeff = shelley_genesis["activeSlotsCoeff"]
        assert 0 < coeff <= 1, f"activeSlotsCoeff must be (0, 1], got {coeff}"


# ---------------------------------------------------------------------------
# Test 2: Byron genesis required fields
# ---------------------------------------------------------------------------


class TestByronGenesis:
    """Verify byron-genesis.json has all required fields.

    Haskell ref: GenesisData in Cardano.Chain.Genesis.Config
    """

    REQUIRED_FIELDS = [
        "blockVersionData",
        "protocolConsts",
        "startTime",
        "heavyDelegation",
        "avvmDistr",
    ]

    REQUIRED_BLOCK_VERSION_DATA = [
        "heavyDelThd",
        "maxBlockSize",
        "maxHeaderSize",
        "maxTxSize",
        "slotDuration",
        "softforkRule",
        "txFeePolicy",
    ]

    REQUIRED_PROTOCOL_CONSTS = [
        "k",
        "protocolMagic",
    ]

    def test_has_all_required_top_level_fields(self, byron_genesis: dict) -> None:
        for field_name in self.REQUIRED_FIELDS:
            assert (
                field_name in byron_genesis
            ), f"Missing required field '{field_name}' in byron-genesis.json"

    def test_has_block_version_data_fields(self, byron_genesis: dict) -> None:
        bvd = byron_genesis.get("blockVersionData", {})
        for field_name in self.REQUIRED_BLOCK_VERSION_DATA:
            assert field_name in bvd, f"Missing required blockVersionData field '{field_name}'"

    def test_has_protocol_consts_fields(self, byron_genesis: dict) -> None:
        pc = byron_genesis.get("protocolConsts", {})
        for field_name in self.REQUIRED_PROTOCOL_CONSTS:
            assert field_name in pc, f"Missing required protocolConsts field '{field_name}'"


# ---------------------------------------------------------------------------
# Test 3: Alonzo genesis cost model fields
# ---------------------------------------------------------------------------


class TestAlonzoGenesis:
    """Verify alonzo-genesis.json has required cost model fields.

    Haskell ref: AlonzoGenesis in Cardano.Ledger.Alonzo.Genesis
    """

    REQUIRED_FIELDS = [
        "costModels",
        "executionPrices",
        "maxTxExUnits",
        "maxBlockExUnits",
        "maxValueSize",
        "collateralPercentage",
        "maxCollateralInputs",
    ]

    def test_has_all_required_fields(self, alonzo_genesis: dict) -> None:
        for field_name in self.REQUIRED_FIELDS:
            assert (
                field_name in alonzo_genesis
            ), f"Missing required field '{field_name}' in alonzo-genesis.json"

    def test_has_plutus_v1_cost_model(self, alonzo_genesis: dict) -> None:
        cost_models = alonzo_genesis.get("costModels", {})
        assert "PlutusV1" in cost_models, "Missing PlutusV1 cost model"
        assert isinstance(cost_models["PlutusV1"], list), "PlutusV1 must be a list"
        assert len(cost_models["PlutusV1"]) > 0, "PlutusV1 cost model is empty"

    def test_has_plutus_v2_cost_model(self, alonzo_genesis: dict) -> None:
        cost_models = alonzo_genesis.get("costModels", {})
        assert "PlutusV2" in cost_models, "Missing PlutusV2 cost model"
        assert isinstance(cost_models["PlutusV2"], list), "PlutusV2 must be a list"
        assert len(cost_models["PlutusV2"]) > 0, "PlutusV2 cost model is empty"

    def test_execution_prices_structure(self, alonzo_genesis: dict) -> None:
        prices = alonzo_genesis.get("executionPrices", {})
        for key in ("prMem", "prSteps"):
            assert key in prices, f"Missing executionPrices.{key}"
            assert "numerator" in prices[key], f"Missing {key}.numerator"
            assert "denominator" in prices[key], f"Missing {key}.denominator"


# ---------------------------------------------------------------------------
# Test 4: Conway genesis governance params
# ---------------------------------------------------------------------------


class TestConwayGenesis:
    """Verify conway-genesis.json has governance parameters.

    Haskell ref: ConwayGenesis in Cardano.Ledger.Conway.Genesis
    Spec ref: CIP-1694 -- governance actions, DReps, constitutional committee
    """

    REQUIRED_FIELDS = [
        "poolVotingThresholds",
        "dRepVotingThresholds",
        "committeeMinSize",
        "committeeMaxTermLength",
        "govActionLifetime",
        "govActionDeposit",
        "dRepDeposit",
        "dRepActivity",
        "constitution",
        "committee",
    ]

    REQUIRED_POOL_THRESHOLDS = [
        "committeeNormal",
        "committeeNoConfidence",
        "hardForkInitiation",
        "motionNoConfidence",
        "ppSecurityGroup",
    ]

    REQUIRED_DREP_THRESHOLDS = [
        "motionNoConfidence",
        "committeeNormal",
        "committeeNoConfidence",
        "updateToConstitution",
        "hardForkInitiation",
        "ppNetworkGroup",
        "ppEconomicGroup",
        "ppTechnicalGroup",
        "ppGovGroup",
        "treasuryWithdrawal",
    ]

    def test_has_all_required_fields(self, conway_genesis: dict) -> None:
        for field_name in self.REQUIRED_FIELDS:
            assert (
                field_name in conway_genesis
            ), f"Missing required field '{field_name}' in conway-genesis.json"

    def test_pool_voting_thresholds(self, conway_genesis: dict) -> None:
        pvt = conway_genesis.get("poolVotingThresholds", {})
        for field_name in self.REQUIRED_POOL_THRESHOLDS:
            assert field_name in pvt, f"Missing poolVotingThresholds.{field_name}"
            assert (
                0 <= pvt[field_name] <= 1
            ), f"poolVotingThresholds.{field_name} must be [0, 1], got {pvt[field_name]}"

    def test_drep_voting_thresholds(self, conway_genesis: dict) -> None:
        dvt = conway_genesis.get("dRepVotingThresholds", {})
        for field_name in self.REQUIRED_DREP_THRESHOLDS:
            assert field_name in dvt, f"Missing dRepVotingThresholds.{field_name}"
            assert (
                0 <= dvt[field_name] <= 1
            ), f"dRepVotingThresholds.{field_name} must be [0, 1], got {dvt[field_name]}"


# ---------------------------------------------------------------------------
# Test 5: No bech32 addresses in any genesis file
# ---------------------------------------------------------------------------


class TestNoBech32Addresses:
    """Genesis files must use hex-encoded keys/addresses, never bech32.

    Cardano genesis files use raw hex for all cryptographic material.
    Bech32 encoding (addr1..., stake1..., pool1...) is a user-facing
    convenience and must not appear in genesis configuration.
    """

    @pytest.mark.parametrize(
        "filename",
        [
            "shelley-genesis.json",
            "byron-genesis.json",
            "alonzo-genesis.json",
            "conway-genesis.json",
        ],
    )
    def test_no_bech32_in_genesis(self, filename: str) -> None:
        filepath = GENESIS_DIR / filename
        content = filepath.read_text()
        matches = BECH32_PATTERN.findall(content)
        assert len(matches) == 0, f"Found bech32 address(es) in {filename}: {matches[:5]}"
