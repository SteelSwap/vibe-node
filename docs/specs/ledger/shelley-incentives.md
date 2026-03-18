::: changelog

::: landscape
<!-- [Image from original LaTeX source: d4-depends.pdf] Positioning of this Deliverable (outlined in red). -->

***Note: this document is subject to change. In particular, it may be necessary to include a simplified fees calculation in the incentivised TestNet, where all the fees accrue to the Treasury. Also note that some terms and symbols that were used in SL-D1 have been changed in this document in order to simplify the explanations that are given here. These are outlined in Appendix 4.***

# Introduction
The purpose of this document is to precisely explain the incentives schemes that will be used by the Shelley implementation of the Cardano blockchain, giving step-by-step explanations of the rewards calculations. It follows Section 5 of SL-D1 (Delegation/Incentives Design) [@delegation_design] and the more theoretical description of reward sharing schemes in [@bkks2018][^1], but aims to provide a more approachable description that can be used by e.g. StakePool owners/operators, delegators etc. It also explains the differences between the simplified scheme that will be used in the Shelley Incentivised TestNet implementation and the full scheme that will be used in the Shelley MainNet implementation.

Figure 1 gives some basic terminology that will be used in this document. The Shelley implementation rewards those ADA holders who either own active stake pools (*Owners*) or who delegate stake to active stake pools (*Delegators*). In line with the design of the Ouroboros protocol [@ouroboros_classic], the *StakePool* receives rewards in proportion to the stake that it *controls* ("proof of stake") rather than in proportion to the work that it does ("proof of work"). This has cost, efficiency and safety advantages. The rewards scheme is designed to help ensure that no single entity can dominate the system by *controlling* excessive amounts of ADA. This is achieved by creating intrinsic balancing mechanisms that will naturally spread all the active stake among a large number of StakePools. In particular, the rewards to any one *StakePool* may be capped to a pre-determined limit, meaning that both delegators and owners will receive less reward if too much stake is controlled by a single StakePool, so encouraging the creation of additional, smaller StakePools. It is also designed to ensure *non-myopic* behaviour. That is, it avoids chaotic system behaviour by encouraging the delegation of ADA to those StakePools that will provide the best overall returns over an extended period of time rather than over the short term. The overall theory that ensures this is described in the Ouroboros Praos research paper [@ouroboros_praos]; Section 5 of SL-D1 [@delegation_design] provides the design rationale for the actual incentives scheme.

