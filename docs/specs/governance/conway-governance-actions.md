# Governance Actions
sec:governance-actions
\LedgerModule{GovernanceActions}.

We introduce the following distinct bodies with specific functions in the new governance framework:
enumerate
  \item a constitutional committee (henceforth called );
  \item a group of delegate representatives (henceforth called );
  \item the stake pool operators (henceforth called ).
enumerate


figure*[ht]
AgdaMultiCode
```agda
data GovRole : Type where
  CC DRep SPO : GovRole

Voter        = GovRole × Credential
GovActionID  = TxId × ℕ

data VDeleg : Type where
  credVoter        : GovRole → Credential →  VDeleg
  abstainRep       :                         VDeleg
  noConfidenceRep  :                         VDeleg

record Anchor : Type where
  field
    url   : String
    hash  : DocHash

data GovActionType : Type where
  NoConfidence     : GovActionType
  UpdateCommittee  : GovActionType
  NewConstitution  : GovActionType
  TriggerHF        : GovActionType
  ChangePParams    : GovActionType
  TreasuryWdrl     : GovActionType
  Info             : GovActionType

GovActionData : GovActionType → Type
GovActionData NoConfidence     = ⊤
GovActionData UpdateCommittee  = (Credential ⇀ Epoch) × ℙ Credential × ℚ
GovActionData NewConstitution  = DocHash × Maybe ScriptHash
GovActionData TriggerHF        = ProtVer
GovActionData ChangePParams    = PParamsUpdate
GovActionData TreasuryWdrl     = RwdAddr ⇀ Coin
GovActionData Info             = ⊤

record GovAction : Type where
```
```agda
  field
    gaType : GovActionType
    gaData : GovActionData gaType
```
AgdaMultiCode
Governance actions
defs:governance
figure*
defs:governance defines several data types used to represent
governance actions. The type  is abstract but in the
implementation it will be instantiated with a 32-bit hash type (like
e.g.\@ ). We keep it separate because it is used for a
different purpose.
%
itemize
  \item : a unique identifier for a governance action, consisting of the
     of the proposing transaction and an index to identify a proposal within a transaction;
  \item  (governance role): one of three available voter roles
    defined above (, , );
  \item  (voter delegation): one of three ways to delegate votes: by credential,
    abstention, or no confidence (, , or );
  \item : a url and a document hash;
  \item  (governance action): one of seven possible actions
    (see fig:types-of-governance-actions for definitions);
itemize

The governance actions carry the following information:
%
itemize
  \item : a map of credentials and terms to add and a set of
    credentials to remove from the committee;
  \item : a hash of the new constitution document and an optional proposal policy;
  \item : the protocol version of the epoch to hard fork into;
  \item : the updates to the parameters; and
  \item : a map of withdrawals.
itemize
figure*[h]
longtable[]{@{}
 >{\raggedright\arraybackslash}p{(\columnwidth - 2\tabcolsep) * 0.2}
 >{\raggedright\arraybackslash}p{(\columnwidth - 2\tabcolsep) * 0.75}@{}}
**Action**  & **Description**\\
\hline

            & a motion to create a *state of no-confidence* in the current constitutional committee \\[10pt]
         & changes to the members of the constitutional committee and/or to its signature threshold and/or terms \\[10pt]
         & a modification to the off-chain Constitution and the proposal policy script \\[10pt]
\footnotemark  & triggers a non-backwards compatible upgrade of the network; requires a prior software upgrade  \\[10pt]
           & a change to *one or more* updatable protocol parameters, excluding changes to major protocol versions (``hard forks'')\\[10pt]
            & movements from the treasury\\
                    & an action that has no effect on-chain, other than an on-chain record
longtable
Types of governance actions
fig:types-of-governance-actions
figure*
\footnotetext{There are many varying definitions of the term ``hard fork'' in the blockchain industry. Hard forks typically refer
  to non-backwards compatible updates of a network. In Cardano, we attach a bit more meaning to the definition by calling any upgrade that
  would lead to *more blocks* being validated a ``hard fork'' and force nodes to comply with the new protocol version, effectively
  rendering a node obsolete if it is unable to handle the upgrade.}

