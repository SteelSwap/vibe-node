# Transactions
Transactions are defined in Figure 1. A transaction body, $\mathsf{TxBody}$, is made up of eight pieces:

- A set of transaction inputs. This derived type identifies an output from a previous transaction. It consists of a transaction id and an index to uniquely identify the output.

- An indexed collection of transaction outputs. The $\mathsf{TxOut}$ type is an address paired with a coin value.

- A list of certificates, which will be explained in detail in Section sec:delegation-shelley.

- A transaction fee. This value will be added to the fee pot and eventually handed out as stake rewards.

- A time to live. A transaction will be deemed invalid if processed after this slot.

- A mapping of reward account withdrawals. The type $\mathsf{Wdrl}$ is a finite map that maps a reward address to the coin value to be withdrawn. The coin value must be equal to the full value contained in the account. Explicitly stating these values ensures that error messages can be precise about why a transaction is invalid. For reward calculation rules, see Section sec:reward-overview, and for the rule for collecting rewards, see Section sec:utxo-trans.

- An optional update proposals for the protocol parameters. The update system will be explained in Section sec:update.

- An optional metadata hash.

A transaction, $\mathsf{Tx}$, consists of:

- The transaction body.

- A triple of:

  - A finite map from payment verification keys to signatures.

  - A finite map containing scripts as values, with their hashes as their indexes.

  - Optional metadata.

Additionally, the $\mathsf{UTxO}$ type will be used by the ledger state to store all the unspent transaction outputs. It is a finite map from transaction inputs to transaction outputs that are available to be spent.

Finally, $\mathsf{txid}$ computes the transaction id of a given transaction. This function must produce a unique id for each unique transaction body.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{gkey} & \mathsf{VKeyGen} & \text{genesis public keys}\\
      \mathit{gkh} & \mathsf{KeyHashGen} & \text{genesis key hash}\\
      \mathit{txid} & \mathsf{TxId} & \text{transaction id}\\
      \mathit{m} & \mathsf{MetaDatum} & \text{metadatum}\\
      \mathit{mdh} & \mathsf{MetaDataHash} & \text{hash of transaction metadata}\\
    \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rllr}
      (\mathit{txid}, \mathit{ix})
      & \mathsf{TxIn}
      & \mathsf{TxId} \times \mathsf{Ix}
      & \text{transaction input}
      \\
      (\mathit{addr}, c)
      & \mathsf{TxOut}
      & \mathsf{Addr} \times \mathsf{Coin}
      & \text{transaction output}
      \\
      \mathit{utxo}
      & \mathsf{UTxO}
      & \mathsf{TxIn} \mapsto \mathsf{TxOut}
      & \text{unspent tx outputs}
      \\
      \mathit{wdrl}
      & \mathsf{Wdrl}
      & \mathsf{AddrRWD} \mapsto \mathsf{Coin}
      & \text{reward withdrawal}
      \\
      \mathit{md}
      & \mathsf{MetaData}
      & \N \mapsto \mathsf{MetaDatum}
      & \text{metadata}
    \end{array}
\end{equation*}$$ *Derived types (update system)* $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{pup}
      & \mathsf{ProposedPPUpdates}
      & \mathsf{KeyHashGen} \mapsto \mathsf{PParamsUpdate}
      & \text{proposed updates}
      \\
      \mathit{up}
      & \mathsf{Update}
      & \mathsf{ProposedPPUpdates} \times \mathsf{Epoch}
      & \text{update proposal}
    \end{array}
\end{equation*}$$ *Transaction Types* $$\begin{equation*}
    \begin{array}{rll}
      \mathit{txbody}
      & \mathsf{TxBody}
      & \begin{array}{l}
        \mathbb{P}~\mathsf{TxIn} \times (\mathsf{Ix} \mapsto \mathsf{TxOut}) \times \mathsf{DCert}^{*}
        \times \mathsf{Coin} \times \mathsf{Slot} \times \mathsf{Wdrl}
        \\ ~~~~\times \mathsf{Update}^? \times \mathsf{MetaDataHash}^?
        \end{array}
      \\
      \mathit{wit} & \mathsf{TxWitness} & (\mathsf{VKey} \mapsto \mathsf{Sig}) \times (\mathsf{HashScr} \mapsto \mathsf{Script})
      \\
      \mathit{tx}
      & \mathsf{Tx}
      & \mathsf{TxBody} \times \mathsf{TxWitness} \times \mathsf{MetaData}^?
    \end{array}
