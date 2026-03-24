"""Tests for Shelley witness, epoch boundary, and pool registration validation gaps.

These tests cover validation rules that were missing or under-tested in the
initial Shelley UTXO/UTXOW and delegation implementations:

1. Bootstrap (Byron) address witness handling
2. MissingScriptWitnessesUTxOW -- script-locked input without script witness
3. Extraneous script witnesses (Shelley allows them -- no rejection)
4. Epoch boundary crossing -- TTL spans an epoch boundary
5. Instant stake distribution -- delegation visible after epoch delay
6. Pool metadata hash size validation
7. VRF key uniqueness across pools
8. Pool reward address wrong network ID
9. Pool metadata URL too long (>64 bytes)
10. Duplicate VRF on re-registration by a different pool
11. VRF reuse after pool retirement
12. Network ID in output address

Spec references:
    - Shelley ledger formal spec, Sections 9-10 (UTXO, UTXOW)
    - Shelley ledger formal spec, Section 8 (DELEG, POOL rules)
    - Shelley CDDL: ``url = tstr .size (0..64)``, ``pool_metadata_hash = $hash32``
    - ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Utxow.hs``
    - ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Pool.hs``
"""

from __future__ import annotations

import hashlib
from fractions import Fraction

import pytest
from pycardano import (
    TransactionBody,
    TransactionInput,
    TransactionOutput,
)
from pycardano.address import Address
from pycardano.certificate import (
    PoolParams,
    PoolRegistration,
    StakeCredential,
    StakeDelegation,
)
from pycardano.hash import (
    PoolKeyHash,
    PoolMetadataHash,
    ScriptHash,
    TransactionId,
    VerificationKeyHash,
)
from pycardano.key import PaymentSigningKey, PaymentVerificationKey
from pycardano.nativescript import ScriptPubkey
from pycardano.network import Network
from pycardano.pool_params import PoolMetadata
from pycardano.witness import TransactionWitnessSet, VerificationKeyWitness

