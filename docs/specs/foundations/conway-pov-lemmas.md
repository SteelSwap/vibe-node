% If the module name changes, change the following macro to match!
\CertsPoVL{Certs/Properties/PoVLemmas}


lemma[%
  \CertsPoVL.lagda{\CertsPoVL{}}:  rule preserves value%
  ]
  itemize
    \item Informally.
      Let s, s' be s such that
      s~⇀⦇~dcert~,CERT⦈~s'
      for some dcert~:~.
      Then, getCoin~s $≡$ getCoin s'.
    \item Formally.
```agda
  CERT-pov : {Γ : CertEnv} {s s'  : CertState}
    → Γ ⊢ s ⇀⦇ dCert ,CERT⦈ s'
    → getCoin s ≡ getCoin s'
```
    \item Proof. See the
      \CertsPoVL.lagda{\CertsPoVL{}}
      module in the \repourl{formal ledger repository}.
  itemize
lemma


lemma[%
  \CertsPoVL.lagda{\CertsPoVL{}}:  rule preserves value%
  ]
  itemize
    \item Informally.
      Let Γ~:~ be a certificate environment, and let
      s, s'~:~ be certificate states such that
      s~⇀⦇~\_~,CERTBASE⦈~s'.
      Then, the value of s is equal to the value of s' plus the value of
      the withdrawals in Γ.  In other terms,
      \\[4pt]
      getCoin~s $≡$ getCoin~s'
       + getCoin~(Γ .wdrls ).
    \item Formally.
```agda
    CERTBASE-pov : {Γ : CertEnv} {s s' : CertState}
      → ∀[ a ∈ dom (CertEnv.wdrls Γ) ] NetworkIdOf a ≡ NetworkId
      → Γ ⊢ s ⇀⦇ _ ,CERTBASE⦈ s'
      → getCoin s ≡ getCoin s' + getCoin (CertEnv.wdrls Γ)
```
    \item Proof. See the
      \CertsPoVL.lagda{\CertsPoVL{}}
      module in the \repourl{formal ledger repository}.
  itemize
lemma


lemma[%
  \CertsPoVL.lagda{\CertsPoVL{}}: iteration of  rule preserves value%
  ]
  itemize
    \item Informally.
      Let l be a list of s, and let s₁, sₙ be s such
      that, starting with s₁ and successively applying the  rule to
      with s from the list l, we obtain sₙ.
      Then, the value of s₁ is equal to the value of sₙ.      
    \item Formally.
```agda
    sts-pov : {Γ : CertEnv} {s₁ sₙ : CertState}
      → ReflexiveTransitiveClosure {sts = _⊢_⇀⦇_,CERT⦈_} Γ s₁ l sₙ
      → getCoin s₁ ≡ getCoin sₙ
```
    \item Proof. See the
      \CertsPoVL.lagda{\CertsPoVL{}}
      module in the \repourl{formal ledger repository}.
  itemize
lemma


