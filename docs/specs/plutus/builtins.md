# Interpretation of built-in types and functions {#sec:specify-builtins}

As mentioned above, Plutus Core is generic over a universe $\Uni$ of types and a set $\Fun$ of built-in functions. As the terminology suggests, built-in functions are interpreted as functions over terms and elements of the built-in types: in this section we make this interpretation precise by giving a specification of built-in types and functions in a set-theoretic denotational style. We require a considerable amount of extra notation in order to do this, and we emphasise that nothing in this section is part of the syntax of Plutus Core: it is meta-notation introduced purely for specification purposes.

## Built-in types {#sec:built-in-types}

We require some extra syntactic notation for built-in types: see Figure [\[fig:type-names-operators\]](#fig:type-names-operators){reference-type="ref" reference="fig:type-names-operators"}.

::: minipage
$$\begin{array}{rclr}
    \at    & ::= & n & \textrm{Atomic type}\\
     \op             & ::= & n & \textrm{Type operator}\\
     \tn             & ::= & \at \ | \ \op(\tn,\tn,...,\tn) & \textrm{Built-in type}\\
    \end{array}$$ []{#fig:type-names-operators label="fig:type-names-operators"}
:::

We assume that we have a set $\Uni_0$ of *atomic type names* and a set $\TyOp$ of *type operator names*. Each type operator name $\op \in \TyOp$ has an *argument count* $\valency{\op} \in \Nplus$, and a type name $\op(\tn_1,
\ldots, \tn_n)$ is well-formed if and only if $n = \valency{\op}$. We define the *universe* $\Uni$ to be the closure of $\Uni_0$ under repeated applications of operators in $\TyOp$: $$\Uni_{i+1} = \Uni_i \cup \{\op(\tn_1, \ldots, \tn_{\valency{\op}}): \op \in \TyOp, \tn_1, \ldots, \tn_{\valency{op}} \in \Uni_i\}$$ $$\Uni = \bigcup\{\Uni_i: i \in \Nplus\}$$

The universe $\Uni$ consists entirely of *names*, and the semantics of these names are given by *denotations*. Each built-in type $\tn \in \Uni$ is associated with some mathematical set $\denote{\tn}$, the *denotation* of $\tn$. For example, we might have $\denote{\texttt{bool}}= \{\mathsf{true},
\mathsf{false}\}$ and $\denote{\texttt{integer}} = \mathbb{Z}$ and $\denote{\pairOf{a}{b}} = \denote{a} \times \denote{b}$. We assume that if $T,
T^{\prime} \in \Uni$ and $T \ne T^{\prime}$ then $\denote{T}$ and $\denote{T^{\prime}}$ are disjoint, and we put

$$\denote{\Uni} = \bigdisj{\{\denote{T}: T \in \Uni\}}.$$

See Section [\[sec:cardano-builtins\]](#sec:cardano-builtins){reference-type="ref" reference="sec:cardano-builtins"} for a description of the types and functions which have already been deployed on the Cardano blockchain (or will be in the near future).

For non-atomic type names $\tn = \op(\tn_1, \ldots, \tn_r)$ we would generally expect the denotation of $\tn$ to be obtained in some uniform way (ie, parametrically) from the denotations of $\tn_1, \ldots, \tn_r$; we do not insist on this though.

### Type variables {#sec:type-variables}

Built-in functions can be polymorphic, and to deal with this we need *type variables*. An argument of a polymorphic function can be either restricted to built-in types or can be an arbitrary term, and we define two different kinds of type variables to cover these two situations. See Figure [\[fig:type-variables\]](#fig:type-variables){reference-type="ref" reference="fig:type-variables"}.

::: minipage
$$\begin{array}{lrclr}
        \textrm{TypeVariable}    & \textit{tv}& ::= & n_{\#} & \textrm{built-in-polymorphic type variable}\\
                                 &    &      & \star & \textrm{fully-polymorphic type variable}\\
    \end{array}$$ []{#fig:type-variables label="fig:type-variables"}
:::

We denote the set of all possible type variables by $\Var$ and the set of all built-in-polymorphic type variables $v_\#$ by $\Var_\#$. Note that $\Var \cap
\Uni = \varnothing$ since the symbols $\star$ and ${}_\#$ do not occur in names in $\Uni$.

The two kinds of type variable are required because we have two different kinds of polymorphism. Later on we will see that built-in functions can take arguments which can be of a type which is unknown but must be in $\Uni$, whereas other arguments can range over a larger set of values such as the set of all Plutus Core terms. Type variables in $\Var_\#$ are used in the former situation and $\star$ is used in the latter.

### Polymorphic types {#sec:polymorphic-types}

We also need to talk about polymorphic types, and to do this we define an extended universe of polymorphic types $\Unihash$ by adjoining $\Var_\#$ to $\Uni_0$ and closing under type operators as before:

$$\Unihashn{0} = \Uni_0 \cup \Var_\#$$ $$\Unihashn{i+1} = \Unihashn{i} \cup \{\op(\tn_1, \ldots, \tn_{\valency{\op}}): \op \in \TyOp, \tn_1, \ldots, \tn_{\valency{op}} \in \Unihashn{i}\}$$ $$\Unihash = \bigcup\{\Unihashn{i}: i \in \Nplus\}.$$ We will denote a typical element of $\Unihash$ by the symbol $P$ (possibly subscripted).

We define the set of *free #-variables* of an element of $\Unihash$ by $$\fv{P} = \varnothing \ \text{if $P \in \Uni_0$}$$ $$\fv{v_\#} = \{v_\#\}$$ $$\fv{\op(P_1, \ldots, P_k)} = \fv{P_1} \cup \fv{P_2} \cup \cdots \cup \fv{P_r}.$$

Thus $\fv{P} \subseteq \Var_\#$ for all $P \in \Uni$. We say that a type name $P \in \Unihash$ is *monomorphic* if $\fv{P} = \varnothing$ (in which case we actually have $P \in \Uni$); otherwise $P$ is *polymorphic*. The fact that type variables in $\Unihash$ are only allowed to come from $\Var_\#$ will ensure that values of polymorphic types such as lists and pairs can only contain values of built-in types: in particular, we will not be able to construct types representing things such as lists of Plutus Core terms.

### Type assignments {#sec:type-assignments}

A *type assignment* is a function $S: D \rightarrow \Uni$ where $D$ is some subset of $\Var_\#$. As usual we say that $D$ is the *domain* of $S$ and denote it by $\dom S$.

We can extend a type assignment $S$ to a map $\Sext : \Unihash \disj \VarStar \rightarrow \Unihash \disj \VarStar$ by defining

$$\begin{align*}
    \Sext(v_\#) &= S(v_\#) \quad \text{if $v_\# \in \dom S$}\\
    \Sext(v_\#) &= v_\# \quad \text{if $v_\# \in \Var_\# \backslash \dom S$}\\
    \Sext(T) &= T \quad\text{if $T \in \Uni_0$}     \\
    \Sext(\op(P_1,\ldots,P_n)) &= \op(\Sext(P_1),\ldots,\Sext(P_n))\\
    \Sext(\star) &= \star.
\end{align*}$$

If $P \in \Unihash$ and $S$ is a type assignment with $\fv{P}
\subseteq \dom S$ then in fact $\Sext(P) \in \Uni$; in this case we say that $\Sext(P)$ is an *instance* or a *monomorphisation* of $P$ (*via $S$*). If $T$ is an instance of $P$ then there is a unique smallest $S$ (with $\fv{P}=\dom S$) such that $T = \Sext(P)$: we write $T\preceq_S P$ to indicate that $T$ is an instance of $P$ via $S$ and $S$ is minimal.

#### Constructing type assignments.

We say that a collection $\{S_i: 1 \leq i \leq n\}$ of type assignments is *consistent* if $S_i|_{D_{ij}} = S_j|_{D_{ij}}$ for all $i$ and $j$, where $|$ denotes function restriction and $D_{ij} = \dom S_i \ \cap \ \dom
S_j$. If this is the case then (viewing functions as sets of pairs in the usual way) $S_1 \cup \cdots \cup S_n$ is also a well-formed type assignment (each variable in its domain is associated with exactly one type).

Given $T \in \Uni$ and $P \in \Unihash$ it can be shown that $T \preceq_S P$ if and only if one of the following holds:

- $T = P$ and $S =\varnothing$.

- $P \in \Var_\#$ and $S = \{(v_\#, T)\}$.

- - $T = \op(T_1, \ldots, T_n)$ with each $T_i \in \Uni$.

  - $P = \op(P_1, \ldots, P_n)$ with each $P_i \in \Unihash$.

  - $T_i \preceq_{S_i} P_i$ for $1 \leq i \leq n$.

  - $\{S_1, \ldots, S_n\}$ is consistent.

  - $S = S_1 \cup \cdots \cup S_n$.

This allows us to decide whether $T \in \Uni$ is an instance of $P \in
\Unihash$ and, if so, to construct an $S$ with $T \preceq_S P$.

## Built-in functions {#sec:builtin-functions}

### Inputs to built-in functions {#sec:builtin-inputs}

To treat the typed and untyped versions of Plutus Core uniformly it is necessary to make the machinery of built-in functions generic over a set $\Inputs$ of *inputs* which are taken as arguments by built-in functions. In practice $\Inputs$ will be the set of Plutus Core values or something very closely related.

We require $\Inputs$ to have the following two properties:

- $\Inputs$ is disjoint from $\denote{\tn}$ for all $\tn \in \Uni$

- There should be disjoint subsets $\Con{\tn} \subseteq \Inputs$ (where $\tn
    \in \Uni$) of *constants of type $\tn$* and maps $\denote{\cdot}_{\tn}:
    \Con{\tn} \rightarrow \denote{\tn}$ (*denotation*) and $\reify{\cdot}_{\tn}: \denote{\tn} \rightarrow \Con{\tn}$ (*reification*) such that $\reify{\denote{c}_{\tn}}_{\tn} = c \text{
      for all } c \in \Con{\tn}$. We do not require these maps to be bijective (for example, there may be multiple inputs with the same denotation), but the condition implies that $\denote{\cdot}_{\tn}$ is surjective and $\reify{\cdot}_{\tn}$ is injective.

It is also convenient to let $\denote{\Inputs} = \Inputs$ and define both $\denote{\cdot}_{\Inputs}$ and $\reify{\cdot}_{\Inputs}$ to be the identity function, and we write $$\denote{\Uni}_{\Inputs} = \denote{\Uni} \disj \Inputs.$$

For example, we could take $\Inputs$ to be the set of all Plutus Core values (see Section [\[sec:uplc-values\]](#sec:uplc-values){reference-type="ref" reference="sec:uplc-values"}), $\Con{\tn}$ to be the set of all terms of the form $\con{\tn}{c}$, and $\denote{\cdot}_{\tn}$ to be the function which maps $\con{\tn}{c}$ to $c$. For simplicity we are assuming that mathematical entities occurring as members of type denotations $\denote{\tn}$ are embedded directly as values $c$ in Plutus Core constant terms. In reality, tools which work with Plutus Core will need some concrete syntactic representation of constants; we do not specify this here, but see Section [\[sec:cardano-builtins\]](#sec:cardano-builtins){reference-type="ref" reference="sec:cardano-builtins"} for suggested syntax for the built-in types currently in use on the Cardano blockchain.

### Outputs of built-in functions {#sec:builtin-outputs}

All built-in functions either fail or conceptually return a non-empty list whose entries lie either in the denotation of some built-in type $T$ or in the set of inputs $\Inputs$, i.e., builtins return elements of the set ${(\R^+)_{\errorX}}$, where

$$\R := \bigdisj\left\{\denote{\tn}: \tn \in \Uni \right\} \disj \Inputs.$$

We will denote elements of $\R^+$ by expressions of the form $(v|v_1,
\ldots, v_k)$ with $v, v_i \in \R$ and $k \geq 0$, the case $k=0$ indicating a list $(v|)$ with a single entry. Currently all builtins return a single value, and to simplify notation we will identify $\R$ with $\{(v|): v \in \R\}
\subseteq \R^+$. The intention is that $(v|v_1, \ldots, v_k)$ will immediately be interpreted as an application $v \;v_1\; \ldots\; v_k$ in the ambient language (eg, typed or untyped Plutus Core); the number of arguments $k$ may depend on the values of the inputs to the function.

### Signatures and denotations of built-in functions {#sec:signatures}

We will consistently use the symbol $\tau$ and subscripted versions of it to denote members of $\UnihashStar$ in the rest of the document; these indicate the types of values consumed by built-in functions.

We also define a class of *quantifications* which are used to introduce type variables: a quantification is a symbol of the form $\forallty{v}$ with $v \in \Var$; the set of of all possible quantifications is denoted by $\QVar$.

#### Signatures.

Every built-in function $b \in \Fun$ has a *signature* $\sigma(b)$ which describes the types of its arguments and its return value: a signature is of the form $$[\iota_1, \ldots, \iota_n] \rightarrow \omega$$ with

- $\iota_j \in \UnihashStar \disj \QVar \enspace\text{for all $j$}$

- $\omega \in \UnihashStarAp$

- $\lvert\{j : \iota_j \notin \QVar\}\rvert \geq 1$ (so $n \geq 1$)

- If $\iota_j$ involves $v \in \Var$ then $\iota_k = \forallty{v}$ for some $k < j$, and similarly for $\omega$; in other words, any type variable $v$ must be introduced by a quantification before it is used. (Here $\iota$ *involves* $v$ if either $\iota = \tn \in \Unihash$ and $v \in \fv{\tn}$ or $\iota = v$ and $v \in \VarStar$.)

- If $\omega$ involves $v \in \Var$ then some $\iota_j$ must involve $v$; this implies that $\fv{\omega} \subseteq \bigcup \{\fv{\iota_j}: \iota_j \in
      \Unihash\}$ (where we extend the earlier definition of $\mathsf{FV}_{\#}$ by setting $\fv{\ap}=\varnothing$).

- If $j \neq k$ and $\iota_j, \iota_k \in \QVar$ then $\iota_j \neq
      \iota_k$; ie, no quantification appears more than once.

- If $\iota_i = \forall v \in \QVar$ then some $i_j \notin \QVar$ with $j
      > i$ must involve $v$ (signatures are not allowed to contain phantom type variables).

For example, in our default set of built-in functions we have the functions `mkCons` with signature $[\forall a_\#, a_\#,$ $\listOf{a_\#}] \rightarrow \listOf{a_\#}$ and `ifThenElse` with signature $[\forallStar, \mathtt{bool}, \star, \star] \rightarrow \star$. When we use `mkCons` its arguments must be of built-in types, but the two final arguments of `ifThenElse` can be any Plutus Core values.

If $b$ has signature $[\iota_1, \ldots, \iota_n] \rightarrow \omega$ then we define the *arity* of $b$ to be $$\alpha(b) = [\iota_1, \ldots, \iota_n].$$

We also define $$\chi(b) = n.$$

We may abuse notation slightly by using the symbol $\sigma$ to denote a specific signature as well as the function which maps built-in function names to signatures, and similarly with the symbol $\alpha$.

Given a signature $\sigma = [\iota_1, \ldots, \iota_n] \rightarrow \omega$, we define the *reduced signature* $\sigmabar$ to be $$\sigmabar = [\iota_j : \iota_j \notin \QVar] \rightarrow \omega$$

Here we have extended the usual set comprehension notation to lists in the obvious way, so $\sigmabar$ just denotes the signature $\sigma$ with all quantifications omitted. We will often write a reduced signature in the form $[\tau_1, \ldots, \tau_m] \rightarrow \omega$ to emphasise that the entries are *types*, and $\mathbf{\forall}$ does not appear.

Also, given an arity $= [\iota_1, \ldots, \iota_n]$, the *reduced arity* is $$\alphabar = [\iota_j : \iota_j \notin \QVar].$$

#### Commentary.

What is the intended meaning of the notation introduced above? In Typed Plutus Core we have to instantiate polymorphic functions (both built-in functions and polymorphic lambda terms) at concrete types before they can be applied, and in Untyped Plutus Core instantiation is replaced by an application of `force`. When we are applying a built-in function we supply its arguments one by one, and we can also apply `force` (or perform type instantiation in the typed case) to a partially-applied builtin "between" arguments (and also after the final argument); no computation occurs until all arguments have been supplied and all `force`s have been applied. The arity (read from left to right) specifies what types of arguments are expected and how they should be interleaved with applications of `force`, and $\chi(b)$ tells you the total number of arguments and applications of `force` that a built-in function $b$ requires. The fully-polymorphic type variable $\star$ indicates that an arbitrary value from $\Inputs$ can be provided, whereas a type from $\Unihash$ indicates that a value of the specified built-in type is expected. Occurrences of quantifications indicate that `force` is to be applied to a partially-applied builtin; we allow this purely so that partially-applied builtins can be treated in the same way as delayed lambda-abstractions: `force` has no effect unless it is the very last item in the signature. In Plutus Core, partially-applied builtins are values which can be treated like any others (for example, by being passed as an argument to a `lam`-expression): see Section [\[sec:uplc-values\]](#sec:uplc-values){reference-type="ref" reference="sec:uplc-values"}.

In general a builtin returns a sequence $(v|v_1,\ldots,v_k) \in \R^+$, but in fact the majority of builtins currently deployed on Cardano only return a single value, and in this case we can specify a signature where $\omega$ is either a built-in type name $T$ or $\star$, denoting an input (typically a value in the ambient language), and this tells us exactly what sort of value is returned. The general case is considerably more complicated: the size of the list returned, and the types of its entries, may be different for different inputs. To specify this sort of behaviour precisely in a signature would require a considerable increase in the complexity of the notation for signatures, so instead we approximate all return types involving elements of $\R^+\backslash
\R$ by $\ap$. However, when specifying the semantics of particular builtins with $\omega = \ap$ we will always give a precise description of the possible return values.

### Denotations of built-in functions {#sec:builtin-denotations}

The basic idea is that a built-in function $b$ should represent some mathematical function on the denotations of the types of its inputs. However, this is complicated by the presence of polymorphism and we have to require that there is such a function for every possible monomorphisation of $b$.

More precisely, suppose that we have a builtin $b$ with reduced signature $[\tau_1, \ldots \tau_n] \rightarrow \omega$. For every type assignment $S$ with $\dom S = \fv{\tau_1} \cup \cdots \cup \fv{\tau_n}$ (which contains $\fv{\omega}$ by the conditions on signatures in Section [1.2.3](#sec:signatures){reference-type="ref" reference="sec:signatures"}) we require a *denotation of $b$ at $S$*, a function $$\denote{b}_S: \denote{\Sext(\tau_1)} \times \cdots \times \denote{\Sext(\tau_n)} \rightarrow \withError{\denote{\Sext(\omega)}}$$ where $$\denote{\star} = \Inputs \quad\text{and}\quad \denote{\ap} = \R^+.$$ This makes sense because $\Sext(\tau_i) \in \Uni \disj
\Inputs$ for all $i$, so $\denote{\Sext(\tau_i)}$ is always defined, and similarly for $\omega$ (extending $\Sext$ by setting $\Sext(\ap) = \ap$).

If $\fv{\sigmabar(b)} = \varnothing$ (in which case we say that $b$ is *monomorphic*) then the only relevant type assignment will be the empty one; in this case we have a single denotation $$\denote{b}_\varnothing: \denote{\tau_1} \times \cdots \times \denote{\tau_n} \rightarrow \withError{\denote{\omega}}.$$

Denotations of builtins are mathematical functions which terminate on every possible input; the symbol $\errorX$ can be returned by a function to indicate that something has gone wrong, for example if an argument is out of range.

In practice we expect most builtins to be *parametrically polymorphic* [@Wadler-theorems-for-free; @Reynolds-parametric], so that the denotation $\denote{b}_S$ will be the "same" for all type assignments $S$; we do not insist on this though.

### Results of built-in functions. {#sec:builtin-results}

Recall from Section [1.2.2](#sec:builtin-outputs){reference-type="ref" reference="sec:builtin-outputs"} that the result of the evaluation of a built-in function lies in the set $$(\R^+)_{\errorX} = \left(\bigdisj\left\{\denote{\tn}: \tn \in \Uni \right\} \disj \Inputs \right)^+ \disj \{\errorX\}.$$ Since we have assumed that all denotations $\denote{T}$ with $T \in
\Uni$ are disjoint from each other and from $\Inputs$ (Section [1.2.1](#sec:builtin-inputs){reference-type="ref" reference="sec:builtin-inputs"}) we can define a function $$\reify{\cdot}: \R \rightarrow \withError{\Inputs}$$ which converts elements $r \in \R$ back into inputs by $$\reify{r} = 
\begin{cases}
  \reify{r}_{\tn} \in \Con{\tn} \subseteq \Inputs & \text{if $r \in \denote{\tn}$}\\
  r & \text{if $r \in \Inputs$}
\end{cases}$$ (see Section [1.2.1](#sec:builtin-inputs){reference-type="ref" reference="sec:builtin-inputs"} for the definition of $\reify{\cdot}_{\tn}$), and we can extend this to a function $\reify{\cdot}: (\R^+)_{\errorX} \rightarrow \withError{\Inputs}$ by defining

$$\begin{align*}
  \reify{(r, r_1, \ldots, r_k)} &= (\reify{r}|\reify{r_1}, \ldots, \reify{r_k})\\
  \reify{\errorX} &= \errorX.
\end{align*}$$

### Parametricity for fully-polymorphic arguments {#sec:builtin-behaviour}

A built-in function $b$ can only inspect arguments which are values of built-in types; other arguments (occurring as $\star$ in $\sigmabar(b)$) are treated opaquely, and can be discarded or returned as (part of) a result, but cannot be altered or examined (in particular, they cannot be compared for equality): $b$ is *parametrically polymorphic* in such arguments. This implies that if the sequence returned by a builtin contains a value $v \in \Inputs$, then $v$ must have been an argument of the builtin.

## Evaluation of built-in functions {#sec:builtin-evaluation}

### Compatibility of inputs and signature entries {#sec:compatibility}

The previous section describes how a built-in function is interpreted as a mathematical function. When a Plutus Core built-in function $b$ is applied to a sequence of arguments, the arguments must have types which are compatible with the signature of $b$; for example, if $b$ has signature $[\forallStar, \forall a_\#, \forall b_\#, a_\#, b_\#, a_\#, \star, \star] \rightarrow \star$ and $b$ is applied to a sequence of inputs $V_1, V_2, V_3, V_4, V_5$ then $V_1, V_2$, and $V_3$ must all be constants of some monomorphic built-in types and the types of $V_1$ and $V_3$ must be the same; $V_4$ and $V_5$ can be arbitrary inputs. This section describes the conditions for type compatibility.

In detail, given a reduced arity $\alphabar = [\tau_1, \ldots,
  \tau_n]$, a sequence $\bar{V} = [V_1, \ldots, V_m]$, and a type assignment $S$ we say that $\bar{V}$ is *compatible with* $\alphabar$ (*via* $S$) if and only if $n=m$ and, letting $I = \{i: 1 \leq i \leq n, \tau_i \in
\Unihash\}$ (so $\tau_j = \star$ if $j \notin I$), there exist type assignments $S_i$ ($1 \leq i \leq n$) such that all of the following are satisfied

- For all $i \in I$ there exists $T_i \in \Uni$ such that $V_i \in \Con{T_i}$ and $T_i \preceq_{S_i} \tau_i$.

- $\{S_i: i \in I\}$ is consistent (see Section [1.1.3](#sec:type-assignments){reference-type="ref" reference="sec:type-assignments"}).

- $S = \bigcup\{S_i: i \in I\}$.

If these conditions are all satisfied then we can find suitable $S_i$ using the procedure described in Section [1.1.3](#sec:type-assignments){reference-type="ref" reference="sec:type-assignments"} and this allows us to construct $S$ explicitly since the $S_i$ are consistent. Note that in this case $\dom S = \dom S_1 \cup \ldots \cup \dom S_n = \fv{\tau_1} \cup
\cdots \cup \fv{\tau_n} = \fv{\alpha}$, so $S$ is minimal in the sense that no $S'$ with $\dom S'$ strictly smaller than $\dom S$ is sufficient to monomorphise all of the $\tau_i$ simultaneously. We write $$[V_1, \ldots, V_m] \approx_S [\tau_1, \ldots, \tau_n]$$ in this case. If $\bar{V}$ is not compatible with $\alphabar$ then we write $\bar{V} \napprox \alphabar$.

### Evaluation {#sec:eval}

For later use we define a function $\Eval$ which attempts to evaluate an application of a built-in function $b$ to a sequence of inputs $[V_1, \ldots,
  V_m]$. This fails if the number of inputs is incorrect or if the inputs are not compatible with $\alphabar(b)$: $$\Eval(b,[V_1, \ldots, V_n]) = \errorX \quad \text{if $[V_1, \ldots, V_n] \napprox \alphabar(b)$}.$$

Otherwise, the conditions for the existence of a denotation of $b$ are met and we can apply that denotation to the denotations of the inputs and then reify the result. If $[V_1, \ldots, V_n] \approx_S \alphabar(b) = [\tau_1,
  \ldots, \tau_n]$, let $T_i = \Sext(\tau_i)$ for $1 \leq i \leq n$; then we define

$$\Eval(b,[V_1, \ldots, V_n]) = \reify{\denote{b}_S (\denote{V_1}_{T_1}, \ldots, \denote{V_n}_{T_n})}.$$ It can be checked that the compatibility condition guarantees that this makes sense according to the definition of $\denote{b}_S$ in Section [1.2.4](#sec:builtin-denotations){reference-type="ref" reference="sec:builtin-denotations"}.

#### Notes.

- All of the machinery which we have defined for built-in functions is parametric over the set $\Inputs$ of inputs and the sets $\Con{T} \subseteq
      \Inputs$ of constants. This also applies to the $\Eval$ function, so its meaning is not fully defined until we have given concrete definitions of the sets of inputs and constants.

- The error value $\errorX$ can occur in two different ways: either because the arguments are not compatible with the signature, or because the builtin itself returns $\errorX$ to signal some error condition.

- The symbol $\errorX$ is not part of Plutus Core; when we define reduction rules and evaluators for Plutus Core later some extra translation will be required to convert the result of $\Eval$ into something appropriate to the context.
