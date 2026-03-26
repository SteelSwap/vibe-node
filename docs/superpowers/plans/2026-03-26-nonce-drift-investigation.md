# Epoch Nonce Drift Investigation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find and fix the epoch nonce drift that causes VRFKeyBadProof rejection of our forged blocks starting at epoch 13 on the devnet.

**Architecture:** Add full nonce logging, capture Haskell node's expected nonce from rejection errors, compare byte-for-byte, trace the divergence point back to the specific epoch boundary or VRF accumulation step that differs.

**Tech Stack:** Python, docker-compose devnet, Haskell cardano-node logs

---

## Evidence So Far

- Haskell node rejects our blocks with `VRFKeyBadProof` starting at slot 1301 (epoch 13)
- Nonce first 16 hex chars MATCH between our node and Haskell node
- But we only log 16 of 64 hex chars -- the remaining bytes may differ
- VRF proofs are valid for epochs 0-12, invalid from epoch 13 onward
- Our nonce is derived from VRF outputs accumulated during block processing
- Block processing is sequential (single-peer for producers), no out-of-order issues
- Duplicate "Epoch transition 12 -> 13" logged -- suggests on_epoch_boundary called twice

## File Structure

- **Modify:** `packages/vibe-cardano/src/vibe/cardano/node/kernel.py` -- full nonce logging
- **Modify:** `packages/vibe-cardano/src/vibe/cardano/consensus/nonce.py` -- debug nonce evolution
- **Create:** `scripts/compare-devnet-nonces.py` -- extract and compare nonces from both node logs

---

### Task 1: Add full nonce logging and reproduce

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py`

- [ ] **Step 1: Log full 32-byte nonce on epoch transitions**

In `kernel.py`, change line 305 from:
```python
new_nonce_bytes.hex()[:16],
```
to:
```python
new_nonce_bytes.hex(),
```

Also add full logging for the candidate_nonce and evolving_nonce at each epoch boundary:
```python
logger.info(
    "Epoch transition %d -> %d nonce=%s candidate=%s lab=%s",
    old_epoch, new_epoch,
    new_nonce_bytes.hex(),
    self._candidate_nonce.hex() if isinstance(self._candidate_nonce, bytes) else str(self._candidate_nonce),
    self._last_epoch_block_nonce.hex()[:16] if isinstance(self._last_epoch_block_nonce, bytes) else "None",
)
```

- [ ] **Step 2: Log VRF output accumulation**

In `kernel.py` `on_block_adopted`, add logging around the nonce accumulation:
```python
logger.debug(
    "Nonce accumulate: slot=%d vrf=%s evolving=%s",
    slot,
    vrf_output.hex()[:16] if vrf_output else "None",
    self._evolving_nonce.hex()[:16] if isinstance(self._evolving_nonce, bytes) else "?",
)
```

- [ ] **Step 3: Fix duplicate epoch transition**

Check why "Epoch transition 12 -> 13" is logged twice. In `on_epoch_boundary`:
```python
if new_epoch <= self._current_epoch:
    return
```
This should prevent duplicates. The duplicate suggests `on_block_adopted` is calling `on_epoch_boundary` twice for the same epoch. Add a guard log:
```python
if new_epoch <= self._current_epoch:
    logger.warning("Duplicate epoch transition ignored: %d -> %d (current=%d)",
                   self._current_epoch, new_epoch, self._current_epoch)
    return
```

- [ ] **Step 4: Rebuild devnet, run 5 minutes, capture logs**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml down -v
docker compose -f infra/devnet/docker-compose.devnet.yml up -d --build
sleep 300
docker compose -f infra/devnet/docker-compose.devnet.yml logs vibe-node > /tmp/vibe-nonce.log
docker compose -f infra/devnet/docker-compose.devnet.yml logs haskell-node-1 > /tmp/haskell-nonce.log
```

- [ ] **Step 5: Compare full nonces**

Extract full nonces from both logs and compare:
```bash
# Our nonces
grep "Epoch transition" /tmp/vibe-nonce.log

# Haskell expected nonces (from VRFKeyBadProof errors)
grep "VRFKeyBadProof" /tmp/haskell-nonce.log | grep -oP 'Nonce "\K[0-9a-f]+'
```

