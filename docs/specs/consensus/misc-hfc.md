# Misc stuff. To clean up.
## Ledger

### Invalid states
In a way, it is somewhat strange to have the hard fork mechanism be part of the Byron ([\[byron:hardfork\]](#byron:hardfork)) or Shelley ledger ([\[shelley:hardfork\]](#shelley:hardfork)) itself, rather than some overarching ledger on top. For Byron, a Byron ledger state where the *major* version is the (predetermined) moment of the hard fork is basically an invalid state, used only once to translate to a Shelley ledger. Similar, the *hard fork* part of the Shelley protocol version will never increase during Shelley's lifetime; the moment it *does* increase, that Shelley state will be translated to the (initial) state of the post-Shelley ledger.

## Keeping track of time
EpochInfo

## Failed attempts

### Forecasting
As part of the integration of any ledger in the consensus layer (not HFC specific), we need a projection from the ledger *state* to the consensus protocol ledger *view* ([\[,ledger:api:LedgerSupportsProtocol\]](#,ledger:api:LedgerSupportsProtocol)). As we have seen, the HFC additionally requires for each pair of consecutive eras a *state* translation functions as well as a *projection* from the state of the old era to the ledger view of the new era. These means that if we have $n + 1$ eras, we need $n$ across-era projection functions, in addition to the $n + 1$ projections functions we already have *within* each era.

This might feel a bit cumbersome; perhaps a more natural approach would be to only have within-era projection functions, but require a function to translate the ledger view (in addition to the ledger state) for each pair of eras. We initially tried this approach; when projecting from an era to the next, we would first ask the old era to give us the final ledger view in that era, and then translate this final ledger view across the eras:

::: center

The problem with this approach is that the ledger view only contains a small subset of the ledger state; the old ledger state might contain information about scheduled changes that should be taken into account when constructing the ledger view in the new era, but the final ledger view in the old era might not have that information.

Indeed, a moment's reflection reveals that this cannot be right the approach. After all, we cannot step the ledger state; the dashed arrow in

::: center

is not definable: scheduled changes are recorded in the ledger state, not in the ledger view. If we cannot even do this *within* an era, there is no reason to assume it would be possible *across* eras.

We cannot forecast directly from the old ledger state to the new era either: this would result in a ledger view from the old era in the new era, violating the invariant we discussed in [1.1.1](#hfc:ledger:invalid-states).

Both approaches---forecasting the final old ledger state and then translating, or forecasting directly across the era boundary and then translating---also suffer from another problem: neither approach would compute correct forecast bounds. Correct bounds depend on properties of both the old and the new ledger, as well as the distance of the old ledger state to that final ledger view. For example, if that final ledger view is right at the edge of the forecast range of the old ledger state, we should not be able to give a forecast in the new era at all.

Requiring a special forecasting function for each pair of eras of course in a way is cheating: it pushes the complexity of doing this forecasting to the specific ledgers that the HFC is instantiated at. As it turns out, however, this function tends to be easy to define for any pair of concrete ledgers; it's just hard to define in a completely general way.
