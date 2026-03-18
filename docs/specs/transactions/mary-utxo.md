# UTxO
## UTxO Transitions
We have added the following helper functions, which are used in defining the UTxO transition system, see Figure 1. These include:

- the function $\mathsf{getOut}$ builds a UTxO-type output out of a transaction output

- the function $\mathsf{outs}$ builds the MA UTxO entries from the outputs of a transaction

For calculating the minimum size of an output, we also need the function $\mathsf{valueSize}$ that computes the size of a $\mathsf{Value}$. It is defined as the size of the serialization of the $\mathsf{Value}$, in analogy to $\mathsf{txSize}$.


$$\begin{align*}
    & \mathsf{getOut} \in \mathsf{TxOut} \to \mathsf{UTxOOut} \\
    & \text{tx outputs transformed to UTxO outputs} \\
    & \mathsf{getOut} ~{txout}~= (\mathsf{getAddr}~\mathit{txout}, \mathsf{getValue}~\mathit{txout})
    \\[0.5em]
    & \mathsf{outs} \in \mathsf{TxBody} \to \mathsf{UTxO} \\
    & \text{tx outputs as UTxO} \\
    & \mathsf{outs} ~\mathit{txb} =
        \left\{
          (\mathsf{txid} ~ \mathit{txb}, \mathit{ix}) \mapsto \mathsf{getOut}~\mathit{txout} ~
          \middle|~
          \mathit{ix} \mapsto \mathit{txout} \in \mathsf{txouts}~txb
        \right\} \\
\end{align*}$$

**Functions on Tx Outputs**
**UTxO Helper Functions.**

Figure 2 defines additional calculations that are needed for the UTxO transition system with MA:

- $\mathsf{getCoin}$ sums all the Ada in a given output and returns it as a $\mathsf{Coin}$ value

- The $\mathsf{ubalance}$ function calculates the (aggregated by $\mathsf{PolicyID}$ and $\mathsf{AssetID}$) sum total of all the value in a given UTxO.

- The $\mathsf{valueSize}$ function estimates an upper bound on the size of a value as stored in the UTxO.

- As in Shelley, the $\mathsf{consumed}$ calculation is the sum of: i) the values of the UTxO entries consumed; ii) the reward address value consumed; and iii) the amount that is removed from the deposit pot as a result of the transaction collecting the deposit refunds that are due. There is an additional summand in this calculation, namely the value forged by a transaction. This calculation now returns a $\mathsf{Value}$.

- The $\mathsf{produced}$ calculation sums the same values as its Shelley counterpart. This calculation also returns a $\mathsf{Value}$.

**Produced and Consumed Calculations and Preservation of Value.** Note that the $\mathsf{consumed}$ and $\mathsf{produced}$ calculations both produce a $\mathsf{Value}$. This is because the outputs of a transaction, as well as UTxO outputs, are of the $\mathsf{Value}$ type. The administrative amounts (of the $\mathsf{Coin}$ type) are converted into MA values for these summations.

While the preservation of value is a single equality, it is really a comparison of token quantities aggregated by $\mathsf{AssetID}$ and by $\mathsf{PolicyID}$. In particular, ensuring that the produced amount equals the consumed amount also implies that the total quantity of Ada tokens is preserved.

**Forging and the Preservation of Value.** What does it mean to preserve the value of non-Ada tokens, since they are put in and taken out of circulation by the users themselves? This is expressed by including the $\mathsf{forge}$ value of the transaction in the preservation of value equation.

The *produced* side of the equation adds up, among other things, the values in the outputs that will be added to the ledger UTxO by the transaction. These outputs are where the forged value is \"put into of circulation\", i.e. how it ends up in the UTxO. Suppose a transaction $tx$ contains a single output $(a, pid \mapsto tkns)$. Suppose also that it does not have any inputs spending any UTxO outputs with policy ID $pid$.

A valid transaction $tx$ satisfies the preservation of value condition by adding the value $pid \mapsto tkns$ to the *consumed* side as well. To do this, the $tx$ declares that it is forging the tokens $pid \mapsto tkns$ via the $\mathsf{forge}$ field, i.e. $tx$ must have

$$pid \mapsto tkns\in\mathsf{forge}~tx$$

The forge field value is then added to the consumed side. This approach to balancing the *preservation of value* (POV) equation (Equation eqn:pov) extends to cases where the transaction might also be consuming some existing $pid$ tokens, or taking the out of circulation with negative quantities in the forge field.

