# Addresses
Addresses are described in section 4.2 of the delegation design document [@delegation_design]. The types needed for the addresses are defined in Figure 1. They all involve a credential, which is either a key or a multi-signature script. There are four types of UTxO addresses:

- Base addresses, $\mathsf{AddrB}$, containing the hash of a payment credential and the hash of a staking credential. Note that the payment credential hash is the hash of the key (or script) which has contol of the funds at this address, i.e. is able to witness spending them. The staking credential controls the delegation decision for the Ada at this address (i.e. it is used for rewards, staking, etc.). The staking credential must be a (registered) delegation credential (see Section sec:delegation-shelley for a discussion of the delegation mechanism).

- Pointer addresses, $\mathsf{AddrP}$, containing the hash of a payment credential and a pointer to a stake credential registration certificate.

- Enterprise addresses, $\mathsf{AddrE}$, containing only the hash of a payment credential (and which have no staking rights).

- Bootstrap addresses, $\mathsf{AddrBS}$, corresponding to the addresses in Byron, behaving exactly like enterprise addresses with a key hash payment credential.

Where a credential is either a key or a multi-signature script. Together, these four address types make up the $\mathsf{Addr}$ type, which will be used in transaction outputs in Section sec:utxo. The notations $\mathsf{Credential}_{pay}$ and $\mathsf{Credential}_{stake}$ do not represent distinct types. The subscripts are annotations indicating how the credential is being used.

Section 5.5.2 of [@delegation_design] provides the motivation behind enterprise addresses and explains why one might forgo staking rights. Bootstrap addresses are needed for the Byron-Shelley transition in order to accommodate having UTxO entries from the Byron era during the Shelley era.

There are also subtypes of the address types which correspond to the credential being either a key hash (the $vkey$ subtype) or a script hash (the $script$ subtype). So for example $\mathsf{Addr}_{base}^{script}$ is the type of base addresses which have a script hash as pay credential. This approach is used to facilitate expressing the restriction of the domain of certain functions to a specific credential type.

Note that for security, privacy and usability reasons, the staking (delegating) credential associated with an address should be different from its payment credential. Before the stake credential is registered and delegated to an existing stake pool, the payment credential can be used for transactions, though it will not receive rewards from staking. Once a stake credential is registered, the shorter pointer addresses can be generated.

Finally, there is an account style address $\mathsf{AddrRWD}$ which contains the hash of a staking credential. These account addresses will only be used for receiving rewards from the proof of stake leader election. Appendix A of [@delegation_design] explains this design choice. The mechanism for transferring rewards from these accounts will be explained in Section sec:utxo and follows the approach outlined in the document [@chimeric].

Note that, even though in the Cardano system, most of the accounting is UTxO-style, the reward addresses are a special case. Their use is restricted to only special cases (e.g. collecting rewards from them), outlined in the rules in Sections sec:utxo and Section sec:epoch. For each staking credential, we use the function $\mathsf{addr_{rwd}}$ to create the reward address corresponding to the credential, or to access an existing one if it already exists. Note that $\mathsf{addr_{rwd}}$ uses the global constant $\mathsf{NetworkId}$ to attach a network ID to the given stake credential.

Base, pointer and enterprise addresses contain a payment credential which is either a key hash or a script hash. Base addresses contain a staking credential which is also either a key hash or a script hash.


*Abstract types* $$\begin{equation*}
    \begin{array}{rlr}
      \mathit{slot} & \mathsf{Slot} & \text{absolute slot}\\
      \mathit{ix} & \mathsf{Ix} & \text{index}\\
      \mathit{net} & \mathsf{Network} & \text{either $\mathsf{Testnet}$ or $\mathsf{Mainnet}$}\\
    \end{array}
\end{equation*}$$ *Derived types* $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{cred} & \mathsf{Credential} & \mathsf{KeyHash}\uplus\mathsf{HashScr} \\
      \mathit{(s,t,c)}
      & \mathsf{Ptr}
      & \mathsf{Slot}\times\mathsf{Ix}\times\mathsf{Ix}
      & \text{certificate pointer}
      \\
      \mathit{addr}
      & \mathsf{AddrB}
      & \mathsf{Network}\times\mathsf{Credential}_{pay}\times\mathsf{Credential}_{stake}
      & \text{base address}
      \\
      \mathit{addr}
      & \mathsf{AddrP}
      & \mathsf{Network}\times\mathsf{Credential}_{pay}\times\mathsf{Ptr}
      & \text{pointer address}
      \\
      \mathit{addr}
      & \mathsf{AddrE}
      & \mathsf{Network}\times\mathsf{Credential}_{pay}
      & \text{enterprise address}
      \\
      \mathit{addr}
      & \mathsf{AddrBS}
      & \mathsf{Network}\times\mathsf{KeyHash}_{pay}
      & \text{bootstrap address}
      \\
      \mathit{addr}
      & \mathsf{Addr}
      & \begin{array}{ll}
          \mathsf{AddrB} & \mathsf{AddrP} \uplus \mathsf{AddrE}
          \\
                 & \mathsf{AddrBS}
        \end{array}
      & \text{output address}
      \\
      \mathit{acct}
      & \mathsf{AddrRWD}
      & \mathsf{Network}\times\mathsf{Credential}_{stake}
      & \text{reward account}
      \\
    \end{array}
