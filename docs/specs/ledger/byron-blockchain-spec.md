# List of Contributors
Damian Nadales, Yun Lu.

# Introduction
The idea behind this document is to formalise what it means for a new block to be added to the blockchain to be valid. The scope of the document is the Byron release and a transition phase to the Shelley release of the Cardano blockchain platform.

Unless a new block is valid, it cannot be added to the blockchain and thereby extend it. This is needed for a system that is subscribed to the blockchain and keeps a copy of it locally. In particular, this document gives a formalisation that should be straightforward to implement in a programming language, e.g., in Haskell.

This document is intended to be read in conjunction with [@byron_ledger_spec], which covers the payload carried around in the blockchain. Certain of the underlying systems and types defined will rely on definitions in that document.

# Preliminaries
Powerset

:   Given a set $\mathsf{X}$, $\mathbb{P}~\mathsf{X}$ is the set of all the subsets of $X$.

Sequence

:   Given a set $\mathsf{X}$, $\mathsf{X}^{*}$ is a sequence having elements taken from $\mathsf{X}$. The empty sequence is denoted by $\epsilon$, and given a sequence $\Lambda$, $\Lambda; x$ is the sequence that results from appending $x \in \mathsf{X}$ to $\Lambda$. Furthermore, $\epsilon$ is an identity element for sequence joining: $\epsilon; x = x; \epsilon = x$.

Dropping on sequences

:   Given a sequence $\Lambda$, $\Lambda \shortdownarrow n$ is the sequence that is obtained after removing (dropping) the first $n$ elements from $\Lambda$. If $n \leq 0$ then $\Lambda \shortdownarrow n = \Lambda$.

Appending with a moving window

:   Given a sequence $\Lambda$, we define $$\Lambda ;_w x \mathrel{\mathop:=}(\Lambda; x) \shortdownarrow (\left| \Lambda \right| + 1 - w)$$

Filtering on sequences

:   Given a sequence $\Lambda$, and a predicate $p$ on the elements of $\Lambda$, $\mathsf{filter}~p~\Lambda$ is the sequence that contains all the elements of $\Lambda$ that satisfy $p$, in the same order they appear on $\Lambda$.

Option type

:   An option type in type $A$ is denoted as $A^? = A + \Diamond$. The $A$ case corresponds to a case when there is a value of type $A$ and the $\Diamond$ case corresponds to a case when there is no value.

Union override

