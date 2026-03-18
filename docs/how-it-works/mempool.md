# Mempool

Every transaction you submit goes through a waiting room before it makes it into a block. That waiting room is the mempool — and it's where your transaction sits between "submitted" and "confirmed."

## The Waiting Room

When you send a transaction from your wallet, it doesn't go directly into a block. First, your local node validates it against the current [ledger rules](ledger.md). If it passes, it enters the mempool — a holding area for valid-but-unconfirmed transactions. From there, the transaction is shared with other nodes via the [tx-submission miniprotocol](miniprotocols.md), and their mempools fill up too.

The mempool has a size limit. It can't grow forever or it would consume all available memory. When the mempool is full and a new valid transaction arrives, older transactions may be evicted to make room. This is why transactions with higher fees tend to be processed more reliably during periods of high network activity.

When a block producer wins a slot, it reaches into the mempool and selects transactions to include in the new block, typically preferring transactions that maximize fee revenue while fitting within the block size limit.

![Mempool](../assets/how-it-works/mempool.svg)

## Staying Fresh

The mempool isn't just a passive queue — it actively maintains its state. When a new block arrives from the network, the mempool removes every transaction that was included in that block. It also removes transactions that would now be invalid because a block consumed the same UTxO they were trying to spend (conflicting transactions).

This "scrubbing" process happens every time the chain tip advances. The result is that the mempool always reflects transactions that are valid against the *current* chain state, not some stale version. If the chain rolls back due to a fork, the mempool even re-validates and potentially re-admits transactions from the abandoned branch.

## How It Connects

- Transactions enter the mempool from [**miniprotocols**](miniprotocols.md) — tx-submission (from peers) and local tx-submission (from wallets).
- Each incoming transaction is validated by the [**ledger rules**](ledger.md) before being accepted.
- [**Block production**](block-production.md) selects transactions from the mempool when forging a new block.
- The mempool is synchronized with [**consensus**](consensus.md) — it knows which chain tip is current and scrubs accordingly.
