"""vibe.cardano.consensus — Ouroboros Praos consensus implementation.

This package provides:

* **Slot Arithmetic** — era-aware slot/epoch/time conversions handling
  Byron (20s slots, 21600 epoch length) and Shelley+ (1s slots, 432000
  epoch length) with era transition support.
* **Chain Selection** — longest-chain rule with k-deep finality,
  fork choice within the security window, and deterministic VRF
  tiebreaking per the Ouroboros Praos specification.
* **Header Validation** — full block header verification including
  slot monotonicity, block number sequencing, VRF leader eligibility,
  KES signature verification, and operational certificate validation.
* **Praos Protocol** — the top-level Ouroboros Praos state machine
  that ties together leader election, header validation, and chain
  state transitions.

Spec references:
    - Ouroboros Praos paper (Crypto 2017), Sections 3-4
    - Shelley formal spec, Sections 3 (chain state), 16 (VRF/leader)
    - Ouroboros.Consensus.Protocol.Praos (Haskell)
"""

from .chain_selection import (
    ChainCandidate,
    Preference,
    compare_chains,
    is_chain_better,
    should_switch_to,
)
from .header_validation import (
    HeaderValidationError,
    validate_header,
)
from .praos import (
    ActiveSlotCoeff,
    PraosState,
    apply_header,
    leader_check,
)
from .slot_arithmetic import (
    SlotConfig,
    epoch_to_first_slot,
    slot_to_epoch,
    slot_to_kes_period,
    slot_to_wall_clock,
    wall_clock_to_slot,
)

__all__ = [
    # Slot arithmetic
    "SlotConfig",
    "epoch_to_first_slot",
    "slot_to_epoch",
    "slot_to_kes_period",
    "slot_to_wall_clock",
    "wall_clock_to_slot",
    # Chain selection
    "ChainCandidate",
    "Preference",
    "compare_chains",
    "is_chain_better",
    "should_switch_to",
    # Header validation
    "HeaderValidationError",
    "validate_header",
    # Praos protocol
    "ActiveSlotCoeff",
    "PraosState",
    "apply_header",
    "leader_check",
]
