# Interface to the ledger
## Abstract interface
In [\[overview:ledger\]](#overview:ledger) we identified three responsibilities for the ledger layer:

- "Ticking" the ledger state, applying any time related changes ([1.1.1](#ledger:api:IsLedger)). This is independent from blocks, both at the value level (we don't need a block in order to tick) and at the type level.

- Applying and verifying blocks ([1.1.2](#ledger:api:ApplyBlock)). This obviously connects a ledger and a block type, but we try to avoid to talk about *the* ledger corresponding to a block, in order to improve compositionality; we will see examples of where this comes in useful in the definition of the extended ledger state ([\[storage:extledgerstate\]](#storage:extledgerstate)) and the ledger database ([\[ledgerdb\]](#ledgerdb)).

- Projecting out the ledger view ([1.1.4](#ledger:api:LedgerSupportsProtocol)), connecting a ledger to a consensus protocol.

We will discuss these responsibilities one by one.

### Independent definitions
We will start with ledger API that can be defined independent of a choice of block or a choice of consensus protocol.

#### Configuration

Like the other abstractions in the consensus layer, the ledger defines its own type of required static configuration

    type family LedgerCfg l :: Type

#### Tip

We require that any ledger can report its tip as a `Point`. A `Point` is either genesis (no blocks have been applied yet) or a pair of a hash and slot number; it is parametric over $l$ in order to allow different ledgers to use different hash types.

    class GetTip l where
      getTip :: l -> Point l

#### Ticking

We can now define the `IsLedger` class as

    class (GetTip l, GetTip (Ticked l), ..) => IsLedger l where
      type family LedgerErr l :: Type
      applyChainTick :: LedgerCfg l -> SlotNo -> l -> Ticked l

The type of `applyChainTick` is similar to the type of `tickChainDepState` we saw in [\[consensus:class:state\]](#consensus:class:state). Examples of the time-based changes in the ledger state include activating delegation certificates in the Byron ledger, or paying out staking rewards in the Shelley ledger.

Ticking is not allowed to fail (it cannot return an error). Consider what it would mean if it *could* fail: it would mean that a previous block was accepted as valid, but set up the ledger state so that no matter what would happen next, as soon as a particular moment in time is reached, the ledger would fail to advance any further. Obviously, such a situation cannot be permitted to arise (the block should have been rejected as invalid).

Note that ticking does not change the tip of the ledger: no blocks have been applied (yet). This means that we should have

$$\begin{equation}
  \mathtt{getTip} \; l
= \mathtt{getTip} \; (\mathtt{applyChainTick}_\mathit{cfg} \; s \; l)
\end{equation}$$

#### Ledger errors

The inclusion of `LedgerErr` in `IsLedger` is perhaps somewhat surprising. `LedgerErr` is the type of errors that can arise when applying blocks to the ledger, but block application is not yet defined here. Nonetheless, a ledger can only be used with a *single* type of block[^1], and consequently can only have a *single* type of error; the only reason block application is defined separately is that a single type of *block* can be used with multiple ledgers (in other words, this is a 1-to-many relationship).[^2]

### Applying blocks
If `applyChainTick` was analogous to `tickChainDepState`, then `applyLedgerBlock` and `reapplyLedgerBlock` are analogous to `updateChainDepState` and `reupdateChainDepState`, respectively ([\[consensus:class:state\]](#consensus:class:state)): apply a block to an already ticked ledger state:

    class (IsLedger l, ..) => ApplyBlock l blk where
      applyLedgerBlock ::
        LedgerCfg l -> blk -> Ticked l -> Except (LedgerErr l) l
      reapplyLedgerBlock ::
        LedgerCfg l -> blk -> Ticked l -> l

The discussion of the difference between, and motivation for, the distinction between application and reapplication in [\[consensus:class:state\]](#consensus:class:state) about the consensus protocol state applies here equally.

### Linking a block to its ledger

We mentioned at the start of [1.1](#ledger:api) that a single block can be used with multiple ledgers. Nonetheless, there is one "canonical" ledger for each block; for example, the Shelley block is associated with the Shelley ledger, even if it can also be applied to the extended ledger state or the ledger DB. We express this through a data family linking a block to its "canonical ledger state":

    data family LedgerState blk :: Type

and then require that it must be possible to apply a block to its associated ledger state

    class ApplyBlock (LedgerState blk) blk => UpdateLedger blk

(this is an otherwise empty class). For convenience, we then also introduce some shorthand:

    type LedgerConfig      blk = LedgerCfg (LedgerState blk)
    type LedgerError       blk = LedgerErr (LedgerState blk)
    type TickedLedgerState blk = Ticked    (LedgerState blk)

### Projecting out the ledger view
In [\[overview:ledger\]](#overview:ledger) we mentioned that a consensus protocol may require some information from the ledger, and in [\[consensus:class:ledgerview\]](#consensus:class:ledgerview) we saw that this is modelled as the `LedgerView` type family in the `ConsensusProtocol` class. A ledger and a consensus protocol are linked through the block type (indeed, apart from the fundamental concepts we have discussed so far, most of consensus is parameterised over blocks, not ledgers or consensus protocols). Recall from [\[BlockSupportsProtocol\]](#BlockSupportsProtocol) that the `BlockProtocol` type family defines for each block what the corresponding consensus protocol is; we can use this to define the projection of the ledger view (defined by the consensus protocol) from the ledger state as follows:

    class (..) => LedgerSupportsProtocol blk where
      protocolLedgerView ::
           LedgerConfig blk
        -> Ticked (LedgerState blk)
        -> Ticked (LedgerView (BlockProtocol blk))

      ledgerViewForecastAt ::
           LedgerConfig blk
        -> LedgerState blk
        -> Forecast (LedgerView (BlockProtocol blk))

The first method extracts the ledger view out of an already ticked ledger state; think of it as the "current" ledger view. Forecasting deserves a more detailed discussion and will be the topic of the next section.

## Forecasting
### Introduction

In [\[nonfunctional:network:headerbody\]](#nonfunctional:network:headerbody) we discussed the need to validate headers from upstream peers. In general, header validation requires information from the ledger state. For example, in order to verify whether a Shelley header was produced by the right node, we need to know the stake distribution (recall that in Shelley the probability of being elected a leader is proportional to the stake); this information is precisely what is captured by the `LedgerView` ([\[consensus:class:ledgerview\]](#consensus:class:ledgerview)). However, we cannot update the ledger state with block headers only, we need the block bodies: after all, to stay with the Shelley example, the stake evolves based on the transactions that are made, which appear only in the block bodies.

Not all is lost, however. The stake distribution used by the Shelley ledger for the sake of the leadership check *is not the *current* stake distribution*, but the stake distribution as it was at a specific point in the past. Moreover, that same stake distribution is then used for all leadership checks in a given period of time.[^3] In the depiction below, the stake distribution as it was at point $b$ is used for the leadership checks near the current tip, the stake distribution at point $a$ was used before that, and so forth:

::: center

This makes it possible to *forecast* what the stake distribution (i.e., the ledger view) will be at various points. For example, if the chain looks like

::: center

then we can "forecast" that the stake distribution at point $c$ will be the one established at point $a$, whereas the stake distribution at point $d$ will be the one established at point $b$. The stake distribution at point $e$ is however not yet known; we say that $e$ is "out of the forecast range".

### Code

Since we're always forecasting what the ledger would look like *if it would be advanced to a particular slot*, the result of forecasting is always something ticked:[^4]

    data Forecast a = Forecast {
          forecastAt  :: WithOrigin SlotNo
        , forecastFor :: SlotNo -> Except OutsideForecastRange (Ticked a)
        }

Here `forecastAt` is the tip of the ledger in which the forecast was constructed and `forecastFor` is constructing the forecast for a particular slot, possibly returning an error message of that slot is out of range. This terminology---a forecast constructed *at* a slot and computed *for* a slot---is used throughout both this technical report as well as the consensus layer code base.

### Ledger view
For the ledger view specifically, the `LedgerSupportsProtocol` class ([1.1.4](#ledger:api:LedgerSupportsProtocol)) requires a function

    ledgerViewForecastAt ::
         LedgerConfig blk
      -> LedgerState blk
      -> Forecast (LedgerView (BlockProtocol blk))

This function must satisfy two important properties:

Sufficient range

:   When we validate headers from an upstream node, the most recent usable ledger state we have is the ledger state at the intersection of our chain and the chain of the upstream node. That intersection will be at most $k$ blocks back, because that is our maximum rollback and we disconnect from nodes that fork from our chain more than $k$ blocks ago ([\[consensus:overview:k\]](#consensus:overview:k)). Furthermore, it is only useful to track an upstream peer if we might want to adopt their blocks, and we only switch to their chain if it is longer than ours ([\[consensus:overview:chainsel\]](#consensus:overview:chainsel)). This means that in the worst case scenario, with the intersection $k$ blocks back, we need to be able to evaluate $k + 1$ headers in order to adopt the alternative chain. However, the range of a forecast is based on *slots*, not blocks; since not every slot may contain a block ([\[time:slots-vs-blocks\]](#time:slots-vs-blocks)), the range needs to be sufficient to *guarantee* to contain at least $k + 1$ blocks[^5]; we will come back to this in [\[future:block-vs-slot\]](#future:block-vs-slot).

    The network layer may have additional reasons for wanting a long forecast range; see [\[nonfunctional:network:headerbody\]](#nonfunctional:network:headerbody).

Relation to ticking

:   Forecasting is not the only way that we can get a ledger view for a particular slot; alternatively, we can also *tick* the ledger state, and then ask for the ledger view at that ticked ledger state. These two ways should give us the same answer: $$\begin{equation}
    \begin{array}{lllll}
    \mathrm{whenever} &
    \mathtt{forecastFor} \; (\mathtt{ledgerViewForecastAt}_\mathit{cfg} \; l) \; s & = & \mathtt{Right} & l' \\
    \mathrm{then} & \mathtt{protocolLedgerView}_\mathit{cfg} \; (\mathtt{applyChainTick}_\mathit{cfg} \; s \; l) & = && l'
    \end{array}
    \end{equation}$$ In other words, whenever the ledger view for a particular slot is within the forecast range, then ticking the ledger state to that slot and asking for the ledger view at the tip should give the same answer. Unlike forecasting, however, ticking has no maximum range. The reason is the following fundamental difference between these two concepts:

    > **(Forecast vs. ticking)** When we *forecast* a ledger view, we are predicting what that ledger view will be, *no matter which blocks will be applied to the chain* between the current tip and the slot of the forecast. By contrast, when we *tick* a ledger, we are applying any time-related changes to the ledger state in order to apply the *next* block; in other words, when we tick to a particular slot, *there *are* no blocks in between the current tip and the slot we're ticking to*. Since there are no intervening blocks, there is no uncertainty, and hence no limited range.

## Queries
## Abandoned approach: historical states

[^1]: While it is true that the Cardano ledger can be used with Byron blocks, Shelley blocks, Goguen blocks, etc., this distinction between the different blocks is invisible to most of the consensus layer. The whole raison d'être of the hard fork combinator ([\[hfc\]](#hfc)) is to present a composite ledger (say, the one consisting of the Byron, Shelley and Goguen eras) as a single type of ledger with a single type of block. The rest of the consensus layer is not aware that this composition has happened; from its point perspective it's just another ledger with an associated block type.

[^2]: Defining `LedgerErr` in `ApplyBlock` ([1.1.2](#ledger:api:ApplyBlock)) would result in ambiguous types, since it would not refer to the `blk` type variable of that class.

[^3]: The exact details of precisely *how* the chain is split is not relevant to the consensus layer, and is determined by the ledger layer.

[^4]: An *unticked* ledger view would arise from deriving the ledger view from the *current* ledger state, not taking (nor needing to take) into account any changes that have been scheduled for later slots. The unticked ledger view is however rarely useful; when we validate a header, any changes that have been scheduled in the most recent ledger state for slots before or at the slot number of the header must be applied before we validate the header; we therefore almost exclusively work with ticked ledger views.

[^5]: Due to a misalignment between the consensus requirements and the Shelley specification, this is not the case for Shelley, where the effective maximum rollback is in fact $k - 1$; see [\[shelley:forecasting\]](#shelley:forecasting)).
