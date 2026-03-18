# Mini Protocols
## Mini Protocols and Protocol Families

A mini protocol is a well-defined and modular building block of the network protocol. Structuring a protocol around mini-protocols helps manage the overall complexity of the design and adds useful flexibility. The design turns into a family of mini-protocols that can be specialised to particular requirements by choosing a particular set of mini-protocols.

The mini-protocols in this section describe the initiator and responder of a communication. The initiator is the dual of the responder and vice versa. (The terms client/server, consumer/producer or initiator/responder are also used sometimes.) At any time, a node will typically run many instances of mini-protocols, including many instances of the same mini-protocol. Each mini-protocol instance of the node communicates with the dual instance of exactly one peer.

The set of mini protocols that run on a connection between two participants of the system depends on the role of the participants, i.e. whether the node acts as a full node or just a blockchain consumer, such as a wallet.

## Protocols as State Machines

The implementation of the mini protocols uses a generic framework for state machines. This framework uses correct-by-construction techniques to guarantee several properties of each mini-protocol. In particular, it guarantees that there are no deadlocks. At any time, only one side has the agency (is expected to transmit the next message) while the other side is waiting for the message (or both sides agree that the mini-protocol has terminated). If either side receives a message that is not expected according to the mini-protocol the communication is aborted (the connection is closed).

For each mini-protocol based on this underlying framework, the description provides the following pieces of information:

- An informal description of the mini-protocol.

- States of the state machine.

- The messages (transitions) of the mini-protocol.

- A transition graph of the global view of the state machine.

- The client implementation of the mini-protocol.

- The server implementation of the mini-protocol.

State Machine

:   Each mini-protocol is described as a state machine. This document uses simple diagram representations for state machines and also includes corresponding transition tables. Descriptions of state machines in this section are directly derived from specifications of mini protocols using the state machine framework.

    The state machine framework that is used to specify the mini-protocol can be instantiated with different implementations that work at different levels of abstraction (for example, implementations used for simulation, implementations that run over virtual connections and implementations that actually transmit messages over the real network).

States

:   States are abstract: they are not a value of some variables in a node, but rather describe the state of the two-party communication as a whole, e.g. that a client is responsible for sending a particular type of message and the server is waiting on it. This, in particular, means that if the state machine is in a given state, then both the client and server are in this state. An additional piece of information that differentiates the roles of peers in a given state is the agency, which describes which side is responsible for sending the next message.

    In the state machine framework, abstract states of a state machine are modelled as promoted types, so they do not correspond to any particular the value held by one of the peers.

    The document presents this abstract view of mini protocols and the state machines where the client and server are always in identical states, which also means that the client and server simultaneously transit to new states. For this description, network delays are not important.

    An interpretation which is closer to the real-world implementation but less concise is that there are independent client and server states and that transitions on either side happen independently when a message is sent or received.

Messages

:   Messages exchanged by peers form edges of a state machine diagram; in other words, they are transitions between states. They are elements from the set $$\{(label, data) \mid label \in Labels, data \in Data\}$$ Protocols use a small set of $Labels$ typically $|Labels| \leq 10$. The state machine framework requires that messages can be serialised, transferred over the network and de-serialised by the receiver.

Agency

:   A node has agency if it is expected to send the next message. The client or server has agency in every state, except a termination state in which nor the client, nor the server can send any message. All our mini-protocols have a single terminating state .

State machine diagrams

:   States are drawn as circles in state machine diagrams. States with the agency on the client side are drawn in green, states with the agency on the server side are drawn in blue, and the termination states are in black. By construction, the system is always in exactly one state, i.e. the client's state is always the same state as the server's, and the colour indicates who the agent is. It is also important to understand that the arrows in the state transition diagram denote state transitions and not the direction of the message that is being transmitted. For the agent of the particular state, the arrow means: "send a message to the other peer and move to the next state". For a non-agent, an arrow in the diagram can be interpreted as: "receive an incoming message and move to the next state". This may not be very clear because the arrows are labelled with the messages, and many arrows go from a green state (the client has the agency) to a blue state (the server has the agency) or vice versa.

    $A$ is green, i.e in state $A$ the client has agency. Therefore, the client sends a message to the server and both client and server transition to state $B$. As $B$ is blue, the agency also changes from client to server.

    $C$ is blue, i.e in state $C$ the server has agency. Therefore, the server sends a message to the client and both client and server transition to state $D$. As $D$ is also blue, the agency remains on the server.

Client and server implementation

:   The state machine describes which messages are sent and received and in which order. This is the external view of the protocol that every compatible implementation MUST follow. In addition to the external view of the protocol, this part of the specification describes how the client and server actually process the transmitted messages, i.e. how the client and server update their internal mutable state upon the exchange of messages.

    Strictly speaking, the representation of the node-local mutable state and the updates to the node-local state are implementation details that are not part of the communication protocol between the nodes and will depend on an application that is built on top of the network service (wallet, core node, explorer, etc.). The corresponding sections were added to clarify the mode of operation of the mini protocols.

## Overview of all implemented Mini Protocols

### Dummy mini-protocols

Dummy mini-protocols are not used by 'cardano-node'; however, they might be helpful when writing demos, testing purposes or getting familiar with the framework.

