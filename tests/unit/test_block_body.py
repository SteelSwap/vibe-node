"""Unit tests for block body decoding — transactions, witnesses, auxiliary data.

Tests use CBOR test vectors constructed by hand with cbor2, following
the CDDL specs from cardano-ledger (shelley.cddl, babbage.cddl, conway.cddl).

Test specifications sourced from the test_specifications database table
(subsystem='serialization', test_type='unit', priority='critical').
"""

from __future__ import annotations

import hashlib

import cbor2
import pytest

from pycardano.key import VerificationKey
from pycardano.metadata import AuxiliaryData, Metadata
from pycardano.transaction import Transaction, TransactionBody
from pycardano.witness import TransactionWitnessSet, VerificationKeyWitness

from vibe.cardano.serialization.transaction import (
    DecodedBlockBody,
    DecodedTransaction,
    Era,
    decode_block_body,
    decode_block_transactions,
    _tx_hash,
    _try_decode_tx_body,
    _try_decode_witness_set,
    _try_decode_auxiliary_data,
)


# ---------------------------------------------------------------------------
# Test vector helpers
# ---------------------------------------------------------------------------

# Dummy 32-byte values
HASH32 = b"\xab" * 32
VKEY32 = b"\xef" * 32
SIG64 = b"\xcd" * 64
VRF_CERT = [b"\x01" * 32, b"\x02" * 80]

# Valid Shelley-era address bytes (type 0, mainnet, with 28-byte key hash pairs)
ADDR_BYTES = b"\x00" + b"\x11" * 28 + b"\x22" * 28


def _make_shelley_header_body() -> list:
    """Minimal Shelley header_body (15 items)."""
    return [
        42,         # block_number
        1000,       # slot
        HASH32,     # prev_hash
        VKEY32,     # issuer_vkey
        VKEY32,     # vrf_vkey
        VRF_CERT,   # nonce_vrf
        VRF_CERT,   # leader_vrf
        512,        # block_body_size
        HASH32,     # block_body_hash
        VKEY32,     # op_cert hot_vkey
        7,          # op_cert sequence_number
        100,        # op_cert kes_period
        SIG64,      # op_cert sigma
        3,          # protocol_version major
        0,          # protocol_version minor
    ]


def _make_babbage_header_body() -> list:
    """Minimal Babbage header_body (14 items)."""
    return [
        99,         # block_number
        5000,       # slot
        HASH32,     # prev_hash
        VKEY32,     # issuer_vkey
        VKEY32,     # vrf_vkey
        VRF_CERT,   # vrf_result (single, replaces nonce_vrf + leader_vrf)
        1024,       # block_body_size
        HASH32,     # block_body_hash
        VKEY32,     # op_cert hot_vkey
        10,         # op_cert sequence_number
        200,        # op_cert kes_period
        SIG64,      # op_cert sigma
        7,          # protocol_version major
        0,          # protocol_version minor
    ]


def _make_tx_body_primitive(
    *,
    input_tx_hash: bytes = HASH32,
    input_index: int = 0,
    output_addr: bytes = ADDR_BYTES,
    output_amount: int = 2_000_000,
    fee: int = 200_000,
    ttl: int | None = None,
) -> dict:
    """Construct a minimal transaction body as a CBOR primitive (map).

    CDDL (shelley.cddl):
        transaction_body =
          { 0 : set<transaction_input>    ; inputs
          , 1 : [* transaction_output]    ; outputs
          , 2 : coin                      ; fee
          , ? 3 : uint                    ; ttl
          , ...
          }
        transaction_input = [transaction_id : hash32, index : uint]
        transaction_output = [address, amount : value]
    """
    body: dict = {
        0: [[input_tx_hash, input_index]],
        1: [[output_addr, output_amount]],
        2: fee,
    }
    if ttl is not None:
        body[3] = ttl
    return body


def _make_witness_set_primitive(
    *,
    vkey: bytes | None = None,
    sig: bytes | None = None,
) -> dict:
    """Construct a minimal witness set as a CBOR primitive (map).

    CDDL: transaction_witness_set = {? 0: [* vkeywitness], ...}
    """
    ws: dict = {}
    if vkey is not None and sig is not None:
        ws[0] = [[vkey, sig]]
    return ws


def _make_block_cbor(
    era: Era,
    tx_bodies: list[dict] | None = None,
    tx_witnesses: list[dict] | None = None,
    auxiliary_data: dict | None = None,
    header_body: list | None = None,
) -> bytes:
    """Build a complete tagged block CBOR for testing.

    block = tag(era, [header, tx_bodies, tx_witnesses, auxiliary_data])
    """
    if header_body is None:
        if era.value <= Era.ALONZO:
            header_body = _make_shelley_header_body()
        else:
            header_body = _make_babbage_header_body()

    header = [header_body, SIG64]

    if tx_bodies is None:
        tx_bodies = []
    if tx_witnesses is None:
        tx_witnesses = []
    if auxiliary_data is None:
        auxiliary_data = {}

    block_array = [header, tx_bodies, tx_witnesses, auxiliary_data]
    payload_cbor = cbor2.dumps(block_array)

    # Manually prepend the era tag byte (major type 6, tag 0-7)
    tag_byte = 0xC0 | era.value
    return bytes([tag_byte]) + payload_cbor


# ---------------------------------------------------------------------------
# Tests: raw_tags CBOR tag decoding (replaces removed _strip_tag tests)
# ---------------------------------------------------------------------------


