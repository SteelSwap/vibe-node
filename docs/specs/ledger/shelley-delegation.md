# Delegation
We briefly describe the motivation and context for delegation. The full context is contained in [@delegation_design].

Stake is said to be *active* in the blockchain protocol when it is eligible for participation in the leader election. In order for stake to become active, the associated verification stake credential must be registered and its staking rights must be delegated to an active stake pool. Individuals who wish to participate in the protocol can register themselves as a stake pool.

Stake credentials are registered (or deregistered) through the use of registration (or deregistration) certificates. Registered stake credentials are delegated through the use of delegation certificates. Finally, stake pools are registered (or retired) through the use of registration (or retirement) certificates.

Stake pool retirement is handled a bit differently than stake deregistration. Stake credentials are considered inactive as soon as a deregistration certificate is applied to the ledger state. Stake pool retirement certificates, however, specify the epoch in which it will retire.

Delegation requires the following to be tracked by the ledger state: the registered stake credentials, the delegation map from registered stake credentials to stake pools, pointers associated with stake credentials, the registered stake pools and upcoming stake pool retirements. Additionally, the blockchain protocol rewards eligible stake and so we must also include a mapping from active stake credentials to rewards.

Finally, there are two types of delegation certificates available only to the genesis keys. The genesis keys will still be used for update proposals at the beginning of the Shelley era, and so there must be a way to maintain the delegation of these keys to their cold keys. This mapping is also maintained by the delegation state. There is also a mechanism to transfer rewards directly from either the reserves pot or the treasury pot to a reward address. While technically everybody can post such a certificate, the transaction that contains it must be signed by $\Quorum$-many genesis key delegates.

## Delegation Definitions
In 1{reference-type="ref+label" reference="fig:delegation-defs"} we give the delegation primitives. Here we introduce the following primitive datatypes used in delegation:

- $\DCertRegKey$: a stake credential registration certificate.

- $\DCertDeRegKey$: a stake credential de-registration certificate.

- $\DCertDeleg$: a stake credential delegation certificate.

- $\DCertRegPool$: a stake pool registration certificate.

- $\DCertRetirePool$: a stake pool retirement certificate.

- $\DCertGen$: a genesis key delegation certificate.

- $\DCertMir$: a move instantaneous rewards certificate.

- $\DCert$: any one of of the seven certificate types above.

The following derived types are introduced:

- $\PoolParam$ represents the parameters found in a stake pool registration certificate that must be tracked:

  - the pool owners.

  - the pool cost.

  - the pool margin.

  - the pool pledge.

  - the pool reward account.

  - the hash of the VRF verification key.

  - the pool relays.

  - optional pool medata (a url and a hash).

  The idea of pool owners is explained in Section 4.4.4 of [@delegation_design]. The pool cost and margin indicate how much more of the rewards pool leaders get than the members. The pool pledge is explained in Section 5.1 of [@delegation_design]. The pool reward account is where all pool rewards go. The pool relays and metadata url are explained in Sections 3.4.4 and 4.2 of [@delegation_design].

Accessor functions for certificates and pool parameters are also defined, but only the $\cwitness{}$ accessor function needs explanation. It does the following:

- For a $\DCertRegKey$ certificate, $\fun{cwitness}$ is not defined as stake key registrations do not require a witness.

- For a $\DCertDeRegKey$ certificate, $\fun{cwitness}$ returns the hashkey of the key being de-registered.

- For a $\DCertDeleg$ certificate, $\fun{cwitness}$ returns the hashkey of the key that is delegating (and not the key to which the stake in being delegated to).

- For a $\DCertRegPool$ certificate, $\fun{cwitness}$ returns the hashkey of the key of the pool operator.

- For a $\DCertRetirePool$ certificate, $\fun{cwitness}$ returns the hashkey of the key of the pool operator.

- For a $\DCertGen$ certificate, $\fun{cwitness}$ returns the hashkey of the genesis key.

- For a $\DCertMir$ certificate, $\fun{cwitness}$ is not defined as there is no single core node or genesis key that posts the certificate.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \var{url} & \URL & \text{a url}\\
      \var{mp} & \MIRPot & \text{either $\ReservesMIR$ or $\TreasuryMIR$}\\
    \end{array}
\end{equation*}$$ *Delegation Certificate types* $$\begin{equation*}
  \begin{array}{rcl}
    \DCert &=& \DCertRegKey \uniondistinct \DCertDeRegKey \uniondistinct \DCertDeleg \\
                &\hfill\uniondistinct\;&
                \DCertRegPool \uniondistinct \DCertRetirePool \uniondistinct
                                         \DCertGen\\
           &\hfill\uniondistinct\;& \DCertMir
  \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{lclr}
      \PoolMD
      & ~=~
      & \URL \times \type{PoolMDHash}
      & \text{stake pool metadata} \\
      %
      \PoolParam
      & ~=~
      & \powerset{\KeyHash} \times \Coin \times \unitInterval \times \Coin
      & \text{stake pool parameters} \\
      & & \qquad \times \AddrRWD \times \KeyHash_{vrf} \\
      & & \qquad \seqof{\URL} \times \PoolMD^?
    \end{array}