The forge field value represents the change in total existing tokens of each given asset as a result of processing the transaction. It is always added to the *consumed* side of the POV equation because of this side, the signs of the quantities in the forge field match the signs of the change. That is, when tokens are added into the UTxO, their quantities are positive, and when they are taken out of circulation via the forge field, the signs are negative.

Note also that the UTXO rule only checks that the transaction is forging the amount it has declared using the forge field (and that no Ada is forged). The forging scripts themselves are not evaluated in this transition rule. That step is part of witnessing, i.e. the UTXOW rule, see below.


*Helper Functions* $$\begin{align*}
    & \mathsf{getCoin} \in \mathsf{UTxOOut} \to \mathsf{Coin} \\
    & \mathsf{getCoin}~{(\underline{\phantom{a}},~\mathit{out})} ~=~\mathsf{co}~(\mathit{out}~\mathsf{adaID}~\mathsf{adaToken}) \\
    \\[0.5em]
    & \mathsf{ubalance} \in \mathsf{UTxO} \to \mathsf{Value} \\
    & \mathsf{ubalance} ~ utxo = \sum_{\underline{\phantom{a}}\mapsto\mathit{u}\in~\mathit{utxo}}
    \mathsf{getValue}~\mathit{u} \\
    & \text{UTxO balance} \\
    \\[0.5em]
    & \mathsf{valueSize} \in \mathsf{Value} \to \N \\
    & \mathsf{valueSize}~\mathit{v} = k + k' * |\{ (\mathit{pid}, \mathit{aid}) : \mathit{v}~\mathit{pid}~\mathit{aid} \neq 0
      \land (\mathit{pid}, \mathit{aid}) \neq (\mathsf{adaID}, \mathsf{adaToken}) \}|
\end{align*}$$ *Produced and Consumed Calculations* $$\begin{align*}
    & \mathsf{consumed} \in \mathsf{PParams} \to \mathsf{UTxO} \to \mathsf{StakeCreds} \to \mathsf{Wdrl} \to \mathsf{TxBody} \to \mathsf{Value} \\
    & \mathsf{consumed}~pp~utxo~stkCreds{rewards}~{txb} = \\
    & ~~\mathsf{ubalance}~(\mathsf{txins}~txb \lhd \mathit{utxo}) + \\
    &~~  \mathsf{coinToValue}(\mathsf{wbalance}~(\mathsf{txwdrls}~{txb})~+~ \mathsf{keyRefunds}~pp~stkCreds{txb}) \\
    &~~+~\mathsf{forge}~\mathit{txb} \\
    & \text{\emph{-- value consumed}} \\
    \\[0.5em]
    & \mathsf{produced} \to \mathsf{PParams} \to \mathsf{StakePools} \to \mathsf{TxBody} \to \mathsf{Value} \\
    & \mathsf{produced}~\mathit{pp}~\mathit{stpools}~\mathit{txb} = \\
    &~~\mathsf{ubalance}~(\mathsf{outs}~{txb}) \\
    &~~+ \mathsf{coinToValue}(\mathsf{txfee}~txb + \mathsf{totalDeposits}~pp~stpools{(\mathsf{txcerts}~txb)})\\
    & \text{\emph{-- value produced}} \\
\end{align*}$$

**UTxO Calculations**
**The UTXO Transition Rule.** In Figure 3, we give the UTXO transition rule, updated for MA support. There are the following changes to the preconditions of this rule as compared to the original Shelley UTXO rule:

- The transaction is not forging any Ada

- All outputs of the transaction contain only non-negative quantities (this is the $\mathsf{Value}$-type version to the corresponding rule about non-negative $\mathsf{Coin}$ amounts in the Shelley ledger rules)

- In the preservation of value calculation (which looks the same as in Shelley), the value in the $\mathsf{forge}$ field is taken into account

Note that updating the $\mathsf{UTxO}$ with the inputs and the outputs of the transaction looks the same as in the Shelley rule, however, there is a type-level difference. Recall that the outputs of a transaction contain a $\mathsf{Value}$ term, rather than $\mathsf{Coin}$. Moreover, the $\mathsf{outs}$ map converts $\mathsf{TxOut}$ terms into $\mathsf{UTxOOut}$.


