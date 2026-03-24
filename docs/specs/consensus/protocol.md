# Consensus Protocol
## Overview

### Chain selection
Chain selection is the process of choosing between multiple competing chains, and is one of the most important responsibilities of a consensus protocol. When choosing between two chains, in theory any part of those chains could be relevant; indeed, the research literature typically describes chain selection as a comparison of two entire chains (\[bft-paper,praos-paper\]{reference-type="ref+label" reference="bft-paper,praos-paper"}). In practice that is not realistic: the node has to do chain selection frequently, and scanning millions of blocks each time to make the comparison is of course out of the question.

The consensus layer keeps the most recent headers as a *chain fragment* in memory (\[storage:inmemory\]{reference-type="ref+label" reference="storage:inmemory"}); the rest of the chain is stored on disk. Similarly, we keep a chain fragment of headers in memory for every (upstream) node whose chain we are following and whose blocks we may wish to adopt (\[chainsyncclient\]{reference-type="ref+label" reference="chainsyncclient"}). Before the introduction of the hard fork combinator chain selection used to be given these fragments to compare; as we will discuss in \[hfc:intro\]{reference-type="ref+label" reference="hfc:intro"}, however, this does not scale so well to hybrid chains.

It turns out, however, that it suffices to look only at the headers at the very tip of the chain, at least for the class of consensus algorithms we need to support. The exact information we need about that tip varies from one protocol to the other, but at least for the Ouroboros family of consensus protocols the essence is always the same: we prefer longer chains over shorter ones (justifying *why* this is the right choice is the domain of cryptographic research and well outside the scope of this report). In the simplest case, the length of the chain is *all* that matters, and hence the only thing we need to know about the blocks at the tips of the chains is their block numbers.[^1]

This does beg the question of how to compare two chains when one (or both) of them are empty, since now we have no header to compare. We will resolve this by stating the following fundamental assumption about *all* chain selection algorithms supported by the consensus layer:

