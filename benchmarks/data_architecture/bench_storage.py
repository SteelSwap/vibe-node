"""
Storage engine benchmarks for vibe-node data architecture evaluation.

Compares DuckDB (columnar/Arrow), SQLite (row-based), and LMDB (key-value)
against Cardano node data access patterns:

  1. Bulk insert (simulating block processing / UTxO creation)
  2. Point lookup by key (simulating UTxO lookup by TxIn)
  3. Range scan (simulating address-based UTxO queries)
  4. Delete + insert (simulating UTxO consumption + creation per block)
  5. Memory footprint

Usage:
    uv run --with duckdb --with pyarrow --with lmdb \
        python benchmarks/data_architecture/bench_storage.py

Requires: duckdb, pyarrow, lmdb  (not project dependencies — benchmark only)
"""

from __future__ import annotations

import gc
import os
import random
import resource
import shutil
import sqlite3
import struct
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NUM_UTXOS = 200_000  # Total UTxO records to insert
LOOKUP_COUNT = 10_000  # Number of point lookups
SCAN_RESULTS = 500  # Approximate results per range scan
BLOCK_SIZE = 300  # UTxOs consumed+created per "block"
NUM_BLOCKS = 100  # Number of block-apply cycles

# Each UTxO record:
#   tx_hash  : 32 bytes
#   tx_index : 2 bytes  (uint16)
#   address  : 57 bytes (bech32-ish)
#   value    : 8 bytes  (uint64 lovelace)
#   datum_hash: 32 bytes (optional, but we always store for uniformity)
# Total ~131 bytes per record — realistic for Cardano UTxO entries.

ADDR_PREFIXES = [f"addr1q{i:04d}" for i in range(400)]  # 400 distinct prefixes


def generate_utxo_records(n: int, offset: int = 0) -> list[tuple[bytes, int, str, int, bytes]]:
    """Generate n fake UTxO records deterministically from offset."""
    rng = random.Random(42 + offset)
    records = []
    for i in range(n):
        tx_hash = rng.randbytes(32)
        tx_index = rng.randint(0, 65535)
        prefix = rng.choice(ADDR_PREFIXES)
        address = prefix + rng.randbytes(25).hex()[:50]
        value = rng.randint(1_000_000, 500_000_000_000)  # 1 ADA to 500k ADA
        datum_hash = rng.randbytes(32)
        records.append((tx_hash, tx_index, address, value, datum_hash))
    return records


def make_key(tx_hash: bytes, tx_index: int) -> bytes:
    """Pack a UTxO key: 32-byte tx_hash + 2-byte big-endian index."""
    return tx_hash + struct.pack(">H", tx_index)


