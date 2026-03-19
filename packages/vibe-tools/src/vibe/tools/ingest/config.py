"""Configuration for ingestion pipelines."""

import os

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

GITHUB_REPOS = [
    "IntersectMBO/cardano-node",
    "IntersectMBO/cardano-ledger",
    "IntersectMBO/ouroboros-network",
    "IntersectMBO/ouroboros-consensus",
    "IntersectMBO/plutus",
    "IntersectMBO/formal-ledger-specifications",
    "cardano-foundation/CIPs",
]

# ── Code indexing: vendor submodule paths ────────────────────────────

CODE_REPOS: dict[str, str] = {
    "cardano-node": "vendor/cardano-node",
    "cardano-ledger": "vendor/cardano-ledger",
    "ouroboros-network": "vendor/ouroboros-network",
    "ouroboros-consensus": "vendor/ouroboros-consensus",
    "plutus": "vendor/plutus",
    "formal-ledger-specs": "vendor/formal-ledger-specs",
}

# Regex patterns for filtering release tags per repo.
# Only tags matching the pattern are processed — keeps out
# pre-release noise, component sub-tags, etc.
import re  # noqa: E402

TAG_PATTERNS: dict[str, re.Pattern[str]] = {
    "cardano-node": re.compile(r"^\d+\.\d+\.\d+$"),
    "cardano-ledger": re.compile(r"^cardano-ledger-spec-|^release/"),
    "ouroboros-network": re.compile(r"^ouroboros-network-\d"),
    "ouroboros-consensus": re.compile(r"^ouroboros-consensus-\d"),
    "plutus": re.compile(r"^\d+\.\d+\.\d+\.\d+$"),
    "formal-ledger-specs": re.compile(r"^conway-v"),
}
