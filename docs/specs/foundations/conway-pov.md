% If the module name changes, change the following macro to match!
\mathsf{LedgerPoV}{Ledger/Properties/PoV}


theorem[\mathsf{LedgerPoV}.lagda{\mathsf{LedgerPoV}{}}:  rule preserves value]
  thm:LEDGER-PoV
  itemize
    \item Informally.
    Let s, s'~:~ be ledger states and let tx~:~ be a
    fresh transaction, that is, a transaction that is not already part of the
     of s. If s~⇀⦇~tx~,LEDGER⦈~s',
    then the coin values of s and s' are equal, that is,
    getCoin~s $≡$ getCoin~s'.
    \item Formally.
AgdaMultiCode
```agda
  LEDGER-pov : {Γ : LEnv} {s s' : LState}
    → txid ∉ mapˢ proj₁ (dom (UTxOOf s))
    → Γ ⊢ s ⇀⦇ tx ,LEDGER⦈ s' → getCoin s ≡ getCoin s'
```
AgdaMultiCode
    \item Proof. See the
      \mathsf{LedgerPoV}.lagda{\mathsf{LedgerPoV}{}}
      module in the \repourl{formal ledger repository}.
  itemize
theorem
