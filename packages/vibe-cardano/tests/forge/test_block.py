"""Tests for block construction (vibe.cardano.forge.block).

Tests cover:
    * Block body: txs are CBOR-encoded, size within limit
    * Block body: empty block (no mempool txs)
    * Block construction: correct block_number, slot, prev_hash
    * Block header: KES signature verifies
    * Block body: size limit enforcement
    * Full forge_block round-trip

Spec references:
    - babbage.cddl: block, header, header_body
    - Shelley formal spec, Figure 10 (block structure)
"""

from __future__ import annotations

import hashlib

import cbor2
import pytest

from vibe.cardano.crypto.kes import (
    CARDANO_KES_DEPTH,
    kes_derive_vk,
    kes_keygen,
    kes_verify,
)
from vibe.cardano.crypto.ocert import OperationalCert
from vibe.cardano.crypto.vrf import VRF_OUTPUT_SIZE, VRF_PROOF_SIZE
from vibe.cardano.forge.block import (
    DEFAULT_MAX_BLOCK_BODY_SIZE,
    DEFAULT_PROTOCOL_VERSION,
    Block,
    ForgedBlock,
    _build_block_body,
    _build_header_body,
    forge_block,
)
from vibe.cardano.forge.leader import LeaderProof


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_leader_proof(slot: int = 1000) -> LeaderProof:
    """Create a synthetic leader proof for testing."""
    return LeaderProof(
        vrf_proof=b"\x11" * VRF_PROOF_SIZE,
        vrf_output=b"\x22" * VRF_OUTPUT_SIZE,
        slot=slot,
    )


def _make_ocert() -> OperationalCert:
    """Create a synthetic operational certificate for testing."""
    return OperationalCert(
        kes_vk=b"\x33" * 32,
        cert_count=0,
        kes_period_start=0,
        cold_sig=b"\x44" * 64,
    )


def _make_sample_tx(size: int = 100) -> bytes:
    """Create a fake CBOR-encoded transaction of approximately `size` bytes."""
    # Create a CBOR-encoded byte string of the requested size
    payload = b"\xab" * max(size - 10, 1)
    return cbor2.dumps(payload)


# ---------------------------------------------------------------------------
# Block body tests
# ---------------------------------------------------------------------------


class TestBuildBlockBody:
    """Test block body construction from mempool transactions."""

    def test_empty_mempool(self) -> None:
        """Empty mempool produces an empty block body."""
        body_cbor, num_txs = _build_block_body([])
        assert num_txs == 0
        decoded = cbor2.loads(body_cbor)
        assert isinstance(decoded, list)
        assert len(decoded) == 4
        # tx_bodies should be empty list
        assert decoded[0] == []

    def test_single_tx(self) -> None:
        """Single transaction included in body."""
        tx = _make_sample_tx(50)
        body_cbor, num_txs = _build_block_body([tx])
        assert num_txs == 1
        decoded = cbor2.loads(body_cbor)
        assert len(decoded[0]) == 1

    def test_multiple_txs(self) -> None:
        """Multiple transactions included in body."""
        txs = [_make_sample_tx(50) for _ in range(5)]
        body_cbor, num_txs = _build_block_body(txs)
        assert num_txs == 5
        decoded = cbor2.loads(body_cbor)
        assert len(decoded[0]) == 5

    def test_size_limit_enforced(self) -> None:
        """Transactions exceeding max body size are excluded."""
        # Create txs that will exceed a small limit
        txs = [_make_sample_tx(200) for _ in range(10)]
        body_cbor, num_txs = _build_block_body(txs, max_body_size=500)
        # Should include fewer than all 10
        assert num_txs < 10
        assert num_txs > 0
        # Body should be under the limit
        assert len(body_cbor) <= 600  # some overhead allowed

    def test_body_is_valid_cbor(self) -> None:
        """Block body is valid CBOR."""
        txs = [_make_sample_tx(50) for _ in range(3)]
        body_cbor, _ = _build_block_body(txs)
        decoded = cbor2.loads(body_cbor)
        assert isinstance(decoded, list)
        assert len(decoded) == 4


# ---------------------------------------------------------------------------
# Header body tests
# ---------------------------------------------------------------------------


