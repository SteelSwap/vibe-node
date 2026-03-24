"""Serialization test parity with Haskell cardano-ledger test suite.

M6.4 work item 2.2: Tests that cover Haskell-equivalent serialization scenarios
not already present in the codebase. Focuses on:

  1. All-era CBOR round-trip (encode -> decode -> verify match) for block headers
     across Byron, Shelley, Allegra, Mary, Alonzo, Babbage, Conway
  2. Era detection from raw CBOR bytes — exhaustive and edge-case coverage
  3. Transaction body field completeness per era (era-specific CDDL fields)
  4. Edge cases: empty blocks, blocks with many transactions, maximum-size fields,
     boundary integer encodings

Haskell test references:
  - cardano-ledger/eras/shelley/impl/test/Test/Cardano/Ledger/Shelley/Serialisation/
    Golden/Encoding.hs (checkEncodingCBORAnnotated for block header round-trips)
  - cardano-ledger/eras/shelley/impl/test/Test/Cardano/Ledger/Shelley/Serialisation/
    Generators.hs (genBlock, genShelleyBlock for property-based block generation)
  - cardano-ledger/byron/ledger/impl/test/Test/Cardano/Chain/Block/CBOR.hs
    (goldenHeader, goldenBody, goldenABlockSignature)
  - cardano-ledger/eras/alonzo/impl/test/.../Serialisation/ (Alonzo tx body fields)
  - cardano-ledger/eras/babbage/impl/test/.../Serialisation/ (Babbage tx body fields)
  - cardano-ledger/eras/conway/impl/test/.../Serialisation/ (Conway tx body fields)

Spec references:
  - shelley.cddl: header_body (15-field, two-VRF format)
  - babbage.cddl: header_body (14-field, single-VRF format)
  - alonzo.cddl: transaction_body (adds script_data_hash, collateral, etc.)
  - babbage.cddl: transaction_body (adds reference_inputs, collateral_return)
  - conway.cddl: transaction_body (adds voting_procedures, proposal_procedures)
"""

from __future__ import annotations

import hashlib
from typing import Any

import cbor2pure as _cbor2
import pytest

from vibe.cardano.serialization.block import (
    Era,
    ProtocolVersion,
    block_hash,
    decode_block_header,
    decode_block_header_raw,
    detect_era,
)

# These were removed from block.py in M6.1 (replaced by raw_tags=True).
# Provide local equivalents for tests that still need them.
_loads = _cbor2.loads
_dumps = _cbor2.dumps


def _strip_tag(cbor_bytes: bytes) -> tuple[int, bytes]:
    """Local helper replacing the removed block.py function."""
    decoded = _cbor2.loads(cbor_bytes, raw_tags=True)
    if isinstance(decoded, _cbor2.CBORTag):
        return decoded.tag, _cbor2.dumps(decoded.value)
    raise ValueError(f"Expected CBOR tag, got {type(decoded).__name__}")


from vibe.cardano.serialization.transaction import (
    _tx_hash,
    decode_block_body,
)

# ---------------------------------------------------------------------------
# Shared test vector constants
# ---------------------------------------------------------------------------

HASH32 = b"\xab" * 32
HASH32_ALT = b"\xba" * 32
VKEY32 = b"\xef" * 32
SIG64 = b"\xcd" * 64
VRF_CERT = [b"\x01" * 32, b"\x02" * 80]
VRF_CERT_ALT = [b"\x03" * 32, b"\x04" * 80]
ADDR_BYTES = b"\x00" + b"\x11" * 28 + b"\x22" * 28

# Era groupings
SHELLEY_FAMILY_ERAS = [Era.SHELLEY, Era.ALLEGRA, Era.MARY, Era.ALONZO]
BABBAGE_FAMILY_ERAS = [Era.BABBAGE, Era.CONWAY]
ALL_POST_BYRON_ERAS = SHELLEY_FAMILY_ERAS + BABBAGE_FAMILY_ERAS
BYRON_ERAS = [Era.BYRON_MAIN, Era.BYRON_EBB]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _make_shelley_header_body(
    *,
    block_number: int = 42,
    slot: int = 1000,
    prev_hash: bytes | None = HASH32,
    issuer_vkey: bytes = VKEY32,
    vrf_vkey: bytes = VKEY32,
    nonce_vrf: list = VRF_CERT,
    leader_vrf: list = VRF_CERT,
    body_size: int = 512,
    body_hash: bytes = HASH32,
    hot_vkey: bytes = VKEY32,
    seq_number: int = 7,
    kes_period: int = 100,
    sigma: bytes = SIG64,
    proto_major: int = 3,
    proto_minor: int = 0,
) -> list:
    """Construct a Shelley-era header_body (15 fields, two-VRF format)."""
    return [
        block_number,
        slot,
        prev_hash,
        issuer_vkey,
        vrf_vkey,
        nonce_vrf,
        leader_vrf,
        body_size,
        body_hash,
        hot_vkey,
        seq_number,
        kes_period,
        sigma,
        proto_major,
        proto_minor,
    ]


def _make_babbage_header_body(
    *,
    block_number: int = 99,
    slot: int = 5000,
    prev_hash: bytes | None = HASH32,
    issuer_vkey: bytes = VKEY32,
    vrf_vkey: bytes = VKEY32,
    vrf_result: list = VRF_CERT,
    body_size: int = 1024,
    body_hash: bytes = HASH32,
    hot_vkey: bytes = VKEY32,
    seq_number: int = 12,
    kes_period: int = 200,
    sigma: bytes = SIG64,
    proto_major: int = 7,
    proto_minor: int = 0,
) -> list:
    """Construct a Babbage-era header_body (14 fields, single-VRF format)."""
    return [
        block_number,
        slot,
        prev_hash,
        issuer_vkey,
        vrf_vkey,
        vrf_result,
        body_size,
        body_hash,
        hot_vkey,
        seq_number,
        kes_period,
        sigma,
        proto_major,
        proto_minor,
    ]