::: framed
**Ping Pong Protocol**Section 1.5.1\
A simple ping-pong protocol for testing.\
[`typed-protocols/src/Network/TypedProtocol/PingPong/Type.hs`](https://input-output-hk.github.io/typed-protocols/typed-protocols-examples/Network-TypedProtocol-PingPong-Type.html#t:PingPong)

::: framed
**Request Response Protocol**Section 1.5.2\
A ping-pong-like protocol which allows the exchange of data.\
[`typed-protocols/src/Network/TypedProtocol/ReqResp/Type.hs`](https://input-output-hk.github.io/typed-protocols/typed-protocols-examples/Network-TypedProtocol-ReqResp-Type.html#t:ReqResp)

### Handshake

Handshake mini-protocol is shared by the node-to-node and node-to-client protocols (it is polymorphic to allow that).

::: framed
**Handshake Mini Protocol**Section handshake-protocol\
This protocol is used for version negotiation.\
[`ouroboros-network-framework/src/Ouroboros/Network/Protocol/Handshake/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-framework/Ouroboros-Network-Protocol-Handshake-Type.html#t:Handshake)

### Node-to-node mini-protocols

In this section, we list all the mini-protocols that constitute the node-to-node protocol.

::: framed
**Chain Synchronisation Protocol**Section 1.7\
The protocol by which a downstream chain consumer follows an upstream chain producer.\
[`ouroboros-network-protocols/src/Ouroboros/Network/Protocol/ChainSync/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-protocols/Ouroboros-Network-Protocol-ChainSync-Type.html#t:ChainSync)

::: framed
**Block Fetch Protocol**Section 1.8\
The block fetching mechanism enables a node to download ranges of blocks.\
[`ouroboros-network-protocols/src/Ouroboros/Network/Protocol/BlockFetch/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-protocols/Ouroboros-Network-Protocol-BlockFetch-Type.html#t:BlockFetch)

::: framed
**Transaction Submission Protocol v2**Section tx-submission-protocol2\
A Protocol for transmitting transactions between core nodes.\
[`ouroboros-network-protocols/src/Ouroboros/Network/Protocol/TxSubmission2/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-protocols/Ouroboros-Network-Protocol-TxSubmission2-Type.html#t:TxSubmission2)

::: framed
**Keep Alive Protocol**Section keep-alive-protocol\
A protocol for sending keep alive messages and doing round trip measurements\
[`ouroboros-network-protocols/src/Ouroboros/Network/Protocol/KeepAlive/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-protocols/Ouroboros-Network-Protocol-KeepAlive-Type.html#t:KeepAlive)

::: framed
**Peer Sharing Protocol**Section peer-sharing-protocol\
A mini-protocol which allows to share peer addresses\
[`ouroboros-network-protocols/src/Ouroboros/Network/Protocol/PeerSharing/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-protocols/Ouroboros-Network-Protocol-PeerSharing-Type.html#t:PeerSharing)

### Node-to-client mini-protocols

Mini-protocols used by node-to-client protocol. The chain-sync mini-protocol is shared between node-to-node and node-to-client protocols, but it is instantiated differently. In node-to-client protocol, it is used with full blocks rather than just headers.

::: framed
**Chain Synchronisation Protocol**Section 1.7\
The protocol by which a downstream chain consumer follows an upstream chain producer.\
[`ouroboros-network-protocols/src/Ouroboros/Network/Protocol/ChainSync/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-protocols/Ouroboros-Network-Protocol-ChainSync-Type.html#t:ChainSync)

::: framed
**Local State Query Mini Protocol**Section 1.13\
Protocol used by local clients to query ledger state\
[`ouroboros-network-protocols/src/Ouroboros/Network/Protocol/LocalStateQuery/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-protocols/Ouroboros-Network-Protocol-LocalStateQuery-Type.html#t:LocalStateQuery)

::: framed
**Local Tx Submission Mini Protocol**Section local-tx-submission-protocol\
Protocol used by local clients to submit transactions\
[`ouroboros-network-protocols/src/Ouroboros/Network/Protocol/LocalTxSubmission/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-protocols/Ouroboros-Network-Protocol-LocalTxSubmission-Type.html#t:LocalTxSubmission)

::: framed
**Local Tx Monitor Mini Protocol**Section local-tx-monitor-protocol\
Protocol used by local clients to monitor transactions\
[`ouroboros-network-protocols/src/Ouroboros/Network/Protocol/LocalTxMonitor/Type.hs`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-protocols/Ouroboros-Network-Protocol-LocalTxMonitor-Type.html#t:LocalTxMonitor)

## CBOR and CDDL

All mini-protocols are encoded using the concise binary object representation (CBOR), see <https://cbor.io>. Each codec comes along with a specification written in CDDL, see ['Coincise data definition language (CDDL)'](https://cbor-wg.github.io/cddl/draft-ietf-cbor-cddl.html).

The networking layer knows little about blocks, transactions or their identifiers. In `ouroboros-network` we use parametric polymorphism for blocks, tx, txids, etc, and we only assume these data types have their own valid CDDL encoding (and CDDL specifications). For testing against the `ouroboros-network` CDDL, we need concrete values; for this reason, we use `any` in our CDDL specification. This describes very closely what the `ouroboros-network` implementation does. It doesn't mean the payloads are not validated, the full codecs of messages transferred on the wire are composed from network, consensus & ledger codecs. There is an ongoing effort to capture combined CDDLs. If you want to find concrete instantiations of these types by 'Cardano', you will need to consult [cardano-ledger](https://github.com/intersectmbo/cardano-ledger) and [ouroboros-consensus](https://github.com/intersectmbo/ouroboros-consensus) (in particular [ouroboros-consensus#1422](https://github.com/IntersectMBO/ouroboros-consensus/pull/1422)). Each ledger era has its own CDDL spec, which you can find [here](https://github.com/intersectmbo/cardano-ledger#cardano-ledger). Note that the hard fork combinator (HFC) also allows us to combine multiple eras into a single blockchain. It affects how many of the data types are encoded across different eras.

We want to retain the ability to decode messages incrementally, which for the Praos protocol might allow us to improve performance.

## Dummy Protocols

Dummy protocols are only used for testing and are not needed either for Node-to-Node nor for the Node-to-Client protocols.

### Ping-Pong mini-protocol
#### Description

A client can use the Ping-Pong protocol to check that the server is responsive. The Ping-Pong protocol is very simple because the messages do not carry any data and because the Ping-Pong client and the Ping-Pong server do not access the internal state of the node.

#### State Machine


  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

The protocol uses the following messages. The messages of the Ping-Pong protocol do not carry any data.

:   The client sends a Ping request to the server.

:   The server replies to a Ping with a Pong.

:   Terminate the protocol.

  -- -- --
        
        
        
  -- -- --

  : Ping-Pong mini-protocol messages.

### Request-Response mini-protocol
#### Description

The request-response protocol is polymorphic in the request and response data that is being transmitted. This means that there are different possible applications of this protocol, and the application of the protocol determines the types of requests and responses.

#### State machine


  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

The protocol uses the following messages.

 $(request)$

:   The client sends a request to the server.

 $(response)$

:   The server replies with a response.

 $(done)$

:   Terminate the protocol.

  -- -- ------------ --
        $request$    
        $response$   
                     
  -- -- ------------ --

  : Request-Response mini-protocol messages.

## Handshake mini-protocol

\
\
*node-to-node mini-protocol number*: `0`\
*node-to-client mini-protocol number*: `0`\
node-to-client handshake CDDL spec []{#handshake-protocol label="handshake-protocol"}

### Description

The handshake mini protocol is used to negotiate the protocol version and the protocol parameters that are used by the client and the server. It is run exactly once when a new connection is initialised and consists of a single request from the client and a single reply from the server.

The handshake mini protocol is a generic protocol that can negotiate version number and protocol parameters (these my depend on the version number). It only assumes that protocol parameters can be encoded to and decoded from CBOR terms. A node that runs the handshake protocol must instantiate it with the set of supported protocol versions and callback functions to handle the protocol parameters. These callback functions are specific to the supported protocol versions.

The handshake mini protocol is designed to handle simultaneous TCP open.

### State machine


  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

Messages of the protocol:

 $(versionTable)$

:   The client proposes a number of possible versions and protocol parameters. $versionTable$ is a map from version numbers to their associated version data. Note that different version numbers might use different version data (e.g. supporting a different set of parameters).

 $(versionTable)$

:   This message must not be explicitly sent, it's only to support TCP simultaneous open scenario in which both sides sent . In this case, the received is interpreted as and thus it MUST have the same CBOR decoding as .

 $(versionNumber,extraParameters)$

:   The server accepts $versionNumber$ and returns possible extra protocol parameters.

 $(reason)$

:   The server refuses the proposed versions.

  -- -- ------------------------------- --
        $versionTable$                  
        $versionTable$                  
        $(versionNumber,versionData)$   
        $reason$                        
  -- -- ------------------------------- --

### Size limits per state

These bounds limit how many bytes can be sent in a given state; indirectly, this limits the payload size of each message. If a space limit is violated, the connection SHOULD be torn down.

:::: center

  -- --------
       `5760`
       `5760`
  -- --------

[]{#table:handshake-size-limits label="table:handshake-size-limits"}


### Timeouts per state

These limits bound how much time the receiver side can wait for the arrival of a message. If a timeout is violated, the connection SHOULD be torn down.

:::: center

  -- -------
       `10`s
       `10`s
  -- -------

  : timeouts per state

### Node-to-node handshake

The node-to-node handshake instantiates version data[^1] to a record which consists of

network magic

:   a `Word32` value;

diffusion mode

:   a boolean value: `True` value indicates initiator only mode, `False` - initiator and responder mode;

peer sharing

:   either $0$ or $1$: $1$ indicates that the node will engage in peer sharing (and thus it will run the PeerSharing mini-protocol);

query

:   a boolean value: `True` will send back all supported versions & version data and terminate the connection.

When negotiating a connection, each side will have access to local and remote version data associated with the negotiated version number. The result of negotiation is a new version data record which consists of:

- if the network magic agrees, then it is inherited by the negotiated version data, otherwise the negotiation fails;

- diffusion mode SHOULD be initiator only if and only if any side proposes the initiator-only mode (i.e. the logical disjunction operator);

- peer sharing SHOULD be inherited from the remote side;

- query SHOULD be inherited from the client (the side that sent ).

If the negotiation is successful, the negotiated version data is sent back using , otherwise SHOULD be sent.

#### Size limits per state

These bounds limit how many bytes can be sent in a given state; indirectly, this limits the payload size of each message. If a space limit is violated, the connection SHOULD be torn down.

::: center
  -- --------
       `5760`
       `5760`
  -- --------

#### Timeouts per state

These limits bound how much time the receiver side can wait for the arrival of a message. If a timeout is violated, the connection SHOULD be torn down.

::: center
  -- -------
       `10`s
       `10`s
  -- -------

### Node-to-client handshake

The node-to-node handshake instantiates version data to a record which consists of

network magic

:   a `Word32` value;

query

:   a boolean value: `True` will send back all supported; versions & version data and terminate the connection.

The negotiated version data is computed similarly as in the node-to-node protocol:

- if the network magic agrees, then it is inherited by the negotiated version data, otherwise the negotiation fails;

- query SHOULD be inherited from the client (the side that sent ).

If the negotiation is successful, the negotiated version data is sent back using , otherwise SHOULD be sent.

#### Size limits per state

These bounds limit how many bytes can be sent in a given state; indirectly, this limits the payload size of each message. If a space limit is violated, the connection SHOULD be torn down.

::: center
  -- --------
       `5760`
       `5760`
  -- --------

#### Timeouts per state

No timeouts are used for node-to-client handshake.

### Client and Server Implementation

Section 1.6.9 contains the CDDL specification of the binary format of the handshake messages. The version table is encoded as a CBOR table with the version number as the key and the protocol parameters as a value. The handshake protocol requires that the version numbers ( i.e. the keys) in the version table are unique and appear in ascending order. (Note that CDDL is not expressive enough to precisely specify that requirement on the keys of the CBOR table. Therefore, the CDDL specification uses a table with keys from 1 to 4 as an example.)

In a run of the handshake mini protocol, the peers exchange only two messages: The client initiates the protocol with a message that contains information about all protocol versions it wants to support. The server replies either with an message containing the negotiated version number and version data or a message. The message contains one of three alternative refuse reasons: , or just .

When a server receives a message, it uses the following algorithm to compute the response:

1.  Compute the intersection of the set of protocol version numbers that the server supports and the version numbers requested by the client.

2.  If the intersection is empty: Reply with () and the list of protocol numbers the server supports.

3.  Otherwise, select the protocol with the highest version number in the intersection.

4.  Run the protocol-specific decoder on the CBOR term that contains the protocol parameters.

5.  If the decoder fails: Reply with (), the selected version number and an error message.

6.  Otherwise, test the proposed protocol parameters of the selected protocol version

7.  If the test refuses the parameters: Reply with (), the selected version number and an error message.

8.  Otherwise, compute negotiation parameters according to the algorithm alg:node-to-node-negotiation or alg:node-to-client-negotiation, encode them with the corresponding CBOR codec and reply with , the selected version number and the extra parameters.

Note that in step 4), 6) and 8) the handshake protocol uses the callback functions that are specific for a set of protocols that the server supports. The handshake protocol is designed so that a server can always handle requests for protocol versions that it does not support. The server simply ignores the CBOR terms that represent the protocol parameters of unsupported versions.

In case of simultaneous open of a TCP connection, both handshake clients will send their , and both will interpret the incoming message as (thus, both must have the same encoding; the implementation can distinguish them by the protocol state). Both clients should choose the highest version of the protocol available. If any side does not accept any version (or its parameters), the connection can be reset.

The protocol does not forbid, nor could it detect a usage of outside of TCP simultaneous open. The process of choosing between the proposed and received version must be symmetric in the following sense.

:   We use `acceptable :: vData -> vData -> Accept vData` function to compute accepted version data from local and remote data, where

          data Accept vData = Accept vData
                            | Refuse Text
                            deriving Eq

    See [ref](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-framework/Ouroboros-Network-Protocol-Handshake-Version.html#t:Acceptable). Both `acceptable local remote` and `acceptable remote local` must satisfy the following conditions:

    - if either of them accepts a version by returning `Accept`, the other one must accept the same value, i.e. in this case `acceptable local remote == acceptable remote local`

    - if either of them refuses to accept (returns `Refuse reason`) the other one SHOULD return `Refuse` as well.

Note that the above condition guarantees that if either side returns `Accept`, then the connection will not be closed by the remote end. A weaker condition, in which the return values are equal if they both return `Accept` does not guarantee this property. We also verify that the whole Handshake protocol, not just the `acceptable` satisfies the above property, see [Ouroboros-Network test suite](https://github.com/intersectmbo/ouroboros-network/blob/master/ouroboros-network/protocol-tests/Ouroboros/Network/Protocol/Handshake/Test.hs).

The fact that we are using non-injective encoding in the handshake protocol side steps typed-protocols strong typed-checked properties. For injective codecs (i.e. codecs for which each message has a distinguished encoding), both sides of typed-protocols are always in the same state (once all in-flight the message arrived). This is no longer true in general; however, this is still true for the handshake protocol. Even though the opening message of a simultaneous open will materialise on the other side as a termination message , and the same will happen to the transmitted in the other direction. We include a special test case ([`prop_channel_simultaneous_open`](https://github.com/intersectmbo/ouroboros-network/blob/master/ouroboros-network/protocol-tests/Ouroboros/Network/Protocol/Handshake/Test.hs#L551)) to verify that simultaneous open behaves well and does not lead to protocol errors.

### Handshake and the multiplexer

The handshake mini protocol runs before the multiplexer is initialised. Each message is transmitted within a single MUX segment, i.e. with a proper segment header, but as the multiplexer is not yet running, the messages MUST not be split into multiple segments. The Handshake protocol uses the mini-protocol number $0$ in both node-to-node and node-to-client cases.

### CDDL encoding specification
There are two flavours of the mini-protocol that only differ with type instantiations, e.g., different protocol versions and version data carried in messages. First, one is used by the node-to-node protocol, and the other is used by the node-to-client protocol.

#### Node-to-node handshake mini-protocol

``` {style="cddl"}
```

#### Node-to-client handshake mini-protocol

``` {style="cddl"}
```

## Chain-Sync mini-protocol
\
\
*node-to-node mini-protocol number*: `2`\
*node-to-client mini-protocol number*: `5`\

### Description

The chain synchronisation protocol is used by a blockchain consumer to replicate the producer's blockchain locally. A node communicates with several upstream and downstream nodes and runs an independent client instance and an independent server instance for every other node it communicates with. (See Figure node-diagram-concurrency.)

The chain synchronisation protocol is polymorphic. The node-to-client protocol uses an instance of the chain synchronisation protocol that transfers full blocks, while the node-to-node instance only transfers block headers. In the node-to-node case, the block fetch protocol (Section 1.8) is used to diffuse full blocks.

### State Machine


**State machine of the Chain-Sync mini-protocol**
::::: {.figure latex-placement="h"}
::: center
  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
     [**Server**]{style="color: myblue"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

**Chain-Sync state agencies**
:::::

The protocol uses the following messages:

:   Request the next update from the producer. The response can be a roll forward, a roll back or wait.

:   Acknowledge the request but require the consumer to wait for the next update. This means that the consumer is synced with the producer, and the producer is waiting for its own chain state to change.

 $(header, tip)$

:   Tell the consumer to extend their chain with the given $header$. The message also tells the consumer about the $tip$ of the producer's chain.

 $(point_{old}, tip$

:   Tell the consumer to roll back to a given $point_{old}$ on their chain. The message also tells the consumer about the current $tip$ of the chain the producer is following.

 $\langle point_{head} \rangle$

:   Ask the producer to try to find an improved intersection point between the consumer and producer's chains. The consumer sends a sequence $\langle point \rangle$, which shall be ordered by preference (e.g. points with the highest slot number first), and it is up to the producer to find the first intersection point on its chain and send it back to the consumer. If an empty list of points is sent with , the server will reply with .

 $(point_{intersect} ,tip)$

:   The producer replies with the first point of the request, which is on his current chain. The consumer can decide whether to send more points. The message also tells the consumer about the $tip$ of the producer. Whenever the server replies with , the client can expect the next update (i.e. a replay to ) to be to the specified $point_{intersect}$ (which makes handling state updates on the client side easier).

 $(tip)$

:   Reply to the consumer that no intersection was found: none of the points the consumer supplied are on the producer chain. The message only contains the $tip$ of the producer chain.

:   Terminate the protocol.

  -- -- ---------------------------- --
                                     
        $\langle point\rangle$       
                                     
                                     
        $header$, $tip$              
        $point_{old}$, $tip$         
        $header$, $tip$              
        $point_{old}$, $tip$         
        $point_{intersect}$, $tip$   
        $tip$                        
  -- -- ---------------------------- --

  : Chain-Sync mini-protocol messages.

### Node-to-node size limits per state

Table 1.3 specifies how many bytes can be sent in a given state in the chain-sync mini-protocol of the node-to-node protocol; indirectly, this limits the payload size of each message. If a space limit is violated, the connection SHOULD be torn down.

:::: center

  -- ---------
       `65535`
       `65535`
       `65535`
       `65535`
  -- ---------

  : size limits per state

### Node-to-node timeouts per state
The table 1.4 specifies message timeouts in a given state. If a timeout is violated, the connection SHOULD be torn down.

:::: center

  -- ----------------------------------
                                `3673`s
                                  `10`s
       random between `601`s and `911`s
                                  `10`s
  -- ----------------------------------

  : timeouts per state

### Node-to-client size limits and timeouts

There are no size-limits nor timeouts for the chain-sync mini-protocol of the node-to-client protocol.

### Implementation of the Chain Producer

This section describes a stateful implementation of a chain producer that is suitable for a setting where the producer cannot trust the chain consumer. An important requirement in this setting is that a chain consumer must never be able to cause excessive resource use on the producer side. The presented implementation meets this requirement. It uses a constant amount of memory to store the state that the producer maintains per chain consumer. This protocol is only used to reproduce the producer chain locally by the consumer. By running many instances of this protocol against different peers, a node can reproduce chains in the network and make chain selection, which by design is not part of this protocol. Note that when we refer to the consumer's chain in this section, we mean the chain that is reproduced by the consumer with the instance of the chain-sync protocol and not the result of the chain selection algorithm.

We call the state which the producer maintains about the consumer the *read-pointer*. The *read-pointer* basically tracks what the producer knows about the head of the consumer's chain without storing it locally. It points to a block on the current chain of the chain producer. The *read-pointer*s are part of the shared state of the node (Figure node-diagram-concurrency), and *read-pointer*s are concurrently updated by the thread that runs the chain-sync mini-protocol and the chain tracking logic of the node itself.

We first describe how the mini-protocol updates a *read-pointer* and later address what happens in case of a fork.

###### Initializing the *read-pointer*.

The chain producer assumes that a consumer which has just connected, only knows the genesis block and initialises the *read-pointer* of that consumer with a pointer to the genesis block on its chain.

###### Downloading a chain of blocks

A typical situation is when the consumer follows the chain of the producer but is not yet at the head of the chain (this also covers a consumer booting from the genesis). In this case, the protocol follows a simple, consumer-driven, request-response pattern. The consumer sends messages to ask for the next block. If the *read-pointer* is not yet at the head of the chain, the producer replies with a and advances the *read-pointer* to the next block (optimistically assuming that the client will update its chain accordingly). The message contains the next block and also the head-point of the producer. The protocol follows this pattern until the *read-pointer* reaches the end of its chain.

::::: {#read-pointer-consumer-driver .figure latex-placement="ht"}
::: center

**Consumer-driven block download.**
:::::

###### Producer driven updates

If the *read-pointer* points to the end of the chain and the producer receives a the consumer's chain is already up to date. The producer informs the consumer with an that no new data is available. After receiving a , the consumer waits for a new message, and the producer keeps agency. The switches from a consumer-driven phase to a producer-driven phase.

The producer waits until new data becomes available. When a new block is available, the producer will send a message and give agency back to the consumer. The producer can also get unblocked when its node switches to a new chain fork.

###### Producer switches to a new fork

The node of the chain producer can switch to a new fork at any time, independent of the state machine. A chain switch can cause an update of the *read-pointer*, which is part of the mutable state that is shared between the thread that runs the chain sync protocol and the thread that implements the chain following the logic of the node. There are two cases:

1\) If the *read-pointer* points to a block that is on the common prefix of the new fork and the old fork, no update of the *read-pointer* is needed.

2\) If the *read-pointer* points to a block that is no longer part of the chain that is followed by the node, the *read-pointer* is set to the last block that is common between the new and the old chain. The node also sets a flag that signals the chain-sync thread to send a instead of a . Finally, the producer thread must unblock if it is in the state.

::::: {#read-pointer-rollback .figure latex-placement="ht"}
::: center

***read-pointer* update for a fork switch in case of a rollback.**
:::::

Figure 1.3 illustrates a fork switch that requires an update of the *read-pointer* for one of the chain consumers. Before the switch, the *read-pointer* of the consumer points to block $0x660f$. The producer switches to a new chain with the head of the chain at block $0xcdf0$. The node must update the *read-pointer* to block $0xfa40$, and the next message to the consumer will be a .

Note that a node typically communicates with several consumers. For each consumer, it runs an independent version of the chain-sync-protocol state machine in an independent thread and with its own *read-pointer*. Each of those *read-pointer*s has to be updated independently, and for each consumer, either case 1) or case 2) can apply.

###### Consumer starts with an arbitrary fork

Typically, the consumer already knows some fork of the blockchain when it starts to track the producer. The protocol provides an efficient method to search for the longest common prefix (here called intersection) between the fork of the producer and the fork that is known to the consumer.

To do so, the consumer sends a message with a list of chain points on the chain known to the consumer. If the producer does not know any of the points, it replies with . Otherwise, it replies with and the best (i.e. the newest) of the points that it knows and also updates the *read-pointer* accordingly. For efficiency, the consumer should use a binary search scheme to search for the longest common prefix.

It is advised that the consumer always starts with in a fresh connection and it is free to use at any time later as it is beneficial. If the consumer does not know anything about the producer's chain, it can start the search with the following list of points: $\langle point(b), point(b-1), point(b-2), point(b-4), point (b-8),\ldots \rangle$ where $point(b-i)$ is the point of the $i$th predecessor of block $b$ and $b$ is the head of the consumer fork. The maximum depth of a fork in Ouroboros is bounded, and the intersection will always be found with a small number of iterations of this algorithm.

###### Additional remarks

Note that by sending , the server will not modify its *read-pointer*.

### Implementation of the Chain Consumer

In principle, the chain consumer has to guard against a malicious chain producer as much as the other way around. However, two aspects of the protocol play a role in favour of the consumer here.

- The protocol is consumer-driven, i.e., the producer cannot send unsolicited data to the consumer (within the protocol).

- The consumer can verify the response data itself.

Here are some cases to consider:

 Phase

:   The consumer and the producer play a number guessing game, so the consumer can easily detect inconsistent behaviour.

The producer replies with a 

:   The consumer can verify the block itself with the help of the ledger layer. (The consumer may need to download the block first if the protocol only sends block headers.)

The producer replies with a 

:   The consumer tracks several producers, so if the producer sends false messages, the consumer's node will, at some point, switch to a longer chain fork.

The Producer is just passive/slow

:   The consumer's node will switch to a longer chain coming from another producer via another instance of chain-sync protocol.

### CDDL encoding specification
``` {style="cddl"}
```

See appendix cddl-common for common definitions.

## Block-Fetch mini-protocol
\
\
*node-to-node mini-protocol number*: `3`\

### Description

The block fetching mechanism enables a node to download a range of blocks.

### State machine

:::: {.figure latex-placement="h"}
**State machine of the block-fetch mini-protocol**
::::: {.figure latex-placement="h"}
::: center
  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

**Block-Fetch state agencies**
:::::

##### Protocol messages

 $(range)$

:   The client requests a $range$ of blocks from the server. The range is inclusive on both sides.

:   The server tells the client that it does not have all of the blocks in the requested $range$.

:   The server starts block streaming.

 $(body)$

:   Stream a single block's body.

:   The server ends block streaming.

:   The client terminates the protocol.

The transitions are shown in table 1.5.

:::: center

  -- -- --------- --
                  
        $range$   
                  
                  
        $body$    
                  
  -- -- --------- --

  : Block-Fetch mini-protocol messages.

### Size limits per state

These bounds limit how many bytes can be sent in a given state; indirectly, this limits the payload size of each message. If a space limit is violated, the connection SHOULD be torn down.

:::: center

  -- -----------
         `65535`
         `65535`
       `2500000`
  -- -----------

[]{#table:block-fetch-size-limits label="table:block-fetch-size-limits"}


### Timeouts per state

These limits bound how much time the receiver side can wait for the arrival of a message. If a timeout is violated, the connection SHOULD be torn down.

:::: center

  -- -------
          \-
       `60`s
       `60`s
  -- -------

  : timeouts per state

### CDDL encoding specification
``` {style="cddl"}
```

See appendix cddl-common for common definitions.

## Tx-Submission mini-protocol

\
\
*node-to-node mini-protocol number*: `4`\
[]{#tx-submission-protocol label="tx-submission-protocol"} []{#tx-submission-protocol2 label="tx-submission-protocol2"}

#### Description

The node-to-node transaction submission protocol is used to transfer transactions between full nodes. The protocol follows a pull-based strategy where the initiator asks for new transactions, and the responder sends them back. It is suitable for a trustless setting where both sides need to guard against resource consumption attacks from the other side. The local transaction submission protocol, is a simpler which is used when the server trusts a local client, is described in Section local-tx-submission-protocol.

The *tx-submission* mini-protocol is designed in a way that the information (e.g. transactions) flows across the system in the other direction than in the *chain-sync* or *block-fetch* protocols. Transactions must flow toward the block producer, while headers and blocks disseminate from it to the rest of the system. This is reflected in the protocol graphs, transactions are sent from a client to a server. However, to preserve that all mini-protocols start on the client, the state was added in version 2 of the protocol.

Note that Version 1 of the tx-submission protocol is no longer supported. Version 2 is used since `NodeToNode_V6` of the node-to-node protocol.

### State machine


**State machine of the Tx-Submission mini-protocol (version 2).**
::::: {.figure latex-placement="h"}
::: center
  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
     [**Client**]{style="color: mygreen"}
     [**Client**]{style="color: mygreen"}
     [**Client**]{style="color: mygreen"}
  -- --------------------------------------

**Tx-Submission state agencies**
:::::

##### Protocol messages

:   initial message of the protocol

 $(ack,req)$

:   Request a non-empty list of transaction identifiers from the client, and confirm a number of outstanding transaction identifiers.

    This is a non-blocking operation: the response may be an empty list and this does expect a prompt response. This covers high throughput use cases where we wish to pipeline, by interleaving requests for additional transaction identifiers with requests for transactions, which requires these requests not block.

    The request gives the maximum number of transaction identifiers that can be accepted in the response. Either the numbers acknowledged or the number requested MUST be non-zero. In either case, the number requested MUST not put the total outstanding over the fixed protocol limit (see below in section [1.9.2](#tx-submission-size-limits)).

    The request also gives the number of outstanding transaction identifiers that can now be acknowledged. The actual transactions to acknowledge are known to the peer based on the FIFO order in which they were provided.

    The request MUST be made (over ) if there are non-zer remaining unacknowledged transactions.

 $(ack,req)$

:   The server asks for new transaction ids and acknowledges old ids. The client will block until new transactions are available, thus the respond will always have at least one transaction identifier.

    This is a blocking operation: the response will always have at least one transaction identifier, and it does not expect a prompt response: there is no timeout. This covers the case when there is nothing else to do but wait. For example this covers leaf nodes that rarely, if ever, create and submit a transaction.

    The request gives the maximum number of transaction identifiers that can be accepted in the response. This must be greater than zero. The number requested ids MUST not put the total outstanding over the fixed protocol limit (see below in section [1.9.2](#tx-submission-size-limits)).

    The request also gives the number of outstanding transaction identifiers that can now be acknowledged. The actual transactions to acknowledge are known to the peer based on the FIFO order in which they were provided.

    The request MUST be made (over ) if there are zero remaining unacknowledged transactions.

 ($\langle (id, size) \rangle$) 

:   The client replies with a list of available transactions. The list contains pairs of transaction ids and the corresponding size of the transaction in bytes. In the blocking case, the reply MUST contain at least one transaction identifier. In the non-blocking case, the reply may contain an empty list.

    These transactions are added to the notional FIFO of outstanding transaction identifiers for the protocol.

    The order in which these transaction identifiers are returned must be the order in which they are submitted to the mempool, to preserve dependent transactions.

 ($\langle ids \rangle$)

:   The server requests transactions by sending a non-empty list of transaction-ids.

    While it is the responsibility of the replying peer to keep within pipelining in-flight limits, the sender must also cooperate by keeping the total requested across all in-flight requests within the limits.

    It is an error to ask for transaction identifiers that were not previously announced (via ).

    It is an error to ask for transaction identifiers that are not outstanding or that were already asked for.

 ($\langle txs \rangle$)

:   The client replies with a list of transactions. It may implicitly discard transaction-ids which were requested.

    Transactions can become invalid between the time the transaction identifier was sent and the transaction being requested. Invalid (including committed) transactions do not need to be sent.

    Any transaction identifiers requested but not provided in this reply should be considered as if this peer had never announced them. (Note that this is no guarantee that the transaction is invalid, it may still be valid and available from another peer).

:   Termination message, initiated by the client when the server is making a blocking call for more transaction identifiers.

  -- -- ------------------------------ --
                                       
        $ack$,$req$                    
        $ack$,$req$                    
        $\langle (id, size) \rangle$   
        $\langle (id, size) \rangle$   
        $\langle ids \rangle$          
        $\langle txs \rangle$          
                                       
  -- -- ------------------------------ --

  : Tx-Submission mini-protocol (version 2) messages.

### Size limits per state
Table 1.8 specifies how many bytes can be sent in a given state; indirectly, this limits the payload size of each message. If a space limit is violated, the connection SHOULD be torn down.

:::: center

  -- -----------
          `5760`
          `5760`
       `2500000`
       `2500000`
       `2500000`
  -- -----------

  : size limits per state

#### Maximum number of unacknowledged transaction identifiers

The maximal number of unacknowledged transactions ids is `10`. It is a protocol error to exceed it.

### Timeouts per state

The table 1.9 specifies message timeouts in a given state. If a timeout is violated, the connection SHOULD be torn down.

:::: center

  -- -------
          \-
          \-
          \-
       `10`s
       `10`s
  -- -------

  : timeouts per state

### CDDL encoding specification
``` {style="cddl"}
```

### Client and Server Implementation

The protocol has two design goals: It must diffuse transactions with high efficiency and, at the same time, it must rule out asymmetric resource attacks from the transaction consumer against the transaction provider.

The protocol is based on two pull-based operations. The transaction consumer can ask for a number of transaction ids, and it can use these transaction ids to request a batch of transactions. The transaction consumer has flexibility in the number of transaction ids it requests, whether to actually download the transaction body and flexibility in how it batches the download of transactions. The transaction consumer can also switch between requesting transaction ids and downloading transaction bodies at any time. It must, however, observe several constraints that are necessary for a memory-efficient implementation of the transaction provider.

Conceptually, the provider maintains a limited size FIFO of outstanding transactions per consumer. (The actual implementation can, of course, use the data structure that works best). The maximum FIFO size is a protocol parameter. The protocol guarantees that, at any time, the consumer and producer agree on the current size of that FIFO and on the outstanding transaction ids. The consumer can use a variety of heuristics to request transaction ids and transactions. One possible implementation for a consumer is to maintain a FIFO that mirrors the producer's FIFO but only contains the transaction ids (and the size of the transaction) and not the full transactions.

After the consumer requests new transaction ids, the provider replies with a list of transaction ids and puts these transactions in its FIFO. As part of a request, a consumer also acknowledges the number of old transactions, which are removed from the FIFO at the same time. The provider checks that the size of the FIFO, i.e. the number of outstanding transactions, never exceeds the protocol limit and aborts the connection if a request violates the limits. The consumer can request any batch of transactions from the current FIFO in any order. Note, however, that the reply will omit any transactions that have become invalid in the meantime. (More precisely, the server will omit invalid transactions from the reply, but they will still be counted in the FIFO size, and they will still require an acknowledgement from the consumer).

The protocol supports blocking and non-blocking requests for new transactions ids. If the FIFO is empty, the consumer must use a blocking request; otherwise, it must be a non-blocking request. The producer must reply immediately (i.e. within a small timeout) to a non-blocking request. It replies with not more than the requested number of ids (possibly with an empty list). A blocking request, on the other side, waits until at least one transaction is available.

## Keep Alive Mini Protocol

\
\
*node-to-node mini-protocol number*: `8`\
[]{#keep-alive-protocol label="keep-alive-protocol"}

### Description

Keep-alive mini-protocol is a member of the node-to-node protocol. It is used for two purposes: to provide keep alive messages and do round trip time measurements.

### State machine

:::: {.figure latex-placement="h"}
**State machine of the keep-alive protocol.**
::::: {.figure latex-placement="h"}
::: center
  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

**Keep-Alive state agencies**
:::::

##### Protocol messages

 $cookie$

:   Keep alive message. The $cookie$ value is a `Word16` value, which allows to match requests with responses. It is a protocol error if the cookie received back with does not match the value sent with .

 $cookie$

:   Keep alive response message.

:   Terminating message.

### Size limits per state
These bounds limit how many bytes can be sent in a given state; indirectly, this limits the payload size of each message. If a space limit is violated, the connection SHOULD be torn down.

:::: center

  -- ---------
       `65535`
       `65535`
  -- ---------

[]{#table:keep-alive-size-limits label="table:keep-alive-size-limits"}


### Timeouts per state

These limits bound how much time the receiver side can wait for the arrival of a message. If a timeout is violated, the connection SHOULD be torn down.

:::: center

  -- -------
       `97`s
       `60`s
  -- -------

  : timeouts per state

### CDDL encoding specification
``` {style="cddl"}
```

## Peer Sharing mini-protocol

\
\
*node-to-node mini-protocol number*: `10`\
[]{#peer-sharing-protocol label="peer-sharing-protocol"}

### Description

The Peer-Sharing mini-protocol is a simple Request-Reply mini-protocol. The mini-protocol is used by nodes to share their upstream peers (a subset of their Known Peers).

### State machine

:::: {.figure latex-placement="h"}
**State machine of the peer sharing protocol.**
::::: {.figure latex-placement="h"}
::: center
  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

**Peer-Sharing state agencies**
:::::

##### Protocol messages

 $amount$

:   The client requests a maximum number of peers to be shared ($amount$). Ideally, this amount should limited by a protocol level constant to disallow a bad actor from requesting too many peers.

 ${[}peerAddress{]}$

:   The server replies with a set of peers. The amount of information send is limited by message size limit (see below).

    It is a protocol error to send more peers than it was requested.

    The server should only share peers with which it has (or recently had) an successful inbound or outbound session.

:   Terminating message.

### Size limits per state
These bounds limit how many bytes can be sent in a given state; indirectly, this limits the payload size of each message. If a space limit is violated, the connection SHOULD be torn down.

:::: center

  -- --------
       `5760`
       `5760`
  -- --------

[]{#table:peer-share-size-limits label="table:peer-share-size-limits"}


### Timeouts per state

These limits bound how much time the receiver side can wait for the arrival of a message. If a timeout is violated, the connection SHOULD be torn down.

:::: center

  -- -------
          \-
       `60`s
  -- -------

  : timeouts per state

### Client Implementation Details

The initiator side will have to be running indefinitely since protocol termination means either an error or peer demotion. Because of this, the protocol won't be able to be run as a simple request-response protocol. To overcome this, the client-side implementation will use a registry so that each connected peer gets registered and assigned a controller with a request mailbox. This controller will be used to issue requests to the client implementation, which will be waiting for the queue to be filled up to send a . After sending a request, the result is put into a local result mailbox.

If a peer gets disconnected, it should get unregistered.

#### Deciding from whom to request peers (and how many)

First of all, peer-sharing requests should only be issued if:

- The current number of known peers is less than the target for known peers;

- The rate limit value for peer sharing requests isn't exceeded;

- There are available peers to issue requests to;

If these conditions hold, then we can pick a set of peers to issue requests to. Ideally, this set respects the rate limit value for peer-sharing requests.

If a peer has `PeerSharingDisabled`, flag value, do not ask it for peers. This peer won't even have the Peer-Sharing miniprotocol server running.

The number of peers to request from each upstream peer should aim to fulfil the target for known peers. This number should be split for the current peer target objective across all peer-sharing candidates for efficiency and diversity reasons.

#### Picking peers for the response

Apart from managing the Outbound Governor state correctly, the final result set should be a random distribution of the original set.

This selection should be done in such a way that when the same initial PRNG state is used, the selected set does not significantly vary with small perturbations in the set of published peers.

The intention of this selection method is that the selection should give approximately the same replies to the same peers over the course of multiple requests from the same peer. This is to deliberately slow the rate at which peers can discover and map out the entire network.

### Server Implementation Details

As soon as the server receives a share request, it needs to pick a subset not bigger than the value specified in the request's parameter. The reply set needs to be sampled randomly from the Known Peer set according to the following constraints:

- Only pick peers that we managed to connect to at some point

- Don't pick known-to-be-ledger peers

- Pick peers that have public willingness information (e.g. `DoAdvertisePeer`).

- Pick peers that haven't behaved badly (e.g. `PeerFailCount == 0`)

Computing the result (i.e. random sampling of available peers) needs access to the `PeerSelectionState`, which is specific to the `peerSelectionGovernorLoop`. However, when initialising the server side of the mini-protocol, we have to provide the result computing function early on the consensus side. This means we will have to find a way to delay the function application all the way to diffusion and share the relevant parts of `PeerSelectionState` with this function via a `TVar`.

### CDDL encoding specification ($\geq 14$)
``` {style="cddl"}
```

## Local Tx-Submission mini-protocol

\
\
*node-to-client mini-protocol number*: `6`\
[]{#local-tx-submission-protocol label="local-tx-submission-protocol"}

### Description

The local transaction submission mini protocol is used by local clients, For example, wallets or CLI tools are used to submit transactions to a local node. The protocol is **not** used to forward transactions from one core node to another. The protocol for the transfer of transactions between full nodes is described in Section tx-submission-protocol2.

The protocol follows a simple request-response pattern:

1.  The client sends a request with a single transaction.

2.  The Server either accepts the transaction (returning a confirmation) or rejects it (returning the reason).

Note that the local transaction submission protocol is a push-based protocol where the client creates a workload for the server. This is acceptable because this mini-protocol is only to be used between a node and a local client.

### State machine

:::: {.figure latex-placement="h"}
**State machine of the Local Tx-Submission mini-protocol.**
::::: {.figure latex-placement="h"}
::: center
  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

**Local Tx-Submission state agencies**
:::::

##### Protocol messages

 $(t)$

:   The client submits a single transaction. It MUST wait for a reply.

:   The server confirms that it accepted the transaction.

 $(reason)$

:   The server informs the client that it rejected the transaction and provides a $reason$.

:   The client terminates the mini protocol.

### Size limits per state
No size limits.

### Timeouts per state

No timeouts.

### CDDL encoding specification
``` {style="cddl"}
```

See appendix cddl-common for common definitions.

## Local State Query mini-protocol
\
\
*node-to-client mini-protocol number*: `7`\

### Description

Local State Query mini-protocol allows querying of the consensus/ledger state. This mini protocol is part of the node-to-client protocol; hence, it is only used by local (and thus trusted) clients. Possible queries depend on the era (Byron, Shelly, etc.) and are not specified in this document. The protocol specifies basic operations like acquiring/releasing the consensus/ledger state, which is done by the server, or running queries against the acquired ledger state.

### State machine

:::: {.figure latex-placement="h"}
**State machine of the Local State Query mini-protocol.**
:::: {.figure latex-placement="h"}
::: center
  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

##### Protocol messages

See Figure 1.5, where $AcquireFailure$ is either:

- $AcquireFailurePointTooOld$, or

- $AcquireFailurePointNotOnChain$

$Target$ is either $ImmutableTip$, $VolatileTip$, or $SpecificPoint pt$.

The primary motivation for being able to acquire the $ImmutableTip$ is that it's the most recent ledger state that the node will never abandon: the node will never rollback to a prefix of that immutable chain (unless the on-disk ChainDB is corrupted/manipulated). Therefore, answers to queries against the $ImmutableTip$ is necessarily not subject to rollback.

:   The client requests that the $Target$ ledger state on the server's be made available to query, and waits for confirmation or failure.

:   The server can confirm that it has the state at the requested point.

:   The server can report that it cannot obtain the state for the requested point.

:   The client can perform queries on the current acquired state.

:   The server must reply with the queries.

:   The client can instruct the server to release the state. This lets the server free resources.

:   This is like but for when the client already has a state. By moving to another state directly without a it enables optimisations on the server side (e.g. moving to the state for the immediate next block).

    Note that failure to re-acquire is equivalent to , rather than keeping the exiting acquired state.

:   The client can terminate the protocol.


  -- -- ------------------ --
        $Target\ point$    
        $AcquireFailure$   
                           
        $query$            
        $result$           
        $Target\ point$    
                           
                           
  -- -- ------------------ --

**Local State Query mini-protocol messages.**
### Size limits per state
No size limits.

### Timeouts per state

No timeouts.

### CDDL encoding specification
``` {style="cddl"}
```

See appendix cddl-common for common definitions.

## Local Tx-Monitor mini-protocol

\
\
*node-to-client mini-protocol number*: `9`\
[]{#local-tx-monitor-protocol label="local-tx-monitor-protocol"}

### Description

A mini-protocol which allows the monitoring of transactions in the local mempool. This mini-protocol is stateful; the server side tracks transactions already sent to the client.

### State machine

:::: {.figure latex-placement="h"}
**State machine of the Local Tx-Monitor mini-protocol.**
::::: {.figure latex-placement="h"}
::: center
  -- --------------------------------------
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
     [**Client**]{style="color: mygreen"}
     [**Server**]{style="color: myblue"}
  -- --------------------------------------

**Local Tx-Monitor state agencies**
:::::

##### Protocol messages

:   Acquire the latest snapshot. This enables subsequent queries to be made against a consistent view of the mempool.

 (SlotNo)

:   The server side is now locked to a particular mempool snapshot. It returns the slot number of the 'virtual block' under construction.

:   Like 'MsgAcquire' but await a new snapshot different from the one currently acquired.

:   Release the acquired snapshot in order to loop back to the idle state.

:   The client requests a single transaction and waits for a reply.

 (**Nothing** \| **Just** $tx$)

:   The server responds with a single transaction if one is available in the mempool. This must be a transaction that was not previously sent to the client for this particular snapshot.

:   The client checks whether the server knows of a particular transaction identified by its id.

 (Bool)

:   The server responds `True` when the given tx is present in the snapshot, `False` otherwise.

:   The client asks the server about the mempool current size and max capacity.

 (Word32,Word32,Word32)

:   The server responds with three sizes. The meaning of them are:

    capacity in bytes

    :   the maximum capacity of the mempool (note that this may dynamically change when the ledger state is updated);

    size in bytes

    :   the summed byte size of all the transactions in the mempool;

    number of transactions

    :   the number of transactions in the mempool.

:   The client asks the server for information on the mempool's measures.

 (Word32, Map Text (Integer, Integer))

:   The server responds with the total number of transactions currently in the mempool, and a map of the measures known to the mempool. The keys of this map are textual labels of the measure names, which should typically be considered stable for a given node version, and the values are a pair of integers representing the current size and maximum capacity respectively for that measure. The maximum capacity should not be considered fixed and is likely to change due to mempool conditions. The size should always be less than or equal to the capacity.


  --- -- ----------------------------------- ---
                                             
         SlotNo                              
                                             
                                             
                                              
         (**Nothing** \| **Just** $tx$)      
                                              
         Bool                                
                                              
         Word32,Word32,Word32                
                                              
         Word32,Map Text (Integer,Integer)   
                                             
  --- -- ----------------------------------- ---

**Local Transaction Monitor mini-protocol messages.**
### Size limits per state
No size limits.

### Timeouts per state

No timeouts.

### CDDL encoding specification
``` {style="cddl"}
```

See appendix cddl-common for common definitions.

## Pipelining of Mini Protocols
Protocol pipelining is a technique that improves the performance of some protocols. The underlying idea is that a client that wants to perform several requests just transmits those requests in sequence without blocking and waiting for the reply from the server. In the reference implementation, pipelining is used by the clients of all mini-protocols except Chain-Sync. Those mini-protocols follow a request-response pattern that is amenable to pipelining such that pipelining becomes a feature of the client implementation and does not require any modifications to the server implementation.

As an example, let's consider the Block-Fetch mini protocol. When a client follows the protocol and sends a sequence of  messages to the server, the data stream from the client to the server will only consist of  messages (and a final  message) and no other message types. The server can simply follow the state machine of the protocol and process the messages in turn, regardless of whether the client uses pipelining or not. The MUX/DEMUX layer (Chapter chapter:multiplexer) guarantees that messages of the same mini protocol are delivered in transmission order. Therefore, the client can determine which response belongs to which request.

The MUX/DEMUX layer also provides a fixed-size buffer between the egress of DEMUX and the ingress of mini protocol thread. The size of this buffer is a protocol parameter that determines how many messages a client can send before waiting for a reply from the server (see Section mux-flow-control). The protocol requires that a client must never cause an overrun of these buffers on a server node. If a message arrives at the server that would cause the buffer to overrun, the server treats this case as a protocol violation of the peer (and closes the connection to the peer).

## Node-to-node protocol
\
\

The *node-to-node protocol* consists of the following protocols:

- *chain-sync mini-protocol* for headers (section 1.7)

- *block-fetch mini-protocol* (section 1.8)

- *tx-submission mini-protocol*; from `NodeToNodeV_6` the version 2 is used (section tx-submission-protocol2)

- *keep alive mini-protocol*; from `NodeToNodeV_3` (section keep-alive-protocol)

- *peer-sharing mini-protocol*; from `NodeToNodeV_11` (section peer-sharing-protocol)

Currently supported versions of the *node-to-node protocol* are listed in table 1.7.

::::: {#table:node-to-node-protocol-versions .figure latex-placement="h"}
::: center
  ------------------ ------------------------------------------------------------------------------
  `NodeToNodeV_14`   No changes, identifies Plomin HF nodes mandatory on mainnet as of 2025.01.29
  `NodeToNodeV_15`   No changes, identifies nodes which support SRV records
  ------------------ ------------------------------------------------------------------------------

**Node-to-node protocol versions**
:::::

\
Previously supported node-to-node versions are listed in table table:historical-node-to-node-protocol-versions.

### Node-to-node mux mini-protocol numbers

The following table 1.14 shows mux mini-protocol numbers assigned to each node-to-node mini-protocol.

:::: center

  --------------------------------------------------- ------
  Handshake                     $0$
  Chain-Sync                   $2$
  Block-Fetch                 $3$
  Tx-Submission            $4$
  Keep-Alive                   $8$
  Peer-Sharing (optional)    $10$
  --------------------------------------------------- ------

  : Node-to-node protocol numbers

### Node-to-node mux ingress buffer size limits

Ingress buffer is the buffer which holds received data for a given mini-protocol. It is an internal detail of the multiplexer. Each implementation should define its ingress buffer size limits. Here we specify the default choices we made for Cardano Node. These limits depend on how much pipelining depth a given mini-protocol can do. This is an internal implementation detail since the amount of pipelining is controlled by the peer who owns its ingress buffer.

:::: center

  ------------------------------------------- -----------------
  Handshake                           \-
  Chain-Sync                 $462\,000$
  Block-Fetch          $230\,686\,940$
  Tx-Submission          $721\,424$
  Keep-Alive                   $1\,408$
  Peer-Sharing               $5\,760$
  ------------------------------------------- -----------------

  : Mux ingress buffer sizes for each mini-protocol

## Node-to-client protocol
\
\

The *node-to-client protocol* consists of the following protocols:

- *chain-sync mini-protocol* for blocks (section 1.7)

- *local-tx-submission mini-protocol* (section local-tx-submission-protocol)

- *local-state-query mini-protocol*; from version `NodeToClientV_2` (section 1.13)

- *local tx-monitor mini-protocol*; from version `NodeToClientV_12` (section local-tx-monitor-protocol)

Supported versions of *node-to-client protocol* are listed in table 1.8.

::::: {#table:node-to-client-protocol-versions .figure latex-placement="h"}
::: center
  -------------------- ----------------------------------------------------------------
  `NodeToClientV_16`   Conway era, `ImmutableTip` and `GetStakeDelegDeposits` queries
  `NodeToClientV_17`   `GetProposals`, `GetRatifyState` queries
  `NodeToClientV_18`   `GetFuturePParams` query
  `NodeToClientV_19`   `GetBigLedgerPeerSnapshot` query
  `NodeToClientV_20`   `QueryStakePoolDefaultVote` query;
                       added `MsgGetMeasures` and `MsgReplyGetMeasures` queries
  `NodeToClientV_21`   new codecs for `PParams` and `CompactGenesis`
  -------------------- ----------------------------------------------------------------

**Node-to-client protocol versions**
:::::

\
Previously supported node-to-client versions are listed in table table:historical-node-to-client-protocol-versions.

### Node-to-client mux mini-protocol numbers

The following table 1.16 show mux mini-protocol numbers assigned to each node-to-client mini-protocol.

:::: center

  ------------------------------------------------------ -----
  Handshake                        $0$
  Chain-Sync                      $5$
  Local Tx-Submission    $6$
  Local State Query        $7$
  Local Tx-Monitor          $9$
  ------------------------------------------------------ -----

  : Node-to-client protocol numbers

### Node-to-client mux ingress buffer size limits

All *node-to-client protocols* are using very large ingress buffer size limits of $4\,294\,967\,295$ bytes, effectively there are no size limits.

[^1]: To be precise, in ouroboros-network, we instantiate version data to CBOR terms and do encoding / decoding of version data lazily (as required) rather than as part of the protocol codec (the protocol codec only decodes bytes to CBOR terms, and thus fails only if received bytes are not a valid CBOR encoding). This is important in order to support receiving a mixture of known and unknown versions. The same the remark applies to the node-to-client protocol as well.
