# Serialising `data` Objects Using the CBOR Format
## Introduction

In this section we define a CBOR encoding for the `data` type introduced in Section sec:built-in-types-1. For ease of reference we reproduce the definition of the Haskell `Data` type, which we may regard as the definition of the Plutus `data` type. Other representations are of course possible, but this is useful for the present discussion.

`data``\ `{=latex}`Data``\ `{=latex}`=`\
`Constr``\ `{=latex}`Integer``\ `{=latex}`[Data]`\
`|``\ `{=latex}`Map``\ `{=latex}`[(Data,``\ `{=latex}`Data)]`\
`|``\ `{=latex}`List``\ `{=latex}`[Data]`\
`|``\ `{=latex}`I``\ `{=latex}`Integer`\
`|``\ `{=latex}`B``\ `{=latex}`ByteString`

The CBOR encoding defined here uses basic CBOR encodings as defined in the CBOR standard [@rfc8949-CBOR], but with some refinements. Specifically

- We use a restricted encoding for bytestrings which requires that bytestrings are serialised as sequences of blocks, each block being at most 64 bytes long. Any encoding of a bytestring using our scheme is valid according to the CBOR specification, but the CBOR specification permits some encodings which we do not accept. The purpose of the size restriction is to prevent arbitrary data from being stored on the blockchain.

- Large integers (less than $-2^{64}$ or greater than $2^{64}-1$) are encoded via the restricted bytestring encoding; other integers are encoded as normal. Again, our restricted encodings are compatible with the CBOR specification.

- The `Constr` case of the `data` type is encoded using a scheme which is an early version of a proposed extension of the CBOR specification to include encodings for discriminated unions. See [@CBOR-alternatives] and [@CBOR-notable-tags Section 9.1].

## Notation

We introduce some extra notation for use here and in Appendix appendix:flat-serialisation.

The notation $f: X \rightharpoonup Y$ indicates that $f$ is a partial map from $X$ to $Y$. We denote the empty bytestring by $\epsilon$ and (as in sec:notation-lists) use $\length(s)$ to denote the length of a bytestring $s$ and $\cdot$ to denote the concatenation of two bytestrings, and also the operation of prepending or appending a byte to a bytestring. We will also make use of the $\divfn$ and $\modfn$ functions described in Note note:integer-division-functions in Section sec:default-builtins-1.

##### Encoders and decoders.

Recall that $\B = \mathsf{Nab}{0}{255}$, the set of integral values that can be represented in a single byte, and that we identify bytestrings with elements of $\B^*$. We will describe the CBOR encoding of the `data` type by defining families of encoding functions (or *encoders*) $$\e_X : X \rightarrow \B^*$$ and decoding functions (or *decoders*) $$\d_X : \B^* \rightharpoonup \B^* \times X$$

for various sets $X$, such as the set $\Z$ of integers and the set of all `data` items. The encoding function $\e_X$ takes an element $x \in
X$ and converts it to a bytestring, and the decoding function $\d_X$ takes a bytestring $s$, decodes some initial prefix of $s$ to a value $x \in X$, and returns the remainder of $s$ together with $x$. Decoders for complex types will often be built up from decoders for simpler types. Decoders are *partial* functions because they can fail, for instance, if there is insufficient input, or if the input is not well formed, or if a decoded value is outside some specified range.

Many of the decoders which we define below involve a number of cases for different forms of input, and we implicitly assume that the decoder fails if none of the cases applies. We also assume that if a decoder fails then so does any other decoder which invokes it, so any failure when attempting to decode a particular data item in a bytestring will cause the entire decoding process to fail (immediately).

## The CBOR format

A CBOR-encoded item consists of a bytestring beginning with a *head* which occupies 1,2,3,5, or 9 bytes. Depending on the contents of the head, some sequence of bytes following it may also contribute to the encoded item. The first three bits of the head are interpreted as a natural number between 0 and 7 (the *major type*) which gives basic information about the type of the following data. The remainder of the head is called the *argument* of the head and is used to encode further information, such as the value of an encoded integer or the size of a list of encoded items. Encodings of complex objects may occupy the bytes following the head, and these will typically contain further encoded items.

## Encoding and decoding the heads of CBOR items

For $i \in \N$ we define a function $\byte_i: \N \rightarrow \B$ which returns the $i$-th byte of an integer, with the 0-th byte being the least significant: $$\byte_i(n) = \modfn(\divfn(n,256^i), 256).$$