def rss_mb() -> float:
    """Current RSS in MiB (macOS / Linux)."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    # macOS reports in bytes, Linux in KiB
    if "darwin" in os.uname().sysname.lower():
        return ru.ru_maxrss / (1024 * 1024)
    return ru.ru_maxrss / 1024


@dataclass
class BenchResult:
    engine: str
    bulk_insert_s: float = 0.0
    point_lookup_s: float = 0.0
    range_scan_s: float = 0.0
    block_apply_s: float = 0.0
    rss_after_mb: float = 0.0
    db_size_mb: float = 0.0
    extra: dict = field(default_factory=dict)

    def summary_row(self) -> str:
        return (
            f"| {self.engine:<10} "
            f"| {self.bulk_insert_s:>8.3f}s "
            f"| {self.point_lookup_s:>8.3f}s "
            f"| {self.range_scan_s:>8.3f}s "
            f"| {self.block_apply_s:>8.3f}s "
            f"| {self.rss_after_mb:>8.1f} MiB "
            f"| {self.db_size_mb:>8.1f} MiB |"
        )


# ===================================================================
# SQLite benchmark
# ===================================================================

def bench_sqlite(records, lookup_keys, scan_prefix, tmpdir) -> BenchResult:
    result = BenchResult(engine="SQLite")
    db_path = os.path.join(tmpdir, "bench.sqlite3")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")  # 256 MiB
    conn.execute("PRAGMA cache_size=-65536")  # 64 MiB
    conn.execute("""
        CREATE TABLE utxo (
            tx_hash BLOB NOT NULL,
            tx_index INTEGER NOT NULL,
            address TEXT NOT NULL,
            value INTEGER NOT NULL,
            datum_hash BLOB,
            PRIMARY KEY (tx_hash, tx_index)
        )
    """)
    conn.execute("CREATE INDEX idx_utxo_address ON utxo(address)")

    # Bulk insert
    gc.collect()
    t0 = time.perf_counter()
    conn.executemany(
        "INSERT INTO utxo VALUES (?, ?, ?, ?, ?)", records
    )
    conn.commit()
    result.bulk_insert_s = time.perf_counter() - t0

    # Point lookups
    gc.collect()
    t0 = time.perf_counter()
    for tx_hash, tx_index in lookup_keys:
        conn.execute(
            "SELECT * FROM utxo WHERE tx_hash=? AND tx_index=?",
            (tx_hash, tx_index),
        ).fetchone()
    result.point_lookup_s = time.perf_counter() - t0

    # Range scan (address prefix)
    gc.collect()
    t0 = time.perf_counter()
    rows = conn.execute(
        "SELECT * FROM utxo WHERE address LIKE ?", (scan_prefix + "%",)
    ).fetchall()
    result.range_scan_s = time.perf_counter() - t0
    result.extra["scan_rows"] = len(rows)

    # Block apply: delete BLOCK_SIZE random UTxOs, insert BLOCK_SIZE new ones
    gc.collect()
    t0 = time.perf_counter()
    rng = random.Random(99)
    for _blk in range(NUM_BLOCKS):
        # Delete
        to_delete = rng.sample(records, min(BLOCK_SIZE, len(records)))
        conn.executemany(
            "DELETE FROM utxo WHERE tx_hash=? AND tx_index=?",
            [(r[0], r[1]) for r in to_delete],
        )
        # Insert new
        new_recs = generate_utxo_records(BLOCK_SIZE, offset=_blk * 1000)
        conn.executemany("INSERT OR IGNORE INTO utxo VALUES (?, ?, ?, ?, ?)", new_recs)
        conn.commit()
    result.block_apply_s = time.perf_counter() - t0

    result.rss_after_mb = rss_mb()
    conn.close()
    result.db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    # Include WAL + SHM if present
    for suffix in ["-wal", "-shm"]:
        p = db_path + suffix
        if os.path.exists(p):
            result.db_size_mb += os.path.getsize(p) / (1024 * 1024)
    return result


# ===================================================================
# DuckDB benchmark
# ===================================================================

def bench_duckdb(records, lookup_keys, scan_prefix, tmpdir) -> BenchResult:
    import duckdb

    result = BenchResult(engine="DuckDB")
    db_path = os.path.join(tmpdir, "bench.duckdb")

    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE utxo (
            tx_hash BLOB NOT NULL,
            tx_index USMALLINT NOT NULL,
            address VARCHAR NOT NULL,
            value UBIGINT NOT NULL,
            datum_hash BLOB,
            PRIMARY KEY (tx_hash, tx_index)
        )
    """)

    # Bulk insert — batch via Arrow for best DuckDB perf
    import pyarrow as pa

    tx_hashes = [r[0] for r in records]
    tx_indices = [r[1] for r in records]
    addresses = [r[2] for r in records]
    values = [r[3] for r in records]
    datum_hashes = [r[4] for r in records]

    arrow_tbl = pa.table({
        "tx_hash": pa.array(tx_hashes, type=pa.binary()),
        "tx_index": pa.array(tx_indices, type=pa.uint16()),
        "address": pa.array(addresses, type=pa.string()),
        "value": pa.array(values, type=pa.uint64()),
        "datum_hash": pa.array(datum_hashes, type=pa.binary()),
    })

    gc.collect()
    t0 = time.perf_counter()
    conn.execute("INSERT INTO utxo SELECT * FROM arrow_tbl")
    result.bulk_insert_s = time.perf_counter() - t0

    # Point lookups
    gc.collect()
    t0 = time.perf_counter()
    for tx_hash, tx_index in lookup_keys:
        conn.execute(
            "SELECT * FROM utxo WHERE tx_hash=$1 AND tx_index=$2",
            [tx_hash, tx_index],
        ).fetchone()
    result.point_lookup_s = time.perf_counter() - t0

    # Range scan
    gc.collect()
    t0 = time.perf_counter()
    rows = conn.execute(
        "SELECT * FROM utxo WHERE address LIKE $1", [scan_prefix + "%"]
    ).fetchall()
    result.range_scan_s = time.perf_counter() - t0
    result.extra["scan_rows"] = len(rows)

    # Block apply
    gc.collect()
    t0 = time.perf_counter()
    rng = random.Random(99)
    for _blk in range(NUM_BLOCKS):
        to_delete = rng.sample(records, min(BLOCK_SIZE, len(records)))
        for r in to_delete:
            conn.execute(
                "DELETE FROM utxo WHERE tx_hash=$1 AND tx_index=$2",
                [r[0], r[1]],
            )
        new_recs = generate_utxo_records(BLOCK_SIZE, offset=_blk * 1000)
        new_table = pa.table({
            "tx_hash": pa.array([r[0] for r in new_recs], type=pa.binary()),
            "tx_index": pa.array([r[1] for r in new_recs], type=pa.uint16()),
            "address": pa.array([r[2] for r in new_recs], type=pa.string()),
            "value": pa.array([r[3] for r in new_recs], type=pa.uint64()),
            "datum_hash": pa.array([r[4] for r in new_recs], type=pa.binary()),
        })
        conn.execute("INSERT OR IGNORE INTO utxo SELECT * FROM new_table")
    result.block_apply_s = time.perf_counter() - t0

    result.rss_after_mb = rss_mb()
    conn.close()

    # Measure DB size
    result.db_size_mb = 0
    for f in Path(tmpdir).glob("bench.duckdb*"):
        result.db_size_mb += f.stat().st_size / (1024 * 1024)
    return result


