# Rewards
sec:rewards
\LedgerModule{Rewards}

This section defines how rewards for stake pools and their delegators
are calculated and paid out.

## Rewards Motivation
sec:rewards-motivation
In order to operate, any blockchain needs to attract parties that are
willing to spend computational and network resources
on processing transactions and producing new blocks.
These parties, called block producers,
are incentivized by monetary rewards.

Cardano is a proof-of-stake (PoS) blockchain:
through a random lottery,
one block producer is selected to produce one particular block.
The probability for being select depends on their stake of Ada,
that is the amount of Ada that they (and their delegators) own
relative to the total amount of Ada. (We will explain delegation below.)
After successful block production,
the block producer is eligible for a share of the rewards.

The rewards for block producers come from two sources:
during an initial period, rewards are paid out from the reserve,
which is an initial allocation of Ada created for this very purpose.
Over time, the reserve is depleted,
and rewards are sourced from transaction fees.

Rewards are paid out epoch by epoch.

Rewards are collective, but depend on performance:
after every epoch, a fraction of the available reserve
and the transaction fees accumulated during that epoch
are added together. This sum is paid out to the block producers
proportionally to how many blocks they have created each.
In order to avoid perverse incentives, block producers
do not receive individual rewards that depend on the content
of their blocks.

Not all people can or want to set up and administer a dedicated computer
that produces blocks. However, these people still own Ada,
and their stake is relevant for block production.
Specifically, these people have the option to delegate their stake
to a stake pool, which belongs to a block producer.
This stake counts towards the stake of the pool in the block production lottery.
In turn, the protocol distributes the rewards for produced blocks
to the stake pool owner and their delegators.
The owner receives a fixed fee (``cost'') and a share of the rewards (``margin'').
The remainder is distributed among delegators in proportion to their stake.
By design, delegation and ownership are separate
--- delegation counts towards the stake of the pool,
but delegators remain in full control of their Ada,
stake pools cannot spend delegated Ada.

Stake pools compete for delegators based on fees and performance.
In order to achieve stable blockchain operation,
the rewards are chosen such that they incentivize the system to evolve into a
large, but fixed number of stake pools that attract most of the stake.
For more details about the design and rationale of the rewards and delegation
system, see shelley-delegation-design.

## Precision of Arithmetic Operations
sec:precision-rewards
When computing rewards, all intermediate results are computed
using rational numbers, ℚ,
and converted to  using the floor function
at the very end of the computation.

Note for implementors:
Values in ℚ can have arbitrarily large nominators and denominators.
Please use an appropriate type that represents rational numbers
as fractions of unbounded nominators and denominators.
Types such as Double, Float,
BigDecimal (Java Platform),
or Fixed (fixed-precision arithmetic)
do *not* faithfully represent the rational numbers, and
are *not* suitable for computing rewards according to this specification!

We use the following arithmetic operations besides basic arithmetic:
itemize
  \item fromℕ: Interpret a natural number as a rational number.
  \item floor: Round a rational number to the next smaller integer.
  \item posPart:
    Convert an integer to a natural number by mapping all negative numbers to zero.
  \item ÷: Division of rational numbers.
  \item ÷₀: Division operator that returns zero when the denominator is zero.
  \item /: Division operator that maps integer arguments to a rational number.
  \item /₀: Like ÷₀, but with integer arguments.
itemize

## Rewards Distribution Calculation
sec:rewards-distribution-calculation
This section defines the amount of rewards that are paid out
to stake pools and their delegators.

fig:functions:maxPool defines the function maxPool
which gives the maximum reward a stake pool can receive in an epoch.
Relevant quantities are:
itemize
  \item rewardPot: Total rewards to be paid out after the epoch.
  \item stake: Relative stake of the pool.
  \item pledge: Relative stake that the pool owner has pledged themselves to the pool.
  \item z0: Relative stake of a fully saturated pool.
  \item nopt: Protocol parameter, planned number of block producers.
  \item a0: Protocol parameter that incentivizes higher pledges.
  \item rewardℚ: Pool rewards as a rational number.
  \item rewardℕ: Pool rewards after rounding to a natural number of lovelace.
itemize

figure*[ht]
AgdaMultiCode
```agda
maxPool : PParams → Coin → UnitInterval → UnitInterval → Coin
maxPool pparams rewardPot stake pledge = rewardℕ
  where
    a0      = ℚ.max 0 (pparams .PParams.a0)
    1+a0    = 1 + a0
    nopt    = ℕ.max 1 (pparams .PParams.nopt)
```
```agda
    z0       = 1 / nopt
    stake'   = ℚ.min (fromUnitInterval stake) z0
    pledge'  = ℚ.min (fromUnitInterval pledge) z0
```
```agda
    rewardℚ =
        ((fromℕ rewardPot) ÷ 1+a0)
        * (stake' + pledge' * a0 * (stake' - pledge' * (z0 - stake') ÷ z0) ÷ z0)
    rewardℕ = posPart (floor rewardℚ)
```
AgdaMultiCode
Function maxPool used for computing a Reward Update
fig:functions:maxPool
figure*

