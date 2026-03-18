# Blockchain layer
This chapter introduces the view of the blockchain layer as required for the ledger. This includes in particular the information required for the epoch boundary and its rewards calculation as described in Section \[sec:epoch\]. It also covers the transitions that keep track of produced blocks in order to calculate rewards and penalties for stake pools.

The main transition rule is $\mathsf{CHAIN}$ which calls the subrules $\mathsf{NEWEPOCH}$ and $\mathsf{UPDN}$, $\mathsf{VRF}$ and $\mathsf{BBODY}$.

## Verifiable Random Functions (VRF)
*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \var{seed} & \Seed  & \text{seed for pseudo-random number generator}\\
      \var{prf} & \type{Proof}& \text{VRF proof}\\
    \end{array}
\end{equation*}$$ *Abstract functions ($T$ an arbitrary type)* $$\begin{equation*}
    \begin{array}{rlr}
      \seedOp & \Seed \to \Seed \to \Seed & \text{binary seed operation} \\
      \fun{vrf}_{\type{T}} ~  ~  & \SKey \to \Seed \to \type{T}\times\type{Proof}
                   & \text{verifiable random function} \\
                   %
      \fun{verifyVrf}_{\type{T}} ~  ~  ~ & \VKey \to \Seed \to \type{Proof}\times\type{T}\to \Bool
                           & \text{verify vrf proof} \\
                           %
    \end{array}
\end{equation*}$$ *Derived Types* $$\begin{align*}
    \type{PoolDistr}= \KeyHash_{pool} \mapsto \left([0, 1]\times\KeyHash_{vrf}\right)
      \text{ \hspace{1cm}stake pool distribution}
\end{align*}$$

*Constraints* $$\begin{align*}
    & \forall (sk, vk) \in \KeyPair,~ seed \in \Seed,~
    \fun{verifyVrf}_{T} ~ vk ~ seed ~\left(\fun{vrf}_{T} ~ sk ~ seed\right)
\end{align*}$$ *Constants* $$\begin{align*}
    & 0_{seed} \in \Seed & \text{neutral seed element} \\
    & \mathsf{Seed}_\ell\in \Seed & \text{leader seed constant} \\
    & \mathsf{Seed}_\eta\in \Seed & \text{nonce seed constant}\\
\end{align*}$$

**VRF definitions**

## Block Definitions
*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \var{h} & \type{HashHeader}& \text{hash of a block header}\\
      \var{hb} & \type{HashBBody}& \text{hash of a block body}\\
      \var{bn} & \BlockNo & \text{block number}\\
    \end{array}
\end{equation*}$$ *Operational Certificate* $$\begin{equation*}
    \type{OCert}=
    \left(
      \begin{array}{rlr}
        \var{vk_{hot}} & \VKeyEv & \text{operational (hot) key}\\
        \var{n} & \N & \text{certificate issue number}\\
        c_0 & \KESPeriod & \text{start KES period}\\
        \sigma & \Sig & \text{cold key signature}\\
      \end{array}
    \right)
\end{equation*}$$ *Block Header Body* $$\begin{equation*}
    \type{BHBody}=
    \left(
      \begin{array}{rlr}
        \var{prev} & \type{HashHeader}^? & \text{hash of previous block header}\\
        \var{vk} & \VKey & \text{block issuer}\\
        \var{vrfVk} & \VKey & \text{VRF verification key}\\
        \var{slot} & \Slot & \text{block slot}\\
        \eta & \Seed & \text{nonce}\\
        \var{prf}_{\eta} & \type{Proof}& \text{nonce proof}\\
        \ell & \unitInterval & \text{leader election value}\\
        \var{prf_{\ell}} & \type{Proof}& \text{leader election proof}\\
        \var{bsize} & \N & \text{size of the block body}\\
        \var{bhash} & \type{HashBBody}& \text{block body hash}\\
        \var{oc} & \type{OCert}& \text{operational certificate}\\
        \var{pv} & \ProtVer & \text{protocol version}\\
      \end{array}
    \right)
\end{equation*}$$ *Block Types* $$\begin{equation*}
    \begin{array}{rll}
      \var{bh}
      & \type{BHeader}
      & \type{BHBody}\times \Sig
      \\
      \var{b}
      & \Block
      & \type{BHeader}\times \seqof{\Tx}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \fun{bhHash}~ \var{} & \type{BHeader}\to \type{HashHeader}
                   & \text{hash of a block header} \\
      \fun{bHeaderSize}~ \var{} & \type{BHeader}\to \N
                   & \text{size of a block header} \\
      \fun{bBodySize}~ \var{} & \seqof{\Tx} \to \N
                   & \text{size of a block body} \\
      \fun{slotToSeed}~ \var{} & \Slot \to \Seed
                    & \text{convert a slot to a seed} \\
      \fun{prevHashToNonce}~ \var{} & \type{HashHeader}^? \to \Seed
                    & \text{convert an optional header hash to a seed} \\
      \fun{bbodyhash} & \seqof{\Tx} \to \type{HashBBody}\\
    \end{array}
\end{equation*}$$ *Accessor Functions* $$\begin{equation*}
    \begin{array}{rlrlr}
      \fun{bheader} & \Block \to \type{BHeader}&
      \fun{bhbody} & \type{BHeader}\to \type{BHBody}\\
      \fun{hsig} & \type{BHeader}\to \Sig &
      \fun{bbody} & \Block \to \seqof{\Tx} \\
      \fun{bvkcold} & \type{BHBody}\to \VKey &
      \fun{bvkvrf} & \type{BHBody}\to \VKey \\
      \fun{bprev} & \type{BHBody}\to \type{HashHeader}^? &
      \fun{bslot} & \type{BHBody}\to \Slot \\
      \fun{bblockno} & \type{BHBody}\to \BlockNo &
      \fun{bnonce} & \type{BHBody}\to \Seed \\
      \fun{\fun{bprf}_{n}~\var{}} & \type{BHBody}\to \type{Proof}&
      \fun{bleader} & \type{BHBody}\to \N \\
      \fun{\fun{bprf}_{\ell}~\var{}} & \type{BHBody}\to \type{Proof}&
      \fun{hBbsize} & \type{BHBody}\to \N \\
      \fun{bhash} & \type{BHBody}\to \type{HashBBody}&
      \fun{bocert} & \type{BHBody}\to \type{OCert}\\
    \end{array}
\end{equation*}$$

**Block Definitions**

## MIR Transition
The transition which moves the instantaneous rewards is $\mathsf{MIR}$. Figure 3 defines the types for the transition. It has no environment or signal, and the state is $\EpochState$.


*MIR Transitions* $$\begin{equation*}
    \vdash \var{\_} \trans{mir}{} \var{\_} \subseteq
    \powerset (\EpochState \times \EpochState)
\end{equation*}$$

**MIR transition-system types**

Figure 4 defines the MIR state transition.

If the reserve and treasury pots are large enough to cover the sum of the corresponding instantaneous rewards, the reward accounts are increased by the appropriate amount and the two pots are decreased appropriately. In either case, if the pots are large enough or not, we reset both of the instantaneous reward mappings back to the empty mapping.