We use this to define for each $k \geq 1$ a partial function $\intToBS_k: \N \rightharpoonup \B^*$ which converts a sufficiently small integer to a bytestring of length $k$ (possibly with leading zeros): $$\intToBS_k(n) = [\byte_{k-1}(n), \ldots, \byte_0(n)]  \quad \text {if $n \leq 256^k-1$}.$$ This function fails if the input is too large to fit into a $k$-byte bytestring.

We also define inverse functions $\bsToInt_k: \B^* \rightharpoonup \N$ which decode a $k$-byte natural number from the start of a bytestring, failing if there is insufficient input: $$\bsToInt_k(s) = (s', \sum_{i=0}^{k-1}256^ib_i) \qquad \text{if $s = [b_{k-1},
    \ldots, b_0] \cdot s'$}.$$

We now define an encoder $\eHead: \mathsf{Nab}{0}{7} \times
\mathsf{Nab}{0}{2^{64}-1} \rightarrow \B^*$ which takes a major type and a natural number and encodes them as a CBOR head using the standard encoding:

$$\eHead(m,n) =
  \begin{cases}
    [32m + n] & \text{if $n \leq 23$}\\
    (32m+24) \cdot \intToBS_1(n) & \text{if $24 \leq n \leq 255$}\\
    (32m+25) \cdot \intToBS_2(n) & \text{if $256 \leq n \leq 256^2-1$}\\
    (32m+26) \cdot \intToBS_4(n)& \text{if $256^2 \leq n \leq 256^4-1$}\\
    (32m+27) \cdot \intToBS_8(n) & \text{if $256^4 \leq n \leq 256^8-1$}.
  \end{cases}$$

The corresponding decoder $\dHead: \B^* \rightharpoonup \B^* \times
\mathsf{Nab}{0}{7} \times \mathsf{Nab}{0}{2^{64}-1}$ is given by

$$\dHead(n \cdot s) =
  \begin{cases}
    (s, \divfn(n,32), \modfn(n,32)) & \text{if $\modfn(n,32) \leq 23$}\\
    (s', \divfn(n,32), k) & \text{if $\modfn(n,32) = 24$ and $\bsToInt_1(s) = (s', k)$}\\
    (s', \divfn(n,32), k) & \text{if $\modfn(n,32) = 25$ and $\bsToInt_2(s) = (s', k)$}\\
    (s', \divfn(n,32), k) & \text{if $\modfn(n,32) = 26$ and $\bsToInt_4(s) = (s', k)$}\\
    (s', \divfn(n,32), k) & \text{if $\modfn(n,32) = 27$ and $\bsToInt_8(s) = (s', k)$}.
  \end{cases}$$

This function is undefined if the input is the empty bytestring $\epsilon$, if the input is too short, or if its initial byte is not of the expected form.

##### Heads for indefinite-length items.

The functions $\eHead$ and $\dHead$ defined above are used for a number of purposes. One use is to encode integers less than 64 bits, where the argument of the head is the relevant integer. Another use is for "definite-length" encodings of items such as bytestrings and lists, where the head contains the length $n$ of the object and is followed by some encoding of the object itself (for example a sequence of $n$ bytes for a bytestring or a sequence of $n$ encoded objects for the elements of a list). It is also possible to have "indefinite-length" encodings of objects such as lists and arrays, which do not specify the length of an object in advance: instead a special head with argument 31 is emitted, followed by the encodings of the individual items; the end of the sequence is marked by a "break" byte with value 255. We define an encoder $\eIndef: \mathsf{Nab}{2}{5} \rightarrow \B^*$ and a decoder $\dIndef: \B^* \rightharpoonup \B^* \times \mathsf{Nab}{2}{5}$ which deal with indefinite heads for a given major type:

$$\begin{align*}
  \eIndef(m) &= [32m+31]\\
  \dIndef(n \cdot s) & = (s, m) \qquad \text{if $n = 32m+31$}.
\end{align*}$$

Note that $\eIndef$ and $\dIndef$ are only defined for $m \in
\{2,3,4,5\}$ (and we shall only use them in these cases). The case $m=31$ corresponds to the break byte and for $m \in \{0,1,6\}$ the value is not well formed: see [@rfc8949-CBOR 3.2.4].

## Encoding and decoding bytestrings

