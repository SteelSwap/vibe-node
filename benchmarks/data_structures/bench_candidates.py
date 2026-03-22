#!/usr/bin/env python3
"""Benchmark candidate data structure implementations for hot-path types.

M6.3 Work Item 6.2: Benchmark instantiation, field access, and memory
for candidate data structure representations.

We use BlockHeader-like fields (the most complex hot-path type) as the
representative benchmark target: 11 fields mixing int, bytes, Optional,
and nested objects.

Candidates:
  1. @dataclass (current codebase pattern)
  2. @dataclass(slots=True) (current codebase pattern, already used)
  3. pydantic.BaseModel
  4. msgspec.Struct
  5. attrs.define
  6. Plain __slots__ class
  7. NamedTuple

Measures: instantiation time, field access time, memory per instance.
"""

from __future__ import annotations

import gc
import statistics
import sys
import time
import tracemalloc
from typing import NamedTuple, Optional

# ---------------------------------------------------------------------------
# 1. @dataclass (no slots)
# ---------------------------------------------------------------------------
from dataclasses import dataclass


@dataclass(frozen=True)
class DC_NoSlots:
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


# ---------------------------------------------------------------------------
# 2. @dataclass(slots=True) — current codebase pattern
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DC_Slots:
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


# ---------------------------------------------------------------------------
# 3. pydantic.BaseModel (if available)
# ---------------------------------------------------------------------------
PydanticModel = None
try:
    from pydantic import BaseModel

    class PydanticModel(BaseModel):  # type: ignore[no-redef]
        model_config = {"frozen": True}
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

except ImportError:
    pass


# ---------------------------------------------------------------------------
# 4. msgspec.Struct (if available)
# ---------------------------------------------------------------------------
MsgspecStruct = None
try:
    import msgspec

    class MsgspecStruct(msgspec.Struct, frozen=True):  # type: ignore[no-redef]
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

except ImportError:
    pass


# ---------------------------------------------------------------------------
# 5. attrs.define (if available)
# ---------------------------------------------------------------------------
AttrsClass = None
try:
    import attrs

    @attrs.define(frozen=True, slots=True)
    class AttrsClass:  # type: ignore[no-redef]
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

except ImportError:
    pass


# ---------------------------------------------------------------------------
# 6. Plain __slots__ class
# ---------------------------------------------------------------------------


class PlainSlots:
    __slots__ = (
        "slot",
        "block_number",
        "prev_hash",
        "issuer_vkey",
        "block_body_hash",
        "block_body_size",
        "era",
        "header_cbor",
        "vrf_output",
        "proto_major",
        "proto_minor",
    )

    def __init__(
        self,
        slot: int,
        block_number: int,
        prev_hash: Optional[bytes],
        issuer_vkey: bytes,
        block_body_hash: bytes,
        block_body_size: int,
        era: int,
        header_cbor: bytes,
        vrf_output: Optional[bytes],
        proto_major: int,
        proto_minor: int,
    ) -> None:
        self.slot = slot
        self.block_number = block_number
        self.prev_hash = prev_hash
        self.issuer_vkey = issuer_vkey
        self.block_body_hash = block_body_hash
        self.block_body_size = block_body_size
        self.era = era
        self.header_cbor = header_cbor
        self.vrf_output = vrf_output
        self.proto_major = proto_major
        self.proto_minor = proto_minor


# ---------------------------------------------------------------------------
# 7. NamedTuple
# ---------------------------------------------------------------------------


class NT(NamedTuple):
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


# ---------------------------------------------------------------------------
# Benchmark parameters
# ---------------------------------------------------------------------------

N_INSTANCES = 1_000_000
N_ACCESS_ITERS = 5_000_000
WARMUP = 100_000

# Sample field values (representative of real block header data)
SAMPLE_ARGS = {
    "slot": 134_567_890,
    "block_number": 10_234_567,
    "prev_hash": b"\xab" * 32,
    "issuer_vkey": b"\xcd" * 32,
    "block_body_hash": b"\xef" * 32,
    "block_body_size": 65535,
    "era": 7,
    "header_cbor": b"\x00" * 200,
    "vrf_output": b"\x11" * 64,
    "proto_major": 10,
    "proto_minor": 0,
}

SAMPLE_TUPLE = tuple(SAMPLE_ARGS.values())


def bench_instantiation(name: str, factory, n: int = N_INSTANCES) -> dict:
    """Benchmark creating n instances. Returns {name, total_s, per_instance_ns}."""
    # Warmup
    for _ in range(min(WARMUP, n)):
        factory()

    gc.disable()
    t0 = time.perf_counter_ns()
    for _ in range(n):
        factory()
    elapsed_ns = time.perf_counter_ns() - t0
    gc.enable()

    return {
        "name": name,
        "total_s": elapsed_ns / 1e9,
        "per_instance_ns": elapsed_ns / n,
        "instances": n,
    }


