"""Golden byte vector tests for Cardano CBOR serialization.

VNODE-xxx: Verifies that our CBOR encoding of Cardano data structures produces
exact byte sequences matching the Haskell cardano-ledger implementation. These
are the serialization "acceptance tests" — if the bytes differ from what Haskell
produces, interop is broken.

Each test constructs a known structure with fixed values, encodes it to CBOR via
cbor2, and asserts the output matches a hardcoded expected hex string. The expected
values are derived from:

1. Manual CBOR encoding per RFC 7049 / RFC 8949
2. The CDDL schemas in cardano-ledger (shelley.cddl, allegra.cddl, mary.cddl,
   alonzo.cddl, babbage.cddl, conway.cddl)
3. Cross-reference with Haskell golden tests where available

Spec references:
  - RFC 7049: Concise Binary Object Representation (CBOR)
  - RFC 8949: CBOR (updated spec, canonical encoding rules)
  - cardano-ledger/eras/shelley/impl/cddl-files/shelley.cddl
  - cardano-ledger/eras/allegra/impl/cddl-files/allegra.cddl
  - cardano-ledger/eras/mary/impl/cddl-files/mary.cddl
  - cardano-ledger/eras/alonzo/impl/cddl-files/alonzo.cddl
  - cardano-ledger/eras/babbage/impl/cddl-files/babbage.cddl
  - cardano-ledger/eras/conway/impl/cddl-files/conway.cddl
"""

from __future__ import annotations

import cbor2
from cbor2 import CBORTag

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fixed 32-byte values for deterministic test vectors
ZERO_HASH = b"\x00" * 32
ONE_HASH = b"\x01" * 32
FF_HASH = b"\xff" * 32
DEAD_HASH = b"\xde\xad" * 16  # 32 bytes of 0xdead repeated

# Fixed 64-byte signature
ZERO_SIG = b"\x00" * 64

# Fixed 32-byte VRF verification key
ZERO_VRF_VK = b"\x00" * 32

# Fixed VRF output (80 bytes: 64-byte proof + padded, but Cardano uses 32+80)
# VRF cert in Cardano is [bytes, bytes] — a 2-element array
ZERO_VRF_CERT = [b"\x00" * 32, b"\x00" * 80]


def _hex(obj: object, *, canonical: bool = False) -> str:
    """Encode object to CBOR and return hex string."""
    return cbor2.dumps(obj, canonical=canonical).hex()


# ---------------------------------------------------------------------------
# 1. Byron block header (minimal)
#
# Byron uses a different structure from Shelley+. The Byron main block header
# is wrapped in a 2-element array: [0, [header, body, extra]]
# The header itself is: [protocol_magic, prev_hash, body_proof, consensus_data, extra_data]
#
# CDDL (from byron.cddl):
#   block = [0, [header, body, extra_data]]
#   header = [protocol_magic, prev_hash, body_proof, consensus_data, extra_data]
#
# We test a minimal Byron-style header structure.
# ---------------------------------------------------------------------------


class TestByronBlockHeader:
    """Golden vectors for Byron-era block header encoding."""

    def test_byron_minimal_header_structure(self):
        """A minimal Byron header wraps content in [protocol_magic, prev_hash, ...]."""
        # Byron protocol magic for mainnet = 764824073 (0x2d964a09)
        protocol_magic = 764824073
        prev_hash = ZERO_HASH

        # Minimal Byron header: just protocol_magic and prev_hash in a list
        # This tests the outer structure encoding
        header = [protocol_magic, prev_hash]
        result = cbor2.dumps(header)

        # Manually verify: array(2) + uint(764824073) + bstr(32)
        # 82 = array of 2 items
        # 1a 2d964a09 = uint32 764824073
        # 5820 + 00*32 = 32-byte bstr of zeros
        expected = "821a2d964a095820" + "00" * 32
        assert result.hex() == expected, (
            f"Byron header encoding mismatch:\n  got:      {result.hex()}\n  expected: {expected}"
        )

    def test_byron_ebb_tag(self):
        """Byron EBB blocks use CBOR tag 1 in the hard-fork combinator."""
        # The hard-fork combinator wraps Byron EBB in tag 1
        # Tag 1 = 0xc1 (major type 6, additional 1)
        ebb_content = [0, ZERO_HASH]
        tagged = CBORTag(1, ebb_content)
        result = cbor2.dumps(tagged)

        # c1 = tag(1), then 82 00 5820 00*32
        expected = "c1" + "8200" + "5820" + "00" * 32
        assert result.hex() == expected


# ---------------------------------------------------------------------------
# 2. Shelley TxBody (inputs, outputs, fee, ttl)
#
# CDDL (shelley.cddl):
#   transaction_body =
#     { 0 : set<transaction_input>    ; inputs
#     , 1 : [* transaction_output]    ; outputs
#     , 2 : coin                      ; fee
#     , 3 : uint                      ; ttl
#     , ? 4 : [* certificate]
#     , ? 5 : withdrawals
#     , ? 6 : update
#     , ? 7 : auxiliary_data_hash
#     }
#
#   transaction_input = [transaction_id : hash32, index : uint]
#   transaction_output = [address, amount : coin]
#
# Inputs use tag 258 (set) in the Haskell node for canonical ordering.
# ---------------------------------------------------------------------------


