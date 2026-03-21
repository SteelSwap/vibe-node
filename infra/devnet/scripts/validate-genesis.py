#!/usr/bin/env python3
"""Validate devnet genesis files for cardano-node 10.x compatibility.

This script checks all 4 genesis files (Byron, Shelley, Alonzo, Conway)
for structural correctness and known issues that prevent cardano-node
from starting.

Usage:
    cd infra/devnet
    python scripts/validate-genesis.py
"""

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
GENESIS_DIR = SCRIPT_DIR.parent / "genesis"

errors: list[str] = []
warnings: list[str] = []


def error(msg: str) -> None:
    errors.append(msg)
    print(f"  ERROR: {msg}")


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"  WARN:  {msg}")


def ok(msg: str) -> None:
    print(f"  OK:    {msg}")


def validate_json(filepath: Path) -> dict | None:
    """Load and validate JSON file."""
    if not filepath.exists():
        error(f"{filepath.name} not found")
        return None
    try:
        with open(filepath) as f:
            data = json.load(f)
        ok(f"{filepath.name} is valid JSON")
        return data
    except json.JSONDecodeError as e:
        error(f"{filepath.name} is invalid JSON: {e}")
        return None


def validate_shelley(data: dict) -> None:
    """Validate shelley-genesis.json for cardano-node 10.x."""
    print("\n--- Shelley Genesis ---")

    # Required top-level fields
    required_fields = [
        "activeSlotsCoeff",
        "epochLength",
        "genDelegs",
        "initialFunds",
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
    for field in required_fields:
        if field not in data:
            error(f"Missing required field: {field}")
        else:
            ok(f"Field '{field}' present")

    # maxMajorPV — needed for protocol version validation
    if "maxMajorPV" not in data:
        warn("Missing 'maxMajorPV' (recommended for Conway)")

    # Check initialFunds format: must be hex, NOT bech32
    funds = data.get("initialFunds", {})
    if funds:
        for addr in funds:
            if addr.startswith("addr_test1") or addr.startswith("addr1"):
                error(
                    f"initialFunds contains bech32 address: {addr[:30]}... "
                    "(cardano-node 10.x requires hex)"
                )
            elif re.match(r"^[0-9a-fA-F]+$", addr):
                ok(f"initialFunds address is hex: {addr[:20]}...")
            else:
                error(f"initialFunds address is neither bech32 nor hex: {addr[:30]}...")
    else:
        warn("initialFunds is empty")

    # Check systemStart
    system_start = data.get("systemStart", "")
    if system_start == "PLACEHOLDER_SYSTEM_START":
        ok("systemStart is placeholder (will be set by genesis-init)")
    elif "T" in system_start and "Z" in system_start:
        ok(f"systemStart is set: {system_start}")
    else:
        warn(f"systemStart looks suspicious: {system_start}")

    # Check genDelegs
    gen_delegs = data.get("genDelegs", {})
    if gen_delegs:
        ok(f"genDelegs has {len(gen_delegs)} entries")
        for gk_hash, deleg in gen_delegs.items():
            if "delegate" not in deleg:
                error(f"genDelegs[{gk_hash[:16]}...] missing 'delegate' field")
            if "vrf" not in deleg:
                error(f"genDelegs[{gk_hash[:16]}...] missing 'vrf' field")
    else:
        warn("genDelegs is empty (OK if decentralisationParam=0)")

    # Check protocolParams
    pp = data.get("protocolParams", {})
    required_pp = [
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
        "minUTxOValue",
        "nOpt",
        "poolDeposit",
        "protocolVersion",
        "rho",
        "tau",
    ]
    for field in required_pp:
        if field not in pp:
            error(f"protocolParams missing: {field}")

    pv = pp.get("protocolVersion", {})
    if pv.get("major", 0) < 10:
        warn(
            f"protocolVersion.major={pv.get('major')} "
            "(expected >= 10 for Conway devnet)"
        )

    # Check staking
    staking = data.get("staking", {})
    pools = staking.get("pools", {})
    stake = staking.get("stake", {})
    if pools:
        ok(f"staking.pools has {len(pools)} entries")
    else:
        warn("staking.pools is empty")
    if stake:
        ok(f"staking.stake has {len(stake)} entries")
    else:
        warn("staking.stake is empty")

    # Check numeric ranges
    if data.get("activeSlotsCoeff", 0) <= 0 or data.get("activeSlotsCoeff", 0) > 1:
        error(
            f"activeSlotsCoeff={data.get('activeSlotsCoeff')} "
            "must be in (0, 1]"
        )

    if data.get("maxKESEvolutions", 0) <= 0:
        error(f"maxKESEvolutions={data.get('maxKESEvolutions')} must be > 0")


def validate_byron(data: dict) -> None:
    """Validate byron-genesis.json."""
    print("\n--- Byron Genesis ---")

    required_fields = [
        "avvmDistr",
        "blockVersionData",
        "bootStakeholders",
        "heavyDelegation",
        "nonAvvmBalances",
        "protocolConsts",
        "startTime",
    ]
    for field in required_fields:
        if field not in data:
            error(f"Missing required field: {field}")
        else:
            ok(f"Field '{field}' present")

    # Check protocolConsts
    pc = data.get("protocolConsts", {})
    if "k" not in pc:
        error("protocolConsts missing 'k'")
    if "protocolMagic" not in pc:
        error("protocolConsts missing 'protocolMagic'")
    elif pc["protocolMagic"] != data.get("protocolConsts", {}).get("protocolMagic"):
        pass  # Tautology, but ensures it exists
    else:
        ok(f"protocolMagic={pc['protocolMagic']}")


def validate_alonzo(data: dict) -> None:
    """Validate alonzo-genesis.json."""
    print("\n--- Alonzo Genesis ---")

    required_fields = [
        "collateralPercentage",
        "costModels",
        "executionPrices",
        "lovelacePerUTxOWord",
        "maxBlockExUnits",
        "maxCollateralInputs",
        "maxTxExUnits",
        "maxValueSize",
    ]
    for field in required_fields:
        if field not in data:
            error(f"Missing required field: {field}")
        else:
            ok(f"Field '{field}' present")

    # Check cost models
    cost_models = data.get("costModels", {})
    if "PlutusV1" not in cost_models:
        warn("costModels missing PlutusV1")
    if "PlutusV2" not in cost_models:
        warn("costModels missing PlutusV2")


def validate_conway(data: dict) -> None:
    """Validate conway-genesis.json."""
    print("\n--- Conway Genesis ---")

    required_fields = [
        "poolVotingThresholds",
        "dRepVotingThresholds",
        "committeeMinSize",
        "committeeMaxTermLength",
        "govActionLifetime",
        "govActionDeposit",
        "dRepDeposit",
        "dRepActivity",
        "minFeeRefScriptCostPerByte",
        "plutusV3CostModel",
        "constitution",
        "committee",
    ]
    for field in required_fields:
        if field not in data:
            error(f"Missing required field: {field}")
        else:
            ok(f"Field '{field}' present")


def validate_config() -> None:
    """Validate config.json."""
    print("\n--- Node Config ---")

    config_file = GENESIS_DIR.parent / "config" / "config.json"
    data = validate_json(config_file)
    if data is None:
        return

    # Check hard fork epochs
    hf_fields = [
        "TestShelleyHardForkAtEpoch",
        "TestAllegraHardForkAtEpoch",
        "TestMaryHardForkAtEpoch",
        "TestAlonzoHardForkAtEpoch",
        "TestBabbageHardForkAtEpoch",
        "TestConwayHardForkAtEpoch",
    ]
    for field in hf_fields:
        if field in data:
            if data[field] == 0:
                ok(f"{field}=0 (immediate fork)")
            else:
                warn(f"{field}={data[field]} (not epoch 0)")
        else:
            warn(f"Missing {field}")

    # Check protocol
    if data.get("Protocol") != "Cardano":
        error(f"Protocol={data.get('Protocol')} (expected 'Cardano')")

    # Check genesis file paths
    for gf in [
        "ByronGenesisFile",
        "ShelleyGenesisFile",
        "AlonzoGenesisFile",
        "ConwayGenesisFile",
    ]:
        if gf in data:
            ok(f"{gf}={data[gf]}")
        else:
            error(f"Missing {gf}")


def main() -> int:
    print("=== Validating devnet genesis files ===")
    print(f"Genesis directory: {GENESIS_DIR}")

    # Validate each genesis file
    shelley = validate_json(GENESIS_DIR / "shelley-genesis.json")
    if shelley:
        validate_shelley(shelley)

    byron = validate_json(GENESIS_DIR / "byron-genesis.json")
    if byron:
        validate_byron(byron)

    alonzo = validate_json(GENESIS_DIR / "alonzo-genesis.json")
    if alonzo:
        validate_alonzo(alonzo)

    conway = validate_json(GENESIS_DIR / "conway-genesis.json")
    if conway:
        validate_conway(conway)

    # Validate config
    validate_config()

    # Summary
    print("\n=== Summary ===")
    print(f"  Errors:   {len(errors)}")
    print(f"  Warnings: {len(warnings)}")

    if errors:
        print("\nERRORS (must fix):")
        for e in errors:
            print(f"  - {e}")
        return 1

    if warnings:
        print("\nWarnings (review):")
        for w in warnings:
            print(f"  - {w}")

    print("\nAll validations passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
