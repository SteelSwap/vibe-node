# Update Proposal Mechanism

figure*[h]
AgdaMultiCode
```agda
GenesisDelegation = KeyHash ⇀ (KeyHash × KeyHash)

record PPUpdateState : Type where
  field
    pup   : ProposedPPUpdates
    fpup  : ProposedPPUpdates

record PPUpdateEnv : Type where
  field
    slot       : Slot
    pparams    : PParams
    genDelegs  : GenesisDelegation
```
AgdaMultiCode
PPUP types
figure*
figure*[h]
```agda
viablePParams : PParams → Type
viablePParams pp = ⊤ -- TODO: block size check

isViableUpdate : PParams → PParamsUpdate → Type
isViableUpdate pp pup with applyUpdate pp pup
... | pp' = pvCanFollow (PParams.pv pp) (PParams.pv pp') × viablePParams pp'
```
Definitions for PPUP
figure*
figure*[h]
```agda
  PPUpdateEmpty : Γ ⊢ s ⇀⦇ nothing ,PPUP⦈ s

  PPUpdateCurrent : let open PPUpdateEnv Γ in
    dom pup ⊆ dom genDelegs
    → All (isViableUpdate pparams) (range pup)
    → slot + 2 * StabilityWindow < firstSlot (epoch slot + 1)
    → epoch slot ≡ e
    ────────────────────────────────
    Γ ⊢ record { pup = pupˢ ; fpup = fpupˢ } ⇀⦇ just (pup , e) ,PPUP⦈
        record { pup = pup ∪ˡ pupˢ ; fpup = fpupˢ }

  PPUpdateFuture : let open PPUpdateEnv Γ in
    dom pup ⊆ dom genDelegs
    → All (isViableUpdate pparams) (range pup)
    → firstSlot (epoch slot + 1) ≤ slot + 2 * StabilityWindow
    → epoch slot + 1 ≡ e
    ────────────────────────────────
    Γ ⊢ record { pup = pupˢ ; fpup = fpupˢ } ⇀⦇ just (pup , e) ,PPUP⦈
        record { pup = pupˢ ; fpup = pup ∪ˡ fpupˢ }
```
PPUP inference rules
figure*
