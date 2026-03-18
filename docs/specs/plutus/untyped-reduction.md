# Term reduction
This section defines the semantics of (untyped) Plutus Core.

#### More notation.

Suppose that $A$ is a well-formed partial application with $\alpha(\beta(A)) = [\iota_1,\ldots,\iota_n]$. We define a function $\nextArg$ which extracts the next argument (or `force`) expected by $A$: $$\nextArg(A) = \iota_{\pbasize{A}+1}.$$ This makes sense because in a well-formed partial application $A$ we have $\pbasize{A} < n$.

We also define a function $\args{}$ which extracts the arguments which $b$ has received so far in $A$: $$\begin{array}{ll}
  \args(\builtin{b}) &= []\\
  \args(\appU{A}{V}) &= \args(A)\snoc V\\
  \args(\force{A})   &= \args(A).\\
\end{array}$$

## Term reduction
We define the semantics of Plutus Core using contextual semantics (or reduction semantics): see [@Felleisen-Hieb] or [@Felleisen-Semantics-Engineering] or [@Harper:PFPL 5.3], for example. We use $A$ to denote a partial application of a built-in function as in Section \[sec:uplc-values\] above. For builtin evaluation, we instantiate the set $\Inputs$ of Section \[sec:builtin-inputs\] to be the set of Plutus Core values. Thus all builtins take values as arguments and return a value or $\errorX$. Since values are terms here, we can take $\reify{V} = V$.

The notation $[V/x]M$ below denotes substitution of the value $V$ for the variable $x$ in $M$. This is *capture-avoiding* in that substitution is not performed on occurrences of $x$ inside subterms of $M$ of the form $\lamU{x}{N}$.


$$\begin{array}{lrclr}
        \textrm{Frame} & f  & ::=   & \inAppLeftFrame{M}                                       & \textrm{left application}\\
                       &   &     & \inAppRightFrame{V}                                         & \textrm{right application}\\
                       &   &     & \inForceFrame                                               & \textrm{force}\\
                       &   &     & \inConstrFrame{i}{\repetition{V}}{\repetition{M}}           & \textrm{constructor argument}\\
                       &   &     & \inCaseFrame{\repetition{M}}                                & \textrm{case scrutinee}
    \end{array}$$

**Grammar of reduction frames for Plutus Core**

::: prooftree

::: prooftree

::: prooftree

::: prooftree

::: prooftree

::: prooftree

::: prooftree

::: prooftree

::: prooftree

**Reduction via contextual semantics**

$$\Eval'(b, [V_1, \ldots, V_n]) =
  \begin{cases}
    \errorU  & \text{if $\Eval(b,[V_1, \ldots, V_n]) = \errorX$}\\
    V & \text{if $\Eval(b,[V_1, \ldots, V_n]) = (V|)$}\\
    [V \repetition{V^{\prime}}] & \text{if $\Eval(b,[V_1, \ldots, V_n]) = (V|\repetition{V^{\prime}})$ with $\repetition{V^{\prime}}$ nonempty.}
  \end{cases}$$

**Built-in function application**

**Term reduction for Plutus Core**

It can be shown that any closed Plutus Core term whose evaluation terminates yields either `(error)` or a value. Recall from Section \[sec:grammar-notes\] that we require the body of every Plutus Core program to be closed.
