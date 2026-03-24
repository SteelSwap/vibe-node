# Serialisation abstractions
Some of the various pieces of data that are handled by consensus also need to be serialised to a binary format so that they can be:

1.  written/read to/from *storage* (see \[storage\]{reference-type="ref+label" reference="storage"}) or;

2.  sent/received across the *network* (e.g., headers via the chain sync protocol \[chainsyncclient\]{reference-type="ref+label" reference="chainsyncclient"}).

The two serialisation purposes above have different requirements and are independent of each other. For example, when establishing a network connection, a version number is negotiated. We can vary the network serialisation format depending on the version number, allowing for instance to include some more information in the payload. A concrete example of this is that starting from a certain version, we include the block size in the payload when sending a Byron header across the network as the header itself does not contain it. This kind of versioning only concerns the network and is independent of the storage layer. Hence we define separate abstractions for them, decoupling them from each other.

For both abstractions, we use the CBOR (Concise Binary Object Representation) format, because it has the following benefits, paraphrasing the `cborg` library:

- fast serialisation and deserialisation

- compact binary format

- stable format across platforms (32/64bit, big/little endian)

- potential to read the serialised format from other languages

- incremental or streaming (de)serialisation

- suitable to use with untrusted input (resistance to asymmetric resource consumption attacks)

- \...

Moreover, CBOR was chosen for the initial implementation of the Cardano blockchain, with which we must maintain binary compatibility. While it was possible to switch to another format for the block types developed after the initial implementation, we saw no reason to switch.

We will now discuss both serialisation abstractions in more detail.

## Serialising for storage
The following data is stored on disk (see \[storage\]{reference-type="ref+label" reference="storage"}):

- Blocks

- The extended ledger state (see \[storage:extledgerstate\]{reference-type="ref+label" reference="storage:extledgerstate"} and \[ledgerdb:on-disk\]{reference-type="ref+label" reference="ledgerdb:on-disk"}) which is the combination of:

  - The header state (\[storage:headerstate\]{reference-type="ref+label" reference="storage:headerstate"})

  - The ledger state

We use the following abstraction for serialising data to and from disk:

    class EncodeDisk blk a where
      encodeDisk<!-- CodecConfig -->

    class DecodeDisk blk a where
      decodeDisk<!-- CodecConfig -->

- These type classes have two type parameters: the block `blk`, over which most things are parameterised, and `a`, the type to (de)serialise. For example, `a` can be the block type itself or the type corresponding to the ledger state.

- `CodecConfig blk` is a data family that defines the extra configuration needed for (de)serialisation. For example, to deserialise an EBB (\[ebbs\]{reference-type="ref+label" reference="ebbs"}), the number of slots per epoch needs to be known statically to compute the slot of the block based on the epoch number, as the serialisation of an EBB does not contain its slot number, but the in-memory representation does. This configuration is kept as small as possible and is ideally empty.

- The `a -> Encoding` and `forall s. Decoder s a` are the types for respectively encoders and decoders of the `cborg` library.

- The encoder and decoder are split in two classes because they are not always *symmetric*: the instantiation of `a` in the encoder is not always the same as in the corresponding decoder. This is because blocks are *annotated* with their serialisation. We discuss this in more detail in 1.3{reference-type="ref+label" reference="serialisation:annotations"}.

### Nested contents
By writing a block to disk we automatically have written the block's header to disk, as the header is a part of the block. While we never write just a header, we do support *reading* just the header. This is more efficient than reading the entire block and then extracting the header, as fewer bytes have to be read from disk and deserialised.

<!-- center -->

Extracting the header from a block on disk can be very simple, like in the figure above. The block starts with an envelope, which is followed by the block header and the block body. In this case, we read the bytes starting from the start of the header until the end of the header, which we then decode. We use the following abstraction to represent this information:

    data BinaryBlockInfo = BinaryBlockInfo {
          headerOffset :: !Word16
        , headerSize   :: !Word16
        }

    class HasBinaryBlockInfo blk where
      getBinaryBlockInfo<!-- blk -->

