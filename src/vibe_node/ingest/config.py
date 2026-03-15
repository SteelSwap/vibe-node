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
