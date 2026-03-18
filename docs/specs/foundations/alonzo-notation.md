# Notation
$\mathbb{N}$

:   The (canonical) symbol for the natural numbers

$\mathbb{H}$

:   The type of byte strings

Aggregated Addition

:   Given a type $\mathsf{FM}~\in~ \powerset(\mathsf{X} \times \mathsf{Y})$, where addition is defined on terms of type $\mathsf{Y}$, and a term $\mathit{fm} \in \mathsf{FM}$, we overload the $\sum$ notation as follows: $$\sum_{(x, y)\in\mathit{fm}} (x,y) :=
        \{ x\mapsto \sum_{(x,y)\in\mathit{fm}} y \}$$

    In the case $\mathsf{Y}~=~\mathsf{A}\mapsto\mathsf{B}$ is itself a finite map, and addition is defined on terms of type $\mathsf{B}$, we interpret $$\sum_{(x, (a\mapsto b))\in\mathit{fm}} (x,a\mapsto b) :=
        \{ x \mapsto (a\mapsto \sum_{(x,a\mapsto b)\in\mathit{fm}} b) \}$$

    We define $\sum$ on a set of the form $$\mathsf{FM} \subseteq \{ x \mapsto y \vert x \in \mathsf{X}, y \in \mathsf{Y} \}$$

    in a similar way, $$\sum_{(x\mapsto y)\in\mathit{fm}} x \mapsto y :=
        \{ x\mapsto \sum_{x\mapsto y\in\mathit{fm}} y \}$$

    We use the $+$ to denote this overloaded addition operation also.

Other Operations

:   Similar to the definition of aggregated addition, other scalar operations are defined on finite maps. This includes multiplication, floor, etc.

$\leq$

:   This symbol is overloaded to represent the conjunction of the pairwise $\leq$ comparison of entries with at same index in a list or a vector. Every other comparison symbol is overloaded in a similar way.
