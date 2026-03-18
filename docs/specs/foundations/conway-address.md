# Addresses
sec:addresses
\mathsf{LedgerModule}{Address}, in which we define credentials and various types
of addresses here. 

A credential contains a hash, either of a verifying (public) key
() or of a script ().

N.B.\@ in the Shelley era the type of the  field of the
 record was  (see \textcite[\sectionname~4]{shelley-ledger-spec});
to specify an address with no stake, we would use an ``enterprise'' address.
In contrast, the type of  in the Conway era is ~,
so we can now use  to specify an address with no stake
by setting  to .


figure*[!ht]
AgdaMultiCode
*Abstract types*
```agda
  Network
  KeyHash
  ScriptHash

```
*Derived types*
\mathsf{AgdaTarget}{Credential, BaseAddr, BootstrapAddr, RwdAddr, net, pay, stake, Addr,
VKeyBaseAddr, VKeyBoostrapAddr, ScriptBaseAddr, ScriptBootstrapAddr, VKeyAddr, ScriptAddr}
```agda
data Credential : Type where
  KeyHashObj : KeyHash → Credential
  ScriptObj  : ScriptHash → Credential
```
```agda

record BaseAddr : Type where
  field net    : Network
        pay    : Credential
        stake  : Maybe Credential

record BootstrapAddr : Type where
  field net        : Network
        pay        : Credential
        attrsSize  : ℕ

record RwdAddr : Type where
  field net    : Network
        stake  : Credential
```
```agda

VKeyBaseAddr         = Σ[ addr ∈ BaseAddr       ] isVKey    (addr .pay)
VKeyBootstrapAddr    = Σ[ addr ∈ BootstrapAddr  ] isVKey    (addr .pay)
ScriptBaseAddr       = Σ[ addr ∈ BaseAddr       ] isScript  (addr .pay)
ScriptBootstrapAddr  = Σ[ addr ∈ BootstrapAddr  ] isScript  (addr .pay)

Addr        = BaseAddr        ⊎ BootstrapAddr
VKeyAddr    = VKeyBaseAddr    ⊎ VKeyBootstrapAddr
ScriptAddr  = ScriptBaseAddr  ⊎ ScriptBootstrapAddr
```
\\
*Helper functions*
payCred, isVKeyAddr
```agda
payCred       : Addr → Credential
stakeCred     : Addr → Maybe Credential
netId         : Addr → Network
isVKeyAddr    : Addr → Type
isScriptAddr  : Addr → Type

isVKeyAddr       = isVKey ∘ payCred
isScriptAddr     = isScript ∘ payCred
isScriptRwdAddr  = isScript ∘ CredentialOf
```
AgdaMultiCode
Definitions used in Addresses
fig:defs:addresses
figure*
