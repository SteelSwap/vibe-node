


*[Image from original source]*

# Introduction
Under some circumstances, multiple signatures may be required to authorise a transaction, for example, where an account is held in joint names or is a business account that is held by several business partners. Depending on the account, it may be that authorisation is required by all signatories or by a single signatory. This specification for a simple multi-signature scheme on the formal specification for the Shelley Cardano Ledger [@shelley_spec]. The main changes from that document are:

1.  Add a new address type for outputs, stake and rewards that require scripts;

2.  Add a new witness type to the transaction;

3.  Adapt the signature validation in such a way that funds that require a multi-signature script can be spent and delegation certificates that require multi-signature scripts can be used;

4.  Adapt the validation functions to the extended types of addresses, transaction inputs and to delegation certificates with scripts.

In this approach for multi-signature, the scripts will receive as input the set of all the keys that were used to sign the transaction. The script can then check this set against its own representation of valid combinations of keys that are permitted to unlock the unspent output. This design means that the scripts are completely stateless and therefore that no data needs to be supplied to the script apart from the information about which combinations of keys can legitimately sign the transaction. The design allows for any $n$ of $m$ signatures to be required for each unspent transaction output, where $m, n \ge 0$.

# Types
*Abstract types*

$$\begin{equation*}
    \begin{array}{rllr}
      script & \type{Script}& \type{Script}_{plc}\uniondistinct\type{Script}_{msig}\uniondistinct\,\,\cdots  & \text{Representation of a script}
    \end{array}
\end{equation*}$$

*Derived types*

$$\begin{equation*}
    \begin{array}{rllr}
      \var{addr_{s}} & \type{Addr^{script}}& \type{Addr_{base}^{script}}\uniondistinct \type{Addr_{enterprise}^{script}}
                              \uniondistinct \type{Addr_{ptr}^{script}}& \text{Script address} \\
      \var{addr_{vk}} & \type{Addr^{vkey}}& \begin{array}{ll}
                             \type{Addr^{vkey}_{base}}& \type{Addr^{vkey}_{ptr}}\uniondistinct \type{Addr^{vkey}_{enterprise}}\\
                                    & \type{Addr^{vkey}_{bootstrap}}
                           \end{array}
                                & \text{Key address}\\
      \var{addr} & \type{Addr}& \type{Addr^{script}}\uniondistinct \type{Addr^{vkey}}\\
      \var{addr_{rwd}} & \type{Addr_{rwd}}& (\type{Addr_{rwd}^{vkey}}\uniondistinct \type{Addr_{rwd}^{script}})
                                                         & \text{Reward address}
    \end{array}
\end{equation*}$$

*Accessor Functions*

$$\begin{equation*}
    \begin{array}{rlr}
      \fun{paymentHK} & \type{Addr^{vkey}}\to \type{KeyHash}_{pay}
      & \text{hash of payment key from addr}\\
      \fun{validatorHash} & \type{Addr^{script}}\to \type{ScriptHash}& \text{hash of validator
                                                    script} \\
      \fun{stakeCred_{b}} & (\type{Addr^{vkey}_{base}}\uniondistinct \type{Addr_{base}^{script}}) \to
                          \type{StakeCredential}& \text{stake credential from base
                                      addr}\\
      \fun{stakeCred_{r}} & \type{Addr_{rwd}}\to \type{StakeCredential}& \text{stake credential
                                                   from reward addr}\\
      \fun{addrPtr} & (\type{Addr^{vkey}_{ptr}}\uniondistinct \type{Addr_{ptr}^{script}}) \to \type{Ptr}&
                                                                         \text{pointer
                                                                         from
                                                                         pointer addr}
    \end{array}
\end{equation*}$$

*Abstract Functions*

$$\begin{equation*}
    \begin{array}{rlr}
      \fun{hashScript} & \type{Script}\to \type{ScriptHash}& \text{hash a serialized script}
    \end{array}
\end{equation*}$$

**Types for Scripts and Script Addresses**

