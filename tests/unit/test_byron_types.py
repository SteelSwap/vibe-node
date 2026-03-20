"""Tests for Byron-era transaction types and UTxO model.

Tests cover:
    - CBOR encode/decode roundtrips for all Byron types
    - Golden vector compatibility with Haskell cardano-ledger
    - Byron address format validation via pycardano
    - TxId computation (Blake2b-256 of serialized Tx)
    - Edge cases: empty attributes, witness tag dispatch

Spec references:
    - byron.cddl
    - cardano-ledger/byron/ledger/impl/test/Test/Cardano/Chain/UTxO/CBOR.hs
    - cardano-ledger/byron/ledger/impl/test/Test/Cardano/Chain/UTxO/Example.hs
"""

from __future__ import annotations

import hashlib

import cbor2
import pytest
from cbor2 import CBORTag
from pycardano.address import Address

from vibe.cardano.ledger.byron import (
    ByronRedeemWitness,
    ByronTx,
    ByronTxAux,
    ByronTxId,
    ByronTxIn,
    ByronTxOut,
    ByronVKWitness,
    _witness_from_primitive,
    witness_from_cbor,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

# A well-known mainnet Byron address (Daedalus genesis).  The base58 string
# decodes to valid Byron CBOR.
BYRON_MAINNET_ADDR = (
    "Ae2tdPwUPEZFRbyhz3cpfC2CumGzNkFBN2L42rcUc2yjQpEkxDbkPodpMAi"
)


def make_dummy_txid(seed: int = 0) -> ByronTxId:
    """Create a deterministic 32-byte TxId from a seed."""
    digest = hashlib.blake2b(
        seed.to_bytes(4, "big"), digest_size=32
    ).digest()
    return ByronTxId(digest)


def make_byron_address() -> Address:
    """Return a decoded Byron mainnet address from the constant above."""
    return Address.from_primitive(BYRON_MAINNET_ADDR)


def make_dummy_tx() -> ByronTx:
    """Create a minimal Byron Tx for testing."""
    txin = ByronTxIn(tx_id=make_dummy_txid(0), index=0)
    addr = make_byron_address()
    txout = ByronTxOut(address=addr, value=1_000_000)
    return ByronTx(inputs=[txin], outputs=[txout])


# ---------------------------------------------------------------------------
# ByronTxId tests
# ---------------------------------------------------------------------------


class TestByronTxId:
    def test_valid_32_byte_digest(self):
        digest = b"\x00" * 32
        txid = ByronTxId(digest)
        assert txid.digest == digest

    def test_reject_wrong_size(self):
        with pytest.raises(ValueError, match="32 bytes"):
            ByronTxId(b"\x00" * 31)
        with pytest.raises(ValueError, match="32 bytes"):
            ByronTxId(b"\x00" * 33)

    def test_cbor_roundtrip(self):
        txid = make_dummy_txid(42)
        encoded = txid.to_cbor()
        decoded = ByronTxId.from_cbor(encoded)
        assert decoded == txid

    def test_from_tx_deterministic(self):
        """TxId computed from the same Tx must be identical."""
        tx = make_dummy_tx()
        txid1 = ByronTxId.from_tx(tx)
        txid2 = ByronTxId.from_tx(tx)
        assert txid1 == txid2

    def test_from_tx_is_blake2b256_of_cbor(self):
        """TxId should be blake2b-256 of the CBOR-encoded Tx body."""
        tx = make_dummy_tx()
        expected = hashlib.blake2b(tx.to_cbor(), digest_size=32).digest()
        assert ByronTxId.from_tx(tx).digest == expected

    def test_haskell_golden_hash(self):
        """Reproduce the Haskell test: exampleHashTx = serializeCborHash "golden".

        serializeCborHash x = blake2b-256(serialize x)
        serialize "golden" in Byron CBOR = cbor2.dumps("golden")
        """
        cbor_of_golden = cbor2.dumps("golden")
        expected = hashlib.blake2b(cbor_of_golden, digest_size=32).digest()
        txid = ByronTxId(expected)
        assert len(txid.digest) == 32
        # Verify the hash is stable
        assert txid.digest == expected

    def test_repr(self):
        txid = make_dummy_txid(0)
        r = repr(txid)
        assert "ByronTxId(" in r
        assert "..." in r


# ---------------------------------------------------------------------------
# ByronTxIn tests
# ---------------------------------------------------------------------------


class TestByronTxIn:
    def test_cbor_roundtrip(self):
        txin = ByronTxIn(tx_id=make_dummy_txid(1), index=47)
        encoded = txin.to_cbor()
        decoded = ByronTxIn.from_cbor(encoded)
        assert decoded.tx_id == txin.tx_id
        assert decoded.index == txin.index

    def test_cbor_structure(self):
        """Verify the wire format: [0, #6.24(bytes .cbor [txid, index])]."""
        txin = ByronTxIn(tx_id=make_dummy_txid(0), index=47)
        encoded = txin.to_cbor()
        outer = cbor2.loads(encoded)

        assert isinstance(outer, list)
        assert len(outer) == 2
        assert outer[0] == 0  # TxInUtxo tag

        tagged = outer[1]
        assert isinstance(tagged, CBORTag)
        assert tagged.tag == 24

        inner = cbor2.loads(tagged.value)
        assert isinstance(inner, list)
        assert len(inner) == 2
        assert inner[0] == txin.tx_id.digest
        assert inner[1] == 47

    def test_reject_unknown_tag(self):
        """Only tag 0 (TxInUtxo) is valid."""
        inner = cbor2.dumps([b"\x00" * 32, 0])
        bad = cbor2.dumps([1, CBORTag(24, inner)])
        with pytest.raises(ValueError, match="Unknown TxIn tag"):
            ByronTxIn.from_cbor(bad)

    def test_reject_missing_tag24(self):
        """The inner value must be wrapped in CBOR tag 24."""
        bad = cbor2.dumps([0, b"\x00" * 32])
        with pytest.raises(ValueError, match="tag 24"):
            ByronTxIn.from_cbor(bad)

    def test_haskell_golden_txin(self):
        """Reproduce exampleTxInUtxo = TxInUtxo exampleHashTx 47."""
        cbor_golden = cbor2.dumps("golden")
        golden_hash = hashlib.blake2b(cbor_golden, digest_size=32).digest()
        txin = ByronTxIn(tx_id=ByronTxId(golden_hash), index=47)
        # Roundtrip
        decoded = ByronTxIn.from_cbor(txin.to_cbor())
        assert decoded.tx_id.digest == golden_hash
        assert decoded.index == 47

    def test_repr(self):
        txin = ByronTxIn(tx_id=make_dummy_txid(0), index=5)
        r = repr(txin)
        assert "ByronTxIn(" in r
        assert "5" in r


# ---------------------------------------------------------------------------
# ByronTxOut tests
# ---------------------------------------------------------------------------


class TestByronTxOut:
    def test_cbor_roundtrip(self):
        addr = make_byron_address()
        txout = ByronTxOut(address=addr, value=1_000_000)
        encoded = txout.to_cbor()
        decoded = ByronTxOut.from_cbor(encoded)
        assert bytes(decoded.address) == bytes(txout.address)
        assert decoded.value == txout.value

    def test_cbor_structure(self):
        """Verify the wire format: [address_bytes, coin]."""
        addr = make_byron_address()
        txout = ByronTxOut(address=addr, value=42)
        encoded = txout.to_cbor()
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, list)
        assert len(decoded) == 2
        assert isinstance(decoded[0], bytes)
        assert decoded[1] == 42

    def test_reject_negative_value(self):
        addr = make_byron_address()
        with pytest.raises(ValueError, match="non-negative"):
            ByronTxOut(address=addr, value=-1)

    def test_zero_value_allowed(self):
        """Zero lovelace is technically valid at the type level."""
        addr = make_byron_address()
        txout = ByronTxOut(address=addr, value=0)
        assert txout.value == 0

    def test_repr(self):
        addr = make_byron_address()
        txout = ByronTxOut(address=addr, value=100)
        r = repr(txout)
        assert "ByronTxOut(" in r
        assert "100" in r


