# Serialising Plutus Core Terms and Programs Using the `flat` Format
We use the `flat` format [@flat] to serialise Plutus Core terms, and we regard this format as being the definitive concrete representation of Plutus Core programs. For compactness we generally (and *always* for scripts on the blockchain) replace names with de Bruijn indices (see Section sec:grammar-notes) in serialised programs.

We use bytestrings for serialisation, but it is convenient to define the serialisation and deserialisation process in terms of strings of bits. Some extra bits of padding are added at the end of the encoding of a program to ensure that the number of bits in the output is a multiple of 8, and this allows us to regard serialised programs as bytestrings in the obvious way.

See Section 1.4 for some restrictions on serialisation specific to the Cardano blockchain.

##### Note: `flat` versus CBOR.

Much of the Cardano codebase uses the CBOR format for serialisation; however, it is important that serialised scripts not be too large. CBOR pays a price for being a self-describing format. The size of the serialised terms is consistently larger than a format that is not self-describing: benchmarks show that `flat` encodings of Plutus Core scripts are smaller than CBOR encodings by about 35% (without using compression).

## Encoding and decoding
Firstly recall some notation from Section sec:notation. The set of all finite sequences of bits is denoted by $\mathsf{Bits} = \{\mathsf{bits}~0,\mathsf{bits}~1\}^*$. For brevity we write a sequence of bits in the form $b_{n-1} \cdots b_0$ instead of $[b_{n-1}, \ldots, b_0]$: thus $\mathsf{bits}~011001$ instead of $[\mathsf{bits}~0,
  \mathsf{bits}~1,\mathsf{bits}~1,\mathsf{bits}~0,\mathsf{bits}~0,\mathsf{bits}~1])$. We denote the empty sequence by $\epsilon$, and use $\length(s)$ to denote the length of a sequence of bits, and $\cdot$ to denote concatenation (or prepending or appending a single bit to a sequence of bits).

Similarly to the CBOR encoding for `data` described in Appendix appendix:data-cbor-encoding, we will describe the flat encoding by defining families of encoding functions (or *encoders*) $$\E_X : \mathsf{Bits} \times X \rightarrow \mathsf{Bits}$$ and (partial) decoding functions (or *decoders*) $$\D_X : \mathsf{Bits} \rightharpoonup \mathsf{Bits} \times X$$

for various sets $X$, such as the set $\Z$ of integers and the set of all Plutus Core terms. The encoding function $\E_X$ takes a sequence $s \in
\mathsf{Bits}$ and an element $x \in X$ and produces a new sequence of bits by appending the encoding of $x$ to $s$, and the decoding function $\D_X$ takes a sequence of bits, decodes some initial prefix of $s$ to a value $x \in X$, and returns the remainder of $s$ together with $x$.

Encoding functions basically operate by decomposing an object into subobjects and concatenating the encodings of the subobject; however it is sometimes necessary to add some padding between subobjects in order to make sure that parts of the output are aligned on byte boundaries, and for this reason (unlike the CBOR encoding for `data`) all of our encoding functions have a first argument containing all of the previous output, so that it can be examined to determine how much alignment is required.

As in the case of CBOR, decoding functions are partial: they can fail if, for instance, there is insufficient input, or if a decoded value is outside some specified range. To simplify notation we will mention any preconditions separately, with the assumption that the decoder will fail if the preconditions are not met; we also make a blanket assumption that all decoders fail if there is not enough input for them to proceed. Many of the definitions of decoders construct objects by calling other decoders to obtain subobjects which are then composed, and these are often introduced by a condition of the form "if $\D_X(s) = x$". Conditions like this should be read as implicitly saying that if the decoder $\D_X$ fails then the whole decoding process fails.

### Padding

The encoding functions mentioned above produce sequences of *bits*, but we sometimes need sequences of *bytes*. To this end we introduce a functions $\pad: \mathsf{Bits} \rightarrow \mathsf{Bits}$ which adds a sequence of $\mathsf{bits}~0$s followed by a $\mathsf{bits}~1$ to a sequence $s$ to get a sequence whose length is a multiple of 8; if $s$ is a sequence such that $\length(s)$ is already a multiple of 8 then $\pad$ still adds an extra byte of padding; $\pad$ is used both for internal alignment (for example, to make sure that the contents of a bytestring are aligned on byte boundaries) and at the end of a complete encoding of a Plutus Core program to make the length a multiple of 8 bits. Symbolically, $$\pad(s)  = s \cdot \mathsf{k} \quad \text{if $\length(s) = 8n+k$ with $n,k \in \N$ and $0 \leq k \leq 7$}$$ where $$\begin{align*}
 \mathsf{0} &= \mathsf{bits}~00000001 \\
 \mathsf{1} &= \mathsf{bits}~0000001  \\
 \mathsf{2} &= \mathsf{bits}~000001   \\
 \mathsf{3} &= \mathsf{bits}~00001    \\
 \mathsf{4} &= \mathsf{bits}~0001     \\
 \mathsf{5} &= \mathsf{bits}~001      \\
 \mathsf{6} &= \mathsf{bits}~01       \\
 \mathsf{7} &= \mathsf{bits}~1.
\end{align*}$$

We also define a (partial) inverse function $\unpad: \mathsf{Bits} \rightharpoonup
\mathsf{Bits}$ which discards padding: $$\unpad(q \cdot s) = s \quad \text{if $q = \mathsf{i}$ for some $i \in \{0,1,2,3,4,5,6,7\} $}.$$

This can fail if the padding is not of the expected form or if the input is the empty sequence $\epsilon$.

