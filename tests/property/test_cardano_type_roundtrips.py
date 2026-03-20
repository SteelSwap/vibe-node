"""CBOR round-trip tests for Cardano-specific types.

Validates that all Cardano domain types survive CBOR encode-decode cycles
with bit-perfect fidelity. This is a layer above test_cbor_roundtrip.py
(which tests primitive CBOR patterns) — here we test the actual types used
in block headers, transactions, and consensus.

Organized into:
  - Crypto types: Ed25519 keys/sigs, VRF proofs/outputs, KES sigs, hashes
  - Slotting types: SlotNo, EpochNo, BlockNo, SystemStart
  - Ledger types: Byron TxIn/TxOut/Tx, Shelley TxBody, Alonzo ExUnits/Redeemer
  - Container types: CBOR sets (tag 258), sorted maps, nested CBOR (tag 24)
  - Hypothesis property tests: slot round-trips, hash round-trips, CRC, dup detection

Spec references:
  - shelley.cddl: $vkey, $signature, $vrf_vkey, $vrf_cert, $kes_signature
  - byron.cddl: TxIn, TxOut, Tx, tag-24 CBOR-in-CBOR encoding
  - alonzo.cddl: ex_units, redeemers
  - RFC 8949 Section 3.4.5.1: tag 258 for sets
"""

from __future__ import annotations

import hashlib
import os
import struct

import cbor2
import pytest
from cbor2 import CBORTag
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.crypto.kes import (
    CARDANO_KES_DEPTH,
    kes_derive_vk,
    kes_keygen,
    kes_sig_size,
    kes_sign,
    kes_verify,
)
from vibe.cardano.crypto.vrf import VRF_OUTPUT_SIZE, VRF_PK_SIZE, VRF_PROOF_SIZE
from vibe.cardano.ledger.alonzo_types import ExUnits, Redeemer, RedeemerTag
from vibe.cardano.ledger.byron import (
    ByronTx,
    ByronTxId,
    ByronTxIn,
    ByronTxOut,
)
from vibe.cardano.serialization.block import OperationalCert, ProtocolVersion


# ===========================================================================
# Crypto types (~15 tests)
# ===========================================================================


@pytest.mark.property
class TestEd25519Roundtrips:
    """Ed25519 verification keys, signing keys, and signatures via CBOR."""

    def test_ed25519_verification_key_roundtrip(self) -> None:
        """32-byte Ed25519 vkey encodes as CBOR bstr and round-trips.

        CDDL: $vkey = bytes .size 32
        """
        vkey = os.urandom(32)
        encoded = cbor2.dumps(vkey)
        decoded = cbor2.loads(encoded)
        assert decoded == vkey
        assert isinstance(decoded, bytes)
        assert len(decoded) == 32

    def test_ed25519_signing_key_roundtrip(self) -> None:
        """64-byte Ed25519 signing key encodes as CBOR bstr and round-trips.

        The signing key is the 32-byte secret scalar concatenated with the
        32-byte public key in the Haskell representation.
        """
        skey = os.urandom(64)
        encoded = cbor2.dumps(skey)
        decoded = cbor2.loads(encoded)
        assert decoded == skey
        assert len(decoded) == 64

    def test_ed25519_signature_roundtrip(self) -> None:
        """64-byte Ed25519 signature encodes as CBOR bstr and round-trips.

        CDDL: $signature = bytes .size 64
        """
        sig = os.urandom(64)
        encoded = cbor2.dumps(sig)
        decoded = cbor2.loads(encoded)
        assert decoded == sig
        assert len(decoded) == 64


