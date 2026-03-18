# Specifications & Gap Analysis

This section hosts the Cardano protocol specifications we track and the gap analysis documenting where the published specs diverge from the Haskell node implementation.

## Specifications

We ingest and index specifications from 17+ sources across 6 repositories, covering every era from Byron to Conway/Dijkstra. Formats include LaTeX formal specs, Literate Agda, CDDL binary schemas, Markdown, and PDF.

All specs are searchable via the knowledge base — use `vibe-node db search "query"` to find relevant sections across all indexed documents.

### Browse by Subsystem

- **[Foundations](foundations/index.md)** — Crypto primitives, notation, addresses, base types, introductions, properties & proofs (46 documents)
- **[Serialization](serialization/index.md)** — CDDL schemas, CBOR encoding, flat serialization (7 documents)
- **[Transactions](transactions/index.md)** — UTxO rules, transaction formats, witnesses, scripts, multi-asset, fees (18 documents)
- **[Ledger](ledger/index.md)** — Ledger state transitions, delegation, protocol parameters, epoch/rewards, chain layer (26 documents)
- **[Consensus](consensus/index.md)** — Ouroboros protocol, chain selection, Genesis, era-specific consensus (43 documents)
- **[Storage](storage/index.md)** — ImmutableDB, VolatileDB, LedgerDB, ChainDB (6 documents)
- **[Networking](networking/index.md)** — Multiplexer, miniprotocols, connection management (9 documents)
- **[Plutus](plutus/index.md)** — Plutus Core grammar, CEK machine, builtins, cost models (6 documents)
- **[Governance](governance/index.md)** — Conway governance, ratification, enactment, voting (4 documents)
- **[Papers](papers/index.md)** — Full research papers (2 documents)

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
