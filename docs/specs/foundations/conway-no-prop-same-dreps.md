% If the module name changes, change the following macro to match!
\mathsf{EpochPropConstDReps}{Epoch/Properties/NoPropSameDReps}


claim[%
  \mathsf{EpochPropConstDReps}.lagda{\mathsf{EpochPropConstDReps}{}}:
  DReps unchanged if no gov proposals%
  ]
  itemize
    \item Informally. 
      If there are no governance proposals in the  of es, then the
      activeDReps of es in  e are the same as the
      activeDReps of es' in the next epoch. 
    \item Formally.  
```agda
prop≡∅⇒activeDReps-const : Epoch → (es es' : NewEpochState) → Type
prop≡∅⇒activeDReps-const e es es' =
  GovStateOf es ≡ [] → activeDReps e es ≡ᵉ activeDReps (sucᵉ e) es'
```
    \item Proof. To appear (in the
      \mathsf{EpochPropConstDReps}.lagda{\mathsf{EpochPropConstDReps}{}} module
      of the \repourl{formal ledger repository}).
  itemize
claim
