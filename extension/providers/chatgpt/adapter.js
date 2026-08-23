(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  const profile = bridge.ChatGPTProfile;
  const selectors = profile.selectors;
  function visible(element) { if (!element) return false; const style = root.getComputedStyle(element); return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0; }
  function findVisible(list) { for (const selector of list) { const element = document.querySelector(selector); if (visible(element)) return element; } return null; }
  function matches(node, list) { return Boolean(node && node.nodeType === Node.ELEMENT_NODE && list.some((selector) => { try { return node.matches(selector); } catch (_error) { return false; } })); }
  function activitySelectors() { return ["main", '[role="main"]', selectors.message, ...selectors.tool, ...selectors.status]; }
  function stableHash(value) {
    let hash = 2166136261;
    for (const char of String(value)) { hash ^= char.charCodeAt(0); hash = Math.imul(hash, 16777619); }
    return (hash >>> 0).toString(16).padStart(8, "0");
  }
  function turnId(node) {
    const container = bridge.ChatGPTAdapter.findTurnContainer(node);
    for (const attribute of bridge.ChatGPTAdapter.turnAttributes) { const value = container?.getAttribute?.(attribute); if (value) return value; }
    return `node-${stableHash(container?.innerText || "")}`;
  }
  function sourceKind(source) { try { return new URL(source, root.location?.href || undefined).protocol.replace(":", ""); } catch (_error) { return ""; } }
  function absoluteSource(source) { try { return new URL(source, root.location?.href || undefined).href; } catch (_error) { return source; } }
  function candidateFromSrcset(value) {
    if (typeof value !== "string") return null;
    const candidates = value.split(",").map((item) => {
      const parts = item.trim().split(/\s+/); const descriptor = parts[1] || "";
      const numeric = Number.parseFloat(descriptor); const density = descriptor.endsWith("x");
      return { source: parts[0], density, score: Number.isFinite(numeric) ? numeric : 0 };
    }).filter((item) => item.source);
    const preferred = candidates.some((item) => item.density) ? candidates.filter((item) => item.density) : candidates;
    preferred.sort((left, right) => right.score - left.score);
    return preferred[0]?.source || null;
  }
  function attr(element, names) { for (const name of names) { const value = element?.getAttribute?.(name); if (value) return value; } return ""; }
  function imageSource(image) {
    const original = attr(image, ["data-original", "data-original-src", "data-full-size", "data-download-url"]);
    if (original) return { source: absoluteSource(original), quality: "original" };
    const anchor = image.closest?.("a");
    const href = anchor?.getAttribute?.("href") || "";
    if (href && /^(https?:|data:|blob:|\/)/i.test(href)) return { source: absoluteSource(href), quality: "original" };
    const srcset = candidateFromSrcset(image.getAttribute?.("srcset"));
    if (srcset) return { source: absoluteSource(srcset), quality: "display" };
    const current = image.currentSrc || "";
    if (current) return { source: absoluteSource(current), quality: "unknown" };
    const src = image.getAttribute?.("src") || "";
    if (src) return { source: absoluteSource(src), quality: "unknown" };
    return { source: "", quality: "unknown" };
  }
  function isArtifactImage(image) {
    if (!image || image.tagName?.toLowerCase() !== "img") return false;
    const values = [image.getAttribute?.("alt"), image.getAttribute?.("aria-label"), image.getAttribute?.("class"), image.getAttribute?.("data-testid"), image.closest?.("[aria-hidden='true']") && "hidden"].filter(Boolean).join(" ").toLowerCase();
    if (/(avatar|favicon|icon|toolbar|logo|loading|placeholder|spinner|thumbnail|工具|头像|图标)/i.test(values)) return false;
    const source = imageSource(image).source;
    if (!source || !/^(https?:|data:|blob:)/i.test(source)) return false;
    if (/(avatar|favicon|icon|loading|placeholder|spinner|thumbnail)/i.test(source)) return false;
    const complete = image.complete !== false;
    const width = Number(image.naturalWidth || image.width || 0);
    const height = Number(image.naturalHeight || image.height || 0);
    return { source, ready: complete && width > 0 && height > 0, width, height };
  }
  function imageNodesFor(messageNode) {
    if (!messageNode?.querySelectorAll) return [];
    const roots = [messageNode];
    const container = bridge.ChatGPTAdapter?.findTurnContainer?.(messageNode);
    if (container && container !== messageNode) roots.push(container);
    const nodes = []; const seen = new Set();
    for (const rootNode of roots) for (const image of rootNode.querySelectorAll("img")) if (!seen.has(image)) { seen.add(image); nodes.push(image); }
    return nodes;
  }
  function isGeneratedImage(image) {
    const state = isArtifactImage(image);
    if (!state) return false;
    const alt = String(image.getAttribute?.("alt") || "");
    return /已生成图片|generated\s+(?:image|picture)/i.test(alt) || /\/backend-api\/estuary\/content(?:[/?]|$)/i.test(state.source);
  }
  function visualTurnNodes() {
    if (!document.querySelectorAll) return [];
    const roots = document.querySelectorAll('[data-turn-id], [data-testid^="conversation-turn-"], [data-turn]');
    return [...roots].filter((node) => node.getAttribute?.("data-message-author-role") !== "user" && imageNodesFor(node).some(isGeneratedImage));
  }
  function documentOrder(nodes) {
    return [...nodes].sort((left, right) => {
      if (left === right || !left?.compareDocumentPosition) return 0;
      const relation = left.compareDocumentPosition(right);
      if (relation & (root.Node?.DOCUMENT_POSITION_FOLLOWING || 4)) return -1;
      if (relation & (root.Node?.DOCUMENT_POSITION_PRECEDING || 2)) return 1;
      return 0;
    });
  }
  function assistantNodes() {
    const roleNodes = document.querySelectorAll(selectors.assistant) ? [...document.querySelectorAll(selectors.assistant)] : [];
    const candidates = documentOrder([...roleNodes, ...visualTurnNodes()]);
    const result = []; const seen = new Set();
    for (const node of candidates) {
      const container = bridge.ChatGPTAdapter.findTurnContainer(node);
      if (seen.has(container)) continue;
      seen.add(container); result.push(node);
    }
    return result;
  }
  function getArtifacts(messageNode) {
    if (!messageNode?.querySelectorAll) return [];
    const role = messageNode.getAttribute?.("data-message-author-role");
    if (role && role !== "assistant") return [];
    const result = []; const seenSources = new Set(); let index = 0;
    for (const image of imageNodesFor(messageNode)) {
      const state = isArtifactImage(image); if (!state) continue;
      const source = imageSource(image);
      if (source.source && seenSources.has(source.source)) continue;
      if (source.source) seenSources.add(source.source);
      result.push({ kind: "image", turn_id: turnId(messageNode), index, mime_type: attr(image, ["data-mime-type", "type"]) || null, width: state.width || null, height: state.height || null, alt: image.getAttribute?.("alt") || "", quality: source.quality, ready: state.ready, _source: source.source, _source_kind: sourceKind(source.source) });
      index += 1;
    }
    return result;
  }
  function resolveArtifact(ref) {
    const turn = String(ref?.turn_id || ""); const index = Number(ref?.index);
    if (!turn || !Number.isInteger(index) || index < 0) throw bridge.error("ARTIFACT_NOT_FOUND", "页面中未找到指定 Artifact", true);
    for (const node of assistantNodes()) {
      if (turnId(node) !== turn) continue;
      const artifacts = getArtifacts(node); if (artifacts[index]) return artifacts[index];
    }
    throw bridge.error("ARTIFACT_NOT_FOUND", "页面中未找到指定 Artifact", true);
  }
  bridge.ChatGPTAdapter = {
    selectors,
    serializer: bridge.ChatGPTSerializer,
    findPrompt: () => findVisible(selectors.prompt),
    findSendButton: () => findVisible(selectors.send),
    isGenerating: () => Boolean(findVisible(selectors.stop)),
    isEnabled: (button) => !button.disabled && button.getAttribute("aria-disabled") !== "true" && !button.hasAttribute("disabled"),
    getMessages: () => {
      const users = [...document.querySelectorAll(selectors.user)];
      return documentOrder([...users, ...assistantNodes()]);
    },
    getUsers: () => document.querySelectorAll(selectors.user),
    getLastAssistant: () => { const nodes = assistantNodes(); return nodes.length ? nodes[nodes.length - 1] : null; },
    getRole: (node) => { const role = node.getAttribute("data-message-author-role"); return role || (getArtifacts(node).length ? "assistant" : null); },
    findTurnContainer: (node) => node.closest("[data-turn-id]") || node.closest('[data-testid^="conversation-turn-"]') || node.closest("[data-turn]") || node,
    turnAttributes: ["data-turn-id", "data-testid", "data-turn"],
    getArtifacts,
    resolveArtifact,
    hasCompletionMarker(node) { return [node, node?.parentElement].filter(Boolean).some((candidate) => selectors.completion.some((selector) => { try { return Boolean(candidate.matches?.(selector) || candidate.querySelector(selector)); } catch (_error) { return false; } })); },
    isActivityNode(node) { const all = activitySelectors(); return matches(node, all) || all.some((selector) => { try { return Boolean(node?.closest(selector)); } catch (_error) { return false; } }); },
    isActivitySubtree(node) { return this.isActivityNode(node) || [...activitySelectors()].some((selector) => { try { return Boolean(node?.querySelector(selector)); } catch (_error) { return false; } }); },
    activitySnapshot() {
      const nodes = new Set(); for (const selector of [...selectors.tool, ...selectors.status]) { try { for (const node of document.querySelectorAll(selector)) nodes.add(node); } catch (_error) {} }
      const text = (node) => bridge.normalizeText(node?.innerText || node?.textContent || "");
      const signature = [...nodes].map((node) => [node.tagName, "data-testid", "data-status", "data-state", "aria-label", "aria-live", "aria-busy"].map((key) => key === node.tagName ? key : `${key}=${node.getAttribute(key) || ""}`).join("|") + `|${text(node)}|${node.childElementCount}`).sort().join("\n");
      const pattern = /(tool|function|browser|search|code|reasoning|analysis|analyzing|executing|running|working|loading|调用工具|工具调用|搜索|浏览|代码执行|正在思考|思考中|分析中|工作中|运行中|加载中)/i;
      const toolCall = [...nodes].some((node) => matches(node, selectors.tool) || (matches(node, selectors.status) && pattern.test(`${node.getAttribute("aria-label") || ""} ${node.getAttribute("data-status") || ""} ${text(node)}`)));
      return { signature, toolCall };
    },
  };
  bridge.registerProvider({ ...bridge.ChatGPTProfile, adapter: bridge.ChatGPTAdapter });
})(globalThis);
