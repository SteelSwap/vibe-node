"""Slot/epoch/time arithmetic for Cardano's era-based timeline.

Cardano's timeline is divided into fixed-length slots grouped into epochs.
The slot length and epoch length differ between Byron and Shelley+ eras:

    Byron:    slot_length = 20s, epoch_length = 21600 slots (= 5 days)
    Shelley+: slot_length = 1s,  epoch_length = 432000 slots (= 5 days)

The transition from Byron to Shelley resets the slot numbering.  Byron slots
are counted from the system start; Shelley slots continue from the first
Shelley slot.  The ``SlotConfig`` captures per-era parameters; callers must
use the correct config for the era a slot belongs to.

Spec references:
    - Shelley formal spec, Section 3.1 — "Time" (slot, epoch definitions)
    - Byron spec — slot_duration = 20 seconds
    - ouroboros-consensus: Ouroboros.Consensus.HardFork.History.Qry
      (era translations, slot/epoch/time queries)
    - ouroboros-consensus: Ouroboros.Consensus.BlockchainTime.WallClock.Util

Haskell references:
    - Ouroboros.Consensus.HardFork.History.Summary (EraParams)
    - Ouroboros.Consensus.Shelley.Ledger.Config (shelleyEraParams)
    - Ouroboros.Consensus.Byron.Ledger.Config (byronEraParams)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

# ---------------------------------------------------------------------------
# Constants — mainnet era parameters
# ---------------------------------------------------------------------------

#: Byron slot length in seconds (one slot per 20 seconds).
BYRON_SLOT_LENGTH: Final[float] = 20.0

#: Byron epoch length in slots (21600 slots * 20s = 432000s = 5 days).
BYRON_EPOCH_LENGTH: Final[int] = 21600

#: Shelley+ slot length in seconds (one slot per second).
SHELLEY_SLOT_LENGTH: Final[float] = 1.0

#: Shelley+ epoch length in slots (432000 slots * 1s = 432000s = 5 days).
SHELLEY_EPOCH_LENGTH: Final[int] = 432000

#: Cardano mainnet system start time (2017-09-23T21:44:51Z).
MAINNET_SYSTEM_START: Final[datetime] = datetime(2017, 9, 23, 21, 44, 51, tzinfo=UTC)

#: SlotsPerKESPeriod on Cardano mainnet (129600 slots = 36 hours).
MAINNET_SLOTS_PER_KES_PERIOD: Final[int] = 129600


# ---------------------------------------------------------------------------
# SlotConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SlotConfig:
    """Per-era slot/epoch configuration.

    Each Cardano era has its own slot length and epoch length.  A
    ``SlotConfig`` captures these parameters along with the system start
    time, which anchors slot 0 to wall-clock time.

    For multi-era conversions (e.g., a Shelley slot that needs to account
    for Byron's different slot length), the caller must track the era
    boundary slot and use the correct config for each segment.

    Haskell ref: ``EraParams`` in
        ``Ouroboros.Consensus.HardFork.History.Summary``

    Attributes:
        system_start: UTC timestamp of slot 0 (genesis).
        slot_length: Duration of one slot in seconds.
        epoch_length: Number of slots in one epoch.
    """

    system_start: datetime
    slot_length: float
    epoch_length: int

    def __post_init__(self) -> None:
        if self.slot_length <= 0:
            raise ValueError(f"slot_length must be positive, got {self.slot_length}")
        if self.epoch_length <= 0:
            raise ValueError(f"epoch_length must be positive, got {self.epoch_length}")


#: Pre-built Byron config for mainnet.
BYRON_CONFIG: Final[SlotConfig] = SlotConfig(
    system_start=MAINNET_SYSTEM_START,
    slot_length=BYRON_SLOT_LENGTH,
    epoch_length=BYRON_EPOCH_LENGTH,
)

#: Pre-built Shelley+ config for mainnet.
SHELLEY_CONFIG: Final[SlotConfig] = SlotConfig(
    system_start=MAINNET_SYSTEM_START,
    slot_length=SHELLEY_SLOT_LENGTH,
    epoch_length=SHELLEY_EPOCH_LENGTH,
)


# ---------------------------------------------------------------------------
# Slot <-> Epoch conversions
# ---------------------------------------------------------------------------


def slot_to_epoch(slot: int, config: SlotConfig) -> int:
    """Convert an absolute slot number to its epoch number.

    ``epoch = slot // epoch_length``

    Spec ref: Shelley formal spec, Section 3.1 — "The epoch of a slot s
    is ⌊s / epoch_length⌋"

    Haskell ref: ``slotToEpoch`` in
        ``Ouroboros.Consensus.HardFork.History.Qry``

    Args:
        slot: Absolute slot number (>= 0).
        config: Era-specific slot configuration.

    Returns:
        Epoch number (0-indexed).

    Raises:
        ValueError: If slot is negative.
    """
    if slot < 0:
        raise ValueError(f"Slot must be non-negative, got {slot}")
    return slot // config.epoch_length


def epoch_to_first_slot(epoch: int, config: SlotConfig) -> int:
    """Convert an epoch number to the first slot in that epoch.

    ``first_slot = epoch * epoch_length``

    Spec ref: Shelley formal spec — "The first slot of epoch e is
    e * epoch_length"

    Haskell ref: ``epochToSlot`` in
        ``Ouroboros.Consensus.HardFork.History.Qry``

    Args:
        epoch: Epoch number (>= 0).
        config: Era-specific slot configuration.

    Returns:
        Absolute slot number of the first slot in the epoch.

    Raises:
        ValueError: If epoch is negative.
    """
    if epoch < 0:
        raise ValueError(f"Epoch must be non-negative, got {epoch}")
    return epoch * config.epoch_length


# ---------------------------------------------------------------------------
# Slot <-> Wall-clock conversions
# ---------------------------------------------------------------------------


def slot_to_wall_clock(slot: int, config: SlotConfig) -> datetime:
    """Convert an absolute slot number to its wall-clock start time.

    ``time = system_start + slot * slot_length``

    The returned timestamp is the *start* of the slot, not the end.

    Haskell ref: ``slotToWallclock`` in
        ``Ouroboros.Consensus.BlockchainTime.WallClock.Util``

    Args:
        slot: Absolute slot number (>= 0).
        config: Era-specific slot configuration.

    Returns:
        UTC datetime of the slot's start time.

    Raises:
        ValueError: If slot is negative.
    """
    if slot < 0:
        raise ValueError(f"Slot must be non-negative, got {slot}")
    delta = timedelta(seconds=slot * config.slot_length)
    return config.system_start + delta


def wall_clock_to_slot(time: datetime, config: SlotConfig) -> int:
    """Convert a wall-clock time to the slot that contains it.

    ``slot = floor((time - system_start) / slot_length)``

    If the time is before system start, returns 0 (clamped).

    Haskell ref: ``wallclockToSlot`` in
        ``Ouroboros.Consensus.BlockchainTime.WallClock.Util``

    Args:
        time: UTC datetime.
        config: Era-specific slot configuration.

    Returns:
        Absolute slot number.
    """
    delta = (time - config.system_start).total_seconds()
    if delta < 0:
        return 0
    return int(delta / config.slot_length)


# ---------------------------------------------------------------------------
# Slot -> KES period
# ---------------------------------------------------------------------------


def slot_to_kes_period(
    slot: int,
    slots_per_kes_period: int = MAINNET_SLOTS_PER_KES_PERIOD,
) -> int:
    """Convert a slot number to a KES period.

    ``kesPeriod(s) = s // SlotsPerKESPeriod``

    This is a pure integer division — no era-specific logic needed
    because KES periods are defined over absolute Shelley+ slots.

    Spec ref: Shelley formal spec — ``kesPeriod`` function.
    Haskell ref: ``kesPeriod`` in ``Cardano.Protocol.TPraos.BHeader``

    Args:
        slot: Absolute slot number (Shelley+ slot, >= 0).
        slots_per_kes_period: Protocol parameter ``SlotsPerKESPeriod``
            (129600 on mainnet).

    Returns:
        KES period number.

    Raises:
        ValueError: If slot is negative or slots_per_kes_period <= 0.
    """
    if slot < 0:
        raise ValueError(f"Slot must be non-negative, got {slot}")
    if slots_per_kes_period <= 0:
        raise ValueError(f"slots_per_kes_period must be positive, got {slots_per_kes_period}")
    return slot // slots_per_kes_period
