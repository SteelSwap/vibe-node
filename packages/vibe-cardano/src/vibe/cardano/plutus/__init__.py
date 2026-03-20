"""vibe.cardano.plutus -- Plutus script evaluation bridge.

Provides the interface between vibe-node's ledger and the uplc CEK machine
for evaluating Plutus scripts (V1, V2, V3).

Key components:
    - ``evaluate.py`` -- Script evaluation via uplc
    - ``context.py`` -- ScriptContext construction (TxInfo, ScriptPurpose)
    - ``cost_model.py`` -- Cost model types and parameter vectors

Spec references:
    * Alonzo ledger formal spec, Section 4 (Plutus scripts)
    * Babbage ledger formal spec, Section 4 (PlutusV2 extensions)
    * Conway ledger formal spec (PlutusV3 extensions)
    * ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Plutus/Evaluate.hs``
    * ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Scripts.hs``

Haskell references:
    * ``evalPlutusScript`` in ``Cardano.Ledger.Alonzo.Plutus.Evaluate``
    * ``ScriptContext`` in ``PlutusLedgerApi.V1.Contexts`` / V2 / V3
    * ``CostModel`` in ``Cardano.Ledger.Alonzo.Scripts``
"""

from vibe.cardano.plutus.cost_model import (
    CostModel,
    ExUnits,
    PlutusVersion,
)
from vibe.cardano.plutus.evaluate import (
    EvalResult,
    evaluate_script,
)

__all__ = [
    "CostModel",
    "ExUnits",
    "EvalResult",
    "PlutusVersion",
    "evaluate_script",
]
