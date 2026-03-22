# Block Production & Validation Pipeline

This document traces the complete lifecycle of a Cardano block — from VRF leader election through forging, diffusion to peers, validation, and chain adoption. All references point to the Haskell implementation in `ouroboros-consensus` and `cardano-ledger`.

---

## Overview

```mermaid
flowchart TB
    subgraph Production ["Block Production (Forge Node)"]
        A[Slot Clock Tick] --> AA{mkCurrentBlockContext}
        AA -->|"Chain empty or tip in future"| A
        AA -->|"Got prev point + block number"| AB[Get LedgerState at prev point]
        AB --> AC{Ledger View Forecast}
        AC -->|"Too far behind tip → SKIP"| A
        AC -->|"Within forecast window"| B{checkIsLeader}
        B -->|Not Leader| A
        B -->|Leader| C[Tick LedgerState to current slot]
        C --> CC[Get Mempool Snapshot]
        CC --> D[Build Block Body from Txs]
        D --> E[Build Header Body]
        E --> F[KES Sign Header]
        F --> G[Assemble Block]
        G --> H[verifyBlockIntegrity]
        H --> I[addBlock to ChainDB]
    end

    subgraph Diffusion ["Block Diffusion (Network)"]
        I --> J[ChainDB Follower Notified]
        J --> K[Chain-Sync Server: MsgRollForward header]
        K --> L[Peer: Block-Fetch Client requests range]
        L --> M[Block-Fetch Server: stream block body]
    end

    subgraph Adoption ["Block Adoption (Receiving Node)"]
        M --> N[addBlockAsync to ChainDB]
        N --> O[Store in VolatileDB]
        O --> P[Chain Selection]
        P --> Q{Better than current?}
        Q -->|No| R[Keep current chain]
        Q -->|Yes| S[Validate via Ledger]
        S --> T{Valid?}
        T -->|No| U[Mark Invalid]
        T -->|Yes| V[Switch to new chain]
        V --> W[Update LedgerDB]
        W --> X[Notify Followers]
    end
```

---

## 1. Sync Gate (Must Be Caught Up Before Forging)

The Haskell forge loop does **not** have an explicit "am I synced?" check. Instead, it uses an implicit gate via the ledger view forecast.

```mermaid
flowchart LR
    A[Current Slot] --> B[Read ChainDB tip]
    B --> C["gap = currentSlot - tipSlot"]
    C --> D{"gap < 3k/f slots?"}
    D -->|Yes: within forecast window| E[Proceed to leader check]
    D -->|"No: too far behind"| F["TraceNoLedgerView → skip slot"]
```

**Haskell source:** `Ouroboros.Consensus.NodeKernel.forkBlockForging` (line 608-627)

At each slot, the forge loop:

1. **`mkCurrentBlockContext`** (line 574) — reads `ChainDB.getCurrentChain` to find the tip. If the chain is empty or the tip's slot is >= currentSlot, the forge exits early (`TraceSlotIsImmutable` or `TraceBlockFromFuture`).

2. **`getReadOnlyForkerAtPoint`** (line 594) — gets a ledger state snapshot at the previous block's point. If the chain switched and that point is no longer on it, gives up (`TraceNoLedgerState`).

3. **`ledgerViewForecastAt`** (line 608-627) — computes the protocol-level ledger view for the current slot. The forecast has a limited window: at most `3k/f` slots from the tip. On mainnet (`k=2160, f=0.05`): ~129,600 slots (~36 hours). On our devnet (`k=10, f=0.1`): ~300 slots (~60 seconds). **If the node is further behind than this, the forecast fails and the forge loop skips the slot** with `TraceNoLedgerView`.

This means the node naturally stops forging when it's far behind the chain tip, and resumes when it catches up. There is no explicit GSM check in the forge path — the GSM (`PreSyncing` / `Syncing` / `CaughtUp`) is used by the diffusion layer for peer selection, not by the forge loop.

**Implication for vibe-node:** Our forge loop must read `prev_hash` and `block_number` from ChainDB's current chain — NOT from an isolated counter. And we must skip forging when ChainDB's tip is more than `3k/f` slots behind the current wall-clock slot.

---

## 2. Leader Election

At each slot boundary, the node checks whether it is elected to produce a block.

```mermaid
flowchart LR
    A[Current Slot] --> B[Compute VRF Input]
    B --> C["alpha = mkSeed seedEta slot eta0"]
    C --> D[VRF.eval sk alpha]
    D --> E["certifiedOutput = (proof, hash)"]
    E --> F{checkLeaderValue}
    F -->|"hash/2^512 < 1-(1-f)^sigma"| G[ELECTED]
    F -->|Above threshold| H[Not Leader]
```

**Haskell source:** `Ouroboros.Consensus.Protocol.TPraos.checkIsLeader` (vendor/ouroboros-consensus)

