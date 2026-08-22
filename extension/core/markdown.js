(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  function clean(value) {
    return String(value || "").replace(/\u00a0/g, " ").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }
  function children(element, provider) {
    return [...(element.childNodes || [])].map((node) => nodeToMarkdown(node, provider)).join("");
  }
  function nodeToMarkdown(node, provider) {
    if (node.nodeType === 3) return node.nodeValue || "";
    if (node.nodeType !== 1) return "";
    const special = provider.serializeElement && provider.serializeElement(node);
    if (special !== undefined) return special;
    const tag = node.tagName.toLowerCase();
    if (["script", "style", "noscript"].includes(tag) || node.getAttribute("aria-hidden") === "true") return "";
    if (tag === "br") return "\n";
    if (tag === "hr") return "\n---\n";
    if (tag === "pre") return `\n\`\`\`\n${(node.innerText || node.textContent || "").replace(/\n+$/, "")}\n\`\`\`\n`;
    if (tag === "code") return `\`${(node.innerText || node.textContent || "").trim()}\``;
    if (tag === "a") { const text = children(node, provider).trim(); const href = node.getAttribute("href"); return href ? `[${text || href}](${href})` : text; }
    if (["strong", "b"].includes(tag)) return `**${children(node, provider).trim()}**`;
    if (["em", "i"].includes(tag)) return `*${children(node, provider).trim()}*`;
    if (/^h[1-6]$/.test(tag)) return `\n${"#".repeat(Number(tag[1]))} ${children(node, provider).trim()}\n`;
    if (tag === "blockquote") return `\n${clean(children(node, provider)).split("\n").map((line) => `> ${line}`).join("\n")}\n`;
    if (tag === "ul" || tag === "ol") return `\n${[...node.children].filter((item) => item.tagName?.toLowerCase() === "li").map((item, index) => `${tag === "ol" ? `${index + 1}.` : "-"} ${children(item, provider).trim()}`).join("\n")}\n`;
    if (tag === "table") {
      const rows = [...node.querySelectorAll("tr")].map((row) => [...row.querySelectorAll("th, td")].map((cell) => bridge.normalizeText(children(cell, provider)).replace(/\|/g, "\\|"))).filter((row) => row.length);
      if (!rows.length) return "";
      const width = Math.max(...rows.map((row) => row.length)); const pad = (row) => Array.from({ length: width }, (_, index) => row[index] || "");
      return `\n| ${pad(rows[0]).join(" | ")} |\n| ${Array.from({ length: width }, () => "---").join(" | ")} |\n${rows.slice(1).map((row) => `| ${pad(row).join(" | ")} |`).join("\n")}\n`;
    }
    const result = children(node, provider);
    return ["p", "div", "section", "article", "li"].includes(tag) ? `\n${result}\n` : result;
  }
  bridge.serializeMessageToMarkdown = function serializeMessageToMarkdown(node, provider) {
    return clean(nodeToMarkdown(node, provider)) || clean(node?.innerText || "");
  };
})(globalThis);
