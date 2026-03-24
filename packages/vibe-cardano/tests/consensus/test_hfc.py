"""Tests for vibe.cardano.consensus.hfc — Hard Fork Combinator.

Covers:
- Era enumeration ordering and values
- Era determination from slots (boundary conditions)
- Era dispatch to correct validator (mock blocks)
- State translation at each boundary (structural, no crash)
- Protocol version detection triggers correct era transition
- Multi-era slot/epoch arithmetic
- HFCState advance and era boundary detection
- Hypothesis: era determination is monotonic in slot number
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.consensus.hfc import (
    DEFAULT_ERA_PARAMS,
    ERA_MIN_PROTOCOL_VERSION,
    MAINNET_HFC_CONFIG,
    MAINNET_TRANSITIONS,
    PROTOCOL_VERSION_ERA,
    Era,
    EraParams,
    HardForkConfig,
    HFCState,
    PastHorizonError,
    _era_start_slots,
    current_era,
    detect_era_transition,
    epoch_to_first_slot_hfc,
    invariant_check,
    slot_to_epoch_hfc,
    translate_ledger_state,
    translate_through_eras,
    validate_block,
)
from vibe.cardano.consensus.slot_arithmetic import (
    BYRON_EPOCH_LENGTH,
    SHELLEY_EPOCH_LENGTH,
)

# ---------------------------------------------------------------------------
# Era enumeration
# ---------------------------------------------------------------------------


class TestEra:
    def test_era_values_ascending(self) -> None:
        """Era integer values must be strictly ascending."""
        eras = list(Era)
        for i in range(len(eras) - 1):
            assert eras[i] < eras[i + 1]

    def test_era_count(self) -> None:
        """There are exactly 7 eras (Byron through Conway)."""
        assert len(Era) == 7

    def test_era_names(self) -> None:
        """All expected era names are present."""
        names = {e.name for e in Era}
        assert names == {"BYRON", "SHELLEY", "ALLEGRA", "MARY", "ALONZO", "BABBAGE", "CONWAY"}

    def test_era_integer_identity(self) -> None:
        """Era values match their ordinal position."""
        assert Era.BYRON == 0
        assert Era.SHELLEY == 1
        assert Era.ALLEGRA == 2
        assert Era.MARY == 3
        assert Era.ALONZO == 4
        assert Era.BABBAGE == 5
        assert Era.CONWAY == 6

    def test_era_comparison(self) -> None:
        """IntEnum comparison works for era ordering."""
        assert Era.BYRON < Era.SHELLEY
        assert Era.CONWAY > Era.BABBAGE
        assert Era.MARY >= Era.MARY


# ---------------------------------------------------------------------------
# HardForkConfig
# ---------------------------------------------------------------------------


class TestHardForkConfig:
    def test_default_config_byron_only(self) -> None:
        """Default config starts with Byron at epoch 0."""
        config = HardForkConfig()
        assert Era.BYRON in config.era_transitions
        assert config.era_transitions[Era.BYRON] == 0

    def test_mainnet_config_has_all_eras(self) -> None:
        """Mainnet config includes all 7 eras."""
        assert len(MAINNET_HFC_CONFIG.era_transitions) == 7
        for era in Era:
            assert era in MAINNET_HFC_CONFIG.era_transitions

    def test_mainnet_transitions_monotonic(self) -> None:
        """Mainnet era start epochs are monotonically increasing."""
        epochs = [MAINNET_TRANSITIONS[era] for era in Era]
        for i in range(len(epochs) - 1):
            assert epochs[i] < epochs[i + 1], (
                f"Era {Era(i).name} epoch {epochs[i]} >= "
                f"Era {Era(i + 1).name} epoch {epochs[i + 1]}"
            )

    def test_config_requires_byron(self) -> None:
        """Config must include Byron era."""
        with pytest.raises(ValueError, match="must include Byron"):
            HardForkConfig(era_transitions={Era.SHELLEY: 208})

    def test_config_byron_must_be_epoch_zero(self) -> None:
        """Byron must start at epoch 0."""
        with pytest.raises(ValueError, match="must start at epoch 0"):
            HardForkConfig(era_transitions={Era.BYRON: 1})

    def test_custom_config(self) -> None:
        """Custom devnet config with different transition epochs."""
        config = HardForkConfig(
            era_transitions={
                Era.BYRON: 0,
                Era.SHELLEY: 1,
                Era.ALLEGRA: 2,
                Era.MARY: 3,
            }
        )
        assert config.era_transitions[Era.SHELLEY] == 1
        assert Era.ALONZO not in config.era_transitions


# ---------------------------------------------------------------------------
# Era start slot computation
# ---------------------------------------------------------------------------


class TestEraStartSlots:
    def test_byron_starts_at_slot_zero(self) -> None:
        """Byron always starts at absolute slot 0."""
        config = MAINNET_HFC_CONFIG
        slots = _era_start_slots(config)
        assert slots[0] == (Era.BYRON, 0)

    def test_shelley_start_slot_mainnet(self) -> None:
        """Shelley starts after 208 Byron epochs (208 * 21600 = 4492800)."""
        config = MAINNET_HFC_CONFIG
        slots = _era_start_slots(config)
        era_slots = dict(slots)
        expected = 208 * BYRON_EPOCH_LENGTH  # 4492800
        assert era_slots[Era.SHELLEY] == expected

    def test_allegra_start_slot_mainnet(self) -> None:
        """Allegra starts after Byron + Shelley epochs."""
        config = MAINNET_HFC_CONFIG
        slots = _era_start_slots(config)
        era_slots = dict(slots)
        # 208 Byron epochs + (236 - 208) Shelley epochs
        byron_slots = 208 * BYRON_EPOCH_LENGTH
        shelley_slots = (236 - 208) * SHELLEY_EPOCH_LENGTH
        expected = byron_slots + shelley_slots
        assert era_slots[Era.ALLEGRA] == expected

    def test_start_slots_monotonic(self) -> None:
        """Era start slots are strictly increasing."""
        config = MAINNET_HFC_CONFIG
        slots = _era_start_slots(config)
        for i in range(len(slots) - 1):
            assert slots[i][1] < slots[i + 1][1]


# ---------------------------------------------------------------------------
# current_era determination
# ---------------------------------------------------------------------------


class TestCurrentEra:
    def test_slot_zero_is_byron(self) -> None:
        """Slot 0 is always Byron."""
        assert current_era(0, MAINNET_HFC_CONFIG) == Era.BYRON

    def test_last_byron_slot(self) -> None:
        """The last slot before Shelley is still Byron."""
        shelley_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.SHELLEY]
        assert current_era(shelley_start - 1, MAINNET_HFC_CONFIG) == Era.BYRON

    def test_first_shelley_slot(self) -> None:
        """The first Shelley slot is Shelley."""
        shelley_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.SHELLEY]
        assert current_era(shelley_start, MAINNET_HFC_CONFIG) == Era.SHELLEY

    def test_deep_in_shelley(self) -> None:
        """A slot well into Shelley era is Shelley."""
        shelley_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.SHELLEY]
        assert current_era(shelley_start + 100000, MAINNET_HFC_CONFIG) == Era.SHELLEY

    def test_first_conway_slot(self) -> None:
        """The first Conway slot is Conway."""
        conway_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.CONWAY]
        assert current_era(conway_start, MAINNET_HFC_CONFIG) == Era.CONWAY

    def test_far_future_is_conway(self) -> None:
        """A very large slot is Conway (the latest era)."""
        assert current_era(999_999_999, MAINNET_HFC_CONFIG) == Era.CONWAY

    def test_all_era_boundaries(self) -> None:
        """Each era boundary slot maps to the correct era."""
        slots = _era_start_slots(MAINNET_HFC_CONFIG)
        for era, start_slot in slots:
            assert current_era(start_slot, MAINNET_HFC_CONFIG) == era

    def test_negative_slot_raises(self) -> None:
        """Negative slots raise ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            current_era(-1, MAINNET_HFC_CONFIG)

    def test_byron_only_config(self) -> None:
        """With only Byron configured, all slots are Byron."""
        config = HardForkConfig()
        assert current_era(0, config) == Era.BYRON
        assert current_era(999_999_999, config) == Era.BYRON


