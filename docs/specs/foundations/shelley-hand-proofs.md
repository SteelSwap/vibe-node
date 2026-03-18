## Preservation of Value
As visualized in Figure fig:fund-preservation, the total amount of lovelace in any given chain state $\mathit{s}\in\mathsf{ChainState}$ is completely contained within the values of the six variables:

  **Variable**   **Name in Figure fig:fund-preservation**   **Nesting Inside Chain State**   **Kind**
  -------------- -------------------------------------------------------------------------------------------------------------------------------- -------------------------------- --------------------------
  utxo           circulation                                                                                                                      s.nes.es.ls.utxoSt               Map over Lovelace Values
  deposits       deposits                                                                                                                         s.nes.es.ls.utxoSt               Lovelace Value ($\mathsf{Coin}$)
  fees           fees                                                                                                                             s.nes.es.ls.utxoSt               Lovelace Value ($\mathsf{Coin}$)
  rewards        reward accounts                                                                                                                  s.nes.es.ls.dpstate.dstate       Lovelace Value ($\mathsf{Coin}$)
  treasury       treasury                                                                                                                         s.nes.es.acnt                    Lovelace Value ($\mathsf{Coin}$)
  reserves       reserves                                                                                                                         s.nes.es.acnt                    Map over Lovelace Values

Notice that $\mathit{deposits}$, $\mathit{fees}$, $\mathit{treasury}$, and $\mathit{reserves}$ are all single lovelace values, while $\mathit{utxo}$, and $\mathit{rewards}$ are maps whose values are lovelace.

We define the *Lovelace Value* of a given chain state as:

