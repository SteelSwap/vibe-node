#!/usr/bin/env bash
# run-sync-benchmark.sh — Start a vibe-node preview sync benchmark
#
# This script:
#   1. Builds the vibe-node Docker image for preview sync
#   2. Starts the node + metrics sidecar via Docker Compose
#   3. Tails the metrics capture log
#   4. On Ctrl-C, stops everything and copies results out
#
# Usage:
#   ./scripts/run-sync-benchmark.sh [--interval SECONDS] [--detach]
#
# Options:
#   --interval N    Metrics sampling interval in seconds (default: 30)
#   --detach        Run in background (don't tail logs)
#
# Results are written to infra/preview-sync/results/vibe-node-metrics.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/infra/preview-sync"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.preview-sync.yml"
RESULTS_DIR="$COMPOSE_DIR/results"

# Defaults
INTERVAL=30
DETACH=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        --detach)
            DETACH=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--interval SECONDS] [--detach]"
            echo ""
            echo "Start a vibe-node preview testnet sync benchmark."
            echo ""
            echo "Options:"
            echo "  --interval N    Metrics sampling interval (default: 30s)"
            echo "  --detach        Run in background"
            echo "  -h, --help      Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "═══════════════════════════════════════════════════════════════"
echo "  vibe-node Preview Sync Benchmark"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Network:    Preview (magic 2)"
echo "  Relay:      relays-new.cardano-testnet.iohkdev.io:3001"
echo "  Interval:   ${INTERVAL}s"
echo "  Results:    ${RESULTS_DIR}/"
echo ""

# Create results directory
mkdir -p "$RESULTS_DIR"

# Record hardware info
echo "[benchmark] Capturing hardware info..."
HARDWARE_FILE="$RESULTS_DIR/hardware-info.json"
cat > "$HARDWARE_FILE" <<HWEOF
{
  "captured_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "hostname": "$(hostname)",
  "os": "$(uname -s) $(uname -r)",
  "arch": "$(uname -m)",
  "cpu_model": "$(grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs || sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'unknown')",
  "cpu_cores": $(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 0),
  "total_ram_mb": $(free -m 2>/dev/null | awk '/^Mem:/ {print $2}' || echo $(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1048576 ))),
  "docker_version": "$(docker --version 2>/dev/null | head -1 || echo 'unknown')"
}
HWEOF
echo "[benchmark] Hardware info saved to $HARDWARE_FILE"

# Build
echo "[benchmark] Building Docker image..."
docker compose -f "$COMPOSE_FILE" build

# Start with metrics interval
echo "[benchmark] Starting vibe-node + metrics capture..."
METRICS_INTERVAL="$INTERVAL" docker compose -f "$COMPOSE_FILE" up -d

echo ""
echo "[benchmark] Benchmark running. Results will be written to:"
echo "  $RESULTS_DIR/vibe-node-metrics.json"
echo ""

if [ "$DETACH" = true ]; then
    echo "[benchmark] Running in background. To check status:"
    echo "  docker compose -f $COMPOSE_FILE logs -f metrics-capture"
    echo ""
    echo "[benchmark] To stop:"
    echo "  docker compose -f $COMPOSE_FILE down"
else
    echo "[benchmark] Tailing metrics log (Ctrl-C to stop)..."
    echo ""

    # Trap Ctrl-C to gracefully stop
    trap 'echo ""; echo "[benchmark] Stopping..."; docker compose -f "$COMPOSE_FILE" down; echo "[benchmark] Results saved to $RESULTS_DIR/"; exit 0' INT TERM

    docker compose -f "$COMPOSE_FILE" logs -f metrics-capture
fi
