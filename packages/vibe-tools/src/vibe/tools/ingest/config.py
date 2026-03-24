"""Configuration for ingestion pipelines."""

import os
import re

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

# Exclude pre-release, test, and RC tags
EXCLUDE_PATTERNS = re.compile(r"-(test|rc\d*|beta|alpha|pre|dev|min\d*|prototype)[-.]")

TAG_PATTERNS: dict[str, re.Pattern[str]] = {
    # cardano-node: clean semver only (e.g., 10.6.2)
    "cardano-node": re.compile(r"^\d+\.\d+\.\d+$"),
    # cardano-ledger: legacy spec tags + per-era package releases
    "cardano-ledger": re.compile(
        r"^cardano-ledger-spec-"
        r"|^release/"
        r"|^cardano-ledger-(conway|babbage|alonzo|shelley|allegra|mary|core|binary|api)-\d"
    ),
    # ouroboros-network: only the main ouroboros-network package tags
    "ouroboros-network": re.compile(r"^ouroboros-network-\d"),
    # ouroboros-consensus: both old and new naming conventions
    "ouroboros-consensus": re.compile(r"^ouroboros-consensus-\d|^release-ouroboros-consensus"),
    # plutus: clean 4-part semver only
    "plutus": re.compile(r"^\d+\.\d+\.\d+\.\d+$"),
    # formal-ledger-specs: conway versions
    "formal-ledger-specs": re.compile(r"^conway-v"),
}

# Maximum number of tags to index per repo.
# Keeps ingestion manageable for repos with hundreds of sub-package tags
# (e.g., cardano-ledger has 237 release tags). Only the N most recent
# by git commit date are indexed. Set to None for no limit.
MAX_TAGS_PER_REPO: dict[str, int | None] = {
    "cardano-node": 10,  # well-indexed already (99 tags), just keep recent
    "cardano-ledger": 20,  # was 3 tags, need modern eras
    "ouroboros-network": 10,  # well-indexed (52 tags), just keep recent
    "ouroboros-consensus": 15,  # was 6 tags, need modern consensus
    "plutus": 10,  # well-indexed (67 tags), just keep recent
    "formal-ledger-specs": None,  # only 3 tags total
}
