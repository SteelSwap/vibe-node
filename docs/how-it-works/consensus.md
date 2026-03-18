# Consensus

Every time you delegate your ADA to a stake pool, you're participating in consensus. Your delegation gives that pool a better chance of being selected to create the next block — and that selection process is at the heart of how Cardano agrees on a single version of history.

## How the Network Agrees

Cardano uses a consensus protocol called **Ouroboros Praos**. Its job is to answer two fundamental questions: *who gets to make the next block?* and *which chain is the real one when there's a disagreement?*

Time on Cardano is divided into **slots** (one per second) and **epochs** (432,000 slots, or about 5 days). Every slot is an opportunity for a block to be created, but most slots are empty — only about 5% of slots actually produce a block. This is by design: spacing out blocks gives the network time to propagate each one before the next arrives.

At each slot, every stake pool secretly runs a **VRF lottery** (Verifiable Random Function). The pool combines its private key with the slot number to produce a random output. If that output falls below a threshold determined by the pool's stake, the pool wins the right to produce a block. More stake means a lower threshold, which means a higher chance of winning — but it's still random. Small pools win too, just less often.

![Consensus](../assets/how-it-works/consensus.svg)

## Forks and Chain Selection

Sometimes two pools win the same slot and produce competing blocks. This creates a temporary **fork** — two versions of the chain that diverge at one point. The network resolves forks with a simple rule: **the longest chain wins**. Since each pool builds on the chain it knows about, the fork typically resolves within a few slots as one branch naturally gets more blocks added to it.

The **security parameter k** (set to 2160 on mainnet) defines how deep a block needs to be before it's considered final. Once 2160 blocks have been built on top of your transaction's block, it's permanent. No amount of forking can undo it. This gives Cardano strong settlement guarantees — after about 20 minutes, your transaction is set in stone.

## How It Connects

- Consensus receives new blocks from [**miniprotocols**](miniprotocols.md) (chain-sync and block-fetch) and decides whether they extend the best chain.
- Valid blocks are passed to the [**ledger**](ledger.md) to apply their transactions and update the chain state.
- When the node's pool wins a slot, consensus triggers [**block production**](block-production.md).
- The chain state is persisted by [**storage**](storage.md), including both the immutable history and the volatile tip.
