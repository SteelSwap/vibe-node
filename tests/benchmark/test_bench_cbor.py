"""M6.7.1 — CBOR block decode benchmarks across all Cardano eras.

Measures the performance of CBOR deserialization for block headers
from Byron through Conway. Uses synthetic blocks that match the
wire format structure for each era.

Run: uv run pytest tests/benchmark/test_bench_cbor.py -v --benchmark-only
"""

from __future__ import annotations

import cbor2pure as cbor2
import pytest

from vibe.cardano.serialization.block import (
    Era,
    decode_block_header,
    detect_era,
)


# ---------------------------------------------------------------------------
# Benchmark: raw CBOR decode (cbor2.loads — no semantic interpretation)
# ---------------------------------------------------------------------------

class TestRawCBORDecode:
    """Benchmark raw cbor2.loads across all eras.

    This measures the cbor2pure deserialization overhead independent
    of our block header parsing logic.
    """

    def test_raw_decode_byron_main(self, benchmark, byron_block_cbor: bytes) -> None:
        benchmark.pedantic(
            cbor2.loads,
            args=(byron_block_cbor,),
            kwargs={"raw_tags": True},
            rounds=100,
        )

    def test_raw_decode_byron_ebb(self, benchmark, byron_ebb_cbor: bytes) -> None:
        benchmark.pedantic(
            cbor2.loads,
            args=(byron_ebb_cbor,),
            kwargs={"raw_tags": True},
            rounds=100,
        )

    def test_raw_decode_shelley(self, benchmark, shelley_block_cbor: bytes) -> None:
        benchmark.pedantic(
            cbor2.loads,
            args=(shelley_block_cbor,),
            kwargs={"raw_tags": True},
            rounds=100,
        )

    def test_raw_decode_allegra(self, benchmark, allegra_block_cbor: bytes) -> None:
        benchmark.pedantic(
            cbor2.loads,
            args=(allegra_block_cbor,),
            kwargs={"raw_tags": True},
            rounds=100,
        )

    def test_raw_decode_mary(self, benchmark, mary_block_cbor: bytes) -> None:
        benchmark.pedantic(
            cbor2.loads,
            args=(mary_block_cbor,),
            kwargs={"raw_tags": True},
            rounds=100,
        )

    def test_raw_decode_alonzo(self, benchmark, alonzo_block_cbor: bytes) -> None:
        benchmark.pedantic(
            cbor2.loads,
            args=(alonzo_block_cbor,),
            kwargs={"raw_tags": True},
            rounds=100,
        )

    def test_raw_decode_babbage(self, benchmark, babbage_block_cbor: bytes) -> None:
        benchmark.pedantic(
            cbor2.loads,
            args=(babbage_block_cbor,),
            kwargs={"raw_tags": True},
            rounds=100,
        )

    def test_raw_decode_conway(self, benchmark, conway_block_cbor: bytes) -> None:
        benchmark.pedantic(
            cbor2.loads,
            args=(conway_block_cbor,),
            kwargs={"raw_tags": True},
            rounds=100,
        )


# ---------------------------------------------------------------------------
# Benchmark: era detection (tag parsing)
# ---------------------------------------------------------------------------

class TestEraDetection:
    """Benchmark detect_era — fast tag parsing without full decode."""

    def test_detect_era_shelley(self, benchmark, shelley_block_cbor: bytes) -> None:
        result = benchmark.pedantic(detect_era, args=(shelley_block_cbor,), rounds=100)
        assert result == Era.SHELLEY

    def test_detect_era_babbage(self, benchmark, babbage_block_cbor: bytes) -> None:
        result = benchmark.pedantic(detect_era, args=(babbage_block_cbor,), rounds=100)
        assert result == Era.BABBAGE

    def test_detect_era_conway(self, benchmark, conway_block_cbor: bytes) -> None:
        result = benchmark.pedantic(detect_era, args=(conway_block_cbor,), rounds=100)
        assert result == Era.CONWAY


# ---------------------------------------------------------------------------
# Benchmark: full block header decode (our decode_block_header)
# ---------------------------------------------------------------------------

class TestBlockHeaderDecode:
    """Benchmark decode_block_header across Shelley+ eras.

    Byron blocks use a different header format and decode path.
    Shelley-Alonzo use the two-VRF-cert format.
    Babbage-Conway use the single vrf_result format.
    """

    def test_decode_header_shelley(self, benchmark, shelley_block_cbor: bytes) -> None:
        header = benchmark.pedantic(
            decode_block_header,
            args=(shelley_block_cbor,),
            rounds=100,
        )
        assert header.era == Era.SHELLEY
        assert header.block_number == 100

    def test_decode_header_allegra(self, benchmark, allegra_block_cbor: bytes) -> None:
        header = benchmark.pedantic(
            decode_block_header,
            args=(allegra_block_cbor,),
            rounds=100,
        )
        assert header.era == Era.ALLEGRA

    def test_decode_header_mary(self, benchmark, mary_block_cbor: bytes) -> None:
        header = benchmark.pedantic(
            decode_block_header,
            args=(mary_block_cbor,),
            rounds=100,
        )
        assert header.era == Era.MARY

    def test_decode_header_alonzo(self, benchmark, alonzo_block_cbor: bytes) -> None:
        header = benchmark.pedantic(
            decode_block_header,
            args=(alonzo_block_cbor,),
            rounds=100,
        )
        assert header.era == Era.ALONZO

    def test_decode_header_babbage(self, benchmark, babbage_block_cbor: bytes) -> None:
        header = benchmark.pedantic(
            decode_block_header,
            args=(babbage_block_cbor,),
            rounds=100,
        )
        assert header.era == Era.BABBAGE
        assert header.block_number == 500

    def test_decode_header_conway(self, benchmark, conway_block_cbor: bytes) -> None:
        header = benchmark.pedantic(
            decode_block_header,
            args=(conway_block_cbor,),
            rounds=100,
        )
        assert header.era == Era.CONWAY
        assert header.block_number == 600


# ---------------------------------------------------------------------------
# Benchmark: CBOR encode round-trip
# ---------------------------------------------------------------------------

class TestCBORRoundTrip:
    """Benchmark encode+decode cycle to measure serialization overhead."""

    def test_roundtrip_shelley(self, benchmark, shelley_block_cbor: bytes) -> None:
        """Decode then re-encode a Shelley block."""
        def roundtrip(data: bytes) -> bytes:
            decoded = cbor2.loads(data, raw_tags=True)
            return cbor2.dumps(decoded)

        result = benchmark.pedantic(roundtrip, args=(shelley_block_cbor,), rounds=100)
        assert isinstance(result, bytes)

    def test_roundtrip_conway(self, benchmark, conway_block_cbor: bytes) -> None:
        """Decode then re-encode a Conway block."""
        def roundtrip(data: bytes) -> bytes:
            decoded = cbor2.loads(data, raw_tags=True)
            return cbor2.dumps(decoded)

        result = benchmark.pedantic(roundtrip, args=(conway_block_cbor,), rounds=100)
        assert isinstance(result, bytes)
