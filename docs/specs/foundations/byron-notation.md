# Notation
Natural Numbers

:   The set $\mathbb{N}$ refers to the set of all natural numbers $\{0, 1, 2, \ldots\}$. The set $\mathbb{Q}$ refers to the set of rational numbers.

Booleans

:   The set $\mathbb{B}$ denotes the set of booleans $\{\mathit{True}, \mathit{False}\}$.

Powerset

:   Given a set $\mathsf{X}$, $\mathbb{P}~\mathsf{X}$ is the set of all the subsets of $X$.

Sequences

:   Given a set $\mathsf{X}$, $\mathsf{X}^{*}$ is the set of sequences having elements taken from $\mathsf{X}$. The empty sequence is denoted by $\epsilon$, and given a sequence $\Lambda$, $\Lambda; \mathsf{x}$ is the sequence that results from appending $\mathsf{x} \in \mathsf{X}$ to $\Lambda$.

Functions

:   $A \to B$ denotes a **total function** from $A$ to $B$. Given a function $f$ we write $f~a$ for the application of $f$ to argument $a$.

Inverse Image

:   Given a function $f: A \to B$ and $b\in B$, we write $f^{-1}~b$ for the **inverse image** of $f$ at $b$, which is defined by $\{a \mid\ f a =  b\}$.

Maps and partial functions

:   $A \mapsto B$ denotes a **partial function** from $A$ to $B$, which can be seen as a map (dictionary) with keys in $A$ and values in $B$. Given a map $m \in A \mapsto B$, notation $a \mapsto b \in m$ is equivalent to both $m~ a = b$ and $\mathsf{a}~m = b$. Given a set $A$, $A \mapsto A$ represents the identity map on $A$: $\{a \mapsto a \mid a \in A\}$. The $\emptyset$ symbol is also used to represent the empty map as well.

Domain and range

:   Given a relation $R \in \mathbb{P}~(A \times B)$, $\dom~R \in \mathbb{P}~A$ refers to the domain of $R$, and $\range~R \in \mathbb{P}~B$ refers to the range of $R$. Note that (partial) functions (and hence maps) are also relations, so we will be using $\dom$ and $\range$ on functions.

Domain and range operations

:   Given a relation $R \in \mathbb{P}~(A \times B)$ we make use of the *domain-restriction*, *domain-exclusion*, and *range-restriction* operators, which are defined in 1. Note that a map $A \mapsto B$ can be seen as a relation, which means that these operators can be applied to maps as well.

Integer ranges

:   Given $a, b \in \mathbb{Z}$, $[a, b]$ denotes the sequence $[i \mid a \leq i \leq b]$ . Ranges can have open ends: $[.., b]$ denotes sequence $[i \mid i \leq b]$, whereas $[a, ..]$ denotes sequence $[i \mid a \leq i]$. Furthermore, sometimes we use $[a, b]$ to denote a set instead of a sequence. The context in which it is used should provide enough information about the specific type.

Domain and range operations on sequences

:   We overload the $\lhd$, $\mathbin{\rlap{\lhd}/}$, and $\rhd$ to operate over sequences. So for instance given $S \in A^{*}$, and $R \in (A \times B)^{*}$: $S \lhd R$ denotes the sequence $[ (a, b) \mid (a, b) \in R, a \in S]$.

Wildcard variables

:   When a variable is not needed in a term, we replace it by $\underline{\phantom{a}}$ to make it explicit that we do not use this variable in the scope of the given term.

Implicit existential quantifications

:   Given a predicate $P \in X \to \mathbb{B}$, we use $P \underline{\phantom{a}}$ as a shorthand notation for $\exists x \cdot P~x$.

Pattern matching in premises

:   In the inference-rules premises use $\mathit{patt} \mathrel{\mathop:}= \mathit{exp}$ to pattern-match an expression $\mathit{exp}$ with a certain pattern $\mathit{patt}$. For instance, we use $\Lambda'; x \mathrel{\mathop:}= \Lambda$ to be able to deconstruct a sequence $\Lambda$ in its last element, and prefix. If an expression does not match the given pattern, then the premise does not hold, and the rule cannot trigger.

Ceiling

:   Given a number $n \in \mathbb{R}$, $\ceil{n}$ represents the ceiling of $n$, and $\floor{n}$ represents its floor.


$$\begin{align*}
    \mathit{S} \lhd \mathit{R}
    & = \{ (a, b) \mid (a, b) \in R, ~ a \in S \}
    & \text{domain restriction}
    \\
    S \mathbin{\rlap{\lhd}/} R
    & = \{ (a, b) \mid (a, b) \in R, ~ a \notin S \}
    & \text{domain exclusion}
    \\
    R \rhd S
    & = \{ (a, b) \mid (a, b) \in R, ~ b \in S \}
    & \text{range restriction}
\end{align*}$$

**Domain and range operations**