# UTxO
The transition rules for unspent transaction outputs are presented in Figure 4. The states of the UTxO transition system, along with their types are defined in Figure 1:

- we define the protocol parameters as an abstract type, this type is made concrete in Section sec:update, where the update mechanism is discussed.

- The lovelace supply cap ($\mathsf{lovelaceCap}$) is treated as an abstract function in this specification. In the actual system this value equals $$45 \times 10^{15}$$

Functions on the types introduced in 4 are defined in 2. In particular, note that in function $\mathsf{minfee}$ we make use of the fact that the $\mathsf{Lovelace}$ type is an alias for the set of the integers numbers ($\mathbb{Z}$).

Rule eq:utxo-bootstrap, models the fact that the **reserves** of the system are set to: $$\mathsf{lovelaceCap} - \mathsf{balance}~utxo_0$$ The Lovelace amount $45 \times 10^{15}$ is the initial money supply in the system.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{tx} & \mathsf{Tx} & \text{transaction}\\
      %
      \mathit{txid} & \mathsf{TxId} & \text{transaction id}\\
      %
      ix & \mathsf{Ix} & \text{transaction index}\\
      %
      \mathit{addr} & \mathsf{Addr} & \text{address}\\
      %
      \mathit{pps} & \mathsf{PParams}& \text{protocol parameters}
    \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rlrlr}
      \ell & \mathsf{Lovelace}
      & n  & \mathbb{Z}
      & \text{currency value}
      \\
      \mathit{txin}
      & \mathsf{TxIn}
      & (\mathit{txid}, \mathit{ix})
      & \mathsf{TxId} \times \mathsf{Ix}
      & \text{transaction input}
      \\
      \mathit{txout}
      & \mathsf{TxOut}
      & (\mathit{addr}, c)
      & \mathsf{Addr} \times \mathsf{Lovelace}
      & \text{transaction output}
      \\
      \mathit{utxo}
      & \mathsf{UTxO}
      & m
      & \mathsf{TxIn} \mapsto \mathsf{TxOut}
      & \text{unspent tx outputs}
    \end{array}
\end{equation*}$$ *Abstract Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{txid}~ & \mathsf{Tx} \to \mathsf{TxId} & \text{compute transaction id}\\
      %
      \mathsf{txbody} & \mathsf{Tx} \to \mathbb{P}~\mathsf{TxIn} \times (\mathsf{Ix} \mapsto \mathsf{TxOut})
                                  & \text{transaction body}\\
      %
      \mathsf{a} & \mathsf{PParams}\to \mathbb{Z} & \text{minimum fee constant}\\
      %
      \mathsf{b} & \mathsf{PParams}\to \mathbb{Z} & \text{minimum fee factor}\\
      %
      \mathsf{txSize} & \mathsf{Tx} \to \mathbb{Z} & \text{abstract size of a transaction}\\
      %
      \mathsf{lovelaceCap} & \mathsf{Lovelace} & \text{lovelace supply cap}
    \end{array}
\end{equation*}$$ *Constraints* $$\begin{equation}
    \label{eq:txid-injective}
    \forall \mathit{tx_i}, \mathit{tx_j} \cdot
    \mathsf{txid}~\mathit{tx_i} = \mathsf{txid}~\mathit{tx_j} \Rightarrow \mathit{tx_i} = \mathit{tx_j}
\end{equation}$$

**Definitions used in the UTxO transition system**
$$\begin{align*}
    & \mathsf{txins} \in \mathsf{Tx} \to \mathbb{P}~\mathsf{TxIn}
    & \text{transaction inputs} \\
    & \mathsf{txins}~tx = \mathit{inputs} \where \mathsf{txbody}~tx = (\mathit{inputs}, ~\underline{\phantom{a}})
    \\[0.5em]
    & \mathsf{txouts} \in \mathsf{Tx} \to \mathsf{UTxO}
    & \text{transaction outputs as UTxO} \\
    & \mathsf{txouts} ~ \mathit{tx} =
      \left\{ (\mathsf{txid} ~ \mathit{tx}, \mathit{ix}) \mapsto \mathit{txout} ~
      \middle| \begin{array}{lcl}
                 (\_, \mathit{outputs}) & = & \mathsf{txbody}~tx \\
                 \mathit{ix} \mapsto \mathit{txout} & \in & \mathit{outputs}
               \end{array}
      \right\}
    \\[0.5em]
    & \mathsf{balance} \in \mathsf{UTxO} \to \mathbb{Z}
    & \text{UTxO balance} \\
    & \mathsf{balance} ~ utxo = \sum_{(~\underline{\phantom{a}} ~ \mapsto (\underline{\phantom{a}}, ~c)) \in \mathit{utxo}} c\\
   \\[0.5em]
   %
    & \mathsf{minfee} \in \mathsf{PParams}\to \mathsf{Tx} \to \mathbb{Z} & \text{minimum fee}\\
    & \mathsf{minfee}~\mathit{pps}~\mathit{tx} =
      \mathsf{a}~\mathit{pps} + \mathsf{b}~\mathit{pps} * \mathsf{txSize}~\mathit{tx}
