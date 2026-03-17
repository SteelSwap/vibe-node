# Specifications & Gap Analysis

This section hosts the Cardano protocol specifications we track and the gap analysis documenting where the published specs diverge from the Haskell node implementation.

## Specifications

We ingest and index specifications from 17+ sources across 6 repositories, covering every era from Byron to Conway/Dijkstra. Formats include LaTeX formal specs, Literate Agda, CDDL binary schemas, Markdown, and PDF.

All specs are searchable via the knowledge base — use `vibe-node db search "query"` to find relevant sections across all indexed documents.

### Sources by Era

| Era | Primary Source | Format |
|-----|---------------|--------|
| Byron | cardano-ledger `byron/` | LaTeX |
| Shelley | cardano-ledger `shelley/` | LaTeX |
| Mary/Allegra | cardano-ledger `shelley-mc/` | LaTeX |
| Alonzo | cardano-ledger `goguen/` | LaTeX |
| Conway/Dijkstra | formal-ledger-specifications | Literate Agda |
| Consensus | ouroboros-consensus `docs/` | LaTeX + Markdown |
| Networking | ouroboros-network `docs/` | LaTeX |
| Plutus | plutus `doc/` | LaTeX |
| Cross-era | CIPs, CDDL schemas | Markdown, CDDL |

## Gap Analysis

- **[Methodology & Entries](gap-analysis.md)** — The spec is the ideal, the code is the reality, the gap is the measured delta

Gap analysis is not a discrete phase — it is a discipline woven into every development step. Entries appear here as we implement each subsystem and observe divergences.
