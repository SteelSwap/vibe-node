# Protocol Parameters
## Updatble Protocol Parameters
The Shelley protocol parameters are listed in Figure 1. Some of the Shelley protocol parameters are common to the Byron era, specifically, the common ones are $\mathit{a}$, $\mathit{b}$, $\mathit{maxTxSize}$, and $\mathit{maxHeaderSize}$ (see the document [@byron_ledger_spec]).

The type $\mathsf{Ppm}$ represents the names of the protocol parameters, and $\mathsf{T_{ppm}}$ is the type of the protocol parameter $\mathit{ppm}$. The type $\mathsf{PParams}$ is a finite map containing all the Shelley parameters, indexed by their names. We will explain the significance of each parameter as it comes up in the calculations used in transition rules. The type $\mathsf{PParamsUpdate}$ is similar to $\mathsf{PParams}$, but is a partial mapping of the protocol parameters. It is used in the update system explained in Section sec:update.

The type $\mathsf{Coin}$ is defined as an alias for the integers. Negative values will not be allowed in UTxO outputs or reward accounts, and $\Z$ is only chosen over $\N$ for its additive inverses.

Some helper functions are defined in Figure 3. The $\mathsf{minfee}$ function calculates the minimum fee that must be paid by a transaction. This value depends on the protocol parameters and the size of the transaction.

Two time related types are introduced, $\mathsf{Epoch}$ and $\mathsf{Duration}$. A $\mathsf{Duration}$ is the difference between two slots, as given by $-$.

Lastly, there are two functions, $\mathsf{epoch}$ and $\mathsf{firstSlot}$ for converting between epochs and slots and one function $\mathsf{kesPeriod}$ for getting the cycle of a slot. Note that $\mathsf{Slot}$ is an abstract type, while the constants are integers. We use multiplication and division symbols on these distinct types without being explicit about the types and conversion.

