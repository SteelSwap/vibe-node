% If the module name changes, change the following macro to match!
\mathsf{LedgerPropGov}{Ledger/Properties/GovDepsMatch}


lemma[\mathsf{LedgerPropGov}.lagda{\mathsf{LedgerPropGov}{}}: govDepsMatch is invariant of  rule%
  ]lem:LedgerGovDepsMatch
  \nopagebreak
  itemize
    \item Informally. 
      Suppose s, s' are ledger states such that
      s ⇀⦇~tx~,LEDGER⦈~s'.
      Let utxoSt and utxoSt' be their respective s and let govSt
      and govSt' be their respective s.
      If the governance action deposits of utxoSt are equal those
      of govSt, then the same holds for utxoSt' and govSt'.
      In other terms, if govDepsMatch~s, then govDepsMatch~s'. 
    \item Formally.
```agda
LEDGER-govDepsMatch :  LedgerInvariant _⊢_⇀⦇_,LEDGER⦈_ govDepsMatch
```
  \item Proof. See the
    \mathsf{LedgerPropGov}.lagda{\mathsf{LedgerPropGov}{}}
    module in the \repourl{formal ledger repository}.

  itemize
lemma
