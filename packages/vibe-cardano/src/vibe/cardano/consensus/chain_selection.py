"""Chain selection rules for Ouroboros Praos.

Ouroboros Praos uses a **longest-chain** rule: prefer the chain with the
highest block number (not the highest slot number, since slots can be
empty).  When two chains have the same block number, the protocol breaks
ties deterministically using the VRF output — the chain whose tip has
the lower VRF output wins.  If no VRF preference exists, stay on the
current chain (Haskell has no block-hash fallback).

Chain selection is constrained by the **security parameter k** (2160 on
mainnet).  A block more than k blocks from the tip is considered
immutable — we will never roll it back.  When evaluating whether to
switch to a candidate chain, we require:

1. The candidate must be strictly longer (higher block_number).
2. The fork point (common ancestor) must be within the last k blocks
   of our chain.  If the candidate forks deeper than k, we reject it
   regardless of length — switching would violate the immutability
   guarantee.

Spec references:
    - Ouroboros Praos paper, Section 3 — "The protocol" (chain selection)
    - Ouroboros Praos paper, Definition 4 — "maxvalid" (prefer longer chain)
    - Shelley formal spec, Section 3.3 — chain preference

Haskell references:
    - Ouroboros.Consensus.Protocol.Praos (preferCandidate, compareCandidates)
    - Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
    - Ouroboros.Consensus.Block.Abstract (preferAnchoredCandidate)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Security parameter k — number of blocks for immutability on mainnet.
SECURITY_PARAM_K: Final[int] = 2160


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Preference(Enum):
    """Result of comparing two chain candidates.

    Haskell ref: ``Ordering`` result from ``compareCandidates``
    """

    PREFER_FIRST = auto()
    """First chain is preferred (longer, or same length with lower VRF)."""

    PREFER_SECOND = auto()
    """Second chain is preferred."""

    EQUAL = auto()
    """Chains are equally preferred (same block_number AND same VRF output)."""


@dataclass(frozen=True, slots=True)
class ChainCandidate:
    """Summary of a chain tip for comparison purposes.

    This captures the minimal information needed for chain selection
    without requiring the full block data.

    Attributes:
        tip_slot: Slot number of the tip block.
        tip_block_number: Block height of the tip (used for length comparison).
        tip_hash: 32-byte block header hash of the tip.
        chain_length: Total chain length (may differ from tip_block_number
            in edge cases with genesis offsets, but usually identical).
        vrf_output: Optional 64-byte VRF output for deterministic tiebreaking.
            If None, chains with equal block number are considered EQUAL.
    """

    tip_slot: int
    tip_block_number: int
    tip_hash: bytes
    chain_length: int
    vrf_output: bytes | None = None


# ---------------------------------------------------------------------------
# Chain comparison
# ---------------------------------------------------------------------------


def compare_chains(
    chain_a: ChainCandidate,
    chain_b: ChainCandidate,
) -> Preference:
    """Compare two chain candidates and return which is preferred.

    The comparison follows the Ouroboros Praos chain selection rule:

    1. **Prefer the longer chain** — the one with higher ``tip_block_number``.
       Block number is the canonical measure of chain length in Cardano,
       NOT slot number (since slots can be empty).

    2. **Tiebreak on VRF output** — if both chains have the same block
       number and both provide VRF outputs, prefer the chain whose tip
       has the lexicographically lower VRF output. This ensures
       deterministic, unpredictable tiebreaking.

    3. **No fallback** — if VRF outputs are unavailable or equal,
       return EQUAL. Haskell stays on the current chain when there is
       no preference (no block hash fallback).

    Spec ref: Ouroboros Praos, Definition 4 — maxvalid selects the
    longest valid chain.

    Haskell ref: ``compareCandidates`` in
        ``Ouroboros.Consensus.Protocol.Abstract``
        ``selectView`` for Praos uses block number + VRF tiebreaker.

    Args:
        chain_a: First chain candidate.
        chain_b: Second chain candidate.

    Returns:
        Preference indicating which chain is preferred.
    """
    # Primary: prefer higher block number (longer chain)
    if chain_a.tip_block_number > chain_b.tip_block_number:
        return Preference.PREFER_FIRST
    if chain_b.tip_block_number > chain_a.tip_block_number:
        return Preference.PREFER_SECOND

    # Tiebreak: same block number — use VRF output (lower wins).
    # Haskell ref: comparePraos uses `compare `on` Down . ptvTieBreakVRF`
    # which prefers lower VRF (Down reverses the ordering).
    # When VRF outputs are equal or unavailable, return EQUAL — Haskell
    # stays on the current chain (no block hash fallback).
    if chain_a.vrf_output is not None and chain_b.vrf_output is not None:
        if chain_a.vrf_output < chain_b.vrf_output:
            return Preference.PREFER_FIRST
        if chain_b.vrf_output < chain_a.vrf_output:
            return Preference.PREFER_SECOND

    return Preference.EQUAL


def is_chain_better(
    our_tip: ChainCandidate,
    candidate_tip: ChainCandidate,
) -> bool:
    """Check if a candidate chain is strictly better than our current chain.

    A simple convenience wrapper around ``compare_chains`` that returns
    True if the candidate is preferred over our chain.

    Args:
        our_tip: Our current chain's tip summary.
        candidate_tip: The candidate chain's tip summary.

    Returns:
        True if the candidate is strictly preferred.
    """
    return compare_chains(candidate_tip, our_tip) == Preference.PREFER_FIRST


# ---------------------------------------------------------------------------
# Fork choice with k-deep finality
# ---------------------------------------------------------------------------


def should_switch_to(
    our_chain: ChainCandidate,
    candidate_chain: ChainCandidate,
    k: int = SECURITY_PARAM_K,
    *,
    fork_point_block_number: int | None = None,
) -> bool:
    """Determine whether we should switch to a candidate chain.

    This implements the full Praos chain selection with the k-deep
    finality constraint:

    1. The candidate must be strictly better (longer, or same length
       with lower VRF tiebreaker).
    2. If a fork point is provided, the fork must be within the last
       k blocks of our chain.  A fork deeper than k would require
       rolling back immutable blocks, which is forbidden.

    If no ``fork_point_block_number`` is provided, only the length/VRF
    comparison is performed (useful when the fork point hasn't been
    computed yet — the caller should verify it separately).

    Spec ref: Ouroboros Praos paper, Section 3 — "A party adopts the
    longest valid chain, provided the fork point is within the last k
    blocks."

    Haskell ref:
        ``Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel``
        — checks that the intersection point is within the volatile
        suffix (i.e., within k blocks of the tip).

    Args:
        our_chain: Our current chain tip summary.
        candidate_chain: The candidate chain tip summary.
        k: Security parameter (default 2160).
        fork_point_block_number: Block number of the common ancestor,
            or None if unknown.

    Returns:
        True if we should switch to the candidate chain.
    """
    # Must be strictly better
    if not is_chain_better(our_chain, candidate_chain):
        return False

    # If fork point is provided, check k-deep finality constraint
    if fork_point_block_number is not None:
        # The fork point must be within the last k blocks of our chain.
        # Equivalently: our_tip.block_number - fork_point <= k
        depth = our_chain.tip_block_number - fork_point_block_number
        if depth > k:
            return False

    return True
