% If the module name changes, change the following macro to match!
\ChainPropEpoch{Chain/Properties/EpochStep}

claim[%
  \ChainPropEpoch.lagda{\ChainPropEpoch{}}:
  New enact state only if new epoch%
  ]\

  itemize
    \item Informally.
      Let cs and cs' be s and b a .
      If cs~⇀⦇~b~,CHAIN⦈~cs'
      and if the enact states of cs and cs' differ, then
      the epoch of the slot of b is the successor of the last epoch of cs.
    \item Formally.
AgdaMultiCode
```agda
enact-change⇒newEpoch : (b : Block) {cs cs'  : ChainState} 
  → _ ⊢ cs ⇀⦇ b ,CHAIN⦈ cs' → EnactStateOf cs ≢ EnactStateOf cs'
  → Type

enact-change⇒newEpoch b {cs} h es≢es' = epoch (b .slot) ≡ sucᵉ (LastEpochOf cs) 
```
AgdaMultiCode
    \item Proof. To appear (in the
      \ChainPropEpoch.lagda{\ChainPropEpoch{}}
      module of the \repourl{formal ledger repository}).
  itemize
claim
