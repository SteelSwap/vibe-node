# cbor2pure Round-Trip Issue: Indefinite-Length Encoding Lost

## Problem

cbor2pure decodes indefinite-length CBOR containers (arrays, maps, bytestrings) into plain Python types (list, dict, bytes), losing the encoding form. Re-encoding always produces definite-length output. This breaks byte-level round-trip fidelity.

**This is critical for Cardano** where block hashes, transaction hashes, and VRF inputs all depend on exact byte-level reproduction of CBOR.

## Demonstration

```python
import cbor2pure as cbor2

# Indefinite array [1,2,3]: 9F 01 02 03 FF (5 bytes)
original = bytes.fromhex("9f010203ff")
decoded = cbor2.loads(original)      # [1, 2, 3] — plain list
reencoded = cbor2.dumps(decoded)     # 83 01 02 03 (4 bytes, definite)
assert original != reencoded         # HASH MISMATCH
```

Same issue affects:
- Indefinite maps (`BF ... FF` → `A2 ...`)
- Indefinite bytestrings (`5F ... FF` → `44 ...`)

## Impact on vibe-node

In `node/run.py:571`, we re-encode blocks after partial decode:
```python
raw_block = cbor2.dumps(cbor2.CBORTag(era_tag, block_body))
```

If `block_body` was decoded from Haskell CBOR that used indefinite-length containers, the re-encoded bytes will differ, producing a different block hash.

## Existing Support

cbor2's encoder has `indefinite_containers=True` but it's all-or-nothing — encodes ALL containers as indefinite. What we need is per-value preservation.

## Proposed Fix

Add wrapper types that preserve encoding form through decode/encode:

```python
class IndefiniteArray(list):
    """A list that was decoded from an indefinite-length CBOR array."""
    pass

class IndefiniteMap(dict):
    """A dict that was decoded from an indefinite-length CBOR map."""
    pass

class IndefiniteByteString(bytes):
    """Bytes decoded from an indefinite-length CBOR byte string."""
    # Also needs to preserve the chunk boundaries
    chunks: list[bytes]
```

**Decoder changes:**
- `decode_array()` returns `IndefiniteArray` for indefinite-length arrays
- `decode_map()` returns `IndefiniteMap` for indefinite-length maps
- `decode_bytestring()` returns `IndefiniteByteString` for chunked bytestrings

**Encoder changes:**
- `encode_array()` checks `isinstance(value, IndefiniteArray)` → encode as indefinite
- `encode_map()` checks `isinstance(value, IndefiniteMap)` → encode as indefinite
- `encode_bytestring()` checks `isinstance(value, IndefiniteByteString)` → encode chunks

**Backward compatible:** Subclasses of list/dict/bytes, so all existing code that checks `isinstance(x, list)` still works. Only the encoder behavior changes when it detects the subclass.