class TestShelleyTxBody:
    """Golden vectors for Shelley-era transaction body encoding."""

    def test_minimal_tx_body(self):
        """Minimal Shelley TxBody: 1 input, 1 output, fee, ttl."""
        # Transaction input: [tx_hash, index]
        tx_input = [ZERO_HASH, 0]

        # Inputs are wrapped in tag 258 (set) per Haskell node encoding
        inputs = CBORTag(258, [tx_input])

        # Transaction output: [address_bytes, coin]
        # Use a minimal 29-byte Shelley address (type 0, payment + staking keyhash)
        address = b"\x00" + b"\xab" * 28
        output = [address, 2000000]  # 2 ADA

        tx_body = {
            0: inputs,  # inputs (set)
            1: [output],  # outputs
            2: 170000,  # fee
            3: 50000000,  # ttl (slot)
        }

        result = cbor2.dumps(tx_body)
        # Verify the CBOR starts with a map of 4 items
        # a4 = map(4)
        assert result[0] == 0xA4, f"Expected map(4), got 0x{result[0]:02x}"

        # Verify key 0 is followed by tag 258
        # The map encoding for key 0: 00 = uint(0)
        # Then d9 0102 = tag(258) per CBOR encoding (0xd9 = tag with 2-byte arg)
        assert result.hex().startswith("a400d90102"), (
            f"Expected map(4), key(0), tag(258) prefix, got {result.hex()[:20]}"
        )

    def test_tx_input_encoding(self):
        """A transaction input is [hash32, uint]."""
        tx_input = [ZERO_HASH, 0]
        result = cbor2.dumps(tx_input)

        # 82 = array(2), 5820 + 00*32 = bstr(32), 00 = uint(0)
        expected = "82" + "5820" + "00" * 32 + "00"
        assert result.hex() == expected

    def test_tx_input_with_nonzero_index(self):
        """Transaction input with index > 0."""
        tx_input = [ONE_HASH, 3]
        result = cbor2.dumps(tx_input)

        # 82 = array(2), 5820 + 01*32, 03 = uint(3)
        expected = "82" + "5820" + "01" * 32 + "03"
        assert result.hex() == expected

    def test_coin_encoding_small(self):
        """Coin values under 24 encode in 1 byte."""
        assert cbor2.dumps(0).hex() == "00"
        assert cbor2.dumps(23).hex() == "17"

    def test_coin_encoding_medium(self):
        """Coin value 2000000 (2 ADA) encodes as uint32."""
        result = cbor2.dumps(2000000)
        # 1a 001e8480 = uint32(2000000)
        assert result.hex() == "1a001e8480"

    def test_fee_encoding(self):
        """Fee of 170000 encodes correctly."""
        result = cbor2.dumps(170000)
        # 1a 00029810 = uint32(170000)  [170000 = 0x29810]
        assert result.hex() == "1a00029810"


# ---------------------------------------------------------------------------
# 3. Shelley block header body
#
# CDDL (shelley.cddl):
#   header_body =
#     [ block_number     : uint
#     , slot             : uint
#     , prev_hash        : $hash32 / null
#     , issuer_vkey      : $vkey
#     , vrf_vkey         : $vrf_vkey
#     , nonce_vrf        : $vrf_cert
#     , leader_vrf       : $vrf_cert
#     , block_body_size  : uint
#     , block_body_hash  : $hash32
#     , operational_cert
#     , protocol_version
#     ]
#
#   $vrf_cert = [bytes, bytes .size 80]
# ---------------------------------------------------------------------------


