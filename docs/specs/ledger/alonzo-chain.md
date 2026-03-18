# Blockchain layer
## Block Body Transition
In Figure 1, we have added the check that the sum total of script fees all transactions in a block pay do not exceed the maximum total fees per block (stored as a protocol parameter).


$$\begin{equation}
\label{eq:bbody}
    \inference[Block-Body]
    {
      \mathit{txs} \mathrel{\mathop:}= \mathsf{bbody}~block
      &
      \mathit{bhb} \mathrel{\mathop:}= \bhbody\mathsf{bheader}~\mathit{block}
      &
      \mathit{hk} \mathrel{\mathop:}= \hashKey\mathsf{bvkcold}~\mathit{bhb}
      \\~\\
      \mathsf{bBodySize}~ \mathit{txs} = \mathsf{hBbsize}~\mathit{bhb}
      &
      \mathsf{hash}~{txs} = \mathsf{bbodyhash}~\mathit{bhb}
      \\~\\
      \sum_{tx\in txs} \mathsf{txexunits}~(\txbody~{tx}) \leq \mathsf{maxBlockExUnits}~\mathit{pp}
      \\~\\
      {
        {\begin{array}{c}
                 \mathsf{bslot}~bhb \\
                 \mathit{pp} \\
                 \mathit{reserves}
        \end{array}}
        \vdash
             \mathit{ls} \\
        \xrightarrow[\mathsf{\hyperref[fig:rules:ledger-sequence]{ledgers}}]{}{\mathit{txs}}
             \mathit{ls}' \\
      }
    }
    {
      {\begin{array}{c}
               \mathit{oslots} \\
               \mathit{pp} \\
               \mathit{reserves}
      \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \mathit{ls} \\
            \mathit{b} \\
      \end{array}\right)}
      \xrightarrow[\mathsf{bbody}]{}{\mathit{block}}
      {\left(\begin{array}{c}
            \mathsf{varUpdate}~\mathit{ls}' \\
            \varUpdate{\mathsf{incrBlocks}~{(\mathsf{bslot}~bhb\in\mathit{oslots})}~{hk}~{b}} \\
      \end{array}\right)}
    }
\end{equation}$$

**BBody rules**
We have also defined a function that transforms the Shelley ledger state into the Goguen one, see Figure 3. Note that here we refer to Shelley-era protocol parameter type as $\mathsf{ShelleyPParams}$, and the Goguen type as $\mathsf{PParams}$. We use the notation $\mathit{chainstate}_{x}$ to represent variable $x$ in the chain state. We do not specify the variables that remain unchanged during the transition.

::: note
**What creation slots should Shelley era UTxOs have?** It is not yet clear whether we will follow the approach of making the creation slot of every Shelley-era UTxO entry the first slot of Goguen. It is possible to look through all the blocks and add the correct one, but not clear if necessary. The other option is to allow both types out outputs, some without the creation slot.

*Types and Constants* $$\begin{align*}
      & s_{last} \\
      & \text{last slot of Shelley era} \\
      & \mathsf{NewParams} ~=~ (\mathsf{Language} \mapsto \mathsf{CostMod}) \times \mathsf{Prices} \times \mathsf{ExUnits} \times \mathsf{ExUnits} \\
      & \text{the type of new parameters to add for Goguen}
      \\[0.5em]
      & \mathsf{ivPP} ~\in~ \mathsf{NewParams} \\
      & \text{the initial values for new Goguen parameters}
\end{align*}$$ *Shelley to Goguen Transition Functions* $$\begin{align*}
      & \mathsf{mkUTxO} ~\in~ \mathsf{Slot} \to \mathsf{ShelleyUTxO}  \to \mathsf{UTxO}  \\
      & \mathsf{mkUTxO}~s~\mathit{utxo} ~=~ \{~ \mathit{txin} \mapsto ((a,\mathsf{coinToValue}~c),s) ~\vert~
      \mathit{txin} \mapsto \mathit{(a,c)}\in ~\mathit{utxo}~\} \\
      & \text{make UTxO Goguen}
      \\[0.5em]
      & \mathsf{toGoguen} \in ~ \mathsf{ShelleyChainState} \to \mathsf{ChainState}\\
      & \mathsf{toGoguen}~\mathit{chainstate} =~\mathit{chainstate'} \\
      &~~\where \\
      &~~~~\mathit{chainstate'}_{utxo}~=~\mathsf{mkUTxO}~s_{last}~\mathit{utxo} \\
      &~~~~\mathit{chainstate'}_{pparams}~=~\mathit{pp}\cup \mathsf{ivPP}\\
      & \text{transform Shelley chain state to Goguen state}
\end{align*}$$

**Shelley to Goguen State Transtition**
The transformation we use in the preceeding rules to turn a Shelley transaction into a Goguen one is given in Figure 3. Recall that it stays the same if the same if it was already a Goguen one.


*Functions* $$\begin{align*}
      & \mathsf{mkIns} ~\in~ \mathbb{P}~\mathsf{ShelleyTxIn} \to \mathbb{P}~\mathsf{TxIn}  \\
      & \mathsf{mkIns}~\mathit{ins} ~=~ \{~ (\mathit{txin}, \mathsf{Yes}) ~\vert~
      \mathit{txin} \in \mathit{ins}~\} \\
      & \text{transform Shelley inputs into Goguen inputs}
      \\[0.5em]
      & \mathsf{toGoguenTx} ~\in~  \mathsf{Tx} \to \mathsf{GoguenTx} \\
      & \text{outputs a Goguen tx given any tx} \\
      & \mathsf{toGoguenTx} ~=
          \begin{cases}
           \mathsf{tg}~\mathit{tx}  & \text{if~} \mathit{tx} \in \mathsf{ShelleyTx} \\
                \mathit{tx} & \text{otherwise}
              \end{cases}
      \\[0.5em]
      & \mathsf{tg} ~\in~  \mathsf{Tx} \to \mathsf{GoguenTx} \\
      & \text{transform a Shelley transaction into a Goguen transaction as follows:} \\
      & ~~\mathsf{txinputs}~{txb'} ~=~ \mathsf{mkIns}~(\mathsf{txins}~{txb}) \\
      & ~~\mathsf{forge}~{txb'} ~= ~\epsilon \\
      & ~~\mathsf{txexunits}~{txb'} ~= ~(0,0) \\
      & ~~\mathsf{txfst}~{txb'} ~= ~0 \\
      & ~~\mathsf{ppHash}~{txb'} ~= ~\mathsf{Nothing} \\
      & ~~\mathsf{rdmrsHash}~{txb'} ~= ~\mathsf{Nothing} \\~\\
      & ~~\mathsf{txwits}~{tx'} ~= ~(\epsilon,\emptyset,\emptyset,\epsilon) \\
      & ~~\mathsf{txvaltag}~{tx'} ~= ~\mathsf{Yes} \\
      &~~      \where \\
      & ~~~~~~~ \mathit{txb}~=~\mathsf{txbody}~tx \\
      & ~~~~~~~ \mathit{txb'}~=~\mathsf{txbody}~tx'
\end{align*}$$

**Shelley to Goguen Transaction Interpretation**