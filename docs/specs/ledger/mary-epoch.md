# Rewards and the Epoch Boundary
In order to handle rewards and staking, we must change the stake distribution calculation function to add up only the Ada in the UTxO before performing any calculations. In Figure 1 below, we do so using the function $\fun{utxoAda}$, which returns the amount of Ada tokens in an address.


*Helper function* $$\begin{align*}
    & \fun{utxoAda} \in \UTxO \to \Addr \to \Coin \\
    & \fun{utxoAda}~{\var{utxo}}~\var{addr} ~=~\sum_{\var{out} \in \range \var{utxo}, \fun{getAddr}~\var{out} = \var{addr}} \fun{getCoin}~\var{out}
\end{align*}$$ *Stake Distribution (using functions and maps as relations)* $$\begin{align*}
      & \fun{stakeDistr} \in \UTxO \to \DState \to \PState \to \type{Stake}\\
      & \fun{stakeDistr}~{utxo}~{dstate}~{pstate} =
      (\dom{\var{activeDelegs}})\restrictdom\left(\sum\var{stakeRelation}\right)\\
      & \where \\
      & ~~~~ (\var{stdelegs},~\var{rewards},~\var{delegations},~\var{ptrs},~\wcard,~\wcard)
        = \var{dstate} \\
      & ~~~~ (\var{stpools},~\wcard,~\wcard,~\wcard,~\wcard) = \var{pstate} \\
      & ~~~~ \var{stakeRelation} = \left(
        \left(\fun{stakeCred_b}^{-1}\cup\left(\fun{addrPtr}\circ\var{ptr}\right)^{-1}\right)
        \circ\left(\fun{utxoAda}~{\var{utxo}}\right)
        \right)
        \cup \left(\fun{stakeCred_r}^{-1}\circ\var{rewards}\right) \\
      & ~~~~ \var{activeDelegs} =
               (\dom{stdelegs}) \restrictdom \var{delegations} \restrictrange (\dom{stpools}) \\
\end{align*}$$

**Stake Distribution Function**