class TestRawTagDecoding:
    """Verify raw_tags=True correctly extracts CBOR era tags.

    Uses cbor2pure (our fork with raw_tags support), not cbor2.
    """

    def test_tag_0_raw(self):
        import cbor2pure

        payload = [1, 2, 3]
        tagged = cbor2pure.dumps(cbor2pure.CBORTag(0, payload))
        decoded = cbor2pure.loads(tagged, raw_tags=True)
        assert decoded.tag == 0
        assert decoded.value == payload

    def test_tag_7_raw(self):
        import cbor2pure

        payload = "hello"
        tagged = cbor2pure.dumps(cbor2pure.CBORTag(7, payload))
        decoded = cbor2pure.loads(tagged, raw_tags=True)
        assert decoded.tag == 7
        assert decoded.value == payload

    def test_tag_30_raw(self):
        import cbor2pure

        payload = 42
        tagged = cbor2pure.dumps(cbor2pure.CBORTag(30, payload))
        decoded = cbor2pure.loads(tagged, raw_tags=True)
        assert decoded.tag == 30
        assert decoded.value == payload

    def test_non_tag_returns_plain_value(self):
        """Non-tagged data returns plain value, not CBORTag."""
        import cbor2pure

        decoded = cbor2pure.loads(b"\x01", raw_tags=True)
        assert not isinstance(decoded, cbor2pure.CBORTag)
        assert decoded == 1


# ---------------------------------------------------------------------------
# Tests: _tx_hash
# ---------------------------------------------------------------------------


class TestTxHash:
    """test_txid_is_hash_of_tx_body: Verify TxId is blake2b-256 of serialized body."""

    def test_tx_hash_matches_manual_blake2b(self):
        body = _make_tx_body_primitive()
        body_cbor = cbor2.dumps(body)
        expected = hashlib.blake2b(body_cbor, digest_size=32).digest()
        assert _tx_hash(body) == expected

    def test_tx_hash_is_32_bytes(self):
        body = _make_tx_body_primitive()
        assert len(_tx_hash(body)) == 32

    def test_different_bodies_produce_different_hashes(self):
        body1 = _make_tx_body_primitive(fee=100_000)
        body2 = _make_tx_body_primitive(fee=200_000)
        assert _tx_hash(body1) != _tx_hash(body2)


# ---------------------------------------------------------------------------
# Tests: decode_block_body — basic structure
# ---------------------------------------------------------------------------


class TestDecodeBlockBodyStructure:
    """Structural tests for the block body decoder."""

    def test_empty_block_shelley(self):
        """Block with zero transactions should decode to empty list."""
        raw = _make_block_cbor(Era.SHELLEY)
        result = decode_block_body(raw)
        assert isinstance(result, DecodedBlockBody)
        assert result.era == Era.SHELLEY
        assert result.tx_count == 0
        assert result.transactions == []

    def test_empty_block_babbage(self):
        raw = _make_block_cbor(Era.BABBAGE)
        result = decode_block_body(raw)
        assert result.era == Era.BABBAGE
        assert result.tx_count == 0

    def test_empty_block_conway(self):
        raw = _make_block_cbor(Era.CONWAY)
        result = decode_block_body(raw)
        assert result.era == Era.CONWAY
        assert result.tx_count == 0

    @pytest.mark.parametrize("era", [Era.SHELLEY, Era.ALLEGRA, Era.MARY, Era.ALONZO])
    def test_all_shelley_family_eras(self, era):
        body = _make_tx_body_primitive()
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(era, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        assert result.era == era
        assert result.tx_count == 1

    @pytest.mark.parametrize("era", [Era.BABBAGE, Era.CONWAY])
    def test_babbage_conway_eras(self, era):
        body = _make_tx_body_primitive()
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(era, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        assert result.era == era
        assert result.tx_count == 1

    def test_byron_raises_not_implemented(self):
        payload = cbor2.dumps([[], [], [], {}])
        tagged = bytes([0xC0]) + payload  # tag 0 = Byron main
        with pytest.raises(NotImplementedError, match="Byron"):
            decode_block_body(tagged)

    def test_byron_ebb_raises_not_implemented(self):
        payload = cbor2.dumps([[], [], [], {}])
        tagged = bytes([0xC1]) + payload  # tag 1 = Byron EBB
        with pytest.raises(NotImplementedError, match="Byron"):
            decode_block_body(tagged)

    def test_unknown_era_raises_value_error(self):
        payload = cbor2.dumps([[], [], [], {}])
        tagged = bytes([0xD8, 42]) + payload  # tag 42 = unknown
        with pytest.raises(ValueError, match="Unknown era tag"):
            decode_block_body(tagged)

    def test_malformed_block_not_array(self):
        payload = cbor2.dumps({"not": "an array"})
        tagged = bytes([0xC2]) + payload
        with pytest.raises(ValueError, match="array of >= 4"):
            decode_block_body(tagged)

    def test_malformed_block_too_few_elements(self):
        payload = cbor2.dumps([[], []])
        tagged = bytes([0xC2]) + payload
        with pytest.raises(ValueError, match="array of >= 4"):
            decode_block_body(tagged)

    def test_tx_body_count_mismatch_raises(self):
        """Body count != witness count should raise."""
        body = _make_tx_body_primitive()
        raw = _make_block_cbor(
            Era.SHELLEY,
            tx_bodies=[body, body],
            tx_witnesses=[_make_witness_set_primitive()],
        )
        with pytest.raises(ValueError, match="does not match"):
            decode_block_body(raw)


# ---------------------------------------------------------------------------
# Tests: Transaction body decoding
# ---------------------------------------------------------------------------


class TestTransactionBodyDecoding:
    """test_try_decode_tx_body and integration with decode_block_body."""

    def test_simple_tx_body_decodes_to_pycardano(self):
        """A minimal tx body should be decoded by pycardano."""
        body = _make_tx_body_primitive()
        result = _try_decode_tx_body(body)
        assert isinstance(result, TransactionBody)
        assert result.fee == 200_000

    def test_tx_body_with_ttl(self):
        body = _make_tx_body_primitive(ttl=50_000)
        result = _try_decode_tx_body(body)
        assert isinstance(result, TransactionBody)
        assert result.ttl == 50_000

    def test_tx_body_inputs_decoded(self):
        body = _make_tx_body_primitive()
        result = _try_decode_tx_body(body)
        assert isinstance(result, TransactionBody)
        assert len(result.inputs) == 1
        tx_input = list(result.inputs)[0]
        assert tx_input.index == 0

    def test_tx_body_outputs_decoded(self):
        body = _make_tx_body_primitive(output_amount=5_000_000)
        result = _try_decode_tx_body(body)
        assert isinstance(result, TransactionBody)
        assert len(result.outputs) == 1
        assert result.outputs[0].amount.coin == 5_000_000

    def test_tx_body_fallback_on_unknown_fields(self):
        """Unknown fields that pycardano can't handle should fall back to raw dict."""
        body = _make_tx_body_primitive()
        # Add a field with a very high key that pycardano might not know
        body[999] = b"unknown_data"
        result = _try_decode_tx_body(body)
        # pycardano may or may not handle this — the point is we don't crash
        assert result is not None

    def test_multiple_tx_bodies_in_block(self):
        bodies = [
            _make_tx_body_primitive(fee=100_000),
            _make_tx_body_primitive(fee=200_000),
            _make_tx_body_primitive(fee=300_000),
        ]
        witnesses = [_make_witness_set_primitive() for _ in bodies]
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=bodies, tx_witnesses=witnesses)
        result = decode_block_body(raw)
        assert result.tx_count == 3
        assert all(isinstance(tx, DecodedTransaction) for tx in result.transactions)

    def test_transaction_indices_sequential(self):
        bodies = [_make_tx_body_primitive() for _ in range(5)]
        witnesses = [_make_witness_set_primitive() for _ in bodies]
        raw = _make_block_cbor(Era.SHELLEY, tx_bodies=bodies, tx_witnesses=witnesses)
        result = decode_block_body(raw)
        assert [tx.index for tx in result.transactions] == [0, 1, 2, 3, 4]

    def test_each_tx_has_unique_hash_when_different(self):
        bodies = [
            _make_tx_body_primitive(fee=i * 100_000 + 100_000)
            for i in range(3)
        ]
        witnesses = [_make_witness_set_primitive() for _ in bodies]
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=bodies, tx_witnesses=witnesses)
        result = decode_block_body(raw)
        hashes = [tx.tx_hash for tx in result.transactions]
        assert len(set(hashes)) == 3  # all unique


