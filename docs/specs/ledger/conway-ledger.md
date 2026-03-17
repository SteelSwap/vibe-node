# Ledger
sec:ledger
\LedgerModule{Ledger}, where the entire state transformation of the
ledger state caused by a valid transaction can now be given as a combination of the
previously defined transition systems.

Conway
As there is nothing new to the Conway era in this part of the ledger, we do not
present any details of the Agda formalization.
%% TODO: we need a way to reference the latest full spec
Conway


figure*[ht]
AgdaMultiCode
```agda
record LEnv : Type where
  field
    slot        : Slot
    ppolicy     : Maybe ScriptHash
    pparams     : PParams
    enactState  : EnactState
    treasury    : Coin
```
```agda


record LState : Type where
```
```agda
  field
    utxoSt     : UTxOState
    govSt      : GovState
    certState  : CertState

```
```agda
txgov : TxBody → List (GovVote ⊎ GovProposal)
txgov txb = map inj₂ txprop ++ map inj₁ txvote
  where open TxBody txb

rmOrphanDRepVotes : CertState → GovState → GovState
rmOrphanDRepVotes cs govSt = L.map (map₂ go) govSt
  where
   ifDRepRegistered : Voter → Type
   ifDRepRegistered (r , c) = r ≡ DRep → c ∈ dom (cs .gState .dreps)

   go : GovActionState → GovActionState
   go gas = record gas { votes = filterKeys ifDRepRegistered (gas .votes) }

allColdCreds : GovState → EnactState → ℙ Credential
allColdCreds govSt es =
  ccCreds (es .cc) ∪ concatMapˢ (λ (_ , st) → proposedCC (st .action)) (fromList govSt)
```
AgdaMultiCode
Types and functions for the LEDGER transition system
figure*

figure*[ht]
AgdaMultiCode
```agda
data _⊢_⇀⦇_,LEDGER⦈_ : LEnv → LState → Tx → LState → Type where

  LEDGER-V :
    let  txb         = tx .body
```
```agda
         rewards     = certState .dState .rewards
    in
    ∙ isValid tx ≡ true
    ∙ ⟦ slot , pp , treasury ⟧  ⊢ utxoSt ⇀⦇ tx ,UTXOW⦈ utxoSt'
    ∙ ⟦ epoch slot , pp , txvote , txwdrls , allColdCreds govSt enactState ⟧ ⊢ certState ⇀⦇ txcerts ,CERTS⦈ certState'
    ∙ ⟦ txid , epoch slot , pp , ppolicy , enactState , certState' , dom rewards ⟧ ⊢ rmOrphanDRepVotes certState' govSt ⇀⦇ txgov txb ,GOVS⦈ govSt'
      ────────────────────────────────
      ⟦ slot , ppolicy , pp , enactState , treasury ⟧ ⊢ ⟦ utxoSt , govSt , certState ⟧ ⇀⦇ tx ,LEDGER⦈ ⟦ utxoSt' , govSt' , certState' ⟧

  LEDGER-I :
    ∙ isValid tx ≡ false
    ∙ ⟦ slot , pp , treasury ⟧ ⊢ utxoSt ⇀⦇ tx ,UTXOW⦈ utxoSt'
      ────────────────────────────────
      ⟦ slot , ppolicy , pp , enactState , treasury ⟧ ⊢ ⟦ utxoSt , govSt , certState ⟧ ⇀⦇ tx ,LEDGER⦈ ⟦ utxoSt' , govSt , certState ⟧
```
AgdaMultiCode
LEDGER transition system
figure*

NoConway
figure*[h]
```agda
_⊢_⇀⦇_,LEDGERS⦈_ : LEnv → LState → List Tx → LState → Type
_⊢_⇀⦇_,LEDGERS⦈_ = ReflexiveTransitiveClosure {sts = _⊢_⇀⦇_,LEDGER⦈_}
```
LEDGERS transition system
figure*
NoConway
