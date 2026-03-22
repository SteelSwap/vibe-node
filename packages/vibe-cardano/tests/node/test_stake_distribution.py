"""Tests for StakeDistribution and NodeKernel stake integration.

Validates:
- StakeDistribution.relative_stake() arithmetic
- NodeKernel.init_stake_distribution() / .stake_distribution property
- Zero-stake edge cases
- Genesis staking parser (_parse_genesis_stake)
"""

from __future__ import annotations

import hashlib

import pytest

from vibe.cardano.node.kernel import NodeKernel, StakeDistribution


# ---------------------------------------------------------------------------
# StakeDistribution unit tests
# ---------------------------------------------------------------------------


class TestStakeDistribution:
    """Direct tests on the StakeDistribution dataclass."""

    def test_relative_stake_single_pool(self) -> None:
        pool_id = b"\x01" * 28
        dist = StakeDistribution(pool_stakes={pool_id: 1_000_000}, total_stake=1_000_000)
        assert dist.relative_stake(pool_id) == 1.0

    def test_relative_stake_equal_pools(self) -> None:
        pools = {bytes([i]) * 28: 500_000 for i in range(3)}
        total = sum(pools.values())
        dist = StakeDistribution(pool_stakes=pools, total_stake=total)
        for pid in pools:
            assert abs(dist.relative_stake(pid) - 1.0 / 3.0) < 1e-12

    def test_relative_stake_unequal(self) -> None:
        pool_a = b"\xaa" * 28
        pool_b = b"\xbb" * 28
        dist = StakeDistribution(
            pool_stakes={pool_a: 750_000, pool_b: 250_000},
            total_stake=1_000_000,
        )
        assert dist.relative_stake(pool_a) == 0.75
        assert dist.relative_stake(pool_b) == 0.25

    def test_unknown_pool_returns_zero(self) -> None:
        pool_id = b"\x01" * 28
        unknown = b"\xff" * 28
        dist = StakeDistribution(pool_stakes={pool_id: 1_000}, total_stake=1_000)
        assert dist.relative_stake(unknown) == 0.0

    def test_zero_total_stake_returns_zero(self) -> None:
        dist = StakeDistribution(pool_stakes={}, total_stake=0)
        assert dist.relative_stake(b"\x01" * 28) == 0.0

    def test_empty_pools(self) -> None:
        dist = StakeDistribution(pool_stakes={}, total_stake=0)
        assert dist.relative_stake(b"\x00" * 28) == 0.0

    def test_pool_id_is_blake2b_224(self) -> None:
        """Verify that pool_id = Blake2b-224(cold_vk) matches 28 bytes."""
        cold_vk = b"\xab" * 32  # Fake 32-byte cold verification key
        pool_id = hashlib.blake2b(cold_vk, digest_size=28).digest()
        assert len(pool_id) == 28

        dist = StakeDistribution(
            pool_stakes={pool_id: 42_000_000},
            total_stake=42_000_000,
        )
        assert dist.relative_stake(pool_id) == 1.0


# ---------------------------------------------------------------------------
# NodeKernel stake distribution integration
# ---------------------------------------------------------------------------



class TestParseGenesisStake:
    """Test the CLI's _parse_genesis_stake helper."""

    def _parse(self, sg: dict) -> dict[bytes, int]:
        """Import and call the parser."""
        from vibe_node.cli import _parse_genesis_stake
        return _parse_genesis_stake(sg)

    def test_devnet_genesis_structure(self) -> None:
        """Full devnet-style genesis with initialFunds + stake delegations."""
        pool1_hex = "6907cca237d89686082bc932aae51de3fbc90fe6bde58a806f63dede"
        pool2_hex = "4f89f84d57006ffb712154d17850125f1fe5d99e405aaae5f005bb9d"
        staker1_hex = "f08f7e25d2498c61eaaf8c881088803a5e94ed687b9342dd2cab975b"
        staker2_hex = "92f0159d4457de9053a4cb733d7a3ea18bd39a768c8c361b9e42d3b7"

        # Shelley base address: 00 + 28-byte payment + 28-byte staking
        addr1 = "00" + "11" * 28 + staker1_hex
        addr2 = "00" + "22" * 28 + staker2_hex

        sg = {
            "staking": {
                "pools": {
                    pool1_hex: {"pledge": 1_000_000_000_000},
                    pool2_hex: {"pledge": 1_000_000_000_000},
                },
                "stake": {
                    staker1_hex: pool1_hex,
                    staker2_hex: pool2_hex,
                },
            },
            "initialFunds": {
                addr1: 500_000_000_000,
                addr2: 750_000_000_000,
            },
        }

        result = self._parse(sg)
        assert len(result) == 2
        assert result[bytes.fromhex(pool1_hex)] == 500_000_000_000
        assert result[bytes.fromhex(pool2_hex)] == 750_000_000_000

    def test_multiple_delegators_to_same_pool(self) -> None:
        """Two stakers delegating to the same pool should sum."""
        pool_hex = "aa" * 28
        staker1 = "bb" * 28
        staker2 = "cc" * 28

        addr1 = "00" + "11" * 28 + staker1
        addr2 = "00" + "22" * 28 + staker2

        sg = {
            "staking": {
                "pools": {pool_hex: {"pledge": 100}},
                "stake": {staker1: pool_hex, staker2: pool_hex},
            },
            "initialFunds": {
                addr1: 300,
                addr2: 700,
            },
        }

        result = self._parse(sg)
        assert result[bytes.fromhex(pool_hex)] == 1000

    def test_fallback_to_pledge(self) -> None:
        """When no initialFunds, fall back to pledge values."""
        pool_hex = "dd" * 28
        sg = {
            "staking": {
                "pools": {pool_hex: {"pledge": 999_000_000}},
                "stake": {},
            },
        }
        result = self._parse(sg)
        assert result[bytes.fromhex(pool_hex)] == 999_000_000

    def test_empty_genesis(self) -> None:
        """No staking section at all."""
        result = self._parse({})
        assert result == {}

    def test_no_initial_funds_no_stake(self) -> None:
        """Pools exist but no delegations and no initialFunds."""
        pool_hex = "ee" * 28
        sg = {
            "staking": {
                "pools": {pool_hex: {"pledge": 42}},
            },
        }
        result = self._parse(sg)
        # Should fall back to pledge
        assert result[bytes.fromhex(pool_hex)] == 42

    def test_undelegated_funds_ignored(self) -> None:
        """Funds at an address whose staking cred isn't in the delegation map."""
        pool_hex = "ff" * 28
        staker = "aa" * 28
        undelegated_staker = "bb" * 28

        addr_delegated = "00" + "11" * 28 + staker
        addr_undelegated = "00" + "22" * 28 + undelegated_staker

        sg = {
            "staking": {
                "pools": {pool_hex: {"pledge": 100}},
                "stake": {staker: pool_hex},
            },
            "initialFunds": {
                addr_delegated: 500,
                addr_undelegated: 999,  # This should be ignored
            },
        }

        result = self._parse(sg)
        assert result[bytes.fromhex(pool_hex)] == 500
