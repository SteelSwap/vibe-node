# Protocol Parameters Update

figure*[h]
AgdaMultiCode
```agda
record NewPParamState : Type where
  field
    pparams  : PParams
    ppup     : PPUpdateState

updatePPUp : PParams → PPUpdateState → PPUpdateState
updatePPUp pparams record { fpup = fpup }
  with allᵇ ¿ isViableUpdate pparams ¿¹ (range fpup)
... | false  = record { pup = ∅ᵐ    ; fpup = ∅ᵐ }
... | true   = record { pup = fpup  ; fpup = ∅ᵐ }

votedValue : ProposedPPUpdates → PParams → ℕ → Maybe PParamsUpdate
votedValue pup pparams quorum =
  case any? (λ u → lengthˢ (pup ∣^ fromList [ u ]) ≥? quorum) (range pup) of
```
```agda
       (no  _)        → nothing
       (yes (u , _))  → just u
```
AgdaMultiCode
Types and functions for the NEWPP transition system
figure*
figure*[h]
```agda
  NEWPP-Accept : ∀ {Γ} → let open NewPParamState s; newpp = applyUpdate pparams upd in
    viablePParams newpp
    ────────────────────────────────
    Γ ⊢ s ⇀⦇ just upd ,NEWPP⦈ ⟦ newpp , updatePPUp newpp ppup ⟧

  NEWPP-Reject : ∀ {Γ} →
    Γ ⊢ s ⇀⦇ nothing ,NEWPP⦈ s
```
NEWPP transition system
figure*
