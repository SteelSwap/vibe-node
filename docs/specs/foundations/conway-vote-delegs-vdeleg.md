% If the module name changes, change the following macro to match!
\mathsf{CertsVDelegs}{Certs/Properties/VoteDelegsVDeleg}

claim[%
  \mathsf{CertsVDelegs}.lagda{\mathsf{CertsVDelegs}{}}:
   by  constructor% 
  ]thm:VDelegsInRegDReps
  itemize
    \item Informally. A  has a , , and a
      .  The  contains a field  which is a
      mapping from  to .

       is a datatype with three constructors; the one of
      interest to us here is , which takes two arguments,
      a  and a .

      Now suppose we have a collection C of credentials---for instance, 
      given d~:~, take C to be the domain of the
       field of d.  We could then obtain a set of s
      by applying ~ to each element of C. 

      The present property asserts that the set of s that results from the
      application of ~ to the domain of the  of
      d contains the range of the  of d.
    \item Formally.
```agda
voteDelegsVDeleg :  DState → Type
voteDelegsVDeleg d = range (voteDelegsOf d) ⊆ mapˢ (credVoter DRep) (dom (voteDelegsOf d))
```
    \item Proof. To appear in the
      \mathsf{CertsVDelegs}.lagda{\mathsf{CertsVDelegs}{}}
      module in the \repourl{formal ledger repository}.
  itemize
claim
