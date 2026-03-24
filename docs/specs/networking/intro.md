# Overview

The Cardano blockchain system is based on the Ouroboros family of protocols for a proof-of-stake cryptocurrency. The operation of these protocols on a node, working in collaboration with the consensus and ledger aspects of Cardano, create the overall distributed system. It is that distributed system that defines the \"single source of truth\" that is the distributed ledger. The Ouroboros papers describe these protocols in a high-level mathematical formalism that allows for a concise presentation and is appropriate for peer review by cryptography experts. For separation of concerns, the papers do not describe a concrete implementation of the Ouroboros protocols.

This document has a broader scope. It is addressed to system designers and engineers who have an IT background but are not necessarily crypto experts, but want to implement Cardano or to understand the reference implementation. The description of the protocol in this document contains all the information needed to implement the data diffusion functionality of a compatible Cardano network node. It covers:

- How nodes join the network.

- The general semantics of the messages that nodes exchange.

- The binary format of the messages.

- The order in which nodes send and receive the messages of the protocol.

- The permissible protocol states for each participant in the protocol.

This information is typically found in the description of network protocols.

However, the Ouroboros proof-of-stake cryptocurrency has additional requirements, of a sort that are not typically covered in a protocol description itself. While these underlying requirements are essential for understanding the design of the protocol, it also makes sense to also discuss these aspects and requirements in this document. Typical network protocols describe simple information exchanges; the distributed nature of blockchain computation means that additional contextual information is available. Use of this context allows, for example, for validated store and forward which is an essential feature to contain the effect of potential malicious actions against the distributed system.

Shelley is a first fully decentralised release of Cardano system, implementing the Ouroboros protocol.

This Chapter contains an overview of the content and scope of this document and aspects that are being discussed.

#### Layered Protocols

Traditionally network protocols are presented as a stack of layers where upper layers build on services provided by lower layers and lower layers are independent of the implementation of the upper layers. This concept of layers is misleading when discussing Ouroboros. For example, it is *not* the case that the consensus (layer) is built on top of the network (layer). It is more appropriate to talk about a network component than a network layer. The network component provides services to the consensus component and vice versa; both components rely on each other. The network component uses the consensus component to validate information that it distributes to other nodes, which is essential to guard against certain kinds of DoS attacks. Existing peer-to-peer systems focus on a slightly different problem domain. For example, they do not consider the information validation issue or are concerned with issues such as 'eclipse attacks' that to not apply to the Ouroboros family of protocols.

#### Performance of the Ouroboros Network

In computer science, Byzantine Fault Tolerance is a property of a distributed algorithm, which states that it works for the honest participants under the assumption that a certain proportion of the participants are indeed honest. A similar, but more informal property applies to performance of the Ouroboros network as well.

The network provides a service to its participants while at the same time the participants provide a service to the network. The performance of the Ouroboros network depends (among other things) on the performance of the nodes, while the performance of a node also depends on the performance of the network. Not only are there honest and adversarial participant, but there is also a huge variety of possible network topographies, bandwidths and latencies of network connections and other factors that determine the performance of the network.

This document discusses the high level functional and performance requirements for Ouroboros and the assumptions made about the structure of the underlying P2P network.

#### Protocol vs Implementation

Network Protocols are written at different levels of abstraction. To be useful, a protocol description must be precise enough to be implemented. A protocol description should also be abstract enough to allow alternative implementations of the protocol and to facilitate developing and improving it. Furthermore, it should be possible to both implement an abstract version of a protocol and interpret it in a real-world scenario. For example, it must be possible to implement a protocol such that the real-world software runs on a machine with a typical size of memory and a typical speed network connection.

The Shelley network protocol design has been developed in parallel with a reference implementation in Haskell. Haskell (more precisely GHC) has built-in support for high level concurrency abstractions such as light-weight threads and software transactional memory. While the protocol itself is completely language agnostic, it still makes sense to discuss some aspects of the Haskell reference implementation in this document. In particular, the document describes how to achieve good resource bounds for a protocol implementation.

## High level requirements and User Stories

These are the high level business requirements for the networking that were gathered and signed off in late 2017. As such they are expressed in informal prose, often following a "user story" style. Roughly, there are three different kinds of users:

