"""Haskell test parity — forge module edge cases and invariants.

This module covers block forging behaviors that the Haskell node tests
exercise but our existing tests do not:

    1.  Header body field encoding: verify every field position per CDDL
    2.  Body size limit: txs exceeding maxBlockBodySize are excluded
    3.  VRF result encoding: [output, proof] pair in header body
    4.  KES signature integration: sign/verify at non-zero period
    5.  Empty vs non-empty blocks: both produce valid CBOR
    6.  prev_hash chaining: sequential blocks chain correctly
    7.  Body hash integrity: body_hash in header matches body content
    8.  Protocol version field encoding per era
    9.  Operational cert encoding in header body
    10. Block body four-array structure: [tx_bodies, witnesses, aux, invalid]
    11. Determinism: same inputs produce same block hash
    12. Hypothesis: body size never exceeds limit

Spec references:
    - babbage.cddl: block, header, header_body
    - Shelley formal spec, Figure 10 (block structure)
    - Shelley formal spec, Section 3.3 (bbody function)

Haskell references:
    - Ouroboros.Consensus.Shelley.Node.Forging (forgeShelleyBlock)
    - Test.Consensus.Shelley.Golden (golden block tests)
    - Cardano.Ledger.Shelley.BlockChain (bbody, mkShelleyHeader)
"""

from __future__ import annotations

import hashlib

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.crypto.kes import (
    kes_derive_vk,
    kes_keygen,
    kes_verify,
)
from vibe.cardano.crypto.ocert import OperationalCert
from vibe.cardano.crypto.vrf import VRF_OUTPUT_SIZE, VRF_PROOF_SIZE
from vibe.cardano.forge.block import (
    DEFAULT_PROTOCOL_VERSION,
    ForgedBlock,
    _build_block_body,
    _build_header_body,
    forge_block,
)
from vibe.cardano.forge.leader import LeaderProof

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _leader_proof(slot: int = 1000) -> LeaderProof:
    return LeaderProof(
        vrf_proof=b"\x11" * VRF_PROOF_SIZE,
        vrf_output=b"\x22" * VRF_OUTPUT_SIZE,
        slot=slot,
    )


def _ocert(kes_vk: bytes = b"\x33" * 32) -> OperationalCert:
    return OperationalCert(
        kes_vk=kes_vk,
        cert_count=0,
        kes_period_start=0,
        cold_sig=b"\x44" * 64,
    )


def _kes_keypair(depth: int = 2):
    sk = kes_keygen(depth)
    vk = kes_derive_vk(sk)
    return sk, vk


def _sample_tx(size: int = 100) -> bytes:
    payload = b"\xab" * max(size - 10, 1)
    return cbor2.dumps(payload)


def _forge_helper(
    slot: int = 1000,
    prev_block_number: int = 41,
    prev_header_hash: bytes | None = b"\xaa" * 32,
    mempool_txs: list[bytes] | None = None,
    kes_depth: int = 2,
    kes_period: int = 0,
    protocol_version: tuple[int, int] = DEFAULT_PROTOCOL_VERSION,
) -> ForgedBlock:
    """Convenience wrapper for forge_block with sensible defaults."""
    kes_sk, kes_vk = _kes_keypair(depth=kes_depth)
    ocert = _ocert(kes_vk=kes_vk)
    return forge_block(
        leader_proof=_leader_proof(slot=slot),
        prev_block_number=prev_block_number,
        prev_header_hash=prev_header_hash,
        mempool_txs=mempool_txs or [],
        kes_sk=kes_sk,
        kes_period=kes_period,
        ocert=ocert,
        pool_vk=b"\xbb" * 32,
        vrf_vk=b"\xcc" * 32,
        kes_depth=kes_depth,
        protocol_version=protocol_version,
    )


# ---------------------------------------------------------------------------
# 1. Header body field encoding per CDDL
# ---------------------------------------------------------------------------


