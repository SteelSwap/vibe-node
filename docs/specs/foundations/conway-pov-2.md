% If the module name changes, change the following macro to match!
\mathsf{UtxoPoV}{Utxo/Properties/PoV}


lemma[\mathsf{UtxoPoV}.lagda{\mathsf{UtxoPoV}{}}:  rule preserves value]
  itemize
    \item Informally.
    Let s and s' be s, let tx~:~ be
    a fresh transaction with withdrawals txwdrls, and suppose
    s~⇀⦇~tx~,UTXO⦈~s'.
    If tx is valid, then the coin value of s' is equal to the sum of the
    coin values of s and txwdrls.  If tx is not valid, then the coin
    values of s and s' are equal.  
    We can express this concisely as follows:
    \[\mathsf{AgdaField}{getCoin~s} + \mathsf{AgdaField}{getCoin~txwdrls}
      · \mathsf{AgdaFunction}{χ} (\ab{tx~.isValid})
      ≡ \mathsf{AgdaField}{getCoin s'},\]
    where $χ~:~Bool~→~{0, 1}$ is the characteristic function,
    which returns 0 for false and 1 for true.
    \item Formally.
```agda
UTXOpov : {Γ : UTxOEnv} {tx : Tx} {s s' : UTxOState}
  → txidOf tx ∉ mapˢ proj₁ (dom (UTxOOf s))
  → Γ ⊢ s ⇀⦇ tx ,UTXO⦈ s'
  → getCoin s + getCoin (wdrlsOf tx) * χ (tx .isValid) ≡ getCoin s'
```
  \item Proof. See the
  \mathsf{UtxoPoV}.lagda{\mathsf{UtxoPoV}{}} module
  in the \repourl{formal ledger repository}.
  itemize
lemma
