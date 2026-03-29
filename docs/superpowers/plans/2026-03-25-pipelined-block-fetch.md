# Pipelined Block-Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace sequential block-fetch with a pipelined 3-task architecture that eliminates batch boundary RTT and decouples block processing from network receive.

**Architecture:** Three concurrent asyncio tasks — sender (pipelines range requests), receiver (decodes responses into a block queue), processor (runs `_on_block` independently). Bypasses ProtocolRunner for raw channel access, same proven pattern as pipelined chain-sync.

**Tech Stack:** Python asyncio, cbor2pure, existing blockfetch.py encode/decode functions

**Spec:** `docs/superpowers/specs/2026-03-25-pipelined-block-fetch-design.md`

---

## File Structure

- **Modify:** `packages/vibe-cardano/src/vibe/cardano/network/blockfetch_protocol.py` — add `run_block_fetch_pipelined` function
- **Modify:** `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py` — swap call site (~line 789)
- **Create:** `tests/unit/test_blockfetch_pipelined.py` — unit tests for the new function

---

### Task 1: Scaffold `run_block_fetch_pipelined` with a basic sender

**Files:**
- Create: `tests/unit/test_blockfetch_pipelined.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/network/blockfetch_protocol.py`

- [ ] **Step 1: Write the failing test — sender sends MsgRequestRange from range_queue**

```python
"""Tests for pipelined block-fetch (run_block_fetch_pipelined)."""

from __future__ import annotations

import asyncio

import pytest

import cbor2pure as cbor2

from vibe.cardano.network.blockfetch import (
    MSG_REQUEST_RANGE,
    encode_batch_done,
    encode_block,
    encode_start_batch,
)
from vibe.cardano.network.chainsync import Point


HASH_A = b"\xaa" * 32
HASH_B = b"\xbb" * 32
POINT_A = Point(slot=1, hash=HASH_A)
POINT_B = Point(slot=100, hash=HASH_B)
SAMPLE_BLOCK = b"\xde\xad" * 50


class FakeChannel:
    """Mock mux channel that records sent bytes and feeds scripted responses."""

    def __init__(self, responses: list[bytes] | None = None) -> None:
        self.sent: list[bytes] = []
        self._responses: asyncio.Queue[bytes] = asyncio.Queue()
        if responses:
            for r in responses:
                self._responses.put_nowait(r)

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> bytes:
        return await self._responses.get()

    def inject(self, data: bytes) -> None:
        """Add a response to be returned by recv()."""
        self._responses.put_nowait(data)


class TestPipelinedSender:
    """Verify the sender task sends MsgRequestRange from range_queue."""

    @pytest.mark.asyncio
    async def test_sender_sends_request_range(self):
        """Sender encodes and sends MsgRequestRange for each range in the queue."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()
        range_queue.put_nowait((POINT_A, POINT_B))

        stop = asyncio.Event()
        blocks_received: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks_received.append(b)

        # Inject server response: StartBatch, Block, BatchDone
        channel.inject(encode_start_batch())
        channel.inject(encode_block(SAMPLE_BLOCK))
        channel.inject(encode_batch_done())

        # Run pipelined fetch — should process 1 range then wait
        # Set stop after a short delay
        async def stop_after():
            await asyncio.sleep(0.1)
            stop.set()

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        stopper = asyncio.create_task(stop_after())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=3,
        )
        await stopper

        # Verify: sender sent MsgRequestRange
        assert len(channel.sent) >= 1
        decoded = cbor2.loads(channel.sent[0])
        assert decoded[0] == MSG_REQUEST_RANGE

        # Verify: processor received the block
        assert len(blocks_received) == 1
        assert blocks_received[0] == SAMPLE_BLOCK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_blockfetch_pipelined.py::TestPipelinedSender::test_sender_sends_request_range -xvs --timeout=10`
Expected: FAIL with `ImportError: cannot import name 'run_block_fetch_pipelined'`

- [ ] **Step 3: Write the minimal implementation**

Add to `packages/vibe-cardano/src/vibe/cardano/network/blockfetch_protocol.py` (after `run_block_fetch_continuous`, before the server section):

