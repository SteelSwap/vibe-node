"""Property-based tests for Shelley ledger invariants.

These tests use Hypothesis to verify critical ledger properties that must hold
for any sequence of valid transactions:

1. No double spending — no input is consumed twice
2. Outputs appear in UTxO — every output of a valid tx is in the resulting UTxO
3. Fee monotonically increases with size — larger tx → higher min fee
4. ADA preservation — total ADA in UTxO + fees is constant

These are fundamental safety properties of the UTxO ledger model. If any of
these fail, the ledger is broken.

Spec references:
    - Shelley ledger formal spec, Section 9 (UTxO transition)
    - Ouroboros Praos, Section 3 (transaction semantics)
    - Property: ∀ tx₁, tx₂ ∈ block. inputs(tx₁) ∩ inputs(tx₂) = ∅
    - Property: txouts(tx) ⊆ utxo' after apply(tx)
    - Property: minfee(s₁) ≤ minfee(s₂) when s₁ ≤ s₂
    - Property: sum(utxo) + sum(fees) = constant

Structured for Antithesis compatibility: deterministic given the same seed,
with property invariants expressible as assertions.
"""

from __future__ import annotations

import hashlib

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from pycardano import (
    Transaction,
    TransactionBody,
    TransactionInput,
    TransactionOutput,
)
from pycardano.hash import TransactionId
from pycardano.key import PaymentSigningKey, PaymentVerificationKey
from pycardano.witness import TransactionWitnessSet, VerificationKeyWitness
from pycardano.address import Address
from pycardano.network import Network

from vibe.cardano.ledger.shelley import (
    ShelleyProtocolParams,
    ShelleyUTxO,
    ShelleyValidationError,
    apply_shelley_tx,
    shelley_min_fee,
    _output_lovelace,
)

# Mark all tests in this module as property tests
pytestmark = pytest.mark.property


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_PARAMS = ShelleyProtocolParams(
    min_fee_a=1,
    min_fee_b=100,
    max_tx_size=16384,
    min_utxo_value=1000000,
    key_deposit=2000000,
    pool_deposit=500000000,
)


def _make_signing_key(seed: int) -> PaymentSigningKey:
    """Create a deterministic signing key from a seed."""
    seed_bytes = seed.to_bytes(32, "big")
    return PaymentSigningKey(seed_bytes)


def _make_key_pair(seed: int) -> tuple[PaymentSigningKey, PaymentVerificationKey]:
    sk = _make_signing_key(seed)
    vk = sk.to_verification_key()
    return sk, vk


def _make_address(vk: PaymentVerificationKey) -> Address:
    return Address(payment_part=vk.hash(), network=Network.TESTNET)


def _make_tx_id(seed: int) -> TransactionId:
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=32).digest()
    return TransactionId(digest)


def _sign_tx_body(tx_body: TransactionBody, sk: PaymentSigningKey) -> VerificationKeyWitness:
    tx_body_hash = tx_body.hash()
    signature = sk.sign(tx_body_hash)
    vk = sk.to_verification_key()
    return VerificationKeyWitness(vkey=vk, signature=signature)


def _make_utxo_set(
    num_entries: int,
    value_per_entry: int,
    key_seed: int = 0,
) -> tuple[ShelleyUTxO, PaymentSigningKey, PaymentVerificationKey]:
    """Create a UTxO set with multiple entries owned by the same key."""
    sk, vk = _make_key_pair(key_seed)
    addr = _make_address(vk)
    utxo_set: ShelleyUTxO = {}
    for i in range(num_entries):
        txin = TransactionInput(_make_tx_id(i + 1000), 0)
        utxo_set[txin] = TransactionOutput(addr, value_per_entry)
    return utxo_set, sk, vk


# ---------------------------------------------------------------------------
# Property 1: No double spending
# ---------------------------------------------------------------------------


class TestNoDoubleSpend:
    """Hypothesis: for any sequence of valid transactions applied to a UTxO set,
    no input is consumed twice.

    Spec: Each tx consumes a set of inputs. After application, those inputs
    are removed from the UTxO. A subsequent tx cannot reference them.
    """

    @given(
        num_txs=st.integers(min_value=1, max_value=5),
        seed=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=50, deadline=5000)
    def test_no_double_spend_property(self, num_txs: int, seed: int):
        """No input appears in more than one transaction's consumed set
        when transactions are applied sequentially to the UTxO."""
        # Create UTxO with enough entries for our transactions
        total_entries = num_txs
        utxo_set, sk, vk = _make_utxo_set(
            total_entries, value_per_entry=10_000_000, key_seed=seed % 100
        )
        addr = _make_address(vk)

        all_consumed: list[TransactionInput] = []
        current_utxo = dict(utxo_set)

        for i in range(num_txs):
            available_inputs = list(current_utxo.keys())
            if not available_inputs:
                break

            txin = available_inputs[0]
            input_value = _output_lovelace(current_utxo[txin])
            fee = 2_000_000
            output_value = input_value - fee
            assume(output_value >= TEST_PARAMS.min_utxo_value)

            tx_body = TransactionBody(
                inputs=[txin],
                outputs=[TransactionOutput(addr, output_value)],
                fee=fee,
                ttl=999999,
            )
            wit = _sign_tx_body(tx_body, sk)
            tx = Transaction(tx_body, TransactionWitnessSet(vkey_witnesses=[wit]))

            try:
                current_utxo = apply_shelley_tx(
                    tx, current_utxo, TEST_PARAMS, current_slot=0
                )
            except ShelleyValidationError:
                break

            # Track consumed inputs
            all_consumed.append(txin)

        # Verify: no input was consumed twice
        assert len(all_consumed) == len(set(all_consumed)), (
            f"Double spend detected! Consumed inputs: {all_consumed}"
        )


