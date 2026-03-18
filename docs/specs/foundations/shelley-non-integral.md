# Non-Integral Calculations
In the ledger there are several cases where non-integral calculations are required, particularly calculations relating to delegation transitions.

## Types of Non-Integral Calculations
The specification employs non-integral calculations for different mathematical operations. Table [1](#tab:func-non-integral) shows the function and transition rules that use non-integral calculations and which type.


  name    page   multiplication   division   exponential function   exponentiation
  ------ ------ ---------------- ---------- ---------------------- ----------------
                                                                   
                                                                   
                                                                   
                                                                   
                                                                   
                                                                   
                                                                   

  : Functions with Non-Integral Calculation

The transcendental exponential function is used in reward and refund calculation to model the decay of the deposit values. The pool reward uses exponentiation to calculate a pool's ranking.

The domain for the exponential function are the non-negative reals, more precisely the distribution parameter $\lambda \in (0, \infty)$ multiplied by a discrete non-negative duration $\delta$.

The domain of the base of the exponentiation in $\fun{poolReward}$ are the non-negative reals resulting from the calculation in $\fun{movingAvg}$, the exponent $\gamma$ is a constant taken from the protocol parameters.

## Implementation of Non-Integer Calculations
The large part consists of multiplication and division which can easily be done using fractional arithmetic to the desired precision. The precision necessary is bounded by the ability to represent a single lovelace in all calculations.

### Function Simplification
The transcendental function $e^{x}$ can be approximated using different approaches, depending on the desired accuracy. In general, one uses the exponential laws $e^{x} = 1/e^{-x}$ and $e^{x} = \left(e^{\frac{x}{n}} \right)^{n}, n \in \mathbb{N}$ to reduce the approximation to the unit interval and apply fast integral exponentiation afterwards.

Exponentiation is implemented using the law $a^{b} = e^{\ln(a^{b})}= e^{b\ln(a)}$. This therefore requires being able to calculate $e^{x}$ and $\ln(x)$. The the natural logarithm can be approximated using different approaches, again, depending on the desired accuracy. Most approximations work for $\ln(x), x \in [1, c)$ with some $c >
1$. One then uses the law $\log_{b}(x) = \log_{b}(\frac{x}{b^{n}}b^{n})$ where $n \in \mathbb{N}$ is chosen in such a way that $\frac{x}{b^{n}} \in [1,
c)$. Using this, one can separate the calculation of the integral and decimal part as follows:

$$\begin{equation*}
  \log_{b}(\frac{x}{b^{n}}b^{n})=\log_{b}(b^{n}) + \log_{b}(\frac{x}{b^{n}})=
  n + \log(\frac{x}{b^{n}})
\end{equation*}$$

### Properties of Function Approximation
There are several properties that approximations of the transcendental functions are expected to have. In the following let $\ln'(x)$ be the approximation of $\ln(x)$, $\exp'(x)$ be the approximation of $e^{x}$ and $x\star y$ the approximation of $x^{y}$.

::: property
[]{#prop:monotone label="prop:monotone"} Both $\exp'$ and $\ln'$ must be monotone on their respective domains.

In order to guarantee correctness of the approximations, we also require that the mathematical laws are fulfilled. For some small $\epsilon > 0$, define $x \approx y \Leftrightarrow \lvert x - y\rvert < \epsilon$.

::: property
[]{#prop:ln-laws label="prop:ln-laws"} The following mathematical laws state the requirements for the approximations of the $\ln'$ and $\exp'$ function:

- $\ln'(x\cdot y) \approx \ln'(x) + \ln'(y)$

- $\ln'(x\star y) \approx y\cdot \ln'(x)$

- $\ln'(\exp'(x)) \approx \exp'(\ln'(x)) \approx x$

- $x, y \in [0,1] \implies x \star y \in [0, 1]$

- $x, y, z \in [0,1], x > 0 \implies
      (z\star\frac{1}{x})\star y \approx (z\star y)\star\frac{1}{x}$

- $\exp'(x + y) \approx \exp'(x) \cdot \exp'(y)$
