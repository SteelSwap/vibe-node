% If the module name changes, change the following macro to match!
\mathsf{CertsPoV}{Certs/Properties/PoV}


theorem[%
  \mathsf{CertsPoV}.lagda{\mathsf{CertsPoV}{}}:
   rule preserves value%
  ]thm:CERTS-PoV
  itemize
    \item Informally.
      Let l be a list of s, and let s₁, sₙ be s
      such that s₁~⇀⦇~l~,CERTS⦈~sₙ.
      Then, the value of s₁ is equal to the value of sₙ plus
      the value of the withdrawals in Γ.
    \item Formally.
```agda
    CERTS-pov :  {Γ : CertEnv} {s₁ sₙ  : CertState}
      → ∀[ a ∈ dom (CertEnv.wdrls Γ) ] NetworkIdOf a ≡ NetworkId
      →  Γ ⊢ s₁ ⇀⦇ l ,CERTS⦈ sₙ 
      → getCoin s₁ ≡ getCoin sₙ + getCoin (wdrlsOf Γ)
```
    \item Proof. See the
      \mathsf{CertsPoV}.lagda{\mathsf{CertsPoV}{}}
      module in the \repourl{formal ledger repository}.
  itemize
theorem
