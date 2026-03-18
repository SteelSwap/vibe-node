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

- The function $\mathsf{obligation}$ calculates the the minimal amount of coin needed to pay out all deposit refunds.

- The function $\mathsf{poolStake}$ filters the stake distribution to one stake pool.


*Total possible refunds* $$\begin{align*}
    & \mathsf{obligation} \in \mathsf{PParams} \to (\mathsf{StakeCredential} \mapsto \mathsf{Coin})
    \to (\mathsf{KeyHash}_{pool}\mapsto\mathsf{PoolParam}) \to \mathsf{Coin} \\
    & \mathsf{obligation}~ \mathit{pp}~ \mathit{rewards}~ \mathit{poolParams} = \\
    & ~~~~~
    (\mathsf{keyDeposit}~\mathit{pp}) \cdot|\mathit{rewards}| +
    (\mathsf{poolDeposit}~\mathit{pp}) \cdot|\mathit{poolParams}| \\
\end{align*}$$ *Filter Stake to one Pool* $$\begin{align*}
      & \mathsf{poolStake} \in \mathsf{KeyHash}_{pool} \to (\mathsf{KeyHash}_{stake} \mapsto \mathsf{KeyHash}_{pool})
        \to \mathsf{Stake}\to \mathsf{Stake}\\
      & \mathsf{poolStake}~ \mathit{hk}~ \mathit{delegs}~ \mathit{stake} =
        \mathrm{dom}~(\mathit{delegs}\rhd\{hk\})\lhd\mathit{stake}
\end{align*}$$

**Helper Functions used in Rewards and Epoch Boundary**
The Figure 2 lists the accounting fields, denoted by $\mathsf{Acnt}$, which will be used throughout this section. It consists of:

- The value $\mathit{treasury}$ tracks the amount of coin currently stored in the treasury. Initially there will be no way to remove these funds.

- The value $\mathit{reserves}$ tracks the amount of coin currently stored in the reserves. This pot is used to pay rewards.

More will be said about the general accounting system in Section 1.9.


*Accounting Fields* $$\begin{equation*}
    \mathsf{Acnt} =
    \left(
      \begin{array}{rll}
        \mathit{treasury} & \mathsf{Coin} & \text{treasury pot}\\
        \mathit{reserves} & \mathsf{Coin} & \text{reserve pot}\\
      \end{array}
    \right)
\end{equation*}$$

**Accounting fields**
## Stake Distribution Calculation
This section defines the stake distribution calculations. Figure 3 introduces three new derived types:

- $\mathsf{BlocksMade}$ represents the number of blocks each stake pool produced during an epoch.

- $\mathsf{Stake}$ represents the amount of stake (in $\mathsf{Coin}$) controlled by each stake pool.


*Derived types* $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{blocks}
      & \mathsf{BlocksMade}
      & \mathsf{KeyHash}_{pool} \mapsto \N
      & \text{blocks made by stake pools} \\
      \mathit{stake}
      & \mathsf{Stake}
      & \mathsf{Credential} \mapsto \mathsf{Coin}
      & \text{stake} \\
    \end{array}
\end{equation*}$$

**Epoch definitions**
The stake distribution calculation is given in Figure 4.

- $\mathsf{aggregate_{+}}$ takes a relation on $A\times B$, where $B$ is any monoid $(B,+,e)$ and returns a map from each $a\in A$ to the "sum" (using the monoidal $+$ operation) of all $b\in B$ such that $(a, b)\in A\times B$.

- $\mathsf{stakeDistr}$ uses the $\mathsf{aggregate_{+}}$ function and several relations to compute the stake distribution, mapping each hashkey to the total coin under its control. Keys that are not both registered and delegated are filtered out. The relation passed to $\mathsf{aggregate_{+}}$ is made up of:

  - $\mathsf{stakeCred_b}^{-1}$, relating credentials to (base) addresses

  - $\left(\mathsf{addrPtr}\circ\mathit{ptr}\right)^{-1}$, relating credentials to (pointer) addresses

  - $\mathrm{range}~utxo$, relating addresses to coins

  - $\mathsf{stakeCred_r}^{-1}\circ\mathit{rewards}$, relating (reward) addresses to coins

  The notation for relations is explained in Section sec:notation-shelley.


*Aggregation (for a monoid B)* $$\begin{align*}
      & \mathsf{aggregate_{+}} \in \mathbb{P}~(A \times B) \to (A\mapsto B) \\
      & \mathsf{aggregate_{+}}~\mathit{R} = \left\{a\mapsto \sum_{(a,b)\in\mathit{R}}b
          ~\mid~a\in\dom\mathit{R}\right\} \\
\end{align*}$$ *Stake Distribution (using functions and maps as relations)* $$\begin{align*}
      & \mathsf{stakeDistr} \in \mathsf{UTxO} \to \mathsf{DState} \to \mathsf{PState} \to \mathsf{Snapshot}\\
      & \mathsf{stakeDistr}~{utxo}~{dstate}~{pstate} = \\
      & ~~~~ \big((\mathrm{dom}~\mathit{activeDelegs})
      \lhd\left(\mathsf{aggregate_{+}}~\mathit{stakeRelation}\right),
    ~\mathit{delegations},~\mathit{poolParams}\big)\\
      & \where \\
      & ~~~~ (~\mathit{rewards},~\mathit{delegations},~\mathit{ptrs},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}})
        = \mathit{dstate} \\
      & ~~~~ (~\mathit{poolParams}~\underline{\phantom{a}},~\underline{\phantom{a}}) = \mathit{pstate} \\
      & ~~~~ \mathit{stakeRelation} = \left(
        \left(\mathsf{stakeCred_b}^{-1}\cup\left(\mathsf{addrPtr}\circ\mathit{ptr}\right)^{-1}\right)
        \circ\left(\mathrm{range}~\mathit{utxo}\right)
        \right)
        \cup \left(\mathsf{stakeCred_r}^{-1}\circ\mathit{rewards}\right) \\
      & ~~~~ \mathit{activeDelegs} =
               (\mathrm{dom}~rewards) \lhd \mathit{delegations} \rhd (\mathrm{dom}~poolParams) \\
\end{align*}$$

**Stake Distribution Function**
## Snapshot Transition
The state transition types for stake distribution snapshots are given in Figure 5. Each snapshot consists of:

- $\mathit{stake}$, a stake distribution, which is defined in Figure 3 as a mapping of credentials to coin.

