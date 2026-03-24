<!-- frame -->
### Chain selection rule

<!-- alertblock -->
Density rule A candidate chain is preferred over our current chain if it is denser (contains more blocks) in a window of $s$ slots anchored at the intersection between the two chains.

<!-- alertblock -->
Genesis window size The genesis window size $s$ will be set to $s = 3k/f$.


<!-- frame -->
### Fragment selection

<!-- center -->


<!-- frame -->
### Fragment selection

<!-- center -->


<!-- frame -->
Known density

We say that a chain fragment has a *known density* at some point $p$ if either of the following conditions hold:

1.  The fragment contains a block after at least $s$ slots:

<!-- center -->
    :::

2.  The chain (not just the fragment) terminates within the window:

<!-- center -->
    :::

<!-- frame -->
Fragment selection

<!-- alertblock -->
Look-ahead closure []{#lookahead-closure label="lookahead-closure"} Let $\mathcal{S}$ be a set of chain fragments all anchored at the same point. We say that $\mathcal{S}$ is *look-ahead closed* if whenever there are two fragments $A, B \in \mathcal{S}$, the densities of $A$ and $B$ are known at their intersection.

Unfortunately, requires unbounded lookahead:

<!-- center -->


<!-- frame -->
Preferred Prefix

$$\begin{equation*}
\mathcal{S} = \left\{ \;
\begin{tikzpicture}[baseline=0pt, xscale=0.5,yscale=0.5]
\draw [very thick, red] (-2,0) -- (0,0);
\draw (0,0) -- (1, 1) -- (6,  1) node[right]{$A$};
\draw (0,0) -- (1,-1) -- (7, -1) node[right]{$B$};
\draw [dashed] (-2,0) -- ++(0,1.5) -- ++(5,0) node[pos=0.5,above]{$\overbrace{\hspace{2cm}}^\text{$s$ slots}$} -- ++(0,-3) -- ++(-5,0) -- cycle;
\end{tikzpicture}
\right\}
\end{equation*}$$

<!-- alertblock -->
Preferred prefix Given a set $\mathcal{S}$ of chain fragments, all anchored at the same point, a preferred prefix is a prefix $\Pi$ of one of the fragments in $\mathcal{S}$, such that $\Pi$ is guaranteed to be a prefix of a preferred fragment in the lookahead-closure of $\mathcal{S}$.


<!-- frame -->
Prefix selection

<!-- alertblock -->
Step 1: Resolve initial fork

<!-- center -->


<!-- frame -->
Prefix selection

<!-- alertblock -->
Step 2: Adopt common prefix

<!-- center -->


<!-- frame -->
Prefix selection

<!-- alertblock -->
Step 2: Adopt common prefix (special case)

<!-- center -->


Smooth transition to longest chain rule.

<!-- frame -->
Maximum rollback

1.  Ouroboros Praos assumes all nodes are online all the time

2.  Imposes a maximum rollback of $k$ blocks

3.  This is fine (Praos analysis tells us honest nodes won't diverge by more than $k$ blocks) ...

4.  ...unless we are eclipsed by a malicious node and we adopt more than $k$ of their blocks (reasonably long time)

<!-- frame -->
Maximum rollback

1.  Ouroboros Genesis drops the "always online" assumption ...

2.  ...as well as the maximum rollback ...

3.  ...but we don't want to do that

<!-- frame -->
Maximum rollback

1.  Genesis analysis tells us we do not need to roll back more than $k$ *when we are up to date* (just like Praos)

2.  When we are behind, prefix selection *will always pick the honest chain* at every intersection ...**provided it can see it**

3.  Not a fundamentally new problem, difference in *degree* only: when we are online, being eclipsed temporarily is fine.

4.  But if we are behind, being eclipsed even for a very short amount can be disastrous: adversary can feed us $k$ blocks from their chain, we adopt them, and are now stuck.

5.  Solution: make sure to connect to a large number of upstream peers (probably randomly chosen), and refuse to make chain selection decisions if that quota is not reached.

<!-- frame -->
Being "up to date"

<!-- alertblock -->
Recovering "alert" status When prefix selection can see all available chains to their tip, and we have selected and adopted the best one, the node is up to date.

When not up to date:

- Insist on quota of peers before chain selection

- Do not produce blocks

When up to date:

- Danger of being eclipsed same as in Praos (very small, provided not too long)

- Not entirely clear when to conclude we no longer up to date. Proposal from Frisby: "as long as we stay connected to our current peers".