```python
async def run_block_fetch_pipelined(
    channel: object,
    range_queue: asyncio.Queue,
    on_block_received: OnBlockReceived,
    on_no_blocks: OnNoBlocks | None = None,
    *,
    stop_event: asyncio.Event | None = None,
    max_in_flight: int = 3,
    block_queue_size: int = 200,
) -> None:
    """Run block-fetch with pipelined range requests and decoupled processing.

    Three concurrent tasks:
    - Sender: pulls ranges from range_queue, sends MsgRequestRange on the
      raw channel, tracks in-flight batches (capped at max_in_flight).
    - Receiver: reads raw bytes from channel, decodes CBOR responses,
      puts block bytes onto block_queue.
    - Processor: pulls from block_queue, calls on_block_received.

    Bypasses ProtocolRunner for raw channel access (same pattern as
    pipelined chain-sync). The sender pipelines multiple range requests
    so the next batch's RTT overlaps with the current batch's streaming.

    Haskell ref: blockFetchClient uses YieldPipelined / Collect to overlap
    range requests. addBlockRunner processes blocks on a background thread.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for block-fetch.
    range_queue : asyncio.Queue
        Queue of (point_from, point_to) tuples to fetch.
    on_block_received : OnBlockReceived
        Async callback invoked for each block received.
    on_no_blocks : OnNoBlocks | None
        Async callback when server has no blocks for a range.
    stop_event : asyncio.Event | None
        If provided, all tasks exit when this event is set.
    max_in_flight : int
        Maximum concurrent range requests on the wire.
    block_queue_size : int
        Bounded size of the block processing queue.
    """
    import io as _io

    import cbor2pure as _cbor2

    from vibe.cardano.network.blockfetch import (
        MSG_BATCH_DONE,
        MSG_BLOCK,
        MSG_NO_BLOCKS,
        MSG_START_BATCH,
        encode_client_done,
        encode_request_range,
    )

    block_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=block_queue_size)
    in_flight = 0
    can_send = asyncio.Event()
    can_send.set()  # Start open — sender can send immediately
    _recv_buf = b""

    async def _sender() -> None:
        """Pull ranges from range_queue and send MsgRequestRange."""
        nonlocal in_flight
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return

                # Wait until we have capacity
                if in_flight >= max_in_flight:
                    can_send.clear()
                    await can_send.wait()
                    continue

                try:
                    point_from, point_to = await asyncio.wait_for(
                        range_queue.get(), timeout=0.1
                    )
                except TimeoutError:
                    continue

                data = encode_request_range(point_from, point_to)
                await channel.send(data)
                in_flight += 1
        except asyncio.CancelledError:
            return

    async def _receiver() -> None:
        """Read responses from channel and dispatch to block_queue."""
        nonlocal in_flight, _recv_buf

        while True:
            if stop_event is not None and stop_event.is_set():
                return

            # Read from channel
            if _recv_buf:
                raw = _recv_buf
                _recv_buf = b""
            else:
                raw = await channel.recv()

            # Accumulate into a bytearray for multi-segment reassembly
            buf = bytearray(raw)

            # Decode all complete CBOR messages in this buffer
            while len(buf) > 0:
                try:
                    stream = _io.BytesIO(bytes(buf))
                    dec = _cbor2.CBORDecoder(stream)
                    msg = dec.decode()
                    consumed = stream.tell()
                except Exception:
                    # Incomplete CBOR — need more data
                    try:
                        more = await channel.recv()
                        buf.extend(more)
                    except Exception:
                        return
                    continue

                # Successfully decoded one message
                remainder = bytes(buf[consumed:])
                buf = bytearray()  # Clear — we'll process remainder below

                if not isinstance(msg, list) or len(msg) < 1:
                    logger.warning("block-fetch pipelined: unexpected CBOR: %s", type(msg))
                    continue

                msg_id = msg[0]

                if msg_id == MSG_BLOCK:
                    # Extract block_cbor from element [1]
                    block_data = msg[1] if len(msg) > 1 else b""
                    if isinstance(block_data, bytes):
                        block_cbor = block_data
                    elif isinstance(block_data, memoryview):
                        block_cbor = bytes(block_data)
                    else:
                        block_cbor = _cbor2.dumps(block_data)
                    await block_queue.put(block_cbor)
                elif msg_id == MSG_START_BATCH:
                    pass  # Expected — batch is starting
                elif msg_id == MSG_BATCH_DONE:
                    in_flight -= 1
                    can_send.set()
                elif msg_id == MSG_NO_BLOCKS:
                    in_flight -= 1
                    can_send.set()
                    # NoBlocks — range not available. We don't track
                    # which range got this response, so skip callback.
                    # The range_builder will re-queue if needed.

                # Process any remainder
                if remainder:
                    buf = bytearray(remainder)

    async def _processor() -> None:
        """Pull blocks from block_queue and run on_block_received."""
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    # Drain remaining blocks before exiting
                    while not block_queue.empty():
                        try:
                            block_cbor = block_queue.get_nowait()
                            await on_block_received(block_cbor)
                        except asyncio.QueueEmpty:
                            break
                    return

                try:
                    block_cbor = await asyncio.wait_for(
                        block_queue.get(), timeout=0.1
                    )
                except TimeoutError:
                    continue

                await on_block_received(block_cbor)
        except asyncio.CancelledError:
            # Drain remaining
            while not block_queue.empty():
                try:
                    block_cbor = block_queue.get_nowait()
                    await on_block_received(block_cbor)
                except asyncio.QueueEmpty:
                    break

    # Launch sender and processor as tasks; receiver runs in main coroutine
    sender_task = asyncio.create_task(_sender())
    processor_task = asyncio.create_task(_processor())

    try:
        await _receiver()
    except Exception as exc:
        logger.warning("block-fetch pipelined receiver error: %s", exc)
        if stop_event is not None:
            stop_event.set()
    finally:
        # Shutdown: cancel sender, let processor drain, then cancel
        sender_task.cancel()
        try:
            await sender_task
        except asyncio.CancelledError:
            pass

        # Send ClientDone if channel is still open
        try:
            await channel.send(encode_client_done())
        except Exception:
            pass

        # Signal processor to drain and exit
        if stop_event is not None:
            stop_event.set()
        # Give processor time to drain block_queue
        try:
            await asyncio.wait_for(processor_task, timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            processor_task.cancel()
            try:
                await processor_task
            except asyncio.CancelledError:
                pass
```

