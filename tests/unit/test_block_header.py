"""Unit tests for block header decoding and hash verification.

Tests use CBOR test vectors constructed by hand with cbor2, following
the CDDL specs from cardano-ledger (shelley.cddl, babbage.cddl).
"""

import hashlib

import cbor2
import pytest

from vibe.cardano.serialization.block import (
    BlockHeader,
    Era,
    OperationalCert,
    ProtocolVersion,
    block_hash,
    decode_block_header,
    decode_block_header_raw,
    detect_era,
)

# ---------------------------------------------------------------------------
# Test vector helpers
# ---------------------------------------------------------------------------

# Dummy 32-byte hash (used for prev_hash, block_body_hash, vrf_vkey, etc.)
HASH32 = b"\xab" * 32

# Dummy 64-byte signature (used for KES signature, op_cert sigma)
SIG64 = b"\xcd" * 64

# Dummy 32-byte vkey
VKEY32 = b"\xef" * 32

# Dummy VRF cert: [output_bytes, proof_bytes] per CDDL $vrf_cert = [bytes, bytes .size 80]
VRF_CERT = [b"\x01" * 32, b"\x02" * 80]


def _make_shelley_header_body() -> list:
    """Construct a Shelley-era header_body as a CBOR array.

    Field order from shelley.cddl:
      block_number, slot, prev_hash, issuer_vkey, vrf_vkey,
      nonce_vrf, leader_vrf, block_body_size, block_body_hash,
      hot_vkey, sequence_number, kes_period, sigma,
      proto_major, proto_minor
    """
    return [
        42,  # block_number
        1000,  # slot
        HASH32,  # prev_hash
        VKEY32,  # issuer_vkey
        VKEY32,  # vrf_vkey
        VRF_CERT,  # nonce_vrf
        VRF_CERT,  # leader_vrf
        512,  # block_body_size
        HASH32,  # block_body_hash
        VKEY32,  # op_cert hot_vkey
        7,  # op_cert sequence_number
        100,  # op_cert kes_period
        SIG64,  # op_cert sigma
        3,  # protocol_version major
        0,  # protocol_version minor
    ]


def _make_babbage_header_body() -> list:
    """Construct a Babbage-era header_body as a CBOR array.

    Field order from babbage.cddl:
      block_number, slot, prev_hash, issuer_vkey, vrf_vkey,
      vrf_result, block_body_size, block_body_hash,
      hot_vkey, sequence_number, kes_period, sigma,
      proto_major, proto_minor
    """
    return [
        99,  # block_number
        5000,  # slot
        HASH32,  # prev_hash
        VKEY32,  # issuer_vkey
        VKEY32,  # vrf_vkey
        VRF_CERT,  # vrf_result (single, replaces nonce + leader)
        1024,  # block_body_size
        HASH32,  # block_body_hash
        VKEY32,  # op_cert hot_vkey
        12,  # op_cert sequence_number
        200,  # op_cert kes_period
        SIG64,  # op_cert sigma
        7,  # protocol_version major
        0,  # protocol_version minor
    ]


def _encode_tagged_block(era_tag: int, block_payload: list) -> bytes:
    """Manually encode a CBOR-tagged block.

    We construct the tagged CBOR bytes by hand because cbor2's encoder
    for low-numbered tags (0-5) applies semantic encoding that doesn't
    match the wire format. For tags >= 6, cbor2.dumps(CBORTag(...)) works
    fine.

    CBOR tag encoding (RFC 7049, major type 6):
      Tag 0-23: single byte 0xc0 + tag_number
    """
    # Encode the tag byte manually
    tag_byte = bytes([0xC0 | era_tag])
    # Encode the payload using cbor2
    payload_cbor = cbor2.dumps(block_payload)
    return tag_byte + payload_cbor