<!-- assumption -->
[]{#prefer-extension label="prefer-extension"} The extension of a chain is always preferred over that chain.

A direct consequence of \[prefer-extension\]{reference-type="ref+label" reference="prefer-extension"} is that a non-empty chain is always preferred over an empty one,[^2] but we will actually need something stronger than that: we insist that shorter chains can never be preferred over longer ones:

<!-- assumption -->
[]{#never-shrink label="never-shrink"} A shorter chain is never preferred over a longer chain.

\[never-shrink\]{reference-type="ref+Label" reference="never-shrink"} does not say anything about chains of equal length; this will be important for Praos ([1.6](#praos){reference-type="ref+label" reference="praos"}). An important side-note here is that the Ouroboros Genesis consensus protocol includes a chain selection rule (the genesis rule) that violates \[never-shrink\]{reference-type="ref+label" reference="never-shrink"} (though not \[prefer-extension\]{reference-type="ref+label" reference="prefer-extension"}); it also cannot be defined by only looking at the tips of chains. It will therefore require special treatment; we will come back to this in \[genesis\]{reference-type="ref+label" reference="genesis"}.

### The security parameter $k$
When the Cardano blockchain was first launched, it was using a consensus protocol that we now refer to as Ouroboros Classic [@cryptoeprint:2016:889]. The re-implementation of the consensus layer never had support for Ouroboros Classic, instead using Ouroboros BFT [@cryptoeprint:2018:1049] as a transitional protocol towards Ouroboros Praos [@cryptoeprint:2017:573], which is the consensus protocol in use at the time of writing, with plans to switch to Ouroboros Genesis [@cryptoeprint:2018:378] relatively soon (\[genesis\]{reference-type="ref+label" reference="genesis"}).

Both Ouroboros Classic and Ouroboros Praos are based on a chain selection rule that imposes a maximum rollback condition: alternative chains to a node's current chain that fork off more than a certain number of blocks ago are never considered for adoption. This limit is known as the *security parameter*, and is usually denoted by $k$; at present $k = 2160$ blocks. The Ouroboros analysis shows that consensus will be reached despite this maximum rollback limitation; indeed, this maximum rollback is *required* in order to reach consensus (we discuss this in some detail in \[genesis:background:longest-chain\]{reference-type="ref+label" reference="genesis:background:longest-chain"}).

For Ouroboros BFT and Ouroboros Genesis the situation is slightly different:

- Ouroboros BFT does not impose a maximum rollback, but adding such a requirement does not change the protocol in any fundamental way: the analysis for Ouroboros Praos shows that nodes will not diverge more than $k$ blocks, and since BFT converges much quicker than that, adding this (large) maximum rollback requirement does not change anything.

- The analysis that shows that nodes will not diverge by more than $k$ blocks does of course not apply to new nodes joining the system. Indeed, when using Ouroboros Praos, such nodes are vulnerable to an attack where an adversary with some stake (does not have to be much) presents the newly joining node with a chain that diverges by more than $k$ blocks from the honest chain, at which point point the node would become unable to switch to the real chain. Solving this is the purview of Ouroboros Genesis.

  Like Ouroboros BFT, Ouroboros Genesis likewise does not impose a maximum rollback, *but* the analysis [@cryptoeprint:2018:378] shows that when nodes are up to date, they can employ the Ouroboros Praos rule (i.e., the rule *with* the maximum rollback requirement). This is not true when the node is behind and is catching up, but the main goal of \[genesis\]{reference-type="ref+label" reference="genesis"} is to show how we can nonetheless avoid rollbacks exceeding $k$ blocks even when a node is catching up.

Within the consensus layer we therefore assume that we *always* have a limit $k$ on the number of blocks we might have to rollback. We take advantage of this in many ways; here we just mention a few:

- We use it as an organising principle in the storage layer (\[storage\]{reference-type="ref+label" reference="storage"}), dividing the chain into a part that we know is stable (the \"immutable chain\"), and a part near the tip that is still subject to rollback (the \"volatile chain\"). Block lookup into the immutable chain is very efficient, and since the vast majority of the chain is immutable, this helps improve overall efficiency of the system.

- When we switch to a new fork by rolling back and then adopting some new blocks, those new blocks must be verified against the ledger state as it was at the point we rolled back to. This means we must be able to construct historical ledger states. In principle this is always possible, as we can always replay the entire chain, but doing so would be expensive. However, since we have a limit on the maximum rollback, we also have a limit on how old the oldest ledger state is we might have to reconstruct; we take advantage of this in the Ledger Database (\[ledgerdb\]{reference-type="ref+label" reference="ledgerdb"}) which can efficiently reconstruct any of those $k$ historical ledger states.

- We need to keep track of the chains of our peer nodes in order to be able to decide whether or not we might wish to switch to those chains (\[chainsyncclient\]{reference-type="ref+label" reference="chainsyncclient"}). For consensus protocols based on a longest chain rule (such as Ouroboros Praos), this means that we would need to download and verify enough blocks from those alternative chains that the alternative chain becomes longer than our own. Without a maximum rollback, this would be an unbounded amount of work as well as an unbounded amount of data we would have to store. A maximum rollback of $k$, however, means that validating (and storing) $k+1$ blocks should be sufficient.[^3]

Of course, a maximum rollback may be problematic in the case of severe network outages that partition the nodes for extended periods of time (in the order of days). When this happens, the chains will diverge and recovering converge will need manual intervention; this is true for any of the consensus protocols mentioned above. This manual intervention is outside the scope of this report.

## The `ConsensusProtocol` Class
We model consensus protocols as a single class called `ConsensusProtocol`; this class can be considered to be the central class within the consensus layer.

    class (..) => ConsensusProtocol p where

The type variable $p$ is a type-level tag describing a particular consensus protocol; if Haskell had open kinds[^4], we could say `(p<!-- ConsensusProtocol -->

    data family ConsensusConfig p<!-- Type -->

This allows the protocol to depend on some static configuration data; what configuration data is required will vary from protocol to protocol.[^5] The rest of the consensus layer does not really do much with this configuration, except make it available where required; however, we do require that whatever the configuration is, we can extract $k$ from it:

    protocolSecurityParam<!-- ConsensusConfig -->

For example, this is used by the chain database to determine when blocks can be moved from the volatile DB to the immutable DB (\[storage:components\]{reference-type="ref+label" reference="storage:components"}). In the rest of this section we will consider the various parts of the `ConsensusProtocol` class one by one.

### Chain selection
As mentioned in 1.1.1{reference-type="ref+label" reference="consensus:overview:chainsel"}, chain selection will only look at the headers at the tip of the ledger. Since we are defining consensus protocols independent from a concrete choice of ledger, however (\[decouple-consensus-ledger\]{reference-type="ref+label" reference="decouple-consensus-ledger"}), we cannot use a concrete block or header type. Instead, we merely say that the chain selection requires *some* view on headers that it needs to make its decisions:

    type family SelectView p<!-- Type -->
    type SelectView p = BlockNo

The default is `BlockNo` because as we have seen this is all that is required for the most important chain selection rule, simply preferring longer chains over shorter ones. It is the responsibility of the glue code that connects a specific choice of ledger to a consensus protocol to define the projection from a concrete block type to this `SelectView` (1.3). We then require that these views must be comparable

    class (Ord (SelectView p), ..) => ConsensusProtocol p where

and say that one chain is (strictly) preferred over another if its `SelectView` is greater. If two chains terminate in headers with the *same* view, neither chain is preferred over the other, and we could pick either one (we say they are equally preferable).

Later in this chapter we will discuss in detail how our treatment of consensus algorithms differs from the research literature (\[bft,praos\]{reference-type="ref+label" reference="bft,praos"}), and in \[chainsel\]{reference-type="ref+label" reference="chainsel"} we will see how the details of how chain selection is implemented in the chain database; it is worth pointing out here, however, that the comparison based on `SelectView` is not intended to capture

- chain validity

- the intersection point (checking that the intersection point is not too far back, preserving the invariant that we never roll back more than $k$ blocks, see 1.1.2{reference-type="ref+label" reference="consensus:overview:k"})

Both of these responsibilities would require more than seeing just the tip of the chains. They are handled independent of the choice of consensus protocol by the chain database, as discussed in \[chainsel\]{reference-type="ref+label" reference="chainsel"}.

When two *candidate* chains (that is, two chains that aren't our current) are equally preferable, we are free to choose either one. However, when a candidate chain is equally preferable to our current, we *must* stick with our current chain. This is true for all Ouroboros consensus protocols, and we define it once and for all:

    preferCandidate ::
         ConsensusProtocol p
      => proxy      p
      -> SelectView p  -- ^ Tip of our chain
      -> SelectView p  -- ^ Tip of the candidate
      -> Bool
    preferCandidate _ ours cand = cand > ours

### Ledger view
We mentioned in \[overview:ledger\]{reference-type="ref+label" reference="overview:ledger"} that some consensus protocols may require limited information from the ledger; for instance, the Praos consensus protocol needs access to the stake distribution for the leadership check. In the `ConsensusProtocol` abstraction, this is modelled as a *view* on the ledger state

    type family LedgerView p<!-- Type -->

The ledger view will be required in only one function: when we "tick" the state of the consensus protocol. We will discuss this state management in more detail next.

### Protocol state management
Each consensus protocol has its own type chain dependent state[^6]

    type family ChainDepState p<!-- Type -->

The state must be updated with each block that comes in, but just like for chain selection, we don't work with a concrete block type but instead define a *view* on blocks that is used to update the consensus state:

    type family ValidateView p<!-- Type -->

We're referring to this as the `ValidateView` because updating the consensus state also serves as *validation* of (that part of) the block; consequently, validation can also *fail*, with protocol specific error messages:

    type family ValidationErr p<!-- Type -->

Updating the chain dependent state now comes as a pair of functions. As for the ledger (\[overview:ledger\]{reference-type="ref+label" reference="overview:ledger"}), we first *tick* the protocol state to the appropriate slot, passing the already ticked ledger view as an argument:[^7]

    tickChainDepState ::
         ConsensusConfig p
      -> Ticked (LedgerView p)
      -> SlotNo
      -> ChainDepState p
      -> Ticked (ChainDepState p)

As an example, the Praos consensus protocol ([1.6](#praos){reference-type="ref+label" reference="praos"}) derives its randomness from the chain itself. It does that by maintaining a set of random numbers called *nonces*, which are used as seeds to pseudo-random number generators. Every so often the current nonce is swapped out for a new one; this does not depend on the specific block, but merely on a certain slot number being reached, and hence is an example of something that the ticking function should do.

The (validation view on) a block can then be applied to the already ticked protocol state:

    updateChainDepState ::
         ConsensusConfig       p
      -> ValidateView          p
      -> SlotNo
      -> Ticked (ChainDepState p)
      -> Except (ValidationErr p) (ChainDepState p)

Finally, there is a variant of this function that can we used to *reapply* a known-to-be-valid block, potentially skipping expensive cryptographic checks, merely computing what the new state is:

    reupdateChainDepState ::
         ConsensusConfig       p
      -> ValidateView          p
      -> SlotNo
      -> Ticked (ChainDepState p)
      -> ChainDepState         p

Re-applying previously-validated blocks happens when we are replaying blocks from the immutable database when initialising the in-memory ledger state (\[ledgerdb:on-disk:initialisation\]{reference-type="ref+label" reference="ledgerdb:on-disk:initialisation"}). It is also useful during chain selection (\[chainsel\]{reference-type="ref+label" reference="chainsel"}): depending on the consensus protocol, we may end up switching relatively frequently between short-lived forks; when this happens, skipping expensive checks can improve the performance of the node.

### Leader selection
The final responsibility of the consensus protocol is leader selection. First, it is entirely possible for nodes to track the blockchain without ever producing any blocks themselves; indeed, this will be the case for the majority of nodes[^8] In order for a node to be able to lead at all, it may need access to keys and other configuration data; the exact nature of what is required is different from protocol to protocol, and so we model this as a type family

    type family CanBeLeader p<!-- Type -->

A value of `CanBeLeader` merely indicates that the node has the required configuration to lead at all. It does *not* necessarily mean that the node has the right to lead in any particular slot; *this* is indicated by a value of type `IsLeader`:

    type family IsLeader p<!-- Type -->

In simple cases `IsLeader` can just be a unit value ("yes, you are a leader now") but for more sophisticated consensus protocols such as Praos this will be a cryptographic proof that the node indeed has the right to lead in this slot. Checking whether a that *can* lead *should* lead in a given slot is the responsibility of the final function in this class:

    checkIsLeader ::
         ConsensusConfig       p
      -> CanBeLeader           p
      -> SlotNo
      -> Ticked (ChainDepState p)
      -> Maybe (IsLeader       p)

## Connecting a block to a protocol
Although a single consensus protocol might be used with many blocks, any given block is designed for a *single* consensus protocol. The following type family witnesses this relation:[^9]

    type family BlockProtocol blk<!-- Type -->

Of course, for the block to be usable with that consensus protocol, we need functions that construct the `SelectView` (1.2.1{reference-type="ref+label" reference="consensus:class:chainsel"}) and `ValidateView` (1.2.3{reference-type="ref+label" reference="consensus:class:state"}) projections from that block:

    class (..) => BlockSupportsProtocol blk where
      validateView ::
           BlockConfig blk
        -> Header blk -> ValidateView (BlockProtocol blk)

      selectView ::
           BlockConfig blk
        -> Header blk -> SelectView (BlockProtocol blk)

The `BlockConfig` is the static configuration required to work with blocks of this type; it's just another data family:

    data family BlockConfig blk<!-- Type -->

## Design decisions constraining the Ouroboros protocol family
TODO: Perhaps we should move this to conclusions; some of these requirements may only become clear in later chapters (like the forecasting range).

TODO: The purpose of this section should be to highlight design decisions we're already covering in this chapter that impose constraints on existing or future members of the Ouroboros protocol family.

For example, we at least have:

- max-K rollback, we insist that there be a maximum rollback length. This was true for Ouroboros Classic, but is not true for Praos/Genesis, nevertheless we insist on this for our design. We should say why this is so helpful for our design. We should also admit that this is a fundamental decision on liveness vs consistency, and that we're picking consistency over liveness. The Ouroboros family is more liberal and different members of that family can and do make different choices, so some adaptation of protocols in papers may be needed to fit this design decision. In particular this is the case for Genesis. We cannot implement Genesis as described since it is not compatible with a rollback limit.

- We insist that we can compare chains based only on their tips. For example even length is a property of the whole chain not a block, but we insist that chains include their length into the blocks in a verifiable way, which enables this tip-only checking. Future Ouroboros family members may need some adaptation to fit into this constraint. In particular the Genesis rule as described really is a whole chain thing. Some creativity is needed to fit Genesis into our framework: e.g. perhaps seeing it not as a chain selection rule at all but as a different (coordinated) mode for following headers.

- We insist that a strict extension of a chain is always preferred over that chain.

- We insist that we never roll back to a strictly shorter chain.

- The minimum cyclic data dependency time: the minimum time we permit between some data going onto the chain and it affecting the validity of blocks or the choices made by chain selection. This one is a constraint on both the consensus algorithm and the ledger rules. For example this constrains the Praos epoch structure, but also ledger rules like the Shelley rule on when genesis key delegations or VRF key updates take effect. We should cover why we have this constraint: arising from wanting to do header validation sufficiently in advance of block download and validation that we can see that there's a potential longer valid chain.

- The ledger must be able to look ahead sufficiently to validate $k + 1$ headers (to guarantee a roll back of $k$). TODO: We should discuss this in more detail.

## Permissive BFT
Defined in [@byron-chain-spec] Not to be confused with "Practical BFT" [@10.1145/571637.571640]

### Background
Discuss *why* we started with Permissive BFT (backwards compatible with Ouroboros Classic).

### Implementation

### Relation to the paper
Permissive BFT is a variation on Ouroboros BFT, defined in [@cryptoeprint:2018:1049]. We have included the main protocol description from that paper as 1.1{reference-type="ref+label" reference="figure:bft"} in this document; the only difference is that we've added a few additional labels so we can refer to specific parts of the protocol description below.

It will be immediately obvious from 1.1{reference-type="ref+label" reference="figure:bft"} that this description covers significantly more than what we consider to be part of the consensus protocol proper here. We will discuss the various parts of the BFT protocol description below.

Clock update and network delivery

:   The BFT specification requires that "with each advance of the clock (..) a collection of transactions and blockchains are pushed to the server". We consider neither block submission nor transaction submission to be within the scope of the consensus algorithm; see \[nonfunctional:network:blocksubmission,servers:blockfetch\]{reference-type="ref+label" reference="nonfunctional:network:blocksubmission,servers:blockfetch"} and \[nonfunctional:network:blocksubmission,servers:txsubmission\]{reference-type="ref+label" reference="nonfunctional:network:blocksubmission,servers:txsubmission"} instead, respectively.

Mempool update

:   (\[bft:mempool\]{reference-type="ref+label" reference="bft:mempool"}). The design of the mempool is the subject of \[mempool\]{reference-type="ref+label" reference="mempool"}. Here we only briefly comment on how it relates to what the BFT specification assumes:

    - *Consistency* ([\[bft:mempool:consistency\]](#bft:mempool:consistency){reference-type="ref+label" reference="bft:mempool:consistency"}). Our mempool does indeed ensure consistency. In fact, we require something strictly stronger; see [\[mempool:consistency\]](#mempool:consistency){reference-type="ref+label" reference="mempool:consistency"} for details.

    - *Time-to-live (TTL)* ([\[bft:mempool:ttl\]](#bft:mempool:ttl){reference-type="ref+label" reference="bft:mempool:ttl"}). The BFT specification requires that transactions stay in the mempool for a maximum of $u$ rounds, for some configurable $u$. Our current mempool does not have explicit support for a TTL parameter. The Shelley ledger will have support for TTL starting with the "Allegra" era, so that transactions are only valid within a certain slot window; this is part of the normal ledger rules however and requires no explicit support from the consensus layer. That's not to say that explicit support would not be useful; see [\[future:ttl\]](#future:ttl){reference-type="ref+label" reference="future:ttl"} in the chapter on future work.

    - *Receipts* ([\[bft:mempool:receipts\]](#bft:mempool:receipts){reference-type="ref+label" reference="bft:mempool:receipts"}). We do not offer any kind of receipts for inclusion in the mempool. Clients such as wallets must monitor the chain instead (see also [@wallet-spec]). The BFT specification marks this as optional so this is not a deviation.

Blockchain update

:   (\[bft:update\]{reference-type="ref+label" reference="bft:update"}). The BFT specification requires that the node prefers any valid chain over its own, as long as its strictly longer. *We do not satisfy this requirement.* The chain selection rule for Permissive BFT is indeed the longest chain rule, *but* consensus imposes a global maximum rollback (the security parameter $k$; 1.1.2{reference-type="ref+label" reference="consensus:overview:k"}). In other words, nodes *will* prefer longer chains over its own, *provided* that the intersection between that chain and the nodes own chain is no more than $k$ blocks away from the node's tip.

    Moreover, our definition of validity is also different. We do require that hashes line up ([\[bft:update:hash\]](#bft:update:hash){reference-type="ref+label" reference="bft:update:hash"}), although we do not consider this part of the responsibility of the consensus protocol, but instead require this independent of the choice of consensus protocol when updating the header state ([\[storage:headerstate\]](#storage:headerstate){reference-type="ref+label" reference="storage:headerstate"}). We do of course also require that the transactions in the block are valid ([\[bft:update:body\]](#bft:update:body){reference-type="ref+label" reference="bft:update:body"}), but this is the responsibility of the ledger layer instead ([\[ledger\]](#ledger){reference-type="ref+label" reference="ledger"}); the consensus protocol should be independent from what's stored in the block body.

    Permissive BFT is however different from BFT *by design* in the signatures we require.[^10] BFT requires that each block is signed strictly according to the round robin schedule ([\[bft:update:signatures\]](#bft:update:signatures){reference-type="ref+label" reference="bft:update:signatures"}); the whole point of *permissive* BFT is that we relax this requirement and merely require that blocks are signed by *any* of the known core nodes.

    Permissive BFT is however not *strictly* more permissive than BFT: although blocks do not need to be signed according to the round robin schedule, there is a limit on the number of signatures by any given node in a given window of blocks. When a node exceeds that threshold, its block is rejected as invalid. Currently that threshold is set to 0.22 [@byron-chain-spec Appendix A, Calculating the $t$ parameter], which was considered to be the smallest value that would be sufficiently unlikely to consider a chain generated by Ouroboros Classic as invalid ([1.5.1](#bft:background){reference-type="ref+label" reference="bft:background"}) and yet give as little leeway to a malicious node as possible. This has an unfortunate side effect, however. BFT can always recover from network partitions [@cryptoeprint:2018:1049 Section 1, Introduction], but this is not true for PBFT: in a setting with 7 core nodes (the same setting as considered in the PBFT specification), a 4:3 network partition would quickly lead to *both* partitions being unable to produce more blocks; after all, the nodes in the partition of 4 nodes would each sign 1/4th of the blocks, and the nodes in the partition of 3 nodes would each sign 1/3rd. Both partitions would therefore quickly stop producing blocks. Picking 0.25 for the threshold instead of 0.22 would alleviate this problem, and would still be conform the PBFT specification, which says that the value must be in the closed interval $[\frac{1}{5}, \frac{1}{4}]$. Since PBFT is however no longer required (the Byron era is past and fresh deployments would not need Permissive BFT but could use regular BFT), it's probably not worth reconsidering this, although it *is* relevant for the consensus tests ([\[testing:dire\]](#testing:dire){reference-type="ref+label" reference="testing:dire"}).

Blockchain extension

:   (\[bft:extension\]{reference-type="ref+label" reference="bft:extension"}). The leadership check implemented as part of PBFT is conform specification (\[bft:leadershipcheck\]{reference-type="ref+label" reference="bft:leadershipcheck"}). The rest of this section matches the implementation, modulo some details some of which we already alluded to above:

    - The block format is slightly different; for instance, we only have a single signature ([10](#footnote:singlesignature){reference-type="ref+label" reference="footnote:singlesignature"}).

    - Blocks in Byron have a maximum size, so we cannot necessarily take *all* valid transactions from the mempool.

    - Block diffusion is not limited to the suffix of the chain: clients can request *any* block that's on the chain. This is of course critical to allow nodes to join the network later, something which the BFT paper does not consider.

    It should also be pointed out that we consider neither block production nor block diffusion to be part of the consensus protocol at all; only the leadership check itself is.

Ledger reporting

:   . Although we do offer a way to query the state of the ledger (\[ledger:queries\]{reference-type="ref+label" reference="ledger:queries"}), we do not offer a query to distinguish between finalised/pending blocks. TODO: It's also not clear to me why the BFT specification would consider a block to be finalised as soon as it's $3t + 1$ blocks deep (where $t$ is the maximum number of core nodes). The paper claims that BFT can always recover from a network partition, and the chain selection rule in the paper requires supporting infinite rollback.


------------------------------------------------------------------------

**Parameters**:

  ----- -----------------------------------------------------------------------------------------------------------
   $n$  total number of core nodes
   $t$  maximum number of core nodes
        (we do not make this distinction between $n$ and $t$ in the consensus layer, effectively setting $n = t$)
   $u$  time to live (TTL) of a transaction
  ----- -----------------------------------------------------------------------------------------------------------

**Protocol**:\
The $i$-th server locally maintains a blockchain $B_0 B_1 \ldots B_l$, an ordered sequence of transactions called a mempool, and carries out the following protocol:

Clock update and network delivery

:   With each advance of the clock to a slot $\mathit{sl}_j$, a collection of transactions and blockchains are pushed to the server by the network layer. Following this, the server proceeds as follows:

    1.  **Mempool update**.[]{#bft:mempool label="bft:mempool"}

        1.  []{#bft:mempool:consistency label="bft:mempool:consistency"} Whenever a transaction $\mathit{tx}$ is received, it is added to the mempool as long as it is consistent with

            1.  the existing transactions in the mempool and

            2.  the contents of the local blockchain.

        2.  []{#bft:mempool:ttl label="bft:mempool:ttl"} The transaction is maintained in the mempool for $u$ rounds, where $u$ is a parameter.

        3.  []{#bft:mempool:receipts label="bft:mempool:receipts"} Optionally, when the transaction enters the mempool the server can return a signed receipt back to the client that is identified as the sender.

    2.  **Blockchain update**.[]{#bft:update label="bft:update"} Whenever the server becomes aware of an alternative blockchain $B_0 B_1' \ldots B'_s$ with $s > l$, it replaces its local chain with this new chain provided it is valid, i.e. each one of its blocks $(h, d, \mathit{sl}_j, \sigma_\mathit{sl}, \sigma_\mathrm{block})$

        1.  []{#bft:update:signatures label="bft:update:signatures"} contains proper signatures

            1.  one for time slot $\mathit{sl}_j$ and

            2.  one for the entire block

            by server $i$ such that $i - 1 = (j - 1) \bmod n$

        2.  []{#bft:update:hash label="bft:update:hash"} $h$ is the hash of the previous block, and

        3.  []{#bft:update:body label="bft:update:body"} $d$ is a valid sequence of transactions w.r.t. the ledger defined by the transactions found in the previous blocks

    3.  **Blockchain extension**.[]{#bft:extension label="bft:extension"} Finally, the server checks if it is responsible to issue the next block by testing if $$\begin{equation}
            i - 1 = (j - 1) \bmod n
          \label{bft:leadershipcheck}
        \end{equation}$$ In such case, this $i$-th server is the slot leader. It

        - collects the set $d$ of all valid transactions from its mempool and

        - appends the block $B_{l+1} = (h, d, \mathit{sl}_j, \sigma_\mathit{sl}, \sigma_\mathrm{block})$ to its blockchain, where $$\begin{equation*}
                \begin{split}
                \sigma_\mathit{sl}    & = \mathsf{Sign}_{\mathsf{sk}_i}(\mathit{sl}_j) \\
                \sigma_\mathrm{block} & = \mathsf{Sign}_{\mathsf{sk}_i}(h, d, \mathit{sl}_j, \sigma_\mathit{sl}) \\
                h                     & = H(B_l) \\
                \end{split}
          \end{equation*}$$ It then diffuses $B_{l+1}$ as well as any requested blocks from the suffix of its blockchain that covers the most recent $2t + 1$ slots.

Ledger Reporting

:   Whenever queried, the server reports as "finalised" the ledger of transactions contained in the blocks $B_0 \ldots B_m, m \le l$, where $B_m$ has a slot time stamp more than $3t + 1$ slots in the past. Blocks $B_{m+1} \ldots B_l$ are reported as "pending".

------------------------------------------------------------------------

**[]{#figure:bft label="figure:bft"}Ouroboros-BFT [@cryptoeprint:2018:1049 Figure 1]**

## Praos

TODO: Discuss $\Delta$: When relating the papers to the implementation, we loosely think of $\Delta$ as roughly having value 5, i.e., there is a maximum message delay of 5 slots. However, this link to the paper is tenuous at best: the messages the paper expects the system to send, and the messages that the system *actually* sends, are not at all the same. Defining how these relate more precisely would be critical for a more formal statement of equivalence between the paper and the implementation, but such a study is well outside the scope of this report.

### Active slot coefficient
### Implementation

### Relation to the paper
[@cryptoeprint:2018:378]

## Combinator: Override the leader schedule
## Separation of responsibility between consensus and ledger

### Vision

In the vision that underlies the abstract design of the consensus layer, the separation of responsibility between the consensus layer and the ledger layer happens along three axes.

<!-- description -->
Block *selection* versus block *contents*

The primary objective of the consensus layer is to ensure that *consensus* is reached: that is, everyone agrees on (a sufficiently long prefix of) the chain. From a sufficiently high vantage point, the consensus layer could reasonably be described as an implementation of the various Ouroboros papers (Praos, Genesis, etc.). A critical component of this is *chain selection*, choosing between competing chains. The consensus layer does not need to be aware of what is inside the blocks that it is choosing between.

By contrast, the ledger layer is not aware of multiple chains at all, and will never need to execute chain selection: it exclusively deals with linear histories. *Its* primary objective is to define the contents of blocks, along with rules that interpret those contents, computing the *ledger state*.

*Construction* versus *verification*

The ledger layer only ever deals with fully formed blocks. Its responsibility is to *verify* those blocks and describe how they transform the ledger state. But those blocks need to come from somewhere in the first place; block *construction* is the responsibility of the consensus layer. This dichotomy manifests itself in two ways:

- When the ledger layer verifies a block, it must verify whether or not the node that produced the block had the right to do so, that is, whether or not it was a slot leader in the block's slot (though it may be argued that this should be a consensus concern instead, see below). Typically, it will need only access to the node's *public* key to do so. Note that multiple nodes may have the right to produce a block in any given slot; the ledger layer is not checking for *the* slot leader, but rather for *a* slot leader.

  By contrast, the consensus layer is not checking if *some* node is a leader for slot, but rather whether *it* is a leader for the current slot, and if so, produce a block for that slot (along with evidence that it had the right to do so). Typically, it will need access to the node's *private* key in order to execute that check.

- Blocks are only valid with respect to a particular ledger state. Since blocks specify their predecessor (the predecessor hash), they also implicitly specify which ledger state they should be evaluated against: the ledger state that was the result of applying that predecessor block (or the genesis ledger state for the very first block).

  By contrast, when the consensus layer produces a block, it must construct a block that is valid with respect to the node's *current* ledger state, and *choose* the predecessor of that new block to be the tip of the node's current chain.

*Stateful* versus *stateless*

The ledger layer is entirely stateless: it is a pure function that accepts a ledger state and a block as input and produces the new ledger state (or an error if the block was invalid). State management is the responsibility of the consensus layer:

- The consensus layer must maintain the current ledger state, and pass that to the ledger layer when validating blocks that fit neatly onto the node's current tip. In addition, the consensus must provide efficient access to *historical* ledger states, so that it can validate (and possibly adopt) alternative forks of the chain.

- Although the consensus layer does not need to be aware of the exact nature of the block contents, it *does* have to collect these "transactions" and consider them when producing a block (the mempool, \[mempool\]{reference-type="ref+label" reference="mempool"}). If it chooses to do eager transaction validation (that is, before it actually produces a block), it will need support from the ledger layer to do; when producing a block, it will need assistance from the ledger layer to produce the block body.

  In both cases (transaction validation and block body construction), the consensus layer is responsible for passing an appropriate ledger state to the ledger layer. In the case of block production, the choice of ledger state is clear: the current ledger state. For the mempool, it is slightly less clear-cut; the mempool is effectively constructing a "virtual" block with a predecessor chosen from the node's current chain, near its tip.[^11]

Ideally, the implementation of a particular consensus protocol (say, Praos) should be usable with any choice of ledger (cryptocurrency or otherwise), and conversely, a particular ledger (say, Shelley) should be usable with any choice of consensus protocol (Praos, Genesis, or indeed a different consensus protocol entirely). The consensus protocol *does* need some limited information from the ledger, but we can provide this separately (\[ledger:api:LedgerSupportsProtocol\]{reference-type="ref+label" reference="ledger:api:LedgerSupportsProtocol"}), and abstract over what a particular consensus algorithm needs from the ledger layer it is used with (specifically, the `SelectView` and the `LedgerView`, discussed in \[consensus:class:chainsel,consensus:class:ledgerview\]{reference-type="ref+label" reference="consensus:class:chainsel,consensus:class:ledgerview"}).

### Practice

In practice, the separation is not quite so clean. Partly this is for historical reasons. When the Cardano blockchain was re-implemented, the new consensus layer and the new ledger layer were developed in tandem, and it was not always practical to have one wait for design decisions by the other. For example, most of Praos is currently implemented in the ledger layer, despite the ledger layer never having to do chain selection, ever. These are issues that we can resolve with some relatively minor refactoring.

More problematic is that the current ledgers are not designed to be parametric in a choice of consensus algorithm. Specifically, the Shelley ledger hardcodes Praos. At some level, that statement makes no sense: the ledger layer never needs to execute chain selection nor decide if it's a leader for a given slot. However, the *verification* of a block by the ledger layer currently includes verification of the cryptographic proof produced by the consensus layer when constructing a block. This is specific to Praos; other consensus algorithms may require entirely different fields in the block (header). So while the ledger layer is morally independent from the choice of consensus algorithm, in practice it includes just enough information that running it with a different consensus algorithm is difficult to do.

In an ideal world, the Shelley ledger would not be aware of the consensus algorithm at all. Since the implementation of the consensus protocol, and details of the fields required in blocks to support that protocol, are the responsibility of the consensus layer, it would make sense to move the leader verification check from the ledger layer into the consensus header check instead. Block assembly now becomes more of a joint effort between the consensus layer and the ledger layer: the ledger layer produces the block body and some fields in the block header[^12]), whereas the consensus layer produces the fields in the block header that are required by the consensus protocol.

Unfortunately, disentangling the two isn't *quite* that easy. In particular, the Shelley ledger supports key delegation, which is affecting the leadership check. Disentangling this would be non-trivial; it's not clear what consensus-protocol independent delegation would even *mean* and what kind of data it should carry. Solving this will probably require some parameterization in the *other* direction, with the ledger rules for delegation allowing for some protocol specific data to be included.

[^1]: It doesn't actually matter if the actual block headers contain a block number or not; if they don't, we can add a "virtual field" to the in-memory representation of the block header. For block headers that *do* include a block number (which is the case for the Cardano chain), header validation verifies that the block number is increasing. Note that EBBs complicate this particular somewhat; see page .

[^2]: Comparing empty chain *fragments*, introduced in \[storage:fragments\]{reference-type="ref+label" reference="storage:fragments"}, is significantly more subtle, and will be discussed in \[chainsel:fragments\]{reference-type="ref+label" reference="chainsel:fragments"}.

[^3]: For chain selection algorithms such as Ouroboros Genesis which are based on properties of the chains near their *intersection point* rather than near their tips this is less relevant.

[^4]: We will come back to this in \[future:openkinds\]{reference-type="ref+label" reference="future:openkinds"}.

[^5]: Explicitly modelling such a required context could be avoided if we used explicit records instead of type classes; we will discuss this point in more detail in \[technical:classes-vs-records\]{reference-type="ref+label" reference="technical:classes-vs-records"}.

[^6]: We are referring to this as the "chain dependent state" to emphasise that this is state that evolves with the chain, and indeed is subject to rollback when we switch to alternatives forks. This distinguishes it from chain *independent* state such as evolving private keys, which are updated independently from blocks and are not subject to rollback.

[^7]: Throughout the consensus layer, the result of ticking is distinguished from the unticked value at the type level. This allows to store additional (or indeed, less) information in the ticked ledger state, but also clarifies ordering. For example, it is clear in `tickChainDepState` that the ledger view we pass as an argument is already ticked, as opposed to the *old* ledger view.

[^8]: Most "normal" users will not produce blocks themselves, but instead delegate their stake to stakepools who produce blocks on their behalf.

[^9]: For a discussion about why we choose to make some type families top-level definitions rather than associate them with a type class, see \[technical:toplevel-vs-associated\]{reference-type="ref+label" reference="technical:toplevel-vs-associated"}.

[^10]: []{#footnote:singlesignature label="footnote:singlesignature"}There is another minor deviation from the specification: we don't require an explicit signature on the block body. Instead, we have a single signature over the header, and the header includes a *hash* of the body.

[^11]: We could update this "virtual" block every time that the node's current chain changes, so that the virtual block's predecessor is always the current chain's tip. This however couples two concurrent processes more tightly than required, and is moreover costly: re-evaluating the mempool can be expensive.

[^12]: In an perfect world this header/body boundary would align neatly with the consensus/ledger boundary; I think this ought to be possible in principle, but in the current design this is non-trivial to achieve, since the ledger layer is interpreting some fields in the header; for example, it is executing some rules in response to epoch transitions, which it detects based on fields in the header.