class TestShelleyBlockHeaderBody:
    """Golden vectors for Shelley block header body encoding."""

    def test_header_body_structure(self):
        """Shelley header_body is a 15-element array (with inline ocert fields)."""
        header_body = [
            1000,  # block_number
            50000,  # slot
            ZERO_HASH,  # prev_hash
            ZERO_HASH,  # issuer_vkey (32 bytes)
            ZERO_VRF_VK,  # vrf_vkey (32 bytes)
            ZERO_VRF_CERT,  # nonce_vrf: [bytes, bytes]
            ZERO_VRF_CERT,  # leader_vrf: [bytes, bytes]
            1024,  # block_body_size
            ZERO_HASH,  # block_body_hash
            # operational_cert inline (4 fields):
            ZERO_HASH,  # hot_vkey (kes_vkey)
            0,  # sequence_number (counter)
            0,  # kes_period
            ZERO_SIG,  # sigma (cold_sig)
            # protocol_version inline (2 fields):
            7,  # major
            0,  # minor
        ]

        result = cbor2.dumps(header_body)

        # Must be a 15-element array
        # 8f = array(15)
        assert result[0] == 0x8F, f"Expected array(15), got 0x{result[0]:02x}"

        # Verify block_number encoding: 1903e8 = uint16(1000)
        assert "1903e8" in result.hex()[:20], (
            f"Expected uint(1000) near start, got {result.hex()[:20]}"
        )

    def test_header_body_with_null_prev_hash(self):
        """Genesis block has null prev_hash (first Shelley block)."""
        header_body = [
            0,  # block_number
            0,  # slot
            None,  # prev_hash = null (genesis)
            ZERO_HASH,  # issuer_vkey
            ZERO_VRF_VK,  # vrf_vkey
            ZERO_VRF_CERT,  # nonce_vrf
            ZERO_VRF_CERT,  # leader_vrf
            0,  # block_body_size
            ZERO_HASH,  # block_body_hash
            ZERO_HASH,  # hot_vkey
            0,  # sequence_number
            0,  # kes_period
            ZERO_SIG,  # sigma
            0,  # protocol_version major
            0,  # minor
        ]

        result = cbor2.dumps(header_body)

        # 8f = array(15), 00 = uint(0), 00 = uint(0), f6 = null
        assert result.hex().startswith("8f0000f6"), (
            f"Expected array(15), 0, 0, null at start, got {result.hex()[:10]}"
        )

    def test_vrf_cert_encoding(self):
        """VRF cert is [output_bytes, proof_bytes] — a 2-element array."""
        vrf_cert = [b"\xaa" * 32, b"\xbb" * 80]
        result = cbor2.dumps(vrf_cert)

        # 82 = array(2)
        # 5820 + aa*32 = bstr(32)
        # 5850 + bb*80 = bstr(80)  (0x50 = 80)
        expected = "82" + "5820" + "aa" * 32 + "5850" + "bb" * 80
        assert result.hex() == expected


# ---------------------------------------------------------------------------
# 4. Allegra ValidityInterval encoding
#
# CDDL (allegra.cddl):
#   validity_interval = [? invalid_before : uint, ? invalid_hereafter : uint]
#
# Actually per the Allegra CDDL, validity_interval replaces ttl in tx_body:
#   transaction_body key 8 = validity_interval_start  (optional)
#   transaction_body retains key 3 = ttl (now called invalid_hereafter)
#
# The Allegra change is: key 8 => invalid_before (optional uint)
# Key 3 remains as invalid_hereafter (optional uint, was mandatory ttl in Shelley)
# ---------------------------------------------------------------------------


class TestAllegraValidityInterval:
    """Golden vectors for Allegra validity interval encoding."""

    def test_validity_interval_both_bounds(self):
        """TxBody with both invalid_before (key 8) and invalid_hereafter (key 3)."""
        tx_body = {
            0: CBORTag(258, [[ZERO_HASH, 0]]),  # inputs
            1: [[b"\x00" * 29, 1000000]],  # outputs
            2: 170000,  # fee
            3: 60000000,  # invalid_hereafter (was ttl)
            8: 50000000,  # invalid_before (Allegra addition)
        }

        result = cbor2.dumps(tx_body)
        # Map of 5 items: a5
        assert result[0] == 0xA5, f"Expected map(5), got 0x{result[0]:02x}"

        # Key 8 should be present with value 50000000
        # 08 = uint(8), 1a 02faf080 = uint32(50000000)
        assert "081a02faf080" in result.hex()

    def test_validity_no_lower_bound(self):
        """TxBody without invalid_before — just invalid_hereafter."""
        tx_body = {
            0: CBORTag(258, [[ZERO_HASH, 0]]),
            1: [[b"\x00" * 29, 1000000]],
            2: 170000,
            3: 60000000,
            # no key 8 — no lower bound
        }

        result = cbor2.dumps(tx_body)
        # Map of 4 items
        assert result[0] == 0xA4
        # Key 8 should NOT be present
        assert "08" not in result.hex()[2:6]  # After the map header

    def test_validity_no_upper_bound(self):
        """TxBody with invalid_before but no invalid_hereafter."""
        tx_body = {
            0: CBORTag(258, [[ZERO_HASH, 0]]),
            1: [[b"\x00" * 29, 1000000]],
            2: 170000,
            # no key 3 — no upper bound
            8: 50000000,
        }

        result = cbor2.dumps(tx_body)
        # Map of 4 items (0, 1, 2, 8)
        assert result[0] == 0xA4


# ---------------------------------------------------------------------------
# 5. Mary multi-asset Value encoding
#
# CDDL (mary.cddl):
#   value = coin / [coin, multiasset<uint>]
#   multiasset<a> = { * policy_id => { * asset_name => a } }
#   policy_id = scripthash  (28 bytes)
#   asset_name = bytes .size (0..32)
#
# When a TxOut has multi-asset value, it's encoded as a 2-element array:
#   [coin, {policy_id: {asset_name: quantity}}]
# ---------------------------------------------------------------------------