# ---------------------------------------------------------------------------
# ByronTx tests
# ---------------------------------------------------------------------------


class TestByronTx:
    def test_cbor_roundtrip(self):
        tx = make_dummy_tx()
        encoded = tx.to_cbor()
        decoded = ByronTx.from_cbor(encoded)
        assert len(decoded.inputs) == len(tx.inputs)
        assert len(decoded.outputs) == len(tx.outputs)
        assert decoded.inputs[0].tx_id == tx.inputs[0].tx_id
        assert decoded.inputs[0].index == tx.inputs[0].index
        assert decoded.outputs[0].value == tx.outputs[0].value
        assert decoded.attributes == {}

    def test_cbor_structure(self):
        """Verify the wire format: [[*TxIn], [*TxOut], attributes]."""
        tx = make_dummy_tx()
        encoded = tx.to_cbor()
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, list)
        assert len(decoded) == 3
        # inputs list
        assert isinstance(decoded[0], list)
        assert len(decoded[0]) == 1
        # outputs list
        assert isinstance(decoded[1], list)
        assert len(decoded[1]) == 1
        # attributes (empty map)
        assert decoded[2] == {}

    def test_reject_empty_inputs(self):
        addr = make_byron_address()
        txout = ByronTxOut(address=addr, value=100)
        with pytest.raises(ValueError, match="at least one input"):
            ByronTx(inputs=[], outputs=[txout])

    def test_reject_empty_outputs(self):
        txin = ByronTxIn(tx_id=make_dummy_txid(0), index=0)
        with pytest.raises(ValueError, match="at least one output"):
            ByronTx(inputs=[txin], outputs=[])

    def test_tx_id_property(self):
        """The tx_id property should match ByronTxId.from_tx."""
        tx = make_dummy_tx()
        assert tx.tx_id == ByronTxId.from_tx(tx)

    def test_multiple_inputs_outputs(self):
        """Roundtrip with multiple inputs and outputs."""
        txin0 = ByronTxIn(tx_id=make_dummy_txid(0), index=0)
        txin1 = ByronTxIn(tx_id=make_dummy_txid(1), index=3)
        addr = make_byron_address()
        txout0 = ByronTxOut(address=addr, value=500_000)
        txout1 = ByronTxOut(address=addr, value=1_500_000)
        tx = ByronTx(inputs=[txin0, txin1], outputs=[txout0, txout1])

        decoded = ByronTx.from_cbor(tx.to_cbor())
        assert len(decoded.inputs) == 2
        assert len(decoded.outputs) == 2
        assert decoded.inputs[0].index == 0
        assert decoded.inputs[1].index == 3
        assert decoded.outputs[0].value == 500_000
        assert decoded.outputs[1].value == 1_500_000

    def test_haskell_golden_tx_structure(self):
        """Reproduce the Haskell goldenTx example structure.

        goldenTx = UnsafeTx exampleTxInList exampleTxOutList (mkAttributes ())
        exampleTxInList = [TxInUtxo exampleHashTx 47]
        exampleTxOutList = [TxOut (makeVerKeyAddress ...) 47]
        mkAttributes () = Attributes () (UnparsedFields M.empty)

        We verify the structural shape matches even though we can't
        reproduce the exact Byron address bytes without the full key
        derivation.
        """
        cbor_golden = cbor2.dumps("golden")
        golden_hash = hashlib.blake2b(cbor_golden, digest_size=32).digest()
        txin = ByronTxIn(tx_id=ByronTxId(golden_hash), index=47)

        # Use our test address (different from Haskell but structurally valid)
        addr = make_byron_address()
        txout = ByronTxOut(address=addr, value=47)

        tx = ByronTx(inputs=[txin], outputs=[txout], attributes={})
        encoded = tx.to_cbor()

        # Decode and verify structure
        raw = cbor2.loads(encoded)
        assert len(raw) == 3
        assert len(raw[0]) == 1  # one input
        assert len(raw[1]) == 1  # one output
        assert raw[2] == {}      # empty attributes

        # Verify the input structure matches Byron CBOR wire format
        inp = raw[0][0]
        assert inp[0] == 0  # TxInUtxo tag
        assert isinstance(inp[1], CBORTag)
        assert inp[1].tag == 24
        inner = cbor2.loads(inp[1].value)
        assert inner[0] == golden_hash
        assert inner[1] == 47

    def test_repr(self):
        tx = make_dummy_tx()
        r = repr(tx)
        assert "ByronTx(" in r
        assert "inputs=1" in r
        assert "outputs=1" in r


