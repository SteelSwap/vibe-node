# Time and size limits

## Timeouts {#section:timeouts}

There are several layers, where timeouts play a crucial way in making the system secure. At the lowest layer is a mux timeout which we explain next. After establishing a connection (either a Node-to-Node or Node-to-Client one), the handshake is using a bearer with `10s` timeout on receiving each mux SDU. Note, this is a timeout which bounds how long it takes to receive a single mux SDU, e.g. from receiving the leading edge of the mux SDU until receiving its trailing edge, not how long we wait to receive a next SDU. Handshake protocol is then imposing its own timeouts, see table [\[table:handshake-timeouts\]](#table:handshake-timeouts){reference-type="ref" reference="table:handshake-timeouts"}.

After handshake negotiation is done, mux is using a bearer with `30s` timeout on receiving a mux SDU (the previous note applies as well). Once a mini-protocol is in execution it must enforce it's own set of timeouts which we included in the previous chapter and for convenience we referenced them in the table [1.1](#Node-To-Node-timeouts){reference-type="ref" reference="Node-To-Node-timeouts"} below.

::::: {#Node-To-Node-timeouts .figure latex-placement="ht"}
::: center
  --------------- ----------------------------------------------------------------------------------------------------------------------------------------
  Handshake       table [\[table:handshake-timeouts\]](#table:handshake-timeouts){reference-type="ref" reference="table:handshake-timeouts"}
  Chain-Sync      table [\[table:chain-sync-timeouts\]](#table:chain-sync-timeouts){reference-type="ref" reference="table:chain-sync-timeouts"}
  Block-Fetch     table [\[table:block-fetch-timeouts\]](#table:block-fetch-timeouts){reference-type="ref" reference="table:block-fetch-timeouts"}
  Tx-Submission   table [\[table:tx-submission-timeouts\]](#table:tx-submission-timeouts){reference-type="ref" reference="table:tx-submission-timeouts"}
  Keep-Alive      table [\[table:keep-alive-timeouts\]](#table:keep-alive-timeouts){reference-type="ref" reference="table:keep-alive-timeouts"}
  Peer-Share      table [\[table:peer-share-timeouts\]](#table:peer-share-timeouts){reference-type="ref" reference="table:peer-share-timeouts"}
  --------------- ----------------------------------------------------------------------------------------------------------------------------------------
:::

::: caption
Node-To-Node mini-protocol timeouts
:::
:::::

On the inbound side of the Node-to-Node protocol, we also include a `5s` idleness timeout. It starts either when a connection is accepted or when all responder mini-protocols terminated. If this timeout expires, without receiving any message from a remote end, the connection must be closed unless it is a duplex connection which is used by the outbound side.

Once all outbound and inbound mini-protocols have terminated and the idleness timeout expired, the connection is reset and put on a `60s` timeout. See section [\[sec:connection-close\]](#sec:connection-close){reference-type="ref" reference="sec:connection-close"} why this timeout is required.

## Space limits

All per mini-protocol size limits are referenced in table [1.2](#Node-To-Node-size-limits){reference-type="ref" reference="Node-To-Node-size-limits"}:

::::: {#Node-To-Node-size-limits .figure latex-placement="ht"}
::: center
  --------------- -------------------------------------------------------------------------------------------------------------------------------------------------
  Handshake       table [\[table:handshake-size-limits\]](#table:handshake-size-limits){reference-type="ref" reference="table:handshake-size-limits"}
  Chain-Sync      table [\[table:chain-sync-size-limits\]](#table:chain-sync-size-limits){reference-type="ref" reference="table:chain-sync-size-limits"}
  Block-Fetch     table [\[table:block-fetch-size-limits\]](#table:block-fetch-size-limits){reference-type="ref" reference="table:block-fetch-size-limits"}
  Tx-Submission   table [\[table:tx-submission-size-limits\]](#table:tx-submission-size-limits){reference-type="ref" reference="table:tx-submission-size-limits"}
  Keep-Alive      table [\[table:keep-alive-size-limits\]](#table:keep-alive-size-limits){reference-type="ref" reference="table:keep-alive-size-limits"}
  Peer-Share      table [\[table:peer-share-size-limits\]](#table:peer-share-size-limits){reference-type="ref" reference="table:peer-share-size-limits"}
  --------------- -------------------------------------------------------------------------------------------------------------------------------------------------
:::

::: caption
Node-To-Node mini-protocol size limits
:::
:::::
