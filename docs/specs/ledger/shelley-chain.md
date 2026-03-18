# Blockchain layer
This chapter introduces the view of the blockchain layer as required for the ledger. This includes in particular the information required for the epoch boundary and its rewards calculation as described in Section sec:epoch. It also covers the transitions that keep track of produced blocks in order to calculate rewards and penalties for stake pools.

The main transition rule is $\mathsf{CHAIN}$ which calls the subrules $\mathsf{NEWEPOCH}$ and $\mathsf{UPDN}$, $\mathsf{VRF}$ and $\mathsf{BBODY}$.

## Verifiable Random Functions (VRF)
*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{seed} & \mathsf{Seed}  & \text{seed for pseudo-random number generator}\\
      \mathit{prf} & \mathsf{Proof}& \text{VRF proof}\\
    \end{array}
\end{equation*}$$ *Abstract functions ($T$ an arbitrary type)* $$\begin{equation*}
    \begin{array}{rlr}
      \star & \mathsf{Seed} \to \mathsf{Seed} \to \mathsf{Seed} & \text{binary seed operation} \\
      \mathsf{vrf}_{\mathsf{T}} ~  ~  & \mathsf{SKey} \to \mathsf{Seed} \to \mathsf{T}\times\mathsf{Proof}
                   & \text{verifiable random function} \\
                   %
      \mathsf{verifyVrf}_{\mathsf{T}} ~  ~  ~ & \mathsf{VKey} \to \mathsf{Seed} \to \mathsf{Proof}\times\mathsf{T}\to \mathsf{Bool}
                           & \text{verify vrf proof} \\
                           %
    \end{array}
\end{equation*}$$ *Derived Types* $$\begin{align*}
    \mathsf{PoolDistr}= \mathsf{KeyHash}_{pool} \mapsto \left([0, 1]\times\mathsf{KeyHash}_{vrf}\right)
      \text{ \hspace{1cm}stake pool distribution}
\end{align*}$$

*Constraints* $$\begin{align*}
    & \forall (sk, vk) \in \mathsf{KeyPair},~ seed \in \mathsf{Seed},~
    \mathsf{verifyVrf}_{T} ~ vk ~ seed ~\left(\mathsf{vrf}_{T} ~ sk ~ seed\right)
\end{align*}$$ *Constants* $$\begin{align*}
    & 0_{seed} \in \mathsf{Seed} & \text{neutral seed element} \\
    & \mathsf{Seed}_\ell\in \mathsf{Seed} & \text{leader seed constant} \\
    & \mathsf{Seed}_\eta\in \mathsf{Seed} & \text{nonce seed constant}\\
\end{align*}$$

**VRF definitions**
## Block Definitions
*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{h} & \mathsf{HashHeader}& \text{hash of a block header}\\
      \mathit{hb} & \mathsf{HashBBody}& \text{hash of a block body}\\
      \mathit{bn} & \mathsf{BlockNo} & \text{block number}\\
    \end{array}
\end{equation*}$$ *Operational Certificate* $$\begin{equation*}
    \mathsf{OCert}=
    \left(
      \begin{array}{rlr}
        \mathit{vk_{hot}} & \mathsf{VKeyEv} & \text{operational (hot) key}\\
        \mathit{n} & \N & \text{certificate issue number}\\
        c_0 & \mathsf{KESPeriod} & \text{start KES period}\\
        \sigma & \mathsf{Sig} & \text{cold key signature}\\
      \end{array}
    \right)
\end{equation*}$$ *Block Header Body* $$\begin{equation*}
    \mathsf{BHBody}=
    \left(
      \begin{array}{rlr}
        \mathit{prev} & \mathsf{HashHeader}^? & \text{hash of previous block header}\\
        \mathit{vk} & \mathsf{VKey} & \text{block issuer}\\
        \mathit{vrfVk} & \mathsf{VKey} & \text{VRF verification key}\\
        \mathit{slot} & \mathsf{Slot} & \text{block slot}\\
        \eta & \mathsf{Seed} & \text{nonce}\\
        \mathit{prf}_{\eta} & \mathsf{Proof}& \text{nonce proof}\\
        \ell & [0,~1] & \text{leader election value}\\
        \mathit{prf_{\ell}} & \mathsf{Proof}& \text{leader election proof}\\
        \mathit{bsize} & \N & \text{size of the block body}\\
        \mathit{bhash} & \mathsf{HashBBody}& \text{block body hash}\\
        \mathit{oc} & \mathsf{OCert}& \text{operational certificate}\\
        \mathit{pv} & \mathsf{ProtVer} & \text{protocol version}\\
      \end{array}
    \right)
\end{equation*}$$ *Block Types* $$\begin{equation*}
    \begin{array}{rll}
      \mathit{bh}
      & \mathsf{BHeader}
      & \mathsf{BHBody}\times \mathsf{Sig}
      \\
      \mathit{b}
      & \mathsf{Block}
      & \mathsf{BHeader}\times \mathsf{Tx}^{*}
    \end{array}
\end{equation*}$$ *Abstract functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{bhHash}~ \mathit{} & \mathsf{BHeader}\to \mathsf{HashHeader}
                   & \text{hash of a block header} \\
      \mathsf{bHeaderSize}~ \mathit{} & \mathsf{BHeader}\to \N
                   & \text{size of a block header} \\
      \mathsf{bBodySize}~ \mathit{} & \mathsf{Tx}^{*} \to \N
                   & \text{size of a block body} \\
      \mathsf{slotToSeed}~ \mathit{} & \mathsf{Slot} \to \mathsf{Seed}
                    & \text{convert a slot to a seed} \\
      \mathsf{prevHashToNonce}~ \mathit{} & \mathsf{HashHeader}^? \to \mathsf{Seed}
                    & \text{convert an optional header hash to a seed} \\
      \mathsf{bbodyhash} & \mathsf{Tx}^{*} \to \mathsf{HashBBody}\\
    \end{array}
\end{equation*}$$ *Accessor Functions* $$\begin{equation*}
    \begin{array}{rlrlr}
      \mathsf{bheader} & \mathsf{Block} \to \mathsf{BHeader}&
      \mathsf{bhbody} & \mathsf{BHeader}\to \mathsf{BHBody}\\
      \mathsf{hsig} & \mathsf{BHeader}\to \mathsf{Sig} &
      \mathsf{bbody} & \mathsf{Block} \to \mathsf{Tx}^{*} \\
      \mathsf{bvkcold} & \mathsf{BHBody}\to \mathsf{VKey} &
      \mathsf{bvkvrf} & \mathsf{BHBody}\to \mathsf{VKey} \\
      \mathsf{bprev} & \mathsf{BHBody}\to \mathsf{HashHeader}^? &
      \mathsf{bslot} & \mathsf{BHBody}\to \mathsf{Slot} \\
      \mathsf{bblockno} & \mathsf{BHBody}\to \mathsf{BlockNo} &
      \mathsf{bnonce} & \mathsf{BHBody}\to \mathsf{Seed} \\
      \mathsf{\mathsf{bprf}_{n}~\mathit{}} & \mathsf{BHBody}\to \mathsf{Proof}&
      \mathsf{bleader} & \mathsf{BHBody}\to \N \\
      \mathsf{\mathsf{bprf}_{\ell}~\mathit{}} & \mathsf{BHBody}\to \mathsf{Proof}&
      \mathsf{hBbsize} & \mathsf{BHBody}\to \N \\
      \mathsf{bhash} & \mathsf{BHBody}\to \mathsf{HashBBody}&
      \mathsf{bocert} & \mathsf{BHBody}\to \mathsf{OCert}\\
    \end{array}
\end{equation*}$$

**Block Definitions**
## MIR Transition
The transition which moves the instantaneous rewards is $\mathsf{MIR}$. Figure 3 defines the types for the transition. It has no environment or signal, and the state is $\mathsf{EpochState}$.


*MIR Transitions* $$\begin{equation*}
    \vdash \mathit{\_} \xrightarrow[\mathsf{mir}]{}{} \mathit{\_} \subseteq
    \powerset (\mathsf{EpochState} \times \mathsf{EpochState})
\end{equation*}$$

**MIR transition-system types**
Figure 4 defines the MIR state transition.

If the reserve and treasury pots are large enough to cover the sum of the corresponding instantaneous rewards, the reward accounts are increased by the appropriate amount and the two pots are decreased appropriately. In either case, if the pots are large enough or not, we reset both of the instantaneous reward mappings back to the empty mapping.