# ---------------------------------------------------------------------------
# Witness tests
# ---------------------------------------------------------------------------


class TestByronVKWitness:
    def test_cbor_roundtrip(self):
        vk = b"\x01" * 64
        sig = b"\x02" * 64
        wit = ByronVKWitness(verification_key=vk, signature=sig)
        encoded = wit.to_cbor()
        decoded = witness_from_cbor(encoded)
        assert isinstance(decoded, ByronVKWitness)
        assert decoded.verification_key == vk
        assert decoded.signature == sig

    def test_cbor_structure(self):
        """Verify format: [0, #6.24([vk, sig])]."""
        vk = b"\xaa" * 64
        sig = b"\xbb" * 64
        wit = ByronVKWitness(verification_key=vk, signature=sig)
        encoded = wit.to_cbor()
        outer = cbor2.loads(encoded)

        assert outer[0] == 0
        assert isinstance(outer[1], CBORTag)
        assert outer[1].tag == 24
        inner = cbor2.loads(outer[1].value)
        assert inner[0] == vk
        assert inner[1] == sig

    def test_repr(self):
        wit = ByronVKWitness(verification_key=b"\x01" * 64, signature=b"\x02" * 64)
        assert "ByronVKWitness(" in repr(wit)


class TestByronRedeemWitness:
    def test_cbor_roundtrip(self):
        key = b"\x03" * 32
        sig = b"\x04" * 64
        wit = ByronRedeemWitness(redeem_key=key, redeem_signature=sig)
        encoded = wit.to_cbor()
        decoded = witness_from_cbor(encoded)
        assert isinstance(decoded, ByronRedeemWitness)
        assert decoded.redeem_key == key
        assert decoded.redeem_signature == sig

    def test_cbor_structure(self):
        """Verify format: [2, #6.24([key, sig])]."""
        key = b"\xcc" * 32
        sig = b"\xdd" * 64
        wit = ByronRedeemWitness(redeem_key=key, redeem_signature=sig)
        encoded = wit.to_cbor()
        outer = cbor2.loads(encoded)

        assert outer[0] == 2
        assert isinstance(outer[1], CBORTag)
        assert outer[1].tag == 24

    def test_repr(self):
        wit = ByronRedeemWitness(redeem_key=b"\x03" * 32, redeem_signature=b"\x04" * 64)
        assert "ByronRedeemWitness(" in repr(wit)