- $\mathit{delegations}$, a delegation map, mapping credentials to stake pools.

- $\mathit{poolParameters}$, storing the pool parameters of each stake pool.

The type $\mathsf{\mathsf{Snapshots}}$ contains the information needing to be saved on the epoch boundary:

- $\mathit{pstake_{mark}}$, $\mathit{pstake_{set}}$ and $\mathit{pstake_{go}}$ are the three snapshots as explained in Section 1.1.

- $\mathit{feeSS}$ stores the fees which are added to the reward pot during the next reward update calculation, which is then subtracted from the fee pot on the epoch boundary.


*Snapshots* $$\begin{equation*}
    \mathsf{Snapshot}=
    \left(
      \begin{array}{rll}
        \mathit{stake} & \mathsf{Stake}& \text{stake distribution}\\
        \mathit{delegations} & \mathsf{Credential}\mapsto\mathsf{KeyHash}_{pool}
                          & \text{stake delegations}\\
        \mathit{poolParameters} & \mathsf{KeyHash}_{pool} \mapsto \mathsf{PoolParam} & \text{pool parameters }\\
      \end{array}
    \right)
\end{equation*}$$

$$\begin{equation*}
    \mathsf{Snapshots}=
    \left(
      \begin{array}{rll}
        \mathit{pstake_{mark}} & \mathsf{Snapshot}& \text{newest stake}\\
        \mathit{pstake_{set}}  & \mathsf{Snapshot}& \text{middle stake}\\
        \mathit{pstake_{go}}   & \mathsf{Snapshot}& \text{oldest stake}\\
        \mathit{feeSS} & \mathsf{Coin} & \text{fee snapshot}\\
      \end{array}
    \right)
\end{equation*}$$ *Snapshot transitions* $$\begin{equation*}
    \_ \vdash
    \mathit{\_} \xrightarrow[\mathsf{snap}]{}{} \mathit{\_}
    \subseteq \powerset (\mathsf{LState} \times \mathsf{Snapshots}\times \mathsf{Snapshots})
\end{equation*}$$

**Snapshot transition-system types**
The snapshot transition rule is given in Figure 6. This transition has no preconditions and results in the following state change:

- The oldest snapshot is replaced with the penultimate one.

- The penultimate snapshot is replaced with the newest one.

- The newest snapshot is replaced with one just calculated.

- The current fees pot is stored in $\mathit{feeSS}$. Note that this value will not change during the epoch, unlike the $\mathit{fees}$ value in the UTxO state.


$$\begin{equation}
\label{eq:snapshot}
    \inference[Snapshot]
    {
      {
      \begin{array}{rl}
        ((\mathit{utxo},~\underline{\phantom{a}},\mathit{fees},~\underline{\phantom{a}}),~(\mathit{dstate},~\mathit{pstate})) & \mathit{lstate} \\
        \mathit{stake} & \mathsf{stakeDistr}~ \mathit{utxo}~ \mathit{dstate}~ \mathit{pstate} \\
      \end{array}
      }
    }
    {
      \begin{array}{r}
        \mathit{lstate} \\
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
          \mathit{pstake_{mark}}\\
          \mathit{pstake_{set}}\\
          \mathit{pstake_{go}}\\
          \mathit{feeSS} \\
        \end{array}
      \right)
      \xrightarrow[\mathsf{snap}]{}{}
      \left(
        \begin{array}{r}
          \mathsf{varUpdate}~\mathit{stake} \\
          \varUpdate{\mathit{pstake_{mark}}} \\
          \varUpdate{\mathit{pstake_{set}}} \\
          \mathsf{varUpdate}~\mathit{fees} \\
        \end{array}
      \right)
    }
\end{equation}$$

**Snapshot Inference Rule**
## Pool Reaping Transition
Figure 7 defines the types for the pool reap transition, which is responsible for removing pools slated for retirement in the given epoch.


*Pool Reap State* $$\begin{equation*}
    \mathsf{PlReapState}=
    \left(
      \begin{array}{rll}
        \mathit{utxoSt} & \mathsf{UTxOState} & \text{utxo state}\\
        \mathit{acnt} & \mathsf{Acnt} & \text{accounting}\\
        \mathit{dstate} & \mathsf{DState} & \text{delegation state}\\
        \mathit{pstate} & \mathsf{PState} & \text{pool state}\\
      \end{array}
    \right)