In Figure 1 the $\type{Addr}$ type of the Cardano Ledger formal specification [@shelley_spec] is changed to include both public key and script addresses, split into the sub-types $\type{Addr^{vkey}}$ and $\type{Addr^{script}}$. Key addresses, of type $\type{Addr^{vkey}}$, are used as in the original specification; script addresses contain the hash of the validator script, and are used to lookup the script. The $\type{Script}$ type is partitioned into subtypes: here, $\type{Script}_{plc}$ for Plutus scripts, $\type{Script}_{msig}$ for native interpreter scripts (see Sections 4.1 and 4.2 for details).

A transaction output that requires a script carries the hash of the corresponding validator script. The output can only be spent if the matching script is provided and validates its input. The necessary information is carried by the $\type{Addr^{script}}$ sub-type of $\type{Addr}$ (Figure 1). This can therefore be part of a transaction output that consists of a pair of $\type{Addr}\times\type{Coin}$. Analogously to $\type{Addr^{vkey}}$, $\type{Addr^{script}}$ also has an *enterprise* script address sub-type which does not allow staking, as well as *base* and *pointer* script address sub-types. We will refer to the parts of an address that is used for payment as the *payment object* and the part that is used for staking as the *staking reference*. Analogously to the payment object, the staking reference for an $\type{Addr^{script}}$ is also a script. This means that staking can also require a combination of signatures and these may be different from the combination of signatures that is required for payment.

The $\fun{hashScript}$ function calculates the hash of the serialized script. The accessor function $\fun{validatorHash}$ returns the hash of a script address. The domain of the accessor function $\fun{paymentHK}$ is changed to public key addresses. The domains of the accessor functions $\fun{stakeHK_b}$, $\fun{stakeHK_{r}}$ and $\fun{addrPtr}$ are extended to also include the respective script address variants. The return types are changed to be a staking reference.


*Transaction Type*

$$\begin{equation*}
    \begin{array}{rll}
      \var{wit} & \type{TxWitness}& (\type{VKey}\mapsto \type{Sig}, \type{ScriptHash}\mapsto \type{Script})
      \\
      \var{tx}
      & \type{Tx}
      & \type{TxBody}\times \type{TxWitness}
      \\
    \end{array}
\end{equation*}$$

*Accessor Functions*

$$\begin{equation*}
    \begin{array}{rlr}
      \fun{txwitsVKey} & \type{Tx}\to (\type{VKey}\mapsto \type{Sig}) & \text{VKey witnesses} \\
      \fun{txwitsScript} & \type{Tx}\to (\type{ScriptHash}\mapsto \type{Script}) & \text{script witnesses}
    \end{array}
\end{equation*}$$

*Abstract Functions*

$$\begin{equation*}
    \begin{array}{rlr}
      \fun{validateScript} & \type{Script}\to (\type{Tx}\to \mathbb{B}) & \text{script interpreter}
    \end{array}
\end{equation*}$$

**Types for Transaction Inputs with Scripts**

Figure 2 extends the type of a transaction as defined in the formal ledger specification [@shelley_spec] to carry an additional witness type. This is achieved by explicitly defining $\type{TxWitness}$ to be a pair of a public key witness and a script witness. The accessor function $\fun{txwits}$ is renamed to $\fun{txwitsVKey}$. The new accessor function $\fun{txwitsScript}$ returns a map of script hashes to scripts. In order for a transaction to be accepted, all the corresponding scripts need to validate the transaction.


*Classification Functions* $$\begin{align*}
    \fun{txinsVKey} & \in \powerset \type{TxIn}\to \type{UTxO}\to \powerset\type{TxIn}& \text{VKey Tx inputs}\\
    \fun{txinsVKey} & ~\var{txins}~\var{utxo} =
    \var{txins} \cap \dom (\var{utxo} \restrictrange (\type{Addr^{vkey}}\times Coin))
    \\
    \\
    \fun{txinsScript} & \in \powerset \type{TxIn}\to \type{UTxO}\to \powerset\type{TxIn}& \text{Script Tx inputs}\\
    \fun{txinsScript} & ~\var{txins}~\var{utxo} =
                        \var{txins} \cap \dom (\var{utxo} \restrictrange (\type{Addr^{script}}\times Coin))
