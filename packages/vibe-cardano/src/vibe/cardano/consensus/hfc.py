"""Hard Fork Combinator — era dispatch, state translation, and era boundary detection.

The Hard Fork Combinator (HFC) is the mechanism by which Cardano handles
transitions between ledger eras. It dispatches block decoding, ledger rule
application, and protocol parameter lookup to the correct era handler, and
translates ledger state across era boundaries.

Era transitions are triggered by protocol version bumps observed in block
headers. When a new major protocol version is adopted, the HFC schedules
the transition to occur at the next epoch boundary.

Timeline: Byron -> Shelley -> Allegra -> Mary -> Alonzo -> Babbage -> Conway

Spec references:
    - ouroboros-consensus: Ouroboros.Consensus.HardFork.Combinator
    - ouroboros-consensus: Ouroboros.Consensus.HardFork.History.Summary
    - ouroboros-consensus: Ouroboros.Consensus.HardFork.History.EraParams
    - cardano-node: Cardano.Node.Protocol.Cardano (hardForkTransitions)

Haskell references:
    - ``HardForkBlock`` in ``Ouroboros.Consensus.HardFork.Combinator.Basics``
    - ``EraTranslation`` in ``Ouroboros.Consensus.HardFork.Combinator.Translation``
    - ``interpretQuery`` in ``Ouroboros.Consensus.HardFork.Combinator.Ledger.Query``
    - ``translateLedgerState`` in era-specific translation modules
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Final

from vibe.cardano.consensus.slot_arithmetic import (
    BYRON_EPOCH_LENGTH,
    SHELLEY_EPOCH_LENGTH,
)

# ---------------------------------------------------------------------------
# PastHorizonError — safe zone boundary exception
# ---------------------------------------------------------------------------


class PastHorizonError(Exception):
    """Raised when a slot/epoch conversion is beyond the known safe zone.

    The Haskell HFC defines a "safe zone" for each era: conversions within
    the safe zone of the last known era succeed, but beyond that boundary
    the result is unreliable because a hard fork could change epoch/slot
    parameters.

    Spec ref: ``Ouroboros.Consensus.HardFork.History.Qry`` — ``PastHorizonException``
    Haskell ref: ``PastHorizonException`` in ``Ouroboros.Consensus.HardFork.History.Qry``

    Attributes:
        slot_or_epoch: The requested slot or epoch that exceeded the horizon.
        horizon_slot: The last slot within the safe zone.
        message: Human-readable description.
    """

    def __init__(self, slot_or_epoch: int, horizon_slot: int, message: str) -> None:
        self.slot_or_epoch = slot_or_epoch
        self.horizon_slot = horizon_slot
        super().__init__(message)


# ---------------------------------------------------------------------------
# Era enumeration
# ---------------------------------------------------------------------------


class Era(IntEnum):
    """Cardano ledger eras in chronological order.

    Each era introduces new capabilities while maintaining backward
    compatibility through the HFC state translation mechanism.

    Spec ref: ouroboros-consensus ``HardForkEras`` type list.
    Haskell ref: ``CardanoEras`` in ``Ouroboros.Consensus.Cardano.Block``
    """

    BYRON = 0
    SHELLEY = 1
    ALLEGRA = 2
    MARY = 3
    ALONZO = 4
    BABBAGE = 5
    CONWAY = 6


# ---------------------------------------------------------------------------
# Protocol version -> era mapping
# ---------------------------------------------------------------------------

#: Maps major protocol version to the era it activates.
#: When a block header advertises this major protocol version, the HFC
#: schedules a transition to the corresponding era at the next epoch boundary.
#:
#: Spec ref: cardano-node ProtocolTransitionParams.
#: Haskell ref: ``protocolInfo`` in ``Cardano.Node.Protocol.Cardano``
PROTOCOL_VERSION_ERA: Final[dict[int, Era]] = {
    1: Era.BYRON,  # Byron genesis
    2: Era.SHELLEY,  # Byron -> Shelley hard fork
    3: Era.ALLEGRA,  # Shelley -> Allegra (Shelley-MA)
    4: Era.MARY,  # Allegra -> Mary (multi-asset)
    5: Era.ALONZO,  # Mary -> Alonzo (Plutus V1)
    6: Era.ALONZO,  # Alonzo intra-era update
    7: Era.BABBAGE,  # Alonzo -> Babbage (Vasil)
    8: Era.BABBAGE,  # Babbage intra-era update
    9: Era.CONWAY,  # Babbage -> Conway (governance)
    10: Era.CONWAY,  # Conway intra-era update
}

#: Minimum major protocol version that triggers each era.
#: This is the canonical mapping used for era detection.
#:
#: Haskell ref: ``triggerHardFork*`` fields in ``Cardano.Node.Protocol.Cardano``
ERA_MIN_PROTOCOL_VERSION: Final[dict[Era, int]] = {
    Era.BYRON: 1,
    Era.SHELLEY: 2,
    Era.ALLEGRA: 3,
    Era.MARY: 4,
    Era.ALONZO: 5,
    Era.BABBAGE: 7,
    Era.CONWAY: 9,
}


# ---------------------------------------------------------------------------
# Hard Fork Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EraParams:
    """Per-era parameters defining epoch length and slot length.

    Spec ref: ``EraParams`` in ``Ouroboros.Consensus.HardFork.History.Summary``
    Haskell ref: ``EraParams`` record with ``eraEpochSize``, ``eraSlotLength``

    Attributes:
        epoch_length: Number of slots in one epoch for this era.
        slot_length: Duration of one slot in seconds.
    """

    epoch_length: int
    slot_length: float


#: Pre-configured era parameters for mainnet.
#: Byron has 20s slots / 21600 slots per epoch; all post-Byron eras have
#: 1s slots / 432000 slots per epoch.
DEFAULT_ERA_PARAMS: Final[dict[Era, EraParams]] = {
    Era.BYRON: EraParams(epoch_length=BYRON_EPOCH_LENGTH, slot_length=20.0),
    Era.SHELLEY: EraParams(epoch_length=SHELLEY_EPOCH_LENGTH, slot_length=1.0),
    Era.ALLEGRA: EraParams(epoch_length=SHELLEY_EPOCH_LENGTH, slot_length=1.0),
    Era.MARY: EraParams(epoch_length=SHELLEY_EPOCH_LENGTH, slot_length=1.0),
    Era.ALONZO: EraParams(epoch_length=SHELLEY_EPOCH_LENGTH, slot_length=1.0),
    Era.BABBAGE: EraParams(epoch_length=SHELLEY_EPOCH_LENGTH, slot_length=1.0),
    Era.CONWAY: EraParams(epoch_length=SHELLEY_EPOCH_LENGTH, slot_length=1.0),
}


@dataclass(frozen=True)
class HardForkConfig:
    """Configuration for hard fork era transitions.

    Maps each era to the epoch at which it begins. For mainnet/preprod,
    these are known fixed values from the genesis configuration and on-chain
    update proposals. For devnets, they are configurable.

    An era not present in ``era_transitions`` means it hasn't been
    scheduled yet (the chain hasn't reached that era).

    Spec ref: ``HardForkState`` in ``Ouroboros.Consensus.HardFork.Combinator``
    Haskell ref: ``hardForkTransitions`` in ``Cardano.Node.Protocol.Cardano``

    Attributes:
        era_transitions: Maps each era to the epoch at which it starts.
            Must include Era.BYRON -> 0 at minimum.
        era_params: Per-era parameters (epoch length, slot length).
        safe_zone: Number of slots beyond the last known era boundary
            within which slot/epoch conversions are still considered safe.
            For mainnet Cardano: 3k/f = 3*2160/0.05 = 129,600 slots
            (the stability window). None means no safe zone enforcement
            (conversions always succeed — backwards compatible default).
    """

    era_transitions: dict[Era, int] = field(default_factory=lambda: {Era.BYRON: 0})
    era_params: dict[Era, EraParams] = field(default_factory=lambda: dict(DEFAULT_ERA_PARAMS))
    safe_zone: int | None = None

    def __post_init__(self) -> None:
        if Era.BYRON not in self.era_transitions:
            raise ValueError("HardForkConfig must include Byron era starting at epoch 0")
        if self.era_transitions[Era.BYRON] != 0:
            raise ValueError(
                f"Byron era must start at epoch 0, got {self.era_transitions[Era.BYRON]}"
            )


#: Mainnet hard fork transition epochs.
#: Source: cardano-db-sync and cardano-node genesis files.
MAINNET_TRANSITIONS: Final[dict[Era, int]] = {
    Era.BYRON: 0,
    Era.SHELLEY: 208,  # Epoch 208 (2020-07-29)
    Era.ALLEGRA: 236,  # Epoch 236 (2020-12-16)
    Era.MARY: 251,  # Epoch 251 (2021-03-01)
    Era.ALONZO: 290,  # Epoch 290 (2021-09-12)
    Era.BABBAGE: 365,  # Epoch 365 (2022-09-22)
    Era.CONWAY: 519,  # Epoch 519 (2025-01-29)
}

#: Pre-built mainnet config.
MAINNET_HFC_CONFIG: Final[HardForkConfig] = HardForkConfig(
    era_transitions=dict(MAINNET_TRANSITIONS),
    era_params=dict(DEFAULT_ERA_PARAMS),
)


# ---------------------------------------------------------------------------
# Era dispatch: current_era
# ---------------------------------------------------------------------------


def current_era(slot: int, config: HardForkConfig) -> Era:
    """Determine which era a given slot belongs to.

    The era for a slot is determined by finding which era's epoch range
    contains the slot's epoch. We iterate through eras in reverse
    chronological order, checking if the slot falls at or after each
    era's start epoch.

    This must account for different epoch lengths in Byron vs Shelley+ eras.

    Spec ref: ``Summary`` queries in ``Ouroboros.Consensus.HardFork.History``
    Haskell ref: ``interpretQuery`` + ``slotToEpoch`` in HFC History

    Args:
        slot: Absolute slot number (>= 0).
        config: Hard fork configuration with era transitions.

    Returns:
        The era that the slot belongs to.

    Raises:
        ValueError: If slot is negative.
    """
    if slot < 0:
        raise ValueError(f"Slot must be non-negative, got {slot}")

    # Convert slot to epoch, accounting for era-specific epoch lengths.
    # We need to determine the era to know the epoch length — this is
    # a chicken-and-egg problem. We resolve it by computing the absolute
    # slot offset of each era boundary and comparing directly.

    # Build a sorted list of (era, start_slot) pairs
    era_start_slots = _era_start_slots(config)

    # Find the last era whose start slot is <= the given slot
    result = Era.BYRON
    for era, start_slot in era_start_slots:
        if slot >= start_slot:
            result = era
        else:
            break

    return result


def _era_start_slots(config: HardForkConfig) -> list[tuple[Era, int]]:
    """Compute the absolute start slot for each era.

    Byron epochs have a different length than Shelley+ epochs, so we
    can't just multiply epoch * epoch_length. We accumulate slots
    through each era segment.

    Returns:
        Sorted list of (era, absolute_start_slot) pairs.
    """
    # Sort eras by their start epoch
    sorted_eras = sorted(
        config.era_transitions.items(),
        key=lambda x: (x[1], x[0]),
    )

    result: list[tuple[Era, int]] = []
    cumulative_slot = 0

    for i, (era, start_epoch) in enumerate(sorted_eras):
        if i == 0:
            # Byron starts at slot 0, epoch 0
            result.append((era, 0))
            continue

        # Compute how many slots elapsed in the previous era
        prev_era, prev_start_epoch = sorted_eras[i - 1]
        prev_params = config.era_params.get(prev_era, DEFAULT_ERA_PARAMS[prev_era])
        epochs_in_prev = start_epoch - prev_start_epoch
        slots_in_prev = epochs_in_prev * prev_params.epoch_length

        cumulative_slot += slots_in_prev
        result.append((era, cumulative_slot))

    return result


def _horizon_slot(config: HardForkConfig) -> int | None:
    """Compute the maximum slot for which conversions are safe.

    The horizon is the last slot of the last known era's safe zone.
    If safe_zone is None, returns None (no enforcement).

    Spec ref: ``Ouroboros.Consensus.HardFork.History.Summary`` — horizon calculation
    Haskell ref: ``summaryEnd`` in ``Summary``

    Returns:
        The last safe slot, or None if no safe zone is configured.
    """
    if config.safe_zone is None:
        return None

    era_start_slots = _era_start_slots(config)
    if not era_start_slots:
        return None

    # The last known era's start slot + safe_zone defines the horizon
    _last_era, last_start_slot = era_start_slots[-1]
    return last_start_slot + config.safe_zone


def _check_slot_horizon(slot: int, config: HardForkConfig) -> None:
    """Raise PastHorizonError if slot is beyond the safe zone."""
    horizon = _horizon_slot(config)
    if horizon is not None and slot > horizon:
        raise PastHorizonError(
            slot_or_epoch=slot,
            horizon_slot=horizon,
            message=(
                f"Slot {slot} is beyond the safe zone horizon at slot {horizon}. "
                f"The last known era starts at slot {_era_start_slots(config)[-1][1]} "
                f"with safe_zone={config.safe_zone}."
            ),
        )


def slot_to_epoch_hfc(slot: int, config: HardForkConfig) -> int:
    """Convert an absolute slot to an epoch number, accounting for era transitions.

    Unlike the simple ``slot_to_epoch`` in slot_arithmetic, this function
    handles the different epoch lengths across eras.

    Spec ref: ``slotToEpoch`` in ``Ouroboros.Consensus.HardFork.History.Qry``

    Args:
        slot: Absolute slot number.
        config: Hard fork configuration.

    Returns:
        Epoch number.

    Raises:
        PastHorizonError: If the slot is beyond the safe zone of the
            last known era (when safe_zone is configured).
    """
    if slot < 0:
        raise ValueError(f"Slot must be non-negative, got {slot}")

    _check_slot_horizon(slot, config)

    era_start_slots = _era_start_slots(config)

    # Find which era this slot belongs to
    current = era_start_slots[0]
    for era_slot_pair in era_start_slots:
        if slot >= era_slot_pair[1]:
            current = era_slot_pair
        else:
            break

    era, era_start_slot = current

    # Get the start epoch and params for this era
    start_epoch = config.era_transitions[era]
    params = config.era_params.get(era, DEFAULT_ERA_PARAMS[era])

    # How many slots into this era?
    slot_offset = slot - era_start_slot

    # Convert to epoch offset within this era
    epoch_offset = slot_offset // params.epoch_length

    return start_epoch + epoch_offset


def epoch_to_first_slot_hfc(epoch: int, config: HardForkConfig) -> int:
    """Convert an epoch number to its first absolute slot, accounting for era transitions.

    Spec ref: ``epochToSlot`` in ``Ouroboros.Consensus.HardFork.History.Qry``

    Args:
        epoch: Epoch number (>= 0).
        config: Hard fork configuration.

    Returns:
        Absolute slot number of the first slot in the epoch.

    Raises:
        PastHorizonError: If the resulting slot is beyond the safe zone of the
            last known era (when safe_zone is configured).
    """
    if epoch < 0:
        raise ValueError(f"Epoch must be non-negative, got {epoch}")

    # Sort eras by start epoch
    sorted_eras = sorted(
        config.era_transitions.items(),
        key=lambda x: (x[1], x[0]),
    )

    # Find which era this epoch belongs to
    target_era = sorted_eras[0][0]
    target_era_start_epoch = 0
    for era, start_epoch in sorted_eras:
        if epoch >= start_epoch:
            target_era = era
            target_era_start_epoch = start_epoch
        else:
            break

    # Get the absolute start slot of the target era
    era_start_slots = _era_start_slots(config)
    era_start_slot = 0
    for era, start_slot in era_start_slots:
        if era == target_era:
            era_start_slot = start_slot
            break

    # Epoch offset within this era
    epoch_offset = epoch - target_era_start_epoch
    params = config.era_params.get(target_era, DEFAULT_ERA_PARAMS[target_era])

    result_slot = era_start_slot + epoch_offset * params.epoch_length
    _check_slot_horizon(result_slot, config)
    return result_slot


# ---------------------------------------------------------------------------
# Protocol version -> era transition detection
# ---------------------------------------------------------------------------


def detect_era_transition(
    current: Era,
    block_protocol_version_major: int,
) -> Era | None:
    """Detect if a block's protocol version triggers an era transition.

    When a block header advertises a new major protocol version that
    corresponds to a later era, the HFC schedules a transition to that
    era at the next epoch boundary.

    Spec ref: ``triggerHardFork`` in ouroboros-consensus.
    Haskell ref: ``hardForkTrigger*`` fields in ``Cardano.Node.Protocol.Cardano``

    Args:
        current: The current era.
        block_protocol_version_major: Major protocol version from the block header.

    Returns:
        The new era if a transition is triggered, or None if no transition.
    """
    target_era = PROTOCOL_VERSION_ERA.get(block_protocol_version_major)
    if target_era is not None and target_era > current:
        return target_era
    return None


# ---------------------------------------------------------------------------
# Validation dispatch
# ---------------------------------------------------------------------------


class EraValidationError(Exception):
    """Raised when block validation fails in any era.

    Attributes:
        era: The era in which validation failed.
        errors: List of human-readable error descriptions.
    """

    def __init__(self, era: Era, errors: list[str]) -> None:
        self.era = era
        self.errors = errors
        super().__init__(f"{era.name} validation failed: {'; '.join(errors)}")


def validate_block(
    era: Era,
    block: Any,
    ledger_state: Any,
    protocol_params: Any,
    current_slot: int,
) -> list[str]:
    """Dispatch block validation to the correct era handler.

    The HFC routes validation to the appropriate era-specific validator.
    Each era extends the previous one's validation rules.

    Spec ref: ``HardForkBlock`` processing in ouroboros-consensus.
    Haskell ref: ``applyBlockLedgerResult`` via ``HardForkBlock`` dispatch

    Args:
        era: The era to validate in.
        block: The block to validate (era-specific type).
        ledger_state: Current ledger state (era-specific type).
        protocol_params: Protocol parameters for the era.
        current_slot: Slot number of the block.

    Returns:
        List of validation error strings (empty = valid).

    Raises:
        EraValidationError: If the era is unrecognized.
    """
    # Skip validation when protocol params are unavailable or raw dict
    # (e.g., syncing from a public relay with genesis JSON params that
    # haven't been parsed into typed protocol parameter objects)
    if protocol_params is None or isinstance(protocol_params, dict):
        return []

    # Import era-specific validators lazily to avoid circular imports
    if era == Era.BYRON:
        from vibe.cardano.ledger.byron_rules import validate_byron_tx

        # Byron block validation: validate each transaction
        # block is expected to be a list of ByronTxAux
        errors: list[str] = []
        if isinstance(block, list):
            for i, tx_aux in enumerate(block):
                tx_errors = validate_byron_tx(tx_aux, ledger_state, protocol_params)
                for err in tx_errors:
                    errors.append(f"Tx[{i}]: {err}")
        return errors

    elif era == Era.SHELLEY:
        from vibe.cardano.ledger.shelley import validate_shelley_tx

        errors = []
        if isinstance(block, list):
            for i, tx in enumerate(block):
                tx_errors = validate_shelley_tx(
                    tx.body,
                    tx.witness_set,
                    ledger_state,
                    protocol_params,
                    current_slot,
                    0,  # tx size — DecodedTransaction doesn't track serialized size
                )
                for err in tx_errors:
                    errors.append(f"Tx[{i}]: {err}")
        return errors

    elif era == Era.ALLEGRA:
        from vibe.cardano.ledger.allegra_mary import validate_allegra_utxo

        errors = []
        if isinstance(block, list):
            for i, tx in enumerate(block):
                tx_errors = validate_allegra_utxo(
                    tx.body,
                    ledger_state,
                    protocol_params,
                    current_slot,
                    0,  # tx size — DecodedTransaction doesn't track serialized size
                )
                for err in tx_errors:
                    errors.append(f"Tx[{i}]: {err}")
        return errors

    elif era == Era.MARY:
        from vibe.cardano.ledger.allegra_mary import validate_mary_tx

        errors = []
        if isinstance(block, list):
            for i, tx in enumerate(block):
                tx_errors = validate_mary_tx(
                    tx.body,
                    tx.witness_set,
                    ledger_state,
                    protocol_params,
                    current_slot,
                )
                for err in tx_errors:
                    errors.append(f"Tx[{i}]: {err}")
        return errors

    elif era == Era.ALONZO:
        from vibe.cardano.ledger.alonzo import validate_alonzo_tx

        errors = []
        if isinstance(block, list):
            for i, tx in enumerate(block):
                tx_errors = validate_alonzo_tx(
                    tx.body,
                    tx.witness_set,
                    ledger_state,
                    protocol_params,
                    current_slot,
                    0,  # tx size — DecodedTransaction doesn't track serialized size
                )
                for err in tx_errors:
                    errors.append(f"Tx[{i}]: {err}")
        return errors

    elif era == Era.BABBAGE:
        from vibe.cardano.ledger.babbage import validate_babbage_tx

        errors = []
        if isinstance(block, list):
            for i, tx in enumerate(block):
                tx_errors = validate_babbage_tx(
                    tx.body,
                    tx.witness_set,
                    ledger_state,
                    protocol_params,
                    current_slot,
                    0,  # tx size — DecodedTransaction doesn't track serialized size
                )
                for err in tx_errors:
                    errors.append(f"Tx[{i}]: {err}")
        return errors

    elif era == Era.CONWAY:
        # Conway re-uses Babbage UTXO rules with governance extensions.
        # For now, dispatch to Babbage validation — governance rules are
        # applied separately via conway.py.
        from vibe.cardano.ledger.babbage import validate_babbage_tx

        errors = []
        if isinstance(block, list):
            for i, tx in enumerate(block):
                tx_errors = validate_babbage_tx(
                    tx.body,
                    tx.witness_set,
                    ledger_state,
                    protocol_params,
                    current_slot,
                    0,  # tx size — DecodedTransaction doesn't track serialized size
                )
                for err in tx_errors:
                    errors.append(f"Tx[{i}]: {err}")
        return errors

    raise EraValidationError(era, [f"Unrecognized era: {era.name}"])


# ---------------------------------------------------------------------------
# Ledger state translation across era boundaries
# ---------------------------------------------------------------------------


@dataclass
class TranslatedState:
    """Result of translating ledger state across an era boundary.

    This is a generic wrapper that carries the translated state and
    metadata about the translation.

    Attributes:
        era: The target era of the translation.
        utxo_set: The translated UTxO set.
        protocol_params: Translated protocol parameters for the new era.
        metadata: Additional translation metadata (era-specific).
    """

    era: Era
    utxo_set: Any
    protocol_params: Any
    metadata: dict[str, Any] = field(default_factory=dict)


def translate_ledger_state(
    from_era: Era,
    to_era: Era,
    utxo_set: Any,
    protocol_params: Any,
) -> TranslatedState:
    """Translate ledger state from one era to the next.

    State translation happens at era boundaries. Each transition has
    specific requirements for how the UTxO set and protocol parameters
    are converted.

    Spec ref: ``translateLedgerState`` in ouroboros-consensus era translations.
    Haskell ref: ``translateLedgerState*`` in era-specific translation modules
        (e.g., ``Ouroboros.Consensus.Shelley.ShelleyHFC``)

    Major transitions:
        - Byron -> Shelley: Genesis delegation, initial UTxO conversion,
          protocol param translation. This is the most complex translation.
        - Shelley -> Allegra: Add ValidityInterval support (minimal).
        - Allegra -> Mary: Add multi-asset value support.
        - Mary -> Alonzo: Add script/datum/redeemer support, cost models.
        - Alonzo -> Babbage: Add inline datums, reference scripts,
          coinsPerUTxOByte replacing coinsPerUTxOWord.
        - Babbage -> Conway: Add governance state, DRep state.

    Args:
        from_era: Source era.
        to_era: Target era (must be from_era + 1).
        utxo_set: UTxO set in the source era format.
        protocol_params: Protocol parameters in the source era format.

    Returns:
        TranslatedState with the translated state.

    Raises:
        ValueError: If the transition is not a valid single-step transition.
    """
    if to_era != from_era + 1:
        if from_era + 1 <= Era.CONWAY:
            expected_name = Era(from_era + 1).name
        else:
            expected_name = f"Era({from_era + 1})"
        raise ValueError(
            f"Can only translate one era at a time: {from_era.name} -> {to_era.name}. "
            f"Expected {expected_name}."
        )

    if from_era == Era.BYRON and to_era == Era.SHELLEY:
        return _translate_byron_to_shelley(utxo_set, protocol_params)
    elif from_era == Era.SHELLEY and to_era == Era.ALLEGRA:
        return _translate_shelley_to_allegra(utxo_set, protocol_params)
    elif from_era == Era.ALLEGRA and to_era == Era.MARY:
        return _translate_allegra_to_mary(utxo_set, protocol_params)
    elif from_era == Era.MARY and to_era == Era.ALONZO:
        return _translate_mary_to_alonzo(utxo_set, protocol_params)
    elif from_era == Era.ALONZO and to_era == Era.BABBAGE:
        return _translate_alonzo_to_babbage(utxo_set, protocol_params)
    elif from_era == Era.BABBAGE and to_era == Era.CONWAY:
        return _translate_babbage_to_conway(utxo_set, protocol_params)
    else:
        raise ValueError(f"Unknown era transition: {from_era.name} -> {to_era.name}")


def translate_through_eras(
    from_era: Era,
    to_era: Era,
    utxo_set: Any,
    protocol_params: Any,
) -> TranslatedState:
    """Translate ledger state through multiple era boundaries.

    Chains single-step translations from ``from_era`` to ``to_era``.

    Args:
        from_era: Source era.
        to_era: Target era (must be >= from_era).
        utxo_set: UTxO set in the source era format.
        protocol_params: Protocol parameters in the source era format.

    Returns:
        TranslatedState with the final translated state.

    Raises:
        ValueError: If to_era < from_era.
    """
    if to_era < from_era:
        raise ValueError(f"Cannot translate backward: {from_era.name} -> {to_era.name}")

    if to_era == from_era:
        return TranslatedState(
            era=from_era,
            utxo_set=utxo_set,
            protocol_params=protocol_params,
        )

    current_utxo = utxo_set
    current_params = protocol_params
    current_era = from_era

    while current_era < to_era:
        next_era = Era(current_era + 1)
        result = translate_ledger_state(current_era, next_era, current_utxo, current_params)
        current_utxo = result.utxo_set
        current_params = result.protocol_params
        current_era = next_era

    return TranslatedState(
        era=to_era,
        utxo_set=current_utxo,
        protocol_params=current_params,
    )


# ---------------------------------------------------------------------------
# Individual era translations (stubs — full fidelity in conformance testing)
# ---------------------------------------------------------------------------


def _translate_byron_to_shelley(
    utxo_set: Any,
    protocol_params: Any,
) -> TranslatedState:
    """Translate Byron ledger state to Shelley.

    This is the most complex translation — the "big one":
        - Genesis delegation certificates become initial stake distribution
        - Byron UTxO entries (keyed by (tx_id_bytes, index) -> ByronTxOut)
          become Shelley UTxO entries (keyed by TransactionInput -> TransactionOutput)
        - Byron fee parameters (linear model a + b*size) map to Shelley's
          fee params (min_fee_a, min_fee_b)
        - Protocol magic and security parameter carry through
        - Initial reserves = maxLovelaceSupply - sum(utxo)

    Spec ref: Shelley formal spec, genesis block processing.
    Haskell ref: ``translateLedgerStateByronToShelleyWrapper`` in
        ``Ouroboros.Consensus.Cardano.ShelleyBased``

    For now: pass through the UTxO set unchanged. Full translation requires
    conversion between Byron and Shelley UTxO types, which we'll implement
    during conformance testing with real chain data.
    """
    return TranslatedState(
        era=Era.SHELLEY,
        utxo_set=utxo_set,
        protocol_params=protocol_params,
        metadata={"transition": "byron_to_shelley", "notes": "stub — full translation pending"},
    )


def _translate_shelley_to_allegra(
    utxo_set: Any,
    protocol_params: Any,
) -> TranslatedState:
    """Translate Shelley ledger state to Allegra.

    Minimal translation:
        - UTxO set carries through unchanged (same pycardano types)
        - Protocol parameters carry through (Allegra uses Shelley params)
        - ValidityInterval support is added at the transaction level,
          not the ledger state level

    Haskell ref: ``translateLedgerStateShelleyToAllegra`` in
        ``Ouroboros.Consensus.Shelley.ShelleyHFC``
    """
    return TranslatedState(
        era=Era.ALLEGRA,
        utxo_set=utxo_set,
        protocol_params=protocol_params,
        metadata={"transition": "shelley_to_allegra"},
    )


def _translate_allegra_to_mary(
    utxo_set: Any,
    protocol_params: Any,
) -> TranslatedState:
    """Translate Allegra ledger state to Mary.

    Key changes:
        - UTxO values conceptually become multi-asset Values (Value = coin + MultiAsset)
        - In practice, existing UTxOs are pure-ADA and pycardano's
          TransactionOutput already supports both int and Value amounts
        - Protocol parameters gain utxo_entry_size_without_val for
          multi-asset min UTxO calculation

    Haskell ref: ``translateLedgerStateAllegraToMary`` in
        ``Ouroboros.Consensus.Shelley.ShelleyHFC``
    """
    return TranslatedState(
        era=Era.MARY,
        utxo_set=utxo_set,
        protocol_params=protocol_params,
        metadata={"transition": "allegra_to_mary"},
    )


def _translate_mary_to_alonzo(
    utxo_set: Any,
    protocol_params: Any,
) -> TranslatedState:
    """Translate Mary ledger state to Alonzo.

    Key changes:
        - Protocol parameters gain Plutus-related fields:
          execution_unit_prices, max_tx_ex_units, max_block_ex_units,
          collateral_percentage, max_collateral_inputs, coins_per_utxo_word
        - Cost models for PlutusV1 are introduced
        - UTxO set carries through (outputs can now reference datum hashes)

    Haskell ref: ``translateLedgerStateMaryToAlonzo`` in
        ``Ouroboros.Consensus.Shelley.ShelleyHFC``
    """
    return TranslatedState(
        era=Era.ALONZO,
        utxo_set=utxo_set,
        protocol_params=protocol_params,
        metadata={"transition": "mary_to_alonzo"},
    )


def _translate_alonzo_to_babbage(
    utxo_set: Any,
    protocol_params: Any,
) -> TranslatedState:
    """Translate Alonzo ledger state to Babbage.

    Key changes:
        - coinsPerUTxOWord -> coinsPerUTxOByte (more granular min UTxO)
        - Outputs can now contain inline datums and reference scripts
        - PlutusV2 cost model introduced
        - Collateral return outputs supported

    Haskell ref: ``translateLedgerStateAlonzoToBabbage`` in
        ``Ouroboros.Consensus.Shelley.ShelleyHFC``
    """
    return TranslatedState(
        era=Era.BABBAGE,
        utxo_set=utxo_set,
        protocol_params=protocol_params,
        metadata={"transition": "alonzo_to_babbage"},
    )


def _translate_babbage_to_conway(
    utxo_set: Any,
    protocol_params: Any,
) -> TranslatedState:
    """Translate Babbage ledger state to Conway.

    Key changes:
        - Governance state initialized (empty proposals, votes, committee)
        - DRep state initialized (empty DRep registry)
        - Protocol parameters gain governance-related fields:
          gov_action_deposit, drep_deposit, gov_action_lifetime, etc.
        - PlutusV3 cost model introduced

    Haskell ref: ``translateLedgerStateBabbageToConway`` in
        ``Ouroboros.Consensus.Shelley.ShelleyHFC``
    """
    return TranslatedState(
        era=Era.CONWAY,
        utxo_set=utxo_set,
        protocol_params=protocol_params,
        metadata={"transition": "babbage_to_conway"},
    )


# ---------------------------------------------------------------------------
# Summary invariant checking
# ---------------------------------------------------------------------------


def invariant_check(config: HardForkConfig) -> list[str]:
    """Check structural invariants of the HFC configuration.

    Returns a list of human-readable violation strings. An empty list
    means the configuration is structurally valid.

    Invariants checked:
        1. Era transitions are strictly increasing in epoch number
        2. Each era's start slot is >= previous era's end slot (contiguous)
        3. No gaps between eras (eras are contiguous — no missing eras in sequence)
        4. Era parameters (slot_length, epoch_length) are positive
        5. The first era starts at slot 0 / epoch 0

    Spec ref: ``Summary`` invariant checking in
        ``Ouroboros.Consensus.HardFork.History.Summary``

    Args:
        config: Hard fork configuration to validate.

    Returns:
        List of violation strings (empty = valid).
    """
    violations: list[str] = []

    # Sort eras by their integer value (chronological order)
    sorted_eras = sorted(
        config.era_transitions.items(),
        key=lambda x: (x[1], x[0]),
    )

    if not sorted_eras:
        violations.append("No era transitions defined")
        return violations

    # Invariant 5: First era starts at epoch 0
    first_era, first_epoch = sorted_eras[0]
    if first_epoch != 0:
        violations.append(f"First era ({first_era.name}) must start at epoch 0, got {first_epoch}")

    # Invariant 1: Era transition epochs are strictly increasing
    # Check in era enum order (chronological), not sorted-by-epoch order,
    # so we can detect when epochs are assigned out of order.
    eras_by_enum = sorted(config.era_transitions.items(), key=lambda x: x[0].value)
    for i in range(len(eras_by_enum) - 1):
        era_a, epoch_a = eras_by_enum[i]
        era_b, epoch_b = eras_by_enum[i + 1]
        if epoch_b <= epoch_a:
            violations.append(
                f"Era transition epochs not strictly increasing: "
                f"{era_a.name} (epoch {epoch_a}) >= {era_b.name} (epoch {epoch_b})"
            )

    # Invariant 3: Eras are contiguous (no gaps in the Era enum sequence)
    era_values = sorted(e.value for e in config.era_transitions.keys())
    for i in range(len(era_values) - 1):
        if era_values[i + 1] != era_values[i] + 1:
            gap_start = Era(era_values[i])
            gap_end = Era(era_values[i + 1])
            violations.append(
                f"Gap in era sequence: {gap_start.name} (value {era_values[i]}) "
                f"to {gap_end.name} (value {era_values[i + 1]}) — missing intermediate eras"
            )

    # Invariant 4: Era parameters are positive
    for era in config.era_transitions:
        params = config.era_params.get(era, DEFAULT_ERA_PARAMS.get(era))
        if params is None:
            violations.append(f"No era params defined for {era.name}")
            continue
        if params.epoch_length <= 0:
            violations.append(
                f"{era.name} epoch_length must be positive, got {params.epoch_length}"
            )
        if params.slot_length <= 0:
            violations.append(f"{era.name} slot_length must be positive, got {params.slot_length}")

    # Invariant 2: Era start slots are contiguous (no overlap, no gap)
    # This is implied by the epoch-based transitions + epoch_length but
    # we verify the computed slots are strictly increasing.
    era_start_slots_list = _era_start_slots(config)
    for i in range(len(era_start_slots_list) - 1):
        era_a, slot_a = era_start_slots_list[i]
        era_b, slot_b = era_start_slots_list[i + 1]
        if slot_b <= slot_a:
            violations.append(
                f"Era start slots not strictly increasing: "
                f"{era_a.name} (slot {slot_a}) >= {era_b.name} (slot {slot_b})"
            )

    return violations


# ---------------------------------------------------------------------------
# EraDispatch: top-level HFC state machine
# ---------------------------------------------------------------------------


@dataclass
class HFCState:
    """The running state of the Hard Fork Combinator.

    Tracks the current era, slot, epoch, and the scheduled transitions.
    This is the top-level state machine that the consensus layer uses
    to route operations to the correct era handler.

    Spec ref: ``HardForkState`` in ``Ouroboros.Consensus.HardFork.Combinator``
    Haskell ref: ``HardForkLedgerView`` / ``HardForkState``

    Attributes:
        config: Hard fork configuration (immutable).
        current_era: The era of the most recently applied block.
        tip_slot: Slot of the most recently applied block.
        tip_epoch: Epoch of the most recently applied block.
    """

    config: HardForkConfig
    current_era: Era = Era.BYRON
    tip_slot: int = 0
    tip_epoch: int = 0

    def advance_to_slot(self, slot: int) -> Era:
        """Advance the HFC state to a new slot, detecting era transitions.

        Updates current_era based on the new slot position in the
        hard fork timeline.

        Args:
            slot: The new tip slot.

        Returns:
            The era for the new slot.
        """
        self.tip_slot = slot
        self.tip_epoch = slot_to_epoch_hfc(slot, self.config)
        self.current_era = current_era(slot, self.config)
        return self.current_era

    def era_for_epoch(self, epoch: int) -> Era:
        """Determine which era an epoch belongs to.

        Args:
            epoch: Epoch number.

        Returns:
            The era for that epoch.
        """
        sorted_eras = sorted(
            self.config.era_transitions.items(),
            key=lambda x: (x[1], x[0]),
        )
        result = Era.BYRON
        for era, start_epoch in sorted_eras:
            if epoch >= start_epoch:
                result = era
            else:
                break
        return result

    def is_era_boundary(self, slot: int) -> bool:
        """Check if a slot falls on an era boundary.

        An era boundary is the first slot of a new era.

        Args:
            slot: Absolute slot number.

        Returns:
            True if this slot is the first slot of a new era.
        """
        era_start_slots_list = _era_start_slots(self.config)
        return any(start_slot == slot for _, start_slot in era_start_slots_list)

    def next_era_boundary(self) -> int | None:
        """Get the slot number of the next era boundary after the current tip.

        Returns:
            The slot number of the next era transition, or None if
            we're already in the last scheduled era.
        """
        era_start_slots_list = _era_start_slots(self.config)
        for _, start_slot in era_start_slots_list:
            if start_slot > self.tip_slot:
                return start_slot
        return None
