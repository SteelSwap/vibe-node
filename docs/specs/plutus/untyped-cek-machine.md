# The CEK machine

This section contains a description of an abstract machine for efficiently executing Plutus Core. This is based on the CEK machine of Felleisen and Friedman [@Felleisen-CK-CEK].

The machine alternates between two main phases: the *compute* phase ($\triangleright$), where it recurses down the AST looking for values, saving surrounding contexts as frames (or *reduction contexts*) on a stack as it goes; and the *return* phase ($\triangleleft$), where it has obtained a value and pops a frame off the stack to tell it how to proceed next. In addition there is an error state $\cekerror$ which halts execution with an error, and a halting state $\cekhalt{}$ which halts execution and returns a value to the outside world.

To evaluate a program $\texttt{(program}\ v\ M \texttt{)}$, we first check that the version number $v$ is valid, then start the machine in the state $[];[]
\triangleright M$. It can be proved that the transitions in Figure 5 always preserve validity of states, so that the machine can never enter a state such as $[] \triangleleft M$ or $s,
\texttt{(force \_)} \triangleleft \texttt{(lam}\ x\ A \ M\texttt{)}$ which isn't covered by the rules. If such a situation were to occur in an implementation then it would indicate that the machine was incorrectly implemented or that it was attempting to evaluate an ill-formed program (for example, one which attempts to apply a variable to some other term).


$$\begin{array}{lrclr}
    \textrm{State} & \Sigma & ::= & s;\rho \compute M \enspace | \enspace s \return V  \enspace |
       \enspace \cekerror{} \enspace | \enspace \cekhalt{V}\\
    \textrm{Stack} & s      & ::= & f^*\\
    \textrm{CEK value} & V &  ::= & \VCon{\tn}{c} \enspace | \enspace \VDelay{M}{\rho}
       \enspace| \enspace \VLamAbs{x}{M}{\rho} \enspace \\
       &&& | \enspace \VConstr{i}{\repetition{V}} \enspace | \enspace \VBuiltin{b}{\repetition{V}}{\eta}\\
    \textrm{Environment} & \rho & ::= & [] \enspace | \enspace \rho[x \mapsto V] \\
    \textrm{Expected builtin arguments} & \eta & ::= & [\iota] \enspace | \enspace \iota \cons \eta\\
    \end{array}$$

**Grammar of CEK machine states for Plutus Core**

$$\begin{array}{lrclr}
        \textrm{Frame} & f  & ::=   & \inForceFrame                                                       & \textrm{force}\\
                       &    &       & \inAppLeftFrame{(M,\rho)}                                           & \textrm{left application to term}\\
                       &    &       & \inAppLeftFrame{V}                                                  & \textrm{left application to value}\\
                       &    &       & \inAppRightFrame{V}                                                 & \textrm{right application of value}\\
                       &    &       & \inConstrFrame{i}{\repetition{V}}{(\repetition{M}, \rho)}           & \textrm{constructor argument}\\
                       &    &       & \inCaseFrame{(\repetition{M}, \rho)}                                & \textrm{case scrutinee}

    \end{array}$$

**Grammar of CEK stack frames**

Figures 1 and 2 define some notation for *states* of the CEK machine: these involve a modified type of value adapted to the CEK machine, environments which bind names to values, and a stack which stores partially evaluated terms whose evaluation cannot proceed until some more computation has been performed (for example, since Plutus Core is a strict language function arguments have to be reduced to values before application takes place, and because of this a lambda term may have to be stored on the stack while its argument is being reduced to a value). Environments are lists of the form $\rho = [x_1 \mapsto V_1, \ldots, x_n \mapsto
  V_n]$ which grow by having new entries appended on the right; we say that *$x$ is *bound* in the environment $\rho$* if $\rho$ contains an entry of the form $x \mapsto V$, and in that case we denote by $\rho[x]$ the value $V$ in the rightmost (ie, most recent) such entry.[^1]

To make the CEK machine fit into the built-in evaluation mechanism defined in Section \[sec:specify-builtins\] we define $\Inputs = V$ and $\Con{\tn} =
\{\VCon{\tn}{c} : \tn \in \Uni, c \in \denote{\tn}\}$.

The rules in Figure 5 show the transitions of the machine; if any situation arises which is not included in these transitions (for example, if a frame $\inAppRightFrame{\VCon{\tn}{c}}$ is encountered or if an attempt is made to apply `force` to a partial builtin application which is expecting a term argument), then the machine stops immediately in an error state.