As the size of a header can vary on a per-block basis, we maintain this information *per block* in the storage layer. We trade four extra bytes of storage and memory space for faster reading of headers.

However, it is not for every type of block the case that the encoding of a header can literally be sliced out of the encoding of the corresponding block. The serialisation of a header when embedded in a block might be different from the serialisation of a header on its own. For example, the standalone header might require an additional envelope or a different one than the block's envelope.

A concrete example of this are the Byron blocks and headers. A Byron block is either a regular block or an epoch boundary block (EBB) (discussed in \[ebbs\]{reference-type="ref+label" reference="ebbs"}). A regular block has a different header than an EBB, consequently, their encoding differs. The envelope of the encoding of a Byron block includes a tag indicating whether the block is a regular block or an EBB, so that the decoder knows what kind of header and body to expect. For the same reason, the envelope of the encoding of a standalone Byron header includes the same tag. However, when we slice out the header from the Byron block and feed that to the decoder for Byron headers, the envelope containing the tag will be *missing*.

The same problem presents itself for the hard fork combinator (\[hfc\]{reference-type="ref+label" reference="hfc"}): when using the hard fork combinator to combine two block types, A and B, into one, the block's envelope will (typically) indicate whether it is a block of type A or B. The header corresponding to such a block will have a similar envelope. When we slice the header out of such a block, the required envelope will be missing. The right envelope has to be prepended so that the header decoder knows whether it should expect A or B.

The header is *nested* inside the block and to be able to decode it, we need some more *context*, i.e., the envelope of the header. In the storage layer (\[storage\]{reference-type="ref+label" reference="storage"}), we store the context of each block in an index (in-memory or on-disk, depending on the database) so that after reading both the context and the sliced header, we can decode the header without having to read and decode the entire block. We capture this idea in the following abstractions.

    data family NestedCtxt_ blk :: (Type -> Type) -> (Type -> Type)

As usual, we parameterise over the block type. We also parameterise over another functor, e.g., `f`, which in practice will be instantiated to `Header`, but in the future, there might be more types of nested contents, other than headers, e.g., block bodies. The constructors of this data family will represent the different types of context available, e.g., for Byron a context for regular blocks and a context for EBBs.

`NestedCtxt` is indexed by `blk`: it is the block that determines this type. However, we often want to partially apply the second argument (the functor), leaving the block type not yet defined, hence we define:

    newtype NestedCtxt f blk a = NestedCtxt {
          flipNestedCtxt<!-- NestedCtxt -->
        }

The `a` type index will correspond to the raw, sliced header that requires the additional context. It can vary with the context, e.g., the context for a Byron EBB will fix `a` to a raw EBB header (without the necessary envelope).

Now that we have defined `NestedCtxt`, we can define the class that allows us to separate the nested type (the header) into the context and the raw, sliced type (the raw header, `a`), as well as the inverse:

    class (..) => HasNestedContent f blk where
      unnest<!-- f -->
      nest<!-- DepPair -->

`DepPair` is a dependent pair that allows us to hide the type parameter `a`. When writing a block, `unnest` is used to extract the context so that it can be stored in the appropriate index. When reading a header, `nest` is used to combine the context, read from the appropriate index, with the raw header into the header.

In certain scenarios, we do not have access to the separately stored context of the block, but we do have access to the encoded block, in which case we should be able to able to extract the context directly from the encoded block, without having to decode it entirely. We use the `ReconstructNestedCtxt` class for this:

    class HasNestedContent f blk => ReconstructNestedCtxt f blk where
      reconstructPrefixLen<!-- proxy -->
      reconstructNestedCtxt ::
           proxy (f blk)
        -> ShortByteString
        -> ..
        -> SomeSecond (NestedCtxt f) blk