::::: {#fig:terminology .figure latex-placement="t"}
::: center
  **Term**       **Definition**
  -------------- ------------------------------------------------------------------------------------------------------
  StakePool      A system that is actively participating in the creation of blocks on the Cardano blockchain
  Stake          An amount of ADA that is *controlled* by a StakePool.
  Epoch          A fixed period of time during which blocks are created, transactions run, and rewards earned.
  Operator       The entity that is responsible for running a StakePool.
  Owner(s)       The entities that *pledge* stake to the StakePool when it is registered.
  Delegator(s)   The entities that *delegate* stake to the StakePool.
  Treasury       A Central Repository of ADA to be distributed in future.
  Reserve        The ADA that is not yet in circulation.
  Distribution   The ADA that put into circulation in an Epoch.
  Reward         The ADA that is distributed to the Owner(s) and Delegator(s) of a sufficiently performant StakePool.
  MainNet        The full Shelley Cardano implementation.

**General Terminology**
:::::

### Notation

Throughout the document, the colour coding below is used to distinguish the sources of various parameters. A similar scheme is followed in the corresponding spreadsheets.

  **Green**   Parameters that are set by the Cardano system
  ----------- --------------------------------------------------------------
  **Red**     Parameters that are set by a StakePool's Owner(s)/Operator
  **Blue**    Parameters that are set externally
  **Cyan**    Parameters that are observed from the running implementation
  Black       Calculated parameters

## General Parameters

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**              **Expected Value**   **Definition**                                    
  -------------------------- -------------------- ------------------------------------------------- --
  **$N^{\textit{Pools}}$**   **50-1000**          **The Target Number of StakePools**               
  **$T$**                    **10%**              **The Treasury Top Slice Percentage**             
  **$\textit{MER}$**         **10%-15%**          **The "Monetary Expansion Rate" per Year**        
  **$\textit{DPE}$**         **1-5**              **Days per Epoch: Duration of a Cardano Epoch**   

**Key Operational Parameters.**
:::::

Four key operating parameters are set by the community (the initial values will be determined by ): $N^{\textit{Pools}}$, the target number of StakePools; $T$, the treasury top slice percentage; $\textit{MER}$, the monetary expansion per year; and $\textit{DPE}$, the length of each epoch, in days. The target number of StakePools is used to cap the rewards that any individual StakePool can receive. The intention is to encourage the creation of more StakePools, and to avoid domination by any single stake holder. The *treasury top slice percentage* is the fraction of reward that is allocated to the treasury to cover fixed operating costs, and ensure the long-term viability both of Cardano and of ADA as a currency. It is initially set to a small percentage (10%) of the rewards. The *monetary expansion rate* is the rate at which rewards are allocated from the *reserves* of ADA.

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**                        **Value**            **Description**                                       **Calculated as**
  ------------------------------------ -------------------- ----------------------------------------------------- ---------------------------------------------------------
  **$\textit{Ada}^{Tot}$**             *****ADA 45bn*****   **The total ADA that could ever be created**          
  **$\textit{Ada}^{\textit{Circ}}$**   *****ADA 31bn*****   **The total ADA in circulation at Shelley launch**    
  **$\textit{Ada}^{\textit{Rsv}}$**    *****ADA 14bn*****   **The total ADA in the reserves at Shelley launch**   **$\textit{Ada}^{Tot} - \textit{Ada}^{\textit{Circ}}$**

**Parameters that are set by External Factors (e.g. ADA holders).**
:::::

Several parameters are pre-determined by external factors. These include the total ADA that could ever be created, $\textit{Ada}^{Tot}$; the total ADA that is in *circulation* when the Shelley system launches (i.e. all ADA that is held by any entity on the launch date), $\textit{Ada}^{\textit{Circ}}$; and the ADA that is held in reserve when the system starts. These values are fixed and will not change.

## StakePools

### Operator-Set Parameters

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**                             **Range**                  **Description**
  ----------------------------------------- -------------------------- -------------------------------------------------
  **$\textit{Pool}^{\textit{Cost}}$**       *****ADA 0*** $\ldots$**   **Cost *per day* in ADA**
  **${\textit{Pool}}^{\textit{Margin}}$**   **0%-100%**                **Percentage charge on rewards (the "margin")**

**Key Parameters that are set by the StakePool Operator.**
:::::

The two main parameters that need to be set by the StakePool *Operator* are the cost *per day* that will be charged to the pool (in ADA), $\textit{Pool}^{\textit{Cost}}$; and the percentage of any rewards that will subsequently be taken as a fee, ${\textit{Pool}}^{\textit{Margin}}$. The cost is subtracted from the total rewards that are earned by the pool before any rewards are distributed. These parameters are advertised by the StakePool and used as part of the public ranking scheme.

### Private Stake Pools

If the pool charge rate (${\textit{Pool}}^{\textit{Margin}}$) is set to 100%, then the pool owner(s) will receive all the rewards that are allocated to the StakePool. This effectively makes the StakePool "private": all rewards that are earned for any stake that is delegated to the StakePool will be given to the owner(s). An owner may still choose to divide their stake between their pledge and their delegated stake if they wish, of course.

### Sources of Rewards

Rewards are taken from three sources:

1.  the monetary expansion distribution (Section 3.1);

2.  transaction fees (Section 3.2);

3.  non-refundable deposits.

In the Incentivised TestNet, only the first source is likely to be used.

### The Rewards that are received by a StakePool

The rewards that are received by a StakePool will be proportional to the total amount of ADA that it controls as a fraction of the total ADA that is in circulation. The *treasury top slice* is deducted from the total *rewards* for the epoch, then the remainder is distributed proportionately to each StakePool, depending on the stake it controls. In order to avoid domination by large StakePools, in the MainNet, a rewards *cap* will be applied to any single pool, based on the target number of StakePools, $N^{\textit{Pools}}$. This is described in more detail in Section 3.

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**                           **Description**                                                          **Calculated as**
  --------------------------------------- ------------------------------------------------------------------------ --------------------------------------------------------------------
  **${\textit{Pool}}^\textit{Pledge}$**   **ADA that is pledged to the StakePool by the Owner(s)**                 
  **${\textit{Pool}}^\textit{Deleg}$**    **ADA that is delegated to the StakePool**                               
  ${\textit{Pool}}^{Tot}$                 All ADA that is controlled by the StakePool                              ${\textit{Pool}}^\textit{Pledge} + {\textit{Pool}}^\textit{Deleg}$
  ${\textit{Pool}}^\%$                    Fraction of the ADA in circulation that is controlled by the StakePool   $\frac{{\textit{Pool}}^{Tot}}{\textit{Ada}^{\textit{Circ}}}$

**The ADA that is controlled by a StakePool.**
:::::

The total ADA that a StakePool controls is the sum of the ADA that is *pledged* to the StakePool by the owners(s) plus the additional ADA that is *delegated* to the StakePool. An owner may *delegate* to a StakePool if they wish as well as *pledging* to it, but would receive lower rewards for their *delegated* stake. In return for receiving higher rewards, *pledging* incurs higher risk, requiring owners to *trust* each other.

### The Rewards that are given to Owner(s) and Delegators

Once the pool operating charges are subtracted from the net rewards, any remaining reward is distributed to the owner(s) and delegators in proportion to their pledged/delegated stake.

# The Simplified Incentives Scheme (Shelley Incentivised TestNet)
The simplified scheme calculates rewards based on the total number of blocks that each stake pool produces, and distributes a fixed amount of ADA per epoch. Since Cardano is based on *proof of stake*, then on average, each stake pool will obtain rewards that are proportional to the stake that it holds. So, if e.g. a pool holds 1% of the total ADA in circulation, then it will receive, on average, 1% of the total rewards that are allocated to all the StakePools.

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**        **Expected Value**   **Definition**                                    
  -------------------- -------------------- ------------------------------------------------- --
  **$T$**              **10%**              **The Treasury Top Slice Percentage**             
  **$\textit{MER}$**   **10%**              **The "Monetary Expansion Rate" per Year**        
  **$\textit{DPE}$**   **1**                **Days per Epoch: Duration of a Cardano Epoch**   

**Settings for Key Operational Parameters in the Incentivised TestNet.**
:::::

In the Incentivised TestNet, the target number of StakePools, $N^{\textit{Pools}}$, will not be considered in the first release. The treasury top slice percentage, $T$ is fixed at 10% of the total distribution per epoch (this is expected to be unchanged in the MainNet). The monetary expansion rate, $\textit{Mer}$ is fixed at the equivalent of 10% per annum, so that precisely 10% of the ADA reserves would be distributed if the TestNet were to run for one complete year, or precisely 2.5% of the ADA reserves would be distributed if it were to run for 3 months. For simplicity and to ensure that epoch changes occur frequently, in the Incentivised TestNet, the length of each epoch ($\textit{DPE}$) has been set to 1 day.

::::: {#fig:distrib .figure latex-placement="h!"}
::: center
  **Parameter**        **Expected Value**   **Description**                         **Calculated as**
  -------------------- -------------------- --------------------------------------- ---------------------------------------------------------------------------------
  $\textit{Distr}_E$   ***ADA 3.84M***      Distribution per Epoch in the TestNet   $\frac{\textit{Ada}^{\textit{Rsv}} \times \textit{MER}}{365 \div \textit{DPE}}$
  $T_E$                ***ADA 384K***       Treasury Top Slice per Epoch            $\textit{Distr}_E \times T$
  $R_E$                ***ADA 3.45M***      Total Rewards per Epoch                 $\textit{Distr}_E - T_E$

**Total Distribution and Rewards per Epoch.**
:::::

The total ADA that is distributed per epoch in the Incentivised TestNet (${\textit{Distr}}_E$) is calculated from the initial value of the ADA reserves, $\textit{Ada}^{\textit{Rsv}}$, and the fixed monetary expansion rate, *MER*. An equal distribution is given per epoch. The top slice that is allocated to the treasury ($T_E$) is deducted from this distribution, and the remainder is then allocated to the StakePools as rewards ($R_E$).

### Transaction Fees in the Incentivised TestNet (possible addition)

Transaction fees are not considered initially in the Incentivised TestNet, but, if they are eventually included, would simply be allocated to the Treasury in their entirety. Deposits will not be considered in the Incentivised Testnet.

## The Rewards that are received by a StakePool per Epoch

::::: {#fig:rewards .figure latex-placement="h!"}
::: center
  **Parameter**                                  **Expected Value**   **Definition**                                                           **Calculated as**
  ---------------------------------------------- -------------------- ------------------------------------------------------------------------ ------------------------------------------------------------------------------
  **$\textit{\textit{Pool}}^{\textit{Cost}}$**                        **Cost per day in ADA**                                                  
  **${\textit{Pool}}^{\textit{Margin}}$**        **0%-100%**          **Percentage charge on rewards (the "margin")**                          
  **${\textit{Pool}}^\textit{Pledge}$**                               **ADA that is pledged to the StakePool by the Owner(s)**                 
  **${\textit{Pool}}^\textit{Deleg}$**                                **ADA that is delegated to the StakePool**                               
  ${\textit{Pool}}^{Tot}$                                             All ADA that is controlled by the StakePool                              ${\textit{Pool}}^\textit{Pledge} + {\textit{Pool}}^\textit{Deleg}$
  ${\textit{Pool}}^\%$                                                Fraction of the ADA in circulation that is controlled by the StakePool   $\frac{{\textit{Pool}}^{Tot}}{\textit{Ada}^{\textit{Circ}}_{\textit{Test}}}$
                                                                                                                                               

**Parameters Governing the Rewards to a StakePool.**
:::::

The parameters governing the StakePool reward calculation are shown above.

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**                            **Definition**                        **Calculated as**
  ---------------------------------------- ------------------------------------- ------------------------------------------------------------------------------------------------
  ${\textit{Pool}}^{\textit{Cost}}_E$      *Pool* Operator Costs for the Epoch   $\textrm{min}((\textit{\textit{Pool}}^{\textit{Cost}} \times \textit{DPE}),R_E)$
  $R^{\textit{Net}}$                       The Net Reward to the StakePool       $R_E - {\textit{Pool}}^{\textit{Cost}}_E$
  ${\textit{Pool}}^{\textit{Charges}}_E$   *Pool* Charges for the Epoch          $R^{\textit{Net}} \times \textit{Pool}^{\textit{Margin}}$
  $R^{Owner}$                              The Reward to the Owner(s)            $(R^{\textit{Net}}-\textit{Pool}^{\textit{Charges}}) \times {\textit{Pool}}^{\textit{Margin}}$
  $R^{Deleg}$                              The Reward to the Delegators          $(R^{\textit{Net}}-\textit{Pool}^{\textit{Charges}}) - R^{Owner}$
  $\textit{Owner}^\textit{Income}$         The Total Pool Owner Income           ${\textit{Pool}}^{\textit{Cost}}_E + {\textit{Pool}}^{\textit{Charges}}_E + R^{Owner}$

**Calculation of the Total Stake Pool Reward.**
:::::

The gross reward that is received by the StakePool is, on average, directly proportional to the stake that it controls, as a proportion of the total ADA that is in circulation. Once the fixed pool operator cost and the variable pool charges[^2]) are deducted, the remaining reward is then distributed to the owner(s) and delegators in proportion to the stake that each group controls. The StakePool owner income is then the total sum of the operator costs, the pool charges, and the pool owner rewards. Note that if there is insufficient gross reward to cover the operator costs, all the reward will be assigned to cover the pool cost, leaving no further reward to be distributed to either the owners or delegators, that is the *net reward* will be zero.

### The Rewards that are received by each Delegator per Epoch

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**             **Definition**                                                    **Calculated as**
  ------------------------- ----------------------------------------------------------------- --------------------------------------------------------------------
  ${\textit{Pool}}^{Tot}$   All ADA that is controlled by the StakePool                       ${\textit{Pool}}^\textit{Pledge} + {\textit{Pool}}^\textit{Deleg}$
  $R^{Deleg}$               The Reward to the Delegators                                      $(R^{\textit{Net}}-\textit{Pool}^{\textit{Charges}}) - R^{Owner}$
  $D^{Stake}$               The ADA that is delegated by Delegator $D$                        
  $D^\%$                    The proportion of ADA in the StakePool that is delegated by $D$   $\frac{D^{Stake}}{Pool^{Tot}}$
  $D^{Rewards}$             The ADA rewards that are received by $D$                          $R^{\textit{Deleg}} \times D^\%$

**The Rewards that are received by a specific Delegator, $D$.**
:::::

The rewards that are received by an individual delegator are directly proportional to the stake that the delegator has placed in the StakePool, calculated from the net rewards to the StakePool. This applies to the owner stake as well as to independent delegators. If there are multiple owners, rewards will subsequently be distributed between them according to an external agreement that will not be governed by or enforced by the TestNet.

## Calculating Rewards in External Currencies
::::: {#fig:monetary .figure latex-placement="h!"}
::: center
  **Value**   **Description**            **Calculated as**
  ----------- -------------------------- -------------------
  $R_A$       Rewards value in ADA       
  $ER_D$      Dollar Price per ADA       
  $R_D$       Rewards value in dollars   $R_A \times ER_D$

**Calculating Rewards in Terms of Other Currencies**
:::::

As usual, rewards in ADA can easily be converted to an external dollar or other currency equivalent using the current exchange rate, $ER_D$, as shown above. For example, if the rewards are ***ADA 10,000*** and the exchange rate is \$0.039 (1 ADA is worth 3.9 cents). Realising this value would require the use of an *exchange*, of course.

## Worked Example: Simplified Scheme

::: minipage
This example is taken from the internal spreadsheet calculator at <https://docs.google.com/spreadsheets/d/1c-KmCNBIMZjHN7wdsrNx3ac1zT8xEqodK1OyZxC_QIk/edit#gid=1365573139>. It has been used as the basis for the online calculator at <https://cardano-staking-site.netlify.com/en/>.

### Key Parameters

<!-- [Image from original LaTeX source] -->

<!-- [Image from original LaTeX source] -->

This diagram shows the key parameters and settings for the rewards system, including the rewards that are distributed from the reserves at each epoch. We assume a Treasury Top Slice of 10% and the target number of StakePools to be 100. The ADA in circulation and reserves are the values as of September 24$^{th}$ 2019, rounded to the nearest ADA1bn. We further assume a *monetary expansion rate* of 10% and that the TestNet will run for 180 days (this is used to calculate the initial values of the ADA in circulation and in reserve for the full incentives scheme). After the Treasury Top Slice is taken, the total rewards per Epoch (or Day) that will be distributed to the StakePools is ***ADA 3,452,054.79***.

### StakePool Parameters

<!-- [Image from original LaTeX source] -->

This diagram shows the StakePool-specific parameters, including the total controlled ADA and the division by owner(s) and delegators. Here, 98.71% of the StakePool ADA is owned by delegators. We choose a *margin* for the pool charges of 2.00% of the net income, and a daily *cost* of ***ADA 256.41*** (\$10). The gross reward to the StakePool is precisely the expected reward, since it controls exactly the required percentage of stake (1.00%, corresponding to the limit set from the $N^{\textit{Pools}}$ parameter). This is reduced in line with the StakePool's *actual performance* as observed by the system (here assumed to be 90%), giving a *penalty* that amounts to ***ADA 3452.05*** per day.

### Calculated Rewards

::: minipage
<!-- [Image from original LaTeX source] -->

<!-- [Image from original LaTeX source] -->

This diagram shows the corresponding rewards that accrue to the owner(s) and delegators, plus a calculation of the total income that is received by the owners. We will assume that the average and actual gross rewards are the same, i.e. if the StakePool controls 1% of the total ADA in circulation, it will produce exactly 1% of the blocks, and it would therefore receive exactly 1% of the total rewards as its *average gross rewards*. The *actual gross rewards*, $R^{\textit{Gross}}$ reduce this by its *actual performance* in epoch $E$, giving 0.9% of the total rewards. In total, the owners and delegators to this StakePool would receive a net reward that was equivalent to 7.11% per year (the "staking yield"). We assume that the owners have agreed an equal distribution of rewards. If there were 4 owners for the StakePool, each would then receive 25% of the owner rewards, i.e. $\textbf{\emph{ADA{}~{158,121.42}}} \div 4 ~~=~~ \textbf{\emph{ADA{}~{39,530.355}}}$. Similarly, a delegator contributing 10% of the delegated stake would receive 10% of the delegator reward, i.e., $\textbf{\emph{ADA{}~{12,096,288.83}}} \div 10 ~~=~~ \textbf{\emph{ADA{}~{1,209,628.8883}}}$. If we assume that the pool operating cost is accurate, then the net income to the pool owner(s) would be the sum of the pool charges and the rewards, i.e. ***ADA 367,140.88*** or a net return of 18.36% of the owners' stake.

## How Rewards are returned to Owners and Delegators
In the Incentivised Testnet, rewards will be calculated following the end of the epoch, and returned to wallets as part of the transition to the MainNet. This will be achieved using the instantaneous rewards return mechanism that is described below.

- When the testnet terminates, a snapshot will be taken in order to calculate the rewards that were earned. The result will be a mapping of stake keys to rewards as a whole number of Lovelace.

- The MIR certificate ("move instantaneous rewards") will contain a mapping of stake credentials (that are derived from the stake keys) to Lovelace amounts. These values will be auditable and visible on the blockchain. Any transaction containing one of these certificates must be entirely signed by a *quorum* of core nodes (currently set to be five or more).

- When the ledger processes a valid MIR certificate, it will ignore any stake credential that is not registered with the system. All the stake keys in the snapshot will be registered by . A deposit may be charged for the registration.

- The Lovelace values from all valid MIR certificates will be transferred from the ADA reserves to the relevant reward accounts.

# The Full Incentives Scheme (Shelley MainNet Implementation)
The full incentives scheme that will be used in the MainNet adds several additional aspects to the simple scheme above:

1.  Transaction fees that are added to the gross rewards;

2.  StakePool deposits, part of which are also added to the gross rewards;

3.  An "influence factor", that determines how much influence the owner(s)' stake has on the desirability of a StakePool;

4.  A monetary expansion rate that varies over time (decreasing in an exponential way);

5.  The performance of the system as a whole is taken into account;

6.  The *apparent performance* of the StakePool rather than its *actual performance*.

In addition, the number of days per epoch will be changed. Collectively, these changes implement the *non-myopic rewards* scheme of [@delegation_design; @bkks2018].

::::: {.figure latex-placement="h!"}
::: center
  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Parameter**               **Definition**
  --------------------------- --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **$\textit{inf}$**          **The influence Factor. The influence that the owner(s)' stake has on the desirability of a pool. This is a finite positive number, with 0 being no influence, and larger numbers being more influence.**

  **$\textit{Perf}_E$**       **The ratio of the number of blocks that were actually produced in Epoch $E$ to the expected average number of blocks that should be produced in an Epoch. This will be derived from the number of slots in the Epoch.**

  **$\textit{Fees}_E$**       **All the transaction fees for Epoch $E$**

  **$\textit{Deposits}_E$**   **The non-refundable deposits for Epoch $E$**

  **$\textit{MER}_E$**        **The "Monetary Expansion Rate" for Epoch $E$**.\
                              ***See Section 3.1.***
  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

**New Parameters used in the MainNet Incentives Calculation.**
:::::

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**                        **Expected Value**    **Description**                                                               **Calculated as**
  ------------------------------------ --------------------- ----------------------------------------------------------------------------- -----------------------------------------------------------------------------------
  ${\textit{Distr}}^{Test}$                                  The total Distribution of ADA that will be made by the Incentivised TestNet   
  $\textit{Ada}^{\textit{Circ}}_{0}$   ***ADA 31-31.5bn***   The ADA that is initially circulating in the MainNet                          $\textit{Ada}^{\textit{Circ}}_{\textit{Test}} + {\textit{Distr}}^{\textit{Test}}$
  $\textit{Ada}^{\textit{Rsv}}_{0}$    ***ADA 14-14.5bn***   The total ADA in the reserves at Shelley MainNet launch                       $\textit{Ada}^{Tot} - \textit{Ada}^{\textit{Circ}}_{0}$

**The ADA that is Initially in Circulation in the MainNet.**
:::::

The total ADA that will initially circulate in the MainNet, that is the ADA in circulation in Epoch 0 of the MainNet, $\textit{Ada}^{\textit{Circ}}_{0}$ will be the ADA that was in circulation at the launch of the Incentivised TestNet plus the total distribution that was made over the period of operation of the TestNet. Since an equal amount of ADA is distributed per epoch in the TestNet, the distribution is will just be the multiple of the number of epochs that the Incentivised TestNet has been active and the rewards distribution that has been made in each epoch.

::::: {.figure latex-placement="h!"}
::: center
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| **Parameter**                    | **Expected Initial Value** | **Description**                                     | **Calculated as**                                                                                 |
+:=================================+:===========================+:====================================================+:==================================================================================================+
| $\textit{E}$                     | $0$                        | The Current MainNet Epoch, $0 \le E \le \infty$     |                                                                                                   |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| **$\textit{DPE}$**               | **5**                      | **Days per Epoch: Duration of a Cardano Epoch**     |                                                                                                   |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| **$\textit{Fees}_E$**            |                            | **All the transaction fees for Epoch $E$**          |                                                                                                   |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| **$\textit{Deposits}_E$**        |                            | **The non-refundable deposits for Epoch $E$**       |                                                                                                   |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| $\textit{MER}_E$                 | 10%-15%                    | The "Monetary Expansion Rate" for Epoch $E$         | *See Section 3.1.*              |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| $\textit{Perf}_E$                | 80%-100%                   | The Overall Performance of the MainNet in Epoch $E$ |                                                                                                   |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| $\textit{Distr}_E$               | approx. ***ADA 62M***      | Gross Distribution for Epoch $E$                    | ::: flushleft                                                                                     |
|                                  |                            |                                                     | $\textit{Ada}^{\textit{Rsv}}_E \times \textit{MER}_E \times \textrm{min}(\textit{Perf}_E, 100\%)$ |
|                                  |                            |                                                     | :::                                                                                               |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| $\textit{Ada}^{\textit{Circ}}_E$ | approx. ***ADA 31.5bn***   | ADA in circulation in Epoch $E$                     | $\textit{Ada}^{\textit{Circ}}_{E-1} + \textit{Distr}_E$                                           |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| $\textit{Ada}^{\textit{Rsv}}_E$  | approx. ***ADA 14.5bn***   | ADA in reserve in Epoch $E$                         | $\textit{Ada}^{\textit{Rsv}}_{E-1} - \textit{Distr}_E$                                            |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+
| $R_E$                            | approx. ***ADA 56M***      | Total Rewards per Epoch                             | $(\textit{Distr}_E + \textit{Fees}_E + \textit{Deposits}_E) \div (\textit{inf}+1)$                |
+----------------------------------+----------------------------+-----------------------------------------------------+---------------------------------------------------------------------------------------------------+

**Total Distribution and Rewards per Epoch in the MainNet, with expected values for the first MainNet Epoch (Epoch 0).**
:::::

In the MainNet, the gross rewards distribution will depend on the current MainNet Epoch, $E$, and will reduce over time. The total ADA that is distributed during epoch $E$ in the MainNet (${\textit{Distr}}_E$) is calculated from the current value of the ADA reserves, $\textit{Ada}^{\textit{Rsv}}_E$, and the variable *monetary expansion rate* that is in force for the current epoch, $\textit{MER}_E$. This distribution is restricted by the *overall performance*, $\textit{Perf}_E$, which is defined as a fraction of the *expected performance* during Epoch $E$. The reserves will be depleted by the amount of new ADA that is distributed in the Epoch, $\textit{Distr}_E$. This gives the value of the reserve for the next Epoch, $\textit{Ada}^{\textit{Rsv}}_{E+1}$. The ADA in circulation, $\textit{Ada}^{\textit{Circ}}_{E+1}$ is correspondingly increased by the amount that has been distributed. Fees and non-returned deposits are added to the reward distribution. This total distribution is then modified by the *influence factor* (the higher the influence factor, the lower the total rewards) to give the total rewards per epoch, $R_E$.

## The Monetary Expansion Rate
::::: {.figure latex-placement="h!"}
::: center
<!-- [Image from original LaTeX source] -->\
<!-- [Image from original LaTeX source] -->

**Ada Rewards over Time, assuming $R^{\textit{Avg}}$=0.05, $\textit{Fee}_E$=2000, $\textit{Perf}_E=100\%$.**
:::::

The monetary expansion rate for Epoch $E$ is determined by the following equation:

$$\textit{MER}_E ~~=~~ \frac{\textit{Ada}^{Circ}_E \times (\sqrt[\textit{EPY}]{1+R^{\textit{Avg}}} - 1) - (1- T) \times \textit{Fees}_E}
                          {(1-T) \times \textit{min}(\textit{Perf}_E,100\%) \times (\textit{Ada}^{Tot} - Ada^{Circ}_E)}$$

where $R^{\textit{Avg}}$ is the expected average rewards per ADA per year, and $\textit{EPY}$ is the number of epochs per year (73 in non-leap years if $\textit{DPE} = 5$). $T$ is the pre-defined Treasury Top Slice (initially 10%). Assuming $R^{\textit{Avg}}$=0.05, $\textit{Fee}_E$=2000, and $\textit{Perf}_E=99\%$, with the other values as above, then we obtain $\textit{MER}_0 = 0.00178650067$, equating to monetary expansion of 13.04% over a year.

## Transaction Fees
The fee for each transaction $t$ is calculated as follows:

$$\textit{Fee} (t) ~=~ a + b \times \textit{size}(t)$$

where $a$ is a fixed fee for each transaction, and $b$ calculates an additional fee from the transaction size ($\textit{size}(t)$). This size function may be an abstract representation (e.g. the impact of the transaction on the size of the blockchain) rather than e.g. the actual physical size of the transaction.

## The Rewards that are received by a StakePool for Epoch $E$

::::: {#fig:rewards-MainNet .figure latex-placement="h!"}
::: center
  **Parameter**                                  **Expected Value**   **Definition**                                                                          **Calculated as**
  ---------------------------------------------- -------------------- --------------------------------------------------------------------------------------- --------------------------------------------------------------------
  **$\textit{\textit{Pool}}^{\textit{Cost}}$**                        **Cost per day in ADA**                                                                 
  **${\textit{Pool}}^{\textit{Margin}}$**        **0%-100%**          **Percentage chargee on rewards (the "margin")**                                        
  **${Pool}^\textit{Pledge}$**                                        **ADA that is pledged to the StakePool by the Owner(s)**                                
  **${\textit{Pool}}^\textit{Deleg}$**                                **ADA that is delegated to the StakePool**                                              
  ${\textit{Pool}}^{Tot}$                                             All ADA that is controlled by the StakePool                                             ${\textit{Pool}}^\textit{Pledge} + {\textit{Pool}}^\textit{Deleg}$
  ${\textit{Pool}}^\%$                                                Fraction of the ADA in circulation that is controlled by the StakePool                  $\frac{{\textit{Pool}}^{Tot}}{\textit{Ada}^{\textit{Circ}}_E}$
  ${\textit{Pledge}}^\%$                                              Fraction of the ADA in circulation that is *pledged* to the StakePool by the Owner(s)   $\frac{{\textit{Pool}}^{Pledge}}{\textit{Ada}^{\textit{Circ}}_E}$
                                                                                                                                                              
  **$N^{\textit{Pools}}$**                       **50-1000**          **The Target Number of StakePools**                                                     
  *z*                                            0.001-0.02           The Rewards Limit Fraction                                                              $\frac{1}{k}$
                                                                                                                                                              
  **$\textit{Pool}^{\textit{Perf}}$**                                 **The *Apparent Performance* of the StakePool**                                         

**Parameters Governing the Rewards to a StakePool in a given Epoch, $E$.**
:::::

The parameters that govern the StakePool reward calculation are shown above. Compared with the Incentivised TestNet, the only new parameters are the effective rewards rate to the owner(s), $s'$, the apparent performance of the StakePool, $\textit{Pool}^{\textit{Perf}}$, and the target number of StakePools, $N^{\textit{Pools}}$. In the MainNet, $N^{\textit{Pools}}$ is expected is expected to be 50-100 initially, but this will be increased as necessary to encourage the creation of more StakePools. It will therefore rise over time, up to about 1000 for the fully decentralised MainNet.

The effective rewards rate limits the rewards that the owners can receive. The *apparent performance* of a StakePool is calculated by dividing the fraction of blocks that the StakePool has created by the fraction of the total stake that it controls. This may be more than 100%.

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**                            **Definition**                                                                                                        **Calculated as**
  ---------------------------------------- --------------------------------------------------------------------------------------------------------------------- ------------------------------------------------------------------------------------------------
  $s^\%$                                   The *effective* stake                                                                                                 $\textrm{min} (z,{\textit{Pool}}^\%)$
  $p^\%$                                   The *effective* pledge                                                                                                $\textrm{min} (z,{\textit{Pledge}}^\%)$
  $\textit{R}^\textit{Factor}$             Overall StakePool rewards factor, taking into account the influence factor and rewards limit.                         $s^\% \times \textit{inf} \times ((s^\% - p^\% \times (z - s^\%)) \div z)$
  $R^{Optimal}$                            The Optimal Gross Reward to the StakePool. **This will be reduced to 0 if any Owner(s)' *pledge* is not honoured.**   $R_E \times \textit{R}^{Factor}$
  $R^{\textit{Gross}}$                     The Actual Gross Reward to the StakePool                                                                              $R^{Optimal} \times \textit{Pool}^{\textit{Perf}}$
  ${\textit{Pool}}^{\textit{Cost}}_E$      Pool Operator Costs for the Epoch                                                                                     $\textrm{min}(\textit{\textit{Pool}}^{\textit{Cost}} \times \textit{DPE},R^{\textit{Gross}})$
  $R^{\textit{Net}}$                       The Net Reward to the StakePool                                                                                       $R^{\textit{Gross}} - {\textit{Pool}}^{\textit{Cost}}_E$
  ${\textit{Pool}}^{\textit{Charges}}_E$   *Pool* Charges for the Epoch                                                                                          $R^{\textit{Net}} \times \textit{Pool}^{\textit{Margin}}$
  $R^{Owner}$                              The Reward to the Owner(s)                                                                                            $(R^{\textit{Net}}-\textit{Pool}^{\textit{Charges}}) \times {\textit{Pool}}^{\textit{Margin}}$
  $R^{Deleg}$                              The Reward to the Delegators                                                                                          $(R^{\textit{Net}}-\textit{Pool}^{\textit{Charges}}) - R^{Owner}$

**Calculation of the Total Stake Pool Reward (MainNet).**
:::::

As before, the gross reward that is received by the StakePool is, on average, directly proportional to the stake that it controls, as a proportion of the total ADA that is in circulation. The *optimal* reward is limited by the pre-calculated *rewards limit fraction*, and is further reduced in proportion to its *apparent performance*, $\textit{Pool}^{\textit{Perf}}$. Once the pool operator costs are subtracted, the net reward is then distributed to the owner(s) and delegators. The delegator reward is calculated as in the Incentivised TestNet, in proportion to the stake that has been delegated to the StakePool. The owner(s) reward is, however, limited by $p^\%$, the *effective rewards rate* to the owner(s). The StakePool owner income is then the sum of the operator costs and the pool owner rewards. **Note that, as before, if there is insufficient gross reward to cover the operator costs, all the reward will be used to cover those costs, leaving no further reward to be distributed to the either owners or delegators. Note also that if any Owner withdraws their *pledge* from the StakePool, no rewards will be received by the Owner(s) or the Delegator(s).**

### The Rewards that are received by each Delegator for Epoch $E$

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**             **Definition**                                                    **Calculated as**
  ------------------------- ----------------------------------------------------------------- --------------------------------------------------------------------
  ${\textit{Pool}}^{Tot}$   All ADA that is controlled by the StakePool                       ${\textit{Pool}}^\textit{Pledge} + {\textit{Pool}}^\textit{Deleg}$
  $R^{Deleg}$               The Reward to the Delegators                                      $(R^{\textit{Net}}-\textit{Pool}^{\textit{Charges}}) - R^{Owner}$
  $D^{Stake}$               The ADA that is delegated by Delegator $D$                        
  $D^\%$                    The proportion of ADA in the StakePool that is delegated by $D$   $\frac{D^{Stake}}{Pool^{Tot}}$
  $D^{Rewards}$             The ADA rewards that are received by $D$                          $R^{\textit{Deleg}} \times D^\%$

**The Rewards that are received by a specific Delegator, $D$.**
:::::

The rewards that are received by an individual delegator are calculated in exactly the same way as in the Incentivised TestNet. Each delegator receives rewards that are directly proportional to the stake that that delegator has placed in the StakePool. These are calculated from the net rewards to the StakePool after deducting the owner rewards.

### The Rewards that are received by each StakePool Owner for Epoch $E$

::::: {.figure latex-placement="h!"}
::: center
  **Parameter**        **Definition**                                                                                                                                                                                                                                                                **Calculated as**
  -------------------- ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- -------------------------------------------------------------
  $R^\textit{Owner}$   The Reward to the Owner(s).                                                                                                                                                                                                                                                   $R^{\textit{Net}} \times {\textit{Pool}}^{\textit{Margin}}$
  $O^\textit{Stake}$   The ADA that is pledged by Owner $O$                                                                                                                                                                                                                                          
  $O^\%$               The proportion of ADA in the StakePool that is pledged by $O$                                                                                                                                                                                                                 $\frac{O^{Stake}}{Pool^{Tot}}$
  $O^{Rewards}$        The ADA rewards that are received by $O$. This may be capped if the owner fraction is too large, as described in Section sec:penalties, or reduced to zero if any owner fails to honour their pledge.   $R^{\textit{Net}} \times O^\%$

**The Rewards that are received by each Owner, $O$.**
:::::

In the MainNet, each owner receives rewards that are proportional to the stake that they have pledged, calculated similarly to the delegator rewards. If one or more StakePool owners withdraw their pledge during the epoch, however, then no owner rewards will be received by any owner of that StakePool.

## The Rewards that are allocated to the Treasury for Epoch $E$

In the MainNet, all rewards that are not allocated to StakePools will accrue to the treasury. This will include some fraction of the monetary expansion $\textit{MER}_E$, plus any penalties. This will always be a positive value.

### StakePool Rewards Penalties

Any rewards that are not allocated to a StakePool will accrue to the Treasury instead. This can happen:

i)  because of poor *apparent performance*, $\textit{Pool}^{\textit{Perf}}$;

ii) because one or more owners of a StakePool have failed to honour their *pledge* (in which case **all** reward will accrue to the Treasury);

iii) because the StakePool as a whole has exceeded the target size as governed by the $N^{\textit{Pools}}$ and $z$ parameters;

iv) because the Owner(s)' stake has exceeded the target size as governed by the $N^{\textit{Pools}}$ and $z$ parameters.