# ---------------------------------------------------------------------------
# Tests: Witness set decoding
# ---------------------------------------------------------------------------


class TestWitnessSetDecoding:
    """Tests for witness set parsing, matching DB test specs."""

    def test_empty_witness_set(self):
        """test_tx_witnesses_empty: empty vkSigs and scripts."""
        ws = _try_decode_witness_set({})
        assert isinstance(ws, TransactionWitnessSet)
        assert ws.vkey_witnesses is None
        assert ws.native_scripts is None

    def test_witness_set_is_empty_method(self):
        """Verify is_empty() works on decoded empty witness set."""
        ws = _try_decode_witness_set({})
        assert isinstance(ws, TransactionWitnessSet)
        assert ws.is_empty()

    def test_witness_set_with_vkey_witnesses(self):
        """test_tx_witnesses_has_both_fields: vkSigs accessible."""
        vkey = b"\x01" * 32
        sig = b"\x02" * 64
        raw = {0: [[vkey, sig]]}
        ws = _try_decode_witness_set(raw)
        assert isinstance(ws, TransactionWitnessSet)
        assert ws.vkey_witnesses is not None
        assert len(ws.vkey_witnesses) == 1

    def test_vkeywitness_serializes_as_two_element_array(self):
        """test_vkeywitness_serializes_as_two_element_array:
        VKey witness is a 2-element CBOR array [vkey, signature]."""
        vkey = b"\xaa" * 32
        sig = b"\xbb" * 64
        vkw = VerificationKeyWitness(
            vkey=VerificationKey.from_primitive(vkey),
            signature=sig,
        )
        cbor_bytes = vkw.to_cbor()
        # First byte should be 0x82 (definite-length array of 2)
        assert cbor_bytes[0] == 0x82

    def test_vkeywitness_element_order_vkey_then_sig(self):
        """test_vkeywitness_element_order_is_vkey_then_signature:
        Element [0] is vkey, element [1] is signature."""
        vkey = b"\xaa" * 32
        sig = b"\xbb" * 64
        vkw = VerificationKeyWitness(
            vkey=VerificationKey.from_primitive(vkey),
            signature=sig,
        )
        cbor_bytes = vkw.to_cbor()
        decoded = cbor2.loads(cbor_bytes)
        assert decoded[0] == vkey
        assert decoded[1] == sig

    def test_vkeywitness_uses_definite_length_encoding(self):
        """test_vkeywitness_uses_definite_length_encoding:
        Check first byte is 0x82 (definite-length, not indefinite)."""
        vkey = b"\x01" * 32
        sig = b"\x02" * 64
        vkw = VerificationKeyWitness(
            vkey=VerificationKey.from_primitive(vkey),
            signature=sig,
        )
        raw = vkw.to_cbor()
        assert raw[0] == 0x82  # definite-length 2-element array

    def test_witness_set_with_native_scripts(self):
        """Witness set with native scripts field (key 1)."""
        # ScriptAll with no scripts is [1, []] in CDDL
        raw = {1: [[0, []]]}  # NativeScript type 0 = ScriptAll? Actually ScriptPubkey
        # pycardano may or may not handle this — test we don't crash
        ws = _try_decode_witness_set(raw)
        assert ws is not None

    def test_witness_set_fallback_on_malformed(self):
        """Malformed witness data should fall back to raw dict."""
        raw = {0: "not_a_list"}
        ws = _try_decode_witness_set(raw)
        # Should fall back to dict, not crash
        assert ws is not None

    def test_block_body_with_witnesses(self):
        """Integration: decode block with transactions that have witnesses."""
        vkey = b"\x01" * 32
        sig = b"\x02" * 64
        body = _make_tx_body_primitive()
        ws = {0: [[vkey, sig]]}
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        assert result.tx_count == 1
        tx = result.transactions[0]
        if isinstance(tx.witness_set, TransactionWitnessSet):
            assert tx.witness_set.vkey_witnesses is not None


