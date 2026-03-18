# Introduction

A model of a UTxO ledger utilizing an abstract authorization mechanism is described in [@utxo_scripts]. The authorization mechanism involves a scripting language, which we leave unspecified and refer to as $\mathsf{Script}$. This model is an extension of the model described in [@chimeric], which includes account based transactions in addition to UTxO transactions. We do not include account transactions in this specification.

The model described in [@utxo_scripts] was further generalized in [@multi_currency] to support using multiple currencies on the same ledger.

In what follows, we describe the multi-currency UTxO ledger model using mostly set theory, we state validation rules that determine whether a transaction is valid for a given ledger state and finally we define the state transformation that a valid transaction has on the state.

# Scripts

We use an abstract scripting language $\mathsf{Script}$ to generalize authorization mechanisms such as pay-to-pubkey-hash. In pay-to-pubkey-hash, an address is the hash of a public key. UTxO held by that address are authorized by providing the public key and a digital signature. Similarly, in the generalized script model, an address is the hash of a verification script and the redeemer script plays the role of the digital signature. UTxO held by script addresses are authorized by providing both the validator and redeemer script. Analogously to checking a digital signature, the authorization succeeds if the redeemer scripts provides evidence to that causes the validator script to return true. This is made precise in 1.


*Scripts* $$\begin{equation*}
\begin{array}{rlrl}
  \mathit{validator}
& \mathsf{Script}
& [\![ validator ]\!]
& \mathsf{LedgerState} \mapsto \mathsf{R} \mapsto \mathsf{Bool}
\\
  \mathit{redeemer}
& \mathsf{Script}
& [\![ redeemer ]\!]
& \mathsf{LedgerState} \mapsto \mathsf{R}
\end{array}
\end{equation*}$$      

     \
\
*Script Operations* $$\begin{align*}
& \mathsf{scriptValidate} \in
  \mathsf{LedgerState} \mapsto \mathsf{Script}\mapsto \mathsf{Script}\mapsto \mathsf{Bool}\\
& \mathsf{scriptValidate} ~ \mathit{st} ~ \mathit{validator} ~ \mathit{redeemer} =
[\![ validator ]\!] ~ state \left([\![ redeemer ]\!] state\right)
\end{align*}$$

**Scripts**
# Multi-Currency

Multi-currency is explained in detail in [@multi_currency], but here we give some brief details. The main idea is to replace the currency quantity type with a (finite) mapping from currency names to quantity. The understanding is that currencies not in a given mapping are assumed to have value 0 (the additive identity). Previous operations on the quantity type, such as addition and less-than, are now performed coordinate-wise on the new type. We write $\vec{0}$ for the empty map/value.

# Basic Types and Operations

The basic types and operations for this specification are given in 2. Transaction inputs are references to previous unspent outputs, together with the scripts needed to authorize it. Outputs are the pair of an address (the hash of a validator script) and a multi-currency value. A transaction is a collection of inputs and outputs, together with other data for creating new currencies, minting currency, and paying fees. Currency is authorized to be minted using the same mechanism of validator and redeemer scripts. Other needed operations on transactions and UTxO are given in 3.


*Primitive types* $$\begin{equation*}
\begin{array}{rlr}
  \mathit{txid}
& \mathsf{TxId}
& \text{transaction id}
\\
  ix
& \mathsf{Ix}
& \text{index}
\\
  \mathit{addr}
& Addr
& \text{address}
\\
  curr
& \mathsf{Currency}
& \text{currency identifier}
\\
  qty
& \mathsf{Quantity}
& \text{currency quantity}
\end{array}
\end{equation*}$$

*Derived types* $$\begin{equation*}
\begin{array}{rlcrl}
  \mathsf{Value}
& \mathsf{Currency}\mapsto \mathsf{Quantity}
&
& (\mathit{curr}, \mathit{qty})
& \mathsf{Value}
\\
  \mathsf{TxIn}
& \mathsf{TxId}\times \mathsf{Ix}\times \mathsf{Script}\times \mathsf{Script}
&
& (\mathit{txid}, \mathit{ix}, \mathit{validator}, \mathit{redeemer})
& \mathsf{TxIn}
\\
  \mathsf{OutRef}
& \mathsf{TxId}\times \mathsf{Ix}
&
& (\mathit{txid}, \mathit{ix})
& \mathsf{OutRef}
\\
  \mathsf{TxOut}
& \mathsf{Addr}\times \mathsf{Value}
&
& (\mathit{addr}, v)
& \mathsf{TxOut}
\\
  \mathsf{UTxO}
& \mathsf{OutRef}\mapsto \mathsf{TxOut}
&
& \mathit{outRef} \mapsto \mathit{txout} \in \mathit{utxo}
& \mathsf{UTxO}
\\
  \mathsf{Create}
& \mathsf{Optional} (\mathsf{Currency}\times \mathsf{Script})
&
& (\mathit{currency}, \mathit{validator})
& \mathsf{Create}
\\
  \mathsf{Forge}