\end{equation*}$$ *Certificate Accessor functions* $$\begin{equation*}
    \begin{array}{rlr}
      \cwitness{} & \DCert\setminus(\DCertRegKey\cup\DCertMir) \to \Credential & \text{certificate witness} \\
      \fun{regCred} & \DCertRegKey \to \Credential & \text{registered credential} \\
      \fun{dpool} & \DCertDeleg \to \KeyHash
                                            & \text{pool being delegated to}
      \\
      \fun{poolParam} & \DCertRegPool \to \PoolParam
                                            & \text{stake pool}
      \\
      \fun{retire} & \DCertRetirePool \to \Epoch
                                            & \text{epoch of pool retirement}
      \\
      \fun{genesisDeleg} & \DCertGen \to (\KeyHashGen,~\KeyHash,~\KeyHash_{vrf})
                                            & \text{genesis delegation}
      \\
      \fun{moveRewards} & \DCertMir \to (\StakeCredential \mapsto \Coin)
                                            & \text{moved inst. rewards}
      \\
      \fun{mirPot} & \DCertMir \to \MIRPot & \text{pot for inst. rewards}
    \end{array}
\end{equation*}$$ *Pool Parameter Accessor functions* $$\begin{equation*}
  \begin{array}{rlr}
    \fun{poolOwners} & \PoolParam \to \powerset{\KeyHash}
                     & \text{stake pool owners}
    \\
    \fun{poolCost} & \PoolParam \to \Coin
                     & \text{stake pool cost}
    \\
    \fun{poolMargin} & \PoolParam \to \unitInterval
                     & \text{stake pool margin}
    \\
    \fun{poolPledge} & \PoolParam \to \Coin
                     & \text{stake pool pledge}
    \\
    \fun{poolRAcnt} & \PoolParam \to \AddrRWD
                     & \text{stake pool reward account}
    \\
    \fun{poolVRF} & \PoolParam \to \KeyHash_{vrf}
                  & \text{stake pool VRF key hash}
    \\
  \end{array}
\end{equation*}$$

**Delegation Definitions**

## Delegation Transitions
In 2{reference-type="ref+label" reference="fig:delegation-transitions"} we give the delegation and stake pool state transition types. We define two separate parts of the ledger state.

- $\DState$ keeps track of the delegation state, consisting of:

  - $\var{rewards}$ stores the rewards accumulated by stake credentials. These are represented by a finite map from reward addresses to the accumulated rewards.

  - $\var{delegations}$ stores the delegation relation, mapping stake credentials to the pool to which is delegates.

  - $\var{ptrs}$ maps stake credentials to the position of the registration certificate in the blockchain. This is needed to lookup the stake hashkey of a pointer address.

  - $\var{fGenDelegs}$ are the future genesis keys delegations. This variable is needed because genesis keys can only update their delegation with a delay of $\StabilityWindow$ slots after submitting the certificate (this is necessary for header validation, see Section \[sec:chain\])

  - $\var{genDelegs}$ maps genesis key hashes to hashes of the cold key delegates.

  - $\var{i_{rwd}}$ stores two maps of stake credentials to $\Coin$, which is used for moving instantaneous rewards at the epoch boundary. One map corresponds to rewards taken from the reserves, and the other corresponds to rewards taken from the treasury.

- $\PState$ keeps track of the stake pool information:

  - $\var{poolParams}$ tracks the parameters associated with each stake pool, such as their costs and margin.

  - When changes are made to the pool parameters late in an epoch, they are staged in $\var{fPoolParams}$. These parameters will be updated by another transition (namely $\mathsf{EPOCH}$) when the next epoch starts.

  - $\var{retiring}$ tracks stake pool retirements, using a map from hashkeys to the epoch in which it will retire.

The operational certificates counters $\var{cs}$ in the stake pool state are a tool to ensure that blocks containing outdated certificates are rejected. These certificates are part of the block header. For a discussion of why this additional mechanism is needed, see the document [@delegation_design], and for the relevant rules, see Section \[sec:oper-cert-trans\].

The environment for the state transition for $\DState$ contains the current slot number, the index for the current certificate pointer, and the account state. The environment for the state transition for $\PState$ contains the current slot number and the protocol parameters.