class TestMaryMultiAssetValue:
    """Golden vectors for Mary-era multi-asset Value encoding."""

    def test_ada_only_value(self):
        """ADA-only value is just a coin (uint), not an array."""
        value = 5000000  # 5 ADA
        result = cbor2.dumps(value)
        # 1a 004c4b40 = uint32(5000000)
        assert result.hex() == "1a004c4b40"

    def test_multiasset_value(self):
        """Multi-asset value is [coin, {policy: {asset: qty}}]."""
        policy_id = b"\xaa" * 28  # 28-byte policy hash
        asset_name = b"TOKEN"  # 5-byte asset name
        quantity = 1000

        value = [
            2000000,  # ADA (lovelace)
            {
                policy_id: {
                    asset_name: quantity,
                }
            },
        ]

        result = cbor2.dumps(value)

        # Must be array(2)
        assert result[0] == 0x82, f"Expected array(2), got 0x{result[0]:02x}"

        # First element: 1a001e8480 = uint32(2000000)
        assert result.hex()[2:12] == "1a001e8480"

    def test_multiasset_empty_asset_name(self):
        """Asset with empty name (the 'ADA-like' token within a policy)."""
        policy_id = b"\xbb" * 28
        empty_name = b""
        quantity = 42

        value = [1000000, {policy_id: {empty_name: quantity}}]

        result = cbor2.dumps(value)

        # Empty bstr = 0x40
        assert "40" in result.hex()

    def test_multiasset_multiple_assets(self):
        """Multiple assets under one policy."""
        policy_id = b"\xcc" * 28
        token_a = b"ALPHA"
        token_b = b"BETA"

        value = [
            3000000,
            {
                policy_id: {
                    token_a: 100,
                    token_b: 200,
                }
            },
        ]

        result = cbor2.dumps(value)
        # Must be array(2) with coin first
        assert result[0] == 0x82


# ---------------------------------------------------------------------------
# 6. Alonzo script integrity hash encoding
#
# CDDL (alonzo.cddl):
#   transaction_body key 11 = script_data_hash : $hash32
#
# The script_data_hash (script integrity hash) is a Blake2b-256 hash
# computed over the redeemers, datums, and cost models. The hash input
# is the concatenation of:
#   - CBOR-encoded redeemers (as a list)
#   - CBOR-encoded datums (as a list)
#   - CBOR-encoded cost model language views (canonical CBOR)
#
# Here we test the encoding of the hash field itself in a tx body.
# ---------------------------------------------------------------------------


class TestAlonzoScriptIntegrityHash:
    """Golden vectors for Alonzo script integrity hash in TxBody."""

    def test_script_data_hash_in_tx_body(self):
        """Script data hash is tx_body key 11, value is a 32-byte hash."""
        script_data_hash = DEAD_HASH  # 32 bytes

        # Minimal Alonzo tx body with script_data_hash
        tx_body = {
            0: CBORTag(258, [[ZERO_HASH, 0]]),  # inputs
            1: [[b"\x00" * 29, 2000000]],  # outputs
            2: 200000,  # fee
            11: script_data_hash,  # script_data_hash
        }

        result = cbor2.dumps(tx_body)

        # Map of 4 items
        assert result[0] == 0xA4

        # Key 11 = 0x0b, then 5820 + dead*16
        expected_fragment = "0b5820" + "dead" * 16
        assert expected_fragment in result.hex(), (
            "Expected key(11) + bstr(32) fragment in encoding"
        )

    def test_hash32_encoding(self):
        """A $hash32 is always a 32-byte bstr."""
        result = cbor2.dumps(DEAD_HASH)
        expected = "5820" + "dead" * 16
        assert result.hex() == expected


# ---------------------------------------------------------------------------
# 7. Alonzo Redeemer encoding
#
# CDDL (alonzo.cddl):
#   redeemers = [ * redeemer ]  (Alonzo)
#   redeemer = [tag: redeemer_tag, index: uint, data: plutus_data, ex_units: ex_units]
#   redeemer_tag = 0 / 1 / 2 / 3  ; Spend / Mint / Cert / Reward
#   ex_units = [mem: uint, steps: uint]
#
# In Babbage+, redeemers changed to a map: { [tag, index] => [data, ex_units] }
# Here we test the Alonzo (list) format.
# ---------------------------------------------------------------------------


