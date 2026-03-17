## UTxO
sec:utxo-properties


Here we state the fact that the UTxO relation is computable.

figure*[h]
```agda
UTXO-step : UTxOEnv → UTxOState → Tx → ComputationResult String UTxOState
UTXO-step = compute ⦃ Computational-UTXO ⦄

UTXO-step-computes-UTXO  :  UTXO-step Γ utxoState tx ≡ success utxoState'
                         ⇔  Γ ⊢ utxoState ⇀⦇ tx ,UTXO⦈ utxoState'
UTXO-step-computes-UTXO = ≡-success⇔STS ⦃ Computational-UTXO ⦄
```
Computing the UTXO transition system
figure*


property[**General Minimum Spending Condition**]~\\

property
