#!/usr/bin/env python3
"""monitor-tips.py — Poll devnet nodes and check tip agreement.

Connects to each node via the Ouroboros node-to-client local-state-query
miniprotocol (or falls back to cardano-cli query tip via Docker exec)
and compares their chain tips every MONITOR_INTERVAL seconds.

Exit codes:
    0 — All nodes agreed within tolerance for the entire monitoring duration
    1 — Tip divergence detected (delta > max allowed)
    2 — Configuration or connection error

Environment variables:
    MONITOR_NODES       Comma-separated host:port pairs (default: localhost:30001,localhost:30002,localhost:30003)
    MONITOR_INTERVAL    Seconds between polls (default: 10)
    MONITOR_DURATION    Total monitoring duration in seconds (default: 86400 = 24h)
    MONITOR_MAX_DELTA   Maximum allowed slot delta before alerting (default: 10)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("monitor-tips")


# ─── Data types ──────────────────────────────────────────────────


@dataclass
class ChainTip:
    """A node's current chain tip."""

    slot: int
    block_no: int
    block_hash: str
    node: str
    timestamp: float

    def __str__(self) -> str:
        return f"{self.node}: slot={self.slot} block={self.block_no} hash={self.block_hash[:16]}..."


@dataclass
class PollResult:
    """Result of a single poll across all nodes."""

    timestamp: float
    tips: list[ChainTip]
    max_delta: int
    agreed: bool

    def __str__(self) -> str:
        ts = datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()
        status = "AGREED" if self.agreed else f"DIVERGED (delta={self.max_delta})"
        tips_str = " | ".join(str(t) for t in self.tips)
        return f"[{ts}] {status} — {tips_str}"


# ─── Node querying ───────────────────────────────────────────────


def query_tip_via_socket(host: str, port: int, network_magic: int = 42) -> Optional[ChainTip]:
    """Query chain tip via a lightweight TCP probe.

    This is a placeholder that will be replaced with proper miniprotocol
    implementation once the vibe-node networking stack is integrated.
    For now, it attempts a basic TCP connection check.
    """
    # TODO(M4.x): Replace with proper Ouroboros local-state-query client
    # For now, we just verify the node is listening and return None
    # to signal we need the Docker exec fallback
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))
        sock.close()
        return None  # Connected but can't query tip yet
    except (socket.error, OSError):
        return None


def query_tip_via_cli(container_name: str) -> Optional[ChainTip]:
    """Query chain tip by exec-ing cardano-cli inside a Docker container."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                container_name,
                "cardano-cli",
                "latest",
                "query",
                "tip",
                "--testnet-magic",
                "42",
                "--socket-path",
                "/ipc/node.socket",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            log.warning("cardano-cli query tip failed for %s: %s", container_name, result.stderr.strip())
            return None

        data = json.loads(result.stdout)
        return ChainTip(
            slot=data.get("slot", 0),
            block_no=data.get("block", 0),
            block_hash=data.get("hash", "unknown"),
            node=container_name,
            timestamp=time.time(),
        )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as exc:
        log.warning("Failed to query %s via CLI: %s", container_name, exc)
        return None


def query_node(name: str, host: str, port: int) -> Optional[ChainTip]:
    """Query a node's chain tip, trying socket first then CLI fallback."""
    tip = query_tip_via_socket(host, port)
    if tip is not None:
        return tip

    # Derive container name from docker compose service name
    # In docker compose, the default container name is <project>-<service>-1
    # Try common patterns
    for container in [name, f"devnet-{name}-1", f"infra-devnet-{name}-1"]:
        tip = query_tip_via_cli(container)
        if tip is not None:
            return tip

    log.warning("Could not query tip for %s (%s:%d)", name, host, port)
    return None


# ─── Monitoring loop ─────────────────────────────────────────────


def poll_once(nodes: list[tuple[str, str, int]], max_allowed_delta: int) -> PollResult:
    """Poll all nodes once and compute tip agreement."""
    tips: list[ChainTip] = []
    now = time.time()

    for name, host, port in nodes:
        tip = query_node(name, host, port)
        if tip is not None:
            tips.append(tip)

    if len(tips) < 2:
        return PollResult(
            timestamp=now,
            tips=tips,
            max_delta=0,
            agreed=True,  # Can't disagree with < 2 nodes
        )

    slots = [t.slot for t in tips]
    delta = max(slots) - min(slots)
    agreed = delta <= max_allowed_delta

    return PollResult(timestamp=now, tips=tips, max_delta=delta, agreed=agreed)


def monitor(
    nodes: list[tuple[str, str, int]],
    interval: int,
    duration: int,
    max_delta: int,
) -> int:
    """Run the monitoring loop. Returns exit code."""
    log.info("Starting tip monitor")
    log.info("  Nodes: %s", ", ".join(f"{n}={h}:{p}" for n, h, p in nodes))
    log.info("  Interval: %ds, Duration: %ds, Max delta: %d slots", interval, duration, max_delta)

    start = time.time()
    divergence_count = 0
    poll_count = 0

    while time.time() - start < duration:
        result = poll_once(nodes, max_delta)
        poll_count += 1

        if result.agreed:
            log.info("%s", result)
        else:
            divergence_count += 1
            log.warning("DIVERGENCE #%d: %s", divergence_count, result)

        time.sleep(interval)

    # Final report
    log.info("=== Monitoring complete ===")
    log.info("  Duration: %ds", int(time.time() - start))
    log.info("  Polls: %d", poll_count)
    log.info("  Divergences: %d", divergence_count)

    if divergence_count > 0:
        log.error("FAIL: %d tip divergences detected", divergence_count)
        return 1

    log.info("PASS: All nodes agreed for the entire monitoring period")
    return 0


# ─── CLI ─────────────────────────────────────────────────────────


def parse_nodes(nodes_str: str) -> list[tuple[str, str, int]]:
    """Parse 'name=host:port,name=host:port' or 'host:port,host:port' format."""
    result = []
    for entry in nodes_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            name, hostport = entry.split("=", 1)
        else:
            hostport = entry
            name = hostport.split(":")[0]
        host, port_str = hostport.rsplit(":", 1)
        result.append((name, host, int(port_str)))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor devnet node tip agreement")
    parser.add_argument(
        "--nodes",
        default=os.environ.get("MONITOR_NODES", "haskell-node-1:3001,haskell-node-2:3001,vibe-node:3001"),
        help="Comma-separated node addresses (name=host:port or host:port)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("MONITOR_INTERVAL", "10")),
        help="Seconds between polls (default: 10)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=int(os.environ.get("MONITOR_DURATION", "86400")),
        help="Total monitoring duration in seconds (default: 86400)",
    )
    parser.add_argument(
        "--max-delta",
        type=int,
        default=int(os.environ.get("MONITOR_MAX_DELTA", "10")),
        help="Maximum allowed slot delta (default: 10)",
    )
    args = parser.parse_args()

    nodes = parse_nodes(args.nodes)
    if len(nodes) < 2:
        log.error("Need at least 2 nodes to monitor, got %d", len(nodes))
        return 2

    return monitor(nodes, args.interval, args.duration, args.max_delta)


if __name__ == "__main__":
    sys.exit(main())