# ===================================================================
# LMDB benchmark
# ===================================================================

def bench_lmdb(records, lookup_keys, scan_prefix, tmpdir) -> BenchResult:
    import lmdb

    result = BenchResult(engine="LMDB")
    db_path = os.path.join(tmpdir, "bench.lmdb")

    # 2 GiB map size — LMDB requires pre-declared maximum
    env = lmdb.open(db_path, map_size=2 * 1024 * 1024 * 1024, max_dbs=2)

    # Two sub-databases: utxo (key -> value) and addr_idx (address_prefix -> keys)
    utxo_db = env.open_db(b"utxo")
    addr_db = env.open_db(b"addr_idx", dupsort=True)

    # Bulk insert
    gc.collect()
    t0 = time.perf_counter()
    with env.begin(write=True) as txn:
        for tx_hash, tx_index, address, value, datum_hash in records:
            key = make_key(tx_hash, tx_index)
            # Value: address (variable) + 8-byte value + 32-byte datum_hash
            val = address.encode("utf-8") + struct.pack(">Q", value) + datum_hash
            txn.put(key, val, db=utxo_db)
            # Secondary index: address prefix (first 14 chars) -> key
            txn.put(address[:14].encode("utf-8"), key, db=addr_db)
    result.bulk_insert_s = time.perf_counter() - t0

    # Point lookups
    gc.collect()
    t0 = time.perf_counter()
    with env.begin(buffers=True) as txn:
        for tx_hash, tx_index in lookup_keys:
            key = make_key(tx_hash, tx_index)
            txn.get(key, db=utxo_db)
    result.point_lookup_s = time.perf_counter() - t0

    # Range scan (address prefix via secondary index)
    gc.collect()
    t0 = time.perf_counter()
    scan_key = scan_prefix[:14].encode("utf-8")
    found = 0
    with env.begin(buffers=True) as txn:
        cursor = txn.cursor(db=addr_db)
        if cursor.set_range(scan_key):
            for addr_key, utxo_key in cursor:
                if not bytes(addr_key).startswith(scan_key):
                    break
                # Fetch the actual UTxO record
                txn.get(bytes(utxo_key), db=utxo_db)
                found += 1
    result.range_scan_s = time.perf_counter() - t0
    result.extra["scan_rows"] = found

    # Block apply
    gc.collect()
    t0 = time.perf_counter()
    rng = random.Random(99)
    for _blk in range(NUM_BLOCKS):
        with env.begin(write=True) as txn:
            to_delete = rng.sample(records, min(BLOCK_SIZE, len(records)))
            for r in to_delete:
                key = make_key(r[0], r[1])
                txn.delete(key, db=utxo_db)
                txn.delete(r[2][:14].encode("utf-8"), key, db=addr_db)
            new_recs = generate_utxo_records(BLOCK_SIZE, offset=_blk * 1000)
            for tx_hash, tx_index, address, value, datum_hash in new_recs:
                key = make_key(tx_hash, tx_index)
                val = address.encode("utf-8") + struct.pack(">Q", value) + datum_hash
                txn.put(key, val, db=utxo_db)
                txn.put(address[:14].encode("utf-8"), key, db=addr_db)
    result.block_apply_s = time.perf_counter() - t0

    result.rss_after_mb = rss_mb()
    env.close()

    # Measure DB size
    result.db_size_mb = 0
    for f in Path(db_path).iterdir():
        result.db_size_mb += f.stat().st_size / (1024 * 1024)
    return result


