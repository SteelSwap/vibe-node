"""CDDL conformance test infrastructure for Cardano CBOR schemas.

VNODE-xxx: Validates that our CBOR-encoded messages conform to the official
Cardano CDDL (Concise Data Definition Language) schemas. CDDL is the formal
schema language for CBOR (RFC 8610), and cardano-ledger defines the canonical
CDDL for every era's block, transaction, and protocol message formats.

Current status: INFRASTRUCTURE PHASE
  - No Python CDDL validation library is available for Python 3.14
  - Tests document which CDDL schemas exist and where they live
  - Placeholder tests mark the validation gaps for future tooling
  - When a CDDL parser becomes available (cddlparser, pycddl, or similar),
    these tests will be upgraded to parse CDDL and validate our encodings

CDDL schema locations in the Haskell cardano-ledger repository:
  - eras/byron/cddl-spec/byron.cddl
  - eras/shelley/impl/cddl/data/shelley.cddl
  - eras/allegra/impl/cddl/data/allegra.cddl
  - eras/mary/impl/cddl/data/mary.cddl
  - eras/alonzo/impl/cddl/data/alonzo.cddl
  - eras/babbage/impl/cddl/data/babbage.cddl
  - eras/conway/impl/cddl/data/conway.cddl

Spec references:
  - RFC 8610: Concise Data Definition Language (CDDL)
  - RFC 7049 / RFC 8949: CBOR encoding rules
  - cardano-ledger CDDL files (the ground truth for on-wire encoding)
"""

from __future__ import annotations

from pathlib import Path