The standard CBOR encoding of bytestrings encodes a bytestring as either a definite-length sequence of bytes (the length being given in the head) or as an indefinite-length sequence of definite-length "chunks" (see [@rfc8949-CBOR §§3.1 and 3.4.2]). We use a similar scheme, but only allow chunks of length up to 64. To this end, suppose that $a = [a_1, \ldots, a_{64k+r}] \in
\B^*\backslash\{\epsilon\}$ where $k \geq 0$ and $0 \leq r \leq 63$. We define the *canonical 64-byte decomposition* $\bar{a}$ of $a$ to be $$\bar{a} = [[a_1, \ldots, a_{64}],
  [a_{65}, \ldots, a_{128}] ,\ldots,
  [a_{64(k-1)+1}, \ldots, a_{64k}]] \in (\B^*)^*$$ if $r=0$ and

$$\bar{a} = [[a_1, \ldots, a_{64}],
  [a_{65}, \ldots, a_{128}], \ldots,
  [a_{64(k-1)+1}, \ldots, a_{64k}], [a_{64k+1}, \ldots, a_{64k+r}]] \in (\B^*)^*$$ if $r>0$. The canonical decomposition of the empty list is $\bar{\epsilon} = []$.

We define the encoder $\eBS: \B^* \rightarrow \B^*$ for bytestrings by encoding bytestrings of size up to 64 using the standard CBOR encoding and encoding larger bytestrings by breaking them up into 64-byte chunks (with the final chunk possibly being less than 64 bytes long) and encoding them as an indefinite-length list (major type 2 indicates a bytestring): $$\eBS(s) =
\begin{cases}
  \eHead(2,\length(s)) \cdot s & \text{if $\length(s) \leq 64$}\\
  \eIndef(2) \cdot \eHead(2,\length(c_1)) \cdot c_1 \cdot \eHead(2,\length(c_2)) \cdot \cdots \\
  \qquad  \cdots  \cdot c_{n-1} \cdot \eHead(2,\length(c_n)) \cdot c_n \cdot 255
  & \text{if $\length(s) > 64$ and $\bar{s} = [c_1, \ldots, c_n]$.}
\end{cases}$$

The decoder is slightly more complicated. Firstly, for every $n \geq
0$ we define a decoder $\dBytes^{(n)}: \B^* \rightharpoonup \B^* \times \B^*$ which extracts an $n$-byte prefix from its input (failing in the case of insufficient input): $$\dBytes^{(n)}(s) =
\begin{cases}
  (s, \epsilon) & \text{if $n=0$}\\
  (s'', b \cdot t) & \text{if $s = b \cdot s'$ and $\dBytes^{(n-1)}(s') = (s'', t)$}.
\end{cases}$$

Secondly, we define a decoder $\dBlock: \B^* \rightharpoonup \B^*
\times \B^*$ which attempts to extract a bytestring of length at most 64 from its input; $\dBlock$ (and any other function which calls it) will fail if it encounters a bytestring which is greater than 64 bytes. $$\dBlock(s) =
  \dBytes^{(n)}(s') \quad \text{if $\dHead(s) = (s', 2,n)$ and $n \leq 64$}.$$

Thirdly, we define a decoder $\dBlocks: \B^* \rightharpoonup \B^*
\times \B^*$ which decodes a sequence of blocks and returns their concatenation. $$\dBlocks(s) =
\begin{cases}
  (s', \epsilon) & \text{if $s = 255 \cdot s'$}\\
  (s'', t \cdot t') &
  \text{if $\dBlock(s) = (s', t)$
    and $\dBlocks(s') = (s'', t')$}.
\end{cases}$$

Finally we define the decoder $\dBS: \B^* \rightharpoonup \B^*
\times \B^*$ for bytestrings by $$\dBS(s) =
\begin{cases}
  (s', t) & \text{if $\dBlock(s) = (s', t)$}\\
  \dBlocks(s') & \text{if $\dIndef(s) = (s', 2)$}.
\end{cases}$$

This looks for either a single block or an indefinite-length list of blocks, in the latter case returning their concatenation. It will accept the output of $\eBS$ but will reject bytestring encodings containing any blocks greater than 64 bytes long, even if they are valid bytestring encodings according to the CBOR specification.

## Encoding and decoding integers

As with bytestrings we use a specialised encoding scheme for integers which prohibits encodings with overly-long sequences of arbitrary data. We encode integers in $\mathsf{Nab}{-2^{64}}{2^{64}-1}$ as normal (see  [@rfc8949-CBOR § 3.1]: the major type is 0 for positive integers and 1 for negative ones) and larger ones by emitting a CBOR tag (major type 6; argument 2 for positive numbers and 3 for negative numbers) to indicate the sign, then converting the integer to a bytestring and emitting that using the encoder defined above. This encoding scheme is the same as the standard one except for the size limitations.