& \mathsf{Value}\times (\mathsf{Currency}\mapsto \mathsf{Script})
&
& (\mathit{value}, \mathit{curr} \mapsto \mathit{redeemer})
& \mathsf{Forge}
\\
  \mathsf{TxBody}
& \mathbb{P}~\mathsf{TxIn} \times (\mathsf{Ix}\mapsto \mathsf{TxOut})
&
& (\mathit{txins}, \mathit{txouts})
& \mathsf{TxBody}
\\
  \mathsf{Tx}
& \mathsf{TxBody}\times \mathsf{Forge}\times \mathsf{Value}\times \mathsf{Create}
&
& (\mathit{txbody}, \mathit{forge}, \mathit{fee}, \mathit{create})
& \mathsf{Tx}
\end{array}
\end{equation*}$$ *Functions* $$\begin{equation*}
\begin{array}{lr}
  \mathsf{txid} \in \mathsf{Tx}\to \mathsf{TxId}
& \text{compute transaction id}
\\
  \mathsf{hash} \in \mathsf{Script}\to \mathsf{Addr}
& \text{compute script address}
\end{array}
\end{equation*}$$

**Basic Definitions**
$$\begin{align*}
& \mathsf{txins} \in \mathsf{Tx}\to \mathbb{P}~\mathsf{TxIn}
& \text{transaction inputs} \\
& \mathsf{txins} ~ ((\mathit{txins}, \_), \_, \_, \_) = \mathit{txins}
\\[1em]
& \mathsf{txouts} \in \mathsf{Tx}\to \mathsf{UTxO}
& \text{transaction outputs as UTxO} \\
& \mathsf{txouts} ~ \mathit{tx} =
  \left\{ (\mathsf{txid} ~ \mathit{tx}, \mathit{ix}) \mapsto \mathit{txout} ~
  \middle| \begin{array}{lcl}
             ((\_, \mathit{txouts}),\_, \_, \_) & = & \mathit{tx} \\
             \mathit{ix} \mapsto \mathit{txout} & \in & \mathit{txouts}
           \end{array}
  \right\}
\\[1em]
& \mathsf{outRefs} \in \mathsf{Tx}\to \mathbb{P}~({\mathsf{TxId}\times \mathsf{Ix}})
& \text{Output References} \\
& \mathsf{outRefs} ~ ((\mathit{txins}, \_), \_, \_, \_)
= \left\{ (id, ix) \middle| (id, ix, \_, \_) \in txins\right\}
\\[1em]
& \mathsf{balance} \in \mathsf{UTxO}\to \mathsf{Value}
& \text{UTxO balance} \\
& \mathsf{balance} ~ utxo = \sum_{(\_ ~ \mapsto (\_, v)) \in \mathit{utxo}} v
\\[1em]
& \mathsf{created} \in \mathsf{Tx}\to \mathsf{Create}
& \text{created currency} \\
& \mathsf{created} ~ (\_, \_, \_, create) = \mathit{create}
\\[1em]
& \mathsf{forged} \in \mathsf{Tx}\to \mathsf{Value}
& \text{the forged multi-currency} \\
& \mathsf{forged} ~ (\_, (value, \_), \_, \_) = \mathit{value}
\\[1em]
& \mathsf{forgeReedemers} \in \mathsf{Tx}\to \mathsf{Script}
& \text{redeemer scripts for forging} \\
& \mathsf{forgeReedemers} ~ ( \_, (\_, \mathit{redeemers}), \_, \_) = reedemers
\\[1em]
& \mathsf{fee} \in \mathsf{Tx}\to \mathsf{Value}
& \text{the fees in a transaction} \\
& \mathsf{fee} ~ (\_, \_, fee, \_) = \mathit{fee}
\end{align*}$$

**Operations on transactions and UTxOs**
# Validation and Ledger State

Validation is the determination that a transaction is permitted to be appended to the ledger and hence manipulate the state of the ledger. The data in the ledger state is given by 5. Though $\mathit{totalMinted}$ and $\mathit{slot}$ do not appear to be used in this specification, they are important since they are used by the validator scripts. For example, expirations can be implemented using $\mathit{slot}$ and a currency's policy may depend on $\mathit{totalMinted}$.

The ledger state is defined inductively. The initial state is defined in 5. Given a transaction and a ledger state, first we check that the transaction is valid. To be valid, it must pass every test given in 4. Note that these rules depend only on the transaction and the ledger state. If a transaction is valid for a given ledger state, it is then applied using the state transformation rule given in 6.

Note that two rules from [@multi_currency] do not appear in 4, namely "creator has enough money\" and "fee is non-negative\". In a model without account transactions, as we have here, we do not need additive inverses and can assume that all quantities are nonnegative.


*Valid-Inputs* $$\begin{equation*}
\mathsf{outRefs}\ \mathit{tx} \subseteq \mathop{\mathrm{dom}}\mathit{utxo}
\end{equation*}$$