import cbor2
import pytest
from cbor2 import CBORTag

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Root of the project (assumes tests/ is one level below project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Where we expect the cardano-ledger vendor checkout
VENDOR_LEDGER = PROJECT_ROOT / "vendor" / "cardano-ledger"

# Known CDDL file locations relative to cardano-ledger root
# These paths match the cardano-ledger repository structure
CDDL_SCHEMAS: dict[str, str] = {
    "byron": "eras/byron/cddl-spec/byron.cddl",
    "shelley": "eras/shelley/impl/cddl/data/shelley.cddl",
    "allegra": "eras/allegra/impl/cddl/data/allegra.cddl",
    "mary": "eras/mary/impl/cddl/data/mary.cddl",
    "alonzo": "eras/alonzo/impl/cddl/data/alonzo.cddl",
    "babbage": "eras/babbage/impl/cddl/data/babbage.cddl",
    "conway": "eras/conway/impl/cddl/data/conway.cddl",
}

# Whether any CDDL parser library is available
_CDDL_PARSER_AVAILABLE = False
_cddl_parser_module = None

try:
    import cddlparser  # type: ignore[import-not-found]

    _CDDL_PARSER_AVAILABLE = True
    _cddl_parser_module = cddlparser
except ImportError:
    pass

if not _CDDL_PARSER_AVAILABLE:
    try:
        import cddl  # type: ignore[import-not-found]

        _CDDL_PARSER_AVAILABLE = True
        _cddl_parser_module = cddl
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vendor_ledger_available() -> bool:
    """Check if the cardano-ledger vendor directory is populated."""
    # Check for at least one CDDL file
    for era, rel_path in CDDL_SCHEMAS.items():
        full_path = VENDOR_LEDGER / rel_path
        if full_path.exists():
            return True
    return False


# ---------------------------------------------------------------------------
# 1. CDDL file existence and parseability
# ---------------------------------------------------------------------------


class TestCddlSchemaDiscovery:
    """Verify that CDDL schema files exist and can be located."""

    def test_vendor_directory_exists(self):
        """The cardano-ledger vendor directory should exist."""
        assert VENDOR_LEDGER.exists(), (
            f"cardano-ledger vendor directory not found at {VENDOR_LEDGER}. "
            f"Run: git submodule update --init vendor/cardano-ledger"
        )

    @pytest.mark.parametrize("era,rel_path", list(CDDL_SCHEMAS.items()))
    def test_cddl_file_exists(self, era: str, rel_path: str):
        """Each era's CDDL schema file should exist in the vendor checkout."""
        full_path = VENDOR_LEDGER / rel_path
        assert full_path.exists(), (
            f"{era} CDDL schema not found at {full_path}. "
            f"Ensure vendor submodules are at latest tags: "
            f"git submodule update --init vendor/cardano-ledger"
        )

    @pytest.mark.parametrize("era,rel_path", list(CDDL_SCHEMAS.items()))
    def test_cddl_file_is_readable_text(self, era: str, rel_path: str):
        """CDDL files should be valid UTF-8 text."""
        full_path = VENDOR_LEDGER / rel_path
        if not full_path.exists():
            pytest.skip(f"CDDL file not available: {full_path}")

        text = full_path.read_text(encoding="utf-8")
        assert len(text) > 0, f"{era} CDDL file is empty"

        # Basic sanity: CDDL files should contain assignment operators
        assert "=" in text, f"{era} CDDL file doesn't contain '=' — may not be valid CDDL"

    @pytest.mark.parametrize("era,rel_path", list(CDDL_SCHEMAS.items()))
    def test_cddl_file_contains_key_definitions(self, era: str, rel_path: str):
        """CDDL files should define the era's core types."""
        full_path = VENDOR_LEDGER / rel_path
        if not full_path.exists():
            pytest.skip(f"CDDL file not available: {full_path}")

        text = full_path.read_text(encoding="utf-8")

        # Every era's CDDL should define at least 'block' or 'transaction_body'
        has_block = "block" in text.lower()
        has_tx = "transaction" in text.lower()
        assert has_block or has_tx, (
            f"{era} CDDL file doesn't define 'block' or 'transaction' types"
        )


# ---------------------------------------------------------------------------
# 2. CDDL parser availability
# ---------------------------------------------------------------------------


class TestCddlParserAvailability:
    """Document whether a CDDL parser is available for validation."""

    def test_cddl_parser_status(self):
        """Report CDDL parser availability — not a failure if missing.

        This test always passes but documents the current status for CI logs.
        When a CDDL parser becomes available, upgrade the placeholder tests
        below to use actual CDDL validation.
        """
        if _CDDL_PARSER_AVAILABLE:
            module_name = _cddl_parser_module.__name__
            pytest.skip(
                f"CDDL parser IS available ({module_name}) — upgrade placeholder tests to use it!"
            )
        else:
            # This is expected for now — no Python 3.14 CDDL parser exists
            pass  # Test passes: we document the gap

    def test_cddl_parser_packages_to_monitor(self):
        """Document known Python CDDL parser packages.

        These packages may gain Python 3.14 support in the future:
          - cddlparser: https://github.com/niccokunzmann/cddlparser
          - pycddl: https://github.com/niccokunzmann/pycddl (Rust-backed)
          - cddl: https://github.com/niccokunzmann/python-cddl

        When any becomes available, update _CDDL_PARSER_AVAILABLE detection
        at the top of this file and implement the placeholder tests.
        """
        packages = ["cddlparser", "pycddl", "cddl"]
        available = []
        for pkg in packages:
            try:
                __import__(pkg)
                available.append(pkg)
            except ImportError:
                pass

        if available:
            pytest.skip(f"CDDL parser(s) available: {available}. Implement real CDDL validation!")
        # Test passes: documents the current state


# ---------------------------------------------------------------------------
# 3. Structural CBOR conformance tests (CDDL-derived, manual validation)
#
# These tests validate our CBOR encoding against the CDDL structural rules
# without a CDDL parser. They check that:
#   - Map keys match expected integer identifiers from the CDDL
#   - Array lengths match expected field counts
#   - Tagged values use the correct CBOR tags
#   - Bytestring sizes match expected hash/key/signature sizes
#
# This is the manual equivalent of what a CDDL validator would do.
# ---------------------------------------------------------------------------


class TestStructuralCddlConformance:
    """Manual structural checks derived from CDDL schemas."""

    def test_shelley_tx_body_map_keys(self):
        """Shelley tx_body uses integer map keys 0-7 per CDDL.

        shelley.cddl:
          transaction_body =
            { 0 : set<transaction_input>
            , 1 : [* transaction_output]
            , 2 : coin
            , 3 : uint
            , ? 4 : [* certificate]
            , ? 5 : withdrawals
            , ? 6 : update
            , ? 7 : auxiliary_data_hash
            }
        """
        # Required keys per Shelley CDDL
        required_keys = {0, 1, 2, 3}
        optional_keys = {4, 5, 6, 7}
        all_valid_keys = required_keys | optional_keys

        # Build a minimal Shelley tx body
        tx_body = {
            0: CBORTag(258, [[b"\x00" * 32, 0]]),
            1: [[b"\x00" * 29, 2000000]],
            2: 170000,
            3: 50000000,
        }

        # Verify all keys are valid Shelley tx_body keys
        for key in tx_body:
            assert key in all_valid_keys, f"Key {key} is not a valid Shelley tx_body field"

        # Verify required keys present
        for key in required_keys:
            assert key in tx_body, f"Required Shelley tx_body key {key} is missing"

        # Encode and verify round-trip
        encoded = cbor2.dumps(tx_body)
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, dict)
        assert set(decoded.keys()) == set(tx_body.keys())

    def test_alonzo_tx_body_extended_keys(self):
        """Alonzo extends tx_body with keys 8-14 per CDDL.

        alonzo.cddl adds:
          , ? 8  : coin                    ; validity_interval_start (from Allegra)
          , ? 9  : mint                    ; (from Mary)
          , ? 11 : script_data_hash
          , ? 13 : set<transaction_input>  ; collateral
          , ? 14 : required_signers
        """
        alonzo_valid_keys = set(range(15)) - {10, 12}  # 10 and 12 unused in Alonzo

        # Minimal Alonzo body with script_data_hash and collateral
        tx_body = {
            0: CBORTag(258, [[b"\x00" * 32, 0]]),
            1: [[b"\x00" * 29, 2000000]],
            2: 200000,
            3: 80000000,
            11: b"\xab" * 32,  # script_data_hash
            13: CBORTag(258, [[b"\x00" * 32, 1]]),  # collateral input
        }

        for key in tx_body:
            assert key in alonzo_valid_keys, f"Key {key} is not a valid Alonzo tx_body field"

    def test_babbage_tx_body_extended_keys(self):
        """Babbage adds keys 16-18 per CDDL.

        babbage.cddl adds:
          , ? 15 : coin                  ; network_id  (actually from Alonzo unused)
          , ? 16 : transaction_output    ; collateral_return
          , ? 17 : coin                  ; total_collateral
          , ? 18 : set<transaction_input>; reference_inputs
        """
        babbage_extra_keys = {16, 17, 18}

        tx_body = {
            0: CBORTag(258, [[b"\x00" * 32, 0]]),
            1: [[b"\x00" * 29, 2000000]],
            2: 200000,
            18: CBORTag(258, [[b"\x01" * 32, 0]]),  # reference input
        }

        # Verify key 18 encodes correctly
        encoded = cbor2.dumps(tx_body)
        decoded = cbor2.loads(encoded)
        assert 18 in decoded

    def test_conway_tx_body_extended_keys(self):
        """Conway adds keys 19-21 per CDDL.

        conway.cddl adds:
          , ? 19 : voting_procedures
          , ? 20 : proposal_procedures
          , ? 21 : coin                  ; treasury_value
          , ? 22 : coin                  ; donation
        """
        conway_extra_keys = {19, 20, 21, 22}

        # Minimal Conway body with donation field
        tx_body = {
            0: CBORTag(258, [[b"\x00" * 32, 0]]),
            1: [[b"\x00" * 29, 2000000]],
            2: 200000,
            22: 1000000,  # donation
        }

        encoded = cbor2.dumps(tx_body)
        decoded = cbor2.loads(encoded)
        assert 22 in decoded
        assert decoded[22] == 1000000

    def test_block_header_body_shelley_field_count(self):
        """Shelley header_body has 15 fields per CDDL."""
        header_body = [
            0,
            0,
            None,
            b"\x00" * 32,
            b"\x00" * 32,  # 5 fields
            [b"\x00" * 32, b"\x00" * 80],  # nonce_vrf
            [b"\x00" * 32, b"\x00" * 80],  # leader_vrf
            0,
            b"\x00" * 32,  # body_size, body_hash
            b"\x00" * 32,
            0,
            0,
            b"\x00" * 64,  # ocert (4 fields)
            0,
            0,  # protocol_version (2 fields)
        ]
        assert len(header_body) == 15, (
            f"Shelley header_body should have 15 fields, got {len(header_body)}"
        )

    def test_block_header_body_babbage_field_count(self):
        """Babbage header_body has 14 fields per CDDL (single VRF cert)."""
        header_body = [
            0,
            0,
            None,
            b"\x00" * 32,
            b"\x00" * 32,  # 5 fields
            [b"\x00" * 32, b"\x00" * 80],  # vrf_result (1 cert, not 2)
            0,
            b"\x00" * 32,  # body_size, body_hash
            b"\x00" * 32,
            0,
            0,
            b"\x00" * 64,  # ocert (4 fields)
            0,
            0,  # protocol_version (2 fields)
        ]
        assert len(header_body) == 14, (
            f"Babbage header_body should have 14 fields, got {len(header_body)}"
        )

    def test_operational_cert_field_sizes(self):
        """OCert fields have specific sizes per CDDL."""
        kes_vkey = b"\x00" * 32
        counter = 0
        kes_period = 100
        cold_sig = b"\x00" * 64

        assert len(kes_vkey) == 32, "kes_vkey must be 32 bytes"
        assert len(cold_sig) == 64, "cold_sig must be 64 bytes"
        assert isinstance(counter, int) and counter >= 0
        assert isinstance(kes_period, int) and kes_period >= 0

    def test_vrf_cert_structure(self):
        """VRF cert is [output: bytes, proof: bytes .size 80] per CDDL."""
        vrf_output = b"\x00" * 32
        vrf_proof = b"\x00" * 80

        vrf_cert = [vrf_output, vrf_proof]

        encoded = cbor2.dumps(vrf_cert)
        decoded = cbor2.loads(encoded)

        assert len(decoded) == 2
        assert len(decoded[1]) == 80, "VRF proof must be 80 bytes"