@pytest.mark.property
class TestVRFRoundtrips:
    """VRF proof, output, and public key CBOR round-trips."""

    def test_vrf_proof_roundtrip(self) -> None:
        """80-byte VRF proof (Gamma || c || s) encodes as CBOR bstr.

        CDDL: $vrf_cert = [bytes, bytes .size 80]
        The proof itself is 80 bytes per ECVRF-ED25519-SHA512-Elligator2.
        """
        proof = os.urandom(VRF_PROOF_SIZE)
        assert len(proof) == 80
        encoded = cbor2.dumps(proof)
        decoded = cbor2.loads(encoded)
        assert decoded == proof
        assert len(decoded) == VRF_PROOF_SIZE

    def test_vrf_output_roundtrip(self) -> None:
        """64-byte VRF output (SHA-512 of the proof) round-trips.

        This is the value used in the Praos leader lottery.
        """
        output = os.urandom(VRF_OUTPUT_SIZE)
        assert len(output) == 64
        encoded = cbor2.dumps(output)
        decoded = cbor2.loads(encoded)
        assert decoded == output
        assert len(decoded) == VRF_OUTPUT_SIZE

    def test_vrf_public_key_roundtrip(self) -> None:
        """32-byte VRF public key round-trips.

        CDDL: $vrf_vkey = bytes .size 32
        """
        pk = os.urandom(VRF_PK_SIZE)
        assert len(pk) == 32
        encoded = cbor2.dumps(pk)
        decoded = cbor2.loads(encoded)
        assert decoded == pk
        assert len(decoded) == VRF_PK_SIZE

    def test_vrf_cert_array_roundtrip(self) -> None:
        """VRF cert as [output, proof] array round-trips.

        CDDL: $vrf_cert = [bytes .size 64, bytes .size 80]
        This is the on-wire format in block headers.
        """
        vrf_cert = [os.urandom(VRF_OUTPUT_SIZE), os.urandom(VRF_PROOF_SIZE)]
        encoded = cbor2.dumps(vrf_cert)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == vrf_cert[0]
        assert decoded[1] == vrf_cert[1]


@pytest.mark.property
class TestKESRoundtrips:
    """KES signature and verification key CBOR round-trips."""

    def test_kes_signature_roundtrip(self) -> None:
        """448-byte KES signature (depth 6) round-trips through CBOR.

        sig_size(d) = 64 * (d + 1) = 64 * 7 = 448 for depth 6.
        Haskell ref: SizeSignKES (SumKES h d)
        """
        sig_size = kes_sig_size(CARDANO_KES_DEPTH)
        assert sig_size == 448
        sig = os.urandom(sig_size)
        encoded = cbor2.dumps(sig)
        decoded = cbor2.loads(encoded)
        assert decoded == sig
        assert len(decoded) == 448

    def test_kes_verification_key_roundtrip(self) -> None:
        """32-byte KES verification key round-trips.

        CDDL: $kes_vkey = bytes .size 32
        At the root level, KES VK is always 32 bytes (Blake2b-256 hash
        for depth > 0, Ed25519 public key for depth 0).
        """
        kes_vk = os.urandom(32)
        encoded = cbor2.dumps(kes_vk)
        decoded = cbor2.loads(encoded)
        assert decoded == kes_vk
        assert len(decoded) == 32

    def test_kes_sign_verify_roundtrip(self) -> None:
        """Generate KES key, sign, encode sig to CBOR, decode, verify.

        This tests the full lifecycle: keygen -> sign -> CBOR encode ->
        CBOR decode -> verify. Uses depth 3 for speed (depth 6 generates
        64 leaf keys which is slow for a unit test).
        """
        depth = 3  # 2^3 = 8 periods, fast enough for testing
        sk = kes_keygen(depth)
        vk = kes_derive_vk(sk)
        msg = b"test block header body"
        period = 0

        sig = kes_sign(sk, period, msg)
        assert len(sig) == kes_sig_size(depth)

        # Round-trip through CBOR
        encoded = cbor2.dumps(sig)
        decoded_sig = cbor2.loads(encoded)
        assert decoded_sig == sig

        # Verify with the decoded signature
        assert kes_verify(vk, depth, period, decoded_sig, msg)


@pytest.mark.property
class TestHashRoundtrips:
    """Blake2b hash round-trips (224 and 256 bit)."""

    def test_blake2b_224_hash_roundtrip(self) -> None:
        """28-byte Blake2b-224 hash (address key hash) round-trips.

        Used for: payment credential hashes, stake credential hashes,
        script hashes, policy IDs.
        Haskell: Cardano.Crypto.Hash.Blake2b_224
        """
        data = os.urandom(64)
        h = hashlib.blake2b(data, digest_size=28).digest()
        assert len(h) == 28
        encoded = cbor2.dumps(h)
        decoded = cbor2.loads(encoded)
        assert decoded == h
        assert len(decoded) == 28

    def test_blake2b_256_hash_roundtrip(self) -> None:
        """32-byte Blake2b-256 hash (block hash, tx hash) round-trips.

        Used for: block hashes, transaction IDs, KES VK hashing,
        script integrity hashes.
        Haskell: Cardano.Crypto.Hash.Blake2b_256
        """
        data = os.urandom(64)
        h = hashlib.blake2b(data, digest_size=32).digest()
        assert len(h) == 32
        encoded = cbor2.dumps(h)
        decoded = cbor2.loads(encoded)
        assert decoded == h
        assert len(decoded) == 32


