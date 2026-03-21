# Full Node Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire all existing subsystems together so vibe-node achieves full Cardano node feature parity — forged blocks accepted by Haskell nodes, received blocks validated through ledger rules, N2C clients served.

**Architecture:** All individual subsystems (KES/VRF crypto, ledger rules Byron-Conway, storage, miniprotocols, Praos consensus) are implemented and tested. This plan is purely integration: deserialize real keys, connect the sync pipeline to validation and storage, wire N2C servers, and fix the epoch nonce. No new algorithms — just plumbing.

**Tech Stack:** Python 3.14, asyncio, cbor2, cryptography (Ed25519), PyArrow (LedgerDB), pycardano

---

## File Structure

### Files to Create
- `packages/vibe-cardano/src/vibe/cardano/crypto/kes_serialization.py` — KES key deserialization from cardano-cli 608-byte format
- `packages/vibe-cardano/tests/crypto/test_kes_serialization.py` — Tests for KES deserialization

### Files to Modify
- `packages/vibe-cardano/src/vibe/cardano/crypto/kes.py` — Add seed-based deterministic keygen
- `packages/vibe-cardano/src/vibe/cardano/node/run.py` — Main integration point: sync pipeline, validation, N2C servers
- `packages/vibe-cardano/src/vibe/cardano/node/kernel.py` — Add epoch nonce tracking, received block storage
- `packages/vibe-cardano/src/vibe/cardano/network/blockfetch_protocol.py` — Persistent block-fetch client mode
- `packages/vibe-cardano/src/vibe/cardano/node/config.py` — Add genesis_hash field for epoch nonce

### Test Files
- `packages/vibe-cardano/tests/crypto/test_kes_serialization.py`
- `packages/vibe-cardano/tests/node/test_node.py` — Update existing tests
- `packages/vibe-cardano/tests/node/test_sync_pipeline.py` — New integration tests

---

## Task 1: KES Key Deserialization

The forge loop currently generates random KES keys, so forged blocks have KES signatures that don't match the opcert registered in genesis. We need to deserialize the 608-byte KES secret key from cardano-cli's `.skey` file into our `KesSecretKey` tree.

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/crypto/kes_serialization.py`
- Create: `packages/vibe-cardano/tests/crypto/test_kes_serialization.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/crypto/kes.py` (add `kes_keygen_from_seed`)
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py:720-740` (use deserialized key)

### Background

The Haskell `Sum6KES Ed25519DSIGN` serialization format for the 608-byte key:

For `SumKES h d`, the serialized signing key is:
```
rawSerialise(sk) = rawSerialise(active_sub_sk) || seed_for_other_half || left_vk || right_vk
```

At depth 0 (Ed25519): `sk_seed(32 bytes) || vk(32 bytes)` = 64 bytes

Size formula: `size(0) = 64`, `size(d) = size(d-1) + size(d-1) + 32 + 32`
But that gives size(6) = 4160, not 608. The actual Haskell format stores only the **active path**, not the full tree:

```
size(0) = 32 (just the seed)
size(d) = size(d-1) + 32 + 32 + 32 = size(d-1) + 96
```
`size(0)=32, size(1)=128, size(2)=224, size(3)=320, size(4)=416, size(5)=512, size(6)=608`

So 608 bytes = the active signing path (depth 0 seed) + at each level: the other half's seed(32) + left_vk(32) + right_vk(32).

- [ ] **Step 1: Write the failing test for KES deserialization**