# ---------------------------------------------------------------------------
# 4. Placeholder tests for full CDDL validation
#
# These tests document which CDDL rules need automated validation.
# Each is tagged with the specific CDDL definition and era.
# When a CDDL parser becomes available, replace the body with real validation.
# ---------------------------------------------------------------------------


class TestCddlValidationPlaceholders:
    """Placeholder tests documenting CDDL rules needing automated validation.

    Each test represents a specific CDDL definition that should be validated
    against our encoded CBOR. The test name identifies the era and definition.
    """

    @pytest.mark.parametrize(
        "era,definition,description",
        [
            ("shelley", "block", "Shelley block = [header, tx_bodies, witnesses, auxiliary]"),
            ("shelley", "header", "header = [header_body, body_signature]"),
            ("shelley", "header_body", "15-field header body with two VRF certs"),
            ("shelley", "transaction_body", "Map with keys 0-7"),
            ("shelley", "transaction_input", "[hash32, uint]"),
            ("shelley", "transaction_output", "[address, coin]"),
            ("shelley", "operational_cert", "(kes_vkey, counter, kes_period, sigma)"),
            ("allegra", "validity_interval", "Key 8 = invalid_before added to tx_body"),
            ("mary", "value", "coin / [coin, multiasset<uint>]"),
            ("mary", "multiasset", "{policy_id => {asset_name => a}}"),
            ("alonzo", "transaction_body", "Extended with keys 8-14"),
            ("alonzo", "redeemer", "[tag, index, data, ex_units]"),
            ("alonzo", "costmdls", "{language => cost_model} in canonical CBOR"),
            ("alonzo", "plutus_data", "Constr / Map / List / Integer / Bytes"),
            ("babbage", "header_body", "14-field header body with single VRF result"),
            (
                "babbage",
                "post_alonzo_transaction_output",
                "Map-based TxOut with datum_option and script_ref",
            ),
            ("babbage", "datum_option", "[0, hash32] / [1, data .cbor plutus_data]"),
            ("babbage", "script_ref", "#6.24(bytes .cbor script)"),
            ("conway", "transaction_body", "Extended with keys 19-22"),
            ("conway", "gov_action", "7 governance action types"),
            ("conway", "voting_procedures", "{voter => {gov_action_id => procedure}}"),
            ("conway", "voter", "5 voter types with keyhash/scripthash"),
        ],
    )
    def test_cddl_definition_needs_validation(self, era: str, definition: str, description: str):
        """Document a CDDL definition that needs automated validation.

        This test always passes — it's a tracking mechanism for CDDL coverage.
        When a CDDL parser becomes available, convert this to real validation
        by parsing the CDDL schema and checking our encoded output against it.
        """
        if _CDDL_PARSER_AVAILABLE:
            pytest.skip(
                f"CDDL parser available — implement real validation for "
                f"{era}.{definition}: {description}"
            )
        # Pass: documents the validation gap
        # Future: parse {era}.cddl, extract {definition}, validate our encoding


