% If the module name changes, change the following macro to match!
\ChainPropGov{Chain/Properties/GovDepsMatch}


theorem[%
  \ChainPropGov.lagda{\ChainPropGov{}}:
  govDepsMatch is invariant of  rule%
  ]\
  thm:ChainGovDepsMatch

  itemize
    \item Informally.
      Fix a  b, a  cs, and a  nes.
      Let csLState be the ledger state of cs.
      Recall, a  has just one field, newEpochState~:~.
      Consider the chain state cs' defined as follows:
```agda
  cs' : ChainState
  cs' .newEpochState =
    record { lastEpoch   = nes .lastEpoch
           ; epochState  = record (EpochStateOf cs) {ls = LStateOf nes}
           ; ru          = nes .ru }
```
      That is cs' is essentially nes, but the  field is
      set to the epochState of cs with the exception of the
       field, which is set to that of nes.
      \\[4pt]
      Let utxoSt and utxoSt' be the respective s of the ledger
      states of cs and cs', respectively, and let govSt and govSt'
      be their respective s.
      \\[4pt]
      Assume the following conditions hold:
      itemize
        \item let removed'~:~ℙ(GovActionID~×~GovActionState)
          be the union of
          itemize
            \item the governance actions in the removed field of the ratify
              state of eps, and
            \item the orphaned governance actions in the  of eps.
          itemize
          Let $G$ be the set
          $\{\GovActionDeposit{~id} : \ab{id} ∈ proj₁~\AgdaFunction{removed'}\}$.
          $G$ is a subset of the set of deposits of the chain state cs;
          that is,\\[4pt]
          map~(GovActionDeposit~$∘$~proj₁)~removed'~$⊆$~
          dom~(DepositsOf~cs);
        \item the total reference script size of csLState is not greater than the
          maximum allowed size per block (as specified in );
        \item cs~⇀⦇~b~,CHAIN⦈~cs'. 
      itemize
      Under these conditions, if the governance action deposits of utxoSt
      equal those of govSt, then the same holds for utxoSt' and govSt'.
      In other terms,
      govDepsMatch~csLState implies govDepsMatch~nesState.
    \item Formally.
```agda
  CHAIN-govDepsMatch :
    map (GovActionDeposit ∘ proj₁) removed' ⊆ dom (DepositsOf cs)
    →  totalRefScriptsSize csLState ts ≤ maxRefScriptSizePerBlock
    →  _ ⊢ cs ⇀⦇ b ,CHAIN⦈ cs'
    →  govDepsMatch csLState → govDepsMatch (LStateOf nes)
```
    \item Proof.  See the
      \ChainPropGov.lagda{\ChainPropGov{}}
       module in the \repourl{formal ledger repository}.
  itemize
theorem