```python
# packages/vibe-cardano/tests/crypto/test_kes_serialization.py
import pytest
from vibe.cardano.crypto.kes import kes_keygen, kes_derive_vk, kes_sign, kes_verify, CARDANO_KES_DEPTH
from vibe.cardano.crypto.kes_serialization import serialize_kes_sk, deserialize_kes_sk


class TestKESSerialization:
    def test_roundtrip_depth_0(self):
        """Serialize then deserialize a depth-0 KES key."""
        sk = kes_keygen(0)
        raw = serialize_kes_sk(sk)
        assert len(raw) == 32  # Just the Ed25519 seed
        sk2 = deserialize_kes_sk(raw, depth=0)
        assert kes_derive_vk(sk2) == kes_derive_vk(sk)

    def test_roundtrip_depth_6(self):
        """Serialize then deserialize a depth-6 KES key (Cardano mainnet)."""
        sk = kes_keygen(CARDANO_KES_DEPTH)
        raw = serialize_kes_sk(sk)
        assert len(raw) == 608
        sk2 = deserialize_kes_sk(raw, depth=CARDANO_KES_DEPTH)
        # Same VK means same signing capability
        assert kes_derive_vk(sk2) == kes_derive_vk(sk)

    def test_deserialized_key_signs_correctly(self):
        """A deserialized key produces the same signature."""
        sk = kes_keygen(CARDANO_KES_DEPTH)
        raw = serialize_kes_sk(sk)
        sk2 = deserialize_kes_sk(raw, depth=CARDANO_KES_DEPTH)
        msg = b"test message"
        sig = kes_sign(sk2, 0, msg)
        vk = kes_derive_vk(sk)
        assert kes_verify(vk, CARDANO_KES_DEPTH, 0, sig, msg)

    def test_cardano_cli_key_loads(self):
        """Load a real cardano-cli KES skey file (if available)."""
        import json
        from pathlib import Path
        skey_path = Path("infra/devnet/keys/pool3/kes.skey")
        if not skey_path.exists():
            pytest.skip("No devnet keys generated")
        with open(skey_path) as f:
            data = json.load(f)
        import cbor2
        raw = cbor2.loads(bytes.fromhex(data["cborHex"]))
        assert isinstance(raw, bytes)
        assert len(raw) == 608
        sk = deserialize_kes_sk(raw, depth=CARDANO_KES_DEPTH)
        vk = kes_derive_vk(sk)
        assert len(vk) == 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/vibe-cardano/tests/crypto/test_kes_serialization.py -v`
Expected: ImportError for `serialize_kes_sk`, `deserialize_kes_sk`

- [ ] **Step 3: Implement KES serialization/deserialization**

```python
# packages/vibe-cardano/src/vibe/cardano/crypto/kes_serialization.py
"""KES key serialization — compatible with cardano-cli .skey format.

The Haskell Sum6KES serialization stores the active signing path:
  - At each depth d > 0: active_sub_key || inactive_seed(32) || left_vk(32) || right_vk(32)
  - At depth 0 (leaf): ed25519_seed(32)

Total size for depth 6: 32 + 6*96 = 608 bytes.

Haskell ref:
    Crypto.rawSerialiseSignKeyKES / rawDeserialiseSignKeyKES
    for SumKES composition over Ed25519DSIGN
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .kes import KesSecretKey, kes_derive_vk, kes_vk_hash, _ed25519_vk_bytes


def _serialized_size(depth: int) -> int:
    """Compute serialized size for a KES key at given depth."""
    if depth == 0:
        return 32  # Ed25519 seed only
    return _serialized_size(depth - 1) + 96  # sub_key + seed(32) + left_vk(32) + right_vk(32)


def serialize_kes_sk(sk: KesSecretKey) -> bytes:
    """Serialize a KesSecretKey to raw bytes (Haskell-compatible format)."""
    if sk.depth == 0:
        assert sk.ed25519_sk is not None
        return sk.ed25519_sk.private_bytes_raw()

    assert sk.left is not None and sk.right is not None
    assert sk.left_vk is not None and sk.right_vk is not None

    # Active subtree (left at period 0) + right subtree seed + VKs
    left_bytes = serialize_kes_sk(sk.left)
    right_bytes = serialize_kes_sk(sk.right)
    # For the inactive half, we store its serialized form (acts as seed)
    return left_bytes + right_bytes + sk.left_vk + sk.right_vk


def deserialize_kes_sk(data: bytes, depth: int) -> KesSecretKey:
    """Deserialize raw bytes into a KesSecretKey tree.

    Args:
        data: Raw serialized bytes (608 bytes for depth 6).
        depth: Tree depth (6 for Cardano mainnet).

    Returns:
        A KesSecretKey ready for signing.
    """
    expected = _serialized_size(depth)
    if len(data) != expected:
        raise ValueError(
            f"KES key at depth {depth} should be {expected} bytes, got {len(data)}"
        )

    if depth == 0:
        sk = Ed25519PrivateKey.from_private_bytes(data[:32])
        vk = _ed25519_vk_bytes(sk)
        return KesSecretKey(depth=0, ed25519_sk=sk, ed25519_vk=vk)

    sub_size = _serialized_size(depth - 1)
    left_data = data[:sub_size]
    right_data = data[sub_size : sub_size + sub_size]
    left_vk = data[sub_size + sub_size : sub_size + sub_size + 32]
    right_vk = data[sub_size + sub_size + 32 : sub_size + sub_size + 64]

    left = deserialize_kes_sk(left_data, depth - 1)
    right = deserialize_kes_sk(right_data, depth - 1)

    return KesSecretKey(
        depth=depth,
        left=left,
        right=right,
        left_vk=left_vk,
        right_vk=right_vk,
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/vibe-cardano/tests/crypto/test_kes_serialization.py -v`
Expected: All PASS (roundtrip tests verify VK equality and signing capability)

