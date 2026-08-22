(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  bridge.ChatGPTSerializer = {
    serializeElement(element) {
      const tag = element.tagName.toLowerCase();
      if (tag === "math" || element.classList.contains("katex")) {
        const tex = (element.querySelector('annotation[encoding="application/x-tex"]')?.textContent || "").trim();
        if (!tex) return "";
        const display = element.matches('.katex-display, [display="block"], [display="true"]') || Boolean(element.closest('.katex-display, [display="block"], [display="true"]'));
        return display ? `\n$$\n${tex}\n$$\n` : `$${tex}$`;
      }
      if (element.classList.contains("katex-html") || element.classList.contains("katex-mathml") || element.classList.contains("MathJax")) return "";
      return undefined;
    },
  };
})(globalThis);
