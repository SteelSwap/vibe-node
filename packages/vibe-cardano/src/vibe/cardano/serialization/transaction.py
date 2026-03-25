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


def _cbor_dumps(obj: object) -> bytes:
    """Encode to CBOR bytes."""
    return _cbor2.dumps(obj)


def _tx_hash(body_primitive: dict) -> bytes:
    """Compute transaction hash: Blake2b-256 of the CBOR-encoded body.

    The transaction ID is the hash of the serialized transaction body,
    matching the Haskell node's behavior (Crypto.Hash.Blake2b_256).

    Args:
        body_primitive: The raw CBOR primitive (map) of the transaction body.

    Returns:
        32-byte Blake2b-256 digest.
    """
    body_cbor = _cbor_dumps(body_primitive)
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

    if not isinstance(block_array, list) or len(block_array) < 4:
        raise ValueError(
            f"Expected block as CBOR array of >= 4 elements, "
            f"got {type(block_array).__name__} with "
            f"{len(block_array) if isinstance(block_array, list) else 0} elements"
        )

    # block = [header, transaction_bodies, transaction_witness_sets, auxiliary_data]
    raw_tx_bodies = block_array[1]
    raw_tx_witnesses = block_array[2]
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

    # auxiliary_data is a map {tx_index: aux_data} — may be empty map or null
    aux_map: dict = {}
    if isinstance(raw_auxiliary_data, dict):
        aux_map = raw_auxiliary_data
    elif raw_auxiliary_data is not None:
        # Some eras encode empty auxiliary data as null rather than {}
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

        # Compute tx hash from the raw body primitive
        tx_hash = _tx_hash(body_raw)

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
