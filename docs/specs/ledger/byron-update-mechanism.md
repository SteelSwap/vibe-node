'

# Update mechanism {#sec:update}

This section formalizes the update mechanism by which the protocol parameters get updated. This formalization is a simplification of the current update mechanism implemented in [`cardano-sl`](https://github.com/input-output-hk/cardano-sl/), and partially documented in:

- [Updater implementation](https://cardanodocs.com/technical/updater/)

- [Update mechanism](https://cardanodocs.com/cardano/update-mechanism/)

- [Update system consensus rules](https://github.com/input-output-hk/cardano-sl/blob/2a19d8ce2941b8e60f0208a5198943ec2ada1fd4/docs/block-processing/us.md)

The reason for formalizing a simplified version of the current implementation is that research work on blockchain update mechanisms is needed before introducing a more complex update logic. Since this specification is to be implemented in a federated setting, some of the constraints put in place in the current implementation are no longer relevant. Once the research work is ready, this specification can be extended to incorporate the research results.

## Update proposals {#sec:update-proposals}

The definitions used in the update mechanism rules are presented in [1](#fig:defs:update-proposals){reference-type="ref+label" reference="fig:defs:update-proposals"}. A system tag is used to identify the system for which the update is proposed (in practice this would be a string referring to an operating system; e.g. 'linux', 'win64', or 'mac32'). The software update metadata ($\type{Mdt}$) is any information required for performing an update such as hashes of software downloads. Note that the fact that the metadata is kept abstract in the specification does not mean that we allow any arbitrary metadata (in the actual implementation this abstract metadata would correspond to 'Map SystemTag UpdateData', were the 'SystemTag' corresponds with $\type{STag}$ and 'UpdateData' contains the software hash for a specific platform).

:::: {#fig:defs:update-proposals .figure latex-placement="htb"}
*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \var{up} & \type{UProp}& \text{update proposal}\\
      \var{p} & \type{Ppm}& \text{protocol parameter}\\
      \var{upd} & \type{UpdData} & \text{update data}\\
      \var{upa} & \type{UpdAttrs} & \text{update attributes}\\
      \var{an} & \type{ApName}& \text{application name}\\
      \var{t} & \type{STag}& \text{system tag}\\
      \var{m} & \type{Mdt}& \text{metadata}
    \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rlrlr}
      \var{s_n} & \Slot & n & \mathbb{N} & \text{slot number}\\
      \var{pv} & \type{ProtVer}& (\var{maj}, \var{min}, \var{alt})
      & (\mathbb{N}, \mathbb{N}, \mathbb{N}) & \text{protocol version}\\
      \var{pps} & \PPMMap & \var{pps} & \type{Ppm}\mapsto \Value
                                         & \text{protocol parameters map}\\
      \var{apv} & \type{ApVer}& n & \mathbb{N}\\
      \var{swv} & \type{SWVer}
      & (\var{an}, \var{av}) & \type{ApName}\times \type{ApVer}
      & \text{software version}\\
      \var{pb} & \type{UpSD}
      &
        {\left(\begin{array}{r l}
                 \var{pv}\\
                 \var{pps}\\
                 \var{swv}\\
                 \var{upd}\\
                 \var{upa}\\
               \end{array}\right)}
      & {
        \left(
        \begin{array}{l}
          \type{ProtVer}\\
          \PPMMap\\
          \type{SWVer}\\
          \type{UpdData}\\
          \type{UpdAttrs}\\
        \end{array}
                   \right)
                   }
               & \text{protocol update signed data}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \fun{upIssuer} & \type{UProp}\to \VKey & \text{update proposal issuer (delegate)}\\
      \fun{upSize} & \type{UProp}\to \mathbb{N} & \text{update proposal size}\\
      \fun{upPV} & \type{UProp}\to \type{ProtVer}& \text{update proposal protocol version}\\
      \fun{upId} & \type{UProp}\to \type{UpId}& \text{update proposal id}\\
      \fun{upParams} & \type{UProp}\to \mathbb{\PPMMap}
                                           & \text{proposed parameters update}\\
      \fun{upSwVer} & \type{UProp}\to \type{SWVer}& \text{software-version update proposal}\\
      \fun{upSig} & \type{UProp}\to \Sig & \text{update proposal signature}\\
      \fun{upSigData} & \type{UProp}\to \type{UpSD}& \text{update proposal signed data}\\
      \fun{upSTags} & \type{UProp}\to \powerset{\type{STag}} & \text{update proposal system tags}\\
      \fun{upMdt} & \type{UProp}\to \type{Mdt}& \text{software update metadata}
    \end{array}
\end{equation*}$$

::: caption
Update proposals definitions
:::
::::

The set of protocol parameters ($\type{Ppm}$) is assumed to contain the following keys, some of which correspond with fields of the [`cardano-sl`](https://github.com/input-output-hk/cardano-sl/) 'BlockVersionData' structure:

- Maximum block size: $\var{maxBlockSize}$

- Maximum transaction size: $\var{maxTxSize}$

- Maximum header size: $\var{maxHeaderSize}$

- Maximum proposal size: $\var{maxProposalSize}$

- Transaction fee policy: $\var{txFeePolicy}$

- Script version: $\var{scriptVersion}$

- Update adoption threshold: $\var{upAdptThd}$. This represents the minimum percentage of the total number of genesis keys that have to endorse a protocol version to be able to become adopted. We use this parameter to determine the confirmation threshold as well. There is no corresponding parameter in the 'cardano-sl' protocol parameters, however we do have a soft-fork minimum threshold parameter ('srMinThd' in 'bvdSoftforkRule'). When divided by, $1\times 10^{15}$, it determines the minimum portion of the total stake that is needed for the adoption of a new protocol version. On mainnet, this number is set to $6 \times 10^{14}$, so the minimum portion becomes $0.6$. This number can be multiplied by the total number of genesis keys to obtain how many keys are needed to reach a majority.

- Update proposal time-to-live: $\var{upropTTL}$. This would correspond to the number of slots specified by 'bvdUpdateImplicit'. In 'cardano-sl' the rule was that after 'bvdUpdateImplicit' slots, if a proposal did not reach a majority of the votes, then if the proposal has more votes for than against it, then it will become implicitly accepted, or rejected otherwise. In this specification, we re-interpret the meaning of this parameter as the proposal time-to-live: if after the number of slots specified by 'bvdUpdateImplicit' the proposal does not reach a majority of approvals, the proposal is simply discarded. In the mainnet configuration ('mainnet-genesis.json') this value is set to $10000$, which corresponds with almost half of the total number of slots in an epoch.

The protocol parameters are formally defined in [2](#fig:prot-params-defs){reference-type="ref+label" reference="fig:prot-params-defs"}.

:::: {#fig:prot-params-defs .figure latex-placement="ht"}
$$\begin{equation*}
    \begin{array}{rlr}
      \var{maxBlockSize} \mapsto \mathbb{N} & \PPMMap & \text{maximum block size}\\
      \var{maxTxSize} \mapsto \mathbb{N} & \PPMMap & \text{maximum transaction size}\\
      \var{maxHeaderSize} \mapsto \mathbb{N} & \PPMMap & \text{maximum header size}\\
      \var{scriptVersion} \mapsto \mathbb{N} & \PPMMap & \text{script version}\\
      \var{upAdptThd} \mapsto \mathbb{Q} & \PPMMap & \text{update proposal adoption threshold}\\
      \var{upropTTL} \mapsto \mathbb{\Slot} & \PPMMap & \text{update proposal time-to-live}\\
    \end{array}
\end{equation*}$$

::: caption
Protocol-parameters definitions
:::
::::

## Update proposals registration {#sec:update-proposals-registration}

:::: {#fig:ts-types:up-validity .figure latex-placement="htb"}
*Update proposals validity environments* $$\begin{equation*}
    \type{UPVEnv}=
    \left(
      \begin{array}{rlr}
        \var{pv} & \type{ProtVer}& \text{adopted (current) protocol version}\\
        \var{pps} & \PPMMap & \text{adopted protocol parameters map}\\
        \var{avs} & \type{ApName}\mapsto (\type{ApVer}\times \Slot \times \type{Mdt})
        & \text{application versions}\\
      \end{array}
    \right)
\end{equation*}$$ *Update proposals validity states* $$\begin{align*}
    & \type{UPVState}\\
    & = \left(
      \begin{array}{rlr}
        \var{rpus} & \type{UpId}\mapsto (\type{ProtVer}\times \PPMMap)
        & \text{registered protocol update proposals}\\
        \var{raus} & \type{UpId}\mapsto (\type{ApName}\times \type{ApVer}\times \type{Mdt})
        & \text{registered software update proposals}\\
      \end{array}
    \right)
\end{align*}$$ *Update proposals validity transitions* $$\begin{equation*}
    \var{\_} \vdash
    \var{\_} \trans{upv}{\_} \var{\_}
    \subseteq \powerset (\type{UPVEnv}\times \type{UPVState}\times \type{UProp}\times \type{UPVState})
\end{equation*}$$

::: caption
Update proposals validity transition-system types
:::
::::

The rules in Figure [5](#fig:rules:up-validity){reference-type="ref" reference="fig:rules:up-validity"} model the validity of a proposal:

- if an update proposal proposes a change in the protocol version, it must do so in a consistent manner:

  - The proposed version must be lexicographically bigger than the current version.

  - The major versions of the proposed and current version must differ in at most one.

  - If the proposed major version is equal to the current major version, then the proposed minor version must be incremented by one.

  - If the proposed major version is larger than the current major version, then the proposed minor version must be zero.

  - must be consistent with the current protocol parameters:

    - the proposal size must not exceed the maximum size specified by the current protocol parameters, (note that here we use function application to extract the value of the different protocol parameters, and a rule that uses a value of the map can be applied only if the function -e.g. $\var{pps}$- is defined for that value)

    - the proposed new maximum block size should be not greater than twice current maximum block size,

    - the maximum transaction size must be smaller than the maximum block size (this requirement is **crucial** for having every transaction fitting in a block, and

    - the proposed new script version can be incremented by at most 1.

  - must have a unique version among the current active proposals.

- if an update proposal proposes to increase the application version version ($\var{av}$) for a given application ($\var{an}$), then there should not be an active update proposal that proposes the same update.

Note that the rules in Figure [5](#fig:rules:up-validity){reference-type="ref" reference="fig:rules:up-validity"} allow for an update that does not propose changes in the protocol version, or does not propose changes to the software version. However the update proposal must contain a change proposal in any of these two aspects. Also note that we do not allow for updating the protocol parameters without updating the protocol version. If an update in the protocol parameters does not cause a soft-fork we might use the alt version for that purpose.

In Rule [\[eq:rule:up-av-validity\]](#eq:rule:up-av-validity){reference-type="ref" reference="eq:rule:up-av-validity"} we make use of the following abstract functions:

- $\fun{apNameValid}$, which checks that the name is an ASCII string 12 characters or less.

- $\fun{sTagValid}$, which checks that the name is an ASCII string of 10 characters or less.

:::: {#fig:defs:update-proposal-validity .figure latex-placement="htb"}
*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \fun{apNameValid} & \type{ApName}\rightarrow \mathbb{B} & \text{validity checking for application name}\\
      \fun{sTagValid} & \type{STag}\rightarrow \mathbb{B} & \text{validity checking for system tag}
    \end{array}
\end{equation*}$$

::: caption
Update proposal validity definitions
:::
::::

:::: {.figure latex-placement="htb"}
$$\begin{equation}
    \label{eq:func:pv-can-follow}
    \begin{array}{r c l}
      \fun{pvCanFollow}~(\var{mj_p}, \var{mi_p}, \var{a_p})~(\var{mj_n}, \var{mi_n}, \var{a_n})
      & = & (\var{mj_p}, \var{mi_p}, \var{a_p}) < (\var{mj_n}, \var{mi_n}, \var{a_n})\\
      & \wedge & 0 \leq \var{mj_n} - \var{mj_p} \leq 1\\
      & \wedge & (\var{mj_p} = \var{mj_n} \Rightarrow \var{mi_p} + 1 = \var{mi_n}))\\
      & \wedge & (\var{mj_p} + 1 = \var{mj_n} \Rightarrow \var{mi_n} = 0)
    \end{array}
\end{equation}$$ $$\begin{equation}
    \label{eq:func:can-update}
    \begin{array}{l}
      \fun{canUpdate}~\var{pps}~\var{pps'}\\
      {\begin{array}{r c l}
         & = & \var{pps'}~\var{maxBlockSize} \leq 2\cdot\var{pps}~\var{maxBlockSize}\\
         & \wedge & \var{pps'}~\var{maxTxSize} < \var{pps'}~\var{maxBlockSize} \\
         & \wedge
             & 0 \leq
               \var{pps'}~\var{scriptVersion} - \var{pps}~\var{scriptVersion}
               \leq 1
       \end{array}}
    \end{array}
\end{equation}$$ $$\begin{equation}
    \label{eq:func:av-can-follow}
    \begin{array}{r c l}
      \fun{svCanFollow}~\var{avs}~(\var{an}, \var{av}) & =
      & (\var{an} \mapsto (\var{av_c}, \wcard, \wcard) \in \var{avs}
        \Rightarrow \var{av} = \var{av_c} + 1)\\
      & \wedge & (\var{an} \notin \dom~\var{avs} \Rightarrow \var{av} = 0 \vee \var{av} = 1)
    \end{array}
\end{equation}$$

::: caption
Update validity functions
:::
::::

:::: {#fig:rules:up-validity .figure latex-placement="htb"}
$$\begin{equation}
    \label{eq:rule:up-av-validity}
    \inference
    {
      (\var{an}, \var{av}) \leteq \fun{upSwVer~\var{up}}
      & \fun{apNameValid}~\var{an}\\
      & \fun{svCanFollow}~\var{avs}~(\var{an}, \var{av})
      & (\var{an}, \wcard, \wcard) \notin \range~\var{raus}\\
      \forall \var{t} \in \fun{upSTags}~\var{up} \cdot \fun{sTagValid}~t
    }
    {
      {\left(
        \begin{array}{l}
          \var{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{raus}
          \end{array}
        \right)
      }
      \trans{upsvv}{up}
      {
        \left(
          \begin{array}{l}
            \var{raus} \unionoverrideRight \{ \fun{upId~\var{up}} \mapsto (\var{an}, \var{av}, \fun{upMdt~\var{up}})\}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-pv-validity}
    \inference
    {
      \var{pps'} \leteq \var{pps} \unionoverrideRight \fun{upParams~\var{up}}
      & \fun{canUpdate}~\var{pps}~\var{pps'}\\
      & \var{nv} \leteq \fun{upPV~\var{up}}
      & \fun{pvCanFollow}~\var{nv}~\var{pv}\\
      & \fun{upSize~\var{up}} \leq \var{pps}~\var{maxProposalSize}
      & \var{nv} \notin \dom~(\range~\var{rpus})
    }
    {
      {\left(
        \begin{array}{l}
          \var{pv}\\
          \var{pps}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{rpus}
          \end{array}
        \right)
      }
      \trans{uppvv}{\var{up}}
      {
        \left(
          \begin{array}{l}
            \var{rpus} \unionoverrideRight
            \{ \fun{upId~\var{up}} \mapsto (\var{nv}, \var{pps'}) \}
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
          \var{pv}\\
          \var{pps}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{rpus}
          \end{array}
        \right)
      }
      \trans{uppvv}{\var{up}}
      {
        \left(
          \begin{array}{l}
            \var{rpus'}
          \end{array}
        \right)
      }
      &
      (\var{an}, \var{av}) \leteq \fun{upSwVer~\var{up}} & \var{an} \mapsto (\var{av}, \_, \_) \in \var{avs}
    }
    {
      {\left(
        \begin{array}{l}
          \var{pv}\\
          \var{pps}\\
          \var{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{rpus}\\
            \var{raus}
          \end{array}
        \right)
      }
      \trans{upv}{\var{up}}
      {
        \left(
          \begin{array}{l}
            \var{rpus'}\\
            \var{raus}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-validity-nopu-no}
    \inference
    {
      \var{pv} = \fun{upPV~\var{up}} & \fun{upParams~\var{up}} = \emptyset &
      {\left(
        \begin{array}{l}
          \var{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{raus}
          \end{array}
        \right)
      }
      \trans{upsvv}{up}
      {
        \left(
          \begin{array}{l}
            \var{raus'}
          \end{array}
        \right)
      }
    }
    {
      {\left(
        \begin{array}{l}
          \var{pv}\\
          \var{pps}\\
          \var{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{rpus}\\
            \var{raus}
          \end{array}
        \right)
      }
      \trans{upv}{\var{up}}
      {
        \left(
          \begin{array}{l}
            \var{rpus}\\
            \var{raus'}
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
          \var{pv}\\
          \var{pps}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{rpus}
          \end{array}
        \right)
      }
      \trans{uppvv}{\var{up}}
      {
        \left(
          \begin{array}{l}
            \var{rpus'}
          \end{array}
        \right)
      }
      &
      {
        \begin{array}{l}
          \var{avs}
        \end{array}
      }
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{raus}
          \end{array}
        \right)
      }
      \trans{upsvv}{up}
      {
        \left(
          \begin{array}{l}
            \var{raus'}
          \end{array}
        \right)
      }
    }
    {
      {\left(
        \begin{array}{l}
          \var{pv}\\
          \var{pps}\\
          \var{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{rpus}\\
            \var{raus}
          \end{array}
        \right)
      }
      \trans{upv}{\var{up}}
      {
        \left(
          \begin{array}{l}
            \var{rpus'}\\
            \var{raus'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

::: caption
Update proposals validity rules
:::
::::

The rule of Figure [7](#fig:rules:up-registration){reference-type="ref" reference="fig:rules:up-registration"} models the registration of an update proposal:

- We consider the update proposal issuers to be the delegators of the key ($\var{vk}$) that is associated with the proposal under consideration ($\var{up}$).

- We check that the issuer of a proposal was delegated by a genesis key (which are in the domain of $\var{dms}$).

- the update proposal data (see the definition of $\fun{upSigdata}$) must be signed by the proposal issuer.

:::: {#fig:ts-types:up-registration .figure latex-placement="htb"}
*Update proposals registration environments* $$\begin{equation*}
    \type{UPREnv}=
    \left(
      \begin{array}{rlr}
        \var{pv} & \type{ProtVer}& \text{adopted (current) protocol version}\\
        \var{pps} & \PPMMap & \text{adopted protocol parameters map}\\
        \var{avs} & \type{ApName}\mapsto (\type{ApVer}\times \Slot \times \type{Mdt})
        & \text{application versions}\\
        \var{dms} & \VKeyGen \mapsto \VKey & \text{delegation map}\\
      \end{array}
    \right)
\end{equation*}$$ *Update proposals registration states* $$\begin{align*}
    & \type{UPRState}= \\
    & \left(
      \begin{array}{rlr}
        \var{rpus} & \type{UpId}\mapsto (\type{ProtVer}\times \PPMMap)
        & \text{registered update proposals}\\
        \var{raus} & \type{UpId}\mapsto (\type{ApName}\times \type{ApVer}\times \type{Mdt})
        & \text{registered software update proposals}
      \end{array}
    \right)
\end{align*}$$ *Update proposals registration transitions* $$\begin{equation*}
    \var{\_} \vdash
    \var{\_} \trans{upreg}{\_} \var{\_}
    \subseteq \powerset (\type{UPREnv}\times \type{UPRState}\times \type{UProp}\times \type{UPRState})
\end{equation*}$$

::: caption
Update proposals registration transition-system types
:::
::::

:::: {#fig:rules:up-registration .figure latex-placement="htb"}
$$\begin{equation}
    \label{eq:rule:up-registration}
    \inference
    {
      {\left(
        \begin{array}{l}
          \var{pv}\\
          \var{pps}\\
          \var{avs}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{rpus}\\
            \var{raus}\\
          \end{array}
        \right)
      }
      \trans{\hyperref[fig:rules:up-validity]{upv}}{\var{up}}
      {
        \left(
          \begin{array}{l}
            \var{rpus'}\\
            \var{raus'}\\
          \end{array}
        \right)
      }
      &
      \var{dms} \restrictrange \{\var{vk}\} \neq \emptyset\\
      \var{vk} \leteq \fun{upIssuer~\var{up}} &
      \mathcal{V}_{\var{vk}}\serialised{\fun{upSigData~\var{up}}}_{(\fun{upSig~\var{up}})}
    }
    {
      {\left(
        \begin{array}{l}
          \var{pv}\\
          \var{pps}\\
          \var{avs}\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{rpus}\\
            \var{raus}
          \end{array}
        \right)
      }
      \trans{upreg}{\var{up}}
      {
        \left(
          \begin{array}{l}
            \var{rpus'}\\
            \var{raus'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

::: caption
Update registration rules
:::
::::

## Voting on update proposals {#sec:voting-on-update-proposals}

:::: {#fig:defs:voting .figure latex-placement="htb"}
*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \var{v} & \type{Vote}& \text{vote on an update proposal}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{align*}
    & \fun{vCaster} \in \type{Vote}\to \VKey & \text{caster of a vote}\\
    & \fun{vPropId} \in \type{Vote}\to \type{UpId}& \text{proposal id that is being voted}\\
    & \fun{vSig} \in \type{Vote}\to \Sig & \text{vote signature}
\end{align*}$$

::: caption
Voting definitions
:::
::::

:::: {#fig:ts-types:voting .figure latex-placement="htb"}
*Voting environments* $$\begin{align*}
    & \type{VREnv}
      = \left(
      \begin{array}{rlr}
        \var{rups} & \powerset{\type{UpId}}
        & \text{registered update proposals}\\
        \var{dms} & \VKeyGen \mapsto \VKey & \text{delegation map}
      \end{array}\right)
\end{align*}$$ *Voting states* $$\begin{align*}
    & \type{VRState}
      = \left(
      \begin{array}{rlr}
        \var{vts} & \powerset{(\type{UpId}\times \VKeyGen)} & \text{votes}
      \end{array}\right)
\end{align*}$$ *Voting transitions* $$\begin{equation*}
    \_ \vdash \_ \trans{addvote}{\_} \_ \in
    \powerset (\type{VREnv}\times \type{VRState}\times \type{Vote}\times \type{VRState})
\end{equation*}$$

::: caption
Voting transition-system types
:::
::::

In Rule [\[eq:rule:voting\]](#eq:rule:voting){reference-type="ref" reference="eq:rule:voting"}:

- Only genesis keys can vote on an update proposal, although votes can be cast by delegates of these genesis keys.

- We count one vote per genesis key that delegated to the key that is casting the vote.

- The vote must refer to a registered update proposal.

- The proposal id must be signed by the key that is casting the vote.

- A given genesis key is only allowed to vote for a proposal once. This provision guards against replay attacks, where a third party may replay the vote in multiple blocks.

:::: {#fig:rules:voting .figure latex-placement="htb"}
$$\begin{equation}
    \label{eq:rule:voting}
    \inference
    {
      \var{pid} \leteq \fun{vPropId~\var{v}} & \var{vk} \leteq \fun{vCaster~\var{v}} & \var{pid} \in \var{rups}\\
      \var{vts}_{\var{pid}} \leteq
      \{ (\var{pid}, \var{vk_s}) \mid \var{vk_s} \mapsto \var{vk} \in \var{dms} \} &
      \var{vts}_{\var{pid}} \neq \emptyset &
      \var{vts}_{\var{pid}} \nsubseteq \var{vts} \\
      \mathcal{V}_{\var{vk}}\serialised{\var{pid}}_{(\fun{vSig~\var{v}})}\\
    }
    {
      {\left(
        \begin{array}{l}
          \var{rups}\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{vts}
          \end{array}
        \right)
      }
      \trans{addvote}{\var{v}}
      {
        \left(
          \begin{array}{l}
            \var{vts} \cup \var{vts}_{\var{pid}}\\
          \end{array}
        \right)
      }
    }
\end{equation}$$

::: caption
Update voting rules
:::
::::

:::: {#fig:ts-types:vote-reg .figure latex-placement="htb"}
*Vote registration environments* $$\begin{align*}
    & \type{VEnv}
      = \left(
      \begin{array}{rlr}
        \var{s_n} & \Slot & \text{current slot number}\\
        \var{t} & \mathbb{N} & \text{confirmation threshold}\\
        \var{rups} & \powerset{\type{UpId}}
        & \text{registered update proposals}\\
        \var{dms} & \VKeyGen \mapsto \VKey & \text{delegation map}
      \end{array}\right)
\end{align*}$$ *Vote registration states* $$\begin{align*}
    & \type{VState}
      = \left(
      \begin{array}{rlr}
        \var{cps} & \type{UpId}\mapsto \Slot & \text{confirmed proposals}\\
        \var{vts} & \powerset{(\type{UpId}\times \VKeyGen)} & \text{votes}
      \end{array}\right)
\end{align*}$$ *Vote registration transitions* $$\begin{equation*}
    \_ \vdash \_ \trans{UPVOTE}{\_} \_ \in
    \powerset (\type{VEnv}\times \type{VState}\times \type{Vote}\times \type{VState})
\end{equation*}$$

::: caption
Vote registration transition-system types
:::
::::

The rules in Figure [12](#fig:rules:up-vote-reg){reference-type="ref" reference="fig:rules:up-vote-reg"} model the registration of a vote:

- The vote gets added to the list set of votes per-proposal ($\var{vts}$), via transition $\trans{addvote}{}$.

- If the number of votes for the proposal $v$ refers to exceeds the confirmation threshold and this proposal was not confirmed already, then the proposal gets added to the set of confirmed proposals ($\var{cps}$). The reason why we check that the proposal was not already confirmed, is that we want to keep in $\var{cps}$ the earliest block number in which the proposal was confirmed.

:::: {#fig:rules:up-vote-reg .figure latex-placement="htb"}
$$\begin{equation}
    \label{eq:rule:up-no-confirmation}
    \inference
    {
      {\left(
        \begin{array}{l}
          \var{rups}\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{vts}
          \end{array}
        \right)
      }
      \trans{\hyperref[fig:rules:voting]{addvote}}{\var{v}}
      {
        \left(
          \begin{array}{l}
            \var{vts'}
          \end{array}
        \right)
      }\\
      \var{pid} \leteq \fun{vPropId~\var{v}}
      & (\size{\{\var{pid}\} \restrictdom \var{vts'}} < t
      \vee \var{pid} \in \dom~\var{cps}
      )
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \var{t}\\
          \var{rups}\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{cps}\\
            \var{vts}
          \end{array}
        \right)
      }
      \trans{upvote}{\var{v}}
      {
        \left(
          \begin{array}{l}
            \var{cps}\\
            \var{vts'}
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
          \var{rups}\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{vts}
          \end{array}
        \right)
      }
      \trans{\hyperref[fig:rules:voting]{addvote}}{\var{v}}
      {
        \left(
          \begin{array}{l}
            \var{vts'}
          \end{array}
        \right)
      }\\
      \var{pid} \leteq \fun{vPropId~\var{v}}
      & t \leq \size{\{\var{pid}\} \restrictdom \var{vts'}}
      & \var{pid} \notin \dom~\var{cps}
    }
    {
      {\left(
        \begin{array}{l}
          \var{s_n}\\
          \var{t}\\
          \var{rups}\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{cps}\\
            \var{vts}
          \end{array}
        \right)
      }
      \trans{upvote}{\var{v}}
      {
        \left(
          \begin{array}{l}
            \var{cps} \unionoverrideRight  \{\var{pid} \mapsto s_n\} \\
            \var{vts'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

::: caption
Vote registration rules
:::
::::

## Update-proposal endorsement {#sec:proposal-endorsement}

Figure [13](#fig:ts-types:up-end){reference-type="ref" reference="fig:ts-types:up-end"} shows the types of the transition system associated with the registration of candidate protocol versions present in blocks. Some clarifications are in order:

- The $k$ parameter is used to determine when a confirmed proposal is stable. Given we are in a current slot $s_n$, all update proposals confirmed at or before slot $s_n - 2 \cdot k$ are deemed stable.

- For the sake of conciseness, we omit the types associated to the transitions $\trans{fads}{}$, since they can be inferred from the types of the $\trans{upend}{}$ transitions.

:::: {#fig:ts-types:up-end .figure latex-placement="htb"}
*Update-proposal endorsement environments* $$\begin{align*}
    & \type{BVREnv}
      = \left(
      \begin{array}{rlr}
        \var{s_n} & \Slot & \text{current slot number}\\
        t & \mathbb{N} & \text{adoption threshold}\\
        \var{dms} & \VKeyGen \mapsto \VKey & \text{delegation map}\\
        \var{cps} & \type{UpId}\mapsto \Slot & \text{confirmed proposals}\\
        \var{rpus} & \type{UpId}\mapsto (\type{ProtVer}\times \PPMMap)
                             & \text{registered update proposals}\\
      \end{array}\right)
\end{align*}$$ *Update-proposal endorsement states* $$\begin{align*}
    & \type{BVRState}
      = \left(
      \begin{array}{rlr}
        \var{fads} & \seqof{(\Slot \times (\type{ProtVer}\times \PPMMap))}
        & \text{future protocol-version adoptions}\\
        \var{bvs} & \powerset{(\type{ProtVer}\times \VKeyGen)}
        & \text{endorsement-key pairs}
      \end{array}\right)
\end{align*}$$ *Update-proposal endorsement transitions* $$\begin{equation*}
    \_ \vdash \_ \trans{upend}{\_} \_ \in
    \powerset (\type{BVREnv}\times \type{BVRState}
    \times (\type{ProtVer}\times \VKey) \times \type{BVRState})
\end{equation*}$$

::: caption
Update-proposal endorsement transition-system types
:::
::::

Rules in [14](#fig:rules:up-end){reference-type="ref+label" reference="fig:rules:up-end"} specify what happens when a block issuer signals that it is ready to upgrade to a new protocol version, given in the rule by $\var{bv}$:

- The set $\var{bvs}$, containing which genesis keys are (through their delegates) ready to adopt a given protocol version, is updated to reflect that the delegators of the block issuer (identified by its verifying key $\var{vk}$) are ready to upgrade to $\var{bv}$. Given a pair $(\var{pv}, ~\var{vk_s}) \in \var{bvs}$, we say that (the owner of) key $\var{vk_s}$ endorses the (proposed) protocol version $\var{pv}$. Note that before the decentralized era we do not count the total number nodes that are ready to upgrade to a new protocol version, but we count only nodes that are delegated by a genesis key. This allows us to implement a simple update mechanism while we transition to the decentralized era, where we will incorporate the results of ongoing research on a decentralized update mechanism.

- If there are a significant number of genesis keys that endorse $\var{bv}$ (the $t$ environment variable is used for this), there is a registered proposal (which are contained in $\var{rpus}$) which proposes to upgrade the protocol to version $\var{bv}$, and this update proposal was confirmed at least $2 \cdot k$ slots ago (to ensure stability of the confirmation), then we update the sequence of future protocol-version adoptions ($\var{fads}$).

- An element $(s_c, (\var{pv_c}, \var{pps_c})$ of $\var{fads}$ represents the fact that protocol version $\var{pv_c}$ got enough endorsements at slot $s_c$. An invariant that this sequence should maintain is that it is sorted in ascending order on slots and on protocol versions. This means that if we want to know what is the next candidate to adopt at a slot $s_k$ we only need to look at the last element of $[.., s_k] \restrictdom \var{fads}$. Since the list is sorted in ascending order on protocol versions, we know that this last element will contain the highest version to be adopted in the slot range $[.., s_k]$. The $\trans{fads}{}$ transition rules take care of maintaining the aforementioned invariant. If a given protocol-version $\var{bv}$ got enough endorsements, but there is an adoption candidate as last element of $\var{fads}$ with a higher version, we simply discard $\var{bv}$.

- If a registered proposal cannot be adopted, we only register the endorsement.

- If a block version does not correspond to a registered or confirmed proposal, we just ignore the endorsement.

:::: {#fig:rules:up-end .figure latex-placement="htb"}
$$\begin{equation}
    \label{eq:rule:fads-add}
    \inference
    {
      (\wcard ; (\wcard, (\var{pv_c}, \wcard)) \leteq \var{fads}
      \wedge \var{pv_c} < bv) \vee \epsilon = fads
    }
    {
      {
        \left(
          \begin{array}{l}
            \var{fads}
          \end{array}
        \right)
      }
      \trans{fads}{(s_n, (\var{bv}, \var{pps_c}))}
      {
        \left(
          \begin{array}{l}
            \var{fads}; (s_n, (\var{bv}, \var{pps_c}))
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:fads-noop}
    \inference
    {
      \wcard ; (\wcard, (\var{pv_c}, \wcard)) \leteq \var{fads} & \var{bv} \leq \var{pv_c}
    }
    {
      {
        \left(
          \begin{array}{l}
            \var{fads}
          \end{array}
        \right)
      }
      \trans{fads}{(s_n, (\var{bv}, \var{pps_c}))}
      {
        \left(
          \begin{array}{l}
            \var{fads}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-up-invalid}
    \inference
    {
      \var{pid} \mapsto (\var{bv}, \wcard) \notin \var{rpus}
      \vee \var{pid} \notin \dom~(\var{cps} \restrictrange [.., s_n - 2 \cdot k])
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          t\\
          \var{dms}\\
          \var{cps}\\
          \var{rpus}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{fads}\\
            \var{bvs}
          \end{array}
        \right)
      }
      \trans{upend}{(\var{bv}, \var{vk})}
      {
        \left(
          \begin{array}{l}
            \var{fads}\\
            \var{bvs}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-cant-adopt}
    \inference
    {
      \var{bvs'} \leteq \var{bvs} \cup
      \{ (\var{bv}, \var{vk_s}) \mid \var{vk_s} \mapsto \var{vk} \in \var{dms} \}
      & \size{\{\var{bv}\} \restrictdom \var{bvs'}} < t\\
      \var{pid} \mapsto (\var{bv}, \wcard) \in \var{rpus}
      & \var{pid} \in \dom~(\var{cps} \restrictrange [.., s_n - 2 \cdot k])
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          t\\
          \var{dms}\\
          \var{cps}\\
          \var{rpus}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{fads}\\
            \var{bvs}
          \end{array}
        \right)
      }
      \trans{upend}{(\var{bv}, \var{vk})}
      {
        \left(
          \begin{array}{l}
            \var{fads}\\
            \var{bvs'}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:up-canadopt}
    \inference
    {
      \var{bvs'} \leteq \var{bvs} \cup
      \{ (\var{bv}, \var{vk_s}) \mid \var{vk_s} \mapsto \var{vk} \in \var{dms} \}
      & t \leq \size{\{\var{bv}\} \restrictdom \var{bvs'}}\\
      \var{pid} \mapsto (\var{bv}, \var{pps_c}) \in \var{rpus}
      & \var{pid} \in \dom~(\var{cps} \restrictrange [.., s_n - 2 \cdot k])\\
      (\var{fads}) \trans{fads}{(s_n, (\var{bv}, \var{pps_c}))} (\var{fads'})
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          t\\
          \var{dms}\\
          \var{cps}\\
          \var{rpus}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{fads}\\
            \var{bvs}
          \end{array}
        \right)
      }
      \trans{upend}{(\var{bv}, \var{vk})}
      {
        \left(
          \begin{array}{l}
            \var{fads'}\\
            \var{bvs'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

::: caption
Update-proposal endorsement rules
:::
::::

## Deviations from the `cardano-sl` implementation {#sec:update:deviation-actual-impl}

The current specification of the voting mechanism deviates from the actual implementation, although it should be backwards compatible with the latter. These deviations are required to simplify the voting and update mechanism removing unnecessary features for a simplified setting, which will use the OBFT consensus protocol with federated genesis key holders. This in turn, enables us to remove any accidental complexity that might have been introduced in the current implementation. The following subsections highlight the differences between the this specification and the current implementation.

### Positive votes {#sec:only-positive-votes}

Genesis keys can only vote (positively) for an update proposal. In the current implementation stakeholders can vote for or against a proposal, which makes the voting logic more complex:

- there are more cases to consider

- the current voting validation rules allow voters to change their minds (by flipping their vote) at most once, which requires to keep track how a stake holder voted and how many times. Contrast this with Rule [\[eq:rule:voting\]](#eq:rule:voting){reference-type="ref" reference="eq:rule:voting"} where we only need to keep track of the set of key-proposal-id's pairs.

### Alternative version numbers {#sec:alt-version-numbers-constraints}

Alternative version numbers are only lexicographically constrained. The current implementation seems to be dependent on the order in which the update proposals arrive: given a new update proposal $\var{up}$, if a set $X$ of update proposals with the same minor and major versions than $\var{up}$ exist, then the alternative version of $\var{up}$ has to be one more than the maximum alternative number of $X$. Not only this logic seems to be brittle since it depends on the order of arrival of the update proposals, but it requires a more complex check (which depends on state) to determine if a proposed version can follow the current one. By being more lenient on the alternative versions of update proposals we can simplify the version checking logic considerably.

### No implicit agreement {#sec:no-implicit-agreement}

We do not model the implicit agreement rule. If a proposal does not get enough votes before the end of the voting period, then we simply discard it. At the moment it is not clear whether the implicit agreement rule is needed. Furthermore, in a non-federated setting, one could imagine an attack based on exploiting an implicit agreement rule, where the attacker would attempt to carry out a DoS attack on the parts of network that are likely to affect a proposal in a way that is undesirable for the attacker. Thus the explicit agreement seems to be a safer option.

### Adoption threshold {#sec:adoption-threshold}

The current implementation adopts a proposal with version $\var{pv}$ if the portion of block issuers' stakes, which issued blocks with this version, is greater than the threshold given by:

    max spMinThd (spInitThd - (t - s) * spThdDecrement)

where:

- `spMinThd` is a minimum threshold required for adoption.

- `spInitThd` is an initial threshold.

- `spThdDecrement` is the decrement constant of the initial threshold.

In this specification we only make use of a minimum adoption threshold, represented by the protocol parameter $\var{upAdptThd}$ until it becomes clear why a dynamic alternative is needed.

### No checks on unlock-stake-epoch parameter {#sec:no-unlock-stake-epoch-check}

The rule of Figure [\[eq:rule:up-pv-validity\]](#eq:rule:up-pv-validity){reference-type="ref" reference="eq:rule:up-pv-validity"} does not check the `bvdUnlockStakeEpoch` parameter, since it will have a different meaning in the handover phase: its use will be reserved for unlocking the Ouroboros-BFT logic in the software.

### Ignored attributes of proposals

In Figure [1](#fig:defs:update-proposals){reference-type="ref" reference="fig:defs:update-proposals"} the types $\type{UpdData}$, and $\type{UpdAttrs}$ are only needed to model the fact that an update proposal must sign such data, however, we do not use them for any other purpose in this formalization.

### No limits on update proposals per-key per-epoch {#sec:no-up-limits}

In the current system a given genesis key can submit only one proposal per epoch. At the moment, it is not clear what are the advantages of such constraint:

- Genesis keys are controlled by the Cardano foundation.

- Even if a genesis key falls in the hands of the adversary, only one update proposal can be submitted per-block, and proposals have a time to live of $u$ blocks. So in the worst case scenario we are looking at an increase in the state size of the ledger proportional to $u$.

On the other hand, having that constraint in place brings some extra complexity in the specification, and therefore in the code that will implement it. Furthermore, in the current system, if an error is made in an update proposal, then if an amendment must be made within the current epoch, then a new update proposal must be submitted with a different key, which adds extra complexity for devops. In light of the preceding discussion, unless there is a benefit for restricting the number of times a genesis key can submit an update proposal, we opted for removing such a constraint in the current specification.

### Acceptance of blocks endorsing unconfirmed proposal updates {#sec:acceptance-of-uncofirmed-up-endorsements}

A consequence of enforcing the update rules in [14](#fig:rules:up-end){reference-type="ref+label" reference="fig:rules:up-end"} is that a block that is endorsing an unconfirmed proposal gets accepted, although it will not have any effect on the update mechanism. It is not clear at this stage whether such a block should be rejected, therefore we have chosen to be lenient.

### Only genesis keys are counted for endorsement {#sec:only-genesis-keys-count-for-endorsement}

The rules in [14](#fig:rules:up-end){reference-type="ref+label" reference="fig:rules:up-end"} take only into account the endorsements by delegates of genesis keys. The reason for this is that implementing a more complex update mechanism depends on research that is in progress at the time of writing this specification. We decided to keep the update mechanism as simple as possible in the centralized era and incorporate the research results for the decentralized era at a later stage.
