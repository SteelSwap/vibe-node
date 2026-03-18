# Scripts
sec:scripts
\mathsf{LedgerModule}{Script}, in which we define  scripts.  

 scripts can verify the presence of keys and whether a transaction happens in a certain slot
interval.  The scripts are executed as part of the regular witnessing.

figure*[h]
```agda
data Timelock : Type where
  RequireAllOf       : List Timelock      → Timelock
  RequireAnyOf       : List Timelock      → Timelock
  RequireMOf         : ℕ → List Timelock  → Timelock
  RequireSig         : KeyHash            → Timelock
  RequireTimeStart   : Slot               → Timelock
  RequireTimeExpire  : Slot               → Timelock
```
```agda
  evalTimelock (khs : ℙ KeyHash) (I : Maybe Slot × Maybe Slot) : Timelock → Type where
  evalAll  : All (evalTimelock khs I) ss
           → (evalTimelock khs I) (RequireAllOf ss)
  evalAny  : Any (evalTimelock khs I) ss
           → (evalTimelock khs I) (RequireAnyOf ss)
  evalMOf  : MOf m (evalTimelock khs I) ss
           → (evalTimelock khs I) (RequireMOf m ss)
  evalSig  : x ∈ khs
           → (evalTimelock khs I) (RequireSig x)
  evalTSt  : M.Any (a ≤_) (I .proj₁)
           → (evalTimelock khs I) (RequireTimeStart a)
  evalTEx  : M.Any (_≤ a) (I .proj₂)
           → (evalTimelock khs I) (RequireTimeExpire a)
```
Timelock scripts and their evaluation
fig:defs:timelock
figure*

