% If the module name changes, change the following macro to match!
\mathsf{ChainPropWF}{Chain/Properties/PParamsWellFormed}


claim[%
  \mathsf{ChainPropWF}.lagda{\mathsf{ChainPropWF}{}}:
  Well-formedness of  is a  invariant%
  ]
  itemize
    \item Informally. We say the  of a chain state are well-formed if
    each of the following parameters is non-zero:
    maxBlockSize, maxTxSize, maxHeaderSize, maxValSize, refScriptCostStride, coinsPerUTxOByte,
    poolDeposit, collateralPercentage, ccMaxTermLength, govActionLifetime,
    govActionDeposit, drepDeposit.  Formally,
```agda
pp-wellFormed : ChainState → Type
pp-wellFormed = paramsWellFormed ∘ PParamsOf
```
      This property asserts that pp-wellFormed is a chain invariant.
      That is, if cs and cs' are chain states such that
      cs~⇀⦇~tx~,CHAIN⦈~cs', and if
      the  of cs are well-formed, then so are the  of cs'.
    \item Formally.  
```agda
pp-wellFormed-invariant : Type
pp-wellFormed-invariant = LedgerInvariant _⊢_⇀⦇_,CHAIN⦈_ pp-wellFormed
```
    \item Proof. To appear (in the
      \mathsf{ChainPropWF}.lagda{\mathsf{ChainPropWF}{}} module
      of the \repourl{formal ledger repository}).
  itemize
claim
