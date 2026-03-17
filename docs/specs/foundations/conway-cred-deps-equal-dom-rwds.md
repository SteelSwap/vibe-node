% If the module name changes, change the following macro to match!
\ChainPropCredDeps{Chain/Properties/CredDepsEqualDomRwds}

claim[%
  \ChainPropCredDeps.lagda{\ChainPropCredDeps{}}:
  Equality of credential depsoits is a  invariant%
  ]
  itemize
    \item Informally.  This property concerns two quantities associated with
    a given  cs,
    itemize
      \item the credential deposits of the  of cs and
      \item the credential deposits of the rewards in the ledger state of cs.
    itemize
    The predicate credDeposits≡dom-rwds~cs asserts that these
    quantities are equal for cs.  Formally,
```agda
credDeposits≡dom-rwds : ChainState → Type
credDeposits≡dom-rwds cs =  filter isCredDeposit (dom (DepositsOf cs))
                            ≡ map CredentialDeposit (dom (RewardsOf cs))
```
    The property
    credDeposits≡dom-rwds-inv asserts that
    credDeposits≡dom-rwds is a chain invariant.  That is, if cs
    and cs' are two s such that
    cs~⇀⦇~tx~,CHAIN⦈~cs',
    then credDeposits≡dom-rwds~cs only if
    credDeposits≡dom-rwds~cs'.
    \item Formally.
```agda
credDeposits≡dom-rwds-inv : Type
credDeposits≡dom-rwds-inv = LedgerInvariant _⊢_⇀⦇_,CHAIN⦈_ credDeposits≡dom-rwds
```
    \item Proof. To appear (in the
      \ChainPropCredDeps.lagda{\ChainPropCredDeps{}} module
      of the \repourl{formal ledger repository}).
  itemize
claim