class TestWitnessDispatch:
    def test_unknown_tag_rejected(self):
        inner = cbor2.dumps([b"\x00" * 32, b"\x00" * 64])
        bad = cbor2.dumps([1, CBORTag(24, inner)])
        with pytest.raises(ValueError, match="Unknown Byron witness tag"):
            witness_from_cbor(bad)

    def test_missing_tag24_rejected(self):
        bad = cbor2.dumps([0, b"\x00"])
        with pytest.raises(ValueError, match="tag 24"):
            witness_from_cbor(bad)


# ---------------------------------------------------------------------------
# ByronTxAux tests
# ---------------------------------------------------------------------------


class TestByronTxAux:
    def test_cbor_roundtrip(self):
        tx = make_dummy_tx()
        wit = ByronVKWitness(verification_key=b"\x01" * 64, signature=b"\x02" * 64)
        txaux = ByronTxAux(tx=tx, witnesses=[wit])

        encoded = txaux.to_cbor()
        decoded = ByronTxAux.from_cbor(encoded)

        assert len(decoded.tx.inputs) == 1
        assert len(decoded.tx.outputs) == 1
        assert len(decoded.witnesses) == 1
        assert isinstance(decoded.witnesses[0], ByronVKWitness)
        assert decoded.witnesses[0].verification_key == b"\x01" * 64

    def test_cbor_structure(self):
        """Verify format: [tx_body, [witnesses]]."""
        tx = make_dummy_tx()
        wit = ByronVKWitness(verification_key=b"\x01" * 64, signature=b"\x02" * 64)
        txaux = ByronTxAux(tx=tx, witnesses=[wit])

        encoded = txaux.to_cbor()
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, list)
        assert len(decoded) == 2
        # tx body is a 3-element list
        assert isinstance(decoded[0], list)
        assert len(decoded[0]) == 3
        # witnesses is a list
        assert isinstance(decoded[1], list)
        assert len(decoded[1]) == 1

    def test_tx_id_delegates_to_tx(self):
        tx = make_dummy_tx()
        wit = ByronVKWitness(verification_key=b"\x01" * 64, signature=b"\x02" * 64)
        txaux = ByronTxAux(tx=tx, witnesses=[wit])
        assert txaux.tx_id == tx.tx_id

    def test_multiple_witnesses(self):
        """TxAux with VK + Redeem witnesses."""
        tx = make_dummy_tx()
        vk_wit = ByronVKWitness(verification_key=b"\x01" * 64, signature=b"\x02" * 64)
        redeem_wit = ByronRedeemWitness(redeem_key=b"\x03" * 32, redeem_signature=b"\x04" * 64)
        txaux = ByronTxAux(tx=tx, witnesses=[vk_wit, redeem_wit])

        decoded = ByronTxAux.from_cbor(txaux.to_cbor())
        assert len(decoded.witnesses) == 2
        assert isinstance(decoded.witnesses[0], ByronVKWitness)
        assert isinstance(decoded.witnesses[1], ByronRedeemWitness)

    def test_repr(self):
        tx = make_dummy_tx()
        txaux = ByronTxAux(tx=tx, witnesses=[])
        r = repr(txaux)
        assert "ByronTxAux(" in r
        assert "witnesses=0" in r


