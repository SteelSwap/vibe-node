# Transactions
In this chapter, we outline the changes necessary to transaction and UTxO structure to make it possible to use Plutus scripts to validate certain actions. Note that we use EUTxO and UTxO interchangably here, implicitly referring to the extended version.

In Figure 1, we give the transaction types modified to support Plutus.

These types are consistent with the Shelley ledger as much as possible, except for the following changes and additions:

- $\mathsf{PolicyID}$ is the type of hashes of Plutus and MSig scripts (and any other scripts added in the future)

- $\mathsf{RdmrsHash}$ is the type of hashes of the indexed redeemer structure included in the transaction (details about this structure below)

- $\mathsf{AssetID},~\mathsf{Quantity}$ are types related to native multicurrency on the ledger.

- $\mathsf{ScriptMSig}$ is the native multisignature scripts already supported.

- $\mathsf{ScriptPlutus}$ is a type for scripts made with the Plutus version that is the first version of Plutus supported. Subsequent versions will have names like $\mathsf{ScriptPlutusV2}$. Recall that introducing a new version of Plutus necessitates a hard fork, and requires changes to the formal and executable specs.

- $\mathsf{Yes}$ and $\mathsf{Nope}$: These are single-value types used in tags. These values are used instead of booleans for clarity.

- The tags indicate which of the (currently, four) types of things a script can be validating, i.e.\
  $\mathsf{inputTag}$ is for validating spending a (Plutus) script UTxO entry\
  $\mathsf{forgeTag}$ is for validating forging tokens\
  $\mathsf{certTag}$ is for validating certificates with script credentials\
  $\mathsf{wdrlTag}$ is for validating reward withdrawals from (Plutus) script addresses

- $\mathsf{Script}$ is a sum type for all types of scripts, currently only Plutus V1 and multisig

- $\mathsf{IsValidating}$ is a tag that indicates when a transaction is expected to have all the non-native scripts (currently this means only Plutus scripts) inside it validate. This value is added by the block creator when constructing a block, and is checked as part of running scripts. $\mathsf{Yes}$ for when when all scripts will validate, $\mathsf{Nope}$ is for when one of them does not.