Also add to the `__all__` list at the top of the file:
```python
"run_block_fetch_pipelined",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_blockfetch_pipelined.py::TestPipelinedSender::test_sender_sends_request_range -xvs --timeout=10`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_blockfetch_pipelined.py packages/vibe-cardano/src/vibe/cardano/network/blockfetch_protocol.py
git commit -m "feat(m6.14): scaffold run_block_fetch_pipelined with sender/receiver/processor

Prompt: Implement pipelined block-fetch per design spec — three concurrent
asyncio tasks: sender pipelines MsgRequestRange, receiver decodes
responses to a block_queue, processor runs on_block_received. Bypasses
ProtocolRunner for raw channel access.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Test pipelining behavior — multiple ranges in flight

**Files:**
- Modify: `tests/unit/test_blockfetch_pipelined.py`

- [ ] **Step 1: Write the failing test — sender sends 3 ranges before any BatchDone**

```python
class TestPipelining:
    """Verify that multiple range requests are in flight simultaneously."""

    @pytest.mark.asyncio
    async def test_multiple_ranges_in_flight(self):
        """Sender sends up to max_in_flight ranges without waiting for BatchDone."""

        class TrackingChannel(FakeChannel):
            """FakeChannel that signals when N sends have occurred."""

            def __init__(self, notify_at: int) -> None:
                super().__init__()
                self._notify_at = notify_at
                self.send_reached = asyncio.Event()

            async def send(self, data: bytes) -> None:
                self.sent.append(data)
                if len(self.sent) >= self._notify_at:
                    self.send_reached.set()

        max_in_flight = 2
        channel = TrackingChannel(notify_at=max_in_flight)
        range_queue: asyncio.Queue = asyncio.Queue()

        # Queue 5 ranges
        for i in range(5):
            point = Point(slot=i * 100, hash=b"\x00" * 31 + bytes([i]))
            range_queue.put_nowait((point, point))

        stop = asyncio.Event()
        blocks: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks.append(b)

        async def delayed_responses():
            # Wait until sender has sent max_in_flight requests
            await channel.send_reached.wait()
            sent_before_response = len(channel.sent)

            # Now feed responses for all 5 ranges
            for _ in range(5):
                channel.inject(encode_start_batch())
                channel.inject(encode_block(SAMPLE_BLOCK))
                channel.inject(encode_batch_done())

            await asyncio.sleep(0.3)
            stop.set()
            return sent_before_response

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        response_task = asyncio.create_task(delayed_responses())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=max_in_flight,
        )
        sent_before_response = await response_task

        # Sender should have sent exactly max_in_flight before blocking
        assert sent_before_response == max_in_flight

        # All 5 blocks should have been processed
        assert len(blocks) == 5
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_blockfetch_pipelined.py::TestPipelining::test_multiple_ranges_in_flight -xvs --timeout=10`
Expected: PASS (implementation from Task 1 already handles this)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_blockfetch_pipelined.py
git commit -m "test(m6.14): verify pipelined block-fetch sends multiple ranges in flight

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Test backpressure and clean shutdown