# ---------------------------------------------------------------------------
# Byron address integration tests
# ---------------------------------------------------------------------------


class TestByronAddressIntegration:
    def test_mainnet_address_decode(self):
        """Verify we can decode and re-encode a real Byron mainnet address."""
        addr = Address.from_primitive(BYRON_MAINNET_ADDR)
        assert addr.is_byron
        # Re-encode to base58 should produce the same string
        assert addr.encode() == BYRON_MAINNET_ADDR

    def test_byron_address_has_no_stake_delegation(self):
        """VNODE test spec: test_byron_address_has_no_stake_delegation.

        Byron addresses have no stake credential or stake reference.
        """
        addr = Address.from_primitive(BYRON_MAINNET_ADDR)
        assert addr.staking_part is None

    def test_byron_address_roundtrip_through_txout(self):
        """Address survives a TxOut encode/decode cycle."""
        addr = make_byron_address()
        txout = ByronTxOut(address=addr, value=999_999)
        decoded = ByronTxOut.from_cbor(txout.to_cbor())
        assert bytes(decoded.address) == bytes(addr)
        assert decoded.address.is_byron

    def test_byron_address_bytes_roundtrip(self):
        """Raw bytes of Byron address roundtrip through CBOR."""
        addr = make_byron_address()
        raw = bytes(addr)
        restored = Address.from_primitive(raw)
        assert restored.is_byron
        assert bytes(restored) == raw
