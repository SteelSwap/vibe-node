# Ratification
sec:ratification
\mathsf{LedgerModule}{Ratify}

Governance actions are ratified through on-chain votes.
Different kinds of governance actions have different ratification requirements
but always involve at least two of the three governance bodies.

A successful motion of no-confidence, election of a new constitutional
committee, a constitutional change, or a hard-fork delays ratification of
all other governance actions until the first epoch after their
enactment. This gives a new constitutional committee enough time to vote
on current proposals, re-evaluate existing proposals with respect to a
new constitution, and ensures that the (in principle arbitrary) semantic
changes caused by enacting a hard-fork do not have unintended
consequences in combination with other actions.

## Ratification Requirements
sec:ratification-requirements
fig:ratification-requirements details the ratification
requirements for each governance action scenario. For a governance
action to be ratified, all of these requirements must be satisfied, on
top of other conditions that are explained further down. The
 function is defined as a table, with a row for each type of
 and the colums representing the ,  and  roles
in that order.

The symbols mean the following:
itemize
\item
  vote x: For an action to pass, the fraction of stake
  associated with yes votes with respect to that associated
  with yes and no votes must exceed the threshold x.
\item
  ─: The body of governance does not participate in voting.
\item
  ✓: The constitutional committee needs to approve an action,
  with the threshold assigned to it.
\item
  ✓†: Voting is possible, but the action will never be enacted.
  This is equivalent to vote 2 (or any other number above 1).
itemize

Two rows in this table contain functions that compute the
 and  thresholds simultaneously: the rows for 
and .

For , there can be different thresholds depending on whether the
system is in a state of no-confidence or not. This information is
provided via the ccThreshold argument: if the system is in a
state of no-confidence, then ccThreshold is set to .

In case of the  action, the thresholds further depend on
what groups that action is associated with. 
associates a pair of thresholds to each individual group. Since an
individual update can contain multiple groups, the actual thresholds
are then given by taking the maximum of all those thresholds.

Note that each protocol parameter belongs to exactly one of the four
groups that have a  threshold, so a  vote will always be
required. A protocol parameter may or may not be in the
, so an  vote may not be required.

Finally, each of the P$_x$ and Q$_x$ in
fig:ratification-requirements are protocol parameters.
figure*[htb]
AgdaMultiCode
```agda
threshold : PParams → Maybe ℚ → GovAction → GovRole → Maybe ℚ
threshold pp ccThreshold ga =
  case  ga ↓ of
```
```agda
        (NoConfidence     , _) → ∣ ─   ∣ vote P1      ∣ vote Q1  ∣
        (UpdateCommittee  , _) → ∣ ─   ∥ P/Q2a/b                 ∣
        (NewConstitution  , _) → ∣ ✓   ∣ vote P3      ∣ ─        ∣
        (TriggerHF        , _) → ∣ ✓   ∣ vote P4      ∣ vote Q4  ∣
        (ChangePParams    , x) → ∣ ✓   ∥ P/Q5 x                  ∣
        (TreasuryWdrl     , _) → ∣ ✓   ∣ vote P6      ∣ ─        ∣
        (Info             , _) → ∣ ✓†  ∣ ✓†           ∣ ✓†       ∣
          where
```
```agda
          P/Q2a/b : Maybe ℚ × Maybe ℚ
          P/Q2a/b =  case ccThreshold of
```
```agda
                     (just _)  → (vote P2a , vote Q2a)
                     nothing   → (vote P2b , vote Q2b)

          pparamThreshold : PParamGroup → Maybe ℚ × Maybe ℚ
          pparamThreshold NetworkGroup     = (vote P5a  , ─         )
          pparamThreshold EconomicGroup    = (vote P5b  , ─         )
          pparamThreshold TechnicalGroup   = (vote P5c  , ─         )
          pparamThreshold GovernanceGroup  = (vote P5d  , ─         )
          pparamThreshold SecurityGroup    = (─         , vote Q5   )

          P/Q5 : PParamsUpdate → Maybe ℚ × Maybe ℚ
          P/Q5 ppu = maxThreshold (mapˢ (proj₁ ∘ pparamThreshold) (updateGroups ppu))
                   , maxThreshold (mapˢ (proj₂ ∘ pparamThreshold) (updateGroups ppu))

canVote : PParams → GovAction → GovRole → Type
canVote pp a r = Is-just (threshold pp nothing a r)
```
AgdaMultiCode
% TODO: this doesn't actually depend on PParams so we could remove that
%       argument, but we don't have a default ATM
Functions related to voting
fig:ratification-requirements
figure*

