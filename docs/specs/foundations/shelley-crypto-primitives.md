# Cryptographic primitives
Figure 1 introduces the cryptographic abstractions used in this document. We begin by listing the abstract types, which are meant to represent the corresponding concepts in cryptography. Their exact implementation remains open to interpretation and we do not rely on any additional properties of public key cryptography that are not explicitly stated in this document. The types and rules we give here are needed in order to guarantee certain security properties of the delegation process, which we discuss later.

The cryptographic concepts required for the formal definition of witnessing include public-private key pairs, one-way functions, signatures and multi-signature scripts. The constraint we introduce states that a signature of some data signed with a (private) key is only correct whenever we can verify it using the corresponding public key.

Abstract data types in this paper are essentially placeholders with names indicating the data types they are meant to represent in an implementation. Derived types are made up of data structures (i.e. products, lists, finite maps, etc.) built from abstract types. The underlying structure of a data type is implementation-dependent and furthermore, the way the data is stored on physical storage can vary as well.

Serialization is a physical manifestation of data on a given storage device. In this document, the properties and rules we state involving serialization are assumed to hold true independently of the storage medium and style of data organization chosen for an implementation. The type $\mathsf{Ser}$ denotes the serialized representation of a term of any serializable type.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{sk} & \mathsf{SKey} & \text{private signing key}\\
      \mathit{vk} & \mathsf{VKey} & \text{public verifying key}\\
      \mathit{hk} & \mathsf{KeyHash} & \text{hash of a key}\\
      \sigma & \mathsf{Sig}  & \text{signature}\\
      \mathit{d} & \mathsf{Ser}  & \text{data}\\
      \mathit{script} & \mathsf{Script} & \text{multi-signature script} \\
      \mathit{hs} & \mathsf{HashScr} & \text{hash of a script}
    \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rlr}
      (sk, vk) & \mathsf{KeyPair} & \text{signing-verifying key pairs}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{hashKey}~ & \mathsf{VKey} \to \mathsf{KeyHash}
                 & \text{hash a verification key} \\
                 %
      \mathsf{verify} & \mathbb{P}~\left(\mathsf{VKey} \times \mathsf{Ser} \times \mathsf{Sig}\right)
                   & \text{verification relation}\\
                   %
      \mathsf{sign} & \mathsf{SKey} \to \mathsf{Ser} \to \mathsf{Sig}
                 & \text{signing function}\\
      \mathsf{hashScript} & \mathsf{Script} \to \mathsf{HashScr} & \text{hash a serialized script}
    \end{array}
\end{equation*}$$ *Constraints* $$\begin{align*}
    & \forall (sk, vk) \in \mathsf{KeyPair},~ d \in \mathsf{Ser},~ \sigma \in \mathsf{Sig} \cdot
    \mathsf{sign}~sk~d = \sigma \implies (vk, d, \sigma) \in \mathsf{verify}
\end{align*}$$ *Notation for serialized and verified data* $$\begin{align*}
    & \lbrack\!\lbrack \mathit{x} \rbrack\!\rbrack ~\in \mathsf{Ser} & \text{serialised representation of } x\\
    & \mathcal{V}_{\mathit{vk}}{\lbrack\!\lbrack \mathit{d} \rbrack\!\rbrack}_{\sigma} = \mathsf{verify}~vk~d~\sigma
    & \text{shorthand notation for } \mathsf{verify}
\end{align*}$$

**Cryptographic definitions**
When we get to the blockchain layer validation, we will use key evolving signatures (KES) according to the MMM scheme [@cryptoeprint:2001:034]. This is another asymmetric key cryptographic scheme, also relying on the use of public and private key pairs. These signature schemes provide forward cryptographic security, meaning that a compromised key does not make it easier for an adversary to forge a signature that allegedly had been signed in the past. Figure 2 introduces the additional cryptographic abstractions needed for KES.

In KES, the public verification key stays constant, but the corresponding private key evolves incrementally. For this reason, KES signing keys are indexed by integers representing the step in the key's evolution. This evolution step parameter is also an additional parameter needed for the signing (denoted by $\mathsf{sign_{ev}}$) and verification (denoted by $\mathsf{verify_{ev}}$) functions.

Since the private key evolves incrementally in a KES scheme, the ledger rules require the pool operators to evolve their keys every time a certain number of slots have passed, as determined by the global constant $\mathsf{SlotsPerKESPeriod}$.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{sk} & \N \to \mathsf{SKeyEv} & \text{private signing keys}\\
      \mathit{vk} & \mathsf{VKeyEv} & \text{public verifying key}\\
    \end{array}