*Preservation-of-Value* $$\begin{equation*}
balance (\mathsf{txouts}\ \mathit{t}x) + (\mathsf{fee}\ \mathit{t}x)
  = balance (\mathsf{outRefs}\ \mathit{t}x \lhd utxo) + (\mathsf{forged}\ \mathit{t}x)
\end{equation*}$$

*No-Double-Spend* $$\begin{equation*}
\lvert \mathsf{txins}\ \mathit{t}x \rvert = \lvert \mathsf{outRefs}\ \mathit{t}x\rvert
\end{equation*}$$

*Scripts-Validate* $$\begin{equation*}
\forall (\_, \_, validator, redeemer)\in(\mathsf{txins}\ \mathit{t}x),
~ \mathsf{scriptValidate} ~ \mathit{state} ~ \mathit{validator} ~ \mathit{redeemer}
\end{equation*}$$

*Authorized* $$\begin{equation*}
\begin{array}{c}
  \forall i\in(\mathsf{txins}\ \mathit{t}x),\\
    i = (txid, ix, validator, \_)
    \land ((txid, ix) \mapsto (addr, \_)) \in \mathit{utxo}
    \land \mathsf{hash}\ \mathit{v}alidator = addr
\end{array}
\end{equation*}$$

*Forge-Obeys-Policy* $$\begin{equation*}
\begin{array}{c}
\forall c\in(\mathsf{forged}\ \mathit{t}x), \\
\exists policy, (c \mapsto policy) \in \mathit{currencies} \\
\exists reedemer, (c \mapsto reedemer) \in \mathsf{forgeReedemers}\ \mathit{t}x \\
\mathsf{scriptValidate} ~ \mathit{state} ~ \mathit{policy} ~ \mathit{redeemer}
\end{array}
\end{equation*}$$

*Create-Only-New-Currencies* $$\begin{equation*}
\mathsf{created}\ \mathit{t}x = (curr, policy), curr \notin \mathop{\mathrm{dom}}currencies
\end{equation*}$$

**Validation Rules**
*Ledger State* $$\begin{equation*}
\begin{array}{rlr}
utxo & \mathsf{UTxO}& \text{unspent outputs}
\\
currencies & \mathsf{Currency}\mapsto \mathsf{Script}
  & \text{currencies with policies}
\\
totalMinted & \mathsf{Value}& \text{total currency minted}
\\
slot & \mathsf{Slot}& \text{current slot}

\end{array}
\end{equation*}$$ *Initial Ledger State* $$\begin{equation*}
\begin{array}{llllll}
utxo = \emptyset
  & currencies = \emptyset
  & totalMinted = \vec{0}
  & slot = 0
\end{array}
\end{equation*}$$

**Ledger State**
$$\begin{equation}
\label{eq:utxo-update}
    \inference[update-UTxO]
    {
      \text{Valid-Inputs} & \text{Preservation-of-Value} & \text{No-Double-Spend} \\
      \text{Scripts-Validate} & \text{Authorized} & \text{Forge-Obeys-Policy}
    }
    {
      \begin{array}{rcl}
        \mathit{utxo} & & (\mathsf{outRefs}\ \mathit{t}x \mathbin{\slashed{\lhd}}\mathit{utxo}) \cup\mathsf{txouts}\ \mathit{t}x \\
        \mathit{totalMinted} & \xlongrightarrow[\textsc{}]{tx} & \mathit{totalMinted} + (\mathsf{forged}\ \mathit{t}x)\\
      \end{array}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:create-currency}
    \inference[create-currency]
    {
      \text{Create-Only-New-Currencies}
    }
    {
      \mathit{currencies} \xlongrightarrow[\textsc{}]{tx} \mathit{currencies} \cup(\mathsf{created}\ \mathit{t}x)
    }
\end{equation}$$

**State Transitions**
# Disabling Multi-Currency

If we want to disable multi-currency, we can remove the "Forge Obeys Policy\" rule and add 7


*Only ADA* $$\begin{equation*}
\mathsf{created}\ \mathit{t}x = (curr, policy), curr = \mathsf{ADA}
\end{equation*}$$

**Only ADA Rule**
# Disabling Scripts

WIP - We should probably make two types of addresses, pay-to-pubkey addresses and script addresses. The pay-to-pubkey addresses will work similarly to the validation rules defined above, with the following changes:

\"Scripts Validate\" becomes a specific validator/redeemer pair, where $\mathsf{validator}$ checks a digital signature and $\mathsf{redeemer}$ is the constant function returning a signature of the part of transaction (perhaps $\mathsf{outRefs}\ \mathit{t}x$?).

"Authorized\" is nearly the same, except we hash the stake key instead of the validator script.

"No Double Spend\" is no longer needed.

# Extended UTxO

The main documentation is [here](https://github.com/input-output-hk/plutus/tree/master/docs/extended-utxo). We need to add the data script to TxOut: $$\mathsf{TxOut}= \mathsf{Addr}\times \mathsf{Value}\times \mathsf{Script}$$ We also need to provide the validator script with more information. Is the $\mathsf{TxBody}$ enough? How is this more expressive than what we already have?