def _encode_tagged_block(era_tag: int, payload: Any) -> bytes:
    """Manually encode a CBOR-tagged block (bypasses cbor2 semantic tag handling)."""
    tag_byte = bytes([0xC0 | era_tag])
    payload_cbor = _dumps(payload)
    return tag_byte + payload_cbor


def _wrap_block(
    era: Era, header_body: list, *, tx_bodies=None, tx_witnesses=None, aux_data=None
) -> bytes:
    """Wrap a header body + optional transactions into a full tagged block."""
    header = [header_body, SIG64]
    block = [header, tx_bodies or [], tx_witnesses or [], aux_data if aux_data is not None else {}]
    return _encode_tagged_block(era.value, block)


def _make_tx_body(
    *,
    fee: int = 200_000,
    ttl: int | None = None,
    inputs: list | None = None,
    outputs: list | None = None,
    extra_fields: dict | None = None,
) -> dict:
    """Construct a minimal transaction body as a CBOR map."""
    if inputs is None:
        inputs = [[HASH32, 0]]
    if outputs is None:
        outputs = [[ADDR_BYTES, 2_000_000]]
    body: dict = {0: inputs, 1: outputs, 2: fee}
    if ttl is not None:
        body[3] = ttl
    if extra_fields:
        body.update(extra_fields)
    return body


# ===========================================================================
# Section 1: All-era CBOR round-trip tests for block headers
#
# Haskell equivalent: checkEncodingCBORAnnotated "block_header" in each era's
# Serialisation/Encoding.hs — verifies encode/decode/re-encode identity.
# ===========================================================================


class TestAllEraHeaderRoundTrip:
    """CBOR round-trip for block headers across all post-Byron eras.

    For each era, we:
      1. Construct a header_body per CDDL
      2. Encode to CBOR (tagged block)
      3. Decode via decode_block_header
      4. Verify all fields match input
      5. Verify header_cbor round-trips through CBOR decode/encode

    This mirrors the Haskell checkEncodingCBORAnnotated pattern: encode, decode,
    verify structural identity and field correctness.
    """

    @pytest.mark.parametrize("era", SHELLEY_FAMILY_ERAS, ids=lambda e: e.name)
    def test_shelley_family_round_trip(self, era: Era):
        """Shelley/Allegra/Mary/Alonzo headers round-trip through encode/decode."""
        body = _make_shelley_header_body(
            block_number=100 + era.value,
            slot=2000 + era.value * 100,
            proto_major=era.value,
        )
        cbor_bytes = _wrap_block(era, body)
        hdr = decode_block_header(cbor_bytes)

        # Field correctness
        assert hdr.era == era
        assert hdr.block_number == 100 + era.value
        assert hdr.slot == 2000 + era.value * 100
        assert hdr.prev_hash == HASH32
        assert hdr.issuer_vkey == VKEY32
        assert hdr.block_body_size == 512
        assert hdr.block_body_hash == HASH32
        assert hdr.protocol_version.major == era.value
        assert hdr.protocol_version.minor == 0
        assert hdr.operational_cert.hot_vkey == VKEY32
        assert hdr.operational_cert.sequence_number == 7
        assert hdr.operational_cert.kes_period == 100
        assert hdr.operational_cert.sigma == SIG64

        # CBOR round-trip: header_cbor decodes back to valid structure
        re_decoded = _loads(hdr.header_cbor)
        assert isinstance(re_decoded, list)
        assert len(re_decoded) == 2  # [header_body, body_signature]
        assert len(re_decoded[0]) == 15  # Shelley-family header_body has 15 fields

    @pytest.mark.parametrize("era", BABBAGE_FAMILY_ERAS, ids=lambda e: e.name)
    def test_babbage_family_round_trip(self, era: Era):
        """Babbage/Conway headers round-trip through encode/decode."""
        proto_major = 7 if era == Era.BABBAGE else 9
        body = _make_babbage_header_body(
            block_number=200 + era.value,
            slot=8000 + era.value * 100,
            proto_major=proto_major,
        )
        cbor_bytes = _wrap_block(era, body)
        hdr = decode_block_header(cbor_bytes)

        assert hdr.era == era
        assert hdr.block_number == 200 + era.value
        assert hdr.slot == 8000 + era.value * 100
        assert hdr.protocol_version.major == proto_major

        # CBOR round-trip
        re_decoded = _loads(hdr.header_cbor)
        assert isinstance(re_decoded, list)
        assert len(re_decoded) == 2
        assert len(re_decoded[0]) == 14  # Babbage-family header_body has 14 fields

    @pytest.mark.parametrize("era", ALL_POST_BYRON_ERAS, ids=lambda e: e.name)
    def test_header_hash_stability(self, era: Era):
        """Block hash is stable across encode/decode cycle for all eras.

        Haskell equivalent: the golden hash tests that pin expected block hashes
        for known block content. We verify hash determinism here.
        """
        if era in SHELLEY_FAMILY_ERAS:
            body = _make_shelley_header_body()
        else:
            body = _make_babbage_header_body()

        cbor_bytes = _wrap_block(era, body)
        hdr = decode_block_header(cbor_bytes)

        # Compute hash from the preserved header_cbor
        hash1 = hdr.hash
        hash2 = block_hash(hdr.header_cbor)
        hash3 = hashlib.blake2b(hdr.header_cbor, digest_size=32).digest()

        assert hash1 == hash2 == hash3
        assert len(hash1) == 32

    @pytest.mark.parametrize("era", ALL_POST_BYRON_ERAS, ids=lambda e: e.name)
    def test_raw_header_round_trip(self, era: Era):
        """decode_block_header_raw round-trips header CBOR for all eras.

        This tests the alternate decode path used when headers arrive
        without the block wrapper (e.g., from chain-sync HeaderOnly).
        """
        if era in SHELLEY_FAMILY_ERAS:
            body = _make_shelley_header_body()
        else:
            body = _make_babbage_header_body()

        header = [body, SIG64]
        header_cbor = _dumps(header)

        hdr = decode_block_header_raw(header_cbor, era)
        assert hdr.era == era

        # Re-encode and compare
        re_decoded = _loads(hdr.header_cbor)
        assert isinstance(re_decoded, list)
        assert len(re_decoded) == 2


