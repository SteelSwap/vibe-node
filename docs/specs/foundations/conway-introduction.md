# Introduction
sec:introduction

Conway
This is the specification of the Conway era of the Cardano ledger. As
with previous specifications, this document is an incremental
specification, so everything that isn't defined here refers to the
most recent definition from an older specification.
Conway

NoConway
This is the work-in-progress specification of the Cardano ledger.
The Agda source code with which we formalize the ledger specification and which
generates this pdf document is open source and resides at the following
center
repository: \repourl
center

The current status of each individual era is described in Table fig:eras-progress.

longtable[h!]{|l l l l|}
\hline
Era  & Figures & Prose & Cleanup \\
\hline
\endhead
Shelley~shelley-ledger-spec & Partial & Partial & Not started \\
Shelley-MA~shelley-ma-ledger-spec & Partial & Partial & Not started \\
Alonzo~alonzo-ledger-spec & Partial & Partial & Not started \\
Babbage~babbage-ledger-spec & Not started & Not started & Not started \\
Conway~cip1694 & Complete & Partial & Partial \\
\hline
Specification progress
fig:eras-progress
longtable

## Overview
sec:overview
This document describes, in a precise and executable way, the behavior of the Cardano ledger
that can be updated in response to a series of events.  Because of the precise nature
of the document, it can be dense and difficult to read at times, and it can be
helpful to have a high-level understanding of what it is trying to describe, which we
present below.  Keep in mind that this section focuses on intuition, using
terms (set in italics) which may be unfamiliar to some readers, but rest assured that
later sections of the document will make the intuition and italicized terms precise.
NoConway


