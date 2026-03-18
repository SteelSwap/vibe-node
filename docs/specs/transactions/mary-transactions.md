
*Abstract Types* $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{s_{mc}} & \mathsf{ScriptMPS} & \text{monetary policy script}
     \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{lng} & \mathsf{Language} & \{\mathsf{nativeMSigTag}, \mathsf{nativeMATag}, \cdots\} \\
      \mathit{scr} & \mathsf{Script} & \mathsf{ScriptMSig} \uplus \mathsf{ScriptMPS} \\
      \mathit{pid} & \mathsf{PolicyID} & \mathsf{ScriptHash} \\
       % \text{currency ID}\\
      \mathit{aid} & \mathsf{AssetID} & \mathbb{H}_{\leq 32}\\
       % \text{token identifier}\\
      \mathit{quan} & \mathsf{Quantity} & \Z \\
      %\text{quantity of a token}\\
      \mathit{v}, \mathit{w} & \mathsf{Value}
      & \mathsf{PolicyID} \mapsto ( \mathsf{AssetID} \mapsto \mathsf{Quantity} ) \\
%      & \text{a collection of tokens}
      \mathit{txout}
      & \mathsf{TxOut}
      & \mathsf{Addr} \times \mathsf{Value}
%      & \text{tx outputs}
      \\
      \mathit{utxoout}
      & \mathsf{UTxOOut}
      & \mathsf{Addr} \times \mathsf{Value} \\
%      & \text{utxo outputs}
      \mathit{utxo}
      & \mathsf{UTxO}
      & \mathsf{TxIn} \to \mathsf{UTxOOut}
%      & \text{unspent tx outputs}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{align*}
    \mathsf{language} ~\in~    & \mathsf{Script} \to \mathsf{Language} \\
                            & \text{returns the language tag, e.g. $\mathsf{nativeMATag}$ for the MPS language} \\
    \mathsf{evalMPSScript}~\in~& \mathsf{ScriptMPS}\to\mathsf{PolicyID}\to\mathsf{Slot}\to\powerset\mathsf{KeyHash} \\
    % \\
%   \caption{Languages}
\end{align*}$$

**Type Definitions used in the UTxO transition system ($\mathbb{H}_{\leq 32}$ is a string of exactly 32 bytes)**
# Transactions
This section describes the changes that are necessary to the transaction and UTxO type structure to support native multi-asset functionality in Cardano.

## Representing Multi-asset Types and Values.

Some new types (and some changes to existing types) are required for the ledger to support multi-assets, as shown in Figure 1. All other types are as specified in the Shelley ledger design and implementation \.... An *Asset* comprises a set of different *Asset Classes*, each of which has a unique identifier, $\mathsf{AssetID}$ (of type $\mathbb{H}_{\leq 32}$, that is *byte strings of length $\leq 32$*). We will informally refer to a pair $(\mathit{pid}, \mathit{aid})$ of a Policy ID and an Asset ID as a "token". The set of tokens that are referred to by the underlying monetary policy represents the coinage that the asset supports. A multi-asset value, $\mathsf{Value}$ is a map over zero or more assets to single asset values. A single asset value is then a finite map from $\mathsf{AssetID}$s to quantities.

## Value Operations and Partial Order.

We require basic operations on $\mathsf{Value}$, which include, equality, addition and $\leq$ comparison. For convenience, here and in the rest of the document, we will also treat values of type $\mathsf{Value}$ as non-partial functions where any omitted tokens in the domain of an asset are assumed to be zero.

Addition and binary relations are extended pointwise from $\mathsf{Coin}$ to $\mathsf{Value}$, so if $R$ is a binary relation defined on $\mathsf{Coin}$, like $=$ or $\leq$, and $v, w$ are values, we define

$$v~R~w :\Leftrightarrow \forall~\mathit{pid}~\mathit{aid}, (v~\mathit{pid}~\mathit{aid})~R~(w~\mathit{pid}~\mathit{aid})$$ $$(v + w)~\mathit{pid}~\mathit{aid} := (v~\mathit{pid}~\mathit{aid}) + (w~\mathit{pid}~\mathit{aid})$$.

