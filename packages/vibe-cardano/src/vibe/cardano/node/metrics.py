"""Prometheus metrics endpoint and health check for the vibe Cardano node.

Provides a lightweight HTTP server exposing ``/metrics`` in Prometheus text
exposition format and ``/health`` as a JSON liveness probe.  Zero external
dependencies -- built on :mod:`asyncio` and the stdlib only.

Haskell references:
    - Cardano.Node.Tracing.Tracers (EKG / Prometheus integration)
    - Ouroboros.Consensus.Node (health probes via ekg-core)

Design notes:
    The Haskell node uses ekg-core for runtime metrics and optionally
    exposes them via ekg-prometheus-adapter.  We mirror the same metric
    semantics (counters, gauges, histograms) but emit the Prometheus text
    format directly from a plain asyncio HTTP handler -- no aiohttp, no
    prometheus_client wheel required.  This keeps the dependency footprint
    minimal per project policy.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import ClassVar

__all__ = [
    "Counter",
    "Gauge",
    "Histogram",
    "MetricsServer",
    "BLOCKS_FORGED",
    "BLOCKS_SYNCED",
    "BLOCK_VALIDATION_DURATION",
    "FORGE_DURATION",
    "MEMORY_RSS",
    "PEERS_CONNECTED",
    "TIP_SLOT",
]

# ---------------------------------------------------------------------------
# Metric primitives
# ---------------------------------------------------------------------------

NODE_VERSION = "0.5.0"


@dataclass
class Counter:
    """A monotonically-increasing counter (Prometheus COUNTER)."""

    name: str
    help: str
    _value: float = 0.0

    def inc(self, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError("Counter increment must be non-negative")
        self._value += amount

    @property
    def value(self) -> float:
        return self._value

    def exposition(self) -> str:
        return (
            f"# HELP {self.name} {self.help}\n"
            f"# TYPE {self.name} counter\n"
            f"{self.name} {self._value}\n"
        )


@dataclass
class Gauge:
    """A value that can go up and down (Prometheus GAUGE)."""

    name: str
    help: str
    _value: float = 0.0

    def set(self, value: float) -> None:
        self._value = value

    def inc(self, amount: float = 1.0) -> None:
        self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        self._value -= amount

    @property
    def value(self) -> float:
        return self._value

    def exposition(self) -> str:
        return (
            f"# HELP {self.name} {self.help}\n"
            f"# TYPE {self.name} gauge\n"
            f"{self.name} {self._value}\n"
        )


# Default histogram buckets mirroring Prometheus client_golang defaults
_DEFAULT_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    float("inf"),
)


@dataclass
class Histogram:
    """A distribution of observed values (Prometheus HISTOGRAM).

    Uses cumulative bucket counters, a running sum, and a count --
    identical semantics to Prometheus histograms.
    """

    name: str
    help: str
    buckets: tuple[float, ...] = _DEFAULT_BUCKETS
    _bucket_counts: list[int] = field(default_factory=list, init=False)
    _sum: float = field(default=0.0, init=False)
    _count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        # Ensure +Inf is the last bucket
        bs = list(self.buckets)
        if not bs or bs[-1] != float("inf"):
            bs.append(float("inf"))
        self.buckets = tuple(bs)
        self._bucket_counts = [0] * len(self.buckets)

    def observe(self, value: float) -> None:
        self._sum += value
        self._count += 1
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self._bucket_counts[i] += 1
                break

    @property
    def count(self) -> int:
        return self._count

    @property
    def sum(self) -> float:
        return self._sum

    def exposition(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help}",
            f"# TYPE {self.name} histogram",
        ]
        cumulative = 0
        for bound, count in zip(self.buckets, self._bucket_counts):
            cumulative += count
            le = "+Inf" if math.isinf(bound) else str(bound)
            lines.append(f'{self.name}_bucket{{le="{le}"}} {cumulative}')
        lines.append(f"{self.name}_sum {self._sum}")
        lines.append(f"{self.name}_count {self._count}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Singleton metrics -- importable from anywhere in the node
# ---------------------------------------------------------------------------

TIP_SLOT = Gauge("vibe_node_tip_slot", "Current chain tip slot number")
BLOCKS_SYNCED = Counter("vibe_node_blocks_synced_total", "Total blocks synced from peers")
BLOCKS_FORGED = Counter("vibe_node_blocks_forged_total", "Total blocks forged by this node")
PEERS_CONNECTED = Gauge("vibe_node_peers_connected", "Number of currently connected peers")
MEMORY_RSS = Gauge("vibe_node_memory_rss_bytes", "Resident set size in bytes")
FORGE_DURATION = Histogram(
    "vibe_node_forge_duration_seconds",
    "Time spent forging a block",
)
BLOCK_VALIDATION_DURATION = Histogram(
    "vibe_node_block_validation_duration_seconds",
    "Time spent validating a received block",
)

_ALL_METRICS: list[Counter | Gauge | Histogram] = [
    TIP_SLOT,
    BLOCKS_SYNCED,
    BLOCKS_FORGED,
    PEERS_CONNECTED,
    MEMORY_RSS,
    FORGE_DURATION,
    BLOCK_VALIDATION_DURATION,
]


def _render_metrics() -> str:
    """Render all registered metrics in Prometheus text exposition format."""
    return "\n".join(m.exposition() for m in _ALL_METRICS)


# ---------------------------------------------------------------------------
# Asyncio HTTP server
# ---------------------------------------------------------------------------


def _try_read_rss() -> int | None:
    """Best-effort RSS read via /proc/self/status or resource module."""
    try:
        import resource  # Unix only

        # ru_maxrss is in KB on Linux, bytes on macOS
        ru = resource.getrusage(resource.RUSAGE_SELF)
        import sys

        if sys.platform == "darwin":
            return ru.ru_maxrss  # already bytes on macOS
        return ru.ru_maxrss * 1024  # KB -> bytes on Linux
    except Exception:
        return None


class MetricsServer:
    """Lightweight asyncio HTTP server for ``/metrics`` and ``/health``.

    Parameters:
        host: Bind address (default ``"0.0.0.0"``).
        port: Listen port (default ``9100``).
        syncing_slot_threshold: If the tip slot is more than this many
            slots behind wall-clock time, ``/health`` reports
            ``"syncing": true``.  Defaults to 600 (10 minutes).
    """

    DEFAULT_PORT: ClassVar[int] = 9100

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int | None = None,
        syncing_slot_threshold: int = 600,
    ) -> None:
        self.host = host
        self.port = port or int(os.environ.get("VIBE_METRICS_PORT", str(self.DEFAULT_PORT)))
        self.syncing_slot_threshold = syncing_slot_threshold
        self._server: asyncio.Server | None = None

    # -- HTTP handling (minimal, no framework) --------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single HTTP/1.0 request."""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not request_line:
                return

            parts = request_line.decode("utf-8", errors="replace").strip().split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else "/"

            # Consume remaining headers (we don't need them)
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if line in (b"\r\n", b"\n", b""):
                    break

            if method != "GET":
                self._send_response(
                    writer, HTTPStatus.METHOD_NOT_ALLOWED, "text/plain", "Method Not Allowed\n"
                )
            elif path == "/metrics":
                self._handle_metrics(writer)
            elif path == "/health":
                self._handle_health(writer)
            else:
                self._send_response(writer, HTTPStatus.NOT_FOUND, "text/plain", "Not Found\n")

            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _send_response(
        self,
        writer: asyncio.StreamWriter,
        status: HTTPStatus,
        content_type: str,
        body: str,
    ) -> None:
        encoded = body.encode("utf-8")
        header = (
            f"HTTP/1.0 {status.value} {status.phrase}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(encoded)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        writer.write(header.encode("utf-8"))
        writer.write(encoded)

    def _handle_metrics(self, writer: asyncio.StreamWriter) -> None:
        # Update RSS before serving
        rss = _try_read_rss()
        if rss is not None:
            MEMORY_RSS.set(rss)
        body = _render_metrics()
        self._send_response(
            writer,
            HTTPStatus.OK,
            "text/plain; version=0.0.4; charset=utf-8",
            body,
        )

    def _handle_health(self, writer: asyncio.StreamWriter) -> None:
        tip = int(TIP_SLOT.value)
        peers = int(PEERS_CONNECTED.value)
        syncing = tip < self.syncing_slot_threshold  # simple heuristic
        payload = {
            "status": "ok",
            "tip_slot": tip,
            "peers": peers,
            "syncing": syncing,
            "version": NODE_VERSION,
        }
        self._send_response(
            writer,
            HTTPStatus.OK,
            "application/json",
            json.dumps(payload),
        )

    # -- Lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        """Start the metrics server (non-blocking)."""
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
        )

    async def stop(self) -> None:
        """Gracefully stop the metrics server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    async def __aenter__(self) -> MetricsServer:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()
