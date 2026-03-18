## Witnessing
sec:witnessing
\LedgerModule{Utxow}, in which we define witnessing.

The purpose of witnessing is make sure the intended action is
authorized by the holder of the signing key.  (For details
see \textcite[\sectionname~8.3]{shelley-ledger-spec}.)
fig:functions:utxow defines functions used for witnessing.
 and  are now defined by projecting the same
information out of .  Note that the last component of 
adds the script in the proposal policy only if it is present.


 has additional conditions for new features in
Conway. If a transaction contains any votes, proposals, a treasury
donation or asserts the treasury amount, it is only allowed to contain
Plutus V3 scripts. Additionally, the presence of reference scripts or
inline scripts does not prevent Plutus V1 scripts from being used in a
transaction anymore. Only inline datums are now disallowed from
appearing together with a Plutus V1 script.

figure*[h]
AgdaMultiCode
```agda
getVKeys : ℙ Credential → ℙ KeyHash
getVKeys = mapPartial isKeyHashObj

allowedLanguages : Tx → UTxO → ℙ Language
allowedLanguages tx utxo =
  if (∃[ o ∈ os ] isBootstrapAddr (proj₁ o))
    then ∅
  else if UsesV3Features txb
    then fromList (PlutusV3 ∷ [])
  else if ∃[ o ∈ os ] HasInlineDatum o
    then fromList (PlutusV2 ∷ PlutusV3 ∷ [])
  else
    fromList (PlutusV1 ∷ PlutusV2 ∷ PlutusV3 ∷ [])
  where
    txb = tx .Tx.body; open TxBody txb
    os = range (outs txb) ∪ range (utxo ∣ (txins ∪ refInputs))

getScripts : ℙ Credential → ℙ ScriptHash
getScripts = mapPartial isScriptObj

credsNeeded : UTxO → TxBody → ℙ (ScriptPurpose × Credential)
credsNeeded utxo txb
  =  mapˢ (λ (i , o)  → (Spend  i , payCred (proj₁ o))) ((utxo ∣ (txins ∪ collateral)) ˢ)
  ∪  mapˢ (λ a        → (Rwrd   a , stake a)) (dom ∣ txwdrls ∣)
  ∪  mapPartial (λ c  → (Cert   c ,_) <$> cwitness c) (fromList txcerts)
  ∪  mapˢ (λ x        → (Mint   x , ScriptObj x)) (policies mint)
  ∪  mapˢ (λ v        → (Vote   v , proj₂ v)) (fromList (map voter txvote))
  ∪  mapPartial (λ p  → case  p .policy of
```
```agda
                              (just sh)  → just (Propose  p , ScriptObj sh)
                              nothing    → nothing) (fromList txprop)
```
```agda

witsVKeyNeeded : UTxO → TxBody → ℙ KeyHash
witsVKeyNeeded = getVKeys ∘ mapˢ proj₂ ∘ credsNeeded

scriptsNeeded  : UTxO → TxBody → ℙ ScriptHash
scriptsNeeded = getScripts ∘ mapˢ proj₂ ∘ credsNeeded
```
AgdaMultiCode
Functions used for witnessing
fig:functions:utxow
figure*

figure*[h]
```agda
  _⊢_⇀⦇_,UTXOW⦈_ : UTxOEnv → UTxOState → Tx → UTxOState → Type
```
UTxOW transition-system types
fig:ts-types:utxow
figure*

figure*[h]
AgdaMultiCode
```agda
  UTXOW-inductive :
    let  utxo                                = s .utxo
```
```agda
         witsKeyHashes                       = mapˢ hash (dom vkSigs)
         witsScriptHashes                    = mapˢ hash scripts
         inputHashes                         = getInputHashes tx utxo
         refScriptHashes                     = fromList (map hash (refScripts tx utxo))
         neededHashes                        = scriptsNeeded utxo txb
         txdatsHashes                        = dom txdats
         allOutHashes                        = getDataHashes (range txouts)
         nativeScripts                       = mapPartial isInj₁ (txscripts tx utxo)
```
```agda
    in
    ∙  ∀[ (vk , σ) ∈ vkSigs ] isSigned vk (txidBytes txid) σ
    ∙  ∀[ s ∈ nativeScripts ] (hash s ∈ neededHashes → validP1Script witsKeyHashes txvldt s)
    ∙  witsVKeyNeeded utxo txb ⊆ witsKeyHashes
    ∙  neededHashes ＼ refScriptHashes ≡ᵉ witsScriptHashes
    ∙  inputHashes ⊆ txdatsHashes
    ∙  txdatsHashes ⊆ inputHashes ∪ allOutHashes ∪ getDataHashes (range (utxo ∣ refInputs))
    ∙  languages tx utxo ⊆ allowedLanguages tx utxo
    ∙  txADhash ≡ map hash txAD
    ∙  Γ ⊢ s ⇀⦇ tx ,UTXO⦈ s'
       ────────────────────────────────
       Γ ⊢ s ⇀⦇ tx ,UTXOW⦈ s'
```
AgdaMultiCode
UTXOW inference rules
fig:rules:utxow
figure*

## Plutus script context
0069
unifies the arguments given to all types of Plutus scripts currently available:
spending, certifying, rewarding, minting, voting, proposing.

The formal specification permits running spending scripts in the absence datums
in the Conway era.  However, since the interface with Plutus is kept abstract
in this specification, changes to the representation of the script context which
are part of 0069 are not included here.  To provide a 0069-conformant
implementation of Plutus to this specification, an additional step processing
the   argument we provide would be required.

In fig:rules:utxow, the line
~~ compares two inhabitants of
~.  In the Alonzo spec, these two terms would
have inhabited ~(~), where a  is thrown
out~\parencite[\sectionname~3.1]{alonzo-ledger-spec}.
