# Blockchain interface
## Delegation interface
*Delegation interface environments* $$\begin{equation*}
    \mathsf{DIEnv}=
    \left(
      \begin{array}{rlr}
        \mathcal{K} & \mathbb{P}~\mathsf{VKeyGen} & \text{allowed delegators}\\
        \mathit{e} & \mathsf{Epoch} & \text{current epoch}\\
        \mathit{s} & \mathsf{Slot} & \text{current slot}
      \end{array}
    \right)
\end{equation*}$$

*Delegation interface states* $$\begin{equation*}
    \mathsf{DIState}
    = \left(
      \begin{array}{rlr}
        \mathit{dms} & \mathsf{VKeyGen} \mapsto \mathsf{VKey} & \text{delegation map}\\
        \mathit{dws} & \mathsf{VKeyGen} \mapsto \mathsf{Slot} & \text{when last delegation occurred}\\
        \mathit{sds} & (\mathsf{Slot} \times (\mathsf{VKeyGen} \times \mathsf{VKey}))^{*} & \text{scheduled delegations}\\
        \mathit{eks} & \mathbb{P}~(\mathsf{Epoch} \times \mathsf{VKeyGen}) & \text{key-epoch delegations}
      \end{array}
    \right)
\end{equation*}$$

*Delegation transitions* $$\begin{equation*}
    \_ \vdash \_ \xrightarrow[\mathsf{deleg}]{}{\_} \_ \in
    \powerset (\mathsf{DIEnv}\times \mathsf{DIState}\times \mathsf{DCert}^{*} \times \mathsf{DIState})
\end{equation*}$$

