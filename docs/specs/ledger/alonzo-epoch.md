# Rewards and the Epoch Boundary
In order to handle rewards and staking, we must change filter the UTxO for Ada-only values before performing any calculations. We also use the overloaded $\sum$ symbol for monoid addition here.


*Stake Distribution (using functions and maps as relations)* $$\begin{align*}
      & \mathsf{stakeDistr} \in \mathsf{UTxO} \to \mathsf{DState} \to \mathsf{PState} \to \mathsf{Stake}\\
      & \mathsf{stakeDistr}~{utxo}~{dstate}~{pstate} =
      (\mathrm{dom}~\mathit{activeDelegs})\lhd\left(\sum\mathit{stakeRelation}\right)\\
      & \where \\
      & ~~~~ (\mathit{stdelegs},~\mathit{rewards},~\mathit{delegations},~\mathit{ptrs},~\underline{\phantom{a}},~\underline{\phantom{a}})
        = \mathit{dstate} \\
      & ~~~~ (\mathit{stpools},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}}) = \mathit{pstate} \\
      & ~~~~ \mathit{stakeRelation} = \left(
        \left(\mathsf{stakeCred_b}^{-1}\cup\left(\mathsf{addrPtr}\circ\mathit{ptr}\right)^{-1}\right)
        \circ\left(\mathsf{utxoAda}~{\mathit{utxo}}\right)
        \right)
        \cup \left(\mathsf{stakeCred_r}^{-1}\circ\mathit{rewards}\right) \\
      & ~~~~ \mathit{activeDelegs} =
               (\mathrm{dom}~stdelegs) \lhd \mathit{delegations} \rhd (\mathrm{dom}~stpools) \\
\end{align*}$$

**Stake Distribution Function**