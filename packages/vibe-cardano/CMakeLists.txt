# CMakeLists.txt — Build the _vrf_native pybind11 extension for vibe-cardano.
#
# This builds two things:
#   1. The IOG libsodium fork from vendor/libsodium-iog/ (static library)
#   2. The _vrf_native Python extension module linking against it
#
# Usage with scikit-build-core (recommended):
#   pip install . -v
#
# Usage standalone (for development):
#   cmake -B build -DCMAKE_BUILD_TYPE=Release
#   cmake --build build
#   cp build/_vrf_native*.so src/vibe/cardano/crypto/
#
# Prerequisites:
#   - pybind11 (pip install pybind11)
#   - autotools (autoconf, automake, libtool) for libsodium build
#   - C/C++ compiler with C++17 support

cmake_minimum_required(VERSION 3.18)
project(vibe_cardano_vrf LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# The IOG libsodium fork lives in vendor/ at the repo root.
# When building via scikit-build-core, CMAKE_SOURCE_DIR is packages/vibe-cardano/
# so we navigate up to the repo root.
set(REPO_ROOT "${CMAKE_SOURCE_DIR}/../..")
get_filename_component(REPO_ROOT "${REPO_ROOT}" ABSOLUTE)
set(LIBSODIUM_SRC "${REPO_ROOT}/vendor/libsodium-iog")
set(LIBSODIUM_PREFIX "${CMAKE_BINARY_DIR}/libsodium-install")

# ---------------------------------------------------------------------------
# Build libsodium from source (static, with VRF support)
# ---------------------------------------------------------------------------

include(ExternalProject)

ExternalProject_Add(
    libsodium_iog
    SOURCE_DIR "${LIBSODIUM_SRC}"
    CONFIGURE_COMMAND
        "${LIBSODIUM_SRC}/configure"
        "--prefix=${LIBSODIUM_PREFIX}"
        "--disable-shared"
        "--enable-static"
        "--with-pic"
        "--disable-dependency-tracking"
    BUILD_COMMAND make -j4
    INSTALL_COMMAND make install
    BUILD_IN_SOURCE 0
    BUILD_BYPRODUCTS "${LIBSODIUM_PREFIX}/lib/libsodium.a"
)

# Create an imported target for the static libsodium.
# Note: We use IMPORTED_LOCATION but NOT INTERFACE_INCLUDE_DIRECTORIES
# because CMake validates that path at configure time (before ExternalProject
# has built libsodium). Instead we pass the include dir via
# target_include_directories on the consuming target.
add_library(sodium STATIC IMPORTED)
set_target_properties(sodium PROPERTIES
    IMPORTED_LOCATION "${LIBSODIUM_PREFIX}/lib/libsodium.a"
)
add_dependencies(sodium libsodium_iog)

# Ensure the include directory exists so CMake doesn't complain.
file(MAKE_DIRECTORY "${LIBSODIUM_PREFIX}/include")

# ---------------------------------------------------------------------------
# Find pybind11
# ---------------------------------------------------------------------------

find_package(pybind11 CONFIG REQUIRED)

# ---------------------------------------------------------------------------
# Build the _vrf_native extension module
# ---------------------------------------------------------------------------

pybind11_add_module(_vrf_native
    src/vibe/cardano/crypto/_vrf_native.cpp
)

target_link_libraries(_vrf_native PRIVATE sodium)
target_include_directories(_vrf_native PRIVATE
    "${LIBSODIUM_PREFIX}/include"
)
add_dependencies(_vrf_native libsodium_iog)

# scikit-build-core handles installation. For standalone builds,
# the .so lands in the build directory — copy it manually.
install(TARGETS _vrf_native
    LIBRARY DESTINATION vibe/cardano/crypto
)
