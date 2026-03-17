# Cryptographic Primitives
sec:cryptographic-primitives
\LedgerModule{Crypto}, in which we rely on a public key signing scheme
for verification of spending.

fig:defs:crypto shows some of the types,
functions and properties of this scheme.


figure*[h]
AgdaMultiCode
*Types \& functions*
```agda
    SKey VKey Sig Ser  : Type
    isKeyPair          : SKey → VKey → Type
    isSigned           : VKey → Ser → Sig → Type
    sign               : SKey → Ser → Sig

  KeyPair = Σ[ sk ∈ SKey ] Σ[ vk ∈ VKey ] isKeyPair sk vk

```
*Property of signatures*
```agda
    isSigned-correct  : ((sk , vk , _) : KeyPair) (d : Ser) (σ : Sig)
                      → sign sk d ≡ σ → isSigned vk d σ
```
AgdaMultiCode
Definitions for the public key signature scheme
fig:defs:crypto
figure*