- [ ] **Step 5: Wire deserialized KES into forge loop**

Modify `packages/vibe-cardano/src/vibe/cardano/node/run.py` — replace the random KES keygen block (~lines 722-737) with:

```python
    # --- Initialise forge credentials ---
    # Load KES key from pool_keys if available (deserialized from cardano-cli skey),
    # otherwise generate fresh (for testing).
    if pool_keys.kes_sk:
        from vibe.cardano.crypto.kes_serialization import deserialize_kes_sk
        kes_sk = deserialize_kes_sk(pool_keys.kes_sk, CARDANO_KES_DEPTH)
        kes_vk = kes_derive_vk(kes_sk)
        logger.info("Loaded KES key from pool configuration")
    else:
        kes_sk = kes_keygen(CARDANO_KES_DEPTH)
        kes_vk = kes_derive_vk(kes_sk)
        logger.info("Generated fresh KES key (no skey provided)")

    # Load opcert from pool_keys if available, otherwise sign a fresh one.
    if pool_keys.ocert:
        import cbor2 as _cbor2
        ocert_data = _cbor2.loads(pool_keys.ocert)
        # opcert = [[kes_vk, cert_count, kes_period, cold_sig], vrf_keyhash]
        inner = ocert_data[0]
        ocert = OperationalCert(
            kes_vk=bytes(inner[0]),
            cert_count=inner[1],
            kes_period_start=inner[2],
            cold_sig=bytes(inner[3]),
        )
        logger.info("Loaded operational certificate")
    elif pool_keys.cold_sk:
        # Generate fresh opcert
        ocert_payload = ocert_signed_payload(kes_vk, cert_count=0, kes_period_start=0)
        cold_sk_ed = Ed25519PrivateKey.from_private_bytes(pool_keys.cold_sk)
        cold_sig = cold_sk_ed.sign(ocert_payload)
        ocert = OperationalCert(
            kes_vk=kes_vk, cert_count=0, kes_period_start=0, cold_sig=cold_sig,
        )
        logger.info("Generated fresh operational certificate")
    else:
        logger.error("No opcert or cold signing key — cannot forge blocks")
        return
```

- [ ] **Step 6: Update CLI and __main__.py to load KES skey and opcert again**