# ---------------------------------------------------------------------------
# Slot/epoch HFC arithmetic
# ---------------------------------------------------------------------------


class TestSlotEpochHFC:
    def test_slot_zero_is_epoch_zero(self) -> None:
        assert slot_to_epoch_hfc(0, MAINNET_HFC_CONFIG) == 0

    def test_last_byron_slot_epoch(self) -> None:
        """Last Byron slot should be in epoch 207."""
        shelley_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.SHELLEY]
        epoch = slot_to_epoch_hfc(shelley_start - 1, MAINNET_HFC_CONFIG)
        assert epoch == 207

    def test_first_shelley_slot_epoch(self) -> None:
        """First Shelley slot should be in epoch 208."""
        shelley_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.SHELLEY]
        epoch = slot_to_epoch_hfc(shelley_start, MAINNET_HFC_CONFIG)
        assert epoch == 208

    def test_epoch_to_first_slot_roundtrip(self) -> None:
        """Converting epoch to first slot and back should be identity."""
        for epoch in [0, 100, 208, 209, 300, 400, 519, 520]:
            slot = epoch_to_first_slot_hfc(epoch, MAINNET_HFC_CONFIG)
            recovered = slot_to_epoch_hfc(slot, MAINNET_HFC_CONFIG)
            assert recovered == epoch, f"Epoch {epoch}: slot={slot}, recovered={recovered}"

    def test_byron_epoch_slot_conversion(self) -> None:
        """Byron: epoch 10 starts at slot 10 * 21600 = 216000."""
        slot = epoch_to_first_slot_hfc(10, MAINNET_HFC_CONFIG)
        assert slot == 10 * BYRON_EPOCH_LENGTH

    def test_shelley_epoch_slot_conversion(self) -> None:
        """Shelley: epoch 209 starts one Shelley epoch after epoch 208."""
        shelley_start = epoch_to_first_slot_hfc(208, MAINNET_HFC_CONFIG)
        epoch_209_slot = epoch_to_first_slot_hfc(209, MAINNET_HFC_CONFIG)
        assert epoch_209_slot == shelley_start + SHELLEY_EPOCH_LENGTH

    def test_negative_slot_raises(self) -> None:
        with pytest.raises(ValueError):
            slot_to_epoch_hfc(-1, MAINNET_HFC_CONFIG)

    def test_negative_epoch_raises(self) -> None:
        with pytest.raises(ValueError):
            epoch_to_first_slot_hfc(-1, MAINNET_HFC_CONFIG)


# ---------------------------------------------------------------------------
# Protocol version -> era transition detection
# ---------------------------------------------------------------------------


