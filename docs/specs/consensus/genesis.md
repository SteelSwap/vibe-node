<!-- frame -->
### The Genesis Rule

<!-- alertblock -->
Genesis chain selection rule A candidate chain is preferred over our current chain if

- The intersection between the candidate chain and our chain is **no more than $k$** blocks back, and the candidate chain is strictly **longer** than our chain.

- If the intersection *is* **more than $k$** blocks back, and the candidate chain is **denser** (contains more blocks) than our chain in a region of $s$ slots starting at the intersection.


<!-- frame -->
### The Genesis Rule

<!-- alertblock -->
Alternative genesis rule A candidate chain is preferred over our current chain if

- The intersection between the candidate chain and our chain is **at least $s$ slots** back, and the candidate chain is denser in a window of $s$ slots at the intersection, or

- The intersection between the candidate chain and our chain is **no more than $k$ blocks** back, and the candidate chain is strictly **longer** than our chain.


<!-- frame -->
### Fundamental Assumptions within the Consensus Layer

<!-- onlyenv -->
\<1\>

<!-- alertblock -->
Invariant We never roll back more than $k$ blocks.

This invariant is used to

- **Organise on-disk and in-memory block and ledger storage**: blocks older than $k$ are stored in the *immutable* database, the remainder in the *volatile* database.

- **Guarantee efficient block validation**: we have access to the $k$ most recent ledger states

- **Bound memory usage for tracking peers**: we need to track at most $k + 1$ blocks per upstream peer to be able to decide if we prefer their chain over ours (apply the longest chain rule)

- ...

<!-- onlyenv -->
\<2\>

<!-- alertblock -->
Invariant We never switch to a shorter chain.

Without this invariant, the previous invariant (never roll back more than $k$ blocks) is not very useful.

- If we *could* switch to a shorter chain but continue to support a rollback of $k$, the *effective* maximum rollback is infinite.

- We would need efficient access to *all* past ledger states.

- We would have to move blocks *back* from the immutable database to the volatile database.

- ...

<!-- onlyenv -->
\<3\>

<!-- alertblock -->
Invariant The strict extension of a chain is always preferred over that chain.

- Used to make some local chain selection decisions.

- (I *think* this one is compatible with Genesis.)


<!-- frame -->
Towards an Alternative

<!-- center -->


<!-- frame -->
### Towards an Alternative

<!-- onlyenv -->
\<1\>

<!-- alertblock -->
Key Idea: Delay the decision Rather than adopting chain $A$ as soon as we see it, and later switch to chain $B$ (possibly incurring a large rollback), *wait*: don't adopt *either* $A$ *or* $B$ until we know which one we want.

Assumptions:

- We can guarantee that we see (a representative sample of) all chains in the network. An attacker **can't eclipse** us.

- We can **detect when** we should delay because the genesis condition might apply.\
  (We will come back to this.)\


<!-- frame -->
### Choosing between forks: at genesis

### Choosing between forks: general case

<!-- center -->


<!-- frame -->
### Common prefix: at genesis

### Common prefix: general case

<!-- center -->


<!-- frame -->
### Insufficient peers

<!-- center -->

<!-- center -->


<!-- frame -->
### Insufficient blocks

<!-- center -->

<!-- center -->


<!-- frame -->
### Threshold for sufficient blocks

<!-- center -->


<!-- frame -->
### Detecting when to delay

- **[Cannot]{.alert} apply density rule when we are closer than $s$ slots from the wallclock slot.**\
  (We would be unable to fill the window, by definition.)

- **[Don't need]{.alert} to apply density rule when within $k = 2160$ blocks from the wallclock slot.** \[Handwavy\]\
  (Too?) liberal rephrasing of Theorem 2 of the genesis paper.

- **Always sound to delay chain selection**\
  (Unless *really* near tip and we might have to forge a block)\

- Paper suggests $s = \frac{1}{4} (k/f)$ = 10,800 slots.\
  (I.e. $s \times f = \frac{1}{4}k = 540$ blocks on average.)

<!-- alertblock -->
**Delay if more than $s$ slots from the wallclock.**\
(If wallclock slot unknown, must be more than $(3k/f) > s$ slots.)


<!-- frame -->
### Generalising delay mode

<!-- center -->

- **Cannot reliably detect** whether we have more than $k$ blocks\
  (node reports tip but we cannot verify)

- **Can still apply genesis condition**, independent of \# blocks\
  (justified by alternative genesis rule)

<!-- frame -->
### Header/Body split: choosing between forks

<!-- center -->

- What if we find an invalid block on $A$ after discarding $C$, $D$?

- Header validation justifies deciding before block validation.

<!-- minipage -->
  Christian: "Intuitively, right after the forking point, the lottery to elect slot leaders is still the same on both chains, and there, no adversarial chain can be denser."
  :::

- Header validation (as separate from block validation) critical.\
  (So far was "merely" required to guard against DoS attacks.)

<!-- frame -->
### Header/Body split: common prefix

<!-- center -->

- Blocks from common prefix will be validated by chain database before adoption.

- If found to be invalid, something went horribly wrong and we are eclipsed by an attacker after all. Disconnect from all peers and start over.

<!-- frame -->
### Open questions

- Assumption is that when we see $n$ peers, that gives us a representative sample of all chains in the network. Does that mean that after we discard some peers (not dense enough), we do not have have to look for more peers (apart from for performance reasons, perhaps)?

- Detection of genesis mode OK?

- Applying genesis condition even if fork closer than $k$ okay?

- Concerns about invalid blocks with valid headers?

- Anything else..?

<!-- frame -->
### Flip-flopping

<!-- center -->

$A$ is preferred over $B$, and $B$ is preferred over $A$!
