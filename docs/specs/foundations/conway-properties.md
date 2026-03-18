```agda
govDepsMatch : LState → Type
govDepsMatch ls =
  filterˢ isGADeposit (dom (DepositsOf ls)) ≡ᵉ fromList (dpMap (GovStateOf ls))
```
