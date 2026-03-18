# Rewards and the Epoch Boundary
In order to handle rewards and staking, we must change the stake distribution calculation function to add up only the Ada in the UTxO before performing any calculations. In Figure 1 below, we do so using the function $\mathsf{utxoAda}$, which returns the amount of Ada tokens in an address.


*Helper function* $$\begin{align*}
    & \mathsf{utxoAda} \in \mathsf{UTxO} \to \mathsf{Addr} \to \mathsf{Coin} \\
    & \mathsf{utxoAda}~{\mathit{utxo}}~\mathit{addr} ~=~\sum_{\mathit{out} \in \range \mathit{utxo}, \mathsf{getAddr}~\mathit{out} = \mathit{addr}} \mathsf{getCoin}~\mathit{out}
\end{align*}$$ *Stake Distribution (using functions and maps as relations)* $$\begin{align*}
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