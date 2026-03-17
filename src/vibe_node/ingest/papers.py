"""Ouroboros and Cardano research paper catalog.

Canonical list of papers relevant to node implementation,
with IACR ePrint URLs for stable PDF downloads.
"""

from dataclasses import dataclass


@dataclass
class Paper:
    """A research paper to download and ingest."""
    name: str
    url: str
    filename: str
    year: int
    era: str
    relevance: str


# Papers ordered by implementation priority
PAPERS: list[Paper] = [
    # ── Core Consensus (must-read) ──────────────────────────────
    Paper(
        name="Ouroboros: A Provably Secure Proof-of-Stake Blockchain Protocol",
        url="https://eprint.iacr.org/2016/889.pdf",
        filename="ouroboros-classic-2016.pdf",
        year=2016,
        era="multi-era",
        relevance="Foundational PoS consensus. VRF-based slot leadership, chain selection.",
    ),
    Paper(
        name="Ouroboros Praos: Adaptively-Secure Semi-Synchronous PoS",
        url="https://eprint.iacr.org/2017/573.pdf",
        filename="ouroboros-praos-2017.pdf",
        year=2017,
        era="multi-era",
        relevance="Current Cardano consensus protocol. Adaptive corruption, forward-secure KES.",
    ),
    Paper(
        name="Ouroboros Genesis: Composable PoS with Dynamic Availability",
        url="https://eprint.iacr.org/2018/378.pdf",
        filename="ouroboros-genesis-2018.pdf",
        year=2018,
        era="multi-era",
        relevance="Bootstrapping from genesis without trusted checkpoints. Full node sync.",
    ),
    Paper(
        name="Ouroboros BFT: Simple Byzantine Fault Tolerant Consensus",
        url="https://eprint.iacr.org/2018/1049.pdf",
        filename="ouroboros-bft-2018.pdf",
        year=2018,
        era="byron",
        relevance="Used in Byron-to-Shelley hard fork transition.",
    ),
    Paper(
        name="Ouroboros Chronos: Permissionless Clock Synchronization via PoS",
        url="https://eprint.iacr.org/2019/838.pdf",
        filename="ouroboros-chronos-2019.pdf",
        year=2019,
        era="multi-era",
        relevance="Clock synchronization and time assumptions for slot timing.",
    ),

    # ── Ledger & UTxO ───────────────────────────────────────────
    Paper(
        name="Formal Specification of the Cardano Blockchain Ledger (Agda)",
        url="https://drops.dagstuhl.de/storage/01oasics/oasics-vol118-fmbc2024/OASIcs.FMBC.2024.2/OASIcs.FMBC.2024.2.pdf",
        filename="cardano-ledger-formal-agda-2024.pdf",
        year=2024,
        era="conway",
        relevance="Machine-verified formal spec. Transaction validation, governance.",
    ),
    Paper(
        name="The Extended UTXO Model",
        url="https://omelkonian.github.io/data/publications/eutxo.pdf",
        filename="eutxo-model.pdf",
        year=2020,
        era="alonzo",
        relevance="Formal EUTXO definition. Plutus script integration, tx inputs/outputs.",
    ),
    Paper(
        name="Efficient State Management in Distributed Ledgers",
        url="https://eprint.iacr.org/2021/183.pdf",
        filename="efficient-state-mgmt-2021.pdf",
        year=2021,
        era="multi-era",
        relevance="UTxO set optimization and state management.",
    ),

    # ── Implementation Architecture ──────────────────────────────
    Paper(
        name="Cardano Consensus and Storage Layer (Technical Report)",
        url="https://ouroboros-consensus.cardano.intersectmbo.org/pdfs/report.pdf",
        filename="consensus-storage-report.pdf",
        year=2023,
        era="multi-era",
        relevance="Consensus layer architecture, storage, chain selection. Direct implementation reference.",
    ),
]
