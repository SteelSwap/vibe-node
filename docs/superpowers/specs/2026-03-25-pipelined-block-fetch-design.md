# Pipelined Block-Fetch Design

**Goal:** Eliminate batch boundary dead time and decouple block processing from network receive in the block-fetch pipeline, increasing sync throughput beyond the current ~30 bps baseline.

**Covers:** M6.14 Task 6 (Pipeline block-fetch range requests) and Task 7 (Decouple block storage from block-fetch loop).

## Problem

The current block-fetch pipeline is sequential:

```
send RequestRange → RTT wait → recv StartBatch → [recv Block + _on_block] × N → recv BatchDone
                                                                                      |
send RequestRange → RTT wait → recv StartBatch → [recv Block + _on_block] × N → ...
```

Two sources of dead time:

1. **Batch boundary RTT (~50-200ms per batch):** After `BatchDone`, the code loops back, pulls a range from the queue, sends `MsgRequestRange`, and waits for `MsgStartBatch`. During this round trip, zero blocks flow.

2. **Inline block processing:** `_on_block` (decode, validate, store in ChainDB) runs synchronously between `recv_message()` calls. While a block is being processed, the next block isn't being received. The mux buffers help, but slow processing can stall the mux sender (shared connection with chain-sync).

The Haskell node solves both: block-fetch uses `YieldPipelined` / `Collect` to overlap range requests, and `addBlockRunner` processes blocks on a dedicated background thread via a `TBQueue`.

## Architecture

Three concurrent asyncio tasks sharing one mux channel and two queues:

```
range_queue ──→ [SENDER] ──→ mux channel ──→ [RECEIVER] ──→ block_queue ──→ [PROCESSOR]
                  │                              │                              │
           encodes & sends              decodes responses              _on_block (decode,
           MsgRequestRange              dispatches blocks              validate, store)
           tracks in_flight             to block_queue
```

- **Sender**: Pulls `(point_from, point_to)` from `range_queue`, encodes `MsgRequestRange`, sends on raw channel. Tracks `in_flight_batches` (capped at 3). When at max, awaits a signal from the receiver.
- **Receiver**: Reads raw bytes from channel, does CBOR boundary finding + decode. For `MsgBlock`, puts `block_cbor` onto `block_queue`. For `BatchDone`/`NoBlocks`, decrements `in_flight_batches` and signals the sender.
- **Processor**: Pulls `block_cbor` from `block_queue`, runs the existing `_on_block` logic unchanged.

## Concurrency Control & Backpressure

- **`in_flight_batches`**: Max 3 outstanding range requests. Sender increments on send, receiver decrements on `BatchDone` or `NoBlocks`. Sender awaits an `asyncio.Event` when at max; receiver sets the event on decrement.
- **`block_queue`**: Bounded `asyncio.Queue(maxsize=200)`. Receiver does `await block_queue.put()` — if the processor is slow, the receiver blocks, creating natural backpressure on the mux channel read.
- **`range_queue`**: Unchanged — the existing `_range_builder` feeds it.

## Shutdown

All three tasks check `stop_event`:
- Sender stops sending new ranges
- Receiver drains remaining responses
- Processor drains `block_queue` then exits

Structure: sender and processor are `asyncio.create_task()`, receiver runs in the main coroutine (same pattern as pipelined chain-sync). `finally` block cancels sender and processor.

If any task raises, it sets `stop_event` and logs the error. Other tasks see the event and exit cleanly.

## Wire Format & CBOR Handling

Sender and receiver work with raw bytes on the mux channel, bypassing `ProtocolRunner` (same pattern as pipelined chain-sync).

**Sender encodes** using existing functions from `blockfetch.py`:
- `encode_request_range(point_from, point_to)`
- `encode_client_done()` on shutdown

**Receiver decodes** using the chain-sync CBOR boundary pattern:
- `CBORDecoder` on `BytesIO`, track consumed vs remainder in `_recv_buf`
- Decode outer array to get `msg_id`
- `msg_id == 4` (Block): extract `block_cbor`, put on `block_queue`
- `msg_id == 2` (StartBatch): no-op
- `msg_id == 5` (BatchDone): decrement `in_flight_batches`, signal sender
- `msg_id == 3` (NoBlocks): decrement `in_flight_batches`, signal sender

**SDU reassembly**: Same pattern as `ProtocolRunner.recv_message()` — if CBOR decode fails with truncation error, read another segment and retry.

## Code Changes

**New function** in `blockfetch_protocol.py`:

```python
async def run_block_fetch_pipelined(
    channel: MiniProtocolChannel,
    range_queue: asyncio.Queue,
    on_block_received: OnBlockReceived,
    on_no_blocks: OnNoBlocks | None = None,
    *,
    stop_event: asyncio.Event | None = None,
    max_in_flight: int = 3,
    block_queue_size: int = 200,
) -> None:
```

**One call site change** in `peer_manager.py` (~line 791): swap `run_block_fetch_continuous` for `run_block_fetch_pipelined`.

**No changes to**: `runner.py`, `mux.py`, `blockfetch.py`, `chaindb.py`, `volatile.py`, or the existing `run_block_fetch_continuous` / `BlockFetchClient` code.

## Testing

**Unit test**: Mock mux channel (`FakeChannel`). Verify:
- Sender sends multiple `MsgRequestRange` before any `BatchDone` (confirms pipelining)
- Receiver dispatches blocks to `block_queue`
- Processor calls `on_block_received` for each block
- `in_flight_batches` never exceeds `max_in_flight`
- Clean shutdown (no hanging tasks)

**Integration test**: Run against Docker Compose Haskell node on Preview. Measure bps improvement over ~30 bps baseline.

**Existing tests**: All 151 blockfetch tests stay green — `run_block_fetch_continuous` and `BlockFetchClient` are untouched.

## Success Criteria

Preview sync bps measurably above 30 (baseline from same chain region). Any improvement confirms the batch boundary RTT and inline processing were real bottlenecks.