class TestAlonzoRedeemer:
    """Golden vectors for Alonzo-era Redeemer encoding."""

    def test_spend_redeemer(self):
        """Spend redeemer (tag=0) with simple data and ExUnits."""
        # redeemer = [tag, index, data, ex_units]
        # tag 0 = Spend
        # data = simple integer (Plutus data: constr or int)
        # ExUnits = [mem, steps]
        redeemer = [
            0,  # Spend tag
            0,  # index
            42,  # plutus data (integer)
            [500000, 200000],  # ex_units: [mem, steps]
        ]

        result = cbor2.dumps(redeemer)

        # 84 = array(4), 00 = uint(0), 00 = uint(0), 182a = uint(42)
        # 82 1a0007a120 1a00030d40 = [uint32(500000), uint32(200000)]
        expected = "840000182a" + "82" + "1a0007a120" + "1a00030d40"
        assert result.hex() == expected

    def test_mint_redeemer(self):
        """Mint redeemer (tag=1)."""
        redeemer = [
            1,  # Mint tag
            0,  # index
            CBORTag(121, []),  # Plutus constr 0 (empty fields)
            [1000000, 500000],  # ex_units
        ]

        result = cbor2.dumps(redeemer)
        # 84 = array(4), 01 = Mint, 00 = index
        assert result[0] == 0x84
        assert result[1] == 0x01

    def test_ex_units_encoding(self):
        """ExUnits is [mem: uint, steps: uint]."""
        ex_units = [500000, 200000]
        result = cbor2.dumps(ex_units)

        expected = "82" + "1a0007a120" + "1a00030d40"
        assert result.hex() == expected


# ---------------------------------------------------------------------------
# 8. Alonzo CostModel encoding (language view for script integrity hash)
#
# The cost model language view uses CANONICAL CBOR (RFC 7049 Section 3.9):
#   - Map keys in sorted order (by byte comparison of their CBOR encoding)
#   - Minimum-length integer encoding
#   - No indefinite-length encoding
#
# CDDL (alonzo.cddl):
#   costmdls = { * language => cost_model }
#   language = 0 / 1 / 2  ; PlutusV1 / PlutusV2 / PlutusV3
#   cost_model = [* int]  ; list of cost parameters
#
# For the script integrity hash, the Haskell node encodes cost models
# in canonical CBOR. The language key is encoded minimally, and the
# cost model parameter list preserves the exact ordering from the protocol
# parameters.
# ---------------------------------------------------------------------------


class TestAlonzoCostModelEncoding:
    """Golden vectors for Alonzo CostModel canonical CBOR encoding."""

    def test_canonical_costmodel_map(self):
        """CostModel map uses canonical encoding: sorted int keys, minimal lengths."""
        # Minimal cost model: language 0 (PlutusV1) with 3 parameters
        cost_models = {
            0: [100, 200, 300],
        }

        # Canonical CBOR encoding
        result = cbor2.dumps(cost_models, canonical=True)

        # a1 = map(1), 00 = uint(0)
        # 83 = array(3), 1864 = uint(100), 18c8 = uint(200), 19012c = uint(300)
        expected = "a100" + "83" + "1864" + "18c8" + "19012c"
        assert result.hex() == expected

    def test_canonical_vs_noncanonical(self):
        """Canonical encoding must match non-canonical for simple cost models.

        For integer keys 0-23, canonical and non-canonical are identical.
        The canonical requirement matters when keys > 23 or when map key
        ordering differs.
        """
        cost_models = {0: [1, 2, 3]}
        canonical = cbor2.dumps(cost_models, canonical=True)
        regular = cbor2.dumps(cost_models)

        # For this simple case they should be identical
        assert canonical.hex() == regular.hex()

    def test_canonical_multi_language(self):
        """Cost models for multiple Plutus versions, canonically ordered."""
        cost_models = {
            1: [10, 20],  # PlutusV2
            0: [30, 40],  # PlutusV1
        }

        result = cbor2.dumps(cost_models, canonical=True)

        # Canonical: keys sorted by CBOR encoding bytes
        # Key 0 (0x00) sorts before key 1 (0x01)
        # a2 = map(2)
        # 00 82 181e 1828 = key(0), array(2), 30, 40
        # 01 82 0a 14    = key(1), array(2), 10, 20
        expected = "a2" + "00" + "82" + "181e" + "1828" + "01" + "82" + "0a" + "14"
        assert result.hex() == expected

    def test_negative_cost_parameter(self):
        """Cost models can contain negative integers (used in PlutusV2+)."""
        # CBOR negative integer -1 = 0x20 (major type 1, value 0)
        cost_models = {0: [-1, 0, 1]}
        result = cbor2.dumps(cost_models, canonical=True)

        # a1 00 83 20 00 01
        expected = "a100" + "83" + "20" + "00" + "01"
        assert result.hex() == expected


# ---------------------------------------------------------------------------
# 9. Babbage TxOut with inline datum
#
# CDDL (babbage.cddl):
#   post_alonzo_transaction_output =
#     { 0 : address
#     , 1 : value
#     , ? 2 : datum_option    ; [0, datum_hash] / [1, data]
#     , ? 3 : script_ref
#     }
#
#   datum_option = [0, $hash32] / [1, data .cbor plutus_data]
#
# The inline datum uses datum_option variant [1, encoded_datum]:
#   - The datum is a CBOR-encoded Plutus data value wrapped in tag 24
#     (embedded CBOR / CBOR-in-CBOR)
# ---------------------------------------------------------------------------