:   The union override operation is defined in Figure 1.

    :::: {#fig:unionoverride .figure}
    $$\begin{align*}
          \mathit{K} \lhd\mathit{M}
          & = \{ i \mapsto o \mid i \mapsto o \in \mathit{M}, ~ i \in \mathit{K} \}
          & \text{domain restriction}
          \\
          \mathit{K} \mathbin{\slashed{\lhd}}\mathit{M}
          & = \{ i \mapsto o \mid i \mapsto o \in \mathit{M}, ~ i \notin \mathit{K} \}
          & \text{domain exclusion}
          \\
          \mathit{M} \rhd\mathit{V}
          & = \{ i \mapsto o \mid i \mapsto o \in \mathit{M}, ~ o \in \mathit{V} \}
          & \text{range restriction}
          \\
          & \mathbin{\underrightarrow\cup}\in (A \mapsto B) \to (A \mapsto B) \to (A \mapsto B)
          & \text{union override}\\
          & d_0 \mathbin{\underrightarrow\cup}d_1 = d_1 \cup (\mathop{\mathrm{dom}}d_1 \mathbin{\slashed{\lhd}}d_0)
    \end{align*}$$

    ::: caption
    Definition of the Union Override Operation
    :::
    ::::

Pattern matching in premises

:   In the inference-rules premises use $\mathit{patt} = \mathit{exp}$ to pattern-match an expression $\mathit{exp}$ with a certain pattern $\mathit{patt}$. For instance, we use $\Lambda'; x = \Lambda$ to be able to deconstruct a sequence $\Lambda$ in its last element, and prefix. If an expression does not match the given pattern, then the premise does not hold, and the rule cannot trigger.

Maps and partial functions

:   $A \mapsto B$ denotes a **partial function** from $A$ to $B$, which can be seen as a map (dictionary) with keys in $A$ and values in $B$. Given a map $m \in A \mapsto B$, notation $a \mapsto b \in m$ is equivalent to $m~ a = b$.

## Sets
There are several standard sets used in the document:

Booleans

:   The set of booleans is denoted with $\mathbb{B}$ and has two values, $\mathbb{B} = \{\bot, \top\}$.

Natural numbers

:   The set of natural numbers is denoted with $\mathbb{N}$ and defined as $\mathbb{N} = \{0, 1, 2, \dots\}$.

# Update interface

We define a general update interface to abstract over the various update state transitions which happen when a new block is processed. Figure 2 defines the type of signals used for this system. Figure 4 defines the rules for this system. The two rules handle the cases where there is or is not an update proposal contained within the block.


*Update interface signals* $$\begin{equation*}
    \mathsf{UpdatePayload}=
    \left(
      \begin{array}{rlr}
        \mathit{mprop} & \mathsf{UProp}^{?} & \text{possible update proposal}\\
        \mathit{votes} & \mathsf{Vote}^{*} & \text{votes for update proposals}\\
        \mathit{end} & (\mathsf{VKey}\times \mathsf{ProtVer}) & \text{protocol version endorsment}
      \end{array}
    \right)
\end{equation*}$$

**Update interface processing types and functions**

*Update interface processing transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xlongrightarrow[\textsc{bupi}]{\_} \mathit{\_} \subseteq
    \mathbb{P}~(\mathsf{UPIEnv}\times \mathsf{UPIState}\times \mathsf{UpdatePayload}\times \mathsf{UPIState})
\end{equation*}$$

**Update interface processing transition-system types**

$$\begin{equation*}
    \inference
    { \Gamma \vdash \mathit{us}
      \xlongrightarrow[\textsc{\hyperlink{byron_ledger_spec_link}{upireg}}]{\mathit{prop}} \mathit{us'}
      \\
      \Gamma \vdash \mathit{us'}
      \xlongrightarrow[\textsc{\hyperlink{byron_ledger_spec_link}{upivotes}}]{\mathit{votes}} \mathit{us''}
      &
      \Gamma \vdash \mathit{us''}
      \xlongrightarrow[\textsc{\hyperlink{byron_ledger_spec_link}{upiend}}]{\mathit{end}} \mathit{us'''}
    }
    {
      \Gamma \vdash
      {\mathit{us}}
      \xlongrightarrow[\textsc{bupi}]{
        \left(
          \begin{array}{l}
            \mathit{prop} \\
            \mathit{votes} \\
            \mathit{end}
          \end{array}
        \right)
      }
      {\mathit{us'''}}
    }
\end{equation*}$$ $$\begin{equation*}
    \inference
    { \Gamma \vdash \mathit{us}
      \xlongrightarrow[\textsc{\hyperlink{byron_ledger_spec_link}{upivotes}}]{\mathit{votes}} \mathit{us'}
      &
      \Gamma \vdash \mathit{us'}
      \xlongrightarrow[\textsc{\hyperlink{byron_ledger_spec_link}{upiend}}]{\mathit{end}} \mathit{us''}
    }
    {
      \Gamma \vdash \mathit{us}
      \xlongrightarrow[\textsc{bupi}]{
        \left(
          \begin{array}{l}
            \Diamond\\
            \mathit{votes} \\
            \mathit{end}
          \end{array}
        \right)
      }
      \mathit{us''}
    }
\end{equation*}$$

**Update interface processing rules**

# Permissive BFT

The majority of this specification is concerned with the processing of the *ledger*; that is, the content (contained in both the block header and the block body). In addition, however, we must also concern ourselves with the protocol used to transmit the blocks and whether, according to that protocol, we may validly extend the chain with a new block (assuming that block forms a valid extension to the chain under the ledger rules).

Cardano's planned evolution can be split into roughly three eras:

Byron/Ouroboros

:   In the Byron/Ouroboros era, the Ouroboros ([@ouroboros]) protocol is used to control who is eligible to issue a block, using a stake distribution mediated by heavyweight delegation certificates. The Byron payload includes such things as VSS and payloads verified by individual signatures.

Handover

:   In the handover era, blocks will be issued according to Ouroboros BFT ([@ouroboros_bft]). The Byron payload will be retained, although parts of will be superfluous.

Shelley/Praos

:   In the Shelley/Praos era, blocks will be issued according to the Ouroboros Praos ([@ouroboros_praos]) protocol, with stake distribution determined according to the new delegation design in [@delegation_design].

During the handover era (as described in this document), while blocks will be issued according to Ouroboros BFT, they will be validated according to a variant known as Permissive BFT. This is designed such that it will successfully validate blocks issued both under Ouroboros and under Ouroboros BFT (with a high probability - see Appendix 9).

This section therefore will describe the section of the rules concerned with the Permissive BFT protocol. Note that all of these are concerned only with the block header, since the block body is entirely concerned with the ledger.

## Counting signed blocks

To guard against the compromise of a minority of the genesis keys, we require that in the rolling window of the last $k$ blocks, where $k$ is the chain stability parameter, the number of blocks signed by keys that $sk_s$ delegated to is no more than a threshold $k \cdot t$, where $t$ is a constant that will be picked in the range $1/5 \leq t \leq 1/4$. Initial research suggests setting $t=0.22$ as a good value. Specifically, given $k=2160$, we would allow a single genesis key to issue (via delegates) $475$ blocks (since $2160 \cdot 0.22 = 475.2$), but a $476^{\text{th}}$ block would be rejected. See Appendix 9 for the background on this value. The abstract constant (nullary functions) related to the protocol are defined in 5{reference-type="ref+label" reference="fig:defs:proto-abstract-funcs"}.


*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      k & \mathbb{N} & \text{chain stability parameter}\\
      t & \left[\frac{1}{5}, \frac{1}{4}\right] & \text{block signature count threshold}\\
      \mathsf{dms} & \mathsf{DIState}\to(\mathsf{VKey_G}\mapsto \mathsf{VKey}) & \text{delegation-state delegation-map}
    \end{array}
\end{equation*}$$

**Protocol abstract functions**

Figure 7 gives the rules for signature counting. We verify that the key that delegates to the signer of this block has not already signed more than its allowed threshold of blocks. If there are no delegators for the given key, or if there is more than one delegator, the rule will fail to trigger. We then update the sequence of signers, and drop those elements that fall outside the size of the moving window ($k$).


*Block signature count environments* $$\begin{equation*}
    \mathsf{BSCEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{ds} & \mathsf{DIState}& \text{delegation state} \\
      \end{array}
    \right)
\end{equation*}$$

*Block signature count transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xlongrightarrow[\textsc{sigcnt}]{\_} \mathit{\_} \subseteq
    \mathbb{P}~(\mathsf{BSCEnv}\times \mathsf{VKey_G}^{*} \times \mathsf{VKey}\times \mathsf{VKey_G}^{*})
\end{equation*}$$

**Block signature count transition-system types**

$$\begin{equation*}
    \inference
    {
      \{\mathit{vk_g}\} \mathrel{\mathop:=}\mathop{\mathrm{dom}}{((\mathsf{dms} ~ \mathit{ds}) \rhd\{\mathit{vk_d}\})}
      & \mathit{sgs'} \mathrel{\mathop:=}\mathit{sgs};_k {vk_g} &
      \left| \mathsf{filter}~(=\mathit{vk_g})~\mathit{sgs'} \right| \leq k \cdot t \\
    }
    {
      \mathit{ds}
      \vdash
      {\mathit{sgs}}
      \xlongrightarrow[\textsc{sigcnt}]{\mathit{vk_d}}
      {\mathit{sgs'}}
    }
   \label{eq:rule:sigcnt}
\end{equation*}$$

**Block signature count rules**

## Permissive BFT Header Processing

During PBFT processing of the block header, we do the following:

1.  We check that the current block is being issued for a slot later than that of the last block issued.

2.  We check that the current block is being issued for a slot no later than the current slot (as determined by the system clock).

3.  We check that the previous block hash contained in the block header corresponds to the known hash of the previous block.

4.  We check that the header signature correctly verifies the "signed" content of the header.

5.  Finally, we verify and update the state according to the signature count rules.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      bh & \mathsf{BlockHeader}& \text{Block header}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{bhPrevHash} & \mathsf{BlockHeader}\to\mathsf{Hash}& \text{previous header hash} \\
      \mathsf{bhHash} & \mathsf{BlockHeader}\to\mathsf{Hash}& \text{header hash} \\
      \mathsf{bhSig} & \mathsf{BlockHeader}\to\mathsf{Sig}& \text{block signature} \\
      \mathsf{bhIssuer} & \mathsf{BlockHeader}\to\mathsf{VKey}& \text{block issuer} \\
      \mathsf{bhSlot} & \mathsf{BlockHeader}\to\mathsf{Slot}& \text{slot for which this block is issued}
    \end{array}
\end{equation*}$$

**Permissive BFT types and functions**

*Permissive BFT environments* $$\begin{equation*}
    \mathsf{PBFTEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{ds} & \mathsf{DIState}& \text{delegation state} \\
        \mathit{s_{last}} & \mathsf{Slot}& \text{slot for which the last known block was issued} \\
        \mathit{s_{now}} & \mathsf{Slot}& \text{current slot} \\
      \end{array}
    \right)
\end{equation*}$$

*Permissive BFT states* $$\begin{equation*}
    \mathsf{PBFTState}=
    \left(
      \begin{array}{rlr}
        \mathit{h} & \mathsf{Hash}& \text{Tip header hash} \\
        \mathit{sgs} & \mathsf{VKey_G}^{*} & \text{Last signers}
      \end{array}
    \right)
\end{equation*}$$ *Permissive BFT transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xlongrightarrow[\textsc{pbft}]{\_} \mathit{\_} \subseteq
    \mathbb{P}~(\mathsf{PBFTEnv}\times \mathsf{PBFTState}\times \mathsf{BlockHeader}\times \mathsf{PBFTState})
\end{equation*}$$

**Permissive BFT transition-system types**

$$\begin{equation*}
    \inference
    {
      \mathit{vk_d} \mathrel{\mathop:=}\mathsf{bhIssuer} ~ bh & \mathit{s} \mathrel{\mathop:=}\mathsf{bhSlot}\ bh
      \\ \mathit{s} > \mathit{s_{last}} & \mathit{s} \leq \mathit{s_{now}}
      \\ \mathsf{bhPrevHash}\ bh = \mathit{h} & \mathsf{verify} ~ vk_d ~ \llbracket \mathit{\mathsf{bhToSign}\ bh} \rrbracket ~ (\mathsf{bhSig} ~ bh)
      \\
      ds
      \vdash
      \mathit{sgs} \xlongrightarrow[\textsc{\hyperref[fig:rules:sigcnt]{sigcnt}}]{\mathit{vk_d}} \mathit{sgs'}
      \\
    }
    {
      \left(
        {\begin{array}{c}
           \mathit{ds} \\
           \mathit{s_{last}} \\
           \mathit{s_{now}} \\
         \end{array}}
     \right)
     \vdash
     \left(
       {\begin{array}{c}
          \mathit{h} \\
          \mathit{sgs}
        \end{array}}
    \right)
    \xlongrightarrow[\textsc{pbft}]{\mathit{bh}}
    \left(
      {\begin{array}{c}
         \mathsf{bhHash}\ bh \\
         \mathit{sgs}'
       \end{array}}
   \right)
 }
\end{equation*}$$

**Permissive BFT rules**

# Epoch transitions

During each block transition, we must determine whether that block sits on an epoch boundary and, if so, carry out various actions which are done on that boundary. In the BFT era, the only computation carried out at the epoch boundary is the update of protocol versions.

We rely on a function $\mathsf{sEpoch}$, whose type is given in 11{reference-type="ref+label" reference="fig:defs:epoch"}, to determine the epoch corresponding to a given slot. We do not provide an implementation for such function in this specification, but in practice a possible way of implementing such function is to rely on map from the epochs to their corresponding length (given in number of slots they contain). Such a map would also be required by the database layer to find the requisite epoch file to look up a given block. We envision that an implementation may of course choose a more compact representation for this partial function that only records the changes in epoch length, rather than storing a length for each epoch. In addition, we rely on abstract constant (nullary function) $\mathit{ngk}$, which determines the number of genesis keys.

It is also worth noticing that in the Byron era, the number of slots per-epoch is fixed to $10 \cdot k$, where $k$ is the chain stability parameter.

Figure 13 determines when an epoch change has occurred and updates the update state to the correct version.


*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{sEpoch}
      & \mathsf{Slot}\to\mathbb{N} \to\mathsf{Epoch}
      & \text{epoch containing this slot} \\
      \mathit{ngk} & \mathbb{N} & \text{number of genesis keys}\\
    \end{array}
\end{equation*}$$

**Epoch transition types and functions**

*Epoch transition environments* $$\begin{align*}
    & \mathsf{ETEnv}
      = \left(
          \begin{array}{rlr}
            \mathit{e_c} & \mathsf{Epoch}& \text{current epoch}
          \end{array}\right)
\end{align*}$$

*Epoch transition states* $$\begin{equation*}
    \mathsf{ETState}=
    \left(
      \begin{array}{rlr}
        \mathit{us} & \mathsf{UPIState}& \text{update interface state}
      \end{array}
    \right)
\end{equation*}$$

*Epoch transition transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xlongrightarrow[\textsc{epoch}]{\_} \mathit{\_} \subseteq
    \mathbb{P}~(\mathsf{ETEnv}\times \mathsf{ETState}\times \mathsf{Slot}\times \mathsf{ETState})
\end{equation*}$$

**Epoch transition transition-system types**

$$\begin{equation*}
    \inference
    {
      \mathit{e_c} \geq \mathsf{sEpoch}\ s\ k
    }
    {\mathit{e_c}
      \vdash
      {
          {\begin{array}{c}
             \mathit{us}
           \end{array}
         }
     }
     \xlongrightarrow[\textsc{epoch}]{s}
     {
         {\begin{array}{c}
            \mathit{us}
          \end{array}
        }
    }
  }
\end{equation*}$$ $$\begin{equation*}
  \inference
  {
    \mathit{e_c} < \mathsf{sEpoch}\ s\ k
    &
    \mathsf{sEpoch}\ s\ k\vdash \mathit{us} \xlongrightarrow[\textsc{\hyperlink{byron_ledger_spec_link}{upiec}}]{} \mathit{us'}
  }
  {
    \mathit{e_c}
    \vdash
    {
        {\begin{array}{c}
           \mathit{us}
         \end{array}
       }
   }
   \xlongrightarrow[\textsc{epoch}]{s}
   {
       {\begin{array}{c}
          \mathit{us'}
        \end{array}
      }
  }
}
\end{equation*}$$

**Epoch transition rules**

# Block processing
We delineate here between processing the header and body of a block. It's useful to make this distinction since we may process headers ahead of the block body, and we have less context available to process headers - in particular, we must be able to process block headers without the recent history of block bodies.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      b & \mathsf{Block}& \text{block} \\
      h & \mathsf{Hash}& \text{hash} \\
      \mathit{data} & \mathsf{Data}& \text{data}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{bSize} & \mathsf{Block}\to\mathbb{N} & \text{block size in bytes} \\
      \mathsf{verify} & \mathsf{VKey}\times \mathsf{Data}\times \mathsf{Sig}& \text{verification relation} \\
    \end{array}
\end{equation*}$$

**Basic Block-related Types and Functions**

## Block header processing

Processing headers doesn't require any changes to the state, so we simply check predicates. Figure \[eq:func:header-is-valid\] gives the validity predicate for a header. We verify that the block header does not exceed the maximum size specified in the protocol parameters. The $\mathsf{maxHeaderSize}{}$ protocol parameter is defined in [@byron_ledger_spec].


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      bh & \mathsf{BlockHeader}& \text{block header} \\
      bts & \mathsf{BHToSign}& \text{part of the block header which must be signed}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{bHead} & \mathsf{Block}\to\mathsf{BlockHeader}& \text{block header} \\
      \mathsf{bHeaderSize} & \mathsf{BlockHeader}\to\mathbb{N} & \text{block header size in bytes}
    \end{array}
\end{equation*}$$

**Block header processing types and functions**

$$\begin{equation}
    \label{eq:func:header-is-valid}
    \mathsf{headerIsValid}~\mathit{us}~\mathit{bh} = \mathsf{maxHeaderSize}\mapsto \mathit{s_{max}} \in \mathsf{pps}~\mathit{us} \Rightarrow \mathsf{bHeaderSize} ~ bh \leq \mathit{s_{max}}
\end{equation}$$

**Block header validity functions**

## Block body processing

During processing of the block body, we perform two main functions: verification of the body integrity using the proofs contained in the block header, and update of the various state components. These rules are given in 18{reference-type="ref+label" reference="fig:rules:bbody"}, where the types and the functions used there are defined in 17{reference-type="ref+label" reference="fig:ts-types:bbody"}. The UTxO, delegation, and update state as well as the $\mathsf{maxBlockSize}{}$ protocol parameter are defined in [@byron_ledger_spec].

Verification is done independently for the three components of the body payload: UTxO, delegation and update. Each of these three has a hash in the block header. Note that Byron-era block payload also has an additional component: the VSS payload. This part of the block is unnecessary during the BFT era, and hence we do not verify it.

In addition to block verification, we also process the three components of the payload; UTxO, delegation and update.


*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{bUtxo} & \mathsf{Block}\to(\mathsf{Tx}\times \mathbb{P}~(\mathsf{VKey}\times \mathsf{Sig})) & \text{block UTxO payload} \\
      \mathsf{bCerts} & \mathsf{Block}\to\mathsf{DCert}^{*}
                                         & \text{block certificates} \\
      \mathsf{bUpdProp} & \mathsf{Block}\to\mathsf{UProp}^{?} & \text{block update proposal payload} \\
      \mathsf{bUpdVotes} & \mathsf{Block}\to\mathsf{Vote}^{*} & \text{block update votes payload} \\
      \mathsf{bProtVer} & \mathsf{Block}\to\mathsf{ProtVer}& \text{block protocol version} \\
      \mathsf{bhUtxoHash} & \mathsf{BlockHeader}\to\mathsf{Hash}& \text{UTxO payload hash} \\
      \mathsf{bhDlgHash} & \mathsf{BlockHeader}\to\mathsf{Hash}& \text{delegation payload hash} \\
      \mathsf{bhUpdHash} & \mathsf{BlockHeader}\to\mathsf{Hash}& \text{update payload hash} \\
      \mathsf{hash} & \mathsf{Data} \to\mathsf{Hash}& \text{hash function} \\
    \end{array}
\end{equation*}$$ *Derived functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{bEndorsment} & \in \mathsf{Block}\to \mathsf{ProtVer}\times \mathsf{VKey}& \text{Protocol version endorsment} \\
      \mathsf{bEndorsment}\ b & = (\mathsf{bProtVer}\ b, (bhIssuer\cdot bHead) ~ b)\\
      \mathsf{bSlot} & \in \mathsf{Block}\to \mathsf{Slot}& \text{Slot for which this block is being issued} \\
      \mathsf{bSlot}\ b & = (bhSlot\cdot bHead)~b \\
      \mathsf{bUpdPayload} & \in \mathsf{Block}\to (\mathsf{UProp}^{?}\times\mathsf{Vote}^{*}) & \text{Block update payload} \\
      \mathsf{bUpdPayload}\ b & = (\mathsf{bUpdProp}\ b,~\mathsf{bUpdVotes}\ b)
    \end{array}
\end{equation*}$$

**Block body processing types and functions**

*Block body processing environments* $$\begin{equation*}
    \mathsf{BBEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{pps} & \mathsf{PParams}& \text{protocol parameters} \\
        \mathit{e_n} & \mathsf{Epoch}& \text{epoch we are currently processing blocks for} \\
        \mathit{utxo_0} & \mathsf{UTxO}& \text{genesis UTxO}
      \end{array}
    \right)
\end{equation*}$$

*Block body processing states* $$\begin{equation*}
    \mathsf{BBState}=
    \left(
      \begin{array}{rlr}
        \mathit{utxoSt} & \mathsf{UTxOState}& \text{UTxO state} \\
        \mathit{ds} & \mathsf{DIState}& \text{delegation state} \\
        \mathit{us} & \mathsf{UPIState}& \text{update interface state}
      \end{array}
    \right)
\end{equation*}$$

*Block body processing transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xlongrightarrow[\textsc{bbody}]{\_} \mathit{\_} \subseteq
    \mathbb{P}~(\mathsf{BBEnv}\times \mathsf{BBState}\times \mathsf{Block}\times \mathsf{BBState})
\end{equation*}$$

**Block body processing transition-system types**

$$\begin{equation*}
    \inference
    { \mathsf{maxBlockSize}\mapsto \mathit{b_{max}} \in \mathit{pps} && \mathsf{bSize} ~ b \leq \mathit{b_{max}} \\
      \mathit{bh} \mathrel{\mathop:=}\mathsf{bHead}\ b & \mathit{vk_d} \mathrel{\mathop:=}\mathsf{bhIssuer} ~ \mathit{bh} \\
      \mathsf{hash}~(\mathsf{bUtxo}\ b) = \mathsf{bhUtxoHash}~\mathit{bh} &
      \mathsf{hash}~(\mathsf{bCerts} ~ b) = \mathsf{bhDlgHash}~\mathit{bh} \\
      \mathsf{hash}~(\mathsf{bUpdPayload}\ b) = \mathsf{bhUpdHash}~\mathit{bh}\\~\\
      {\left(
          \begin{array}{l}
            \mathsf{bSlot}\ b \\
            \mathsf{dms}~ ds
          \end{array}
        \right)}
      \vdash \mathit{us} \xlongrightarrow[\textsc{\hyperref[fig:rules:bupi]{bupi}}]{
        {\left(
            \begin{array}{l}
              \mathsf{bUpdProp}\ b \\
              \mathsf{bUpdVotes}\ b \\
              \mathsf{bEndorsment}\ b
            \end{array}
          \right)}
      } \mathit{us'}
      \\
      {\left(
          \begin{array}{l}
            \mathop{\mathrm{dom}}{(\mathsf{dms}~ ds)} \\
            \mathit{e_n}\\
            \mathsf{bSlot}\ b
          \end{array}
        \right)}
      \vdash \mathit{ds} \xlongrightarrow[\textsc{\hyperlink{byron_ledger_spec_link}{deleg}}]{\mathsf{bCerts} ~ b} \mathit{ds'} &
      {\left(
          \begin{array}{l}
            \mathit{utxo_0} \\
            \mathit{pps}
          \end{array}
        \right)}
      \vdash \mathit{utxoSt}
        \xlongrightarrow[\textsc{\hyperlink{byron_ledger_spec_link}{utxows}}]{\mathsf{bUtxo}\ b} \mathit{utxoSt'} \\
    }
    {
      \left(
        {\begin{array}{l}
           \mathit{pps} \\
           \mathit{e_n} \\
           \mathit{utxo_0}
         \end{array}}
     \right)
     \vdash
     {
       \left(
         {\begin{array}{c}
            \mathit{utxoSt} \\
            \mathit{ds} \\
            \mathit{us}
          \end{array}}
      \right)
    }
    \xlongrightarrow[\textsc{bbody}]{\mathit{b}}
    {
      \left(
        {\begin{array}{c}
           \mathit{utxoSt'} \\
           \mathit{ds'} \\
           \mathit{us'}
         \end{array}}
     \right)
   }
 }
\end{equation*}$$

**Block body processing rules**

# Blockchain extension
Figure 21 captures the central chain extension rule. This has two variants, depending on whether the block in question is an epoch boundary block. Epoch boundary blocks are not required during the BFT era, but whilst they are not distributed, epoch boundary blocks must still be processed since their hash forms part of the chain. Since we do not care about the contents of an epoch boundary block, we check that it does not exceed some suitably large size, and otherwise simply update the header hash to the block hash.

If the block is not an epoch boundary block, then we process:

- a potential epoch change according to the rules in figure 13,

- the header using the validity predicate of equation \[eq:func:header-is-valid\], and

- the body according to the rules in figure 18.


*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{bIsEBB} & \mathsf{Block}\to\mathbb{B} & \text{epoch boundary block check} \\
      \mathsf{pps} & \mathsf{UPIState}\to\mathsf{PParams}& \text{update-state protocol-parameters}
    \end{array}
\end{equation*}$$

**Blockchain Extension Types and Functions**

*Chain extension environments* $$\begin{equation*}
    \mathsf{CEEnv}
    = \left(
      \begin{array}{rlr}
        \mathit{s_{now}} & \mathsf{Slot}& \text{current slot} \\
        \mathit{utxo_0} & \mathsf{UTxO}& \text{genesis UTxO}
      \end{array}\right)
\end{equation*}$$

*Chain extension states* $$\begin{equation*}
    \mathsf{CEState}=
    \left(
      \begin{array}{rlr}
        \mathit{s_{last}} & \mathsf{Slot}& \text{slot of the last seen block} \\
        \mathit{sgs} & \mathsf{VKey_G}^{*} & \text{last signers}\\
        \mathit{h} & \mathsf{Hash}& \text{current block hash} \\
        \mathit{utxoSt} & \mathsf{UTxO}& \text{UTxOState} \\
        \mathit{ds} & \mathsf{DIState}& \text{delegation state}\\
        \mathit{us} & \mathsf{UPIState}& \text{update interface state} \\
      \end{array}
    \right)
\end{equation*}$$

*Chain extension transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xlongrightarrow[\textsc{chain}]{\_} \mathit{\_} \subseteq
    \mathbb{P}~(\mathsf{CEEnv}\times \mathsf{CEState}\times \mathsf{Block}\times \mathsf{CEState})
\end{equation*}$$

**Blockchain extension transition-system types**

$$\begin{equation*}
    \inference
    { \mathsf{bIsEBB} ~ b & \mathsf{bSize} ~ b \leq 2^{21} &
       \mathit{h'} \mathrel{\mathop:=}\mathsf{bhHash}\ (\mathsf{bHead}\ b)
    }
    {
     \left(
       {\begin{array}{l}
       \mathit{s_{now}} \\
       \mathit{utxo_0}
         \end{array}}
     \right)
     \vdash
     \left(
       {\begin{array}{c}
          \mathit{s_{last}} \\
          \mathit{sgs} \\
          \mathit{h} \\
          \mathit{utxoSt} \\
          \mathit{ds} \\
          \mathit{us}
        \end{array}}
    \right)
    \xlongrightarrow[\textsc{chain}]{b}
    \left(
      {\begin{array}{c}
         \mathit{s_{last}} \\
         \mathit{sgs} \\
         \mathit{h'} \\
         \mathit{utxoSt} \\
         \mathit{ds} \\
         \mathit{us}
       \end{array}}
   \right)
 }
\end{equation*}$$ $$\begin{equation*}
  \inference
  {
    \neg\mathsf{bIsEBB} ~ b \\~\\
    {
      \begin{array}{rl}
        {\left(
          \begin{array}{l}
            \mathsf{sEpoch}\ s_{last}\ k\\
          \end{array}
        \right)}
        &
        {\left(
          \begin{array}{l}
            us
          \end{array}
        \right)}
        \xlongrightarrow[\textsc{\hyperref[fig:rules:epoch]{epoch}}]{\mathsf{bSlot}\ b}
        {\left(
          \begin{array}{l}
            us'
          \end{array}
          \right)}\\
        \multicolumn{1}{l}{~}\\
        \multicolumn{2}{c}{\mathsf{headerIsValid}~\mathit{us'}~(\mathsf{bHead}\ b)}\\
        \multicolumn{1}{l}{~}\\
        {\left(
        \begin{array}{l}
          \mathsf{pps} ~  us' \\
          \mathsf{sEpoch}\ (\mathsf{bSlot}\ b)\ k \\
          \mathit{utxo_0}
        \end{array}
        \right)}
        &
        {\left(
          {\begin{array}{c}
             \mathit{utxoSt} \\
             \mathit{ds} \\
             \mathit{us'}
           \end{array}}
        \right)}
        \xlongrightarrow[\textsc{\hyperref[fig:rules:bbody]{bbody}}]{b}
        {\left(
          {\begin{array}{c}
             \mathit{utxoSt'} \\
             \mathit{ds'} \\
             \mathit{us''}
           \end{array}}
        \right)}\\
        \multicolumn{1}{l}{~}\\
        \left(
        {\begin{array}{l}
           \mathit{ds} \\
           \mathit{s_{last}} \\
           \mathit{s_{now}} \\
         \end{array}}
        \right)
        &
        \left(
          {\begin{array}{c}
             \mathit{h} \\
             \mathit{sgs}
           \end{array}}
        \right)
        \xlongrightarrow[\textsc{\hyperref[fig:rules:pbft]{pbft}}]{\mathsf{bHead}\ b}
        \left(
        {\begin{array}{c}
           \mathit{h'} \\
           \mathit{sgs}'
         \end{array}}
        \right)
      \end{array}
    }
  }
  {
     \left(
      {\begin{array}{l}
         \mathit{s_{now}} \\
         \mathit{utxo_0}
       \end{array}}
     \right)
     \vdash
     \left(
       {\begin{array}{c}
          \mathit{s_{last}} \\
          \mathit{sgs} \\
          \mathit{h} \\
          \mathit{utxoSt} \\
          \mathit{ds} \\
          \mathit{us}
        \end{array}}
    \right)
    \xlongrightarrow[\textsc{chain}]{b}
    \left(
      {\begin{array}{c}
         \mathit{\mathsf{bSlot}\ b} \\
         \mathit{sgs'} \\
         \mathit{h'} \\
         \mathit{utxoSt'} \\
         \mathit{ds'} \\
         \mathit{us''}
       \end{array}}
    \right)
  }
\end{equation*}$$

**Blockchain extension rules**

# Transition systems properties
## Header only validation
The following transition system is used in the properties enunciated in this section.


**Definition 1** (EPOCH+BHEAD+PBFT STS). *$$\inference
  {
    {\begin{array}{rl}
        {\left(
          \begin{array}{l}
            \mathsf{sEpoch}\ s_{last}\ k\\
          \end{array}
        \right)}
        &
        {\left(
          \begin{array}{l}
            us
          \end{array}
        \right)}
        \xlongrightarrow[\textsc{\hyperref[fig:rules:epoch]{epoch}}]{\mathsf{bSlot}\ b}
        {\left(
          \begin{array}{l}
            us'
          \end{array}
        \right)}\\
        \multicolumn{1}{l}{~}\\
        \multicolumn{2}{c}{\mathsf{headerIsValid}~\mathit{us'}~(\mathsf{bHead}\ b)}\\
        \multicolumn{1}{l}{~}\\
        \left(
        {\begin{array}{l}
           \mathit{ds} \\
           \mathit{s_{last}} \\
           \mathit{s_{now}} \\
         \end{array}}
        \right)
        &
        \left(
          {\begin{array}{c}
             \mathit{h} \\
             \mathit{sgs}
           \end{array}}
        \right)
        \xlongrightarrow[\textsc{\hyperref[fig:rules:pbft]{pbft}}]{\mathit{bh}}
        \left(
        {\begin{array}{c}
           \mathit{h'} \\
           \mathit{sgs}'
         \end{array}}
        \right)\\
      \end{array}}
  }
  {
    {\left(
        {\begin{array}{l}
           \mathit{ds} \\
           \mathit{s_{last}} \\
           \mathit{s_{now}} \\
         \end{array}}
     \right)
     \vdash
     \left(
          {\begin{array}{c}
             \mathit{h} \\
             \mathit{sgs}\\
             \mathit{us}
           \end{array}}
       \right)
       \xlongrightarrow[\textsc{epoch+bhead+pbft}]{\mathit{bh}}
        \left(
        {\begin{array}{c}
           \mathit{h'} \\
           \mathit{sgs}'\\
           \mathit{us'}
         \end{array}}
     \right)
     }
   }$$*

In any given ledger state, the consensus layer needs to be able to validate the block headers without having to download the block bodies. Property 1 states that if an extension of a chain that spans less than $2 \cdot k$ slots is valid, then validating the headers of that extension is also valid. This property is useful for its converse: if the header validation check for a sequence of headers does not pass, then we know that the block validation that corresponds to those headers will not pass either.


**Property 1** (Header only validation). *For all environments $e$, states $s$ with slot number $t$[^1], and chain extensions $E$ with corresponding headers $H$ such that: $$0 \leq t_E - t  \leq 2 \cdot k$$ we have: $$e \vdash s \xlongrightarrow[\textsc{chain}]{E}\negthickspace^{*} s' \implies e_h \vdash s_h \xlongrightarrow[\textsc{epoch+bhead+pbft}]{H}\negthickspace^{*} s'_h$$ where $t_E$ is the maximum slot number appearing in the blocks contained in $E$, $e_h \mathrel{\mathop:=}\mathsf{h_e}~e~s$ and $s_h \mathrel{\mathop:=}\mathsf{h_s}~e~s$, and functions $\mathsf{h_e}$ and $\mathsf{h_s}$ select the appropriate environment and state components needed by the $\footnotesize{\textsc{epoch+bhead+pbft}}$ transition system in the obvious way.*

Property 2 states that if we validate a sequence of headers, we can validate their bodies independently and be sure that the blocks will pass the chain validation rule. To see this, given an environment $e$ and initial state $s$, assume that a sequence of headers $H = [h_0, \ldots, h_n]$ corresponding to blocks in $E = [b_0, \ldots, b_n]$ is valid according to the $\footnotesize{\textsc{epoch+bhead+pbft}}$ transition system: $$e_h \vdash s_h \xlongrightarrow[\textsc{epoch+bhead+pbft}]{H}\negthickspace^{*} s'_h$$ where $e_h$ and $s_h$ are obtained from $e$ and $s$ as described in Property 1. Assume the bodies of $E$ are valid according to the $\footnotesize{\textsc{bbody}}$ rules, but $E$ is not valid according to the $\footnotesize{\textsc{chain}}$ rule. Assume that there is a $b_j \in E$ such that it is **the first block** such that does not pass the $\footnotesize{\textsc{chain}}$ validation. Then: $$e \vdash s \xlongrightarrow[\textsc{chain}]{[b_0, \ldots b_{j-1}]}\negthickspace^{*} s_j$$ But by Property 2 we know that $$e_{h_j} \vdash s_{h_j} \xlongrightarrow[\textsc{epoch+bhead+pbft}]{h_j} s_{h_{j+1}}$$ which means that block $b_j$ has valid headers, and this in turn means that the validation of $b_j$ according to the chain rules must have failed because it contained an invalid block body. But this contradicts our assumption that the block bodies were valid.


**Property 2** (Body only validation). *For all environments $e$, states $s$ with slot number $t$, and chain extensions $E = [b_0, \ldots, b_n]$ with corresponding headers $H$ such that: $$0 \leq t_E - t  \leq 2 \cdot k$$ we have that for all $i \in [1, n]$: $$e_h \vdash s_h \xlongrightarrow[\textsc{epoch+bhead+pbft}]{H}\negthickspace^{*} s'_h
  \wedge
  e \vdash s \xlongrightarrow[\textsc{chain}]{[b_0 \ldots b_{i-1}]}\negthickspace^{*} s_{i-1}
  \implies
  e_{h_{i-1}} \vdash s_{h_{i-1}}\xlongrightarrow[\textsc{epoch+bhead+pbft}]{h_i} s''_{h_{i}}$$ where $t_E$ is the maximum slot number appearing in the blocks contained in $E$, $e_h \mathrel{\mathop:=}\mathsf{h_e}~e~s$ and $s_h \mathrel{\mathop:=}\mathsf{h_s}~e~s$, $e_{h_{i-1}} \mathrel{\mathop:=}\mathsf{h_e}~e~s_{i-1}$ and $s_{h_{i-i}} \mathrel{\mathop:=}\mathsf{h_s}~e~s_{i-1}$, and $\mathsf{h_e}$ and $\mathsf{h_s}$ are the same functions mentioned in Property 1.*

Property 3 expresses the fact the there is a function that allow us to recover the header-only state by rolling back at most $k$ blocks, and use this state to validate the headers of an alternate chain. Note that this property is not inherent to the $\footnotesize{\textsc{chain}}$ rules and can be trivially satisfied by any function that keeps track of the history of the intermediate chain states up to $k$ blocks back. This property is stated here so that it can be used as a reference for the tests in the consensus layer, which uses the rules presented in this document.


**Property 3** (Existence of roll back function). *There exists a function $\mathsf{f}$ such that for all chains $$C = C_0 ; b; C_1$$ we have that if for all alternative chains $C'_1$, $\left| C'_1 \right| \leq k$, with corresponding headers $H'_1$ $$e \vdash s_0 \xlongrightarrow[\textsc{chain}]{C_0;b}\negthickspace^{*} s_1 \xlongrightarrow[\textsc{chain}]{C_1}\negthickspace^{*} s_2
  \wedge
  e \vdash s_1 \xlongrightarrow[\textsc{chain}]{C_1'}\negthickspace^{*} s'_1
  \implies
  (\mathsf{f}~(\mathsf{bHead}\ b)~s_2) \xlongrightarrow[\textsc{epoch+bhead+pbft}]{H'_1}\negthickspace^{*} s_h$$*

::: appendices
# Calculating the $t$ parameter
We originally give the range of $t$ as between $\frac{1}{5}$ and $\frac{1}{4}$. The upper bound here is to reduce the possible number of malicious blocks; if two of the genesis keys are comprimised, the attackers may not be able to produce a longer chain than the honest participants. The lower bound is required to prevent a situation in which a chain produced under the initial Ouroboros setting produces a chain which, according to the new BFT semantics, is invalid.

In order to determine the best value of $t$, we must consider the likelihood of such an invalid chain being produced by the old procedure of randomly selecting the slot leaders for each slot. Given the Cardano chain is still federated, the likelihood of this happening is the same for each of the 7 stakeholders, and we may model the number of selected slots within a $k$-slot window $X$ as a binomial distribution $X \sim \mathrm{B}\left(k, \frac{1}{7}\right)$.

In each epoch of size $n$ blocks, there are $n-k+1$ such $k$-block windows. Boole's inequality gives us that the likelihood of exceeding the threshold in any one of these windows is bounded above by the sum of the likelihoods for each window. We may thus consider that the probability of a given stakeholder violating the threshold in an epoch to be bounded by

$$(n-k+1)\cdot P(X > t*k)$$

Appealing to Boole's inequality again, we may multiply this by the number of epochs and the number of stakeholders to give a bound for the likelihood of generating an invalid chain.

Figure 22 gives the bound on the likelihood of threshold violation for $t$ in our plausible range: from this we can see that the likelihood decreases to a negligible level around $0.21$, and so we choose the value of $t=0.22$, giving an upper bound on the likelihood around $6e-10$. Increasing $t$ beyond this point gives no decrease in the likelihood of violation.


::: center
*[Image from original source]*

**Probability of generating an invalid chain for values of $t\in\left[
        \frac{1}{4}, \frac{1}{5} \right]$.**


[^1]: *i.e. the component $\mathit{s_{last}}$ of $s$ equals $t$*
