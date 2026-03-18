/**
 * MathJax configuration for Cardano formal spec rendering.
 *
 * Custom LaTeX macros are pre-expanded in the markdown source files
 * (by the export_specs pipeline). This config only needs standard
 * MathJax setup for pymdownx.arithmatex.
 */
window.MathJax = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
    processEscapes: true,
    processEnvironments: true,
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
