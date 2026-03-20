# Conformance tests — bit-for-bit validation against the Haskell cardano-node
# via Ogmios JSON-RPC over WebSocket.
#
# Two-tier test architecture:
#
# 1. **Fixture-based tests** (no Docker required):
#    Pre-cached block JSON in tests/conformance/fixtures/ enables structural
#    validation, metadata extraction, cost model parameter checks, and
#    Plutus version invariants to run in any CI environment.
#
# 2. **Live Ogmios tests** (requires Docker Compose):
#    Tests marked @pytest.mark.conformance compare our results against a
#    running Haskell cardano-node + Ogmios. These are the gold standard.
#
# Running:
#   pytest tests/conformance/                     # fixture tests only (no Docker)
#   docker compose up -d cardano-node ogmios      # start services
#   pytest tests/conformance/ -m conformance      # live conformance tests
#   pytest tests/conformance/                     # all tests (with Docker)
#
# Tests skip gracefully when Ogmios is not reachable.