class TestDetectEraTransition:
    def test_no_transition_same_era(self) -> None:
        """Protocol version 1 in Byron doesn't trigger a transition."""
        assert detect_era_transition(Era.BYRON, 1) is None

    def test_byron_to_shelley(self) -> None:
        """Protocol version 2 in Byron triggers Shelley."""
        assert detect_era_transition(Era.BYRON, 2) == Era.SHELLEY

    def test_shelley_to_allegra(self) -> None:
        """Protocol version 3 in Shelley triggers Allegra."""
        assert detect_era_transition(Era.SHELLEY, 3) == Era.ALLEGRA

    def test_allegra_to_mary(self) -> None:
        """Protocol version 4 in Allegra triggers Mary."""
        assert detect_era_transition(Era.ALLEGRA, 4) == Era.MARY

    def test_mary_to_alonzo(self) -> None:
        """Protocol version 5 in Mary triggers Alonzo."""
        assert detect_era_transition(Era.MARY, 5) == Era.ALONZO

    def test_alonzo_to_babbage(self) -> None:
        """Protocol version 7 in Alonzo triggers Babbage."""
        assert detect_era_transition(Era.ALONZO, 7) == Era.BABBAGE

    def test_babbage_to_conway(self) -> None:
        """Protocol version 9 in Babbage triggers Conway."""
        assert detect_era_transition(Era.BABBAGE, 9) == Era.CONWAY

    def test_intra_era_update_no_transition(self) -> None:
        """Protocol version 6 in Alonzo is intra-era, no transition."""
        assert detect_era_transition(Era.ALONZO, 6) is None

    def test_downgrade_no_transition(self) -> None:
        """A lower protocol version in a later era doesn't trigger transition."""
        assert detect_era_transition(Era.CONWAY, 2) is None

    def test_unknown_version(self) -> None:
        """Unknown protocol version doesn't trigger transition."""
        assert detect_era_transition(Era.CONWAY, 99) is None

    def test_all_forward_transitions(self) -> None:
        """Verify the complete chain of forward transitions."""
        transitions = [
            (Era.BYRON, 2, Era.SHELLEY),
            (Era.SHELLEY, 3, Era.ALLEGRA),
            (Era.ALLEGRA, 4, Era.MARY),
            (Era.MARY, 5, Era.ALONZO),
            (Era.ALONZO, 7, Era.BABBAGE),
            (Era.BABBAGE, 9, Era.CONWAY),
        ]
        for from_era, pv, expected in transitions:
            result = detect_era_transition(from_era, pv)
            assert (
                result == expected
            ), f"Expected {from_era.name} + PV{pv} -> {expected.name}, got {result}"


# ---------------------------------------------------------------------------
# State translation
# ---------------------------------------------------------------------------


class TestStateTranslation:
    """Test that state translation functions don't crash and produce correct metadata."""

    def test_byron_to_shelley(self) -> None:
        result = translate_ledger_state(Era.BYRON, Era.SHELLEY, {}, {})
        assert result.era == Era.SHELLEY
        assert result.metadata["transition"] == "byron_to_shelley"

    def test_shelley_to_allegra(self) -> None:
        result = translate_ledger_state(Era.SHELLEY, Era.ALLEGRA, {}, {})
        assert result.era == Era.ALLEGRA

    def test_allegra_to_mary(self) -> None:
        result = translate_ledger_state(Era.ALLEGRA, Era.MARY, {}, {})
        assert result.era == Era.MARY

    def test_mary_to_alonzo(self) -> None:
        result = translate_ledger_state(Era.MARY, Era.ALONZO, {}, {})
        assert result.era == Era.ALONZO

    def test_alonzo_to_babbage(self) -> None:
        result = translate_ledger_state(Era.ALONZO, Era.BABBAGE, {}, {})
        assert result.era == Era.BABBAGE

    def test_babbage_to_conway(self) -> None:
        result = translate_ledger_state(Era.BABBAGE, Era.CONWAY, {}, {})
        assert result.era == Era.CONWAY

    def test_skip_era_raises(self) -> None:
        """Cannot skip an era (e.g., Byron -> Mary)."""
        with pytest.raises(ValueError, match="one era at a time"):
            translate_ledger_state(Era.BYRON, Era.MARY, {}, {})

    def test_same_era_raises(self) -> None:
        """Cannot translate to the same era."""
        with pytest.raises(ValueError, match="one era at a time"):
            translate_ledger_state(Era.SHELLEY, Era.SHELLEY, {}, {})

    def test_backward_raises(self) -> None:
        """Cannot translate backward."""
        with pytest.raises(ValueError, match="one era at a time"):
            translate_ledger_state(Era.CONWAY, Era.BABBAGE, {}, {})

    def test_utxo_passthrough(self) -> None:
        """UTxO set is passed through in stub translations."""
        utxo = {"key": "value"}
        result = translate_ledger_state(Era.SHELLEY, Era.ALLEGRA, utxo, {})
        assert result.utxo_set == utxo

    def test_params_passthrough(self) -> None:
        """Protocol params are passed through in stub translations."""
        params = {"min_fee": 44}
        result = translate_ledger_state(Era.ALLEGRA, Era.MARY, {}, params)
        assert result.protocol_params == params


class TestTranslateThroughEras:
    """Test multi-era translation chaining."""

    def test_same_era_noop(self) -> None:
        result = translate_through_eras(Era.BYRON, Era.BYRON, {}, {})
        assert result.era == Era.BYRON

    def test_single_step(self) -> None:
        result = translate_through_eras(Era.BYRON, Era.SHELLEY, {}, {})
        assert result.era == Era.SHELLEY

    def test_full_chain(self) -> None:
        """Translate from Byron all the way to Conway."""
        result = translate_through_eras(Era.BYRON, Era.CONWAY, {}, {})
        assert result.era == Era.CONWAY

    def test_partial_chain(self) -> None:
        """Translate from Shelley to Babbage (4 steps)."""
        result = translate_through_eras(Era.SHELLEY, Era.BABBAGE, {}, {})
        assert result.era == Era.BABBAGE

    def test_backward_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot translate backward"):
            translate_through_eras(Era.CONWAY, Era.BYRON, {}, {})


# ---------------------------------------------------------------------------
# HFCState
# ---------------------------------------------------------------------------