\end{equation*}$$ *Pool Reap transitions* $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{poolreap}]{}{\_} \_ \in
    \powerset (\mathsf{PParams} \times \mathsf{PlReapState}\times \mathsf{Epoch} \times \mathsf{PlReapState})
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
        \mathit{retired} & \mathrm{dom}~(\mathit{retiring}^{-1}~\mathit{e}) \\
        \mathit{pr} & \left\{
                   \mathit{hk}\mapsto(\mathsf{poolDeposit}~\mathit{pp})
                     \mid
                     \mathit{hk}\in\mathit{retired}
                   \right\}\\
        \mathit{rewardAcnts}
                 & \{\mathit{hk}\mapsto \mathsf{poolRAcnt}~\mathit{pool} \mid
                   \mathit{hk}\mapsto\mathit{pool} \in \mathit{retired}\lhd\mathit{poolParams} \} \\
        \mathit{rewardAcnts'} & \left\{
                        a \mapsto c
                        \mathrel{\Bigg|}
                        \begin{array}{rl}
                          \mathit{hk} \mapsto c & \mathit{pr}, \\
                          \mathit{hk}\mapsto\mathit{a} & \mathit{rewardAcnts} \\
                        \end{array}
                      \right\} \\
        \mathit{refunds} & \mathrm{dom}~rewards\lhd\mathit{rewardAcnts'} \\
        \mathit{mRefunds} & \mathrm{dom}~rewards\mathbin{\rlap{\lhd}/}\mathit{rewardAcnts'} \\
        \mathit{refunded} & \sum\limits_{\underline{\phantom{a}}\mapsto c\in\mathit{refunds}} c \\
        \mathit{unclaimed} & \sum\limits_{\underline{\phantom{a}}\mapsto c\in\mathit{mRefunds}} c \\
      \end{array}
      }
    }
    {
      \mathit{pp}
      \vdash
      \left(
        \begin{array}{r}
          \mathit{utxo} \\
          \mathit{deposits} \\
          \mathit{fees} \\
          \mathit{ups} \\
          ~ \\
          \mathit{treasury} \\
          \mathit{reserves} \\
          ~ \\
          \mathit{rewards} \\
          \mathit{delegations} \\
          \mathit{ptrs} \\
          \mathit{genDelegs} \\
          \mathit{fGenDelegs} \\
          \mathit{i_{rwd}} \\
          ~ \\
          \mathit{poolParams} \\
          \mathit{fPoolParams} \\
          \mathit{retiring} \\
        \end{array}
      \right)
      \xrightarrow[\mathsf{poolreap}]{}{e}
      \left(
        \begin{array}{rcl}
          \mathit{utxo} \\
          \mathsf{varUpdate}~\mathit{deposits}
          & \mathsf{varUpdate}~-
          & \mathsf{varUpdate}~(\mathit{unclaimed} + \mathit{refunded}) \\
          \mathit{fees} \\
          \mathit{ups} \\
          ~ \\
          \mathsf{varUpdate}~\mathit{treasury} & \mathsf{varUpdate}~+ & \mathsf{varUpdate}~\mathit{unclaimed} \\
          \mathit{reserves} \\
          ~ \\
          \mathsf{varUpdate}~\mathit{rewards} & \mathsf{varUpdate}~\unionoverridePlus & \mathsf{varUpdate}~\mathit{refunds} \\
          \mathsf{varUpdate}~\mathit{delegations} & \mathsf{varUpdate}~\subtractrange & \mathsf{varUpdate}~\mathit{retired} \\
          \mathit{ptrs} \\
          \mathit{genDelegs} \\
          \mathit{fGenDelegs} \\
          \mathit{i_{rwd}}\\
          ~ \\
          \mathsf{varUpdate}~\mathit{retired} & \varUpdate{\mathbin{\rlap{\lhd}/}} & \mathsf{varUpdate}~\mathit{poolParams} \\
          \mathsf{varUpdate}~\mathit{retired} & \varUpdate{\mathbin{\rlap{\lhd}/}} & \mathsf{varUpdate}~\mathit{fPoolParams} \\
          \mathsf{varUpdate}~\mathit{retired} & \varUpdate{\mathbin{\rlap{\lhd}/}} & \mathsf{varUpdate}~\mathit{retiring} \\
        \end{array}
      \right)
    }
\end{equation}$$

**Pool Reap Inference Rule**
## Protocol Parameters Update Transition
Finally, reaching the epoch boundary may trigger a change in the protocol parameters. The protocol parameters environment consists of the delegation and pool states, and the signal is an optional new collection of protocol parameters The state change is a change of the $\mathsf{UTxOState}$, the $\mathsf{Acnt}$ states and the current $\mathsf{PParams}$. The type of this state transition is given in Figure 9.


*New Proto Param environment* $$\begin{equation*}
    \mathsf{NewPParamEnv}=
    \left(
      \begin{array}{rll}
        \mathit{dstate} & \mathsf{DState} & \text{delegation state}\\
        \mathit{pstate} & \mathsf{PState} & \text{pool state}\\
      \end{array}
    \right)
\end{equation*}$$ *New Proto Param States* $$\begin{equation*}
    \mathsf{NewPParamState}=
    \left(
      \begin{array}{rll}
        \mathit{utxoSt} & \mathsf{UTxOState} & \text{utxo state}\\
        \mathit{acnt} & \mathsf{Acnt} & \text{accounting}\\
        \mathit{pp} & \mathsf{PParams} & \text{current protocol parameters}\\
      \end{array}
    \right)
\end{equation*}$$ *New Proto Param transitions* $$\begin{equation*}
    \_ \vdash
    \mathit{\_} \xrightarrow[\mathsf{newpp}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{NewPParamEnv}\times \mathsf{NewPParamState}\times \mathsf{PParams}^? \times \mathsf{NewPParamState})
\end{equation*}$$

*Helper Functions* $$\begin{align*}
      & \mathsf{updatePpup} \in \mathsf{UTxOState} \to \mathsf{PParams} \to \mathsf{UTxOState}\\
      & \mathsf{updatePpup}~\mathit{utxoSt}~\mathit{pp} =
      \begin{cases}
        (\mathit{utxo},\mathit{deposits},\mathit{fees},(\mathit{fpup},~\emptyset))
        &
        \mathit{canFollow}
        \\
        (\mathit{utxo},\mathit{deposits},\mathit{fees},(\emptyset,~\emptyset))
        &
        \text{otherwise} \\
      \end{cases}\\
      & ~~~\where \\
      & ~~~~~~~\mathit{canFollow} =
        \forall\mathit{ps}\in\mathrm{range}~pup,~
        \mathit{pv}\mapsto\mathit{v}\in\mathit{ps}\implies\mathsf{pvCanFollow}~(\mathsf{pv}~\mathit{pp})~\mathit{v}
        \\
      & ~~~~~~~(\mathit{utxo},\mathit{deposits},\mathit{fees},(\mathit{pup},~\mathit{fpup})) = \mathit{utxoSt} \\
\end{align*}$$

**New Proto Param transition-system types**
Figure 10 defines the new protocol parameter transition. The transition has two rules, depending on whether or not the new protocol parameters meet some requirements. In particular, we require that the new parameters would not incur a debt of the system that can not be covered by the reserves, and that the max block size is greater than the sum of the max transaction size and the max header size. If the requirements are met, the new protocol parameters are accepted, the proposal is reset, and the reserves are adjusted to account for changes in the deposits. Otherwise, the only change is that the proposal is reset.

The $\mathsf{NEWPP}$ rule also cleans up the protocol parameter update proposals, by calling $\mathsf{updatePpup}$ on the UTxO state. The $\mathsf{updatePpup}$ sets the protocol parameter updates to the future protocol parameter updates provided the protocol versions all can follow from the version given in the protocol parameters, or the emptyset otherwise. In any case, the future protocol parameters update proposals are set to the empty set. If new protocol parameters are being adopted, then these is the value given to $\mathsf{updatePpup}$, otherwise the old parameters are given.

Regarding adjusting the reserves for changes in the deposits, one of three things happens:

- If the new protocol parameters mean that **fewer** funds are required in the deposit pot to cover all possible refunds, then the excess is moved to the reserves.

- If the new protocol parameters mean that **more** funds are required in the deposit pot to cover all possible refunds and the difference is **less** than the reserve pot, then funds are moved from the reserve pot to cover the difference.

- If the new protocol parameters mean that **more** funds are required in the deposit pot to cover all possible refunds and the difference is **more** than the reserve pot, then Rule eq:new-pc-denied meets the precondition and the only change of state is that the update proposals are reset.