# ===========================================================================
# Section 2: Era detection from raw CBOR bytes
#
# Haskell equivalent: the hard-fork combinator's tag dispatching.
# Tests cover all valid tags, boundary conditions, and error cases.
# ===========================================================================


class TestEraDetectionExhaustive:
    """Exhaustive era detection tests covering all CBOR tag edge cases.

    The HFC wraps each era's block in a CBOR tag (major type 6). Our
    detect_era function must correctly parse this without full decoding.
    """

    @pytest.mark.parametrize(
        "era",
        list(Era),
        ids=lambda e: e.name,
    )
    def test_detect_all_known_eras(self, era: Era):
        """Every Era enum value is correctly detected from tagged CBOR."""
        tagged = _encode_tagged_block(era.value, [1, 2, 3])
        assert detect_era(tagged) == era

    @pytest.mark.parametrize("tag", [8, 9, 10, 15, 23])
    def test_detect_future_era_tags_rejected(self, tag: int):
        """Tags 8-23 (single-byte encoding) that aren't valid eras are rejected."""
        tagged = bytes([0xC0 | tag]) + _dumps([])
        with pytest.raises(ValueError, match="Unknown era tag"):
            detect_era(tagged)

    def test_detect_two_byte_tag_rejected(self):
        """Two-byte CBOR tag (0xD8 XX) for tag > 23 is rejected."""
        tagged = bytes([0xD8, 42]) + _dumps([])
        with pytest.raises(ValueError, match="Unknown era tag"):
            detect_era(tagged)

    def test_detect_empty_bytes_rejected(self):
        """Empty input raises an error (CBORDecodeEOF or ValueError)."""
        with pytest.raises((ValueError, Exception)):
            detect_era(b"")

    def test_detect_non_tag_major_types(self):
        """Non-tag CBOR major types (0-5, 7) are all rejected."""
        # Major type 0 (unsigned int): 0x00
        # Major type 1 (negative int): 0x20
        # Major type 2 (byte string): 0x40
        # Major type 3 (text string): 0x60
        # Major type 4 (array): 0x80
        # Major type 5 (map): 0xa0
        # Major type 7 (float/simple): 0xe0
        for prefix in [0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xE0]:
            with pytest.raises(ValueError, match="Expected CBOR tag"):
                detect_era(bytes([prefix]) + b"\x00" * 10)

    def test_detect_era_ignores_payload_content(self):
        """Era detection only reads the tag byte, not the payload.

        This is important for performance: we detect era without
        deserializing potentially megabytes of block data.
        """
        # Different payloads, same tag
        for payload in [[], {}, "hello", 42, b"\xff" * 100]:
            tagged = _encode_tagged_block(Era.CONWAY.value, payload)
            assert detect_era(tagged) == Era.CONWAY

    def test_detect_era_with_large_payload(self):
        """Era detection works with large payloads (does not decode them)."""
        # 10KB of nested data
        big_payload = list(range(1000))
        tagged = _encode_tagged_block(Era.BABBAGE.value, big_payload)
        assert detect_era(tagged) == Era.BABBAGE


# ===========================================================================
# Section 3: VRF output extraction — Shelley vs Babbage format
#
# Haskell: bheaderEta / bheaderL (Shelley) vs vrf_result (Babbage+)
# The VRF output is critical for nonce evolution in Ouroboros Praos.
# ===========================================================================


class TestVRFOutputExtraction:
    """VRF output extraction from block headers across era boundaries.

    Shelley-Alonzo: nonce_vrf = [output, proof] at index 5
    Babbage+: vrf_result = [output, proof] at index 5
    """

    @pytest.mark.parametrize("era", SHELLEY_FAMILY_ERAS, ids=lambda e: e.name)
    def test_shelley_family_vrf_output(self, era: Era):
        """VRF output is extracted from nonce_vrf cert in Shelley-family eras."""
        vrf_output = b"\xaa" * 32
        nonce_vrf = [vrf_output, b"\xbb" * 80]
        body = _make_shelley_header_body(nonce_vrf=nonce_vrf)
        cbor_bytes = _wrap_block(era, body)
        hdr = decode_block_header(cbor_bytes)

        assert hdr.vrf_output == vrf_output

    @pytest.mark.parametrize("era", BABBAGE_FAMILY_ERAS, ids=lambda e: e.name)
    def test_babbage_family_vrf_output(self, era: Era):
        """VRF output is extracted from vrf_result cert in Babbage-family eras."""
        vrf_output = b"\xcc" * 32
        vrf_result = [vrf_output, b"\xdd" * 80]
        body = _make_babbage_header_body(vrf_result=vrf_result)
        cbor_bytes = _wrap_block(era, body)
        hdr = decode_block_header(cbor_bytes)

        assert hdr.vrf_output == vrf_output

    def test_vrf_output_none_when_not_bytes(self):
        """VRF output is None if the cert structure is unexpected."""
        body = _make_shelley_header_body(nonce_vrf=[42, b"\x00" * 80])
        cbor_bytes = _wrap_block(Era.SHELLEY, body)
        hdr = decode_block_header(cbor_bytes)

        # 42 is an int, not bytes, so vrf_output should be None
        assert hdr.vrf_output is None

    def test_vrf_output_none_for_empty_cert(self):
        """VRF output is None if the cert array is empty."""
        body = _make_shelley_header_body(nonce_vrf=[])
        cbor_bytes = _wrap_block(Era.SHELLEY, body)
        hdr = decode_block_header(cbor_bytes)

        assert hdr.vrf_output is None