from vibe.cardano.ledger.shelley import (
    ShelleyProtocolParams,
    ShelleyUTxO,
    validate_shelley_utxo,
    validate_shelley_witnesses,
)
from vibe.cardano.ledger.shelley_delegation import (
    DelegationError,
    DelegationState,
    process_certificate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_hash(prefix: int, size: int = 28) -> bytes:
    """Create a deterministic fake hash for testing."""
    return bytes([prefix] * size)


def _make_signing_key(seed: int = 0) -> PaymentSigningKey:
    """Create a deterministic signing key from a seed."""
    seed_bytes = seed.to_bytes(32, "big")
    return PaymentSigningKey(seed_bytes)


def _make_key_pair(seed: int = 0) -> tuple[PaymentSigningKey, PaymentVerificationKey]:
    """Create a deterministic signing/verification key pair."""
    sk = _make_signing_key(seed)
    vk = sk.to_verification_key()
    return sk, vk


def _make_address(vk: PaymentVerificationKey, network: Network = Network.TESTNET) -> Address:
    """Create a Shelley enterprise address from a verification key."""
    return Address(payment_part=vk.hash(), network=network)


def _make_tx_id(seed: int = 0) -> TransactionId:
    """Create a deterministic TransactionId from a seed."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=32).digest()
    return TransactionId(digest)


def _sign_tx_body(tx_body: TransactionBody, sk: PaymentSigningKey) -> VerificationKeyWitness:
    """Sign a transaction body and return a VKey witness."""
    tx_body_hash = tx_body.hash()
    signature = sk.sign(tx_body_hash)
    vk = sk.to_verification_key()
    return VerificationKeyWitness(vkey=vk, signature=signature)


def _make_script_address(script_hash_bytes: bytes, network: Network = Network.TESTNET) -> Address:
    """Create a Shelley script address (enterprise, script payment credential)."""
    return Address(payment_part=ScriptHash(script_hash_bytes), network=network)


def _stake_credential(prefix: int = 0xAA) -> StakeCredential:
    """Create a test StakeCredential with a fake verification key hash."""
    return StakeCredential(VerificationKeyHash(_fake_hash(prefix)))


def _pool_key_hash_obj(prefix: int = 0xBB) -> PoolKeyHash:
    """Create a test PoolKeyHash."""
    return PoolKeyHash(_fake_hash(prefix))


def _pool_params(
    operator_prefix: int = 0xBB,
    vrf_prefix: int = 0xCC,
    reward_account: bytes | None = None,
    pool_metadata: PoolMetadata | None = None,
) -> PoolParams:
    """Create test PoolParams with configurable VRF key and metadata."""
    if reward_account is None:
        # Default: testnet reward address header 0xe0 (VKey, testnet network=0)
        reward_account = bytes([0xE0]) + _fake_hash(0xDD)
    return PoolParams(
        operator=PoolKeyHash(_fake_hash(operator_prefix)),
        vrf_keyhash=_fake_hash(vrf_prefix, size=32),
        pledge=100_000_000,  # 100 ADA
        cost=340_000_000,  # 340 ADA min cost
        margin=Fraction(1, 100),  # 1% margin
        reward_account=reward_account,
        pool_owners=[VerificationKeyHash(_fake_hash(operator_prefix))],
        relays=None,
        pool_metadata=pool_metadata,
    )


# Test params: testnet (network_id=0) with small fees
TEST_PARAMS = ShelleyProtocolParams(
    min_fee_a=1,
    min_fee_b=100,
    max_tx_size=16384,
    min_utxo_value=1_000_000,
    key_deposit=2_000_000,
    pool_deposit=500_000_000,
    min_pool_cost=340_000_000,
    network_id=0,  # testnet
)


# ===========================================================================
# 1. Bootstrap (Byron) address witness
# ===========================================================================


class TestBootstrapAddressWitness:
    """Test that VKey witnesses work for spending from a regular Shelley address.

    In Shelley, Byron-era bootstrap addresses use a different witness format
    (bootstrap witnesses, key 2 in the witness set). Our current implementation
    does not yet support bootstrap witnesses -- it only handles VKey witnesses.
    This test documents the expected behavior: VKey witnesses for Shelley
    addresses work, and the bootstrap witness path is a known gap.

    Spec ref: Shelley formal spec, Section 10 (UTXOW)
    Haskell ref: ``bootstrapWitKeyHash`` in ``Cardano.Ledger.Shelley.Rules.Utxow``
    """

    def test_vkey_witness_for_shelley_address_succeeds(self):
        """A VKey witness that matches the payment key hash is accepted."""
        sk, vk = _make_key_pair(seed=42)
        addr = _make_address(vk, network=Network.TESTNET)
        tx_id = _make_tx_id(100)
        txin = TransactionInput(tx_id, 0)
        txout = TransactionOutput(addr, 5_000_000)
        utxo_set: ShelleyUTxO = {txin: txout}

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 3_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        wit = _sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_shelley_witnesses(tx_body, witness_set, utxo_set)
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_bootstrap_address_without_bootstrap_witness_fails(self):
        """A Byron bootstrap address without a proper bootstrap witness should
        fail with a missing witness error since VKey witness won't match the
        bootstrap address format.

        This documents a known limitation -- our witness validation currently
        does not handle the bootstrap witness path (key 2 in witness set CDDL).
        """
        sk, vk = _make_key_pair(seed=42)

        # Create a fake "bootstrap-style" address by using a different key hash
        # so the VKey witness won't match
        other_sk, other_vk = _make_key_pair(seed=99)
        addr = _make_address(other_vk, network=Network.TESTNET)
        tx_id = _make_tx_id(101)
        txin = TransactionInput(tx_id, 0)
        txout = TransactionOutput(addr, 5_000_000)
        utxo_set: ShelleyUTxO = {txin: txout}

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 3_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        # Sign with the wrong key -- this simulates missing bootstrap witness
        wit = _sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_shelley_witnesses(tx_body, witness_set, utxo_set)
        assert any("MissingVKeyWitnessesUTxOW" in e for e in errors)


# ===========================================================================
# 2. MissingScriptWitnesses
# ===========================================================================


class TestMissingScriptWitnesses:
    """Test that spending from a script-locked UTxO without providing the
    script in the witness set is rejected.

    Spec ref: Shelley formal spec, Section 10 (UTXOW)
        scriptsNeeded txb utxo ⊆ dom (txscripts tx)
    Haskell ref: ``MissingScriptWitnessesUTxOW`` in
        ``Cardano.Ledger.Shelley.Rules.Utxow``
    """

    def test_script_locked_input_without_script_witness_rejected(self):
        """Input references a script-locked UTxO but no script in witness set."""
        script_hash_bytes = hashlib.blake2b(b"test_script", digest_size=28).digest()
        script_addr = _make_script_address(script_hash_bytes, Network.TESTNET)

        tx_id = _make_tx_id(200)
        txin = TransactionInput(tx_id, 0)
        txout = TransactionOutput(script_addr, 5_000_000)
        utxo_set: ShelleyUTxO = {txin: txout}

        sk, vk = _make_key_pair(seed=1)
        dest_addr = _make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 3_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        # No script in witness set -- only a VKey witness
        wit = _sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_shelley_witnesses(tx_body, witness_set, utxo_set)
        assert any("MissingScriptWitnessesUTxOW" in e for e in errors), (
            f"Expected MissingScriptWitnessesUTxOW, got: {errors}"
        )


# ===========================================================================
# 3. Extraneous script witnesses
# ===========================================================================


class TestExtraneousScriptWitnesses:
    """Test that including a native script in the witness set that no input
    references does NOT cause rejection in Shelley.

    In Shelley, the spec checks that scriptsNeeded ⊆ dom(txscripts), but does
    NOT require dom(txscripts) ⊆ scriptsNeeded. Extraneous scripts are
    tolerated. The Alonzo era later tightened this.

    Spec ref: Shelley formal spec, Section 10 (UTXOW)
    Haskell ref: Shelley does not have ``ExtraneousScriptWitnessesUTxOW``
        -- that failure was added in Alonzo.
    """

    def test_extraneous_script_in_witness_set_accepted(self):
        """Tx includes a native script that no input references -- still valid
        in Shelley.
        """
        sk, vk = _make_key_pair(seed=50)
        addr = _make_address(vk, network=Network.TESTNET)
        tx_id = _make_tx_id(300)
        txin = TransactionInput(tx_id, 0)
        txout = TransactionOutput(addr, 5_000_000)
        utxo_set: ShelleyUTxO = {txin: txout}

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 3_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        wit = _sign_tx_body(tx_body, sk)

        # Add an unreferenced native script (ScriptPubkey for some random key)
        unreferenced_script = ScriptPubkey(VerificationKeyHash(_fake_hash(0xFF)))

        witness_set = TransactionWitnessSet(
            vkey_witnesses=[wit],
            native_scripts=[unreferenced_script],
        )

        errors = validate_shelley_witnesses(tx_body, witness_set, utxo_set)
        # Shelley does NOT reject extraneous scripts
        assert errors == [], f"Shelley should accept extraneous scripts, got: {errors}"


# ===========================================================================
# 4. Epoch boundary crossing (TTL)
# ===========================================================================


class TestEpochBoundaryCrossing:
    """Test TTL behavior when a transaction's validity spans an epoch boundary.

    In Shelley, an epoch is 432000 slots (5 days at 1-second slots on mainnet).
    The TTL check is simply: current_slot < ttl. A tx with TTL in epoch N+1
    should be valid in epoch N but rejected once the slot passes.

    Spec ref: Shelley formal spec, Section 9 (ExpiredUTxO)
    Haskell ref: ``ExpiredUTxO`` in ``ShelleyUtxoPredFailure``
    """

    EPOCH_LENGTH = 432_000  # slots per epoch on mainnet

    def test_tx_valid_before_epoch_boundary(self):
        """Tx with TTL in the next epoch is valid in the current epoch."""
        sk, vk = _make_key_pair(seed=60)
        addr = _make_address(vk, network=Network.TESTNET)
        tx_id = _make_tx_id(400)
        txin = TransactionInput(tx_id, 0)
        utxo_set: ShelleyUTxO = {txin: TransactionOutput(addr, 5_000_000)}

        # TTL is 100 slots into epoch 2 (epoch boundary at slot 432000)
        ttl = self.EPOCH_LENGTH + 100
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 3_000_000)],
            fee=2_000_000,
            ttl=ttl,
        )

        # Current slot is in epoch 0 -- well before TTL
        current_slot = self.EPOCH_LENGTH - 1000
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot, tx_size=200)
        # Should not have ExpiredUTxO
        expired = [e for e in errors if "ExpiredUTxO" in e]
        assert expired == [], f"Tx should be valid before TTL, got: {expired}"

    def test_tx_rejected_after_ttl_in_next_epoch(self):
        """Tx with TTL in epoch N+1 is rejected when current slot >= TTL."""
        sk, vk = _make_key_pair(seed=60)
        addr = _make_address(vk, network=Network.TESTNET)
        tx_id = _make_tx_id(401)
        txin = TransactionInput(tx_id, 0)
        utxo_set: ShelleyUTxO = {txin: TransactionOutput(addr, 5_000_000)}

        ttl = self.EPOCH_LENGTH + 100
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 3_000_000)],
            fee=2_000_000,
            ttl=ttl,
        )

        # Current slot is past TTL
        current_slot = self.EPOCH_LENGTH + 100  # exactly at TTL (>= means expired)
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot, tx_size=200)
        expired = [e for e in errors if "ExpiredUTxO" in e]
        assert len(expired) == 1, f"Tx should be expired at TTL, got: {errors}"


# ===========================================================================
# 5. Instant stake distribution (epoch delay)
# ===========================================================================


class TestInstantStakeDistribution:
    """Test that delegation is recorded immediately but would only affect
    stake distribution after the required epoch delay.

    In Shelley, stake snapshots are taken at epoch boundaries. A delegation
    made in epoch N takes effect in the stake distribution at epoch N+2
    (the "two-epoch delay"). This test verifies the delegation state is
    updated immediately, which is the prerequisite for the snapshot machinery.

    Spec ref: Shelley ledger formal spec, Section 11 (SNAP rule, epoch boundary)
    Haskell ref: ``snapShotsFee`` in ``Cardano.Ledger.Shelley.LedgerState``
    """

    def test_delegation_recorded_immediately(self):
        """After delegation, the delegation map is updated in the current state."""
        params = TEST_PARAMS
        pool_hash = _fake_hash(0xBB)
        cred_hash = _fake_hash(0xAA)

        state = DelegationState(
            rewards={cred_hash: 0},
            pools={pool_hash: _pool_params(0xBB)},
        )

        cert = StakeDelegation(_stake_credential(0xAA), _pool_key_hash_obj(0xBB))
        new_state = process_certificate(cert, state, params, current_epoch=200)

        # Delegation is immediately recorded
        assert new_state.delegations[cred_hash] == pool_hash

    def test_delegation_not_in_original_state(self):
        """The original state is not mutated -- the new delegation only exists
        in the returned state, simulating that the snapshot for the current
        epoch was already taken from the old state.
        """
        params = TEST_PARAMS
        pool_hash = _fake_hash(0xBB)
        cred_hash = _fake_hash(0xAA)

        state = DelegationState(
            rewards={cred_hash: 0},
            pools={pool_hash: _pool_params(0xBB)},
        )

        cert = StakeDelegation(_stake_credential(0xAA), _pool_key_hash_obj(0xBB))
        new_state = process_certificate(cert, state, params, current_epoch=200)

        # Original state unchanged -- old snapshot doesn't see the delegation
        assert cred_hash not in state.delegations
        # New state has it
        assert cred_hash in new_state.delegations


# ===========================================================================
# 6. Pool metadata hash size
# ===========================================================================


class TestPoolMetadataHashSize:
    """Test that pool registration with a metadata hash that is not exactly
    32 bytes is rejected.

    Spec ref: Shelley CDDL -- ``pool_metadata_hash = $hash32``
    Haskell ref: CDDL deserialization enforces hash32 = bytes .size 32
    """

    def test_metadata_hash_wrong_size_rejected(self):
        """Pool registration with a non-32-byte metadata hash is rejected.

        pycardano's PoolMetadataHash enforces [32,32] at construction, so we
        bypass it to simulate malformed CBOR deserialization where the hash
        field arrives with the wrong size.
        """
        # Create a PoolMetadataHash that bypasses the size check
        short_hash = PoolMetadataHash.__new__(PoolMetadataHash)
        object.__setattr__(short_hash, "_payload", b"\xaa" * 16)

        metadata = PoolMetadata(
            url="https://example.com/pool.json",
            pool_metadata_hash=short_hash,
        )
        pp = _pool_params(operator_prefix=0xB1, pool_metadata=metadata)
        cert = PoolRegistration(pp)

        with pytest.raises(DelegationError, match="PoolMetadataHashWrongSizePOOL"):
            process_certificate(cert, DelegationState(), TEST_PARAMS, current_epoch=200)

    def test_metadata_hash_correct_size_accepted(self):
        """Pool registration with a proper 32-byte metadata hash succeeds."""
        good_hash = PoolMetadataHash(b"\xbb" * 32)
        metadata = PoolMetadata(
            url="https://example.com/pool.json",
            pool_metadata_hash=good_hash,
        )
        pp = _pool_params(operator_prefix=0xB2, pool_metadata=metadata)
        cert = PoolRegistration(pp)

        new_state = process_certificate(cert, DelegationState(), TEST_PARAMS, current_epoch=200)
        assert _fake_hash(0xB2) in new_state.pools


# ===========================================================================
# 7. VRF key uniqueness
# ===========================================================================


class TestVrfKeyUniqueness:
    """Test that two different pools cannot register with the same VRF key.

    Spec ref: Shelley ledger formal spec, Section 8 (POOL rule)
        VRF keys must be unique across all registered pools.
    Haskell ref: The invariant is maintained by the protocol -- duplicate VRF
        keys would allow equivocation in leader election.
    """

    def test_duplicate_vrf_key_rejected(self):
        """Second pool registration with same VRF key as existing pool fails."""
        params = TEST_PARAMS
        pool1_hash = _fake_hash(0xB1)
        pool1 = _pool_params(operator_prefix=0xB1, vrf_prefix=0xCC)

        # Pool 1 already registered
        state = DelegationState(pools={pool1_hash: pool1})

        # Pool 2 tries to register with the same VRF key (0xCC)
        pool2 = _pool_params(operator_prefix=0xB2, vrf_prefix=0xCC)
        cert = PoolRegistration(pool2)

        with pytest.raises(DelegationError, match="StakePoolDuplicateVrfKeyPOOL"):
            process_certificate(cert, state, params, current_epoch=200)

    def test_different_vrf_keys_accepted(self):
        """Two pools with different VRF keys can both be registered."""
        params = TEST_PARAMS
        pool1_hash = _fake_hash(0xB1)
        pool1 = _pool_params(operator_prefix=0xB1, vrf_prefix=0xC1)
        state = DelegationState(pools={pool1_hash: pool1})

        pool2 = _pool_params(operator_prefix=0xB2, vrf_prefix=0xC2)
        cert = PoolRegistration(pool2)

        new_state = process_certificate(cert, state, params, current_epoch=200)
        assert _fake_hash(0xB1) in new_state.pools
        assert _fake_hash(0xB2) in new_state.pools


# ===========================================================================
# 8. Pool wrong network ID
# ===========================================================================


class TestPoolWrongNetworkId:
    """Test that pool registration with a reward address having the wrong
    network ID is rejected.

    Spec ref: Shelley formal spec, POOL rule
        netId (poolRewardAddr poolParams) = NetworkId
    Haskell ref: ``WrongNetworkPOOL``
    """

    def test_wrong_network_in_reward_address_rejected(self):
        """Pool reward address with mainnet network_id=1 on a testnet
        (network_id=0) chain is rejected.
        """
        # Mainnet reward address: header 0xE1 (VKey, mainnet)
        mainnet_reward = bytes([0xE1]) + _fake_hash(0xDD)
        pp = _pool_params(
            operator_prefix=0xB3,
            reward_account=mainnet_reward,
        )
        cert = PoolRegistration(pp)

        with pytest.raises(DelegationError, match="WrongNetworkPOOL"):
            process_certificate(cert, DelegationState(), TEST_PARAMS, current_epoch=200)

    def test_correct_network_in_reward_address_accepted(self):
        """Pool reward address with matching network_id is accepted."""
        # Testnet reward address: header 0xE0 (VKey, testnet)
        testnet_reward = bytes([0xE0]) + _fake_hash(0xDD)
        pp = _pool_params(
            operator_prefix=0xB4,
            reward_account=testnet_reward,
        )
        cert = PoolRegistration(pp)

        new_state = process_certificate(cert, DelegationState(), TEST_PARAMS, current_epoch=200)
        assert _fake_hash(0xB4) in new_state.pools


# ===========================================================================
# 9. Pool metadata URL too long
# ===========================================================================


class TestPoolMetadataUrlTooLong:
    """Test that pool registration with a metadata URL exceeding 64 bytes
    is rejected.

    Spec ref: Shelley CDDL -- ``url = tstr .size (0..64)``
    Haskell ref: CDDL deserialization enforces the 64-byte limit; the ledger
        rule also checks ``StakePoolMetadataUrlTooLongPOOL`` in later eras.
    """

    def test_url_too_long_rejected(self):
        """Metadata URL of 65+ bytes is rejected."""
        long_url = "https://example.com/" + "a" * 50  # 70 bytes total
        assert len(long_url.encode("utf-8")) > 64

        metadata = PoolMetadata(
            url=long_url,
            pool_metadata_hash=PoolMetadataHash(b"\xcc" * 32),
        )
        pp = _pool_params(operator_prefix=0xB5, pool_metadata=metadata)
        cert = PoolRegistration(pp)

        with pytest.raises(DelegationError, match="PoolMetadataUrlTooLongPOOL"):
            process_certificate(cert, DelegationState(), TEST_PARAMS, current_epoch=200)

    def test_url_at_64_bytes_accepted(self):
        """Metadata URL of exactly 64 bytes is accepted."""
        # Build a URL of exactly 64 bytes
        prefix = "https://x.co/"
        url_64 = prefix + "b" * (64 - len(prefix))
        assert len(url_64.encode("utf-8")) == 64

        metadata = PoolMetadata(
            url=url_64,
            pool_metadata_hash=PoolMetadataHash(b"\xdd" * 32),
        )
        pp = _pool_params(operator_prefix=0xB6, pool_metadata=metadata)
        cert = PoolRegistration(pp)

        new_state = process_certificate(cert, DelegationState(), TEST_PARAMS, current_epoch=200)
        assert _fake_hash(0xB6) in new_state.pools


# ===========================================================================
# 10. Duplicate VRF on re-registration (different pool)
# ===========================================================================


class TestDuplicateVrfOnReRegistration:
    """Test that a pool trying to re-register (update params) with a VRF key
    already in use by ANOTHER pool is rejected, but re-registering with your
    OWN VRF key is allowed.

    Spec ref: Shelley formal spec, POOL rule (VRF uniqueness invariant)
    """

    def test_reregister_own_vrf_key_accepted(self):
        """A pool re-registering with the same VRF key it already has is fine."""
        params = TEST_PARAMS
        pool_hash = _fake_hash(0xBB)
        pool = _pool_params(operator_prefix=0xBB, vrf_prefix=0xCC)
        state = DelegationState(pools={pool_hash: pool})

        # Re-register with same VRF key but updated pledge
        updated = PoolParams(
            operator=PoolKeyHash(_fake_hash(0xBB)),
            vrf_keyhash=_fake_hash(0xCC, size=32),  # same VRF
            pledge=200_000_000,  # changed
            cost=340_000_000,
            margin=Fraction(1, 100),
            reward_account=bytes([0xE0]) + _fake_hash(0xDD),
            pool_owners=[VerificationKeyHash(_fake_hash(0xBB))],
        )
        cert = PoolRegistration(updated)
        new_state = process_certificate(cert, state, params, current_epoch=200)
        assert new_state.pools[pool_hash].pledge == 200_000_000

    def test_reregister_with_other_pools_vrf_rejected(self):
        """Pool B trying to adopt Pool A's VRF key on re-registration is rejected."""
        params = TEST_PARAMS
        pool_a_hash = _fake_hash(0xA1)
        pool_b_hash = _fake_hash(0xA2)
        pool_a = _pool_params(operator_prefix=0xA1, vrf_prefix=0xC1)
        pool_b = _pool_params(operator_prefix=0xA2, vrf_prefix=0xC2)

        state = DelegationState(pools={pool_a_hash: pool_a, pool_b_hash: pool_b})

        # Pool B tries to re-register with Pool A's VRF key
        updated_b = PoolParams(
            operator=PoolKeyHash(_fake_hash(0xA2)),
            vrf_keyhash=_fake_hash(0xC1, size=32),  # Pool A's VRF!
            pledge=100_000_000,
            cost=340_000_000,
            margin=Fraction(1, 100),
            reward_account=bytes([0xE0]) + _fake_hash(0xDD),
            pool_owners=[VerificationKeyHash(_fake_hash(0xA2))],
        )
        cert = PoolRegistration(updated_b)

        with pytest.raises(DelegationError, match="StakePoolDuplicateVrfKeyPOOL"):
            process_certificate(cert, state, params, current_epoch=200)


# ===========================================================================
# 11. VRF reuse after pool retirement
# ===========================================================================


class TestVrfReuseAfterRetirement:
    """Test that after a pool retires and is removed from the active pool set,
    a new pool can register with the retired pool's VRF key.

    In Shelley, retirement is scheduled via RetirePool but the actual removal
    happens at the epoch boundary (POOLREAP rule). Once removed from the pools
    map, the VRF key is available for reuse.

    Spec ref: Shelley formal spec, Section 8 (POOL rule, POOLREAP)
    """

    def test_vrf_available_after_pool_removed(self):
        """After manually removing a retired pool from state, its VRF key
        can be reused by a new pool registration.
        """
        params = TEST_PARAMS
        old_pool_hash = _fake_hash(0xA3)
        old_pool = _pool_params(operator_prefix=0xA3, vrf_prefix=0xC3)

        # Simulate post-POOLREAP state: old pool is removed from pools map
        # (retirement was scheduled and the epoch boundary processed it)
        state = DelegationState(pools={})  # old pool already reaped

        # New pool registers with the same VRF key
        new_pool = _pool_params(operator_prefix=0xA4, vrf_prefix=0xC3)
        cert = PoolRegistration(new_pool)

        new_state = process_certificate(cert, state, params, current_epoch=300)
        assert _fake_hash(0xA4) in new_state.pools

    def test_vrf_still_blocked_before_pool_removal(self):
        """If the retired pool is still in the pools map (retirement scheduled
        but epoch boundary not yet processed), the VRF key is still locked.
        """
        params = TEST_PARAMS
        old_pool_hash = _fake_hash(0xA3)
        old_pool = _pool_params(operator_prefix=0xA3, vrf_prefix=0xC3)

        # Pool is still active (retirement scheduled but not reaped)
        state = DelegationState(
            pools={old_pool_hash: old_pool},
            retiring={old_pool_hash: 300},
        )

        new_pool = _pool_params(operator_prefix=0xA5, vrf_prefix=0xC3)
        cert = PoolRegistration(new_pool)

        with pytest.raises(DelegationError, match="StakePoolDuplicateVrfKeyPOOL"):
            process_certificate(cert, state, params, current_epoch=299)


# ===========================================================================
# 12. Network ID in output address
# ===========================================================================


class TestOutputAddressNetworkId:
    """Test that transaction outputs with addresses having the wrong network
    ID are rejected.

    Spec ref: Shelley formal spec, Section 9 (UTXO rule)
        ∀ txout ∈ txouts txb, netId txout_addr = NetworkId
    Haskell ref: ``WrongNetwork`` in ``ShelleyUtxoPredFailure``
    """

    def test_wrong_network_in_output_address_rejected(self):
        """Output address with mainnet network on a testnet chain is rejected."""
        sk, vk = _make_key_pair(seed=70)
        # Input is on testnet
        input_addr = _make_address(vk, network=Network.TESTNET)
        tx_id = _make_tx_id(500)
        txin = TransactionInput(tx_id, 0)
        utxo_set: ShelleyUTxO = {txin: TransactionOutput(input_addr, 5_000_000)}

        # Output address is on MAINNET -- wrong for our testnet params
        output_addr = _make_address(vk, network=Network.MAINNET)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(output_addr, 3_000_000)],
            fee=2_000_000,
            ttl=1000,
        )

        errors = validate_shelley_utxo(
            tx_body, utxo_set, TEST_PARAMS, current_slot=500, tx_size=200
        )
        wrong_net = [e for e in errors if "WrongNetwork" in e]
        assert len(wrong_net) == 1, f"Expected WrongNetwork error, got: {errors}"

    def test_correct_network_in_output_address_accepted(self):
        """Output address with matching network ID is accepted."""
        sk, vk = _make_key_pair(seed=70)
        addr = _make_address(vk, network=Network.TESTNET)
        tx_id = _make_tx_id(501)
        txin = TransactionInput(tx_id, 0)
        utxo_set: ShelleyUTxO = {txin: TransactionOutput(addr, 5_000_000)}

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 3_000_000)],
            fee=2_000_000,
            ttl=1000,
        )

        errors = validate_shelley_utxo(
            tx_body, utxo_set, TEST_PARAMS, current_slot=500, tx_size=200
        )
        wrong_net = [e for e in errors if "WrongNetwork" in e]
        assert wrong_net == [], f"Should accept matching network, got: {wrong_net}"
