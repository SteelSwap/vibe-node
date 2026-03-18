# Rewards and the Epoch Boundary
In order to handle rewards and staking, we must change filter the UTxO for Ada-only values before performing any calculations. We also use the overloaded $\sum$ symbol for monoid addition here.


*Stake Distribution (using functions and maps as relations)* $$\begin{align*}
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