We firstly define conversion functions $\itos : \N \rightarrow
\B^*$ and $\stoi: \B^* \rightarrow \N$ by $$\itos(n) =
\begin{cases}
  \epsilon & \text{if $n=0$}\\
  \itos(\divfn(n,256)) \cdot \modfn(n,256) & \text{if $n>0$.}\\
\end{cases}$$ and $$\stoi(l) =
\begin{cases}
  0 & \text{if $l = \epsilon$}\\
  256\times\stoi(l') + n & \text{if $l=l' \cdot n$ with $n \in \B$.}\\
\end{cases}$$

The encoder $\eZ: \Z \rightarrow \B^*$ for integers is now defined by $$\eZ(n) =
\begin{cases}
  \eHead(0,n)                             & \text{if $0\leq n \leq 2^{64}-1$}\\
  \eHead(6,2) \cdot \eBS(\itos(n))    & \text{if $n \geq 2^{64}$}\\
  \eHead(1,-n-1)                          & \text{if $-2^{64} \leq n \leq -1$}\\
  \eHead(6,3) \cdot \eBS(\itos(-n-1)) & \text{if $n \leq -2^{64}-1$}.
\end{cases}$$

The decoder $\dZ: \B^* \rightharpoonup \B^* \times \Z$ inverts this process. The decoder is in fact slightly more permissive than the encoder because it also accepts small integers encoded using the scheme for larger ones. However, the CBOR standard permits integer encodings which contain bytestrings longer than 64 bytes and it will not accept those. $$\dZ(s) =
\begin{cases}
  (s', n)               & \text{if $\dHead(s) = (s', 0,n)$}\\
  (s', -n-1)            & \text{if $\dHead(s) = (s', 1,n)$}\\
  (s'', \stoi(b))       & \text{if $\dHead(s) = (s', 6,2)$ and $\dBS(s') = (s'', b)$}\\
  (s'', -\stoi(b)-1)    & \text{if $\dHead(s) = (s', 6,3)$ and $\dBS(s') = (s'', b)$}.\\
\end{cases}$$

## Encoding and decoding `data`
It is now quite straightforward to encode most `data` values. The main complication is in the encoding of constructor tags (the number $i$ in $\mathtt{Constr}\: i\, l$).

##### The encoder.

The encoder is given by $$\begin{alignat*}
{2}
&  \e_{\mathtt{data}}(\mathtt{Map}\: l) && = \eHead(5,\length(l)) \cdot \e_{\mathtt{(data^2)^*}}(l)\\
&  \e_{\mathtt{data}}(\mathtt{List}\: l) && = \eIndef(4) \cdot \e_{\mathtt{data^*}}(l) \cdot 255\\
&  \e_{\mathtt{data}}(\mathtt{Constr}\: i\, l) && = \ecTag(i) \cdot \eIndef(4) \cdot  \e_{\mathtt{data^*}}(l) \cdot 255\\
& \e_{\mathtt{data}}(\mathtt{I}\: n) && = \eZ(n)\\
&  \e_{\mathtt{data}}(\mathtt{B}\: s) && = \eBS(s).
\end{alignat*}$$

This definition uses encoders for lists of data items, lists of pairs of data items, and constructor tags as follows: $$\e_{\mathtt{data^*}}([d_1, \ldots, d_n]) = \e_{\mathtt{data}}(d_1) \cdot \cdots \cdot \e_{\mathtt{data}}(d_n)$$ $$\e_{\mathtt{(data^2)^*}}([(k_1,d_1), \ldots, (k_n, d_n)]) = \e_{\mathtt{data}}(k_1) \cdot \e_{\mathtt{data}}(d_1) \cdot \cdots \cdot \e_{\mathtt{data}}(k_n) \cdot \e_{\mathtt{data}}(d_n)$$ $$\ecTag(i) =
\begin{cases}
  \eHead(6,121+i) & \text{if $0 \leq i \leq 6$}\\
  \eHead(6,1280+(i-7)) & \text{if $7 \leq i \leq 127$}\\
  \eHead(6,102) \cdot \eHead(4,2) \cdot \eZ(i) & \text{otherwise}.\\
  \end{cases}$$