- $\mathsf{Language}$ is an abstract type that labels the scripting language, e.g. $\mathsf{nativeMSigTag}$ or $\mathsf{nativeMATag}$. It is kept abstract for easier extensibility in the future.

- $\mathsf{PolicyID}$ identifies a specific asset. As in normal life, two assets may use the same *coinage* (sets of tokens that distinguish different values in the asset), but are distinguished by their *monetary policy*, which governs how tokens of the asset may be created and destroyed. The monetary policy for an asset $\mathit{pid}$ is given by the *Monetary Policy Script* (MPS) $s$, where $\mathsf{hashScript}~s~=~pid$. When a transaction attempts to create or destroy tokens, the script verifies that the coinage for asset $\mathit{pid}$ respects the restrictions that are imposed by the monetary policy. If the restrictions are complied with, then it returns $\mathsf{True}$, and if they are not then it returns $\mathsf{False}$. Monetary Policy Scripts are described in more detail below.

- $\mathsf{AssetID}$ : the coinage for an asset $\mathit{pid} \in \mathit{PolicyID}$ is a set of terms $t\in\mathsf{AssetID}$. Each $t$ identifies a unique kind of token in $\mathit{pid}$. We will assume that the token for Ada is $(\mathsf{adaID}, \mathsf{adaToken})$.

- $\mathsf{Quantity}$ is an integer type that represents an amount of a specific $\mathsf{AssetID}$. We associate a term $q\in\mathsf{Quantity}$ with a specific token to track how much of that token is contained in a given asset value.

- $\mathsf{Value}$ is the multi-asset type that is used to represent an amount of a collection of tokens, including Ada. If $(\mathit{pid}, \mathit{aid})$ is a token and $v \in \mathsf{Value}$, the amount in $v$ belonging to that token is $v~\mathit{pid}~\mathit{aid}$ if defined, or zero otherwise. Token amounts are fungible with each other if and only if they belong to the same token, i.e. they have the same $\mathsf{PolicyID}$ and $\mathsf{AssetID}$. Terms of type $\mathsf{Value}$ are sometimes also referred to as *token bundles*.

- $\mathsf{TxOut}$ : The type of outputs that are carried by a transaction. This differs from the base Shelley $\mathsf{TxOut}$ type in that it contains a $\mathsf{Value}$ rather than a $\mathsf{Coin}$

- $\mathsf{UTxOOut}$ is the type of UTxO entry that is created when a transaction output is processed. This has the same structure as the transaction output $\mathsf{TxOut}$, but is given a different name to account for the fact that $\mathsf{Value}$ is stored differently in the outputs of $\mathsf{UTxO}$ and $\mathsf{Tx}$ (due to optimization in the $\mathsf{UTxO}$).

- $\mathsf{UTxO}$ entries are stored in the finite map $\mathsf{TxIn}\mapsto \mathsf{UTxOOut}$. This type also differs from the Shelley $\mathsf{UTxO}$ type only in that $\mathsf{Coin}$ is replaced by $\mathsf{Value}$.

#### The Monetary Policy Scripting Language.

Recall that an asset is identified by the hash of its MPS. Figure fig:defs:tx-mc-script gives the types that relate to monetary policy scripts. As discussed below, the monetary policy script type, $\mathsf{ScriptMPS}$, groups multisig scripts and resourced scripts. The abstract function $\mathsf{language}$ returns a value of type $\mathsf{Language}$, corresponding to the language that is used by a given script.

#### Multi-Asset Script Evaluation.

A monetary policy is a collection of restrictions on the tokens of a specific multi-asset. MP scripts are evaluated for the purpose of checking that the given asset adheres to its monetary policy. The monetary policy scripting language is a basic scripting language that allows for expressing some of the most common restrictions, e.g. the maximum total number of different kinds of tokens of a given asset. A suggestion for $\mathsf{ScriptMPS}$ and the implementation of the function $\mathsf{evalMPSScript}$, which evaluates MPS scripts, is given in Appendix sec:mps-lang. As inputs, $\mathsf{evalMPSScript}$ takes