# ===========================================================================
# Section 4: Transaction body field completeness per era
#
# Haskell: each era adds fields to the transaction_body CDDL map.
# We verify decode_block_body correctly handles era-specific fields.
# ===========================================================================


class TestTransactionBodyFieldsPerEra:
    """Transaction body field completeness per era.

    CDDL field keys per era:
      Shelley: 0=inputs, 1=outputs, 2=fee, 3=ttl, 4=certs, 5=withdrawals,
               6=update, 7=auxiliary_data_hash
      Alonzo adds: 8=validity_interval_start, 9=mint, 11=script_data_hash,
                   13=collateral, 14=required_signers
      Babbage adds: 15=network_id, 16=collateral_return, 17=total_collateral,
                    18=reference_inputs
      Conway adds: 19=voting_procedures, 20=proposal_procedures, 21=treasury_value,
                   22=donation
    """

    def test_shelley_minimal_tx_body(self):
        """Shelley tx body: inputs(0), outputs(1), fee(2) are mandatory."""
        body = _make_tx_body(fee=180_000, ttl=50_000)
        block_cbor = _wrap_block(
            Era.SHELLEY,
            _make_shelley_header_body(),
            tx_bodies=[body],
            tx_witnesses=[{}],
        )
        result = decode_block_body(block_cbor)
        assert result.tx_count == 1
        tx = result.transactions[0]
        assert 0 in tx.body_raw  # inputs
        assert 1 in tx.body_raw  # outputs
        assert 2 in tx.body_raw  # fee
        assert 3 in tx.body_raw  # ttl

    def test_shelley_tx_with_certs_and_withdrawals(self):
        """Shelley tx body with optional fields 4 (certs) and 5 (withdrawals)."""
        body = _make_tx_body(
            fee=180_000,
            extra_fields={
                4: [[0, b"\x33" * 28]],  # dummy stake registration cert
                5: {b"\xe0" + b"\x44" * 28: 5_000_000},  # dummy withdrawal
            },
        )
        block_cbor = _wrap_block(
            Era.SHELLEY,
            _make_shelley_header_body(),
            tx_bodies=[body],
            tx_witnesses=[{}],
        )
        result = decode_block_body(block_cbor)
        tx = result.transactions[0]
        assert 4 in tx.body_raw
        assert 5 in tx.body_raw

    def test_alonzo_tx_body_with_collateral(self):
        """Alonzo tx body with script_data_hash(11) and collateral(13).

        CDDL (alonzo.cddl):
          transaction_body = {
            ...
            ? 11 : script_data_hash
            ? 13 : set<transaction_input>  ; collateral inputs
            ? 14 : set<$hash28>            ; required_signers
          }
        """
        body = _make_tx_body(
            fee=500_000,
            extra_fields={
                11: HASH32,  # script_data_hash
                13: [[HASH32, 1]],  # collateral input
                14: [b"\x55" * 28],  # required signer
            },
        )
        block_cbor = _wrap_block(
            Era.ALONZO,
            _make_shelley_header_body(),
            tx_bodies=[body],
            tx_witnesses=[{}],
        )
        result = decode_block_body(block_cbor)
        tx = result.transactions[0]
        assert tx.body_raw[11] == HASH32
        assert tx.body_raw[13] == [[HASH32, 1]]
        assert tx.body_raw[14] == [b"\x55" * 28]

    def test_alonzo_tx_body_with_validity_interval_start(self):
        """Alonzo tx body with validity_interval_start(8).

        Alonzo changed TTL to an optional upper bound and added
        validity_interval_start as the lower bound.
        """
        body = _make_tx_body(
            fee=300_000,
            extra_fields={
                8: 1_000_000,  # validity_interval_start (slot)
            },
        )
        block_cbor = _wrap_block(
            Era.ALONZO,
            _make_shelley_header_body(),
            tx_bodies=[body],
            tx_witnesses=[{}],
        )
        result = decode_block_body(block_cbor)
        tx = result.transactions[0]
        assert tx.body_raw[8] == 1_000_000

    def test_babbage_tx_body_with_reference_inputs(self):
        """Babbage tx body with reference_inputs(18) and collateral_return(16).

        CDDL (babbage.cddl):
          transaction_body = {
            ...
            ? 16 : transaction_output   ; collateral return
            ? 17 : coin                 ; total collateral
            ? 18 : set<transaction_input>  ; reference inputs
          }
        """
        body = _make_tx_body(
            fee=400_000,
            extra_fields={
                16: [ADDR_BYTES, 1_500_000],  # collateral return output
                17: 2_000_000,  # total collateral
                18: [[HASH32, 2]],  # reference input
            },
        )
        block_cbor = _wrap_block(
            Era.BABBAGE,
            _make_babbage_header_body(),
            tx_bodies=[body],
            tx_witnesses=[{}],
        )
        result = decode_block_body(block_cbor)
        tx = result.transactions[0]
        assert tx.body_raw[16] == [ADDR_BYTES, 1_500_000]
        assert tx.body_raw[17] == 2_000_000
        assert tx.body_raw[18] == [[HASH32, 2]]

    def test_conway_tx_body_with_governance_fields(self):
        """Conway tx body with voting_procedures(19) and proposal_procedures(20).

        CDDL (conway.cddl):
          transaction_body = {
            ...
            ? 19 : voting_procedures
            ? 20 : proposal_procedures
            ? 21 : coin            ; treasury_value (current treasury amt)
            ? 22 : positive_coin   ; donation
          }
        """
        body = _make_tx_body(
            fee=500_000,
            extra_fields={
                19: {
                    b"\x66" * 28: {HASH32: 1}
                },  # voting procedures (voter -> govActionId -> vote)
                20: [[0, HASH32, 1_000_000, HASH32]],  # proposal procedures
                21: 50_000_000_000,  # treasury value
                22: 1_000_000,  # donation
            },
        )
        block_cbor = _wrap_block(
            Era.CONWAY,
            _make_babbage_header_body(proto_major=9),
            tx_bodies=[body],
            tx_witnesses=[{}],
        )
        result = decode_block_body(block_cbor)
        tx = result.transactions[0]
        assert 19 in tx.body_raw
        assert 20 in tx.body_raw
        assert tx.body_raw[21] == 50_000_000_000
        assert tx.body_raw[22] == 1_000_000

    def test_conway_tx_body_all_field_keys_preserved(self):
        """All Conway CDDL field keys (0-22) are preserved in body_raw.

        This ensures the decoder does not drop unknown fields — a critical
        property for forward compatibility.
        """
        all_fields = {
            0: [[HASH32, 0]],  # inputs
            1: [[ADDR_BYTES, 2_000_000]],  # outputs
            2: 300_000,  # fee
            3: 100_000,  # ttl
            4: [],  # certs
            5: {},  # withdrawals
            7: HASH32,  # auxiliary_data_hash
            8: 500,  # validity_interval_start
            9: {b"\x00" * 28: {b"TOKEN": 100}},  # mint (policy_id -> {asset -> amount})
            11: HASH32,  # script_data_hash
            13: [[HASH32, 1]],  # collateral
            14: [b"\x55" * 28],  # required_signers
            15: 1,  # network_id (mainnet)
            16: [ADDR_BYTES, 1_000_000],  # collateral_return
            17: 2_000_000,  # total_collateral
            18: [[HASH32, 3]],  # reference_inputs
            19: {},  # voting_procedures
            20: [],  # proposal_procedures
            21: 10_000_000_000,  # treasury_value
            22: 500_000,  # donation
        }
        block_cbor = _wrap_block(
            Era.CONWAY,
            _make_babbage_header_body(proto_major=9),
            tx_bodies=[all_fields],
            tx_witnesses=[{}],
        )
        result = decode_block_body(block_cbor)
        tx = result.transactions[0]

        for key in all_fields:
            assert key in tx.body_raw, f"Field key {key} missing from body_raw"