Re-add `kes_sk` and `ocert` loading in `_load_pool_keys()` and `__main__.py`.

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest packages/vibe-cardano/tests/ tests/ -q --timeout=30 --ignore=tests/conformance/test_uplc_conformance.py`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/crypto/kes_serialization.py \
       packages/vibe-cardano/tests/crypto/test_kes_serialization.py \
       packages/vibe-cardano/src/vibe/cardano/node/run.py \
       src/vibe_node/cli.py \
       packages/vibe-cardano/src/vibe/cardano/node/__main__.py
git commit -m "feat: KES key deserialization from cardano-cli format + opcert loading"
```

---

## Task 2: Persistent Block-Fetch Client

The current `run_block_fetch()` sends `ClientDone` after processing all ranges, making it one-shot. The FSM supports looping (`BatchDone -> BFIdle`), so we need a continuous mode that accepts ranges from a queue.

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/network/blockfetch_protocol.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py:420-530` (block-fetch worker)

- [ ] **Step 1: Add `run_block_fetch_continuous()` to blockfetch_protocol.py**

```python
async def run_block_fetch_continuous(
    channel: object,
    range_queue: asyncio.Queue,
    on_block_received: OnBlockReceived,
    on_no_blocks: OnNoBlocks | None = None,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run block-fetch in continuous mode — pulls ranges from a queue.

    Unlike run_block_fetch(), this keeps the protocol alive between
    ranges. The BlockFetchClient loops in BFIdle, sending RequestRange
    for each item from the queue. Only sends ClientDone on stop.

    Parameters
    ----------
    channel : MiniProtocolChannel
    range_queue : asyncio.Queue
        Queue of (point_from, point_to) tuples.
    on_block_received : OnBlockReceived
    on_no_blocks : OnNoBlocks | None
    stop_event : asyncio.Event | None
    """
    protocol = BlockFetchProtocol()
    codec = BlockFetchCodec()
    runner = ProtocolRunner(
        role=PeerRole.Initiator,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    client = BlockFetchClient(runner)

    while True:
        if stop_event is not None and stop_event.is_set():
            break

        try:
            point_from, point_to = await asyncio.wait_for(
                range_queue.get(), timeout=1.0
            )
        except TimeoutError:
            continue

        blocks = await client.request_range(point_from, point_to)
        if blocks is None:
            if on_no_blocks is not None:
                await on_no_blocks(point_from, point_to)
        else:
            for block_cbor in blocks:
                await on_block_received(block_cbor)

    await client.done()
```

- [ ] **Step 2: Update block-fetch worker in run.py to use continuous mode**

Replace the `_block_fetch_worker` function in `_connect_peer` to use `run_block_fetch_continuous` instead of calling `run_block_fetch` repeatedly.

- [ ] **Step 3: Run tests**

Run: `uv run pytest packages/vibe-cardano/tests/network/ -q --timeout=30`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: persistent block-fetch client — continuous mode from range queue"
```

---

## Task 3: Block Validation in Sync Pipeline

Wire `validate_block()` into the chain-sync/block-fetch pipeline so received blocks are validated through era-specific ledger rules before storage.

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py` (on_block callback)
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py` (track protocol params)

- [ ] **Step 1: Add block parsing to the on_block callback**

In the `_on_block` callback inside `_block_fetch_worker`, after receiving block CBOR:

```python
from vibe.cardano.serialization.block import decode_block_header, detect_era
from vibe.cardano.serialization.transaction import decode_block_body
from vibe.cardano.consensus.hfc import validate_block

# Parse header
header = decode_block_header(block_cbor)
era = detect_era(block_cbor)

# Parse body and validate each transaction
body = decode_block_body(block_cbor)
errors = []
for tx in body.transactions:
    tx_errors = validate_block(
        era=era,
        block=tx,
        ledger_state=ledger_db,  # UTxO set
        protocol_params=protocol_params,
        current_slot=header.slot,
    )
    errors.extend(tx_errors)

if errors:
    logger.warning(
        "Block %d at slot %d: %d validation errors: %s",
        header.block_number, header.slot, len(errors), errors[:3],
    )
else:
    # Store valid block
    await chain_db.add_block(...)
```

- [ ] **Step 2: Add default protocol params to NodeConfig or genesis loading**

Load protocol params from `shelley-genesis.json` `protocolParams` field in the CLI serve command.

- [ ] **Step 3: Run tests**

Run: `uv run pytest packages/vibe-cardano/tests/ -q --timeout=30 --ignore=tests/conformance/test_uplc_conformance.py`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: block validation in sync pipeline — era-aware ledger rules"
```

---

## Task 4: Ledger State Application

After block validation passes, apply the block's UTxO mutations to LedgerDB.

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py` (after validation)

- [ ] **Step 1: Extract consumed/created UTxOs from validated block**

```python
# After successful validation:
consumed_keys = []
created_entries = []

for tx in body.transactions:
    if not tx.valid:
        continue
    # Consumed: all inputs
    if hasattr(tx.body, 'inputs') and tx.body.inputs:
        for inp in tx.body.inputs:
            key = inp.transaction_id.payload + inp.index.to_bytes(2, 'big')
            consumed_keys.append(key)
    # Created: all outputs
    if hasattr(tx.body, 'outputs') and tx.body.outputs:
        for idx, out in enumerate(tx.body.outputs):
            key = tx.tx_hash + idx.to_bytes(2, 'big')
            created_entries.append((key, {
                'tx_hash': tx.tx_hash,
                'tx_index': idx,
                'address': str(out.address) if hasattr(out, 'address') else '',
                'value': int(out.amount) if hasattr(out, 'amount') else 0,
                'datum_hash': getattr(out, 'datum_hash', b'') or b'',
            }))

ledger_db.apply_block(consumed_keys, created_entries, block_slot=header.slot)
```

- [ ] **Step 2: Run tests**

Expected: All pass

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: apply ledger state mutations from validated blocks"
```

---

## Task 5: Epoch Nonce from Genesis and Chain State

Replace the hardcoded epoch nonce with the real genesis nonce, then evolve it each epoch.

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py` (add nonce tracking)
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py` (use kernel nonce in forge loop)
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/config.py` (add genesis_hash)

- [ ] **Step 1: Compute genesis hash for epoch nonce seed**

In the CLI serve command, after loading shelley-genesis.json:
```python
import hashlib, json
genesis_bytes = json.dumps(sg, sort_keys=True).encode()
genesis_hash = hashlib.blake2b(genesis_bytes, digest_size=32).digest()
```

Pass this as `config.genesis_hash` (add the field to NodeConfig).

- [ ] **Step 2: Add nonce tracking to NodeKernel**

```python
# In NodeKernel.__init__:
from vibe.cardano.consensus.nonce import EpochNonce, accumulate_vrf_output, evolve_nonce

self._epoch_nonce = EpochNonce(value=genesis_hash)
self._eta_v = genesis_hash  # Accumulated VRF outputs for current epoch
self._current_epoch = 0
```

Add `accumulate_block_vrf()` method that accumulates VRF outputs from received block headers within the stability window.

- [ ] **Step 3: Use kernel nonce in forge loop**

Replace `epoch_nonce = hashlib.blake2b(...)` with `epoch_nonce = node_kernel.epoch_nonce.value`.

- [ ] **Step 4: Run tests**

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: epoch nonce from genesis hash with per-block VRF accumulation"
```

---

## Task 6: N2C Server Wiring

Wire the 4 existing N2C miniprotocol servers (local chain-sync, local tx-submission, local state-query, local tx-monitor) onto inbound Unix socket connections.

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py` (`_run_n2c_server`)

- [ ] **Step 1: Add N2C handshake responder**

The N2C handshake uses different version numbers (16-20) and 2-element version data `[network_magic, query]`. Add `run_handshake_server_n2c()` or extend the existing server with an `n2c=True` flag.

- [ ] **Step 2: Wire local chain-sync server**

```python
from vibe.cardano.network.local_chainsync_protocol import create_local_chainsync_server

server = create_local_chainsync_server(channels[CHAIN_SYNC_N2C_ID], chaindb=chain_db)
asyncio.create_task(server.run(stop_event=stop))
```

- [ ] **Step 3: Wire local tx-submission server**

```python
from vibe.cardano.network.local_txsubmission_protocol import run_local_tx_submission_server
asyncio.create_task(run_local_tx_submission_server(channels[LOCAL_TX_SUBMISSION_ID], mempool=mempool, stop_event=stop))
```

- [ ] **Step 4: Wire local state-query server**

```python
from vibe.cardano.network.local_statequery_protocol import run_local_state_query_server
asyncio.create_task(run_local_state_query_server(channels[LOCAL_STATE_QUERY_PROTOCOL_ID], ledger_db=ledger_db, stop_event=stop))
```

- [ ] **Step 5: Wire local tx-monitor server**

```python
from vibe.cardano.network.local_txmonitor_protocol import run_local_tx_monitor_server
asyncio.create_task(run_local_tx_monitor_server(channels[LOCAL_TX_MONITOR_ID], mempool=mempool, stop_event=stop))
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest packages/vibe-cardano/tests/ tests/ -q --timeout=30 --ignore=tests/conformance/test_uplc_conformance.py`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git commit -m "feat: wire all 4 N2C miniprotocol servers on Unix socket connections"
```

---

## Task 7: Devnet End-to-End Verification

Restart the 3-node devnet with fresh genesis and verify:
1. vibe-node syncs headers from Haskell nodes
2. vibe-node fetches and validates full block bodies
3. vibe-node forges blocks with correct KES signatures
4. Haskell nodes accept vibe-node's blocks (chain-sync from us + block-fetch)

**Files:**
- Modify: `infra/devnet/docker-compose.devnet.yml` (if needed)
- Modify: `infra/devnet/Dockerfile.vibe-node` (if needed)

- [ ] **Step 1: Clean restart devnet**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml down -v
./infra/devnet/scripts/generate-keys.sh
docker compose -f infra/devnet/docker-compose.devnet.yml up -d
```

- [ ] **Step 2: Monitor vibe-node logs for block forging**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml logs -f vibe-node | grep -E "(FORGED|stored block|inbound|accepted)"
```

Expected: Forged blocks appear every ~6s (f=0.1, stake=33%)

- [ ] **Step 3: Monitor Haskell node logs for vibe-node blocks**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml logs -f haskell-node-1 | grep -E "(AddedToCurrentChain|SwitchedToAFork)"
```

Expected: Haskell node-1 adds blocks produced by pool3 (vibe-node) to its chain.

- [ ] **Step 4: Verify tip agreement**

All 3 nodes should converge on the same tip within k*slotLength seconds.

- [ ] **Step 5: Commit any fixes**

```bash
git commit -m "fix: devnet integration fixes for end-to-end block acceptance"
```

---

## Dependency Order

```
Task 1 (KES deserialization) ──────────────────────┐
Task 2 (Persistent block-fetch) ───┐               │
Task 3 (Block validation) ─────────┤               │
Task 4 (Ledger state) ─────────────┤               │
Task 5 (Epoch nonce) ──────────────┤               │
                                   ├─► Task 7 (E2E)
Task 6 (N2C servers) ─────────────────────────────┘
```

Tasks 1-6 can be done in parallel (except Task 4 depends on Task 3). Task 7 is the final integration test that validates everything together.

## Estimated Scope

- Task 1: ~100 lines new code + ~30 lines modified
- Task 2: ~40 lines new + ~20 lines modified
- Task 3: ~50 lines modified
- Task 4: ~30 lines modified
- Task 5: ~40 lines modified
- Task 6: ~60 lines modified
- Task 7: Testing only

Total: ~350 lines of new/modified code. All subsystem logic already exists.
