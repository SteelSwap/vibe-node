# Proofs {#sec:proofs}

For the proofs we use the automated theorem prover MetiTarski [@DBLP:journals/jar/AkbarpourP10] which is specialized for proofs over real arithmetic, including elementary functions.

::: proof
*Proof.* The property ([\[prop:minimal-refund\]](#prop:minimal-refund){reference-type="ref" reference="prop:minimal-refund"}) (p. ) for the minimal refund can be proven automatically via

    fof(minimal_refund, conjecture,
    ! [Dmin, Lambda, Delta, Dval] :
    ((Dmin : (=0,1=) & Lambda > 0 & Delta > 0 & Dval > 0
    =>
    Dval*Dmin >= 0 &
    (Dval * (Dmin + (1 - Dmin) * exp(-Lambda * Delta))) : (=Dval * Dmin, Dval=)))).

    fof(floor_lower_upper, conjecture,
    ! [X] :
    (X >= 0 => X - 1 <= floor(X) & floor(X) <= X)).

`minimal_refund` shows that the resulting value is within the interval $[d_{val}\cdot d_{min}, d_{val}]$ and that $d_{val}\cdot d_{min}$ is non-negative, while `floor_lower_upper` shows that the floor of a value $x$ has an upper bound $x$ and lower bound $x - 1$. ◻
:::

::: proof
*Proof.* For the property ([\[prop:reward-splitting\]](#prop:reward-splitting){reference-type="ref" reference="prop:reward-splitting"}) (p. ) for reward splitting we actually show a stronger one, by removing the floor function. Using the fractional values we get an upper bound for the real value and showing that this upper bound is bounded by $\hat{f}$ we show that the real value is also bounded by $\hat{f}$. To eliminate the sum, we use the identity $\frac{s +
    \sum_{j}t_{j}}{\sigma} = 1$, see the definition of $\sigma$ in [@delegation_design]. Using this, we show for $\hat{f} > c$

$$\begin{equation*}
    \begin{array}{cll}
      & 0 \leq c + (\hat{f} - c)\cdot (m + (1 - m))\cdot \frac{s}{\sigma} +
        \sum_{j}(\hat{f}-c)\cdot(1-m)\cdot\frac{t_{j}}{\sigma} & \leq \hat{f} \\
      \Leftrightarrow &
                        0\leq c + (\hat{f}-c)\cdot m \cdot \frac{s}{\sigma} + (\hat{f}
                        -c)\cdot(1-m)\cdot\frac{s + \sum_{j}t_{j}}{\sigma} & \leq \hat{f} \\
      \Leftrightarrow &
                        0\leq c + (\hat{f}-c)\cdot m \cdot \frac{s}{\sigma} + (\hat{f}
                        -c)\cdot(1-m) & \leq \hat{f} \\
    \end{array}
\end{equation*}$$

This can be proven automatically using

    fof(reward_splitting, conjecture,
    ! [C, F, M, S, Sigma] :
    (
    M : (=0, 1=) & C >= 0 & F > C & Sigma : (0, 1=) & S : (=0, Sigma=)
    =>
    C + (F - C) * M * S / Sigma + (F - C) * (1 - M) <= F &
    0 <= C + (F - C) * M * S / Sigma + (F - C) * (1 - M))).

 ◻
:::