**Inputs:**
- `slot` — current slot number
- `eta0` — epoch nonce (evolves at epoch boundaries)
- `sk` — VRF secret key
- `sigma` — pool's relative stake (from 2-epoch-old snapshot)
- `f` — active slot coefficient (0.05 on mainnet)

**Two VRF evaluations:**
1. `seedEta` — for nonce contribution (accumulated into next epoch's nonce)
2. `seedL` — for leader eligibility check

The leader threshold check is: `certifiedNat(vrfOutput) / 2^512 < 1 - (1 - f)^sigma`

This is the Praos `φ(sigma)` function — the probability that a pool with relative stake `sigma` leads this slot.

---

## 3. Block Forging

Once elected, the node constructs a block from the current ledger state and mempool.

```mermaid
flowchart TB
    subgraph Inputs
        A[Ticked LedgerState]
        B[Mempool Txs]
        C[IsLeader Proof]
        D[Hot KES Key]
        E[Operational Cert]
    end

    subgraph "Body Construction"
        B --> F[mkBasicBlockBody]
        F --> G[Set txSeq from mempool]
        G --> H["hashBlockBody → bodyHash"]
        G --> I["bBodySize → bodySize"]
    end

    subgraph "Header Construction"
        H --> J[BHBody]
        I --> J
        J --> K["Fields: prevHash, issuerVK, vrfVK,
                 slot, blockNo, vrfEta, vrfL,
                 bodySize, bodyHash, oCert, protVer"]
        K --> L["KES.sign hotKey headerBody"]
        L --> M["Header = (BHBody, KES Signature)"]
    end

    subgraph "Assembly"
        M --> N["Block = (Header, Body)"]
        N --> O["verifyBlockIntegrity"]
        O --> P["Return ForgedBlock"]
    end
```

**Haskell source:** `Ouroboros.Consensus.Shelley.Ledger.Forge.forgeShelleyBlock`

### Header Body Fields (BHBody)

The header body is a CBOR array with these fields in order:

| # | Field | Type | Source |
|---|-------|------|--------|
| 0 | `bheaderBlockNo` | `BlockNo` | Previous block number + 1 |
| 1 | `bheaderSlotNo` | `SlotNo` | Current slot |
| 2 | `bheaderPrev` | `PrevHash` | Hash of previous block header |
| 3 | `bheaderVk` | `VKey` | Pool cold verification key |
| 4 | `bheaderVrfVk` | `VerKeyVRF` | VRF verification key |
| 5 | `bheaderEta` / `vrfResult` | `CertifiedVRF` | VRF nonce + leader proof |
| 6 | `bsize` | `Word32` | Block body size in bytes |
| 7 | `bhash` | `Hash` | Blake2b-256 of block body |
| 8-11 | `bheaderOCert` | `OCert` | 4 inline fields: kes_vk, n, c0, sigma |
| 12-13 | `bprotver` | `ProtVer` | Major + minor protocol version |

**Note:** Babbage+ uses a single `vrfResult` field (index 5) instead of separate `bheaderEta` and `bheaderL` fields. The format changed at the Babbage hard fork.

### Block Hash Computation

The **block hash** (used for identification in Points and chain-sync) is:

```
blockHash = Blake2b-256(CBOR(header))
```

Where `header = [headerBody, kesSignature]` — the full header including the KES signature. This is the `ShelleyHash` type in Haskell, computed as `hashAnnotated` over the memoized CBOR bytes.

---

## 4. Block Diffusion

After forging, the block must reach other nodes via the network layer.

```mermaid
sequenceDiagram
    participant Forge as Forge Loop
    participant CDB as ChainDB
    participant Vol as VolatileDB
    participant Fol as Follower
    participant CSS as Chain-Sync Server
    participant Peer as Remote Peer
    participant BFS as Block-Fetch Server

    Forge->>CDB: addBlockAsync(block)
    CDB->>Vol: putBlock(block)
    CDB->>CDB: chainSelectionForBlock
    CDB->>Fol: notify tip change
    Fol->>CSS: AddBlock(header)
    CSS->>Peer: MsgRollForward(header, tip)
    Peer->>BFS: MsgRequestRange(from, to)
    BFS->>CDB: stream(from, to)
    CDB-->>BFS: Iterator[blocks]
    BFS->>Peer: MsgStartBatch
    BFS->>Peer: MsgBlock(block) × N
    BFS->>Peer: MsgBatchDone
```

**Key mechanism:** ChainDB maintains **Followers** — subscriber handles that receive chain updates. Each connected peer has a chain-sync server with its own follower. When ChainDB's selected chain changes (new block adopted), all followers are notified, and the chain-sync servers send `MsgRollForward` with the new header.

**Haskell source:**
- Chain-sync server: `Ouroboros.Consensus.MiniProtocol.ChainSync.Server`
- Block-fetch server: `Ouroboros.Consensus.MiniProtocol.BlockFetch.Server`
- ChainDB follower: `Ouroboros.Consensus.Storage.ChainDB.Impl.Follower`

---

## 5. Block Validation (Receiving Node)

When a block arrives from a peer, it goes through a multi-stage validation pipeline.

```mermaid
flowchart TB
    A[Block arrives via Block-Fetch] --> B[addBlockAsync]
    B --> C{Already in VolatileDB?}
    C -->|Yes| D[Skip - duplicate]
    C -->|No| E{Older than immutable tip?}
    E -->|Yes| F[Skip - too old]
    E -->|No| G{Known invalid?}
    G -->|Yes| H[Skip - previously rejected]
    G -->|No| I[Store in VolatileDB]

    I --> J[Chain Selection]
    J --> K[Construct candidate chains]
    K --> L{Any better than current?}
    L -->|No| M[Keep current chain]
    L -->|Yes| N[Validate candidate]

    subgraph Validation ["Full Validation"]
        N --> O["Tick: applyChainTickLedgerResult
              (advance slot, epoch boundary)"]
        O --> P["Header: validateHeader
              (envelope checks, slot/blockNo sequence)"]
        P --> Q["Protocol: updateChainDepState
              (VRF verify, KES verify, nonce update)"]
        Q --> R["Body: applyBlockEither
              (BBODY rule — all transactions)"]
    end

    R --> S{All valid?}
    S -->|No| T[Mark block + descendants invalid]
    S -->|Yes| U[Switch chain]
    U --> V[Commit new LedgerState]
    V --> W[GC old blocks from VolatileDB]
    W --> X[Advance ImmutableDB tip]
```

**Haskell source:** `Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel`

### 5a. Header Validation

Basic structural checks before fetching the full block body:

1. **Slot progression** — slot must be > previous block's slot
2. **Block number progression** — must be exactly previous + 1
3. **Protocol envelope** — header size within limits, VRF/KES field sizes correct

### 5b. Protocol State Transition (PRTCL Rule)

Verifies the consensus-layer fields in the header:

1. **VRF verification** — VRF proof verifies against the pool's registered VRF key
2. **VRF leader check** — output satisfies `φ(sigma)` threshold
3. **KES signature** — header body signature verifies against the opcert's KES key
4. **OCert validation** — cert counter is non-decreasing, KES period is valid
5. **Nonce accumulation** — VRF output folded into epoch nonce accumulator

**Haskell source:** `Cardano.Protocol.TPraos.Rules.Prtcl`

### 5c. Block Body Validation (BBODY Rule)

Full ledger validation of all transactions in the block:

1. **Body hash** — CBOR hash of body matches header's `bhash`
2. **Body size** — actual size matches header's `bsize`
3. **Transaction validation** (per era):
   - UTXO rules (value preservation, fee adequacy, TTL)
   - UTXOW rules (witness verification)
   - Script evaluation (Alonzo+ Plutus)
   - Governance (Conway)
4. **State transitions** — apply all valid transactions to produce new ledger state

---

## 6. Chain Selection

When multiple valid chains exist (forks), the node selects the best one.

```mermaid
flowchart TB
    A[Candidate Chains from VolatileDB] --> B[Filter: only those extending immutable chain]
    B --> C[Filter: only those better than current]
    C --> D{How to compare?}

    D --> E["Standard Praos:
    1. Longer chain wins (more blocks)
    2. Equal length: higher slot tip wins
    3. Equal slot: lower VRF value wins"]

    D --> F["With Peras (experimental):
    Weighted chain comparison
    using certificate weights"]

    E --> G[Validate best candidate]
    F --> G
    G --> H{Valid?}
    H -->|Yes| I[Switch to candidate]
    H -->|No| J[Try next best]
```

**The SelectView for Praos includes:**
- Block number (higher = more blocks = better)
- Slot number (for tiebreaking)
- VRF tiebreaker value (lower = wins tie)

**Haskell source:** `Ouroboros.Consensus.Util.AnchoredFragment.preferAnchoredCandidate`

---

## Summary: What Must Be True for Block Acceptance

For a remote node to adopt a block we produce, ALL of these must hold:

1. **VRF proof verifies** — our VRF proof for the slot must verify against our registered VRF key with the correct epoch nonce
2. **Leader threshold met** — the VRF output must satisfy `φ(sigma)` for our pool's stake
3. **KES signature valid** — the header must be signed with a KES key matching the opcert
4. **OCert valid** — cert counter non-decreasing, KES period within range
5. **prev_hash correct** — must point to a block the receiving node knows about (on their current chain)
6. **block_number correct** — must be exactly prev_block_number + 1
7. **Body valid** — all transactions pass ledger rules
8. **Chain is preferred** — the chain including our block must be longer/better than their current chain

**If any of these fail, the block is rejected.**
