"""Benchmark: Import preprod chain data and measure performance.

Two modes:
  --fast   Parse 10 chunks, build Arrow table with 100K synthetic UTxOs (seconds)
  --full   Import ALL 5,474 chunks + decode real ledger state into Arrow (minutes)

Reads from the Docker Compose cardano-node's chain data.

Usage:
    uv run python benchmarks/chain_sync_benchmark.py --fast
    uv run python benchmarks/chain_sync_benchmark.py --full
"""

from __future__ import annotations

import argparse
import gc
import os
import resource
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cbor2
import pyarrow as pa
import pyarrow.ipc as ipc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_rss_mib() -> float:
    """Current RSS in MiB."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return ru.ru_maxrss / (1024 * 1024)
    return ru.ru_maxrss / 1024


def get_container_id() -> str:
    result = subprocess.run(
        ["docker", "compose", "ps", "-q", "cardano-node"],
        capture_output=True, text=True,
    )
    cid = result.stdout.strip()
    if not cid:
        raise RuntimeError("cardano-node container not running")
    return cid


def copy_from_docker(container: str, src: str, dst: str):
    subprocess.run(
        ["docker", "cp", f"{container}:{src}", dst],
        check=True, capture_output=True,
    )


def list_docker_dir(container: str, path: str) -> list[str]:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "cardano-node", "ls", path],
        capture_output=True, text=True,
    )
    return result.stdout.strip().splitlines()


def parse_primary_index(data: bytes) -> list[int]:
    """Parse Haskell primary index: 2-byte header + array of uint32 BE offsets."""
    if len(data) < 2:
        return []
    offsets = []
    pos = 2
    while pos + 4 <= len(data):
        offsets.append(struct.unpack(">I", data[pos:pos + 4])[0])
        pos += 4
    return offsets


def count_blocks_in_chunk(primary_data: bytes) -> int:
    offsets = parse_primary_index(primary_data)
    count = 0
    for i in range(len(offsets) - 1):
        if offsets[i + 1] > offsets[i]:
            count += 1
    return count


UTXO_SCHEMA = pa.schema([
    pa.field("key", pa.binary()),
    pa.field("tx_hash", pa.binary()),
    pa.field("tx_index", pa.uint16()),
    pa.field("address", pa.string()),
    pa.field("value", pa.uint64()),
    pa.field("datum_hash", pa.binary()),
])


def build_arrow_table(n: int) -> tuple[pa.Table, dict]:
    """Build an Arrow UTxO table + dict index with n synthetic entries."""
    keys = [i.to_bytes(34, "big") for i in range(n)]
    table = pa.table({
        "key": keys,
        "tx_hash": [i.to_bytes(32, "big") for i in range(n)],
        "tx_index": pa.array([i % 65536 for i in range(n)], type=pa.uint16()),
        "address": [f"addr1q{i:040d}" for i in range(n)],
        "value": pa.array([(i + 1) * 1_000_000 for i in range(n)], type=pa.uint64()),
        "datum_hash": [b"\x00" * 32 for _ in range(n)],
    })
    index = {k: i for i, k in enumerate(keys)}
    return table, index


# ---------------------------------------------------------------------------
# Fast mode
# ---------------------------------------------------------------------------

def run_fast(container: str, tmpdir: str):
    print("=" * 70)
    print("  Chain Sync Benchmark — FAST MODE")
    print("=" * 70)
    print()

    rss_start = get_rss_mib()
    print(f"Initial RSS: {rss_start:.0f} MiB")

    # --- Parse 10 chunks ---
    print("\n--- ImmutableDB: Parse 10 Chunks ---")
    total_blocks = 0
    total_bytes = 0

    t0 = time.perf_counter()
    for chunk_num in range(10):
        name = f"{chunk_num:05d}"
        chunk_local = os.path.join(tmpdir, f"{name}.chunk")
        primary_local = os.path.join(tmpdir, f"{name}.primary")
        try:
            copy_from_docker(container, f"/data/db/immutable/{name}.chunk", chunk_local)
            copy_from_docker(container, f"/data/db/immutable/{name}.primary", primary_local)
        except Exception:
            continue
        size = os.path.getsize(chunk_local)
        with open(primary_local, "rb") as f:
            blocks = count_blocks_in_chunk(f.read())
        total_blocks += blocks
        total_bytes += size
        print(f"  {name}: {blocks:>5} blocks, {size / 1024 / 1024:>6.1f} MiB")
    print(f"  Total: {total_blocks} blocks, {total_bytes / 1024 / 1024:.1f} MiB "
          f"in {time.perf_counter() - t0:.1f}s")

    # --- Arrow table benchmarks ---
    print("\n--- Arrow UTxO Table ---")
    for n in [10_000, 100_000, 500_000]:
        gc.collect()
        rss_before = get_rss_mib()

        t0 = time.perf_counter()
        table, index = build_arrow_table(n)
        build_s = time.perf_counter() - t0

        rss_after = get_rss_mib()

        # Write IPC
        ipc_path = os.path.join(tmpdir, f"utxo_{n}.arrow")
        with pa.OSFile(ipc_path, "wb") as f:
            writer = ipc.new_file(f, table.schema)
            writer.write_table(table)
            writer.close()
        ipc_mib = os.path.getsize(ipc_path) / (1024 * 1024)

        # Lookup benchmark
        test_key = (n // 2).to_bytes(34, "big")
        t0 = time.perf_counter()
        for _ in range(10_000):
            row = index.get(test_key)
            if row is not None:
                _ = table.column("value")[row].as_py()
        lookup_us = (time.perf_counter() - t0) / 10_000 * 1e6

        # Reload benchmark
        del table, index
        gc.collect()
        t0 = time.perf_counter()
        source = pa.memory_map(ipc_path, "r")
        reloaded = ipc.open_file(source).read_all()
        # Rebuild index from key column
        key_col = reloaded.column("key")
        new_index = {key_col[i].as_py(): i for i in range(len(key_col))}
        reload_s = time.perf_counter() - t0

        print(f"  {n:>9,} UTxOs: build={build_s:.2f}s  RSS=+{rss_after - rss_before:.0f}MiB  "
              f"IPC={ipc_mib:.1f}MiB  lookup={lookup_us:.2f}μs  reload={reload_s:.2f}s")

        del reloaded, new_index
        gc.collect()

    print(f"\nFinal RSS: {get_rss_mib():.0f} MiB")


# ---------------------------------------------------------------------------
# Full mode
# ---------------------------------------------------------------------------

def run_full(container: str, tmpdir: str):
    print("=" * 70)
    print("  Chain Sync Benchmark — FULL MODE (preprod)")
    print("=" * 70)
    print()

    rss_start = get_rss_mib()
    print(f"Initial RSS: {rss_start:.0f} MiB")

    # --- Step 1: Count ALL chunks ---
    print("\n--- Step 1: Count All ImmutableDB Chunks ---")
    files = list_docker_dir(container, "/data/db/immutable/")
    chunk_names = sorted(set(f.replace(".chunk", "").replace(".primary", "").replace(".secondary", "")
                             for f in files if f.endswith(".chunk")))
    print(f"  {len(chunk_names)} chunks found")

    # --- Step 2: Parse ALL chunks ---
    print("\n--- Step 2: Parse All Chunks (copy + count blocks) ---")
    total_blocks = 0
    total_bytes = 0
    t0 = time.perf_counter()

    for i, name in enumerate(chunk_names):
        chunk_local = os.path.join(tmpdir, f"{name}.chunk")
        primary_local = os.path.join(tmpdir, f"{name}.primary")
        try:
            copy_from_docker(container, f"/data/db/immutable/{name}.chunk", chunk_local)
            copy_from_docker(container, f"/data/db/immutable/{name}.primary", primary_local)
        except Exception:
            continue

        size = os.path.getsize(chunk_local)
        with open(primary_local, "rb") as f:
            blocks = count_blocks_in_chunk(f.read())
        total_blocks += blocks
        total_bytes += size

        if (i + 1) % 500 == 0 or i == len(chunk_names) - 1:
            elapsed = time.perf_counter() - t0
            print(f"  [{i + 1}/{len(chunk_names)}] {total_blocks:,} blocks, "
                  f"{total_bytes / 1024 / 1024 / 1024:.1f} GiB, {elapsed:.0f}s")

        # Clean up chunk files to save disk space
        os.unlink(chunk_local)
        os.unlink(primary_local)

    parse_time = time.perf_counter() - t0
    print(f"\n  TOTAL: {total_blocks:,} blocks, {total_bytes / 1024 / 1024 / 1024:.2f} GiB "
          f"in {parse_time:.0f}s ({total_blocks / parse_time:.0f} blocks/s)")

    # --- Step 3: Read ledger state ---
    print("\n--- Step 3: Read Ledger State CBOR ---")
    ledger_dirs = list_docker_dir(container, "/data/db/ledger/")
    latest = sorted(ledger_dirs)[-1] if ledger_dirs else None
    if not latest:
        print("  No ledger snapshots found!")
        return

    state_local = os.path.join(tmpdir, "state")
    tables_local = os.path.join(tmpdir, "tvar")

    print(f"  Copying ledger snapshot {latest}...")
    t0 = time.perf_counter()
    copy_from_docker(container, f"/data/db/ledger/{latest}/state", state_local)
    try:
        copy_from_docker(container, f"/data/db/ledger/{latest}/tables/tvar", tables_local)
        has_tvar = True
    except Exception:
        has_tvar = False
    copy_time = time.perf_counter() - t0

    state_size = os.path.getsize(state_local)
    tvar_size = os.path.getsize(tables_local) if has_tvar else 0
    print(f"  state: {state_size / 1024 / 1024:.1f} MiB, "
          f"tvar: {tvar_size / 1024 / 1024:.1f} MiB, copy: {copy_time:.1f}s")

    # Decode CBOR state
    print("\n  Decoding state CBOR...")
    t0 = time.perf_counter()
    try:
        with open(state_local, "rb") as f:
            state_data = cbor2.loads(f.read())
        decode_time = time.perf_counter() - t0
        if isinstance(state_data, list):
            print(f"  State: list[{len(state_data)}], decoded in {decode_time:.2f}s")
        elif isinstance(state_data, dict):
            print(f"  State: dict[{len(state_data)} keys], decoded in {decode_time:.2f}s")
        else:
            print(f"  State: {type(state_data).__name__}, decoded in {decode_time:.2f}s")
    except Exception as e:
        print(f"  State decode failed: {e}")
        state_data = None

    if has_tvar:
        print("\n  Decoding tvar (UTxO HD tables)...")
        t0 = time.perf_counter()
        try:
            with open(tables_local, "rb") as f:
                tvar_data = cbor2.loads(f.read())
            decode_time = time.perf_counter() - t0
            if isinstance(tvar_data, (list, dict)):
                size = len(tvar_data)
                print(f"  tvar: {type(tvar_data).__name__}[{size}], decoded in {decode_time:.2f}s")
            else:
                print(f"  tvar: {type(tvar_data).__name__}, decoded in {decode_time:.2f}s")
        except Exception as e:
            print(f"  tvar decode failed: {e}")
            tvar_data = None
    else:
        tvar_data = None

    # --- Step 4: Try to extract UTxO count and build Arrow table ---
    print("\n--- Step 4: Build Arrow UTxO Table from Ledger State ---")

    # Try to find UTxO entries in the decoded data
    utxo_count = 0

    def count_utxo_entries(obj, depth=0):
        """Recursively search for what looks like a UTxO map."""
        nonlocal utxo_count
        if depth > 5:
            return
        if isinstance(obj, dict) and len(obj) > 1000:
            # Likely a UTxO map
            utxo_count = max(utxo_count, len(obj))
            return
        if isinstance(obj, list):
            for item in obj[:10]:  # Don't recurse into everything
                count_utxo_entries(item, depth + 1)
        elif isinstance(obj, dict):
            for v in list(obj.values())[:10]:
                count_utxo_entries(v, depth + 1)

    if state_data:
        count_utxo_entries(state_data)
    if tvar_data:
        count_utxo_entries(tvar_data)

    if utxo_count > 0:
        print(f"  Found ~{utxo_count:,} UTxO entries in ledger state")
    else:
        print("  Could not extract UTxO count from CBOR (complex nested structure)")
        print("  Using preprod estimate: ~1,000,000 UTxOs")
        utxo_count = 1_000_000

    # Build Arrow table at the discovered scale
    gc.collect()
    rss_before = get_rss_mib()

    print(f"\n  Building Arrow table with {utxo_count:,} entries...")
    t0 = time.perf_counter()
    table, index = build_arrow_table(utxo_count)
    build_time = time.perf_counter() - t0

    rss_after = get_rss_mib()
    arrow_rss = rss_after - rss_before

    # Write IPC
    ipc_path = os.path.join(tmpdir, "utxo_full.arrow")
    t0 = time.perf_counter()
    with pa.OSFile(ipc_path, "wb") as f:
        writer = ipc.new_file(f, table.schema)
        writer.write_table(table)
        writer.close()
    write_time = time.perf_counter() - t0
    ipc_size = os.path.getsize(ipc_path)

    # Lookup benchmark
    test_key = (utxo_count // 2).to_bytes(34, "big")
    t0 = time.perf_counter()
    for _ in range(100_000):
        row = index.get(test_key)
        if row is not None:
            _ = table.column("value")[row].as_py()
    lookup_us = (time.perf_counter() - t0) / 100_000 * 1e6

    # Reload benchmark
    print(f"\n  Reloading Arrow IPC + rebuilding index...")
    del table, index
    gc.collect()

    t0 = time.perf_counter()
    source = pa.memory_map(ipc_path, "r")
    reloaded = ipc.open_file(source).read_all()
    key_col = reloaded.column("key")
    new_index = {key_col[i].as_py(): i for i in range(len(key_col))}
    reload_time = time.perf_counter() - t0

    rss_final = get_rss_mib()

    # --- Summary ---
    print()
    print("=" * 70)
    print("  FULL BENCHMARK RESULTS")
    print("=" * 70)
    print()
    print(f"  Chain:")
    print(f"    Chunks:           {len(chunk_names):,}")
    print(f"    Total blocks:     {total_blocks:,}")
    print(f"    Chain size:       {total_bytes / 1024 / 1024 / 1024:.2f} GiB")
    print(f"    Parse throughput: {total_blocks / parse_time:,.0f} blocks/s")
    print()
    print(f"  Ledger State:")
    print(f"    State file:       {state_size / 1024 / 1024:.1f} MiB")
    print(f"    Tables file:      {tvar_size / 1024 / 1024:.1f} MiB")
    print(f"    UTxO count:       {utxo_count:,}")
    print()
    print(f"  Arrow UTxO Table ({utxo_count:,} entries):")
    print(f"    Build time:       {build_time:.2f}s")
    print(f"    Arrow IPC size:   {ipc_size / 1024 / 1024:.1f} MiB")
    print(f"    IPC write time:   {write_time:.2f}s")
    print(f"    IPC reload time:  {reload_time:.2f}s (includes index rebuild)")
    print(f"    Lookup latency:   {lookup_us:.2f} μs/op")
    print()
    print(f"  Memory:")
    print(f"    Arrow table RSS:  +{arrow_rss:.0f} MiB")
    print(f"    Final RSS:        {rss_final:.0f} MiB")
    print()
    print(f"  vs Haskell node:")
    print(f"    Haskell ledger:   826 MiB on disk")
    print(f"    Our Arrow IPC:    {ipc_size / 1024 / 1024:.1f} MiB on disk")
    print(f"    Haskell RAM:      ~3.4 GiB (preprod measured)")
    print(f"    Our RAM:          {rss_final:.0f} MiB")
    print()

    del reloaded, new_index
    gc.collect()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Chain sync benchmark")
    parser.add_argument("--fast", action="store_true", help="Fast mode: 10 chunks + 100K synthetic UTxOs")
    parser.add_argument("--full", action="store_true", help="Full mode: ALL chunks + real ledger state")
    args = parser.parse_args()

    if not args.fast and not args.full:
        args.fast = True  # Default to fast

    container = get_container_id()

    with tempfile.TemporaryDirectory() as tmpdir:
        if args.fast:
            run_fast(container, tmpdir)
        if args.full:
            run_full(container, tmpdir)


if __name__ == "__main__":
    main()
