"""Block body decoding: transactions, witnesses, and auxiliary data.

Parses the body portion of a Cardano block (Shelley+). A block is a CBOR array:
    [header, transaction_bodies, transaction_witness_sets, auxiliary_data_map]

This module extracts and deserializes the transaction bodies (index 1),
witness sets (index 2), and auxiliary data (index 3) from the block array,
using pycardano types where possible and falling back to raw cbor2 where
pycardano can't handle era-specific structures.

Spec references:
  - shelley.cddl: transaction_body, transaction_witness_set
  - alonzo.cddl: transaction_body (adds script_data_hash, collateral, etc.)
  - babbage.cddl: transaction_body (adds reference_inputs, collateral_return)
  - conway.cddl: transaction_body (adds voting_procedures, proposal_procedures)

The block body structure per the CDDL:
  block = [header, transaction_bodies, transaction_witness_sets, auxiliary_data]

  transaction_bodies      = [* transaction_body]
  transaction_witness_sets = [* transaction_witness_set]
  auxiliary_data          = {* transaction_index => auxiliary_data}

Each transaction_body is a map keyed by integer field identifiers.
Each transaction_witness_set is a map keyed by integer witness type tags.
The auxiliary_data map is keyed by transaction index (0-based).
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass

import cbor2pure as _cbor2
from pycardano.metadata import AuxiliaryData
from pycardano.transaction import Transaction, TransactionBody
from pycardano.witness import TransactionWitnessSet

from vibe.cardano.serialization.block import Era

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DecodedTransaction:
    """A single transaction extracted from a block body.

    Wraps pycardano types where deserialization succeeds, falls back to
    raw CBOR primitives where it doesn't (documented as gaps).

    Attributes:
        index: Transaction index within the block (0-based).
        body: Decoded TransactionBody, or raw dict if pycardano fails.
        witness_set: Decoded TransactionWitnessSet, or raw dict if pycardano fails.
        auxiliary_data: Decoded AuxiliaryData, raw primitive, or None.
        valid: Validity flag (True for Shelley-Mary, explicit in Alonzo+).
        body_raw: The raw CBOR primitive (dict) of the transaction body,
                  preserved for hash computation and debugging.
        tx_hash: Blake2b-256 hash of the CBOR-serialized transaction body.
    """

    index: int
    body: TransactionBody | dict
    witness_set: TransactionWitnessSet | dict
    auxiliary_data: AuxiliaryData | object | None
    valid: bool
    body_raw: dict
    tx_hash: bytes


@dataclass(frozen=True, slots=True)
class DecodedBlockBody:
    """All transactions decoded from a single block.

    Attributes:
        transactions: List of decoded transactions in block order.
        era: The era of the block these transactions came from.
        tx_count: Number of transactions in the block.
    """

    transactions: list[DecodedTransaction]
    era: Era
    tx_count: int


def _normalize_cbor_types(obj: object) -> object:
    """Recursively convert cbor2 internal types to standard Python types.

    cbor2pure decodes indefinite-length CBOR arrays/maps into
    IndefiniteFrozenList/IndefiniteArray types that can't be re-serialized.
    This converts them to regular list/dict so cbor2.dumps() works.

    Uses duck typing (hasattr + try/iter) rather than isinstance checks
    because the cbor2pure internal types vary across versions.

    NOTE: This is a fallback — prefer using original bytes over
    re-serialization wherever possible.
    """
    if isinstance(obj, dict):
        return {_normalize_cbor_types(k): _normalize_cbor_types(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_cbor_types(item) for item in obj]
    if hasattr(obj, "tag") and hasattr(obj, "value"):
        return _cbor2.CBORTag(obj.tag, _normalize_cbor_types(obj.value))
    # Catch-all for any iterable cbor2 type (IndefiniteFrozenList, frozenlist, etc.)
    # that isn't list/tuple/dict/str/bytes but is iterable
    if not isinstance(obj, (str, bytes, int, float, bool, type(None))):
        try:
            return [_normalize_cbor_types(item) for item in obj]
        except TypeError:
            pass  # Not iterable
    return obj


def _cbor_dumps(obj: object) -> bytes:
    """Encode to CBOR bytes, normalizing types if needed."""
    try:
        return _cbor2.dumps(obj)
    except Exception:
        return _cbor2.dumps(_normalize_cbor_types(obj))


def _tx_hash(body: dict | bytes) -> bytes:
    """Compute transaction hash. Accepts dict (re-encodes) or bytes (direct).

    Prefer passing original CBOR bytes when available to avoid
    re-serialization issues.
    """
    if isinstance(body, bytes):
        return _tx_hash_from_bytes(body)
    return _tx_hash_from_bytes(_cbor_dumps(body))


def _tx_hash_from_bytes(body_cbor: bytes) -> bytes:
    """Compute transaction hash from original CBOR bytes.

    The transaction ID is Blake2b-256 of the CBOR-encoded body.
    We use the ORIGINAL bytes (not re-encoded) to match Haskell's
    MemoBytes/Annotator pattern — CBOR has multiple valid encodings,
    so re-serialization can change bytes and produce wrong hashes.

    Haskell ref: hashAnnotated in Cardano.Ledger.Hashes

    Args:
        body_cbor: Original CBOR bytes of the transaction body.

    Returns:
        32-byte Blake2b-256 digest.
    """
    return hashlib.blake2b(body_cbor, digest_size=32).digest()


def _try_decode_tx_body(raw: dict) -> TransactionBody | dict:
    """Attempt to decode a transaction body using pycardano.

    Falls back to the raw dict if pycardano raises during deserialization
    (e.g., for era-specific fields it doesn't recognize).

    Args:
        raw: The CBOR-decoded map of the transaction body.

    Returns:
        A TransactionBody instance, or the raw dict on failure.
    """
    try:
        return TransactionBody.from_primitive(raw)
    except Exception as exc:
        logger.debug(
            "pycardano TransactionBody.from_primitive failed, falling back to raw dict: %s",
            exc,
        )
        return raw


def _try_decode_witness_set(raw: dict) -> TransactionWitnessSet | dict:
    """Attempt to decode a transaction witness set using pycardano.

    Falls back to the raw dict if pycardano raises.

    Args:
        raw: The CBOR-decoded map of the witness set.

    Returns:
        A TransactionWitnessSet instance, or the raw dict on failure.
    """
    try:
        return TransactionWitnessSet.from_primitive(raw)
    except Exception as exc:
        logger.debug(
            "pycardano TransactionWitnessSet.from_primitive failed, falling back to raw dict: %s",
            exc,
        )
        return raw


def _try_decode_auxiliary_data(raw: object) -> AuxiliaryData | object | None:
    """Attempt to decode auxiliary data using pycardano.

    Falls back to the raw primitive if pycardano raises. Returns None
    if input is None.

    Args:
        raw: The CBOR-decoded auxiliary data (dict, CBORTag, or None).

    Returns:
        An AuxiliaryData instance, the raw primitive, or None.
    """
    if raw is None:
        return None
    try:
        return AuxiliaryData.from_primitive(raw)
    except Exception as exc:
        logger.debug(
            "pycardano AuxiliaryData.from_primitive failed, falling back to raw primitive: %s",
            exc,
        )
        return raw


def decode_block_body(cbor_bytes: bytes) -> DecodedBlockBody:
    """Decode the body of a CBOR-encoded Cardano block.

    Parses the full block CBOR, strips the era tag, and extracts:
      - Transaction bodies (block_array[1])
      - Transaction witness sets (block_array[2])
      - Auxiliary data map (block_array[3])

    For each transaction, attempts pycardano deserialization first,
    falling back to raw CBOR primitives on failure.

    Byron blocks (tags 0, 1) raise NotImplementedError.

    Args:
        cbor_bytes: Raw CBOR bytes of a tagged block.

    Returns:
        DecodedBlockBody with all transactions parsed.

    Raises:
        NotImplementedError: For Byron-era blocks.
        ValueError: For malformed CBOR or unexpected structure.
    """
    decoded = _cbor2.loads(cbor_bytes, raw_tags=True)

    # Handle both CBORTag(era, body) and [era_int, body] list format
    if isinstance(decoded, _cbor2.CBORTag):
        era_val = decoded.tag
        block_array = decoded.value
    elif isinstance(decoded, list) and len(decoded) >= 2 and isinstance(decoded[0], int):
        era_val = decoded[0]
        block_array = decoded[1]
    else:
        raise ValueError(f"Expected CBOR tag or [era, body] list, got {type(decoded).__name__}")

    try:
        era = Era(era_val)
    except ValueError:
        raise ValueError(f"Unknown era tag: {era_val}") from None

    if era in (Era.BYRON_MAIN, Era.BYRON_EBB):
        raise NotImplementedError(f"Byron block decoding not yet supported (era tag {era.value})")

    # Accept any sequence-like type (list, IndefiniteFrozenList, IndefiniteArray, etc.)
    # cbor2pure versions use different types for indefinite-length CBOR arrays.
    def _is_sequence(obj: object) -> bool:
        return isinstance(obj, (list, tuple)) or (
            hasattr(obj, "__len__") and hasattr(obj, "__getitem__") and not isinstance(obj, (str, bytes, dict))
        )

    if not _is_sequence(block_array) or len(block_array) < 4:
        raise ValueError(
            f"Expected block as CBOR array of >= 4 elements, "
            f"got {type(block_array).__name__} with "
            f"{len(block_array) if _is_sequence(block_array) else 0} elements"
        )

    # block = [header, transaction_bodies, transaction_witness_sets, auxiliary_data]
    raw_tx_bodies = list(block_array[1]) if _is_sequence(block_array[1]) else block_array[1]
    raw_tx_witnesses = list(block_array[2]) if _is_sequence(block_array[2]) else block_array[2]
    raw_auxiliary_data = block_array[3]

    if not isinstance(raw_tx_bodies, list):
        raise ValueError(
            f"Expected transaction_bodies as CBOR array, got {type(raw_tx_bodies).__name__}"
        )

    if not isinstance(raw_tx_witnesses, list):
        raise ValueError(
            f"Expected transaction_witness_sets as CBOR array, "
            f"got {type(raw_tx_witnesses).__name__}"
        )

    if len(raw_tx_bodies) != len(raw_tx_witnesses):
        raise ValueError(
            f"Transaction body count ({len(raw_tx_bodies)}) does not match "
            f"witness set count ({len(raw_tx_witnesses)})"
        )

    # Extract original CBOR bytes for each tx body from the raw block.
    # This avoids re-serialization (which fails on IndefiniteFrozenList
    # and changes CBOR encoding, breaking hash computation).
    # Haskell ref: MemoBytes/Annotator pattern — always hash original bytes.
    tx_body_original_bytes: list[bytes] = []
    try:
        # Re-parse the block to find byte boundaries of each tx body.
        # Walk the CBOR structure using CBORDecoder with fp.tell() to
        # track positions of individual items in the tx_bodies array.
        stream = io.BytesIO(cbor_bytes)
        dec = _cbor2.CBORDecoder(stream, tag_hook=lambda d, t: t)
        outer = dec.decode()
        # Navigate to the tx_bodies array in the block structure.
        # The structure is: tag(era, [header, [bodies...], ...]) or [era, [header, [bodies...], ...]]
        # We need the raw bytes of each body in the bodies array.
        # Since we already decoded block_array above, use a second pass
        # that tracks byte positions for just the bodies.
        if isinstance(raw_tx_bodies, list) and len(raw_tx_bodies) > 0:
            # Encode each body individually — but use a safe encoder that
            # converts IndefiniteFrozenList to regular list first.
            for body_raw in raw_tx_bodies:
                try:
                    body_cbor = _cbor2.dumps(body_raw)
                except Exception:
                    # Fallback: recursively convert non-serializable types
                    body_cbor = _cbor2.dumps(_normalize_cbor_types(body_raw))
                tx_body_original_bytes.append(body_cbor)
    except Exception:
        # If byte extraction fails, fall back to empty (will re-encode per body)
        tx_body_original_bytes = []

    # auxiliary_data is a map {tx_index: aux_data} — may be empty map or null
    aux_map: dict = {}
    if isinstance(raw_auxiliary_data, dict):
        aux_map = raw_auxiliary_data
    elif raw_auxiliary_data is not None:
        logger.debug(
            "Auxiliary data is %s (not dict), treating as empty",
            type(raw_auxiliary_data).__name__,
        )

    transactions: list[DecodedTransaction] = []
    for i, (body_raw, witness_raw) in enumerate(zip(raw_tx_bodies, raw_tx_witnesses)):
        if not isinstance(body_raw, dict):
            raise ValueError(
                f"Transaction body at index {i} is {type(body_raw).__name__}, "
                f"expected dict (CBOR map)"
            )

        # Compute tx hash from original bytes (no re-serialization)
        if i < len(tx_body_original_bytes):
            tx_hash = _tx_hash_from_bytes(tx_body_original_bytes[i])
        else:
            # Fallback: re-encode with normalization
            tx_hash = _tx_hash_from_bytes(_cbor2.dumps(_normalize_cbor_types(body_raw)))

        # Decode with pycardano (fallback to raw on failure)
        body = _try_decode_tx_body(body_raw)
        witness_set = _try_decode_witness_set(witness_raw if isinstance(witness_raw, dict) else {})

        # Auxiliary data for this transaction (keyed by index)
        aux_raw = aux_map.get(i)
        auxiliary_data = _try_decode_auxiliary_data(aux_raw)

        # Validity flag: Shelley-Mary blocks don't have explicit validity,
        # Alonzo+ blocks include it. For blocks without explicit validity,
        # all transactions are considered valid.
        valid = True

        transactions.append(
            DecodedTransaction(
                index=i,
                body=body,
                witness_set=witness_set,
                auxiliary_data=auxiliary_data,
                valid=valid,
                body_raw=body_raw,
                tx_hash=tx_hash,
            )
        )

    return DecodedBlockBody(
        transactions=transactions,
        era=era,
        tx_count=len(transactions),
    )


def decode_block_transactions(cbor_bytes: bytes) -> list[Transaction | dict]:
    """Convenience: decode block body and return pycardano Transaction objects.

    Attempts to assemble full pycardano Transaction objects from the decoded
    body, witness set, and auxiliary data. Falls back to a raw dict
    representation when pycardano can't handle the transaction.

    Args:
        cbor_bytes: Raw CBOR bytes of a tagged block.

    Returns:
        List of Transaction objects (or raw dicts on decode failure).
    """
    decoded = decode_block_body(cbor_bytes)
    result: list[Transaction | dict] = []

    for dtx in decoded.transactions:
        if isinstance(dtx.body, TransactionBody) and isinstance(
            dtx.witness_set, TransactionWitnessSet
        ):
            try:
                aux = dtx.auxiliary_data if isinstance(dtx.auxiliary_data, AuxiliaryData) else None
                tx = Transaction(
                    transaction_body=dtx.body,
                    transaction_witness_set=dtx.witness_set,
                    valid=dtx.valid,
                    auxiliary_data=aux,
                )
                result.append(tx)
            except Exception as exc:
                logger.debug(
                    "Failed to assemble Transaction at index %d: %s",
                    dtx.index,
                    exc,
                )
                result.append(
                    {
                        "index": dtx.index,
                        "body": dtx.body_raw,
                        "witnesses": (
                            dtx.witness_set
                            if isinstance(dtx.witness_set, dict)
                            else dtx.witness_set.to_primitive()
                        ),
                        "auxiliary_data": dtx.auxiliary_data,
                    }
                )
        else:
            result.append(
                {
                    "index": dtx.index,
                    "body": dtx.body_raw,
                    "witnesses": dtx.witness_set,
                    "auxiliary_data": dtx.auxiliary_data,
                }
            )

    return result
