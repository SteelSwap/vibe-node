# Update Proposal Mechanism
The $\mathsf{UPDATE}$ transition is responsible for the federated governance model in Shelley. The governance process includes a mechanism for core nodes to propose and vote on protocol parameter updates. In this chapter we outline rules for genesis keys *proposing* protocol parameter updates. For rules regarding the *adoption* of protocol parameter updates, see Section sec:pparam-update.

This chapter does not discuss authentication of update proposals. The signature for the keys in the proposal will be checked in the $\mathsf{UTXOW}$ transition, which checks all the necessary witnesses for a transaction, see Sectionsec:witnesses-shelley.

**Genesis Key Delegations.** The environment for the protocol parameter update transition contains the value $\mathit{genDelegs}$, which is a finite map indexed by genesis key hashes, and which maps to a pair consisting of a delegate key hash (corresponding to the cold key used for producing blocks) and a VRF key hash.

During the Byron era, the genesis nodes are all already delegated to some $\mathsf{KeyHash}$, and these delegations are inherited through the Byron-Shelley transition (see Section sec:byron-to-shelley). The VRF key hashes in this mapping will be new to the Shelley era.

The delegations mapping can be updated as described in Section sec:delegation-shelley, but there is no mechanism for them to un-delegate or for the keys to which they delegate to retire (unlike regular stake pools).

The types $\mathsf{ProposedPPUpdates}$ and $\mathsf{Update}$ were defined in Figure fig:defs:utxo-shelley. The update proposal type $\mathsf{Update}$ is a pair of $\mathsf{ProposedPPUpdates}$ and $\mathsf{Epoch}$. The epoch in the update specifies the epoch in which the proposal is valid. $\mathsf{ProposedPPUpdates}$ is a finite maps which is indexed by the hashes of the keys of entities proposing the given updates, $\mathsf{KeyHashGen}$. We use the abstract type $\mathsf{KeyHashGen}$ to represent hashes of genesis (public verification) keys, which have type $\mathsf{VKeyGen}$. Genesis keys are the keys belonging to the federated nodes running the Cardano system currently (also referred to as core nodes). The regular user verification keys are of a type $\mathsf{VKey}$, distinct from the genesis key type, $\mathsf{VKeyGen}$. Similarly, the type hashes of these are distinct, $\mathsf{KeyHash}$ and $\mathsf{KeyHashGen}$ respectively.

Currently, updates can only be proposed and voted on by the owners of the genesis keys. The process of decentralization will result in the core nodes gradually giving up some of their privileges and responsibilities to the network, eventually give them *all* up. The update proposal mechanism will not be decentralized in the Shelley era, however. For more on the decentralization process, see Section sec:new-epoch-trans.

## Protocol Parameter Update Proposals
The transition type $\mathsf{PPUP}$ is for proposing updates to protocol parameters, see Figure 1 (for the corresponding rules, see Figure 2). The signal for this transition is an optional update.

Protocol updates for the current epoch are only allowed up until ($2\cdot\mathsf{StabilityWindow}$)-many slots before the end of the epoch. The reason for this involves how we safely predict hard forks. Changing the protocol version can result in a hard fork, and we would like an entire stability period between when we know that a hard fork will necessarily happen and when the current epoch ends. Protocol updates can still be submitted during the last ($2\cdot\mathsf{StabilityWindow}$)-many slots of the epoch, but they must be marked for the following epoch.

The transition $\mathsf{PPUP}$ has three rules:

- PP-Update-Empty : No new updates were proposed, do nothing.

- PP-Update-Current : Some new updates $\mathit{up}$ were proposed for the current epoch, and the current slot is not too far into the epoch. Add these to the existing proposals using a right override. That is, if a genesis key has previously submitted an update proposal, replace it with its new proposal in $\mathit{pup}$.

- PP-Update-Future : Some new updates $\mathit{up}$ were proposed for the next epoch, and the current slot is near the end of the epoch. Add these to the existing future proposals using a right override. That is, if a genesis key has previously submitted a future update proposal, replace it with its new proposal in $\mathit{pup}$.

  The future update proposals will become update proposals on the next epoch, provided they contain no proposals for a protocol version which cannot follow from the current protocol version. See the $\mathsf{NEWPP}$ transition in Figure fig:rules:new-proto-param, and the function $\mathsf{updatePpup}$ from Figure fig:ts-types:new-proto-param.

This rule has the following predicate failures:

1.  In the case that the epoch number in the signal is not appropriate for the slot in the current epoch, there is a *PPUpdateWrongEpoch* failure.

2.  In the case of being non-empty, if the check $\dom pup \subseteq
      \dom genDelegs$ fails, there is a *NonGenesisUpdate* failure as only genesis keys can be used in the protocol parameter update.

3.  If a protocol parameter update in contains a proposal for a protocol version which cannot follow from the current protocol version, there is a *PVCannotFollow* failure. Note that $\mathsf{pvCanFollow}$ is defined in Figure 1.


*Derived types* $$\begin{equation*}
    \begin{array}{lclr}
      \mathsf{GenesisDelegation}
      & ~=~
      & \mathsf{KeyHashGen}\mapsto(\mathsf{KeyHash}\times\mathsf{KeyHash}_{vrf})
      & \text{genesis delegations} \\
    \end{array}