**Files:**
- Modify: `tests/unit/test_blockfetch_pipelined.py`

- [ ] **Step 1: Write backpressure test — in_flight never exceeds max**

```python
class TestBackpressure:
    """Verify in_flight tracking and backpressure."""

    @pytest.mark.asyncio
    async def test_in_flight_respects_max(self):
        """After max_in_flight ranges sent, sender blocks until BatchDone."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()

        for i in range(10):
            point = Point(slot=i, hash=b"\x00" * 31 + bytes([i]))
            range_queue.put_nowait((point, point))

        stop = asyncio.Event()
        blocks: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks.append(b)

        # Feed responses one batch at a time with delays
        async def slow_responses():
            for batch_num in range(10):
                await asyncio.sleep(0.02)
                channel.inject(encode_start_batch())
                channel.inject(encode_block(b"block"))
                channel.inject(encode_batch_done())
            await asyncio.sleep(0.2)
            stop.set()

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        resp_task = asyncio.create_task(slow_responses())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=3,
        )
        await resp_task

        # All 10 blocks received
        assert len(blocks) == 10


class TestShutdown:
    """Verify clean shutdown without hanging tasks."""

    @pytest.mark.asyncio
    async def test_stop_event_exits_cleanly(self):
        """Setting stop_event causes all tasks to exit without hanging."""

        class ClosingChannel(FakeChannel):
            """FakeChannel that raises on recv after close."""

            def __init__(self):
                super().__init__()
                self._closed = False

            def close(self):
                self._closed = True
                # Unblock any pending recv
                self._responses.put_nowait(b"__CLOSED__")

            async def recv(self) -> bytes:
                data = await self._responses.get()
                if self._closed:
                    raise ConnectionError("channel closed")
                return data

        channel = ClosingChannel()
        range_queue: asyncio.Queue = asyncio.Queue()
        stop = asyncio.Event()

        async def on_block(b: bytes) -> None:
            pass

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        # Set stop after a tiny delay so tasks have started
        async def stop_soon():
            await asyncio.sleep(0.01)
            stop.set()
            channel.close()

        stopper = asyncio.create_task(stop_soon())
        await asyncio.wait_for(
            run_block_fetch_pipelined(
                channel,
                range_queue=range_queue,
                on_block_received=on_block,
                stop_event=stop,
            ),
            timeout=2.0,
        )
        await stopper
        # If we get here without timeout, shutdown is clean
```

- [ ] **Step 2: Write NoBlocks response test**

```python
class TestNoBlocks:
    """Verify NoBlocks response is handled correctly."""

    @pytest.mark.asyncio
    async def test_no_blocks_decrements_in_flight(self):
        """NoBlocks response frees a slot so sender can send more ranges."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()

        for i in range(3):
            point = Point(slot=i, hash=b"\x00" * 31 + bytes([i]))
            range_queue.put_nowait((point, point))

        stop = asyncio.Event()
        blocks: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks.append(b)

        from vibe.cardano.network.blockfetch import encode_no_blocks

        async def responses():
            await asyncio.sleep(0.05)
            # Range 1: NoBlocks
            channel.inject(encode_no_blocks())
            # Range 2: has blocks
            channel.inject(encode_start_batch())
            channel.inject(encode_block(b"block2"))
            channel.inject(encode_batch_done())
            # Range 3: has blocks
            channel.inject(encode_start_batch())
            channel.inject(encode_block(b"block3"))
            channel.inject(encode_batch_done())
            await asyncio.sleep(0.2)
            stop.set()

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        resp = asyncio.create_task(responses())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=3,
        )
        await resp

        # 2 blocks received (range 1 had NoBlocks)
        assert len(blocks) == 2
```

- [ ] **Step 3: Write multi-segment CBOR reassembly test**

