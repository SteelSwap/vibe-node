# Gap Analysis

## The Spec Is the Ideal. The Code Is the Reality. The Gap Is the Delta.

Cardano has formal specifications — mathematical descriptions of how the system should work. The Haskell node is the implementation — how it actually works. These don't always agree.

This section documents every divergence we discover, published like errata in a scientific publication. Where the spec says one thing and the Haskell node does another, we record it: what, where, why it matters, and how it affects our implementation.

## Why This Matters

1. **Correctness** — If we implement the spec but the Haskell node deviates, our node will disagree with the network. We need to follow the Haskell node (it's the oracle), but we need to know where we're deviating from the spec to do it.
2. **Community value** — The Cardano community benefits from a clear catalog of where reality diverges from the published specifications.
3. **Spec improvement** — Documented gaps can feed back into the formal specification process, making the specs more accurate over time.

## This Is Not a Phase

Gap analysis is **not** a discrete phase of development. It is a discipline woven into every implementation step. Every time we implement a protocol rule, a ledger validation, or a consensus mechanism, we:

1. Read the spec (via the Search MCP)
2. Implement against the spec
3. Test against the Haskell node
4. Document any divergence we observe

This approach breaks the analysis into concrete chunks tied to real implementation work, making it less error-prone than a bulk analysis pass. It also keeps the team constantly aware that gaps may exist.

## Entry Format

Each gap entry follows this structure:

```markdown
## [Subsystem] — [Brief description of divergence]

**Spec reference:** [Document, section, page/equation number]
**Era:** [Which era this applies to]
**Spec says:** [What the spec defines]
**Haskell does:** [What the Haskell node actually implements]
**Delta:** [The specific difference]
**Implications:** [How this affects our implementation]
**Discovered during:** [Which phase/task uncovered this]
```

## Example (Placeholder)

!!! note "No Gaps Documented Yet"
    Gap analysis entries will appear here as we implement each subsystem starting in Phase 1. Each entry will be tied to a specific implementation task and linked to the relevant spec sections.

The following is a hypothetical example of what an entry looks like:

---

### UTxO Validation — Minimum Ada requirement calculation

**Spec reference:** Shelley Ledger Spec, Section 4.3.2, Equation (7)
**Era:** Babbage
**Spec says:** Minimum Ada is calculated as `max(minUTxOValue, utxoEntrySizeWithoutVal + 160 + numAssets * 28) * coinsPerUTxOByte`
**Haskell does:** Uses a slightly different formula that accounts for datum hash size in the overhead calculation, adding an extra 32 bytes when a datum hash is present
**Delta:** The spec formula doesn't account for the datum hash overhead; the implementation adds it
**Implications:** Our implementation must follow the Haskell behavior (add datum hash overhead) to agree on UTxO validation. The spec should be updated to reflect this.
**Discovered during:** Phase 3, M3.4 — UTxO validation rules

---

*This is a hypothetical example. Real entries will appear as development progresses.*
