# Delegation
We briefly describe the motivation and context for delegation. The full context is contained in [@delegation_design].

Stake is said to be *active* in the blockchain protocol when it is eligible for participation in the leader election. In order for stake to become active, the associated verification stake credential must be registered and its staking rights must be delegated to an active stake pool. Individuals who wish to participate in the protocol can register themselves as a stake pool.

Stake credentials are registered (or deregistered) through the use of registration (or deregistration) certificates. Registered stake credentials are delegated through the use of delegation certificates. Finally, stake pools are registered (or retired) through the use of registration (or retirement) certificates.

Stake pool retirement is handled a bit differently than stake deregistration. Stake credentials are considered inactive as soon as a deregistration certificate is applied to the ledger state. Stake pool retirement certificates, however, specify the epoch in which it will retire.

Delegation requires the following to be tracked by the ledger state: the registered stake credentials, the delegation map from registered stake credentials to stake pools, pointers associated with stake credentials, the registered stake pools and upcoming stake pool retirements. Additionally, the blockchain protocol rewards eligible stake and so we must also include a mapping from active stake credentials to rewards.

Finally, there are two types of delegation certificates available only to the genesis keys. The genesis keys will still be used for update proposals at the beginning of the Shelley era, and so there must be a way to maintain the delegation of these keys to their cold keys. This mapping is also maintained by the delegation state. There is also a mechanism to transfer rewards directly from either the reserves pot or the treasury pot to a reward address. While technically everybody can post such a certificate, the transaction that contains it must be signed by $\mathsf{Quorum}$-many genesis key delegates.

## Delegation Definitions
In 1 we give the delegation primitives. Here we introduce the following primitive datatypes used in delegation:

- $\mathsf{DCertRegKey}$: a stake credential registration certificate.

- $\mathsf{DCertDeRegKey}$: a stake credential de-registration certificate.

- $\mathsf{DCertDeleg}$: a stake credential delegation certificate.

- $\mathsf{DCertRegPool}$: a stake pool registration certificate.

- $\mathsf{DCertRetirePool}$: a stake pool retirement certificate.

- $\mathsf{DCertGen}$: a genesis key delegation certificate.

- $\mathsf{DCertMir}$: a move instantaneous rewards certificate.

- $\mathsf{DCert}$: any one of of the seven certificate types above.

The following derived types are introduced:

- $\mathsf{PoolParam}$ represents the parameters found in a stake pool registration certificate that must be tracked:

  - the pool owners.

  - the pool cost.

  - the pool margin.

  - the pool pledge.

  - the pool reward account.

  - the hash of the VRF verification key.

  - the pool relays.

  - optional pool medata (a url and a hash).

  The idea of pool owners is explained in Section 4.4.4 of [@delegation_design]. The pool cost and margin indicate how much more of the rewards pool leaders get than the members. The pool pledge is explained in Section 5.1 of [@delegation_design]. The pool reward account is where all pool rewards go. The pool relays and metadata url are explained in Sections 3.4.4 and 4.2 of [@delegation_design].

Accessor functions for certificates and pool parameters are also defined, but only the $\mathsf{cwitness}~$ accessor function needs explanation. It does the following:

- For a $\mathsf{DCertRegKey}$ certificate, $\mathsf{cwitness}$ is not defined as stake key registrations do not require a witness.

- For a $\mathsf{DCertDeRegKey}$ certificate, $\mathsf{cwitness}$ returns the hashkey of the key being de-registered.

- For a $\mathsf{DCertDeleg}$ certificate, $\mathsf{cwitness}$ returns the hashkey of the key that is delegating (and not the key to which the stake in being delegated to).

- For a $\mathsf{DCertRegPool}$ certificate, $\mathsf{cwitness}$ returns the hashkey of the key of the pool operator.

- For a $\mathsf{DCertRetirePool}$ certificate, $\mathsf{cwitness}$ returns the hashkey of the key of the pool operator.

- For a $\mathsf{DCertGen}$ certificate, $\mathsf{cwitness}$ returns the hashkey of the genesis key.

- For a $\mathsf{DCertMir}$ certificate, $\mathsf{cwitness}$ is not defined as there is no single core node or genesis key that posts the certificate.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{url} & \mathsf{URL} & \text{a url}\\
      \mathit{mp} & \mathsf{MIRPot} & \text{either $\mathsf{ReservesMIR}$ or $\mathsf{TreasuryMIR}$}\\
    \end{array}