class TestHFCState:
    def test_initial_state(self) -> None:
        state = HFCState(config=MAINNET_HFC_CONFIG)
        assert state.current_era == Era.BYRON
        assert state.tip_slot == 0
        assert state.tip_epoch == 0

    def test_advance_to_byron_slot(self) -> None:
        state = HFCState(config=MAINNET_HFC_CONFIG)
        era = state.advance_to_slot(100)
        assert era == Era.BYRON
        assert state.tip_slot == 100

    def test_advance_to_shelley(self) -> None:
        state = HFCState(config=MAINNET_HFC_CONFIG)
        shelley_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.SHELLEY]
        era = state.advance_to_slot(shelley_start + 1000)
        assert era == Era.SHELLEY
        assert state.current_era == Era.SHELLEY

    def test_advance_to_conway(self) -> None:
        state = HFCState(config=MAINNET_HFC_CONFIG)
        conway_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.CONWAY]
        era = state.advance_to_slot(conway_start + 1)
        assert era == Era.CONWAY

    def test_era_for_epoch(self) -> None:
        state = HFCState(config=MAINNET_HFC_CONFIG)
        assert state.era_for_epoch(0) == Era.BYRON
        assert state.era_for_epoch(207) == Era.BYRON
        assert state.era_for_epoch(208) == Era.SHELLEY
        assert state.era_for_epoch(236) == Era.ALLEGRA
        assert state.era_for_epoch(519) == Era.CONWAY

    def test_is_era_boundary(self) -> None:
        state = HFCState(config=MAINNET_HFC_CONFIG)
        assert state.is_era_boundary(0)  # Byron start
        shelley_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.SHELLEY]
        assert state.is_era_boundary(shelley_start)
        assert not state.is_era_boundary(shelley_start + 1)

    def test_next_era_boundary_from_byron(self) -> None:
        state = HFCState(config=MAINNET_HFC_CONFIG)
        state.advance_to_slot(100)
        boundary = state.next_era_boundary()
        shelley_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.SHELLEY]
        assert boundary == shelley_start

    def test_next_era_boundary_from_conway(self) -> None:
        """Conway is the last era — no next boundary."""
        state = HFCState(config=MAINNET_HFC_CONFIG)
        conway_start = dict(_era_start_slots(MAINNET_HFC_CONFIG))[Era.CONWAY]
        state.advance_to_slot(conway_start + 1000)
        assert state.next_era_boundary() is None


# ---------------------------------------------------------------------------
# Validation dispatch (mock blocks)
# ---------------------------------------------------------------------------


class TestValidateBlock:
    """Test that validate_block dispatches to the correct era without crashing.

    We use empty block lists since full validation requires real
    pycardano objects — the dispatch mechanism is what we're testing.
    """

    def test_byron_empty_block(self) -> None:
        errors = validate_block(Era.BYRON, [], {}, None, 0)
        assert errors == []

    def test_shelley_empty_block(self) -> None:
        errors = validate_block(Era.SHELLEY, [], {}, None, 0)
        assert errors == []

    def test_allegra_empty_block(self) -> None:
        errors = validate_block(Era.ALLEGRA, [], {}, None, 0)
        assert errors == []

    def test_mary_empty_block(self) -> None:
        errors = validate_block(Era.MARY, [], {}, None, 0)
        assert errors == []

    def test_alonzo_empty_block(self) -> None:
        errors = validate_block(Era.ALONZO, [], {}, None, 0)
        assert errors == []

    def test_babbage_empty_block(self) -> None:
        errors = validate_block(Era.BABBAGE, [], {}, None, 0)
        assert errors == []

    def test_conway_empty_block(self) -> None:
        errors = validate_block(Era.CONWAY, [], {}, None, 0)
        assert errors == []

    def test_non_list_block_returns_empty(self) -> None:
        """If block is not a list, validators return empty errors."""
        errors = validate_block(Era.BYRON, "not_a_list", {}, None, 0)
        assert errors == []


# ---------------------------------------------------------------------------
# Protocol version / era mapping consistency
# ---------------------------------------------------------------------------


class TestProtocolVersionEraMapping:
    def test_every_era_has_min_protocol_version(self) -> None:
        """Each era has a minimum protocol version defined."""
        for era in Era:
            assert era in ERA_MIN_PROTOCOL_VERSION

    def test_min_versions_monotonic(self) -> None:
        """Minimum protocol versions increase with eras."""
        prev_version = 0
        for era in Era:
            version = ERA_MIN_PROTOCOL_VERSION[era]
            assert (
                version >= prev_version
            ), f"{era.name} min PV {version} < previous {prev_version}"
            prev_version = version

    def test_protocol_version_era_covers_1_through_10(self) -> None:
        """Protocol versions 1-10 all map to a valid era."""
        for pv in range(1, 11):
            assert pv in PROTOCOL_VERSION_ERA
            assert isinstance(PROTOCOL_VERSION_ERA[pv], Era)


# ---------------------------------------------------------------------------
# Devnet configuration
# ---------------------------------------------------------------------------


class TestDevnetConfig:
    """Test HFC with a fast-transition devnet config."""

    def test_fast_transitions(self) -> None:
        """Devnet with all eras transitioning every epoch."""
        config = HardForkConfig(
            era_transitions={
                Era.BYRON: 0,
                Era.SHELLEY: 1,
                Era.ALLEGRA: 2,
                Era.MARY: 3,
                Era.ALONZO: 4,
                Era.BABBAGE: 5,
                Era.CONWAY: 6,
            }
        )
        # Byron slot range: epoch 0 = slots 0..21599
        assert current_era(0, config) == Era.BYRON
        assert current_era(21599, config) == Era.BYRON

        # Shelley starts at epoch 1 = slot 21600 (after 1 Byron epoch)
        assert current_era(21600, config) == Era.SHELLEY

        # Allegra starts at epoch 2 = 21600 + 432000 = 453600
        assert current_era(453600, config) == Era.ALLEGRA

    def test_single_era_no_transitions(self) -> None:
        """Config with only Byron — everything is Byron."""
        config = HardForkConfig(era_transitions={Era.BYRON: 0})
        assert current_era(0, config) == Era.BYRON
        assert current_era(99999999, config) == Era.BYRON


# ---------------------------------------------------------------------------
# Hypothesis properties
# ---------------------------------------------------------------------------


