# Multiplexing mini-protocols
The role of the multiplexing layer is to take an established underlying point-to-point bearer (e.g. a TCP connection, a UNIX socket or similar) and offer a multiplexed, sequenced-record delivery service for a fixed collection of services (fixed after negotiation).

Carrying all the related services between two peers has several advantages over multiple TCP connections: It reduces overheads (in the kernel and network path), improves congestion window management by minimising network capacity over-allocation during periods of congestion while, at the same time, gaining more dynamic responsiveness to changing end-to-end transport conditions.

Finally, it helps with performance exception detection and mitigation by creating a logical unit-of-failure - if a single component should 'fail' all the associated services on that peer can be failed together.

## The Multiplexing Layer
Multiplexing is used to run several mini-protocols in parallel over a bidirectional bearer (for example, a TCP connection). Figure 1.1 illustrates multiplexing of three mini-protocols over a single duplex bearer. The multiplexer guarantees a fixed pairing of mini-protocol instances, each mini-protocol only communicates with its counter part on the remote end.


<!-- center -->

**Data flow through the multiplexer and demultiplexer**

The multiplexer is agnostic to the bearer it runs over. However, it assumes that the bearer guarantees an ordered and reliable transport layer[^1] and it requires the bearer to be [full-duplex](https://www.wikiwand.com/en/Duplex_(telecommunications)#/Full-duplex) to allow simultaneous reads and writes[^2]. The multiplexer is agnostic to the serialisation used by a mini-protocol (which we specify in section \[chapter:mini-protocols\]). Multiplexer has its own framing / binary serialisation format, described in section 1.1.1. The multiplexer allows the use of each mini-protocol in either direction.

The multiplexer exposes an interface that hides all the multiplexer details, and a single mini-protocol communication can be written as if it would only communicate with its instance on the remote end. When the multiplexer is instructed to send bytes of some mini-protocol, it splits the data into segments, adds a segment header, encodes it and transmits the segments over to the bearer. When reading data from the network, the segment's headers are used to reassemble mini-protocol byte streams.

### Wire Format
<!-- center -->

+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+----------------------+
| 0                    | 1                    | 2                    | 3                    | 4                    | 5                    | 6                    | 7                    | 8                    | 9                    | 0                    | 1                    | 2                    | 3                    | 4                    | 5                    | 6                    | 7                    | 8                    | 9                    | 0                    | 1                    | 2                    | 3                    | 4                    | 5                    | 6                    | 7                    | 8                    | 9                    | 0                    | 1                    |
+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+:====================:+
| Transmission Time                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
+----------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| $M$                  | Mini Protocol ID                                                                                                                                                                                                                                                                                                                                       | Payload-length $n$                                                                                                                                                                                                                                                                                                                                                            |
+----------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
|                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
+---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| Payload of $n$ Bytes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
+---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
|                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
+---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

: Multiplexer's segment data unit (SDU) encoding, see [Network.Mux.Codec](https://ouroboros-network.cardano.intersectmbo.org/network-mux/Network-Mux-Codec).


Table 1.1 shows the layout of the service data unit (SDU) of the multiplexing protocol in big-endian bit order. The segment header contains the following data:

Transmission Time

:   The transmission time is a time stamp based on the lower 32 bits of the sender's monotonic clock with a resolution of one microsecond.

Mini Protocol ID

:   The unique ID of the mini-protocol as in tables \[table:node-to-node-protocol-numbers\] and \[table:node-to-client-protocol-numbers\].

Payload Length

:   The payload length is the size of the segment payload in Bytes. The maximum payload length that is supported by the multiplexing wire format is $2^{16}-1$. Note that an instance of the protocol can choose a smaller limit for the size of segments it transmits.

Mode

:   The single bit $M$ (the mode) is used to distinguish the dual instances of a mini-protocol. The mode is set to $0$ in segments from the initiator, i.e. the side that initially has agency and $1$ in segments from the responder.

### Fairness and Flow-Control in the Multiplexer

The Shelley network protocol requires that the multiplexer uses a fair scheduling of the mini-protocols. Haskell's implementation of the multiplexer uses a round-robin schedule of the mini-protocols to choose the next data segment to transmit. If a mini-protocol does not have new data available when it is scheduled, it is skipped. A mini-protocol can transmit at most one segment of data every time it is scheduled, and it will only be rescheduled immediately if no other mini-protocol is ready to send data.

From the point of view of the mini-protocols, there is a one-message buffer between the egress of the mini-protocol and the ingress of the multiplexer. The mini-protocol will block when it sends a message and the buffer is full.

A concrete implementation of a multiplexer may use a variety of data structures and heuristics to yield the overall best efficiency. For example, although the multiplexing protocol itself is agnostic to the underlying structure of the data, the multiplexer may try to avoid splitting small mini-protocol messages into two segments. The multiplexer may also try to merge multiple messages from one mini-protocol into a single segment. Note that the messages within a segment must all belong to the same mini-protocol.

### Flow-control and Buffering in the Demultiplexer
The demultiplexer eagerly reads data from the bearer. There is a fixed-size buffer between the egress of the demultiplexer and the ingress of the mini-protocols. Each mini-protocol implements its own mechanism for flow control, which guarantees that this buffer never overflows (see Section \[pipelining\].). If the demultiplexer detects an overflow of the buffer, it means that the peer violated the protocol and the MUX/DEMUX layer shuts down the connection to the peer.

For ingress buffer limits for each mini-protocol see \[table:node-to-node-ingress-buffer-limits\].

For Cardano Node, each SDU for the *node-to-node mini-protocol* has the size at most of $12\,288$ bytes. This is not a protocol limit, Cardano Node can handle larger SDUs. In general this is implementation dependent.

Each SDU for the *node-to-client mini-protocol* has the size at most $12\,288$ bytes ($24\,576$ bytes on Windows).

When receiving SDU we place a timeout. For the handshake mini-protocol we use a *10s* timeout, for all other node-to-node and node-to-client mini-protocols a *30s* timeout is used.

## Node-to-node and node-to-client protocol numbers

\
\

Ouroboros network defines two protocols: *node-to-node* and *node-to-client* protocols. *Node-to-node* is used for inter-node communication across the Internet, while *node-to-client* is an inter-process communication used by clients, e.g. a wallet, db-sync, etc. Each of them consists of a bundle of mini-protocols (see chapter \[chapter:mini-protocols\]). The protocol numbers of both protocols are specified in tables \[table:node-to-node-protocol-numbers\] and \[table:node-to-client-protocol-numbers\].

[^1]: Slightly more relaxed property is required: in order delivery of multiplexer segments which belong to the same mini-protocol.

[^2]: Note that one can always pair two unidirectional bearers to form a duplex bearer; we use this to define a duplex bearer out of unix pipes or queues (for intra-process communication only).