::::: {#fig:defs:protocol-parameters .figure latex-placement="htb"}
*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{p} & \mathsf{Ppm} & \text{protocol parameter}\\
      \mathit{dur} & \mathsf{Duration} & \text{difference between slots}\\
      \mathit{epoch} & \mathsf{Epoch} & \text{epoch} \\
      \mathit{kesPeriod} & \mathsf{KESPeriod} & \text{KES period} \\
    \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{pp}
      & \mathsf{PParams}
      & \mathsf{Ppm} \to \mathsf{T_{ppm}}
      & \text{protocol parameters}
      \\
      \mathit{ppup}
      & \mathsf{PParamsUpdate}
      & \mathsf{Ppm} \mapsto \mathsf{T_{ppm}}
      & \text{protocol parameter update}
      \\
      \mathit{coin}
      & \mathsf{Coin}
      & \Z
      & \text{unit of value}
      \\
      \mathit{pv}
      & \mathsf{ProtVer}
      & \N\times\N
      & \text{protocol version}
    \end{array}
\end{equation*}$$ *Protocol Parameters* $$\begin{equation*}
      \begin{array}{rlr}
        \mathit{a} \mapsto \Z & \mathsf{PParams} & \text{min fee factor}\\
        \mathit{b} \mapsto \Z & \mathsf{PParams} & \text{min fee constant}\\
        \mathit{maxBlockSize} \mapsto \N & \mathsf{PParams} & \text{max block body size}\\
        \mathit{maxTxSize} \mapsto \N & \mathsf{PParams} & \text{max transaction size}\\
        \mathit{maxHeaderSize} \mapsto \N & \mathsf{PParams} & \text{max block header size}\\
        \mathit{keyDecayRate} \mapsto [0,~\infty) & \mathsf{PParams} & \text{stake credential decay rate}\\
        \mathit{poolDeposit} \mapsto \mathsf{Coin} & \mathsf{PParams} & \text{stake pool deposit}\\
        \mathit{E_{max}} \mapsto \mathsf{Epoch} & \mathsf{PParams} & \text{epoch bound on pool retirement}\\
        \mathit{n_{opt}} \mapsto \mathsf{Npos} & \mathsf{PParams} & \text{desired number of pools}\\
        \mathit{a_0} \mapsto (0,~\infty) & \mathsf{PParams} & \text{pool influence}\\
        \tau \mapsto [0,~1] & \mathsf{PParams} & \text{treasury expansion}\\
        \rho \mapsto [0,~1] & \mathsf{PParams} & \text{monetary expansion}\\
        \mathit{d} \mapsto \{0,~0.1,~0.2,~\ldots,~1\} & \mathsf{PParams} & \text{decentralization parameter}\\
        \mathit{extraEntropy} \mapsto \mathsf{Seed} & \mathsf{PParams} & \text{extra entropy}\\
        \mathit{pv} \mapsto \mathsf{ProtVer} & \mathsf{PParams} & \text{protocol version}\\
        \mathit{minUTxOValue} \mapsto \mathsf{Coin} & \mathsf{PParams} & \text{minimum allowed value of a new \mathsf{TxOut}}\\
        \mathit{minPoolCost} \mapsto \mathsf{Coin} & \mathsf{PParams} & \text{minimum allowed stake pool cost}\\
      \end{array}
\end{equation*}$$ *Accessor Functions*

::: center
, , , , , , , , , , , , , , , ,

*Abstract Functions* $$\begin{equation*}
    \begin{array}{rlr}
      (-) & \mathsf{Slot} \to \mathsf{Slot} \to \mathsf{Duration}
                       & \text{duration between slots}
    \end{array}
\end{equation*}$$

**Definitions Used in Protocol Parameters**
:::::

## Global Constants
In additon to the updatable protocol parameters defined in Section 1.1, there are ten parameters which cannot be changed by the update system in Section sec:update. We call these the global constants, as changing these values can only be done by updating the software, i.e. a soft or a hard fork. For the software update mechanism, see Section sec:software-updates.

The constants $\mathsf{SlotsPerEpoch}$ and $\mathsf{SlotsPerKESPeriod}$ represent the number of slots in an epoch/KES period (for a brief explanation of a KES period, see Section sec:crypto-primitives-shelley). The constants $\mathsf{StabilityWindow}$ and $\mathsf{RandomnessStabilisationWindow}$ concern the chain stability. The maximum number of time a KES key can be evolved before a pool operator must create a new operational certificate is given by $\mathsf{MaxKESEvo}$. **Note that if** $\mathsf{MaxKESEvo}$ **is changed, the KES signature format may have to change as well.**

The constant $\mathsf{Quorum}$ determines the quorum amount needed for votes on the protocol parameter updates and the application version updates.

The constant $\mathsf{MaxMajorPV}$ provides a mechanism for halting outdated nodes. Once the major component of the protocol version in the protocol parameters exceeds this value, every subsequent block is invalid. See Figures fig:funcs:chain-helper and fig:rules:chain.

The constant $\mathsf{MaxLovelaceSupply}$ gives the total number of lovelace in the system, which is used in the reward calculation. It is always equal to the sum of the values in the UTxO, plus the sum of the values in the reward accounts, plus the deposit pot, plus the fee pot, plus the treasury and the reserves.

The constant $\mathsf{ActiveSlotCoeff}$ is the value $f$ from the Praos paper [@ouroboros_praos].

Lastly, $\mathsf{NetworkId}$ determines what network, either mainnet or testnet, is expected. This value will also appear inside every address, and transactions containing addresses with an unexpected network ID are rejected.


*Global Constants* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{SlotsPerEpoch} & \N & \text{- slots per epoch} \\
      \mathsf{SlotsPerKESPeriod} & \N & \text{- slots per KES period} \\
      \mathsf{StabilityWindow} & \mathsf{Duration} &
      \begin{array}{r}
        \text{- window size for chain growth} \\
        \text{guarantees, see}\text{ in \cite{ouroboros_praos}}
      \end{array} \\
      \mathsf{RandomnessStabilisationWindow} & \mathsf{Duration} &
      \begin{array}{r}
        \text{- duration needed for epoch}\\
        \text{nonce stabilization}\\
      \end{array} \\
      \mathsf{MaxKESEvo} & \N & \text{- maximum KES key evolutions}\\
      \mathsf{Quorum} & \N & \text{- quorum for update system votes}\\
      \mathsf{MaxMajorPV} & \N & \text{- all blocks are invalid after this value}\\
      \mathsf{MaxLovelaceSupply} & \mathsf{Coin} & \text{- total lovelace in the system}\\
      \mathsf{ActiveSlotCoeff} & (0, 1] & \text{ - }f\text{ in \cite{ouroboros_praos}}\\
      \mathsf{NetworkId} & \mathsf{Network} & \text{- the network, mainnet or testnet}\\
    \end{array}
\end{equation*}$$

**Global Constants**
*Helper Functions* $$\begin{align*}
    \mathsf{minfee} & \in \mathsf{PParams} \to \mathsf{Tx} \to \mathsf{Coin} & \text{minimum fee}\\
    \mathsf{minfee} & ~\mathit{pp}~\mathit{tx} =
    (\mathsf{a}~\mathit{pp}) \cdot \mathsf{txSize}~\mathit{tx} + (\mathsf{b}~\mathit{pp})
    \\
    \\
    \mathsf{epoch} & \in ~ \mathsf{Slot} \to \mathsf{Epoch} & \text{epoch of a slot}
    \\
    \mathsf{epoch} & ~\mathit{slot} = \mathit{slot}~/~\mathsf{SlotsPerEpoch}
    \\
    \\
    \mathsf{firstSlot} & \in ~ \mathsf{Epoch} \to \mathsf{Slot}
               & \text{first slot of an epoch}
    \\
    \mathsf{firstSlot} & ~\mathit{e} = \mathit{e}~\cdot~\mathsf{SlotsPerEpoch}
    \\
    \\
    \mathsf{kesPeriod} & \in ~ \mathsf{Slot} \to \mathsf{KESPeriod} & \text{KES period of a slot}
    \\
    \mathsf{kesPeriod} & ~\mathit{slot} = \mathit{slot}~/~\mathsf{SlotsPerKESPeriod}
\end{align*}$$

**Helper functions for the Protocol Parameters**