- the script getting evaluated

- the $\mathsf{PolicyID}$ of the asset being forged

- the current slot number,

- a set of key hashes (needed to use MSig scripts as MPS scripts)

- the transaction body

- the inputs of the transaction as a UTxO finite map (with addresses and values), i.e. the outputs it is spending

## MPS Script Validation.

In the Shelley ledger specification, a script validation function is used to evaluate all types of native (ledger-rule-defined) scripts. In Figure 2, we modify this function to also call the evaluation function that is specific to our new MPS script type.

The arguments that are passed to the $\mathsf{validateScript}$ function include all those that are needed for MPS and MSig script evaluation. Because of the extra arguments (the slot number and the UTxO), we also modify the call to this function within the UTXOW rule.


$$\begin{align*}
      \mathsf{validateScript} & \in\mathsf{Script}\to\mathsf{ScriptHash}\to\mathsf{Slot}\to
      \mathbb{P}~\mathsf{KeyHash}\to\mathsf{TxBody}\to\mathsf{UTxO}\to\mathsf{Bool} \\
      \mathsf{validateScript} & ~s~\mathit{pid}~\mathit{slot}~\mathit{vhks}
       ~\mathit{txb}~\mathit{utxo} =
                             \begin{cases}
                               \mathsf{evalMultiSigScript}~s~vhks & \text{if}~s \in\mathsf{ScriptMSig} \\
                               \mathsf{evalMPSScript}~s~\mathit{pid}~\mathit{slot}~\mathit{vhks} \\
                                ~~~~txb~\mathit{utxo} & \text{if}~s \in\mathsf{ScriptMPS} \\
                               \mathsf{False} & \text{otherwise}
                             \end{cases} \\
\end{align*}$$

**Script Validation**
## The Forge Field.

The body of a transaction with multi-asset support contains one additional field, the $\mathsf{forge}$ field (see Figure 3). The $\mathsf{forge}$ field is a term of type $\mathsf{Value}$, which contains tokens the transaction is putting into circulation or taking out of circulation. Here, by \"circulation\", we mean specifically \"the UTxO on the ledger\". Since the administrative fields cannot contain tokens other than Ada, and Ada cannot be forged, they are not affected in any way by forging.

Putting tokens into circulation is done with positive values in the $\mathsf{Quantity}$ fields of the tokens forged, and taking tokens out of circulation can be done with negative quantities.

A transaction cannot simply forge arbitrary tokens. Recall that restrictions on Multi-Asset tokens are imposed, for each asset with ID $\mathit{pid}$, by the script with the hash $\mathit{pid}$. Whether a given asset adheres to the restrictions prescribed by its script is verified at forging time (i.e. when the transaction forging it is being processed). Another restriction on forging is imposed by the preservation of value conditition. Also, no forging Ada is permitted. In Section sec:utxo, we specify the mechanism by which forging is done, and rules that enforce these restrictions.

## Transaction Body.

Besides the addition of the $\mathsf{forge}$ field to the transaction body, note that the $\mathsf{TxOut}$ type in the body is not the same as the $\mathsf{TxOut}$ in the system without multi-asset support. Instead of $\mathsf{Coin}$, the transaction outputs now have type $\mathsf{Value}$.

The only change to the types related to transaction witnessing is the addition of MPS scripts to the $\mathsf{Script}$ type, so we do not include the whole $\mathsf{Tx}$ type here.


*Transaction Type* $$\begin{equation*}
    \begin{array}{rlll}
      \mathit{txbody} ~\in~ \mathsf{TxBody} ~=~
      & \mathbb{P}~\mathsf{TxIn} & \mathsf{txinputs}& \text{inputs}\\
      &\times ~(\mathsf{Ix} \mapsto \mathsf{TxOut}) & \mathsf{txouts}& \text{outputs}\\
      & \times~ \mathsf{DCert}^{*} & \mathsf{txcerts}& \text{certificates}\\
       & \times ~\mathsf{Value}  & \mathsf{forge} &\text{value forged}\\
       & \times ~\mathsf{Coin} & \mathsf{txfee} &\text{non-script fee}\\
       & \times ~\mathsf{Slot} & \mathsf{txttl} & \text{time to live}\\
       & \times~ \mathsf{Wdrl}  & \mathsf{txwdrls} &\text{reward withdrawals}\\
       & \times ~\mathsf{Update}  & \mathsf{txUpdates} & \text{update proposals}\\
       & \times ~\mathsf{MetaDataHash}^? & \mathsf{txMDhash} & \text{metadata hash}\\
    \end{array}