class TestHypothesisProperties:
    @given(
        slot1=st.integers(min_value=0, max_value=500_000_000),
        slot2=st.integers(min_value=0, max_value=500_000_000),
    )
    @settings(max_examples=200)
    def test_era_monotonic_in_slot(self, slot1: int, slot2: int) -> None:
        """Era determination must be monotonically non-decreasing with slot number.

        If slot_a <= slot_b, then era(slot_a) <= era(slot_b).
        This is a fundamental invariant — the chain never goes backward in eras.
        """
        if slot1 > slot2:
            slot1, slot2 = slot2, slot1
        era1 = current_era(slot1, MAINNET_HFC_CONFIG)
        era2 = current_era(slot2, MAINNET_HFC_CONFIG)
        assert (
            era1 <= era2
        ), f"Era monotonicity violated: slot {slot1} -> {era1.name}, slot {slot2} -> {era2.name}"

    @given(epoch=st.integers(min_value=0, max_value=10000))
    @settings(max_examples=100)
    def test_epoch_slot_roundtrip(self, epoch: int) -> None:
        """epoch_to_first_slot -> slot_to_epoch should return the original epoch."""
        slot = epoch_to_first_slot_hfc(epoch, MAINNET_HFC_CONFIG)
        recovered = slot_to_epoch_hfc(slot, MAINNET_HFC_CONFIG)
        assert recovered == epoch

    @given(slot=st.integers(min_value=0, max_value=500_000_000))
    @settings(max_examples=200)
    def test_slot_epoch_era_consistency(self, slot: int) -> None:
        """The era for a slot and the era for its epoch should agree."""
        epoch = slot_to_epoch_hfc(slot, MAINNET_HFC_CONFIG)
        era_from_slot = current_era(slot, MAINNET_HFC_CONFIG)
        state = HFCState(config=MAINNET_HFC_CONFIG)
        era_from_epoch = state.era_for_epoch(epoch)
        assert era_from_slot == era_from_epoch, (
            f"Slot {slot} (epoch {epoch}): era_from_slot={era_from_slot.name}, "
            f"era_from_epoch={era_from_epoch.name}"
        )


# ---------------------------------------------------------------------------
# Test 1: PastHorizonError for out-of-range conversions
# ---------------------------------------------------------------------------


class TestPastHorizonError:
    """Test that slot/epoch conversions beyond the known era boundary raise PastHorizonError.

    The Haskell HFC raises PastHorizonException when a query falls outside
    the Summary's safe zone. Our implementation mirrors this with PastHorizonError.

    Spec ref: ``PastHorizonException`` in ``Ouroboros.Consensus.HardFork.History.Qry``
    """

    def _alonzo_only_config(self) -> HardForkConfig:
        """Config that only knows about eras up to Alonzo, with safe_zone."""
        return HardForkConfig(
            era_transitions={
                Era.BYRON: 0,
                Era.SHELLEY: 208,
                Era.ALLEGRA: 236,
                Era.MARY: 251,
                Era.ALONZO: 290,
            },
            safe_zone=129_600,  # 3k/f = 3*2160/0.05
        )

    def test_slot_within_safe_zone_succeeds(self) -> None:
        """Conversion at the boundary of the safe zone should succeed."""
        config = self._alonzo_only_config()
        era_slots = dict(_era_start_slots(config))
        alonzo_start = era_slots[Era.ALONZO]
        # Exactly at the horizon (alonzo_start + safe_zone) should succeed
        horizon_slot = alonzo_start + 129_600
        epoch = slot_to_epoch_hfc(horizon_slot, config)
        assert epoch >= 290  # Should be in the Alonzo range

    def test_slot_one_beyond_safe_zone_raises(self) -> None:
        """Conversion one slot beyond the safe zone should raise PastHorizonError."""
        config = self._alonzo_only_config()
        era_slots = dict(_era_start_slots(config))
        alonzo_start = era_slots[Era.ALONZO]
        beyond_horizon = alonzo_start + 129_600 + 1
        with pytest.raises(PastHorizonError) as exc_info:
            slot_to_epoch_hfc(beyond_horizon, config)
        assert exc_info.value.slot_or_epoch == beyond_horizon
        assert exc_info.value.horizon_slot == alonzo_start + 129_600

    def test_conway_slot_with_alonzo_config_raises(self) -> None:
        """A Conway-era slot with a config that only knows up to Alonzo raises PastHorizonError.

        This simulates what happens during chain sync when the node doesn't
        yet know about future hard forks.
        """
        config = self._alonzo_only_config()
        # Conway would start around slot ~140M on mainnet, well beyond Alonzo safe zone
        conway_era_slot = 200_000_000
        with pytest.raises(PastHorizonError):
            slot_to_epoch_hfc(conway_era_slot, config)

    def test_epoch_beyond_safe_zone_raises(self) -> None:
        """epoch_to_first_slot_hfc also raises PastHorizonError beyond the safe zone."""
        config = self._alonzo_only_config()
        # Epoch 10000 is way beyond what Alonzo-only config can handle
        with pytest.raises(PastHorizonError):
            epoch_to_first_slot_hfc(10000, config)

    def test_no_safe_zone_never_raises(self) -> None:
        """When safe_zone is None (default), conversions never raise PastHorizonError."""
        # MAINNET_HFC_CONFIG has safe_zone=None by default
        assert MAINNET_HFC_CONFIG.safe_zone is None
        # Even absurdly large slots should work
        epoch = slot_to_epoch_hfc(999_999_999, MAINNET_HFC_CONFIG)
        assert epoch > 0

    def test_past_horizon_error_attributes(self) -> None:
        """PastHorizonError carries the right attributes."""
        err = PastHorizonError(slot_or_epoch=500, horizon_slot=400, message="test")
        assert err.slot_or_epoch == 500
        assert err.horizon_slot == 400
        assert "test" in str(err)

    def test_epoch_at_safe_zone_boundary_succeeds(self) -> None:
        """Epoch whose first slot is exactly at the horizon should succeed."""
        config = self._alonzo_only_config()
        era_slots = dict(_era_start_slots(config))
        alonzo_start = era_slots[Era.ALONZO]
        horizon_slot = alonzo_start + 129_600
        # Find the epoch that starts at or just before the horizon
        epoch = slot_to_epoch_hfc(horizon_slot, config)
        # Converting that epoch back should succeed
        first_slot = epoch_to_first_slot_hfc(epoch, config)
        assert first_slot <= horizon_slot


# ---------------------------------------------------------------------------
# Test 2: Safe zone boundary handling
# ---------------------------------------------------------------------------