# ===========================================================================
# Section 5: Edge cases — empty blocks, many transactions, boundary values
#
# Haskell: genBlock generates blocks with 0..N transactions. The property
# tests verify round-trip for arbitrary block sizes. We test boundaries.
# ===========================================================================


class TestEmptyBlocks:
    """Empty blocks (no transactions) across all post-Byron eras.

    Haskell equivalent: checkEncodingCBORAnnotated "empty_block"
    Block (BHeader ...) (TxSeq StrictSeq.Empty)
    """

    @pytest.mark.parametrize("era", ALL_POST_BYRON_ERAS, ids=lambda e: e.name)
    def test_empty_block_round_trip(self, era: Era):
        """Empty block decodes successfully with tx_count=0 for all eras."""
        if era in SHELLEY_FAMILY_ERAS:
            body = _make_shelley_header_body()
        else:
            body = _make_babbage_header_body()

        block_cbor = _wrap_block(era, body)
        result = decode_block_body(block_cbor)

        assert result.era == era
        assert result.tx_count == 0
        assert result.transactions == []

    @pytest.mark.parametrize("era", ALL_POST_BYRON_ERAS, ids=lambda e: e.name)
    def test_empty_block_header_still_valid(self, era: Era):
        """Header decodes correctly even when block body is empty."""
        if era in SHELLEY_FAMILY_ERAS:
            body = _make_shelley_header_body(block_number=0, slot=0)
        else:
            body = _make_babbage_header_body(block_number=0, slot=0)

        block_cbor = _wrap_block(era, body)
        hdr = decode_block_header(block_cbor)

        assert hdr.era == era
        assert hdr.block_number == 0
        assert hdr.slot == 0