The `PrefixLen` is the number of bytes extracted from the beginning of the encoded block required to reconstruct the context. The `ShortByteString` corresponds to these bytes. The `reconstructNestedCtxt` method will parse this bytestring and return the corresponding context. The `SomeSecond` type is used to hide the type parameter `a`.

As these contexts and context-dependent types do not fit the mould of the `EncodeDisk` and `DecodeDisk` classes described in 1.1{reference-type="ref+label" reference="serialisation:storage"}, we define variants of these classes:

    class EncodeDiskDepIx f blk where
      encodeDiskDepIx<!-- CodecConfig -->
                      -> SomeSecond f blk -> Encoding

    class DecodeDiskDepIx f blk where
      decodeDiskDepIx<!-- CodecConfig -->
                      -> Decoder s (SomeSecond f blk)

    class EncodeDiskDep f blk where
      encodeDiskDep<!-- CodecConfig -->
                    -> a -> Encoding

    class DecodeDiskDep f blk where
      decodeDiskDep<!-- CodecConfig -->
                    -> forall s. Decoder s (ByteString -> a)

## Serialising for network transmission
The following data is sent across the network:

- Header hashes

- Blocks

- Headers

- Transactions

- Transaction IDs

- Transaction validation errors

- Ledger queries

- Ledger query results

We use the following abstraction for serialising data to and from the network:

    class SerialiseNodeToNode blk a where
      encodeNodeToNode<!-- CodecConfig -->
                       -> BlockNodeToNodeVersion blk
                       -> a -> Encoding
      decodeNodeToNode<!-- CodecConfig -->
                       -> BlockNodeToNodeVersion blk
                       -> forall s. Decoder s a

    class SerialiseNodeToClient blk a where
      encodeNodeToClient<!-- CodecConfig -->
                         -> BlockNodeToClientVersion blk
                         -> a -> Encoding
      decodeNodeToClient<!-- CodecConfig -->
                         -> BlockNodeToClientVersion blk
                         -> forall s. Decoder s a

These classes are similar to the ones used for storage (1.1{reference-type="ref+label" reference="serialisation:storage"}), but there are some important differences:

- The encoders and decoders are always symmetric, which means we do not have to separate encoders from decoders and can merge them in a single class. Nevertheless, some of the types sent across the network still have to deal with annotations (1.3{reference-type="ref+label" reference="serialisation:annotations"}), we discuss how we solve this in 1.2.2{reference-type="ref+label" reference="serialisation:network:cbor-in-cbor"}.

- We have separate classes for *node-to-node* and *node-to-client* serialisation. By separating them, we are more explicit about which data is serialised for which type of connection. Node-to-node protocols and node-to-client protocols have different properties and requirements. This also gives us the ability to, for example, use a different encoding for blocks for node-to-node protocols than for node-to-client protocols.

- The methods in these classes all take a *version* as argument. We will discuss versioning in 1.2.1{reference-type="ref+label" reference="serialisation:network:versioning"}.

### Versioning
As requirements evolve, features are added, data types change, constructors are added and removed. For example, adding the block size to the Byron headers, adding new ledger query constructors, etc. This affects the data we send across the network. In a distributed network of nodes, it is a given that not all nodes will simultaneously upgrade to the latest released version and that nodes running different versions of the software, i.e., different versions of the consensus layer, will try to communicate with each other. They should of course be able to communicate with each other, otherwise the different versions would cause partitions in the network.

This means we should be careful to maintain binary compatibility between versions. The network layer is faced with the same issue: as requirements evolve, network protocols (block fetch, chain sync) are modified change (adding messages, removing messages, etc.), network protocols are added or retired, etc. While the network layer is responsible for the network protocols and the encoding of their messages, the consensus layer is responsible for the encoding of the data embedded in these messages. Changes to either should be possible without losing compatibility: a node should be able to communicate successfully with other nodes that run a newer or older version of the software, up to certain limits (old versions can be retired eventually).