\end{equation*}$$ *Protocol Parameter Update environment* $$\begin{equation*}
    \mathsf{PPUpdateState} =
    \left(
      \begin{array}{rlr}
        \mathit{pup} & \mathsf{ProposedPPUpdates} & \text{current proposals}\\
        \mathit{fpup} & \mathsf{ProposedPPUpdates} & \text{future proposals}\\
      \end{array}
    \right)
\end{equation*}$$ $$\begin{equation*}
    \mathsf{PPUpdateEnv} =
    \left(
      \begin{array}{rlr}
        \mathit{slot} & \mathsf{Slot} & \text{current slot}\\
        \mathit{pp} & \mathsf{PParams} & \text{protocol parameters}\\
        \mathit{genDelegs} & \mathsf{GenesisDelegation}
                        & \text{genesis key delegations} \\
      \end{array}
    \right)
\end{equation*}$$ *Protocol Parameter Update transitions* $$\begin{equation*}
    \_ \vdash
    \mathit{\_} \xrightarrow[\mathsf{ppup}]{}{\_} \mathit{\_}
    \subseteq \powerset (
    \mathsf{PPUpdateEnv} \times \mathsf{PPUpdateState} \times \mathsf{Update}^? \times \mathsf{PPUpdateState})
\end{equation*}$$ *Helper Functions* $$\begin{align*}
      & \mathsf{pvCanFollow} \in \mathsf{ProtVer} \to \mathsf{ProtVer} \to \mathsf{Bool}\\
      & \mathsf{pvCanFollow}~(m,~n)~(m',~n') = \\
      & ~~~~(m + 1, 0) = (m', n') \lor (m, n + 1) = (m', n')
\end{align*}$$

**Protocol Parameter Update Transition System Types**
$$\begin{equation}
\label{eq:pp-update-Empty}
    \inference[PP-Update-Empty]
    {
      \mathit{up} = \mathsf{Nothing}
    }
    {
      \begin{array}{r}
        \mathit{slot}\\
        \mathit{pp}\\
        \mathit{genDelegs}\\
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{pup_s} \\
        \mathit{fpup_s}
      \end{array}
      \right)
      \xrightarrow[\mathsf{ppup}]{}{up}
      \left(
      \begin{array}{r}
        \mathit{pup_s} \\
        \mathit{fpup_s}
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:update-nonempty}
    \inference[PP-Update-Current]
    {
      (\mathit{pup},~\mathit{e})\mathrel{\mathop:}=\mathit{up}
      &
      \mathrm{dom}~pup\subseteq\mathrm{dom}~genDelegs
      \\
      \forall\mathit{ps}\in\mathrm{range}~pup,~
        \mathit{pv}\mapsto\mathit{v}\in\mathit{ps}\implies\mathsf{pvCanFollow}~(\mathsf{pv}~\mathit{pp})~\mathit{v}
      \\
      \mathit{slot} < \mathsf{firstSlot}~((\mathsf{epoch}~slot) + 1) - 2\cdot\mathsf{StabilityWindow}
      \\
      \mathsf{epoch}~slot = e
    }
    {
      \begin{array}{c}
        \mathit{slot}\\
        \mathit{pp}\\
        \mathit{genDelegs}\\
      \end{array}
      \vdash
      \left(
      \begin{array}{c}
        \mathit{pup_s} \\
        \mathit{fpup_s}
      \end{array}
      \right)
      \xrightarrow[\mathsf{ppup}]{}{up}
      \left(
      \begin{array}{c}
        \mathsf{varUpdate}~pup_s\unionoverrideRight pup \\
        \mathit{fpup_s}
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:update-nonempty}
    \inference[PP-Update-Future]
    {
      (\mathit{pup},~\mathit{e})\mathrel{\mathop:}=\mathit{up}
      &
      \mathrm{dom}~pup\subseteq\mathrm{dom}~genDelegs
      \\
      \forall\mathit{ps}\in\mathrm{range}~pup,~
        \mathit{pv}\mapsto\mathit{v}\in\mathit{ps}\implies\mathsf{pvCanFollow}~(\mathsf{pv}~\mathit{pp})~\mathit{v}
      \\
      \mathit{slot} \geq \mathsf{firstSlot}~((\mathsf{epoch}~slot) + 1) - 2\cdot\mathsf{StabilityWindow}
      \\
      \mathsf{epoch}~slot = e + 1
    }
    {
      \begin{array}{c}
        \mathit{slot}\\
        \mathit{pp}\\
        \mathit{genDelegs}\\
      \end{array}
      \vdash
      \left(
      \begin{array}{c}
        \mathit{pup_s} \\
        \mathit{fpup_s}
      \end{array}
      \right)
      \xrightarrow[\mathsf{ppup}]{}{up}
      \left(
      \begin{array}{c}
        \mathit{pup_s} \\
        \mathsf{varUpdate}~fpup_s\unionoverrideRight pup \\
      \end{array}
      \right)
    }
\end{equation}$$

**Protocol Parameter Update Inference Rules**