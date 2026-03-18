# Certificates
sec:certificates
\mathsf{LedgerModule}{Certs}.


figure*[ht]
*Derived types*
```agda
data DepositPurpose : Type where
  CredentialDeposit  : Credential   → DepositPurpose
  PoolDeposit        : KeyHash      → DepositPurpose
  DRepDeposit        : Credential   → DepositPurpose
  GovActionDeposit   : GovActionID  → DepositPurpose

Deposits  = DepositPurpose ⇀ Coin
Rewards   = Credential ⇀ Coin
DReps     = Credential ⇀ Epoch
```
Deposit types
fig:certs:deposit-types
figure*

figure*
AgdaMultiCode
NoConway
```agda
record PoolParams : Type where
  field
    owners          : ℙ KeyHash
    cost            : Coin
    margin          : UnitInterval
    pledge          : Coin
    rewardAccount   : Credential
```
NoConway
AgdaMultiCode
Stake pool parameter definitions
figure*

figure*[h!]
AgdaMultiCode
```agda
data DCert : Type where
  delegate    : Credential → Maybe VDeleg → Maybe KeyHash → Coin → DCert
  dereg       : Credential → Maybe Coin → DCert
  regpool     : KeyHash → PoolParams → DCert
  retirepool  : KeyHash → Epoch → DCert
  regdrep     : Credential → Coin → Anchor → DCert
  deregdrep   : Credential → Coin → DCert
  ccreghot    : Credential → Maybe Credential → DCert
```
NoConway
```agda
cwitness : DCert → Maybe Credential
cwitness (delegate c _ _ _)  = just c
cwitness (dereg c _)         = just c
cwitness (regpool kh _)      = just $ KeyHashObj kh
cwitness (retirepool kh _)   = just $ KeyHashObj kh
cwitness (regdrep c _ _)     = just c
cwitness (deregdrep c _)     = just c
cwitness (ccreghot c _)      = just c
```
NoConway
AgdaMultiCode
Delegation definitions
figure*

figure*[htb]
AgdaMultiCode
```agda
record CertEnv : Type where
  field
    epoch     : Epoch
    pp        : PParams
    votes     : List GovVote
    wdrls     : RwdAddr ⇀ Coin
    coldCreds : ℙ Credential
```
```agda

record DState : Type where
```
```agda
  field
    voteDelegs   : Credential ⇀ VDeleg
    stakeDelegs  : Credential ⇀ KeyHash
    rewards      : Credential ⇀ Coin
```
NoConway
```agda

record PState : Type where
  field
    pools     : KeyHash ⇀ PoolParams
    retiring  : KeyHash ⇀ Epoch
```
NoConway
```agda

record GState : Type where
```
```agda
  field
    dreps      : DReps
    ccHotKeys  : Credential ⇀ Maybe Credential
```
```agda

record CertState : Type where
```
```agda
  field
    dState : DState
    pState : PState
    gState : GState
```
```agda

record DelegEnv : Type where
  field
    pparams       : PParams
    pools         : KeyHash ⇀ PoolParams
    delegatees    : ℙ Credential

GovCertEnv  = CertEnv
PoolEnv     = PParams
```
AgdaMultiCode
Types used for CERTS transition system
figure*


## Changes Introduced in Conway Era

### Delegation

Registered credentials can now delegate to a DRep as well as to a
stake pool. This is achieved by giving the  certificate two
optional fields, corresponding to a DRep and stake pool.

Stake can be delegated for voting and block production simultaneously,
since these are two separate features. In fact, preventing this could
weaken the security of the chain, since security relies on high
participation of honest stake holders.

### Removal of Pointer Addresses, Genesis Delegations and MIR Certificates

Support for pointer addresses, genesis delegations and MIR
certificates is removed (see 1694 and cip1694).
In , this means that the four fields relating to those features
are no longer present, and  contains none of the fields it used
to in the Shelley era (see \textcite[\sectionname~9.2]{shelley-ledger-spec}).

Note that pointer addresses are still usable, only their staking
functionality has been retired. So all funds locked behind pointer
addresses are still accessible, they just don't count towards the
stake distribution anymore. Genesis delegations and MIR certificates
have been superceded by the new governance mechanisms, in particular
the  governance action in case of the MIR certificates.

### Explicit Deposits

Registration and deregistration of staking credentials are now
required to explicitly state the deposit that is being paid or
refunded. This deposit is used for checking correctness of transactions
with certificates. Including the deposit aligns better with other
design decisions such as having explicit transaction fees and helps
make this information visible to light clients and hardware wallets.

While not shown in the figures, the old certificates without explicit
deposits will still be supported for some time for backwards
compatibility.

## Governance Certificate Rules

The rules for transition systems dealing with individual certificates
are defined in
NoConway
fig:sts:aux-cert-deleg,fig:sts:aux-cert-pool,fig:sts:aux-cert-gov.
NoConway
Conway
fig:sts:aux-cert-deleg,fig:sts:aux-cert-gov.
Conway
GOVCERT deals with the new certificates relating to DReps and the
constitutional committee.