## Basic `flat` encodings
### Fixed-width natural numbers

We often wish to encode and decode natural numbers which fit into some fixed number of bits, and we do this simply by encoding them as their binary expansion (most significant bit first), adding leading zeros if necessary. More precisely for $n \geq 1$ we define an encoder $$\E_n : \mathsf{Bits} \times \mathsf{Nab}{0}{2^{n-1}-1} \rightarrow \mathsf{Bits}$$ by $$\E_n(s, \sum^{n-1}_{i=0}b_i2^i) = s \cdot b_{n-1} \cdots b_0 \quad \text{($b_i \in \{0,1\}$)}$$ and a decoder $$\D_n : \mathsf{Bits} \rightharpoonup \mathsf{Bits} \times \mathsf{Nab}{0}{2^{n-1}-1}$$ by $$\D_n(b_{n-1}\cdots{b_0} \cdot s)= (s,\sum^{n-1}_{i=0}b_i2^i).$$ As in Appendix appendix:data-cbor-encoding, $\mathsf{Nab}{a}{b}$ denotes the closed interval of integers $\{n \in \Z : a \leq n \leq b\}$. Note that $n$ here is a variable (not a fixed label) so we are defining whole families of encoders $\E_1, \E_2, \E_3, \ldots$ and decoders $\D_1, \D_2, \D_3\ldots$.

### Lists
Suppose that we have a set $X$ for which we have defined an encoder $\E_X$ and a decoder $\D_X$; we define an encoder $\mathsf{Elist}_X$ which encodes lists of elements of $X$ by emitting the encodings of the elements of the list, each preceded by a $\mathsf{bits}~1$ bit, then emitting a $\mathsf{bits}~0$ bit to mark the end of the list. $$\begin{align*}
  \mathsf{Elist}_X(s,[]) &= s \cdot \mathsf{bits}~0 \\
  \mathsf{Elist}_X(s,[x_1, \ldots, x_n]) &= \mathsf{Elist}_X (s \cdot \mathsf{bits}~1 \cdot \E_X(x_1), [x_2, \ldots, x_n]).
\end{align*}$$

The corresponding decoder is given by $$\begin{align*}
\mathsf{Dlist}_X(\mathsf{bits}~0 \cdot s) &= (s,[])\\
\mathsf{Dlist}_X(\mathsf{bits}~1 \cdot s) &= (s'', x \cdot l) \quad \text{if $D_X(s) = (s', x)$ and $\mathsf{Dlist}_X(s') = (s'', l).$}
\end{align*}$$

### Natural numbers

Every natural number $m$ can be uniquely written in the form

$$m = \sum_{i=0}^{n}k_i2^{7i}$$ with $n \geq 0$, $0 \leq k_i \leq 127$ for $0 \leq i \leq n$, and $k_n \ne 0$. Each $k_i$ is 7 bit binary block, $k_0$ being the least significant block.

With this representation, the encoder for natural numbers is

$$\E_{\N} (s, \sum_{i=0}^{n}k_i2^{7i}) =
\begin{cases}
  \E_7(\mathsf{Elist}_7(s, []), k_{0}) & \text{if } n = 0 \\
  \E_7(\mathsf{Elist}_7(s, [k_0, \ldots, k_{n-1}]), k_{n}) & \text{if } n \ne 0.
\end{cases}$$

The decoder is $$\D_{\N}(s) =
\begin{cases}
  D_7(s') & \text{if $\mathsf{Dlist}_7(s) = (s',[])$} \\
  (s'', \sum_{i=0}^{n}k_i2^{7i}) & \text{if $\mathsf{Dlist}_7(s) = (s', [k_0, \ldots, k_{n-1}])$ and $\D_7(s') = (s'', k_{n})$ with $n\geq 1$}.
\end{cases}$$

Intuitively, every 7 bit block except for the last one is prefixed by 1 and the last block is prefixed by 0.

### Integers

Signed integers are encoded by converting them to natural numbers using the zigzag encoding ($0 \mapsto 0, -1 \mapsto 1, 1 \mapsto 2, -2 \mapsto 3, 2
\mapsto 4, \ldots$) and then encoding the result using $\E_{\N}$: $$\E_{\Z} (s, n) =
\begin{cases}
  \E_{\N}(s, 2n) & \text{if $n \geq 0$}\\
  \E_{\N}(s, -2n-1) & \text{if $n < 0$}.