Returning the rewards to the Treasury ensures that the ADA remains in circulation and can be re-allocated in future.

## Calculating Rewards in External Currencies
Rewards can be converted to other currencies using the current exchange rate, exactly as described in Section 2.2. Realising these funds will require the use of an external *exchange* service.

## Worked Example: Full Scheme

This example is taken from the internal calculator at <https://docs.google.com/spreadsheets/d/1m_CfNMdkxR_OrfRwThbU-6faxHUf7NdIhDLc6r-4lIM/edit#gid=1365573139>.

### Key Parameters

::: minipage
<!-- [Image from original LaTeX source] -->

<!-- [Image from original LaTeX source] -->

This diagram shows the key parameters and settings for the rewards system, including the initially circulating and reserve ADA. The monetary expansion rate is calculated as described above. The number of days per Epoch is set to 5, the influence factor to 0.1, the system performance to 99%, the average transaction fees to ***ADA 2,000*** and the expected rewards rate to 0.05. These parameters are used as part of the monetary expansion rate calculation.

### Circulation and Distribution

<!-- [Image from original LaTeX source] -->

The upper part of this diagram shows the ADA that is distributed for Epoch E, assuming the overall system performance of 99%, retained deposits of ***ADA 500*** and transaction fees of ***ADA 2,000***. The total distribution for the Epoch is ***ADA 56,051,291.02***. These are reduced by the Treasury Top Slice and the influence factor to give the rewards that are distributed to the pools of ***ADA 46,323,360.35***. The lower part of the diagram shows the ADA in circulation and the reserves at the start and end of the Epoch.

