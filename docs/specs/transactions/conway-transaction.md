# Transactions
sec:transactions
\mathsf{LedgerModule}{Transaction}, where we define transactions.

 A transaction consists of a transaction body, a collection of witnesses and some optional auxiliary
data.


NoConway
Some key ingredients in the transaction body are:
itemize
  \item A set  of transaction inputs, each of which identifies an output from
    a previous transaction.  A transaction input consists of a transaction id and an
    index to uniquely identify the output.
  \item An indexed collection  of transaction outputs.
    The  type is an address paired with a coin value.
  \item A transaction fee. This value will be added to the fee pot.
  \item The size  and the hash  of the serialized form of the
    transaction that was included in the block.
itemize
NoConway
Conway
Ingredients of the transaction body introduced in the Conway era are the following:
itemize
  \item , the list of votes for goverance actions;
  \item , the list of governance proposals;
  \item , amount of  to donate to treasury, e.g., to return money
    to the treasury after a governance action;
  \item , the current value of the treasury. This field serves as a
    precondition to executing Plutus scripts that access the value of the treasury.
itemize
Conway

figure*[ht]
*Abstract types*
```agda
    Ix TxId AuxiliaryData : Type

```
NoConway
*Derived types*
```agda
  TxIn     = TxId × Ix
  TxOut    = Addr × Value × Maybe (Datum ⊎ DataHash) × Maybe Script
  UTxO     = TxIn ⇀ TxOut
  Wdrl     = RwdAddr ⇀ Coin
  RdmrPtr  = Tag × Ix

  ProposedPPUpdates  = KeyHash ⇀ PParamsUpdate
  Update             = ProposedPPUpdates × Epoch
```
NoConway
*Transaction types*
AgdaMultiCode
```agda
  record TxBody : Type where
    field
      txins          : ℙ TxIn
      refInputs      : ℙ TxIn
      txouts         : Ix ⇀ TxOut
      txfee          : Coin
      mint           : Value
      txvldt         : Maybe Slot × Maybe Slot
      txcerts        : List DCert
      txwdrls        : Wdrl
      txvote         : List GovVote
      txprop         : List GovProposal
      txdonation     : Coin
      txup           : Maybe Update
      txADhash       : Maybe ADHash
      txNetworkId    : Maybe Network
      curTreasury    : Maybe Coin
      txsize         : ℕ
      txid           : TxId
      collateral     : ℙ TxIn
      reqSigHash     : ℙ KeyHash
      scriptIntHash  : Maybe ScriptHash
```

NoConway
```agda
  record TxWitnesses : Type where
    field
      vkSigs   : VKey ⇀ Sig
      scripts  : ℙ Script
      txdats   : DataHash ⇀ Datum
      txrdmrs  : RdmrPtr  ⇀ Redeemer × ExUnits

    scriptsP1 : ℙ P1Script
    scriptsP1 = mapPartial isInj₁ scripts

  record Tx : Type where
    field
      body     : TxBody
      wits     : TxWitnesses
      isValid  : Bool
      txAD     : Maybe AuxiliaryData
```
NoConway
AgdaMultiCode
Transactions and related types
fig:defs:transactions
figure*

NoConway
figure*[ht]
AgdaMultiCode
```agda
  getValue : TxOut → Value
  getValue (_ , v , _) = v

  TxOutʰ = Addr × Value × Maybe (Datum ⊎ DataHash) × Maybe ScriptHash

  txOutHash : TxOut → TxOutʰ
  txOutHash (a , v , d , s) = a , (v , (d , M.map hash s))

  getValueʰ : TxOutʰ → Value
  getValueʰ (_ , v , _) = v

  txinsVKey : ℙ TxIn → UTxO → ℙ TxIn
  txinsVKey txins utxo = txins ∩ dom (utxo ∣^' (isVKeyAddr ∘ proj₁))

  scriptOuts : UTxO → UTxO
  scriptOuts utxo = filter (λ (_ , addr , _) → isScriptAddr addr) utxo

  txinsScript : ℙ TxIn → UTxO → ℙ TxIn
  txinsScript txins utxo = txins ∩ dom (proj₁ (scriptOuts utxo))

  refScripts : Tx → UTxO → List Script
  refScripts tx utxo =
    mapMaybe (proj₂ ∘ proj₂ ∘ proj₂) $ setToList (range (utxo ∣ (txins ∪ refInputs)))
    where open Tx; open TxBody (tx .body)

  txscripts : Tx → UTxO → ℙ Script
  txscripts tx utxo = scripts (tx .wits) ∪ fromList (refScripts tx utxo)
    where open Tx; open TxWitnesses

  lookupScriptHash : ScriptHash → Tx → UTxO → Maybe Script
  lookupScriptHash sh tx utxo =
    if sh ∈ mapˢ proj₁ (m ˢ) then
      just (lookupᵐ m sh)
    else
      nothing
    where m = setToMap (mapˢ < hash , id > (txscripts tx utxo))
```
AgdaMultiCode
Functions related to transactions
fig:defs:transaction-funs
figure*
NoConway

