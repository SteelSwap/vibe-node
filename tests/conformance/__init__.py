# Conformance tests — bit-for-bit validation against the Haskell cardano-node
# via Ogmios JSON-RPC over WebSocket.
#
# These tests require Docker Compose services to be running:
#   docker compose up -d cardano-node ogmios
#
# Tests skip gracefully when Ogmios is not reachable.