::: definition
[]{#def:val label="def:val"} $$\begin{equation*}
    \mathsf{Val}(s~\in~\mathit{State}) =
        \mathsf{Val}(\mathit{utxo}) +
            \mathsf{Val}(\mathit{deposits}) +
            \mathsf{Val}(\mathit{fees}) +
            \mathsf{Val}(\mathit{reserves}) +
            \mathsf{Val}(\mathit{treasury}) +
            \mathsf{Val}(\mathit{rewards})
\end{equation*}$$ where $$\begin{equation*}
      \mathsf{Val}(x \in \mathsf{Coin}) = x
\end{equation*}$$ $$\begin{equation*}
      \mathsf{Val}((\underline{\phantom{a}}\mapsto (y \in \mathsf{Coin}))^{*}) = \sum y
\end{equation*}$$

For any state that is used in a given subtransition of $\mathsf{CHAIN}$, we define $\mathsf{Val}{}$ in an analogous way, setting the value of any variable that is not explicitly represented in the state to zero. For example, given $\mathit{utxoSt}\in\mathsf{UTxOState}$, $$\begin{equation*}
  \mathsf{Val}(\mathit{utxoSt}) =
  \left(\sum_{\underline{\phantom{a}}\mapsto(\underline{\phantom{a}},~v)\in\mathit{utxo}}v\right) + \mathit{deposits} + \mathit{fees}
\end{equation*}$$

The key property that we want to prove is that no semantic transition changes the value that is captured in the state ($\mathsf{Val}{s}$). This property is easy to state: intuitively, the *Lovelace Value*before the transition is the same as the *Lovelace Value* after that transition.

::: theorem
[]{#thm:chain-pres-of-value label="thm:chain-pres-of-value"} For all environments $e$, blocks $b$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\xrightarrow[\mathsf{\hyperref[fig:rules:chain]{chain}}]{}{b}s'
\end{equation*}$$ then $$\begin{equation*}
    \mathsf{Val}(s) = \mathsf{Val}(s')
\end{equation*}$$

We will prove the soundness of Theorem thm:chain-pres-of-value via a few lemmas.

::: lemma
[]{#lemma:value-sum-pres-1 label="lemma:value-sum-pres-1"} For any mapping $m:A\mapsto\mathsf{Coin}$ and set $s\in\mathbb{P}~A$, $$\begin{equation*}
    \mathsf{Val}(\mathit{m}) = \mathsf{Val}(s\mathbin{\rlap{\lhd}/} m) + \mathsf{Val}(s\lhd m)
\end{equation*}$$

::: proof
*Proof.* easy ◻

::: lemma
[]{#lemma:value-sum-pres-2 label="lemma:value-sum-pres-2"} For any mappings $m_1, m_2:A\mapsto\mathsf{Coin}$, if $\mathrm{dom}~m_1\cap\mathrm{dom}~m_2=\emptyset$, then $$\begin{equation*}
    \mathsf{Val}(m_1\cup m_2) = \mathsf{Val}(m_1) + \mathsf{Val}(m_2)
\end{equation*}$$

::: proof
*Proof.* easy ◻

::: lemma
[]{#lemma:utxo-pres-of-value label="lemma:utxo-pres-of-value"} For all environments $e$, transactions $t$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\xrightarrow[\mathsf{\hyperref[fig:rules:utxo-shelley]{utxo}}]{}{t}s'
\end{equation*}$$ then $$\begin{equation*}
    \mathsf{Val}(s) + w = \mathsf{Val}(s')
\end{equation*}$$ where $w = \mathsf{wbalance}~(\mathsf{txwdrls}~{t})$.

::: proof
*Proof.* The proof is essentially unfolding the definition of the predicate $$\begin{equation}
    \label{cons-is-prod}
    \mathsf{consumed}~pp~utxo~t = \mathsf{produced}~pp~stpools{t}
\end{equation}$$ and applying a little algebra. If we let: $$\begin{equation*}
    \begin{array}{rl}
      k & \mathsf{keyRefunds}~pp~stkCreds{t} \\
      f & \mathsf{txfee}~t \\
      d & \mathsf{totalDeposits}~pp~stpools{(\mathsf{txcerts}~t)} \\
    \end{array}
\end{equation*}$$ then equation cons-is-prod can be rewritten as: $$\begin{equation*}
    \mathsf{Val}(\mathsf{txins}~t \lhd{\mathit{utxo}}) + w + k = \mathsf{Val}(\mathsf{outs}~t) + f + d
\end{equation*}$$ where $\mathsf{outs}~$ is defined in Figure fig:functions:utxo and returns a value of type $\mathsf{UTxO}$. Therefore, moving $k$ to the right and adding $\mathsf{txins}~t \mathbin{\rlap{\lhd}/}{\mathit{utxo}}$ to each side, $$\begin{equation*}
    \mathsf{Val}(\mathsf{txins}~t \lhd{\mathit{utxo}}) + \mathsf{Val}(\mathsf{txins}~t \mathbin{\rlap{\lhd}/}{\mathit{utxo}}) + w
    = \mathsf{Val}(\mathsf{outs}~t) + f + d - k + \mathsf{Val}(\mathsf{txins}~t \mathbin{\rlap{\lhd}/}{\mathit{utxo}})
\end{equation*}$$ (Though not needed for the proof at hand, note that $d-k$ is non-negative since the deposits will always be large enough to cover the current obligation. See Theorem thm:non-neg-deposits.) It then follows that: $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{Val}(\mathit{utxo}) + w
    & \mathsf{Val}(\mathsf{outs}~t) + f + d - k + \mathsf{Val}(\mathsf{txins}~t \mathbin{\rlap{\lhd}/}{\mathit{utxo}})
    & \text{(by Lemma~\ref{lemma:value-sum-pres-1})}
    \\
    & \mathsf{Val}((\mathsf{txins}~t \mathbin{\rlap{\lhd}/}{\mathit{utxo}})\cup\mathsf{outs}~t) + (d - k) + f
    & \text{(by Lemma~\ref{lemma:value-sum-pres-2})}
    \end{array}
\end{equation*}$$ Note that in order to apply Lemma lemma:value-sum-pres-2 above, it must be true that $(\mathsf{txins}~t \mathbin{\rlap{\lhd}/}{\mathit{utxo}})$ and $(\mathsf{outs}~t)$ have disjoint domains, which follows from the uniqueness of the transaction IDs.

Therefore, by adding the deposits and fees from $s$ to the equality above, it follows that $\mathsf{Val}(s) + w = \mathsf{Val}(s')$. ◻

::: lemma
[]{#lemma:deleg-pres-of-value label="lemma:deleg-pres-of-value"} For all environments $e$, transactions $c$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\xrightarrow[\mathsf{\hyperref[fig:delegation-rules]{deleg}}]{}{c}s'
\end{equation*}$$ then $$\begin{equation*}
    \mathsf{Val}(s) = \mathsf{Val}(s')
\end{equation*}$$

::: proof
*Proof.* The only variable with value in this transition is . Only two of the rules in $\mathsf{DELEG}$ can change , namely $\mathsf{Deleg{-}Reg}$ and $\mathsf{Deleg{-}Dereg}$. However, $\mathsf{Deleg{-}Reg}$ only adds a zero value, and $\mathsf{Deleg{-}Dereg}$ only removes a zero value. ◻

::: lemma
[]{#lemma:delegs-pres-of-value label="lemma:delegs-pres-of-value"} For all environments $e$, certificates $\Gamma$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\xrightarrow[\mathsf{\hyperref[fig:rules:delegation-sequence]{delegs}}]{}{\Gamma}s'
\end{equation*}$$ then $$\begin{equation*}
    \mathsf{Val}(s) = \mathsf{Val}(s') + w
\end{equation*}$$ where $w = \mathsf{wbalance}~(\mathsf{txwdrls}~{t})$, and $t$ is the transaction in the environment $e$.

::: proof
*Proof.* The proof is by induction on the length of $\Gamma$. Note that the only variable with value in this transition is .

*In the base case*, we look at the rule $\mathsf{Seq{-}delg{-}base}$. Since $\mathit{wdrls}\subseteq\mathit{rewards}$, then $\mathit{rewards} = \mathit{wdrls}\cup\mathit{(\mathit{rewards}\setminus\mathit{wdrls})}$. Therefore $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{Val}{(\mathit{rewards})}
      & \mathsf{Val}{(\mathit{rewards}\setminus\mathit{wdrls})} + \mathsf{Val}{(\mathit{wdrls})}
      & \text{by Lemma~\ref{lemma:value-sum-pres-2}}
      \\
      & \mathsf{Val}{(\mathit{rewards}\setminus\mathit{wdrls})} + w
      & \text{by definition}
      \\
      & \mathsf{Val}\left(\mathit{rewards}\unionoverrideRight\{(w, 0) \mid w \in \dom \mathit{wdrls}\}\right) + w
    \end{array}
\end{equation*}$$ Therefore $\mathsf{Val}(s) = \mathsf{Val}(s')$.

*In the inductive case*, we look at the rule $\mathsf{Seq{-}delg{-}ind}$. In this case, the lemma then follows directly from Lemma lemma:deleg-pres-of-value. ◻

::: lemma
[]{#lemma:poolreap-pres-of-value label="lemma:poolreap-pres-of-value"} For all environments $e$, epoch $\epsilon$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\xrightarrow[\mathsf{\hyperref[fig:rules:pool-reap]{poolreap}}]{}{\epsilon}s'
\end{equation*}$$ then $$\begin{equation*}
    \mathsf{Val}(s) = \mathsf{Val}(s')
\end{equation*}$$

::: proof
*Proof.* The $\mathsf{POOLREAP}$ value is contained in $\mathit{deposits}$, $\mathit{treasury}$, and $\mathit{rewards}$. Notice that $\mathit{unclaimed}$ is added to $\mathit{treasury}$ and subtracted from the $\mathit{deposits}$. Moreover, $\mathit{refunded}$ is subtracted from $\mathit{deposits}$. (Note that $\mathit{deposits}-(\mathit{unclaimed}+\mathit{refunded})$ is non-negative by Theorem thm:non-neg-deposits.) It therefore suffices to show that $$\begin{equation*}
    \begin{array}{rl}
    \mathsf{Val}(\mathit{rewards}\unionoverridePlus\mathit{refunds})
    & \mathsf{Val}(\mathit{rewards}) + \mathsf{Val}(\mathit{refunds})
    \\
    & \mathsf{Val}(\mathit{rewards}) + \mathit{refunded}
    \end{array}
\end{equation*}$$ But this is clear from the definition of $\unionoverridePlus$. ◻

::: lemma
[]{#lemma:ru-pres-of-value label="lemma:ru-pres-of-value"} For every $(\Delta t,~\Delta r,~\mathit{rs},~\Delta f)$ in the range of $\mathsf{createRUpd}$, $$\begin{equation*}
    \Delta t + \Delta r + \mathsf{Val}(rs) + \Delta f = 0
\end{equation*}$$

::: proof
*Proof.* In the definition of $\mathsf{createRUpd}$ in Figure fig:functions:reward-update-creation, We see that: $$\begin{equation*}
    \begin{array}{rl}
      \mathit{rewardPot} & \mathit{feeSS} + \Delta r \\
      \mathit{R} & \mathit{rewardPot} - \Delta t_1 \\
      \Delta t_2 & R - \mathsf{Val}(\mathit{rs})\\
      \Delta t & \Delta t_1 + \Delta t_2 \\
    \end{array}
\end{equation*}$$ Therefore $$\begin{equation*}
    \begin{array}{rl}
      (\mathit{feeSS} + \Delta r) & \mathit{rewardPot} = R + \Delta t_1 = \Delta t_2 + \mathsf{Val}(rs) + \Delta t_1  \\
      0 & (\Delta t_1 + \Delta t_2 ) - \Delta r + \mathsf{Val}(rs)- \mathit{feeSS} \\
      0 & \Delta t - \Delta r + \mathsf{Val}(rs)- \mathit{feeSS} \\
    \end{array}
\end{equation*}$$ It then suffices to notice that $\mathsf{createRUpd}$ returns $(\Delta t,-~\Delta r,~\mathit{rs},~-\mathit{feeSS})$. ◻

Note that Lemma lemma:ru-pres-of-value is not strictly need for the proof of Theorem thm:chain-pres-of-value, since the $\mathsf{NEWEPOCH}$ transition requires that $\Delta t + \Delta r + \mathsf{Val}(rs) + \Delta f = 0$ holds. It does, however, give us confidence that the $\mathsf{CHAIN}$ transition can proceed.

We are now ready to prove Theorem thm:chain-pres-of-value.

::: proof
*Proof.* For a given transition $\mathsf{TR}$, let be the statement:

Our goal is to prove . Lemmas lemma:utxo-pres-of-value and lemma:delegs-pres-of-value imply , since $\mathsf{UTXOW}$ transforms state exactly as $\mathsf{UTXO}$ does. then follows by straightforward induction on the length of $\Gamma$: the base case is trivial; and the inductive case follows directly from . holds trivially, since it contains no value. Similarly, holds since $\mathit{diff}$ is added to $\mathit{reserves}$ and subtracted from $\mathit{deposits}$. Therefore holds by Lemma lemma:poolreap-pres-of-value. holds since $\mathsf{Val}{i_{rwd}'}=\mathit{tot}$ in Figure fig:rules:mir. Morover, holds in the presence of $\mathsf{applyRUpd}$ since the transition requires $\Delta t + \Delta r + \mathsf{Val}(rs) + \Delta f = 0$. easily follows from this. ◻

## Non-negative Deposit Pot
The *deposit pot* (the variable $\mathit{deposits}$ in the UTxO State) represents the amount of *lovelace* that is set aside by the system as a whole for refunding deposits. Deposits are added to this pot, which then decays exponentially over time, and is also depleted by any refunded deposits. At an epoch boundary, the decayed parts of any deposits (including, possibly, deposits for any transactions that will complete in future epochs) will be distributed as additional *rewards*, as described in [@delegation_design]. Since $\mathit{deposits}$ is only used to record the value of future refunds or rewards whose costs have already been incurred, both it and any reward value will always be non-negative. Note that there are two types of deposits which are recorded in the same pot: those for stake keys; and those for stake pools. Stake keys are deregistered in the slot in which the deregistration certificates is processed. Stake pools, however, are staged for retirement on epoch boundaries. The following theorem ensures that the deposit pot is properly maintained and will always be large enough to meet all of its obligations.

:::: {.figure latex-placement="h!"}
  **Variable**   **Value**     **Nesting Inside Chain State**        **Kind**
  -------------- ------------- ------------------------------------- -------------------------------------------
  deposits       0             s.nes.es.ls.utxoSt                    $\mathsf{Coin}$
  stkCreds       $\emptyset$   s.nes.es.ls.dpstate.dstate.stkCreds   $\mathsf{StakeCreds}$ ($\mathsf{Credential}\mapsto\mathsf{Slot}$)
  stpools        $\emptyset$   s.nes.es.ls.dpstate.pstate.stpools    $\mathsf{StakePools}$ ($\mathsf{KeyHash}\mapsto\mathsf{Slot}$)

**Initial Chain State**
::: theorem
[]{#thm:non-neg-deposits label="thm:non-neg-deposits"} Let $n\in\N$ and $c_0\in\mathsf{ChainState}$ be a chain state in which $\mathit{deposits} ~=~0$, $\mathit{stkCreds}~=~\emptyset$ and $\mathit{stPools}~=~\emptyset$, as shown above: If $$\begin{equation*}
    s_0\vdash c_0\xrightarrow[\mathsf{\hyperref[fig:rules:chain]{chain}}]{}{b_0}c_1,~~
    s_1\vdash c_1\xrightarrow[\mathsf{\hyperref[fig:rules:chain]{chain}}]{}{b_1}c_2,~~
    \ldots,~~
    s_n\vdash c_n\xrightarrow[\mathsf{\hyperref[fig:rules:chain]{chain}}]{}{b_n}c_{n+1},~~n \ge 0
\end{equation*}$$ is a sequence of valid $\mathsf{CHAIN}$ transitions, then $\forall i, 0 \le i \le n, \mathit{deposits} ~(c_{n+1}) \ge 0$.

::: proof
*Proof.* We will prove a slightly stronger condition, namely that some stronger invariants hold most of the time, and that when they do fail to hold, then $\mathit{deposits}$ is still non-negative. These stronger invariants will require a few additional definitions. Given a slot $s$, let $\ell(s)$ be the first slot of the epoch that $s$ occurs in, that is $\ell = \mathsf{firstSlot}\circ\mathsf{epoch}$. Given a mapping $m\in\mathsf{T}\to\mathsf{Slot}$ and a slot $s\in\mathsf{Slot}$, let $\mathsf{sep}$ be the function that separates $m$ into two maps, those whose value is strictly less than $s$ and those whose value is at least $s$. So, $$\begin{equation*}
    \mathsf{sep}~m~s = \forall x\mapsto t~\in~m,~~
    \left(\{x\mapsto t~\mid~t<s\},~\{x\mapsto t~\mid~t\geq s\}\right)
\end{equation*}$$

If we assume that the *protocol parameters*, $pp$, are fixed[^1], then we can provide convenience functions $R_c$ and $R_p$ for the *stake credential* and *stake pool* refunds, respectively: $$\begin{equation*}
    \begin{array}{rl}
      R_c~s_0~s_1 & \mathsf{refund}~d_{val}~d_{min}~\lambda_d~s_1-s_0 \\
      R_p~s_0~s_1 & \mathsf{refund}~p_{val}~p_{min}~\lambda_p~s_1-s_0 \\
    \end{array}
\end{equation*}$$ where $d_{val}$, $d_{min}$, $\lambda_d$, $p_{val}$, $p_{min}$, $\lambda_p$ are the protocol parameter values from $pp$, and $\mathsf{refund}$ is defined in Figure fig:functions:deposits-refunds. We let ("Deposits (precisely) Big Enough\"), be the following property: $$\begin{equation}
\tag{DBE}\label{DBE}
    \mathit{deposits}
    = \left(\sum_{\underline{\phantom{a}}\mapsto t\in C_{old}}R_c~t~\ell(s)\right)
    + |C_{new}|\cdot d_{val}
    + \left(\sum_{\underline{\phantom{a}}\mapsto t\in P_{old}}R_p~t~\ell(s)\right)
    + |P_{new}|\cdot p_{val}
\end{equation}$$ where $$\begin{equation*}
    \begin{array}{rl}
      C_{old},~C_{new} & \mathsf{sep}~\mathit{stkCreds}~{\ell(s)} \\
      P_{old},~P_{new} & \mathsf{sep}~\mathit{stpools}~{\ell(s)},
    \end{array}
\end{equation*}$$ for some slot, $s$, where $\mathit{pp}$, $\mathit{stkCreds}$, $\mathit{stpools}$ are in the corresponding chain state, $c$. In other words, asserts that the deposit pot is equal to the sum of the deposit refunds that were available at the previous epoch boundary, plus the sum of the initial deposit values for all the deposits from the current epoch.

Notice that for a chain state $c$ and slot $s$, if the range of $\mathit{stkCreds}$ and $\mathit{stpools}$ contains only slots from the previous epoch, then is equivalent to $$\begin{equation}
\tag{DEO}\label{DEO}
    \mathit{deposits} = \mathsf{obligation}~pp~stkCreds~stpools{\ell(s)}
\end{equation}$$ where $\mathsf{obligation}$ is defined in Figure fig:funcs:epoch-helper-rewards. It is generally true that holds after each subtransition of $s_i\vdash c_i\xrightarrow[\mathsf{\hyperref[fig:rules:chain]{chain}}]{}{b_i}c_{i+1}$. However, this invariant can fail to hold after the $\hyperref[fig:delegation-transitions]{\mathsf{DELEG}}$ transition, since this transition can add and remove stake credentials, and can also add stake pools, but the deposit pot is not adjusted accordingly until the next subtransiton of $\hyperref[fig:rules:ledger]{\mathsf{LEDGER}}$, namely $\hyperref[fig:rules:utxo-shelley]{\mathsf{UTXO}}$. The invariant can also fail to hold if the slot increases while the chain state remains the same. That is, if holds, then can fail to hold if $\mathsf{epoch}~s_i < \mathsf{epoch}~s_{i+1}$, since the value of the deposit in the left hand side of equation DBE remains the same, but the refunded values become smaller[^2]. Therefore, in this situation we can consider the slightly weaker constraint: $$\begin{equation}
\tag{DGO}\label{DGTO}
    \mathit{deposits} \geq \mathsf{obligation}~pp~stkCreds~stpools{\ell(s)}
\end{equation}$$ The difference between the left and right hand sides of the inequality corresponds to the lovelace value in $c_{i+1}$ that decays between $s_i$ and $s_{i+1}$.

There are four sub-transitions where $\mathit{deposits}$ is changed: $\mathsf{SNAP}$ (Figure fig:rules:snapshot), $\mathsf{POOLREAP}$ (Figure fig:rules:pool-reap), $\mathsf{NEWPP}$ (Figure fig:rules:new-proto-param), $\mathsf{UTXO}$ (Figure fig:rules:utxo-shelley). This ordering is also the order in which $\mathit{deposits}$ is changed. Of these sub-transitions, only $\mathsf{UTXO}$ actually changes the value of $\mathit{deposits}$ when $s_i$ is in the same epoch as $s_i$. (We say that $s_i$ *crosses the epoch boundary* if the precondition of Rule eq:new-epoch in Figure fig:rules:new-epoch is met, namely if $\mathsf{epoch}~s_i \ge e_\ell+1$.) The proof then proceeds by induction on $n$, showing the following:

- Let $c$ be the chain state after the $\mathsf{SNAP}$ transition in $s_i\vdash c_i\xrightarrow[\mathsf{\hyperref[fig:rules:chain]{chain}}]{}{b_i}c_{i+1}$. If , then holds.

- $\mathsf{POOLREAP}$ preserves DBE.

- $\mathsf{NEWPP}$ preserves DBE.

- The property for $\mathsf{UTXO}$ requires a bit of explanation. Let $\mathit{nes}\in\mathsf{NewEpochState}$ be the new epoch state in $c_i$. Note that the property DBE makes sense for values of $\mathsf{NewEpochState}$ since it contains all the relevant variables. Similarly, DBE also makes sense for values of $\mathsf{UTxOState}\times\mathsf{PParams}$. Let $${\begin{array}{c}
             \mathit{gkeys} \\
           \end{array}}
          \vdash\mathit{nes}\xrightarrow[\mathsf{\hyperref[fig:rules:tick]{tick}}]{}{\mathit{bh}}\mathit{nes'}$$ be the first sub-transition of $s_i\vdash c_i\xrightarrow[\mathsf{\hyperref[fig:rules:chain]{chain}}]{}{b_i}c_{i+1}$. If holds, then holds for every transaction $tx$ in $b_i$, where: $$\mathit{env}\vdash \mathit{us} \xrightarrow[\mathsf{\hyperref[fig:rules:utxow-shelley]{utxo}}]{}{tx} \mathit{us'},$$ is a sub-transition of $s_i\vdash c_i\xrightarrow[\mathsf{\hyperref[fig:rules:chain]{chain}}]{}{b_i}c_{i+1}$, and $\mathit{pp}$ is the protocol parameters in $\mathit{nes'}$.

Case $\hyperref[fig:rules:snapshot]{\mathsf{SNAP}}$. We must show that if $c$ is the chain state after the $\mathsf{SNAP}$ transition in $s_i\vdash c_i\xrightarrow[\mathsf{\hyperref[fig:rules:chain]{chain}}]{}{b_i}c_{i+1}$, and holds, then so does . We can assume that $s_i$ crosses the epoch boundary, since otherwise the $\mathsf{SNAP}$ transition will not occur. Since the $\mathsf{SNAP}$ transition only happens within the $\mathsf{TICK}$ transition on the epoch boundary, it follows that $c_i$ does not contain any stake credentials or pools from the current epoch, and so DBE will be equivalent to DEO (the current epoch is $\mathsf{epoch}~s_i$). However, holds trivially, since it is determined from the $\mathsf{obligation}$ value.\
 \
Case $\hyperref[fig:rules:pool-reap]{\mathsf{POOLREAP}}$. We must show that DBE is preserved. We again assume that $s_i$ crosses the epoch boundary. The $\mathsf{POOLREAP}$ transition does the following:

1.  leaves $\mathit{stkCreds}$ unchanged,

2.  removes $\mathit{retired}$ from $\mathit{stpools}$,

3.  subtracts $\mathit{unclaimed}+\mathit{refunded}$ from $\mathit{deposits}$.

Notice that the domain of the $\mathit{pr}$ is $\mathit{retired}$, and similarly the domain of the $\mathit{rewardAcnts}$ is also $\mathit{retired}$ since the domains of $\mathit{stpools}$ and $\mathit{poolParams}$ are the same. Therefore $\mathit{retired}$ is the disjoint union of $\dom({\mathit{refunds}})$ and $\dom({\mathit{mRefunds}})$, so that $$\begin{equation*}
    \begin{array}{rl}
      \mathit{unclaimed}+\mathit{refunded}
      &
      \left(
        \sum\limits_{\underline{\phantom{a}}\mapsto t\in\mathit{refunds}}R_p~t~\ell(s)
      \right)+
      \left(
        \sum\limits_{\underline{\phantom{a}}\mapsto t\in\mathit{mRefunds}}R_p~t~\ell(s)
      \right)
      \\
      &
      \sum\limits_{\underline{\phantom{a}}\mapsto t\in\mathit{rewardAcnts'}}R_p~t~\ell(s)
      \\
      &
      \left(
        \sum\limits_{\underline{\phantom{a}}\mapsto t\in\mathit{stpools}}R_p~t~\ell(s)
      \right)-
      \left(
        \sum\limits_{\underline{\phantom{a}}\mapsto t\in\mathit{retired}\mathbin{\rlap{\lhd}/}\mathit{stpools}}R_p~t~\ell(s)
      \right)
    \end{array}
\end{equation*}$$ Therefore, it follows that if DEO holds before $\mathsf{POOLREAP}$, then it also holds afterwards.\
 \
Case $\hyperref[fig:rules:new-proto-param]{\mathsf{NEWPP}}$. We must show that DBE is preserved. We again assume that $s_i$ crosses the epoch boundary. In this transition $\mathit{pp}$ can change, but $\mathit{stkCreds}$, $\mathit{stpools}$, and $\mathit{deposits}$ do not change. As in the $\mathsf{SNAP}$ case, holds trivially, since it is set to the value that is determined by $\mathsf{obligation}$.\
 \
Case $\hyperref[fig:rules:utxo-shelley]{\mathsf{UTXO}}$. We assume that holds, where $\mathit{nes'}$ is the new epoch state after the $\mathsf{TICK}$ transition. We must show that DBE is preserved after each $\mathsf{UTXO}$ transition. The $\mathsf{DELEGS}$ transition can result in values being added to or deleted from $\mathit{stkCreds}$, and added to $\mathit{stpools}$. Let $A_s$ be the added stake credentials, $D_s$ be the deleted credentials, and $A_p$ be the added stake pools, where $\mathit{stkCreds}'$ is the stake credential mapping $\mathit{stpools}'$ is the stake pools, and $\mathit{deposits}'$ is the deposit pot after $\mathsf{DELEGS}$. We have that $$\begin{equation*}
    \begin{array}{rcl}
      \mathit{D_s} & \subseteq & \mathit{\mathit{stkCreds}\cup\mathit{A_s}} \\
      \mathit{stkCreds}' & = & (\mathit{stkCreds}\cup\mathit{A_s})\setminus\mathit{D_s} \\
      \mathit{stpools}' & = & \mathit{stpools}\cup\mathit{A_p} \\
    \end{array}
\end{equation*}$$ The slots in the range of $A_s$ will all be equal to $s_i$, but the slots in the range of $D_s$ may either be from the current epoch or an earlier one, so we split them using $\mathsf{sep}$: $$\begin{equation*}
    (\mathit{D_{s\_old}},~\mathit{D_{s\_new}}) = \mathsf{sep}~\mathit{D_s}~\ell(s_i)
\end{equation*}$$ We must then show that $$\begin{equation*}
    \mathit{deposits}' = \mathit{deposits}
    + |A_s|\cdot d_{val}
    + |P_c|\cdot p_{val}
    - |D_{s\_new}|\cdot d_{val}
    - \left(\sum_{\underline{\phantom{a}}\mapsto t\in D_{s\_old}}R_c~t~\ell(s_i)\right)
\end{equation*}$$ Looking at the $\mathsf{UTXO}$ transition in Figure fig:rules:utxo-shelley, $$\begin{equation*}
    \mathit{deposits}' = \mathit{deposits} + \mathsf{totalDeposits}~pp~stpools{(\mathsf{txcerts}~tx)}
    - (\mathit{refunded} + \mathit{decayed})
\end{equation*}$$ The function $\mathsf{totalDeposits}$ is defined in Figure fig:functions:deposits-refunds and it is clear that here it is equal to $$|A_s|\cdot d_{val} + |P_c|\cdot p_{val.}$$ Recall that $$\begin{equation*}
    \begin{array}{rl}
      \mathit{refunded} & \mathsf{keyRefunds}~pp~stkCreds~{tx} \\
      \mathit{decayed} & \decayedTx{pp}{stkCreds}~{tx}
    \end{array}
\end{equation*}$$ where $\mathsf{keyRefunds}$ is defined in Figure fig:functions:deposits-refunds. This iterates $\mathsf{keyRefund}$ from the same figure, which in turn just looks up the creation slot for a transaction and returns $R_c$. The function to calculate the value of decayed deposits, $\mathsf{decayedTx}$, is defined in Figure fig:functions:deposits-decay. This iterates $\mathsf{decayedKey}$ from the same figure. Therefore, to show that $$\begin{equation}
\label{deleted-is-refunds-plus-decayed}
    |D_{s\_new}|\cdot d_{val} + \sum_{\underline{\phantom{a}}\mapsto t\in D_{s\_old}}R_c~t~\ell(s_i)
    = \mathit{refunded} + \mathit{decayed},
\end{equation}$$ and thus complete the proof for the $\mathsf{UTXO}$ case, it suffices to show that for a given $\mathit{c}\mapsto s\in D_s$, the $R_c$ value plus the $\mathsf{decayedKey}$ value that is associated with the stake credential $c$ is equal to $d_{val}$ if $\epoch(s)=\epoch(s_i)$, and is otherwise equal to $R_c~s~\ell(s_i)$. Looking at the definition of $\mathsf{decayedKey}$, observe that if $\epoch(s)=\epoch(s_i)$ then $\mathit{start}=\mathit{created}$ and so the decayed value is $(R_c~s~s)-(R_c~s~s_i)$. However, $R_c~s~s = d_{val}$, so the refund plus the decayed value is $d_{val}-(R_c~s~s_i)+(R_c~s~s_i)=d_{val}$. Otherwise, if $s$ is from a previous epoch, then $\mathit{start}=\ell(s_i)$, and so the decayed value is $(R_c~s~\ell(s_i))-(R_c~s~s_i)$. The refund plus the decayed value is thus $(R_c~s~\ell(s_i))-(R_c~s~s_i)+(R_c~s~s_i)=(R_c~s~\ell(s_i))$. Therefore, equation deleted-is-refunds-plus-decayed holds, and consequently so also does . ◻

[^1]: Note that the protocol parameters can only change in the $\mathsf{NEWPP}$ transition.

[^2]: Note that if $\mathsf{epoch}~s_i = \mathsf{epoch}~s_{i+1}$, then is trivially true.