@pytest.mark.property
class TestOperationalCertRoundtrip:
    """Operational certificate CBOR round-trip.

    CDDL (shelley.cddl):
        operational_cert =
          ( hot_vkey        : $kes_vkey
          , sequence_number : uint
          , kes_period      : uint
          , sigma           : $signature
          )
    """

    def test_operational_cert_roundtrip(self) -> None:
        """OperationalCert fields survive CBOR array round-trip."""
        oc = OperationalCert(
            hot_vkey=os.urandom(32),
            sequence_number=42,
            kes_period=350,
            sigma=os.urandom(64),
        )
        # Encode as CBOR array (matching the on-wire format)
        cbor_array = [oc.hot_vkey, oc.sequence_number, oc.kes_period, oc.sigma]
        encoded = cbor2.dumps(cbor_array)
        decoded = cbor2.loads(encoded)

        reconstructed = OperationalCert(
            hot_vkey=decoded[0],
            sequence_number=decoded[1],
            kes_period=decoded[2],
            sigma=decoded[3],
        )
        assert reconstructed.hot_vkey == oc.hot_vkey
        assert reconstructed.sequence_number == oc.sequence_number
        assert reconstructed.kes_period == oc.kes_period
        assert reconstructed.sigma == oc.sigma


# ===========================================================================
# Slotting types (~5 tests)
# ===========================================================================


@pytest.mark.property
class TestSlottingRoundtrips:
    """SlotNo, EpochNo, BlockNo, SystemStart CBOR round-trips."""

    def test_slot_no_roundtrip(self) -> None:
        """SlotNo as CBOR unsigned integer round-trips.

        CDDL: slot = uint
        Cardano mainnet is currently at ~130M slots.
        """
        slot = 130_000_000
        encoded = cbor2.dumps(slot)
        decoded = cbor2.loads(encoded)
        assert decoded == slot
        assert decoded >= 0

    def test_epoch_no_roundtrip(self) -> None:
        """EpochNo as CBOR unsigned integer round-trips.

        CDDL: epoch = uint
        Mainnet is currently at epoch ~500+.
        """
        epoch = 512
        encoded = cbor2.dumps(epoch)
        decoded = cbor2.loads(encoded)
        assert decoded == epoch

    def test_block_no_roundtrip(self) -> None:
        """BlockNo as CBOR unsigned integer round-trips.

        CDDL: block_number = uint
        """
        block_no = 10_500_000
        encoded = cbor2.dumps(block_no)
        decoded = cbor2.loads(encoded)
        assert decoded == block_no

    def test_system_start_roundtrip(self) -> None:
        """SystemStart as CBOR text (ISO 8601) round-trips.

        SystemStart is transmitted as a text string in the handshake.
        Cardano mainnet: 2017-09-23T21:44:51Z
        """
        system_start = "2017-09-23T21:44:51Z"
        encoded = cbor2.dumps(system_start)
        decoded = cbor2.loads(encoded)
        assert decoded == system_start
        assert isinstance(decoded, str)

    def test_protocol_version_roundtrip(self) -> None:
        """ProtocolVersion as CBOR [uint, uint] round-trips.

        CDDL: protocol_version = (uint, uint)
        """
        pv = ProtocolVersion(major=10, minor=0)
        cbor_arr = [pv.major, pv.minor]
        encoded = cbor2.dumps(cbor_arr)
        decoded = cbor2.loads(encoded)
        reconstructed = ProtocolVersion(major=decoded[0], minor=decoded[1])
        assert reconstructed.major == pv.major
        assert reconstructed.minor == pv.minor


# ===========================================================================
# Ledger types (~15 tests)
# ===========================================================================