class TestSafeZoneBoundary:
    """Test the safe zone concept more thoroughly.

    Safe zone = stability_window = 3k/f slots. For Cardano mainnet:
    k=2160, f=0.05 => 3*2160/0.05 = 129,600 slots.

    Spec ref: ``SafeZone`` in ``Ouroboros.Consensus.HardFork.History.EraParams``
    """

    def test_safe_zone_stored_in_config(self) -> None:
        """safe_zone is a proper field on HardForkConfig."""
        config = HardForkConfig(
            era_transitions={Era.BYRON: 0},
            safe_zone=129_600,
        )
        assert config.safe_zone == 129_600

    def test_safe_zone_default_is_none(self) -> None:
        """Default config has no safe zone enforcement."""
        config = HardForkConfig()
        assert config.safe_zone is None

    def test_safe_zone_cardano_value(self) -> None:
        """Verify the Cardano mainnet safe zone calculation: 3k/f."""
        k = 2160
        f = 0.05
        safe_zone = int(3 * k / f)
        assert safe_zone == 129_600

    def test_within_safe_zone_last_era(self) -> None:
        """Conversions within safe_zone slots of the last era start succeed."""
        config = HardForkConfig(
            era_transitions={
                Era.BYRON: 0,
                Era.SHELLEY: 10,
            },
            safe_zone=50_000,
        )
        # Shelley starts at slot 10 * 21600 = 216000
        shelley_start = dict(_era_start_slots(config))[Era.SHELLEY]
        # Within safe zone: should work
        slot_to_epoch_hfc(shelley_start + 49_999, config)
        slot_to_epoch_hfc(shelley_start + 50_000, config)

    def test_beyond_safe_zone_last_era(self) -> None:
        """Conversions beyond safe_zone of the last era fail."""
        config = HardForkConfig(
            era_transitions={
                Era.BYRON: 0,
                Era.SHELLEY: 10,
            },
            safe_zone=50_000,
        )
        shelley_start = dict(_era_start_slots(config))[Era.SHELLEY]
        with pytest.raises(PastHorizonError):
            slot_to_epoch_hfc(shelley_start + 50_001, config)

    def test_safe_zone_with_full_config_no_raises(self) -> None:
        """Full mainnet config with safe_zone still works for known-era slots.

        When all eras are configured, the safe zone extends from the last
        (Conway) era start. Reasonable slots in Conway should be fine.
        """
        config = HardForkConfig(
            era_transitions=dict(MAINNET_TRANSITIONS),
            era_params=dict(DEFAULT_ERA_PARAMS),
            safe_zone=129_600,
        )
        conway_start = dict(_era_start_slots(config))[Era.CONWAY]
        # Just inside safe zone
        epoch = slot_to_epoch_hfc(conway_start + 100_000, config)
        assert epoch >= 519

    def test_safe_zone_with_full_config_beyond_raises(self) -> None:
        """Even with all eras, slots way beyond the last era + safe zone fail."""
        config = HardForkConfig(
            era_transitions=dict(MAINNET_TRANSITIONS),
            era_params=dict(DEFAULT_ERA_PARAMS),
            safe_zone=129_600,
        )
        conway_start = dict(_era_start_slots(config))[Era.CONWAY]
        with pytest.raises(PastHorizonError):
            slot_to_epoch_hfc(conway_start + 200_000, config)

    def test_safe_zone_zero(self) -> None:
        """A safe_zone of 0 means only the era start slot itself is safe."""
        config = HardForkConfig(
            era_transitions={Era.BYRON: 0},
            safe_zone=0,
        )
        # Slot 0 is the Byron start, which equals the horizon
        slot_to_epoch_hfc(0, config)
        # Slot 1 is beyond
        with pytest.raises(PastHorizonError):
            slot_to_epoch_hfc(1, config)


# ---------------------------------------------------------------------------
# Test 3: Summary invariant checking
# ---------------------------------------------------------------------------