## Protocol Parameters and Governance Actions
sec:protocol-parameters-and-governance-actions
Voting thresholds for protocol parameters can be set by group, and we do not require that each protocol
parameter governance action be confined to a single group. In case a governance action carries updates
for multiple parameters from different groups, the maximum threshold of all the groups involved will
apply to any given such governance action.

The purpose of the  is to add an additional check to
security-relevant protocol parameters. Any proposal that includes a
change to a security-relevant protocol parameter must also be accepted
by at least half of the SPO stake.

## Ratification Restrictions
sec:ratification-restrictions
figure*[ht]
AgdaMultiCode
```agda
record StakeDistrs : Type where
  field
    stakeDistr  : VDeleg ⇀ Coin

record RatifyEnv : Type where
  field
    stakeDistrs   : StakeDistrs
    currentEpoch  : Epoch
    dreps         : Credential ⇀ Epoch
    ccHotKeys     : Credential ⇀ Maybe Credential
    treasury      : Coin
    pools         : KeyHash ⇀ PoolParams
    delegatees    : Credential ⇀ VDeleg

record RatifyState : Type where
  field
    es              : EnactState
    removed         : ℙ (GovActionID × GovActionState)
    delay           : Bool
```
```agda

CCData : Type
CCData = Maybe ((Credential ⇀ Epoch) × ℚ)

govRole : VDeleg → GovRole
govRole (credVoter gv _)  = gv
govRole abstainRep        = DRep
govRole noConfidenceRep   = DRep

IsCC IsDRep IsSPO : VDeleg → Type
IsCC    v = govRole v ≡ CC
IsDRep  v = govRole v ≡ DRep
IsSPO   v = govRole v ≡ SPO
```
AgdaMultiCode
Types and functions for the RATIFY transition system
fig:types-and-functions-for-the-ratify-transition-system
figure*
As mentioned earlier, most governance actions must include a 
for the most recently enacted action of its given type. Consequently, two actions of the
same type can be enacted at the same time, but they must be *deliberately*
designed to do so.

fig:types-and-functions-for-the-ratify-transition-system
defines some types and functions used in the RATIFY transition
system.  is simply an alias to define some functions more
easily.