def _wrap_block(era_tag: int, header_body: list) -> bytes:
    """Wrap a header body into a full tagged block CBOR structure.

    block = tag(era, [header, tx_bodies, tx_witnesses, auxiliary_data])
    header = [header_body, body_signature]
    """
    header = [header_body, SIG64]  # [header_body, kes_signature]
    block = [header, [], [], {}]  # empty body, witnesses, auxiliary
    return _encode_tagged_block(era_tag, block)


# ---------------------------------------------------------------------------
# test_detect_era -- known CBOR bytes with era tags 0-7
# ---------------------------------------------------------------------------


class TestDetectEra:
    """Test era detection from CBOR tags."""

    @pytest.mark.parametrize(
        "tag,expected_era",
        [
            (0, Era.BYRON_MAIN),
            (1, Era.BYRON_EBB),
            (2, Era.SHELLEY),
            (3, Era.ALLEGRA),
            (4, Era.MARY),
            (5, Era.ALONZO),
            (6, Era.BABBAGE),
            (7, Era.CONWAY),
        ],
    )
    def test_detect_known_eras(self, tag: int, expected_era: Era):
        """Each tag 0-7 maps to the correct Era enum."""
        # Manually construct tagged CBOR: tag byte + empty array
        tagged = _encode_tagged_block(tag, [])
        assert detect_era(tagged) == expected_era

    def test_detect_unknown_tag(self):
        """Tags outside 0-7 raise ValueError."""
        # Tag 15 = 0xCF followed by empty array
        tagged = bytes([0xCF]) + cbor2.dumps([])
        with pytest.raises(ValueError, match="Unknown era tag"):
            detect_era(tagged)

    def test_detect_untagged_raises(self):
        """Untagged CBOR raises ValueError (not major type 6)."""
        untagged = cbor2.dumps([1, 2, 3])
        with pytest.raises(ValueError, match="Expected CBOR tag"):
            detect_era(untagged)


# ---------------------------------------------------------------------------
# test_decode_shelley_header -- decode a Shelley-format block header
# ---------------------------------------------------------------------------


class TestDecodeShelleyHeader:
    """Test decoding of Shelley-era (two-VRF) block headers."""

    @pytest.fixture
    def shelley_block_cbor(self) -> bytes:
        return _wrap_block(Era.SHELLEY, _make_shelley_header_body())

    def test_decode_fields(self, shelley_block_cbor: bytes):
        """All header fields are correctly extracted."""
        hdr = decode_block_header(shelley_block_cbor)

        assert hdr.block_number == 42
        assert hdr.slot == 1000
        assert hdr.prev_hash == HASH32
        assert hdr.issuer_vkey == VKEY32
        assert hdr.block_body_size == 512
        assert hdr.block_body_hash == HASH32
        assert hdr.era == Era.SHELLEY

    def test_decode_operational_cert(self, shelley_block_cbor: bytes):
        """Operational certificate fields are decoded."""
        hdr = decode_block_header(shelley_block_cbor)

        assert hdr.operational_cert.hot_vkey == VKEY32
        assert hdr.operational_cert.sequence_number == 7
        assert hdr.operational_cert.kes_period == 100
        assert hdr.operational_cert.sigma == SIG64

    def test_decode_protocol_version(self, shelley_block_cbor: bytes):
        """Protocol version is decoded."""
        hdr = decode_block_header(shelley_block_cbor)

        assert hdr.protocol_version.major == 3
        assert hdr.protocol_version.minor == 0

    def test_header_cbor_preserved(self, shelley_block_cbor: bytes):
        """The raw header CBOR is preserved for hash computation."""
        hdr = decode_block_header(shelley_block_cbor)

        assert isinstance(hdr.header_cbor, bytes)
        assert len(hdr.header_cbor) > 0

    def test_null_prev_hash(self):
        """A null prev_hash (genesis block) decodes as None."""
        body = _make_shelley_header_body()
        body[2] = None  # prev_hash = null
        cbor_bytes = _wrap_block(Era.SHELLEY, body)

        hdr = decode_block_header(cbor_bytes)
        assert hdr.prev_hash is None


