"""Tests for delegation state tracking — M5.29.

Tests cover:
- Stake registration adds to reward_accounts
- Stake deregistration removes from rewards and delegations
- Stake delegation updates delegations map
- Pool registration adds to pool_params
- Pool retirement queues retirement
- Compute per-pool stake distribution from delegations + UTxO
- Apply multiple certs in order
- NodeKernel delegation integration
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from pycardano.certificate import (
    PoolParams,
    PoolRegistration,
    PoolRetirement,
    StakeCredential,
    StakeDelegation,
    StakeDeregistration,
    StakeRegistration,
)
from pycardano.hash import PoolKeyHash, VerificationKeyHash, VrfKeyHash

from vibe.cardano.ledger.delegation import (
    DelegationState,
    _apply_cert_lenient,
    apply_block_certs,
    compute_pool_stake_distribution,
    extract_certs_from_tx,
)
from vibe.cardano.node.kernel import NodeKernel

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

CRED_A = b"\xaa" * 28
CRED_B = b"\xbb" * 28
CRED_C = b"\xcc" * 28
POOL_1 = b"\x01" * 28
POOL_2 = b"\x02" * 28
VRF_KEY_1 = b"\x11" * 32
VRF_KEY_2 = b"\x22" * 32
# Reward account: 0xe1 header (mainnet VKey staking) + 28-byte credential hash
REWARD_ACCOUNT_1 = b"\xe1" + POOL_1


def _make_stake_cred(raw: bytes) -> StakeCredential:
    """Create a StakeCredential wrapping a VerificationKeyHash."""
    return StakeCredential(VerificationKeyHash(raw))


def _make_pkh(raw: bytes) -> PoolKeyHash:
    """Create a PoolKeyHash from raw bytes."""
    return PoolKeyHash(raw)


def _make_pool_params(
    operator: bytes,
    vrf_key: bytes = VRF_KEY_1,
    pledge: int = 100_000_000,
    cost: int = 340_000_000,
    margin: Fraction = Fraction(1, 100),
    reward_account: bytes = REWARD_ACCOUNT_1,
) -> PoolParams:
    """Build a PoolParams with minimal required fields."""
    return PoolParams(
        operator=_make_pkh(operator),
        vrf_keyhash=VrfKeyHash(vrf_key),
        pledge=pledge,
        cost=cost,
        margin=margin,
        reward_account=reward_account,
        pool_owners=[VerificationKeyHash(operator)],
    )


@dataclass
class FakeTxBody:
    """Minimal transaction body with certificates."""

    certificates: list[Any] | None = None


@dataclass
class FakeTx:
    """Minimal transaction for testing cert extraction."""

    body: FakeTxBody | None = None
    valid: bool = True


# ---------------------------------------------------------------------------
# Test: stake registration
# ---------------------------------------------------------------------------


class TestStakeRegistration:
    """StakeRegistration adds the credential to reward_accounts with 0 balance."""

    def test_registration_adds_to_rewards(self) -> None:
        state = DelegationState()
        cert = StakeRegistration(_make_stake_cred(CRED_A))
        state = _apply_cert_lenient(state, cert, current_epoch=0)

        assert CRED_A in state.rewards
        assert state.rewards[CRED_A] == 0

    def test_duplicate_registration_is_idempotent(self) -> None:
        """Lenient mode: duplicate registration does not raise."""
        state = DelegationState()
        state.rewards[CRED_A] = 500  # Already registered with rewards

        cert = StakeRegistration(_make_stake_cred(CRED_A))
        state = _apply_cert_lenient(state, cert, current_epoch=0)

        # Should not overwrite existing balance
        assert state.rewards[CRED_A] == 500


# ---------------------------------------------------------------------------
# Test: stake deregistration
# ---------------------------------------------------------------------------


class TestStakeDeregistration:
    """StakeDeregistration removes credential from rewards and delegations."""

    def test_deregistration_removes_reward(self) -> None:
        state = DelegationState()
        state.rewards[CRED_A] = 0
        state.delegations[CRED_A] = POOL_1

        cert = StakeDeregistration(_make_stake_cred(CRED_A))
        state = _apply_cert_lenient(state, cert, current_epoch=0)

        assert CRED_A not in state.rewards
        assert CRED_A not in state.delegations

    def test_deregistration_of_unregistered_is_noop(self) -> None:
        """Lenient mode: deregistering an unregistered key is a no-op."""
        state = DelegationState()
        cert = StakeDeregistration(_make_stake_cred(CRED_A))
        state = _apply_cert_lenient(state, cert, current_epoch=0)

        assert CRED_A not in state.rewards


# ---------------------------------------------------------------------------
# Test: stake delegation
# ---------------------------------------------------------------------------


class TestStakeDelegation:
    """StakeDelegation maps a stake credential to a pool."""

    def test_delegation_updates_map(self) -> None:
        state = DelegationState()
        state.rewards[CRED_A] = 0
        state.pools[POOL_1] = _make_pool_params(POOL_1)

        cert = StakeDelegation(_make_stake_cred(CRED_A), _make_pkh(POOL_1))
        state = _apply_cert_lenient(state, cert, current_epoch=0)

        assert state.delegations[CRED_A] == POOL_1

    def test_delegation_auto_registers_in_lenient(self) -> None:
        """Lenient mode: delegating an unregistered credential registers it."""
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)

        cert = StakeDelegation(_make_stake_cred(CRED_A), _make_pkh(POOL_1))
        state = _apply_cert_lenient(state, cert, current_epoch=0)

        assert CRED_A in state.rewards
        assert state.delegations[CRED_A] == POOL_1

    def test_redelegation_changes_pool(self) -> None:
        """Changing delegation target from one pool to another."""
        state = DelegationState()
        state.rewards[CRED_A] = 0
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        state.pools[POOL_2] = _make_pool_params(POOL_2, vrf_key=VRF_KEY_2)
        state.delegations[CRED_A] = POOL_1

        cert = StakeDelegation(_make_stake_cred(CRED_A), _make_pkh(POOL_2))
        state = _apply_cert_lenient(state, cert, current_epoch=0)

        assert state.delegations[CRED_A] == POOL_2


# ---------------------------------------------------------------------------
# Test: pool registration
# ---------------------------------------------------------------------------


class TestPoolRegistration:
    """PoolRegistration adds to pool_params and cancels pending retirement."""

    def test_pool_registration_adds_params(self) -> None:
        state = DelegationState()
        params = _make_pool_params(POOL_1)
        cert = PoolRegistration(params)
        state = _apply_cert_lenient(state, cert, current_epoch=0)

        assert POOL_1 in state.pools
        assert state.pools[POOL_1].pledge == 100_000_000

    def test_pool_reregistration_updates_params(self) -> None:
        """Re-registering a pool updates its parameters."""
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1, pledge=100_000_000)

        new_params = _make_pool_params(POOL_1, pledge=200_000_000)
        cert = PoolRegistration(new_params)
        state = _apply_cert_lenient(state, cert, current_epoch=0)

        assert state.pools[POOL_1].pledge == 200_000_000

    def test_pool_registration_cancels_retirement(self) -> None:
        """Re-registering a pool cancels any pending retirement."""
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        state.retiring[POOL_1] = 10  # Scheduled for epoch 10

        new_params = _make_pool_params(POOL_1, pledge=200_000_000)
        cert = PoolRegistration(new_params)
        state = _apply_cert_lenient(state, cert, current_epoch=5)

        assert POOL_1 not in state.retiring


# ---------------------------------------------------------------------------
# Test: pool retirement
# ---------------------------------------------------------------------------


class TestPoolRetirement:
    """PoolRetirement queues the pool for retirement at a future epoch."""

    def test_pool_retirement_queues(self) -> None:
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)

        cert = PoolRetirement(_make_pkh(POOL_1), epoch=15)
        state = _apply_cert_lenient(state, cert, current_epoch=5)

        assert state.retiring[POOL_1] == 15

    def test_pool_retirement_overwrites_previous(self) -> None:
        """A second retirement cert overwrites the first epoch."""
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        state.retiring[POOL_1] = 10

        cert = PoolRetirement(_make_pkh(POOL_1), epoch=20)
        state = _apply_cert_lenient(state, cert, current_epoch=5)

        assert state.retiring[POOL_1] == 20


# ---------------------------------------------------------------------------
# Test: compute_pool_stake_distribution
# ---------------------------------------------------------------------------


class TestComputeStakeDistribution:
    """Stake distribution sums UTxO + reward balances per delegated pool."""

    def test_basic_stake_distribution(self) -> None:
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        state.rewards[CRED_A] = 500
        state.rewards[CRED_B] = 300
        state.delegations[CRED_A] = POOL_1
        state.delegations[CRED_B] = POOL_1

        utxo_stakes = {CRED_A: 1000, CRED_B: 2000}
        dist = compute_pool_stake_distribution(state, utxo_stakes)

        # Pool1 = (1000 + 500) + (2000 + 300) = 3800
        assert dist[POOL_1] == 3800

    def test_multiple_pools(self) -> None:
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        state.pools[POOL_2] = _make_pool_params(POOL_2, vrf_key=VRF_KEY_2)
        state.rewards[CRED_A] = 0
        state.rewards[CRED_B] = 0
        state.delegations[CRED_A] = POOL_1
        state.delegations[CRED_B] = POOL_2

        utxo_stakes = {CRED_A: 5000, CRED_B: 3000}
        dist = compute_pool_stake_distribution(state, utxo_stakes)

        assert dist[POOL_1] == 5000
        assert dist[POOL_2] == 3000

    def test_undelegated_stake_not_counted(self) -> None:
        """Credentials with no delegation don't appear in distribution."""
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        state.rewards[CRED_A] = 100
        # CRED_A has no delegation

        utxo_stakes = {CRED_A: 5000}
        dist = compute_pool_stake_distribution(state, utxo_stakes)

        # Pool1 should have 0 because nobody delegates to it
        assert dist[POOL_1] == 0

    def test_delegation_to_unregistered_pool_ignored(self) -> None:
        """Delegations to pools not in pool_params are ignored."""
        state = DelegationState()
        # No pools registered
        state.rewards[CRED_A] = 0
        state.delegations[CRED_A] = POOL_1

        utxo_stakes = {CRED_A: 5000}
        dist = compute_pool_stake_distribution(state, utxo_stakes)

        assert POOL_1 not in dist

    def test_empty_state_returns_empty(self) -> None:
        state = DelegationState()
        dist = compute_pool_stake_distribution(state, {})
        assert dist == {}

    def test_rewards_included_in_stake(self) -> None:
        """Reward balances are added to UTxO stake."""
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        state.rewards[CRED_A] = 1_000_000
        state.delegations[CRED_A] = POOL_1

        # No UTxO stake, only rewards
        dist = compute_pool_stake_distribution(state, {})
        assert dist[POOL_1] == 1_000_000