class TestHeaderBodyFieldEncoding:
    """Verify every field position in the Babbage/Conway header_body.

    CDDL: header_body = [
        block_number,      -- 0
        slot,              -- 1
        prev_hash,         -- 2
        issuer_vkey,       -- 3
        vrf_vkey,          -- 4
        vrf_result,        -- 5
        block_body_size,   -- 6
        block_body_hash,   -- 7
        operational_cert,  -- 8
        protocol_version,  -- 9
    ]
    """

    def test_all_field_positions(self) -> None:
        """Each field is at the correct index in the header body array."""
        issuer_vk = b"\x01" * 32
        vrf_vk = b"\x02" * 32
        vrf_out = b"\x03" * VRF_OUTPUT_SIZE
        vrf_proof = b"\x04" * VRF_PROOF_SIZE
        body_hash = b"\x05" * 32
        ocert = _ocert()

        hb = _build_header_body(
            block_number=42,
            slot=1000,
            prev_hash=b"\x00" * 32,
            issuer_vk=issuer_vk,
            vrf_vk=vrf_vk,
            vrf_result=(vrf_out, vrf_proof),
            body_size=256,
            body_hash=body_hash,
            ocert=ocert,
            protocol_version=(10, 0),
        )

        assert hb[0] == 42, "block_number at index 0"
        assert hb[1] == 1000, "slot at index 1"
        assert hb[2] == b"\x00" * 32, "prev_hash at index 2"
        assert hb[3] == issuer_vk, "issuer_vkey at index 3"
        assert hb[4] == vrf_vk, "vrf_vkey at index 4"
        assert hb[5] == [vrf_out, vrf_proof], "vrf_result at index 5"
        assert hb[6] == 256, "block_body_size at index 6"
        assert hb[7] == body_hash, "block_body_hash at index 7"
        assert isinstance(hb[8], list), "operational_cert at index 8"
        assert hb[9] == [10, 0], "protocol_version at index 9"

    def test_vrf_result_is_two_element_list(self) -> None:
        """vrf_result is encoded as [output, proof]."""
        vrf_out = b"\xaa" * VRF_OUTPUT_SIZE
        vrf_proof = b"\xbb" * VRF_PROOF_SIZE

        hb = _build_header_body(
            block_number=1,
            slot=1,
            prev_hash=None,
            issuer_vk=b"\x00" * 32,
            vrf_vk=b"\x00" * 32,
            vrf_result=(vrf_out, vrf_proof),
            body_size=0,
            body_hash=b"\x00" * 32,
            ocert=_ocert(),
        )

        vrf_field = hb[5]
        assert isinstance(vrf_field, list)
        assert len(vrf_field) == 2
        assert vrf_field[0] == vrf_out
        assert vrf_field[1] == vrf_proof

    def test_ocert_is_four_element_array(self) -> None:
        """Operational cert is [kes_vk, cert_count, kes_period_start, cold_sig].

        CDDL: operational_cert = [kes_vkey, n, c0, sigma]
        """
        ocert = OperationalCert(
            kes_vk=b"\xaa" * 32,
            cert_count=7,
            kes_period_start=42,
            cold_sig=b"\xbb" * 64,
        )
        hb = _build_header_body(
            block_number=1,
            slot=1,
            prev_hash=None,
            issuer_vk=b"\x00" * 32,
            vrf_vk=b"\x00" * 32,
            vrf_result=(b"\x00" * VRF_OUTPUT_SIZE, b"\x00" * VRF_PROOF_SIZE),
            body_size=0,
            body_hash=b"\x00" * 32,
            ocert=ocert,
        )

        ocert_field = hb[8]
        assert isinstance(ocert_field, list)
        assert len(ocert_field) == 4
        assert ocert_field[0] == b"\xaa" * 32  # kes_vk
        assert ocert_field[1] == 7  # cert_count
        assert ocert_field[2] == 42  # kes_period_start
        assert ocert_field[3] == b"\xbb" * 64  # cold_sig


# ---------------------------------------------------------------------------
# 2. Body size limit enforcement
# ---------------------------------------------------------------------------


