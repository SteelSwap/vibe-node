# Properties of the Goguen Ledger
This section collects properties that the ledger described previously is expected to satisfy.

- Any token with the $\mathsf{PolicyID}$ of Ada is an Ada token, i.e. it also has the $\mathsf{AssetID}$ of Ada.

- The general accounting property holds with any transaction, whether it is fully processed or just paying fees. In particular, this implies that the total amount of Ada in the system is constant.

- If a transaction is accepted and marked as paying fees only (i.e. $\mathsf{txvaltag}\, tx \in \mathsf{Yes}$), then the only change to the ledger when processing the transaction is that the inputs marked for paying fees are moved to the fee pot.

- If a Shelley transaction is accepted, it is fully processed.

- If a transaction extends the UTxO, all its scripts validate, and if it has a script that does not validate, it cannot extend the UTxO.

- A valid transaction that does not forge tokens satisfies the accounting property of the Shelley ledger where the type $\mathsf{Coin}$ is replaced by $\mathsf{Value}$.
