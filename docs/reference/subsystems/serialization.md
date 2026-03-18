# CBOR / Serialization

## Overview
Binary encoding and decoding for blocks, transactions, headers, and protocol messages using CBOR. Each era has its own CDDL schema defining the wire format.

## Governing Specs
| Spec Source | Key Sections |
|-------------|-------------|
| CDDL schemas per era (byron.cddl, shelley.cddl, etc.) | See [specs index](../../specs/index.md) |

## Haskell Package Structure
libs/cardano-ledger-binary (583 functions). Era-specific CDDL schemas in each era's package.

## Module Decomposition
- CBOR codec framework
- CDDL schema validation
- Era-specific encoders/decoders
- Block and header serialization
- Transaction serialization
- Protocol message codecs (for miniprotocols)

## Library Recommendations
*To be populated during Phase 1 analysis (M1.8)*

## Test Strategy
*To be populated during Phase 1 analysis (M1.8)*

## Phase Assignment
**Implementation Phase:** 2
