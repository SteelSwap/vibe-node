# Base Types
sec:base-types
\LedgerModule{BaseTypes}, in which we define some of the most basic types used throughout the ledger.


figure*[h]
```agda
  Coin   = ℕ
  Slot   = ℕ
  Epoch  = ℕ
```
Some basic types used in many places in the ledger
figure*

figure*[h]
```agda
  UnitInterval = [ x ∈ ℚ ∣ (0 ≤ x) × (x ≤ 1) ]
```
Refinement types used in some places in the ledger
figure*