fig:functions:mkApparentPerformance defines
the function mkApparentPerformance
which computes the apparent performance of a stake pool.
Relevant quantities are:
itemize
  \item stake: Relative active stake of the pool.
  \item poolBlocks: Number of blocks that the pool added to the chain in the last epoch.
  \item totalBlocks: Total number of blocks added in the last epoch.
itemize

figure*[ht]
AgdaMultiCode
```agda
mkApparentPerformance : UnitInterval → ℕ → ℕ → ℚ
mkApparentPerformance stake poolBlocks totalBlocks = ratioBlocks ÷₀ stake'
  where
    stake' = fromUnitInterval stake
```
```agda
    ratioBlocks = (ℤ.+ poolBlocks) / (ℕ.max 1 totalBlocks)
```
AgdaMultiCode
Function mkApparentPerformance used for computing a Reward Update
fig:functions:mkApparentPerformance
figure*

fig:functions:rewardOwners-rewardMember defines
the functions rewardOwners and rewardMember.
Their purpose is to divide the reward for one pool
between pool owners and individual delegators
by taking into account a fixed pool cost, a relative pool margin,
and the stake of each member.
The rewards will be distributed as follows:
itemize
  \item rewardOwners:
    These funds will go to the rewardAccount
    specified in the pool registration certificate.
  \item rewardMember:
    These funds will go to the reward accounts of the individual delegators.
itemize
Relevant quantities for the functions are:
itemize
  \item rewards: Rewards paid out to this pool.
  \item pool: Pool parameters, such as cost and margin.
  \item ownerStake: Stake of the pool owners relative to the total amount of Ada.
  \item memberStake: Stake of the pool member relative to the total amount of Ada.
  \item stake: Stake of the whole pool relative to the total amount of Ada.
itemize

figure*[ht]
AgdaMultiCode
```agda
rewardOwners : Coin → PoolParams → UnitInterval → UnitInterval → Coin
rewardOwners rewards pool ownerStake stake = if rewards ≤ cost
  then rewards
  else cost + posPart (floor (
        (fromℕ rewards - fromℕ cost) * (margin + (1 - margin) * ratioStake)))
  where
    ratioStake   = fromUnitInterval ownerStake ÷₀ fromUnitInterval stake
    cost         = pool .PoolParams.cost
    margin       = fromUnitInterval (pool .PoolParams.margin)
```
AgdaMultiCode
AgdaMultiCode
```agda
rewardMember : Coin → PoolParams → UnitInterval → UnitInterval → Coin
rewardMember rewards pool memberStake stake = if rewards ≤ cost
  then 0
  else posPart (floor (
         (fromℕ rewards - fromℕ cost) * ((1 - margin) * ratioStake)))
  where
    ratioStake    = fromUnitInterval memberStake ÷₀ fromUnitInterval stake
    cost          = pool .PoolParams.cost
    margin        = fromUnitInterval (pool .PoolParams.margin)
```
AgdaMultiCode
Functions rewardOwners and rewardMember
fig:functions:rewardOwners-rewardMember
figure*

fig:functions:rewardOnePool defines
the function rewardOnePool
which calculates the rewards given out to each member of a given pool.
Relevant quantities are:
itemize
  \item rewardPot: Total rewards to be paid out for this epoch.
  \item n: Number of blocks produced by the pool in the last epoch.
  \item N: Expectation value of the number of blocks to be produced by the pool.
  \item stakeDistr: Distribution of stake,
    as mapping from Credential to .
  \item σ: Total relative stake controlled by the pool.
  \item σa: Total active relative stake controlled by the pool, used for selecting block producers.
  \item tot: Total amount of Ada in circulation, for computing the relative stake.
  \item mkRelativeStake: Compute stake relative to the total amount in circulation.
  \item ownerStake: Total amount of stake controlled by the stake pool operator and owners.
  \item maxP: Maximum rewards the pool can claim if the pledge is met,
    and zero otherwise.
  \item poolReward: Actual rewards to be paid out to this pool.
itemize

