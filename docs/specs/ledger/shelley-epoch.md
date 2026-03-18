# Rewards and the Epoch Boundary
This chapter introduces the epoch boundary transition system and the related reward calculation.

The transition system is defined in Section 1.7, and involves taking stake distribution snapshots (Sections 1.3 and 1.4), retiring stake pools (Section 1.5), and performing protocol updates (Section 1.6). The reward calculation, defined in Sections 1.8 and 1.9, distributes the leader election rewards.

## Overview of the Reward Calculation
The rewards for a given epoch $e_i$ involve the two epochs surrounding it. In particular, the stake distribution will come from the previous epoch and the rewards will be calculated in the following epoch. More concretely:

(A) A stake distribution snapshot is taken at the begining of epoch $e_{i-1}$.

(B) The randomness for leader election is fixed during epoch $e_{i-1}$

(C) Epoch $e_{i}$ begins.

(D) Epoch $e_{i}$ ends. A snapshot is taken of the stake pool performance during epoch $e_{i}$. A snapshot is also taken of the fee pot and the decayed deposit values.

(E) The snapshots from (D) are stable and the reward calculation can begin.

(F) The reward calculation is finished and an update to the ledger state is ready to be applied.

(G) Rewards are given out.

We must therefore store the last three stake distributions. The mnemonic "mark, set, go" will be used to keep track of the snapshots, where the label "mark" refers to the most recent snapshot, and "go" refers to the snapshot that is ready to be used in the reward calculation. In the above diagram, the snapshot taken at (A) is labeled "mark" during epoch $e_{i-1}$, "set" during epoch $e_i$ and "go" during epoch $e_{i+1}$. At (G) the snapshot taken at (A) is no longer needed and will be discarded.

The two main transition systems in this section are:

- The transition system named $\mathsf{EPOCH}$, which is defined in Section 1.7, covers what happens at the epoch boundary, such as at (A), (C), (D) and (G).

- The transition named $\mathsf{RUPD}$, which is defined in Section sec:reward-update-trans, covers the reward calculation that happens between (E) and (F).

::: note
Between time D and E we are concerned with chain growth and stability. Therefore this duration can be stated as 2k blocks (to state it in slots requires details about the particular version of the Ouroboros protocol). The duration between F and G is also 2k blocks. Between E and F a single honest block is enough to ensure a random nonce.

## Helper Functions and Accounting Fields
Figure 1 defines four helper functions needed throughout the rest of the section.

- The function $\fun{obligation}$ calculates the the minimal amount of coin needed to pay out all deposit refunds.

- The function $\fun{poolStake}$ filters the stake distribution to one stake pool.


*Total possible refunds* $$\begin{align*}
    & \fun{obligation} \in \PParams \to (\StakeCredential \mapsto \Coin)
    \to (\KeyHash_{pool}\mapsto\PoolParam) \to \Coin \\
    & \fun{obligation}~ \var{pp}~ \var{rewards}~ \var{poolParams} = \\
    & ~~~~~
    (\fun{keyDeposit}~\var{pp}) \cdot|\var{rewards}| +
    (\fun{poolDeposit}~\var{pp}) \cdot|\var{poolParams}| \\
\end{align*}$$ *Filter Stake to one Pool* $$\begin{align*}
      & \fun{poolStake} \in \KeyHash_{pool} \to (\KeyHash_{stake} \mapsto \KeyHash_{pool})
        \to \type{Stake}\to \type{Stake}\\
      & \fun{poolStake}~ \var{hk}~ \var{delegs}~ \var{stake} =
        \dom{(\var{delegs}\restrictrange\{hk\})\restrictdom\var{stake}}
\end{align*}$$

**Helper Functions used in Rewards and Epoch Boundary**
The Figure 2 lists the accounting fields, denoted by $\Acnt$, which will be used throughout this section. It consists of:

- The value $\var{treasury}$ tracks the amount of coin currently stored in the treasury. Initially there will be no way to remove these funds.

- The value $\var{reserves}$ tracks the amount of coin currently stored in the reserves. This pot is used to pay rewards.

More will be said about the general accounting system in Section 1.9.


*Accounting Fields* $$\begin{equation*}
    \Acnt =
    \left(
      \begin{array}{rll}
        \var{treasury} & \Coin & \text{treasury pot}\\
        \var{reserves} & \Coin & \text{reserve pot}\\
      \end{array}
    \right)
\end{equation*}$$

**Accounting fields**
## Stake Distribution Calculation
This section defines the stake distribution calculations. Figure 3 introduces three new derived types:

- $\type{BlocksMade}$ represents the number of blocks each stake pool produced during an epoch.

- $\type{Stake}$ represents the amount of stake (in $\type{Coin}$) controlled by each stake pool.


*Derived types* $$\begin{equation*}
    \begin{array}{rllr}
      \var{blocks}
      & \type{BlocksMade}
      & \KeyHash_{pool} \mapsto \N
      & \text{blocks made by stake pools} \\
      \var{stake}
      & \type{Stake}
      & \Credential \mapsto \Coin
      & \text{stake} \\
    \end{array}
\end{equation*}$$

**Epoch definitions**
The stake distribution calculation is given in Figure 4.

- $\fun{aggregate_{+}}$ takes a relation on $A\times B$, where $B$ is any monoid $(B,+,e)$ and returns a map from each $a\in A$ to the "sum" (using the monoidal $+$ operation) of all $b\in B$ such that $(a, b)\in A\times B$.

- $\fun{stakeDistr}$ uses the $\fun{aggregate_{+}}$ function and several relations to compute the stake distribution, mapping each hashkey to the total coin under its control. Keys that are not both registered and delegated are filtered out. The relation passed to $\fun{aggregate_{+}}$ is made up of:

  - $\fun{stakeCred_b}^{-1}$, relating credentials to (base) addresses

  - $\left(\fun{addrPtr}\circ\var{ptr}\right)^{-1}$, relating credentials to (pointer) addresses

  - $\range{utxo}$, relating addresses to coins

  - $\fun{stakeCred_r}^{-1}\circ\var{rewards}$, relating (reward) addresses to coins

  The notation for relations is explained in Section sec:notation-shelley.


