# Connection Manager State Machine Specification {#chapter:connection-manager}

= \[ diamond , fill=DarkSeaGreen1 , text width=4.5em , text badly centered , node distance=3cm , inner sep=0pt \] = \[ rectangle , rounded corners , fill=DodgerBlue1 , minimum height=2em \] = \[ rectangle , rounded corners , fill=HotPink3 , minimum height=2em \] = \[ rectangle , rounded corners , fill=DarkOliveGreen3 , minimum height=2em \] = \[ rectangle , rounded corners , fill=LightBlue2 , rounded corners , minimum height=2em \] = \[ draw , -latex' \] = \[ rectangle , rounded corners , fill=red!255!blue!20 , minimum height=2em \] = \[ color = DodgerBlue1 \] = \[ color = HotPink3 \] = \[ color = DarkOliveGreen3 \] = \[ color = Orange2 \] = \[ color = Turquoise \] = \[ color = DarkOrchid2 \]

## Introduction

As described in the [Network Design](https://ouroboros-network.cardano.intersectmbo.org/pdfs/network-design) document, the goal is to transition to a more decentralised network. To make that happen, a plan was designed to come up with a P2P network that is capable of achieving desired network properties. One key component of such design is the *p2p governor*, which is responsible for managing the *cold*/*warm*/*hot* peer selection, managing the churn of these groups, and adjusting the targets in order for the network to reach the desired properties. However, having *warm* and *hot* peers implies establishing a bearer connection; *hot* peers need to run several mini-protocols, and each mini-protocol runs two instances (client and server). This means that with a large enough warm/hot peer target, there's going to be a lot of resource waste when it comes to file descriptor usage. There's also the problem of firewalls, where it matters who tries to start a communication with whom (if it's the client or the server).

Knowing this, it would be good to make the most of each connection and, in order to do so, the *Connection manager* was designed.

## Components

Figure [1.1](#tik:components){reference-type="ref" reference="tik:components"} illustrates the three main components of the decentralisation process from the perspective of a local node. In the `Outbound` side, the *p2p governor*, as said previously, takes care of all connection initiation (outbound connections) and decides which mini-protocols to run (*established*, *warm* or *hot*). In the `Inbound` side, the `Server` is just a simple loop, responsible for accepting incoming connections; and the `Inbound Protocol Governor` role is starting/restarting the required mini-protocols, to detect if its local peer was added as a *warm*/*hot* peer in some other remote node and to set timers in some cases, e.g. if the remote end opened a connection and did not send any message; the `Inbound Protocol Governor` will timeout after some time and close the connection. The arrows in Figure [1.1](#tik:components){reference-type="ref" reference="tik:components"} represent dependencies between components: The server accepts a connection, which is then given to *Connection manager*. *Connection manager* exposes methods to update its state whenever the `Inbound Protocol Governor` notices that the connection was used (could be used due to *warm*\
hot transitions). If peer sharing is enabled, the incoming address will eventually be added to the known set of the outbound governor.

:::: {#tik:components .figure latex-placement="h"}
::: caption
Main components
:::
::::

Using a TCP connection in both directions rather than two independent TCP connections is suitable for efficient use of network resources, but more importantly, it is crucial to support certain essential scenarios where one node is behind a firewall that blocks incoming TCP connections. For example, it is good practice to have a block-producing node behind a firewall while deploying relay nodes outside of it. If the node behind the firewall can establish an outbound TCP connection to its relays but still has those relays select the block-producing node as an upstream peer, which means that node operators do not need to configure any holes and/or port forwarding in the firewall. If we were only to support running mini-protocols in one direction, then this scenario would require a hole in the firewall to allow the relays to establish incoming connections to the block-producing node. That would be both less secure and also require additional configuration.

Consider, however, what is required to make this scenario work.

1.  We must start with an outbound connection being established from the block-producing node to a relay.

2.  The block-producing node wants the relay as an upstream peer -- to receive blocks from the rest of the network -- so the normal mini-protocols need to be run with the block-producing node in the client role and relay in the server role. So initially, at least, the relay had to act as a server to accept the connection and to run the server side of the mini-protocols.

3.  Next, however, we want the relay to be able to select the block-producing node as an upstream peer, and we want it to do so by reusing the existing connection since we know the firewall makes it impossible to establish a new outbound connection to the block-producing node. Thus, we must be able to have the relay start the client side of the usual mini-protocols and The block-producer must be running on their server side.

4.  So, notice that this means we have started with just running the mini-protocols in one direction and transitioned to running them in both directions, what we call full *duplex*.

5.  Furthermore, such transitions are not a one-off event. It is entirely possible for a node to select another peer as an upstream peer and later change its mind. This means we could transition from duplex back to unidirectional -- and that unidirectional direction need not even be the same as the initial direction!

This leads to a couple of observations:

1.  that, in the general case, we need to support any number of transitions between unidirectional and duplex use of a connection and

2.  that once a bearer has been established, the relationship between the two ends is symmetric: the original direction hardly matters.

A consequence of all this is that we cannot use a classic client/server design. We are decoupling the ongoing role of the connection from who initiated it. That is, we cannot just run a server component that manages all the connections and threads for the server (inbound) side of things and a separate component that manages the connections and threads for the client (outbound) side of things. The connections have to be a shared resource between the inbound and outbound sides so that we can use connections in either or both directions over the lifetime of a connection.

Although actual TCP connections must be a shared resource, we do not wish to Intermingle the code to handle the inbound and outbound directions. As noted above, the selection of upstream (outbound) peers is quite complicated, and we would not want to add to that complexity by mixing it with a lot of other concerns, and vice versa. To minimise complexity, it would be preferable if the code that manages the outbound side would be completely unaware of the inbound side and vice versa. Yet, we still want the inbound and outbound sides to opportunistically share TCP connections where possible. This appears to be eminently achievable given that we are using multiplexing to run mini-protocols in either direction and concurrency for mini-protocol handlers to achieve a degree of modularity.

The use of a single TCP connection helps simplify exception processing and mitigate poor peer performance in a timely manner (whether connection-related or otherwise). This is covered in more detail in [1.3](#sec:exceptions){reference-type="ref+label" reference="sec:exceptions"}.

These ideas lead to the design illustrated in [1.1](#tik:components){reference-type="ref+label" reference="tik:components"}. In this design, there is an outbound and inbound side -- which are completely unaware of each other -- mediated by a shared *connection manager* component.

The connection manager is there to manage the underlying TCP connection resources. It has to provide an interface to the outbound side to enable the use of connections in an outbound direction. Correspondingly, it must provide an interface to the inbound side to enable the use of connections in an inbound direction. Internally, it must deal with connections being used in a unidirectional or duplex way, as well as the transitions between them. Of course, it can be the case that connections are no longer required in either direction, and such connections should be closed in an orderly manner. This must be the responsibility of the connection manager since it is the only component that can see both inbound and outbound sides to be able to see that a connection is no longer needed in either direction and, hence, not needed at all.

In the next couple of sections, we will review the inbound and outbound sides need to be able to do, and what service does the connection manager need to provide?

## Exception Processing {#sec:exceptions}

We maintain a one-to-one correspondence between peers and connections, which simplifies exception handling since if there's a single mini-protocol violation, we need to shut down the thread that handles that particular connection. Although multiple threads handle a single connection: two threads per a pipelined mini-protocol, one thread per a non-pipelined one, plus two multiplexer threads (muxer & demuxer threads). However, all these threads are spawned and managed by the multiplexer, which has the property that if any of the threads throws an exception, all of the threads will be killed. This property allows us to have a single error handling policy (called [`RethrowPolicy`](https://ouroboros-network.cardano.intersectmbo.org/ouroboros-network-framework/Ouroboros-Network-RethrowPolicy.html#t:RethrowPolicy)) per connection handler thread. A `RethrowPolicy` classifies exceptions into two categories, depending on whether an exception should terminate the connection or be propagated to terminate the whole process. `RethrowPolicy`-ies can be composed in terms of a semi-group. Network code only makes `IOManagerError`s fatal. On top of that, consensus introduces its own [`consensusRethrowPolicy`](https://ouroboros-consensus.cardano.intersectmbo.org/haddocks/ouroboros-consensus-diffusion/Ouroboros-Consensus-Node-RethrowPolicy.html#v:consensusRethrowPolicy) for the Node-To-Node protocol.

## Mini-protocol return values {#sec:mini-protocol-return-values}

Handling of mini-protocol return values is a complementary feature to exception processing, hence it's described here, although it is done at the Outbound-Governor level rather than Connection-Manager level, which is primarily described in this part of the documentation.

We classify mini-protocol return values for initiator/client mini-protocols (this feature is only needed for the *chain-sync mini-protocol*). For a given return value, we compute the re-promotion delay used by the Outbound-Governor. Here is the [`returnPolicy`](https://ouroboros-consensus.cardano.intersectmbo.org/haddocks/ouroboros-consensus-diffusion/Ouroboros-Consensus-Node-ExitPolicy.html#v:returnPolicy). introduced in Ouroboros-Consensus for the Node-To-Node protocol. Cardano-Node is not managing outbound node-to-client connection; hence, a policy for the node-to-client protocol is not needed.

The outbound governor is also given a policy which controls how long to wait until re-promote a peer after an exception (for now, we use a fixed delay).

## Outbound side: the outbound governor

A key component of the design for decentralisation is the outbound governor. It is responsible for:

- managing the selection of upstream peers;

- managing the transitions of upstream peers between cold/warm/hot states;

- continuously making progress towards the target number of peers in each state; and

- adjusting these targets over time to achieve a degree of 'churn'.

Taken together, and with appropriate policies, a network of nodes should be able to self-organise and achieve the desired properties. We have simulation results that give us a good degree of confidence that this is indeed the case at a large scale.

Fortunately, while the outbound governor's decision-making procedures are relatively complex, the use of connections is quite simple. The governor needs only two interactions.

Acquire a connection.

:   The governor decides when to promote a peer from cold to warm. To perform the promotion, it needs to acquire access to a connection -- either fresh or pre-existing. To complete the promotion, the client side of warm mini-protocols will be started.

Release a connection.

:   The governor also decides when to demote a peer to cold. As part of the demotion, the client-side mini-protocols are terminated. The connection is then no longer needed by the governor and is released.

It is worth noting again that the outbound governor does not require exclusive access to the TCP bearer. It has no special TCP-specific needs during setup or shutdown. It needs access to the multiplexer to be able to run a set of mini-protocols in one direction. So, in a sense, it needs exclusive access to 'half' of a multiplexer for a connection, but it does not need to coordinate with or even be aware of any use of the other 'half' of the multiplexer. It is this separation of concerns that enables a modular design and implementation.

## Inbound side: the server

The inbound side has a less complex task than the outbound governor, but its interactions with the connection manager are slightly more complicated.

The inbound side is split into two components: the server and the inbound governor.

The server is responsible for accepting new TCP connections on the listening socket. It is responsible for not exceeding resource limits by accepting too many new connections. It is also responsible for a little bit of DoS protection: limiting the rate of accepting new connections.

The server component is much simpler than in most network server applications because it does not need to manage the connection resources once created. The server hands new connections over to the connection manager as soon as they are accepted. The server's responsibilities end there. The server needs only two interactions with the connection manager.

Query number of connections

:   The server component needs to query the connection manager to find the current number of connections. It uses this information to decide if any new connections can be accepted or if we are at the resource limits. Below the hard limits, the current number can be used as part of rate-limiting decisions.

Hand over a new connection

:   Once the server component has successfully accepted a new connection, it needs to hand over responsibility for it to the connection manager.

## Inbound side: the inbound governor

The inbound governor is responsible for starting, restarting and monitoring the the server side of the mini-protocols.

One of the high-level design choices is that when a server-side mini-protocol terminates cleanly (usually because the client chose to terminate it), then the the server side of the mini-protocol should be restarted in its initial state in case the client wishes to use the protocol again later. It is the inbound governor that is responsible for doing this.

The mux component provides a mechanism to start mini-protocol handlers on a connection for a specific mini-protocol number in a particular direction. These handlers can then be monitored to see when they terminate. The inbound governor relies on this mechanism to monitor when the protocol handler terminates cleanly. When it does terminate cleanly, the governor restarts the mini-protocol handler.

All the mini-protocols have the property that agency starts with the client/initiator side[^1]. This allows all of the server/responder side protocols to be started in the mux 'on-demand' mode. In the on-demand mode, the protocol handler thread is not started until the client's first message arrives.

The inbound governor gets informed of new connections that should be monitored either via the server or by the connection manager. The server informs the governor about fresh inbound connections. The connection manager informs the governor about connections that started due to a request for an outbound connection -- at least for those connections that are to be available to use in duplex mode.

As illustrated in [1.1](#tik:components){reference-type="ref+label" reference="tik:components"}, both the connection manager and server components communicate with the inbound governor directly. They do this to inform the inbound governor about new connections so that it can start to run and monitor the server-side protocols. The server notifies about new connections established inbound, while the connection manager acquires new connections established outbound (at least the duplex ones) through the connection manager API. A slight simplification would be to have only one of these routes of notification.

The inbound governor

One simple illustration of how these three components interact together:

- Server accepts a connection;

- Server registers that connection to the connection manager (which puts the connection in `UnnegotiatedState Inbound`);

- Assuming the handshake was successful, the connection is put in `InboundIdleState`^$\tau$^` Duplex`;

- The remote end transitions the local node to warm (using the connection) within the expected timeout;

- IPG (Inbound Protocol Governor) notifies the *Connection manager* about this state change, via `promotedToWarmRemote`. Now the connection is in `InboundState Duplex`;

- *Connection manager* is asked for an outbound connection to that peer (by the *p2p governor*), it notices that it already has a connection with that peer in `InboundState Duplex`, so it gives that connection to *p2p governor* and updates its state to `DuplexState`.

You can find more information about the possible different connection states in the section [1.8.3](#sec:connection-state){reference-type="ref" reference="sec:connection-state"}.

## Connection Manager

### Overview

*Connection manager* is a lower-level component responsible for managing connections and its resources. Its responsibilities consist of:

- Tracking each connection, in order to keep an eye on the bounded resources;

- Starting new connections, negotiating if the connection should be *full-duplex* or *half-duplex*, through the *Connection Handler*;

- Be aware of *warm*/*hot* transitions, in order to try and reuse already established connections;

- Negotiating which direction, which mini-protocol is going to run (Client $\rightarrow$ Server, Server$\rightarrow$Client, or both);

- Taking care of a particularity of TCP connection termination (lingering connections).

The *Connection manager* creates and records accepted connections and keeps track of their state as negotiations for the connection and start/stop mini-protocols are made. There's an *internal state machine* that helps the *Connection manager* keep track of the state of each connection, and help it make decisions when it comes to resource management and connection reusing.

The *Connection Handler* drives through handshake negotiation and starts the multiplexer. The the outcome of the handshake negotiation is:

- the negotiated version of the protocol

- negotiated parameters, which include the mode in which the connection will be run (`InitiatorOnlyMode`, `ResponderOnlyMode`,\
  `InitiatorAndResponderMode` - the first two are *half-duplex*, the last one is *full-duplex* mode)

- Handshake might error

![Duplex connection running several mini-protocols](figure/node-to-node-ipc.png){#fig:protocol-diagram width="\\linewidth"}

The *Connection Handler* notifies the *Connection manager* about the result of a negotiation, which triggers a state transition. If we can run the connection in full-duplex mode, then it is possible to run the bundles of mini-protocols in both directions and otherwise only in one direction. So, Figure [1.2](#fig:protocol-diagram){reference-type="ref" reference="fig:protocol-diagram"} shows $6$ mini protocols running, $3$ in each direction. If we negotiated only a unidirectional connection, then we'd only be running $3$ (The direction is based on which peer established the connection).

From the point of view of the *connection manager*, it only matters whether an *unidirectional* or *duplex* connection was negotiated. Unidirectional connections are the ones that run exclusively on either the initiator or responder side of mini-protocols, while duplex connections can run either or both initiator and responder protocols. Note that in the outbound direction (initiator side), it is the *p2p governor* responsibility to decide which set of mini-protocols: *established*, *warm* or *hot*, are running. On the inbound side (responder mini-protocols), we have no choice but to run all of them.

The *connection manager* should only be run in two `MuxMode`s:

- `ResponderMode` or

- `InitiatorAndResponderMode`

, the `InitiatorMode` is not allowed, since that mode is reserved for special leaf nodes in the network (such as the blockchain explorer, for example), and it doesn't make sense to run a node-to-client client side.

The duplex mode: `InitiatorAndResponderMode` is useful for managing connection with external nodes (*node-to-node protocol*), while `ResponderMode` is useful for running a server which responds to local connections (server side of *node-to-client protocol*).

*Connection manager* can use at most one [ipv4]{.sans-serif} and at most one [ipv6]{.sans-serif} address. It will bind to the correct address depending on the remote address type ([ipv4]{.sans-serif}/[ipv6]{.sans-serif}).

In this specification, we will often need to speak about two nodes communicating via a [TCP]{.sans-serif} connection. We will often call them local and remote ends of the connection or local / remote nodes; we will usually take the perspective of the local node.

### Types

*Connection manager* exposes two methods to register a connection:

    data Connected peerAddr handle handleError
      -- | We are connected, and mux is running.
      = Connected    !(ConnectionId peerAddr) !handle

      -- | There was an error during the handshake negotiation.
      | Disconnected !(ConnectionId peerAddr) !(Maybe handleError)

    -- | Include the outbound connection in 'ConnectionManager'.

    --   This executes:
    --
    -- * \(Reserve\) to \(Negotiated^{*}_{Outbound}\) transitions
    -- * \(PromotedToWarm^{Duplex}_{Local}\) transition
    -- * \(Awake^{Duplex}_{Local}\) transition
    requestOutboundConnection
      *'$\coloncolon$'* HasInitiator muxMode ~ True
      *'$\Rightarrow$'* ConnectionManager muxMode socket peerAddr handle handleError m
      *'$\rightarrow$'* peerAddr *'$\rightarrow$'* m (Connected peerAddr handle handleError)

    -- | Include an inbound connection into 'ConnectionManager'.

    --   This executes:
    --
    -- * \(Accepted\) \/ \(Overwritten\) to \(Negotiated^{*}_{Inbound}\) transitions
    includeInboundConnection
      *'$\coloncolon$'* HasResponder muxMode ~ True
      *'$\Rightarrow$'* ConnectionManager muxMode socket peerAddr handle handleError m
      *'$\rightarrow$'* socket *'$\rightarrow$'* peerAddr *'$\rightarrow$'* m (Connected peerAddr handle handleError)

The first one asks the *connection manager* to either connect to an outbound peer or, if possible, reuse a duplex connection. The other one allows registering an inbound connection, which was `accepted`. Both methods block operations and return either an error (handshake negotiation error or a multiplexer error) or a handle to a *negotiated* connection.

Other methods which are discussed in this specification:

    -- | Custom Either type for the result of various methods.
    data OperationResult a
        = UnsupportedState !InState
        | OperationSuccess a

    -- | Enumeration of states, used for reporting; constructors elided from this
    -- specification.
    data InState

    -- | Unregister an outbound connection.
    --
    --   This executes:
    --
    -- * \(DemotedToCold^{*}_{Local}\) transitions
    unregisterOutboundConnection
      *'$\coloncolon$'* HasInitiator muxMode ~ True
      *'$\Rightarrow$'* ConnectionManager muxMode socket peerAddr handle handleError m
      *'$\rightarrow$'* peerAddr *'$\rightarrow$'* m (OperationResult ())

    -- | Notify the 'ConnectionManager' that a remote end promoted us to a
    -- /warm peer/.
    --
    -- This executes:
    --
    -- * \(PromotedToWarm^{Duplex}_{Remote}\) transition,
    -- * \(Awake^{*}_{Remote}\) transition.
    promotedToWarmRemote
      *'$\coloncolon$'* HasInitiator muxMode ~ True
      *'$\Rightarrow$'* ConnectionManager muxMode socket peerAddr handle handleError m
      *'$\rightarrow$'* peerAddr *'$\rightarrow$'* m (OperationResult InState)

    -- | Notify the 'ConnectionManager' that a remote end demoted us to a /cold
    -- peer/.
    --
    -- This executes:
    --
    -- * \(DemotedToCold^{*}_{Remote}\) transition.
    demotedToColdRemote
      *'$\coloncolon$'* HasResponder muxMode ~ True
      *'$\Rightarrow$'* ConnectionManager muxMode socket peerAddr handle handleError m
      *'$\rightarrow$'* peerAddr -> m (OperationResult InState)

    -- | Unregister outbound connection. Returns if the operation was successful.
    --
    -- This executes:
    --
    -- * \(Commit*{*}\) transition
    -- * \(TimeoutExpired\) transition
    unregisterInboundConnection
      *'$\coloncolon$'* HasResponder muxMode ~ True
      *'$\Rightarrow$'* ConnectionManager muxMode socket peerAddr handle handleError m
      *'$\rightarrow$'* peerAddr *'$\rightarrow$'* m (OperationResult DemotedToColdRemoteTr)

    -- | Number of connections tracked by the server.
    numberOfConnections
      *'$\coloncolon$'* HasResponder muxMode ~ True
      *'$\Rightarrow$'* ConnectionManager muxMode socket peerAddr handle handleError m
      *'$\rightarrow$'* STM m Int

### Connection states {#sec:connection-state}

Each connection is either initiated by `Inbound` or `Outbound` side.

    data Provenance
      = Inbound
      | Outbound

Each connection negotiates `dataFlow`:

    data DataFlow
      = Unidirectional
      | Duplex

In `Unidirectional` data flow, the connection is only used in one direction: The outbound side runs the initiator side of mini-protocols, and the inbound side runs responders; in `Duplex` mode, both the inbound and outbound side runs the initiator and responder side of each mini-protocol. Negotiation of `DataFlow` is done by the handshake protocol; the final result depends on two factors: the negotiated version and `InitiatorOnly` flag, which is announced through a handshake. Each connection can be in one of the following states:

    data ConnectionState
      -- The connection manager is about to connect with a peer.
      = ReservedOutboundState

      -- Connected to a peer, handshake negotiation is ongoing.
      | UnnegotiatedState Provenance

      -- Outbound connection, inbound idle timeout is ticking.
      | OutboundState*'$^\tau$'* DataFlow

      -- Outbound connection, inbound idle timeout expired.
      | OutboundState DataFlow

      -- Inbound connection, but not yet used.
      | InboundIdleState*'$^\tau$'* DataFlow

      -- Active inbound connection.
      | InboundState DataFlow

      -- Connection runs in duplex mode: either outbound connection negotiated
      -- 'Duplex' data flow, or 'InboundState Duplex' was reused.
      | DuplexState

      -- Connection manager is about to close (reset) the connection, before it
      -- will do that it will put the connection in 'OutboundIdleState' and start
      -- a timeout.
      | OutboundIdleState*'$^\tau$'*

      -- Connection has terminated; socket is closed, thread running the
      -- the connection is killed.  For some delay (`TIME_WAIT`) the connection is kept
      -- in this state until the kernel releases all the resources.
      | TerminatingState

      -- Connection is forgotten.
      | TerminatedState

The above type is a simplified version of what is implemented. The real implementation tracks more detail, e.g. connection id (the quadruple of IP addresses and ports), multiplexer handle, thread id, etc., which we do not need to take care of in this specification. The rule of thumb is that all states that have some kind of timeout should be annotated with a $\tau$. In these cases, we are waiting for any message that would indicate a *warm* or *hot* transition. If that does not happen within a timeout, we will close the connection.

In this specification, we represent `OutboundState`^$\tau$^` Unidirectional`, which is not used, the implementation avoids this constructor, for the same reasons that were given above, regarding `InitiatorMode`.

:::: {#fig:statediagram .figure latex-placement="p"}
::: caption
*Outbound* (blue & violet) and *inbound* (green & violet) connection states and allowed transitions.
:::
::::

Figure [1.3](#fig:statediagram){reference-type="ref" reference="fig:statediagram"} shows all the transitions between `ConnectionState`s. Blue and Violet states represent states of an *Outbound* connection, and Green and Violet states represent states of an *Inbound* connection. Dashed arrows indicate asynchronous transitions that are triggered, either by a remote node or by the connection manager itself.

Note that the vertical symmetry in the graph corresponds to the local vs remote state of the connection, see table [1.1](#table:symmetry){reference-type="ref" reference="table:symmetry"}. The symmetry is only broken by `InboundIdleState`^$\tau$^` dataFlow`, which does not have a corresponding local equivalent. This is simply because, locally, we immediately know when we will start initiator protocols, and the implementation is supposed to do that promptly. This, however, cannot be assumed to be the case on the inbound side.

::: {#table:symmetry}
  *local connection state*                 *remote connection state*
  ---------------------------------------- ---------------------------------------
                                           
  `UnnegotiatedState Outbound`             `UnnegotiatedState Inbound`
  `OutboundIdleState`^$\tau$^` dataFlow`   `InboundIdleState`^$\tau$^` dataFlow`
  `OutboundState dataFlow`                 `InboundState dataFlow`
  `OutboundState`^$\tau$^` dataFlow`       `InboundState dataFlow`
  `InboundState dataFlow`                  `OutboundState dataFlow`
  `DuplexState`                            `DuplexState`

  : Symmetry between local and remote states
:::

Another symmetry that we tried to preserve is between `Unidirectional` and `Duplex` connections. The `Duplex` side is considerably more complex as it includes interaction between `Inbound` and `Outbound` connections (in the sense that inbound connections can migrate to outbound only and vice versa). However, the state machine for an inbound-only connection is the same whether it is `Duplex` or `Unidirectional`, see Figure [1.4](#fig:statediagram-inbound-only){reference-type="ref" reference="fig:statediagram-inbound-only"}. A *connection manager* running in `ResponderMode` will use this state machine.

For *node-to-client* server, it will be even simpler, as there we only allow for unidirectional connections. Nevertheless, this symmetry simplifies the implementation.

:::: {#fig:statediagram-inbound-only .figure latex-placement="p"}
::: caption
Sub-graph of inbound states.
:::
::::

### Transitions

#### [Reserve]{.sans-serif}

When *connection manager* is asked for an outbound connection, it reserves a slot in its state for that connection. If any other thread asks for the same outbound connection, the *connection manager* will raise an exception in that thread. Reservation is done to guarantee exclusiveness for state transitions to a single outbound thread.

#### [Connected]{.sans-serif}

This transition is executed once an outbound connection successfully performs the `connect` system call.

#### [Accepted]{.sans-serif} and [Overwritten]{.sans-serif}

Transition driven by the `accept` system call. Once it returns, the *connection manager* might either not know about such connection or, there might be one in `ReservedOutboundState`. The [Accepted]{.sans-serif} transition represents the former situation, while the [Overwritten]{.sans-serif} transition captures the latter.

Let us note that if [Overwritten]{.sans-serif} transition happened, then on the outbound side, the scheduled `connect` call will fail. In this case, the *p2p governor* will recover, putting the peer in a queue of failed peers and will either try to connect to another peer or reconnect to that peer after some time, in which case it would re-use the accepted connection (assuming that a duplex connection was negotiated).

#### [Negotiated]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Outbound]{.sans-serif}~ and [Negotiated]{.sans-serif}^[Duplex]{.sans-serif}^~[Outbound]{.sans-serif}~

Once an outbound connection has been negotiated, one of [Negotiated]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Outbound]{.sans-serif}~ or [Negotiated]{.sans-serif}^[Duplex]{.sans-serif}^~[Outbound]{.sans-serif}~ transition is performed, depending on the result of a handshake negotiation. Duplex connections are negotiated only for node-to-node protocol versions higher than `NodeToNodeV_7`, and neither side declared that it is an *initiator* only.

If a duplex outbound connection was negotiated, the *connection manager* needs to ask the *inbound protocol governor* to start and monitor responder mini-protocols on the outbound connection.

::: detail
This transition is done by the `requestOutboundConnection`.
:::

#### [Negotiated]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Inbound]{.sans-serif}~ and [Negotiated]{.sans-serif}^[Duplex]{.sans-serif}^~[Inbound]{.sans-serif}~

This transition is performed once the handshake negotiated an unidirectional or duplex connection on an inbound connection.

For [Negotiated]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Inbound]{.sans-serif}~, [Negotiated]{.sans-serif}^[Duplex]{.sans-serif}^~[Inbound]{.sans-serif}~, [Negotiated]{.sans-serif}^[Duplex]{.sans-serif}^~[Outbound]{.sans-serif}~ transitions, the *inbound protocol governor* will restart all responder mini-protocols (for all *established*, *warm* and *hot* groups of mini-protocols) and keep monitoring them.

::: detail
This transition is done by the `includeInboundConnection`.
:::

::: detail
Whenever a mini-protocol terminates, it is immediately restarted using an on-demand strategy. All *node-to-node* protocols have initial agency on the client side; hence, restarting them on-demand does not send any message.
:::

#### [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~, [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ and [Awake]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~

All the awake transitions start either at `InboundIdleState`^$\tau$^` dataFlow`, the [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ can also be triggered on `OutboundIdleState`^$\tau$^` Duplex`.

::: detail
[Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~ transition is done by `requestOutboundConnection` on the request of *p2p governor*, while [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ and [Awake]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~ are triggered by incoming traffic on any of the responder mini-protocols (asynchronously if detected any *warm*/*hot* transition).
:::

#### [Commit]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~, [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ {#sec:tr_commit}

Both commit transitions happen after *protocol idle timeout* of inactivity (as the [TimeoutExpired]{.sans-serif} transition does). They transition to `TerminatingState`^$\tau$^ (closing the bearer). For duplex connections, a normal shutdown procedure goes through `InboundIdleState`^$\tau$^` Duplex` via [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ - which gave the name to this transition.

The inactivity of responder mini-protocols triggers these transitions. They both protect against a client that connects but never sends any data through the bearer; also, as part of a termination sequence, it is protecting us from shutting down a connection which is transitioning between *warm* and *hot* states.

Both commit transitions:

- [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~

- [Commit]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~

need to detect idleness during a time interval (which we call: ). If, during this time frame, inbound traffic on any responder mini-protocol is detected, one of the [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ or [Awake]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~ transition is performed. The idleness detection might also be interrupted by the local [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~ transition.

::: detail
These transitions can be triggered by `unregisterInboundConnection` and `unregisterOutboundConnection` (both are non-blocking), but the stateful idleness detection during *protocol idle timeout* is implemented by the server.

The implementation relies on two properties:

- the multiplexer being able to start mini-protocols on-demand, which allows us to restart a mini-protocol as soon as it returns without disturbing idleness detection;

- the initial agency for any mini-protocol is on the client.
:::

::: detail
Whenever an outbound connection is requested, we notify the server about a new connection. We also do that when the connection manager hands over an existing connection. If *inbound protocol governor* is already tracking that connection, we need to make sure that

- *inbound protocol governor* preserves its internal state of that connection;

- *inbound protocol governor* does not start mini-protocols, as they are already running (we restart responders as soon as they stop, using the on-demand strategy).
:::

#### [DemotedToCold]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Local]{.sans-serif}~, [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~

This transition is driven by the *p2p governor* when it decides to demote the peer to *cold* state; its domain is `OutboundState dataFlow` or `OutboundState`^$\tau$^` Duplex`. The target state is `OutboundIdleState`^$\tau$^` dataFlow` in which the connection manager sets up a timeout. When the timeout expires, the connection manager will do [Commit]{.sans-serif}^[dataFlow]{.sans-serif}^~[Local]{.sans-serif}~ transition, which will reset the connection.

::: detail
This transition is done by `unregisterOutboundConnection`.
:::

#### [DemotedToCold]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~, [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~

Both transitions are edge-triggered, the connection manager is notified by the *inbound protocol governor* once it notices that all responders became idle. Detection of idleness during *protocol idle timeout* is done in a separate step which is triggered immediately, see section [1.8.4.14](#sec:tr_commit_rem){reference-type="ref" reference="sec:tr_commit_rem"} for details.

::: detail
Both transitions are done by `demotedToColdRemote`.
:::

#### [PromotedToWarm]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~

This transition is driven by the local *p2p governor* when it promotes a *cold* peer to *warm* state. *connection manager* will provide a handle to an existing connection, so that *p2p governor* can drive its state.

::: detail
This transition is done by `requestOutboundConnection`.
:::

#### [TimeoutExpired]{.sans-serif}

This transition is triggered when the protocol idleness timeout expires while the connection is in `OutboundState`^$\tau$^` Duplex`. The server starts this timeout when it triggers [DemotedToCold]{.sans-serif}^[dataFlow]{.sans-serif}^~[Remote]{.sans-serif}~ transition. The connection manager tracks the state of this timeout so we can decide if a connection in the outbound state can terminate or if it needs to wait for that timeout to expire.

::: detail
This transition is done by `unregisterInboundConnection`.
:::

#### [PromotedToWarm]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~

The remote peer triggers this asynchronous transition. The *inbound protocol governor* can notice it by observing the multiplexer ingress side of running mini-protocols. It then should notify the *connection manager*.

::: detail
This transition is done by `promotedToWarmRemote`.

The implementation relies on two properties:

- all initial states of node-to-node mini-protocols have client agency, i.e. the the server expects an initial message;

- all mini-protocols are started using an on-demand strategy, which allows to detect when a mini-protocol is brought to life by the multiplexer.
:::

#### [Prune]{.sans-serif} transitions

First, let us note that a connection in `InboundState Duplex` could have been initiated by either side (Outbound or Inbound). This means that even though a node might not have accepted any connection, it could end up serving peers and possibly go beyond server hard limit, thus exceeding the number of allowed file descriptors. This is possible via the following path:

- [Connected]{.sans-serif},

- [Negotiated]{.sans-serif}^[Duplex]{.sans-serif}^~[Outbound]{.sans-serif}~,

- [PromotedToWarm]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~,

- [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~

which leads from the initial state • to `InboundState Duplex`, the same state in which accepted duplex connections end up. Even though the server rate limits connections based on how many connections are in this state, we could exceed the server hard limit.

These are all transitions that potentially could lead to exceeding the server hard limit, all of them are transitions from some outbound/duplex state into an inbound/duplex state:

- `DuplexState` to `InboundState Duplex` (via [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~)

- `OutboundState`^$\tau$^` Duplex` to `InboundState Duplex` (via [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~)

- `OutboundIdleState`^$\tau$^` Duplex` to `InboundState Duplex` (via [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~)

- `OutboundState`^$\tau$^` Duplex` to `DuplexState` (via [PromotedToWarm]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~)

- `OutboundState Duplex` to `DuplexState` (via [PromotedToWarm]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~)

To solve this problem, the connection manager will check to see if the server hard limit was exceeded in any of the above transitions. If that happens, the *connection manager* will reset an arbitrary connection (with some preference).

The reason why going from `OutboundState`^$\tau$^` Duplex` (or `OutboundState Duplex`, or `OutboundIdleState`^$\tau$^` Duplex`) to `InboundState Duplex` might exceed the server hard limit is exacty the same as the `DuplexState` to `InboundState Duplex` one. However, the reason why going from `OutboundState`^$\tau$^` Duplex` to `DuplexState` might exceed the limit is more tricky. To reach a `DuplexState`, one assumes there must have been an incoming *accepted* connection. However, there's another way that two end-points can establish a connection without a node accepting it. If two nodes try to request an outbound connection simultaneously, it is possible for two applications to both perform an active opening to each other at the same time. This is called a [*simultaneous open*](https://flylib.com/books/en/3.223.1.190/1/). In a simultaneous TCP open, we can have $2$ nodes establishing a connection without any of them having explicitly accepted a connection, which can make a server violate its file descriptor limit.

Given this, we prefer to reset an inbound connection rather than close an outbound connection because, from a systemic point of view, outbound connections are more valuable than inbound ones. If we keep the number of *established* peers to be smaller than the server hard limit; with the right policy, we should never need to reset a connection in `DuplexState`. However, when dealing with a connection that transitions from `OutboundState`^$\tau$^` Duplex` to `DuplexState`, we actually need to make sure this connection is closed, because we have no way to know for sure if this connection is the result of a TCP simultaneous open there might not be any other connection available to prune that can make space for this one.

The *inbound protocol governor* is in a position to make an educated decision about which connection to reset. Initially, we aim for a decision driven by randomness, but other choices are possible[^2] and the implementation should allow to easily extend the initial choice.

#### [Commit]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~, [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ {#sec:tr_commit_rem}

Both commit transitions happen after *protocol idle timeout* of inactivity (as the [TimeoutExpired]{.sans-serif} transition does). They transition to `TerminatingState`^$\tau$^ (closing the bearer). For duplex connections, a normal shutdown procedure goes through `InboundIdleState`^$\tau$^` Duplex` via [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ - which gave the name to this transition, or through `OutboundIdleState`^$\tau$^` Duplex` via [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~ transition.

These transitions are triggered by the inactivity of responder mini-protocols. They both protect against a client that connects but never sends any data through the bearer; also, as part of a termination sequence, it is protecting us from shutting down a connection which is transitioning between *warm* and *hot* states.

Both commit transitions:

- [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~

- [Commit]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~

Need to detect idleness during time interval (which we call: ). If during this time frame, inbound traffic on any responder mini-protocol is detected, one of the [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ or [Awake]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~ transition is performed. The local [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~ transition might also interrupt the idleness detection.

::: detail
These transitions can be triggered by `unregisterInboundConnection` and `unregisterOutboundConnection` (both are non-blocking), but the stateful idleness detection during *protocol idle timeout* is implemented by the *inbound protocol governor*. The implementation relies on two properties:

- the multiplexer being able to start mini-protocols on-demand, which allows us to restart a mini-protocol as soon as it returns without disturbing idleness detection;

- the initial agency for any mini-protocol is on the client.
:::

::: detail
Whenever an outbound connection is requested, we notify the server about a new connection. We also do that when the connection manager hands over an existing connection. If *inbound protocol governor* is already tracking that connection, we need to make sure that

- *inbound protocol governor* preserves its internal state of that connection;

- *inbound protocol governor* does not start mini-protocols, as they are already running (we restart responders as soon as they stop, using the on-demand strategy).
:::

#### [Commit]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Local]{.sans-serif}~, [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~ {#sec:tr_commit_loc}

As previous two transitions, these also are triggered after *protocol idle timeout*, but this time, they are triggered on the outbound side. This transition will reset the connection, and the timeout ensures that the remote end can clear its ingress queue before the [TCP]{.sans-serif} reset arrives. For a more detailed analysis, see [1.8.6](#sec:connection-close){reference-type="ref" reference="sec:connection-close"} section.

#### [Terminate]{.sans-serif}

After a connection is closed, we keep it in `TerminatingState`^$\tau$^ for the duration of *wait time timeout*. When the timeout expires, the connection is forgotten.

#### Connecting to oneself

The transitions described in this section can only happen when the connection the manager was requested to connect to its own listening socket and the address wasn't translated by the [OS]{.sans-serif} or a [NAT]{.sans-serif}. This could happen only in particular situations:

1.  misconfiguration a system;

2.  running a node on multiple interfaces;

3.  in some cases, it could also happen when learning about oneself from the ledger;

4.  or due to peer sharing.

In some of these cases, the external IP address would need to agree with the internal one, which is true for some cloud service providers.

Let us note that these connections effectively only add delay, and thus they will be replaced by the outbound governor (by its churn mechanism).

These transitions are not indicated in the figure [1.3](#fig:statediagram){reference-type="ref" reference="fig:statediagram"}, instead they are shown bellow in figure [1.5](#fig:statediagram-selfconn){reference-type="ref" reference="fig:statediagram-selfconn"}.

##### [SelfConn]{.sans-serif} and [SelfConn$^{-1}$]{.sans-serif}

We allow transitioning between

- `UnnegotiatedState Outbound` and

- `UnnegotiatedState Inbound`

or the other way. This transition is not guaranteed as on some systems in such case, the outbound and inbound addresses (as returned by the `accept` call) can be different. Whether [SelfConn]{.sans-serif} or [SelfConn$^{-1}$]{.sans-serif} will happen depending on the race between the inbound and outbound sides.

##### [SelfConn']{.sans-serif} and [SelfConn'$^{-1}$]{.sans-serif}

We also allow transitioning between

- `InboundIdleState`^$\tau$^` dataFlow` and

- `OutboundState dataFlow`

After the handshake is negotiated, there is a race between inbound and outbound threads, which need to be resolved consistently.

:::: {#fig:statediagram-selfconn .figure latex-placement="p"}
::: caption
Extra transitions when connecting to onself
:::
::::

### Protocol errors

If a mini-protocol errors, on either side, the connection will be reset and put in `TerminatedState`. This can happen in any connection state.

### Closing connection {#sec:connection-close}

By default, when the operating system is closing a socket, it is done in the background, but when `SO_LINGER` option is set, the `close` system call blocks until either all messages are sent or the specified linger timeout fires. Unfortunately, our experiments showed that if the remote side (not the one that called `close`), delays reading the packets, then even with `SO_LINGER` option set, the socket is kept in the background by the OS. On `FreeBSD` it is eventually closed cleanly, on `Linux` and `OSX` it is reset. This behaviour gives the remote end the power to keep resources for an extended amount of time, which we want to avoid. We thus decided to always use `SO_LINGER` option with timeout set to `0`, which always resets the connection (i.e. it sets the `RST` [TCP]{.sans-serif} flag). This has the following consequences:

- Four-way handshake used by [TCP]{.sans-serif} termination will not be used. The four-way handshake allows one to close each side of the connection separately. With the reset, the OS is instructed to forget the state of the connection immediately (including freeing unread ingress buffer).

- the system will not keep the socket in `TIME_WAIT` state, which was designed to:

  - provide enough time for final `ACK` to be received;

  - protect the connection from packets that arrive late. Such packets could interfere with a new connection (see [@stevens2003unix]).

The connection state machine makes sure that we close a connection only when both sides are not using the connection for some time: for outbound connections this is configured by the timeout on the `OutboundIdleState`^$\tau$^` dataFlow`, while for inbound connections by the timeout on the `InboundIdleState`^$\tau$^` dataFlow`. This ensures that the application can read from ingress buffers before the `RST` packet arrives. Excluding protocol errors and prune transitions, which uncooperatively reset the connection.

We also provide application-level `TIME_WAIT` state: `TerminatingState`^$\tau$^, in which we keep a connection, which should also protect us from late packets from a previous connection. However, the connection manager does allow to accept new connections during `TerminatingState`^$\tau$^ - it is the client's responsibility not to reconnect too early. For example, *p2p governor* enforces a 60s idle period before it can reconnect to the same peer, after either a protocol error or a connection failure.

From an operational point of view, it's essential that connections are not held in `TIME_WAIT` state for too long. This would be problematic when restarting a node (without rebooting the system) (e.g. when adjusting configuration). Since we reset connections, this is not a concern.

### *Outbound* connection

If the connection state is in either `ReservedOutboundState`, `UnnegotiatedState Inbound` or `InboundState Duplex` then, when calling `requestOutboundConnection` the state of a connection leads to either `OutboundState Unidirectional` or `DuplexState`.

If `Unidirectional` connection was negotiated, `requestOutboundConnection` must error. If `Duplex` connection was negotiated, it can use the egress side of this connection leading to `DuplexState`.

##### [initial state (•)]{.nodecor}:

the *connection manager* does not have a connection with that peer. The connection is put in `ReservedOutboundState` before *connection manager* connects to that peer;

##### `UnnegotiatedState Inbound`:

if the *connection manager* accepted a connection from that peer, handshake is ongoing; `requestOutboundConnection` will await until the connection state changes to `InboundState dataFlow`.

##### `InboundState Unidirectional`:

if `requestOutboundConnection` finds a connection in this state it will error.

##### `InboundState Duplex`:

if *connection manager* accepted connection from that peer and handshake negotiated a `Duplex` data flow; `requestOutboundConnection` transitions to `DuplexState`.

##### `TerminatingState`^$\tau$^:

block until `TerminatedState` and start from the initial state.

##### [Otherwise]{.nodecor}:

if *connection manager* is asked to connect to peer, and there exists a connection in any other state, e.g. `UnnegotiatedState Outbound`, `OutboundState dataFlow`, `DuplexState`, *connection manager* signals the caller with an error, see section [1.2](#table:requestOutboundConnection){reference-type="ref" reference="table:requestOutboundConnection"}.

Figure [1.6](#fig:outbound_flow){reference-type="ref" reference="fig:outbound_flow"} shows outbound connection state evolution, e.g. the flow graph of `requestOutboundConnection`.

:::: {#fig:outbound_flow .figure latex-placement="p"}
::: caption
*Outbound* connection flow graph
:::
::::

#### `OutboundState Duplex` and `DuplexState`

Once an outbound connection negotiates `Duplex` data flow, it transfers to `OutboundState Duplex`. At this point, we need to start responder protocols. This means that the *connection manager* needs a way to inform the server (which accepts and monitors inbound connections) to start the protocols and monitor that connection. This connection will transition to `DuplexState` only once we notice incoming traffic on any of *established* protocols. Since this connection might have been established via TCP simultaneous open, this transition to `DuplexState` can also trigger [Prune]{.sans-serif} transitions if the number of inbound connections becomes above the limit.

::: detail
The implementation is using a `TBQueue`. The server uses this channel for incoming duplex outbound and inbound connections.
:::

#### Termination {#sec:outbound_termination}

When *p2p governor* demotes a peer to *cold* state, an outbound the connection needs to transition from either:

- `OutboundState dataFlow` to `OutboundIdleState`^$\tau$^` dataFlow`

- `OutboundState`^$\tau$^` Duplex` to `InboundIdleState`^$\tau$^` Duplex`

- `DuplexState` to `InboundState Duplex`

To support that the *connection manager* exposes a method:

    unregisterOutboundConnection *'$\coloncolon$'* peerAddr *'$\rightarrow$'* m ()

This method performs [DemotedToCold]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Local]{.sans-serif}~ or [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~ transition. In the former case, it will shut down the multiplexer and close the [TCP]{.sans-serif} connection; in the latter case, besides changing the connection state, it will also trigger [Prune]{.sans-serif} transitions if the number of inbound connections is above the limit.

#### Connection manager methods

The tables [1.2](#table:requestOutboundConnection){reference-type="ref" reference="table:requestOutboundConnection"} and [1.3](#table:unregisterOutboundConnection){reference-type="ref" reference="table:unregisterOutboundConnection"} show transitions performed by

- `requestOutboundConnection` and

- `unregisterOutboundConnection`

respectively.

::: {#table:requestOutboundConnection}
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| *State*                                     | *Action*                                                                                                                                                         |
+:============================================+:=================================================================================================================================================================+
|                                             |                                                                                                                                                                  |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| •                                           | ::: minipage                                                                                                                                                     |
|                                             | - `ReservedOutboundState`,                                                                                                                                       |
|                                             |                                                                                                                                                                  |
|                                             | - [Connected]{.sans-serif},                                                                                                                                      |
|                                             |                                                                                                                                                                  |
|                                             | - start connection thread (handshake, *mux*)                                                                                                                     |
|                                             |                                                                                                                                                                  |
|                                             | - [Negotiated]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Outbound]{.sans-serif}~ or [Negotiated]{.sans-serif}^[Duplex]{.sans-serif}^~[Outbound]{.sans-serif}~ |
|                                             | :::                                                                                                                                                              |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `ReservedOutboundState`                     | error `ConnectionExists`                                                                                                                                         |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `UnnegotiatedState Outbound`                | error `ConnectionExists`                                                                                                                                         |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `UnnegotiatedState Inbound`                 | ::: minipage                                                                                                                                                     |
|                                             | await for `InboundState dataFlow`, if negotiated duplex connection transition to `DuplexState`, otherwise error `ForbiddenConnection`                            |
|                                             | :::                                                                                                                                                              |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `OutboundState dataFlow`                    | error `ConnectionExists`                                                                                                                                         |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `OutboundState`^$\tau$^` Duplex`            | error `ConnectionExists`                                                                                                                                         |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `OutboundIdleState`^$\tau$^` dataFlow`      | error `ForbiddenOperation`                                                                                                                                       |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `InboundIdleState`^$\tau$^` Unidirectional` | error `ForbiddenConnection`                                                                                                                                      |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `InboundIdleState`^$\tau$^` Duplex`         | transition to `OutboundState Duplex`                                                                                                                             |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `InboundState Unidirectional`               | error `ForbiddenConnection`                                                                                                                                      |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `InboundState Duplex`                       | transition to `DuplexState`                                                                                                                                      |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `DuplexState`                               | error `ConnectionExists`                                                                                                                                         |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `TerminatingState`^$\tau$^                  | await for `TerminatedState`                                                                                                                                      |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| `TerminatedState`                           | can be treated as initial state                                                                                                                                  |
+---------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+

: `requestOutboundConnection`; states indicated with a ^$\dagger$^ are forbidden by [TCP]{.sans-serif}.
:::

::: {#table:unregisterOutboundConnection}
  *State*                                       *Action*
  --------------------------------------------- ---------------------------------------------------------------------------------------------------
                                                
  •                                             `no-op`
  `ReservedOutboundState`                       error `ForbiddenOperation`
  `UnnegotiatedState Outbound`                  error `ForbiddenOperation`
  `UnnegotiatedState Inbound`                   error `ForbiddenOperation`
  `OutboundState dataFlow`                      [DemotedToCold]{.sans-serif}^[dataFlow]{.sans-serif}^~[Local]{.sans-serif}~
  `OutboundState`^$\tau$^` Duplex`              [Prune]{.sans-serif} or [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~
  `OutboundIdleState`^$\tau$^` dataFlow`        `no-op`
  `InboundIdleState`^$\tau$^` Unidirectional`   assertion error
  `InboundIdleState`^$\tau$^` Duplex`           `no-op`
  `InboundState Unidirectional`                 assertion error
  `InboundState Duplex`                         `no-op`
  `DuplexState`                                 [Prune]{.sans-serif} or [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Local]{.sans-serif}~
  `TerminatingState`^$\tau$^                    `no-op`
  `TerminatedState`                             `no-op`

  : `unregisterOutboundConnection`
:::

The choice between `no-op` and error is solved by the following rule: if the calling component (e.g. *p2p governor*), can keep its state in a consistent state with *connection manager* then use `no-op`, otherwise error. Since both *inbound protocol governor* and *p2p governor* are using *mux* to track the state of the connection, the state can't be inconsistent.

### *Inbound* connection

Initial states for inbound connection are either:

- initial state •;

- `ReservedOutboundState`: this can happen when `requestOutboundConnection` reserves a connection with `ReservedOutboundState`, but before it calls `connect` the `accept` call returned. In this case, the `connect` call will fail and, as a consequence, `requestOutboundConnection` will fail too. Any mutable variables used by it can be disposed since no thread can be blocked on it: if another thread asked for an outbound connection with that peer, it would see `ReservedOutboundState` and throw `ConnectionExists` exception.

  To make sure that this case is uncommon, we need to guarantee that the *connection manager* does not block between putting the connection in the `ReservedOutboundState` and calling the `connect` system call.

:::: {.figure latex-placement="h"}
::: caption
*Inbound* connection flow graph, where both bordered states: `ReservedOutboundState` and `UnnegotiatedState Inbound` are initial states.
:::
::::

#### Connection manager methods

The following tables show transitions of the following connection manager methods:

- `includeInboundConnection`: table [1.4](#table:includeInboundConnection){reference-type="ref" reference="table:includeInboundConnection"}

- `promotedToWarmRemote`: table [1.5](#table:promotedToWarmRemote){reference-type="ref" reference="table:promotedToWarmRemote"}

- `demotedToColdRemote`: table [1.6](#table:demotedToColdRemote){reference-type="ref" reference="table:demotedToColdRemote"}

- `unregisterInboundConnection`: table [1.7](#table:unregisterInboundConnection){reference-type="ref" reference="table:unregisterInboundConnection"}

States indicated by '-' are preserved, though unexpected; `promotedToWarmRemote` will use `UnsupportedState :: OperationResult a` to indicate that to the caller.

::: {#table:includeInboundConnection}
+---------------------------------------+--------------------------------------------------------+
| *State*                               | *Action*                                               |
+:======================================+:=======================================================+
|                                       |                                                        |
+---------------------------------------+--------------------------------------------------------+
| •                                     | ::: minipage                                           |
|                                       | - start connection thread (handshake, *mux*)           |
|                                       |                                                        |
|                                       | - transition to `UnnegotiatedState Inbound`.           |
|                                       |                                                        |
|                                       | - await for handshake result                           |
|                                       |                                                        |
|                                       | - transition to `InboundIdleState`^$\tau$^` dataFlow`. |
|                                       | :::                                                    |
+---------------------------------------+--------------------------------------------------------+
| `ReservedOutboundState`               | the same as •                                          |
+---------------------------------------+--------------------------------------------------------+
| `UnnegotiatedState prov`              | `impossible state`^$\dagger$^                          |
+---------------------------------------+--------------------------------------------------------+
| `InboundIdleState`^$\tau$^` dataFlow` | `impossible state`^$\dagger$^                          |
+---------------------------------------+--------------------------------------------------------+
| `InboundState dataFlow`               | `impossible state`^$\dagger$^                          |
+---------------------------------------+--------------------------------------------------------+
| `OutboundState dataFlow`              | `impossible state`^$\dagger$^                          |
+---------------------------------------+--------------------------------------------------------+
| `DuplexState`                         | `impossible state`^$\dagger$^                          |
+---------------------------------------+--------------------------------------------------------+
| `TerminatingState`^$\tau$^            | the same as •                                          |
+---------------------------------------+--------------------------------------------------------+
| `TerminatedState`                     | the same as •                                          |
+---------------------------------------+--------------------------------------------------------+

: `includeInboundConnection`
:::

States indicated with a ^$\dagger$^ are forbidden by [TCP]{.sans-serif}.

::: {#table:promotedToWarmRemote}
  *StateIn*                                     *StateOut*                               *Transition*                                                                   
  --------------------------------------------- ---------------------------------------- ------------------------------------------------------------------------------ --
                                                                                                                                                                        
  •                                             \-                                                                                                                      
  `ReservedOutboundState`                       \-                                                                                                                      
  `UnnegotiatedState prov`                      \-                                                                                                                      
  `OutboundState Unidirectional`                \-                                                                                                                      
  `OutboundState Duplex`                        [Prune]{.sans-serif} or (`DuplexState`   [PromotedToWarm]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~)   
  `InboundIdleState`^$\tau$^` Unidirectional`   `InboundState Unidirectional`            [Awake]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~     
  `InboundIdleState`^$\tau$^` Duplex`           `InboundState Duplex`                    [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~             
  `InboundState Unidirectional`                 \-                                                                                                                      
  `InboundState Duplex`                         \-                                                                                                                      
  `DuplexState`                                 \-                                                                                                                      
  `TerminatingState`^$\tau$^                    \-                                                                                                                      
  `TerminatedState`                             \-                                                                                                                      

  : `promotedToWarmRemote`
:::

::: {#table:demotedToColdRemote}
  *StateIn*                               *StateOut*                              *Transition*
  --------------------------------------- --------------------------------------- ------------------------------------------------------------------------------
                                                                                  
  `ReservedOutboundState`                 \-                                      \-
  `UnnegotiatedState prov`                \-                                      \-
  `OutboundState dataFlow`                \-                                      \-
  `InboundIdleState`^$\tau$^` dataFlow`   \-                                      \-
  `InboundState dataFlow`                 `InboundIdleState`^$\tau$^` dataFlow`   [DemotedToCold]{.sans-serif}^[dataFlow]{.sans-serif}^~[Remote]{.sans-serif}~
  `DuplexState`                           `OutboundState`^$\tau$^` Duplex`        [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~
  `TerminatingState`^$\tau$^              \-                                      \-
  `TerminatedState`                       \-                                      \-

  : `demotedToColdRemote`
:::

::: {#table:unregisterInboundConnection}
  *StateIn*                                  *StateOut*                            *Returned Value*   *Transition(s)*
  ------------------------------------------ ------------------------------------- ------------------ ------------------------------------------------------------------------------
                                                                                                      
  •                                          \-                                    \-                 
  `ReservedOutboundState`                    \-                                    \-                 
  `UnnegotiatedState prov`                   \-                                    \-                 
  `OutboundState`^$\tau$^` Unidirectional`   $\dagger$                             \-                 
  `OutboundState Unidirectional`             $\dagger$                             \-                 
  `OutboundState`^$\tau$^` Duplex`           `OutboundState Duplex`                \-                 
  `OutboundState Duplex`                     $\dagger$                             \-                 
  `InboundIdleState`^$\tau$^` dataFlow`      `TerminatingState`^$\tau$^            `True`             
  `InboundState dataFlow`                    `TerminatingState`^$\tau$$\dagger$^   `True`             [DemotedToCold]{.sans-serif}^[dataFlow]{.sans-serif}^~[Remote]{.sans-serif}~
                                                                                                      [Commit]{.sans-serif}^[dataFlow]{.sans-serif}^~[Remote]{.sans-serif}~
  `DuplexState`                              `OutboundState Duplex`                `False`            [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~
  `TerminatingState`^$\tau$^                 \-                                    \-                 
  `TerminatedState`                          \-                                    \-                 

  : `unregisterInboundConnection`
:::

Transitions denoted by ^$\dagger$^ should not happen. The implementation is using assertion, and the production system will trust that the server side calls `unregisterInboundConnection` only after all responder mini-protocols where idle for *protocol idle timeout*.

`unregisterInboundConnection` might be called when the connection is in `OutboundState Duplex`. This can, though very rarely, happen as a race between [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ and [DemotedToCold]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~[^3]. Let's consider the following sequence of transitions:

::: center
:::

If the *protocol idle timeout* on the `InboundIdleState`^$\tau$^` Duplex` expires the [Awake]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ transition is triggered and the *inbound protocol governor* calls `unregisterInboundConnection`.

:::: {#fig:methods .figure latex-placement="p"}
::: caption
Transitions classified by connection manager method.
:::
::::

## Server

The server consists of an accept loop and an *inbound protocol governor*. The accept loop is using `includeInboundConnnection` on incoming connections, while the *inbound protocol governor* tracks the state of the responder side of all mini-protocols and it is responsible for starting and restarting mini-protocols, as well as detecting if they are used to support:

- [PromotedToWarm]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~,

- [DemotedToCold]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~,

- [Commit]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~ and [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ transitions.

The *inbound protocol governor* will always start/restart all the mini-protocols using `StartOnDemand` strategy. When the multiplexer detects any traffic on its ingress queues, corresponding to responder protocols, it will do the [PromotedToWarm]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ transition using `promotedToWarmRemote` method.

Once all responder mini-protocols become idle, i.e. they all stopped, were restarted (on-demand) but are not yet running, a [DemotedToCold]{.sans-serif}^[dataFlow]{.sans-serif}^~[Remote]{.sans-serif}~ transition is run: the *inbound protocol governor* will notify the *connection manager* using:

    -- | Notify the 'ConnectionManager' that a remote end demoted us to a /cold
    -- peer/.
    --
    -- This executes:
    --
    -- * \(DemotedToCold^{*}_{Remote}\) transition.
    demotedToColdRemote
        :: HasResponder muxMode ~ True
        => ConnectionManager muxMode socket peerAddr handle handleError m
        -> peerAddr -> m (OperationResult InState)

When all responder mini-protocols are idle for *protocol idle timeout*, the *inbound protocol governor* will execute `unregisterInboundConnection` which will trigger:

- [Commit]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~ or [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ if the initial state is `InboundIdleState`^$\tau$^` Duplex`;

- [TimeoutExpired]{.sans-serif} if the initial state is `OutboundState`^$\tau$^` Duplex`;

- `no-op` if the initial state is `OutboundState Duplex` or `OutboundIdleState`^$\tau$^` dataFlow`.

&nbsp;

    -- | Return the value of 'unregisterInboundConnection' to inform the caller about
    -- the transition.
    --
    data DemotedToColdRemoteTr =
        -- | @Commit^{dataFlow}@ transition from @'InboundIdleState' dataFlow@.
        --
        CommitTr

        -- | @DemotedToCold^{Remote}@ transition from @'InboundState' dataFlow@
        --
      | DemotedToColdRemoteTr

        -- | Either @DemotedToCold^{Remote}@ transition from @'DuplexState'@, or
        -- a level triggered @Awake^{Duplex}_{Local}@ transition.  In both cases
        -- the server must keep the responder's side of all protocols ready.
      | KeepTr
      deriving Show

    unregisterInboundConnection *'$\coloncolon$'* peerAddr *'$\Rightarrow$'* m (OperationResult DemotedToColdRemoteTr)

Both [Commit]{.sans-serif}^[Unidirectional]{.sans-serif}^~[Remote]{.sans-serif}~ and [Commit]{.sans-serif}^[Duplex]{.sans-serif}^~[Remote]{.sans-serif}~ will free resources (terminate the connection thread, close the socket).

## Inbound Protocol Governor

*Inbound protocol governor* keeps track of the responder side of the protocol for both inbound and outbound duplex connections. Unidirectional outbound connections are not tracked by *inbound protocol governor*. The server and connection manager are responsible for notifying it about new connections once negotiated. Figure [1.8](#fig:inbgov-state-machine){reference-type="ref" reference="fig:inbgov-state-machine"} presents the state machine that drives changes to connection states tracked by *inbound protocol governor*. As in the connection manager case, there is an implicit transition from every state to the terminating state, representing mux or mini-protocol failures.

::::: {#fig:inbgov-state-machine .figure latex-placement="h!"}
::: center
:::

::: caption
Inbound protocol governor state machine
:::
:::::

### States

States of the inbound governor are similar to the outbound governor, but there are crucial differences.

#### [RemoteCold]{.sans-serif}

The remote cold state signifies that the remote peer is not using the connection, however the only reason why the inbound governor needs to track that connection is because the outbound side of this connection is used. The inbound governor will wait until any of the responder mini-protocols wakes up ([AwakeRemote]{.sans-serif}) or the mux will be shut down ([MuxTerminated]{.sans-serif}).

#### [RemoteIdle]{.sans-serif}^$\tau$^

The [RemoteIdle]{.sans-serif}^$\tau$^ state is the initial state of each new connection ([NewConnection]{.sans-serif}). An active connection will become [RemoteIdle]{.sans-serif}^$\tau$^ once the inbound governor detects that all responder mini-protocols terminated ([WaitIdleRemote]{.sans-serif}). When a connection enters this state, an idle timeout is started. If no activity is detected on the responders, the connection will either be closed by the connection manager and forgotten by the inbound governor or progress to the [RemoteCold]{.sans-serif} state. This depends on whether the connection is used (*warm* or *hot*) or not (*cold*) by the outbound side.

#### [RemoteWarm]{.sans-serif}

A connection dwells in [RemoteWarm]{.sans-serif} if there are strictly only any warm or established responder protocols running. Note also that an established protocol is one that may run in both hot and warm states, but cannot be the only type running to maintain hot state once all proper hot protocols have terminated. In other words, the connection must be demoted in that case.

#### [RemoteHot]{.sans-serif}

A connection enters [RemoteHot]{.sans-serif} state once any hot responder protocol has started. In particular, if a hot responder is the first to start, the state cycles through [RemoteWarm]{.sans-serif} first. Once all hot responders terminate, the connection will be put in [RemoteWarm]{.sans-serif} regardless of whether there are any warm or established responders left. In the latter case, if there aren't any other protocols running, the connection will then follow up with further demotion to [RemoteIdle]{.sans-serif}^$\tau$^.

### Transitions

#### [NewConnection]{.sans-serif}

Inbound and outbound duplex connections are passed to the inbound governor. They are then put in [RemoteIdle]{.sans-serif}^$\tau$^ state.

#### [CommitRemote]{.sans-serif}

Once the [RemoteIdle]{.sans-serif}^$\tau$^ timeout expires, the inbound governor will call `unregisterInboundConnection`. The connection will either be forgotten or kept in [RemoteCold]{.sans-serif} state depending on the returned value.

#### [AwakeRemote]{.sans-serif}

While a connection was put in [RemoteIdle]{.sans-serif}^$\tau$^ state, it is possible that the remote end will start using it. When the inbound governor detects that any of the responders is active, it will put that connection in [RemoteWarm]{.sans-serif} state.

::: detail
The inbound governor calls `promotedToWarmRemote` to notify the connection manager about the state change.
:::

#### [WaitIdleRemote]{.sans-serif}

[WaitIdleRemote]{.sans-serif} transition happens once all mini-protocol is terminated.

::: detail
The inbound governor calls `demotedToColdRemote`. If it returns `TerminatedConnection` the connection will be forgotten (as in [MuxTerminated]{.sans-serif} transition), if it returns `OperationSuccess` it will register a idle timeout.
:::

#### [MiniProtocolTerminated]{.sans-serif}

When any of the mini-protocols terminates, the inbound governor will restart the responder and update the internal state of the connection (e.g. update the stm transaction, which tracks the state of the mini-protocol).

::: detail
The implementation distinguishes two situations: whether the mini-protocol terminated or errored. The multiplexer guarantees that if it errors, the multiplexer will be closed (and thus, the connection thread will exit, and the associated socket will be closed). Hence, the inbound governor can forget about the connection (perform [MuxTerminated]{.sans-serif}).

The inbound governor does not notify the connection manager about a terminating responder mini-protocol.
:::

#### [MuxTerminated]{.sans-serif}

The inbound governor monitors the multiplexer. As soon as it exists, the connection will be forgotten.

The inbound governor does not notify the connection manager about the termination of the connection, as it can detect this by itself.

#### [PromotedToHotRemote]{.sans-serif}

The inbound governor detects when any *hot* mini-protocols have started. In such case a [RemoteWarm]{.sans-serif} connection is put in [RemoteHot]{.sans-serif} state.

#### [DemotedToWarmRemote]{.sans-serif}

Dually to [PromotedToHotRemote]{.sans-serif} state transition, as soon as all of the *hot* mini-protocols terminate, the connection will transition to [RemoteWarm]{.sans-serif} state.

[^1]: Originally transaction submission protocol had agency start with the responder/server side. A later protocol update reversed the initial agency so that they are now all consistent.

[^2]: We can take into account whether we are *hot* to the remote end, or for how long we have been *hot* to to the remote node.

[^3]: race is not the right term, these transitions are concurrent and independent
