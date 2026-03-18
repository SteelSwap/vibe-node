# UTxO
## UTxO Transitions
We have added several functions having to to with transaction and UTxO inputs and outputs, which are used in defining the UTxO transition system. These are given in Figure 1. These include

- the function $\mathsf{txinputs_{vf}}$ returns only those transaction inputs that were selected to pay transaction fees (we call these \"fee-marked\" inputs)

- the predicate function $\mathsf{feesOK}$ checks whether the transaction is paying the necessary fees, and correctly. That is, it checks that

  - the fee-marked inputs are strictly of the type that are key or multisignature script locked, not Plutus script

  - all the fee-marked inputs contain strictly Ada and no other tokens

  - the fee-marked inputs are enough to cover the fee amount stated in the transaction

  - minimum fee the transaction is obligated to pay (this includes the script-running fee) is less than the fee amount the transaction states it is paying

- the function $\mathsf{getOut}$ selects from a transaction output the data that will be stored in the UTxO, i.e. $\mathsf{UTxOOut}$ without the slot number

- the function $\mathsf{outs}$ throws away the $\mathsf{HasDV}$ tag from a transaction output. It also now adds the slot number of the block in which transaction is included to the outputs. This slot number is available in the environment of the rule that calls the $\mathsf{outs}$ function, and gets passed to it.

- the function $\mathsf{txins}$ that returns UTxO output reference part of both script and non-script transaction inputs.

Because the $\mathsf{Tx}$ type is a sum of $\mathsf{ShelleyTx}$ and $\mathsf{GoguenTx}$, and there was a way of computing an ID from a Shelley transaction, there is potential for confusion how the ID of a transaction is computed. Here, $\mathsf{TxId}$ is always computed from values of type $\mathsf{Tx}$, never from $\mathsf{ShelleyTx}$ or $\mathsf{GoguenTx}$.

Note that when submitting a transaction, the wallet is responsible for determining the total price of the validation of all the Plutus scripts in a transaction by running the script itself to see how much resources it takes and doing the fee calculation using the cost model in protocol parameters. It is then also responsible for adding enough inputs to the transaction to cover the fees required. In the implementation of the wallet this is handled automatically by default, so this generates no overhead for users.


$$\begin{align*}
    & \mathsf{txinputs_{vf}} \in \mathsf{TxBody} \to \mathbb{P}~\mathsf{TxId} \times \mathsf{Ix} \\
    & \text{tx VK and MSig inputs used for fees} \\
    & \mathsf{txinputs_{vf}} ~txb~= \\
    &~~\{ (txid,ix)~\vert~(txid,ix,\mathit{isfee}) \in
    \mathsf{txinputs} ~txb,~
     \mathit{isfee}\in\mathsf{Yes}\}
    \\[0.5em]
    & \mathsf{feesOK} \in \N \to \mathsf{PParams} \to \mathsf{GoguenTx} \to \mathsf{UTxO} \to \mathsf{Bool}  \\
    & \text{check if fee-marked inputs are Ada-only and enough to cover fees} \\
    & \mathsf{feesOK} ~n~\mathit{pp}~tx~utxo~= \\
    &~~\mathsf{range}~(\mathsf{txinputs_{vf}}~{txb} \lhd \mathit{utxo}) \subseteq \mathsf{TxOutND} ~ \\
    &~~\wedge~ \mathsf{ubalance}~(\mathsf{txinputs_{vf}}~{txb} \lhd \mathit{utxo}) \in \mathsf{Coin} \\
    &~~      \wedge~ \mathsf{ubalance}~(\mathsf{txinputs_{vf}}~{txb} \lhd \mathit{utxo}) \geq \mathsf{txfee}~txb ~ \\
    &~~      \wedge~ \minfee~n~{pp}~{tx} \leq \mathsf{txfee}~txb \\
    &~~      \where \\
    & ~~~~~~~ \mathit{txb}~=~\mathsf{txbody}~tx
    \\[0.5em]
    & \mathsf{getOut} \in \mathsf{TxOut} \to (\mathsf{Addr} \times \mathsf{Value}) \uplus (\mathsf{Addr} \times \mathsf{Value} \times \mathsf{DataHash})  \\
    & \text{tx outputs transformed to UTxO outputs} \\
    & \mathsf{getOut} ~{txout}~= \begin{cases}
         \mathit{txout}  & \text{if~} \mathit{txout} \in \mathsf{TxOutND} \\
              (\mathsf{getAddr}~\mathit{txout}, \mathsf{getValue}~\mathit{txout},
              \mathsf{getDataHash}~\mathit{txout}) & \text{otherwise}
            \end{cases}
    \\[0.5em]
    & \mathsf{outs} \in \mathsf{Slot} \to \mathsf{TxBody} \to \mathsf{UTxO} \\
    & \text{tx outputs as UTxO} \\
    & \mathsf{outs} ~ \mathit{slot}~\mathit{txb} =
        \left\{
          (\mathsf{txid} ~ \mathit{txb}, \mathit{ix}) \mapsto (\mathsf{getOut}~\mathit{txout},\mathit{slot}) ~
          \middle|~
          \mathit{ix} \mapsto \mathit{txout} \in \mathsf{txouts}~txb
        \right\} \\
    \\[0.5em]
    & \mathsf{txins} \in \mathsf{TxBody} \to \mathbb{P}~\mathsf{TxId} \times \mathsf{Ix} \\
    & \text{transaction inputs} \\
    & \mathsf{txins} ~\mathit{txb} = \{(txid,ix) \mid ((txid,ix),\underline{\phantom{a}})\in\mathsf{txinputs} ~txb\} \\
\end{align*}$$

**Functions on Tx Inputs and Outputs**
Figure 2 defines functions needed for the UTxO transition system. The changes due to Plutus integration are as follows:

- $\mathsf{getCoin}$ adds up all the Ada in a given output and returns it as a $\mathsf{Coin}$ value

- $\mathsf{utxoAda}$ returns the set of all the outputs in a UTxO with only Ada tokens (the other tokens are discarded). This is used in the stake distribution calculation at the epoch boundary

- $\mathsf{txscrfee}$ calculates the fee a transaction must pay for script execution based on the amount of $\mathsf{ExUnits}$ it has budgeted for running the scripts it carries, and the prices (as indicated in the current protocol parameters) for each of the components of $\mathsf{ExUnits}$. Recall that a transaction pays a flat fee for running a Plutus script, plus some amount per unit of memory and per reduction step. Note that this value, like the non-script portion of the transaction fee, is calculated in $\mathsf{Coin}$, as fees can only be paid in Ada.

- For Goguen transactions, we have also changed the minimim fee calculation, $\mathsf{minfee}$, to include the script fees the transaction is obligated to pay to run its scripts.

- The $\mathsf{ubalance}$ function calculates the (aggregated by currency ID and Token) sum total of all the value in a given UTxO.

- The $\mathsf{consumed}$ calculation for the preservation of value remains the same. It is still the sum of the value in the UTxO entries consumed, the reward address value consumed, the value consumed from the deposit pot (due to the transaction collecting deposit refunds), and the value forged by a transaction.

  Note that forged value is part of the *consumed* calculation because it is value that will appear in the outputs \"out of thin air\". All outputs in a transaction are put in the UTxO once it is processed, and therefore are part of the *produced* calculation. That same forged amount must be added to the *consumed* calculation in order to balance the preservation of value equation.

- The $\mathsf{produced}$ calculation sums the value in the outputs the transaction adds to the UTxO, the fee a transaction pays to the fee pot (this consists of both the standard size-based transaction fee and the fee for processing all the scripts inside it), and the deposits it makes to the deposit pot. This calculation now also takes the current slot number as an argument, which is needed to construct the correct UTxO outputs.

- For calculating the minimum size of an output, we need the function $\mathsf{scaledValueSize}$ that computes the size of a $\mathsf{Value}$. It is defined as the size of the serialization of the $\mathsf{Value}$, in analogy to $\mathsf{txSize}$.

## Value Operations and Partial Order.
Some of the UTxO update and precondition functions now operate on the $\mathsf{Value}$ type instead of $\mathsf{Coin}$ (sometimes on a combination of $\mathsf{Value}$ and $\mathsf{Coin}$). To make this precise, we must define basic operations on $\mathsf{Value}$, which include, most notably, addition and $\leq$ comparison.

Because the absence of a token in a $\mathsf{Value}$ has the same semantics as the token being present with an amount of $0$, we regard two elements of type $\mathsf{Value}$ as the same if they only differ by some tokens with amount $0$. This means that we can equivalently regard values as total maps that map all except a finite amount of its inputs to $0$.

This way, when adding two partial maps, $m_1$ and $m_2$, $m_1 + m_2$ is defined by $(m_1 + m_2)~\mathit{pid}~\mathit{aid} := (m_1~\mathit{pid}~\mathit{aid}) + (m_2~\mathit{pid}~\mathit{aid})$.

Similarly, if we compare two maps, we compare them as follows:

$$m_1 \leq m_2 \Leftrightarrow \forall~\mathit{pid}~\mathit{aid}, m_1~\mathit{pid}~\mathit{aid} \leq m_2~\mathit{pid}~\mathit{aid}$$


*Helper Functions* $$\begin{align*}
    & \mathsf{getCoin} \in \mathsf{UTxOOut} \to \mathsf{Coin} \\
    & \mathsf{getCoin}~{\mathit{out}} ~=~\sum_{\mathsf{adaID} \mapsto tkns \in \mathsf{getValue}~out}
       (\sum_{q \in \range~{tkns}} \mathsf{co}~q) \\
    & \text{sum total of amount of Ada in an output}
    \\[0.5em]
    & \mathsf{utxoAda} \in \mathsf{UTxO} \to \mathbb{P}~(\mathsf{Addr} \times \mathsf{Coin}) \\
    & \mathsf{utxoAda}~{\mathit{utxo}} ~=~\{~(\mathsf{getAddr}~\mathit{out},~\mathsf{getCoin}~{out})
    ~\vert~ \mathit{out} \in \range~\mathit{utxo} ~\} \\
    & \text{returns the addresses in the UTxO paired with the amount of Ada in them} \\
\end{align*}$$ *Main Calculations* $$\begin{align*}
    & \mathsf{txscrfee} \in \N \to \mathsf{Prices} \to \mathsf{ExUnits} \to \mathsf{Coin} \\
    & \mathsf{txscrfee}~n~ (\mathit{pr_{init}, pr_{mem}, pr_{steps}})~ (\mathit{mem, steps})
    = \mathit{pr_{init}}*n + \mathit{pr_{mem}}*\mathit{mem} + \mathit{pr_{steps}}*\mathit{steps} \\
    & \text{calculates the script fee a transaction must pay} \\
    \\[0.5em]
    &\mathsf{minfee} \in \N \to \mathsf{PParams} \to \mathsf{GoguenTx} \to \mathsf{Coin} \\
    & \text{minimum fee}\\
    &\mathsf{minfee}  ~n~\mathit{pp}~\mathit{tx} = \\
    &~~(\mathsf{a}~\mathit{pp}) \cdot \mathsf{txSize}~\mathit{tx} + (\mathsf{b}~\mathit{pp}) +
    \mathsf{txscrfee}~n~(\mathsf{prices}~{pp})~(\mathsf{txexunits}~(\mathsf{txbody}~{tx}))
    \\[0.5em]
    & \mathsf{ubalance} \in \mathsf{UTxO} \to \mathsf{Value} \\
    & \mathsf{ubalance} ~ utxo = \sum_{\underline{\phantom{a}}\mapsto\mathit{out}\in~\mathit{utxo}}
    \mathsf{getValue}~\mathit{out} \\
    & \text{UTxO balance} \\
    \\[0.5em]
    & \mathsf{consumed} \in \mathsf{PParams} \to \mathsf{UTxO} \to \mathsf{StakeCreds} \to \mathsf{Wdrl} \to \mathsf{TxBody} \to \mathsf{Value} \\
    & \consumed~{pp}~{utxo}~{stkCreds}~{txb} = \\
    & ~~\mathsf{ubalance}~(\mathsf{txins}~txb \lhd \mathit{utxo}) + \\
    &~~  \mathsf{coinToValue}(\mathsf{wbalance}~(\mathsf{txwdrls}~{txb})~\\
        &~~+~ \mathsf{keyRefunds}~pp~stkCreds{txb}) +
        ~\mathsf{forge}~\mathit{txb} \\
    & \text{value consumed} \\
    \\[0.5em]
    & \mathsf{produced} \in \mathsf{Slot} \to \mathsf{PParams} \to \mathsf{StakePools} \to \mathsf{TxBody} \to \mathsf{Value} \\
    & \mathsf{produced}~\mathit{slot}~\mathit{pp}~\mathit{stpools}~\mathit{txb} = \\
    &~~\mathsf{ubalance}~(\mathsf{outs}~slot~{txb})  + \mathsf{coinToValue}(\mathsf{txfee}~txb \\
    &~~+ \mathsf{deposits}~pp~stpools~{(\mathsf{txcerts}~txb)})\\
    & \text{value produced} \\
    \\[0.5em]
    & \mathsf{scaledValueSize} \in \mathsf{Value} \to \N \\
    & \mathsf{scaledValueSize}~\mathit{val} = \mathsf{valueSize}~\mathit{val} / \mathsf{valueSize}~(\mathsf{coinToValue}~1) \\
\end{align*}$$

**Functions used in UTxO rules**
## Putting Together Plutus Scripts and Their Inputs
In Figure 3 we give the helper functions needed to retrieve all the data relevant to validation of Plutus scripts. This includes,

- $\mathsf{indexof}$ finds the index of a given certificate, value, input, or withdrawal in the list, finite map, or set of things of the corresponding type. This function assumes there is some ordering on each of these structures. This function is abstract because it assumes there is some ordering rather than giving it explicitly. The specific ordering of a set or a finite map could be implementation-dependent. A list ordering should be unambiguous.

  ::: note
  $\mathsf{indexof}$ should only be called on arguments of the correct type? or it cannot be applied at all to a predicate of the wrong type, so there is no way the predicate in the subset definition should not be satisfied in case of wrong type. Does this work?
  :::

- $\mathsf{indexedScripts}$ creates a finite map wherein all the scripts of a transaction (that it carries as a set) are indexed by their hashes, calculated by this function

- $\mathsf{indexedDats}$ is a similar function that indexes all the datum objects carried by the transaction with their hashes

- $\mathsf{findRdmr}$ gets the redeemer carried by a Goguen transaction which corresponds to the given current item. Recall that items that may require Plutus scripts to be run include certificates, withdrawals, forges, and outputs. To find the redeemer corresponding to that item, we search the indexed redeemer structure for the redeemer with the right key. The key we look for is the pair of the type of item it is for (indicated by the tag), and the index of said item in the list/set/map of these kinds of items in the transaction.


*Abstract functions* $$\begin{align*}
    &\mathsf{indexof} \in \mathsf{DCert} \to \mathsf{DCert}^{*} \to \mathsf{Ix}\\
    &\mathsf{indexof} \in \mathsf{AddrRWD} \to \mathsf{Wdrl} \to \mathsf{Ix}\\
    &\mathsf{indexof} \in (\mathsf{TxId} \times \mathsf{Ix}) \to \mathbb{P}~\mathsf{TxIn} \to \mathsf{Ix}\\
    &\mathsf{indexof} \in \mathsf{CurrencyId} \to \mathsf{Value} \to \mathsf{Ix}\\
    & \text{get the index of an item in the an ordered representation} \\
    \\[0.5em]
\end{align*}$$ *Helper functions* $$\begin{align*}
    &\mathsf{indexedScripts} \in \mathsf{GoguenTx} \to (\mathsf{PolicyID} \mapsto \mathsf{Script}) \\
    & \text{make a finite map of hash-indexed scripts} \\
    &\mathsf{indexedScripts}~{tx} ~=~ \{ h \mapsto s ~\vert~ \mathsf{hashScript}~{s}~=~h,
     s\in~\mathsf{txscripts}~(\mathsf{txwits}~{tx})\}
    \\[0.5em]
    &\mathsf{indexedDats} \in \mathsf{GoguenTx} \to (\mathsf{DataHash} \mapsto \mathsf{Data})\\
    & \text{make a finite map of hash-indexed datum objects} \\
    &\mathsf{indexedDats}~{tx} ~=~ \{ h \mapsto d ~\vert~ \mathsf{hashData}~{d}~=~h,
     d\in~\mathsf{txdats}~(\mathsf{txwits}~{tx})\}
    &\\[0.5em]
    &\mathsf{findRdmr} \in \mathsf{GoguenTx} \to \mathsf{CurItem} \to \mathbb{P}~\mathsf{Data}\\
    & \text{get empty set or redeemer corresponding to index} \\
    & \mathsf{findRdmr}~{tx}~\mathit{it} ~=~ \{~ r ~\vert~ \\
    &~~(\mathsf{certTag},~\mathit{it}~\in~\mathsf{DCert}~\wedge~ \mathsf{indexof}~\mathit{it}~(\mathsf{txcerts}~{txb})) \mapsto ~r \in \mathsf{txrdmrs}~{txw} \\
    &~~\vee~ (\mathsf{wdrlTag},~\mathit{it}\mapsto c~\in~\mathsf{Wdrl}~\wedge~\mathsf{indexof}~\mathit{w}~(\mathsf{txwdrls}~{txb}))
      \mapsto ~r \in \mathsf{txrdmrs}~{txw} \\
    &~~\vee~(\mathsf{forgeTag},~\mathit{it}\mapsto \mathit{tkns}~\in~\mathsf{Value}~\wedge~\mathsf{indexof}~\mathit{cid}~(\mathsf{forge}~{txb}))  \mapsto ~r
      \in \mathsf{txrdmrs}~{txw} \\
    &~~\vee~(\mathsf{inputTag},~\mathit{(it,\_)}~\in~\mathsf{TxIn}~\wedge~\mathsf{indexof}~\mathit{(txid,ix)}~(\mathsf{txinputs}~{txb})) \mapsto ~r
      \in \mathsf{txrdmrs}~{txw} \} \\
      & ~~\where \\
      & ~~~~~~~ \mathit{txb}~=~\mathsf{txbody}~tx \\
      & ~~~~~~~ \mathit{txw}~=~\mathsf{txwits}~{tx}
\end{align*}$$

**Combining Script Validators and their Inputs**
**Matching Scripts and Inputs.** In Figures 4 and 5, we give the four functions that gather all data inside a transaction and in the UTxO that is needed for script validation.

- $\mathsf{allCertScrts}$ returns the set of all the validators for the key deregistration certificates, together with the data needed for validation

- $\mathsf{allWDRLSScrts}$ returns the set of all the validators locking the script-address reward addresses together with the data needed for validation

- $\mathsf{forgedScrts}$ returns the set of all the validators for forging new tokens together with the data needed for validation

- $\mathsf{allInsScrts}$ returns the set of all the validators locking the script-address UTxO's together with the data needed for validation

**What scripts get redeemers?** Here we assume it is ok for every kind of Plutus script to have a redeemer. In fact, the transaction is obligated to provide a redeemer for every Plutus script. There is the possibility, in the future, to optimize supplying redeemers by allowing transactions to omit unit-value redeemers, filling the $\mathsf{Data}$-type unit in by default. Whether this will be done is contingent on real-world observations of the use of redeemers.

Note that there are no \"checks\" done inside the functions matching scripts with their inputs. If there are missing validators or inputs, or incorrect hashes, wrong type of script, this is caught during the application of the UTXOW rule (before these functions are ever applied). There are several pieces of data from different sources involved in building these sets:

- the hash of the validator script, which is either the address (withdrawal address or an output address in the UTxO), the certificate credential, or the currency ID of forged tokens

- the corresponding full validator, which is looked up (by hash value) in the finite map constructed by $\mathsf{indexedScripts}$

- the datum objects, which are also looked up by hash in the map constructed by $\mathsf{indexedDats}$. The hashes used to look up the datum objects are found in the outputs of the UTxO, indexed by the $(txid,ix)$ in the transaction output spending the UTxO entry

- the redeemers, which are in the indexed redeemer structure carried by the transaction. These are looked up by current item using the $\mathsf{findRdmr}$ function. Note that the redeemer lookup function returns a set of redeemers, but this set should contain exactly one redeemer. There is exactly one redeemer associated with each $\mathsf{CurItem}$ in the indexed redeemer structure.

- the validation data, built using the UTxO, the transaction itself, and the current item being validated

Recall that $\mathsf{valContext}$ constructs the validation context (kept abstract in this spec).

The function $\mathsf{mkPLCLst}$ returns a list made of the union of the sets of pairs (of a script and the input list, except the execution budget) which were constructed by the functions specific to the script uses ($\mathsf{allCertScrts}$, $\mathsf{allWDRLSScrts}$, $\mathsf{forgedScrts}$, $\mathsf{allInsScrts}$).


$$\begin{align*}
    & \mathsf{allCertScrts} \in \mathsf{PParams} \to \mathsf{UTxO} \to \mathsf{GoguenTx} \to \mathbb{P}~(\mathsf{ScriptPlutus} \times \mathsf{Data}^{*} \times \mathsf{CostMod}) \\
    & \text{check that all certificate witnessing scripts in a tx validate} \\
    & \mathsf{allCertScrts}~\mathit{pp}~{utxo}~{tx}~=~ \\
    & ~~\{ (\mathit{script_v}, (r;
    \mathsf{valContext}~\mathit{utxo}~\mathit{tx}~\mathit{cert}; \epsilon),~cm) ~\vert \\
    & ~~r \in \mathsf{findRdmr}~{tx}~\mathit{cert}, \\
    & ~~\mathit{cert} \in (\mathsf{DCertDeRegKey}\cap\mathsf{txcerts}~\mathsf{txbody}~tx), \\
    &~~\mathsf{regCred}~\mathit{cert}\mapsto \mathit{script_v}\in \mathsf{indexedScripts}~{tx}, \\
    &~~(\mathsf{language}~{script_v} \mapsto cm)\in(\mathsf{costmdls}~{pp}) \\
    & ~~\mathit{script_v} \in \mathsf{ScriptPlutus}
     \}
    %
    \\[0.5em]
    & \mathsf{allWDRLSScrts} \in \mathsf{PParams} \to \mathsf{UTxO} \to \mathsf{GoguenTx} \to \mathbb{P}~(\mathsf{ScriptPlutus}\times\mathsf{Data}^{*} \times \mathsf{CostMod}) \\
    & \text{check that all reward withdrawal locking scripts in a tx validate} \\
    & \mathsf{allWDRLSScrts}~\mathit{pp}~{utxo}~{tx}~=~ \\
    & ~~\{ (\mathit{script_v}, (r; \mathsf{valContext}~\mathit{utxo}~\mathit{tx}~
      (a\mapsto c); \epsilon),~cm) ~\vert \\
    &~~ r\in \mathsf{findRdmr}~{tx}~\mathit{a}, \\
    & ~~a \mapsto c \in\mathsf{txwdrls}~(\mathsf{txbody}~tx), \\
    & ~~\mathit{a}\mapsto \mathit{script_v}\in \mathsf{indexedScripts}~{tx}, \\
    &~~(\mathsf{language}~{script_v} \mapsto cm)\in(\mathsf{costmdls}~{pp}) \\
    & ~~ \mathit{script_v} \in \mathsf{ScriptPlutus} \}
    \\[0.5em]
    %
    & \mathsf{forgedScrts} \in \mathsf{PParams} \to \mathsf{UTxO} \to \mathsf{GoguenTx} \to \mathbb{P}~(\mathsf{ScriptPlutus}\times\mathsf{Data}^{*} \times \mathsf{CostMod}) \\
    & \text{check that all forging scripts in a tx validate} \\
    & \mathsf{forgedScrts}~\mathit{pp}~{utxo}~{tx}~=~\\
    & ~~\{ (\mathit{script_v}, (r;
    \mathsf{valContext}~\mathit{utxo}~\mathit{tx}~\mathit{cid}; \epsilon),~cm) ~\vert \\
    & ~~r \in \mathsf{findRdmr}~{tx}~\mathit{cid}, \\
    & ~~\mathit{cid}\mapsto ~ \mathit{tkns} \in \mathsf{forge}~(\mathsf{txbody}~tx), \\
    &~~\mathit{cid}\mapsto \mathit{script_v}\in \mathsf{indexedScripts}~{tx} \\
    &~~(\mathsf{language}~{script_v} \mapsto cm)\in(\mathsf{costmdls}~{pp}) \\
    & ~~ \mathit{script_v} \in \mathsf{ScriptPlutus} \}
    %
\end{align*}$$

**Scripts and their Arguments**
$$\begin{align*}
    & \mathsf{allInsScrts} \in \mathsf{PParams} \to \mathsf{UTxO} \to \mathsf{GoguenTx} \to \mathbb{P}~(\mathsf{ScriptPlutus}\times\mathsf{Data}^{*} \times \mathsf{CostMod}) \\
    & \text{check that all UTxO entry locking scripts in a tx validate} \\
    & \mathsf{allInsScrts}~\mathit{pp}~{utxo}~{tx}~=~ \{ (\mathit{script_v}, (\mathit{d};\mathit{r}; \\
    & ~~ \mathsf{valContext}~\mathit{utxo}~\mathit{tx}~
      (txid,ix,\mathit{hash_r})),~cm) ~\vert \\
    & ~~(txid,ix, \_) \in \mathsf{txinputs}~(\mathsf{txbody}~tx), \\
    & ~~\mathit{r} \in \mathsf{findRdmr}~{tx}~\mathit{(txid,ix)}, \\
    & ~~\mathit{(txid,ix)} \mapsto ((a,v),h_d, \_) \in \mathit{utxo}, \\
    & ~~\mathit{h_d}\mapsto \mathit{d} \in \mathsf{indexedDats}~{tx}, \\
    & ~~(\mathsf{validatorHash}~{a})\mapsto \mathit{script_v}\in \mathsf{indexedScripts}~{tx} \\
    &~~(\mathsf{language}~{script_v} \mapsto cm)\in(\mathsf{costmdls}~{pp}) \}
    \\[0.5em]
    & \mathsf{mkPLCLst} \in \mathsf{PParams} \to \mathsf{GoguenTx} \to \mathsf{UTxO} \to \seqof{(\mathsf{ScriptPlutus} \times \mathsf{Data}^{*} \times \mathsf{CostMod})} \\
    & \text{a list of all Plutus validators and corresponding input data} \\
    & \mathsf{mkPLCLst} ~\mathit{pp}~\mathit{tx}~ \mathit{utxo} ~=~
    \mathsf{toList}~(\mathsf{allCertScrts}~{utxo}~{tx} \cup \mathsf{allWDRLSScrts}~{utxo}~{tx} \\
    & ~~ \cup \mathsf{allInsScrts}~{utxo}~{tx} ~~ \cup \mathsf{forgedScrts}~{utxo}~{tx}) \\
\end{align*}$$

**Scripts and their Arguments**
## Two Phase Script Validation
Two phase Plutus script validation is necessary to ensure users pay for the computational resources script validation uses. Native script execution costs are expected to be much smaller than Plutus scripts, and can be assesed and limited by the ledger rules directly. Hence these scripts do not require two-phase validation. They are already in use in the Shelley spec with a single validation phase.

The first phase two-phase validation approach performs every aspect of transaction validation except running the scripts. The second phase is running the scripts. We use four transition systems for this validation approach, each with different responsibilities. We give the details of each below, but to summarize, when a transction is processed, it is done by rules in the transition systems in the following order (each transition calls on the one below it in its rules):

- : Verifies all the necessary witnessing info is present, including VK witnesses, scripts, and all the script input data. It also performs key witness checks and runs multisig scripts. It then applies state changes computed by the UTXO transition

- : Verifies a transaction satisfies all the accounting requirements (including the general accounting property, correct fee payment, etc.), applies state changes computed by the UTXOS transition

- : Performs the appropriate UTxO state changes, deciding based on the value of the $\mathsf{IsValidating}$ tag, which it checks using the SVAL transition

- : Runs the scripts, verifying that the $\mathsf{IsValidating}$ tag is applied correctly

Recall that, unlike native multisignature scripts, Plutus scripts are opaque to the ledger. Recall also that a transaction states a $\mathsf{ExUnits}$ \"budget\" to cover running all Plutus scripts it is carrying. There is no way to check that this budget is enough, except running the scripts. To avoid over-spending, we run them sequentially, stopping whenever one does not validate, and charging the transaction the fees. From the point of view of the ledger, there is no difference between a script runnig out of $\mathsf{ExUnits}$ during validation, or not validating. If a transaction contains an invalid script, the only change to the ledger as a result of applying this transaction is the fees. Other parts of the transaction cannot be processed correctly in this case.

Two phase validation requires a new transition system (see Figure 6) to sequentially run scripts and keep track of the execution units being spent as part of its state ($\mathit{remExU}$). The signal here is a sequence of pairs of a validator script and the corresponding input data.

Note that there is one state variable in the SVAL transition system. The reason for this is that in the second, script-running validation phase, we separate the UTxO state update from sequentially running scripts. This transition system is strictly for running the scripts, and a transition of this type will be used by another rule to perform the correct UTxO update.

Running scripts sequentially to verify that they all validate in the allotted $\mathsf{ExUnits}$ budget only requires the amount of remaining $\mathsf{ExUnits}$ to be included in the state, and nothing else. In the environment, we need the protocol parameters and the transaction being validated. All other data needed to run the scripts comes from the signal.


*Validation environment* $$\begin{equation*}
    \mathsf{ValEnv} =
    \left(
      \begin{array}{rlr}
        \mathit{pp} & \mathsf{PParams} & \text{protocol parameters}\\
        \mathit{tx} & \mathsf{GoguenTx} & \text{transaction being processed} \\
      \end{array}
    \right)
\end{equation*}$$ *Validation state* $$\begin{equation*}
    \mathsf{ValState} =
    \left(
      \begin{array}{rlr}
        \mathit{remExU} & \mathsf{ExUnits} & \text{exunits remaining to spend on validation} \\
      \end{array}
    \right)
\end{equation*}$$ *Script transitions* $$\begin{equation*}
    \_ \vdash
    \mathit{\_} \xrightarrow[\mathsf{sval}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{ValEnv} \times \mathsf{ValState} \times \seqof{(\mathsf{ScriptPlutus}\times\mathsf{Data}^{*}\times\mathsf{CostMod})} \times \mathsf{ValState})
\end{equation*}$$

**UTxO script validation types**
The rules for the second-phase script validation SVAL are given in Figure 7. Again, there is no UTxO state update done in this rule. Its function is essentially verifying that the validation tag ($\mathsf{txvaltag}$) is applied correctly by the creater of the block by running all the scripts.

Note that following the Shelley ledger spec approach, every function we define and use in the preconditions or calculations in the rules is necessarily total. This way, all errors (validation failures) we encounter always come from rule applications, i.e. a precondition of a rule is not met. We mention this here because the SVAL rule looks as if it could be simply a function. However, we want the incorrect application of the validation tag to be an error, so it must be an error that comes form an unmet precondition of a rule.

There are three transition rules. The first rule, $\mathsf{Scripts\mbox{-}Val}$, applies when

- there are no scripts left to validate in the signal list (i.e. this is the base case of induction when all the scripts have validated), there could be $\mathsf{ExUnits}$ left over

- the validation tag is applied correctly (it is $\mathsf{Yes}$)

The $\mathsf{Scripts\mbox{-}Stop}$ rule applies when

- The currenct script-input pair being validated does not validate (because the transaction ran out of $\mathsf{ExUnits}$ or any other reasons)

- The validation tag is correct ($\mathsf{Nope}$ in this case)

These first two rules require no state change. The $\mathsf{Scripts\mbox{-}Ind}$ rule applies when

- the current script being validated has validated

- there is a non-negative fee which remains to pay for validating the rest of the scripts in the list

- transition rules apply for rest of the list (without the currenct script)

The only state change in this rule is of the variable $\mathit{remExU}$. It is decreased by subtracting the cost of the execution of the current script from its current value. This is the variable we use to keep track of the remaining funds for script execution. If the transaction is overpaying ($\mathsf{txscrfee}~{tx}$ is too big), the whole fee is still taken.

It is always in the interest of the slot leader to have the new block validate, containing only valid transactions. This motivates the slot leader to:

- correctly apply of the $\mathsf{IsValidating}$ tag,

- include transactions that validate in every way *except possibly 2nd step script validation failure*

- exclude any transactions that are invalid in some way *other than 2nd step script validation failure*

We want to throw away all the blocks which have transactions with these tags applied incorrectly. One of the reasons for having the correct validation tag added by the slot leader to a transaction is that re-applying blocks would not require repeat execution of scripts in the transactions inside a block. In fact, when replaying blocks, all the witnessing info can be thrown away. We also rely on correct use of tags in other rules (at this time, only in the rules in Figure fig:rules:ledger).

**Non-integral calculations inside the Plutus interpreter.** If there will be some in the future (from the Actus contracts implemented using the Marlowe interpreter, for e.g.), they should be done the same way they are done in the Shelley ledger. This is a matter of deterministic script validation outcomes. Inconsistent rounding could result in different validation outcomes running the same script on the same arguments. For how this is done in the ledger calculations, see  [@non_int].


$$\begin{equation}
    \inference[Scripts-Val]
    {
    \mathsf{txvaltag}~\mathit{tx} \in \mathsf{Yes}  &
    \mathit{remExU}~\geq~0
    }
    {
    \begin{array}{l}
      \mathit{pp}\\
      \mathit{tx}\\
    \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{remExU}\\
      \end{array}
      \right)
      \xrightarrow[\mathsf{sval}]{}{\epsilon}
      \left(
      \begin{array}{r}
        \mathit{remExU}\\
      \end{array}
      \right) \\
    }
