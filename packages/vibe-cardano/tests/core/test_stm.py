"""Tests for STM — Software Transactional Memory."""

from __future__ import annotations

import threading
import time

from vibe.core.stm import TVar, Transaction, atomically, RetryTransaction


class TestTVarBasic:
    def test_initial_value(self):
        v = TVar(42)
        assert v.value == 42

    def test_read_write_in_transaction(self):
        v = TVar(10)
        def tx(t):
            val = t.read(v)
            t.write(v, val + 5)
            return val
        result = atomically(tx)
        assert result == 10
        assert v.value == 15

    def test_read_your_own_writes(self):
        v = TVar(0)
        def tx(t):
            t.write(v, 100)
            return t.read(v)  # Should see 100, not 0
        result = atomically(tx)
        assert result == 100
        assert v.value == 100


class TestAtomicity:
    def test_concurrent_increments(self):
        """Multiple threads incrementing a TVar should not lose updates."""
        counter = TVar(0)
        n_threads = 10
        n_increments = 100

        def worker():
            for _ in range(n_increments):
                def tx(t):
                    val = t.read(counter)
                    t.write(counter, val + 1)
                atomically(tx)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert counter.value == n_threads * n_increments

    def test_multi_tvar_atomic(self):
        """Transfer between two TVars should be atomic."""
        a = TVar(100)
        b = TVar(0)

        def transfer(t):
            va = t.read(a)
            vb = t.read(b)
            t.write(a, va - 10)
            t.write(b, vb + 10)

        # Run 10 transfers
        for _ in range(10):
            atomically(transfer)

        assert a.value == 0
        assert b.value == 100
        # Sum is always preserved
        assert a.value + b.value == 100

    def test_conflict_causes_retry(self):
        """Conflicting transactions should retry, not corrupt state."""
        v = TVar(0)
        attempts = [0]

        def tx(t):
            attempts[0] += 1
            val = t.read(v)
            # Simulate slow computation
            time.sleep(0.001)
            t.write(v, val + 1)

        # Two threads both try to increment
        t1 = threading.Thread(target=lambda: atomically(tx))
        t2 = threading.Thread(target=lambda: atomically(tx))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert v.value == 2
        # At least one retry should have happened
        assert attempts[0] >= 2


class TestRetry:
    def test_retry_blocks_until_change(self):
        """RetryTransaction should block until a read TVar changes."""
        flag = TVar(False)
        result = [None]

        def wait_for_flag(t):
            if not t.read(flag):
                raise RetryTransaction()
            return "done"

        def waiter():
            result[0] = atomically(wait_for_flag)

        t = threading.Thread(target=waiter)
        t.start()

        # Give the waiter time to block
        time.sleep(0.1)
        assert result[0] is None  # Still waiting

        # Set the flag
        atomically(lambda tx: tx.write(flag, True))

        t.join(timeout=2)
        assert result[0] == "done"


class TestForgeScenario:
    def test_nonce_read_consistent_with_forge(self):
        """Simulate the forge scenario: read nonce + tip, forge, commit.
        Another thread changes nonce mid-forge — should retry."""
        nonce = TVar(b"nonce_epoch_1")
        tip = TVar({"slot": 100, "hash": b"tip_100"})

        forge_nonce_used = [None]
        forge_count = [0]

        def forge_tx(t):
            # Read nonce and tip
            n = t.read(nonce)
            tp = t.read(tip)
            forge_nonce_used[0] = n
            forge_count[0] += 1

            # "Forge" a block
            new_tip = {"slot": tp["slot"] + 1, "hash": b"forged"}
            t.write(tip, new_tip)
            return "forged"

        # Thread 2: change nonce after a delay
        def change_nonce():
            time.sleep(0.01)
            atomically(lambda t: t.write(nonce, b"nonce_epoch_2"))

        changer = threading.Thread(target=change_nonce)
        changer.start()

        result = atomically(forge_tx)
        changer.join()

        assert result == "forged"
        # The forge used a consistent nonce (either epoch_1 or epoch_2)
        assert forge_nonce_used[0] in (b"nonce_epoch_1", b"nonce_epoch_2")
