# Ledger State Transition {#sec:ledger-trans}

The entire state transformation of the ledger state caused by a valid transaction can now be given as the combination of the UTxO transition and the delegation transitions.

Figure [1](#fig:ts-types:ledger){reference-type="ref" reference="fig:ts-types:ledger"} defines the types for this transition. The environment for this rule consists of:

- The current slot.

- The transaction index within the current block.

- The protocol parameters.

- The accounting state.

The ledger state consists of:

- The UTxO state.

- The delegation and pool states.

:::: {#fig:ts-types:ledger .figure latex-placement="htb"}
*Ledger environment* $$\begin{equation*}
    \LEnv =
    \left(
      \begin{array}{rlr}
        \var{slot} & \Slot & \text{current slot}\\
        \var{txIx} & \Ix & \text{transaction index}\\
        \var{pp} & \PParams & \text{protocol parameters}\\
        \var{acnt} & \Acnt & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ *Ledger state* $$\begin{equation*}
    \LState =
    \left(
      \begin{array}{rlr}
        \var{utxoSt} & \UTxOState & \text{UTxO state}\\
        \var{dpstate} & \DPState & \text{delegation and pool state}\\
      \end{array}
    \right)
\end{equation*}$$ *Ledger transitions* $$\begin{equation*}
    \_ \vdash
    \var{\_} \trans{ledger}{\_} \var{\_}
    \subseteq \powerset (\LEnv \times \LState \times \Tx \times \LState)
\end{equation*}$$

::: caption
Ledger transition-system types
:::
::::

Figure [1](#fig:ts-types:ledger){reference-type="ref" reference="fig:ts-types:ledger"} defines the ledger state transition. It has a single rule, which first calls the $\mathsf{UTXOW}$ transition, then calls the $\mathsf{DELEGS}$ transition.

:::: {#fig:rules:ledger .figure}
$$\begin{equation}
    \label{eq:ledger}
    \inference[ledger]
    {
      {
        \begin{array}{c}
          \var{slot} \\
          \var{txIx} \\
          \var{pp} \\
          \var{tx}\\
          \var{acnt}
        \end{array}
      }
      \vdash
      dpstate \trans{\hyperref[fig:rules:delegation-sequence]{delegs}}{
        \fun{txcerts}~\var{(\txbody{tx})}} dpstate'
      \\~\\
      (\var{dstate}, \var{pstate}) \leteq \var{dpstate} \\
      (\_, \_, \_, \_, \var{genDelegs}, \_) \leteq \var{dstate} \\
      (\var{poolParams}, \_, \_) \leteq \var{pstate} \\
      \\~\\
      {
        \begin{array}{c}
        \var{slot} \\
        \var{pp} \\
        \var{poolParams} \\
        \var{genDelegs} \\
        \end{array}
      }
      \vdash \var{utxoSt} \trans{\hyperref[fig:rules:utxow-shelley]{utxow}}{tx} \var{utxoSt'}
    }
    {
      \begin{array}{c}
        \var{slot} \\
        \var{txIx} \\
        \var{pp} \\
        \var{acnt}
      \end{array}
      \vdash
      \left(
        \begin{array}{ll}
          \var{utxoSt} \\
          \var{dpstate} \\
        \end{array}
      \right)
      \trans{ledger}{tx}
      \left(
        \begin{array}{ll}
          \varUpdate{utxoSt'} \\
          \varUpdate{dpstate'} \\
        \end{array}
      \right)
    }
\end{equation}$$

::: caption
Ledger inference rule
:::
::::

The transition system $\mathsf{LEDGER}$ in Figure [2](#fig:rules:ledger){reference-type="ref" reference="fig:rules:ledger"} is iterated in $\mathsf{LEDGERS}$ in order to process a list of transactions.

:::: {#fig:ts-types:ledgers .figure latex-placement="htb"}
*Ledger Sequence transitions* $$\begin{equation*}
    \_ \vdash
    \var{\_} \trans{ledgers}{\_} \var{\_}
    \subseteq \powerset ((\Slot\times\PParams\times\Coin) \times \LState \times \seqof{\Tx} \times \LState)
\end{equation*}$$

::: caption
Ledger Sequence transition-system types
:::
::::

:::: {#fig:rules:ledger-sequence .figure latex-placement="hbt"}
$$\begin{equation}
    \label{eq:ledgers-base}
    \inference[Seq-ledger-base]
    { }
    {
      \begin{array}{r}
        \var{slot}\\
        \var{pp}\\
        \var{acnt}
      \end{array}
      \vdash \var{ls} \trans{ledgers}{\epsilon} \varUpdate{\var{ls'}}
    }
\end{equation}$$

$$\begin{equation}
    \label{eq:ledgers-induct}
    \inference[Seq-ledger-ind]
    {
      {
        \begin{array}{r}
          \var{slot}\\
          \var{pp}\\
          \var{acnt}
        \end{array}
      }
      \vdash
      \var{ls}
      \trans{ledgers}{\Gamma}
      \var{ls'}
      &
      {
        \begin{array}{r}
          \var{slot}\\
          \mathsf{len}~\Gamma - 1\\
          \var{pp}\\
          \var{acnt}
        \end{array}
      }
      \vdash
        \var{ls'}
        \trans{\hyperref[fig:rules:ledger]{ledger}}{\var{tx}}
        \var{ls''}
    }
    {
      \begin{array}{r}
        \var{slot}\\
        \var{pp}\\
        \var{acnt}
      \end{array}
    \vdash
      \var{ls}
      \trans{ledgers}{\Gamma;~\var{tx}}
      \varUpdate{\var{ls''}}
    }
\end{equation}$$

::: caption
Ledger sequence rules
:::
::::