- Users who have delegated.

- Small stakeholders.

- Large stakeholders.

#### Network connectivity

##### Participate as a user who has delegated

As a Daedalus home user with my stake delegated to other users I would like to join the Cardano network so I can participate in the network.

- The system must be designed to provide this user segment with the ability to catch up and keep up with the blockchain without having to do any local network configuration.

- The system must be designed to provide this user segment with the ability to continuously find and maintain a discovery of a sufficient number of other network participants that have reasonable connectivity.

- The system must be designed to provide this user segment with the ability to find and maintain a minimum of 3 other network participants to maintain connectivity with performance that is sufficient to catch up with the blockchain.

- The system design will take into account that this user will probably be behind a firewall.

- Users in the segment can be defined by having all their stake delegated to other network participants. As such they will never be selected as a slot leader (i.e required to generate a block).

##### Participate in network as small stakeholder

As a Daedalus home user operating a node with a small stake, I would like to join the Cardano network so I can participate in the network as a node that produces blocks i.e. my stake is not delegated to someone else.

- The system must be designed to provide this user segment with the ability to receive the transactions that will be incorporated into blocks (although sizing the operation of the distributed system to ensure that all such participants would be able to receive all transactions is not a bounding constraint).

- The system must be designed to provide this user segment with the ability to participate in the MPC protocol[^1].

- The system will be designed to provide this user segment with the ability to catch up and keep up with the blockchain without having to do any local network configuration (this is a bounding constraint).

- The user will have sufficient connectivity and performance to receive a block within a time slot and they have to be able to create and broadcast a block within a time slot in which the block is received by other participating nodes.

- The system will be designed to maximise the likelihood that 50% of home users operating a participating node are compliant with the previous requirement at any one time.

- The system will be designed to provide this user segment with the ability to continuously find and maintain a discovery of a sufficient number of other network participants that have reasonable connectivity.

- The system will provide a discovery mechanism that will find and maintain a minimum of 3 other network participants to maintain connectivity with performance that is sufficient to catch up with the blockchain.

- The system design will take into account that this user may be behind a firewall (i.e being behind a firewall should not preclude a user participating in this fashion).

- The Delegation work stream will provide a UI feature for the user to choose to control their own stake.

- Users in this segment will be defined as not

  - being in the top 100 users ranked by stake or

  - in a ranked set of users who together control 80% of the stake

- Users in this segment will not be part of the Core Dif, but still subject to the normal incentives related to creating blocks.

##### Participate in network as a large stakeholder

As a user running a core node on a server and with large stake in the network, I would like to join the Cardano network so I can participate in the network as a core server node that produces blocks i.e. have not delegated to someone else.

- A large stakeholder will be defined as

  - being in the top 100 users ranked by stake; or

  - in a ranked set of users who combined control 80% of the stake

- Assuming that this user has sufficient connectivity and performance, the system should ensure that the collective operation of the distributed system will ensure that they have a high probability of receiving a block within a time slot such that they have sufficient time to be able to create and broadcast a block within a time slot where the block is received by other core nodes.

- It is expected that the previous requirement will be fulfilled to a high degree of reliability between nodes in this category -- assuming normal network operations

    ----------- ---------
      Threshold $>95\%$
         Target $>98\%$
        Stretch $>99\%$
    ----------- ---------

- The system will be designed to provide this user segment with the ability to continuously find and maintain a discovery of a sufficient number of other network participants that have reasonable connectivity.

- Discovery will find and maintain a minimum of 10 other network participants to maintain connectivity with performance that is sufficient to catch up with the blockchain.

- Ability to receive the transactions that will be incorporated into blocks.

- Ability to participate in the MPC protocol[^2].

- The user will catch up and keep up with the blockchain.

- The server firewall rules will be such that it can communicate with other core nodes on the system (and vice versa) -- The system will provide the necessary information to update firewall rules if the server is operating behind a firewall to ensure the server can communicate with other core nodes.