**Delegation interface transition-system types**
### Delegation interface rules
$$\begin{equation}
    \label{eq:rule:delegation-interface-init}
    \inference
    {
      {\left(\begin{array}{l}
       \mathcal{K}\\
        e\\
        s
      \end{array}\right)}
      \vdash
      \xrightarrow[\mathsf{\hyperref[eq:sdeleg-bootstrap]{sdeleg}}]{}{}
      {\left(
        \begin{array}{l}
          \mathit{sds_0}\\
          \mathit{eks_0}
        \end{array}
      \right)}
      &
      {
        \mathcal{K}
        \vdash
        \xrightarrow[\mathsf{\hyperref[eq:adeleg-bootstrap]{adeleg}}]{}{}
        \left(
          \begin{array}{l}
            \mathit{dms_0}\\
            \mathit{dws_0}
          \end{array}
        \right)
      }
    }
    {
      {\left(\begin{array}{l}
         \mathcal{K} \\
         e\\
         s
      \end{array}\right)}
      \vdash
      \xrightarrow[\mathsf{deleg}]{}{}
      {
        \left(
          \begin{array}{l}
            \mathit{dms_0}\\
            \mathit{dws_0}\\
            \mathit{sds_0}\\
            \mathit{eks_0}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:delegation-interface}
    \inference
    {
      {\left(\begin{array}{l}
         \mathcal{K} \\
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
      \xrightarrow[\mathsf{\hyperref[fig:rules:delegation-scheduling-seq]{sdelegs}}]{}{\Gamma}
      {
        \left(
          \begin{array}{l}
            \mathit{sds'}\\
            \mathit{eks'}
          \end{array}
        \right)
      }
      &
      {\begin{array}{l}
       \mathcal{K}
       \end{array}}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{dms}\\
            \mathit{dws}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{\hyperref[fig:rules:delegation-seq]{adelegs}}]{}{[.., s] \lhd \mathit{sds'}}
      {
        \left(
          \begin{array}{l}
            \mathit{dms'}\\
            \mathit{dws'}
          \end{array}
        \right)
      }
    }
    {
      {\left(\begin{array}{l}
         \mathcal{K} \\
         e\\
         s
      \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{dms}\\
            \mathit{dws}\\
            \mathit{sds}\\
            \mathit{eks}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{deleg}]{}{\Gamma}
      {
        \left(
          \begin{array}{l}
            \mathit{dms'}\\
            \mathit{dws'}\\
            \mathit{[s+1, ..]} \lhd \mathit{sds'}\\
            \mathit{[e, ..]} \lhd \mathit{eks'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Delegation interface rules**
## Update-proposals interface
Figure 4 defines the types of the transition systems related with the update-proposals interface. The acronyms in the transition labels have the following meaning:

UPIREG

:   Update-proposal-interface registration.

UPIVOTE

:   Update-proposal-interface vote.

UPIEND

:   Update-proposal-interface endorsement.

UPIEC

:   Update-proposal-interface epoch-change.

In these rules we make use of the abstract constant $\mathit{ngk}$, defined in 3, which determines the number of genesis keys:


*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{ngk} & \mathbb{N} & \text{number of genesis keys}\\
      \mathsf{firstSlot} & \in ~ \mathsf{Epoch} \to \mathsf{Slot}
      & \text{first slot of an epoch}
    \end{array}
\end{equation*}$$

**Update interface types and functions**
*Update-proposals interface environments* $$\begin{align*}
    & \mathsf{UPIEnv}
      = \left(
      \begin{array}{rlr}
        \mathit{s_n} & \mathsf{Slot} & \text{current slot number}\\
        \mathit{dms} & \mathsf{VKeyGen} \mapsto \mathsf{VKey} & \text{delegation map}
      \end{array}\right)
\end{align*}$$ *Update-proposals interface states* $$\begin{align*}
    & \mathsf{UPIState}= \\
    & \left(
      \begin{array}{rlr}
        (\mathit{pv}, \mathit{pps}) & \mathsf{ProtVer} \times \mathsf{PPMMap}
        & \text{current protocol information}\\
        \mathit{fads} & (\mathsf{Slot} \times (\mathsf{ProtVer} \times \mathsf{PPMMap}))^{*}
        & \text{future protocol version adoptions}\\
        \mathit{avs} & \mathsf{ApName} \mapsto (\mathsf{ApVer} \times \mathsf{Slot} \times \mathsf{Metadata})
        & \text{application versions}\\
        \mathit{rpus} & \mathsf{UPropId} \mapsto (\mathsf{ProtVer} \times \mathsf{PPMMap})
        & \text{registered protocol update proposals}\\
        \mathit{raus} & \mathsf{UPropId} \mapsto (\mathsf{ApName} \times \mathsf{ApVer} \times \mathsf{Metadata})
        & \text{registered software update proposals}\\
        \mathit{cps} & \mathsf{UPropId} \mapsto \mathsf{Slot} & \text{confirmed proposals}\\
        \mathit{vts} & \mathbb{P}~(\mathsf{UPropId} \times \mathsf{VKeyGen}) & \text{proposals votes}\\
        \mathit{bvs} & \mathbb{P}~(\mathsf{ProtVer} \times \mathsf{VKeyGen})
                           & \text{endorsement-key pairs}\\
        \mathit{pws} & \mathsf{UPropId} \mapsto \mathsf{Slot} & \text{proposal timestamps}
      \end{array}\right)\\
\end{align*}$$ *Update-proposals interface transitions* $$\begin{equation*}
    \begin{array}{rl}
      \_ \vdash \_ \xrightarrow[\mathsf{upireg}]{}{\_} \_ &
      \powerset (\mathsf{UPIEnv}\times \mathsf{UPIState}\times \mathsf{UProp} \times \mathsf{UPIState})\\
      \_ \vdash \_ \xrightarrow[\mathsf{upivote}]{}{\_} \_ &
      \powerset (\mathsf{UPIEnv}\times \mathsf{UPIState}\times \mathsf{Vote} \times \mathsf{UPIState})\\
      \_ \vdash \_ \xrightarrow[\mathsf{upiend}]{}{\_} \_ &
      \powerset (\mathsf{UPIEnv}\times \mathsf{UPIState}
      \times (\mathsf{ProtVer} \times \mathsf{VKey}) \times \mathsf{UPIState})\\
      \_ \vdash \_ \xrightarrow[\mathsf{upiec}]{}{} \_ &
      \powerset (\mathsf{Epoch} \times \mathsf{UPIState}\times \mathsf{UPIState})
    \end{array}
\end{equation*}$$

**Update-proposals interface transition-system types**
$$\begin{equation}
    \label{eq:rule:upi-reg-interface}
    \inference
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
      \xrightarrow[\mathsf{\hyperref[fig:rules:up-registration]{upreg}}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            \mathit{rpus'}\\
            \mathit{raus'}
          \end{array}
        \right)
      }
      &
      pws' \mathrel{\mathop:}= pws \unionoverrideRight \{ \mathsf{upId}~up \mapsto s_n\}
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus}\\
            \mathit{raus}\\
            \mathit{cps}\\
            \mathit{vts}\\
            \mathit{bvs}\\
            \mathit{pws}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upireg}]{}{\mathit{up}}
      {
        \left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus'}\\
            \mathit{raus'}\\
            \mathit{cps}\\
            \mathit{vts}\\
            \mathit{bvs}\\
            \mathit{pws'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Update-proposals registration rules**
Rule eq:rule:upi-vote models the effect of voting on an update proposal.


$$\begin{equation}
    \label{eq:rule:upi-vote}
    \inference
    {
      \mathit{upAdptThd} \mapsto q \in \mathit{pps}\\
      {\left(
        \begin{array}{l}
          s_n\\
          \floor{q \cdot \mathit{ngk}}\\
          \mathit{\dom~pws}\\
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
      \xrightarrow[\mathsf{\hyperref[fig:rules:up-vote-reg]{upvote}}]{}{\mathit{v}}
      {
        \left(
          \begin{array}{l}
            \mathit{cps'}\\
            \mathit{vts'}
          \end{array}
        \right)
      }
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus}\\
            \mathit{raus}\\
            \mathit{cps}\\
            \mathit{vts}\\
            \mathit{bvs}\\
            \mathit{pws}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upivote}]{}{\mathit{v}}
      {
        \left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus}\\
            \mathit{raus}\\
            \mathit{cps'}\\
            \mathit{vts'}\\
            \mathit{bvs}\\
            \mathit{pws}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Voting on update-proposals rules**
Figure 7 shows the different states in which a software proposal update might be: if valid, a software update proposal becomes active whenever it is included in a block. If the update proposal gets enough votes, then the corresponding software update proposal becomes confirmed. After this confirmation becomes stable, the new software version gets adopted. If the voting period ends without an update proposal being confirmed, then the corresponding software update proposal gets rejected. Protocol updates on the other hand, involve a slightly different logic, and the state transition diagram for these kind of updates is shown in Figure 13.


**State-transition diagram for software-updates**
A sequence of votes can be applied using $\xrightarrow[\mathsf{upivotes}]{}{}$ transitions. The inference rules for them are presented in 8. After applying a sequence of votes, proposals might get confirmed, which means that they will be added to the set $\mathit{cps'}$. In such case, the mapping of application names to their latest version known to the ledger will be updated to include the information about the confirmed proposals. Note that, unlike protocol updates, software updates take effect as soon as a proposal is confirmed (we cannot wait for stability since we need to preserve compatibility with the existing chain, where there are software update proposals that were adopted without waiting for $2\cdot k$ slots). In this rule, we also delete the confirmed id's from the set of registered application update proposals ($\mathit{raus}$), since this information is no longer needed once the application-name to software-version map ($\mathit{avs}$) is updated.

Also note that, unlike the rules of 11, we need not remove other update proposals that refer to the software names whose versions were changed in $\mathit{avs_{new}}$. The reason for this is that the range of $\mathit{raus}$ can contain only one pair of the form $(\mathit{an}, \underline{\phantom{a}}, \underline{\phantom{a}})$ for any given application name $\mathit{an}$ (see Rule eq:rule:up-av-validity).


$$\begin{equation}
    \label{eq:rule:apply-votes-base}
    \inference
    {
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      \mathit{us}
      \xrightarrow[\mathsf{applyvotes}]{}{\epsilon}
      \mathit{us}
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:apply-votes-ind}
    \inference
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      \mathit{us}
      \xrightarrow[\mathsf{applyvotes}]{}{\Gamma}
      \mathit{us'}
      &
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      \mathit{us'}
      \xrightarrow[\mathsf{\hyperref[fig:rules:upi-vote]{upivote}}]{}{v}
      \mathit{us''}
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      \mathit{us}
      \xrightarrow[\mathsf{applyvotes}]{}{\Gamma;v}
      \mathit{us''}
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:upivotes}
    \inference{
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {\left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus}\\
            \mathit{raus}\\
            \mathit{cps}\\
            \mathit{vts}\\
            \mathit{bvs}\\
            \mathit{pws}
          \end{array}
        \right)}
      \xrightarrow[\mathsf{applyvotes}]{}{\Gamma}
      {\left(
          \begin{array}{l}
            (\mathit{pv'}, \mathit{pps'})\\
            \mathit{fads'}\\
            \mathit{avs'}\\
            \mathit{rpus'}\\
            \mathit{raus'}\\
            \mathit{cps'}\\
            \mathit{vts'}\\
            \mathit{bvs'}\\
            \mathit{pws'}
          \end{array}
      \right)}\\
      %
      {\begin{array}{rl}
        \mathit{cfm_{raus}} & \dom~(cps') \lhd \mathit{raus'}\\
        \mathit{avs_{new}} & \{ \mathit{an} \mapsto (\mathit{av}, \mathit{s_n}, m)
        \mid (\mathit{an}, \mathit{av}, m) \in \mathit{cfm_{raus}} \}
      \end{array}}
    }{
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {\left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus}\\
            \mathit{raus}\\
            \mathit{cps}\\
            \mathit{vts}\\
            \mathit{bvs}\\
            \mathit{pws}
          \end{array}
      \right)}
      \xrightarrow[\mathsf{upivotes}]{}{\Gamma}
      {\left(
          \begin{array}{l}
            (\mathit{pv'}, \mathit{pps'})\\
            \mathit{fads'}\\
            \mathit{avs'} \unionoverrideRight \mathit{avs_{new}}\\
            \mathit{rpus'}\\
            \dom~(cps') \mathbin{\rlap{\lhd}/} \mathit{raus'}\\
            \mathit{cps'}\\
            \mathit{vts'}\\
            \mathit{bvs'}\\
            \mathit{pws'}
          \end{array}
      \right)}
    }
\end{equation}$$

**Applying multiple votes on update-proposals rules**
The interface rule for protocol-version endorsement makes use of the $\xrightarrow[\mathsf{upend}]{}{}$ transition, where we set the threshold for proposal adoption to: the number of genesis keys ($\mathit{ngk}$) times the minimum proportion of genesis keys that need to endorse an update proposal for it to become a candidate for adoption (given by the protocol parameter $\mathit{upAdptThd}$). In addition, the unconfirmed proposals that are older than $u$ blocks are removed from the parts of the state that hold:

- the registered protocol and software update proposals,

- the votes associated with the proposals,

- the set of endorsement-key pairs, and

- the block number in which proposals where added.

In Rule eq:rule:upi-pend, the set of proposal id's $\mathit{pid_{keep}}$ contains only those proposals that haven't expired yet or that are confirmed. Once a proposal $\mathit{up}$ is confirmed, it is removed from the set of confirmed proposals ($\mathit{cps}$) when a new a protocol version gets adopted (see Rule eq:rule:upi-ec-pv-change). The set of endorsement-key pairs is cleaned here as well as in the epoch change rule (Rule eq:rule:upi-ec-pv-change). The reason for this is that this set grows at each block, and it can get considerably large if no proposal gets adopted at the end of an epoch.


$$\begin{equation}
    \label{eq:rule:upi-pend}
    \inference
    {
      \mathit{upAdptThd} \mapsto q \in \mathit{pps} \\
      \left({
        \begin{array}{l}
          s_n\\
          \floor{q \cdot \mathit{ngk}}\\
          \mathit{dms}\\
          \mathit{cps}\\
          \mathit{rpus}
        \end{array}
      }\right)
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{fads}\\
            \mathit{bvs}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{\hyperref[fig:rules:up-end]{upend}}]{}{(\mathit{bv}, \mathit{vk})}
      {
        \left(
          \begin{array}{l}
            \mathit{fads'}\\
            \mathit{bvs'}
          \end{array}
        \right)
      }\\
      \mathit{upropTTL} \mapsto u \in \mathit{pps}\\
      {
        \begin{array}{rl}
          \mathit{pids_{keep}} & \dom~(pws \rhd [s_n - u, ..]) \cup \dom~\mathit{cps}\\
          \mathit{vs_{keep}} & \dom~(\range~\mathit{rpus'})\\
          \mathit{rpus'} & \mathit{pids_{keep}} \lhd \mathit{rpus}
        \end{array}
      }
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \mathit{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus}\\
            \mathit{raus}\\
            \mathit{cps}\\
            \mathit{vts}\\
            \mathit{bvs}\\
            \mathit{pws}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upiend}]{}{(\mathit{bv}, \mathit{vk})}
      {
        \left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads'}\\
            \mathit{avs}\\
            \mathit{rpus'}\\
            \mathit{pids_{keep}} \lhd \mathit{raus}\\
            \mathit{cps}\\
            \mathit{pids_{keep}} \lhd \mathit{vts}\\
            \mathit{vs_{keep}}  \lhd \mathit{bvs'}\\
            \mathit{pids_{keep}} \lhd \mathit{pws}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Proposal endorsement rules**
Rule eq:rule:upi-ec-pv-change models how the protocol-version and its parameters are changed depending on an epoch change signal. On an epoch change, this rule will pick a candidate that gathered enough endorsements at least $4 \cdot k$ slots ago. If a protocol-version candidate cannot gather enough endorsements $4 \cdot k$ slots before the end of an epoch, the proposal can only be adopted in the next epoch. The reason for the $4 \cdot
k$ slot delay is to allow a period between knowing when a proposal will be adopted, and the event of its being adopted. Since update proposals can and will make large changes to the way the chain operates, it is useful to be able to guarantee a window in which it is known that no update will take place. Figure 12 shows an example of a proposal being confirmed too late in an epoch, where it is not possible to get enough endorsements in the remaining window. In this Figure we take $k = 2$, and we assume $4$ endorsements are needed to consider a proposal as candidate for adoption. Note that, in the final state, we use union override to define the updated parameters ($\mathit{pps} \unionoverrideRight \mathit{pps'}$). This is because candidate proposal might only update some parameters of the protocol.

In Rule eq:rule:upi-ec-pv-change, when a new proposal gets adopted, all the state components that refer to protocol update proposals get emptied. The reason for this is that at the moment of registering a proposal, we evaluated it in a state where the protocol parameters that we used for this are no longer up to date (see for instance eq:func:can-update). For instance, assume we register a proposal $\mathit{up}$ which only changes the maximum transaction size to $x$, and the current block size is set to $x + 1$. Then, $\mathsf{canUpdate}$ holds, since the maximum transaction size is less than the maximum block size. If now a new proposal gets adopted that changes the maximum block size to $x - 1$, then this invalidates $\mathit{up}$ since $\mathsf{canUpdate}$ no longer holds.

If there are no candidates for adoption, then the state variables remain unaltered (Rule eq:rule:upi-ec-pv-unchanged).

Also note that the registered software-update proposals need not be cleaned here, since this is done either when a proposal gets confirmed or when it expires.


$$\begin{equation}
    \label{eq:rule:pvbump-change-epoch-only}
    \inference
    {
      [.., s_n - 4 \cdot k] \lhd \mathit{fads} = \epsilon
    }
    {
      {\left(\begin{array}{l}
         s_n\\
         \mathit{fads}
       \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{pv}, \mathit{pps}\\
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{pvbump}]{}{}
      {
        \left(
          \begin{array}{l}
            \mathit{pv}, \mathit{pps}\\
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:pvbump-change}
    \inference
    {
      \underline{\phantom{a}} ; (\underline{\phantom{a}} , (\mathit{pv_c}, \mathit{pps_c})) \mathrel{\mathop:}= [.., s_n - 4 \cdot k] \lhd \mathit{fads}
    }
    {
      {\left(\begin{array}{l}
         s_n\\
         \mathit{fads}
       \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{pv}, \mathit{pps}\\
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{pvbump}]{}{}
      {
        \left(
          \begin{array}{l}
            \mathit{pv_c}, \mathit{pps_c}\\
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Protocol version bump rules**
$$\begin{equation}
    \label{eq:rule:upi-ec-pv-unchanged}
    \inference
    {
      {\left(\begin{array}{l}
         \mathsf{firstSlot}~e_n\\
         \mathit{fads}
       \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{pv}, \mathit{pps}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{\hyperref[fig:rules:pvbump]{pvbump}}]{}{}
      {
        \left(
          \begin{array}{l}
            \mathit{pv'}, \mathit{pps'}\\
          \end{array}
        \right)
      } &\mathit{pv} = \mathit{pv'}
    }
    {
      (e_n)
      \vdash
      {
        \left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus}\\
            \mathit{raus}\\
            \mathit{cps}\\
            \mathit{vts}\\
            \mathit{bvs}\\
            \mathit{pws}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upiec}]{}{}
      {
        \left(
          \begin{array}{l}
            (\mathit{pv}, \mathit{pps})\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus}\\
            \mathit{raus}\\
            \mathit{cps}\\
            \mathit{vts}\\
            \mathit{bvs}\\
            \mathit{pws}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:upi-ec-pv-change}
    \inference
    {
      {\left(\begin{array}{l}
         \mathsf{firstSlot}~e_n\\
         \mathit{fads}
       \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{pv}, \mathit{pps}\\
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{\hyperref[fig:rules:pvbump]{pvbump}}]{}{}
      {
        \left(
          \begin{array}{l}
            \mathit{pv'}, \mathit{pps'}\\
          \end{array}
        \right)
      }
      & \mathit{pv} \neq \mathit{pv'}
    }
    {
      (e_n)
      \vdash
      {
        \left(
          \begin{array}{l}
            \mathit{(\mathit{pv}, \mathit{pps})}\\
            \mathit{fads}\\
            \mathit{avs}\\
            \mathit{rpus}\\
            \mathit{raus}\\
            \mathit{cps}\\
            \mathit{vts}\\
            \mathit{bvs}\\
            \mathit{pws}
          \end{array}
        \right)
      }
      \xrightarrow[\mathsf{upiec}]{}{}
      {
        \left(
          \begin{array}{l}
            (\mathit{pv'}, \mathit{pps'})\\
            \epsilon\\
            \mathit{avs}\\
            \emptyset\\
            \emptyset\\
            \emptyset\\
            \emptyset\\
            \emptyset\\
            \emptyset\\
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Block version adoption on epoch change rules**
**An update proposal confirmed too late**
Figure 13 shows the different states a protocol-update proposal can be in, and what causes the transitions between them.


**State-transition diagram for protocol-updates**