class TestInvariantCheck:
    """Test structural invariants of the HFC configuration.

    Spec ref: ``Summary`` invariants in ``Ouroboros.Consensus.HardFork.History.Summary``
    """

    def test_mainnet_config_valid(self) -> None:
        """Mainnet config passes all invariant checks."""
        violations = invariant_check(MAINNET_HFC_CONFIG)
        assert violations == [], f"Mainnet config has violations: {violations}"

    def test_default_config_valid(self) -> None:
        """Default (Byron-only) config passes all invariant checks."""
        config = HardForkConfig()
        violations = invariant_check(config)
        assert violations == []

    def test_non_monotonic_epochs_detected(self) -> None:
        """Detect when era transition epochs aren't strictly increasing."""
        # Manually construct an invalid config (bypass __post_init__ by using
        # a config where the epoch ordering is violated but Byron is still 0)
        config = HardForkConfig.__new__(HardForkConfig)
        object.__setattr__(
            config,
            "era_transitions",
            {
                Era.BYRON: 0,
                Era.SHELLEY: 100,
                Era.ALLEGRA: 50,  # violation: 50 < 100
            },
        )
        object.__setattr__(config, "era_params", dict(DEFAULT_ERA_PARAMS))
        object.__setattr__(config, "safe_zone", None)
        violations = invariant_check(config)
        assert any("not strictly increasing" in v for v in violations)

    def test_gap_in_era_sequence_detected(self) -> None:
        """Detect when there's a gap in the era sequence (e.g., Byron -> Mary, skipping Shelley)."""
        config = HardForkConfig(
            era_transitions={
                Era.BYRON: 0,
                Era.MARY: 100,  # Skips Shelley and Allegra
            },
        )
        violations = invariant_check(config)
        assert any("Gap in era sequence" in v for v in violations)

    def test_negative_epoch_length_detected(self) -> None:
        """Detect when epoch_length is non-positive."""
        config = HardForkConfig(
            era_transitions={Era.BYRON: 0},
            era_params={Era.BYRON: EraParams(epoch_length=-100, slot_length=20.0)},
        )
        violations = invariant_check(config)
        assert any("epoch_length must be positive" in v for v in violations)

    def test_zero_slot_length_detected(self) -> None:
        """Detect when slot_length is zero."""
        config = HardForkConfig(
            era_transitions={Era.BYRON: 0},
            era_params={Era.BYRON: EraParams(epoch_length=21600, slot_length=0.0)},
        )
        violations = invariant_check(config)
        assert any("slot_length must be positive" in v for v in violations)

    def test_first_era_not_epoch_zero_detected(self) -> None:
        """Detect when the first era doesn't start at epoch 0.

        Note: HardForkConfig.__post_init__ catches this for Byron specifically,
        but invariant_check should also flag it.
        """
        config = HardForkConfig.__new__(HardForkConfig)
        object.__setattr__(config, "era_transitions", {Era.BYRON: 5})
        object.__setattr__(config, "era_params", dict(DEFAULT_ERA_PARAMS))
        object.__setattr__(config, "safe_zone", None)
        violations = invariant_check(config)
        assert any("must start at epoch 0" in v for v in violations)

    def test_valid_devnet_config(self) -> None:
        """A well-formed devnet config with fast transitions passes."""
        config = HardForkConfig(
            era_transitions={
                Era.BYRON: 0,
                Era.SHELLEY: 1,
                Era.ALLEGRA: 2,
                Era.MARY: 3,
                Era.ALONZO: 4,
                Era.BABBAGE: 5,
                Era.CONWAY: 6,
            },
        )
        violations = invariant_check(config)
        assert violations == []

    def test_contiguous_eras_pass(self) -> None:
        """A config with contiguous eras (no gaps) passes the gap check."""
        config = HardForkConfig(
            era_transitions={
                Era.BYRON: 0,
                Era.SHELLEY: 10,
                Era.ALLEGRA: 20,
            },
        )
        violations = invariant_check(config)
        assert not any("Gap" in v for v in violations)

    def test_multiple_violations_reported(self) -> None:
        """invariant_check reports ALL violations, not just the first."""
        config = HardForkConfig.__new__(HardForkConfig)
        object.__setattr__(
            config,
            "era_transitions",
            {
                Era.BYRON: 5,  # violation: not epoch 0
                Era.ALONZO: 3,  # violation: gap (missing Shelley/Allegra/Mary)
            },
        )
        object.__setattr__(
            config,
            "era_params",
            {
                Era.BYRON: EraParams(epoch_length=0, slot_length=-1.0),  # two violations
                Era.ALONZO: EraParams(epoch_length=432000, slot_length=1.0),
            },
        )
        object.__setattr__(config, "safe_zone", None)
        violations = invariant_check(config)
        # Should have at least: epoch 0 violation, gap violation, epoch_length, slot_length
        assert (
            len(violations) >= 4
        ), f"Expected >= 4 violations, got {len(violations)}: {violations}"


# ---------------------------------------------------------------------------
# Test 4: EpochInfo adapter correctness
# ---------------------------------------------------------------------------


class TestEpochInfoAdapter:
    """Test that slot/epoch conversion functions are consistent with each other.

    These properties mirror the EpochInfo adapter in the Haskell HFC,
    which provides slot<->epoch conversions to the ledger layer.

    Spec ref: ``EpochInfo`` in ``Ouroboros.Consensus.HardFork.History.EpochInfo``
    """

    def test_slot_to_epoch_to_first_slot_leq(self) -> None:
        """For any slot S: epoch_to_first_slot(slot_to_epoch(S)) <= S.

        The first slot of an epoch is always <= any slot in that epoch.
        """
        test_slots = [0, 1, 21599, 21600, 100_000, 4_492_799, 4_492_800, 50_000_000]
        for slot in test_slots:
            epoch = slot_to_epoch_hfc(slot, MAINNET_HFC_CONFIG)
            first_slot = epoch_to_first_slot_hfc(epoch, MAINNET_HFC_CONFIG)
            assert (
                first_slot <= slot
            ), f"Slot {slot}: epoch={epoch}, first_slot_of_epoch={first_slot} > slot"

    def test_epoch_to_first_slot_to_epoch_identity(self) -> None:
        """For any epoch E: slot_to_epoch(epoch_to_first_slot(E)) == E.

        The first slot of epoch E must map back to epoch E.
        """
        test_epochs = [0, 1, 100, 207, 208, 235, 236, 250, 251, 289, 290, 364, 365, 518, 519, 600]
        for epoch in test_epochs:
            first_slot = epoch_to_first_slot_hfc(epoch, MAINNET_HFC_CONFIG)
            recovered_epoch = slot_to_epoch_hfc(first_slot, MAINNET_HFC_CONFIG)
            assert (
                recovered_epoch == epoch
            ), f"Epoch {epoch}: first_slot={first_slot}, recovered={recovered_epoch}"

    def test_roundtrip_slot_epoch_first_slot(self) -> None:
        """Round-trip: slot -> epoch -> first_slot_of_epoch -> verify <= original.

        Checks both directions of the conversion contract across era boundaries.
        """
        # Test slots at every era boundary and mid-era
        era_slots = dict(_era_start_slots(MAINNET_HFC_CONFIG))
        for era, start_slot in era_slots.items():
            for offset in [0, 1, 1000, 100_000]:
                slot = start_slot + offset
                epoch = slot_to_epoch_hfc(slot, MAINNET_HFC_CONFIG)
                first_slot = epoch_to_first_slot_hfc(epoch, MAINNET_HFC_CONFIG)
                assert first_slot <= slot
                assert slot_to_epoch_hfc(first_slot, MAINNET_HFC_CONFIG) == epoch

    @given(slot=st.integers(min_value=0, max_value=500_000_000))
    @settings(max_examples=500)
    def test_hypothesis_first_slot_leq_original(self, slot: int) -> None:
        """Hypothesis: epoch_to_first_slot(slot_to_epoch(S)) <= S for all S.

        This is the fundamental EpochInfo contract — the first slot of the
        epoch containing S is never after S.
        """
        epoch = slot_to_epoch_hfc(slot, MAINNET_HFC_CONFIG)
        first_slot = epoch_to_first_slot_hfc(epoch, MAINNET_HFC_CONFIG)
        assert first_slot <= slot, (
            f"EpochInfo contract violated: slot={slot}, epoch={epoch}, "
            f"first_slot_of_epoch={first_slot}"
        )

    @given(epoch=st.integers(min_value=0, max_value=10_000))
    @settings(max_examples=500)
    def test_hypothesis_epoch_roundtrip_identity(self, epoch: int) -> None:
        """Hypothesis: slot_to_epoch(epoch_to_first_slot(E)) == E for all E.

        The first slot of any epoch must map back to that exact epoch.
        """
        first_slot = epoch_to_first_slot_hfc(epoch, MAINNET_HFC_CONFIG)
        recovered = slot_to_epoch_hfc(first_slot, MAINNET_HFC_CONFIG)
        assert recovered == epoch, (
            f"Epoch roundtrip failed: epoch={epoch}, first_slot={first_slot}, "
            f"recovered={recovered}"
        )

    @given(slot=st.integers(min_value=0, max_value=500_000_000))
    @settings(max_examples=300)
    def test_hypothesis_next_epoch_boundary(self, slot: int) -> None:
        """For any slot S in epoch E, the first slot of epoch E+1 is > S.

        This ensures epochs don't overlap.
        """
        epoch = slot_to_epoch_hfc(slot, MAINNET_HFC_CONFIG)
        next_epoch_first_slot = epoch_to_first_slot_hfc(epoch + 1, MAINNET_HFC_CONFIG)
        assert next_epoch_first_slot > slot, (
            f"Epoch overlap: slot={slot}, epoch={epoch}, "
            f"next_epoch_first_slot={next_epoch_first_slot}"
        )


