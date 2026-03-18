# Chain sync client
## Header validation
Discuss the fact that we validate headers (maybe a forward reference to the genesis chapter, where this becomes critical).

Discuss that this means we need efficient access to the $k$ most recent ledger states (we refer to this section for that).

## Forecasting requirements
Discuss that forecasting must have sufficient range to validate a chain longer than our own chain, so that we can meaningfully apply chain selection.

NOTE: Currently [\[low-density\]](#low-density) contains such a discussion.

## Trimming
## Interface to the block fetch logic
We should discuss here the (very subtle!) reasoning about how we establish the precondition that allows us to compare candidates ([\[chainsel:fragments:precondition\]](#chainsel:fragments:precondition)). See `plausibleCandidateChain` in `NodeKernel` (PR #2735).
