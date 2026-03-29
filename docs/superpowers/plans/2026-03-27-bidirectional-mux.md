# Bidirectional Mux Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement bidirectional mux channels keyed by `(protocol_id, direction)` so each TCP connection can run both initiator and responder miniprotocols, matching Haskell's `InitiatorResponderMode`.

**Architecture:** Extend the `Multiplexer` to support dual channels per protocol ID — one for initiator direction, one for responder. The receiver flips the direction bit when routing (remote's initiator → local's responder). The sender reads each channel's `is_initiator` flag for the segment direction bit. Both `inbound_server` and `peer_manager` call shared bundle launchers to start the full miniprotocol set in both directions.

**Tech Stack:** Python 3.14, asyncio, existing vibe-core multiplexer and vibe-cardano network modules.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `packages/vibe-core/src/vibe/core/multiplexer/mux.py` | **Modify** | Dual-channel routing: `_channels` keyed by `(protocol_id, is_initiator_dir)`, receiver flips direction, sender uses per-channel direction |
| `packages/vibe-core/tests/multiplexer/test_mux.py` | **Create** | Unit tests for dual-channel routing, direction flipping, round-robin over both directions |
| `packages/vibe-cardano/src/vibe/cardano/node/miniprotocol_bundle.py` | **Create** | Shared `launch_initiator_bundle()` and `launch_responder_bundle()` functions |
| `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py` | **Modify** | Use `add_protocol_pair()`, launch both initiator + responder bundles |
| `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py` | **Modify** | Use `add_protocol_pair()`, launch both initiator + responder bundles |
| `packages/vibe-cardano/src/vibe/cardano/network/handshake_protocol.py` | **Modify** | Revert to `initiator_only=False` |
| `packages/vibe-cardano/tests/node/test_bidirectional_mux.py` | **Create** | Integration test: dual-channel mux with mock bearer |

---

### Task 1: Mux dual-channel support

**Files:**
- Modify: `packages/vibe-core/src/vibe/core/multiplexer/mux.py`
- Create: `packages/vibe-core/tests/multiplexer/test_mux.py`

This is the core change. The `Multiplexer._channels` dict changes from `dict[int, MiniProtocolChannel]` to `dict[tuple[int, bool], MiniProtocolChannel]`. A new `add_protocol_pair()` method registers both directions. The receiver flips the direction bit when routing. The sender uses per-channel direction.

- [ ] **Step 1: Write failing tests for dual-channel mux**