\end{equation*}$$ *Accessor Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{getValue} & \mathsf{TxOut} \uplus \mathsf{UTxOOut} \to \mathsf{Value} & \text{output value} \\
      \mathsf{getAddr} & \mathsf{TxOut} \uplus \mathsf{UTxOOut} \to \mathsf{Addr} & \text{output address} \\
    \end{array}
\end{equation*}$$

**Definitions used in the UTxO transition system (continued).**
## Coin and Multi-Asset Tokens

When multi-asset is introduced, Ada is still expected to be the most common type of token on the ledger. The $\mathsf{Coin}$ type is used to represent an amount of Ada. It is the only type of token that can be used for all non-UTxO ledger accounting, including deposits, fees, rewards, treasury, and the proof of stake protocol. Under no circumstances are these administrative fields and calculations ever expected to operate on any types of tokens besides Ada. These fields will continue to have the type $\mathsf{Coin}$.

The exact representation of tokens in the UTxO and inside transactions is an implementation detail, which we omit here. Note that it necessarily is equivalent to $\mathsf{Value}$, optimized for Ada-only cases, has a unique representation for Ada tokens, and does not allow Ada to have tokens denoted by anything other than $\mathsf{adaToken}$.

In Figure 4 we give the following helper functions and constants. These are needed to use Ada in a multi-asset setting.

- $\mathsf{adaID}$ is a random script hash value with no known associated script. It is the policy ID of Ada. Even if a script that hashes to this value and validates is found, the UTXO rule forbids forging Ada

- $\mathsf{adaToken}$ is a byte string representation of the word \"Ada\". The ledger should never allow the use of any other token name associated with Ada's policy ID

- $\mathsf{qu}$ and $\mathsf{co}$ are type conversions from quantity to coin. Both of these types are synonyms for $\Z$, so they are type re-naming conversions that are mutual inverses, with

  $\mathsf{qu} ~(\mathsf{co} ~q )~= ~q$, and

  $\mathsf{co}~ (\mathsf{qu}~ c) ~=~ c$, for all $c \in \mathsf{Coin},~q \in \mathsf{Quantity}$.

- $\mathsf{coinToValue}$ takes a coin value and generates a $\mathsf{Value}$ type representation of it

An amount of Ada can also be represented as a multi-asset value using the notation in Figure 4, as $\mathsf{coinToValue}~c$ where $c \in \mathsf{Coin}$. We must use this representation when adding or subtracting Ada and other tokens as $\mathsf{Value}$, e.g. in the *preservation of value* calculations.


*Abstract Functions and Values* $$\begin{align*}
    \mathsf{adaID} \in& ~\mathsf{PolicyID}
    & \text{Ada asset ID} \\
    \mathsf{adaToken} \in& ~\mathsf{AssetID}
    & \text{Ada Token} \\
    \mathsf{co} \in& ~\mathsf{Quantity} \to \mathsf{Coin}
    & \text{type conversion} \\
    \mathsf{qu} \in& ~\mathsf{Coin} \to \mathsf{Quantity}
    & \text{type conversion} \\
\end{align*}$$ *Helper Functions* $$\begin{align*}
    \mathsf{coinToValue} \in & ~\mathsf{Coin}\to \mathsf{Value} \\
    \mathsf{coinToValue}~ c = & \{\mathsf{adaID} \mapsto \{\mathsf{adaToken} \mapsto \mathsf{qu}~c\}\} \\
    &\text{convert a Coin amount to a Value} \\
\end{align*}$$

**Auxiliary Functions to Support Multi-Asset Capability**