\end{equation*}$$ *Notation for evolved signing key* $$\begin{align*}
    & \mathit{sk_n} = \mathit{sk}~n & n\text{-th evolution of }sk
\end{align*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rlr}
      (sk_n, vk) & \mathsf{KeyPairEv} & \text{signing-verifying key pairs}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{verify_{ev}} & \mathbb{P}~\left(\mathsf{VKey} \times \N \times \mathsf{Ser} \times \mathsf{Sig}\right)
                        & \text{verification relation}\\
                        %
      \mathsf{sign_{ev}} & (\N \to \mathsf{SKeyEv}) \to \N \to \mathsf{Ser} \to \mathsf{Sig}
                      & \text{signing function}\\
    \end{array}
\end{equation*}$$ *Constraints* $$\begin{align*}
    & \forall n\in\N, (sk_n, vk) \in \mathsf{KeyPairEv}, ~ d \in \mathsf{Ser},~ \sigma \in \mathsf{Sig} \cdot \\
    & ~~~~~~~~\mathsf{sign_{ev}}~{sk}~{n}~{d} = \sigma \implies \verifyEv{vk}{n}{d}{\sigma}
\end{align*}$$ *Notation for verified KES data* $$\begin{align*}
    & \mathcal{V}^{\mathsf{KES}}_{\mathit{vk}}{\lbrack\!\lbrack \mathit{d} \rbrack\!\rbrack}_{\sigma}^n
        = \verifyEv{vk}{n}{d}{\sigma}
    & \text{shorthand notation for } \mathsf{verify_{ev}}
\end{align*}$$

**KES Cryptographic definitions**
Figure 3 shows the types for multi-signature schemes. Multi-signatures effectively specify one or more combinations of cryptographic signatures which are considered valid. This is realized in a native way via a script-like DSL which allows for defining terms that can be evaluated. Multi-signature scripts is the only type of script (for any purpose, including output-locking) that exist in Shelley.

The terms form a tree like structure and are evaluated via the function. The parameters are a script and a set of key hashes. The function returns $\mathsf{True}$ when the supplied key hashes are a valid combination for the script, otherwise it returns $\mathsf{False}$. The following are the four constructors that make up the multisignature script scheme:

-  :  the signature of a key with a specific hash is required;

-  : signatures of all of the keys that hash to the values specified in the given list are required;

-  : a single signature is required, by a key hashing to one of the given values in the list (this constructor is redundant and can be expressed using $\mathsf{RequireMOf}$);

-  :  $m$ of the keys with the hashes specified in the list are required to sign


*MultiSig Type*

$$\begin{equation*}
    \begin{array}{rll}
      \mathsf{MSig} & \subseteq & \mathsf{Script} \\
      \\~\\
      \mathit{msig}\in\mathsf{MSig} & = & \mathsf{RequireSig}~\mathsf{KeyHash}\\
      & \uplus &
         \mathsf{RequireAllOf}~[\mathsf{Script}] \\
      & \uplus&
         \mathsf{RequireAnyOf}~[\mathsf{Script}] \\
      & \uplus&
        \mathsf{RequireMOf}~\N~[\mathsf{Script}]
    \end{array}
\end{equation*}$$

*Functions*

$$\begin{align*}
    \mathsf{evalMultiSigScript} & \in\mathsf{MSig}\to\powerset\mathsf{KeyHash}\to\mathsf{Bool} & \\
    \mathsf{evalMultiSigScript} & ~(\mathsf{RequireSig}~hk)~\mathit{vhks} =  hk \in vhks \\
    \mathsf{evalMultiSigScript} & ~(\mathsf{RequireAllOf}~ts)~\mathit{vhks} =
                              \forall t \in ts: \mathsf{evalMultiSigScript}~t~vhks\\
    \mathsf{evalMultiSigScript} & ~(\mathsf{RequireAnyOf}~ts)~\mathit{vhks} =
                              \exists t \in ts: \mathsf{evalMultiSigScript}~t~vhks\\
    \mathsf{evalMultiSigScript} & ~(\mathsf{RequireMOf}~m~ts)~\mathit{vhks} = \\
                             & m \leq \Sigma
                               \left(
                               [\textrm{if}~(\mathsf{evalMultiSigScript}~\mathit{t}~\mathit{vhks})~
                               \textrm{then}~1~\textrm{else}~0\vert t \leftarrow ts]
                               \right)
\end{align*}$$

**Multi-signature via Native Scripts**