### StakePool Parameters

<!-- [Image from original LaTeX source] -->

This diagram shows the StakePool-specific parameters, including the total controlled ADA and the division by owner(s) and delegators. In the MainNet, 99.37% of the StakePool ADA is owned by delegators. The StakePool receives all of its optimal rewards, since it controls exactly the required percentage of stake (1.00%, corresponding to the limit set from the $N^{\textit{Pools}}$ parameter).

### Calculated Rewards

::: minipage
<!-- [Image from original LaTeX source] -->

<!-- [Image from original LaTeX source] -->

This diagram shows the corresponding rewards that accrue to the owner(s) and delegators, plus a calculation of the total income that is received by the owners. As before, we will assume that the average and actual gross rewards are the same, i.e. if the StakePool controls 1% of the total ADA in circulation, it will produce exactly 1% of the blocks, that it has 100% performance, and will therefore receive exactly 1% of the rewards. In total, the owners and delegators to this StakePool would receive a net reward that was equivalent to 8.33% per year (the "staking yield"), representing a 17% better return than with the simplified scheme. The final rows calculate the *non-myopic* rewards (i.e. long-term rewards that ensure a stable and well-functioning system). As described in [@delegation_design], these values will be used to guide stakeholder behaviour through a ranking system that will encourage convergence to the $N^{\textit{Pools}}$ best-performing pools. For this pool, which is *saturated*, the non-myopic rewards are identical to the *optimal rewards*. Rewards will be returned as described in Section 2.4. In the MainNet, when multiple owners are involved, this return could be through a multi-signature transaction [@shelley_multisig], according to an agreed formula.

