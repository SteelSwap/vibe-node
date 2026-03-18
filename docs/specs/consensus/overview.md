# Overview

## Components

### Consensus protocols
The consensus protocol has two primary responsibilities: []{#consensus-responsibilities label="consensus-responsibilities"}

Chain selection

:   Competing chains arise when two or more nodes extend the chain with different blocks. This can happen when nodes are not aware of each other's blocks due to temporarily network delays or partitioning, but depending on the particular choice of consensus algorithm it can also happen in the normal course of events. When it happens, it is the responsibility of the consensus protocol to choose between these competing chains.

Leadership check

:   In proof-of-work blockchains any node can produce a block at any time, provided that they have sufficient hashing power. By contrast, in proof-of-stake time is divided into *slots*, and each slot has a number of designated *slot leaders* who can produce blocks in that slot. It is the responsibility of the consensus protocol to decide on this mapping from slots to slot leaders.

The consensus protocol will also need to maintain its own state; we will discuss state management in more detail in \[storage:inmemory\]{reference-type="ref+label" reference="storage:inmemory"}.

### Ledger
The role of the ledger is to define what is stored *on* the blockchain. From the perspective of the consensus layer, the ledger has three primary responsibilities:

Applying blocks

:   The most obvious and most important responsibility of the ledger is to define how the ledger state changes in response to new blocks, validating blocks at it goes and rejecting invalid blocks. 

Applying transactions

:   Similar to applying blocks, the ledger layer also must provide an interface for applying a single transaction to the ledger state. This is important, because the consensus layer does not just deal with previously constructed blocks, but also constructs *new* blocks.

Ticking time

:   Some parts of the ledger state change due to the passage of time only. For example, blocks might *schedule* some changes to be applied later, and then when the relevant slot arrives those changes should be applied, independent from any blocks.

Forecasting

:   Some consensus protocols require limited information from the ledger. In Praos, for example, a node's probability of being a slot leader is proportional to its stake, but the stake distribution is something that the ledger keeps track of. We refer to this as a *view* on the ledger, and we require not just that the ledger can give us a view on the *current* ledger state, but also *predict* what that view will be for slots in the near future. We will discuss the motivation for this requirement in \[nonfunctional:network:headerbody\]{reference-type="ref+label" reference="nonfunctional:network:headerbody"}.

The primary reason for separating out "ticking" from applying blocks is that the consensus layer is responsible to the leadership check (\[consensus-responsibilities\]{reference-type="ref+label" reference="consensus-responsibilities"}), and when we need to decide if we should be producing a block in a particular slot, we need to know the ledger state at that slot (even though we don't have a block for that slot *yet*). It is also required in the mempool; see \[mempool\]{reference-type="ref+label" reference="mempool"}.

## Design Goals

### Multiple consensus protocols

From the beginning it was clear that we would need support for multiple consensus algorithms: the Byron era uses a consensus algorithm called (Permissive) BFT (\[bft\]{reference-type="ref+label" reference="bft"}) and the Shelley era uses a consensus algorithm called Praos (\[praos\]{reference-type="ref+label" reference="praos"}). Moreover, the Cardano blockchain is a *hybrid* chain where the prefix of the chain runs Byron (and thus uses BFT), and then continues with Shelley (and thus uses Praos); we will come back to the topic of composing protocols when we discuss the hard fork combinator (\[hfc\]{reference-type="ref+label" reference="hfc"}). It is therefore important that the consensus layer abstracts over a choice of consensus protocol.

### Support for multiple ledgers
For much the same reason that we must support multiple consensus protocols, we also have to support multiple ledgers. Indeed, we expect more changes in ledger than in consensus protocol; currently the Cardano blockchain starts with a Byron ledger and then transitions to a Shelley ledger, but further changes to the ledger have already been planned (some intermediate ledgers currently code-named Allegra and Mary, as well as larger updates to Goguen, Basho and Voltaire). All of the ledgers (Shelley up to including Voltaire) use the Praos consensus algorithm (potentially extended with the genesis chain selection rule, see \[genesis\]{reference-type="ref+label" reference="genesis"}).

### Decouple consensus protocol from ledger
As we saw above (1.2.2{reference-type="ref+label" reference="multiple-ledgers"}), we have multiple ledgers that all use the same consensus protocol. We therefore should be able to define the consensus protocol *independent* from a particular choice of ledger, merely defining what the consensus protocol expects from the ledger (we will see what this interface looks like in [\[ledger\]](#ledger){reference-type="ref+label" reference="ledger"}).

### Testability

The consensus layer is a critical component of the Cardano Node, the software that runs the Cardano blockchain. Since the blockchain is used to run the ada cryptocurrency, it is of the utmost importance that this node is reliable; network downtime or, worse, corruption of the blockchain, cannot be tolerated. As such the consensus layer is subject to much stricter correctness criteria than most software, and must be tested thoroughly. To make this possible, we have to design for testability.

- We must be able to simulate various kinds of failures (disk failures, network failures, etc.) and verify that the system can recover.

- We must be able to run *lots* of tests which means that tests need to be cheap. This in turn will require for example the possibility to swap the cryptographic algorithms for much faster "mock" crypto algorithms.

- We must be able to test how the system behaves under certain expected-but-rare circumstances. For example, under the Praos consensus protocol it can happen that a particular slot has multiple leaders. We should be able to test what happens when this happens repeatedly, but the leader selection is a probabilistic process; it would be difficult to set up test scenarios to test for this specifically, and even more difficult to set things up so that those scenarios are *shrinkable* (leading to minimal test cases). We must therefore be able to "override" the behaviour of the consensus protocol (or indeed the ledger) at specific points.

- We must be able to test components individually (rather than just the system as a whole), so that if a test fails, it is much easier to see where something went wrong.

### Adaptability and Maintainability
The Cardano Node began its life as an ambitious replacement of the initial implementation of the Cardano blockchain, which had been developed by Serokell. At the time, the Shelley ledger was no more than a on-paper design, and the Praos consensus protocol existed only as a research paper. Moreover, since the redesign would be unable to reuse any parts of the initial implementation, even the Byron ledger did not yet exist when the consensus layer was started. It was therefore important from the get-go that the consensus layer was not written for a specific ledger, but rather abstract over a choice of ledger and define precisely what the responsibilities of that ledger were.

This abstraction over both the consensus algorithm and the ledger is important for other reasons, too. As we've mentioned, although initially developed to support the Byron ledger and the (Permissive) BFT consensus algorithm, the goal was to move to Shelley/Praos as quickly as possible. Moreover, additional ledgers had already been planned (Goguen, Basho and Voltaire), and research on consensus protocols was (and still is) ongoing. It was therefore important that the consensus layer could easily be adapted.

Admittedly, adaptability does not *necessarily* require abstraction. We could have built the consensus layer against the Byron ledger initially (although we might have had to wait for it to be partially completed at least), and then generalise as we went. There are however a number of downsides to this approach.

- When working with a concrete interface, it is difficult to avoid certain assumptions creeping in that may hold for this ledger but will not hold for other ledgers necessarily. When such assumptions go unnoticed, it can be costly to adjust later. (For one example of such an assumption that nonetheless *did* go unnoticed, despite best efforts, and took a lot of work to resolve, see \[time\]{reference-type="ref+label" reference="time"} on removing the assumption that we can always convert between wallclock time and slot number.)

- IOHK is involved in the development of blockchains other than the public Cardano instance, and from the start of the project, the hope was that the consensus layer can be used in those projects as well. Indeed, it is currently being integrated into various other IOHK projects.

- Perhaps most importantly, if the consensus layer only supports a single, concrete ledger, it would be impossible to *test* the consensus layer with any ledgers other than that concrete ledger. But this means that all consensus tests need to deal with all the complexities of the real ledger. By contrast, by staying abstract, we can run a lot of consensus tests with mock ledgers that are easier to set up, easier to reason about, more easily instrumented and more amenable to artificially creating rare circumstances (see [1.2.4](#testability){reference-type="ref+label" reference="testability"}).

Of course, abstraction is also just good engineering practice. Programming against an abstract interface means we are clear about our assumptions, decreases dependence between components, and makes it easier to understand and work with individual components without having to necessarily understand the entire system as a whole.

### Composability

The consensus layer is a complex piece of software; at the time we are writing this technical report, it consists of roughly 100,000 lines of code. It is therefore important that we split it into into small components that can be understood and modified independently from the rest of the system. Abstraction, discussed in 1.2.5{reference-type="ref+label" reference="adaptability"}, is one technique to do that, but by no means the only. One other technique that we make heavy use of is composability. We will list two examples here:

- As discussed in [1.2.1](#multiple-consensus-protocols){reference-type="ref+label" reference="multiple-consensus-protocols"} and 1.2.2{reference-type="ref+label" reference="multiple-ledgers"}, the Cardano blockchain has a prefix that runs the BFT consensus protocol and the Byron ledger, and then continues with the Praos consensus protocol and the Shelley ledger. We do not however define a consensus protocol that is the combination of Byron and Praos, nor a ledger that is the combination of Byron and Shelley. Instead, the *hard fork combinator* (\[hfc\]{reference-type="ref+label" reference="hfc"}) makes it possible to *compose* consensus protocols and ledgers: construct the hybrid consensus protocol from an implementation of BFT and an implementation of Praos, and similarly for the ledger.

- We mentioned in [1.2.4](#testability){reference-type="ref+label" reference="testability"} that it is important that we can test the behaviour of the consensus layer under rare-but-possible circumstances, and that it is therefore important that we can override the behaviour of the consensus algorithm in tests. We do not accomplish this however by adding special hooks to the Praos consensus algorithm (or any other); instead we define another combinator that takes the implementation of a consensus algorithm and *adds* additional hooks for the sake of the testing infrastructure. This means that the implementation of Praos does not have to be aware of testing constraints, and the combinator that adds these testing hooks does not need to be aware of the details of how Praos is implemented.

### Predictable Performance

Make sure node operators do not set up nodes for \"normal circumstances\" only for the network to go down when something infrequent (but expected) occurs. (This is not about malicious behaviour, that's the next section).

### Protection against DoS attacks

Brief introduction to asymptotic attacker/defender costs. (This is just an overview, we come back to these topics in more detail later.)

## History
- Briefly describe the old system (`cardano-sl`) the decision to rewrite it

- Briefly discuss the OBFT hard fork.
