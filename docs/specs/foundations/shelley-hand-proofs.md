## Preservation of Value
As visualized in Figure \[fig:fund-preservation\], the total amount of lovelace in any given chain state $\var{s}\in\ChainState$ is completely contained within the values of the six variables:

  **Variable**   **Name in Figure \[fig:fund-preservation\]**   **Nesting Inside Chain State**   **Kind**
  -------------- -------------------------------------------------------------------------------------------------------------------------------- -------------------------------- --------------------------
  utxo           circulation                                                                                                                      s.nes.es.ls.utxoSt               Map over Lovelace Values
  deposits       deposits                                                                                                                         s.nes.es.ls.utxoSt               Lovelace Value ($\Coin$)
  fees           fees                                                                                                                             s.nes.es.ls.utxoSt               Lovelace Value ($\Coin$)
  rewards        reward accounts                                                                                                                  s.nes.es.ls.dpstate.dstate       Lovelace Value ($\Coin$)
  treasury       treasury                                                                                                                         s.nes.es.acnt                    Lovelace Value ($\Coin$)
  reserves       reserves                                                                                                                         s.nes.es.acnt                    Map over Lovelace Values

Notice that $\var{deposits}$, $\var{fees}$, $\var{treasury}$, and $\var{reserves}$ are all single lovelace values, while $\var{utxo}$, and $\var{rewards}$ are maps whose values are lovelace.

We define the *Lovelace Value* of a given chain state as:

