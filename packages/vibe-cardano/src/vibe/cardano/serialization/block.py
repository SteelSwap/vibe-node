"""Block header decoding and hash verification for Cardano multi-era blocks.

Implements CBOR deserialization of block headers across all Cardano eras,
from Byron through Conway. The block format follows the CDDL specifications
from cardano-ledger.

Spec references:
  - shelley.cddl: block, header, header_body, operational_cert, protocol_version
  - babbage.cddl: header_body (vrf_result replaces nonce_vrf + leader_vrf)
  - Hard-fork combinator wraps each era's block in a CBOR tag (0-7)

Block hash = Blake2b-256 of the CBOR-encoded header bytes. This is the
canonical block identifier used by chain-sync, block-fetch, and consensus.
See: cardano-ledger issue "add txid and headerHash in cddl schema" — the
header hash IS the block hash because the header contains the body hash.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import IntEnum

import cbor2pure as cbor2


class Era(IntEnum):
    """Cardano era tags as used by the hard-fork combinator.

    On the wire, blocks are wrapped in a CBOR tag that identifies the era.
    The tag value maps directly to these enum members.
    """

    BYRON_MAIN = 0
    BYRON_EBB = 1
    SHELLEY = 2
    ALLEGRA = 3
    MARY = 4
    ALONZO = 5
    BABBAGE = 6
    CONWAY = 7


# Eras that use the legacy two-VRF-cert header format (nonce_vrf + leader_vrf)
_TWO_VRF_ERAS = frozenset({Era.SHELLEY, Era.ALLEGRA, Era.MARY, Era.ALONZO})

# Eras that use the single vrf_result format (Babbage onward)
_SINGLE_VRF_ERAS = frozenset({Era.BABBAGE, Era.CONWAY})


@dataclass(frozen=True, slots=True)
class OperationalCert:
    """Operational certificate embedded in the block header.

    CDDL (shelley.cddl):
        operational_cert =
          ( hot_vkey        : $kes_vkey
          , sequence_number : uint
          , kes_period      : uint
          , sigma           : $signature
          )
    """

    hot_vkey: bytes
    sequence_number: int
    kes_period: int
    sigma: bytes


@dataclass(frozen=True, slots=True)
class ProtocolVersion:
    """Protocol version from the block header.

    CDDL: protocol_version = (uint, uint)
    """

    major: int
    minor: int


@dataclass(frozen=True, slots=True)
class BlockHeader:
    """Decoded Cardano block header.

    CDDL (shelley.cddl / babbage.cddl):
        header_body =
          [ block_number     : uint
          , slot             : uint
          , prev_hash        : $hash32 / null
          , issuer_vkey      : $vkey
          , vrf_vkey         : $vrf_vkey
          , nonce_vrf        : $vrf_cert        ; Shelley-Alonzo
          , leader_vrf       : $vrf_cert        ; Shelley-Alonzo
          -- OR --
          , vrf_result       : $vrf_cert        ; Babbage+
          , block_body_size  : uint
          , block_body_hash  : $hash32
          , operational_cert
          , protocol_version
          ]

    The block hash is NOT stored here — it's computed from the raw
    CBOR bytes of the header via Blake2b-256.
    """

    slot: int
    block_number: int
    prev_hash: bytes | None
    issuer_vkey: bytes
    block_body_hash: bytes
    block_body_size: int
    protocol_version: ProtocolVersion
    operational_cert: OperationalCert
    era: Era
    # The raw CBOR bytes of the full header (header_body + body_signature),
    # retained for hash computation.
    header_cbor: bytes
    # VRF output bytes from the header (nonce_vrf for Shelley-Alonzo,
    # vrf_result for Babbage+).  None for Byron or if not decoded.
    vrf_output: bytes | None = None

    @property
    def hash(self) -> bytes:
        """Blake2b-256 hash of the header CBOR — the canonical block ID."""
        return block_hash(self.header_cbor)


def detect_era(cbor_bytes: bytes) -> Era:
    """Detect which era a CBOR-encoded block belongs to from its tag.

    The hard-fork combinator wraps each era's block in a CBOR tag:
      Tag 0 = Byron main block
      Tag 1 = Byron EBB
      Tag 2 = Shelley
      ...
      Tag 7 = Conway

    This function parses the CBOR tag byte directly, without fully decoding
    the block payload. This avoids cbor2's semantic tag conversion (which
    interprets tags 0-5 as datetime/bignum).

    Args:
        cbor_bytes: Raw CBOR bytes of a tagged block.

    Returns:
        The Era enum value.

    Raises:
        ValueError: If the outer CBOR structure is not a valid era tag.
    """
    decoded = cbor2.loads(cbor_bytes, raw_tags=True)
    if not isinstance(decoded, cbor2.CBORTag):
        raise ValueError(f"Expected CBOR tag, got {type(decoded).__name__}")
    try:
        return Era(decoded.tag)
    except ValueError:
        raise ValueError(f"Unknown era tag: {decoded.tag}") from None


def block_hash(header_cbor: bytes) -> bytes:
    """Compute the block hash: Blake2b-256 of the CBOR-encoded header.

    This is the canonical block identifier used throughout Cardano for
    chain-sync points, block-fetch requests, and prev_hash references.

    Args:
        header_cbor: Raw CBOR bytes of the block header
                     (the [header_body, body_signature] array).

    Returns:
        32-byte Blake2b-256 digest.
    """
    return hashlib.blake2b(header_cbor, digest_size=32).digest()


def _decode_header_body_shelley(items: list, era: Era, header_cbor: bytes) -> BlockHeader:
    """Decode a Shelley-through-Alonzo header_body (two VRF certs).

    CDDL field order (shelley.cddl):
      [0] block_number     : uint
      [1] slot             : uint
      [2] prev_hash        : $hash32 / null
      [3] issuer_vkey      : $vkey
      [4] vrf_vkey         : $vrf_vkey
      [5] nonce_vrf        : $vrf_cert
      [6] leader_vrf       : $vrf_cert
      [7] block_body_size  : uint
      [8] block_body_hash  : $hash32
      [9..12] operational_cert (4 inline fields)
      [13] protocol_version major
      [14] protocol_version minor
    """
    if len(items) < 15:
        raise ValueError(f"Shelley-era header_body expected >= 15 items, got {len(items)}")

    block_number = items[0]
    slot = items[1]
    prev_hash = items[2]  # bytes or None
    issuer_vkey = items[3]
    # items[4] = vrf_vkey (skipped for now)
    # items[5] = nonce_vrf: $vrf_cert = [output, proof]
    # items[6] = leader_vrf (skipped for now)
    block_body_size = items[7]
    block_body_hash = items[8]

    # Extract VRF output from nonce_vrf cert for nonce evolution.
    # Shelley nonce_vrf is items[5] = [vrf_output_bytes, vrf_proof_bytes]
    vrf_output: bytes | None = None
    nonce_vrf = items[5]
    if isinstance(nonce_vrf, (list, tuple)) and len(nonce_vrf) >= 1:
        candidate = nonce_vrf[0]
        if isinstance(candidate, bytes):
            vrf_output = candidate

    op_cert = OperationalCert(
        hot_vkey=items[9],
        sequence_number=items[10],
        kes_period=items[11],
        sigma=items[12],
    )

    proto_ver = ProtocolVersion(major=items[13], minor=items[14])

    return BlockHeader(
        slot=slot,
        block_number=block_number,
        prev_hash=prev_hash if prev_hash is not None else None,
        issuer_vkey=issuer_vkey,
        block_body_hash=block_body_hash,
        block_body_size=block_body_size,
        protocol_version=proto_ver,
        operational_cert=op_cert,
        era=era,
        header_cbor=header_cbor,
        vrf_output=vrf_output,
    )


def _decode_header_body_babbage(items: list, era: Era, header_cbor: bytes) -> BlockHeader:
    """Decode a Babbage/Conway header_body (single vrf_result).

    CDDL field order (babbage.cddl):
      [0] block_number     : uint
      [1] slot             : uint
      [2] prev_hash        : $hash32 / null
      [3] issuer_vkey      : $vkey
      [4] vrf_vkey         : $vrf_vkey
      [5] vrf_result       : $vrf_cert   ; replaces nonce_vrf + leader_vrf
      [6] block_body_size  : uint
      [7] block_body_hash  : $hash32
      [8..11] operational_cert (4 inline fields)
      [12] protocol_version major
      [13] protocol_version minor
    """
    # Babbage/Conway uses 10 fields with nested opcert + protver sub-arrays:
    #   [0] block_number, [1] slot, [2] prev_hash, [3] issuer_vkey,
    #   [4] vrf_vkey, [5] vrf_result, [6] body_size, [7] body_hash,
    #   [8] [kes_vk, n, c0, sig], [9] [major, minor]
    # Shelley-Mary uses 14 fields with opcert + protver inlined.
    if len(items) < 10:
        raise ValueError(f"header_body expected >= 10 items, got {len(items)}")

    block_number = items[0]
    slot = items[1]
    prev_hash = items[2]
    issuer_vkey = items[3]
    # items[4] = vrf_vkey (skipped for now)
    # items[5] = vrf_result: $vrf_cert = [vrf_output, vrf_proof]
    block_body_size = items[6]
    block_body_hash = items[7]

    # Extract VRF output from vrf_result cert for nonce evolution.
    # Babbage vrf_result is items[5] = [vrf_output_bytes, vrf_proof_bytes]
    vrf_output: bytes | None = None
    vrf_result = items[5]
    if isinstance(vrf_result, (list, tuple)) and len(vrf_result) >= 1:
        candidate = vrf_result[0]
        if isinstance(candidate, bytes):
            vrf_output = candidate

    # Babbage/Conway: opcert is nested [kes_vk, n, c0, sig] at index 8
    # Shelley-Mary: opcert is 4 inline fields at indices 8-11
    if len(items) == 10 and isinstance(items[8], (list, tuple)):
        # Babbage/Conway 10-field format with nested sub-arrays
        opcert_data = items[8]  # [kes_vk, n, c0, sig]
        protver_data = items[9]  # [major, minor]
        op_cert = OperationalCert(
            hot_vkey=opcert_data[0],
            sequence_number=opcert_data[1],
            kes_period=opcert_data[2],
            sigma=opcert_data[3],
        )
        proto_ver = ProtocolVersion(major=protver_data[0], minor=protver_data[1])
    elif len(items) >= 14:
        # Shelley-Mary 14-field format with inline opcert + protver
        # Shelley-Mary 14-field format
        op_cert = OperationalCert(
            hot_vkey=items[8],
            sequence_number=items[9],
            kes_period=items[10],
            sigma=items[11],
        )
        proto_ver = ProtocolVersion(major=items[12], minor=items[13])
    else:
        raise ValueError(
            f"header_body has {len(items)} items but opcert at index 8 "
            f"is not a nested array — cannot determine format"
        )

    return BlockHeader(
        slot=slot,
        block_number=block_number,
        prev_hash=prev_hash if prev_hash is not None else None,
        issuer_vkey=issuer_vkey,
        block_body_hash=block_body_hash,
        block_body_size=block_body_size,
        protocol_version=proto_ver,
        operational_cert=op_cert,
        era=era,
        header_cbor=header_cbor,
        vrf_output=vrf_output,
    )


def _decode_tagged_block(cbor_bytes: bytes) -> tuple[Era, object]:
    """Decode a tagged block, returning (era, block_payload).

    Handles two formats:
    1. CBORTag(era, block_body) — our internal storage format
    2. [era_int, block_body] — HFC wire format from block-fetch

    Uses raw_tags=True so CBOR tags 0-7 are returned as CBORTag objects
    instead of being interpreted as semantic types (datetime, bignum, etc.).
    """
    decoded = cbor2.loads(cbor_bytes, raw_tags=True)

    # Format 1: CBORTag(era, value) — our tagged storage format
    if isinstance(decoded, cbor2.CBORTag):
        try:
            era = Era(decoded.tag)
        except ValueError:
            raise ValueError(f"Unknown era tag: {decoded.tag}") from None
        return era, decoded.value

    # Format 2: [era_int, block_body] — HFC wire format from block-fetch
    if isinstance(decoded, list) and len(decoded) >= 2 and isinstance(decoded[0], int):
        try:
            era = Era(decoded[0])
        except ValueError:
            raise ValueError(f"Unknown era tag: {decoded[0]}") from None
        return era, decoded[1]

    raise ValueError(f"Expected CBOR tag or [era, body] list, got {type(decoded).__name__}")


def decode_block_header(cbor_bytes: bytes) -> BlockHeader:
    """Decode a raw CBOR block and extract its header.

    Handles the full multi-era block format:
      1. Unwrap the era tag from the hard-fork combinator
      2. Decode the block array: [header, body, witnesses, auxiliary]
      3. Decode the header: [header_body, body_signature]
      4. Decode header_body fields according to era-specific CDDL

    For Byron blocks (tags 0, 1), raises NotImplementedError — Byron uses
    a completely different block structure (TxAux) with no pycardano support.

    Args:
        cbor_bytes: Raw CBOR bytes of a tagged block (as received from
                    chain-sync or read from chain data files).

    Returns:
        Decoded BlockHeader with all fields populated.

    Raises:
        NotImplementedError: For Byron-era blocks.
        ValueError: For malformed CBOR or unexpected structure.
    """
    era, block_array = _decode_tagged_block(cbor_bytes)

    if era in (Era.BYRON_MAIN, Era.BYRON_EBB):
        raise NotImplementedError(f"Byron block decoding not yet supported (era tag {era.value})")

    if not isinstance(block_array, list) or len(block_array) < 4:
        raise ValueError(
            f"Expected block as CBOR array of >= 4 elements, "
            f"got {type(block_array).__name__} with "
            f"{len(block_array) if isinstance(block_array, list) else 0} elements"
        )

    # block = [header, transaction_bodies, transaction_witness_sets, auxiliary_data]
    # header = [header_body, body_signature]
    header_array = block_array[0]

    if not isinstance(header_array, list) or len(header_array) != 2:
        raise ValueError(
            f"Expected header as CBOR array of 2 elements, "
            f"got {len(header_array) if isinstance(header_array, list) else 0}"
        )

    # Re-encode the header to get its canonical CBOR bytes for hashing.
    # This is what the Haskell node does: hash of the serialized header.
    header_cbor = cbor2.dumps(header_array)

    header_body = header_array[0]
    # header_array[1] = body_signature (KES signature, preserved in header_cbor)

    if not isinstance(header_body, list):
        raise ValueError(f"Expected header_body as CBOR array, got {type(header_body).__name__}")

    if era in _TWO_VRF_ERAS:
        return _decode_header_body_shelley(header_body, era, header_cbor)
    elif era in _SINGLE_VRF_ERAS:
        return _decode_header_body_babbage(header_body, era, header_cbor)
    else:
        raise ValueError(f"Unhandled era: {era}")


def decode_block_header_from_array(
    block_array: list | object, era: Era, header_cbor_override: bytes | None = None,
) -> BlockHeader:
    """Decode a block header from an already-decoded block array.

    Avoids re-parsing the entire block CBOR — the caller provides the
    pre-decoded block_array and era tag from their initial parse.

    This is the "decode once" optimization: the block is decoded once
    in _on_block, and the parsed structure is passed through to header
    and body decoding without re-serialization.

    Args:
        block_array: The decoded block body: [header, tx_bodies, witnesses, aux]
        era: The era of this block.
        header_cbor_override: If provided, use these bytes for the header hash
            instead of re-encoding. Preferred for hash correctness.

    Returns:
        Decoded BlockHeader.
    """
    if era in (Era.BYRON_MAIN, Era.BYRON_EBB):
        raise NotImplementedError(f"Byron block decoding not supported (era {era.value})")

    # Accept any sequence type (IndefiniteFrozenList, etc.)
    if not hasattr(block_array, "__getitem__") or len(block_array) < 4:
        raise ValueError(
            f"Expected block as array of >= 4 elements, got {type(block_array).__name__}"
        )

    header_array = block_array[0]
    if not hasattr(header_array, "__getitem__") or len(header_array) != 2:
        raise ValueError(
            f"Expected header as array of 2 elements, got {type(header_array).__name__}"
        )

    if header_cbor_override is not None:
        header_cbor = header_cbor_override
    else:
        # Fallback: re-encode (may change encoding for indefinite types)
        from vibe.cardano.serialization.transaction import _normalize_cbor_types

        header_cbor = cbor2.dumps(_normalize_cbor_types(header_array))

    header_body = header_array[0]
    if not hasattr(header_body, "__getitem__"):
        raise ValueError(f"Expected header_body as array, got {type(header_body).__name__}")

    # Convert to list for consistent indexing
    if not isinstance(header_body, list):
        header_body = list(header_body)

    if era in _TWO_VRF_ERAS:
        return _decode_header_body_shelley(header_body, era, header_cbor)
    elif era in _SINGLE_VRF_ERAS:
        return _decode_header_body_babbage(header_body, era, header_cbor)
    else:
        raise ValueError(f"Unhandled era: {era}")


def decode_block_header_raw(header_cbor: bytes, era: Era) -> BlockHeader:
    """Decode a block header from raw header CBOR bytes (no block wrapper).

    Useful when you already have just the header bytes (e.g., from
    the storage layer or from a chain-sync HeaderOnly message).

    Args:
        header_cbor: Raw CBOR bytes of the header [header_body, body_signature].
        era: The era this header belongs to.

    Returns:
        Decoded BlockHeader.

    Raises:
        NotImplementedError: For Byron-era headers.
        ValueError: For malformed CBOR or unexpected structure.
    """
    if era in (Era.BYRON_MAIN, Era.BYRON_EBB):
        raise NotImplementedError(f"Byron header decoding not yet supported (era tag {era.value})")

    header_array = cbor2.loads(header_cbor)

    if not isinstance(header_array, list) or len(header_array) != 2:
        raise ValueError(
            f"Expected header as CBOR array of 2 elements, "
            f"got {len(header_array) if isinstance(header_array, list) else 0}"
        )

    header_body = header_array[0]

    if not isinstance(header_body, list):
        raise ValueError(f"Expected header_body as CBOR array, got {type(header_body).__name__}")

    if era in _TWO_VRF_ERAS:
        return _decode_header_body_shelley(header_body, era, header_cbor)
    elif era in _SINGLE_VRF_ERAS:
        return _decode_header_body_babbage(header_body, era, header_cbor)
    else:
        raise ValueError(f"Unhandled era: {era}")