To accomplish this, the network layer uses *versions*, one for each bundle of protocols:

    data NodeToNodeVersion
        = NodeToNodeV_1
        | NodeToNodeV_2
        | ..

    data NodeToClientVersion
        = NodeToClientV_1
        | NodeToClientV_2
        | ..

For each backwards-incompatible change, either a change in the network protocols or in the encoding of the consensus data types, a new version number is introduced in the corresponding version data type. When the network layer establishes a connection with another node or client, it will negotiate a version number during the handshake: the highest version that both parties can agree on. This version number is then passed to any client and server handlers, which decide based on the version number which protocols to start and which protocol messages (not) to send. A new protocol message would only be sent when the version number is greater or equal than the one with which it was introduced.

This same network version is passed to the consensus layer, so we can follow the same approach. However, we decouple the network version numbers from the consensus version numbers for the following reason. A new network version number is needed for each backwards-incompatible change to the network protocols or the encoding of the consensus data types. This is clearly a strict superset of the changes caused by consensus. When the network layer introduces a new protocol message, this does not necessarily mean anything changes in the encoding of the consensus data types. This means multiple network versions can correspond to the same consensus-side encoding or *consensus version*. In the other direction, each change to the consensus-side encodings should result in a new network version. We capture this in the following abstraction:

    class (..) => HasNetworkProtocolVersion blk where
      type BlockNodeToNodeVersion   blk<!-- Type -->
      type BlockNodeToClientVersion blk<!-- Type -->

    class HasNetworkProtocolVersion blk
       => SupportedNetworkProtocolVersion blk where
      supportedNodeToNodeVersions ::
           Proxy blk -> Map NodeToNodeVersion   (BlockNodeToNodeVersion   blk)
      supportedNodeToClientVersions ::
           Proxy blk -> Map NodeToClientVersion (BlockNodeToClientVersion blk)

The `HasNetworkProtocolVersion` class has two associated types to define the consensus version number types for the given block. When no versioning is needed, one can use the unit type as the version number. The `SupportedNetworkProtocolVersion` defines the mapping between the network and the consensus version numbers. Note that this does not have to be an injection, as multiple network version can most certainly map to the same consensus version. Nor does this have to be a surjection, as old network and consensus versions might be removed from the mapping when the old version no longer needs to be supported. This last reason is also why this mapping is modelled with a `Map` instead of a function: it allows enumerating a subset of all defined versions, which is not possible with a function.

Global numbering vs multiple block types

The `SerialiseNodeToNode` and `SerialiseNodeToClient` instances can then branch on the passed version to introduce changes to the encoding format, for example, the inclusion of the block size in the Byron header encoding.

Consider the following scenario: a change is made to one of the consensus data types, for example, a new query constructor is added the ledger query data type. This requires a new consensus and thus network version number, as older versions will not be able to decode it. What should be done when the new query constructor is sent to a node that does not support it (the negotiated version is older than the one in which the constructor was added)? If it is encoded and send, the receiving side will fail to decode it and terminate its connection. This is rather confusing to the sender, as they are left in the dark. Instead, we let the *encoder* throw an exception in this case, terminating that connection, so that the sender is at least notified of this. Ideally, we could statically prevent such cases.

### CBOR-in-CBOR
In 1.3{reference-type="ref+label" reference="serialisation:annotations"}, we explain why the result of the decoder for types using *annotations* needs to be passed the original encoding as a bytestring. When reading from disk, we already have the entire bytestring in memory, so it can easily be passed to the result of the decoder. However, this is not the case when receiving a message via the network layer: the entire message, containing the annotated type(s), is decoded incrementally. When decoding CBOR, it is not possible to obtain the bytestring corresponding to what the decoder is decoding. To work around this, we use *CBOR-in-CBOR*: we encode the original data as CBOR and then encode the resulting bytestring as CBOR *again*. When decoding CBOR-in-CBOR, after decoding the outer CBOR layer, we have exactly the bytestring that we will need for the annotation. Next, we feed this bytestring to the original decoder, and, finally, we pass the bytestring to the function returned by the decoder.

