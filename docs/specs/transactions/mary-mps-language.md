# Appendix A: Example MPS Language

The language for MP scripts given here is only a suggestion and its implementation may differ from the one given here. The constructors which make up the MPS script scheme are used to express the following aspects of monetary policy:

- $\mathsf{JustMSig}$  :  evaluates an MSig script

- $\mathsf{RequireAll}$ : evaluates all MPS scripts in the given set

- Others will be here once decided on

The Figures 1, 3,  fig:defs:tx-mc-eval-2, and 2 give possible constructors of the MPS language.


$$\begin{align*}
    & \mathsf{evalMPSScript} \in\mathsf{ScriptMPS}\to\mathsf{PolicyID}\to\mathsf{Slot}\to\powerset\mathsf{KeyHash} \\
    &~~~~\to\mathsf{TxBody}\to\mathsf{UTxO} \to\mathsf{Bool}  \\
    & \text{UTxO is only for the outputs THIS tx is spending, not global UTxO, i.e.} \\
    & \text{when called,}~\mathit{spentouts}~=~(\mathsf{txins}~\mathit{txb}) ~\lhd~\mathit{utxo} \\~\\
    %
    & \mathsf{evalMPSScript}  ~(\mathsf{JustMSig}~s)~\mathit{pid}~\mathit{slot}~\mathit{vhks}
     ~\mathit{txb}~\mathit{spentouts} \\
    &~~~~ =~ \mathsf{evalMultiSigScript}~s~\mathit{vhks} \\
    & \text {checks the msig script}\\~\\
    %
    & \mathsf{evalMPSScript}
     ~\mathsf{DoForge}~\mathit{pid}~ \mathit{slot}~\mathit{vhks} ~\mathit{txb}~\mathit{spentouts} \\
    &~~~~ =~ \mathit{pid} \notin \dom~(\mathsf{forge}~\mathit{txb}) \\
    & \text {checks that script hash of this script is not an asset ID being forged by tx}  \\~\\
    %
    & \mathsf{evalMPSScript}
     ~\mathsf{SignedByPIDToken}~\mathit{pid}~ \mathit{slot}~\mathit{vhks} ~\mathit{txb}~\mathit{spentouts} \\
    &~~~~ =~ \exists~t\mapsto ~\_~\in~ \mathsf{range}~(\mathit{pid}~ \lhd~(\mathsf{ubalance}~\mathit{spentouts})) ~:~ t~\in~\mathit{vhks} \\
    & \text{checks that tx is signed by a key whose hash is the name of a token in this asset}
    \\~\\
    & \mathsf{evalMPSScript}
     ~(\mathsf{SpendsCur}~\mathit{pid'})~\mathit{pid}~ \mathit{slot}~\mathit{vhks} ~\mathit{txb}~\mathit{spentouts} \\
    &~~~~ =~ (\mathit{pid'}~\neq~\mathsf{Nothing} ~\wedge ~\mathit{pid'}~\in~ \dom~(\mathsf{ubalance}~\mathit{spentouts}))\\
    &~~~~~~ \vee (\mathit{pid'}~=~\mathsf{Nothing} ~\wedge ~\mathit{pid}~\in~ \dom~(\mathsf{ubalance}~\mathit{spentouts})) \\
    & \text{checks that this transaction spends asset pid' OR itself if}~\mathit{pid'}~=~\mathsf{Nothing}
    \\~\\
    &\mathsf{evalMPSScript}~(\mathsf{Not}~s)~\mathit{pid}~\mathit{slot}~\mathit{vhks}
    ~\mathit{txb}~\mathit{spentouts}
   \\
    &~~~~ = \neg ~\mathsf{evalMPSScript}~s~\mathit{pid}~\mathit{slot}~\mathit{vhks}
    ~\mathit{txb}~\mathit{spentouts}\\~\\
    %
    &\mathsf{evalMPSScript}~(\mathsf{RequireAll}~ls)~\mathit{pid}~\mathit{slot}~\mathit{vhks}
    ~\mathit{txb}~\mathit{spentouts}
   \\
    &~~~~ = \forall ~s'~ \in~ ls~:~\mathsf{evalMPSScript}~s'~\mathit{pid}~\mathit{slot}~\mathit{vhks}
    ~\mathit{txb}~\mathit{spentouts}\\~\\
    %
    &\mathsf{evalMPSScript}~(\mathsf{RequireOr}~ls)~\mathit{pid}~\mathit{slot}~\mathit{vhks}
    ~\mathit{txb}~\mathit{spentouts}
   \\
    &~~~~ = \exists ~s'~ \in~ ls~:~\mathsf{evalMPSScript}~s'~\mathit{pid}~\mathit{slot}~\mathit{vhks}
    ~\mathit{txb}~\mathit{spentouts}\\
\end{align*}$$

**Multi-asset Script Evaluation**
$$\begin{align*}
    & \mathsf{evalMPSScript}
     ~(\mathsf{AssetToAddress}~\mathit{pid'}~\mathit{addr})~\mathit{pid}~ \mathit{slot}~\mathit{vhks} ~\mathit{txb}~\mathit{spentouts} \\
    &~~~~ =~ \forall~(a, v)~\in~\mathsf{range}~(\mathsf{outs}~txb),~\\
    &~~~~~~ \mathit{c}~\in~\dom~v~\Rightarrow~(a~=~ \mathit{a'} ~\wedge~
                       v~=~\mathit{c}~ \lhd~(\mathsf{ubalance}~(\mathsf{outs}~txb)) \\
    & \where \\
    & ~~~~~~~ \mathit{a'}~=~\mathsf{if}~ \mathit{addr}~\neq~\mathsf{Nothing}~\mathsf{then}~\mathit{addr}~\mathsf{else}~\mathit{(pid',pid')} \\
    & ~~~~~~~ \mathit{c}~=~\mathsf{if}~ \mathit{pid'}~\neq~\mathsf{Nothing}~\mathsf{then}~\mathit{pid'}~\mathsf{else}~\mathit{pid} \\
    & \text{checks that tx outputs any pid tokens by themselves to the specified address} \\
    & \text {the script address of the given asset when addr unspecified} \\~\\
    & \mathsf{evalMPSScript}
     ~(\mathsf{TrancheTokens}~\mathit{tts}~\mathit{txin})~\mathit{pid}~\mathit{slot}~\mathit{vhks}
     ~\mathit{txb}~\mathit{spentouts}  \\
    &~~~~ =~(\mathit{pid}\mapsto\mathit{tts}~\in~\mathit{val})~ \wedge~(\mathit{txin}~\in~\mathsf{txins}~{txb}) \\
    & \text{tranche tokens is incomplete} \\~\\
    %
    & \mathsf{evalMPSScript}
     ~(\mathsf{FreshTokens})~\mathit{pid}~\mathit{slot}~\mathit{vhks}
     ~\mathit{txb}~\mathit{spentouts}
      \\
    &~~~~ =~\forall~\mathit{pid}~ \mapsto ~tkns ~\in~ \mathit{val}~:~ \\
    &~~~~ \forall~t~\in~\mathit{tkns},~
        \mathsf{nameToken}~(\mathsf{indexof}~\mathit{t}~\mathit{tkns},~\mathsf{txins}~{txb})~=~t
\end{align*}$$

**Multi-asset Script Evaluation, cont.**
$$\begin{align*}
    & \mathsf{whitelist} \in\mathsf{ScriptMSig}\to\mathsf{Script}  \\~\\
    %
    & \mathsf{whitelist}  ~\mathit{msig}~ =~ \mathsf{RequireOr}~
      (\mathsf{RequireAll}~(\mathsf{DoForge};~\mathsf{JustMSig}~\mathit{msig});~\\
    &~~~~~~ \mathsf{RequireAll}~(\mathsf{AssetToAddress}~\mathsf{Nothing}~\mathsf{Nothing} ;\\
    &~~~~~~ (\mathsf{Not}~\mathsf{DoForge});~\mathsf{SignedByPIDToken})) \\
    %
    & \text{msig is some MSig script containing signatures of some accreditation authority} \\
    & \text{i.e. this authority can do any forging or spending of this token} \\~\\
    %
    & (\mathsf{hashScript}~(\mathsf{SpendsCur}~(\mathsf{hashScript}~(\mathsf{whitelist}~\mathit{msig}))),~ \mathit{tkns}) \\
    & \text{an example of an output spending which requires to be on a whitelist made by msig authority}
\end{align*}$$

**Whitelist Script Example**