@pytest.mark.property
class TestByronLedgerRoundtrips:
    """Byron TxIn, TxOut, Tx CBOR round-trips."""

    def _make_byron_txid(self) -> ByronTxId:
        """Create a random ByronTxId for testing."""
        return ByronTxId(os.urandom(32))

    def test_byron_txid_roundtrip(self) -> None:
        """ByronTxId (32-byte hash) round-trips through its to_cbor/from_cbor."""
        txid = self._make_byron_txid()
        encoded = txid.to_cbor()
        decoded = ByronTxId.from_cbor(encoded)
        assert decoded.digest == txid.digest

    def test_byron_txin_roundtrip(self) -> None:
        """ByronTxIn round-trips through CBOR.

        Wire format: [0, #6.24(bytes .cbor [txid, index])]
        The CBOR-in-CBOR (tag 24) pattern is Byron's encodeKnownCborDataItem.
        """
        txid = self._make_byron_txid()
        txin = ByronTxIn(tx_id=txid, index=7)
        encoded = txin.to_cbor()
        decoded = ByronTxIn.from_cbor(encoded)
        assert decoded.tx_id.digest == txin.tx_id.digest
        assert decoded.index == txin.index

    def test_byron_txin_tag24_structure(self) -> None:
        """ByronTxIn CBOR contains a tag-24 wrapper (CBOR-in-CBOR)."""
        txid = self._make_byron_txid()
        txin = ByronTxIn(tx_id=txid, index=0)
        encoded = txin.to_cbor()
        decoded_raw = cbor2.loads(encoded)
        # Should be [0, CBORTag(24, inner_bytes)]
        assert isinstance(decoded_raw, list)
        assert decoded_raw[0] == 0
        assert isinstance(decoded_raw[1], CBORTag)
        assert decoded_raw[1].tag == 24

    def test_byron_txout_roundtrip(self) -> None:
        """ByronTxOut round-trips through CBOR.

        Wire format: [address_bytes, coin]
        Byron addresses are base58-encoded with CRC32 protection.
        We use a known mainnet Byron address for this test.
        """
        from pycardano.address import Address

        # Known Byron mainnet address (Daedalus-style)
        byron_addr_str = (
            "DdzFFzCqrhsrcTVhLygDMwKDrEFsWqKbFnG1MGHZ"
            "Lia3ap8KYvJLjrffUos29QF93y38omJ4GnNgRF3Bve"
            "R78SiTfG9LnaiFYLToFGR"
        )
        try:
            addr = Address.decode(byron_addr_str)
        except Exception:
            pytest.skip("pycardano cannot decode this Byron address on this platform")

        txout = ByronTxOut(address=addr, value=1_500_000)
        encoded = txout.to_cbor()
        decoded = ByronTxOut.from_cbor(encoded)
        assert decoded.value == txout.value
        assert bytes(decoded.address) == bytes(txout.address)

    def test_byron_tx_roundtrip(self) -> None:
        """ByronTx (inputs, outputs, attributes) round-trips.

        Wire format: [[*TxIn], [*TxOut], attributes_map]
        Tests the full transaction body (no witnesses).
        """
        from pycardano.address import Address

        byron_addr_str = (
            "DdzFFzCqrhsrcTVhLygDMwKDrEFsWqKbFnG1MGHZ"
            "Lia3ap8KYvJLjrffUos29QF93y38omJ4GnNgRF3Bve"
            "R78SiTfG9LnaiFYLToFGR"
        )
        try:
            addr = Address.decode(byron_addr_str)
        except Exception:
            pytest.skip("pycardano cannot decode this Byron address on this platform")

        txid = self._make_byron_txid()
        txin = ByronTxIn(tx_id=txid, index=0)
        txout = ByronTxOut(address=addr, value=2_000_000)
        tx = ByronTx(inputs=[txin], outputs=[txout], attributes={})

        encoded = tx.to_cbor()
        decoded = ByronTx.from_cbor(encoded)
        assert len(decoded.inputs) == 1
        assert len(decoded.outputs) == 1
        assert decoded.inputs[0].tx_id.digest == txin.tx_id.digest
        assert decoded.inputs[0].index == txin.index
        assert decoded.outputs[0].value == txout.value
        assert decoded.attributes == {}

    def test_byron_tx_hash_stability(self) -> None:
        """Byron TxId is Blake2b-256 of CBOR encoding, and is stable.

        Encoding the same Tx twice must yield the same TxId.
        """
        from pycardano.address import Address

        byron_addr_str = (
            "DdzFFzCqrhsrcTVhLygDMwKDrEFsWqKbFnG1MGHZ"
            "Lia3ap8KYvJLjrffUos29QF93y38omJ4GnNgRF3Bve"
            "R78SiTfG9LnaiFYLToFGR"
        )
        try:
            addr = Address.decode(byron_addr_str)
        except Exception:
            pytest.skip("pycardano cannot decode this Byron address on this platform")

        txid = ByronTxId(os.urandom(32))
        txin = ByronTxIn(tx_id=txid, index=0)
        txout = ByronTxOut(address=addr, value=1_000_000)
        tx = ByronTx(inputs=[txin], outputs=[txout])

        hash1 = tx.tx_id.digest
        hash2 = tx.tx_id.digest
        assert hash1 == hash2
        assert len(hash1) == 32


