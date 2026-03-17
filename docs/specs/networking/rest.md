## Design Discussion

#### Why distinguish between node to node and node-to-consumer IPC {#why_distinguish_protocols}

We use two different sets of protocols for these two use cases.

node-to-node

:   IPC between nodes that are engaged in the high level Ouroboros blockchain consensus protocol.

node-to-consumer

:   IPC between a Cardano node and a 'chain consumer' component such as a wallet, explorer or other custom application.

This section describes the differences between those two variants of IPC and why they use different protocols.

The node-to-node protocol is conducted in a P2P environment with very limited trust between peers. The node-to-node protocol utilises store-and-forward over selected *bearers* which form the underlying connectivity graph. A concern in this setting is asymmetric resource consumption attacks. Ease of implementation is desirable, but is subordinate to the other hard constraints.

A node-to-consumer protocol is intended to support blockchain applications like wallets and explorers, or Cardano-specific caches or proxies. The setting here is that a consumer trusts a node (a 'chain producer') and just wants to catch up and keep up with the blockchain of that producer. It is assumed that a consumer only consumes from one producer (or one of a related set of producers), so unlike in the node-to-node protocol there is no need to choose between different available chains. The producer may still not fully trust the consumer and does not want to be subject to asymmetric resource consumption attacks. In this use case, because of the wider range of applications that wish to consume the blockchain, having some options that are easy to implement is more important, even if this involves a trade-off with performance. That said, there are also use cases where tight integration is possible and making the most efficient use of resources is more desirable.

There are a number of applications that simply want to consume the blockchain, but are able to rely on an upstream trusted or semi-trusted Cardano consensus node. These applications do not need to engage in the full consensus protocol, and may be happy to delegate the necessary chain validation.

Examples include 3rd party applications that want to observe the blockchain, examples being business processes triggered by transactions or analytics. It may also include certain kinds of light client that wish to follow the blockchain but not do full validation.

Once one considers a node-to-consumer protocol as a first class citizen then it opens up opportunities for different system architecture choices. The architecture of the original Cardano Mainnet release was entirely homogeneous: every node behaved the same, each trusted nothing but itself and paid the full networking and processing cost of engaging in the consensus protocol. In particular everything was integrated into a single process: the consensus algorithm itself, serving data to other peers and components such as the wallet or explorer. If we were to have a robust and efficient node-to-consumer protocol then we can make many other choices.

With an efficient *local* IPC protocol we can have applications like wallets and explorers as separate processes. Even for tightly integrated components it can make sense to run them in separate OS processes and using associated OS management tools. Not only are the timing constraints for a consensus node much easier to manage when it does not have to share CPU resources with chain consumers, but it enables sophisticated end-users to use operating system features to have finer control over resource consumption. There have been cases in production where a highly loaded wallet component takes more than its allowed allocation of CPU resources and causes the local node to miss its deadlines. By giving a consensus node a dedicated CPU core it becomes easier to provide the necessary hard real time guarantees. In addition, scaling on multi-core machines is significantly easier with multiple OS processes than with a multi-threaded OS process with a shared-heap. This could allow larger capacity Cardano relay deployments where there are multiple network facing proxy processes that all get their chain from a single local consensus node.

With an efficient *network* IPC protocol we can do similar things but extend it across multiple machines. This permits: large organisations to achieve better alignment with their security policies; clusters of relays operated by a single organisation to use the more efficient (less resource costly) node-to-consumer protocol instead of the node-to-node protocol; and wallet or explorer-like applications that need to scale out, and are able to make use of a trusted node.

# CDDL Specification of the Protocol Messages {#CBOR-section}

[]{#included-cddl label="included-cddl"} This Sections contains the CDDL[@cddl] specification of the binary serialisation format of the network protocol messages.

To keep this Section in close sync with the actual Haskell implementation the names of the Haskell identifiers have been reused for the corresponding CBOR types (with the first letter converted to lower case). Note, that, for readability, the previous Sections used simplified message identifiers, for example `RequestNext` instead of `msgRequestNext`, etc. Both identifiers refer to the same message format.

All transmitted messages satisfy the shown CDDL specification. However, CDDL, by design, also permits variants in the encoding that are not valid in the protocol. In particular, the notation ${\tt [} ... {\tt ]}$ in CDDL can be used for both fixed-length and variable-length CBOR-list, while only one of the two encodings is valid in the protocol. We add comments in specification to make clear which encoding must be used.

Note that, in the case of the request-response mini protocol (Section refrequest-response-protocol) there in only ever one possible kind of message in each state. This means that there is no need to tag messages at all and the protocol can directly transmit the plain request and response data.