# ---------------------------------------------------------------------------
# Test: apply_block_certs (multiple certs in order)
# ---------------------------------------------------------------------------


class TestApplyBlockCerts:
    """apply_block_certs processes all certs in order from a block's txs."""

    def test_apply_multiple_certs_in_order(self) -> None:
        """Register pool, register stake, delegate — all in one block."""
        state = DelegationState()

        pool_reg = PoolRegistration(_make_pool_params(POOL_1))
        stake_reg = StakeRegistration(_make_stake_cred(CRED_A))
        delegation = StakeDelegation(_make_stake_cred(CRED_A), _make_pkh(POOL_1))

        tx1 = FakeTx(body=FakeTxBody(certificates=[pool_reg]))
        tx2 = FakeTx(body=FakeTxBody(certificates=[stake_reg, delegation]))

        state = apply_block_certs(state, [tx1, tx2], current_epoch=0)

        assert POOL_1 in state.pools
        assert CRED_A in state.rewards
        assert state.delegations[CRED_A] == POOL_1

    def test_invalid_tx_skipped(self) -> None:
        """Transactions marked invalid are skipped."""
        state = DelegationState()

        pool_reg = PoolRegistration(_make_pool_params(POOL_1))
        tx = FakeTx(body=FakeTxBody(certificates=[pool_reg]), valid=False)

        state = apply_block_certs(state, [tx], current_epoch=0)

        assert POOL_1 not in state.pools

    def test_tx_without_certs(self) -> None:
        """Transactions without certificates are harmless."""
        state = DelegationState()

        tx = FakeTx(body=FakeTxBody(certificates=None))
        state = apply_block_certs(state, [tx], current_epoch=0)

        assert state.rewards == {}
        assert state.delegations == {}

    def test_register_deregister_in_same_block(self) -> None:
        """Register and deregister in the same block."""
        state = DelegationState()

        reg = StakeRegistration(_make_stake_cred(CRED_A))
        dereg = StakeDeregistration(_make_stake_cred(CRED_A))

        tx = FakeTx(body=FakeTxBody(certificates=[reg, dereg]))
        state = apply_block_certs(state, [tx], current_epoch=0)

        # Deregistration should have removed it
        assert CRED_A not in state.rewards


