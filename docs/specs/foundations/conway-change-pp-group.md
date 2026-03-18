
% If the module name changes, change the following macro to match!
\mathsf{ChangePPGroup}{GovernanceActions/Properties/ChangePPGroup}


claim[%
  \mathsf{ChangePPGroup}.lagda{\mathsf{ChangePPGroup}{}}:
  PParam updates have non-empty groups%
  ]
  itemize
    \item Informally.
      Let p~:~ be a governance proposal and suppose the  
      of p~.action is .  If the data
      field of p---that is pu = p~.action~.gaData---is
      denoted by pu (``parameter update''), then the set
      updateGroups~pu is nonempty.
    \item Formally.
```agda
ChangePPHasGroup : {tx : Tx} {p : GovProposal} (pu : PParamsUpdate)
  → p ∈ Tx.body tx → p .GovProposal.action ≡ ⟦ ChangePParams , pu ⟧ᵍᵃ
  → Type
ChangePPHasGroup pu _ _ = updateGroups pu ≢ ∅
```
    \item Proof. To appear (in the
      \mathsf{ChangePPGroup}.lagda{\mathsf{ChangePPGroup}{}} module
      of the \repourl{formal ledger repository}).
  itemize
claim
