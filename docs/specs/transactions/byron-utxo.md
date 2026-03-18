# UTxO
The transition rules for unspent transaction outputs are presented in Figure 4. The states of the UTxO transition system, along with their types are defined in Figure 1:

- we define the protocol parameters as an abstract type, this type is made concrete in Section sec:update, where the update mechanism is discussed.

- The lovelace supply cap ($\fun{lovelaceCap}$) is treated as an abstract function in this specification. In the actual system this value equals $$45 \times 10^{15}$$

Functions on the types introduced in 4 are defined in 2. In particular, note that in function $\fun{minfee}$ we make use of the fact that the $\Lovelace$ type is an alias for the set of the integers numbers ($\mathbb{Z}$).

Rule eq:utxo-bootstrap, models the fact that the **reserves** of the system are set to: $$\fun{lovelaceCap} - \balance{utxo_0}$$ The Lovelace amount $45 \times 10^{15}$ is the initial money supply in the system.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \var{tx} & \Tx & \text{transaction}\\
      %
      \var{txid} & \TxId & \text{transaction id}\\
      %
      ix & \Ix & \text{transaction index}\\
      %
      \var{addr} & \Addr & \text{address}\\
      %
      \var{pps} & \type{PParams}& \text{protocol parameters}
    \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rlrlr}
      \ell & \Lovelace
      & n  & \mathbb{Z}
      & \text{currency value}
      \\
      \var{txin}
      & \TxIn
      & (\var{txid}, \var{ix})
      & \TxId \times \Ix
      & \text{transaction input}
      \\
      \var{txout}
      & \type{TxOut}
      & (\var{addr}, c)
      & \Addr \times \Lovelace
      & \text{transaction output}
      \\
      \var{utxo}
      & \UTxO
      & m
      & \TxIn \mapsto \TxOut
      & \text{unspent tx outputs}
    \end{array}
\end{equation*}$$ *Abstract Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \txid{} & \Tx \to \TxId & \text{compute transaction id}\\
      %
      \fun{txbody} & \Tx \to \powerset{\TxIn} \times (\Ix \mapsto \TxOut)
                                  & \text{transaction body}\\
      %
      \fun{a} & \type{PParams}\to \mathbb{Z} & \text{minimum fee constant}\\
      %
      \fun{b} & \type{PParams}\to \mathbb{Z} & \text{minimum fee factor}\\
      %
      \fun{txSize} & \Tx \to \mathbb{Z} & \text{abstract size of a transaction}\\
      %
      \fun{lovelaceCap} & \Lovelace & \text{lovelace supply cap}
    \end{array}
\end{equation*}$$ *Constraints* $$\begin{equation}
    \label{eq:txid-injective}
    \forall \var{tx_i}, \var{tx_j} \cdot
    \txid{\var{tx_i}} = \txid{\var{tx_j}} \Rightarrow \var{tx_i} = \var{tx_j}
\end{equation}$$

**Definitions used in the UTxO transition system**
$$\begin{align*}
    & \fun{txins} \in \Tx \to \powerset{\TxIn}
    & \text{transaction inputs} \\
    & \txins{tx} = \var{inputs} \where \txbody{tx} = (\var{inputs}, ~\wcard)
    \nextdef
    & \fun{txouts} \in \Tx \to \UTxO
    & \text{transaction outputs as UTxO} \\
    & \fun{txouts} ~ \var{tx} =
      \left\{ (\fun{txid} ~ \var{tx}, \var{ix}) \mapsto \var{txout} ~
      \middle| \begin{array}{lcl}
                 (\_, \var{outputs}) & = & \txbody{tx} \\
                 \var{ix} \mapsto \var{txout} & \in & \var{outputs}
               \end{array}
      \right\}
    \nextdef
    & \fun{balance} \in \UTxO \to \mathbb{Z}
    & \text{UTxO balance} \\
    & \fun{balance} ~ utxo = \sum_{(~\wcard ~ \mapsto (\wcard, ~c)) \in \var{utxo}} c\\
   \nextdef
   %
    & \fun{minfee} \in \type{PParams}\to \Tx \to \mathbb{Z} & \text{minimum fee}\\
    & \fun{minfee}~\var{pps}~\var{tx} =
      \fun{a}~\var{pps} + \fun{b}~\var{pps} * \fun{txSize}~\var{tx}