# ---------------------------------------------------------------------------
# Test: extract_certs_from_tx
# ---------------------------------------------------------------------------


class TestExtractCertsFromTx:
    """extract_certs_from_tx handles different tx representations."""

    def test_extract_from_body_certs(self) -> None:
        reg = StakeRegistration(_make_stake_cred(CRED_A))
        tx = FakeTx(body=FakeTxBody(certificates=[reg]))
        certs = extract_certs_from_tx(tx)
        assert len(certs) == 1
        assert isinstance(certs[0], StakeRegistration)

    def test_extract_empty_certs(self) -> None:
        tx = FakeTx(body=FakeTxBody(certificates=None))
        certs = extract_certs_from_tx(tx)
        assert certs == []

    def test_extract_no_body(self) -> None:
        tx = FakeTx(body=None)
        certs = extract_certs_from_tx(tx)
        assert certs == []


# ---------------------------------------------------------------------------
# Test: NodeKernel delegation integration
# ---------------------------------------------------------------------------


class TestNodeKernelDelegation:
    """NodeKernel tracks delegation state and computes stake distribution."""

    def test_initial_state_empty(self) -> None:
        kernel = NodeKernel()
        assert kernel.delegation_state.rewards == {}
        assert kernel.delegation_state.delegations == {}
        assert kernel.delegation_state.pools == {}
        assert kernel.stake_distribution == {}

    def test_apply_delegation_certs(self) -> None:
        """NodeKernel.apply_delegation_certs processes certs from txs."""
        kernel = NodeKernel()

        pool_reg = PoolRegistration(_make_pool_params(POOL_1))
        stake_reg = StakeRegistration(_make_stake_cred(CRED_A))
        deleg = StakeDelegation(_make_stake_cred(CRED_A), _make_pkh(POOL_1))

        tx = FakeTx(body=FakeTxBody(certificates=[pool_reg, stake_reg, deleg]))
        kernel.apply_delegation_certs([tx], current_epoch=0)

        assert POOL_1 in kernel.delegation_state.pools
        assert kernel.delegation_state.delegations[CRED_A] == POOL_1

    def test_update_stake_distribution(self) -> None:
        """NodeKernel.update_stake_distribution computes per-pool stakes."""
        kernel = NodeKernel()

        # Set up delegation state manually
        kernel._delegation_state.pools[POOL_1] = _make_pool_params(POOL_1)
        kernel._delegation_state.rewards[CRED_A] = 500
        kernel._delegation_state.delegations[CRED_A] = POOL_1

        utxo_stakes = {CRED_A: 10000}
        dist = kernel.update_stake_distribution(utxo_stakes)

        assert dist[POOL_1] == 10500  # 10000 UTxO + 500 rewards
        assert kernel.stake_distribution[POOL_1] == 10500

    def test_stake_distribution_evolves(self) -> None:
        """Delegation changes between epochs change the stake distribution."""
        kernel = NodeKernel()

        # Epoch 0: Pool1 gets CRED_A
        kernel._delegation_state.pools[POOL_1] = _make_pool_params(POOL_1)
        kernel._delegation_state.pools[POOL_2] = _make_pool_params(POOL_2, vrf_key=VRF_KEY_2)
        kernel._delegation_state.rewards[CRED_A] = 0
        kernel._delegation_state.delegations[CRED_A] = POOL_1

        dist = kernel.update_stake_distribution({CRED_A: 5000})
        assert dist[POOL_1] == 5000
        assert dist[POOL_2] == 0

        # Now redelegate to Pool2
        redeleg = StakeDelegation(_make_stake_cred(CRED_A), _make_pkh(POOL_2))
        tx = FakeTx(body=FakeTxBody(certificates=[redeleg]))
        kernel.apply_delegation_certs([tx], current_epoch=1)

        dist = kernel.update_stake_distribution({CRED_A: 5000})
        assert dist[POOL_1] == 0
        assert dist[POOL_2] == 5000