*Delegation Types* $$\begin{equation*}
    \begin{array}{rclclr}
      \var{stakeCred} & \in &  \StakeCredential & = & (\KeyHash_{stake} \uniondistinct
                                       \HashScr) \\
      \var{fGenDelegs} & \in &  \FutGenesisDelegation & =
                       & (\Slot\times\KeyHashGen)\mapsto(\KeyHash\times\KeyHash_{vrf}) \\
      \var{ir} & \in &  \InstantaneousRewards & =
               & (\StakeCredential \mapsto \Coin) \\
               & & & & ~~~~\times(\StakeCredential \mapsto \Coin) \\
    \end{array}
\end{equation*}$$ *Delegation States* $$\begin{equation*}
    \begin{array}{l}
    \DState =
    \left(\begin{array}{rlr}
            \var{rewards} & \StakeCredential \mapsto \Coin & \text{rewards}\\
            \var{delegations} & \StakeCredential \mapsto \KeyHash_{pool} & \text{delegations}\\
            \var{ptrs} & \Ptr \mapsto \StakeCredential & \text{pointer to stake credential}\\
            \var{fGenDelegs} & \FutGenesisDelegation & \text{future genesis key delegations}\\
            \var{genDelegs} & \GenesisDelegation & \text{genesis key delegations}\\
            \var{i_{rwd}} & \InstantaneousRewards & \text{instantaneous rewards}\\
          \end{array}
      \right)
      \\
    \\
    \PState =
    \left(\begin{array}{rlr}
      \var{poolParams} & \KeyHash_{pool} \mapsto \PoolParam
        & \text{registered pools to pool parameters}\\
      \var{fPoolParams} & \KeyHash_{pool} \mapsto \PoolParam
        & \text{future pool parameters}\\
      \var{retiring} & \KeyHash_{pool} \mapsto \Epoch & \text{retiring stake pools}\\
    \end{array}\right)
    \end{array}
