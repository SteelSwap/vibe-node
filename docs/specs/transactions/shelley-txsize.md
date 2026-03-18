# Implementation of
The minimum fee calculation in Figure [\[fig:defs:protocol-parameters-helpers\]](#fig:defs:protocol-parameters-helpers) depends on an abstract $\fun{txSize}$ function. We have implemented $\fun{txSize}$ as the number of bytes in the CBOR serialization of the transaction, as defined in Appendix [\[sec:cddl\]](#sec:cddl).