\end{equation*}$$ *Delegation Certificate types* $$\begin{equation*}
  \begin{array}{rcl}
    \mathsf{DCert} &=& \mathsf{DCertRegKey} \uplus \mathsf{DCertDeRegKey} \uplus \mathsf{DCertDeleg} \\
                &\hfill\uplus\;&
                \mathsf{DCertRegPool} \uplus \mathsf{DCertRetirePool} \uplus
                                         \mathsf{DCertGen}\\
           &\hfill\uplus\;& \mathsf{DCertMir}
  \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{lclr}
      \mathsf{PoolMD}
      & ~=~
      & \mathsf{URL} \times \mathsf{PoolMDHash}
      & \text{stake pool metadata} \\
      %
      \mathsf{PoolParam}
      & ~=~
      & \mathbb{P}~\mathsf{KeyHash} \times \mathsf{Coin} \times [0,~1] \times \mathsf{Coin}
      & \text{stake pool parameters} \\
      & & \qquad \times \mathsf{AddrRWD} \times \mathsf{KeyHash}_{vrf} \\
      & & \qquad \mathsf{URL}^{*} \times \mathsf{PoolMD}^?
    \end{array}
\end{equation*}$$ *Certificate Accessor functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{cwitness}~ & \mathsf{DCert}\setminus(\mathsf{DCertRegKey}\cup\mathsf{DCertMir}) \to \mathsf{Credential} & \text{certificate witness} \\
      \mathsf{regCred} & \mathsf{DCertRegKey} \to \mathsf{Credential} & \text{registered credential} \\
      \mathsf{dpool} & \mathsf{DCertDeleg} \to \mathsf{KeyHash}
                                            & \text{pool being delegated to}
      \\
      \mathsf{poolParam} & \mathsf{DCertRegPool} \to \mathsf{PoolParam}
                                            & \text{stake pool}
      \\
      \mathsf{retire} & \mathsf{DCertRetirePool} \to \mathsf{Epoch}
                                            & \text{epoch of pool retirement}
      \\
      \mathsf{genesisDeleg} & \mathsf{DCertGen} \to (\mathsf{KeyHashGen},~\mathsf{KeyHash},~\mathsf{KeyHash}_{vrf})
                                            & \text{genesis delegation}
      \\
      \mathsf{moveRewards} & \mathsf{DCertMir} \to (\mathsf{StakeCredential} \mapsto \mathsf{Coin})
                                            & \text{moved inst. rewards}
      \\
      \mathsf{mirPot} & \mathsf{DCertMir} \to \mathsf{MIRPot} & \text{pot for inst. rewards}
    \end{array}
\end{equation*}$$ *Pool Parameter Accessor functions* $$\begin{equation*}
  \begin{array}{rlr}
    \mathsf{poolOwners} & \mathsf{PoolParam} \to \mathbb{P}~\mathsf{KeyHash}
                     & \text{stake pool owners}
    \\
    \mathsf{poolCost} & \mathsf{PoolParam} \to \mathsf{Coin}
                     & \text{stake pool cost}
    \\
    \mathsf{poolMargin} & \mathsf{PoolParam} \to [0,~1]
                     & \text{stake pool margin}
    \\
    \mathsf{poolPledge} & \mathsf{PoolParam} \to \mathsf{Coin}
                     & \text{stake pool pledge}
    \\
    \mathsf{poolRAcnt} & \mathsf{PoolParam} \to \mathsf{AddrRWD}
                     & \text{stake pool reward account}
    \\
    \mathsf{poolVRF} & \mathsf{PoolParam} \to \mathsf{KeyHash}_{vrf}
                  & \text{stake pool VRF key hash}
    \\
  \end{array}
\end{equation*}$$

**Delegation Definitions**
## Delegation Transitions
In 2 we give the delegation and stake pool state transition types. We define two separate parts of the ledger state.

- $\mathsf{DState}$ keeps track of the delegation state, consisting of:

  - $\mathit{rewards}$ stores the rewards accumulated by stake credentials. These are represented by a finite map from reward addresses to the accumulated rewards.

  - $\mathit{delegations}$ stores the delegation relation, mapping stake credentials to the pool to which is delegates.

  - $\mathit{ptrs}$ maps stake credentials to the position of the registration certificate in the blockchain. This is needed to lookup the stake hashkey of a pointer address.

  - $\mathit{fGenDelegs}$ are the future genesis keys delegations. This variable is needed because genesis keys can only update their delegation with a delay of $\mathsf{StabilityWindow}$ slots after submitting the certificate (this is necessary for header validation, see Section sec:chain)

  - $\mathit{genDelegs}$ maps genesis key hashes to hashes of the cold key delegates.

  - $\mathit{i_{rwd}}$ stores two maps of stake credentials to $\mathsf{Coin}$, which is used for moving instantaneous rewards at the epoch boundary. One map corresponds to rewards taken from the reserves, and the other corresponds to rewards taken from the treasury.

- $\mathsf{PState}$ keeps track of the stake pool information:

  - $\mathit{poolParams}$ tracks the parameters associated with each stake pool, such as their costs and margin.

  - When changes are made to the pool parameters late in an epoch, they are staged in $\mathit{fPoolParams}$. These parameters will be updated by another transition (namely $\mathsf{EPOCH}$) when the next epoch starts.

  - $\mathit{retiring}$ tracks stake pool retirements, using a map from hashkeys to the epoch in which it will retire.

