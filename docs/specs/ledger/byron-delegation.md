# Delegation
An agent owning a key that can sign new blocks can delegate its signing rights to another key by means of *delegation certificates*. These certificates are included in the ledger, and therefore also included in the body of the blocks in the blockchain.

There are several restrictions on a certificate posted on the blockchain:

1.  Only genesis keys can delegate.

2.  Certificates must be properly signed by the delegator.

3.  Any given key can delegate at most once per-epoch.

4.  Any given key can issue at most one certificate in a given slot.

5.  The epochs in the certificates must refer to the current or to the next epoch. We do not want to allow certificates from past epochs so that a delegation certificate cannot be replayed. On the other hand if we allow certificates with arbitrary future epochs, then a malicious key can issue a delegation certificate per-slot, setting the epoch to a sufficiently large value. This will cause a blow up in the size of the ledger state since we will not be able to clean $\mathit{eks}$ (we only clean past epochs). Also note that we do not check the relation between the certificate epoch and the slot in which the certificate becomes active. This would bring additional complexity without any obvious benefit.

6.  Certificates do not become active immediately, but they require a certain number of slots till they become stable in all the nodes.

These conditions are formalized in 3. Rule eq:rule:delegation-scheduling determines when a certificate can become "scheduled". The definitions used in these rules are presented in 1, and the types of the system induced by $\xrightarrow[\mathsf{sdeleg}]{}{\underline{\phantom{a}}}$ are presented in 2. Here and in the remaining rules we will be using $k$ as an abstract constant that gives us the chain stability parameter.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      c & \mathsf{DCert} & \text{delegation certificate}\\
      \mathit{vk_g} & \mathsf{VKeyGen} & \text{genesis verification key}\\
    \end{array}
\end{equation*}$$

*Derived types* $$\begin{equation*}
    \begin{array}{rlrlr}
      \mathit{e} & \mathsf{Epoch} & n & \mathbb{N} & \text{epoch}\\
      \mathit{s} & \mathsf{Slot} & s & \mathbb{N} & \text{slot}\\
      \mathit{d} & \mathsf{SlotCount} & s & \mathbb{N} & \text{slot}
    \end{array}
\end{equation*}$$

*Constraints* $$\begin{align*}
    \mathsf{VKeyGen} \subseteq \mathsf{VKey}
\end{align*}$$

*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{dbody} & \mathsf{DCert} \to (\mathsf{VKey} \times \mathsf{Epoch})
      & \text{body of the delegation certificate}\\
      \mathsf{dwit} & \mathsf{DCert} \to (\mathsf{VKeyGen} \times \mathsf{Sig})
      & \text{witness for the delegation certificate}\\
      \mathsf{dwho} & \mathsf{DCert} \mapsto (\mathsf{VKeyGen} \times \mathsf{VKey})
      & \text{who delegates to whom in the certificate}\\
      \mathsf{depoch} & \mathsf{DCert} \mapsto \mathsf{Epoch}
      & \text{certificate epoch}\\
      \mathit{k} & \mathbb{N} & \text{chain stability parameter}
    \end{array}
\end{equation*}$$

**Delegation scheduling definitions**
*Delegation scheduling environments* $$\begin{equation*}
    \mathsf{DSEnv} =
    \left(
      \begin{array}{rlr}
        \mathcal{K} & \mathbb{P}~\mathsf{VKeyGen} & \text{allowed delegators}\\
        \mathit{e} & \mathsf{Epoch} & \text{epoch}\\
        \mathit{s} & \mathsf{Slot} & \text{slot}\\
      \end{array}
    \right)
\end{equation*}$$

*Delegation scheduling states* $$\begin{equation*}
    \mathsf{DSState}
    = \left(
      \begin{array}{rlr}
        \mathit{sds} & (\mathsf{Slot} \times (\mathsf{VKeyGen} \times \mathsf{VKey}))^{*} & \text{scheduled delegations}\\
        \mathit{eks} & \mathbb{P}~(\mathsf{Epoch} \times \mathsf{VKeyGen}) & \text{key-epoch delegations}
      \end{array}
    \right)
