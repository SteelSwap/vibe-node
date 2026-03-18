'

# Update mechanism
This section formalizes the update mechanism by which the protocol parameters get updated. This formalization is a simplification of the current update mechanism implemented in [`cardano-sl`](https://github.com/input-output-hk/cardano-sl/), and partially documented in:

- [Updater implementation](https://cardanodocs.com/technical/updater/)

- [Update mechanism](https://cardanodocs.com/cardano/update-mechanism/)

- [Update system consensus rules](https://github.com/input-output-hk/cardano-sl/blob/2a19d8ce2941b8e60f0208a5198943ec2ada1fd4/docs/block-processing/us.md)

The reason for formalizing a simplified version of the current implementation is that research work on blockchain update mechanisms is needed before introducing a more complex update logic. Since this specification is to be implemented in a federated setting, some of the constraints put in place in the current implementation are no longer relevant. Once the research work is ready, this specification can be extended to incorporate the research results.

## Update proposals
The definitions used in the update mechanism rules are presented in 1. A system tag is used to identify the system for which the update is proposed (in practice this would be a string referring to an operating system; e.g. 'linux', 'win64', or 'mac32'). The software update metadata ($\mathsf{Mdt}$) is any information required for performing an update such as hashes of software downloads. Note that the fact that the metadata is kept abstract in the specification does not mean that we allow any arbitrary metadata (in the actual implementation this abstract metadata would correspond to 'Map SystemTag UpdateData', were the 'SystemTag' corresponds with $\mathsf{STag}$ and 'UpdateData' contains the software hash for a specific platform).


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{up} & \mathsf{UProp}& \text{update proposal}\\
      \mathit{p} & \mathsf{Ppm}& \text{protocol parameter}\\
      \mathit{upd} & \mathsf{UpdData} & \text{update data}\\
      \mathit{upa} & \mathsf{UpdAttrs} & \text{update attributes}\\
      \mathit{an} & \mathsf{ApName}& \text{application name}\\
      \mathit{t} & \mathsf{STag}& \text{system tag}\\
      \mathit{m} & \mathsf{Mdt}& \text{metadata}
    \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rlrlr}
      \mathit{s_n} & \mathsf{Slot} & n & \mathbb{N} & \text{slot number}\\
      \mathit{pv} & \mathsf{ProtVer}& (\mathit{maj}, \mathit{min}, \mathit{alt})
      & (\mathbb{N}, \mathbb{N}, \mathbb{N}) & \text{protocol version}\\
      \mathit{pps} & \mathsf{PPMMap} & \mathit{pps} & \mathsf{Ppm}\mapsto \mathsf{Value}
                                         & \text{protocol parameters map}\\
      \mathit{apv} & \mathsf{ApVer}& n & \mathbb{N}\\
      \mathit{swv} & \mathsf{SWVer}
      & (\mathit{an}, \mathit{av}) & \mathsf{ApName}\times \mathsf{ApVer}
      & \text{software version}\\
      \mathit{pb} & \mathsf{UpSD}
      &
        {\left(\begin{array}{r l}
                 \mathit{pv}\\
                 \mathit{pps}\\
                 \mathit{swv}\\
                 \mathit{upd}\\
                 \mathit{upa}\\
               \end{array}\right)}
      & {
        \left(
        \begin{array}{l}
          \mathsf{ProtVer}\\
          \mathsf{PPMMap}\\
          \mathsf{SWVer}\\
          \mathsf{UpdData}\\
          \mathsf{UpdAttrs}\\
        \end{array}
                   \right)
                   }
               & \text{protocol update signed data}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{upIssuer} & \mathsf{UProp}\to \mathsf{VKey} & \text{update proposal issuer (delegate)}\\
      \mathsf{upSize} & \mathsf{UProp}\to \mathbb{N} & \text{update proposal size}\\
      \mathsf{upPV} & \mathsf{UProp}\to \mathsf{ProtVer}& \text{update proposal protocol version}\\
      \mathsf{upId} & \mathsf{UProp}\to \mathsf{UpId}& \text{update proposal id}\\
      \mathsf{upParams} & \mathsf{UProp}\to \mathbb{\mathsf{PPMMap}}
                                           & \text{proposed parameters update}\\
      \mathsf{upSwVer} & \mathsf{UProp}\to \mathsf{SWVer}& \text{software-version update proposal}\\
      \mathsf{upSig} & \mathsf{UProp}\to \mathsf{Sig} & \text{update proposal signature}\\
      \mathsf{upSigData} & \mathsf{UProp}\to \mathsf{UpSD}& \text{update proposal signed data}\\
      \mathsf{upSTags} & \mathsf{UProp}\to \mathbb{P}~\mathsf{STag} & \text{update proposal system tags}\\
      \mathsf{upMdt} & \mathsf{UProp}\to \mathsf{Mdt}& \text{software update metadata}
    \end{array}
\end{equation*}$$

**Update proposals definitions**
The set of protocol parameters ($\mathsf{Ppm}$) is assumed to contain the following keys, some of which correspond with fields of the [`cardano-sl`](https://github.com/input-output-hk/cardano-sl/) 'BlockVersionData' structure:

- Maximum block size: $\mathit{maxBlockSize}$

- Maximum transaction size: $\mathit{maxTxSize}$

- Maximum header size: $\mathit{maxHeaderSize}$

- Maximum proposal size: $\mathit{maxProposalSize}$

- Transaction fee policy: $\mathit{txFeePolicy}$

- Script version: $\mathit{scriptVersion}$

- Update adoption threshold: $\mathit{upAdptThd}$. This represents the minimum percentage of the total number of genesis keys that have to endorse a protocol version to be able to become adopted. We use this parameter to determine the confirmation threshold as well. There is no corresponding parameter in the 'cardano-sl' protocol parameters, however we do have a soft-fork minimum threshold parameter ('srMinThd' in 'bvdSoftforkRule'). When divided by, $1\times 10^{15}$, it determines the minimum portion of the total stake that is needed for the adoption of a new protocol version. On mainnet, this number is set to $6 \times 10^{14}$, so the minimum portion becomes $0.6$. This number can be multiplied by the total number of genesis keys to obtain how many keys are needed to reach a majority.

- Update proposal time-to-live: $\mathit{upropTTL}$. This would correspond to the number of slots specified by 'bvdUpdateImplicit'. In 'cardano-sl' the rule was that after 'bvdUpdateImplicit' slots, if a proposal did not reach a majority of the votes, then if the proposal has more votes for than against it, then it will become implicitly accepted, or rejected otherwise. In this specification, we re-interpret the meaning of this parameter as the proposal time-to-live: if after the number of slots specified by 'bvdUpdateImplicit' the proposal does not reach a majority of approvals, the proposal is simply discarded. In the mainnet configuration ('mainnet-genesis.json') this value is set to $10000$, which corresponds with almost half of the total number of slots in an epoch.

The protocol parameters are formally defined in 2.


$$\begin{equation*}
    \begin{array}{rlr}
      \mathit{maxBlockSize} \mapsto \mathbb{N} & \mathsf{PPMMap} & \text{maximum block size}\\
      \mathit{maxTxSize} \mapsto \mathbb{N} & \mathsf{PPMMap} & \text{maximum transaction size}\\
      \mathit{maxHeaderSize} \mapsto \mathbb{N} & \mathsf{PPMMap} & \text{maximum header size}\\
      \mathit{scriptVersion} \mapsto \mathbb{N} & \mathsf{PPMMap} & \text{script version}\\
      \mathit{upAdptThd} \mapsto \mathbb{Q} & \mathsf{PPMMap} & \text{update proposal adoption threshold}\\
      \mathit{upropTTL} \mapsto \mathbb{\mathsf{Slot}} & \mathsf{PPMMap} & \text{update proposal time-to-live}\\
    \end{array}
\end{equation*}$$

**Protocol-parameters definitions**
## Update proposals registration
*Update proposals validity environments* $$\begin{equation*}
    \mathsf{UPVEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{pv} & \mathsf{ProtVer}& \text{adopted (current) protocol version}\\
        \mathit{pps} & \mathsf{PPMMap} & \text{adopted protocol parameters map}\\
        \mathit{avs} & \mathsf{ApName}\mapsto (\mathsf{ApVer}\times \mathsf{Slot} \times \mathsf{Mdt})
        & \text{application versions}\\
      \end{array}
    \right)
\end{equation*}$$ *Update proposals validity states* $$\begin{align*}
    & \mathsf{UPVState}\\
    & = \left(
      \begin{array}{rlr}
        \mathit{rpus} & \mathsf{UpId}\mapsto (\mathsf{ProtVer}\times \mathsf{PPMMap})
        & \text{registered protocol update proposals}\\
        \mathit{raus} & \mathsf{UpId}\mapsto (\mathsf{ApName}\times \mathsf{ApVer}\times \mathsf{Mdt})
        & \text{registered software update proposals}\\
      \end{array}
    \right)
\end{align*}$$ *Update proposals validity transitions* $$\begin{equation*}
    \mathit{\_} \vdash
    \mathit{\_} \xrightarrow[\mathsf{upv}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{UPVEnv}\times \mathsf{UPVState}\times \mathsf{UProp}\times \mathsf{UPVState})
\end{equation*}$$

**Update proposals validity transition-system types**
The rules in Figure 5 model the validity of a proposal:

- if an update proposal proposes a change in the protocol version, it must do so in a consistent manner:

  - The proposed version must be lexicographically bigger than the current version.

  - The major versions of the proposed and current version must differ in at most one.

  - If the proposed major version is equal to the current major version, then the proposed minor version must be incremented by one.

  - If the proposed major version is larger than the current major version, then the proposed minor version must be zero.

  - must be consistent with the current protocol parameters:

    - the proposal size must not exceed the maximum size specified by the current protocol parameters, (note that here we use function application to extract the value of the different protocol parameters, and a rule that uses a value of the map can be applied only if the function -e.g. $\mathit{pps}$- is defined for that value)

    - the proposed new maximum block size should be not greater than twice current maximum block size,

    - the maximum transaction size must be smaller than the maximum block size (this requirement is **crucial** for having every transaction fitting in a block, and

    - the proposed new script version can be incremented by at most 1.

  - must have a unique version among the current active proposals.

- if an update proposal proposes to increase the application version version ($\mathit{av}$) for a given application ($\mathit{an}$), then there should not be an active update proposal that proposes the same update.

Note that the rules in Figure 5 allow for an update that does not propose changes in the protocol version, or does not propose changes to the software version. However the update proposal must contain a change proposal in any of these two aspects. Also note that we do not allow for updating the protocol parameters without updating the protocol version. If an update in the protocol parameters does not cause a soft-fork we might use the alt version for that purpose.

In Rule eq:rule:up-av-validity we make use of the following abstract functions:

- $\mathsf{apNameValid}$, which checks that the name is an ASCII string 12 characters or less.

- $\mathsf{sTagValid}$, which checks that the name is an ASCII string of 10 characters or less.


*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{apNameValid} & \mathsf{ApName}\rightarrow \mathbb{B} & \text{validity checking for application name}\\
      \mathsf{sTagValid} & \mathsf{STag}\rightarrow \mathbb{B} & \text{validity checking for system tag}
    \end{array}
\end{equation*}$$

**Update proposal validity definitions**
:::: {.figure latex-placement="htb"}
$$\begin{equation}
    \label{eq:func:pv-can-follow}
    \begin{array}{r c l}
      \mathsf{pvCanFollow}~(\mathit{mj_p}, \mathit{mi_p}, \mathit{a_p})~(\mathit{mj_n}, \mathit{mi_n}, \mathit{a_n})
      & = & (\mathit{mj_p}, \mathit{mi_p}, \mathit{a_p}) < (\mathit{mj_n}, \mathit{mi_n}, \mathit{a_n})\\
      & \wedge & 0 \leq \mathit{mj_n} - \mathit{mj_p} \leq 1\\
      & \wedge & (\mathit{mj_p} = \mathit{mj_n} \Rightarrow \mathit{mi_p} + 1 = \mathit{mi_n}))\\
      & \wedge & (\mathit{mj_p} + 1 = \mathit{mj_n} \Rightarrow \mathit{mi_n} = 0)
    \end{array}
\end{equation}$$ $$\begin{equation}
    \label{eq:func:can-update}
    \begin{array}{l}
      \mathsf{canUpdate}~\mathit{pps}~\mathit{pps'}\\
      {\begin{array}{r c l}
         & = & \mathit{pps'}~\mathit{maxBlockSize} \leq 2\cdot\mathit{pps}~\mathit{maxBlockSize}\\
         & \wedge & \mathit{pps'}~\mathit{maxTxSize} < \mathit{pps'}~\mathit{maxBlockSize} \\
         & \wedge
             & 0 \leq
               \mathit{pps'}~\mathit{scriptVersion} - \mathit{pps}~\mathit{scriptVersion}
               \leq 1
       \end{array}}
    \end{array}
\end{equation}$$ $$\begin{equation}
    \label{eq:func:av-can-follow}
    \begin{array}{r c l}
      \mathsf{svCanFollow}~\mathit{avs}~(\mathit{an}, \mathit{av}) & =
      & (\mathit{an} \mapsto (\mathit{av_c}, \underline{\phantom{a}}, \underline{\phantom{a}}) \in \mathit{avs}
        \Rightarrow \mathit{av} = \mathit{av_c} + 1)\\
      & \wedge & (\mathit{an} \notin \dom~\mathit{avs} \Rightarrow \mathit{av} = 0 \vee \mathit{av} = 1)
    \end{array}
\end{equation}$$

**Update validity functions**
$$\begin{equation}
    \label{eq:rule:up-av-validity}
    \inference
    {
      (\mathit{an}, \mathit{av}) \mathrel{\mathop:}= \mathsf{upSwVer~\mathit{up}}
      & \mathsf{apNameValid}~\mathit{an}\\
      & \mathsf{svCanFollow}~\mathit{avs}~(\mathit{an}, \mathit{av})
      & (\mathit{an}, \underline{\phantom{a}}, \underline{\phantom{a}}) \notin \range~\mathit{raus}\\
      \forall \mathit{t} \in \mathsf{upSTags}~\mathit{up} \cdot \mathsf{sTagValid}~t
    }
    {
      {\left(
        \begin{array}{l}
          \mathit{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{raus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upsvv}]{}{up}
      {
        \left(
          \begin{array}{l}
            \mathit{raus} \unionoverrideRight \{ \mathsf{upId~\mathit{up}} \mapsto (\mathit{an}, \mathit{av}, \mathsf{upMdt~\mathit{up}})\}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-pv-validity}
    \inference
    {
      \mathit{pps'} \mathrel{\mathop:}= \mathit{pps} \unionoverrideRight \mathsf{upParams~\mathit{up}}
      & \mathsf{canUpdate}~\mathit{pps}~\mathit{pps'}\\
      & \mathit{nv} \mathrel{\mathop:}= \mathsf{upPV~\mathit{up}}
      & \mathsf{pvCanFollow}~\mathit{nv}~\mathit{pv}\\
      & \mathsf{upSize~\mathit{up}} \leq \mathit{pps}~\mathit{maxProposalSize}
      & \mathit{nv} \notin \dom~(\range~\mathit{rpus})
    }
    {
      {\left(
        \begin{array}{l}
          \mathit{pv}\\
          \mathit{pps}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{rpus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{uppvv}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            \mathit{rpus} \unionoverrideRight
            \{ \mathsf{upId~\mathit{up}} \mapsto (\mathit{nv}, \mathit{pps'}) \}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-validity-pu-nosu}
    \inference
    {
      {\left(
        \begin{array}{l}
          \mathit{pv}\\
          \mathit{pps}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{rpus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{uppvv}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            \mathit{rpus'}
          \end{array}
        \right)
      }
      &
      (\mathit{an}, \mathit{av}) \mathrel{\mathop:}= \mathsf{upSwVer~\mathit{up}} & \mathit{an} \mapsto (\mathit{av}, \_, \_) \in \mathit{avs}
    }
    {
      {\left(
        \begin{array}{l}
          \mathit{pv}\\
          \mathit{pps}\\
          \mathit{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{rpus}\\
            \mathit{raus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upv}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            \mathit{rpus'}\\
            \mathit{raus}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-validity-nopu-no}
    \inference
    {
      \mathit{pv} = \mathsf{upPV~\mathit{up}} & \mathsf{upParams~\mathit{up}} = \emptyset &
      {\left(
        \begin{array}{l}
          \mathit{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{raus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upsvv}]{}{up}
      {
        \left(
          \begin{array}{l}
            \mathit{raus'}
          \end{array}
        \right)
      }
    }
    {
      {\left(
        \begin{array}{l}
          \mathit{pv}\\
          \mathit{pps}\\
          \mathit{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{rpus}\\
            \mathit{raus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upv}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            \mathit{rpus}\\
            \mathit{raus'}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-validity-pu-su}
    \inference
    {
      {\left(
        \begin{array}{l}
          \mathit{pv}\\
          \mathit{pps}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{rpus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{uppvv}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            \mathit{rpus'}
          \end{array}
        \right)
      }
      &
      {
        \begin{array}{l}
          \mathit{avs}
        \end{array}
      }
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{raus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upsvv}]{}{up}
      {
        \left(
          \begin{array}{l}
            \mathit{raus'}
          \end{array}
        \right)
      }
    }
    {
      {\left(
        \begin{array}{l}
          \mathit{pv}\\
          \mathit{pps}\\
          \mathit{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{rpus}\\
            \mathit{raus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upv}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            \mathit{rpus'}\\
            \mathit{raus'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Update proposals validity rules**
The rule of Figure 7 models the registration of an update proposal:

- We consider the update proposal issuers to be the delegators of the key ($\mathit{vk}$) that is associated with the proposal under consideration ($\mathit{up}$).

- We check that the issuer of a proposal was delegated by a genesis key (which are in the domain of $\mathit{dms}$).

- the update proposal data (see the definition of $\mathsf{upSigdata}$) must be signed by the proposal issuer.


*Update proposals registration environments* $$\begin{equation*}
    \mathsf{UPREnv}=
    \left(
      \begin{array}{rlr}
        \mathit{pv} & \mathsf{ProtVer}& \text{adopted (current) protocol version}\\
        \mathit{pps} & \mathsf{PPMMap} & \text{adopted protocol parameters map}\\
        \mathit{avs} & \mathsf{ApName}\mapsto (\mathsf{ApVer}\times \mathsf{Slot} \times \mathsf{Mdt})
        & \text{application versions}\\
        \mathit{dms} & \mathsf{VKeyGen} \mapsto \mathsf{VKey} & \text{delegation map}\\
      \end{array}
    \right)
\end{equation*}$$ *Update proposals registration states* $$\begin{align*}
    & \mathsf{UPRState}= \\
    & \left(
      \begin{array}{rlr}
        \mathit{rpus} & \mathsf{UpId}\mapsto (\mathsf{ProtVer}\times \mathsf{PPMMap})
        & \text{registered update proposals}\\
        \mathit{raus} & \mathsf{UpId}\mapsto (\mathsf{ApName}\times \mathsf{ApVer}\times \mathsf{Mdt})
        & \text{registered software update proposals}
      \end{array}
    \right)
\end{align*}$$ *Update proposals registration transitions* $$\begin{equation*}
    \mathit{\_} \vdash
    \mathit{\_} \xrightarrow[\mathsf{upreg}]{}{\_} \mathit{\_}
    \subseteq \powerset (\mathsf{UPREnv}\times \mathsf{UPRState}\times \mathsf{UProp}\times \mathsf{UPRState})
\end{equation*}$$

**Update proposals registration transition-system types**
$$\begin{equation}
    \label{eq:rule:up-registration}
    \inference
    {
      {\left(
        \begin{array}{l}
          \mathit{pv}\\
          \mathit{pps}\\
          \mathit{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{rpus}\\
            \mathit{raus}\\
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{\hyperref[fig:rules:up-validity]{upv}}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            \mathit{rpus'}\\
            \mathit{raus'}\\
          \end{array}
        \right)
      }
      &
      \mathit{dms} \rhd \{\mathit{vk}\} \neq \emptyset\\
      \mathit{vk} \mathrel{\mathop:}= \mathsf{upIssuer~\mathit{up}} &
      \mathcal{V}_{\mathit{vk}}\lbrack\!\lbrack \mathit{\mathsf{upSigData~\mathit{up}}} \rbrack\!\rbrack_{(\mathsf{upSig~\mathit{up}})}
    }
    {
      {\left(
        \begin{array}{l}
          \mathit{pv}\\
          \mathit{pps}\\
          \mathit{avs}\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{rpus}\\
            \mathit{raus}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upreg}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            \mathit{rpus'}\\
            \mathit{raus'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Update registration rules**
## Voting on update proposals
*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{v} & \mathsf{Vote}& \text{vote on an update proposal}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{align*}
    & \mathsf{vCaster} \in \mathsf{Vote}\to \mathsf{VKey} & \text{caster of a vote}\\
    & \mathsf{vPropId} \in \mathsf{Vote}\to \mathsf{UpId}& \text{proposal id that is being voted}\\
    & \mathsf{vSig} \in \mathsf{Vote}\to \mathsf{Sig} & \text{vote signature}
\end{align*}$$

**Voting definitions**
*Voting environments* $$\begin{align*}
    & \mathsf{VREnv}
      = \left(
      \begin{array}{rlr}
        \mathit{rups} & \mathbb{P}~\mathsf{UpId}
        & \text{registered update proposals}\\
        \mathit{dms} & \mathsf{VKeyGen} \mapsto \mathsf{VKey} & \text{delegation map}
      \end{array}\right)
\end{align*}$$ *Voting states* $$\begin{align*}
    & \mathsf{VRState}
      = \left(
      \begin{array}{rlr}
        \mathit{vts} & \mathbb{P}~(\mathsf{UpId}\times \mathsf{VKeyGen}) & \text{votes}
      \end{array}\right)
\end{align*}$$ *Voting transitions* $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{addvote}]{}{\_} \_ \in
    \powerset (\mathsf{VREnv}\times \mathsf{VRState}\times \mathsf{Vote}\times \mathsf{VRState})
\end{equation*}$$

**Voting transition-system types**
In Rule eq:rule:voting:

- Only genesis keys can vote on an update proposal, although votes can be cast by delegates of these genesis keys.

- We count one vote per genesis key that delegated to the key that is casting the vote.

- The vote must refer to a registered update proposal.

- The proposal id must be signed by the key that is casting the vote.

- A given genesis key is only allowed to vote for a proposal once. This provision guards against replay attacks, where a third party may replay the vote in multiple blocks.


$$\begin{equation}
    \label{eq:rule:voting}
    \inference
    {
      \mathit{pid} \mathrel{\mathop:}= \mathsf{vPropId~\mathit{v}} & \mathit{vk} \mathrel{\mathop:}= \mathsf{vCaster~\mathit{v}} & \mathit{pid} \in \mathit{rups}\\
      \mathit{vts}_{\mathit{pid}} \mathrel{\mathop:}=
      \{ (\mathit{pid}, \mathit{vk_s}) \mid \mathit{vk_s} \mapsto \mathit{vk} \in \mathit{dms} \} &
      \mathit{vts}_{\mathit{pid}} \neq \emptyset &
      \mathit{vts}_{\mathit{pid}} \nsubseteq \mathit{vts} \\
      \mathcal{V}_{\mathit{vk}}\lbrack\!\lbrack \mathit{\mathit{pid}} \rbrack\!\rbrack_{(\mathsf{vSig~\mathit{v}})}\\
    }
    {
      {\left(
        \begin{array}{l}
          \mathit{rups}\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{vts}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{addvote}]{}{\mathit{v}}
      {
        \left(
          \begin{array}{l}
            \mathit{vts} \cup \mathit{vts}_{\mathit{pid}}\\
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Update voting rules**
*Vote registration environments* $$\begin{align*}
    & \mathsf{VEnv}
      = \left(
      \begin{array}{rlr}
        \mathit{s_n} & \mathsf{Slot} & \text{current slot number}\\
        \mathit{t} & \mathbb{N} & \text{confirmation threshold}\\
        \mathit{rups} & \mathbb{P}~\mathsf{UpId}
        & \text{registered update proposals}\\
        \mathit{dms} & \mathsf{VKeyGen} \mapsto \mathsf{VKey} & \text{delegation map}
      \end{array}\right)
\end{align*}$$ *Vote registration states* $$\begin{align*}
    & \mathsf{VState}
      = \left(
      \begin{array}{rlr}
        \mathit{cps} & \mathsf{UpId}\mapsto \mathsf{Slot} & \text{confirmed proposals}\\
        \mathit{vts} & \mathbb{P}~(\mathsf{UpId}\times \mathsf{VKeyGen}) & \text{votes}
      \end{array}\right)
\end{align*}$$ *Vote registration transitions* $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{UPVOTE}]{}{\_} \_ \in
    \powerset (\mathsf{VEnv}\times \mathsf{VState}\times \mathsf{Vote}\times \mathsf{VState})
\end{equation*}$$

**Vote registration transition-system types**
The rules in Figure 12 model the registration of a vote:

- The vote gets added to the list set of votes per-proposal ($\mathit{vts}$), via transition $\xrightarrow[\mathsf{addvote}]{}{}$.

- If the number of votes for the proposal $v$ refers to exceeds the confirmation threshold and this proposal was not confirmed already, then the proposal gets added to the set of confirmed proposals ($\mathit{cps}$). The reason why we check that the proposal was not already confirmed, is that we want to keep in $\mathit{cps}$ the earliest block number in which the proposal was confirmed.


$$\begin{equation}
    \label{eq:rule:up-no-confirmation}
    \inference
    {
      {\left(
        \begin{array}{l}
          \mathit{rups}\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{vts}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{\hyperref[fig:rules:voting]{addvote}}]{}{\mathit{v}}
      {
        \left(
          \begin{array}{l}
            \mathit{vts'}
          \end{array}
        \right)
      }\\
      \mathit{pid} \mathrel{\mathop:}= \mathsf{vPropId~\mathit{v}}
      & (\size{\{\mathit{pid}\} \lhd \mathit{vts'}} < t
      \vee \mathit{pid} \in \dom~\mathit{cps}
      )
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{t}\\
          \mathit{rups}\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{cps}\\
            \mathit{vts}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upvote}]{}{\mathit{v}}
      {
        \left(
          \begin{array}{l}
            \mathit{cps}\\
            \mathit{vts'}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-vote-reg}
    \inference
    {
      {\left(
        \begin{array}{l}
          \mathit{rups}\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{vts}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{\hyperref[fig:rules:voting]{addvote}}]{}{\mathit{v}}
      {
        \left(
          \begin{array}{l}
            \mathit{vts'}
          \end{array}
        \right)
      }\\
      \mathit{pid} \mathrel{\mathop:}= \mathsf{vPropId~\mathit{v}}
      & t \leq \size{\{\mathit{pid}\} \lhd \mathit{vts'}}
      & \mathit{pid} \notin \dom~\mathit{cps}
    }
    {
      {\left(
        \begin{array}{l}
          \mathit{s_n}\\
          \mathit{t}\\
          \mathit{rups}\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{cps}\\
            \mathit{vts}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upvote}]{}{\mathit{v}}
      {
        \left(
          \begin{array}{l}
            \mathit{cps} \unionoverrideRight  \{\mathit{pid} \mapsto s_n\} \\
            \mathit{vts'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Vote registration rules**
## Update-proposal endorsement
Figure 13 shows the types of the transition system associated with the registration of candidate protocol versions present in blocks. Some clarifications are in order:

- The $k$ parameter is used to determine when a confirmed proposal is stable. Given we are in a current slot $s_n$, all update proposals confirmed at or before slot $s_n - 2 \cdot k$ are deemed stable.

- For the sake of conciseness, we omit the types associated to the transitions $\xrightarrow[\mathsf{fads}]{}{}$, since they can be inferred from the types of the $\xrightarrow[\mathsf{upend}]{}{}$ transitions.


*Update-proposal endorsement environments* $$\begin{align*}
    & \mathsf{BVREnv}
      = \left(
      \begin{array}{rlr}
        \mathit{s_n} & \mathsf{Slot} & \text{current slot number}\\
        t & \mathbb{N} & \text{adoption threshold}\\
        \mathit{dms} & \mathsf{VKeyGen} \mapsto \mathsf{VKey} & \text{delegation map}\\
        \mathit{cps} & \mathsf{UpId}\mapsto \mathsf{Slot} & \text{confirmed proposals}\\
        \mathit{rpus} & \mathsf{UpId}\mapsto (\mathsf{ProtVer}\times \mathsf{PPMMap})
                             & \text{registered update proposals}\\
      \end{array}\right)
\end{align*}$$ *Update-proposal endorsement states* $$\begin{align*}
    & \mathsf{BVRState}
      = \left(
      \begin{array}{rlr}
        \mathit{fads} & (\mathsf{Slot} \times (\mathsf{ProtVer}\times \mathsf{PPMMap}))^{*}
        & \text{future protocol-version adoptions}\\
        \mathit{bvs} & \mathbb{P}~(\mathsf{ProtVer}\times \mathsf{VKeyGen})
        & \text{endorsement-key pairs}
      \end{array}\right)
\end{align*}$$ *Update-proposal endorsement transitions* $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{upend}]{}{\_} \_ \in
    \powerset (\mathsf{BVREnv}\times \mathsf{BVRState}
    \times (\mathsf{ProtVer}\times \mathsf{VKey}) \times \mathsf{BVRState})
\end{equation*}$$

**Update-proposal endorsement transition-system types**
Rules in 14 specify what happens when a block issuer signals that it is ready to upgrade to a new protocol version, given in the rule by $\mathit{bv}$:

- The set $\mathit{bvs}$, containing which genesis keys are (through their delegates) ready to adopt a given protocol version, is updated to reflect that the delegators of the block issuer (identified by its verifying key $\mathit{vk}$) are ready to upgrade to $\mathit{bv}$. Given a pair $(\mathit{pv}, ~\mathit{vk_s}) \in \mathit{bvs}$, we say that (the owner of) key $\mathit{vk_s}$ endorses the (proposed) protocol version $\mathit{pv}$. Note that before the decentralized era we do not count the total number nodes that are ready to upgrade to a new protocol version, but we count only nodes that are delegated by a genesis key. This allows us to implement a simple update mechanism while we transition to the decentralized era, where we will incorporate the results of ongoing research on a decentralized update mechanism.

- If there are a significant number of genesis keys that endorse $\mathit{bv}$ (the $t$ environment variable is used for this), there is a registered proposal (which are contained in $\mathit{rpus}$) which proposes to upgrade the protocol to version $\mathit{bv}$, and this update proposal was confirmed at least $2 \cdot k$ slots ago (to ensure stability of the confirmation), then we update the sequence of future protocol-version adoptions ($\mathit{fads}$).

- An element $(s_c, (\mathit{pv_c}, \mathit{pps_c})$ of $\mathit{fads}$ represents the fact that protocol version $\mathit{pv_c}$ got enough endorsements at slot $s_c$. An invariant that this sequence should maintain is that it is sorted in ascending order on slots and on protocol versions. This means that if we want to know what is the next candidate to adopt at a slot $s_k$ we only need to look at the last element of $[.., s_k] \lhd \mathit{fads}$. Since the list is sorted in ascending order on protocol versions, we know that this last element will contain the highest version to be adopted in the slot range $[.., s_k]$. The $\xrightarrow[\mathsf{fads}]{}{}$ transition rules take care of maintaining the aforementioned invariant. If a given protocol-version $\mathit{bv}$ got enough endorsements, but there is an adoption candidate as last element of $\mathit{fads}$ with a higher version, we simply discard $\mathit{bv}$.

- If a registered proposal cannot be adopted, we only register the endorsement.

- If a block version does not correspond to a registered or confirmed proposal, we just ignore the endorsement.


$$\begin{equation}
    \label{eq:rule:fads-add}
    \inference
    {
      (\underline{\phantom{a}} ; (\underline{\phantom{a}}, (\mathit{pv_c}, \underline{\phantom{a}})) \mathrel{\mathop:}= \mathit{fads}
      \wedge \mathit{pv_c} < bv) \vee \epsilon = fads
    }
    {
      {
        \left(
          \begin{array}{l}
            \mathit{fads}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{fads}]{}{(s_n, (\mathit{bv}, \mathit{pps_c}))}
      {
        \left(
          \begin{array}{l}
            \mathit{fads}; (s_n, (\mathit{bv}, \mathit{pps_c}))
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:fads-noop}
    \inference
    {
      \underline{\phantom{a}} ; (\underline{\phantom{a}}, (\mathit{pv_c}, \underline{\phantom{a}})) \mathrel{\mathop:}= \mathit{fads} & \mathit{bv} \leq \mathit{pv_c}
    }
    {
      {
        \left(
          \begin{array}{l}
            \mathit{fads}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{fads}]{}{(s_n, (\mathit{bv}, \mathit{pps_c}))}
      {
        \left(
          \begin{array}{l}
            \mathit{fads}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-up-invalid}
    \inference
    {
      \mathit{pid} \mapsto (\mathit{bv}, \underline{\phantom{a}}) \notin \mathit{rpus}
      \vee \mathit{pid} \notin \dom~(\mathit{cps} \rhd [.., s_n - 2 \cdot k])
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          t\\
          \mathit{dms}\\
          \mathit{cps}\\
          \mathit{rpus}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{fads}\\
            \mathit{bvs}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upend}]{}{(\mathit{bv}, \mathit{vk})}
      {
        \left(
          \begin{array}{l}
            \mathit{fads}\\
            \mathit{bvs}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-cant-adopt}
    \inference
    {
      \mathit{bvs'} \mathrel{\mathop:}= \mathit{bvs} \cup
      \{ (\mathit{bv}, \mathit{vk_s}) \mid \mathit{vk_s} \mapsto \mathit{vk} \in \mathit{dms} \}
      & \size{\{\mathit{bv}\} \lhd \mathit{bvs'}} < t\\
      \mathit{pid} \mapsto (\mathit{bv}, \underline{\phantom{a}}) \in \mathit{rpus}
      & \mathit{pid} \in \dom~(\mathit{cps} \rhd [.., s_n - 2 \cdot k])
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          t\\
          \mathit{dms}\\
          \mathit{cps}\\
          \mathit{rpus}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{fads}\\
            \mathit{bvs}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upend}]{}{(\mathit{bv}, \mathit{vk})}
      {
        \left(
          \begin{array}{l}
            \mathit{fads}\\
            \mathit{bvs'}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-canadopt}
    \inference
    {
      \mathit{bvs'} \mathrel{\mathop:}= \mathit{bvs} \cup
      \{ (\mathit{bv}, \mathit{vk_s}) \mid \mathit{vk_s} \mapsto \mathit{vk} \in \mathit{dms} \}
      & t \leq \size{\{\mathit{bv}\} \lhd \mathit{bvs'}}\\
      \mathit{pid} \mapsto (\mathit{bv}, \mathit{pps_c}) \in \mathit{rpus}
      & \mathit{pid} \in \dom~(\mathit{cps} \rhd [.., s_n - 2 \cdot k])\\
      (\mathit{fads}) \xrightarrow[\mathsf{fads}]{}{(s_n, (\mathit{bv}, \mathit{pps_c}))} (\mathit{fads'})
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          t\\
          \mathit{dms}\\
          \mathit{cps}\\
          \mathit{rpus}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{fads}\\
            \mathit{bvs}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upend}]{}{(\mathit{bv}, \mathit{vk})}
      {
        \left(
          \begin{array}{l}
            \mathit{fads'}\\
            \mathit{bvs'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Update-proposal endorsement rules**
## Deviations from the `cardano-sl` implementation
The current specification of the voting mechanism deviates from the actual implementation, although it should be backwards compatible with the latter. These deviations are required to simplify the voting and update mechanism removing unnecessary features for a simplified setting, which will use the OBFT consensus protocol with federated genesis key holders. This in turn, enables us to remove any accidental complexity that might have been introduced in the current implementation. The following subsections highlight the differences between the this specification and the current implementation.

### Positive votes
Genesis keys can only vote (positively) for an update proposal. In the current implementation stakeholders can vote for or against a proposal, which makes the voting logic more complex:

- there are more cases to consider

- the current voting validation rules allow voters to change their minds (by flipping their vote) at most once, which requires to keep track how a stake holder voted and how many times. Contrast this with Rule eq:rule:voting where we only need to keep track of the set of key-proposal-id's pairs.

### Alternative version numbers
Alternative version numbers are only lexicographically constrained. The current implementation seems to be dependent on the order in which the update proposals arrive: given a new update proposal $\mathit{up}$, if a set $X$ of update proposals with the same minor and major versions than $\mathit{up}$ exist, then the alternative version of $\mathit{up}$ has to be one more than the maximum alternative number of $X$. Not only this logic seems to be brittle since it depends on the order of arrival of the update proposals, but it requires a more complex check (which depends on state) to determine if a proposed version can follow the current one. By being more lenient on the alternative versions of update proposals we can simplify the version checking logic considerably.

### No implicit agreement
We do not model the implicit agreement rule. If a proposal does not get enough votes before the end of the voting period, then we simply discard it. At the moment it is not clear whether the implicit agreement rule is needed. Furthermore, in a non-federated setting, one could imagine an attack based on exploiting an implicit agreement rule, where the attacker would attempt to carry out a DoS attack on the parts of network that are likely to affect a proposal in a way that is undesirable for the attacker. Thus the explicit agreement seems to be a safer option.

### Adoption threshold
The current implementation adopts a proposal with version $\mathit{pv}$ if the portion of block issuers' stakes, which issued blocks with this version, is greater than the threshold given by:

    max spMinThd (spInitThd - (t - s) * spThdDecrement)

where:

- `spMinThd` is a minimum threshold required for adoption.

- `spInitThd` is an initial threshold.

- `spThdDecrement` is the decrement constant of the initial threshold.

In this specification we only make use of a minimum adoption threshold, represented by the protocol parameter $\mathit{upAdptThd}$ until it becomes clear why a dynamic alternative is needed.

### No checks on unlock-stake-epoch parameter
The rule of Figure eq:rule:up-pv-validity does not check the `bvdUnlockStakeEpoch` parameter, since it will have a different meaning in the handover phase: its use will be reserved for unlocking the Ouroboros-BFT logic in the software.

### Ignored attributes of proposals

In Figure 1 the types $\mathsf{UpdData}$, and $\mathsf{UpdAttrs}$ are only needed to model the fact that an update proposal must sign such data, however, we do not use them for any other purpose in this formalization.

### No limits on update proposals per-key per-epoch
In the current system a given genesis key can submit only one proposal per epoch. At the moment, it is not clear what are the advantages of such constraint:

- Genesis keys are controlled by the Cardano foundation.

- Even if a genesis key falls in the hands of the adversary, only one update proposal can be submitted per-block, and proposals have a time to live of $u$ blocks. So in the worst case scenario we are looking at an increase in the state size of the ledger proportional to $u$.

On the other hand, having that constraint in place brings some extra complexity in the specification, and therefore in the code that will implement it. Furthermore, in the current system, if an error is made in an update proposal, then if an amendment must be made within the current epoch, then a new update proposal must be submitted with a different key, which adds extra complexity for devops. In light of the preceding discussion, unless there is a benefit for restricting the number of times a genesis key can submit an update proposal, we opted for removing such a constraint in the current specification.

### Acceptance of blocks endorsing unconfirmed proposal updates
A consequence of enforcing the update rules in 14 is that a block that is endorsing an unconfirmed proposal gets accepted, although it will not have any effect on the update mechanism. It is not clear at this stage whether such a block should be rejected, therefore we have chosen to be lenient.

### Only genesis keys are counted for endorsement
The rules in 14 take only into account the endorsements by delegates of genesis keys. The reason for this is that implementing a more complex update mechanism depends on research that is in progress at the time of writing this specification. We decided to keep the update mechanism as simple as possible in the centralized era and incorporate the research results for the decentralized era at a later stage.