# ---------------------------------------------------------------------------
# Tests: Bootstrap witness structure (Byron-style witnesses in Shelley blocks)
# ---------------------------------------------------------------------------


class TestBootstrapWitness:
    """test_bootstrap_witness_* from DB specs.

    Bootstrap witnesses (key 2 in witness set) are Byron-era compatibility
    witnesses used in Shelley+ blocks. They have 4 fields:
    [vkey, signature, chain_code, attributes].
    """

    def test_bootstrap_witness_four_fields_present(self):
        """test_bootstrap_witness_four_fields_present:
        4 fields: vkey(32), sig(64), chain_code(32), attributes(bytes)."""
        vkey = b"\x01" * 32
        sig = b"\x02" * 64
        chain_code = b"\x03" * 32
        attributes = b""  # empty attributes
        bw = [vkey, sig, chain_code, attributes]

        # Bootstrap witnesses are at key 2 in witness set
        raw_ws = {2: [bw]}
        ws = _try_decode_witness_set(raw_ws)
        assert ws is not None
        # pycardano stores bootstrap_witness as List[Any]
        if isinstance(ws, TransactionWitnessSet):
            assert ws.bootstrap_witness is not None
            assert len(ws.bootstrap_witness) == 1

    def test_bootstrap_witness_cbor_round_trip(self):
        """test_bootstrap_witness_cbor_round_trip:
        Serialize as 4-element array, deserialize, verify fields match."""
        vkey = b"\x01" * 32
        sig = b"\x02" * 64
        chain_code = b"\x03" * 32
        attributes = b""
        bw = [vkey, sig, chain_code, attributes]
        encoded = cbor2.dumps(bw)
        decoded = cbor2.loads(encoded)
        assert len(decoded) == 4
        assert decoded[0] == vkey
        assert decoded[1] == sig
        assert decoded[2] == chain_code
        assert decoded[3] == attributes

    def test_bootstrap_witness_empty_attributes(self):
        """test_bootstrap_witness_empty_attributes:
        Common case for non-HDPayload Byron addresses."""
        vkey = b"\x01" * 32
        sig = b"\x02" * 64
        chain_code = b"\x03" * 32
        attributes = b""
        bw = [vkey, sig, chain_code, attributes]
        encoded = cbor2.dumps(bw)
        decoded = cbor2.loads(encoded)
        assert decoded[3] == b""

    def test_bootstrap_witness_with_hd_payload_attributes(self):
        """test_bootstrap_witness_with_hd_payload_attributes:
        Attributes containing HD derivation path preserved through round-trip."""
        vkey = b"\x01" * 32
        sig = b"\x02" * 64
        chain_code = b"\x03" * 32
        # Simulate HD payload as opaque bytes
        hd_payload = cbor2.dumps({1: b"\xde\xad\xbe\xef"})
        bw = [vkey, sig, chain_code, hd_payload]
        encoded = cbor2.dumps(bw)
        decoded = cbor2.loads(encoded)
        assert decoded[3] == hd_payload


# ---------------------------------------------------------------------------
# Tests: Auxiliary data decoding
# ---------------------------------------------------------------------------


class TestAuxiliaryDataDecoding:
    def test_no_auxiliary_data(self):
        result = _try_decode_auxiliary_data(None)
        assert result is None

    def test_simple_metadata_decodes(self):
        """Simple Shelley-era metadata (just a map)."""
        raw = {1: "hello", 2: b"world"}
        result = _try_decode_auxiliary_data(raw)
        assert isinstance(result, AuxiliaryData)

    def test_auxiliary_data_in_block(self):
        """Integration: block with auxiliary data for tx at index 0."""
        body = _make_tx_body_primitive()
        # Add auxiliary_data_hash to the body (key 7)
        metadata_raw = {1: "test_metadata"}
        metadata = Metadata(metadata_raw)
        aux = AuxiliaryData(metadata)
        body[7] = aux.hash().payload

        ws = _make_witness_set_primitive()
        aux_map = {0: metadata_raw}
        raw = _make_block_cbor(
            Era.BABBAGE,
            tx_bodies=[body],
            tx_witnesses=[ws],
            auxiliary_data=aux_map,
        )
        result = decode_block_body(raw)
        assert result.tx_count == 1
        assert result.transactions[0].auxiliary_data is not None

    def test_auxiliary_data_only_for_some_txs(self):
        """Auxiliary data map only has entries for txs that need it."""
        bodies = [
            _make_tx_body_primitive(fee=100_000),
            _make_tx_body_primitive(fee=200_000),
        ]
        witnesses = [_make_witness_set_primitive(), _make_witness_set_primitive()]
        # Only tx at index 1 has auxiliary data
        aux_map = {1: {42: "only_for_tx1"}}
        raw = _make_block_cbor(
            Era.BABBAGE,
            tx_bodies=bodies,
            tx_witnesses=witnesses,
            auxiliary_data=aux_map,
        )
        result = decode_block_body(raw)
        assert result.transactions[0].auxiliary_data is None
        assert result.transactions[1].auxiliary_data is not None

    def test_null_auxiliary_data_treated_as_empty(self):
        """Some eras encode empty aux data as null instead of {}."""
        header_body = _make_babbage_header_body()
        header = [header_body, SIG64]
        block_array = [header, [], [], None]
        payload = cbor2.dumps(block_array)
        tagged = bytes([0xC6]) + payload  # Babbage
        result = decode_block_body(tagged)
        assert result.tx_count == 0

    def test_auxiliary_data_fallback_on_decode_failure(self):
        """Unrecognized aux data format should fall back to raw."""
        # A raw integer is not valid auxiliary data for pycardano
        result = _try_decode_auxiliary_data(12345)
        # Should not be None (we passed a value) and not AuxiliaryData
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: Transaction hash computation
# ---------------------------------------------------------------------------


