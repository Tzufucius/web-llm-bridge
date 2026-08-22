(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  bridge.createContentRuntime = function createContentRuntime(providerId) {
    const provider = bridge.getProvider(providerId);
    if (!provider) throw new Error(`未注册 Provider：${providerId}`);
    const timing = { ...(provider.timing || {}), ...(bridge.timing || {}) };
    const adapter = provider.adapter;
    const history = bridge.createHistory(provider, timing);
    let revision = 0; let scheduled = false;
    function promptText(prompt) { return typeof prompt?.value === "string" ? prompt.value : prompt?.innerText || ""; }
    function input(prompt, text) { prompt.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text })); }
    function write(prompt, text) {
      if (prompt.isContentEditable) {
        prompt.focus(); const range = document.createRange(); range.selectNodeContents(prompt); const selection = root.getSelection(); selection.removeAllRanges(); selection.addRange(range);
        if (!document.execCommand("delete", false)) { range.deleteContents(); input(prompt, ""); }
        if (!document.execCommand("insertText", false, text)) { range.selectNodeContents(prompt); range.deleteContents(); range.insertNode(document.createTextNode(text)); input(prompt, text); }
      } else if ("value" in prompt) { const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(prompt), "value"); if (descriptor?.set) descriptor.set.call(prompt, ""); else prompt.value = ""; if (descriptor?.set) descriptor.set.call(prompt, text); else prompt.value = text; input(prompt, text); }
      else throw bridge.error("INPUT_FAILED", "输入框不支持文本写入");
      if (bridge.normalizeText(promptText(prompt)) !== bridge.normalizeText(text)) throw bridge.error("INPUT_FAILED", "文本未成功写入输入框");
    }
    async function waitFor(find, code, message, timeout) { const deadline = root.performance.now() + timeout; while (root.performance.now() < deadline) { const value = find(); if (value) return value; await bridge.sleep(timing.pollIntervalMs); } throw bridge.error(code, message); }
    async function sendText(text) {
      if (adapter.isGenerating()) throw bridge.error("BUSY", "页面当前仍在生成回复");
      const deadline = root.performance.now() + timing.pageReadyTimeoutMs; let lastError;
      while (root.performance.now() < deadline) { try { const remaining = Math.max(1, deadline - root.performance.now()); const prompt = await waitFor(adapter.findPrompt, "PROMPT_NOT_FOUND", "页面仍在加载，输入框尚未就绪", remaining); write(prompt, text); const button = await waitFor(() => { const candidate = adapter.findSendButton(); return candidate && adapter.isEnabled(candidate) ? candidate : null; }, "SEND_BUTTON_NOT_FOUND", "发送按钮不可用或页面结构发生变化", Math.min(remaining, timing.buttonReadyTimeoutMs)); button.click(); return; } catch (error) { lastError = error; if (!["PROMPT_NOT_FOUND", "SEND_BUTTON_NOT_FOUND", "INPUT_FAILED"].includes(error?.code)) throw error; await bridge.sleep(timing.pollIntervalMs); } }
      throw bridge.error("PAGE_NOT_READY", lastError ? "页面在限定时间内未完成加载，输入框或发送按钮仍不可用" : "页面在限定时间内未完成加载");
    }
    function progress(requestId, phase, startedAt, activityAt) { if (typeof requestId !== "string" || !requestId) return; const now = root.performance.now(); try { const result = chrome.runtime.sendMessage({ type: "chat_progress", request_id: requestId, phase, elapsed_ms: Math.max(0, Math.round(now - startedAt)), idle_ms: Math.max(0, Math.round(now - activityAt)) }); result?.catch?.(() => {}); } catch (_error) {} }
    async function waitForSubmitted(beforeUsers, text, baseline, requestId, startedAt) {
      const deadline = root.performance.now() + timing.submissionConfirmationTimeoutMs; let lastRevision = revision; let lastProgress = startedAt; let lastActivity = startedAt; progress(requestId, "working", startedAt, lastActivity);
      while (root.performance.now() < deadline) { if (adapter.getUsers().length > beforeUsers) return; const prompt = adapter.findPrompt(); if ((prompt && bridge.normalizeText(promptText(prompt)) === "") || adapter.isGenerating() || (adapter.getLastAssistant() && adapter.getLastAssistant() !== baseline)) return; const now = root.performance.now(); if (revision !== lastRevision) { lastRevision = revision; lastActivity = now; } if (now - lastProgress >= timing.progressIntervalMs) { progress(requestId, "working", startedAt, lastActivity); lastProgress = now; } await bridge.sleep(timing.pollIntervalMs); }
      throw bridge.error("SEND_FAILED", "页面在 60 秒内未确认消息提交，可能仍在加载");
    }
    async function waitForComplete(requestId, baseline, startedAt) {
      let lastActivity = startedAt; let lastRevision = revision; let lastText = (baseline?.innerText || "").trim() || null; let lastNode = baseline; let stableSince = null; let lastProgress = startedAt; let lastPhase = "thinking"; let observed = false; let kind = "thinking"; let snapshot = adapter.activitySnapshot(); let marker = adapter.hasCompletionMarker(baseline); let candidateSince = null; let serialized = null; progress(requestId, "thinking", startedAt, lastActivity);
      while (true) { const now = root.performance.now(); const assistant = adapter.getLastAssistant(); const current = (assistant?.innerText || "").trim(); const nextSnapshot = adapter.activitySnapshot(); const nextMarker = adapter.hasCompletionMarker(assistant); const markerChanged = nextMarker !== marker; const changed = revision !== lastRevision || current !== lastText || nextSnapshot.signature !== snapshot.signature || markerChanged;
        if (changed) { lastActivity = now; lastRevision = revision; observed = true; kind = nextSnapshot.toolCall ? "tool_call" : "working"; } snapshot = nextSnapshot; marker = nextMarker; const nodeChanged = assistant !== lastNode; if (nodeChanged) { lastNode = assistant; candidateSince = null; serialized = null; } if (current !== lastText || nodeChanged) { lastText = current; stableSince = current ? now : null; }
        if (!adapter.isGenerating() && current && assistant) { const next = bridge.serializeMessageToMarkdown(assistant, adapter.serializer); if (markerChanged) { candidateSince = null; serialized = null; } if (serialized !== next) { if (serialized !== null) { lastActivity = now; stableSince = now; observed = true; } serialized = next; candidateSince = now; } else if (candidateSince === null) candidateSince = now; } else { candidateSince = null; serialized = null; }
        const phase = current ? "streaming" : kind === "tool_call" && now - lastActivity <= timing.progressIntervalMs ? "tool_call" : observed && now - lastActivity <= timing.progressIntervalMs ? "working" : "thinking"; if (phase !== lastPhase || now - lastProgress >= timing.progressIntervalMs) { progress(requestId, phase, startedAt, lastActivity); lastPhase = phase; lastProgress = now; }
        if (current && stableSince !== null && now - stableSince >= timing.stableTimeMs && now - lastActivity >= timing.stableTimeMs && candidateSince !== null && now - candidateSince >= timing.completionConfirmationMs && !adapter.isGenerating()) { const final = adapter.getLastAssistant(); const finalText = final && bridge.serializeMessageToMarkdown(final, adapter.serializer); if (finalText && finalText === serialized) return finalText; candidateSince = null; serialized = null; stableSince = null; }
        if (now - lastActivity >= timing.responseIdleTimeoutMs) throw bridge.error("RESPONSE_TIMEOUT", "连续 5 分钟未检测到页面更新，可能仍在思考或页面结构已变化"); await bridge.sleep(timing.pollIntervalMs);
      }
    }
    async function chat(text, requestId) { if (typeof text !== "string" || !text.trim()) throw bridge.error("INPUT_FAILED", "消息不能为空"); const beforeUsers = adapter.getUsers().length; const baseline = adapter.getLastAssistant(); const started = root.performance.now(); progress(requestId, "working", started, started); await sendText(text); await waitForSubmitted(beforeUsers, text, baseline, requestId, started); progress(requestId, "submitted", started, started); return { text: await waitForComplete(requestId, baseline, started) }; }
    function observe() { if (!document.body) return; new MutationObserver((records) => { if (records.some((record) => [...record.addedNodes, ...record.removedNodes, record.target].some((node) => adapter.isActivitySubtree(node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement)))) revision += 1; if (!scheduled) { scheduled = true; root.setTimeout(() => { scheduled = false; history.capture({ prepend: history.active }); }, 100); } }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true }); }
    observe();
    return { async handle(message) { if (message.method === "ping") return { ready: true, provider: provider.id }; if (message.method === "get_messages") return history.collect({ limit: message.limit, full: message.full === true }); if (message.method === "chat") return chat(message.text, message.request_id); throw bridge.error("INTERNAL_ERROR", `未知内容脚本方法：${message.method}`); } };
  };
})(globalThis);
