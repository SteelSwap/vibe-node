# Protocol Parameters
sec:protocol-parameters
\LedgerModule{PParams}, in which we define the adjustable protocol
parameters of the Cardano ledger.  

Protocol parameters are used in block validation and
can affect various features of the system, such as minimum fees, maximum and minimum
sizes of certain components, and more.


NoConway
The Acnt record has two fields, treasury and reserves, so
the acnt field in NewEpochState keeps track of the total assets that
remain in treasury and reserves.

figure*[ht]
AgdaMultiCode
```agda
record Acnt : Type where
```
```agda
  field
    treasury reserves : Coin

record Hastreasury {a} (A : Type a) : Type a where
  field treasuryOf : A → Coin
open Hastreasury ⦃...⦄ public

ProtVer : Type
ProtVer = ℕ × ℕ

instance
  Show-ProtVer : Show ProtVer
  Show-ProtVer = Show-×

data pvCanFollow : ProtVer → ProtVer → Type where
  canFollowMajor : pvCanFollow (m , n) (m + 1 , 0)
  canFollowMinor : pvCanFollow (m , n) (m , n + 1)
```
AgdaMultiCode
Definitions related to protocol parameters
fig:protocol-parameter-defs
figure*
NoConway

figure*[ht]
```agda
data PParamGroup : Type where
  NetworkGroup     : PParamGroup
  EconomicGroup    : PParamGroup
  TechnicalGroup   : PParamGroup
  GovernanceGroup  : PParamGroup
  SecurityGroup    : PParamGroup
```
Protocol parameter group definition
fig:protocol-parameter-groups
figure*

figure*[ht]
```agda
record DrepThresholds : Type where
  field
    P1 P2a P2b P3 P4 P5a P5b P5c P5d P6 : ℚ

record PoolThresholds : Type where
  field
    Q1 Q2a Q2b Q4 Q5 : ℚ
```
Protocol parameter threshold definitions
fig:protocol-parameter-thresholds
figure*

figure*[ht]
AgdaMultiCode
```agda
record PParams : Type where
  field
```
*Network group*
```agda
        maxBlockSize                  : ℕ
        maxTxSize                     : ℕ
        maxHeaderSize                 : ℕ
        maxTxExUnits                  : ExUnits
        maxBlockExUnits               : ExUnits
        maxValSize                    : ℕ
        maxCollateralInputs           : ℕ
```
*Economic group*
```agda
        a                             : ℕ
        b                             : ℕ
        keyDeposit                    : Coin
        poolDeposit                   : Coin
        monetaryExpansion             : UnitInterval -- formerly: rho
        treasuryCut                   : UnitInterval -- formerly: tau
        coinsPerUTxOByte              : Coin
        prices                        : Prices
        minFeeRefScriptCoinsPerByte   : ℚ
        maxRefScriptSizePerTx         : ℕ
        maxRefScriptSizePerBlock      : ℕ
        refScriptCostStride           : ℕ
        refScriptCostMultiplier       : ℚ
```
*Technical group*
```agda
        Emax                          : Epoch
        nopt                          : ℕ
        a0                            : ℚ
        collateralPercentage          : ℕ
```
```agda
        costmdls                      : CostModel
```
*Governance group*
```agda
        poolThresholds                : PoolThresholds
        drepThresholds                : DrepThresholds
        ccMinSize                     : ℕ
        ccMaxTermLength               : ℕ
        govActionLifetime             : ℕ
        govActionDeposit              : Coin
        drepDeposit                   : Coin
        drepActivity                  : Epoch
```
AgdaMultiCode
*Security group*

   
 a{} b{}
  
Protocol parameter definitions
fig:protocol-parameter-declarations
figure*
figure*
AgdaMultiCode
```agda
positivePParams : PParams → List ℕ
positivePParams pp =  ( maxBlockSize ∷ maxTxSize ∷ maxHeaderSize
                      ∷ maxValSize ∷ refScriptCostStride ∷ coinsPerUTxOByte
                      ∷ poolDeposit ∷ collateralPercentage ∷ ccMaxTermLength
                      ∷ govActionLifetime ∷ govActionDeposit ∷ drepDeposit ∷ [] )
```
```agda

paramsWellFormed : PParams → Type
paramsWellFormed pp = 0 ∉ fromList (positivePParams pp)
```
AgdaMultiCode
Protocol parameter well-formedness
fig:protocol-parameter-well-formedness
figure*
% Retiring ProtVer's documentation since ProtVer is retired.
%  represents the protocol version used in the Cardano ledger.
% It is a pair of natural numbers, representing the major and minor version,
% respectively.

 contains parameters used in the Cardano ledger, which we group according
to the general purpose that each parameter serves.
itemize
  \item : parameters related to the network settings;
  \item : parameters related to the economic aspects of the ledger;
  \item : parameters related to technical settings;
  \item : parameters related to governance settings;
  \item : parameters that can impact the security of the system.
itemize
The purpose of these groups is to determine voting thresholds for
proposals aiming to change parameters.  Given a proposal to change a certain set of
parameters, we look at which groups those parameters fall into and from this we
determine the voting threshold for that proposal.  (The voting threshold
calculation is described in detail in sec:ratification-requirements; in
particular, the definition of the  function appears in
fig:ratification-requirements.)

The first four groups have the property that every protocol parameter
is associated to precisely one of these groups.  The  is
special: a protocol parameter may or may not be in the .
So, each protocol parameter belongs to at least one and at most two groups.
Note that in 1694 there is no , but there is the
concept of security-relevant protocol parameters (see cip1694).
The difference between these notions is only social, so we implement
security-relevant protocol parameters as a group.

The new protocol parameters are declared in fig:protocol-parameter-declarations
and denote the following concepts:
itemize
  \item : governance thresholds for ; these are rational
    numbers named , , , , , ,
    , , , and ;
  \item \poolThresholds: pool-related governance thresholds; these are rational
    numbers named , , ,  and ;
  \item : minimum constitutional committee size;
  \item : maximum term limit (in epochs) of constitutional
    committee members;
  \item : governance action expiration;
  \item : governance action deposit;
  \item :  deposit amount;
  \item :  activity period;
  \item : the minimum active voting threshold.
itemize
fig:protocol-parameter-declarations also defines the
function  which performs some sanity checks on protocol
parameters.
fig:pp-update-type defines types and functions to update
parameters. These consist of an abstract type UpdateT and
two functions applyUpdate and updateGroups.
The type UpdateT is to be instantiated by a type that
%
itemize
  \item can be used to update parameters, via the
    function applyUpdate
  \item can be queried about what parameter groups it updates, via the
    function updateGroups
itemize
%
An element of the type UpdateT is well formed if it
updates at least one group and applying the update preserves
well-formedness.



figure*[ht]
AgdaMultiCode
*Abstract types \& functions*
```agda
    UpdateT : Type
    applyUpdate : PParams → UpdateT → PParams
    updateGroups : UpdateT → ℙ PParamGroup

```
*Well-formedness condition*
```agda

  ppdWellFormed : UpdateT → Type
  ppdWellFormed u = updateGroups u ≢ ∅
    × ∀ pp → paramsWellFormed pp → paramsWellFormed (applyUpdate pp u)
```
AgdaMultiCode
Abstract type for parameter updates
fig:pp-update-type
figure*
