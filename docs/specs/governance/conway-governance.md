# Governance
sec:governance
\mathsf{LedgerModule}{Gov}, where we define the types required for ledger governance.

The behavior of  is similar to that of a queue.  New proposals are
appended at the end, but any proposal can be removed at the epoch boundary.  However,
for the purposes of enactment, earlier proposals take priority.  Note that
 used in  is defined in sec:enactment.

itemize
  \item
     inserts (and potentially overrides) a vote made for a
    particular governance action (identified by its ID) by a credential with a role.
  \item
     adds a new proposed action at the end of a given .
  \item
    The  property indicates whether a given proposal, if it is a
     action, can potentially be enacted in the future. For this to be the
    case, its  needs to exist, be another  action and have a
    compatible version.
itemize


figure*
*Derived types*
AgdaMultiCode
```agda
GovState = List (GovActionID × GovActionState)
```
```agda

record GovEnv : Type where
  field
    txid        : TxId
    epoch       : Epoch
    pparams     : PParams
    ppolicy     : Maybe ScriptHash
    enactState  : EnactState
    certState   : CertState
    rewardCreds : ℙ Credential
```
AgdaMultiCode
Types used in the GOV transition system
defs:gov-derived-types
figure*


figure*
AgdaMultiCode
```agda
govActionPriority : GovActionType → ℕ
govActionPriority NoConfidence     = 0
govActionPriority UpdateCommittee  = 1
govActionPriority NewConstitution  = 2
govActionPriority TriggerHF        = 3
govActionPriority ChangePParams    = 4
govActionPriority TreasuryWdrl     = 5
govActionPriority Info             = 6

Overlap : GovActionType → GovActionType → Type
Overlap NoConfidence    UpdateCommittee  = ⊤
Overlap UpdateCommittee NoConfidence     = ⊤
Overlap a               a'               = a ≡ a'
```
```agda

insertGovAction : GovState → GovActionID × GovActionState → GovState
insertGovAction [] gaPr = [ gaPr ]
insertGovAction ((gaID₀ , gaSt₀) ∷ gaPrs) (gaID₁ , gaSt₁)
  =  if govActionPriority (action gaSt₀ .gaType) ≤ govActionPriority (action gaSt₁ .gaType)
     then (gaID₀ , gaSt₀) ∷ insertGovAction gaPrs (gaID₁ , gaSt₁)
     else (gaID₁ , gaSt₁) ∷ (gaID₀ , gaSt₀) ∷ gaPrs

mkGovStatePair : Epoch → GovActionID → RwdAddr → (a : GovAction) → NeedsHash (a .gaType)
                 → GovActionID × GovActionState
mkGovStatePair e aid addr a prev = (aid , record
  { votes = ∅ ; returnAddr = addr ; expiresIn = e ; action = a ; prevAction = prev })

addAction : GovState
          → Epoch → GovActionID → RwdAddr → (a : GovAction) → NeedsHash (a .gaType)
          → GovState
addAction s e aid addr a prev = insertGovAction s (mkGovStatePair e aid addr a prev)
```
```agda
  addVote : GovState → GovActionID → Voter → Vote → GovState
  addVote s aid voter v = map modifyVotes s
    where modifyVotes : GovActionID × GovActionState → GovActionID × GovActionState
          modifyVotes = λ (gid , s') → gid , record s'
            { votes = if gid ≡ aid then insert (votes s') voter v else votes s'}

  isRegistered : GovEnv → Voter → Type
  isRegistered Γ (r , c) = case r of
```
```agda
      CC    → just c ∈ range (gState .ccHotKeys)
      DRep  → c ∈ dom (gState .dreps)
      SPO   → c ∈ mapˢ KeyHashObj (dom (pState .pools))
        where
          open CertState (GovEnv.certState Γ) using (gState; pState)

  validHFAction : GovProposal → GovState → EnactState → Type
  validHFAction (record { action = ⟦ TriggerHF , v ⟧ᵍᵃ ; prevAction = prev }) s e =
    (let (v' , aid) = EnactState.pv e in aid ≡ prev × pvCanFollow v' v)
    ⊎ ∃₂[ x , v' ] (prev , x) ∈ fromList s × x .action ≡ ⟦ TriggerHF , v' ⟧ᵍᵃ × pvCanFollow v' v
  validHFAction _ _ _ = ⊤
```
AgdaMultiCode
Functions used in the GOV transition system
defs:gov-functions
figure*

figure*
AgdaMultiCode
*Transition relation types*
```agda
  _⊢_⇀⦇_,GOV⦈_  : GovEnv × ℕ → GovState → GovVote ⊎ GovProposal → GovState → Type
```
```agda
_⊢_⇀⦇_,GOVS⦈_   : GovEnv → GovState → List (GovVote ⊎ GovProposal) → GovState → Type
```
AgdaMultiCode
Type signature of the transition relation of the GOV transition system
defs:gov-defs
figure*

defs:enactable shows some of the functions used to determine whether certain
actions are enactable in a given state.  Specifically, allEnactable passes
the GovState to getAidPairsList to obtain a list of
GovActionID-pairs which is then passed to enactable. The latter uses the
\mathsf{AgdaUnderscore}{connectsto} function to check
whether the list of GovActionID-pairs connects the proposed action to a previously
enacted one.

The function  assigns a priority to the various types of governance actions.
This is useful for ordering lists of governance actions (see insertGovAction
in defs:gov-functions).
%
Priority is also used to check if two actions Overlap; that is,
they would modify the same piece of EnactState.

