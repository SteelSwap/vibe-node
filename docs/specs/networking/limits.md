# Time and size limits

## Timeouts
There are several layers, where timeouts play a crucial way in making the system secure. At the lowest layer is a mux timeout which we explain next. After establishing a connection (either a Node-to-Node or Node-to-Client one), the handshake is using a bearer with `10s` timeout on receiving each mux SDU. Note, this is a timeout which bounds how long it takes to receive a single mux SDU, e.g. from receiving the leading edge of the mux SDU until receiving its trailing edge, not how long we wait to receive a next SDU. Handshake protocol is then imposing its own timeouts, see table \[table:handshake-timeouts\].

After handshake negotiation is done, mux is using a bearer with `30s` timeout on receiving a mux SDU (the previous note applies as well). Once a mini-protocol is in execution it must enforce it's own set of timeouts which we included in the previous chapter and for convenience we referenced them in the table 1.1 below.


::: center
  --------------- ----------------------------------------------------------------------------------------------------------------------------------------
  Handshake       table \[table:handshake-timeouts\]
  Chain-Sync      table \[table:chain-sync-timeouts\]
  Block-Fetch     table \[table:block-fetch-timeouts\]
  Tx-Submission   table \[table:tx-submission-timeouts\]
  Keep-Alive      table \[table:keep-alive-timeouts\]
  Peer-Share      table \[table:peer-share-timeouts\]
  --------------- ----------------------------------------------------------------------------------------------------------------------------------------

**Node-To-Node mini-protocol timeouts**

On the inbound side of the Node-to-Node protocol, we also include a `5s` idleness timeout. It starts either when a connection is accepted or when all responder mini-protocols terminated. If this timeout expires, without receiving any message from a remote end, the connection must be closed unless it is a duplex connection which is used by the outbound side.

Once all outbound and inbound mini-protocols have terminated and the idleness timeout expired, the connection is reset and put on a `60s` timeout. See section \[sec:connection-close\] why this timeout is required.

## Space limits

All per mini-protocol size limits are referenced in table 1.2:


::: center
  --------------- -------------------------------------------------------------------------------------------------------------------------------------------------
  Handshake       table \[table:handshake-size-limits\]
  Chain-Sync      table \[table:chain-sync-size-limits\]
  Block-Fetch     table \[table:block-fetch-size-limits\]
  Tx-Submission   table \[table:tx-submission-size-limits\]
  Keep-Alive      table \[table:keep-alive-size-limits\]
  Peer-Share      table \[table:peer-share-size-limits\]
  --------------- -------------------------------------------------------------------------------------------------------------------------------------------------

**Node-To-Node mini-protocol size limits**
