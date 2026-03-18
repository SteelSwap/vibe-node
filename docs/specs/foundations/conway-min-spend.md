% If the module name changes, change the following macro to match!
\themodpath{Utxo/Properties/MinSpend}


theorem[%
  \themodpath.lagda{\themodpath{}}:
  general spend lower bound%
  ]\
  thm:minspend

  itemize
    \item Informally.  
      Let tx~:~ be a valid transaction and let txcerts be its
      list of s.
      Denote by
      noRefundCert~txcerts the assertion that no
      element in txcerts is one of the two refund types
      (i.e., an element of l is neither a  nor a ).
      \\[4pt]
      Let s, s'~:~ be two UTxO states.
      If s~⇀⦇~tx~,UTXO⦈~s'
      and if noRefundCert~txcerts,
      then the coin consumed by tx is at least the sum of the governance action
      deposits of the proposals in tx.

    \item Formally.
AgdaMultiCode
```agda
  utxoMinSpend : {Γ : UTxOEnv} {tx : Tx} {s s' : UTxOState}
    → Γ ⊢ s ⇀⦇ tx ,UTXO⦈ s'
    → noRefundCert (txcertsOf tx)
    → coin (consumed _ s (TxBodyOf tx)) ≥ length (txpropOf tx) * govActionDepositOf Γ
```
    \item Proof. See the
      \themodpath.lagda{\themodpath{}} module
      in the \repourl{formal ledger repository}.
AgdaMultiCode
  itemize
theorem

theorem[%
  \themodpath.lagda{\themodpath{}}:
  spend lower bound for proposals%
  ]\

  itemize
  \item Preliminary remarks.
  enumerate
    \item Define noRefundCert~l and pp as in thm:minspend.
    \item Given a ledger state ls and a transaction tx, denote by
      validTxIn₂~tx the assertion that there exists ledger state
      ls' such that ls~⇀⦇~tx~,LEDGER⦈~ls'.  
    \item Assume the following additive property of the ∪⁺ operator holds:
```agda
                           ∑[ x ← d₁ ∪⁺ d₂ ] x ≡ ∑[ x ← d₁ ] x ◇ ∑[ x ← d₂ ] x
```
  enumerate
  \item Informally.
    Let tx~:~ be a valid transaction and let cs~:~ be a chain state.
    If the condition validTxIn₂~tx (described above) holds,
    then the coin consumed by tx is at least the sum of the governance action
    deposits of the proposals in tx.

  \item Formally.
AgdaMultiCode
```agda
  propose-minSpend :  {slot : Slot} {tx : Tx} {cs : ChainState}
                      ( let  pp      = PParamsOf cs
                             utxoSt  = UTxOStateOf cs )
```
```agda
    → noRefundCert txcerts
    → validTxIn₂ cs slot tx
    → coin (consumed pp utxoSt body) ≥ length txprop * pp .govActionDeposit 
```
  \item Proof. See the
    \themodpath.lagda{\themodpath{}} module
    in the \repourl{formal ledger repository}.
AgdaMultiCode
  itemize
theorem