itemize
\item  registers (or re-registers) a DRep. In case of
  registration, a deposit needs to be paid. Either way, the activity
  period of the DRep is reset.
\item  deregisters a DRep.
\item  registers a ``hot'' credential for constitutional
  committee members.\footnote{By ``hot'' and ``cold'' credentials we mean
    the following: a cold credential is used to register a hot credential,
    and then the hot credential is used for voting. The idea is that the
    access to the cold credential is kept in a secure location, while the
    hot credential is more conveniently accessed.  If the hot credential
    is compromised, it can be changed using the cold credential.}
  We check that the cold key did not previously
  resign from the committee. We allow this delegation for any cold
  credential that is either part of  or is is a proposal.
  This allows a newly elected member of the constitutional committee to
  immediately delegate their vote to a hot key and use it to vote. Since
  votes are counted after previous actions have been enacted, this allows
  constitutional committee members to act without a delay of one epoch.
itemize

figure*[ht]
AgdaMultiCode
```agda
  _⊢_⇀⦇_,DELEG⦈_     : DelegEnv    → DState     → DCert       → DState     → Type
```
```agda
  _⊢_⇀⦇_,POOL⦈_      : PoolEnv     → PState     → DCert       → PState     → Type
```
```agda
  _⊢_⇀⦇_,GOVCERT⦈_   : GovCertEnv  → GState     → DCert       → GState     → Type
```
```agda
  _⊢_⇀⦇_,CERT⦈_      : CertEnv     → CertState  → DCert       → CertState  → Type
```
```agda
  _⊢_⇀⦇_,CERTBASE⦈_  : CertEnv     → CertState  → ⊤           → CertState  → Type
```
```agda
  _⊢_⇀⦇_,CERTS⦈_     : CertEnv     → CertState  → List DCert  → CertState  → Type
```
AgdaMultiCode
Types for the transition systems relating to certificates
fig:sts:certs-types
figure*

figure*[h]
AgdaSuppressSpace
```agda
  DELEG-delegate :
    let Γ = ⟦ pp , pools , delegatees ⟧
    in
    ∙ (c ∉ dom rwds → d ≡ pp .keyDeposit)
    ∙ (c ∈ dom rwds → d ≡ 0)
    ∙ mv ∈ mapˢ (just ∘ credVoter DRep) delegatees ∪
        fromList ( nothing ∷ just abstainRep ∷ just noConfidenceRep ∷ [] )
    ∙ mkh ∈ mapˢ just (dom pools) ∪ ❴ nothing ❵
      ────────────────────────────────
      Γ ⊢  ⟦ vDelegs , sDelegs , rwds ⟧ ⇀⦇ delegate c mv mkh d ,DELEG⦈
           ⟦ insertIfJust c mv vDelegs , insertIfJust c mkh sDelegs , rwds ∪ˡ ❴ c , 0 ❵ ⟧

  DELEG-dereg :
    ∙ (c , 0) ∈ rwds
      ────────────────────────────────
      ⟦ pp , pools , delegatees ⟧ ⊢ ⟦ vDelegs , sDelegs , rwds ⟧ ⇀⦇ dereg c md ,DELEG⦈
        ⟦ vDelegs ∣ ❴ c ❵ ᶜ , sDelegs ∣ ❴ c ❵ ᶜ , rwds ∣ ❴ c ❵ ᶜ ⟧

  DELEG-reg :
    ∙ c ∉ dom rwds
    ∙ d ≡ pp .keyDeposit ⊎ d ≡ 0
      ────────────────────────────────
      ⟦ pp , pools , delegatees ⟧ ⊢
        ⟦ vDelegs , sDelegs , rwds ⟧ ⇀⦇ reg c d ,DELEG⦈
        ⟦ vDelegs , sDelegs , rwds ∪ˡ ❴ c , 0 ❵ ⟧
```
AgdaSuppressSpace
Auxiliary DELEG transition system
fig:sts:aux-cert-deleg
figure*

NoConway
figure*[h]
AgdaSuppressSpace
```agda
  POOL-regpool :
    ∙ kh ∉ dom pools
      ────────────────────────────────
      pp ⊢  ⟦ pools , retiring ⟧ ⇀⦇ regpool kh poolParams ,POOL⦈
            ⟦ ❴ kh , poolParams ❵ ∪ˡ pools , retiring ⟧

  POOL-retirepool :
    ────────────────────────────────
    pp ⊢ ⟦ pools , retiring ⟧ ⇀⦇ retirepool kh e ,POOL⦈ ⟦ pools , ❴ kh , e ❵ ∪ˡ retiring ⟧
```
AgdaSuppressSpace
Auxiliary POOL transition system
fig:sts:aux-cert-pool
figure*
NoConway

