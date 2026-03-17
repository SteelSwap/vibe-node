/**
 * MathJax configuration for Cardano formal spec rendering.
 *
 * Defines custom LaTeX macros used throughout the Cardano ledger,
 * consensus, and networking specifications. These macros are defined
 * in the original LaTeX sources (small-step-semantics.tex, ledger-spec.tex)
 * and must be available for MathJax to render the converted specs correctly.
 */
window.MathJax = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
    processEscapes: true,
    processEnvironments: true,
    macros: {
      // === Base macros (from small-step-semantics.tex) ===
      fun: ["\\mathsf{#1}", 1],
      var: ["\\mathit{#1}", 1],
      type: ["\\mathsf{#1}", 1],
      powerset: ["\\mathbb{P}~#1", 1],
      restrictdom: "\\lhd",
      subtractdom: "\\unlhd",
      restrictrange: "\\rhd",
      wcard: "\\underline{\\phantom{a}}",
      dom: ["\\mathop{\\mathrm{dom}}~#1", 1],
      range: ["\\mathop{\\mathrm{range}}~#1", 1],

      // === Cardano types (from ledger-spec.tex) ===
      Tx: "\\mathsf{Tx}",
      TxBody: "\\mathsf{TxBody}",
      TxId: "\\mathsf{TxId}",
      TxIn: "\\mathsf{TxIn}",
      TxOut: "\\mathsf{TxOut}",
      UTxO: "\\mathsf{UTxO}",
      UTxOEnv: "\\mathsf{UTxOEnv}",
      UTxOState: "\\mathsf{UTxOState}",
      Addr: "\\mathsf{Addr}",
      Coin: "\\mathsf{Coin}",
      Lovelace: "\\mathsf{Lovelace}",
      Slot: "\\mathsf{Slot}",
      SlotNo: "\\mathsf{SlotNo}",
      Epoch: "\\mathsf{Epoch}",
      Ix: "\\mathsf{Ix}",
      VKey: "\\mathsf{VKey}",
      VKeyGen: "\\mathsf{VKey_{genesis}}",
      SKey: "\\mathsf{SKey}",
      Sig: "\\mathsf{Sig}",
      Proof: "\\mathsf{Proof}",
      Seed: "\\mathsf{Seed}",
      Nonce: "\\mathsf{Nonce}",
      HashHeader: "\\mathsf{HashHeader}",
      HashBBody: "\\mathsf{HashBBody}",
      HashScr: "\\mathsf{Hash_{Script}}",
      KeyHash: "\\mathsf{KeyHash}",
      KeyHashGen: "\\mathsf{KeyHash_{genesis}}",
      ScriptHash: "\\mathsf{ScriptHash}",
      Credential: "\\mathsf{Credential}",
      DCert: "\\mathsf{DCert}",
      DCertRegKey: "\\mathsf{DCert_{regkey}}",
      DCertDeRegKey: "\\mathsf{DCert_{deregkey}}",
      DCertDeleg: "\\mathsf{DCert_{deleg}}",
      DCertRegPool: "\\mathsf{DCert_{regpool}}",
      DCertRetirePool: "\\mathsf{DCert_{retirepool}}",
      DCertMir: "\\mathsf{DCert_{mir}}",
      PoolParam: "\\mathsf{PoolParam}",
      PParams: "\\mathsf{PParams}",
      Update: "\\mathsf{Update}",
      GenesisDelegation: "\\mathsf{GenesisDelegation}",

      // === Cardano functions (from ledger-spec.tex) ===
      txins: ["\\mathsf{txins}~\\mathit{#1}", 1],
      txouts: ["\\mathsf{txouts}~\\mathit{#1}", 1],
      txcerts: ["\\mathsf{txcerts}~\\mathit{#1}", 1],
      txwdrls: ["\\mathsf{txwdrls}~\\mathit{#1}", 1],
      txid: ["\\mathsf{txid}~\\mathit{#1}", 1],
      txbody: ["\\mathsf{txbody}~\\mathit{#1}", 1],
      balance: ["\\mathsf{balance}~\\mathit{#1}", 1],
      txinsVKey: ["\\mathsf{txinsVKey}~\\mathit{#1}", 1],
      txinsScript: ["\\mathsf{txinsScript}~\\mathit{#1}", 1],
      paymentHK: ["\\mathsf{paymentHK}~\\mathit{#1}", 1],
      validatorHash: ["\\mathsf{validatorHash}~\\mathit{#1}", 1],
      stakeCredr: ["\\mathsf{stakeCred_r}~\\mathit{#1}", 1],

      // === Transition system notation ===
      trans: ["\\xrightarrow[\\mathsf{#1}]{}", 1],
      vdash: "\\vdash",

      // === Address types ===
      AddrRWDVKey: "\\mathsf{Addr_{rwd}^{vkey}}",
      AddrRWDScr: "\\mathsf{Addr_{rwd}^{script}}",
      AddrScr: "\\mathsf{Addr^{script}}",
      AddrVKey: "\\mathsf{Addr^{vkey}}",

      // === Witness functions ===
      cwitness: ["\\mathsf{cwitness}~\\mathit{#1}", 1],

      // === Misc ===
      txup: ["\\mathsf{txup}~\\mathit{#1}", 1],
    }
  },
  options: {
    ignoreHtmlClass: ".*|",
    processHtmlClass: "arithmatex"
  }
};

document$.subscribe(() => {
  MathJax.startup.output.clearCache();
  MathJax.typesetClear();
  MathJax.texReset();
  MathJax.typesetPromise();
});