## A Note on Agda
This specification is written using the
\hrefAgdaWiki[Agda programming language and proof assistant]~agda2024.
We have made a considerable effort to ensure
that this document is readable by people unfamiliar with Agda (or other proof
assistants, functional programming languages, etc.).  However, by the
nature of working in a formal language we have to play by its rules,
meaning that some instances of uncommon notation are very difficult or
impossible to avoid.  Some are explained in
sec:notation,sec:appendix-agda-essentials,
but there is no guarantee that those sections are complete.  If the meaning of an
expression is confusing or unclear, please \repourl/issues{open an issue} in
the \repourl{formal ledger repository} with the `notation' label.

## Separation of Concerns
The *Cardano Node* consists of three pieces,
itemize
  \item a networking layer responsible for sending messages across the internet,
  \item a consensus layer establishing a common order of valid blocks, and
  \item a ledger layer which determines whether a sequence of blocks is valid.
itemize
Because of this separation, the ledger can be modeled as a state machine,
\[
  s \xrightarrow[X]{b} s'.
\]
More generally, we will consider state machines with an environment,
\[
  Γ ⊢ s \xrightarrow[X]{b} s'.
\]
These are modelled as 4-ary relations between the environment \(Γ\), an
initial state \(s\), a signal \(b\) and a final state \(s'\). The ledger consists of
roughly 25 (depending on the version) such relations that depend on each
other, forming a directed graph that is almost a tree.
NoConway
(See fig:latest-sts-diagram.)
NoConway
% TODO: Uncomment the next line and replace XXXX with ref to cardano-ledger.pdf.
% Conway(See XXXX.Conway
Thus each such relation represents the transition rule of the state machine; \(X\) is
simply a placeholder for the name of the transition rule.

NoConway
## Ledger State Transition Rules
sec:ledger-state-transition-rules
By a ledger we mean a structure that contains information about
how funds in the system are distributed accross accounts---that is, account
balances, how such balances should be adjusted when transactions and
proposals are processed, the ADA currently held in the treasury reserve, a
list of stake pools operating the network, and so on.

The ledger can be updated in response to certain events, such as receiving a new
transaction, time passing and crossing an epoch boundary, enacting a
governance proposal, to name a few.  This document defines, as part of the
behaior of the ledger, a set of rules that determine which events are valid and
exactly how the state of the ledger should be updated in response to those events.
The primary aim of this document is to provide a precise description of this
system---the ledger state, valid events and the rules for processing them.

We will model this via a number of state transition systems (STS) which
from now on we refer to as ``transition rules'' or just ``rules.''
These rules describe the different behaviors that determine how the whole system
evolves and, taken together, they comprise a full description of the ledger protocol.
Each transition rule consists of the following components:
itemize
  \item an environment consisting of data, read from the ledger state
        or the outside world, which should be considered constant for the
        purposes of the rule;
  \item an initial state, consisting of the subset of the full ledger
        state that is relevant to the rule and which the rule can update;
  \item a signal or event, with associated data, that the
        rule can receive or observe;
  \item a set of preconditions that must be met in order for the transition
        to be valid;
  \item a new state that results from the transition rule.
itemize
For example, the UTXOW transition rule defined in fig:rules:utxow of
sec:witnessing checks that, among other things, a given transaction is signed
by the appropriate parties.

The transition rules can be composed in the sense that they may require other
transition rules to hold as part of their preconditions.  For example, the UTXOW rule
mentioned above requires the UTXO rule, which checks that the inputs to the
transaction exist, that the transaction is balanced, and several other conditions.

figure[h!]
  \centering
  Diagrams/CardanoLedger
  \caption{State transition rules of the ledger specification, presented as a
  directed graph; each node represents a transition rule; an arrow from rule A to
  rule B indicates that B appears among the premises of A; a dotted arrow represents
  a dependency in the sense that the output of the target node is an input to the
  source node, either as part of the source state, the environment or the event
    (\ConwayColor~rules added in Conway;
     \BabbageColor~rules modified in Conway; dotted ellipses represent rules
  that are not yet formalized in Agda).
  }
  fig:latest-sts-diagram
figure

A brief description of each transition rule is provided below, with a link to
an Agda module and reference to a section where the rule is formally defined.

itemize
\item
  Chain{CHAIN} is the top level transition in response to a new
  block that applies the NEWEPOCH transition when crossing an epoch boundary, and the
  LEDGERS transition on the list of transactions in the body (sec:blockchain-layer).
\item
  Epoch{NEWEPOCH} computes the new state as of the start of a new
  epoch; includes the previous EPOCH transition (sec:epoch-boundary).
\item
  Epoch{EPOCH} computes the new state as of the end of an epoch;
  includes the ENACT, RATIFY, and SNAP transition rules (sec:epoch-boundary).
\item
  Ratify{RATIFY} decides whether a pending governance action has
  reached the thresholds it needs to be ratified (sec:ratification).
\item
  Enact{ENACT} applies the result of a previously ratified
  governance action, such as triggering a hard fork or updating the protocol
  parameters (sec:enactment).
\item
  Epoch{SNAP} computes new stake distribution snapshots (sec:epoch-boundary).
\item
  Ledger{LEDGERS} applies LEDGER repeatedly as needed, for each
  transaction in a list of transactions (sec:ledger).
\item
  Ledger{LEDGER} is the full state update in response to a
  single transaction; it includes the UTXOW, GOV, and CERTS rules (sec:ledger).
\item
  Certs{CERTS} applies CERT repeatedly for each certificate in
  the transaction (sec:certificates).
\item
  Certs{CERT} combines DELEG, POOL, GOVCERT transition rules,
  as well as some additional rules shared by all three (sec:certificates).
\item
  Certs{DELEG} handles registering stake addresses and delegating
  to a stake pool (sec:certificates).
\item
  Certs{GOVCERT} handles registering and delegating to DReps (sec:certificates).
\item
  Certs{POOL} handles registering and retiring stake pools (sec:certificates).
\item
  Gov{GOV} handles voting and submitting governance proposals (sec:governance).
\item
  Utxow{UTXOW} checks that a transaction is witnessed correctly
  with the appropriate signatures, datums, and scripts; includes the UTXO transition
  rule (sec:witnessing).
\item
  Utxo{UTXO} checks core invariants for an individual transaction
  to be valid, such as the transaction being balanced, fees being paid, etc; include
  the UTXOS transition rule (sec:utxo).
\item
  Utxo{UTXOS} checks that any relevant scripts needed by the
  transaction evaluate to true (sec:utxo).
itemize
NoConway

## Reflexive-transitive Closure

Some state transition rules need to be applied as many times as possible to arrive at
a final state.  Since we use this pattern multiple times, we define a closure
operation which takes a transition rule and applies it as many times as possible.

The closure  of a relation  is defined in fig:rt-closure.
In the remainder of the text, the closure operation is called .

figure*[htb]
Reflexive transitive closure
AgdaMultiCode
*Closure type*
```agda
  data _⊢_⇀⟦_⟧*_ : C → S → List Sig → S → Type where