```python
# packages/vibe-core/tests/multiplexer/test_mux.py
"""Tests for bidirectional mux channel routing."""
from __future__ import annotations

import asyncio

import pytest

from vibe.core.multiplexer.mux import MiniProtocolChannel, Multiplexer
from vibe.core.multiplexer.bearer import Bearer
from vibe.core.multiplexer.segment import MuxSegment, encode_segment


class MockBearer:
    """Minimal bearer for testing — stores written segments, feeds reads."""

    def __init__(self):
        self.written: list[MuxSegment] = []
        self._read_queue: asyncio.Queue[MuxSegment] = asyncio.Queue()
        self.closed = False

    async def write_segment(self, segment: MuxSegment) -> None:
        self.written.append(segment)

    async def read_segment(self) -> MuxSegment:
        return await self._read_queue.get()

    def feed_segment(self, segment: MuxSegment) -> None:
        self._read_queue.put_nowait(segment)

    async def close(self) -> None:
        self.closed = True


class TestAddProtocolPair:
    def test_returns_two_channels(self):
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        init_ch, resp_ch = mux.add_protocol_pair(2)
        assert isinstance(init_ch, MiniProtocolChannel)
        assert isinstance(resp_ch, MiniProtocolChannel)

    def test_channels_have_correct_direction(self):
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        init_ch, resp_ch = mux.add_protocol_pair(2)
        assert init_ch.is_initiator is True
        assert resp_ch.is_initiator is False

    def test_channels_have_same_protocol_id(self):
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        init_ch, resp_ch = mux.add_protocol_pair(2)
        assert init_ch.protocol_id == 2
        assert resp_ch.protocol_id == 2

    def test_duplicate_pair_raises(self):
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        mux.add_protocol_pair(2)
        with pytest.raises(ValueError):
            mux.add_protocol_pair(2)

    def test_add_protocol_still_works(self):
        """Legacy add_protocol registers single direction."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(5)
        assert ch.protocol_id == 5
        assert ch.is_initiator is True


class TestSenderDirection:
    @pytest.mark.asyncio
    async def test_initiator_channel_sends_with_initiator_flag(self):
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        init_ch, resp_ch = mux.add_protocol_pair(2)

        # Send on initiator channel
        await init_ch.send(b"hello")

        # Start sender, let it drain one segment, then stop
        mux._stop_event = asyncio.Event()
        sender = asyncio.create_task(mux._sender_loop())
        await asyncio.sleep(0.05)
        mux._stop_event.set()
        mux._closed = True
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass

        assert len(bearer.written) >= 1
        assert bearer.written[0].is_initiator is True
        assert bearer.written[0].protocol_id == 2

    @pytest.mark.asyncio
    async def test_responder_channel_sends_with_responder_flag(self):
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        init_ch, resp_ch = mux.add_protocol_pair(2)

        # Send on responder channel
        await resp_ch.send(b"world")

        mux._stop_event = asyncio.Event()
        sender = asyncio.create_task(mux._sender_loop())
        await asyncio.sleep(0.05)
        mux._stop_event.set()
        mux._closed = True
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass

        assert len(bearer.written) >= 1
        assert bearer.written[0].is_initiator is False
        assert bearer.written[0].protocol_id == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/vibe-core/tests/multiplexer/test_mux.py -v`
Expected: FAIL — `add_protocol_pair` doesn't exist

- [ ] **Step 3: Implement dual-channel mux**

In `mux.py`, make these changes:

**a) Change `_channels` type** (line 181):
```python
# Before:
self._channels: dict[int, MiniProtocolChannel] = {}
# After:
self._channels: dict[tuple[int, bool], MiniProtocolChannel] = {}
```

**b) Add `add_protocol_pair()` method** (after line 233):
```python
def add_protocol_pair(
    self, protocol_id: int, max_ingress_size: int = 0,
) -> tuple[MiniProtocolChannel, MiniProtocolChannel]:
    """Register both initiator and responder channels for a protocol.

    Returns (initiator_channel, responder_channel).

    Haskell ref: InitiatorAndResponderProtocol registers two entries
    per protocol number in mkMiniProtocolInfo.
    """
    if self._closed:
        raise MuxClosedError("multiplexer is closed")
    if not (0 <= protocol_id <= 0x7FFF):
        raise ValueError(f"protocol_id must be 0..32767, got {protocol_id}")
    if (protocol_id, True) in self._channels or (protocol_id, False) in self._channels:
        raise ValueError(f"protocol {protocol_id} is already registered")

    init_ch = MiniProtocolChannel(
        protocol_id=protocol_id,
        is_initiator=True,
        max_ingress_size=max_ingress_size,
    )
    init_ch._on_send = self._data_available.set

    resp_ch = MiniProtocolChannel(
        protocol_id=protocol_id,
        is_initiator=False,
        max_ingress_size=max_ingress_size,
    )
    resp_ch._on_send = self._data_available.set

    self._channels[(protocol_id, True)] = init_ch
    self._channels[(protocol_id, False)] = resp_ch
    return init_ch, resp_ch
```