\end{align*}$$

**Functions used in UTxO rules**
*UTxO environments* $$\begin{equation*}
    \UTxOEnv =
    \left(
      \begin{array}{rlr}
        \var{utxo_0} & \UTxO & \text{genesis UTxO}\\
        \var{pps} & \type{PParams}& \text{protocol parameters map}
      \end{array}
    \right)
\end{equation*}$$

*UTxO states* $$\begin{equation*}
    \UTxOState =
    \left(
      \begin{array}{rlr}
        \var{utxo} & \UTxO & \text{unspent transaction outputs}\\
        \var{reserves} & \Lovelace & \text{system's reserves}
      \end{array}
    \right)
\end{equation*}$$

*UTxO transitions* $$\begin{equation*}
    \_ \vdash
    \var{\_} \trans{utxo}{\_} \var{\_}
    \subseteq \powerset (\UTxOEnv \times \UTxOState \times \Tx \times \UTxOState)
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
      \trans{utxo}{}
      \left(
        \begin{array}{l}
          \var{utxo_0}\\
          \fun{lovelaceCap} - \balance{utxo_0}
        \end{array}
      \right)
    }
\end{equation}$$ $$\begin{equation}
\label{eq:utxo-inductive}
    \inference
    { \txins{tx} \subseteq \dom \var{utxo}\\
      \var{fee} \leteq \balance{(\txins{tx} \restrictdom \var{utxo})} - \balance{(\txouts{tx})}
      & \minfee{pps}{tx} \leq \var{fee}\\
      \txins{tx} \neq \emptyset
      & \txouts{tx} \neq \emptyset
      & \forall \wcard \mapsto (\wcard, c) \in \txouts{tx} \cdot 0 < c
    }
    {
      {\left(\begin{array}{l}
        utxo_0\\
        pps
       \end{array}\right)}
      \vdash
      \left(
          \begin{array}{l}
            \var{utxo}\\
            \var{reserves}
          \end{array}
      \right)
      \trans{utxo}{tx}
      \left(
        \begin{array}{l}
          (\txins{tx} \subtractdom \var{utxo}) \cup \txouts{tx}\\
          \var{reserves + \var{fee}}
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

- If the above conditions hold, then the new state will not have the inputs spent in transaction $\var{tx}$ and it will have the new outputs in $\var{tx}$.

## Witnesses
The rules for witnesses are presented in Figure 8. In the initial rules note that $\var{utxoEnv}$ and $\var{utxoSt}$ are tuples, where $\var{utxoEnv} \in \UTxOEnv$ and $\var{utxoSt} \in \UTxOState$. The definitions used in Rule eq:utxo-witness-inductive are given in Figure 5. Note that Rule eq:utxo-witness-inductive uses the transition relation defined in Figure 4. The main reason for doing this is to define the rules incrementally, modeling different aspects in isolation to keep the rules as simple as possible. Also note that the $\trans{utxo}{}$ relation could have been defined in terms of $\trans{utxow}{}$ (thus composing the rules in a different order). The choice here is arbitrary.


*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \fun{wits} & \Tx \to \powerset{(\VKey \times \Sig)}
      & \text{witnesses of a transaction}\\
      \fun{hash_{vkey}} & \Addr \mapsto \KeyHash
      & \text{hash of a verifying key in an address}\\
    \end{array}
\end{equation*}$$

**Definitions used in the UTxO transition system with witnesses**
$$\begin{align*}
    & \addr{}{} \in \UTxO \to \TxIn \mapsto \Addr & \text{addresses of inputs}\\
    & \addr{utxo} = \{ i \mapsto a \mid i \mapsto (a, \wcard) \in \var{utxo} \} \\
    \nextdef
    & \fun{addr_h} \in \UTxO \to \TxIn \mapsto \KeyHash & \text{verifying key hashes}\\
    & \fun{addr_h}~utxo = \{ i \mapsto h \mid i \mapsto (a, \wcard) \in \var{utxo}
      \wedge a \mapsto h \in \fun{hash_{vkey}} \}
\end{align*}$$

**Functions used in rules witnesses**
*UTxO with witness transitions* $$\begin{equation*}
    \var{\_} \vdash
    \var{\_} \trans{utxow}{\_} \var{\_}
    \subseteq \powerset
    (\UTxOEnv \times \UTxOState \times (\Tx \times \powerset{(\VKey \times \Sig)}) \times \UTxOState)
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
      \trans{\hyperref[fig:rules:utxo]{utxo}}{}
      \left(
        \var{utxoSt}
      \right)
    }
    {
      {\begin{array}{l}
         utxoEnv
      \end{array}}
      \vdash
      \trans{utxow}{}
      \left(
        \var{utxoSt}
      \right)
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:utxo-witness-inductive}
    \inference
    { \var{utxoEnv}
      \vdash
      {\left(
        \begin{array}{l}
          \var{utxo}\\
          \var{reserves}
        \end{array}
      \right)}
      \trans{\hyperref[fig:rules:utxo]{utxo}}{tx}
      {\left(
        \begin{array}{l}
          \var{utxo'}\\
          \var{reserves'}
        \end{array}
      \right)}
      & \var{maxTxSize} \mapsto \var{t} \in \var{pps} & \fun{txSize}~\var{tx} \leq t \\ ~ \\
      & \forall i \in \txins{tx} \cdot \exists (\var{vk}, \sigma) \in \wits{\var{tx}}
      \cdot
      \mathcal{V}^\sigma_{\var{vk}}~{\serialised{\txbody{tx}}}
      \wedge  \fun{addr_h}~{utxo}~i = \hash{vk}\\
    }
    {\var{utxoEnv} \vdash
      \left(
        \begin{array}{l}
          \var{utxo}\\
          \var{reserves}
        \end{array}
      \right)
      \trans{utxow}{tx}
      \left(
        \begin{array}{l}
          \var{utxo'}\\
          \var{reserves'}
        \end{array}
      \right)
    }
\end{equation}$$

**UTxO with witnesses inference rules**
## Transaction sequences
9 models the application of a sequence of transactions. For the sake of concision we omit the types of this transition system, since they are the same as the ones of $\trans{utxow}{}$.


$$\begin{equation}
\label{eq:utxows-bootstrap}
    \inference
    {
      {\begin{array}{l}
         utxoEnv
      \end{array}}
      \vdash
      \trans{\hyperref[fig:rules:utxo]{utxow}}{}
      \left(
        \var{utxoSt}
      \right)
    }
    {
      {\begin{array}{l}
         utxoEnv
      \end{array}}
      \vdash
      \trans{utxows}{}
      \left(
        \var{utxoSt}
      \right)
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:utxow-seq-base}
    \inference
    {}
    {\var{utxoEnv} \vdash \var{utxoSt} \trans{utxows}{\epsilon} \var{utxoSt}}
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:utxow-seq-ind}
    \inference
    {
      \var{utxoEnv} \vdash \var{utxoSt} \trans{utxows}{\Gamma} \var{utxoSt'}
      &
      \var{utxoEnv} \vdash \var{utxoSt'} \trans{\hyperref[fig:rules:utxow]{utxow}}{\var{tx}} \var{utxoSt''}
    }
    {\var{utxoEnv} \vdash \var{utxoSt} \trans{utxows}{\Gamma;\var{tx}} \var{utxoSt''}}
\end{equation}$$

**UTxO sequence rules**