### Serialised
One of the duties of the consensus layer is to serve blocks and headers to other nodes in the network. To serve for example a block, we read it from disk, deserialise it, and then serialise it again and send it across the network. The costly deserialisation and serialisation steps cancel each other out and are thus redundant. We perform this optimisation in the following way. When reading such a block from storage, we do not read the `blk`, but the `Serialised blk`, which is a phantom type around a raw, still serialised bytestring:

    newtype Serialised a = Serialised ByteString

To send this serialised block over the network, we have to encode this `Serialised blk`. As it happens, we use CBOR-in-CBOR to send both blocks and headers over the network, as described in 1.2.2{reference-type="ref+label" reference="serialisation:network:cbor-in-cbor"}. This means the serialised block corresponds to the inner CBOR layer and that we only have to encode the bytestring again as CBOR, which is cheap.

This optimisation is only used to *send* and thus encode blocks and headers, not when *receiving* them, because each received block or header will have to be inspected and validated, and thus deserialised anyway.

As discussed in 1.1.1{reference-type="ref+label" reference="serialisation:storage:nested-contents"}, reading a header (nested in a block) from disk requires reading the context and the raw header, and then combining them before we can deserialise the header. This means the approach for serialised headers differs slightly:

    newtype SerialisedHeader blk = SerialisedHeaderFromDepPair {
          serialisedHeaderToDepPair<!-- GenDepPair -->
                                                  (NestedCtxt Header blk)
        }

This is similar to the `DepPair (NestedCtxt f blk)` type from 1.1.1{reference-type="ref+label" reference="serialisation:storage:nested-contents"}, but this time the raw header is wrapped in `Serialised` instead of being deserialised.

## Annotations
move up? The previous two sections refer to this

The following technique is used in the Byron and Shelley ledgers for a number of data types like blocks, headers, transactions, ...The in-memory representation of, for example a block, consists of both the typical fields describing the block (header, transactions, ...), but also the *serialisation* of the block in question. The block is *annotated* with its serialisation.

The principal reason for this is that it is possible that multiple serialisations, each which a different hash, correspond to the same logical block. For example, a client sending us the block might encode a number using a binary type that is wider than necessary (e.g., encoding the number 0 using four bytes instead of a single byte). CBOR defines a *canonical format*, we call an encoding that is in CBOR's canonical format a *canonical encoding*.

When after deserialising a block in a non-canonical encoding, we serialise it again, we will end up with a different encoding, i.e., the canonical encoding, as we stick to the canonical format. This means the hash, which is part of the blockchain, is now different and can no longer be verified.

For this reason, when deserialising a block, the original, possibly non-canonical encoding is retained and used to annotate the block. To compute the hash of the block, one can hash the annotated serialisation.

Besides solving the issue with non-canonical encodings, this has a performance advantage, as encoding such a block is very cheap, it is just a matter of copying the in-memory annotation.

We rely on it being cheap in a few places, mention that/them?

extra memory usage

This means that the result of the decoder must be passed the original encoding as a bytestring to use as the annotation of the block or other type in question. Hence the decoder corresponding to the encoder `blk -> Encoding` has type `forall s. Decoder s (ByteString -> blk)`, which is a different instantiation of the type `a`, explaining the split of the serialisation classes used for storage (1.1{reference-type="ref+label" reference="serialisation:storage"}). The original encoding is then applied to the resulting function to obtain the annotated block. This asymmetry is handled in a different way for the network serialisation, namely using CBOR-in-CBOR (1.2.2{reference-type="ref+label" reference="serialisation:network:cbor-in-cbor"}).

### Slicing

discuss the slicing of annotations with an example. What is the relation between the decoded bytestring and the bytestring passed to the function the decoder returns? Talk about compositionality.