class TestDecodeAllegraHeader:
    """Allegra uses the same header format as Shelley (two VRF certs)."""

    def test_decode_allegra(self):
        cbor_bytes = _wrap_block(Era.ALLEGRA, _make_shelley_header_body())
        hdr = decode_block_header(cbor_bytes)
        assert hdr.era == Era.ALLEGRA
        assert hdr.slot == 1000


class TestDecodeMaryHeader:
    """Mary uses the same header format as Shelley (two VRF certs)."""

    def test_decode_mary(self):
        cbor_bytes = _wrap_block(Era.MARY, _make_shelley_header_body())
        hdr = decode_block_header(cbor_bytes)
        assert hdr.era == Era.MARY


class TestDecodeAlonzoHeader:
    """Alonzo uses the same header format as Shelley (two VRF certs)."""

    def test_decode_alonzo(self):
        cbor_bytes = _wrap_block(Era.ALONZO, _make_shelley_header_body())
        hdr = decode_block_header(cbor_bytes)
        assert hdr.era == Era.ALONZO


# ---------------------------------------------------------------------------
# test_decode_babbage_header -- single vrf_result format
# ---------------------------------------------------------------------------


class TestDecodeBabbageHeader:
    """Test decoding of Babbage-era (single VRF) block headers."""

    @pytest.fixture
    def babbage_block_cbor(self) -> bytes:
        return _wrap_block(Era.BABBAGE, _make_babbage_header_body())

    def test_decode_fields(self, babbage_block_cbor: bytes):
        hdr = decode_block_header(babbage_block_cbor)

        assert hdr.block_number == 99
        assert hdr.slot == 5000
        assert hdr.prev_hash == HASH32
        assert hdr.issuer_vkey == VKEY32
        assert hdr.block_body_size == 1024
        assert hdr.block_body_hash == HASH32
        assert hdr.era == Era.BABBAGE
        assert hdr.protocol_version == ProtocolVersion(major=7, minor=0)

    def test_decode_operational_cert(self, babbage_block_cbor: bytes):
        hdr = decode_block_header(babbage_block_cbor)

        assert hdr.operational_cert.sequence_number == 12
        assert hdr.operational_cert.kes_period == 200


class TestDecodeConwayHeader:
    """Conway uses the same header format as Babbage (single VRF)."""

    def test_decode_conway(self):
        body = _make_babbage_header_body()
        body[12] = 9  # Conway protocol version major
        cbor_bytes = _wrap_block(Era.CONWAY, body)
        hdr = decode_block_header(cbor_bytes)

        assert hdr.era == Era.CONWAY
        assert hdr.protocol_version.major == 9


# ---------------------------------------------------------------------------
# test_decode_block_header_raw -- header-only decoding
# ---------------------------------------------------------------------------


class TestDecodeBlockHeaderRaw:
    """Test decoding from raw header CBOR (no block wrapper)."""

    def test_shelley_raw(self):
        header_body = _make_shelley_header_body()
        header = [header_body, SIG64]
        header_cbor = cbor2.dumps(header)

        hdr = decode_block_header_raw(header_cbor, Era.SHELLEY)
        assert hdr.slot == 1000
        assert hdr.era == Era.SHELLEY

    def test_babbage_raw(self):
        header_body = _make_babbage_header_body()
        header = [header_body, SIG64]
        header_cbor = cbor2.dumps(header)

        hdr = decode_block_header_raw(header_cbor, Era.BABBAGE)
        assert hdr.slot == 5000
        assert hdr.era == Era.BABBAGE


# ---------------------------------------------------------------------------
# test_block_hash_deterministic -- same header always produces same hash
# ---------------------------------------------------------------------------


