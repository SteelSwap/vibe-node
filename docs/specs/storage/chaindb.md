# Chain Database {#chaindb}

TODO: This is currently a disjoint collection of snippets.

## Union of the Volatile DB and the Immutable DB {#chaindb:union}

As discussed in [\[storage:components\]](#storage:components){reference-type="ref+label" reference="storage:components"}, the blocks in the Chain DB are divided between the Volatile DB ([\[volatile\]](#volatile){reference-type="ref+label" reference="volatile"}) and the Immutable DB ([\[immutable\]](#immutable){reference-type="ref+label" reference="immutable"}). Yet, it presents a unified view of the two databases. Whereas the Immutable DB only contains the immutable chain and the Volatile DB the volatile *parts* of multiple forks, by combining the two, the Chain DB contains multiple forks.

### Looking up blocks {#chaindb:union:lookup}

Just like the two underlying databases the Chain DB allows looking up a `BlockComponent` of a block by its point. By comparing the slot number of the point to the slot of the immutable tip, we could decide in which database to look up the block. However, this would not be correct: the point might have a slot older than the immutable tip, but refer to a block not in the Immutable DB, i.e., a block on an older fork. More importantly, there is a potential race condition: between the time at which the immutable tip was retrieved and the time the block is retrieved from the Volatile DB, the block might have been copied to the Immutable DB and garbage collected from the Volatile DB, resulting in a false negative. Nevertheless, the overlap between the two makes this scenario very unlikely.

For these reasons, we look up a block in the Chain DB as follows. We first look up the given point in the Volatile DB. If the block is not in the Volatile DB, we fall back to the Immutable DB. This means that if, at the same, a block is copied from the Volatile DB to the Immutable DB and garbage collected from the Volatile DB, we will still find it in the Immutable DB. Note that failed lookups in the Volatile DB are cheap, as no disk access is required.

### Iterators {#chaindb:union:iterators}

Similar to the Immutable DB ([\[immutable:api:iterators\]](#immutable:api:iterators){reference-type="ref+label" reference="immutable:api:iterators"}), the Chain DB allows streaming blocks using iterators. We only support streaming blocks from the current chain or from a recent fork. We *do not* support streaming from a fork that starts before the current immutable tip, as these blocks are likely to be garbage collected soon. Moreover, it is of no use to us to serve another node blocks from a fork we discarded.

We might have to stream blocks from the Immutable DB, the Volatile DB, or from both. If the end bound is older or equal to the immutable tip, we simply try to open an Immutable DB iterator with the given bounds. If the end bound is newer than the immutable tip, we construct a path of points (see `filterByPredecessor` in [\[volatile:api\]](#volatile:api){reference-type="ref+label" reference="volatile:api"}) connecting the end bound to the start bound. This path is either entirely in the Volatile DB or it is partial because a block is missing from the Volatile DB. If the missing block is the tip of the Immutable DB, we will have to stream from the Immutable DB in addition to the Volatile DB. If the missing block is not the tip of the Immutable DB, we consider the range to be invalid. In other words, we allow streaming from both databases, but only if the immutable tip is the transition point between the two, it cannot be a block before the tip, as that would mean the fork is too old.

Image?

To stream blocks from the Volatile DB, we maintain the constructed path of points as a list in memory and look up the corresponding block (component) in the Volatile DB one by one.

Consider the following scenario: we open a Chain DB iterator to stream the beginning of the current volatile chain, i.e., the blocks in the Volatile DB right after the immutable tip. However, before streaming the iterator's first block, we switch to a long fork that forks off all the way back at our immutable tip. If that fork is longer than the previous chain, blocks from the start of our chain will be copied from the Volatile DB to the Immutable DB, advancing the immutable tip. This means the blocks the iterator will stream are now part of a fork older than $k$. In this new situation, we would not allow opening an iterator with the same range as the already-opened iterator. However, we do allow streaming these blocks using the already opened iterator, as the blocks to stream are unlikely to have already been garbage collected. Nevertheless, it is still theoretically possible[^1] that such a block has already been garbage collected. For this reason, the Chain DB extends the Immutable DB's `IteratorResult` type (see [\[immutable:api:iterators\]](#immutable:api:iterators){reference-type="ref+label" reference="immutable:api:iterators"}) with the `IteratorBlockGCed` constructor:

    data IteratorResult blk b =
        IteratorExhausted
      | IteratorResult b
      | IteratorBlockGCed (RealPoint blk)

There is another scenario to consider: we stream the blocks from the start of the current volatile chain, just like in the previous scenario. However, in this case, we do not switch to a fork, but our chain is extended with new blocks, which means blocks from the start of our volatile chain are copied from the Volatile DB to the Immutable DB. If these blocks have been copied and garbage collected before the iterator is used to stream them from the Volatile DB (which is unlikely, as explained in the previous scenario), the iterator will incorrectly yield `IteratorBlockGCed`. Instead, when a block that was planned to be streamed from the Volatile DB is missing, we first look in the Immutable DB for the block in case it has been copied there. After the block copied to the Immutable has been streamed, we continue with the remaining blocks to stream from the Volatile DB. It might be the case that the next block has also been copied and garbage collected, requiring another switch to the Immutable DB. In the theoretical worst case, we have to switch between the two databases for each block, but this is nearly impossible to happen in practice.

### Followers {#chaindb:union:followers}

In addition to iterators, the Chain DB also supports *followers*. Unlike an iterator, which is used to request a static segment of the current chain or a recent fork, a follower is used to follow the *current chain*. Either from the start of from a suggested more recent point. Unlike iterators, followers are dynamic, they will follow the chain when it grows or forks. A follower is pull-based, just like its primary user, the chain sync server (see [\[servers:chainsync\]](#servers:chainsync){reference-type="ref+label" reference="servers:chainsync"}). This avoids the need to have a growing queue of changes to the chain on the server side in case the client side is slower.

The API of a follower is as follows:

    data Follower m blk a = Follower {
          followerInstruction         :: m (Maybe (ChainUpdate blk a))
        , followerInstructionBlocking :: m (ChainUpdate blk a)
        , followerForward             :: [Point blk] -> m (Maybe (Point blk))
        , followerClose               :: m ()
        }

The `a` parameter is the same `a` as the one in `BlockComponent` (see [\[immutable:api:block-component\]](#immutable:api:block-component){reference-type="ref+label" reference="immutable:api:block-component"}), as a follower for any block component `a` can be opened.

A follower always has an implicit position associated with it. The `followerInstruction` operation and its blocking variant allow requesting the next instruction w.r.t. the follower's implicit position, i.e., a `ChainUpdate`:

    data ChainUpdate block a =
        AddBlock a
      | RollBack (Point block)

The `AddBlock` constructor indicates that to follow the current chain, the follower should extend its chain with the given block (component). Switching to a fork is represented by first rolling back to a certain point (`RollBack`), followed by at least as many new blocks (`AddBlock`) as blocks that have been rolled back. If we were to represent switching to a fork using a constructor like:

      | SwitchToFork (Point block) [a]

we would need to have many blocks or block components in memory at the same time.

These operations are implemented as follows. In case the follower is looking at the immutable part of the chain, an Immutable DB iterator is used and no rollbacks will be encountered. When the follower has advanced into the volatile part of the chain, the in-memory fragment containing the last $k$ headers is used (see [\[storage:inmemory\]](#storage:inmemory){reference-type="ref+label" reference="storage:inmemory"}). Depending on the block component, the corresponding block might have to be read from the Volatile DB.

When a new chain has been adopted during chain selection (see [\[chainsel:addblock\]](#chainsel:addblock){reference-type="ref+label" reference="chainsel:addblock"}), all open followers that are looking at the part of the current chain that was rolled back are updated so that their next instruction will be the correct `RollBack`. By definition, followers looking at the immutable part of the chain will be unaffected.

By default, a follower will start from the very start of the chain, i.e., at genesis. Accordingly, the first instruction will be an `AddBlock` with the very first block of the chain. As mentioned, the primary user of a follower is the chain sync server, of which the clients in most cases already have large parts of the chain. The `followerForward` operation can be used in these cases to find a more recent intersection from which the follower can start. The client will sent a few recent points from its chain and the follower will try to find the most recent of them that is on our current chain. This is implemented by looking up blocks by their point in the current chain fragment and the Immutable DB.

Followers are affected by garbage collection similarly to how iterators are ([1.1.2](#chaindb:union:iterators){reference-type="ref+label" reference="chaindb:union:iterators"}): when the implicit position of the follower is in the immutable part of the chain, an Immutable DB iterator with a static range is used. Such an iterator is not aware of blocks appended to the Immutable DB since the iterator was opened. This means that when the iterator reaches its end, we first have to check whether more blocks have been appended to the Immutable DB. If so, a new iterator is opened to stream these blocks. If not, we switch over to the in-memory fragment.

## Block processing queue {#chaindb:queue}

Discuss the chain DB's block processing queue, the future/promises/events, concurrency concerns, etc.

Discuss the problem of the effective queue size (#2721).

## Marking invalid blocks {#chaindb:invalidblocks}

The chain database keeps a set of hashes of known-to-be-invalid blocks. This information is used by the chain sync client ([\[chainsyncclient\]](#chainsyncclient){reference-type="ref+label" reference="chainsyncclient"}) to terminate connections to nodes with a chain that contains an invalid block.

::: lemma
[]{#chaindb:dont-mark-invalid-successors label="chaindb:dont-mark-invalid-successors"} When the chain database discovers an invalid block $X$, it is sufficient to mark only $X$; there is no need to additionally mark any successors of $X$.
:::

::: proof
*Proof (sketch)..* The chain sync client maintains a chain fragment corresponding to some suffix of the upstream node's chain, and it preserves an invariant that that suffix must intersect with the node's own current chain. It can therefore never be the case that the fragment contains a successor of $X$ but not $X$ itself: since $X$ is invalid, the node will never adopt it, and so a fragment that intersects the node's current chain and includes a successor of $X$ *must* also contain $X$. ◻
:::

TODO: We should discuss how this relates to GC ([1.5](#chaindb:gc){reference-type="ref+label" reference="chaindb:gc"}).

## Effective maximum rollback

The maximum rollback we can support is bound by the length of the current fragment. This will be less than $k$ only if

- We are near genesis and the immutable database is empty, or

- Due to data corruption the volatile database lost some blocks

Only the latter case is some cause for concern: we are in a state where conceptually we *could* roll back up to $k$ blocks, but due to how we chose to organise the data on disk (the immutable/volatile split) we cannot. One option here would be to move blocks *back* from the immutable DB to the volatile DB under these circumstances, and indeed, if there were other parts of the system where rollback might be instigated that would be the right thing to do: those other parts of the system should not be aware of particulars of the disk layout.

However, since the chain database is *exclusively* in charge of switching to forks, all the logic can be isolated to the chain database. So, when we have a short volatile fragment, we will just not roll back more than the length of that fragment. Conceptually this can be justified also: the fact that $I$ is the tip of the immutable DB means that *at some point* it was in our chain at least $k$ blocks back, and so we considered it to be immutable: the fact that some data loss occurred does not really change that. We may still roll back more than $k$ blocks when disk corruption occurs in the immutable database, of course.

One use case of the current fragment merits a closer examination. When the chain sync client ([\[chainsyncclient\]](#chainsyncclient){reference-type="ref+label" reference="chainsyncclient"}) looks for an intersection between our chain and the chain of the upstream peer, it sends points from our chain fragment. If the volatile fragment is shorter than $k$ due to data corruption, the client would have fewer points to send to the upstream node. However, this is the correct behaviour: it would mean we cannot connect to upstream nodes who fork more than $k$ of what *used to be* our tip before the data corruption, even if that's not where our tip is anymore. In the extreme case, if the volatile database gets entirely erased, only a single point is available (the tip of the immutable database $I$), and hence we can only connect to upstream nodes that have $I$ on their chain. This is precisely stating that we can only sync with upstream nodes that have a chain that extends our immutable chain.

## Garbage collection {#chaindb:gc}

Blocks on chains that are never selected, or indeed blocks whose predecessor we never learn, will eventually be garbage collected when their slot number number is more than $k$ away from the tip of the selected chain.[^2]

::: bug
The chain DB (more specifically, the volatile DB) can still grow without bound if we allow upstream nodes to rapidly switch between forks; this should be addressed at the network layer (for instance, by introducing rate limiting for rollback in the chain sync client, [\[chainsyncclient\]](#chainsyncclient){reference-type="ref+label" reference="chainsyncclient"}).
:::

Although this is GC of the volatile DB, I feel it belongs here more than in the volatile DB chapter because here we know *when* we could GC. But perhaps it should be split into two: a section on how GC is implemented in the volatile DB chapter, and then a section here how it's used in the chain DB. References from elsewhere in the report to GC should probably refer here, though, not to the vol DB chapter.

### GC delay {#chaindb:gc:delay}

For performance reasons neither the immutable DB nor the volatile DB ever makes explicit `fsync` calls to flush data to disk. This means that when the node crashes, recently added blocks may be lost. When this happens in the volatile DB it's not a huge deal: when the node starts back up and the chain database is initialised we just run chain selection on whatever blocks still remain; in typical cases we just end up with a slightly shorter chain.

However, when this happens in the immutable database the impact may be larger. In particular, if we delete blocks from the volatile database as soon as we add them to the immutable database, then data loss in the immutable database would result in a gap between the volatile database and the immutable database, making *all* blocks in the volatile database unusable. We can recover from this, but it would result in a large rollback (in particular, one larger than $k$).

To avoid this, we currently have a delay between adding blocks to the immutable DB and removing them from the volatile DB (garbage collection). The delay is configurable, but should be set in such a way that the possibility that the block has not yet been written to disk at the time of garbage collection is minimised;a a relatively short delay should suffice (currently we use a delay of 1 minute), though there are other reasons for preferring a longer delay:

- Clock changes can more easily be accommodated with more overlap ([\[{future:clockchanges}\]](#{future:clockchanges}){reference-type="ref+label" reference="{future:clockchanges}"})

- The time delay also determines the worst-case validity of iterators (todo: reference to relevant section).

Larger delays will of course result in more overlap between the two databases. During normal node operation this might not be much, but the overlap might be more significant during bulk syncing.

Notwithstanding the above discussion, an argument could be made that the additional complexity due to the delay is not worth it; even a "rollback" of more than $k$ is easily recovered from[^3], and clock changes as well, as iterators asking for blocks that now live on distant chains, are not important use cases. We could therefore decide to remove it altogether.

## Resources {#chaindb:resources}

In the case of the chain DB, the allocation function will be wrapped in a `runWithTempRegistry` combinator, which will hold an empty resulting state. This is because as mentioned in [\[nonfunctional:temporaryregs\]](#nonfunctional:temporaryregs){reference-type="ref" reference="nonfunctional:temporaryregs"}, we only get values that do not leak implementation details and therefore we can't run any checks, but still we want to keep track of the resources. The allocation of each of the databases (Immutable DB and Volatile DB) will be executed using the combinator `runInnerWithTempRegistry` so that each of them performs the relevant checks on the `OpenState` they return but such checks are not visible (nor runnable) on the chain DB scope.

The threads that are spawned during the initialization of the database will be registered in the node general registry as they won't be directly tracked by the chain DB API but instead will coexist on its side.

The final step of ChainDB initialization is registering itself in the general registry so that it is closed in presence of an exception.

[^1]: This is unlikely, as there is a delay between copying and garbage collection (see [1.5.1](#chaindb:gc:delay){reference-type="ref+label" reference="chaindb:gc:delay"}) and there are network time-outs on the block fetch protocol, of which the server-side (see [\[servers:blockfetch\]](#servers:blockfetch){reference-type="ref+label" reference="servers:blockfetch"}) is the primary user of Chain DB iterators.

[^2]: This is slot based rather than block based for historical reasons only; we should probably change this.

[^3]: Note that the node will never actually notice such a rollback; the node would crash when discovering data loss, and then restart with a smaller chain
