#!/usr/bin/env bash
# run-haskell-sync-benchmark.sh — Start a Haskell cardano-node preview sync benchmark
#
# This script:
#   1. Fetches preview network config if not present
#   2. Starts the Haskell node + metrics sidecar via Docker Compose
#   3. Tails the metrics capture log
#   4. On Ctrl-C, stops everything and reports results location
#
# Usage:
#   ./scripts/run-haskell-sync-benchmark.sh [--interval SECONDS] [--detach]
#
# Results are written to infra/preview-sync/results/haskell-node-metrics.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/infra/preview-sync"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.haskell-sync.yml"
RESULTS_DIR="$COMPOSE_DIR/results"
CONFIG_DIR="$COMPOSE_DIR/config/preview"

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
            echo "Start a Haskell cardano-node preview testnet sync benchmark."
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
echo "  Haskell cardano-node Preview Sync Benchmark"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Image:      ghcr.io/intersectmbo/cardano-node:10.4.1"
echo "  Network:    Preview (magic 2)"
echo "  Interval:   ${INTERVAL}s"
echo "  Results:    ${RESULTS_DIR}/"
echo ""

# Fetch preview config if not present
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    echo "[benchmark] Preview config not found, fetching..."
    bash "$COMPOSE_DIR/scripts/fetch-preview-config.sh"
else
    echo "[benchmark] Preview config found at $CONFIG_DIR"
fi

# Create results directory
mkdir -p "$RESULTS_DIR"

# Record hardware info (same as vibe-node benchmark)
HARDWARE_FILE="$RESULTS_DIR/hardware-info.json"
if [ ! -f "$HARDWARE_FILE" ]; then
    echo "[benchmark] Capturing hardware info..."
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
fi

# Start
echo "[benchmark] Starting Haskell node + metrics capture..."
METRICS_INTERVAL="$INTERVAL" docker compose -f "$COMPOSE_FILE" up -d

echo ""
echo "[benchmark] Benchmark running. Results will be written to:"
echo "  $RESULTS_DIR/haskell-node-metrics.json"
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

    trap 'echo ""; echo "[benchmark] Stopping..."; docker compose -f "$COMPOSE_FILE" down; echo "[benchmark] Results saved to $RESULTS_DIR/"; exit 0' INT TERM

    docker compose -f "$COMPOSE_FILE" logs -f metrics-capture
fi