\end{equation*}$$ *Address subtypes* $$\begin{equation*}
    \begin{array}{rllr}
      \mathit{addr^{vkey}_{base}}
                 & \mathsf{Addr}^{vkey}_{base}
                               & \mathsf{KeyHash}\lhd\mathsf{Addr}_{base}
      \\
      \mathit{addr^{script}_{base}}
                 & \mathsf{Addr}^{vkey}_{base}
                               & \mathsf{HashScr}\lhd\mathsf{Addr}_{base}
      \\
      \mathit{addr^{vkey}_{ptr}}
                 & \mathsf{Addr}^{vkey}_{ptr}
                               & \mathsf{KeyHash}\lhd\mathsf{Addr}_{ptr}
      \\
      \mathit{addr^{script}_{ptr}}
                 & \mathsf{Addr}^{vkey}_{ptr}
                               & \mathsf{HashScr}\lhd\mathsf{Addr}_{ptr}
      \\
      \mathit{addr^{vkey}_{enterprise}}
                 & \mathsf{Addr}^{vkey}_{enterprise}
                               & \mathsf{Addr}_{enterprise}\cap\mathsf{KeyHash}
      \\
      \mathit{addr^{script}_{enterprise}}
                 & \mathsf{Addr}^{vkey}_{enterprise}
                               & \mathsf{Addr}_{enterprise}\mathsf{HashScr}
      \\[0.5cm]
      \mathit{addr^{vkey}} &
             \mathsf{Addr}^{vkey} &
                            \mathsf{Addr}^{vkey}_{base} \uplus \mathsf{Addr}^{vkey}_{ptr} \uplus \mathsf{Addr}^{vkey}_{enterprise} \uplus \mathsf{Addr}_{bootstrap}\\[0.3cm]
      \mathit{addr^{script}} &
                            \mathsf{Addr}^{script} &
                                             \mathsf{Addr}^{script}_{base}
                                             \uplus \mathsf{Addr}^{script}_{ptr}
                                             \uplus
                                             \mathsf{Addr}^{script}_{enterprise}
      \\[0.5cm]
      \mathit{addr_{rwd}^{vkey}} & \mathsf{Addr}_{rwd}^{vkey} & \mathsf{Addr}_{rwd}\cap\mathsf{KeyHash} \\
      \mathit{addr_{rwd}^{script}} & \mathsf{Addr}_{rwd}^{script} & \mathsf{Addr}_{rwd}\cap\mathsf{HashScr} \\
    \end{array}
\end{equation*}$$ *Accessor Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{paymentHK} & \mathsf{AddrVKey} \to \mathsf{KeyHash}_{pay}
      & \text{hash of payment key from addr}\\
      \mathsf{validatorHash} & \mathsf{AddrScr} \to \mathsf{HashScr} & \text{hash of validator
                                                    script} \\
            \mathsf{stakeCred_{b}} & \mathsf{AddrB} \to
                          \mathsf{StakeCredential} & \text{stake credential from base
                                      addr}\\
      \mathsf{stakeCred_{r}} & \mathsf{AddrRWD} \to \mathsf{StakeCredential} & \text{stake credential
                                                   from reward addr}\\
      \mathsf{addrPtr} & \mathsf{AddrP} \to \mathsf{Ptr}
                    & \text{pointer from pointer addr}\\
      \mathsf{netId} & \mathsf{Addr} \to \mathsf{Network}
                    & \text{network Id from addr}\\
    \end{array}
\end{equation*}$$ *Constructor Functions* $$\begin{equation*}
    \begin{array}{rlr}
      \mathsf{addr_{rwd}}
        & \mathsf{Credential}_{stake} \to \mathsf{AddrRWD}
        & \begin{array}{l}
            \text{construct a reward account,} \\
            \text{implicitly using $\mathsf{NetworkId}$}
          \end{array}
    \end{array}
\end{equation*}$$ *Constraints* $$\begin{equation*}
    \mathit{hk_1} = \mathit{hk_2} \iff \mathsf{addr_{rwd}}~\mathit{hk_2} = \mathsf{addr_{rwd}}~\mathit{hk_2}
    ~~~ \left( \mathsf{addr_{rwd}} \text{ is injective} \right)
\end{equation*}$$

**Definitions used in Addresses**