# Blockchain layer {#sec:chain}

## Block Body Transition {#sec:block-body-trans}

In Figure [1](#fig:rules:bbody){reference-type="ref" reference="fig:rules:bbody"}, we have added the check that the sum total of script fees all transactions in a block pay do not exceed the maximum total fees per block (stored as a protocol parameter).

:::: {#fig:rules:bbody .figure latex-placement="ht"}
$$\begin{equation}
\label{eq:bbody}
    \inference[Block-Body]
    {
      \var{txs} \leteq \bbody{block}
      &
      \var{bhb} \leteq \bhbody\fun{bheader}~\var{block}
      &
      \var{hk} \leteq \hashKey\fun{bvkcold}~\var{bhb}
      \\~\\
      \fun{bBodySize}~ \var{txs} = \fun{hBbsize}~\var{bhb}
      &
      \fun{hash}~{txs} = \fun{bbodyhash}~\var{bhb}
      \\~\\
      \sum_{tx\in txs} \fun{txexunits}~(\txbody~{tx}) \leq \fun{maxBlockExUnits}~\var{pp}
      \\~\\
      {
        {\begin{array}{c}
                 \bslot{bhb} \\
                 \var{pp} \\
                 \var{reserves}
        \end{array}}
        \vdash
             \var{ls} \\
        \trans{\hyperref[fig:rules:ledger-sequence]{ledgers}}{\var{txs}}
             \var{ls}' \\
      }
    }
    {
      {\begin{array}{c}
               \var{oslots} \\
               \var{pp} \\
               \var{reserves}
      \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \var{ls} \\
            \var{b} \\
      \end{array}\right)}
      \trans{bbody}{\var{block}}
      {\left(\begin{array}{c}
            \varUpdate{\var{ls}'} \\
            \varUpdate{\fun{incrBlocks}~{(\bslot{bhb}\in\var{oslots})}~{hk}~{b}} \\
      \end{array}\right)}
    }
\end{equation}$$

::: caption
BBody rules
:::
::::

We have also defined a function that transforms the Shelley ledger state into the Goguen one, see Figure [3](#fig:functions:to-shelley){reference-type="ref" reference="fig:functions:to-shelley"}. Note that here we refer to Shelley-era protocol parameter type as $\ShelleyPParams$, and the Goguen type as $\PParams$. We use the notation $\var{chainstate}_{x}$ to represent variable $x$ in the chain state. We do not specify the variables that remain unchanged during the transition.

::: note
**What creation slots should Shelley era UTxOs have?** It is not yet clear whether we will follow the approach of making the creation slot of every Shelley-era UTxO entry the first slot of Goguen. It is possible to look through all the blocks and add the correct one, but not clear if necessary. The other option is to allow both types out outputs, some without the creation slot.
:::

:::: {#fig:functions:to-shelley .figure latex-placement="htb"}
*Types and Constants* $$\begin{align*}
      & s_{last} \\
      & \text{last slot of Shelley era} \\
      & \NewParams ~=~ (\Language \mapsto \CostMod) \times \Prices \times \ExUnits \times \ExUnits \\
      & \text{the type of new parameters to add for Goguen}
      \nextdef
      & \mathsf{ivPP} ~\in~ \NewParams \\
      & \text{the initial values for new Goguen parameters}
\end{align*}$$ *Shelley to Goguen Transition Functions* $$\begin{align*}
      & \fun{mkUTxO} ~\in~ \Slot \to \ShelleyUTxO  \to \UTxO  \\
      & \fun{mkUTxO}~s~\var{utxo} ~=~ \{~ \var{txin} \mapsto ((a,\fun{coinToValue}~c),s) ~\vert~
      \var{txin} \mapsto \var{(a,c)}\in ~\var{utxo}~\} \\
      & \text{make UTxO Goguen}
      \nextdef
      & \fun{toGoguen} \in ~ \ShelleyChainState \to \type{ChainState}\\
      & \fun{toGoguen}~\var{chainstate} =~\var{chainstate'} \\
      &~~\where \\
      &~~~~\var{chainstate'}_{utxo}~=~\fun{mkUTxO}~s_{last}~\var{utxo} \\
      &~~~~\var{chainstate'}_{pparams}~=~\var{pp}\cup \mathsf{ivPP}\\
      & \text{transform Shelley chain state to Goguen state}
\end{align*}$$

::: caption
Shelley to Goguen State Transtition
:::
::::

The transformation we use in the preceeding rules to turn a Shelley transaction into a Goguen one is given in Figure [3](#fig:functions:to-shelley){reference-type="ref" reference="fig:functions:to-shelley"}. Recall that it stays the same if the same if it was already a Goguen one.

:::: {#fig:functions:to-shelley .figure latex-placement="htb"}
*Functions* $$\begin{align*}
      & \fun{mkIns} ~\in~ \powerset{\ShelleyTxIn} \to \powerset{\TxIn}  \\
      & \fun{mkIns}~\var{ins} ~=~ \{~ (\var{txin}, \Yes) ~\vert~
      \var{txin} \in \var{ins}~\} \\
      & \text{transform Shelley inputs into Goguen inputs}
      \nextdef
      & \fun{toGoguenTx} ~\in~  \Tx \to \GoguenTx \\
      & \text{outputs a Goguen tx given any tx} \\
      & \fun{toGoguenTx} ~=
          \begin{cases}
           \fun{tg}~\var{tx}  & \text{if~} \var{tx} \in \ShelleyTx \\
                \var{tx} & \text{otherwise}
              \end{cases}
      \nextdef
      & \fun{tg} ~\in~  \Tx \to \GoguenTx \\
      & \text{transform a Shelley transaction into a Goguen transaction as follows:} \\
      & ~~\fun{txinputs}~{txb'} ~=~ \fun{mkIns}~(\fun{txins}~{txb}) \\
      & ~~\fun{forge}~{txb'} ~= ~\epsilon \\
      & ~~\fun{txexunits}~{txb'} ~= ~(0,0) \\
      & ~~\fun{txfst}~{txb'} ~= ~0 \\
      & ~~\fun{ppHash}~{txb'} ~= ~\Nothing \\
      & ~~\fun{rdmrsHash}~{txb'} ~= ~\Nothing \\~\\
      & ~~\fun{txwits}~{tx'} ~= ~(\epsilon,\emptyset,\emptyset,\epsilon) \\
      & ~~\fun{txvaltag}~{tx'} ~= ~\Yes \\
      &~~      \where \\
      & ~~~~~~~ \var{txb}~=~\txbody{tx} \\
      & ~~~~~~~ \var{txb'}~=~\txbody{tx'}
\end{align*}$$

::: caption
Shelley to Goguen Transaction Interpretation
:::
::::
