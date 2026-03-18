# Leader Value Calculation
This section details how we determine whether a node is entitled to lead (under the Praos protocol) given the output of its verifiable random function calculation.


*Values associated with the leader value calculations* $$\begin{equation*}
  \begin{array}{rlr}
    \var{certNat} & \{n | n \in \N, n \in [0,2^{256})\} & \text{Certified natural value from VRF} \\
    \var{f} & [0,1] & \text{Active slot coefficient} \\
    \sigma & [0,1] & \text{Stake proportion}
  \end{array}
\end{equation*}$$

## Computing the leader value

The verifiable random function gives us a 32-byte random output. We interpret this as a natural number $\var{certNat}$ in the range $[0,2^{256})$.

## Node eligibility

As per [@ouroboros_praos], a node is eligible to lead when its leader value $\ell < 1 - (1 - f)^\sigma$. We have

$$\begin{align*}
  \ell & < 1 - (1 -f)^\sigma \\
  \iff \left(\frac{1}{1-\ell}\right) & < \exp{(-\sigma \cdot \ln{(1-f)})}
\end{align*}$$

The latter inquality can be efficiently computed through use of its Taylor expansion and error estimation to stop computing terms once we are certain that the result will be either above or below the target value.

We carry out all computations using fixed precision arithmetic (specifically, we use 34 decimal bits of precision, since this is enough to represent the fraction of a single lovelace.)

As such, we define the following:

$$\begin{align*}
  q & = \frac{2^{256}}{2^{256} - \var{certNat}} \\
  c & = \ln{(1 - f)}
\end{align*}$$

and define the function *checkLeaderVal* as follows:

$$\begin{equation*}
  \fun{checkLeaderVal}~\var{certNat}~\sigma~\var{f} =
    \left\{
      \begin{array}{lr}
        \mathsf{True}, & f = 1 \\
        q > \exp{(-\sigma \cdot c)}, & \text{otherwise}
      \end{array}
    \right.
\end{equation*}$$