figure*[htb]
AgdaSuppressSpace
```agda
  GOVCERT-regdrep :
    let Γ = ⟦ e , pp , vs , wdrls , cc ⟧
    in
    ∙ (d ≡ pp .drepDeposit × c ∉ dom dReps) ⊎ (d ≡ 0 × c ∈ dom dReps)
      ────────────────────────────────
      Γ ⊢ ⟦ dReps , ccKeys ⟧ ⇀⦇ regdrep c d an ,GOVCERT⦈
          ⟦ ❴ c , e + pp .drepActivity ❵ ∪ˡ dReps , ccKeys ⟧

  GOVCERT-deregdrep :
    ∙ c ∈ dom dReps
      ────────────────────────────────
      ⟦ e , pp , vs , wdrls , cc ⟧ ⊢ ⟦ dReps , ccKeys ⟧ ⇀⦇ deregdrep c d ,GOVCERT⦈ ⟦ dReps ∣ ❴ c ❵ ᶜ , ccKeys ⟧

  GOVCERT-ccreghot :
    ∙ (c , nothing) ∉ ccKeys
    ∙ c ∈ cc
      ────────────────────────────────
      ⟦ e , pp , vs , wdrls , cc ⟧ ⊢ ⟦ dReps , ccKeys ⟧ ⇀⦇ ccreghot c mc ,GOVCERT⦈ ⟦ dReps , ❴ c , mc ❵ ∪ˡ ccKeys ⟧
```
AgdaSuppressSpace
Auxiliary GOVCERT transition system
fig:sts:aux-cert-gov
figure*

fig:sts:certs assembles the CERTS transition system by
bundling the previously defined pieces together into the CERT system,
and then taking the reflexive-transitive closure of CERT together with
CERTBASE as the base case. CERTBASE does the following:

itemize
\item check the correctness of withdrawals and ensure that withdrawals
  only happen from credentials that have delegated their voting power;
\item set the rewards of the credentials that withdrew funds to zero;
\item and set the activity timer of all DReps that voted to
   epochs in the future.
itemize

figure*[htbp]
*CERT transitions*
AgdaSuppressSpace
```agda
  CERT-deleg :
    ∙ ⟦ pp , PState.pools stᵖ , dom (GState.dreps stᵍ) ⟧ ⊢ stᵈ ⇀⦇ dCert ,DELEG⦈ stᵈ'
      ────────────────────────────────
      ⟦ e , pp , vs , wdrls , cc ⟧ ⊢ ⟦ stᵈ , stᵖ , stᵍ ⟧ ⇀⦇ dCert ,CERT⦈ ⟦ stᵈ' , stᵖ , stᵍ ⟧

  CERT-pool :
    ∙ pp ⊢ stᵖ ⇀⦇ dCert ,POOL⦈ stᵖ'
      ────────────────────────────────
      ⟦ e , pp , vs , wdrls , cc ⟧ ⊢ ⟦ stᵈ , stᵖ , stᵍ ⟧ ⇀⦇ dCert ,CERT⦈ ⟦ stᵈ , stᵖ' , stᵍ ⟧

  CERT-vdel :
    ∙ Γ ⊢ stᵍ ⇀⦇ dCert ,GOVCERT⦈ stᵍ'
      ────────────────────────────────
      Γ ⊢ ⟦ stᵈ , stᵖ , stᵍ ⟧ ⇀⦇ dCert ,CERT⦈ ⟦ stᵈ , stᵖ , stᵍ' ⟧
```
AgdaSuppressSpace
*CERTBASE transition*
AgdaSuppressSpace
```agda
  CERT-base :
    let refresh          = mapPartial getDRepVote (fromList vs)
        refreshedDReps   = mapValueRestricted (const (e + pp .drepActivity)) dReps refresh
        wdrlCreds        = mapˢ stake (dom wdrls)
        validVoteDelegs  = voteDelegs ∣^ (  mapˢ (credVoter DRep) (dom dReps)
                                        ∪ fromList (noConfidenceRep ∷ abstainRep ∷ []) )
    in
    ∙ filter isKeyHash wdrlCreds ⊆ dom voteDelegs
    ∙ mapˢ (map₁ stake) (wdrls ˢ) ⊆ rewards ˢ
      ────────────────────────────────
      ⟦ e , pp , vs , wdrls , cc ⟧ ⊢
        ⟦ ⟦ voteDelegs , stakeDelegs , rewards ⟧
        , stᵖ
        , ⟦ dReps , ccHotKeys ⟧
        ⟧ ⇀⦇ _ ,CERTBASE⦈
        ⟦ ⟦ validVoteDelegs , stakeDelegs , constMap wdrlCreds 0 ∪ˡ rewards ⟧
        , stᵖ
        , ⟦ refreshedDReps , ccHotKeys ⟧
        ⟧
```
AgdaSuppressSpace
CERTS rules
fig:sts:certs
figure*
