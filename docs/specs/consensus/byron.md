# Byron

Some details specific to the Byron ledger. EBBs already discussed at length in \[ebbs\]{reference-type="ref+label" reference="ebbs"}.

The Byron specification can be found at <https://github.com/input-output-hk/cardano-ledger-specs>.

## Update proposals
### Moment of hard fork
The Byron ledger state provides the current protocol version in

    adoptedProtocolVersion :: ProtocolVersion

in the `State` type from `Cardano.Chain.Update.Validation.Interface`. This protocol version is a three-tuple *major*, *minor*, *alt*. The Byron specification does not provide any semantic interpretation of these components. By convention (outside of the purview of the Byron specification), the hard fork is initiated the moment that the *major* component of `adoptedProtocolVersion` reaches a predefined, hardcoded, value.

### The update mechanism for the `ProtocolVersion`

Updates to the `ProtocolVersion` in Byron are part of the general infrastructure for changing protocol parameters (parameters such as the maximum block size), except that in the case of a hard fork, we care only about changing the `ProtocolVersion`, and not any of the parameters themselves.

The general mechanism for updating protocol parameters in Byron is as follows:

1.  A protocol update *proposal* transaction is created. It proposes new values for some protocol parameters and a greater *protocol version* number as an identifier. There cannot be two proposals with the same version number.

2.  Genesis key delegates can add *vote* transactions that refer to such a proposal (by its hash). They don't have to wait; a node could add a proposal and a vote for it to its mempool simultaneously. There are only positive votes, and a proposal has a time-to-live (see `ppUpdateProposalTTL`) during which to gather sufficient votes. While gathering votes, a proposal is called *active*.

    Note that neither Byron nor Shelley support full centralisation (everybody can vote); this is what the Voltaire ledger is intended to accomplish.

3.  Once the number of voters satisfies a threshold (currently determined by the `srMinThd` field of the `ppSoftforkRule` protocol parameter), the proposal becomes *confirmed*.

4.  Once the threshold-satisfying vote becomes stable (i.e. its containing block is at least $2k$ slots deep), a block whose header's protocol version number (`CC.Block.headerProtocolVersion`) is that of the proposal is interpreted as an *endorsement* of the stably-confirmed proposal by the block's issuer (specifically by the Verification Key of its delegation certificate). Endorsements---i.e. *any block*, since they all contain that header field---also trigger the system to discard proposals that were not confirmed within their TTL.

    Notably, endorsements for proposals that are not yet stably-confirmed (or do not even exist) are not invalid but rather silently ignored. In other words, no validation applies to the 'headerProtocolVersion' field.

5.  Once the number of endorsers satisfies a threshold (same as for voting), the confirmed proposal becomes a *candidate* proposal.

6.  *At the beginning of an epoch*, the candidate proposal with the greatest protocol version number among those candidates whose threshold-satisfying endorsement is stable (i.e. the block is at least $2k$ deep) is *adopted*: the new protocol parameter values have now been changed.

    If there was no stable candidate proposal, then nothing happens. Everything is retained; in particular, a candidate proposal whose threshold-satisfying endorsement was not yet stable will be adopted at the subsequent epoch unless it is surpassed in the meantime.

    When a candidate is adopted, all record of other proposals/votes/endorsements---regardless of their state---is discarded. The explanation for this is that such proposals would now be interpreted as an update to the newly adopted parameter values, whereas they were validated as an update to the previously adopted parameter values.

The diagram shown in 1.1{reference-type="ref+label" reference="byron:update-process"} summarises the progress of a proposal that's eventually adopted. For other proposals, the path short circuits to a "rejected/discarded" status at some point.


------------------------------------------------------------------------

::: center

------------------------------------------------------------------------

**[]{#byron:update-process label="byron:update-process"}Byron update proposal process**

### Initiating the hard fork
Proposals to initiate the hard fork can be submitted and voted on before all core nodes are ready. After all, once a proposal is stably confirmed, it will effectively remain so indefinitely until nodes endorse it (or it gets superseded by another proposal). This means that nodes can vote to initiate the hard fork, *then* wait for everybody to update their software, and once updated, the proposal is endorsed and eventually the hard fork is initiated.

Endorsement is somewhat implicit. The node operator does not submit an explicit "endorsement transaction", but instead restarts the node[^1] (probably after a software update that makes the node ready to support the hard fork) with a new protocol version (as part of a configuration file or command line parameter), which then gets included in the blocks that the node produces (this value is the `byronProtocolVersion` field in the static `ByronConfig`).

### Software versions

The Byron ledger additionally also records the latest version of the software on the chain, in order to facilitate software discovering new versions and subsequently updating themselves. This would normally precede all of the above, but as far as the consensus layer is concerned, this is entirely orthogonal. It does not in any way interact with either the decision to hard fork nor the moment of the hard fork. If we did forego it, the discussion above would still be entirely correct. As of Shelley, software discovery is done off-chain.

The Byron *block header* also records a software version (`headerSoftwareVersion`). This is a legacy concern only, and is present in but ignored by the current Byron implementation, and entirely absent from the Byron specification.

[^1]: []{#byron:unnecessary-restarts label="byron:unnecessary-restarts"}A node restart is necessary for *any* change to a protocol parameter, even though most parameters do not require any change to the software at all.
