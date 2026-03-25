# Miniprotocols (N2C) — Critical Gap Analysis

**2 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. abdee4b4

**Era:** multi-era

**Spec says:** The Local Tx-Monitor mini-protocol state machine has states with alternating agency between Client and Server. The spec lists states: idle, acquired, and busy (after acquire, next-tx, has-tx, get-sizes, or get-measures).

**Haskell does:** The Haskell ServerStAcquired type includes a recvMsgGetMeasures field corresponding to a GetMeasures busy state, and the busy state is parameterized by request type (NextTx, HasTx, GetSizes, GetMeasures). The recvMsgAwaitAcquire transitions to ServerStAcquiring (not ServerStBusy), indicating Acquiring is a distinct state from the generic Busy states.

**Delta:** The spec description mentions 'get-measures' as one of the request types but the Haskell implementation reveals finer structure: Acquiring is a separate state type (ServerStAcquiring) distinct from the parameterized ServerStBusy type. The Python implementation must model both ServerStAcquiring and ServerStBusy as distinct state constructors, not collapse them. Also, GetMeasures is a valid request type that must be supported alongside GetSizes.

**Implications:** The Python implementation must ensure: (1) GetMeasures is supported as a distinct request type in the Acquired state, (2) the Acquiring state (from MsgAcquire/MsgAwaitAcquire) is modeled separately from the Busy states (from NextTx/HasTx/GetSizes/GetMeasures), and (3) MsgAwaitAcquire is valid from the Acquired state (not just Idle).

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. c15dc484

**Era:** multi-era

**Spec says:** The Local Transaction Monitor mini-protocol includes messages: MsgGetSizes → MsgReplyGetSizes (Word32, Word32, Word32) and MsgGetMeasures → MsgReplyGetMeasures (Word32, Map Text (Integer, Integer)). These are two distinct query/response pairs for mempool metadata.

**Haskell does:** The Haskell implementation defines a state machine with states StIdle, StAcquiring, StAcquired, StBusy (parameterized by StBusyKind), and StDone. The provided code snippet only shows the state type definitions, not the message types. Based on the ouroboros-network codebase, the implemented messages include MsgGetSizes/MsgReplyGetSizes but MsgGetMeasures/MsgReplyGetMeasures may not yet be implement

**Delta:** The spec describes MsgGetMeasures/MsgReplyGetMeasures (Word32, Map Text (Integer, Integer)) which may not be present in the current Haskell implementation. The Haskell code shown only provides state machine types without the full message definitions, making it impossible to confirm full coverage. The MsgGetMeasures message appears to be a spec extension not yet reflected in the implementation.

**Implications:** The Python implementation should implement all messages from the spec including MsgGetMeasures/MsgReplyGetMeasures. However, if the Haskell node does not support MsgGetMeasures, attempting to send it will likely cause a protocol error. The Python implementation should be prepared to handle both cases - nodes that support MsgGetMeasures and those that don't. Version negotiation may determine which messages are available.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

