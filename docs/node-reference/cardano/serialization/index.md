# Serialization

CBOR encoding and decoding for all Cardano eras — blocks, headers, transactions, and witnesses.

## Modules

### Block

Block and header CBOR decoding across all eras (Byron through Conway). Includes block hash computation.

::: vibe.cardano.serialization.block
    options:
      show_source: false
      members_order: source

### Transaction

Transaction body and witness set decoding. Handles multi-era transaction formats.

::: vibe.cardano.serialization.transaction
    options:
      show_source: false
      members_order: source