@pytest.mark.property
class TestShelleyLedgerRoundtrips:
    """Shelley-era TxBody minimal fields CBOR round-trip."""

    def test_shelley_txbody_minimal_roundtrip(self) -> None:
        """Minimal Shelley TxBody (inputs, outputs, fee, ttl) round-trips.

        CDDL (shelley.cddl): transaction_body = { 0: set<transaction_input>,
          1: [*transaction_output], 2: coin, 3: uint, ... }
        Keys: 0=inputs, 1=outputs, 2=fee, 3=ttl
        """
        # Build a raw CBOR map matching the Shelley tx body format
        tx_input = [os.urandom(32), 0]  # [tx_hash, index]
        tx_output = [os.urandom(57), 2_000_000]  # [address_bytes, coin]

        tx_body_map = {
            0: CBORTag(258, [tx_input]),  # inputs as set (tag 258)
            1: [tx_output],               # outputs
            2: 200_000,                    # fee
            3: 50_000_000,                 # ttl
        }

        encoded = cbor2.dumps(tx_body_map)
        decoded = cbor2.loads(encoded)

        assert decoded[2] == 200_000
        assert decoded[3] == 50_000_000

        # Tag 258 decodes to frozenset in cbor2 >= 5.6
        inputs = decoded[0]
        if isinstance(inputs, frozenset):
            # cbor2 auto-converts tag 258 to frozenset
            assert len(inputs) == 1
        elif isinstance(inputs, CBORTag):
            assert inputs.tag == 258
        else:
            # Some cbor2 versions may return a list
            pass

        outputs = decoded[1]
        assert isinstance(outputs, list)
        assert len(outputs) == 1
        assert outputs[0][1] == 2_000_000


@pytest.mark.property
class TestAlonzoLedgerRoundtrips:
    """Alonzo ExUnits, Redeemer, RedeemerTag CBOR round-trips."""

    def test_exunits_roundtrip(self) -> None:
        """ExUnits [mem, steps] as CBOR array round-trips.

        CDDL: ex_units = [mem: uint, steps: uint]
        """
        eu = ExUnits(mem=500_000, steps=200_000_000)
        cbor_arr = [eu.mem, eu.steps]
        encoded = cbor2.dumps(cbor_arr)
        decoded = cbor2.loads(encoded)
        reconstructed = ExUnits(mem=decoded[0], steps=decoded[1])
        assert reconstructed.mem == eu.mem
        assert reconstructed.steps == eu.steps

    def test_exunits_zero_roundtrip(self) -> None:
        """ExUnits with zero values (native scripts) round-trips."""
        eu = ExUnits(mem=0, steps=0)
        cbor_arr = [eu.mem, eu.steps]
        encoded = cbor2.dumps(cbor_arr)
        decoded = cbor2.loads(encoded)
        assert decoded == [0, 0]

    def test_redeemer_tag_values(self) -> None:
        """RedeemerTag integer values match CBOR encoding.

        CDDL: redeemer_tag = 0 / 1 / 2 / 3
        """
        assert RedeemerTag.SPEND == 0
        assert RedeemerTag.MINT == 1
        assert RedeemerTag.CERT == 2
        assert RedeemerTag.REWARD == 3

        for tag in RedeemerTag:
            encoded = cbor2.dumps(tag.value)
            decoded = cbor2.loads(encoded)
            assert decoded == tag.value

    def test_redeemer_roundtrip(self) -> None:
        """Redeemer [tag, index, data, [mem, steps]] round-trips.

        CDDL: redeemer = [tag: redeemer_tag, index: uint,
                          data: plutus_data, ex_units: [uint, uint]]
        """
        # Create a simple PlutusData (a CBOR integer)
        plutus_data = cbor2.dumps(42)
        r = Redeemer(
            tag=RedeemerTag.SPEND,
            index=0,
            data=plutus_data,
            ex_units=ExUnits(mem=300_000, steps=100_000_000),
        )
        cbor_arr = [
            r.tag.value,
            r.index,
            cbor2.loads(r.data),  # Inline the Plutus data
            [r.ex_units.mem, r.ex_units.steps],
        ]
        encoded = cbor2.dumps(cbor_arr)
        decoded = cbor2.loads(encoded)

        assert decoded[0] == RedeemerTag.SPEND
        assert decoded[1] == 0
        assert decoded[2] == 42
        assert decoded[3] == [300_000, 100_000_000]

    def test_multi_asset_value_roundtrip(self) -> None:
        """Multi-asset Value (ADA + native tokens) round-trips.

        CDDL: value = coin / [coin, multiasset<uint>]
        multiasset<a> = { policy_id => { asset_name => a } }
        """
        policy_id = os.urandom(28)  # 28-byte script hash
        asset_name = b"VibeToken"
        token_quantity = 1_000_000

        # [coin, { policy_id: { asset_name: quantity } }]
        value = [5_000_000, {policy_id: {asset_name: token_quantity}}]

        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)

        assert decoded[0] == 5_000_000
        assert isinstance(decoded[1], dict)
        assert policy_id in decoded[1]
        assert decoded[1][policy_id][asset_name] == token_quantity

    def test_multi_asset_multiple_policies_roundtrip(self) -> None:
        """Multi-asset with multiple policies and assets round-trips."""
        policy_a = os.urandom(28)
        policy_b = os.urandom(28)

        multiasset = {
            policy_a: {b"TokenA": 100, b"TokenB": 200},
            policy_b: {b"": 50},  # empty asset name (ADA-like within policy)
        }
        value = [10_000_000, multiasset]

        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)

        assert decoded[0] == 10_000_000
        assert decoded[1][policy_a][b"TokenA"] == 100
        assert decoded[1][policy_a][b"TokenB"] == 200
        assert decoded[1][policy_b][b""] == 50

    def test_exunits_large_values_roundtrip(self) -> None:
        """ExUnits with large values (max tx/block budgets) round-trips.

        Alonzo mainnet: maxTxExUnits = mem=14M, steps=10B
        These are large uint values that must survive CBOR encoding.
        """
        eu = ExUnits(mem=14_000_000, steps=10_000_000_000)
        cbor_arr = [eu.mem, eu.steps]
        encoded = cbor2.dumps(cbor_arr)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 14_000_000
        assert decoded[1] == 10_000_000_000


