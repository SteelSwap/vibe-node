# The grammar of Plutus Core {#sec:untyped-plc-grammar}

This section presents the grammar of Plutus Core in a Lisp-like form. This is intended as a specification of the abstract syntax of the language; it may also by used by tools as a concrete syntax for working with Plutus Core programs, but this is a secondary use and we do not make any guarantees of its completeness when used in this way. The primary concrete form of Plutus Core programs is the binary format described in Appendix [\[appendix:flat-serialisation\]](#appendix:flat-serialisation){reference-type="ref" reference="appendix:flat-serialisation"}.

## Lexical grammar {#sec:untyped-plc}

::: minipage
$$\begin{array}{lrclr}

        \textrm{Name}          & n      & ::= & \texttt{[a-zA-Z][a-zA-Z0-9\_\textquotesingle]*(-[0-9]+)?}   & \textrm{name}\\

        \textrm{Var}           & x      & ::= & n & \textrm{term variable}\\
        \textrm{BuiltinName}   & bn     & ::= & n & \textrm{built-in function name}\\
        \textrm{Version} & v & ::= & \texttt{[0-9]+.[0-9]+.[0-9]+}& \textrm{version}\\
        \textrm{Natural}  & k      & ::= & \texttt{[0-9]+} & \textrm{a natural number}\\
        \textrm{Constant} & c & ::= & \langle{\textrm{literal constant}}\rangle& \\

    \end{array}$$ []{#fig:lexical-grammar-untyped label="fig:lexical-grammar-untyped"}
:::

## Grammar

::: minipage
$$\begin{array}{lrclr}
    \textrm{Term}       & L,M,N  & ::= & x                               & \textrm{variable}\\
                        &        &     & \con{\tn}{c}                    & \textrm{constant}\\
                        &        &     & \builtin{b}                     & \textrm{builtin}\\
                        &        &     & \lamU{x}{M}                     & \textrm{$\lambda$ abstraction}\\
                        &        &     & \appU{M}{N}                     & \textrm{function application}\\
                        &        &     & \delay{M}                       & \textrm{delay execution of a term}\\
                        &        &     & \force{M}                       & \textrm{force execution of a term}\\
                        &        &     & \constr{k}{M_1 \ldots M_m}      & \textrm{constructor with tag $k$ and $m$ arguments ($m \geq 0$)}\\
                        &        &     & \kase{M}{N_1 \ldots N_n}        & \textrm{case analysis with $n$ alternatives ($n \geq 0$)}\\
                        &        &     & \errorU                         & \textrm{error}\\
        \textrm{Program}& P      & ::= & \version{v}{M}                  & \textrm{versioned program}

    \end{array}$$ []{#fig:untyped-grammar label="fig:untyped-grammar"}
:::

## Notes {#sec:grammar-notes}

#### Version numbers.

The version number at the start of a program specifies the Plutus Core language version used in the program.

A *Plutus Core language version* describes a version of the basic language with a particular set of features. A language version consists of three non-negative integers separated by decimal points, for example `1.4.2`. Language versions are ordered lexicographically.

The grammar above describes Plutus Core version 1.1.0. Version 1.0.0 is identical, except that `constr` and `case` are not included. Version 1.0.0 is fully forward-compatible with version 1.1.0, so any valid version 1.0.0 program is also a valid version 1.1.0 program. The semantics, evaluator and serialisation formats described later in this document all apply to both versions, except that it is an error to use `constr` or `case` in any program with a version prior to 1.1.0: a parser, deserialiser, or evaluator should fail immediately if `constr` or `case` is encountered when processing such a program.

#### Scoping.

For simplicity, **we assume throughout that the body of a Plutus Core program is a closed term**, ie, that it contains no free variables. Thus `(program 1.0.0 (lam x x))` is a valid program but `(program 1.0.0 (lam x y))` is not, since the variable `y` is free. This condition should be checked before execution of any program commences, and the program should be rejected if its body is not closed. The assumption implies that any variable $x$ occurring in the body of a program must be bound by an occurrence of `lam` in some enclosing term; in this case, we always assume that $x$ refers to the *most recent* (ie, innermost) such binding.

#### Iterated applications.

An application of a term $M$ to a term $N$ is represented by $\appU{M}{N}$. We may occasionally write $\appU{M}{N_1 \ldots N_k}$ or $\appU{M}{\repetition{N}}$ as an abbreviation for an iterated application $\mathtt{[}\ldots\mathtt{[[}M\;N_1\mathtt{]}\;N_2\mathtt{]}\ldots$ $N_k\mathtt{]}$, and tools may also use this as concrete syntax.

#### Constructors and case analysis.

Plutus Core supports creating structured data using $\keyword{constr}$ and deconstructing it using $\keyword{case}$. Both of these terms are unusual in that they have (possibly empty) lists of children: $\keyword{constr}$ has the (0-based) *tag* and then a list of arguments; $\keyword{case}$ has a scrutinee and then a list of case branches. The behaviour of $\keyword{constr}$ and $\keyword{case}$ is mostly straightforward: $\keyword{constr}$ evaluates its arguments and forms a value; $\keyword{case}$ evaluates the scrutinee into a $\keyword{constr}$ value, selects the branch corresponding to the tag on the value (if the tag is $k$ and the branches are $N_1, \ldots, N_n$ then it selects $N_{k+1}$, with an error occurring if $k$ does not lie between 0 and $n-1$), and then applies that to the arguments in the value. Note that $\keyword{case}$ does *not* strictly evaluate the case branches, only applying (and hence evaluating) the one that is eventually selected. The list of branches in $\keyword{case}$ is allowed to be empty, but in that case there will be an error if it is ever applied to a scrutinee.

#### Constructor tags.

Constructor tags can in principle be any natural number. In practice, since they cannot be dynamically constructed, we can limit them to a fixed size without having to worry about overflow. So we limit them to 64 bits, although this is currently only enforced in the binary format (see Section [\[sec:flat-term-encodings\]](#sec:flat-term-encodings){reference-type="ref" reference="sec:flat-term-encodings"}).

#### Built-in types and functions.

The language is parameterised by a set $\Uni$ of *built-in types* (we sometimes refer to $\Uni$ as the *universe*) and a set $\Fun$ of *built-in functions* (*builtins* for short), both of which are sets of Names. Briefly, the built-in types represent sets of constants such as integers or strings; constant expressions $\con{\tn}{c}$ represent values of the built-in types (the integer 123 or the string `"string"`, for example), and built-in functions are functions operating on these values, and possibly also general Plutus Core terms. Precise details are given in Section [\[sec:specify-builtins\]](#sec:specify-builtins){reference-type="ref" reference="sec:specify-builtins"}.

See Section [\[sec:cardano-builtins\]](#sec:cardano-builtins){reference-type="ref" reference="sec:cardano-builtins"} for a description of the types and functions which have already been deployed on the Cardano blockchain (or will be in the near future).

#### De Bruijn indices.

The grammar defines names to be textual strings, but occasionally (specifically in Appendix [\[appendix:flat-serialisation\]](#appendix:flat-serialisation){reference-type="ref" reference="appendix:flat-serialisation"}) we want to use de Bruijn indices ([@deBruijn], [@Barendregt C.3]), and for this we redefine names to be natural numbers. In de Bruijn terms, $\lambda$-expressions do not need to bind a variable, but in order to re-use our existing syntax we arbitrarily use 0 for the bound variable, so that all $\lambda$-expressions are of the form `(lam 0 `$M$`)`; other variables (ie, those not appearing immediately after a `lam` binder) are represented by natural number greater than zero.

#### Name suffixes.

Names may include an optional numeric suffix consisting of a dash followed by one or more digits (for example, `x-0`, `name-42`, or `variable-12345`). This suffix provides a mechanism for disambiguating variables that share the same base name, allowing multiple distinct variables with identical textual representations to coexist within a program.

#### Lists in constructor and case terms.

The grammar defines constructor and case terms to have a variable number of subterms written in sequence with no delimiters. This corresponds to the concrete syntax, e.g. we write $\constr{0}{t_1\ t_2\ t_3}$. However, in the rest of the specification we will abuse notation and treat these terms as having *lists* of subterms.
