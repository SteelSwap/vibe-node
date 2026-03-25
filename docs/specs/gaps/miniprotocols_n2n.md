# Miniprotocols (N2N) — Critical Gap Analysis

**4 critical gaps** where the spec and Haskell diverge in consensus-affecting ways.
Each gap must be matched to Haskell behavior exactly.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

---

## 1. 8d786236

**Era:** multi-era

**Spec says:** The consumer sends RequestNext and the producer responds with exactly one of three outcomes: RollForward (with header and tip), RollBackward (with point and tip), or AwaitReply (indicating the consumer is at the tip). After AwaitReply, the producer eventually sends either RollForward or RollBackward.

**Haskell does:** The implementation correctly handles all three responses. However, after MsgAwaitReply, it runs the stAwait callback as a side-effect and then enters a second Await state that only accepts MsgRollForward or MsgRollBackward (not another MsgAwaitReply). This means the protocol enforces that after AwaitReply, the next message must be either RollForward or RollBackward — AwaitReply cannot be repeated 

**Delta:** The two-phase await handling after MsgAwaitReply is an implementation detail not explicitly spelled out in the high-level spec description but is consistent with the typed protocol state machine. After AwaitReply, the server transitions to StNext (not StIdle), so only RollForward/RollBackward are valid next messages. A Python implementation must replicate this two-phase state transition.

**Implications:** Python implementation must model the state machine such that after receiving AwaitReply, the client enters a restricted state where only RollForward or RollBackward are accepted (not another AwaitReply or RequestNext). The stAwait callback must be invoked as a side-effect before waiting for the follow-up response.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 2. 993e2631

**Era:** multi-era

**Spec says:** The producer replies with a message containing the next block AND the head-point of the producer's chain, and advances the read-pointer to the next block. The consumer-driven request-response pattern continues until the read-pointer reaches the end of the producer's chain.

**Haskell does:** The client implementation receives `header` and `_pHead` in `recvMsgRollForward` but ignores the producer's head-point (`_pHead` is unused). It also checks a `controlMessageSTM` after each block to decide whether to terminate or continue, which is an additional termination mechanism not described in the spec. The `addBlock` function uses `shiftAnchoredFragment 50` which caps the candidate chain fr

**Delta:** 1) The producer head-point delivered with each RollForward message is discarded by the consumer implementation, so the consumer never knows how far behind it is. 2) Termination is driven by an external control message STM rather than by the read-pointer reaching the chain head. 3) The candidate chain fragment is artificially capped at 50 blocks via shiftAnchoredFragment. 4) Rollback failure is unhandled (partial pattern match).

**Implications:** Python implementation should: (1) make use of the producer head-point from RollForward messages (e.g., for progress tracking or deciding when steady-state is reached); (2) implement the spec's termination condition (read-pointer reaches chain head) as the primary loop exit, with external termination as an addition; (3) not silently cap chain fragment length unless explicitly designed; (4) handle rollback failure gracefully rather than crashing.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 3. f2b0cd39

**Era:** multi-era

**Spec says:** The Chain-Sync mini-protocol timeouts are: 3673s for idle state, 10s for intersect state, random between 601s and 911s for MustReply state, and 10s for CanAwait state. If a timeout is violated, the connection SHOULD be torn down.

**Haskell does:** The implementation differs from the spec in several ways: (1) The idle timeout is parameterized via ChainSyncIdleTimeout and can be Nothing (disabled), not hardcoded to 3673s. (2) The MustReply random timeout range is 135-269s (based on minChainSyncTimeout/maxChainSyncTimeout) for non-trustable peers, not 601-911s as the spec states. For trustable peers, the MustReply timeout is completely disable

**Delta:** The MustReply random timeout range in the implementation (135-269s) does not match the spec's stated range (601-911s). The spec range may refer to a different version or different parameters. Additionally, the idle timeout is configurable rather than fixed at 3673s, and trustable peers bypass the MustReply timeout entirely (not mentioned in spec).

**Implications:** Python implementation must decide which timeout range to use. The spec says 601-911s but the actual Haskell code uses 135-269s. The Python implementation should match the Haskell code (135-269s) for interoperability, but document the spec discrepancy. Must also handle the trustable/non-trustable peer distinction and the configurable idle timeout.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

## 4. fb165bf3

**Era:** multi-era

**Spec says:** Once a mini-protocol is in execution, it must enforce its own set of timeouts. Each mini-protocol (Handshake, Chain-Sync, Block-Fetch, Tx-Submission, Keep-Alive, Peer-Share) has dedicated timeout values specified in a table.

**Haskell does:** The ChainSync timeout implementation uses a sophisticated state-dependent timeout mechanism: (1) Idle state uses a configurable ChainSyncIdleTimeout or None; (2) Intersect and CanAwait states use shortWait; (3) MustReply state distinguishes between trustable peers (no timeout) and non-trustable peers (random timeout uniformly drawn from [135s, 269s] corresponding to 99.9%-99.9999% empty slot strea

**Delta:** The spec describes a simple per-protocol timeout table, but the Haskell implementation has state-dependent, trust-dependent, and randomized timeouts for ChainSync. The MustReply timeout for non-trustable peers is randomly chosen from [minChainSyncTimeout, maxChainSyncTimeout] (135-269 seconds) using a StdGen, while trustable peers get no timeout at all. This nuanced behavior is not captured by a simple timeout table.

**Implications:** Python implementation must: (1) implement state-dependent timeout logic per ChainSync state, (2) handle the trustable vs non-trustable peer distinction where trustable peers have no MustReply timeout, (3) implement randomized timeout selection in the range [135, 269] seconds for non-trustable MustReply state, (4) use shortWait for Intersect and CanAwait states, (5) support configurable idle timeout with fallback to None, (6) carry random state (StdGen equivalent) through timeout computations.

**Our status:** TODO

**Discovered during:** Phase 1 pipeline + M6.10 audit

---

