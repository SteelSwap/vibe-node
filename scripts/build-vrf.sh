#!/usr/bin/env bash
# build-vrf.sh — Build the VRF native extension for development
#
# This compiles the pybind11 wrapper around IOG libsodium and copies
# the .so into the source tree so editable installs pick it up.
#
# Usage:
#   ./scripts/build-vrf.sh
#
# Prerequisites:
#   - git submodule initialized: git submodule update --init vendor/libsodium-iog
#   - C/C++ compiler (clang or gcc)
#   - make

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="$REPO_ROOT/packages/vibe-cardano"
CRYPTO_DIR="$PKG_DIR/src/vibe/cardano/crypto"
LIBSODIUM_DIR="$REPO_ROOT/vendor/libsodium-iog"

# Check submodule
if [ ! -f "$LIBSODIUM_DIR/configure" ]; then
    echo "Initializing libsodium-iog submodule..."
    git -C "$REPO_ROOT" submodule update --init vendor/libsodium-iog
fi

# Check for existing build
if [ -f "$CRYPTO_DIR/_vrf_native"*.so ] 2>/dev/null; then
    echo "VRF native extension already built. To rebuild, delete:"
    ls "$CRYPTO_DIR"/_vrf_native*.so
    echo "Then re-run this script."
    exit 0
fi

echo "=== Building VRF native extension ==="

# Ensure build deps
uv pip install pybind11 cmake 2>/dev/null || pip install pybind11 cmake

# Build with CMake
cd "$PKG_DIR"
cmake -B build -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -5
cmake --build build -j$(nproc 2>/dev/null || sysctl -n hw.ncpu) 2>&1 | tail -5

# Copy to source tree for editable installs
cp build/_vrf_native*.so "$CRYPTO_DIR/"

echo ""
echo "=== VRF native extension built ==="
uv run python -c "from vibe.cardano.crypto.vrf import HAS_VRF_NATIVE; print(f'HAS_VRF_NATIVE = {HAS_VRF_NATIVE}')"