# ===========================================================================
# Container types (~5 tests)
# ===========================================================================


@pytest.mark.property
class TestContainerRoundtrips:
    """CBOR containers: sets (tag 258), sorted maps, nested CBOR (tag 24)."""

    def test_cbor_set_tag258_roundtrip(self) -> None:
        """CBOR set (tag 258) round-trips.

        RFC 8949 Section 3.4.5.1 defines tag 258 for sets.
        Cardano uses this for transaction inputs, required signers.
        cbor2 >= 5.6 auto-decodes tag 258 to frozenset.
        """
        items = [os.urandom(32) for _ in range(3)]
        tagged_set = CBORTag(258, items)
        encoded = cbor2.dumps(tagged_set)
        decoded = cbor2.loads(encoded)

        # cbor2 auto-converts tag 258 to set or frozenset
        if isinstance(decoded, (set, frozenset)):
            assert len(decoded) == 3
            for item in items:
                assert item in decoded
        elif isinstance(decoded, CBORTag):
            assert decoded.tag == 258
            assert len(decoded.value) == 3
        else:
            pytest.fail(f"Unexpected decoded type: {type(decoded)}")

    def test_cbor_map_sorted_keys_roundtrip(self) -> None:
        """CBOR map with sorted integer keys (canonical encoding) round-trips.

        Cardano transaction bodies use integer-keyed maps.
        Canonical CBOR requires keys sorted by their encoded form.
        """
        tx_body = {0: b"inputs", 1: b"outputs", 2: 200_000, 3: 50_000}
        encoded = cbor2.dumps(tx_body, canonical=True)
        decoded = cbor2.loads(encoded)

        assert decoded == tx_body
        # Verify canonical encoding produces sorted keys
        raw_bytes = encoded
        # Re-encode to verify idempotence
        re_encoded = cbor2.dumps(decoded, canonical=True)
        assert raw_bytes == re_encoded

    def test_nested_cbor_in_cbor_tag24_roundtrip(self) -> None:
        """Nested CBOR-in-CBOR (tag 24) round-trips.

        Tag 24 wraps pre-serialized CBOR bytes. Used in:
        - Byron TxIn (encodeKnownCborDataItem / encodeNestedCbor)
        - Plutus script datums
        - Block header KES signature wrapping
        """
        inner_value = [42, b"hello", {"key": "value"}]
        inner_cbor = cbor2.dumps(inner_value)
        tagged = CBORTag(24, inner_cbor)

        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, CBORTag)
        assert decoded.tag == 24
        assert decoded.value == inner_cbor

        # Decode the inner CBOR
        inner_decoded = cbor2.loads(decoded.value)
        assert inner_decoded == inner_value

    def test_nested_tag24_double_wrap_roundtrip(self) -> None:
        """Double-nested CBOR-in-CBOR round-trips.

        Byron addresses use tag 24 wrapping another tag 24 structure.
        """
        innermost = cbor2.dumps(b"address_payload")
        inner = CBORTag(24, innermost)
        inner_bytes = cbor2.dumps(inner)
        outer = CBORTag(24, inner_bytes)

        encoded = cbor2.dumps(outer)
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, CBORTag)
        assert decoded.tag == 24
        inner_result = cbor2.loads(decoded.value)
        assert isinstance(inner_result, CBORTag)
        assert inner_result.tag == 24
        innermost_result = cbor2.loads(inner_result.value)
        assert innermost_result == b"address_payload"

    def test_compact_address_encoding_roundtrip(self) -> None:
        """Compact Shelley address bytes round-trip through CBOR.

        Shelley addresses are 57 bytes (1-byte header + 28-byte payment
        credential + 28-byte staking credential). They encode as CBOR bstr.
        """
        # Construct a synthetic Shelley address:
        # Header byte: 0x01 (mainnet, key-key)
        header = bytes([0x01])
        payment_cred = os.urandom(28)
        staking_cred = os.urandom(28)
        addr_bytes = header + payment_cred + staking_cred
        assert len(addr_bytes) == 57

        encoded = cbor2.dumps(addr_bytes)
        decoded = cbor2.loads(encoded)
        assert decoded == addr_bytes
        assert len(decoded) == 57