### Delegator Rewards

::: minipage
<!-- [Image from original LaTeX source] -->

<!-- [Image from original LaTeX source] -->

This diagram shows the rewards that a stakeholder would receive over time if they delegated ***ADA 1,000,000*** to the sample pool under the assumptions used above. In total, this would represent 0.65% of the stake that is delegated to the incentivised TestNet pool, or 0.32% of the stake that is delegated to the MainNet pool. Overall, the staking yield would be 7.11% for the simplified scheme, or 8.33% for the full scheme, representing a return of ***ADA 70K***-***ADA 80K*** over a year.

## Summary of Differences between the Two Incentives Schemes
::::: {.figure latex-placement="h!"}
::: center
  **Value**                                            **Incentivised TestNet**                     **MainNet**
  ---------------------------------------------------- -------------------------------------------- ----------------------------------------------------------------------------------------------------------------------------------
  Treasury Top Slice Percentage                        Fixed at 10%                                 Initially set to 10% but can be changed in future by a community vote
  Monetary Expansion Rate per Year                     Fixed at 10%                                 Exponential decay from  10%
  Target Number of Stake Pools, $N^{\textit{Pools}}$   None.                                        $N^{\textit{Pools}}$ is expected to grow over time and may reach around 1000. It will initially be set low (probably 50 or 100).
  Transaction Fees                                     None                                         Included in the reward pot
  Registration Deposits                                None                                         Non-refundable parts included in the reward pot
  Influence Factor ($\textit{inf}$)                    None                                         Included in calculation, initially set to 0.1
  StakePool Performance                                Actual block creation considered             Directly affects rewards, any "penalty" accrues to the treasury
  Owner Rewards                                        Divided equally amongst multiple Owners      Owners can decide proportions using a smart contract
  ADA that affects rewards                             All ADA that is circulating in the TestNet   All ADA that is in circulation
  Stake pledged by owners                              Assumed to be fully pledged                  Affects rewards if not honoured
  Epoch duration ($E$)                                 Fixed to 1 day                               Set to 5 days initially (but community vote can change)
  Treasury Fraction ($T$)                              Fixed at 10%                                 All rewards that are not distributed to the StakePools