\end{align*}$$

**Key/Script Classification Functions**

Figure 3 shows the $\fun{txinsVKey}$ and $\fun{txinsScript}$ scripts, which partition the set of transaction inputs of the transaction into those that require a private key and those that require a multi-signature script, respectively.

# Ledger Transitions for Multi-Signature
While spending transaction outputs and altering delegation decisions can both require multi-signature scripts, script validation can be treated in the same way for both cases. The validation of all witnesses occurs through the UTXOW STS rule, using the function to collect all the necessary key signatures and the function to collect all necessary multi-signature scripts.

## Delegation Specific Changes
Staking using multiple signatures requires a change to the type of staking reference from just a hashed key to either a hashed key or a hashed script. This is reflected in the type of $\type{StakeCreds}$ (which replaces the previous $\type{StakeKeys}$ type) and the new $\type{StakeCredential}$ type, as shown in Figure 4.


*Delegation Types* $$\begin{equation*}
      \begin{array}{rllr}
        \var{stakeCred} & \type{StakeCredential}& (\type{KeyHash}_{stake} \uniondistinct
                                            \type{ScriptHash}) \\
        \var{regCreds} & \type{StakeCreds}& \type{StakeCredential}\mapsto \type{Slot}\\
      \end{array}
\end{equation*}$$ *Delegation States* $$\begin{equation*}
    \begin{array}{l}
    \type{DState}=
    \left(\begin{array}{rlr}
      \var{stkCreds} & \type{StakeCreds}& \text{registered stake delegators}\\
      \var{rewards} & \type{Addr_{rwd}}\mapsto \type{Coin}& \text{rewards}\\
      \var{delegations} & \type{StakeCredential}\mapsto \type{KeyHash}_{pool} & \text{delegations}\\
      \var{ptrs} & \type{Ptr}\mapsto \type{StakeCredential}& \text{pointer to staking reference}\\
      \var{fGenDelegs} & (\type{Slot}\times\type{VKey_G}) \mapsto \type{VKey}& \text{future genesis key delegations}\\
      \var{genDelegs} & \type{VKey_G}\mapsto \type{VKey}& \text{genesis key delegations}\\
          \end{array}\right)
    \end{array}
\end{equation*}$$ *Certificate Accessor functions* $$\begin{equation*}
  \begin{array}{rlr}
    \fun{cwitness}~ \var{} & \type{DCert}\to \type{StakeCreds}& \text{certificate witness}
  \end{array}
\end{equation*}$$

**Delegation State type**

**Note:** In contrast to staking reference delegation, staking pools themselves cannot use multi-signature schemes. Otherwise, the lightweight certificates that are used for delegation from the pool to the KES hot keys would also need to be script witnesses. This is undesirable since these certificates need to be included in each header, but headers are required to have a minimal and fixed size.

## UTXOW Transition Rule
The UTXOW extended transition system of [@shelley_spec] is shown in Figure 5. The constraint on the set of required witnesses is relaxed in such a way that *redundant* signatures can be supplied in the transaction. The set of verification keys is passed to the validator script via the concrete implementation of $\fun{validateScript}$ for the specific script type. The set of all validator scripts of $\fun{txwitsScript}~(\fun{txins}~tx)$ is checked for:

1.  equality of the hashed script with the hash that is stored in the output to spent;

2.  that the script validates the transaction; and

3.  that it is precisely the set of the scripts required for the transaction (as returned from $\fun{scriptsNeeded}$).