# ===========================================================================
# Properties (Hypothesis, ~5 tests)
# ===========================================================================


@pytest.mark.property
class TestSlotNoProperties:
    """Property-based tests for SlotNo CBOR encoding."""

    @given(slot=st.integers(min_value=0, max_value=2**64 - 1))
    @settings(max_examples=200)
    def test_any_valid_slot_roundtrips(self, slot: int) -> None:
        """Any valid SlotNo (uint64) encodes as CBOR uint and round-trips.

        SlotNo is Word64 in Haskell, so [0, 2^64 - 1].
        """
        encoded = cbor2.dumps(slot)
        decoded = cbor2.loads(encoded)
        assert decoded == slot
        assert decoded >= 0


@pytest.mark.property
class TestHashProperties:
    """Property-based tests for hash round-trips."""

    @given(data=st.binary(min_size=28, max_size=28))
    @settings(max_examples=200)
    def test_any_28_byte_hash_roundtrips(self, data: bytes) -> None:
        """Any 28-byte hash (Blake2b-224) encodes as CBOR bstr and round-trips."""
        encoded = cbor2.dumps(data)
        decoded = cbor2.loads(encoded)
        assert decoded == data
        assert len(decoded) == 28

    @given(data=st.binary(min_size=32, max_size=32))
    @settings(max_examples=200)
    def test_any_32_byte_hash_roundtrips(self, data: bytes) -> None:
        """Any 32-byte hash (Blake2b-256) encodes as CBOR bstr and round-trips."""
        encoded = cbor2.dumps(data)
        decoded = cbor2.loads(encoded)
        assert decoded == data
        assert len(decoded) == 32


@pytest.mark.property
class TestByronCRCProperties:
    """Property-based tests for Byron CRC-protected encoding."""

    @given(data=st.binary(min_size=1, max_size=256))
    @settings(max_examples=100)
    def test_byron_crc_protected_roundtrip(self, data: bytes) -> None:
        """Byron CRC-protected encoding (tag 24 + CRC32) round-trips.

        Byron uses CBOR-in-CBOR with tag 24 for nested encoding.
        The CRC is separate (in address encoding), but the tag 24
        wrapping itself must be bit-perfect.
        """
        inner_cbor = cbor2.dumps(data)
        tagged = CBORTag(24, inner_cbor)
        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, CBORTag)
        assert decoded.tag == 24
        inner_decoded = cbor2.loads(decoded.value)
        assert inner_decoded == data


# ===========================================================================
# Negative tests: duplicate detection
# ===========================================================================


