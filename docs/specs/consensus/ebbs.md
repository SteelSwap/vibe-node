# Epoch Boundary Blocks
## Introduction

Recall that when a new epoch begins, the active stake distribution in the new epoch---that is, the stake distribution used to determine the leader schedule--- is not the stake distribution as it was at the end of the last epoch, but rather as it was some distance back:

::: center

This means that blocks cannot influence the active stake distribution until some time in the future. That is important, because when a malicious node forks off from the honest chain, the leadership schedule near the intersection point cannot be influenced by the attacker, allowing us to compare chain density and choose the honest chain (which will be denser because of the assumed honest majority); see genesis for an in-depth discussion.

In the literature, the term "epoch boundary block" (or EBB for short) normally simply refers to the last block in any given epoch (for example, see [@buterin2020combining]). It might therefore be a bit surprising to find the term in this report since the final block in an epoch is not of special interest in the Ouroboros family of consensus protocols. However, in the first implementation of the Byron ledger (using the original Ouroboros protocol [@cryptoeprint:2016:889], which we now refer to as "Ouroboros Classic"), a decision was made to include the leadership schedule for each new epoch as an explicit block on the blockchain; the term EBB was used to refer to this special kind of block:[^1]

::: center

Having the leadership schedule explicitly recorded on-chain turns out not to be particularly useful, however, and the code was modified not to produce EBBs anymore even before we switched from Byron to Shelley (as part of the OBFT hard fork, see overview:history); these days, the contents of the existing EBBs on the chain are entirely ignored. Unfortunately, we cannot forget about EBBs altogether because---since they are an actual block on the blockchain---they affect the chain of block hashes: the first "real" block in each epoch points to the EBB as its predecessor, which then in turns points to the final block in the previous epoch.

So far, none of this is particularly problematic to the consensus layer. Having multiple types of blocks in a ledger presents some challenges for serialisation (serialisation:storage:nested-contents), but does not otherwise affect consensus much: after all, blocks are interpreted by the ledger layer, not by the consensus layer. Unfortunately, however, the design of the Byron EBBs has odd quirk: an EBB has the same block number as its *predecessor*, and the same slot number as its *successor*:

::: center

This turns out to be a huge headache. When we started the rewrite, I think we underestimated quite how many parts of the system would be affected by the possibility of having multiple blocks with the same block number and multiple blocks with the same slot number on a single chain. Some examples include:

- []{#ebb-chain-selection label="ebb-chain-selection"} For chain selection protocols based on chain length, two chains may end in blocks with the same block number, yet not have equal length.

- When we validate block headers that contain explicit block numbers, we cannot insist that those block numbers are monotonically increasing, instead having to add a special case for EBBs.

- TODO: Many, many others

In hindsight, we should have tried harder to eliminate EBBs from the get-go. In this chapter, we will discuss two options for modifying the existing design to reduce the impact of EBBs (1.2), or indeed eliminate them altogether (1.3).

## Logical slot/block numbers
## Eliminating EBBs altogether
[^1]: It is not entirely clear if an EBB should be regarded as the final block in an epoch, or as the first block in the next epoch. The name would suggest that the former interpretation is more appropriate; as it turns out, however, the very first epoch on the chain *starts* with an EBB, recording the leadership schedule derived from the genesis block. We will therefore regard the EBB as starting an epoch, rather than ending one.