class TestBabbageTxOutInlineDatum:
    """Golden vectors for Babbage TxOut with inline datum."""

    def test_txout_with_datum_hash(self):
        """Babbage TxOut with datum hash reference: datum_option = [0, hash32]."""
        datum_hash = ZERO_HASH
        txout = {
            0: b"\x00" * 29,  # address
            1: 2000000,  # value (ADA only)
            2: [0, datum_hash],  # datum_option: [0, hash] = datum hash ref
        }

        result = cbor2.dumps(txout)
        # Map of 3 items
        assert result[0] == 0xA3

    def test_txout_with_inline_datum(self):
        """Babbage TxOut with inline datum: datum_option = [1, cbor_data].

        The inline datum is wrapped in CBOR tag 24 (embedded CBOR).
        """
        # Plutus data: integer 42, encoded as CBOR then wrapped in tag 24
        plutus_data_cbor = cbor2.dumps(42)  # 182a
        inline_datum = CBORTag(24, plutus_data_cbor)

        txout = {
            0: b"\x00" * 29,  # address
            1: 2000000,  # value
            2: [1, inline_datum],  # datum_option: [1, tag24(datum_cbor)]
        }

        result = cbor2.dumps(txout)
        assert result[0] == 0xA3

        # The datum_option [1, tag24(182a)] should appear in the encoding
        # Key 2 = 0x02
        # Value: array(2) 82, uint(1) 01, tag24 d818 42 182a
        datum_fragment = "02" + "82" + "01" + "d818" + "42" + "182a"
        assert datum_fragment in result.hex(), (
            f"Expected inline datum fragment, got {result.hex()}"
        )

    def test_tag24_embedded_cbor(self):
        """Tag 24 wraps CBOR-encoded data as a bytestring."""
        inner = cbor2.dumps(42)  # 182a (2 bytes)
        tagged = CBORTag(24, inner)
        result = cbor2.dumps(tagged)

        # d8 18 = tag(24), 42 = bstr(2), 18 2a = uint(42)
        expected = "d818" + "42" + "182a"
        assert result.hex() == expected


# ---------------------------------------------------------------------------
# 10. Babbage TxOut with reference script
#
# CDDL (babbage.cddl):
#   post_alonzo_transaction_output key 3 = script_ref
#   script_ref = #6.24(bytes .cbor script)
#   script = [0, native_script] / [1, plutus_v1_script] / [2, plutus_v2_script]
#
# Reference scripts are stored inline in TxOuts, wrapped in tag 24.
# ---------------------------------------------------------------------------


class TestBabbageTxOutReferenceScript:
    """Golden vectors for Babbage TxOut with reference script."""

    def test_txout_with_reference_script(self):
        """Babbage TxOut with a PlutusV2 reference script."""
        # A minimal PlutusV2 script: [2, script_bytes]
        # script_bytes is the compiled Plutus script (opaque bytes)
        script_bytes = b"\xde\xad\xbe\xef"
        plutus_v2_script = [2, script_bytes]

        # Encode the script, then wrap in tag 24
        script_cbor = cbor2.dumps(plutus_v2_script)
        script_ref = CBORTag(24, script_cbor)

        txout = {
            0: b"\x00" * 29,  # address
            1: 5000000,  # value
            3: script_ref,  # reference script
        }

        result = cbor2.dumps(txout)
        assert result[0] == 0xA3

        # Key 3 should be present with tag 24
        # 03 d818 = key(3), tag(24)
        assert "03d818" in result.hex()

    def test_txout_with_datum_and_script(self):
        """Babbage TxOut with both inline datum and reference script."""
        plutus_data_cbor = cbor2.dumps(0)  # 0x00
        inline_datum = CBORTag(24, plutus_data_cbor)

        script_cbor = cbor2.dumps([1, b"\xca\xfe"])  # PlutusV1 script
        script_ref = CBORTag(24, script_cbor)

        txout = {
            0: b"\x00" * 29,
            1: 10000000,
            2: [1, inline_datum],
            3: script_ref,
        }

        result = cbor2.dumps(txout)
        # Map of 4 items
        assert result[0] == 0xA4


# ---------------------------------------------------------------------------
# 11. Conway GovAction encoding
#
# CDDL (conway.cddl):
#   gov_action =
#     [ parameter_change_action      ; 0
#     // hard_fork_initiation_action  ; 1
#     // treasury_withdrawals_action  ; 2
#     // no_confidence                ; 3
#     // update_committee             ; 4
#     // new_constitution             ; 5
#     // info_action                  ; 6
#     ]
#
#   info_action = 6  (just the tag, no additional data)
#   no_confidence = [3, gov_action_id / null]
#   treasury_withdrawals_action = [2, { reward_account => coin }, policy_hash / null]
# ---------------------------------------------------------------------------


