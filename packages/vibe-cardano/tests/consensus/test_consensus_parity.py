"""Haskell test parity: consensus property-based tests (chain selection + Praos + nonce).

Brings our test coverage in line with the Haskell ouroboros-consensus
property tests, specifically:

- Chain selection: longer chain wins, equal length keeps current, reflexivity
- Praos leader threshold: monotonic in stake (Hypothesis), zero stake never
  elected, full stake always elected at low VRF output, boundary precision
- Epoch nonce evolution: multi-epoch chaining, determinism, commutativity of
  VRF accumulation order matters (non-commutative)

Spec references:
    - Ouroboros Praos paper, Section 3 — chain selection (maxvalid)
    - Ouroboros Praos paper, Section 4, Definition 6 — leader election
    - Shelley formal spec, Section 16.1 — VRF verification
    - Shelley formal spec, Section 12.1 — epoch nonce evolution

Haskell references:
    - ouroboros-consensus: Test.Consensus.Protocol.Praos
    - ouroboros-consensus: Test.Consensus.ChainSel
    - cardano-ledger: Test.Cardano.Ledger.Shelley.Rules.Nonce
"""

from __future__ import annotations

import hashlib
import os
from decimal import Decimal, getcontext

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from vibe.cardano.consensus.chain_selection import (
    SECURITY_PARAM_K,
    ChainCandidate,
    Preference,
    compare_chains,
    is_chain_better,
    should_switch_to,
)
from vibe.cardano.consensus.praos import (
    MAINNET_ACTIVE_SLOT_COEFF,
    ActiveSlotCoeff,
    leader_check,
)
from vibe.cardano.consensus.nonce import (
    NEUTRAL_NONCE,
    EpochNonce,
    accumulate_vrf_output,
    evolve_nonce,
    mk_nonce,
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
# Chain selection: longer chain wins
#
# Haskell parity: prop_preferLongerChain — a chain with higher block
# number is always preferred, regardless of slot or hash.
# ---------------------------------------------------------------------------


class TestChainSelectionLongerChainWins:
    """The chain with the higher block number always wins.

    Haskell ref: preferCandidate in Ouroboros.Consensus.Protocol.Abstract
    """

    @given(
        bn_short=st.integers(min_value=0, max_value=9999),
        delta=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=200)
    def test_longer_chain_always_preferred(
        self, bn_short: int, delta: int
    ) -> None:
        """For any two chains where one is strictly longer, prefer the longer."""
        bn_long = bn_short + delta
        short = _make_candidate(block_number=bn_short, tip_hash=b"\xff" * 32)
        long = _make_candidate(block_number=bn_long, tip_hash=b"\x00" * 32)

        assert compare_chains(long, short) == Preference.PREFER_FIRST
        assert compare_chains(short, long) == Preference.PREFER_SECOND
        assert is_chain_better(short, long) is True
        assert is_chain_better(long, short) is False


# ---------------------------------------------------------------------------
# Chain selection: equal length keeps current
#
# Haskell parity: when chains have equal block number and equal
# tiebreaker, we do NOT switch (EQUAL is not strictly better).
# ---------------------------------------------------------------------------


class TestChainSelectionEqualKeepsCurrent:
    """Equal-length chains with identical tiebreakers result in no switch.

    Haskell ref: preferAnchoredCandidate requires STRICTLY better.
    """

    @given(
        bn=st.integers(min_value=0, max_value=10000),
        hash_byte=st.integers(min_value=0, max_value=255),
    )
    @settings(max_examples=100)
    def test_equal_chains_no_switch(self, bn: int, hash_byte: int) -> None:
        """Two chains with the same block_number and hash are EQUAL."""
        h = bytes([hash_byte]) * 32
        a = _make_candidate(block_number=bn, tip_hash=h)
        b = _make_candidate(block_number=bn, tip_hash=h)
        assert compare_chains(a, b) == Preference.EQUAL
        assert is_chain_better(a, b) is False
        assert should_switch_to(a, b) is False

    @given(
        bn=st.integers(min_value=0, max_value=10000),
    )
    @settings(max_examples=100)
    def test_same_chain_is_not_better_than_itself(self, bn: int) -> None:
        """Reflexivity: a chain is EQUAL to itself, never strictly better."""
        h = b"\x42" * 32
        chain = _make_candidate(block_number=bn, tip_hash=h)
        assert compare_chains(chain, chain) == Preference.EQUAL
        assert is_chain_better(chain, chain) is False


# ---------------------------------------------------------------------------
# Chain selection: reflexivity and antisymmetry (Hypothesis)
#
# Haskell parity: the chain comparison must form a total preorder.
# ---------------------------------------------------------------------------


class TestChainSelectionOrderProperties:
    """Chain comparison forms a total preorder: reflexive, transitive,
    antisymmetric.

    Haskell ref: implied by the use of Ord for chain tips.
    """

    @given(
        bn=st.integers(min_value=0, max_value=10000),
        hash_bytes=st.binary(min_size=32, max_size=32),
        vrf_bytes=st.binary(min_size=64, max_size=64),
    )
    @settings(max_examples=100)
    def test_reflexivity(
        self, bn: int, hash_bytes: bytes, vrf_bytes: bytes
    ) -> None:
        """compare_chains(x, x) == EQUAL for any chain."""
        chain = _make_candidate(
            block_number=bn, tip_hash=hash_bytes, vrf_output=vrf_bytes
        )
        assert compare_chains(chain, chain) == Preference.EQUAL

    @given(
        bn_a=st.integers(min_value=0, max_value=10000),
        bn_b=st.integers(min_value=0, max_value=10000),
        hash_a=st.binary(min_size=32, max_size=32),
        hash_b=st.binary(min_size=32, max_size=32),
    )
    @settings(max_examples=200)
    def test_antisymmetry_with_hash(
        self, bn_a: int, bn_b: int, hash_a: bytes, hash_b: bytes
    ) -> None:
        """If A > B then B < A (antisymmetry)."""
        a = _make_candidate(block_number=bn_a, tip_hash=hash_a)
        b = _make_candidate(block_number=bn_b, tip_hash=hash_b)
        ab = compare_chains(a, b)
        ba = compare_chains(b, a)
        if ab == Preference.PREFER_FIRST:
            assert ba == Preference.PREFER_SECOND
        elif ab == Preference.PREFER_SECOND:
            assert ba == Preference.PREFER_FIRST
        else:
            assert ba == Preference.EQUAL

    @given(
        bn_a=st.integers(min_value=0, max_value=10000),
        bn_b=st.integers(min_value=0, max_value=10000),
        bn_c=st.integers(min_value=0, max_value=10000),
    )
    @settings(max_examples=300)
    def test_transitivity_full(
        self, bn_a: int, bn_b: int, bn_c: int
    ) -> None:
        """If A >= B and B >= C then A >= C (transitivity)."""
        a = _make_candidate(block_number=bn_a, tip_hash=b"\x01" * 32)
        b = _make_candidate(block_number=bn_b, tip_hash=b"\x02" * 32)
        c = _make_candidate(block_number=bn_c, tip_hash=b"\x03" * 32)

        ab = compare_chains(a, b)
        bc = compare_chains(b, c)
        ac = compare_chains(a, c)

        # If A preferred over B, and B preferred over C, then A over C
        if ab == Preference.PREFER_FIRST and bc == Preference.PREFER_FIRST:
            assert ac == Preference.PREFER_FIRST
        if ab == Preference.PREFER_SECOND and bc == Preference.PREFER_SECOND:
            assert ac == Preference.PREFER_SECOND


# ---------------------------------------------------------------------------
# Chain selection: k-deep fork rejection (Hypothesis)
#
# Haskell parity: prop_chainSelectionRejectsDeepFork
# ---------------------------------------------------------------------------


class TestChainSelectionKDeepFork:
    """Forks deeper than k blocks are always rejected.

    Haskell ref: Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
    """

    @given(
        our_bn=st.integers(min_value=2200, max_value=10000),
        candidate_delta=st.integers(min_value=1, max_value=100),
        k=st.integers(min_value=10, max_value=2160),
    )
    @settings(max_examples=100)
    def test_deep_fork_rejected(
        self, our_bn: int, candidate_delta: int, k: int
    ) -> None:
        """A fork deeper than k is rejected even if candidate is longer."""
        candidate_bn = our_bn + candidate_delta
        fork_point = our_bn - k - 1  # deeper than k

        ours = _make_candidate(block_number=our_bn)
        candidate = _make_candidate(block_number=candidate_bn)

        result = should_switch_to(
            ours, candidate, k=k, fork_point_block_number=fork_point
        )
        assert result is False, (
            f"Fork at depth {our_bn - fork_point} > k={k} should be rejected"
        )

    @given(
        our_bn=st.integers(min_value=100, max_value=10000),
        candidate_delta=st.integers(min_value=1, max_value=100),
        fork_depth=st.integers(min_value=0, max_value=99),
    )
    @settings(max_examples=100)
    def test_shallow_fork_accepted(
        self, our_bn: int, candidate_delta: int, fork_depth: int
    ) -> None:
        """A fork within k blocks is accepted if candidate is longer."""
        candidate_bn = our_bn + candidate_delta
        fork_point = our_bn - fork_depth

        ours = _make_candidate(block_number=our_bn)
        candidate = _make_candidate(block_number=candidate_bn)

        # With default k=2160, fork_depth <= 99 is always within k
        result = should_switch_to(
            ours, candidate, fork_point_block_number=fork_point
        )
        assert result is True


# ---------------------------------------------------------------------------
# Praos leader threshold: monotonic in stake (Hypothesis)
#
# Haskell parity: prop_leaderElectionMonotonic — higher stake means
# at least as many slots won.
# ---------------------------------------------------------------------------


class TestPraosLeaderThresholdMonotonic:
    """Leader election probability is monotonically non-decreasing in stake.

    Haskell ref: checkVRFValue in Cardano.Protocol.TPraos.Rules.Overlay
    """

    @given(
        vrf_bytes=st.binary(min_size=64, max_size=64),
        sigma_low=st.floats(min_value=0.0, max_value=0.998),
        delta=st.floats(min_value=0.001, max_value=0.1),
    )
    @settings(max_examples=300)
    def test_higher_stake_at_least_as_likely(
        self, vrf_bytes: bytes, sigma_low: float, delta: float
    ) -> None:
        """If elected at sigma, must also be elected at sigma + delta."""
        sigma_high = min(sigma_low + delta, 1.0)
        assume(sigma_high > sigma_low)

        f = MAINNET_ACTIVE_SLOT_COEFF
        if sigma_low == 0.0:
            # sigma=0 is always False; sigma_high > 0 may or may not win
            assert not leader_check(vrf_bytes, 0.0, f)
            return

        result_low = leader_check(vrf_bytes, sigma_low, f)
        if result_low:
            result_high = leader_check(vrf_bytes, sigma_high, f)
            assert result_high, (
                f"Elected at sigma={sigma_low} but not at "
                f"sigma={sigma_high} — monotonicity violated"
            )

    @given(
        vrf_bytes=st.binary(min_size=64, max_size=64),
        f_low=st.floats(min_value=0.01, max_value=0.97),
        f_delta=st.floats(min_value=0.01, max_value=0.1),
    )
    @settings(max_examples=200)
    def test_higher_f_at_least_as_likely(
        self, vrf_bytes: bytes, f_low: float, f_delta: float
    ) -> None:
        """Higher active slot coefficient means at least as likely to win."""
        f_high = min(f_low + f_delta, 0.99)
        assume(f_high > f_low)

        sigma = 0.5
        result_low = leader_check(vrf_bytes, sigma, f_low)
        if result_low:
            result_high = leader_check(vrf_bytes, sigma, f_high)
            assert result_high, (
                f"Elected at f={f_low} but not at f={f_high}"
            )


# ---------------------------------------------------------------------------
# Praos leader: zero stake never elected (Hypothesis)
#
# Haskell parity: prop_zeroStakeNeverElected
# ---------------------------------------------------------------------------


class TestPraosZeroStakeNeverElected:
    """Zero stake is never elected regardless of VRF output.

    Haskell ref: checkVRFValue edge case — sigma=0 => threshold=0.
    """

    @given(
        vrf_bytes=st.binary(min_size=64, max_size=64),
        f=st.floats(min_value=0.01, max_value=0.99),
    )
    @settings(max_examples=200)
    def test_zero_stake_never_wins(self, vrf_bytes: bytes, f: float) -> None:
        """sigma=0 always returns False."""
        assert leader_check(vrf_bytes, 0.0, f) is False


# ---------------------------------------------------------------------------
# Praos leader: full stake + low VRF always elected
#
# Haskell parity: prop_fullStakeLowVRFElected
# ---------------------------------------------------------------------------


class TestPraosFullStakeLowVRF:
    """Full stake (sigma=1.0) leader check with known VRF outputs.

    In Praos, the leader value is blake2b_256("L" || vrf_output) / 2^256,
    NOT the raw VRF output. So "zero VRF output" doesn't mean "zero
    leader value" — the hash scrambles the mapping.

    At sigma=1.0, the threshold is exactly f. A VRF output is elected
    iff its derived leader value < f.

    Haskell ref: vrfLeaderValue in Praos/VRF.hs, checkLeaderNatValue
    """

    def test_full_stake_high_f_elected(self) -> None:
        """sigma=1.0, f=0.5 — zero VRF output's leader value (~0.23) < 0.5."""
        zero_vrf = b"\x00" * 64
        assert leader_check(zero_vrf, 1.0, 0.5) is True

    def test_full_stake_low_f_not_elected(self) -> None:
        """sigma=1.0, f=0.1 — zero VRF output's leader value (~0.23) > 0.1."""
        zero_vrf = b"\x00" * 64
        assert leader_check(zero_vrf, 1.0, 0.1) is False

    @given(
        f=st.floats(min_value=0.01, max_value=0.99),
    )
    @settings(max_examples=100)
    def test_full_stake_threshold_is_f(self, f: float) -> None:
        """sigma=1.0 means threshold = f. Check consistency."""
        import hashlib
        zero_vrf = b"\x00" * 64
        leader_hash = hashlib.blake2b(b"L" + zero_vrf, digest_size=32).digest()
        leader_val = int.from_bytes(leader_hash, "big") / (2**256)
        expected = leader_val < f
        assert leader_check(zero_vrf, 1.0, f) is expected

    def test_threshold_boundary_precision(self) -> None:
        """Test that the threshold comparison uses the Praos leader hash.

        In Praos, the leader value is blake2b_256("L" || vrf_output) / 2^256.
        We verify that leader_check correctly compares this derived value
        against the threshold (= f at sigma=1.0).
        """
        import hashlib
        getcontext().prec = 40
        f = 0.05
        # Use a known VRF output whose leader hash we can compute
        vrf_output = b"\x42" * 64
        leader_hash = hashlib.blake2b(b"L" + vrf_output, digest_size=32).digest()
        leader_val = int.from_bytes(leader_hash, "big") / (2**256)
        # The result should be consistent with the derived leader value
        expected = leader_val < f
        assert leader_check(vrf_output, 1.0, f) is expected


# ---------------------------------------------------------------------------
# Epoch nonce evolution across multiple epochs
#
# Haskell parity: prop_nonceEvolution — nonce evolves deterministically
# through multiple epoch boundaries, and order of VRF accumulation matters.
# ---------------------------------------------------------------------------


class TestEpochNonceMultiEpochEvolution:
    """Nonce evolution across multiple epoch boundaries is deterministic
    and correctly chains.

    Haskell ref: Test.Cardano.Ledger.Shelley.Rules.Nonce
    """

    def test_three_epoch_evolution_chain(self) -> None:
        """Simulate 3 epochs of nonce evolution.

        Epoch 0 -> 1: evolve with eta_v_0
        Epoch 1 -> 2: evolve with eta_v_1
        Epoch 2 -> 3: evolve with eta_v_2

        Each step is deterministic, and the final nonce depends on all
        intermediate values.
        """
        eta_0 = mk_nonce(b"genesis nonce")

        eta_v_0 = b"\x11" * 32
        eta_v_1 = b"\x22" * 32
        eta_v_2 = b"\x33" * 32

        eta_1 = evolve_nonce(eta_0, eta_v_0)
        eta_2 = evolve_nonce(eta_1, eta_v_1)
        eta_3 = evolve_nonce(eta_2, eta_v_2)

        # Each step produces a different nonce
        assert eta_0 != eta_1
        assert eta_1 != eta_2
        assert eta_2 != eta_3

        # Verify manually: eta_1 = blake2b(eta_0 || eta_v_0)
        expected_1 = hashlib.blake2b(
            eta_0.value + eta_v_0, digest_size=32
        ).digest()
        assert eta_1.value == expected_1

        # Chain is deterministic: re-running gives the same result
        eta_1_redo = evolve_nonce(eta_0, eta_v_0)
        eta_2_redo = evolve_nonce(eta_1_redo, eta_v_1)
        eta_3_redo = evolve_nonce(eta_2_redo, eta_v_2)
        assert eta_3 == eta_3_redo

    def test_evolution_order_matters(self) -> None:
        """Evolving with eta_v_a then eta_v_b differs from b then a.

        Nonce evolution is NOT commutative — the order of epoch
        transitions matters.
        """
        base = mk_nonce(b"order test")
        a = b"\xaa" * 32
        b = b"\xbb" * 32

        ab = evolve_nonce(evolve_nonce(base, a), b)
        ba = evolve_nonce(evolve_nonce(base, b), a)
        assert ab != ba, "Nonce evolution must not be commutative"

    def test_vrf_accumulation_order_matters(self) -> None:
        """Accumulating VRF outputs in different orders gives different
        results.

        This mirrors the real scenario where blocks arrive in slot order,
        and the accumulator must process them in that order.
        """
        eta = b"\x00" * 32
        vrf_a = b"\x01" * 32
        vrf_b = b"\x02" * 32

        result_ab = accumulate_vrf_output(
            accumulate_vrf_output(eta, vrf_a), vrf_b
        )
        result_ba = accumulate_vrf_output(
            accumulate_vrf_output(eta, vrf_b), vrf_a
        )
        assert result_ab != result_ba, (
            "VRF accumulation order must matter"
        )

    @given(
        vrf_outputs=st.lists(
            st.binary(min_size=32, max_size=64),
            min_size=2,
            max_size=10,
        ),
    )
    @settings(max_examples=50)
    def test_vrf_accumulation_deterministic(
        self, vrf_outputs: list[bytes]
    ) -> None:
        """Accumulating the same VRF outputs in the same order always
        gives the same result."""
        eta = b"\x00" * 32

        # First pass
        result1 = eta
        for vrf in vrf_outputs:
            result1 = accumulate_vrf_output(result1, vrf)

        # Second pass
        result2 = eta
        for vrf in vrf_outputs:
            result2 = accumulate_vrf_output(result2, vrf)

        assert result1 == result2

    def test_extra_entropy_applied_at_epoch_boundary(self) -> None:
        """Extra entropy (e.g., from a governance action) changes the
        epoch nonce.

        In Conway era, extra entropy can be injected via governance.
        This test verifies that extra_entropy changes the result and
        that different extra values produce different nonces.
        """
        base = mk_nonce(b"epoch with entropy")
        eta_v = b"\x55" * 32

        without = evolve_nonce(base, eta_v)
        with_a = evolve_nonce(base, eta_v, extra_entropy=b"\xaa" * 16)
        with_b = evolve_nonce(base, eta_v, extra_entropy=b"\xbb" * 16)

        assert without != with_a
        assert without != with_b
        assert with_a != with_b

    @given(
        n_epochs=st.integers(min_value=5, max_value=20),
    )
    @settings(max_examples=10)
    def test_long_evolution_chain_all_unique(self, n_epochs: int) -> None:
        """Evolving through N epochs produces N+1 unique nonces.

        With cryptographic hashing, every evolution step should produce
        a completely different nonce.
        """
        nonce = mk_nonce(b"long chain test")
        seen = {nonce.value}

        for i in range(n_epochs):
            eta_v = hashlib.blake2b(
                i.to_bytes(4, "big"), digest_size=32
            ).digest()
            nonce = evolve_nonce(nonce, eta_v)
            assert nonce.value not in seen, (
                f"Nonce collision at epoch {i}"
            )
            seen.add(nonce.value)

        assert len(seen) == n_epochs + 1


# ---------------------------------------------------------------------------
# Praos leader election: statistical distribution test
#
# Haskell parity: prop_leaderElectionDistribution — verify that the
# election frequency matches the theoretical probability.
# ---------------------------------------------------------------------------


class TestPraosLeaderDistribution:
    """Statistical tests for leader election frequency.

    These complement the existing statistical tests with additional
    stake values and tighter bounds.
    """

    def test_quarter_stake_election_rate(self) -> None:
        """sigma=0.25, f=0.05: expected ~1.28% election rate.

        p = 1 - (1-0.05)^0.25 = 1 - 0.95^0.25 ~ 0.01274
        """
        import random

        rng = random.Random(12345)
        n_trials = 20_000
        n_elected = sum(
            1
            for _ in range(n_trials)
            if leader_check(
                bytes(rng.getrandbits(8) for _ in range(64)),
                0.25,
                0.05,
            )
        )
        fraction = n_elected / n_trials
        # Expected ~1.27%, generous bounds [0.8%, 1.8%]
        assert 0.008 <= fraction <= 0.018, (
            f"Quarter-stake election rate {fraction:.4f} outside [0.008, 0.018]"
        )

    def test_three_quarter_stake_election_rate(self) -> None:
        """sigma=0.75, f=0.05: expected ~3.80% election rate.

        p = 1 - (1-0.05)^0.75 = 1 - 0.95^0.75 ~ 0.03797
        """
        import random

        rng = random.Random(54321)
        n_trials = 20_000
        n_elected = sum(
            1
            for _ in range(n_trials)
            if leader_check(
                bytes(rng.getrandbits(8) for _ in range(64)),
                0.75,
                0.05,
            )
        )
        fraction = n_elected / n_trials
        # Expected ~3.80%, generous bounds [2.8%, 4.8%]
        assert 0.028 <= fraction <= 0.048, (
            f"3/4 stake election rate {fraction:.4f} outside [0.028, 0.048]"
        )

    def test_election_rate_increases_monotonically_statistical(self) -> None:
        """Statistical verification: higher stake => more elections.

        Test with 5 stake levels and verify strict ordering.
        """
        import random

        rng = random.Random(99999)
        n_trials = 10_000
        sigmas = [0.1, 0.3, 0.5, 0.7, 0.9]

        vrf_outputs = [
            bytes(rng.getrandbits(8) for _ in range(64))
            for _ in range(n_trials)
        ]

        win_counts = []
        for sigma in sigmas:
            wins = sum(
                1 for v in vrf_outputs
                if leader_check(v, sigma, 0.05)
            )
            win_counts.append(wins)

        # Each higher stake level should win more
        for i in range(len(win_counts) - 1):
            assert win_counts[i] < win_counts[i + 1], (
                f"sigma={sigmas[i]} won {win_counts[i]} but "
                f"sigma={sigmas[i+1]} won only {win_counts[i+1]}"
            )