# ===================================================================
# Main
# ===================================================================

def main():
    print(f"Generating {NUM_UTXOS:,} fake UTxO records...")
    records = generate_utxo_records(NUM_UTXOS)

    # Pick random lookup keys from inserted records
    rng = random.Random(77)
    lookup_keys = [(r[0], r[1]) for r in rng.sample(records, LOOKUP_COUNT)]

    # Pick an address prefix that should match ~500 records (NUM_UTXOS / 400 prefixes)
    scan_prefix = ADDR_PREFIXES[42]

    print(f"Lookup keys: {LOOKUP_COUNT:,}, scan prefix: {scan_prefix!r}")
    print(f"Block apply: {NUM_BLOCKS} blocks x {BLOCK_SIZE} UTxOs each\n")

    results = []

    # --- SQLite ---
    print("=== SQLite (WAL mode) ===")
    tmpdir = tempfile.mkdtemp(prefix="bench_sqlite_")
    try:
        r = bench_sqlite(records, lookup_keys, scan_prefix, tmpdir)
        results.append(r)
        print(f"  Bulk insert:  {r.bulk_insert_s:.3f}s")
        print(f"  Point lookup: {r.point_lookup_s:.3f}s ({LOOKUP_COUNT} lookups)")
        print(f"  Range scan:   {r.range_scan_s:.3f}s ({r.extra['scan_rows']} rows)")
        print(f"  Block apply:  {r.block_apply_s:.3f}s ({NUM_BLOCKS} blocks)")
        print(f"  DB size:      {r.db_size_mb:.1f} MiB")
        print(f"  RSS:          {r.rss_after_mb:.1f} MiB")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # --- DuckDB ---
    print("\n=== DuckDB (Arrow insert) ===")
    tmpdir = tempfile.mkdtemp(prefix="bench_duckdb_")
    try:
        r = bench_duckdb(records, lookup_keys, scan_prefix, tmpdir)
        results.append(r)
        print(f"  Bulk insert:  {r.bulk_insert_s:.3f}s")
        print(f"  Point lookup: {r.point_lookup_s:.3f}s ({LOOKUP_COUNT} lookups)")
        print(f"  Range scan:   {r.range_scan_s:.3f}s ({r.extra['scan_rows']} rows)")
        print(f"  Block apply:  {r.block_apply_s:.3f}s ({NUM_BLOCKS} blocks)")
        print(f"  DB size:      {r.db_size_mb:.1f} MiB")
        print(f"  RSS:          {r.rss_after_mb:.1f} MiB")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # --- LMDB ---
    print("\n=== LMDB ===")
    tmpdir = tempfile.mkdtemp(prefix="bench_lmdb_")
    try:
        r = bench_lmdb(records, lookup_keys, scan_prefix, tmpdir)
        results.append(r)
        print(f"  Bulk insert:  {r.bulk_insert_s:.3f}s")
        print(f"  Point lookup: {r.point_lookup_s:.3f}s ({LOOKUP_COUNT} lookups)")
        print(f"  Range scan:   {r.range_scan_s:.3f}s ({r.extra['scan_rows']} rows)")
        print(f"  Block apply:  {r.block_apply_s:.3f}s ({NUM_BLOCKS} blocks)")
        print(f"  DB size:      {r.db_size_mb:.1f} MiB")
        print(f"  RSS:          {r.rss_after_mb:.1f} MiB")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # --- Summary table ---
    print("\n" + "=" * 100)
    print("SUMMARY (200K UTxOs, 10K lookups, 100 block-apply cycles)")
    print("=" * 100)
    header = (
        f"| {'Engine':<10} "
        f"| {'Insert':>9} "
        f"| {'Lookup':>9} "
        f"| {'Scan':>9} "
        f"| {'BlockApply':>10} "
        f"| {'RSS':>12} "
        f"| {'DB Size':>12} |"
    )
    print(header)
    print("|" + "-" * (len(header) - 2) + "|")
    for r in results:
        print(r.summary_row())
    print()


if __name__ == "__main__":
    main()