- The threshold which defines the group of large stakeholders may be configurable on the network layer. The configuration may include toggling between the rules a) and b) in the previous requirement and the threshold numbers within these (this is pending a decision from the Incentives work stream.

- The rules and threshold configuration may need to be a protocol parameter that is updated by the update system.

##### Poor network connectivity notification

As a home user, I want to see a network connection status on Daedalus so that I know the state of my network connection.

- If the user receives a notification that they are in red or amber mode, Daedalus will give the user some helpful information on how to resolve common connectivity issues.

There are three (at least) the following three distinct modes that the network can be operating in: each one has a red, green, amber status.

<!-- center -->
  Initial block sync      
  ----------------------- ------------------------------------------------------------------
  red                     receiving $<1$ blocks per 10s
  amber                   receiving $<10$ blocks per 10s
  green                   otherwise
  Recovery                
  red                     receiving $<1$ block per 10s
  amber                   otherwise
  green                   (not applicable)
  Block chain following   
  red                     it has been more that 200s since a slot indication was received.
  amber                   it has been more than 60s since a slot indication was received.
  green                   otherwise.

This assumes that the slot time remains 20 seconds, or at least that the average time between production of new blocks is 20 seconds.

##### Transaction Latency

As a user I want my transaction to be submitted to the blockchain and received by the target user within the following time period:

<!-- center -->
  ----------- -------------
  Threshold     100 seconds
  Target         60 seconds
  Stretch        30 seconds
  ----------- -------------

The above time-frames will be achieved for $>95\%$ of all transactions.

##### Network Bearer Resource Use -- end user control

As a user operating on the network as a home user not behind a firewall, I would like a cap on the total amount of network capacity in terms of short-term bandwidth that other network users can request from my connection so I am assured my network resource is not eaten up by the data diffusion function.

- The cap should be based on a fraction of a typical home internet connection -- it can be changed by configuration including "don't act as a super node".

- The system will allow users syncing with the latest version of the blockchain to download blocks from more than one and up to five network peers concurrently.

- A cap on number of incoming subscribers.

- A cap on number of outbound requests for block syncing from other users.

- The cap will not be imposed on core nodes running on a server.

- If these resources are available, a reasonable connection speed should be available to users requesting to sync the latest version of the blockchain e.g. downloading blocks from 5 peers concurrently to aggregate the bandwidth.

- (nice to have) the actual number and capacity being used is available to user.

##### Participant performance measurement

There may be a requirement for measuring if a large stakeholder is not meeting their network obligation [@DBLP:journals/corr/abs-1807-11218].

It is accepted that this requirement is a "nice to have", and it has not been established that it is possible, nor has it been incorporated into the incentives mechanism.

#### Distributed System Resilience and Security

##### Resilience to abuse

As a user I should not be able to attack the system using an asymmetric denial of service attack that will deplete network resources from other users.

- The system should achieve its connectivity and performance requirements even in the presence of a non-trivial proportion of bad actors on the network.

- There is an assumption that there are not a large numbers of bad actors in the network.

- The previous assumption does not follow from the assumptions of Ouroboros which states that the users that control 50% of the stake are non-adversarial.

##### DDoS protection

As a large stakeholder running a core node on a server, I should still be able to communicate with other user in this segment, even if the system comes under a DDoS attack.

- Users in this segment will be able to generate and broadcast blocks to each other within the usual timing constraints in this situation.

IP addresses will be hidden.

- Encrypted IP addresses will be published by 10 of the other members of the group of large stakeholder core nodes.

Assumption

- Core node operators will not publish their IP addresses publicly.

- Encrypted IP addresses will be published by the 10 of the other members of the group of large stakeholder core nodes.

- If a node operator's IP address is compromised the operator will respond and change the IP address of their node.

- The system will allow operators to change the address of their core nodes and communicate with that new IP address within a reasonable period of time.

#### Network decentralisation

##### No hegemony

As a user I want to be assured that IOHK and its business partners are not in an especially privileged position in terms of trust, responsibility and necessity to the network so that network hegemony is avoided.

- IOHK should be in the same position on the network as any other stakeholder with an equivalent amount of stake.

- There is a more general requirement that no other actor could achieve hegemonic control of the operation of the data diffusion layer.

# System Architecture

## Congestion Control

A central design goal of the system is robust operation at high workloads. For example, it is a normal working condition of the networking design that transactions arrive at a higher rate than the number that can be included in blockchain. An increase of the rate at which transactions are submitted must not cause a decrease of the block chain quality.

Point-to-point TCP bearers do not deal well with overloading. A TCP connection has a certain maximal bandwidth, i.e. a certain maximum load that it can handle relatively reliably under normal conditions. If the connection is ever overloaded, the performance characteristics will degrade rapidly unless the load presented to the TCP connection is appropriately managed.

At the same time, the node itself has a limit on the rate at which it can process data. In particular, a node may have to share its processing power with other processes that run on the same machine/operation system instance, which means that a node may get slowed down for some reason, and the system may get in a situation where there is more data available from the network than the node can process. The design must operate appropriately in this situation and recover from transient conditions. In any condition, a node must not exceed its memory limits, that is there must be defined limits, breaches of which being treated like protocol violations.

Of course it makes no sense if the system design is robust, but so defensive that it fails to meet performance goals. An example would be a protocol that never transmits a message unless it has received an explicit ACK for the previous message. This approach might avoid overloading the network, but would waste most of the potential bandwidth.


<!-- center -->

**Data flow inside a Node**

## Data Flow in a Node

Nodes maintain connections with the peers that have been chosen with help of the peer selection process. Suppose node $A$ is connected to node $B$. The Ouroboros protocol schedules a node $N$ to generate a new block in a given time slot. Depending on the location of nodes $A$, $B$ and $N$ in the network topology and whether the new block arrives first at $A$ or $B$, $A$ can be either up-stream or down-stream of $B$. Therefore, node $A$ runs an instance of the client side of the chain-sync mini protocol that talks with a server instance of chain-sync at node $B$ and also a server instance of chain sync that talks with a client instance at $B$. The situation is similar for the other mini protocols (block fetch, transaction submission, etc). The set of mini protocols that runs over a connection is determined by the version of the network protocol, i.e. Node-to-Node, Node-to-Wallet and Node-to-Chain-Consumer connections use different sets of mini protocols (e.g. different protocol versions). The version is negotiated when a new connection is established using protocol which is described in Chapter \[connection-management\].

Figure 2.1 illustrates parts of the data flow in a node. Circles represents a thread that runs one of the mini protocols (the mini protocols are explained in Chapter \[chapter:mini-protocols\]). There are two kinds of data flows: mini protocols communicate with mini protocols of other nodes by sending and receiving messages; and, within a node, they communicate by reading from- and writing to- a shared mutable state (represented by boxes in Figure 2.1). [Software transactional memory](https://en.wikipedia.org/wiki/Software_transactional_memory) (STM) is a mechanism for safe and lock-free concurrent access to mutable state and the reference implementation makes intensive use of this abstraction.

## Real-time Constraints and Coordinated Universal Time

Ouroboros models the passage of physical time as an infinite sequence of time slots, i.e. contiguous, equal-length intervals of time, and assigns slot leaders (nodes that are eligible to create a new block) to those time slots. At the beginning of a time slot, the slot leader selects the block chain and transactions that are the basis for the new block, then it creates the new block and sends the new block to its peers. When the new block reaches the next block leader before the beginning of next time slot, the next block leader can extend the block chain upon this block (if the block did not arrive on time the next leader will create a new block anyway).

There are some trade-offs when choosing the slot time that is used for the protocol but basically the slot length should be long enough such that a new block has a good chance to reach the next slot leader in time. A chosen value for the slot length is 20 seconds. It is assumed that the clock skews between the local clocks of the nodes is small with respect to the slot length.

However, no matter how accurate the local clocks of the nodes are with respect to the time slots the effects of a possible clock skew must still be carefully considered. For example, when a node time-stamps incoming blocks with its local clock time, it may encounter blocks that are created in the future with respect to the local clock of the node. The node must then decide whether this is because of a clock skew or whether the node considers this as adversarial behaviour of another node.

[^1]: This requirement is now redundant because the MPC protocol is specific to Ouroboros Classic.

[^2]: This requirement is now redundant because the MPC protocol is specific to Ouroboros Classic.