**c) Update `add_protocol()` for backward compat** (replace lines 201-233):
```python
def add_protocol(self, protocol_id: int, max_ingress_size: int = 0) -> MiniProtocolChannel:
    """Register a single-direction channel (legacy API).

    Uses the mux's is_initiator flag for direction. Cannot coexist
    with add_protocol_pair for the same protocol_id.
    """
    if self._closed:
        raise MuxClosedError("multiplexer is closed")
    if not (0 <= protocol_id <= 0x7FFF):
        raise ValueError(f"protocol_id must be 0..32767, got {protocol_id}")
    direction = self._is_initiator
    key = (protocol_id, direction)
    if key in self._channels:
        raise ValueError(f"protocol {protocol_id} direction {direction} is already registered")
    channel = MiniProtocolChannel(
        protocol_id=protocol_id,
        is_initiator=direction,
        max_ingress_size=max_ingress_size,
    )
    channel._on_send = self._data_available.set
    self._channels[key] = channel
    return channel
```

**d) Update `_sender_loop()` — iterate over all channels, use per-channel direction** (replace lines 336-377):
```python
async def _sender_loop(self) -> None:
    channel_keys = list(self._channels.keys())
    if not channel_keys:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            return

    idx = 0
    while not self._closed:
        sent_any = False

        for _ in range(len(channel_keys)):
            key = channel_keys[idx % len(channel_keys)]
            idx += 1
            channel = self._channels.get(key)
            if channel is None or channel._closed:
                continue

            try:
                payload = channel._outbound.get_nowait()
            except asyncio.QueueEmpty:
                continue

            if payload is _CHANNEL_CLOSED:
                continue

            assert isinstance(payload, bytes)
            segment = MuxSegment(
                timestamp=self._make_timestamp(),
                protocol_id=channel.protocol_id,
                is_initiator=channel.is_initiator,  # Per-channel direction
                payload=payload,
            )
            try:
                await self._bearer.write_segment(segment)
            except (BearerClosedError, ConnectionError) as exc:
                logger.debug("sender: bearer disconnected: %s", exc)
                return
            sent_any = True

        if not sent_any:
            # ... (keep existing event-driven wait logic, but use channel_keys)
```

**e) Update `_receiver_loop()` — flip direction when routing** (replace line 425):
```python
# Before:
channel = self._channels.get(segment.protocol_id)
# After — flip direction: remote's initiator → local's responder
local_dir = not segment.is_initiator
channel = self._channels.get((segment.protocol_id, local_dir))
```