figure*
AgdaMultiCode
```agda
enactable  : EnactState → List (GovActionID × GovActionID)
           → GovActionID × GovActionState → Type
enactable e aidPairs = λ (aidNew , as) → case getHashES e (action as .gaType) of
```
```agda
   nothing        → ⊤
   (just aidOld)  → ∃[ t ]  fromList t ⊆ fromList aidPairs
                            × Unique t × t connects aidNew to aidOld

allEnactable : EnactState → GovState → Type
allEnactable e aid×states = All (enactable e (getAidPairsList aid×states)) aid×states

hasParentE : EnactState → GovActionID → GovActionType → Type
hasParentE e aid gaTy = case getHashES e gaTy of
```
```agda
   nothing    → ⊤
   (just id)  → id ≡ aid

hasParent : EnactState → GovState → (gaTy : GovActionType) → NeedsHash gaTy → Type
hasParent e s gaTy aid = case getHash aid of
```
```agda
    nothing      → ⊤
    (just aid')  → hasParentE e aid' gaTy
                   ⊎ Any (λ (gid , gas) → gid ≡ aid' × Overlap (gas .action .gaType) gaTy) s
```
AgdaMultiCode
Enactability predicate
defs:enactable
figure*

\clearpage

figure*
```agda
actionValid : ℙ Credential → Maybe ScriptHash → Maybe ScriptHash → Epoch → GovAction → Type
actionValid rewardCreds p ppolicy epoch ⟦ ChangePParams , _ ⟧ᵍᵃ =
  p ≡ ppolicy
actionValid rewardCreds p ppolicy epoch ⟦ TreasuryWdrl  , x ⟧ᵍᵃ =
  p ≡ ppolicy × mapˢ RwdAddr.stake (dom x) ⊆ rewardCreds
actionValid rewardCreds p ppolicy epoch ⟦ UpdateCommittee , (new , rem , q) ⟧ᵍᵃ =
  p ≡ nothing × (∀[ e ∈ range new ]  epoch < e) × (dom new ∩ rem ≡ᵉ ∅)
actionValid rewardCreds p ppolicy epoch _ =
  p ≡ nothing

actionWellFormed : GovAction → Type
actionWellFormed ⟦ ChangePParams , x ⟧ᵍᵃ = ppdWellFormed x
actionWellFormed ⟦ TreasuryWdrl  , x ⟧ᵍᵃ =
  (∀[ a ∈ dom x ] NetworkIdOf a ≡ NetworkId) × (∃[ v ∈ range x ] ¬ (v ≡ 0))
actionWellFormed _                 = ⊤
```
Validity and wellformedness predicates
fig:valid-and-wellformed
figure*

fig:valid-and-wellformed defines predicates used in the  case
of the GOV rule to ensure that a governance action is valid and well-formed.
itemize
  \item  ensures that the proposed action is valid given the current state of the system:
        itemize
          \item a  action is valid if the proposal policy is provided;
          \item a  action is valid if the proposal policy is provided and the reward stake
                credential is registered;
          \item an  action is valid if credentials of proposed candidates
                have not expired, and the action does not propose to both add and
                remove the same candidate.
        itemize
  \item  ensures that the proposed action is well-formed:
        itemize
          \item a  action must preserves well-formedness of the protocol parameters;
          \item a  action is well-formed if the network ID is correct and
                there is at least one non-zero withdrawal amount in the given  map.
        itemize
itemize


\clearpage

figure*
AgdaMultiCode
```agda
data _⊢_⇀⦇_,GOV⦈_ where
```
```agda
  GOV-Vote :
    ∙ (aid , ast) ∈ fromList s
    ∙ canVote (Γ .pparams) (action ast) (proj₁ voter)
    ∙ isRegistered Γ voter
    ∙ ¬ expired (Γ .epoch) ast
      ───────────────────────────────────────
      (Γ , k) ⊢ s ⇀⦇ inj₁ ⟦ aid , voter , v , machr ⟧ ,GOV⦈ addVote s aid voter v

  GOV-Propose :
    let pp           = Γ .pparams
        e            = Γ .epoch
        enactState   = Γ .enactState
        rewardCreds  = Γ .rewardCreds
        prop         = record { returnAddr = addr ; action = a ; anchor = achr
                              ; policy = p ; deposit = d ; prevAction = prev }
    in
    ∙ actionWellFormed a
    ∙ actionValid rewardCreds p (Γ .ppolicy) e a
    ∙ d ≡ pp .govActionDeposit
    ∙ validHFAction prop s enactState
    ∙ hasParent enactState s (a .gaType) prev
    ∙ NetworkIdOf addr ≡ NetworkId
    ∙ CredentialOf addr ∈ rewardCreds
      ───────────────────────────────────────
      (Γ , k) ⊢ s ⇀⦇ inj₂ prop ,GOV⦈ addAction s (pp .govActionLifetime +ᵉ e)
                                                 (Γ .txid , k) addr a prev

_⊢_⇀⦇_,GOVS⦈_ = ReflexiveTransitiveClosureᵢ {sts = _⊢_⇀⦇_,GOV⦈_}
```
AgdaMultiCode
Rules for the GOV transition system
defs:gov-rules
figure*

The GOVS transition system is now given as the reflexitive-transitive
closure of the system GOV, described in defs:gov-rules.

For , we check that the governance action being voted on
exists; that the voter's role is allowed to vote (see  in
fig:ratification-requirements); and that the voter's
credential is actually associated with their role (see
 in defs:gov-defs).

For , we check the correctness of the deposit along with some
and some conditions that ensure the action is well-formed and valid;
naturally, these checks depend on the type of action being proposed
(see fig:valid-and-wellformed).