$$\begin{equation}
    \inference[UTxO-wit]
    {
      (utxo, \underline{\phantom{a}}, \underline{\phantom{a}}) \mathrel{\mathop:=}\var{utxoSt} \\~\\
            \forall \var{hs} \mapsto \var{validator} \in \fun{txwitsScript}~{tx},\\
      \fun{hashScript}~\var{validator} = \var{hs} \wedge
      \fun{validateScript}~\var{validator}~\var{tx}\\~\\
      \fun{scriptsNeeded}~\var{utxo}~\var{tx} = \dom (\fun{txwitsScript}~{tx})
      \\~\\
      \forall \var{vk} \mapsto \sigma \in \fun{txwitsVKey}~\var{tx},
      \mathcal{V}_{\var{vk}}{\llbracket \var{\fun{txbody}~ \var{tx}} \rrbracket}_{\sigma} \\
      \fun{witsVKeyNeeded}~{utxo}~{tx} \subseteq \{ \fun{hashKey}~ \var{\var}{vk} \mid
      \var{vk}\in\dom{(\fun{txwitsVKey}~\var{tx})} \}\\~\\
      {
        \begin{array}{l}
        \var{utxoEnv}
        \end{array}
      }
      \vdash \var{utxoSt} \trans{\hyperref[fig:rules:utxo-shelley]{utxo}}{tx} \var{utxoSt'}\\
    }
    {
      \begin{array}{l}
        \var{utxoEnv}
      \end{array}
      \vdash \var{utxoSt} \trans{utxow}{tx} \varUpdate{\var{utxoSt'}}
    }
\end{equation}$$

**UTxO with Witnesses and Multi-Signatures**

Multi-signature staking also causes reward accounts to be locked by a multi-signature scheme. This means that in order to allow for spending of rewards accumulated in a multi-signature rewards account, we also need to validate the required script. This is done in a predicate in the UTXOW rule which checks that for each withdrawal of a transaction which uses a multi-script rewards account, there exists a corresponding script that matches the hash in the reward address and that also validates the transaction. Because of the changes to the staking reference type, the original function $\fun{witsNeeded}$ is changed as shown in Figure 6. Figure 6 also shows the function $\fun{scriptNeeded}$ that computes the required script hashes from the set of spent inputs that are locked by scripts and the consumed withdrawals that are locked by scripts.


$$\begin{align*}
    & \hspace{-0.8cm}\fun{witsVKeyNeeded} \in \type{UTxO}\to \type{Tx}\to (\type{VKey_G}\mapsto\type{VKey}) \to
      \powerset{\type{KeyHash}}
    & \text{required keyhashes} \\
    &  \hspace{-0.8cm}\fun{witsVKeyNeeded}~\var{utxo}~\var{tx}~\var{dms} = \\
    & ~~\{ \fun{paymentHK}~a \mid i \mapsto (a, \underline{\phantom{a}}) \in \var{utxo},~i\in\fun{txinsVKey}~{tx} \} \\
    \cup & ~~
           \left(\{\fun{stakeCred_r}~a\mid a\mapsto \underline{\phantom{a}}\in \type{Addr_{rwd}^{vkey}}
      \restrictdom \fun{txwdrls}~ \var{tx}\} \cap \type{KeyHash}_{Stake}  \right)\\
    \cup & ~~\{\fun{cwitness}~ \var{c} \mid c \in \fun{txcerts}~ \var{tx}\}~\cup \\
    \cup & ~~\fun{propWits}~(\fun{txup}~\var{tx}) \\
    \cup & ~~\bigcup_{\substack{c \in \fun{txcerts}~ \var{tx} \\ ~c \in\type{DCert_{regpool}}}} \fun{poolOwners}~{c}
\end{align*}$$ $$\begin{align*}
    & \hspace{-0.5cm}\fun{scriptsNeeded} \in \type{UTxO}\to \type{Tx}\to
      \powerset{\type{ScriptHash}}
    & \text{required script hashes} \\
    &  \hspace{-0.5cm}\fun{scriptsNeeded}~\var{utxo}~\var{tx} = \\
    & ~~\{ \fun{validatorHash}~a \mid i \mapsto (a, \underline{\phantom{a}}) \in \var{utxo},\\
    & ~~~~~i\in\fun{txinsScript}~{(\fun{txins~\var{tx}})}~{utxo}\} \\
    \cup & ~~\left(\{ \fun{stakeCred_{r}}~\var{a} \mid a \in \dom (\type{Addr_{rwd}^{script}}
           \restrictdom \fun{txwdrls}~\var{tx}) \} \cap \type{ScriptHash}\right) \\
    \cup & ~~\{\type{Addr^{script}}\cap \fun{cwitness}~\var{c} \mid c \in \fun{txcerts}~\var{tx}\}
\end{align*}$$

**Required Witnesses**

# Implementation of Script-Based Multi-Signature
There are different implementation possibilities for the introduced multi-signature scheme. Section 4.1 describes an implementation based on Plutus [@plutus_eutxo] which uses only simple scripts, without redeemer or data scripts. Section 4.2 describes an alternative implementation that supports validation using a native implementation for a script-like DSL.

## Plutus Scripts
*Abstract Type*

$$\begin{equation*}
    \begin{array}{rlr}
      pendingTx & \type{PendingTx}& \text{information about pending Tx}
    \end{array}
\end{equation*}$$

*Abstract Functions*

$$\begin{equation*}
    \begin{array}{rlr}
      \fun{validateScript} & \type{Script}_{plc}\to (\type{Tx}\to \mathbb{B}) & \text{Plutus script
                                                               interpreter} \\
      \fun{validate} & () \to () \to (\type{PendingTx}\to \mathbb{B}) & \text{Plutus
                                                            validator script type}
    \end{array}
\end{equation*}$$

**Implementation based on Plutus Scripts**

$\type{PendingTx}$ is a representation of the pending transaction. In particular, this information contains the set of keys that signed the transaction. The function $\fun{txPending}$ constructs the necessary information about a transaction which can be passed as value of type $\type{PendingTx}$ to the validator script.

In order to spend funds locked by a multi-signature script, the validator scripts need to validate the transaction. The abstract function $\fun{validate}$ corresponds to such a Plutus validator script. Its type consists of two parameters of unit type and one parameter of type $\type{PendingTx}$; its return type is Boolean. The first two input parameters correspond to the redeemer and the data scripts which are used in the full extended UTxO model for Plutus [@plutus_eutxo]. As those values are not required for simple multi-signature, we use the unit type for them. The Boolean return type signals whether the script succeeded in validating the transaction. The function $\fun{validateScript}$ specialized for $\type{Script}_{plc}$ takes a Plutus script representation and a $\type{PendingTx}$ value, and evaluates the script using the Plutus interpreter.

The following is a possible Plutus implementation of a simple $m$ out of $n$ multi-signature validation script. The type $\type{MultiSig}$ is a list of keys and a threshold value.

    import qualified Language.PlutusTx            as P
    import           Ledger.Validation            as V

    data MultiSig = MultiSig
                    { signatories :: [Ledger.PubKey]
                    -- ^ List of public keys of people who may sign the transaction
                    , requiredSignatures :: Integer
                    -- ^ Minimum number of signatures required to unlock
                    --   the output (should not exceed @length signatories@)
                    --   n.b., should also check that this is >= 0
                    }

    validate :: MultiSig -> () -> () -> PendingTx -> Bool
    validate multiSig@(MultiSig keys num) () () p =
        let present = P.length (P.filter (V.txSignedBy p) keys)
        in present `P.geq` num

The above Plutus script takes a parameter of type $\type{MultiSig}$. This is a list of keys $\var{keys}$ and a threshold $num$ that indicates how many of the keys are required as signatures. When the validation script is called, it computes the length of the list of keys in $keys$ which correctly signed the transaction. If this number is greater than or equal to *num*, then sufficient signatures are present. It follows that, since is a value of type , partial application of $\fun{validate}~multisig$ will return a correctly typed validator script as defined by Figure 7.

## Native Script Interpreter
*MultiSig Type*

$$\begin{equation*}
    \begin{array}{rll}
      \var{msig} & \in & \type{RequireSig}~\type{KeyHash}\\
      & \uniondistinct &
         \type{RequireAllOf}~[\type{Script}_{msig}] \\
      & \uniondistinct&
         \type{RequireAnyOf}~[\type{Script}_{msig}] \\
      & \uniondistinct&
        \type{RequireMOf}~\mathbb{N}~[\type{Script}_{msig}]
    \end{array}
\end{equation*}$$

*Functions*

$$\begin{align*}
    \fun{validateScript} & \in\type{Script}_{msig}\to\type{Tx}\to\mathbb{B}& \text{validate native
                                                          script} \\
    \fun{validateScript} & ~\var{msig}~\var{tx}= \\
                         & \textrm{let}~\var{vhks}\mathrel{\mathop:=}\{\fun{hashKey}~vk \vert
                           vk \in \fun{txwitsVKey}~\var{tx}\} \\
                         & \fun{evalMultiSigScript}~msig~vhks\\
\end{align*}$$ $$\begin{align*}
    \fun{evalMultiSigScript} & \in\type{Script}_{msig}\to\powerset\type{KeyHash}\to\mathbb{B}& \\
    \fun{evalMultiSigScript} & ~(\type{RequireSig}~hk)~\var{vhks} =  hk \in vhks \\
    \fun{evalMultiSigScript} & ~(\type{RequireAllOf}~ts)~\var{vhks} =
                              \forall t \in ts: \fun{evalMultiSigScript}~t~vhks\\
    \fun{evalMultiSigScript} & ~(\type{RequireAnyOf}~ts)~\var{vhks} =
                              \exists t \in ts: \fun{evalMultiSigScript}~t~vhks\\
    \fun{evalMultiSigScript} & ~(\type{RequireMOf}~m~ts)~\var{vhks} = \\
                             & m \leq \Sigma
                               (\textrm{card} \{ t s.t. t \leftarrow ts \wedge \fun{evalMultiSigScript}~\var{t}~\var{vhks}
%                               \left(
%                               [\textrm{if}~(\fun{evalMultiSigScript}~\var{t}~\var{vhks})~
%                               \textrm{then}~1~\textrm{else}~0\vert t \leftarrow ts]
%                               \right)
\end{align*}$$

**Implementation based on Native Scripts**

An alternative implementation for multi-signature scripts is an embedding of the script as a data type that can then be interpreted directly. Figure 8 shows the types and functions that are needed for such a native script implementation. The type $\type{Script}_{msig}$ is defined as a tree-structure which is either a single signature leaf node or a list of values of type $\type{Script}_{msig}$. This either requires all signatures to be validated, at least one of the signatures to be validated, or at least the threshold value of $m$ signatures to be validated.

## Lower Level Implementation Details
For each new type of witness, there will be a requirement to represent such a witness on-chain and allow for identification when deserializing such a witness. For this, there will be a language-specific tag for each witness (and staking reference) in its serialized form. This tag will also be part of the hash to allow for easy identification of the language type.

As an example, one could tag key hash payment object and staking references with the tag $0$, native multi-signature scripts with the tag $1$, and simple Plutus scripts with the tag $2$. Every new language would require a new tag. Changes to the payment or staking reference details that are treated *within* an existing language framework would be changed via a software update, rather than an additional tag.

# Summary
The script-based multi-signature scheme that is presented here does not require the scripts to use any cryptographic primitives. Rather, it requires only the ability to compare the required keys to those that actually signed the transaction. The worst-case potential calculation cost can therefore be calculated statically in advance and can be added to the transaction fees or as gas cost. The scripts can be realized with only limited functionality requirements for the script language. The necessary extensions to the data types in the Shelley specification [@shelley_spec] are relatively simple. They consist mainly of introducing additional optional data types for payment objects or staking references.

The relaxation on accepting a superset of the strictly required signatures potentially allows the creation of transactions with an arbitrary number of signatures. This could then be a possible attack vector. The number of signatures should be taken into account in some way in the calculation of the transaction fee.

There are two proposed implementation schemes, one based on Plutus, the other on a script-like integration as DSL for a native interpreter. Both follow the same strategy for integration: extending addresses, defining witnesses and specializing the script validation function. If the Plutus approach is not viable for any reason, e.g., script size or readiness of library, only the native script implementation could be pursued instead.
