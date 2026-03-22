#!/usr/bin/env python3
"""Benchmark CBOR serialization round-trips for hot-path data structures.

M6.3 Work Item 6.3: Measure CBOR encode + decode performance using cbor2pure,
the same library used by the node for all CBOR serialization.

Benchmark: 100K round-trips of a BlockHeader-like dataclass (11 fields).
Also verifies memory at scale (1M instances via tracemalloc).
"""

from __future__ import annotations

import gc
import sys
import time
import tracemalloc
from dataclasses import dataclass
from typing import Optional

import cbor2pure as cbor2


@dataclass(frozen=True, slots=True)
class BlockHeaderLike:
    """Representative hot-path dataclass matching real BlockHeader shape."""

    slot: int
    block_number: int
    prev_hash: Optional[bytes]
    issuer_vkey: bytes
    block_body_hash: bytes
    block_body_size: int
    era: int
    header_cbor: bytes
    vrf_output: Optional[bytes]
    proto_major: int
    proto_minor: int

    def to_cbor_list(self) -> list:
        """Serialize to a CBOR-friendly list (matches Cardano wire format)."""
        return [
            self.slot,
            self.block_number,
            self.prev_hash,
            self.issuer_vkey,
            self.block_body_hash,
            self.block_body_size,
            self.era,
            self.header_cbor,
            self.vrf_output,
            self.proto_major,
            self.proto_minor,
        ]

    @classmethod
    def from_cbor_list(cls, items: list) -> BlockHeaderLike:
        """Deserialize from a CBOR-decoded list."""
        return cls(
            slot=items[0],
            block_number=items[1],
            prev_hash=items[2],
            issuer_vkey=items[3],
            block_body_hash=items[4],
            block_body_size=items[5],
            era=items[6],
            header_cbor=items[7],
            vrf_output=items[8],
            proto_major=items[9],
            proto_minor=items[10],
        )


# Sample data matching real block header sizes
SAMPLE = BlockHeaderLike(
    slot=134_567_890,
    block_number=10_234_567,
    prev_hash=b"\xab" * 32,
    issuer_vkey=b"\xcd" * 32,
    block_body_hash=b"\xef" * 32,
    block_body_size=65535,
    era=7,
    header_cbor=b"\x00" * 200,
    vrf_output=b"\x11" * 64,
    proto_major=10,
    proto_minor=0,
)

N_ROUNDTRIPS = 100_000
WARMUP = 1_000


def bench_cbor_roundtrip(n: int = N_ROUNDTRIPS) -> dict:
    """Benchmark CBOR encode + decode for n round-trips."""
    cbor_list = SAMPLE.to_cbor_list()

    # Warmup
    for _ in range(WARMUP):
        encoded = cbor2.dumps(cbor_list)
        decoded = cbor2.loads(encoded)
        _ = BlockHeaderLike.from_cbor_list(decoded)

    # Pre-encode once to measure encode and decode separately
    sample_encoded = cbor2.dumps(cbor_list)

    # --- Encode benchmark ---
    gc.disable()
    t0 = time.perf_counter_ns()
    for _ in range(n):
        cbor2.dumps(cbor_list)
    encode_ns = time.perf_counter_ns() - t0
    gc.enable()

    # --- Decode benchmark ---
    gc.disable()
    t0 = time.perf_counter_ns()
    for _ in range(n):
        cbor2.loads(sample_encoded)
    decode_ns = time.perf_counter_ns() - t0
    gc.enable()

    # --- Full round-trip benchmark ---
    gc.disable()
    t0 = time.perf_counter_ns()
    for _ in range(n):
        encoded = cbor2.dumps(cbor_list)
        decoded = cbor2.loads(encoded)
        BlockHeaderLike.from_cbor_list(decoded)
    roundtrip_ns = time.perf_counter_ns() - t0
    gc.enable()

    return {
        "n": n,
        "encode_total_s": encode_ns / 1e9,
        "encode_per_ns": encode_ns / n,
        "decode_total_s": decode_ns / 1e9,
        "decode_per_ns": decode_ns / n,
        "roundtrip_total_s": roundtrip_ns / 1e9,
        "roundtrip_per_ns": roundtrip_ns / n,
        "cbor_size_bytes": len(sample_encoded),
    }


def bench_memory_at_scale(n: int = 1_000_000) -> dict:
    """Verify memory per instance at 1M scale using tracemalloc."""
    gc.collect()
    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    instances = [
        BlockHeaderLike(
            slot=134_567_890 + i,
            block_number=10_234_567 + i,
            prev_hash=b"\xab" * 32,
            issuer_vkey=b"\xcd" * 32,
            block_body_hash=b"\xef" * 32,
            block_body_size=65535,
            era=7,
            header_cbor=b"\x00" * 200,
            vrf_output=b"\x11" * 64,
            proto_major=10,
            proto_minor=0,
        )
        for i in range(n)
    ]

    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snap_after.compare_to(snap_before, "lineno")
    total_bytes = sum(s.size_diff for s in stats if s.size_diff > 0)
    per_instance = total_bytes / n

    # Prevent GC
    _ = instances

    return {
        "n": n,
        "total_bytes": total_bytes,
        "per_instance_bytes": per_instance,
    }


def run_all():
    """Run serialization benchmarks and print results."""
    print("=" * 72)
    print("M6.3 Serialization Benchmark — CBOR Round-Trip (cbor2pure)")
    print(f"Python {sys.version}")
    print("=" * 72)

    # --- CBOR round-trip ---
    print(f"\n--- CBOR Round-Trip ({N_ROUNDTRIPS:,} iterations) ---")
    r = bench_cbor_roundtrip()
    print(f"  CBOR payload size:      {r['cbor_size_bytes']} bytes")
    print(f"  Encode:  {r['encode_total_s']:.3f}s total, "
          f"{r['encode_per_ns']:.0f} ns/op")
    print(f"  Decode:  {r['decode_total_s']:.3f}s total, "
          f"{r['decode_per_ns']:.0f} ns/op")
    print(f"  Round-trip (encode+decode+reconstruct): "
          f"{r['roundtrip_total_s']:.3f}s total, "
          f"{r['roundtrip_per_ns']:.0f} ns/op")

    # --- Memory at 1M scale ---
    print(f"\n--- Memory at Scale (1M instances, tracemalloc) ---")
    m = bench_memory_at_scale()
    print(f"  Total allocated:   {m['total_bytes'] / 1e6:.1f} MB")
    print(f"  Per instance:      {m['per_instance_bytes']:.0f} bytes")

    print("\n" + "=" * 72)

    return {"cbor": r, "memory": m}


if __name__ == "__main__":
    results = run_all()