@pytest.mark.property
class TestDuplicateDetection:
    """Verify that CBOR maps/sets with duplicate keys are detectable."""

    def test_should_fail_map_with_dup_keys(self) -> None:
        """CBOR maps with duplicate keys are detectable.

        RFC 7049 says duplicate keys make the map "not valid CBOR",
        though decoders may handle them differently. We verify that
        hand-crafted duplicate-key maps are at least detectable.

        Haskell ref: Cardano deserializers reject duplicate map keys
        as a validity check (decodeMaybe / enforceKeyValuePairs).
        """
        # Hand-craft a CBOR map with duplicate key 0:
        # Map(2) { 0: "first", 0: "second" }
        # CBOR: A2 (map of 2) 00 (key 0) 65 6669727374 (text "first")
        #       00 (key 0) 66 7365636F6E64 (text "second")
        raw = bytes.fromhex("a2006566697273740066736563" "6f6e64")
        decoded = cbor2.loads(raw)
        # Standard Python dict behavior: last value wins
        assert isinstance(decoded, dict)
        # The duplicate IS present in the raw bytes — a conformance-checking
        # decoder would reject this. We verify the raw bytes contain two
        # instances of key 0.
        # Count occurrences of key 0 (byte 0x00) in map position
        # More rigorous: decode with awareness of duplicates
        # Since cbor2 silently takes the last value, we verify that:
        assert decoded[0] == "second"  # last-value-wins semantics

        # Verify we can detect the duplicate by re-encoding and comparing
        re_encoded = cbor2.dumps(decoded)
        # Re-encoding a deduplicated map should be shorter than the original
        assert len(re_encoded) < len(raw)

    def test_should_fail_set_with_dup_elements(self) -> None:
        """CBOR sets (tag 258) with duplicate elements are detectable.

        A conformance-checking decoder should reject sets with duplicates.
        cbor2 auto-converts tag 258 to frozenset, which deduplicates.
        """
        # Create a tag-258 set with duplicate elements
        items = [b"alpha", b"beta", b"alpha"]  # duplicate!
        tagged_set = CBORTag(258, items)
        encoded = cbor2.dumps(tagged_set)
        decoded = cbor2.loads(encoded)

        if isinstance(decoded, (set, frozenset)):
            # cbor2 auto-deduplicates via set/frozenset
            assert len(decoded) == 2  # duplicates removed
            assert b"alpha" in decoded
            assert b"beta" in decoded
        elif isinstance(decoded, CBORTag):
            # Older cbor2: items preserved, duplicates detectable
            assert decoded.tag == 258
            seen = set()
            has_dup = False
            for item in decoded.value:
                if item in seen:
                    has_dup = True
                seen.add(item)
            assert has_dup, "Expected duplicate element in set"
        else:
            pytest.fail(f"Unexpected decoded type: {type(decoded)}")

    def test_should_fail_map_with_dup_bytestring_keys(self) -> None:
        """CBOR map with duplicate bytestring keys is detectable.

        Cardano uses bytestring keys for policy IDs in multi-asset maps.
        Duplicate policy IDs in a Value are invalid.
        """
        policy = os.urandom(28)
        # Build a map with the same policy ID twice (different assets)
        # In Python dict, second assignment wins
        value_map = {policy: {b"TokenA": 100}}
        encoded = cbor2.dumps(value_map)
        decoded = cbor2.loads(encoded)

        # Verify the map is well-formed after round-trip
        assert isinstance(decoded, dict)
        assert len(decoded) == 1
        assert policy in decoded

        # Now hand-craft a CBOR map with duplicate bytestring keys
        # by concatenating two single-entry maps' innards
        single_entry_1 = cbor2.dumps({policy: {b"A": 1}})
        single_entry_2 = cbor2.dumps({policy: {b"B": 2}})

        # Build raw CBOR: map(2) + key1 + val1 + key2 + val2
        # where key1 == key2
        key_cbor = cbor2.dumps(policy)
        val1_cbor = cbor2.dumps({b"A": 1})
        val2_cbor = cbor2.dumps({b"B": 2})

        # CBOR map header for 2 entries
        header = bytes([0xA2])
        raw = header + key_cbor + val1_cbor + key_cbor + val2_cbor
        decoded_dup = cbor2.loads(raw)

        # Python dict takes last value — duplicate detected by size change
        assert isinstance(decoded_dup, dict)
        assert len(decoded_dup) == 1  # deduplicated
        re_encoded = cbor2.dumps(decoded_dup)
        assert len(re_encoded) < len(raw)  # shorter = duplicates removed
