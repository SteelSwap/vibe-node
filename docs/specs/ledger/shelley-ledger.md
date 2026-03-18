# Ledger State Transition
The entire state transformation of the ledger state caused by a valid transaction can now be given as the combination of the UTxO transition and the delegation transitions.

Figure 1 defines the types for this transition. The environment for this rule consists of:

- The current slot.

- The transaction index within the current block.

- The protocol parameters.

- The accounting state.

The ledger state consists of:

- The UTxO state.

- The delegation and pool states.


*Ledger environment* $$\begin{equation*}
    \mathsf{LEnv} =
    \left(
      \begin{array}{rlr}
        \mathit{slot} & \mathsf{Slot} & \text{current slot}\\
        \mathit{txIx} & \mathsf{Ix} & \text{transaction index}\\
        \mathit{pp} & \mathsf{PParams} & \text{protocol parameters}\\
        \mathit{acnt} & \mathsf{Acnt} & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ *Ledger state* $$\begin{equation*}
    \mathsf{LState} =
    \left(
      \begin{array}{rlr}
        \mathit{utxoSt} & \mathsf{UTxOState} & \text{UTxO state}\\
        \mathit{dpstate} & \mathsf{DPState} & \text{delegation and pool state}\\
      \end{array}
    \right)
\end{equation*}$$ *Ledger transitions* $$\begin{equation*}
    \_ \vdash
    \mathit{\_} \xrightarrow[\mathsf{ledger}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{LEnv} \times \mathsf{LState} \times \mathsf{Tx} \times \mathsf{LState})
\end{equation*}$$

**Ledger transition-system types**
Figure 1 defines the ledger state transition. It has a single rule, which first calls the $\mathsf{UTXOW}$ transition, then calls the $\mathsf{DELEGS}$ transition.


$$\begin{equation}
    \label{eq:ledger}
    \inference[ledger]
    {
      {
        \begin{array}{c}
          \mathit{slot} \\
          \mathit{txIx} \\
          \mathit{pp} \\
          \mathit{tx}\\
          \mathit{acnt}
        \end{array}
      }
      \vdash
      dpstate \xrightarrow[\mathsf{\hyperref[fig:rules:delegation-sequence]{delegs}}]{}{
        \mathsf{txcerts}~\mathit{(\mathsf{txbody}~tx)}} dpstate'
      \\~\\
      (\mathit{dstate}, \mathit{pstate}) \mathrel{\mathop:}= \mathit{dpstate} \\
      (\_, \_, \_, \_, \mathit{genDelegs}, \_) \mathrel{\mathop:}= \mathit{dstate} \\
      (\mathit{poolParams}, \_, \_) \mathrel{\mathop:}= \mathit{pstate} \\
      \\~\\
      {
        \begin{array}{c}
        \mathit{slot} \\
        \mathit{pp} \\
        \mathit{poolParams} \\
        \mathit{genDelegs} \\
        \end{array}
      }
      \vdash \mathit{utxoSt} \xrightarrow[\mathsf{\hyperref[fig:rules:utxow-shelley]{utxow}}]{}{tx} \mathit{utxoSt'}
    }
    {
      \begin{array}{c}
        \mathit{slot} \\
        \mathit{txIx} \\
        \mathit{pp} \\
        \mathit{acnt}
      \end{array}
      \vdash
      \left(
        \begin{array}{ll}
          \mathit{utxoSt} \\
          \mathit{dpstate} \\
        \end{array}
      \right)
      \xrightarrow[\mathsf{ledger}]{}{tx}
      \left(
        \begin{array}{ll}
          \mathsf{varUpdate}~utxoSt' \\
          \mathsf{varUpdate}~dpstate' \\
        \end{array}
      \right)
    }
\end{equation}$$

**Ledger inference rule**
The transition system $\mathsf{LEDGER}$ in Figure 2 is iterated in $\mathsf{LEDGERS}$ in order to process a list of transactions.


*Ledger Sequence transitions* $$\begin{equation*}
    \_ \vdash
    \mathit{\_} \xrightarrow[\mathsf{ledgers}]{}{\_} \mathit{\_}
    \subseteq \powerset ((\mathsf{Slot}\times\mathsf{PParams}\times\mathsf{Coin}) \times \mathsf{LState} \times \mathsf{Tx}^{*} \times \mathsf{LState})
\end{equation*}$$

**Ledger Sequence transition-system types**
$$\begin{equation}
    \label{eq:ledgers-base}
    \inference[Seq-ledger-base]
    { }
    {
      \begin{array}{r}
        \mathit{slot}\\
        \mathit{pp}\\
        \mathit{acnt}
      \end{array}
      \vdash \mathit{ls} \xrightarrow[\mathsf{ledgers}]{}{\epsilon} \mathsf{varUpdate}~\mathit{ls'}
    }
\end{equation}$$

$$\begin{equation}
    \label{eq:ledgers-induct}
    \inference[Seq-ledger-ind]
    {
      {
        \begin{array}{r}
          \mathit{slot}\\
          \mathit{pp}\\
          \mathit{acnt}
        \end{array}
      }
      \vdash
      \mathit{ls}
      \xrightarrow[\mathsf{ledgers}]{}{\Gamma}
      \mathit{ls'}
      &
      {
        \begin{array}{r}
          \mathit{slot}\\
          \mathsf{len}~\Gamma - 1\\
          \mathit{pp}\\
          \mathit{acnt}
        \end{array}
      }
      \vdash
        \mathit{ls'}
        \xrightarrow[\mathsf{\hyperref[fig:rules:ledger]{ledger}}]{}{\mathit{tx}}
        \mathit{ls''}
    }
    {
      \begin{array}{r}
        \mathit{slot}\\
        \mathit{pp}\\
        \mathit{acnt}
      \end{array}
    \vdash
      \mathit{ls}
      \xrightarrow[\mathsf{ledgers}]{}{\Gamma;~\mathit{tx}}
      \mathsf{varUpdate}~\mathit{ls''}
    }
\end{equation}$$

**Ledger sequence rules**