$$\begin{equation}
\label{eq:mir}
    \inference[MIR]
    {
      (\mathit{rewards},~\mathit{delegations},~
      \mathit{ptrs},~\mathit{fGenDelegs},~\mathit{genDelegs},~\mathit{i_{rwd}})
        \mathrel{\mathop:}= \mathit{ds}
      \\
      (\mathit{treasury},~\mathit{reserves})\mathrel{\mathop:}=\mathit{acnt}
      &
      (\mathit{irReserves},~\mathit{irTreasury})\mathrel{\mathop:}=\mathit{i_{rwd}}
      \\~\\
      \mathit{irwdR}\mathrel{\mathop:}=
        \left\{
        \mathsf{addr_{rwd}}~\mathit{hk}\mapsto\mathit{val}
        ~\vert~\mathit{hk}\mapsto\mathit{val}\in(\mathrm{dom}~rewards)\lhd\mathit{irReserves}
        \right\}
      \\
      \mathit{irwdT}\mathrel{\mathop:}=
        \left\{
        \mathsf{addr_{rwd}}~\mathit{hk}\mapsto\mathit{val}
        ~\vert~\mathit{hk}\mapsto\mathit{val}\in(\mathrm{dom}~rewards)\lhd\mathit{irTreasury}
        \right\}
      \\~\\
      \mathit{totR}\mathrel{\mathop:}=\sum\limits_{\underline{\phantom{a}}\mapsto v\in\mathit{irwdR}}v
      &
      \mathit{totT}\mathrel{\mathop:}=\sum\limits_{\underline{\phantom{a}}\mapsto v\in\mathit{irwdT}}v
      \\
      \mathit{totR}\leq\mathit{reserves}
      &
      \mathit{totT}\leq\mathit{treasury}
      \\~\\
      \mathit{rewards'}\mathrel{\mathop:}=\mathit{rewards}\unionoverridePlus\mathit{irwdR}\unionoverridePlus\mathit{irwdT}
      \\
      \mathit{ds'} \mathrel{\mathop:}=
      (\mathsf{varUpdate}~\mathit{rewards}',~\mathit{delegations},~
      \mathit{ptrs},~\mathit{fGenDelegs},~\mathit{genDelegs},
      ~(\mathsf{varUpdate}~\emptyset,~\mathsf{varUpdate}~\emptyset))
    }
    {
      \vdash
      {\left(\begin{array}{c}
            \mathit{acnt} \\
            \mathit{ss} \\
            (\mathit{us},~(\mathit{ds},~\mathit{ps})) \\
            \mathit{prevPP} \\
            \mathit{pp} \\
      \end{array}\right)}
      \xrightarrow[\mathsf{mir}]{}{}
      {\left(\begin{array}{c}
            \varUpdate{(\mathsf{varUpdate}~\mathit{treasury}-\mathit{totT},~\mathsf{varUpdate}~\mathit{reserves}-\mathit{totR})} \\
            \mathit{ss} \\
            (\mathit{us},~(\mathsf{varUpdate}~\mathit{ds'},~\mathit{ps})) \\
            \mathit{prevPP} \\
            \mathit{pp} \\
      \end{array}\right)}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:mir-skip}
    \inference[MIR-Skip]
    {
      (\mathit{rewards},~\mathit{delegations},~
      \mathit{ptrs},~\mathit{fGenDelegs},~\mathit{genDelegs},~\mathit{i_{rwd}})
        \mathrel{\mathop:}= \mathit{ds}
      \\
      (\mathit{treasury},~\mathit{reserves})\mathrel{\mathop:}=\mathit{acnt}
      &
      (\mathit{irReserves},~\mathit{irTreasury})\mathrel{\mathop:}=\mathit{i_{rwd}}
      \\~\\
      \mathit{irwdR}\mathrel{\mathop:}=
        \left\{
        \mathsf{addr_{rwd}}~\mathit{hk}\mapsto\mathit{val}
        ~\vert~\mathit{hk}\mapsto\mathit{val}\in(\mathrm{dom}~rewards)\lhd\mathit{irReserves}
        \right\}
      \\
      \mathit{irwdT}\mathrel{\mathop:}=
        \left\{
        \mathsf{addr_{rwd}}~\mathit{hk}\mapsto\mathit{val}
        ~\vert~\mathit{hk}\mapsto\mathit{val}\in(\mathrm{dom}~rewards)\lhd\mathit{irTreasury}
        \right\}
      \\~\\
      \mathit{totR}\mathrel{\mathop:}=\sum\limits_{\underline{\phantom{a}}\mapsto v\in\mathit{irwdR}}v
      &
      \mathit{totT}\mathrel{\mathop:}=\sum\limits_{\underline{\phantom{a}}\mapsto v\in\mathit{irwdT}}v
      \\
      \mathit{totR}>\mathit{reserves}~\lor~\mathit{totT}>\mathit{treasury}
      \\~\\
      \mathit{ds'} \mathrel{\mathop:}=
      (\mathit{rewards},~\mathit{delegations},~
      \mathit{ptrs},~\mathit{fGenDelegs},~\mathit{genDelegs},
      ~(\mathsf{varUpdate}~\emptyset,~\mathsf{varUpdate}~\emptyset))
    }
    {
      \vdash
      {\left(\begin{array}{c}
            \mathit{acnt} \\
            \mathit{ss} \\
            (\mathit{us},~(\mathit{ds},~\mathit{ps})) \\
            \mathit{prevPP} \\
            \mathit{pp} \\
      \end{array}\right)}
      \xrightarrow[\mathsf{mir}]{}{}
      {\left(\begin{array}{c}
            \mathit{acnt} \\
            \mathit{ss} \\
            (\mathit{us},~(\mathsf{varUpdate}~\mathit{ds'},~\mathit{ps})) \\
            \mathit{prevPP} \\
            \mathit{pp} \\
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

Figure 5 also defines an abstract pseudorandom function $\mathsf{overlaySchedule}$ for creating the OBFT overlay schedule for each new epoch, as explained in section 3.8.2 of [@delegation_design]. The function takes a set of genesis keys, a seed, and the protocol parameters (of which the decentralization parameter $d$ and the active slot coeffient $f$ are used). It must create $(d\cdot\mathsf{SlotsPerEpoch})$-many OBFT slots, $(f\cdot d\cdot \mathsf{SlotsPerEpoch})$ of which are active.


*New Epoch environments* $$\begin{equation*}
    \mathsf{NewEpochEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{s} & \mathsf{Slot} & \text{current slot} \\
        \mathit{gkeys} & \mathbb{P}~\mathsf{KeyHashGen} & \text{genesis key hashes} \\
      \end{array}
    \right)
\end{equation*}$$ *New Epoch states* $$\begin{equation*}
    \mathsf{NewEpochState}=
    \left(
      \begin{array}{rlr}
        \mathit{e_\ell} & \mathsf{Epoch} & \text{last epoch} \\
        \mathit{b_{prev}} & \mathsf{BlocksMade} & \text{blocks made last epoch} \\
        \mathit{b_{cur}} & \mathsf{BlocksMade} & \text{blocks made this epoch} \\
        \mathit{es} & \mathsf{EpochState} & \text{epoch state} \\
        \mathit{ru} & \mathsf{RewardUpdate}^? & \text{reward update} \\
        \mathit{pd} & \mathsf{PoolDistr}& \text{pool stake distribution} \\
        \mathit{osched} & \mathsf{Slot}\mapsto\mathsf{KeyHashGen}^? & \text{OBFT overlay schedule} \\
      \end{array}
    \right)
\end{equation*}$$ *Abstract pseudorandom schedule function* $$\begin{align*}
    & \mathsf{overlaySchedule} \in \mathsf{Epoch} \to \mathbb{P}~\mathsf{KeyHashGen} \to \mathsf{PParams}
        \to (\mathsf{Slot}\mapsto\mathsf{KeyHashGen}^?) \\
\end{align*}$$ *Constraints* $$\begin{align*}
    \text{ given: }~\mathit{osched}\mathrel{\mathop:}=\mathsf{overlaySchedule}~\mathit{e}~\mathit{gkeys}~\mathit{pp} \\
    \mathrm{range}~osched\subseteq\mathit{gkeys} \\
    |\mathit{osched}| = \floor{(\mathsf{d}~\mathit{pp})\cdot\mathsf{SlotsPerEpoch}} \\
    |\{s\mapsto k\in\mathit{osched}~\mid~k\neq\mathsf{Nothing}\}| =
    \floor{\mathsf{ActiveSlotCoeff}(\mathsf{d}~\mathit{pp})\cdot\mathsf{SlotsPerEpoch}} \\
    \forall s\in\mathrm{dom}~osched,~\mathsf{epoch}~s=e\\
\end{align*}$$ *New Epoch Transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xrightarrow[\mathsf{newepoch}]{}{\_} \mathit{\_} \subseteq
    \powerset (\mathsf{NewEpochEnv}\times \mathsf{NewEpochState}\times \mathsf{Epoch} \times \mathsf{NewEpochState})
\end{equation*}$$ *Helper function* $$\begin{align*}
      & \mathsf{calculatePoolDistr} \in \mathsf{Snapshot} \to \mathsf{PoolDistr}\\
      & \mathsf{calculatePoolDistr}~(\mathit{stake},~\mathit{delegs},~\mathit{poolParams}) = \\
      & ~~~\left\{\mathit{hk_p}\mapsto(\sigma,~\mathsf{poolVRF}~\mathit{p})
            ~\Big\vert~
            {
              \begin{array}{rl}
                \mathit{hk_p}\mapsto\sigma & \mathit{sd} \\
                \mathit{hk_p}\mapsto\mathit{p} & \mathit{poolParams}
              \end{array}
            }
            \right\}\\
      & ~~~~\where \\
      & ~~~~~~~~~\mathit{total} = \sum_{\_ \mapsto c\in\mathit{stake}} c \\
      & ~~~~~~~~~\mathit{sd} = \mathsf{aggregate_{+}}~\left(\mathit{delegs}^{-1}\circ
                     \left\{\left(
                       \mathit{hk}, \frac{\mathit{c}}{\mathit{total}}
                     \right) \vert (\mathit{hk},
                     \mathit{c}) \in \mathit{stake}
                     \right\}\right) \\
\end{align*}$$

**NewEpoch transition-system types**
Figure 6 defines the new epoch state transition. It has three rules. The first rule describes the change in the case of $e$ being equal to the next epoch $e_\ell+ 1$. It also calls the $\mathsf{MIR}$ and $\mathsf{EPOCH}$ rules and checks that the reward update is net neutral with respect to the Ada in the system. This should always hold (by the definition of the $\mathsf{createRUpd}$ function) and is present only for extra assurance and for help in proving that Ada is preserved by this transition. The second rule deals with the case when the epoch signal $e$ is not one greater than the current epoch . This rule does not change the state. The third one deals with the case when the reward update is equal to $\mathsf{Nothing}$. This rule also does not change the state.

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
      \mathit{ru} \neq \mathsf{Nothing}
      &
      (\Delta t,~\Delta r,~\mathit{rs},~\Delta f)\mathrel{\mathop:}=\mathit{ru}
      \\
      \Delta t+~\Delta r+\left(\sum\limits_{\underline{\phantom{a}}\mapsto v\in\mathit{rs}} v\right)+\Delta f=0
      \\
      \mathit{es'}\mathrel{\mathop:}=\mathsf{applyRUpd}~\mathit{ru}~\mathit{es}
      &
      {
        \vdash
        \mathit{es'}
          \xrightarrow[\mathsf{\hyperref[fig:rules:mir]{mir}}]{}{}\mathit{es''}
      }
      &
      {
        \vdash
        \mathit{es''}
          \xrightarrow[\mathsf{\hyperref[fig:rules:epoch]{epoch}}]{}{\mathit{e}}\mathit{es'''}
      }
      \\~\\
      {\begin{array}{rl}
         (\mathit{acnt},~\mathit{ss},~\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{pp}) & \mathit{es'''} \\
         (\underline{\phantom{a}},~\mathit{pstake_{set}},~\underline{\phantom{a}},~\underline{\phantom{a}}) & \mathit{ss} \\
         \mathit{pd'} & \mathsf{calculatePoolDistr}~\mathit{pstake_{set}} \\
         \mathit{osched'} & \mathsf{overlaySchedule}~\mathit{e}~\mathit{gkeys}~\mathit{pp} \\
       \end{array}}
    }
    {
      {\begin{array}{c}
         \mathit{s} \\
         \mathit{gkeys} \\
       \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \mathit{e_\ell} \\
            \mathit{b_{prev}} \\
            \mathit{b_{cur}} \\
            \mathit{es} \\
            \mathit{ru} \\
            \mathit{pd} \\
            \mathit{osched} \\
      \end{array}\right)}
      \xrightarrow[\mathsf{newepoch}]{}{\mathit{e}}
      {\left(\begin{array}{c}
            \mathsf{varUpdate}~\mathit{e} \\
            \varUpdate{\mathit{b_{cur}}} \\
            \mathsf{varUpdate}~\emptyset \\
            \mathsf{varUpdate}~\mathit{es'''} \\
            \mathsf{varUpdate}~\mathsf{Nothing} \\
            \mathsf{varUpdate}~\mathit{pd}' \\
            \mathsf{varUpdate}~\mathit{osched}' \\
      \end{array}\right)}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:not-new-epoch}
    \inference[Not-New-Epoch]
    {
      (e_\ell,~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}})\mathrel{\mathop:}=\mathit{nes}
      &
      e \neq e_\ell + 1
    }
    {
      {\begin{array}{c}
          \mathit{s} \\
          \mathit{gkeys} \\
      \end{array}}
      \vdash\mathit{nes}\xrightarrow[\mathsf{newepoch}]{}{\mathit{e}} \mathit{nes}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:no-reward-update}
    \inference[No-Reward-Update]
    {
      (e_\ell,~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{ru},~\underline{\phantom{a}},~\underline{\phantom{a}})\mathrel{\mathop:}=\mathit{nes}
      &
      e = e_\ell + 1
      &
      \mathit{ru} = \mathsf{Nothing}
    }
    {
      {\begin{array}{c}
          \mathit{s} \\
          \mathit{gkeys} \\
      \end{array}}
      \vdash\mathit{nes}\xrightarrow[\mathsf{newepoch}]{}{\mathit{e}} \mathit{nes}
    }
\end{equation}$$

**New Epoch rules**
## Tick Nonce Transition
The Tick Nonce Transition is responsible for updating the epoch nonce and the previous hash nonce at the start of an epoch. Its environment is shown in Figure 7 and consists of the protocol parameters $\mathit{pp}$, the candidate nonce $\eta_c$ and the previous header hash as a nonce. Its state consists of the epoch nonce $\eta_0$ and the previous hash nonce.


*Tick Nonce environments* $$\begin{equation*}
    \mathsf{TickNonceEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{pp} & \mathsf{PParams} & \text{protocol parameters} \\
        \eta_c & \mathsf{Seed} & \text{candidate nonce} \\
        \eta_\mathit{ph} & \mathsf{Seed} & \text{previous header hash as nonce} \\
      \end{array}
    \right)
\end{equation*}$$ *Tick Nonce states* $$\begin{equation*}
    \mathsf{TickNonceState}=
    \left(
      \begin{array}{rlr}
        \eta_0 & \mathsf{Seed} & \text{epoch nonce} \\
        \eta_h & \mathsf{Seed} & \text{seed generated from hash of previous epoch} \\
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
        \mathit{pp} \\
        \eta_c \\
        \eta_\mathit{ph} \\
      \end{array}}
     \vdash
     {\left(\begin{array}{c}
           \eta_0 \\
           \eta_h \\
     \end{array}\right)}
     \xrightarrow[\mathsf{tickn}]{}{\mathsf{False}}
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
     \eta_e \mathrel{\mathop:}= \mathsf{extraEntropy}~\mathit{pp}
   }
   {
     {\begin{array}{c}
        \mathit{pp} \\
        \eta_c \\
        \eta_\mathit{ph} \\
      \end{array}}
     \vdash
     {\left(\begin{array}{c}
           \eta_0 \\
           \eta_h \\
     \end{array}\right)}
     \xrightarrow[\mathsf{tickn}]{}{\mathsf{True}}
     {\left(\begin{array}{c}
           \mathsf{varUpdate}~\eta_c \star \eta_h \star \eta_e \\
           \mathsf{varUpdate}~\eta_\mathit{ph} \\
     \end{array}\right)}
   }
\end{equation}$$

**Tick Nonce rules**
## Update Nonce Transition
The Update Nonce Transition updates the nonces until the randomness gets fixed. The environment is shown in Figure 9 and consists of the block nonce $\eta$. The update nonce state is shown in Figure 9 and consists of the candidate nonce $\eta_c$ and the evolving nonce $\eta_v$.


*Update Nonce environments* $$\begin{equation*}
    \mathsf{UpdateNonceEnv}=
    \left(
      \begin{array}{rlr}
        \eta & \mathsf{Seed} & \text{new nonce} \\
      \end{array}
    \right)
\end{equation*}$$ *Update Nonce states* $$\begin{equation*}
    \mathsf{UpdateNonceState}=
    \left(
      \begin{array}{rlr}
        \eta_v & \mathsf{Seed} & \text{evolving nonce} \\
        \eta_c & \mathsf{Seed} & \text{candidate nonce} \\
      \end{array}
    \right)
\end{equation*}$$ *Update Nonce Transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xrightarrow[\mathsf{updn}]{}{\_} \mathit{\_} \subseteq
    \powerset (\mathsf{UpdateNonceEnv}
               \times \mathsf{UpdateNonceState}
               \times \mathsf{Slot}
               \times \mathsf{UpdateNonceState}
              )
\end{equation*}$$

**UpdNonce transition-system types**
The transition rule $\mathsf{UPDN}$ takes the slot as signal. There are two different cases for $\mathsf{UPDN}$: one where is not yet slots from the beginning of the next epoch and one where is less than slots until the start of the next epoch.

Note that in eq:update-both, the nonce candidate $\eta_c$ transitions to $\eta_v\star\eta$, not $\eta_c\star\eta$. The reason for this is that even though the nonce candidate is frozen sometime during the epoch, we want the two nonces to again be equal at the start of a new epoch (so that the entropy added near the end of the epoch is not discarded).


$$\begin{equation}
\label{eq:update-both}
    \inference[Update-Both]
    {
      s < \mathsf{firstSlot}~((\mathsf{epoch}~s) + 1) - \mathsf{RandomnessStabilisationWindow}
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
      \xrightarrow[\mathsf{updn}]{}{\mathit{s}}
      {\left(\begin{array}{c}
            \mathsf{varUpdate}~\eta_v\star\eta \\
            \mathsf{varUpdate}~\eta_v\star\eta \\
      \end{array}\right)}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:only-evolve}
    \inference[Only-Evolve]
    {
      s \geq \mathsf{firstSlot}~((\mathsf{epoch}~s) + 1) - \mathsf{RandomnessStabilisationWindow}
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
      \xrightarrow[\mathsf{updn}]{}{\mathit{s}}
      {\left(\begin{array}{c}
            \mathsf{varUpdate}~\eta_v\star\eta \\
            \eta_c \\
      \end{array}\right)}
    }
\end{equation}$$

**Update Nonce rules**
## Reward Update Transition
The Reward Update Transition calculates a new $\mathsf{RewardUpdate}$ to apply in a $\mathsf{NEWEPOCH}$ transition. The environment is shown in Figure 11, it consists of the produced blocks mapping and the epoch state . Its state is an optional reward update.


*Reward Update environments* $$\begin{equation*}
    \mathsf{RUpdEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{b} & \mathsf{BlocksMade} & \text{blocks made} \\
        \mathit{es} & \mathsf{EpochState} & \text{epoch state} \\
      \end{array}
    \right)
\end{equation*}$$ *Reward Update Transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xrightarrow[\mathsf{rupd}]{}{\_} \mathit{\_} \subseteq
    \powerset (\mathsf{RUpdEnv}\times \mathsf{RewardUpdate}^? \times \mathsf{Slot} \times \mathsf{RewardUpdate}^?)
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
      s > \mathsf{firstSlot}~(\mathsf{epoch}~s) + \mathsf{StabilityWindow}
      &
      ru = \mathsf{Nothing}
      \\~\\
      ru' \mathrel{\mathop:}= \mathsf{createRUpd}~\mathsf{SlotsPerEpoch}~b~es~\mathsf{MaxLovelaceSupply}
    }
    {
      {\begin{array}{c}
         \mathit{b} \\
         \mathit{es} \\
       \end{array}}
      \vdash
      \mathit{ru}\xrightarrow[\mathsf{rupd}]{}{\mathit{s}}\mathsf{varUpdate}~\mathit{ru}'
    }
\end{equation}$$

$$\begin{equation}
\label{eq:no-reward-update}
    \inference[Reward-Update-Exists]
    {
      ru \neq \mathsf{Nothing}
    }
    {
      {\begin{array}{c}
         \mathit{b} \\
         \mathit{es} \\
       \end{array}}
      \vdash
      \mathit{ru}\xrightarrow[\mathsf{rupd}]{}{\mathit{s}}\mathit{ru}
    }
\end{equation}$$

$$\begin{equation}
\label{eq:reward-too-early}
    \inference[Reward-Too-Early]
    {
      ru = \mathsf{Nothing}
      \\
      s \leq \mathsf{firstSlot}~(\mathsf{epoch}~s) + \mathsf{StabilityWindow}
    }
    {
      {\begin{array}{c}
         \mathit{b} \\
         \mathit{es} \\
       \end{array}}
      \vdash
      \mathit{ru}\xrightarrow[\mathsf{rupd}]{}{\mathit{s}}\mathit{ru}
    }
\end{equation}$$

**Reward Update rules**
## Chain Tick Transition
The Chain Tick Transition performs some chain level upkeep. The environment consists of a set of genesis keys, and the state is the epoch specific state necessary for the $\mathsf{NEWEPOCH}$ transition.

Part of the upkeep is updating the genesis key delegation mapping according to the future delegation mapping. For each genesis key, we adopt the most recent delegation in $\mathit{fGenDelegs}$ that is past the current slot, and any future genesis key delegations past the current slot is removed. The helper function $\mathsf{adoptGenesisDelegs}$ accomplishes the update.


*Chain Tick Transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xrightarrow[\mathsf{tick}]{}{\_} \mathit{\_} \subseteq
    \powerset (\mathbb{P}~\mathsf{KeyHashGen} \times \mathsf{NewEpochState}\times \mathsf{Slot} \times \mathsf{NewEpochState})
\end{equation*}$$

*helper function* $$\begin{align*}
      & \mathsf{adoptGenesisDelegs} \in \mathsf{EpochState} \to \mathsf{Slot} \to EpochState
      \\
      & \mathsf{adoptGenesisDelegs}~\mathit{es}~\mathit{slot} = \mathit{es'}
      \\
      & ~~~~\where
      \\
      & ~~~~~~~~~~
      (\mathit{acnt},~\mathit{ss},(\mathit{us},(\mathit{ds},\mathit{ps})),~\mathit{prevPp},~\mathit{pp})
      \mathrel{\mathop:}=\mathit{es}
      \\
      & ~~~~~~~~~~
      (~\mathit{rewards},~\mathit{delegations},~\mathit{ptrs},
      ~\mathit{fGenDelegs},~\mathit{genDelegs},~\mathit{i_{rwd}})\mathrel{\mathop:}=\mathit{ds}
      \\
      & ~~~~~~~~~~\mathit{curr}\mathrel{\mathop:}=
        \{
          (\mathit{s},~\mathit{gkh})\mapsto(\mathit{vkh},~\mathit{vrf})\in\mathit{fGenDelegs}
          ~\mid~
          \mathit{s}\leq\mathit{slot}
        \}
      \\
      & ~~~~~~~~~~\mathit{fGenDelegs'}\mathrel{\mathop:}=
          \mathit{fGenDelegs}\setminus\mathit{curr}
      \\
      & ~~~~~~~~~~\mathit{genDelegs'}\mathrel{\mathop:}=
          \left\{
            \mathit{gkh}\mapsto(\mathit{vkh},~\mathit{vrf})
            ~\mathrel{\Bigg|}~
            {
              \begin{array}{l}
                (\mathit{s},~\mathit{gkh})\mapsto(\mathit{vkh},~\mathit{vrf})\in\mathit{curr}\\
                \mathit{s}=\max\{s'~\mid~(s',~\mathit{gkh})\in\mathrm{dom}~\mathit{curr}\}
              \end{array}
            }
          \right\}
      \\
      & ~~~~~~~~~~\mathit{ds'}\mathrel{\mathop:}=
          (\mathit{stkeys},~\mathit{rewards},~\mathit{delegations},~\mathit{ptrs},
          ~\mathit{fGenDelegs'},~\mathit{genDelegs}\unionoverrideRight\mathit{genDelegs'},~\mathit{i_{rwd}})
      \\
      & ~~~~~~~~~~\mathit{es'}\mathrel{\mathop:}=
      (\mathit{acnt},~\mathit{ss},(\mathit{us},(\mathit{ds'},\mathit{ps})),~\mathit{prevPp},~\mathit{pp})
\end{align*}$$

**Tick transition-system types**
The $\mathsf{TICK}$ transition rule is shown in Figure 14. The signal is a slot .

Three transitions are done:

- The $\mathsf{NEWEPOCH}$ transition performs any state change needed if it is the first block of a new epoch.

- The $\mathsf{RUPD}$ creates the reward update if it is late enough in the epoch. **Note** that for every block header, either $\mathsf{NEWEPOCH}$ or $\mathsf{RUPD}$ will be the identity transition, and so, for instance, it does not matter if $\mathsf{RUPD}$ uses $\mathit{nes}$ or $\mathit{nes}'$ to obtain the needed state.


$$\begin{equation}
\label{eq:tick}
    \inference[Tick]
    {
      {
        {\begin{array}{c}
           \mathit{slot} \\
           \mathit{gkeys} \\
         \end{array}}
        \vdash
        \mathit{nes}
        \xrightarrow[\mathsf{\hyperref[fig:rules:new-epoch]{newepoch}}]{}{\mathsf{epoch}~slot}
        \mathit{nes}'
      }
      \\~\\
      (\underline{\phantom{a}},~\mathit{b_{prev}},~\underline{\phantom{a}},~\mathit{es},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}})\mathrel{\mathop:}=\mathit{nes} \\
      \\~\\
      {
        {\begin{array}{c}
           \mathit{b_{prev}} \\
           \mathit{es} \\
         \end{array}}
        \vdash \mathit{ru'}\xrightarrow[\mathsf{\hyperref[fig:rules:reward-update]{rupd}}]{}{\mathit{slot}} \mathit{ru''}
      }
      \\~\\
      (\mathit{e_\ell'},~\mathit{b_{prev}'},~\mathit{b_{cur}'},~\mathit{es'},~\mathit{ru'},~\mathit{pd'},\mathit{osched'})
      \mathrel{\mathop:}=\mathit{nes'}
      \\
      \mathit{es''}\mathrel{\mathop:}=\mathsf{adoptGenesisDelegs}~\mathit{es'}~\mathit{slot}
      \\
      \mathit{nes''}\mathrel{\mathop:}=
      (\mathit{e_\ell'},~\mathit{b_{prev}'},~\mathit{b_{cur}'},~\mathit{es''},~\mathit{ru''},~\mathit{pd'},\mathit{osched'})
      \\~\\
    }
    {
      {\begin{array}{c}
         \mathit{gkeys} \\
       \end{array}}
      \vdash\mathit{nes}\xrightarrow[\mathsf{tick}]{}{\mathit{slot}}\mathsf{varUpdate}~\mathit{nes''}
    }
\end{equation}$$

**Tick rules**
## Operational Certificate Transition
The Operational Certificate Transition environment consists of the genesis key delegation map $\mathit{genDelegs}$ and the set of stake pools $\mathit{stpools}$. Its state is the mapping of operation certificate issue numbers. Its signal is a block header.


*Operational Certificate environments* $$\begin{equation*}
    \mathsf{OCertEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{stpools} & \mathbb{P}~\mathsf{KeyHash} & \text{stake pools} \\
        \mathit{genDelegs} & \mathbb{P}~\mathsf{KeyHash} & \text{genesis key delegates}\\
      \end{array}
    \right)
\end{equation*}$$ *Operational Certificate Transitions* $$\begin{equation*}
    \mathit{\_} \vdash \mathit{\_} \xrightarrow[\mathsf{ocert}]{}{\_} \mathit{\_} \subseteq
    \powerset (\mathsf{OCertEnv}\times \mathsf{KeyHash}_{pool} \mapsto \N \times \mathsf{BHeader}\times \mathsf{KeyHash}_{pool} \mapsto \N)
\end{equation*}$$ *Operational Certificate helper function* $$\begin{align*}
      & \mathsf{currentIssueNo} \in \mathsf{OCertEnv}\to (\mathsf{KeyHash}_{pool} \mapsto \N)
                                           \to \mathsf{KeyHash}_{pool}
                                           \to \N^? \\
      & \mathsf{currentIssueNo}~(\mathit{stpools}, \mathit{genDelegs})~ \mathit{cs} ~\mathit{hk} =
      \begin{cases}
        \mathit{hk}\mapsto \mathit{n} \in \mathit{cs} & n \\
        \mathit{hk} \in \mathit{stpools} & 0 \\
        \mathit{hk} \in \mathit{genDelegs} & 0 \\
        \text{otherwise} & \mathsf{Nothing}
      \end{cases}
\end{align*}$$

**OCert transition-system types**
The transition rule is shown in Figure 16. From the block header body we first extract the following:

- The operational certificate, consisting of the hot key , the certificate issue number , the KES period start and the cold key signature.

- The cold key .

- The slot for the block.

- The number of KES periods that have elapsed since the start period on the certificate.

Using this we verify the preconditions of the operational certificate state transition which are the following:

- The KES period of the slot in the block header body must be greater than or equal to the start value listed in the operational certificate, and less than $\mathsf{MaxKESEvo}$-many KES periods after . The value of $\mathsf{MaxKESEvo}$ is the agreed-upon lifetime of an operational certificate, see [@delegation_design].

- exists as key in the mapping of certificate issues numbers to a KES period and that period is less than or equal to .

- The signature $\tau$ can be verified with the cold verification key .

- The KES signature $\sigma$ can be verified with the hot verification key .

After this, the transition system updates the operational certificate state by updating the mapping of operational certificates where it overwrites the entry of the key with the KES period .


$$\begin{equation}
\label{eq:ocert}
    \inference[OCert]
    {
      (\mathit{bhb},~\sigma)\mathrel{\mathop:}=\mathit{bh}
      &
      (\mathit{vk_{hot}},~n,~c_{0},~\tau) \mathrel{\mathop:}= \mathsf{bocert}~\mathit{bhb}
      &
      \mathit{vk_{cold}} \mathrel{\mathop:}= \mathsf{bvkcold}~\mathit{bhb}
      \\
      \mathit{hk} \mathrel{\mathop:}= \mathsf{hashKey}~vk_{cold}
      &
      \mathit{s}\mathrel{\mathop:}=\mathsf{bslot}~bhb
      &
      t \mathrel{\mathop:}= \mathsf{kesPeriod}~s - c_0
      \\~\\
      c_0 \leq \mathsf{kesPeriod}~s < c_0 + \mathsf{MaxKESEvo}
      \\
      \mathsf{currentIssueNo} ~ \mathit{oce} ~ \mathit{cs} ~ \mathit{hk} = m
      &
      m \leq n
      \\~\\
      \mathcal{V}_{\mathit{vk_{cold}}}{\lbrack\!\lbrack \mathit{(\mathit{vk_{hot}},~n,~c_0)} \rbrack\!\rbrack}_{\tau}
      &
      \mathcal{V}^{\mathsf{KES}}_{vk_{hot}}{\lbrack\!\lbrack \mathit{bhb} \rbrack\!\rbrack}_{\sigma}^{t}
      \\
    }
    {
      \mathit{oce}\vdash\mathit{cs}
      \xrightarrow[\mathsf{ocert}]{}{\mathit{bh}}\varUpdate{\mathit{cs}\unionoverrideRight\{\mathit{hk}\mapsto n\}}
    }
\end{equation}$$

**OCert rules**
The OCERT rule has six predicate failures:

- If the KES period is less than the KES period start in the certificate, there is a *KESBeforeStart* failure.

- If the KES period is greater than or equal to the KES period end (start + $\mathsf{MaxKESEvo}$) in the certificate, there is a *KESAfterEnd* failure.

- If the period counter in the original key hash counter mapping is larger than the period number in the certificate, there is a *CounterTooSmall* failure.

- If the signature of the hot key, KES period number and period start is incorrect, there is an *InvalidSignature* failure.

- If the KES signature using the hot key of the block header body is incorrect, there is an *InvalideKesSignature* failure.

- If there is no entry in the key hash to counter mapping for the cold key, there is a *NoCounterForKeyHash* failure.

## Verifiable Random Function
In this section we define a function $\mathsf{vrfChecks}$ which performs all the VRF related checks on a given block header body. In addition to the block header body, the function requires the epoch nonce, the stake distribution (aggregated by pool), and the active slots coefficient from the protocol parameters. The function checks:

- The validity of the proofs for the leader value and the new nonce.

- The verification key is associated with relative stake $\sigma$ in the stake distribution.

- The $\mathsf{bleader}$ value of indicates a possible leader for this slot. The function $\mathsf{checkLeaderVal}$ is defined in sec:leader-value-calc.


*VRF helper function* $$\begin{align*}
      & \mathsf{vrfChecks} \in \mathsf{Seed} \to \mathsf{BHBody}\to \mathsf{Bool} \\
      & \mathsf{vrfChecks}~\eta_0~\mathit{bhb} = \\
      & \begin{array}{cl}
        ~~~~ &
             \mathsf{verifyVrf}_{\mathsf{Seed}} ~ \mathit{vrfVk} ~ ((\eta_0\star ss)\star\mathsf{Seed}_\eta) ~(\mathsf{bprf}_{n}~\mathit{bhb},~\mathsf{bnonce}~\mathit{bhb}) \\
        ~~~~ \land &
             \mathsf{verifyVrf}_{[0,~1]} ~ \mathit{vrfVk} ~ ((\eta_0\star ss)\star\mathsf{Seed}_\ell) ~(\mathsf{bprf}_{\ell}~\mathit{bhb},~\mathsf{bleader}~\mathit{bhb}) \\
      \end{array} \\
      & ~~~~\where \\
      & ~~~~~~~~~~\mathit{ss} \mathrel{\mathop:}= \mathsf{slotToSeed}~ \mathit{(\mathsf{bslot}~bhb)} \\
      & ~~~~~~~~~~\mathit{vrfVk} \mathrel{\mathop:}= \mathsf{bvkvrf}~\mathit{bhb} \\
\end{align*}$$ $$\begin{align*}
      & \mathsf{praosVrfChecks} \in \mathsf{Seed} \to \mathsf{PoolDistr}\to [0,~1] \to \mathsf{BHBody}\to \mathsf{Bool} \\
      & \mathsf{praosVrfChecks}~\eta_0~\mathit{pd}~\mathit{f}~\mathit{bhb} = \\
      & \begin{array}{cl}
        ~~~~ & \mathit{hk}\mapsto (\sigma,~\mathit{hk_{vrf}})\in\mathit{pd} \\
        ~~~~ \land & \mathsf{vrfChecks}~\eta_0~\mathit{bhb} \\
        ~~~~ \land & \mathsf{checkLeaderVal}~(\mathsf{bleader}~\mathit{bhb})~\sigma~\mathit{f} \\
      \end{array} \\
      & ~~~~\where \\
      & ~~~~~~~~~~\mathit{hk} \mathrel{\mathop:}= \mathsf{hashKey}~(\mathsf{bvkcold}~\mathit{b}hb) \\
      & ~~~~~~~~~~\mathit{hk_{vrf}} \mathrel{\mathop:}= \mathsf{hashKey}~(\mathsf{bvkvrf}~\mathit{bhb}) \\
\end{align*}$$ $$\begin{align*}
      & \mathsf{pbftVrfChecks} \in \mathsf{KeyHash}_{vrf} \to \mathsf{Seed} \to \mathsf{BHBody}\to \mathsf{Bool} \\
      & \mathsf{pbftVrfChecks}~\mathit{vrfh}~\eta_0~~\mathit{bhb} = \\
      & \begin{array}{cl}
        ~~~~ & \mathit{vrfh} = \mathsf{hashKey}~(\mathsf{bvkvrf}~\mathit{bhb}) \\
        ~~~~ \land & \mathsf{vrfChecks}~\eta_0~\mathit{bhb} \\
      \end{array} \\
\end{align*}$$ []{#fig:vrf-checks label="fig:vrf-checks"}

## Overlay Schedule
The transition from the bootstrap era to a fully decentralized network is explained in section 3.9.2 of [@delegation_design]. Key to this transition is a protocol parameter $d$ which controls how many slots are governed by the genesis nodes via OBFT, and which slots are open to any registered stake pool. The transition system introduced in this section, $\mathsf{OVERLAY}$, covers this mechanism.

This transition is responsible for validating the protocol for both the OBFT blocks and the Praos blocks, depending on the overlay schedule.

The environments for this transition are:

- A mapping $\mathit{osched}$ of slots to an optional genesis key. In the terminology of [@delegation_design], the slots in $\mathit{osched}$ are the "OBFT slots". A slot in this map with a value of $\mathsf{Nothing}$ is a non-active slot, otherwise it is an active slot and its value designates the genesis key responsible for producing the block.

- The epoch nonce $\eta_0$.

- The stake pool stake distribution $\mathit{pd}$.

- The mapping $\mathit{genDelegs}$ of genesis keys to their cold keys and vrf keys.

The states for this transition consist only of the mapping of certificate issue numbers.

This transition establishes that a block producer is in fact authorized. Since there are three key pairs involved (cold keys, VRF keys, and hot KES keys) it is worth examining the interaction closely. First we look at the regular Praos/decentralized setting, which is given by Equation eq:decentralized.

- First we check the operational certificate with $\mathsf{OCERT}$. This uses the cold verification key given in the block header. We do not yet trust that this key is a registered pool key. If this transition is successful, we know that the cold key in the block header has authorized the block.

- Next, in the $\mathsf{vrfChecks}$ predicate, we check that the hash of this cold key is in the mapping $\mathit{pd}$, and that it maps to $(\sigma,~\mathit{hk_{vrf}})$, where $(\sigma,~\mathit{hk_{vrf}})$ is the hash of the VRF key in the header. If $\mathsf{praosVrfChecks}$ returns true, then we know that the cold key in the block header was a registered stake pool at the beginning of the previous epoch, and that it is indeed registered with the VRF key listed in the header.

- Finally, we use the VRF verification key in the header, along with the VRF proofs in the header, to check that the operator is allowed to produce the block.

The situation for the overlay schedule, given by Equation eq:active-pbft, is similar. The difference is that we check the overlay schedule to see what core node is supposed to make a block, and then use the genesis delegation mapping to check the correct cold key hash and vrf key hash.


*Overlay environments* $$\begin{equation*}
    \mathsf{OverlayEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{osched} & \mathsf{Slot}\mapsto\mathsf{KeyHashGen}^? & \text{OBFT overlay schedule} \\
        \eta_0 & \mathsf{Seed} & \text{epoch nonce} \\
        \mathit{pd} & \mathsf{PoolDistr}& \text{pool stake distribution} \\
        \mathit{genDelegs} & \mathsf{GenesisDelegation} & \text{genesis key delegations} \\
      \end{array}
    \right)
\end{equation*}$$ *Overlay Transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xrightarrow[\mathsf{overlay}]{}{\_} \mathit{\_} \subseteq
    \powerset (\mathsf{OverlayEnv}\times (\mathsf{KeyHash}_{pool} \mapsto \N) \times \mathsf{BHeader}\times
    (\mathsf{KeyHash}_{pool} \mapsto \N))
\end{equation*}$$

**Overlay transition-system types**
$$\begin{equation}
\label{eq:active-pbft}
    \inference[Active-OBFT]
    {
      \mathit{bhb}\mathrel{\mathop:}=\mathsf{bheader}~\mathit{bh}
      &
      \mathit{vk}\mathrel{\mathop:}=\mathsf{bvkcold}~\mathit{bhb}
      &
      \mathit{vkh}\mathrel{\mathop:}=\mathsf{hashKey}~vk
      \\
      \bslot bhb \mapsto \mathit{gkh}\in\mathit{osched}
      &
      \mathit{gkh}\mapsto(\mathit{vkh},~\mathit{vrfh})\in\mathit{genDelegs}
      \\~\\
      \mathsf{pbftVrfChecks}~\mathit{vrfh}~\eta_0~\mathit{bhb}
      \\~\\
      {
        {\begin{array}{c}
         \mathrm{dom}~\mathit{pd} \\
         \mathrm{range}~\mathit{genDelegs} \\
         \end{array}
        }
        \vdash\mathit{cs}\xrightarrow[\mathsf{\hyperref[fig:rules:ocert]{ocert}}]{}{\mathit{bh}}\mathit{cs'}
      }
    }
    {
      {\begin{array}{c}
         \mathit{osched} \\
         \eta_0 \\
         \mathit{pd} \\
         \mathit{genDelegs} \\
       \end{array}}
      \vdash
      \mathit{cs}
      \xrightarrow[\mathsf{overlay}]{}{\mathit{bh}}
      \mathsf{varUpdate}~\mathit{cs}'
    }
\end{equation}$$

$$\begin{equation}
\label{eq:decentralized}
    \inference[Decentralized]
    {
      \mathit{bhb}\mathrel{\mathop:}=\mathsf{bheader}~\mathit{bh}
      \\
      \mathsf{bslot}~bhb \notin \mathrm{dom}~\mathit{osched}
      \\~\\
      {
        \vdash\mathit{cs}\xrightarrow[\mathsf{\hyperref[fig:rules:ocert]{ocert}}]{}{\mathit{bh}}\mathit{cs'}
      }
      \\~\\
      \mathsf{praosVrfChecks}~\eta_0~\mathit{pd}~\mathsf{ActiveSlotCoeff}~\mathit{bhb}
    }
    {
      {\begin{array}{c}
         \mathit{osched} \\
         \eta_0 \\
         \mathit{pd} \\
         \mathit{genDelegs} \\
       \end{array}}
      \vdash
      \mathit{cs}
      \xrightarrow[\mathsf{overlay}]{}{\mathit{bh}}
      \mathsf{varUpdate}~\mathit{cs}'
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
    \mathsf{PrtclEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{osched} & \mathsf{Slot}\mapsto\mathsf{KeyHashGen}^? & \text{OBFT overlay schedule} \\
        \mathit{pd} & \mathsf{PoolDistr}& \text{pool stake distribution} \\
        \mathit{dms} & \mathsf{KeyHashGen}\mapsto\mathsf{KeyHash} & \text{genesis key delegations} \\
      \end{array}
    \right)
\end{equation*}$$ *Protocol states* $$\begin{equation*}
    \mathsf{PrtclState}=
    \left(
      \begin{array}{rlr}
        \mathit{cs} & \mathsf{KeyHash}_{pool} \mapsto \N & \text{operational certificate issues numbers} \\
        \eta_v & \mathsf{Seed} & \text{evolving nonce} \\
        \eta_c & \mathsf{Seed} & \text{candidate nonce} \\
      \end{array}
    \right)
\end{equation*}$$ *Protocol Transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xrightarrow[\mathsf{prtcl}]{}{\_} \mathit{\_} \subseteq
    \powerset (\mathbb{P}~\mathsf{PrtclEnv} \times \mathsf{PrtclState}\times \mathsf{BHeader}\times \mathsf{PrtclState})
\end{equation*}$$

**Protocol transition-system types**
The environments for this transition are:

- A mapping $\mathit{osched}$ of slots to an optional genesis key. In the terminology of [@delegation_design], the slots in $\mathit{osched}$ are the "OBFT slots". A slot in this map with a value of $\mathsf{Nothing}$ is a non-active slot, otherwise it is an active slot and its value designates the genesis key responsible for producing the block.

- The stake pool stake distribution $\mathit{pd}$.

- The mapping $\mathit{dms}$ of genesis keys to their cold keys.

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
      \eta\mathrel{\mathop:}=\mathsf{bnonce}~(\mathsf{bhbody}~bhb)
      \\~\\
      {
        \eta
        \vdash
        {\left(\begin{array}{c}
        \eta_v \\
        \eta_c \\
        \end{array}\right)}
        \xrightarrow[\mathsf{\hyperref[fig:rules:update-nonce]{updn}}]{}{\mathit{slot}}
        {\left(\begin{array}{c}
        \eta_v' \\
        \eta_c' \\
        \end{array}\right)}
      }\\~\\
      {
        {\begin{array}{c}
          \mathit{osched} \\
          \eta_0 \\
          \mathit{pd} \\
          \mathit{dms} \\
        \end{array}
        }
        \vdash \mathit{cs}\xrightarrow[\mathsf{\hyperref[fig:rules:overlay]{overlay}}]{}{\mathit{bh}} \mathit{cs}'
      }
    }
    {
      {\begin{array}{c}
         \mathit{osched} \\
         \mathit{pd} \\
         \mathit{dms} \\
         \eta_0 \\
       \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \mathit{cs} \\
            \eta_v \\
            \eta_c \\
      \end{array}\right)}
      \xrightarrow[\mathsf{prtcl}]{}{\mathit{bh}}
      {\left(\begin{array}{c}
            \mathsf{varUpdate}~cs' \\
            \mathsf{varUpdate}~\eta_v' \\
            \mathsf{varUpdate}~\eta_c' \\
      \end{array}\right)}
    }
\end{equation}$$

**Protocol rules**
The PRTCL rule has no predicate failures.

## Block Body Transition
The Block Body Transition updates the block body state which comprises the ledger state and the map describing the produced blocks. The environment of the $\mathsf{BBODY}$ transition are overlay schedule slots, the protocol parameters, and the accounting state. The environments and states are defined in Figure 22, along with a helper function $\mathsf{incrBlocks}$, which counts the number of non-overlay blocks produced by each stake pool.


*BBody environments* $$\begin{equation*}
    \mathsf{BBodyEnv}=
    \left(
      \begin{array}{rlr}
        \mathit{oslots} & \mathbb{P}~\mathsf{Slot} & \text{overlay slots} \\
        \mathit{pp} & \mathsf{PParams} & \text{protocol parameters} \\
        \mathit{acnt} & \mathsf{Acnt} & \text{accounting state}
      \end{array}
    \right)
\end{equation*}$$ *BBody states* $$\begin{equation*}
    \mathsf{BBodyState}=
    \left(
      \begin{array}{rlr}
        \mathit{ls} & \mathsf{LState} & \text{ledger state} \\
        \mathit{b} & \mathsf{BlocksMade} & \text{blocks made} \\
      \end{array}
    \right)
\end{equation*}$$ *BBody Transitions* $$\begin{equation*}
    \_ \vdash \mathit{\_} \xrightarrow[\mathsf{bbody}]{}{\_} \mathit{\_} \subseteq
    \powerset (\mathsf{BBodyEnv}\times \mathsf{BBodyState}\times \mathsf{Block} \times \mathsf{BBodyState})
\end{equation*}$$

*BBody helper function* $$\begin{align*}
      & \mathsf{incrBlocks} \in \mathsf{Bool} \to \mathsf{KeyHash}_{pool} \to
          \mathsf{BlocksMade} \to \mathsf{BlocksMade} \\
      & \mathsf{incrBlocks}~\mathit{isOverlay}~\mathit{hk}~\mathit{b} =
        \begin{cases}
          b & \text{if }\mathit{isOverlay} \\
          b\cup\{\mathit{hk}\mapsto 1\} & \text{if }\mathit{hk}\notin\mathrm{dom}~b \\
          b\unionoverrideRight\{\mathit{hk}\mapsto n+1\} & \text{if }\mathit{hk}\mapsto n\in b \\
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
      \mathit{txs} \mathrel{\mathop:}= \mathsf{bbody}~block
      &
      \mathit{bhb} \mathrel{\mathop:}= \mathsf{bhbody}~(\mathsf{bheader}~\mathit{block})
      &
      \mathit{hk} \mathrel{\mathop:}= \mathsf{hashKey}~(\mathsf{bvkcold}~\mathit{bhb})
      \\~\\
      \mathsf{bBodySize}~ \mathit{txs} = \mathsf{hBbsize}~\mathit{bhb}
      &
      \mathsf{bbodyhash}~{txs} = \mathsf{bhash}~\mathit{bhb}
      \\~\\
      {
        {\begin{array}{c}
                 \mathsf{bslot}~bhb \\
                 \mathit{pp} \\
                 \mathit{acnt}
        \end{array}}
        \vdash
             \mathit{ls} \\
        \xrightarrow[\mathsf{\hyperref[fig:rules:ledger-sequence]{ledgers}}]{}{\mathit{txs}}
             \mathit{ls}' \\
      }
    }
    {
      {\begin{array}{c}
               \mathit{oslots} \\
               \mathit{pp} \\
               \mathit{acnt}
      \end{array}}
      \vdash
      {\left(\begin{array}{c}
            \mathit{ls} \\
            \mathit{b} \\
      \end{array}\right)}
      \xrightarrow[\mathsf{bbody}]{}{\mathit{block}}
      {\left(\begin{array}{c}
            \mathsf{varUpdate}~\mathit{ls}' \\
            \varUpdate{\mathsf{incrBlocks}~{(\mathsf{bslot}~bhb\in\mathit{oslots})}~{hk}~{b}} \\
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

The transition checks six things (via $\mathsf{chainChecks}$ and $\mathsf{prtlSeqChecks}$ from Figure 25):

- The slot in the block header body is larger than the last slot recorded.

- The block number increases by exactly one.

- The previous hash listed in the block header matches the previous block header hash which was recorded.

- The size of is less than or equal to the maximal size that the protocol parameters allow for block headers.

- The size of the block body, as claimed by the block header, is less than or equal to the maximal size that the protocol parameters allow for block bodies. It will later be verified that the size of the block body matches the size claimed in the header (see Figure 23).

- The node is not obsolete, meaning that the major component of the protocol version in the protocol parameters is not bigger than the constant $\mathsf{MaxMajorPV}$.

The chain state is shown in Figure 24, it consists of the following:

- The epoch specific state $\mathit{nes}$.

- The operational certificate issue number map $\mathit{cs}$.

- The epoch nonce $\eta_0$.

- The evolving nonce $\eta_v$.

- The candidate nonce $\eta_c$.

- The previous epoch hash nonce $\eta_h$.

- The last header hash .

- The last slot .

- The last block number .


*Chain states* $$\begin{equation*}
    \mathsf{LastAppliedBlock}=
    \left(
      \begin{array}{rlr}
        \mathit{b_\ell} & \mathsf{Slot} & \text{last block number} \\
        \mathit{s_\ell} & \mathsf{Slot} & \text{last slot} \\
        \mathit{h} & \mathsf{HashHeader}& \text{latest header hash} \\
      \end{array}
    \right)
\end{equation*}$$ $$\begin{equation*}
    \mathsf{ChainState}=
    \left(
      \begin{array}{rlr}
        \mathit{nes} & \mathsf{NewEpochState}& \text{epoch specific state} \\
        \mathit{cs} & \mathsf{KeyHash}_{pool} \mapsto \N & \text{operational certificate issue numbers} \\
        ~\eta_0 & \mathsf{Seed} & \text{epoch nonce} \\
        ~\eta_v & \mathsf{Seed} & \text{evolving nonce} \\
        ~\eta_c & \mathsf{Seed} & \text{candidate nonce} \\
        ~\eta_h & \mathsf{Seed} & \text{seed generated from hash of previous epoch} \\
        \mathit{lab} & \mathsf{LastAppliedBlock}^? & \text{latest applied block} \\
      \end{array}
    \right)
\end{equation*}$$ *Chain Transitions* $$\begin{equation*}
    \vdash \mathit{\_} \xrightarrow[\mathsf{chain}]{}{\_} \mathit{\_} \subseteq
    \powerset (\mathsf{ChainState}\times \mathsf{Block} \times \mathsf{ChainState})
\end{equation*}$$

**Chain transition-system types**
The $\mathsf{CHAIN}$ transition rule is shown in Figure 26. Its signal is a . The transition uses a few helper functions defined in Figure 25.


*Chain Transition Helper Functions* $$\begin{align*}
      & \mathsf{getGKeys} \in \mathsf{NewEpochState}\to \mathbb{P}~\mathsf{KeyHashGen} \\
      & \mathsf{getGKeys}~\mathit{nes} = \mathrm{dom}~genDelegs \\
      &
      \begin{array}{lrl}
        \where
          & (\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{es},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}})
          & \mathit{nes}
          \\
          & (\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{ls},~\underline{\phantom{a}})
          & \mathit{es}
          \\
          & (\underline{\phantom{a}},~((\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{genDelegs},~\underline{\phantom{a}}),~\underline{\phantom{a}}))
          & \mathit{ls}
      \end{array}
\end{align*}$$ $$\begin{align*}
      & \mathsf{updateNES} \in \mathsf{NewEpochState}\to \mathsf{BlocksMade} \to \mathsf{LState} \to \mathsf{NewEpochState}\\
      & \mathsf{updateNES}~
      (\mathit{e_\ell},~\mathit{b_{prev}},~\underline{\phantom{a}},~(\mathit{acnt},~\mathit{ss},~\underline{\phantom{a}},~\mathit{pp}),
       ~\mathit{ru},~\mathit{pd},~\mathit{osched})
          ~\mathit{b_{cur}}~\mathit{ls} = \\
      & ~~~~
      (\mathit{e_\ell},~\mathit{b_{prev}},~\mathit{b_{cur}},
       ~(\mathit{acnt},~\mathit{ss},~\mathit{ls},~\mathit{pp}),~\mathit{ru},~\mathit{pd},~\mathit{osched})
\end{align*}$$ $$\begin{align*}
      & \mathsf{chainChecks} \in \mathsf{PParams} \to \mathsf{BHeader}\to \mathsf{Bool} \\
      & \mathsf{chainChecks}~\mathit{pp}~\mathit{bh} = \\
      & ~~~~ m \leq \mathsf{MaxMajorPV} \\
      & ~~~~ \land~\mathsf{bHeaderSize}~ \mathit{bh} \leq \mathsf{maxHeaderSize}~\mathit{pp} \\
      & ~~~~ \land~\mathsf{hBbsize}~\mathit{(\mathsf{bhbody}~bh)} \leq \mathsf{maxBlockSize}~\mathit{pp} \\
      & ~~~~ \where (m,~\underline{\phantom{a}})\mathrel{\mathop:}=\mathsf{pv}~\mathit{pp}
\end{align*}$$ $$\begin{align*}
      & \mathsf{lastAppliedHash} \in \mathsf{LastAppliedBlock}^? \to \mathsf{HashHeader}^? \\
      & \mathsf{lastAppliedHash}~\mathit{lab} =
        \begin{cases}
          \mathsf{Nothing} & lab = \mathsf{Nothing} \\
          h & lab = (\underline{\phantom{a}},~\underline{\phantom{a}},~h) \\
        \end{cases}
\end{align*}$$ $$\begin{align*}
      & \mathsf{prtlSeqChecks} \to \mathsf{LastAppliedBlock}^? \to \mathsf{BHeader}\to \mathsf{Bool} \\
      & \mathsf{prtlSeqChecks}~\mathit{lab}~\mathit{bh} =
        \begin{cases}
          \mathsf{True}
          &
          lab = \mathsf{Nothing}
          \\
          \mathit{s_\ell} < \mathit{slot}
          \land \mathit{b_\ell} + 1 = \mathit{bn}
          \land \mathit{ph} = \mathsf{bprev}~\mathit{bhb}
          &
          lab = (b_\ell,~s_\ell,~\underline{\phantom{a}}) \\
        \end{cases} \\
      & ~~~~\where \\
      & ~~~~~~~~~~\mathit{bhb} \mathrel{\mathop:}= \mathsf{bhbody}~bh \\
      & ~~~~~~~~~~\mathit{bn} \mathrel{\mathop:}= \mathsf{bblockno}~bhb \\
      & ~~~~~~~~~~\mathit{slot} \mathrel{\mathop:}= \mathsf{bslot}~bhb \\
      & ~~~~~~~~~~\mathit{ph} \mathrel{\mathop:}= \mathsf{lastAppliedHash}~\mathit{lab} \\
\end{align*}$$

**Helper Functions used in the CHAIN transition**
$$\begin{equation}
\label{eq:chain}
    \inference[Chain]
    {
      \mathit{bh} \mathrel{\mathop:}= \mathsf{bheader}~\mathit{block}
      &
      \mathit{bhb} \mathrel{\mathop:}= \mathsf{bhbody}~bh
      \\
      \mathit{gkeys} \mathrel{\mathop:}= \mathsf{getGKeys}~\mathit{nes}
      &
      \mathit{s} \mathrel{\mathop:}= \mathsf{bslot}~bhb
      \\
      (\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~(\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{pp}),~\underline{\phantom{a}},~\underline{\phantom{a}},\underline{\phantom{a}}) \mathrel{\mathop:}= \mathit{nes}
      \\~\\
      \mathsf{prtlSeqChecks}~\mathit{lab}~\mathit{bh}\\
      \mathsf{chainChecks}~\mathit{pp}~\mathit{bh}
      \\~\\
      {
        {\begin{array}{c}
           \mathit{gkeys} \\
         \end{array}}
        \vdash\mathit{nes}\xrightarrow[\mathsf{\hyperref[fig:rules:tick]{tick}}]{}{\mathit{s}}\mathit{nes'}
      } \\~\\
      (\mathit{e_1},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},\underline{\phantom{a}})
        \mathrel{\mathop:}=\mathit{nes} \\
      (\mathit{e_2},~\underline{\phantom{a}},~\mathit{b_{cur}},~\mathit{es},~\underline{\phantom{a}},~\mathit{pd},\mathit{osched})
        \mathrel{\mathop:}=\mathit{nes'} \\
        (\mathit{acnt},~\underline{\phantom{a}},\mathit{ls},~\underline{\phantom{a}},~\mathit{pp'})\mathrel{\mathop:}=\mathit{es}\\
        ( \underline{\phantom{a}},
          ( (\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}},~\mathit{genDelegs},~\underline{\phantom{a}}),~
          (\underline{\phantom{a}},~\underline{\phantom{a}},~\underline{\phantom{a}})))\mathrel{\mathop:}=\mathit{ls}\\
          \mathit{ne} \mathrel{\mathop:}=  \mathit{e_1} \neq \mathit{e_2}\\
          \eta_{ph} \mathrel{\mathop:}= \mathsf{prevHashToNonce}~ \mathit{(\mathsf{lastAppliedHash}~\mathit{lab})} \\
      {
        {\begin{array}{c}
        \mathit{pp'} \\
        \eta_c \\
        \eta_\mathit{ph} \\
        \end{array}}
        \vdash
        {\left(\begin{array}{c}
        \eta_0 \\
        \eta_h \\
        \end{array}\right)}
        \xrightarrow[\mathsf{\hyperref[fig:rules:tick-nonce]{tickn}}]{}{\mathit{ne}}
        {\left(\begin{array}{c}
        \eta_0' \\
        \eta_h' \\
        \end{array}\right)}
      }\\~\\~\\
      {
        {\begin{array}{c}
            \mathit{osched} \\
            \mathit{pd} \\
            \mathit{genDelegs} \\
            \eta_0' \\
         \end{array}}
        \vdash
        {\left(\begin{array}{c}
              \mathit{cs} \\
              \eta_v \\
              \eta_c \\
        \end{array}\right)}
        \xrightarrow[\mathsf{\hyperref[fig:rules:prtcl]{prtcl}}]{}{\mathit{bh}}
        {\left(\begin{array}{c}
              \mathit{cs'} \\
              \eta_v' \\
              \eta_c' \\
        \end{array}\right)}
      } \\~\\~\\
      {
        {\begin{array}{c}
                 \mathrm{dom}~osched \\
                 \mathit{pp'} \\
                 \mathit{acnt}
        \end{array}}
        \vdash
        {\left(\begin{array}{c}
              \mathit{ls} \\
              \mathit{b_{cur}} \\
        \end{array}\right)}
        \xrightarrow[\mathsf{\hyperref[fig:rules:bbody]{bbody}}]{}{\mathit{block}}
        {\left(\begin{array}{c}
              \mathit{ls}' \\
              \mathit{b_{cur}'} \\
        \end{array}\right)}
      }\\~\\
      \mathit{nes''}\mathrel{\mathop:}=\mathsf{updateNES}~\mathit{nes'}~\mathit{b_{cur}'},~\mathit{ls'} \\
      \mathit{lab'}\mathrel{\mathop:}= (\mathsf{bblockno}~bhb,~\mathit{s},~\mathsf{bhash}~\mathit{bh} ) \\
    }
    {
      \vdash
      {\left(\begin{array}{c}
            \mathit{nes} \\
            \mathit{cs} \\
            \eta_0 \\
            \eta_v \\
            \eta_c \\
            \eta_h \\
            \mathit{lab} \\
      \end{array}\right)}
      \xrightarrow[\mathsf{chain}]{}{\mathit{block}}
      {\left(\begin{array}{c}
            \mathsf{varUpdate}~\mathit{nes}'' \\
            \mathsf{varUpdate}~\mathit{cs}' \\
            \mathsf{varUpdate}~\eta_0' \\
            \mathsf{varUpdate}~\eta_v' \\
            \mathsf{varUpdate}~\eta_c' \\
            \mathsf{varUpdate}~\eta_h' \\
            \mathsf{varUpdate}~\mathit{lab}' \\
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

- If the major component of the protocol version is larger than $\mathsf{MaxMajorPV}$, there is a *ObsoleteNode* failure.

## Byron to Shelley Transition
This section defines the valid initial Shelley ledger states and describes how to transition the state held by the Byron ledger to Shelley. The Byron ledger state $\mathsf{CEState}$ is defined in [@byron_chain_spec]. The valid initial Shelley ledger states are exactly the range of the function $\mathsf{initialShelleyState}$ defined in Figure 27. Figure 28 defines the transition function from Byron. Note that we use the hash of the final Byron header as the first evolving and candidate nonces for Shelley.


*Shelley Initial States* $$\begin{align*}
      & \mathsf{initialShelleyState} \in \mathsf{LastAppliedBlock}^? \to \mathsf{Epoch} \to \mathsf{UTxO}
        \to \mathsf{Coin} \to \mathsf{GenesisDelegation} \\
      & ~~~ \to (\mathsf{Slot}\mapsto\mathsf{KeyHashGen}^?)
        \to \mathsf{PParams} \to \mathsf{Seed} \to \mathsf{ChainState}\\
      & \mathsf{initialShelleyState}~
      \left(
        \begin{array}{c}
          \mathit{lab} \\
          \mathit{e} \\
          \mathit{utxo} \\
          \mathit{reserves} \\
          \mathit{genDelegs} \\
          \mathit{os} \\
          \mathit{pp} \\
          \mathit{initNonce} \\
        \end{array}
      \right)
      =
      \left(
        \begin{array}{c}
          \left(
            \begin{array}{c}
              \mathit{e} \\
              \emptyset \\
              \emptyset \\
              \left(
                \begin{array}{c}
                  \left(
                    \begin{array}{c}
                      0 \\
                      \mathit{reserves} \\
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
                          \mathit{utxo} \\
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
                            \mathit{genDelegs} \\
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
                  \mathit{pp} \\
                  \mathit{pp} \\
                \end{array}
              \right) \\
              \\
              \mathsf{Nothing} \\
              \emptyset \\
              \mathit{os} \\
            \end{array}
          \right) \\
          \mathit{cs} \\
          \mathit{initNonce} \\
          \mathit{initNonce} \\
          \mathit{initNonce} \\
          0_{seed} \\
          \mathit{lab} \\
        \end{array}
      \right) \\
      & ~~~~\where cs = \{\mathit{hk}\mapsto 0~\mid~(\mathit{hk},~\underline{\phantom{a}})\in\mathrm{range}~genDelegs\} \\
\end{align*}$$

**Initial Shelley States**
*Byron to Shelley Transition* $$\begin{align*}
      & \mathsf{toShelley} \in \mathsf{CEState} \to \mathsf{GenesisDelegation} \to \mathsf{BlockNo} \to \mathsf{ChainState}\\
      & \mathsf{toShelley}~
      \left(
        \begin{array}{c}
          \mathit{s_{last}} \\
          \underline{\phantom{a}} \\
          \mathit{h} \\
          (\mathit{utxo},~\mathit{reserves}) \\
          \underline{\phantom{a}} \\
          \mathit{us}
        \end{array}
      \right)~\mathit{gd}~\mathit{bn}
      =
      \mathsf{initialShelleyState}~
      \left(
        \begin{array}{c}
          (\mathit{s_{last}}~\mathit{bn},~\mathsf{prevHashToNonce}~ \mathit{h}) \\
          e \\
          \mathsf{hash}~{h} \\
          \mathit{utxo} \\
          \mathit{reserves} \\
          \mathit{gd} \\
          \mathsf{overlaySchedule}~\mathit{e}~\mathit{(\mathrm{dom}~gd)}~\mathit{pp} \\
          \mathit{pp} \\
          \mathsf{prevHashToNonce}~ \mathit{h} \\
        \end{array}
      \right) \\
      & ~~~~\where \\
      & ~~~~~~~~~e = \mathsf{epoch}~s_{last} \\
      & ~~~~~~~~~pp = \mathsf{pps}~{us} \\   % this pps function is defined in the Byron chain spec
\end{align*}$$

**Byron to Shelley State Transtition**