class TestManyTransactions:
    """Blocks with many transactions test decode scalability.

    Haskell property tests generate blocks with arbitrary tx counts.
    We verify our decoder handles realistic counts (up to 100).
    """

    @pytest.mark.parametrize("tx_count", [1, 5, 10, 50, 100])
    def test_multi_tx_block_decode(self, tx_count: int):
        """Block with N transactions decodes all of them."""
        bodies = [_make_tx_body(fee=200_000 + i) for i in range(tx_count)]
        witnesses = [{} for _ in range(tx_count)]

        block_cbor = _wrap_block(
            Era.BABBAGE,
            _make_babbage_header_body(),
            tx_bodies=bodies,
            tx_witnesses=witnesses,
        )
        result = decode_block_body(block_cbor)

        assert result.tx_count == tx_count
        assert len(result.transactions) == tx_count

        # Each transaction has a unique fee (and therefore unique hash)
        hashes = {tx.tx_hash for tx in result.transactions}
        assert len(hashes) == tx_count, "All transactions should have unique hashes"

    def test_tx_indices_are_sequential(self):
        """Transaction indices are 0-based and sequential."""
        bodies = [_make_tx_body(fee=100_000 + i) for i in range(20)]
        witnesses = [{} for _ in range(20)]

        block_cbor = _wrap_block(
            Era.CONWAY,
            _make_babbage_header_body(proto_major=9),
            tx_bodies=bodies,
            tx_witnesses=witnesses,
        )
        result = decode_block_body(block_cbor)

        for i, tx in enumerate(result.transactions):
            assert tx.index == i, f"Transaction at position {i} has index {tx.index}"


class TestBoundaryValues:
    """Boundary value tests for CBOR integer encoding edge cases.

    CBOR encodes integers differently based on magnitude:
      0-23: single byte (major type + value)
      24-255: 2 bytes (major type + 0x18 + value)
      256-65535: 3 bytes (major type + 0x19 + 2-byte value)
      65536-2^32-1: 5 bytes (major type + 0x1A + 4-byte value)
      2^32-2^64-1: 9 bytes (major type + 0x1B + 8-byte value)

    Block headers contain integers (slot, block_number, body_size) that
    must survive CBOR round-trips at encoding boundaries.
    """

    @pytest.mark.parametrize(
        "slot,desc",
        [
            (0, "zero"),
            (23, "max_single_byte"),
            (24, "min_two_byte"),
            (255, "max_two_byte"),
            (256, "min_three_byte"),
            (65535, "max_three_byte"),
            (65536, "min_five_byte"),
            (2**32 - 1, "max_five_byte"),
            (2**32, "min_nine_byte"),
            (2**63 - 1, "large_slot"),
        ],
    )
    def test_slot_boundary_round_trip(self, slot: int, desc: str):
        """Slot numbers at CBOR integer encoding boundaries survive round-trip."""
        body = _make_babbage_header_body(slot=slot)
        cbor_bytes = _wrap_block(Era.BABBAGE, body)
        hdr = decode_block_header(cbor_bytes)
        assert hdr.slot == slot, f"Slot {desc}={slot} did not round-trip"

    @pytest.mark.parametrize(
        "block_number",
        [0, 1, 23, 24, 255, 256, 65535, 65536, 2**32 - 1, 2**32],
    )
    def test_block_number_boundary_round_trip(self, block_number: int):
        """Block numbers at encoding boundaries survive round-trip."""
        body = _make_shelley_header_body(block_number=block_number)
        cbor_bytes = _wrap_block(Era.SHELLEY, body)
        hdr = decode_block_header(cbor_bytes)
        assert hdr.block_number == block_number

    @pytest.mark.parametrize(
        "body_size",
        [0, 1, 255, 256, 65535, 65536, 2**20, 2**32 - 1],
    )
    def test_body_size_boundary_round_trip(self, body_size: int):
        """Block body size at encoding boundaries survives round-trip."""
        body = _make_babbage_header_body(body_size=body_size)
        cbor_bytes = _wrap_block(Era.BABBAGE, body)
        hdr = decode_block_header(cbor_bytes)
        assert hdr.block_body_size == body_size

    @pytest.mark.parametrize(
        "fee",
        [0, 1, 255, 256, 65535, 65536, 2**32 - 1, 2**32, 45_000_000_000_000],
    )
    def test_tx_fee_boundary_round_trip(self, fee: int):
        """Transaction fees at encoding boundaries survive round-trip."""
        body = _make_tx_body(fee=fee)
        block_cbor = _wrap_block(
            Era.BABBAGE,
            _make_babbage_header_body(),
            tx_bodies=[body],
            tx_witnesses=[{}],
        )
        result = decode_block_body(block_cbor)
        assert result.transactions[0].body_raw[2] == fee


class TestNullPrevHash:
    """Null prev_hash handling (genesis block scenario).

    The first block of each era has prev_hash = null (CBOR null = 0xF6).
    The Haskell node uses GenesisHash (a sentinel) for this case.
    """

    @pytest.mark.parametrize("era", ALL_POST_BYRON_ERAS, ids=lambda e: e.name)
    def test_null_prev_hash_all_eras(self, era: Era):
        """Null prev_hash decodes as None for all post-Byron eras."""
        if era in SHELLEY_FAMILY_ERAS:
            body = _make_shelley_header_body(prev_hash=None)
        else:
            body = _make_babbage_header_body(prev_hash=None)

        cbor_bytes = _wrap_block(era, body)
        hdr = decode_block_header(cbor_bytes)
        assert hdr.prev_hash is None


