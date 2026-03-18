# Fee Calculation
sec:fees
\mathsf{LedgerModule}{Fees}, where we define the functions used to compute the
fees associated with reference scripts.

The function ~(fig:scriptsCost) calculates the fee for reference scripts in a
transaction.  It takes as input the total size of the reference scripts in
bytes---which can be calculated using
refScriptsSize~(fig:functions:utxo-conway)---and uses a
function (scriptsCostAux) that is piece-wise linear in the size,
where the linear constant multiple grows with each refScriptCostStride
bytes.
%
In addition,  depends on the following constants (which
are bundled with the protocol parameters; see
fig:protocol-parameter-declarations):
%
itemize
  \item refScriptCostMultiplier, a rational number, the
   growth factor or step multiplier that determines how much the price
   per byte increases after each increment;
  \item refScriptCostStride, an integer, the size in bytes at which
   the price per byte grows linearly;
  \item minFeeRefScriptCoinsPerByte, a rational number,
   the base fee or initial price per byte.
itemize

For background on this particular choice of fee calculation, see adr9.


figure
AgdaMultiCode
```agda
scriptsCost : (pp : PParams) → ℕ → Coin
scriptsCost pp scriptSize
```
```agda
  = scriptsCostAux 0ℚ minFeeRefScriptCoinsPerByte scriptSize
```
```agda
    scriptsCostAux : ℚ        -- accumulator
                   → ℚ        -- current tier price
                   → (n : ℕ)  -- remaining script size
```
```agda
                   → Coin
    scriptsCostAux acl curTierPrice n
```
```agda
        = case  n ≤? refScriptCostStride of
```
```agda
                (yes _)  → ∣ floor (acl + (fromℕ n * curTierPrice)) ∣
                (no  p)  → scriptsCostAux (acl + (fromℕ refScriptCostStride * curTierPrice))
                                          (refScriptCostMultiplier * curTierPrice)
                                          (n - refScriptCostStride)
```
AgdaMultiCode
Calculation of fees for reference scripts
fig:scriptsCost
figure