```
*Closure rules*
```agda
    RTC-base :
      Γ ⊢ s ⇀⟦ [] ⟧* s

    RTC-ind :
      ∙ Γ ⊢ s  ⇀⟦ sig  ⟧  s'
      ∙ Γ ⊢ s' ⇀⟦ sigs ⟧* s''
      ───────────────────────────────────────
      Γ ⊢ s ⇀⟦ sig ∷ sigs ⟧* s''
```
AgdaMultiCode
fig:rt-closure
figure*

## Computational

Since all such state machines need to be evaluated by the nodes and all
nodes should compute the same states, the relations specified by them
should be computable by functions. This can be captured by the
definition in fig:computational which is parametrized
over the state transition relation.

figure*[htb]
AgdaMultiCode
```agda
record Computational (_⊢_⇀⦇_,X⦈_ : C → S → Sig → S → Type) : Type where
  field
    compute     : C → S → Sig → Maybe S
    ≡-just⇔STS  : compute Γ s b ≡ just s' ⇔ Γ ⊢ s ⇀⦇ b ,X⦈ s'

  nothing⇒∀¬STS : compute Γ s b ≡ nothing → ∀ s' → ¬ Γ ⊢ s ⇀⦇ b ,X⦈ s'
```
AgdaMultiCode
Computational relations
fig:computational
figure*

Unpacking this, we have a  function that computes a final
state from a given environment, state and signal. The second piece is
correctness:  succeeds with some final state if and only if
that final state is in relation to the inputs.

This has two further implications:

itemize
\item Since  is a function, the state transition relation is necessarily
a (partial) function; i.e., there is at most one possible final state for each
input data.  Otherwise, we could prove that  could evaluates to
two different states on the same inputs, which is impossible since it
is a function.
\item The actual definition of  is irrelevant---any two
implementations of  have to produce the same result on any
input. This is because we can simply chain the equivalences for two
different  functions together.
itemize

What this all means in the end is that if we give a 
instance for every relation defined in the ledger, we also have an
executable version of the rules which is guaranteed to be
correct. This is indeed something we have done, and the same source
code that generates this document also generates a Haskell library
that lets anyone run this code.

## Sets \& Maps
sec:sets-maps
The ledger heavily uses set theory. For various reasons it was
necessary to implement our own set theory (there will be a paper on this
some time in the future). Crucially, the set theory is completely
abstract (in a technical sense---Agda has an abstract keyword) meaning
that implementation details of the set theory are
irrelevant. Additionally, all sets in this specification are finite.

We use this set theory to define maps as seen below, which are used in
many places. We usually think of maps as partial functions
(i.e., functions not necessarily defined everywhere---equivalently, "left-unique"
relations) and we use the harpoon arrow ⇀ to
distinguish such maps from standard Agda functions which use →.
The figure below also gives notation for the powerset operation, ,
used to form a type of sets with elements in a given type,
as well as the subset relation and the equality relation for sets.

When we need to convert a list l to its set of elements,
we write ~l.
figure*[h]
```agda
_⊆_ : {A : Type} → ℙ A → ℙ A → Type
X ⊆ Y = ∀ {x} → x ∈ X → x ∈ Y

_≡ᵉ_ : {A : Type} → ℙ A → ℙ A → Type
X ≡ᵉ Y = X ⊆ Y × Y ⊆ X

Rel : Type → Type → Type
Rel A B = ℙ (A × B)

left-unique : {A B : Type} → Rel A B → Type
left-unique R = ∀ {a b b'} → (a , b) ∈ R → (a , b') ∈ R → b ≡ b'

_⇀_ : Type → Type → Type
A ⇀ B = r ∈ Rel A B ﹐ left-unique r
```
figure*

## Propositions as Types, Properties and Relations
sec:prop-as-types
In type theory we represent propositions as types and proofs of a proposition as
elements of the corresponding type.
A unary predicate is a function that takes each x (of some type A) and
returns a proposition P(x). Thus, a predicate is a function of type
A~→~.
A binary relation R between A and B is a
function that takes a pair of values x and y and returns a proposition
asserting that the relation R holds between x and y.
Thus, such a relation is a function of type
A~×~B~→~
or A~→~B~→~.

These relations are typically required to be decidable, which means
that there is a boolean-valued function that computes whether the
predicate holds or not. This means that it is generally safe to think
of predicates simply returning a boolean value instead.