class TestProtocolVersionPerEra:
    """Protocol version values per era.

    Spec reference: each hard fork bumps the major protocol version:
      Shelley: 2.0, Allegra: 3.0, Mary: 4.0, Alonzo: 5.0/6.0,
      Babbage: 7.0/8.0, Conway: 9.0/10.0

    The header_body includes protocol_version which the node validates
    against the current era. We verify it round-trips correctly.
    """

    @pytest.mark.parametrize(
        "era,major,minor",
        [
            (Era.SHELLEY, 2, 0),
            (Era.ALLEGRA, 3, 0),
            (Era.MARY, 4, 0),
            (Era.ALONZO, 6, 0),
            (Era.BABBAGE, 8, 0),
            (Era.CONWAY, 9, 0),
            (Era.CONWAY, 10, 0),
        ],
    )
    def test_protocol_version_round_trip(self, era: Era, major: int, minor: int):
        """Protocol version round-trips for realistic era/version combinations."""
        if era in SHELLEY_FAMILY_ERAS:
            body = _make_shelley_header_body(proto_major=major, proto_minor=minor)
        else:
            body = _make_babbage_header_body(proto_major=major, proto_minor=minor)

        cbor_bytes = _wrap_block(era, body)
        hdr = decode_block_header(cbor_bytes)
        assert hdr.protocol_version == ProtocolVersion(major=major, minor=minor)


# ===========================================================================
# Section 6: Transaction hash determinism
#
# Haskell: TxId is defined as SafeHash (blake2b-256 of serialized TxBody).
# We verify deterministic hashing and uniqueness properties.
# ===========================================================================


class TestTransactionHashDeterminism:
    """Transaction hash determinism and uniqueness.

    Haskell equivalent: hashAnnotated (TxBody) produces SafeHash TxId.
    """

    def test_same_body_same_hash(self):
        """Identical transaction bodies produce identical hashes."""
        body = _make_tx_body(fee=200_000)
        h1 = _tx_hash(body)
        h2 = _tx_hash(body)
        assert h1 == h2

    def test_different_body_different_hash(self):
        """Different transaction bodies produce different hashes."""
        b1 = _make_tx_body(fee=200_000)
        b2 = _make_tx_body(fee=200_001)
        assert _tx_hash(b1) != _tx_hash(b2)

    def test_tx_hash_is_blake2b_256(self):
        """Transaction hash matches manual blake2b-256 computation."""
        body = _make_tx_body(fee=300_000)
        body_cbor = _dumps(body)
        expected = hashlib.blake2b(body_cbor, digest_size=32).digest()
        assert _tx_hash(body) == expected

    def test_tx_hash_in_decoded_block(self):
        """Transaction hashes in decoded blocks match manual computation."""
        bodies = [_make_tx_body(fee=100_000 + i) for i in range(5)]
        witnesses = [{} for _ in range(5)]

        block_cbor = _wrap_block(
            Era.CONWAY,
            _make_babbage_header_body(proto_major=9),
            tx_bodies=bodies,
            tx_witnesses=witnesses,
        )
        result = decode_block_body(block_cbor)

        for i, tx in enumerate(result.transactions):
            expected_hash = hashlib.blake2b(_dumps(bodies[i]), digest_size=32).digest()
            assert tx.tx_hash == expected_hash, f"Tx {i} hash mismatch"

    def test_tx_hash_length_always_32(self):
        """Transaction hash is always exactly 32 bytes."""
        for fee in [0, 1, 2**32, 2**63 - 1]:
            body = _make_tx_body(fee=fee)
            assert len(_tx_hash(body)) == 32


# ===========================================================================
# Section 7: Auxiliary data handling
#
# Haskell: auxiliary data is a map from tx index to metadata.
# The block body decoder must handle present, absent, and empty cases.
# ===========================================================================


class TestAuxiliaryDataHandling:
    """Auxiliary data (metadata) handling in block body decoding.

    CDDL: auxiliary_data = { * transaction_index => auxiliary_data }
    """

    def test_block_with_no_auxiliary_data(self):
        """Empty auxiliary data map decodes correctly."""
        body = _make_tx_body()
        block_cbor = _wrap_block(
            Era.SHELLEY,
            _make_shelley_header_body(),
            tx_bodies=[body],
            tx_witnesses=[{}],
            aux_data={},
        )
        result = decode_block_body(block_cbor)
        assert result.transactions[0].auxiliary_data is None

    def test_block_with_auxiliary_data_for_tx(self):
        """Auxiliary data present for a specific transaction index."""
        body = _make_tx_body()
        aux = {0: {1: "metadata value"}}  # tx index 0 -> metadata map

        block_cbor = _wrap_block(
            Era.BABBAGE,
            _make_babbage_header_body(),
            tx_bodies=[body],
            tx_witnesses=[{}],
            aux_data=aux,
        )
        result = decode_block_body(block_cbor)
        # Auxiliary data should be present (either as AuxiliaryData or raw)
        assert result.transactions[0].auxiliary_data is not None

    def test_block_with_null_auxiliary_data(self):
        """Null auxiliary data is treated as empty.

        Some eras encode empty auxiliary data as CBOR null rather than
        empty map {}. The decoder should handle both.
        """
        header_body = _make_shelley_header_body()
        header = [header_body, SIG64]
        body = _make_tx_body()
        # Manually construct block with null auxiliary_data
        block_array = [header, [body], [{}], None]
        payload_cbor = _dumps(block_array)
        block_cbor = bytes([0xC0 | Era.SHELLEY.value]) + payload_cbor

        result = decode_block_body(block_cbor)
        assert result.tx_count == 1
        # With null aux_data, no metadata for any transaction
        assert result.transactions[0].auxiliary_data is None


# ===========================================================================
# Section 8: Byron block rejection
#
# Haskell: Byron blocks use a completely different structure. Our decoder
# explicitly rejects them with NotImplementedError.
# ===========================================================================


