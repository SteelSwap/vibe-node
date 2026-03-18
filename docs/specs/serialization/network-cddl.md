# Common CDDL definitions
``` {style="cddl"}
```

# Historical protocol versions

## Node-to-node protocol

Previously supported versions of the *node-to-node protocol* are listed in table [2.1](#table:historical-node-to-node-protocol-versions).

::::: {#table:historical-node-to-node-protocol-versions .figure latex-placement="h"}
::: center
  **version**        **description**
  ------------------ -----------------------------------------------------------------------
  `NodeToNodeV_1`    initial version
  `NodeToNodeV_2`    block size hints
  `NodeToNodeV_3`    introduction of keep-alive mini-protocol
  `NodeToNodeV_4`    introduction of diffusion mode in handshake mini-protocol
  `NodeToNodeV_5`    
  `NodeToNodeV_6`    transaction submission version 2
  `NodeToNodeV_7`    new keep-alive, Alonzo ledger era
  `NodeToNodeV_8`    chain-sync & block-fetch pipelining
  `NodeToNodeV_9`    Babbage ledger era
  `NodeToNodeV_10`   Full duplex connections
  `NodeToNodeV_11`   Peer sharing willingness
  `NodeToNodeV_12`   No observable changes
  `NodeToNodeV_13`   Disabled peer sharing for buggy V11 & V12 and for InitiatorOnly nodes

**Node-to-node protocol versions**
:::::

## Node-to-client protocol

Previously supported versions of the *node-to-client protocol* are listed in table [2.2](#table:historical-node-to-client-protocol-versions).

::::: {#table:historical-node-to-client-protocol-versions .figure latex-placement="h"}
::: center
  **version**          **description**
  -------------------- ------------------------------------------------------
  `NodeToClientV_1`    initial version
  `NodeToClientV_2`    added local-query mini-protocol
  `NodeToClientV_3`    
  `NodeToClientV_4`    new queries added to local state query mini-protocol
  `NodeToClientV_5`    Allegra era
  `NodeToClientV_6`    Mary era
  `NodeToClientV_7`    new queries added to local state query mini-protocol
  `NodeToClientV_8`    codec changed for local state query mini-protocol
  `NodeToClientV_9`    Alonzo era
  `NodeToClientV_10`   GetChainBlock & GetChainPoint queries
  `NodeToClientV_11`   GetRewardInfoPools query
  `NodeToClientV_12`   Added LocalTxMonitor mini-protocol
  `NodeToClientV_13`   Babbage era
  `NodeToClientV_14`   GetPoolDistr, GetPoolState, GetSnapshots queries
  `NodeToClientV_15`   internal changes

**Node-to-client protocol versions**
:::::

[^1]: `duncan@well-typed.com`, `duncan.coutts@iohk.io`

[^2]: `neil.davies@pnsol.com`, `neil.davies@iohk.io`

[^3]: `marc.fontaine@iohk.io`

[^4]: `karl.knutsson-ext@cardanofoundation.org`

[^5]: `armando@well-typed.com`

[^6]: `marcin.szamotulski@iohk.io`

[^7]: `alex@well-typed.com`