The operational certificates counters $\mathit{cs}$ in the stake pool state are a tool to ensure that blocks containing outdated certificates are rejected. These certificates are part of the block header. For a discussion of why this additional mechanism is needed, see the document [@delegation_design], and for the relevant rules, see Section sec:oper-cert-trans.

The environment for the state transition for $\mathsf{DState}$ contains the current slot number, the index for the current certificate pointer, and the account state. The environment for the state transition for $\mathsf{PState}$ contains the current slot number and the protocol parameters.


*Delegation Types* $$\begin{equation*}
    \begin{array}{rclclr}
      \mathit{stakeCred} & \in &  \mathsf{StakeCredential} & = & (\mathsf{KeyHash}_{stake} \uplus
                                       \mathsf{HashScr}) \\
      \mathit{fGenDelegs} & \in &  \mathsf{FutGenesisDelegation} & =
                       & (\mathsf{Slot}\times\mathsf{KeyHashGen})\mapsto(\mathsf{KeyHash}\times\mathsf{KeyHash}_{vrf}) \\
      \mathit{ir} & \in &  \mathsf{InstantaneousRewards} & =
               & (\mathsf{StakeCredential} \mapsto \mathsf{Coin}) \\
               & & & & ~~~~\times(\mathsf{StakeCredential} \mapsto \mathsf{Coin}) \\
    \end{array}
\end{equation*}$$ *Delegation States* $$\begin{equation*}
    \begin{array}{l}
    \mathsf{DState} =
    \left(\begin{array}{rlr}
            \mathit{rewards} & \mathsf{StakeCredential} \mapsto \mathsf{Coin} & \text{rewards}\\
            \mathit{delegations} & \mathsf{StakeCredential} \mapsto \mathsf{KeyHash}_{pool} & \text{delegations}\\
            \mathit{ptrs} & \mathsf{Ptr} \mapsto \mathsf{StakeCredential} & \text{pointer to stake credential}\\
            \mathit{fGenDelegs} & \mathsf{FutGenesisDelegation} & \text{future genesis key delegations}\\
            \mathit{genDelegs} & \mathsf{GenesisDelegation} & \text{genesis key delegations}\\
            \mathit{i_{rwd}} & \mathsf{InstantaneousRewards} & \text{instantaneous rewards}\\
          \end{array}
      \right)
      \\
    \\
    \mathsf{PState} =
    \left(\begin{array}{rlr}
      \mathit{poolParams} & \mathsf{KeyHash}_{pool} \mapsto \mathsf{PoolParam}
        & \text{registered pools to pool parameters}\\
      \mathit{fPoolParams} & \mathsf{KeyHash}_{pool} \mapsto \mathsf{PoolParam}
        & \text{future pool parameters}\\
      \mathit{retiring} & \mathsf{KeyHash}_{pool} \mapsto \mathsf{Epoch} & \text{retiring stake pools}\\
    \end{array}\right)
    \end{array}
\end{equation*}$$ *Delegation Environment* $$\begin{equation*}
    \mathsf{DEnv} =
    \left(
      \begin{array}{rlr}
        \mathit{slot} & \mathsf{Slot} & \text{slot}\\
        \mathit{ptr} & \mathsf{Ptr} & \text{certificate pointer}\\
        \mathit{acnt} & \mathsf{Acnt} & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ *Pool Environment* $$\begin{equation*}
    \mathsf{PEnv} =
    \left(
      \begin{array}{rlr}
        \mathit{slot} & \mathsf{Slot} & \text{slot}\\
        \mathit{pp} & \mathsf{PParams} & \text{protocol parameters}\\
      \end{array}
    \right)
\end{equation*}$$ *Delegation Transitions* $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{deleg}]{}{\_} \_ \in
      \powerset (\mathsf{DEnv} \times \mathsf{DState} \times \mathsf{DCert} \times \mathsf{DState})
\end{equation*}$$ $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{pool}]{}{\_} \_ \in
    \powerset (\mathsf{PEnv} \times \mathsf{PState} \times \mathsf{DCert} \times \mathsf{PState})
\end{equation*}$$

**Delegation Transitions**
## Delegation Rules
The rules for registering and delegating stake credentials are given in 3. Note that section 5.2 of [@delegation_design] describes how a wallet would help a user choose a stake pool, though these concerns are independent of the ledger rules.

- Stake credential registration is handled by eq:deleg-reg, since it contains the precondition that the certificate has type $\mathsf{DCertRegKey}$. All the equations in $\mathsf{DELEG}$ and $\mathsf{POOL}$ follow this same pattern of matching on certificate type.

  There are also preconditions on registration that the hashkey associated with the certificate witness of the certificate is not already found in the current list of stake credentials or the current reward accounts. We expect that the stake credentials and the reward accounts contain the same key hashes, making one of the checks redundant.

  Registration causes the following state transformation:

  - The key is added to the set of registered stake credentials.

  - A reward account is created for this key, with a starting balance of zero. Note that eq:deleg-reg uses a union override left to add a zero balance reward account.

  - The certificate pointer is mapped to the new stake credential.

