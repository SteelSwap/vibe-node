# uplc Fork Plan

## Package Info
- **Current version:** 1.3.2
- **PyPI:** https://pypi.org/project/uplc/
- **Source:** https://github.com/OpShin/uplc
- **Our usage:** 2 files (plutus/evaluate.py, plutus/context.py), 6 import sites

## Bug #1: Haskell string escape sequences not parsed (string-04 conformance)

**File:** `uplc/parser.py` + `uplc/lexer.py`

**Problem:** The UPLC parser uses Python's string handling for escape sequences, which supports `\t`, `\n`, `\xNN` (hex) but NOT Haskell's `\DDD` (decimal) and `\oOOO` (octal) formats.

**Input:** `(con string "\t\"\83\x75\x63\o143e\x73s\o041\o042\n")`
**Expected:** `\t"Success!"\n`
**Actual:** `\t"\83uc\o143ess\o041\o042\n` (decimal/octal escapes left as literals)

**Missing escape handling:**
- `\DDD` — decimal character code (e.g., `\83` = `S`, `\10` = newline)
- `\oOOO` — octal character code (e.g., `\o143` = `c`, `\o041` = `!`)

**Fix:** Add a post-processing step after the lexer captures the string to expand Haskell-style escapes:
```python
import re

def _expand_haskell_escapes(s: str) -> str:
    """Expand Haskell string escape sequences not handled by Python."""
    # \oOOO — octal
    s = re.sub(r'\\o([0-7]+)', lambda m: chr(int(m.group(1), 8)), s)
    # \DDD — decimal (but not \x, \n, \t, etc.)
    s = re.sub(r'\\(\d+)', lambda m: chr(int(m.group(1), 10)), s)
    return s
```

Apply this in the parser where `BuiltinString` values are constructed (parser.py:456-457).

## Bug #2: Cost model parameter injection API missing

**File:** `uplc/cost_model.py`

**Problem:** No clean API to inject on-chain cost model parameters. We use hardcoded defaults. Our `evaluate.py:99-100` has a TODO for this.

**Fix:** Add `CostModel.from_params(param_vector: list[int])` class method that overrides individual cost parameters.

## Bug #3: string-04 conformance test failure

This is a direct consequence of Bug #1. The conformance test at `tests/conformance/test_uplc_conformance.py` runs the Plutus conformance suite and `string-04` fails because `\83` and `\o143` aren't expanded.

## Fork Steps

1. Fork https://github.com/OpShin/uplc to SteelSwap/uplc
2. Add `_expand_haskell_escapes()` to parser
3. Add cost model parameter injection API
4. Run full conformance suite — verify string-04 passes
5. Open upstream PR
6. Update vibe-node pyproject.toml to point to fork