In the final case of $\ecTag$ we emit a head with major type 4 and argument 2. This indicates that an encoding of a list of length 2 will follow: the first element of the list is the constructor number and the second is the argument list of the constructor, which is actually encoded in $\e_{\mathtt{data}}$. It might be conceptually more accurate to have a single encoder which would encode both the constructor tag and the argument list, but this would increase the complexity of the notation even further. Similar remarks apply to $\dcTag$ below.

##### The decoder.

The decoder is given by $$\d_{\mathtt{data}}(s) =
\begin{cases}
  (s'', \mathtt{Map}\: l) & \text{if $\dHead(s) = (s', 5, n)$ and $\d_{\mathtt{(data^2)^*}}^{(n)}(s') = (s'', l)$}\\
  (s', \mathtt{List}\: l) & \text{if $\d_{\mathtt{data^*}}(s) = (s', l)$}\\
  (s'', \mathtt{Constr}\: i \, l) & \text{if $\dcTag(s) = (s', i)$ and $\d_{\mathtt{data^*}}(s') = (s'', l)$}\\
  (s', \mathtt{I}\: n) & \text{if $\dZ(s) = (s', n)$}\\
  (s', \mathtt{B}\: b) & \text{if $\dBS(s) = (s', b)$}
\end{cases}$$ where $$\d_{\mathtt{data^*}}(s) =
\begin{cases}
  \d_{\mathtt{data^*}}^{(n)}(s') & \text{if $\dHead(s) = (s', 4, n)$}\\
  \d_{\mathtt{data^*}}^{\mathsf{indef}}(s') & \text{if $\dIndef(s) = (s', 4)$}
\end{cases}$$

$$\d_{\mathtt{data^*}}^{(n)}(s) =
\begin{cases}
  (s, \epsilon) & \text{if $n = 0$}\\
  (s'', d \cdot l) & \text{if $\d_{\mathtt{data}}(s) = (s', d)$ and $\d_{\mathtt{data^*}}^{(n-1)}(s') = (s'', l)$}\\
\end{cases}$$

$$\d_{\mathtt{data^*}}^{\mathsf{indef}}(s) =
\begin{cases}
  (s', \epsilon) & \text{if $s = 255 \cdot s' $}\\
  (s'', d \cdot l) & \text{if $\d_{\mathtt{data}}(s) = (s', d)$ and $\d_{\mathtt{data^*}}^{\mathsf{indef}}(s') = (s'', l)$}\\
\end{cases}$$

$$\d_{\mathtt{(data^2)^*}}^{(n)}(s) =
\begin{cases}
  (s, \epsilon) & \text{if $n=0$}\\
  (s''', (k,d) \cdot l) &
  \begin{cases}
    \text{if $n > 0$}\\
    \text{and $\d_{\mathtt{data}}(s) = (s', k)$}\\
    \text{and $\d_{\mathtt{data}}(s') = (s'', d)$}\\
    \text{and $\d_{\mathtt{(data^2)^*}}^{(n-1)}(s'') = (s''', l)$}
  \end{cases}
\end{cases}$$

$$\dcTag(s) =
\begin{cases}
  (s', i-121) & \text{if $\dHead(s) = (s', 6, i)$ and $121 \leq i \leq 127$}\\
  (s', (i-1280)+7) & \text{if $\dHead(s) = (s', 6, i)$ and $1280 \leq i \leq 1400$}\\
  (s''', i) &
  \begin{cases}
    \text{if $\dHead(s) = (s', 6, 102)$}\\
    \text{and $\dHead(s') = (s'', 4, 2)$}\\
    \text{and $\dZ(s'') = (s''', i)$}\\
    \text{and $0 \leq i \leq 2^{64}-1$}.
    \end{cases}\\
  \end{cases}$$

Note that the decoders for `List` and `Constr` accept both definite-length and indefinite-length lists of encoded `data` values, but the decoder for `Map` only accepts definite-length lists (and the length is the number of *pairs* in the map). This is consistent with CBOR's standard encoding of arrays and lists (major type 4) and maps (major type 5).

Note also that the encoder $\ecTag$ accepts arbitrary integer values for `Constr` tags, but (for compatibility with [@CBOR-alternatives]) the decoder $\dcTag$ only accepts tags in $\mathsf{Nab}{0}{2^{64}-1}$. This means that some valid Plutus Core programs can be serialised but not deserialised, and is the reason for the recommendation in Section sec:built-in-types-1 that only constructor tags between 0 and $2^{64}-1$ should be used.