**f) Update `_shutdown_channels()`** — iterate dict values (no change needed, already does `self._channels.values()`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/vibe-core/tests/multiplexer/test_mux.py -v`
Expected: All PASS

- [ ] **Step 5: Run existing tests for regressions**

Run: `uv run pytest packages/vibe-cardano/tests/ -q --timeout=60`
Expected: All PASS (backward-compat `add_protocol` still works)

- [ ] **Step 6: Commit**

```bash
git add packages/vibe-core/src/vibe/core/multiplexer/mux.py packages/vibe-core/tests/multiplexer/test_mux.py
git commit -m "feat: bidirectional mux — dual channels per protocol ID

Extend Multiplexer to key channels by (protocol_id, direction).
add_protocol_pair() returns (initiator_ch, responder_ch).
Receiver flips direction bit when routing: remote's initiator →
local's responder. Sender uses per-channel is_initiator flag.

Haskell ref: Network.Mux.Ingress.demuxer flips direction on routing.
InitiatorAndResponderProtocol registers two entries per protocol.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Shared miniprotocol bundle launcher

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/node/miniprotocol_bundle.py`

Extract the miniprotocol launch logic from `inbound_server.py` and `peer_manager.py` into shared functions. This avoids duplicating the setup code when both files need to launch both bundles.

- [ ] **Step 1: Create miniprotocol_bundle.py**

```python
# packages/vibe-cardano/src/vibe/cardano/node/miniprotocol_bundle.py
"""Shared miniprotocol bundle launchers for N2N connections.

Both inbound_server and peer_manager need to launch the same set of
miniprotocol clients and servers. This module provides shared functions
to avoid duplicating the setup logic.

Haskell ref: Ouroboros.Network.NodeToNode (nodeToNodeProtocols)
    — defines the full miniprotocol bundle for N2N connections.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def launch_responder_bundle(
    channels: dict[int, Any],
    chain_db: Any,
    mempool: Any,
    stop_event: asyncio.Event,
    peer_info: str = "",
) -> list[asyncio.Task]:
    """Start responder-side miniprotocols (chain-sync server, etc.).

    Args:
        channels: Dict mapping protocol_id → responder MiniProtocolChannel.
        chain_db: ChainDB for chain-sync and block-fetch serving.
        mempool: Mempool for tx-submission serving.
        stop_event: Event to signal shutdown.
        peer_info: Peer identifier for logging.

    Returns:
        List of launched asyncio Tasks.
    """
    from vibe.cardano.network.blockfetch import BLOCK_FETCH_N2N_ID
    from vibe.cardano.network.blockfetch_protocol import run_block_fetch_server
    from vibe.cardano.network.chainsync import CHAIN_SYNC_N2N_ID
    from vibe.cardano.network.chainsync_protocol import run_chain_sync_server
    from vibe.cardano.network.keepalive import KEEP_ALIVE_PROTOCOL_ID
    from vibe.cardano.network.keepalive_protocol import run_keep_alive_server
    from vibe.cardano.network.txsubmission import TX_SUBMISSION_N2N_ID
    from vibe.core.multiplexer import MuxClosedError, BearerClosedError

    tasks: list[asyncio.Task] = []

    async def _safe(coro, name: str) -> None:
        try:
            await coro
        except (MuxClosedError, BearerClosedError):
            logger.debug("Responder %s %s: peer disconnected", peer_info, name)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Responder %s %s: error: %s", peer_info, name, exc)

    # Keep-alive server
    if KEEP_ALIVE_PROTOCOL_ID in channels:
        tasks.append(asyncio.create_task(
            _safe(run_keep_alive_server(channels[KEEP_ALIVE_PROTOCOL_ID], stop_event=stop_event), "keep-alive"),
            name=f"ka-srv-{peer_info}",
        ))

    # Chain-sync server
    if CHAIN_SYNC_N2N_ID in channels and chain_db is not None:
        follower = chain_db.new_follower()
        tasks.append(asyncio.create_task(
            _safe(run_chain_sync_server(channels[CHAIN_SYNC_N2N_ID], follower=follower, stop_event=stop_event), "chain-sync"),
            name=f"cs-srv-{peer_info}",
        ))

    # Block-fetch server
    if BLOCK_FETCH_N2N_ID in channels and chain_db is not None:
        tasks.append(asyncio.create_task(
            _safe(run_block_fetch_server(channels[BLOCK_FETCH_N2N_ID], block_provider=chain_db, stop_event=stop_event), "block-fetch"),
            name=f"bf-srv-{peer_info}",
        ))

    # Tx-submission server
    if TX_SUBMISSION_N2N_ID in channels and mempool is not None:
        from vibe.cardano.network.txsubmission_protocol import run_tx_submission_server

        async def _on_tx_ids(txids):
            pass

        async def _on_txs(txs):
            for tx_cbor in txs:
                try:
                    await mempool.add_tx(tx_cbor)
                except Exception:
                    pass

        tasks.append(asyncio.create_task(
            _safe(run_tx_submission_server(
                channels[TX_SUBMISSION_N2N_ID],
                on_tx_ids_received=_on_tx_ids,
                on_txs_received=_on_txs,
                stop_event=stop_event,
            ), "tx-sub"),
            name=f"txsub-srv-{peer_info}",
        ))

    return tasks


async def launch_initiator_bundle(
    channels: dict[int, Any],
    stop_event: asyncio.Event,
    peer_info: str = "",
) -> list[asyncio.Task]:
    """Start initiator-side miniprotocols (keep-alive client, tx-sub client).

    For inbound connections, this provides the initiator-direction traffic
    that Haskell's inbound governor expects. Chain-sync client and block-fetch
    client are NOT started here — those are managed by peer_manager with
    specific fetch queues and range tracking.

    Args:
        channels: Dict mapping protocol_id → initiator MiniProtocolChannel.
        stop_event: Event to signal shutdown.
        peer_info: Peer identifier for logging.

    Returns:
        List of launched asyncio Tasks.
    """
    from vibe.cardano.network.keepalive import KEEP_ALIVE_PROTOCOL_ID
    from vibe.cardano.network.keepalive_protocol import run_keep_alive_client
    from vibe.cardano.network.txsubmission import TX_SUBMISSION_N2N_ID
    from vibe.core.multiplexer import MuxClosedError, BearerClosedError

    tasks: list[asyncio.Task] = []

    async def _safe(coro, name: str) -> None:
        try:
            await coro
        except (MuxClosedError, BearerClosedError):
            logger.debug("Initiator %s %s: peer disconnected", peer_info, name)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Initiator %s %s: error: %s", peer_info, name, exc)

    # Keep-alive client — sends pings to keep connection warm
    if KEEP_ALIVE_PROTOCOL_ID in channels:
        tasks.append(asyncio.create_task(
            _safe(run_keep_alive_client(channels[KEEP_ALIVE_PROTOCOL_ID], stop_event=stop_event, interval=10.0), "keep-alive"),
            name=f"ka-cli-{peer_info}",
        ))

    # Tx-submission client — responds to server's tx requests with empty lists
    if TX_SUBMISSION_N2N_ID in channels:
        from vibe.cardano.network.txsubmission_protocol import run_tx_submission_client

        async def _on_request_tx_ids(blocking, ack_count, req_count):
            if blocking:
                await stop_event.wait()
                return None
            return []

        async def _on_request_txs(txids):
            return []

        tasks.append(asyncio.create_task(
            _safe(run_tx_submission_client(
                channels[TX_SUBMISSION_N2N_ID],
                on_request_tx_ids=_on_request_tx_ids,
                on_request_txs=_on_request_txs,
                stop_event=stop_event,
            ), "tx-sub"),
            name=f"txsub-cli-{peer_info}",
        ))

    return tasks
```

- [ ] **Step 2: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/miniprotocol_bundle.py
git commit -m "feat: shared miniprotocol bundle launchers

Extract responder and initiator miniprotocol launch logic into
shared functions. Both inbound_server and peer_manager will use
these to avoid duplicating setup code.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Inbound server — full duplex with dual channels

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py`

Replace the per-protocol `mux.add_protocol()` calls with `mux.add_protocol_pair()`, and launch both responder + initiator bundles.

- [ ] **Step 1: Update inbound_server.py**

Replace the channel registration and miniprotocol launch section (lines ~160-284) with:

```python
# In handle_connection(), after bearer and mux creation:
from vibe.cardano.network.blockfetch import BLOCK_FETCH_N2N_ID
from vibe.cardano.network.chainsync import CHAIN_SYNC_N2N_ID
from vibe.cardano.network.keepalive import KEEP_ALIVE_PROTOCOL_ID
from vibe.cardano.network.txsubmission import TX_SUBMISSION_N2N_ID
from vibe.cardano.node.miniprotocol_bundle import (
    launch_initiator_bundle,
    launch_responder_bundle,
)

bearer = Bearer(reader, writer)
mux = Multiplexer(bearer, is_initiator=False)

# Register dual channels for each N2N protocol
init_channels: dict[int, MiniProtocolChannel] = {}
resp_channels: dict[int, MiniProtocolChannel] = {}
for proto_id in [HANDSHAKE_PROTOCOL_ID, CHAIN_SYNC_N2N_ID, BLOCK_FETCH_N2N_ID, TX_SUBMISSION_N2N_ID, KEEP_ALIVE_PROTOCOL_ID]:
    if proto_id == HANDSHAKE_PROTOCOL_ID:
        # Handshake only needs responder direction for inbound
        resp_channels[proto_id] = mux.add_protocol(proto_id)
    else:
        init_ch, resp_ch = mux.add_protocol_pair(proto_id)
        init_channels[proto_id] = init_ch
        resp_channels[proto_id] = resp_ch

# Start mux, run handshake on responder channel...
# (handshake code stays the same, using resp_channels[HANDSHAKE_PROTOCOL_ID])

# After handshake succeeds:
# Launch responder bundle (chain-sync server, etc.)
resp_tasks = await launch_responder_bundle(
    resp_channels, chain_db, mempool, stop, peer_info=str(peer_info),
)
# Launch initiator bundle (keep-alive client, tx-sub client)
init_tasks = await launch_initiator_bundle(
    init_channels, stop, peer_info=str(peer_info),
)
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest packages/vibe-cardano/tests/ -q --timeout=60`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py
git commit -m "feat: inbound server runs full duplex with dual channels

Use add_protocol_pair() for each N2N protocol on inbound connections.
Launch both responder bundle (chain-sync server, etc.) and initiator
bundle (keep-alive client, tx-sub client). Haskell's inbound governor
now sees initiator-direction traffic and keeps the connection warm.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Peer manager — dual channels on outbound

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py`

Update outbound connection setup to use `add_protocol_pair()` and launch responder bundle alongside the existing initiator protocols.

- [ ] **Step 1: Update peer_manager channel registration**

In `_setup_peer()` (or wherever channels are registered for outbound connections), replace:
```python
for proto_id in N2N_PROTOCOL_IDS:
    channels[proto_id] = mux.add_protocol(proto_id)
```

With:
```python
init_channels: dict[int, MiniProtocolChannel] = {}
resp_channels: dict[int, MiniProtocolChannel] = {}
for proto_id in N2N_PROTOCOL_IDS:
    if proto_id == HANDSHAKE_PROTOCOL_ID:
        init_channels[proto_id] = mux.add_protocol(proto_id)
    else:
        init_ch, resp_ch = mux.add_protocol_pair(proto_id)
        init_channels[proto_id] = init_ch
        resp_channels[proto_id] = resp_ch
channels = init_channels  # Existing code uses channels[proto_id] for initiator side
```

Then after launching the existing initiator protocols, add:
```python
# Launch responder bundle on outbound connection
from vibe.cardano.node.miniprotocol_bundle import launch_responder_bundle
resp_tasks = await launch_responder_bundle(
    resp_channels, chain_db, mempool, stop_event, peer_info=peer_addr,
)
for t in resp_tasks:
    peer.protocol_tasks.append(t)
```

- [ ] **Step 2: Revert handshake to InitiatorAndResponder**

In `packages/vibe-cardano/src/vibe/cardano/network/handshake_protocol.py`, revert both calls:

```python
# Line ~314 (client):
version_table = build_version_table(network_magic)  # Remove initiator_only=True

# Line ~374 (server):
server_versions = build_version_table(network_magic)  # Remove initiator_only=True
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest packages/vibe-cardano/tests/ -q --timeout=60`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py packages/vibe-cardano/src/vibe/cardano/network/handshake_protocol.py
git commit -m "feat: outbound connections run full duplex + revert InitiatorOnly

Outbound connections now use add_protocol_pair() and launch responder
bundle (chain-sync server, etc.) alongside initiator protocols.
Revert handshake to InitiatorAndResponder since we now support it.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Devnet verification

**Files:**
- No code changes — verification only

- [ ] **Step 1: Rebuild and run devnet for 5 minutes**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml build vibe-node
docker compose -f infra/devnet/docker-compose.devnet.yml up -d
sleep 330
docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color > /tmp/devnet-bidirectional.txt 2>&1
```

- [ ] **Step 2: Verify metrics**

```bash
# Target: 0 VRFKeyBadProof, 0 ExceededTimeLimit, 0 DemotedToColdRemote
# Vibe forge share: ~30-36%
grep -c "VRFKeyBadProof" /tmp/devnet-bidirectional.txt    # Should be 0
grep -c "ExceededTimeLimit" /tmp/devnet-bidirectional.txt  # Should be 0
grep -c "DemotedToColdRemote" /tmp/devnet-bidirectional.txt  # Should be 0
```

- [ ] **Step 3: Stop devnet**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml down -v
```