\end{equation*}$$ *Accessor Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{txins} & \mathsf{Tx} \to \mathbb{P}~\mathsf{TxIn} & \text{transaction inputs} \\
      \mathsf{txouts} & \mathsf{Tx} \to (\mathsf{Ix} \mapsto \mathsf{TxOut}) & \text{transaction outputs} \\
      \mathsf{txcerts} & \mathsf{Tx} \to \mathsf{DCert}^{*} & \text{delegation certificates} \\
      \mathsf{txfee} & \mathsf{Tx} \to \mathsf{Coin} & \text{transaction fee} \\
      \mathsf{txttl} & \mathsf{Tx} \to \mathsf{Slot} & \text{time to live} \\
      \mathsf{txwdrls} & \mathsf{Tx} \to \mathsf{Wdrl} & \text{withdrawals} \\
      \mathsf{txbody} & \mathsf{Tx} \to \mathsf{TxBody} & \text{transaction body}\\
      \mathsf{txwitsVKey} & \mathsf{Tx} \to (\mathsf{VKey} \mapsto \mathsf{Sig}) & \text{VKey witnesses} \\
      \mathsf{txwitsScript} & \mathsf{Tx} \to (\mathsf{HashScr} \mapsto \mathsf{Script}) & \text{script witnesses}\\
      \mathsf{txup} & \mathsf{Tx} \to \mathsf{Update}^? & \text{protocol parameter update}\\
      \mathsf{txMD} & \mathsf{Tx} \to \mathsf{MetaData}^? & \text{metadata}\\
      \mathsf{txMDhash} & \mathsf{Tx} \to \mathsf{MetaDataHash}^? & \text{metadata hash}\\
    \end{array}
\end{equation*}$$ *Abstract Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{txid}~ & \mathsf{TxBody} \to \mathsf{TxId} & \text{compute transaction id}\\
      \mathsf{validateScript} & \mathsf{Script} \to \mathsf{Tx} \to \mathsf{Bool} & \text{script interpreter}\\
      \mathsf{hashMD} & \mathsf{MetaData} \to \mathsf{MetaDataHash} & \text{hash the metadata}\\
      \mathsf{bootstrapAttrSize} & \mathsf{AddrBS} \to \N & \text{bootstrap attribute size}\\
    \end{array}
\end{equation*}$$

**Definitions used in the UTxO transition system**
*Helper Functions* $$\begin{align*}
    \mathsf{txinsVKey} & \in \powerset \mathsf{TxIn} \to \mathsf{UTxO} \to \powerset\mathsf{TxIn} & \text{VKey Tx inputs}\\
    \mathsf{txinsVKey} & ~\mathit{txins}~\mathit{utxo} =
    \mathit{txins} \cap \dom (\mathit{utxo} \rhd (\mathsf{AddrVKey} \times Coin))
    \\
    \\
    \mathsf{txinsScript} & \in \powerset \mathsf{TxIn} \to \mathsf{UTxO} \to \powerset\mathsf{TxIn} & \text{Script Tx inputs}\\
    \mathsf{txinsScript} & ~\mathit{txins}~\mathit{utxo} =
                        \mathit{txins} \cap \dom (\mathit{utxo} \rhd (\mathsf{AddrScr} \times Coin))
\end{align*}$$ $$\begin{align*}
    \mathsf{validateScript} & \in\mathsf{Script}\to\mathsf{Tx}\to\mathsf{Bool} & \text{validate
                                                      script} \\
    \mathsf{validateScript} & ~\mathit{msig}~\mathit{tx}=
                           \begin{cases}
                             \mathsf{evalMultiSigScript}~msig~vhks & \text{if}~msig \in\mathsf{MSig} \\
                             \mathsf{False} & \text{otherwise}
                           \end{cases} \\
                         & ~~~~\where \mathit{vhks}\mathrel{\mathop:}= \{\mathsf{hashKey}~vk \vert
                           vk \in \dom(\mathsf{txwitsVKey}~\mathit{tx})\}
\end{align*}$$

**Helper Functions for Transaction Inputs**
Figure 2 shows the helper functions $\mathsf{txinsVKey}$ and $\mathsf{txinsScript}$ which partition the set of transaction inputs of the transaction into those that are locked with a private key and those that are locked via a script. It also defines $\mathsf{validateScript}$, which validates the multisignature scripts.