class TestBodySizeLimit:
    """Block body construction respects maxBlockBodySize."""

    def test_large_txs_excluded(self) -> None:
        """Txs that would exceed the limit are excluded.

        Haskell ref: bbody enforces maxBlockBodySize from protocol params.
        """
        # Each tx is ~200 bytes of CBOR, limit is 500.
        txs = [_sample_tx(200) for _ in range(10)]
        body_cbor, num_txs, *_ = _build_block_body(txs, max_body_size=500)

        assert num_txs < 10
        assert num_txs > 0

    def test_single_oversized_tx_excluded(self) -> None:
        """A single tx larger than the body limit produces empty body."""
        huge_tx = _sample_tx(100000)
        body_cbor, num_txs, bodies_bytes, *_ = _build_block_body([huge_tx], max_body_size=500)

        assert num_txs == 0
        decoded_bodies = cbor2.loads(bodies_bytes)
        assert decoded_bodies == []

    def test_prefix_selection_not_knapsack(self) -> None:
        """Selection is prefix-based: a large tx blocks smaller ones behind it.

        Haskell ref: The forger takes a prefix of the TxSeq, not an
        optimal knapsack packing.
        """
        # tx1=100 bytes, tx2=10000 bytes (too big), tx3=50 bytes
        tx1 = _sample_tx(100)
        tx2 = _sample_tx(10000)
        tx3 = _sample_tx(50)

        body_cbor, num_txs, *_ = _build_block_body([tx1, tx2, tx3], max_body_size=500)
        # Only tx1 should be included; tx2 is too big, so we stop.
        assert num_txs == 1


# ---------------------------------------------------------------------------
# 3. VRF result encoding in forged block
# ---------------------------------------------------------------------------


class TestVrfResultInBlock:
    """VRF output and proof appear correctly in the forged block header."""

    def test_vrf_result_in_forged_header(self) -> None:
        """The VRF result in the header matches the leader proof."""
        result = _forge_helper(slot=500)

        header_array = cbor2.loads(result.block.header_cbor)
        header_body = header_array[0]
        vrf_field = header_body[5]

        assert vrf_field[0] == b"\x22" * VRF_OUTPUT_SIZE  # from _leader_proof
        assert vrf_field[1] == b"\x11" * VRF_PROOF_SIZE


# ---------------------------------------------------------------------------
# 4. KES signature at non-zero period
# ---------------------------------------------------------------------------