*Aggregation (for a monoid B)* $$\begin{align*}
      & \fun{aggregate_{+}} \in \powerset{(A \times B)} \to (A\mapsto B) \\
      & \fun{aggregate_{+}}~\var{R} = \left\{a\mapsto \sum_{(a,b)\in\var{R}}b
          ~\mid~a\in\dom\var{R}\right\} \\
\end{align*}$$ *Stake Distribution (using functions and maps as relations)* $$\begin{align*}
      & \fun{stakeDistr} \in \UTxO \to \DState \to \PState \to \type{Snapshot}\\
      & \fun{stakeDistr}~{utxo}~{dstate}~{pstate} = \\
      & ~~~~ \big((\dom{\var{activeDelegs}})
      \restrictdom\left(\fun{aggregate_{+}}~\var{stakeRelation}\right),
    ~\var{delegations},~\var{poolParams}\big)\\
      & \where \\
      & ~~~~ (~\var{rewards},~\var{delegations},~\var{ptrs},~\wcard,~\wcard,~\wcard)
        = \var{dstate} \\
      & ~~~~ (~\var{poolParams}~\wcard,~\wcard) = \var{pstate} \\
      & ~~~~ \var{stakeRelation} = \left(
        \left(\fun{stakeCred_b}^{-1}\cup\left(\fun{addrPtr}\circ\var{ptr}\right)^{-1}\right)
        \circ\left(\range{\var{utxo}}\right)
        \right)
        \cup \left(\fun{stakeCred_r}^{-1}\circ\var{rewards}\right) \\
      & ~~~~ \var{activeDelegs} =
               (\dom{rewards}) \restrictdom \var{delegations} \restrictrange (\dom{poolParams}) \\
\end{align*}$$

**Stake Distribution Function**
## Snapshot Transition
The state transition types for stake distribution snapshots are given in Figure 5. Each snapshot consists of:

- $\var{stake}$, a stake distribution, which is defined in Figure 3 as a mapping of credentials to coin.

- $\var{delegations}$, a delegation map, mapping credentials to stake pools.

- $\var{poolParameters}$, storing the pool parameters of each stake pool.

The type $\type{\type{Snapshots}}$ contains the information needing to be saved on the epoch boundary:

- $\var{pstake_{mark}}$, $\var{pstake_{set}}$ and $\var{pstake_{go}}$ are the three snapshots as explained in Section 1.1.

- $\var{feeSS}$ stores the fees which are added to the reward pot during the next reward update calculation, which is then subtracted from the fee pot on the epoch boundary.


*Snapshots* $$\begin{equation*}
    \type{Snapshot}=
    \left(
      \begin{array}{rll}
        \var{stake} & \type{Stake}& \text{stake distribution}\\
        \var{delegations} & \Credential\mapsto\KeyHash_{pool}
                          & \text{stake delegations}\\
        \var{poolParameters} & \KeyHash_{pool} \mapsto \PoolParam & \text{pool parameters }\\
      \end{array}
    \right)
\end{equation*}$$

$$\begin{equation*}
    \type{Snapshots}=
    \left(
      \begin{array}{rll}
        \var{pstake_{mark}} & \type{Snapshot}& \text{newest stake}\\
        \var{pstake_{set}}  & \type{Snapshot}& \text{middle stake}\\
        \var{pstake_{go}}   & \type{Snapshot}& \text{oldest stake}\\
        \var{feeSS} & \Coin & \text{fee snapshot}\\
      \end{array}
    \right)
\end{equation*}$$ *Snapshot transitions* $$\begin{equation*}
    \_ \vdash
    \var{\_} \trans{snap}{} \var{\_}
    \subseteq \powerset (\LState \times \type{Snapshots}\times \type{Snapshots})
\end{equation*}$$

**Snapshot transition-system types**
The snapshot transition rule is given in Figure 6. This transition has no preconditions and results in the following state change:

- The oldest snapshot is replaced with the penultimate one.

- The penultimate snapshot is replaced with the newest one.

- The newest snapshot is replaced with one just calculated.

- The current fees pot is stored in $\var{feeSS}$. Note that this value will not change during the epoch, unlike the $\var{fees}$ value in the UTxO state.


$$\begin{equation}
\label{eq:snapshot}
    \inference[Snapshot]
    {
      {
      \begin{array}{rl}
        ((\var{utxo},~\wcard,\var{fees},~\wcard),~(\var{dstate},~\var{pstate})) & \var{lstate} \\
        \var{stake} & \fun{stakeDistr}~ \var{utxo}~ \var{dstate}~ \var{pstate} \\
      \end{array}
      }
    }
    {
      \begin{array}{r}
        \var{lstate} \\
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
          \var{pstake_{mark}}\\
          \var{pstake_{set}}\\
          \var{pstake_{go}}\\
          \var{feeSS} \\
        \end{array}
      \right)
      \trans{snap}{}
      \left(
        \begin{array}{r}
          \varUpdate{\var{stake}} \\
          \varUpdate{\var{pstake_{mark}}} \\
          \varUpdate{\var{pstake_{set}}} \\
          \varUpdate{\var{fees}} \\
        \end{array}
      \right)
    }
\end{equation}$$

**Snapshot Inference Rule**
## Pool Reaping Transition
Figure 7 defines the types for the pool reap transition, which is responsible for removing pools slated for retirement in the given epoch.


*Pool Reap State* $$\begin{equation*}
    \type{PlReapState}=
    \left(
      \begin{array}{rll}
        \var{utxoSt} & \UTxOState & \text{utxo state}\\
        \var{acnt} & \Acnt & \text{accounting}\\
        \var{dstate} & \DState & \text{delegation state}\\
        \var{pstate} & \PState & \text{pool state}\\
      \end{array}
    \right)
\end{equation*}$$ *Pool Reap transitions* $$\begin{equation*}
    \_ \vdash \_ \trans{poolreap}{\_} \_ \in
    \powerset (\PParams \times \type{PlReapState}\times \Epoch \times \type{PlReapState})
\end{equation*}$$

**Pool Reap Transition**
The pool-reap transition rule is given in Figure 8. This transition has no preconditions and results in the following state change:

- For each retiring pool, the refund for the pool registration deposit is added to the pool's registered reward account, provided the reward account is still registered.

