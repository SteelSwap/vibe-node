"""Block construction -- assembles a valid Cardano block for forging.

Given a leader proof (VRF), a set of mempool transactions, and the pool's
signing credentials (KES key + operational certificate), this module builds
a complete block: header body, KES-signed header, and transaction body.

The block layout follows the Babbage+ CDDL schema (single vrf_result):

    block = [header, transaction_bodies, transaction_witness_sets,
             auxiliary_data_map]
    header = [header_body, kes_signature]
    header_body = [block_number, slot, prev_hash, issuer_vkey, vrf_vkey,
                   vrf_result, block_body_size, block_body_hash,
                   operational_cert, protocol_version]

Spec references:
    - babbage.cddl: block, header, header_body
    - Shelley formal spec, Figure 10 (block structure)
    - Shelley formal spec, Section 3.3 (bbody function)

Haskell references:
    - Ouroboros.Consensus.Shelley.Node.Forging (forgeShelleyBlock)
    - Cardano.Ledger.Shelley.BlockChain (bbody, mkShelleyHeader)
    - Cardano.Ledger.Api.Era (CBOR encoding)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import cbor2pure as cbor2

from vibe.cardano.crypto.kes import (
    CARDANO_KES_DEPTH,
    KesSecretKey,
    kes_sign,
)
from vibe.cardano.crypto.ocert import OperationalCert

from .leader import LeaderProof

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default protocol parameters
# ---------------------------------------------------------------------------

#: Default maximum block body size in bytes (Babbage/Conway mainnet: 90112).
DEFAULT_MAX_BLOCK_BODY_SIZE: int = 90112

#: Default protocol version for forged blocks (Conway = 10.0).
DEFAULT_PROTOCOL_VERSION: tuple[int, int] = (10, 0)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Block:
    """A forged Cardano block ready for propagation.

    Contains the CBOR-encoded header (with KES signature) and body,
    plus the pre-computed block hash for convenience.

    Attributes:
        header_cbor: CBOR-encoded header [header_body, kes_signature].
        body_cbor: CBOR-encoded block body (transaction arrays).
        block_hash: Blake2b-256 of header_cbor (the canonical block ID).
        block_number: Block number.
        slot: Slot number.
    """

    header_cbor: bytes
    body_cbor: bytes
    block_hash: bytes
    block_number: int
    slot: int


@dataclass(frozen=True, slots=True)
class ForgedBlock:
    """Complete forged block as a single CBOR-encoded blob.

    This is the wire-format block ready for block-fetch responses and
    chain-sync announcements.

    Attributes:
        block: The structured Block.
        cbor: The full CBOR-encoded block (tagged with era).
    """

    block: Block
    cbor: bytes


# ---------------------------------------------------------------------------
# Block body construction
# ---------------------------------------------------------------------------


def _build_block_body(
    mempool_txs: list[bytes],
    max_body_size: int = DEFAULT_MAX_BLOCK_BODY_SIZE,
) -> tuple[bytes, int]:
    """Build the block body from mempool transactions.

    Selects the largest prefix of transactions that fits within the
    maximum block body size. Each transaction is a pre-encoded CBOR blob.

    The block body is encoded as four parallel arrays per the CDDL:
        [transaction_bodies, transaction_witness_sets,
         auxiliary_data_map, invalid_transactions]

    For simplicity in this initial implementation, we encode transactions
    as raw CBOR-tagged items. The transaction_bodies and witness_sets are
    extracted from the full transaction CBOR.

    Spec ref: babbage.cddl -- ``block`` structure
    Haskell ref: ``bbody`` in ``Cardano.Ledger.Shelley.BlockChain``

    Args:
        mempool_txs: List of CBOR-encoded transactions.
        max_body_size: Maximum block body size in bytes.

    Returns:
        Tuple of (body_cbor, num_txs_included).
    """
    # Collect transactions that fit within the body size limit.
    # We build the body incrementally and check size after each tx.
    selected_txs: list[bytes] = []
    current_size = 0

    for tx_cbor in mempool_txs:
        # Estimate: each tx adds its CBOR size plus minor CBOR array overhead.
        # The actual body CBOR includes array framing, but we use a
        # conservative estimate here.
        tx_size = len(tx_cbor)
        # Account for CBOR array overhead (rough estimate: 16 bytes per tx
        # for the four parallel arrays' per-element framing)
        overhead = 20
        if current_size + tx_size + overhead > max_body_size:
            break
        selected_txs.append(tx_cbor)
        current_size += tx_size + overhead

    # Encode the body as four arrays:
    # [tx_bodies, tx_witness_sets, auxiliary_data_map, invalid_txs]
    #
    # Each selected tx is a complete CBOR-encoded transaction. For now we
    # store them in tx_bodies as raw CBOR items. A real implementation would
    # split the transaction into body/witnesses/auxiliary, but for the forge
    # module the key property is: the block body is deterministically encoded
    # and its hash can be verified.
    # Alonzo/Conway block body is NOT a CBOR array. It's 4 separate
    # CBOR-encoded items concatenated: bodies || wits || auxdata || isvalid.
    # Each part is independently serialized.
    #
    # Haskell ref: encCBORGroup in Alonzo/BlockBody/Internal.hs:177-181
    #   encCBORGroup = encodePreEncoded (bodyBytes <> witsBytes <> metaBytes <> invalidBytes)
    #   listLen = 4
    #
    # The body hash uses hashAlonzoSegWits which hashes each part separately:
    #   hash( hash(bodies) || hash(wits) || hash(auxdata) || hash(isvalid) )
    bodies_cbor = cbor2.dumps(selected_txs)  # CBOR array of tx bodies
    wits_cbor = cbor2.dumps([])  # CBOR array of witness sets
    auxdata_cbor = cbor2.dumps({})  # CBOR map of auxiliary data
    isvalid_cbor = cbor2.dumps([])  # CBOR array of invalid tx indices

    # Body is the concatenation of the 4 parts (no outer array wrapper)
    body_cbor = bodies_cbor + wits_cbor + auxdata_cbor + isvalid_cbor

    logger.debug(
        "Block body: %d txs, %d bytes (limit %d)",
        len(selected_txs),
        len(body_cbor),
        max_body_size,
    )

    return body_cbor, len(selected_txs), bodies_cbor, wits_cbor, auxdata_cbor, isvalid_cbor


# ---------------------------------------------------------------------------
# Header construction
# ---------------------------------------------------------------------------


def _build_header_body(
    block_number: int,
    slot: int,
    prev_hash: bytes | None,
    issuer_vk: bytes,
    vrf_vk: bytes,
    vrf_result: tuple[bytes, bytes],
    body_size: int,
    body_hash: bytes,
    ocert: OperationalCert,
    protocol_version: tuple[int, int] = DEFAULT_PROTOCOL_VERSION,
) -> list[Any]:
    """Build the header body as a CBOR-encodable list.

    Follows the Babbage+ header_body CDDL layout (single vrf_result):

        header_body = [
            block_number, slot, prev_hash, issuer_vkey, vrf_vkey,
            vrf_result, block_body_size, block_body_hash,
            operational_cert, protocol_version
        ]

    The operational_cert is inlined as 4 fields, and protocol_version
    as 2 fields, matching the CDDL.

    Spec ref: babbage.cddl -- header_body
    Haskell ref: ``mkShelleyHeader`` in
        ``Cardano.Ledger.Shelley.BlockChain``

    Args:
        block_number: Block number (prev + 1).
        slot: Slot number from leader proof.
        prev_hash: Blake2b-256 hash of previous header, or None for genesis.
        issuer_vk: Pool's cold verification key (32 bytes).
        vrf_vk: Pool's VRF verification key (32 bytes).
        vrf_result: Tuple of (vrf_output, vrf_proof).
        body_size: Size of the CBOR-encoded block body.
        body_hash: Blake2b-256 hash of the block body.
        ocert: Operational certificate.
        protocol_version: Tuple of (major, minor).

    Returns:
        List suitable for CBOR encoding as the header body.
    """
    return [
        block_number,
        slot,
        prev_hash,  # None encodes as CBOR null
        issuer_vk,
        vrf_vk,
        list(vrf_result),  # [vrf_output, vrf_proof]
        body_size,
        body_hash,
        # Operational cert (nested array in Babbage/Conway format)
        [ocert.kes_vk, ocert.cert_count, ocert.kes_period_start, ocert.cold_sig],
        # Protocol version (nested array in Babbage/Conway format)
        [protocol_version[0], protocol_version[1]],
    ]


# ---------------------------------------------------------------------------
# Block forging
# ---------------------------------------------------------------------------


def forge_block(
    leader_proof: LeaderProof,
    prev_block_number: int,
    prev_header_hash: bytes | None,
    mempool_txs: list[bytes],
    kes_sk: KesSecretKey,
    kes_period: int,
    ocert: OperationalCert,
    pool_vk: bytes,
    vrf_vk: bytes,
    *,
    max_body_size: int = DEFAULT_MAX_BLOCK_BODY_SIZE,
    protocol_version: tuple[int, int] = DEFAULT_PROTOCOL_VERSION,
    kes_depth: int = CARDANO_KES_DEPTH,
) -> ForgedBlock:
    """Forge a complete Cardano block.

    This is the top-level block construction function. Given a leader proof
    (from ``check_leadership``), previous chain state, and mempool
    transactions, it:

    1. Builds the block body from mempool txs (largest prefix fitting in
       maxBlockBodySize).
    2. Constructs the header body with all required fields.
    3. CBOR-encodes the header body and signs it with KES.
    4. Assembles the complete block.

    Spec ref:
        Shelley formal spec, Section 3.3 -- block construction:
            block = (header, block_body)
            header = (header_body, kes_signature)

    Haskell ref:
        ``forgeShelleyBlock`` in
            ``Ouroboros.Consensus.Shelley.Node.Forging``

    Args:
        leader_proof: VRF proof of slot leadership.
        prev_block_number: Block number of the previous block.
        prev_header_hash: Blake2b-256 hash of the previous block header,
            or None if this is the first block after genesis.
        mempool_txs: List of CBOR-encoded transactions from the mempool.
        kes_sk: KES secret key for signing.
        kes_period: Current KES period (relative to OCert start).
        ocert: Operational certificate (cold-to-hot key delegation).
        pool_vk: Pool's cold verification key (32 bytes).
        vrf_vk: Pool's VRF verification key (32 bytes).
        max_body_size: Maximum block body size in bytes.
        protocol_version: Protocol version tuple (major, minor).
        kes_depth: KES tree depth (default 6 for Cardano mainnet).

    Returns:
        A ``ForgedBlock`` containing the complete CBOR-encoded block.

    Raises:
        ValueError: If KES period is out of range.
    """
    block_number = prev_block_number + 1
    slot = leader_proof.slot

    # Step 1: Build block body (4 separate CBOR-encoded parts)
    body_cbor, num_txs, bodies_bytes, wits_bytes, auxdata_bytes, isvalid_bytes = (
        _build_block_body(mempool_txs, max_body_size)
    )

    # Step 2: Compute body hash (Alonzo segmented witness hash)
    # Haskell ref: hashAlonzoSegWits in Alonzo/BlockBody/Internal.hs:194-206
    #   hash( hash(bodies) || hash(wits) || hash(auxdata) || hash(isvalid) )
    def _hash_part(data: bytes) -> bytes:
        return hashlib.blake2b(data, digest_size=32).digest()

    body_hash = hashlib.blake2b(
        _hash_part(bodies_bytes) + _hash_part(wits_bytes)
        + _hash_part(auxdata_bytes) + _hash_part(isvalid_bytes),
        digest_size=32,
    ).digest()

    # Step 3: Construct header body
    vrf_result = (leader_proof.vrf_output, leader_proof.vrf_proof)
    header_body = _build_header_body(
        block_number=block_number,
        slot=slot,
        prev_hash=prev_header_hash,
        issuer_vk=pool_vk,
        vrf_vk=vrf_vk,
        vrf_result=vrf_result,
        body_size=len(body_cbor),
        body_hash=body_hash,
        ocert=ocert,
        protocol_version=protocol_version,
    )

    # Step 4: CBOR-encode the header body (this is the KES-signed message)
    header_body_cbor = cbor2.dumps(header_body)

    # Step 5: KES-sign the header body
    kes_signature = kes_sign(kes_sk, kes_period, header_body_cbor)

    # Step 6: Assemble header = [header_body, kes_signature]
    header_array = [header_body, kes_signature]
    header_cbor = cbor2.dumps(header_array)

    # Step 7: Compute block hash = Blake2b-256(header_cbor)
    block_hash = hashlib.blake2b(header_cbor, digest_size=32).digest()

    block = Block(
        header_cbor=header_cbor,
        body_cbor=body_cbor,
        block_hash=block_hash,
        block_number=block_number,
        slot=slot,
    )

    # Step 8: Assemble full block for storage.
    # Format: [era_tag, [header, bodies, wits, aux, isvalid]]
    # Built by concatenating raw CBOR bytes directly — no decode/re-encode.
    #
    # CBOR structure:
    #   82         array(2)  — [era_tag, block_body]
    #   07         uint(7)   — Conway era
    #   85         array(5)  — [header, bodies, wits, aux, isvalid]
    #   <header_cbor> <bodies_bytes> <wits_bytes> <auxdata_bytes> <isvalid_bytes>
    full_block_cbor = b'\x82\x07\x85' + header_cbor + bodies_bytes + wits_bytes + auxdata_bytes + isvalid_bytes

    logger.debug(
        "forge_block: block #%d slot=%d txs=%d header=%d body=%d hash=%s",
        block_number,
        slot,
        num_txs,
        len(header_cbor),
        len(body_cbor),
        block_hash.hex()[:16],
    )

    return ForgedBlock(block=block, cbor=full_block_cbor)
