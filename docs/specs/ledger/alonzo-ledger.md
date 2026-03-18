# Ledger State Transition
Figure 1 now separates the cases where all scripts validate in a transaction and the case where there is one that does not. The cases are distinguished by the use of the $\mathsf{IsValidating}$ tag.

Besides fee collection, no side effects should occur when processing a transaction containing a script that does not validate. That is, no delegation or pool state updates, or update proposals should be applied. The UTxO rule is still applied, as this is where the correctness of the validation tag is verified, and script fees are collected.


$$\begin{equation}
    \label{eq:ledger}
    \inference[ledger-V]
    {
      \mathit{txb}\mathrel{\mathop:}=\mathsf{txbody}~tx \\
      \mathsf{txvaltag}~{tx} \in \mathsf{Yes} \\~\\
      {
        \begin{array}{c}
          \mathit{slot} \\
          \mathit{txIx} \\
          \mathit{pp} \\
          \mathit{tx}\\
          \mathit{reserves}
        \end{array}
      }
      \vdash
      dpstate \xrightarrow[\mathsf{\hyperref[fig:rules:delegation-sequence]{delegs}}]{}{
                     \mathsf{txcerts}~\mathit{txb}} dpstate'
      \\~\\
      (\mathit{dstate}, \mathit{pstate}) \mathrel{\mathop:}= \mathit{dpstate} \\
      (\mathit{stkCreds}, \_, \_, \_, \_, \mathit{genDelegs}, \_) \mathrel{\mathop:}= \mathit{dstate} \\
      (\mathit{stpools}, \_, \_) \mathrel{\mathop:}= \mathit{pstate} \\
      \\~\\
      {
        \begin{array}{c}
        \mathit{slot} \\
        \mathit{pp} \\
        \mathit{stkCreds} \\
        \mathit{stpools} \\
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
        \mathit{reserves}
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
\end{equation}$$ $$\begin{equation}
    \label{eq:ledger}
    \inference[ledger-NV]
    {
      \mathsf{txvaltag}~{tx} \in \mathsf{Nope} \\~\\
      (\mathit{dstate}, \mathit{pstate}) \mathrel{\mathop:}= \mathit{dpstate} \\
      (\mathit{stkCreds}, \_, \_, \_, \_, \mathit{genDelegs}, \_) \mathrel{\mathop:}= \mathit{dstate} \\
      (\mathit{stpools}, \_, \_) \mathrel{\mathop:}= \mathit{pstate} \\
      \\~\\
      {
        \begin{array}{c}
        \mathit{slot} \\
        \mathit{pp} \\
        \mathit{stkCreds} \\
        \mathit{stpools} \\
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
        \mathit{reserves}
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
          \mathit{dpstate} \\
        \end{array}
      \right)
    }
\end{equation}$$

**Ledger inference rules**