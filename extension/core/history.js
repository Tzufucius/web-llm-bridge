(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  bridge.createHistory = function createHistory(provider, timing) {
    const cache = new Map(); const fallbackIds = new WeakMap(); let sequence = 0; let order = []; let pending = null; let active = false; let location = null;
    function reset() { const current = `${root.location?.origin || ""}${root.location?.pathname || ""}`; if (location !== null && location !== current) { cache.clear(); order = []; } location = current; }
    function idFor(node, occurrences) {
      const container = provider.adapter.findTurnContainer(node);
      let base = "";
      for (const attribute of provider.adapter.turnAttributes) {
        const value = container.getAttribute(attribute);
        if (value) { base = `${attribute}:${value}`; break; }
      }
      if (!base) {
        if (!fallbackIds.has(container)) fallbackIds.set(container, `node:${++sequence}`);
        base = fallbackIds.get(container);
      }
      // ChatGPT occasionally renders more than one role node inside one turn
      // container. Never let a duplicate identity overwrite another message.
      const occurrence = (occurrences.get(base) || 0) + 1;
      occurrences.set(base, occurrence);
      return occurrence === 1 ? base : `${base}#${occurrence}`;
    }
    function capture({ prepend = false } = {}) { reset(); const records = []; const occurrences = new Map(); for (const node of provider.adapter.getMessages()) { const role = provider.adapter.getRole(node); if (role !== "user" && role !== "assistant") continue; const content = bridge.serializeMessageToMarkdown(node, provider.adapter.serializer); const artifacts = role === "assistant" && provider.adapter.getArtifacts ? provider.adapter.getArtifacts(node) : []; if (content || artifacts.length) records.push({ id: idFor(node, occurrences), role, content, artifacts, artifactSignature: JSON.stringify(artifacts.map((item) => [item.id, item.source_identity, item.width, item.height, item.complete, item.naturalWidth, item.naturalHeight, item.ready])) }); }
      const added = []; for (const record of records) { const old = cache.get(record.id); if (!old) { cache.set(record.id, record); added.push(record.id); } else if (record.content !== old.content || record.artifactSignature !== old.artifactSignature) { cache.set(record.id, record); added.push(record.id); } } const unique = added.filter((id) => !order.includes(id)); order = prepend ? [...unique, ...order] : [...order, ...unique]; return { newCount: added.length, total: order.length }; }
    function messages() { return order.map((id) => cache.get(id)).filter(Boolean).map(({ role, content, artifacts }) => ({ role, content, artifacts: artifacts || [] })); }
    function container() { let current = document.querySelector(provider.adapter.selectors.message); while (current && current !== document.body) { const style = root.getComputedStyle(current); if (["auto", "scroll"].includes(style.overflowY) && current.scrollHeight > current.clientHeight + 1) return current; current = current.parentElement; } return document.scrollingElement || document.documentElement; }
    function top(node) { return node === document.scrollingElement ? root.scrollY : node.scrollTop; } function max(node) { return Math.max(0, node.scrollHeight - node.clientHeight); } function set(node, value) { if (node === document.scrollingElement) root.scrollTo(0, value); else node.scrollTop = value; }
    async function collect(options = {}) { if (pending) return pending; pending = (async () => { const full = options.full === true; const limit = options.limit == null ? null : Number(options.limit); if (!full && limit !== null && (!Number.isInteger(limit) || limit < 1 || limit > 1000)) throw bridge.error("INPUT_FAILED", "历史消息数量必须是 1 到 1000 的正整数"); const scroll = container(); const original = top(scroll); const nearBottom = max(scroll) - original <= scroll.clientHeight * 1.5; const deadline = root.performance.now() + timing.historyLoadTimeoutMs; let emptyRounds = 0; active = true; try { capture(); while (root.performance.now() < deadline) { if (!full && (limit === null || messages().length >= limit)) break; if (top(scroll) <= 1 && emptyRounds >= 3) break; const before = order.length; set(scroll, Math.max(0, top(scroll) - Math.max(80, Math.floor(scroll.clientHeight * .75)))); await bridge.sleep(timing.historyPollIntervalMs); const result = capture({ prepend: true }); emptyRounds = result.newCount === 0 && top(scroll) <= 1 ? emptyRounds + 1 : (result.newCount > 0 || order.length > before ? 0 : Math.max(0, emptyRounds - 1)); } const result = messages(); return { messages: full || limit === null ? result : result.slice(-limit), truncated: root.performance.now() >= deadline }; } finally { active = false; set(scroll, nearBottom ? max(scroll) : Math.min(original, max(scroll))); } })().finally(() => { pending = null; }); return pending; }
    return { capture, collect, get active() { return active; } };
  };
})(globalThis);
