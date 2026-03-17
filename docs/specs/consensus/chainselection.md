# Chain Selection {#chainsel}

Chain selection is one of the central responsibilities of the chain database ([\[chaindb\]](#chaindb){reference-type="ref+label" reference="chaindb"}). It of course depends on chain selection as it is defined by the consensus protocol ([\[consensus:class:chainsel\]](#consensus:class:chainsel){reference-type="ref+label" reference="consensus:class:chainsel"}), but needs to take care of a lot of operational concerns. In this chapter we will take a closer look at the implementation of chain selection in the chain database, and state some properties and sketch some proofs to motivate it.

## Comparing anchored fragments {#chainsel:fragments}

### Introduction

Recall from [\[consensus:overview:chainsel\]](#consensus:overview:chainsel){reference-type="ref+label" reference="consensus:overview:chainsel"} that while in the literature chain selection is defined in terms of comparisons between entire chains, we instead opted to model it in terms of a comparison between the *headers* at the tip of those chains (or rather, a *view* on those headers defined by the specific consensus protocol).

We saw in [\[storage:inmemory\]](#storage:inmemory){reference-type="ref+label" reference="storage:inmemory"} (specifically, [\[storage:fragments\]](#storage:fragments){reference-type="ref+label" reference="storage:fragments"}) that the consensus layer stores chain fragments in memory (the most recent headers on a chain), both for the node's own current chain as well as for upstream nodes (which we refer to as "candidate chains"). Defining chain selection in terms of fragments is straight-forward when those fragments are non-empty: we simply take the most recent header, extract the view required by the consensus protocol ([\[BlockSupportsProtocol\]](#BlockSupportsProtocol){reference-type="ref+label" reference="BlockSupportsProtocol"}), and then use the consensus protocol's chain selection interface to compare them. The question is, however, how to compare two fragments when one (or both) of them is *empty*. This problem is more subtle than it might seem at first sight, and requires careful consideration.

We mentioned in [\[consensus:overview:chainsel\]](#consensus:overview:chainsel){reference-type="ref+label" reference="consensus:overview:chainsel"} that consensus imposes a fundamental assumption that the strict extension of a chain is always (strictly) preferred over that chain ([\[prefer-extension\]](#prefer-extension){reference-type="ref+label" reference="prefer-extension"}), and that consequently we *always* prefer a non-empty chain over an empty one (and conversely we *never* prefer an empty chain over a non-empty one). However, chain fragments are mere proxies for their chains, and the fragment might be empty even if the chain is not. This means that in principle it's possible we do not prefer a non-empty fragment over an empty one, or indeed prefer an empty fragment over a non-empty one. However, when a fragment is empty, we cannot rely on the consensus protocol's chain selection because we have no header to give it.

Let's consider under which conditions these fragments might be empty:

Our fragment

:   Our own fragment is a path through the volatile database, anchored at the tip of the immutable database ([\[storage:fragments\]](#storage:fragments){reference-type="ref+label" reference="storage:fragments"}). Under normal circumstances, it will be empty only if our *chain* is empty; we will refer to such empty fragments as *genuinely empty*.[^1] However, our fragment can also be empty even when our chain is not, if due to data loss the volatile database is empty (or contains no blocks that fit onto the tip of the immutable database).

Candidate fragment

:   A *genuinely* empty candidate fragment, representing an empty candidate chain, is never preferred over our chain. Unfortunately, however, the candidate fragment as maintained by the chain sync client ([\[chainsyncclient\]](#chainsyncclient){reference-type="ref+label" reference="chainsyncclient"}) can essentially be empty at any point due to the way that a switch-to-fork is implemented in terms of rollback followed by roll forward: after a maximum rollback (and before the roll forward), the candidate fragment is empty.

### Precondition {#chainsel:fragments:precondition}

Since neither of these circumstances can be avoided, we must therefore impose a precondition for chain selection between chain fragments to be definable:

::: definition
The two fragments must either both be non-empty, or they must intersect.
:::

In this chapter, we establish this precondition in two different ways:

1.  When we construct candidates chains (potential chains that we may wish to replace our own chain with), those candidate chains must intersect with our own chain within $k$ blocks from its tip; after all, if that is not the case, we would induce a roll back of more than $k$ blocks ([\[consensus:overview:k\]](#consensus:overview:k){reference-type="ref+label" reference="consensus:overview:k"}).

2.  When we compare fragments to each other, we only compare fragments from a set of fragments that are all anchored at the same point (i.e., the anchor of all fragments in the set is the same, though it might be different from the anchor of our current fragment). Since they are all anchored at the same point, they trivially all intersect with each other.

There is one more use of fragment selection, which is rather more subtle; we will come back to this in [\[chainsyncclient:plausiblecandidates\]](#chainsyncclient:plausiblecandidates){reference-type="ref+label" reference="chainsyncclient:plausiblecandidates"}.

TODO: Throughout we are talking about *anchored* fragments here. We should make sure that we discuss those somewhere.

### Definition {#chainsel:fragments:definition}

We will now show that this precondition suffices to compare two fragments, whether or not they are empty; we'll consider each case in turn.

Both fragments empty

:   Since the two fragments must intersect, that intersection point can only be the two anchor points, which must therefore be equal. This means that two fragments represent the same chain: neither fragment is preferred over the other.

First fragment non-empty, second fragment empty

:   Since the two fragments must intersect, that intersection can only be the anchor of the second fragment, which can lie anywhere on the first fragment.

    - If it lies at the *tip* of the first fragment, the two fragments represent the same chain, and neither is preferred over the other.

    - If it lies *before* the tip of first fragment, the first fragment is a strict extension of the second, and is therefore is preferred over the second.

First fragment empty, second fragment non-empty

:   This case is entirely symmetric to the previous; if the intersection is the tip of the second fragment, the fragments represent the same chain. Otherwise, the second fragment is a strict extension of the first, and is therefore preferred.

Both fragments non-empty

:   In this case, we can simply use the consensus protocol chain selection API to compare the two most recent headers on both fragments.

Note that this relies critically on the "prefer extension" rule ([\[prefer-extension\]](#prefer-extension){reference-type="ref+label" reference="prefer-extension"}).

## Preliminaries {#chainsel:spec}

Recall from [\[storage:components\]](#storage:components){reference-type="ref+label" reference="storage:components"} that the immutable database stores a linear chain, terminating in the *tip* $I$ of the immutable database. The volatile database stores a (possibly fragmented) tree of extensions to that chain:

::: center
:::

The node's *current chain* is stored in memory as a chain fragment through the volatile database, anchored at $I$. When we start up the node, the chain database must find the best possible path through the volatile database and adopt that as our current fragment; every time a new block is added to the volatile database, we have to recompute the new best possible path. In other words, we maintain the following invariant:

::: definition
[]{#current-chain-invariant label="current-chain-invariant"} The current chain is the best possible path through the volatile DB.
:::

"Best" of course is according to the chain selection rule defined by the consensus protocol ([\[consensus:class:chainsel\]](#consensus:class:chainsel){reference-type="ref+label" reference="consensus:class:chainsel"}). In this section we describe how the chain database establishes and preserves this invariant.

### Notation

So far we have been relatively informal in our description of chain selection, but in order to precisely describe the algorithm and state some of its properties, we have to introduce some notation.

::: definition
We will model chain selection as a transitive binary relation ($\mathrel{\sqsubset}$) between valid chains (it is undefined for invalid chains), and let $C \mathrel{\sqsubseteq}C'$ if and only if $C \mathrel{\sqsubset}C'$ or $C = C'$. It follows that ($\mathrel{\sqsubseteq}$) is a partial order (reflexive, antisymmetric, and transitive).
:::

For example, the simple "prefer longest chain" chain selection rule could be given as $$\begin{equation*}
\tag{longest chain rule}
C \mathrel{\sqsubset}C'  \qquad\mathrm{iff\qquad}\mathrm{length \; C} < \mathrm{length \; C'}
\end{equation*}$$

In general of course the exact rule depends on the choice of consensus protocol. [\[prefer-extension\]](#prefer-extension){reference-type="ref+Label" reference="prefer-extension"} ([\[consensus:overview:chainsel\]](#consensus:overview:chainsel){reference-type="ref+label" reference="consensus:overview:chainsel"}) can now be rephrased as $$\begin{equation}
\label{eq:prefer-extension}
\forall C, B .\;C \mathrel{\sqsubset}(C \mathrel{\triangleright}B)
\end{equation}$$

We will not be comparing whole chains, but rather chain fragments (we will leave the anchor of fragments implicit):

::: definition
We lift $\mathrel{\sqsubset}$ to chain fragments in the manner described in [1.1](#chainsel:fragments){reference-type="ref+label" reference="chainsel:fragments"}; this means that $\mathrel{\sqsubset}$ is undefined for two fragments if they do not intersect ([1.1.2](#chainsel:fragments:precondition){reference-type="ref+label" reference="chainsel:fragments:precondition"}).
:::

We also lift $\mathrel{\sqsubseteq}$ to *sets* of fragments, intuitively indicating that a particular fragment is the "best choice" out of a set $\mathcal{S}$ of candidate fragments:

::: definition
$$\begin{equation*}
\mathcal{S} \mathrel{\sqsubseteq}F  \qquad\mathrm{iff\qquad}\nexists F' \in \mathcal{S} .\;F \mathrel{\sqsubset}F'
\end{equation*}$$ (in other words, if additionally $F \in \mathcal{S}$, then $F$ is a maximal element of $C$). This inherits all the preconditions of $\mathrel{\sqsubseteq}$ on chains and fragments.
:::

Finally, we will introduce some notation for *computing* candidate fragments:[^2]

::: definition
Given some set of blocks $V$, and some anchor $A$ (with $A$ either a block or the genesis point), $$\mathsf{candidates_A(V)}$$ is the set of chain fragments anchored at $A$ using blocks picked from $V$.
:::

By construction all fragments in $\mathsf{candidates_A(V)}$ have the same anchor, and hence all intersect (at $A$); this will be important for the use of the $\mathrel{\sqsubseteq}$ operator.

### Properties

In the following we will use ($F \mathrel{\triangleright}B$) to denote appending block $B$ to chain $F$, and lift this notation to sets, so that for some set of blocks $\mathcal{B}$ we have $$\begin{equation*}
F \mathrel{\triangleright}\mathcal{B} = \{ F \mathrel{\triangleright}B \mid B \in \mathcal{B} \}
\end{equation*}$$

::: lemma
[]{#candidates:properties label="candidates:properties"} The set of candidates computed by $\mathsf{candidates_A(V)}$ has the following properties.

1.  []{#candidates:prefixclosed label="candidates:prefixclosed"} It is prefix closed: $$\begin{equation*}
    \forall F, B .\;
    \mathrm{if \quad (F \mathrel{\triangleright}B) \in \mathsf{candidates_A(V)} \quad \mathrm{then} \quad F \in \mathsf{candidates_A(V)}}
    \end{equation*}$$

2.  []{#candidates:appendnew label="candidates:appendnew"} If we add a new block into the set, we can append that block to existing candidates (where it fits): $$\begin{equation*}
    \mathrm{if \quad F \in \mathsf{candidates_A(V)} \quad \mathrm{then} \quad F \mathrel{\triangleright}B \in \mathsf{candidates_A(V \cup \{ B \})}}
    \end{equation*}$$ provided $F$ can be extended with $B$.

3.  []{#candidates:monotone label="candidates:monotone"} Adding blocks doesn't remove any candidates: $$\begin{equation*}
    \mathsf{candidates_A(V)} \subseteq \mathsf{candidates_A(V \cup \{B\})}
    \end{equation*}$$

4.  []{#candidates:musthavenew label="candidates:musthavenew"} If we add a new block, then any new candidates must involve that new block: $$\begin{equation*}
    \mathrm{if \quad F \in \mathsf{candidates_A(V \cup \{B\})} \quad \mathrm{then} \quad F \in \mathsf{candidates_A(V)} \text{ or } F = (\ldots \mathrel{\triangleright}B \mathrel{\triangleright}\ldots)}
    \end{equation*}$$
:::

The next lemma says that if we have previously found some optimal candidate $F$, and subsequently learn of a new block $B$ (where $B$ is a direct or indirect extension of $F$), it suffices to find a locally optimal candidate *amongst the candidates that involve $B$*; this new candidate will also be a globally optimal candidate.

::: lemma
[]{#focusonnewblock label="focusonnewblock"} Suppose we have $F, F_\mathit{new}$ such that

1.  []{#focusonnewblock:previouslyoptimal label="focusonnewblock:previouslyoptimal"} $\mathsf{candidates_A(V)} \mathrel{\sqsubseteq}F$

2.  []{#focusonnewblock:optimalamongstnew label="focusonnewblock:optimalamongstnew"} $(\mathsf{candidates_A(V \cup \{B\})} \setminus \mathsf{candidates_A(V)}) \mathrel{\sqsubseteq}F_\mathit{new}$

3.  []{#focusonnewblock:betterthanold label="focusonnewblock:betterthanold"} $F \mathrel{\sqsubseteq}F_\mathit{new}$

Then $$\begin{equation*}
\mathsf{candidates_A(V \cup \{B\})} \mathrel{\sqsubseteq}F_\mathit{new}
\end{equation*}$$
:::

::: proof
*Proof.* Suppose there exists $F' \in \mathsf{candidates_A(V \cup \{B\})}$ such that $F_\mathit{new} \mathrel{\sqsubset}F'$. By transitivity and assumption [\[focusonnewblock:betterthanold\]](#focusonnewblock:betterthanold){reference-type="ref" reference="focusonnewblock:betterthanold"}, $F \mathrel{\sqsubset}F'$. As shown in [\[candidates:properties\]](#candidates:properties){reference-type="ref+label" reference="candidates:properties"} ([\[candidates:musthavenew\]](#candidates:musthavenew){reference-type="ref+label" reference="candidates:musthavenew"}), there are two possibilities:

- $F' \in \mathsf{candidates_A(V)}$, which would violate assumption [\[focusonnewblock:previouslyoptimal\]](#focusonnewblock:previouslyoptimal){reference-type="ref+label" reference="focusonnewblock:previouslyoptimal"}, or

- $F'$ must contain block $B$, which would violate assumption [\[focusonnewblock:optimalamongstnew\]](#focusonnewblock:optimalamongstnew){reference-type="ref+label" reference="focusonnewblock:optimalamongstnew"}.

 ◻
:::

## Initialisation {#chainsel:init}

The initialisation of the chain database proceeds as follows.

1.  []{#chaindb:init:imm label="chaindb:init:imm"} Initialise the immutable database, determine its tip $I$, and ask the ledger DB for the corresponding ledger state $L$ (see [\[ledgerdb:on-disk:initialisation\]](#ledgerdb:on-disk:initialisation){reference-type="ref+label" reference="ledgerdb:on-disk:initialisation"}).

2.  Compute the set of candidates anchored at the immutable database's tip []{#chaindb:init:compute label="chaindb:init:compute"} $I$ using blocks from the volatile database $V$ $$\mathsf{candidates_I(V)}$$ ignoring known-to-be-invalid blocks (if any; see [\[chaindb:invalidblocks\]](#chaindb:invalidblocks){reference-type="ref+label" reference="chaindb:invalidblocks"}) and order them using $(\mathrel{\sqsubset})$ so that we process better candidates first.[^3] Candidates that are strict prefixes of other candidates can be ignored (as justified by the "prefer extension" assumption, [\[prefer-extension\]](#prefer-extension){reference-type="ref+label" reference="prefer-extension"});[^4] we may reconsider some of these prefixes if we subsequently discover invalid blocks (see [\[chaindb:init:select\]](#chaindb:init:select){reference-type="ref+label" reference="chaindb:init:select"}).

3.  []{#chaindb:init:select label="chaindb:init:select"} Not all of these candidates may be valid, because the volatile database stores blocks whose *headers* have been validated, but whose *bodies* are still unverified (other than to check that they correspond to their headers). We therefore validate each candidate chain fragment, starting with $L$ (the ledger state at the tip of the immutable database) each time.[^5]

    As soon as we find a candidate that is valid, we adopt it as our current chain. If we find a candidate that is *invalid*, we mark the invalid block[^6] (unless it is invalid due to potential clock skew, see [1.5](#chainsel:infuture){reference-type="ref+label" reference="chainsel:infuture"}), and go back to step [\[chaindb:init:compute\]](#chaindb:init:compute){reference-type="ref" reference="chaindb:init:compute"}. It is important to recompute the set of candidates after marking some blocks as invalid because those blocks may also exist in other candidates and we do not know how the valid prefixes of those candidates should now be ordered.

## Adding new blocks {#chainsel:addblock}

When a new block $B$ is added to the chain database, we need to add it to the volatile DB and recompute our current chain. We distinguish between the following different cases.

Before we process the new block, we first run chain selection on any blocks that had previously been temporarily shelved because their slot number was (just) ahead of the wallclock ([1.5](#chainsel:infuture){reference-type="ref+label" reference="chainsel:infuture"}). We do this independent of what we do with the new block.[^7]

The implementation `addBlock` additionally provides client code with various notifications throughout the process ("block added", "chain selection run", etc.). We will not describe these notifications here.

### Ignore

We can just ignore the block if any of the following is true.

- The block is already in the immutable DB, *or* it belongs to a branch which forks more than $k$ blocks away from our tip, i.e.[^8] $$\begin{equation*}
  \mathtt{blockNo(B)} \leq \mathtt{blockNo(I)}
  \end{equation*}$$ We could distinguish between between the block being on our chain or on a distant fork by doing a single query on the immutable database, but it does not matter: either way we do not care about this block.

  We don't expect the chain sync client to feed us such blocks under normal circumstances, though it's not impossible: by the time a block is downloaded it's conceivable, albeit unlikely, that that block is now older than $k$.

- The block was already in the volatile database, i.e. $$\begin{equation*}
  B \in V
  \end{equation*}$$

- The block is known to be invalid ([\[chaindb:invalidblocks\]](#chaindb:invalidblocks){reference-type="ref+label" reference="chaindb:invalidblocks"}).

### Add to current chain {#chainsel:addtochain}

Let $B_\mathit{pred}$ be the predecessor block of $B$. If $B$ fits onto the end of our current fragment $F$ (and hence onto our current chain) $F$, i.e.

- $F$ is empty, and $B_\mathit{pred} = I$ (where $I$ must necessarily also be the anchor of the fragment), or

- $\exists F' .\;F = F' \mathrel{\triangleright}B_\mathit{pred}$

then any new candidates must be equal to or an extension of $F \mathrel{\triangleright}B$ ([\[candidates:properties\]](#candidates:properties){reference-type="ref+label" reference="candidates:properties"}, [\[candidates:musthavenew\]](#candidates:musthavenew){reference-type="ref+label" reference="candidates:musthavenew"}); this set is computed by $$\begin{equation*}
(F \mathrel{\triangleright}B \mathrel{\triangleright}\mathsf{candidates_B(V \cup \{B\})})
\end{equation*}$$ Since all candidates would be strictly preferred over $F$ (since they are extensions of $F$), by [\[focusonnewblock\]](#focusonnewblock){reference-type="ref+label" reference="focusonnewblock"} it suffices to pick the best candidate amongst these extensions. Apart from the starting point, chain selection then proceeds in the same way as when we are initialising the database ([1.3](#chainsel:init){reference-type="ref+label" reference="chainsel:init"}).

This case takes care of the common case where we just add a block to our chain, as well as the case where we stay with the same branch but receive some blocks out of order. Moreover, we can use the *current* ledger state as the starting point for validation.

### Store, but don't change current chain

When we are missing one of the (transitive) predecessors of the block, we store the block but do nothing else. We can check this by following back pointers until we reach a block $B'$ such that $B' \notin V$ and $B' \neq I$. The cost of this is bounded by the length of the longest fragment in the volatile DB, and will typically be low; moreover, the chain fragment we are constructing this way will be used in the switch-to-fork case ([1.4.4](#chainsel:switchtofork){reference-type="ref+label" reference="chainsel:switchtofork"}).[^9]

At this point we *could* do a single query on the immutable DB to check if $B'$ is in the immutable DB or not. If it is, then this block is on a distant branch that we will never switch to, and so we can ignore it. If it is not, we may or may not need this block later and we must store it; if it turns out we will never need it, it will eventually be garbage collected ([\[chaindb:gc\]](#chaindb:gc){reference-type="ref+label" reference="chaindb:gc"}).

An alternative and easier approach is to omit the check on the immutable DB, simply assuming we might need the block, and rely on garbage collection to eventually remove it if we don't. This is the approach we currently use.

### Switch to a fork {#chainsel:switchtofork}

If none of the cases above apply, we have a block $B$ such that

1.  []{#chainsel:switchtofork:notinvoldb label="chainsel:switchtofork:notinvoldb"} $B \notin V$

2.  []{#chainsel:switchtofork:notinimmdb label="chainsel:switchtofork:notinimmdb"} $\mathtt{blockNo(B)} > \mathtt{blockNo(I)}$ (and hence $B$ cannot be in the immutable DB)

3.  []{#chainsel:switchtofork:connected label="chainsel:switchtofork:connected"} For all transitive predecessors $B'$ of $B$ we have $B' \in V$ or $B' = I$. In other words, we must have a fragment $$F_\mathit{prefix} = I \mathrel{\triangleright}\ldots \mathrel{\triangleright}B$$ in $\mathsf{candidates_I(V \cup \{B\})}$.

4.  []{#chainsel:switchtofork:doesnotfit label="chainsel:switchtofork:doesnotfit"} (Either $F$ is empty and $B_\mathit{pred} \neq I$, or) $\exists F', B' .\;
    F = F' \mathrel{\triangleright}B'$ where $B' \neq B_\mathit{pred}$; i.e., block does not fit onto current chain.[^10]

(This list is just the negation of the conditions we handled in the sections above.) We proceed in similar fashion to the case when the block fit onto the tip of our chain ([1.4.2](#chainsel:addtochain){reference-type="ref+label" reference="chainsel:addtochain"}). The new candidates in $\mathsf{candidates_I(V \cup
\{B\})}$ must involve $B$ ([\[candidates:properties\]](#candidates:properties){reference-type="ref+label" reference="candidates:properties"}, [\[candidates:musthavenew\]](#candidates:musthavenew){reference-type="ref+label" reference="candidates:musthavenew"}), which in this case means they must all be extensions of $F_\mathit{prefix}$; we can compute these candidates using[^11] $$I \mathrel{\triangleright}\ldots \mathrel{\triangleright}B \mathrel{\triangleright}\mathsf{candidates_B(V \cup \{B\})}$$ Not all of these fragments might be preferred over the current chain; we filter those out.[^12] We then proceed as usual, considering each of the remaining fragments in $(\mathrel{\sqsubseteq})$ order, and appeal to [\[focusonnewblock\]](#focusonnewblock){reference-type="ref+label" reference="focusonnewblock"} again to conclude that the fragment we find in this way will be an optimal candidate across the entire volatile database.

## In-future check {#chainsel:infuture}

As we saw in [1.2](#chainsel:spec){reference-type="ref+label" reference="chainsel:spec"}, the chain DB performs full block validation during chain selection. When we have validated a block, we then do one additional check, and verify that the block's slot number is not ahead of the wallclock time (for a detailed discussion of why we require the block's ledger state for this, see [\[time\]](#time){reference-type="ref+label" reference="time"}, especially [\[time:block-infuture-check\]](#time:block-infuture-check){reference-type="ref+label" reference="time:block-infuture-check"}). If the block is far ahead of the wallclock, we treat this as any other validation error and mark the block as invalid.

Marking a block as invalid will cause the network layer to disconnect from the peer that provided the block to us, since non-malicious (and non-faulty) peers should never send invalid blocks to us. It is however possible that an upstream peer's clock is not perfectly aligned with us, and so they might produce a block which *we* think is ahead of the wallclock but *they* do not. To avoid regarding such peers as malicious, the chain database supports a configurable *permissible clock skew*: blocks that are ahead of the wallclock by an amount less than this permissible clock skew are not marked as invalid, but neither will chain selection adopt them; instead, they simply remain in the volatile database available for the next chain selection.

It is constructive to consider what happens if *our* clock is off, in particular, when it is slow. In this scenario *every* (or almost every) block that the node receives will be considered to be in the future. Suppose we receive two consecutive blocks $A$ and $B$. When we receive $A$, chain selection runs, we find that $A$ is ahead of the clock but within the permissible clock skew, and we don't adopt it. When we then receive $B$, chain selection runs again, we now discover the $A, B$ extension to our current chain; during validation we cut off this chain at $B$ because it is ahead of the clock, but we adopt $A$ because it is now valid. In other words, we are always behind one block, adopting each block only when we receive the *next* block.

## Sorting

In this chapter we have modelled chain selection as a partial order $(\mathrel{\sqsubseteq})$. This suffices for the formal treatment, and in theory also suffices for the implementation. However, at various points during the chain selection process we need to *sort* candidates in order of preference. We can of course sort values based on a preorder only (topological sorting), but we can do slightly better. Recall from [\[consensus:class:chainsel\]](#consensus:class:chainsel){reference-type="ref+label" reference="consensus:class:chainsel"} that we require that the `SelectView` on headers must be a total order. We can therefore define

::: definition
Let $C \precsimC'$ if the select view at the tip of $C$ is less than or equal to the select view at the tip of $C'$.
:::

($\precsim$) forms a total preorder (though not a partial order); if $C
\precsimC'$ *and* $C' \precsimC$ then the select views at the tips of $C$ and $C'$ are equal (though they might be different chains, of course). Since $C \precsimC'$ implies $C' \mathrel{\nsqsubset}C$, we can use this preorder to sort candidates (in order words, we will sort them *on* their select view, in Haskell-parlance).

[^1]: We can distinguish between an empty fragment of a non-empty chain and a (necessarily) empty fragment of an empty chain by looking at the anchor point: if it is the genesis point, the chain must be empty.

[^2]: In order to compute these candidates efficiently, the volatile database must support a "forward chain index", able to efficiently answer the question "which blocks succeed this one?".

[^3]: Technically speaking we should *first* validate all candidates, and only then apply selection to the valid chains. We perform chain selection first, because that is much cheaper. Both approaches are semantically equivalent, since `sortBy f . filter p = filter p . sortBy f` due to the stability of `sortBy`.

[^4]: The implementation does not compute candidates, but rather "maximal" candidates, which do not include such prefixes.

[^5]: We make no attempt to share ledger states between candidates, even if they share a common prefix, trading runtime performance for lower memory pressure.

[^6]: There is no need to mark any successors of invalid blocks; see [\[chaindb:dont-mark-invalid-successors\]](#chaindb:dont-mark-invalid-successors){reference-type="ref+label" reference="chaindb:dont-mark-invalid-successors"}.

[^7]: In a way, calls to `addBlock` are how the chain database sees time advance. It does not rely on slot length to do so, because slot length is ledger state dependent.

[^8]: The check is a little more complicated in the presence of EBBs ([\[ebbs\]](#ebbs){reference-type="ref+label" reference="ebbs"}). This is relevant if we switch to an alternative fork after a maximum rollback, and that alternative fork starts with an EBB. It is also relevant when due to data corruption the volatile database is empty and the first block we add when we continue to sync the chain happens to be an EBB.

[^9]: The function that constructs these fragments is called `isReachable`.

[^10]: [\[chainsel:switchtofork:connected\]](#chainsel:switchtofork:connected){reference-type="ref+Label" reference="chainsel:switchtofork:connected"} rules out the first option: if $B_\mathit{pred} \neq I$ then we must have $B_\mathit{pred} \in
    V$ and moreover this must form some kind of chain back to $I$; this means that the preferred candidate cannot be empty.

[^11]: The implementation of the chain database actually does not construct fragments that go back to $I$, but rather to the intersection point with the current chain. This can be considered to be an optimisation of what we describe here.

[^12]: Recall that the current chain gets special treatment: when two candidates are equally preferable, we can pick either one, but when a candidate and the current chain are equally preferable, we must stick with the current chain.