\end{align*}$$

**Functions used in UTxO rules**
*UTxO environments* $$\begin{equation*}
    \mathsf{UTxOEnv} =
    \left(
      \begin{array}{rlr}
        \mathit{utxo_0} & \mathsf{UTxO} & \text{genesis UTxO}\\
        \mathit{pps} & \mathsf{PParams}& \text{protocol parameters map}
      \end{array}
    \right)
\end{equation*}$$

*UTxO states* $$\begin{equation*}
    \mathsf{UTxOState} =
    \left(
      \begin{array}{rlr}
        \mathit{utxo} & \mathsf{UTxO} & \text{unspent transaction outputs}\\
        \mathit{reserves} & \mathsf{Lovelace} & \text{system's reserves}
      \end{array}
    \right)
\end{equation*}$$

*UTxO transitions* $$\begin{equation*}
    \_ \vdash
    \mathit{\_} \xrightarrow[\mathsf{utxo}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{UTxOEnv} \times \mathsf{UTxOState} \times \mathsf{Tx} \times \mathsf{UTxOState})
\end{equation*}$$

**UTxO transition-system types**
$$\begin{equation}
\label{eq:utxo-bootstrap}
    \inference
    {
    }
    {
      {\left(\begin{array}{l}
        utxo_0\\
        pps
      \end{array}\right)}
      \vdash
      \xrightarrow[\mathsf{utxo}]{}{}
      \left(
        \begin{array}{l}
          \mathit{utxo_0}\\
          \mathsf{lovelaceCap} - \mathsf{balance}~utxo_0
        \end{array}
      \right)
    }
\end{equation}$$ $$\begin{equation}
\label{eq:utxo-inductive}
    \inference
    { \mathsf{txins}~tx \subseteq \dom \mathit{utxo}\\
      \mathit{fee} \mathrel{\mathop:}= \mathsf{balance}~(\mathsf{txins}~tx \lhd \mathit{utxo}) - \mathsf{balance}~(\mathsf{txouts}~tx)
      & \mathsf{minfee}~pps~tx \leq \mathit{fee}\\
      \mathsf{txins}~tx \neq \emptyset
      & \mathsf{txouts}~tx \neq \emptyset
      & \forall \underline{\phantom{a}} \mapsto (\underline{\phantom{a}}, c) \in \mathsf{txouts}~tx \cdot 0 < c
    }
    {
      {\left(\begin{array}{l}
        utxo_0\\
        pps
       \end{array}\right)}
      \vdash
      \left(
          \begin{array}{l}
            \mathit{utxo}\\
            \mathit{reserves}
          \end{array}
      \right)
      \xrightarrow[\mathsf{utxo}]{}{tx}
      \left(
        \begin{array}{l}
          (\mathsf{txins}~tx \mathbin{\rlap{\lhd}/} \mathit{utxo}) \cup \mathsf{txouts}~tx\\
          \mathit{reserves + \mathit{fee}}
        \end{array}
      \right)
    }
\end{equation}$$

**UTxO inference rules**
Rule eq:utxo-inductive specifies under which conditions a transaction can be applied to a set of unspent outputs, and how the set of unspent output changes with a transaction:

- Each input spent in the transaction must be in the set of unspent outputs.

- The minimum fee, which depends on the transaction and the protocol parameters, must be less or equal than the difference between the balance of the unspent outputs in a transaction (i.e. the total amount paid in a transaction) and the amount of spent inputs.

- The set of inputs must not be empty.

- All the transaction outputs must be positive. We do not allow $0$ value outputs to be consistent with the current implementation.

- If the above conditions hold, then the new state will not have the inputs spent in transaction $\mathit{tx}$ and it will have the new outputs in $\mathit{tx}$.

## Witnesses
The rules for witnesses are presented in Figure 8. In the initial rules note that $\mathit{utxoEnv}$ and $\mathit{utxoSt}$ are tuples, where $\mathit{utxoEnv} \in \mathsf{UTxOEnv}$ and $\mathit{utxoSt} \in \mathsf{UTxOState}$. The definitions used in Rule eq:utxo-witness-inductive are given in Figure 5. Note that Rule eq:utxo-witness-inductive uses the transition relation defined in Figure 4. The main reason for doing this is to define the rules incrementally, modeling different aspects in isolation to keep the rules as simple as possible. Also note that the $\xrightarrow[\mathsf{utxo}]{}{}$ relation could have been defined in terms of $\xrightarrow[\mathsf{utxow}]{}{}$ (thus composing the rules in a different order). The choice here is arbitrary.


*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{wits} & \mathsf{Tx} \to \mathbb{P}~(\mathsf{VKey} \times \mathsf{Sig})
      & \text{witnesses of a transaction}\\
      \mathsf{hash_{vkey}} & \mathsf{Addr} \mapsto \mathsf{KeyHash}
      & \text{hash of a verifying key in an address}\\
    \end{array}
\end{equation*}$$

**Definitions used in the UTxO transition system with witnesses**
$$\begin{align*}
    & \mathsf{addr}~{} \in \mathsf{UTxO} \to \mathsf{TxIn} \mapsto \mathsf{Addr} & \text{addresses of inputs}\\
    & \mathsf{addr}~utxo = \{ i \mapsto a \mid i \mapsto (a, \underline{\phantom{a}}) \in \mathit{utxo} \} \\
    \\[0.5em]
    & \mathsf{addr_h} \in \mathsf{UTxO} \to \mathsf{TxIn} \mapsto \mathsf{KeyHash} & \text{verifying key hashes}\\
    & \mathsf{addr_h}~utxo = \{ i \mapsto h \mid i \mapsto (a, \underline{\phantom{a}}) \in \mathit{utxo}
      \wedge a \mapsto h \in \mathsf{hash_{vkey}} \}
\end{align*}$$

**Functions used in rules witnesses**
*UTxO with witness transitions* $$\begin{equation*}
    \mathit{\_} \vdash
    \mathit{\_} \xrightarrow[\mathsf{utxow}]{}{\_} \mathit{\_}
    \subseteq \powerset
    (\mathsf{UTxOEnv} \times \mathsf{UTxOState} \times (\mathsf{Tx} \times \mathbb{P}~(\mathsf{VKey} \times \mathsf{Sig})) \times \mathsf{UTxOState})
\end{equation*}$$

**UTxO with witness transition-system types**
$$\begin{equation}
\label{eq:utxow-bootstrap}
    \inference
    {
      {\begin{array}{l}
         utxoEnv
      \end{array}}
      \vdash
      \xrightarrow[\mathsf{\hyperref[fig:rules:utxo]{utxo}}]{}{}
      \left(
        \mathit{utxoSt}
      \right)
    }
    {
      {\begin{array}{l}
         utxoEnv
      \end{array}}
      \vdash
      \xrightarrow[\mathsf{utxow}]{}{}
      \left(
        \mathit{utxoSt}
      \right)
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:utxo-witness-inductive}
    \inference
    { \mathit{utxoEnv}
      \vdash
      {\left(
        \begin{array}{l}
          \mathit{utxo}\\
          \mathit{reserves}
        \end{array}
      \right)}
      \xrightarrow[\mathsf{\hyperref[fig:rules:utxo]{utxo}}]{}{tx}
      {\left(
        \begin{array}{l}
          \mathit{utxo'}\\
          \mathit{reserves'}
        \end{array}
      \right)}
      & \mathit{maxTxSize} \mapsto \mathit{t} \in \mathit{pps} & \mathsf{txSize}~\mathit{tx} \leq t \\ ~ \\
      & \forall i \in \mathsf{txins}~tx \cdot \exists (\mathit{vk}, \sigma) \in \mathsf{wits}~\mathit{tx}
      \cdot
      \mathcal{V}^\sigma_{\mathit{vk}}~{\lbrack\!\lbrack \mathit{\mathsf{txbody}~tx} \rbrack\!\rbrack}
      \wedge  \mathsf{addr_h}~{utxo}~i = \mathrm{hash}~vk\\
    }
    {\mathit{utxoEnv} \vdash
      \left(
        \begin{array}{l}
          \mathit{utxo}\\
          \mathit{reserves}
        \end{array}
      \right)
      \xrightarrow[\mathsf{utxow}]{}{tx}
      \left(
        \begin{array}{l}
          \mathit{utxo'}\\
          \mathit{reserves'}
        \end{array}
      \right)
    }
\end{equation}$$

**UTxO with witnesses inference rules**
## Transaction sequences
9 models the application of a sequence of transactions. For the sake of concision we omit the types of this transition system, since they are the same as the ones of $\xrightarrow[\mathsf{utxow}]{}{}$.


$$\begin{equation}
\label{eq:utxows-bootstrap}
    \inference
    {
      {\begin{array}{l}
         utxoEnv
      \end{array}}
      \vdash
      \xrightarrow[\mathsf{\hyperref[fig:rules:utxo]{utxow}}]{}{}
      \left(
        \mathit{utxoSt}
      \right)
    }
    {
      {\begin{array}{l}
         utxoEnv
      \end{array}}
      \vdash
      \xrightarrow[\mathsf{utxows}]{}{}
      \left(
        \mathit{utxoSt}
      \right)
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:utxow-seq-base}
    \inference
    {}
    {\mathit{utxoEnv} \vdash \mathit{utxoSt} \xrightarrow[\mathsf{utxows}]{}{\epsilon} \mathit{utxoSt}}
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:utxow-seq-ind}
    \inference
    {
      \mathit{utxoEnv} \vdash \mathit{utxoSt} \xrightarrow[\mathsf{utxows}]{}{\Gamma} \mathit{utxoSt'}
      &
      \mathit{utxoEnv} \vdash \mathit{utxoSt'} \xrightarrow[\mathsf{\hyperref[fig:rules:utxow]{utxow}}]{}{\mathit{tx}} \mathit{utxoSt''}
    }
    {\mathit{utxoEnv} \vdash \mathit{utxoSt} \xrightarrow[\mathsf{utxows}]{}{\Gamma;\mathit{tx}} \mathit{utxoSt''}}
\end{equation}$$

**UTxO sequence rules**