class TestBlockHash:
    """Test block hash computation."""

    def test_deterministic(self):
        """Same header bytes always produce the same hash."""
        header_body = _make_shelley_header_body()
        header = [header_body, SIG64]
        header_cbor = cbor2.dumps(header)

        hash1 = block_hash(header_cbor)
        hash2 = block_hash(header_cbor)

        assert hash1 == hash2

    def test_length_32_bytes(self):
        """Block hash is always exactly 32 bytes (Blake2b-256)."""
        header_body = _make_shelley_header_body()
        header = [header_body, SIG64]
        header_cbor = cbor2.dumps(header)

        h = block_hash(header_cbor)
        assert len(h) == 32

    def test_different_headers_different_hashes(self):
        """Different header content produces different hashes."""
        body1 = _make_shelley_header_body()
        body2 = _make_shelley_header_body()
        body2[1] = 9999  # different slot

        h1 = block_hash(cbor2.dumps([body1, SIG64]))
        h2 = block_hash(cbor2.dumps([body2, SIG64]))

        assert h1 != h2

    def test_matches_hashlib_directly(self):
        """block_hash() matches a direct hashlib.blake2b call."""
        data = b"some header cbor bytes"
        expected = hashlib.blake2b(data, digest_size=32).digest()
        assert block_hash(data) == expected

    def test_header_property_matches(self):
        """BlockHeader.hash property matches block_hash() on its header_cbor."""
        cbor_bytes = _wrap_block(Era.BABBAGE, _make_babbage_header_body())
        hdr = decode_block_header(cbor_bytes)

        assert hdr.hash == block_hash(hdr.header_cbor)
        assert len(hdr.hash) == 32


# ---------------------------------------------------------------------------
# Byron -- not yet implemented
# ---------------------------------------------------------------------------


class TestByronBlocks:
    """Byron blocks raise NotImplementedError."""

    def test_byron_main(self):
        cbor_bytes = _encode_tagged_block(0, [[], [], [], {}])
        with pytest.raises(NotImplementedError, match="Byron"):
            decode_block_header(cbor_bytes)

    def test_byron_ebb(self):
        cbor_bytes = _encode_tagged_block(1, [[], [], [], {}])
        with pytest.raises(NotImplementedError, match="Byron"):
            decode_block_header(cbor_bytes)

    def test_byron_raw(self):
        with pytest.raises(NotImplementedError, match="Byron"):
            decode_block_header_raw(b"", Era.BYRON_MAIN)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test error paths for malformed input."""

    def test_not_array_block(self):
        """Block payload that isn't an array raises ValueError."""
        cbor_bytes = _encode_tagged_block(2, "not an array")
        with pytest.raises(ValueError, match="Expected block as CBOR array"):
            decode_block_header(cbor_bytes)

    def test_short_block_array(self):
        """Block array with fewer than 4 elements raises ValueError."""
        cbor_bytes = _encode_tagged_block(2, [[], []])
        with pytest.raises(ValueError, match="Expected block as CBOR array"):
            decode_block_header(cbor_bytes)

    def test_bad_header_array(self):
        """Header that isn't a 2-element array raises ValueError."""
        cbor_bytes = _encode_tagged_block(2, [[1, 2, 3], [], [], {}])
        with pytest.raises(ValueError, match="Expected header as CBOR array of 2"):
            decode_block_header(cbor_bytes)

    def test_short_header_body_shelley(self):
        """Shelley header_body with too few fields raises ValueError."""
        short_body = list(range(10))  # need 15
        cbor_bytes = _wrap_block(Era.SHELLEY, short_body)
        with pytest.raises(ValueError, match="expected >= 15 items"):
            decode_block_header(cbor_bytes)

    def test_short_header_body_babbage(self):
        """Babbage header_body with too few fields raises ValueError."""
        short_body = list(range(10))  # need 14
        cbor_bytes = _wrap_block(Era.BABBAGE, short_body)
        with pytest.raises(ValueError, match="expected >= 14 items"):
            decode_block_header(cbor_bytes)