```python
class TestReassembly:
    """Verify receiver handles CBOR messages split across multiple recv() calls."""

    @pytest.mark.asyncio
    async def test_split_block_message(self):
        """A MsgBlock split across two recv() calls is reassembled correctly."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()
        range_queue.put_nowait((POINT_A, POINT_B))

        stop = asyncio.Event()
        blocks: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks.append(b)

        # Encode a complete batch: StartBatch + Block + BatchDone
        start_bytes = encode_start_batch()
        block_bytes = encode_block(SAMPLE_BLOCK)
        done_bytes = encode_batch_done()

        # Inject StartBatch normally
        channel.inject(start_bytes)
        # Split the Block message in half
        mid = len(block_bytes) // 2
        channel.inject(block_bytes[:mid])
        channel.inject(block_bytes[mid:])
        # BatchDone normally
        channel.inject(done_bytes)

        async def stop_later():
            await asyncio.sleep(0.3)
            stop.set()

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        stopper = asyncio.create_task(stop_later())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=3,
        )
        await stopper

        assert len(blocks) == 1
        assert blocks[0] == SAMPLE_BLOCK
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/test_blockfetch_pipelined.py -xvs --timeout=10`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_blockfetch_pipelined.py
git commit -m "test(m6.14): backpressure, shutdown, NoBlocks, and reassembly tests

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire up in peer_manager.py

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py:789-794`

- [ ] **Step 1: Swap the call site**

Change line ~789 from:

```python
            try:
                await run_block_fetch_continuous(
                    bf_channel,
                    range_queue=range_queue,
                    on_block_received=_on_block,
                    stop_event=stop_event,
                )
```

To:

```python
            try:
                await run_block_fetch_pipelined(
                    bf_channel,
                    range_queue=range_queue,
                    on_block_received=_on_block,
                    stop_event=stop_event,
                    max_in_flight=3,
                    block_queue_size=200,
                )
```

Also update the import at ~line 485 from:

```python
from vibe.cardano.network.blockfetch_protocol import run_block_fetch_continuous
```

To:

```python
from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined
```

- [ ] **Step 2: Run existing blockfetch tests to verify no regressions**

Run: `.venv/bin/pytest tests/unit/test_blockfetch_protocol.py tests/unit/test_blockfetch_pipelined.py -xvs --timeout=30`
Expected: All PASS (existing tests use `run_block_fetch_continuous` / `BlockFetchClient` directly — they don't go through peer_manager)

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/pytest tests/ -x -q --timeout=60 --deselect tests/unit/test_chainsync_protocol.py::TestRunChainSync::test_sync_loop_empty_points_uses_origin`
Expected: 4,277+ passed, 0 failed

- [ ] **Step 4: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py
git commit -m "feat(m6.14): wire pipelined block-fetch into peer_manager sync pipeline

Prompt: Swap run_block_fetch_continuous for run_block_fetch_pipelined
in peer_manager._block_fetch_worker. max_in_flight=3, block_queue_size=200.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Integration test — Docker Compose benchmark

**Files:**
- No code changes — this is a benchmark run

- [ ] **Step 1: Wipe data and rebuild**

```bash
cd infra/preview-sync
docker compose -f docker-compose.preview-sync.yml down
docker volume rm preview-sync_vibe-preview-data
docker compose -f docker-compose.preview-sync.yml up -d --build vibe-node
```

- [ ] **Step 2: Wait 60 seconds and measure bps**

```bash
sleep 60
docker compose -f docker-compose.preview-sync.yml logs vibe-node --tail 5
```

Count blocks stored vs time elapsed. Baseline is ~30 bps from genesis.

- [ ] **Step 3: Wait another 60 seconds for steady-state measurement**

```bash
sleep 60
docker compose -f docker-compose.preview-sync.yml logs vibe-node --tail 5
```

- [ ] **Step 4: Check for errors**

```bash
docker compose -f docker-compose.preview-sync.yml logs vibe-node 2>&1 | grep -c "ERROR"
docker compose -f docker-compose.preview-sync.yml logs vibe-node 2>&1 | grep -i "error" | head -10
```

Expected: 0 errors, bps measurably above 30.

- [ ] **Step 5: Record results and commit**

If bps improved, commit the benchmark result as a note in the plan doc. If not, investigate and iterate on `max_in_flight` and `block_queue_size` parameters.