- Stake credential deregistration is handled by eq:deleg-dereg. There is a precondition that the credential has been registered and that the reward balance is zero. Deregistration causes the following state transformation:

  - The key is removed from the collection of registered keys.

  - The reward account is removed.

  - The key is removed from the delegation relation.

  - The certificate pointer is removed.

- Stake credential delegation is handled by eq:deleg-deleg. There is a precondition that the key has been registered. Delegation causes the following state transformation:

  - The delegation relation is updated so that the stake credential is delegated to the given stake pool. The use of union override here allows us to use the same rule to perform both an initial delegation and an update to an existing delegation.

- Genesis key delegation is handled by eq:deleg-gen. There is a precondition that the genesis key is already in the mapping $\mathit{genDelegs}$. Genesis delegation causes the following state transformation:

  - The future genesis delegation relation is updated with the new delegate to be adopted in $\mathsf{StabilityWindow}$-many slots.

- Moving instantaneous rewards is handled by eq:deleg-mir-reserves and eq:deleg-mir-treasury. There is a precondition that the current slot is early enough in the current epoch and that the available reserves or treasury are sufficient to pay for the instantaneous rewards.


$$\begin{equation}
\label{eq:deleg-reg}
    \inference[Deleg-Reg]
    {
      \mathit{c}\in\mathsf{DCertRegKey} &
      hk \mathrel{\mathop:}= \mathsf{regCred}~{c} &
      \mathit{hk} \notin \dom \mathit{rewards}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{ptr} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
        \mathit{rewards} \\
        \mathit{delegations} \\
        \mathit{ptrs} \\
        \mathit{fGenDelegs} \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
      \xrightarrow[\mathsf{deleg}]{}{\mathit{c}}
      \left(
      \begin{array}{rcl}
        \mathsf{varUpdate}~\mathit{rewards} & \mathsf{varUpdate}~\union & \varUpdate{\{\mathit{hk} \mapsto 0\}}\\
        \mathit{delegations} \\
        \mathsf{varUpdate}~\mathit{ptrs} & \mathsf{varUpdate}~\union & \varUpdate{\{ptr \mapsto \mathit{hk}\}} \\
        \mathit{fGenDelegs} \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:deleg-dereg}
    \inference[Deleg-Dereg]
    {
      \mathit{c}\in \mathsf{DCertDeRegKey} &
      hk \mathrel{\mathop:}= \mathsf{cwitness}~c &
      \mathit{hk} \mapsto 0 \in \mathit{rewards}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{ptr} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{rewards} \\
        \mathit{delegations} \\
        \mathit{ptrs} \\
        \mathit{fGenDelegs} \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
      \xrightarrow[\mathsf{deleg}]{}{\mathit{c}}
      \left(
      \begin{array}{rcl}
        \varUpdate{\{\mathit{hk}\}} & \varUpdate{\mathbin{\rlap{\lhd}/}} & \mathsf{varUpdate}~\mathit{rewards} \\
        \varUpdate{\{\mathit{hk}\}} & \varUpdate{\mathbin{\rlap{\lhd}/}} & \mathsf{varUpdate}~\mathit{delegations} \\
        \mathsf{varUpdate}~\mathit{ptrs} & \mathsf{varUpdate}~\subtractrange & \varUpdate{\{\mathit{hk}\}} \\
        \mathit{fGenDelegs} \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:deleg-deleg}
    \inference[Deleg-Deleg]
    {
      \mathit{c}\in \mathsf{DCertDeleg} & hk \mathrel{\mathop:}= \mathsf{cwitness}~c & hk \in \dom \mathit{rewards}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{ptr} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{rewards} \\
        \mathit{delegations} \\
        \mathit{ptrs} \\
        \mathit{fGenDelegs} \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
      \xrightarrow[\mathsf{deleg}]{}{c}
      \left(
      \begin{array}{rcl}
        \mathit{rewards} \\
        \mathsf{varUpdate}~\mathit{delegations} & \mathsf{varUpdate}~\unionoverrideRight
                                      & \varUpdate{\{\mathit{hk} \mapsto \dpool c\}} \\
        \mathit{ptrs} \\
        \mathit{fGenDelegs} \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:deleg-gen}
    \inference[Deleg-Gen]
    {
      \mathit{c}\in \mathsf{DCertGen}
      & (\mathit{gkh},~\mathit{vkh},~\mathit{vrf})\mathrel{\mathop:}=\mathsf{genesisDeleg}~{c}
      \\
      s'\mathrel{\mathop:}=\mathit{slot}+\mathsf{StabilityWindow}
      & \mathit{gkh}\in\mathrm{dom}~genDelegs
      \\~\\
      {
        \begin{array}{ l  c  l \neq\mathit{gkh}\}} }
          \mathit{cod} & \mathit{g} & \mathit{genDelegs} \\
          \mathit{fod} & (\underline{\phantom{a}},~\mathit{g}) & \mathit{fGenDelegs}
        \end{array}
      }
      \\~\\
      {
        \begin{array}{ l  c  c  l }}
          \mathit{currentOtherColdKeyHashes} & \mathit{k} & (\mathit{k},~\underline{\phantom{a}}) & \mathit{cod}\\
          \mathit{currentOtherVrfKeyHashes}  & \mathit{v} & (\underline{\phantom{a}},~\mathit{v}) & \mathit{cod}\\
          \mathit{futureOtherColdKeyHashes}  & \mathit{k} & (\mathit{k},~\underline{\phantom{a}}) & \mathit{fod}\\
          \mathit{futureOtherVrfKeyHashes}   & \mathit{v} & (\underline{\phantom{a}},~\mathit{v}) & \mathit{fod}\\
      \end{array}
      }
      \\
      \mathit{vkh}\notin\mathit{currentOtherColdKeyHashes}\union\mathit{futureOtherColdKeyHashes} \\
      \mathit{vrf}\notin\mathit{currentOtherVrfKeyHashes}\union\mathit{futureOtherVrfKeyHashes} \\
      \mathit{fdeleg}\mathrel{\mathop:}=\{(\mathit{s'},~\mathit{gkh}) \mapsto (\mathit{vkh},~\mathit{vrf})\}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{ptr} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{rewards} \\
        \mathit{delegations} \\
        \mathit{ptrs} \\
        \mathit{fGenDelegs} \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
      \xrightarrow[\mathsf{deleg}]{}{c}
      \left(
      \begin{array}{rcl}
        \mathit{rewards} \\
        \mathit{delegations} \\
        \mathit{ptrs} \\
        \mathsf{varUpdate}~\mathit{fGenDelegs}
        & \mathsf{varUpdate}~\unionoverrideRight
        & \mathsf{varUpdate}~fdeleg \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
    }
\end{equation}$$

**Delegation Inference Rules**
$$\begin{equation}
\label{eq:deleg-mir-reserves}
    \inference[Deleg-Mir]
    {
      \mathit{c}\in \mathsf{DCertMir}
      &
      \mathsf{mirPot}~\mathit{c}=\mathsf{ReservesMIR}
      \\
      slot < \mathsf{firstSlot}~((\mathsf{epoch}~slot) + 1) - \mathsf{StabilityWindow}\\
      (\mathit{irReserves},~\mathit{irTreasury})\mathrel{\mathop:}=\mathit{i_{rwd}}
      &
      \mathit{combinedR}\mathrel{\mathop:}=\mathit{irReserves}\unionoverrideRight(\mathsf{moveRewards}~\mathit{c}) \\
      \sum\limits_{\underline{\phantom{a}}\mapsto\mathit{val}\in\mathit{combinedR}} val \leq\mathit{reserves}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{ptr} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{rewards} \\
        \mathit{delegations} \\
        \mathit{ptrs} \\
        \mathit{fGenDelegs} \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
      \xrightarrow[\mathsf{deleg}]{}{c}
      \left(
      \begin{array}{c}
        \mathit{rewards} \\
        \mathit{delegations} \\
        \mathit{ptrs} \\
        \mathit{fGenDelegs}\\
        \mathit{genDelegs} \\
        (\mathsf{varUpdate}~\mathit{combinedR},~\mathit{irTreasury}) \\
      \end{array}
      \right)
    }
\end{equation}$$\
 \
$$\begin{equation}
\label{eq:deleg-mir-treasury}
    \inference[Deleg-Mir]
    {
      \mathit{c}\in \mathsf{DCertMir}
      &
      \mathsf{mirPot}~\mathit{c}=\mathsf{TreasuryMIR}
      \\
      slot < \mathsf{firstSlot}~((\mathsf{epoch}~slot) + 1) - \mathsf{StabilityWindow}\\
      (\mathit{irReserves},~\mathit{irTreasury})\mathrel{\mathop:}=\mathit{i_{rwd}}
      &
      \mathit{combinedT}\mathrel{\mathop:}=\mathit{irTreasury}\unionoverrideRight(\mathsf{moveRewards}~\mathit{c}) \\
      \sum\limits_{\underline{\phantom{a}}\mapsto\mathit{val}\in\mathit{combinedT}} val \leq\mathit{treasury}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{ptr} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{rewards} \\
        \mathit{delegations} \\
        \mathit{ptrs} \\
        \mathit{fGenDelegs} \\
        \mathit{genDelegs} \\
        \mathit{i_{rwd}}
      \end{array}
      \right)
      \xrightarrow[\mathsf{deleg}]{}{c}
      \left(
      \begin{array}{c}
        \mathit{rewards} \\
        \mathit{delegations} \\
        \mathit{ptrs} \\
        \mathit{fGenDelegs}\\
        \mathit{genDelegs} \\
        (\mathit{irReserves},~\mathsf{varUpdate}~\mathit{combinedT}) \\
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

- In the case that a MIR certificate is issued during the last $\mathsf{StabilityWindow}$-many slots of the epoch, there is a *MIRCertificateTooLateinEpoch* failure.

- In the case of a genesis key delegation certificate, if the VRF key is in the range of the genesis delegation mapping, there is a *DuplicateGenesisVRF* failure.

## Stake Pool Rules
The rules for updating the part of the ledger state defining the current stake pools are given in 5. The calculation of stake distribution is described in Section sec:stake-dist-calc.

In the pool rules, the stake pool is identified with the hashkey of the pool operator. For each rule, again, we first check that a given certificate $c$ is of the correct type.

- Stake pool registration is handled by eq:pool-reg. It is required that the pool not be currently registered. Registration causes the following state transformation:

  - The key is added to the set of registered stake pools.

  - The pool's parameters are stored.

- Stake pool parameter updates are handled by eq:pool-rereg. This rule, which also matches on the certificate type $\mathsf{DCertRegPool}$, is distinguished from eq:pool-reg by the requirement that the pool be registered.

  Unlike the initial stake pool registrations, the pool parameters will not change until the next epoch, after stake distribution snapshots are taken. This gives delegators an entire epoch to respond to changes in stake pool parameters. The staging is achieved by adding updates to the mapping $\mathit{fPoolParams}$, which will override $\mathit{poolParam}$ with new values in the $\mathsf{EPOCH}$ transition (see Figure fig:rules:epoch).

  This rule also ends stake pool retirements. Note that $\mathit{poolParams}$ is **not** updated. The registration creation slot does does not change.

- Stake pool retirements are handled by eq:pool-ret. Given a slot number $\mathit{slot}$, the application of this rule requires that the planned retirement epoch $\mathit{e}$ stated in the certificate is in the future, i.e. after $\mathit{cepoch}$ (the epoch of the current slot number in this context) and that it is no more than than $\emax$ epochs after the current one. It is also required that the pool be registered. Note that imposing the $\emax$ constraint on the system is not strictly necessary. However, forcing stake pools to announce their retirement a shorter time in advance will curb the growth of the $\mathit{retiring}$ list in the ledger state.

  The pools scheduled for retirement must be removed from the $\mathit{retiring}$ state variable at the end of the epoch they are scheduled to retire in. This non-signaled transition (triggered, instead, directly by a change of current slot number in the environment), along with all other transitions that take place at the epoch boundary, are described in Section sec:epoch.

  Reregistration causes the following state transformation:

  - The pool is marked to retire on the given epoch. If it was previously retiring, the retirement epoch is now updated.


$$\begin{equation}
\label{eq:pool-reg}
    \inference[Pool-Reg]
    {
      \mathit{c}\in\mathsf{DCertRegPool}
      & \mathit{hk} \mathrel{\mathop:}= \mathsf{cwitness}~c
      & \mathit{pool} \mathrel{\mathop:}= \mathsf{poolParam}~c
      \\
      hk \notin \dom \mathit{poolParams}
      & \mathsf{poolCost}~\mathit{pool}\geq\mathsf{minPoolCost}~\mathit{pp}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{pp} \\
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{poolParams} \\
        \mathit{fPoolParams} \\
        \mathit{retiring} \\
      \end{array}
      \right)
      \xrightarrow[\mathsf{pool}]{}{c}
      \left(
      \begin{array}{rcl}
        \mathsf{varUpdate}~\mathit{poolParams} & \mathsf{varUpdate}~\union
                                    & \varUpdate{\{\mathit{hk} \mapsto \mathit{pool}\}} \\
       \mathit{fPoolParams} \\
       \mathit{retiring} \\
      \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:pool-rereg}
    \inference[Pool-reReg]
    {
      \mathit{c}\in\mathsf{DCertRegPool}
      & \mathit{hk} \mathrel{\mathop:}= \mathsf{cwitness}~c
      & \mathit{pool} \mathrel{\mathop:}= \mathsf{poolParam}~c
      \\
      hk \in \dom \mathit{poolParams}
      & \mathsf{poolCost}~\mathit{pool}\geq\mathsf{minPoolCost}~\mathit{pp}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{pp} \\
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
          \mathit{poolParams} \\
          \mathit{fPoolParams} \\
          \mathit{retiring} \\
        \end{array}
      \right)
      \xrightarrow[\mathsf{pool}]{}{c}
      \left(
        \begin{array}{rcl}
          \mathit{poolParams} \\
          \mathsf{varUpdate}~\mathit{fPoolParams} & \mathsf{varUpdate}~\unionoverrideRight
                                        & \varUpdate{\{\mathit{hk} \mapsto \mathit{pool}\}}\\
          \varUpdate{\{\mathit{hk}\}} & \varUpdate{\mathbin{\rlap{\lhd}/}} & \mathsf{varUpdate}~\mathit{retiring} \\
        \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:pool-ret}
    \inference[Pool-Retire]
    {
    \mathit{c} \in \mathsf{DCertRetirePool}
    & hk \mathrel{\mathop:}= \mathsf{cwitness}~c
    & \mathit{hk} \in \dom \mathit{poolParams} \\
    \mathit{e} \mathrel{\mathop:}= \mathsf{retire}~c
    & \mathit{cepoch} \mathrel{\mathop:}= \mathsf{epoch}~slot
    & \mathit{cepoch} < \mathit{e} \leq \mathit{cepoch} + (\mathsf{emax}~{pp})
  }
  {
    \begin{array}{r}
      \mathit{slot} \\
      \mathit{pp} \\
    \end{array}
    \vdash
    \left(
      \begin{array}{r}
        \mathit{poolParams} \\
        \mathit{fPoolParams} \\
        \mathit{retiring} \\
      \end{array}
    \right)
    \xrightarrow[\mathsf{pool}]{}{c}
    \left(
      \begin{array}{rcl}
        \mathit{poolParams} \\
        \mathit{fPoolParams} \\
        \mathsf{varUpdate}~\mathit{retiring} & \mathsf{varUpdate}~\unionoverrideRight
                                   & \varUpdate{\{\mathit{hk} \mapsto \mathit{e}\}} \\
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
    \mathsf{DPEnv} =
    \left(
      \begin{array}{rlr}
        \mathit{slot} & \mathsf{Slot} & \text{slot}\\
        \mathit{ptr} & \mathsf{Ptr} & \text{certificate pointer}\\
        \mathit{pp} & \mathsf{PParams} & \text{protocol parameters}\\
        \mathit{acnt} & \mathsf{Acnt} & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ *Delegation and Pool Combined State* $$\begin{equation*}
    \mathsf{DPState} =
    \left(
      \begin{array}{rlr}
        \mathit{dstate} & \mathsf{DState} & \text{delegation state}\\
        \mathit{pstate} & \mathsf{PState} & \text{pool state}\\
      \end{array}
    \right)
\end{equation*}$$ *Delegation and Pool Combined Transition* $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{delpl}]{}{\_} \_ \in
      \powerset (
        \mathsf{DPEnv} \times \mathsf{DPState} \times \mathsf{DCert} \times \mathsf{DPState})
\end{equation*}$$

**Delegation and Pool Combined Transition Type**
Figure 7, gives the rules for the combined transition. Note that for any given certificate, at most one of the two rules (eq:delpl-d and eq:delpl-p) will be successful, since the pool certificates are disjoint from the delegation certificates.


*Delegation and Pool Combined Rules* $$\begin{equation}
    \label{eq:delpl-d}
    \inference[Delpl-Deleg]
    {
      &
      {
        \begin{array}{r}
          \mathit{slot} \\
          \mathit{ptr} \\
          \mathit{acnt}
        \end{array}
      }
      \vdash \mathit{dstate} \xrightarrow[\mathsf{\hyperref[fig:delegation-rules]{deleg}}]{}{c} \mathit{dstate'}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{ptr} \\
        \mathit{pp} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{dstate} \\
        \mathit{pstate}
      \end{array}
      \right)
      \xrightarrow[\mathsf{delpl}]{}{c}
      \left(
      \begin{array}{rcl}
        \mathsf{varUpdate}~\mathit{dstate'} \\
        \mathit{pstate}
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
        \mathit{slot} \\
        \mathit{pp} \\
      \end{array}
    }
    \vdash \mathit{pstate} \xrightarrow[\mathsf{\hyperref[fig:pool-rules]{pool}}]{}{c} \mathit{pstate'}
    }
    {
      \begin{array}{r}
        \mathit{slot} \\
        \mathit{ptr} \\
        \mathit{pp} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{dstate} \\
        \mathit{pstate}
      \end{array}
      \right)
      \xrightarrow[\mathsf{delpl}]{}{c}
      \left(
      \begin{array}{rcl}
        \mathit{dstate} \\
        \mathsf{varUpdate}~\mathit{pstate'}
      \end{array}
      \right)
    }
\end{equation}$$

**Delegation and Pool Combined Transition Rules**
We now describe a transition system that processes the list of certificates inside a transaction. It is defined recursively from the transition system in Figure 7 above.

Figure 8 defines the types for the delegation certificate sequence transition.


*Certificate Sequence Environment* $$\begin{equation*}
    \mathsf{DPSEnv} =
    \left(
      \begin{array}{rlr}
        \mathit{slot} & \mathsf{Slot} & \text{slot}\\
        \mathit{txIx} & \mathsf{Ix} & \text{transaction index}\\
        \mathit{pp} & \mathsf{PParams} & \text{protocol parameters}\\
        \mathit{tx} & \mathsf{Tx} & \text{transaction} \\
        \mathit{acnt} & \mathsf{Acnt} & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{delegs}]{}{\_} \_ \in
    \powerset (
    \mathsf{DPSEnv} \times \mathsf{DPState} \times \mathsf{DCert}^{*} \times \mathsf{DPState})
\end{equation*}$$

**Delegation sequence transition type**
Figure 9 defines the transition system recursively. This definition guarantees that a certificate list (and therefore, the transaction carrying it) cannot be processed unless every certificate in it is valid. For example, if a transaction is carrying a certificate that schedules a pool retirement in a past epoch, the whole transaction will be invalid.

- The base case, when the list is empty, is captured by eq:delegs-base. In the base case we address one final accounting detail not yet covered by the UTxO transition, namely setting the reward account balance to zero for any account that made a withdrawal. There is therefore a precondition that all withdrawals are correct, where correct means that there is a reward account for each stake credential and that the balance matches that of the reward being withdrawn. The base case triggers the following state transformation:

  - Reward accounts are set to zero for each corresponding withdrawal.

- The inductive case, when the list is non-empty, is captured by eq:delegs-induct. It constructs a certificate pointer given the current slot and transaction index, calls $\mathsf{DELPL}$ on the next certificate in the list and inductively calls $\mathsf{DELEGS}$ on the rest of the list. The inductive case triggers the following state transformation:

  - The delegation and pool states are (inductively) updated by the results of $\mathsf{DELEGS}$, which is then updated according to $\mathsf{DELPL}$.


$$\begin{equation}
    \label{eq:delegs-base}
    \inference[Seq-delg-base]
    {
      \mathit{wdrls} \mathrel{\mathop:}= \mathsf{txwdrls}~(\mathsf{txbody}~tx)
      &
      \mathit{wdrls} \subseteq \mathit{rewards}
      \\
      \mathit{rewards'} \mathrel{\mathop:}= \mathit{rewards} \unionoverrideRight \{(w, 0) \mid w \in \dom \mathit{wdrls}\}
    }
    {
      \begin{array}{c}
        \mathit{slot} \\
        \mathit{txIx} \\
        \mathit{pp} \\
        \mathit{tx} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
      \begin{array}{c}
        \left(
        \begin{array}{r}
          \mathit{rewards} \\
          \mathit{delegations} \\
          \mathit{ptrs} \\
          \mathit{fGenDelegs} \\
          \mathit{genDelegs} \\
          \mathit{i_{rwd}}
        \end{array}
        \right) \\~\\
        \left(
        \begin{array}{c}
          \mathit{poolParams} \\
          \mathit{fPoolParams} \\
          \mathit{retiring} \\
        \end{array}
        \right) \\
      \end{array}
      \right)
      \xrightarrow[\mathsf{delegs}]{}{\epsilon}
      \left(
      \begin{array}{c}
        \left(
        \begin{array}{c}
          \mathsf{varUpdate}~\mathit{rewards'} \\
          \mathit{delegations} \\
          \mathit{ptrs} \\
          \mathit{fGenDelegs} \\
          \mathit{genDelegs} \\
          \mathit{i_{rwd}}
        \end{array}
        \right) \\~\\
        \left(
        \begin{array}{c}
          \mathit{poolParams} \\
          \mathit{fPoolParams} \\
          \mathit{retiring} \\
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
            \mathit{slot}\\
            \mathit{txIx}\\
            \mathit{pp}\\
            \mathit{tx}\\
            \mathit{acnt}
          \end{array}
        }
      \vdash
      \mathit{dpstate}
      \xrightarrow[\mathsf{delegs}]{}{\Gamma}
      \mathit{dpstate'}
    \\~\\~\\
      \mathit{c}\in\mathsf{DCertDeleg} \Rightarrow \mathsf{dpool}~{c} \in \dom \mathit{poolParams} \\
      ptr \mathrel{\mathop:}= (\mathit{slot},~\mathit{txIx},~\mathsf{len}~\Gamma) \\~\\
    {
      \begin{array}{c}
        \mathit{slot}\\
        \mathit{ptr}\\
        \mathit{pp}\\
        \mathit{acnt}
      \end{array}
    }
    \vdash
      \mathit{dpstate'}
      \xrightarrow[\mathsf{\hyperref[fig:rules:delpl]{delpl}}]{}{c}
      \mathit{dpstate''}
    }
    {
    {
      \begin{array}{c}
        \mathit{slot}\\
        \mathit{txIx}\\
        \mathit{pp}\\
        \mathit{tx}\\
        \mathit{acnt}
      \end{array}
    }
    \vdash
      \mathit{dpstate}
      \xrightarrow[\mathsf{delegs}]{}{\Gamma; c}
      \mathsf{varUpdate}~\mathit{dpstate''}
    }
\end{equation}$$

**Delegation sequence rules**
The DELEGS rule has two predicate failures:

- In the case of a key delegation certificate, if the pool key is not registered, there is a *DelegateeNotRegistered* failure.

- If the withdrawals mapping of the transaction is not a subset of the rewards mapping of the delegation state, there is a *WithdrawalsNotInRewards* failure.