def bench_field_access(name: str, obj, n: int = N_ACCESS_ITERS) -> dict:
    """Benchmark reading 3 fields (slot, block_number, header_cbor) n times."""
    # Warmup
    for _ in range(min(WARMUP, n)):
        _ = obj.slot
        _ = obj.block_number
        _ = obj.header_cbor

    gc.disable()
    t0 = time.perf_counter_ns()
    for _ in range(n):
        _ = obj.slot
        _ = obj.block_number
        _ = obj.header_cbor
    elapsed_ns = time.perf_counter_ns() - t0
    gc.enable()

    return {
        "name": name,
        "total_s": elapsed_ns / 1e9,
        "per_access_ns": elapsed_ns / (n * 3),  # 3 field accesses per iter
        "accesses": n * 3,
    }


def bench_memory(name: str, factory, n: int = 10_000) -> dict:
    """Measure memory per instance using tracemalloc."""
    gc.collect()
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    instances = [factory() for _ in range(n)]

    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_bytes = sum(s.size_diff for s in stats if s.size_diff > 0)
    per_instance = total_bytes / n

    # Also get sys.getsizeof for a single instance
    single = factory()
    shallow_size = sys.getsizeof(single)

    # prevent GC
    _ = instances

    return {
        "name": name,
        "tracemalloc_per_instance_bytes": per_instance,
        "getsizeof_bytes": shallow_size,
        "n": n,
    }


def run_all():
    """Run all benchmarks and print results."""
    candidates = []

    # 1. dataclass (no slots)
    candidates.append(("dataclass(frozen)", lambda: DC_NoSlots(**SAMPLE_ARGS)))

    # 2. dataclass(slots=True) — current pattern
    candidates.append(("dataclass(frozen,slots)", lambda: DC_Slots(**SAMPLE_ARGS)))

    # 3. pydantic
    if PydanticModel is not None:
        candidates.append(("pydantic.BaseModel", lambda: PydanticModel(**SAMPLE_ARGS)))

    # 4. msgspec
    if MsgspecStruct is not None:
        candidates.append(("msgspec.Struct", lambda: MsgspecStruct(**SAMPLE_ARGS)))

    # 5. attrs
    if AttrsClass is not None:
        candidates.append(("attrs.define", lambda: AttrsClass(**SAMPLE_ARGS)))

    # 6. Plain __slots__
    candidates.append(("plain __slots__", lambda: PlainSlots(**SAMPLE_ARGS)))

    # 7. NamedTuple
    candidates.append(("NamedTuple", lambda: NT(**SAMPLE_ARGS)))

    print("=" * 72)
    print("M6.3 Data Structure Benchmark — Hot-Path Candidates")
    print(f"11 fields, {N_INSTANCES:,} instantiations, {N_ACCESS_ITERS:,} access loops")
    print(f"Python {sys.version}")
    print("=" * 72)

    # --- Instantiation ---
    print("\n--- Instantiation (1M instances) ---")
    print(f"{'Candidate':<28} {'Total (s)':>10} {'Per instance (ns)':>18}")
    print("-" * 60)
    inst_results = []
    for name, factory in candidates:
        r = bench_instantiation(name, factory)
        inst_results.append(r)
        print(f"{r['name']:<28} {r['total_s']:>10.3f} {r['per_instance_ns']:>18.1f}")

    # --- Field Access ---
    print(f"\n--- Field Access (3 fields x {N_ACCESS_ITERS:,} iters) ---")
    print(f"{'Candidate':<28} {'Total (s)':>10} {'Per access (ns)':>16}")
    print("-" * 58)
    access_results = []
    for name, factory in candidates:
        obj = factory()
        r = bench_field_access(name, obj)
        access_results.append(r)
        print(f"{r['name']:<28} {r['total_s']:>10.3f} {r['per_access_ns']:>16.1f}")

    # --- Memory ---
    print(f"\n--- Memory (10k instances, tracemalloc + getsizeof) ---")
    print(f"{'Candidate':<28} {'tracemalloc/inst (B)':>20} {'getsizeof (B)':>14}")
    print("-" * 66)
    mem_results = []
    for name, factory in candidates:
        r = bench_memory(name, factory)
        mem_results.append(r)
        print(
            f"{r['name']:<28} "
            f"{r['tracemalloc_per_instance_bytes']:>20.1f} "
            f"{r['getsizeof_bytes']:>14}"
        )

    print("\n" + "=" * 72)

    # Return structured results for report generation
    return {
        "instantiation": inst_results,
        "access": access_results,
        "memory": mem_results,
        "python_version": sys.version,
        "n_instances": N_INSTANCES,
        "n_access_iters": N_ACCESS_ITERS,
    }


if __name__ == "__main__":
    results = run_all()