\end{equation}$$ $$\begin{equation}
    \inference[Scripts-Stop]
    { \\~\\
    (\mathit{isVal},\mathit{remExU'})~:=~ \llbracket sc \rrbracket_
    {cm,\mathit{remExU}} dt \\
    (sc, dt, cm) := s
    \\
    ~
    \\
    \mathsf{txvaltag}~\mathit{tx} \in \mathsf{Nope} &
    (\mathit{remExU'}~<~0 ~ \lor ~ \mathit{isVal}\in \mathsf{Nope})
    }
    {
    \begin{array}{l}
      \mathit{pp}\\
      \mathit{tx}\\
    \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{remExU}\\
      \end{array}
      \right)
      \xrightarrow[\mathsf{sval}]{}{\Gamma;s}
      \left(
      \begin{array}{r}
        \mathit{remExU}\\
      \end{array}
      \right)
    }
\end{equation}$$ $$\begin{equation}
    \inference[Scripts-Ind]
    {
    {
    \begin{array}{l}
      \mathit{pp}\\
      \mathit{tx}\\
    \end{array}
    }
      \vdash
      \left(
      {
      \begin{array}{r}
        \mathit{remExU}\\
      \end{array}
      }
      \right)
      \xrightarrow[\mathsf{sval}]{}{\Gamma}
      \left(
      {
      \begin{array}{r}
        \mathit{remExU'}\\
      \end{array}
      }
      \right) \\
    (\mathit{isVal},\mathit{remExU''})~:=~ \llbracket sc \rrbracket
    _{cm,\mathit{remExU'}} dt \\
    (sc, dt, cm) := s & \mathit{remExU''}~\geq~0
    }
    {
    \begin{array}{l}
      \mathit{pp}\\
      \mathit{tx}\\
    \end{array}
      \vdash
      \left(
      \begin{array}{r}
        \mathit{remExU}\\
      \end{array}
      \right)
      \xrightarrow[\mathsf{sval}]{}{\Gamma;s}
      \left(
      \begin{array}{r}
        \mathsf{varUpdate}~remExU''\\
      \end{array}
      \right)
    }
\end{equation}$$

**Script validation rules**
## Updating the UTxO State
We have defined a separate transition system, UTXOS, to represent the two distinct UTxO state changes, one resulting from all scripts in a transaction validating, the other - from at least one failing to validate. Its transition types are all the same as for the for the UTXO transition, see Figure 12.


*State transitions* $$\begin{equation*}
    \_ \vdash
    \mathit{\_} \xrightarrow[\mathsf{utxo, utxos}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{UTxOEnv} \times \mathsf{UTxOState} \times \mathsf{GoguenTx} \times \mathsf{UTxOState})
\end{equation*}$$

**UTxO and UTxO script state update types**
There are two rules corresponding to the two possible state changes of the UTxO state in the UTXOS transition system, see Figure 9.

In both cases, the SVAL transition is called upon to verify that the $\mathsf{IsValidating}$ tag has been applied correctly. The function $\mathsf{mkPLCLst}$ is used to build the signal list $\mathit{sLst}$ for the SVAL transition.

The first rule applies when the validation tag is $\mathsf{Yes}$. In this case, the states of the UTxO, fee and deposit pots, and updates are updated exactly as in the current Shelley ledger spec.

The second rule applies when the validation tag is $\mathsf{Nope}$. In this case, the UTxO state changes as follows:

- All the UTxO entries corresponding to the transaction inputs selected for covering script fees are removed

- The sum total of the value of the marked UTxO entries is added to the fee pot


$$\begin{equation}
    \inference[Scripts-Yes]
    {
    \mathit{txb}\mathrel{\mathop:}=\mathsf{txbody}~tx &
    \mathsf{txvaltag}~\mathit{tx} \in \mathsf{Yes}
    \\
    ~
    \\
    \mathit{sLst} := \mathsf{mkPLCLst}~\mathit{pp}~\mathit{tx}~\mathit{utxo}
    \\~\\
    {
      \left(
        \begin{array}{r}
          \mathit{pp} \\
          \mathit{tx} \\
        \end{array}
      \right)
    }
      \vdash
        \mathit{\mathsf{txexunits}~{tx}}
      \xrightarrow[\mathsf{sval}]{}{sLst}\mathit{remExU}
      \\~\\
    {
      \left(
        \begin{array}{r}
          \mathit{slot} \\
          \mathit{pp} \\
          \mathit{genDelegs} \\
        \end{array}
      \right)
    }
    \vdash \mathit{ups} \xrightarrow[\mathsf{\hyperref[fig:rules:update]{up}}]{}{\mathsf{txup}~\mathit{tx}} \mathit{ups'}
    \\~\\
    \mathit{refunded} \mathrel{\mathop:}= \mathsf{keyRefunds}~pp~stkCreds~{txb}
    \\
    \mathit{depositChange} \mathrel{\mathop:}=
      (\deposits{pp}~{stpools}~{(\mathsf{txcerts}~txb)}) - \mathit{refunded}
    }
    {
    \begin{array}{l}
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
        \mathit{ups} \\
      \end{array}
      \right)
      \xrightarrow[\mathsf{utxos}]{}{tx}
      \left(
      \begin{array}{r}
        \varUpdate{\mathit{(\mathsf{txins}~txb \mathbin{\rlap{\lhd}/} \mathit{utxo}) \cup \mathsf{outs}~slot~{txb}}}  \\
        \mathsf{varUpdate}~\mathit{deposits} + \mathit{depositChange} \\
        \mathsf{varUpdate}~\mathit{fees} + \mathsf{txfee}~txb \\
        \mathsf{varUpdate}~\mathit{ups'} \\
      \end{array}
      \right) \\
    }
\end{equation}$$ $$\begin{equation}
    \inference[Scripts-No]
    {
    \mathit{txb}\mathrel{\mathop:}=\mathsf{txbody}~tx &
    \mathsf{txvaltag}~\mathit{tx} \in \mathsf{Nope}
    \\
    ~
    \\
    \mathit{sLst} := \mathsf{mkPLCLst}~\mathit{pp}~\mathit{tx}~\mathit{utxo}
    \\~\\
    {
      \left(
        \begin{array}{r}
          \mathit{pp} \\
          \mathit{tx} \\
        \end{array}
      \right)
    }
      \vdash
        \mathit{\mathsf{txexunits}~{tx}}
      \xrightarrow[\mathsf{sval}]{}{sLst}\mathit{remExU}
    }
    {
    \begin{array}{l}
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
        \mathit{ups} \\
      \end{array}
      \right)
      \xrightarrow[\mathsf{utxos}]{}{tx}
      \left(
      \begin{array}{r}
        \varUpdate{\mathit{\mathsf{txinputs_{vf}}~{txb} \mathbin{\rlap{\lhd}/} \mathit{utxo}}}  \\
        \mathit{deposits} \\
        \varUpdate{\mathit{fees} + \mathsf{ubalance}~(\mathsf{txinputs_{vf}}~{txb}\lhd \mathit{utxo})} \\
        \mathit{ups} \\
      \end{array}
      \right)
    }
\end{equation}$$

**State update rules**
In Figure 10, we present the $\mathsf{UTxO-inductive}$ transition rule for the UTXO transition type. Note that the signal for this transition is now specifically of type $\mathsf{GoguenTx}$, it does not work with Shelley transactions (see explanation about transforming one type into the other below). This rule It has the following preconditions (the relevant ones remain from the original Shelley spec):

- The transaction is being processed within its validity interval

- The transaction has at least one input

- All inputs in a transaction correspond to UTxO entries

- The general accounting property holds

- The transaction is paying fees correctly

- The transaction is not forging any Ada

- All outputs of the transaction contain only non-negative quantities

- The transaction size does not exceed maximum

- The execution units budget a transaction gives does not exceed the max allowed units

- The UTXOS state transition is valid

The resulting state transition is defined entirely by the application of the UTXOS rule.


$$\begin{equation}
\label{eq:utxo-inductive-shelley}
    \inference[UTxO-inductive]
    {
      \mathit{txb}\mathrel{\mathop:}=\mathsf{txbody}~tx &
      \mathit{txw}\mathrel{\mathop:}=\mathsf{txwits}~{tx} \\
      \mathsf{txfst}~txb \leq \mathit{slot}
      & \mathsf{txttl}~txb \geq \mathit{slot}
      \\
      \mathsf{txins}~txb \neq \emptyset
      & \mathsf{txins}~txb \subseteq \dom \mathit{utxo}
      \\
      \mathsf{consumed}~pp~utxo~stkCreds{rewards}~{txb} = \produced{slot}~{pp}~{stpools}~{txb}
      \\~\\
      \mathsf{feesOK}~(\vert~ \mathsf{txscripts}~{tx} \cap \mathsf{ScriptPlutus} ~\vert) ~pp~tx~utxo \\
      \\
      ~
      \\
      \mathsf{adaID}~\notin \dom~{\mathsf{forge}~tx} \\
      \forall txout \in \mathsf{txouts}~txb, ~ \mathsf{getValue}~txout  ~\geq ~ 0 \\~
      \forall txout \in \mathsf{txouts}~txb, ~ \mathsf{getCoin}~txout ~\geq \\
      \mathsf{scaledValueSize}~(\mathsf{getValue}~txout) * \mathsf{minUTxOValue}~pp \\~
      \\
      \mathsf{txsize}~{tx}\leq\mathsf{maxTxSize}~\mathit{pp} \\
      \mathsf{txexunits}~{txb} \leq \mathsf{maxTxExUnits}~{pp}
      \\
      ~
      \\
      {
        \begin{array}{c}
          \mathit{slot}\\
          \mathit{pp}\\
          \mathit{stkCreds}\\
          \mathit{stpools}\\
          \mathit{genDelegs}\\
        \end{array}
      }
      \vdash
      {
        \left(
          \begin{array}{r}
            \mathit{utxo} \\
            \mathit{deposits} \\
            \mathit{fees} \\
            \mathit{ups}\\
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{utxos}]{}{\mathit{tx}}
      {
        \left(
          \begin{array}{r}
            \mathit{utxo'} \\
            \mathit{deposits'} \\
            \mathit{fees'} \\
            \mathit{ups'}\\
          \end{array}
        \right)
      }
    }
    {
      \begin{array}{l}
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
        \mathsf{varUpdate}~\mathit{utxo'}  \\
        \mathsf{varUpdate}~\mathit{deposits'} \\
        \mathsf{varUpdate}~\mathit{fees'} \\
        \mathsf{varUpdate}~\mathit{ups'}\\
      \end{array}
      \right)
    }
\end{equation}$$

**UTxO inference rules**
## Witnessing
Plutus script validation is not part of witnessing because of the introduction of two-phase validation, as this type of validation may result in two different ways of updating the UTxO (fee payment only, or a full update). Native script validation still is, and we need to pick only the native scripts to validate as part of witnessing. We have changed the definition of the function $\mathsf{scriptsNeeded}$, see Figure 11. It now includes both MSig and Plutus scripts, and scripts used for every validation purpose (forging, outputs, certificates, withdrawals), see Figure 11.


$$\begin{align*}
      & \hspace{-1cm}\mathsf{scriptsNeeded} \in \mathsf{UTxO} \to \mathsf{GoguenTx} \to
        \mathsf{PolicyID}\\
      & \hspace{-1cm}\text{items that need script validation and corresponding script hashes} \\
      &  \hspace{-1cm}\mathsf{scriptsNeeded}~\mathit{utxo}~\mathit{tx} = \\
      & ~~\{ \mathsf{validatorHash}~(\mathsf{getAddr}~{txout}) \mid i \mapsto \mathit{txout} \in \mathit{utxo},\\
      & ~~~~~i\in\mathsf{txinsScript}~{(\mathsf{txinputs}~\mathit{txb})}~{utxo}\} \\
      \cup & ~~\{ \mathit{a} \mid a \mapsto c \in \mathsf{txwdrls}~\mathit{txb}),
         a\in \mathsf{AddrRWDScr} \} \\
        \cup & ~~\mathsf{PolicyID} \cap \mathsf{certWitsNeeded}~{txb} \\
        \cup & ~~\{ cid \mid cid \mapsto \mathit{tkns}~\in~\mathsf{forge}~{txb} \} \\
      & \where \\
      & ~~~~~~~ \mathit{txb}~=~\mathsf{txbody}~tx \\
\end{align*}$$

**Functions used in witness rule**
Recall here that in the Goguen era, we must be able to validate both Shelley type and Goguen type transactions. To do this, we transform the transaction being processed into a Goguen transaction (if it's already a Goguen one, it stays the same). Goguen transactions have more data, so it we use defaul values to fill it in. The only time we need the original Shelley transaction is to check the signatures on the hash of the the orignal transaction body, see Figure 13. In addition to the Shelley UTXOW preconditions that still apply, we have made the following changes and additions to the preconditions:

- All the multisig scripts the transaction is carrying validate

- The transaction has exactly the scripts required for witnessing and no additional ones (this includes all languages of scripts, for all purposes)

- The transaction is carrying a redeemer for every item that needs validation by a Plutus script

- The only certificates that are allowed to have scripts as witnesses are delegation deregistration certificates

- The transaction has a datum for every Plutus script output it is spending

- The transaction has a datum for every Plutus script output that is marked with the $\mathsf{Yes}$ tag for $\mathsf{HasDV}$

- The hash of the subset of protocol parameters in the transaction body is equal to the hash of the same subset of protocol parameters currently on the ledger

- The hash of the indexed redeemer structure attached to the transaction is the same as the $\mathsf{rdmrsHash}~{tx}$ (the hash value contained in the signed body of the transaction)

If these conditions are all satisfied, the resulting UTxO state change is fully determined by the UTXO transition (the application of which is also part of the conditions).


*State transitions* $$\begin{equation*}
    \_ \vdash
    \mathit{\_} \xrightarrow[\mathsf{utxow}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{UTxOEnv} \times \mathsf{UTxOState} \times \mathsf{Tx} \times \mathsf{UTxOState})
\end{equation*}$$

**UTxO with witnesses state update types**
$$\begin{equation}
    \label{eq:utxo-witness-inductive-goguen}
    \inference[UTxO-witG]
    {
      \mathit{tx}~\mathrel{\mathop:}=~\mathsf{toGoguenTx}~{tx}_o \\~\\
      \mathit{txb}\mathrel{\mathop:}=\mathsf{txbody}~tx &
      \mathit{txw}\mathrel{\mathop:}=\mathsf{txwits}~{tx} &
      \mathit{tx}~\in~\mathsf{GoguenTx} \\
      (utxo, \underline{\phantom{a}}, \underline{\phantom{a}}, \underline{\phantom{a}}) \mathrel{\mathop:}= \mathit{utxoSt} \\
      \mathit{witsKeyHashes} \mathrel{\mathop:}= \{\mathsf{hashKey}~\mathit{vk} \vert \mathit{vk} \in
      \dom (\mathsf{txwitsVKey}~txw) \}\\~\\
      \forall \mathit{validator} \in \mathsf{txscripts}~{txw} \cap \mathsf{ScriptMSig},\\
      \mathsf{runMSigScript}~\mathit{validator}~\mathit{tx}\\~\\
      \mathsf{scriptsNeeded}~\mathit{utxo}~\mathit{tx} ~=~ \dom (\mathsf{indexedScripts}~{tx}) \\
      \forall h \in ~\mathsf{scriptsNeeded}~\mathit{utxo}~\mathit{tx}, ~h\mapsto s~\in~\mathsf{indexedScripts}~{tx},\\
       s \in \mathsf{ScriptPlutus}~\Leftrightarrow ~\mathsf{findRdmr}~{tx}~{c}\neq \emptyset
      \\~\\
      \forall \mathit{cert}~\in~\mathsf{txcerts}~{txb}, \mathsf{regCred}~{cert}\in \mathsf{PolicyID} \Leftrightarrow
      \mathit{cert} \in~ \mathsf{DCertDeRegKey} \\~\\
      \forall~\mathit{txin}\in\mathsf{txinputs}~{txb},
      \mathit{txin} \mapsto \mathit{(\underline{\phantom{a}},\underline{\phantom{a}},h_d)} \in \mathit{utxo},
      \mathit{h_d} ~\in \mathsf{dom}(\mathsf{indexedDats}~{tx})
      \\
      ~
      \\
      \forall~ix \mapsto (a,v,d_h,\mathsf{Yes}) ~\in~\mathsf{txouts}~{txb}, \\
       \mathit{d_h}\in \mathsf{dom}~ (\mathsf{indexedDats}~{tx})
      \\
      ~
      \\
      \mathsf{ppHash}~{txb}~=~\mathsf{hashLanguagePP}~\mathit{pp}~(\mathsf{cmlangs}~(\mathsf{txscripts}~\mathit{txw})) \\~\\
      \mathsf{txrdmrs}~\mathit{txw} ~=~ \emptyset \Leftrightarrow \mathsf{rdmrsHash}~{txb}~=~\mathsf{Nothing} \\
      \mathsf{txrdmrs}~\mathit{txw} ~\neq~ \emptyset \Leftrightarrow
      \mathsf{hash}~(\mathsf{txrdmrs}~\mathit{txw})~ =~  \mathsf{rdmrsHash}~{txb} \\
      \\~\\
      \forall \mathit{vk} \mapsto \sigma \in \mathsf{txwitsVKey}~txw,
      \mathcal{V}_{\mathit{vk}}{\lbrack\!\lbrack \mathit{tx_{o}} \rbrack\!\rbrack}_{\sigma} \\
      \mathsf{witsVKeyNeeded}~{utxo}~{tx}~{genDelegs} \subseteq \mathit{witsKeyHashes}
      \\~\\
      genSig \mathrel{\mathop:}=
      \left\{
        \mathsf{hashKey}~gkey \vert gkey \in\mathrm{dom}~genDelegs
      \right\}
      \cap
      \mathit{witsKeyHashes}
      \\
      \left\{
        c\in\mathsf{txcerts}~txb~\cap\mathsf{DCertMir}
      \right\} \neq\emptyset \implies \vert genSig\vert \geq \mathsf{Quorum} \wedge
      \mathsf{d}~\mathit{pp} > 0
      \\~\\
      \mathit{mdh}\mathrel{\mathop:}=\mathsf{txMDhash}~\mathit{txb}
      &
      \mathit{md}\mathrel{\mathop:}=\mathsf{txMD}~\mathit{tx}
      \\
      (\mathit{mdh}=\mathsf{Nothing} \land \mathit{md}=\mathsf{Nothing})
      \lor
      (\mathit{mdh}=\mathsf{hashMD}~\mathit{md})
      \\~\\
      {
        \begin{array}{r}
          \mathit{slot}\\
          \mathit{pp}\\
          \mathit{stkCreds}\\
          \mathit{stpools}\\
          \mathit{genDelegs}\\
        \end{array}
      }
      \vdash \mathit{utxoSt} \xrightarrow[\mathsf{\hyperref[fig:rules:utxo-shelley]{utxo}}]{}{tx}
      \mathit{utxoSt'}\\
    }
    {
      \begin{array}{r}
        \mathit{slot}\\
        \mathit{pp}\\
        \mathit{stkCreds}\\
        \mathit{stpools}\\
        \mathit{genDelegs}\\
      \end{array}
      \vdash \mathit{utxoSt} \xrightarrow[\mathsf{utxow}]{}{{tx}_o} \mathsf{varUpdate}~\mathit{utxoSt'}
    }
\end{equation}$$

**UTxO with witnesses inference rules for GoguenTx**