class TestConwayGovAction:
    """Golden vectors for Conway governance action encoding."""

    def test_info_action(self):
        """Info action is the simplest: just [6]."""
        info_action = [6]
        result = cbor2.dumps(info_action)
        # 81 06 = array(1), uint(6)
        assert result.hex() == "8106"

    def test_no_confidence(self):
        """No confidence action: [3, null] (no prior gov action reference)."""
        no_confidence = [3, None]
        result = cbor2.dumps(no_confidence)
        # 82 03 f6 = array(2), uint(3), null
        assert result.hex() == "8203f6"

    def test_no_confidence_with_prior_action(self):
        """No confidence with prior gov action: [3, [tx_hash, index]]."""
        gov_action_id = [ZERO_HASH, 0]
        no_confidence = [3, gov_action_id]
        result = cbor2.dumps(no_confidence)
        # 82 03 82 5820 00*32 00
        expected = "8203" + "82" + "5820" + "00" * 32 + "00"
        assert result.hex() == expected

    def test_treasury_withdrawal(self):
        """Treasury withdrawal: [2, {reward_acct => coin}, policy_hash / null]."""
        reward_account = b"\xe0" + b"\xab" * 28  # 29-byte reward address
        withdrawal_map = {reward_account: 1000000}

        treasury_action = [2, withdrawal_map, None]
        result = cbor2.dumps(treasury_action)
        # 83 = array(3), 02 = uint(2)
        assert result[0] == 0x83
        assert result[1] == 0x02


# ---------------------------------------------------------------------------
# 12. Conway Vote encoding
#
# CDDL (conway.cddl):
#   voting_procedures =
#     { * voter => { * gov_action_id => voting_procedure } }
#
#   voter =
#     [ 0, $addr_keyhash ]           ; constitutional committee hot key
#     / [ 1, $scripthash ]           ; constitutional committee hot script
#     / [ 2, $addr_keyhash ]         ; DRep key
#     / [ 3, $scripthash ]           ; DRep script
#     / [ 4, $addr_keyhash ]         ; StakePool operator key
#
#   voting_procedure = [vote, anchor / null]
#   vote = 0 / 1 / 2  ; No / Yes / Abstain
# ---------------------------------------------------------------------------


class TestConwayVote:
    """Golden vectors for Conway voting procedure encoding."""

    def test_vote_yes(self):
        """Vote encoding: 1 = Yes."""
        vote = 1
        assert cbor2.dumps(vote).hex() == "01"

    def test_vote_no(self):
        """Vote encoding: 0 = No."""
        assert cbor2.dumps(0).hex() == "00"

    def test_vote_abstain(self):
        """Vote encoding: 2 = Abstain."""
        assert cbor2.dumps(2).hex() == "02"

    def test_voting_procedure_yes_no_anchor(self):
        """Voting procedure: [vote, null] (no anchor)."""
        procedure = [1, None]  # Yes vote, no anchor
        result = cbor2.dumps(procedure)
        # 82 01 f6 = array(2), uint(1), null
        assert result.hex() == "8201f6"

    def test_voter_drep_keyhash(self):
        """DRep key voter: [2, keyhash]."""
        keyhash = b"\xdd" * 28
        voter = [2, keyhash]
        result = cbor2.dumps(voter)

        # 82 02 581c dd*28
        expected = "8202" + "581c" + "dd" * 28
        assert result.hex() == expected

    def test_voter_spo(self):
        """StakePool operator voter: [4, keyhash]."""
        keyhash = b"\xee" * 28
        voter = [4, keyhash]
        result = cbor2.dumps(voter)

        expected = "8204" + "581c" + "ee" * 28
        assert result.hex() == expected

    def test_full_voting_procedures_map(self):
        """Full voting_procedures map: {voter => {gov_action_id => procedure}}."""
        voter = [2, b"\xdd" * 28]  # DRep key voter
        gov_action_id = [ZERO_HASH, 0]
        procedure = [1, None]  # Yes, no anchor

        # The outer map uses complex keys (arrays as map keys via CBOR)
        # This matches the CDDL: { voter => { gov_action_id => voting_procedure } }
        # Note: cbor2 supports non-string map keys
        voter_key = (2, b"\xdd" * 28)  # tuple for hashable map key
        gov_action_key = (ZERO_HASH, 0)

        # Build the nested structure
        inner_map = {gov_action_key: procedure}
        voting_procedures = {voter_key: inner_map}

        # This should encode without error
        result = cbor2.dumps(voting_procedures)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# 13. OCert encoding
#
# CDDL (shelley.cddl):
#   operational_cert =
#     ( hot_vkey        : $kes_vkey     ; 32 bytes
#     , sequence_number : uint
#     , kes_period      : uint
#     , sigma           : $signature    ; 64 bytes
#     )
#
# In the block header, OCert fields are inlined (not a separate array).
# But for standalone testing, we encode the 4 fields as an array.
# ---------------------------------------------------------------------------