% ## Voting and Ratification
% sec:voting-and-ratification
% Every governance action must be ratified by at least two of these three bodies using their on-chain votes.
% The type of action and the state of the governance system determines which bodies must ratify it.
% Ratified actions are then enacted on-chain, following a set of rules (see sec:enactment,fig:enactment-types).

## Hash Protection
sec:hash-protection

For some governance actions, in addition to obtaining the necessary votes,
enactment requires that the following condition is also satisfied: the state
obtained by enacting the proposal is in fact the state that was intended when
the proposal was submitted.  This
is achieved by requiring actions to unambiguously link to the state
they are modifying via a pointer to the previous modification. A
proposal can only be enacted if it contains the  of the
previously enacted proposal modifying the same piece of
state.   and  modify the same state, while
every other type of governance action has its own state that isn't
shared with any other action. This means that the enactibility of a
proposal can change when other proposals are enacted.

However, not all types of governance actions require this strict
protection.  For  and , enacting them does not change
the state in non-commutative ways, so they can always be enacted.

Types related to this hash protection scheme are defined
in fig:needshash-and-hashprotected-types.

figure*[h]
```agda
NeedsHash : GovActionType → Type
NeedsHash NoConfidence     = GovActionID
NeedsHash UpdateCommittee  = GovActionID
NeedsHash NewConstitution  = GovActionID
NeedsHash TriggerHF        = GovActionID
NeedsHash ChangePParams    = GovActionID
NeedsHash TreasuryWdrl     = ⊤
NeedsHash Info             = ⊤

HashProtected : Type → Type
HashProtected A = A × GovActionID
```
NeedsHash and HashProtected types
fig:needshash-and-hashprotected-types
figure*


figure*[htb]
AgdaMultiCode
```agda
data Vote : Type where
  yes no abstain  : Vote

record GovVote : Type where
  field
    gid         : GovActionID
    voter       : Voter
    vote        : Vote
    anchor      : Maybe Anchor

record GovProposal : Type where
  field
    action      : GovAction
    prevAction  : NeedsHash (gaType action)
    policy      : Maybe ScriptHash
    deposit     : Coin
    returnAddr  : RwdAddr
    anchor      : Anchor

record GovActionState : Type where
  field
    votes       : Voter ⇀ Vote
    returnAddr  : RwdAddr
    expiresIn   : Epoch
    action      : GovAction
    prevAction  : NeedsHash (gaType action)
```
AgdaMultiCode
Vote and proposal types
defs:governance-votes
figure*
## Votes and Proposals

figure*[htb]
```agda
getDRepVote : GovVote → Maybe Credential
getDRepVote record { voter = (DRep , credential) }  = just credential
getDRepVote _                                       = nothing

proposedCC : GovAction → ℙ Credential
proposedCC ⟦ UpdateCommittee , (x , _ , _) ⟧ᵍᵃ  = dom x
proposedCC _                                    = ∅
```
Governance helper function
figure*

The data type  represents the different voting options: ,
, or . For a  to be cast, it must be packaged together
with further information, such as who votes and for which governance
action. This information is combined in the  record. An
optional  can be provided to give context about why a vote was
cast in a certain manner.

To propose a governance action, a  needs to be
submitted. Beside the proposed action, it contains:
itemize
\item a pointer to the previous action if required (see sec:hash-protection),
\item a pointer to the proposal policy if one is required,
\item a deposit, which will be returned to , and
\item an , providing further information about the proposal.
itemize

While the deposit is held, it is added to the deposit pot, similar to
stake key deposits. It is also counted towards the voting stake (but
not the block production stake) of the reward address to which it will
be returned, so as not to reduce the submitter's voting power when
voting on their own (and competing) actions. For a proposal to be
valid, the deposit must be set to the current value of
. The deposit will be returned when the action is
removed from the state in any way.

 is the state of an individual governance action. It
contains the individual votes, its lifetime, and information necessary
to enact the action and to repay the deposit.