figure*[!ht]
AgdaMultiCode
```agda
actualVotes  : RatifyEnv → PParams → CCData → GovActionType
             → (GovRole × Credential ⇀ Vote) → (VDeleg ⇀ Vote)
actualVotes Γ pparams cc gaTy votes
  =   mapKeys (credVoter CC) actualCCVotes  ∪ˡ actualPDRepVotes gaTy
  ∪ˡ  actualDRepVotes                       ∪ˡ actualSPOVotes gaTy
  where
```
```agda
  roleVotes : GovRole → VDeleg ⇀ Vote
  roleVotes r = mapKeys (uncurry credVoter) (filter (λ (x , _) → r ≡ proj₁ x) votes)

  activeDReps = dom (filter (λ (_ , e) → currentEpoch ≤ e) dreps)
  spos  = filterˢ IsSPO (dom (stakeDistr stakeDistrs))
```
```agda

  getCCHotCred : Credential × Epoch → Maybe Credential
  getCCHotCred (c , e) = if currentEpoch > e then nothing
    else case lookupᵐ? ccHotKeys c of
```
```agda
        (just (just c'))  → just c'
        _                 → nothing -- no hot key or resigned

  SPODefaultVote : GovActionType → VDeleg → Vote
  SPODefaultVote gaT (credVoter SPO (KeyHashObj kh)) = case lookupᵐ? pools kh of
```
```agda
        nothing → Vote.no
        (just  p) → case lookupᵐ? delegatees (PoolParams.rewardAccount p) , gaTy of
```
```agda
               (_                     , TriggerHF)     → Vote.no
               (just noConfidenceRep  , NoConfidence)  → Vote.yes
               (just abstainRep       , _           )  → Vote.abstain
               _                                       → Vote.no
  SPODefaultVote _ _ = Vote.no

  actualCCVote : Credential → Epoch → Vote
  actualCCVote c e = case getCCHotCred (c , e) of
```
```agda
        (just c')  → maybe id Vote.no (lookupᵐ? votes (CC , c'))
        _          → Vote.abstain

  actualCCVotes : Credential ⇀ Vote
  actualCCVotes = case cc of
```
```agda
        nothing         →  ∅
        (just (m , q))  →  if ccMinSize ≤ lengthˢ (mapFromPartialFun getCCHotCred (m ˢ))
                           then mapWithKey actualCCVote m
                           else constMap (dom m) Vote.no

  actualPDRepVotes : GovActionType → VDeleg ⇀ Vote
  actualPDRepVotes NoConfidence
                      = ❴ abstainRep , Vote.abstain ❵ ∪ˡ ❴ noConfidenceRep , Vote.yes ❵
  actualPDRepVotes _  = ❴ abstainRep , Vote.abstain ❵ ∪ˡ ❴ noConfidenceRep , Vote.no ❵

  actualDRepVotes : VDeleg ⇀ Vote
  actualDRepVotes  =   roleVotes DRep
                   ∪ˡ  constMap (mapˢ (credVoter DRep) activeDReps) Vote.no

  actualSPOVotes : GovActionType → VDeleg ⇀ Vote
  actualSPOVotes gaTy = roleVotes SPO ∪ˡ mapFromFun (SPODefaultVote gaTy) spos
```
AgdaMultiCode
Vote counting
fig:defs:ratify-actualvotes
figure*

fig:defs:ratify-actualvotes defines the 
function. Given the current state about votes and other parts of the
system it calculates a new mapping of votes, which is the mapping that
will actually be used during ratification. Things such as default
votes or resignation/expiry are implemented in this way.

 is defined as the union of four voting maps,
corresponding to the constitutional committee, predefined (or auto)
DReps, regular DReps and SPOs.
itemize
\item  filters the votes based on the given governance role
  and is a helper for definitions further down.
\item if a  member has not yet registered a hot key, has ,
  or has resigned, then  returns ; if none
  of these conditions is met, then
  itemize
    \item if the  member has voted, then that vote is returned;
    \item if the  member has not voted, then the default value of  is returned.
  itemize
\item  adds a default vote of  to all active DReps
  that didn't vote.
\item  adds a default vote to all SPOs who didn't vote,
  with the default depending on the action.
itemize
Let us discuss the last item above---the way SPO votes are counted---as the ledger
specification's handling of this has evolved in response to community feedback.
Previously, if an SPO did not vote, then it would be counted as having voted
 by default.  Members of the SPO community found this behavior counterintuitive
and requested that non-voters be assigned a  vote by default, with the caveat that
an SPO could change its default setting by delegating its reward account credential
to an AlwaysNoConfidence DRep or an AlwaysAbstain DRep.
(This change applies only after the bootstrap period; during the bootstrap period
the logic is unchanged; see sec:conway-bootstrap-gov.)
To be precise, the agreed upon specification is the following: an SPO that did
not vote is assumed to have vote , except under the following circumstances:
itemize
\item if the SPO has delegated its reward credential to an
  AlwaysNoConfidence DRep, then their default vote is  for
   proposals and  for other proposals;
\item if the SPO has delegated its reward credential to an AlwaysAbstain
  DRep, then its default vote is  for all proposals.
itemize
It is important to note that the credential that can now be used to set a default
voting behavior is the credential used to withdraw staking rewards, which is not
(in general) the same as the credential used for voting.
%% And as a second layer, this means that if that credential is a script, it may need
%% to have explicit logic written to be able to set a default at all.