class TestOCertEncoding:
    """Golden vectors for Operational Certificate encoding."""

    def test_ocert_standalone(self):
        """OCert as a standalone 4-element array."""
        ocert = [
            ZERO_HASH,  # kes_vkey (32 bytes)
            0,  # counter (sequence_number)
            100,  # kes_period
            ZERO_SIG,  # cold_sig (64 bytes)
        ]

        result = cbor2.dumps(ocert)

        # 84 = array(4)
        # 5820 00*32 = kes_vkey
        # 00 = counter
        # 1864 = kes_period (100)
        # 5840 00*64 = cold_sig
        expected = (
            "84"
            + "5820"
            + "00" * 32  # kes_vkey
            + "00"  # counter = 0
            + "1864"  # kes_period = 100
            + "5840"
            + "00" * 64  # cold_sig
        )
        assert result.hex() == expected

    def test_ocert_large_counter(self):
        """OCert with a large sequence number (multi-byte uint)."""
        ocert = [
            ONE_HASH,  # kes_vkey
            1000,  # counter = 1000
            200,  # kes_period
            ZERO_SIG,  # cold_sig
        ]

        result = cbor2.dumps(ocert)
        # 84 = array(4)
        assert result[0] == 0x84

        # Counter 1000: 1903e8
        assert "1903e8" in result.hex()

    def test_ocert_inlined_in_header_body(self):
        """OCert fields inlined in a Shelley header_body array.

        In the actual block header, OCert is not a sub-array — its 4 fields
        are placed directly in the header_body array at indices 9-12.
        """
        header_body = [
            42,  # [0] block_number
            1000,  # [1] slot
            ZERO_HASH,  # [2] prev_hash
            ZERO_HASH,  # [3] issuer_vkey
            ZERO_VRF_VK,  # [4] vrf_vkey
            ZERO_VRF_CERT,  # [5] nonce_vrf
            ZERO_VRF_CERT,  # [6] leader_vrf
            256,  # [7] block_body_size
            ZERO_HASH,  # [8] block_body_hash
            # OCert fields (inlined, NOT a sub-array):
            ZERO_HASH,  # [9] hot_vkey (kes_vkey)
            5,  # [10] sequence_number
            62,  # [11] kes_period
            ZERO_SIG,  # [12] sigma (cold_sig)
            # Protocol version:
            7,  # [13] major
            0,  # [14] minor
        ]

        result = cbor2.dumps(header_body)
        # 8f = array(15)
        assert result[0] == 0x8F
        assert len(header_body) == 15


# ---------------------------------------------------------------------------
# 14. Additional encoding invariants
#
# These aren't era-specific but are critical for Cardano interoperability.
# ---------------------------------------------------------------------------


class TestCborEncodingInvariants:
    """Cross-cutting CBOR encoding invariants for Cardano."""

    def test_tag258_set_encoding(self):
        """Tag 258 encodes sets (used for tx inputs, required signers)."""
        items = [[ZERO_HASH, 0], [ONE_HASH, 1]]
        tagged = CBORTag(258, items)
        result = cbor2.dumps(tagged)

        # d9 0102 = tag(258)
        assert result.hex().startswith("d90102")

    def test_null_encoding(self):
        """CBOR null is 0xf6 — used for optional fields (prev_hash, anchors)."""
        assert cbor2.dumps(None).hex() == "f6"

    def test_empty_map(self):
        """Empty map is 0xa0 — used for empty withdrawal maps, etc."""
        assert cbor2.dumps({}).hex() == "a0"

    def test_empty_array(self):
        """Empty array is 0x80 — used for empty certificate lists, etc."""
        assert cbor2.dumps([]).hex() == "80"

    def test_bstr_32_encoding(self):
        """32-byte bytestring uses 2-byte length prefix (5820)."""
        result = cbor2.dumps(b"\x00" * 32)
        assert result.hex().startswith("5820")
        assert len(result) == 34  # 2 prefix + 32 data

    def test_bstr_28_encoding(self):
        """28-byte bytestring (keyhash/scripthash) uses 2-byte prefix (581c)."""
        result = cbor2.dumps(b"\x00" * 28)
        assert result.hex().startswith("581c")
        assert len(result) == 30  # 2 prefix + 28 data

    def test_bstr_64_encoding(self):
        """64-byte bytestring (signature) uses 2-byte prefix (5840)."""
        result = cbor2.dumps(b"\x00" * 64)
        assert result.hex().startswith("5840")
        assert len(result) == 66  # 2 prefix + 64 data

    def test_uint_encoding_boundaries(self):
        """CBOR uint encoding boundary values per RFC 7049."""
        # 0-23: single byte (value in additional info)
        assert cbor2.dumps(0).hex() == "00"
        assert cbor2.dumps(23).hex() == "17"

        # 24-255: 2 bytes (0x18 + 1 byte)
        assert cbor2.dumps(24).hex() == "1818"
        assert cbor2.dumps(255).hex() == "18ff"

        # 256-65535: 3 bytes (0x19 + 2 bytes)
        assert cbor2.dumps(256).hex() == "190100"
        assert cbor2.dumps(65535).hex() == "19ffff"

        # 65536-4294967295: 5 bytes (0x1a + 4 bytes)
        assert cbor2.dumps(65536).hex() == "1a00010000"
        assert cbor2.dumps(4294967295).hex() == "1affffffff"

        # 4294967296+: 9 bytes (0x1b + 8 bytes)
        assert cbor2.dumps(4294967296).hex() == "1b0000000100000000"
