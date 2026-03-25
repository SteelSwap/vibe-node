# Properties
This section describes the properties that the ledger should have. The goal is to to include these properties in the executable specification to enable e.g. property-based testing or formal verification.

## Header-Only Validation
The header-only validation properties of the Shelley Ledger are the analogs of those from Section 8.1 of [@byron_chain_spec].

In any given chain state, the consensus layer needs to be able to validate the block headers without having to download the block bodies. Property \[prop:header-only-validation\] states that if an extension of a chain that spans less than $\StabilityWindow$ slots is valid, then validating the headers of that extension is also valid. This property is useful for its converse: if the header validation check for a sequence of headers does not pass, then we know that the block validation that corresponds to those headers will not pass either.

First we define the header-only version of the $\mathsf{CHAIN}$ transition, which we call $\mathsf{CHAINHEAD}$. It is very similiar to $\mathsf{CHAIN}$, the only difference being that it does not call $\mathsf{BBODY}$.


$$\begin{equation}
\label{eq:chain-head}
    \inference[ChainHead]
    {
      \var{bh} \leteq \bheader{block}
      &
      \var{gkeys} \leteq \fun{getGKeys}~\var{nes}
      &
      \var{s} \leteq \bslot{(\bhbody{bh})}
      \\
      (\wcard,~\wcard,~\wcard,~(\wcard,~\wcard,~\wcard,~\var{pp}),~\wcard,~\wcard,\wcard) \leteq \var{nes}
      \\~\\
      \fun{chainChecks}~\var{pp}~\var{bh}
      \\~\\
      {
        {\begin{array}{c}
           \var{gkeys} \\
         \end{array}}
        \vdash\var{nes}\trans{\hyperref[fig:rules:tick]{tick}}{\var{s}}\var{nes'}
      } \\~\\
      (\var{e_1},~\wcard,~\wcard,~\wcard,~\wcard,~\wcard,\wcard)
        \leteq\var{nes} \\
      (\var{e_2},~\wcard,~\wcard,~\var{es},~\wcard,~\var{pd},\var{osched})
        \leteq\var{nes'} \\
        (\wcard,~\wcard,\var{ls},~\wcard,~\var{pp'})\leteq\var{es}\\
        ( \wcard,
          ( (\wcard,~\wcard,~\wcard,~\wcard,~\wcard,~\var{genDelegs}),~
          (\wcard,~\wcard,~\wcard)))\leteq\var{ls}\\
          \var{ne} \leteq  \var{e_1} \neq \var{e_2}\\
      {
        {\begin{array}{c}
            \var{pp'} \\
            \var{osched} \\
            \var{pd} \\
            \var{genDelegs} \\
            \var{s_{now}} \\
            \var{ne}
         \end{array}}
        \vdash
        {\left(\begin{array}{c}
              \var{cs} \\
              \var{lab} \\
              \eta_0 \\
              \eta_v \\
              \eta_c \\
              \eta_h \\
        \end{array}\right)}
        \trans{\hyperref[fig:rules:prtcl]{prtcl}}{\var{bh}}
        {\left(\begin{array}{c}
              \var{cs'} \\
              \var{lab'} \\
              \eta_0' \\
              \eta_v' \\
              \eta_c' \\
              \eta_h' \\
        \end{array}\right)}
      } \\~\\~\\
    }
    {
      \var{s_{now}}
      \vdash
      {\left(\begin{array}{c}
            \var{nes} \\
            \var{cs} \\
            \eta_0 \\
            \eta_v \\
            \eta_c \\
            \eta_h \\
            \var{lab} \\
      \end{array}\right)}
      \trans{chainhead}{\var{bh}}
      {\left(\begin{array}{c}
            \varUpdate{\var{nes}'} \\
            \varUpdate{\var{cs}'} \\
            \varUpdate{\eta_0'} \\
            \varUpdate{\eta_v'} \\
            \varUpdate{\eta_c'} \\
            \varUpdate{\eta_h'} \\
            \varUpdate{\var{lab}'} \\
      \end{array}\right)}
    }
\end{equation}$$

**Chain-Head rules**

<!-- property -->
[]{#prop:header-only-validation label="prop:header-only-validation"} For all environments $e$, states $s$ with slot number $t$[^1], and chain extensions $E$ with corresponding headers $H$ such that: $$0 \leq t_E - t  \leq \StabilityWindow$$ we have: $$e \vdash s \xlongrightarrow[\textsc{\hyperref[fig:rules:chain]{chain}}]{E}\negthickspace^{*} s'
  \implies
  e \vdash s \xlongrightarrow[\textsc{\hyperref[fig:rules:chainhead]{chainhead}}]{H}\negthickspace^{*} s''$$ where $t_E$ is the maximum slot number appearing in the blocks contained in $E$, and $H$ is obtained from $E$ by applying $\fun{bheader}$ to each block in $E$.

<!-- property -->
[]{#prop:body-only-validation label="prop:body-only-validation"} For all environments $e$, states $s$ with slot number $t$, and chain extensions $E = [b_0, \ldots, b_n]$ with corresponding headers $H$ such that: $$0 \leq t_E - t  \leq \StabilityWindow$$ we have that for all $i \in [1, n]$: $$e \vdash s \xlongrightarrow[\textsc{\hyperref[fig:rules:chainhead]{chainhead}}]{H}\negthickspace^{*} s_{h}
  \wedge
  e \vdash s \xlongrightarrow[\textsc{\hyperref[fig:rules:chain]{chain}}]{[b_0 \ldots b_{i-1}]}\negthickspace^{*} s_{i-1}
  \implies
  e_{i-1} \vdash s_{i-1}\trans{\hyperref[fig:rules:chainhead]{chainhead}}{h_i} s'_{h}$$ where $t_E$ is the maximum slot number appearing in the blocks contained in $E$.

Property \[prop:body-only-validation\] states that if we validate a sequence of headers, we can validate their bodies independently and be sure that the blocks will pass the chain validation rule. To see this, given an environment $e$ and initial state $s$, assume that a sequence of headers $H = [h_0, \ldots, h_n]$ corresponding to blocks in $E = [b_0, \ldots, b_n]$ is valid according to the $\mathsf{chainhead}$ transition system: $$e \vdash s \xlongrightarrow[\textsc{\hyperref[fig:rules:chainhead]{chainhead}}]{H}\negthickspace^{*} s'$$ Assume the bodies of $E$ are valid according to the $\mathsf{bbody}$ rules, but $E$ is not valid according to the $\mathsf{chain}$ rule. Assume that there is a $b_j \in E$ such that it is **the first block** such that does not pass the $\mathsf{chain}$ validation. Then: $$e \vdash s \xlongrightarrow[\textsc{\hyperref[fig:rules:chain]{chain}}]{[b_0, \ldots b_{j-1}]}\negthickspace^{*} s_j$$ But by Property \[prop:body-only-validation\] we know that $$e_j \vdash s_j \trans{\hyperref[fig:rules:chainhead]{chainhead}}{h_j} s_{j+1}$$ which means that block $b_j$ has valid headers, and this in turn means that the validation of $b_j$ according to the chain rules must have failed because it contained an invalid block body. But this contradicts our assumption that the block bodies were valid.

<!-- property -->
[]{#prop:roll-back-funk label="prop:roll-back-funk"} There exists a function $\fun{f}$ such that for all chains $$C = C_0 ; b; C_1$$ we have that if for all alternative chains $C'_1$, $\size{C'_1} \leq \frac{\StabilityWindow}{2}$, with corresponding headers $H'_1$ $$e \vdash s_0 \xlongrightarrow[\textsc{\hyperref[fig:rules:chain]{chain}}]{C_0;b}\negthickspace^{*} s_1 \xlongrightarrow[\textsc{\hyperref[fig:rules:chain]{chain}}]{C_1}\negthickspace^{*} s_2
  \wedge
  e \vdash s_1 \xlongrightarrow[\textsc{\hyperref[fig:rules:chain]{chain}}]{C_1'}\negthickspace^{*} s'_1
  \implies
  (\fun{f}~(\bheader{b})~s_2) \xlongrightarrow[\textsc{\hyperref[fig:rules:chainhead]{chainhead}}]{H'_1}\negthickspace^{*} s_h$$

Property \[prop:roll-back-funk\] expresses the fact the there is a function that allow us to recover the header-only state by rolling back at most $k$ blocks, and use this state to validate the headers of an alternate chain. Note that this property is not inherent to the $\mathsf{chain}$ rules and can be trivially satisfied by any function that keeps track of the history of the intermediate chain states up to $k$ blocks back. This property is stated here so that it can be used as a reference for the tests in the consensus layer, which uses the rules presented in this document.

## Validity of a Ledger State
Many properties only make sense when applied to a valid ledger state. In informal terms, a valid ledger state $l$ can only be reached when starting from an initial state $l_{0}$ (ledger in the genesis state) and only executing LEDGER state transition rules as specified in Section \[sec:ledger-trans\] which changes wither the UTxO or the delegation state.


$$\begin{align*}
    \genesisId & \in & \TxId \\
    \genesisTxOut & \in & \TxOut \\
    \genesisUTxO & \coloneqq & (\genesisId, 0) \mapsto \genesisTxOut
    \\
    \ledgerState & \in & \left(
                         \begin{array}{c}
                           \UTxOState \\
                           \DPState
                         \end{array}
    \right)\\
               && \\
    \fun{getUTxO} & \in & \UTxOState \to \UTxO \\
    \fun{getUTxO} & \coloneqq & (\var{utxo}, \wcard, \wcard, \wcard) \to \var{utxo}
\end{align*}$$

**Definitions and Functions for Valid Ledger State**

In Figure 2 marks the transaction identifier of the initial coin distribution, where represents the initial UTxO. It should be noted that no corresponding inputs exists, i.e., the transaction inputs are the empty set for the initial transaction. The function extracts the UTxO from a UTxO state.

<!-- definition -->
$$\begin{multline*}
    \forall l_{0},\ldots,l_{n} \in \LState, lenv_{0},\ldots,lenv_{n} \in \LEnv,
    l_{0} = \left(
      \begin{array}{c}
        \genesisUTxOState \\
        \left(
        \begin{array}{c}
          \emptyset\\
          \emptyset
        \end{array}
        \right)
      \end{array}
    \right)  \\
    \implies \forall 0 < i \leq n, (\exists tx_{i} \in \Tx,
    lenv_{i-1}\vdash l_{i-1} \trans{ledger}{tx_{i}} l_{i}) \implies
    \applyFun{validLedgerState} l_{n}
\end{multline*}$$ []{#def:valid-ledger-state label="def:valid-ledger-state"}

Definition \[def:valid-ledger-state\] defines a valid ledger state reachable from the genesis state via valid LEDGER STS transitions. This gives a constructive rule how to reach a valid ledger state.

## Ledger Properties
The following properties state the desired features of updating a valid ledger state.

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \LState: \applyFun{validLedgerstate}{l},
    l=(u,\wcard,\wcard,\wcard), l' = (u',\wcard,\wcard,\wcard)\\
    \implies \forall \var{tx} \in \Tx, lenv \in\LEnv, lenv \vdash\var{u} \trans{utxow}{tx} \var{u'} \\
    \implies \applyFun{destroyed}{pc~utxo~stkCreds~rewards~tx} =
    \applyFun{created}{pc~stPools~tx}
\end{multline*}$$ []{#prop:ledger-properties-1 label="prop:ledger-properties-1"}

Property \[prop:ledger-properties-1\] states that for each valid ledger $l$, if a transaction $tx$ is added to the ledger via the state transition rule UTXOW to the new ledger state $l'$, the balance of the UTxOs in $l$ equals the balance of the UTxOs in $l'$ in the sense that the amount of created value in $l'$ equals the amount of destroyed value in $l$. This means that the total amount of value is left unchanged by a transaction.

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState: \applyFun{validLedgerstate}{l},
    l=(u,\wcard,\wcard,\wcard), l' = (u',\wcard,\wcard,\wcard)\\
    \implies \forall \var{tx} \in \Tx, lenv \in\LEnv, lenv \vdash \var{u}
    \trans{utxow}{tx} \var{u'} \\
    \implies \fun{ubalance}(\applyFun{txins}{tx} \restrictdom
    \applyFun{getUTxO}{u}) = \fun{ubalance}(\applyFun{outs}{tx}) +
    \applyFun{txfee}{tx} + depositChange
\end{multline*}$$ []{#prop:ledger-properties-2 label="prop:ledger-properties-2"}

Property \[prop:ledger-properties-2\] states a slightly more detailed relation of the balances change. For ledgers $l, l'$ and a transaction $tx$ as above, the balance of the UTxOs of $l$ restricted to those whose domain is in the set of transaction inputs of $tx$ equals the balance of the transaction outputs of $tx$ minus the transaction fees and the change in the deposit $depositChange$ (cf. Fig. \[fig:rules:utxo-shelley\]).

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState: \applyFun{validLedgerstate}{l},
    l=(u,\wcard,\wcard,\wcard), l' = (u',\wcard,\wcard,\wcard)\\
    \implies \forall \var{tx} \in \Tx, lenv \in\LEnv, lenv \vdash \var{u}
    \trans{utxow}{tx} \var{u'} \implies \forall \var{out} \in
    \applyFun{outs}{tx}, out \in \applyFun{getUTxO}{u'}
\end{multline*}$$ []{#prop:ledger-properties-3 label="prop:ledger-properties-3"}

Property \[prop:ledger-properties-3\] states that for all ledger states $l, l'$ and transaction $tx$ as above, all output UTxOs of $tx$ are in the UTxO set of $l'$, i.e., they are now available as unspent transaction output.

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState: \applyFun{validLedgerstate}{l},
    l=(u,\wcard,\wcard,\wcard), l' = (u',\wcard,\wcard,\wcard)\\
    \implies \forall \var{tx} \in \Tx, lenv \in\LEnv, lenv \vdash \var{u}
    \trans{utxow}{tx} \var{u'} \implies \forall \var{in} \in
    \applyFun{txins}{tx}, in \not\in \fun{dom}(\applyFun{getUTxO}{u'})
\end{multline*}$$ []{#prop:ledger-properties-4 label="prop:ledger-properties-4"}

Property \[prop:ledger-properties-4\] states that for all ledger states $l, l'$ and transaction $tx$ as above, all transaction inputs $in$ of $tx$ are not in the domain of the UTxO of $l'$, i.e., these are no longer available to spend.

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState: \applyFun{validLedgerstate}{l},
    l=(u,\wcard,\wcard,\wcard), l' = (u',\wcard,\wcard,\wcard)\\
    \implies \forall \var{tx} \in \Tx, lenv \in\LEnv, lenv \vdash \var{u}
    \trans{utxow}{tx} \var{u'} \\ \implies \forall ((txId', \wcard) \mapsto
    \wcard) \in \applyFun{outs}{tx}, ((txId, \wcard) \mapsto \wcard)
    \in\applyFun{getUTxO}{u} \implies \var{txId'} \neq \var{txId}
\end{multline*}$$ []{#prop:ledger-properties-5 label="prop:ledger-properties-5"}

Property \[prop:ledger-properties-5\] states that for ledger states $l, l'$ and a transaction $tx$ as above, the UTxOs of $l'$ contain all newly created UTxOs and the referred transaction id of each new UTxO is not used in the UTxO set of $l$.

<!-- property -->
$$\begin{multline*}
    \forall l_{0},\ldots,l_{n} \in \ledgerState, l_{0} =
    \left(
      \begin{array}{c}
        \left\{
        \genesisUTxO
        \right\} \\
        \left(
        \begin{array}{c}
          \emptyset\\
          \emptyset
        \end{array}
        \right)
      \end{array}
    \right) \wedge \applyFun{validLedgerState} l_{n}, l_{i}=(u_{i},\wcard,\wcard,\wcard)\\
    \implies \forall 0 < i \leq n, tx_{i} \in \Tx, lenv_{i}\in\LEnv,
    lenv_{i} \vdash u_{i-1}
    \trans{ledger}{tx_{i}} u_{i} \wedge \applyFun{validLedgerState} l_{i} \\
    \implies \forall j < i, \applyFun{txins}{tx_{j}} \cap
    \applyFun{txins}{tx_{i}} = \emptyset
\end{multline*}$$ []{#prop:ledger-properties-no-double-spend label="prop:ledger-properties-no-double-spend"}

Property \[prop:ledger-properties-no-double-spend\] states that for each valid ledger state $l_{n}$ reachable from the genesis state, each transaction $t_{i}$ does not share any input with any previous transaction $t_{j}$. This means that each output of a transition is spent at most once.

## Ledger State Properties for Delegation Transitions
$$\begin{align*}
    \fun{getStDelegs} & \in & \DState \to \powerset \Credential \\
    \fun{getStDelegs} & \coloneqq &
                                    ((\var{stkCreds}, \wcard,
                                    \wcard,\wcard,\wcard,\wcard) \to \var{stkCreds} \\
                      &&\\
    \fun{getRewards} & \in & \DState \to (\AddrRWD \mapsto \Coin) \\
    \fun{getRewards} & \coloneqq & (\wcard, \var{rewards},
                                   \wcard,\wcard,\wcard,\wcard)
                                   \to \var{rewards} \\
                      &&\\
    \fun{getDelegations} & \in & \DState \to (\Credential \mapsto \KeyHash) \\
    \fun{getDelegations} & \coloneqq & (\wcard, \wcard,
                                       \var{delegations},\wcard,\wcard,\wcard) \to
                                       \var{delegations} \\
                      &&\\
    \fun{getStPools} & \in & \LState \to (\KeyHash \mapsto \DCertRegPool) \\
    \fun{getStPools} & \coloneqq & (\wcard, (\wcard,
                                   (\var{stpools},\wcard,\wcard,\wcard))) \to \var{stpools} \\
                      &&\\
    \fun{getRetiring} & \in & \LState \to (\KeyHash \mapsto \Epoch) \\
    \fun{getRetiring} & \coloneqq & (\wcard, (\wcard,
                                    (\wcard, \wcard, \var{retiring},\wcard))) \to \var{retiring} \\
\end{align*}$$

**Definitions and Functions for Stake Delegation in Ledger States**

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState: \applyFun{validLedgerstate}{l},
    l = (\wcard, ((d, \wcard), \wcard)), l' = (\wcard, ((d',\wcard), \wcard)), dEnv\in\DEnv \\
    \implies \forall \var{c} \in \DCertRegKey, dEnv\vdash \var{d}
    \trans{deleg}{c} \var{d'} \implies \applyFun{cwitness}{c} = \var{hk}\\
    \implies hk\not\in \fun{getStDelegs}~\var{d} \implies \var{hk} \in
    \applyFun{getStDelegs}{d'} \wedge
    (\applyFun{getRewards}\var{d'})[\fun{addr_{rwd}}{hk}] = 0
\end{multline*}$$ []{#prop:ledger-properties-6 label="prop:ledger-properties-6"}

Property \[prop:ledger-properties-6\] states that for each valid ledger state $l$, if a delegation transaction of type $\DCertRegKey$ is executed, then in the resulting ledger state $l'$, the set of staking credential of $l'$ includes the credential $hk$ associated with the key registration certificate and the associated reward is set to 0 in $l'$.

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState: \applyFun{validLedgerstate}{l},
    l = (\wcard, (d, \wcard)), l' = (\wcard, (d', \wcard)), dEnv\in\DEnv \\
    \implies \forall \var{c} \in \DCertDeRegKey, dEnv\vdash\var{d}
    \trans{deleg}{c} \var{d'} \implies \applyFun{cwitness}{c} = \var{hk}\\
    \implies \var{hk} \not\in \applyFun{getStDelegs}{d'} \wedge hk\not\in
    \left\{ \fun{stakeCred_{r}}~sc\vert
      sc\in\fun{dom}(\applyFun{getRewards}{d'})
    \right\}\\
    \wedge hk \not\in \fun{dom}(\applyFun{getDelegations}{d'}))
\end{multline*}$$ []{#prop:ledger-properties-7 label="prop:ledger-properties-7"}

Property \[prop:ledger-properties-7\] states that for $l, l'$ as above but with a delegation transition of type $\DCertDeRegKey$, the staking credential $hk$ associated with the deregistration certificate is not in the set of staking credentials of $l'$ and is not in the domain of either the rewards or the delegation map of $l'$.

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState: \applyFun{validLedgerstate}{l},
    l = (\wcard, (d,\wcard)), l' = (\wcard, (d',\wcard)), dEnv\in\DEnv \\
    \implies \forall \var{c} \in \DCertDeleg, dEnv \vdash\var{d}
    \trans{deleg}{c} \var{d'} \implies \applyFun{cwitness}{c} = \var{hk}\\
    \implies \var{hk} \in \applyFun{getStDelegs}{d'} \wedge
    (\applyFun{getDelegations}{d'})[hk] = \applyFun{dpool}{c}
\end{multline*}$$ []{#prop:ledger-properties-8 label="prop:ledger-properties-8"}

Property \[prop:ledger-properties-8\] states that for $l, l'$ as above but with a delegation transition of type $\DCertDeleg$, the staking credential $hk$ associated with the deregistration certificate is in the set of staking credentials of $l$ and delegates to the staking pool associated with the delegation certificate in $l'$.

<!-- property -->
[]{#prop:genkeys-delegated label="prop:genkeys-delegated"} $$\begin{multline*}
    \forall \var{l}, \var{l'} \in \LState: \applyFun{validLedgerstate}{l},\\
    \implies \forall \Gamma \in \seqof{\Tx}, env \in (\Slot \times \PParams), \\
    env \vdash\var{l} \trans{ledgers}{\Gamma} \var{l'} \implies |genDelegs| = 7
\end{multline*}$$

Property \[prop:genkeys-delegated\] states that all seven of the genesis keys are constantly all delegated after applying a list of transactions to a valid ledger state.

## Ledger State Properties for Staking Pool Transitions
<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState: \applyFun{validLedgerstate}{l},
    l = (\wcard, (\wcard, p)), l' = (\wcard, (\wcard, p')), pEnv\in\PEnv \\
    \implies \forall \var{c} \in \DCertRegPool, \var{p} \trans{pool}{c} \var{p'}
    \implies \applyFun{cwitness}{c} = \var{hk}\\ \implies
    \var{hk}\in\applyFun{getStPools}{p'} \wedge \var{hk} \not\in
    \applyFun{getRetiring}{p'}
\end{multline*}$$ []{#prop:ledger-properties-9 label="prop:ledger-properties-9"}

Property \[prop:ledger-properties-9\] states that for $l, l'$ as above but with a delegation transition of type $\DCertRegPool$, the key $hk$ is associated with the author of the pool registration certificate in $\var{stpools}$ of $l'$ and that $hk$ is not in the set of retiring stake pools in $l'$.

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState, \var{cepoch} \in \Epoch:
    \applyFun{validLedgerstate}{l},
    l = (\wcard, (\wcard,p)), l' = (\wcard, (\wcard,p')), pEnv\in\PEnv \\
    \implies \forall \var{c} \in \DCertRetirePool, pEnv\vdash\var{p}
    \trans{POOL}{c} \var{p'} \\ \implies e = \applyFun{retire}{c} \wedge
    \var{cepoch} < e < \var{cepoch} + \emax \wedge \applyFun{cwitness}{c} =
    \var{hk}\\ \implies (\applyFun{getRetiring}{p'})[\var{hk}] = e \wedge
    \var{hk} \in
    \fun{dom}(\applyFun{getStPools}{p})\wedge\fun{dom}(\applyFun{getStPools}{p'}
    )
\end{multline*}$$ []{#prop:ledger-properties-10 label="prop:ledger-properties-10"}

Property \[prop:ledger-properties-10\] states that for $l, l'$ as above but with a delegation transition of type $\DCertRetirePool$, the key $hk$ is associated with the author of the pool registration certificate in $\var{stpools}$ of $l'$ and that $hk$ is in the map of retiring staking pools of $l'$ with retirement epoch $e$, as well as that $hk$ is in the map of stake pools in $l$ and $l'$.

<!-- property -->
$$\begin{multline*}
    \forall \var{l}, \var{l'} \in \ledgerState, \var{e} \in \Epoch:
    \applyFun{validLedgerstate}{l},\\
    l = (\wcard, (d, p)), l' = (\wcard, (d', p')), pp\in\PParams, acnt, acnt'\in\Acnt \\
    \implies pp\vdash\var{(acnt, d, p} \trans{poolreap}{e} \var{(acnt, d', p')}
    \implies \forall \var{retire}\in{(\fun{getRetiring}~p)}^{-1}[e], retire \neq
    \emptyset \\ \wedge \var{retire} \subseteq
    \fun{dom}(\applyFun{getStPool}{p}) \wedge
    \var{retire} \cap\fun{dom}(\applyFun{getStPool}{p'})=\emptyset \\
    \wedge\var{retire} \cap \fun{dom}(\applyFun{getRetiring}{p'}) = \emptyset
\end{multline*}$$ []{#prop:ledger-properties-11 label="prop:ledger-properties-11"}

Property \[prop:ledger-properties-11\] states that for $l, l'$ as above but with a delegation transition of type POOLREAP, there exist registered stake pools in $l$ which are associated to stake pool registration certificates and which are to be retired at the current epoch $\var{e}$. In $l'$ all those stake pools are removed from the maps $stpools$ and $retiring$.

## Properties of Numerical Calculations
The numerical calculations for refunds and rewards in (see Section \[sec:epoch\]) are also required to have certain properties. In particular we need to make sure that the functions that use non-integral arithmetic have properties which guarantee consistency of the system. Here, we state those properties and formulate them in a way that makes them usable in properties-based testing for validation in the executable spec.

<!-- property -->
[]{#prop:minimal-refund label="prop:minimal-refund"}

The function $\fun{refund}$ takes a value, a minimal percentage, a decay parameter and a duration. It must guarantee that the refunded amount is within the minimal refund (off-by-one for rounding / floor) and the original value.

$$\begin{multline*}
    \forall d_{val} \in \mathbb{N}, d_{min} \in [0,1], \lambda \in (0, \infty),
    \delta \in \mathbb{N} \\
    \implies \max(0,d_{val}\cdot d_{min} - 1) \leq \floor*{d_{val}\cdot(d_{min} +
      (1-d_{min})\cdot e^{-\lambda\cdot\delta})} \leq d_{val}
\end{multline*}$$

<!-- property -->
[]{#prop:maximal-pool-reward label="prop:maximal-pool-reward"}

The maximal pool reward is the expected maximal reward paid to a stake pool. The sum of all these rewards cannot exceed the total available reward, let $Pool$ be the set of active stake pools:

$$\begin{equation*}
    \forall R \in Coin:\sum_{p \in Pools} \floor*{\frac{R}{1+p_{a_{0}}}\cdot
      \left(
        p_{\sigma'}+p_{p'}\cdotp_{a_{0}}\cdot\frac{p_{\sigma'}-p_{p'}\cdot\frac{p_{z_{0}}-p_{\sigma'}}{p_{z_{0}}}}{p_{z_{0}}}
      \right)}\leq R
\end{equation*}$$

<!-- property -->
[]{#prop:actual-reward label="prop:actual-reward"}

The actual reward for a stake pool in an epoch is calculated by the function $\fun{poolReward}$. The actual reward per stake pool is non-negative and bounded by the maximal reward for the stake pool, with $\overline{p}$ being the relation $\frac{n}{\max(1, \overline{N})}$ of the number of produced blocks $n$ of one pool to the total number $\overline{N}$ of produced blocks in an epoch and $maxP$ being the maximal reward for the stake pool. This gives us:

$$\begin{equation*}
    \forall \gamma \in [0,1] \implies 0\leq \floor*{\overline{p}\cdot maxP} \leq maxP
\end{equation*}$$

The two functions $\fun{r_{operator}}$ and $\fun{r_{member}}$ are closely related as they both split the reward between the pool leader and the members.

<!-- property -->
[]{#prop:reward-splitting label="prop:reward-splitting"}

The reward splitting is done via $\fun{r_{operator}}$ and $\fun{r_{member}}$, i.e., a split between the pool leader and the pool members using the pool cost $c$ and the pool margin $m$. Therefore the property relates the total reward $\hat{f}$ to the split rewards in the following way:

$$\begin{multline*}
    \forall m\in [0,1], c\in Coin \implies c + \floor*{(\hat{f} - c)\cdot (m +
      (1 - m)) \cdot \frac{s}{\sigma}} + \sum_{j}\floor*{(\hat{f} -
      c)\cdot(1-m)\cdot\frac{t_{j}}{\sigma}} \leq \hat{f}
\end{multline*}$$

[^1]: i.e. the component $\var{s_\ell}$ of the last applied block of $s$ equals $t$