\end{cases}$$ The decoder is $$\D_{\Z}(s) =
\begin{cases}
  (s', \frac{n}{2}) & \text{if $n \equiv 0 \pmod 2$}\\
  (s', -\frac{n+1}{2}) & \text{if $n \equiv 1 \pmod 2$}
\end{cases} \quad\text{if $\D_{\N}(s) = (s', n)$}.$$

### Bytestrings

Bytestrings are encoded by dividing them into nonempty blocks of up to 255 bytes and emitting each block in sequence. Each block is preceded by a single unsigned byte containing its length, and the end of the encoding is marked by a zero-length block (so the empty bytestring is encoded just as a zero-length block). Before emitting a bytestring, the preceding output is padded so that its length (in bits) is a multiple of 8; if this is already the case a single padding byte is still added; this ensures that contents of the bytestring are aligned to byte boundaries in the output.

Recall that $\B$ denotes the set of 8-bit bytes, $\{0,1, \ldots, 255\}$. For specification purposes we may identify the set of bytestrings with the set $\B^*$ of (possibly empty) lists of elements of $\B$. We denote by $C$ the set of *bytestring chunks* of **nonempty** bytestrings of length at most 255: $C = \{[b_1, \ldots, b_n]: b_i \in \B, 1 \leq n \leq 255\}$, and define a function $E_C: C \rightarrow \mathsf{Bits}$ by $$E_C ([b_1, \ldots, b_n]) = \E_8(n) \cdot \E_8(b_1) \cdot \cdots \cdot \E_8(b_n).$$

We define an encoder $\E_{C^*}$ for lists of chunks by $$\E_{C^*} (s, [c_1, \ldots, c_n]) = s \cdot E_C(c_1) \cdot \cdots \cdot E_C(c_n) \cdot \mathsf{bits}~00000000.$$ Note that each $c_i$ is required to be nonempty but that we allow the case $n = 0$, so that an empty list of chunks encodes as $\mathsf{bits}~00000000$.

To encode a bytestring we decompose it into a list $L$ of chunks and then apply $\E_{C^*}$ to $L$. However, there will usually be many ways to decompose a given bytestring $a$ into chunks. For definiteness we recommend (but do not demand) that $a$ is decomposed into a sequence of chunks of length 255 possibly followed by a smaller chunk. Formally, suppose that $a = [a_1, \ldots,
  a_{255k+r}] \in \B^*\backslash\{\epsilon\}$ where $k \geq 0$ and $0 \leq r
\leq 254$. We define the *canonical 256-byte decomposition* $\tilde{a}$ of $a$ to be $$\tilde{a} = [[a_1, \ldots, a_{255}],
  [a_{256}, \ldots, a_{510}],\ldots
  [a_{255(k-1)+1}, \ldots, a_{255k}]] \in C^*$$ if $r=0$ and $$\tilde{a} = [[a_1, \ldots, a_{255}],
  [a_{256}, \ldots, a_{510}],\ldots
  [a_{255(k-1)+1}, \ldots, a_{255k}], [a_{255k+1}, \ldots, a_{255k+r}]] \in C^*$$ if $r>0$.

For the empty bytestring we define $$\tilde{\epsilon} = [].$$

Given all of the above, we define the canonical encoding function $\E_{\B^*}$ for bytestrings to be $$\E_{\B^*}(s, a) = E_{C^*}(\pad(s), \tilde{a}).$$ Non-canonical encodings can be obtained by replacing $\tilde{a}$ with any other decomposition of $a$ into nonempty chunks, and the decoder below will accept these as well.

To define a decoder for bytestrings we first define a decoder $\D_{C}$ for bytestring chunks:

$$\D_{C}(s) = \D_C^{(n)}(s',[]) \quad \text{if $\D_8(s) = (s', n)$}$$ where $$\D^{(n)}_C (s, l) =
\begin{cases}
  (s, l) & \text{if $n=0$}\\
  \D^{(n-1)}_C (s',l\cdot x)  & \text{if $n > 0$ and $\D_8(s) = (s',x)$.}
\end{cases}$$ Now we define $$\D_{C^*}(s) =
\begin{cases}
  (s', []) & \text{if $D_C(s) = (s', [])$}\\
  (s'', x \cdot l) & \text{if $\D_C(s) = (s', x)$ with $x \ne []$ and $\D_{C^*}(s') = (s'', l)$}.
\end{cases}$$ The notation is slightly misleading here: $\D_{C^*}$ does not decode to a list of bytestring chunks, but to a single bytestring. We could alternatively decode to a list of bytestrings and then concatenate them later, but this would have the same overall effect.

Finally, we define the decoder for bytestrings by $$\D_{\B^*} (s) = \D_{C^*}(\unpad(s)).$$

### Strings

We have defined values of the `string` type to be sequences of Unicode characters. As mentioned earlier we do not specify any particular internal representation of Unicode characters, but for serialisation we use the UTF-8 representation to convert between strings and bytestrings and then use the bytestring encoder and decoder:

$$\E_{\U^*}(s,u) = \E_{\B^*}(s,\utfeight(u))$$

$$\D_{\U^*}(s) = (s', \unutfeight(a)) \quad \text{if $\D_{\B^*}(s) = (s', a)$}$$

where $\utfeight$ and $\unutfeight$ are the UTF8 encoding and decoding functions mentioned in Section sec:default-builtins-1. Recall that $\unutfeight$ is partial (not all bytestrings represent valid Unicode sequences), so $\D_{\U^*}$ may fail if the input is invalid.

## Encoding and decoding Plutus Core

### Programs

A program is encoded by encoding the three components of the version number in sequence then encoding the body, and possibly adding some padding to ensure that the total number of bits in the output is a multiple of 8 (and hence the output can be viewed as a bytestring). $$\mathsf{Eprogram}(\mathsf{Prog}{a}{b}{c}{t}) =
\pad(\mathsf{Eterm}(\E_{\N}(\E_{\N}(\E_{\N}(\epsilon, a), b), c), t)).$$