figure*[ht]
AgdaMultiCode
```agda
Stake = Credential ⇀ Coin

rewardOnePool : PParams → Coin → ℕ → ℕ → PoolParams
  → Stake → UnitInterval → UnitInterval → Coin → (Credential ⇀ Coin)
rewardOnePool pparams rewardPot n N pool stakeDistr σ σa tot = rewards
  where
    mkRelativeStake = λ coin → clamp (coin /₀ tot)
    owners = mapˢ KeyHashObj (pool .PoolParams.owners) 
    ownerStake = ∑[ c ← stakeDistr ∣ owners ] c
    pledge = pool .PoolParams.pledge
    maxP = if pledge ≤ ownerStake
      then maxPool pparams rewardPot σ (mkRelativeStake pledge)
      else 0
    apparentPerformance = mkApparentPerformance σa n N
    poolReward = posPart (floor (apparentPerformance * fromℕ maxP))
    memberRewards =
      mapValues (λ coin → rewardMember poolReward pool (mkRelativeStake coin) σ)
        (stakeDistr ∣ owners ᶜ)
    ownersRewards  =
      ❴ pool .PoolParams.rewardAccount
      , rewardOwners poolReward pool (mkRelativeStake ownerStake) σ ❵ᵐ
    rewards = memberRewards ∪⁺ ownersRewards
```
AgdaMultiCode
Function rewardOnePool used for computing a Reward Update
fig:functions:rewardOnePool
figure*

fig:functions:poolStake defines
the function poolStake
which filters the stake distribution to one stake pool.
Relevant quantities are:
itemize
  \item hk: KeyHash of the stake pool to be filtered by.
    \item delegs:
      Mapping from Credentials to stake pool that they delegate to.
  \item stake: Distribution of stake for all Credentials.
itemize

figure*[ht]
AgdaMultiCode
```agda
Delegations = Credential ⇀ KeyHash

poolStake  : KeyHash → Delegations → Stake → Stake
poolStake hk delegs stake = stake ∣ dom (delegs ∣^ ❴ hk ❵)
```
AgdaMultiCode
Function poolStake
fig:functions:poolStake
figure*

fig:functions:reward defines
the function reward
which applies rewardOnePool to each registered stake pool.
Relevant quantities are:
itemize
  \item uncurryᵐ: Helper function to rearrange a nested mapping.
  \item blocks: Number of blocks produced by pools in the last epoch,
    as a mapping from pool KeyHash to number.
  \item poolParams: Parameters of all known stake pools.
  \item stake: Distribution of stake,
    as mapping from Credential to .
    \item delegs:
      Mapping from Credentials to stake pool that they delegate to.
  \item total: Total stake $=$ amount of Ada in circulation, for computing the relative stake.
  \item active: Active stake $=$ amount of Ada that was used for selecting block producers.
  \item Σ\_/total: Sum of stake divided by total stake.
  \item Σ\_/active: Sum of stake divided by active stake.
  \item N: Total number of blocks produced in the last epoch.
  \item pdata: Data needed to compute rewards for each pool.
itemize

figure*[ht]
AgdaMultiCode
```agda
BlocksMade = KeyHash ⇀ ℕ

uncurryᵐ :
```
```agda
  A ⇀ (B ⇀ C) → (A × B) ⇀ C
```
```agda

reward : PParams → BlocksMade → Coin → (KeyHash ⇀ PoolParams)
  → Stake → Delegations → Coin → (Credential ⇀ Coin)
reward pp blocks rewardPot poolParams stake delegs total = rewards
  where
    active = ∑[ c ← stake ] c
    Σ_/total = λ st → clamp ((∑[ c ← st ] c) /₀ total)
    Σ_/active = λ st → clamp ((∑[ c ← st ] c) /₀ active)
    N = ∑[ m ← blocks ] m
    mkPoolData = λ hk p →
      map (λ n → (n , p , poolStake hk delegs stake)) (lookupᵐ? blocks hk)
    pdata = mapMaybeWithKeyᵐ mkPoolData poolParams

    results  : (KeyHash × Credential) ⇀ Coin
    results = uncurryᵐ (mapValues (λ (n , p , s)
      → rewardOnePool pp rewardPot n N p s (Σ s /total) (Σ s /active) total)
      pdata)
    rewards  = aggregateBy
      (mapˢ (λ (kh , cred) → (kh , cred) , cred) (dom results))
      results
```
AgdaMultiCode
Function reward used for computing a Reward Update
fig:functions:reward
figure*

## Reward Update
sec:reward-update
TODO: This section defines the RewardUpdate type,
which records the net flow of Ada due to paying out rewards
after an epoch.
NOTE: The function createRUpd calculates the
RewardUpdate,
but requires the definition EpochState,
so we have to defer its definition to a later section.

## Stake Distribution Snapshots
sec:stake-dstribution-snapshots-
TODO: This section defines the SNAP transition rule
for the stake distribution snapshots.