\end{equation*}$$

*Delegation scheduling transitions* $$\begin{equation*}
    \mathit{\_} \vdash
    \mathit{\_} \xrightarrow[\mathsf{sdeleg}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{DSEnv} \times \mathsf{DSState} \times \mathsf{DCert} \times \mathsf{DSState})
\end{equation*}$$

**Delegation scheduling transition-system types**
$$\begin{equation}
    \label{eq:sdeleg-bootstrap}
    \inference
    {
      \mathit{sds_0} \mathrel{\mathop:}= \epsilon
      &
      \mathit{eks_0} \mathrel{\mathop:}= \emptyset
    }
    {
      {\left(\begin{array}{l}
       \mathcal{K}\\
        e\\
        s
      \end{array}\right)}
      \vdash
      \xrightarrow[\mathsf{sdeleg}]{}{}
      \left(
        \begin{array}{l}
          \mathit{sds_0}\\
          \mathit{eks_0}
        \end{array}
      \right)
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:delegation-scheduling}
    \inference
    {
      (\mathit{vk_s},~ \sigma) \mathrel{\mathop:}= \mathsf{dwit}~c
      & \mathsf{verify}~vk_s~\lbrack\!\lbrack \mathit{\mathsf{dbody}~c} \rbrack\!\rbrack~\sigma & vk_s \in \mathcal{K}\\ ~ \\
      (\mathit{vk_s},~ \mathit{vk_d}) \mathrel{\mathop:}= \mathsf{dwho}~c & e_d \mathrel{\mathop:}= \mathsf{depoch}~c
      & (e_d,~ \mathit{vk_s}) \notin \mathit{eks} & 0 \leq e_d - e \leq 1 \\ ~ \\
      d \mathrel{\mathop:}= 2 \cdot k & (s + d,~ (\mathit{vk_s},~ \underline{\phantom{a}})) \notin \mathit{sds}\\
    }
    {
      {\left(\begin{array}{l}
       \mathcal{K}\\
        e\\
        s
      \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{sds}\\
            \mathit{eks}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{sdeleg}]{}{c}
      {
        \left(
          \begin{array}{l}
            \mathit{sds}; (s + d,~ (\mathit{vk_s},~ \mathit{vk_d}))\\
            \mathit{eks} \cup \{(e_d,~ \mathit{vk_s})\}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Delegation scheduling rules**
The rules in Figure 6 model the activation of delegation certificates. Once a scheduled certificate becomes active (see sec:delegation-interface-rules), the delegation map is changed by it only if:

- The delegating key ($\mathit{vk_s}$) did not activate a delegation certificate in a slot greater or equal than the certificate slot ($s$). This check is performed to avoid having the constraint that the delegation certificates have to be activated in slot order.

- The key being delegated to ($\mathit{vk_d}$) has not been delegated by another key (injectivity constraint).

The reason why we check that the delegation map is injective is to avoid a potential risk (during the OBFT era) in which a malicious node gets control of a genesis key $\mathit{vk_m}$ that issued the maximum number of blocks in a given window. By delegating to another key $\mathit{vk_d}$, which was already delegated to by some other key $\mathit{vk_g}$, the malicious node could prevent $\mathit{vk_g}$ from issuing blocks. Even though the delegation certificates take several slots to become effective, the malicious node could calculate when the certificate would become active, and issue a delegation certificate at the right time.

As an additional advantage, by having an injective delegation map, we are able to simplify our specification when it comes to counting the blocks issued by (delegates of) genesis keys.

Note also, that we could not impose the injectivity constraint in Rule eq:rule:delegation-scheduling since we do not have information about the delegations that will become effective. We could of course detect a violation in the injectivity constraint when scheduling a delegation certificate, but this will lead to a complex computation and larger state in said rule.

Finally, note that we do not want to reject a scheduled delegation that would violate the injectivity constraint (since delegation might not have been scheduled by the node issuing the block). Instead, we simply ignore the delegation certificate (Rule eq:rule:delegation-nop).


$$\begin{align*}
    & \unionoverrideRight \in (A \mapsto B) \to (A \mapsto B) \to (A \mapsto B)
    & \text{union override}\\
    & d_0 \unionoverrideRight d_1 = d_1 \cup (\dom d_1 \mathbin{\rlap{\lhd}/} d_0)
\end{align*}$$

**Functions used in delegation rules**
*Delegation environments* $$\begin{equation*}
    \mathsf{DEnv} =
    \left(
      \begin{array}{rlr}
        \mathcal{K} & \mathbb{P}~\mathsf{VKeyGen} & \text{allowed delegators}
      \end{array}
    \right)
\end{equation*}$$

*Delegation states* $$\begin{align*}
    & \mathsf{DState}
      = \left(
        \begin{array}{rlr}
          \mathit{dms} & \mathsf{VKeyGen} \mapsto \mathsf{VKey} & \text{delegation map}\\
          \mathit{dws} & \mathsf{VKeyGen} \mapsto \mathsf{Slot} & \text{when last delegation occurred}\\
        \end{array}\right)
\end{align*}$$ *Delegation transitions* $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{adeleg}]{}{\_} \_ \in
    \powerset (\mathsf{DEnv} \times \mathsf{DState} \times (\mathsf{Slot} \times (\mathsf{VKeyGen} \times \mathsf{VKey})) \times \mathsf{DState})
\end{equation*}$$

**Delegation transition-system types**
$$\begin{equation}
    \label{eq:adeleg-bootstrap}
    \inference
    {
      \mathit{dms_0} \mathrel{\mathop:}= \mathsf{Set}{k \mapsto k}{k \in \mathcal{K}} &
      \mathit{dws_0} \mathrel{\mathop:}= \mathsf{Set}{k \mapsto 0}{k \in \mathcal{K}}
    }
    {
      \left(
        \mathcal{K}
      \right)
      \vdash
      \xrightarrow[\mathsf{adeleg}]{}{}
      \left(
        \begin{array}{l}
          \mathit{dms_0}\\
          \mathit{dws_0}
        \end{array}
      \right)
    }
\end{equation}$$ $$\begin{equation}
\label{eq:rule:delegation-change}
    \inference
    {
      \mathit{vk_d} \notin \range~\mathit{dms} & (\mathit{vk_s} \mapsto s_p \in \mathit{dws} \Rightarrow s_p < s)
    }
    {
      \left(\mathcal{K}\right)
      \vdash
      \left(
      \begin{array}{r}
        \mathit{dms}\\
        \mathit{dws}
      \end{array}
      \right)
      \xrightarrow[\mathsf{adeleg}]{}{(s,~ (vk_s,~ vk_d))}
      \left(
      \begin{array}{lcl}
        \mathit{dms} & \unionoverrideRight & \{\mathit{vk_s} \mapsto \mathit{vk_d}\}\\
        \mathit{dws} & \unionoverrideRight & \{\mathit{vk_s} \mapsto s \}
      \end{array}
      \right)
    }
\end{equation}$$ $$\begin{equation}
\label{eq:rule:delegation-nop}
    \inference
    {\mathit{vk_d} \in \range~\mathit{dms} \vee (\mathit{vk_s} \mapsto s_p  \in \mathit{dws}  \wedge s \leq s_p)
    }
    {
      \left(\mathcal{K}\right)
      \vdash
      \left(
      \begin{array}{r}
        \mathit{dms}\\
        \mathit{dws}
      \end{array}
      \right)
      \xrightarrow[\mathsf{adeleg}]{}{(s,~ (\mathit{vk_s},~ \mathit{vk_d}))}
      \left(
      \begin{array}{lcl}
        \mathit{dms}\\
        \mathit{dws}
      \end{array}
      \right)
    }
\end{equation}$$

**Delegation inference rules**
## Delegation sequences
This section presents the rules that model the effect that sequences of delegations have on the ledger.


$$\begin{equation}
    \inference
    {
      {\begin{array}{l}
         \mathit{delegEnv}
      \end{array}}
      \vdash
      \xrightarrow[\mathsf{\hyperref[eq:sdeleg-bootstrap]{sdeleg}}]{}{}
      \mathit{delegSt}
    }
    {
      {\begin{array}{l}
         \mathit{delegEnv}
      \end{array}}
      \vdash
      \xrightarrow[\mathsf{sdelegs}]{}{}
      \mathit{delegSt}
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:delegation-scheduling-seq-base}
    \inference
    {}
    {
      \mathit{delegEnv}
      \vdash
      \mathit{delegSt}
      \xrightarrow[\mathsf{sdelegs}]{}{\epsilon}
      \mathit{delegSt}
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:delegation-scheduling-seq-ind}
    \inference
    {
      \mathit{delegEnv}
      \vdash
      \mathit{delegSt}
      \xrightarrow[\mathsf{sdelegs}]{}{\Gamma}
      \mathit{delegSt'}
      &
      \mathit{delegEnv}
      \vdash
      \mathit{delegSt'}
      \xrightarrow[\mathsf{\hyperref[fig:rules:delegation-scheduling]{sdeleg}}]{}{c}
      \mathit{delegSt''}
    }
    {
      \mathit{delegEnv}
      \vdash
      \mathit{delegSt}
      \xrightarrow[\mathsf{sdelegs}]{}{\Gamma; c}
      \mathit{delegSt''}
    }
\end{equation}$$

**Delegation scheduling sequence rules**
$$\begin{equation}
    \inference
    {
      {\begin{array}{l}
         \mathit{delegEnv}
      \end{array}}
      \vdash
      \xrightarrow[\mathsf{\hyperref[eq:adeleg-bootstrap]{adeleg}}]{}{}
      \mathit{delegSt}
    }
    {
      {\begin{array}{l}
         \mathit{delegEnv}
      \end{array}}
      \vdash
      \xrightarrow[\mathsf{adelegs}]{}{}
      \mathit{delegSt}
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:delegation-seq-base}
    \inference
    {}
    {
      \mathit{delegEnv}
      \vdash
      \mathit{delegSt}
      \xrightarrow[\mathsf{adelegs}]{}{\epsilon}
      \mathit{delegSt}
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:delegation-seq-ind}
    \inference
    {
      \mathit{delegEnv}
      \vdash
      \mathit{delegSt}
      \xrightarrow[\mathsf{adelegs}]{}{\Gamma}
      \mathit{delegSt'}
      &
      \mathit{delegEnv}
      \vdash
      \mathit{delegSt'}
      \xrightarrow[\mathsf{\hyperref[fig:rules:delegation]{adeleg}}]{}{c}
      \mathit{delegSt''}
    }
    {
      \mathit{delegEnv}
      \vdash
      \mathit{delegSt}
      \xrightarrow[\mathsf{adelegs}]{}{\Gamma; c}
      \mathit{delegSt''}
    }
\end{equation}$$

**Delegations sequence rules**
## Deviation from the `cardano-sl` implementation
In the `cardano-sl` implementation, the block issuer needs to include a delegation certificate in the block, which witness the fact that a genesis key gave the issuer the rights of issuing blocks on behalf of this genesis key. The reasons why this was implemented in this way in `cardano-sl` are not clear, since the delegation certificates are posted on the chain, so the ledger state contains the information about who delegates to whom. Hence in the current specification we use a heavyweight delegation scheme, i.e. where the certificates are posted on the chain, but an implementation of this rules that aims at being compatible with the implementation in `cardano-sl` has to take the fact that delegation certificates are also present in a block into account.