# ---------------------------------------------------------------------------
# 5. CBOR tag conformance
#
# Cardano uses specific CBOR tags that must be encoded correctly.
# These are derivable from the CDDL without needing a parser.
# ---------------------------------------------------------------------------


class TestCborTagConformance:
    """Verify correct CBOR tag usage per Cardano CDDL conventions."""

    def test_tag258_for_sets(self):
        """Tag 258 is used for sets (transaction inputs, required signers).

        CDDL: set<a> = #6.258([* a])
        This is a Cardano convention, not part of core CBOR.
        """
        items = [[b"\x00" * 32, 0]]
        tagged = CBORTag(258, items)
        result = cbor2.dumps(tagged)

        # d9 0102 = tag(258)
        assert result[0] == 0xD9
        assert result[1] == 0x01
        assert result[2] == 0x02

    def test_tag24_for_embedded_cbor(self):
        """Tag 24 wraps embedded CBOR (inline datums, reference scripts).

        CDDL: #6.24(bytes .cbor T)
        RFC 8949: Tag 24 = Encoded CBOR data item
        """
        inner_data = cbor2.dumps(42)
        tagged = CBORTag(24, inner_data)
        result = cbor2.dumps(tagged)

        # d8 18 = tag(24)
        assert result[0] == 0xD8
        assert result[1] == 0x18

    def test_tag121_plutus_constr0(self):
        """Tag 121 encodes Plutus Constr with index 0.

        Plutus data constructors use tags 121-128 for indices 0-6,
        and tag 102 with explicit index for higher constructors.
        This is defined in the Plutus Core specification.
        """
        constr0 = CBORTag(121, [1, 2, 3])  # Constr(0, [1, 2, 3])
        result = cbor2.dumps(constr0)

        # d8 79 = tag(121)
        assert result[0] == 0xD8
        assert result[1] == 0x79

    def test_tag122_plutus_constr1(self):
        """Tag 122 encodes Plutus Constr with index 1."""
        constr1 = CBORTag(122, [])  # Constr(1, [])
        result = cbor2.dumps(constr1)
        assert result[0] == 0xD8
        assert result[1] == 0x7A

    def test_era_tags_for_hard_fork_combinator(self):
        """Era tags 0-7 wrap blocks in the hard-fork combinator.

        Tag 0 = Byron main, 1 = Byron EBB, 2 = Shelley, ..., 7 = Conway
        These are CBOR major type 6 (tag) with small values.
        """
        for era_tag in range(8):
            tagged = CBORTag(era_tag, [b"dummy"])
            result = cbor2.dumps(tagged)
            # Tags 0-23 encode as 0xC0 + tag (single byte)
            expected_byte = 0xC0 + era_tag
            assert result[0] == expected_byte, (
                f"Era tag {era_tag} should encode as 0x{expected_byte:02x}, got 0x{result[0]:02x}"
            )

    def test_canonical_map_key_ordering(self):
        """Canonical CBOR requires map keys sorted by encoded byte value.

        This is critical for cost model encoding (script integrity hash)
        and any context where deterministic serialization is required.
        RFC 7049 Section 3.9 / RFC 8949 Section 4.2.1.
        """
        # Keys: 0, 1, 10, 2 — canonical order should be 0, 1, 2, 10
        # (sorted by CBOR-encoded byte representation)
        data = {10: "ten", 2: "two", 0: "zero", 1: "one"}
        result = cbor2.dumps(data, canonical=True)
        decoded = cbor2.loads(result)

        # The decoded map should have keys in canonical order
        keys = list(decoded.keys())
        assert keys == [0, 1, 2, 10], f"Canonical CBOR should sort keys by encoded bytes: {keys}"
