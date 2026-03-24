"""Tests for vibe.cardano.consensus.chain_selection.

Covers:
- Prefer longer chain (higher block_number)
- Tie-breaking with VRF output (lower wins)
- Fallback tie-breaking on block hash
- k-deep finality constraint (should_switch_to)
- Fork choice within security window
- Transitivity property (Hypothesis)
"""

from __future__ import annotations

import os

from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.consensus.chain_selection import (
    SECURITY_PARAM_K,
    ChainCandidate,
    Preference,
    compare_chains,
    is_chain_better,
    should_switch_to,
)


def _make_candidate(
    block_number: int = 100,
    slot: int = 5000,
    tip_hash: bytes | None = None,
    vrf_output: bytes | None = None,
) -> ChainCandidate:
    """Helper to construct a ChainCandidate with defaults."""
    if tip_hash is None:
        tip_hash = os.urandom(32)
    return ChainCandidate(
        tip_slot=slot,
        tip_block_number=block_number,
        tip_hash=tip_hash,
        chain_length=block_number,
        vrf_output=vrf_output,
    )


# ---------------------------------------------------------------------------
# Prefer longer chain
# ---------------------------------------------------------------------------


class TestCompareChainsLength:
    def test_prefer_longer_chain(self) -> None:
        short = _make_candidate(block_number=100)
        long = _make_candidate(block_number=101)
        assert compare_chains(long, short) == Preference.PREFER_FIRST
        assert compare_chains(short, long) == Preference.PREFER_SECOND

    def test_longer_chain_regardless_of_slot(self) -> None:
        """Block number, not slot, determines chain length."""
        low_slot_long = _make_candidate(block_number=200, slot=1000)
        high_slot_short = _make_candidate(block_number=100, slot=9999)
        assert compare_chains(low_slot_long, high_slot_short) == Preference.PREFER_FIRST

    def test_same_block_number_and_hash_is_equal(self) -> None:
        same_hash = b"\x42" * 32
        a = _make_candidate(block_number=100, tip_hash=same_hash)
        b = _make_candidate(block_number=100, tip_hash=same_hash)
        assert compare_chains(a, b) == Preference.EQUAL


# ---------------------------------------------------------------------------
# VRF tie-breaking
# ---------------------------------------------------------------------------


class TestVRFTieBreaking:
    def test_lower_vrf_wins(self) -> None:
        low_vrf = b"\x00" * 64
        high_vrf = b"\xff" * 64
        a = _make_candidate(block_number=100, vrf_output=low_vrf)
        b = _make_candidate(block_number=100, vrf_output=high_vrf)
        assert compare_chains(a, b) == Preference.PREFER_FIRST

    def test_higher_vrf_loses(self) -> None:
        low_vrf = b"\x00" * 64
        high_vrf = b"\xff" * 64
        a = _make_candidate(block_number=100, vrf_output=high_vrf)
        b = _make_candidate(block_number=100, vrf_output=low_vrf)
        assert compare_chains(a, b) == Preference.PREFER_SECOND

    def test_equal_vrf_falls_through_to_hash(self) -> None:
        same_vrf = b"\xab" * 64
        low_hash = b"\x00" * 32
        high_hash = b"\xff" * 32
        a = _make_candidate(block_number=100, tip_hash=low_hash, vrf_output=same_vrf)
        b = _make_candidate(block_number=100, tip_hash=high_hash, vrf_output=same_vrf)
        assert compare_chains(a, b) == Preference.PREFER_FIRST

    def test_only_one_has_vrf_falls_to_hash(self) -> None:
        """When only one chain has VRF output, fall through to hash."""
        low_hash = b"\x00" * 32
        high_hash = b"\xff" * 32
        a = _make_candidate(block_number=100, tip_hash=low_hash, vrf_output=b"\xff" * 64)
        b = _make_candidate(block_number=100, tip_hash=high_hash, vrf_output=None)
        # VRF comparison skipped (only one has it), falls to hash
        assert compare_chains(a, b) == Preference.PREFER_FIRST


# ---------------------------------------------------------------------------
# Block hash tie-breaking
# ---------------------------------------------------------------------------


class TestHashTieBreaking:
    def test_lower_hash_wins(self) -> None:
        a = _make_candidate(block_number=100, tip_hash=b"\x00" * 32)
        b = _make_candidate(block_number=100, tip_hash=b"\xff" * 32)
        assert compare_chains(a, b) == Preference.PREFER_FIRST

    def test_equal_hash_is_equal(self) -> None:
        h = b"\x42" * 32
        a = _make_candidate(block_number=100, tip_hash=h)
        b = _make_candidate(block_number=100, tip_hash=h)
        assert compare_chains(a, b) == Preference.EQUAL


# ---------------------------------------------------------------------------
# is_chain_better
# ---------------------------------------------------------------------------


