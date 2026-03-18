# Blockchain interface
## Delegation interface
*Delegation interface environments* $$\begin{equation*}
    \type{DIEnv}=
    \left(
      \begin{array}{rlr}
        \mathcal{K} & \powerset{\VKeyGen} & \text{allowed delegators}\\
        \var{e} & \Epoch & \text{current epoch}\\
        \var{s} & \Slot & \text{current slot}
      \end{array}
    \right)
\end{equation*}$$

*Delegation interface states* $$\begin{equation*}
    \type{DIState}
    = \left(
      \begin{array}{rlr}
        \var{dms} & \VKeyGen \mapsto \VKey & \text{delegation map}\\
        \var{dws} & \VKeyGen \mapsto \Slot & \text{when last delegation occurred}\\
        \var{sds} & \seqof{(\Slot \times (\VKeyGen \times \VKey))} & \text{scheduled delegations}\\
        \var{eks} & \powerset{(\Epoch \times \VKeyGen)} & \text{key-epoch delegations}
      \end{array}
    \right)
\end{equation*}$$

*Delegation transitions* $$\begin{equation*}
    \_ \vdash \_ \trans{deleg}{\_} \_ \in
    \powerset (\type{DIEnv}\times \type{DIState}\times \seqof{\DCert} \times \type{DIState})
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
      \trans{\hyperref[eq:sdeleg-bootstrap]{sdeleg}}{}
      {\left(
        \begin{array}{l}
          \var{sds_0}\\
          \var{eks_0}
        \end{array}
      \right)}
      &
      {
        \mathcal{K}
        \vdash
        \trans{\hyperref[eq:adeleg-bootstrap]{adeleg}}{}
        \left(
          \begin{array}{l}
            \var{dms_0}\\
            \var{dws_0}
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
      \trans{deleg}{}
      {
        \left(
          \begin{array}{l}
            \var{dms_0}\\
            \var{dws_0}\\
            \var{sds_0}\\
            \var{eks_0}
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
            \var{sds}\\
            \var{eks}
          \end{array}
        \right)
      }
      \trans{\hyperref[fig:rules:delegation-scheduling-seq]{sdelegs}}{\Gamma}
      {
        \left(
          \begin{array}{l}
            \var{sds'}\\
            \var{eks'}
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
            \var{dms}\\
            \var{dws}
          \end{array}
        \right)
      }
      \trans{\hyperref[fig:rules:delegation-seq]{adelegs}}{[.., s] \restrictdom \var{sds'}}
      {
        \left(
          \begin{array}{l}
            \var{dms'}\\
            \var{dws'}
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
            \var{dms}\\
            \var{dws}\\
            \var{sds}\\
            \var{eks}
          \end{array}
        \right)
      }
      \trans{deleg}{\Gamma}
      {
        \left(
          \begin{array}{l}
            \var{dms'}\\
            \var{dws'}\\
            \var{[s+1, ..]} \restrictdom \var{sds'}\\
            \var{[e, ..]} \restrictdom \var{eks'}
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

In these rules we make use of the abstract constant $\var{ngk}$, defined in 3{reference-type="ref+label" reference="fig:defs:upi"}, which determines the number of genesis keys:


*Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \var{ngk} & \mathbb{N} & \text{number of genesis keys}\\
      \fun{firstSlot} & \in ~ \Epoch \to \Slot
      & \text{first slot of an epoch}
    \end{array}
\end{equation*}$$

**Update interface types and functions**

*Update-proposals interface environments* $$\begin{align*}
    & \type{UPIEnv}
      = \left(
      \begin{array}{rlr}
        \var{s_n} & \Slot & \text{current slot number}\\
        \var{dms} & \VKeyGen \mapsto \VKey & \text{delegation map}
      \end{array}\right)
\end{align*}$$ *Update-proposals interface states* $$\begin{align*}
    & \type{UPIState}= \\
    & \left(
      \begin{array}{rlr}
        (\var{pv}, \var{pps}) & \ProtVer \times \PPMMap
        & \text{current protocol information}\\
        \var{fads} & \seqof{(\Slot \times (\ProtVer \times \PPMMap))}
        & \text{future protocol version adoptions}\\
        \var{avs} & \ApName \mapsto (\ApVer \times \Slot \times \Metadata)
        & \text{application versions}\\
        \var{rpus} & \UPropId \mapsto (\ProtVer \times \PPMMap)
        & \text{registered protocol update proposals}\\
        \var{raus} & \UPropId \mapsto (\ApName \times \ApVer \times \Metadata)
        & \text{registered software update proposals}\\
        \var{cps} & \UPropId \mapsto \Slot & \text{confirmed proposals}\\
        \var{vts} & \powerset{(\UPropId \times \VKeyGen)} & \text{proposals votes}\\
        \var{bvs} & \powerset{(\ProtVer \times \VKeyGen)}
                           & \text{endorsement-key pairs}\\
        \var{pws} & \UPropId \mapsto \Slot & \text{proposal timestamps}
      \end{array}\right)\\
\end{align*}$$ *Update-proposals interface transitions* $$\begin{equation*}
    \begin{array}{rl}
      \_ \vdash \_ \trans{upireg}{\_} \_ &
      \powerset (\type{UPIEnv}\times \type{UPIState}\times \UProp \times \type{UPIState})\\
      \_ \vdash \_ \trans{upivote}{\_} \_ &
      \powerset (\type{UPIEnv}\times \type{UPIState}\times \Vote \times \type{UPIState})\\
      \_ \vdash \_ \trans{upiend}{\_} \_ &
      \powerset (\type{UPIEnv}\times \type{UPIState}
      \times (\ProtVer \times \VKey) \times \type{UPIState})\\
      \_ \vdash \_ \trans{upiec}{} \_ &
      \powerset (\Epoch \times \type{UPIState}\times \type{UPIState})
    \end{array}
\end{equation*}$$

**Update-proposals interface transition-system types**

$$\begin{equation}
    \label{eq:rule:upi-reg-interface}
    \inference
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
      \trans{\hyperref[fig:rules:up-registration]{upreg}}{\var{up}}
      {
        \left(
          \begin{array}{l}
            \var{rpus'}\\
            \var{raus'}
          \end{array}
        \right)
      }
      &
      pws' \leteq pws \unionoverrideRight \{ \upId{up} \mapsto s_n\}
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus}\\
            \var{raus}\\
            \var{cps}\\
            \var{vts}\\
            \var{bvs}\\
            \var{pws}
          \end{array}
        \right)
      }
      \trans{upireg}{\var{up}}
      {
        \left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus'}\\
            \var{raus'}\\
            \var{cps}\\
            \var{vts}\\
            \var{bvs}\\
            \var{pws'}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Update-proposals registration rules**

Rule \[eq:rule:upi-vote\] models the effect of voting on an update proposal.


$$\begin{equation}
    \label{eq:rule:upi-vote}
    \inference
    {
      \var{upAdptThd} \mapsto q \in \var{pps}\\
      {\left(
        \begin{array}{l}
          s_n\\
          \floor{q \cdot \var{ngk}}\\
          \var{\dom~pws}\\
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
      \trans{\hyperref[fig:rules:up-vote-reg]{upvote}}{\var{v}}
      {
        \left(
          \begin{array}{l}
            \var{cps'}\\
            \var{vts'}
          \end{array}
        \right)
      }
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus}\\
            \var{raus}\\
            \var{cps}\\
            \var{vts}\\
            \var{bvs}\\
            \var{pws}
          \end{array}
        \right)
      }
      \trans{upivote}{\var{v}}
      {
        \left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus}\\
            \var{raus}\\
            \var{cps'}\\
            \var{vts'}\\
            \var{bvs}\\
            \var{pws}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Voting on update-proposals rules**

Figure 7 shows the different states in which a software proposal update might be: if valid, a software update proposal becomes active whenever it is included in a block. If the update proposal gets enough votes, then the corresponding software update proposal becomes confirmed. After this confirmation becomes stable, the new software version gets adopted. If the voting period ends without an update proposal being confirmed, then the corresponding software update proposal gets rejected. Protocol updates on the other hand, involve a slightly different logic, and the state transition diagram for these kind of updates is shown in Figure 13.


**State-transition diagram for software-updates**

A sequence of votes can be applied using $\trans{upivotes}{}$ transitions. The inference rules for them are presented in 8{reference-type="ref+label" reference="fig:rules:apply-votes"}. After applying a sequence of votes, proposals might get confirmed, which means that they will be added to the set $\var{cps'}$. In such case, the mapping of application names to their latest version known to the ledger will be updated to include the information about the confirmed proposals. Note that, unlike protocol updates, software updates take effect as soon as a proposal is confirmed (we cannot wait for stability since we need to preserve compatibility with the existing chain, where there are software update proposals that were adopted without waiting for $2\cdot k$ slots). In this rule, we also delete the confirmed id's from the set of registered application update proposals ($\var{raus}$), since this information is no longer needed once the application-name to software-version map ($\var{avs}$) is updated.

Also note that, unlike the rules of 11{reference-type="ref+label" reference="fig:rules:upi-ec"}, we need not remove other update proposals that refer to the software names whose versions were changed in $\var{avs_{new}}$. The reason for this is that the range of $\var{raus}$ can contain only one pair of the form $(\var{an}, \wcard, \wcard)$ for any given application name $\var{an}$ (see Rule \[eq:rule:up-av-validity\]).


$$\begin{equation}
    \label{eq:rule:apply-votes-base}
    \inference
    {
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      \var{us}
      \trans{applyvotes}{\epsilon}
      \var{us}
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:apply-votes-ind}
    \inference
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      \var{us}
      \trans{applyvotes}{\Gamma}
      \var{us'}
      &
      {\left(
        \begin{array}{l}
          s_n\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      \var{us'}
      \trans{\hyperref[fig:rules:upi-vote]{upivote}}{v}
      \var{us''}
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      \var{us}
      \trans{applyvotes}{\Gamma;v}
      \var{us''}
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:upivotes}
    \inference{
      {\left(
        \begin{array}{l}
          s_n\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {\left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus}\\
            \var{raus}\\
            \var{cps}\\
            \var{vts}\\
            \var{bvs}\\
            \var{pws}
          \end{array}
        \right)}
      \trans{applyvotes}{\Gamma}
      {\left(
          \begin{array}{l}
            (\var{pv'}, \var{pps'})\\
            \var{fads'}\\
            \var{avs'}\\
            \var{rpus'}\\
            \var{raus'}\\
            \var{cps'}\\
            \var{vts'}\\
            \var{bvs'}\\
            \var{pws'}
          \end{array}
      \right)}\\
      %
      {\begin{array}{rl}
        \var{cfm_{raus}} & \dom~(cps') \restrictdom \var{raus'}\\
        \var{avs_{new}} & \{ \var{an} \mapsto (\var{av}, \var{s_n}, m)
        \mid (\var{an}, \var{av}, m) \in \var{cfm_{raus}} \}
      \end{array}}
    }{
      {\left(
        \begin{array}{l}
          s_n\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {\left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus}\\
            \var{raus}\\
            \var{cps}\\
            \var{vts}\\
            \var{bvs}\\
            \var{pws}
          \end{array}
      \right)}
      \trans{upivotes}{\Gamma}
      {\left(
          \begin{array}{l}
            (\var{pv'}, \var{pps'})\\
            \var{fads'}\\
            \var{avs'} \unionoverrideRight \var{avs_{new}}\\
            \var{rpus'}\\
            \dom~(cps') \subtractdom \var{raus'}\\
            \var{cps'}\\
            \var{vts'}\\
            \var{bvs'}\\
            \var{pws'}
          \end{array}
      \right)}
    }
\end{equation}$$

**Applying multiple votes on update-proposals rules**

The interface rule for protocol-version endorsement makes use of the $\trans{upend}{}$ transition, where we set the threshold for proposal adoption to: the number of genesis keys ($\var{ngk}$) times the minimum proportion of genesis keys that need to endorse an update proposal for it to become a candidate for adoption (given by the protocol parameter $\var{upAdptThd}$). In addition, the unconfirmed proposals that are older than $u$ blocks are removed from the parts of the state that hold:

- the registered protocol and software update proposals,

- the votes associated with the proposals,

- the set of endorsement-key pairs, and

- the block number in which proposals where added.

In Rule \[eq:rule:upi-pend\], the set of proposal id's $\var{pid_{keep}}$ contains only those proposals that haven't expired yet or that are confirmed. Once a proposal $\var{up}$ is confirmed, it is removed from the set of confirmed proposals ($\var{cps}$) when a new a protocol version gets adopted (see Rule \[eq:rule:upi-ec-pv-change\]). The set of endorsement-key pairs is cleaned here as well as in the epoch change rule (Rule \[eq:rule:upi-ec-pv-change\]). The reason for this is that this set grows at each block, and it can get considerably large if no proposal gets adopted at the end of an epoch.


$$\begin{equation}
    \label{eq:rule:upi-pend}
    \inference
    {
      \var{upAdptThd} \mapsto q \in \var{pps} \\
      \left({
        \begin{array}{l}
          s_n\\
          \floor{q \cdot \var{ngk}}\\
          \var{dms}\\
          \var{cps}\\
          \var{rpus}
        \end{array}
      }\right)
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{fads}\\
            \var{bvs}
          \end{array}
        \right)
      }
      \trans{\hyperref[fig:rules:up-end]{upend}}{(\var{bv}, \var{vk})}
      {
        \left(
          \begin{array}{l}
            \var{fads'}\\
            \var{bvs'}
          \end{array}
        \right)
      }\\
      \var{upropTTL} \mapsto u \in \var{pps}\\
      {
        \begin{array}{rl}
          \var{pids_{keep}} & \dom~(pws \restrictrange [s_n - u, ..]) \cup \dom~\var{cps}\\
          \var{vs_{keep}} & \dom~(\range~\var{rpus'})\\
          \var{rpus'} & \var{pids_{keep}} \restrictdom \var{rpus}
        \end{array}
      }
    }
    {
      {\left(
        \begin{array}{l}
          s_n\\
          \var{dms}
        \end{array}
      \right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus}\\
            \var{raus}\\
            \var{cps}\\
            \var{vts}\\
            \var{bvs}\\
            \var{pws}
          \end{array}
        \right)
      }
      \trans{upiend}{(\var{bv}, \var{vk})}
      {
        \left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads'}\\
            \var{avs}\\
            \var{rpus'}\\
            \var{pids_{keep}} \restrictdom \var{raus}\\
            \var{cps}\\
            \var{pids_{keep}} \restrictdom \var{vts}\\
            \var{vs_{keep}}  \restrictdom \var{bvs'}\\
            \var{pids_{keep}} \restrictdom \var{pws}
          \end{array}
        \right)
      }
    }
\end{equation}$$

**Proposal endorsement rules**

Rule \[eq:rule:upi-ec-pv-change\] models how the protocol-version and its parameters are changed depending on an epoch change signal. On an epoch change, this rule will pick a candidate that gathered enough endorsements at least $4 \cdot k$ slots ago. If a protocol-version candidate cannot gather enough endorsements $4 \cdot k$ slots before the end of an epoch, the proposal can only be adopted in the next epoch. The reason for the $4 \cdot
k$ slot delay is to allow a period between knowing when a proposal will be adopted, and the event of its being adopted. Since update proposals can and will make large changes to the way the chain operates, it is useful to be able to guarantee a window in which it is known that no update will take place. Figure 12 shows an example of a proposal being confirmed too late in an epoch, where it is not possible to get enough endorsements in the remaining window. In this Figure we take $k = 2$, and we assume $4$ endorsements are needed to consider a proposal as candidate for adoption. Note that, in the final state, we use union override to define the updated parameters ($\var{pps} \unionoverrideRight \var{pps'}$). This is because candidate proposal might only update some parameters of the protocol.

In Rule \[eq:rule:upi-ec-pv-change\], when a new proposal gets adopted, all the state components that refer to protocol update proposals get emptied. The reason for this is that at the moment of registering a proposal, we evaluated it in a state where the protocol parameters that we used for this are no longer up to date (see for instance \[eq:func:can-update\]{reference-type="ref+label" reference="eq:func:can-update"}). For instance, assume we register a proposal $\var{up}$ which only changes the maximum transaction size to $x$, and the current block size is set to $x + 1$. Then, $\fun{canUpdate}$ holds, since the maximum transaction size is less than the maximum block size. If now a new proposal gets adopted that changes the maximum block size to $x - 1$, then this invalidates $\var{up}$ since $\fun{canUpdate}$ no longer holds.

If there are no candidates for adoption, then the state variables remain unaltered (Rule \[eq:rule:upi-ec-pv-unchanged\]).

Also note that the registered software-update proposals need not be cleaned here, since this is done either when a proposal gets confirmed or when it expires.


$$\begin{equation}
    \label{eq:rule:pvbump-change-epoch-only}
    \inference
    {
      [.., s_n - 4 \cdot k] \restrictdom \var{fads} = \epsilon
    }
    {
      {\left(\begin{array}{l}
         s_n\\
         \var{fads}
       \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{pv}, \var{pps}\\
          \end{array}
        \right)
      }
      \trans{pvbump}{}
      {
        \left(
          \begin{array}{l}
            \var{pv}, \var{pps}\\
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:pvbump-change}
    \inference
    {
      \wcard ; (\wcard , (\var{pv_c}, \var{pps_c})) \leteq [.., s_n - 4 \cdot k] \restrictdom \var{fads}
    }
    {
      {\left(\begin{array}{l}
         s_n\\
         \var{fads}
       \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{pv}, \var{pps}\\
          \end{array}
        \right)
      }
      \trans{pvbump}{}
      {
        \left(
          \begin{array}{l}
            \var{pv_c}, \var{pps_c}\\
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
         \fun{firstSlot}~e_n\\
         \var{fads}
       \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{pv}, \var{pps}
          \end{array}
        \right)
      }
      \trans{\hyperref[fig:rules:pvbump]{pvbump}}{}
      {
        \left(
          \begin{array}{l}
            \var{pv'}, \var{pps'}\\
          \end{array}
        \right)
      } &\var{pv} = \var{pv'}
    }
    {
      (e_n)
      \vdash
      {
        \left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus}\\
            \var{raus}\\
            \var{cps}\\
            \var{vts}\\
            \var{bvs}\\
            \var{pws}
          \end{array}
        \right)
      }
      \trans{upiec}{}
      {
        \left(
          \begin{array}{l}
            (\var{pv}, \var{pps})\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus}\\
            \var{raus}\\
            \var{cps}\\
            \var{vts}\\
            \var{bvs}\\
            \var{pws}
          \end{array}
        \right)
      }
    }
\end{equation}$$ $$\begin{equation}
    \label{eq:rule:upi-ec-pv-change}
    \inference
    {
      {\left(\begin{array}{l}
         \fun{firstSlot}~e_n\\
         \var{fads}
       \end{array}\right)}
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{pv}, \var{pps}\\
          \end{array}
        \right)
      }
      \trans{\hyperref[fig:rules:pvbump]{pvbump}}{}
      {
        \left(
          \begin{array}{l}
            \var{pv'}, \var{pps'}\\
          \end{array}
        \right)
      }
      & \var{pv} \neq \var{pv'}
    }
    {
      (e_n)
      \vdash
      {
        \left(
          \begin{array}{l}
            \var{(\var{pv}, \var{pps})}\\
            \var{fads}\\
            \var{avs}\\
            \var{rpus}\\
            \var{raus}\\
            \var{cps}\\
            \var{vts}\\
            \var{bvs}\\
            \var{pws}
          \end{array}
        \right)
      }
      \trans{upiec}{}
      {
        \left(
          \begin{array}{l}
            (\var{pv'}, \var{pps'})\\
            \epsilon\\
            \var{avs}\\
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
