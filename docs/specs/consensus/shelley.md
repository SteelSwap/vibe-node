# Shelley

## Update proposals
### Moment of the hard fork
Similar to the Byron ledger (byron:hardfork:moment), the Shelley ledger provides a "current protocol version", but it is a two-tuple (not a three-tuple), containing only a *hard fork* component and *soft fork* component:

    _protocolVersion :: (Natural, Natural)

in `PParams`. The hard fork from Shelley to its successor will be initiated once the hard fork component of this version gets incremented.

### The update mechanism for the protocol version

The update mechanism in Shelley is simpler than it is in Byron. There is no distinction between votes and proposals: to "vote" for a proposal one merely submits the exact same proposal. There is also no separate endorsement step (though see 1.1.3).

The procedure is as follows:

1.  As in Byron, a proposal is a partial map from parameters to their values.

2.  During each epoch, a genesis key can submit (via its delegates) zero, one, or many proposals; each submission overrides the previous one.

3.  "Voting" (submitting of proposals) ends $6k/f$ slots before the end of the epoch (i.e., twice the stability period, called `stabilityWindow` in the Shelley ledger implementation).

4.  At the end of an epoch, if the majority of nodes (as determined by the `Quorum` specification constant, which must be greater than half the nodes) have most recently submitted the same exact proposal, then it is adopted.

5.  The next epoch is always started with a clean slate, proposals from the previous epoch that didn't make it are discarded.[^1]

The protocol version itself is also considered to be merely another parameter, and parameters can change without changing the protocol version, although a convention could be established that the protocol version must change if any of the parameters do; but the specification itself does not mandate this.

### Initiating the hard fork
The timing of the hard fork in Shelley is different to the one in Byron: in Byron, we *first* vote and then wait for people to get ready (byron:hardfork:initiating); in Shelley it is the other way around.

Core node operators will want to know that a significant majority of the core nodes is ready (supports the hard fork) before initiating it. To make this visible, Shelley blocks contain a protocol version. This is not related to the current protocol version as reported by the ledger state (`_protocolVersion` as discussed in the previous section), but it is the *maximum* protocol version that the node which produced that block can support.

Once we see blocks from all or nearly all core nodes with the 'hard fork' component of their protocol version equal to the post-hard-fork value, nodes will submit their proposals with the required major version change to initiate the hard fork.[^2]

## Forecasting
Discuss the fact that the effective maximum rollback in Shelley is $k - 1$, not $k$; see also ledger:forecasting.

[^1]: Proposals *can* be explicitly marked to be for future epochs; in that case, these are simply not considered until that epoch is reached.

[^2]: This also means that unlike in Byron (byron:unnecessary-restarts), in Shelley there is no need to restart the node merely to support a particular parameter change (such as a maximum block size).
