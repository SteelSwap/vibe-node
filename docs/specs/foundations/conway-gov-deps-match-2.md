% If the module name changes, change the following macro to match!
\EpochPropGov{Epoch/Properties/GovDepsMatch}


lemma[%
  \EpochPropGov.lagda{\EpochPropGov{}}:
  govDepsMatch is invariant of  rule%
  ]
  lem:EpochGovDepsMatch

  itemize
    \item Informally.
      Let eps, eps'~:~ be two epoch states and let
      e~:~ be an epoch.  Recall, eps~.ls denotes the
      ledger state of eps.  If eps~⇀⦇~e~,EPOCH⦈~eps', then
      (under a certain special condition) ~(eps~.ls)
      implies ~(eps'~.ls). 
    \\[4pt]
    The special condition under which the property holds is the same as the one in thm:ChainGovDepsMatch:
    let removed' be the union of the governance actions in the removed field of the ratify
    state of eps and the orphaned governance actions in the  of eps.
    Let $G$ be the set
    $\{\GovActionDeposit{~id} : \ab{id} ∈ proj₁~\AgdaFunction{removed'}\}$.
    Assume: $G$ is a subset of the set of deposits
    of (the governance state of) eps.
    \item Formally.
```agda
  EPOCH-govDepsMatch :  {eps' : EpochState} {e : Epoch}
    → map (GovActionDeposit ∘ proj₁) removed' ⊆ dom (DepositsOf eps)
    → _ ⊢ eps ⇀⦇ e ,EPOCH⦈ eps'
    → govDepsMatch (eps .ls) → govDepsMatch (eps' .ls)
```
    \item Proof. See the
      \EpochPropGov.lagda{\EpochPropGov{}}
      module in the \repourl{formal ledger repository}.
  itemize
lemma