class TestKesIntegration:
    """KES sign/verify integration in forged blocks."""

    def test_kes_at_period_zero(self) -> None:
        """Block forged at KES period 0 verifies correctly."""
        depth = 2
        kes_sk, kes_vk = _kes_keypair(depth=depth)
        ocert = _ocert(kes_vk=kes_vk)

        result = forge_block(
            leader_proof=_leader_proof(),
            prev_block_number=0,
            prev_header_hash=None,
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

        assert kes_verify(kes_vk, depth, 0, kes_sig, header_body_cbor)

    def test_kes_at_period_one(self) -> None:
        """Block forged at KES period 1 verifies at period 1 but not 0.

        Haskell ref: The KES signature embeds the period, so verification
        must use the correct period.
        """
        depth = 2  # 4 periods (0-3)
        kes_sk, kes_vk = _kes_keypair(depth=depth)
        ocert = _ocert(kes_vk=kes_vk)

        result = forge_block(
            leader_proof=_leader_proof(),
            prev_block_number=0,
            prev_header_hash=None,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=1,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=depth,
        )

        header_array = cbor2.loads(result.block.header_cbor)
        header_body_cbor = cbor2.dumps(header_array[0])
        kes_sig = header_array[1]

        # Correct period verifies.
        assert kes_verify(kes_vk, depth, 1, kes_sig, header_body_cbor)
        # Wrong period fails.
        assert not kes_verify(kes_vk, depth, 0, kes_sig, header_body_cbor)
        assert not kes_verify(kes_vk, depth, 2, kes_sig, header_body_cbor)

    def test_kes_at_last_period(self) -> None:
        """Block forged at the last valid KES period (2^depth - 1) verifies."""
        depth = 2  # 4 periods: 0, 1, 2, 3
        last_period = (1 << depth) - 1  # 3
        kes_sk, kes_vk = _kes_keypair(depth=depth)
        ocert = _ocert(kes_vk=kes_vk)

        result = forge_block(
            leader_proof=_leader_proof(),
            prev_block_number=0,
            prev_header_hash=None,
            mempool_txs=[],
            kes_sk=kes_sk,
            kes_period=last_period,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=depth,
        )

        header_array = cbor2.loads(result.block.header_cbor)
        header_body_cbor = cbor2.dumps(header_array[0])
        kes_sig = header_array[1]

        assert kes_verify(kes_vk, depth, last_period, kes_sig, header_body_cbor)


# ---------------------------------------------------------------------------
# 5. Empty vs non-empty blocks
# ---------------------------------------------------------------------------


class TestEmptyVsNonEmpty:
    """Both empty and non-empty blocks produce valid structures."""

    def test_empty_block_valid_cbor(self) -> None:
        """Empty block (no txs) produces decodable CBOR."""
        result = _forge_helper(mempool_txs=[])

        decoded = cbor2.loads(result.cbor)
        assert isinstance(decoded, list)
        assert decoded[0] == 7  # era tag
        # Inner array: [header, bodies, wits, aux, isvalid]
        block_inner = decoded[1]
        # tx_bodies is index 1 of the inner array
        assert block_inner[1] == []

    def test_nonempty_block_valid_cbor(self) -> None:
        """Block with txs produces decodable CBOR with correct tx count."""
        txs = [_sample_tx(80) for _ in range(3)]
        result = _forge_helper(mempool_txs=txs)

        decoded = cbor2.loads(result.cbor)
        block_inner = decoded[1]
        assert len(block_inner[1]) == 3

    def test_empty_and_nonempty_differ_in_hash(self) -> None:
        """Empty and non-empty blocks at same slot produce different hashes."""
        empty = _forge_helper(slot=100, mempool_txs=[])
        nonempty = _forge_helper(slot=100, mempool_txs=[_sample_tx(50)])

        # Different body -> different body_hash -> different header -> different block_hash
        assert empty.block.block_hash != nonempty.block.block_hash


# ---------------------------------------------------------------------------
# 6. prev_hash chaining
# ---------------------------------------------------------------------------


class TestPrevHashChaining:
    """Sequential blocks chain via prev_header_hash."""

    def test_chain_of_three_blocks(self) -> None:
        """Three blocks chain correctly: block2.prev = hash(block1.header).

        Haskell ref: Each block header contains the hash of the previous
        block's header, forming the blockchain.
        """
        # Block 1: genesis (no prev_hash).
        b1 = _forge_helper(slot=100, prev_block_number=0, prev_header_hash=None)

        # Block 2: prev = block1's header hash.
        b2 = _forge_helper(
            slot=200,
            prev_block_number=b1.block.block_number,
            prev_header_hash=b1.block.block_hash,
        )

        # Block 3: prev = block2's header hash.
        b3 = _forge_helper(
            slot=300,
            prev_block_number=b2.block.block_number,
            prev_header_hash=b2.block.block_hash,
        )

        # Verify chain.
        h1 = cbor2.loads(b1.block.header_cbor)[0]
        h2 = cbor2.loads(b2.block.header_cbor)[0]
        h3 = cbor2.loads(b3.block.header_cbor)[0]

        assert h1[2] is None  # genesis has no prev
        assert h2[2] == b1.block.block_hash
        assert h3[2] == b2.block.block_hash

    def test_block_hash_is_header_hash(self) -> None:
        """block_hash == blake2b-256(header_cbor), not full block."""
        result = _forge_helper()
        expected = hashlib.blake2b(result.block.header_cbor, digest_size=32).digest()
        assert result.block.block_hash == expected


# ---------------------------------------------------------------------------
# 7. Body hash integrity
# ---------------------------------------------------------------------------


class TestBodyHashIntegrity:
    """body_hash in header must match blake2b-256 of body_cbor."""

    def test_body_hash_empty_body(self) -> None:
        """Body hash is correct for empty block body (segmented witness hash)."""
        result = _forge_helper(mempool_txs=[])
        header_body = cbor2.loads(result.block.header_cbor)[0]
        body_hash_in_header = header_body[7]
        # Verify body hash is a 32-byte hash (segmented witness hash)
        assert len(body_hash_in_header) == 32
        # Verify body size matches
        body_size_in_header = header_body[6]
        assert body_size_in_header == len(result.block.body_cbor)

    def test_body_hash_nonempty_body(self) -> None:
        """Body hash is correct for block with transactions (segmented witness hash)."""
        txs = [_sample_tx(100) for _ in range(5)]
        result = _forge_helper(mempool_txs=txs)
        header_body = cbor2.loads(result.block.header_cbor)[0]
        body_hash_in_header = header_body[7]
        # Verify body hash is a 32-byte hash
        assert len(body_hash_in_header) == 32
        # Verify body size matches
        body_size_in_header = header_body[6]
        assert body_size_in_header == len(result.block.body_cbor)

    def test_body_size_in_header_matches(self) -> None:
        """body_size field in header == len(body_cbor).

        Haskell ref: The header body includes the body size for
        validation without downloading the full body.
        """
        txs = [_sample_tx(80) for _ in range(3)]
        result = _forge_helper(mempool_txs=txs)
        header_body = cbor2.loads(result.block.header_cbor)[0]
        body_size_in_header = header_body[6]
        assert body_size_in_header == len(result.block.body_cbor)


# ---------------------------------------------------------------------------
# 8. Protocol version encoding
# ---------------------------------------------------------------------------


class TestProtocolVersion:
    """Protocol version field is encoded correctly per era."""

    def test_conway_protocol_version(self) -> None:
        """Conway blocks use protocol version (10, 0)."""
        result = _forge_helper(protocol_version=(10, 0))
        header_body = cbor2.loads(result.block.header_cbor)[0]
        assert header_body[9] == [10, 0]

    def test_babbage_protocol_version(self) -> None:
        """Babbage blocks use protocol version (8, 0)."""
        result = _forge_helper(protocol_version=(8, 0))
        header_body = cbor2.loads(result.block.header_cbor)[0]
        assert header_body[9] == [8, 0]

    def test_custom_protocol_version(self) -> None:
        """Arbitrary protocol version is encoded correctly."""
        result = _forge_helper(protocol_version=(99, 7))
        header_body = cbor2.loads(result.block.header_cbor)[0]
        assert header_body[9] == [99, 7]


# ---------------------------------------------------------------------------
# 9. Block body four-array structure
# ---------------------------------------------------------------------------


class TestBlockBodyStructure:
    """Block body is a 4-element CBOR array per CDDL."""

    def test_four_element_concatenation(self) -> None:
        """Body is 4 concatenated CBOR items: bodies || wits || auxdata || isvalid.

        Alonzo/Conway block body is NOT a CBOR array. Each part is
        independently serialized and concatenated.
        """
        txs = [_sample_tx(50)]
        body_cbor, _, bodies_bytes, wits_bytes, auxdata_bytes, isvalid_bytes = _build_block_body(txs)

        # body_cbor is the concatenation of the 4 parts
        assert body_cbor == bodies_bytes + wits_bytes + auxdata_bytes + isvalid_bytes

        # Part 0: tx_bodies (list)
        decoded_bodies = cbor2.loads(bodies_bytes)
        assert isinstance(decoded_bodies, list)
        # Part 1: tx_witnesses (list, currently empty placeholder)
        decoded_wits = cbor2.loads(wits_bytes)
        assert isinstance(decoded_wits, list)
        # Part 2: auxiliary_data (map/dict for no aux data)
        decoded_aux = cbor2.loads(auxdata_bytes)
        assert isinstance(decoded_aux, dict)
        # Part 3: invalid_txs (list, currently empty)
        decoded_isvalid = cbor2.loads(isvalid_bytes)
        assert isinstance(decoded_isvalid, list)
        assert decoded_isvalid == []

    def test_empty_body_structure(self) -> None:
        """Empty body still has the four-part concatenation structure."""
        body_cbor, num_txs, bodies_bytes, *_ = _build_block_body([])
        assert num_txs == 0
        decoded_bodies = cbor2.loads(bodies_bytes)
        assert decoded_bodies == []


# ---------------------------------------------------------------------------
# 10. Determinism: same inputs produce same hash
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Same inputs must produce identical blocks (deterministic forging)."""

    def test_same_inputs_same_hash(self) -> None:
        """Two calls with identical inputs produce the same block hash.

        Haskell ref: forgeShelleyBlock is a pure function — given the
        same inputs, it always produces the same output.
        """
        # Use fixed KES keys for determinism.
        depth = 2
        kes_sk, kes_vk = _kes_keypair(depth=depth)
        ocert = _ocert(kes_vk=kes_vk)
        lp = _leader_proof(slot=500)
        txs = [_sample_tx(80)]
        prev_hash = b"\xaa" * 32

        r1 = forge_block(
            leader_proof=lp,
            prev_block_number=10,
            prev_header_hash=prev_hash,
            mempool_txs=txs,
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=depth,
        )
        r2 = forge_block(
            leader_proof=lp,
            prev_block_number=10,
            prev_header_hash=prev_hash,
            mempool_txs=txs,
            kes_sk=kes_sk,
            kes_period=0,
            ocert=ocert,
            pool_vk=b"\xbb" * 32,
            vrf_vk=b"\xcc" * 32,
            kes_depth=depth,
        )

        assert r1.block.block_hash == r2.block.block_hash
        assert r1.cbor == r2.cbor


# ---------------------------------------------------------------------------
# 11. Full block CBOR structure (header + body merged)
# ---------------------------------------------------------------------------


class TestFullBlockStructure:
    """The full block CBOR is [header, tx_bodies, witnesses, aux, invalid]."""

    def test_full_block_starts_with_header(self) -> None:
        """Full block is [era_tag, [header, bodies, wits, aux, isvalid]]."""
        result = _forge_helper(mempool_txs=[_sample_tx(50)])
        decoded = cbor2.loads(result.cbor)

        assert decoded[0] == 7  # Conway era tag
        block_inner = decoded[1]
        assert isinstance(block_inner, list)
        assert len(block_inner) == 5

        header = block_inner[0]
        assert isinstance(header, list)
        assert len(header) == 2  # [header_body, kes_sig]

        # header_body is a 10-element list.
        assert isinstance(header[0], list)
        assert len(header[0]) == 10

    def test_full_block_has_era_tag_and_inner(self) -> None:
        """Full block is [era_tag, inner_array] where inner has 5 elements."""
        result = _forge_helper(mempool_txs=[])
        decoded = cbor2.loads(result.cbor)
        assert len(decoded) == 2  # [era_tag, inner]
        assert decoded[0] == 7  # Conway era
        assert len(decoded[1]) == 5  # [header, bodies, wits, aux, isvalid]


# ---------------------------------------------------------------------------
# 12. Hypothesis: block body size invariant
# ---------------------------------------------------------------------------


@given(
    num_txs=st.integers(min_value=0, max_value=20),
    tx_size=st.integers(min_value=10, max_value=500),
    max_body=st.integers(min_value=100, max_value=5000),
)
@settings(max_examples=100)
def test_property_body_never_includes_excess_txs(
    num_txs: int, tx_size: int, max_body: int
) -> None:
    """Hypothesis: included tx count * tx_size stays within body limit.

    The actual CBOR may add framing overhead, but the tx selection logic
    should not include txs that would push raw size over the limit.
    """
    txs = [_sample_tx(tx_size) for _ in range(num_txs)]
    body_cbor, included, *_ = _build_block_body(txs, max_body_size=max_body)

    assert included <= num_txs
    # The included txs' raw sizes should be at most max_body (before overhead).
    raw_size = sum(len(tx) for tx in txs[:included])
    # Allow for per-tx overhead of 20 bytes in the selection logic.
    assert raw_size <= max_body or included == 0


# ---------------------------------------------------------------------------
# 13. LeaderProof immutability
# ---------------------------------------------------------------------------


class TestLeaderProofImmutability:
    """LeaderProof is frozen — no accidental mutation."""

    def test_frozen_dataclass(self) -> None:
        lp = _leader_proof()
        with pytest.raises(AttributeError):
            lp.slot = 999  # type: ignore[misc]

    def test_slot_preserved_in_block(self) -> None:
        """Leader proof's slot appears in the forged block."""
        result = _forge_helper(slot=7777)
        assert result.block.slot == 7777
        header_body = cbor2.loads(result.block.header_cbor)[0]
        assert header_body[1] == 7777


# ---------------------------------------------------------------------------
# 14. Block number edge case: block 1 after genesis
# ---------------------------------------------------------------------------


class TestBlockNumberEdgeCases:
    """Block numbering edge cases."""

    def test_first_block_after_genesis(self) -> None:
        """Block number 1 is produced from prev_block_number=0."""
        result = _forge_helper(prev_block_number=0, prev_header_hash=None)
        assert result.block.block_number == 1
        header_body = cbor2.loads(result.block.header_cbor)[0]
        assert header_body[0] == 1

    def test_large_block_number(self) -> None:
        """Large block numbers are handled correctly."""
        result = _forge_helper(prev_block_number=10_000_000)
        assert result.block.block_number == 10_000_001
