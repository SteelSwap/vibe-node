# Some basic notation
We begin with some notation which will be used throughout the document.

## Sets
- $\N = \{0,1,2,3,\ldots\}$.

- $\mathsf{Nplus} = \{1,2,3,\ldots\}$.

- The symbol $\disj$ denotes a disjoint union of sets; for emphasis we often use this to denote the union of sets which we know to be disjoint.

- Given a set $X$, $X^*$ denotes the set of finite sequences of elements of $X$: $$X^* = \bigdisj{\{X^n: n \in \N\}}$$ and $X^+$ denotes the set of nonempty finite sequences of elements of $X$: $$X^+ = \bigdisj{\{X^n: n \in \mathsf{Nplus}\}}.$$ We will sometimes write elements of $X^+$ in the form $(x|x_1,\ldots,x_n)$ with $n \geq 0$.

- $\mathsf{Nab}{a}{b} = \{n \in \N: a \leq n \leq b\}$.

- $\B = \mathsf{Nab}{0}{255}$, the set of 8-bit bytes.

- $\B^*$ is the set of all bytestrings.

- $\b = \{\mathtt{0}, \mathtt{1}\}$, the set of bits.

- $\b^*$ is the set of all bitstrings.

- $\Z = \{\ldots, -2, -1, 0, 1, 2, \ldots\}$.

- $\mathbb{F}_q$ denotes a finite field with $q$ elements ($q$ a prime power).

- $\units{\mathbb{F}_q}$ denotes the multiplicative group of nonzero elements of $\mathbb{F}_q$.

- $\U$ denotes the set of Unicode scalar values, as defined in [@Unicode-standard Definition D76].

- $\U^*$ is the set of all Unicode strings.

- We assume that there is a special symbol $\errorX$ which does not appear in any other set we mention. The symbol $\errorX$ is used to indicate that some sort of error condition has occurred, and we will often need to consider situations in which a value is either $\errorX$ or a member of some set $S$. For brevity, if $S$ is a set then we define $$\withError{S} := S \disj \{\errorX\}.$$

## Lists
- The symbol $[]$ denotes an empty list.

- The notation $[x_m, \ldots, x_n]$ denotes a list containing the elements $x_m, \ldots, x_n$. If $m>n$ then the list is empty.

- The length of a list $L$ is denoted by $\length(L)$.

- Given two lists $L = [x_1,\ldots, x_m]$ and $L' = [y_1,\ldots, y_n]$, $L\cdot L'$ denotes their concatenation $[x_1,\ldots, x_m,$ $y_1, \ldots, y_n]$.

- Given an object $x$ and a list $L = [x_1,\ldots, x_n]$, we denote the list $[x,x_1,\ldots, x_n]$ by $x \cons L$.

- Given a list $L = [x_1, \ldots, x_n]$ and an object $x$, we denote the list $[x_1, \ldots, x_n, x]$ by $L \snoc x$.

- Given a syntactic category $V$, the symbol $\overline{V}$ denotes a possibly empty list $[V_1,\ldots, V_n]$ of elements $V_i \in V$.

## Bytestrings and bitstrings
We make frequent use of bytestrings and bitstrings and for the sake of conciseness we occasionally use special notation. We also define conversion functions between bytestrings and bitstrings

- We typically index the bytes in bytestrings starting from the *left* end but the bits in bitstrings from the *right* end.

- The bytestring $[c_0, \ldots, c_{n-1}]$ may be denoted by $c_0{\cdots}c_{n-1}$ ($n \geq 0$, $c_i \in \B$); the empty bytestring may be denoted by $\epsilon$.

- The bitstring $[b_{n-1}, \ldots, b_0]$ may be denoted by $b_{n-1}{\cdots}b_0$ ($n \geq 0$, $b_i \in \b$); the empty bitstring may be denoted by $\epsilon$: we also use this symbol for the empty bytestring, but this should not cause any confusion.

- In the special case of bitstrings we sometimes use notation such as `101110` to denote the list $[1,0,1,1,1,0]$; we use a teletype font to avoid confusion with decimal numbers.

- A bytestring can naturally be viewed as a bitstring whose length is a multiple of 8 simply by concatenating the bits of the individual bytes, and vice-versa (by breaking the bitstring into groups of 8 bits). To make this precise we define two conversion functions $\bitsof: \B^* \rightarrow \b^*$ and $\bytesof: \{s \in \b^* : 8 \mid \length(s)\} \rightarrow \B^*$. These depend on the fact that any $c \in \B$ can be written uniquely in the form $\Sigma_{i=0}^72^ib_i$ with $b_0, \ldots, b_7 \in \b$.

  - $\bitsof([c_0, \ldots, c_{n-1}]) = [b_{8n-1}, \ldots, b_0]$ where $c_j=\Sigma_{i=0}^72^ib_{8(n-j-1)+i}$

  - $\bytesof([b_{8n-1}, \ldots, b_0]) = [c_0, \ldots, c_{n-1}]$ where $c_j=\Sigma_{i=0}^72^ib_{8(n-j-1)+i}$.

## Miscellaneous notation

- Given integers $k \in \Z$ and $n \geq 1$ we write $k \bmod n = \min\{r \in \Z: r \geq 0 \text{ and } n | k - r \}$
