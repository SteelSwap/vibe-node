# The Challenge

This project is a response to **Pi Lanningham's (Quantumplation) open challenge**: vibe-code a spec-compliant Cardano node from scratch.

## The Rules

1. The entire git history is visible from day one
2. 90% of commits include the model name, prompt context, and a `Co-Authored-By` tag
3. If written in a language used by an existing alternative node, MOSS and JPlag scores must show low structural similarity
4. All of the above are subject to reasonable third-party review

## Acceptance Criteria

The node must:

1. **Sync** from a recent mainnet Mithril snapshot or genesis to tip
2. **Produce valid blocks** accepted by other nodes on preview/preprod
3. **Implement all node-to-node miniprotocols** (chain-sync, block-fetch, tx-submission, keep-alive)
4. **Implement all node-to-client miniprotocols** (local chain-sync, local tx-submission, local state-query, local tx-monitor)
5. **Run in a private devnet** alongside 2 Haskell nodes
6. **Match or beat** the Haskell node in average memory usage across 10 days
7. **Agree on tip selection** within 2160 slots for 10 continuous days
8. **Recover from power-loss** without human intervention
9. **Agree with the Haskell node** on all block validity, transaction validity, and chain-tip selection

## No Other Node Implementations

We may NOT reference, use, or be influenced by any alternative Cardano node implementation — Amaru (Rust), Dingo (Go), Dolos (Rust), or any other. The only permitted sources are:

1. The published specifications (formal specs, CIPs, Ouroboros papers, CDDL schemas)
2. The Haskell cardano-node and its ecosystem (cardano-ledger, ouroboros-network, ouroboros-consensus, plutus)

This ensures our Python implementation is original by construction and demonstrates that the specs + reference implementation are sufficient to build a conformant node.

## The Prize

$5,000 in USDCx or USDM, plus a campaign for retroactive funding from the treasury.

## The Deadline

Deliver before Amaru or Dingo claim mainnet readiness, or within one year — whichever is later.

## Why Python?

Python avoids the MOSS/JPlag concern entirely — no existing alternative Cardano node uses it. Our implementation is original by construction.