::: definition
[]{#def:val label="def:val"} $$\begin{equation*}
    \Val(s~\in~\var{State}) =
        \Val(\var{utxo}) +
            \Val(\var{deposits}) +
            \Val(\var{fees}) +
            \Val(\var{reserves}) +
            \Val(\var{treasury}) +
            \Val(\var{rewards})
\end{equation*}$$ where $$\begin{equation*}
      \Val(x \in \Coin) = x
\end{equation*}$$ $$\begin{equation*}
      \Val((\wcard\mapsto (y \in \Coin))^{*}) = \sum y
\end{equation*}$$

For any state that is used in a given subtransition of $\mathsf{CHAIN}$, we define $\Val{}$ in an analogous way, setting the value of any variable that is not explicitly represented in the state to zero. For example, given $\var{utxoSt}\in\UTxOState$, $$\begin{equation*}
  \Val(\var{utxoSt}) =
  \left(\sum_{\wcard\mapsto(\wcard,~v)\in\var{utxo}}v\right) + \var{deposits} + \var{fees}
\end{equation*}$$

The key property that we want to prove is that no semantic transition changes the value that is captured in the state ($\Val{s}$). This property is easy to state: intuitively, the *Lovelace Value*before the transition is the same as the *Lovelace Value* after that transition.

::: theorem
[]{#thm:chain-pres-of-value label="thm:chain-pres-of-value"} For all environments $e$, blocks $b$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\trans{\hyperref[fig:rules:chain]{chain}}{b}s'
\end{equation*}$$ then $$\begin{equation*}
    \Val(s) = \Val(s')
\end{equation*}$$

We will prove the soundness of Theorem \[thm:chain-pres-of-value\] via a few lemmas.

::: lemma
[]{#lemma:value-sum-pres-1 label="lemma:value-sum-pres-1"} For any mapping $m:A\mapsto\Coin$ and set $s\in\powerset{A}$, $$\begin{equation*}
    \Val(\var{m}) = \Val(s\subtractdom m) + \Val(s\restrictdom m)
\end{equation*}$$


*Proof.* easy ◻

::: lemma
[]{#lemma:value-sum-pres-2 label="lemma:value-sum-pres-2"} For any mappings $m_1, m_2:A\mapsto\Coin$, if $\dom{m_1}\cap\dom{m_2}=\emptyset$, then $$\begin{equation*}
    \Val(m_1\cup m_2) = \Val(m_1) + \Val(m_2)
\end{equation*}$$


*Proof.* easy ◻

::: lemma
[]{#lemma:utxo-pres-of-value label="lemma:utxo-pres-of-value"} For all environments $e$, transactions $t$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\trans{\hyperref[fig:rules:utxo-shelley]{utxo}}{t}s'
\end{equation*}$$ then $$\begin{equation*}
    \Val(s) + w = \Val(s')
\end{equation*}$$ where $w = \fun{wbalance}~(\fun{txwdrls}~{t})$.


*Proof.* The proof is essentially unfolding the definition of the predicate $$\begin{equation}
    \label{cons-is-prod}
    \consumed{pp}{utxo}{t} = \produced{pp}{stpools}{t}
\end{equation}$$ and applying a little algebra. If we let: $$\begin{equation*}
    \begin{array}{rl}
      k & \keyRefunds{pp}{stkCreds}{t} \\
      f & \txfee{t} \\
      d & \totalDeposits{pp}{stpools}{(\txcerts{t})} \\
    \end{array}
\end{equation*}$$ then equation \[cons-is-prod\] can be rewritten as: $$\begin{equation*}
    \Val(\txins{t} \restrictdom{\var{utxo}}) + w + k = \Val(\outs{t}) + f + d
\end{equation*}$$ where $\outs{}$ is defined in Figure \[fig:functions:utxo\] and returns a value of type $\UTxO$. Therefore, moving $k$ to the right and adding $\txins{t} \subtractdom{\var{utxo}}$ to each side, $$\begin{equation*}
    \Val(\txins{t} \restrictdom{\var{utxo}}) + \Val(\txins{t} \subtractdom{\var{utxo}}) + w
    = \Val(\outs{t}) + f + d - k + \Val(\txins{t} \subtractdom{\var{utxo}})
\end{equation*}$$ (Though not needed for the proof at hand, note that $d-k$ is non-negative since the deposits will always be large enough to cover the current obligation. See Theorem \[thm:non-neg-deposits\].) It then follows that: $$\begin{equation*}
    \begin{array}{rlr}
      \Val(\var{utxo}) + w
    & \Val(\outs{t}) + f + d - k + \Val(\txins{t} \subtractdom{\var{utxo}})
    & \text{(by Lemma~\ref{lemma:value-sum-pres-1})}
    \\
    & \Val((\txins{t} \subtractdom{\var{utxo}})\cup\outs{t}) + (d - k) + f
    & \text{(by Lemma~\ref{lemma:value-sum-pres-2})}
    \end{array}
\end{equation*}$$ Note that in order to apply Lemma \[lemma:value-sum-pres-2\] above, it must be true that $(\txins{t} \subtractdom{\var{utxo}})$ and $(\outs{t})$ have disjoint domains, which follows from the uniqueness of the transaction IDs.

Therefore, by adding the deposits and fees from $s$ to the equality above, it follows that $\Val(s) + w = \Val(s')$. ◻

::: lemma
[]{#lemma:deleg-pres-of-value label="lemma:deleg-pres-of-value"} For all environments $e$, transactions $c$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\trans{\hyperref[fig:delegation-rules]{deleg}}{c}s'
\end{equation*}$$ then $$\begin{equation*}
    \Val(s) = \Val(s')
\end{equation*}$$


*Proof.* The only variable with value in this transition is . Only two of the rules in $\mathsf{DELEG}$ can change , namely $\mathsf{Deleg{-}Reg}$ and $\mathsf{Deleg{-}Dereg}$. However, $\mathsf{Deleg{-}Reg}$ only adds a zero value, and $\mathsf{Deleg{-}Dereg}$ only removes a zero value. ◻

::: lemma
[]{#lemma:delegs-pres-of-value label="lemma:delegs-pres-of-value"} For all environments $e$, certificates $\Gamma$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\trans{\hyperref[fig:rules:delegation-sequence]{delegs}}{\Gamma}s'
\end{equation*}$$ then $$\begin{equation*}
    \Val(s) = \Val(s') + w
\end{equation*}$$ where $w = \fun{wbalance}~(\fun{txwdrls}~{t})$, and $t$ is the transaction in the environment $e$.


*Proof.* The proof is by induction on the length of $\Gamma$. Note that the only variable with value in this transition is .

*In the base case*, we look at the rule $\mathsf{Seq{-}delg{-}base}$. Since $\var{wdrls}\subseteq\var{rewards}$, then $\var{rewards} = \var{wdrls}\cup\var{(\var{rewards}\setminus\var{wdrls})}$. Therefore $$\begin{equation*}
    \begin{array}{rlr}
      \Val{(\var{rewards})}
      & \Val{(\var{rewards}\setminus\var{wdrls})} + \Val{(\var{wdrls})}
      & \text{by Lemma~\ref{lemma:value-sum-pres-2}}
      \\
      & \Val{(\var{rewards}\setminus\var{wdrls})} + w
      & \text{by definition}
      \\
      & \Val\left(\var{rewards}\unionoverrideRight\{(w, 0) \mid w \in \dom \var{wdrls}\}\right) + w
    \end{array}
\end{equation*}$$ Therefore $\Val(s) = \Val(s')$.

*In the inductive case*, we look at the rule $\mathsf{Seq{-}delg{-}ind}$. In this case, the lemma then follows directly from Lemma \[lemma:deleg-pres-of-value\]. ◻

::: lemma
[]{#lemma:poolreap-pres-of-value label="lemma:poolreap-pres-of-value"} For all environments $e$, epoch $\epsilon$, and states $s$, $s'$, if $$\begin{equation*}
    e\vdash s\trans{\hyperref[fig:rules:pool-reap]{poolreap}}{\epsilon}s'
\end{equation*}$$ then $$\begin{equation*}
    \Val(s) = \Val(s')
\end{equation*}$$


*Proof.* The $\mathsf{POOLREAP}$ value is contained in $\var{deposits}$, $\var{treasury}$, and $\var{rewards}$. Notice that $\var{unclaimed}$ is added to $\var{treasury}$ and subtracted from the $\var{deposits}$. Moreover, $\var{refunded}$ is subtracted from $\var{deposits}$. (Note that $\var{deposits}-(\var{unclaimed}+\var{refunded})$ is non-negative by Theorem \[thm:non-neg-deposits\].) It therefore suffices to show that $$\begin{equation*}
    \begin{array}{rl}
    \Val(\var{rewards}\unionoverridePlus\var{refunds})
    & \Val(\var{rewards}) + \Val(\var{refunds})
    \\
    & \Val(\var{rewards}) + \var{refunded}
    \end{array}
\end{equation*}$$ But this is clear from the definition of $\unionoverridePlus$. ◻

::: lemma
[]{#lemma:ru-pres-of-value label="lemma:ru-pres-of-value"} For every $(\Delta t,~\Delta r,~\var{rs},~\Delta f)$ in the range of $\fun{createRUpd}$, $$\begin{equation*}
    \Delta t + \Delta r + \Val(rs) + \Delta f = 0
\end{equation*}$$


*Proof.* In the definition of $\fun{createRUpd}$ in Figure \[fig:functions:reward-update-creation\], We see that: $$\begin{equation*}
    \begin{array}{rl}
      \var{rewardPot} & \var{feeSS} + \Delta r \\
      \var{R} & \var{rewardPot} - \Delta t_1 \\
      \Delta t_2 & R - \Val(\var{rs})\\
      \Delta t & \Delta t_1 + \Delta t_2 \\
    \end{array}
\end{equation*}$$ Therefore $$\begin{equation*}
    \begin{array}{rl}
      (\var{feeSS} + \Delta r) & \var{rewardPot} = R + \Delta t_1 = \Delta t_2 + \Val(rs) + \Delta t_1  \\
      0 & (\Delta t_1 + \Delta t_2 ) - \Delta r + \Val(rs)- \var{feeSS} \\
      0 & \Delta t - \Delta r + \Val(rs)- \var{feeSS} \\
    \end{array}
\end{equation*}$$ It then suffices to notice that $\fun{createRUpd}$ returns $(\Delta t,-~\Delta r,~\var{rs},~-\var{feeSS})$. ◻

Note that Lemma \[lemma:ru-pres-of-value\] is not strictly need for the proof of Theorem \[thm:chain-pres-of-value\], since the $\mathsf{NEWEPOCH}$ transition requires that $\Delta t + \Delta r + \Val(rs) + \Delta f = 0$ holds. It does, however, give us confidence that the $\mathsf{CHAIN}$ transition can proceed.

We are now ready to prove Theorem \[thm:chain-pres-of-value\].


*Proof.* For a given transition $\mathsf{TR}$, let be the statement:

Our goal is to prove . Lemmas \[lemma:utxo-pres-of-value\] and \[lemma:delegs-pres-of-value\] imply , since $\mathsf{UTXOW}$ transforms state exactly as $\mathsf{UTXO}$ does. then follows by straightforward induction on the length of $\Gamma$: the base case is trivial; and the inductive case follows directly from . holds trivially, since it contains no value. Similarly, holds since $\var{diff}$ is added to $\var{reserves}$ and subtracted from $\var{deposits}$. Therefore holds by Lemma \[lemma:poolreap-pres-of-value\]. holds since $\Val{i_{rwd}'}=\var{tot}$ in Figure \[fig:rules:mir\]. Morover, holds in the presence of $\fun{applyRUpd}$ since the transition requires $\Delta t + \Delta r + \Val(rs) + \Delta f = 0$. easily follows from this. ◻

## Non-negative Deposit Pot
The *deposit pot* (the variable $\var{deposits}$ in the UTxO State) represents the amount of *lovelace* that is set aside by the system as a whole for refunding deposits. Deposits are added to this pot, which then decays exponentially over time, and is also depleted by any refunded deposits. At an epoch boundary, the decayed parts of any deposits (including, possibly, deposits for any transactions that will complete in future epochs) will be distributed as additional *rewards*, as described in [@delegation_design]. Since $\var{deposits}$ is only used to record the value of future refunds or rewards whose costs have already been incurred, both it and any reward value will always be non-negative. Note that there are two types of deposits which are recorded in the same pot: those for stake keys; and those for stake pools. Stake keys are deregistered in the slot in which the deregistration certificates is processed. Stake pools, however, are staged for retirement on epoch boundaries. The following theorem ensures that the deposit pot is properly maintained and will always be large enough to meet all of its obligations.


  **Variable**   **Value**     **Nesting Inside Chain State**        **Kind**
  -------------- ------------- ------------------------------------- -------------------------------------------
  deposits       0             s.nes.es.ls.utxoSt                    $\Coin$
  stkCreds       $\emptyset$   s.nes.es.ls.dpstate.dstate.stkCreds   $\StakeCreds$ ($\Credential\mapsto\Slot$)
  stpools        $\emptyset$   s.nes.es.ls.dpstate.pstate.stpools    $\StakePools$ ($\KeyHash\mapsto\Slot$)

**Initial Chain State**

::: theorem
[]{#thm:non-neg-deposits label="thm:non-neg-deposits"} Let $n\in\N$ and $c_0\in\ChainState$ be a chain state in which $\var{deposits} ~=~0$, $\var{stkCreds}~=~\emptyset$ and $\var{stPools}~=~\emptyset$, as shown above: If $$\begin{equation*}
    s_0\vdash c_0\trans{\hyperref[fig:rules:chain]{chain}}{b_0}c_1,~~
    s_1\vdash c_1\trans{\hyperref[fig:rules:chain]{chain}}{b_1}c_2,~~
    \ldots,~~
    s_n\vdash c_n\trans{\hyperref[fig:rules:chain]{chain}}{b_n}c_{n+1},~~n \ge 0
\end{equation*}$$ is a sequence of valid $\mathsf{CHAIN}$ transitions, then $\forall i, 0 \le i \le n, \var{deposits} ~(c_{n+1}) \ge 0$.


*Proof.* We will prove a slightly stronger condition, namely that some stronger invariants hold most of the time, and that when they do fail to hold, then $\var{deposits}$ is still non-negative. These stronger invariants will require a few additional definitions. Given a slot $s$, let $\ell(s)$ be the first slot of the epoch that $s$ occurs in, that is $\ell = \fun{firstSlot}\circ\fun{epoch}$. Given a mapping $m\in\mathsf{T}\to\Slot$ and a slot $s\in\Slot$, let $\fun{sep}$ be the function that separates $m$ into two maps, those whose value is strictly less than $s$ and those whose value is at least $s$. So, $$\begin{equation*}
    \fun{sep}~m~s = \forall x\mapsto t~\in~m,~~
    \left(\{x\mapsto t~\mid~t<s\},~\{x\mapsto t~\mid~t\geq s\}\right)
\end{equation*}$$

If we assume that the *protocol parameters*, $pp$, are fixed[^1], then we can provide convenience functions $R_c$ and $R_p$ for the *stake credential* and *stake pool* refunds, respectively: $$\begin{equation*}
    \begin{array}{rl}
      R_c~s_0~s_1 & \refund{d_{val}}{d_{min}}{\lambda_d}{s_1-s_0} \\
      R_p~s_0~s_1 & \refund{p_{val}}{p_{min}}{\lambda_p}{s_1-s_0} \\
    \end{array}
\end{equation*}$$ where $d_{val}$, $d_{min}$, $\lambda_d$, $p_{val}$, $p_{min}$, $\lambda_p$ are the protocol parameter values from $pp$, and $\fun{refund}$ is defined in Figure \[fig:functions:deposits-refunds\]. We let ("Deposits (precisely) Big Enough\"), be the following property: $$\begin{equation}
\tag{DBE}\label{DBE}
    \var{deposits}
    = \left(\sum_{\wcard\mapsto t\in C_{old}}R_c~t~\ell(s)\right)
    + |C_{new}|\cdot d_{val}
    + \left(\sum_{\wcard\mapsto t\in P_{old}}R_p~t~\ell(s)\right)
    + |P_{new}|\cdot p_{val}
\end{equation}$$ where $$\begin{equation*}
    \begin{array}{rl}
      C_{old},~C_{new} & \fun{sep}~\var{stkCreds}~{\ell(s)} \\
      P_{old},~P_{new} & \fun{sep}~\var{stpools}~{\ell(s)},
    \end{array}
\end{equation*}$$ for some slot, $s$, where $\var{pp}$, $\var{stkCreds}$, $\var{stpools}$ are in the corresponding chain state, $c$. In other words, asserts that the deposit pot is equal to the sum of the deposit refunds that were available at the previous epoch boundary, plus the sum of the initial deposit values for all the deposits from the current epoch.

Notice that for a chain state $c$ and slot $s$, if the range of $\var{stkCreds}$ and $\var{stpools}$ contains only slots from the previous epoch, then is equivalent to $$\begin{equation}
\tag{DEO}\label{DEO}
    \var{deposits} = \obligation{pp}{stkCreds}{stpools}{\ell(s)}
\end{equation}$$ where $\fun{obligation}$ is defined in Figure \[fig:funcs:epoch-helper-rewards\]. It is generally true that holds after each subtransition of $s_i\vdash c_i\trans{\hyperref[fig:rules:chain]{chain}}{b_i}c_{i+1}$. However, this invariant can fail to hold after the $\hyperref[fig:delegation-transitions]{\mathsf{DELEG}}$ transition, since this transition can add and remove stake credentials, and can also add stake pools, but the deposit pot is not adjusted accordingly until the next subtransiton of $\hyperref[fig:rules:ledger]{\mathsf{LEDGER}}$, namely $\hyperref[fig:rules:utxo-shelley]{\mathsf{UTXO}}$. The invariant can also fail to hold if the slot increases while the chain state remains the same. That is, if holds, then can fail to hold if $\epoch{s_i} < \epoch{s_{i+1}}$, since the value of the deposit in the left hand side of equation \[DBE\] remains the same, but the refunded values become smaller[^2]. Therefore, in this situation we can consider the slightly weaker constraint: $$\begin{equation}
\tag{DGO}\label{DGTO}
    \var{deposits} \geq \obligation{pp}{stkCreds}{stpools}{\ell(s)}
\end{equation}$$ The difference between the left and right hand sides of the inequality corresponds to the lovelace value in $c_{i+1}$ that decays between $s_i$ and $s_{i+1}$.

There are four sub-transitions where $\var{deposits}$ is changed: $\mathsf{SNAP}$ (Figure \[fig:rules:snapshot\]), $\mathsf{POOLREAP}$ (Figure \[fig:rules:pool-reap\]), $\mathsf{NEWPP}$ (Figure \[fig:rules:new-proto-param\]), $\mathsf{UTXO}$ (Figure \[fig:rules:utxo-shelley\]). This ordering is also the order in which $\var{deposits}$ is changed. Of these sub-transitions, only $\mathsf{UTXO}$ actually changes the value of $\var{deposits}$ when $s_i$ is in the same epoch as $s_i$. (We say that $s_i$ *crosses the epoch boundary* if the precondition of Rule \[eq:new-epoch\] in Figure \[fig:rules:new-epoch\] is met, namely if $\epoch{s_i} \ge e_\ell+1$.) The proof then proceeds by induction on $n$, showing the following:

- Let $c$ be the chain state after the $\mathsf{SNAP}$ transition in $s_i\vdash c_i\trans{\hyperref[fig:rules:chain]{chain}}{b_i}c_{i+1}$. If , then holds.

- $\mathsf{POOLREAP}$ preserves \[DBE\].

- $\mathsf{NEWPP}$ preserves \[DBE\].

- The property for $\mathsf{UTXO}$ requires a bit of explanation. Let $\var{nes}\in\NewEpochState$ be the new epoch state in $c_i$. Note that the property \[DBE\] makes sense for values of $\NewEpochState$ since it contains all the relevant variables. Similarly, \[DBE\] also makes sense for values of $\UTxOState\times\PParams$. Let $${\begin{array}{c}
             \var{gkeys} \\
           \end{array}}
          \vdash\var{nes}\trans{\hyperref[fig:rules:tick]{tick}}{\var{bh}}\var{nes'}$$ be the first sub-transition of $s_i\vdash c_i\trans{\hyperref[fig:rules:chain]{chain}}{b_i}c_{i+1}$. If holds, then holds for every transaction $tx$ in $b_i$, where: $$\var{env}\vdash \var{us} \trans{\hyperref[fig:rules:utxow-shelley]{utxo}}{tx} \var{us'},$$ is a sub-transition of $s_i\vdash c_i\trans{\hyperref[fig:rules:chain]{chain}}{b_i}c_{i+1}$, and $\var{pp}$ is the protocol parameters in $\var{nes'}$.

Case $\hyperref[fig:rules:snapshot]{\mathsf{SNAP}}$. We must show that if $c$ is the chain state after the $\mathsf{SNAP}$ transition in $s_i\vdash c_i\trans{\hyperref[fig:rules:chain]{chain}}{b_i}c_{i+1}$, and holds, then so does . We can assume that $s_i$ crosses the epoch boundary, since otherwise the $\mathsf{SNAP}$ transition will not occur. Since the $\mathsf{SNAP}$ transition only happens within the $\mathsf{TICK}$ transition on the epoch boundary, it follows that $c_i$ does not contain any stake credentials or pools from the current epoch, and so \[DBE\] will be equivalent to \[DEO\] (the current epoch is $\epoch{s_i}$). However, holds trivially, since it is determined from the $\fun{obligation}$ value.\
 \
Case $\hyperref[fig:rules:pool-reap]{\mathsf{POOLREAP}}$. We must show that \[DBE\] is preserved. We again assume that $s_i$ crosses the epoch boundary. The $\mathsf{POOLREAP}$ transition does the following:

1.  leaves $\var{stkCreds}$ unchanged,

2.  removes $\var{retired}$ from $\var{stpools}$,

3.  subtracts $\var{unclaimed}+\var{refunded}$ from $\var{deposits}$.

Notice that the domain of the $\var{pr}$ is $\var{retired}$, and similarly the domain of the $\var{rewardAcnts}$ is also $\var{retired}$ since the domains of $\var{stpools}$ and $\var{poolParams}$ are the same. Therefore $\var{retired}$ is the disjoint union of $\dom({\var{refunds}})$ and $\dom({\var{mRefunds}})$, so that $$\begin{equation*}
    \begin{array}{rl}
      \var{unclaimed}+\var{refunded}
      &
      \left(
        \sum\limits_{\wcard\mapsto t\in\var{refunds}}R_p~t~\ell(s)
      \right)+
      \left(
        \sum\limits_{\wcard\mapsto t\in\var{mRefunds}}R_p~t~\ell(s)
      \right)
      \\
      &
      \sum\limits_{\wcard\mapsto t\in\var{rewardAcnts'}}R_p~t~\ell(s)
      \\
      &
      \left(
        \sum\limits_{\wcard\mapsto t\in\var{stpools}}R_p~t~\ell(s)
      \right)-
      \left(
        \sum\limits_{\wcard\mapsto t\in\var{retired}\subtractdom\var{stpools}}R_p~t~\ell(s)
      \right)
    \end{array}
\end{equation*}$$ Therefore, it follows that if \[DEO\] holds before $\mathsf{POOLREAP}$, then it also holds afterwards.\
 \
Case $\hyperref[fig:rules:new-proto-param]{\mathsf{NEWPP}}$. We must show that \[DBE\] is preserved. We again assume that $s_i$ crosses the epoch boundary. In this transition $\var{pp}$ can change, but $\var{stkCreds}$, $\var{stpools}$, and $\var{deposits}$ do not change. As in the $\mathsf{SNAP}$ case, holds trivially, since it is set to the value that is determined by $\fun{obligation}$.\
 \
Case $\hyperref[fig:rules:utxo-shelley]{\mathsf{UTXO}}$. We assume that holds, where $\var{nes'}$ is the new epoch state after the $\mathsf{TICK}$ transition. We must show that \[DBE\] is preserved after each $\mathsf{UTXO}$ transition. The $\mathsf{DELEGS}$ transition can result in values being added to or deleted from $\var{stkCreds}$, and added to $\var{stpools}$. Let $A_s$ be the added stake credentials, $D_s$ be the deleted credentials, and $A_p$ be the added stake pools, where $\var{stkCreds}'$ is the stake credential mapping $\var{stpools}'$ is the stake pools, and $\var{deposits}'$ is the deposit pot after $\mathsf{DELEGS}$. We have that $$\begin{equation*}
    \begin{array}{rcl}
      \var{D_s} & \subseteq & \var{\var{stkCreds}\cup\var{A_s}} \\
      \var{stkCreds}' & = & (\var{stkCreds}\cup\var{A_s})\setminus\var{D_s} \\
      \var{stpools}' & = & \var{stpools}\cup\var{A_p} \\
    \end{array}
\end{equation*}$$ The slots in the range of $A_s$ will all be equal to $s_i$, but the slots in the range of $D_s$ may either be from the current epoch or an earlier one, so we split them using $\fun{sep}$: $$\begin{equation*}
    (\var{D_{s\_old}},~\var{D_{s\_new}}) = \fun{sep}~\var{D_s}~\ell(s_i)
\end{equation*}$$ We must then show that $$\begin{equation*}
    \var{deposits}' = \var{deposits}
    + |A_s|\cdot d_{val}
    + |P_c|\cdot p_{val}
    - |D_{s\_new}|\cdot d_{val}
    - \left(\sum_{\wcard\mapsto t\in D_{s\_old}}R_c~t~\ell(s_i)\right)
\end{equation*}$$ Looking at the $\mathsf{UTXO}$ transition in Figure \[fig:rules:utxo-shelley\], $$\begin{equation*}
    \var{deposits}' = \var{deposits} + \totalDeposits{pp}{stpools}{(\txcerts{tx})}
    - (\var{refunded} + \var{decayed})
\end{equation*}$$ The function $\fun{totalDeposits}$ is defined in Figure \[fig:functions:deposits-refunds\] and it is clear that here it is equal to $$|A_s|\cdot d_{val} + |P_c|\cdot p_{val.}$$ Recall that $$\begin{equation*}
    \begin{array}{rl}
      \var{refunded} & \keyRefunds{pp}{stkCreds}~{tx} \\
      \var{decayed} & \decayedTx{pp}{stkCreds}~{tx}
    \end{array}
\end{equation*}$$ where $\fun{keyRefunds}$ is defined in Figure \[fig:functions:deposits-refunds\]. This iterates $\fun{keyRefund}$ from the same figure, which in turn just looks up the creation slot for a transaction and returns $R_c$. The function to calculate the value of decayed deposits, $\fun{decayedTx}$, is defined in Figure \[fig:functions:deposits-decay\]. This iterates $\fun{decayedKey}$ from the same figure. Therefore, to show that $$\begin{equation}
\label{deleted-is-refunds-plus-decayed}
    |D_{s\_new}|\cdot d_{val} + \sum_{\wcard\mapsto t\in D_{s\_old}}R_c~t~\ell(s_i)
    = \var{refunded} + \var{decayed},
\end{equation}$$ and thus complete the proof for the $\mathsf{UTXO}$ case, it suffices to show that for a given $\var{c}\mapsto s\in D_s$, the $R_c$ value plus the $\fun{decayedKey}$ value that is associated with the stake credential $c$ is equal to $d_{val}$ if $\epoch(s)=\epoch(s_i)$, and is otherwise equal to $R_c~s~\ell(s_i)$. Looking at the definition of $\fun{decayedKey}$, observe that if $\epoch(s)=\epoch(s_i)$ then $\var{start}=\var{created}$ and so the decayed value is $(R_c~s~s)-(R_c~s~s_i)$. However, $R_c~s~s = d_{val}$, so the refund plus the decayed value is $d_{val}-(R_c~s~s_i)+(R_c~s~s_i)=d_{val}$. Otherwise, if $s$ is from a previous epoch, then $\var{start}=\ell(s_i)$, and so the decayed value is $(R_c~s~\ell(s_i))-(R_c~s~s_i)$. The refund plus the decayed value is thus $(R_c~s~\ell(s_i))-(R_c~s~s_i)+(R_c~s~s_i)=(R_c~s~\ell(s_i))$. Therefore, equation \[deleted-is-refunds-plus-decayed\] holds, and consequently so also does . ◻

[^1]: Note that the protocol parameters can only change in the $\mathsf{NEWPP}$ transition.

[^2]: Note that if $\epoch{s_i} = \epoch{s_{i+1}}$, then is trivially true.