figure*[!ht]
```agda

  getStakeDist : GovRole → ℙ VDeleg → StakeDistrs → VDeleg ⇀ Coin
  getStakeDist CC    cc  sd  = constMap (filterˢ IsCC cc) 1
  getStakeDist DRep  _   sd  = filterKeys IsDRep  (sd .stakeDistr)
  getStakeDist SPO   _   sd  = filterKeys IsSPO   (sd .stakeDistr)

  acceptedStakeRatio : GovRole → ℙ VDeleg → StakeDistrs → (VDeleg ⇀ Vote) → ℚ
  acceptedStakeRatio r cc dists votes = acceptedStake /₀ totalStake
    where
      dist : VDeleg ⇀ Coin
      dist = getStakeDist r cc dists
      acceptedStake totalStake : Coin
      acceptedStake  = ∑[ x ← dist ∣ votes ⁻¹ Vote.yes                              ] x
      totalStake     = ∑[ x ← dist ∣ dom (votes ∣^ (❴ Vote.yes ❵ ∪ ❴ Vote.no ❵))  ] x

  acceptedBy : RatifyEnv → EnactState → GovActionState → GovRole → Type
  acceptedBy Γ (record { cc = cc , _; pparams = pparams , _ }) gs role =
    let open GovActionState gs; open PParams pparams
        votes'  = actualVotes Γ pparams cc (gaType action) votes
        mbyT    = threshold pparams (proj₂ <$> cc) action role
        t       = maybe id 0ℚ mbyT
    in acceptedStakeRatio role (dom votes') (stakeDistrs Γ) votes' ≥ t
     ∧ (role ≡ CC → maybe (λ (m , _) → lengthˢ m) 0 cc ≥ ccMinSize ⊎ Is-nothing mbyT)

  accepted : RatifyEnv → EnactState → GovActionState → Type
  accepted Γ es gs = acceptedBy Γ es gs CC ∧ acceptedBy Γ es gs DRep ∧ acceptedBy Γ es gs SPO

  expired : Epoch → GovActionState → Type
  expired current record { expiresIn = expiresIn } = expiresIn < current
```
Functions related to ratification
fig:defs:ratify-defs-i
figure*

fig:defs:ratify-defs-i defines the  and 
functions (together with some helpers) that are used in the rules of
RATIFY.
itemize
  \item  computes the stake distribution based on the
    given governance role and the corresponding delegations. Note that
    every constitutional committe member has a stake of 1, giving them
    equal voting power. However, just as with other delegation, multiple
    CC members can delegate to the same hot key, giving that hot key
    the power of those multiple votes with a single actual vote.
  \item  is the ratio of accepted stake. It is
    computed as the ratio of  votes over the votes that didn't
    . The latter is equivalent to the sum of  and  votes.
    The special division symbol /₀ indicates that in case
    of a division by 0, the numbers 0 should be returned. This implies
    that in the absence of stake, an action can only pass if the
    threshold is also set to 0.
  \item  looks up the threshold in the  table and
    compares it to the result of .
  \item  then checks if an action is accepted by all roles; and
  \item  checks whether a governance action is expired in a given epoch.
itemize
figure*[ht]
AgdaMultiCode
```agda
verifyPrev : (a : GovActionType) → NeedsHash a → EnactState → Type
verifyPrev NoConfidence     h es  = h ≡ es .cc .proj₂
verifyPrev UpdateCommittee  h es  = h ≡ es .cc .proj₂
verifyPrev NewConstitution  h es  = h ≡ es .constitution .proj₂
verifyPrev TriggerHF        h es  = h ≡ es .pv .proj₂
verifyPrev ChangePParams    h es  = h ≡ es .pparams .proj₂
verifyPrev TreasuryWdrl     _ _   = ⊤
verifyPrev Info             _ _   = ⊤

delayingAction : GovActionType → Bool
delayingAction NoConfidence     = true
delayingAction UpdateCommittee  = true
delayingAction NewConstitution  = true
delayingAction TriggerHF        = true
delayingAction ChangePParams    = false
delayingAction TreasuryWdrl     = false
delayingAction Info             = false

delayed : (a : GovActionType) → NeedsHash a → EnactState → Bool → Type
delayed gaTy h es d = ¬ verifyPrev gaTy h es ⊎ d ≡ true

acceptConds : RatifyEnv → RatifyState → GovActionID × GovActionState → Type
acceptConds Γ stʳ (id , st) =
       accepted Γ es st
    ×  ¬ delayed (gaType action) prevAction es delay
    × ∃[ es' ]  ⟦ id , treasury , currentEpoch ⟧ ⊢ es ⇀⦇ action ,ENACT⦈ es'
```
AgdaMultiCode
Functions related to ratification, continued
fig:defs:ratify-defs-ii
figure*