# ---------------------------------------------------------------------------
# Test 5: HFC Skeleton / era structure (Haskell parity gap)
# ---------------------------------------------------------------------------


class TestHFCSkeleton:
    """Test the HFC skeleton/era structure matches the Cardano spec.

    The HFC "skeleton" is the ordered list of eras with their parameters
    and transition points. This test verifies the structural integrity
    of the era timeline as defined in the HFC configuration.

    Haskell reference:
        Ouroboros.Consensus.HardFork.History.Summary
        The Summary type is the "skeleton" of the hard fork history:
        a non-empty list of EraSummary values with era parameters.
    """

    def test_hfc_skeleton(self) -> None:
        """HFC skeleton has correct era count and ordering for mainnet.

        Verifies:
        1. All 7 eras are present in the mainnet config
        2. Era start epochs are strictly ascending
        3. Era start slots are strictly ascending
        4. Each era has valid parameters (positive epoch_length, slot_length)
        5. The HFCState can advance through all eras
        """
        config = MAINNET_HFC_CONFIG

        # 1. All 7 eras present.
        assert len(config.era_transitions) == 7
        for era in Era:
            assert era in config.era_transitions, f"Missing era: {era.name}"

        # 2. Era start epochs are strictly ascending.
        sorted_eras = sorted(config.era_transitions.items(), key=lambda x: x[0].value)
        for i in range(len(sorted_eras) - 1):
            era_a, epoch_a = sorted_eras[i]
            era_b, epoch_b = sorted_eras[i + 1]
            assert (
                epoch_b > epoch_a
            ), f"Epochs not ascending: {era_a.name}={epoch_a}, {era_b.name}={epoch_b}"

        # 3. Era start slots are strictly ascending.
        era_slots = _era_start_slots(config)
        for i in range(len(era_slots) - 1):
            era_a, slot_a = era_slots[i]
            era_b, slot_b = era_slots[i + 1]
            assert (
                slot_b > slot_a
            ), f"Slots not ascending: {era_a.name}={slot_a}, {era_b.name}={slot_b}"

        # 4. All era params are valid.
        for era in Era:
            params = config.era_params.get(era, DEFAULT_ERA_PARAMS[era])
            assert params.epoch_length > 0, f"{era.name} epoch_length not positive"
            assert params.slot_length > 0, f"{era.name} slot_length not positive"

        # 5. HFCState can advance through all era boundaries.
        state = HFCState(config=config)
        era_slot_dict = dict(era_slots)
        for era in Era:
            start_slot = era_slot_dict[era]
            result_era = state.advance_to_slot(start_slot)
            assert (
                result_era == era
            ), f"At slot {start_slot}: expected {era.name}, got {result_era.name}"
            assert state.current_era == era
            assert state.tip_slot == start_slot

    def test_hfc_skeleton_byron_epoch_length(self) -> None:
        """Byron era uses 21600-slot epochs (10-second blocks, 20s slot)."""
        params = DEFAULT_ERA_PARAMS[Era.BYRON]
        assert params.epoch_length == BYRON_EPOCH_LENGTH
        assert params.slot_length == 20.0

    def test_hfc_skeleton_shelley_plus_epoch_length(self) -> None:
        """All post-Byron eras use 432000-slot epochs (1s slots)."""
        for era in [Era.SHELLEY, Era.ALLEGRA, Era.MARY, Era.ALONZO, Era.BABBAGE, Era.CONWAY]:
            params = DEFAULT_ERA_PARAMS[era]
            assert params.epoch_length == SHELLEY_EPOCH_LENGTH
            assert params.slot_length == 1.0

    def test_hfc_skeleton_era_boundary_detection(self) -> None:
        """HFCState.is_era_boundary returns True for era start slots."""
        state = HFCState(config=MAINNET_HFC_CONFIG)
        era_slots = _era_start_slots(MAINNET_HFC_CONFIG)

        for era, start_slot in era_slots:
            assert state.is_era_boundary(
                start_slot
            ), f"Slot {start_slot} should be an era boundary for {era.name}"
            # One slot before should NOT be a boundary (except slot 0).
            if start_slot > 0:
                assert not state.is_era_boundary(start_slot - 1)