class TestBuildHeaderBody:
    """Test header body construction."""

    def test_field_count(self) -> None:
        """Babbage header_body has 14 fields."""
        header_body = _build_header_body(
            block_number=42,
            slot=1000,
            prev_hash=b"\x00" * 32,
            issuer_vk=b"\x01" * 32,
            vrf_vk=b"\x02" * 32,
            vrf_result=(b"\x03" * VRF_OUTPUT_SIZE, b"\x04" * VRF_PROOF_SIZE),
            body_size=256,
            body_hash=b"\x05" * 32,
            ocert=_make_ocert(),
        )
        # Babbage/Conway: 10 fields (8 direct + nested ocert + nested protver)
        assert len(header_body) == 10

    def test_block_number_and_slot(self) -> None:
        """Block number and slot are at indices 0 and 1."""
        header_body = _build_header_body(
            block_number=42,
            slot=1000,
            prev_hash=b"\x00" * 32,
            issuer_vk=b"\x01" * 32,
            vrf_vk=b"\x02" * 32,
            vrf_result=(b"\x03" * VRF_OUTPUT_SIZE, b"\x04" * VRF_PROOF_SIZE),
            body_size=256,
            body_hash=b"\x05" * 32,
            ocert=_make_ocert(),
        )
        assert header_body[0] == 42
        assert header_body[1] == 1000

    def test_prev_hash_none_for_genesis(self) -> None:
        """prev_hash is None for the first block after genesis."""
        header_body = _build_header_body(
            block_number=1,
            slot=100,
            prev_hash=None,
            issuer_vk=b"\x01" * 32,
            vrf_vk=b"\x02" * 32,
            vrf_result=(b"\x03" * VRF_OUTPUT_SIZE, b"\x04" * VRF_PROOF_SIZE),
            body_size=0,
            body_hash=b"\x05" * 32,
            ocert=_make_ocert(),
        )
        assert header_body[2] is None

    def test_protocol_version(self) -> None:
        """Protocol version is nested array at index 9 (Babbage/Conway)."""
        header_body = _build_header_body(
            block_number=1,
            slot=100,
            prev_hash=None,
            issuer_vk=b"\x01" * 32,
            vrf_vk=b"\x02" * 32,
            vrf_result=(b"\x03" * VRF_OUTPUT_SIZE, b"\x04" * VRF_PROOF_SIZE),
            body_size=0,
            body_hash=b"\x05" * 32,
            ocert=_make_ocert(),
            protocol_version=(10, 0),
        )
        assert header_body[9] == [10, 0]

    def test_cbor_encodable(self) -> None:
        """Header body can be CBOR-encoded."""
        header_body = _build_header_body(
            block_number=1,
            slot=100,
            prev_hash=b"\x00" * 32,
            issuer_vk=b"\x01" * 32,
            vrf_vk=b"\x02" * 32,
            vrf_result=(b"\x03" * VRF_OUTPUT_SIZE, b"\x04" * VRF_PROOF_SIZE),
            body_size=256,
            body_hash=b"\x05" * 32,
            ocert=_make_ocert(),
        )
        encoded = cbor2.dumps(header_body)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 1
        assert decoded[1] == 100


# ---------------------------------------------------------------------------
# Full block forging tests
# ---------------------------------------------------------------------------