<!-- minipage -->
$$\begin{alignat*}
{2}
 s;\rho & \compute x                                 &~\mapsto~& s \return  \rho[x] \enskip \text{if $x$ is bound in $\rho$}\\
 s;\rho & \compute \con{\tn}{c}                       &~\mapsto~& s \return \VCon{\tn}{c}\\
 s;\rho & \compute \lamU{x}{M}                       &~\mapsto~& s \return \VLamAbs{x}{M}{\rho}\\
 s;\rho & \compute \delay{M}                         &~\mapsto~& s\return \VDelay{M}{\rho}\\
 s;\rho & \compute \force{M}                         &~\mapsto~& \inForceFrame{} \cons s;\rho \compute M \\
 s;\rho & \compute \appU{M}{N}                       &~\mapsto~& \inAppLeftFrame{(N,\rho)} \cons s ;\rho \compute M\\
  s;\rho & \compute \constr{i}{M \cons \repetition{M}} &~\mapsto~& \inConstrFrame{i}{[]}{(\repetition{M},\rho)} \cons s ;\rho \compute M\\
 s;\rho & \compute \constr{i}{[]} &~\mapsto~&  s \return \VConstr{i}{[]}\\
 s;\rho & \compute \kase{N}{\repetition{M}} &~\mapsto~&  \inCaseFrame{(\repetition{M},\rho)} \cons s ;\rho \compute N\\
% No nullary builtins (yet)
 s;\rho & \compute \builtin{b}                      &~\mapsto~& s \return \VBuiltin{b}{[]}{\arity{b}}\\
 s;\rho & \compute \errorU                           &~\mapsto~& \cekerror{}\\
\\[-10pt] %% Put some vertical space between compute and return rules, but not a whole line
[] & \return V                                    &~\mapsto~& \cekhalt{V}\\
\inAppLeftFrame{(M,\rho)}  \cons s            & \return V  &~\mapsto~& \inAppRightFrame{V} \cons s;\rho \compute M\\
\inAppRightFrame{\VLamAbs{x}{M}{\rho}} \cons s   & \return V  &~\mapsto~& s;\rho[x \mapsto V] \compute M\\
\inAppLeftFrame{V} \cons s   & \return \VLamAbs{x}{M}{\rho}  &~\mapsto~& s;\rho[x \mapsto V] \compute M\\
\inAppRightFrame{\VBuiltin{b}{\repetition{V}}{(\iota \cons \eta)}} \cons s & \return V &~\mapsto~&
                         s \return \VBuiltin{b}{(\repetition{V} \snoc V)}{\eta} \enskip \text{if $\iota \in \Unihash \cup \VarStar$}\\
\inAppLeftFrame{V} \cons s & \return \VBuiltin{b}{\repetition{V}}{(\iota \cons \eta)} &~\mapsto~&
                         s \return \VBuiltin{b}{(\repetition{V} \snoc V)}{\eta} \enskip \text{if $\iota \in \Unihash \cup \VarStar$}\\
\inAppRightFrame{\VBuiltin{b}{\repetition{V}}{[\iota]}} \cons s  & \return V &~\mapsto~&
                         \EvalCEK\,(s, b, \repetition{V}\snoc V) \enskip \text{if $\iota \in \Unihash \cup \VarStar$}\\
\inAppLeftFrame{V} \cons s & \return \VBuiltin{b}{\repetition{V}}{[\iota]} &~\mapsto~&
                         \EvalCEK\,(s, b, \repetition{V}\snoc V) \enskip \text{if $\iota \in \Unihash \cup \VarStar$}\\
\inForceFrame{} \cons s & \return \VDelay{M}{\rho}         &~\mapsto~& s;\rho \compute M\\
\inForceFrame{} \cons s & \return \VBuiltin{b}{\repetition{V}}{(\iota \cons \eta)} &~\mapsto~&
                         s \return \VBuiltin{b}{\repetition{V}}{\eta} \enskip \text{if $\iota \in \QVar$}\\
\inForceFrame{} \cons s & \return \VBuiltin{b}{\repetition{V}}{[\iota]}   &~\mapsto~&
                         \EvalCEK\,(s, b, \repetition{V}) \enskip \text{if $\iota \in \QVar$}\\
\inConstrFrame{i}{\repetition{V}}{(M \cons \repetition{M}, \rho)} \cons s & \return V   &~\mapsto~&
                         \inConstrFrame{i}{\repetition{V} \cons V}{(\repetition{M}, \rho)} \cons s;\rho \compute M \\
