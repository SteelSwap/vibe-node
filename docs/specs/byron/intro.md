# Introduction {#sec:introduction}

This specification models the *conditions* that the different parts of a transaction have to fulfill so that they can extend a ledger, which is represented here as a list of transactions. In particular, we model the following aspects:

Preservation of value

:   relationship between the total value of input and outputs in a new transaction, and the unspent outputs.

Witnesses

:   authentication of parts of the transaction data by means of cryptographic entities (such as signatures and private keys) contained in these transactions.

Delegation

:   validity of delegation certificates, which delegate block-signing rights.

Update validation

:   voting mechanism which captures the identification of the voters, and the participants that can post update proposals.

The following aspects will not be modeled (since they are not part of the Byron release):

Stake

:   staking rights associated to an addresses.
