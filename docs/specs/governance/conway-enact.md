# Enactment
sec:enactment
\LedgerModule{Enact}


fig:enact-defs contains some definitions required to
define the ENACT transition system.   is the environment and
 the state of ENACT, which enacts a governance action. All
governance actions except  and  modify 
permanently, which of course can have further
consequences.   accumulates withdrawal temporarily in the
 field of ,
but this information is applied and reset in EPOCH (see fig:epoch:sts).
Also, enacting these governance actions is the
*only* way of modifying .

Note that all other fields of  also contain a 
since they are .

figure*[ht]
AgdaMultiCode
```agda
record EnactEnv : Type where
  field
    gid       : GovActionID
    treasury  : Coin
    epoch     : Epoch

record EnactState : Type where
  field
    cc            : HashProtected (Maybe ((Credential ⇀ Epoch) × ℚ))
    constitution  : HashProtected (DocHash × Maybe ScriptHash)
    pv            : HashProtected ProtVer
    pparams       : HashProtected PParams
    withdrawals   : RwdAddr ⇀ Coin
```
```agda

ccCreds : HashProtected (Maybe ((Credential ⇀ Epoch) × ℚ)) → ℙ Credential
ccCreds (just x   , _)  = dom (x .proj₁)
ccCreds (nothing  , _)  = ∅

getHash : ∀ {a} → NeedsHash a → Maybe GovActionID
getHash {NoConfidence}     h = just h
getHash {UpdateCommittee}  h = just h
getHash {NewConstitution}  h = just h
getHash {TriggerHF}        h = just h
getHash {ChangePParams}    h = just h
getHash {TreasuryWdrl}     _ = nothing
getHash {Info}             _ = nothing

getHashES : EnactState → GovActionType → Maybe GovActionID
getHashES es NoConfidence       = just (es .cc .proj₂)
getHashES es (UpdateCommittee)  = just (es .cc .proj₂)
getHashES es (NewConstitution)  = just (es .constitution .proj₂)
getHashES es (TriggerHF)        = just (es .pv .proj₂)
getHashES es (ChangePParams)    = just (es .pparams .proj₂)
getHashES es (TreasuryWdrl)     = nothing
getHashES es Info               = nothing
```
*Type of the ENACT transition system*
```agda
  _⊢_⇀⦇_,ENACT⦈_ : EnactEnv → EnactState → GovAction → EnactState → Type
```
AgdaMultiCode
Types and function used for the ENACT transition system
fig:enact-defs
figure*

fig:sts:enact,fig:sts:enact-cont define the rules of the ENACT transition
system. Usually no preconditions are checked and the state is simply
updated (including the  for the hash protection scheme, if
required). The exceptions are  and :
itemize
  \item  requires that maximum terms are respected, and
  \item  requires that the treasury is able to cover the sum of all withdrawals (old and new).
itemize

figure*[ht]
AgdaMultiCode
```agda
  Enact-NoConf :
    ───────────────────────────────────────
    ⟦ gid , t , e ⟧ ⊢ s ⇀⦇ ⟦ NoConfidence , _ ⟧ᵍᵃ ,ENACT⦈ record s { cc = nothing , gid }

  Enact-UpdComm : let old      = maybe proj₁ ∅ (s .cc .proj₁)
                      maxTerm  = ccMaxTermLengthOf s +ᵉ e
                  in
    ∀[ term ∈ range new ] term ≤ maxTerm
    ───────────────────────────────────────
    ⟦ gid , t , e ⟧ ⊢ s ⇀⦇ ⟦ UpdateCommittee , (new , rem , q) ⟧ᵍᵃ ,ENACT⦈
      record s { cc = just ((new ∪ˡ old) ∣ rem ᶜ , q) , gid }

  Enact-NewConst :
    ───────────────────────────────────────
    ⟦ gid , t , e ⟧ ⊢ s ⇀⦇ ⟦ NewConstitution , (dh , sh) ⟧ᵍᵃ ,ENACT⦈ record s { constitution = (dh , sh) , gid }
```
AgdaMultiCode
ENACT transition system
fig:sts:enact
figure*
figure*[ht]
AgdaMultiCode
```agda
  Enact-HF :
    ───────────────────────────────────────
    ⟦ gid , t , e ⟧ ⊢ s ⇀⦇ ⟦ TriggerHF , v ⟧ᵍᵃ ,ENACT⦈ record s { pv = v , gid }

  Enact-PParams :
    ───────────────────────────────────────
    ⟦ gid , t , e ⟧ ⊢ s ⇀⦇ ⟦ ChangePParams , up ⟧ᵍᵃ ,ENACT⦈
      record s { pparams = applyUpdate (PParamsOf s) up , gid }

  Enact-Wdrl : let newWdrls = s .withdrawals ∪⁺ wdrl in
    ∑[ x ← newWdrls ] x ≤ t
    ───────────────────────────────────────
    ⟦ gid , t , e ⟧ ⊢ s ⇀⦇ ⟦ TreasuryWdrl , wdrl ⟧ᵍᵃ ,ENACT⦈ record s { withdrawals = newWdrls }

  Enact-Info :
    ───────────────────────────────────────
    ⟦ gid , t , e ⟧ ⊢ s ⇀⦇ ⟦ Info , _ ⟧ᵍᵃ ,ENACT⦈ s
```
AgdaMultiCode
ENACT transition system (continued)
fig:sts:enact-cont
figure*
