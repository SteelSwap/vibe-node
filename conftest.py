"""Root conftest — auto-detect system crypto libraries."""

import os
import sys


def _find_libsecp256k1() -> str | None:
    """Find libsecp256k1 shared library on the system."""
    if sys.platform == "darwin":
        candidates = [
            "/opt/homebrew/lib/libsecp256k1.dylib",
            "/usr/local/lib/libsecp256k1.dylib",
        ]
    else:
        candidates = [
            "/usr/lib/x86_64-linux-gnu/libsecp256k1.so.2",
            "/usr/lib/x86_64-linux-gnu/libsecp256k1.so",
            "/usr/lib/libsecp256k1.so",
            "/usr/local/lib/libsecp256k1.so",
        ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# Auto-set PYSECP_SO if not already configured
if "PYSECP_SO" not in os.environ:
    path = _find_libsecp256k1()
    if path:
        os.environ["PYSECP_SO"] = path