class TestByronBlockRejection:
    """Byron blocks are explicitly rejected by all decoders.

    Both header and body decoders reject Byron-era blocks because
    Byron uses a fundamentally different block structure.
    """

    @pytest.mark.parametrize("era", BYRON_ERAS, ids=lambda e: e.name)
    def test_decode_header_rejects_byron(self, era: Era):
        """decode_block_header raises NotImplementedError for Byron."""
        block_cbor = _encode_tagged_block(era.value, [[], [], [], {}])
        with pytest.raises(NotImplementedError, match="Byron"):
            decode_block_header(block_cbor)

    @pytest.mark.parametrize("era", BYRON_ERAS, ids=lambda e: e.name)
    def test_decode_body_rejects_byron(self, era: Era):
        """decode_block_body raises NotImplementedError for Byron."""
        block_cbor = _encode_tagged_block(era.value, [[], [], [], {}])
        with pytest.raises(NotImplementedError, match="Byron"):
            decode_block_body(block_cbor)

    @pytest.mark.parametrize("era", BYRON_ERAS, ids=lambda e: e.name)
    def test_decode_header_raw_rejects_byron(self, era: Era):
        """decode_block_header_raw raises NotImplementedError for Byron."""
        with pytest.raises(NotImplementedError, match="Byron"):
            decode_block_header_raw(b"\x82\x80\x40", era)


# ===========================================================================
# Section 9: Cross-decoder consistency
#
# Verify that decode_block_header and decode_block_body agree on era
# detection and structural parsing when given the same block CBOR.
# ===========================================================================


class TestCrossDecoderConsistency:
    """Header and body decoders agree on era and structure for the same block."""

    @pytest.mark.parametrize("era", ALL_POST_BYRON_ERAS, ids=lambda e: e.name)
    def test_header_and_body_agree_on_era(self, era: Era):
        """Both decoders report the same era for identical block CBOR."""
        if era in SHELLEY_FAMILY_ERAS:
            header_body = _make_shelley_header_body()
        else:
            header_body = _make_babbage_header_body()

        body = _make_tx_body()
        block_cbor = _wrap_block(
            era,
            header_body,
            tx_bodies=[body],
            tx_witnesses=[{}],
        )

        hdr = decode_block_header(block_cbor)
        block_body = decode_block_body(block_cbor)

        assert hdr.era == era
        assert block_body.era == era

    @pytest.mark.parametrize("era", ALL_POST_BYRON_ERAS, ids=lambda e: e.name)
    def test_detect_era_agrees_with_decoders(self, era: Era):
        """detect_era agrees with the era reported by full decoders."""
        if era in SHELLEY_FAMILY_ERAS:
            header_body = _make_shelley_header_body()
        else:
            header_body = _make_babbage_header_body()

        block_cbor = _wrap_block(era, header_body)
        detected = detect_era(block_cbor)
        hdr = decode_block_header(block_cbor)

        assert detected == era
        assert hdr.era == era


# ===========================================================================
# Section 10: Malformed input rejection
#
# Haskell: decodeFull'Annotated rejects malformed CBOR with DecoderError.
# We verify our decoders produce clear errors for various malformed inputs.
# ===========================================================================


class TestMalformedInputRejection:
    """Malformed CBOR inputs produce clear error messages."""

    def test_truncated_header_body_shelley(self):
        """Shelley header_body with fewer than 15 fields is rejected."""
        short_body = list(range(10))  # need 15
        block_cbor = _wrap_block(Era.SHELLEY, short_body)
        with pytest.raises(ValueError, match="expected >= 15 items"):
            decode_block_header(block_cbor)

    def test_truncated_header_body_babbage(self):
        """Babbage header_body with fewer than 10 fields is rejected."""
        short_body = list(range(5))  # need 10
        block_cbor = _wrap_block(Era.BABBAGE, short_body)
        with pytest.raises(ValueError, match="expected >= 10 items"):
            decode_block_header(block_cbor)

    def test_block_not_array(self):
        """Block payload that is not a CBOR array is rejected."""
        block_cbor = _encode_tagged_block(Era.SHELLEY.value, "not an array")
        with pytest.raises(ValueError, match="Expected block as CBOR array"):
            decode_block_header(block_cbor)

    def test_block_too_short(self):
        """Block array with fewer than 4 elements is rejected."""
        block_cbor = _encode_tagged_block(Era.SHELLEY.value, [[], []])
        with pytest.raises(ValueError, match="Expected block as CBOR array"):
            decode_block_header(block_cbor)

    def test_header_not_two_element_array(self):
        """Header that is not [header_body, signature] is rejected."""
        block_cbor = _encode_tagged_block(Era.SHELLEY.value, [[1, 2, 3], [], [], {}])
        with pytest.raises(ValueError, match="Expected header as CBOR array of 2"):
            decode_block_header(block_cbor)

    def test_tx_body_witness_count_mismatch(self):
        """Mismatched tx body and witness counts are rejected."""
        bodies = [_make_tx_body(), _make_tx_body()]
        witnesses = [{}]  # One witness for two bodies
        block_cbor = _wrap_block(
            Era.BABBAGE,
            _make_babbage_header_body(),
            tx_bodies=bodies,
            tx_witnesses=witnesses,
        )
        with pytest.raises(ValueError, match="does not match"):
            decode_block_body(block_cbor)

    def test_tx_body_not_dict_rejected(self):
        """Transaction body that is not a CBOR map is rejected."""
        block_cbor = _wrap_block(
            Era.BABBAGE,
            _make_babbage_header_body(),
            tx_bodies=[[1, 2, 3]],  # array instead of map
            tx_witnesses=[{}],
        )
        with pytest.raises(ValueError, match="expected dict"):
            decode_block_body(block_cbor)