- The sum of all the refunds attached to unregistered reward accounts are added to the treasury.

- The deposit pool is reduced by the amount of claimed and unclaimed refunds.

- Any delegation to a retiring pool is removed.

- Each retiring pool is removed from all four maps in the pool state.


$$\begin{equation}
\label{eq:pool-reap}
    \inference[Pool-Reap]
    {
      {
      \begin{array}{rl}
        \var{retired} & \dom{(\var{retiring}^{-1}~\var{e})} \\
        \var{pr} & \left\{
                   \var{hk}\mapsto(\fun{poolDeposit}~\var{pp})
                     \mid
                     \var{hk}\in\var{retired}
                   \right\}\\
        \var{rewardAcnts}
                 & \{\var{hk}\mapsto \fun{poolRAcnt}~\var{pool} \mid
                   \var{hk}\mapsto\var{pool} \in \var{retired}\restrictdom\var{poolParams} \} \\
        \var{rewardAcnts'} & \left\{
                        a \mapsto c
                        \mathrel{\Bigg|}
                        \begin{array}{rl}
                          \var{hk} \mapsto c & \var{pr}, \\
                          \var{hk}\mapsto\var{a} & \var{rewardAcnts} \\
                        \end{array}
                      \right\} \\
        \var{refunds} & \dom{rewards}\restrictdom\var{rewardAcnts'} \\
        \var{mRefunds} & \dom{rewards}\subtractdom\var{rewardAcnts'} \\
        \var{refunded} & \sum\limits_{\wcard\mapsto c\in\var{refunds}} c \\
        \var{unclaimed} & \sum\limits_{\wcard\mapsto c\in\var{mRefunds}} c \\
      \end{array}
      }
    }
    {
      \var{pp}
      \vdash
      \left(
        \begin{array}{r}
          \var{utxo} \\
          \var{deposits} \\
          \var{fees} \\
          \var{ups} \\
          ~ \\
          \var{treasury} \\
          \var{reserves} \\
          ~ \\
          \var{rewards} \\
          \var{delegations} \\
          \var{ptrs} \\
          \var{genDelegs} \\
          \var{fGenDelegs} \\
          \var{i_{rwd}} \\
          ~ \\
          \var{poolParams} \\
          \var{fPoolParams} \\
          \var{retiring} \\
        \end{array}
      \right)
      \trans{poolreap}{e}
      \left(
        \begin{array}{rcl}
          \var{utxo} \\
          \varUpdate{\var{deposits}}
          & \varUpdate{-}
          & \varUpdate{(\var{unclaimed} + \var{refunded})} \\
          \var{fees} \\
          \var{ups} \\
          ~ \\
          \varUpdate{\var{treasury}} & \varUpdate{+} & \varUpdate{\var{unclaimed}} \\
          \var{reserves} \\
          ~ \\
          \varUpdate{\var{rewards}} & \varUpdate{\unionoverridePlus} & \varUpdate{\var{refunds}} \\
          \varUpdate{\var{delegations}} & \varUpdate{\subtractrange} & \varUpdate{\var{retired}} \\
          \var{ptrs} \\
          \var{genDelegs} \\
          \var{fGenDelegs} \\
          \var{i_{rwd}}\\
          ~ \\
          \varUpdate{\var{retired}} & \varUpdate{\subtractdom} & \varUpdate{\var{poolParams}} \\
          \varUpdate{\var{retired}} & \varUpdate{\subtractdom} & \varUpdate{\var{fPoolParams}} \\
          \varUpdate{\var{retired}} & \varUpdate{\subtractdom} & \varUpdate{\var{retiring}} \\
        \end{array}
      \right)
    }
\end{equation}$$

**Pool Reap Inference Rule**
## Protocol Parameters Update Transition
Finally, reaching the epoch boundary may trigger a change in the protocol parameters. The protocol parameters environment consists of the delegation and pool states, and the signal is an optional new collection of protocol parameters The state change is a change of the $\UTxOState$, the $\Acnt$ states and the current $\PParams$. The type of this state transition is given in Figure 9.


*New Proto Param environment* $$\begin{equation*}
    \type{NewPParamEnv}=
    \left(
      \begin{array}{rll}
        \var{dstate} & \DState & \text{delegation state}\\
        \var{pstate} & \PState & \text{pool state}\\
      \end{array}
    \right)
\end{equation*}$$ *New Proto Param States* $$\begin{equation*}
    \type{NewPParamState}=
    \left(
      \begin{array}{rll}
        \var{utxoSt} & \UTxOState & \text{utxo state}\\
        \var{acnt} & \Acnt & \text{accounting}\\
        \var{pp} & \PParams & \text{current protocol parameters}\\
      \end{array}
    \right)
\end{equation*}$$ *New Proto Param transitions* $$\begin{equation*}
    \_ \vdash
    \var{\_} \trans{newpp}{\_} \var{\_}
    \subseteq \powerset (\type{NewPParamEnv}\times \type{NewPParamState}\times \PParams^? \times \type{NewPParamState})
\end{equation*}$$

*Helper Functions* $$\begin{align*}
      & \fun{updatePpup} \in \UTxOState \to \PParams \to \UTxOState\\
      & \fun{updatePpup}~\var{utxoSt}~\var{pp} =
      \begin{cases}
        (\var{utxo},\var{deposits},\var{fees},(\var{fpup},~\emptyset))
        &
        \var{canFollow}
        \\
        (\var{utxo},\var{deposits},\var{fees},(\emptyset,~\emptyset))
        &
        \text{otherwise} \\
      \end{cases}\\
      & ~~~\where \\
      & ~~~~~~~\var{canFollow} =
        \forall\var{ps}\in\range{pup},~
        \var{pv}\mapsto\var{v}\in\var{ps}\implies\fun{pvCanFollow}~(\fun{pv}~\var{pp})~\var{v}
        \\
      & ~~~~~~~(\var{utxo},\var{deposits},\var{fees},(\var{pup},~\var{fpup})) = \var{utxoSt} \\
\end{align*}$$

**New Proto Param transition-system types**
Figure 10 defines the new protocol parameter transition. The transition has two rules, depending on whether or not the new protocol parameters meet some requirements. In particular, we require that the new parameters would not incur a debt of the system that can not be covered by the reserves, and that the max block size is greater than the sum of the max transaction size and the max header size. If the requirements are met, the new protocol parameters are accepted, the proposal is reset, and the reserves are adjusted to account for changes in the deposits. Otherwise, the only change is that the proposal is reset.

The $\mathsf{NEWPP}$ rule also cleans up the protocol parameter update proposals, by calling $\fun{updatePpup}$ on the UTxO state. The $\fun{updatePpup}$ sets the protocol parameter updates to the future protocol parameter updates provided the protocol versions all can follow from the version given in the protocol parameters, or the emptyset otherwise. In any case, the future protocol parameters update proposals are set to the empty set. If new protocol parameters are being adopted, then these is the value given to $\fun{updatePpup}$, otherwise the old parameters are given.

Regarding adjusting the reserves for changes in the deposits, one of three things happens:

- If the new protocol parameters mean that **fewer** funds are required in the deposit pot to cover all possible refunds, then the excess is moved to the reserves.

- If the new protocol parameters mean that **more** funds are required in the deposit pot to cover all possible refunds and the difference is **less** than the reserve pot, then funds are moved from the reserve pot to cover the difference.

- If the new protocol parameters mean that **more** funds are required in the deposit pot to cover all possible refunds and the difference is **more** than the reserve pot, then Rule eq:new-pc-denied meets the precondition and the only change of state is that the update proposals are reset.

Note that here, unlike most of the inference rules in this document, the $\var{utxoSt'}$ and the $\var{acnt'}$ do not come from valid UTxO or accounts transitions in the antecedent. We simply define the consequent transition using these directly (instead of listing all the fields in both states in the consequent transition). It is done this way here for ease of reading.


$$\begin{equation}
\label{eq:new-pc-accepted}
    \hspace{-0.3cm}
    \inference[New-Proto-Param-Accept]
    {
      \var{pp_{new}}\neq\Nothing \\~\\
      {\begin{array}{rcl}
         (\var{utxo},~\var{deposits},~\var{fees},~\var{pup}) & \leteq & \var{utxoSt} \\
         \var{(\var{rewards},~\wcard,~\wcard,~\wcard,~\wcard,~\var{i_{rwd}})} &
         \leteq & \var{dstate}\\
         \var{(\var{poolParams},~\wcard,~\wcard)} & \leteq & \var{pstate}\\
         \var{oblg_{cur}} & \leteq & \fun{obligation}~ \var{pp}~ \var{rewards}~ \var{poolParams} \\
         \var{oblg_{new}} & \leteq & \fun{obligation}~ \var{pp_{new}}~ \var{rewards}~ \var{poolParams} \\
         \var{diff} & \leteq & \var{oblg_{cur}} - \var{oblg_{new}}\\
      \end{array}}
      \\~\\~\\
      \var{oblg_{cur}} = \var{deposits} \\
      \var{reserves} + \var{diff} \geq \sum\limits_{\wcard\mapsto\var{val}\in\var{i_{rwd}}} val \\
      \fun{maxTxSize}~\var{pp_{new}} + \fun{maxHeaderSize}~\var{pp_{new}} <
        \fun{maxBlockSize}~\var{pp_{new}}
      \\~\\
        \var{utxoSt'} \leteq
        \left(\var{utxo},~\varUpdate{oblg_{new}},~\var{fees},~\var{pup}\right)
      \\
      \var{utxoSt''} \leteq \fun{updatePpup}~\var{utxoSt'}~\var{pp_{new}}
      \\~\\
      (\var{treasury},~\var{reserves})\leteq \var{acnt} \\
      \var{acnt'} \leteq (\var{treasury},~\varUpdate{reserves + diff}) \\
    }
    {
      \begin{array}{l}
        \var{dstate}\\
        \var{pstate}\\
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
          \var{utxoSt} \\
          \var{acnt} \\
          \var{pp}
        \end{array}
      \right)
      \trans{newpp}{\var{pp_{new}}}
      \left(
        \begin{array}{rcl}
          \varUpdate{utxoSt''}\\
          \varUpdate{acnt'} \\
          \varUpdate{\var{pp_{new}}} \\
        \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:new-pc-denied}
    \inference[New-Proto-Param-Denied]
    {
      \left({\begin{array}{c}
            \var{pp_{new}}=\Nothing \\
        \lor \\
        \var{reserves} + \var{diff} < \sum\limits_{\wcard\mapsto\var{val}\in\var{i_{rwd}}} val\\
        \lor \\
        \fun{maxTxSize}~\var{pp_{new}} + \fun{maxHeaderSize}~\var{pp_{new}} \geq
          \fun{maxBlockSize}~\var{pp_{new}}
      \end{array}}\right)
      \\~\\~\\
      {\begin{array}{rcl}
         (\var{utxo},~\var{deposits},~\var{fees},~\var{pup}) & \leteq & \var{utxoSt} \\
          \var{(\var{rewards},~\wcard,~\wcard,~\wcard,~\wcard,~\var{i_{rwd}})} &
          \leteq & \var{dstate}\\
         \var{(\var{poolParams},~\wcard,~\wcard)} & \leteq & \var{pstate}\\
          \var{oblg_{cur}} & \leteq & \fun{obligation}~ \var{pp}~ \var{rewards}~ \var{poolParams} \\
          \var{oblg_{new}} & \leteq & \fun{obligation}~ \var{pp_{new}}~ \var{rewards}~ \var{poolParams} \\
         \var{diff} & \leteq & \var{oblg_{cur}} - \var{oblg_{new}}
      \end{array}}
      \\~\\~\\
      \var{utxoSt'} \leteq \fun{updatePpup}~\var{utxoSt}~\var{pp} \\
    }
    {
      \begin{array}{l}
        \var{dstate}\\
        \var{pstate}\\
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
          \var{utxoSt} \\
          \var{acnt} \\
          \var{pp}
        \end{array}
      \right)
      \trans{newpp}{\var{pp_{new}}}
      \left(
        \begin{array}{rcl}
          \varUpdate{utxoSt'}\\
          \var{acnt} \\
          \var{pp}
        \end{array}
      \right)
    }
\end{equation}$$

**New Proto Param Inference Rule**
## Complete Epoch Boundary Transition
Finally, it is possible to define the complete epoch boundary transition type, which is defined in Figure 11. The transition has no evironment. The state is made up of the the accounting state, the snapshots, the ledger state and the protocol parameters. The transition uses a helper function $\fun{votedValue}$ which returns the consensus value of update proposals in the event that consensus is met. **Note that** $\fun{votedValue}$ **is only well-defined if** $\var{quorum}$ **is greater than half the number of core nodes, i.e.** $\Quorum > |\var{genDelegs}|/2$ **.**


*Epoch States* $$\begin{equation*}
    \type{EpochState}=
    \left(
      \begin{array}{rll}
        \var{acnt} & \Acnt & \text{accounting}\\
        \var{ss} & \type{Snapshots}& \text{snapshots}\\
        \var{ls} & \LState & \text{ledger state}\\
        \var{prevPp} & \PParams & \text{previous protocol parameters}\\
        \var{pp} & \PParams & \text{protocol parameters}\\
      \end{array}
    \right)
\end{equation*}$$ *Epoch transitions* $$\begin{equation*}
    \vdash
    \var{\_} \trans{epoch}{\_} \var{\_}
    \subseteq \powerset (\type{EpochState}\times \Epoch \times \type{EpochState})
\end{equation*}$$ *Accessor Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \fun{getIR} & \type{EpochState}\to (\StakeCredential \mapsto \Coin)
                  & \text{get instantaneous rewards} \\
    \end{array}
\end{equation*}$$ *Helper Functions* $$\begin{align*}
      & \fun{votedValue} \in (\KeyHashGen\mapsto\PParamsUpdate) \to \PParams \to \N \to \PParamsUpdate^?\\
      & \fun{votedValue}~\var{pup}~\var{pp}~\var{quorum} =
      \begin{cases}
        \var{pp}\unionoverrideRight\var{p}
          & \exists! p\in\range{pup}~(|pup\restrictrange p|\geq \var{quorum}) \\
        \Nothing & \text{otherwise} \\
      \end{cases}
\end{align*}$$

**Epoch transition-system types**
The epoch transition rule calls $\mathsf{SNAP}$, $\mathsf{POOLREAP}$ and $\mathsf{NEWPP}$ in sequence. It also stores the previous protocol parameters in $\var{prevPp}$. The previous protocol parameters will be used for the reward calculation in the upcoming epoch, note that they correspond to the epoch for which the rewards are being calculated. Additionally, this transition also adopts the pool parameters $\var{fPoolParams}$ corresponding to the pool re-registration certificates which we submitted late in the ending epoch. The ordering of these rules is important. The stake pools which will be updated by $\var{fPoolParams}$ or reaped during the $\mathsf{POOLREAP}$ transition must still be a part of the new snapshot, and so $\mathsf{SNAP}$ must occur before these two actions. Moreover, $\mathsf{SNAP}$ sets the deposit pot equal to current obligation, which is a property that is preserved by $\mathsf{POOLREAP}$ and which is necessary for the preservation of Ada property in the $\mathsf{NEWPP}$ transition.


$$\begin{equation}
\label{eq:epoch}
    \inference[Epoch]
    {
      {
        \begin{array}{r}
          \var{lstate} \\
        \end{array}
      }
      \vdash
      { \var{ss} }
      \trans{\hyperref[fig:rules:snapshot]{snap}}{}
      { \var{ss'} }
      \\~\\
      (\var{utxoSt},~(\var{dstate},~\var{pstate}))\leteq\var{ls} \\
      (\var{poolParams},~\var{fPoolParams},~\var{retiring})\leteq\var{pstate}
      \\
      \var{pstate'}\leteq(\var{poolParams}\unionoverrideRight\var{fPoolParams},
      ~\emptyset,~\var{retiring})
      \\~\\~\\
      \var{pp}
      \vdash
      \left(
        {
          \begin{array}{r}
            \var{utxoSt} \\
            \var{acnt} \\
            \var{dstate} \\
            \var{pstate'} \\
          \end{array}
        }
      \right)
      \trans{\hyperref[fig:rules:pool-reap]{poolreap}}{e}
      \left(
      {
        \begin{array}{rcl}
            \var{utxoSt'} \\
            \var{acnt'} \\
            \var{dstate'} \\
            \var{pstate''} \\
        \end{array}
      }
      \right)
      \\~\\~\\
      \var{(\wcard,~\wcard,~\wcard,~(\var{pup},\wcard))}\leteq\var{utxoSt'}\\
      \var{pp_{new}}\leteq\fun{votedValue}~\var{pup}~\var{pp}~\Quorum\\
      {
        \begin{array}{r}
          \var{dstate'}\\
          \var{pstate''}\\
        \end{array}
      }
      \vdash
      \left(
        {
          \begin{array}{r}
            \var{utxoSt'} \\
            \var{acnt'} \\
            \var{pp}\\
          \end{array}
        }
      \right)
      \trans{\hyperref[fig:rules:new-proto-param]{newpp}}{\var{pp_{new}}}
      \left(
      {
        \begin{array}{rcl}
            \var{utxoSt''} \\
            \var{acnt''} \\
            \var{pp'}\\
        \end{array}
      }
      \right)
      \\~\\~\\
      \var{ls}' \leteq (\var{utxoSt}'',~(\var{dstate}',~\var{pstate}''))
    }
    {
      \vdash
      \left(
      \begin{array}{r}
        \var{acnt} \\
        \var{ss} \\
        \var{ls} \\
        \var{prevPp} \\
        \var{pp} \\
      \end{array}
      \right)
      \trans{epoch}{e}
      \left(
      \begin{array}{rcl}
        \varUpdate{\var{acnt''}} \\
        \varUpdate{\var{ss'}} \\
        \varUpdate{\var{ls'}} \\
        \varUpdate{\var{pp}} \\
        \varUpdate{\var{pp'}} \\
      \end{array}
      \right)
    }
\end{equation}$$

**Epoch Inference Rule**
## Rewards Distribution Calculation
This section defines the reward calculation for the proof of stake leader election. Figure 13 defines the pool reward as described in section 5.5.2 of [@delegation_design].

- The function $\fun{maxPool}$ gives the maximum reward a stake pool can receive in an epoch. This is a fraction of the total available rewards for the epoch. The result depends on the pool's relative stake, the pool's pledge and the following protocol parameters:

  - $\var{a_0}$, the leader-stake influence

  - $n_{opt}$, the optimal number of saturated stake pools

- The function $\fun{poolReward}$ gives the total rewards available to be distributed to the members of the given pool. It depends on the protocol parameter $d$, the relative stake $\sigma$, the number $n$ of blocks the pool added to the chain and the total number $\overline{N}$ of blocks added to the chain in the last epoch.


*Maximal Reward Function, called $f(s,\sigma)$ in section 5.5.2 of [@delegation_design]* $$\begin{align*}
      & \fun{maxPool} \in \PParams \to \Coin \to \unitInterval \to \unitInterval \to \Coin \\
      & \fun{maxPool}~\var{pp}~\var{R}~\sigma~\var{p_r} =
          ~~~\floor*{
             \frac{R}{1 + a_0}
             \cdot
             \left(
               \sigma' + p'\cdot a_0\cdot\frac{\sigma' - p'\frac{z_0-\sigma'}{z_0}}{z_0}
             \right)} \\
      & ~~~\where \\
      & ~~~~~~~a_0 = \fun{influence}~pp \\
      & ~~~~~~~n_{opt} = \fun{nopt}~pp \\
      & ~~~~~~~z_0 = 1/n_{opt} \\
      & ~~~~~~~\sigma'=\min(\sigma,~z_0) \\
      & ~~~~~~~p'=\min(p_r,~z_0) \\
\end{align*}$$

*Actual Reward Function, called $\hat{f}$ in section 5.5.2 of [@delegation_design]* $$\begin{align*}
      & \fun{poolReward} \in \unitInterval \to \unitInterval \to \N \to \N \to \Coin \to \Coin \\
      & \fun{poolReward}~\var{d}~{\sigma}~\var{n}~\var{\overline{N}}~\var{f} =
      \floor*{\overline{p}\cdot\var{f}}\\
      & ~~~\where \\
      & ~~~~~~~\overline{p} =
        \begin{cases}
          \frac{\beta}{\sigma} & \text{if } d < 0.8 \\
          1 & \text{otherwise}
        \end{cases} \\
      & ~~~~~~~\beta = \frac{n}{\max(1, \overline{N})} \\
\end{align*}$$

**Functions used in the Reward Calculation**
Figure 14 gives the calculation for splitting the pool rewards with its members, as described in 6.5.2 of [@delegation_design]. The portion of rewards allocated to the pool operator and owners is different than that of the members.

- The $\fun{r_{operator}}$ function calculates the leader reward, based on the pool cost, margin and the proportion of the pool's total stake. Note that this reward will go to the reward account specified in the pool registration certificate.

- The $\fun{r_{member}}$ function calculates the member reward, proportionally to their stake after the cost and margin are removed.


*Pool leader reward, from section 5.5.3 of [@delegation_design]* $$\begin{align*}
      & \fun{r_{operator}} \in \Coin \to \PoolParam \to \unitInterval \to \unitIntervalNonNull \to \Coin \\
      & \fun{r_{operator}}~ \var{\hat{f}}~ \var{pool}~ \var{s}~ {\sigma} =
        \begin{cases}
        \hat{f} & \hat{f} \leq c\\
        c + \floor*{(\hat{f} - c)\cdot\left(m + (1-m)\cdot\frac{s}{\sigma}\right) }&
        \text{otherwise.}
      \end{cases} \\
      & ~~~\where \\
      & ~~~~~~~c = \fun{poolCost}~pool \\
      & ~~~~~~~m = \fun{poolMargin}~pool \\
\end{align*}$$

*Pool member reward, from section 5.5.3 of [@delegation_design]* $$\begin{align*}
    & \fun{r_{member}} \in \Coin \to \PoolParam \to \unitInterval \to \unitIntervalNonNull \to \Coin \\
    & \fun{r_{member}}~ \var{\hat{f}}~ \var{pool}~ \var{t}~ {\sigma} =
      \begin{cases}
        0 & \hat{f} \leq c\\
        \floor*{(\hat{f} - c)\cdot(1-m)\cdot\frac{t}{\sigma}} &
        \text{otherwise.}
      \end{cases} \\
    & ~~~\where \\
    & ~~~~~~~c = \fun{poolCost}~pool \\
    & ~~~~~~~m = \fun{poolMargin}~pool \\
\end{align*}$$

**Functions used in the Reward Splitting**
Finally, the full reward calculation is presented in Figure 15. The calculation is done pool-by-pool.

- The $\fun{rewardOnePool}$ function calculates the rewards given out to each member of a given pool. The pool leader is identified by the stake credential of the pool operator. The function returns the rewards, calculated as follows:

  - $\var{pstake}$, the total amount of stake controlled by the stake pool.

  - $\var{ostake}$, the total amount of stake controlled by the stake pool operator and owners

  - $\sigma$, the total proportion of stake controlled by the stake pool.

  - $\overline{N}$, the expected number of blocks the pool should have produced.

  - $\var{pledge}$, the pool's pledge in lovelace.

  - $p_r$, the pool's pledge, as a proportion of active stake.

  - $\var{maxP}$, maximum rewards the pool can claim if the pledge is met, and zero otherwise.

  - $\var{poolR}$, the pool's actual reward, based on its performance.

  - $\var{mRewards}$, the member's rewards as a mapping of reward accounts to coin.

  - $\var{lReward}$, the leader's reward as coin.

  - $\var{potentialRewards}$, the combination of $\var{mRewards}$ and $\var{lRewards}$.

  - $\var{rewards}$, the restriction of $\var{potentialRewards}$ to the active reward accounts.

- The $\fun{reward}$ function applies $\fun{rewardOnePool}$ to each registered stake pool.


*Calculation to reward a single stake pool* $$\begin{align*}
    & \fun{rewardOnePool} \in \PParams \to \Coin \to \N \to \N \to \KeyHash \to \PoolParam\\
      & ~~~\to \type{Stake}\to \Coin \to \powerset{\AddrRWD}
           \to (\AddrRWD \mapsto \Coin) \\
      & \fun{rewardOnePool}
  ~\var{pp}~\var{R}~\var{n}~\var{\overline{N}}~\var{poolHK}~\var{pool}~\var{stake}~\var{tot}~\var{addrs_{rew}} =
          \var{rewards}\\
      & ~~~\where \\
      & ~~~~~~~\var{pstake} = \sum_{\_\mapsto c\in\var{stake}} c \\
      & ~~~~~~~\var{ostake} = \sum_{\substack{
        hk_\mapsto c\in\var{stake}\\
        hk\in(\fun{poolOwners}~\var{pool})\\
        }} c \\
      & ~~~~~~~\sigma = \var{pstake} / tot \\
      & ~~~~~~~\var{pledge} = \fun{poolPledge}~pool \\
      & ~~~~~~~p_{r} = \var{pledge} / \var{tot} \\
      & ~~~~~~~maxP =
      \begin{cases}
        \fun{maxPool}~\var{pp}~\var{R}~\sigma~\var{p_r}&
        \var{pledge} \leq \var{ostake}\\
        0 & \text{otherwise.}
      \end{cases} \\
      & ~~~~~~~\var{poolR} = \fun{poolReward}~\var{(\fun{d}~pp)}~{\sigma}~\var{n}~\var{\overline{N}}~\var{maxP} \\
      & ~~~~~~~\var{mRewards} = \left\{
                                  \addrRw~hk\mapsto\fun{r_{member}}~ \var{poolR}~ \var{pool}~ \var{\frac{c}{tot}}~ {\sigma}
                                  ~\Big\vert~
                                  hk\mapsto c\in\var{stake},~~hk \neq\var{poolHK}
                               \right\}\\
      & ~~~~~~~\var{lReward} = \fun{r_{operator}}~ \var{poolR}~ \var{pool}~ \var{\frac{\var{ostake}}{tot}}~ {\sigma} \\
      & ~~~~~~~\var{potentialRewards} =
                 \var{mRewards} \cup
                 \{(\fun{poolRAcnt}~\var{pool})\mapsto\var{lReward}\} \\
      & ~~~~~~~\var{rewards} = \var{addrs_{rew}}\restrictdom{\var{potentialRewards}} \\
\end{align*}$$

*Calculation to reward all stake pools* $$\begin{align*}
      & \fun{reward} \in \PParams \to \type{BlocksMade}\to \Coin\to \powerset{\AddrRWD}
      \to (\KeyHash \mapsto \PoolParam) \\
      & ~~~\to \type{Stake}\to (\KeyHash_{stake} \mapsto \KeyHash_{pool}) \to
      \Coin \to (\AddrRWD \mapsto \Coin)\\
      & \fun{reward}
  ~ \var{pp}~ \var{blocks}~ \var{R}~ \var{addrs_{rew}}~ \var{poolParams}~ \var{stake}~ \var{delegs}~ \var{total}
          = \var{rewards}\\
      & ~~~\where \\
      & ~~~~~~~tot = \sum_{\_\mapsto c\in \var{stake}}c \\
      & ~~~~~~~\var{\overline{N}} = \sum_{\_\mapsto m\in blocks}m \\
      & ~~~~~~~pdata = \left\{
        hk\mapsto \left(p,~n,~\fun{poolStake}~ \var{hk}~ \var{delegs}~ \var{stake}\right)
        \mathrel{\Bigg|}
        \begin{array}{rcl}
          hk & \var{p} & \var{poolParams} \\
          hk & \var{n} & \var{blocks} \\
        \end{array}
      \right\} \\
      & ~~~~~~~\var{results} = \left\{
        hk \mapsto \fun{rewardOnePool}
  ~\var{pp}~\var{R}~\var{n}~\var{\overline{N}}~\var{hk}~\var{p}~\var{s}~\var{tot}~\var{addrs_{rew}}
                 \mid
        hk\mapsto(p, n, s)\in\var{pdata} \right\} \\
      & ~~~~~~~\var{rewards} = \bigcup_{\wcard\mapsto\var{r}\in\var{results}}\var{r}
\end{align*}$$

**The Reward Calculation**
## Reward Update Calculation
This section defines the calculation of a reward update. A reward update is the information needed to account for the movement of lovelace in the system due to paying out rewards.

Figure 16 captures the potential movement of funds in the entire system, taking every transition system in this document into account. Value is moved between accounting pots, but the total amount of value in the system remains constant. In particular, the red subgraph represents the inputs and outputs to the "reward pot", a temporary variable used during the reward update calculation in Figure 18. The blue arrows represent the movement of funds that pass through the "reward pot".

::::: {#fig:fund-preservation .figure latex-placement="htb"}
::: center

**Preservation of Value**
:::::

Figure 17 defines a reward update. It consists of four pots:

- The change to the treasury. This will be a positive value.

- The change to the reserves. This will be a negative value.

- The map of new individual rewards (to be added to the existing rewards).

- The change to the fee pot. This will be a negative value. rewards.


*Reward Update* $$\begin{equation*}
    \type{RewardUpdate}=
    \left(
      \begin{array}{rll}
        \Delta t & \Coin & \text{change to the treasury} \\
        \Delta r & \Coin & \text{change to the reserves} \\
        \var{rs} & \AddrRWD\mapsto\Coin & \text{new individual rewards} \\
        \Delta f & \Coin & \text{change to the fee pot} \\
      \end{array}
    \right)
\end{equation*}$$

**Rewards Update type**
Figure 18 defines two functions, $\fun{createRUpd}$ to create a reward update and $\fun{applyRUpd}$ to apply a reward update to an instance of $\type{EpochState}$.

The $\fun{createRUpd}$ function does the following:

- Note that for all the calculations below, we use the previous protocol parameters $\var{prevPp}$, which corresponds to the parameters during the epoch for which we are creating rewards.

- First we calculate the change to the reserves, as determined by the $\rho$ protocol parameter.

- Next we calculate $\var{rewardPot}$, the total amount of coin available for rewards this epoch, as described in section 6.4 of [@delegation_design]. It consists of:

  - The fee pot, containing the transaction fees from the epoch.

  - The amount of monetary expansion from the reserves, calculated above.

  Note that the fee pot is taken from the snapshot taken at the epoch boundary. (See Figure6).

- Next we calculate the proportion of the reward pot that will move to the treasury, as determined by the $\tau$ protocol parameter. The remaining pot is called the $\var{R}$, just as in section 6.5 of [@delegation_design].

- The rewards are calculated, using the oldest stake distribution snapshot (the one labeled "go"). As given by $\fun{maxPool}$, each pool can receive a maximal amount, determined by its performance. The difference between the maximal amount and the actual amount received is added to the amount moved to the treasury.

- The fee pot will be reduced by $\var{feeSS}$.

Note that fees are not explicitly removed from any account: the fees come from transactions paying them and are accounted for whenever transactions are processed and when the deposit decay value comes from returning smaller refunds for deposits than were paid upon depositing.

The $\fun{applyRUpd}$ function does the following:

- Adjust the treasury, reserves and fee pots by the appropriate amounts.

- Add each individual reward to the global reward mapping. We must be careful, though, not to give out rewards to accounts that have been deregistered after the reward update was created.

  - Rewards for accounts that are still registered are added to the reward mappings.

  - The sum of the unregistered rewards are added to the reserves.

These two functions will be used in the blockchain transition systems in Section sec:chain. In particular, $\fun{createRUpd}$ will be used in Equation eq:reward-update, and $\fun{applyRUpd}$ will be used in Equation eq:new-epoch.


*Calculation to create a reward update* $$\begin{align*}
    & \fun{createRUpd} \in \N \to \type{BlocksMade}\to \type{EpochState}\to \Coin \to \type{RewardUpdate}\\
    & \fun{createRUpd}~\var{slotsPerEpoch}~\var{b}~\var{es}~\var{total} = \left(
      \Delta t_1,-~\Delta r_1+\Delta r_2,~\var{rs},~-\var{feeSS}\right) \\
    & ~~~\where \\
    & ~~~~~~~(\var{acnt},~\var{ss},~\var{ls},~\var{prevPp},~\wcard) = \var{es} \\
    & ~~~~~~~(\wcard,~\wcard,~\var{pstake_{go}},~\var{poolsSS},~\var{feeSS}) = \var{ss}\\
    & ~~~~~~~(\var{stake},~\var{delegs}) = \var{pstate_{go}} \\
    & ~~~~~~~(\wcard,~\var{reserves}) = \var{acnt} \\
    & ~~~~~~~\left(
      \wcard,~
      \left(
      \left(\var{rewards},~\wcard,~\wcard,~\wcard,~\wcard,~\wcard\right)~
      \wcard
      \right)
      \right) = \var{ls} \\
    & ~~~~~~~\Delta r_1 = \floor*{\min(1,\eta) \cdot (\fun{rho}~\var{prevPp}) \cdot
      \var{reserves}}
    \\
    & ~~~~~~~\eta = \frac{blocksMade}{\var{slotsPerEpoch} \cdot \ActiveSlotCoeff} \\
    & ~~~~~~~\var{rewardPot} = \var{feeSS} + \Delta r_1 \\
    & ~~~~~~~\Delta t_1 = \floor*{(\fun{tau}~\var{prevPp}) \cdot \var{rewardPot}} \\
    & ~~~~~~~\var{R} = \var{rewardPot} - \Delta t_1 \\
    & ~~~~~~~\var{circulation} = \var{total} - \var{reserves} \\
    & ~~~~~~~\var{rs}
      = \fun{reward}
  ~ \var{prevPp}~ \var{b}~ \var{R}~ \var{(\dom{rewards})}~ \var{poolsSS}~ \var{stake}~ \var{delegs}~ \var{circulation} \\
    & ~~~~~~~\Delta r_{2} = R - \left(\sum\limits_{\_\mapsto c\in\var{rs}}c\right) \\
    & ~~~~~~~blocksMade = \sum_{\wcard \mapsto m \in b}m
\end{align*}$$

**Reward Update Creation**
*Applying a reward update* $$\begin{align*}
      & \fun{applyRUpd} \in \type{RewardUpdate}\to \type{EpochState}\to \type{EpochState}\\
      & \fun{applyRUpd}~
      \left(
        \begin{array}{c}
          \Delta t \\
          \Delta r \\
          \var{rs} \\
          \Delta f \\
        \end{array}
    \right)
      \left(
        \begin{array}{c}
          \var{treasury} \\
          \var{reserves} \\
          ~ \\
          \var{rewards} \\
          \var{delegations} \\
          \var{ptrs} \\
          \var{genDelegs} \\
          \var{fGenDelegs} \\
          \var{i_{rwd}}
          \\~ \\
          \var{poolParams} \\
          \var{fPoolParams} \\
          \var{retiring} \\
          ~ \\
          \var{utxo} \\
          \var{deposits} \\
          \var{fees} \\
          \var{up} \\
          ~ \\
          \var{prevPp} \\
          \var{pp} \\
        \end{array}
      \right)
      =
      \left(
        \begin{array}{c}
          \varUpdate{\var{treasury} + \Delta t + \var{unregRU'}}\\
          \varUpdate{\var{reserves} + \Delta r}\\
          ~ \\
          \varUpdate{\var{rewards}\unionoverridePlus\var{regRU}} \\
          \var{delegations} \\
          \var{ptrs} \\
          \var{genDelegs} \\
          \var{fGenDelegs} \\
          \var{i_{rwd}}
          \\~ \\
          \var{poolParams} \\
          \var{fPoolParams} \\
          \var{retiring} \\
          ~ \\
          \var{utxo} \\
          \var{deposits} \\
          \varUpdate{\var{fees}+\Delta f} \\
          \var{up} \\
          ~ \\
          \var{prevPp} \\
          \var{pp} \\
        \end{array}
    \right) \\
    & ~~~\where \\
    & ~~~~~~~\var{regRU}=(\dom{rewards})\restrictdom rs\\
    & ~~~~~~~\var{unregRU}=(\dom{rewards})\subtractdom rs\\
    & ~~~~~~~\var{unregRU'}=\sum\limits_{\wcard\mapsto c\in\var{unregRU}} \var{c}\\
\end{align*}$$

**Reward Update Application**