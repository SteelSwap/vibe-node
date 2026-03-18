# Token Algebras
sec:token-algebra
\mathsf{LedgerModule}{TokenAlgebra}.

figure*[h]
AgdaMultiCode
*Abstract types*
PolicyId
```agda
  PolicyId

```

*Derived types*
TokenAlgebra
```agda
record TokenAlgebra : Type₁ where
  field
    Value : Set
    ⦃ Value-CommutativeMonoid ⦄ : CommutativeMonoid 0ℓ 0ℓ Value

```
```agda
    coin                      : Value → Coin
    inject                    : Coin → Value
    policies                  : Value → ℙ PolicyId
    size                      : Value → MemoryEstimate
    _≤ᵗ_                      : Value → Value → Type
    coin∘inject≗id            : coin ∘ inject ≗ id
    coinIsMonoidHomomorphism  : IsMonoidHomomorphism coin

```

*Helper functions*
sumᵛ
```agda
  sumᵛ : List Value → Value
  sumᵛ [] = inject 0
  sumᵛ (x ∷ l) = x + sumᵛ l
```
AgdaMultiCode
Token algebras, used for multi-assets
figure*