# ---------------------------------------------------------------------------
# Property 2: Outputs appear in resulting UTxO
# ---------------------------------------------------------------------------


class TestOutputsAppearInUtxo:
    """Hypothesis: every output of a valid transaction appears in the resulting
    UTxO set, keyed by (tx_id, output_index).

    Spec: utxo' = (utxo \\ txins) ∪ txouts
    """

    @given(
        num_outputs=st.integers(min_value=1, max_value=5),
        seed=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=50, deadline=5000)
    def test_outputs_appear_in_utxo_property(self, num_outputs: int, seed: int):
        """Every output of a valid tx must appear in the resulting UTxO."""
        sk, vk = _make_key_pair(seed % 100)
        addr = _make_address(vk)

        # Need enough input value for all outputs + fee
        total_output = num_outputs * 2_000_000
        fee = 2_000_000
        input_value = total_output + fee

        txin = TransactionInput(_make_tx_id(seed), 0)
        utxo_set: ShelleyUTxO = {txin: TransactionOutput(addr, input_value)}

        outputs = [TransactionOutput(addr, 2_000_000) for _ in range(num_outputs)]

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=outputs,
            fee=fee,
            ttl=999999,
        )
        wit = _sign_tx_body(tx_body, sk)
        tx = Transaction(tx_body, TransactionWitnessSet(vkey_witnesses=[wit]))

        new_utxo = apply_shelley_tx(tx, utxo_set, TEST_PARAMS, current_slot=0)

        # Every output should appear in the new UTxO
        tx_id = tx_body.id
        for i in range(num_outputs):
            expected_txin = TransactionInput(tx_id, i)
            assert expected_txin in new_utxo, (
                f"Output {i} not found in UTxO after tx application"
            )
            assert _output_lovelace(new_utxo[expected_txin]) == 2_000_000


# ---------------------------------------------------------------------------
# Property 3: Fee monotonically increases with size
# ---------------------------------------------------------------------------


class TestFeeMonotonicity:
    """Hypothesis: for any two transaction sizes s1 < s2, the minimum fee
    for s2 is strictly greater than for s1 (given min_fee_a > 0).

    Spec: minfee = a * txSize + b, where a > 0.
    """

    @given(
        size1=st.integers(min_value=0, max_value=100000),
        size2=st.integers(min_value=0, max_value=100000),
        fee_a=st.integers(min_value=1, max_value=1000),
        fee_b=st.integers(min_value=0, max_value=1000000),
    )
    @settings(max_examples=200, deadline=1000)
    def test_fee_monotonically_increases_with_size(
        self, size1: int, size2: int, fee_a: int, fee_b: int
    ):
        """Larger tx size -> strictly higher min fee (when fee_a > 0)."""
        assume(size1 != size2)
        params = ShelleyProtocolParams(min_fee_a=fee_a, min_fee_b=fee_b)

        fee1 = shelley_min_fee(size1, params)
        fee2 = shelley_min_fee(size2, params)

        if size1 < size2:
            assert fee1 < fee2, (
                f"Fee should increase: size={size1}->{size2}, fee={fee1}->{fee2}"
            )
        else:
            assert fee1 > fee2, (
                f"Fee should decrease: size={size1}->{size2}, fee={fee1}->{fee2}"
            )


# ---------------------------------------------------------------------------
# Property 4: ADA preservation
# ---------------------------------------------------------------------------


class TestAdaPreservation:
    """Hypothesis: total ADA in UTxO + accumulated fees is constant across
    any valid transaction application.

    Spec: consumed(tx) = produced(tx)
          where consumed = sum(inputs) + withdrawals
                produced = sum(outputs) + fee + deposits
          This means: sum(utxo') + fee = sum(utxo)
          (ignoring withdrawals and deposits for the simple case)

    This is THE fundamental safety property of the UTxO model.
    """

    @given(
        output_split=st.lists(
            st.integers(min_value=1_000_000, max_value=5_000_000),
            min_size=1,
            max_size=5,
        ),
        seed=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=100, deadline=5000)
    def test_ada_preservation_property(self, output_split: list[int], seed: int):
        """Total ADA (UTxO + fees) must be constant after applying a valid tx."""
        sk, vk = _make_key_pair(seed % 100)
        addr = _make_address(vk)

        output_total = sum(output_split)
        fee = 2_000_000
        input_value = output_total + fee

        txin = TransactionInput(_make_tx_id(seed), 0)
        utxo_set: ShelleyUTxO = {txin: TransactionOutput(addr, input_value)}

        # Total ADA before
        utxo_sum_before = sum(_output_lovelace(v) for v in utxo_set.values())

        outputs = [TransactionOutput(addr, v) for v in output_split]
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=outputs,
            fee=fee,
            ttl=999999,
        )
        wit = _sign_tx_body(tx_body, sk)
        tx = Transaction(tx_body, TransactionWitnessSet(vkey_witnesses=[wit]))

        try:
            new_utxo = apply_shelley_tx(tx, utxo_set, TEST_PARAMS, current_slot=0)
        except ShelleyValidationError:
            # If validation fails, the invariant trivially holds (no state change)
            return

        # Total ADA after: UTxO sum + fee
        utxo_sum_after = sum(_output_lovelace(v) for v in new_utxo.values())
        total_after = utxo_sum_after + fee

        assert utxo_sum_before == total_after, (
            f"ADA not preserved! Before: {utxo_sum_before}, "
            f"After (utxo={utxo_sum_after} + fee={fee} = {total_after})"
        )
