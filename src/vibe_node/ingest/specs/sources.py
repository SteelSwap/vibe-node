"""Registry of spec sources to ingest."""

from dataclasses import dataclass


@dataclass
class SpecSource:
    """A spec document source to ingest."""
    source_repo: str        # e.g. "IntersectMBO/ouroboros-consensus"
    submodule_path: str     # e.g. "vendor/ouroboros-consensus"
    spec_glob: str          # e.g. "docs/website/contents/**/*.md"
    format: str             # markdown, cddl, latex, agda
    era: str                # byron, shelley, conway, multi-era, etc.
    root_file: str | None = None  # For LaTeX: main .tex file


# Ordered by implementation priority — easiest formats first
SPEC_SOURCES: list[SpecSource] = [
    # ── Markdown sources (Phase 1 — zero external deps) ────────────
    SpecSource(
        source_repo="IntersectMBO/ouroboros-consensus",
        submodule_path="vendor/ouroboros-consensus",
        spec_glob="docs/website/contents/**/*.md",
        format="markdown",
        era="multi-era",
    ),

    # ── CDDL sources (Phase 2 — plain text) ────────────────────────
    SpecSource(
        source_repo="IntersectMBO/cardano-ledger",
        submodule_path="vendor/cardano-ledger",
        spec_glob="shelley/**/cddl-files/*.cddl",
        format="cddl",
        era="shelley",
    ),
    SpecSource(
        source_repo="IntersectMBO/cardano-ledger",
        submodule_path="vendor/cardano-ledger",
        spec_glob="byron/cddl-spec/*.cddl",
        format="cddl",
        era="byron",
    ),

    # ── LaTeX sources (Phase 3 — needs pandoc) ──────────────────────
    SpecSource(
        source_repo="IntersectMBO/cardano-ledger",
        submodule_path="vendor/cardano-ledger",
        spec_glob="shelley/chain-and-ledger/formal-spec/*.tex",
        format="latex",
        era="shelley",
        root_file="shelley/chain-and-ledger/formal-spec/shelley-ledger.tex",
    ),
    SpecSource(
        source_repo="IntersectMBO/cardano-ledger",
        submodule_path="vendor/cardano-ledger",
        spec_glob="shelley/design-spec/*.tex",
        format="latex",
        era="shelley",
        root_file="shelley/design-spec/shelley-delegation.tex",
    ),
    SpecSource(
        source_repo="IntersectMBO/cardano-ledger",
        submodule_path="vendor/cardano-ledger",
        spec_glob="byron/ledger/formal-spec/*.tex",
        format="latex",
        era="byron",
        root_file="byron/ledger/formal-spec/byron-ledger.tex",
    ),
    SpecSource(
        source_repo="IntersectMBO/cardano-ledger",
        submodule_path="vendor/cardano-ledger",
        spec_glob="byron/chain/formal-spec/*.tex",
        format="latex",
        era="byron",
        root_file="byron/chain/formal-spec/byron-blockchain.tex",
    ),
    SpecSource(
        source_repo="IntersectMBO/cardano-ledger",
        submodule_path="vendor/cardano-ledger",
        spec_glob="shelley-mc/formal-spec/*.tex",
        format="latex",
        era="shelley-ma",
        root_file="shelley-mc/formal-spec/mary-ledger.tex",
    ),
    SpecSource(
        source_repo="IntersectMBO/cardano-ledger",
        submodule_path="vendor/cardano-ledger",
        spec_glob="goguen/formal-spec/*.tex",
        format="latex",
        era="alonzo",
        root_file="goguen/formal-spec/alonzo-ledger.tex",
    ),
    SpecSource(
        source_repo="IntersectMBO/ouroboros-network",
        submodule_path="vendor/ouroboros-network",
        spec_glob="docs/network-spec/*.tex",
        format="latex",
        era="multi-era",
        root_file="docs/network-spec/network-spec.tex",
    ),
    SpecSource(
        source_repo="IntersectMBO/ouroboros-network",
        submodule_path="vendor/ouroboros-network",
        spec_glob="docs/network-design/*.tex",
        format="latex",
        era="multi-era",
        root_file="docs/network-design/network-design.tex",
    ),
    SpecSource(
        source_repo="IntersectMBO/ouroboros-consensus",
        submodule_path="vendor/ouroboros-consensus",
        spec_glob="docs/report/**/*.tex",
        format="latex",
        era="multi-era",
    ),
    SpecSource(
        source_repo="IntersectMBO/plutus",
        submodule_path="vendor/plutus",
        spec_glob="doc/plutus-core-spec/*.tex",
        format="latex",
        era="plutus",
        root_file="doc/plutus-core-spec/plutus-core-specification.tex",
    ),

    # ── Agda sources (Phase 4 — literate Agda) ─────────────────────
    SpecSource(
        source_repo="IntersectMBO/formal-ledger-specifications",
        submodule_path="vendor/formal-ledger-specs",
        spec_glob="src/Ledger/**/*.lagda",
        format="agda",
        era="conway",
    ),
]
