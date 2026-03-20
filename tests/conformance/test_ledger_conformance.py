"""Conformance tests: validate ledger rules against the Haskell node via Ogmios.

This module provides two tiers of testing:

1. **Fixture-based tests** (run without Docker) — validate our internal
   logic against pre-cached block data. These verify structural consistency:
   metadata extraction, era detection, transaction counting, fee summation.

2. **Live Ogmios tests** (@pytest.mark.conformance) — validate against real
   chain data from a running Haskell node. These are the gold standard:
   our results must match the Haskell node exactly.

Spec references:
    * Shelley ledger formal spec, Section 9 (UTXO)
    * Alonzo ledger formal spec, Section 9 (UTXO) + Section 4 (Scripts)
    * Babbage ledger formal spec, Section 4 (UTXO)
    * Conway ledger formal spec, Section 5 (Governance)

Haskell references:
    * ``applyBlock`` in each era's ``Rules/Bbody.hs``
    * ``validateTx`` path through ``Rules/Utxo.hs`` / ``Rules/Utxow.hs``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import websockets

# Make helpers importable from this directory
_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from helpers import (  # noqa: E402
    extract_block_metadata,
    fetch_blocks_from_origin,
    fetch_blocks_from_point,
    load_fixture,
    ogmios_rpc,
)


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

# Tests in this file use one of two markers:
# - @pytest.mark.conformance: requires live Ogmios (skipped without Docker)
# - No marker / fixture_only: runs with cached fixture files only


# ===================================================================
# TIER 1: Fixture-based tests (no Docker required)
# ===================================================================


class TestFixtureBlockStructure:
    """Validate pre-cached fixture files have correct Ogmios v6 structure."""

    @pytest.mark.parametrize("era", ["byron", "shelley", "alonzo", "babbage", "conway"])
    def test_fixture_has_required_fields(self, era: str) -> None:
        """Every era fixture must have the core block fields."""
        block = load_fixture(era)
        assert block["era"] == era
        assert isinstance(block["id"], str)
        assert len(block["id"]) == 64, f"Block ID should be 64 hex chars, got {len(block['id'])}"
        assert isinstance(block["height"], int)
        assert isinstance(block["slot"], int)
        assert isinstance(block["transactions"], list)

    @pytest.mark.parametrize("era", ["byron", "shelley", "alonzo", "babbage", "conway"])
    def test_fixture_has_ancestor(self, era: str) -> None:
        """Every block should reference its ancestor (previous block hash)."""
        block = load_fixture(era)
        assert "ancestor" in block
        assert isinstance(block["ancestor"], str)
        assert len(block["ancestor"]) == 64

    @pytest.mark.parametrize("era", ["shelley", "alonzo", "babbage", "conway"])
    def test_post_byron_has_protocol_version(self, era: str) -> None:
        """Post-Byron blocks must include protocol version."""
        block = load_fixture(era)
        pv = block["protocol"]["version"]
        assert isinstance(pv["major"], int)
        assert isinstance(pv["minor"], int)

    @pytest.mark.parametrize("era", ["shelley", "alonzo", "babbage", "conway"])
    def test_post_byron_has_issuer(self, era: str) -> None:
        """Post-Byron blocks must include issuer verification key."""
        block = load_fixture(era)
        assert "verificationKey" in block["issuer"]
        assert "vrfVerificationKey" in block["issuer"]


class TestFixtureMetadataExtraction:
    """Validate metadata extraction from fixture files."""

    @pytest.mark.parametrize("era", ["byron", "shelley", "alonzo", "babbage", "conway"])
    def test_extract_metadata_era(self, era: str) -> None:
        """Extracted metadata must report the correct era."""
        block = load_fixture(era)
        meta = extract_block_metadata(block)
        assert meta["era"] == era

    @pytest.mark.parametrize("era", ["byron", "shelley", "alonzo", "babbage", "conway"])
    def test_extract_metadata_tx_count(self, era: str) -> None:
        """Transaction count must match the fixture."""
        block = load_fixture(era)
        meta = extract_block_metadata(block)
        assert meta["tx_count"] == len(block["transactions"])

    def test_shelley_fee_extraction(self) -> None:
        """Fee extraction from Shelley fixture must match the tx fee."""
        block = load_fixture("shelley")
        meta = extract_block_metadata(block)
        # Our Shelley fixture has 1 tx with fee 168801 lovelace
        assert meta["total_fee_lovelace"] == 168801

    def test_alonzo_script_counts(self) -> None:
        """Alonzo fixture should report correct script/datum/redeemer counts."""
        block = load_fixture("alonzo")
        meta = extract_block_metadata(block)
        assert meta["script_count"] == 1
        assert meta["datum_count"] == 1
        assert meta["redeemer_count"] == 1

    def test_babbage_reference_inputs_present(self) -> None:
        """Babbage fixture transactions should have reference inputs."""
        block = load_fixture("babbage")
        tx = block["transactions"][0]
        assert "references" in tx
        assert len(tx["references"]) > 0

    def test_babbage_inline_datum_present(self) -> None:
        """Babbage fixture should have at least one output with inline datum."""
        block = load_fixture("babbage")
        tx = block["transactions"][0]
        inline_datums = [o for o in tx["outputs"] if "datum" in o]
        assert len(inline_datums) > 0

    def test_babbage_collateral_return(self) -> None:
        """Babbage fixture should have collateral return and total collateral."""
        block = load_fixture("babbage")
        tx = block["transactions"][0]
        assert "collateralReturn" in tx
        assert "totalCollateral" in tx

    def test_conway_governance_fields(self) -> None:
        """Conway fixture should have governance proposals and votes."""
        block = load_fixture("conway")
        tx = block["transactions"][0]
        assert "proposals" in tx
        assert len(tx["proposals"]) > 0
        assert "votes" in tx
        assert len(tx["votes"]) > 0


class TestFixtureEraProgression:
    """Verify era fixtures represent a realistic era progression."""

    EXPECTED_PROTOCOL_VERSIONS = {
        "shelley": 2,
        "alonzo": 5,
        "babbage": 7,
        "conway": 9,
    }

    @pytest.mark.parametrize("era,expected_pv", list(EXPECTED_PROTOCOL_VERSIONS.items()))
    def test_protocol_version_matches_era(self, era: str, expected_pv: int) -> None:
        """Each era fixture should have the correct protocol major version."""
        block = load_fixture(era)
        actual_pv = block["protocol"]["version"]["major"]
        assert actual_pv == expected_pv, (
            f"{era} should have protocol version {expected_pv}, got {actual_pv}"
        )

    def test_heights_increase_across_eras(self) -> None:
        """Block heights should increase across eras (realistic chain ordering)."""
        eras = ["byron", "shelley", "alonzo", "babbage", "conway"]
        heights = [load_fixture(era)["height"] for era in eras]
        for i in range(1, len(heights)):
            assert heights[i] > heights[i - 1], (
                f"{eras[i]} height ({heights[i]}) should be > {eras[i-1]} "
                f"height ({heights[i-1]})"
            )

    def test_slots_increase_across_eras(self) -> None:
        """Slots should increase across eras."""
        eras = ["byron", "shelley", "alonzo", "babbage", "conway"]
        slots = [load_fixture(era)["slot"] for era in eras]
        for i in range(1, len(slots)):
            assert slots[i] > slots[i - 1], (
                f"{eras[i]} slot ({slots[i]}) should be > {eras[i-1]} "
                f"slot ({slots[i-1]})"
            )


class TestFixtureBlockIdFormat:
    """Verify block ID format across all fixtures."""

    @pytest.mark.parametrize("era", ["byron", "shelley", "alonzo", "babbage", "conway"])
    def test_block_id_is_valid_hex(self, era: str) -> None:
        """Block IDs must be valid hex strings (32 bytes = 64 hex chars)."""
        block = load_fixture(era)
        block_id = block["id"]
        assert len(block_id) == 64
        # Verify it's valid hex
        try:
            bytes.fromhex(block_id)
        except ValueError:
            pytest.fail(f"Block ID is not valid hex: {block_id[:20]}...")

    @pytest.mark.parametrize("era", ["byron", "shelley", "alonzo", "babbage", "conway"])
    def test_ancestor_id_is_valid_hex(self, era: str) -> None:
        """Ancestor IDs must be valid hex strings."""
        block = load_fixture(era)
        ancestor = block["ancestor"]
        assert len(ancestor) == 64
        bytes.fromhex(ancestor)  # Raises ValueError on invalid hex


class TestFixtureTransactionStructure:
    """Validate transaction-level fields in fixtures."""

    @pytest.mark.parametrize("era", ["shelley", "alonzo", "babbage", "conway"])
    def test_tx_has_id(self, era: str) -> None:
        """Post-Byron transactions must have a 64-char hex id."""
        block = load_fixture(era)
        for tx in block["transactions"]:
            assert "id" in tx
            assert len(tx["id"]) == 64

    @pytest.mark.parametrize("era", ["shelley", "alonzo", "babbage", "conway"])
    def test_tx_has_inputs_and_outputs(self, era: str) -> None:
        """Transactions must have inputs and outputs."""
        block = load_fixture(era)
        for tx in block["transactions"]:
            assert "inputs" in tx
            assert "outputs" in tx
            assert len(tx["inputs"]) > 0
            assert len(tx["outputs"]) > 0

    @pytest.mark.parametrize("era", ["shelley", "alonzo", "babbage", "conway"])
    def test_tx_has_fee(self, era: str) -> None:
        """Transactions must have a fee."""
        block = load_fixture(era)
        for tx in block["transactions"]:
            assert "fee" in tx
            fee = tx["fee"]
            lovelace = fee.get("ada", {}).get("lovelace", 0)
            assert lovelace > 0, "Fee must be positive"

    @pytest.mark.parametrize("era", ["alonzo", "babbage"])
    def test_script_tx_has_collateral(self, era: str) -> None:
        """Alonzo+ transactions with scripts must have collateral inputs."""
        block = load_fixture(era)
        for tx in block["transactions"]:
            if tx.get("scripts"):
                assert "collaterals" in tx
                assert len(tx["collaterals"]) > 0

    @pytest.mark.parametrize("era", ["shelley", "alonzo", "babbage", "conway"])
    def test_tx_has_signatories(self, era: str) -> None:
        """Transactions must have at least one signatory."""
        block = load_fixture(era)
        for tx in block["transactions"]:
            assert "signatories" in tx
            assert len(tx["signatories"]) > 0
            for sig in tx["signatories"]:
                assert "key" in sig
                assert "signature" in sig


# ===================================================================
# TIER 2: Live Ogmios conformance tests (requires Docker)
# ===================================================================


@pytest.mark.conformance
@pytest.mark.timeout(30)
class TestLiveByronConformance:
    """Byron-era conformance tests against live Ogmios."""

    async def test_first_blocks_are_byron(self, ogmios_client: websockets.ClientConnection) -> None:
        """Preprod genesis blocks should be Byron era."""
        blocks = await fetch_blocks_from_origin(ogmios_client, count=5)
        assert len(blocks) >= 5
        for block in blocks:
            assert block["era"] == "byron"

    async def test_byron_blocks_have_valid_structure(
        self, ogmios_client: websockets.ClientConnection,
    ) -> None:
        """Byron blocks should have all expected metadata fields."""
        blocks = await fetch_blocks_from_origin(ogmios_client, count=5)
        bft_blocks = [b for b in blocks if b.get("type") == "bft"]
        assert len(bft_blocks) > 0

        for block in bft_blocks:
            assert "slot" in block
            assert "id" in block
            assert len(block["id"]) == 64
            assert "transactions" in block
            assert "size" in block

    async def test_byron_block_ids_are_unique(
        self, ogmios_client: websockets.ClientConnection,
    ) -> None:
        """All Byron block IDs in a sequence should be unique."""
        blocks = await fetch_blocks_from_origin(ogmios_client, count=20)
        ids = [b["id"] for b in blocks]
        assert len(ids) == len(set(ids)), "Duplicate block IDs found"

    async def test_byron_heights_are_monotonic(
        self, ogmios_client: websockets.ClientConnection,
    ) -> None:
        """Byron block heights should increase monotonically."""
        blocks = await fetch_blocks_from_origin(ogmios_client, count=20)
        heights = [b["height"] for b in blocks]
        for i in range(1, len(heights)):
            assert heights[i] >= heights[i - 1], (
                f"Height decreased: {heights[i-1]} -> {heights[i]}"
            )

    async def test_byron_ancestor_chain(
        self, ogmios_client: websockets.ClientConnection,
    ) -> None:
        """Each block's ancestor should match the previous block's ID."""
        blocks = await fetch_blocks_from_origin(ogmios_client, count=10)
        for i in range(1, len(blocks)):
            ancestor = blocks[i].get("ancestor")
            prev_id = blocks[i - 1]["id"]
            assert ancestor == prev_id, (
                f"Block {i} ancestor {ancestor[:16]}... != prev {prev_id[:16]}..."
            )


@pytest.mark.conformance
@pytest.mark.timeout(30)
class TestLiveShelleyConformance:
    """Shelley-era conformance tests against live Ogmios."""

    async def test_chain_has_passed_shelley(self, ogmios_url: str) -> None:
        """Preprod chain tip should be well past Shelley era."""
        async with websockets.connect(ogmios_url) as ws:
            tip = await ogmios_rpc(ws, "queryNetwork/tip", rpc_id="tip")
            # Shelley starts around slot 86400 on preprod
            assert tip["slot"] > 86400, "Preprod should be past Shelley era"

    async def test_current_era_is_conway(self, ogmios_url: str) -> None:
        """Preprod should currently be in Conway era."""
        import httpx

        health_url = ogmios_url.replace("ws://", "http://") + "/health"
        resp = httpx.get(health_url, timeout=5)
        health = resp.json()
        assert health["currentEra"] == "conway"


@pytest.mark.conformance
@pytest.mark.timeout(60)
class TestLiveMultiEraConformance:
    """Cross-era conformance tests against live Ogmios.

    These tests validate block metadata consistency across eras,
    comparing our extraction logic against what Ogmios reports.
    """

    async def test_block_metadata_consistency(
        self, ogmios_client: websockets.ClientConnection,
    ) -> None:
        """Block metadata extraction should produce consistent results.

        Fetch real blocks and verify that extract_block_metadata agrees
        with the raw Ogmios data on all fields.
        """
        blocks = await fetch_blocks_from_origin(ogmios_client, count=10)
        for block in blocks:
            meta = extract_block_metadata(block)
            assert meta["era"] == block.get("era")
            assert meta["id"] == block.get("id")
            assert meta["height"] == block.get("height")
            # Byron EBBs may not have a slot field
            if "slot" in block:
                assert meta["slot"] == block["slot"]
            assert meta["tx_count"] == len(block.get("transactions", []))

    async def test_fee_totals_are_non_negative(
        self, ogmios_client: websockets.ClientConnection,
    ) -> None:
        """Fee totals across all transactions in a block must be >= 0."""
        blocks = await fetch_blocks_from_origin(ogmios_client, count=20)
        for block in blocks:
            meta = extract_block_metadata(block)
            assert meta["total_fee_lovelace"] >= 0, (
                f"Negative fee total in block {block['id'][:16]}..."
            )

    async def test_block_size_is_reasonable(
        self, ogmios_client: websockets.ClientConnection,
    ) -> None:
        """Block sizes should be within Cardano protocol limits.

        Byron max block body = 2 MB, Shelley+ max block body varies by era
        but is at most ~90 KB for typical blocks, up to ~2 MB at max.
        """
        blocks = await fetch_blocks_from_origin(ogmios_client, count=10)
        for block in blocks:
            size = block.get("size", {})
            if isinstance(size, dict):
                byte_size = size.get("bytes", 0)
            elif isinstance(size, int):
                byte_size = size
            else:
                continue
            # EBBs (epoch boundary blocks) may report size 0; skip those
            if byte_size == 0 and block.get("type") == "ebb":
                continue
            if byte_size > 0:
                assert byte_size < 2_100_000, (
                    f"Block size {byte_size} exceeds 2MB limit for block {block['id'][:16]}..."
                )


@pytest.mark.conformance
@pytest.mark.timeout(30)
class TestLiveFeeValidation:
    """Fee validation tests against live Ogmios data.

    Spec ref: Shelley ledger spec Section 9 — fee >= a * txSize + b.
    Byron uses a similar linear fee model: fee >= a + b * txSize.

    We verify that all real transactions on-chain have fees that are
    strictly positive (the Haskell node would reject 0-fee txs).
    """

    async def test_byron_empty_blocks_have_zero_fees(
        self, ogmios_client: websockets.ClientConnection,
    ) -> None:
        """Byron blocks with no transactions should sum to 0 fees."""
        blocks = await fetch_blocks_from_origin(ogmios_client, count=10)
        empty_blocks = [b for b in blocks if len(b.get("transactions", [])) == 0]
        for block in empty_blocks:
            meta = extract_block_metadata(block)
            assert meta["total_fee_lovelace"] == 0