fig:defs:ratify-defs-ii defines functions that deal with
delays and the acceptance criterion for ratification.  A given action
can either be delayed if the action contained in  isn't the
one the given action is building on top of, which is checked by
, or if a previous action was a .  Note that
 affects the future: whenever a  is
accepted all future actions are delayed.   then expresses the
condition whether an action is delayed. This happens either because
the previous action doesn't match the current one, or because the
previous action was a delaying one. This information is passed in as
an argument.

figure*[ht]
AgdaMultiCode
```agda
  _⊢_⇀⦇_,RATIFY⦈_ : RatifyEnv → RatifyState → GovActionID × GovActionState → RatifyState → Type

_⊢_⇀⦇_,RATIFIES⦈_  : RatifyEnv → RatifyState → List (GovActionID × GovActionState)
                   → RatifyState → Type
```
AgdaMultiCode
Types of the RATIFY and RATIFIES transition systems
figure*

figure*[ht]
AgdaSuppressSpace
```agda
  RATIFY-Accept :
    let treasury       = Γ .treasury
        e              = Γ .currentEpoch
        (gaId , gaSt)  = a
        action         = gaSt .action
    in
    ∙ acceptConds Γ ⟦ es , removed , d ⟧ a
    ∙ ⟦ gaId , treasury , e ⟧ ⊢ es ⇀⦇ action ,ENACT⦈ es'
      ────────────────────────────────
      Γ ⊢ ⟦ es  , removed         , d                     ⟧ ⇀⦇ a ,RATIFY⦈
          ⟦ es' , ❴ a ❵ ∪ removed , delayingAction (gaType action) ⟧

  RATIFY-Reject :
    let e              = Γ .currentEpoch
        (gaId , gaSt)  = a
    in
    ∙ ¬ acceptConds Γ ⟦ es , removed , d ⟧ a
    ∙ expired e gaSt
      ────────────────────────────────
      Γ ⊢ ⟦ es , removed , d ⟧ ⇀⦇ a ,RATIFY⦈ ⟦ es , ❴ a ❵ ∪ removed , d ⟧

  RATIFY-Continue :
     let e              = Γ .currentEpoch
         (gaId , gaSt)  = a
     in
     ∙ ¬ acceptConds Γ ⟦ es , removed , d ⟧ a
     ∙ ¬ expired e gaSt
       ────────────────────────────────
       Γ ⊢ ⟦ es , removed , d ⟧ ⇀⦇ a ,RATIFY⦈ ⟦ es , removed , d ⟧

_⊢_⇀⦇_,RATIFIES⦈_ = ReflexiveTransitiveClosure {sts = _⊢_⇀⦇_,RATIFY⦈_}
```
AgdaSuppressSpace
The RATIFY transition system
fig:sts:ratify
figure*

The RATIFIES transition system is defined as the reflexive-transitive
closure of RATIFY, which is defined via three rules, defined in
fig:sts:ratify.
%
itemize
  \item  checks if the votes for a given  meet the
    threshold required for acceptance, that the action is accepted and not delayed,
    and  ratifies the action.
%
  \item  asserts that the given  is not 
    and ; it removes the governance action.
%
  \item  covers the remaining cases and keeps the 
    around for further voting.
itemize
%
Note that all governance actions eventually either get accepted and enacted via  or
rejected via . If an action satisfies all criteria to be accepted but cannot be
enacted anyway, it is kept around and tried again at the next epoch boundary.

We never remove actions that do not attract sufficient  votes before they expire, even if it
is clear to an outside observer that this action will never be enacted. Such an action will simply
keep getting checked every epoch until it expires.
