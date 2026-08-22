(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  const profile = bridge.ChatGPTProfile;
  const selectors = profile.selectors;
  function visible(element) { if (!element) return false; const style = root.getComputedStyle(element); return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0; }
  function findVisible(list) { for (const selector of list) { const element = document.querySelector(selector); if (visible(element)) return element; } return null; }
  function matches(node, list) { return Boolean(node && node.nodeType === Node.ELEMENT_NODE && list.some((selector) => { try { return node.matches(selector); } catch (_error) { return false; } })); }
  function activitySelectors() { return ["main", '[role="main"]', selectors.message, ...selectors.tool, ...selectors.status]; }
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