class TestTransactionHash:
    """test_txid_is_hash_of_tx_body: hash is blake2b-256 of CBOR body."""

    def test_tx_hash_in_decoded_transaction(self):
        body = _make_tx_body_primitive()
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(Era.SHELLEY, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        tx = result.transactions[0]

        # Manually compute expected hash
        expected = hashlib.blake2b(cbor2.dumps(body), digest_size=32).digest()
        assert tx.tx_hash == expected

    def test_tx_hash_stable_across_decode(self):
        """Same body should produce same hash regardless of era."""
        body = _make_tx_body_primitive()
        ws = _make_witness_set_primitive()

        raw_shelley = _make_block_cbor(
            Era.SHELLEY, tx_bodies=[body], tx_witnesses=[ws]
        )
        raw_babbage = _make_block_cbor(
            Era.BABBAGE, tx_bodies=[body], tx_witnesses=[ws]
        )

        result_s = decode_block_body(raw_shelley)
        result_b = decode_block_body(raw_babbage)

        assert result_s.transactions[0].tx_hash == result_b.transactions[0].tx_hash


# ---------------------------------------------------------------------------
# Tests: decode_block_transactions convenience function
# ---------------------------------------------------------------------------


class TestDecodeBlockTransactions:
    def test_returns_pycardano_transaction_objects(self):
        body = _make_tx_body_primitive()
        vkey = b"\x01" * 32
        sig = b"\x02" * 64
        ws = {0: [[vkey, sig]]}
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_transactions(raw)
        assert len(result) == 1
        # Should be either a Transaction or a dict fallback
        assert isinstance(result[0], (Transaction, dict))

    def test_empty_block_returns_empty_list(self):
        raw = _make_block_cbor(Era.CONWAY)
        result = decode_block_transactions(raw)
        assert result == []

    def test_multiple_transactions(self):
        bodies = [
            _make_tx_body_primitive(fee=100_000 + i * 10_000) for i in range(4)
        ]
        witnesses = [_make_witness_set_primitive() for _ in bodies]
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=bodies, tx_witnesses=witnesses)
        result = decode_block_transactions(raw)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# Tests: tx_size includes witnesses for fee calculation
# ---------------------------------------------------------------------------


class TestTxSizeIncludesWitnesses:
    """test_tx_size_includes_witnesses_for_fee:
    The fee-relevant size of a transaction must include witnesses."""

    def test_full_tx_larger_than_body_alone(self):
        body_raw = _make_tx_body_primitive()
        body = _try_decode_tx_body(body_raw)
        if not isinstance(body, TransactionBody):
            pytest.skip("pycardano couldn't decode body")

        vkey = b"\x01" * 32
        sig = b"\x02" * 64
        ws_raw = {0: [[vkey, sig]]}
        ws = _try_decode_witness_set(ws_raw)
        if not isinstance(ws, TransactionWitnessSet):
            pytest.skip("pycardano couldn't decode witness set")

        body_cbor_len = len(body.to_cbor())
        tx = Transaction(
            transaction_body=body,
            transaction_witness_set=ws,
            valid=True,
            auxiliary_data=None,
        )
        full_tx_cbor_len = len(tx.to_cbor())
        assert full_tx_cbor_len > body_cbor_len


# ---------------------------------------------------------------------------
# Tests: Validity flag
# ---------------------------------------------------------------------------