If the full 32-byte nonces match but VRF still fails, the issue is in VRF input encoding.
If the full nonces diverge, the divergence point reveals which epoch's VRF accumulation differs.

---

### Task 2: Trace nonce divergence to root cause

This task depends on Task 1 findings.

**If nonces diverge at epoch N:**
- Compare VRF outputs accumulated during epoch N-1
- Check if we're accumulating the correct VRF output bytes (64-byte vs 32-byte)
- Check the stability window calculation: `3*k/f` with k=10, f=0.1 = 300 slots (3 epochs). Are blocks within the stability window correctly excluded from nonce accumulation?
- Check `_last_epoch_block_nonce` (lab_nonce) -- is it the hash of the LAST block of the previous epoch?

**If nonces match but VRF proof fails:**
- The VRF input alpha construction differs
- Compare byte-by-byte: `blake2b_256(slot_be64 ++ epoch_nonce)`
- Check if Haskell uses a different domain separator or padding
- Verify our `_mk_input_vrf` matches Haskell's `mkInputVRF` exactly

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/consensus/nonce.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/forge/leader.py`

- [ ] **Step 1: Based on Task 1 findings, identify the divergence type**
- [ ] **Step 2: Add targeted logging at the divergence point**
- [ ] **Step 3: Cross-reference with Haskell implementation**
- [ ] **Step 4: Implement fix**
- [ ] **Step 5: Verify fix on devnet -- target 30%+ forge rate over 10 minutes**
- [ ] **Step 6: Commit**

---

### Task 3: Verify the stability window calculation

The devnet has k=10, f=0.1, epoch_length=100.

Stability window = 3 * k / f = 3 * 10 / 0.1 = 300 slots = 3 epochs.

This means VRF outputs are accumulated for blocks in the first `epoch_length - stability_window` = `100 - 300` = negative?!

**This is likely the bug.** When stability_window > epoch_length, the condition `slot + stab_window < first_slot_next_epoch` is NEVER true, so `candidate_nonce` is NEVER updated from `evolving_nonce`. The epoch nonce computation uses a stale `candidate_nonce`.

On mainnet (k=2160, f=0.05, epoch=432000), stability_window = 129600 < 432000, so it works. On devnet (k=10, f=0.1, epoch=100), stability_window = 300 > 100, so it NEVER updates.

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py`

- [ ] **Step 1: Verify the hypothesis**

```python
# In kernel.py, check on_block_adopted around line 273:
stab_window = stability_window(self._security_param, self._active_slot_coeff)
# With k=10, f=0.1: stab_window = 3 * 10 / 0.1 = 300
# epoch_length = 100, so first_slot_next_epoch = epoch_start + 100
# slot + 300 < epoch_start + 100 is NEVER true
# => candidate_nonce is NEVER set to evolving_nonce
# => epoch nonce uses the initial candidate_nonce (all zeros or genesis)
```

- [ ] **Step 2: Fix the stability window for short epochs**

The Haskell node handles this by capping the stability window at the epoch length. When stab_window >= epoch_length, ALL blocks contribute to the nonce (candidate = evolving at every block).

```python
# In on_block_adopted, replace:
if slot + stab_window < first_slot_next_epoch:
    self._candidate_nonce = self._evolving_nonce

# With:
if stab_window >= self._epoch_length or slot + stab_window < first_slot_next_epoch:
    self._candidate_nonce = self._evolving_nonce
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/ -x -q -k "nonce or kernel or forge" --timeout=60
```

- [ ] **Step 4: Rebuild devnet and verify 30%+ forge rate**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml down -v
docker compose -f infra/devnet/docker-compose.devnet.yml up -d --build
# Wait 10 minutes, check forge rates
```

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/kernel.py
git commit -m "fix: cap stability window at epoch length for short-epoch devnets

Prompt: stability_window (3*k/f) = 300 on devnet (k=10, f=0.1) exceeds
epoch_length (100), causing candidate_nonce to never update. The epoch
nonce drifts because it's computed from a stale candidate. Haskell caps
the stability window at epoch length so all blocks contribute when the
window exceeds the epoch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```