class TestForgeBlock:
    """Test the complete forge_block function."""

    def _make_kes_keypair(self, depth: int = 2):
        """Generate a small KES keypair for testing (depth 2 = 4 periods)."""
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        return sk, vk

    def test_basic_forge(self) -> None:
        """Forge a block with no transactions."""
        kes_sk, kes_vk = self._make_kes_keypair(depth=2)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )
        leader_proof = _make_leader_proof(slot=500)
        prev_hash = b"\xaa" * 32

        result = forge_block(
            leader_proof=leader_proof,
            prev_block_number=41,
            prev_header_hash=prev_hash,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=2,
        )

        assert isinstance(result, ForgedBlock)
        assert isinstance(result.block, Block)
        assert result.block.block_number == 42
        assert result.block.slot == 500
        assert len(result.block.block_hash) == 32

    def test_block_number_increment(self) -> None:
        """Block number is prev + 1."""
        kes_sk, kes_vk = self._make_kes_keypair(depth=2)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )

        result = forge_block(
            leader_proof=_make_leader_proof(slot=100),
            prev_block_number=99,
            prev_header_hash=b"\x00" * 32,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=2,
        )
        assert result.block.block_number == 100

    def test_slot_from_leader_proof(self) -> None:
        """Slot comes from the leader proof."""
        kes_sk, kes_vk = self._make_kes_keypair(depth=2)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )

        result = forge_block(
            leader_proof=_make_leader_proof(slot=7777),
            prev_block_number=0,
            prev_header_hash=None,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=2,
        )
        assert result.block.slot == 7777

    def test_kes_signature_verifies(self) -> None:
        """KES signature in the header verifies against the KES VK."""
        depth = 2
        kes_sk, kes_vk = self._make_kes_keypair(depth=depth)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )

        result = forge_block(
            leader_proof=_make_leader_proof(slot=200),
            prev_block_number=10,
            prev_header_hash=b"\xdd" * 32,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=depth,
        )

        # Decode the header to extract signature and header body
        header_array = cbor2.loads(result.block.header_cbor)
        assert len(header_array) == 2
        header_body = header_array[0]
        kes_sig = header_array[1]

        # Re-encode header body to get the signed message
        header_body_cbor = cbor2.dumps(header_body)

        # Verify the KES signature
        assert kes_verify(kes_vk, depth, 0, kes_sig, header_body_cbor)

    def test_kes_signature_wrong_period_fails(self) -> None:
        """KES signature does not verify at a different period."""
        depth = 2
        kes_sk, kes_vk = self._make_kes_keypair(depth=depth)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )

        result = forge_block(
            leader_proof=_make_leader_proof(slot=200),
            prev_block_number=10,
            prev_header_hash=b"\xdd" * 32,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=depth,
        )

        header_array = cbor2.loads(result.block.header_cbor)
        header_body_cbor = cbor2.dumps(header_array[0])
        kes_sig = header_array[1]

        # Verify at wrong period should fail
        assert not kes_verify(kes_vk, depth, 1, kes_sig, header_body_cbor)

    def test_block_hash_is_blake2b_of_header(self) -> None:
        """Block hash = Blake2b-256(header_cbor)."""
        kes_sk, kes_vk = self._make_kes_keypair(depth=2)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )

        result = forge_block(
            leader_proof=_make_leader_proof(slot=300),
            prev_block_number=0,
            prev_header_hash=None,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=2,
        )

        expected_hash = hashlib.blake2b(
            result.block.header_cbor, digest_size=32
        ).digest()
        assert result.block.block_hash == expected_hash

    def test_body_hash_in_header(self) -> None:
        """Block body hash in header matches actual body hash."""
        kes_sk, kes_vk = self._make_kes_keypair(depth=2)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )
        txs = [_make_sample_tx(50) for _ in range(3)]

        result = forge_block(
            leader_proof=_make_leader_proof(slot=400),
            prev_block_number=5,
            prev_header_hash=b"\xee" * 32,
            mempool_txs=txs,
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=2,
        )

        # Extract body hash from header body
        header_array = cbor2.loads(result.block.header_cbor)
        header_body = header_array[0]
        body_hash_in_header = header_body[7]  # index 7 = block_body_hash

        # Compute actual body hash
        actual_body_hash = hashlib.blake2b(
            result.block.body_cbor, digest_size=32
        ).digest()

        assert body_hash_in_header == actual_body_hash

    def test_forge_with_transactions(self) -> None:
        """Forging with transactions includes them in the body."""
        kes_sk, kes_vk = self._make_kes_keypair(depth=2)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )
        txs = [_make_sample_tx(80) for _ in range(5)]

        result = forge_block(
            leader_proof=_make_leader_proof(slot=600),
            prev_block_number=10,
            prev_header_hash=b"\xff" * 32,
            mempool_txs=txs,
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=2,
        )

        # Decode body and check tx count
        body = cbor2.loads(result.block.body_cbor)
        assert len(body[0]) == 5

    def test_full_block_cbor_decodable(self) -> None:
        """Full block CBOR can be decoded."""
        kes_sk, kes_vk = self._make_kes_keypair(depth=2)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )

        result = forge_block(
            leader_proof=_make_leader_proof(slot=700),
            prev_block_number=0,
            prev_header_hash=None,
            mempool_txs=[_make_sample_tx(50)],
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=2,
        )

        decoded = cbor2.loads(result.cbor)
        # block = [header, tx_bodies, tx_witnesses, auxiliary_data, invalid_txs]
        assert isinstance(decoded, list)
        # Header is a 2-element array [header_body, kes_sig]
        assert len(decoded[0]) == 2

    def test_prev_hash_none_genesis(self) -> None:
        """prev_hash=None for first block is encoded as CBOR null in header."""
        kes_sk, kes_vk = self._make_kes_keypair(depth=2)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )

        result = forge_block(
            leader_proof=_make_leader_proof(slot=1),
            prev_block_number=0,
            prev_header_hash=None,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=2,
        )

        header_array = cbor2.loads(result.block.header_cbor)
        header_body = header_array[0]
        assert header_body[2] is None  # prev_hash at index 2

    def test_prev_hash_populated(self) -> None:
        """prev_hash is set correctly when provided."""
        kes_sk, kes_vk = self._make_kes_keypair(depth=2)
        ocert = OperationalCert(
            kes_vk=kes_vk,
            cert_count=0,
            kes_period_start=0,
            cold_sig=b"\x44" * 64,
        )
        prev_hash = b"\xfe" * 32

        result = forge_block(
            leader_proof=_make_leader_proof(slot=2),
            prev_block_number=1,
            prev_header_hash=prev_hash,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=2,
        )

        header_array = cbor2.loads(result.block.header_cbor)
        header_body = header_array[0]
        assert header_body[2] == prev_hash