$$\begin{equation}
\label{eq:utxo-inductive-shelley}
    \inference[UTxO-inductive]
    { \mathit{txb}\mathrel{\mathop:}=\mathsf{txbody}~tx
      & \txttl txb \geq \mathit{slot}
      \\ \mathsf{txins}~txb \neq \emptyset
      & \mathsf{minfee}~pp~tx \leq \mathsf{txfee}~txb
      & \mathsf{txins}~txb \subseteq \dom \mathit{utxo}
      \\
      \mathsf{consumed}~pp~utxo~stkCreds{rewards}~{txb} = \mathsf{produced}~pp~stpools~{txb}
      \\
      ~
      \\
      {
        \begin{array}{r}
          \mathit{slot} \\
          \mathit{pp} \\
          \mathit{genDelegs} \\
        \end{array}
      }
      \vdash \mathit{ups} \xrightarrow[\mathsf{\hyperref[fig:rules:update]{up}}]{}{\mathsf{txup}~\mathit{tx}} \mathit{ups'}
      \\
      ~
      \\
      \mathsf{adaID}~\notin \dom~{\mathsf{forge}~tx} \\
      ~\\
      \forall txout \in \mathsf{txouts}~txb, ~ \mathsf{getValue}~txout  ~\geq ~ 0, \\~
      \mathsf{getCoin}~txout ~\geq ~\mathsf{valueSize}~(\mathsf{getValue}~txout) * \mathsf{minUTxOValue}~pp \\~
      \\
      \mathsf{txsize}~{tx}\leq\mathsf{maxTxSize}~\mathit{pp}
      \\
      ~
      \\
      \mathit{refunded} \mathrel{\mathop:}= \mathsf{keyRefunds}~pp~stkCreds{txb}
      \\
      \mathit{depositChange} \mathrel{\mathop:}=
        \mathsf{totalDeposits}~pp~stpools{(\mathsf{txcerts}~txb)} - \mathit{refunded}
    }
    {
      \begin{array}{r}
        \mathit{slot}\\
        \mathit{pp}\\
        \mathit{stkCreds}\\
        \mathit{stpools}\\
        \mathit{genDelegs}\\
      \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{utxo} \\
        \mathit{deposits} \\
        \mathit{fees} \\
        \mathit{ups}\\
      \end{array}
      \right)
      \xrightarrow[\mathsf{utxo}]{}{tx}
      \left(
      \begin{array}{r}
        \varUpdate{(\mathsf{txins}~txb \mathbin{\rlap{\lhd}/} \mathit{utxo}) \cup \mathsf{outs}~{txb}}  \\
        \mathsf{varUpdate}~\mathit{deposits} + \mathit{depositChange} \\
        \mathsf{varUpdate}~\mathit{fees} + \mathsf{txfee}~txb \\
        \mathsf{varUpdate}~ups'\\
      \end{array}
      \right)
    }
\end{equation}$$

**UTxO inference rules**
**Witnessing.**

We have changed the definition of the function $\mathsf{scriptsNeeded}$, see Figure 4. There is now an additional category of scripts that are needed for transaction validation, the forging scripts.

Note that there are no restrictions on the use of forging scripts. Their hashes may be used as credentials in UTxO entries, certificates, and withdrawals. Non-MPS type scripts can also be used for forging, e.g. MSig scripts.

Note also that UTxO entries containing MA tokens, just like Shelley UTxO entries, can be locked by a script. This script will add an additional set of restrictions to the use of MA tokens (additional to the forging script requirements, but enforced at spending time). This output-locking script can itself also be a forging script.


$$\begin{align*}
    & \hspace{-1cm}\mathsf{scriptsNeeded} \in \mathsf{UTxO} \to \mathsf{Tx} \to
      \mathbb{P}~\mathsf{ScriptHash}
    & \text{required script hashes} \\
    &  \hspace{-1cm}\mathsf{scriptsNeeded}~\mathit{utxo}~\mathit{tx} = \\
    & ~~\{ \mathsf{validatorHash}~a \mid i \mapsto (a, \underline{\phantom{a}}) \in \mathit{utxo},\\
    & ~~~~~i\in\mathsf{txinsScript}~{(\mathsf{txins~\mathit{txb}})}~{utxo}\} \\
    \cup & ~~\{ \mathsf{stakeCred_{r}}~\mathit{a} \mid a \in \dom (\mathsf{AddrRWDScr}
           \lhd \mathsf{txwdrls}~\mathit{txb}) \} \\
      \cup & ~~(\mathsf{AddrScr} \cap \mathsf{certWitsNeeded}~{txb}) \\
      \cup & ~~\dom~(\mathsf{forge}~{txb}) \\
      & \where \\
      & ~~~~~~~ \mathit{txb}~=~\mathsf{txbody}~tx \\
\end{align*}$$

**Scripts Needed**