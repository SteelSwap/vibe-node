% If the module name changes, change the following macro to match!
\mathsf{EpochPropConstRwds}{Epoch/Properties/ConstRwds}


claim[%
  \mathsf{EpochPropConstRwds}.lagda{\mathsf{EpochPropConstRwds}{}}:
   rule leaves rewards unchanged%
  ]
  itemize
    \item Informally. Rewards are left unchanged by the 
      rule.  That is, if es and es' are two s such that
      es~⇀⦇~e~,NEWEPOCH⦈~es', then the
      rewards of es and es' are equal.
    \item Formally.  
```agda
dom-rwds-const : {e : Epoch} (es es' : NewEpochState)
  → _ ⊢ es ⇀⦇ e ,NEWEPOCH⦈ es' → Type

dom-rwds-const es es' step = dom (RewardsOf es) ≡ dom (RewardsOf es')
```
    \item Proof. To appear (in the
      \mathsf{EpochPropConstRwds}.lagda{\mathsf{EpochPropConstRwds}{}} module
      of the \repourl{formal ledger repository}).
  itemize
claim