Note that here, unlike most of the inference rules in this document, the $\mathit{utxoSt'}$ and the $\mathit{acnt'}$ do not come from valid UTxO or accounts transitions in the antecedent. We simply define the consequent transition using these directly (instead of listing all the fields in both states in the consequent transition). It is done this way here for ease of reading.


$$\begin{equation}
\label{eq:new-pc-accepted}
    \hspace{-0.3cm}
    \inference[New-Proto-Param-Accept]
    {
      \mathit{pp_{new}}\neq\mathsf{Nothing} \\~\\
      {\begin{array}{rcl}
         (\mathit{utxo},~\mathit{deposits},~\mathit{fees},~\mathit{pup}) & \mathrel{\mathop:}= & \mathit{utxoSt} \\
         \mathit{(\mathit{rewards},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{i_{rwd}})} &
         \mathrel{\mathop:}= & \mathit{dstate}\\
         \mathit{(\mathit{poolParams},~\underline{\phantom{a}},~\underline{\phantom{a}})} & \mathrel{\mathop:}= & \mathit{pstate}\\
         \mathit{oblg_{cur}} & \mathrel{\mathop:}= & \mathsf{obligation}~ \mathit{pp}~ \mathit{rewards}~ \mathit{poolParams} \\
         \mathit{oblg_{new}} & \mathrel{\mathop:}= & \mathsf{obligation}~ \mathit{pp_{new}}~ \mathit{rewards}~ \mathit{poolParams} \\
         \mathit{diff} & \mathrel{\mathop:}= & \mathit{oblg_{cur}} - \mathit{oblg_{new}}\\
      \end{array}}
      \\~\\~\\
      \mathit{oblg_{cur}} = \mathit{deposits} \\
      \mathit{reserves} + \mathit{diff} \geq \sum\limits_{\underline{\phantom{a}}\mapsto\mathit{val}\in\mathit{i_{rwd}}} val \\
      \mathsf{maxTxSize}~\mathit{pp_{new}} + \mathsf{maxHeaderSize}~\mathit{pp_{new}} <
        \mathsf{maxBlockSize}~\mathit{pp_{new}}
      \\~\\
        \mathit{utxoSt'} \mathrel{\mathop:}=
        \left(\mathit{utxo},~\mathsf{varUpdate}~oblg_{new},~\mathit{fees},~\mathit{pup}\right)
      \\
      \mathit{utxoSt''} \mathrel{\mathop:}= \mathsf{updatePpup}~\mathit{utxoSt'}~\mathit{pp_{new}}
      \\~\\
      (\mathit{treasury},~\mathit{reserves})\mathrel{\mathop:}= \mathit{acnt} \\
      \mathit{acnt'} \mathrel{\mathop:}= (\mathit{treasury},~\mathsf{varUpdate}~reserves + diff) \\
    }
    {
      \begin{array}{l}
        \mathit{dstate}\\
        \mathit{pstate}\\
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
          \mathit{utxoSt} \\
          \mathit{acnt} \\
          \mathit{pp}
        \end{array}
      \right)
      \xrightarrow[\mathsf{newpp}]{}{\mathit{pp_{new}}}
      \left(
        \begin{array}{rcl}
          \mathsf{varUpdate}~utxoSt''\\
          \mathsf{varUpdate}~acnt' \\
          \varUpdate{\mathit{pp_{new}}} \\
        \end{array}
      \right)
    }
\end{equation}$$

$$\begin{equation}
\label{eq:new-pc-denied}
    \inference[New-Proto-Param-Denied]
    {
      \left({\begin{array}{c}
            \mathit{pp_{new}}=\mathsf{Nothing} \\
        \lor \\
        \mathit{reserves} + \mathit{diff} < \sum\limits_{\underline{\phantom{a}}\mapsto\mathit{val}\in\mathit{i_{rwd}}} val\\
        \lor \\
        \mathsf{maxTxSize}~\mathit{pp_{new}} + \mathsf{maxHeaderSize}~\mathit{pp_{new}} \geq
          \mathsf{maxBlockSize}~\mathit{pp_{new}}
      \end{array}}\right)
      \\~\\~\\
      {\begin{array}{rcl}
         (\mathit{utxo},~\mathit{deposits},~\mathit{fees},~\mathit{pup}) & \mathrel{\mathop:}= & \mathit{utxoSt} \\
          \mathit{(\mathit{rewards},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{i_{rwd}})} &
          \mathrel{\mathop:}= & \mathit{dstate}\\
         \mathit{(\mathit{poolParams},~\underline{\phantom{a}},~\underline{\phantom{a}})} & \mathrel{\mathop:}= & \mathit{pstate}\\
          \mathit{oblg_{cur}} & \mathrel{\mathop:}= & \mathsf{obligation}~ \mathit{pp}~ \mathit{rewards}~ \mathit{poolParams} \\
          \mathit{oblg_{new}} & \mathrel{\mathop:}= & \mathsf{obligation}~ \mathit{pp_{new}}~ \mathit{rewards}~ \mathit{poolParams} \\
         \mathit{diff} & \mathrel{\mathop:}= & \mathit{oblg_{cur}} - \mathit{oblg_{new}}
      \end{array}}
      \\~\\~\\
      \mathit{utxoSt'} \mathrel{\mathop:}= \mathsf{updatePpup}~\mathit{utxoSt}~\mathit{pp} \\
    }
    {
      \begin{array}{l}
        \mathit{dstate}\\
        \mathit{pstate}\\
      \end{array}
      \vdash
      \left(
        \begin{array}{r}
          \mathit{utxoSt} \\
          \mathit{acnt} \\
          \mathit{pp}
        \end{array}
      \right)
      \xrightarrow[\mathsf{newpp}]{}{\mathit{pp_{new}}}
      \left(
        \begin{array}{rcl}
          \mathsf{varUpdate}~utxoSt'\\
          \mathit{acnt} \\
          \mathit{pp}
        \end{array}
      \right)
    }
\end{equation}$$

**New Proto Param Inference Rule**
## Complete Epoch Boundary Transition
Finally, it is possible to define the complete epoch boundary transition type, which is defined in Figure 11. The transition has no evironment. The state is made up of the the accounting state, the snapshots, the ledger state and the protocol parameters. The transition uses a helper function $\mathsf{votedValue}$ which returns the consensus value of update proposals in the event that consensus is met. **Note that** $\mathsf{votedValue}$ **is only well-defined if** $\mathit{quorum}$ **is greater than half the number of core nodes, i.e.** $\mathsf{Quorum} > |\mathit{genDelegs}|/2$ **.**


*Epoch States* $$\begin{equation*}
    \mathsf{EpochState}=
    \left(
      \begin{array}{rll}
        \mathit{acnt} & \mathsf{Acnt} & \text{accounting}\\
        \mathit{ss} & \mathsf{Snapshots}& \text{snapshots}\\
        \mathit{ls} & \mathsf{LState} & \text{ledger state}\\
        \mathit{prevPp} & \mathsf{PParams} & \text{previous protocol parameters}\\
        \mathit{pp} & \mathsf{PParams} & \text{protocol parameters}\\
      \end{array}
    \right)
\end{equation*}$$ *Epoch transitions* $$\begin{equation*}
    \vdash
    \mathit{\_} \xrightarrow[\mathsf{epoch}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{EpochState}\times \mathsf{Epoch} \times \mathsf{EpochState})
\end{equation*}$$ *Accessor Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{getIR} & \mathsf{EpochState}\to (\mathsf{StakeCredential} \mapsto \mathsf{Coin})
                  & \text{get instantaneous rewards} \\
    \end{array}
\end{equation*}$$ *Helper Functions* $$\begin{align*}
      & \mathsf{votedValue} \in (\mathsf{KeyHashGen}\mapsto\mathsf{PParamsUpdate}) \to \mathsf{PParams} \to \N \to \mathsf{PParamsUpdate}^?\\
      & \mathsf{votedValue}~\mathit{pup}~\mathit{pp}~\mathit{quorum} =
      \begin{cases}
        \mathit{pp}\unionoverrideRight\mathit{p}
          & \exists! p\in\mathrm{range}~pup~(|pup\rhd p|\geq \mathit{quorum}) \\
        \mathsf{Nothing} & \text{otherwise} \\
      \end{cases}
\end{align*}$$

**Epoch transition-system types**
The epoch transition rule calls $\mathsf{SNAP}$, $\mathsf{POOLREAP}$ and $\mathsf{NEWPP}$ in sequence. It also stores the previous protocol parameters in $\mathit{prevPp}$. The previous protocol parameters will be used for the reward calculation in the upcoming epoch, note that they correspond to the epoch for which the rewards are being calculated. Additionally, this transition also adopts the pool parameters $\mathit{fPoolParams}$ corresponding to the pool re-registration certificates which we submitted late in the ending epoch. The ordering of these rules is important. The stake pools which will be updated by $\mathit{fPoolParams}$ or reaped during the $\mathsf{POOLREAP}$ transition must still be a part of the new snapshot, and so $\mathsf{SNAP}$ must occur before these two actions. Moreover, $\mathsf{SNAP}$ sets the deposit pot equal to current obligation, which is a property that is preserved by $\mathsf{POOLREAP}$ and which is necessary for the preservation of Ada property in the $\mathsf{NEWPP}$ transition.


$$\begin{equation}
\label{eq:epoch}
    \inference[Epoch]
    {
      {
        \begin{array}{r}
          \mathit{lstate} \\
        \end{array}
      }
      \vdash
      { \mathit{ss} }
      \xrightarrow[\mathsf{\hyperref[fig:rules:snapshot]{snap}}]{}{}
      { \mathit{ss'} }
      \\~\\
      (\mathit{utxoSt},~(\mathit{dstate},~\mathit{pstate}))\mathrel{\mathop:}=\mathit{ls} \\
      (\mathit{poolParams},~\mathit{fPoolParams},~\mathit{retiring})\mathrel{\mathop:}=\mathit{pstate}
      \\
      \mathit{pstate'}\mathrel{\mathop:}=(\mathit{poolParams}\unionoverrideRight\mathit{fPoolParams},
      ~\emptyset,~\mathit{retiring})
      \\~\\~\\
      \mathit{pp}
      \vdash
      \left(
        {
          \begin{array}{r}
            \mathit{utxoSt} \\
            \mathit{acnt} \\
            \mathit{dstate} \\
            \mathit{pstate'} \\
          \end{array}
        }
      \right)
      \xrightarrow[\mathsf{\hyperref[fig:rules:pool-reap]{poolreap}}]{}{e}
      \left(
      {
        \begin{array}{rcl}
            \mathit{utxoSt'} \\
            \mathit{acnt'} \\
            \mathit{dstate'} \\
            \mathit{pstate''} \\
        \end{array}
      }
      \right)
      \\~\\~\\
      \mathit{(\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~(\mathit{pup},\underline{\phantom{a}}))}\mathrel{\mathop:}=\mathit{utxoSt'}\\
      \mathit{pp_{new}}\mathrel{\mathop:}=\mathsf{votedValue}~\mathit{pup}~\mathit{pp}~\mathsf{Quorum}\\
      {
        \begin{array}{r}
          \mathit{dstate'}\\
          \mathit{pstate''}\\
        \end{array}
      }
      \vdash
      \left(
        {
          \begin{array}{r}
            \mathit{utxoSt'} \\
            \mathit{acnt'} \\
            \mathit{pp}\\
          \end{array}
        }
      \right)
      \xrightarrow[\mathsf{\hyperref[fig:rules:new-proto-param]{newpp}}]{}{\mathit{pp_{new}}}
      \left(
      {
        \begin{array}{rcl}
            \mathit{utxoSt''} \\
            \mathit{acnt''} \\
            \mathit{pp'}\\
        \end{array}
      }
      \right)
      \\~\\~\\
      \mathit{ls}' \mathrel{\mathop:}= (\mathit{utxoSt}'',~(\mathit{dstate}',~\mathit{pstate}''))
    }
    {
      \vdash
      \left(
      \begin{array}{r}
        \mathit{acnt} \\
        \mathit{ss} \\
        \mathit{ls} \\
        \mathit{prevPp} \\
        \mathit{pp} \\
      \end{array}
      \right)
      \xrightarrow[\mathsf{epoch}]{}{e}
      \left(
      \begin{array}{rcl}
        \mathsf{varUpdate}~\mathit{acnt''} \\
        \mathsf{varUpdate}~\mathit{ss'} \\
        \mathsf{varUpdate}~\mathit{ls'} \\
        \mathsf{varUpdate}~\mathit{pp} \\
        \mathsf{varUpdate}~\mathit{pp'} \\
      \end{array}
      \right)
    }
\end{equation}$$

**Epoch Inference Rule**
## Rewards Distribution Calculation
This section defines the reward calculation for the proof of stake leader election. Figure 13 defines the pool reward as described in section 5.5.2 of [@delegation_design].

- The function $\mathsf{maxPool}$ gives the maximum reward a stake pool can receive in an epoch. This is a fraction of the total available rewards for the epoch. The result depends on the pool's relative stake, the pool's pledge and the following protocol parameters:

  - $\mathit{a_0}$, the leader-stake influence

  - $n_{opt}$, the optimal number of saturated stake pools

- The function $\mathsf{poolReward}$ gives the total rewards available to be distributed to the members of the given pool. It depends on the protocol parameter $d$, the relative stake $\sigma$, the number $n$ of blocks the pool added to the chain and the total number $\overline{N}$ of blocks added to the chain in the last epoch.


*Maximal Reward Function, called $f(s,\sigma)$ in section 5.5.2 of [@delegation_design]* $$\begin{align*}
      & \mathsf{maxPool} \in \mathsf{PParams} \to \mathsf{Coin} \to [0,~1] \to [0,~1] \to \mathsf{Coin} \\
      & \mathsf{maxPool}~\mathit{pp}~\mathit{R}~\sigma~\mathit{p_r} =
          ~~~\floor*{
             \frac{R}{1 + a_0}
             \cdot
             \left(
               \sigma' + p'\cdot a_0\cdot\frac{\sigma' - p'\frac{z_0-\sigma'}{z_0}}{z_0}
             \right)} \\
      & ~~~\where \\
      & ~~~~~~~a_0 = \mathsf{influence}~pp \\
      & ~~~~~~~n_{opt} = \mathsf{nopt}~pp \\
      & ~~~~~~~z_0 = 1/n_{opt} \\
      & ~~~~~~~\sigma'=\min(\sigma,~z_0) \\
      & ~~~~~~~p'=\min(p_r,~z_0) \\
\end{align*}$$

*Actual Reward Function, called $\hat{f}$ in section 5.5.2 of [@delegation_design]* $$\begin{align*}
      & \mathsf{poolReward} \in [0,~1] \to [0,~1] \to \N \to \N \to \mathsf{Coin} \to \mathsf{Coin} \\
      & \mathsf{poolReward}~\mathit{d}~{\sigma}~\mathit{n}~\mathit{\overline{N}}~\mathit{f} =
      \floor*{\overline{p}\cdot\mathit{f}}\\
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

- The $\mathsf{r_{operator}}$ function calculates the leader reward, based on the pool cost, margin and the proportion of the pool's total stake. Note that this reward will go to the reward account specified in the pool registration certificate.

- The $\mathsf{r_{member}}$ function calculates the member reward, proportionally to their stake after the cost and margin are removed.


*Pool leader reward, from section 5.5.3 of [@delegation_design]* $$\begin{align*}
      & \mathsf{r_{operator}} \in \mathsf{Coin} \to \mathsf{PoolParam} \to [0,~1] \to [0,~1]NonNull \to \mathsf{Coin} \\
      & \mathsf{r_{operator}}~ \mathit{\hat{f}}~ \mathit{pool}~ \mathit{s}~ {\sigma} =
        \begin{cases}
        \hat{f} & \hat{f} \leq c\\
        c + \floor*{(\hat{f} - c)\cdot\left(m + (1-m)\cdot\frac{s}{\sigma}\right) }&
        \text{otherwise.}
      \end{cases} \\
      & ~~~\where \\
      & ~~~~~~~c = \mathsf{poolCost}~pool \\
      & ~~~~~~~m = \mathsf{poolMargin}~pool \\
\end{align*}$$

*Pool member reward, from section 5.5.3 of [@delegation_design]* $$\begin{align*}
    & \mathsf{r_{member}} \in \mathsf{Coin} \to \mathsf{PoolParam} \to [0,~1] \to [0,~1]NonNull \to \mathsf{Coin} \\
    & \mathsf{r_{member}}~ \mathit{\hat{f}}~ \mathit{pool}~ \mathit{t}~ {\sigma} =
      \begin{cases}
        0 & \hat{f} \leq c\\
        \floor*{(\hat{f} - c)\cdot(1-m)\cdot\frac{t}{\sigma}} &
        \text{otherwise.}
      \end{cases} \\
    & ~~~\where \\
    & ~~~~~~~c = \mathsf{poolCost}~pool \\
    & ~~~~~~~m = \mathsf{poolMargin}~pool \\
\end{align*}$$

**Functions used in the Reward Splitting**
Finally, the full reward calculation is presented in Figure 15. The calculation is done pool-by-pool.

- The $\mathsf{rewardOnePool}$ function calculates the rewards given out to each member of a given pool. The pool leader is identified by the stake credential of the pool operator. The function returns the rewards, calculated as follows:

  - $\mathit{pstake}$, the total amount of stake controlled by the stake pool.

  - $\mathit{ostake}$, the total amount of stake controlled by the stake pool operator and owners

  - $\sigma$, the total proportion of stake controlled by the stake pool.

  - $\overline{N}$, the expected number of blocks the pool should have produced.

  - $\mathit{pledge}$, the pool's pledge in lovelace.

  - $p_r$, the pool's pledge, as a proportion of active stake.

  - $\mathit{maxP}$, maximum rewards the pool can claim if the pledge is met, and zero otherwise.

  - $\mathit{poolR}$, the pool's actual reward, based on its performance.

  - $\mathit{mRewards}$, the member's rewards as a mapping of reward accounts to coin.

  - $\mathit{lReward}$, the leader's reward as coin.

  - $\mathit{potentialRewards}$, the combination of $\mathit{mRewards}$ and $\mathit{lRewards}$.

  - $\mathit{rewards}$, the restriction of $\mathit{potentialRewards}$ to the active reward accounts.

- The $\mathsf{reward}$ function applies $\mathsf{rewardOnePool}$ to each registered stake pool.


*Calculation to reward a single stake pool* $$\begin{align*}
    & \mathsf{rewardOnePool} \in \mathsf{PParams} \to \mathsf{Coin} \to \N \to \N \to \mathsf{KeyHash} \to \mathsf{PoolParam}\\
      & ~~~\to \mathsf{Stake}\to \mathsf{Coin} \to \mathbb{P}~\mathsf{AddrRWD}
           \to (\mathsf{AddrRWD} \mapsto \mathsf{Coin}) \\
      & \mathsf{rewardOnePool}
  ~\mathit{pp}~\mathit{R}~\mathit{n}~\mathit{\overline{N}}~\mathit{poolHK}~\mathit{pool}~\mathit{stake}~\mathit{tot}~\mathit{addrs_{rew}} =
          \mathit{rewards}\\
      & ~~~\where \\
      & ~~~~~~~\mathit{pstake} = \sum_{\_\mapsto c\in\mathit{stake}} c \\
      & ~~~~~~~\mathit{ostake} = \sum_{\substack{
        hk_\mapsto c\in\mathit{stake}\\
        hk\in(\mathsf{poolOwners}~\mathit{pool})\\
        }} c \\
      & ~~~~~~~\sigma = \mathit{pstake} / tot \\
      & ~~~~~~~\mathit{pledge} = \mathsf{poolPledge}~pool \\
      & ~~~~~~~p_{r} = \mathit{pledge} / \mathit{tot} \\
      & ~~~~~~~maxP =
      \begin{cases}
        \mathsf{maxPool}~\mathit{pp}~\mathit{R}~\sigma~\mathit{p_r}&
        \mathit{pledge} \leq \mathit{ostake}\\
        0 & \text{otherwise.}
      \end{cases} \\
      & ~~~~~~~\mathit{poolR} = \mathsf{poolReward}~\mathit{(\mathsf{d}~pp)}~{\sigma}~\mathit{n}~\mathit{\overline{N}}~\mathit{maxP} \\
      & ~~~~~~~\mathit{mRewards} = \left\{
                                  \addrRw~hk\mapsto\mathsf{r_{member}}~ \mathit{poolR}~ \mathit{pool}~ \mathit{\frac{c}{tot}}~ {\sigma}
                                  ~\Big\vert~
                                  hk\mapsto c\in\mathit{stake},~~hk \neq\mathit{poolHK}
                               \right\}\\
      & ~~~~~~~\mathit{lReward} = \mathsf{r_{operator}}~ \mathit{poolR}~ \mathit{pool}~ \mathit{\frac{\mathit{ostake}}{tot}}~ {\sigma} \\
      & ~~~~~~~\mathit{potentialRewards} =
                 \mathit{mRewards} \cup
                 \{(\mathsf{poolRAcnt}~\mathit{pool})\mapsto\mathit{lReward}\} \\
      & ~~~~~~~\mathit{rewards} = \mathit{addrs_{rew}}\lhd{\mathit{potentialRewards}} \\
\end{align*}$$

*Calculation to reward all stake pools* $$\begin{align*}
      & \mathsf{reward} \in \mathsf{PParams} \to \mathsf{BlocksMade}\to \mathsf{Coin}\to \mathbb{P}~\mathsf{AddrRWD}
      \to (\mathsf{KeyHash} \mapsto \mathsf{PoolParam}) \\
      & ~~~\to \mathsf{Stake}\to (\mathsf{KeyHash}_{stake} \mapsto \mathsf{KeyHash}_{pool}) \to
      \mathsf{Coin} \to (\mathsf{AddrRWD} \mapsto \mathsf{Coin})\\
      & \mathsf{reward}
  ~ \mathit{pp}~ \mathit{blocks}~ \mathit{R}~ \mathit{addrs_{rew}}~ \mathit{poolParams}~ \mathit{stake}~ \mathit{delegs}~ \mathit{total}
          = \mathit{rewards}\\
      & ~~~\where \\
      & ~~~~~~~tot = \sum_{\_\mapsto c\in \mathit{stake}}c \\
      & ~~~~~~~\mathit{\overline{N}} = \sum_{\_\mapsto m\in blocks}m \\
      & ~~~~~~~pdata = \left\{
        hk\mapsto \left(p,~n,~\mathsf{poolStake}~ \mathit{hk}~ \mathit{delegs}~ \mathit{stake}\right)
        \mathrel{\Bigg|}
        \begin{array}{rcl}
          hk & \mathit{p} & \mathit{poolParams} \\
          hk & \mathit{n} & \mathit{blocks} \\
        \end{array}
      \right\} \\
      & ~~~~~~~\mathit{results} = \left\{
        hk \mapsto \mathsf{rewardOnePool}
  ~\mathit{pp}~\mathit{R}~\mathit{n}~\mathit{\overline{N}}~\mathit{hk}~\mathit{p}~\mathit{s}~\mathit{tot}~\mathit{addrs_{rew}}
                 \mid
        hk\mapsto(p, n, s)\in\mathit{pdata} \right\} \\
      & ~~~~~~~\mathit{rewards} = \bigcup_{\underline{\phantom{a}}\mapsto\mathit{r}\in\mathit{results}}\mathit{r}
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
    \mathsf{RewardUpdate}=
    \left(
      \begin{array}{rll}
        \Delta t & \mathsf{Coin} & \text{change to the treasury} \\
        \Delta r & \mathsf{Coin} & \text{change to the reserves} \\
        \mathit{rs} & \mathsf{AddrRWD}\mapsto\mathsf{Coin} & \text{new individual rewards} \\
        \Delta f & \mathsf{Coin} & \text{change to the fee pot} \\
      \end{array}
    \right)
\end{equation*}$$

**Rewards Update type**
Figure 18 defines two functions, $\mathsf{createRUpd}$ to create a reward update and $\mathsf{applyRUpd}$ to apply a reward update to an instance of $\mathsf{EpochState}$.

The $\mathsf{createRUpd}$ function does the following:

- Note that for all the calculations below, we use the previous protocol parameters $\mathit{prevPp}$, which corresponds to the parameters during the epoch for which we are creating rewards.

- First we calculate the change to the reserves, as determined by the $\rho$ protocol parameter.

- Next we calculate $\mathit{rewardPot}$, the total amount of coin available for rewards this epoch, as described in section 6.4 of [@delegation_design]. It consists of:

  - The fee pot, containing the transaction fees from the epoch.

  - The amount of monetary expansion from the reserves, calculated above.

  Note that the fee pot is taken from the snapshot taken at the epoch boundary. (See Figure6).

- Next we calculate the proportion of the reward pot that will move to the treasury, as determined by the $\tau$ protocol parameter. The remaining pot is called the $\mathit{R}$, just as in section 6.5 of [@delegation_design].

- The rewards are calculated, using the oldest stake distribution snapshot (the one labeled "go"). As given by $\mathsf{maxPool}$, each pool can receive a maximal amount, determined by its performance. The difference between the maximal amount and the actual amount received is added to the amount moved to the treasury.

- The fee pot will be reduced by $\mathit{feeSS}$.

Note that fees are not explicitly removed from any account: the fees come from transactions paying them and are accounted for whenever transactions are processed and when the deposit decay value comes from returning smaller refunds for deposits than were paid upon depositing.

The $\mathsf{applyRUpd}$ function does the following:

- Adjust the treasury, reserves and fee pots by the appropriate amounts.

- Add each individual reward to the global reward mapping. We must be careful, though, not to give out rewards to accounts that have been deregistered after the reward update was created.

  - Rewards for accounts that are still registered are added to the reward mappings.

  - The sum of the unregistered rewards are added to the reserves.

These two functions will be used in the blockchain transition systems in Section sec:chain. In particular, $\mathsf{createRUpd}$ will be used in Equation eq:reward-update, and $\mathsf{applyRUpd}$ will be used in Equation eq:new-epoch.


*Calculation to create a reward update* $$\begin{align*}
    & \mathsf{createRUpd} \in \N \to \mathsf{BlocksMade}\to \mathsf{EpochState}\to \mathsf{Coin} \to \mathsf{RewardUpdate}\\
    & \mathsf{createRUpd}~\mathit{slotsPerEpoch}~\mathit{b}~\mathit{es}~\mathit{total} = \left(
      \Delta t_1,-~\Delta r_1+\Delta r_2,~\mathit{rs},~-\mathit{feeSS}\right) \\
    & ~~~\where \\
    & ~~~~~~~(\mathit{acnt},~\mathit{ss},~\mathit{ls},~\mathit{prevPp},~\underline{\phantom{a}}) = \mathit{es} \\
    & ~~~~~~~(\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{pstake_{go}},~\mathit{poolsSS},~\mathit{feeSS}) = \mathit{ss}\\
    & ~~~~~~~(\mathit{stake},~\mathit{delegs}) = \mathit{pstate_{go}} \\
    & ~~~~~~~(\underline{\phantom{a}},~\mathit{reserves}) = \mathit{acnt} \\
    & ~~~~~~~\left(
      \underline{\phantom{a}},~
      \left(
      \left(\mathit{rewards},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}}\right)~
      \underline{\phantom{a}}
      \right)
      \right) = \mathit{ls} \\
    & ~~~~~~~\Delta r_1 = \floor*{\min(1,\eta) \cdot (\mathsf{rho}~\mathit{prevPp}) \cdot
      \mathit{reserves}}
    \\
    & ~~~~~~~\eta = \frac{blocksMade}{\mathit{slotsPerEpoch} \cdot \mathsf{ActiveSlotCoeff}} \\
    & ~~~~~~~\mathit{rewardPot} = \mathit{feeSS} + \Delta r_1 \\
    & ~~~~~~~\Delta t_1 = \floor*{(\mathsf{tau}~\mathit{prevPp}) \cdot \mathit{rewardPot}} \\
    & ~~~~~~~\mathit{R} = \mathit{rewardPot} - \Delta t_1 \\
    & ~~~~~~~\mathit{circulation} = \mathit{total} - \mathit{reserves} \\
    & ~~~~~~~\mathit{rs}
      = \mathsf{reward}
  ~ \mathit{prevPp}~ \mathit{b}~ \mathit{R}~ \mathit{(\mathrm{dom}~rewards)}~ \mathit{poolsSS}~ \mathit{stake}~ \mathit{delegs}~ \mathit{circulation} \\
    & ~~~~~~~\Delta r_{2} = R - \left(\sum\limits_{\_\mapsto c\in\mathit{rs}}c\right) \\
    & ~~~~~~~blocksMade = \sum_{\underline{\phantom{a}} \mapsto m \in b}m
\end{align*}$$

**Reward Update Creation**
*Applying a reward update* $$\begin{align*}
      & \mathsf{applyRUpd} \in \mathsf{RewardUpdate}\to \mathsf{EpochState}\to \mathsf{EpochState}\\
      & \mathsf{applyRUpd}~
      \left(
        \begin{array}{c}
          \Delta t \\
          \Delta r \\
          \mathit{rs} \\
          \Delta f \\
        \end{array}
    \right)
      \left(
        \begin{array}{c}
          \mathit{treasury} \\
          \mathit{reserves} \\
          ~ \\
          \mathit{rewards} \\
          \mathit{delegations} \\
          \mathit{ptrs} \\
          \mathit{genDelegs} \\
          \mathit{fGenDelegs} \\
          \mathit{i_{rwd}}
          \\~ \\
          \mathit{poolParams} \\
          \mathit{fPoolParams} \\
          \mathit{retiring} \\
          ~ \\
          \mathit{utxo} \\
          \mathit{deposits} \\
          \mathit{fees} \\
          \mathit{up} \\
          ~ \\
          \mathit{prevPp} \\
          \mathit{pp} \\
        \end{array}
      \right)
      =
      \left(
        \begin{array}{c}
          \mathsf{varUpdate}~\mathit{treasury} + \Delta t + \mathit{unregRU'}\\
          \mathsf{varUpdate}~\mathit{reserves} + \Delta r\\
          ~ \\
          \mathsf{varUpdate}~\mathit{rewards}\unionoverridePlus\mathit{regRU} \\
          \mathit{delegations} \\
          \mathit{ptrs} \\
          \mathit{genDelegs} \\
          \mathit{fGenDelegs} \\
          \mathit{i_{rwd}}
          \\~ \\
          \mathit{poolParams} \\
          \mathit{fPoolParams} \\
          \mathit{retiring} \\
          ~ \\
          \mathit{utxo} \\
          \mathit{deposits} \\
          \mathsf{varUpdate}~\mathit{fees}+\Delta f \\
          \mathit{up} \\
          ~ \\
          \mathit{prevPp} \\
          \mathit{pp} \\
        \end{array}
    \right) \\
    & ~~~\where \\
    & ~~~~~~~\mathit{regRU}=(\mathrm{dom}~rewards)\lhd rs\\
    & ~~~~~~~\mathit{unregRU}=(\mathrm{dom}~rewards)\mathbin{\rlap{\lhd}/} rs\\
    & ~~~~~~~\mathit{unregRU'}=\sum\limits_{\underline{\phantom{a}}\mapsto c\in\mathit{unregRU}} \mathit{c}\\
\end{align*}$$

**Reward Update Application**