"""Map Haskell module paths and file paths to Cardano eras.

Used by the code indexing pipeline to tag every code chunk with the era
it belongs to, enabling era-filtered search across the knowledge base.
"""

import re

# Ordered list of (pattern, era) — first match wins.
# Patterns are checked against both the module name and the file path.
_MODULE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Cardano\.Ledger\.Byron|\.Byron\b"), "byron"),
    (re.compile(r"Cardano\.Ledger\.Allegra"), "allegra"),
    (re.compile(r"Cardano\.Ledger\.ShelleyMA|Cardano\.Ledger\.Mary"), "mary"),
    (re.compile(r"Cardano\.Ledger\.Shelley|Shelley\.Spec"), "shelley"),
    (re.compile(r"Cardano\.Ledger\.Alonzo"), "alonzo"),
    (re.compile(r"Cardano\.Ledger\.Babbage"), "babbage"),
    (re.compile(r"Cardano\.Ledger\.Conway"), "conway"),
    (re.compile(r"Ouroboros\.Consensus"), "consensus"),
    (re.compile(r"Ouroboros\.Network"), "network"),
    (re.compile(r"PlutusCore|UntypedPlutusCore"), "plutus"),
]

# Path-based fallbacks (checked against file_path with forward slashes).
_PATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/byron/", re.IGNORECASE), "byron"),
    (re.compile(r"/allegra/", re.IGNORECASE), "allegra"),
    (re.compile(r"/mary/", re.IGNORECASE), "mary"),
    (re.compile(r"/shelley-ma/|/shelleyma/", re.IGNORECASE), "mary"),
    (re.compile(r"/shelley/", re.IGNORECASE), "shelley"),
    (re.compile(r"/alonzo/", re.IGNORECASE), "alonzo"),
    (re.compile(r"/babbage/", re.IGNORECASE), "babbage"),
    (re.compile(r"/conway/", re.IGNORECASE), "conway"),
    (re.compile(r"/plutus-core/|/plutus/", re.IGNORECASE), "plutus"),
    (re.compile(r"/consensus/", re.IGNORECASE), "consensus"),
    (re.compile(r"/network/", re.IGNORECASE), "network"),
]


def infer_era(module_name: str, file_path: str) -> str:
    """Map a Haskell module path to a Cardano era.

    Checks the fully-qualified module name first, then falls back to
    directory-based heuristics on the file path. Returns ``"generic"``
    if no era can be determined.
    """
    for pattern, era in _MODULE_PATTERNS:
        if pattern.search(module_name):
            return era

    normalised = file_path.replace("\\", "/")
    for pattern, era in _PATH_PATTERNS:
        if pattern.search(normalised):
            return era

    return "generic"