\end{equation*}$$ *Delegation Environment* $$\begin{equation*}
    \DEnv =
    \left(
      \begin{array}{rlr}
        \var{slot} & \Slot & \text{slot}\\
        \var{ptr} & \Ptr & \text{certificate pointer}\\
        \var{acnt} & \Acnt & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ *Pool Environment* $$\begin{equation*}
    \PEnv =
    \left(
      \begin{array}{rlr}
        \var{slot} & \Slot & \text{slot}\\
        \var{pp} & \PParams & \text{protocol parameters}\\
      \end{array}
    \right)
\end{equation*}$$ *Delegation Transitions* $$\begin{equation*}
    \_ \vdash \_ \trans{deleg}{\_} \_ \in
      \powerset (\DEnv \times \DState \times \DCert \times \DState)
\end{equation*}$$ $$\begin{equation*}
    \_ \vdash \_ \trans{pool}{\_} \_ \in
    \powerset (\PEnv \times \PState \times \DCert \times \PState)
\end{equation*}$$

**Delegation Transitions**

## Delegation Rules
The rules for registering and delegating stake credentials are given in 3{reference-type="ref+label" reference="fig:delegation-rules"}. Note that section 5.2 of [@delegation_design] describes how a wallet would help a user choose a stake pool, though these concerns are independent of the ledger rules.

- Stake credential registration is handled by \[eq:deleg-reg\]{reference-type="ref+label" reference="eq:deleg-reg"}, since it contains the precondition that the certificate has type $\DCertRegKey$. All the equations in $\mathsf{DELEG}$ and $\mathsf{POOL}$ follow this same pattern of matching on certificate type.

  There are also preconditions on registration that the hashkey associated with the certificate witness of the certificate is not already found in the current list of stake credentials or the current reward accounts. We expect that the stake credentials and the reward accounts contain the same key hashes, making one of the checks redundant.

  Registration causes the following state transformation:

  - The key is added to the set of registered stake credentials.

  - A reward account is created for this key, with a starting balance of zero. Note that \[eq:deleg-reg\]{reference-type="ref+label" reference="eq:deleg-reg"} uses a union override left to add a zero balance reward account.

  - The certificate pointer is mapped to the new stake credential.

- Stake credential deregistration is handled by \[eq:deleg-dereg\]{reference-type="ref+label" reference="eq:deleg-dereg"}. There is a precondition that the credential has been registered and that the reward balance is zero. Deregistration causes the following state transformation:

  - The key is removed from the collection of registered keys.

  - The reward account is removed.

  - The key is removed from the delegation relation.

  - The certificate pointer is removed.

- Stake credential delegation is handled by \[eq:deleg-deleg\]{reference-type="ref+label" reference="eq:deleg-deleg"}. There is a precondition that the key has been registered. Delegation causes the following state transformation:

  - The delegation relation is updated so that the stake credential is delegated to the given stake pool. The use of union override here allows us to use the same rule to perform both an initial delegation and an update to an existing delegation.

- Genesis key delegation is handled by \[eq:deleg-gen\]{reference-type="ref+label" reference="eq:deleg-gen"}. There is a precondition that the genesis key is already in the mapping $\var{genDelegs}$. Genesis delegation causes the following state transformation:

  - The future genesis delegation relation is updated with the new delegate to be adopted in $\StabilityWindow$-many slots.

- Moving instantaneous rewards is handled by \[eq:deleg-mir-reserves\]{reference-type="ref+label" reference="eq:deleg-mir-reserves"} and \[eq:deleg-mir-treasury\]{reference-type="ref+label" reference="eq:deleg-mir-treasury"}. There is a precondition that the current slot is early enough in the current epoch and that the available reserves or treasury are sufficient to pay for the instantaneous rewards.


$$\begin{equation}
\label{eq:deleg-reg}
    \inference[Deleg-Reg]
    {
      \var{c}\in\DCertRegKey &
      hk \leteq \fun{regCred}~{c} &
      \var{hk} \notin \dom \var{rewards}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{ptr} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
        \var{rewards} \\
        \var{delegations} \\
        \var{ptrs} \\
        \var{fGenDelegs} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
      \trans{deleg}{\var{c}}
      \left(
      \begin{array}{rcl}
        \varUpdate{\var{rewards}} & \varUpdate{\union} & \varUpdate{\{\var{hk} \mapsto 0\}}\\
        \var{delegations} \\
        \varUpdate{\var{ptrs}} & \varUpdate{\union} & \varUpdate{\{ptr \mapsto \var{hk}\}} \\
        \var{fGenDelegs} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:deleg-dereg}
    \inference[Deleg-Dereg]
    {
      \var{c}\in \DCertDeRegKey &
      hk \leteq \cwitness{c} &
      \var{hk} \mapsto 0 \in \var{rewards}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{ptr} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \var{rewards} \\
        \var{delegations} \\
        \var{ptrs} \\
        \var{fGenDelegs} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
      \trans{deleg}{\var{c}}
      \left(
      \begin{array}{rcl}
        \varUpdate{\{\var{hk}\}} & \varUpdate{\subtractdom} & \varUpdate{\var{rewards}} \\
        \varUpdate{\{\var{hk}\}} & \varUpdate{\subtractdom} & \varUpdate{\var{delegations}} \\
        \varUpdate{\var{ptrs}} & \varUpdate{\subtractrange} & \varUpdate{\{\var{hk}\}} \\
        \var{fGenDelegs} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:deleg-deleg}
    \inference[Deleg-Deleg]
    {
      \var{c}\in \DCertDeleg & hk \leteq \cwitness{c} & hk \in \dom \var{rewards}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{ptr} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \var{rewards} \\
        \var{delegations} \\
        \var{ptrs} \\
        \var{fGenDelegs} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
      \trans{deleg}{c}
      \left(
      \begin{array}{rcl}
        \var{rewards} \\
        \varUpdate{\var{delegations}} & \varUpdate{\unionoverrideRight}
                                      & \varUpdate{\{\var{hk} \mapsto \dpool c\}} \\
        \var{ptrs} \\
        \var{fGenDelegs} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:deleg-gen}
    \inference[Deleg-Gen]
    {
      \var{c}\in \DCertGen
      & (\var{gkh},~\var{vkh},~\var{vrf})\leteq\fun{genesisDeleg}~{c}
      \\
      s'\leteq\var{slot}+\StabilityWindow
      & \var{gkh}\in\dom{genDelegs}
      \\~\\
      {
        \begin{array}{ l  c  l \neq\var{gkh}\}} }
          \var{cod} & \var{g} & \var{genDelegs} \\
          \var{fod} & (\wcard,~\var{g}) & \var{fGenDelegs}
        \end{array}
      }
      \\~\\
      {
        \begin{array}{ l  c  c  l }}
          \var{currentOtherColdKeyHashes} & \var{k} & (\var{k},~\wcard) & \var{cod}\\
          \var{currentOtherVrfKeyHashes}  & \var{v} & (\wcard,~\var{v}) & \var{cod}\\
          \var{futureOtherColdKeyHashes}  & \var{k} & (\var{k},~\wcard) & \var{fod}\\
          \var{futureOtherVrfKeyHashes}   & \var{v} & (\wcard,~\var{v}) & \var{fod}\\
      \end{array}
      }
      \\
      \var{vkh}\notin\var{currentOtherColdKeyHashes}\union\var{futureOtherColdKeyHashes} \\
      \var{vrf}\notin\var{currentOtherVrfKeyHashes}\union\var{futureOtherVrfKeyHashes} \\
      \var{fdeleg}\leteq\{(\var{s'},~\var{gkh}) \mapsto (\var{vkh},~\var{vrf})\}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{ptr} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \var{rewards} \\
        \var{delegations} \\
        \var{ptrs} \\
        \var{fGenDelegs} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
      \trans{deleg}{c}
      \left(
      \begin{array}{rcl}
        \var{rewards} \\
        \var{delegations} \\
        \var{ptrs} \\
        \varUpdate{\var{fGenDelegs}}
        & \varUpdate{\unionoverrideRight}
        & \varUpdate{fdeleg} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
    }
\end{equation}$$

**Delegation Inference Rules**

$$\begin{equation}
\label{eq:deleg-mir-reserves}
    \inference[Deleg-Mir]
    {
      \var{c}\in \DCertMir
      &
      \fun{mirPot}~\var{c}=\ReservesMIR
      \\
      slot < \fun{firstSlot}~((\epoch{slot}) + 1) - \fun{StabilityWindow}\\
      (\var{irReserves},~\var{irTreasury})\leteq\var{i_{rwd}}
      &
      \var{combinedR}\leteq\var{irReserves}\unionoverrideRight(\fun{moveRewards}~\var{c}) \\
      \sum\limits_{\wcard\mapsto\var{val}\in\var{combinedR}} val \leq\var{reserves}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{ptr} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \var{rewards} \\
        \var{delegations} \\
        \var{ptrs} \\
        \var{fGenDelegs} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
      \trans{deleg}{c}
      \left(
      \begin{array}{c}
        \var{rewards} \\
        \var{delegations} \\
        \var{ptrs} \\
        \var{fGenDelegs}\\
        \var{genDelegs} \\
        (\varUpdate{\var{combinedR}},~\var{irTreasury}) \\
      \end{array}
      \right)
    }
\end{equation}$$\
 \
$$\begin{equation}
\label{eq:deleg-mir-treasury}
    \inference[Deleg-Mir]
    {
      \var{c}\in \DCertMir
      &
      \fun{mirPot}~\var{c}=\TreasuryMIR
      \\
      slot < \fun{firstSlot}~((\epoch{slot}) + 1) - \fun{StabilityWindow}\\
      (\var{irReserves},~\var{irTreasury})\leteq\var{i_{rwd}}
      &
      \var{combinedT}\leteq\var{irTreasury}\unionoverrideRight(\fun{moveRewards}~\var{c}) \\
      \sum\limits_{\wcard\mapsto\var{val}\in\var{combinedT}} val \leq\var{treasury}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{ptr} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \var{rewards} \\
        \var{delegations} \\
        \var{ptrs} \\
        \var{fGenDelegs} \\
        \var{genDelegs} \\
        \var{i_{rwd}}
      \end{array}
      \right)
      \trans{deleg}{c}
      \left(
      \begin{array}{c}
        \var{rewards} \\
        \var{delegations} \\
        \var{ptrs} \\
        \var{fGenDelegs}\\
        \var{genDelegs} \\
        (\var{irReserves},~\varUpdate{\var{combinedT}}) \\
      \end{array}
      \right)
    }
\end{equation}$$

**Move Instantaneous Rewards Inference Rule**

The DELEG rule has ten possible predicate failures:

- In the case of a key registration certificate, if the staking credential is already registered, there is a *StakeKeyAlreadyRegistered* failure.

- In the case of a key deregistration certificate, if the key is not registered, there is a *StakeKeyNotRegistered* failure.

- In the case of a key deregistration certificate, if the associated reward account is non-zero, there is a *StakeKeyNonZeroAccountBalance* failure.

- In the case of a non-existing stake pool key in a delegation certificate, there is a *StakeDelegationImpossible* failure.

- In the case of a pool delegation certificate, there is a *WrongCertificateType* failure.

- In the case of a genesis key delegation certificate, if the genesis key is not in the domain of the genesis delegation mapping, there is a *GenesisKeyNotInMapping* failure.

- In the case of a genesis key delegation certificate, if the delegate key is in the range of the genesis delegation mapping, there is a *DuplicateGenesisDelegate* failure.

- In the case of insufficient reserves to pay the instantaneous rewards, there is a *InsufficientForInstantaneousRewards* failure.

- In the case that a MIR certificate is issued during the last $\StabilityWindow$-many slots of the epoch, there is a *MIRCertificateTooLateinEpoch* failure.

- In the case of a genesis key delegation certificate, if the VRF key is in the range of the genesis delegation mapping, there is a *DuplicateGenesisVRF* failure.

## Stake Pool Rules
The rules for updating the part of the ledger state defining the current stake pools are given in 5{reference-type="ref+label" reference="fig:pool-rules"}. The calculation of stake distribution is described in Section \[sec:stake-dist-calc\].

In the pool rules, the stake pool is identified with the hashkey of the pool operator. For each rule, again, we first check that a given certificate $c$ is of the correct type.

- Stake pool registration is handled by \[eq:pool-reg\]{reference-type="ref+label" reference="eq:pool-reg"}. It is required that the pool not be currently registered. Registration causes the following state transformation:

  - The key is added to the set of registered stake pools.

  - The pool's parameters are stored.

- Stake pool parameter updates are handled by \[eq:pool-rereg\]{reference-type="ref+label" reference="eq:pool-rereg"}. This rule, which also matches on the certificate type $\type{DCertRegPool}$, is distinguished from \[eq:pool-reg\]{reference-type="ref+label" reference="eq:pool-reg"} by the requirement that the pool be registered.

  Unlike the initial stake pool registrations, the pool parameters will not change until the next epoch, after stake distribution snapshots are taken. This gives delegators an entire epoch to respond to changes in stake pool parameters. The staging is achieved by adding updates to the mapping $\var{fPoolParams}$, which will override $\var{poolParam}$ with new values in the $\mathsf{EPOCH}$ transition (see Figure \[fig:rules:epoch\]{reference-type="ref+label" reference="fig:rules:epoch"}).

  This rule also ends stake pool retirements. Note that $\var{poolParams}$ is **not** updated. The registration creation slot does does not change.

- Stake pool retirements are handled by \[eq:pool-ret\]{reference-type="ref+label" reference="eq:pool-ret"}. Given a slot number $\var{slot}$, the application of this rule requires that the planned retirement epoch $\var{e}$ stated in the certificate is in the future, i.e. after $\var{cepoch}$ (the epoch of the current slot number in this context) and that it is no more than than $\emax$ epochs after the current one. It is also required that the pool be registered. Note that imposing the $\emax$ constraint on the system is not strictly necessary. However, forcing stake pools to announce their retirement a shorter time in advance will curb the growth of the $\var{retiring}$ list in the ledger state.

  The pools scheduled for retirement must be removed from the $\var{retiring}$ state variable at the end of the epoch they are scheduled to retire in. This non-signaled transition (triggered, instead, directly by a change of current slot number in the environment), along with all other transitions that take place at the epoch boundary, are described in Section \[sec:epoch\].

  Reregistration causes the following state transformation:

  - The pool is marked to retire on the given epoch. If it was previously retiring, the retirement epoch is now updated.


$$\begin{equation}
\label{eq:pool-reg}
    \inference[Pool-Reg]
    {
      \var{c}\in\DCertRegPool
      & \var{hk} \leteq \cwitness{c}
      & \var{pool} \leteq \poolParam{c}
      \\
      hk \notin \dom \var{poolParams}
      & \fun{poolCost}~\var{pool}\geq\fun{minPoolCost}~\var{pp}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{pp} \\
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \var{poolParams} \\
        \var{fPoolParams} \\
        \var{retiring} \\
      \end{array}
      \right)
      \trans{pool}{c}
      \left(
      \begin{array}{rcl}
        \varUpdate{\var{poolParams}} & \varUpdate{\union}
                                    & \varUpdate{\{\var{hk} \mapsto \var{pool}\}} \\
       \var{fPoolParams} \\
       \var{retiring} \\
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:pool-rereg}
    \inference[Pool-reReg]
    {
      \var{c}\in\DCertRegPool
      & \var{hk} \leteq \cwitness{c}
      & \var{pool} \leteq \poolParam{c}
      \\
      hk \in \dom \var{poolParams}
      & \fun{poolCost}~\var{pool}\geq\fun{minPoolCost}~\var{pp}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{pp} \\
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
          \var{poolParams} \\
          \var{fPoolParams} \\
          \var{retiring} \\
        \end{array}
      \right)
      \trans{pool}{c}
      \left(
        \begin{array}{rcl}
          \var{poolParams} \\
          \varUpdate{\var{fPoolParams}} & \varUpdate{\unionoverrideRight}
                                        & \varUpdate{\{\var{hk} \mapsto \var{pool}\}}\\
          \varUpdate{\{\var{hk}\}} & \varUpdate{\subtractdom} & \varUpdate{\var{retiring}} \\
        \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:pool-ret}
    \inference[Pool-Retire]
    {
    \var{c} \in \DCertRetirePool
    & hk \leteq \cwitness{c}
    & \var{hk} \in \dom \var{poolParams} \\
    \var{e} \leteq \retire{c}
    & \var{cepoch} \leteq \epoch{slot}
    & \var{cepoch} < \var{e} \leq \var{cepoch} + (\fun{emax}~{pp})
  }
  {
    \begin{array}{r}
      \var{slot} \\
      \var{pp} \\
    \end{array}
    \vdash
    \left(
      \begin{array}{r}
        \var{poolParams} \\
        \var{fPoolParams} \\
        \var{retiring} \\
      \end{array}
    \right)
    \trans{pool}{c}
    \left(
      \begin{array}{rcl}
        \var{poolParams} \\
        \var{fPoolParams} \\
        \varUpdate{\var{retiring}} & \varUpdate{\unionoverrideRight}
                                   & \varUpdate{\{\var{hk} \mapsto \var{e}\}} \\
      \end{array}
    \right)
  }
\end{equation}$$

**Pool Inference Rule**

The POOL rule has four predicate failures:

- In the case of a pool registration or re-registration certificate, if specified pool cost parameter is smaller than the value of the protocol parameter $\mathsf{minPoolCost}$, there is a *StakePoolCostTooLow* failure.

- In the case of a pool retirement certificate, if the pool key is not in the domain of the stake pools mapping, there is a *StakePoolNotRegisteredOnKey* failure.

- In the case of a pool retirement certificate, if the retirement epoch is not between the current epoch and the relative maximal epoch from the current epoch, there is a *StakePoolRetirementWrongEpoch* failure.

- If the delegation certificate is not of one of the pool types, there is a *WrongCertificateType* failure.

## Delegation and Pool Combined Rules
We now combine the delegation and pool transition systems. Figure 6 gives the state, environment and transition type for the combined transition.


*Delegation and Pool Combined Environment* $$\begin{equation*}
    \DPEnv =
    \left(
      \begin{array}{rlr}
        \var{slot} & \Slot & \text{slot}\\
        \var{ptr} & \Ptr & \text{certificate pointer}\\
        \var{pp} & \PParams & \text{protocol parameters}\\
        \var{acnt} & \Acnt & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ *Delegation and Pool Combined State* $$\begin{equation*}
    \DPState =
    \left(
      \begin{array}{rlr}
        \var{dstate} & \DState & \text{delegation state}\\
        \var{pstate} & \PState & \text{pool state}\\
      \end{array}
    \right)
\end{equation*}$$ *Delegation and Pool Combined Transition* $$\begin{equation*}
    \_ \vdash \_ \trans{delpl}{\_} \_ \in
      \powerset (
        \DPEnv \times \DPState \times \DCert \times \DPState)
\end{equation*}$$

**Delegation and Pool Combined Transition Type**

Figure 7, gives the rules for the combined transition. Note that for any given certificate, at most one of the two rules (\[eq:delpl-d\]{reference-type="ref+label" reference="eq:delpl-d"} and \[eq:delpl-p\]{reference-type="ref+label" reference="eq:delpl-p"}) will be successful, since the pool certificates are disjoint from the delegation certificates.


*Delegation and Pool Combined Rules* $$\begin{equation}
    \label{eq:delpl-d}
    \inference[Delpl-Deleg]
    {
      &
      {
        \begin{array}{r}
          \var{slot} \\
          \var{ptr} \\
          \var{acnt}
        \end{array}
      }
      \vdash \var{dstate} \trans{\hyperref[fig:delegation-rules]{deleg}}{c} \var{dstate'}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{ptr} \\
        \var{pp} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \var{dstate} \\
        \var{pstate}
      \end{array}
      \right)
      \trans{delpl}{c}
      \left(
      \begin{array}{rcl}
        \varUpdate{\var{dstate'}} \\
        \var{pstate}
      \end{array}
      \right)
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:delpl-p}
    \inference[Delpl-Pool]
    {
    &
    {
      \begin{array}{r}
        \var{slot} \\
        \var{pp} \\
      \end{array}
    }
    \vdash \var{pstate} \trans{\hyperref[fig:pool-rules]{pool}}{c} \var{pstate'}
    }
    {
      \begin{array}{r}
        \var{slot} \\
        \var{ptr} \\
        \var{pp} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \var{dstate} \\
        \var{pstate}
      \end{array}
      \right)
      \trans{delpl}{c}
      \left(
      \begin{array}{rcl}
        \var{dstate} \\
        \varUpdate{\var{pstate'}}
      \end{array}
      \right)
    }
\end{equation}$$

**Delegation and Pool Combined Transition Rules**

We now describe a transition system that processes the list of certificates inside a transaction. It is defined recursively from the transition system in Figure 7 above.

Figure 8 defines the types for the delegation certificate sequence transition.


*Certificate Sequence Environment* $$\begin{equation*}
    \DPSEnv =
    \left(
      \begin{array}{rlr}
        \var{slot} & \Slot & \text{slot}\\
        \var{txIx} & \Ix & \text{transaction index}\\
        \var{pp} & \PParams & \text{protocol parameters}\\
        \var{tx} & \Tx & \text{transaction} \\
        \var{acnt} & \Acnt & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ $$\begin{equation*}
    \_ \vdash \_ \trans{delegs}{\_} \_ \in
    \powerset (
    \DPSEnv \times \DPState \times \seqof{\DCert} \times \DPState)
\end{equation*}$$

**Delegation sequence transition type**

Figure 9 defines the transition system recursively. This definition guarantees that a certificate list (and therefore, the transaction carrying it) cannot be processed unless every certificate in it is valid. For example, if a transaction is carrying a certificate that schedules a pool retirement in a past epoch, the whole transaction will be invalid.

- The base case, when the list is empty, is captured by \[eq:delegs-base\]{reference-type="ref+label" reference="eq:delegs-base"}. In the base case we address one final accounting detail not yet covered by the UTxO transition, namely setting the reward account balance to zero for any account that made a withdrawal. There is therefore a precondition that all withdrawals are correct, where correct means that there is a reward account for each stake credential and that the balance matches that of the reward being withdrawn. The base case triggers the following state transformation:

  - Reward accounts are set to zero for each corresponding withdrawal.

- The inductive case, when the list is non-empty, is captured by \[eq:delegs-induct\]{reference-type="ref+label" reference="eq:delegs-induct"}. It constructs a certificate pointer given the current slot and transaction index, calls $\mathsf{DELPL}$ on the next certificate in the list and inductively calls $\mathsf{DELEGS}$ on the rest of the list. The inductive case triggers the following state transformation:

  - The delegation and pool states are (inductively) updated by the results of $\mathsf{DELEGS}$, which is then updated according to $\mathsf{DELPL}$.


$$\begin{equation}
    \label{eq:delegs-base}
    \inference[Seq-delg-base]
    {
      \var{wdrls} \leteq \txwdrls{(\txbody{tx})}
      &
      \var{wdrls} \subseteq \var{rewards}
      \\
      \var{rewards'} \leteq \var{rewards} \unionoverrideRight \{(w, 0) \mid w \in \dom \var{wdrls}\}
    }
    {
      \begin{array}{c}
        \var{slot} \\
        \var{txIx} \\
        \var{pp} \\
        \var{tx} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{c}
        \left(
        \begin{array}{r}
          \var{rewards} \\
          \var{delegations} \\
          \var{ptrs} \\
          \var{fGenDelegs} \\
          \var{genDelegs} \\
          \var{i_{rwd}}
        \end{array}
        \right) \\~\\
        \left(
        \begin{array}{c}
          \var{poolParams} \\
          \var{fPoolParams} \\
          \var{retiring} \\
        \end{array}
        \right) \\
      \end{array}
      \right)
      \trans{delegs}{\epsilon}
      \left(
      \begin{array}{c}
        \left(
        \begin{array}{c}
          \varUpdate{\var{rewards'}} \\
          \var{delegations} \\
          \var{ptrs} \\
          \var{fGenDelegs} \\
          \var{genDelegs} \\
          \var{i_{rwd}}
        \end{array}
        \right) \\~\\
        \left(
        \begin{array}{c}
          \var{poolParams} \\
          \var{fPoolParams} \\
          \var{retiring} \\
        \end{array}
        \right) \\
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
    \label{eq:delegs-induct}
    \inference[Seq-delg-ind]
    {
        {
          \begin{array}{c}
            \var{slot}\\
            \var{txIx}\\
            \var{pp}\\
            \var{tx}\\
            \var{acnt}
          \end{array}
        }
      \vdash
      \var{dpstate}
      \trans{delegs}{\Gamma}
      \var{dpstate'}
    \\~\\~\\
      \var{c}\in\DCertDeleg \Rightarrow \fun{dpool}~{c} \in \dom \var{poolParams} \\
      ptr \leteq (\var{slot},~\var{txIx},~\mathsf{len}~\Gamma) \\~\\
    {
      \begin{array}{c}
        \var{slot}\\
        \var{ptr}\\
        \var{pp}\\
        \var{acnt}
      \end{array}
    }
    \vdash
      \var{dpstate'}
      \trans{\hyperref[fig:rules:delpl]{delpl}}{c}
      \var{dpstate''}
    }
    {
    {
      \begin{array}{c}
        \var{slot}\\
        \var{txIx}\\
        \var{pp}\\
        \var{tx}\\
        \var{acnt}
      \end{array}
    }
    \vdash
      \var{dpstate}
      \trans{delegs}{\Gamma; c}
      \varUpdate{\var{dpstate''}}
    }
\end{equation}$$

**Delegation sequence rules**

The DELEGS rule has two predicate failures:

- In the case of a key delegation certificate, if the pool key is not registered, there is a *DelegateeNotRegistered* failure.

- If the withdrawals mapping of the transaction is not a subset of the rewards mapping of the delegation state, there is a *WithdrawalsNotInRewards* failure.