\inConstrFrame{i}{\repetition{V}}{([], \rho)} \cons s & \return V   &~\mapsto~&
                         s \return \VConstr{i}{\repetition{V} \cons V} \\
\inCaseFrame{(M_1 \ldots M_n, \rho)} \cons s & \return \VConstr{i}{V_1 \ldots V_m}   &~\mapsto~&
                         \inAppLeftFrame{V_1} \cons \cdots \cons \inAppLeftFrame{V_m} \cons s ;\rho \compute M_{i+1} \enskip \text{if $0 \leq i \leq n-1$}
\end{alignat*}$$

**CEK machine transitions for Plutus Core**

$$\begin{align*}
 \EvalCEK(s, b, [V_1, \ldots, V_n]) =
  &   \begin{cases}
        \cekerror  & \text{if $r = \errorX$}\\
        \inAppLeftFrame{V^{\prime}_m} \cons \cdots \cons \inAppLeftFrame{V^{\prime}_1} \cons s \return V^{\prime}
          & \text{if $r = (V^{\prime}|V^{\prime}_1,\ldots,V^{\prime}_m) \in \R^{+}$}
      \end{cases}\\
  &  \;\;\text{where $r = \Eval\,(b,[V_1, \ldots, V_n])$}\\
\end{align*}$$

**Evaluation of built-in functions**

**A CEK machine for Plutus Core**

## Converting CEK evaluation results into Plutus Core terms

The purpose of the CEK machine is to evaluate Plutus Core terms, but in the definition in Figure 5 it does not return a Plutus Core term; instead the machine can halt in two different ways:

- The machine can halt in the state $\cekhalt{V}$ for some CEK value $V$.

- The machine can halt in the state $\cekerror{}$ .

To get a complete evaluation strategy for Plutus Core we must convert these states into Plutus Core terms. The term corresponding to $\cekerror{}$ is $\errorU$, and to obtain a term from $\cekhalt{V}$ we perform a process which we refer to as *discharging* the CEK value $V$ (also known as *unloading*: see [@Plotkin-cbn-cbv pp. 129--130], [@Felleisen-pllc pp. 71ff]). This process substitutes bindings in environments for variables occurring in the value $V$ to obtain a term $\unload{V}$: see Figure 6. Since environments contain bindings $x \mapsto W$ of variables to further CEK values, we have to recursively discharge those bindings first before substituting: see Figure 7, which defines an operation $\Unload{\rho}{}$ which does this. As before $[N/x]M$ denotes the usual (capture-avoiding) process of substituting the term $N$ for all unbound occurrences of the variable $x$ in the term $M$. Note that in Figure 7 we substitute the rightmost (ie, the most recent) bindings in the environment first.


$$\begin{align*}
      \unload{\VCon{\tn}{c}} &= \con{\tn}{c}\\
      \unload{\VDelay{M}{\rho}}
        &= \Unload{\rho}{\delay{M}}\\
      \unload{\VLamAbs{x}{M}{\rho}} &= \Unload{\rho}{\lamU{x}{M}}\\
      \unload{\VConstr{i}{\repetition{V}}} &= \constr{i}{\repetition{\unload{V}}}\\
      \unload{\VBuiltin{b}{V_1 V_2\ldots V_k}{\eta}} &=
      \appU{\ldots}  % [...[[(builtin b) V1!] V2!] ... Vk!]
           {\appU
             {\appU
               {\builtin{b}}
               {(\unload{V_1})}
             }
             {(\unload{V_2})}
             {\ldots (\unload{V_k})}
           }
\end{align*}$$

**Discharging CEK values**

$$\begin{align*}
      \Unload{\rho}{M} &= [(\unload{V_1})/x_1]\cdots[(\unload{V_n})/x_n]M \quad
      \text{if $\rho = [x_1 \mapsto V_1, \ldots, x_n \mapsto V_n]$}
\end{align*}$$

**Iterated substitution/discharging**

**Discharging CEK values to obtain Plutus Core terms**

We can prove that if we evaluate a closed Plutus Core term in the CEK machine and then convert the result back to a term using the above procedure then we get the result that we should get according to the semantics in Figure \[fig:untyped-term-reduction\].

[^1]: The description of environments we use here is more general than necessary in that it permits a given variable to have multiple bindings; however, in what follows we never actually retrieve bindings other than the most recent one and we never remove bindings to expose earlier ones. The list-based definition has the merit of simplicity and suffices for specification purposes but in an implementation it would be safe to use some data structure where existing bindings of a given variable are discarded when a new binding is added.
