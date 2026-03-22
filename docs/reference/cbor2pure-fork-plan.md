# cbor2pure Fork Plan

## Package Info
- **Current version:** 5.8.0
- **PyPI:** https://pypi.org/project/cbor2pure/
- **Source:** https://github.com/agronholm/cbor2 (cbor2pure is the pure-Python subset)
- **Our usage:** 23 files, 141 call sites (88 dumps, 42 loads, 9 CBORTag, 1 CBORDecoder)

## Bug #1: Semantic tag decoders fire before tag_hook (CRITICAL)

**File:** `cbor2pure/_decoder.py:479-491`

**Problem:** `decode_semantic()` calls hardcoded semantic decoders for tags 0-5 (datetime, bignum, etc.) BEFORE checking `tag_hook`. Cardano uses CBOR tags 0-7 for era identification (not semantic types), so decoding a Cardano block with tag 0 crashes with `TypeError: expected string or bytes-like object, got 'list'`.

**Reproduction:**
```python
import cbor2pure as cbor2
raw = bytes([0xc0, 0x83, 0x01, 0x02, 0x03])  # tag(0) + [1,2,3]
cbor2.loads(raw)  # TypeError!
cbor2.loads(raw, tag_hook=lambda d, t: t)  # ALSO TypeError — hook never called
```

**Fix:** When `tag_hook` is set, skip semantic decoders:
```python
def decode_semantic(self, subtype: int) -> Any:
    tagnum = self._decode_length(subtype)
    if not self._tag_hook:
        if semantic_decoder := semantic_decoders.get(tagnum):
            return semantic_decoder(self)

    tag = CBORTag(tagnum, None)
    self.set_shareable(tag)
    tag.value = self._decode(unshared=True)
    if self._tag_hook:
        tag = self._tag_hook(self, tag)

    return self.set_shareable(tag)
```

**Impact:** Eliminates `_strip_tag()` workarounds in block.py and transaction.py.

## Bug #2: No indefinite-length list/map encoding API (MINOR)

**Problem:** No API to encode indefinite-length CBOR arrays. Haskell uses indefinite-length for tx-submission.

**Impact:** Would fix definite-length workaround in `network/txsubmission.py:188-202`.

## Fork Steps

1. Fork https://github.com/agronholm/cbor2 to SteelSwap/cbor2
2. Apply Bug #1 fix
3. Add test for tag_hook with semantic tags
4. Open upstream PR
5. Update vibe-node pyproject.toml to point to fork
6. Remove `_strip_tag()` workarounds
7. Run full test suite
