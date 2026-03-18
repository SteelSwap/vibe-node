# Implementation of
The minimum fee calculation in Figure fig:defs:protocol-parameters-helpers depends on an abstract $\mathsf{txSize}$ function. We have implemented $\mathsf{txSize}$ as the number of bytes in the CBOR serialization of the transaction, as defined in Appendix sec:cddl.