class TestIsChainBetter:
    def test_longer_candidate_is_better(self) -> None:
        ours = _make_candidate(block_number=100)
        candidate = _make_candidate(block_number=101)
        assert is_chain_better(ours, candidate) is True

    def test_shorter_candidate_is_not_better(self) -> None:
        ours = _make_candidate(block_number=100)
        candidate = _make_candidate(block_number=99)
        assert is_chain_better(ours, candidate) is False

    def test_equal_length_is_not_better(self) -> None:
        """Equal-length chain with same hash is not strictly better."""
        h = b"\x42" * 32
        ours = _make_candidate(block_number=100, tip_hash=h)
        candidate = _make_candidate(block_number=100, tip_hash=h)
        assert is_chain_better(ours, candidate) is False


# ---------------------------------------------------------------------------
# should_switch_to (k-deep finality)
# ---------------------------------------------------------------------------


class TestShouldSwitchTo:
    def test_switch_to_longer_chain(self) -> None:
        ours = _make_candidate(block_number=100)
        candidate = _make_candidate(block_number=101)
        assert should_switch_to(ours, candidate) is True

    def test_no_switch_to_shorter_chain(self) -> None:
        ours = _make_candidate(block_number=100)
        candidate = _make_candidate(block_number=99)
        assert should_switch_to(ours, candidate) is False

    def test_fork_within_k_allows_switch(self) -> None:
        ours = _make_candidate(block_number=100)
        candidate = _make_candidate(block_number=101)
        # Fork point at block 99 — depth 1, well within k=2160
        assert should_switch_to(ours, candidate, fork_point_block_number=99) is True

    def test_fork_at_exactly_k_allows_switch(self) -> None:
        ours = _make_candidate(block_number=2260)
        candidate = _make_candidate(block_number=2261)
        # Fork point at block 100 — depth = 2260 - 100 = 2160 = k
        assert should_switch_to(ours, candidate, fork_point_block_number=100) is True

    def test_fork_deeper_than_k_rejects(self) -> None:
        ours = _make_candidate(block_number=2261)
        candidate = _make_candidate(block_number=2262)
        # Fork point at block 100 — depth = 2261 - 100 = 2161 > k
        assert should_switch_to(ours, candidate, fork_point_block_number=100) is False

    def test_no_fork_point_only_checks_length(self) -> None:
        """Without fork point info, only length is checked."""
        ours = _make_candidate(block_number=100)
        candidate = _make_candidate(block_number=101)
        assert should_switch_to(ours, candidate, fork_point_block_number=None) is True

    def test_custom_k(self) -> None:
        ours = _make_candidate(block_number=20)
        candidate = _make_candidate(block_number=21)
        # Fork at block 0, depth = 20, k = 10 — too deep
        assert should_switch_to(ours, candidate, k=10, fork_point_block_number=0) is False
        # Same scenario with k=20 — exactly at limit, allowed
        assert should_switch_to(ours, candidate, k=20, fork_point_block_number=0) is True

    def test_security_param_constant(self) -> None:
        assert SECURITY_PARAM_K == 2160


# ---------------------------------------------------------------------------
# Transitivity (Hypothesis)
# ---------------------------------------------------------------------------


class TestTransitivity:
    """Chain comparison should be transitive: if A > B and B > C, then A > C."""

    @given(
        bn_a=st.integers(min_value=0, max_value=10000),
        bn_b=st.integers(min_value=0, max_value=10000),
        bn_c=st.integers(min_value=0, max_value=10000),
    )
    @settings(max_examples=300)
    def test_length_transitivity(self, bn_a: int, bn_b: int, bn_c: int) -> None:
        """Length comparison is transitive."""
        # Use deterministic hashes to avoid hash-based tiebreaking noise
        a = _make_candidate(block_number=bn_a, tip_hash=b"\x01" * 32)
        b = _make_candidate(block_number=bn_b, tip_hash=b"\x02" * 32)
        c = _make_candidate(block_number=bn_c, tip_hash=b"\x03" * 32)

        ab = compare_chains(a, b)
        bc = compare_chains(b, c)
        ac = compare_chains(a, c)

        if ab == Preference.PREFER_FIRST and bc == Preference.PREFER_FIRST:
            assert ac == Preference.PREFER_FIRST

    @given(data=st.data())
    @settings(max_examples=200)
    def test_antisymmetry(self, data: st.DataObject) -> None:
        """If A is preferred over B, then B is not preferred over A."""
        bn_a = data.draw(st.integers(min_value=0, max_value=10000))
        bn_b = data.draw(st.integers(min_value=0, max_value=10000))

        a = _make_candidate(block_number=bn_a, tip_hash=b"\x01" * 32)
        b = _make_candidate(block_number=bn_b, tip_hash=b"\x02" * 32)

        ab = compare_chains(a, b)
        ba = compare_chains(b, a)

        if ab == Preference.PREFER_FIRST:
            assert ba == Preference.PREFER_SECOND
        elif ab == Preference.PREFER_SECOND:
            assert ba == Preference.PREFER_FIRST