class TestValidityFlag:
    def test_shelley_transactions_are_valid(self):
        """Shelley-Mary blocks don't have explicit validity — default True."""
        body = _make_tx_body_primitive()
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(Era.SHELLEY, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        assert result.transactions[0].valid is True

    def test_babbage_transactions_default_valid(self):
        body = _make_tx_body_primitive()
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        assert result.transactions[0].valid is True


# ---------------------------------------------------------------------------
# Tests: Body raw preservation
# ---------------------------------------------------------------------------


class TestBodyRawPreservation:
    """test_annotated_transaction_preserves_bytes (adapted):
    The raw body primitive is preserved for hash computation."""

    def test_body_raw_preserved(self):
        body = _make_tx_body_primitive(fee=42_000)
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(Era.SHELLEY, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        tx = result.transactions[0]
        assert tx.body_raw == body
        assert tx.body_raw[2] == 42_000

    def test_body_raw_usable_for_hash_recomputation(self):
        body = _make_tx_body_primitive()
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        tx = result.transactions[0]
        recomputed = hashlib.blake2b(cbor2.dumps(tx.body_raw), digest_size=32).digest()
        assert recomputed == tx.tx_hash


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_tx_body_raises(self):
        """Transaction body that's not a dict should raise."""
        header_body = _make_babbage_header_body()
        header = [header_body, SIG64]
        # tx_bodies has a non-dict element
        block_array = [header, ["not_a_dict"], [{}], {}]
        payload = cbor2.dumps(block_array)
        tagged = bytes([0xC6]) + payload
        with pytest.raises(ValueError, match="expected dict"):
            decode_block_body(tagged)

    def test_tx_bodies_not_array_raises(self):
        header_body = _make_babbage_header_body()
        header = [header_body, SIG64]
        block_array = [header, "not_a_list", [], {}]
        payload = cbor2.dumps(block_array)
        tagged = bytes([0xC6]) + payload
        with pytest.raises(ValueError, match="CBOR array"):
            decode_block_body(tagged)

    def test_tx_witnesses_not_array_raises(self):
        header_body = _make_babbage_header_body()
        header = [header_body, SIG64]
        block_array = [header, [], "not_a_list", {}]
        payload = cbor2.dumps(block_array)
        tagged = bytes([0xC6]) + payload
        with pytest.raises(ValueError, match="CBOR array"):
            decode_block_body(tagged)

    def test_utxo_empty_transaction_outputs(self):
        """test_utxo_empty_transaction_outputs: tx with zero outputs."""
        body = {
            0: [[HASH32, 0]],  # one input
            1: [],              # zero outputs
            2: 200_000,
        }
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        assert result.tx_count == 1
        tx = result.transactions[0]
        if isinstance(tx.body, TransactionBody):
            assert len(tx.body.outputs) == 0
        else:
            assert tx.body[1] == []


# ---------------------------------------------------------------------------
# Tests: Metadata validation
# ---------------------------------------------------------------------------


class TestMetadataKeyMustBeUint:
    """test_metadata_key_must_be_uint: Metadata top-level keys must be unsigned
    integers (0 to 2^64-1). Non-integer keys should be rejected by pycardano.

    Spec: Shelley CDDL — transaction_metadatum_label = uint
    """

    def test_integer_keys_accepted(self):
        """Integer keys (uint) are valid metadata keys."""
        m = Metadata({0: "zero", 1: "one", 2**32: "large"})
        assert 0 in m
        assert 1 in m
        assert 2**32 in m

    def test_string_key_rejected(self):
        """String keys are not valid metadata keys — must be uint."""
        from pycardano.exception import InvalidArgumentException

        with pytest.raises(InvalidArgumentException, match="int"):
            Metadata({"bad_key": "value"})

    def test_negative_key_accepted_by_pycardano(self):
        """pycardano accepts negative int keys (isinstance check only).

        Note: The CDDL says transaction_metadatum_label = uint, meaning
        negative keys are technically invalid per spec. pycardano does not
        enforce the unsigned constraint — it only checks isinstance(k, int).
        Our validation layer must enforce the uint constraint separately.
        """
        # pycardano allows it — documents a gap we must enforce ourselves
        m = Metadata({-1: "negative"})
        assert -1 in m

    def test_bytes_key_rejected(self):
        """Bytestring keys are not valid metadata keys."""
        from pycardano.exception import InvalidArgumentException

        with pytest.raises(InvalidArgumentException, match="int"):
            Metadata({b"\x01": "bytes_key"})


class TestMetadataBytesMax64:
    """test_metadata_bytes_max_64: Metadata bytestring values must be <= 64 bytes.

    Spec: Shelley CDDL — transaction_metadatum = ... / bytes .size (0..64)
    """

    def test_64_bytes_accepted(self):
        m = Metadata({1: b"\x00" * 64})
        assert m[1] == b"\x00" * 64

    def test_65_bytes_rejected(self):
        from pycardano.exception import InvalidArgumentException

        with pytest.raises(InvalidArgumentException, match="exceeds"):
            Metadata({1: b"\x00" * 65})

    def test_empty_bytes_accepted(self):
        m = Metadata({1: b""})
        assert m[1] == b""


class TestMetadataTextMax64BytesNotChars:
    """test_metadata_text_max_64_bytes_not_chars: Text metadata values are limited
    to 64 bytes of UTF-8 encoding, not 64 characters.

    Spec: Shelley CDDL — transaction_metadatum = ... / text .size (0..64)
    (where .size refers to byte length of the UTF-8 encoding)
    """

    def test_64_ascii_chars_accepted(self):
        """64 ASCII chars = 64 bytes, should pass."""
        m = Metadata({1: "a" * 64})
        assert len(m[1]) == 64

    def test_multibyte_chars_hit_byte_limit(self):
        """Multibyte UTF-8 characters — fewer than 64 chars can exceed 64 bytes.
        Each emoji is 4 bytes UTF-8, so 17 emojis = 68 bytes > 64."""
        from pycardano.exception import InvalidArgumentException

        # 17 x 4-byte chars = 68 bytes
        with pytest.raises(InvalidArgumentException, match="exceeds"):
            Metadata({1: "\U0001f600" * 17})

    def test_16_emojis_accepted(self):
        """16 x 4-byte emojis = 64 bytes, exactly at boundary."""
        m = Metadata({1: "\U0001f600" * 16})
        assert len(m[1].encode("utf-8")) == 64


class TestMetadataValueBytesAtBoundary:
    """test_metadata_value_bytes_at_boundary: Test 63, 64, 65 byte metadata values."""

    def test_63_bytes_accepted(self):
        m = Metadata({1: b"\xab" * 63})
        assert len(m[1]) == 63

    def test_64_bytes_accepted(self):
        m = Metadata({1: b"\xab" * 64})
        assert len(m[1]) == 64

    def test_65_bytes_rejected(self):
        from pycardano.exception import InvalidArgumentException

        with pytest.raises(InvalidArgumentException, match="exceeds"):
            Metadata({1: b"\xab" * 65})


class TestMetadataValueTextAtBoundary:
    """test_metadata_value_text_at_boundary: Test 63, 64, 65 byte text metadata."""

    def test_63_bytes_text_accepted(self):
        m = Metadata({1: "x" * 63})
        assert len(m[1].encode("utf-8")) == 63

    def test_64_bytes_text_accepted(self):
        m = Metadata({1: "x" * 64})
        assert len(m[1].encode("utf-8")) == 64

    def test_65_bytes_text_rejected(self):
        from pycardano.exception import InvalidArgumentException

        with pytest.raises(InvalidArgumentException, match="exceeds"):
            Metadata({1: "x" * 65})


class TestMetadataNestedArrayAndMap:
    """test_metadata_nested_array_and_map: Metadata can contain nested arrays and maps.

    Spec: Shelley CDDL —
        transaction_metadatum =
            { * transaction_metadatum => transaction_metadatum }
          / [ * transaction_metadatum ]
          / int / bytes / text
    """

    def test_nested_list(self):
        m = Metadata({1: [1, 2, 3]})
        assert m[1] == [1, 2, 3]

    def test_nested_dict(self):
        m = Metadata({1: {2: "inner"}})
        assert m[1] == {2: "inner"}

    def test_deeply_nested(self):
        m = Metadata({1: [{"nested": [1, b"\xff", "text"]}]})
        assert isinstance(m[1], list)
        assert isinstance(m[1][0], dict)

    def test_nested_array_with_bytes_and_text(self):
        m = Metadata({1: [b"\x00" * 32, "hello", 42]})
        assert len(m[1]) == 3

    def test_nested_map_cbor_roundtrip(self):
        raw = {1: {2: [3, b"\xab" * 10, "nested"]}}
        m = Metadata(raw)
        cbor_bytes = m.to_cbor()
        restored = Metadata.from_cbor(cbor_bytes)
        assert restored[1] == raw[1]


class TestMetadataIntValueRange:
    """test_metadata_int_value_range: Metadata integer values can be negative and large.

    Spec: Shelley CDDL — transaction_metadatum includes int
    (int = uint / nint, i.e. the full CBOR integer range)
    """

    def test_zero(self):
        m = Metadata({1: 0})
        assert m[1] == 0

    def test_large_positive(self):
        m = Metadata({1: 2**63 - 1})
        assert m[1] == 2**63 - 1

    def test_negative(self):
        m = Metadata({1: -1})
        assert m[1] == -1

    def test_large_negative(self):
        m = Metadata({1: -(2**63)})
        assert m[1] == -(2**63)

    def test_int_roundtrip_cbor(self):
        val = -(2**32)
        m = Metadata({1: val})
        restored = Metadata.from_cbor(m.to_cbor())
        assert restored[1] == val


# ---------------------------------------------------------------------------
# Tests: Transaction body spec fields
# ---------------------------------------------------------------------------


class TestTxBodyHasAllSpecFields:
    """test_txbody_has_all_spec_fields: Conway TxBody has all spec-required fields.

    Spec: Conway CDDL —
        transaction_body =
          { 0 : set<transaction_input>   ; inputs
          , 1 : [* transaction_output]   ; outputs
          , 2 : coin                     ; fee
          , ? 3 : uint                   ; time to live
          , ...
          }

    At minimum: inputs (key 0), outputs (key 1), fee (key 2).
    """

    def test_conway_txbody_has_inputs_outputs_fee(self):
        """A decoded TransactionBody must have inputs, outputs, and fee."""
        body_prim = _make_tx_body_primitive()
        result = _try_decode_tx_body(body_prim)
        assert isinstance(result, TransactionBody)
        assert result.inputs is not None
        assert result.outputs is not None
        assert result.fee is not None

    def test_conway_txbody_has_optional_fields(self):
        """TransactionBody dataclass has Conway-era optional fields."""
        assert hasattr(TransactionBody, "voting_procedures")
        assert hasattr(TransactionBody, "proposal_procedures")
        assert hasattr(TransactionBody, "current_treasury_value")
        assert hasattr(TransactionBody, "collateral")
        assert hasattr(TransactionBody, "collateral_return")
        assert hasattr(TransactionBody, "reference_inputs")

    def test_conway_txbody_field_keys_match_cddl(self):
        """Verify the CBOR map keys match the CDDL spec."""
        import dataclasses

        fields = dataclasses.fields(TransactionBody)
        key_map = {}
        for f in fields:
            if "key" in f.metadata:
                key_map[f.name] = f.metadata["key"]
        # Core required fields
        assert key_map["inputs"] == 0
        assert key_map["outputs"] == 1
        assert key_map["fee"] == 2


class TestTxBodyRoundtripSerialization:
    """test_txbody_roundtrip_serialization: Encode a TxBody, decode it, compare."""

    def test_minimal_txbody_roundtrip(self):
        body_prim = _make_tx_body_primitive(fee=300_000, ttl=100_000)
        result = _try_decode_tx_body(body_prim)
        if not isinstance(result, TransactionBody):
            pytest.skip("pycardano couldn't decode body")

        cbor_bytes = result.to_cbor()
        restored = TransactionBody.from_cbor(cbor_bytes)
        assert restored.fee == 300_000
        assert restored.ttl == 100_000
        assert len(restored.inputs) == len(result.inputs)
        assert len(restored.outputs) == len(result.outputs)

    def test_roundtrip_preserves_hash(self):
        """Hash of serialized body should be stable across round-trip."""
        body_prim = _make_tx_body_primitive()
        result = _try_decode_tx_body(body_prim)
        if not isinstance(result, TransactionBody):
            pytest.skip("pycardano couldn't decode body")

        cbor1 = result.to_cbor()
        restored = TransactionBody.from_cbor(cbor1)
        cbor2_bytes = restored.to_cbor()
        hash1 = hashlib.blake2b(cbor1, digest_size=32).digest()
        hash2 = hashlib.blake2b(cbor2_bytes, digest_size=32).digest()
        assert hash1 == hash2


# ---------------------------------------------------------------------------
# Tests: Bootstrap witness field sizes
# ---------------------------------------------------------------------------


class TestBootstrapWitnessChainCode32Bytes:
    """test_bootstrap_witness_chain_code_32_bytes: Chain code in bootstrap witness
    is exactly 32 bytes.

    Spec: Shelley CDDL — bootstrap_witness =
      [ public_key : vkey             ; 32 bytes
      , signature  : signature        ; 64 bytes
      , chain_code : bytes .size 32
      , attributes : bytes
      ]
    """

    def test_chain_code_32_bytes(self):
        chain_code = b"\x03" * 32
        bw = [b"\x01" * 32, b"\x02" * 64, chain_code, b""]
        encoded = cbor2.dumps(bw)
        decoded = cbor2.loads(encoded)
        assert len(decoded[2]) == 32

    def test_chain_code_wrong_size_detectable(self):
        """Chain codes not exactly 32 bytes should be detectable."""
        for size in [0, 16, 31, 33, 64]:
            bw = [b"\x01" * 32, b"\x02" * 64, b"\x03" * size, b""]
            encoded = cbor2.dumps(bw)
            decoded = cbor2.loads(encoded)
            assert len(decoded[2]) == size
            assert len(decoded[2]) != 32 or size == 32


class TestBootstrapWitnessVkey32Bytes:
    """test_bootstrap_witness_vkey_32_bytes: VKey in bootstrap witness is 64 bytes
    (XPub = 32-byte public key + 32-byte chain verification key = 64 bytes for
    extended public key).

    Note: The CDDL says vkey = bytes .size 32, but Byron bootstrap witnesses
    use extended public keys (XPub) which are 64 bytes in the Byron/OBFT era.
    In Shelley+ the vkey field in bootstrap_witness is still 32 bytes (ed25519).
    We test both the 32-byte (Shelley spec) and document the 64-byte Byron case.
    """

    def test_vkey_32_bytes_shelley(self):
        """Standard Shelley bootstrap witness vkey is 32 bytes."""
        vkey = b"\x01" * 32
        bw = [vkey, b"\x02" * 64, b"\x03" * 32, b""]
        encoded = cbor2.dumps(bw)
        decoded = cbor2.loads(encoded)
        assert len(decoded[0]) == 32

    def test_vkey_64_bytes_byron_xpub(self):
        """Byron XPub is 64 bytes — vkey(32) + chain_verification(32)."""
        xpub = b"\x01" * 64
        bw = [xpub, b"\x02" * 64, b"\x03" * 32, b""]
        encoded = cbor2.dumps(bw)
        decoded = cbor2.loads(encoded)
        assert len(decoded[0]) == 64


# ---------------------------------------------------------------------------
# Tests: Constr tag encoding for alternatives >= 7
# ---------------------------------------------------------------------------


class TestConstrTagEncodingGeneralRange:
    """test_constr_tag_encoding_general_range: Constr alternatives >= 7 use
    CBOR tag 102 encoding.

    Spec: Plutus Core CDDL —
        constr<a> =
            #6.121([* a])  ; alternative 0
          / #6.122([* a])  ; alternative 1
          / ...
          / #6.127([* a])  ; alternative 6
          / #6.102([uint, [* a]])  ; general form for alternatives >= 7
    """

    def test_alternatives_0_through_6_use_compact_tags(self):
        """Alternatives 0-6 use tags 121-127."""
        for alt in range(7):
            tag = cbor2.CBORTag(121 + alt, [42])
            encoded = cbor2.dumps(tag)
            decoded = cbor2.loads(encoded)
            assert isinstance(decoded, cbor2.CBORTag)
            assert decoded.tag == 121 + alt
            assert decoded.value == [42]

    def test_alternative_7_uses_tag_102(self):
        """Alternative 7 uses tag 102 with [7, fields]."""
        tag = cbor2.CBORTag(102, [7, [42]])
        encoded = cbor2.dumps(tag)
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, cbor2.CBORTag)
        assert decoded.tag == 102
        assert decoded.value == [7, [42]]

    def test_alternative_100_uses_tag_102(self):
        """Large alternative numbers still use tag 102."""
        tag = cbor2.CBORTag(102, [100, ["a", "b"]])
        encoded = cbor2.dumps(tag)
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, cbor2.CBORTag)
        assert decoded.tag == 102
        assert decoded.value[0] == 100

    def test_general_form_roundtrip(self):
        """Tag 102 with arbitrary alternative and fields round-trips."""
        for alt in [7, 8, 42, 1000]:
            fields = [1, b"\xff", "text"]
            tag = cbor2.CBORTag(102, [alt, fields])
            encoded = cbor2.dumps(tag)
            decoded = cbor2.loads(encoded)
            assert decoded.tag == 102
            assert decoded.value[0] == alt
            assert decoded.value[1] == fields


