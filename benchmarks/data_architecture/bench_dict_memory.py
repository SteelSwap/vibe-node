"""
Memory-efficient dictionary alternatives for UTxO index.

The Arrow+Dict architecture uses a Python dict mapping TxIn → row index.
At 15M mainnet UTxOs, Python dict uses ~2 GiB (144 bytes/entry).
This benchmark tests alternatives to reduce that overhead.

Approaches tested:
  1. Python dict {bytes: int}        — baseline
  2. Python dict {int: int}          — hash TxIn to 8-byte int key
  3. NumPy open-addressing hash table — typed arrays, no Python object overhead
  4. Array-based sorted + bisect     — sorted keys with binary search

Usage:
    uv run python benchmarks/data_architecture/bench_dict_memory.py [--scale 1000000]
"""

from __future__ import annotations

import gc
import hashlib
import os
import resource
import struct
import sys
import time
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_SCALE = 1_000_000  # 1M entries (use --scale for more)
LOOKUP_COUNT = 100_000


def get_rss_mib() -> float:
    """Current RSS in MiB (macOS/Linux)."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return ru.ru_maxrss / (1024 * 1024)  # bytes on macOS
    return ru.ru_maxrss / 1024  # KiB on Linux


def make_txin_keys(n: int) -> list[bytes]:
    """Generate n realistic TxIn keys (32-byte hash + 2-byte index)."""
    keys = []
    for i in range(n):
        tx_hash = hashlib.sha256(i.to_bytes(8, "little")).digest()
        tx_idx = struct.pack(">H", i % 65536)
        keys.append(tx_hash + tx_idx)
    return keys


def txin_to_int(key: bytes) -> int:
    """Hash a 34-byte TxIn to a 64-bit integer (for int-key dict)."""
    # Use first 8 bytes of SHA-256 hash of the TxIn as key
    # Collision probability for 15M entries: ~1 in 10^8 (birthday bound)
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "little")


# ---------------------------------------------------------------------------
# 1. Python dict {bytes: int}
# ---------------------------------------------------------------------------

def bench_dict_bytes(keys: list[bytes], lookup_keys: list[bytes]) -> dict:
    gc.collect()
    rss_before = get_rss_mib()

    t0 = time.perf_counter()
    d = {}
    for i, k in enumerate(keys):
        d[k] = i
    t_insert = time.perf_counter() - t0

    rss_after = get_rss_mib()

    t0 = time.perf_counter()
    hits = 0
    for k in lookup_keys:
        if k in d:
            _ = d[k]
            hits += 1
    t_lookup = time.perf_counter() - t0

    return {
        "name": "dict{bytes:int}",
        "insert_s": t_insert,
        "lookup_s": t_lookup,
        "lookup_us": t_lookup / len(lookup_keys) * 1e6,
        "rss_mib": rss_after - rss_before,
        "rss_after_mib": rss_after,
        "entries": len(d),
        "hits": hits,
        "bytes_per_entry": (rss_after - rss_before) * 1024 * 1024 / len(d) if len(d) > 0 else 0,
    }


# ---------------------------------------------------------------------------
# 2. Python dict {int: int}
# ---------------------------------------------------------------------------

def bench_dict_int(keys: list[bytes], lookup_keys: list[bytes]) -> dict:
    gc.collect()
    rss_before = get_rss_mib()

    int_keys = [txin_to_int(k) for k in keys]
    int_lookup = [txin_to_int(k) for k in lookup_keys]

    t0 = time.perf_counter()
    d = {}
    for i, k in enumerate(int_keys):
        d[k] = i
    t_insert = time.perf_counter() - t0

    rss_after = get_rss_mib()

    t0 = time.perf_counter()
    hits = 0
    for k in int_lookup:
        if k in d:
            _ = d[k]
            hits += 1
    t_lookup = time.perf_counter() - t0

    return {
        "name": "dict{int:int}",
        "insert_s": t_insert,
        "lookup_s": t_lookup,
        "lookup_us": t_lookup / len(lookup_keys) * 1e6,
        "rss_mib": rss_after - rss_before,
        "rss_after_mib": rss_after,
        "entries": len(d),
        "hits": hits,
        "bytes_per_entry": (rss_after - rss_before) * 1024 * 1024 / len(d) if len(d) > 0 else 0,
    }


# ---------------------------------------------------------------------------
# 3. NumPy open-addressing hash table (Robin Hood hashing)
# ---------------------------------------------------------------------------

class NumpyHashTable:
    """
    Open-addressing hash table using NumPy arrays.

    Keys: uint64 (hashed TxIn)
    Values: int32 (row index, supports up to 2B rows)

    Memory per slot: 8 (key) + 4 (value) + 1 (occupied flag) = 13 bytes
    With 75% load factor: ~17.3 bytes per entry
    vs Python dict: ~144 bytes per entry → 8.3x reduction
    """

    EMPTY = np.uint64(0)

    def __init__(self, capacity: int):
        # Round up to power of 2 for fast modulo
        self.capacity = 1
        while self.capacity < capacity:
            self.capacity <<= 1
        self.mask = np.uint64(self.capacity - 1)
        self.keys = np.zeros(self.capacity, dtype=np.uint64)
        self.values = np.zeros(self.capacity, dtype=np.int32)
        self.occupied = np.zeros(self.capacity, dtype=np.bool_)
        self.size = 0

    def _probe(self, key: int) -> int:
        idx = int(np.uint64(key) & self.mask)
        while self.occupied[idx]:
            if self.keys[idx] == key:
                return idx
            idx = (idx + 1) & int(self.mask)
        return idx

    def insert(self, key: int, value: int) -> None:
        idx = self._probe(key)
        if not self.occupied[idx]:
            self.size += 1
        self.keys[idx] = key
        self.values[idx] = value
        self.occupied[idx] = True

    def get(self, key: int) -> Optional[int]:
        idx = int(np.uint64(key) & self.mask)
        while self.occupied[idx]:
            if self.keys[idx] == key:
                return int(self.values[idx])
            idx = (idx + 1) & int(self.mask)
        return None

    def memory_bytes(self) -> int:
        return (
            self.keys.nbytes
            + self.values.nbytes
            + self.occupied.nbytes
        )


def bench_numpy_ht(keys: list[bytes], lookup_keys: list[bytes]) -> dict:
    gc.collect()
    rss_before = get_rss_mib()

    # Pre-hash all keys
    int_keys = [txin_to_int(k) for k in keys]
    int_lookup = [txin_to_int(k) for k in lookup_keys]

    # Capacity = entries / 0.75 load factor
    capacity = int(len(keys) / 0.75) + 1

    t0 = time.perf_counter()
    ht = NumpyHashTable(capacity)
    for i, k in enumerate(int_keys):
        ht.insert(k, i)
    t_insert = time.perf_counter() - t0

    rss_after = get_rss_mib()

    t0 = time.perf_counter()
    hits = 0
    for k in int_lookup:
        v = ht.get(k)
        if v is not None:
            hits += 1
    t_lookup = time.perf_counter() - t0

    array_mib = ht.memory_bytes() / (1024 * 1024)

    return {
        "name": "numpy_ht{u64:i32}",
        "insert_s": t_insert,
        "lookup_s": t_lookup,
        "lookup_us": t_lookup / len(lookup_keys) * 1e6,
        "rss_mib": rss_after - rss_before,
        "rss_after_mib": rss_after,
        "array_mib": array_mib,
        "entries": ht.size,
        "hits": hits,
        "bytes_per_entry": ht.memory_bytes() / ht.size if ht.size > 0 else 0,
        "capacity": ht.capacity,
        "load_factor": ht.size / ht.capacity,
    }


# ---------------------------------------------------------------------------
# 4. NumPy sorted array + binary search
# ---------------------------------------------------------------------------

def bench_sorted_array(keys: list[bytes], lookup_keys: list[bytes]) -> dict:
    gc.collect()
    rss_before = get_rss_mib()

    # Hash keys to uint64
    int_keys = np.array([txin_to_int(k) for k in keys], dtype=np.uint64)
    int_lookup = np.array([txin_to_int(k) for k in lookup_keys], dtype=np.uint64)

    t0 = time.perf_counter()
    # Sort and create paired value array
    sort_idx = np.argsort(int_keys)
    sorted_keys = int_keys[sort_idx]
    sorted_vals = np.arange(len(keys), dtype=np.int32)[sort_idx]
    t_insert = time.perf_counter() - t0

    rss_after = get_rss_mib()

    t0 = time.perf_counter()
    hits = 0
    for k in int_lookup:
        idx = np.searchsorted(sorted_keys, k)
        if idx < len(sorted_keys) and sorted_keys[idx] == k:
            _ = sorted_vals[idx]
            hits += 1
    t_lookup = time.perf_counter() - t0

    array_mib = (sorted_keys.nbytes + sorted_vals.nbytes) / (1024 * 1024)

    return {
        "name": "sorted_array{u64:i32}",
        "insert_s": t_insert,
        "lookup_s": t_lookup,
        "lookup_us": t_lookup / len(lookup_keys) * 1e6,
        "rss_mib": rss_after - rss_before,
        "rss_after_mib": rss_after,
        "array_mib": array_mib,
        "entries": len(sorted_keys),
        "hits": hits,
        "bytes_per_entry": (sorted_keys.nbytes + sorted_vals.nbytes) / len(sorted_keys),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Dict memory benchmark")
    parser.add_argument("--scale", type=int, default=DEFAULT_SCALE,
                        help=f"Number of entries (default: {DEFAULT_SCALE:,})")
    args = parser.parse_args()

    n = args.scale
    lookups = min(LOOKUP_COUNT, n)

    print(f"{'='*70}")
    print(f"  Dictionary Memory Benchmark — {n:,} entries, {lookups:,} lookups")
    print(f"{'='*70}")
    print()

    print("Generating keys...")
    keys = make_txin_keys(n)
    lookup_keys = keys[:lookups]  # lookup existing keys (100% hit rate)
    print(f"  Key size: {len(keys[0])} bytes (32B hash + 2B index)")
    print()

    results = []

    # Run each benchmark, cleaning up between runs
    for bench_fn in [bench_dict_bytes, bench_dict_int, bench_numpy_ht, bench_sorted_array]:
        print(f"Running {bench_fn.__name__}...")
        r = bench_fn(keys, lookup_keys)
        results.append(r)
        print(f"  Done: {r['rss_mib']:.1f} MiB RSS, {r['lookup_us']:.2f} μs/lookup")
        # Force cleanup
        gc.collect()
        print()

    # Summary table
    print(f"{'='*70}")
    print(f"  Results Summary")
    print(f"{'='*70}")
    print()
    print(f"{'Approach':<25} {'Insert(s)':>10} {'Lookup(μs)':>11} {'RSS(MiB)':>10} {'B/entry':>8} {'Hits':>8}")
    print(f"{'-'*25} {'-'*10} {'-'*11} {'-'*10} {'-'*8} {'-'*8}")
    for r in results:
        print(
            f"{r['name']:<25} "
            f"{r['insert_s']:>10.3f} "
            f"{r['lookup_us']:>11.2f} "
            f"{r['rss_mib']:>10.1f} "
            f"{r['bytes_per_entry']:>8.1f} "
            f"{r['hits']:>8,}"
        )
    print()

    # Extrapolation to 15M mainnet UTxOs
    print(f"{'='*70}")
    print(f"  Extrapolation to 15M mainnet UTxOs")
    print(f"{'='*70}")
    print()
    for r in results:
        bpe = r["bytes_per_entry"]
        est_mib = bpe * 15_000_000 / (1024 * 1024)
        print(f"  {r['name']:<25} → {est_mib:>8.0f} MiB ({est_mib/1024:.1f} GiB) index only")
    print()
    print("  Note: Add ~2.6 GiB for Arrow table data at 15M UTxOs")


if __name__ == "__main__":
    main()