The decoding process is the inverse of the encoding process: three natural numbers are read to obtain the version number and then the body is decoded. After this we discard any padding in the remaining input and check that all of the input has been consumed. $$\mathsf{Dprogram}(s) = \mathsf{Prog}{a}{b}{c}{t} \quad
\begin{cases}
  \text{ if }  &\D_{\N}(s) = (s', a)\\
  \text{ and } &\D_{\N}(s') = (s'', b)\\
  \text{ and } &\D_{\N}(s'') = (s''', c)\\
  \text{ and } &\mathsf{Dterm}(s''') = (r, t)\\
  \text{ and } &\unpad(r) = \epsilon.
\end{cases}$$

### Terms
Plutus Core terms are encoded by emitting a 4-bit tag identifying the type of the term (see Table 1.1; recall that `[]` denotes application) then emitting the encodings for any subterms. We currently only use ten of the sixteen available tags: the remainder are reserved for potential future expansion.


  Term type       Binary       Decimal
  ----------- --------------- ---------
  Variable     $\mathsf{bits}~0000$      0
  `delay`      $\mathsf{bits}~0001$      1
  `lam`        $\mathsf{bits}~0010$      2
  `[]`         $\mathsf{bits}~0011$      3
  `const`      $\mathsf{bits}~0100$      4
  `force`      $\mathsf{bits}~0101$      5
  `error`      $\mathsf{bits}~0110$      6
  `builtin`    $\mathsf{bits}~0111$      7
  `constr`     $\mathsf{bits}~1000$      8
  `case`       $\mathsf{bits}~1001$      9

  : Term tags

The encoder for terms is given below: it refers to other encoders (for names, types, and constants) which will be defined later.

$$\begin{alignat*}
{2}
&  \mathsf{Eterm}(s,x)                 &&= \mathsf{Ename}(s \cdot \mathsf{bits}~0000,x) \\
&  \mathsf{Eterm}(s, \mathsf{Delay}{t})        &&=\mathsf{Eterm}(s \cdot \mathsf{bits}~0001, t) \\
&  \mathsf{Eterm}(s, \mathsf{Lam}{x}{t})       &&= \mathsf{Eterm}(\mathsf{Ebinder}(s \cdot \mathsf{bits}~0010, x), t) \\
&  \mathsf{Eterm}(s, \mathsf{Apply}{t_1}{t_2}) &&= \mathsf{Eterm}(\mathsf{Eterm}(s \cdot \mathsf{bits}~0011, t_1), t_2)\\
&  \mathsf{Eterm}(s, \mathsf{Const}{tn}{c})    &&= \mathsf{Econstant}{tn}(\mathsf{Etype}(s \cdot \mathsf{bits}~0100, \tn), c) \\
&  \mathsf{Eterm}(s, \mathsf{Force}{t})        &&= \mathsf{Eterm}(s \cdot \mathsf{bits}~0101, t) \\
&  \mathsf{Eterm}(s, \mathsf{Error})           &&= s \cdot \mathsf{bits}~0110 \\
&  \mathsf{Eterm}(s, \mathsf{Builtin}{b})      &&= \mathsf{Ebuiltin}(s \cdot \mathsf{bits}~0111, b) \\
&  \mathsf{Eterm}(s, \mathsf{Constr}{i}{l})    &&= \mathsf{Elist}_{\mathsf{term}}(\E_{\N}(s \cdot \mathsf{bits}~1000, i), l) \\
&  \mathsf{Eterm}(s, \mathsf{Kase}{u}{l})      &&= \mathsf{Elist}_{\mathsf{term}}(\mathsf{Eterm}(s \cdot \mathsf{bits}~1001, u), l)
\end{alignat*}$$

The decoder for terms is given below. To simplify the definition we use some pattern-matching syntax for inputs to decoders: for example the argument $\mathsf{bits}~0101 \cdot s$ indicates that when the input is a string beginning with $\mathsf{bits}~0101$ the definition after the $=$ sign should be used (and the remainder of the input is available in $s$ there). If the input is not long enough to permit the indicated decomposition then the decoder fails. The decoder also fails if the input begins with a prefix which is not listed; that does not happen here, but does in some later decoders.

$$\begin{alignat*}
{5}
  \mathsf{Dterm}(\mathsf{bits}~0000 \cdot s)  &= (s', x) &&\quad \text{if } \mathsf{Dname}(s) = (s', x) \\
  \mathsf{Dterm}(\mathsf{bits}~0001 \cdot s)  &= (s', \mathsf{Delay}{t})  &&\quad \text{if}\ \mathsf{Dterm}(s) = (s', t) \\
  \mathsf{Dterm}(\mathsf{bits}~0010 \cdot s)  &= (s'', \mathsf{Lam}{x}{t})  &&\quad \text{if}\ \mathsf{Dbinder}(s) = (s', x)
                                                           &&\ \text{and}\ \mathsf{Dterm}(s') = (s'', t) \\
  \mathsf{Dterm}(\mathsf{bits}~0011 \cdot s)  &= (s'', \mathsf{Apply}{t_1}{t_2}) &&\quad \text{if}\ \mathsf{Dterm}(s) = (s', t_1)
                                                  &&\ \text{and}\ \mathsf{Dterm}(s') = (s'', t_2) \\
  \mathsf{Dterm}(\mathsf{bits}~0100 \cdot s)  &= (s'', \mathsf{Const}{tn}{c}) &&\quad \text{if}\ \mathsf{Dtype}(s) = (s', \tn)
                                                           &&\ \text{and}\ \dConstant{\tn}(s') =(s'', c) \\
  \mathsf{Dterm}(\mathsf{bits}~0101 \cdot s)  &= (s', \mathsf{Force}{t})  &&\quad \text{if}\ \mathsf{Dterm}(s) = (s', t) \\
  \mathsf{Dterm}(\mathsf{bits}~0110 \cdot s)  &= (s, \mathsf{Error})  && \\
  \mathsf{Dterm}(\mathsf{bits}~0111 \cdot s)  &= (s', \mathsf{Builtin}{b}) &&\quad \text{if } \mathsf{Dbuiltin}(s) = (s', b) \\
  \mathsf{Dterm}(\mathsf{bits}~1000 \cdot s)  &= (s'', \mathsf{Constr}{i}{l}) &&\quad \text{if } \D_{\N}(s) = (s', i)\ \text{and}\ i < 2^{64} &&\ \text{and}\ \mathsf{Dlist}_{\mathsf{term}}(s') = (s'', l)\\
  \mathsf{Dterm}(\mathsf{bits}~1001 \cdot s)  &= (s'', \mathsf{Kase}{u}{l}) &&\quad \text{if } \mathsf{Dterm}(s) = (s', u) &&\ \text{and}\ \mathsf{Dlist}_{\mathsf{term}}(s') = (s'', l)
\end{alignat*}$$

##### NOTE.

The decoder $\mathsf{Dterm}$ should fail if we are decoding a program with a version less than 1.1.0 and an input of the form $\mathsf{bits}~1000 \cdot s$ or $\mathsf{bits}~1001 \cdot s$ is encountered. It should also fail when decoding a `constr` term if a tag is encountered which is greater than or equal to $2^{64}$ (this enforces the 64-bit limitation mentioned in the paragraph headed **Constructor tags** in Section sec:grammar-notes).

### Built-in types

Constants from built-in types are essentially encoded by emitting a sequence of 4-bit tags representing the constant's type and then emitting the encoding of the constant itself. However the encoding of types is somewhat complex because it has to be able to deal with type operators such as $\ty{list}$ and $\ty{pair}$. The tags are given in Table 1.2: they include tags for the basic types together with a tag for a type application operator.


  Type                                 Binary       Decimal
  -------------------------------- --------------- ---------
  $\ty{integer}$                    $\mathsf{bits}~0000$      0
  $\ty{bytestring}$                 $\mathsf{bits}~0001$      1
  $\ty{string}$                     $\mathsf{bits}~0010$      2
  $\ty{unit}$                       $\mathsf{bits}~0011$      3
  $\ty{bool}$                       $\mathsf{bits}~0100$      4
  $\ty{list}$                       $\mathsf{bits}~0101$      5
  $\ty{pair}$                       $\mathsf{bits}~0110$      6
  (type application)                $\mathsf{bits}~0111$      7
  $\ty{data}$                       $\mathsf{bits}~1000$      8
  $\ty{bls12\_381\_G1\_element}$    $\mathsf{bits}~1001$      9
  $\ty{bls12\_381\_G2\_element}$    $\mathsf{bits}~1010$     10
  $\ty{bls12\_381\_MlResult}$       $\mathsf{bits}~1011$     11
  $\ty{array}$                      $\mathsf{bits}~1100$     12

  : Type tags

We define auxiliary functions $\mathsf{e}_{\mathsf{type}}: \mathsf{Uni} \rightarrow \N^*$ and $\mathsf{d}_{\mathsf{type}}: \N^* \rightharpoonup \N^* \times \mathsf{Uni}$ ($\mathsf{d}_{\mathsf{type}}$ is partial and $\mathsf{Uni}$ denotes the universe of types defined in Sections sec:default-builtins-1, sec:default-builtins-2, and sec:default-builtins-3).

$$\begin{alignat*}
{2}
  &\mathsf{e}_{\mathsf{type}}(\ty{integer})      &&= [0]  \\
  &\mathsf{e}_{\mathsf{type}}(\ty{bytestring})   &&= [1]  \\
  &\mathsf{e}_{\mathsf{type}}(\ty{string})       &&= [2]  \\
  &\mathsf{e}_{\mathsf{type}}(\ty{unit})         &&= [3]  \\
  &\mathsf{e}_{\mathsf{type}}(\ty{bool})         &&= [4]  \\
  &\mathsf{e}_{\mathsf{type}}(\listOf{t})        &&= [7,5] \cdot \mathsf{e}_{\mathsf{type}}(t) \\
  &\mathsf{e}_{\mathsf{type}}(\arrayOf{t})       &&= [7,12] \cdot \mathsf{e}_{\mathsf{type}}(t) \\
  &\mathsf{e}_{\mathsf{type}}(\pairOf{t_1}{t_2}) &&= [7,7,6] \cdot \mathsf{e}_{\mathsf{type}}(t_1) \cdot \mathsf{e}_{\mathsf{type}}(t_2)\\
  &\mathsf{e}_{\mathsf{type}}(\ty{data})         &&= [8].
\end{alignat*}$$

$$\begin{alignat*}
{3}
 &\mathsf{d}_{\mathsf{type}}(0 \cdot l) &&= (l, \ty{integer})    \\
 &\mathsf{d}_{\mathsf{type}}(1 \cdot l) &&= (l, \ty{bytestring}) \\
 &\mathsf{d}_{\mathsf{type}}(2 \cdot l) &&= (l, \ty{string})    \\
 &\mathsf{d}_{\mathsf{type}}(3 \cdot l) &&= (l, \ty{unit})       \\
 &\mathsf{d}_{\mathsf{type}}(4 \cdot l) &&= (l, \ty{bool})       \\
 &\mathsf{d}_{\mathsf{type}}([7,5] \cdot l) &&= (l', \listOf{t}) &&\quad \text{if $\mathsf{d}_{\mathsf{type}}(l) = (l', t)$}\\
 &\mathsf{d}_{\mathsf{type}}([7,12] \cdot l) &&= (l', \arrayOf{t}) &&\quad \text{if $\mathsf{d}_{\mathsf{type}}(l) = (l', t)$}\\
 &\mathsf{d}_{\mathsf{type}}([7,7,6] \cdot l) &&= (l'', \pairOf{t_1}{t_2})
  &&\ \begin{cases}
      \text{if} & \mathsf{d}_{\mathsf{type}}(l) = (l', t_1)\\
      \text{and} & \mathsf{d}_{\mathsf{type}}(l') = (l'', t_2)
    \end{cases}\\
  &\mathsf{d}_{\mathsf{type}}(8 \cdot l) &&= (l, \ty{data}).
\end{alignat*}$$

The encoder and decoder for types is obtained by combining $\mathsf{e}_{\mathsf{type}}$ and $\mathsf{d}_{\mathsf{type}}$ with $\mathsf{Elist}_4$ and $\mathsf{Dlist}_4$, the encoder and decoder for lists of four-bit integers (see Section 1.2).

$$\mathsf{Etype}(s,t) = \mathsf{Elist}_4 (s, \mathsf{e}_{\mathsf{type}}(t))$$

$$\mathsf{Dtype}(s) = (s', t) \quad \text{if $\mathsf{Dlist}_4(s) = (s', l)$ and $\mathsf{d}_{\mathsf{type}}(l) = ([], t)$}.$$

### Constants
Values of built-in types can mostly be encoded quite simply by using encoders already defined:

$$\begin{alignat*}
{2}
  & \mathsf{Econstant}{\ty{integer}}(s,n)                  &&= \E_{\Z}(s, n) \\
  & \mathsf{Econstant}{\ty{bytestring}}(s,a)               &&= \E_{\B^*}(s, a) \\
  & \mathsf{Econstant}{\ty{string}}(s,t)                   &&= \E_{\U^*}(s, t) \\
  & \mathsf{Econstant}{\ty{unit}}(s,c)                     &&= s  \\
  & \mathsf{Econstant}{\ty{bool}}(s, \texttt{False})       &&= s \cdot \mathsf{bits}~0\\
  & \mathsf{Econstant}{\ty{bool}}(s, \texttt{True})        &&= s \cdot \mathsf{bits}~1\\
  & \mathsf{Econstant}{\listOf{\tn}}(s,l)                  &&= \mathsf{Elist}^{\tn}_{\mathsf{constant}}(s, l) \\
  & \mathsf{Econstant}{\arrayOf{\tn}}(s,a)                 &&= \mathsf{Earray}^{\tn}_{\mathsf{constant}}(s, a) \\
  & \mathsf{Econstant}{\pairOf{\tn_1}{\tn_2}}(s,(c_1,c_2)) &&= \mathsf{Econstant}{\tn_2}(\mathsf{Econstant}{\tn_1}(s, c_1), c_2)\\
  & \mathsf{Econstant}{\ty{data}}(s,d)                     &&= \E_{\B^*}(s, \eData(d))
\end{alignat*}$$

$$\begin{alignat*}
{3}
  &\dConstant{\ty{integer}}(s)              &&= \D_{\Z}(s) \\
  &\dConstant{\ty{bytestring}}(s)           &&= \D_{\B^*}(s) \\
  &\dConstant{\ty{string}}(s)               &&= \D_{\U^*}(s) \\
  &\dConstant{\ty{unit}}(s)                 &&= s  \\
  &\dConstant{\ty{bool}}(\mathsf{bits}~0 \cdot s)  &&= (s, \texttt{False}) \\
  &\dConstant{\ty{bool}}(\mathsf{bits}~1 \cdot s)  &&= (s, \texttt{True}) \\
  &\dConstant{\listOf{\tn}}(s)              &&= \mathsf{Dlist}^{\tn}_{\mathsf{constant}}(s) \\
  &\dConstant{\arrayOf{\tn}}(s)             &&= \mathsf{Darray}^{\tn}_{\mathsf{constant}}(s) \\
  &\dConstant{\pairOf{\tn_1}{\tn_2}}(s)     &&= (s'', (c_1, c_2))
  && \begin{cases}
       \text{if}  & \dConstant{\tn_1}(s) = (s', c_1) \\
       \text{and} & \dConstant{\tn_2}(s') = (s'', c_2)
     \end{cases}\\
  &\dConstant{\ty{data}}(s)                  &&= (s', d) &&
                                           \text{if $\D_{\B*}(s) = (s', t)$
                                            and $\dData(t) = (t', d)$ for some $t'$}.
\end{alignat*}$$

##### Units.

The unit value `(con unit ())` does not have an explicit encoding: the type has only one possible value, so there is no need to use any space to serialise it.

##### Data.

The $\ty{data}$ type is encoded by converting to a bytestring using the CBOR encoder $\eData$ described in Appendix appendix:data-cbor-encoding and then using $\E_{\B^*}$. The decoding process is the opposite of this: a bytestring is obtained using $\D_{\B^*}$ and this is then decoded from CBOR using $\dData$ to obtain a $\ty{data}$ object.

##### Arrays.

Arrays use the same encoders and decoders as lists (see Section 1.2.2): given a set $X$ for which we have defined an encoder $\E_X$ and a decoder $\D_X$, arrays of elements of $X$ are encoded using $\mathsf{Elist}_X$ and decoded using $\mathsf{Dlist}_X$. In practice the run-time implementations of lists and arrays may differ and some extra work may be required to convert arrays to lists before encoding and lists to arrays after decoding.

##### BLS12-381 elements.

We do not provide serialisation and deserialisation methods for constants of type $\ty{bls12\_381\_G1\_element}$, $\ty{bls12\_381\_G2\_element}$, or $\ty{bls12\_381\_mlresult}$. We have specified tags for these types, but if one of these tags is encountered during deserialisation then deserialisation fails and any subsequent input is ignored. Note however that constants of the first two types can be serialised by using the compression functions defined in Section sec:bls-builtins-4 and serialising the resulting bytestrings. Decoding can similarly be performed indirectly by using `bls12_381_G1_uncompress` and `bls12_381_G2_uncompress` on bytestring constants during program execution.

### Built-in functions

Built-in functions are represented by seven-bit integer tags and encoded and decoded using $\E_7$ and $\D_7$. The tags are specified in Tables 1.3--1.7. We assume that there are (partial) functions $\mathsf{Tag}$ and $\unTag$ which convert back and forth between builtin names and their tags.

$$\begin{alignat*}
{2}
  & \mathsf{Ebuiltin}(s,b) &&= \E_7(s, \mathsf{Tag}(b))\\
  & \mathsf{Dbuiltin}(s)   &&= (s', \unTag(n)) \quad \text{if $\D_7(s) = (s', n)$}.\\
\end{alignat*}$$


  Builtin         Binary        Decimal  Builtin         Binary        Decimal
  --------- ------------------ --------- --------- ------------------ ---------
             $\mathsf{bits}~0000000$      0                $\mathsf{bits}~0011010$     26
             $\mathsf{bits}~0000001$      1                $\mathsf{bits}~0011011$     27
             $\mathsf{bits}~0000010$      2                $\mathsf{bits}~0011100$     28
             $\mathsf{bits}~0000011$      3                $\mathsf{bits}~0011101$     29
             $\mathsf{bits}~0000100$      4                $\mathsf{bits}~0011110$     30
             $\mathsf{bits}~0000101$      5                $\mathsf{bits}~0011111$     31
             $\mathsf{bits}~0000110$      6                $\mathsf{bits}~0100000$     32
             $\mathsf{bits}~0000111$      7                $\mathsf{bits}~0100001$     33
             $\mathsf{bits}~0001000$      8                $\mathsf{bits}~0100010$     34
             $\mathsf{bits}~0001001$      9                $\mathsf{bits}~0100011$     35
             $\mathsf{bits}~0001010$     10                $\mathsf{bits}~0100100$     36
             $\mathsf{bits}~0001011$     11                $\mathsf{bits}~0100101$     37
             $\mathsf{bits}~0001100$     12                $\mathsf{bits}~0100110$     38
             $\mathsf{bits}~0001101$     13                $\mathsf{bits}~0100111$     39
             $\mathsf{bits}~0001110$     14                $\mathsf{bits}~0101000$     40
             $\mathsf{bits}~0001111$     15                $\mathsf{bits}~0101001$     41
             $\mathsf{bits}~0010000$     16                $\mathsf{bits}~0101010$     42
             $\mathsf{bits}~0010001$     17                $\mathsf{bits}~0101011$     43
             $\mathsf{bits}~0010010$     18                $\mathsf{bits}~0101100$     44
             $\mathsf{bits}~0010011$     19                $\mathsf{bits}~0101101$     45
             $\mathsf{bits}~0010100$     20                $\mathsf{bits}~0101110$     46
             $\mathsf{bits}~0010101$     21                $\mathsf{bits}~0101111$     47
             $\mathsf{bits}~0010110$     22                $\mathsf{bits}~0110000$     48
             $\mathsf{bits}~0010111$     23                $\mathsf{bits}~0110001$     49
             $\mathsf{bits}~0011000$     24                $\mathsf{bits}~0110010$     50
             $\mathsf{bits}~0011001$     25                                  

  : Tags for built-in functions (Batch 1)

  Builtin         Binary        Decimal
  --------- ------------------ ---------
             $\mathsf{bits}~0110011$     51

  : Tags for built-in functions (Batch 2)

  Builtin         Binary        Decimal
  --------- ------------------ ---------
             $\mathsf{bits}~0110100$     52
             $\mathsf{bits}~0110101$     53

  : Tags for built-in functions (Batch 3)


  Builtin         Binary        Decimal
  --------- ------------------ ---------
             $\mathsf{bits}~0110110$     54
             $\mathsf{bits}~0110111$     55
             $\mathsf{bits}~0111000$     56
             $\mathsf{bits}~0111001$     57
             $\mathsf{bits}~0111010$     58
             $\mathsf{bits}~0111011$     59
             $\mathsf{bits}~0111100$     60
             $\mathsf{bits}~0111101$     61
             $\mathsf{bits}~0111110$     62
             $\mathsf{bits}~0111111$     63
             $\mathsf{bits}~1000000$     64
             $\mathsf{bits}~1000001$     65
             $\mathsf{bits}~1000010$     66
             $\mathsf{bits}~1000011$     67
             $\mathsf{bits}~1000100$     68
             $\mathsf{bits}~1000101$     69
             $\mathsf{bits}~1000110$     70
             $\mathsf{bits}~1000111$     71
             $\mathsf{bits}~1001000$     72
             $\mathsf{bits}~1001000$     73
             $\mathsf{bits}~1001000$     74

  : Tags for built-in functions (Batch 4)

  Builtin         Binary        Decimal
  --------- ------------------ ---------
             $\mathsf{bits}~1001011$     75
             $\mathsf{bits}~1001100$     76
             $\mathsf{bits}~1001101$     77
             $\mathsf{bits}~1001110$     78
             $\mathsf{bits}~1001111$     79
             $\mathsf{bits}~1010000$     80
             $\mathsf{bits}~1010001$     81
             $\mathsf{bits}~1010010$     82
             $\mathsf{bits}~1010011$     83
             $\mathsf{bits}~1010100$     84
             $\mathsf{bits}~1010101$     85
             $\mathsf{bits}~1010110$     86

  : Tags for built-in functions (Batch 5)

  Builtin         Binary        Decimal
  --------- ------------------ ---------
             $\mathsf{bits}~1010111$     87
             $\mathsf{bits}~1011000$     88
             $\mathsf{bits}~1011001$     89
             $\mathsf{bits}~1011010$     90
             $\mathsf{bits}~1011011$     91
             $\mathsf{bits}~1011100$     92
             $\mathsf{bits}~1011101$     93

  : Tags for built-in functions (Batch 6)

### Variable names

Variable names are encoded and decoded using the $\mathsf{Ename}$ and $\mathsf{Dname}$ functions, and variables bound in `lam` expressions are encoded and decoded by the $\mathsf{Ebinder}$ and $\mathsf{Dbinder}$ functions.

##### De Bruijn indices.

We use serialised de Bruijn-indexed terms for script transmission because this makes serialised scripts significantly smaller. Recall from Section sec:grammar-notes that when we want to use our syntax with de Bruijn indices we replace names with natural numbers and the bound variable in a `lam` expression with 0. During serialisation the zero is ignored, and during deserialisation no input is consumed and the index 0 is always returned:

$$\mathsf{Ebinder}(s, n) = s$$ $$\mathsf{Dbinder}(s) = 0.$$

For variables we always use indices which are greater than zero, and our encoder and decoder for names are given by $$\mathsf{Ename} = \E_{\N}$$ and $$\mathsf{Dname} (s) = (s', n) \quad \text{if $\D_{\N} = (s', n)$ and $n>0$}.$$

##### Other types of name.

One can serialise code involving other types of name by providing suitable encoders and decoders for name. For example, for textual names one could use $\mathsf{Ebinder} = \mathsf{Ename} = \E_{\U^*}$ and $\mathsf{Dbinder} = \mathsf{Dname} = \D_{\U^*}$. Depending on the method used to represent variable names it may also be necessary to check during deserialisation the more general requirement that variables are well-scoped, but this problem will not arise if de Bruijn indices are used.

## Cardano-specific serialisation issues
### Scope checking

To execute a Plutus Core program on the blockchain it will be necessary to deserialise it to some in-memory representation, and during or immediately after deserialisation it should be checked that the body of the program is a closed term (see the requirement in Section sec:grammar-notes); if this is not the case then evaluation should fail immediately.

### CBOR wrapping

Plutus Core programs are not stored on the Cardano chain directly as `flat` bytestrings; for consistency with other objects used on the chain, the `flat` bytestrings are in fact wrapped in a CBOR encoding. This should not concern most users, but we mention it here to avoid possible confusion.

## Example

Consider the program

    (program 5.0.2
     [
      [(builtin indexByteString)(con bytestring #1a5f783625ee8c)]
      (con integer 54321)
     ])

Suppose this is stored in `index.uplc`. We can convert it to `flat` by running

    $ cabal run exec uplc convert -- -i index.uplc --of flat -o index.flat

The serialised program looks like this:

    $ xxd -b index.flat
    00000000: 00000101 00000000 00000010 00110011 01110001 11001001  ...3q.
    00000006: 00010001 00000111 00011010 01011111 01111000 00110110  ..._x6
    0000000c: 00100101 11101110 10001100 00000000 01001000 00111000  %...H8
    00000012: 10110100 00000001 10000001

Figure 1.1 shows how this encodes the original program. Sequences of bits are followed by explanatory comments and lines beginning with `#` provide further commentary on preceding bit sequences.


``` {commandchars="\\\\\\{\\}"}
00000101 : \textrm{Final integer chunk: \texttt{0000101} \arrow 5}
             00000000 : \textrm{Final integer chunk: \texttt{0000000} \arrow 0}
             00000010 : \textrm{Final integer chunk: \texttt{0000000} \arrow 2}
                      \# \textrm{Version: 5.0.2}
             0011     : \textrm{Term tag 3: apply}
             0011     : \textrm{Term tag 3: apply}
             0111     : \textrm{Term tag 7: builtin}
             0001110  : \textrm{Builtin tag 14}
                      \# builtin indexByteString
             0100     : \textrm{Term tag 4: constant}
             1        : \textrm{Start of type tag list}
             0001     : \textrm{Type tag 1}
             0        : \textrm{End of list}
                      \# \textrm{Type tags: [1] \arrow \texttt{bytestring}}
             001      : \textrm{Padding before bytestring}
             00000111 : \textrm{Bytestring chunk size: 7}
             00011010 : 0x1a
             01011111 : 0x5f
             01111000 : 0x78
             00110110 : 0x36
             00100101 : 0x25
             11101110 : 0xee
             10001100 : 0x8c
             00000000 : \textrm{Bytestring chunk size: 0 (end of list of chunks)}
                      \# con bytestring \#1a5f783625ee8c
             0100     : \textrm{Term tag 4: constant}
             1        : \textrm{Start of type tag list}
             0000     : \textrm{Type tag 0}
             0        : \textrm{End of list}
                      \# \textrm{Type tags: [0] \arrow \texttt{integer}}
             11100010 : \textrm{Integer chunk \texttt{1100010} (least significant)}
             11010000 : \textrm{Integer chunk \texttt{1010000}}
             00000110 : \textrm{Final integer chunk \texttt{0000110} (most significant)}
                      \# 0000110 \(\cons\) 1010000 \(\cons\) 1100010 \textrm{\arrow 108642 decimal}
                      \# \textrm{Zigzag encoding: 108642/2 \arrow +54321}
                      \# con integer 54321
             000001   : \textrm{Padding}
```

**`flat` encoding of `index.uplc`**