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
    const naturalWidth = Number(image.naturalWidth || image.width || 0);
    const naturalHeight = Number(image.naturalHeight || image.height || 0);
    return { source, complete, ready: complete && naturalWidth > 0 && naturalHeight > 0, naturalWidth, naturalHeight };
  }
  function getArtifacts(messageNode) {
    if (!messageNode?.querySelectorAll) return [];
    const role = messageNode.getAttribute?.("data-message-author-role");
    if (role && role !== "assistant") return [];
    const result = []; let index = 0;
    for (const image of messageNode.querySelectorAll("img")) {
      const state = isArtifactImage(image); if (!state) continue;
      const source = imageSource(image);
      const id = `img_${stableHash(`${profile.id}:${root.location?.pathname || ""}:${turnId(messageNode)}:${index}`)}_${index}`;
      result.push({ id, kind: "image", provider: profile.id, turn_id: turnId(messageNode), index, mime_type: attr(image, ["data-mime-type", "type"]) || null, width: state.naturalWidth || null, height: state.naturalHeight || null, alt: image.getAttribute?.("alt") || "", quality: source.quality, ready: state.ready, complete: state.complete, naturalWidth: state.naturalWidth, naturalHeight: state.naturalHeight, source_identity: source.source, _source: source.source, _source_kind: sourceKind(source.source) });
      index += 1;
    }
    return result;
  }
  function resolveArtifact(ref) {
    const artifactId = String(ref?.artifact_id || ""); const turn = String(ref?.turn_id || ""); const index = Number(ref?.index);
    for (const node of document.querySelectorAll(selectors.assistant)) {
      if (turnId(node) !== turn) continue;
      const artifacts = getArtifacts(node); if (artifacts[index] && (!artifactId || artifacts[index].id === artifactId)) return artifacts[index];
    }
    throw bridge.error("ARTIFACT_NOT_FOUND", "页面中未找到指定 Artifact", true);
  }
  function debugArtifact(item) {
    const source = typeof item?.source_identity === "string" ? item.source_identity : "";
    return {
      id: item?.id || "",
      kind: item?.kind || "image",
      index: Number.isInteger(item?.index) ? item.index : null,
      quality: item?.quality || "unknown",
      mime_type: item?.mime_type || null,
      width: item?.width ?? null,
      height: item?.height ?? null,
      complete: item?.complete === true,
      natural_width: Number(item?.naturalWidth || 0),
      natural_height: Number(item?.naturalHeight || 0),
      ready: item?.ready === true,
      source_kind: item?._source_kind || sourceKind(source) || null,
      source_available: Boolean(source),
      source_hash: source ? stableHash(source) : null,
    };
  }
  function debugSnapshot(revision) {
    const prompt = findVisible(selectors.prompt);
    const assistant = bridge.ChatGPTAdapter.getLastAssistant();
    const text = bridge.normalizeText(assistant?.innerText || assistant?.textContent || "");
    const artifacts = assistant ? getArtifacts(assistant) : [];
    const origin = root.location?.origin || "";
    const pathname = root.location?.pathname || "/";
    return {
      page: { origin, pathname },
      prompt: {
        present: Boolean(prompt),
        visible: Boolean(prompt && visible(prompt)),
        text_length: String(prompt?.value ?? prompt?.innerText ?? "").length,
      },
      counts: {
        users: bridge.ChatGPTAdapter.getUsers().length,
        assistants: document.querySelectorAll(selectors.assistant).length,
        messages: bridge.ChatGPTAdapter.getMessages().length,
      },
      assistant: assistant ? {
        present: true,
        turn_id: turnId(assistant),
        text_length: text.length,
        text_hash: stableHash(text),
        completion_marker: bridge.ChatGPTAdapter.hasCompletionMarker(assistant),
      } : { present: false },
      generating: bridge.ChatGPTAdapter.isGenerating(),
      revision: Number.isInteger(revision) ? revision : 0,
      artifacts: artifacts.map(debugArtifact),
      artifact_signature: JSON.stringify(artifacts.map((item) => [item.id, item.index, item.width, item.height, item.complete, item.naturalWidth, item.naturalHeight, item.ready, item._source_kind || sourceKind(item.source_identity || "")])),
    };
  }
  bridge.ChatGPTAdapter = {
    selectors,
    serializer: bridge.ChatGPTSerializer,
    findPrompt: () => findVisible(selectors.prompt),
    findSendButton: () => findVisible(selectors.send),
    isGenerating: () => Boolean(findVisible(selectors.stop)),
    isEnabled: (button) => !button.disabled && button.getAttribute("aria-disabled") !== "true" && !button.hasAttribute("disabled"),
    getMessages: () => document.querySelectorAll(selectors.message),
    getUsers: () => document.querySelectorAll(selectors.user),
    getLastAssistant: () => { const nodes = document.querySelectorAll(selectors.assistant); return nodes.length ? nodes[nodes.length - 1] : null; },
    getRole: (node) => node.getAttribute("data-message-author-role"),
    findTurnContainer: (node) => node.closest("[data-turn-id]") || node.closest('[data-testid^="conversation-turn-"]') || node.closest("[data-turn]") || node,
    turnAttributes: ["data-turn-id", "data-testid", "data-turn"],
    getArtifacts,
    resolveArtifact,
    debugSnapshot,
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
