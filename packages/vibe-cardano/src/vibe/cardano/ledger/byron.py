"""Byron-era transaction types and UTxO model.

Byron uses a different transaction format than Shelley+ eras.  The key
differences:

* Transactions are wrapped in TxAux (tx + witnesses), not the Shelley
  Transaction envelope.
* TxIn uses CBOR-in-CBOR via tag 24 (``encodeKnownCborDataItem`` in the
  Haskell node -- see ``Cardano.Chain.Common.CBOR.encodeNestedCbor``).
* Addresses are base58-encoded with a double-hash scheme
  (SHA3-256 then Blake2b-224).
* No scripts, no metadata, no fee fields in the transaction body --
  fees are implicit (sum of inputs minus sum of outputs).

Spec references:
    * Byron CDDL schema (``byron.cddl``)
    * ``cardano-ledger/byron/ledger/impl/src/Cardano/Chain/UTxO/Tx.hs``
    * ``cardano-ledger/byron/ledger/impl/src/Cardano/Chain/UTxO/TxAux.hs``
    * ``cardano-ledger/byron/ledger/impl/src/Cardano/Chain/UTxO/TxWitness.hs``
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import ClassVar

import cbor2pure as cbor2
from cbor2pure import CBORTag
from pycardano.address import Address

# ---------------------------------------------------------------------------
# Lovelace
# ---------------------------------------------------------------------------


Lovelace = int
"""Byron lovelace is just an integer.  We alias it for readability."""


# ---------------------------------------------------------------------------
# TxId
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ByronTxId:
    """Blake2b-256 hash of the CBOR-encoded transaction body.

    In Byron the TxId is ``hash(serialize(Tx))`` where ``Tx`` is the
    three-element array ``[inputs, outputs, attributes]``.

    Haskell ref: ``Cardano.Chain.UTxO.TxId`` (a ``Hash Tx``).
    """

    digest: bytes
    """32-byte Blake2b-256 digest."""

    HASH_SIZE: ClassVar[int] = 32

    def __post_init__(self) -> None:
        if len(self.digest) != self.HASH_SIZE:
            raise ValueError(
                f"ByronTxId digest must be {self.HASH_SIZE} bytes, got {len(self.digest)}"
            )

    @classmethod
    def from_tx(cls, tx: ByronTx) -> ByronTxId:
        """Compute the TxId by hashing the CBOR encoding of *tx*."""
        encoded = tx.to_cbor()
        digest = hashlib.blake2b(encoded, digest_size=cls.HASH_SIZE).digest()
        return cls(digest)

    def to_cbor(self) -> bytes:
        """CBOR-encode the TxId (just the raw 32-byte hash)."""
        return cbor2.dumps(self.digest)

    @classmethod
    def from_cbor(cls, data: bytes) -> ByronTxId:
        """Decode a CBOR-encoded TxId."""
        digest = cbor2.loads(data)
        if not isinstance(digest, bytes):
            raise ValueError(f"Expected bytes for TxId, got {type(digest)}")
        return cls(digest)

    def __repr__(self) -> str:
        return f"ByronTxId({self.digest.hex()[:16]}...)"


# ---------------------------------------------------------------------------
# TxIn
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ByronTxIn:
    """A Byron transaction input: reference to a previous output.

    CBOR encoding (Haskell ``ToCBOR TxIn``):
        ``[0, #6.24(bytes .cbor [txid, index])]``

    This is a two-element array:
        0. Tag byte ``0`` (the ``TxInUtxo`` variant -- the only variant)
        1. CBOR tag 24 wrapping a CBOR-encoded ``[TxId, Word32]`` pair

    The CBOR-in-CBOR pattern (tag 24) is Byron's ``encodeKnownCborDataItem``
    / ``encodeNestedCbor`` -- it serializes the inner value to bytes, then
    wraps those bytes with CBOR tag 24.
    """

    tx_id: ByronTxId
    """Hash of the transaction containing the output we're spending."""

    index: int
    """Index of the output within that transaction (Word32 in Haskell)."""

    def to_cbor(self) -> bytes:
        """Encode this TxIn to CBOR following the Byron wire format.

        Format: ``[0, #6.24(bytes .cbor [txid_bytes, index])]``
        """
        # Inner payload: CBOR-encode [tx_id_digest, index]
        inner = cbor2.dumps([self.tx_id.digest, self.index])
        # Wrap in tag 24 (CBOR-in-CBOR)
        tagged = CBORTag(24, inner)
        # Outer array: [0, tagged]
        return cbor2.dumps([0, tagged])

    @classmethod
    def from_cbor(cls, data: bytes) -> ByronTxIn:
        """Decode a CBOR-encoded Byron TxIn."""
        outer = cbor2.loads(data)
        return cls._from_primitive(outer)

    @classmethod
    def _from_primitive(cls, outer: list) -> ByronTxIn:
        """Construct from an already-decoded CBOR primitive."""
        if not isinstance(outer, list) or len(outer) != 2:
            raise ValueError(f"Expected 2-element list for TxIn, got {outer!r}")

        tag = outer[0]
        if tag != 0:
            raise ValueError(f"Unknown TxIn tag: {tag} (only tag 0 = TxInUtxo supported)")

        tagged = outer[1]
        if not isinstance(tagged, CBORTag) or tagged.tag != 24:
            raise ValueError(f"Expected CBOR tag 24, got {tagged!r}")

        # Decode the inner CBOR-in-CBOR payload
        inner = cbor2.loads(tagged.value)
        if not isinstance(inner, list) or len(inner) != 2:
            raise ValueError(f"Expected [txid, index] in tag 24, got {inner!r}")

        tx_id = ByronTxId(inner[0])
        index = inner[1]
        return cls(tx_id=tx_id, index=index)

    def __repr__(self) -> str:
        return f"ByronTxIn({self.tx_id.digest.hex()[:16]}..., {self.index})"


# ---------------------------------------------------------------------------
# TxOut
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ByronTxOut:
    """A Byron transaction output: address + lovelace value.

    CBOR encoding (Haskell ``ToCBOR TxOut``):
        ``[address_cbor_bytes, coin]``

    The address is CBOR-encoded as its raw bytes representation (the full
    Byron address structure including tag 24 wrapper and CRC32).
    """

    address: Address
    """Byron base58 address (pycardano Address with Byron payload)."""

    value: Lovelace
    """Amount in lovelace."""

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError(f"Lovelace value must be non-negative, got {self.value}")

    def to_cbor(self) -> bytes:
        """Encode this TxOut to CBOR.

        Format: ``[address_bytes, coin]``

        The address is serialized as its raw CBOR bytes (pycardano's
        ``bytes(address)`` produces the correct Byron wire format).
        """
        addr_bytes = bytes(self.address)
        return cbor2.dumps([addr_bytes, self.value])

    @classmethod
    def from_cbor(cls, data: bytes) -> ByronTxOut:
        """Decode a CBOR-encoded Byron TxOut."""
        decoded = cbor2.loads(data)
        return cls._from_primitive(decoded)

    @classmethod
    def _from_primitive(cls, decoded: list) -> ByronTxOut:
        """Construct from an already-decoded CBOR primitive."""
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError(f"Expected 2-element list for TxOut, got {decoded!r}")
        addr_bytes = decoded[0]
        if isinstance(addr_bytes, bytes):
            address = Address.from_primitive(addr_bytes)
        else:
            raise ValueError(f"Expected bytes for address, got {type(addr_bytes)}")
        value = decoded[1]
        return cls(address=address, value=value)

    def __repr__(self) -> str:
        return f"ByronTxOut({self.address.encode()[:20]}..., {self.value})"


# ---------------------------------------------------------------------------
# Tx (transaction body)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ByronTx:
    """Byron transaction body: inputs, outputs, and attributes.

    CBOR encoding (Haskell ``ToCBOR Tx``):
        ``[[*TxIn], [*TxOut], attributes]``

    Three-element array:
        0. Non-empty list of ``TxIn``
        1. Non-empty list of ``TxOut``
        2. Attributes map (always empty ``{}`` in practice)

    Note: ``attributes`` is an empty map encoded as ``{}`` (CBOR map with
    zero entries).  The Haskell type is ``Attributes ()`` which serializes
    to ``mkAttributes () = Attributes () (UnparsedFields M.empty)``.
    """

    inputs: list[ByronTxIn]
    """Non-empty list of transaction inputs."""

    outputs: list[ByronTxOut]
    """Non-empty list of transaction outputs."""

    attributes: dict = field(default_factory=dict)
    """Transaction attributes (always empty for Byron)."""

    def __post_init__(self) -> None:
        if not self.inputs:
            raise ValueError("Byron transaction must have at least one input")
        if not self.outputs:
            raise ValueError("Byron transaction must have at least one output")

    @property
    def tx_id(self) -> ByronTxId:
        """Compute the transaction ID (Blake2b-256 of CBOR encoding)."""
        return ByronTxId.from_tx(self)

    def to_cbor(self) -> bytes:
        """Encode to CBOR: ``[[*TxIn], [*TxOut], attributes]``."""
        inputs_prim = [self._txin_to_primitive(txin) for txin in self.inputs]
        outputs_prim = [self._txout_to_primitive(txout) for txout in self.outputs]
        return cbor2.dumps([inputs_prim, outputs_prim, self.attributes])

    @classmethod
    def from_cbor(cls, data: bytes) -> ByronTx:
        """Decode a CBOR-encoded Byron Tx."""
        decoded = cbor2.loads(data)
        return cls._from_primitive(decoded)

    @classmethod
    def _from_primitive(cls, decoded: list) -> ByronTx:
        """Construct from an already-decoded CBOR primitive."""
        if not isinstance(decoded, list) or len(decoded) != 3:
            raise ValueError(f"Expected 3-element list for Tx, got {decoded!r}")

        raw_inputs, raw_outputs, attributes = decoded
        inputs = [ByronTxIn._from_primitive(inp) for inp in raw_inputs]
        outputs = [ByronTxOut._from_primitive(out) for out in raw_outputs]

        # Normalize attributes
        if not isinstance(attributes, dict):
            attributes = {}
        return cls(inputs=inputs, outputs=outputs, attributes=attributes)

    @staticmethod
    def _txin_to_primitive(txin: ByronTxIn) -> list:
        """Convert a TxIn to its CBOR primitive representation."""
        inner = cbor2.dumps([txin.tx_id.digest, txin.index])
        return [0, CBORTag(24, inner)]

    @staticmethod
    def _txout_to_primitive(txout: ByronTxOut) -> list:
        """Convert a TxOut to its CBOR primitive representation."""
        return [bytes(txout.address), txout.value]

    def __repr__(self) -> str:
        return f"ByronTx(inputs={len(self.inputs)}, outputs={len(self.outputs)})"


# ---------------------------------------------------------------------------
# TxWitness (Byron witness types)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ByronVKWitness:
    """Byron verification-key witness.

    CBOR encoding (Haskell ``ToCBOR TxInWitness`` VKWitness variant):
        ``[0, #6.24(bytes .cbor [vk, sig])]``

    Where ``vk`` is a 64-byte extended Ed25519 public key and ``sig`` is
    a 64-byte Ed25519 signature.
    """

    VK_TAG: ClassVar[int] = 0

    verification_key: bytes
    """64-byte extended Ed25519 public key."""

    signature: bytes
    """64-byte Ed25519 signature over the TxSigData (hash of Tx)."""

    def to_cbor(self) -> bytes:
        """Encode to CBOR: ``[0, #6.24([vk, sig])]``."""
        inner = cbor2.dumps([self.verification_key, self.signature])
        return cbor2.dumps([self.VK_TAG, CBORTag(24, inner)])

    @classmethod
    def _from_tagged_inner(cls, inner_bytes: bytes) -> ByronVKWitness:
        """Decode from the tag-24 inner payload."""
        inner = cbor2.loads(inner_bytes)
        if not isinstance(inner, list) or len(inner) != 2:
            raise ValueError(f"Expected [vk, sig] in VKWitness, got {inner!r}")
        return cls(verification_key=inner[0], signature=inner[1])

    def __repr__(self) -> str:
        return f"ByronVKWitness(vk={self.verification_key.hex()[:16]}...)"


@dataclass(frozen=True, slots=True)
class ByronRedeemWitness:
    """Byron redeem witness (for redemption addresses from the genesis block).

    CBOR encoding:
        ``[2, #6.24(bytes .cbor [redeem_vk, redeem_sig])]``
    """

    REDEEM_TAG: ClassVar[int] = 2

    redeem_key: bytes
    """32-byte Ed25519 redemption public key."""

    redeem_signature: bytes
    """64-byte Ed25519 redemption signature."""

    def to_cbor(self) -> bytes:
        """Encode to CBOR: ``[2, #6.24([key, sig])]``."""
        inner = cbor2.dumps([self.redeem_key, self.redeem_signature])
        return cbor2.dumps([self.REDEEM_TAG, CBORTag(24, inner)])

    @classmethod
    def _from_tagged_inner(cls, inner_bytes: bytes) -> ByronRedeemWitness:
        """Decode from the tag-24 inner payload."""
        inner = cbor2.loads(inner_bytes)
        if not isinstance(inner, list) or len(inner) != 2:
            raise ValueError(f"Expected [key, sig] in RedeemWitness, got {inner!r}")
        return cls(redeem_key=inner[0], redeem_signature=inner[1])

    def __repr__(self) -> str:
        return f"ByronRedeemWitness(key={self.redeem_key.hex()[:16]}...)"


# Unified type alias
ByronTxInWitness = ByronVKWitness | ByronRedeemWitness


def witness_from_cbor(data: bytes) -> ByronTxInWitness:
    """Decode a single CBOR-encoded Byron witness."""
    decoded = cbor2.loads(data)
    return _witness_from_primitive(decoded)


def _witness_from_primitive(decoded: list) -> ByronTxInWitness:
    """Construct a witness from an already-decoded CBOR primitive."""
    if not isinstance(decoded, list) or len(decoded) != 2:
        raise ValueError(f"Expected 2-element list for witness, got {decoded!r}")

    tag = decoded[0]
    tagged = decoded[1]

    if not isinstance(tagged, CBORTag) or tagged.tag != 24:
        raise ValueError(f"Expected CBOR tag 24 in witness, got {tagged!r}")

    if tag == ByronVKWitness.VK_TAG:
        return ByronVKWitness._from_tagged_inner(tagged.value)
    elif tag == ByronRedeemWitness.REDEEM_TAG:
        return ByronRedeemWitness._from_tagged_inner(tagged.value)
    else:
        raise ValueError(f"Unknown Byron witness tag: {tag}")


# ---------------------------------------------------------------------------
# TxAux (transaction + witnesses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ByronTxAux:
    """Byron transaction with witnesses.

    CBOR encoding (Haskell ``ToCBOR TxAux``):
        ``[tx, [*witness]]``

    Two-element array:
        0. The ``Tx`` (body)
        1. List of ``TxInWitness``

    This is the top-level transaction type that appears in Byron blocks.
    """

    tx: ByronTx
    """The transaction body."""

    witnesses: list[ByronTxInWitness]
    """List of witnesses (one per input, typically)."""

    @property
    def tx_id(self) -> ByronTxId:
        """Transaction ID (delegates to the inner Tx)."""
        return self.tx.tx_id

    def to_cbor(self) -> bytes:
        """Encode to CBOR: ``[tx_primitive, [witness_primitives...]]``."""
        tx_prim = cbor2.loads(self.tx.to_cbor())
        wit_prims = [cbor2.loads(w.to_cbor()) for w in self.witnesses]
        return cbor2.dumps([tx_prim, wit_prims])

    @classmethod
    def from_cbor(cls, data: bytes) -> ByronTxAux:
        """Decode a CBOR-encoded Byron TxAux."""
        decoded = cbor2.loads(data)
        return cls._from_primitive(decoded)

    @classmethod
    def _from_primitive(cls, decoded: list) -> ByronTxAux:
        """Construct from an already-decoded CBOR primitive."""
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError(f"Expected 2-element list for TxAux, got {decoded!r}")

        tx = ByronTx._from_primitive(decoded[0])
        witnesses = [_witness_from_primitive(w) for w in decoded[1]]
        return cls(tx=tx, witnesses=witnesses)

    def __repr__(self) -> str:
        return f"ByronTxAux(tx={self.tx!r}, witnesses={len(self.witnesses)})"
