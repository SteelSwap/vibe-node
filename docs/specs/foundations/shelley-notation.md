# Notation
The transition system is explained in [@small_step_semantics].

Powerset

:   Given a set $\mathsf{X}$, $\mathbb{P}~\mathsf{X}$ is the set of all the subsets of $\mathsf{X}$.

Sequences

:   Given a set $\mathsf{X}$, $\mathsf{X}^{*}$ is the set of sequences having elements taken from $\mathsf{X}$. The empty sequence is denoted by $\epsilon$. Given a sequence $\Lambda$, $\Lambda; \mathsf{x}$ is the sequence that results from appending $\mathsf{x} \in \mathsf{X}$ to $\Lambda$.

Functions

:   $A \to B$ denotes a **total function** from $A$ to $B$. Given a function $f$ we write $f~a$ for the application of $f$ to argument $a$.

Inverse Image

:   Given a function $f: A \to B$ and $b\in B$, we write $f^{-1}~b$ for the **inverse image** of $f$ at $b$, which is defined by $\{a \mid\ f a =  b\}$.

Maps and partial functions

:   $A \mapsto B$ denotes a **partial function** from $A$ to $B$, which can be seen as a map (dictionary) with keys in $A$ and values in $B$. Given a map $m \in A \mapsto B$, notation $a \mapsto b \in m$ is equivalent to $m~ a = b$. The $\emptyset$ symbol is also used to represent the empty map as well.

Map Operations

:   Figure 1 describes some non-standard map operations.

Relations

:   A relation on $A\times B$ is a subset of $A\times B$. Both maps and functions can be thought of as relations. A function $f:A\to B$ is a relation consisting of pairs $(a, f(a))$ such that $a\in A$. A map $m: A\mapsto B$ is a relation consisting of pairs $(a, b)$ such that $a\mapsto b \in m$. Given a relation $R$ on $A\times B$, we define the inverse relation $R^{-1}$ to be all pairs $(b, a)$ such that $(a, b)\in R$. Similarly, given a function $f:A\to B$ we define the inverse relation $f^{-1}$ to consist of all pairs $(f(a), a)$. Finally, given two relations $R\subseteq A\times B$ and $S\subseteq B\times C$, we define the compostion $R\circ S$ to be all pairs $(a, c)$ such that $(a, b)\in R$ and $(b, c)\in S$ for some $b\in B$.

Option type

:   An option type in type $A$ is denoted as $A^? = A + \mathsf{Nothing}$. The $A$ case corresponds to the case when there is a value of type $A$ and the $\mathsf{Nothing}$ case corresponds to the case when there is no value.

:=

:   We abuse the **:=** symbol here to mean propositional equality. In the style of semantics we use in this formal spec, definitional equality is not needed. It is meant to make the spec easier to read in the sense that each time we use it, we use a fresh variable as shorthand notation for an expression, e.g. we write

    $$s := slot + \mathsf{StabilityWindow}$$

    Then, in subsequent expressions, it is more convenient to write simply $s$. It is not meant to shadow variables, and if it does, there is likely a problem with the rules that must be addressed.

In Figure 1, we specify the notation that we use in the rest of the document.


$$\begin{align*}
    \mathit{set} \lhd \mathit{map}
    & = \{ k \mapsto v \mid k \mapsto v \in \mathit{map}, ~ k \in \mathit{set} \}
    & \text{domain restriction}
    \\
    \mathit{set} \mathbin{\rlap{\lhd}/} \mathit{map}
    & = \{ k \mapsto v \mid k \mapsto v \in \mathit{map}, ~ k \notin \mathit{set} \}
    & \text{domain exclusion}
    \\
    \mathit{map} \rhd \mathit{set}
    & = \{ k \mapsto v \mid k \mapsto v \in \mathit{map}, ~ v \in \mathit{set} \}
    & \text{range restriction}
    \\
    \mathit{map} \subtractrange \mathit{set}
    & = \{ k \mapsto v \mid k \mapsto v \in \mathit{map}, ~ v \notin \mathit{set} \}
    & \text{range exclusion}
    \\
    A \triangle B
    & = (A \setminus B) \cup (B \setminus A)
    & \text{symmetric difference}
    \\
    M \unionoverrideRight N
    & = (\dom N \mathbin{\rlap{\lhd}/} M)\cup N
    & \text{union override right}
    \\
    M \unionoverrideLeft N
    & = M \cup (\dom M \mathbin{\rlap{\lhd}/} N)
    & \text{union override left}
    \\
    M \unionoverridePlus N
    & = (M \triangle N)
    \cup \{k\mapsto v_1+v_2\mid {k\mapsto v_1}\in M \land {k\mapsto v_2}\in N \}
    & \text{union override plus} \\
    & & \text{(for monoidal values)}\\
\end{align*}$$

**Non-standard map operators**