- $\mathsf{Data}$ refers to the type defined in Plutus libraries, but is related to a ledger type (see note \"Data Representation\" below)

- $\mathsf{Value}$ is the multicurrency type used to represent both fungible and non fungible tokens. The key of this finite map type is the hash of the monetary policy script for tokens of this currency. This hash is referred to as the $\mathsf{PolicyID}$ of the currency. Within a single currency, tokens belong to an $\mathsf{AssetID}$, which is assigned at the creation the token and can be controlled by monetary policy script. Tokens with different $\mathsf{PolicyID}$s or different $\mathsf{AssetID}$s are not fungible with each other. See the note below for a discussion of Ada representation.

- $\mathsf{IsFee}$ is a tag that indicates when an input has been marked to be used for paying transaction fees ($\mathsf{Yes}$ for when it is for fees, $\mathsf{Nope}$ when it is not). The purpose of this tag is to give users a way to prevent the entire value of the UTxO entries spent by the transaction from going into the fee pot in case of script validation failure. Instead, only the total amount referenced by for-fees inputs goes to the fee pot.

  Note that in the extended UTxO model, it is possible for a transaction to either be processed in full, or do nothing but pay fees for script validation (in the case of script validation failure, see Section sec:utxo for details). In designing a way to prevent all Ada in the transaction outputs from going into the fee pot (in case of script validation failure), we have considered two possibilities:

  - programmatically select the inputs which will be used to pay fees

  - allow the user to decide which inputs will be used to pay fees

  We have decided to give control over input selection for this purpose to the user, as users may have different considerations when making their selection. This option will additionally allow users to write their own programmatic solutions to choosing for-fees inputs.

- $\mathsf{UTxOIn}$ is the type of the keys in the UTxO finite map. In Goguen, it is the same as the type as the basic UTxO keys in Shelley, but we have changed the name to make the distinction between a transaction input type and UTxO keys. These two types are the same in Shelley, but distinct in Goguen.

- $\mathsf{TxIn}$ is a transaction input. It includes the reference to the UTxO entry it is spending (the UTxO output reference part) and the $\mathsf{IsFee}$ tag, which indicates if this input should be used to pay script execution fees.

  Only VK-spending inputs and native-script (MSig) spending inputs can be used to pay fees. In Shelley, spending VK or MSig outputs is validated in a single witnessing rule application, so either all required signatures are valid, or a transaction is completely invalid. We kept this model, but chose a different approach to charging users for running Plutus scripts, see Section sec:two-phase.

  It is expected that Plutus scripts will be more expensive to run, on average, than only checking signatures. We want to charge users for running Plutus scripts, even if they do not validate. The outputs spent to pay for running them (the ones marked as for-fees) must be validated fully before validating Plutus scripts.

- $\mathsf{TxOutND}$: A transaction output with no datum hash (this type is for VK and multisig scripts outputs).

- $\mathsf{TxOutP}$: A transaction output type for Plutus script outputs (which include datum hash).

- $\mathsf{HasDV}$: This is a tag attached to a transaction output if it is locked by a Plutus script. That is, the output contains an address, a value, and necessarily a hash of a datum. This tag indicates whether the transaction carrying the output contains, in its set of datum objects, the full datum corresponding to the hash of the datum in the output.

  Note that it is up to the user to decide whether the transaction should have the full datum. The purpose of including it is strictly to communicate it to the user who will be spending the output in the future, and will require the full datum to validate the Plutus script locking the output. However, this tag must be applied correctly, otherwise the transaction will not validate.

- $\mathsf{UTxOOut}$ is the type of UTxO entry that gets created when a transaction output is processed. Note that, like in the case of the type of transaction inputs, the type of a transaction output is distinct from the type of the UTxO entry that gets created with the transaction output data.

  The (extended) UTxO entries in the Goguen era include the slot numbers associated with each output to indicate when the output was created. This feature will be used for functionality that will be added in the future.

- $\mathsf{TxOut}$ : The type of outputs carried by a transaction, $\mathsf{TxOutND}$ or the pair of $\mathsf{TxOutP}$ with the tag $\mathsf{HasDV}$.

- $\mathsf{UTxO}$ entries are stored in the finite map $\mathsf{UTxOIn}\mapsto \mathsf{UTxOOut}$

- $\mathsf{RdmrPtr}$: This type is a pair of a tag and an index. This type is used to index Plutus redeemers that are included in a transaction. More on this below.

- $\mathsf{CurItem}$ is either the hash of a forging script (currency ID), the current transaction input being spent, the current reward withdrawal, or the current certificate being validated. This current item is a sum type of all the types of things for which we want to run scripts to validate.

::::: {#fig:defs:utxo-shelley-1 .figure latex-placement="htb"}
*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{polid} &\mathsf{PolicyID} & \text{hash of policy scripts}\\
      \mathit{hdv} &\mathsf{RdmrsHash} & \text{hash of the indexed redeemers structure}\\
      \mathit{assetid} & \mathsf{AssetID} & \text{asset identifier}\\
      \mathit{quan} & \mathsf{Quantity} & \text{quantity of a token}\\
      \mathit{msig} & \mathsf{ScriptMSig} & \text{Multisig scripts} \\
      \mathit{plc} & \mathsf{ScriptPlutus} & \text{Plutus scripts of initial Plutus version} \\
      \mathit{yes} & \mathsf{Yes} & \text{tag type for yes} \\
      \mathit{no} & \mathsf{Nope} & \text{tag type for no} \\
      \mathit{dat} & \mathsf{Data} & \text{the $\mathsf{Data}$ type} \\
    \end{array}
\end{equation*}$$ *Tag types*

::: center
$\mathsf{inputTag},~\mathsf{forgeTag},~\mathsf{certTag},~\mathsf{wdrlTag}$

*Script types* $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{scr} & \mathsf{Script} & \mathsf{ScriptPlutus} \uplus \mathsf{ScriptMSig} \\
      \mathit{isv} & \mathsf{IsValidating} & \mathsf{Yes} \uplus \mathsf{Nope} \\
    \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{val} & \mathsf{Value}
      & \mathsf{PolicyID} \mapsto (\mathsf{AssetID} \mapsto \mathsf{Quantity})
%      & \text{a collection of tokens}
      \\
      \mathit{isf}
      & \mathsf{IsFee}
      & \mathsf{Yes} \uplus \mathsf{Nope}
%      & \text {tag for inputs used to pay script fees}
      \\
      \mathit{uin}
      & \mathsf{UTxOIn}
      & \mathsf{TxId} \times \mathsf{Ix}
%      & \text{transaction output preference}
      \\
      \mathit{txin}
      & \mathsf{TxIn}
      & \mathsf{TxId} \times \mathsf{Ix} \times \mathsf{IsFee}
%      & \text{transaction input}
      \\
      (\mathit{addr}, v)
      & \mathsf{TxOutND}
      & \mathsf{Addr} \times \mathsf{Value}
%      & \text{vk address output}
      \\
      (\mathit{addr}, v, \mathit{hashscr_d})
      & \mathsf{TxOutP}
      & \mathsf{TxOutND} \times \mathsf{DataHash}
%      & \text{script address output}
      \\
      \mathit{hdv}
      & \mathsf{HasDV}
      & \mathsf{Yes} \uplus \mathsf{Nope}
      %      & \text {tag for outputs that come with datums}
      \\
      \mathit{uout}
      & \mathsf{UTxOOut}
      & (\mathsf{TxOutND} \uplus \mathsf{TxOutP}) \times \mathsf{Slot}
%      & \text{transaction outputs}
      \\
      \mathit{txotx}
      & \mathsf{TxOut}
      & \mathsf{TxOutND} \uplus (\mathsf{TxOutP} \times \mathsf{HasDV})
%      & \text{transaction outputs in a transaction}
      \\
      \mathit{utxo}
      & \mathsf{UTxO}
      & \mathsf{UTxOIn} \mapsto \mathsf{UTxOOut}
%      & \text{unspent tx outputs}
      \\
      \mathit{dvin}
      & \mathsf{RdmrPtr}
      & (\mathsf{inputTag} \uplus \mathsf{forgeTag} \uplus
      \mathsf{certTag} \uplus \mathsf{wdrlTag}) \times \mathsf{Ix}
%      & \text{reverse pointer to thing dv is for}
      \\
      \mathit{cur}
      & \mathsf{CurItem}
      & \mathsf{CurrencyId} \uplus (\mathsf{TxId} \times \mathsf{Ix}) \uplus \mathsf{AddrRWD} \uplus \mathsf{DCert}
%      & \text{item the script is validated for}
    \end{array}
\end{equation*}$$

**Definitions used in the UTxO transition system**
:::::

**Data Representation.** The type $\mathsf{Data}$ is a Plutus type, however, there is a similar type in the ledger. We do not assume these are the same $\mathsf{Data}$, but we do assume there is structural equality between them.

**Witnessing.** In Figure 2, the type $\mathsf{TxWitness}$ contains everything in a transaction that is needed for witnessing (script and VK), including

- VK signatures, as before

- a set of scripts (this includes scripts of all languages, and for all validation purposes - forging tokens, spending outputs, verifying certificates, and verifying withdrawals)

- a set of terms of type data, which contains all required datum objects

- an structure indexed by $\mathsf{RdmrPtr}$, with $\mathsf{Data}$ values, which includes all required redeemers

There is a difference between the way scripts and datum objects are included in a transaction (as a set) versus how redeemers are (as an indexed structure). The reason for this difference is a matter of matching the pieces of witnessing info to the thing it is required for witnessing. There are two possibilities here:

- The item being validated (output, forge, etc.) explicitly references the piece needed for witnessing, usually by containing its hash. In particular, this is the case for all scripts. Script addresses, currency IDs, and certificate credentials must contain the hash of the validator script that will be run.

  To find the script, we can look through the set of scripts for the one with the matching hash value. This is also the case with hashes of datum objects. A Plutus-script locked UTxO entry contains the hash of the datum, and we can look for the datum with this hash in the set.

- The item being validated has no explicit link to, hash of, or reference to, the piece of data needed for validation. In this case, we must create the link.

  For redeemers, we use a reverse pointer approach. Instead of pairing a pointer (to the correct redeemer) with the item that redeemer is needed for, we make the index of the redeemer the pointer to the item for which it will be used. This pointer is the key in the indexed redeemer structure. This pointer is a pair of a tag indicating the type of thing being validated, and an index of it in the structure (list, set, or map) where it is stored.

**Body of the Transaction.** We have also made the following changes to the body of the transaction:

- We have changed $\mathsf{txinputs}$ to map to $\mathsf{TxIn}$, and added other the relevant accessor functions. The transaction still contains inputs ($\mathsf{TxIn}$), and outputs ($\mathsf{TxOut}$), which are of different types than for Shelley transactions.

- the body now includes a term of type $\mathsf{Value}$, which represents the tokens forged (or taken out of circulation, if the quantity is negative) by the transaction, with accessor $\mathsf{forge}$. Ada cannot be forged this way.

- the body now includes a term of type $\mathsf{ExUnits}$, which is the total quantity of execution units that may be used by all Plutus scripts in the transaction. This execution units \"budget\" is pre-computed off-chain by a Plutus interpreter before the transaction is submitted, with accessor $\mathsf{txexunits}$

- the time to live $\mathsf{Slot}$ was replaced by a liveness interval $\mathsf{Slot} \times \mathsf{Slot}$, where the first slot is accessed by $\mathsf{txfst}$.

- the fee a transaction is paying is the sum total of the script and the non-script transaction fee portions, with accessor $\mathsf{txfee}$ as in Shelley

- the body has a hash of the the indexed redeemer structure with accessor $\mathsf{rdmrsHash}$

- the body has a hash of a subset of the current protocol parameters (only the ones relevant to Plutus script validation of each Plutus version of the transaction's validators), $\mathsf{PPHash}$, with accessor $\mathsf{ppHash}$

**Additional Role of Signatures on TxBody.** Note that the transaction body must contain every bit of data (or at least the hash of the data) that can influence the on-chain transfer of value resulting from this transaction being processed (see Figure 2). In the classic UTxO case, this means that, for example, every input being spent and every output being created are in the body.

There is no need to ever sign anything related to validator scripts or datum objects, because a hash of every validator script that will be run during the validation of the transaction is always part of the body, and the hash of every datum is recorded in the UTxO.

In the EUTxO case, this means additionally including everything in the body that can change the validation outcome of a transaction between \"fully validated\", and \"only paying fees\" (two distinct cases of value transfer, which we will explain in Section sec:utxo).

The signatures on transactions in both the extended and basic UTxO models are outside the body of the transaction. In both the basic and extended UTxO model, the body is signed by every key whose outputs are being spent. In the extended case, this additionally offers protection from tampering with Plutus interpreter arguments, which may cause script validation failure (thus putting the transaction in the \"only paying fees\" case). In particular, the hash of the indexed redeemer structure, which has type $\mathsf{RdmrPtr} \mapsto \mathsf{Data}$, is part of the body.

Anyone whose tokens are being spent as part of a given transaction signs the transaction body. The body also includes the for-fee tags attached to inputs. Because of this, the users whose tokens are being spent by the transaction have signed their selection of inputs that will be put in the fee pot in case of script validation failure. With this body structure, like in the basic UTxO case, a change in the body of the transaction will make the transaction completely invalid, rather than cause the fee-paying script validation failure or change the amount of fees it pays.

**GoguenTx** Finally, the complete Goguen transaction is made up of:

- the transaction body

- all info needed for transaction witnessing

- $\mathsf{IsValidating}$ is a tag that is set by the user submitting the block containing this transaction. Its correctness is verified as part of the ledger rules, and the block is deemed invalid if this tag is applied incorrectly. It can later be used to re-apply blocks without performing script validation again. This tag does not need to be signed, since incorrect use will result in the whole block being invalid, which benefits no one.

- transaction metadata

**Processing Shelley Transactions in the Goguen Era.** Everything we have discussed so far in this document is about the structure and data in Goguen era protocol parameters and transactions. Some type names are reinterpreted for different purposes in the Goguen era than they were used for in Shelley, and we specify the differences in these cases.

To make the transition from one era to the next smoother and less restrictive, in the Goguen era, we will be able to process both transaction formats. For this reason, we refer to the Shelley trasaction type as $\mathsf{ShelleyTx}$, and $\mathsf{GoguenTx}$ is the new style Goguen transaction. A true Goguen transaction is really of either type, i.e. $\mathsf{ShelleyTx} \uplus \mathsf{GoguenTx}$.

Shelley transactions have less data than the Goguen ones, so we can interpret a Shelley transaction as a Goguen one and process it using Goguen ledger rules. A crucial part of a Shelley transaction, however, that cannot be transformed, is the witnesses. We will specify how to verify signatures before transforming and processing the rest of a Shelley transction in the Goguen format when we discuss witnessing.


*Transaction Types* $$\begin{equation*}
    \begin{array}{rlll}
      \mathit{wits} ~\in~ \mathsf{TxWitness} ~=~
       & (\mathsf{VKey} \mapsto \mathsf{Sig}) & \mathsf{txwitsVKey} & \text{VK signatures}\\
       & \times ~\mathbb{P}~\mathsf{Script}  & \mathsf{txscripts} & \text{all scripts}\\
       & \times~ \mathbb{P}~\mathsf{Data} & \mathsf{txdats} & \text{all datum objects}\\
       & \times ~(\mathsf{RdmrPtr} \mapsto \mathsf{Data})& \mathsf{txrdmrs}& \text{indexed redeemers}\\
    \end{array}
\end{equation*}$$ $$\begin{equation*}
    \begin{array}{rlll}
      \mathit{txbody} ~\in~ \mathsf{TxBody} ~=~
      & \mathbb{P}~\mathsf{TxIn} & \mathsf{txinputs}& \text{inputs}\\
      &\times ~(\mathsf{Ix} \mapsto \mathsf{TxOut}) & \mathsf{txouts}& \text{outputs}\\
      & \times~ \mathsf{DCert}^{*} & \mathsf{txcerts}& \text{certificates}\\
       & \times ~\mathsf{Value}  & \mathsf{forge} &\text{value forged}\\
       & \times ~\mathsf{ExUnits}  & \mathsf{txexunits}& \text{script exec budget}\\
       & \times ~\mathsf{Coin} & \mathsf{txfee} &\text{non-script fee}\\
       & \times ~(\mathsf{Slot}\times\mathsf{Slot}) & \mathsf{txfst},~\mathsf{txttl} & \text{validity interval}\\
       & \times~ \mathsf{Wdrl}  & \mathsf{txwdrls} &\text{reward withdrawals}\\
       & \times ~\mathsf{Update}  & \mathsf{txUpdates} & \text{update proposals}\\
       & \times ~\mathsf{PPHash}^?  & \mathsf{ppHash} & \text{hash or PPs}\\
       & \times ~\mathsf{RdmrsHash}^? & \mathsf{rdmrsHash} & \text{hash of indexed rdmrs}\\
       & \times ~\mathsf{MetaDataHash}^? & \mathsf{txMDhash} & \text{metadata hash}\\
    \end{array}
\end{equation*}$$ $$\begin{equation*}
    \begin{array}{rlll}
      \mathit{txg} ~\in~ \mathsf{GoguenTx} ~=~
      & \mathsf{TxBody} & \mathsf{txbody} & \text{body}\\
      & \times ~\mathsf{TxWitness} & \mathsf{txwits} & \text{witnesses}\\
      & \times ~\mathsf{IsValidating} & \mathsf{txvaltag}&\text{validation tag}\\
      & \times ~\mathsf{MetaData}^? & \mathsf{txMD}&\text{metadata}\\
    \end{array}
\end{equation*}$$ $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{tx} & \mathsf{Tx} & \mathsf{ShelleyTx} \uplus \mathsf{GoguenTx}
      \text{~~a Shelley or Goguen transaction}\\
    \end{array}
\end{equation*}$$ *Accessor Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{getValue} & \mathsf{TxOut} \uplus \mathsf{UTxOOut} \to \mathsf{Value} & \text{output value} \\
      \mathsf{getAddr} & \mathsf{TxOut} \uplus \mathsf{UTxOOut} \to \mathsf{Addr} & \text{output address} \\
      \mathsf{outref} & \mathsf{TxIn} \to (\mathsf{TxId} \times \mathsf{Ix}) & \text{output reference $(txid,ix)$} \\
      \mathsf{getDataHash} & \mathsf{TxOut} \uplus \mathsf{UTxOOut} \to \mathsf{DataHash} & \text{data hash} \\
      \mathsf{getDataTag} & \mathsf{TxOut} \to \mathsf{HasDV} & \text{data} \\
    \end{array}
\end{equation*}$$

**Definitions used in the UTxO transition system, cont.**
**Protocol Parameter Hash Comparison Considerations.** Recall that to ensure deterministic script validation outcome, we must include a hash of certain on-chain data (currently, only some protocol parameters) inside the body of the transaction. This hash is accessed by $\mathsf{ppHash}$. We must also compute the hash of a subset of the actual current protocol parameter values, and compare it to the hash inside the transaction.

To select the relevant protocol parameters to hash, we have defined two helper functions (see Figure 3). The first is an accessor function that returns the language tag of a given script, $\mathsf{language}$. The second is $\mathsf{cmlangs}$, which, given a set of scripts, returns the set of language tags of scripts whose languages have a corresponding cost model, e.g. MSig (recall the discussion in sec:plutus-native). We will use these in the rules we present later to compare the hashes.

Note that at this time, only data from the protocol parameters must be hashed for the comparison we defined. For future Plutus versions, parts of the ledger state may need to be included in this hash as well, if they are passed as arguments to the new interpreter versions. Note also that data from the UTxO is passed to the interpreter, but does not require this type of hash comparison. This is because if the entries the transaction being processed is trying to spend have already been spent, there is a phase 1 validation check that will fail.

In the future, additional functionality may be supported by the ledger that allows a sequence of transactions built over a period of time to be put on-chain as a single transaction. Over this period of time, the parameters or ledger data that must be passed as an argument to script interpreters could have changed. As a result, this transaction (that contains the whole sequence of transactions) is still obligated to include the hash of the current parameters and any additional script processing fees.

Additional fees may be required because of the changes in prices or the cost model for script interpreter versions of the scripts inside the transaction.


*Helper Functions* $$\begin{align*}
    \mathsf{language} ~\in~& \mathsf{Script} \to \mathsf{Language} \\
    &\text{returns the language tag, $\mathsf{plcV1Tag}$ for Plutus V1} \\
    \\[0.5em]
    \mathsf{cmlangs} ~\in~& \mathbb{P}~\mathsf{Script} \to \mathbb{P}~(\mathsf{Language}) \\
    \mathsf{cmlangs}~ \mathit{scrts} ~=~ & \{ \mathsf{language}~\mathit{scr} ~\vert~
      \mathit{scr}~\in~ \mathit{scrts}, \mathsf{language}~\mathit{scr} \in \{\mathsf{plcV1Tag} \}  \}\\
    &\text{get all languages that have cost models (just Plutus V1 at this time)} \\
\end{align*}$$

**Languages and Plutus Versions**
**Coin and Multicurrency Tokens** In the Goguen era, multicurrency is intorduced, but Ada is still expected to be the most common type of token on the ledger. The $\mathsf{Coin}$ type is used to represent an amount of Ada. It is the only type of token which can be used for all non-UTxO ledger accounting, including deposits, fees, rewards, treasury, and the proof of stake protocol. Under no circumstances are these administrative fields and calculations ever expected to operate on any types of tokens besides Ada. These fiels will continue to have the type $\mathsf{Coin}$.

The exact representation of tokens in the UTxO and inside transactions is an implementation detail, which we omit here. Note that it necessarily is equivalent to $\mathsf{Value}$, optimized for Ada-only cases, has a unique representation for the Ada token class, and does not allow tokens of the Ada currency to have a $\mathsf{AssetID}$ value of anything other than $\mathsf{adaToken}$. In Figure 4 are the following helper functions,

- $\mathsf{adaID}$ is a fixed bytestring value with no known associated script (i.e. no known script hashes to this bytestring). It is the currency ID of Ada. Note that as part of transaction validation, we explicitly check that there is no value with currency ID $\mathsf{adaID}$ in its forge field.

  It is very unlikely that a script with the hash $\mathsf{adaID}$ will be found, and even less likely that it is a meaningful forging script that can ever validate. If this does happen, however, making a small change to the script, leaving its semantic meaning intact, will change its hash and likely allow the forge to take place.

- $\mathsf{adaToken}$ is a byte string representation of the word \"Ada\". The ledger should never allow the use of any other token name associated with Ada's currency ID

- $\mathsf{qu}$ and $\mathsf{co}$ are type conversions from quantity to coin. Both of these types are synonyms for $\Z$, so they are type re-naming conversions that are mutual inverses, with

  $\mathsf{qu} ~(\mathsf{co} ~q )~= ~q$, and

  $\mathsf{co}~ (\mathsf{qu}~ c) ~=~ c$, for $c \in \mathsf{Coin},~q \in \mathsf{Quantity}$.

- $\mathsf{coinToValue}$ takes a coin value and generates a $\mathsf{Value}$ type representation of it

An amount of Ada can also be represented as a multicurrency value using the notation in Figure 4, as $\mathsf{coinToValue}~c$ where $c \in \mathsf{Coin}$. We must use this representation when adding or subtracting Ada and other tokens as $\mathsf{Value}$, e.g. in the preservation of value calculations. However, we will abuse notation and write shorthand that $v ~\in~ \mathsf{Coin}$ is $\mathsf{True}$ when $v~ =~ \mathsf{coinToValue}~ c$ for some $c~\in~\mathsf{Coin}$.


*Abstract Functions and Values* $$\begin{align*}
    \mathsf{adaID} \in& ~\mathsf{PolicyID}
    & \text{Ada currency ID} \\
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

**Multicurrency**
**Plutus Script Validation** In Figure 5, abstract functions for script validation are presented.

- $\mathsf{valContext}$ constructs the validation context value passed to the script interpreter (all the necessary transaction and chain state data)

- $\mathsf{hashScript},~ \mathsf{hashData}$ are abstract hashing functions.

- $\mathsf{runMSigScript}$ (replacing $\mathsf{evaluateScript}$ in Shelley the ledger spec) performs validation for multi-sig scripts. This validation works exactly as before.

- $\mathsf{runPLCScript}$ performs validation for Plutus scripts. It takes the following arguments:

  - A cost model. The specific cost model is selected according to the Plutus version of the script, and is passed to allow the interpreter to do the correct conversion of the quantity of resource primitives the script validation computation used into $\mathsf{ExUnits}$. T

  - a list of (at most three) terms of type $\mathsf{Data}$ (the datum, redeemer, and the validation context).

  - the execution units budget (the maximum $\mathit{exunits}$ the validation is allowed to use)

  The script validation function outputs the pair of the validation result and the remaining execution units (after the ones used by script execution have been subtracted). Note that script exeuction stops if the full execution units budget has been spent before the validation is complete.

::: note
**Know your contract arguments** A Plutus validator script may receive either a list of three terms of type $\mathsf{Data}$, such as for output locking scripts, or two terms (redeemer and context, with no datum), such as in the rest of the Plutus scripts use cases. Contract authors must keep this in mind when writing contracts, as there is only one function (per Plutus version) to interface with the Plutus interpreter, that runs every kind of Plutus script - with no knowledge of what $\mathsf{Data}$ arguments are passed to it via this list.

*Abstract Script Validation Functions* $$\begin{align*}
     &\mathsf{hashScript} \in  ~\mathsf{Script}\to \mathsf{PolicyID} \\
     &\text{compute script hash} \\~\\
     &\mathsf{hashData} \in  ~\mathsf{Data} \to \mathsf{DataHash} \\
     &\text{compute hash of data} \\~\\
     &\mathsf{valContext} \in  \mathsf{UTxO} \to \mathsf{GoguenTx} \to \mathsf{CurItem} \to \mathsf{Data} \\
     &\text{build Validation Data} \\~\\
     &\mathsf{runMSigScript} \in\mathsf{ScriptMSig}\to \mathsf{GoguenTx} \to \mathsf{IsValidating}  \\
     &\text{validation of a multi-sig script} \\~\\
     &\mathsf{runPLCScript} \in \mathsf{CostMod} \to\mathsf{ScriptPlutus} \to
    \mathsf{Data}^{*} \to \mathsf{ExUnits} \to (\mathsf{IsValidating} \times \mathsf{ExUnits}) \\
     &\text{resource-restricted validation of a Plutus script}
\end{align*}$$ *Notation* $$\begin{align*}
    \llbracket \mathit{script_v} \rrbracket_{\mathit{cm},\mathit{exunits}}(\mathit{dataval},~\mathit{rdmr},~\mathit{ptx})
    &=& \mathsf{runPLCScript} ~{cm}~\mathit{script_v}~((\mathit{dataval};~\mathit{rdmr};~\mathit{ptx};\epsilon),~
    \mathit{exunits})
\end{align*}$$

**Script Validation, cont.**