**Differences between the Incentivised TestNet and the MainNet**
:::::

# Summary of Differences in terminology etc. to [@delegation_design]
- SL-D1 only considers the full incentives calculation, not the simplified one, or how rewards are to be transferred to the MainNet.

- SL-D1 does not distinguish the StakePool Operator and Owner(s).

- SL-D1 does not use the terms "Control" or "Distribution".

- This document uses terminology that is intended to convey the purpose of specific symbols in SL-D1. The main differences are shown below.

  ::: center
    **SL-D1**      **This Document**
    -------------- -----------------------------------
    $a_0$          $\textit{inf}$
    $\eta$         $\textit{Perf}_E$
    $k$            $N^{\textit{Pools}}$
    $\bar{p}$      $\textit{Pool}^{\textit{Perf}}$
    $\rho$         $\textit{MER}$
    $s$            $\textit{Pool}^{\textit{Pledge}}$
    $s'$           $\textit{p}^{\%}$
    $\sigma$       $\textit{Pool}^{\textit{Perf}}$
    $\sigma'$      $\textit{s}^{\%}$
    $\tau$         $T$
    $T_{\infty}$   $\textit{Ada}^{Tot}$
    $z_0$          $z$
  :::

[^1]: This does not include the "performance factor".

[^2]: The cost is a fixed amount; the charges are calculated from the net rewards using the pre-set *margin*, $\textit{Pool}^{\textit{Margin}}$
