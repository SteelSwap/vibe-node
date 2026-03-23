"""Benchmark tests for vibe-node — performance regression tracking.

Uses pytest-benchmark to measure critical code paths:
- CBOR block decoding across all eras (Byron through Conway)
- Cryptographic operations (VRF, KES, Ed25519, Blake2b)
- Chain selection, mempool, and storage operations
- End-to-end block forge loop

Run with: uv run pytest tests/benchmark/ -v --benchmark-only
"""