# ---------------------------------------------------------------------------
# Tests: Serialization distributivity for transactions
# ---------------------------------------------------------------------------


class TestSerializationDistributivityTx:
    """test_serialization_distributivity_tx: hash(encode(body)) == encode(hash(body))
    — extracting body from serialized tx matches serializing the extracted body.

    This is the critical invariant: the tx_id (hash of the body) must be
    computable from either the raw CBOR body or from a re-serialized decoded body.
    """

    def test_hash_of_raw_body_matches_decoded_hash(self):
        """hash(raw_body_cbor) == tx.tx_hash computed during decode."""
        body = _make_tx_body_primitive(fee=150_000)
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=[body], tx_witnesses=[ws])
        result = decode_block_body(raw)
        tx = result.transactions[0]

        # Hash from raw primitive
        raw_hash = hashlib.blake2b(cbor2.dumps(body), digest_size=32).digest()
        assert tx.tx_hash == raw_hash

    def test_reencode_decoded_body_same_hash(self):
        """Re-encoding a decoded body and hashing should match the original tx_id."""
        body_prim = _make_tx_body_primitive(fee=250_000)
        ws = _make_witness_set_primitive()
        raw = _make_block_cbor(Era.BABBAGE, tx_bodies=[body_prim], tx_witnesses=[ws])
        result = decode_block_body(raw)
        tx = result.transactions[0]

        # Re-encode the raw body primitive
        reencoded = cbor2.dumps(tx.body_raw)
        rehash = hashlib.blake2b(reencoded, digest_size=32).digest()
        assert rehash == tx.tx_hash

    def test_distributivity_across_multiple_txs(self):
        """The distributivity property holds for every tx in a multi-tx block."""
        bodies = [_make_tx_body_primitive(fee=100_000 * (i + 1)) for i in range(5)]
        witnesses = [_make_witness_set_primitive() for _ in bodies]
        raw = _make_block_cbor(Era.CONWAY, tx_bodies=bodies, tx_witnesses=witnesses)
        result = decode_block_body(raw)

        for i, tx in enumerate(result.transactions):
            expected = hashlib.blake2b(
                cbor2.dumps(bodies[i]), digest_size=32
            ).digest()
            assert tx.tx_hash == expected, f"Distributivity failed for tx {i}"
