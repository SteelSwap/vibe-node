"""Tests for vibe.cardano.node.metrics -- Prometheus metrics and health endpoint."""

from __future__ import annotations

import asyncio
import json

import pytest

from vibe.cardano.node.metrics import (
    BLOCKS_FORGED,
    BLOCKS_SYNCED,
    PEERS_CONNECTED,
    TIP_SLOT,
    Counter,
    Gauge,
    Histogram,
    MetricsServer,
)

# ---------------------------------------------------------------------------
# Metric primitives
# ---------------------------------------------------------------------------


class TestCounter:
    def test_metrics_counter_increment(self) -> None:
        """Verify counter increases correctly."""
        c = Counter("test_counter", "A test counter")
        assert c.value == 0.0
        c.inc()
        assert c.value == 1.0
        c.inc(5.0)
        assert c.value == 6.0

    def test_counter_rejects_negative(self) -> None:
        c = Counter("test_counter_neg", "Negative test")
        with pytest.raises(ValueError, match="non-negative"):
            c.inc(-1)

    def test_counter_exposition(self) -> None:
        c = Counter("my_counter", "help text")
        c.inc(3)
        text = c.exposition()
        assert "# TYPE my_counter counter" in text
        assert "my_counter 3" in text


class TestGauge:
    def test_metrics_gauge_set(self) -> None:
        """Verify gauge reflects the value that was set."""
        g = Gauge("test_gauge", "A test gauge")
        assert g.value == 0.0
        g.set(42.0)
        assert g.value == 42.0
        g.set(0.0)
        assert g.value == 0.0

    def test_gauge_inc_dec(self) -> None:
        g = Gauge("test_gauge_incdec", "Inc/dec test")
        g.inc(10)
        assert g.value == 10.0
        g.dec(3)
        assert g.value == 7.0

    def test_gauge_exposition(self) -> None:
        g = Gauge("my_gauge", "help text")
        g.set(99)
        text = g.exposition()
        assert "# TYPE my_gauge gauge" in text
        assert "my_gauge 99" in text


class TestHistogram:
    def test_observe_updates_count_and_sum(self) -> None:
        h = Histogram("test_hist", "A test histogram")
        h.observe(0.1)
        h.observe(0.5)
        assert h.count == 2
        assert abs(h.sum - 0.6) < 1e-9

    def test_histogram_buckets(self) -> None:
        h = Histogram("test_hist_bucket", "Bucket test", buckets=(0.1, 0.5, 1.0))
        h.observe(0.05)  # fits in 0.1, 0.5, 1.0, +Inf
        h.observe(0.3)  # fits in 0.5, 1.0, +Inf
        h.observe(2.0)  # fits in +Inf only
        text = h.exposition()
        assert 'le="0.1"} 1' in text
        assert 'le="0.5"} 2' in text
        assert 'le="1.0"} 2' in text
        assert 'le="+Inf"} 3' in text

    def test_histogram_exposition_format(self) -> None:
        h = Histogram("dur", "duration")
        h.observe(0.01)
        text = h.exposition()
        assert "# TYPE dur histogram" in text
        assert "dur_sum" in text
        assert "dur_count 1" in text


# ---------------------------------------------------------------------------
# HTTP endpoints (integration-style, hitting a real TCP server)
# ---------------------------------------------------------------------------


async def _http_get(host: str, port: int, path: str) -> tuple[int, dict[str, str], str]:
    """Minimal HTTP/1.0 GET client -- returns (status_code, headers, body)."""
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(f"GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
        text = data.decode("utf-8", errors="replace")
        head, _, body = text.partition("\r\n\r\n")
        status_line = head.split("\r\n")[0]
        status_code = int(status_line.split()[1])
        headers: dict[str, str] = {}
        for line in head.split("\r\n")[1:]:
            k, _, v = line.partition(": ")
            headers[k.lower()] = v
        return status_code, headers, body
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.fixture
async def metrics_server():
    """Start a MetricsServer on a random free port and tear it down after the test."""
    server = MetricsServer(host="127.0.0.1", port=0)
    await server.start()
    # Retrieve the actual bound port
    assert server._server is not None
    sock = server._server.sockets[0]
    port = sock.getsockname()[1]
    server.port = port
    yield server
    await server.stop()


@pytest.mark.asyncio
async def test_health_endpoint_returns_json(metrics_server: MetricsServer) -> None:
    """Verify /health returns well-formed JSON with required fields."""
    # Set some known state
    TIP_SLOT.set(12345)
    PEERS_CONNECTED.set(3)

    status, headers, body = await _http_get("127.0.0.1", metrics_server.port, "/health")
    assert status == 200
    assert "application/json" in headers.get("content-type", "")

    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["tip_slot"] == 12345
    assert payload["peers"] == 3
    assert isinstance(payload["syncing"], bool)
    assert payload["version"] == "0.5.0"


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format(metrics_server: MetricsServer) -> None:
    """Verify /metrics contains expected metric names in Prometheus text format."""
    BLOCKS_SYNCED.inc(10)
    BLOCKS_FORGED.inc(2)

    status, headers, body = await _http_get("127.0.0.1", metrics_server.port, "/metrics")
    assert status == 200
    assert "text/plain" in headers.get("content-type", "")

    # Check that all expected metric names appear
    expected_names = [
        "vibe_node_tip_slot",
        "vibe_node_blocks_synced_total",
        "vibe_node_blocks_forged_total",
        "vibe_node_peers_connected",
        "vibe_node_memory_rss_bytes",
        "vibe_node_forge_duration_seconds",
        "vibe_node_block_validation_duration_seconds",
    ]
    for name in expected_names:
        assert name in body, f"Expected metric '{name}' not found in /metrics output"


@pytest.mark.asyncio
async def test_not_found(metrics_server: MetricsServer) -> None:
    """Unknown paths return 404."""
    status, _, _ = await _http_get("127.0.0.1", metrics_server.port, "/unknown")
    assert status == 404


@pytest.mark.asyncio
async def test_server_context_manager() -> None:
    """MetricsServer works as an async context manager."""
    async with MetricsServer(host="127.0.0.1", port=0) as srv:
        assert srv.is_running
    assert not srv.is_running