$$\begin{equation}
\label{eq:mir}
    \inference[MIR]
    {
      (\var{rewards},~\var{delegations},~
      \var{ptrs},~\var{fGenDelegs},~\var{genDelegs},~\var{i_{rwd}})
        \leteq \var{ds}
      \\
      (\var{treasury},~\var{reserves})\leteq\var{acnt}
      &
      (\var{irReserves},~\var{irTreasury})\leteq\var{i_{rwd}}
      \\~\\
      \var{irwdR}\leteq
        \left\{
        \fun{addr_{rwd}}~\var{hk}\mapsto\var{val}
        ~\vert~\var{hk}\mapsto\var{val}\in(\dom{rewards})\restrictdom\var{irReserves}
        \right\}
      \\
      \var{irwdT}\leteq
        \left\{
        \fun{addr_{rwd}}~\var{hk}\mapsto\var{val}
        ~\vert~\var{hk}\mapsto\var{val}\in(\dom{rewards})\restrictdom\var{irTreasury}
        \right\}
      \\~\\
      \var{totR}\leteq\sum\limits_{\wcard\mapsto v\in\var{irwdR}}v
      &
      \var{totT}\leteq\sum\limits_{\wcard\mapsto v\in\var{irwdT}}v
      \\
      \var{totR}\leq\var{reserves}
      &
      \var{totT}\leq\var{treasury}
      \\~\\
      \var{rewards'}\leteq\var{rewards}\unionoverridePlus\var{irwdR}\unionoverridePlus\var{irwdT}
      \\
      \var{ds'} \leteq
      (\varUpdate{\var{rewards}'},~\var{delegations},~
      \var{ptrs},~\var{fGenDelegs},~\var{genDelegs},
      ~(\varUpdate{\emptyset},~\varUpdate{\emptyset}))
    }
    {
      \vdash
      {\left(\begin{array}{c}
            \var{acnt} \\
            \var{ss} \\
            (\var{us},~(\var{ds},~\var{ps})) \\
            \var{prevPP} \\
            \var{pp} \\
      \end{array}\right)}
      \trans{mir}{}
      {\left(\begin{array}{c}
            \varUpdate{(\varUpdate{\var{treasury}-\var{totT}},~\varUpdate{\var{reserves}-\var{totR}})} \\
            \var{ss} \\
            (\var{us},~(\varUpdate{\var{ds'}},~\var{ps})) \\
            \var{prevPP} \\
            \var{pp} \\
      \end{array}\right)}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:mir-skip}
    \inference[MIR-Skip]
    {
      (\var{rewards},~\var{delegations},~
      \var{ptrs},~\var{fGenDelegs},~\var{genDelegs},~\var{i_{rwd}})
        \leteq \var{ds}
      \\
      (\var{treasury},~\var{reserves})\leteq\var{acnt}
      &
      (\var{irReserves},~\var{irTreasury})\leteq\var{i_{rwd}}
      \\~\\
      \var{irwdR}\leteq
        \left\{
        \fun{addr_{rwd}}~\var{hk}\mapsto\var{val}
        ~\vert~\var{hk}\mapsto\var{val}\in(\dom{rewards})\restrictdom\var{irReserves}
        \right\}
      \\
      \var{irwdT}\leteq
        \left\{
        \fun{addr_{rwd}}~\var{hk}\mapsto\var{val}
        ~\vert~\var{hk}\mapsto\var{val}\in(\dom{rewards})\restrictdom\var{irTreasury}
        \right\}
      \\~\\
      \var{totR}\leteq\sum\limits_{\wcard\mapsto v\in\var{irwdR}}v
      &
      \var{totT}\leteq\sum\limits_{\wcard\mapsto v\in\var{irwdT}}v
      \\
      \var{totR}>\var{reserves}~\lor~\var{totT}>\var{treasury}
      \\~\\
      \var{ds'} \leteq
      (\var{rewards},~\var{delegations},~
      \var{ptrs},~\var{fGenDelegs},~\var{genDelegs},
      ~(\varUpdate{\emptyset},~\varUpdate{\emptyset}))
    }
    {
      \vdash
      {\left(\begin{array}{c}
            \var{acnt} \\
            \var{ss} \\
            (\var{us},~(\var{ds},~\var{ps})) \\
            \var{prevPP} \\
            \var{pp} \\
      \end{array}\right)}
      \trans{mir}{}
      {\left(\begin{array}{c}
            \var{acnt} \\
            \var{ss} \\
            (\var{us},~(\varUpdate{\var{ds'}},~\var{ps})) \\
            \var{prevPP} \\
            \var{pp} \\
      \end{array}\right)}
    }
\end{equation}$$

**MIR rules**

## New Epoch Transition
For the transition to a new epoch ($\mathsf{NEWEPOCH}$), the environment is given in Figure 5, it consists of

- The current slot.

- The set of genesis keys.

The new epoch state is given in Figure 5, it consists of

- The number of the last epoch.

- The information about produced blocks for each stake pool during the previous epoch.

- The information about produced blocks for each stake pool during the current epoch.

- The old epoch state.

- An optional rewards update.

- The stake pool distribution of the epoch.

- The OBFT overlay schedule.

Figure 5 also defines an abstract pseudorandom function $\fun{overlaySchedule}$ for creating the OBFT overlay schedule for each new epoch, as explained in section 3.8.2 of [@delegation_design]. The function takes a set of genesis keys, a seed, and the protocol parameters (of which the decentralization parameter $d$ and the active slot coeffient $f$ are used). It must create $(d\cdot\SlotsPerEpoch)$-many OBFT slots, $(f\cdot d\cdot \SlotsPerEpoch)$ of which are active.


*New Epoch environments* $$\begin{equation*}
    \type{NewEpochEnv}=
    \left(
      \begin{array}{rlr}
        \var{s} & \Slot & \text{current slot} \\
        \var{gkeys} & \powerset{\KeyHashGen} & \text{genesis key hashes} \\
      \end{array}
    \right)
\end{equation*}$$ *New Epoch states* $$\begin{equation*}
    \type{NewEpochState}=
    \left(
      \begin{array}{rlr}
        \var{e_\ell} & \Epoch & \text{last epoch} \\
        \var{b_{prev}} & \BlocksMade & \text{blocks made last epoch} \\
        \var{b_{cur}} & \BlocksMade & \text{blocks made this epoch} \\
        \var{es} & \EpochState & \text{epoch state} \\
        \var{ru} & \RewardUpdate^? & \text{reward update} \\
        \var{pd} & \type{PoolDistr}& \text{pool stake distribution} \\
        \var{osched} & \Slot\mapsto\KeyHashGen^? & \text{OBFT overlay schedule} \\
      \end{array}
    \right)
\end{equation*}$$ *Abstract pseudorandom schedule function* $$\begin{align*}
    & \fun{overlaySchedule} \in \Epoch \to \powerset{\KeyHashGen} \to \PParams
        \to (\Slot\mapsto\KeyHashGen^?) \\
\end{align*}$$ *Constraints* $$\begin{align*}
    \text{ given: }~\var{osched}\leteq\fun{overlaySchedule}~\var{e}~\var{gkeys}~\var{pp} \\
    \range{osched}\subseteq\var{gkeys} \\
    |\var{osched}| = \floor{(\fun{d}~\var{pp})\cdot\SlotsPerEpoch} \\
    |\{s\mapsto k\in\var{osched}~\mid~k\neq\Nothing\}| =
    \floor{\ActiveSlotCoeff(\fun{d}~\var{pp})\cdot\SlotsPerEpoch} \\
    \forall s\in\dom{osched},~\epoch{s}=e\\
\end{align*}$$ *New Epoch Transitions* $$\begin{equation*}
    \_ \vdash \var{\_} \trans{newepoch}{\_} \var{\_} \subseteq
    \powerset (\type{NewEpochEnv}\times \type{NewEpochState}\times \Epoch \times \type{NewEpochState})
\end{equation*}$$ *Helper function* $$\begin{align*}
      & \fun{calculatePoolDistr} \in \Snapshot \to \type{PoolDistr}\\
      & \fun{calculatePoolDistr}~(\var{stake},~\var{delegs},~\var{poolParams}) = \\
      & ~~~\left\{\var{hk_p}\mapsto(\sigma,~\fun{poolVRF}~\var{p})
            ~\Big\vert~
            {
              \begin{array}{rl}
                \var{hk_p}\mapsto\sigma & \var{sd} \\
                \var{hk_p}\mapsto\var{p} & \var{poolParams}
              \end{array}
            }
            \right\}\\
      & ~~~~\where \\
      & ~~~~~~~~~\var{total} = \sum_{\_ \mapsto c\in\var{stake}} c \\
      & ~~~~~~~~~\var{sd} = \fun{aggregate_{+}}~\left(\var{delegs}^{-1}\circ
                     \left\{\left(
                       \var{hk}, \frac{\var{c}}{\var{total}}
                     \right) \vert (\var{hk},
                     \var{c}) \in \var{stake}
                     \right\}\right) \\
\end{align*}$$

**NewEpoch transition-system types**

Figure 6 defines the new epoch state transition. It has three rules. The first rule describes the change in the case of $e$ being equal to the next epoch $e_\ell+ 1$. It also calls the $\mathsf{MIR}$ and $\mathsf{EPOCH}$ rules and checks that the reward update is net neutral with respect to the Ada in the system. This should always hold (by the definition of the $\fun{createRUpd}$ function) and is present only for extra assurance and for help in proving that Ada is preserved by this transition. The second rule deals with the case when the epoch signal $e$ is not one greater than the current epoch . This rule does not change the state. The third one deals with the case when the reward update is equal to $\Nothing$. This rule also does not change the state.

In the first case, the new epoch state is updated as follows:

- The epoch is set to the new epoch $e$.

- The mapping for the blocks produced by each stake pool for the previous epoch is set to the current such mapping.

- The mapping for the blocks produced by each stake pool for the current epoch is set to the empty map.

- The epoch state is updated with: first applying the rewards update , then calling the $\mathsf{MIR}$ transition, and finally by calling the $\mathsf{EPOCH}$ transition.

- The rewards update is set to .

- The new pool distribution ' is calculated from the delegation map and stake allocation of the previous epoch.

- A new OBFT overlay schedule is created.


$$\begin{equation}
\label{eq:new-epoch}
    \inference[New-Epoch]
    {
      e = e_\ell + 1
      &
      \var{ru} \neq \Nothing
      &
      (\Delta t,~\Delta r,~\var{rs},~\Delta f)\leteq\var{ru}
      \\
      \Delta t+~\Delta r+\left(\sum\limits_{\wcard\mapsto v\in\var{rs}} v\right)+\Delta f=0
      \\
      \var{es'}\leteq\fun{applyRUpd}~\var{ru}~\var{es}
      &
      {
        \vdash
        \var{es'}
          \trans{\hyperref[fig:rules:mir]{mir}}{}\var{es''}
      }
      &
      {
        \vdash
        \var{es''}
          \trans{\hyperref[fig:rules:epoch]{epoch}}{\var{e}}\var{es'''}
      }
      \\~\\
      {\begin{array}{rl}
         (\var{acnt},~\var{ss},~\wcard,~\wcard,~\var{pp}) & \var{es'''} \\
         (\wcard,~\var{pstake_{set}},~\wcard,~\wcard) & \var{ss} \\
         \var{pd'} & \fun{calculatePoolDistr}~\var{pstake_{set}} \\
         \var{osched'} & \fun{overlaySchedule}~\var{e}~\var{gkeys}~\var{pp} \\
       \end{array}}
    }
    {
      {\begin{array}{c}
         \var{s} \\
         \var{gkeys} \\
       \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \var{e_\ell} \\
            \var{b_{prev}} \\
            \var{b_{cur}} \\
            \var{es} \\
            \var{ru} \\
            \var{pd} \\
            \var{osched} \\
      \end{array}\right)}
      \trans{newepoch}{\var{e}}
      {\left(\begin{array}{c}
            \varUpdate{\var{e}} \\
            \varUpdate{\var{b_{cur}}} \\
            \varUpdate{\emptyset} \\
            \varUpdate{\var{es'''}} \\
            \varUpdate{\Nothing} \\
            \varUpdate{\var{pd}'} \\
            \varUpdate{\var{osched}'} \\
      \end{array}\right)}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:not-new-epoch}
    \inference[Not-New-Epoch]
    {
      (e_\ell,~\wcard,~\wcard,~\wcard,~\wcard,~\wcard,~\wcard)\leteq\var{nes}
      &
      e \neq e_\ell + 1
    }
    {
      {\begin{array}{c}
          \var{s} \\
          \var{gkeys} \\
      \end{array}}
      \vdash\var{nes}\trans{newepoch}{\var{e}} \var{nes}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:no-reward-update}
    \inference[No-Reward-Update]
    {
      (e_\ell,~\wcard,~\wcard,~\wcard,~\var{ru},~\wcard,~\wcard)\leteq\var{nes}
      &
      e = e_\ell + 1
      &
      \var{ru} = \Nothing
    }
    {
      {\begin{array}{c}
          \var{s} \\
          \var{gkeys} \\
      \end{array}}
      \vdash\var{nes}\trans{newepoch}{\var{e}} \var{nes}
    }
\end{equation}$$

**New Epoch rules**

## Tick Nonce Transition
The Tick Nonce Transition is responsible for updating the epoch nonce and the previous hash nonce at the start of an epoch. Its environment is shown in Figure 7 and consists of the protocol parameters $\var{pp}$, the candidate nonce $\eta_c$ and the previous header hash as a nonce. Its state consists of the epoch nonce $\eta_0$ and the previous hash nonce.


*Tick Nonce environments* $$\begin{equation*}
    \type{TickNonceEnv}=
    \left(
      \begin{array}{rlr}
        \var{pp} & \PParams & \text{protocol parameters} \\
        \eta_c & \Seed & \text{candidate nonce} \\
        \eta_\var{ph} & \Seed & \text{previous header hash as nonce} \\
      \end{array}
    \right)
\end{equation*}$$ *Tick Nonce states* $$\begin{equation*}
    \type{TickNonceState}=
    \left(
      \begin{array}{rlr}
        \eta_0 & \Seed & \text{epoch nonce} \\
        \eta_h & \Seed & \text{seed generated from hash of previous epoch} \\
      \end{array}
    \right)
\end{equation*}$$ []{#fig:ts-types:ticknonce label="fig:ts-types:ticknonce"}

The signal to the transition rule $\mathsf{TICKN}$ is a marker indicating whether we are in a new epoch. If we are in a new epoch, we update the epoch nonce and the previous hash. Otherwise, we do nothing.


$$\begin{equation}
\label{eq:tick-nonce-notnewepoch}
   \inference[Not-New-Epoch]
   { }
   {
     {\begin{array}{c}
        \var{pp} \\
        \eta_c \\
        \eta_\var{ph} \\
      \end{array}}
     \vdash
     {\left(\begin{array}{c}
           \eta_0 \\
           \eta_h \\
     \end{array}\right)}
     \trans{tickn}{\mathsf{False}}
     {\left(\begin{array}{c}
           \eta_0 \\
           \eta_h \\
     \end{array}\right)}
   }
\end{equation}$$

$$\begin{equation}
\label{eq:tick-nonce-newepoch}
   \inference[New-Epoch]
   {
     \eta_e \leteq \fun{extraEntropy}~\var{pp}
   }
   {
     {\begin{array}{c}
        \var{pp} \\
        \eta_c \\
        \eta_\var{ph} \\
      \end{array}}
     \vdash
     {\left(\begin{array}{c}
           \eta_0 \\
           \eta_h \\
     \end{array}\right)}
     \trans{tickn}{\mathsf{True}}
     {\left(\begin{array}{c}
           \varUpdate{\eta_c \seedOp \eta_h \seedOp \eta_e} \\
           \varUpdate{\eta_\var{ph}} \\
     \end{array}\right)}
   }
\end{equation}$$

**Tick Nonce rules**

## Update Nonce Transition
The Update Nonce Transition updates the nonces until the randomness gets fixed. The environment is shown in Figure 9 and consists of the block nonce $\eta$. The update nonce state is shown in Figure 9 and consists of the candidate nonce $\eta_c$ and the evolving nonce $\eta_v$.


*Update Nonce environments* $$\begin{equation*}
    \type{UpdateNonceEnv}=
    \left(
      \begin{array}{rlr}
        \eta & \Seed & \text{new nonce} \\
      \end{array}
    \right)
\end{equation*}$$ *Update Nonce states* $$\begin{equation*}
    \type{UpdateNonceState}=
    \left(
      \begin{array}{rlr}
        \eta_v & \Seed & \text{evolving nonce} \\
        \eta_c & \Seed & \text{candidate nonce} \\
      \end{array}
    \right)
\end{equation*}$$ *Update Nonce Transitions* $$\begin{equation*}
    \_ \vdash \var{\_} \trans{updn}{\_} \var{\_} \subseteq
    \powerset (\type{UpdateNonceEnv}
               \times \type{UpdateNonceState}
               \times \Slot
               \times \type{UpdateNonceState}
              )
\end{equation*}$$

**UpdNonce transition-system types**

The transition rule $\mathsf{UPDN}$ takes the slot as signal. There are two different cases for $\mathsf{UPDN}$: one where is not yet slots from the beginning of the next epoch and one where is less than slots until the start of the next epoch.

Note that in \[eq:update-both\], the nonce candidate $\eta_c$ transitions to $\eta_v\seedOp\eta$, not $\eta_c\seedOp\eta$. The reason for this is that even though the nonce candidate is frozen sometime during the epoch, we want the two nonces to again be equal at the start of a new epoch (so that the entropy added near the end of the epoch is not discarded).


$$\begin{equation}
\label{eq:update-both}
    \inference[Update-Both]
    {
      s < \fun{firstSlot}~((\epoch{s}) + 1) - \RandomnessStabilisationWindow
    }
    {
      {\begin{array}{c}
         \eta \\
       \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \eta_v \\
            \eta_c \\
      \end{array}\right)}
      \trans{updn}{\var{s}}
      {\left(\begin{array}{c}
            \varUpdate{\eta_v\seedOp\eta} \\
            \varUpdate{\eta_v\seedOp\eta} \\
      \end{array}\right)}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:only-evolve}
    \inference[Only-Evolve]
    {
      s \geq \fun{firstSlot}~((\epoch{s}) + 1) - \RandomnessStabilisationWindow
    }
    {
      {\begin{array}{c}
         \eta \\
       \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \eta_v \\
            \eta_c \\
      \end{array}\right)}
      \trans{updn}{\var{s}}
      {\left(\begin{array}{c}
            \varUpdate{\eta_v\seedOp\eta} \\
            \eta_c \\
      \end{array}\right)}
    }
\end{equation}$$

**Update Nonce rules**

## Reward Update Transition
The Reward Update Transition calculates a new $\RewardUpdate$ to apply in a $\mathsf{NEWEPOCH}$ transition. The environment is shown in Figure 11, it consists of the produced blocks mapping and the epoch state . Its state is an optional reward update.


*Reward Update environments* $$\begin{equation*}
    \type{RUpdEnv}=
    \left(
      \begin{array}{rlr}
        \var{b} & \BlocksMade & \text{blocks made} \\
        \var{es} & \EpochState & \text{epoch state} \\
      \end{array}
    \right)
\end{equation*}$$ *Reward Update Transitions* $$\begin{equation*}
    \_ \vdash \var{\_} \trans{rupd}{\_} \var{\_} \subseteq
    \powerset (\type{RUpdEnv}\times \RewardUpdate^? \times \Slot \times \RewardUpdate^?)
\end{equation*}$$

**Reward Update transition-system types**

The transition rules are shown in Figure 12. There are three cases, one which computes a new reward update, one which leaves the rewards update unchanged as it has not yet been applied and finally one that leaves the reward update unchanged as the transition was started too early.

The signal of the transition rule $\mathsf{RUPD}$ is the slot . The execution of the transition role is as follows:

- If the current reward update is empty and is greater than the sum of the first slot of its epoch and the duration , then a new rewards update is calculated and the state is updated.

- If the current reward update is not , i.e., a reward update has already been calculated but not yet applied, then the state is not updated.

- If the current reward update is empty and is less than or equal to the sum of the first slot of its epoch and the duration to start rewards , then the state is not updated.


$$\begin{equation}
\label{eq:reward-update}
    \inference[Create-Reward-Update]
    {
      s > \fun{firstSlot}~(\epoch{s}) + \StabilityWindow
      &
      ru = \Nothing
      \\~\\
      ru' \leteq \createRUpd{\SlotsPerEpoch}{b}{es}{\MaxLovelaceSupply}
    }
    {
      {\begin{array}{c}
         \var{b} \\
         \var{es} \\
       \end{array}}
      \vdash
      \var{ru}\trans{rupd}{\var{s}}\varUpdate{\var{ru}'}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:no-reward-update}
    \inference[Reward-Update-Exists]
    {
      ru \neq \Nothing
    }
    {
      {\begin{array}{c}
         \var{b} \\
         \var{es} \\
       \end{array}}
      \vdash
      \var{ru}\trans{rupd}{\var{s}}\var{ru}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:reward-too-early}
    \inference[Reward-Too-Early]
    {
      ru = \Nothing
      \\
      s \leq \fun{firstSlot}~(\epoch{s}) + \StabilityWindow
    }
    {
      {\begin{array}{c}
         \var{b} \\
         \var{es} \\
       \end{array}}
      \vdash
      \var{ru}\trans{rupd}{\var{s}}\var{ru}
    }
\end{equation}$$

**Reward Update rules**

## Chain Tick Transition
The Chain Tick Transition performs some chain level upkeep. The environment consists of a set of genesis keys, and the state is the epoch specific state necessary for the $\mathsf{NEWEPOCH}$ transition.

Part of the upkeep is updating the genesis key delegation mapping according to the future delegation mapping. For each genesis key, we adopt the most recent delegation in $\var{fGenDelegs}$ that is past the current slot, and any future genesis key delegations past the current slot is removed. The helper function $\fun{adoptGenesisDelegs}$ accomplishes the update.


*Chain Tick Transitions* $$\begin{equation*}
    \_ \vdash \var{\_} \trans{tick}{\_} \var{\_} \subseteq
    \powerset (\powerset{\KeyHashGen} \times \type{NewEpochState}\times \Slot \times \type{NewEpochState})
\end{equation*}$$

*helper function* $$\begin{align*}
      & \fun{adoptGenesisDelegs} \in \EpochState \to \Slot \to EpochState
      \\
      & \fun{adoptGenesisDelegs}~\var{es}~\var{slot} = \var{es'}
      \\
      & ~~~~\where
      \\
      & ~~~~~~~~~~
      (\var{acnt},~\var{ss},(\var{us},(\var{ds},\var{ps})),~\var{prevPp},~\var{pp})
      \leteq\var{es}
      \\
      & ~~~~~~~~~~
      (~\var{rewards},~\var{delegations},~\var{ptrs},
      ~\var{fGenDelegs},~\var{genDelegs},~\var{i_{rwd}})\leteq\var{ds}
      \\
      & ~~~~~~~~~~\var{curr}\leteq
        \{
          (\var{s},~\var{gkh})\mapsto(\var{vkh},~\var{vrf})\in\var{fGenDelegs}
          ~\mid~
          \var{s}\leq\var{slot}
        \}
      \\
      & ~~~~~~~~~~\var{fGenDelegs'}\leteq
          \var{fGenDelegs}\setminus\var{curr}
      \\
      & ~~~~~~~~~~\var{genDelegs'}\leteq
          \left\{
            \var{gkh}\mapsto(\var{vkh},~\var{vrf})
            ~\mathrel{\Bigg|}~
            {
              \begin{array}{l}
                (\var{s},~\var{gkh})\mapsto(\var{vkh},~\var{vrf})\in\var{curr}\\
                \var{s}=\max\{s'~\mid~(s',~\var{gkh})\in\dom{\var{curr}}\}
              \end{array}
            }
          \right\}
      \\
      & ~~~~~~~~~~\var{ds'}\leteq
          (\var{stkeys},~\var{rewards},~\var{delegations},~\var{ptrs},
          ~\var{fGenDelegs'},~\var{genDelegs}\unionoverrideRight\var{genDelegs'},~\var{i_{rwd}})
      \\
      & ~~~~~~~~~~\var{es'}\leteq
      (\var{acnt},~\var{ss},(\var{us},(\var{ds'},\var{ps})),~\var{prevPp},~\var{pp})
\end{align*}$$

**Tick transition-system types**

The $\mathsf{TICK}$ transition rule is shown in Figure 14. The signal is a slot .

Three transitions are done:

- The $\mathsf{NEWEPOCH}$ transition performs any state change needed if it is the first block of a new epoch.

- The $\mathsf{RUPD}$ creates the reward update if it is late enough in the epoch. **Note** that for every block header, either $\mathsf{NEWEPOCH}$ or $\mathsf{RUPD}$ will be the identity transition, and so, for instance, it does not matter if $\mathsf{RUPD}$ uses $\var{nes}$ or $\var{nes}'$ to obtain the needed state.


$$\begin{equation}
\label{eq:tick}
    \inference[Tick]
    {
      {
        {\begin{array}{c}
           \var{slot} \\
           \var{gkeys} \\
         \end{array}}
        \vdash
        \var{nes}
        \trans{\hyperref[fig:rules:new-epoch]{newepoch}}{\epoch{slot}}
        \var{nes}'
      }
      \\~\\
      (\wcard,~\var{b_{prev}},~\wcard,~\var{es},~\wcard,~\wcard,~\wcard)\leteq\var{nes} \\
      \\~\\
      {
        {\begin{array}{c}
           \var{b_{prev}} \\
           \var{es} \\
         \end{array}}
        \vdash \var{ru'}\trans{\hyperref[fig:rules:reward-update]{rupd}}{\var{slot}} \var{ru''}
      }
      \\~\\
      (\var{e_\ell'},~\var{b_{prev}'},~\var{b_{cur}'},~\var{es'},~\var{ru'},~\var{pd'},\var{osched'})
      \leteq\var{nes'}
      \\
      \var{es''}\leteq\fun{adoptGenesisDelegs}~\var{es'}~\var{slot}
      \\
      \var{nes''}\leteq
      (\var{e_\ell'},~\var{b_{prev}'},~\var{b_{cur}'},~\var{es''},~\var{ru''},~\var{pd'},\var{osched'})
      \\~\\
    }
    {
      {\begin{array}{c}
         \var{gkeys} \\
       \end{array}}
      \vdash\var{nes}\trans{tick}{\var{slot}}\varUpdate{\var{nes''}}
    }
\end{equation}$$

**Tick rules**

## Operational Certificate Transition
The Operational Certificate Transition environment consists of the genesis key delegation map $\var{genDelegs}$ and the set of stake pools $\var{stpools}$. Its state is the mapping of operation certificate issue numbers. Its signal is a block header.


*Operational Certificate environments* $$\begin{equation*}
    \type{OCertEnv}=
    \left(
      \begin{array}{rlr}
        \var{stpools} & \powerset{\type{KeyHash}} & \text{stake pools} \\
        \var{genDelegs} & \powerset{\type{KeyHash}} & \text{genesis key delegates}\\
      \end{array}
    \right)
\end{equation*}$$ *Operational Certificate Transitions* $$\begin{equation*}
    \var{\_} \vdash \var{\_} \trans{ocert}{\_} \var{\_} \subseteq
    \powerset (\type{OCertEnv}\times \KeyHash_{pool} \mapsto \N \times \type{BHeader}\times \KeyHash_{pool} \mapsto \N)
\end{equation*}$$ *Operational Certificate helper function* $$\begin{align*}
      & \fun{currentIssueNo} \in \type{OCertEnv}\to (\KeyHash_{pool} \mapsto \N)
                                           \to \KeyHash_{pool}
                                           \to \N^? \\
      & \fun{currentIssueNo}~(\var{stpools}, \var{genDelegs})~ \var{cs} ~\var{hk} =
      \begin{cases}
        \var{hk}\mapsto \var{n} \in \var{cs} & n \\
        \var{hk} \in \var{stpools} & 0 \\
        \var{hk} \in \var{genDelegs} & 0 \\
        \text{otherwise} & \Nothing
      \end{cases}
\end{align*}$$

**OCert transition-system types**

The transition rule is shown in Figure 16. From the block header body we first extract the following:

- The operational certificate, consisting of the hot key , the certificate issue number , the KES period start and the cold key signature.

- The cold key .

- The slot for the block.

- The number of KES periods that have elapsed since the start period on the certificate.

Using this we verify the preconditions of the operational certificate state transition which are the following:

- The KES period of the slot in the block header body must be greater than or equal to the start value listed in the operational certificate, and less than $\MaxKESEvo$-many KES periods after . The value of $\MaxKESEvo$ is the agreed-upon lifetime of an operational certificate, see [@delegation_design].

- exists as key in the mapping of certificate issues numbers to a KES period and that period is less than or equal to .

- The signature $\tau$ can be verified with the cold verification key .

- The KES signature $\sigma$ can be verified with the hot verification key .

After this, the transition system updates the operational certificate state by updating the mapping of operational certificates where it overwrites the entry of the key with the KES period .


$$\begin{equation}
\label{eq:ocert}
    \inference[OCert]
    {
      (\var{bhb},~\sigma)\leteq\var{bh}
      &
      (\var{vk_{hot}},~n,~c_{0},~\tau) \leteq \fun{bocert}~\var{bhb}
      &
      \var{vk_{cold}} \leteq \fun{bvkcold}~\var{bhb}
      \\
      \var{hk} \leteq \hashKey{vk_{cold}}
      &
      \var{s}\leteq\bslot{bhb}
      &
      t \leteq \kesPeriod{s} - c_0
      \\~\\
      c_0 \leq \kesPeriod{s} < c_0 + \MaxKESEvo
      \\
      \fun{currentIssueNo} ~ \var{oce} ~ \var{cs} ~ \var{hk} = m
      &
      m \leq n
      \\~\\
      \mathcal{V}_{\var{vk_{cold}}}{\serialised{(\var{vk_{hot}},~n,~c_0)}}_{\tau}
      &
      \mathcal{V}^{\mathsf{KES}}_{vk_{hot}}{\serialised{bhb}}_{\sigma}^{t}
      \\
    }
    {
      \var{oce}\vdash\var{cs}
      \trans{ocert}{\var{bh}}\varUpdate{\var{cs}\unionoverrideRight\{\var{hk}\mapsto n\}}
    }
\end{equation}$$

**OCert rules**

The OCERT rule has six predicate failures:

- If the KES period is less than the KES period start in the certificate, there is a *KESBeforeStart* failure.

- If the KES period is greater than or equal to the KES period end (start + $\MaxKESEvo$) in the certificate, there is a *KESAfterEnd* failure.

- If the period counter in the original key hash counter mapping is larger than the period number in the certificate, there is a *CounterTooSmall* failure.

- If the signature of the hot key, KES period number and period start is incorrect, there is an *InvalidSignature* failure.

- If the KES signature using the hot key of the block header body is incorrect, there is an *InvalideKesSignature* failure.

- If there is no entry in the key hash to counter mapping for the cold key, there is a *NoCounterForKeyHash* failure.

## Verifiable Random Function
In this section we define a function $\fun{vrfChecks}$ which performs all the VRF related checks on a given block header body. In addition to the block header body, the function requires the epoch nonce, the stake distribution (aggregated by pool), and the active slots coefficient from the protocol parameters. The function checks:

- The validity of the proofs for the leader value and the new nonce.

- The verification key is associated with relative stake $\sigma$ in the stake distribution.

- The $\fun{bleader}$ value of indicates a possible leader for this slot. The function $\fun{checkLeaderVal}$ is defined in \[sec:leader-value-calc\].


*VRF helper function* $$\begin{align*}
      & \fun{vrfChecks} \in \Seed \to \type{BHBody}\to \Bool \\
      & \fun{vrfChecks}~\eta_0~\var{bhb} = \\
      & \begin{array}{cl}
        ~~~~ &
             \fun{verifyVrf}_{\Seed} ~ \var{vrfVk} ~ ((\eta_0\seedOp ss)\seedOp\mathsf{Seed}_\eta) ~(\fun{bprf}_{n}~\var{bhb},~\fun{bnonce}~\var{bhb}) \\
        ~~~~ \land &
             \fun{verifyVrf}_{\unitInterval} ~ \var{vrfVk} ~ ((\eta_0\seedOp ss)\seedOp\mathsf{Seed}_\ell) ~(\fun{bprf}_{\ell}~\var{bhb},~\fun{bleader}~\var{bhb}) \\
      \end{array} \\
      & ~~~~\where \\
      & ~~~~~~~~~~\var{ss} \leteq \fun{slotToSeed}~ \var{(\bslot{bhb})} \\
      & ~~~~~~~~~~\var{vrfVk} \leteq \fun{bvkvrf}~\var{bhb} \\
\end{align*}$$ $$\begin{align*}
      & \fun{praosVrfChecks} \in \Seed \to \type{PoolDistr}\to \unitInterval \to \type{BHBody}\to \Bool \\
      & \fun{praosVrfChecks}~\eta_0~\var{pd}~\var{f}~\var{bhb} = \\
      & \begin{array}{cl}
        ~~~~ & \var{hk}\mapsto (\sigma,~\var{hk_{vrf}})\in\var{pd} \\
        ~~~~ \land & \fun{vrfChecks}~\eta_0~\var{bhb} \\
        ~~~~ \land & \fun{checkLeaderVal}~(\fun{bleader}~\var{bhb})~\sigma~\var{f} \\
      \end{array} \\
      & ~~~~\where \\
      & ~~~~~~~~~~\var{hk} \leteq \hashKey{(\fun{bvkcold}~\var{b}hb)} \\
      & ~~~~~~~~~~\var{hk_{vrf}} \leteq \hashKey{(\fun{bvkvrf}~\var{bhb})} \\
\end{align*}$$ $$\begin{align*}
      & \fun{pbftVrfChecks} \in \KeyHash_{vrf} \to \Seed \to \type{BHBody}\to \Bool \\
      & \fun{pbftVrfChecks}~\var{vrfh}~\eta_0~~\var{bhb} = \\
      & \begin{array}{cl}
        ~~~~ & \var{vrfh} = \hashKey{(\fun{bvkvrf}~\var{bhb})} \\
        ~~~~ \land & \fun{vrfChecks}~\eta_0~\var{bhb} \\
      \end{array} \\
\end{align*}$$ []{#fig:vrf-checks label="fig:vrf-checks"}

## Overlay Schedule
The transition from the bootstrap era to a fully decentralized network is explained in section 3.9.2 of [@delegation_design]. Key to this transition is a protocol parameter $d$ which controls how many slots are governed by the genesis nodes via OBFT, and which slots are open to any registered stake pool. The transition system introduced in this section, $\type{OVERLAY}$, covers this mechanism.

This transition is responsible for validating the protocol for both the OBFT blocks and the Praos blocks, depending on the overlay schedule.

The environments for this transition are:

- A mapping $\var{osched}$ of slots to an optional genesis key. In the terminology of [@delegation_design], the slots in $\var{osched}$ are the "OBFT slots". A slot in this map with a value of $\Nothing$ is a non-active slot, otherwise it is an active slot and its value designates the genesis key responsible for producing the block.

- The epoch nonce $\eta_0$.

- The stake pool stake distribution $\var{pd}$.

- The mapping $\var{genDelegs}$ of genesis keys to their cold keys and vrf keys.

The states for this transition consist only of the mapping of certificate issue numbers.

This transition establishes that a block producer is in fact authorized. Since there are three key pairs involved (cold keys, VRF keys, and hot KES keys) it is worth examining the interaction closely. First we look at the regular Praos/decentralized setting, which is given by Equation \[eq:decentralized\].

- First we check the operational certificate with $\mathsf{OCERT}$. This uses the cold verification key given in the block header. We do not yet trust that this key is a registered pool key. If this transition is successful, we know that the cold key in the block header has authorized the block.

- Next, in the $\fun{vrfChecks}$ predicate, we check that the hash of this cold key is in the mapping $\var{pd}$, and that it maps to $(\sigma,~\var{hk_{vrf}})$, where $(\sigma,~\var{hk_{vrf}})$ is the hash of the VRF key in the header. If $\fun{praosVrfChecks}$ returns true, then we know that the cold key in the block header was a registered stake pool at the beginning of the previous epoch, and that it is indeed registered with the VRF key listed in the header.

- Finally, we use the VRF verification key in the header, along with the VRF proofs in the header, to check that the operator is allowed to produce the block.

The situation for the overlay schedule, given by Equation \[eq:active-pbft\], is similar. The difference is that we check the overlay schedule to see what core node is supposed to make a block, and then use the genesis delegation mapping to check the correct cold key hash and vrf key hash.


*Overlay environments* $$\begin{equation*}
    \type{OverlayEnv}=
    \left(
      \begin{array}{rlr}
        \var{osched} & \Slot\mapsto\KeyHashGen^? & \text{OBFT overlay schedule} \\
        \eta_0 & \Seed & \text{epoch nonce} \\
        \var{pd} & \type{PoolDistr}& \text{pool stake distribution} \\
        \var{genDelegs} & \GenesisDelegation & \text{genesis key delegations} \\
      \end{array}
    \right)
\end{equation*}$$ *Overlay Transitions* $$\begin{equation*}
    \_ \vdash \var{\_} \trans{overlay}{\_} \var{\_} \subseteq
    \powerset (\type{OverlayEnv}\times (\KeyHash_{pool} \mapsto \N) \times \type{BHeader}\times
    (\KeyHash_{pool} \mapsto \N))
\end{equation*}$$

**Overlay transition-system types**

$$\begin{equation}
\label{eq:active-pbft}
    \inference[Active-OBFT]
    {
      \var{bhb}\leteq\fun{bheader}~\var{bh}
      &
      \var{vk}\leteq\fun{bvkcold}~\var{bhb}
      &
      \var{vkh}\leteq\hashKey{vk}
      \\
      \bslot bhb \mapsto \var{gkh}\in\var{osched}
      &
      \var{gkh}\mapsto(\var{vkh},~\var{vrfh})\in\var{genDelegs}
      \\~\\
      \fun{pbftVrfChecks}~\var{vrfh}~\eta_0~\var{bhb}
      \\~\\
      {
        {\begin{array}{c}
         \dom{\var{pd}} \\
         \range{\var{genDelegs}} \\
         \end{array}
        }
        \vdash\var{cs}\trans{\hyperref[fig:rules:ocert]{ocert}}{\var{bh}}\var{cs'}
      }
    }
    {
      {\begin{array}{c}
         \var{osched} \\
         \eta_0 \\
         \var{pd} \\
         \var{genDelegs} \\
       \end{array}}
      \vdash
      \var{cs}
      \trans{overlay}{\var{bh}}
      \varUpdate{\var{cs}'}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:decentralized}
    \inference[Decentralized]
    {
      \var{bhb}\leteq\fun{bheader}~\var{bh}
      \\
      \bslot{bhb} \notin \dom{\var{osched}}
      \\~\\
      {
        \vdash\var{cs}\trans{\hyperref[fig:rules:ocert]{ocert}}{\var{bh}}\var{cs'}
      }
      \\~\\
      \fun{praosVrfChecks}~\eta_0~\var{pd}~\ActiveSlotCoeff~\var{bhb}
    }
    {
      {\begin{array}{c}
         \var{osched} \\
         \eta_0 \\
         \var{pd} \\
         \var{genDelegs} \\
       \end{array}}
      \vdash
      \var{cs}
      \trans{overlay}{\var{bh}}
      \varUpdate{\var{cs}'}
    }
\end{equation}$$

**Overlay rules**

The OVERLAY rule has nine predicate failures:

- If in the decentralized case the VRF key is not in the pool distribution, there is a *VRFKeyUnknown* failure.

- If in the decentralized case the VRF key hash does not match the one listed in the block header, there is a *VRFKeyWrongVRFKey* failure.

- If the VRF generated nonce in the block header does not validate against the VRF certificate, there is a *VRFKeyBadNonce* failure.

- If the VRF generated leader value in the block header does not validate against the VRF certificate, there is a *VRFKeyBadLeaderValue* failure.

- If the VRF generated leader value in the block header is too large compared to the relative stake of the pool, there is a *VRFLeaderValueTooBig* failure.

- In the case of the slot being in the OBFT schedule, but without genesis key (i.e., $Nothing$), there is a *NotActiveSlot* failure.

- In the case of the slot being in the OBFT schedule, if there is a specified genesis key which is not the same key as in the bock header body, there is a *WrongGenesisColdKey* failure.

- In the case of the slot being in the OBFT schedule, if the hash of the VRF key in block header does not match the hash in the genesis delegation mapping, there is a *WrongGenesisVRFKey* failure.

- In the case of the slot being in the OBFT schedule, if the genesis delegate keyhash is not in the genesis delegation mapping, there is a *UnknownGenesisKey* failure. This case should never happen, and represents a logic error.

## Protocol Transition
The protocol transition covers the common predicates of OBFT and Praos, and then calls $\mathsf{OVERLAY}$ for the particular transitions, followed by the transition to update the evolving and candidate nonces.


*Protocol environments* $$\begin{equation*}
    \type{PrtclEnv}=
    \left(
      \begin{array}{rlr}
        \var{osched} & \Slot\mapsto\KeyHashGen^? & \text{OBFT overlay schedule} \\
        \var{pd} & \type{PoolDistr}& \text{pool stake distribution} \\
        \var{dms} & \KeyHashGen\mapsto\KeyHash & \text{genesis key delegations} \\
      \end{array}
    \right)
\end{equation*}$$ *Protocol states* $$\begin{equation*}
    \type{PrtclState}=
    \left(
      \begin{array}{rlr}
        \var{cs} & \KeyHash_{pool} \mapsto \N & \text{operational certificate issues numbers} \\
        \eta_v & \Seed & \text{evolving nonce} \\
        \eta_c & \Seed & \text{candidate nonce} \\
      \end{array}
    \right)
\end{equation*}$$ *Protocol Transitions* $$\begin{equation*}
    \_ \vdash \var{\_} \trans{prtcl}{\_} \var{\_} \subseteq
    \powerset (\powerset{\type{PrtclEnv}} \times \type{PrtclState}\times \type{BHeader}\times \type{PrtclState})
\end{equation*}$$

**Protocol transition-system types**

The environments for this transition are:

- A mapping $\var{osched}$ of slots to an optional genesis key. In the terminology of [@delegation_design], the slots in $\var{osched}$ are the "OBFT slots". A slot in this map with a value of $\Nothing$ is a non-active slot, otherwise it is an active slot and its value designates the genesis key responsible for producing the block.

- The stake pool stake distribution $\var{pd}$.

- The mapping $\var{dms}$ of genesis keys to their cold keys.

- The epoch nonce $\eta_0$.

The states for this transition consists of:

- The operational certificate issue number mapping.

- The last applied block information.

- The evolving nonce.

- The canditate nonce for the next epoch.


$$\begin{equation}
\label{eq:prtcl}
    \inference[PRTCL]
    {
      \eta\leteq\fun{bnonce}~(\bhbody{bhb})
      \\~\\
      {
        \eta
        \vdash
        {\left(\begin{array}{c}
        \eta_v \\
        \eta_c \\
        \end{array}\right)}
        \trans{\hyperref[fig:rules:update-nonce]{updn}}{\var{slot}}
        {\left(\begin{array}{c}
        \eta_v' \\
        \eta_c' \\
        \end{array}\right)}
      }\\~\\
      {
        {\begin{array}{c}
          \var{osched} \\
          \eta_0 \\
          \var{pd} \\
          \var{dms} \\
        \end{array}
        }
        \vdash \var{cs}\trans{\hyperref[fig:rules:overlay]{overlay}}{\var{bh}} \var{cs}'
      }
    }
    {
      {\begin{array}{c}
         \var{osched} \\
         \var{pd} \\
         \var{dms} \\
         \eta_0 \\
       \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \var{cs} \\
            \eta_v \\
            \eta_c \\
      \end{array}\right)}
      \trans{prtcl}{\var{bh}}
      {\left(\begin{array}{c}
            \varUpdate{cs'} \\
            \varUpdate{\eta_v'} \\
            \varUpdate{\eta_c'} \\
      \end{array}\right)}
    }
\end{equation}$$

**Protocol rules**

The PRTCL rule has no predicate failures.

## Block Body Transition
The Block Body Transition updates the block body state which comprises the ledger state and the map describing the produced blocks. The environment of the $\mathsf{BBODY}$ transition are overlay schedule slots, the protocol parameters, and the accounting state. The environments and states are defined in Figure 22, along with a helper function $\fun{incrBlocks}$, which counts the number of non-overlay blocks produced by each stake pool.


*BBody environments* $$\begin{equation*}
    \type{BBodyEnv}=
    \left(
      \begin{array}{rlr}
        \var{oslots} & \powerset{\Slot} & \text{overlay slots} \\
        \var{pp} & \PParams & \text{protocol parameters} \\
        \var{acnt} & \Acnt & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ *BBody states* $$\begin{equation*}
    \type{BBodyState}=
    \left(
      \begin{array}{rlr}
        \var{ls} & \LState & \text{ledger state} \\
        \var{b} & \BlocksMade & \text{blocks made} \\
      \end{array}
    \right)
\end{equation*}$$ *BBody Transitions* $$\begin{equation*}
    \_ \vdash \var{\_} \trans{bbody}{\_} \var{\_} \subseteq
    \powerset (\type{BBodyEnv}\times \type{BBodyState}\times \Block \times \type{BBodyState})
\end{equation*}$$

*BBody helper function* $$\begin{align*}
      & \fun{incrBlocks} \in \Bool \to \KeyHash_{pool} \to
          \BlocksMade \to \BlocksMade \\
      & \fun{incrBlocks}~\var{isOverlay}~\var{hk}~\var{b} =
        \begin{cases}
          b & \text{if }\var{isOverlay} \\
          b\cup\{\var{hk}\mapsto 1\} & \text{if }\var{hk}\notin\dom{b} \\
          b\unionoverrideRight\{\var{hk}\mapsto n+1\} & \text{if }\var{hk}\mapsto n\in b \\
        \end{cases}
\end{align*}$$

**BBody transition-system types**

The $\mathsf{BBODY}$ transition rule is shown in Figure 23, its sub-rule is $\mathsf{LEDGERS}$ which does the update of the ledger state. The signal is a block from which we extract:

- The sequence of transactions of the block.

- The block header body .

- The verification key of the issuer of the and its hash .

The transition is executed if the following preconditions are met:

- The size of the block body matches the value given in the block header body.

- The hash of the block body matches the value given in the block header body.

- The $\mathsf{LEDGERS}$ transition succeeds.

After this, the transition system updates the mapping of the hashed stake pool keys to the incremented value of produced blocks ( + 1), provided the current slot is not an overlay slot.


$$\begin{equation}
\label{eq:bbody}
    \inference[Block-Body]
    {
      \var{txs} \leteq \bbody{block}
      &
      \var{bhb} \leteq \bhbody{(\fun{bheader}~\var{block})}
      &
      \var{hk} \leteq \hashKey{(\fun{bvkcold}~\var{bhb})}
      \\~\\
      \fun{bBodySize}~ \var{txs} = \fun{hBbsize}~\var{bhb}
      &
      \fun{bbodyhash}~{txs} = \fun{bhash}~\var{bhb}
      \\~\\
      {
        {\begin{array}{c}
                 \bslot{bhb} \\
                 \var{pp} \\
                 \var{acnt}
        \end{array}}
        \vdash
             \var{ls} \\
        \trans{\hyperref[fig:rules:ledger-sequence]{ledgers}}{\var{txs}}
             \var{ls}' \\
      }
    }
    {
      {\begin{array}{c}
               \var{oslots} \\
               \var{pp} \\
               \var{acnt}
      \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \var{ls} \\
            \var{b} \\
      \end{array}\right)}
      \trans{bbody}{\var{block}}
      {\left(\begin{array}{c}
            \varUpdate{\var{ls}'} \\
            \varUpdate{\fun{incrBlocks}~{(\bslot{bhb}\in\var{oslots})}~{hk}~{b}} \\
      \end{array}\right)}
    }
\end{equation}$$

**BBody rules**

The BBODY rule has two predicate failures:

- if the size of the block body in the header is not equal to the real size of the block body, there is a *WrongBlockBodySize* failure.

- if the hash of the block body is not also the hash of transactions, there is an *InvalidBodyHash* failure.

## Chain Transition
The $\mathsf{CHAIN}$ transition rule is the main rule of the blockchain layer part of the STS. It calls $\mathsf{BHEAD}$, $\mathsf{PRTCL}$, and $\mathsf{BBODY}$ as sub-rules.

The chain rule has no environment.

The transition checks six things (via $\fun{chainChecks}$ and $\fun{prtlSeqChecks}$ from Figure 25):

- The slot in the block header body is larger than the last slot recorded.

- The block number increases by exactly one.

- The previous hash listed in the block header matches the previous block header hash which was recorded.

- The size of is less than or equal to the maximal size that the protocol parameters allow for block headers.

- The size of the block body, as claimed by the block header, is less than or equal to the maximal size that the protocol parameters allow for block bodies. It will later be verified that the size of the block body matches the size claimed in the header (see Figure 23).

- The node is not obsolete, meaning that the major component of the protocol version in the protocol parameters is not bigger than the constant $\MaxMajorPV$.

The chain state is shown in Figure 24, it consists of the following:

- The epoch specific state $\var{nes}$.

- The operational certificate issue number map $\var{cs}$.

- The epoch nonce $\eta_0$.

- The evolving nonce $\eta_v$.

- The candidate nonce $\eta_c$.

- The previous epoch hash nonce $\eta_h$.

- The last header hash .

- The last slot .

- The last block number .


*Chain states* $$\begin{equation*}
    \type{LastAppliedBlock}=
    \left(
      \begin{array}{rlr}
        \var{b_\ell} & \Slot & \text{last block number} \\
        \var{s_\ell} & \Slot & \text{last slot} \\
        \var{h} & \type{HashHeader}& \text{latest header hash} \\
      \end{array}
    \right)
\end{equation*}$$ $$\begin{equation*}
    \type{ChainState}=
    \left(
      \begin{array}{rlr}
        \var{nes} & \type{NewEpochState}& \text{epoch specific state} \\
        \var{cs} & \KeyHash_{pool} \mapsto \N & \text{operational certificate issue numbers} \\
        ~\eta_0 & \Seed & \text{epoch nonce} \\
        ~\eta_v & \Seed & \text{evolving nonce} \\
        ~\eta_c & \Seed & \text{candidate nonce} \\
        ~\eta_h & \Seed & \text{seed generated from hash of previous epoch} \\
        \var{lab} & \type{LastAppliedBlock}^? & \text{latest applied block} \\
      \end{array}
    \right)
\end{equation*}$$ *Chain Transitions* $$\begin{equation*}
    \vdash \var{\_} \trans{chain}{\_} \var{\_} \subseteq
    \powerset (\type{ChainState}\times \Block \times \type{ChainState})
\end{equation*}$$

**Chain transition-system types**

The $\mathsf{CHAIN}$ transition rule is shown in Figure 26. Its signal is a . The transition uses a few helper functions defined in Figure 25.


*Chain Transition Helper Functions* $$\begin{align*}
      & \fun{getGKeys} \in \type{NewEpochState}\to \powerset{\KeyHashGen} \\
      & \fun{getGKeys}~\var{nes} = \dom{genDelegs} \\
      &
      \begin{array}{lrl}
        \where
          & (\wcard,~\wcard,~\wcard,~\wcard,~\var{es},~\wcard,~\wcard,~\wcard)
          & \var{nes}
          \\
          & (\wcard,~\wcard,~\var{ls},~\wcard)
          & \var{es}
          \\
          & (\wcard,~((\wcard,~\wcard,~\wcard,~\wcard,~\var{genDelegs},~\wcard),~\wcard))
          & \var{ls}
      \end{array}
\end{align*}$$ $$\begin{align*}
      & \fun{updateNES} \in \type{NewEpochState}\to \BlocksMade \to \LState \to \type{NewEpochState}\\
      & \fun{updateNES}~
      (\var{e_\ell},~\var{b_{prev}},~\wcard,~(\var{acnt},~\var{ss},~\wcard,~\var{pp}),
       ~\var{ru},~\var{pd},~\var{osched})
          ~\var{b_{cur}}~\var{ls} = \\
      & ~~~~
      (\var{e_\ell},~\var{b_{prev}},~\var{b_{cur}},
       ~(\var{acnt},~\var{ss},~\var{ls},~\var{pp}),~\var{ru},~\var{pd},~\var{osched})
\end{align*}$$ $$\begin{align*}
      & \fun{chainChecks} \in \PParams \to \type{BHeader}\to \Bool \\
      & \fun{chainChecks}~\var{pp}~\var{bh} = \\
      & ~~~~ m \leq \MaxMajorPV \\
      & ~~~~ \land~\fun{bHeaderSize}~ \var{bh} \leq \fun{maxHeaderSize}~\var{pp} \\
      & ~~~~ \land~\fun{hBbsize}~\var{(\bhbody{bh})} \leq \fun{maxBlockSize}~\var{pp} \\
      & ~~~~ \where (m,~\wcard)\leteq\fun{pv}~\var{pp}
\end{align*}$$ $$\begin{align*}
      & \fun{lastAppliedHash} \in \type{LastAppliedBlock}^? \to \type{HashHeader}^? \\
      & \fun{lastAppliedHash}~\var{lab} =
        \begin{cases}
          \Nothing & lab = \Nothing \\
          h & lab = (\wcard,~\wcard,~h) \\
        \end{cases}
\end{align*}$$ $$\begin{align*}
      & \fun{prtlSeqChecks} \to \type{LastAppliedBlock}^? \to \type{BHeader}\to \Bool \\
      & \fun{prtlSeqChecks}~\var{lab}~\var{bh} =
        \begin{cases}
          \mathsf{True}
          &
          lab = \Nothing
          \\
          \var{s_\ell} < \var{slot}
          \land \var{b_\ell} + 1 = \var{bn}
          \land \var{ph} = \fun{bprev}~\var{bhb}
          &
          lab = (b_\ell,~s_\ell,~\wcard) \\
        \end{cases} \\
      & ~~~~\where \\
      & ~~~~~~~~~~\var{bhb} \leteq \bhbody{bh} \\
      & ~~~~~~~~~~\var{bn} \leteq \bblockno{bhb} \\
      & ~~~~~~~~~~\var{slot} \leteq \bslot{bhb} \\
      & ~~~~~~~~~~\var{ph} \leteq \fun{lastAppliedHash}~\var{lab} \\
\end{align*}$$

**Helper Functions used in the CHAIN transition**

$$\begin{equation}
\label{eq:chain}
    \inference[Chain]
    {
      \var{bh} \leteq \fun{bheader}~\var{block}
      &
      \var{bhb} \leteq \bhbody{bh}
      \\
      \var{gkeys} \leteq \fun{getGKeys}~\var{nes}
      &
      \var{s} \leteq \bslot{bhb}
      \\
      (\wcard,~\wcard,~\wcard,~(\wcard,~\wcard,~\wcard,~\var{pp}),~\wcard,~\wcard,\wcard) \leteq \var{nes}
      \\~\\
      \fun{prtlSeqChecks}~\var{lab}~\var{bh}\\
      \fun{chainChecks}~\var{pp}~\var{bh}
      \\~\\
      {
        {\begin{array}{c}
           \var{gkeys} \\
         \end{array}}
        \vdash\var{nes}\trans{\hyperref[fig:rules:tick]{tick}}{\var{s}}\var{nes'}
      } \\~\\
      (\var{e_1},~\wcard,~\wcard,~\wcard,~\wcard,~\wcard,\wcard)
        \leteq\var{nes} \\
      (\var{e_2},~\wcard,~\var{b_{cur}},~\var{es},~\wcard,~\var{pd},\var{osched})
        \leteq\var{nes'} \\
        (\var{acnt},~\wcard,\var{ls},~\wcard,~\var{pp'})\leteq\var{es}\\
        ( \wcard,
          ( (\wcard,~\wcard,~\wcard,~\wcard,~\var{genDelegs},~\wcard),~
          (\wcard,~\wcard,~\wcard)))\leteq\var{ls}\\
          \var{ne} \leteq  \var{e_1} \neq \var{e_2}\\
          \eta_{ph} \leteq \fun{prevHashToNonce}~ \var{(\fun{lastAppliedHash}~\var{lab})} \\
      {
        {\begin{array}{c}
        \var{pp'} \\
        \eta_c \\
        \eta_\var{ph} \\
        \end{array}}
        \vdash
        {\left(\begin{array}{c}
        \eta_0 \\
        \eta_h \\
        \end{array}\right)}
        \trans{\hyperref[fig:rules:tick-nonce]{tickn}}{\var{ne}}
        {\left(\begin{array}{c}
        \eta_0' \\
        \eta_h' \\
        \end{array}\right)}
      }\\~\\~\\
      {
        {\begin{array}{c}
            \var{osched} \\
            \var{pd} \\
            \var{genDelegs} \\
            \eta_0' \\
         \end{array}}
        \vdash
        {\left(\begin{array}{c}
              \var{cs} \\
              \eta_v \\
              \eta_c \\
        \end{array}\right)}
        \trans{\hyperref[fig:rules:prtcl]{prtcl}}{\var{bh}}
        {\left(\begin{array}{c}
              \var{cs'} \\
              \eta_v' \\
              \eta_c' \\
        \end{array}\right)}
      } \\~\\~\\
      {
        {\begin{array}{c}
                 \dom{osched} \\
                 \var{pp'} \\
                 \var{acnt}
        \end{array}}
        \vdash
        {\left(\begin{array}{c}
              \var{ls} \\
              \var{b_{cur}} \\
        \end{array}\right)}
        \trans{\hyperref[fig:rules:bbody]{bbody}}{\var{block}}
        {\left(\begin{array}{c}
              \var{ls}' \\
              \var{b_{cur}'} \\
        \end{array}\right)}
      }\\~\\
      \var{nes''}\leteq\fun{updateNES}~\var{nes'}~\var{b_{cur}'},~\var{ls'} \\
      \var{lab'}\leteq (\bblockno{bhb},~\var{s},~\fun{bhash}~\var{bh} ) \\
    }
    {
      \vdash
      {\left(\begin{array}{c}
            \var{nes} \\
            \var{cs} \\
            \eta_0 \\
            \eta_v \\
            \eta_c \\
            \eta_h \\
            \var{lab} \\
      \end{array}\right)}
      \trans{chain}{\var{block}}
      {\left(\begin{array}{c}
            \varUpdate{\var{nes}''} \\
            \varUpdate{\var{cs}'} \\
            \varUpdate{\eta_0'} \\
            \varUpdate{\eta_v'} \\
            \varUpdate{\eta_c'} \\
            \varUpdate{\eta_h'} \\
            \varUpdate{\var{lab}'} \\
      \end{array}\right)}
    }
\end{equation}$$

**Chain rules**

The CHAIN rule has six predicate failures:

- If the slot of the block header body is not larger than the last slot or greater than the current slot, there is a *WrongSlotInterval* failure.

- If the block number does not increase by exactly one, there is a *WrongBlockNo* failure.

- If the hash of the previous header of the block header body is not equal to the hash given in the environment, there is a *WrongBlockSequence* failure.

- If the size of the block header is larger than the maximally allowed size, there is a *HeaderSizeTooLarge* failure.

- If the size of the block body is larger than the maximally allowed size, there is a *BlockSizeTooLarge* failure.

- If the major component of the protocol version is larger than $\MaxMajorPV$, there is a *ObsoleteNode* failure.

## Byron to Shelley Transition
This section defines the valid initial Shelley ledger states and describes how to transition the state held by the Byron ledger to Shelley. The Byron ledger state $\CEState$ is defined in [@byron_chain_spec]. The valid initial Shelley ledger states are exactly the range of the function $\fun{initialShelleyState}$ defined in Figure 27. Figure 28 defines the transition function from Byron. Note that we use the hash of the final Byron header as the first evolving and candidate nonces for Shelley.


*Shelley Initial States* $$\begin{align*}
      & \fun{initialShelleyState} \in \type{LastAppliedBlock}^? \to \Epoch \to \UTxO
        \to \Coin \to \GenesisDelegation \\
      & ~~~ \to (\Slot\mapsto\KeyHashGen^?)
        \to \PParams \to \Seed \to \type{ChainState}\\
      & \fun{initialShelleyState}~
      \left(
        \begin{array}{c}
          \var{lab} \\
          \var{e} \\
          \var{utxo} \\
          \var{reserves} \\
          \var{genDelegs} \\
          \var{os} \\
          \var{pp} \\
          \var{initNonce} \\
        \end{array}
      \right)
      =
      \left(
        \begin{array}{c}
          \left(
            \begin{array}{c}
              \var{e} \\
              \emptyset \\
              \emptyset \\
              \left(
                \begin{array}{c}
                  \left(
                    \begin{array}{c}
                      0 \\
                      \var{reserves} \\
                    \end{array}
                  \right) \\
                  \left(
                    \begin{array}{c}
                      (\emptyset, \emptyset) \\
                      (\emptyset, \emptyset) \\
                      (\emptyset, \emptyset) \\
                      \emptyset \\
                      \emptyset \\
                      0
                    \end{array}
                  \right) \\
                  \left(
                    \begin{array}{c}
                      \left(
                        \begin{array}{c}
                          \var{utxo} \\
                          0 \\
                          0 \\
                          (\emptyset,~\emptyset) \\
                        \end{array}
                      \right) \\
                      \left(
                        \begin{array}{c}
                        \left(
                          \begin{array}{c}
                            \emptyset \\
                            \emptyset \\
                            \emptyset \\
                            \emptyset \\
                            \var{genDelegs} \\
                            \emptyset \\
                          \end{array}
                        \right) \\
                        \left(
                          \begin{array}{c}
                            \emptyset \\
                            \emptyset \\
                            \emptyset \\
                          \end{array}
                        \right) \\
                        \end{array}
                      \right) \\
                    \end{array}
                  \right) \\
                  \var{pp} \\
                  \var{pp} \\
                \end{array}
              \right) \\
              \\
              \Nothing \\
              \emptyset \\
              \var{os} \\
            \end{array}
          \right) \\
          \var{cs} \\
          \var{initNonce} \\
          \var{initNonce} \\
          \var{initNonce} \\
          0_{seed} \\
          \var{lab} \\
        \end{array}
      \right) \\
      & ~~~~\where cs = \{\var{hk}\mapsto 0~\mid~(\var{hk},~\wcard)\in\range{genDelegs}\} \\
\end{align*}$$

**Initial Shelley States**

*Byron to Shelley Transition* $$\begin{align*}
      & \fun{toShelley} \in \CEState \to \GenesisDelegation \to \BlockNo \to \type{ChainState}\\
      & \fun{toShelley}~
      \left(
        \begin{array}{c}
          \var{s_{last}} \\
          \wcard \\
          \var{h} \\
          (\var{utxo},~\var{reserves}) \\
          \wcard \\
          \var{us}
        \end{array}
      \right)~\var{gd}~\var{bn}
      =
      \fun{initialShelleyState}~
      \left(
        \begin{array}{c}
          (\var{s_{last}}~\var{bn},~\fun{prevHashToNonce}~ \var{h}) \\
          e \\
          \fun{hash}~{h} \\
          \var{utxo} \\
          \var{reserves} \\
          \var{gd} \\
          \fun{overlaySchedule}~\var{e}~\var{(\dom{gd})}~\var{pp} \\
          \var{pp} \\
          \fun{prevHashToNonce}~ \var{h} \\
        \end{array}
      \right) \\
      & ~~~~\where \\
      & ~~~~~~~~~e = \epoch{s_{last}} \\
      & ~~~~~~~~~pp = \fun{pps}~{us} \\   % this pps function is defined in the Byron chain spec
\end{align*}$$

**Byron to Shelley State Transtition**
