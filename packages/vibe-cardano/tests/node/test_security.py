"""Tests for security hardening: CBOR limits and protocol message validation.

Verifies that safe_cbor_loads rejects oversized and deeply nested payloads,
and that validate_protocol_message filters unexpected message types.
"""

from __future__ import annotations

import logging

import cbor2pure
import pytest

from vibe.cardano.security import (
    MAX_CBOR_DEPTH,
    MAX_CBOR_SIZE,
    safe_cbor_loads,
    validate_protocol_message,
)


# ---------------------------------------------------------------------------
# safe_cbor_loads
# ---------------------------------------------------------------------------


class TestSafeCborLoadsRejectsOversized:
    """Payloads exceeding max_size must be rejected before decoding."""

    def test_rejects_oversized(self) -> None:
        # Create a payload that is just over the limit.
        # We use a small custom limit to avoid allocating 64 MB in tests.
        small_limit = 32
        payload = cbor2pure.dumps(b"\x00" * (small_limit + 1))
        with pytest.raises(ValueError, match="exceeds limit"):
            safe_cbor_loads(payload, max_size=small_limit)

    def test_rejects_at_default_constant(self) -> None:
        """Ensure the default constant is 64 MB."""
        assert MAX_CBOR_SIZE == 64 * 1024 * 1024


class TestSafeCborLoadsRejectsDeepNesting:
    """Deeply nested CBOR must raise CBORDecodeError."""

    def test_rejects_deep_nesting(self) -> None:
        # Build a deeply nested list: [[[[...]]]]
        depth = 10
        obj: list = []
        current = obj
        for _ in range(depth):
            child: list = []
            current.append(child)
            current = child

        payload = cbor2pure.dumps(obj)
        with pytest.raises(cbor2pure.CBORDecodeError, match="nesting depth"):
            safe_cbor_loads(payload, max_depth=5)

    def test_default_depth_constant(self) -> None:
        assert MAX_CBOR_DEPTH == 256


class TestSafeCborLoadsAcceptsValid:
    """Normal CBOR payloads decode correctly."""

    def test_integer(self) -> None:
        assert safe_cbor_loads(cbor2pure.dumps(42)) == 42

    def test_list(self) -> None:
        assert safe_cbor_loads(cbor2pure.dumps([1, 2, 3])) == [1, 2, 3]

    def test_dict(self) -> None:
        assert safe_cbor_loads(cbor2pure.dumps({"a": 1})) == {"a": 1}

    def test_bytes(self) -> None:
        assert safe_cbor_loads(cbor2pure.dumps(b"hello")) == b"hello"

    def test_nested_within_limits(self) -> None:
        obj = [[["deep"]]]
        assert safe_cbor_loads(cbor2pure.dumps(obj), max_depth=10) == obj


class TestSafeCborLoadsCustomLimits:
    """Custom max_size and max_depth parameters are respected."""

    def test_custom_max_size_accepts(self) -> None:
        payload = cbor2pure.dumps(b"\x00" * 100)
        # Payload should be around 102 bytes (CBOR overhead)
        result = safe_cbor_loads(payload, max_size=200)
        assert result == b"\x00" * 100

    def test_custom_max_size_rejects(self) -> None:
        payload = cbor2pure.dumps(b"\x00" * 100)
        with pytest.raises(ValueError, match="exceeds limit"):
            safe_cbor_loads(payload, max_size=10)

    def test_custom_max_depth_accepts(self) -> None:
        obj = [[[1]]]  # depth 3
        assert safe_cbor_loads(cbor2pure.dumps(obj), max_depth=5) == obj

    def test_custom_max_depth_rejects(self) -> None:
        obj = [[[1]]]  # depth 3
        with pytest.raises(cbor2pure.CBORDecodeError, match="nesting depth"):
            safe_cbor_loads(cbor2pure.dumps(obj), max_depth=2)


# ---------------------------------------------------------------------------
# validate_protocol_message
# ---------------------------------------------------------------------------


class TestValidateProtocolMessageAcceptsValid:
    """Messages matching expected types pass through unchanged."""

    def test_accepts_matching_type(self) -> None:
        msg = [1, 2, 3]
        result = validate_protocol_message(msg, [list, dict])
        assert result is msg

    def test_accepts_first_of_multiple(self) -> None:
        msg = {"key": "value"}
        result = validate_protocol_message(msg, [list, dict])
        assert result is msg

    def test_accepts_subclass(self) -> None:
        """Subclasses of expected types should also be accepted."""

        class MyList(list):
            pass

        msg = MyList([1, 2])
        result = validate_protocol_message(msg, [list])
        assert result is msg


class TestValidateProtocolMessageRejectsInvalid:
    """Messages not matching expected types return None and log a warning."""

    def test_rejects_wrong_type(self, caplog: pytest.LogCaptureFixture) -> None:
        msg = "unexpected string"
        with caplog.at_level(logging.WARNING):
            result = validate_protocol_message(msg, [list, dict])
        assert result is None
        assert "Unexpected protocol message type" in caplog.text
        assert "str" in caplog.text

    def test_rejects_none_when_not_expected(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = validate_protocol_message(None, [list, dict])
        assert result is None
        assert "NoneType" in caplog.text

    def test_rejects_int_when_list_expected(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = validate_protocol_message(42, [list])
        assert result is None
