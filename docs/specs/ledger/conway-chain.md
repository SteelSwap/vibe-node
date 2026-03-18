# Blockchain Layer
sec:blockchain-layer
\mathsf{LedgerModule}{Chain}

figure*[h]
AgdaMultiCode
```agda
record ChainState : Type where
  field
    newEpochState  : NewEpochState

record Block : Type where
  field
    ts    : List Tx
    slot  : Slot
```
AgdaMultiCode
Definitions CHAIN transition system
figure*
figure*[h]
AgdaSuppressSpace
```agda
  _⊢_⇀⦇_,CHAIN⦈_ : ⊤ → ChainState → Block → ChainState → Type
```
AgdaSuppressSpace
Type of the CHAIN transition system
figure*
figure*[h]
AgdaSuppressSpace
```agda
  CHAIN : {b : Block} {nes : NewEpochState} {cs : ChainState}
```
```agda
    let  cs'  = record cs {  newEpochState
                             = record nes {  epochState
                                             = record epochState {ls = ls'} } }
         Γ    = ⟦ slot , ∣ constitution ∣ , ∣ pp ∣ , es , treasuryOf nes ⟧
    in
    ∙ totalRefScriptsSize ls ts ≤ maxRefScriptSizePerBlock
    ∙ _ ⊢ newEpochState ⇀⦇ epoch slot ,NEWEPOCH⦈ nes
    ∙ Γ ⊢ ls ⇀⦇ ts ,LEDGERS⦈ ls'
      ────────────────────────────────
      _ ⊢ cs ⇀⦇ b ,CHAIN⦈ cs'
```
AgdaSuppressSpace
CHAIN transition system
figure*
